"""Option expiry / DTE / session-shape arithmetic (D2 §11).

Two consumers from day one: the options backtest engine, and — later — the
execution layer's OMS, which must cross-check a broker clock against this module
and **block on disagreement** (program map §6.4).  The design rules that make one
module serve both (D2 §11.1) are enforced here:

1. **Pure functions of explicit arguments.**  No DB session, no network, and the
   wall clock is never read: :func:`clock_agreement` and :func:`market_phase`
   take ``now`` from the caller.  A backtest calls them at a 2023 date; the OMS
   calls them at the present instant; both take the same code path.
2. **Depends only on** :mod:`signalforge.data.calendar`.  No import of
   ``backtest``, ``research``, ``paper``, or any future ``execution`` package, so
   the order path can import this without dragging the research stack with it.
3. **Deterministic and cacheable**, following ``calendar.py``'s ``lru_cache``.
4. **Every return is total.**  An unresolvable expiry, close time, or phase
   *raises* :class:`CalendarUnresolved` rather than returning a plausible wrong
   answer.  A calendar function on the order path that guesses is the input that
   turns a no-submit window into a submission.

``dte`` is a two-headed word (D2 §11.4), so no bare ``dte()`` is exposed:
:func:`calendar_dte` and :func:`session_dte` are named separately and a strategy
must interpolate which one it used into its spec text.

**Deliberately NOT derived from the calendar library** (D2 §11.3): the 13:00 ET
options close on an early-close session, and settlement style.  Both are asserted
market-structure facts, not schedule data, so they live in the explicitly-sourced
constant tables below and :func:`settlement_style` *raises* for an underlying that
is not in its table rather than defaulting.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from functools import lru_cache
from zoneinfo import ZoneInfo

from signalforge.data import calendar

_EASTERN = ZoneInfo("America/New_York")

# The window this module will answer questions about at all.  Outside it every
# total function raises rather than trusting an extrapolated schedule.  Version
# controlled on purpose: widening it is a deliberate edit, not a silent default.
SUPPORTED_START = date(1990, 1, 1)
SUPPORTED_END = date(2035, 12, 31)

# --- asserted market-structure constants (D2 §11.3) -------------------------
# Source: general market structure — US equity-option trading ends at 16:00 ET on
# a regular session and 13:00 ET on an NYSE half-day.  The operator must verify
# both against their own broker before anything is armed (program map §6.7a).
# These are NOT read from pandas-market-calendars: that library carries the
# *equity* close, which is 13:00 on a half-day but is not itself a statement
# about option trading hours.
REGULAR_OPTIONS_CLOSE = time(16, 0)
EARLY_OPTIONS_CLOSE = time(13, 0)

_EARLY_CLOSE_EQUITY_CUTOFF = time(16, 0)


class SettlementStyle(StrEnum):
    PM_PHYSICAL = "pm_physical"
    AM_CASH = "am_cash"


# Source: ETF and single-name listed options are PM-settled and physically
# settled.  AM/cash settlement (the cash index complex — SPX, NDX, RUT) is OUT OF
# SCOPE for Phase 1, and an underlying missing from this table RAISES.  That is
# how the scope boundary is enforced rather than merely documented (D2 §11.3).
_SETTLEMENT_STYLE: dict[str, SettlementStyle] = {
    "SPY": SettlementStyle.PM_PHYSICAL,
    "QQQ": SettlementStyle.PM_PHYSICAL,
    "IWM": SettlementStyle.PM_PHYSICAL,
    "DIA": SettlementStyle.PM_PHYSICAL,
    "AAPL": SettlementStyle.PM_PHYSICAL,
    "MSFT": SettlementStyle.PM_PHYSICAL,
    "NVDA": SettlementStyle.PM_PHYSICAL,
    "AMZN": SettlementStyle.PM_PHYSICAL,
    "GOOGL": SettlementStyle.PM_PHYSICAL,
    "META": SettlementStyle.PM_PHYSICAL,
}


class Phase(StrEnum):
    PRE = "pre"
    RTH = "rth"
    POST = "post"
    CLOSED = "closed"


class Verdict(StrEnum):
    AGREE = "agree"
    DISAGREE = "disagree"
    UNDETERMINED = "undetermined"


class CalendarUnresolved(RuntimeError):
    """This module cannot justify an answer, so it refuses to invent one."""


@dataclass(frozen=True, slots=True)
class BrokerClockView:
    """What a broker adapter says about the market right now.

    ``is_open`` is ``None`` when the adapter could not report it — which is an
    ``UNDETERMINED`` verdict, never an ``AGREE``.
    """

    is_open: bool | None
    timestamp: datetime | None = None


@dataclass(frozen=True, slots=True)
class ClockAgreement:
    verdict: Verdict
    detail: str

    @property
    def blocks(self) -> bool:
        """The OMS blocks on anything that is not ``AGREE`` (D2 §11.2)."""
        return self.verdict is not Verdict.AGREE


def _require_supported(d: date) -> None:
    if not (SUPPORTED_START <= d <= SUPPORTED_END):
        raise CalendarUnresolved(
            f"{d.isoformat()} is outside this module's supported range "
            f"{SUPPORTED_START.isoformat()}..{SUPPORTED_END.isoformat()}"
        )


# ---------------------------------------------------------------------------
# Expiry resolution
# ---------------------------------------------------------------------------


def _preceding_session(d: date) -> date:
    """The latest XNYS session at or before ``d``."""
    _require_supported(d)
    probe = d
    for _ in range(15):
        if calendar.is_session(probe):
            return probe
        probe -= timedelta(days=1)
    raise CalendarUnresolved(f"no XNYS session at or before {d.isoformat()}")


def _third_friday(year: int, month: int) -> date:
    first = date(year, month, 1)
    # weekday(): Monday=0 .. Friday=4
    offset = (4 - first.weekday()) % 7
    return first + timedelta(days=offset + 14)


@lru_cache(maxsize=2048)
def monthly_expiry(year: int, month: int) -> date:
    """Third Friday; if that Friday is not an XNYS session, the preceding session.

    No expiry data feed is needed for monthlies — the holiday rule is answered by
    ``calendar.is_session`` (D2 §11.3).
    """
    friday = _third_friday(year, month)
    _require_supported(friday)
    return friday if calendar.is_session(friday) else _preceding_session(friday)


def weekly_expiries(start: date, end: date) -> tuple[date, ...]:
    """Every Friday-anchored expiry in ``[start, end]``, holiday-adjusted.

    Calendar-derived, not data-derived: it says which dates *would* be Friday
    expiries, not which weekly series a venue actually listed.  A caller that
    needs listed weeklies must intersect this with observed contracts.
    """
    if end < start:
        return ()
    _require_supported(start)
    _require_supported(end)
    out: list[date] = []
    d = start + timedelta(days=(4 - start.weekday()) % 7)
    while d <= end:
        resolved = d if calendar.is_session(d) else _preceding_session(d)
        if start <= resolved <= end and resolved not in out:
            out.append(resolved)
        d += timedelta(days=7)
    return tuple(sorted(out))


def expiries_between(start: date, end: date, *, monthly_only: bool) -> tuple[date, ...]:
    if end < start:
        return ()
    if not monthly_only:
        return weekly_expiries(start, end)
    _require_supported(start)
    _require_supported(end)
    out: list[date] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        exp = monthly_expiry(y, m)
        if start <= exp <= end:
            out.append(exp)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return tuple(out)


def is_expiry(d: date, *, monthly_only: bool = False) -> bool:
    if monthly_only:
        return d == monthly_expiry(d.year, d.month)
    return d in weekly_expiries(d, d)


def cycle_of(d: date) -> date:
    """The monthly expiry whose cycle contains ``d`` (the next monthly at/after ``d``)."""
    exp = monthly_expiry(d.year, d.month)
    if exp >= d:
        return exp
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return monthly_expiry(y, m)


# ---------------------------------------------------------------------------
# DTE — both senses, named so they cannot be confused (D2 §11.4)
# ---------------------------------------------------------------------------


def calendar_dte(as_of: date, expiry: date) -> int:
    """Calendar days from ``as_of`` to ``expiry`` (negative once past)."""
    return (expiry - as_of).days


def session_dte(as_of: date, expiry: date) -> int:
    """XNYS sessions in ``(as_of, expiry]`` — 0 on the expiry session itself."""
    if expiry <= as_of:
        return 0
    _require_supported(as_of)
    _require_supported(expiry)
    after = as_of + timedelta(days=1)
    return calendar.session_count(after, expiry)


def last_trade_session(expiry: date) -> date:
    """The last session on which the contract trades.

    Phase 1 is PM-settled only, so that is the expiry session itself (rolled back
    to the preceding session if the nominal expiry date is not an XNYS session).
    """
    return _preceding_session(expiry)


def force_close_session(expiry: date) -> date:
    """The ``expiry - 1`` session on which the engine closes unconditionally."""
    last = last_trade_session(expiry)
    return _preceding_session(last - timedelta(days=1))


# ---------------------------------------------------------------------------
# Session shape — the OMS cross-check surface
# ---------------------------------------------------------------------------


def is_early_close(d: date) -> bool:
    """True on an XNYS half-day.  Derived from the schedule, not a holiday list."""
    _require_supported(d)
    bounds = calendar.rth_bounds(d)
    return bounds is not None and bounds[1].time() < _EARLY_CLOSE_EQUITY_CUTOFF


def options_close_time(d: date) -> time:
    """13:00 ET on an early close, 16:00 ET otherwise.  RAISES on a non-session.

    A wrong close time on a half-day is exactly the input that turns a no-submit
    window into a submission, so an unresolvable session is refused (D2 §11.1).
    """
    _require_supported(d)
    if not calendar.is_session(d):
        raise CalendarUnresolved(f"{d.isoformat()} is not an XNYS session; no options close time")
    return EARLY_OPTIONS_CLOSE if is_early_close(d) else REGULAR_OPTIONS_CLOSE


def market_phase(dt: datetime) -> Phase:
    """``PRE`` | ``RTH`` | ``POST`` | ``CLOSED``.  RAISES if unresolvable.

    ``dt`` is supplied by the caller — this module never reads the wall clock.
    """
    eastern_date = dt.date() if dt.tzinfo is None else dt.astimezone(_EASTERN).date()
    _require_supported(eastern_date)
    return Phase(calendar.session_of(dt))


def clock_agreement(now: datetime, broker_clock: BrokerClockView) -> ClockAgreement:
    """Compare our calendar's verdict at ``now`` against a broker's clock.

    Fail-closed by construction: anything this function cannot resolve returns
    ``UNDETERMINED``, and the OMS treats ``UNDETERMINED`` exactly as ``DISAGREE``
    — it blocks, and writes ``detail`` to the audit trail in **every** non-``AGREE``
    case (D2 §11.2).
    """
    try:
        phase = market_phase(now)
    except CalendarUnresolved as exc:
        return ClockAgreement(Verdict.UNDETERMINED, f"calendar cannot resolve {now!r}: {exc}")

    if broker_clock.is_open is None:
        return ClockAgreement(
            Verdict.UNDETERMINED, f"broker reported no open/closed state; local phase {phase.value}"
        )

    if broker_clock.timestamp is not None:
        drift = abs((broker_clock.timestamp - now).total_seconds())
        if drift > 60.0:
            return ClockAgreement(
                Verdict.DISAGREE,
                f"broker timestamp {broker_clock.timestamp.isoformat()} differs from "
                f"{now.isoformat()} by {drift:.0f}s",
            )

    local_open = phase is Phase.RTH
    if local_open == broker_clock.is_open:
        return ClockAgreement(
            Verdict.AGREE, f"local phase {phase.value}; broker is_open={broker_clock.is_open}"
        )
    return ClockAgreement(
        Verdict.DISAGREE,
        f"local phase {phase.value} (open={local_open}) but broker is_open={broker_clock.is_open}",
    )


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------


def settlement_style(underlying: str) -> SettlementStyle:
    """RAISES for an underlying not in the constant table — never defaults."""
    key = underlying.strip().upper()
    try:
        return _SETTLEMENT_STYLE[key]
    except KeyError:
        raise CalendarUnresolved(
            f"settlement style for {key!r} is not in the version-controlled table; "
            "Phase 1 covers PM-settled, physically-settled ETF and single-name options only"
        ) from None
