"""Family A — diversified-ETF time-series momentum (MEDIUM_SWING).

Pre-registered 2026-11-02 in
``docs/research/PREREGISTRATION_universe_program_2026-11-02.md`` §2A BEFORE any
bar of the 10-ETF universe was backtested. Published basis: Moskowitz, Ooi &
Pedersen (JFE 2012) — the trailing 12-month return of an asset predicts its
next-month return; Hurst, Ooi & Pedersen (JPM 2017) — the same across a
century and four asset classes; Faber (JWM 2007) — price above its 10-month
moving average as the long/flat filter.

What the engine can and cannot express, stated rather than tuned around: the
literature sizes positions by volatility and rebalances monthly; this engine
takes a fixed-risk position with a disaster stop and a 21-session time stop,
re-decided at the next month end. Cash yield is not subtracted from the
12-month return.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from signalforge.backtest.engine import EntrySignal
from signalforge.data.series import PriceSeries
from signalforge.domain import Direction, Horizon
from signalforge.gitinfo import git_sha
from signalforge.research.features.daily import atr, rolling_return, sma
from signalforge.research.registry import StrategySpec, StrategyStatus
from signalforge.research.strategies.base import StrategyContext
from signalforge.research.strategies.calendar_rules import is_last_session_of_month

VERSION = "0.1.0"


@dataclass(frozen=True, slots=True)
class TsmomParams:
    lookback: int = 252  # 12 months of sessions (MOP 2012)
    sma_window: int = 210  # Faber's 10-month SMA in sessions
    atr_window: int = 20
    stop_atr: float = 3.0  # disaster stop only
    time_stop_bars: int = 21  # one month; re-decided at the next month end


class TsmomEtf:
    horizon = Horizon.MEDIUM_SWING

    def __init__(self, params: TsmomParams | None = None) -> None:
        self.params = params or TsmomParams()
        self.key = "tsmom_etf.medium_swing"

    def spec(self) -> StrategySpec:
        p = self.params
        return StrategySpec(
            name=self.key,
            version=VERSION,
            git_sha=git_sha(),
            horizon=self.horizon,
            rule_definition=(
                "Evaluated only on the last exchange session of each calendar month (exchange "
                f"calendar, known in advance). LONG when the {p.lookback}-session return is "
                f"positive and close > SMA({p.sma_window}); SHORT (only when shorts are enabled) "
                f"when the return is negative and close < SMA({p.sma_window}). No regime gate: "
                "the rule is each asset's own trend."
            ),
            required_data_sources=("BAR_DAILY",),
            feature_definitions=(
                f"mom=close(t)/close(t-{p.lookback})-1",
                f"sma=SMA(close,{p.sma_window})",
                f"atr=ATR({p.atr_window})",
                "month_end=is_last_session_of_month(date(t))",
            ),
            entry_conditions="month-end session; sign(mom) agrees with price vs SMA",
            invalidation_conditions="time stop (re-decided at the next month end) or disaster stop",
            exit_logic="no target; time stop",
            stop_logic=f"stop = entry -/+ {p.stop_atr} * ATR({p.atr_window})",
            time_stop=f"{p.time_stop_bars} sessions",
            liquidity_requirements="see ResearchConfig.liquidity (price / ADDV / spread)",
            event_filters="none (ETF universe; earnings windows do not apply)",
            assumed_transaction_costs="ResearchConfig commission model (default 0)",
            slippage_model="ResearchConfig slippage_bps + half spread",
            permits_long=True,
            permits_short=True,
            known_failure_modes=(
                "sharp trend reversals (momentum crashes)",
                "range-bound years with repeated small time-stop losses",
                "gap through the disaster stop",
            ),
            test_date_range="set per backtest run",
            in_sample_period="first 60% of the available history",
            out_of_sample_period="last 40% of the available history",
            walkforward_result_ref=f"reports/{self.key}-{VERSION}.md",
            status=StrategyStatus.EXPERIMENTAL,
            notes="Pre-registered 2026-11-02: PREREGISTRATION_universe_program_2026-11-02.md §2A",
        )

    def evaluate(self, series: PriceSeries, t: int, ctx: StrategyContext) -> EntrySignal | None:
        p = self.params
        if not is_last_session_of_month(series.dates[t]):
            return None
        mom = rolling_return(series, t, p.lookback)
        s = sma(series, t, p.sma_window)
        a = atr(series, t, p.atr_window)
        if any(math.isnan(x) for x in (mom, s, a)) or a <= 0:
            return None
        close = float(series.close[t])
        if mom > 0 and close > s:
            return EntrySignal(
                direction=Direction.LONG,
                stop_price=close - p.stop_atr * a,
                time_stop_bars=p.time_stop_bars,
                reason=f"month end; {p.lookback}d return {mom:+.1%}; close > SMA{p.sma_window}",
            )
        if ctx.allow_short and mom < 0 and close < s:
            return EntrySignal(
                direction=Direction.SHORT,
                stop_price=close + p.stop_atr * a,
                time_stop_bars=p.time_stop_bars,
                reason=f"month end; {p.lookback}d return {mom:+.1%}; close < SMA{p.sma_window}",
            )
        return None
