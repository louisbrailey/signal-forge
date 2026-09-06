"""Strategy 1 — trend continuation with volume confirmation (SHORT_SWING, MEDIUM_SWING)."""

from __future__ import annotations

import math
from dataclasses import dataclass

from signalforge.backtest.engine import EntrySignal
from signalforge.data.series import PriceSeries
from signalforge.domain import Direction, Horizon
from signalforge.gitinfo import git_sha
from signalforge.research.features.daily import atr, sma, volume_ratio
from signalforge.research.regime import Trend
from signalforge.research.registry import StrategySpec, StrategyStatus
from signalforge.research.strategies.base import StrategyContext

VERSION = "0.1.0"


@dataclass(frozen=True, slots=True)
class TrendParams:
    sma_fast: int = 20
    sma_slow: int = 50
    vol_window: int = 20
    vol_mult: float = 1.3
    atr_window: int = 14
    stop_atr: float = 1.5
    target_atr: float = 3.0
    time_stop_bars: int = 10


class TrendContinuation:
    def __init__(self, horizon: Horizon = Horizon.SHORT_SWING, params: TrendParams | None = None):
        if horizon not in (Horizon.SHORT_SWING, Horizon.MEDIUM_SWING):
            raise ValueError("TrendContinuation supports SHORT_SWING or MEDIUM_SWING")
        self.horizon = horizon
        self.params = params or (
            TrendParams(time_stop_bars=40) if horizon is Horizon.MEDIUM_SWING else TrendParams()
        )
        self.key = f"trend_continuation.{horizon.value.lower()}"

    def spec(self) -> StrategySpec:
        p = self.params
        return StrategySpec(
            name=self.key,
            version=VERSION,
            git_sha=git_sha(),
            horizon=self.horizon,
            rule_definition=(
                "LONG when close > SMA(slow), SMA(fast) > SMA(slow), close > SMA(fast), and "
                f"today's volume >= {p.vol_mult}x the {p.vol_window}-day average, with the market "
                "regime not risk-off. SHORT is the mirror image and only when shorts are enabled "
                "and the regime is risk-off."
            ),
            required_data_sources=("BAR_DAILY",),
            feature_definitions=(
                f"sma_fast=SMA(close,{p.sma_fast})",
                f"sma_slow=SMA(close,{p.sma_slow})",
                f"vol_ratio=volume(t)/mean(volume,{p.vol_window})",
                f"atr=ATR({p.atr_window})",
            ),
            entry_conditions="trend alignment + volume confirmation + regime gate",
            invalidation_conditions="close back below SMA(slow)",
            exit_logic=f"target = entry + {p.target_atr} * ATR({p.atr_window})",
            stop_logic=f"stop = entry - {p.stop_atr} * ATR({p.atr_window})",
            time_stop=f"{p.time_stop_bars} sessions",
            liquidity_requirements="see ResearchConfig.liquidity (price / ADDV / spread)",
            event_filters="excluded earnings window from ResearchConfig.events",
            assumed_transaction_costs="ResearchConfig commission model (default 0)",
            slippage_model="ResearchConfig slippage_bps + half spread",
            permits_long=True,
            permits_short=True,
            known_failure_modes=(
                "whipsaw in range-bound regimes",
                "volume spike on news that reverses",
                "gap through the stop",
            ),
            test_date_range="set per backtest run",
            in_sample_period="first 60% of the available history",
            out_of_sample_period="last 40% of the available history",
            walkforward_result_ref=f"reports/{self.key}-{VERSION}.md",
            status=StrategyStatus.EXPERIMENTAL,
        )

    def evaluate(self, series: PriceSeries, t: int, ctx: StrategyContext) -> EntrySignal | None:
        p = self.params
        fast = sma(series, t, p.sma_fast)
        slow = sma(series, t, p.sma_slow)
        vr = volume_ratio(series, t, p.vol_window)
        a = atr(series, t, p.atr_window)
        if any(math.isnan(x) for x in (fast, slow, vr, a)) or a <= 0:
            return None
        close = float(series.close[t])

        long_ok = (
            close > slow
            and fast > slow
            and close > fast
            and vr >= p.vol_mult
            and not ctx.regime.risk_off
        )
        if long_ok:
            return EntrySignal(
                direction=Direction.LONG,
                stop_price=close - p.stop_atr * a,
                target_price=close + p.target_atr * a,
                time_stop_bars=p.time_stop_bars,
                reason=(
                    f"close {close:.2f} > SMA{p.sma_slow} {slow:.2f}; "
                    f"SMA{p.sma_fast} > SMA{p.sma_slow}; vol {vr:.2f}x; "
                    f"regime {ctx.regime.trend.value}/{ctx.regime.vol.value}"
                ),
            )

        short_ok = (
            ctx.allow_short
            and close < slow
            and fast < slow
            and close < fast
            and vr >= p.vol_mult
            and ctx.regime.trend is Trend.BEAR
        )
        if short_ok:
            return EntrySignal(
                direction=Direction.SHORT,
                stop_price=close + p.stop_atr * a,
                target_price=close - p.target_atr * a,
                time_stop_bars=p.time_stop_bars,
                reason=(
                    f"close {close:.2f} < SMA{p.sma_slow} {slow:.2f}; downtrend + vol {vr:.2f}x; "
                    "regime bear"
                ),
            )
        return None
