"""Decision-time daily scanner inputs; no database or current-metric lookups.

Research admission deliberately does not imply promotion. Production-equivalent
qualification additionally requires pre-existing, time-stamped OOS evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from signalforge.config.research import EventFilters, LiquidityFilters
from signalforge.data.series import PriceSeries
from signalforge.domain import Horizon

MIN_HISTORY = 220
HORIZON_DAYS = {Horizon.SHORT_SWING: 10, Horizon.MEDIUM_SWING: 40, Horizon.POSITION: 126}


@dataclass(frozen=True)
class KnownEarnings:
    scheduled_for: date
    known_on: date


@dataclass(frozen=True)
class EventCoverage:
    start: date
    end: date
    known_on: date
    source: str
    events: tuple[KnownEarnings, ...] = ()


@dataclass(frozen=True)
class HistoricalEligibility:
    instrument_types: dict[str, str]
    liquidity: LiquidityFilters
    events: EventFilters
    horizon: Horizon
    earnings: dict[str, tuple[EventCoverage, ...]]
    modeled_spread_bps: float = 5.0

    def __call__(self, symbol: str, visible: PriceSeries, t: int) -> tuple[str, ...]:
        if len(visible) != t + 1:
            raise ValueError("Only decision-time prefix allowed")
        if len(visible) < MIN_HISTORY:
            return ("insufficient_history",)
        if (
            float(visible.close[-1]) < self.liquidity.min_price
            or visible.dollar_volume(20) < self.liquidity.min_avg_dollar_volume
        ):
            return ("liquidity",)
        if self.modeled_spread_bps > self.liquidity.max_avg_spread_bps:
            return ("modeled_spread_limit",)
        if self.instrument_types.get(symbol) == "etf":
            return ()
        day = visible.dates[-1]
        lo = day - timedelta(days=self.events.exclude_days_before_earnings)
        hi = day + timedelta(
            days=HORIZON_DAYS[self.horizon] * 2 + self.events.exclude_days_after_earnings
        )
        covers = [
            c
            for c in self.earnings.get(symbol, ())
            if c.source and c.known_on <= day and c.start <= lo and c.end >= hi
        ]
        if not covers:
            return ("earnings_coverage_unavailable",)
        if self.events.exclude_days_before_earnings > 0 and any(
            lo <= e.scheduled_for <= hi and e.known_on <= day for c in covers for e in c.events
        ):
            return ("earnings_event_window",)
        return ()
