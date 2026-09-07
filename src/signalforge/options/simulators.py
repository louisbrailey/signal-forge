"""Position payoff / risk simulators for education. Long-only or fully-collateralised.

Supported: long call, long put, covered call (long 100 shares + short 1 call),
cash-secured put (short 1 put fully cash-collateralised). NOT supported by design:
naked/uncovered short options, margin-dependent structures, spreads, 0DTE alerts.

Every result carries an explicit ``max_loss`` and the standard disclaimer. These
are hypothetical payoffs at expiration plus a Black-Scholes mark for time decay —
not a recommendation and not an order.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from signalforge.options import DISCLAIMER
from signalforge.options.blackscholes import greeks

_CONTRACT_MULTIPLIER = 100


@dataclass(frozen=True, slots=True)
class PayoffPoint:
    underlying: float
    pnl: float


@dataclass(frozen=True, slots=True)
class SimResult:
    strategy: str
    entry_cost: float  # net debit paid (negative = net credit received)
    max_loss: float  # worst case, always a finite number here (long-only/collateralised)
    max_gain: float  # may be math.inf for a long call
    break_evens: tuple[float, ...]
    payoff_at_expiry: tuple[PayoffPoint, ...]
    notes: list[str] = field(default_factory=list)
    disclaimer: str = DISCLAIMER


def _grid(center: float, span_pct: float = 0.4, n: int = 41) -> list[float]:
    lo, hi = center * (1 - span_pct), center * (1 + span_pct)
    step = (hi - lo) / (n - 1)
    return [round(lo + i * step, 4) for i in range(n)]


def long_call(spot: float, strike: float, premium: float, *, contracts: int = 1) -> SimResult:
    mult = contracts * _CONTRACT_MULTIPLIER
    cost = premium * mult
    be = strike + premium
    pts = tuple(PayoffPoint(u, round(max(u - strike, 0.0) * mult - cost, 2)) for u in _grid(spot))
    return SimResult(
        strategy="long_call",
        entry_cost=round(cost, 2),
        max_loss=round(cost, 2),
        max_gain=float("inf"),
        break_evens=(round(be, 4),),
        payoff_at_expiry=pts,
        notes=[
            f"Max loss = premium paid (${cost:,.2f}) if the underlying is <= {strike} at expiry.",
            "Unlimited theoretical upside; time decay works against the holder.",
        ],
    )


def long_put(spot: float, strike: float, premium: float, *, contracts: int = 1) -> SimResult:
    mult = contracts * _CONTRACT_MULTIPLIER
    cost = premium * mult
    be = strike - premium
    max_gain = (strike - premium) * mult  # underlying floored at 0
    pts = tuple(PayoffPoint(u, round(max(strike - u, 0.0) * mult - cost, 2)) for u in _grid(spot))
    return SimResult(
        strategy="long_put",
        entry_cost=round(cost, 2),
        max_loss=round(cost, 2),
        max_gain=round(max_gain, 2),
        break_evens=(round(be, 4),),
        payoff_at_expiry=pts,
        notes=[
            f"Max loss = premium paid (${cost:,.2f}) if the underlying is >= {strike} at expiry.",
            f"Max gain ${max_gain:,.2f} if the underlying goes to 0.",
        ],
    )


def covered_call(
    spot: float, strike: float, premium: float, *, shares_basis: float | None = None
) -> SimResult:
    """Long 100 shares + short 1 call. Fully covered — no naked exposure."""
    basis = spot if shares_basis is None else shares_basis
    mult = _CONTRACT_MULTIPLIER
    net_debit = basis * mult - premium * mult  # cash outlay
    be = basis - premium
    capped_value = strike * mult
    max_gain = capped_value + premium * mult - basis * mult
    max_loss = net_debit  # if the underlying goes to 0
    pts = tuple(
        PayoffPoint(
            u,
            round(min(u, strike) * mult + premium * mult - basis * mult, 2),
        )
        for u in _grid(spot)
    )
    return SimResult(
        strategy="covered_call",
        entry_cost=round(net_debit, 2),
        max_loss=round(max_loss, 2),
        max_gain=round(max_gain, 2),
        break_evens=(round(be, 4),),
        payoff_at_expiry=pts,
        notes=[
            f"Upside capped at strike {strike}; keeps the ${premium * mult:,.2f} premium.",
            f"Max loss ${max_loss:,.2f} if the underlying goes to 0 (same as owning the stock, "
            "less the premium).",
        ],
    )


def cash_secured_put(spot: float, strike: float, premium: float) -> SimResult:
    """Short 1 put, fully collateralised with ``strike * 100`` cash. No margin."""
    mult = _CONTRACT_MULTIPLIER
    collateral = strike * mult
    credit = premium * mult
    be = strike - premium
    max_gain = credit
    max_loss = collateral - credit  # underlying to 0, assigned at strike
    pts = tuple(PayoffPoint(u, round(credit - max(strike - u, 0.0) * mult, 2)) for u in _grid(spot))
    return SimResult(
        strategy="cash_secured_put",
        entry_cost=round(-credit, 2),  # net credit
        max_loss=round(max_loss, 2),
        max_gain=round(max_gain, 2),
        break_evens=(round(be, 4),),
        payoff_at_expiry=pts,
        notes=[
            f"Collateral held: ${collateral:,.2f} (fully cash-secured, no margin).",
            f"Max gain ${credit:,.2f} (keep the premium) if underlying >= {strike} at expiry.",
            f"Max loss ${max_loss:,.2f} if the underlying goes to 0.",
        ],
    )


@dataclass(frozen=True, slots=True)
class DecayPoint:
    days_to_expiry: int
    mark: float
    theta_per_day: float


def time_decay_curve(
    spot: float,
    strike: float,
    iv: float,
    days_to_expiry: int,
    *,
    call: bool,
    r: float = 0.04,
    q: float = 0.0,
) -> list[DecayPoint]:
    """Black-Scholes mark and per-day theta as expiry approaches (education).

    ``iv`` is an input assumption, not a vendor number.
    """
    out: list[DecayPoint] = []
    for d in range(max(days_to_expiry, 1), 0, -1):
        g = greeks(spot, strike, d / 365.0, r, iv, call=call, q=q)
        out.append(DecayPoint(d, round(g.price, 4), round(g.theta_per_day, 4)))
    return out
