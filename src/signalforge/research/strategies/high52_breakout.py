"""Round 2, family E1 — 52-week-high breakout (MEDIUM_SWING).

Pre-registered 2026-11-03 in ``docs/research/PREREGISTRATION_round2_2026-11-03.md``
§1 (R2-E1) before any bar was backtested. Published basis: George & Hwang,
"The 52-Week High and Momentum Investing," Journal of Finance 59(5) 2004 —
nearness to the 52-week high predicts returns better than past returns and
the effect does not reverse long-run (investors anchor on the high and
under-react to news). This is the single-name, time-series form of that
anchor: a close through the prior 252-session high, confirmed by volume,
with the market regime not risk-off.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from signalforge.backtest.engine import EntrySignal
from signalforge.data.series import PriceSeries
from signalforge.domain import Direction, Horizon
from signalforge.gitinfo import git_sha
from signalforge.research.features.daily import atr, donchian_high, volume_ratio
from signalforge.research.registry import StrategySpec, StrategyStatus
from signalforge.research.strategies.base import StrategyContext

VERSION = "0.1.0"


@dataclass(frozen=True, slots=True)
class High52Params:
    lookback: int = 252  # sessions in the "52-week" window (prior bars, today excluded)
    vol_window: int = 20
    vol_mult: float = 1.3
    atr_window: int = 14
    stop_atr: float = 2.0
    target_atr: float = 4.0
    time_stop_bars: int = 40


class High52Breakout:
    horizon = Horizon.MEDIUM_SWING

    def __init__(self, params: High52Params | None = None) -> None:
        self.params = params or High52Params()
        self.key = "high52_breakout.medium_swing"

    def spec(self) -> StrategySpec:
        p = self.params
        return StrategySpec(
            name=self.key,
            version=VERSION,
            git_sha=git_sha(),
            horizon=self.horizon,
            rule_definition=(
                f"LONG when close > the highest high of the prior {p.lookback} sessions (a new "
                f"52-week high), today's volume >= {p.vol_mult}x its {p.vol_window}-session "
                "average, and the market regime is not risk-off. Long only."
            ),
            required_data_sources=("BAR_DAILY",),
            feature_definitions=(
                f"high52=donchian_high({p.lookback}) (prior bars, today excluded)",
                f"vol_ratio=volume(t)/mean(volume,{p.vol_window})",
                f"atr=ATR({p.atr_window})",
            ),
            entry_conditions="close > high52 and vol_ratio >= vol_mult and not risk_off",
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
                "false breakout that closes back inside the range",
                "late-cycle breakouts into a regime turn",
                "gap through the stop",
            ),
            test_date_range="set per backtest run",
            in_sample_period="first 60% of the available history",
            out_of_sample_period="last 40% of the available history",
            walkforward_result_ref=f"reports/{self.key}-{VERSION}.md",
            status=StrategyStatus.EXPERIMENTAL,
            notes="Pre-registered 2026-11-03: PREREGISTRATION_round2_2026-11-03.md §1 R2-E1",
        )

    def evaluate(self, series: PriceSeries, t: int, ctx: StrategyContext) -> EntrySignal | None:
        p = self.params
        hi = donchian_high(series, t, p.lookback)
        vr = volume_ratio(series, t, p.vol_window)
        a = atr(series, t, p.atr_window)
        if any(math.isnan(x) for x in (hi, vr, a)) or a <= 0:
            return None
        close = float(series.close[t])
        if close > hi and vr >= p.vol_mult and not ctx.regime.risk_off:
            return EntrySignal(
                direction=Direction.LONG,
                stop_price=close - p.stop_atr * a,
                target_price=close + p.target_atr * a,
                time_stop_bars=p.time_stop_bars,
                reason=f"close {close:.2f} > {p.lookback}-session high {hi:.2f}; vol {vr:.2f}x",
            )
        return None
