"""Calendar continuity for 24/7 crypto research. Missing bars are never filled."""

from collections.abc import Sequence
from datetime import date, datetime, timedelta


def missing_intervals(
    stamps: Sequence[date] | Sequence[datetime],
    step: timedelta,
    *,
    start: date | datetime | None = None,
    end: date | datetime | None = None,
) -> int:
    """Count absent expected timestamps, including supplied boundary dates.

    Interior gaps are measured on the native calendar (daily or hourly), not
    compressed into adjacent trading bars. Empty bounded windows fail closed.
    """
    if not stamps:
        return max(1, int((end - start) / step) + 1) if start and end else 1
    lo, hi = start or stamps[0], end or stamps[-1]
    observed = {d for d in stamps if lo <= d <= hi}
    expected = int((hi - lo) / step) + 1
    return max(0, expected - len(observed))
