"""Calendar-aware feed staleness: a weekend or exchange holiday publishes no new
bar and must not make a feed stale; a missed due bar still must.

Incident 2026-11-09 00:10 UTC (Monday): the worker alerted
``feed.stale providers=['massive_fx', 'massive_grouped']``. ``massive_fx`` had
fetched Friday's completed bar on Saturday 00:31 UTC and correctly had nothing
to fetch since; ``massive_grouped`` had not succeeded since 2026-10-25.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from signalforge.data.adapters.base import FeedType
from signalforge.data.feeds import (
    DEFAULT_STALE_AFTER,
    FEED_CALENDARS,
    FX_WEEKDAYS,
    UTC_DAILY,
    XNYS,
    bar_due_since,
    feed_status_report,
)
from signalforge.db.models import DataFeedStatus
from signalforge.domain import LatencyCategory

pytestmark = pytest.mark.safety


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)  # type: ignore[misc]


def _feed(session: Session, provider: str, last_success: datetime | None) -> None:
    session.add(
        DataFeedStatus(
            provider=provider,
            feed_type=FeedType.BAR_DAILY,
            latency_category=LatencyCategory.END_OF_DAY,
            is_simulated=False,
            entitlement_note="",
            last_success_at=last_success,
            updated_at=last_success or _utc(2026, 1, 1),
        )
    )
    session.flush()


def _stale(session: Session, now: datetime) -> dict[str, bool]:
    return {f["provider"]: f["is_stale"] for f in feed_status_report(session, now=now)["feeds"]}


# --------------------------------------------------------------------------- #
# Incident replay
# --------------------------------------------------------------------------- #
def test_incident_replay_monday_0010_utc_only_grouped_is_stale(session: Session) -> None:
    now = _utc(2026, 11, 9, 0, 10)
    _feed(session, "massive_fx", _utc(2026, 11, 7, 0, 31, 25))
    _feed(session, "massive_grouped", _utc(2026, 10, 25, 22, 56, 31))
    _feed(session, "massive", _utc(2026, 11, 8, 23, 8, 48))
    _feed(session, "massive_crypto", _utc(2026, 11, 8, 0, 46, 39))

    assert _stale(session, now) == {
        "massive": False,
        "massive_crypto": False,
        "massive_fx": False,  # weekend: Friday's bar is the newest owed
        "massive_grouped": True,  # genuinely stale: two weeks of sessions missed
    }
    fx = next(
        f for f in feed_status_report(session, now=now)["feeds"] if f["provider"] == "massive_fx"
    )
    assert fx["calendar"] == FX_WEEKDAYS
    assert fx["bar_due_since"] == "2026-11-07T00:00:00+00:00"  # Friday's UTC day closed
    assert fx["age_seconds"] > DEFAULT_STALE_AFTER.total_seconds()  # the old rule fired


def test_incident_replay_alert_names_only_the_genuinely_stale_feed(session: Session) -> None:
    from signalforge.alerts.dispatch import plan_alerts
    from signalforge.domain import AlertType

    now = _utc(2026, 11, 9, 0, 10)
    _feed(session, "massive_fx", _utc(2026, 11, 7, 0, 31, 25))
    _feed(session, "massive_grouped", _utc(2026, 10, 25, 22, 56, 31))

    data = [p for p in plan_alerts(session, now) if p.alert_type is AlertType.DATA_ISSUE]
    assert len(data) == 1
    assert "massive_grouped/BAR_DAILY stale" in data[0].body
    assert "massive_fx" not in data[0].body


# --------------------------------------------------------------------------- #
# Forex: Monday-Friday UTC-day bars
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "now",
    [
        _utc(2026, 11, 7, 12, 0),  # Saturday
        _utc(2026, 11, 8, 23, 0),  # Sunday, after the ~22:00 reopen
        _utc(2026, 11, 9, 23, 59),  # Monday: Monday's bar is not complete yet
        _utc(2026, 11, 10, 12, 29),  # Tue: Monday's bar ingest (00:30 UTC) + grace
    ],
)
def test_fx_weekend_is_not_stale(session: Session, now: datetime) -> None:
    _feed(session, "massive_fx", _utc(2026, 11, 7, 0, 31))  # fetched Friday's bar
    assert _stale(session, now) == {"massive_fx": False}


def test_fx_missed_monday_bar_is_stale(session: Session) -> None:
    _feed(session, "massive_fx", _utc(2026, 11, 7, 0, 31))
    # Monday's bar completed Tue 00:00 UTC; the 19:30 ET (00:30 UTC in EST)
    # ingest owes it, and its 12h grace ends Tue 12:30 UTC.
    assert _stale(session, _utc(2026, 11, 10, 12, 31)) == {"massive_fx": True}


def test_fx_missed_weekday_run_is_stale(session: Session) -> None:
    # Last fetched Tuesday's bar (Wed 00:30); Wednesday's bar is overdue Thu 12:30.
    _feed(session, "massive_fx", _utc(2026, 11, 5, 0, 30))
    assert _stale(session, _utc(2026, 11, 5, 23, 0)) == {"massive_fx": False}
    assert _stale(session, _utc(2026, 11, 6, 12, 29)) == {"massive_fx": False}
    assert _stale(session, _utc(2026, 11, 6, 12, 31)) == {"massive_fx": True}


# --------------------------------------------------------------------------- #
# Equities: XNYS sessions (weekends, holidays, early closes)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("provider", ["massive", "massive_grouped"])
def test_equity_weekend_is_not_stale(session: Session, provider: str) -> None:
    _feed(session, provider, _utc(2026, 11, 6, 23, 30))  # Friday post-close ingest
    # Monday 08:00 UTC: Friday is still the newest owed session (age ~56.5h).
    assert _stale(session, _utc(2026, 11, 9, 8, 0)) == {provider: False}


def test_equity_holiday_is_not_stale(session: Session) -> None:
    # Thanksgiving Thu 2026-11-26 is an XNYS holiday: Wednesday's bar is the
    # newest owed until Friday's (early-close) session has its grace.
    _feed(session, "massive", _utc(2026, 11, 25, 22, 30))
    now = _utc(2026, 11, 27, 12, 0)
    assert now - _utc(2026, 11, 25, 22, 30) > DEFAULT_STALE_AFTER  # old rule: stale
    assert _stale(session, now) == {"massive": False}


def test_equity_early_close_is_owed_from_its_real_close(session: Session) -> None:
    # Fri 2026-11-27 closes 13:00 ET = 18:00 UTC; +12h grace = Sat 06:00 UTC.
    assert bar_due_since(XNYS, _utc(2026, 11, 28, 6, 0)) == _utc(2026, 11, 27, 18, 0)
    _feed(session, "massive", _utc(2026, 11, 25, 22, 30))
    assert _stale(session, _utc(2026, 11, 28, 5, 59)) == {"massive": False}
    assert _stale(session, _utc(2026, 11, 28, 6, 1)) == {"massive": True}


def test_equity_missed_weekday_session_is_stale(session: Session) -> None:
    # Last success after Tuesday's close; Wednesday's close (21:00 UTC) + 12h passes.
    _feed(session, "massive_grouped", _utc(2026, 11, 10, 22, 30))
    assert _stale(session, _utc(2026, 11, 12, 8, 59)) == {"massive_grouped": False}
    assert _stale(session, _utc(2026, 11, 12, 9, 1)) == {"massive_grouped": True}


# --------------------------------------------------------------------------- #
# Crypto: every UTC day
# --------------------------------------------------------------------------- #
def test_crypto_weekend_is_still_owed(session: Session) -> None:
    _feed(session, "massive_crypto", _utc(2026, 11, 7, 0, 45))  # fetched Friday's bar
    # Saturday's bar completed Sun 00:00 UTC; its 19:45 ET ingest is Sun 00:45
    # UTC (EST), so it is overdue Sun 12:45 UTC.
    assert _stale(session, _utc(2026, 11, 8, 12, 44)) == {"massive_crypto": False}
    assert _stale(session, _utc(2026, 11, 8, 12, 46)) == {"massive_crypto": True}
    assert bar_due_since(UTC_DAILY, _utc(2026, 11, 8, 12, 46)) == _utc(2026, 11, 8)


# --------------------------------------------------------------------------- #
# EDT: the 19:30/19:45 America/New_York ingest crons run at 23:30/23:45 UTC,
# so UTC day D's bar is first fetched ~23.5h after it completes.
# --------------------------------------------------------------------------- #
def test_edt_fx_normal_weekday_is_not_stale(session: Session) -> None:
    # Tue 2026-10-27 23:30 UTC run fetched Monday's bar; Tuesday's bar is not
    # owed until Wed 23:30 UTC + grace.
    _feed(session, "massive_fx", _utc(2026, 10, 27, 23, 31))
    assert _stale(session, _utc(2026, 10, 28, 12, 30)) == {"massive_fx": False}
    assert _stale(session, _utc(2026, 10, 28, 23, 0)) == {"massive_fx": False}


@pytest.mark.parametrize(
    ("last", "now"),
    [
        (_utc(2026, 10, 27, 23, 46), _utc(2026, 10, 28, 12, 30)),  # Wed
        (_utc(2026, 10, 24, 23, 46), _utc(2026, 10, 25, 12, 30)),  # Sun
    ],
)
def test_edt_crypto_normal_day_is_not_stale(
    session: Session, last: datetime, now: datetime
) -> None:
    _feed(session, "massive_crypto", last)
    assert _stale(session, now) == {"massive_crypto": False}


def test_edt_fx_missed_run_is_stale(session: Session) -> None:
    # Mon 2026-10-26 23:30 UTC run succeeded (Friday's bar); Tue 23:30 UTC run
    # (Monday's bar, available Tue 00:00) is missed: overdue Wed 11:30 UTC.
    _feed(session, "massive_fx", _utc(2026, 10, 26, 23, 31))
    assert bar_due_since(FX_WEEKDAYS, _utc(2026, 10, 28, 11, 31)) == _utc(2026, 10, 27)
    assert _stale(session, _utc(2026, 10, 28, 11, 29)) == {"massive_fx": False}
    assert _stale(session, _utc(2026, 10, 28, 11, 31)) == {"massive_fx": True}


def test_edt_crypto_missed_run_is_stale(session: Session) -> None:
    # Tue 23:45 UTC run fetched Monday's bar; Wed 23:45 UTC run (Tuesday's bar)
    # is missed: overdue Thu 11:45 UTC.
    _feed(session, "massive_crypto", _utc(2026, 10, 27, 23, 46))
    assert _stale(session, _utc(2026, 10, 29, 11, 44)) == {"massive_crypto": False}
    assert _stale(session, _utc(2026, 10, 29, 11, 46)) == {"massive_crypto": True}


def test_ingest_times_match_the_scheduler() -> None:
    """The UTC-day grace is measured from these crons; a moved cron must not
    silently reintroduce false (or missed) staleness."""
    from signalforge.data.feeds import UTC_DAY_INGEST_AT, UTC_DAY_INGEST_TZ
    from signalforge.scheduler import default_job_specs

    specs = {s.name: s for s in default_job_specs()}
    for job, calendar in (("forex_ingest", FX_WEEKDAYS), ("crypto_ingest", UTC_DAILY)):
        spec = specs[job]
        assert spec.cron_tz == UTC_DAY_INGEST_TZ.key
        assert (spec.cron_hour, spec.cron_minute) == (
            UTC_DAY_INGEST_AT[calendar].hour,
            UTC_DAY_INGEST_AT[calendar].minute,
        )


# --------------------------------------------------------------------------- #
# Fail-closed edges and unknown feeds
# --------------------------------------------------------------------------- #
def test_never_succeeded_and_future_timestamp_stay_stale(session: Session) -> None:
    now = _utc(2026, 11, 8, 12, 0)  # a Sunday: no calendar excuse applies
    _feed(session, "massive_fx", None)
    _feed(session, "massive", now + timedelta(hours=1))
    assert _stale(session, now) == {"massive": True, "massive_fx": True}


def test_unknown_feed_keeps_the_age_rule(session: Session) -> None:
    now = _utc(2026, 11, 8, 12, 0)  # Sunday
    _feed(session, "fixture", now - DEFAULT_STALE_AFTER - timedelta(minutes=1))
    _feed(session, "stooq", now - DEFAULT_STALE_AFTER + timedelta(minutes=1))
    feeds = feed_status_report(session, now=now)["feeds"]
    assert {f["provider"]: f["is_stale"] for f in feeds} == {"fixture": True, "stooq": False}
    assert all(f["calendar"] is None and f["bar_due_since"] is None for f in feeds)


def test_calendar_lookup_failure_falls_back_to_age_rule_and_logs(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from structlog.testing import capture_logs

    from signalforge.data import feeds

    def boom(*_a: object, **_k: object) -> datetime:
        raise ValueError("calendar data exhausted")

    monkeypatch.setattr(feeds, "bar_due_since", boom)
    now = _utc(2026, 11, 8, 12, 0)  # Sunday: the calendar would have excused both
    _feed(session, "massive", now - DEFAULT_STALE_AFTER - timedelta(minutes=1))
    _feed(session, "massive_fx", now - DEFAULT_STALE_AFTER + timedelta(minutes=1))
    with capture_logs() as logs:
        report = feed_status_report(session, now=now)["feeds"]
    assert {f["provider"]: f["is_stale"] for f in report} == {
        "massive": True,
        "massive_fx": False,
    }
    assert all(f["calendar"] is None and f["bar_due_since"] is None for f in report)
    fallbacks = [e for e in logs if e["event"] == "feed.calendar_fallback"]
    assert {(e["provider"], e["calendar"], e["log_level"]) for e in fallbacks} == {
        ("massive", XNYS, "warning"),
        ("massive_fx", FX_WEEKDAYS, "warning"),
    }
    assert all("calendar data exhausted" in e["error"] for e in fallbacks)


def test_calendar_labels_match_the_producers() -> None:
    """The map uses literals; a renamed provider must not silently fall back."""
    from signalforge.config.research import UniversePipelineConfig
    from signalforge.data import forex
    from signalforge.data.adapters.massive import MassiveAdapter
    from signalforge.universe.bulk import DEFAULT_SOURCE

    assert FEED_CALENDARS[(MassiveAdapter.provider_name, "BAR_DAILY")] == XNYS
    assert FEED_CALENDARS[(DEFAULT_SOURCE, "BAR_DAILY")] == XNYS
    assert FEED_CALENDARS[(UniversePipelineConfig().normalized_source, "BAR_DAILY")] == XNYS
    assert FEED_CALENDARS[(forex.PROVIDER, "BAR_DAILY")] == FX_WEEKDAYS
    assert FEED_CALENDARS[(forex.CRYPTO_PROVIDER, "BAR_DAILY")] == UTC_DAILY
