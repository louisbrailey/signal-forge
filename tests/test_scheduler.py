"""Scheduler: kill-switch gating on every job, catch-up trigger, job registry."""

from __future__ import annotations

from pathlib import Path

import pytest

import signalforge.scheduler as sched
from signalforge.killswitch import get_kill_switch
from signalforge.scheduler import build_scheduler, default_job_specs, guarded

pytestmark = pytest.mark.safety


def test_guarded_job_is_a_noop_while_engaged(isolated_data_dir: Path) -> None:
    ran: list[str] = []
    job = guarded("demo", lambda: ran.append("x"))

    job()
    assert ran == ["x"]

    get_kill_switch().engage(reason="halt", actor="pytest")
    job()  # must NOT raise, must NOT run
    assert ran == ["x"]

    get_kill_switch().release(reason="resume", actor="pytest")
    job()
    assert ran == ["x", "x"]


def test_every_default_job_is_wrapped_by_the_guard(
    isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    for spec in default_job_specs():
        monkeypatch.setattr(sched, spec.fn.__name__, lambda n=spec.name: calls.append(n))

    get_kill_switch().engage(reason="halt", actor="pytest")
    # Re-read the (now patched) functions and run each through the guard.
    for spec in default_job_specs():
        guarded(spec.name, spec.fn)()
    assert calls == []  # kill switch blocked all of them

    get_kill_switch().release(reason="resume", actor="pytest")
    for spec in default_job_specs():
        guarded(spec.name, spec.fn)()
    assert sorted(calls) == sorted(s.name for s in default_job_specs())


def test_build_scheduler_registers_every_job(db_url: str) -> None:
    scheduler = build_scheduler()
    jobs = {j.id: j for j in scheduler.get_jobs()}
    assert {
        "daily_eod_update",
        "paper_mtm",
        "feed_probe",
        "health_check",
        "news_poll",
        "daily_briefing",
        "strategy_health",
    } <= set(jobs)
    # the single post-close update runs on a daily cron, not a fixed interval
    assert type(jobs["daily_eod_update"].trigger).__name__ == "CronTrigger"
    assert type(jobs["paper_mtm"].trigger).__name__ == "IntervalTrigger"


def test_guarded_records_a_job_failure_for_the_alert_policy(db_url: str) -> None:
    """A raising job must still raise (callers/APScheduler need to see it), but
    also leaves an audit_log 'job.failed' row so plan_alerts can surface it."""
    from sqlalchemy import select

    from signalforge.db.models import AuditLog
    from signalforge.db.session import session_scope

    def _boom() -> None:
        raise ValueError("simulated ingest failure")

    with pytest.raises(ValueError):
        guarded("demo_failing_job", _boom)()

    with session_scope() as session:
        row = session.scalar(
            select(AuditLog).where(
                AuditLog.action == "job.failed", AuditLog.entity == "demo_failing_job"
            )
        )
        assert row is not None
        assert "simulated ingest failure" in row.after_json["error"]


def test_catch_up_runs_when_no_scan_exists(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(sched, "job_ingest", lambda: calls.append("ingest"))
    monkeypatch.setattr(sched, "job_scan_all", lambda: calls.append("scan"))
    sched.run_catch_up()
    assert calls == ["ingest", "scan"]


def test_job_news_poll_ingests_generic_and_benzinga_feeds_separately(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """job_news_poll must call ingest_news once per adapter — the generic
    multi-publisher feed and the dedicated Benzinga News add-on feed — so the
    two stay separately tagged (NewsItem.provider) and never merge."""
    import types

    class _FakeSecret:
        def get_secret_value(self) -> str:
            return ""

    fake_news_cfg = types.SimpleNamespace(
        poll_enabled=True, us_session_only=False, lookback_days=3, per_ticker_limit=25
    )
    fake_research = types.SimpleNamespace(news=fake_news_cfg, universe=["AAPL", "SPY"])
    # Also carries news_api_key/market_data_api_key: if this is the first test
    # in the process to import massive_news.py, its own module-level
    # `from signalforge.config import get_settings` binds fresh and would
    # otherwise pick up this fake too (adapter construction reads those keys).
    fake_settings = types.SimpleNamespace(
        research=fake_research, news_api_key=_FakeSecret(), market_data_api_key=_FakeSecret()
    )
    monkeypatch.setattr("signalforge.config.get_settings", lambda: fake_settings)

    seen_providers: list[str] = []

    def fake_ingest_news(session, adapter, tickers, *, lookback_days=3, limit=50):
        from signalforge.data.news_ingest import NewsIngestReport

        seen_providers.append(adapter.provider_name)
        assert tickers == ["AAPL", "SPY"]
        return NewsIngestReport(fetched=0, written=0, duplicates=0, publishers=[])

    monkeypatch.setattr("signalforge.data.news_ingest.ingest_news", fake_ingest_news)

    sched.job_news_poll()

    assert seen_providers == ["massive_news_generic", "massive_benzinga_news"]


def test_guarded_records_a_job_run_row_for_ok_failed_and_skipped(
    db_url: str, isolated_data_dir: Path
) -> None:
    """The Operational Status page reads the last JobRun per job; every guarded
    outcome must leave one."""
    from sqlalchemy import select

    from signalforge.db.models import JobRun
    from signalforge.db.session import session_scope

    guarded("ok_job", lambda: None)()

    def _boom() -> None:
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError):
        guarded("bad_job", _boom)()

    get_kill_switch().engage(reason="halt", actor="pytest")
    guarded("skipped_job", lambda: None)()
    get_kill_switch().release(reason="resume", actor="pytest")

    with session_scope() as session:
        rows = {r.name: r for r in session.scalars(select(JobRun))}
    assert rows["ok_job"].status == "ok" and rows["ok_job"].finished_at is not None
    assert rows["bad_job"].status == "failed" and "nope" in rows["bad_job"].detail
    assert rows["skipped_job"].status == "skipped" and "kill switch" in rows["skipped_job"].detail


def test_daily_eod_update_runs_ingest_scan_then_approved_scope_scan(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import select

    from signalforge.db.models import JobRun
    from signalforge.db.session import session_scope

    calls: list[str] = []
    monkeypatch.setattr(sched, "job_ingest", lambda: calls.append("ingest"))
    monkeypatch.setattr(sched, "job_scan_all", lambda: calls.append("scan"))
    monkeypatch.setattr(sched, "job_approved_scope_scan", lambda: calls.append("approved"))
    sched.job_daily_eod_update()
    assert calls == ["ingest", "scan", "approved"]
    # the nested guard leaves its own JobRun row on the scheduled path
    with session_scope() as session:
        row = session.scalar(select(JobRun).where(JobRun.name == "approved_scope_scan"))
        assert row is not None and row.status == "ok"

    # an ingest failure must stop BOTH scans — never scan on incomplete data
    calls.clear()

    def _fail() -> None:
        calls.append("ingest")
        raise RuntimeError("provider down")

    monkeypatch.setattr(sched, "job_ingest", _fail)
    with pytest.raises(RuntimeError):
        sched.job_daily_eod_update()
    assert calls == ["ingest"]
    assert "approved_scope_scan" in sched.MANUAL_JOBS


def test_job_run_detail_is_scrubbed_before_it_reaches_the_ops_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import types

    class _Secret:
        def __init__(self, v: str) -> None:
            self._v = v

        def get_secret_value(self) -> str:
            return self._v

    fake = types.SimpleNamespace(
        market_data_api_key=_Secret("sk-REALKEY-123"),
        discord_webhook_url=_Secret("https://discord.com/api/webhooks/1/abc"),
    )
    monkeypatch.setattr("signalforge.config.get_settings", lambda: fake)
    out = sched._scrub_detail(
        "HTTPError sk-REALKEY-123 at https://discord.com/api/webhooks/1/abc "
        "Bearer xyz.123 ?apiKey=deadbeef&x=1"
    )
    assert "sk-REALKEY-123" not in out
    assert "webhooks/1/abc" not in out
    assert "xyz.123" not in out and "deadbeef" not in out
    assert out.count("[REDACTED]") >= 4


def test_job_ingest_writes_an_ingestion_run_row(db_url: str) -> None:
    """review finding (data-issue visibility, medium): the scheduled
    job_ingest -> ingest_universe path used to write no IngestionRun row at
    all, so a real production ingestion failure on the actual scheduled path
    was invisible to plan_alerts' DATA_ISSUE check (only the separate CLI
    deep-history command wrote that row)."""
    from sqlalchemy import select

    from signalforge.db.models import IngestionRun
    from signalforge.db.session import session_scope

    sched.job_ingest()

    with session_scope() as session:
        row = session.scalar(select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(1))
        assert row is not None
        assert row.status in ("ok", "partial", "failed")
        assert row.notes == "scheduled daily incremental top-up (job_ingest)"
        assert row.finished_at is not None and row.finished_at >= row.started_at
