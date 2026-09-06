"""Background job scheduling (ARCHITECTURE.md §10.2).

Phase 1: APScheduler in-process. Every job entrypoint calls
:func:`signalforge.killswitch.ensure_not_engaged` first (invariant S6) — an
engaged kill switch turns every scheduled job into a logged no-op. Missed jobs
(laptop asleep) are coalesced and a catch-up ingest+scan runs on startup when
the last successful scan is stale.

Phase 2 swaps the executor for Arq + Redis behind the same ``Job`` protocol; the
job bodies do not change.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from signalforge.killswitch import KillSwitchEngaged, ensure_not_engaged
from signalforge.observability import get_logger

_log = get_logger("scheduler")

JobFn = Callable[[], None]


@dataclass(frozen=True, slots=True)
class JobSpec:
    name: str
    fn: JobFn
    interval_minutes: int
    description: str


def guarded(name: str, fn: JobFn) -> JobFn:
    """Wrap a job so an engaged kill switch makes it a logged no-op."""

    def _run() -> None:
        try:
            ensure_not_engaged()
        except KillSwitchEngaged as exc:
            _log.warning("job.skipped_kill_switch", job=name, reason=exc.state.reason)
            return
        _log.info("job.start", job=name)
        try:
            fn()
            _log.info("job.done", job=name)
        except Exception:
            _log.exception("job.failed", job=name)
            raise

    return _run


# --------------------------------------------------------------------------- #
# Job bodies
# --------------------------------------------------------------------------- #
def job_ingest() -> None:
    from datetime import date

    from signalforge.config import get_settings
    from signalforge.data.adapters.registry import get_primary_adapter
    from signalforge.data.ingest import ingest_universe
    from signalforge.db.session import session_scope

    settings = get_settings()
    symbols = list(settings.research.universe)
    end = date.today()
    start = end - timedelta(days=400)
    with session_scope() as session:
        ingest_universe(session, get_primary_adapter(settings), symbols, start, end)


def job_scan_all() -> None:
    from signalforge.config import get_settings
    from signalforge.db.session import session_scope
    from signalforge.research.candidates import persist_scan
    from signalforge.research.scan import run_scan

    for horizon in get_settings().research.enabled_horizons:
        with session_scope() as session:
            result = run_scan(session, horizon)
            persist_scan(session, result)


def job_paper_mtm() -> None:
    from signalforge.db.session import session_scope
    from signalforge.paper.ledger import mark_to_market

    with session_scope() as session:
        mark_to_market(session)


def job_feed_probe() -> None:
    from signalforge.data.feeds import feed_status_report

    report = feed_status_report()
    stale = [f["provider"] for f in report["feeds"] if f["is_stale"]]
    if stale:
        _log.warning("feed.stale", providers=stale)


def job_daily_briefing() -> None:
    from signalforge.briefing import build_and_store_briefing
    from signalforge.db.session import session_scope

    with session_scope() as session:
        build_and_store_briefing(session)


def default_job_specs() -> list[JobSpec]:
    specs = [
        JobSpec("ingest", job_ingest, 24 * 60, "Fetch daily bars for the universe"),
        JobSpec("scan_all", job_scan_all, 6 * 60, "Scan every enabled horizon"),
        JobSpec("paper_mtm", job_paper_mtm, 12 * 60, "Mark paper positions to market"),
        JobSpec("feed_probe", job_feed_probe, 60, "Warn on stale data feeds"),
    ]
    specs.append(
        JobSpec("daily_briefing", job_daily_briefing, 24 * 60, "Build the daily research briefing")
    )
    specs.append(JobSpec("alerts", job_alerts, 60, "Evaluate and dispatch alerts (policy-gated)"))
    return specs


def job_alerts() -> None:
    from signalforge.alerts.dispatch import run_alert_cycle
    from signalforge.db.session import session_scope

    with session_scope() as session:
        run_alert_cycle(session)


# --------------------------------------------------------------------------- #
# APScheduler wiring
# --------------------------------------------------------------------------- #
def _last_scan_age() -> timedelta | None:
    from sqlalchemy import select

    from signalforge.db.models import ScanRun
    from signalforge.db.session import session_scope

    with session_scope() as session:
        last = session.scalar(
            select(ScanRun.started_at).order_by(ScanRun.started_at.desc()).limit(1)
        )
    return (datetime.now(UTC) - last) if last else None


def run_catch_up(stale_after_hours: int = 18) -> None:
    """On startup, run ingest+scan once if the last scan is missing or stale."""
    age = _last_scan_age()
    if age is None or age > timedelta(hours=stale_after_hours):
        _log.info(
            "scheduler.catch_up",
            last_scan_age_hours=round(age.total_seconds() / 3600, 1) if age else None,
        )
        try:
            guarded("catchup_ingest", job_ingest)()
            guarded("catchup_scan", job_scan_all)()
        except KillSwitchEngaged:
            _log.warning("scheduler.catch_up_skipped_kill_switch")


def build_scheduler(specs: list[JobSpec] | None = None) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(
        timezone="UTC",
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600},
    )
    for spec in specs or default_job_specs():
        scheduler.add_job(
            guarded(spec.name, spec.fn),
            trigger="interval",
            minutes=spec.interval_minutes,
            id=spec.name,
            name=spec.description,
            replace_existing=True,
        )
    return scheduler
