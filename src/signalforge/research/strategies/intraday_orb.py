"""Strategy 5 (Phase 2) — intraday opening-range breakout (INTRADAY horizon).

After the first ``or_bars`` bars of the regular session define the opening range,
enter on a bar close beyond it, stop at the opposite edge, target a multiple of
the range, and force a time stop well before the close. Regime-gated on the daily
market regime (a coarse risk-on/off filter — the regime does not flip intraday).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from signalforge.backtest.engine import EntrySignal
from signalforge.data.series import PriceSeries
from signalforge.domain import Direction, Horizon
from signalforge.gitinfo import git_sha
from signalforge.research.features.intraday import (
    bars_since_open,
    opening_range,
    session_bar_count,
)
from signalforge.research.registry import StrategySpec, StrategyStatus
from signalforge.research.strategies.base import StrategyContext

VERSION = "0.1.0"


@dataclass(frozen=True, slots=True)
class ORBParams:
    or_bars: int = 3  # bars that define the opening range
    min_bars_before_entry: int = 3
    max_bars_after_open: int = 20  # do not initiate late in the session
    target_range_mult: float = 1.5
    time_stop_bars: int = 12


class IntradayORB:
    horizon = Horizon.INTRADAY
    key = "intraday_orb.intraday"

    def __init__(self, params: ORBParams | None = None) -> None:
        self.params = params or ORBParams()

    def spec(self) -> StrategySpec:
        p = self.params
        return StrategySpec(
            name=self.key,
            version=VERSION,
            git_sha=git_sha(),
            horizon=self.horizon,
            rule_definition=(
                f"After the first {p.or_bars} RTH bars set the opening range (OR). "
                f"LONG when a bar closes above OR high (SHORT below OR low, if enabled) between "
                f"bar {p.min_bars_before_entry} and {p.max_bars_after_open} of the session, "
                "and the daily regime is not risk-off. Stop at the opposite OR edge; target "
                f"{p.target_range_mult}x the OR width; time stop {p.time_stop_bars} bars."
            ),
            required_data_sources=("BAR_INTRADAY", "BAR_DAILY"),
            feature_definitions=(
                f"opening_range(k={p.or_bars})",
                "bars_since_open",
                "session_bar_count",
            ),
            entry_conditions="close beyond the OR within the entry window + regime gate",
            invalidation_conditions="close back inside the opening range",
            exit_logic=f"target = entry +/- {p.target_range_mult} * OR width",
            stop_logic="stop = opposite opening-range edge",
            time_stop=f"{p.time_stop_bars} bars (well before the close)",
            liquidity_requirements="daily ADDV / price / spread from ResearchConfig.liquidity",
            event_filters="excluded earnings window from ResearchConfig.events",
            assumed_transaction_costs="ResearchConfig commission model (default 0)",
            slippage_model="ResearchConfig slippage_bps + half spread (intraday spreads are wider)",
            permits_long=True,
            permits_short=True,
            known_failure_modes=(
                "chop around the OR edge on a rangebound day",
                "gap-and-fade after the open",
                "thin liquidity in the first bars widening the effective spread",
            ),
            test_date_range="set per backtest run (intraday bars)",
            in_sample_period="first 60% of the intraday sessions tested",
            out_of_sample_period="last 40% of the intraday sessions tested",
            walkforward_result_ref=f"reports/{self.key}-{VERSION}.md",
            status=StrategyStatus.EXPERIMENTAL,
        )

    def evaluate(self, series: PriceSeries, t: int, ctx: StrategyContext) -> EntrySignal | None:
        p = self.params
        or_hi, or_lo = opening_range(series, t, p.or_bars)
        if math.isnan(or_hi) or or_hi <= or_lo:
            return None
        since_open = bars_since_open(series, t)
        if not (p.min_bars_before_entry <= since_open <= p.max_bars_after_open):
            return None
        # keep enough room before the close for the time stop
        if session_bar_count(series, t) + p.time_stop_bars > 26 + p.or_bars:
            return None

        close = float(series.close[t])
        width = or_hi - or_lo
        if width <= 0:
            return None

        if close > or_hi and not ctx.regime.risk_off:
            return EntrySignal(
                direction=Direction.LONG,
                stop_price=or_lo,
                target_price=close + p.target_range_mult * width,
                time_stop_bars=p.time_stop_bars,
                reason=(
                    f"close {close:.2f} > OR high {or_hi:.2f} (width {width:.2f}); "
                    f"bar {since_open} of session; regime {ctx.regime.trend.value}"
                ),
            )
        if ctx.allow_short and close < or_lo and ctx.regime.risk_off:
            return EntrySignal(
                direction=Direction.SHORT,
                stop_price=or_hi,
                target_price=close - p.target_range_mult * width,
                time_stop_bars=p.time_stop_bars,
                reason=(
                    f"close {close:.2f} < OR low {or_lo:.2f} (width {width:.2f}); "
                    f"bar {since_open}; regime risk-off"
                ),
            )
        return None
