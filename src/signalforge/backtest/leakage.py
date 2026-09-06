"""Look-ahead / leakage detectors, used by the test suite.

``feature_fn`` must have the signature ``(series, t) -> float`` and must index
**relative to ``t``** (e.g. ``series.close[t-9:t+1]``), never ``series.close[-1]``
or a fixed absolute offset. ``assert_no_lookahead`` calls it once with the series
truncated to ``t`` and once with the full series; a correct feature returns the
same value both times. If it does not, it is reading bars after ``t``.
"""

from __future__ import annotations

from collections.abc import Callable

from signalforge.data.series import PriceSeries

FeatureFn = Callable[[PriceSeries, int], float]


class LookaheadDetected(AssertionError):
    pass


def assert_no_lookahead(
    feature_fn: FeatureFn,
    series: PriceSeries,
    *,
    indices: list[int] | None = None,
    tol: float = 1e-9,
) -> None:
    n = len(series)
    check = indices or list(range(max(1, n - 25), n - 1))
    for t in check:
        truncated = feature_fn(series.head(t), t)
        full = feature_fn(series, t)
        if truncated != truncated:  # NaN
            continue
        if abs(truncated - full) > tol:
            raise LookaheadDetected(
                f"feature at t={t} changed from {truncated!r} to {full!r} when future "
                "bars were revealed — it is reading the future"
            )
