"""Market-regime filter (ARCHITECTURE.md §6.3, strategy 6).

Not a trade generator — a gating input consumed by the baseline strategies. Built
from a broad-market proxy (SPY by default): index trend (SMA-50 vs SMA-200 and
its slope), volatility (20-day realised vol vs its own trailing history), and an
optional breadth figure supplied by the scanner (share of the universe above its
50-day average).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from signalforge.data.series import PriceSeries
from signalforge.research.features.daily import realized_vol, rolling_return, sma


class Trend(StrEnum):
    BULL = "bull"
    BEAR = "bear"
    NEUTRAL = "neutral"


class Vol(StrEnum):
    LOW = "low"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class RegimeState:
    trend: Trend
    vol: Vol
    as_of: date
    breadth_pct_above_ma: float | None = None
    market_ret_20d: float | None = None  # proxy trailing 20-session return
    market_ret_63d: float | None = None  # proxy trailing ~quarter return

    @property
    def risk_off(self) -> bool:
        return self.trend is Trend.BEAR or self.vol is Vol.HIGH

    @property
    def risk_on(self) -> bool:
        return self.trend is Trend.BULL and self.vol is Vol.LOW

    def to_dict(self) -> dict[str, object]:
        return {
            "trend": self.trend.value,
            "vol": self.vol.value,
            "as_of": self.as_of.isoformat(),
            "breadth_pct_above_ma": self.breadth_pct_above_ma,
            "market_ret_20d": self.market_ret_20d,
            "market_ret_63d": self.market_ret_63d,
        }


NEUTRAL = RegimeState(Trend.NEUTRAL, Vol.LOW, date(1970, 1, 1))


def regime_from_proxy(
    proxy: PriceSeries,
    t: int,
    *,
    breadth_pct: float | None = None,
    _vol20: Sequence[float] | None = None,
) -> RegimeState:
    """Point-in-time: uses only ``proxy`` bars at indices <= ``t``.

    ``_vol20`` is ``regime_lookup``'s cache of ``realized_vol(proxy, i, 20)`` for
    every index. Each entry is the same call on the same bars, so the result is
    identical; it only stops a full-series lookup recomputing ~50 trailing vols
    per session."""
    as_of = proxy.dates[t]
    sma50 = sma(proxy, t, 50)
    sma200 = sma(proxy, t, 200)
    sma200_prev = sma(proxy, t - 10, 200) if t >= 210 else float("nan")

    trend = Trend.NEUTRAL
    if sma50 == sma50 and sma200 == sma200:  # both not NaN
        rising = (sma200_prev != sma200_prev) or (sma200 >= sma200_prev)
        if sma50 > sma200 and rising:
            trend = Trend.BULL
        elif sma50 < sma200 and not rising:
            trend = Trend.BEAR

    def vol20(i: int) -> float:
        return _vol20[i] if _vol20 is not None else realized_vol(proxy, i, 20)

    rv = vol20(t)
    hist = [vol20(i) for i in range(max(20, t - 252), t + 1, 5)]
    hist = [h for h in hist if h == h]
    vol = Vol.LOW
    if rv == rv and hist:
        median = sorted(hist)[len(hist) // 2]
        vol = Vol.HIGH if rv > median * 1.15 else Vol.LOW

    r20 = rolling_return(proxy, t, 20)
    r63 = rolling_return(proxy, t, 63)
    return RegimeState(
        trend=trend,
        vol=vol,
        as_of=as_of,
        breadth_pct_above_ma=breadth_pct,
        market_ret_20d=None if r20 != r20 else r20,
        market_ret_63d=None if r63 != r63 else r63,
    )


def regime_lookup(proxy: PriceSeries) -> dict[date, RegimeState]:
    """A per-session regime map for the backtest engine (t-relative, no look-ahead)."""
    vol20 = [realized_vol(proxy, i, 20) for i in range(len(proxy))]
    return {proxy.dates[t]: regime_from_proxy(proxy, t, _vol20=vol20) for t in range(len(proxy))}
