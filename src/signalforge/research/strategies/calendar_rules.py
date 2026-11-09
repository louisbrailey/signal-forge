"""Exchange-calendar lookups for calendar-driven entry rules.

The NYSE session calendar is deterministic and published years ahead, so a
strategy may ask "is the next session the last one of this month?" at bar
``t`` without any look-ahead: nothing here reads a future *bar*, only the
future *calendar*. Sessions are cached per calendar year because the rules
are evaluated once per bar per symbol over two decades of history.
"""

from __future__ import annotations

from bisect import bisect_right
from datetime import date, datetime
from functools import lru_cache

from signalforge.data.calendar import sessions

__all__ = [
    "as_session_date",
    "next_sessions",
    "is_last_session_of_month",
    "is_penultimate_session_of_month",
]


def as_session_date(stamp: date | datetime) -> date:
    return stamp.date() if isinstance(stamp, datetime) else stamp


@lru_cache(maxsize=64)
def _year_sessions(year: int) -> tuple[date, ...]:
    # Run into the following January so December's month end always resolves.
    return sessions(date(year, 1, 1), date(year + 1, 1, 31))


def next_sessions(d: date | datetime, n: int) -> tuple[date, ...]:
    """The ``n`` exchange sessions strictly after ``d`` (``d`` itself excluded)."""
    day = as_session_date(d)
    ss = _year_sessions(day.year)
    i = bisect_right(ss, day)
    return ss[i : i + n]


def is_last_session_of_month(d: date | datetime) -> bool:
    """True when no later session of ``d``'s month exists."""
    day = as_session_date(d)
    nxt = next_sessions(day, 1)
    return bool(nxt) and (nxt[0].year, nxt[0].month) != (day.year, day.month)


def is_penultimate_session_of_month(d: date | datetime) -> bool:
    """True when exactly one more session of ``d``'s month follows ``d``."""
    day = as_session_date(d)
    nxt = next_sessions(day, 2)
    if len(nxt) < 2:
        return False
    same = (nxt[0].year, nxt[0].month) == (day.year, day.month)
    return same and (nxt[1].year, nxt[1].month) != (day.year, day.month)
