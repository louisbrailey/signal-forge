from datetime import date, timedelta

from signalforge.config.research import EventFilters, LiquidityFilters
from signalforge.data.calendar import sessions
from signalforge.data.series import PriceSeries
from signalforge.domain import Horizon
from signalforge.research.historical_eligibility import (
    EventCoverage,
    HistoricalEligibility,
    KnownEarnings,
)


def bars(price=100, volume=1000000):
    return PriceSeries.from_bars(
        "A",
        [
            (d, price, price, price, price, volume)
            for d in sessions(date(2023, 1, 3), date(2024, 1, 31))
        ],
    )


def policy(kind="stock", events=()):
    return HistoricalEligibility(
        {"A": kind}, LiquidityFilters(), EventFilters(), Horizon.SHORT_SWING, {"A": events}
    )


def test_earnings_absence_is_not_no_risk_and_future_coverage_is_rejected():
    b = bars()
    d = b.dates[-1]
    assert policy()("A", b, len(b) - 1) == ("earnings_coverage_unavailable",)
    future = EventCoverage(
        d - timedelta(days=10), d + timedelta(days=30), d + timedelta(days=1), "test"
    )
    assert policy(events=(future,))("A", b, len(b) - 1) == ("earnings_coverage_unavailable",)
    assert policy("etf")("A", b, len(b) - 1) == ()


def test_scanner_liquidity_and_earnings_boundaries():
    b = bars()
    d = b.dates[-1]
    known = EventCoverage(
        d - timedelta(days=3),
        d + timedelta(days=21),
        d,
        "test",
        (KnownEarnings(d + timedelta(days=21), d),),
    )
    assert policy(events=(known,))("A", b, len(b) - 1) == ("earnings_event_window",)
    b = bars(price=4)
    assert policy("etf")("A", b, len(b) - 1) == ("liquidity",)
    b = bars(volume=1)
    assert policy("etf")("A", b, len(b) - 1) == ("liquidity",)
    b = bars().head(218)
    assert policy("etf")("A", b, len(b) - 1) == ("insufficient_history",)
