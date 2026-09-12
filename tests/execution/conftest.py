"""Fixtures for the execution layer: an approved+armed strategy version, an
automatically-created paper trade, and a valid limits row.

Everything here is deliberately assembled by hand rather than by running the
research pipeline, so each precondition test can remove exactly one fact and
watch the factory refuse.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from signalforge.execution.arming import ArmingRequest
    from signalforge.execution.protocol import IsPaperProof
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import (
    ArmedStrategy,
    Candidate,
    DataSnapshot,
    ExecutionLimits,
    Instrument,
    PaperAccount,
    PaperPosition,
    PaperTrade,
    ScanRun,
    Strategy,
    StrategyPromotionEvaluation,
    StrategySealedTest,
    StrategyVersion,
)
from signalforge.domain import (
    Direction,
    Horizon,
    PaperDecision,
    PositionSide,
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


#: The grid centres of §7b / decision 4, in ONE place, so the database row and
#: the database-free :func:`clean_limit_set` cannot drift apart.
LIMIT_GRID_CENTRES: dict[str, object] = {
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
    "cycle_interval_s": 30,
    "max_intent_age_minutes": 15,
    "max_reconciliation_age_s": 120,
    "execution_stale_after_s": 90,
    "drain_timeout_s": 30,
    "no_submit_after_open_minutes": 15,
    "no_submit_before_close_minutes": 15,
    "buying_power_tolerance_usd": 1.0,
    "buying_power_tolerance_pct": 0.1,
    "round_trips_per_5_sessions_max": 3,
    "pdt_equity_threshold_usd": 25_000.0,
    "preregistration_doc_id": "PREREGISTRATION_execution_limits_v1",
}


def clean_limit_set() -> LimitSet:
    """The same grid centres as a :class:`LimitSet`, with no database.

    ``may_open`` needs a parseable limits row and nothing else from the DB, so
    a test about a different gate entirely (T6's ``is_paper`` proof, say) does
    not have to stand a migration up to reach it.
    """
    return LimitSet(id=0, **LIMIT_GRID_CENTRES)  # type: ignore[arg-type]


@pytest.fixture
def limits_row(session: Session) -> ExecutionLimits:
    """The grid centres of §7b / decision 4, as a valid active row.

    Created 30 days before ``NOW`` because §7b rule 3 counts decision-10 evidence
    only from the active row's creation: a limits row created after the evidence
    would (correctly) reset the counter to zero, and that reset has its own test
    rather than being the accidental default of every other one.
    """
    row = ExecutionLimits(
        created_at=NOW - timedelta(days=30), created_by="local-user", **LIMIT_GRID_CENTRES
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


# ---------------------------------------------------------------------------
# I-E4 — the arming ceremony's own fixtures.
#
# Assembled by hand, like everything above: each precondition test removes
# exactly one fact and watches the ceremony refuse. The evidence fixture builds
# REAL closed PaperPositions rather than stubbing the health monitor, because
# decision 10's precondition is "under the health monitor" and a stub would let
# the two definitions of a closed trade drift apart unnoticed.
# ---------------------------------------------------------------------------


@pytest.fixture
def live_hashes(session: Session, strategy_version: StrategyVersion) -> tuple[str, str]:
    """The config/spec hashes the arming ceremony will recompute for itself.

    Read from the same two functions the ceremony reads, never hard-coded: a
    hard-coded hash is a test that keeps passing after the thing it guards has
    moved, which is precisely the 2026-09-11 config-hash incident's shape.
    """
    from signalforge.research.approval_scope import current_spec_json_hash
    from signalforge.settings_store import effective_research_config

    return (
        effective_research_config(session).config_hash,
        current_spec_json_hash(session, strategy_version.id) or "",
    )


@pytest.fixture
def sealed_test(session: Session, strategy_version: StrategyVersion) -> StrategySealedTest:
    """A PASSING sealed final test — §12 step 1's first requirement."""
    from datetime import date

    snapshot = DataSnapshot(key="universe_test_snapshot", symbols_json=["SPY"])
    session.add(snapshot)
    session.flush()
    row = StrategySealedTest(
        strategy_version_id=strategy_version.id,
        dataset_snapshot_id=snapshot.id,
        window_start=date(2024, 1, 2),
        window_end=date(2025, 1, 2),
        universe_json=["SPY"],
        passed=True,
        evaluated_at=NOW - timedelta(days=30),
    )
    session.add(row)
    session.flush()
    return row


@pytest.fixture
def approved_evaluation(
    session: Session,
    strategy_version: StrategyVersion,
    sealed_test: StrategySealedTest,
    live_hashes: tuple[str, str],
) -> StrategyPromotionEvaluation:
    """A PASSING evaluation whose scope hashes equal the LIVE ones.

    This is what makes the approval apply to what the code would run now. A test
    that drifts one of these two hashes is testing the auto-disarm trigger the
    config-hash incident produced.
    """
    from datetime import date

    config_hash, spec_hash = live_hashes
    row = StrategyPromotionEvaluation(
        strategy_version_id=strategy_version.id,
        dataset_snapshot_id=sealed_test.dataset_snapshot_id,
        evaluated_at=NOW - timedelta(days=29),
        config_hash=config_hash,
        spec_json_hash=spec_hash,
        universe_json=["SPY"],
        window_start=date(2024, 1, 2),
        window_end=date(2025, 1, 2),
        data_provenance_json={"sources": ["massive"]},
        passed=True,
        verdict="PAPER_APPROVED",
        sealed_test_id=sealed_test.id,
    )
    session.add(row)
    session.flush()
    return row


def add_closed_paper_positions(
    session: Session,
    *,
    account: PaperAccount,
    strategy_version: StrategyVersion,
    n: int,
    pnl_per_trade: float,
    closed_at: datetime | None = None,
) -> None:
    """``n`` closed positions with a fixed R, for decision 10's counter.

    Entry 100, stop 99 => $1 of per-share risk on 1 share, so ``pnl_per_trade``
    IS the R-multiple the health monitor computes. Keeping that arithmetic
    trivial is deliberate: a test of the >=20/non-negative rule should fail on
    the rule, never on its own fixture's R arithmetic.
    """
    inst = session.scalar(select(Instrument).where(Instrument.symbol == "SPY"))
    if inst is None:
        inst = Instrument(symbol="SPY", name="SPDR", instrument_type="etf", sector="Broad")
        session.add(inst)
        session.flush()
    when = closed_at or (NOW - timedelta(days=1))
    for i in range(n):
        session.add(
            PaperPosition(
                account_id=account.id,
                instrument_id=inst.id,
                strategy_version_id=strategy_version.id,
                horizon=Horizon.SHORT_SWING,
                side=PositionSide.LONG,
                qty=1,
                avg_price=Decimal("100"),
                stop_level=99.0,
                opened_at=when - timedelta(days=2),
                closed_at=when + timedelta(seconds=i),
                realized_pnl=Decimal(str(pnl_per_trade)),
            )
        )
    session.flush()


@pytest.fixture
def evidence_ok(session: Session, account: PaperAccount, strategy_version: StrategyVersion) -> None:
    """Exactly the 20 closed trades decision 10 requires, at +0.5R each."""
    add_closed_paper_positions(
        session,
        account=account,
        strategy_version=strategy_version,
        n=20,
        pnl_per_trade=0.5,
    )


@pytest.fixture
def armable(
    session: Session,
    strategy_version: StrategyVersion,
    approved_evaluation: StrategyPromotionEvaluation,
    evidence_ok: None,
    limits_row: ExecutionLimits,
) -> StrategyVersion:
    """Everything §12 steps 1-2 need, and nothing §12 step 3 needs.

    Step 3's facts — the typed account id, the acknowledgements, the is_paper
    proof, the flat account — are supplied per test, because each of them is a
    separate refusal worth exercising on its own.
    """
    return strategy_version


def arming_request(**overrides: object) -> ArmingRequest:
    """A complete, passing :class:`ArmingRequest`, for tests that break one field."""
    from signalforge.execution.arming import ArmingRequest

    base: dict[str, object] = {
        "strategy_version_id": 1,
        "adapter_name": ADAPTER,
        "broker_account_id_expected": "PAPER-ACCOUNT-1",
        "preregistration_doc_id": "PREREGISTRATION_2026-09-11_snapshot11",
        "max_notional_usd": 1_000.0,
        "max_orders_per_day": 10,
        "structure_type": "equity",
        "acknowledged": True,
    }
    base.update(overrides)
    return ArmingRequest(**base)  # type: ignore[arg-type]


def paper_proof(account_id: str = "PAPER-ACCOUNT-1", *, proven: bool = True) -> IsPaperProof:
    """An :class:`IsPaperProof` in the shape an adapter would return."""
    from signalforge.execution.protocol import IsPaperProof

    return IsPaperProof(
        proven=proven,
        observed_account_id=account_id,
        observed_host="paper.example.invalid",
        expected_account_id=account_id if proven else "",
        checked_at=NOW,
        failure_reason="" if proven else "stubbed mismatch",
    )
