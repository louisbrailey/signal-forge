"""Round 2, family E2 — short-term pullback inside a long-term uptrend (SHORT_SWING).

Pre-registered 2026-11-03 in ``docs/research/PREREGISTRATION_round2_2026-11-03.md``
§1 (R2-E2) before any bar was backtested. Published basis: Jegadeesh,
"Evidence of Predictable Behavior of Security Returns," Journal of Finance
45(3) 1990 — significant negative first-order serial correlation (short-term
reversal) alongside positive twelve-month correlation. The rule buys the
short-term reversal only where the long-term trend is up: close above the
200-session average, three consecutive down closes, close below the
10-session average, regime not risk-off.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from signalforge.backtest.engine import EntrySignal
from signalforge.data.series import PriceSeries
from signalforge.domain import Direction, Horizon
from signalforge.gitinfo import git_sha
from signalforge.research.features.daily import atr, sma
from signalforge.research.registry import StrategySpec, StrategyStatus
from signalforge.research.strategies.base import StrategyContext

VERSION = "0.1.0"


@dataclass(frozen=True, slots=True)
class PullbackParams:
    sma_slow: int = 200
    sma_fast: int = 10
    down_days: int = 3
    atr_window: int = 14
    stop_atr: float = 2.0
    target_atr: float = 2.0
    time_stop_bars: int = 10


class TrendPullback:
    horizon = Horizon.SHORT_SWING

    def __init__(self, params: PullbackParams | None = None) -> None:
        self.params = params or PullbackParams()
        self.key = "trend_pullback.short_swing"

    def spec(self) -> StrategySpec:
        p = self.params
        return StrategySpec(
            name=self.key,
            version=VERSION,
            git_sha=git_sha(),
            horizon=self.horizon,
            rule_definition=(
                f"LONG when close > SMA({p.sma_slow}), the close has fallen on each of the last "
                f"{p.down_days} sessions, close < SMA({p.sma_fast}), and the market regime is "
                "not risk-off. Long only."
            ),
            required_data_sources=("BAR_DAILY",),
            feature_definitions=(
                f"sma_slow=SMA(close,{p.sma_slow})",
                f"sma_fast=SMA(close,{p.sma_fast})",
                f"down_run=close(t-k) < close(t-k-1) for k in 0..{p.down_days - 1}",
                f"atr=ATR({p.atr_window})",
            ),
            entry_conditions="uptrend + short-term pullback + regime gate",
            invalidation_conditions="stop, target or time stop",
            exit_logic=f"target = entry + {p.target_atr} * ATR({p.atr_window})",
            stop_logic=f"stop = entry - {p.stop_atr} * ATR({p.atr_window})",
            time_stop=f"{p.time_stop_bars} sessions",
            liquidity_requirements="see ResearchConfig.liquidity (price / ADDV / spread)",
            event_filters="excluded earnings window from ResearchConfig.events",
            assumed_transaction_costs="ResearchConfig commission model (default 0)",
            slippage_model="ResearchConfig slippage_bps + half spread",
            permits_long=True,
            permits_short=False,
            known_failure_modes=(
                "pullback that becomes a trend break",
                "round-trip costs exceeding a 10-session reversal edge",
                "gap through the stop",
            ),
            test_date_range="set per backtest run",
            in_sample_period="first 60% of the available history",
            out_of_sample_period="last 40% of the available history",
            walkforward_result_ref=f"reports/{self.key}-{VERSION}.md",
            status=StrategyStatus.EXPERIMENTAL,
            notes="Pre-registered 2026-11-03: PREREGISTRATION_round2_2026-11-03.md §1 R2-E2",
        )

    def evaluate(self, series: PriceSeries, t: int, ctx: StrategyContext) -> EntrySignal | None:
        p = self.params
        if t < p.down_days:
            return None
        slow = sma(series, t, p.sma_slow)
        fast = sma(series, t, p.sma_fast)
        a = atr(series, t, p.atr_window)
        if any(math.isnan(x) for x in (slow, fast, a)) or a <= 0:
            return None
        closes = series.close
        down_run = all(closes[t - k] < closes[t - k - 1] for k in range(p.down_days))
        close = float(closes[t])
        if close > slow and down_run and close < fast and not ctx.regime.risk_off:
            return EntrySignal(
                direction=Direction.LONG,
                stop_price=close - p.stop_atr * a,
                target_price=close + p.target_atr * a,
                time_stop_bars=p.time_stop_bars,
                reason=(
                    f"close {close:.2f} > SMA{p.sma_slow} {slow:.2f}; {p.down_days} down closes; "
                    f"close < SMA{p.sma_fast} {fast:.2f}"
                ),
            )
        return None
