"""Print-based fill model for the options engine (D2 §6, §10.3).

The whole model rests on one fact: ``OptionAggregateDaily.close`` is a **last-trade
print**.  There is no bid, no ask, and no mid anywhere in the schema, and
``/v3/quotes/{O:contract}`` returns 403 on this entitlement in 7 of 7 checks — as
does ``/v3/quotes/{sym}`` for equities.  So the spread is *modelled*, never
observed, on both asset classes, and every report must say so.

Rules implemented here:

* **Print, not mid, and a full spread per leg per side** (D2 §6.2).  The print's
  position inside the true spread is unknown, so half-spreading it is arbitrary
  *in sign*; the conservative assumption is that it sat at the favourable touch
  and the fill must cross the whole way.  A 2-leg vertical therefore pays a full
  modelled spread **four times** round trip.  This is deliberately a *different*
  convention from the equity engine's half-spread (``engine.py:94``), and the two
  are not comparable — every report names which it used.
* **A sale's proceeds are floored at zero** and never negative; a buy needs no
  upper bound, because paying more is always the conservative direction (D2 §6.3).
* **Rounding is away from the engine** — up on a buy, down on a sale — so
  rounding can never improve a fill.
* **The intrinsic floor is asymmetric** (D2 §10.3): it applies to a leg being
  *bought back* only.  Applying it to a leg being *sold* would raise assumed
  proceeds above the last print, which is favourable to the strategy, not
  conservative.
* **A** :class:`~signalforge.data.option_chain.Mark` **cannot be filled on.**  The
  type is refused at the door as well as by mypy.
* :class:`IvSource` has **no** ``realized_vol`` member, and that is structural
  (D2 §6.6 rule 4): for a premium-selling strategy realised vol sits below implied
  on average, so marking unsold short premium at realised vol would inflate
  simulated credit capture on exactly the trades the strategy claims as its edge.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from signalforge.backtest.options_costs import OptionCostModel, Side
from signalforge.data.option_chain import ContractPrint, Mark, Right
from signalforge.options import blackscholes

#: Recorded verbatim on every options evaluation (D2 §14.3, D4 gate 0.f).
FILL_MODEL = (
    "print_not_mid; full_modelled_spread_per_leg_per_side; close_basis_stop; "
    "NBBO unavailable under the active entitlement for options AND equities — "
    "spread is modelled, not observed; PLACEHOLDER spread proxy — not yet calibrated"
)


class IvSource(StrEnum):
    """Where an implied vol came from.  ``realized_vol`` is deliberately absent."""

    LOCAL_BS_INVERTED = "local_bs_inverted"
    SAME_SESSION_SURFACE = "same_session_surface"
    VENDOR = "vendor"
    PCT_OTM_PROXY = "pct_otm_proxy"


class ZeroSpreadRefused(ValueError):
    """A cost model that is non-zero in the constructor but zero in practice.

    ``spread_pct_of_last_print * 0.0`` against a zero floor is the same defect one
    layer down, and the constructor check cannot see it (D2 §7.4 rule 3).
    """


@dataclass(frozen=True, slots=True)
class LegFill:
    """One leg-side's modelled fill, with the diagnostics gate 8 requires."""

    price: float
    spread: float
    side: Side
    spread_ge_print: bool
    proceeds_floored_at_zero: bool
    intrinsic_floor_applied: bool
    intrinsic_gap: float  # sale proceeds shortfall vs intrinsic; 0.0 on a buy


def moneyness(underlying_close: float, strike: float) -> float:
    """``strike / underlying_close``.  Carried into ``spread()``'s signature only."""
    if underlying_close <= 0.0:
        raise ValueError("underlying_close must be > 0 to express moneyness")
    return strike / underlying_close


def intrinsic_per_share(underlying_close: float, strike: float, right: Right) -> float:
    """``max(S - K, 0)`` for a call, ``max(K - S, 0)`` for a put.

    Delegated to :func:`signalforge.options.blackscholes.price` at ``t = 0``, which
    already returns ``max(intrinsic, 0.0)`` — the convention is encoded once in the
    shared math module rather than re-derived here (D2 §10.3).
    """
    return blackscholes.price(
        underlying_close, strike, 0.0, 0.0, 0.0, call=right is Right.CALL, q=0.0
    )


def mark_from_iv(
    underlying_close: float,
    strike: float,
    t_years: float,
    r: float,
    sigma: float,
    *,
    right: Right,
    q: float,
    iv_source: IvSource,
) -> Mark:
    """A modelled per-share value for a contract that did not print.

    Returns a :class:`Mark`, which the fill path refuses by type: a ``Mark`` feeds
    reported unrealised diagnostics **only** — never an exit trigger, never R,
    never realised P&L, never a gated statistic (D2 §6.4).
    """
    value = blackscholes.price(
        underlying_close, strike, t_years, r, sigma, call=right is Right.CALL, q=q
    )
    return Mark(value=value, iv_source=iv_source.value)


def adverse_fill(
    print_: ContractPrint,
    cost_model: OptionCostModel,
    *,
    side: Side,
    strike: float,
    right: Right,
    underlying_close: float,
    dte: int,
    apply_intrinsic_floor: bool = False,
) -> LegFill:
    """Per-share modelled fill for one leg-side, crossing the whole modelled spread.

    ``apply_intrinsic_floor`` is honoured on a :attr:`Side.BUY` only; on a sale it
    is ignored by design (D2 §10.3) and the shortfall against intrinsic is
    reported instead as :attr:`LegFill.intrinsic_gap`, so the size of that
    conservatism is a number in the record rather than an unexamined consequence
    of a sign convention.
    """
    if isinstance(print_, Mark):  # pragma: no cover - defended by mypy too
        raise TypeError("a Mark can never be filled on; fills require a ContractPrint")

    last = print_.last_print
    spread = cost_model.spread(last, moneyness=moneyness(underlying_close, strike), dte=dte)
    if spread <= 0.0:
        raise ZeroSpreadRefused(
            f"cost model returned a zero spread for a priced leg (last_print={last!r})"
        )
    intrinsic = intrinsic_per_share(underlying_close, strike, right)
    spread_ge_print = spread >= last

    if side is Side.BUY:
        base = max(intrinsic, last) if apply_intrinsic_floor else last
        raw = base + spread
        return LegFill(
            price=cost_model.round_to_tick(raw, side=Side.BUY),
            spread=spread,
            side=side,
            spread_ge_print=spread_ge_print,
            proceeds_floored_at_zero=False,
            intrinsic_floor_applied=apply_intrinsic_floor and intrinsic > last,
            intrinsic_gap=0.0,
        )

    raw = last - spread
    floored = raw < 0.0
    price = cost_model.round_to_tick(max(raw, 0.0), side=Side.SELL)
    price = max(price, 0.0)
    return LegFill(
        price=price,
        spread=spread,
        side=side,
        spread_ge_print=spread_ge_print,
        proceeds_floored_at_zero=floored,
        intrinsic_floor_applied=False,
        intrinsic_gap=max(intrinsic - price, 0.0),
    )
