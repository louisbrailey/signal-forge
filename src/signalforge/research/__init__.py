"""Deterministic research engine: strategy registry, features, scan, rank, candidates.

Nothing in this package may import :mod:`signalforge.llm` (invariant S3, enforced
by import-linter). All logic is deterministic given (inputs, code version,
``ResearchConfig.config_hash``, seed) — invariant S4.
"""

from __future__ import annotations

from signalforge.research.backtest_runner import (
    StrategyBacktestResult,
    run_strategy_over_universe,
)
from signalforge.research.candidates import persist_scan
from signalforge.research.persistence import (
    persist_backtest_result,
    upsert_strategy_version,
)
from signalforge.research.regime import RegimeState, Trend, Vol, regime_from_proxy
from signalforge.research.registry import (
    StrategyRegistrationError,
    StrategyRegistry,
    StrategySpec,
    StrategyStatus,
)
from signalforge.research.scan import ScanResult, run_scan
from signalforge.research.strategies import build_registry, default_strategies

__all__ = [
    "StrategySpec",
    "StrategyStatus",
    "StrategyRegistry",
    "StrategyRegistrationError",
    "RegimeState",
    "Trend",
    "Vol",
    "regime_from_proxy",
    "default_strategies",
    "build_registry",
    "StrategyBacktestResult",
    "run_strategy_over_universe",
    "ScanResult",
    "run_scan",
    "persist_scan",
    "upsert_strategy_version",
    "persist_backtest_result",
]
