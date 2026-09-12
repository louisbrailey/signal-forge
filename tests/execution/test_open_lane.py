"""D6 §2 / §5 / §6 / §8 — the cycle's OPEN lane.

This is the one module in the tree that can cause an order to be submitted, so
the tests below are mostly about the conditions under which it does NOT. The
single happy path is asserted once; everything else removes exactly one fact and
watches the lane refuse.

The three structural promises, asserted here and nowhere else:

* **absent when nothing is armed** — not "inert", absent: with no live arming
  the lane selects nothing, builds nothing and calls no adapter method at all;
* **one order per paper trade, ever** — the id is a hash of the paper trade and
  the leg signature with no attempt counter, so a second cycle finds the state
  already written and skips;
* **the §6/§8 order** — the ``SUBMITTING`` record is written and COMMITTED
  before ``place()`` is called, so a crash in between leaves a durable row the
  next cycle promotes to ``UNKNOWN`` rather than losing an order that may have
  reached the broker.

``paper_trade`` is immutable (invariant S9, enforced by a SQLite trigger), so
every variant world below is BUILT with the variant rather than mutated into it
— which is the right shape anyway: each one is a different world, not a
tampered-with one.

**A finding this file records rather than works around.** Under
``PREREGISTRATION_execution_limits_v1`` the binding per-order notional cap on the
$25,000 reference account is ``min($1,000, 0.5% x equity)`` = **$125**, so no
order in a $470 instrument can ever pass L2 — not even one share. The happy path
therefore uses a low-priced instrument, and
:func:`test_a_high_priced_instrument_cannot_pass_l2_under_v1` pins the finding.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import (
    ArmedStrategy,
    Candidate,
    DataSnapshot,
    ExecutionEvent,
    ExecutionLimits,
    Instrument,
    PaperAccount,
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
    QualityGate,
    StrategyStatus,
)
from signalforge.execution import cycle as cycle_mod
from signalforge.execution import open_lane as lane_mod
from signalforge.execution.brokers.paper_reference import (
    SIMULATED_ACCOUNT_PREFIX,
    ExecutionEventAudit,
    MarketClock,
    PaperReferenceBroker,
    PaperReferenceOrderStore,
    PreSubmissionInformation,
    ReferenceQuote,
    SimulatedAccount,
)
from signalforge.execution.events import ExecutionEventType
from signalforge.execution.intents import OrderSide
from signalforge.execution.oms import CycleBranch, CyclePosture, ExecutionKillState
from signalforge.execution.states import OrderState
from tests.execution.conftest import LIMIT_GRID_CENTRES, NOW

ACCOUNT_ID = f"{SIMULATED_ACCOUNT_PREFIX}OPEN-LANE"
SYMBOL = "LOWP"
#: 12 x $10.02 = $120.24, inside the $125 binding cap. See the module docstring.
SHARES = 12
FILL_PRICE = 10.02
REFERENCE = 10.00


class World:
    """One complete world in which every §5 precondition holds, or one in which
    exactly one of them does not."""

    def __init__(
        self,
        session: Session,
        *,
        actor: str | None = None,
        decision: PaperDecision = PaperDecision.ACCEPTED,
        created_at: datetime | None = None,
        shares: int = SHARES,
        fill_price: float = FILL_PRICE,
        reference: float = REFERENCE,
        symbol: str = SYMBOL,
        entry: float = 10.0,
        stop: float = 9.0,
        max_orders_per_day: int | None = None,
        extra_trades: int = 0,
    ) -> None:
        from signalforge.paper.auto_simulate import AUTO_SIM_ACTOR
        from signalforge.research.approval_scope import current_spec_json_hash
        from signalforge.settings_store import effective_research_config

        self.session = session
        self.symbol = symbol
        self.reference = reference
        self.account = PaperAccount(
            name="open-lane", initial_cash=Decimal("25000"), cash=Decimal("25000")
        )
        inst = Instrument(symbol=symbol, name="Low priced", instrument_type="stock", sector="Broad")
        session.add_all([self.account, inst])
        session.flush()

        self.strategy = Strategy(
            name="trend_continuation.open_lane",
            horizon=Horizon.SHORT_SWING,
            permits_long=True,
            permits_short=False,
            status=StrategyStatus.PAPER_APPROVED,
        )
        session.add(self.strategy)
        session.flush()
        self.version = StrategyVersion(
            strategy_id=self.strategy.id,
            version="0.1.0",
            git_sha="openlane",
            spec_json={},
            status=StrategyStatus.PAPER_APPROVED,
        )
        session.add(self.version)
        session.flush()

        # The approved scope, and a scan run whose scope MATCHES it exactly. P4
        # re-verifies the full five-part match at intent time; a world whose scan
        # is out of scope would make every test below pass for the wrong reason.
        snapshot = DataSnapshot(key="open_lane_snapshot", symbols_json=[symbol])
        session.add(snapshot)
        session.flush()
        sealed = StrategySealedTest(
            strategy_version_id=self.version.id,
            dataset_snapshot_id=snapshot.id,
            window_start=NOW.date() - timedelta(days=400),
            window_end=NOW.date() - timedelta(days=35),
            universe_json=[symbol],
            passed=True,
            evaluated_at=NOW - timedelta(days=30),
        )
        session.add(sealed)
        session.flush()
        config_hash = effective_research_config(session).config_hash
        spec_hash = current_spec_json_hash(session, self.version.id) or ""
        session.add(
            StrategyPromotionEvaluation(
                strategy_version_id=self.version.id,
                dataset_snapshot_id=snapshot.id,
                evaluated_at=NOW - timedelta(days=29),
                config_hash=config_hash,
                spec_json_hash=spec_hash,
                universe_json=[symbol],
                window_start=sealed.window_start,
                window_end=sealed.window_end,
                data_provenance_json={"sources": ["massive"]},
                passed=True,
                verdict="PAPER_APPROVED",
                sealed_test_id=sealed.id,
            )
        )
        scan = ScanRun(
            horizon=Horizon.SHORT_SWING,
            started_at=NOW,
            config_hash=config_hash,
            source="massive",
            universe_json=[symbol],
            dataset_snapshot_id=snapshot.id,
        )
        session.add(scan)
        session.flush()

        self.trades: list[PaperTrade] = []
        for index in range(1 + extra_trades):
            cand = Candidate(
                scan_run_id=scan.id,
                instrument_id=inst.id,
                strategy_version_id=self.version.id,
                horizon=Horizon.SHORT_SWING,
                direction=Direction.LONG,
                entry_zone_low=entry,
                entry_zone_high=entry + 0.05,
                invalidation_level=stop,
                target_level=entry * 1.2,
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
                rank_in_horizon=index + 1,
            )
            session.add(cand)
            session.flush()
            trade = PaperTrade(
                account_id=self.account.id,
                candidate_id=cand.id,
                decision=decision,
                signal_snapshot_json={"decision": {"actor": actor or AUTO_SIM_ACTOR}},
                # The SIMULATION's own size and price. The lane submits these
                # and never recomputes them.
                plan_json={"shares": shares, "fill_price": fill_price},
                why_qualified="trend",
                why_might_fail="regime flip",
                actor=actor or AUTO_SIM_ACTOR,
                created_at=created_at or NOW,
            )
            session.add(trade)
            session.flush()
            self.trades.append(trade)
        self.candidate = cand
        self.trade = self.trades[0]

        values = dict(LIMIT_GRID_CENTRES)
        if max_orders_per_day is not None:
            values["max_orders_per_day"] = max_orders_per_day
        self.limits_row = ExecutionLimits(
            created_at=NOW - timedelta(days=30), created_by="test", **values
        )
        session.add(self.limits_row)
        session.flush()
        self.armed = ArmedStrategy(
            strategy_version_id=self.version.id,
            structure_type="equity",
            armed_at=NOW - timedelta(days=1),
            armed_by="test",
            expires_at=NOW + timedelta(days=6),
            adapter_name="paper_reference",
            broker_account_id_expected=ACCOUNT_ID,
            max_notional_usd=1_000.0,
            max_orders_per_day=10,
            evidence_paper_trade_count=20,
            evidence_expectancy_r=0.5,
            sealed_look_prior_at_arm=1,
            preregistration_doc_id="PREREGISTRATION_execution_limits_v1",
            execution_limits_id=self.limits_row.id,
            spec_json_hash=spec_hash,
            config_hash=config_hash,
        )
        session.add(self.armed)
        session.flush()

        from signalforge.execution import deadman

        deadman.feed(session, now=NOW, detail="test: the previous cycle")
        session.flush()

    def broker(self, *, available: int | None = None) -> PaperReferenceBroker:
        return PaperReferenceBroker(
            audit=ExecutionEventAudit(self.session),
            account=SimulatedAccount(account_id=ACCOUNT_ID, initial_cash=25_000.0),
            expected_account_id=ACCOUNT_ID,
            information=PreSubmissionInformation.of(
                [
                    ReferenceQuote(
                        self.symbol,
                        self.reference,
                        NOW - timedelta(minutes=1),
                        available_qty=available,
                    )
                ]
            ),
            clock=MarketClock(is_open=True, as_of=NOW),
            book=PaperReferenceOrderStore(self.session),
        )

    def client_order_id(self, index: int = 0) -> str:
        return lane_mod.open_intent_client_order_id(
            trade_id=self.trades[index].id, symbol=self.symbol, side=OrderSide.BUY_TO_OPEN
        )


@pytest.fixture
def world(session: Session) -> World:
    return World(session)


def _posture(branch: CycleBranch = CycleBranch.FULL, *, kill: bool = False) -> CyclePosture:
    return CyclePosture(
        branch=branch,
        may_open=branch is CycleBranch.FULL,
        may_close=True,
        kill_switch_engaged=kill,
        execution_kill=ExecutionKillState(engaged=kill, readable=True),
        detail="test posture",
    )


def _run(
    world: World,
    *,
    branch: CycleBranch = CycleBranch.FULL,
    kill: bool = False,
    now: datetime | None = None,
) -> cycle_mod.CycleReport:
    return cycle_mod.run_execution_cycle(
        world.session,
        _posture(branch, kill=kill),
        now=now or NOW,
        adapter=world.broker(),
        actor="test",
    )


def _events(session: Session, event_type: ExecutionEventType) -> list[ExecutionEvent]:
    return list(
        session.scalars(
            select(ExecutionEvent)
            .where(ExecutionEvent.event_type == event_type.value)
            .order_by(ExecutionEvent.id)
        )
    )


def _refusals(session: Session) -> list[str]:
    return [e.reason for e in _events(session, ExecutionEventType.INTENT_REFUSED)]


# ---------------------------------------------------------------------------
# The one happy path
# ---------------------------------------------------------------------------


def test_the_cycle_opens_when_all_seven_preconditions_hold(world: World) -> None:
    from signalforge.execution.oms import current_state

    report = _run(world)

    assert report.may_open_possible is True, report.blocked_reasons
    assert report.submitted == (world.client_order_id(),), report.open_lane
    assert report.filled == (world.client_order_id(),), report.open_lane
    assert "filled=1" in report.open_lane
    assert current_state(world.session, world.client_order_id()) is OrderState.FILLED

    submitting = [
        e
        for e in _events(world.session, ExecutionEventType.SUBMITTING)
        if e.client_order_id == world.client_order_id()
    ]
    assert len(submitting) == 1
    # The order the SIMULATION decided, not one this lane invented.
    assert submitting[0].payload_json["submitted_units"] == SHARES
    assert submitting[0].source_paper_trade_id == world.trade.id

    created = _events(world.session, ExecutionEventType.INTENT_CREATED)
    assert len(created) == 1
    assert f"BUY_TO_OPEN {SHARES} {SYMBOL}" in created[0].reason


def test_the_submitting_record_is_committed_before_the_adapter_is_called(world: World) -> None:
    """§8. The durable pre-submit record is the whole reason a crash between the
    two leaves an UNKNOWN rather than a lost order."""
    seen: list[str | None] = []

    class _WatchingBroker:
        name = "paper_reference"

        def __init__(self, inner: PaperReferenceBroker) -> None:
            self._inner = inner

        def place(self, intent: object) -> object:
            # Read through a SEPARATE session: the point is that the record is
            # COMMITTED, not merely flushed into the cycle's own transaction.
            seen.append(_state_in_a_new_session(intent.client_order_id))  # type: ignore[attr-defined]
            return self._inner.place(intent)  # type: ignore[arg-type]

        def __getattr__(self, name: str) -> object:
            return getattr(self._inner, name)

    cycle_mod.run_execution_cycle(
        world.session,
        _posture(),
        now=NOW,
        adapter=_WatchingBroker(world.broker()),  # type: ignore[arg-type]
        actor="test",
    )

    assert seen == ["SUBMITTING"], seen


def _state_in_a_new_session(client_order_id: str) -> str | None:
    from signalforge.db.session import get_sessionmaker
    from signalforge.execution.oms import current_state

    with get_sessionmaker()() as other:
        state = current_state(other, client_order_id)
    return state.value if state is not None else None


# ---------------------------------------------------------------------------
# Absent when nothing is armed
# ---------------------------------------------------------------------------


def test_with_nothing_armed_the_lane_is_absent_not_merely_inert(world: World) -> None:
    """The shipped state. No selection query, no intent, no adapter call."""
    world.armed.disarmed_at = NOW - timedelta(hours=1)
    world.session.flush()

    report = _run(world)

    assert report.may_open_possible is False
    assert report.open_lane == ""
    assert report.submitted == ()
    assert _events(world.session, ExecutionEventType.INTENT_CREATED) == []
    assert _events(world.session, ExecutionEventType.SUBMITTING) == []


def test_a_disarm_in_the_same_cycle_stops_the_open(world: World) -> None:
    """The sweep runs BEFORE the lane, so a strategy disarmed by this very cycle
    never opens in it."""
    world.version.status = StrategyStatus.EXPERIMENTAL
    world.session.flush()

    report = _run(world)

    assert any("status_change" in d for d in report.disarms), report.disarms
    assert report.submitted == ()
    assert _events(world.session, ExecutionEventType.SUBMITTING) == []


def test_an_expired_arming_opens_nothing(world: World) -> None:
    world.armed.expires_at = NOW - timedelta(minutes=1)
    world.session.flush()

    report = _run(world)

    assert report.submitted == ()


# ---------------------------------------------------------------------------
# One order per paper trade, ever
# ---------------------------------------------------------------------------


def test_a_second_cycle_does_not_submit_the_same_paper_trade_again(world: World) -> None:
    first = _run(world)
    assert first.submitted == (world.client_order_id(),)

    second = _run(world)

    assert second.submitted == ()
    assert "considered=1" in second.open_lane
    submitting = [
        e
        for e in _events(world.session, ExecutionEventType.SUBMITTING)
        if e.client_order_id == world.client_order_id()
    ]
    assert len(submitting) == 1, "one paper trade, one order, ever"


def test_a_manual_accept_never_becomes_an_order(session: Session) -> None:
    """§5.3 P6, read off the INDEXED actor column. ``accept_candidate`` is
    reachable from the CLI with no guard, so an ACCEPTED PaperTrade is not an
    authorisation predicate."""
    world = World(session, actor="local-user")

    report = _run(world)

    assert report.submitted == ()
    assert "considered=0" in report.open_lane
    assert _events(session, ExecutionEventType.SUBMITTING) == []


def test_a_rejected_simulation_is_not_a_decision_to_open(session: Session) -> None:
    world = World(session, decision=PaperDecision.REJECTED)

    assert _run(world).submitted == ()


def test_yesterdays_paper_trade_is_not_todays_order(session: Session) -> None:
    world = World(session, created_at=NOW - timedelta(days=1))

    assert _run(world).submitted == ()


def test_a_trade_with_no_simulated_size_is_refused(session: Session) -> None:
    """The lane submits the simulation's size or nothing. It never invents one."""
    world = World(session, shares=0)

    report = _run(world)

    assert report.submitted == ()
    assert any("no usable share count" in r for r in _refusals(session)), _refusals(session)


# ---------------------------------------------------------------------------
# The caps, the calendar and the kill switch
# ---------------------------------------------------------------------------


def test_the_daily_order_cap_refuses_the_order_that_would_cross_it(session: Session) -> None:
    """L1 counts SUBMITTING records, so a rejected order still consumed the
    day's allowance. With a cap of one, the second candidate is refused."""
    world = World(session, max_orders_per_day=1, extra_trades=1)

    report = _run(world)

    assert len(report.submitted) == 1, report.open_lane
    assert "considered=2" in report.open_lane
    assert any("L1" in r for r in _refusals(session)), _refusals(session)


def test_a_high_priced_instrument_cannot_pass_l2_under_v1(session: Session) -> None:
    """A FINDING, pinned rather than worked around.

    ``PREREGISTRATION_execution_limits_v1`` pairs a $1,000 dollar cap with a 0.5%
    percent-of-equity cap, and ``binding_cap`` takes the tighter. On the $25,000
    reference account that is **$125** — so no order in a $470 instrument can
    pass L2, not even a single share. The operator either sizes into low-priced
    instruments or supersedes the row under a v2 document; the software's job is
    to refuse clearly, which is what this asserts.
    """
    world = World(
        session, symbol="HIGHP", entry=470.0, stop=465.0, reference=470.0, fill_price=471.18
    )

    report = _run(world)

    assert report.submitted == ()
    reasons = _refusals(session)
    assert any("L2" in r and "binding cap 125.00" in r for r in reasons), reasons


def test_the_kill_switch_blocks_opening_and_leaves_closing_alone(world: World) -> None:
    report = _run(world, branch=CycleBranch.PROTECTIVE, kill=True)

    assert report.may_open_possible is False
    assert report.submitted == ()
    assert _events(world.session, ExecutionEventType.SUBMITTING) == []
    # The protective branch still RAN: that is the promise the switch keeps.
    assert report.branch is CycleBranch.PROTECTIVE
    assert _events(world.session, ExecutionEventType.CYCLE_PROTECTIVE)


def test_a_lapsed_dead_man_blocks_opening_and_still_drains(session: Session) -> None:
    from signalforge.db.models import WorkerHeartbeat

    world = World(session)
    for row in session.scalars(select(WorkerHeartbeat)):
        session.delete(row)
    session.flush()

    report = _run(world)

    assert report.submitted == ()
    assert report.dead_man_alive is False
    assert any("dead_man_lapse" in d for d in report.disarms), report.disarms


def test_inside_the_post_open_no_submit_window_nothing_is_submitted(world: World) -> None:
    """C2 — 13:35 UTC is 09:35 ET, five minutes after the open and inside the
    pre-registered 15-minute window."""
    report = _run(world, now=NOW.replace(hour=13, minute=35))

    assert report.submitted == ()


# ---------------------------------------------------------------------------
# The durable book
# ---------------------------------------------------------------------------


def test_a_fresh_adapter_instance_sees_the_same_book(world: World) -> None:
    """The point of the durable book: the next cycle builds a NEW adapter, and
    it has to hold what the last one filled — otherwise reconciliation is clean
    because the simulator forgot rather than because anything was explained."""
    _run(world)

    fresh = world.broker()

    assert [p.legs for p in fresh.positions()], "a fresh instance holds the position"
    assert fresh.order_status(world.client_order_id()) is not None
    assert fresh.book()[world.client_order_id()].state is OrderState.FILLED


def test_the_second_cycle_reconciles_that_book_clean(world: World) -> None:
    _run(world)

    second = _run(world)

    assert second.reconciliation_status == "CLEAN", second.blocked_reasons


def test_the_fingerprint_dedupe_survives_a_restart(world: World) -> None:
    """A1 / §5.4: 'a fresh id is not a fresh order' has to hold across a restart
    too, which it only can if the fingerprint is stored."""
    from signalforge.execution.intents import CostModelFeedback, IntentKind, OrderIntent

    _run(world)
    fresh = world.broker()

    duplicate = OrderIntent(
        client_order_id="a-brand-new-id",
        intent_kind=IntentKind.OPEN,
        side=OrderSide.BUY_TO_OPEN,
        qty=SHARES,
        limit_price=FILL_PRICE,
        shares_per_contract=1,
        adapter_name="paper_reference",
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
        cost_model=CostModelFeedback(modelled_fill_price=FILL_PRICE, modelled_spread_bps=5.0),
        symbol=SYMBOL,
        source_paper_trade_id=world.trade.id,
        state=OrderState.SUBMITTING,
    )
    result = fresh.place(duplicate)

    assert result.state is OrderState.REJECTED
    assert "economically identical" in result.error_verbatim


def test_a_retry_after_a_timeout_produces_one_fill_not_two(world: World) -> None:
    """The §8 hazard. The adapter records the order and then raises; the lane
    leaves the SUBMITTING record alone and never retries in the except block.
    The next cycle re-presents the SAME id, which A1 answers from the book."""
    broker = world.broker()
    broker.arm_timeout_once()

    report = cycle_mod.run_execution_cycle(
        world.session, _posture(), now=NOW, adapter=broker, actor="test"
    )

    assert report.submitted == (world.client_order_id(),)
    assert report.filled == (), "the caller never heard the response"

    # The lane recorded the ambiguity and did NOT retry. A retry in that except
    # block is how an ambiguous response becomes a double fill.
    calls = [
        e
        for e in _events(world.session, ExecutionEventType.ADAPTER_CALL)
        if e.client_order_id == world.client_order_id()
    ]
    assert any("may or may not have reached the broker" in e.reason for e in calls), [
        e.reason for e in calls
    ]
    assert any("never retried here" in e.reason for e in calls)

    # The local record stays SUBMITTING — the next cycle promotes it to UNKNOWN,
    # never to "failed".
    from signalforge.execution.oms import current_state, promote_stale_submitting

    assert current_state(world.session, world.client_order_id()) is OrderState.SUBMITTING

    # Meanwhile the broker DID take it, and a fresh instance proves the book
    # survived: a retry re-presenting the same id is answered from the book (A1)
    # rather than filling a second time.
    again = world.broker().order_status(world.client_order_id())
    assert again is not None and again.state is OrderState.FILLED

    promoted = promote_stale_submitting(
        world.session, now=NOW + timedelta(minutes=1), adapter_name="paper_reference"
    )
    assert world.client_order_id() in promoted
    assert current_state(world.session, world.client_order_id()) is OrderState.UNKNOWN


# ---------------------------------------------------------------------------
# The constant that must not drift
# ---------------------------------------------------------------------------


def test_the_modelled_spread_matches_the_ledger_and_the_simulator() -> None:
    from signalforge.execution.brokers.paper_reference import MODEL_SPREAD_BPS_FLOOR
    from signalforge.paper.ledger import _NOMINAL_SPREAD_BPS

    assert lane_mod.DEFAULT_MODELLED_SPREAD_BPS == _NOMINAL_SPREAD_BPS
    assert lane_mod.DEFAULT_MODELLED_SPREAD_BPS == MODEL_SPREAD_BPS_FLOOR
