"""The liquid-universe pipeline's research scans (source == normalized_source)
must never become "the latest scan" for the alert planner, dashboards, or the
catch-up staleness check — only research-source scans count."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from signalforge.app.views import _latest_scan
from signalforge.db.models import ScanRun
from signalforge.domain import Horizon
from signalforge.research.candidates import not_universe_scan
from signalforge.settings_store import effective_research_config


def _run(session: Session, *, source: str, minutes_ago: int) -> ScanRun:
    now = datetime.now(UTC)
    run = ScanRun(
        horizon=Horizon.SHORT_SWING,
        started_at=now - timedelta(minutes=minutes_ago),
        finished_at=now - timedelta(minutes=minutes_ago),
        source=source,
        config_hash="test",
    )
    session.add(run)
    session.flush()
    return run


def test_latest_scan_ignores_universe_pipeline_scans(session: Session) -> None:
    uni_src = effective_research_config(session).universe_pipeline.normalized_source
    research = _run(session, source="massive", minutes_ago=60)
    _run(session, source=uni_src, minutes_ago=1)  # newer, but a universe scan
    latest = _latest_scan(session, Horizon.SHORT_SWING)
    assert latest is not None and latest.id == research.id


def test_not_universe_scan_filter_keeps_legacy_blank_source(session: Session) -> None:
    uni_src = effective_research_config(session).universe_pipeline.normalized_source
    legacy = _run(session, source="", minutes_ago=30)
    _run(session, source=uni_src, minutes_ago=1)
    from sqlalchemy import select

    kept = list(session.scalars(select(ScanRun).where(not_universe_scan(session))))
    assert [r.id for r in kept] == [legacy.id]


def test_catch_up_staleness_ignores_universe_scans(session: Session, monkeypatch) -> None:
    import signalforge.scheduler as sched
    from signalforge.db.session import session_scope

    uni_src = effective_research_config(session).universe_pipeline.normalized_source
    with session_scope() as s:
        _run(s, source=uni_src, minutes_ago=1)  # only a universe scan exists
    age = sched._last_scan_age()
    assert age is None  # no research scan -> catch-up must run
