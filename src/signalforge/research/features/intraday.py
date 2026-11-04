"""Intraday feature functions (Phase 2).

``series`` here is a :class:`~signalforge.data.series.PriceSeries` whose ``dates``
are timezone-aware datetimes. Point-in-time: index ``t`` reads only ``<= t``.
"""

from __future__ import annotations

from bisect import bisect_left
from datetime import datetime, time

import numpy as np

from signalforge.data.series import PriceSeries
from signalforge.research.features.daily import atr as _atr

NAN = float("nan")


def _session_date(series: PriceSeries, i: int):  # type: ignore[no-untyped-def]
    d = series.dates[i]
    return d.date() if isinstance(d, datetime) else d


def _session_start(series: PriceSeries, t: int) -> int:
    stamp = series.dates[t]
    boundary = (
        datetime.combine(stamp.date(), time.min, tzinfo=stamp.tzinfo)
        if isinstance(stamp, datetime)
        else stamp
    )
    return bisect_left(series.dates, boundary, 0, t + 1)


def bars_since_open(series: PriceSeries, t: int) -> int:
    """Number of bars so far in the session that contains bar ``t`` (0 = first bar)."""
    return t - _session_start(series, t)


def opening_range(series: PriceSeries, t: int, k_bars: int) -> tuple[float, float]:
    """(high, low) of the first ``k_bars`` bars of bar ``t``'s session, or (nan, nan)
    if the session has not yet produced ``k_bars`` bars at ``t``."""
    # PriceSeries is chronological: a session is contiguous. Walking only its
    # suffix avoids scanning years of earlier sessions on every intraday bar.
    start = _session_start(series, t)
    if t - start + 1 < k_bars:
        return NAN, NAN
    hi = float(np.max(series.high[start : start + k_bars]))
    lo = float(np.min(series.low[start : start + k_bars]))
    return hi, lo


def atr_intraday(series: PriceSeries, t: int, window: int = 14) -> float:
    return _atr(series, t, window)


def session_bar_count(series: PriceSeries, t: int) -> int:
    """Total bars in bar ``t``'s session up to and including ``t``."""
    return bars_since_open(series, t) + 1
