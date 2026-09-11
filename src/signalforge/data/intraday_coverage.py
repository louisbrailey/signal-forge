"""Does the intraday store actually hold a tradeable RTH history?

One question, asked against the database rather than assumed: for a given bar
size, source and span, does EVERY symbol have EVERY regular-hours bar of EVERY
exchange session the NYSE calendar says existed?

This is what promotion gate 0 asks for an INTRADAY strategy (design
``docs/research/designs/intraday_orb.md`` §2.2). The tolerances are frozen at
100 %: a coverage bar that can later be relaxed to obtain a pass is a latent
threshold, and the backfill is operator-controlled end to end, so there is no
legitimate reason to accept less than the calendar says exists.

Deliberately strict about *which* rows count:

* ``bar_size`` must match the configured research bar size exactly — a 5m
  backfill does not satisfy a 15m strategy;
* ``source`` must match the run's source filter — research reads ``massive``
  only (map rule R6);
* ``is_simulated`` rows never count, at all;
* ``session`` must be ``rth`` — pre/post bars are excluded from the count AND
  reported, because ``features.intraday._session_date`` groups by calendar
  date and a post-market bar would corrupt the next session's opening range.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge.data.calendar import rth_bounds
from signalforge.data.calendar import sessions as calendar_sessions
from signalforge.data.repository import SourceFilter
from signalforge.db.models import Instrument, OHLCVIntraday

_ET = ZoneInfo("America/New_York")

BAR_MINUTES: dict[str, int] = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60}

# How many offending items a report names before it says "and N more" — the
# evidence blob goes into an audit row, so it must stay bounded.
_MAX_LISTED = 8


def bar_minutes(bar_size: str) -> int:
    try:
        return BAR_MINUTES[bar_size]
    except KeyError:
        raise ValueError(
            f"unsupported bar_size {bar_size!r}; known: {sorted(BAR_MINUTES)}"
        ) from None


def expected_rth_bars(day: date, bar_size: str) -> int:
    """Bars a full RTH session of ``day`` should contain at ``bar_size``.

    Derived from the exchange calendar itself rather than from a hard-coded
    half-day list: 09:30-16:00 gives 26 bars at 15m, and the calendar's own
    13:00 early closes give 14 — no constant to drift, and no list to forget
    to update."""
    bounds = rth_bounds(day)
    if bounds is None:
        return 0
    minutes = int((bounds[1] - bounds[0]).total_seconds() // 60)
    return minutes // bar_minutes(bar_size)


@dataclass(frozen=True, slots=True)
class SymbolCoverage:
    symbol: str
    sessions_expected: int
    sessions_covered: int  # sessions with the FULL expected bar count
    missing_sessions: list[str] = field(default_factory=list)  # no bars at all
    short_sessions: list[dict[str, Any]] = field(default_factory=list)  # some, not all
    extra_sessions: list[str] = field(default_factory=list)  # bars on a non-session
    rows: int = 0

    @property
    def complete(self) -> bool:
        return (
            self.sessions_expected > 0
            and self.sessions_covered == self.sessions_expected
            and not self.missing_sessions
            and not self.short_sessions
            and not self.extra_sessions
        )

    @property
    def coverage_fraction(self) -> float:
        if not self.sessions_expected:
            return 0.0
        return self.sessions_covered / self.sessions_expected

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "sessions_expected": self.sessions_expected,
            "sessions_covered": self.sessions_covered,
            "coverage_fraction": round(self.coverage_fraction, 6),
            "rows": self.rows,
            "missing_sessions": self.missing_sessions[:_MAX_LISTED],
            "missing_sessions_total": len(self.missing_sessions),
            "short_sessions": self.short_sessions[:_MAX_LISTED],
            "short_sessions_total": len(self.short_sessions),
            "extra_sessions": self.extra_sessions[:_MAX_LISTED],
            "extra_sessions_total": len(self.extra_sessions),
            "complete": self.complete,
        }


@dataclass(frozen=True, slots=True)
class IntradayCoverageReport:
    bar_size: str
    source: str
    start: date
    end: date
    sessions_expected: int
    per_symbol: list[SymbolCoverage]
    rows_counted: int
    rows_rejected_non_rth: int
    rows_rejected_simulated: int
    rows_other_bar_size: int
    rows_other_source: int
    newest_session: date | None
    staleness_sessions: int | None  # sessions between newest_session and the span end

    @property
    def complete(self) -> bool:
        return bool(self.per_symbol) and all(s.complete for s in self.per_symbol)

    @property
    def incomplete_symbols(self) -> list[SymbolCoverage]:
        return [s for s in self.per_symbol if not s.complete]

    def detail(self) -> str:
        if not self.sessions_expected:
            return (
                f"no exchange sessions in {self.start}..{self.end} — nothing to cover "
                f"(bar size {self.bar_size}, source {self.source!r})"
            )
        if self.complete:
            return (
                f"100% RTH coverage at {self.bar_size} from {self.source!r}: "
                f"{len(self.per_symbol)} symbols x {self.sessions_expected} exchange sessions "
                f"({self.start}..{self.end}), {self.rows_counted} bars, every session at its "
                f"full calendar bar count"
            )
        bad = self.incomplete_symbols
        worst = sorted(bad, key=lambda s: s.coverage_fraction)[:_MAX_LISTED]
        parts = [
            f"{s.symbol} {s.sessions_covered}/{s.sessions_expected}"
            + (f" (-{len(s.missing_sessions)} absent" if s.missing_sessions else "")
            + (f" -{len(s.short_sessions)} short" if s.short_sessions else "")
            + (f" +{len(s.extra_sessions)} off-calendar" if s.extra_sessions else "")
            + (")" if (s.missing_sessions or s.short_sessions or s.extra_sessions) else "")
            for s in worst
        ]
        msg = (
            f"incomplete intraday history at {self.bar_size} from {self.source!r} over "
            f"{self.start}..{self.end}: {len(bad)}/{len(self.per_symbol)} symbols short of "
            f"100% of {self.sessions_expected} exchange sessions — " + "; ".join(parts)
        )
        if len(bad) > _MAX_LISTED:
            msg += f"; and {len(bad) - _MAX_LISTED} more"
        extras = []
        if self.rows_rejected_non_rth:
            extras.append(f"{self.rows_rejected_non_rth} non-RTH rows ignored")
        if self.rows_rejected_simulated:
            extras.append(f"{self.rows_rejected_simulated} SIMULATED rows ignored")
        if self.rows_other_bar_size:
            extras.append(f"{self.rows_other_bar_size} rows at another bar size")
        if self.rows_other_source:
            extras.append(f"{self.rows_other_source} rows from another source")
        if extras:
            msg += " [" + "; ".join(extras) + "]"
        return msg

    def to_dict(self) -> dict[str, Any]:
        return {
            "bar_size": self.bar_size,
            "source": self.source,
            "span": f"{self.start}..{self.end}",
            "sessions_expected": self.sessions_expected,
            "symbols": len(self.per_symbol),
            "complete": self.complete,
            "rows_counted": self.rows_counted,
            "rows_rejected_non_rth": self.rows_rejected_non_rth,
            "rows_rejected_simulated": self.rows_rejected_simulated,
            "rows_other_bar_size": self.rows_other_bar_size,
            "rows_other_source": self.rows_other_source,
            "newest_session": self.newest_session.isoformat() if self.newest_session else None,
            "staleness_sessions": self.staleness_sessions,
            "per_symbol": [s.to_dict() for s in self.per_symbol],
            "coverage_requirement": "100% of exchange sessions, 100% of each session's bars",
        }


def _first_source(source: SourceFilter) -> str:
    if isinstance(source, str):
        return source
    if source:
        return next(iter(source))
    return ""


def intraday_rth_coverage(
    session: Session,
    symbols: Sequence[str],
    *,
    start: date,
    end: date,
    bar_size: str,
    source: SourceFilter = None,
) -> IntradayCoverageReport:
    """Per-symbol RTH session coverage of ``ohlcv_intraday`` over ``[start, end]``.

    Read-only. Counts only rows that are simultaneously the right bar size,
    the right source, real (not simulated) and ``session == 'rth'``; every
    other row is counted separately and reported, never silently dropped."""
    syms = [s.strip().upper() for s in symbols]
    expected_sessions = list(calendar_sessions(start, end))
    expected_by_day = {d: expected_rth_bars(d, bar_size) for d in expected_sessions}
    src = _first_source(source)

    lo = datetime.combine(start, datetime.min.time(), tzinfo=UTC)
    hi = datetime.combine(end, datetime.max.time(), tzinfo=UTC)

    def _base(*extra: Any) -> Any:
        stmt = (
            select(Instrument.symbol, OHLCVIntraday.bar_start)
            .join(Instrument, OHLCVIntraday.instrument_id == Instrument.id)
            .where(
                Instrument.symbol.in_(syms),
                OHLCVIntraday.bar_start >= lo,
                OHLCVIntraday.bar_start <= hi,
            )
        )
        for clause in extra:
            stmt = stmt.where(clause)
        return stmt

    counted = _base(
        OHLCVIntraday.bar_size == bar_size,
        OHLCVIntraday.is_simulated.is_(False),
        OHLCVIntraday.session == "rth",
    )
    if source is not None:
        counted = counted.where(
            OHLCVIntraday.source == source
            if isinstance(source, str)
            else OHLCVIntraday.source.in_(list(source))
        )

    per_symbol_days: dict[str, dict[date, int]] = {s: {} for s in syms}
    rows_counted = 0
    for sym, bar_start in session.execute(counted).yield_per(10_000):
        stamp: datetime = bar_start
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=UTC)
        day = stamp.astimezone(_ET).date()
        days = per_symbol_days.setdefault(str(sym), {})
        days[day] = days.get(day, 0) + 1
        rows_counted += 1

    def _count(*extra: Any) -> int:
        stmt = (
            select(func.count(OHLCVIntraday.id))
            .join(Instrument, OHLCVIntraday.instrument_id == Instrument.id)
            .where(
                Instrument.symbol.in_(syms),
                OHLCVIntraday.bar_start >= lo,
                OHLCVIntraday.bar_start <= hi,
            )
        )
        for clause in extra:
            stmt = stmt.where(clause)
        return int(session.scalar(stmt) or 0)

    rejected_non_rth = _count(OHLCVIntraday.bar_size == bar_size, OHLCVIntraday.session != "rth")
    rejected_simulated = _count(
        OHLCVIntraday.bar_size == bar_size, OHLCVIntraday.is_simulated.is_(True)
    )
    other_bar_size = _count(OHLCVIntraday.bar_size != bar_size)
    other_source = (
        _count(OHLCVIntraday.bar_size == bar_size, OHLCVIntraday.source != src) if src else 0
    )

    per_symbol: list[SymbolCoverage] = []
    newest: date | None = None
    for sym in syms:
        days = per_symbol_days.get(sym, {})
        missing: list[str] = []
        short: list[dict[str, Any]] = []
        covered = 0
        for d in expected_sessions:
            want = expected_by_day[d]
            got = days.get(d, 0)
            if got == 0:
                missing.append(d.isoformat())
            elif got < want or got > want:
                short.append({"session": d.isoformat(), "bars": got, "expected": want})
            else:
                covered += 1
        extra_days = sorted(d.isoformat() for d in days if d not in expected_by_day)
        per_symbol.append(
            SymbolCoverage(
                symbol=sym,
                sessions_expected=len(expected_sessions),
                sessions_covered=covered,
                missing_sessions=missing,
                short_sessions=short,
                extra_sessions=extra_days,
                rows=sum(days.values()),
            )
        )
        if days:
            newest = max(newest, max(days)) if newest else max(days)

    staleness: int | None = None
    if newest is not None and expected_sessions:
        staleness = sum(1 for d in expected_sessions if d > newest)

    return IntradayCoverageReport(
        bar_size=bar_size,
        source=src or "any",
        start=start,
        end=end,
        sessions_expected=len(expected_sessions),
        per_symbol=per_symbol,
        rows_counted=rows_counted,
        rows_rejected_non_rth=rejected_non_rth,
        rows_rejected_simulated=rejected_simulated,
        rows_other_bar_size=other_bar_size,
        rows_other_source=other_source,
        newest_session=newest,
        staleness_sessions=staleness,
    )
