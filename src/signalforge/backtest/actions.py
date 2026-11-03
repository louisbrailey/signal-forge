"""Raw-price corporate-action accounting and decision-time split normalization."""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from signalforge.data.series import PriceSeries


@dataclass(frozen=True)
class Split:
    symbol: str
    day: date
    ratio: Decimal  # new shares / old shares
    source: str

    def __post_init__(self) -> None:
        if not self.ratio.is_finite() or self.ratio <= 0 or not self.source:
            raise ValueError("Verified positive split ratio and source required")


@dataclass(frozen=True)
class Dividend:
    symbol: str
    ex_date: date
    pay_date: date
    amount: Decimal  # actual USD per share at the ex-date, not back-adjusted
    source: str
    currency: str = "USD"

    def __post_init__(self) -> None:
        if (
            not self.amount.is_finite()
            or self.amount < 0
            or self.currency != "USD"
            or self.pay_date < self.ex_date
            or not self.source
        ):
            raise ValueError("USD cash dividend with valid ex/pay dates required")


def decision_series(raw: PriceSeries, t: int, splits: tuple[Split, ...]) -> PriceSeries:
    """Normalize past bars ONLY for splits already effective at this decision.

    Execution always uses raw bars. Historical volumes are multiplied inversely
    to prices so historical dollar volume is invariant. Future splits are ignored.
    """
    prefix = raw.head(t)
    arrays = [a.copy() for a in (prefix.open, prefix.high, prefix.low, prefix.close, prefix.volume)]
    for action in splits:
        if action.symbol != raw.symbol or action.day > prefix.dates[-1]:
            continue
        stop = bisect_left(prefix.dates, action.day)
        ratio = float(action.ratio)
        for a in arrays[:4]:
            a[:stop] /= ratio
        arrays[4][:stop] *= ratio
    return PriceSeries(raw.symbol, prefix.dates, *arrays)


@dataclass(frozen=True)
class TickerChange:
    old: str
    new: str
    effective: date
    source: str
    evidence: str

    def __post_init__(self) -> None:
        if (
            not self.old
            or not self.new
            or self.old == self.new
            or not self.source
            or not self.evidence
        ):
            raise ValueError("Verified identity-change evidence required")


def stitch_ticker(old: PriceSeries, new: PriceSeries, change: TickerChange) -> PriceSeries:
    """Only explicit 1:1 ticker changes; no fabricated dates or inferred mergers."""
    from signalforge.data.calendar import sessions

    if old.symbol != change.old or new.symbol != change.new:
        raise ValueError("Ticker mapping does not match input symbols")
    rows: list[tuple[date, float, float, float, float, float]] = []
    for bars, before in ((old, True), (new, False)):
        for i, day in enumerate(bars.dates):
            if (day < change.effective) == before:
                rows.append(
                    (
                        day,
                        float(bars.open[i]),
                        float(bars.high[i]),
                        float(bars.low[i]),
                        float(bars.close[i]),
                        float(bars.volume[i]),
                    )
                )
    if not rows or tuple(r[0] for r in rows) != tuple(sessions(rows[0][0], rows[-1][0])):
        raise ValueError("Ticker seam missing sessions, overlapping or unordered")
    if not any(r[0] < change.effective for r in rows) or not any(
        r[0] >= change.effective for r in rows
    ):
        raise ValueError("Both ticker legs required")
    return PriceSeries.from_bars(change.new, rows)
