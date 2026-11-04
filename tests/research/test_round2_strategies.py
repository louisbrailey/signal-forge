"""Round 2 (PREREGISTRATION_round2_2026-11-03.md): 52-week-high breakout, trend
pullback, CRYPTO-H3 hourly variants — specs, signal logic, grids, wiring."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import numpy as np

from signalforge.data.series import PriceSeries
from signalforge.domain import Horizon
from signalforge.research.fx.hourly import (
    CRYPTO_H1_STRATEGIES,
    CRYPTO_H4_STRATEGIES,
    CRYPTO_H4_VERSION,
    HOURLY_STRATEGIES,
    HOURLY_VERSIONS,
)
from signalforge.research.promotion import _sensitivity_plan
from signalforge.research.regime import RegimeState, Trend, Vol
from signalforge.research.registry import StrategyStatus
from signalforge.research.strategies import High52Breakout, TrendPullback, default_strategies

RISK_OFF = RegimeState(Trend.BEAR, Vol.HIGH, date(2024, 1, 1))


def _daily(closes: list[float]) -> PriceSeries:
    d = date(2020, 1, 2)
    rows = [
        (d + timedelta(days=i), c * 0.999, c * 1.004, c * 0.996, c, 1e6)
        for i, c in enumerate(closes)
    ]
    return PriceSeries.from_bars("X", rows)


def test_round2_strategies_registered_with_complete_specs_and_grids() -> None:
    keys = {s.key for s in default_strategies()}
    assert {"high52_breakout.medium_swing", "trend_pullback.short_swing"} <= keys
    for strat in (High52Breakout(), TrendPullback()):
        spec = strat.spec()
        assert spec.missing_fields() == [] and spec.status is StrategyStatus.EXPERIMENTAL
        assert spec.permits_short is False
        plan = _sensitivity_plan(strat)
        assert plan is not None
        factory, grid = plan
        assert len(grid) == 2 and all(len(v) == 3 for v in grid.values())
        assert factory({k: v[0] for k, v in grid.items()}).key == strat.key
    assert High52Breakout().spec().horizon is Horizon.MEDIUM_SWING
    assert TrendPullback().spec().horizon is Horizon.SHORT_SWING


def test_crypto_h4_is_the_baseline_plus_two_declared_variants() -> None:
    assert CRYPTO_H4_VERSION == "CRYPTO-H4" and CRYPTO_H4_VERSION in HOURLY_VERSIONS
    assert HOURLY_STRATEGIES[CRYPTO_H4_VERSION] is CRYPTO_H4_STRATEGIES
    base, trail120, volx = CRYPTO_H4_STRATEGIES
    assert base is CRYPTO_H1_STRATEGIES[0]
    assert trail120.trail_channel == 120 and volx.trail_channel == 72
    assert volx.params["vol_fast"] == 24 and volx.params["vol_slow"] == 168
    # Synthetic hourly series: every volx signal is a baseline signal, never the reverse.
    rng = np.random.default_rng(5)
    closes = 30000 * np.exp(np.cumsum(rng.normal(0, 0.01, 2000)))
    t0 = datetime(2023, 1, 1, tzinfo=UTC)
    rows = [
        (t0 + timedelta(hours=i), c, c * 1.003, c * 0.997, c, 0.0) for i, c in enumerate(closes)
    ]
    series = PriceSeries.from_bars("BTCUSD", rows)
    n_base = n_volx = 0
    for t in range(volx.warmup, 1990, 7):
        head = series.head(t)
        b, tr, v = base.signal(head, t), trail120.signal(head, t), volx.signal(head, t)
        assert tr == b  # identical entry and stop; only the harness trail differs
        if v is not None:
            n_volx += 1
            assert b is not None and (v.direction, v.stop_price) == (b.direction, b.stop_price)
        if b is not None:
            n_base += 1
    assert n_base > 0 and n_volx <= n_base
