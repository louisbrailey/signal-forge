"""Synthetic price series for backtest tests."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from signalforge.data.series import PriceSeries


def _weekdays(start: date, n: int) -> list[date]:
    out: list[date] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


@pytest.fixture
def uptrend_with_dips() -> PriceSeries:
    """+0.25%/bar drift, a sharp -3% dip every 12 bars that then recovers.

    A 'buy the dip' rule with a 4% target and 3.5% stop should be net positive.
    """
    dates = _weekdays(date(2020, 1, 1), 400)
    rows = []
    price = 100.0
    for i, d in enumerate(dates):
        price *= 1.0025
        if i % 12 == 0 and i > 0:
            price *= 0.97
        o = price * 0.999
        c = price * 1.001
        hi = max(o, c) * 1.004
        lo = min(o, c) * 0.996
        rows.append((d, o, hi, lo, c, 1_000_000.0))
    return PriceSeries.from_bars("TEST", rows)


@pytest.fixture
def flat_range() -> PriceSeries:
    dates = _weekdays(date(2020, 1, 1), 300)
    rows = []
    for i, d in enumerate(dates):
        base = 100.0 + (2.0 if i % 2 == 0 else -2.0)
        rows.append((d, base, base * 1.005, base * 0.995, base, 1_000_000.0))
    return PriceSeries.from_bars("FLAT", rows)
