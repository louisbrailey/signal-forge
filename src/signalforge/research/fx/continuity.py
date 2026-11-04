"""Calendar continuity for 24/7 crypto research. Missing bars are never filled.

Admissibility policy (pre-registered 2026-11-03, PREREGISTRATION_round2_2026-11-03.md §0):
a pair's series is admissible for a research or sealed window when its missing bars are at
most ``max_missing_frac`` of the expected bars AND its longest interior gap is at most
``max_gap_bars``. Anything beyond that fails closed for the whole strategy, exactly as the
zero-tolerance rule did (BNBUSD's 1,735-day hole, XLMUSD's 177-day hole, XRPUSD's 192-hour
hourly gap are all out). Within policy, gaps are counted and reported, never filled: the
engine still treats the surviving bars as adjacent, which is disclosed in every report.
"""

from collections.abc import Sequence
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class ContinuityPolicy:
    max_missing_frac: float
    max_gap_bars: int


#: Daily bars: at most 1% missing and no interior hole longer than a week.
DAILY_POLICY = ContinuityPolicy(max_missing_frac=0.01, max_gap_bars=7)
#: Hourly bars: at most 1% missing and no interior hole longer than two days.
HOURLY_POLICY = ContinuityPolicy(max_missing_frac=0.01, max_gap_bars=48)


def policy_for(step: timedelta) -> ContinuityPolicy:
    return HOURLY_POLICY if step < timedelta(days=1) else DAILY_POLICY


@dataclass(frozen=True, slots=True)
class GapProfile:
    missing: int
    expected: int
    longest_gap: int

    @property
    def missing_frac(self) -> float:
        return self.missing / self.expected if self.expected else 1.0


def gap_profile(
    stamps: Sequence[date] | Sequence[datetime],
    step: timedelta,
    *,
    start: date | datetime | None = None,
    end: date | datetime | None = None,
) -> GapProfile:
    """Missing-bar count (as ``missing_intervals``), expected bars, and the
    longest run of consecutive missing bars inside ``[start, end]``."""
    missing = missing_intervals(stamps, step, start=start, end=end)
    if not stamps:
        return GapProfile(missing, missing, missing)
    lo, hi = start or stamps[0], end or stamps[-1]
    inside = sorted(d for d in stamps if lo <= d <= hi)
    expected = int((hi - lo) / step) + 1
    longest = 0
    if inside:
        longest = max(longest, int(round((inside[0] - lo) / step)))
        longest = max(longest, int(round((hi - inside[-1]) / step)))
        for a, b in zip(inside[:-1], inside[1:], strict=True):
            longest = max(longest, int(round((b - a) / step)) - 1)
    else:
        longest = expected
    return GapProfile(missing, expected, longest)


def continuity_breach(
    stamps: Sequence[date] | Sequence[datetime],
    step: timedelta,
    *,
    start: date | datetime | None = None,
    end: date | datetime | None = None,
    policy: ContinuityPolicy | None = None,
) -> str | None:
    """``None`` when the series is admissible under the policy, else the reason."""
    pol = policy or policy_for(step)
    g = gap_profile(stamps, step, start=start, end=end)
    if g.missing == 0:
        return None
    if g.missing_frac > pol.max_missing_frac or g.longest_gap > pol.max_gap_bars:
        return (
            f"missing {g.missing} of {g.expected} bars ({100 * g.missing_frac:.2f}%, longest gap "
            f"{g.longest_gap} bars) exceeds the admissibility policy "
            f"(<= {100 * pol.max_missing_frac:.0f}% and gaps <= {pol.max_gap_bars} bars)"
        )
    return None
