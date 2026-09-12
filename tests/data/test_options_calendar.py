"""``options_calendar`` (D2 §11) — expiries, DTE, session shape, clock agreement.

Two consumers from day one: the backtest, and the execution layer's OMS.  The
tests that matter most are the ones asserting a function **raises** rather than
guessing: a calendar function on the order path that returns a plausible wrong
close time is the input that turns a no-submit window into a submission.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest

from signalforge.data import options_calendar as oc

# ---------------------------------------------------------------------------
# Monthly expiries and the holiday rule (D2 §11.3 — §15.2 test 18)
# ---------------------------------------------------------------------------


def test_monthly_expiry_is_the_third_friday() -> None:
    assert oc.monthly_expiry(2024, 3) == date(2024, 3, 15)
    assert oc.monthly_expiry(2024, 1) == date(2024, 1, 19)
    assert oc.monthly_expiry(2025, 6) == date(2025, 6, 20)


def test_a_holiday_third_friday_falls_back_to_the_preceding_session() -> None:
    """April 2003: the third Friday (2003-04-18) was Good Friday, not an XNYS session."""
    assert date(2003, 4, 18).weekday() == 4
    assert oc.monthly_expiry(2003, 4) == date(2003, 4, 17)
    # And a month whose third Friday IS a session resolves to that Friday.
    assert oc.monthly_expiry(2015, 4) == date(2015, 4, 17)


def test_expiries_between_monthly_and_weekly() -> None:
    monthlies = oc.expiries_between(date(2024, 1, 1), date(2024, 4, 30), monthly_only=True)
    assert monthlies == (
        date(2024, 1, 19),
        date(2024, 2, 16),
        date(2024, 3, 15),
        date(2024, 4, 19),
    )
    weeklies = oc.expiries_between(date(2024, 3, 1), date(2024, 3, 31), monthly_only=False)
    assert date(2024, 3, 15) in weeklies
    assert date(2024, 3, 29) not in weeklies  # Good Friday rolls back
    assert date(2024, 3, 28) in weeklies


def test_is_expiry_and_cycle_of() -> None:
    assert oc.is_expiry(date(2024, 3, 15), monthly_only=True)
    assert not oc.is_expiry(date(2024, 3, 14), monthly_only=True)
    assert oc.cycle_of(date(2024, 3, 1)) == date(2024, 3, 15)
    assert oc.cycle_of(date(2024, 3, 16)) == date(2024, 4, 19)
    assert oc.cycle_of(date(2024, 12, 25)) == date(2025, 1, 17)


# ---------------------------------------------------------------------------
# DTE is a two-headed word (D2 §11.4 — §15.2 test 21)
# ---------------------------------------------------------------------------


def test_calendar_dte_and_session_dte_disagree_where_they_should() -> None:
    as_of, expiry = date(2024, 3, 1), date(2024, 3, 15)
    assert oc.calendar_dte(as_of, expiry) == 14
    assert oc.session_dte(as_of, expiry) == 10
    assert oc.calendar_dte(expiry, expiry) == 0
    assert oc.session_dte(expiry, expiry) == 0


def test_no_bare_dte_is_exposed() -> None:
    assert not hasattr(oc, "dte")


def test_last_trade_and_force_close_sessions() -> None:
    assert oc.last_trade_session(date(2024, 3, 15)) == date(2024, 3, 15)
    assert oc.force_close_session(date(2024, 3, 15)) == date(2024, 3, 14)
    # A Good-Friday expiry rolls both back through the holiday.
    assert oc.last_trade_session(date(2024, 3, 29)) == date(2024, 3, 28)
    assert oc.force_close_session(date(2024, 3, 29)) == date(2024, 3, 27)


# ---------------------------------------------------------------------------
# Session shape (D2 §11.1 rule 4, §11.3 — §15.2 tests 19, 29)
# ---------------------------------------------------------------------------


def test_is_early_close_is_derived_from_the_schedule_not_a_holiday_list() -> None:
    assert oc.is_early_close(date(2024, 7, 3)) is True  # July 3rd half-day
    assert oc.is_early_close(date(2024, 7, 2)) is False


def test_options_close_time_is_13_00_on_a_half_day_and_16_00_otherwise() -> None:
    assert oc.options_close_time(date(2024, 7, 3)) == time(13, 0)
    assert oc.options_close_time(date(2024, 7, 2)) == time(16, 0)


def test_options_close_time_raises_on_a_non_session() -> None:
    with pytest.raises(oc.CalendarUnresolved):
        oc.options_close_time(date(2024, 7, 4))  # Independence Day
    with pytest.raises(oc.CalendarUnresolved):
        oc.options_close_time(date(2024, 7, 6))  # Saturday


def test_market_phase_classifies_and_raises_outside_the_supported_range() -> None:
    assert oc.market_phase(datetime(2024, 7, 2, 10, 0)) is oc.Phase.RTH
    assert oc.market_phase(datetime(2024, 7, 2, 8, 0)) is oc.Phase.PRE
    assert oc.market_phase(datetime(2024, 7, 2, 17, 0)) is oc.Phase.POST
    assert oc.market_phase(datetime(2024, 7, 4, 10, 0)) is oc.Phase.CLOSED
    with pytest.raises(oc.CalendarUnresolved):
        oc.market_phase(datetime(2099, 7, 2, 10, 0))


# ---------------------------------------------------------------------------
# Clock agreement is fail-closed by signature (D2 §11.2 — §15.2 test 29)
# ---------------------------------------------------------------------------


def test_clock_agreement_agrees_when_both_say_open() -> None:
    now = datetime(2024, 7, 2, 10, 0)
    got = oc.clock_agreement(now, oc.BrokerClockView(is_open=True, timestamp=now))
    assert got.verdict is oc.Verdict.AGREE
    assert got.blocks is False


def test_clock_agreement_disagrees_on_an_open_closed_split() -> None:
    now = datetime(2024, 7, 4, 10, 0)
    got = oc.clock_agreement(now, oc.BrokerClockView(is_open=True))
    assert got.verdict is oc.Verdict.DISAGREE
    assert got.blocks is True
    assert got.detail


def test_clock_agreement_disagrees_on_a_drifting_broker_timestamp() -> None:
    now = datetime(2024, 7, 2, 10, 0)
    got = oc.clock_agreement(
        now, oc.BrokerClockView(is_open=True, timestamp=now + timedelta(minutes=5))
    )
    assert got.verdict is oc.Verdict.DISAGREE


def test_an_unresolvable_session_is_UNDETERMINED_and_never_AGREE() -> None:
    """Fail-open by signature was the defect; ``UNDETERMINED`` blocks exactly as
    ``DISAGREE`` does, and the detail is always written."""
    got = oc.clock_agreement(datetime(2099, 7, 2, 10, 0), oc.BrokerClockView(is_open=False))
    assert got.verdict is oc.Verdict.UNDETERMINED
    assert got.blocks is True
    assert "cannot resolve" in got.detail

    unknown = oc.clock_agreement(datetime(2024, 7, 2, 10, 0), oc.BrokerClockView(is_open=None))
    assert unknown.verdict is oc.Verdict.UNDETERMINED
    assert unknown.blocks is True
    assert unknown.detail


# ---------------------------------------------------------------------------
# Settlement (D2 §11.3 — §15.2 test 20)
# ---------------------------------------------------------------------------


def test_settlement_style_raises_for_an_underlying_not_in_the_table() -> None:
    assert oc.settlement_style("spy") is oc.SettlementStyle.PM_PHYSICAL
    with pytest.raises(oc.CalendarUnresolved, match="PM-settled"):
        oc.settlement_style("SPX")  # AM/cash settled — out of scope for Phase 1


def test_the_module_reads_no_wall_clock() -> None:
    """Rule 1 of D2 §11.1: ``now`` always arrives from the caller."""
    source = __import__("pathlib").Path(oc.__file__).read_text(encoding="utf-8")
    assert "datetime.now(" not in source
    assert "now_eastern" not in source
