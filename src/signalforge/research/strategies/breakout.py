"""Strategy 4 (Phase 2) — volatility-contraction range breakout (SHORT_SWING, MEDIUM_SWING).

When realised volatility has been contracting (short ATR well below long ATR) and
price breaks the Donchian channel, take the breakout in the regime's direction.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from signalforge.backtest.engine import EntrySignal
from signalforge.data.series import PriceSeries
from signalforge.domain import Direction, Horizon
from signalforge.gitinfo import git_sha
from signalforge.research.features.daily import atr, atr_contraction, donchian_high, donchian_low
from signalforge.research.regime import Trend
from signalforge.research.registry import StrategySpec, StrategyStatus
from signalforge.research.strategies.base import StrategyContext

VERSION = "0.1.0"


@dataclass(frozen=True, slots=True)
class BreakoutParams:
    channel: int = 20
    contraction_max: float = 0.75  # ATR(10)/ATR(50) must be <= this (vol squeezing)
    atr_window: int = 14
    stop_atr: float = 1.75
    target_atr: float = 3.5
    time_stop_short: int = 10
    time_stop_medium: int = 40


class VolatilityBreakout:
    def __init__(
        self, horizon: Horizon = Horizon.SHORT_SWING, params: BreakoutParams | None = None
    ) -> None:
        if horizon not in (Horizon.SHORT_SWING, Horizon.MEDIUM_SWING):
            raise ValueError("VolatilityBreakout supports SHORT_SWING or MEDIUM_SWING")
        self.horizon = horizon
        self.params = params or BreakoutParams()
        self.key = f"volatility_breakout.{horizon.value.lower()}"

    def _time_stop(self) -> int:
        p = self.params
        return p.time_stop_medium if self.horizon is Horizon.MEDIUM_SWING else p.time_stop_short

    def spec(self) -> StrategySpec:
        p = self.params
        return StrategySpec(
            name=self.key,
            version=VERSION,
            git_sha=git_sha(),
            horizon=self.horizon,
            rule_definition=(
                f"When ATR(10)/ATR(50) <= {p.contraction_max} (volatility contracting) and price "
                f"closes above the {p.channel}-day Donchian high, go LONG (SHORT on a break of the "
                "Donchian low when shorts are enabled and the regime is BEAR). ATR stop and target."
            ),
            required_data_sources=("BAR_DAILY",),
            feature_definitions=(
                "contraction = ATR(10) / ATR(50)",
                f"donchian_high({p.channel}) / donchian_low({p.channel}) (excluding today)",
                f"atr = ATR({p.atr_window})",
            ),
            entry_conditions="contraction <= contraction_max and close beyond the Donchian edge",
            invalidation_conditions="close back inside the channel",
            exit_logic=f"target = entry +/- {p.target_atr} * ATR({p.atr_window})",
            stop_logic=f"stop = entry -/+ {p.stop_atr} * ATR({p.atr_window})",
            time_stop=f"{self._time_stop()} sessions",
            liquidity_requirements="see ResearchConfig.liquidity",
            event_filters="excluded earnings window from ResearchConfig.events",
            assumed_transaction_costs="ResearchConfig commission model (default 0)",
            slippage_model="ResearchConfig slippage_bps + half spread",
            permits_long=True,
            permits_short=True,
            known_failure_modes=(
                "false breakout / immediate reversal back into the range",
                "contraction filter admits low-volume drift that fails to follow through",
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
        contraction = atr_contraction(series, t, 10, 50)
        dc_hi = donchian_high(series, t, p.channel)
        dc_lo = donchian_low(series, t, p.channel)
        a = atr(series, t, p.atr_window)
        if any(math.isnan(x) for x in (contraction, dc_hi, dc_lo, a)) or a <= 0:
            return None
        if contraction > p.contraction_max:
            return None
        close = float(series.close[t])

        if close > dc_hi and not ctx.regime.risk_off:
            return EntrySignal(
                direction=Direction.LONG,
                stop_price=close - p.stop_atr * a,
                target_price=close + p.target_atr * a,
                time_stop_bars=self._time_stop(),
                reason=(
                    f"vol contraction {contraction:.2f} <= {p.contraction_max}; "
                    f"close {close:.2f} > {p.channel}d Donchian high {dc_hi:.2f}"
                ),
            )
        if ctx.allow_short and close < dc_lo and ctx.regime.trend is Trend.BEAR:
            return EntrySignal(
                direction=Direction.SHORT,
                stop_price=close + p.stop_atr * a,
                target_price=close - p.target_atr * a,
                time_stop_bars=self._time_stop(),
                reason=(
                    f"vol contraction {contraction:.2f}; close {close:.2f} < "
                    f"{p.channel}d Donchian low {dc_lo:.2f}; regime bear"
                ),
            )
        return None
