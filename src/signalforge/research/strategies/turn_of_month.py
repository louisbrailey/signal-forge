"""Family B — turn-of-the-month (SHORT_SWING).

Pre-registered 2026-11-02 in
``docs/research/PREREGISTRATION_universe_program_2026-11-02.md`` §2B. Published
basis: McConnell & Xu, "Equity Returns at the Turn of the Month," Financial
Analysts Journal 64(2) 2008 — over 1926–2005 essentially all of the equity
premium accrued in the four-session window from the last trading day of a
month (day -1) through the third trading day of the next (day +3).

The engine fills an entry at the NEXT session's open, so the signal fires on
the penultimate session of the month (read from the exchange calendar, never
from a future bar); the fill then lands on day -1's open and the 3-session
time stop exits at day +3's close. Long only; a 3xATR disaster stop guards
against a crash inside the window.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from signalforge.backtest.engine import EntrySignal
from signalforge.data.series import PriceSeries
from signalforge.domain import Direction, Horizon
from signalforge.gitinfo import git_sha
from signalforge.research.features.daily import atr
from signalforge.research.registry import StrategySpec, StrategyStatus
from signalforge.research.strategies.base import StrategyContext
from signalforge.research.strategies.calendar_rules import is_penultimate_session_of_month

VERSION = "0.1.0"


@dataclass(frozen=True, slots=True)
class TurnOfMonthParams:
    hold_bars: int = 3  # day -1 open -> day +3 close
    atr_window: int = 14
    stop_atr: float = 3.0  # disaster stop only


class TurnOfMonth:
    horizon = Horizon.SHORT_SWING

    def __init__(self, params: TurnOfMonthParams | None = None) -> None:
        self.params = params or TurnOfMonthParams()
        self.key = "turn_of_month.short_swing"

    def spec(self) -> StrategySpec:
        p = self.params
        return StrategySpec(
            name=self.key,
            version=VERSION,
            git_sha=git_sha(),
            horizon=self.horizon,
            rule_definition=(
                "LONG at the open of the last exchange session of each month (signal on the "
                "penultimate session, from the exchange calendar), held through the close of "
                f"the {p.hold_bars}rd session of the new month. No regime gate; long only."
            ),
            required_data_sources=("BAR_DAILY",),
            feature_definitions=(
                "penultimate=is_penultimate_session_of_month(date(t))",
                f"atr=ATR({p.atr_window})",
            ),
            entry_conditions="calendar only: the next session is the month's last",
            invalidation_conditions="time stop or disaster stop",
            exit_logic="no target; time stop",
            stop_logic=f"stop = entry - {p.stop_atr} * ATR({p.atr_window})",
            time_stop=f"{p.hold_bars} sessions",
            liquidity_requirements="see ResearchConfig.liquidity (price / ADDV / spread)",
            event_filters="none (index ETF universe)",
            assumed_transaction_costs="ResearchConfig commission model (default 0)",
            slippage_model="ResearchConfig slippage_bps + half spread",
            permits_long=True,
            permits_short=False,
            known_failure_modes=(
                "effect decays after publication / is arbitraged away",
                "round-trip costs exceed a few-tenths-of-a-percent edge",
                "month-end crash inside the window",
            ),
            test_date_range="set per backtest run",
            in_sample_period="first 60% of the available history",
            out_of_sample_period="last 40% of the available history",
            walkforward_result_ref=f"reports/{self.key}-{VERSION}.md",
            status=StrategyStatus.EXPERIMENTAL,
            notes="Pre-registered 2026-11-02: PREREGISTRATION_universe_program_2026-11-02.md §2B",
        )

    def evaluate(self, series: PriceSeries, t: int, ctx: StrategyContext) -> EntrySignal | None:
        p = self.params
        if not is_penultimate_session_of_month(series.dates[t]):
            return None
        a = atr(series, t, p.atr_window)
        if math.isnan(a) or a <= 0:
            return None
        close = float(series.close[t])
        return EntrySignal(
            direction=Direction.LONG,
            stop_price=close - p.stop_atr * a,
            time_stop_bars=p.hold_bars,
            reason=f"turn of month: next session is the month's last; hold {p.hold_bars}",
        )
