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
    # When set, the job runs on this daily wall-clock time in ``cron_tz`` instead
    # of a fixed interval (used for the single post-close end-of-day update).
    cron_hour: int | None = None
    cron_minute: int = 0
    cron_tz: str = "America/New_York"


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


def job_strategy_health() -> None:
    from signalforge.db.session import session_scope
    from signalforge.research.health_monitor import run_health_monitor

    with session_scope() as session:
        run_health_monitor(session)


def job_daily_eod_update() -> None:
    """The single post-close update: fetch the day's completed bars, then rescan.

    End-of-day only. Never runs intraday. ``job_ingest`` throttles to the
    provider's rate limit; a stale/failed feed just leaves the last scan in place.
    """
    job_ingest()
    job_scan_all()


def _in_us_market_session(now: datetime | None = None) -> bool:
    """Roughly 08:00-18:00 America/New_York on a weekday (pre-market to after-hours)."""
    from zoneinfo import ZoneInfo

    n = (now or datetime.now(UTC)).astimezone(ZoneInfo("America/New_York"))
    return n.weekday() < 5 and 8 <= n.hour < 18


def job_news_poll() -> None:
    """Poll licensed news for the universe — only during U.S. market sessions and
    only when explicitly enabled in config. Never influences a recommendation."""
    from signalforge.config import get_settings
    from signalforge.data.adapters.massive_news import MassiveNewsAdapter
    from signalforge.data.news_ingest import ingest_news
    from signalforge.db.session import session_scope

    cfg = get_settings().research.news
    if not cfg.poll_enabled:
        return
    if cfg.us_session_only and not _in_us_market_session():
        return
    tickers = list(get_settings().research.universe)
    with session_scope() as session:
        ingest_news(
            session,
            MassiveNewsAdapter(),
            tickers,
            lookback_days=cfg.lookback_days,
            limit=cfg.per_ticker_limit,
        )


def job_health_check() -> None:
    """Around-the-clock: confirm the DB is reachable and log feed staleness."""
    from signalforge.db.health import check_db

    check_db()
    job_feed_probe()


def default_job_specs() -> list[JobSpec]:
    return [
        # One safe daily update, 17:30 America/New_York — ~90 min after the 16:00
        # close so the provider has published completed bars.
        JobSpec(
            "daily_eod_update",
            job_daily_eod_update,
            24 * 60,
            "Post-close: ingest completed daily bars + rescan every enabled horizon",
            cron_hour=17,
            cron_minute=30,
        ),
        JobSpec("paper_mtm", job_paper_mtm, 12 * 60, "Mark paper positions to market"),
        JobSpec("feed_probe", job_feed_probe, 60, "Warn on stale data feeds"),
        JobSpec("health_check", job_health_check, 15, "24/7 DB + feed-staleness health check"),
        JobSpec(
            "news_poll",
            job_news_poll,
            30,
            "Poll licensed news (config-gated OFF; U.S. sessions only; not on the decision path)",
        ),
        JobSpec("daily_briefing", job_daily_briefing, 24 * 60, "Build the daily research briefing"),
        JobSpec(
            "alerts", job_alerts, 60, "Evaluate and dispatch alerts (policy-gated, OFF by default)"
        ),
        JobSpec(
            "strategy_health",
            job_strategy_health,
            12 * 60,
            "Compare live-paper vs OOS expectancy; downgrade/disable on shortfall",
        ),
    ]


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
        if spec.cron_hour is not None:
            trigger_kwargs: dict[str, object] = {
                "trigger": "cron",
                "hour": spec.cron_hour,
                "minute": spec.cron_minute,
                "timezone": spec.cron_tz,
            }
        else:
            trigger_kwargs = {"trigger": "interval", "minutes": spec.interval_minutes}
        scheduler.add_job(
            guarded(spec.name, spec.fn),
            id=spec.name,
            name=spec.description,
            replace_existing=True,
            **trigger_kwargs,
        )
    return scheduler
