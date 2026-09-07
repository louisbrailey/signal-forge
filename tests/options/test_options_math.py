"""Black-Scholes + payoff simulators: education-only, long/collateralised, bounded loss."""

from __future__ import annotations

import math

import pytest

from signalforge.options.blackscholes import greeks, implied_vol, price
from signalforge.options.simulators import (
    cash_secured_put,
    covered_call,
    long_call,
    long_put,
    time_decay_curve,
)

R, Q = 0.04, 0.0


def test_put_call_parity_holds() -> None:
    s, k, t, sig = 100.0, 105.0, 0.5, 0.25
    c = price(s, k, t, R, sig, call=True, q=Q)
    p = price(s, k, t, R, sig, call=False, q=Q)
    lhs = c - p
    rhs = s * math.exp(-Q * t) - k * math.exp(-R * t)
    assert lhs == pytest.approx(rhs, abs=1e-9)


def test_greeks_signs_and_bounds() -> None:
    g_call = greeks(100, 100, 0.5, R, 0.3, call=True)
    g_put = greeks(100, 100, 0.5, R, 0.3, call=False)
    assert 0.0 < g_call.delta < 1.0
    assert -1.0 < g_put.delta < 0.0
    assert g_call.gamma > 0 and g_call.vega > 0
    assert g_call.theta_per_day < 0  # long option bleeds time value
    # ATM 6-month call delta is near 0.5-0.6
    assert 0.45 < g_call.delta < 0.65


def test_implied_vol_round_trips_and_rejects_arbitrage() -> None:
    px = price(100, 100, 0.4, R, 0.32, call=True)
    iv = implied_vol(px, 100, 100, 0.4, R, call=True)
    assert iv == pytest.approx(0.32, abs=1e-4)
    # a price above the underlying is impossible for a call -> None
    assert implied_vol(200.0, 100, 100, 0.4, R, call=True) is None


def test_long_call_loss_is_capped_at_premium_upside_unbounded() -> None:
    res = long_call(spot=100, strike=105, premium=2.5)
    assert res.max_loss == pytest.approx(250.0)
    assert res.max_gain == math.inf
    assert res.break_evens == (107.5,)
    assert min(p.pnl for p in res.payoff_at_expiry) == pytest.approx(-250.0)
    assert res.disclaimer == "Research signal only — no order was placed."


def test_long_put_loss_capped_gain_bounded_by_strike() -> None:
    res = long_put(spot=100, strike=95, premium=3.0)
    assert res.max_loss == pytest.approx(300.0)
    assert res.max_gain == pytest.approx((95 - 3.0) * 100)
    assert res.break_evens == (92.0,)


def test_covered_call_and_csp_have_finite_defined_loss() -> None:
    cc = covered_call(spot=100, strike=110, premium=2.0)
    assert cc.max_loss == pytest.approx(100 * 100 - 2.0 * 100)  # stock to 0, keep premium
    assert cc.max_gain == pytest.approx((110 - 100) * 100 + 2.0 * 100)

    csp = cash_secured_put(spot=100, strike=95, premium=2.5)
    assert csp.entry_cost < 0  # net credit
    assert csp.max_gain == pytest.approx(250.0)
    assert csp.max_loss == pytest.approx(95 * 100 - 250.0)
    assert any("no margin" in n for n in csp.notes)


def test_time_decay_curve_marks_decrease_toward_expiry() -> None:
    curve = time_decay_curve(spot=100, strike=100, iv=0.3, days_to_expiry=30, call=True)
    assert len(curve) == 30
    assert curve[0].days_to_expiry == 30 and curve[-1].days_to_expiry == 1
    assert curve[-1].mark < curve[0].mark  # ATM extrinsic value decays to ~0
    assert all(p.theta_per_day <= 0 for p in curve)


def test_no_naked_or_spread_helpers_are_exported() -> None:
    import signalforge.options.simulators as sim

    banned = {"naked_call", "naked_put", "short_call", "vertical_spread", "iron_condor", "zero_dte"}
    assert banned.isdisjoint(dir(sim))
