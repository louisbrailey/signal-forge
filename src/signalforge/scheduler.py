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

import threading
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

from apscheduler.schedulers.background import BackgroundScheduler

from signalforge.db.retry import LockRetryExhausted, is_lock_error, retry_on_lock
from signalforge.domain import Horizon
from signalforge.jobspec import JobFn, JobSpec
from signalforge.killswitch import KillSwitchEngaged, ensure_not_engaged
from signalforge.observability import get_logger

if TYPE_CHECKING:  # typing only — the runtime import stays inside the job bodies
    from signalforge.db.models import IngestionRun

_log = get_logger("scheduler")

JOB_LOCK_ATTEMPTS = 3
JOB_LOCK_BACKOFF_S = (0.5, 2.0, 5.0)
# Jobs that persist per-unit results (a ScanRun per horizon, a bulk file per
# session...) retry lock contention INSIDE, per unit; re-running the whole body
# would duplicate already-persisted units, so the job-level retry is off.
NO_JOB_LEVEL_LOCK_RETRY: frozenset[str] = frozenset(
    {
        "daily_eod_update",
        "catch_up",
        "universe_update",
        "approved_scope_scan",
        "catchup_scan",
        "catchup_approved_scope_scan",
        # persists a ScanRun of its own; a job-level retry would re-run the
        # whole body and persist a second scan for the same bar
        "intraday_scan",
        # the options EOD chain persists per-unit records (marks per structure,
        # a dated reconciliation report, collateral entries, one commit per
        # auto-simulated candidate) and retries INSIDE, per unit
        "options_paper_eod",
    }
)


def _record_job_failure(name: str, error: str) -> None:
    """Persist a job failure so the alert policy (DATA_ISSUE/SYSTEM_HEALTH) can
    see it. Best-effort: a DB problem here must never mask the original error."""
    try:
        from signalforge.db.models import AuditLog
        from signalforge.db.session import session_scope

        def _write() -> None:
            with session_scope(write=True) as session:
                session.add(
                    AuditLog(
                        ts=datetime.now(UTC),
                        actor="scheduler",
                        action="job.failed",
                        entity=name,
                        before_json={},
                        after_json={"error": error[:300]},
                    )
                )

        retry_on_lock(_write, attempts=4, backoff_s=(0.2, 0.5, 1.0), label="job.failed")
    except Exception as exc:
        _log.warning("job.failure_record_failed", job=name, error=repr(exc)[:160])


def _scrub_detail(text: str) -> str:
    """``JobRun.detail`` is rendered on the /ops page, so redact every
    configured secret value and any bearer/apikey-shaped fragment first.
    Best-effort: a settings problem must never block recording."""
    import re

    out = text
    try:
        from signalforge.config import get_settings

        s = get_settings()
        for attr in (
            "market_data_api_key",
            "market_data_api_key_secondary",
            "options_api_key",
            "news_api_key",
            "llm_api_key",
            "notification_api_key",
            "discord_webhook_url",
            "app_encryption_key",
        ):
            val = getattr(s, attr, None)
            getter = getattr(val, "get_secret_value", None)
            secret = getter() if callable(getter) else ""
            if secret:
                out = out.replace(secret, "[REDACTED]")
    except Exception:  # pragma: no cover - settings unavailable in some test contexts
        _log.debug("job.detail_scrub_settings_unavailable")
    out = re.sub(r"(api[_-]?key|token|apikey)=[^&\s\"']+", r"\1=[REDACTED]", out, flags=re.I)
    out = re.sub(r"Bearer\s+[A-Za-z0-9._\-]+", "Bearer [REDACTED]", out)
    return out


def _record_job_run(name: str, started: datetime, status: str, detail: str = "") -> None:
    """Persist one ``JobRun`` row (ok / failed / skipped) for the Operational
    Status page. Best-effort: never masks the job's own outcome."""
    try:
        from signalforge.db.models import JobRun
        from signalforge.db.session import session_scope

        def _write() -> None:
            with session_scope(write=True) as session:
                session.add(
                    JobRun(
                        name=name,
                        started_at=started,
                        finished_at=datetime.now(UTC),
                        status=status,
                        detail=_scrub_detail(detail)[:300],
                    )
                )

        retry_on_lock(_write, attempts=4, backoff_s=(0.2, 0.5, 1.0), label="job_run")
    except Exception as exc:
        _log.warning("job.run_record_failed", job=name, status=status, error=repr(exc)[:160])


def guarded(name: str, fn: JobFn) -> JobFn:
    """Wrap a job so an engaged kill switch makes it a logged no-op."""

    def _run() -> None:
        started = datetime.now(UTC)
        try:
            ensure_not_engaged()
        except KillSwitchEngaged as exc:
            _log.warning("job.skipped_kill_switch", job=name, reason=exc.state.reason)
            _record_job_run(name, started, "skipped", f"kill switch engaged: {exc.state.reason}")
            return
        _log.info("job.start", job=name)
        try:
            # Only TRANSIENT SQLite lock contention is retried (bounded); any
            # other error, and the lock error once attempts are exhausted,
            # surfaces as a real failure with the reason recorded.
            if name in NO_JOB_LEVEL_LOCK_RETRY:
                fn()
            else:
                retry_on_lock(
                    fn, attempts=JOB_LOCK_ATTEMPTS, backoff_s=JOB_LOCK_BACKOFF_S, label=name
                )
            _log.info("job.done", job=name)
            _record_job_run(name, started, "ok")
        except Exception as exc:
            reason = repr(exc)
            if isinstance(exc, LockRetryExhausted) or is_lock_error(exc):
                reason = f"database lock contention: {exc}"
            _log.exception("job.failed", job=name)
            _record_job_run(name, started, "failed", reason)
            _record_job_failure(name, reason)
            raise

    return _run


# --------------------------------------------------------------------------- #
# Job bodies
# --------------------------------------------------------------------------- #
def job_ingest() -> None:
    """The routine daily incremental top-up, over the UNION of the configured
    universe and every PAPER_APPROVED strategy version's approved-scope
    universe on this adapter's source (``research.approved_scope_scan.
    ingest_scope``).

    Why the union (W6a, 2026-09-14): the approved-scope scan refuses to run on
    a universe that has no completed bar for the latest session, but this job
    used to fetch only ``settings.research.universe`` — so the version approved
    on the 150-symbol snapshot 11 was blocked *every* session
    (``only 24/150 approved symbols have a bar for …``). Its data was simply
    never fetched. Friday 2026-09-11 only worked because a 10-year full-history
    backfill happened to include that session.

    Also records a lightweight ``IngestionRun`` summary (status
    ok/partial/failed) so the alert policy's ``DATA_ISSUE`` check can see a real
    failure on the *scheduled* path — before this, only the CLI's separate
    deep-history command wrote that row, so a scheduled ingest with per-symbol
    errors was invisible to plan_alerts. ``status`` keeps its meaning exactly:
    ``ok`` only when every requested symbol succeeded. Which universes a
    ``partial`` actually blocks is decided per universe from
    ``symbols_failed``, by ``approved_scope_scan.data_readiness`` — not here.
    """
    from datetime import date

    from signalforge.config import get_settings
    from signalforge.data.adapters.registry import get_primary_adapter
    from signalforge.data.ingest import ingest_universe
    from signalforge.db.models import IngestionRun
    from signalforge.db.session import session_scope
    from signalforge.db.types import utcnow
    from signalforge.domain import FeedType
    from signalforge.research.approved_scope_scan import ingest_scope

    settings = get_settings()
    end = date.today()
    start = end - timedelta(days=400)
    adapter = get_primary_adapter(settings)

    # Resolve the symbol set as a PLAIN READER. Doing it inside the write scope
    # would open BEGIN IMMEDIATE before the first symbol's paced network fetch
    # and hold the SQLite write lock across it — the exact shape of the
    # 2026-09-09 lock-starvation bug (docs/SQLITE_CONCURRENCY.md).
    with session_scope() as session:
        scope = ingest_scope(
            session, list(settings.research.universe), source=adapter.provider_name
        )
    symbols = list(scope.symbols)
    _log.info(
        "ingest.scope",
        provider=adapter.provider_name,
        symbols=len(symbols),
        configured=len(scope.configured),
        added=len(scope.added),
        snapshots=[c.dataset_snapshot_id for c in scope.contributions],
        excluded_other_source=[u["dataset_snapshot_id"] for u in scope.other_source],
    )

    with session_scope(write=True) as session:
        started = utcnow()
        # ingest_universe fetches each symbol BEFORE it writes and commits per
        # symbol, so no write transaction ever spans a paced provider call and a
        # run cut short is durable up to its last committed symbol.
        report = ingest_universe(session, adapter, symbols, start, end)
        ok_symbols = [r.symbol for r in report.results if not r.error]
        failed = {r.symbol: r.error for r in report.results if r.error}
        status = "ok" if not failed else ("partial" if ok_symbols else "failed")
        session.add(
            IngestionRun(
                provider=adapter.provider_name,
                feed_type=FeedType.BAR_DAILY,
                kind="incremental",
                requested_start=start,
                requested_end=end,
                symbols_requested=list(symbols),
                symbols_ok=ok_symbols,
                symbols_failed=failed,
                bars_written=report.bars_written,
                status=status,
                started_at=started,
                finished_at=utcnow(),
                gaps_json=scope.provenance(),
                notes=scope.note(),
            )
        )


def job_scan_all() -> None:
    from signalforge.config import get_settings
    from signalforge.db.session import session_scope
    from signalforge.research.candidates import persist_scan
    from signalforge.research.scan import run_scan

    for horizon in get_settings().research.enabled_horizons:

        def _one(h: Horizon = horizon) -> None:
            with session_scope(write=True) as session:
                result = run_scan(session, h)
                persist_scan(session, result)

        # retry per horizon: a lock hit on horizon N never re-runs horizon 1..N-1
        retry_on_lock(
            _one, attempts=JOB_LOCK_ATTEMPTS, backoff_s=JOB_LOCK_BACKOFF_S, label=f"scan:{horizon}"
        )


def job_paper_mtm() -> None:
    from signalforge.db.session import session_scope
    from signalforge.paper.ledger import mark_to_market

    with session_scope(write=True) as session:
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

    with session_scope(write=True) as session:
        build_and_store_briefing(session)


def job_strategy_health() -> None:
    from signalforge.db.session import session_scope
    from signalforge.research.health_monitor import run_health_monitor

    with session_scope(write=True) as session:
        run_health_monitor(session)


def job_approved_scope_scan() -> None:
    """Scan, per PAPER_APPROVED strategy version, EXACTLY the dataset that
    version's own approval was granted on (its newest passing evaluation's
    dataset snapshot and source), so the candidates can pass the five-part
    approval-scope match at alert time. Versions sharing a (snapshot,
    horizon, source) are scanned together, once; two versions approved on
    two different snapshots produce two scans. Hard-gated, PER APPROVED
    UNIVERSE, on fresh, complete data
    (``research.approved_scope_scan.data_readiness``) — a stale feed, a
    non-ok ingestion, or missing bars for the latest session blocks that
    universe (and only that universe) and records why. Never options, never
    an alert; INTRADAY only if ``research.intraday.operating_enabled`` is on
    (default off), the single flag ``research.intraday_policy`` owns.

    When the operator setting ``auto_simulate_qualified_signals`` is ON, the
    scan's own gate-PASSED candidates are then offered to
    ``paper.auto_simulate`` — SIMULATED paper acceptance only, through the same
    deterministic guard and ledger as a manual acceptance."""
    from signalforge.db.session import session_scope
    from signalforge.paper.auto_simulate import auto_simulate_scan_runs
    from signalforge.research.approved_scope_scan import run_approved_scope_scan

    with session_scope(write=True) as session:
        report = run_approved_scope_scan(session)
        if report.ran and report.runs:
            # every group's scan run, so a version approved on a second
            # snapshot is auto-simulated from its OWN scan, not skipped
            sim = auto_simulate_scan_runs(session, [int(r["scan_run_id"]) for r in report.runs])
            _log.info(
                "auto_simulate.done",
                enabled=sim.enabled,
                considered=sim.considered,
                accepted=len(sim.accepted),
                rejected=len(sim.rejected),
                watched=len(sim.watched),
                skipped=len(sim.skipped),
            )
    if not report.ran:
        _log.warning("approved_scope_scan.not_run", reason=report.blocked_reason)
    for blocked in report.blocked_universes:
        _log.warning(
            "approved_scope_scan.universe_blocked",
            dataset_snapshot_id=blocked["dataset_snapshot_id"],
            dataset_key=blocked["dataset_key"],
            reason=blocked["reason"],
        )
    for skipped in report.skipped_versions:
        _log.warning(
            "approved_scope_scan.version_skipped",
            strategy_version_id=skipped["strategy_version_id"],
            reason=skipped["reason"],
        )


# The SIMULATED options paper EOD chain deliberately does NOT live here.
#
# It is ``signalforge.paper.options_eod``, and its ``JobSpec`` is injected from
# ``signalforge.cli`` — the same registration rule D6 §2 established for the
# execution cycle, and for the same structural reason. ``signalforge.app``
# imports this module (``app.main`` at import time, ``app.views`` inside
# ``ops_status_context``), and contract S16 reports INDIRECT chains, so a single
# ``from signalforge.paper.options_marks import ...`` here — even inside a
# function body, which import-linter also sees — puts the whole app layer on the
# options paper decision path.
#
# The operator-visible consequence, stated rather than discovered later: the
# options EOD chain exists **only in the CLI-launched worker**. Started from the
# app process (``APP_RUN_SCHEDULER=true``) there is no options job at all — no
# marks, no reconciliation, no expiry processing and no options auto-simulation.
# ``default_job_specs()`` below is therefore byte-identical to what it was before
# the chain existed. Only ``NO_JOB_LEVEL_LOCK_RETRY`` names it, as a plain string
# with no import, because ``guarded()`` looks the job's retry policy up by name.


# daily_eod_update (cron) and catch_up (interval) are different APScheduler
# jobs, so max_instances=1 does not stop them overlapping — this lock does.
# job_intraday_scan takes the SAME lock: an in-session scan must never run
# while the post-close ingest+rescan is in flight (they write the same tables,
# and an intraday scan straddling the EOD rescan would read half-updated data).
_EOD_UPDATE_LOCK = threading.Lock()


def job_intraday_scan() -> None:
    """In-session INTRADAY scan on the approved dataset, at the bar cadence.

    Config-gated OFF (``research.intraday.operating_enabled``). Every guard the
    EOD path has applies here too, and two more:

    * the kill switch — ``guarded`` wraps every scheduled job, and the adapters
      re-check it inside their own waits;
    * the worker lock — only the single lock-holding worker process runs jobs
      at all (``worker_lock``), so two workers cannot scan the same bar;
    * ``_EOD_UPDATE_LOCK`` — never overlaps the post-close ingest + rescan;
    * the exchange calendar — a no-op outside the configured RTH window, on
      holidays and on early-close afternoons.

    It scans; it does not ingest. Intraday bars come from the operator's
    backfill (``signalforge ingest-intraday``), so a scan can only ever read
    what is already stored — and on a DELAYED feed the newest stored bar is at
    least one bar behind. That is disclosed on every run rather than implied.
    """
    from signalforge.db.session import session_scope
    from signalforge.research.candidates import persist_scan
    from signalforge.research.intraday_policy import (
        LATENCY_DISCLOSURE,
        in_session_window,
        operating_enabled,
    )
    from signalforge.research.scan import run_scan
    from signalforge.settings_store import effective_research_config

    # Read the flag under a plain READ session: a disabled run must not take
    # the SQLite write lock (BEGIN IMMEDIATE) for nothing.
    with session_scope() as session:
        cfg = effective_research_config(session)
    if not operating_enabled(cfg):
        _log.info("intraday_scan.skipped_disabled")
        return
    if not in_session_window(cfg):
        _log.info("intraday_scan.skipped_outside_session")
        return
    if not _EOD_UPDATE_LOCK.acquire(blocking=False):
        _log.warning("intraday_scan.skipped_eod_update_running")
        return
    try:
        with session_scope(write=True) as session:
            result = run_scan(session, Horizon.INTRADAY)
            run = persist_scan(session, result)
        _log.info(
            "intraday_scan.done",
            scan_run_id=run.id,
            candidates=run.candidate_count,
            no_trade=run.no_trade_count,
            bar_size=cfg.intraday_bar_size,
            disclosure=LATENCY_DISCLOSURE,
        )
    finally:
        _EOD_UPDATE_LOCK.release()


def job_daily_eod_update() -> None:
    """The single post-close update: fetch the day's completed bars, rescan,
    run the approved-scope scan on the freshly completed data, then the
    mechanical grid job (config-gated OFF).

    End-of-day only. Never runs intraday. ``job_ingest`` throttles to the
    provider's rate limit; a stale/failed feed just leaves the last scan in
    place — and the approved-scope scan additionally refuses to run on it.
    Ordering is guaranteed by running the three steps sequentially in one job:
    an ingest failure raises before either scan starts.
    """
    if not _EOD_UPDATE_LOCK.acquire(blocking=False):
        _log.warning("daily_eod_update.already_running", detail="skipping overlapping run")
        return
    try:
        job_ingest()
        job_scan_all()
        # Nested guard so the approved-scope step leaves its OWN JobRun row (the
        # Operational Status page shows it by name) — a failure still propagates
        # and also marks daily_eod_update failed.
        guarded("approved_scope_scan", job_approved_scope_scan)()
        # The mechanical grid is NOT chained here: it reads the bulk universe
        # source that ``universe_update`` (18:15 ET) refreshes, so it has its own
        # cron slot after that job (see default_job_specs).
    finally:
        _EOD_UPDATE_LOCK.release()


def job_grid_daily() -> None:
    """Mechanical grid strategy, one evaluation per symbol per session.

    Runs AFTER ``daily_eod_update`` has ingested the day's completed bars (it is
    chained at the end of that job). Evaluates the previous session's close and
    fills at today's open on a dedicated ``grid`` paper account.

    Config-gated OFF (``research.grid.enabled``). The grid is NOT a registered,
    promotion-gated strategy: it never produces a candidate, never alerts, and
    never touches the research paper account.
    """
    from signalforge.db.session import session_scope
    from signalforge.grid.live import run_grid_daily
    from signalforge.settings_store import effective_research_config

    # Read the flag as a plain reader first: a disabled run must not take the
    # SQLite write lock (BEGIN IMMEDIATE) for nothing.
    with session_scope() as session:
        cfg = effective_research_config(session).grid
    if not cfg.enabled:
        _log.info("grid.skipped_disabled")
        return
    with session_scope(write=True) as session:
        res = run_grid_daily(session, cfg=cfg)
    _log.info("grid.daily", **res.to_dict())


def job_universe_update() -> None:
    """Post-close liquid-universe update (discovery -> bulk archive -> screen
    -> normalize eligible -> research scan). Config-gated OFF
    (``research.universe_pipeline.enabled``); strict runtime/storage budgets;
    never an alert, paper trade, option, or intraday bar."""
    from signalforge.db.session import session_scope
    from signalforge.settings_store import effective_research_config
    from signalforge.universe.pipeline import run_universe_update

    with session_scope(write=True) as session:
        cfg = effective_research_config(session).universe_pipeline
        if not cfg.enabled:
            _log.info("universe.update.skipped_disabled")
            return
        run_universe_update(session, cfg=cfg)


def job_agents_daily() -> None:
    """Run every bounded research agent once (read-only reports). Config-gated
    OFF (``research.agents.enabled``); never touches candidates, trades,
    alerts, or settings — contract S14."""
    from signalforge.agents import run_all_agents
    from signalforge.db.session import session_scope
    from signalforge.settings_store import effective_research_config

    # Read the flag under a plain read session first: a disabled run must not
    # take the SQLite write lock (BEGIN IMMEDIATE) for nothing.
    with session_scope() as session:
        enabled = effective_research_config(session).agents.enabled
    if not enabled:
        _log.info("agents.skipped_disabled")
        return
    with session_scope(write=True) as session:
        results = run_all_agents(session)
    _log.info("agents.daily_done", failed=[r.agent for r in results if r.status != "ok"])


# Jobs runnable on demand via `signalforge run-job <name>` that are NOT
# separately scheduled (they run inside daily_eod_update / catch-up).
MANUAL_JOBS: dict[str, JobFn] = {
    "approved_scope_scan": job_approved_scope_scan,
    "universe_update": job_universe_update,
    "agents_daily": job_agents_daily,
    # Runnable by hand even while intraday operation is off — it is then a
    # logged no-op, which is the point: the operator can prove what it would do.
    "intraday_scan": job_intraday_scan,
    "grid_daily": job_grid_daily,
}


def _in_us_market_session(now: datetime | None = None) -> bool:
    """Roughly 08:00-18:00 America/New_York on a weekday (pre-market to after-hours)."""
    from zoneinfo import ZoneInfo

    n = (now or datetime.now(UTC)).astimezone(ZoneInfo("America/New_York"))
    return n.weekday() < 5 and 8 <= n.hour < 18


def job_news_poll() -> None:
    """Poll licensed news for the universe — only during U.S. market sessions and
    only when explicitly enabled in config. Never influences a recommendation.

    Ingests the generic multi-publisher feed and the dedicated Benzinga News
    add-on feed as two separate calls, through two separate adapters — they
    stay distinct in the database (``NewsItem.provider``) and never merge."""
    from signalforge.config import get_settings
    from signalforge.data.adapters.massive_news import BenzingaNewsAdapter, MassiveNewsAdapter
    from signalforge.data.news_ingest import ingest_news
    from signalforge.db.session import session_scope

    cfg = get_settings().research.news
    if not cfg.poll_enabled:
        return
    if cfg.us_session_only and not _in_us_market_session():
        return
    tickers = list(get_settings().research.universe)
    with session_scope(write=True) as session:
        ingest_news(
            session,
            MassiveNewsAdapter(),
            tickers,
            lookback_days=cfg.lookback_days,
            limit=cfg.per_ticker_limit,
        )
        session.commit()  # release the write lock before the second feed's network fetch
        ingest_news(
            session,
            BenzingaNewsAdapter(),
            tickers,
            lookback_days=cfg.lookback_days,
            limit=cfg.per_ticker_limit,
        )


def job_health_check() -> None:
    """Around-the-clock: confirm the DB is reachable and log feed staleness."""
    from signalforge.db.health import check_db

    check_db()
    job_feed_probe()


def _intraday_scan_spec() -> list[JobSpec]:
    """The in-session scan job — registered ONLY while intraday operation is on.

    Deliberately not the "always scheduled, returns early when disabled" shape
    the other config-gated jobs use: at a 15m cadence that would write ~26
    JobRun rows per session for a deployment that has not opted in, changing
    what the Operational Status page shows. With the flag off the job list is
    byte-identical to what it was before this existed.

    Best-effort config read: the scheduler must still start if the database is
    momentarily unavailable, and the safe answer is "not scheduled"."""
    try:
        from signalforge.db.session import session_scope
        from signalforge.research.intraday_policy import operating_enabled, scan_interval_minutes
        from signalforge.settings_store import effective_research_config

        with session_scope() as session:
            cfg = effective_research_config(session)
        if not operating_enabled(cfg):
            return []
        every = scan_interval_minutes(cfg)
    except Exception as exc:  # pragma: no cover - DB unavailable at startup
        _log.warning("intraday_scan.spec_unavailable", error=repr(exc)[:160])
        return []
    return [
        JobSpec(
            "intraday_scan",
            job_intraday_scan,
            every,
            f"In-session INTRADAY scan every {every} min during U.S. RTH "
            f"(config-gated; never overlaps the EOD update)",
        )
    ]


def default_job_specs() -> list[JobSpec]:
    return [
        *_intraday_scan_spec(),
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
        # Post-close, after the EOD update has had time to finish; config-gated OFF.
        JobSpec(
            "universe_update",
            job_universe_update,
            24 * 60,
            "Post-close liquid-universe bulk update + screen (config-gated OFF; EOD only)",
            cron_hour=18,
            cron_minute=15,
        ),
        # After the bulk universe refresh: the mechanical grid evaluates the day's
        # closes for its 1,000-symbol universe (config-gated; SIMULATED account).
        JobSpec(
            "grid_daily",
            job_grid_daily,
            24 * 60,
            "Mechanical grid daily cycle on the refreshed bulk universe (config-gated)",
            cron_hour=18,
            cron_minute=50,
        ),
        JobSpec(
            "catch_up",
            job_catch_up,
            30,
            "Run the EOD update if it is owed for the last completed session (missed/slept)",
        ),
        JobSpec(
            "agents_daily",
            job_agents_daily,
            24 * 60,
            "Bounded research agents: read-only reports (config-gated OFF)",
            cron_hour=18,
            cron_minute=45,
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

    with session_scope(write=True) as session:
        run_alert_cycle(session)


# --------------------------------------------------------------------------- #
# Worker liveness, expected-session logic, catch-up
# --------------------------------------------------------------------------- #
HEARTBEAT_INTERVAL_S = 30
WORKER_STALE_AFTER_S = 3 * HEARTBEAT_INTERVAL_S
EOD_CRON = (17, 30)  # America/New_York — matches the daily_eod_update JobSpec
CATCH_UP_RETRY_BACKOFF = timedelta(hours=2)
WORKER_NAME = "scheduler"


def record_heartbeat(
    scheduler: BackgroundScheduler | None,
    *,
    started_at: datetime,
    worker: str = WORKER_NAME,
    detail: str = "",
) -> None:
    """Upsert this worker's liveness row with the scheduler's real next-run
    times. Best-effort: a DB hiccup must never stop the worker."""
    import os
    import socket

    try:
        from sqlalchemy import select

        from signalforge.db.models import WorkerHeartbeat
        from signalforge.db.session import session_scope

        next_runs: dict[str, str | None] = {}
        if scheduler is not None:
            for job in scheduler.get_jobs():
                nrt = getattr(job, "next_run_time", None)
                next_runs[job.id] = nrt.astimezone(UTC).isoformat() if nrt else None

        def _write() -> None:
            with session_scope(write=True) as session:
                row = session.scalar(
                    select(WorkerHeartbeat).where(WorkerHeartbeat.worker == worker)
                )
                if row is None:
                    row = WorkerHeartbeat(
                        worker=worker, started_at=started_at, last_beat_at=started_at
                    )
                    session.add(row)
                row.host = socket.gethostname()[:120]
                row.pid = os.getpid()
                row.started_at = started_at
                row.last_beat_at = datetime.now(UTC)
                row.next_runs_json = next_runs
                row.detail = detail[:300]

        retry_on_lock(_write, attempts=3, backoff_s=(0.2, 0.5), label="heartbeat")
    except Exception as exc:
        # WARNING, not debug: a silent heartbeat failure would make /ops report a
        # live worker as dead with nothing in the log to tell the two apart.
        _log.warning("worker.heartbeat_failed", error=repr(exc)[:200])


def other_live_worker() -> str | None:
    """A fresh heartbeat from a different pid/host means a worker is alive
    somewhere else (another container/host sharing the database)."""
    import os
    import socket

    from sqlalchemy import select

    from signalforge.db.models import WorkerHeartbeat
    from signalforge.db.session import session_scope

    try:
        with session_scope() as session:
            hb = session.scalar(
                select(WorkerHeartbeat).where(WorkerHeartbeat.worker == "scheduler")
            )
            if hb is None:
                return None
            age = (datetime.now(UTC) - hb.last_beat_at).total_seconds()
            same = hb.host == socket.gethostname()[:120] and hb.pid == os.getpid()
            if age <= WORKER_STALE_AFTER_S and not same:
                return (
                    f"a live scheduler heartbeat exists from pid {hb.pid} on {hb.host} "
                    f"({age:.0f}s ago) — stop it first"
                )
    except Exception:
        return None
    return None


def last_completed_session(now: datetime | None = None) -> date:
    """Latest exchange session past the configured EOD publication cutoff.

    Holidays never manufacture an expected bar; early closes conservatively
    retain the configured post-close publication cutoff.
    """
    from zoneinfo import ZoneInfo

    n = (now or datetime.now(UTC)).astimezone(ZoneInfo("America/New_York"))
    d = n.date()
    if n.weekday() >= 5 or (n.hour, n.minute) < EOD_CRON:
        d -= timedelta(days=1)
    from signalforge.data.calendar import sessions

    available = sessions(d - timedelta(days=14), d)
    if not available:
        raise RuntimeError("no exchange session available for freshness calculation")
    return available[-1]


def _session_cutoff_utc(session_date: date) -> datetime:
    from zoneinfo import ZoneInfo

    return datetime(
        session_date.year,
        session_date.month,
        session_date.day,
        EOD_CRON[0],
        EOD_CRON[1],
        tzinfo=ZoneInfo("America/New_York"),
    ).astimezone(UTC)


def _covers_configured_universe(run: IngestionRun) -> bool:
    """A ``partial`` daily-bar run that nonetheless got every CONFIGURED symbol.

    Since W6a one ingest covers the configured universe plus ~150 approved-scope
    symbols, and it is marked ``partial`` if ANY of them failed. Left alone,
    ``catch_up_pending`` would then see "no OK ingestion since the close" every
    30 minutes and re-run a ~30-minute EOD chain all evening over one
    permanently-bad ticker — hammering the provider and producing the identical
    ``partial`` each time.

    So a partial run counts as "the session was covered" only when the
    configured universe — the core every non-approved-scope scan reads — came
    back intact. A broad provider outage fails configured symbols too, so it
    still triggers a catch-up; a single bad approved-scope symbol does not, and
    is handled where it belongs: ``data_readiness`` blocks that one universe and
    names the symbol, and the DATA_ISSUE alert path already fires on ``partial``.

    Note this is inert for the pre-W6a world: when the ingest requested only the
    configured universe, a partial run always had a failed configured symbol.
    """
    from signalforge.config import get_settings

    failed = {str(s).upper() for s in (run.symbols_failed or {})}
    if not failed:
        return False  # unattributable partial — fail closed, treat as not covered
    requested = {str(s).upper() for s in (run.symbols_requested or ())}
    configured = {s.upper() for s in get_settings().research.universe}
    if not configured or not configured <= requested:
        return False  # this run never even asked for the configured universe
    return not (configured & failed)


def catch_up_pending(now: datetime | None = None) -> tuple[bool, str]:
    """Is the daily EOD update owed for the last completed session? Pending
    when no daily-bar ingestion that covered the configured universe finished
    after that session's cutoff — ``ok``, or ``partial`` with every configured
    symbol intact (see :func:`_covers_configured_universe`).
    Backs off for ``CATCH_UP_RETRY_BACKOFF`` after a failed attempt so a
    broken provider is retried, not hammered."""
    from sqlalchemy import select

    from signalforge.db.models import IngestionRun, JobRun
    from signalforge.db.session import session_scope
    from signalforge.domain import FeedType

    now = now or datetime.now(UTC)
    expected = last_completed_session(now)
    cutoff = _session_cutoff_utc(expected)
    with session_scope() as session:
        last_ok = session.scalar(
            select(IngestionRun.finished_at)
            .where(IngestionRun.feed_type == FeedType.BAR_DAILY, IngestionRun.status == "ok")
            .order_by(IngestionRun.finished_at.desc())
            .limit(1)
        )
        # A partial run since the cutoff that still got the whole configured
        # universe counts as the session's update having run.
        if last_ok is None or last_ok < cutoff:
            for run in session.scalars(
                select(IngestionRun)
                .where(
                    IngestionRun.feed_type == FeedType.BAR_DAILY,
                    IngestionRun.status == "partial",
                    IngestionRun.finished_at.is_not(None),
                    IngestionRun.finished_at >= cutoff,
                )
                .order_by(IngestionRun.finished_at.desc())
                .limit(5)
            ):
                if _covers_configured_universe(run):
                    last_ok = run.finished_at
                    break
        last_fail = session.scalar(
            select(JobRun)
            .where(
                JobRun.name.in_(("daily_eod_update", "catch_up")),
                JobRun.status == "failed",
            )
            .order_by(JobRun.started_at.desc())
            .limit(1)
        )
    if last_ok is not None and last_ok >= cutoff:
        return False, f"daily bars for {expected.isoformat()} ingested at {last_ok.isoformat()}"
    if last_fail is not None and now - last_fail.started_at < CATCH_UP_RETRY_BACKOFF:
        return (
            False,
            f"catch-up owed for {expected.isoformat()} but backing off after a failed attempt "
            f"at {last_fail.started_at.isoformat()} ({last_fail.detail[:80]})",
        )
    owed = f"no OK daily-bar ingestion since the {expected.isoformat()} close"
    if last_ok is not None:
        owed += f" (last OK: {last_ok.isoformat()})"
    return True, owed


def job_catch_up() -> None:
    """Every 30 min: if the EOD update is owed for the last completed session
    (missed cron while the Mac slept, worker restarted, provider outage),
    run it now. Idempotent — a successful update clears the pending state."""
    if _EOD_UPDATE_LOCK.locked():
        _log.info("catch_up.skipped", reason="an EOD update is running right now")
        return
    pending, reason = catch_up_pending()
    if not pending:
        _log.info("catch_up.not_pending", reason=reason)
        return
    _log.warning("catch_up.running", reason=reason)
    job_daily_eod_update()


# --------------------------------------------------------------------------- #
# APScheduler wiring
# --------------------------------------------------------------------------- #
def _last_scan_age() -> timedelta | None:
    from sqlalchemy import select

    from signalforge.db.models import ScanRun
    from signalforge.db.session import session_scope
    from signalforge.research.candidates import not_universe_scan

    with session_scope() as session:
        last = session.scalar(
            select(ScanRun.started_at)
            .where(not_universe_scan(session))
            .order_by(ScanRun.started_at.desc())
            .limit(1)
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
            guarded("catchup_approved_scope_scan", job_approved_scope_scan)()
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
            # A self-guarded spec brings its own kill-switch handling and must
            # not be double-wrapped: guarded() would return before that
            # wrapper's protective branch could run. Default False, so every
            # job in default_job_specs() is registered exactly as before.
            spec.fn if spec.self_guarded else guarded(spec.name, spec.fn),
            id=spec.name,
            name=spec.description,
            replace_existing=True,
            **trigger_kwargs,
        )
    return scheduler
