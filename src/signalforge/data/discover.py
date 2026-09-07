"""Discover the earliest daily-bar date the provider actually serves.

The provider's historical depth is an *entitlement*, not a constant. This probes
it with a binary search on a liquid reference symbol and returns the oldest
``from`` date that still returns data — the caller records this in the ingestion
metadata and ingests with a margin *inside* it (so a routine run never repeatedly
trips the 403 boundary).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from signalforge.data.adapters.base import AdapterError, MarketDataAdapter
from signalforge.observability import get_logger

_log = get_logger("data.discover")
_REF_SYMBOL = "AAPL"
_PROBE_SPAN_DAYS = 8


@dataclass(frozen=True, slots=True)
class HistoryDepth:
    earliest_available: date  # oldest 'from' that returned >=1 bar
    first_unavailable: date  # a 'from' just older than that which failed
    probed_at: str
    reference_symbol: str

    def safe_start(self, margin_days: int = 45) -> date:
        return self.earliest_available + timedelta(days=margin_days)


def _has_data(adapter: MarketDataAdapter, frm: date) -> bool:
    try:
        bars = adapter.fetch_daily_bars(_REF_SYMBOL, frm, frm + timedelta(days=_PROBE_SPAN_DAYS))
    except AdapterError:
        return False
    return len(list(bars)) > 0


def discover_history_depth(
    adapter: MarketDataAdapter,
    *,
    max_years_back: int = 25,
    known_good_years_back: int = 2,
) -> HistoryDepth:
    """Binary-search the oldest servable date. ``known_good_years_back`` must be a
    window the plan definitely covers (used as the search's good anchor)."""
    today = date.today()
    good = today - timedelta(days=int(known_good_years_back * 365.25))
    bad = today - timedelta(days=int(max_years_back * 365.25))
    if not _has_data(adapter, good):
        # Even the "known good" anchor failed — fall back to a recent window.
        good = today - timedelta(days=400)
        if not _has_data(adapter, good):
            raise AdapterError("provider returned no daily data even for a recent window")

    for _ in range(24):
        if (good - bad).days <= 3:
            break
        mid = bad + (good - bad) // 2
        if _has_data(adapter, mid):
            good = mid
        else:
            bad = mid

    depth = HistoryDepth(
        earliest_available=good,
        first_unavailable=bad,
        probed_at=datetime.now(UTC).isoformat(),
        reference_symbol=_REF_SYMBOL,
    )
    _log.info(
        "data.history_depth",
        earliest=good.isoformat(),
        first_unavailable=bad.isoformat(),
        years_back=round((today - good).days / 365.25, 2),
    )
    return depth
