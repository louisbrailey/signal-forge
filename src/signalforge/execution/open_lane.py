"""The cycle's OPEN lane (D6 ADR §2 cycle body, §5 intents, §6/§8 OMS order).

This is the module that turns an already-gated, already-simulated decision into
a submitted order. Everything else in this package exists to stop it, so read
what it *cannot* do first:

* **It runs only for a strategy version with a live, unexpired ``armed_strategy``
  row.** Nothing is armed by default and arming is a separate, expiring, audited
  operator ceremony with a typed confirmation. With nothing armed this module
  selects no candidates, builds no intents and calls no adapter method — the
  cycle is byte-identical to one without it.
* **It runs only with an adapter**, which is built only when
  ``research.execution.enabled`` is True — shipped False — and only for a name in
  the broker registry, which today contains exactly one: ``paper_reference``, a
  local, deterministic, network-free simulator that opens no socket.
* **It never decides anything.** The decision was made by the research pipeline
  and simulated by ``paper/ledger.py``; the size and the price come from that
  simulation's own ``plan_json``, not from anything computed here. This lane
  submits the order the evidence was built on, or it submits nothing.
* **No LLM is on this path** (S15a), no free text reaches an adapter, and the
  source of every order is a ``PaperTrade`` written by the AUTOMATIC actor —
  a manually accepted trade is never an order source (§5.3 P6).

**The order of operations is §6/§8's and is not negotiable.** For each candidate
order: build the intent through :func:`build_open_intent`, which re-verifies all
seven §5 preconditions LIVE; evaluate every ``may_open`` limit for THIS order;
write and **COMMIT** the ``SUBMITTING`` record; and only then call the adapter.
The commit is the point — a process killed between the record and the broker's
response leaves a durable row the next cycle promotes to ``UNKNOWN`` rather than
silently losing an order that may well have reached the broker.

**Idempotency is structural, not a flag.** ``client_order_id_for`` hashes
``(source_paper_trade_id, leg signature)``, with no attempt counter, so the id
for a given paper trade is the same forever. One paper trade can therefore
produce at most one order: if this OMS has already written any state for that
id, the lane skips it and never looks at it again. A retry after a timeout
re-presents the SAME id, which adapter eligibility condition A1 requires to
produce no second fill.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from signalforge.execution.events import ExecutionEventType, record_execution_event
from signalforge.execution.intents import (
    CostModelFeedback,
    IntentRefused,
    OrderSide,
    build_open_intent,
    client_order_id_for,
)
from signalforge.execution.limits import ArmedFacts, LimitSet, OpenGateContext, may_open
from signalforge.execution.oms import (
    SUBMITTED_LEGS_KEY,
    current_state,
    has_outstanding_unknown,
    record_submitting,
    transition,
)
from signalforge.execution.states import OrderState

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.orm import Session

    from signalforge.db.models import ArmedStrategy, PaperTrade
    from signalforge.execution.calendarcheck import CalendarVerdict
    from signalforge.execution.protocol import BrokerAdapter

__all__ = [
    "DEFAULT_MODELLED_SPREAD_BPS",
    "OpenLaneContext",
    "OpenLaneReport",
    "open_intent_client_order_id",
    "orders_submitted_today",
    "round_trips_last_5_sessions",
    "run_open_lane",
]

#: FACT: ``_NOMINAL_SPREAD_BPS = 5.0`` in ``src/signalforge/paper/ledger.py``, and
#: ``MODEL_SPREAD_BPS_FLOOR = 5.0`` in ``brokers/paper_reference.py``. Declared a
#: third time rather than imported: D6 §15 forbids an ``execution -> paper``
#: dependency, and importing the brokers module here would put the one file
#: permitted to hold a brokerage host literal into the cycle's import graph. A
#: test pins all three together so they cannot drift.
DEFAULT_MODELLED_SPREAD_BPS = 5.0

#: §20.2's window. Five BUSINESS days, approximated as five sessions in which
#: this OMS recorded a fill — the counter is the OMS's own and can only see its
#: own orders, which the pre-registration document states in those words.
ROUND_TRIP_SESSION_WINDOW = 5


@dataclass(frozen=True, slots=True)
class OpenLaneContext:
    """Every cycle-level fact the lane needs, collected by the cycle.

    Passed in rather than re-read here, for the same reason ``limits.may_open``
    takes a context: a gate that fetches its own inputs is a gate that can be
    evaluated against a different cycle's facts than the one it is deciding for.
    Every optional field is tri-state and ``None`` BLOCKS.
    """

    now: datetime
    adapter_name: str
    limits: LimitSet
    verdict: CalendarVerdict
    armed: Sequence[ArmedStrategy]
    kill_switch_engaged: bool | None
    execution_kill_engaged: bool | None
    dead_man_alive: bool | None
    reconciliation_clean: bool | None
    reconciliation_age_s: float | None
    is_paper_proven: bool | None
    account_equity_usd: float | None
    account_exposure_usd: float | None


@dataclass
class OpenLaneReport:
    """What the lane did. A record of observations, never a verdict."""

    considered: int = 0
    skipped_existing: int = 0
    refused: list[str] = field(default_factory=list)
    submitted: list[str] = field(default_factory=list)
    filled: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)

    @property
    def note(self) -> str:
        bits = [f"considered={self.considered}"]
        if self.submitted:
            bits.append(f"submitted={len(self.submitted)}")
        if self.filled:
            bits.append(f"filled={len(self.filled)}")
        if self.rejected:
            bits.append(f"rejected={len(self.rejected)}")
        if self.unresolved:
            bits.append(f"UNRESOLVED={len(self.unresolved)}")
        if self.refused:
            bits.append(f"refused={len(self.refused)}")
        return "; ".join(bits)


# ---------------------------------------------------------------------------
# Counters the gates read, derived from this OMS's OWN records
# ---------------------------------------------------------------------------


def orders_submitted_today(session: Session, *, adapter_name: str, now: datetime) -> int:
    """L1's numerator: distinct orders this OMS submitted today.

    Counted from ``SUBMITTING`` events, not from fills: an order that was sent
    and rejected still consumed the day's allowance, and counting only fills
    would let a rejection loop submit without limit.
    """
    from sqlalchemy import select

    from signalforge.db.models import ExecutionEvent

    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    ids = session.scalars(
        select(ExecutionEvent.client_order_id).where(
            ExecutionEvent.adapter_name == adapter_name,
            ExecutionEvent.event_type == ExecutionEventType.SUBMITTING.value,
            ExecutionEvent.client_order_id != "",
            ExecutionEvent.ts >= start,
        )
    )
    return len({cid for cid in ids if cid})


def round_trips_last_5_sessions(session: Session, *, adapter_name: str, now: datetime) -> int:
    """§20.2 / L3 — round trips this OMS itself opened and closed.

    A round trip is an instrument opened AND closed on the same session date.
    Derived from this OMS's own ``execution_event`` rows, which is the whole of
    what the software can see: the pre-registration document says so in those
    words, and says that a trade the operator places by hand in the same account
    is invisible to it. That limitation is disclosed there rather than papered
    over here.
    """
    from sqlalchemy import select

    from signalforge.db.models import ExecutionEvent
    from signalforge.execution.intents import IntentKind

    since = now - timedelta(days=ROUND_TRIP_SESSION_WINDOW * 2)
    rows = list(
        session.scalars(
            select(ExecutionEvent)
            .where(
                ExecutionEvent.adapter_name == adapter_name,
                ExecutionEvent.event_type == ExecutionEventType.FILL.value,
                ExecutionEvent.ts >= since,
            )
            .order_by(ExecutionEvent.ts.asc(), ExecutionEvent.id.asc())
        )
    )
    legs_by_cid = _submitted_legs_by_client_order_id(session, adapter_name)
    opened: set[tuple[date, str]] = set()
    closed: set[tuple[date, str]] = set()
    for row in rows:
        day = row.ts.date()
        for key in legs_by_cid.get(row.client_order_id, ()):
            if row.intent_kind == IntentKind.PROTECTIVE_CLOSE.value:
                closed.add((day, key))
            else:
                opened.add((day, key))
    sessions = sorted({day for day, _ in opened | closed})[-ROUND_TRIP_SESSION_WINDOW:]
    return len({pair for pair in opened & closed if pair[0] in sessions})


def _submitted_legs_by_client_order_id(
    session: Session, adapter_name: str
) -> dict[str, tuple[str, ...]]:
    """Instrument keys per order, from the OMS's own ``SUBMITTING`` payload."""
    from sqlalchemy import select

    from signalforge.db.models import ExecutionEvent

    out: dict[str, tuple[str, ...]] = {}
    rows = session.scalars(
        select(ExecutionEvent).where(
            ExecutionEvent.adapter_name == adapter_name,
            ExecutionEvent.event_type == ExecutionEventType.SUBMITTING.value,
            ExecutionEvent.client_order_id != "",
        )
    )
    for row in rows:
        payload = row.payload_json if isinstance(row.payload_json, dict) else {}
        legs = payload.get(SUBMITTED_LEGS_KEY)
        if not isinstance(legs, list):
            continue
        keys = tuple(
            str(leg.get("instrument_key"))
            for leg in legs
            if isinstance(leg, dict) and leg.get("instrument_key")
        )
        if keys:
            out.setdefault(row.client_order_id, keys)
    return out


# ---------------------------------------------------------------------------
# Candidate selection
# ---------------------------------------------------------------------------


def _candidate_trades(
    session: Session, *, armed: Sequence[ArmedStrategy], now: datetime
) -> list[PaperTrade]:
    """The ACCEPTED, AUTOMATIC paper trades of ARMED versions, from today.

    Four filters, and each one is a refusal the ADR names:

    * ``decision == ACCEPTED`` — a REJECTED or DEFERRED simulation is not a
      decision to open;
    * ``actor == AUTO_SIM_ACTOR`` — §5.3 P6, read off the INDEXED column and
      never off ``signal_snapshot_json``: an order-authorisation predicate must
      not depend on the shape of a free-form blob. ``build_open_intent`` checks
      it again;
    * the strategy version is one with a LIVE arming — nothing else is
      selectable, which is what makes the lane absent when nothing is armed;
    * ``created_at`` is today — an order priced on yesterday's simulation is a
      different order from the one the gates evaluated, and I1 would refuse it
      anyway. Refusing it here keeps the audit trail free of a refusal per stale
      trade per cycle, forever.
    """
    from sqlalchemy import select

    from signalforge.db.models import Candidate, PaperTrade
    from signalforge.domain import PaperDecision
    from signalforge.paper.auto_simulate import AUTO_SIM_ACTOR

    version_ids = {row.strategy_version_id for row in armed}
    if not version_ids:
        return []
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return list(
        session.scalars(
            select(PaperTrade)
            .join(Candidate, Candidate.id == PaperTrade.candidate_id)
            .where(
                PaperTrade.decision == PaperDecision.ACCEPTED,
                PaperTrade.actor == AUTO_SIM_ACTOR,
                PaperTrade.created_at >= start_of_day,
                Candidate.strategy_version_id.in_(version_ids),
            )
            .order_by(PaperTrade.id)
        )
    )


def _plan(trade: PaperTrade) -> tuple[int, float]:
    """``(shares, modelled fill price)`` as ``paper/ledger.py`` recorded them.

    The size and the price are the SIMULATION's, never recomputed here. A lane
    that re-derived them could submit an order the evidence was not built on,
    and "the simulation said 12 shares at 471.18" is the only defensible answer
    to "why this size, at this price".
    """
    plan = trade.plan_json if isinstance(trade.plan_json, dict) else {}
    shares = plan.get("shares")
    price = plan.get("fill_price")
    if not isinstance(shares, int) or shares < 1:
        raise IntentRefused(
            f"P0: paper trade {trade.id} carries no usable share count in plan_json "
            f"({shares!r}); the simulated size is the only size this lane will submit"
        )
    if not isinstance(price, int | float) or price <= 0:
        raise IntentRefused(
            f"P0: paper trade {trade.id} carries no modelled fill price in plan_json "
            f"({price!r}); an order priced by this lane rather than by the simulation is "
            "an order the evidence was not built on"
        )
    return int(shares), float(price)


def _side_for(session: Session, trade: PaperTrade) -> OrderSide:
    from signalforge.db.models import Candidate
    from signalforge.domain import Direction

    cand = session.get(Candidate, trade.candidate_id)
    if cand is None:
        raise IntentRefused(f"P1: paper trade {trade.id} has no candidate")
    return OrderSide.BUY_TO_OPEN if cand.direction is Direction.LONG else OrderSide.SELL_TO_OPEN


def _armed_facts(row: ArmedStrategy, *, adapter_name: str) -> ArmedFacts:
    return ArmedFacts(
        adapter_name=row.adapter_name or adapter_name,
        expires_at=row.expires_at,
        disarmed=row.disarmed_at is not None,
        structure_type=row.structure_type,
        # Equity only in this lane: an options structure needs the operator's
        # real approval level, which is decision 3 and is still outstanding, and
        # build_open_combo_intent refuses outright until map §3.6 lands.
        approval_level_permits_structure=row.structure_type == "equity",
    )


# ---------------------------------------------------------------------------
# The lane
# ---------------------------------------------------------------------------


def run_open_lane(
    session: Session,
    ctx: OpenLaneContext,
    *,
    adapter: BrokerAdapter,
    actor: str = "system",
) -> OpenLaneReport:
    """Submit at most one order per eligible paper trade, in §6/§8's order.

    Returns what it observed. Every refusal, submission and outcome is written
    to ``execution_event`` (and mirrored into the audit sink) before this
    returns, because a submission whose result is not recorded is a submission
    nobody can reconcile.
    """
    report = OpenLaneReport()
    armed_by_version = {row.strategy_version_id: row for row in ctx.armed}
    if not armed_by_version:
        # The default state. No selection query runs, no intent is built, and no
        # adapter method is called: the lane is absent, not merely inert.
        return report

    trades = _candidate_trades(session, armed=ctx.armed, now=ctx.now)
    orders_today = orders_submitted_today(session, adapter_name=ctx.adapter_name, now=ctx.now)
    round_trips = round_trips_last_5_sessions(session, adapter_name=ctx.adapter_name, now=ctx.now)

    for trade in trades:
        report.considered += 1
        outcome = _submit_one(
            session,
            trade,
            ctx=ctx,
            adapter=adapter,
            armed_by_version=armed_by_version,
            orders_today=orders_today,
            round_trips=round_trips,
            report=report,
            actor=actor,
        )
        if outcome:
            # Each submission consumes the day's allowance whatever it returned.
            orders_today += 1
    return report


def _submit_one(
    session: Session,
    trade: PaperTrade,
    *,
    ctx: OpenLaneContext,
    adapter: BrokerAdapter,
    armed_by_version: dict[int, ArmedStrategy],
    orders_today: int,
    round_trips: int,
    report: OpenLaneReport,
    actor: str,
) -> bool:
    """One paper trade. Returns True if an order was actually submitted."""
    from signalforge.db.models import Candidate
    from signalforge.execution.intents import OrderLeg

    cand = session.get(Candidate, trade.candidate_id)
    if cand is None:
        return False
    armed_row = armed_by_version.get(cand.strategy_version_id)
    if armed_row is None:
        return False

    try:
        shares, modelled_price = _plan(trade)
        side = _side_for(session, trade)
    except IntentRefused as exc:
        _refuse(session, ctx, report, trade, reason=str(exc), actor=actor)
        return False

    symbol = _symbol(session, cand.instrument_id)
    if not symbol:
        _refuse(session, ctx, report, trade, reason="P0: the instrument has no symbol", actor=actor)
        return False

    # --- one intent per paper trade, EVER --------------------------------
    #
    # The id is a hash of (paper trade, leg signature) with no attempt counter,
    # so it is the same forever. Any recorded state for it means this OMS has
    # already acted on this trade — including an UNKNOWN, which is exactly when
    # a second submission would be catastrophic.
    leg = OrderLeg(side=side, ratio=1, shares_per_contract=1, symbol=symbol)
    client_order_id = client_order_id_for(source_trade_id=trade.id, legs=[leg])
    if current_state(session, client_order_id) is not None:
        report.skipped_existing += 1
        return False

    # --- every may_open limit, for THIS order ----------------------------
    notional = float(shares) * float(modelled_price)
    decision = may_open(
        OpenGateContext(
            now=ctx.now,
            adapter_name=ctx.adapter_name,
            kill_switch_engaged=ctx.kill_switch_engaged,
            execution_kill_engaged=ctx.execution_kill_engaged,
            dead_man_alive=ctx.dead_man_alive,
            market_open_broker=ctx.verdict.market_open_broker,
            market_open_calendar=ctx.verdict.market_open_calendar,
            minutes_since_open=ctx.verdict.minutes_since_open,
            minutes_until_close=ctx.verdict.minutes_until_close,
            is_early_close_session=ctx.verdict.is_early_close_session,
            early_close_explicitly_handled=ctx.verdict.early_close_explicitly_handled,
            armed=_armed_facts(armed_row, adapter_name=ctx.adapter_name),
            is_paper_proven_this_cycle=ctx.is_paper_proven,
            intent_expires_at=ctx.now + timedelta(minutes=ctx.limits.max_intent_age_minutes),
            unknown_outstanding_for_strategy=has_outstanding_unknown(
                session, cand.strategy_version_id
            ),
            orders_today=orders_today,
            order_notional_usd=notional,
            account_equity_usd=ctx.account_equity_usd,
            account_exposure_usd=ctx.account_exposure_usd,
            round_trips_last_5_sessions=round_trips,
            reconciliation_clean=ctx.reconciliation_clean,
            reconciliation_age_s=ctx.reconciliation_age_s,
            # R2 is the options risk block. This lane is equity-only, so there
            # is no net delta/vega/max-loss surface to breach — stated as True
            # rather than left None, which would block every equity order on a
            # check that does not apply to it.
            options_risk_within_limits=True,
            preconditions_ok=True,
            structure_type="equity",
        ),
        ctx.limits,
    )

    # --- the §5 factory: all seven preconditions, re-verified LIVE --------
    try:
        intent = build_open_intent(
            session,
            paper_trade_id=trade.id,
            adapter_name=ctx.adapter_name,
            side=side,
            qty=shares,
            limit_price=modelled_price,
            cost_model=CostModelFeedback(
                modelled_fill_price=modelled_price,
                modelled_spread_bps=DEFAULT_MODELLED_SPREAD_BPS,
            ),
            limit_decision=decision,
            now=ctx.now,
            max_intent_age_minutes=ctx.limits.max_intent_age_minutes,
            session_end_utc=ctx.verdict.session_end_utc,
            execution_limits_id=ctx.limits.id,
        )
    except IntentRefused as exc:
        _refuse(session, ctx, report, trade, reason=str(exc), actor=actor)
        return False

    record_execution_event(
        session,
        event_type=ExecutionEventType.INTENT_CREATED,
        adapter_name=ctx.adapter_name,
        client_order_id=intent.client_order_id,
        intent_kind=intent.intent_kind.value,
        reason=f"{side.value} {shares} {symbol} @ {modelled_price:.4f} (limit)",
        source_paper_trade_id=trade.id,
        strategy_version_id=intent.strategy_version_id,
        armed_strategy_id=intent.armed_strategy_id,
        execution_limits_id=intent.execution_limits_id,
        config_hash=intent.config_hash,
        spec_json_hash=intent.spec_json_hash,
        payload={"notional_usd": notional, "checks": len(decision.checks)},
        actor=actor,
    )

    # --- §6/§8: VALIDATED, then SUBMITTING committed, THEN the adapter ----
    validated = transition(
        session,
        intent,
        OrderState.VALIDATED,
        reason="every §5 precondition and every §7 may_open limit passed this cycle",
        actor=actor,
    )
    submitting = record_submitting(session, validated, actor=actor)
    report.submitted.append(intent.client_order_id)

    try:
        result = adapter.place(submitting)  # type: ignore[arg-type]
    except Exception as exc:
        # The order may or may not have reached the broker. It is UNKNOWN, never
        # assumed failed, and it is NEVER retried here: the durable SUBMITTING
        # record is already committed and the next cycle promotes it. A retry in
        # this except block is how an ambiguous response becomes a double fill.
        record_execution_event(
            session,
            event_type=ExecutionEventType.ADAPTER_CALL,
            adapter_name=ctx.adapter_name,
            client_order_id=intent.client_order_id,
            intent_kind=intent.intent_kind.value,
            reason=(
                f"place() did not return ({type(exc).__name__}): the order may or may not have "
                "reached the broker — UNKNOWN, never assumed failed, and never retried here"
            )[:300],
            error_verbatim=repr(exc)[:2000],
            strategy_version_id=intent.strategy_version_id,
            armed_strategy_id=intent.armed_strategy_id,
            actor=actor,
        )
        report.unresolved.append(intent.client_order_id)
        return True

    if result.state is OrderState.FILLED or result.state is OrderState.PARTIAL:
        report.filled.append(intent.client_order_id)
    elif result.state is OrderState.REJECTED:
        report.rejected.append(intent.client_order_id)
    return True


def _refuse(
    session: Session,
    ctx: OpenLaneContext,
    report: OpenLaneReport,
    trade: PaperTrade,
    *,
    reason: str,
    actor: str,
) -> None:
    """Record a refusal. Every one of them, every cycle, with its reason."""
    report.refused.append(f"{trade.id}:{reason[:120]}")
    record_execution_event(
        session,
        event_type=ExecutionEventType.INTENT_REFUSED,
        adapter_name=ctx.adapter_name,
        reason=reason[:300],
        source_paper_trade_id=trade.id,
        execution_limits_id=ctx.limits.id,
        actor=actor,
    )


def _symbol(session: Session, instrument_id: int) -> str:
    from signalforge.db.models import Instrument

    inst = session.get(Instrument, instrument_id)
    return inst.symbol if inst is not None else ""


def open_intent_client_order_id(*, trade_id: int, symbol: str, side: OrderSide) -> str:
    """The id this lane WOULD use for a trade — for tests and for the drills."""
    from signalforge.execution.intents import OrderLeg

    leg = OrderLeg(side=side, ratio=1, shares_per_contract=1, symbol=symbol)
    return client_order_id_for(source_trade_id=trade_id, legs=[leg])
