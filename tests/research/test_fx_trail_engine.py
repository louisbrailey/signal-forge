"""FX trailing-exit backtester: exact parity with the frozen engine when off."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

import numpy as np
import pytest

from signalforge.backtest.costs import CostModel
from signalforge.backtest.engine import EntrySignal, run_backtest
from signalforge.data.series import PriceSeries
from signalforge.domain import Direction
from signalforge.research.fx.strategies import FX_STRATEGIES
from signalforge.research.fx.trail_engine import run_backtest_trailing


def _series(closes: list[float]) -> PriceSeries:
    d0 = date(2020, 1, 1)
    rows = []
    prev = closes[0]
    for i, c in enumerate(closes):
        rows.append(
            (d0 + timedelta(days=i), prev, max(prev, c) * 1.002, min(prev, c) * 0.998, c, 0.0)
        )
        prev = c
    return PriceSeries.from_bars("X", rows)


def _walk(seed: int, n: int = 1500) -> list[float]:
    rng = np.random.default_rng(seed)
    return [float(x) for x in 1.2 * np.exp(np.cumsum(rng.normal(0, 0.006, n)))]


def _once_at(t0: int, time_stop: int = 250) -> Callable[[PriceSeries, int], EntrySignal | None]:
    def fn(series: PriceSeries, t: int) -> EntrySignal | None:
        if t != t0:
            return None
        return EntrySignal(Direction.LONG, float(series.close[-1]) * 0.5, time_stop)

    return fn


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_without_a_trail_it_reproduces_the_frozen_engine_exactly(seed: int) -> None:
    s = _series(_walk(seed))
    cm = CostModel(slippage_bps=1.0)
    for strat in FX_STRATEGIES:
        a = run_backtest(s, strat.signal, cost_model=cm, spread_bps=1.5, warmup=strat.warmup)
        b = run_backtest_trailing(
            s, strat.signal, trail_channel=None, cost_model=cm, spread_bps=1.5, warmup=strat.warmup
        )
        assert a.trades == b.trades, strat.key


def test_a_trend_is_held_until_the_close_breaks_the_prior_channel() -> None:
    up = [100.0 + i for i in range(150)]  # a trend far longer than a 40-bar hold
    s = _series(up + [up[-1] - 3.0 * (i + 1) for i in range(10)])
    (t,) = run_backtest_trailing(s, _once_at(10), trail_channel=20, warmup=5).trades
    assert t.exit_reason == "trail" and t.exit_date > s.dates[149] and t.pnl_r > 0
    (u,) = run_backtest(s, _once_at(10, time_stop=40), warmup=5).trades
    assert u.exit_reason == "time_stop" and u.pnl_r < t.pnl_r


def test_the_trailing_exit_uses_no_future_bars() -> None:
    base = _walk(7, 300)
    s1 = _series(base)
    (a,) = run_backtest_trailing(s1, _once_at(10), trail_channel=20, warmup=5).trades
    i = s1.dates.index(a.exit_date)
    shocked = base[: i + 1] + [x * 3 for x in base[i + 1 :]]
    (b,) = run_backtest_trailing(_series(shocked), _once_at(10), trail_channel=20, warmup=5).trades
    assert (a.exit_date, a.exit_reason, a.exit_price) == (b.exit_date, b.exit_reason, b.exit_price)


def test_tiny_channels_are_refused() -> None:
    with pytest.raises(ValueError):
        run_backtest_trailing(_series(_walk(1, 50)), _once_at(5), trail_channel=1, warmup=5)
