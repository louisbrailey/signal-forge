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
    monkeypatch.setattr(
        "signalforge.settings_store.effective_research_config", lambda _session: fake_research
    )

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


# --------------------------------------------------------------------------
# W6a: the scheduled ingest covers every PAPER_APPROVED universe, not just the
# configured watchlist — the defect that blocked snapshot 11 every session.
# --------------------------------------------------------------------------
APPROVED_EXTRA = ["ZZA", "ZZB", "ZZC"]


def _approve_on_snapshot(symbols: list[str], *, source: str = "fixture", key: str = "snap") -> int:
    """A PAPER_APPROVED strategy version approved on a snapshot of ``symbols``.
    Returns the dataset snapshot id."""
    from datetime import date as _date

    from signalforge.db.models import (
        DataSnapshot,
        Strategy,
        StrategyPromotionEvaluation,
        StrategyVersion,
    )
    from signalforge.db.session import session_scope
    from signalforge.db.types import utcnow
    from signalforge.domain import Horizon, StrategyStatus

    with session_scope(write=True) as session:
        snap = DataSnapshot(key=key, symbols_json=list(symbols))
        session.add(snap)
        session.flush()
        strat = Strategy(
            name=f"w6a_{key}",
            horizon=Horizon.MEDIUM_SWING,
            status=StrategyStatus.PAPER_APPROVED,
        )
        session.add(strat)
        session.flush()
        ver = StrategyVersion(
            strategy_id=strat.id,
            version="0.1.0",
            git_sha="0" * 40,
            spec_json={},
            status=StrategyStatus.PAPER_APPROVED,
        )
        session.add(ver)
        session.flush()
        session.add(
            StrategyPromotionEvaluation(
                strategy_version_id=ver.id,
                dataset_snapshot_id=snap.id,
                evaluated_at=utcnow(),
                config_hash="cfg",
                spec_json_hash=f"spec-{key}",
                universe_json=list(symbols),
                window_start=_date(2020, 1, 1),
                window_end=_date(2026, 1, 1),
                data_provenance_json={"sources": [source]},
                passed=True,
            )
        )
        session.flush()
        return int(snap.id)


def _configured_universe() -> list[str]:
    from signalforge.config import get_settings

    return [s.upper() for s in get_settings().research.universe]


def test_job_ingest_covers_config_plus_every_approved_scope_universe(db_url: str) -> None:
    """The live defect (2026-09-14): job_ingest fetched only
    settings.research.universe, so the approved 150-symbol snapshot never got
    the session's bar and its own readiness gate blocked the scan every day."""
    from sqlalchemy import select

    from signalforge.db.models import IngestionRun, Instrument, OHLCVDaily
    from signalforge.db.session import session_scope
    from signalforge.research.approved_scope_scan import INGEST_PROVENANCE_KEY

    configured = _configured_universe()
    overlap = configured[0]  # a symbol in BOTH the config and the snapshot
    snapshot_symbols = [overlap, *APPROVED_EXTRA]
    snap_id = _approve_on_snapshot(snapshot_symbols, key="w6a_union")

    sched.job_ingest()

    with session_scope() as session:
        row = session.scalar(select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(1))
        assert row is not None
        requested = list(row.symbols_requested)
        # union, de-duplicated, configured universe first and in its own order
        assert requested[: len(configured)] == configured
        assert requested[len(configured) :] == sorted(APPROVED_EXTRA)
        assert len(requested) == len(set(requested))
        assert requested.count(overlap) == 1

        # provenance: which symbols came from which approved snapshot
        prov = (row.gaps_json or {})[INGEST_PROVENANCE_KEY]
        assert prov["configured"] == configured
        assert [s["dataset_snapshot_id"] for s in prov["snapshots"]] == [snap_id]
        assert prov["snapshots"][0]["added"] == sorted(APPROVED_EXTRA)
        assert prov["snapshots"][0]["source"] == "fixture"
        assert row.notes.startswith("scheduled daily incremental top-up (job_ingest)")
        assert f"snapshot {snap_id}" in row.notes

        # and the bars for the approved-only symbols really landed
        for sym in APPROVED_EXTRA:
            inst = session.scalar(select(Instrument).where(Instrument.symbol == sym))
            assert inst is not None, f"{sym} was never ingested"
            bars = session.scalar(
                select(OHLCVDaily.id).where(OHLCVDaily.instrument_id == inst.id).limit(1)
            )
            assert bars is not None, f"{sym} got no daily bars"


def test_job_ingest_skips_an_approved_universe_from_another_source(db_url: str) -> None:
    """Bars are written tagged with this adapter's provider_name; fetching a
    universe approved on another source would store rows that can never satisfy
    the readiness gate they were fetched for."""
    from sqlalchemy import select

    from signalforge.db.models import IngestionRun
    from signalforge.db.session import session_scope
    from signalforge.research.approved_scope_scan import INGEST_PROVENANCE_KEY

    snap_id = _approve_on_snapshot(APPROVED_EXTRA, source="massive", key="w6a_other_source")

    sched.job_ingest()

    with session_scope() as session:
        row = session.scalar(select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(1))
        assert row is not None
        assert list(row.symbols_requested) == _configured_universe()
        prov = (row.gaps_json or {})[INGEST_PROVENANCE_KEY]
        assert prov["snapshots"] == []
        assert [u["dataset_snapshot_id"] for u in prov["excluded_other_source"]] == [snap_id]
        # nothing was added, so the routine note stays byte-identical
        assert row.notes == "scheduled daily incremental top-up (job_ingest)"


def test_startup_catch_up_and_the_30_minute_catch_up_ingest_the_same_symbols(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both catch-up paths go through job_ingest, so both must see the union —
    a startup catch-up that topped up only the watchlist would leave the
    approved scan blocked until the next 17:30 cron."""
    from signalforge.data.ingest import IngestReport, SymbolIngestResult

    _approve_on_snapshot([*APPROVED_EXTRA], key="w6a_catchup")
    seen: list[list[str]] = []

    def _fake_ingest_universe(session, adapter, symbols, start, end, **_kw):  # type: ignore[no-untyped-def]
        seen.append(list(symbols))
        report = IngestReport(provider=adapter.provider_name, started_at="now")
        report.results = [SymbolIngestResult(symbol=s, bars_written=1) for s in symbols]
        return report

    monkeypatch.setattr("signalforge.data.ingest.ingest_universe", _fake_ingest_universe)
    monkeypatch.setattr(sched, "job_scan_all", lambda: None)
    monkeypatch.setattr(sched, "job_approved_scope_scan", lambda: None)

    sched.job_ingest()  # the 17:30 cron path, via job_daily_eod_update
    sched.run_catch_up()  # startup catch-up -> guarded("catchup_ingest", job_ingest)
    monkeypatch.setattr(sched, "catch_up_pending", lambda now=None: (True, "test"))
    sched.job_catch_up()  # the 30-minute interval job -> job_daily_eod_update

    assert len(seen) == 3, "every path must have gone through job_ingest"
    assert seen[0] == seen[1] == seen[2]
    expected = _configured_universe() + sorted(APPROVED_EXTRA)
    assert seen[0] == expected


def test_catch_up_is_not_owed_when_a_partial_run_got_the_whole_configured_universe(
    db_url: str,
) -> None:
    """Regression guard for the W6a amplification: one ingest now covers ~150
    extra symbols and is marked 'partial' if ANY of them failed. Without this,
    catch_up_pending would see "no OK ingestion since the close" every 30 min
    and re-run a ~30-minute EOD chain all evening over one bad ticker."""
    from datetime import timedelta as _td

    from signalforge.db.models import IngestionRun
    from signalforge.db.session import session_scope
    from signalforge.db.types import utcnow
    from signalforge.domain import FeedType

    now = utcnow()
    cutoff = sched._session_cutoff_utc(sched.last_completed_session(now))
    configured = _configured_universe()

    def _write(symbols_failed: dict[str, str], requested: list[str]) -> None:
        from sqlalchemy import delete

        with session_scope(write=True) as session:
            # one case at a time: an earlier covering run in the same evening
            # legitimately settles the session for every later one
            session.execute(delete(IngestionRun))
            session.add(
                IngestionRun(
                    provider="fixture",
                    feed_type=FeedType.BAR_DAILY,
                    kind="incremental",
                    requested_start=now.date() - _td(days=400),
                    requested_end=now.date(),
                    symbols_requested=requested,
                    symbols_ok=[s for s in requested if s not in symbols_failed],
                    symbols_failed=symbols_failed,
                    status="partial",
                    started_at=cutoff + _td(minutes=1),
                    finished_at=cutoff + _td(minutes=31),
                )
            )

    # an approved-scope-only symbol failed: the session WAS covered
    _write({"ZZA": "HTTP 404"}, [*configured, "ZZA"])
    pending, reason = sched.catch_up_pending(now)
    assert pending is False, reason

    # a CONFIGURED symbol failed: still owed, exactly as before W6a
    _write({configured[0]: "HTTP 500", "ZZA": "HTTP 404"}, [*configured, "ZZA"])
    pending, reason = sched.catch_up_pending(now)
    assert pending is True, reason

    # a partial that names no failed symbol is unattributable -> still owed
    _write({}, [*configured, "ZZA"])
    pending, reason = sched.catch_up_pending(now)
    assert pending is True, reason


def test_job_news_poll_follows_the_operators_saved_setting(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The news switch saved from the dashboard (research overrides) must take
    effect. The job used to read only static settings, so a saved toggle was
    silently ignored."""
    from signalforge.db.session import session_scope
    from signalforge.settings_store import RESEARCH_OVERRIDES_KEY, set_setting

    calls: list[str] = []

    def fake_ingest_news(session, adapter, tickers, *, lookback_days=3, limit=50):
        from signalforge.data.news_ingest import NewsIngestReport

        calls.append(adapter.provider_name)
        return NewsIngestReport(fetched=0, written=0, duplicates=0, publishers=[])

    monkeypatch.setattr("signalforge.data.news_ingest.ingest_news", fake_ingest_news)

    sched.job_news_poll()  # default config: polling off
    assert calls == []

    with session_scope(write=True) as s:
        set_setting(
            s, RESEARCH_OVERRIDES_KEY, {"news": {"poll_enabled": True, "us_session_only": False}}
        )
    sched.job_news_poll()
    assert calls == ["massive_news_generic", "massive_benzinga_news"]
