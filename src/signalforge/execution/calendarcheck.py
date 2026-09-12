"""Clock, calendar, and the no-submit windows (D6 §11).

``adapter.clock()`` alone is not a rule. Two sources of truth that disagree
about whether the market is open is exactly the condition under which an order
must not be sent, so every cycle cross-checks the broker's own clock against
``data/options_calendar.py`` and **disagreement blocks**.

FACT: ``options_calendar.clock_agreement`` is already written for this consumer
and is already fail-closed — anything it cannot resolve is ``UNDETERMINED``,
which this module treats exactly as ``DISAGREE``. It is a pure function of an
explicit ``now``, so the OMS and the backtest take the same code path, and the
wall clock is never read here.

What this module adds on top of that agreement:

* the **post-open** and **pre-close** no-submit windows, both operator-set in
  ``execution_limits``, measured against the calendar's own session bounds
  rather than the broker's;
* **early-close sessions block by default** — permitted only when the calendar
  resolves the early close explicitly (13:00 ET, an asserted market-structure
  constant in ``options_calendar``, not a schedule read) **and** the adapter's
  clock agrees;
* the **underlying allowlist assertion** (§11, map §2.8): AM-settled cash index
  options are out of scope, and the OMS asserts that per intent rather than
  assuming it.

Every value this module hands to ``may_open`` is tri-state. ``None`` means "could
not be evaluated", and ``limits.may_open`` blocks on ``None``. Nothing here
returns a plausible default: a wrong close time on a half-day is precisely the
input that turns a no-submit window into a submission.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from signalforge.data import calendar as _calendar
from signalforge.data import options_calendar as _options_calendar
from signalforge.execution.intents import MarketClock

_EASTERN = ZoneInfo("America/New_York")

__all__ = [
    "CalendarVerdict",
    "assert_underlying_in_scope",
    "evaluate",
]


@dataclass(frozen=True, slots=True)
class CalendarVerdict:
    """Everything C1/C2/C3 need, as read this cycle.

    ``market_open_calendar`` and ``market_open_broker`` are reported separately
    and are BOTH handed to ``may_open``: the gate's C1 blocks on disagreement,
    which it cannot do if this module collapses them into one boolean first.
    """

    market_open_broker: bool | None
    market_open_calendar: bool | None
    agreement_ok: bool
    minutes_since_open: float | None
    minutes_until_close: float | None
    is_early_close_session: bool | None
    early_close_explicitly_handled: bool
    session_end_utc: datetime | None
    detail: str

    @property
    def blocks_opening(self) -> bool:
        """A convenience for the cycle's audit line. ``may_open`` re-derives this
        from the individual fields; this property never substitutes for it."""
        return not (
            self.agreement_ok
            and self.market_open_broker is True
            and self.market_open_calendar is True
        )


def _rth_bounds_utc(now: datetime) -> tuple[datetime, datetime] | None:
    """The session's UTC open/close, with the OPTIONS close substituted on a
    half-day.

    FACT: ``calendar.rth_bounds_utc`` returns the **equity** close, which is
    13:00 ET on an NYSE half-day. ``options_calendar.options_close_time`` is the
    asserted market-structure constant for *option* trading hours and is the one
    the no-submit window must be measured against — they coincide at 13:00 today,
    and this code does not rely on that coincidence.
    """
    eastern = now.astimezone(_EASTERN)
    bounds = _calendar.rth_bounds_utc(eastern.date())
    if bounds is None:
        return None
    open_utc, _equity_close_utc = bounds
    close_t = _options_calendar.options_close_time(eastern.date())
    close_eastern = eastern.replace(
        hour=close_t.hour, minute=close_t.minute, second=0, microsecond=0
    )
    return open_utc, close_eastern.astimezone(open_utc.tzinfo)


def evaluate(
    now: datetime,
    clock: MarketClock | None,
    *,
    allow_early_close: bool = False,
) -> CalendarVerdict:
    """Cross-check the broker clock against the local calendar and measure the
    no-submit windows. Never raises: an unresolvable calendar is reported as
    ``None`` fields, which block.

    ``clock=None`` models an unreachable adapter. It is NOT "assume closed" and
    it is NOT "assume open": ``market_open_broker`` stays ``None`` and C1 fails
    with "could not be evaluated", which is the same verdict as a disagreement
    and a different one from "the market is closed".

    The no-submit WINDOW arithmetic deliberately does not live here: this module
    reports ``minutes_since_open`` / ``minutes_until_close`` and ``limits.may_open``
    compares them against ``execution_limits``. One rule, one place — a second
    copy of the comparison is a second thing to drift.

    ``allow_early_close`` is the §11 escape hatch and it is deliberately narrow:
    it only has effect when the calendar resolved the early-close time itself
    AND the adapter's clock agrees. The operator setting it does not make an
    unresolved session submittable.
    """
    broker_open = clock.is_open if clock is not None else None
    detail_parts: list[str] = []

    try:
        agreement = _options_calendar.clock_agreement(
            now,
            _options_calendar.BrokerClockView(
                is_open=broker_open,
                timestamp=clock.as_of if clock is not None else None,
            ),
        )
        agreement_ok = agreement.verdict is _options_calendar.Verdict.AGREE
        detail_parts.append(agreement.detail)
    except Exception as exc:  # pragma: no cover - clock_agreement is total by design
        return CalendarVerdict(
            market_open_broker=broker_open,
            market_open_calendar=None,
            agreement_ok=False,
            minutes_since_open=None,
            minutes_until_close=None,
            is_early_close_session=None,
            early_close_explicitly_handled=False,
            session_end_utc=None,
            detail=f"the clock cross-check could not be evaluated ({type(exc).__name__}: {exc})",
        )

    try:
        phase = _options_calendar.market_phase(now)
        calendar_open: bool | None = phase is _options_calendar.Phase.RTH
    except _options_calendar.CalendarUnresolved as exc:
        calendar_open = None
        detail_parts.append(f"phase unresolved: {exc}")

    minutes_since_open: float | None = None
    minutes_until_close: float | None = None
    session_end_utc: datetime | None = None
    is_early_close: bool | None = None
    early_close_handled = False
    try:
        eastern_date = now.astimezone(_EASTERN).date()
        is_early_close = _options_calendar.is_early_close(eastern_date)
        bounds = _rth_bounds_utc(now)
        if bounds is not None:
            open_utc, close_utc = bounds
            session_end_utc = close_utc
            minutes_since_open = (now - open_utc).total_seconds() / 60.0
            minutes_until_close = (close_utc - now).total_seconds() / 60.0
            # The early close is "explicitly handled" only because the close time
            # came from options_calendar's asserted constant table and the
            # adapter's clock agrees with the resulting session shape. An
            # operator flag alone never earns this.
            early_close_handled = bool(allow_early_close and agreement_ok)
            detail_parts.append(
                f"session {open_utc.isoformat()} -> {close_utc.isoformat()}"
                + (" (EARLY CLOSE)" if is_early_close else "")
            )
        else:
            detail_parts.append(f"{eastern_date.isoformat()} is not an XNYS session")
    except _options_calendar.CalendarUnresolved as exc:
        is_early_close = None
        detail_parts.append(f"session bounds unresolved: {exc}")
    except Exception as exc:  # pragma: no cover - defensive; every field stays None
        is_early_close = None
        detail_parts.append(f"session bounds could not be evaluated: {type(exc).__name__}: {exc}")

    if not agreement_ok:
        # A disagreement must not be softened by a window that happens to pass.
        detail_parts.insert(0, "BLOCKED: broker clock and local calendar do not agree")

    return CalendarVerdict(
        market_open_broker=broker_open,
        # A disagreement is surfaced to C1 as a genuine mismatch, never repaired
        # here: limits.may_open prints which side said what, and that string is
        # what ends up in execution_event.
        market_open_calendar=calendar_open,
        agreement_ok=agreement_ok,
        minutes_since_open=minutes_since_open,
        minutes_until_close=minutes_until_close,
        is_early_close_session=is_early_close,
        early_close_explicitly_handled=early_close_handled,
        session_end_utc=session_end_utc,
        detail="; ".join(detail_parts),
    )


def assert_underlying_in_scope(underlying: str) -> None:
    """§11 — AM-settled cash index options are out of scope by the allowlist, and
    the OMS ASSERTS it per intent rather than assuming it.

    ``options_calendar.settlement_style`` raises for an underlying that is not in
    its version-controlled table, which is the enforcement: an unknown underlying
    is refused rather than defaulted to the permitted style.
    """
    style = _options_calendar.settlement_style(underlying)
    if style is not _options_calendar.SettlementStyle.PM_PHYSICAL:
        raise _options_calendar.CalendarUnresolved(
            f"{underlying.upper()} settles {style.value}; Phase 1 covers PM-settled, "
            "physically-settled ETF and single-name options only (D6 §11, map §2.8)"
        )
