"""Gate 9 warm-up lead-in (2026-11-02): the sealed-window backtest is fed
history from before the window so long-lookback rules are not scored "0
trades" by construction, while only trades ENTERED inside the window count."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

from signalforge.research.promotion import (
    SEALED_WARMUP_LEAD_DAYS,
    _sealed_window_trades,
    sealed_lead_start,
)


def test_lead_start_covers_a_twelve_month_lookback_plus_a_ten_month_average() -> None:
    sealed_start = date(2025, 9, 8)
    lead = sealed_lead_start(sealed_start)
    assert lead == sealed_start - timedelta(days=SEALED_WARMUP_LEAD_DAYS)
    # ~252 trading sessions per 365 days: 730 days is comfortably >= 462 sessions.
    assert SEALED_WARMUP_LEAD_DAYS * 252 / 365 >= 252 + 210


def test_only_entries_inside_the_window_are_scored_whatever_the_exit() -> None:
    lo, hi = date(2024, 9, 7), date(2025, 9, 7)
    t = lambda d: SimpleNamespace(entry_date=d, pnl_r=1.0)  # noqa: E731
    trades = [
        t(lo - timedelta(days=1)),  # lead-in entry, exits inside: excluded
        t(lo),  # first day of the window: included
        t(datetime(2025, 3, 3, 14, 30, tzinfo=UTC)),  # intraday stamp inside: included
        t(hi),  # last day: included
        t(hi + timedelta(days=1)),  # after the window: excluded
    ]
    kept = _sealed_window_trades(trades, lo, hi)
    assert [x.entry_date for x in kept] == [lo, datetime(2025, 3, 3, 14, 30, tzinfo=UTC), hi]
