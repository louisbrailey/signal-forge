"""Closed-form Black-Scholes-Merton price, Greeks, and implied volatility.

Education only. Assumes European exercise, continuous dividend yield ``q``,
constant vol and rate. All outputs are **computed locally** — they are never
presented as vendor Greeks or vendor implied volatility.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

_SQRT_2PI = math.sqrt(2.0 * math.pi)


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / _SQRT_2PI


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


@dataclass(frozen=True, slots=True)
class Greeks:
    price: float
    delta: float
    gamma: float
    vega: float  # per 1.00 (100 vol points) change in sigma
    theta: float  # per calendar year
    rho: float  # per 1.00 change in r

    @property
    def theta_per_day(self) -> float:
        return self.theta / 365.0

    @property
    def vega_per_vol_point(self) -> float:
        return self.vega / 100.0


def _d1_d2(s: float, k: float, t: float, r: float, sigma: float, q: float) -> tuple[float, float]:
    vol_sqrt_t = sigma * math.sqrt(t)
    d1 = (math.log(s / k) + (r - q + 0.5 * sigma * sigma) * t) / vol_sqrt_t
    return d1, d1 - vol_sqrt_t


def price(
    s: float, k: float, t: float, r: float, sigma: float, *, call: bool, q: float = 0.0
) -> float:
    """Black-Scholes price. ``t`` in years; ``r``/``q``/``sigma`` annualised decimals."""
    if t <= 0 or sigma <= 0:
        intrinsic = (s - k) if call else (k - s)
        return max(intrinsic, 0.0)
    d1, d2 = _d1_d2(s, k, t, r, sigma, q)
    disc_r, disc_q = math.exp(-r * t), math.exp(-q * t)
    if call:
        return s * disc_q * _norm_cdf(d1) - k * disc_r * _norm_cdf(d2)
    return k * disc_r * _norm_cdf(-d2) - s * disc_q * _norm_cdf(-d1)


def greeks(
    s: float, k: float, t: float, r: float, sigma: float, *, call: bool, q: float = 0.0
) -> Greeks:
    px = price(s, k, t, r, sigma, call=call, q=q)
    if t <= 0 or sigma <= 0:
        delta = (1.0 if s > k else 0.0) if call else (-1.0 if s < k else 0.0)
        return Greeks(px, delta, 0.0, 0.0, 0.0, 0.0)
    d1, d2 = _d1_d2(s, k, t, r, sigma, q)
    disc_r, disc_q = math.exp(-r * t), math.exp(-q * t)
    pdf_d1 = _norm_pdf(d1)
    sqrt_t = math.sqrt(t)
    delta = disc_q * (_norm_cdf(d1) if call else _norm_cdf(d1) - 1.0)
    gamma = disc_q * pdf_d1 / (s * sigma * sqrt_t)
    vega = s * disc_q * pdf_d1 * sqrt_t
    if call:
        theta = (
            -s * disc_q * pdf_d1 * sigma / (2.0 * sqrt_t)
            - r * k * disc_r * _norm_cdf(d2)
            + q * s * disc_q * _norm_cdf(d1)
        )
        rho = k * t * disc_r * _norm_cdf(d2)
    else:
        theta = (
            -s * disc_q * pdf_d1 * sigma / (2.0 * sqrt_t)
            + r * k * disc_r * _norm_cdf(-d2)
            - q * s * disc_q * _norm_cdf(-d1)
        )
        rho = -k * t * disc_r * _norm_cdf(-d2)
    return Greeks(px, delta, gamma, vega, theta, rho)


def implied_vol(
    target_price: float,
    s: float,
    k: float,
    t: float,
    r: float,
    *,
    call: bool,
    q: float = 0.0,
    tol: float = 1e-6,
    max_iter: int = 100,
) -> float | None:
    """Solve for sigma via bisection. Returns ``None`` if the price is outside
    the no-arbitrage band or does not converge (education, not a vendor IV)."""
    if t <= 0 or target_price <= 0:
        return None
    lo_bound = price(s, k, t, r, 1e-6, call=call, q=q)
    hi_bound = price(s, k, t, r, 5.0, call=call, q=q)
    if not (lo_bound - tol <= target_price <= hi_bound + tol):
        return None
    lo, hi = 1e-6, 5.0
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        diff = price(s, k, t, r, mid, call=call, q=q) - target_price
        if abs(diff) < tol:
            return mid
        if diff > 0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)
