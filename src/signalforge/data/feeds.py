"""Feed-status reporting for the UI and ``/api/feeds``.

Every configured feed reports its provider, feed type, latency category, whether
it is simulated, and its last successful update. The UI uses ``latency_category``
to decide the "live vs delayed" label (invariant S7) and ``is_stale`` to disable
live alerts (invariant S8).

Staleness is market-calendar aware for the daily-bar feeds whose trading
calendar is known (``FEED_CALENDARS``): such a feed is stale only when its last
success predates the publication of the newest completed bar that should have
been fetched by now — for equities the session close plus ``DEFAULT_GRACE``;
for UTC-day forex/crypto bars the first scheduled ingest run after the bar
completes (an America/New_York wall-clock cron, so 00:30 UTC in EST but 23:30
UTC — a day later — in EDT) plus ``DEFAULT_GRACE``. A
weekend or exchange holiday publishes no new bar, so it never makes a feed
stale; a missed weekday run still does (incident 2026-11-09: the Monday 00:10
UTC alert named ``massive_fx`` only because Saturday/Sunday have no completed
forex bar to fetch). Feeds without a known calendar keep the plain age rule
(``DEFAULT_STALE_AFTER``).
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import DataFeedStatus
from signalforge.db.session import session_scope
from signalforge.db.types import utcnow
from signalforge.observability import get_logger

_log = get_logger("data.feeds")

# A feed with no success within this window is considered stale for status display.
DEFAULT_STALE_AFTER = timedelta(hours=36)

# Calendar-aware feeds: how long a due bar may stay unfetched before the feed
# is stale. Equities: measured from the session close (the EOD/grouped ingests
# run 17:30-18:15 ET, 1.5-2.25h after a 16:00 close). Forex/crypto: measured
# from the first scheduled ingest run after the UTC day completes (see
# ``UTC_DAY_INGEST_AT``). Either way a whole missed run alerts the same day.
DEFAULT_GRACE = timedelta(hours=12)

# Trading calendar per (provider, feed_type) — BAR_DAILY only:
#   xnys        — U.S. equity sessions (holidays + early closes); a bar is
#                 available at the session's regular-hours close.
#   fx_weekdays — completed UTC-day forex bars, Monday-Friday only (the forex
#                 ingest drops the weekend's partial bars, and records success
#                 only when a new weekday is due); available at 00:00 UTC.
#   utc_daily   — completed UTC-day crypto bars, seven days a week.
# Provider labels are literals (not imports) to keep this module free of the
# ingest layers; tests pin them to the producers' constants.
XNYS = "xnys"
FX_WEEKDAYS = "fx_weekdays"
UTC_DAILY = "utc_daily"
FEED_CALENDARS: dict[tuple[str, str], str] = {
    ("massive", "BAR_DAILY"): XNYS,
    ("massive_grouped", "BAR_DAILY"): XNYS,
    ("massive_fx", "BAR_DAILY"): FX_WEEKDAYS,
    ("massive_crypto", "BAR_DAILY"): UTC_DAILY,
}
_LOOKBACK_DAYS = 14

# Wall-clock time of the daily ingest that fetches each UTC-day calendar's
# bars (scheduler ``forex_ingest`` / ``crypto_ingest`` crons, JobSpec default
# tz America/New_York; a test pins these to ``default_job_specs()``). Because
# the cron is in New York time, the run that first fetches UTC day D's bar is
# D+1 00:30 UTC in EST but D+1 23:30 UTC in EDT: the grace must be measured
# from that run, not from the bar's 00:00 UTC availability.
UTC_DAY_INGEST_TZ = ZoneInfo("America/New_York")
UTC_DAY_INGEST_AT: dict[str, time] = {FX_WEEKDAYS: time(19, 30), UTC_DAILY: time(19, 45)}


def _first_run_at_or_after(available: datetime, run_at: time) -> datetime:
    """First daily ``run_at`` (New York wall clock) at or after ``available``."""
    local = available.astimezone(UTC_DAY_INGEST_TZ)
    run = datetime.combine(local.date(), run_at, tzinfo=UTC_DAY_INGEST_TZ)
    if run < available:
        run = datetime.combine(local.date() + timedelta(days=1), run_at, tzinfo=UTC_DAY_INGEST_TZ)
    return run.astimezone(UTC)


def _utc_day_bar_due(now: datetime, grace: timedelta, *, calendar: str) -> datetime:
    """Availability time (00:00 UTC of the next day) of the newest completed
    UTC-day bar whose first scheduled ingest run is past its grace at ``now``."""
    weekdays_only = calendar == FX_WEEKDAYS
    run_at = UTC_DAY_INGEST_AT[calendar]
    d = now.astimezone(UTC).date()
    for back in range(_LOOKBACK_DAYS + 1):
        day = d - timedelta(days=back)
        if weekdays_only and day.weekday() >= 5:
            continue
        available = datetime.combine(day + timedelta(days=1), time(0), tzinfo=UTC)
        if _first_run_at_or_after(available, run_at) + grace <= now:
            return available
    raise ValueError("no completed UTC-day bar in the lookback window")


def _xnys_bar_due(now: datetime, grace: timedelta) -> datetime:
    """Regular-hours close (UTC; early closes honoured) of the newest XNYS
    session that is past its grace period at ``now``."""
    from signalforge.data.calendar import rth_bounds_utc, sessions

    d = now.astimezone(UTC).date()
    for s in reversed(sessions(d - timedelta(days=_LOOKBACK_DAYS), d)):
        bounds = rth_bounds_utc(s)
        if bounds is not None and bounds[1] + grace <= now:
            return bounds[1]
    raise ValueError("no completed XNYS session in the lookback window")


def bar_due_since(calendar: str, now: datetime, grace: timedelta = DEFAULT_GRACE) -> datetime:
    """When the newest bar this calendar owes by ``now`` became available. A
    feed whose last success is older than this has missed a due bar."""
    if calendar == XNYS:
        return _xnys_bar_due(now, grace)
    if calendar in UTC_DAY_INGEST_AT:
        return _utc_day_bar_due(now, grace, calendar=calendar)
    raise ValueError(f"unknown feed calendar {calendar!r}")


def _row_to_dict(
    row: DataFeedStatus, *, stale_after: timedelta, grace: timedelta, now: datetime
) -> dict[str, Any]:
    last = row.last_success_at
    age_seconds = (now - last).total_seconds() if last else None
    calendar = FEED_CALENDARS.get((row.provider, row.feed_type.value))
    due_since: datetime | None = None
    if calendar is not None:
        try:
            due_since = bar_due_since(calendar, now, grace)
        except Exception as exc:
            # Calendar unavailable (e.g. exchange-calendar data exhausted):
            # fall back to the plain age rule, loudly, so a permanent fallback
            # (weekend false alerts returning) is visible in the worker log.
            _log.warning(
                "feed.calendar_fallback",
                provider=row.provider,
                calendar=calendar,
                error=repr(exc)[:200],
            )
            calendar = None
    if last is None or last > now:
        is_stale = True
    elif due_since is not None:
        is_stale = last < due_since
    else:
        is_stale = (now - last) > stale_after
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
        "calendar": calendar,
        "bar_due_since": due_since.isoformat() if due_since else None,
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
    grace: timedelta = DEFAULT_GRACE,
) -> dict[str, Any]:
    """``now`` is the clock every ``age_seconds``/``is_stale`` value is measured
    against. Callers that already run on an injected clock (the readiness gate,
    the alert planner) pass theirs so one clock governs every freshness
    decision; everyone else gets the wall clock.

    ``grace`` applies to calendar-aware feeds (``FEED_CALENDARS``);
    ``stale_after`` to every other feed."""
    now = now or utcnow()
    if session is not None:
        rows = list(session.scalars(select(DataFeedStatus).order_by(DataFeedStatus.provider)))
        feeds = [_row_to_dict(r, stale_after=stale_after, grace=grace, now=now) for r in rows]
    else:
        with session_scope() as own:
            rows = list(own.scalars(select(DataFeedStatus).order_by(DataFeedStatus.provider)))
            feeds = [_row_to_dict(r, stale_after=stale_after, grace=grace, now=now) for r in rows]
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
