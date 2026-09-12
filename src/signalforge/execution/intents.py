"""The frozen intent/result data model and the TWO intent factories (D6 §4, §5).

Two things in this module carry most of the safety weight:

**1. There are two factories, not one, and their fail directions are opposite.**
:func:`build_open_intent` re-verifies all seven §5 preconditions against the
database *now* and refuses if any of them fails **or cannot be evaluated**.
:func:`build_close_intent` requires none of them: it requires five positive
proofs about the broker's own book, and an unreadable kill switch, a lapsed
dead man, a missing/expired ``armed_strategy`` row, a drifted ``config_hash``
and a failed scope match all block opening and **none of them block closing**.
A close is the removal of an exposure that already exists, not a new opinion
about a candidate — and the one promise this layer makes above all others is
that the kill switch never blocks closing.

**2. "Notional" is defined per structure type, and a structure type with no
definition cannot produce an intent** (§4.1). The word spans two orders of
magnitude for a credit spread (net credit ≈ $50-150 / max loss $350 / gross
short-leg strike value $60k+), so a cap written against the undefined word is
either inert or a total ban depending on who implements it.

Nothing here contacts a network, reads a credential, or decides *whether* to
trade: an intent is only ever built from a decision some other, gated path has
already made.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING

from signalforge.execution.states import OrderState

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.orm import Session

    from signalforge.execution.limits import LimitDecision

__all__ = [
    "AccountSnapshot",
    "ComboOrderIntent",
    "CloseIntentRefused",
    "CostModelFeedback",
    "Fill",
    "IntentKind",
    "IntentRefused",
    "OptionsStreamUnavailable",
    "OrderIntent",
    "OrderLeg",
    "OrderResult",
    "OrderSide",
    "OrderType",
    "PositionLeg",
    "PositionSnapshot",
    "ReconciledPosition",
    "StructureType",
    "TimeInForce",
    "UndefinedNotional",
    "build_close_intent",
    "build_open_combo_intent",
    "build_open_intent",
    "client_order_id_for",
    "close_client_order_id_for",
    "combo_notional",
    "compute_expires_at",
    "single_notional",
]

#: Equities have no contract multiplier; options do, and it is READ from
#: ``OptionContract.shares_per_contract`` rather than assumed (§14 rule 5).
EQUITY_SHARES_PER_CONTRACT = 1
STANDARD_OPTION_SHARES_PER_CONTRACT = 100


class OrderSide(StrEnum):
    BUY_TO_OPEN = "BUY_TO_OPEN"
    SELL_TO_OPEN = "SELL_TO_OPEN"
    BUY_TO_CLOSE = "BUY_TO_CLOSE"
    SELL_TO_CLOSE = "SELL_TO_CLOSE"

    @property
    def is_opening(self) -> bool:
        return self in (OrderSide.BUY_TO_OPEN, OrderSide.SELL_TO_OPEN)

    @property
    def is_closing(self) -> bool:
        return not self.is_opening

    @property
    def sign(self) -> int:
        """+1 if the order increases signed quantity, -1 if it decreases it."""
        return 1 if self in (OrderSide.BUY_TO_OPEN, OrderSide.BUY_TO_CLOSE) else -1


class IntentKind(StrEnum):
    OPEN = "OPEN"
    PROTECTIVE_CLOSE = "PROTECTIVE_CLOSE"


class OrderType(StrEnum):
    LIMIT = "LIMIT"  # the only order type in Phase 1


class TimeInForce(StrEnum):
    DAY = "DAY"  # the only time-in-force in Phase 1


class StructureType(StrEnum):
    EQUITY = "equity"
    SHORT_VERTICAL = "short_vertical"
    CASH_SECURED_PUT = "cash_secured_put"
    COVERED_CALL = "covered_call"


class IntentRefused(RuntimeError):
    """An intent was refused. The message names the FIRST failed condition.

    Shape deliberately copied from ``paper.ledger.AutoSimulateForbidden`` rather
    than invented: the house pattern is a raise that names the condition.
    """


class CloseIntentRefused(IntentRefused):
    """A PROTECTIVE_CLOSE intent was refused — one of C-P1..C-P5 did not prove."""


class UndefinedNotional(IntentRefused):
    """The structure type has no ``notional`` definition in §4.1's table.

    Fail-closed by construction: a new structure requires an explicit notional
    definition *before* it can be built, never a default.
    """


class OptionsStreamUnavailable(IntentRefused):
    """The options order path is blocked until map §3.6 lands (§5.3b rule 4).

    Specifically: ``assert_options_auto_simulate_allowed``, the
    ``option_structure`` instrument type, and ``paper/options_ledger.py`` must
    exist first. The explicitly refused shortcuts — relaxing P6 to "any actor",
    widening ``assert_auto_simulate_allowed``'s ``("stock", "etf")`` tuple, or
    keying options P6 on ``paper_trade.actor`` — are each a gate weakening in
    disguise and are prohibited.
    """


# ---------------------------------------------------------------------------
# Legs and structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OrderLeg:
    """One leg of a structure. Exactly one of ``option_ticker``/``symbol``."""

    side: OrderSide
    ratio: int
    shares_per_contract: int
    option_ticker: str | None = None
    symbol: str | None = None
    strike: float | None = None  # needed to evaluate §4.1's max-loss notional

    def __post_init__(self) -> None:
        if bool(self.option_ticker) == bool(self.symbol):
            raise IntentRefused("a leg carries exactly one of option_ticker / symbol")
        if self.ratio <= 0:
            raise IntentRefused("leg ratio must be a positive integer")
        if self.option_ticker and self.shares_per_contract != STANDARD_OPTION_SHARES_PER_CONTRACT:
            # A non-100 deliverable is the machine-readable signature of an OCC
            # adjustment (§14 rule 5, map §2.3 / gate 0.h).
            raise IntentRefused(
                f"option leg {self.option_ticker} has shares_per_contract="
                f"{self.shares_per_contract}; only 100 is permitted (OCC adjustment)"
            )
        if self.symbol and self.shares_per_contract != EQUITY_SHARES_PER_CONTRACT:
            raise IntentRefused("an equity leg has shares_per_contract == 1")

    @property
    def instrument_key(self) -> str:
        return self.option_ticker or self.symbol or ""


@dataclass(frozen=True, slots=True)
class CostModelFeedback:
    """§4.2 — what the cost model said, so realized-vs-modelled is computable
    from the audit trail rather than reconstructed.

    Revising a cost-model constant on the evidence of live fills is a version
    bump requiring a fresh sealed look (R3) — never an in-place retune.
    """

    modelled_fill_price: float
    modelled_spread_bps: float

    def realized_minus_modelled_bps(self, realized_fill_price: float) -> float:
        if self.modelled_fill_price == 0:
            raise ValueError("modelled_fill_price is zero; bps difference is undefined")
        return (
            (realized_fill_price - self.modelled_fill_price) / abs(self.modelled_fill_price)
        ) * 10_000.0


@dataclass(frozen=True, slots=True)
class OrderIntent:
    """A single-instrument intent (§4). Frozen: a transition produces a new one."""

    client_order_id: str
    intent_kind: IntentKind
    side: OrderSide
    qty: int
    limit_price: float
    shares_per_contract: int
    adapter_name: str
    created_at: datetime
    expires_at: datetime
    cost_model: CostModelFeedback
    structure_type: StructureType = StructureType.EQUITY
    order_type: OrderType = OrderType.LIMIT
    time_in_force: TimeInForce = TimeInForce.DAY
    symbol: str | None = None
    option_ticker: str | None = None
    source_paper_trade_id: int | None = None
    strategy_version_id: int | None = None
    armed_strategy_id: int | None = None
    execution_limits_id: int | None = None
    config_hash: str = ""
    spec_json_hash: str = ""
    state: OrderState = OrderState.CREATED

    def __post_init__(self) -> None:
        if bool(self.option_ticker) == bool(self.symbol):
            raise IntentRefused("an intent carries exactly one of option_ticker / symbol")
        if self.qty <= 0:
            raise IntentRefused("qty must be positive")
        if self.limit_price <= 0:
            raise IntentRefused("Phase 1 submits LIMIT orders only; limit_price must be positive")

    @property
    def max_notional(self) -> float:
        return single_notional(self.qty, self.limit_price, self.shares_per_contract)

    def with_state(self, state: OrderState) -> OrderIntent:
        return replace(self, state=state)


@dataclass(frozen=True, slots=True)
class ComboOrderIntent:
    """A multi-leg structure submitted as ONE atomic native combo order (§14).

    One ``client_order_id`` for the whole structure. There is no loop over legs
    anywhere in this package: leg-by-leg submission manufactures a naked short
    option on a partial fill, and "cannot submit a combo atomically" is an
    adapter-ineligibility condition (A2), not something to work around.
    """

    client_order_id: str
    intent_kind: IntentKind
    legs: tuple[OrderLeg, ...]
    contracts: int
    net_limit_price: float  # signed: a credit is positive
    structure_type: StructureType
    adapter_name: str
    created_at: datetime
    expires_at: datetime
    cost_model: CostModelFeedback
    order_type: OrderType = OrderType.LIMIT
    time_in_force: TimeInForce = TimeInForce.DAY
    underlying_reference_price: float | None = None
    source_paper_trade_id: int | None = None
    source_options_trade_id: int | None = None
    strategy_version_id: int | None = None
    armed_strategy_id: int | None = None
    execution_limits_id: int | None = None
    config_hash: str = ""
    spec_json_hash: str = ""
    state: OrderState = OrderState.CREATED

    def __post_init__(self) -> None:
        if len(self.legs) < 2:
            raise IntentRefused("a combo intent has at least two legs")
        if self.contracts <= 0:
            raise IntentRefused("contracts must be positive")
        if self.structure_type is StructureType.EQUITY:
            raise IntentRefused("an equity structure is not a combo")

    @property
    def max_notional(self) -> float:
        return combo_notional(self)

    def with_state(self, state: OrderState) -> ComboOrderIntent:
        return replace(self, state=state)


@dataclass(frozen=True, slots=True)
class OrderResult:
    """What an adapter returns. ``*_verbatim`` exists because a broker rejection
    is surfaced verbatim and NEVER retried automatically — a paraphrased
    rejection is an unreviewable one (§20, map §6.7b)."""

    client_order_id: str
    state: OrderState
    broker_order_id: str = ""
    submitted_at: datetime | None = None
    raw_status_verbatim: str = ""
    error_verbatim: str = ""


@dataclass(frozen=True, slots=True)
class Fill:
    client_order_id: str
    leg_index: int
    qty: float
    price: float
    fee: float
    filled_at: datetime
    broker_fill_id: str = ""


@dataclass(frozen=True, slots=True)
class PositionLeg:
    """One leg of a position as the BROKER reports it. ``signed_qty`` is
    negative for a short leg."""

    instrument_key: str
    signed_qty: float
    shares_per_contract: int = EQUITY_SHARES_PER_CONTRACT


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    """A vendor-neutral position as translated by an adapter."""

    adapter_name: str
    legs: tuple[PositionLeg, ...]
    market_value: float = 0.0
    as_of: datetime | None = None


@dataclass(frozen=True, slots=True)
class ReconciledPosition:
    """The positive proof the close lane requires (C-P1, C-P2, C-P5).

    Every field is a fact about the BROKER's book read this cycle, never local
    state alone. ``reconciled`` false, ``adapter_reachable`` false, or
    ``reconciliation_diverged`` true each refuse a close: closing into an
    unknown book is not protective.
    """

    adapter_name: str
    legs: tuple[PositionLeg, ...]
    originating_client_order_id: str
    reconciled: bool
    adapter_reachable: bool
    reconciliation_diverged: bool
    as_of: datetime | None = None

    def leg(self, instrument_key: str) -> PositionLeg | None:
        for leg in self.legs:
            if leg.instrument_key == instrument_key:
                return leg
        return None


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    account_id: str
    equity: float
    buying_power: float
    cash: float = 0.0
    as_of: datetime | None = None


@dataclass(frozen=True, slots=True)
class OrderStatus:
    """A broker order as the adapter translated it — resolvable for a TERMINAL
    order, not only an open one (adapter eligibility condition A4)."""

    client_order_id: str
    state: OrderState
    broker_order_id: str = ""
    filled_qty: float = 0.0
    raw_status_verbatim: str = ""
    legs_filled_ratio: tuple[float, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class MarketClock:
    """The broker's own view of the session, cross-checked against the local
    calendar every cycle — disagreement blocks (§11)."""

    is_open: bool
    as_of: datetime
    next_open: datetime | None = None
    next_close: datetime | None = None
    is_early_close: bool | None = None


# ---------------------------------------------------------------------------
# §4.1 — "notional", defined
# ---------------------------------------------------------------------------


def single_notional(qty: int, limit_price: float, shares_per_contract: int) -> float:
    """``abs(qty * limit_price * shares_per_contract)``; equities pass 1."""
    return abs(qty * limit_price * shares_per_contract)


def combo_notional(intent: ComboOrderIntent) -> float:
    """§4.1's table, and nothing else. An unknown structure type raises.

    * ``short_vertical`` -> **maximum loss**
      ``(strike_width - net_credit_per_contract) * shares_per_contract * contracts``
      — not the net credit (which trivially passes every cap) and not the gross
      strike value of the short leg (one SPY put ~ $60k+, which would block
      every spread the strategy can produce).
    * ``cash_secured_put`` -> **full collateral** ``strike * spc * contracts``.
    * ``covered_call`` -> **underlying market value** of the covered shares.
    """
    spc = intent.legs[0].shares_per_contract
    if any(leg.shares_per_contract != spc for leg in intent.legs):
        raise UndefinedNotional("legs disagree on shares_per_contract")

    if intent.structure_type is StructureType.SHORT_VERTICAL:
        strikes = [leg.strike for leg in intent.legs]
        if any(s is None for s in strikes):
            raise UndefinedNotional("a short_vertical needs a strike on every leg")
        width = max(s for s in strikes if s is not None) - min(s for s in strikes if s is not None)
        if width <= 0:
            raise UndefinedNotional("a short_vertical needs a non-zero strike width")
        credit = intent.net_limit_price
        if credit <= 0:
            raise UndefinedNotional("a short (credit) vertical needs a positive net credit")
        if credit >= width:
            raise UndefinedNotional(
                "net credit >= strike width: max loss is not defined for this structure"
            )
        return (width - credit) * spc * intent.contracts

    if intent.structure_type is StructureType.CASH_SECURED_PUT:
        short_puts = [leg for leg in intent.legs if leg.side is OrderSide.SELL_TO_OPEN]
        strikes = [leg.strike for leg in short_puts]
        if not strikes or any(s is None for s in strikes):
            raise UndefinedNotional("a cash_secured_put needs the short leg's strike")
        return max(s for s in strikes if s is not None) * spc * intent.contracts

    if intent.structure_type is StructureType.COVERED_CALL:
        if intent.underlying_reference_price is None:
            raise UndefinedNotional("a covered_call needs the underlying's market price")
        return abs(intent.underlying_reference_price) * spc * intent.contracts

    raise UndefinedNotional(
        f"structure_type {intent.structure_type!r} has no notional definition in D6 §4.1; "
        "define it there before an intent can be built"
    )


# ---------------------------------------------------------------------------
# §5.4 — idempotency and expiry
# ---------------------------------------------------------------------------


def _leg_signature(legs: Sequence[OrderLeg]) -> str:
    return "|".join(f"{leg.instrument_key}:{leg.side.value}:{leg.ratio}" for leg in legs)


def client_order_id_for(*, source_trade_id: int, legs: Sequence[OrderLeg]) -> str:
    """Deterministic hash of ``(source_paper_trade_id, structure_leg_signature)``.

    ``attempt`` is deliberately NOT in the key: an attempt counter means a retry
    produces a different id, which defeats adapter-idempotency (A1) exactly when
    it matters — a post-timeout retry — and converts an ambiguous response into
    a double fill. Attempts are counted in ``execution_event`` rows.
    """
    if not legs:
        raise IntentRefused("a client_order_id needs at least one leg")
    raw = f"{source_trade_id}#{_leg_signature(legs)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def close_client_order_id_for(*, originating_client_order_id: str, legs: Sequence[OrderLeg]) -> str:
    """The close lane's stable id. Keyed on the ORIGINATING order rather than a
    paper trade, because a close requires no ``PaperTrade`` to exist (§5.2b)."""
    if not originating_client_order_id:
        raise CloseIntentRefused("C-P2: no originating client_order_id")
    raw = f"close:{originating_client_order_id}#{_leg_signature(legs)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def compute_expires_at(
    *,
    created_at: datetime,
    max_intent_age_minutes: int,
    session_end_utc: datetime | None,
) -> datetime:
    """``min(end of the current session, created_at + max_intent_age_minutes)``.

    A missing session end does not extend the life of an intent past its age
    cap; it simply leaves the age cap as the only bound. (For an OPEN intent the
    session must be proven open by C1/C2 anyway, so this is not a way around the
    calendar.)
    """
    if max_intent_age_minutes <= 0:
        raise IntentRefused("max_intent_age_minutes must be positive")
    by_age = created_at + timedelta(minutes=max_intent_age_minutes)
    if session_end_utc is None:
        return by_age
    return min(by_age, session_end_utc)


# ---------------------------------------------------------------------------
# §5.2 — the OPEN factory, fail-closed on every one of the seven preconditions
# ---------------------------------------------------------------------------

#: Signature of the approved-scope matcher the OPEN factory calls at intent
#: time. Injected rather than imported so the execution package keeps a single
#: narrow dependency on research state, and so a test can prove the refusal
#: without building a full promotion evaluation.
ScopeMatcher = Callable[["Session", int, int], bool]


def _refuse(label: str, detail: str) -> IntentRefused:
    return IntentRefused(f"{label}: {detail}")


def _guarded(label: str, fn: Callable[[], object]) -> object:
    """Run a precondition; ANY exception is a refusal.

    §5.2: "Any check that cannot be *evaluated* counts as a failure — for an
    OPEN intent." A missing row, an unreadable file, an exception, a ``None``:
    all refuse.
    """
    try:
        return fn()
    except IntentRefused:
        raise
    except Exception as exc:
        raise _refuse(label, f"could not be evaluated ({type(exc).__name__}: {exc})") from exc


def default_scope_matcher(session: Session, strategy_version_id: int, scan_run_id: int) -> bool:
    """P4 — the full five-part approved-scope match, re-verified NOW.

    Never inherited from the scan record: a status or a scope can change between
    acceptance and submission, and the 2026-09-11 config-hash incident is the
    proof that it does.
    """
    from signalforge.db.models import ScanRun
    from signalforge.research.approval_scope import (
        approved_scopes,
        current_spec_json_hash,
        scan_scope_matches,
    )

    run = session.get(ScanRun, scan_run_id)
    if run is None:
        return False
    return scan_scope_matches(
        approved_scopes(session, strategy_version_id),
        dataset_snapshot_id=run.dataset_snapshot_id,
        config_hash=run.config_hash,
        spec_json_hash=current_spec_json_hash(session, strategy_version_id) or "",
        source=run.source,
        universe=frozenset(s.upper() for s in (run.universe_json or ())),
    )


def build_open_intent(
    session: Session,
    *,
    paper_trade_id: int,
    adapter_name: str,
    side: OrderSide,
    qty: int,
    limit_price: float,
    cost_model: CostModelFeedback,
    limit_decision: LimitDecision | None,
    now: datetime,
    max_intent_age_minutes: int,
    session_end_utc: datetime | None,
    execution_limits_id: int | None = None,
    scope_matcher: ScopeMatcher | None = None,
) -> OrderIntent:
    """Build an equity OPEN intent, or raise :class:`IntentRefused` naming the
    first failed precondition.

    It does **not** trust that an ACCEPTED ``PaperTrade`` implies any of P1-P7:
    ``accept_candidate`` checks none of them and is reachable from the CLI with
    no guard, so "an ACCEPTED PaperTrade exists" is not an authorisation
    predicate (§5.1).
    """
    from signalforge.db.models import ArmedStrategy, Candidate, PaperTrade, StrategyVersion
    from signalforge.domain import QualityGate, StrategyStatus
    from signalforge.paper.auto_simulate import AUTO_SIM_ACTOR

    if not side.is_opening:
        raise _refuse("P0", "an OPEN intent carries an opening side")

    trade = _guarded("P0", lambda: session.get(PaperTrade, paper_trade_id))
    if not isinstance(trade, PaperTrade):
        raise _refuse("P0", f"paper trade {paper_trade_id} not found")

    # --- P6: the source PaperTrade was created by the AUTOMATIC actor -------
    # Evaluated on the indexed column, never on signal_snapshot_json: an
    # order-authorisation predicate must not depend on the shape of a
    # free-form JSON blob (§5.3). On the equity stream this transitively
    # carries P1/P2/P4 and the stock/ETF instrument-type check, because the
    # automatic path is the only one that runs assert_auto_simulate_allowed —
    # and P1/P2/P4 are re-evaluated below anyway.
    if trade.actor != AUTO_SIM_ACTOR:
        raise _refuse(
            "P6",
            f"paper trade {paper_trade_id} was created by {trade.actor!r}, not the automatic "
            f"actor {AUTO_SIM_ACTOR!r}; a manually accepted trade is never an order source",
        )

    cand = _guarded("P1", lambda: session.get(Candidate, trade.candidate_id))
    if not isinstance(cand, Candidate):
        raise _refuse("P1", "the source paper trade has no candidate")

    # --- P1: the candidate PASSED every quality gate ------------------------
    if cand.quality_gate_status is not QualityGate.PASSED:
        raise _refuse("P1", f"candidate quality gate is {cand.quality_gate_status}, not PASSED")

    # --- P2: the strategy version is PAPER_APPROVED, re-read now ------------
    ver = _guarded("P2", lambda: session.get(StrategyVersion, cand.strategy_version_id))
    if not isinstance(ver, StrategyVersion):
        raise _refuse("P2", "strategy version not found")
    if ver.status is not StrategyStatus.PAPER_APPROVED:
        raise _refuse("P2", f"strategy version status is {ver.status}, not PAPER_APPROVED")

    # --- P3: an unexpired armed_strategy row for THIS version + adapter -----
    def _armed() -> ArmedStrategy | None:
        from sqlalchemy import select

        return session.scalars(
            select(ArmedStrategy).where(
                ArmedStrategy.strategy_version_id == ver.id,
                ArmedStrategy.adapter_name == adapter_name,
                ArmedStrategy.disarmed_at.is_(None),
            )
        ).first()

    armed = _guarded("P3", _armed)
    if not isinstance(armed, ArmedStrategy):
        raise _refuse(
            "P3", f"no live armed_strategy row for version {ver.id} on adapter {adapter_name!r}"
        )
    if armed.expires_at <= now:
        raise _refuse("P3", f"the arming expired at {armed.expires_at.isoformat()}")

    # --- P4: the full approved-scope match, re-verified NOW -----------------
    matcher = scope_matcher or default_scope_matcher
    in_scope = _guarded("P4", lambda: matcher(session, ver.id, cand.scan_run_id))
    if in_scope is not True:
        raise _refuse("P4", "the scan's scope does not match the strategy's approved scope")

    # --- P5: risk_dollars was PRESENT on the source candidate ---------------
    # A PaperTrade sized by ledger.py's 0.5%-of-cash fallback is never an order
    # source: nothing downstream can distinguish that fallback from a
    # risk-sized position.
    if cand.risk_dollars is None or cand.risk_dollars <= 0:
        raise _refuse("P5", "the source candidate carried no risk_dollars (the invented-size path)")

    # --- P7: every may_open limit evaluated cleanly in THIS cycle -----------
    if limit_decision is None:
        raise _refuse("P7", "no may_open decision was supplied for this cycle")
    if not limit_decision.allowed:
        raise _refuse("P7", f"may_open blocked: {limit_decision.first_failure}")

    expires_at = compute_expires_at(
        created_at=now,
        max_intent_age_minutes=max_intent_age_minutes,
        session_end_utc=session_end_utc,
    )
    if expires_at <= now:
        raise _refuse("I1", "the intent would be born expired")

    symbol = _guarded("P0", lambda: _instrument_symbol(session, cand.instrument_id))
    if not isinstance(symbol, str) or not symbol:
        raise _refuse("P0", "the candidate's instrument has no symbol")

    leg = OrderLeg(
        side=side,
        ratio=1,
        shares_per_contract=EQUITY_SHARES_PER_CONTRACT,
        symbol=symbol,
    )
    return OrderIntent(
        client_order_id=client_order_id_for(source_trade_id=paper_trade_id, legs=[leg]),
        intent_kind=IntentKind.OPEN,
        side=side,
        qty=qty,
        limit_price=limit_price,
        shares_per_contract=EQUITY_SHARES_PER_CONTRACT,
        adapter_name=adapter_name,
        created_at=now,
        expires_at=expires_at,
        cost_model=cost_model,
        structure_type=StructureType.EQUITY,
        symbol=symbol,
        source_paper_trade_id=paper_trade_id,
        strategy_version_id=ver.id,
        armed_strategy_id=armed.id,
        execution_limits_id=execution_limits_id,
        config_hash=armed.config_hash,
        spec_json_hash=armed.spec_json_hash,
        state=OrderState.CREATED,
    )


def _instrument_symbol(session: Session, instrument_id: int) -> str:
    from signalforge.db.models import Instrument

    inst = session.get(Instrument, instrument_id)
    return inst.symbol if inst is not None else ""


def build_open_combo_intent(*_args: object, **_kwargs: object) -> ComboOrderIntent:
    """The options OPEN lane — BLOCKED until map §3.6 lands (§5.3b rule 4).

    This is a refusal, not a stub to be filled in casually: the options P6
    predicate is ``options_paper_trade.actor == AUTO_SIM_OPTIONS_ACTOR``, a
    NEW and DISTINCT actor constant on an options ledger that does not exist
    yet, and whose guard carries MORE than the equity path (instrument type
    ``option_structure``, the structure-type match, the sixth options scope
    part, the per-leg ``shares_per_contract == 100`` assertion and the
    collateral check).
    """
    raise OptionsStreamUnavailable(
        "the options order path is blocked: assert_options_auto_simulate_allowed, the "
        "'option_structure' instrument type and paper/options_ledger.py (map §3.6) do not "
        "exist yet (D6 §5.3b rule 4)"
    )


# ---------------------------------------------------------------------------
# §5.2b — the CLOSE factory, with the fail direction INVERTED
# ---------------------------------------------------------------------------


def _leg_delta(leg: OrderLeg, contracts: int) -> float:
    """Signed change this leg makes to the position's quantity."""
    return leg.side.sign * leg.ratio * contracts


def assert_non_increasing_per_leg(
    position: ReconciledPosition, legs: Sequence[OrderLeg], contracts: int
) -> None:
    """C-P3 — asserted PER LEG, not per net position.

    A net-reducing intent that increases ANY single leg is refused, so a
    "close" cannot be used to roll into a new short leg.
    """
    for leg in legs:
        if leg.side.is_opening:
            raise CloseIntentRefused(
                f"C-P3: leg {leg.instrument_key} uses the opening side {leg.side.value}"
            )
        held = position.leg(leg.instrument_key)
        if held is None:
            raise CloseIntentRefused(
                f"C-P3: the broker reports no {leg.instrument_key} leg in this position"
            )
        if held.signed_qty == 0:
            raise CloseIntentRefused(f"C-P3: the {leg.instrument_key} leg is already flat")
        delta = _leg_delta(leg, contracts)
        if delta == 0 or (delta > 0) == (held.signed_qty > 0):
            raise CloseIntentRefused(
                f"C-P3: leg {leg.instrument_key} would increase exposure "
                f"({held.signed_qty:+g} by {delta:+g})"
            )
        if abs(delta) > abs(held.signed_qty):
            raise CloseIntentRefused(
                f"C-P3: leg {leg.instrument_key} would flip the position "
                f"({held.signed_qty:+g} by {delta:+g})"
            )


def _assert_close_book_is_known(position: ReconciledPosition) -> None:
    # C-P1 / C-P5. These four checks are the ONLY ones the close lane has, and
    # each is a positive proof about the broker's own book — never a
    # research-state lookup that could be missing.
    if not position.reconciled:
        raise CloseIntentRefused("C-P1: the position is not RECONCILED against adapter.positions()")
    if not position.legs:
        raise CloseIntentRefused("C-P1: the broker reports no legs for this position")
    if not position.adapter_reachable:
        raise CloseIntentRefused("C-P5: the adapter is not reachable")
    if position.reconciliation_diverged:
        raise CloseIntentRefused(
            "C-P5: reconciliation is DIVERGED — closing into an unknown book is not protective"
        )


def _assert_originating_event_exists(session: Session, client_order_id: str) -> None:
    from sqlalchemy import select

    from signalforge.db.models import ExecutionEvent

    if not client_order_id:
        raise CloseIntentRefused("C-P2: the position carries no originating client_order_id")
    found = session.scalar(
        select(ExecutionEvent.id).where(ExecutionEvent.client_order_id == client_order_id).limit(1)
    )
    if found is None:
        # A position this OMS never opened is a §10 divergence and a halt, not a
        # close: letting the system flatten a foreign position would be an
        # unreviewed order.
        raise CloseIntentRefused(
            f"C-P2: no execution_event originates client_order_id {client_order_id!r} — "
            "a position this OMS did not open is a divergence, not a close"
        )


def build_close_intent(
    session: Session,
    *,
    position: ReconciledPosition,
    legs: Sequence[OrderLeg],
    contracts: int,
    limit_price: float,
    cost_model: CostModelFeedback,
    now: datetime,
    max_intent_age_minutes: int,
    session_end_utc: datetime | None = None,
    structure_type: StructureType = StructureType.EQUITY,
    execution_limits_id: int | None = None,
) -> OrderIntent | ComboOrderIntent:
    """Build a PROTECTIVE_CLOSE intent from five positive proofs — and nothing
    else.

    **No ``armed_strategy`` row is required. No ``Candidate`` is required. No
    ``PaperTrade`` is required.** A position that exists at the broker is a fact
    about the world; the research state that produced it may be gone,
    superseded or disarmed, and none of that changes the operator's need to
    flatten it. An unreadable kill switch, an unreadable execution-local kill
    state, a lapsed dead man, a missing armed row, a drifted ``config_hash``, a
    failed scope match, an expired arming and an outstanding ``UNKNOWN`` on some
    OTHER intent all block opening and **none of them block closing**.
    """
    if not legs:
        raise CloseIntentRefused("C-P3: a close intent needs at least one leg")
    if contracts <= 0:
        raise CloseIntentRefused("C-P3: contracts must be positive")

    _assert_close_book_is_known(position)
    _assert_originating_event_exists(session, position.originating_client_order_id)
    assert_non_increasing_per_leg(position, legs, contracts)

    expires_at = compute_expires_at(
        created_at=now,
        max_intent_age_minutes=max_intent_age_minutes,
        session_end_utc=session_end_utc,
    )
    coid = close_client_order_id_for(
        originating_client_order_id=position.originating_client_order_id, legs=legs
    )

    if len(legs) == 1:
        leg = legs[0]
        return OrderIntent(
            client_order_id=coid,
            intent_kind=IntentKind.PROTECTIVE_CLOSE,
            side=leg.side,
            qty=leg.ratio * contracts,
            limit_price=limit_price,
            shares_per_contract=leg.shares_per_contract,
            adapter_name=position.adapter_name,
            created_at=now,
            expires_at=expires_at,
            cost_model=cost_model,
            structure_type=structure_type,
            symbol=leg.symbol,
            option_ticker=leg.option_ticker,
            execution_limits_id=execution_limits_id,
            state=OrderState.CREATED,
        )
    return ComboOrderIntent(
        client_order_id=coid,
        intent_kind=IntentKind.PROTECTIVE_CLOSE,
        legs=tuple(legs),
        contracts=contracts,
        net_limit_price=limit_price,
        structure_type=structure_type,
        adapter_name=position.adapter_name,
        created_at=now,
        expires_at=expires_at,
        cost_model=cost_model,
        execution_limits_id=execution_limits_id,
        state=OrderState.CREATED,
    )
