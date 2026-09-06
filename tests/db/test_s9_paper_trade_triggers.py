"""S9 (database level) — paper_trade rows cannot be updated or deleted."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, text, update
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session

from signalforge.db.models import PaperAccount, PaperTrade
from signalforge.domain import PaperDecision

pytestmark = pytest.mark.safety


def _make_trade(session: Session) -> int:
    acct = PaperAccount(name="default", initial_cash=Decimal("10000"), cash=Decimal("10000"))
    session.add(acct)
    session.flush()
    trade = PaperTrade(
        account_id=acct.id,
        decision=PaperDecision.ACCEPTED,
        signal_snapshot_json={"symbol": "SPY", "close": 471.8},
        plan_json={"entry": [470, 472], "stop": 465, "time_stop_days": 10},
        why_qualified="trend + volume",
        why_might_fail="regime flip",
        created_at=datetime.now(UTC),
    )
    session.add(trade)
    session.commit()
    return trade.id


def test_update_is_rejected_by_trigger(session: Session) -> None:
    trade_id = _make_trade(session)
    with pytest.raises(DatabaseError, match="immutable"):
        session.execute(
            update(PaperTrade).where(PaperTrade.id == trade_id).values(why_qualified="changed")
        )
    session.rollback()


def test_delete_is_rejected_by_trigger(session: Session) -> None:
    trade_id = _make_trade(session)
    with pytest.raises(DatabaseError, match="append-only"):
        session.execute(delete(PaperTrade).where(PaperTrade.id == trade_id))
    session.rollback()


def test_row_still_readable_after_blocked_mutation(session: Session) -> None:
    trade_id = _make_trade(session)
    with pytest.raises(DatabaseError):
        session.execute(
            text("UPDATE paper_trade SET why_qualified='x' WHERE id=:i"), {"i": trade_id}
        )
    session.rollback()
    row = session.get(PaperTrade, trade_id)
    assert row is not None
    assert row.why_qualified == "trend + volume"
