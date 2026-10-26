"""Single-structure options backtest engine (D2) — a **sibling** of ``engine.py``.

``backtest/engine.py`` is not generalised and not touched: it never branches on
asset class, ``EntrySignal`` has no honest value for a two-legged structure's
``direction``, ``SimTrade``'s ``entry_price`` / ``exit_price`` / ``costs_bps`` have
no meaning for a net premium, and — the strongest reason — ``spec_json_hash``
hashes every ``StrategySpec`` field, so adding one would change the hash of both
live PAPER_APPROVED strategies and un-scope their approvals.  ``tests/backtest/
test_equity_core_frozen.py`` turns "byte-identical" from a promise into a
guarantee (D2 §1.3).

What this module implements, and the section of D2 that binds each rule:

* §4  leg / structure dataclasses, with ``shares_per_contract`` read **per leg**,
  never as a module constant, and a naked short unrepresentable in the type.
* §6  entry resolved at ``t+1`` at that session's **prints** (never a mid, never
  the thin daily open); a full modelled spread per leg per side; a missing leg bar
  is a **non-entry**, never a synthetic fill.
* §9  ``R = max loss``, on two bases — ``R_incl`` (gating) and ``R_at_print``
  (reporting, fixed-denominator across spread settings).  Gate statistics run on
  the **unclamped** ``pnl_r``; the clamp is a reported label only.
* §10 exit precedence and exit *timing*: a stop or profit target is triggered on a
  close and filled at **t+1** (there is no resting stop order anywhere in this
  design — ``close_basis_stop``), while a time stop and the force close are
  calendar-knowable and fill at their own session.  Intrinsic floor on the buy
  side only; pin band; assignment recorded, not modelled.

Deterministic: pure arithmetic over the input views, no RNG, no wall-clock (S4).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from signalforge.backtest.options_costs import OptionCostModel, Side
from signalforge.backtest.options_pricing import (
    FILL_MODEL,
    IvSource,
    LegFill,
    ZeroSpreadRefused,
    adverse_fill,
    intrinsic_per_share,
)
from signalforge.data import options_calendar
from signalforge.data.option_chain import ContractRef, OptionChainSeries, Right
from signalforge.data.series import PriceSeries

PHASE1_SHARES_PER_CONTRACT = 100
PHASE1_EXERCISE_STYLE = "american"


class StructureType(StrEnum):
    VERTICAL_CREDIT = "vertical_credit"
    VERTICAL_DEBIT = "vertical_debit"
    CASH_SECURED_PUT = "cash_secured_put"
    COVERED_CALL = "covered_call"  # deferred behind O3 (decision #8)


class RBasis(StrEnum):
    """Which denominator a reported ``pnl_r`` was divided by (D2 §9.3).

    ``AT_PRINT`` is a fixed-denominator **reporting** basis computed from the
    unadjusted prints — nobody ever receives the print credit, and **no gate ever
    binds on it**.  ``INCL`` adds entry costs and is the true structural max loss;
    gates 3 and 4 bind on it, and the binding cell of the four-way (basis x spread
    setting) surface is ``INCL`` at ``spread_multiplier = 2.0``.
    """

    AT_PRINT = "at_print"
    INCL = "incl"


class DteBasis(StrEnum):
    """``dte`` is a two-headed word (D2 §11.4); a strategy must name which it used."""

    CALENDAR = "calendar"
    SESSION = "session"


class ExitReason(StrEnum):
    STOP = "stop"
    PROFIT_TARGET = "profit_target"
    TIME_STOP = "time_stop"
    FORCE_CLOSE = "force_close"


class StructureRefused(ValueError):
    """A structure the Phase-1 engine refuses to trade.

    ``counter`` names the gate-8 field the refusal increments.  A refusal that is
    not counted is a silent sample change (D2 §4.2).
    """

    def __init__(self, counter: str, detail: str) -> None:
        super().__init__(f"{counter}: {detail}")
        self.counter = counter


# ---------------------------------------------------------------------------
# Legs and structures (D2 §4)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OptionLeg:
    contract: ContractRef
    qty: int  # signed: +long / -short, per structure.  Never 0.

    @property
    def multiplier(self) -> int:
        """PER LEG, read from the stored row.  Never a module constant (D2 §4.1)."""
        return self.contract.shares_per_contract


@dataclass(frozen=True, slots=True)
class OptionStructure:
    structure_type: StructureType
    underlying_symbol: str
    legs: tuple[OptionLeg, ...]
    contracts: int  # structure count; each leg's qty is per structure

    def __post_init__(self) -> None:
        if not self.legs:
            raise StructureRefused("structure_refusals", "a structure needs at least one leg")
        if any(leg.qty == 0 for leg in self.legs):
            raise StructureRefused("structure_refusals", "a leg with qty == 0 is not a leg")
        if self.contracts < 1:
            raise StructureRefused("structure_refusals", "contracts must be >= 1")
        if len({leg.contract.underlying_symbol for leg in self.legs}) != 1:
            raise StructureRefused("structure_refusals", "Phase 1 is single-underlying")
        if len({leg.contract.expiration for leg in self.legs}) != 1:
            raise StructureRefused(
                "structure_refusals",
                "Phase 1 is single-expiration; a calendar/diagonal is a different R "
                "and a different risk model",
            )
        for leg in self.legs:
            if leg.contract.shares_per_contract != PHASE1_SHARES_PER_CONTRACT:
                raise StructureRefused(
                    "shares_per_contract_refusals",
                    f"{leg.contract.option_ticker} has "
                    f"shares_per_contract={leg.contract.shares_per_contract}",
                )
            if leg.contract.exercise_style != PHASE1_EXERCISE_STYLE:
                raise StructureRefused(
                    "exercise_style_refusals",
                    f"{leg.contract.option_ticker} is {leg.contract.exercise_style!r}",
                )
        if self.structure_type is StructureType.VERTICAL_CREDIT:
            self._validate_vertical_credit()
        elif self.structure_type is not StructureType.VERTICAL_DEBIT:
            raise StructureRefused(
                "structure_refusals",
                f"{self.structure_type.value} is not implemented in Phase 1 "
                "(decision #12: the short vertical credit spread ships first)",
            )

    def _validate_vertical_credit(self) -> None:
        if len(self.legs) != 2:
            raise StructureRefused("structure_refusals", "a vertical has exactly 2 legs")
        short, long_ = self.short_leg, self.long_leg
        if short is None or long_ is None:
            raise StructureRefused(
                "structure_refusals",
                "a defined-risk vertical needs one short and one long leg — a naked "
                "short is not representable",
            )
        if short.contract.right is not long_.contract.right:
            raise StructureRefused("structure_refusals", "both legs of a vertical share a right")
        if abs(short.qty) != abs(long_.qty):
            raise StructureRefused("structure_refusals", "a vertical's legs have equal abs(qty)")
        # The long wing must be strictly FURTHER OTM than the short — that is what
        # caps the loss at the width and makes the naked case unrepresentable.
        if short.contract.right is Right.PUT:
            beyond = long_.contract.strike < short.contract.strike
        else:
            beyond = long_.contract.strike > short.contract.strike
        if not beyond:
            raise StructureRefused(
                "structure_refusals",
                "the long wing must sit strictly beyond the short strike (further OTM)",
            )

    @property
    def short_leg(self) -> OptionLeg | None:
        shorts = [leg for leg in self.legs if leg.qty < 0]
        return shorts[0] if len(shorts) == 1 else None

    @property
    def long_leg(self) -> OptionLeg | None:
        longs = [leg for leg in self.legs if leg.qty > 0]
        return longs[0] if len(longs) == 1 else None

    @property
    def expiration(self) -> date:
        return self.legs[0].contract.expiration

    @property
    def multiplier(self) -> int:
        return self.legs[0].multiplier

    @property
    def strike_width(self) -> float:
        strikes = sorted(leg.contract.strike for leg in self.legs)
        return strikes[-1] - strikes[0]

    @property
    def contract_sides(self) -> int:
        """Contract-sides in ONE order: ``sum(abs(qty)) * contracts`` (D2 §7.2)."""
        return sum(abs(leg.qty) for leg in self.legs) * self.contracts


# ---------------------------------------------------------------------------
# Signal and trade (D2 §5, §12)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OptionsEntrySignal:
    """What a strategy emits at session ``t``.

    Deliberately **absent**: ``net_premium``, ``max_loss_dollars``, ``break_evens``
    (D2 §5.1).  At signal time no fill has occurred and the entry is priced at
    ``t+1``'s prints — a signal carrying a premium is a signal carrying a price it
    cannot know, which is the exact shape of a look-ahead bug.  The engine computes
    them at fill time and puts them on :class:`OptionTrade`.

    Every field below is a **pre-registered constant** (D5, R1) and none has a
    default.
    """

    structure: OptionStructure
    entry_session_index: int
    profit_target_pct_of_credit: float
    stop_multiple_of_credit: float
    time_stop_dte: int
    time_stop_dte_basis: DteBasis
    pin_band_pct: float
    strike_increment: float
    assignment_itm_threshold_pct: float
    iv_source: IvSource
    q_source: str
    r_source: str
    reason: str = ""


@dataclass(frozen=True, slots=True)
class OptionTrade:
    """One closed structure cycle.

    The four fields the existing metrics stack reads — ``entry_date``,
    ``exit_date``, ``pnl_r``, ``bars_held`` — are structurally compatible with
    ``SimTrade`` so ``compute_metrics`` / ``compute_portfolio_metrics`` /
    ``bootstrap_ci`` / ``_regime_census`` work unmodified (D2 §12.1).  Everything
    else is additive and invisible to them.

    ``pnl_r`` is the **unclamped** figure on ``r_basis``.  Gate statistics run on
    it; ``r_clamped`` is a label on a diagnostic, never a transformation of the
    gated data (D2 §9.4).
    """

    underlying_symbol: str
    structure_type: StructureType
    r_basis: RBasis
    entry_date: date
    exit_date: date
    bars_held: int
    pnl_r: float
    pnl_dollars: float
    r_dollars: float
    r_at_print: float
    r_incl: float
    pnl_r_at_print: float
    pnl_r_incl: float
    net_credit_at_print: float
    net_credit_received: float
    entry_costs: float
    exit_costs: float
    dte_at_entry: int
    dte_at_exit: int
    exit_reason: ExitReason
    exit_deferred_sessions: int
    unmarked_sessions: int
    r_clamped: bool
    pin_risk_flag: bool
    assignment_risk: bool
    stop_non_binding: bool
    spread_multiplier: float
    fill_model: str
    iv_source: IvSource
    q_source: str
    r_source: str
    reason: str = ""

    @property
    def pnl_r_clamped(self) -> float:
        """Supplementary REPORTED line only — never the gated series (D2 §9.4)."""
        return max(self.pnl_r, -1.0)


@dataclass(frozen=True, slots=True)
class ExcludedCycle:
    """A cycle removed from the sample, with its bias measured rather than asserted.

    D2 §10.2: the force-close eligibility rule is a **sample-construction rule
    applied with hindsight**.  It is admissible only because it is exclusionary —
    it can never add a trade — and only with the count and the excluded cycles'
    intrinsic-at-expiry distribution disclosed.  ``intrinsic_pnl_r`` is an
    intrinsic-only payoff from the underlying's expiry-session **daily close**: no
    exit costs, no early-assignment path, and not the expiry settlement print.  It
    estimates sign and order of magnitude, not a P&L, and an excluded cycle is
    never added back into any gated statistic.
    """

    underlying_symbol: str
    entry_date: date
    expiration: date
    reason: str
    intrinsic_pnl_r: float | None


@dataclass(slots=True)
class OptionsCounters:
    """Gate-8-facing counts (D2 §14.3, D4 §6.3).  Every refusal lands in one."""

    non_entry_missing_leg_bar: int = 0
    non_entry_no_signal_window: int = 0
    force_close_unpriceable_exclusions: int = 0
    force_close_beyond_data: int = 0
    shares_per_contract_refusals: int = 0
    exercise_style_refusals: int = 0
    structure_refusals: int = 0
    zero_spread_refusals: int = 0
    non_positive_r_refusals: int = 0
    spread_ge_print_leg_sides: int = 0
    sale_proceeds_floored_at_zero: int = 0
    long_leg_intrinsic_gap_dollars: float = 0.0
    leg_sides_priced: int = 0
    held_sessions: int = 0
    unmarked_sessions: int = 0
    unmarked_sessions_max_run: int = 0
    r_clamped: int = 0
    pin_risk_flag: int = 0
    assignment_risk: int = 0
    stop_non_binding: int = 0
    n_losing_trades: int = 0
    exit_deferred_sessions: list[int] = field(default_factory=list)
    # D5a §3.5 / Amendment 2 §3.3: entries a pooled evaluation refused because the
    # book already held its pre-registered maximum of concurrent structures.
    skipped_portfolio_concurrency: int = 0

    def bump(self, name: str, by: int = 1) -> None:
        setattr(self, name, getattr(self, name) + by)

    def to_dict(self) -> dict[str, object]:
        return {
            "non_entry_missing_leg_bar": self.non_entry_missing_leg_bar,
            "non_entry_no_signal_window": self.non_entry_no_signal_window,
            "force_close_unpriceable_exclusions": self.force_close_unpriceable_exclusions,
            "force_close_beyond_data": self.force_close_beyond_data,
            "shares_per_contract_refusals": self.shares_per_contract_refusals,
            "exercise_style_refusals": self.exercise_style_refusals,
            "structure_refusals": self.structure_refusals,
            "zero_spread_refusals": self.zero_spread_refusals,
            "non_positive_r_refusals": self.non_positive_r_refusals,
            "spread_ge_print_leg_sides": self.spread_ge_print_leg_sides,
            "sale_proceeds_floored_at_zero": self.sale_proceeds_floored_at_zero,
            "long_leg_intrinsic_gap_dollars": self.long_leg_intrinsic_gap_dollars,
            "leg_sides_priced": self.leg_sides_priced,
            "held_sessions": self.held_sessions,
            "unmarked_sessions": self.unmarked_sessions,
            "unmarked_sessions_max_run": self.unmarked_sessions_max_run,
            "unmarked_session_fraction": (
                self.unmarked_sessions / self.held_sessions if self.held_sessions else 0.0
            ),
            "r_clamped": self.r_clamped,
            "pin_risk_flag": self.pin_risk_flag,
            "assignment_risk": self.assignment_risk,
            "stop_non_binding": self.stop_non_binding,
            "n_losing_trades": self.n_losing_trades,
            "exit_deferred_sessions": list(self.exit_deferred_sessions),
        }


@dataclass(slots=True)
class OptionsBacktestOutcome:
    underlying_symbol: str
    r_basis: RBasis
    spread_multiplier: float
    trades: list[OptionTrade] = field(default_factory=list)
    excluded: list[ExcludedCycle] = field(default_factory=list)
    counters: OptionsCounters = field(default_factory=OptionsCounters)
    sessions: int = 0
    first_date: date | None = None
    last_date: date | None = None


OptionsSignalFn = Callable[[OptionChainSeries, PriceSeries, int], "OptionsEntrySignal | None"]


# ---------------------------------------------------------------------------
# Pricing helpers
# ---------------------------------------------------------------------------


def _all_legs_print(chain: OptionChainSeries, t: int, structure: OptionStructure) -> bool:
    return all(chain.print_at(t, leg.contract.option_ticker) is not None for leg in structure.legs)


def _premium_at_print(chain: OptionChainSeries, t: int, structure: OptionStructure) -> float | None:
    """The structure's net credit from unadjusted prints, in dollars.

    Positive for a credit structure: the cost to close it.  ``None`` when any leg
    did not print — absence is the answer, never a default (D2 §6.4).
    """
    total = 0.0
    for leg in structure.legs:
        pr = chain.print_at(t, leg.contract.option_ticker)
        if pr is None:
            return None
        total += leg.qty * pr.last_print * leg.multiplier
    return -total * structure.contracts


def _dte(as_of: date, expiry: date, basis: DteBasis) -> int:
    if basis is DteBasis.CALENDAR:
        return options_calendar.calendar_dte(as_of, expiry)
    return options_calendar.session_dte(as_of, expiry)


@dataclass(frozen=True, slots=True)
class _StructureFills:
    fills: dict[str, LegFill]
    cash: float  # signed cash flow of the transaction, in dollars
    spread_cost: float
    commission: float
    fees: float

    @property
    def transaction_costs(self) -> float:
        return self.spread_cost + self.commission + self.fees


def _fill_structure(
    chain: OptionChainSeries,
    t: int,
    structure: OptionStructure,
    cost_model: OptionCostModel,
    counters: OptionsCounters,
    *,
    opening: bool,
    apply_intrinsic_floor: bool,
) -> _StructureFills:
    """Fill every leg of the structure at session ``t``'s prints, adversely.

    ``opening`` acquires ``qty`` contracts per leg; closing transacts ``-qty``.
    A full modelled spread is charged **per leg per side** (D2 §6.2), so a 2-leg
    vertical pays four of them round trip.
    """
    session = chain.sessions[t]
    underlying_close = session.underlying_close
    fills: dict[str, LegFill] = {}
    cash = 0.0
    spread_cost = 0.0
    for leg in sorted(structure.legs, key=lambda leg: leg.contract.option_ticker):
        pr = chain.print_at(t, leg.contract.option_ticker)
        if pr is None:  # pragma: no cover - callers check printability first
            raise ValueError("a leg without a print can never be filled")
        signed_qty = leg.qty if opening else -leg.qty
        side = Side.BUY if signed_qty > 0 else Side.SELL
        fill = adverse_fill(
            pr,
            cost_model,
            side=side,
            strike=leg.contract.strike,
            right=leg.contract.right,
            underlying_close=underlying_close,
            dte=options_calendar.calendar_dte(session.session_date, leg.contract.expiration),
            apply_intrinsic_floor=apply_intrinsic_floor and side is Side.BUY,
        )
        fills[leg.contract.option_ticker] = fill
        units = abs(signed_qty) * leg.multiplier * structure.contracts
        cash += -signed_qty * fill.price * leg.multiplier * structure.contracts
        spread_cost += abs(fill.price - pr.last_print) * units
        counters.bump("leg_sides_priced")
        if fill.spread_ge_print:
            counters.bump("spread_ge_print_leg_sides")
        if fill.proceeds_floored_at_zero:
            counters.bump("sale_proceeds_floored_at_zero")
        if side is Side.SELL and leg.qty > 0:
            counters.long_leg_intrinsic_gap_dollars += fill.intrinsic_gap * units
    sides = structure.contract_sides
    return _StructureFills(
        fills=fills,
        cash=cash,
        spread_cost=spread_cost,
        commission=cost_model.commission(sides),
        fees=cost_model.fees(sides),
    )


def _intrinsic_pnl_dollars(
    structure: OptionStructure, underlying_close: float, net_credit_at_print: float
) -> float:
    """Intrinsic-at-expiry P&L of a cycle, from the underlying alone (D2 §10.2)."""
    value = 0.0
    for leg in structure.legs:
        value += (
            leg.qty
            * intrinsic_per_share(underlying_close, leg.contract.strike, leg.contract.right)
            * leg.multiplier
        )
    return net_credit_at_print + value * structure.contracts


# ---------------------------------------------------------------------------
# The simulator
# ---------------------------------------------------------------------------


def simulate_structure(
    chain: OptionChainSeries,
    signal: OptionsEntrySignal,
    *,
    cost_model: OptionCostModel,
    r_basis: RBasis,
    counters: OptionsCounters,
) -> tuple[OptionTrade | None, ExcludedCycle | None, int]:
    """Simulate one structure cycle.  Returns ``(trade, excluded, exit_index)``.

    ``exit_index`` is the session index the engine is flat again after; it is the
    entry index when nothing was entered, so the caller always advances.
    """
    structure = signal.structure
    t = signal.entry_session_index
    entry_idx = t + 1
    if entry_idx >= len(chain):
        counters.bump("non_entry_no_signal_window")
        return None, None, t

    # --- entry: t+1's prints, or a NON-ENTRY.  Never a synthetic fill. --------
    if not _all_legs_print(chain, entry_idx, structure):
        counters.bump("non_entry_missing_leg_bar")
        return None, None, entry_idx

    net_credit_at_print = _premium_at_print(chain, entry_idx, structure)
    assert net_credit_at_print is not None  # printability just checked
    entry = _fill_structure(
        chain,
        entry_idx,
        structure,
        cost_model,
        counters,
        opening=True,
        apply_intrinsic_floor=False,
    )
    net_credit_received = entry.cash
    entry_costs = entry.transaction_costs

    r_at_print = structure.strike_width * structure.multiplier * structure.contracts
    r_at_print -= net_credit_at_print
    r_incl = r_at_print + entry_costs
    if r_at_print <= 0.0 or r_incl <= 0.0:
        counters.bump("non_positive_r_refusals")
        return None, None, entry_idx

    entry_session = chain.sessions[entry_idx]
    expiry = structure.expiration

    # --- force-close eligibility (D2 §10.2) ---------------------------------
    # A post-hoc SAMPLE filter applied by the engine, never a condition the
    # strategy's evaluate() can see: evaluate() is handed chain.head(t), which
    # cannot answer a question about the expiry-1 session when t precedes it.
    try:
        fc_date = options_calendar.force_close_session(expiry)
    except options_calendar.CalendarUnresolved:
        counters.bump("force_close_beyond_data")
        return None, None, entry_idx
    fc_idx = chain.index_of(fc_date)
    if fc_idx is None or fc_idx <= entry_idx:
        counters.bump("force_close_beyond_data")
        return None, None, entry_idx
    if not _all_legs_print(chain, fc_idx, structure):
        counters.bump("force_close_unpriceable_exclusions")
        expiry_idx = chain.index_of(options_calendar.last_trade_session(expiry))
        intrinsic_r: float | None = None
        if expiry_idx is not None:
            denom = r_incl if r_basis is RBasis.INCL else r_at_print
            intrinsic_r = (
                _intrinsic_pnl_dollars(
                    structure, chain.sessions[expiry_idx].underlying_close, net_credit_at_print
                )
                / denom
            )
        return (
            None,
            ExcludedCycle(
                underlying_symbol=structure.underlying_symbol,
                entry_date=entry_session.session_date,
                expiration=expiry,
                reason="force_close_unpriceable",
                intrinsic_pnl_r=intrinsic_r,
            ),
            entry_idx,
        )

    # --- exit resolution (D2 §10.1) -----------------------------------------
    # The two levels are struck against the credit ACTUALLY RECEIVED (spread- and
    # tick-adjusted), because that is the number a trader who says "stop at 2x the
    # credit" is multiplying.  They are then compared against the net premium from
    # UNADJUSTED prints, per D2 §6.4's Mark firewall: a trigger may only ever read
    # prints, never a modelled mark.  The two bases are named here rather than left
    # to a reader, because the asymmetry cuts both ways and neither direction is
    # free: a received credit is smaller than the print credit, which strikes the
    # stop nearer and fires it sooner, while the print premium is cheaper than the
    # cost to actually buy the structure back, which delays the same stop.  Moving
    # either basis is a modelling change that belongs to D5 pre-registration, not
    # to the engine.
    stop_level = signal.stop_multiple_of_credit * net_credit_received
    target_level = (1.0 - signal.profit_target_pct_of_credit) * net_credit_received
    trigger: ExitReason | None = None
    earliest_fill = entry_idx
    exit_idx: int | None = None
    unmarked = 0
    unmarked_run = 0
    unmarked_run_max = 0
    assignment_risk = False
    short_leg = structure.short_leg

    for u in range(entry_idx, fc_idx + 1):
        priced = _all_legs_print(chain, u, structure)
        if u > entry_idx:
            counters.bump("held_sessions")
            if not priced:
                unmarked += 1
                unmarked_run += 1
                unmarked_run_max = max(unmarked_run_max, unmarked_run)
            else:
                unmarked_run = 0
        session_date = chain.sessions[u].session_date
        underlying_close = chain.sessions[u].underlying_close
        if short_leg is not None and u < fc_idx:
            itm = intrinsic_per_share(
                underlying_close, short_leg.contract.strike, short_leg.contract.right
            )
            if (
                underlying_close > 0.0
                and itm / underlying_close > signal.assignment_itm_threshold_pct
            ):
                assignment_risk = True

        if trigger is None:
            if u == fc_idx:
                trigger, earliest_fill = ExitReason.FORCE_CLOSE, u
            else:
                premium = _premium_at_print(chain, u, structure) if priced else None
                if premium is not None and premium >= stop_level:
                    # close-basis stop: OBSERVED at u's close, actionable at u+1
                    trigger, earliest_fill = ExitReason.STOP, u + 1
                elif premium is not None and premium <= target_level:
                    trigger, earliest_fill = ExitReason.PROFIT_TARGET, u + 1
                elif _dte(session_date, expiry, signal.time_stop_dte_basis) <= signal.time_stop_dte:
                    # calendar-knowable before the session opens: MOC-style, same session
                    trigger, earliest_fill = ExitReason.TIME_STOP, u
        if trigger is not None and u >= earliest_fill and priced:
            exit_idx = u
            break

    if exit_idx is None or trigger is None:  # pragma: no cover - fc_idx always prices
        exit_idx, trigger = fc_idx, ExitReason.FORCE_CLOSE
    deferred = max(0, exit_idx - earliest_fill)
    counters.exit_deferred_sessions.append(deferred)
    counters.bump("unmarked_sessions", unmarked)
    counters.unmarked_sessions_max_run = max(counters.unmarked_sessions_max_run, unmarked_run_max)

    exit_fills = _fill_structure(
        chain,
        exit_idx,
        structure,
        cost_model,
        counters,
        opening=False,
        apply_intrinsic_floor=True,
    )
    exit_costs = exit_fills.transaction_costs
    gross = net_credit_received + exit_fills.cash
    pnl_dollars = gross - entry.commission - entry.fees - exit_fills.commission - exit_fills.fees

    exit_session = chain.sessions[exit_idx]
    pnl_r_incl = pnl_dollars / r_incl
    pnl_r_at_print = pnl_dollars / r_at_print
    pnl_r = pnl_r_incl if r_basis is RBasis.INCL else pnl_r_at_print

    pin = False
    if short_leg is not None:
        band = min(signal.pin_band_pct * exit_session.underlying_close, signal.strike_increment)
        pin = abs(exit_session.underlying_close - short_leg.contract.strike) <= band

    closing_premium = _premium_at_print(chain, exit_idx, structure)
    stop_non_binding = closing_premium is not None and closing_premium > stop_level
    clamped = pnl_r < -1.0

    counters.bump("r_clamped", int(clamped))
    counters.bump("pin_risk_flag", int(pin))
    counters.bump("assignment_risk", int(assignment_risk))
    counters.bump("stop_non_binding", int(stop_non_binding))
    counters.bump("n_losing_trades", int(pnl_dollars < 0.0))

    trade = OptionTrade(
        underlying_symbol=structure.underlying_symbol,
        structure_type=structure.structure_type,
        r_basis=r_basis,
        entry_date=entry_session.session_date,
        exit_date=exit_session.session_date,
        bars_held=exit_idx - entry_idx,
        pnl_r=pnl_r,
        pnl_dollars=pnl_dollars,
        r_dollars=r_incl if r_basis is RBasis.INCL else r_at_print,
        r_at_print=r_at_print,
        r_incl=r_incl,
        pnl_r_at_print=pnl_r_at_print,
        pnl_r_incl=pnl_r_incl,
        net_credit_at_print=net_credit_at_print,
        net_credit_received=net_credit_received,
        entry_costs=entry_costs,
        exit_costs=exit_costs,
        dte_at_entry=_dte(entry_session.session_date, expiry, signal.time_stop_dte_basis),
        dte_at_exit=_dte(exit_session.session_date, expiry, signal.time_stop_dte_basis),
        exit_reason=trigger,
        exit_deferred_sessions=deferred,
        unmarked_sessions=unmarked,
        r_clamped=clamped,
        pin_risk_flag=pin,
        assignment_risk=assignment_risk,
        stop_non_binding=stop_non_binding,
        spread_multiplier=cost_model.spread_multiplier,
        fill_model=FILL_MODEL,
        iv_source=signal.iv_source,
        q_source=signal.q_source,
        r_source=signal.r_source,
        reason=signal.reason,
    )
    return trade, None, exit_idx


def run_options_backtest(
    chain: OptionChainSeries,
    underlying: PriceSeries,
    signal_fn: OptionsSignalFn,
    *,
    cost_model: OptionCostModel,
    r_basis: RBasis = RBasis.INCL,
    warmup: int = 50,
) -> OptionsBacktestOutcome:
    """Loop the chain, one structure at a time, flat between cycles.

    Mirrors ``run_backtest``: the strategy is *handed* ``chain.head(t)`` and
    ``underlying.head(t)`` and cannot opt out of the truncation, and the engine
    goes flat before re-entering (``t = exit_idx + 1``) so there are no overlapping
    positions per underlying (D2 §12.4).
    """
    if len(chain) != len(underlying):
        raise ValueError(
            "chain and underlying must be indexed by the same session list "
            f"({len(chain)} vs {len(underlying)}); see D2 §3.5"
        )
    outcome = OptionsBacktestOutcome(
        underlying_symbol=chain.underlying,
        r_basis=r_basis,
        spread_multiplier=cost_model.spread_multiplier,
        sessions=len(chain),
    )
    if len(chain):
        outcome.first_date = chain.sessions[0].session_date
        outcome.last_date = chain.sessions[-1].session_date

    n = len(chain)
    t = max(warmup, 0)
    while t < n - 1:
        try:
            signal = signal_fn(chain.head(t), underlying.head(t), t)
        except StructureRefused as exc:
            outcome.counters.bump(exc.counter)
            t += 1
            continue
        if signal is None:
            t += 1
            continue
        if signal.entry_session_index != t:
            raise ValueError(
                f"signal.entry_session_index={signal.entry_session_index} must equal t={t}"
            )
        try:
            trade, excluded, exit_idx = simulate_structure(
                chain,
                signal,
                cost_model=cost_model,
                r_basis=r_basis,
                counters=outcome.counters,
            )
        except ZeroSpreadRefused:
            outcome.counters.bump("zero_spread_refusals")
            t += 1
            continue
        if trade is not None:
            outcome.trades.append(trade)
        if excluded is not None:
            outcome.excluded.append(excluded)
        t = exit_idx + 1

    return outcome
