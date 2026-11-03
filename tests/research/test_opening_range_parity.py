"""Opening-range optimisation must preserve every causal value of the old scan."""

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

from signalforge.data.series import PriceSeries
from signalforge.research.features.intraday import opening_range


@pytest.mark.parametrize("intraday", [False, True])
def test_opening_range_matches_full_history_reference(intraday: bool) -> None:
    rows = []
    for day in range(12):
        # Include a shortened session and missing bars; never invent a bar.
        for bar in range((14 if day == 4 else 26) if intraday else 1):
            stamp = (
                (datetime(2024, 1, 2, 14, 30, tzinfo=UTC) + timedelta(days=day, minutes=15 * bar))
                if intraday
                else (date(2024, 1, 2) + timedelta(days=day))
            )
            x = 100 + day + bar / 10
            rows.append((stamp, x, x + 1, x - 1, x, 1000))
    series = PriceSeries.from_bars("X", rows)
    for t in range(len(series)):
        for k in (2, 3, 4):
            stamp = series.dates[t]
            day = stamp.date() if isinstance(stamp, datetime) else stamp
            idx = [
                i
                for i in range(t + 1)
                if (
                    series.dates[i].date()
                    if isinstance(series.dates[i], datetime)
                    else series.dates[i]
                )
                == day
            ]
            expected = (
                (float(np.max(series.high[idx[:k]])), float(np.min(series.low[idx[:k]])))
                if len(idx) >= k
                else (float("nan"), float("nan"))
            )
            np.testing.assert_equal(opening_range(series.head(t), t, k), expected)


def test_batched_calendar_counts_match_individual_sessions_at_dst_and_early_closes() -> None:
    from signalforge.data.calendar import rth_bar_counts, sessions
    from signalforge.data.intraday_coverage import expected_rth_bars

    lo, hi = date(2024, 11, 1), date(2024, 12, 26)
    for size in ("15m", "1h"):
        counts = rth_bar_counts(lo, hi, size)
        assert list(counts) == list(sessions(lo, hi))
        assert counts == {d: expected_rth_bars(d, size) for d in sessions(lo, hi)}
        assert date(2024, 11, 28) not in counts
