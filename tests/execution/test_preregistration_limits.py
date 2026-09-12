"""D6 §7b rule 1 — the ``execution_limits`` row has exactly one constructor.

Before this, nothing in the tree could create the row at all: ``may_open``'s L0
blocked on its absence ("no limits row" is not "no limits") and the only way to
get one was a SQL prompt — which is the shape §7b exists to prevent, because a
row typed by hand is a row nobody pre-registered.

The tests below are about the refusals, not the creation. Every one of them is a
way the row could come into existence carrying a number no document states.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from signalforge.execution import preregistration as prereg
from signalforge.execution.limits import load_active_limits
from tests.execution.conftest import LIMIT_GRID_CENTRES

NOW = datetime(2026, 9, 12, 15, 0, tzinfo=UTC)
V1 = prereg.PREREGISTRATION_EXECUTION_LIMITS_V1


# ---------------------------------------------------------------------------
# The source of truth, pinned to the document and to the other two copies
# ---------------------------------------------------------------------------


def test_the_src_row_equals_the_test_fixtures_grid_centres() -> None:
    """``tests/execution/conftest.py::LIMIT_GRID_CENTRES`` IS the pre-registered
    row, and the code that writes the row must use the same numbers."""
    assert prereg.PREREGISTERED_LIMIT_ROWS[V1] == LIMIT_GRID_CENTRES


def test_the_src_row_equals_the_drill_runners_grid_centres() -> None:
    from scripts.execution_drills import LIMIT_GRID_CENTRES as SCRIPT_GRID_CENTRES

    assert prereg.PREREGISTERED_LIMIT_ROWS[V1] == SCRIPT_GRID_CENTRES


def test_the_src_row_equals_the_document_on_disk() -> None:
    """The run-time check, run here too: the parser and the comparison are the
    ones the CLI applies, on the real file."""
    values, path = prereg.resolve_preregistered_limits(V1)

    assert values == prereg.PREREGISTERED_LIMIT_ROWS[V1]
    assert path.name == "PREREGISTRATION_execution_limits_v1.md"


def test_every_execution_limits_column_is_pre_registered() -> None:
    """A column absent from the mapping is a column nobody chose — and the row
    could not be written without it anyway."""
    from signalforge.db.models import ExecutionLimits

    bookkeeping = {"id", "created_at", "created_by", "superseded_at"}
    columns = {c.name for c in ExecutionLimits.__table__.columns} - bookkeeping

    assert columns == set(prereg.PREREGISTERED_LIMIT_ROWS[V1])


# ---------------------------------------------------------------------------
# The refusals
# ---------------------------------------------------------------------------


def test_an_unregistered_document_id_is_refused() -> None:
    with pytest.raises(prereg.PreregistrationRefused) as exc:
        prereg.resolve_preregistered_limits("PREREGISTRATION_execution_limits_v2")
    assert "no pre-registered execution_limits row is registered" in str(exc.value)


def test_a_registered_id_whose_document_is_missing_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§7b rule 1 / ceremony check S3: the document is a HARD precondition, and
    a mapping entry is not a document."""
    monkeypatch.setitem(prereg.PREREGISTERED_LIMIT_ROWS, "PREREGISTRATION_nowhere", {})

    with pytest.raises(prereg.PreregistrationRefused) as exc:
        prereg.resolve_preregistered_limits("PREREGISTRATION_nowhere")
    assert "no pre-registration document named" in str(exc.value)


def test_a_document_that_disagrees_with_the_code_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The drift that matters. A value edited in one place and not the other
    stops the WRITE, not just the build."""
    drifted = dict(prereg.PREREGISTERED_LIMIT_ROWS[V1])
    drifted["max_orders_per_day"] = 99
    monkeypatch.setitem(prereg.PREREGISTERED_LIMIT_ROWS, V1, drifted)

    with pytest.raises(prereg.PreregistrationRefused) as exc:
        prereg.resolve_preregistered_limits(V1)
    assert "max_orders_per_day" in str(exc.value)
    assert "disagree" in str(exc.value)


def test_a_document_missing_a_column_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    extra = dict(prereg.PREREGISTERED_LIMIT_ROWS[V1])
    extra["a_column_no_document_states"] = 1
    monkeypatch.setitem(prereg.PREREGISTERED_LIMIT_ROWS, V1, extra)

    with pytest.raises(prereg.PreregistrationRefused) as exc:
        prereg.resolve_preregistered_limits(V1)
    assert "a_column_no_document_states" in str(exc.value)
    assert "COMPLETE row" in str(exc.value)


# ---------------------------------------------------------------------------
# Writing, superseding, and never editing
# ---------------------------------------------------------------------------


def test_the_row_is_created_and_loads_back_as_a_parseable_limit_set(session: Session) -> None:
    row, superseded = prereg.set_limits_from_preregistration(session, doc_id=V1, now=NOW)

    assert superseded == ()
    assert row.preregistration_doc_id == V1
    loaded = load_active_limits(session)
    assert loaded is not None
    assert loaded.id == row.id
    assert loaded.cycle_interval_s == LIMIT_GRID_CENTRES["cycle_interval_s"]


def test_a_second_row_is_refused_without_supersede(session: Session) -> None:
    prereg.set_limits_from_preregistration(session, doc_id=V1, now=NOW)

    with pytest.raises(prereg.PreregistrationRefused) as exc:
        prereg.set_limits_from_preregistration(session, doc_id=V1, now=NOW)
    assert "--supersede" in str(exc.value)
    assert "never edited" in str(exc.value)
    assert "RESETS the decision-10 evidence counter" in str(exc.value)


def test_superseding_deactivates_the_old_row_and_never_edits_it(session: Session) -> None:
    first, _ = prereg.set_limits_from_preregistration(session, doc_id=V1, now=NOW)
    later = NOW + timedelta(days=1)

    second, superseded = prereg.set_limits_from_preregistration(
        session, doc_id=V1, now=later, supersede=True
    )

    assert [row.id for row in superseded] == [first.id]
    assert first.superseded_at == later
    assert second.superseded_at is None
    # The old row's VALUES are untouched: supersession is versioning, not editing.
    assert first.max_orders_per_day == LIMIT_GRID_CENTRES["max_orders_per_day"]
    loaded = load_active_limits(session)
    assert loaded is not None and loaded.id == second.id


def test_a_new_row_resets_the_decision_10_evidence_window(session: Session) -> None:
    """§7b rule 3, at the one place that makes it real: evidence is counted from
    the ACTIVE row's created_at, so superseding sets the counter back to zero."""
    from signalforge.execution.cycle import active_limits_created_at

    prereg.set_limits_from_preregistration(session, doc_id=V1, now=NOW)
    assert active_limits_created_at(session) == NOW

    later = NOW + timedelta(days=5)
    prereg.set_limits_from_preregistration(session, doc_id=V1, now=later, supersede=True)

    assert active_limits_created_at(session) == later
