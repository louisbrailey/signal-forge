"""R1 offline challengers. Never imported by the operating strategy registry."""

from __future__ import annotations

import math
from calendar import monthrange
from dataclasses import replace
from datetime import date
from functools import lru_cache

import numpy as np

from signalforge.backtest.engine import EntrySignal
from signalforge.data.calendar import sessions
from signalforge.domain import Direction
from signalforge.research.features.daily import atr, sma

CONFIRM = {"mean_reversion", "volatility_breakout"}
EXTENSION = {"trend_continuation", "relative_strength", "high52_breakout", "trend_pullback"}


def refinement_kind(key):
    family = key.split(".")[0]
    if family in CONFIRM:
        return "one_session_confirmation"
    if family in EXTENSION:
        return "one_atr_extension_limit"
    if family == "tsmom_etf":
        return "benchmark_above_sma200"
    if family == "turn_of_month":
        return "instrument_above_sma200"
    raise ValueError(f"No predeclared refinement for {key}")


def refined_signal(base, key, market_up):
    kind = refinement_kind(key)

    def signal(series, t):
        # Defensive prefixing also protects callers outside the funded engine.
        if not 0 <= t < len(series):
            raise ValueError("Invalid decision index")
        visible = series.head(t)
        close = float(visible.close[t])
        if not math.isfinite(close) or close <= 0:
            return None
        if kind == "one_session_confirmation":
            if t == 0:
                return None
            prior = base(visible.head(t - 1), t - 1)
            if prior is None or prior.direction is not Direction.LONG or prior.time_stop_bars <= 1:
                return None
            if not math.isfinite(prior.stop_price) or not close > prior.stop_price:
                return None
            if prior.target_price is not None and (
                not math.isfinite(prior.target_price) or not close < prior.target_price
            ):
                return None
            if not close > float(visible.close[t - 1]):
                return None
            return replace(
                prior,
                time_stop_bars=prior.time_stop_bars - 1,
                reason=prior.reason + "; R1: completed next-session close confirms recovery",
            )
        original = base(visible, t)
        if original is None or original.direction is not Direction.LONG:
            return None
        if kind == "one_atr_extension_limit":
            average, volatility = sma(visible, t, 20), atr(visible, t, 14)
            if not (math.isfinite(average) and math.isfinite(volatility) and volatility > 0):
                return None
            approved = close - average <= volatility
            reason = f"close-SMA20={close - average:.6f} <= ATR14={volatility:.6f}"
        elif kind == "benchmark_above_sma200":
            approved = market_up.get(visible.dates[t], False)
            reason = "SPY close > SMA200 at decision close"
        else:
            average = sma(visible, t, 200)
            approved = math.isfinite(average) and close > average
            reason = f"close={close:.6f} > SMA200={average:.6f}"
        return replace(original, reason=original.reason + "; R1: " + reason) if approved else None

    return signal


@lru_cache(maxsize=240)
def month_end(year, month):
    days = sessions(date(year, month, 1), date(year, month, monthrange(year, month)[1]))
    return days[-1]


def simple_benchmark(series, t):
    if series.symbol != "SPY":
        return None
    visible = series.head(t)
    day = visible.dates[t]
    if day != month_end(day.year, day.month):
        return None
    average, volatility = sma(visible, t, 200), atr(visible, t, 14)
    close = float(visible.close[t])
    if not all(math.isfinite(x) for x in (average, volatility, close)):
        return None
    if close <= average or volatility <= 0:
        return None
    return EntrySignal(Direction.LONG, close - 3 * volatility, 63, reason="SPY monthly SMA200")


def paired_lower_bound(candidate, baseline):
    """Fixed 3-month block bootstrap; repeated history is NOT fresh OOS evidence."""
    months = sorted(candidate)
    expected = [f"{year}-{month:02d}" for year in (2021, 2022, 2023) for month in range(1, 13)]
    if months != expected or sorted(baseline) != expected:
        raise ValueError("Complete aligned 2021-2023 monthly validation evidence required")
    differences = np.array([candidate[m] - baseline[m] for m in months], dtype=float)
    if not np.isfinite(differences).all():
        raise ValueError("Nonfinite validation evidence")
    blocks = differences.reshape(-1, 3).mean(axis=1)
    draws = np.random.default_rng(20261104).integers(0, len(blocks), size=(10000, len(blocks)))
    means = blocks[draws].mean(axis=1)
    return {
        "mean_monthly_difference_pp": float(differences.mean()),
        "lower_bound_pp": float(np.quantile(means, 0.05 / 30)),
        "lower_quantile": 0.05 / 30,
        "months": len(months),
        "blocks": len(blocks),
        "comparisons": 30,
    }
