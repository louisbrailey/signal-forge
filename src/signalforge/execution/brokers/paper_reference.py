"""``paper_reference`` — the FIRST adapter: local, deterministic, network-free.

Authorised by D6 ADR §3.1, and it is the sole substrate for every §21 Phase V
drill before a vendor adapter is written. It satisfies the §3 ``BrokerAdapter``
protocol for equities **and** for multi-leg option combos.

**Its output is never evidence.** Fills, cash movements and anything derived
from them are drill artifacts: excluded from decision 10's >= 20-closed-trade
count, from ``strategy_health``, from expectancy, and from every promotion gate
(§3.1 rule 4, asserted by T10). Every event it writes carries
``adapter_name = 'paper_reference'`` so that exclusion is a filter on a recorded
fact rather than a convention. Two structural choices make the fence hard
rather than declared:

* **Equity never moves.** The account marks its book at cost, so profit and
  loss is identically zero by construction. There is no number here that could
  be mistaken for performance, because there is no performance.
* **The fill rule is never kinder than the backtest's cost model.** See below.

The fill rule (§3.1, all four rules, and each one is enforced rather than
described):

1. **Information set.** A fill is decided only from information stamped
   **strictly before** the intent's submission timestamp. Rule 1's two halves
   differ at the boundary instant ("at or before" vs. "no bar stamped at or
   after ... may be read"); the prohibition is the operative half, so a quote
   stamped exactly *at* the submission timestamp is refused like a later one.
   :class:`PreSubmissionInformation` raises :class:`LookaheadRefused` rather
   than returning a value, so a lookahead is a crash and not a better fill.
2. **Never better than the modelled spread.** The fill is
   ``limit -/+ modelled half-spread`` in the unfavourable direction, using the
   same spread constant the backtest uses. The intent carries its own
   ``modelled_spread_bps`` (§4.2), and this adapter takes
   ``max(that, MODEL_SPREAD_BPS_FLOOR)``: an intent built with a kinder spread
   cannot make the simulator kinder. Note this is deliberately *worse* than a
   real limit order can fill — a real limit buy fills at or below its limit,
   never above it. Rule 2 specifies this arithmetic, the adapter is fenced off
   from every gate, and a pessimistic simulator is the safe direction for one
   whose fills the implementer controls.
3. **Determinism.** No clock is read, no random source exists, and no ordering
   depends on a dict's insertion history: the same intent against the same
   information set produces a byte-identical result, including timestamps and
   the broker order id (a hash of the client order id).
4. **Never evidence.** As above.

**A partial fill can never leave a naked short leg (§14).** The filled size is
one scalar — ``filled_units`` — applied to every leg as ``ratio_i *
filled_units``. There is no loop that fills legs independently, so a by-leg
partial is not merely rejected: it is not expressible. A leg whose availability
is zero drives ``min()`` to zero and the whole structure rests unfilled; it
never fills the other leg alone. :func:`assert_no_naked_short_leg` re-checks the
filled ratios against the declared ratios before any result leaves the adapter,
and halts if they ever disagree.

**It opens no socket.** This module imports no HTTP client, no ``socket``, and
no vendor package, and it is built only through
``signalforge.execution.brokers.build_adapter`` — never by an import side
effect.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from signalforge.execution.events import ExecutionEventType, record_execution_event
from signalforge.execution.intents import (
    AccountSnapshot as AccountSnapshotType,
)
from signalforge.execution.intents import (
    ComboOrderIntent,
    Fill,
    IntentRefused,
    MarketClock,
    OrderIntent,
    OrderLeg,
    OrderResult,
    OrderSide,
    OrderStatus,
    PositionLeg,
    PositionSnapshot,
)
from signalforge.execution.protocol import IsPaperProof
from signalforge.execution.states import OrderState

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.orm import Session

__all__ = [
    "AdapterAudit",
    "ByLegPartialHalt",
    "ExecutionEventAudit",
    "LookaheadRefused",
    "MODEL_SPREAD_BPS_FLOOR",
    "PAPER_HOST_ALLOWLIST",
    "PAPER_REFERENCE_NAME",
    "PaperReferenceBroker",
    "PreSubmissionInformation",
    "ReferenceQuote",
    "SIMULATED_ACCOUNT_PREFIX",
    "SimulatedAccount",
    "SimulatedBrokerTimeout",
    "SimulatedOrder",
    "assert_no_naked_short_leg",
    "degraded_limit",
    "effective_spread_bps",
    "half_spread_fraction",
]

PAPER_REFERENCE_NAME = "paper_reference"

#: §13 rule 5 — the literal, reviewed paper-host allowlist. This adapter speaks
#: to no host at all; the sentinel is a reserved-TLD name that resolves nowhere,
#: so a future edit that gave this module a real host would fail the check
#: instead of silently connecting.
LOCAL_HOST_SENTINEL = "local.paper-reference.invalid"
PAPER_HOST_ALLOWLIST: tuple[str, ...] = (LOCAL_HOST_SENTINEL,)

#: FACT: ``_NOMINAL_SPREAD_BPS = 5.0`` in ``src/signalforge/paper/ledger.py``.
#: Re-declared rather than imported: D6 §15 forbids creating an
#: ``execution -> paper`` dependency (S15b already forbids the reverse), so the
#: constant is duplicated and a test asserts the two never drift apart.
MODEL_SPREAD_BPS_FLOOR = 5.0

#: Every simulated account id carries this prefix, and the adapter refuses to
#: be constructed with one that does not. A reviewer reading an
#: ``execution_event`` can tell at a glance that the account was simulated,
#: without consulting the adapter name as well.
SIMULATED_ACCOUNT_PREFIX = "PAPER-SIM-"


class LookaheadRefused(RuntimeError):
    """A fill was about to be decided from information at or after submission.

    §3.1 rule 1. Raised rather than worked around: a simulator that consults a
    bar stamped at or after the submission timestamp is performing lookahead,
    and every drill would still pass.
    """


class SimulatedBrokerTimeout(RuntimeError):
    """The broker recorded the order; the caller never heard the response.

    The §8 hazard, reproducible on demand. The order IS in this adapter's book
    afterwards, which is the whole point: ``order_status()`` must be queried
    before any resubmission, and a resubmission of the same id must not
    double-fill.
    """


class ByLegPartialHalt(RuntimeError):
    """Filled ratios disagree across the legs of one structure — a HALT.

    §14 rule 3/4: an unpaired short leg is not a position. This adapter cannot
    reach the condition (the filled size is a single scalar); the check exists
    so that a future edit which made it reachable stops the process instead of
    manufacturing a naked short option.
    """


# ---------------------------------------------------------------------------
# The pre-submission information set (§3.1 rule 1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReferenceQuote:
    """One instrument's reference price, and how much of it was available.

    ``as_of`` must be strictly before the submission timestamp of any intent
    this quote is used to fill. ``available_qty`` is in the instrument's own
    units — shares for an equity, contracts for an option leg — and ``None``
    means "unbounded at this price"; it is what makes a partial fill
    expressible.
    """

    instrument_key: str
    reference_price: float
    as_of: datetime
    available_qty: int | None = None

    def __post_init__(self) -> None:
        if not self.instrument_key:
            raise ValueError("a reference quote needs an instrument key")
        if self.reference_price <= 0:
            raise ValueError(f"{self.instrument_key}: reference_price must be positive")
        if self.available_qty is not None and self.available_qty < 0:
            raise ValueError(f"{self.instrument_key}: available_qty cannot be negative")


@dataclass(frozen=True, slots=True)
class PreSubmissionInformation:
    """Everything the fill rule is allowed to see, and nothing else.

    The adapter holds one of these and can reach no other source of prices: it
    has no session, no data adapter and no network, so "only information at or
    before submission" is a property of what it *can* read rather than a rule
    it is trusted to follow.
    """

    quotes: tuple[ReferenceQuote, ...] = ()

    @classmethod
    def of(cls, quotes: Sequence[ReferenceQuote]) -> PreSubmissionInformation:
        return cls(quotes=tuple(quotes))

    def quote(self, instrument_key: str, *, submitted_at: datetime) -> ReferenceQuote:
        """The quote for ``instrument_key``, or raise.

        Raises :class:`LookaheadRefused` if the only quote available is stamped
        at or after ``submitted_at``, and :class:`KeyError` if there is none at
        all. Neither is a fill.
        """
        matches = [q for q in self.quotes if q.instrument_key == instrument_key]
        if not matches:
            raise KeyError(instrument_key)
        usable = [q for q in matches if q.as_of < submitted_at]
        if not usable:
            latest = max(matches, key=lambda q: q.as_of)
            raise LookaheadRefused(
                f"{instrument_key}: the only quote is stamped {latest.as_of.isoformat()}, "
                f"at or after the submission timestamp {submitted_at.isoformat()} — "
                "a paper_reference fill may be decided only from strictly earlier information "
                "(D6 §3.1 rule 1)"
            )
        # Deterministic: the latest quote strictly before submission.
        return max(usable, key=lambda q: q.as_of)


@dataclass(frozen=True, slots=True)
class SimulatedAccount:
    """The simulated broker's own account record — the "response body" §13's
    proof is read out of."""

    account_id: str
    initial_cash: float
    buying_power: float | None = None

    def __post_init__(self) -> None:
        if not self.account_id.startswith(SIMULATED_ACCOUNT_PREFIX):
            raise ValueError(
                f"a paper_reference account id must start with {SIMULATED_ACCOUNT_PREFIX!r}; "
                f"got {self.account_id!r}"
            )
        if self.initial_cash <= 0:
            raise ValueError("initial_cash must be positive")


# ---------------------------------------------------------------------------
# Audit — every call, through the I-E2 path (§15)
# ---------------------------------------------------------------------------


@runtime_checkable
class AdapterAudit(Protocol):
    """Where the adapter writes. There is no default and no null implementation
    in this module: an adapter that cannot record what it did cannot be built."""

    def record(self, event_type: ExecutionEventType, /, **fields: Any) -> None: ...


class ExecutionEventAudit:
    """The production sink: one ``execution_event`` row plus one
    ``audit.record(...)`` call per adapter call, via I-E2's
    :func:`~signalforge.execution.events.record_execution_event`.

    It does not commit. The caller owns the transaction boundary, because §2's
    SQLite discipline — never hold a write lock across a broker round trip — is
    a property of the *cycle*, not of a single call.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def record(self, event_type: ExecutionEventType, /, **fields: Any) -> None:
        fields.setdefault("adapter_name", PAPER_REFERENCE_NAME)
        record_execution_event(self._session, event_type=event_type, **fields)


# ---------------------------------------------------------------------------
# The fill rule, as pure functions (§3.1 rules 2 and 3)
# ---------------------------------------------------------------------------


def effective_spread_bps(modelled_spread_bps: float) -> float:
    """``max(the intent's modelled spread, the backtest's constant)``.

    The floor is the point: decision 5 makes modelled spreads a permanent
    disclosed assumption and gate 4b permanent, so the simulator must not
    quietly be kinder than the model the evidence rests on. An intent built
    with a tighter spread gets the floor, not the intent's number.
    """
    return max(float(modelled_spread_bps), MODEL_SPREAD_BPS_FLOOR)


def half_spread_fraction(spread_bps: float) -> float:
    """``(bps / 10_000) / 2`` — the same arithmetic as ``paper/ledger.py``."""
    return (effective_spread_bps(spread_bps) / 10_000.0) / 2.0


def degraded_limit(net_limit_price: float, spread_bps: float) -> float:
    """``limit -/+ half-spread``, always in the unfavourable direction.

    ``net_limit_price`` is signed with a credit positive, so subtracting a
    positive amount is "worse" for a credit (receive less) and for a debit
    (pay more) alike — one expression, no branch that could get a sign wrong.
    """
    return net_limit_price - abs(net_limit_price) * half_spread_fraction(spread_bps)


def _signed_leg_price(side: OrderSide, price: float) -> float:
    """A sale contributes a credit (+), a purchase a debit (-)."""
    return price if side.sign < 0 else -price


def net_reference_price(legs: Sequence[OrderLeg], prices: Sequence[float]) -> float:
    """The structure's net price at the given per-leg references, credit
    positive."""
    return sum(
        _signed_leg_price(leg.side, price) * leg.ratio
        for leg, price in zip(legs, prices, strict=True)
    )


def assert_no_naked_short_leg(
    legs: Sequence[OrderLeg], filled_ratios: Sequence[float], *, client_order_id: str
) -> None:
    """§14 rule 4: compare the filled ratios across legs. Disagreement HALTS.

    Unreachable from this adapter by construction — the filled size is a single
    scalar applied to every leg — and that is exactly why it is asserted rather
    than assumed. If a later edit made per-leg fills expressible, the first
    unpaired short leg raises here instead of becoming a position.
    """
    if len(legs) != len(filled_ratios):
        raise ByLegPartialHalt(
            f"{client_order_id}: {len(filled_ratios)} filled ratios for {len(legs)} legs"
        )
    if not filled_ratios:
        return
    first = filled_ratios[0]
    offenders = [
        f"{leg.instrument_key}={ratio:.6f}"
        for leg, ratio in zip(legs, filled_ratios, strict=True)
        if abs(ratio - first) > 1e-9
    ]
    if offenders:
        raise ByLegPartialHalt(
            f"{client_order_id}: a partial fill BY LEG is a halt, not a position — "
            f"an unpaired short leg is an accidental naked short option (D6 §14): "
            + ", ".join(offenders)
        )


# ---------------------------------------------------------------------------
# The simulated book
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SimulatedOrder:
    """One order as this adapter's own book holds it.

    ``filled_units`` is the single scalar that makes a by-leg partial
    inexpressible: every leg filled ``ratio_i * filled_units``, always.
    """

    client_order_id: str
    broker_order_id: str
    fingerprint: str
    state: OrderState
    submitted_at: datetime
    legs: tuple[OrderLeg, ...]
    requested_units: int
    filled_units: int
    leg_fill_prices: tuple[float, ...]
    net_fill_price: float
    intent_kind: str
    structure_type: str
    raw_status_verbatim: str = ""
    error_verbatim: str = ""
    source_paper_trade_id: int | None = None
    strategy_version_id: int | None = None
    armed_strategy_id: int | None = None
    execution_limits_id: int | None = None
    config_hash: str = ""
    spec_json_hash: str = ""
    modelled_fill_price: float = 0.0
    modelled_spread_bps: float = 0.0

    @property
    def filled_ratios(self) -> tuple[float, ...]:
        """One ratio per leg — identical across legs by construction."""
        if self.requested_units <= 0:
            return tuple(0.0 for _ in self.legs)
        ratio = self.filled_units / self.requested_units
        return tuple(ratio for _ in self.legs)

    @property
    def result(self) -> OrderResult:
        return OrderResult(
            client_order_id=self.client_order_id,
            state=self.state,
            broker_order_id=self.broker_order_id,
            submitted_at=self.submitted_at,
            raw_status_verbatim=self.raw_status_verbatim,
            error_verbatim=self.error_verbatim,
        )

    @property
    def status(self) -> OrderStatus:
        return OrderStatus(
            client_order_id=self.client_order_id,
            state=self.state,
            broker_order_id=self.broker_order_id,
            filled_qty=float(self.filled_units),
            raw_status_verbatim=self.raw_status_verbatim,
            legs_filled_ratio=self.filled_ratios,
        )

    def fills(self) -> tuple[Fill, ...]:
        if self.filled_units <= 0:
            return ()
        return tuple(
            Fill(
                client_order_id=self.client_order_id,
                leg_index=index,
                qty=float(leg.ratio * self.filled_units),
                price=price,
                fee=0.0,
                filled_at=self.submitted_at,
                broker_fill_id=f"{self.broker_order_id}-L{index}",
            )
            for index, (leg, price) in enumerate(zip(self.legs, self.leg_fill_prices, strict=True))
        )


def _fingerprint(
    legs: Sequence[OrderLeg],
    units: int,
    net_limit_price: float,
    source_paper_trade_id: int | None,
) -> str:
    """The ECONOMIC identity of an order, independent of its client id.

    A1 makes a resubmission of the *same* id safe. This is the other half, and
    it is stricter than a real broker: a second order with the same economics
    under a *different* client id is refused, so "mint a fresh id after a
    timeout" cannot double-fill even though the §5.4 id rule (a deterministic
    hash with no attempt counter) already makes minting one impossible from the
    factories.
    """
    parts = [
        str(source_paper_trade_id),
        str(units),
        f"{net_limit_price:.10f}",
        *(f"{leg.instrument_key}:{leg.side.value}:{leg.ratio}" for leg in legs),
    ]
    return hashlib.sha256("#".join(parts).encode("utf-8")).hexdigest()[:32]


def _broker_order_id(client_order_id: str) -> str:
    """Deterministic, so a rerun produces a byte-identical result (rule 3)."""
    return "PRF-" + hashlib.sha256(client_order_id.encode("utf-8")).hexdigest()[:16]


class PaperReferenceBroker:
    """A local, deterministic, network-free :class:`BrokerAdapter`.

    Constructed **only** through
    :func:`signalforge.execution.brokers.build_adapter`, which refuses unless
    ``execution.enabled`` is True and ``execution.adapter_name`` selects it.
    Every argument is required: there is no default account, no default
    information set, and no default audit sink.
    """

    name = PAPER_REFERENCE_NAME

    #: Counts constructions in this interpreter. A safety test asserts it is
    #: still zero after importing every execution module, which is how "never
    #: instantiated by an import side effect" is proved rather than asserted.
    instances_created = 0

    def __init__(
        self,
        *,
        audit: AdapterAudit,
        account: SimulatedAccount,
        expected_account_id: str,
        information: PreSubmissionInformation,
        clock: MarketClock,
    ) -> None:
        if not expected_account_id:
            raise ValueError(
                "expected_account_id is required: it is the operator-typed value from the "
                "armed record (D6 §13 step 2), and a proof with nothing to match is not a proof"
            )
        self._audit = audit
        self._account = account
        self._expected_account_id = expected_account_id
        self._information = information
        self._clock = clock
        self._orders: dict[str, SimulatedOrder] = {}
        self._by_fingerprint: dict[str, str] = {}
        self._cash = float(account.initial_cash)
        self._timeout_armed = False
        type(self).instances_created += 1

    # -- drill controls -----------------------------------------------------

    def arm_timeout_once(self) -> None:
        """The next ``place``/``place_combo`` records the order and then raises
        :class:`SimulatedBrokerTimeout` — the §8 hazard, on demand (V6)."""
        self._timeout_armed = True

    def set_clock(self, clock: MarketClock) -> None:
        """Move the simulated session (V10, V12). Not a data source: the fill
        rule reads prices only from the information set."""
        self._clock = clock

    def set_information(self, information: PreSubmissionInformation) -> None:
        self._information = information

    # -- §13: the is_paper proof -------------------------------------------

    def is_paper(self) -> IsPaperProof:
        """Always a *paper* adapter — and the proof still fails on a mismatch.

        "Local simulator" is why this can never reach real money; it is not why
        the proof passes. The proof passes only when the account id in the
        simulated broker's own response body matches the operator-typed
        expected id, and it is re-taken every call, never cached.
        """
        observed = self._account.account_id
        host = LOCAL_HOST_SENTINEL
        reasons: list[str] = []
        if host not in PAPER_HOST_ALLOWLIST:
            reasons.append(f"observed host {host!r} is not in the reviewed paper-host allowlist")
        if not observed:
            reasons.append("the broker response body carried no account identifier")
        elif observed != self._expected_account_id:
            reasons.append(
                f"observed account id {observed!r} does not match the armed record's "
                f"expected {self._expected_account_id!r}"
            )
        proven = not reasons
        proof = IsPaperProof(
            proven=proven,
            observed_account_id=observed,
            observed_host=host,
            expected_account_id=self._expected_account_id,
            checked_at=self._clock.as_of,
            raw_excerpt=(f'{{"account_id": "{observed}", "host": "{host}", "simulated": true}}'),
            failure_reason="; ".join(reasons),
        )
        self._audit.record(
            ExecutionEventType.IS_PAPER_PROOF,
            reason=(
                "is_paper proven"
                if proven
                else f"is_paper FAILED — a mismatch blocks arming and every submission: "
                f"{proof.failure_reason}"
            ),
            payload={
                "proven": proven,
                "observed_account_id": observed,
                "observed_host": host,
                "expected_account_id": self._expected_account_id,
                "raw_excerpt": proof.raw_excerpt,
            },
        )
        return proof

    # -- read-only views ----------------------------------------------------

    def account(self) -> AccountSnapshotType:
        """Cash moves with fills; **equity never does**.

        The book is marked at cost, so profit and loss is identically zero.
        That is deliberate (§3.1 rule 4): a simulator whose fills the
        implementer controls must not be able to produce a performance number
        at all, let alone one that could satisfy decision 10's arming
        precondition.
        """
        equity = float(self._account.initial_cash)
        buying_power = (
            self._cash if self._account.buying_power is None else float(self._account.buying_power)
        )
        snapshot = AccountSnapshotType(
            account_id=self._account.account_id,
            equity=equity,
            buying_power=buying_power,
            cash=self._cash,
            as_of=self._clock.as_of,
        )
        self._audit.record(
            ExecutionEventType.ADAPTER_CALL,
            reason="account()",
            payload={
                "account_id": snapshot.account_id,
                "equity": equity,
                "cash": self._cash,
                "marked_at_cost": True,
            },
        )
        return snapshot

    def _net_positions(self) -> dict[str, PositionLeg]:
        legs: dict[str, PositionLeg] = {}
        for cid in sorted(self._orders):
            order = self._orders[cid]
            if order.filled_units <= 0:
                continue
            for leg in order.legs:
                signed = float(leg.side.sign * leg.ratio * order.filled_units)
                existing = legs.get(leg.instrument_key)
                legs[leg.instrument_key] = PositionLeg(
                    instrument_key=leg.instrument_key,
                    signed_qty=(existing.signed_qty if existing else 0.0) + signed,
                    shares_per_contract=leg.shares_per_contract,
                )
        return {k: v for k, v in legs.items() if abs(v.signed_qty) > 1e-9}

    def positions(self) -> Sequence[PositionSnapshot]:
        """The account's NET book as one snapshot, the way a broker reports it.

        Per-structure attribution is not a broker fact and is not invented
        here: it is the OMS's, reconstructed from ``execution_event``.
        """
        legs = self._net_positions()
        snapshots: tuple[PositionSnapshot, ...] = ()
        if legs:
            snapshots = (
                PositionSnapshot(
                    adapter_name=self.name,
                    legs=tuple(legs[key] for key in sorted(legs)),
                    market_value=float(self._account.initial_cash) - self._cash,
                    as_of=self._clock.as_of,
                ),
            )
        self._audit.record(
            ExecutionEventType.ADAPTER_CALL,
            reason="positions()",
            payload={
                "leg_count": len(legs),
                "legs": {key: legs[key].signed_qty for key in sorted(legs)},
            },
        )
        return snapshots

    def open_orders(self) -> Sequence[OrderStatus]:
        """Working orders only. A filled or rejected order is NOT here — which
        is exactly why ``order_status()`` exists (A4)."""
        working = tuple(
            self._orders[cid].status
            for cid in sorted(self._orders)
            if self._orders[cid].state is OrderState.SUBMITTING
        )
        self._audit.record(
            ExecutionEventType.ADAPTER_CALL,
            reason="open_orders()",
            payload={
                "open_count": len(working),
                "client_order_ids": [s.client_order_id for s in working],
            },
        )
        return working

    def order_status(self, client_order_id: str) -> OrderStatus | None:
        """Resolve ANY known order, terminal ones included (A4).

        The post-timeout procedure (§8) rests on this: ``open_orders()`` alone
        cannot tell "the broker never saw it" from "the broker filled it and it
        is no longer open".
        """
        order = self._orders.get(client_order_id)
        self._audit.record(
            ExecutionEventType.ADAPTER_CALL,
            reason=f"order_status({client_order_id})",
            client_order_id=client_order_id,
            payload={
                "known": order is not None,
                "state": order.state.value if order else "",
                "filled_units": order.filled_units if order else 0,
            },
        )
        return order.status if order else None

    def clock(self) -> MarketClock:
        self._audit.record(
            ExecutionEventType.ADAPTER_CALL,
            reason="clock()",
            payload={
                "is_open": self._clock.is_open,
                "as_of": self._clock.as_of.isoformat(),
                "is_early_close": self._clock.is_early_close,
            },
        )
        return self._clock

    # -- submission ---------------------------------------------------------

    def place(self, intent: OrderIntent) -> OrderResult:
        """A single instrument. Idempotent on ``client_order_id`` (A1)."""
        try:
            leg = OrderLeg(
                side=intent.side,
                ratio=1,
                shares_per_contract=intent.shares_per_contract,
                option_ticker=intent.option_ticker,
                symbol=intent.symbol,
            )
        except IntentRefused as exc:
            return self._reject(
                intent.client_order_id,
                legs=(),
                units=intent.qty,
                intent_kind=intent.intent_kind.value,
                structure_type=intent.structure_type.value,
                error=str(exc),
                intent=intent,
            )
        # Credit positive: a purchase is a debit, so its signed limit is negative.
        net_limit = _signed_leg_price(intent.side, intent.limit_price)
        return self._submit(
            client_order_id=intent.client_order_id,
            legs=(leg,),
            units=intent.qty,
            net_limit_price=net_limit,
            intent=intent,
        )

    def place_combo(self, intent: ComboOrderIntent) -> OrderResult:
        """ONE atomic multi-leg instruction (A2). There is no loop over legs:
        the filled size is a single scalar applied to every leg."""
        return self._submit(
            client_order_id=intent.client_order_id,
            legs=intent.legs,
            units=intent.contracts,
            net_limit_price=intent.net_limit_price,
            intent=intent,
        )

    def _submit(
        self,
        *,
        client_order_id: str,
        legs: tuple[OrderLeg, ...],
        units: int,
        net_limit_price: float,
        intent: OrderIntent | ComboOrderIntent,
    ) -> OrderResult:
        submitted_at = self._clock.as_of

        def reject(error: str) -> OrderResult:
            return self._reject(
                client_order_id,
                legs=legs,
                units=units,
                intent_kind=intent.intent_kind.value,
                structure_type=intent.structure_type.value,
                error=error,
                intent=intent,
            )

        # A1 — idempotency. The SAME id returns the SAME result, and no second
        # fill happens. This is checked before anything else, including the
        # is_paper proof, so a post-timeout retry is answered from the book.
        existing = self._orders.get(client_order_id)
        if existing is not None:
            self._audit.record(
                ExecutionEventType.ADAPTER_CALL,
                reason=(
                    "duplicate client_order_id — returning the recorded result, no second fill "
                    "(adapter eligibility condition A1)"
                ),
                client_order_id=client_order_id,
                intent_kind=existing.intent_kind,
                payload={
                    "state": existing.state.value,
                    "filled_units": existing.filled_units,
                    "broker_order_id": existing.broker_order_id,
                },
            )
            return existing.result

        fingerprint = _fingerprint(legs, units, net_limit_price, intent.source_paper_trade_id)
        prior = self._by_fingerprint.get(fingerprint)
        if prior is not None:
            return reject(
                f"an economically identical order is already on this book under "
                f"client_order_id {prior}; a fresh id is not a fresh order (D6 §5.4, A1)"
            )

        proof = self.is_paper()
        if not proof.proven:
            return reject(f"is_paper proof failed: {proof.failure_reason}")

        try:
            quotes = [
                self._information.quote(leg.instrument_key, submitted_at=submitted_at)
                for leg in legs
            ]
        except KeyError as exc:
            return reject(f"no pre-submission quote for {exc.args[0]}")
        prices = [quote.reference_price for quote in quotes]
        availability = [quote.available_qty for quote in quotes]

        net_reference = net_reference_price(legs, prices)
        spread_bps = effective_spread_bps(intent.cost_model.modelled_spread_bps)
        net_fill = degraded_limit(net_limit_price, spread_bps)

        # Marketability, in ONE expression for both directions: credit-positive
        # signing means "the book is at least as good as the limit we asked for".
        marketable = net_reference >= net_limit_price
        filled_units = 0
        if marketable:
            caps = [
                cap // leg.ratio
                for leg, cap in zip(legs, availability, strict=True)
                if cap is not None
            ]
            # ONE scalar for the whole structure. A leg with zero availability
            # drives this to zero and the structure rests unfilled; there is no
            # path that fills the other leg alone (§14).
            filled_units = min([units, *caps]) if caps else units
            filled_units = max(0, filled_units)

        leg_prices: tuple[float, ...] = tuple(0.0 for _ in legs)
        if filled_units > 0:
            if net_reference == 0.0 or (net_reference > 0) != (net_fill > 0):
                return reject(
                    f"net reference {net_reference:.4f} and the degraded net limit "
                    f"{net_fill:.4f} are not on the same side; per-leg prices cannot be "
                    "allocated from the net without inventing a price"
                )
            # Allocate the net across the legs pro-rata by their references, so
            # the per-leg prices reconstruct the net EXACTLY rather than being
            # a second, independently-degraded set that would not add up.
            scale = net_fill / net_reference
            leg_prices = tuple(price * scale for price in prices)

        if filled_units <= 0:
            state = OrderState.SUBMITTING
            raw = (
                "working: the limit is not marketable against the pre-submission reference"
                if not marketable
                else "working: marketable, but no size was available at or better than the limit"
            )
        elif filled_units < units:
            state = OrderState.PARTIAL
            raw = (
                f"partially filled {filled_units}/{units}, every leg proportional; the "
                "remainder is not left working because PARTIAL is terminal (D6 §6)"
            )
        else:
            state = OrderState.FILLED
            raw = f"filled {filled_units}/{units}"

        order = SimulatedOrder(
            client_order_id=client_order_id,
            broker_order_id=_broker_order_id(client_order_id),
            fingerprint=fingerprint,
            state=state,
            submitted_at=submitted_at,
            legs=tuple(legs),
            requested_units=units,
            filled_units=filled_units,
            leg_fill_prices=leg_prices,
            net_fill_price=net_fill if filled_units > 0 else 0.0,
            intent_kind=intent.intent_kind.value,
            structure_type=intent.structure_type.value,
            raw_status_verbatim=raw,
            source_paper_trade_id=intent.source_paper_trade_id,
            strategy_version_id=intent.strategy_version_id,
            armed_strategy_id=intent.armed_strategy_id,
            execution_limits_id=intent.execution_limits_id,
            config_hash=intent.config_hash,
            spec_json_hash=intent.spec_json_hash,
            modelled_fill_price=intent.cost_model.modelled_fill_price,
            modelled_spread_bps=intent.cost_model.modelled_spread_bps,
        )
        assert_no_naked_short_leg(order.legs, order.filled_ratios, client_order_id=client_order_id)
        self._orders[client_order_id] = order
        self._by_fingerprint[fingerprint] = client_order_id
        self._apply_cash(order)

        if self._timeout_armed:
            # The book keeps the order; the caller never hears the response.
            self._timeout_armed = False
            self._audit.record(
                ExecutionEventType.ADAPTER_CALL,
                reason=(
                    "simulated timeout: the broker recorded the order, the caller did not hear "
                    "the response — query order_status() before any resubmission (D6 §8)"
                ),
                client_order_id=client_order_id,
                intent_kind=order.intent_kind,
                payload={"state": order.state.value, "filled_units": order.filled_units},
            )
            raise SimulatedBrokerTimeout(
                f"{client_order_id}: no response was received; the order may or may not have "
                "reached the broker — it is UNKNOWN, never assumed failed (D6 §6 rule 3)"
            )

        self._record_outcome(order, intent)
        return order.result

    def _apply_cash(self, order: SimulatedOrder) -> None:
        if order.filled_units <= 0:
            return
        for leg, price in zip(order.legs, order.leg_fill_prices, strict=True):
            self._cash -= (
                leg.side.sign * leg.ratio * order.filled_units * price * leg.shares_per_contract
            )

    def _record_outcome(
        self, order: SimulatedOrder, intent: OrderIntent | ComboOrderIntent
    ) -> None:
        common: dict[str, Any] = {
            "client_order_id": order.client_order_id,
            "intent_kind": order.intent_kind,
            "state_from": OrderState.SUBMITTING.value,
            "state_to": order.state.value,
            "source_paper_trade_id": order.source_paper_trade_id,
            "strategy_version_id": order.strategy_version_id,
            "armed_strategy_id": order.armed_strategy_id,
            "execution_limits_id": order.execution_limits_id,
            "config_hash": order.config_hash,
            "spec_json_hash": order.spec_json_hash,
            "raw_status_verbatim": order.raw_status_verbatim,
        }
        if order.filled_units <= 0:
            # A working order has no terminal outcome, so it records no state
            # transition: the OMS's record stays SUBMITTING, which is what a
            # resting order IS.
            working = dict(common)
            working["state_from"] = ""
            working["state_to"] = ""
            self._audit.record(
                ExecutionEventType.ADAPTER_CALL,
                reason="order accepted and working, no fill",
                payload={"requested_units": order.requested_units},
                **working,
            )
            return
        # One FILL event per leg, carrying §4.2's realized-vs-modelled feedback.
        for index, (leg, price) in enumerate(zip(order.legs, order.leg_fill_prices, strict=True)):
            self._audit.record(
                ExecutionEventType.FILL,
                reason=(
                    f"leg {index} {leg.side.value} {leg.instrument_key} "
                    f"{leg.ratio * order.filled_units} @ {price:.6f}"
                ),
                leg_index=index,
                modelled_fill_price=intent.cost_model.modelled_fill_price,
                modelled_spread_bps=intent.cost_model.modelled_spread_bps,
                realized_fill_price=price,
                payload={
                    "filled_units": order.filled_units,
                    "requested_units": order.requested_units,
                    "filled_ratio": order.filled_ratios[index],
                    "net_fill_price": order.net_fill_price,
                    "effective_spread_bps": effective_spread_bps(
                        intent.cost_model.modelled_spread_bps
                    ),
                    "drill_artifact": True,
                },
                **common,
            )

    def _reject(
        self,
        client_order_id: str,
        *,
        legs: Sequence[OrderLeg],
        units: int,
        intent_kind: str,
        structure_type: str,
        error: str,
        intent: OrderIntent | ComboOrderIntent,
    ) -> OrderResult:
        """A rejection is recorded VERBATIM and is never retried (§20)."""
        order = SimulatedOrder(
            client_order_id=client_order_id,
            broker_order_id=_broker_order_id(client_order_id),
            fingerprint="",
            state=OrderState.REJECTED,
            submitted_at=self._clock.as_of,
            legs=tuple(legs),
            requested_units=units,
            filled_units=0,
            leg_fill_prices=tuple(0.0 for _ in legs),
            net_fill_price=0.0,
            intent_kind=intent_kind,
            structure_type=structure_type,
            raw_status_verbatim="rejected",
            error_verbatim=error,
            source_paper_trade_id=intent.source_paper_trade_id,
            strategy_version_id=intent.strategy_version_id,
            armed_strategy_id=intent.armed_strategy_id,
            execution_limits_id=intent.execution_limits_id,
            config_hash=intent.config_hash,
            spec_json_hash=intent.spec_json_hash,
        )
        self._orders[client_order_id] = order
        self._audit.record(
            ExecutionEventType.REJECTION,
            client_order_id=client_order_id,
            intent_kind=intent_kind,
            state_from=OrderState.SUBMITTING.value,
            state_to=OrderState.REJECTED.value,
            reason="broker rejection — surfaced verbatim, never retried automatically",
            source_paper_trade_id=intent.source_paper_trade_id,
            strategy_version_id=intent.strategy_version_id,
            armed_strategy_id=intent.armed_strategy_id,
            execution_limits_id=intent.execution_limits_id,
            config_hash=intent.config_hash,
            spec_json_hash=intent.spec_json_hash,
            error_verbatim=error,
        )
        return order.result

    # -- cancellation -------------------------------------------------------

    def cancel(self, client_order_id: str) -> OrderResult:
        """Cancel a working order. Terminal orders are reported as they stand.

        A cancel never invents a state: an order that already filled comes back
        FILLED with the reason in ``error_verbatim``, because telling the OMS
        that a filled order was cancelled is how a position goes missing.
        """
        order = self._orders.get(client_order_id)
        if order is None:
            self._audit.record(
                ExecutionEventType.CANCELLATION,
                client_order_id=client_order_id,
                reason="cancel refused: unknown client_order_id at this adapter",
                state_to=OrderState.REJECTED.value,
                error_verbatim="unknown client_order_id",
            )
            return OrderResult(
                client_order_id=client_order_id,
                state=OrderState.REJECTED,
                error_verbatim="unknown client_order_id at this adapter",
            )
        if order.state is not OrderState.SUBMITTING:
            self._audit.record(
                ExecutionEventType.CANCELLATION,
                client_order_id=client_order_id,
                intent_kind=order.intent_kind,
                reason=f"cancel is a no-op: the order is already {order.state.value}",
                state_from=order.state.value,
                state_to=order.state.value,
                raw_status_verbatim=order.raw_status_verbatim,
                error_verbatim=f"already terminal: {order.state.value}",
            )
            return replace(order.result, error_verbatim=f"already terminal: {order.state.value}")
        cancelled = replace(
            order,
            state=OrderState.CANCELLED,
            raw_status_verbatim="cancelled before any fill",
        )
        self._orders[client_order_id] = cancelled
        self._audit.record(
            ExecutionEventType.CANCELLATION,
            client_order_id=client_order_id,
            intent_kind=cancelled.intent_kind,
            state_from=OrderState.SUBMITTING.value,
            state_to=OrderState.CANCELLED.value,
            reason="cancelled while working, unfilled",
            source_paper_trade_id=cancelled.source_paper_trade_id,
            strategy_version_id=cancelled.strategy_version_id,
            armed_strategy_id=cancelled.armed_strategy_id,
            execution_limits_id=cancelled.execution_limits_id,
            config_hash=cancelled.config_hash,
            spec_json_hash=cancelled.spec_json_hash,
            raw_status_verbatim=cancelled.raw_status_verbatim,
        )
        return cancelled.result

    def cancel_all(self) -> Sequence[OrderResult]:
        """The kill switch's drain (§8). Deterministic order, so a drill's audit
        trail is comparable run to run."""
        working = [
            cid for cid in sorted(self._orders) if self._orders[cid].state is OrderState.SUBMITTING
        ]
        self._audit.record(
            ExecutionEventType.ADAPTER_CALL,
            reason=f"cancel_all(): {len(working)} working order(s)",
            payload={"client_order_ids": working},
        )
        return tuple(self.cancel(cid) for cid in working)

    # -- introspection for drills ------------------------------------------

    def fills_for(self, client_order_id: str) -> tuple[Fill, ...]:
        order = self._orders.get(client_order_id)
        return order.fills() if order else ()

    def book(self) -> Mapping[str, SimulatedOrder]:
        """A read-only view of every order this adapter has seen."""
        return dict(self._orders)


#: Static proof that this class satisfies the protocol. Checked by mypy at
#: import of this module, and by a test at runtime.
if TYPE_CHECKING:  # pragma: no cover - typing only
    from signalforge.execution.protocol import BrokerAdapter

    _PROTOCOL_CHECK: type[BrokerAdapter] = PaperReferenceBroker
