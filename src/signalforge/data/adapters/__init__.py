"""Data-provider adapters.

Add a provider by implementing the relevant Protocol from ``base.py`` and
publishing an :class:`~signalforge.data.adapters.base.AdapterCapability`. Never
hard-code ``latency_category`` to ``REALTIME`` — it must reflect the configured
entitlement.
"""

from __future__ import annotations

from signalforge.data.adapters.base import (
    AdapterCapability,
    DailyBar,
    FeedType,
    LatencyCategory,
    MarketDataAdapter,
    Provenance,
)

__all__ = [
    "AdapterCapability",
    "DailyBar",
    "FeedType",
    "LatencyCategory",
    "MarketDataAdapter",
    "Provenance",
]
