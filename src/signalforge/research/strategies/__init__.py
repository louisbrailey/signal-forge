"""Baseline strategy implementations (pure functions).

Phase 1 ships:
* ``trend_continuation`` — trend + volume confirmation (SHORT_SWING, MEDIUM_SWING)
* ``mean_reversion`` — reversion after a statistically unusual move (SHORT_SWING)
plus a ``regime_filter`` gating input (``signalforge.research.regime``) that is
consumed by both — it is not itself a trade generator.

All ship as ``EXPERIMENTAL`` (paper only, no alerts) until a walk-forward report
clears the thresholds and the user promotes them.
"""

from __future__ import annotations

from signalforge.domain import Horizon
from signalforge.research.registry import StrategyRegistry
from signalforge.research.strategies.base import (
    BaselineStrategy,
    StrategyContext,
    signal_fn_for,
)
from signalforge.research.strategies.breakout import VolatilityBreakout
from signalforge.research.strategies.intraday_orb import IntradayORB
from signalforge.research.strategies.mean_reversion import MeanReversion
from signalforge.research.strategies.relative_strength import RelativeStrength
from signalforge.research.strategies.trend_continuation import TrendContinuation

__all__ = [
    "BaselineStrategy",
    "StrategyContext",
    "signal_fn_for",
    "TrendContinuation",
    "MeanReversion",
    "RelativeStrength",
    "VolatilityBreakout",
    "IntradayORB",
    "default_strategies",
    "build_registry",
]


def default_strategies() -> list[BaselineStrategy]:
    return [
        IntradayORB(),
        TrendContinuation(Horizon.SHORT_SWING),
        TrendContinuation(Horizon.MEDIUM_SWING),
        MeanReversion(),
        RelativeStrength(Horizon.MEDIUM_SWING),
        VolatilityBreakout(Horizon.SHORT_SWING),
    ]


def build_registry() -> StrategyRegistry:
    reg = StrategyRegistry()
    for strat in default_strategies():
        reg.register(strat.spec())
    return reg
