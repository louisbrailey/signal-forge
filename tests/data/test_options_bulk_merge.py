"""The separate-database-file route and its idempotent merge (D1 §7.7 fix 2).

A ~99-hour backfill must not spend four days writing to the file the paper
probation worker is writing to. It runs against a file-level copy instead, and
this is what makes that safe to rely on:

* a run pointed at another file writes THERE and nowhere else — the property
  that breaks silently if write intent is ever re-derived from the cached
  configured engine;
* the merge is idempotent on each table's natural key, so a re-run inserts
  nothing and says so;
* the bulk run's ``IngestionRun`` survives the merge with a new id, its
  original id, source file and merge time recorded — provenance is the whole
  argument for this dataset, and an id collision would otherwise destroy it;
* ``--dry-run`` measures the merge by doing it and rolling it back;
* the merge refuses rather than guessing: a missing file, the same file twice,
  or a table whose natural key is not unique in the destination.
"""

from __future__ import annotations

import re
import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from signalforge.cli import app
from signalforge.data.adapters import massive_options as mo
from signalforge.data.adapters.massive_options import MassiveOptionsAdapter
from signalforge.data.calendar import sessions as _sessions
from signalforge.data.options_backfill import (
    CycleBackfillCaps,
    backfill_option_cycles,
    coverage_summary,
)
from signalforge.data.options_merge import (
    MERGED_FROM_KEY,
    MergeError,
    merge_options_from_file,
)
from signalforge.db.models import IngestionRun, Instrument, OHLCVDaily, OptionAggregateDaily
from signalforge.db.session import external_session_scope, get_engine
from signalforge.domain import LatencyCategory
from signalforge.worker_lock import acquire_worker_lock

WINDOW_START = date(2024, 1, 2)
WINDOW_END = date(2024, 6, 28)


@pytest.fixture(autouse=True)
def _no_real_sleeping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mo.MassiveOptionsAdapter, "_sleep", lambda self, _s: None)


@pytest.fixture
def bulk_db(tmp_path: Path, db_url: str) -> Path:
    """The bulk file, made the way the runbook says to make it: a file-level
    copy of the live database, taken after a WAL checkpoint so nothing sitting
    in the write-ahead log is left behind by the copy."""
    from sqlalchemy import text

    live = Path(get_engine().url.database or "")
    with get_engine().connect() as conn:
        conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
        assert conn.scalar(text("SELECT count(*) FROM ingestion_run")) == 0
    path = tmp_path / "bulk.sqlite"
    shutil.copy2(live, path)
    return path


_AGG_RE = re.compile(r"/v2/aggs/ticker/(?P<tk>[^/]+)/range/1/day/(?P<a>[\d-]+)/(?P<b>[\d-]+)")
_EXP_RE = re.compile(r"O:[A-Z]+(?P<yy>\d\d)(?P<mm>\d\d)(?P<dd>\d\d)[CP]")


def _client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/v3/reference/options/contracts" in url:
            exp = re.search(r"expiration_date\.gte=([\d-]+)", url)
            assert exp
            expiry = date.fromisoformat(exp.group(1))
            rows = []
            k = 340.0
            while k <= 460.0 + 1e-9:
                for cp, right in (("C", "call"), ("P", "put")):
                    rows.append(
                        {
                            "ticker": f"O:SPY{expiry:%y%m%d}{cp}{round(k * 1000):08d}",
                            "contract_type": right,
                            "strike_price": round(k, 2),
                            "expiration_date": expiry.isoformat(),
                            "exercise_style": "american",
                            "shares_per_contract": 100,
                        }
                    )
                k += 1.0
            return httpx.Response(200, json={"status": "OK", "results": rows})
        m = _AGG_RE.search(url)
        if m:
            e = _EXP_RE.search(m["tk"])
            assert e
            expiry = date(2000 + int(e["yy"]), int(e["mm"]), int(e["dd"]))
            a, b = date.fromisoformat(m["a"]), date.fromisoformat(m["b"])
            out = [
                {
                    "t": int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() * 1000),
                    "o": 1.0,
                    "h": 1.5,
                    "l": 0.8,
                    "c": 1.2,
                    "v": 10,
                    "vw": 1.1,
                    "n": 3,
                }
                for d in _sessions(a, min(b, expiry))
            ]
            return httpx.Response(200, json={"status": "OK", "results": out})
        return httpx.Response(404, json={})

    return httpx.Client(transport=httpx.MockTransport(handler))


def _seed_equity(session: Session, level: float = 400.0) -> None:
    inst = Instrument(symbol="SPY", name="SPY", instrument_type="etf", exchange="ARCX")
    session.add(inst)
    session.flush()
    for d in _sessions(WINDOW_START - timedelta(days=120), WINDOW_END):
        session.add(
            OHLCVDaily(
                instrument_id=inst.id,
                session_date=d,
                open=level,
                high=level,
                low=level,
                close=level,
                volume=1_000_000,
                source="massive",
                latency_category=LatencyCategory.HISTORICAL,
                ingested_at=datetime.now(UTC),
                is_simulated=False,
            )
        )
    session.commit()


def _refuse_network(*_a: object, **_k: object) -> None:
    raise AssertionError("this command must not issue a provider request")


def _run_bulk(bulk_db: Path) -> int:
    """A complete cycle backfill INTO the bulk file. Returns its run id."""
    with external_session_scope(bulk_db, write=True) as bulk:
        _seed_equity(bulk)
        run = backfill_option_cycles(
            bulk,
            MassiveOptionsAdapter("k", client=_client()),
            ["SPY"],
            caps=CycleBackfillCaps(
                window_start=WINDOW_START, window_end=WINDOW_END, max_total_bars=1_000_000
            ),
            options_config_hash="bulk-hash",
        )
        cov = coverage_summary(run)
        assert cov.cycles_covered == cov.cycles_total > 0
        assert run.bars_written > 0
        return int(run.id)


# --------------------------------------------------------------------------- #
def test_a_run_pointed_at_another_file_writes_there_and_not_here(
    bulk_db: Path, session: Session
) -> None:
    """The whole point of the separate-file route. If write intent were ever
    re-derived from the cached configured engine, the bulk run's writes would
    land in the live database — silently, and for four days."""
    _run_bulk(bulk_db)

    assert session.scalar(select(func.count()).select_from(OptionAggregateDaily)) == 0
    assert session.scalar(select(func.count()).select_from(IngestionRun)) == 0
    with external_session_scope(bulk_db) as bulk:
        assert (bulk.scalar(select(func.count()).select_from(OptionAggregateDaily)) or 0) > 0


def test_the_merge_moves_the_option_tables_and_rekeys_the_run(
    bulk_db: Path, session: Session
) -> None:
    source_run_id = _run_bulk(bulk_db)
    result = merge_options_from_file(get_engine(), bulk_db)

    assert result.rows_inserted > 0
    by_table = {t.table: t for t in result.tables}
    assert by_table["option_aggregate_daily"].inserted > 0
    assert by_table["option_contract"].inserted > 0
    assert all(t.inserted == t.source_rows for t in result.tables)

    session.expunge_all()
    with external_session_scope(bulk_db) as bulk:
        there = bulk.scalar(select(func.count()).select_from(OptionAggregateDaily)) or 0
    here = session.scalar(select(func.count()).select_from(OptionAggregateDaily)) or 0
    assert here == there > 0

    assert len(result.runs_merged) == 1
    src_id, new_id = result.runs_merged[0]
    assert src_id == source_run_id
    merged = session.get(IngestionRun, new_id)
    assert merged is not None
    marker = merged.gaps_json[MERGED_FROM_KEY]
    assert marker["source_run_id"] == source_run_id
    assert marker["source_db"] == str(bulk_db.resolve())
    assert "merged from" in merged.notes
    # the coverage summary still reads off the merged row
    assert coverage_summary(merged).cycles_covered > 0


def test_merging_twice_inserts_nothing_the_second_time(bulk_db: Path, session: Session) -> None:
    """Idempotent on the natural keys — and it says so rather than looking like
    a merge that did nothing because it failed."""
    _run_bulk(bulk_db)
    first = merge_options_from_file(get_engine(), bulk_db)
    second = merge_options_from_file(get_engine(), bulk_db)

    assert second.rows_inserted == 0
    assert second.rows_already_present == first.rows_inserted
    assert second.runs_merged == ()
    assert second.runs_already_merged == (first.runs_merged[0][0],)

    session.expunge_all()
    with external_session_scope(bulk_db) as bulk:
        there = bulk.scalar(select(func.count()).select_from(OptionAggregateDaily)) or 0
    here = session.scalar(select(func.count()).select_from(OptionAggregateDaily)) or 0
    runs = session.scalar(select(func.count()).select_from(IngestionRun)) or 0
    assert here == there  # not doubled
    assert runs == 1  # and the provenance row was not duplicated either


def test_a_dry_run_measures_the_merge_and_writes_nothing(bulk_db: Path, session: Session) -> None:
    _run_bulk(bulk_db)
    planned = merge_options_from_file(get_engine(), bulk_db, dry_run=True)
    assert planned.dry_run and planned.rows_inserted > 0

    session.expunge_all()
    assert session.scalar(select(func.count()).select_from(OptionAggregateDaily)) == 0
    assert session.scalar(select(func.count()).select_from(IngestionRun)) == 0

    real = merge_options_from_file(get_engine(), bulk_db)
    assert real.rows_inserted == planned.rows_inserted  # measured, not estimated


def test_the_merge_refuses_rather_than_guessing(bulk_db: Path, db_url: str) -> None:
    with pytest.raises(MergeError, match="does not exist"):
        merge_options_from_file(get_engine(), bulk_db.parent / "nope.sqlite")
    here = Path(get_engine().url.database or "")
    with pytest.raises(MergeError, match="same file"):
        merge_options_from_file(get_engine(), here)


def test_an_absent_bulk_file_is_refused_before_a_multi_day_run_starts(tmp_path: Path) -> None:
    """SQLite would happily create an empty file; a run against one would take
    days and exclude every cycle for want of an equity reference price."""
    with (
        pytest.raises(FileNotFoundError, match="FILE-LEVEL COPY"),
        external_session_scope(tmp_path / "not-there.sqlite", write=True),
    ):
        pass
    assert not (tmp_path / "not-there.sqlite").exists()


def test_tables_without_a_unique_natural_key_are_named_not_merged_blindly() -> None:
    """``INSERT OR IGNORE`` is only idempotent against a unique index. The
    tables that have none are reported by name with the reason, rather than
    duplicated on every re-merge."""
    from signalforge.data.options_merge import NOT_MERGED

    named = dict(NOT_MERGED)
    assert "option_quote_snapshot" in named and "unique" in named["option_quote_snapshot"]
    assert "corporate_action" in named
    assert "ohlcv_daily" in named and "COPY" in named["ohlcv_daily"]


def test_the_merge_command_reports_counts_and_names_what_it_did_not_merge(
    bulk_db: Path, session: Session
) -> None:
    _run_bulk(bulk_db)
    result = CliRunner().invoke(app, ["options", "merge", "--from", str(bulk_db), "--dry-run"])
    assert result.exit_code == 0, result.output
    out = result.output
    assert "DRY RUN — rolled back" in out
    assert "option_aggregate_daily:" in out and "inserted" in out
    assert "key option_ticker+session_date+source" in out
    assert "ingestion_run #" in out
    assert "not merged — ohlcv_daily" in out

    session.expunge_all()
    assert session.scalar(select(func.count()).select_from(OptionAggregateDaily)) == 0


def test_the_cycle_backfill_plans_against_the_bulk_file_it_is_pointed_at(
    bulk_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--to-database`` reaches the session layer: the plan is rendered from a
    session opened against that file, and a file that is not there is refused
    before a multi-day run starts rather than created empty."""
    monkeypatch.setattr(httpx, "get", _refuse_network)
    ok = CliRunner().invoke(
        app,
        [
            "options",
            "cycle-backfill",
            "--underlyings",
            "SPY",
            "--to-database",
            str(bulk_db),
            "--dry-run",
        ],
    )
    assert ok.exit_code == 0, ok.output
    assert f"destination: {bulk_db}" in ok.output

    missing = CliRunner().invoke(
        app,
        [
            "options",
            "cycle-backfill",
            "--underlyings",
            "SPY",
            "--dry-run",
            "--to-database",
            str(bulk_db.parent / "absent.sqlite"),
        ],
    )
    assert missing.exit_code == 1
    assert "FILE-LEVEL COPY" in missing.output
    assert not (bulk_db.parent / "absent.sqlite").exists()


def test_the_merge_command_refuses_while_the_worker_holds_its_lock(bulk_db: Path) -> None:
    """A bulk merge holds the write lock for the whole pass — far longer than
    the 5 s a worker job waits before failing."""
    _run_bulk(bulk_db)
    lock = acquire_worker_lock()
    try:
        result = CliRunner().invoke(app, ["options", "merge", "--from", str(bulk_db)])
        assert result.exit_code == 1
        assert "stop the worker first" in result.output
        forced = CliRunner().invoke(
            app, ["options", "merge", "--from", str(bulk_db), "--allow-worker-running"]
        )
        assert forced.exit_code == 0, forced.output
    finally:
        lock.release()


def test_the_idempotency_guard_refuses_a_destination_missing_its_unique_key() -> None:
    """Refuse, rather than silently duplicating a million rows on the second
    merge, if a migration ever drops the key the merge rests on. The guard is
    checked BEFORE anything is written, which is why it is a refusal and not a
    rollback."""
    import sqlite3

    from signalforge.data.options_merge import _assert_idempotent

    key = ("option_ticker", "source")
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute("CREATE TABLE option_contract (option_ticker TEXT, source TEXT)")
    with pytest.raises(MergeError, match="INSERT OR IGNORE would not be idempotent"):
        _assert_idempotent(cur, "option_contract", key)

    cur.execute("CREATE UNIQUE INDEX u_oc ON option_contract(option_ticker, source)")
    _assert_idempotent(cur, "option_contract", key)  # the key is there: no refusal
    conn.close()
