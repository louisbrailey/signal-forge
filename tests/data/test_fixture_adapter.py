"""Fixture adapter: deterministic bars, quarterly earnings, no earnings for ETFs."""

from __future__ import annotations

from datetime import date
from itertools import pairwise

from signalforge.data.adapters.fixture import FixtureMarketDataAdapter
from signalforge.domain import LatencyCategory


def test_window_is_a_stable_slice_of_one_series() -> None:
    a = FixtureMarketDataAdapter()
    wide = {
        b.session_date: b.close
        for b in a.fetch_daily_bars("AAPL", date(2023, 1, 1), date(2024, 6, 1))
    }
    narrow = a.fetch_daily_bars("AAPL", date(2024, 1, 2), date(2024, 3, 1))
    assert narrow, "expected bars"
    for b in narrow:
        assert b.close == wide[b.session_date]  # same underlying walk


def test_bars_are_simulated_and_historical() -> None:
    bars = FixtureMarketDataAdapter().fetch_daily_bars("SPY", date(2024, 1, 1), date(2024, 2, 1))
    assert bars
    assert all(b.provenance.is_simulated for b in bars)
    assert all(b.provenance.latency_category is LatencyCategory.HISTORICAL for b in bars)


def test_quarterly_earnings_for_stocks_only() -> None:
    a = FixtureMarketDataAdapter()
    stock = sorted(
        a.fetch_earnings("AAPL", date(2024, 1, 1), date(2024, 12, 31)),
        key=lambda e: e.scheduled_for,
    )
    assert len(stock) == 4
    gaps = [(b.scheduled_for - x.scheduled_for).days for x, b in pairwise(stock)]
    assert all(80 <= g <= 100 for g in gaps)  # ~quarterly
    assert a.fetch_earnings("SPY", date(2024, 1, 1), date(2024, 12, 31)) == ()


def test_earnings_are_deterministic() -> None:
    a = FixtureMarketDataAdapter()
    first = a.fetch_earnings("NVDA", date(2024, 1, 1), date(2024, 12, 31))
    second = a.fetch_earnings("NVDA", date(2024, 1, 1), date(2024, 12, 31))
    assert [e.scheduled_for for e in first] == [e.scheduled_for for e in second]
