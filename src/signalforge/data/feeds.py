"""Feed-status reporting for the UI and ``/api/feeds``.

Every configured feed reports its provider, feed type, latency category, whether
it is simulated, and its last successful update. The UI uses ``latency_category``
to decide the "live vs delayed" label (invariant S7) and ``is_stale`` to disable
live alerts (invariant S8).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import DataFeedStatus
from signalforge.db.session import session_scope
from signalforge.db.types import utcnow

# A feed with no success within this window is considered stale for status display.
DEFAULT_STALE_AFTER = timedelta(hours=36)


def _row_to_dict(row: DataFeedStatus, *, stale_after: timedelta, now: datetime) -> dict[str, Any]:
    last = row.last_success_at
    age_seconds = (now - last).total_seconds() if last else None
    is_stale = last is None or last > now or (now - last) > stale_after
    return {
        "provider": row.provider,
        "feed_type": row.feed_type.value,
        "latency_category": row.latency_category.value,
        "is_live": row.latency_category.is_live,
        "is_simulated": row.is_simulated,
        "entitlement_note": row.entitlement_note,
        "last_success_at": last.isoformat() if last else None,
        "age_seconds": age_seconds,
        "is_stale": is_stale,
        "rate_limited_until": (
            row.rate_limited_until.isoformat() if row.rate_limited_until else None
        ),
        "consecutive_failures": row.consecutive_failures,
        "last_error": row.last_error,
    }


def feed_status_report(
    session: Session | None = None,
    stale_after: timedelta = DEFAULT_STALE_AFTER,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """``now`` is the clock every ``age_seconds``/``is_stale`` value is measured
    against. Callers that already run on an injected clock (the readiness gate,
    the alert planner) pass theirs so one clock governs every freshness
    decision; everyone else gets the wall clock."""
    now = now or utcnow()
    if session is not None:
        rows = list(session.scalars(select(DataFeedStatus).order_by(DataFeedStatus.provider)))
        feeds = [_row_to_dict(r, stale_after=stale_after, now=now) for r in rows]
    else:
        with session_scope() as own:
            rows = list(own.scalars(select(DataFeedStatus).order_by(DataFeedStatus.provider)))
            feeds = [_row_to_dict(r, stale_after=stale_after, now=now) for r in rows]
    any_live_capable = any(f["is_live"] for f in feeds)
    return {
        "feeds": feeds,
        "any_live_capable": any_live_capable,
        "note": (
            "No feeds registered yet — run an ingestion job."
            if not feeds
            else "latency_category drives the live/delayed label; is_stale disables live alerts."
        ),
    }
