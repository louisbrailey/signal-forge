"""Baseline strategy implementations (pure functions).

Phase 1 ships:
* ``trend_continuation`` — trend + volume confirmation (SHORT_SWING, MEDIUM_SWING)
* ``mean_reversion`` — reversion after a statistically unusual move (SHORT_SWING)
plus a ``regime_filter`` gating input (``signalforge.research.regime``) that is
consumed by both — it is not itself a trade generator.

All ship as ``EXPERIMENTAL`` (paper only, no alerts) until
``signalforge.research.promotion`` clears every gate on genuine licensed
data — promotion is automatic and evidence-based, never a manual action.
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
from signalforge.research.strategies.high52_breakout import High52Breakout
from signalforge.research.strategies.intraday_orb import IntradayORB
from signalforge.research.strategies.mean_reversion import MeanReversion
from signalforge.research.strategies.relative_strength import RelativeStrength
from signalforge.research.strategies.trend_continuation import TrendContinuation
from signalforge.research.strategies.trend_pullback import TrendPullback
from signalforge.research.strategies.tsmom_etf import TsmomEtf
from signalforge.research.strategies.turn_of_month import TurnOfMonth

__all__ = [
    "BaselineStrategy",
    "StrategyContext",
    "signal_fn_for",
    "TrendContinuation",
    "MeanReversion",
    "RelativeStrength",
    "VolatilityBreakout",
    "IntradayORB",
    "TsmomEtf",
    "TurnOfMonth",
    "High52Breakout",
    "TrendPullback",
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
        # Pre-registered 2026-11-02 (PREREGISTRATION_universe_program_2026-11-02.md).
        TsmomEtf(),
        TurnOfMonth(),
        # Refinement round 1, pre-registered 2026-11-02 (same document §7.1).
        TsmomEtf(Horizon.POSITION),
        # Round 2, pre-registered 2026-11-03 (PREREGISTRATION_round2_2026-11-03.md).
        High52Breakout(),
        TrendPullback(),
    ]


def build_registry() -> StrategyRegistry:
    reg = StrategyRegistry()
    for strat in default_strategies():
        reg.register(strat.spec())
    return reg
