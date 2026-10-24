"""Intraday operating mode: one flag, four surfaces, OFF by default.

The first section is the contract that matters most — with the flag OFF, every
surface behaves exactly as it did before the flag existed. The second section
shows the flag actually reverses each of them.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from signalforge.config.research import ResearchConfig
from signalforge.domain import Horizon, StrategyStatus
from signalforge.research.approved_scope_scan import approved_horizons
from signalforge.research.intraday_policy import (
    LATENCY_DISCLOSURE,
    in_session_window,
    operating_enabled,
    operating_horizons,
    policy_surfaces,
    scan_interval_minutes,
)

OFF = ResearchConfig()
ON = ResearchConfig().model_copy(
    update={"intraday": ResearchConfig().intraday.model_copy(update={"operating_enabled": True})}
)


def _approve(session: Session, name: str, horizon: Horizon) -> None:
    from signalforge.db.models import Strategy

    session.add(Strategy(name=name, horizon=horizon, status=StrategyStatus.PAPER_APPROVED))
    session.flush()


# --------------------------------------------------------------------------- #
# OFF (the default) is byte-identical to the pre-flag behaviour
# --------------------------------------------------------------------------- #
def test_the_flag_is_off_by_default() -> None:
    assert ResearchConfig().intraday.operating_enabled is False
    assert operating_enabled(OFF) is False


def test_off_excludes_intraday_from_the_approved_scope_scan(session: Session) -> None:
    _approve(session, "intraday_orb", Horizon.INTRADAY)
    _approve(session, "trend_continuation", Horizon.SHORT_SWING)
    assert approved_horizons(session, OFF) == [Horizon.SHORT_SWING]


def test_off_skips_intraday_in_the_alert_dispatcher() -> None:
    assert Horizon.INTRADAY in OFF.enabled_horizons  # the research surface is unchanged
    assert Horizon.INTRADAY not in operating_horizons(OFF, OFF.enabled_horizons)
    # ...and every other horizon keeps its order and membership exactly
    assert operating_horizons(OFF, OFF.enabled_horizons) == [
        h for h in OFF.enabled_horizons if h is not Horizon.INTRADAY
    ]


def test_off_schedules_no_intraday_job(db_url: str) -> None:
    from signalforge.scheduler import default_job_specs

    names = [s.name for s in default_job_specs()]
    assert "intraday_scan" not in names
    # Daily context is read-only; it does not enable intraday trading.
    assert names == [
        "daily_eod_update",
        "universe_update",
        "grid_daily",
        "catch_up",
        "agents_daily",
        "paper_mtm",
        "feed_probe",
        "health_check",
        "news_poll",
        "market_context",
        "daily_briefing",
        "alerts",
        "strategy_health",
    ]
    # W3c's options EOD chain is NOT here and must not be: signalforge.app
    # imports the scheduler, and S16 reports indirect chains, so this module may
    # not reach the options paper layer at all. The spec is injected from
    # signalforge.cli (the execution cycle's rule, D6 §2), and
    # tests/paper/test_options_eod_chain.py pins the injected order.
    assert "options_paper_eod" not in names


def test_off_makes_the_job_a_logged_no_op_that_writes_nothing(db_url: str) -> None:
    from sqlalchemy import select

    from signalforge.db.models import ScanRun
    from signalforge.db.session import get_sessionmaker
    from signalforge.scheduler import job_intraday_scan

    job_intraday_scan()
    with get_sessionmaker()() as session:
        assert list(session.scalars(select(ScanRun))) == []


def test_the_flag_is_not_part_of_the_approval_scope_hash() -> None:
    """Hashing it would move config_hash the moment the section appeared and
    put both live PAPER_APPROVED approvals out of scope — while protecting
    nothing, because the flag changes no strategy's signals."""
    assert "intraday" not in ResearchConfig.SCOPE_HASH_FIELDS
    assert OFF.config_hash == ON.config_hash
    # the signal-shaping intraday setting IS hashed, and still is
    assert "intraday_bar_size" in ResearchConfig.SCOPE_HASH_FIELDS
    assert "enabled_horizons" in ResearchConfig.SCOPE_HASH_FIELDS
    resized = OFF.model_copy(update={"intraday_bar_size": "5m"})
    assert resized.config_hash != OFF.config_hash
    # but it is still recorded in the audit-only hash
    assert OFF.full_config_hash != ON.full_config_hash


# --------------------------------------------------------------------------- #
# ON reverses each surface — and only these
# --------------------------------------------------------------------------- #
def test_on_includes_intraday_in_the_approved_scope_scan(session: Session) -> None:
    _approve(session, "intraday_orb", Horizon.INTRADAY)
    _approve(session, "trend_continuation", Horizon.SHORT_SWING)
    assert approved_horizons(session, ON) == [Horizon.INTRADAY, Horizon.SHORT_SWING]


def test_on_lets_the_alert_dispatcher_see_intraday() -> None:
    assert Horizon.INTRADAY in operating_horizons(ON, ON.enabled_horizons)


def test_on_schedules_the_scan_at_the_bar_cadence(db_url: str, monkeypatch) -> None:
    import signalforge.scheduler as sched

    monkeypatch.setattr(sched, "effective_research_config", lambda s: ON, raising=False)
    monkeypatch.setattr("signalforge.settings_store.effective_research_config", lambda s: ON)
    specs = {s.name: s for s in sched.default_job_specs()}
    assert "intraday_scan" in specs
    assert specs["intraday_scan"].interval_minutes == 15  # the configured bar size
    assert specs["intraday_scan"].cron_hour is None  # interval, not a daily cron

    faster = ON.model_copy(
        update={"intraday": ON.intraday.model_copy(update={"scan_interval_minutes": 5})}
    )
    monkeypatch.setattr("signalforge.settings_store.effective_research_config", lambda s: faster)
    assert {s.name: s for s in sched.default_job_specs()}["intraday_scan"].interval_minutes == 5


def test_scan_interval_defaults_to_the_bar_size() -> None:
    assert scan_interval_minutes(ON) == 15
    assert scan_interval_minutes(ON.model_copy(update={"intraday_bar_size": "5m"})) == 5


# --------------------------------------------------------------------------- #
# the session window, and never overlapping the EOD job
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "stamp,expected",
    [
        (datetime(2024, 6, 25, 14, 0, tzinfo=UTC), True),  # 10:00 ET, a Tuesday
        (datetime(2024, 6, 25, 13, 0, tzinfo=UTC), False),  # 09:00 ET, pre-market
        (datetime(2024, 6, 25, 20, 30, tzinfo=UTC), False),  # 16:30 ET, after the close
        (datetime(2024, 6, 22, 15, 0, tzinfo=UTC), False),  # Saturday
        (datetime(2024, 7, 4, 15, 0, tzinfo=UTC), False),  # Independence Day
        (datetime(2024, 11, 29, 18, 30, tzinfo=UTC), False),  # 13:30 ET, after an early close
        (datetime(2024, 11, 29, 15, 0, tzinfo=UTC), True),  # 10:00 ET on that same half-day
    ],
)
def test_in_session_window_follows_the_exchange_calendar(stamp: datetime, expected: bool) -> None:
    assert in_session_window(ON, stamp) is expected


def test_the_intraday_scan_never_runs_while_the_eod_update_holds_the_lock(
    db_url: str, monkeypatch
) -> None:
    import signalforge.scheduler as sched

    monkeypatch.setattr("signalforge.settings_store.effective_research_config", lambda s: ON)
    monkeypatch.setattr(sched, "_EOD_UPDATE_LOCK", __import__("threading").Lock())
    ran: list[str] = []
    monkeypatch.setattr("signalforge.research.scan.run_scan", lambda *a, **k: ran.append("scan"))

    assert sched._EOD_UPDATE_LOCK.acquire(blocking=False)
    try:
        sched.job_intraday_scan()  # the EOD update is "in flight"
    finally:
        sched._EOD_UPDATE_LOCK.release()
    assert ran == []


def test_the_job_is_runnable_by_hand_in_both_states() -> None:
    from signalforge.scheduler import MANUAL_JOBS

    assert "intraday_scan" in MANUAL_JOBS


# --------------------------------------------------------------------------- #
# the four surfaces agree, and say so in one place
# --------------------------------------------------------------------------- #
def test_policy_surfaces_report_one_consistent_answer() -> None:
    off = policy_surfaces(OFF)
    assert off["operating_enabled"] is False
    assert off["approved_scope_scan_includes_intraday"] is False
    assert off["alerts_dispatch_includes_intraday"] is False
    assert off["scheduled_intraday_scan_job"] is False
    # the fourth surface: the research scan has always covered the horizon, and
    # still does — that is research, not operation, and it is stated rather
    # than quietly disagreeing with the other three
    assert off["research_scan_horizons_include_intraday"] is True

    on = policy_surfaces(ON)
    assert [
        on["approved_scope_scan_includes_intraday"],
        on["alerts_dispatch_includes_intraday"],
        on["scheduled_intraday_scan_job"],
    ] == [True, True, True]
    assert LATENCY_DISCLOSURE in on["latency_disclosure"]
    assert "DELAYED" in on["latency_disclosure"]


def test_the_latency_limit_travels_with_the_policy() -> None:
    """Operating intraday must never be able to imply the modelled fill is
    attainable. The disclosure is part of the policy object itself."""
    assert "one bar earlier" in LATENCY_DISCLOSURE
    assert "never an executable price" in LATENCY_DISCLOSURE


def test_dispatch_uses_the_policy_rather_than_a_hard_coded_skip() -> None:
    """A regression guard on the shape, not just the behaviour: if someone
    re-introduces a hard-coded INTRADAY skip, the flag stops working and this
    test says so."""
    from pathlib import Path

    src = Path("src/signalforge/alerts/dispatch.py").read_text()
    assert "operating_horizons" in src
    assert "if h is Horizon.INTRADAY:" not in src


def test_an_intraday_candidate_needs_a_completed_prior_session_regime(
    session: Session,
) -> None:
    """Operating mode does not loosen the v0.2.0 lag: the live scan path reads
    the same lagged label the ladder does."""
    from signalforge.data.series import PriceSeries
    from signalforge.research.scan import _regime_at_lag

    d0 = date(2024, 6, 20)
    rows = [
        (d0 + timedelta(days=i), 100.0, 101.0, 99.0, 100.0 + i * 0.01, 1_000.0) for i in range(300)
    ]
    proxy = PriceSeries.from_bars("SPY", rows)
    as_of = proxy.dates[-1]
    assert _regime_at_lag(proxy, as_of, 1) is not None
    assert _regime_at_lag(proxy, as_of, 1).as_of < as_of
