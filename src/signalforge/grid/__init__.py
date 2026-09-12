"""Mechanical grid strategy over a large U.S.-listed daily-close universe.

The grid is a *mechanical rebalancing rule*, not a researched edge: per symbol
it keeps an anchor price, buys a fixed dollar amount after a fixed percentage
drop from the anchor, and sells a fixed dollar amount after a fixed percentage
rise. It is deliberately NOT a registered strategy and NOT promotion-gated —
it never produces a ``Candidate``, never enters the scan/promotion pipeline,
and its settings are excluded from the approval scope hash. See
``docs/research/grid/README.md``.

Everything here is research/simulation only. No brokerage is contacted and no
order is ever placed.
"""

from __future__ import annotations

from signalforge.grid.config import GridParams
from signalforge.grid.engine import (
    GridBacktestResult,
    GridDecision,
    GridMetrics,
    GridTrade,
    decide,
    run_grid_backtest,
)
from signalforge.grid.universe import GridUniverse, load_universe

__all__ = [
    "GridParams",
    "GridBacktestResult",
    "GridDecision",
    "GridMetrics",
    "GridTrade",
    "GridUniverse",
    "decide",
    "load_universe",
    "run_grid_backtest",
]
