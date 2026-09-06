"""Backtest + walk-forward validation engine (ARCHITECTURE.md §1.4).

Deterministic (invariant S4). No look-ahead: a signal at bar ``t`` sees only
``series.head(t)``; entries fill at ``t+1`` open. All results are net of modeled
costs. Never imports :mod:`signalforge.llm`.
"""

from __future__ import annotations

from signalforge.backtest.costs import CostModel
from signalforge.backtest.engine import (
    BacktestOutcome,
    EntrySignal,
    SignalFn,
    SimTrade,
    run_backtest,
)
from signalforge.backtest.metrics import Metrics, compute_metrics
from signalforge.backtest.montecarlo import bootstrap_ci
from signalforge.backtest.walkforward import WalkforwardReport, run_walkforward
from signalforge.data.series import PriceSeries

__all__ = [
    "CostModel",
    "PriceSeries",
    "EntrySignal",
    "SignalFn",
    "SimTrade",
    "BacktestOutcome",
    "run_backtest",
    "Metrics",
    "compute_metrics",
    "bootstrap_ci",
    "WalkforwardReport",
    "run_walkforward",
]
