"""Isolated monthly trend hypothesis; deliberately absent from the live registry."""

from __future__ import annotations

import math
from dataclasses import dataclass

from signalforge.backtest.engine import EntrySignal
from signalforge.data.series import PriceSeries
from signalforge.domain import Direction
from signalforge.research.features.daily import atr, rolling_return, sma

VERSION = "slow_trend.position@0.1.0"
UNIVERSE = ("SPY", "QQQ", "IWM", "DIA")


@dataclass(frozen=True, slots=True)
class SlowTrendParams:
    sma_window: int = 200
    stop_atr: float = 3.0
    holding_sessions: int = 126


def signal(
    series: PriceSeries,
    t: int,
    params: SlowTrendParams = SlowTrendParams(),
    *,
    trend_filter: bool = True,
) -> EntrySignal | None:
    if series.symbol not in UNIVERSE or t < 252:
        return None
    today, previous = series.dates[t], series.dates[t - 1]
    if (today.year, today.month) == (previous.year, previous.month):
        return None
    close = float(series.close[t])
    average = sma(series, t, params.sma_window)
    momentum = rolling_return(series, t, 252)
    volatility = atr(series, t, 14)
    if not all(math.isfinite(v) for v in (close, average, momentum, volatility)):
        return None
    stop = close - params.stop_atr * volatility
    if volatility <= 0 or stop <= 0:
        return None
    if trend_filter and not (close > average and momentum > 0):
        return None
    return EntrySignal(
        Direction.LONG,
        stop,
        params.holding_sessions,
        close + 6 * volatility,
        reason=(
            f"{VERSION}; monthly close={close:.6g}; SMA{params.sma_window}={average:.6g}; "
            f"return252={momentum:.6g}; ATR14={volatility:.6g}; trend_filter={trend_filter}. "
            "Research signal only — no order was placed."
        ),
    )
