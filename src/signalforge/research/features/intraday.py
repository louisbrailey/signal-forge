"""Intraday feature functions (Phase 2).

``series`` here is a :class:`~signalforge.data.series.PriceSeries` whose ``dates``
are timezone-aware datetimes. Point-in-time: index ``t`` reads only ``<= t``.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np

from signalforge.data.series import PriceSeries
from signalforge.research.features.daily import atr as _atr

NAN = float("nan")


def _session_date(series: PriceSeries, i: int):  # type: ignore[no-untyped-def]
    d = series.dates[i]
    return d.date() if isinstance(d, datetime) else d


def bars_since_open(series: PriceSeries, t: int) -> int:
    """Number of bars so far in the session that contains bar ``t`` (0 = first bar)."""
    day = _session_date(series, t)
    n = 0
    i = t
    while i >= 0 and _session_date(series, i) == day:
        n += 1
        i -= 1
    return n - 1


def opening_range(series: PriceSeries, t: int, k_bars: int) -> tuple[float, float]:
    """(high, low) of the first ``k_bars`` bars of bar ``t``'s session, or (nan, nan)
    if the session has not yet produced ``k_bars`` bars at ``t``."""
    day = _session_date(series, t)
    idxs = [i for i in range(t + 1) if _session_date(series, i) == day]
    if len(idxs) < k_bars:
        return NAN, NAN
    first_k = idxs[:k_bars]
    hi = float(np.max(series.high[first_k]))
    lo = float(np.min(series.low[first_k]))
    return hi, lo


def atr_intraday(series: PriceSeries, t: int, window: int = 14) -> float:
    return _atr(series, t, window)


def session_bar_count(series: PriceSeries, t: int) -> int:
    """Total bars in bar ``t``'s session up to and including ``t``."""
    return bars_since_open(series, t) + 1
