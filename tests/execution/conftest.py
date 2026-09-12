"""Fixtures for the execution layer: an approved+armed strategy version, an
automatically-created paper trade, and a valid limits row.

Everything here is deliberately assembled by hand rather than by running the
research pipeline, so each precondition test can remove exactly one fact and
watch the factory refuse.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from signalforge.db.models import (
    ArmedStrategy,
    Candidate,
    ExecutionLimits,
    Instrument,
    PaperAccount,
    PaperTrade,
    ScanRun,
    Strategy,
    StrategyVersion,
)
from signalforge.domain import (
    Direction,
    Horizon,
    PaperDecision,
    QualityGate,
    StrategyStatus,
)
from signalforge.execution.intents import CostModelFeedback
from signalforge.execution.limits import (
    ArmedFacts,
    LimitSet,
    OpenGateContext,
    limit_set_from_row,
)
from signalforge.paper.auto_simulate import AUTO_SIM_ACTOR

NOW = datetime(2026, 9, 11, 15, 0, tzinfo=UTC)
ADAPTER = "paper_reference"


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def account(session: Session) -> PaperAccount:
    acct = PaperAccount(name="default", initial_cash=Decimal("25000"), cash=Decimal("25000"))
    session.add(acct)
    session.flush()
    return acct


@pytest.fixture
def strategy_version(session: Session) -> StrategyVersion:
    strat = Strategy(
        name="trend_continuation.short_swing",
        horizon=Horizon.SHORT_SWING,
        permits_long=True,
        permits_short=False,
        status=StrategyStatus.PAPER_APPROVED,
    )
    session.add(strat)
    session.flush()
    ver = StrategyVersion(
        strategy_id=strat.id,
        version="0.1.0",
        git_sha="deadbeef",
        spec_json={},
        status=StrategyStatus.PAPER_APPROVED,
    )
    session.add(ver)
    session.flush()
    return ver


@pytest.fixture
def candidate(session: Session, strategy_version: StrategyVersion) -> Candidate:
    inst = Instrument(symbol="SPY", name="SPDR", instrument_type="etf", sector="Broad")
    session.add(inst)
    scan = ScanRun(
        horizon=Horizon.SHORT_SWING,
        started_at=NOW,
        config_hash="cfg",
        source="massive",
        universe_json=["SPY"],
    )
    session.add_all([inst, scan])
    session.flush()
    cand = Candidate(
        scan_run_id=scan.id,
        instrument_id=inst.id,
        strategy_version_id=strategy_version.id,
        horizon=Horizon.SHORT_SWING,
        direction=Direction.LONG,
        entry_zone_low=470.0,
        entry_zone_high=472.0,
        invalidation_level=465.0,
        target_level=485.0,
        target_logic="entry + 3 ATR",
        time_stop_days=10,
        reward_risk_estimate=2.0,
        risk_dollars=125.0,
        risk_pct_of_account=0.5,
        liquidity_json={},
        slippage_assumption_json={},
        event_risk_json={},
        portfolio_context_json={},
        data_freshness_json={},
        ranking_json={},
        reasons_qualify=["trend"],
        reasons_fail=["regime flip"],
        quality_gate_status=QualityGate.PASSED,
        failed_gates=[],
        rank_in_horizon=1,
    )
    session.add(cand)
    session.flush()
    return cand


@pytest.fixture
def auto_paper_trade(session: Session, account: PaperAccount, candidate: Candidate) -> PaperTrade:
    """A paper trade created by the AUTOMATIC actor — the only kind P6 accepts."""
    trade = PaperTrade(
        account_id=account.id,
        candidate_id=candidate.id,
        decision=PaperDecision.ACCEPTED,
        signal_snapshot_json={"decision": {"actor": AUTO_SIM_ACTOR, "automatic": True}},
        plan_json={"shares": 1},
        why_qualified="trend",
        why_might_fail="regime flip",
        actor=AUTO_SIM_ACTOR,
        created_at=NOW,
    )
    session.add(trade)
    session.flush()
    return trade


@pytest.fixture
def manual_paper_trade(session: Session, account: PaperAccount, candidate: Candidate) -> PaperTrade:
    """The hole §5.1 closes: an ACCEPTED trade from the unguarded CLI path."""
    trade = PaperTrade(
        account_id=account.id,
        candidate_id=candidate.id,
        decision=PaperDecision.ACCEPTED,
        signal_snapshot_json={"decision": {"actor": "local-user", "automatic": False}},
        plan_json={"shares": 1},
        why_qualified="",
        why_might_fail="",
        actor="local-user",
        created_at=NOW,
    )
    session.add(trade)
    session.flush()
    return trade


@pytest.fixture
def limits_row(session: Session) -> ExecutionLimits:
    """The grid centres of §7b / decision 4, as a valid active row."""
    row = ExecutionLimits(
        created_at=NOW,
        created_by="local-user",
        max_orders_per_day=10,
        max_order_notional_usd=1_000.0,
        max_account_exposure_pct=40.0,
        per_structure_max_loss_usd=250.0,
        per_structure_max_loss_pct=0.5,
        aggregate_open_max_loss_usd=1_000.0,
        aggregate_open_max_loss_pct=2.0,
        collateral_cap_usd=5_000.0,
        collateral_cap_pct=30.0,
        max_net_delta_notional_usd=10_000.0,
        max_net_vega_per_volpt_usd=50.0,
        cycle_interval_s=30,
        max_intent_age_minutes=15,
        max_reconciliation_age_s=120,
        execution_stale_after_s=90,
        drain_timeout_s=30,
        no_submit_after_open_minutes=15,
        no_submit_before_close_minutes=15,
        buying_power_tolerance_usd=1.0,
        buying_power_tolerance_pct=0.1,
        round_trips_per_5_sessions_max=3,
        pdt_equity_threshold_usd=25_000.0,
        preregistration_doc_id="PREREGISTRATION_execution_limits_v1",
    )
    session.add(row)
    session.flush()
    return row


@pytest.fixture
def limit_set(limits_row: ExecutionLimits) -> LimitSet:
    return limit_set_from_row(limits_row)


@pytest.fixture
def armed(
    session: Session, strategy_version: StrategyVersion, limits_row: ExecutionLimits
) -> ArmedStrategy:
    row = ArmedStrategy(
        strategy_version_id=strategy_version.id,
        structure_type="equity",
        armed_at=NOW - timedelta(days=1),
        armed_by="local-user",
        expires_at=NOW + timedelta(days=6),
        adapter_name=ADAPTER,
        broker_account_id_expected="PAPER-ACCOUNT-1",
        max_notional_usd=1_000.0,
        max_orders_per_day=10,
        evidence_paper_trade_count=20,
        evidence_expectancy_r=0.1,
        sealed_look_prior_at_arm=4,
        preregistration_doc_id="PREREGISTRATION_2026-09-11_snapshot11",
        execution_limits_id=limits_row.id,
        spec_json_hash="spec",
        config_hash="cfg",
    )
    session.add(row)
    session.flush()
    return row


@pytest.fixture
def cost_model() -> CostModelFeedback:
    return CostModelFeedback(modelled_fill_price=471.0, modelled_spread_bps=5.0)


def clean_open_context(**overrides: object) -> OpenGateContext:
    """An ``OpenGateContext`` in which every check passes, for tests that then
    break exactly one of them."""
    base: dict[str, object] = {
        "now": NOW,
        "adapter_name": ADAPTER,
        "kill_switch_engaged": False,
        "execution_kill_engaged": False,
        "dead_man_alive": True,
        "market_open_broker": True,
        "market_open_calendar": True,
        "minutes_since_open": 60.0,
        "minutes_until_close": 120.0,
        "is_early_close_session": False,
        "armed": ArmedFacts(
            adapter_name=ADAPTER,
            expires_at=NOW + timedelta(days=6),
            disarmed=False,
            structure_type="equity",
            approval_level_permits_structure=True,
        ),
        "is_paper_proven_this_cycle": True,
        "intent_expires_at": NOW + timedelta(minutes=15),
        "unknown_outstanding_for_strategy": False,
        "orders_today": 0,
        "order_notional_usd": 100.0,
        "account_equity_usd": 25_000.0,
        "account_exposure_usd": 0.0,
        "round_trips_last_5_sessions": 0,
        "reconciliation_clean": True,
        "reconciliation_age_s": 10.0,
        "options_risk_within_limits": True,
        "preconditions_ok": True,
    }
    base.update(overrides)
    return OpenGateContext(**base)  # type: ignore[arg-type]
