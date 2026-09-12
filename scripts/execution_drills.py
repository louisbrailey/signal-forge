"""Phase V execution drills — executable, against ``paper_reference`` only.

D6 ADR §21 lists the drills each of which "must pass against
``brokers/paper_reference.py`` (local, deterministic, **no network**) before the
vendor paper adapter is written". Until now that list was prose. This module is
the list, executed.

**Safety, and it is the first thing in this file for a reason.**

* Every drill runs against a **scratch SQLite database created for this run**,
  in a temporary directory, migrated from scratch. :func:`refuse_if_live`
  inspects the effective database URL and **raises** rather than running if it
  resolves to anything that looks like the live file (``signalforge.sqlite``, or
  any path under the repository's ``data/`` directory). An ambient
  ``DATABASE_URL`` pointing at the live database is ignored and overridden, and
  the override is printed; if the override ever failed, the guard is what stops
  the run.
* ``SIGNALFORGE_DATA_DIR`` is redirected too, so the kill-switch state file, the
  execution-local kill state and the audit JSONL all land in the scratch tree
  and never touch the operator's.
* The only adapter used is ``paper_reference``: local, deterministic, network
  free. Nothing here reads a credential, and nothing here can reach a broker.
* **No drill arms anything in the live system.** Armings are written into the
  scratch database, which is deleted with the temporary directory.

Every drill is also a pytest (``tests/execution/test_phase_v_drills.py``), which
is how they run in CI. The drill functions below take a ``Session`` and build
their own world inside it; the scratch-database plumbing lives only in
:func:`main`, so the pytest path reuses the suite's own isolated session fixture
and the two paths execute identical assertions.

**No harness object any more, and that is the finding.** ``paper_reference``
``positions()`` returns the account's NET book and deliberately carries no
``originating_client_order_id`` — its docstring says per-structure attribution
"is not a broker fact and is not invented here: it is the OMS's, reconstructed
from ``execution_event``". ``reconcile.py`` reads exactly that attribute and
treats its absence as a ``FOREIGN_POSITION`` divergence. The 2026-09-12 run of
these drills found that **nothing in the tree performed the reconstruction**, so
``paper_reference`` could never reconcile CLEAN while it held a position, and the
drills ran against a local wrapper (``OmsAttributedBook``) that was not
production code. That gap is now CLOSED in ``src/``:
:func:`signalforge.execution.oms.attribute_positions` does the reconstruction the
ADR assigns to the OMS, ``reconcile()`` calls it, and the drills use the bare
adapter. Drill V0 asserts the closure — and asserts that a position with no local
pre-submission record is still foreign, which is the property the wrapper could
only be *configured* to have.

Usage::

    python scripts/execution_drills.py --all
    python scripts/execution_drills.py --name V1 --name V9
    python scripts/execution_drills.py --all --dry-run     # list, run nothing

The run writes a dated report under ``docs/research/execution_drills/``.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Anything matching these is the operator's real database and is never touched.
LIVE_DB_BASENAMES = ("signalforge.sqlite",)
LIVE_DB_DIRS = (REPO_ROOT / "data",)

#: The drill clock. 2026-09-11 15:00 UTC is 11:00 ET on a Friday regular
#: session: 90 minutes after the open and 300 before the close, so it sits
#: outside both 15-minute no-submit windows and a drill that means to test a
#: window has to say so.
DRILL_NOW = datetime(2026, 9, 11, 15, 0, tzinfo=UTC)

SIM_ACCOUNT_SUFFIX = "DRILL-1"
SHORT_PUT = "SPY261218P00460000"
LONG_PUT = "SPY261218P00455000"


class LiveDatabaseRefused(RuntimeError):
    """The drill runner was pointed at something that looks like the live DB."""


def refuse_if_live(url: str) -> None:
    """Raise unless ``url`` is safely a scratch database.

    Deliberately crude and deliberately loud: it matches on the file name and on
    the repository's own ``data/`` directory rather than trying to be clever
    about which database is "really" live. A false refusal costs a rename; a
    false pass costs the operator's probation record.
    """
    if not url.startswith("sqlite"):
        raise LiveDatabaseRefused(
            f"the drills run against SQLite only; refusing {url.split('://')[0]!r}"
        )
    raw = url.split("///", 1)[-1]
    if not raw or raw == ":memory:":
        return
    path = Path(raw).resolve()
    if path.name in LIVE_DB_BASENAMES:
        raise LiveDatabaseRefused(
            f"REFUSED: {path} is named like the live database. The drills never run against "
            "the live file — they write armings, kill states and execution events."
        )
    for parent in LIVE_DB_DIRS:
        if parent.resolve() in path.parents:
            raise LiveDatabaseRefused(
                f"REFUSED: {path} is under {parent}, which holds the live database."
            )


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Check:
    label: str
    passed: bool
    detail: str = ""


@dataclass
class DrillOutcome:
    """What one drill observed. ``checks`` is never empty on a real run: a drill
    that asserted nothing is a drill that did not run."""

    checks: list[Check] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def check(self, label: str, passed: bool, detail: str = "") -> bool:
        self.checks.append(Check(label, bool(passed), detail))
        return bool(passed)

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(c.passed for c in self.checks)

    @property
    def first_failure(self) -> str:
        for c in self.checks:
            if not c.passed:
                return f"{c.label}: {c.detail}" if c.detail else c.label
        return ""


@dataclass(frozen=True, slots=True)
class Drill:
    name: str
    title: str
    pass_condition: str
    run: Callable[[Any, datetime], DrillOutcome]
    in_adr: bool = True


@dataclass(frozen=True, slots=True)
class DrillResult:
    drill: Drill
    outcome: DrillOutcome
    error: str = ""

    @property
    def passed(self) -> bool:
        return not self.error and self.outcome.passed


# ---------------------------------------------------------------------------
# World building — the same facts tests/execution/conftest.py assembles, built
# here because scripts/ must not import tests/.
# ---------------------------------------------------------------------------

#: The §7b / decision 4 grid centres. Must equal
#: ``tests/execution/conftest.py::LIMIT_GRID_CENTRES`` and the values tabulated
#: in ``docs/PREREGISTRATION_execution_limits_v1.md``; a test asserts all three.
LIMIT_GRID_CENTRES: dict[str, Any] = {
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


@dataclass
class World:
    """Everything a drill might need, built once per drill on a clean session."""

    session: Any
    now: datetime
    account: Any = None
    strategy: Any = None
    version: Any = None
    candidate: Any = None
    paper_trade: Any = None
    limits_row: Any = None
    armed: Any = None
    adapter: Any = None
    broker: Any = None
    suffix: str = ""
    approved: bool = False

    @property
    def account_id(self) -> str:
        from signalforge.execution.brokers.paper_reference import SIMULATED_ACCOUNT_PREFIX

        return f"{SIMULATED_ACCOUNT_PREFIX}{SIM_ACCOUNT_SUFFIX}{self.suffix.upper()}"


def seed_research_state(
    session: Any, now: datetime, *, manual_actor: bool = False, suffix: str = ""
) -> World:
    """A PAPER_APPROVED version with one gate-PASSED candidate and one paper
    trade from the automatic actor (or, for V14, from a human).

    ``suffix`` exists so one drill can build two independent worlds in one
    database without colliding on the unique symbol/strategy names.
    """
    from sqlalchemy import select

    from signalforge.db.models import (
        Candidate,
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
    from signalforge.paper.auto_simulate import AUTO_SIM_ACTOR

    world = World(session=session, now=now, suffix=suffix)
    world.account = PaperAccount(
        name=f"drill{suffix}", initial_cash=Decimal("25000"), cash=Decimal("25000")
    )
    session.add(world.account)
    inst = session.scalar(select(Instrument).where(Instrument.symbol == "SPY"))
    if inst is None:
        inst = Instrument(symbol="SPY", name="SPDR", instrument_type="etf", sector="Broad")
        session.add(inst)
    session.flush()

    world.strategy = Strategy(
        name=f"trend_continuation.short_swing{suffix}",
        horizon=Horizon.SHORT_SWING,
        permits_long=True,
        permits_short=False,
        status=StrategyStatus.PAPER_APPROVED,
    )
    session.add(world.strategy)
    session.flush()
    world.version = StrategyVersion(
        strategy_id=world.strategy.id,
        version="0.1.0",
        git_sha="drill",
        spec_json={},
        status=StrategyStatus.PAPER_APPROVED,
    )
    session.add(world.version)
    session.flush()

    scan = ScanRun(
        horizon=Horizon.SHORT_SWING,
        started_at=now,
        config_hash="cfg",
        source="massive",
        universe_json=["SPY"],
    )
    session.add(scan)
    session.flush()
    world.candidate = Candidate(
        scan_run_id=scan.id,
        instrument_id=inst.id,
        strategy_version_id=world.version.id,
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
    session.add(world.candidate)
    session.flush()

    actor = "local-user" if manual_actor else AUTO_SIM_ACTOR
    world.paper_trade = PaperTrade(
        account_id=world.account.id,
        candidate_id=world.candidate.id,
        decision=PaperDecision.ACCEPTED,
        signal_snapshot_json={"decision": {"actor": actor, "automatic": not manual_actor}},
        plan_json={"shares": 1},
        why_qualified="trend",
        why_might_fail="regime flip",
        actor=actor,
        created_at=now,
    )
    session.add(world.paper_trade)
    session.flush()
    return world


def seed_limits(session: Any, now: datetime, **overrides: Any) -> Any:
    """The pre-registered row, created 30 days back so §7b rule 3's evidence
    window is not the thing under test in every other drill."""
    from signalforge.db.models import ExecutionLimits

    values = dict(LIMIT_GRID_CENTRES)
    values.update(overrides)
    row = ExecutionLimits(created_at=now - timedelta(days=30), created_by="drill", **values)
    session.add(row)
    session.flush()
    return row


def seed_approval(session: Any, world: World) -> None:
    """A passing sealed test and a passing evaluation whose scope hashes equal
    the LIVE ones — read from the same functions the ceremony reads, never
    hard-coded."""
    from signalforge.db.models import (
        DataSnapshot,
        StrategyPromotionEvaluation,
        StrategySealedTest,
    )
    from signalforge.research.approval_scope import current_spec_json_hash
    from signalforge.settings_store import effective_research_config

    if world.approved:
        return
    snapshot = DataSnapshot(key=f"drill_snapshot_{world.version.id}", symbols_json=["SPY"])
    session.add(snapshot)
    session.flush()
    sealed = StrategySealedTest(
        strategy_version_id=world.version.id,
        dataset_snapshot_id=snapshot.id,
        window_start=date(2024, 1, 2),
        window_end=date(2025, 1, 2),
        universe_json=["SPY"],
        passed=True,
        evaluated_at=world.now - timedelta(days=30),
    )
    session.add(sealed)
    session.flush()
    config_hash = effective_research_config(session).config_hash
    spec_hash = current_spec_json_hash(session, world.version.id) or ""
    session.add(
        StrategyPromotionEvaluation(
            strategy_version_id=world.version.id,
            dataset_snapshot_id=snapshot.id,
            evaluated_at=world.now - timedelta(days=29),
            config_hash=config_hash,
            spec_json_hash=spec_hash,
            universe_json=["SPY"],
            window_start=date(2024, 1, 2),
            window_end=date(2025, 1, 2),
            data_provenance_json={"sources": ["massive"]},
            passed=True,
            verdict="PAPER_APPROVED",
            sealed_test_id=sealed.id,
        )
    )
    session.flush()
    world.approved = True


def seed_evidence(session: Any, world: World, *, n: int = 20, pnl: float = 0.5) -> None:
    """``n`` closed paper positions at a fixed R, for decision 10's counter.

    Entry 100, stop 99 => $1 of per-share risk on one share, so ``pnl`` IS the
    R-multiple the health monitor computes.
    """
    from sqlalchemy import select

    from signalforge.db.models import Instrument, PaperPosition
    from signalforge.domain import Horizon, PositionSide

    inst = session.scalar(select(Instrument).where(Instrument.symbol == "SPY"))
    when = world.now - timedelta(days=1)
    for i in range(n):
        session.add(
            PaperPosition(
                account_id=world.account.id,
                instrument_id=inst.id,
                strategy_version_id=world.version.id,
                horizon=Horizon.SHORT_SWING,
                side=PositionSide.LONG,
                qty=1,
                avg_price=Decimal("100"),
                stop_level=99.0,
                opened_at=when - timedelta(days=2),
                closed_at=when + timedelta(seconds=i),
                realized_pnl=Decimal(str(pnl)),
            )
        )
    session.flush()


def seed_armed(
    session: Any,
    world: World,
    *,
    expires_in_days: float = 6.0,
    account_id: str | None = None,
) -> Any:
    """An ``armed_strategy`` row written directly.

    Written rather than earned through :func:`signalforge.execution.arming.arm`
    on purpose: the drills that test the *ceremony* call ``arm()`` and watch it
    refuse; the drills that test what happens *while armed* need the row and
    should not also be a test of the ceremony.

    The approved scope is seeded first if it has not been: without it the very
    first auto-disarm sweep fires on ``approved_scope_mismatch`` and every drill
    below would "pass" for the wrong reason.
    """
    from signalforge.db.models import ArmedStrategy
    from signalforge.execution.brokers.paper_reference import PAPER_REFERENCE_NAME
    from signalforge.research.approval_scope import current_spec_json_hash
    from signalforge.settings_store import effective_research_config

    seed_approval(session, world)
    row = ArmedStrategy(
        strategy_version_id=world.version.id,
        structure_type="equity",
        armed_at=world.now - timedelta(days=1),
        armed_by="drill",
        expires_at=world.now + timedelta(days=expires_in_days),
        adapter_name=PAPER_REFERENCE_NAME,
        broker_account_id_expected=account_id or world.account_id,
        max_notional_usd=1_000.0,
        max_orders_per_day=10,
        evidence_paper_trade_count=20,
        evidence_expectancy_r=0.5,
        sealed_look_prior_at_arm=1,
        preregistration_doc_id=LIMIT_GRID_CENTRES["preregistration_doc_id"],
        execution_limits_id=world.limits_row.id if world.limits_row is not None else None,
        spec_json_hash=current_spec_json_hash(session, world.version.id) or "",
        config_hash=effective_research_config(session).config_hash,
    )
    session.add(row)
    session.flush()
    return row


def drill_quotes(now: datetime, **available: int | None) -> Any:
    """The pre-submission information set. Every quote is stamped strictly
    before ``now``; a quote at or after submission is refused as lookahead."""
    from signalforge.execution.brokers.paper_reference import (
        PreSubmissionInformation,
        ReferenceQuote,
    )

    as_of = now - timedelta(minutes=1)
    return PreSubmissionInformation.of(
        [
            ReferenceQuote("SPY", 470.0, as_of, available_qty=available.get("SPY")),
            ReferenceQuote(SHORT_PUT, 3.00, as_of, available_qty=available.get("short")),
            ReferenceQuote(LONG_PUT, 1.40, as_of, available_qty=available.get("long")),
        ]
    )


def make_adapter(
    session: Any,
    world: World,
    *,
    expected_account_id: str | None = None,
    is_open: bool = True,
    clock_at: datetime | None = None,
    information: Any = None,
) -> Any:
    """The bare ``paper_reference`` adapter — no wrapper, no harness.

    Position-origin attribution is the OMS's
    (:func:`signalforge.execution.oms.attribute_positions`, called by
    ``reconcile``), so every drill below drives exactly the object an armed
    session would.
    """
    from signalforge.execution.brokers.paper_reference import (
        ExecutionEventAudit,
        MarketClock,
        PaperReferenceBroker,
        SimulatedAccount,
    )

    broker = PaperReferenceBroker(
        audit=ExecutionEventAudit(session),
        account=SimulatedAccount(account_id=world.account_id, initial_cash=25_000.0),
        expected_account_id=expected_account_id or world.account_id,
        information=information or drill_quotes(world.now),
        clock=MarketClock(is_open=is_open, as_of=clock_at or world.now),
    )
    world.broker = broker
    world.adapter = broker
    return broker


def equity_intent(
    world: World,
    *,
    side: Any = None,
    qty: int = 1,
    limit_price: float = 475.0,
    client_order_id: str = "",
    kind: Any = None,
) -> Any:
    from signalforge.execution.intents import (
        CostModelFeedback,
        IntentKind,
        OrderIntent,
        OrderLeg,
        OrderSide,
        client_order_id_for,
    )
    from signalforge.execution.states import OrderState

    side = side or OrderSide.BUY_TO_OPEN
    leg = OrderLeg(side=side, ratio=1, shares_per_contract=1, symbol="SPY")
    return OrderIntent(
        client_order_id=client_order_id
        or client_order_id_for(source_trade_id=world.paper_trade.id, legs=[leg]),
        intent_kind=kind or IntentKind.OPEN,
        side=side,
        qty=qty,
        limit_price=limit_price,
        shares_per_contract=1,
        adapter_name="paper_reference",
        created_at=world.now,
        expires_at=world.now + timedelta(minutes=15),
        cost_model=CostModelFeedback(modelled_fill_price=470.0, modelled_spread_bps=5.0),
        symbol="SPY",
        source_paper_trade_id=world.paper_trade.id,
        strategy_version_id=world.version.id,
        armed_strategy_id=world.armed.id if world.armed is not None else None,
        execution_limits_id=world.limits_row.id if world.limits_row is not None else None,
        state=OrderState.CREATED,
    )


def short_vertical_intent(world: World, *, contracts: int = 2) -> Any:
    from signalforge.execution.intents import (
        ComboOrderIntent,
        CostModelFeedback,
        IntentKind,
        OrderLeg,
        OrderSide,
        StructureType,
        client_order_id_for,
    )
    from signalforge.execution.states import OrderState

    legs = (
        OrderLeg(
            side=OrderSide.SELL_TO_OPEN,
            ratio=1,
            shares_per_contract=100,
            option_ticker=SHORT_PUT,
            strike=460.0,
        ),
        OrderLeg(
            side=OrderSide.BUY_TO_OPEN,
            ratio=1,
            shares_per_contract=100,
            option_ticker=LONG_PUT,
            strike=455.0,
        ),
    )
    return ComboOrderIntent(
        client_order_id=client_order_id_for(source_trade_id=world.paper_trade.id, legs=legs),
        intent_kind=IntentKind.OPEN,
        legs=legs,
        contracts=contracts,
        net_limit_price=1.20,
        structure_type=StructureType.SHORT_VERTICAL,
        adapter_name="paper_reference",
        created_at=world.now,
        expires_at=world.now + timedelta(minutes=15),
        cost_model=CostModelFeedback(modelled_fill_price=1.60, modelled_spread_bps=5.0),
        source_paper_trade_id=world.paper_trade.id,
        strategy_version_id=world.version.id,
        armed_strategy_id=world.armed.id if world.armed is not None else None,
        execution_limits_id=world.limits_row.id if world.limits_row is not None else None,
        state=OrderState.CREATED,
    )


def submit_through_oms(session: Any, adapter: Any, intent: Any) -> Any:
    """The durable path: CREATED → VALIDATED → SUBMITTING is written and
    COMMITTED, then the adapter is called. Exactly the §6/§8 order, and the
    state machine refuses any shortcut through it."""
    from signalforge.execution.intents import ComboOrderIntent
    from signalforge.execution.oms import record_submitting, transition
    from signalforge.execution.states import OrderState

    validated = transition(
        session, intent, OrderState.VALIDATED, reason="drill: gates evaluated", actor="drill"
    )
    submitting = record_submitting(session, validated)
    if isinstance(submitting, ComboOrderIntent):
        return adapter.place_combo(submitting)
    return adapter.place(submitting)


def reconciled_position(
    world: World, *, origin: str, diverged: bool = False, reachable: bool = True
) -> Any:
    """The broker's book as the close lane's five positive proofs see it."""
    from signalforge.execution.intents import ReconciledPosition

    snapshots = list(world.broker.positions())
    legs = tuple(snapshots[0].legs) if snapshots else ()
    return ReconciledPosition(
        adapter_name="paper_reference",
        legs=legs,
        originating_client_order_id=origin,
        reconciled=bool(legs),
        adapter_reachable=reachable,
        reconciliation_diverged=diverged,
        as_of=world.now,
    )


def open_context(world: World, **overrides: Any) -> Any:
    """An ``OpenGateContext`` in which every check passes, for drills that then
    break exactly one of them."""
    from signalforge.execution.limits import ArmedFacts, OpenGateContext

    base: dict[str, Any] = {
        "now": world.now,
        "adapter_name": "paper_reference",
        "kill_switch_engaged": False,
        "execution_kill_engaged": False,
        "dead_man_alive": True,
        "market_open_broker": True,
        "market_open_calendar": True,
        "minutes_since_open": 90.0,
        "minutes_until_close": 300.0,
        "is_early_close_session": False,
        "armed": ArmedFacts(
            adapter_name="paper_reference",
            expires_at=world.now + timedelta(days=6),
            disarmed=False,
            structure_type="equity",
            approval_level_permits_structure=True,
        ),
        "is_paper_proven_this_cycle": True,
        "intent_expires_at": world.now + timedelta(minutes=15),
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
    return OpenGateContext(**base)


def limit_set(world: World) -> Any:
    from signalforge.execution.limits import limit_set_from_row

    return limit_set_from_row(world.limits_row)


def observed_events(session: Any, *, after_id: int = 0, limit: int = 40) -> list[str]:
    """The ``execution_event`` rows a drill produced, newest last.

    The audit rows are part of a drill's result, not a debugging aid: §15
    requires both spines, and a drill that cannot show the record it wrote has
    not demonstrated the record exists.
    """
    from sqlalchemy import select

    from signalforge.db.models import ExecutionEvent

    rows = list(
        session.scalars(
            select(ExecutionEvent).where(ExecutionEvent.id > after_id).order_by(ExecutionEvent.id)
        )
    )
    out: list[str] = []
    for row in rows[-limit:]:
        arrow = (
            f" {row.state_from or '-'}→{row.state_to}" if (row.state_to or row.state_from) else ""
        )
        cid = f" {row.client_order_id[:12]}" if row.client_order_id else ""
        out.append(f"{row.event_type}{cid}{arrow} — {(row.reason or '')[:120]}")
    return out


def max_event_id(session: Any) -> int:
    from sqlalchemy import func, select

    from signalforge.db.models import ExecutionEvent

    return int(session.scalar(select(func.max(ExecutionEvent.id))) or 0)


def event_types(session: Any, *, after_id: int = 0) -> list[str]:
    from sqlalchemy import select

    from signalforge.db.models import ExecutionEvent

    return list(
        session.scalars(
            select(ExecutionEvent.event_type)
            .where(ExecutionEvent.id > after_id)
            .order_by(ExecutionEvent.id)
        )
    )


def fake_clock() -> tuple[Callable[[], float], Callable[[float], None]]:
    """A monotonic/sleep pair so the drain's bound is exercised without spending
    it. The bound is what is under test, not the wall clock."""
    ticks = {"t": 0.0}

    def monotonic() -> float:
        return ticks["t"]

    def sleep(seconds: float) -> None:
        ticks["t"] += max(seconds, 0.1)

    return monotonic, sleep


# ---------------------------------------------------------------------------
# The drills
# ---------------------------------------------------------------------------


def drill_v0(session: Any, now: datetime) -> DrillOutcome:
    """V0 — OMS-side position-origin attribution, in ``src/`` (the closed gap)."""
    from signalforge.execution.oms import attribute_positions
    from signalforge.execution.reconcile import reconcile

    out = DrillOutcome()
    world = seed_research_state(session, now)
    world.limits_row = seed_limits(session, now)
    world.armed = seed_armed(session, world)
    adapter = make_adapter(session, world)

    intent = equity_intent(world)
    submit_through_oms(session, adapter, intent)

    # 1. The broker still owes us nothing. That has not changed and must not.
    raw_snapshots = list(world.broker.positions())
    out.check(
        "paper_reference.positions() still carries no originating_client_order_id",
        bool(raw_snapshots)
        and all(not getattr(s, "originating_client_order_id", "") for s in raw_snapshots),
        f"{len(raw_snapshots)} snapshot(s)",
    )

    # 2. The OMS reconstructs it, from its own pre-submission records.
    attributed = attribute_positions(
        session, adapter_name="paper_reference", positions=raw_snapshots
    )
    out.check(
        "the OMS attributes the position to the order that opened it",
        bool(attributed) and attributed[0].originating_client_order_id == intent.client_order_id,
        str([p.originating_client_order_id for p in attributed]),
    )

    # 3. So the BARE adapter — no wrapper, no harness — reconciles CLEAN while
    #    holding a position. This is the check the gap made impossible.
    clean = reconcile(session, adapter, now=now, limits=limit_set(world), actor="drill")
    out.check(
        "paper_reference reconciles CLEAN while holding a position",
        clean.clean,
        clean.detail[:200],
    )

    # 4. And it explains only what it can explain. One more share appears in the
    #    same instrument, placed STRAIGHT at the broker with no OMS
    #    pre-submission record: the leg no longer matches what local records
    #    account for, and "mostly ours" is not a category.
    adapter.place(
        equity_intent(world, client_order_id="v0-never-authorised", qty=2, limit_price=476.0)
    )
    partial = attribute_positions(
        session, adapter_name="paper_reference", positions=list(adapter.positions())
    )
    out.check(
        "a leg the local record only partly explains is NOT attributed",
        bool(partial) and not partial[0].originating_client_order_id,
        str([p.unexplained for p in partial]),
    )
    after = reconcile(session, adapter, now=now, limits=limit_set(world), actor="drill")
    out.check(
        "and reconciliation says FOREIGN_POSITION, unrepaired",
        after.diverged and any(d.kind == "FOREIGN_POSITION" for d in after.divergences),
        after.first_divergence[:200],
    )
    out.notes.append(
        "GAP CLOSED: §10's position-origin reconstruction now lives in src/ "
        "(signalforge.execution.oms.attribute_positions, called by reconcile). The drill-local "
        "OmsAttributedBook wrapper is gone and every drill below drives the bare adapter. "
        "Attribution explains a position from the OMS's OWN SUBMITTING records and never "
        "repairs one: anything it cannot explain exactly stays FOREIGN_POSITION."
    )
    out.events = observed_events(session)
    return out


def drill_v1(session: Any, now: datetime) -> DrillOutcome:
    """V1 — kill switch engaged with an open position."""
    from signalforge.db.models import JobRun
    from signalforge.execution.cycle import EXECUTION_CYCLE_JOB, run_execution_cycle
    from signalforge.execution.events import ExecutionEventType
    from signalforge.execution.intents import (
        CostModelFeedback,
        OrderLeg,
        OrderSide,
        build_close_intent,
    )
    from signalforge.execution.limits import may_open
    from signalforge.execution.oms import (
        CycleBranch,
        execution_guarded,
        read_cycle_posture,
        write_execution_kill_state,
    )
    from signalforge.execution.states import OrderState

    out = DrillOutcome()
    world = seed_research_state(session, now)
    world.limits_row = seed_limits(session, now)
    world.armed = seed_armed(session, world)
    adapter = make_adapter(session, world)

    filled = submit_through_oms(session, adapter, equity_intent(world))
    out.check("an opening order filled before the switch", filled.state is OrderState.FILLED)
    # A resting (unmarketable) order, so cancel_all has something to cancel.
    resting = submit_through_oms(
        session, adapter, equity_intent(world, limit_price=460.0, client_order_id="drill-resting")
    )
    out.check("a working order is resting at the broker", resting.state is OrderState.SUBMITTING)

    write_execution_kill_state(engaged=True, reason="V1 drill", actor="drill", now=now)
    posture = read_cycle_posture()
    out.check("posture is the PROTECTIVE branch", posture.branch is CycleBranch.PROTECTIVE)
    out.check("may_open is False by construction", posture.may_open is False)
    out.check("may_close is True — the one promise", posture.may_close is True)

    before = max_event_id(session)
    monotonic, sleep = fake_clock()
    report = run_execution_cycle(
        session, posture, now=now, adapter=adapter, monotonic=monotonic, sleep=sleep, actor="drill"
    )
    types = event_types(session, after_id=before)
    out.check("a CYCLE_PROTECTIVE event was written", ExecutionEventType.CYCLE_PROTECTIVE in types)
    out.check("cancel_all() ran", report.cancelled == 1, f"cancelled={report.cancelled}")
    kill_idx = [i for i, t in enumerate(types) if t == ExecutionEventType.KILL_SWITCH]
    recon_idx = [
        i
        for i, t in enumerate(types)
        if t in (ExecutionEventType.RECONCILED, ExecutionEventType.RECONCILIATION_DIVERGED)
    ]
    out.check(
        "the §8 order ran: reconcile → drain/cancel_all → reconcile again",
        bool(kill_idx) and len(recon_idx) >= 2 and recon_idx[0] < kill_idx[0] < recon_idx[-1],
        f"reconcile at {recon_idx}, kill/drain at {kill_idx}",
    )

    ctx = open_context(world, execution_kill_engaged=True)
    decision = may_open(ctx, limit_set(world))
    out.check(
        "may_open is blocked, naming K2",
        not decision.allowed and "K2" in (decision.first_failure or ""),
        decision.first_failure or "",
    )

    position = reconciled_position(world, origin=filled.client_order_id)
    close = build_close_intent(
        session,
        position=position,
        legs=[OrderLeg(side=OrderSide.SELL_TO_CLOSE, ratio=1, shares_per_contract=1, symbol="SPY")],
        contracts=1,
        limit_price=465.0,
        cost_model=CostModelFeedback(modelled_fill_price=470.0, modelled_spread_bps=5.0),
        now=now,
        max_intent_age_minutes=15,
        execution_limits_id=world.limits_row.id,
    )
    result = submit_through_oms(session, adapter, close)
    out.check(
        "a PROTECTIVE_CLOSE still constructs AND still submits with the switch engaged",
        result.state is OrderState.FILLED,
        f"{result.state.value}: {result.error_verbatim[:120]}",
    )

    # The JobRun half of the pass condition, through the real wrapper.
    session.commit()
    execution_guarded(EXECUTION_CYCLE_JOB, lambda p: f"drill branch={p.branch.value}")()
    session.expire_all()
    from sqlalchemy import select

    runs = list(session.scalars(select(JobRun).where(JobRun.name == EXECUTION_CYCLE_JOB)))
    out.check(
        "execution_guarded wrote a JobRun naming the protective branch",
        bool(runs) and any("protective" in (r.detail or "") for r in runs),
        runs[-1].detail if runs else "no JobRun",
    )
    out.events = observed_events(session, after_id=before)
    return out


def drill_v2(session: Any, now: datetime) -> DrillOutcome:
    """V2 — dead-man lapse: blocked, drained, disarmed, NOT liquidated."""
    from signalforge.db.models import WorkerHeartbeat
    from signalforge.execution.arming import DisarmTrigger
    from signalforge.execution.cycle import run_execution_cycle
    from signalforge.execution.deadman import DEAD_MAN_WORKER, assess
    from signalforge.execution.events import ExecutionEventType
    from signalforge.execution.limits import CloseGateContext, may_close, may_open
    from signalforge.execution.oms import CycleBranch, read_cycle_posture
    from signalforge.execution.states import OrderState

    out = DrillOutcome()
    world = seed_research_state(session, now)
    world.limits_row = seed_limits(session, now)
    world.armed = seed_armed(session, world)
    adapter = make_adapter(session, world)

    filled = submit_through_oms(session, adapter, equity_intent(world))
    submit_through_oms(
        session, adapter, equity_intent(world, limit_price=460.0, client_order_id="drill-resting")
    )
    book_before = {k: v.filled_units for k, v in world.broker.book().items()}

    session.add(
        WorkerHeartbeat(
            worker=DEAD_MAN_WORKER,
            started_at=now - timedelta(hours=1),
            last_beat_at=now - timedelta(minutes=10),
        )
    )
    session.flush()
    state = assess(session, now=now, stale_after_s=limit_set(world).execution_stale_after_s)
    out.check("the dead man has LAPSED", state.lapsed, state.detail[:160])

    posture = read_cycle_posture()
    out.check("the posture is still the FULL branch", posture.branch is CycleBranch.FULL)
    before = max_event_id(session)
    monotonic, sleep = fake_clock()
    report = run_execution_cycle(
        session, posture, now=now, adapter=adapter, monotonic=monotonic, sleep=sleep, actor="drill"
    )
    types = event_types(session, after_id=before)
    out.check("a DEAD_MAN_LAPSE event was written", ExecutionEventType.DEAD_MAN_LAPSE in types)
    out.check("the drain sequence ran", ExecutionEventType.KILL_SWITCH in types)
    out.check("cancel_all() ran", report.cancelled == 1, f"cancelled={report.cancelled}")
    out.check(
        "auto-disarm fired with the dead-man trigger",
        any(DisarmTrigger.DEAD_MAN.value in d for d in report.disarms),
        str(report.disarms),
    )

    book_after = {k: v.filled_units for k, v in world.broker.book().items()}
    out.check(
        "NO auto-liquidation: the filled position is untouched",
        book_after[filled.client_order_id] == book_before[filled.client_order_id],
    )
    closes = [o for o in world.broker.book().values() if o.intent_kind == "PROTECTIVE_CLOSE"]
    out.check("the cycle submitted no close of its own", not closes, f"{len(closes)} closes")
    out.check(
        "the resting order was CANCELLED, not filled",
        world.broker.book()["drill-resting"].state is OrderState.CANCELLED,
    )

    decision = may_open(open_context(world, dead_man_alive=False), limit_set(world))
    out.check(
        "may_open is blocked, naming D1",
        not decision.allowed and "D1" in (decision.first_failure or ""),
        decision.first_failure or "",
    )
    close_ok = may_close(
        CloseGateContext(
            position_exists_and_reconciled=True,
            originating_event_exists=True,
            non_increasing_in_every_leg=True,
            intent_kind_is_protective_close=True,
            adapter_reachable=True,
            reconciliation_diverged=False,
        )
    )
    out.check("may_close remains open through the lapse", close_ok.allowed)
    out.events = observed_events(session, after_id=before)
    return out


def drill_v3(session: Any, now: datetime) -> DrillOutcome:
    """V3 — reconciliation divergence: halt, disarm, and NEVER auto-correct."""
    from signalforge.execution.arming import CycleFacts, DisarmTrigger, auto_disarm_sweep
    from signalforge.execution.cycle import run_execution_cycle
    from signalforge.execution.events import ExecutionEventType
    from signalforge.execution.oms import read_cycle_posture
    from signalforge.execution.reconcile import reconcile

    out = DrillOutcome()
    world = seed_research_state(session, now)
    world.limits_row = seed_limits(session, now)
    world.armed = seed_armed(session, world)
    adapter = make_adapter(session, world)

    # A position with no matching client_order_id: placed straight at the
    # adapter, with no OMS pre-submission record of it at all. The adapter
    # writes its own FILL events for it — which is exactly why attribution
    # reads the OMS's SUBMITTING records and not "any event naming this id".
    world.broker.place(equity_intent(world, client_order_id="foreign-order"))
    before = max_event_id(session)
    result = reconcile(session, adapter, now=now, limits=limit_set(world), actor="drill")
    out.check("reconciliation is DIVERGED", result.diverged, result.detail[:160])
    out.check(
        "the divergence is a FOREIGN_POSITION",
        any(d.kind == "FOREIGN_POSITION" for d in result.divergences),
        result.first_divergence[:160],
    )
    out.check(
        "a RECONCILIATION_DIVERGED event was written",
        ExecutionEventType.RECONCILIATION_DIVERGED in event_types(session, after_id=before),
    )

    book_before = dict(world.broker.book())
    disarms = auto_disarm_sweep(
        session,
        now=now,
        facts=CycleFacts(reconciliation_diverged=True),
        adapter_name="paper_reference",
        actor="drill",
    )
    out.check(
        "the arming was disarmed with the reconciliation trigger",
        any(d.trigger is DisarmTrigger.RECONCILIATION for d in disarms),
        str([d.trigger.value for d in disarms]),
    )
    out.check(
        "NOT auto-corrected: the broker's book is byte-identical afterwards",
        {k: (v.state, v.filled_units) for k, v in world.broker.book().items()}
        == {k: (v.state, v.filled_units) for k, v in book_before.items()},
    )

    posture = read_cycle_posture()
    monotonic, sleep = fake_clock()
    report = run_execution_cycle(
        session, posture, now=now, adapter=adapter, monotonic=monotonic, sleep=sleep, actor="drill"
    )
    out.check(
        "the cycle refuses to open",
        report.may_open_possible is False,
        "; ".join(report.blocked_reasons)[:200],
    )
    out.events = observed_events(session, after_id=before)
    return out


def drill_v4(session: Any, now: datetime) -> DrillOutcome:
    """V4 — reconciliation staleness blocks exactly as a dead-man lapse does."""
    from signalforge.execution.arming import CycleFacts, DisarmTrigger, auto_disarm_sweep
    from signalforge.execution.limits import may_open
    from signalforge.execution.reconcile import last_clean_reconciliation_age_s

    out = DrillOutcome()
    world = seed_research_state(session, now)
    world.limits_row = seed_limits(session, now)
    world.armed = seed_armed(session, world)
    limits = limit_set(world)

    age = last_clean_reconciliation_age_s(session, adapter_name="paper_reference", now=now)
    out.check(
        "never reconciled is None, which is not 'reconciled 3 seconds ago'", age is None, str(age)
    )
    out.check(
        "a None age blocks on R1",
        not may_open(open_context(world, reconciliation_age_s=None), limits).allowed,
    )

    stale = may_open(open_context(world, reconciliation_age_s=300.0), limits)
    lapsed = may_open(open_context(world, dead_man_alive=False), limits)
    out.check(
        "an age past max_reconciliation_age_s blocks",
        not stale.allowed and "R1" in (stale.first_failure or ""),
        stale.first_failure or "",
    )
    out.check(
        "it blocks EXACTLY as a dead-man lapse does — both refuse, neither warns",
        not stale.allowed and not lapsed.allowed,
    )
    fresh = may_open(open_context(world, reconciliation_age_s=119.0), limits)
    out.check("119s < 120s still opens", fresh.allowed, fresh.first_failure or "")

    before = max_event_id(session)
    disarms = auto_disarm_sweep(
        session,
        now=now,
        facts=CycleFacts(reconciliation_age_s=300.0, max_reconciliation_age_s=120),
        adapter_name="paper_reference",
        actor="drill",
    )
    out.check(
        "staleness disarms too",
        any(d.trigger is DisarmTrigger.RECONCILIATION for d in disarms),
        str([d.trigger.value for d in disarms]),
    )
    out.events = observed_events(session, after_id=before)
    return out


def drill_v5(session: Any, now: datetime) -> DrillOutcome:
    """V5 — a duplicate ``client_order_id`` produces no second fill (A1)."""
    from signalforge.execution.states import OrderState

    out = DrillOutcome()
    world = seed_research_state(session, now)
    world.limits_row = seed_limits(session, now)
    world.armed = seed_armed(session, world)
    adapter = make_adapter(session, world)

    before = max_event_id(session)
    intent = equity_intent(world)
    first = adapter.place(intent)
    cash_after_first = world.broker.account().cash
    fills_after_first = world.broker.fills_for(intent.client_order_id)

    second = adapter.place(intent)
    out.check("the first place() filled", first.state is OrderState.FILLED)
    out.check("the second returns the SAME recorded result", second == first)
    out.check(
        "exactly one set of fills exists",
        world.broker.fills_for(intent.client_order_id) == fills_after_first,
        f"{len(fills_after_first)} fill(s)",
    )
    out.check("cash did not move twice", world.broker.account().cash == cash_after_first)
    reasons = observed_events(session, after_id=before)
    out.check(
        "the duplicate is recorded as a duplicate, not as a new order",
        any("duplicate client_order_id" in r for r in reasons),
    )

    # The other half of A1: the same economics under a FRESH id is refused.
    fresh = adapter.place(equity_intent(world, client_order_id="a-fresh-id"))
    out.check(
        "a fresh id for identical economics is REJECTED",
        fresh.state is OrderState.REJECTED and "economically identical" in fresh.error_verbatim,
        fresh.error_verbatim[:160],
    )
    out.events = observed_events(session, after_id=before)
    return out


def drill_v6(session: Any, now: datetime) -> DrillOutcome:
    """V6 — after a simulated timeout, ``order_status()`` is queried BEFORE any
    resubmission, and a broker that already knows the id produces no second
    fill."""
    from signalforge.execution.brokers.paper_reference import SimulatedBrokerTimeout
    from signalforge.execution.states import OrderState

    out = DrillOutcome()
    world = seed_research_state(session, now)
    world.limits_row = seed_limits(session, now)
    world.armed = seed_armed(session, world)
    adapter = make_adapter(session, world)

    before = max_event_id(session)
    intent = equity_intent(world)
    world.broker.arm_timeout_once()
    timed_out = False
    try:
        submit_through_oms(session, adapter, intent)
    except SimulatedBrokerTimeout:
        timed_out = True
    out.check("the submission timed out", timed_out)

    # THE RULE: ask the broker by id before even considering a resubmission.
    status = adapter.order_status(intent.client_order_id)
    out.check(
        "order_status() resolves the id — the broker DID see it (A4)",
        status is not None and status.state is OrderState.FILLED,
        status.raw_status_verbatim[:120] if status is not None else "no status",
    )
    fills = world.broker.fills_for(intent.client_order_id)
    out.check("exactly one fill exists at the broker", len(fills) == 1, f"{len(fills)} fills")

    # A resubmission is not made; and were one made, it could not double-fill.
    replay = adapter.place(intent)
    out.check(
        "a resubmission of the same id cannot double-fill",
        replay.state is OrderState.FILLED
        and world.broker.fills_for(intent.client_order_id) == fills,
    )
    out.check(
        "the client_order_id carries no attempt counter, so a retry IS the same id",
        intent.client_order_id == equity_intent(world).client_order_id,
    )
    events = observed_events(session, after_id=before)
    out.check(
        "the timeout is recorded verbatim, naming the §8 procedure",
        any("simulated timeout" in e for e in events),
    )
    out.events = events
    return out


def drill_v7(session: Any, now: datetime) -> DrillOutcome:
    """V7 — ``SUBMITTING`` with no outcome → ``UNKNOWN`` → arming refused, and a
    retry never clears it."""
    from signalforge.execution.arming import ArmingRequest, check_arming_preconditions
    from signalforge.execution.oms import (
        current_state,
        has_outstanding_unknown,
        promote_stale_submitting,
        record_submitting,
        transition,
    )
    from signalforge.execution.states import IllegalTransition, OrderState, next_state

    out = DrillOutcome()
    world = seed_research_state(session, now)
    world.limits_row = seed_limits(session, now)
    seed_approval(session, world)
    seed_evidence(session, world)

    before = max_event_id(session)
    intent = equity_intent(world)
    # Committed durably, and then the process "dies" before any network call.
    record_submitting(session, transition(session, intent, OrderState.VALIDATED, actor="drill"))
    out.check(
        "the SUBMITTING record is durable",
        current_state(session, intent.client_order_id) is OrderState.SUBMITTING,
    )

    promoted = promote_stale_submitting(session, now=now, adapter_name="paper_reference")
    out.check("the next cycle promotes it to UNKNOWN", promoted == [intent.client_order_id])
    out.check(
        "it is UNKNOWN, never 'assumed failed'",
        current_state(session, intent.client_order_id) is OrderState.UNKNOWN,
    )
    out.check(
        "the strategy has an outstanding UNKNOWN",
        has_outstanding_unknown(session, world.version.id),
    )

    decision = check_arming_preconditions(
        session,
        ArmingRequest(
            strategy_version_id=world.version.id,
            adapter_name="paper_reference",
            broker_account_id_expected=world.account_id,
            preregistration_doc_id=LIMIT_GRID_CENTRES["preregistration_doc_id"],
            max_notional_usd=1_000.0,
            max_orders_per_day=10,
            acknowledged=True,
        ),
        now=now,
        is_paper_proof=None,
        account_is_flat=True,
        limits_id=world.limits_row.id,
    )
    s12 = next(c for c in decision.checks if c.name == "S12")
    out.check("arming that strategy is REFUSED on S12", not s12.passed, s12.detail[:160])

    retried = False
    try:
        next_state(OrderState.UNKNOWN, OrderState.FILLED)
    except IllegalTransition:
        retried = True
    out.check("a retry does NOT clear the UNKNOWN", retried)
    out.events = observed_events(session, after_id=before)
    return out


def drill_v8(session: Any, now: datetime) -> DrillOutcome:
    """V8 — a proportional combo partial is PARTIAL; a by-leg partial halts."""
    from signalforge.execution.brokers.paper_reference import (
        ByLegPartialHalt,
        assert_no_naked_short_leg,
    )
    from signalforge.execution.states import OrderState

    out = DrillOutcome()
    world = seed_research_state(session, now)
    world.limits_row = seed_limits(session, now)
    world.armed = seed_armed(session, world)
    # Only one contract of the long leg is available; the short leg has plenty.
    adapter = make_adapter(session, world, information=drill_quotes(now, short=10, long=1))

    before = max_event_id(session)
    intent = short_vertical_intent(world, contracts=2)
    result = adapter.place_combo(intent)
    out.check("the combo is PARTIAL, not FILLED", result.state is OrderState.PARTIAL)
    order = world.broker.book()[intent.client_order_id]
    out.check(
        "every leg filled the SAME proportion — one scalar, no loop over legs",
        len(set(order.filled_ratios)) == 1,
        str(order.filled_ratios),
    )
    out.check("the partial size is the binding leg's", order.filled_units == 1)

    legs = intent.legs
    halted = False
    try:
        assert_no_naked_short_leg(legs, (1.0, 0.0), client_order_id=intent.client_order_id)
    except ByLegPartialHalt:
        halted = True
    out.check("a BY-LEG partial halts rather than leaving a naked short", halted)
    out.check(
        "the proportional partial does NOT halt",
        assert_no_naked_short_leg(legs, order.filled_ratios, client_order_id="x") is None,
    )
    out.events = observed_events(session, after_id=before)
    return out


def drill_v9(session: Any, now: datetime) -> DrillOutcome:
    """V9 — an ``is_paper`` account-id mismatch fails arming AND every
    subsequent submission."""
    from signalforge.execution.arming import ArmingRefused, ArmingRequest, arm
    from signalforge.execution.states import OrderState

    out = DrillOutcome()
    world = seed_research_state(session, now)
    world.limits_row = seed_limits(session, now)
    seed_approval(session, world)
    seed_evidence(session, world)
    adapter = make_adapter(session, world, expected_account_id="PAPER-SIM-SOMEONE-ELSE")

    before = max_event_id(session)
    proof = adapter.is_paper()
    out.check("the proof FAILS", not proof.proven, proof.failure_reason[:160])
    out.check(
        "it fails on the account id, read from the broker's own response body",
        "does not match" in proof.failure_reason,
        proof.failure_reason[:160],
    )

    request = ArmingRequest(
        strategy_version_id=world.version.id,
        adapter_name="paper_reference",
        broker_account_id_expected="PAPER-SIM-SOMEONE-ELSE",
        preregistration_doc_id=LIMIT_GRID_CENTRES["preregistration_doc_id"],
        max_notional_usd=1_000.0,
        max_orders_per_day=10,
        acknowledged=True,
    )
    refused = ""
    try:
        arm(
            session,
            request,
            now=now,
            is_paper_proof=proof,
            account_is_flat=True,
            actor="drill",
            limits_id=world.limits_row.id,
        )
    except ArmingRefused as exc:
        refused = str(exc)
    out.check("arming is REFUSED", bool(refused), refused[:200])
    out.check("the refusal names S8, the is_paper proof", "S8" in refused, refused[:200])

    result = adapter.place(equity_intent(world))
    out.check(
        "every submission is refused too",
        result.state is OrderState.REJECTED and "is_paper" in result.error_verbatim,
        result.error_verbatim[:160],
    )
    out.check("no fill exists", not world.broker.fills_for(result.client_order_id))
    out.events = observed_events(session, after_id=before)
    return out


def drill_v10(session: Any, now: datetime) -> DrillOutcome:
    """V10 — the broker clock and the local calendar disagreeing blocks."""
    from signalforge.execution import calendarcheck
    from signalforge.execution.intents import MarketClock
    from signalforge.execution.limits import may_open

    out = DrillOutcome()
    world = seed_research_state(session, now)
    world.limits_row = seed_limits(session, now)
    limits = limit_set(world)

    # 03:00 UTC is the middle of the night in New York: the calendar says
    # closed. The broker insists it is open.
    overnight = now.replace(hour=3, minute=0)
    verdict = calendarcheck.evaluate(overnight, MarketClock(is_open=True, as_of=overnight))
    out.check("the calendar says closed", verdict.market_open_calendar is False)
    out.check("the broker says open", verdict.market_open_broker is True)
    out.check("the cross-check refuses to agree", not verdict.agreement_ok, verdict.detail[:160])
    out.check("blocks_opening is True", verdict.blocks_opening)

    decision = may_open(
        open_context(world, now=overnight, market_open_calendar=False, market_open_broker=True),
        limits,
    )
    out.check(
        "may_open blocks on C1, naming which side said what",
        not decision.allowed and "C1" in (decision.first_failure or ""),
        decision.first_failure or "",
    )

    agreed = calendarcheck.evaluate(now, MarketClock(is_open=True, as_of=now))
    out.check("an agreeing clock does NOT block", not agreed.blocks_opening, agreed.detail[:160])
    return out


def drill_v11(session: Any, now: datetime) -> DrillOutcome:
    """V11 — an intent past ``expires_at`` is refused, not warned."""
    from signalforge.execution.intents import (
        CostModelFeedback,
        IntentRefused,
        OrderSide,
        build_open_intent,
        compute_expires_at,
    )
    from signalforge.execution.limits import may_open

    out = DrillOutcome()
    world = seed_research_state(session, now)
    world.limits_row = seed_limits(session, now)
    world.armed = seed_armed(session, world)
    limits = limit_set(world)

    decision = may_open(open_context(world, intent_expires_at=now - timedelta(minutes=1)), limits)
    out.check(
        "may_open REFUSES on I1 — a refusal, not a warning",
        not decision.allowed and "I1" in (decision.first_failure or ""),
        decision.first_failure or "",
    )
    out.check(
        "the session end caps the intent's life below the age cap",
        compute_expires_at(
            created_at=now, max_intent_age_minutes=60, session_end_utc=now + timedelta(minutes=5)
        )
        == now + timedelta(minutes=5),
    )

    refusal = ""
    try:
        build_open_intent(
            session,
            paper_trade_id=world.paper_trade.id,
            adapter_name="paper_reference",
            side=OrderSide.BUY_TO_OPEN,
            qty=1,
            limit_price=471.0,
            cost_model=CostModelFeedback(modelled_fill_price=470.0, modelled_spread_bps=5.0),
            limit_decision=may_open(open_context(world), limits),
            now=now,
            max_intent_age_minutes=15,
            session_end_utc=now - timedelta(minutes=1),
            execution_limits_id=world.limits_row.id,
            scope_matcher=lambda *_: True,
        )
    except IntentRefused as exc:
        refusal = str(exc)
    out.check(
        "the factory refuses to build an intent that would be born expired",
        "I1" in refusal,
        refusal[:160],
    )
    return out


def _find_early_close(year: int) -> date | None:
    from signalforge.data.options_calendar import is_early_close

    day = date(year, 1, 1)
    while day.year == year:
        # A day the calendar cannot resolve is simply not the day being looked
        # for; the drill needs one it CAN resolve, which is the whole point.
        with suppress(Exception):
            if is_early_close(day):
                return day
        day += timedelta(days=1)
    return None


def drill_v12(session: Any, now: datetime) -> DrillOutcome:
    """V12 — an early-close session blocks unless the calendar resolved it AND
    the adapter clock agrees."""
    from signalforge.execution import calendarcheck
    from signalforge.execution.intents import MarketClock
    from signalforge.execution.limits import may_open

    out = DrillOutcome()
    world = seed_research_state(session, now)
    world.limits_row = seed_limits(session, now)
    limits = limit_set(world)

    early = _find_early_close(now.year) or _find_early_close(now.year - 1)
    if early is None:
        out.check("an early-close session exists in the calendar", False, "none found")
        return out
    # 15:00 UTC is 11:00 ET — inside a 09:30–13:00 half day and outside both
    # 15-minute no-submit windows, so C3 is the only thing that can block.
    at = datetime(early.year, early.month, early.day, 15, 0, tzinfo=UTC)

    blocked = calendarcheck.evaluate(at, MarketClock(is_open=True, as_of=at))
    out.check("the calendar reports an early close", blocked.is_early_close_session is True)
    out.check(
        "it is NOT 'explicitly handled' by default",
        blocked.early_close_explicitly_handled is False,
    )
    decision = may_open(
        open_context(
            world,
            now=at,
            is_early_close_session=True,
            early_close_explicitly_handled=False,
            minutes_since_open=blocked.minutes_since_open,
            minutes_until_close=blocked.minutes_until_close,
        ),
        limits,
    )
    out.check(
        "may_open blocks on C3",
        not decision.allowed and "C3" in (decision.first_failure or ""),
        decision.first_failure or "",
    )

    handled = calendarcheck.evaluate(
        at, MarketClock(is_open=True, as_of=at), allow_early_close=True
    )
    out.check(
        "the operator flag earns 'handled' ONLY with the clock agreeing",
        handled.early_close_explicitly_handled is True and handled.agreement_ok,
        handled.detail[:160],
    )
    unreachable = calendarcheck.evaluate(at, None, allow_early_close=True)
    out.check(
        "with no adapter clock the flag earns nothing",
        unreachable.early_close_explicitly_handled is False,
    )
    eastern = ZoneInfo("America/New_York")
    session_end_et = (
        blocked.session_end_utc.astimezone(eastern) if blocked.session_end_utc else None
    )
    out.check(
        "the no-submit window is measured against the OPTIONS close (13:00 ET), not 16:00",
        session_end_et is not None and (session_end_et.hour, session_end_et.minute) == (13, 0),
        str(session_end_et),
    )
    return out


def drill_v13(session: Any, now: datetime) -> DrillOutcome:
    """V13 — the order that would cross the rolling-5-session round-trip
    threshold is refused."""
    from signalforge.execution.limits import may_open

    out = DrillOutcome()
    world = seed_research_state(session, now)
    world.limits_row = seed_limits(session, now)
    world.armed = seed_armed(session, world)
    limits = limit_set(world)
    threshold = limits.round_trips_per_5_sessions_max

    below = may_open(open_context(world, round_trips_last_5_sessions=threshold - 1), limits)
    at_cap = may_open(open_context(world, round_trips_last_5_sessions=threshold), limits)
    out.check(f"{threshold - 1} round trips still opens", below.allowed, below.first_failure or "")
    out.check(
        f"the order that would make it {threshold + 1} is REFUSED on L3",
        not at_cap.allowed and "L3" in (at_cap.first_failure or ""),
        at_cap.first_failure or "",
    )
    out.check(
        "the threshold is one below the 4-day-trade PDT line",
        threshold == 3 and limits.pdt_equity_threshold_usd == 25_000.0,
        f"threshold={threshold} pdt={limits.pdt_equity_threshold_usd}",
    )
    out.check(
        "an unevaluated counter blocks too — missing evidence is not evidence",
        not may_open(open_context(world, round_trips_last_5_sessions=None), limits).allowed,
    )
    return out


def drill_v14(session: Any, now: datetime) -> DrillOutcome:
    """V14 — a manually accepted ``PaperTrade`` produces no intent, end to end."""
    from signalforge.execution.intents import (
        CostModelFeedback,
        IntentRefused,
        OrderSide,
        build_open_intent,
    )
    from signalforge.execution.limits import may_open

    out = DrillOutcome()
    world = seed_research_state(session, now, manual_actor=True)
    world.limits_row = seed_limits(session, now)
    world.armed = seed_armed(session, world)
    limits = limit_set(world)

    def build(trade_id: int) -> str:
        try:
            build_open_intent(
                session,
                paper_trade_id=trade_id,
                adapter_name="paper_reference",
                side=OrderSide.BUY_TO_OPEN,
                qty=1,
                limit_price=471.0,
                cost_model=CostModelFeedback(modelled_fill_price=470.0, modelled_spread_bps=5.0),
                limit_decision=may_open(open_context(world), limits),
                now=now,
                max_intent_age_minutes=15,
                session_end_utc=now + timedelta(hours=5),
                execution_limits_id=world.limits_row.id,
                scope_matcher=lambda *_: True,
            )
        except IntentRefused as exc:
            return str(exc)
        return ""

    refusal = build(world.paper_trade.id)
    out.check("a manually accepted trade produces NO intent", bool(refusal), refusal[:200])
    out.check("the refusal names P6", refusal.startswith("P6"), refusal[:200])
    out.check(
        "the refusal reads the indexed actor column, not signal_snapshot_json",
        "local-user" in refusal,
        refusal[:200],
    )

    # The same world with the automatic actor DOES build — so the refusal is
    # P6 and not some other precondition failing by accident.
    auto = seed_research_state(session, now, suffix="_auto")
    auto.limits_row = world.limits_row
    auto.armed = seed_armed(session, auto)
    auto_refusal = build(auto.paper_trade.id)
    out.check(
        "the automatic actor's trade is not refused on P6",
        not auto_refusal.startswith("P6"),
        auto_refusal[:200],
    )
    return out


def drill_v15(session: Any, now: datetime) -> DrillOutcome:
    """V15 — crash mid-submit → UNKNOWN → cleared and closed, with NO manual
    database write at any step."""
    from signalforge.execution.arming import CycleFacts, DisarmTrigger, auto_disarm_sweep
    from signalforge.execution.brokers.paper_reference import SimulatedBrokerTimeout
    from signalforge.execution.intents import (
        CostModelFeedback,
        OrderLeg,
        OrderSide,
        build_close_intent,
    )
    from signalforge.execution.oms import current_state, promote_stale_submitting, resolve_unknown
    from signalforge.execution.reconcile import expected_account_id_for
    from signalforge.execution.states import OrderState, UnknownResolution

    out = DrillOutcome()
    world = seed_research_state(session, now)
    world.limits_row = seed_limits(session, now)
    world.armed = seed_armed(session, world)
    adapter = make_adapter(session, world)

    before = max_event_id(session)
    intent = equity_intent(world)
    world.broker.arm_timeout_once()
    with suppress(SimulatedBrokerTimeout):
        submit_through_oms(session, adapter, intent)
    # ...the process dies here. On restart:
    promote_stale_submitting(session, now=now, adapter_name="paper_reference", actor="drill")
    out.check(
        "the restart promotes the row to UNKNOWN",
        current_state(session, intent.client_order_id) is OrderState.UNKNOWN,
    )

    disarms = auto_disarm_sweep(
        session, now=now, facts=CycleFacts(), adapter_name="paper_reference", actor="drill"
    )
    out.check(
        "auto-disarm fires on the outstanding UNKNOWN",
        any(d.trigger is DisarmTrigger.UNKNOWN_OUTSTANDING for d in disarms),
        str([d.trigger.value for d in disarms]),
    )
    out.check(
        "the is_paper proof still reads the DISARMED row's account id (§13 rule 4b)",
        expected_account_id_for(session, "paper_reference") == world.account_id,
    )

    status = adapter.order_status(intent.client_order_id)
    out.check("order_status() resolves the id to a terminal state", status is not None)
    resolved = resolve_unknown(
        session,
        intent.client_order_id,
        resolution=UnknownResolution(
            reconciled_from_order_status=True,
            operator_acknowledged=True,
            broker_terminal_state=status.state,
            acknowledged_by="drill-operator",
            note="V15",
        ),
        actor="drill-operator",
    )
    out.check("the UNKNOWN clears to the broker's own terminal state", resolved is status.state)
    out.check(
        "and it took reconciliation AND an acknowledgement — no manual DB write",
        current_state(session, intent.client_order_id) is status.state,
    )

    close = build_close_intent(
        session,
        position=reconciled_position(world, origin=intent.client_order_id),
        legs=[OrderLeg(side=OrderSide.SELL_TO_CLOSE, ratio=1, shares_per_contract=1, symbol="SPY")],
        contracts=1,
        limit_price=465.0,
        cost_model=CostModelFeedback(modelled_fill_price=470.0, modelled_spread_bps=5.0),
        now=now,
        max_intent_age_minutes=15,
        execution_limits_id=world.limits_row.id,
    )
    result = submit_through_oms(session, adapter, close)
    out.check(
        "the position closes with no armed row in force",
        result.state is OrderState.FILLED,
        f"{result.state.value}: {result.error_verbatim[:120]}",
    )
    out.events = observed_events(session, after_id=before)
    return out


def drill_v16(session: Any, now: datetime) -> DrillOutcome:
    """V16 — a close cannot be used to open."""
    from signalforge.execution.intents import (
        CloseIntentRefused,
        CostModelFeedback,
        OrderLeg,
        OrderSide,
        build_close_intent,
    )

    out = DrillOutcome()
    world = seed_research_state(session, now)
    world.limits_row = seed_limits(session, now)
    world.armed = seed_armed(session, world)
    adapter = make_adapter(session, world)
    before = max_event_id(session)
    intent = equity_intent(world)
    submit_through_oms(session, adapter, intent)

    def attempt(legs: list[Any], origin: str) -> str:
        try:
            build_close_intent(
                session,
                position=reconciled_position(world, origin=origin),
                legs=legs,
                contracts=1,
                limit_price=465.0,
                cost_model=CostModelFeedback(modelled_fill_price=470.0, modelled_spread_bps=5.0),
                now=now,
                max_intent_age_minutes=15,
                execution_limits_id=world.limits_row.id,
            )
        except CloseIntentRefused as exc:
            return str(exc)
        return ""

    opening_leg = [
        OrderLeg(side=OrderSide.BUY_TO_OPEN, ratio=1, shares_per_contract=1, symbol="SPY")
    ]
    refusal = attempt(opening_leg, intent.client_order_id)
    out.check("a leg on the OPENING side is refused (C-P3)", "C-P3" in refusal, refusal[:200])

    closing_leg = [
        OrderLeg(side=OrderSide.SELL_TO_CLOSE, ratio=1, shares_per_contract=1, symbol="SPY")
    ]
    foreign = attempt(closing_leg, "never-written-by-this-oms")
    out.check(
        "a close against a position with no originating event is a §10 divergence (C-P2)",
        "C-P2" in foreign,
        foreign[:200],
    )
    out.check(
        "the legitimate close still builds",
        attempt(closing_leg, intent.client_order_id) == "",
    )
    out.events = observed_events(session, after_id=before)
    return out


def drill_v17(session: Any, now: datetime) -> DrillOutcome:
    """V17 — shared-account refusal at arm time."""
    from signalforge.execution.arming import (
        ArmingRequest,
        check_arming_preconditions,
        read_adapter_account_is_flat,
    )

    out = DrillOutcome()
    world = seed_research_state(session, now)
    world.limits_row = seed_limits(session, now)
    seed_approval(session, world)
    seed_evidence(session, world)
    adapter = make_adapter(session, world)

    out.check("a fresh account reads as flat", read_adapter_account_is_flat(adapter) is True)
    world.broker.place(equity_intent(world))
    out.check(
        "an account holding anything at all reads as NOT flat",
        read_adapter_account_is_flat(adapter) is False,
    )

    def checks(**over: Any) -> dict[str, Any]:
        request = ArmingRequest(
            strategy_version_id=world.version.id,
            adapter_name="paper_reference",
            broker_account_id_expected=world.account_id,
            preregistration_doc_id=LIMIT_GRID_CENTRES["preregistration_doc_id"],
            max_notional_usd=1_000.0,
            max_orders_per_day=10,
            acknowledged=True,
        )
        decision = check_arming_preconditions(
            session,
            request,
            now=now,
            is_paper_proof=adapter.is_paper(),
            account_is_flat=over.get("flat"),
            limits_id=world.limits_row.id,
        )
        return {c.name: c for c in decision.checks}

    not_flat = checks(flat=False)
    out.check(
        "arming is machine-REFUSED on S9", not not_flat["S9"].passed, not_flat["S9"].detail[:160]
    )
    unreadable = checks(flat=None)
    out.check(
        "'could not check' is not 'is flat' — None blocks too",
        not unreadable["S9"].passed,
        unreadable["S9"].detail[:160],
    )

    world.armed = seed_armed(session, world)
    clash = checks(flat=True)
    out.check(
        "a second arming against the same account id is refused (S11)",
        not clash["S11"].passed,
        clash["S11"].detail[:160],
    )
    out.check(
        "and the same version cannot be armed twice (S10)",
        not clash["S10"].passed,
        clash["S10"].detail[:160],
    )

    from sqlalchemy import text

    idx = session.execute(
        text("SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='armed_strategy'")
    ).all()
    partial = [
        n for n, sql in idx if sql and "disarmed_at IS NULL" in sql and "UNIQUE" in sql.upper()
    ]
    out.check(
        "a partial UNIQUE index backs the rule at the database level",
        bool(partial),
        str([n for n, _ in idx]),
    )
    return out


def drill_v18(session: Any, now: datetime) -> DrillOutcome:
    """V18 — a disarmed strategy holding an open SHORT option leg still closes.

    No armed row, no Candidate, no PaperTrade on the close path, kill switch
    engaged and dead man lapsed. This is the drill that proves the headline
    promise rather than asserting it.
    """
    from signalforge.db.models import WorkerHeartbeat
    from signalforge.execution.arming import DisarmTrigger, disarm
    from signalforge.execution.deadman import DEAD_MAN_WORKER, assess
    from signalforge.execution.intents import (
        CostModelFeedback,
        OrderLeg,
        OrderSide,
        StructureType,
        build_close_intent,
    )
    from signalforge.execution.oms import (
        CycleBranch,
        read_cycle_posture,
        write_execution_kill_state,
    )
    from signalforge.execution.states import OrderState

    out = DrillOutcome()
    world = seed_research_state(session, now)
    world.limits_row = seed_limits(session, now)
    world.armed = seed_armed(session, world)
    adapter = make_adapter(session, world, information=drill_quotes(now, short=10, long=10))

    before = max_event_id(session)
    opened = submit_through_oms(session, adapter, short_vertical_intent(world, contracts=1))
    out.check("the short vertical filled", opened.state is OrderState.FILLED)
    legs = {leg.instrument_key: leg for leg in world.broker.positions()[0].legs}
    out.check(
        "the book holds a SHORT option leg",
        legs[SHORT_PUT].signed_qty < 0,
        f"{SHORT_PUT}={legs[SHORT_PUT].signed_qty:+g}",
    )

    disarm(
        session,
        world.armed,
        trigger=DisarmTrigger.OPERATOR,
        detail="V18",
        now=now,
        actor="drill",
    )
    write_execution_kill_state(engaged=True, reason="V18 drill", actor="drill", now=now)
    session.add(
        WorkerHeartbeat(
            worker=DEAD_MAN_WORKER,
            started_at=now - timedelta(hours=1),
            last_beat_at=now - timedelta(minutes=10),
        )
    )
    session.flush()
    out.check(
        "the posture is PROTECTIVE and the dead man has lapsed",
        read_cycle_posture().branch is CycleBranch.PROTECTIVE
        and assess(session, now=now, stale_after_s=90).lapsed,
    )

    close = build_close_intent(
        session,
        position=reconciled_position(world, origin=opened.client_order_id),
        legs=[
            OrderLeg(
                side=OrderSide.BUY_TO_CLOSE,
                ratio=1,
                shares_per_contract=100,
                option_ticker=SHORT_PUT,
                strike=460.0,
            ),
            OrderLeg(
                side=OrderSide.SELL_TO_CLOSE,
                ratio=1,
                shares_per_contract=100,
                option_ticker=LONG_PUT,
                strike=455.0,
            ),
        ],
        contracts=1,
        limit_price=-1.80,
        cost_model=CostModelFeedback(modelled_fill_price=1.60, modelled_spread_bps=5.0),
        now=now,
        max_intent_age_minutes=15,
        structure_type=StructureType.SHORT_VERTICAL,
        execution_limits_id=world.limits_row.id,
    )
    out.check("the protective close CONSTRUCTS with no armed row", close is not None)
    result = submit_through_oms(session, adapter, close)
    out.check(
        "and it SUBMITS",
        result.state is OrderState.FILLED,
        f"{result.state.value}: {result.error_verbatim[:160]}",
    )
    flat = world.broker.positions()
    out.check("the short leg is flat afterwards", not flat, f"{len(flat)} position(s) left")
    out.events = observed_events(session, after_id=before)
    return out


def drill_v19(session: Any, now: datetime) -> DrillOutcome:
    """V19 — the app process never carries the execution job."""
    from signalforge.execution.cycle import EXECUTION_CYCLE_JOB, execution_job_specs
    from signalforge.scheduler import default_job_specs
    from signalforge.settings_store import effective_research_config

    out = DrillOutcome()
    cfg = effective_research_config(session)
    out.check("execution.enabled ships False", cfg.execution.enabled is False)
    out.check("execution_job_specs() is empty while disabled", execution_job_specs() == [])

    names = [s.name for s in default_job_specs()]
    out.check(
        f"{EXECUTION_CYCLE_JOB} is not in the default job list", EXECUTION_CYCLE_JOB not in names
    )
    out.check(
        "no default spec is self_guarded — the execution cycle is the only one that may be",
        not any(s.self_guarded for s in default_job_specs()),
    )

    pkg = REPO_ROOT / "src" / "signalforge"
    offenders = [
        str(p.relative_to(REPO_ROOT))
        for p in [*(pkg / "app").rglob("*.py"), pkg / "scheduler.py"]
        if "signalforge.execution" in p.read_text(encoding="utf-8")
    ]
    out.check(
        "no module under app/** and not scheduler.py names signalforge.execution",
        not offenders,
        str(offenders),
    )
    out.notes.append(
        "The ADR's 'the app's embedded-scheduler path refuses to start' clause is met more "
        "strongly than written: app/main.py calls build_scheduler() with no specs, so the "
        "execution job cannot be present to refuse. There is nothing to refuse, and the import "
        "boundary is what guarantees it."
    )
    return out


def drill_v20(session: Any, now: datetime) -> DrillOutcome:
    """V20 (added by W3D, not in ADR §21) — the arming expiry, both halves."""
    from signalforge.execution.arming import (
        ARMING_EXPIRY_DAYS,
        ArmingRequest,
        CycleFacts,
        DisarmTrigger,
        auto_disarm_sweep,
        check_arming_preconditions,
    )
    from signalforge.execution.limits import ArmedFacts, may_open

    out = DrillOutcome()
    world = seed_research_state(session, now)
    world.limits_row = seed_limits(session, now)
    seed_approval(session, world)
    seed_evidence(session, world)
    out.check("the expiry maximum is decision 4's 7 days", ARMING_EXPIRY_DAYS == 7)

    def s7(expires_at: datetime | None) -> Any:
        request = ArmingRequest(
            strategy_version_id=world.version.id,
            adapter_name="paper_reference",
            broker_account_id_expected=world.account_id,
            preregistration_doc_id=LIMIT_GRID_CENTRES["preregistration_doc_id"],
            max_notional_usd=1_000.0,
            max_orders_per_day=10,
            expires_at=expires_at,
            acknowledged=True,
        )
        decision = check_arming_preconditions(
            session,
            request,
            now=now,
            is_paper_proof=None,
            account_is_flat=True,
            limits_id=world.limits_row.id,
        )
        return next(c for c in decision.checks if c.name == "S7")

    out.check("the default 7-day expiry passes", s7(None).passed, s7(None).detail[:120])
    long = s7(now + timedelta(days=30))
    out.check(
        "30 days is REFUSED, not silently clamped",
        not long.passed and "no indefinite arming" in long.detail,
        long.detail[:160],
    )
    past = s7(now - timedelta(seconds=1))
    out.check("an expiry in the past is refused", not past.passed, past.detail[:120])

    expired = may_open(
        open_context(
            world,
            armed=ArmedFacts(
                adapter_name="paper_reference",
                expires_at=now - timedelta(minutes=1),
                disarmed=False,
                structure_type="equity",
                approval_level_permits_structure=True,
            ),
        ),
        limit_set(world),
    )
    out.check(
        "may_open blocks on A1 once the arming has expired",
        not expired.allowed and "A1" in (expired.first_failure or ""),
        expired.first_failure or "",
    )

    world.armed = seed_armed(session, world, expires_in_days=-0.001)
    before = max_event_id(session)
    disarms = auto_disarm_sweep(
        session, now=now, facts=CycleFacts(), adapter_name="paper_reference", actor="drill"
    )
    out.check(
        "the sweep makes the expiry a matter of record",
        any(d.trigger is DisarmTrigger.EXPIRED for d in disarms),
        str([d.trigger.value for d in disarms]),
    )
    out.events = observed_events(session, after_id=before)
    return out


def drill_v21(session: Any, now: datetime) -> DrillOutcome:
    """V21 (added by W3D, not in ADR §21) — auto-disarm on ANY status change."""
    from signalforge.db.models import AuditLog
    from signalforge.domain import StrategyStatus
    from signalforge.execution.arming import CycleFacts, DisarmTrigger, auto_disarm_sweep

    out = DrillOutcome()
    world = seed_research_state(session, now)
    world.limits_row = seed_limits(session, now)
    seed_approval(session, world)
    world.armed = seed_armed(session, world)

    before = max_event_id(session)
    quiet = auto_disarm_sweep(
        session, now=now, facts=CycleFacts(), adapter_name="paper_reference", actor="drill"
    )
    out.check("nothing disarms while everything is unchanged", not quiet, str(quiet))

    world.version.status = StrategyStatus.EXPERIMENTAL
    session.flush()
    changed = auto_disarm_sweep(
        session, now=now, facts=CycleFacts(), adapter_name="paper_reference", actor="drill"
    )
    out.check(
        "a status change disarms",
        any(d.trigger is DisarmTrigger.STATUS_CHANGE for d in changed),
        str([d.trigger.value for d in changed]),
    )
    out.check(
        "and decision 9 is 'ANY change', so the reason says so",
        any("not only a downgrade" in d.detail for d in changed),
        str([d.detail[:80] for d in changed]),
    )

    # The flap: changed and changed back between two cycles is invisible to a
    # point-in-time comparison, and is caught from the audit log instead.
    world.version.status = StrategyStatus.PAPER_APPROVED
    session.flush()
    world.armed = seed_armed(session, world, account_id=f"{world.account_id}-B")
    session.add(
        AuditLog(
            ts=now,
            action="strategy.downgrade",
            actor="health-monitor",
            entity=f"{world.strategy.name}@{world.version.version}",
            before_json={"status": "PAPER_APPROVED"},
            after_json={"status": "EXPERIMENTAL"},
        )
    )
    session.flush()
    flap = auto_disarm_sweep(
        session, now=now, facts=CycleFacts(), adapter_name="paper_reference", actor="drill"
    )
    out.check(
        "a status FLAP is caught from the recorded transition",
        any(d.trigger is DisarmTrigger.STATUS_CHANGE for d in flap),
        str([d.detail[:90] for d in flap]),
    )
    out.events = observed_events(session, after_id=before)
    return out


def drill_v22(session: Any, now: datetime) -> DrillOutcome:
    """V22 (added by W3D, not in ADR §21) — the per-order, daily and notional
    caps, and which form binds."""
    from signalforge.execution.limits import binding_cap, may_open

    out = DrillOutcome()
    world = seed_research_state(session, now)
    world.limits_row = seed_limits(session, now)
    world.armed = seed_armed(session, world)
    limits = limit_set(world)

    at_cap = may_open(open_context(world, orders_today=limits.max_orders_per_day), limits)
    out.check(
        f"the {limits.max_orders_per_day + 1}th order of the day is refused on L1",
        not at_cap.allowed and "L1" in (at_cap.first_failure or ""),
        at_cap.first_failure or "",
    )
    out.check(
        "one below the cap still opens",
        may_open(open_context(world, orders_today=limits.max_orders_per_day - 1), limits).allowed,
    )

    cap = binding_cap(
        usd=limits.max_order_notional_usd,
        pct=limits.per_structure_max_loss_pct,
        equity=25_000.0,
    )
    out.check(
        "at $25,000 the PERCENT form binds at $125, not the $1,000 dollar form",
        cap == 125.0,
        f"binding cap = {cap}",
    )
    over = may_open(open_context(world, order_notional_usd=126.0), limits)
    out.check(
        "an order over the binding cap is refused on L2",
        not over.allowed and "L2" in (over.first_failure or ""),
        over.first_failure or "",
    )
    out.check(
        "an order at the binding cap is allowed",
        may_open(open_context(world, order_notional_usd=125.0), limits).allowed,
    )

    exposure = may_open(
        open_context(world, account_exposure_usd=9_990.0, order_notional_usd=100.0), limits
    )
    out.check(
        f"the {limits.max_account_exposure_pct}% account-exposure cap refuses on L2",
        not exposure.allowed and "L2" in (exposure.first_failure or ""),
        exposure.first_failure or "",
    )
    out.check(
        "an uncomputable cap is not a cap: None equity blocks",
        not may_open(open_context(world, account_equity_usd=None), limits).allowed,
    )
    out.check(
        "no limits row at all blocks on L0 — 'no limits row' is not 'no limits'",
        not may_open(open_context(world), None).allowed,
    )
    return out


DRILLS: tuple[Drill, ...] = (
    Drill(
        "V0",
        "OMS-side position-origin attribution (§10)",
        "the bare paper_reference adapter reconciles CLEAN while holding a position, because "
        "the OMS reconstructs position origin from its own SUBMITTING records; a position it "
        "cannot explain exactly is still FOREIGN_POSITION. Recorded as GAP CLOSED.",
        drill_v0,
        in_adr=False,
    ),
    Drill(
        "V1",
        "Kill switch engaged with an open position",
        "the cycle body executes and writes CYCLE_PROTECTIVE + a JobRun; may_open blocked; "
        "may_close still works and a protective close submits; drain → cancel_all → reconcile "
        "runs in order",
        drill_v1,
    ),
    Drill(
        "V2",
        "Dead-man lapse",
        "opening blocked, auto-disarm fires, NO auto-liquidation occurs, may_close remains open",
        drill_v2,
    ),
    Drill(
        "V3",
        "Reconciliation divergence",
        "a broker position with no matching client_order_id halts opening, disarms, and is NOT "
        "auto-corrected",
        drill_v3,
    ),
    Drill(
        "V4",
        "Reconciliation staleness",
        "with no fresh reconciliation inside max_reconciliation_age_s, may_open blocks exactly as "
        "a dead-man lapse does",
        drill_v4,
    ),
    Drill(
        "V5",
        "Duplicate client_order_id",
        "the second place() with the same id produces no second fill (A1)",
        drill_v5,
    ),
    Drill(
        "V6",
        "Post-timeout non-duplication",
        "after a simulated timeout, order_status() is queried BEFORE any resubmission; a broker "
        "that already knows the id produces no resubmission",
        drill_v6,
    ),
    Drill(
        "V7",
        "SUBMITTING with no outcome → UNKNOWN → blocked arming",
        "the next cycle promotes to UNKNOWN; arming that strategy is refused; a retry does not "
        "clear it",
        drill_v7,
    ),
    Drill(
        "V8",
        "Combo partial fill",
        "a proportional partial is PARTIAL and reconciles; a by-leg partial halts",
        drill_v8,
    ),
    Drill(
        "V9",
        "is_paper account-id mismatch",
        "a response whose account id differs from the armed record fails arming and fails every "
        "subsequent submission",
        drill_v9,
    ),
    Drill(
        "V10",
        "Clock/calendar disagreement",
        "adapter.clock() disagreeing with data/options_calendar.py blocks",
        drill_v10,
    ),
    Drill("V11", "Intent expiry", "an intent past expires_at is refused, not warned", drill_v11),
    Drill(
        "V12",
        "Early-close session",
        "submission refused unless the calendar's early-close handling is explicit and the "
        "adapter clock agrees",
        drill_v12,
    ),
    Drill(
        "V13",
        "Round-trip threshold",
        "the order that would cross the rolling-5-session threshold is refused",
        drill_v13,
    ),
    Drill(
        "V14",
        "Manual-accept refusal, end to end",
        "a PaperTrade accepted by hand produces NO intent (T2, §5)",
        drill_v14,
    ),
    Drill(
        "V15",
        "Crash mid-submit → UNKNOWN → cleared, end to end",
        "promotion, auto-disarm, the is_paper proof reading the disarmed row, the two-part "
        "resolution, and a close needing no armed row — with no manual DB write",
        drill_v15,
    ),
    Drill(
        "V16",
        "Close cannot be used to open",
        "a net-reducing close that increases any single leg is refused (C-P3); a close against a "
        "position with no originating execution_event is refused (C-P2)",
        drill_v16,
    ),
    Drill(
        "V17",
        "Shared-account refusal at arm time",
        "arming is machine-refused when the account is not flat, and a second arming against the "
        "same account id is refused",
        drill_v17,
    ),
    Drill(
        "V18",
        "Disarmed strategy with an open short leg",
        "a protective close still constructs and still submits with no armed row, the kill switch "
        "engaged and the dead man lapsed",
        drill_v18,
    ),
    Drill(
        "V19",
        "The app process never carries the execution job",
        "the job list is unchanged while disabled and no module under app/** or scheduler.py "
        "names signalforge.execution",
        drill_v19,
    ),
    Drill(
        "V20",
        "Arming expiry",
        "7 days is the maximum, >7 is refused rather than clamped, an expired arming blocks "
        "may_open and is disarmed by the sweep",
        drill_v20,
        in_adr=False,
    ),
    Drill(
        "V21",
        "Auto-disarm on any status change",
        "decision 9 — any status change disarms, including a flap caught from the audit log",
        drill_v21,
        in_adr=False,
    ),
    Drill(
        "V22",
        "Per-order, daily and notional caps",
        "L1 daily count, L2 per-order notional with the tighter of the dollar and percent forms, "
        "and the account-exposure cap",
        drill_v22,
        in_adr=False,
    ),
)

DRILLS_BY_NAME: dict[str, Drill] = {d.name: d for d in DRILLS}


def run_drill(drill: Drill, session: Any, now: datetime = DRILL_NOW) -> DrillResult:
    try:
        return DrillResult(drill=drill, outcome=drill.run(session, now))
    except Exception as exc:
        import traceback

        return DrillResult(
            drill=drill,
            outcome=DrillOutcome(),
            error=f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=6)}",
        )


# ---------------------------------------------------------------------------
# Scratch database plumbing — used ONLY by main(); pytest supplies its own.
# ---------------------------------------------------------------------------


@contextmanager
def scratch_session(root: Path, tag: str) -> Iterator[Any]:
    """One freshly migrated scratch database, and a session on it.

    A new file per drill: several drills write armings, kill states and
    heartbeats, and a drill that passed only because a previous one left the
    world in a convenient shape is not a drill.
    """
    data_dir = root / tag
    data_dir.mkdir(parents=True, exist_ok=True)
    url = f"sqlite+pysqlite:///{data_dir / 'drill.sqlite'}"
    refuse_if_live(url)

    os.environ["SIGNALFORGE_DATA_DIR"] = str(data_dir)
    os.environ["DATABASE_URL"] = url
    # Hermetic and offline, in the shape tests/conftest.py uses.
    for var in (
        "MARKET_DATA_API_KEY",
        "MARKET_DATA_PROVIDER_SECONDARY",
        "OPTIONS_API_KEY",
        "NEWS_API_KEY",
        "NOTIFICATION_PROVIDER",
        "DISCORD_WEBHOOK_URL",
        "LLM_PROVIDER",
    ):
        os.environ[var] = ""
    os.environ["MARKET_DATA_PROVIDER"] = "fixture"

    from alembic import command
    from alembic.config import Config

    import signalforge.killswitch as killswitch
    from signalforge.config.settings import get_settings
    from signalforge.db.session import get_sessionmaker, reset_engine_cache

    killswitch._default = None
    get_settings.cache_clear()
    reset_engine_cache()

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "src/signalforge/db/migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")

    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()
        reset_engine_cache()
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def render_report(results: list[DrillResult], *, started: datetime) -> str:
    passed = sum(1 for r in results if r.passed)
    lines: list[str] = [
        f"# Phase V execution drills — {started.date().isoformat()}",
        "",
        f"Run at {started.isoformat()} against `paper_reference` only, on a scratch SQLite "
        "database created for this run and deleted afterwards. **The live database was not "
        "opened.** No network call is possible from this path: the only adapter is local and "
        "deterministic.",
        "",
        f"Generated by `python scripts/execution_drills.py --all`. **{passed}/{len(results)} "
        "PASS.**",
        "",
        "| # | Drill | In ADR §21 | Result | First failure |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        first = r.error.splitlines()[0] if r.error else r.outcome.first_failure
        lines.append(
            f"| {r.drill.name} | {r.drill.title} | {'yes' if r.drill.in_adr else 'added'} | "
            f"**{'PASS' if r.passed else 'FAIL'}** | {first[:120] or '—'} |"
        )
    lines += ["", "---", ""]

    for r in results:
        lines += [
            f"## {r.drill.name} — {r.drill.title}  ·  {'PASS' if r.passed else 'FAIL'}",
            "",
            f"**Pass condition.** {r.drill.pass_condition}",
            "",
        ]
        if r.error:
            lines += ["```", r.error.strip(), "```", ""]
        for c in r.outcome.checks:
            lines.append(
                f"- [{'PASS' if c.passed else 'FAIL'}] {c.label}"
                + (f" — {c.detail}" if c.detail else "")
            )
        if r.outcome.notes:
            lines.append("")
            for note in r.outcome.notes:
                lines.append(f"> {note}")
        if r.outcome.events:
            lines += [
                "",
                "<details><summary>audit rows observed " f"({len(r.outcome.events)})</summary>",
                "",
                "```",
            ]
            lines += r.outcome.events
            lines += ["```", "", "</details>"]
        lines.append("")

    lines += [
        "---",
        "",
        "## What a PASS here does and does not mean",
        "",
        "These drills run against `brokers/paper_reference.py`: local, deterministic, "
        "network-free, and with fills the implementer controls. D6 §3.1 rule 4 fences those "
        "fills off from every gate, and nothing in this report is evidence about a strategy. "
        "A PASS means the **refusals fire** — that the kill switch blocks opening and not "
        "closing, that a divergence halts instead of repairing, that a timeout cannot "
        "double-fill. §21 requires the same list to be repeated against the vendor paper "
        "endpoint, with **zero** armed strategies, before any of it is evidence about a broker.",
        "",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--all", action="store_true", help="run every drill")
    ap.add_argument("--name", action="append", default=[], help="run one drill (repeatable)")
    ap.add_argument("--dry-run", action="store_true", help="list what would run; run nothing")
    ap.add_argument(
        "--out",
        default=str(REPO_ROOT / "docs/research/execution_drills"),
        help="directory for the dated drill report",
    )
    ap.add_argument("--no-report", action="store_true", help="print only; write no report file")
    args = ap.parse_args(argv)

    selected: list[Drill]
    if args.name:
        unknown = [n for n in args.name if n not in DRILLS_BY_NAME]
        if unknown:
            print(f"unknown drill(s): {unknown}; known: {[d.name for d in DRILLS]}")
            return 2
        selected = [DRILLS_BY_NAME[n] for n in args.name]
    elif args.all:
        selected = list(DRILLS)
    else:
        ap.print_help()
        return 2

    if args.dry_run:
        print(f"DRY RUN — {len(selected)} drill(s) would run against a scratch database:")
        for d in selected:
            print(f"  {d.name:>4}  {d.title}")
            print(f"        pass condition: {d.pass_condition}")
        print("\nNothing was run, no database was opened, and nothing was written.")
        return 0

    ambient = os.environ.get("DATABASE_URL", "")
    if ambient:
        print(
            f"NOTE: ambient DATABASE_URL={ambient} is IGNORED; every drill gets its own scratch DB."
        )

    started = datetime.now(UTC)
    results: list[DrillResult] = []
    with tempfile.TemporaryDirectory(prefix="sf-exec-drills-") as tmp:
        root = Path(tmp)
        for drill in selected:
            with scratch_session(root, drill.name.lower()) as session:
                result = run_drill(drill, session)
            results.append(result)
            mark = "PASS" if result.passed else "FAIL"
            print(f"[{mark}] {drill.name} — {drill.title}")
            for c in result.outcome.checks:
                if not c.passed:
                    print(f"        FAIL {c.label}: {c.detail}")
            if result.error:
                print(f"        ERROR {result.error.splitlines()[0]}")

    passed = sum(1 for r in results if r.passed)
    print(f"\n{passed}/{len(results)} drills passed.")

    if not args.no_report:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"DRILLS_{started.date().isoformat()}.md"
        path.write_text(render_report(results, started=started), encoding="utf-8")
        print(f"report: {path.relative_to(REPO_ROOT)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
