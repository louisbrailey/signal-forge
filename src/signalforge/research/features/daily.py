"""Daily-bar feature functions.

Every function takes ``(series, t)`` and reads only indices ``<= t`` (point in
time). They return ``float('nan')`` when there is not enough history, so callers
must check with ``math.isnan``.
"""

from __future__ import annotations

import numpy as np

from signalforge.data.series import PriceSeries

NAN = float("nan")


def _slice(a: np.ndarray, t: int, window: int) -> np.ndarray:
    lo = t - window + 1
    if lo < 0:
        return np.empty(0)
    return a[lo : t + 1]


def sma(series: PriceSeries, t: int, window: int) -> float:
    w = _slice(series.close, t, window)
    return float(w.mean()) if w.size == window else NAN


def ema(series: PriceSeries, t: int, window: int) -> float:
    if t + 1 < window:
        return NAN
    alpha = 2.0 / (window + 1)
    val = float(series.close[0])
    for i in range(1, t + 1):
        val = alpha * float(series.close[i]) + (1 - alpha) * val
    return val


def true_range(series: PriceSeries, t: int) -> float:
    if t < 1:
        return float(series.high[t] - series.low[t])
    prev_close = float(series.close[t - 1])
    hi, lo = float(series.high[t]), float(series.low[t])
    return max(hi - lo, abs(hi - prev_close), abs(lo - prev_close))


def atr(series: PriceSeries, t: int, window: int = 14) -> float:
    if t + 1 < window + 1:
        return NAN
    trs = [true_range(series, i) for i in range(t - window + 1, t + 1)]
    return float(np.mean(trs))


def rolling_return(series: PriceSeries, t: int, window: int) -> float:
    if t - window < 0:
        return NAN
    return float(series.close[t] / series.close[t - window] - 1.0)


def daily_returns(series: PriceSeries, t: int, lookback: int) -> np.ndarray:
    w = _slice(series.close, t, lookback + 1)
    if w.size < 2:
        return np.empty(0)
    return np.diff(w) / w[:-1]


def zscore_last_return(series: PriceSeries, t: int, lookback: int = 20) -> float:
    rets = daily_returns(series, t, lookback)
    if rets.size < lookback:
        return NAN
    mu, sd = float(rets.mean()), float(rets.std())
    if sd == 0:
        return NAN
    return (float(rets[-1]) - mu) / sd


def volume_ratio(series: PriceSeries, t: int, window: int = 20) -> float:
    w = _slice(series.volume, t, window)
    if w.size < window or w[:-1].mean() == 0:
        return NAN
    return float(series.volume[t] / w[:-1].mean())


def atr_contraction(series: PriceSeries, t: int, short_w: int = 10, long_w: int = 50) -> float:
    """ATR(short) / ATR(long); < 1 means volatility is contracting."""
    s, long_ = atr(series, t, short_w), atr(series, t, long_w)
    if long_ != long_ or long_ == 0 or s != s:
        return NAN
    return s / long_


def donchian_high(series: PriceSeries, t: int, window: int = 20) -> float:
    w = _slice(series.high, t - 1 if t > 0 else t, window)  # exclude today
    return float(w.max()) if w.size == window else NAN


def donchian_low(series: PriceSeries, t: int, window: int = 20) -> float:
    w = _slice(series.low, t - 1 if t > 0 else t, window)
    return float(w.min()) if w.size == window else NAN


def realized_vol(series: PriceSeries, t: int, window: int = 20) -> float:
    rets = daily_returns(series, t, window)
    if rets.size < window:
        return NAN
    return float(rets.std() * np.sqrt(252))
