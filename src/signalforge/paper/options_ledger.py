"""Options paper ledger (D3, track I-O6) — a **sibling** of ``paper/ledger.py``.

``paper/ledger.py`` is not generalised and not extended. Three reasons, in
ascending order of how much they bind:

1. Its fill model is ``_NOMINAL_SPREAD_BPS = 5.0`` applied per share. A
   per-share basis-point spread applied to an option premium is not an
   approximation, it is a category error.
2. Its mark prices a position from the **underlying's** daily bars and tests
   stop/target against the underlying's high/low. A structure's exits are
   struck against its own net premium.
3. The equity path is live (paper probation, auto-simulation ON since
   2026-09-10). Sharing code with it is sharing a blast radius. Everything here
   is new, and ``paper/ledger.py`` gains exactly two *narrowing* refusals and
   one type assertion — nothing that can change an equity verdict.

Everything in this module is SIMULATED. No broker is contacted, no order is
placed, and no LLM is anywhere near a decision (import-linter S11/S13/S14/S15c).

Account targeting (D3 §2): every function takes ``account_name`` as a **required
keyword with no default**. A required keyword stops a *forgotten* account name;
it does nothing about a *wrong* one, and ``"default"`` is a perfectly valid
string that resolves to the live equity account. So the name also comes from
configuration (``OptionsRiskLimits.paper_account_name``) and
:func:`resolve_options_account` refuses any account that is not the configured
one, and refuses the account named ``'default'`` outright.

Cash and collateral (D3 §8.0, corrected): the **gross** requirement is reserved
and the credit lands in cash, so ``spendable_cash`` falls by exactly the
structure's maximum loss ``R``. D3 §3.2's literal formula
(``width x M x contracts - net_credit + entry_costs``) subtracts the credit from
the reservation *and* adds it to cash, which double-counts it and under-reserves;
§8.0's stated invariant — "spendable_cash falls by exactly R" — is the one
implemented here, and every reservation records its formula inputs in
``basis_json`` so the reconciler can re-evaluate it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge.backtest.options_costs import OptionCostModel, Side
from signalforge.backtest.options_pricing import FILL_MODEL, IvSource, LegFill, adverse_fill
from signalforge.config.research import OptionsRiskLimits, OptionsStructureLimits
from signalforge.data.option_chain import ContractPrint, Right
from signalforge.db.models import (
    Candidate,
    CandidateOptionStructure,
    Instrument,
    OptionAggregateDaily,
    OptionContract,
    OptionsCollateralEntry,
    OptionsPosition,
    OptionsPositionLeg,
    OptionsReconcileReport,
    OptionsTrade,
    PaperAccount,
)
from signalforge.db.types import utcnow
from signalforge.domain import Direction, PaperDecision, QualityGate
from signalforge.killswitch import ensure_not_engaged
from signalforge.observability import get_logger
from signalforge.options import blackscholes
from signalforge.settings_store import effective_research_config, get_setting

__all__ = [
    "OPTIONS_AUTO_SIM_CAP_KEY",
    "OPTIONS_AUTO_SIM_ENABLED_KEY",
    "OPTIONS_STRUCTURE_KIND",
    "AcceptOptionsResult",
    "LegQuote",
    "OptionExpiryUnhandled",
    "OptionsAutoSimulateForbidden",
    "OptionsPricingContext",
    "PriceSourceUnresolved",
    "StructureSpec",
    "accept_options_candidate",
    "assert_options_auto_simulate_allowed",
    "collateral_basis",
    "evaluate_options_limits",
    "leg_quote",
    "options_auto_simulate_enabled",
    "options_auto_simulate_max_per_day",
    "record_options_decision",
    "reserve_collateral",
    "release_collateral",
    "resolve_options_account",
    "structure_greeks",
]

_log = get_logger("paper.options_ledger")
_CENTS = Decimal("0.000001")

#: ``Candidate.structure_kind`` for a multi-leg options candidate. 13 characters,
#: deliberately inside ``String(16)`` rather than exactly on it (D3 §1.2).
OPTIONS_STRUCTURE_KIND = "option_spread"

#: NEW settings, SEPARATE from the equity pair (``auto_simulate_qualified_signals``
#: is currently ON with a cap of 2/day). Both default OFF/0: a fresh install and
#: the live database alike have options auto-simulation off, and turning it on is
#: a deliberate, audited operator action. Nothing is armed by default.
OPTIONS_AUTO_SIM_ENABLED_KEY = "auto_simulate_options_enabled"
OPTIONS_AUTO_SIM_CAP_KEY = "auto_simulate_options_max_per_day"

_EQUITY_ACCOUNT_NAME = "default"
_PHASE1_SHARES_PER_CONTRACT = 100
_PHASE1_EXERCISE_STYLE = "american"
_PHASE1_STRUCTURE_TYPES = frozenset({"vertical_credit", "vertical_debit"})

NOTICE = "SIMULATED options structure — no order was placed."
DISCLOSURES: tuple[str, ...] = (
    "NBBO unavailable under the active entitlement for options AND equities — "
    "spread is modelled, not observed.",
    "Force-close at expiry-1 approximates away early assignment; the bias is "
    "IN THE STRATEGY'S FAVOUR.",
    "Dividend-driven early assignment on short calls is not modelled in Phase 1.",
    "Exercise style is american; Phase 1 closes before expiry rather than modelling "
    "an assignment process.",
)


class OptionsAutoSimulateForbidden(RuntimeError):
    """An options paper acceptance was requested for a structure that is not
    eligible.

    A **distinct type** from ``paper.ledger.AutoSimulateForbidden``, deliberately:
    no existing ``except AutoSimulateForbidden`` handler anywhere in the tree can
    swallow an options refusal.
    """

    def __init__(self, condition: str, detail: str) -> None:
        super().__init__(f"{condition}: {detail}")
        self.condition = condition
        self.detail = detail


class OptionExpiryUnhandled(RuntimeError):
    """A structure reached a state Phase 1 has no modelled answer for.

    Raised rather than guessed. Phase 1 force-closes at ``expiry - 1``; an open
    structure found past its last trade session with no settlement basis is an
    unhandled state, and inventing a settlement price for it would be inventing
    a P&L.
    """


class PriceSourceUnresolved(ValueError):
    """A price read was asked for without ONE named source, or against the wrong one.

    ``option_aggregate_daily`` and ``ohlcv_daily`` both hold rows for the same
    ticker and session under more than one ``source`` label (``massive`` /
    ``massive_grouped`` for bars, ``massive_options`` for prints, fixtures in
    tests). Reading by ticker + date alone and letting the highest id win is a
    guess about which vendor's print is the mark. This is raised instead, and the
    caller REFUSES the mark (``paper.options_mark_refused``) or the entry
    (condition AC) rather than pick a row.
    """


def _money(x: float | Decimal) -> Decimal:
    return Decimal(str(x)).quantize(_CENTS, rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------- #
# Account targeting (D3 §2, §10.2 condition N)
# --------------------------------------------------------------------------- #


def resolve_options_account(session: Session, *, account_name: str) -> PaperAccount:
    """The options paper account, or a refusal naming condition N.

    Three checks, and the second and third are what make this not a tautology
    (rev 1 of D3 resolved the account *by* the caller's string and then verified
    the resolved account carried that string):

    * the account exists;
    * its name equals ``OptionsRiskLimits.paper_account_name`` — the value in
      **configuration**, not the caller's argument;
    * its id is not the id of the account named ``'default'``, so the live equity
      book can never be the target even if the configured name is later edited to
      point at it.
    """
    configured = effective_research_config(session).options_risk.paper_account_name
    acct = session.scalar(select(PaperAccount).where(PaperAccount.name == account_name))
    if acct is None:
        raise OptionsAutoSimulateForbidden(
            "N",
            f"paper account {account_name!r} does not exist — run "
            f"`signalforge paper init --name {configured} --cash 25000`",
        )
    if acct.name != configured:
        raise OptionsAutoSimulateForbidden(
            "N",
            f"account {acct.name!r} is not the configured options account {configured!r}",
        )
    equity_id = session.scalar(
        select(PaperAccount.id).where(PaperAccount.name == _EQUITY_ACCOUNT_NAME)
    )
    if equity_id is not None and acct.id == equity_id:
        raise OptionsAutoSimulateForbidden(
            "N",
            "the options account resolves to the EQUITY account "
            f"(id {equity_id}) — refusing to write options collateral against it",
        )
    return acct


def options_auto_simulate_enabled(session: Session) -> bool:
    """The SECOND setting. Never ``auto_simulate_qualified_signals``."""
    return get_setting(session, OPTIONS_AUTO_SIM_ENABLED_KEY, False) is True


def options_auto_simulate_max_per_day(session: Session) -> int:
    """The SECOND daily cap, default 0 — separate from the equity cap of 2."""
    raw = get_setting(session, OPTIONS_AUTO_SIM_CAP_KEY, 0)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


# --------------------------------------------------------------------------- #
# Structures, quotes, greeks
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class LegSpec:
    """One leg as proposed or stored. ``shares_per_contract`` is READ, never
    defaulted here — the ``x 100`` arithmetic downstream must be auditable."""

    option_ticker: str
    right: str  # "call" | "put"
    strike: float
    expiration: date
    qty_signed: int  # + long / - short, per structure
    shares_per_contract: int
    exercise_style: str
    option_contract_id: int | None = None

    @property
    def right_enum(self) -> Right:
        return Right.CALL if self.right.lower().startswith("c") else Right.PUT


@dataclass(frozen=True, slots=True)
class StructureSpec:
    """A multi-leg structure, independent of whether it is proposed or open."""

    structure_type: str
    underlying_symbol: str
    contracts: int
    legs: tuple[LegSpec, ...]
    #: Price-source provenance (PR #14 review). Both are REQUIRED, with no
    #: default: ``option_source`` names the ``option_aggregate_daily.source`` the
    #: legs' prints are read under and ``underlying_source`` the
    #: ``ohlcv_daily.source`` the spot is read under. An empty label is a read
    #: that cannot name its source, and every read refuses it.
    option_source: str
    underlying_source: str

    @property
    def expiration(self) -> date:
        return self.legs[0].expiration

    @property
    def multiplier(self) -> int:
        return self.legs[0].shares_per_contract

    @property
    def strike_width(self) -> float:
        strikes = sorted(leg.strike for leg in self.legs)
        return strikes[-1] - strikes[0]

    @property
    def short_leg(self) -> LegSpec | None:
        shorts = [leg for leg in self.legs if leg.qty_signed < 0]
        return shorts[0] if len(shorts) == 1 else None

    @property
    def contract_sides(self) -> int:
        return sum(abs(leg.qty_signed) for leg in self.legs) * self.contracts


def structure_from_candidate(
    row: CandidateOptionStructure, *, option_source: str, underlying_source: str
) -> StructureSpec:
    """The proposed structure, carrying the sources its prices MUST be read from.

    Both labels are the caller's to resolve — the guard reads them from the scan
    (``scan_run.source``) and the scan's DataSnapshot
    (``resolve_option_data_source``) — and are passed through untouched, empty
    included: an empty label refuses at the first read, by name, rather than here
    where the refusal could not say which condition it is.
    """
    return StructureSpec(
        structure_type=row.structure_type,
        underlying_symbol=row.underlying_symbol,
        contracts=row.contracts,
        option_source=option_source,
        underlying_source=underlying_source,
        legs=tuple(
            LegSpec(
                option_ticker=str(leg["option_ticker"]),
                right=str(leg["right"]),
                strike=float(leg["strike"]),
                expiration=date.fromisoformat(str(leg["expiration"])),
                qty_signed=int(leg["qty_signed"]),
                shares_per_contract=int(leg["shares_per_contract"]),
                exercise_style=str(leg.get("exercise_style", "")),
                option_contract_id=leg.get("option_contract_id"),
            )
            for leg in row.legs_json
        ),
    )


def structure_from_position(position: OptionsPosition) -> StructureSpec:
    """The open structure, with the sources RECORDED on the row at entry.

    A position opened before the provenance columns existed carries ``""`` for
    both, and the marks refuse it (``paper.options_mark_refused``) rather than
    read whichever vendor's row happens to have the highest id.
    """
    return StructureSpec(
        structure_type=position.structure_type,
        underlying_symbol=position.underlying_symbol,
        contracts=position.contracts,
        option_source=str(position.option_source or "").strip(),
        underlying_source=str(position.underlying_source or "").strip(),
        legs=tuple(
            LegSpec(
                option_ticker=leg.option_ticker,
                right=leg.right,
                strike=leg.strike,
                expiration=leg.expiration_date,
                qty_signed=leg.qty_signed,
                shares_per_contract=leg.shares_per_contract,
                exercise_style=leg.exercise_style,
                option_contract_id=leg.option_contract_id,
            )
            for leg in sorted(position.legs, key=lambda x: x.option_ticker)
        ),
    )


@dataclass(frozen=True, slots=True)
class OptionsPricingContext:
    """Everything a fill or a mark needs, none of it defaulted into existence.

    ``cost_model`` has no defaults by construction (D2 §7.4: a zero-cost model
    makes gate 4b pass vacuously, because ``2 x 0 == 0``). ``dividend_yield`` is
    required for the same reason decision 11 requires ``q`` to be sourced and
    recorded per underlying: a silent ``q = 0`` is an assumption nobody chose.
    """

    cost_model: OptionCostModel
    risk_free_rate: float
    dividend_yield: float
    q_source: str
    #: The ``ohlcv_daily.source`` the spot in this context was read from, and the
    #: ONLY source any greek computed under it may take its spot from. Required,
    #: no default: a quote whose structure records a different underlying source
    #: is refused (:class:`PriceSourceUnresolved`), never priced off this spot.
    underlying_source: str
    iv_source: str = IvSource.LOCAL_BS_INVERTED.value
    greeks_source: str = "local_bs_inversion"
    #: Phase 1 records unit beta rather than inventing one. D3 §5.2 wants the SPY
    #: proxy series ``backtest/regime.py`` already uses; until that is wired the
    #: assumption is on the row, not in a comment.
    beta_to_spy: float = 1.0


@dataclass(frozen=True, slots=True)
class LegQuote:
    """One leg's session state: its print (or its absence) and its local greeks."""

    option_ticker: str
    print_close: float | None
    underlying_close: float | None
    implied_vol: float | None
    delta: float | None
    vega_per_vol_pt: float | None

    @property
    def priced(self) -> bool:
        return self.print_close is not None


def _require_source(kind: str, source: str, *, what: str) -> str:
    """One named, non-empty source label, or a refusal that says which read lacked it."""
    label = str(source or "").strip()
    if not label:
        raise PriceSourceUnresolved(
            f"{what}: no {kind} source is recorded, so the read cannot name the source it "
            "takes its price from; it is never defaulted and the highest id never wins"
        )
    return label


def _underlying_close(session: Session, symbol: str, on: date, *, source: str) -> float | None:
    """The underlying's last close on or before ``on`` from ONE named ``ohlcv_daily.source``.

    ``source`` is required. The live database holds the same symbol's bars under
    more than one label (``massive`` and ``massive_grouped``), so an unfiltered
    read returns whichever label's row sorts last — a guess. ``None`` means that
    source has no bar in the window, which is a fact, not a cue to try another.
    """
    from signalforge.data.repository import get_daily_bars

    label = _require_source("underlying-bar", source, what=f"{symbol} close on {on}")
    bars = get_daily_bars(session, symbol, on - timedelta(days=10), on, source=label)
    return float(bars[-1].close) if bars else None


def _option_print(session: Session, option_ticker: str, on: date, *, source: str) -> float | None:
    """``OptionAggregateDaily.close`` for that contract on that session from ONE named source.

    ``source`` is required and matched exactly: ``(option_ticker, session_date,
    source)`` is unique, so there is at most one row and nothing to order by. The
    PR #14 review found this read selecting by ticker + date alone with the
    highest id winning, which under two vendors' rows is a coin toss for the mark.

    ``None`` is a FIRST-CLASS liquidity fact (D2 §3): it is never coerced to
    0.0, to the previous session's close, to a model price, or to another
    source's print.
    """
    label = _require_source("option-data", source, what=f"{option_ticker} print on {on}")
    row = session.scalar(
        select(OptionAggregateDaily)
        .where(
            OptionAggregateDaily.option_ticker == option_ticker,
            OptionAggregateDaily.session_date == on,
            OptionAggregateDaily.source == label,
        )
        .limit(1)
    )
    return float(row.close) if row is not None else None


def leg_quote(
    session: Session,
    leg: LegSpec,
    *,
    underlying_symbol: str,
    as_of: date,
    pricing: OptionsPricingContext,
    option_source: str,
    underlying_source: str,
) -> LegQuote:
    """The leg's print and its LOCALLY INVERTED greeks (never vendor greeks).

    Greeks come from a Black-Scholes inversion of the leg's own print. When the
    leg did not print, or the inversion has no solution, every greek is ``None``
    and the caller records ``iv_unavailable`` — realised volatility is **never** a
    fallback (map §2.4b: it values short premium below its worth and manufactures
    the very edge the strategy claims).

    Both sources are REQUIRED. The print is read from ``option_source`` and the
    spot from ``underlying_source`` — the labels recorded on the structure — and
    ``underlying_source`` must be the one ``pricing``'s own spot was taken from,
    or the greeks would mix two vendors' closes. Either absent or mismatched
    raises :class:`PriceSourceUnresolved`; nothing is read.
    """
    opt_src = _require_source("option-data", option_source, what=leg.option_ticker)
    und_src = _require_source("underlying-bar", underlying_source, what=underlying_symbol)
    if pricing.underlying_source != und_src:
        raise PriceSourceUnresolved(
            f"{leg.option_ticker}: the structure records underlying source {und_src!r} but the "
            f"pricing context's spot was read from {pricing.underlying_source!r}; a greek is "
            "never computed off one vendor's spot for a structure recorded against another's"
        )
    px = _option_print(session, leg.option_ticker, as_of, source=opt_src)
    spot = _underlying_close(session, underlying_symbol, as_of, source=und_src)
    if px is None or spot is None or spot <= 0.0:
        return LegQuote(leg.option_ticker, px, spot, None, None, None)
    t_years = max((leg.expiration - as_of).days, 0) / 365.0
    if t_years <= 0.0:
        return LegQuote(leg.option_ticker, px, spot, None, None, None)
    call = leg.right_enum is Right.CALL
    iv = blackscholes.implied_vol(
        px,
        spot,
        leg.strike,
        t_years,
        pricing.risk_free_rate,
        call=call,
        q=pricing.dividend_yield,
    )
    if iv is None or iv <= 0.0:
        return LegQuote(leg.option_ticker, px, spot, None, None, None)
    g = blackscholes.greeks(
        spot,
        leg.strike,
        t_years,
        pricing.risk_free_rate,
        iv,
        call=call,
        q=pricing.dividend_yield,
    )
    return LegQuote(leg.option_ticker, px, spot, iv, g.delta, g.vega_per_vol_point)


@dataclass(frozen=True, slots=True)
class StructureGreeks:
    net_delta_shares: float
    net_delta_notional: float
    net_vega_per_vol_pt: float
    short_leg_delta: float | None
    complete: bool  # every leg's greeks resolved


def structure_greeks(
    structure: StructureSpec,
    quotes: Mapping[str, LegQuote],
    *,
    beta_to_spy: float,
) -> StructureGreeks:
    """Position greeks (D3 §5.2), in the units the caps are stated in.

    ``Greeks.vega`` is per 1.00 change in sigma, so the per-vol-point figure
    divides by 100 — done in ``blackscholes.Greeks.vega_per_vol_point``, never
    re-derived here.
    """
    delta_shares = 0.0
    vega = 0.0
    short_delta: float | None = None
    complete = True
    spot = 0.0
    for leg in structure.legs:
        q = quotes.get(leg.option_ticker)
        if q is None or q.delta is None or q.vega_per_vol_pt is None:
            complete = False
            continue
        spot = q.underlying_close or spot
        units = leg.qty_signed * leg.shares_per_contract * structure.contracts
        delta_shares += q.delta * units
        vega += q.vega_per_vol_pt * units
        if leg.qty_signed < 0:
            short_delta = q.delta
    return StructureGreeks(
        net_delta_shares=delta_shares,
        net_delta_notional=delta_shares * spot * beta_to_spy,
        net_vega_per_vol_pt=vega,
        short_leg_delta=short_delta,
        complete=complete,
    )


# --------------------------------------------------------------------------- #
# Fills
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class StructureFill:
    """One transaction's modelled fills across every leg."""

    fills: dict[str, LegFill]
    cash: float  # signed cash flow, dollars: + received, - paid
    spread_cost: float
    commission: float
    fees: float
    net_premium_at_print: float  # cost to close, from unadjusted prints

    @property
    def transaction_costs(self) -> float:
        return self.spread_cost + self.commission + self.fees


def fill_structure(
    structure: StructureSpec,
    quotes: Mapping[str, LegQuote],
    *,
    cost_model: OptionCostModel,
    as_of: date,
    opening: bool,
    apply_intrinsic_floor: bool,
) -> StructureFill:
    """Fill every leg at its own print, adversely (D2 §6.2).

    A full modelled spread is charged **per leg per side**, so a 2-leg vertical
    pays four of them round trip. A leg without a print can never be filled — the
    caller checks printability first and treats its absence as a non-entry or a
    deferral, never as a synthetic fill.
    """
    fills: dict[str, LegFill] = {}
    cash = 0.0
    spread_cost = 0.0
    at_print = 0.0
    for leg in sorted(structure.legs, key=lambda x: x.option_ticker):
        q = quotes[leg.option_ticker]
        if q.print_close is None or q.underlying_close is None:
            raise ValueError(
                f"leg {leg.option_ticker} did not print on {as_of}; it cannot be filled"
            )
        signed_qty = leg.qty_signed if opening else -leg.qty_signed
        side = Side.BUY if signed_qty > 0 else Side.SELL
        fill = adverse_fill(
            ContractPrint(
                open=q.print_close,
                high=q.print_close,
                low=q.print_close,
                close=q.print_close,
                volume=0.0,
            ),
            cost_model,
            side=side,
            strike=leg.strike,
            right=leg.right_enum,
            underlying_close=q.underlying_close,
            dte=max((leg.expiration - as_of).days, 0),
            apply_intrinsic_floor=apply_intrinsic_floor and side is Side.BUY,
        )
        fills[leg.option_ticker] = fill
        units = abs(signed_qty) * leg.shares_per_contract * structure.contracts
        cash += -signed_qty * fill.price * leg.shares_per_contract * structure.contracts
        spread_cost += abs(fill.price - q.print_close) * units
        at_print += leg.qty_signed * q.print_close * leg.shares_per_contract
    sides = structure.contract_sides
    return StructureFill(
        fills=fills,
        cash=cash,
        spread_cost=spread_cost,
        commission=cost_model.commission(sides),
        fees=cost_model.fees(sides),
        net_premium_at_print=-at_print * structure.contracts,
    )


# --------------------------------------------------------------------------- #
# Collateral (D3 §3)
# --------------------------------------------------------------------------- #


def collateral_basis(
    structure: StructureSpec,
    *,
    net_credit_received: float,
    entry_costs: float,
) -> dict[str, Any]:
    """The reservation and the complete inputs that produced it.

    One consistent rule across all four Phase-1 formulas: the **gross**
    requirement is reserved and the credit lands in cash, so ``spendable_cash``
    falls by exactly ``R``. See the module docstring for why this differs from
    D3 §3.2's literal arithmetic (which double-counts the credit) while
    implementing D3 §8.0's stated invariant.

    A reservation whose ``basis_json`` cannot be re-evaluated to its ``amount``
    is a bug the reconciler (check 7) must catch, which is why every input is
    here rather than only the result.
    """
    m = structure.multiplier
    c = structure.contracts
    kind = structure.structure_type
    if kind == "vertical_credit":
        formula = "strike_width * M * contracts"
        amount = structure.strike_width * m * c
    elif kind == "vertical_debit":
        # Cash-settled at entry: the debit has already left ``cash``, so
        # reserving it again would tie up 2R.
        formula = "cash_settled_at_entry"
        amount = 0.0
    elif kind == "cash_secured_put":
        short = structure.short_leg
        formula = "strike * M * contracts"
        amount = (short.strike if short else 0.0) * m * c
    else:  # pragma: no cover - guarded by condition G before reaching here
        raise OptionsAutoSimulateForbidden("G", f"structure type {kind!r} has no Phase 1 formula")
    return {
        "formula": formula,
        "structure_type": kind,
        "strike": structure.short_leg.strike if structure.short_leg else None,
        "strike_width": structure.strike_width,
        "shares_per_contract": m,
        "contracts": c,
        "net_credit": round(net_credit_received, 6),
        "entry_costs": round(entry_costs, 6),
        "amount": round(amount, 6),
    }


def reevaluate_basis(basis: Mapping[str, Any]) -> float:
    """Recompute a reservation from its own recorded inputs (reconcile check 7)."""
    formula = basis.get("formula")
    m = float(basis.get("shares_per_contract") or 0)
    c = float(basis.get("contracts") or 0)
    if formula == "strike_width * M * contracts":
        return float(basis.get("strike_width") or 0.0) * m * c
    if formula == "cash_settled_at_entry":
        return 0.0
    if formula == "strike * M * contracts":
        return float(basis.get("strike") or 0.0) * m * c
    raise ValueError(f"unknown collateral formula {formula!r}")


def reserve_collateral(
    session: Session,
    account: PaperAccount,
    position: OptionsPosition,
    *,
    amount: Decimal,
    basis: Mapping[str, Any],
    as_of: date,
) -> OptionsCollateralEntry:
    """Append a ``reserve`` entry and move the account balance with it."""
    account.collateral_reserved = account.collateral_reserved + amount
    entry = OptionsCollateralEntry(
        account_id=account.id,
        position_id=position.id,
        event="reserve",
        amount=amount,
        basis_json=dict(basis),
        balance_after=account.collateral_reserved,
        as_of=as_of,
    )
    session.add(entry)
    session.flush()
    return entry


def release_collateral(
    session: Session,
    account: PaperAccount,
    position: OptionsPosition,
    *,
    as_of: date,
) -> OptionsCollateralEntry | None:
    """Append the matching ``release``, for exactly the reserved amount.

    Ordering (D3 §8 step 4, inverted from rev 1): the structure close and the
    immutable ``options_trade`` are written FIRST and the release LAST. A crash
    in that window leaves a closed structure with its collateral still reserved —
    conservative, capacity-*blocking*, and caught by reconcile check 5. The
    opposite ordering leaves collateral freed with no close record, which is
    fail-open: it inflates ``spendable_cash`` and re-opens capacity under
    conditions O / P / R before the reconciler next runs.

    **Releasing twice is refused here, not merely made unlikely.** The structure
    keeps its ``collateral_reserved`` figure after the close — it is the audit of
    what that structure held, and zeroing it would delete exactly the number
    reconcile check 4 compares — so nothing about the row prevents a second
    release. A double release is the fail-open direction (free capacity with no
    structure behind it), so this checks the ledger for an existing release
    rather than trusting the caller's control flow.
    """
    amount = position.collateral_reserved
    if amount <= 0:
        return None
    already = session.scalar(
        select(OptionsCollateralEntry.id).where(
            OptionsCollateralEntry.position_id == position.id,
            OptionsCollateralEntry.event == "release",
        )
    )
    if already is not None:
        return None
    account.collateral_reserved = account.collateral_reserved - amount
    entry = OptionsCollateralEntry(
        account_id=account.id,
        position_id=position.id,
        event="release",
        amount=amount,
        basis_json={"formula": "release_of_reserve", "amount": float(amount)},
        balance_after=account.collateral_reserved,
        as_of=as_of,
    )
    session.add(entry)
    session.flush()
    return entry


# --------------------------------------------------------------------------- #
# Limits (D3 §5, §9)
# --------------------------------------------------------------------------- #

#: A limit entry's three states (D3 §9). ``binding`` is within the limit with
#: less than 10% headroom; ``breached`` means the entry is refused. Rev 1's
#: boolean ``bound`` rendered "tight but legal" and "refused" identically, which
#: is how rev 1's own worked example passed review as an acceptance.
_BINDING_HEADROOM = 0.10


def _state(value: float, limit: float, *, higher_is_worse: bool = True) -> str:
    v = abs(value)
    if limit <= 0:
        # A zero limit means "nothing is allowed", never "no limit". The options
        # daily cap defaults to 0, so returning "ok" here would have made the one
        # setting that keeps the path disarmed by default silently ineffective.
        return "breached" if higher_is_worse and v > 1e-9 else "ok"
    if higher_is_worse and v > limit + 1e-9:
        return "breached"
    return "binding" if v >= limit * (1.0 - _BINDING_HEADROOM) else "ok"


@dataclass(slots=True)
class LimitsEvaluation:
    """Every limit, its POST-entry value, and its state — bound or not.

    The convention is declared rather than left to a reader: **every ``value`` is
    the POST-entry figure**, what the book would look like if this entry were
    taken, because that is the quantity the limit actually governs. Counts
    therefore read 1, not 0, for a first structure.

    Recording every limit on every decision is what keeps D3 Finding 1 knowable:
    at decision 4's numbers neither greek cap binds, and the only way to keep
    knowing that is to record the headroom rather than infer it from an absence
    of refusals.
    """

    entries: dict[str, dict[str, Any]] = field(default_factory=dict)
    first_breach: tuple[str, str, str] | None = None  # (condition, limit_name, reason)

    def record(
        self,
        name: str,
        *,
        condition: str,
        limit: float,
        value: float,
        breached: bool | None = None,
        reason: str = "",
        higher_is_worse: bool = True,
    ) -> None:
        state = (
            ("breached" if breached else _state(value, limit, higher_is_worse=False))
            if breached is not None
            else _state(value, limit, higher_is_worse=higher_is_worse)
        )
        self.entries[name] = {"limit": limit, "value": value, "state": state}
        if state == "breached" and self.first_breach is None:
            self.first_breach = (
                condition,
                name,
                reason or f"{name} {value!r} violates limit {limit!r}",
            )

    def to_dict(self) -> dict[str, Any]:
        return dict(self.entries)


@dataclass(frozen=True, slots=True)
class BookState:
    """The options book as it stands, before this entry."""

    open_structures: int
    open_r_total: float
    collateral_reserved: float
    spendable_cash: float
    net_delta_notional: float
    net_vega_per_vol_pt: float
    equity_net_delta_notional: float
    structures_on_underlying: int
    orders_today: int
    accepts_today: int


def book_state(
    session: Session,
    account: PaperAccount,
    *,
    underlying_instrument_id: int | None,
    now: datetime,
) -> BookState:
    """Read the current options book. Marks supply the current greeks, so the
    caps are evaluated against a live book rather than entry-time values."""
    from signalforge.db.models import OptionsMark

    rows = list(
        session.scalars(
            select(OptionsPosition).where(
                OptionsPosition.account_id == account.id,
                OptionsPosition.closed_at.is_(None),
            )
        )
    )
    delta = 0.0
    vega = 0.0
    for pos in rows:
        mark = session.scalar(
            select(OptionsMark)
            .where(OptionsMark.position_id == pos.id)
            .order_by(OptionsMark.as_of.desc(), OptionsMark.id.desc())
            .limit(1)
        )
        if mark is not None:
            delta += mark.net_delta_notional
            vega += mark.net_vega_per_vol_pt
    day_start = datetime.combine(now.astimezone(UTC).date(), time.min, tzinfo=UTC)
    orders_today = int(
        session.scalar(
            select(func.count())
            .select_from(OptionsPosition)
            .where(
                OptionsPosition.account_id == account.id,
                OptionsPosition.created_at >= day_start,
            )
        )
        or 0
    )
    accepts_today = int(
        session.scalar(
            select(func.count())
            .select_from(OptionsTrade)
            .where(
                OptionsTrade.account_id == account.id,
                OptionsTrade.decision == PaperDecision.ACCEPTED,
                OptionsTrade.created_at >= day_start,
            )
        )
        or 0
    )
    return BookState(
        open_structures=len(rows),
        open_r_total=float(sum(float(p.r_dollars) for p in rows)),
        collateral_reserved=float(account.collateral_reserved),
        spendable_cash=float(account.spendable_cash),
        net_delta_notional=delta,
        net_vega_per_vol_pt=vega,
        equity_net_delta_notional=_equity_net_delta_notional(session),
        structures_on_underlying=sum(
            1 for p in rows if p.underlying_instrument_id == underlying_instrument_id
        ),
        orders_today=orders_today,
        accepts_today=accepts_today,
    )


def _equity_net_delta_notional(session: Session) -> float:
    """The equity book's delta notional, for the COMBINED cap only.

    Read-only, and consulted in exactly one place: condition V inside
    ``assert_options_auto_simulate_allowed``. It is never consulted by
    ``risk.size_position``, by ``accept_candidate``, or by
    ``assert_auto_simulate_allowed``, so the combined cap can only ever refuse an
    OPTIONS open and the equity path is byte-identical whether or not it exists
    (D3 §5.2 Finding 2).
    """
    from signalforge.db.models import PaperPosition
    from signalforge.domain import PositionSide

    total = 0.0
    for pos in session.scalars(select(PaperPosition).where(PaperPosition.closed_at.is_(None))):
        d = 1 if pos.side is PositionSide.LONG else -1
        total += d * pos.qty * float(pos.avg_price)
    return total


def evaluate_options_limits(
    *,
    limits: OptionsRiskLimits,
    shaping: OptionsStructureLimits,
    book: BookState,
    r_dollars: float,
    collateral_required: float,
    net_premium: float,
    credit_to_width: float | None,
    short_leg_delta: float | None,
    theta_at_1x: float | None,
    theta_at_2x: float | None,
    greeks: StructureGreeks,
    account_equity: float,
    daily_cap: int,
) -> LimitsEvaluation:
    """Every capital and shaping limit, evaluated POST-entry, in A-AB order.

    The FIRST breach is the one named, matching ``assert_auto_simulate_allowed``'s
    existing behaviour of naming the first failed condition.
    """
    ev = LimitsEvaluation()
    ev.record(
        "spendable_cash",
        condition="O",
        limit=book.spendable_cash,
        value=collateral_required,
        breached=collateral_required > book.spendable_cash + 1e-9,
        reason=(
            f"collateral required {collateral_required:.2f} exceeds spendable cash "
            f"{book.spendable_cash:.2f}"
        ),
    )
    ev.record(
        "collateral_cap",
        condition="P",
        limit=limits.collateral_cap_dollars,
        value=book.collateral_reserved + collateral_required,
    )
    ev.record(
        "per_structure_max_loss",
        condition="Q",
        limit=limits.per_structure_max_loss_dollars,
        value=r_dollars,
    )
    ev.record(
        "total_open_max_loss",
        condition="R",
        limit=limits.total_open_max_loss_dollars,
        value=book.open_r_total + r_dollars,
    )
    ev.record(
        "max_short_delta",
        condition="S",
        limit=shaping.max_short_delta,
        value=abs(short_leg_delta) if short_leg_delta is not None else float("inf"),
        breached=short_leg_delta is None or abs(short_leg_delta) > shaping.max_short_delta + 1e-9,
        reason=(
            f"|short leg delta| {abs(short_leg_delta):.4f} > max_short_delta "
            f"{shaping.max_short_delta}"
            if short_leg_delta is not None
            else "the short leg's delta could not be computed from prints"
        ),
    )
    ev.record(
        "min_credit_to_width",
        condition="S",
        limit=shaping.min_credit_to_width,
        value=credit_to_width if credit_to_width is not None else 0.0,
        breached=(
            shaping.min_credit_to_width > 0.0
            and (credit_to_width is None or credit_to_width < shaping.min_credit_to_width - 1e-9)
        ),
        reason=(
            f"credit/width {credit_to_width!r} < min_credit_to_width "
            f"{shaping.min_credit_to_width}"
        ),
    )
    theta_limit = shaping.min_net_credit_after_costs_to_max_loss
    ev.record(
        "theta_at_1x",
        condition="T",
        limit=theta_limit,
        value=theta_at_1x if theta_at_1x is not None else float("-inf"),
        breached=theta_at_1x is None or theta_at_1x < theta_limit - 1e-9,
        reason=f"theta@1x {theta_at_1x!r} < {theta_limit}",
    )
    ev.record(
        "theta_at_2x",
        condition="T",
        limit=theta_limit,
        value=theta_at_2x if theta_at_2x is not None else float("-inf"),
        breached=theta_at_2x is None or theta_at_2x < theta_limit - 1e-9,
        reason=f"theta@2x {theta_at_2x!r} < {theta_limit} (gate 4b, decision 5)",
    )
    ev.record(
        "options_net_delta",
        condition="U",
        limit=limits.max_net_delta_notional_dollars,
        value=book.net_delta_notional + greeks.net_delta_notional,
    )
    ev.record(
        "combined_net_delta",
        condition="V",
        limit=limits.combined_max_net_delta_notional_dollars,
        value=book.net_delta_notional + greeks.net_delta_notional + book.equity_net_delta_notional,
    )
    ev.record(
        "options_net_vega",
        condition="W",
        limit=limits.max_net_vega_dollars_per_vol_pt,
        value=book.net_vega_per_vol_pt + greeks.net_vega_per_vol_pt,
    )
    ev.record(
        "max_structures_per_underlying",
        condition="X",
        limit=float(limits.max_structures_per_underlying),
        value=float(book.structures_on_underlying + 1),
    )
    ev.record(
        "max_open_structures",
        condition="Y",
        limit=float(limits.max_open_structures),
        value=float(book.open_structures + 1),
    )
    ev.record(
        "daily_order_cap",
        condition="Z",
        limit=float(limits.daily_order_cap),
        value=float(book.orders_today + 1),
    )
    ev.record(
        "options_auto_simulate_max_per_day",
        condition="Z",
        limit=float(daily_cap),
        value=float(book.accepts_today + 1),
    )
    ev.record(
        "per_order_notional",
        condition="P",
        limit=limits.per_order_notional_dollars,
        value=abs(net_premium) + collateral_required,
    )
    ev.record(
        "account_exposure_cap_pct",
        condition="P",
        limit=limits.account_exposure_cap_pct,
        value=(
            (book.collateral_reserved + collateral_required) / account_equity * 100.0
            if account_equity > 0
            else 0.0
        ),
    )
    return ev


# --------------------------------------------------------------------------- #
# The second guard (D3 §10.2)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class OptionsEntryPlan:
    """What the guard computed while deciding, so the acceptance need not redo it."""

    structure: StructureSpec
    account: PaperAccount
    fill: StructureFill
    quotes: dict[str, LegQuote]
    greeks: StructureGreeks
    r_dollars: float
    r_at_print: float
    collateral_required: float
    credit_to_width: float | None
    theta_at_1x: float | None
    theta_at_2x: float | None
    limits: LimitsEvaluation
    shaping: OptionsStructureLimits
    risk_limits: OptionsRiskLimits
    signal_session: date
    fill_session: date
    dte_at_entry: int


def _entry_price_sources(
    session: Session, run: Any, pricing: OptionsPricingContext
) -> tuple[str, str]:
    """Condition AC: ``(option_source, underlying_source)`` for an entry, or a refusal.

    * ``underlying_source`` is ``scan_run.source`` — the bar label the signal was
      computed from and condition H scope-matched against the approval. It must
      equal ``pricing.underlying_source``, the label the context's spot was read
      from (the EOD chain resolves it from this same scan; a caller that resolved
      it elsewhere is refused rather than trusted).
    * ``option_source`` is resolved from the scan's DataSnapshot by
      ``research.options_evidence.resolve_option_data_source`` — the two-source
      pattern of PR #14: two recorded witnesses that must agree, never a fallback
      to the bar label. A scan that pins no snapshot cannot name one and is
      refused.
    """
    from signalforge.db.models import DataSnapshot
    from signalforge.research.options_evidence import (
        OptionSourceUnresolved,
        resolve_option_data_source,
    )

    underlying_source = str(run.source or "").strip()
    if not underlying_source:
        raise OptionsAutoSimulateForbidden(
            "AC", f"scan run {run.id} records no bar source; the spot cannot name its source"
        )
    if str(pricing.underlying_source or "").strip() != underlying_source:
        raise OptionsAutoSimulateForbidden(
            "AC",
            f"the pricing context's spot was read from {pricing.underlying_source!r} but scan "
            f"run {run.id} was computed from {underlying_source!r}; one structure is never "
            "priced across two bar sources",
        )
    snap = (
        session.get(DataSnapshot, run.dataset_snapshot_id)
        if run.dataset_snapshot_id is not None
        else None
    )
    if snap is None:
        raise OptionsAutoSimulateForbidden(
            "AC",
            f"scan run {run.id} pins no DataSnapshot, so the option-data source of its legs' "
            "prints cannot be resolved; it is never guessed and never the bar source",
        )
    try:
        option_source = resolve_option_data_source(session, snap)
    except OptionSourceUnresolved as exc:
        raise OptionsAutoSimulateForbidden("AC", str(exc)) from None
    return option_source, underlying_source


def _theta(net_credit: float, costs_round_trip: float, r_dollars: float) -> float | None:
    """``(net credit - modelled round-trip costs) / R`` (D3 §5.3 axis 3)."""
    if r_dollars <= 0:
        return None
    return (net_credit - costs_round_trip) / r_dollars


def assert_options_auto_simulate_allowed(
    session: Session,
    cand: Candidate,
    *,
    account_name: str,
    pricing: OptionsPricingContext,
    signal_session: date,
    fill_session: date,
    now: datetime | None = None,
) -> OptionsEntryPlan:
    """The SECOND guard. Refuses unless every condition A-AB holds, naming the FIRST.

    This is a **separate function with a separate exception type**, not a widening
    of ``assert_auto_simulate_allowed``. The equity guard is never relaxed: it
    gains one *narrowing* refusal (a candidate carrying ``structure_kind`` is
    refused outright) and nothing else.

    ``signal_session`` and ``fill_session`` are both required, and condition M is
    evaluated at the **fill** session (D3 §6.0). The equity convention is signal
    at ``t``, fill at ``t+1`` (``backtest/engine.py``: "entries fill at the next
    bar's open"); an options path that filled at ``t`` on a close its own signal
    was computed from would be filling a full session earlier than the equity
    path, on information the signal already used.

    Returns the plan it computed, so the acceptance does not price the structure a
    second time and cannot price it differently.
    """
    from signalforge.data import options_calendar
    from signalforge.db.models import ScanRun, StrategyVersion
    from signalforge.domain import StrategyStatus
    from signalforge.research.approval_scope import (
        approved_scopes,
        current_spec_json_hash,
        scan_scope_matches,
    )

    now = now or datetime.now(UTC)
    cfg = effective_research_config(session)
    risk_limits = cfg.options_risk

    # A — the SECOND setting, default FALSE.
    if not options_auto_simulate_enabled(session):
        raise OptionsAutoSimulateForbidden("A", f"{OPTIONS_AUTO_SIM_ENABLED_KEY} is off")
    # B — the SHARED kill switch. Blocks opening; never blocks closing.
    ensure_not_engaged()
    # C — a POSITIVE discriminator, never "not a stock".
    if cand.structure_kind != OPTIONS_STRUCTURE_KIND:
        raise OptionsAutoSimulateForbidden(
            "C",
            f"candidate.structure_kind is {cand.structure_kind!r}, not {OPTIONS_STRUCTURE_KIND!r}",
        )
    row = session.scalar(
        select(CandidateOptionStructure).where(CandidateOptionStructure.candidate_id == cand.id)
    )
    if row is None:
        raise OptionsAutoSimulateForbidden(
            "C", "candidate is marked as an options structure but carries no structure row"
        )
    # D / E
    if cand.quality_gate_status is not QualityGate.PASSED:
        raise OptionsAutoSimulateForbidden("D", "candidate did not pass every quality gate")
    if cand.direction is Direction.AVOID:
        raise OptionsAutoSimulateForbidden("E", "candidate direction is AVOID")
    # F
    ver = session.get(StrategyVersion, cand.strategy_version_id)
    if ver is None or ver.status is not StrategyStatus.PAPER_APPROVED:
        raise OptionsAutoSimulateForbidden("F", "strategy version is not PAPER_APPROVED")
    shaping = OptionsStructureLimits.from_spec_json(ver.spec_json, cfg.options_shaping)
    # The sources are resolved at AC, below, once the scan is known; until then
    # the structure carries none and no price is read from it.
    structure = structure_from_candidate(row, option_source="", underlying_source="")
    # G — exactly ONE approved structure type per version (gate 0.5).
    if structure.structure_type != shaping.structure_type:
        raise OptionsAutoSimulateForbidden(
            "G",
            f"structure type {structure.structure_type!r} is not the version's approved "
            f"type {shaping.structure_type!r}",
        )
    if structure.structure_type not in _PHASE1_STRUCTURE_TYPES:
        raise OptionsAutoSimulateForbidden(
            "G", f"structure type {structure.structure_type!r} is out of Phase 1 scope"
        )
    # H — the five-part equity scope match.
    run = session.get(ScanRun, cand.scan_run_id)
    scopes = approved_scopes(session, ver.id)
    if run is None or not scan_scope_matches(
        scopes,
        dataset_snapshot_id=run.dataset_snapshot_id,
        config_hash=run.config_hash,
        spec_json_hash=current_spec_json_hash(session, ver.id) or "",
        source=run.source,
        universe=frozenset(x.upper() for x in (run.universe_json or ())),
    ):
        raise OptionsAutoSimulateForbidden(
            "H", "scan scope does not match the strategy's approved scope"
        )
    # I — the SIXTH part: the options risk+coverage scope hash.
    approved_options_scope = (ver.spec_json or {}).get("options_scope_hash")
    live_options_scope = options_scope_hash(cfg)
    if approved_options_scope is not None and approved_options_scope != live_options_scope:
        raise OptionsAutoSimulateForbidden(
            "I",
            f"options scope hash {live_options_scope[:16]}... does not match the approved "
            f"{str(approved_options_scope)[:16]}...",
        )
    # J — the SEVENTH part: the options DATA scope hash.
    approved_data_scope = (ver.spec_json or {}).get("options_data_scope_hash")
    live_data_scope = (
        (run.dataset_snapshot_id, _options_data_scope_hash(session, run.dataset_snapshot_id))[1]
        if run is not None
        else None
    )
    if approved_data_scope is not None and approved_data_scope != live_data_scope:
        raise OptionsAutoSimulateForbidden(
            "J", "options data scope hash does not match the approved options data scope"
        )
    # K / L — read PER LEG from the contract row, never assumed.
    for leg in structure.legs:
        contract = session.scalar(
            select(OptionContract).where(OptionContract.option_ticker == leg.option_ticker).limit(1)
        )
        spc = contract.shares_per_contract if contract is not None else leg.shares_per_contract
        style = contract.exercise_style if contract is not None else leg.exercise_style
        if spc != _PHASE1_SHARES_PER_CONTRACT or leg.shares_per_contract != spc:
            raise OptionsAutoSimulateForbidden(
                "K",
                f"{leg.option_ticker} has shares_per_contract={spc} "
                f"(leg carries {leg.shares_per_contract}); Phase 1 requires 100",
            )
        if style != _PHASE1_EXERCISE_STYLE:
            raise OptionsAutoSimulateForbidden(
                "L",
                f"{leg.option_ticker} is {style!r}; Phase 1's surface fit, q sourcing and data "
                "path are built for american-style physically-settled options only "
                "(a SCOPE restriction, not a safety property — cash-settled index options "
                "are out of Phase 1 scope and their exclusion leaves the biased case in)",
            )
    # N — account targeting, before anything is written anywhere.
    account = resolve_options_account(session, account_name=account_name)
    # AC — price-source provenance, BEFORE the first price is read. The legs'
    # prints are read from the ONE option-data source the scan's DataSnapshot
    # records (never guessed, never the bar label) and the spot from the scan's
    # own bar source — which must be the source the pricing context's spot was
    # read from, or the greeks would mix two vendors' closes. Both labels are
    # then recorded on the position, so every later mark reads the same rows.
    assert run is not None  # H refused otherwise
    option_source, underlying_source = _entry_price_sources(session, run, pricing)
    structure = replace(structure, option_source=option_source, underlying_source=underlying_source)
    # M — every leg must print on the FILL session. A missing bar is a NON-ENTRY,
    # never a synthetic fill, and it is a property of the session the guard is
    # running on, so it consults nothing in the future.
    try:
        quotes = {
            leg.option_ticker: leg_quote(
                session,
                leg,
                underlying_symbol=structure.underlying_symbol,
                as_of=fill_session,
                pricing=pricing,
                option_source=structure.option_source,
                underlying_source=structure.underlying_source,
            )
            for leg in structure.legs
        }
    except PriceSourceUnresolved as exc:
        raise OptionsAutoSimulateForbidden("AC", str(exc)) from None
    missing = [t for t, q in quotes.items() if not q.priced]
    if missing:
        raise OptionsAutoSimulateForbidden(
            "M", f"no print on the fill session {fill_session} for {', '.join(sorted(missing))}"
        )
    # AB — the options calendar agrees this is a completed trading session.
    try:
        if options_calendar.last_trade_session(fill_session) != fill_session:
            raise OptionsAutoSimulateForbidden(
                "AB", f"{fill_session} is not an XNYS trading session"
            )
        if fill_session <= signal_session:
            raise OptionsAutoSimulateForbidden(
                "AB",
                f"fill session {fill_session} must follow the signal session {signal_session} "
                "(D3 §6.0: signal at t, fill at t+1)",
            )
    except options_calendar.CalendarUnresolved as exc:
        raise OptionsAutoSimulateForbidden("AB", str(exc)) from None
    # AA — POSITIVE and DATED. A missing row refuses exactly as a divergent row
    # refuses: absence is never evidence of health.
    report = session.scalar(
        select(OptionsReconcileReport).where(
            OptionsReconcileReport.account_id == account.id,
            OptionsReconcileReport.as_of == fill_session,
        )
    )
    if report is None:
        raise OptionsAutoSimulateForbidden(
            "AA",
            f"no collateral reconciliation report for account {account.name!r} on {fill_session}",
        )
    if not report.clean:
        raise OptionsAutoSimulateForbidden(
            "AA",
            f"collateral reconciliation for {fill_session} is not clean: "
            f"{[f['check'] for f in report.findings_json]}",
        )

    # --- price the entry, then evaluate every capital and shaping limit -----
    entry = fill_structure(
        structure,
        quotes,
        cost_model=pricing.cost_model,
        as_of=fill_session,
        opening=True,
        apply_intrinsic_floor=False,
    )
    net_credit_received = entry.cash
    entry_costs = entry.transaction_costs
    gross = structure.strike_width * structure.multiplier * structure.contracts
    r_at_print = gross - entry.net_premium_at_print
    r_dollars = gross - net_credit_received + entry.commission + entry.fees
    if r_dollars <= 0.0 or r_at_print <= 0.0:
        raise OptionsAutoSimulateForbidden(
            "Q", f"non-positive R (incl {r_dollars:.2f}, at_print {r_at_print:.2f})"
        )
    basis = collateral_basis(
        structure, net_credit_received=net_credit_received, entry_costs=entry_costs
    )
    collateral_required = float(basis["amount"])
    width_dollars = structure.strike_width * structure.multiplier * structure.contracts
    credit_to_width = entry.net_premium_at_print / width_dollars if width_dollars > 0 else None
    greeks = structure_greeks(structure, quotes, beta_to_spy=pricing.beta_to_spy)
    round_trip_1x = 2.0 * entry_costs
    round_trip_2x = 2.0 * (2.0 * entry.spread_cost + entry.commission + entry.fees)
    plan_limits = evaluate_options_limits(
        limits=risk_limits,
        shaping=shaping,
        book=book_state(
            session,
            account,
            underlying_instrument_id=cand.instrument_id,
            now=now,
        ),
        r_dollars=r_dollars,
        collateral_required=collateral_required,
        net_premium=net_credit_received,
        credit_to_width=credit_to_width,
        short_leg_delta=greeks.short_leg_delta,
        theta_at_1x=_theta(net_credit_received, round_trip_1x, r_dollars),
        theta_at_2x=_theta(net_credit_received, round_trip_2x, r_dollars),
        greeks=greeks,
        account_equity=float(account.initial_cash),
        daily_cap=options_auto_simulate_max_per_day(session),
    )
    if plan_limits.first_breach is not None:
        condition, _name, reason = plan_limits.first_breach
        raise OptionsAutoSimulateForbidden(condition, reason)

    return OptionsEntryPlan(
        structure=structure,
        account=account,
        fill=entry,
        quotes=quotes,
        greeks=greeks,
        r_dollars=r_dollars,
        r_at_print=r_at_print,
        collateral_required=collateral_required,
        credit_to_width=credit_to_width,
        theta_at_1x=_theta(net_credit_received, round_trip_1x, r_dollars),
        theta_at_2x=_theta(net_credit_received, round_trip_2x, r_dollars),
        limits=plan_limits,
        shaping=shaping,
        risk_limits=risk_limits,
        signal_session=signal_session,
        fill_session=fill_session,
        dte_at_entry=(structure.expiration - fill_session).days,
    )


def options_scope_hash(cfg: Any) -> str:
    """The SIXTH scope part (D3 §4): a hash over the options risk + coverage
    configuration, computed separately and **never** folded into ``config_hash``.

    Changing a refusal-only limit therefore un-scopes the OPTIONS strategy and
    nothing else — the correct blast radius, and the lesson of the 2026-09-11
    config-hash incident applied in the right direction.
    """
    from signalforge.config.hashing import config_hash

    return config_hash(
        {
            "options": cfg.options.model_dump(mode="json"),
            "options_risk": cfg.options_risk.model_dump(mode="json"),
        }
    )


def _options_data_scope_hash(session: Session, dataset_snapshot_id: int | None) -> str | None:
    """The SEVENTH scope part (D1 §3.5): the hash of the snapshot's
    ``options_scope_json``. ``None`` when the scan resolved no snapshot, which
    condition J then refuses against any recorded approval."""
    from signalforge.config.hashing import config_hash
    from signalforge.db.models import DataSnapshot

    if dataset_snapshot_id is None:
        return None
    snap = session.get(DataSnapshot, dataset_snapshot_id)
    if snap is None or snap.options_scope_json is None:
        return None
    return config_hash(snap.options_scope_json)


# --------------------------------------------------------------------------- #
# The evidence snapshot (D3 §9)
# --------------------------------------------------------------------------- #


def options_candidate_snapshot(
    session: Session,
    cand: Candidate,
    *,
    account: PaperAccount,
    structure: StructureSpec,
    plan: OptionsEntryPlan | None,
    limits: LimitsEvaluation | None,
    refused_condition: str = "",
    refused_reason: str = "",
    pricing: OptionsPricingContext | None = None,
) -> dict[str, Any]:
    """The COMPLETE, immutable options evidence snapshot.

    A **separate function** from ``paper.ledger._candidate_snapshot``, not an
    extension of it, so the equity snapshot's shape is unchanged and the live
    approvals' records stay comparable. It reuses the equity snapshot's keys for
    the candidate-level evidence and adds the ``options`` block.

    Disclosures are **stored, not printed**: ``options_trade`` is immutable, so a
    disclosure that is in the row cannot be dropped from a later report.
    """
    from signalforge.paper.ledger import _candidate_snapshot

    base = _candidate_snapshot(session, cand)
    cfg = effective_research_config(session)
    legs = [
        {
            "option_ticker": leg.option_ticker,
            "right": leg.right,
            "strike": leg.strike,
            "expiration": leg.expiration.isoformat(),
            "qty_signed": leg.qty_signed,
            # READ from option_contract at entry, so the x100 arithmetic in R and
            # in the collateral basis is auditable rather than assumed.
            "shares_per_contract": leg.shares_per_contract,
            "exercise_style": leg.exercise_style,
        }
        for leg in structure.legs
    ]
    options_block: dict[str, Any] = {
        "account_name": account.name,
        "structure_type": structure.structure_type,
        "underlying_symbol": structure.underlying_symbol,
        "contracts": structure.contracts,
        "legs": legs,
        "strike_width": structure.strike_width,
        # Price-source provenance: which rows every print and spot were read from.
        "option_source": structure.option_source,
        "underlying_source": structure.underlying_source,
        "disclosures": list(DISCLOSURES),
        "options_scope_hash": options_scope_hash(cfg),
        "options_shaping_hash": (
            plan.shaping.options_shaping_hash
            if plan is not None
            else cfg.options_shaping.options_shaping_hash
        ),
        "notice": NOTICE,
    }
    if plan is not None:
        fills = {
            ticker: {
                "price": round(f.price, 6),
                "spread": round(f.spread, 6),
                "side": f.side.value,
                "spread_ge_print": f.spread_ge_print,
                "proceeds_floored_at_zero": f.proceeds_floored_at_zero,
            }
            for ticker, f in plan.fill.fills.items()
        }
        options_block |= {
            "signal_session": plan.signal_session.isoformat(),
            "fill_session": plan.fill_session.isoformat(),
            "dte_at_entry": plan.dte_at_entry,
            "entry_net_premium": round(plan.fill.cash, 6),
            "entry_net_premium_at_print": round(plan.fill.net_premium_at_print, 6),
            "entry_costs": round(plan.fill.transaction_costs, 6),
            "fills": fills,
            "max_loss_dollars_R": round(plan.r_dollars, 6),
            "max_loss_dollars_R_at_print": round(plan.r_at_print, 6),
            "credit_to_width": plan.credit_to_width,
            "short_leg_delta": plan.greeks.short_leg_delta,
            "net_delta_shares": plan.greeks.net_delta_shares,
            "net_delta_notional": plan.greeks.net_delta_notional,
            "net_vega_per_vol_pt": plan.greeks.net_vega_per_vol_pt,
            "beta_to_spy": pricing.beta_to_spy if pricing else None,
            "theta_credit_after_costs_to_R": {
                "at_1x": plan.theta_at_1x,
                "at_2x": plan.theta_at_2x,
            },
            "collateral_reserved": round(plan.collateral_required, 6),
            "spendable_cash_before": round(float(account.spendable_cash), 6),
            "spendable_cash_after": round(
                float(account.spendable_cash)
                + plan.fill.cash
                - plan.fill.commission
                - plan.fill.fees
                - plan.collateral_required,
                6,
            ),
            "collateral_basis": collateral_basis(
                structure,
                net_credit_received=plan.fill.cash,
                entry_costs=plan.fill.transaction_costs,
            ),
            "fill_model": FILL_MODEL,
            "cost_model": (
                {
                    "spread_pct_of_last_print": pricing.cost_model.spread_pct_of_last_print,
                    "spread_abs_floor_cents": pricing.cost_model.spread_abs_floor_cents,
                    "spread_multiplier": pricing.cost_model.spread_multiplier,
                    "commission_per_contract": pricing.cost_model.commission_per_contract,
                }
                if pricing is not None
                else None
            ),
            "iv_source": pricing.iv_source if pricing else None,
            "q_source": pricing.q_source if pricing else None,
            "greeks_source": pricing.greeks_source if pricing else None,
        }
    if limits is not None:
        options_block["limits_evaluated"] = limits.to_dict()
    if refused_condition:
        options_block |= {
            "refused": True,
            "refused_condition": refused_condition,
            "refused_reason": refused_reason,
            "notice": f"{NOTICE[:-1]}; the entry was REFUSED.",
        }
    return base | {"options": options_block}


# --------------------------------------------------------------------------- #
# Decisions and acceptance
# --------------------------------------------------------------------------- #


def record_options_decision(
    session: Session,
    candidate_id: int,
    decision: PaperDecision,
    *,
    account_name: str,
    note: str = "",
    actor: str = "local-user",
    refused_condition: str = "",
    limits: LimitsEvaluation | None = None,
    pricing: OptionsPricingContext | None = None,
) -> int:
    """Record REJECTED / IGNORED / WATCH against an options candidate.

    A refused candidate is **recorded, not dropped**: the immutable snapshot
    carries the exact refusal reason and the condition it failed, so refusals are
    evidence rather than log lines.
    """
    ensure_not_engaged()
    if decision is PaperDecision.ACCEPTED:
        raise ValueError("use accept_options_candidate() for ACCEPTED")
    cand = session.get(Candidate, candidate_id)
    if cand is None:
        raise ValueError(f"candidate {candidate_id} not found")
    account = resolve_options_account(session, account_name=account_name)
    row = session.scalar(
        select(CandidateOptionStructure).where(CandidateOptionStructure.candidate_id == cand.id)
    )
    if row is None:
        raise ValueError(f"candidate {candidate_id} carries no options structure")
    # A non-ACCEPTED decision reads no price, so it resolves no source; the
    # snapshot records the structure with the labels blank rather than invented.
    structure = structure_from_candidate(row, option_source="", underlying_source="")
    snapshot = options_candidate_snapshot(
        session,
        cand,
        account=account,
        structure=structure,
        plan=None,
        limits=limits,
        refused_condition=refused_condition,
        refused_reason=note,
        pricing=pricing,
    ) | {"decision": {"actor": actor, "note": note, "automatic": actor.endswith("auto_simulate")}}
    trade = OptionsTrade(
        account_id=account.id,
        candidate_id=cand.id,
        strategy_version_id=cand.strategy_version_id,
        decision=decision,
        structure_type=structure.structure_type,
        underlying_symbol=structure.underlying_symbol,
        signal_snapshot_json=snapshot,
        plan_json={"structure_type": structure.structure_type, "legs": len(structure.legs)},
        why_qualified="; ".join(cand.reasons_qualify),
        why_might_fail="; ".join(cand.reasons_fail),
        refused=decision is PaperDecision.REJECTED,
        refused_condition=refused_condition[:4],
        actor=actor,
        note=note,
        created_at=utcnow(),
    )
    session.add(trade)
    session.flush()
    _log.info(
        "paper.options_decision",
        candidate=candidate_id,
        decision=decision.value,
        condition=refused_condition,
    )
    return trade.id


@dataclass(frozen=True, slots=True)
class AcceptOptionsResult:
    options_trade_id: int
    position_id: int
    structure_type: str
    contracts: int
    net_premium: float
    r_dollars: float
    collateral_reserved: float


def accept_options_candidate(
    session: Session,
    candidate_id: int,
    *,
    account_name: str,
    plan: OptionsEntryPlan,
    pricing: OptionsPricingContext,
    actor: str = "local-user",
    note: str = "",
) -> AcceptOptionsResult:
    """Open a SIMULATED options structure from a plan the guard already approved.

    ``plan`` is the guard's own return value, and it is **required**: the entry is
    never priced twice and therefore can never be priced differently from what
    the guard evaluated its limits against.

    The whole open is ONE unit of work (D3 §8.0) — position, legs, collateral
    entry, account balances and the immutable trade — so a crash is
    all-or-nothing and there is no partial state to reason about. The caller owns
    the commit boundary, one per candidate, exactly as the equity auto-simulation
    does.

    ``paper.ledger.accept_candidate`` is deliberately NOT reused: it would bring
    ``_NOMINAL_SPREAD_BPS`` and per-share sizing with it.
    """
    ensure_not_engaged()
    cand = session.get(Candidate, candidate_id)
    if cand is None:
        raise ValueError(f"candidate {candidate_id} not found")
    if cand.structure_kind != OPTIONS_STRUCTURE_KIND:
        raise OptionsAutoSimulateForbidden(
            "C", "accept_options_candidate requires a candidate carrying an options structure"
        )
    # Structural invariants are re-asserted here rather than trusted from the
    # guard, because this function is reachable from the CLI as well.
    account = resolve_options_account(session, account_name=account_name)
    if account.id != plan.account.id:
        raise OptionsAutoSimulateForbidden("N", "the plan was built against a different account")
    structure = plan.structure
    for leg in structure.legs:
        if leg.shares_per_contract != _PHASE1_SHARES_PER_CONTRACT:
            raise OptionsAutoSimulateForbidden(
                "K", f"{leg.option_ticker} carries shares_per_contract={leg.shares_per_contract}"
            )
        if leg.exercise_style != _PHASE1_EXERCISE_STYLE:
            raise OptionsAutoSimulateForbidden(
                "L", f"{leg.option_ticker} is {leg.exercise_style!r}, not american"
            )
    if plan.collateral_required > float(account.spendable_cash) + 1e-9:
        raise OptionsAutoSimulateForbidden(
            "O",
            f"collateral {plan.collateral_required:.2f} exceeds spendable cash "
            f"{float(account.spendable_cash):.2f}",
        )
    # AC — the plan must carry the sources its prices were read from, because
    # they are written on the position and every later mark reads by them.
    if not structure.option_source.strip() or not structure.underlying_source.strip():
        raise OptionsAutoSimulateForbidden(
            "AC",
            "the plan records no price-source provenance (option_source="
            f"{structure.option_source!r}, underlying_source={structure.underlying_source!r})",
        )
    if structure.underlying_source != pricing.underlying_source:
        raise OptionsAutoSimulateForbidden(
            "AC",
            f"the plan's spot source {structure.underlying_source!r} is not the pricing "
            f"context's {pricing.underlying_source!r}",
        )

    now = utcnow()
    inst = session.get(Instrument, cand.instrument_id)
    assert inst is not None
    position = OptionsPosition(
        account_id=account.id,
        candidate_id=cand.id,
        strategy_version_id=cand.strategy_version_id,
        underlying_instrument_id=inst.id,
        underlying_symbol=structure.underlying_symbol,
        structure_type=structure.structure_type,
        contracts=structure.contracts,
        entry_net_premium=_money(plan.fill.cash),
        entry_costs=_money(plan.fill.transaction_costs),
        r_dollars=_money(plan.r_dollars),
        collateral_reserved=_money(plan.collateral_required),
        strike_width=structure.strike_width,
        expiration_date=structure.expiration,
        dte_at_entry=plan.dte_at_entry,
        profit_target_pct_of_credit=plan.shaping.profit_target_pct_of_credit,
        stop_multiple_of_credit=plan.shaping.stop_multiple_of_credit,
        time_stop_dte=plan.shaping.time_stop_dte,
        signal_session=plan.signal_session,
        fill_session=plan.fill_session,
        opened_at=now,
        fill_model=FILL_MODEL[:200],
        iv_source=pricing.iv_source,
        q_source=pricing.q_source,
        greeks_source=pricing.greeks_source,
        option_source=structure.option_source[:40],
        underlying_source=structure.underlying_source[:40],
    )
    session.add(position)
    session.flush()

    sides = structure.contract_sides
    for leg in structure.legs:
        f = plan.fill.fills[leg.option_ticker]
        q = plan.quotes[leg.option_ticker]
        units = abs(leg.qty_signed) * leg.shares_per_contract * structure.contracts
        session.add(
            OptionsPositionLeg(
                position_id=position.id,
                option_contract_id=leg.option_contract_id,
                option_ticker=leg.option_ticker,
                right=leg.right,
                strike=leg.strike,
                expiration_date=leg.expiration,
                qty_signed=leg.qty_signed,
                shares_per_contract=leg.shares_per_contract,
                exercise_style=leg.exercise_style,
                entry_print=_money(q.print_close or 0.0),
                entry_price=_money(f.price),
                entry_spread_cost=_money(abs(f.price - (q.print_close or 0.0)) * units),
                entry_commission=_money(
                    (plan.fill.commission + plan.fill.fees)
                    * (abs(leg.qty_signed) * structure.contracts)
                    / sides
                    if sides
                    else 0.0
                ),
            )
        )

    # Cash first, then the reservation: the credit lands in cash and the gross
    # requirement is reserved, so spendable_cash falls by exactly R (D3 §8.0).
    account.cash = account.cash + _money(plan.fill.cash - plan.fill.commission - plan.fill.fees)
    basis = collateral_basis(
        structure,
        net_credit_received=plan.fill.cash,
        entry_costs=plan.fill.transaction_costs,
    )
    reserve_collateral(
        session,
        account,
        position,
        amount=_money(plan.collateral_required),
        basis=basis,
        as_of=plan.fill_session,
    )

    snapshot = options_candidate_snapshot(
        session,
        cand,
        account=account,
        structure=structure,
        plan=plan,
        limits=plan.limits,
        pricing=pricing,
    ) | {"decision": {"actor": actor, "note": note, "automatic": actor.endswith("auto_simulate")}}
    trade = OptionsTrade(
        account_id=account.id,
        candidate_id=cand.id,
        options_position_id=position.id,
        strategy_version_id=cand.strategy_version_id,
        decision=PaperDecision.ACCEPTED,
        structure_type=structure.structure_type,
        underlying_symbol=structure.underlying_symbol,
        signal_snapshot_json=snapshot,
        plan_json={
            "structure_type": structure.structure_type,
            "contracts": structure.contracts,
            "legs": [leg.option_ticker for leg in structure.legs],
            "profit_target_pct_of_credit": plan.shaping.profit_target_pct_of_credit,
            "stop_multiple_of_credit": plan.shaping.stop_multiple_of_credit,
            "time_stop_dte": plan.shaping.time_stop_dte,
        },
        why_qualified="; ".join(cand.reasons_qualify),
        why_might_fail="; ".join(cand.reasons_fail),
        r_dollars=_money(plan.r_dollars),
        collateral_reserved=_money(plan.collateral_required),
        actor=actor,
        note=note,
        created_at=now,
    )
    session.add(trade)
    session.flush()
    _log.info(
        "paper.options_accept",
        candidate=candidate_id,
        position=position.id,
        symbol=structure.underlying_symbol,
        r=round(plan.r_dollars, 2),
        collateral=round(plan.collateral_required, 2),
    )
    return AcceptOptionsResult(
        options_trade_id=trade.id,
        position_id=position.id,
        structure_type=structure.structure_type,
        contracts=structure.contracts,
        net_premium=round(plan.fill.cash, 4),
        r_dollars=round(plan.r_dollars, 4),
        collateral_reserved=round(plan.collateral_required, 4),
    )


def open_positions(session: Session, account: PaperAccount) -> Sequence[OptionsPosition]:
    return list(
        session.scalars(
            select(OptionsPosition).where(
                OptionsPosition.account_id == account.id,
                OptionsPosition.closed_at.is_(None),
            )
        )
    )
