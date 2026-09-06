"""Baseline strategy implementations (pure functions).

Each strategy is code + a versioned ``StrategySpec`` in the registry. Phase 1
ships:
* ``trend_continuation`` — trend + volume confirmation (SHORT_SWING, MEDIUM_SWING)
* ``mean_reversion`` — reversion after a statistically unusual move (SHORT_SWING)
plus a ``regime_filter`` gating input (not itself a trade generator).
"""

from __future__ import annotations
