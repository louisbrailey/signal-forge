"""Strategy 3 (Phase 2) — relative-strength / momentum continuation (MEDIUM_SWING, POSITION).

LONG a name whose trailing return meaningfully beats the market proxy over the
same window, while it holds above its long SMA and the regime is bullish. This is
a lightweight proxy-relative version of cross-sectional momentum — the strategy
sees one symbol at a time, so "relative" is measured against the market return
carried on the regime state, not a universe rank.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from signalforge.backtest.engine import EntrySignal
from signalforge.data.series import PriceSeries
from signalforge.domain import Direction, Horizon
from signalforge.gitinfo import git_sha
from signalforge.research.features.daily import atr, rolling_return, sma
from signalforge.research.regime import Trend
from signalforge.research.registry import StrategySpec, StrategyStatus
from signalforge.research.strategies.base import StrategyContext

VERSION = "0.1.0"


@dataclass(frozen=True, slots=True)
class RelativeStrengthParams:
    lookback: int = 63  # ~one quarter
    excess_return_min: float = 0.05  # must beat the proxy by >= 5 pts over the window
    sma_window: int = 100
    atr_window: int = 14
    stop_atr: float = 2.5
    target_atr: float = 5.0
    time_stop_short: int = 40
    time_stop_position: int = 126


class RelativeStrength:
    def __init__(
        self, horizon: Horizon = Horizon.MEDIUM_SWING, params: RelativeStrengthParams | None = None
    ) -> None:
        if horizon not in (Horizon.MEDIUM_SWING, Horizon.POSITION):
            raise ValueError("RelativeStrength supports MEDIUM_SWING or POSITION")
        self.horizon = horizon
        self.params = params or RelativeStrengthParams()
        self.key = f"relative_strength.{horizon.value.lower()}"

    def _time_stop(self) -> int:
        p = self.params
        return p.time_stop_position if self.horizon is Horizon.POSITION else p.time_stop_short

    def spec(self) -> StrategySpec:
        p = self.params
        return StrategySpec(
            name=self.key,
            version=VERSION,
            git_sha=git_sha(),
            horizon=self.horizon,
            rule_definition=(
                f"LONG when the {p.lookback}-session return exceeds the market proxy's return "
                f"over the same window by at least {p.excess_return_min:.0%}, price is above "
                f"SMA({p.sma_window}), and the regime trend is BULL. Long only."
            ),
            required_data_sources=("BAR_DAILY",),
            feature_definitions=(
                f"ret = rolling_return(close, {p.lookback})",
                "market_ret = regime.market_ret_63d",
                f"sma = SMA(close, {p.sma_window})",
                f"atr = ATR({p.atr_window})",
            ),
            entry_conditions=(
                "ret - market_ret >= excess_return_min and close > sma and regime BULL"
            ),
            invalidation_conditions="close back below SMA(window) or relative strength decays",
            exit_logic=f"target = entry + {p.target_atr} * ATR({p.atr_window})",
            stop_logic=f"stop = entry - {p.stop_atr} * ATR({p.atr_window})",
            time_stop=f"{self._time_stop()} sessions",
            liquidity_requirements="see ResearchConfig.liquidity",
            event_filters="excluded earnings window from ResearchConfig.events",
            assumed_transaction_costs="ResearchConfig commission model (default 0)",
            slippage_model="ResearchConfig slippage_bps + half spread",
            permits_long=True,
            permits_short=False,
            known_failure_modes=(
                "momentum crash / sharp mean reversion of winners",
                "proxy-relative strength is not cross-sectional rank",
                "regime flips bull->bear mid-hold",
            ),
            test_date_range="set per backtest run",
            in_sample_period="first 60% of the available history",
            out_of_sample_period="last 40% of the available history",
            walkforward_result_ref=f"reports/{self.key}-{VERSION}.md",
            status=StrategyStatus.EXPERIMENTAL,
        )

    def evaluate(self, series: PriceSeries, t: int, ctx: StrategyContext) -> EntrySignal | None:
        p = self.params
        ret = rolling_return(series, t, p.lookback)
        mean = sma(series, t, p.sma_window)
        a = atr(series, t, p.atr_window)
        market_ret = ctx.regime.market_ret_63d
        if market_ret is None or any(math.isnan(x) for x in (ret, mean, a)) or a <= 0:
            return None
        close = float(series.close[t])
        if (
            ret - market_ret >= p.excess_return_min
            and close > mean
            and ctx.regime.trend is Trend.BULL
        ):
            return EntrySignal(
                direction=Direction.LONG,
                stop_price=close - p.stop_atr * a,
                target_price=close + p.target_atr * a,
                time_stop_bars=self._time_stop(),
                reason=(
                    f"{p.lookback}d return {ret:+.1%} vs market {market_ret:+.1%} "
                    f"(+{ret - market_ret:.1%}); close > SMA{p.sma_window}; regime bull"
                ),
            )
        return None
