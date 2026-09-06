"""US equity trading sessions (NYSE) via pandas-market-calendars.

Used to reject weekend/holiday dates and to compute holding periods in sessions
rather than calendar days.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache

import pandas_market_calendars as mcal


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
