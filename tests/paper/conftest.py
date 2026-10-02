"""Fixtures: a paper account, an instrument with bars, and a PASSED candidate."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from signalforge.db.models import (
    Candidate,
    Instrument,
    OHLCVDaily,
    PaperAccount,
    ScanRun,
    Strategy,
    StrategyVersion,
)
from signalforge.domain import Direction, Horizon, LatencyCategory, QualityGate


@pytest.fixture
def account(session: Session) -> PaperAccount:
    acct = PaperAccount(name="default", initial_cash=Decimal("10000"), cash=Decimal("10000"))
    session.add(acct)
    session.flush()
    return acct


@pytest.fixture
def instrument_with_bars(session: Session) -> Instrument:
    inst = Instrument(symbol="AAPL", name="Apple", instrument_type="stock", sector="Tech")
    session.add(inst)
    session.flush()
    d = date(2024, 1, 2)
    price = 100.0
    for _ in range(30):
        session.add(
            OHLCVDaily(
                instrument_id=inst.id,
                session_date=d,
                open=price,
                high=price * 1.01,
                low=price * 0.99,
                close=price,
                volume=5_000_000,
                adj_close=price,
                source="fixture",
                latency_category=LatencyCategory.HISTORICAL,
                is_simulated=True,
                is_adjusted=True,  # Synthetic series has no corporate actions.
                ingested_at=datetime.now(UTC),
                quality_flags=[],
            )
        )
        d += timedelta(days=1)
        price *= 1.001
    session.flush()
    return inst


@pytest.fixture
def passing_candidate(
    session: Session, account: PaperAccount, instrument_with_bars: Instrument
) -> Candidate:
    strat = Strategy(name="t", horizon=Horizon.SHORT_SWING, permits_long=True, permits_short=False)
    session.add(strat)
    session.flush()
    ver = StrategyVersion(strategy_id=strat.id, version="0.1.0", git_sha="x", spec_json={})
    session.add(ver)
    scan = ScanRun(
        horizon=Horizon.SHORT_SWING,
        started_at=datetime.now(UTC),
        config_hash="h",
    )
    session.add(scan)
    session.flush()
    cand = Candidate(
        scan_run_id=scan.id,
        instrument_id=instrument_with_bars.id,
        strategy_version_id=ver.id,
        horizon=Horizon.SHORT_SWING,
        direction=Direction.LONG,
        entry_zone_low=99.5,
        entry_zone_high=100.5,
        invalidation_level=96.0,
        target_level=110.0,
        target_logic="entry + 3 ATR",
        time_stop_days=10,
        reward_risk_estimate=2.5,
        risk_dollars=50.0,
        risk_pct_of_account=0.5,
        liquidity_json={"last_price": 100.0},
        slippage_assumption_json={},
        event_risk_json={"upcoming_earnings": []},
        portfolio_context_json={},
        data_freshness_json={"fresh": True},
        ranking_json={"score": 0.4},
        reasons_qualify=["trend + volume"],
        reasons_fail=["whipsaw in range regimes"],
        quality_gate_status=QualityGate.PASSED,
        failed_gates=[],
        rank_in_horizon=1,
    )
    session.add(cand)
    session.flush()
    return cand
