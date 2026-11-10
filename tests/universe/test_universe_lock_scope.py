"""The universe update and the worker heartbeat never starve each other.

Incident 2026-11-08 23:15-23:19 UTC: the post-close universe update read its
config inside ``BEGIN IMMEDIATE`` and then walked 14 paced reference pages
(~2.5 min) and parsed the 420-file bulk archive (~1 min) with that write lock
held, so three worker heartbeats failed ``LockRetryExhausted``. Normalization
wrote the whole archive in one write transaction. These tests prove a second
writer with a 0.2 s busy timeout commits mid-way through every slow stage, that
the results are unchanged, and that the heartbeat rides out a short write
transaction on its own connection. Offline only: httpx.MockTransport, synthetic
bars, no provider.
"""

from __future__ import annotations

import sqlite3
import threading
import time
import types
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from signalforge.db.models import (
    AuditLog,
    Instrument,
    OHLCVDaily,
    UniverseMember,
    UniverseTicker,
    WorkerHeartbeat,
)
from signalforge.universe import normalize as nz
from signalforge.universe import screen as sc
from signalforge.universe.bulk import archive_session
from signalforge.universe.discovery import enrich_market_caps, refresh_reference
from tests.universe.test_universe_pipeline import (
    _SCREEN_NOW,
    FakeMassiveAPI,
    _bar,
    _grouped_ok,
    _ref_row,
    _screen_cfg,
    _small_universe_cfg,
    _ticker_row,
    _weekdays,
)


class _Warnings:
    """Records the scheduler's and the lock-retry helper's warnings directly:
    structlog may have cached those module loggers in an earlier test, which
    ``structlog.testing.capture_logs`` cannot see."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from signalforge import scheduler
        from signalforge.db import retry

        self.events: list[tuple[str, dict[str, Any]]] = []
        for module in (scheduler, retry):
            real = module._log

            class _Proxy:
                def __init__(self, inner: Any, sink: list[tuple[str, dict[str, Any]]]) -> None:
                    self._inner, self._sink = inner, sink

                def warning(self, event: str, **kw: Any) -> None:
                    self._sink.append((event, kw))

                def __getattr__(self, name: str) -> Any:
                    return getattr(self._inner, name)

            monkeypatch.setattr(module, "_log", _Proxy(real, self.events))

    def named(self, event: str) -> list[dict[str, Any]]:
        return [kw for e, kw in self.events if e == event]


def _db_path(db_url: str) -> str:
    return db_url.split("///", 1)[1]


def _other_writer_commits(db_url: str, tag: str) -> None:
    """A second writer with a SHORT busy timeout: if the code under test held
    the write lock, this fails ``database is locked`` within 0.2 s."""
    conn = sqlite3.connect(_db_path(db_url), timeout=0.2, isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO job_run (name, started_at, status, detail) VALUES (?, ?, 'ok', '')",
            (tag[:60], datetime.now(UTC).isoformat(sep=" ")),
        )
        conn.execute("COMMIT")
    finally:
        conn.close()


def _interleaved(db_url: str, prefix: str) -> int:
    conn = sqlite3.connect(_db_path(db_url))
    try:
        return int(
            conn.execute(
                "SELECT count(*) FROM job_run WHERE name LIKE ?", (f"{prefix}%",)
            ).fetchone()[0]
        )
    finally:
        conn.close()


class InterleavingAPI(FakeMassiveAPI):
    """Every provider request first lets another writer commit — the request
    is where the paced (~12 s) network wait happens on the live key."""

    def __init__(self, db_url: str) -> None:
        super().__init__()
        self.db_url = db_url
        self.interleave = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.interleave:
            _other_writer_commits(self.db_url, f"il-http-{len(self.calls)}")
        return super().handler(request)


def _wrap_bulk_rows(
    monkeypatch: pytest.MonkeyPatch, module: Any, db_url: str, tag: str
) -> list[date]:
    """Let another writer commit before every archived file is parsed."""
    parsed: list[date] = []
    real: Callable[..., Any] = module.load_bulk_rows

    def _load(bf: Any) -> Any:
        _other_writer_commits(db_url, f"{tag}-{bf.session_date}")
        parsed.append(bf.session_date)
        return real(bf)

    monkeypatch.setattr(module, "load_bulk_rows", _load)
    return parsed


@contextmanager
def _write_scope_mid_read() -> Iterator[Session]:
    """A writer scope that has already read something — i.e. is INSIDE
    ``BEGIN IMMEDIATE``, the state the scheduled job used to hand over."""
    from signalforge.db.session import session_scope

    with session_scope(write=True) as s:
        s.scalar(select(func.count()).select_from(UniverseTicker))
        assert s.in_transaction()
        yield s


# --------------------------------------------------------------------------- #
# discovery: the paced reference walk
# --------------------------------------------------------------------------- #
def test_reference_walk_releases_the_callers_write_lock(db_url: str, session: Session) -> None:
    api = InterleavingAPI(db_url)
    api.reference_pages = [
        {
            "status": "OK",
            "results": [_ref_row("AAA"), _ref_row("BBB", type_="ETF")],
            "next_url": "https://api.example/v3/reference/tickers?cursor=2",
        },
        {"status": "OK", "results": [_ref_row("CCC", type_="WARRANT")]},
    ]
    api.interleave = True
    with _write_scope_mid_read() as s:
        rep = refresh_reference(s, api.client())
    assert _interleaved(db_url, "il-http-") == 2  # one per page, both committed
    assert (rep.pages, rep.upserted, rep.in_scope, rep.discovered_all_types) == (2, 3, 2, 3)
    rows = session.execute(select(UniverseTicker.ticker, UniverseTicker.security_type)).tuples()
    types_ = dict(rows.all())
    assert types_ == {"AAA": "CS", "BBB": "ETF", "CCC": "WARRANT"}


# --------------------------------------------------------------------------- #
# market-cap enrichment: common stocks only, bounded by the run's deadline
# --------------------------------------------------------------------------- #
def test_enrichment_never_requests_an_etf_and_lets_a_writer_commit(
    db_url: str, session: Session
) -> None:
    _ticker_row(session, "CSA")
    _ticker_row(session, "ETFX", security_type="ETF")
    _ticker_row(session, "CSB")
    session.commit()
    api = InterleavingAPI(db_url)
    api.ticker_detail["CSA"] = {"status": "OK", "results": {"market_cap": 5e9}}
    api.ticker_detail["CSB"] = {"status": "OK", "results": {"market_cap": 7e9}}
    api.interleave = True
    with _write_scope_mid_read() as s:
        done = enrich_market_caps(s, api.client(), ["CSA", "ETFX", "CSB"], max_requests=250)
    assert done == 2
    assert [u.rsplit("/", 1)[-1] for u in api.calls] == ["CSA", "CSB"]  # never ETFX
    assert _interleaved(db_url, "il-http-") == 2
    session.expire_all()
    caps = dict(
        session.execute(select(UniverseTicker.ticker, UniverseTicker.market_cap)).tuples().all()
    )
    assert caps == {"CSA": 5e9, "ETFX": None, "CSB": 7e9}


def test_enrichment_stops_at_the_runs_deadline(session: Session) -> None:
    _ticker_row(session, "CSA")
    session.commit()
    api = FakeMassiveAPI()
    done = enrich_market_caps(
        session, api.client(), ["CSA"], max_requests=250, deadline=time.monotonic() - 1
    )
    assert done == 0 and api.calls == []


# --------------------------------------------------------------------------- #
# screen: parsing the archive
# --------------------------------------------------------------------------- #
def _screen_fixture(session: Session) -> None:
    dates = _weekdays(date(2026, 6, 1), 25)
    api = FakeMassiveAPI()
    for i, d in enumerate(dates):
        rows = [
            _bar("GOOD", 100.0, volume=200_000),
            _bar("LOWPRICE", 3.0, volume=40_000_000, vw=3.0),
            _bar("QUALJUMP", 160.0 if i == 12 else 100.0, volume=200_000),
            _bar("ETFA", 100.0, volume=250_000),
        ]
        api.grouped[d.isoformat()] = _grouped_ok(rows)
    client = api.client()
    for d in dates:
        archive_session(session, client, d)
    old = date(2000, 1, 1)
    _ticker_row(session, "GOOD", market_cap=5e9, list_date=old)
    _ticker_row(session, "LOWPRICE", market_cap=5e9, list_date=old)
    _ticker_row(session, "QUALJUMP", market_cap=5e9, list_date=old)
    _ticker_row(session, "ETFA", security_type="ETF", list_date=old)
    session.commit()


def _members(session: Session, run_id: int) -> list[tuple[Any, ...]]:
    return [
        (m.ticker, m.eligible, tuple(m.exclusion_reasons), tuple(m.flags), m.last_close)
        for m in session.scalars(
            select(UniverseMember)
            .where(UniverseMember.run_id == run_id)
            .order_by(UniverseMember.ticker)
        )
    ]


def test_screen_parses_the_archive_without_the_write_lock(
    db_url: str, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from signalforge.db.session import session_scope

    _screen_fixture(session)
    cfg = _screen_cfg()
    with session_scope(write=True) as s:  # baseline: no other writer
        base = sc.run_screen(s, cfg, now=_SCREEN_NOW)
    parsed = _wrap_bulk_rows(monkeypatch, sc, db_url, "il-screen")
    with _write_scope_mid_read() as s:
        rep = sc.run_screen(s, cfg, now=_SCREEN_NOW)
    assert len(parsed) == 25 and _interleaved(db_url, "il-screen-") == 25
    assert rep.eligible_symbols == base.eligible_symbols == ["ETFA", "GOOD"]
    assert rep.excluded_by_reason == base.excluded_by_reason
    assert rep.run_id != base.run_id
    assert _members(session, rep.run_id) == _members(session, base.run_id)


# --------------------------------------------------------------------------- #
# normalize: chunked commits, parsing outside any transaction, resumable
# --------------------------------------------------------------------------- #
def _normalize_fixture(session: Session, n: int = 4) -> list[date]:
    cfg = _small_universe_cfg()
    dates = _weekdays(date(2026, 6, 1), n)
    api = FakeMassiveAPI()
    for i, d in enumerate(dates):
        api.grouped[d.isoformat()] = _grouped_ok(
            [
                _bar("AAA", 10.0 + i, volume=1_000),
                _bar("BBB", 20.0 + i, volume=2_000),
                _bar("SPY", 400.0 + i, volume=5_000),
                _bar("ZZZ", 5.0, volume=100),
            ]
        )
    client = api.client()
    for d in dates:
        archive_session(session, client, d, source=cfg.normalized_source)
    session.commit()
    return dates


def _bars(session: Session) -> list[tuple[Any, ...]]:
    return [
        tuple(r)
        for r in session.execute(
            select(Instrument.symbol, OHLCVDaily.session_date, OHLCVDaily.close, OHLCVDaily.source)
            .join(Instrument, Instrument.id == OHLCVDaily.instrument_id)
            .order_by(Instrument.symbol, OHLCVDaily.session_date)
        )
    ]


def _rows_per_session(db_url: str, source: str) -> dict[date, int]:
    """What a concurrent reader on its own connection sees right now."""
    conn = sqlite3.connect(_db_path(db_url), timeout=1)
    try:
        return {
            date.fromisoformat(str(d)): int(n)
            for d, n in conn.execute(
                "SELECT session_date, count(*) FROM ohlcv_daily WHERE source = ? "
                "GROUP BY session_date",
                (source,),
            )
        }
    finally:
        conn.close()


def test_normalize_commits_whole_sessions_and_parses_without_the_write_lock(
    db_url: str, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import event

    from signalforge.db.session import get_engine

    dates = _normalize_fixture(session)
    cfg = _small_universe_cfg()
    monkeypatch.setattr(nz, "_CHUNK", 2)  # 3 new rows per file -> 2 statements per file
    parsed = _wrap_bulk_rows(monkeypatch, nz, db_url, "il-norm")
    seen: list[dict[date, int]] = []
    real_insert = nz.insert

    def _insert(*a: Any, **k: Any) -> Any:  # a reader looks between the statements
        seen.append(_rows_per_session(db_url, cfg.normalized_source))
        return real_insert(*a, **k)

    commits: list[int] = []

    def _on_commit(_conn: Any) -> None:
        commits.append(1)

    monkeypatch.setattr(nz, "insert", _insert)
    engine = get_engine()
    event.listen(engine, "commit", _on_commit)
    try:
        with _write_scope_mid_read() as s:
            rep = nz.normalize_symbols(s, ["AAA", "BBB"], cfg)
    finally:
        event.remove(engine, "commit", _on_commit)
    # another writer committed before every file was parsed: no transaction open
    assert parsed == dates and _interleaved(db_url, "il-norm-") == len(dates)
    assert rep.rows_written == 3 * len(dates) and rep.symbols == 3
    assert len(seen) == 2 * len(dates)  # 2 insert statements per session...
    # ...but a concurrent reader only ever sees whole sessions (3 rows) or none
    assert seen and all(set(snap.values()) <= {3} for snap in seen), seen
    # one write transaction per session (+ the caller's read, the instruments
    # step and the final feed-success write), never one per statement
    assert len(dates) <= len(commits) <= len(dates) + 4
    expected = [
        (sym, d, base + i, cfg.normalized_source)
        for sym, base in (("AAA", 10.0), ("BBB", 20.0), ("SPY", 400.0))
        for i, d in enumerate(dates)
    ]
    assert _bars(session) == expected
    with _write_scope_mid_read() as s:
        assert nz.normalize_symbols(s, ["AAA", "BBB"], cfg).rows_written == 0  # idempotent


def test_grid_reading_between_normalized_sessions_sees_only_whole_sessions(
    db_url: str, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review finding 2026-11-09: the grid (cron 18:50 ET) ran inside the
    universe update (2026-11-08 23:50 UTC, inside 23:15 -> 00:09). With rows
    committed mid-session it could trade AAA on session D and BBB on D-1. Run
    the REAL grid between every archived file: every symbol it loads is on the
    same latest session, and the final run sees all three on the last one."""
    from signalforge.config.research import GridConfig
    from signalforge.db.session import session_scope
    from signalforge.grid.live import run_grid_daily

    dates = _normalize_fixture(session)
    cfg = _small_universe_cfg()
    grid_cfg = GridConfig.model_validate(
        {
            "enabled": True,
            "universe_name": "test",
            "universe_size": 5,
            "starting_cash": 1_000.0,
            "per_symbol_cap": 50.0,
            "source": cfg.normalized_source,
        }
    )
    monkeypatch.setattr(nz, "_CHUNK", 2)  # sessions span several insert statements
    real: Callable[..., Any] = nz.load_bulk_rows
    runs: list[dict[str, int]] = []

    def _grid_then_parse(bf: Any) -> Any:
        with session_scope(write=True) as gs:
            res = run_grid_daily(gs, cfg=grid_cfg, as_of=dates[-1], symbols=["AAA", "BBB", "SPY"])
        runs.append(dict(res.sessions))
        return real(bf)

    monkeypatch.setattr(nz, "load_bulk_rows", _grid_then_parse)
    with session_scope(write=True) as s:
        nz.normalize_symbols(s, ["AAA", "BBB"], cfg)
    assert len(runs) == len(dates)
    # before the 2nd file no symbol has the two bars the rule needs; after
    # that every symbol it loads is on ONE session (never a mix of D and D-1)
    assert all(len(r) <= 1 for r in runs), runs
    assert all(sum(r.values()) in (0, 3) for r in runs), runs
    with session_scope(write=True) as gs:
        final = run_grid_daily(gs, cfg=grid_cfg, as_of=dates[-1], symbols=["AAA", "BBB", "SPY"])
    assert final.sessions == {dates[-1].isoformat(): 3}


def test_normalize_cut_short_keeps_committed_sessions_and_resumes_identically(
    db_url: str, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from signalforge.db.session import session_scope

    dates = _normalize_fixture(session)
    cfg = _small_universe_cfg()
    monkeypatch.setattr(nz, "_CHUNK", 2)  # sessions span several insert statements
    real: Callable[..., Any] = nz.load_bulk_rows

    def _crash_on_third(bf: Any) -> Any:
        if bf.session_date == dates[2]:
            raise OSError("disk hiccup")
        return real(bf)

    monkeypatch.setattr(nz, "load_bulk_rows", _crash_on_third)
    with pytest.raises(OSError), session_scope(write=True) as s:
        nz.normalize_symbols(s, ["AAA", "BBB"], cfg)
    # committed sessions kept, whole
    assert {d for _, d, _, _ in _bars(session)} == set(dates[:2])
    assert len(_bars(session)) == 3 * 2
    session.commit()  # end this reader's snapshot before looking again
    monkeypatch.setattr(nz, "load_bulk_rows", real)
    with session_scope(write=True) as s:
        rep = nz.normalize_symbols(s, ["AAA", "BBB"], cfg)
    assert rep.rows_written == 3 * (len(dates) - 2) and rep.rows_skipped == 3 * 2
    assert len(_bars(session)) == 3 * len(dates)


# --------------------------------------------------------------------------- #
# the scheduled job end to end, with the real heartbeat beating throughout
# --------------------------------------------------------------------------- #
def test_universe_update_job_lets_writers_and_the_heartbeat_commit_mid_run(
    db_url: str, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from signalforge import scheduler
    from signalforge.universe import pipeline

    # require_market_cap=False: AAPL (no cap yet) survives the screen, so the
    # enrichment request runs too; QQQ is an ETF and must never be requested.
    cfg = _small_universe_cfg(enabled=True, max_runtime_seconds=600, require_market_cap=False)
    api = InterleavingAPI(db_url)
    today = datetime.now(UTC).date()
    for d in _weekdays(today - timedelta(days=21), 15):
        api.grouped[d.isoformat()] = _grouped_ok(
            [_bar("AAPL", 100.0), _bar("QQQ", 300.0), _bar("SPY", 400.0)]
        )
    api.reference_pages = [
        {
            "status": "OK",
            "results": [
                _ref_row("AAPL", type_="CS", list_date="2000-01-01"),
                _ref_row("QQQ", type_="ETF", list_date="2000-01-01"),
            ],
        }
    ]
    api.ticker_detail["AAPL"] = {"status": "OK", "results": {"market_cap": 3e12}}
    research = types.SimpleNamespace(universe_pipeline=cfg, enabled_horizons=[])
    monkeypatch.setattr("signalforge.settings_store.effective_research_config", lambda s: research)
    monkeypatch.setattr(pipeline, "effective_research_config", lambda s: research)
    monkeypatch.setattr(pipeline, "GroupedDailyClient", lambda **_: api.client())

    started = datetime.now(UTC)
    beats: list[int] = []

    def _beat_then_parse(module: Any, tag: str) -> None:
        real: Callable[..., Any] = module.load_bulk_rows

        def _load(bf: Any) -> Any:
            _other_writer_commits(db_url, f"{tag}-{bf.session_date}")
            scheduler.record_heartbeat(None, started_at=started, detail=tag)
            beats.append(1)
            return real(bf)

        monkeypatch.setattr(module, "load_bulk_rows", _load)

    _beat_then_parse(sc, "il-screen")
    _beat_then_parse(nz, "il-norm")
    api.interleave = True
    warned = _Warnings(monkeypatch)
    scheduler.job_universe_update()

    assert warned.named("worker.heartbeat_failed") == [] and warned.named("db.lock_retry") == []
    assert _interleaved(db_url, "il-http-") == len(api.calls) >= 4  # walk + fetch + cap
    assert _interleaved(db_url, "il-screen-") >= 2 and _interleaved(db_url, "il-norm-") >= 2
    assert beats
    hb = session.scalar(select(WorkerHeartbeat))
    assert hb is not None and hb.detail == "il-norm"
    # results: AAPL and QQQ are eligible; AAPL's cap is filled after the screen;
    # both + the SPY proxy are normalized for every archived session.
    audit = session.scalar(select(AuditLog).where(AuditLog.action == "universe.update"))
    assert audit is not None
    after = audit.after_json
    assert after["market_caps_enriched"] == 1
    assert after["normalize"]["symbols"] == 3
    sessions_archived = after["backfill"]["sessions_archived"]
    assert after["normalize"]["rows_written"] == 3 * sessions_archived
    assert [u.rsplit("/", 1)[-1] for u in api.calls if "/reference/tickers/" in u] == ["AAPL"]
    assert session.scalar(
        select(UniverseTicker.market_cap).where(UniverseTicker.ticker == "AAPL")
    ) == pytest.approx(3e12)
    run_id = session.scalar(select(func.max(UniverseMember.run_id)))
    eligible = session.scalars(
        select(UniverseMember.ticker).where(
            UniverseMember.run_id == run_id, UniverseMember.eligible.is_(True)
        )
    ).all()
    assert sorted(eligible) == ["AAPL", "QQQ"]


# --------------------------------------------------------------------------- #
# the heartbeat: its own connection, its own busy timeout, nothing left open
# --------------------------------------------------------------------------- #
def _hold_write_lock(db_url: str, seconds: float) -> tuple[threading.Thread, threading.Event]:
    held = threading.Event()

    def _run() -> None:
        conn = sqlite3.connect(_db_path(db_url), timeout=5, isolation_level=None)
        try:
            conn.execute("PRAGMA journal_mode=WAL")  # as the live file always is
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO job_run (name, started_at, status, detail) "
                "VALUES ('holder', '2026-01-01 00:00:00', 'ok', '')"
            )
            held.set()
            time.sleep(seconds)
            conn.execute("COMMIT")
        finally:
            conn.close()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    assert held.wait(5)
    return t, held


def test_heartbeat_rides_out_a_short_write_transaction(
    db_url: str, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from signalforge import scheduler
    from signalforge.db.session import _isolated_engine, get_engine

    # The shared pool's busy timeout is tiny here; the old heartbeat (3 tries
    # on the shared pool, ~0.3 s of waiting plus 0.7 s backoff) failed under a
    # 1.5 s hold. The heartbeat now waits on its OWN connection's timeout.
    monkeypatch.setenv("SIGNALFORGE_SQLITE_BUSY_TIMEOUT_MS", "100")
    get_engine.cache_clear()
    started = datetime(2026, 11, 9, tzinfo=UTC)
    holder, _ = _hold_write_lock(db_url, 1.5)
    warned = _Warnings(monkeypatch)
    scheduler.record_heartbeat(None, started_at=started, detail="during a long job")
    holder.join(5)
    assert warned.named("worker.heartbeat_failed") == [] and warned.named("db.lock_retry") == []
    hb = session.scalar(select(WorkerHeartbeat))
    assert hb is not None and hb.detail == "during a long job"
    # nothing held open: the heartbeat's engine never pools a connection, and a
    # writer that refuses to wait at all gets the lock straight away
    assert isinstance(_isolated_engine(db_url, scheduler.HEARTBEAT_BUSY_TIMEOUT_MS).pool, NullPool)
    conn = sqlite3.connect(_db_path(db_url), timeout=0, isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("ROLLBACK")
    finally:
        conn.close()


def test_heartbeat_that_cannot_get_the_lock_warns_and_never_raises(
    db_url: str, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from signalforge import scheduler

    monkeypatch.setattr(scheduler, "HEARTBEAT_BUSY_TIMEOUT_MS", 50)
    monkeypatch.setattr(scheduler, "HEARTBEAT_BACKOFF_S", (0.05,))
    holder, _ = _hold_write_lock(db_url, 1.0)
    warned = _Warnings(monkeypatch)
    scheduler.record_heartbeat(None, started_at=datetime.now(UTC))
    holder.join(5)
    failed = warned.named("worker.heartbeat_failed")
    assert len(failed) == 1 and "LockRetryExhausted" in failed[0]["error"]


def test_heartbeat_returns_within_its_wall_clock_budget_however_long_sqlite_waits(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review finding 2026-11-09: on the live worker one lock wait took ~2-2.5x
    its configured busy timeout, so a bound computed from the timeouts alone
    did not hold. The run loop now waits at most the budget (+1 s), and a beat
    still stuck past it makes the next one skip rather than stack up."""
    from signalforge import scheduler

    monkeypatch.setattr(scheduler, "HEARTBEAT_BUDGET_S", 1.2)
    release = threading.Event()
    entered = threading.Event()

    def _overrunning_write(**_: Any) -> None:  # SQLite ignoring its timeout
        entered.set()
        release.wait(10)

    monkeypatch.setattr(scheduler, "_write_heartbeat_row", _overrunning_write)
    warned = _Warnings(monkeypatch)
    t0 = time.monotonic()
    scheduler.record_heartbeat(None, started_at=datetime.now(UTC))
    took = time.monotonic() - t0
    try:
        assert entered.is_set() and 1.2 <= took < 1.2 + 1.0 + 0.5
        assert len(warned.named("worker.heartbeat_over_budget")) == 1
        scheduler.record_heartbeat(None, started_at=datetime.now(UTC))  # still in flight
        assert len(warned.named("worker.heartbeat_skipped")) == 1
    finally:
        release.set()
    assert scheduler._HEARTBEAT_IN_FLIGHT.acquire(timeout=5)  # the stuck beat ended
    scheduler._HEARTBEAT_IN_FLIGHT.release()
    assert warned.named("worker.heartbeat_failed") == []  # the late beat landed


def test_heartbeat_clips_lock_waits_to_its_budget_and_logs_each_wait(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from signalforge import scheduler

    monkeypatch.setattr(scheduler, "HEARTBEAT_BUDGET_S", 1.4)
    monkeypatch.setattr(scheduler, "HEARTBEAT_BUSY_TIMEOUT_MS", 20_000)  # clipped to 1 s
    holder, _ = _hold_write_lock(db_url, 3.0)
    warned = _Warnings(monkeypatch)
    t0 = time.monotonic()
    scheduler.record_heartbeat(None, started_at=datetime.now(UTC))
    took = time.monotonic() - t0
    holder.join(5)
    waits = warned.named("worker.heartbeat_lock_wait")
    # one 1 s attempt; the 0.4 s left cannot hold another one-second attempt
    assert [w["busy_timeout_ms"] for w in waits] == [1000]
    assert waits[0]["waited_s"] >= 0.9
    failed = warned.named("worker.heartbeat_failed")
    assert len(failed) == 1 and "LockRetryExhausted" in failed[0]["error"]
    assert took < 1.4 + 1.0


# --------------------------------------------------------------------------- #
# grid_daily is ordered after the universe update (and the EOD unit)
# --------------------------------------------------------------------------- #
def _grid_and_universe_enabled(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    from signalforge.grid import live
    from signalforge.grid.live import GridDailyResult

    research = types.SimpleNamespace(
        grid=types.SimpleNamespace(enabled=True),
        universe_pipeline=types.SimpleNamespace(enabled=True),
    )
    monkeypatch.setattr("signalforge.settings_store.effective_research_config", lambda s: research)
    ran: list[float] = []

    def _grid(session: Session, *, cfg: Any) -> GridDailyResult:
        ran.append(time.monotonic())
        return GridDailyResult(ran=True, reason="ok")

    monkeypatch.setattr(live, "run_grid_daily", _grid)
    return ran


def test_grid_job_fired_inside_the_universe_update_runs_after_it(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from signalforge import scheduler
    from signalforge.universe import pipeline

    grid_ran = _grid_and_universe_enabled(monkeypatch)
    universe_done: list[float] = []
    grid_errors: list[BaseException] = []

    def _grid_job() -> None:
        try:
            scheduler.job_grid_daily()
        except BaseException as exc:  # pragma: no cover - surfaced below
            grid_errors.append(exc)

    grid_thread = threading.Thread(target=_grid_job)

    def _slow_universe(session: Session, *, cfg: Any) -> None:
        grid_thread.start()  # the 18:50 ET cron fires mid-update
        time.sleep(0.4)
        assert grid_ran == []  # it waits; nothing read mid-refresh
        universe_done.append(time.monotonic())

    monkeypatch.setattr(pipeline, "run_universe_update", _slow_universe)
    scheduler.job_universe_update()
    grid_thread.join(5)
    assert not grid_errors
    assert len(grid_ran) == 1 and grid_ran[0] >= universe_done[0]
    assert not scheduler._EOD_UPDATE_LOCK.locked()


def test_grid_job_fails_closed_when_the_universe_update_never_finishes(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from signalforge import scheduler

    grid_ran = _grid_and_universe_enabled(monkeypatch)
    monkeypatch.setattr(scheduler, "UNIVERSE_WAIT_FOR_EOD_S", 0.1)
    assert scheduler._EOD_UPDATE_LOCK.acquire(blocking=False)  # a long universe update
    try:
        with pytest.raises(RuntimeError, match="grid skipped"):
            scheduler.job_grid_daily()
    finally:
        scheduler._EOD_UPDATE_LOCK.release()
    assert grid_ran == []
