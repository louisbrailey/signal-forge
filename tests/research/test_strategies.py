"""Baseline strategies: spec completeness, entry logic, regime gating."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from signalforge.data.series import PriceSeries
from signalforge.domain import Direction, Horizon
from signalforge.research.regime import NEUTRAL, RegimeState, Trend, Vol
from signalforge.research.registry import StrategyStatus
from signalforge.research.strategies import (
    MeanReversion,
    TrendContinuation,
    build_registry,
    default_strategies,
)
from signalforge.research.strategies.base import StrategyContext

RISK_OFF = RegimeState(Trend.BEAR, Vol.HIGH, date(2024, 1, 1))
BULL = RegimeState(Trend.BULL, Vol.LOW, date(2024, 1, 1))


def _mk(closes: list[float], volumes: list[float] | None = None) -> PriceSeries:
    d = date(2022, 1, 3)
    vols = volumes or [1_000_000.0] * len(closes)
    rows = []
    for c, v in zip(closes, vols, strict=True):
        rows.append((d, c * 0.999, c * 1.005, c * 0.995, c, v))
        d += timedelta(days=1)
    return PriceSeries.from_bars("X", rows)


def test_registry_holds_the_baseline_strategies_all_experimental() -> None:
    reg = build_registry()
    strats = default_strategies()
    assert len(reg.scan_eligible()) == len(strats) >= 6
    assert reg.alert_eligible() == []
    for strat in strats:
        assert strat.spec().missing_fields() == []
        assert strat.spec().status is StrategyStatus.EXPERIMENTAL
    # every enabled horizon has at least one strategy
    from signalforge.domain import Horizon

    covered = {s.spec().horizon for s in strats}
    assert {Horizon.INTRADAY, Horizon.SHORT_SWING, Horizon.MEDIUM_SWING} <= covered


def test_trend_continuation_fires_long_on_confirmed_uptrend() -> None:
    closes = [100.0 * (1.004**i) for i in range(80)]
    vols = [1_000_000.0] * 79 + [2_000_000.0]  # volume surge on the signal bar
    series = _mk(closes, vols)
    strat = TrendContinuation(Horizon.SHORT_SWING)
    sig = strat.evaluate(series, len(series) - 1, StrategyContext(regime=BULL))
    assert sig is not None
    assert sig.direction is Direction.LONG
    assert sig.stop_price < series.close[-1] < (sig.target_price or 0)


def test_trend_continuation_is_gated_by_risk_off_regime() -> None:
    closes = [100.0 * (1.004**i) for i in range(80)]
    vols = [1_000_000.0] * 79 + [2_000_000.0]
    series = _mk(closes, vols)
    strat = TrendContinuation(Horizon.SHORT_SWING)
    assert strat.evaluate(series, len(series) - 1, StrategyContext(regime=RISK_OFF)) is None


def test_mean_reversion_fires_long_after_a_sharp_dip() -> None:
    rng = np.random.default_rng(0)
    closes = [100.0 + float(rng.normal(0, 0.2)) for _ in range(40)]
    closes.append(closes[-1] * 0.90)  # ~ -10% single-day shock => strongly negative z
    series = _mk(closes)
    strat = MeanReversion()
    sig = strat.evaluate(series, len(series) - 1, StrategyContext(regime=NEUTRAL))
    assert sig is not None
    assert sig.direction is Direction.LONG
    assert sig.target_price is not None and sig.target_price > series.close[-1]  # revert up to SMA


def test_mean_reversion_not_in_a_bear_regime() -> None:
    closes = [100.0] * 40 + [90.0]
    series = _mk(closes)
    assert (
        MeanReversion().evaluate(series, len(series) - 1, StrategyContext(regime=RISK_OFF)) is None
    )
