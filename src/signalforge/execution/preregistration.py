"""The pre-registered ``execution_limits`` row, as code (D6 ADR §7b rule 1).

``execution_limits`` blocks opening when there is no active, parseable row —
"no limits row" is not "no limits" — and until now **nothing in the tree could
create one**. The row could only be inserted by hand, which is the shape §7b
exists to prevent: a row typed at a SQL prompt is a row nobody pre-registered.

This module is the missing constructor, and it is deliberately not a free-form
one. There is exactly one way to create an ``execution_limits`` row:

    signalforge execution limits set --from-preregistration <doc id> --yes

and the values come from :data:`PREREGISTERED_LIMIT_ROWS` — never from CLI
options, never from a settings form, never from a default. An operator who wants
different numbers writes a **new pre-registration document with a new id** (§4 of
the v1 document, rules 1-5), adds it here, and supersedes; there is no path in
which a changed value is armed under an unchanged id.

**Three independent statements of the same row, pinned to each other by tests.**
The mapping below is the one the code uses. ``docs/PREREGISTRATION_*.md`` is the
one a reviewer reads. ``tests/execution/conftest.py::LIMIT_GRID_CENTRES`` and
``scripts/execution_drills.py::LIMIT_GRID_CENTRES`` are the ones the suite and
the drill harness assert against. :func:`resolve_preregistered_limits` compares
the first two **at run time**, on the file actually on disk, and refuses rather
than writing a row the document does not state;
``tests/execution/test_phase_v_drills.py`` pins all four together.

Nothing here arms anything, enables anything, or contacts anything. Creating the
limits row is necessary for opening and nowhere near sufficient: with no
unexpired ``armed_strategy`` row, zero orders can be submitted.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from datetime import datetime

    from sqlalchemy.orm import Session

    from signalforge.db.models import ExecutionLimits

__all__ = [
    "PREREGISTERED_LIMIT_ROWS",
    "PREREGISTRATION_EXECUTION_LIMITS_V1",
    "PreregistrationRefused",
    "active_limits_rows",
    "documented_limit_values",
    "preregistration_document_path",
    "resolve_preregistered_limits",
    "set_limits_from_preregistration",
    "supersede_note",
]

PREREGISTRATION_EXECUTION_LIMITS_V1 = "PREREGISTRATION_execution_limits_v1"

#: The complete row, per pre-registration document id. The COMPLETE row: a
#: column absent from here would be a column nobody chose, and
#: :func:`set_limits_from_preregistration` refuses a mapping that does not name
#: every ``execution_limits`` column it is about to write.
PREREGISTERED_LIMIT_ROWS: dict[str, dict[str, Any]] = {
    PREREGISTRATION_EXECUTION_LIMITS_V1: {
        # -- capital limits (decision 4 + map §3.2): both forms, tighter binds --
        "max_orders_per_day": 10,
        "max_order_notional_usd": 1_000.0,
        "max_account_exposure_pct": 40.0,
        "per_structure_max_loss_usd": 250.0,
        "per_structure_max_loss_pct": 0.5,
        "aggregate_open_max_loss_usd": 1_000.0,
        "aggregate_open_max_loss_pct": 2.0,
        "collateral_cap_usd": 5_000.0,
        "collateral_cap_pct": 30.0,
        "max_net_delta_notional_usd": 10_000.0,
        "max_net_vega_per_volpt_usd": 50.0,
        # -- the seven timing parameters this ADR invented (§7b rule 2) --------
        "cycle_interval_s": 30,
        "max_intent_age_minutes": 15,
        "max_reconciliation_age_s": 120,
        "execution_stale_after_s": 90,
        "drain_timeout_s": 30,
        "no_submit_after_open_minutes": 15,
        "no_submit_before_close_minutes": 15,
        # -- reconciliation tolerance and the regulatory counters -------------
        "buying_power_tolerance_usd": 1.0,
        "buying_power_tolerance_pct": 0.1,
        "round_trips_per_5_sessions_max": 3,
        "pdt_equity_threshold_usd": 25_000.0,
        # -- traceability -----------------------------------------------------
        "preregistration_doc_id": PREREGISTRATION_EXECUTION_LIMITS_V1,
    }
}


class PreregistrationRefused(RuntimeError):
    """The limits row was not written. The message names the refusing condition."""


def _docs_root() -> Path:
    """The repository's ``docs/`` tree — resolved exactly as
    ``arming._preregistration_exists`` resolves it, so the two checks can never
    disagree about which tree is being searched."""
    return Path(__file__).resolve().parents[3] / "docs"


def preregistration_document_path(doc_id: str) -> Path | None:
    """The ``docs/**/<doc_id>.md`` file, or ``None``.

    The same stem match the arming ceremony's S3 check performs. A document that
    is not there is a refusal, not a warning: §7b rule 1 makes the document a
    hard precondition, and a row written without one is a row whose numbers
    nobody fixed in advance.
    """
    if not doc_id:
        return None
    root = _docs_root()
    if not root.exists():  # pragma: no cover - only in a stripped install
        return None
    stem = doc_id.removesuffix(".md")
    matches = sorted(p for p in root.rglob("*.md") if p.stem == stem)
    return matches[0] if matches else None


_COLUMN_CELL = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)`")
_FIRST_BOLD = re.compile(r"\*\*(.+?)\*\*")


def documented_limit_values(text: str, columns: set[str]) -> dict[str, str]:
    """Parse ``| `column` | unit | **value** | ...`` rows out of a document.

    The FIRST bold token in a row is the value; a rationale column may be bold
    too (three of them are, deliberately and loudly) and must not be mistaken
    for one. Rows whose first cell is not a bare backticked column name — the
    "which form binds" worked example, the provenance table — are skipped, which
    is why the column set is passed in rather than inferred.

    Identical in behaviour to the parser
    ``tests/execution/test_phase_v_drills.py`` already applies to the same file;
    it lives here as well because the CLI must be able to refuse **at write
    time**, on the document actually on disk, and not only in CI.
    """
    out: dict[str, str] = {}
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells:
            continue
        head = _COLUMN_CELL.fullmatch(cells[0])
        if head is None or head.group(1) not in columns:
            continue
        bold = _FIRST_BOLD.search(line)
        if bold is None:
            continue
        out[head.group(1)] = bold.group(1).strip().strip("`")
    return out


def _as_float(stated: str) -> float:
    return float(stated.replace(",", "").lstrip("$"))


def resolve_preregistered_limits(doc_id: str) -> tuple[dict[str, Any], Path]:
    """The row for ``doc_id``, checked against the document on disk.

    Refuses — never falls back, never defaults — when:

    * no row is registered here for that id (a document alone is not a row: the
      values have to have been read and transcribed by someone);
    * no ``docs/**/<doc_id>.md`` exists (§7b rule 1 / ceremony check S3);
    * the document does not state every column this row would write;
    * any stated value differs from the one the code would use.

    The last two are the ones that matter in practice. A value edited in the
    document and not here — or here and not there — is the exact drift that
    makes a pre-registration a story rather than a control, and it stops the
    write rather than being reported afterwards.
    """
    values = PREREGISTERED_LIMIT_ROWS.get(doc_id)
    if values is None:
        known = ", ".join(sorted(PREREGISTERED_LIMIT_ROWS)) or "(none)"
        raise PreregistrationRefused(
            f"no pre-registered execution_limits row is registered for {doc_id!r}. "
            f"Registered ids: {known}. A new document needs a new entry in "
            "signalforge.execution.preregistration.PREREGISTERED_LIMIT_ROWS — writing the "
            "document alone does not make its numbers the ones the code uses."
        )
    path = preregistration_document_path(doc_id)
    if path is None:
        raise PreregistrationRefused(
            f"no pre-registration document named {doc_id!r} exists under docs/ — §7b rule 1 "
            "makes the document a hard precondition of the row, and the arming ceremony's S3 "
            "check looks for exactly this file"
        )

    documented = documented_limit_values(path.read_text(encoding="utf-8"), set(values))
    missing = sorted(set(values) - set(documented))
    if missing:
        raise PreregistrationRefused(
            f"{path.name} does not pre-register these execution_limits columns: {missing}. "
            "§7b rule 1 requires the COMPLETE row; a column absent from the document is a "
            "column nobody chose."
        )
    mismatches: list[str] = []
    for column, expected in sorted(values.items()):
        stated = documented[column]
        if isinstance(expected, str):
            if stated != expected:
                mismatches.append(f"{column}: document says {stated!r}, code uses {expected!r}")
            continue
        try:
            if _as_float(stated) != float(expected):
                mismatches.append(f"{column}: document says {stated}, code uses {expected}")
        except ValueError:
            mismatches.append(f"{column}: document value {stated!r} is not a number")
    if mismatches:
        raise PreregistrationRefused(
            f"{path.name} and the code disagree about the pre-registered row:\n  "
            + "\n  ".join(mismatches)
            + "\nNothing was written. Changing a value requires a NEW document with a NEW id "
            "(§4 rule 1), not an edit to this one."
        )
    return dict(values), path


def supersede_note() -> str:
    """The one consequence of superseding that an operator must read first."""
    return (
        "Superseding RESETS the decision-10 evidence counter for every strategy armed under "
        "the new row: >= 20 closed paper trades must be accumulated under the limits row "
        "actually in force (§7b rule 3), and arming.evaluate_evidence counts only from the "
        "active row's created_at. This is the expensive consequence of a change, and it is "
        "meant to be."
    )


def active_limits_rows(session: Session) -> list[ExecutionLimits]:
    """Every row with ``superseded_at IS NULL``, newest first.

    Plural on purpose: ``load_active_limits`` takes the newest and a second
    active row would silently shadow the first, so the ceremony reports what it
    found rather than assuming there is at most one.
    """
    from sqlalchemy import select

    from signalforge.db.models import ExecutionLimits

    return list(
        session.scalars(
            select(ExecutionLimits)
            .where(ExecutionLimits.superseded_at.is_(None))
            .order_by(ExecutionLimits.created_at.desc(), ExecutionLimits.id.desc())
        )
    )


def set_limits_from_preregistration(
    session: Session,
    *,
    doc_id: str,
    now: datetime,
    actor: str = "local-user",
    supersede: bool = False,
) -> tuple[ExecutionLimits, tuple[ExecutionLimits, ...]]:
    """Create the active ``execution_limits`` row from ``doc_id``.

    Returns the new row and the rows it superseded. Rows are **never edited**
    (§7 / §7b rule 1): an existing active row is refused unless ``supersede`` is
    asked for explicitly, and superseding stamps ``superseded_at`` on the old row
    and inserts a new one.

    The caller owns the transaction and the audit line. This function writes no
    ``execution_event``: the limits row is not an order-lifecycle event, and the
    append-only execution spine must not gain rows that are not about orders.
    """
    from signalforge.db.models import ExecutionLimits
    from signalforge.execution.limits import limit_set_from_row

    values, _path = resolve_preregistered_limits(doc_id)
    existing = tuple(active_limits_rows(session))
    if existing and not supersede:
        ids = ", ".join(str(row.id) for row in existing)
        raise PreregistrationRefused(
            f"an active execution_limits row already exists (id={ids}); rows are versioned by "
            "supersession and never edited. Re-run with --supersede to deactivate it and "
            "insert a new one. " + supersede_note()
        )

    row = ExecutionLimits(created_at=now, created_by=actor, **values)
    session.add(row)
    session.flush()
    # Parse it back through the same invariants ``load_active_limits`` applies,
    # so a row that would read as None ("no limits row", which blocks opening)
    # can never be left behind by a command that reported success.
    try:
        limit_set_from_row(row)
    except (ValueError, TypeError) as exc:
        raise PreregistrationRefused(
            f"the pre-registered row for {doc_id!r} does not satisfy LimitSet's own invariants "
            f"({exc}); load_active_limits would read it as None, which BLOCKS opening. Nothing "
            "was written."
        ) from exc

    for old in existing:
        old.superseded_at = now
    session.flush()
    return row, existing
