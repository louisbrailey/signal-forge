"""Idempotent merge of a bulk options database file into the live one (D1 §7.7).

The long options backfill (~29,000 requests, ~99 hours at the only pacing this
repo documents) must not spend four days writing to the file the paper
probation worker is writing to. It runs instead against a **file-level copy of
the live database**, taken with the worker stopped, and this module merges the
option tables back in one short pass afterwards.

What makes the merge safe to re-run — and safe to interrupt:

* every table is copied with ``INSERT OR IGNORE`` **on its natural key**, and
  the destination is checked to actually HAVE a unique index over that key
  before a single row is written. Without that check a schema drift would turn
  a second merge into silent duplication, which is exactly the class of failure
  (silent, plausible-looking, discovered late) this program exists to avoid;
* the integer primary keys are never copied. They collide by construction — two
  databases both counting from 1 — and carrying them would either fail or
  overwrite unrelated rows;
* ``ingestion_run`` rows are re-keyed, not copied: each merged run gets a new
  id with its **original** id, the source file and the merge time recorded on
  it, because the whole provenance argument for this dataset depends on that
  row surviving the merge and staying traceable to the file it was built in;
* ``--dry-run`` performs the identical work inside a transaction and rolls it
  back, so the counts it reports are measured rather than estimated.

Deliberately NOT merged, each for a reason:

* ``instrument`` / ``ohlcv_daily`` — the bulk file is a copy of the live one,
  so its equity rows came FROM the destination. Copying them back is at best a
  no-op over a million rows and at worst re-introduces a series the live
  database has since corrected.
* ``option_quote_snapshot`` and ``corporate_action`` — neither has a unique
  natural key in the schema, so ``INSERT OR IGNORE`` could not be idempotent
  over them. They are reported as skipped by name rather than merged blindly.

Counts and identities only: this module never reads a price, an IV or a volume
value, and never returns one. The COVERAGE-SUMMARY-ONLY rule (D1 §10) holds
through the merge as it does through the backfill.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine

from signalforge.db.models import (
    DividendEvent,
    IngestionRun,
    OptionAggregateDaily,
    OptionContract,
    SplitEvent,
)
from signalforge.observability import get_logger

_log = get_logger("options.merge")

_ATTACH_ALIAS = "bulk"
MERGED_FROM_KEY = "__merged_from__"
# Which ingestion runs travel with the option data. A run of any other kind in
# the bulk file describes the *copy*, not the backfill, and must not be
# duplicated into the live provenance chain.
RUN_KIND_PREFIX = "options"

# Tables that are merged, each with the natural key its idempotency rests on.
# The key is verified against the destination schema before anything is copied.
MERGE_TABLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (OptionContract.__tablename__, ("option_ticker", "source")),
    (OptionAggregateDaily.__tablename__, ("option_ticker", "session_date", "source")),
    (DividendEvent.__tablename__, ("symbol", "ex_dividend_date", "source")),
    (SplitEvent.__tablename__, ("symbol", "execution_date", "source")),
)
NOT_MERGED: tuple[tuple[str, str], ...] = (
    ("option_quote_snapshot", "no unique natural key in the schema — a re-merge would duplicate"),
    ("corporate_action", "no unique natural key in the schema — a re-merge would duplicate"),
    ("ohlcv_daily", "the bulk file is a COPY of the live one; its equity bars came from here"),
    ("instrument", "the bulk file is a COPY of the live one; its instruments came from here"),
)

_MODELS = {
    OptionContract.__tablename__: OptionContract,
    OptionAggregateDaily.__tablename__: OptionAggregateDaily,
    DividendEvent.__tablename__: DividendEvent,
    SplitEvent.__tablename__: SplitEvent,
}


class MergeError(RuntimeError):
    """The merge refused to run. Never raised after rows have been committed."""


@dataclass(frozen=True, slots=True)
class TableMerge:
    table: str
    natural_key: tuple[str, ...]
    source_rows: int
    inserted: int

    @property
    def already_present(self) -> int:
        return max(0, self.source_rows - self.inserted)


@dataclass(frozen=True, slots=True)
class MergeResult:
    """Counts and identities only — what moved, what was already there."""

    source_path: str
    destination_url: str
    dry_run: bool
    tables: tuple[TableMerge, ...]
    runs_merged: tuple[tuple[int, int], ...]  # (source run id, destination run id)
    runs_already_merged: tuple[int, ...]  # source run ids a previous merge brought over
    not_merged: tuple[tuple[str, str], ...] = NOT_MERGED

    @property
    def rows_inserted(self) -> int:
        return sum(t.inserted for t in self.tables)

    @property
    def rows_already_present(self) -> int:
        return sum(t.already_present for t in self.tables)


def _table(name: str) -> str:
    """The only way a table name reaches an SQL string in this module.

    Table and column identifiers cannot be bound as parameters, so the
    statements below interpolate them. Every identifier therefore comes from
    :data:`MERGE_TABLES` or from the ORM's own metadata, and this allowlist is
    what makes that checkable rather than asserted — it is why the ``S608``
    suppressions below are suppressions and not exceptions.
    """
    if name not in _MODELS:
        raise MergeError(f"{name!r} is not a mergeable options table")
    return name


def _columns(table: str) -> tuple[str, ...]:
    """Every column except the integer primary key, from the ORM metadata.

    Taken from the model rather than written out here so a later migration
    cannot leave this module quietly copying a subset of each row.
    """
    model = _MODELS[_table(table)]
    return tuple(c.name for c in model.__table__.columns if c.name != "id")


def _unique_indexes(cur: Any, table: str) -> list[tuple[str, ...]]:
    """Unique indexes on the DESTINATION copy of ``table`` (schema-qualified:
    the source is attached, and ``main.`` is the half whose constraints decide
    whether ``INSERT OR IGNORE`` is idempotent)."""
    out: list[tuple[str, ...]] = []
    for row in cur.execute(f"PRAGMA main.index_list('{table}')").fetchall():
        name, unique = row[1], row[2]
        if not unique:
            continue
        cols = tuple(r[2] for r in cur.execute(f"PRAGMA main.index_info('{name}')").fetchall())
        out.append(cols)
    return out


def _assert_idempotent(cur: Any, table: str, key: tuple[str, ...]) -> None:
    found = _unique_indexes(cur, table)
    if not any(set(cols) == set(key) for cols in found):
        raise MergeError(
            f"{table} has no UNIQUE index over {key} in the destination database "
            f"(found {found or 'none'}). INSERT OR IGNORE would not be idempotent, so a "
            "second merge would duplicate every row. Refusing to merge."
        )


def _table_counts(cur: Any, table: str) -> int:
    sql = f"SELECT count(*) FROM {_ATTACH_ALIAS}.{_table(table)}"  # noqa: S608 - allowlisted name
    return int(cur.execute(sql).fetchone()[0])


def _destination_merged_run_ids(cur: Any, source_key: str) -> set[int]:
    """Source run ids a previous merge already brought into the destination."""
    seen: set[int] = set()
    rows = cur.execute(
        "SELECT gaps_json FROM main.ingestion_run WHERE kind LIKE ?", (f"{RUN_KIND_PREFIX}%",)
    ).fetchall()
    for (blob,) in rows:
        if not blob:
            continue
        try:
            payload = json.loads(blob)
        except (TypeError, ValueError):
            continue
        marker = payload.get(MERGED_FROM_KEY) if isinstance(payload, dict) else None
        if isinstance(marker, dict) and str(marker.get("source_db", "")) == source_key:
            try:
                seen.add(int(marker.get("source_run_id", -1)))
            except (TypeError, ValueError):
                continue
    return seen


def _merge_runs(
    cur: Any, source_key: str, merged_at: str
) -> tuple[list[tuple[int, int]], list[int]]:
    cols = tuple(c.name for c in IngestionRun.__table__.columns if c.name != "id")
    names = ", ".join(cols)
    already = _destination_merged_run_ids(cur, source_key)
    # S608 below: identifiers cannot be bound as parameters, and every one
    # interpolated here is read from the ORM's own metadata. The one value is bound.
    select_sql = (
        f"SELECT id, {names} FROM {_ATTACH_ALIAS}.ingestion_run WHERE kind LIKE ?"  # noqa: S608
    )
    rows = cur.execute(select_sql, (f"{RUN_KIND_PREFIX}%",)).fetchall()
    merged: list[tuple[int, int]] = []
    skipped: list[int] = []
    for row in rows:
        source_id = int(row[0])
        if source_id in already:
            skipped.append(source_id)
            continue
        values = dict(zip(cols, row[1:], strict=True))
        try:
            gaps = json.loads(values.get("gaps_json") or "{}")
        except (TypeError, ValueError):
            gaps = {}
        if not isinstance(gaps, dict):
            gaps = {"_unparsed": True}
        gaps[MERGED_FROM_KEY] = {
            "source_run_id": source_id,
            "source_db": source_key,
            "merged_at": merged_at,
        }
        values["gaps_json"] = json.dumps(gaps)
        note = f"merged from {source_key} (source ingestion_run #{source_id}) at {merged_at}"
        values["notes"] = f"{values.get('notes') or ''}; {note}".lstrip("; ")
        placeholders = ", ".join("?" for _ in cols)
        insert_sql = (
            f"INSERT INTO main.ingestion_run ({names}) VALUES ({placeholders})"  # noqa: S608
        )
        cur.execute(insert_sql, tuple(values[c] for c in cols))
        merged.append((source_id, int(cur.lastrowid)))
    return merged, skipped


def merge_options_from_file(
    engine: Engine, source_path: str | Path, *, dry_run: bool = False
) -> MergeResult:
    """Merge the option tables of ``source_path`` into ``engine``'s database.

    One transaction, ``INSERT OR IGNORE`` on the natural keys, counts reported.
    ``dry_run`` does the identical work and rolls it back, so its counts are the
    counts a real merge would produce rather than a guess at them.
    """
    src = Path(source_path).expanduser()
    if not src.is_file():
        raise MergeError(f"{src} does not exist")
    if not engine.url.get_backend_name().startswith("sqlite"):
        raise MergeError(
            "the bulk-file merge is SQLite-only: it ATTACHes the source file to the "
            "destination connection. On another backend, load the bulk run's rows with the "
            "backend's own bulk tooling instead."
        )
    dest_path = Path(engine.url.database or "")
    if dest_path.resolve() == src.resolve():
        raise MergeError(f"source and destination are the same file ({src})")

    source_key = str(src.resolve())
    merged_at = datetime.now(UTC).isoformat()
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute(f"ATTACH DATABASE ? AS {_ATTACH_ALIAS}", (source_key,))
        try:
            for table, key in MERGE_TABLES:
                _assert_idempotent(cur, table, key)
            source_rows = {t: _table_counts(cur, t) for t, _k in MERGE_TABLES}
            cur.execute("BEGIN IMMEDIATE")
            try:
                tables: list[TableMerge] = []
                for table, key in MERGE_TABLES:
                    name = _table(table)
                    cols = ", ".join(_columns(table))
                    copy_sql = (
                        f"INSERT OR IGNORE INTO main.{name} ({cols}) "  # noqa: S608
                        f"SELECT {cols} FROM {_ATTACH_ALIAS}.{name}"
                    )
                    cur.execute(copy_sql)
                    tables.append(
                        TableMerge(
                            table=table,
                            natural_key=key,
                            source_rows=source_rows[table],
                            inserted=max(0, int(cur.rowcount)),
                        )
                    )
                merged, already = _merge_runs(cur, source_key, merged_at)
            except sqlite3.Error as exc:  # pragma: no cover - schema drift
                cur.execute("ROLLBACK")
                raise MergeError(
                    f"merge failed and was rolled back — nothing was written: {exc}"
                ) from exc
            cur.execute("ROLLBACK" if dry_run else "COMMIT")
        finally:
            cur.execute(f"DETACH DATABASE {_ATTACH_ALIAS}")
            cur.close()
    finally:
        raw.close()

    result = MergeResult(
        source_path=source_key,
        destination_url=str(engine.url.render_as_string(hide_password=True)),
        dry_run=dry_run,
        tables=tuple(tables),
        runs_merged=tuple(merged),
        runs_already_merged=tuple(already),
    )
    _log.info(
        "options.merge.done",
        source=source_key,
        dry_run=dry_run,
        rows_inserted=result.rows_inserted,
        rows_already_present=result.rows_already_present,
        runs_merged=len(result.runs_merged),
    )
    return result
