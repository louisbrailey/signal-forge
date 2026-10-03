"""Paper ledger: accept / decisions / mark-to-market / kill-switch guard."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import Candidate, PaperFill, PaperOrder, PaperPosition, PaperTrade
from signalforge.domain import Direction, PaperDecision, PositionSide
from signalforge.killswitch import KillSwitchEngaged, get_kill_switch
from signalforge.paper.ledger import (
    accept_candidate,
    auto_simulate_enabled,
    mark_to_market,
    record_decision,
)


def test_accept_creates_order_fill_position_and_immutable_trade(
    session: Session, passing_candidate: Candidate, account
) -> None:
    start_cash = Decimal(account.cash)
    res = accept_candidate(session, passing_candidate.id, as_of=date(2024, 2, 1))

    assert res.side is PositionSide.LONG and res.shares >= 1
    assert res.fill_price > 100.0  # slippage + half-spread against a long

    order = session.get(PaperOrder, res.order_id)
    fill = session.get(PaperFill, res.fill_id)
    pos = session.get(PaperPosition, res.position_id)
    trade = session.get(PaperTrade, res.paper_trade_id)
    assert order is not None and fill is not None and pos is not None and trade is not None
    assert fill.spread_cost > 0
    assert trade.decision is PaperDecision.ACCEPTED
    assert trade.plan_json["shares"] == res.shares
    assert pos.closed_at is None

    # cash fell by roughly notional + costs
    spent = start_cash - Decimal(account.cash)
    assert spent > Decimal(res.fill_price) * res.shares - Decimal("1")


def test_reject_records_a_trade_but_no_position(
    session: Session, passing_candidate: Candidate, account
) -> None:
    before = Decimal(account.cash)
    tid = record_decision(session, passing_candidate.id, PaperDecision.REJECTED, note="not now")
    trade = session.get(PaperTrade, tid)
    assert trade is not None and trade.decision is PaperDecision.REJECTED
    assert trade.position_id is None
    assert Decimal(account.cash) == before
    assert session.scalars(select(PaperPosition)).first() is None


def test_cannot_accept_an_avoid_candidate(
    session: Session, passing_candidate: Candidate, account
) -> None:
    passing_candidate.direction = Direction.AVOID
    session.flush()
    with pytest.raises(ValueError, match="AVOID"):
        accept_candidate(session, passing_candidate.id)


@pytest.mark.safety
def test_kill_switch_blocks_paper_trade_creation(
    session: Session, passing_candidate: Candidate, account, isolated_data_dir
) -> None:
    get_kill_switch().engage(reason="halt", actor="pytest")
    with pytest.raises(KillSwitchEngaged):
        accept_candidate(session, passing_candidate.id)
    with pytest.raises(KillSwitchEngaged):
        record_decision(session, passing_candidate.id, PaperDecision.WATCH)
    assert session.scalars(select(PaperTrade)).first() is None


def test_mark_to_market_closes_on_time_stop(
    session: Session, passing_candidate: Candidate, account
) -> None:
    res = accept_candidate(session, passing_candidate.id, as_of=date(2024, 1, 5))
    r = mark_to_market(session, as_of=date(2024, 1, 31))  # well past the 10-day time stop
    assert r.closed == 1
    pos = session.get(PaperPosition, res.position_id)
    assert pos is not None and pos.closed_at is not None
    assert pos.realized_pnl is not None


def test_mark_to_market_stops_out_a_loss_on_a_falling_series(
    session: Session, passing_candidate: Candidate, account
) -> None:
    from datetime import UTC, datetime, timedelta

    from signalforge.db.models import OHLCVDaily
    from signalforge.domain import LatencyCategory

    # Add a later, declining series for the same instrument; stop sits just below entry.
    inst_id = passing_candidate.instrument_id
    d = date(2024, 3, 1)
    px = 100.0
    for _ in range(20):
        session.add(
            OHLCVDaily(
                instrument_id=inst_id,
                session_date=d,
                open=px,
                high=px * 1.005,
                low=px * 0.985,
                close=px * 0.99,
                volume=5_000_000,
                adj_close=px * 0.99,
                source="fixture2",
                latency_category=LatencyCategory.HISTORICAL,
                is_simulated=True,
                is_adjusted=True,  # Synthetic series has no corporate actions.
                ingested_at=datetime.now(UTC),
                quality_flags=[],
            )
        )
        d += timedelta(days=1)
        px *= 0.98
    passing_candidate.entry_zone_low = 99.5
    passing_candidate.entry_zone_high = 100.5
    passing_candidate.invalidation_level = 98.0
    session.flush()

    res = accept_candidate(session, passing_candidate.id, as_of=date(2024, 3, 2))
    r = mark_to_market(session, as_of=date(2024, 3, 10))
    assert r.closed == 1
    pos = session.get(PaperPosition, res.position_id)
    assert pos is not None and float(pos.realized_pnl) < 0


def test_auto_simulate_is_off_by_default(session: Session) -> None:
    assert auto_simulate_enabled(session) is False
