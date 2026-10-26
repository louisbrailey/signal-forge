"""Pre-trade limits — the ``may_open`` / ``may_close`` split (D6 ADR §7).

The existing code already documents the correct asymmetry, verbatim
(``paper/ledger.py``, ``mark_to_market``'s docstring): "Closing an existing
position is allowed while the kill switch is engaged (it is protective); only
*opening* new positions is blocked."

A single "engaged => block everything, cancel_all, disarm" rule would cancel the
resting closing order on an open short option leg and block every subsequent
one, leaving the riskiest position in the book unmanaged. That is the opposite
of protective. So:

* :func:`may_open` evaluates sixteen checks and is **fail-closed**: a check whose
  input is ``None`` — unreadable, unreachable, not computed this cycle — BLOCKS.
  Missing evidence of safety is not evidence of safety.
* :func:`may_close` evaluates five, and they are the ONLY five: each is a
  positive proof about the broker's own book. Nothing in the research state can
  block a close.

Every check is reported, not just the first failure, because every failure is
written to ``execution_event``.

This module is pure — no session (except to load the limits row), no adapter, no
clock. The facts are collected by the cycle (I-E4) and passed in, so each rule is
testable on its own and none of them can be "sort of" evaluated.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.orm import Session

    from signalforge.db.models import ExecutionLimits

__all__ = [
    "CloseGateContext",
    "LimitCheck",
    "LimitDecision",
    "LimitSet",
    "OpenGateContext",
    "binding_cap",
    "limit_set_from_row",
    "load_active_limits",
    "may_close",
    "may_open",
]


@dataclass(frozen=True, slots=True)
class LimitCheck:
    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True, slots=True)
class LimitDecision:
    allowed: bool
    checks: tuple[LimitCheck, ...]

    @property
    def first_failure(self) -> str | None:
        for check in self.checks:
            if not check.passed:
                return f"{check.name}: {check.detail}" if check.detail else check.name
        return None

    @property
    def failures(self) -> tuple[LimitCheck, ...]:
        return tuple(c for c in self.checks if not c.passed)


def _decide(checks: Sequence[LimitCheck]) -> LimitDecision:
    return LimitDecision(allowed=all(c.passed for c in checks), checks=tuple(checks))


def binding_cap(*, usd: float | None, pct: float | None, equity: float | None) -> float | None:
    """``min(dollars, pct x live equity)`` — the tighter of the operator's two
    recorded intents (§4.1).

    Decision 4 states three limits in dollars and map §3.2 states the same three
    as percent-of-equity; on a $25,000 account those are different numbers. Both
    are stored, neither is discarded, and the stricter binds — recomputed each
    cycle from the broker's own equity figure. ``None`` in, ``None`` out: an
    uncomputable cap is not a cap, and the caller must treat it as a block.
    """
    if usd is None:
        return None
    if pct is None or equity is None:
        return usd
    return min(usd, (pct / 100.0) * equity)


@dataclass(frozen=True, slots=True)
class LimitSet:
    """The active ``execution_limits`` row, read fresh each cycle."""

    id: int
    max_orders_per_day: int
    max_order_notional_usd: float
    max_account_exposure_pct: float
    per_structure_max_loss_usd: float
    per_structure_max_loss_pct: float
    aggregate_open_max_loss_usd: float
    aggregate_open_max_loss_pct: float
    collateral_cap_usd: float
    collateral_cap_pct: float
    max_net_delta_notional_usd: float
    max_net_vega_per_volpt_usd: float
    cycle_interval_s: int
    max_intent_age_minutes: int
    max_reconciliation_age_s: int
    execution_stale_after_s: int
    drain_timeout_s: int
    no_submit_after_open_minutes: int
    no_submit_before_close_minutes: int
    buying_power_tolerance_usd: float
    buying_power_tolerance_pct: float
    round_trips_per_5_sessions_max: int
    pdt_equity_threshold_usd: float
    preregistration_doc_id: str

    def __post_init__(self) -> None:
        # §9 / §7b: the dead man must tolerate at least two missed cycles, so the
        # two numbers cannot be set into contradiction.
        if self.execution_stale_after_s < 3 * self.cycle_interval_s:
            raise ValueError(
                f"execution_stale_after_s ({self.execution_stale_after_s}) must be >= "
                f"3 x cycle_interval_s ({self.cycle_interval_s})"
            )
        if not self.preregistration_doc_id:
            # §7b rule 1: the complete row is fixed in a pre-registration
            # document BEFORE the first armed session.
            raise ValueError("an execution_limits row without a preregistration_doc_id is invalid")


def limit_set_from_row(row: ExecutionLimits) -> LimitSet:
    return LimitSet(
        id=row.id,
        max_orders_per_day=row.max_orders_per_day,
        max_order_notional_usd=row.max_order_notional_usd,
        max_account_exposure_pct=row.max_account_exposure_pct,
        per_structure_max_loss_usd=row.per_structure_max_loss_usd,
        per_structure_max_loss_pct=row.per_structure_max_loss_pct,
        aggregate_open_max_loss_usd=row.aggregate_open_max_loss_usd,
        aggregate_open_max_loss_pct=row.aggregate_open_max_loss_pct,
        collateral_cap_usd=row.collateral_cap_usd,
        collateral_cap_pct=row.collateral_cap_pct,
        max_net_delta_notional_usd=row.max_net_delta_notional_usd,
        max_net_vega_per_volpt_usd=row.max_net_vega_per_volpt_usd,
        cycle_interval_s=row.cycle_interval_s,
        max_intent_age_minutes=row.max_intent_age_minutes,
        max_reconciliation_age_s=row.max_reconciliation_age_s,
        execution_stale_after_s=row.execution_stale_after_s,
        drain_timeout_s=row.drain_timeout_s,
        no_submit_after_open_minutes=row.no_submit_after_open_minutes,
        no_submit_before_close_minutes=row.no_submit_before_close_minutes,
        buying_power_tolerance_usd=row.buying_power_tolerance_usd,
        buying_power_tolerance_pct=row.buying_power_tolerance_pct,
        round_trips_per_5_sessions_max=row.round_trips_per_5_sessions_max,
        pdt_equity_threshold_usd=row.pdt_equity_threshold_usd,
        preregistration_doc_id=row.preregistration_doc_id,
    )


def load_active_limits(session: Session) -> LimitSet | None:
    """The one active row, or ``None``.

    ``None`` BLOCKS opening at the call site: "no limits row" is not "no
    limits". An unparseable row (one that fails :class:`LimitSet`'s own
    invariants) is likewise ``None``.
    """
    from sqlalchemy import select

    from signalforge.db.models import ExecutionLimits

    row = session.scalars(
        select(ExecutionLimits)
        .where(ExecutionLimits.superseded_at.is_(None))
        .order_by(ExecutionLimits.created_at.desc(), ExecutionLimits.id.desc())
    ).first()
    if row is None:
        return None
    try:
        return limit_set_from_row(row)
    except (ValueError, TypeError):
        return None


@dataclass(frozen=True, slots=True)
class ArmedFacts:
    """What A1 needs to know about the arming, as read this cycle."""

    adapter_name: str
    expires_at: datetime
    disarmed: bool
    structure_type: str
    approval_level_permits_structure: bool | None


@dataclass(frozen=True, slots=True)
class OpenGateContext:
    """Every fact ``may_open`` needs, collected THIS cycle.

    Every optional field is tri-state on purpose: ``None`` means "could not be
    evaluated", and that BLOCKS. There is no default that quietly means "fine".
    """

    now: datetime
    adapter_name: str
    # K1 — killswitch.ensure_not_engaged() did not raise.
    kill_switch_engaged: bool | None
    # K2 — independent execution-local kill state; unreadable (None) BLOCKS.
    # The shared K1 guard also fails closed on corrupt state. Keep both checks.
    execution_kill_engaged: bool | None
    dead_man_alive: bool | None  # D1
    market_open_broker: bool | None  # C1 - adapter.clock()
    market_open_calendar: bool | None  # C1 - the local calendar
    minutes_since_open: float | None  # C2
    minutes_until_close: float | None  # C2
    is_early_close_session: bool | None  # C3
    armed: ArmedFacts | None  # A1
    is_paper_proven_this_cycle: bool | None  # A2
    intent_expires_at: datetime | None  # I1
    unknown_outstanding_for_strategy: bool | None  # I2
    orders_today: int | None  # L1
    order_notional_usd: float | None  # L2
    account_equity_usd: float | None  # L2
    account_exposure_usd: float | None  # L2
    round_trips_last_5_sessions: int | None  # L3
    reconciliation_clean: bool | None  # R1
    reconciliation_age_s: float | None  # R1
    options_risk_within_limits: bool | None  # R2
    preconditions_ok: bool | None  # P - the seven §5 preconditions, this cycle
    early_close_explicitly_handled: bool = False  # C3
    structure_type: str = "equity"


def _tri(
    name: str, value: bool | None, detail_true: str = "", detail_false: str = ""
) -> LimitCheck:
    """A tri-state check: ``None`` fails with "could not be evaluated"."""
    if value is None:
        return LimitCheck(name, False, "could not be evaluated")
    return LimitCheck(name, value, detail_true if value else detail_false)


def may_open(ctx: OpenGateContext, limits: LimitSet | None) -> LimitDecision:
    """ALL must pass, fail-closed. Every failure is reported."""
    checks: list[LimitCheck] = []

    if limits is None:
        checks.append(
            LimitCheck("L0", False, "no active, parseable execution_limits row — opening blocked")
        )
        # Every remaining numeric check depends on the row; report the block and
        # stop rather than evaluating caps against nothing.
        return _decide(checks)
    checks.append(LimitCheck("L0", True, f"execution_limits id={limits.id}"))

    # --- kill switches ------------------------------------------------------
    checks.append(
        _tri(
            "K1",
            None if ctx.kill_switch_engaged is None else not ctx.kill_switch_engaged,
            detail_false="the kill switch is engaged — opening blocked, closing permitted",
        )
    )
    checks.append(
        _tri(
            "K2",
            None if ctx.execution_kill_engaged is None else not ctx.execution_kill_engaged,
            detail_false="the execution-local kill state is engaged",
        )
    )

    # --- dead man -----------------------------------------------------------
    checks.append(_tri("D1", ctx.dead_man_alive, detail_false="the dead man has lapsed"))

    # --- clock and calendar -------------------------------------------------
    if ctx.market_open_broker is None or ctx.market_open_calendar is None:
        checks.append(LimitCheck("C1", False, "could not be evaluated"))
    elif ctx.market_open_broker != ctx.market_open_calendar:
        checks.append(
            LimitCheck(
                "C1",
                False,
                f"adapter.clock() says open={ctx.market_open_broker} and the calendar says "
                f"open={ctx.market_open_calendar} — two sources of truth disagreeing about "
                "whether the market is open is exactly when an order must not be sent",
            )
        )
    else:
        checks.append(
            LimitCheck(
                "C1",
                ctx.market_open_broker,
                detail="" if ctx.market_open_broker else "the market is closed",
            )
        )

    if ctx.minutes_since_open is None or ctx.minutes_until_close is None:
        checks.append(LimitCheck("C2", False, "could not be evaluated"))
    elif ctx.minutes_since_open < limits.no_submit_after_open_minutes:
        checks.append(
            LimitCheck(
                "C2",
                False,
                f"inside the {limits.no_submit_after_open_minutes}-minute post-open no-submit "
                f"window ({ctx.minutes_since_open:.1f}m since the open)",
            )
        )
    elif ctx.minutes_until_close < limits.no_submit_before_close_minutes:
        checks.append(
            LimitCheck(
                "C2",
                False,
                f"inside the {limits.no_submit_before_close_minutes}-minute pre-close no-submit "
                f"window ({ctx.minutes_until_close:.1f}m until the close)",
            )
        )
    else:
        checks.append(LimitCheck("C2", True))

    if ctx.is_early_close_session is None:
        checks.append(LimitCheck("C3", False, "could not be evaluated"))
    elif ctx.is_early_close_session and not ctx.early_close_explicitly_handled:
        checks.append(
            LimitCheck("C3", False, "early-close session with no explicit calendar handling")
        )
    else:
        checks.append(LimitCheck("C3", True))

    # --- arming and the is_paper proof --------------------------------------
    armed = ctx.armed
    if armed is None:
        checks.append(LimitCheck("A1", False, "no armed_strategy facts for this cycle"))
    elif armed.disarmed:
        checks.append(LimitCheck("A1", False, "the strategy is disarmed"))
    elif armed.expires_at <= ctx.now:
        checks.append(
            LimitCheck("A1", False, f"the arming expired at {armed.expires_at.isoformat()}")
        )
    elif armed.adapter_name != ctx.adapter_name:
        checks.append(
            LimitCheck(
                "A1",
                False,
                f"the arming names adapter {armed.adapter_name!r}, not {ctx.adapter_name!r}",
            )
        )
    elif armed.structure_type != ctx.structure_type:
        checks.append(
            LimitCheck(
                "A1",
                False,
                f"the arming permits structure {armed.structure_type!r}, not "
                f"{ctx.structure_type!r}",
            )
        )
    elif armed.approval_level_permits_structure is not True:
        checks.append(
            LimitCheck(
                "A1",
                False,
                "the asserted options approval level does not permit this structure",
            )
        )
    else:
        checks.append(LimitCheck("A1", True))

    checks.append(
        _tri(
            "A2",
            ctx.is_paper_proven_this_cycle,
            detail_false="is_paper() did not prove out against the armed account id this cycle",
        )
    )

    # --- the intent itself --------------------------------------------------
    if ctx.intent_expires_at is None:
        checks.append(LimitCheck("I1", False, "could not be evaluated"))
    elif ctx.intent_expires_at <= ctx.now:
        checks.append(
            LimitCheck("I1", False, f"the intent expired at {ctx.intent_expires_at.isoformat()}")
        )
    else:
        checks.append(LimitCheck("I1", True))

    checks.append(
        _tri(
            "I2",
            (
                None
                if ctx.unknown_outstanding_for_strategy is None
                else not ctx.unknown_outstanding_for_strategy
            ),
            detail_false="an UNKNOWN intent is outstanding for this strategy",
        )
    )

    # --- counted and sized limits -------------------------------------------
    if ctx.orders_today is None:
        checks.append(LimitCheck("L1", False, "could not be evaluated"))
    elif ctx.orders_today >= limits.max_orders_per_day:
        checks.append(
            LimitCheck(
                "L1",
                False,
                f"{ctx.orders_today} orders today >= cap {limits.max_orders_per_day}",
            )
        )
    else:
        checks.append(LimitCheck("L1", True))

    # The percent side of the per-order notional cap is
    # ``per_structure_max_loss_pct``: §4.1's worked arithmetic runs the same
    # 0.5%-of-equity figure through L2 and through the per-structure max-loss
    # limit, because for a defined-risk structure ``notional`` IS the max loss.
    cap = binding_cap(
        usd=limits.max_order_notional_usd,
        pct=limits.per_structure_max_loss_pct,
        equity=ctx.account_equity_usd,
    )
    if ctx.order_notional_usd is None or cap is None:
        checks.append(LimitCheck("L2", False, "could not be evaluated"))
    elif ctx.order_notional_usd > cap:
        checks.append(
            LimitCheck(
                "L2",
                False,
                f"order notional {ctx.order_notional_usd:.2f} exceeds the binding cap {cap:.2f} "
                "(the tighter of the dollar cap and the percent-of-equity cap)",
            )
        )
    elif (
        ctx.account_exposure_usd is None
        or ctx.account_equity_usd is None
        or ctx.account_equity_usd <= 0
    ):
        checks.append(LimitCheck("L2", False, "account exposure could not be evaluated"))
    elif (
        100.0 * (ctx.account_exposure_usd + ctx.order_notional_usd) / ctx.account_equity_usd
        > limits.max_account_exposure_pct
    ):
        checks.append(
            LimitCheck(
                "L2",
                False,
                f"account exposure would exceed {limits.max_account_exposure_pct}% of equity",
            )
        )
    else:
        checks.append(LimitCheck("L2", True))

    if ctx.round_trips_last_5_sessions is None:
        checks.append(LimitCheck("L3", False, "could not be evaluated"))
    elif ctx.round_trips_last_5_sessions >= limits.round_trips_per_5_sessions_max:
        checks.append(
            LimitCheck(
                "L3",
                False,
                f"{ctx.round_trips_last_5_sessions} round trips in the last 5 sessions >= "
                f"the operator-set threshold {limits.round_trips_per_5_sessions_max}",
            )
        )
    else:
        checks.append(LimitCheck("L3", True))

    # --- reconciliation -----------------------------------------------------
    if ctx.reconciliation_clean is None or ctx.reconciliation_age_s is None:
        checks.append(LimitCheck("R1", False, "could not be evaluated"))
    elif not ctx.reconciliation_clean:
        checks.append(LimitCheck("R1", False, "reconciliation is not CLEAN"))
    elif ctx.reconciliation_age_s > limits.max_reconciliation_age_s:
        checks.append(
            LimitCheck(
                "R1",
                False,
                f"reconciliation is {ctx.reconciliation_age_s:.0f}s old > "
                f"{limits.max_reconciliation_age_s}s — blocks exactly like a dead-man lapse",
            )
        )
    else:
        checks.append(LimitCheck("R1", True))

    checks.append(
        _tri(
            "R2",
            ctx.options_risk_within_limits,
            detail_false="an options risk limit (net delta / net vega / max loss) is breached",
        )
    )

    # --- the seven §5 preconditions, re-evaluated in THIS cycle -------------
    checks.append(
        _tri("P", ctx.preconditions_ok, detail_false="a §5 precondition failed this cycle")
    )

    return _decide(checks)


@dataclass(frozen=True, slots=True)
class CloseGateContext:
    """The five positive proofs — and nothing else (§7).

    PERMITTED while: the kill switch is engaged; the execution-local kill state
    is unreadable; the dead man has lapsed; the strategy is disarmed; the arming
    has expired; ``config_hash``/``spec_json_hash`` have drifted; the approved
    scope no longer matches; an ``UNKNOWN`` is outstanding on some OTHER intent;
    or no ``armed_strategy`` row exists at all.

    BLOCKED only while reconciliation is DIVERGED or the adapter is unreachable.
    """

    position_exists_and_reconciled: bool
    originating_event_exists: bool
    non_increasing_in_every_leg: bool
    intent_kind_is_protective_close: bool
    adapter_reachable: bool
    reconciliation_diverged: bool


def may_close(ctx: CloseGateContext) -> LimitDecision:
    """A separate, narrowly-scoped path. ``may_open``'s inputs are not consulted
    and cannot block this."""
    checks = [
        LimitCheck(
            "C-P1",
            ctx.position_exists_and_reconciled,
            detail="" if ctx.position_exists_and_reconciled else "no reconciled broker position",
        ),
        LimitCheck(
            "C-P2",
            ctx.originating_event_exists,
            detail=(
                ""
                if ctx.originating_event_exists
                else "no originating execution_event — that is a divergence, not a close"
            ),
        ),
        LimitCheck(
            "C-P3",
            ctx.non_increasing_in_every_leg,
            detail="" if ctx.non_increasing_in_every_leg else "a leg would increase exposure",
        ),
        LimitCheck(
            "C-P4",
            ctx.intent_kind_is_protective_close,
            detail=(
                "" if ctx.intent_kind_is_protective_close else "intent_kind is not PROTECTIVE_CLOSE"
            ),
        ),
        LimitCheck(
            "C-P5",
            ctx.adapter_reachable and not ctx.reconciliation_diverged,
            detail=(
                ""
                if ctx.adapter_reachable and not ctx.reconciliation_diverged
                else "the adapter is unreachable or reconciliation is DIVERGED"
            ),
        ),
    ]
    return _decide(checks)
