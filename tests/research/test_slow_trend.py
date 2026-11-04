from dataclasses import replace
from datetime import date, timedelta

import numpy as np

from signalforge.data.series import PriceSeries
from signalforge.domain import Direction
from signalforge.research.slow_trend import SlowTrendParams, signal
from signalforge.research.strategies import default_strategies


def series():
    dates = tuple(date(2020, 1, 1) + timedelta(days=i) for i in range(500))
    c = np.linspace(100, 200, len(dates))
    return PriceSeries("SPY", dates, c.copy(), c + 1, c - 1, c.copy(), c * 100000)


def test_monthly_long_signal_has_exact_rules_and_no_future_read():
    b = series()
    t = next(i for i in range(252, len(b)) if b.dates[i].day == 1)
    actual = signal(b, t)
    assert actual and actual.direction is Direction.LONG
    assert actual.stop_price == b.close[t] - 6
    assert actual.target_price == b.close[t] + 12
    assert actual.time_stop_bars == 126
    assert actual == signal(b.head(t), t)
    b.close[t + 1 :] = np.nan
    assert signal(b, t) == actual
    assert signal(b, t + 1) is None
    assert signal(b, 251) is None
    assert signal(replace(b, symbol="AAPL"), t) is None
    assert all("slow_trend" not in s.key for s in default_strategies())


def test_falling_trend_filtered_but_ablation_is_explicit():
    b = series()
    b = replace(b, close=300 - b.close, high=301 - b.close, low=299 - b.close)
    t = next(i for i in range(252, len(b)) if b.dates[i].day == 1)
    assert signal(b, t) is None
    assert signal(b, t, trend_filter=False) is not None
    b.close[t] = np.nan
    assert signal(b, t, trend_filter=False) is None


def test_sensitivity_is_separate_not_mutation():
    b = series()
    t = next(i for i in range(252, len(b)) if b.dates[i].day == 1)
    baseline = signal(b, t)
    assert signal(b, t, SlowTrendParams(holding_sessions=100)).time_stop_bars == 100
    assert signal(b, t) == baseline
