"""SQLite multi-process MVP: deterministic reproduction of the 'database is
locked' failure and proof of the fixes (WAL + bounded busy timeout + explicit
write-intent transactions + no writer across network waits + bounded retry
that never hides a persistent failure)."""

from __future__ import annotations

import sqlite3
import threading
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from signalforge.db.retry import LockRetryExhausted, is_lock_error, retry_on_lock


# --------------------------------------------------------------------------- #
# 1. The original failure mode, reproduced with raw connections
# --------------------------------------------------------------------------- #
def test_repro_writer_holding_lock_across_a_wait_starves_other_writers(tmp_path: Path) -> None:
    """What the old catch-up ingest did: open a write transaction, then wait on
    the network (paced fetch) while holding it. Every other writer whose busy
    timeout expires meanwhile fails with 'database is locked'."""
    db = tmp_path / "lock.sqlite"
    a = sqlite3.connect(db, timeout=0.05, isolation_level=None)
    a.execute("PRAGMA journal_mode=WAL")
    a.execute("CREATE TABLE t (x INTEGER)")
    b = sqlite3.connect(db, timeout=0.05, isolation_level=None)
    b.execute("PRAGMA busy_timeout=50")

    a.execute("BEGIN IMMEDIATE")
    a.execute("INSERT INTO t VALUES (1)")  # ...then the old code waited on HTTP here
    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        b.execute("INSERT INTO t VALUES (2)")
    a.execute("COMMIT")
    b.execute("INSERT INTO t VALUES (2)")  # fine once the writer released the lock
    assert b.execute("SELECT count(*) FROM t").fetchone()[0] == 2
    a.close()
    b.close()


# --------------------------------------------------------------------------- #
# 2. Engine configuration + write-intent scopes
# --------------------------------------------------------------------------- #
def _engine_ready(monkeypatch: pytest.MonkeyPatch, busy_ms: int) -> None:
    from signalforge.db.session import reset_engine_cache

    monkeypatch.setenv("SIGNALFORGE_SQLITE_BUSY_TIMEOUT_MS", str(busy_ms))
    reset_engine_cache()


def test_engine_applies_wal_and_bounded_busy_timeout(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import text

    from signalforge.db.session import get_engine

    _engine_ready(monkeypatch, 250)
    with get_engine().connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert conn.execute(text("PRAGMA busy_timeout")).scalar() == 250
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_read_then_write_upgrade_fails_without_write_intent(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SQLITE_BUSY_SNAPSHOT: a deferred transaction that read, then tries to
    write after another connection committed, fails IMMEDIATELY — the busy
    timeout cannot help. This is why job sessions declare write intent."""
    from signalforge.db.models import AppSetting
    from signalforge.db.session import session_scope

    _engine_ready(monkeypatch, 250)
    with session_scope() as reader:  # plain (DEFERRED) transaction
        reader.execute(select(AppSetting)).all()  # establishes the read snapshot
        with session_scope(write=True) as other:
            other.add(AppSetting(key="concurrent_writer", value_json=1))
        reader.add(AppSetting(key="late_writer", value_json=1))
        with pytest.raises(OperationalError, match="database is locked"):
            reader.flush()
        reader.rollback()


def test_write_intent_scope_waits_for_the_lock_instead_of_failing(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With BEGIN IMMEDIATE the second writer waits (bounded) and then succeeds."""
    from signalforge.db.models import AppSetting
    from signalforge.db.session import session_scope

    _engine_ready(monkeypatch, 1000)
    errors: list[BaseException] = []
    done = threading.Event()

    def second_writer() -> None:
        try:
            with session_scope(write=True) as s:
                s.add(AppSetting(key="second", value_json=2))
        except BaseException as exc:
            errors.append(exc)
        finally:
            done.set()

    with session_scope(write=True) as first:
        first.add(AppSetting(key="first", value_json=1))
        first.flush()  # holds the write lock
        t = threading.Thread(target=second_writer)
        t.start()
        time.sleep(0.2)  # the second writer is now waiting on the busy handler
        assert not done.is_set()
    t.join(timeout=5)
    assert done.is_set() and not errors
    with session_scope() as s:
        assert {r.key for r in s.scalars(select(AppSetting)).all()} >= {"first", "second"}


# --------------------------------------------------------------------------- #
# 3. Concurrent API-style traffic + worker ingestion + heartbeat/job writes
# --------------------------------------------------------------------------- #
def test_concurrent_api_traffic_and_worker_ingest_never_lock(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The regression for the reported failure: a paced ingest (fetch waits)
    runs while an API-style writer, a reader, and the worker heartbeat keep
    hammering the same file with a SHORT busy timeout. Nothing may raise."""
    from signalforge.data.adapters.fixture import FixtureMarketDataAdapter
    from signalforge.data.feeds import feed_status_report
    from signalforge.data.ingest import ingest_universe
    from signalforge.db.models import JobRun, WorkerHeartbeat
    from signalforge.db.session import session_scope
    from signalforge.scheduler import record_heartbeat
    from signalforge.settings_store import set_setting

    _engine_ready(monkeypatch, 300)
    adapter = FixtureMarketDataAdapter()
    real_fetch = adapter.fetch_daily_bars

    def slow_fetch(symbol: str, start: date, end: date):  # type: ignore[no-untyped-def]
        time.sleep(0.12)  # longer than a third of the busy timeout, per symbol
        return real_fetch(symbol, start, end)

    monkeypatch.setattr(adapter, "fetch_daily_bars", slow_fetch)
    symbols = ["SPY", "AAPL", "MSFT", "NVDA", "XOM", "JPM"]
    errors: list[str] = []
    stop = threading.Event()
    counts = {"api_writes": 0, "reads": 0, "job_writes": 0, "heartbeats": 0}

    def worker_ingest() -> None:
        try:
            with session_scope(write=True) as s:
                ingest_universe(s, adapter, symbols, date(2024, 1, 1), date(2024, 6, 30))
        except Exception as exc:
            errors.append(f"ingest: {exc!r}")
        finally:
            stop.set()

    def api_writer() -> None:
        i = 0
        while not stop.is_set():
            try:
                with session_scope(write=True) as s:
                    set_setting(s, "max_alerts_per_day", i % 3)
                counts["api_writes"] += 1
            except Exception as exc:
                errors.append(f"api write: {exc!r}")
                return
            i += 1
            time.sleep(0.02)

    def api_reader() -> None:
        while not stop.is_set():
            try:
                feed_status_report()
                counts["reads"] += 1
            except Exception as exc:
                errors.append(f"api read: {exc!r}")
                return
            time.sleep(0.01)

    def job_writer() -> None:
        while not stop.is_set():
            try:
                with session_scope(write=True) as s:
                    s.add(JobRun(name="probe", started_at=datetime.now(UTC), status="ok"))
                counts["job_writes"] += 1
            except Exception as exc:
                errors.append(f"job write: {exc!r}")
                return
            time.sleep(0.03)

    def heartbeat() -> None:
        started = datetime.now(UTC)
        while not stop.is_set():
            record_heartbeat(None, started_at=started)
            counts["heartbeats"] += 1
            time.sleep(0.03)

    threads = [threading.Thread(target=f) for f in (api_writer, api_reader, job_writer, heartbeat)]
    ingest = threading.Thread(target=worker_ingest)
    for t in threads:
        t.start()
    ingest.start()
    ingest.join(timeout=30)
    stop.set()
    for t in threads:
        t.join(timeout=5)

    assert not errors, errors
    assert counts["api_writes"] > 3 and counts["reads"] > 3 and counts["job_writes"] > 3
    with session_scope() as s:
        hb = s.scalar(select(WorkerHeartbeat).where(WorkerHeartbeat.worker == "scheduler"))
        assert hb is not None  # heartbeat writes went through under contention
        assert s.scalar(select(JobRun).where(JobRun.name == "probe")) is not None


# --------------------------------------------------------------------------- #
# 4. Bounded retry: transient only; persistent failures are reported, never hidden
# --------------------------------------------------------------------------- #
def _lock_error() -> OperationalError:
    return OperationalError("INSERT ...", {}, sqlite3.OperationalError("database is locked"))


def test_retry_on_lock_retries_transient_and_reports_persistent() -> None:
    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise _lock_error()
        return "ok"

    assert retry_on_lock(flaky, attempts=3, backoff_s=(0, 0), sleep=lambda _s: None) == "ok"
    assert calls["n"] == 3

    calls["n"] = 0

    def always() -> None:
        calls["n"] += 1
        raise _lock_error()

    with pytest.raises(LockRetryExhausted, match="after 3 attempts") as excinfo:
        retry_on_lock(always, attempts=3, backoff_s=(0, 0), sleep=lambda _s: None)
    assert calls["n"] == 3 and is_lock_error(excinfo.value.last)

    calls["n"] = 0

    def other() -> None:
        calls["n"] += 1
        raise OperationalError("x", {}, sqlite3.OperationalError("no such table: nope"))

    with pytest.raises(OperationalError, match="no such table"):
        retry_on_lock(other, attempts=3, backoff_s=(0, 0), sleep=lambda _s: None)
    assert calls["n"] == 1  # a non-lock error is never retried


def test_guarded_job_reports_lock_timeout_as_failure_after_bounded_retries(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import signalforge.scheduler as sched
    from signalforge.db.models import AuditLog, JobRun
    from signalforge.db.session import session_scope

    monkeypatch.setattr(sched, "JOB_LOCK_BACKOFF_S", (0.0, 0.0, 0.0))
    monkeypatch.setattr(sched, "JOB_LOCK_ATTEMPTS", 3)
    calls = {"n": 0}

    def locked_job() -> None:
        calls["n"] += 1
        raise _lock_error()

    with pytest.raises(LockRetryExhausted):
        sched.guarded("locked_job", locked_job)()
    assert calls["n"] == 3
    with session_scope() as s:
        run = s.scalar(select(JobRun).where(JobRun.name == "locked_job"))
        assert run is not None and run.status == "failed"
        assert "lock contention" in run.detail and "after 3 attempts" in run.detail
        audit = s.scalar(
            select(AuditLog).where(AuditLog.action == "job.failed", AuditLog.entity == "locked_job")
        )
        assert audit is not None and "lock contention" in audit.after_json["error"]

    # transient: one lock error then success -> ok, exactly two attempts
    calls["n"] = 0

    def transient_job() -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise _lock_error()

    sched.guarded("transient_job", transient_job)()
    assert calls["n"] == 2
    with session_scope() as s:
        run = s.scalar(select(JobRun).where(JobRun.name == "transient_job"))
        assert run is not None and run.status == "ok"


# --------------------------------------------------------------------------- #
# 5. Recording a failure / heartbeat under a locked database never cascades
# --------------------------------------------------------------------------- #
def test_recorders_never_raise_while_the_database_is_locked(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import signalforge.scheduler as sched
    from signalforge.db.models import JobRun, WorkerHeartbeat
    from signalforge.db.session import session_scope

    _engine_ready(monkeypatch, 50)
    monkeypatch.setattr(sched, "retry_on_lock", lambda fn, **kw: fn())  # no waiting in the test
    path = db_url.split("///", 1)[1]
    holder = sqlite3.connect(path, timeout=0.05, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    holder.execute(
        "INSERT INTO job_run (name, started_at, status, detail) "
        "VALUES ('h', '2026-01-01 00:00:00', 'ok', '')"
    )
    try:
        now = datetime.now(UTC)
        sched._record_job_run("blocked", now, "failed", "boom")  # must not raise
        sched._record_job_failure("blocked", "boom")  # must not raise
        sched.record_heartbeat(None, started_at=now)  # must not raise
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    # ...and works again once the lock is gone
    sched._record_job_run("after", datetime.now(UTC), "ok")
    sched.record_heartbeat(None, started_at=datetime.now(UTC) - timedelta(seconds=1))
    with session_scope() as s:
        assert s.scalar(select(JobRun).where(JobRun.name == "after")) is not None
        assert s.scalar(select(WorkerHeartbeat)) is not None


# --------------------------------------------------------------------------- #
# 6. Review findings: write intent is sticky on the session bind — the long
#    read/compute phases must explicitly demote to a plain reader, and every
#    network fetch must run with no transaction open.
# --------------------------------------------------------------------------- #
def _begin_recorder(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    from sqlalchemy import event

    from signalforge.db.session import get_engine

    seen: list[str] = []

    def _on_begin(conn):  # type: ignore[no-untyped-def]
        seen.append("IMMEDIATE" if conn.get_execution_options().get("sqlite_write") else "DEFERRED")

    event.listen(get_engine(), "begin", _on_begin)
    return seen


def test_commit_alone_does_not_demote_a_writer_but_set_write_intent_does(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from signalforge.db.models import AppSetting
    from signalforge.db.session import session_scope, set_write_intent

    _engine_ready(monkeypatch, 250)
    seen = _begin_recorder(monkeypatch)
    with session_scope(write=True) as s:
        s.add(AppSetting(key="w1", value_json=1))
        s.commit()
        s.execute(select(AppSetting)).all()  # sticky: still IMMEDIATE
        s.commit()
        set_write_intent(s, False)
        s.execute(select(AppSetting)).all()  # now a plain reader
        s.commit()
        set_write_intent(s, True)
        s.add(AppSetting(key="w2", value_json=1))
        s.flush()
    assert seen == ["IMMEDIATE", "IMMEDIATE", "DEFERRED", "IMMEDIATE"]


def test_run_scan_compute_phase_is_a_plain_reader_and_persist_re_arms_write(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from signalforge.data.adapters.fixture import FixtureMarketDataAdapter
    from signalforge.data.ingest import ingest_universe
    from signalforge.db.models import PaperAccount
    from signalforge.db.session import session_scope
    from signalforge.domain import Horizon
    from signalforge.research.candidates import persist_scan
    from signalforge.research.scan import run_scan

    _engine_ready(monkeypatch, 250)
    with session_scope(write=True) as s:
        s.add(PaperAccount(name="default", initial_cash=10_000, cash=10_000))
        ingest_universe(
            s, FixtureMarketDataAdapter(), ["SPY", "AAPL"], date(2023, 1, 1), date(2024, 6, 30)
        )
    seen = _begin_recorder(monkeypatch)
    with session_scope(write=True) as s:
        result = run_scan(s, Horizon.SHORT_SWING, as_of=date(2024, 6, 30), symbols=["SPY", "AAPL"])
        # after run_scan the session is a plain reader ...
        assert s.in_transaction()
        assert seen[-1] == "DEFERRED"
        persist_scan(s, result)
        # ... and persist_scan re-armed write intent before writing
        assert seen[-1] == "IMMEDIATE"
    assert seen[0] == "IMMEDIATE"  # the strategy-version upsert


def test_archive_session_fetches_with_no_transaction_open(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx

    from signalforge.db.session import session_scope
    from signalforge.universe.bulk import GroupedDailyClient, archive_session

    _engine_ready(monkeypatch, 250)
    holder: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        holder["in_txn_during_fetch"] = holder["session"].in_transaction()  # type: ignore[attr-defined]
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "resultsCount": 1,
                "results": [{"T": "SPY", "o": 1, "h": 1, "l": 1, "c": 1, "v": 10, "vw": 1}],
            },
        )

    client = GroupedDailyClient(
        api_key="sf-test-key",  # pragma: allowlist secret
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        spacing_s=0,
    )
    with session_scope(write=True) as s:
        holder["session"] = s
        row = archive_session(s, client, date(2026, 9, 1))
    assert row.status == "ok"
    assert holder["in_txn_during_fetch"] is False


def test_alert_cycle_commits_each_sent_alert_so_a_retry_never_resends(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lock error AFTER an alert was dispatched must not roll back its
    AlertLog: on the retried cycle the dedupe check must still find it."""
    import signalforge.alerts.dispatch as dispatch
    from signalforge.alerts.dispatch import ALERT_TYPE_SETTING_KEYS, PlannedAlert, run_alert_cycle
    from signalforge.db.models import AlertLog
    from signalforge.db.session import session_scope
    from signalforge.domain import AlertChannel, AlertStatus, AlertType
    from signalforge.settings_store import set_setting

    sent: list[str] = []

    class _Chan:
        channel = AlertChannel.LOCAL

        def send(self, subject: str, body: str) -> bool:
            sent.append(subject)
            return True

    monkeypatch.setattr(dispatch, "available_channels", lambda: [_Chan()])
    monkeypatch.setattr(dispatch, "feed_status_report", lambda session: {"feeds": []})
    planned = [
        PlannedAlert(
            AlertType.SYSTEM_HEALTH, dedupe_key="a1", subject="first", body="b", overnight_ok=True
        ),
        PlannedAlert(
            AlertType.SYSTEM_HEALTH, dedupe_key="a2", subject="second", body="b", overnight_ok=True
        ),
    ]
    monkeypatch.setattr(dispatch, "plan_alerts", lambda session, now: list(planned))
    with session_scope(write=True) as s:
        set_setting(s, "alerts_enabled", True)
        set_setting(s, ALERT_TYPE_SETTING_KEYS[AlertType.SYSTEM_HEALTH], True)

    calls = {"n": 0}
    real_already = dispatch._already_logged

    def flaky_already_logged(session, key):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if key == "a2" and calls["n"] <= 2:  # first cycle: blow up after "first" was sent
            raise _lock_error()
        return real_already(session, key)

    monkeypatch.setattr(dispatch, "_already_logged", flaky_already_logged)
    with pytest.raises(OperationalError), session_scope(write=True) as s:
        run_alert_cycle(s, now=datetime(2024, 6, 30, 16, 0, tzinfo=UTC))
    assert sent == ["first"]
    with session_scope() as s:  # the first alert's log survived the failed cycle
        rows = list(s.scalars(select(AlertLog).where(AlertLog.status == AlertStatus.SENT)))
        assert [r.dedupe_key for r in rows] == ["a1"]
    # retried cycle: "first" is deduped, only "second" goes out
    with session_scope(write=True) as s:
        run_alert_cycle(s, now=datetime(2024, 6, 30, 16, 0, tzinfo=UTC))
    assert sent == ["first", "second"]


def test_composite_jobs_are_not_retried_at_job_level(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import signalforge.scheduler as sched

    monkeypatch.setattr(sched, "JOB_LOCK_BACKOFF_S", (0.0, 0.0, 0.0))
    calls = {"n": 0}

    def locked() -> None:
        calls["n"] += 1
        raise _lock_error()

    with pytest.raises(OperationalError):
        sched.guarded("daily_eod_update", locked)()  # in NO_JOB_LEVEL_LOCK_RETRY
    assert calls["n"] == 1
    calls["n"] = 0
    with pytest.raises(LockRetryExhausted):
        sched.guarded("paper_mtm", locked)()  # idempotent job: bounded retry
    assert calls["n"] == 3
