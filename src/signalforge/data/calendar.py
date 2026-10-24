"""US equity trading sessions (NYSE) via pandas-market-calendars.

Used to reject weekend/holiday dates, compute holding periods in sessions, and
classify an intraday timestamp as pre-market / regular hours / post-market.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache

import pandas as pd
import pandas_market_calendars as mcal

_RTH_OPEN = time(9, 30)
_RTH_CLOSE = time(16, 0)

# Bar sizes the intraday path understands, in minutes. Lives here — the
# lowest layer that already owns session arithmetic — so the adapter, the
# ingest chunker and the coverage query all read ONE definition.
BAR_MINUTES: dict[str, int] = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60}


def bar_minutes(bar_size: str) -> int:
    try:
        return BAR_MINUTES[bar_size]
    except KeyError:
        raise ValueError(
            f"unsupported bar_size {bar_size!r}; known: {sorted(BAR_MINUTES)}"
        ) from None


@lru_cache(maxsize=1)
def _xnys() -> mcal.MarketCalendar:
    return mcal.get_calendar("XNYS")


@lru_cache(maxsize=32)
def sessions(start: date, end: date) -> tuple[date, ...]:
    sched = _xnys().schedule(start_date=start.isoformat(), end_date=end.isoformat())
    return tuple(ts.date() for ts in sched.index)


def is_session(d: date) -> bool:
    return d in sessions(d, d)


def session_count(start: date, end: date) -> int:
    return len(sessions(start, end))


@lru_cache(maxsize=4096)
def rth_bounds_utc(d: date) -> tuple[datetime, datetime] | None:
    """(open, close) as tz-aware UTC datetimes for a regular session, else None."""
    sched = _xnys().schedule(start_date=d.isoformat(), end_date=d.isoformat())
    if sched.empty:
        return None
    open_ts = pd.Timestamp(sched.iloc[0]["market_open"]).tz_convert("UTC")
    close_ts = pd.Timestamp(sched.iloc[0]["market_close"]).tz_convert("UTC")
    return open_ts.to_pydatetime(), close_ts.to_pydatetime()


def last_closed_session(now: datetime) -> date:
    """The newest XNYS session whose regular-hours close is at or before ``now``.

    The ONE definition of "the current completed bar" shared by the scanner's
    stale-data exclusion and paper acceptance's freshness guard (incident
    2026-10-22: the scanner used a 17:30 ET cutoff while acceptance used the
    16:00 close, so a scan between the two produced candidates on the previous
    session that acceptance then had to refuse). Early closes use their real
    close. ``now`` must be timezone-aware.
    """
    d = now.astimezone(UTC).date()
    for candidate in reversed(sessions(d - timedelta(days=14), d)):
        bounds = rth_bounds_utc(candidate)
        if bounds is not None and bounds[1] <= now:
            return candidate
    raise ValueError("no completed market session in the last 14 days")


@lru_cache(maxsize=4096)
def rth_bounds(d: date) -> tuple[datetime, datetime] | None:
    """(open, close) in US/Eastern-naive wall time for a regular session, else None."""
    b = rth_bounds_utc(d)
    if b is None:
        return None
    o = pd.Timestamp(b[0]).tz_convert("America/New_York").to_pydatetime().replace(tzinfo=None)
    c = pd.Timestamp(b[1]).tz_convert("America/New_York").to_pydatetime().replace(tzinfo=None)
    return o, c


def _eastern_wall(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt  # assume already Eastern wall time
    return pd.Timestamp(dt).tz_convert("America/New_York").to_pydatetime().replace(tzinfo=None)


def session_of(dt: datetime) -> str:
    """``pre`` | ``rth`` | ``post`` | ``closed`` for an intraday timestamp."""
    wall = _eastern_wall(dt)
    if not is_session(wall.date()):
        return "closed"
    bounds = rth_bounds(wall.date())
    if bounds is None:
        return "closed"
    open_dt, close_dt = bounds
    if wall < open_dt:
        return "pre" if wall.time() >= time(4, 0) else "closed"
    if wall >= close_dt:
        return "post" if wall.time() < time(20, 0) else "closed"
    return "rth"


def is_rth(dt: datetime) -> bool:
    return session_of(dt) == "rth"


def now_eastern() -> datetime:
    return _eastern_wall(datetime.now(UTC))
