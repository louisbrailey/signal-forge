"""Market-data ingestion: adapters, normalization, repository, reconciliation.

Adapters are the only place that talks to an external data provider. They declare
a capability descriptor (including a truthful ``latency_category``) that drives
every "live vs delayed" label in the UI (invariant S7). A stale required feed
disables live alerts for the affected horizon (invariant S8) — see
``signalforge.data.freshness``.
"""

from __future__ import annotations

from signalforge.data.feeds import feed_status_report
from signalforge.data.freshness import FreshnessResult, check_feeds_fresh, gate_for_horizon
from signalforge.data.ingest import IngestReport, ingest_symbol, ingest_universe
from signalforge.data.reconciliation import reconcile_closes

__all__ = [
    "feed_status_report",
    "FreshnessResult",
    "check_feeds_fresh",
    "gate_for_horizon",
    "IngestReport",
    "ingest_symbol",
    "ingest_universe",
    "reconcile_closes",
]
