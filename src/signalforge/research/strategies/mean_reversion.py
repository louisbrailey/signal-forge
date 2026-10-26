"""Strategy 2 — mean reversion after a statistically unusual move (SHORT_SWING)."""

from __future__ import annotations

import math
from dataclasses import dataclass

from signalforge.backtest.engine import EntrySignal
from signalforge.data.series import PriceSeries
from signalforge.domain import Direction, Horizon
from signalforge.gitinfo import git_sha
from signalforge.research.features.daily import atr, sma, zscore_last_return
from signalforge.research.regime import Trend
from signalforge.research.registry import StrategySpec, StrategyStatus
from signalforge.research.strategies.base import StrategyContext

# 0.2.0 (pre-registered 2026-10-26, docs/research/PREREGISTRATION_backtest_round_2026-10-26.md):
# adds a per-symbol long-term trend filter, close > SMA(trend_window). Only
# the filter is new; every other parameter is unchanged from 0.1.0.
VERSION = "0.2.0"


@dataclass(frozen=True, slots=True)
class MeanReversionParams:
    z_lookback: int = 20
    z_entry: float = -2.0
    sma_window: int = 20
    atr_window: int = 14
    stop_atr: float = 2.0
    time_stop_bars: int = 6
    trend_window: int = 200  # 0 disables the filter (0.1.0 behaviour; test fixtures only)


class MeanReversion:
    horizon = Horizon.SHORT_SWING
    key = "mean_reversion.short_swing"

    def __init__(self, params: MeanReversionParams | None = None) -> None:
        self.params = params or MeanReversionParams()

    def spec(self) -> StrategySpec:
        p = self.params
        return StrategySpec(
            name=self.key,
            version=VERSION,
            git_sha=git_sha(),
            horizon=self.horizon,
            rule_definition=(
                f"LONG when the 1-day return's z-score over {p.z_lookback} days is <= {p.z_entry} "
                f"and price is below SMA({p.sma_window}) but above its own SMA({p.trend_window}), "
                "unless the regime is strongly bearish. "
                "Target is a reversion to that SMA."
            ),
            required_data_sources=("BAR_DAILY",),
            feature_definitions=(
                f"z_ret = (r_t - mean(r,{p.z_lookback})) / std(r,{p.z_lookback})",
                f"sma = SMA(close,{p.sma_window})",
                f"atr = ATR({p.atr_window})",
                f"trend = SMA(close,{p.trend_window})",
            ),
            entry_conditions=(
                f"z_ret <= {p.z_entry} and close < sma and close > trend and regime not BEAR"
            ),
            invalidation_conditions=(
                "a second large down-day (z stays extended), or the trade is closed"
            ),
            exit_logic=f"target = SMA({p.sma_window}) at entry",
            stop_logic=f"stop = entry - {p.stop_atr} * ATR({p.atr_window})",
            time_stop=f"{p.time_stop_bars} sessions",
            liquidity_requirements="see ResearchConfig.liquidity",
            event_filters="excluded earnings window from ResearchConfig.events",
            assumed_transaction_costs="ResearchConfig commission model (default 0)",
            slippage_model="ResearchConfig slippage_bps + half spread",
            permits_long=True,
            permits_short=False,
            known_failure_modes=(
                "catching a falling knife in a real downtrend",
                "gap-down through the stop after a news shock",
                "regime filter too permissive near a top",
            ),
            test_date_range="set per backtest run",
            in_sample_period="first 60% of the available history",
            out_of_sample_period="last 40% of the available history",
            walkforward_result_ref=f"reports/{self.key}-{VERSION}.md",
            status=StrategyStatus.EXPERIMENTAL,
        )

    def evaluate(self, series: PriceSeries, t: int, ctx: StrategyContext) -> EntrySignal | None:
        p = self.params
        z = zscore_last_return(series, t, p.z_lookback)
        mean = sma(series, t, p.sma_window)
        trend = sma(series, t, p.trend_window) if p.trend_window > 0 else 0.0
        a = atr(series, t, p.atr_window)
        if any(math.isnan(x) for x in (z, mean, trend, a)) or a <= 0:
            return None
        close = float(series.close[t])
        if z <= p.z_entry and close < mean and close > trend and ctx.regime.trend is not Trend.BEAR:
            return EntrySignal(
                direction=Direction.LONG,
                stop_price=close - p.stop_atr * a,
                target_price=mean,
                time_stop_bars=p.time_stop_bars,
                reason=(
                    f"1-day return z={z:.2f} <= {p.z_entry}; close {close:.2f} < SMA{p.sma_window} "
                    f"{mean:.2f}; above SMA{p.trend_window} {trend:.2f}; "
                    f"regime {ctx.regime.trend.value}"
                ),
            )
        return None
