"""D6 §11 — the clock cross-check, the no-submit windows, the early close.

Drills V10 (``adapter.clock()`` disagreeing with the local calendar blocks) and
V12 (submission on an early-close session is refused unless the early close is
explicitly handled AND the adapter's clock agrees).

Every date here is a real XNYS session read through ``data/options_calendar.py``,
not a mocked calendar: the whole point of §11 is that two independent sources are
compared, and comparing a source against a mock of itself proves nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from signalforge.data import options_calendar
from signalforge.execution import calendarcheck
from signalforge.execution.intents import MarketClock
from signalforge.execution.limits import may_open
from tests.execution.conftest import clean_open_context

# 2025-06-17 is an ordinary Tuesday session; 14:00 UTC is 10:00 ET, half an hour
# after the open and well clear of both no-submit windows.
MID_SESSION = datetime(2025, 6, 17, 14, 0, tzinfo=UTC)
# 2025-07-03 is the NYSE half-day before Independence Day (13:00 ET close).
EARLY_CLOSE_SESSION = datetime(2025, 7, 3, 14, 0, tzinfo=UTC)
# A Saturday.
CLOSED_DAY = datetime(2025, 6, 21, 14, 0, tzinfo=UTC)


def _clock(is_open: bool, at: datetime) -> MarketClock:
    return MarketClock(is_open=is_open, as_of=at)


def test_the_early_close_date_this_module_relies_on_is_real() -> None:
    """If the fixture date stopped being a half-day, the V12 test below would
    silently become a test of an ordinary session."""
    assert options_calendar.is_early_close(EARLY_CLOSE_SESSION.date())
    assert not options_calendar.is_early_close(MID_SESSION.date())


def test_an_agreeing_open_session_permits_opening() -> None:
    verdict = calendarcheck.evaluate(MID_SESSION, _clock(True, MID_SESSION))

    assert verdict.agreement_ok
    assert verdict.market_open_broker is True
    assert verdict.market_open_calendar is True
    assert not verdict.blocks_opening
    assert verdict.minutes_since_open == pytest.approx(30.0, abs=1.0)
    assert verdict.minutes_until_close == pytest.approx(360.0, abs=1.0)
    assert verdict.is_early_close_session is False


def test_a_disagreeing_clock_blocks() -> None:
    """Drill V10. The broker says closed, the calendar says open."""
    verdict = calendarcheck.evaluate(MID_SESSION, _clock(False, MID_SESSION))

    assert not verdict.agreement_ok
    assert verdict.blocks_opening
    assert "BLOCKED" in verdict.detail
    # Both sides are reported separately so may_open's C1 can name which said what.
    assert verdict.market_open_broker is False
    assert verdict.market_open_calendar is True


def test_the_gate_refuses_when_the_two_sources_disagree(limit_set: object) -> None:
    decision = may_open(
        clean_open_context(market_open_broker=False, market_open_calendar=True),
        limit_set,  # type: ignore[arg-type]
    )
    assert not decision.allowed
    assert "disagree" in {c.name: c.detail for c in decision.checks}["C1"]


def test_an_unreachable_adapter_is_not_a_closed_market() -> None:
    """ "Could not ask" is a third answer, distinct from open and from closed."""
    verdict = calendarcheck.evaluate(MID_SESSION, None)

    assert verdict.market_open_broker is None
    assert not verdict.agreement_ok
    assert verdict.blocks_opening


def test_a_drifted_broker_clock_disagrees_even_when_both_say_open() -> None:
    """A broker whose own timestamp is a minute out is not agreeing; it is
    disagreeing about what time it is."""
    from datetime import timedelta

    drifted = MarketClock(is_open=True, as_of=MID_SESSION + timedelta(seconds=120))
    verdict = calendarcheck.evaluate(MID_SESSION, drifted)

    assert not verdict.agreement_ok
    assert "differs from" in verdict.detail


def test_a_non_session_day_resolves_to_closed_and_has_no_session_bounds() -> None:
    verdict = calendarcheck.evaluate(CLOSED_DAY, _clock(False, CLOSED_DAY))

    # The two sources AGREE that it is closed — and opening is still blocked,
    # because C1 requires the market to be open, not merely agreed about.
    assert verdict.agreement_ok
    assert verdict.market_open_calendar is False
    assert verdict.blocks_opening
    assert verdict.minutes_since_open is None
    assert verdict.session_end_utc is None


def test_an_early_close_session_is_measured_against_the_OPTIONS_close() -> None:
    """13:00 ET is an asserted market-structure constant, not a schedule read."""
    verdict = calendarcheck.evaluate(EARLY_CLOSE_SESSION, _clock(True, EARLY_CLOSE_SESSION))

    assert verdict.is_early_close_session is True
    assert verdict.session_end_utc is not None
    from zoneinfo import ZoneInfo

    assert verdict.session_end_utc.astimezone(ZoneInfo("America/New_York")).hour == 13
    # 14:00 UTC is 10:00 ET; the 13:00 ET close is 180 minutes away.
    assert verdict.minutes_until_close == pytest.approx(180.0, abs=1.0)


def test_an_early_close_session_blocks_by_default(limit_set: object) -> None:
    """Drill V12."""
    verdict = calendarcheck.evaluate(EARLY_CLOSE_SESSION, _clock(True, EARLY_CLOSE_SESSION))
    assert verdict.early_close_explicitly_handled is False

    decision = may_open(
        clean_open_context(
            is_early_close_session=True,
            early_close_explicitly_handled=False,
        ),
        limit_set,  # type: ignore[arg-type]
    )
    assert not decision.allowed
    assert "early-close session" in {c.name: c.detail for c in decision.checks}["C3"]


def test_an_early_close_is_only_handled_when_the_clock_also_agrees() -> None:
    """The operator's flag alone never earns it: the calendar must have resolved
    the close AND the adapter must agree with the resulting session shape."""
    agreeing = calendarcheck.evaluate(
        EARLY_CLOSE_SESSION, _clock(True, EARLY_CLOSE_SESSION), allow_early_close=True
    )
    assert agreeing.early_close_explicitly_handled is True

    disagreeing = calendarcheck.evaluate(
        EARLY_CLOSE_SESSION, _clock(False, EARLY_CLOSE_SESSION), allow_early_close=True
    )
    assert disagreeing.early_close_explicitly_handled is False


def test_a_date_outside_the_supported_window_is_refused_not_extrapolated() -> None:
    far_future = datetime(2040, 6, 17, 14, 0, tzinfo=UTC)
    verdict = calendarcheck.evaluate(far_future, _clock(True, far_future))

    assert verdict.market_open_calendar is None
    assert verdict.is_early_close_session is None
    assert verdict.blocks_opening


# ---------------------------------------------------------------------------
# The no-submit windows — evaluated by may_open against the limits row
# ---------------------------------------------------------------------------


def test_the_post_open_window_blocks(limit_set: object) -> None:
    decision = may_open(clean_open_context(minutes_since_open=5.0), limit_set)  # type: ignore[arg-type]
    assert not decision.allowed
    assert "post-open no-submit window" in {c.name: c.detail for c in decision.checks}["C2"]


def test_the_pre_close_window_blocks(limit_set: object) -> None:
    decision = may_open(clean_open_context(minutes_until_close=5.0), limit_set)  # type: ignore[arg-type]
    assert not decision.allowed
    assert "pre-close no-submit window" in {c.name: c.detail for c in decision.checks}["C2"]


def test_unmeasurable_windows_block(limit_set: object) -> None:
    decision = may_open(
        clean_open_context(minutes_since_open=None, minutes_until_close=None),
        limit_set,  # type: ignore[arg-type]
    )
    assert not decision.allowed


# ---------------------------------------------------------------------------
# §11 — the underlying allowlist, ASSERTED rather than assumed
# ---------------------------------------------------------------------------


def test_a_pm_settled_underlying_is_in_scope() -> None:
    calendarcheck.assert_underlying_in_scope("spy")  # no raise


def test_an_underlying_outside_the_table_is_refused() -> None:
    """AM-settled cash index options are out of scope, and an underlying the
    table has never heard of is refused rather than defaulted into scope."""
    with pytest.raises(options_calendar.CalendarUnresolved, match="not in the version-controlled"):
        calendarcheck.assert_underlying_in_scope("SPX")
