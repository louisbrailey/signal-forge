"""``execution_event`` is append-only AT THE DATABASE LEVEL (D6 §15).

Shaped after ``tests/db/test_s9_paper_trade_triggers.py``, and for the same
reason: the mechanism is a pair of SQLite triggers, not an ORM exception class.
``ImmutablePaperTradeError`` is declared and exported in ``paper/ledger.py`` and
has no raise site anywhere in ``src/signalforge`` — an ORM-level exception is
exactly the kind of "enforcement" that turns out to enforce nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, text, update
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session

from signalforge.db.models import ExecutionEvent

pytestmark = pytest.mark.safety


def _event(session: Session) -> int:
    row = ExecutionEvent(
        ts=datetime.now(UTC),
        event_type="SUBMITTING",
        client_order_id="c" * 32,
        adapter_name="paper_reference",
        state_from="VALIDATED",
        state_to="SUBMITTING",
        intent_kind="OPEN",
        reason="durable pre-submit record",
        config_hash="cfg",
        spec_json_hash="spec",
        payload_json={},
        raw_status_verbatim="",
        error_verbatim="",
    )
    session.add(row)
    session.commit()
    return row.id


def test_update_is_rejected_by_trigger(session: Session) -> None:
    event_id = _event(session)
    with pytest.raises(DatabaseError, match="immutable"):
        session.execute(
            update(ExecutionEvent).where(ExecutionEvent.id == event_id).values(reason="changed")
        )
    session.rollback()


def test_delete_is_rejected_by_trigger(session: Session) -> None:
    event_id = _event(session)
    with pytest.raises(DatabaseError, match="append-only"):
        session.execute(delete(ExecutionEvent).where(ExecutionEvent.id == event_id))
    session.rollback()


def test_row_still_readable_after_a_blocked_mutation(session: Session) -> None:
    event_id = _event(session)
    with pytest.raises(DatabaseError):
        session.execute(text("UPDATE execution_event SET reason='x' WHERE id=:i"), {"i": event_id})
    session.rollback()
    row = session.get(ExecutionEvent, event_id)
    assert row is not None
    assert row.reason == "durable pre-submit record"


def test_a_correction_is_a_new_row(session: Session) -> None:
    """Corrections are new rows, never edits — the ``TradeCorrection`` pattern."""
    first = _event(session)
    second = _event(session)
    assert first != second
    assert session.query(ExecutionEvent).count() == 2
