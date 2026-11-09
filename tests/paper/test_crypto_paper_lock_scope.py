"""Crypto paper cycles never hold the SQLite write lock across a replay.

Incident 2026-11-07: the hourly crypto paper job held ONE ``BEGIN IMMEDIATE``
transaction for its whole 77-minute catch-up run and six other jobs failed
``database is locked``. A cycle now replays as a plain reader and writes in one
short transaction; these tests prove another writer can commit mid-replay and
that the recorded book is unchanged (synthetic bars, no provider, no broker).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import numpy as np
import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from signalforge.db.models import (
    CryptoBarDaily,
    CryptoBarIntraday,
    CryptoHourlyPaperBook,
    CryptoHourlyPaperTrade,
    CryptoPaperBook,
    CryptoPaperTrade,
    CurrencySealedTest,
    JobRun,
)
from signalforge.domain import LatencyCategory
from signalforge.killswitch import get_kill_switch
from signalforge.paper import crypto_hourly_ledger as hl
from signalforge.paper import crypto_ledger as cl
from signalforge.research.fx import sealed as sl
from signalforge.research.fx.harness import CRYPTO_MARKET

H_KEY = "crypto_h_donchian168_trail72_volx"
D_KEY = "crypto_donchian_55"
T0 = datetime(2024, 1, 1, tzinfo=UTC)
D0 = date(2020, 1, 1)
NOW = datetime(2026, 1, 1, tzinfo=UTC)
PAIRS = ["BTCUSD", "ETHUSD"]


def _closes(n: int, seed: int, base: float, period: int, step: float, vol: float) -> np.ndarray:
    rng = np.random.default_rng(seed)
    drift = np.where((np.arange(n) // period) % 2 == 0, step, -step)  # alternating trends
    return base * np.exp(np.cumsum(drift + rng.normal(0, vol, n)))


def _hourly(n: int = 6000) -> dict[str, np.ndarray]:
    return {
        "BTCUSD": _closes(n, 4, 40000, 400, 0.0015, 0.008),
        "ETHUSD": _closes(n, 9, 2500, 350, 0.0016, 0.009),
    }


def _daily(n: int = 900) -> dict[str, np.ndarray]:
    return {
        "BTCUSD": _closes(n, 3, 20000, 120, 0.004, 0.02),
        "ETHUSD": _closes(n, 5, 1500, 110, 0.004, 0.022),
    }


def _add_hourly(session: Session, closes: dict[str, np.ndarray], lo: int, hi: int) -> None:
    for pair, cs in closes.items():
        for i in range(lo, hi):
            prev = float(cs[i - 1]) if i else float(cs[0])
            c = float(cs[i])
            session.add(
                CryptoBarIntraday(
                    pair=pair,
                    bar_size="1h",
                    bar_start=T0 + timedelta(hours=i),
                    open=prev,
                    high=max(prev, c) * 1.003,
                    low=min(prev, c) * 0.997,
                    close=c,
                    volume=0.0,
                    source="massive_crypto",
                    latency_category=LatencyCategory.END_OF_DAY,
                    ingested_at=NOW,
                )
            )
    session.commit()


def _add_daily(session: Session, closes: dict[str, np.ndarray], lo: int, hi: int) -> None:
    for pair, cs in closes.items():
        for i in range(lo, hi):
            prev = float(cs[i - 1]) if i else float(cs[0])
            c = float(cs[i])
            session.add(
                CryptoBarDaily(
                    pair=pair,
                    session_date=D0 + timedelta(days=i),
                    open=prev,
                    high=max(prev, c) * 1.01,
                    low=min(prev, c) * 0.99,
                    close=c,
                    source="massive_crypto",
                    latency_category=LatencyCategory.END_OF_DAY,
                    ingested_at=NOW,
                    quality_flags=[],
                )
            )
    session.commit()


def _seal(session: Session, *, hourly: bool) -> None:
    if hourly:
        mk, _, _ = sl._lookup("crypto_hourly", H_KEY)
        market, version, key = mk.name, mk.version, H_KEY
    else:
        market, version, key = "Crypto", CRYPTO_MARKET.version, D_KEY
    session.add(
        CurrencySealedTest(
            market=market,
            version=version,
            strategy_key=key,
            sealed_from=date(2025, 1, 1),
            sealed_to=date(2025, 12, 31),
            pairs=list(PAIRS),
            result={"metrics": {"expectancy_r": 0.5}},
            verdict="SEALED_PASS",
        )
    )
    session.commit()


def _db_path(db_url: str) -> str:
    return db_url.split("///", 1)[1]


def _other_writer_commits(db_url: str, tag: str) -> None:
    """A second process-like writer with a SHORT busy timeout: if the cycle
    held the write lock, this fails ``database is locked`` within 0.2 s."""
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


def _interleave(monkeypatch: pytest.MonkeyPatch, module: Any, db_url: str) -> list[str]:
    """Wrap ``module._replay`` so a second writer commits while every pair is
    being replayed (the slow phase)."""
    committed: list[str] = []
    real: Callable[..., Any] = module._replay

    def _replay(session: Session, book: Any, strat: Any, pair: str) -> Any:
        tag = f"interleave-{module.__name__.rsplit('.', 1)[-1]}-{pair}"
        _other_writer_commits(db_url, tag)  # raises if the cycle holds the lock
        out = real(session, book, strat, pair)
        _other_writer_commits(db_url, tag + "-after")
        committed.append(pair)
        return out

    monkeypatch.setattr(module, "_replay", _replay)
    return committed


def _begin_modes() -> list[str]:
    from signalforge.db.session import get_engine

    seen: list[str] = []

    def _on_begin(conn: Any) -> None:
        seen.append("IMMEDIATE" if conn.get_execution_options().get("sqlite_write") else "BEGIN")

    event.listen(get_engine(), "begin", _on_begin)
    return seen


_ROW_TAIL = ("exit_price", "exit_reason", "pnl_r", "mark_r", "bars_held", "divergence")
_HOURLY_COLS = ("pair", "direction", "entry_at", "entry_price", "stop_price", "status", "exit_at")
_DAILY_COLS = ("pair", "direction", "entry_date", "entry_price", "stop_price", "status")


def _hourly_rows(session: Session) -> list[tuple[Any, ...]]:
    return [
        tuple(getattr(r, c) for c in (*_HOURLY_COLS, *_ROW_TAIL))
        for r in session.scalars(
            select(CryptoHourlyPaperTrade).order_by(
                CryptoHourlyPaperTrade.pair, CryptoHourlyPaperTrade.entry_at
            )
        )
    ]


def _daily_rows(session: Session) -> list[tuple[Any, ...]]:
    return [
        tuple(getattr(r, c) for c in (*_DAILY_COLS, "exit_date", *_ROW_TAIL))
        for r in session.scalars(
            select(CryptoPaperTrade).order_by(CryptoPaperTrade.pair, CryptoPaperTrade.entry_date)
        )
    ]


# --------------------------------------------------------------------------- #
# (a) a second writer commits while a cycle is mid-replay
# --------------------------------------------------------------------------- #
def test_hourly_cycle_lets_another_writer_commit_mid_replay(
    db_url: str, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from signalforge.db.session import session_scope

    closes = _hourly()
    _seal(session, hourly=True)
    hl.start_book(session, H_KEY, now=T0 + timedelta(hours=3000))
    _add_hourly(session, closes, 0, len(closes[PAIRS[0]]))
    committed = _interleave(monkeypatch, hl, db_url)
    seen = _begin_modes()
    with session_scope(write=True) as s:  # even a writer scope is demoted for the replay
        rep = hl.run_cycle(s, H_KEY, now=NOW)
    assert committed == PAIRS
    assert rep.opened, "the synthetic series must produce trades after the start hour"
    # one plain reader per pair (+ the book lookup), then exactly ONE short write
    assert seen.count("IMMEDIATE") == 1 and seen[-1] == "IMMEDIATE"
    with session_scope() as s:
        names = set(
            s.scalars(select(JobRun.name).where(JobRun.name.like("interleave-crypto_hourly%")))
        )
    assert len(names) == 2 * len(PAIRS)  # before AND after every pair's replay


def test_daily_cycle_lets_another_writer_commit_mid_replay(
    db_url: str, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from signalforge.db.session import session_scope

    closes = _daily()
    _seal(session, hourly=False)
    cl.start_book(session, D_KEY, now=datetime(2020, 6, 1, tzinfo=UTC))
    _add_daily(session, closes, 0, len(closes[PAIRS[0]]))
    committed = _interleave(monkeypatch, cl, db_url)
    seen = _begin_modes()
    with session_scope(write=True) as s:
        rep = cl.run_cycle(s, D_KEY, now=NOW)
    assert committed == PAIRS and rep.opened
    assert seen.count("IMMEDIATE") == 1 and seen[-1] == "IMMEDIATE"


def test_scheduled_hourly_job_lets_another_writer_commit_mid_run(
    db_url: str, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from signalforge import scheduler
    from signalforge.config import get_settings

    monkeypatch.setenv("CRYPTO_HOURLY_PAPER_ENABLED", "true")
    get_settings.cache_clear()
    closes = _hourly()
    _seal(session, hourly=True)
    hl.start_book(session, H_KEY, now=T0 + timedelta(hours=3000))
    _add_hourly(session, closes, 0, len(closes[PAIRS[0]]))
    committed = _interleave(monkeypatch, hl, db_url)
    scheduler.job_crypto_hourly_paper()
    assert committed == PAIRS
    session.expire_all()
    assert session.scalars(select(CryptoHourlyPaperTrade)).first() is not None


def test_run_cycle_hands_the_session_back_with_its_write_intent(
    db_url: str, session: Session
) -> None:
    from signalforge.db.session import has_write_intent, session_scope

    closes = _hourly(4500)
    _seal(session, hourly=True)
    hl.start_book(session, H_KEY, now=T0 + timedelta(hours=3000))
    _add_hourly(session, closes, 0, 4500)
    with session_scope(write=True) as s:
        hl.run_cycle(s, H_KEY, now=NOW)
        assert has_write_intent(s)
    with session_scope() as s:
        hl.run_cycle(s, H_KEY, now=NOW)
        assert not has_write_intent(s)


def test_a_failing_cycle_writes_nothing(
    db_url: str, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """All-or-nothing per book, as before the split: a pair that fails in the
    read phase leaves no row for the pairs replayed before it."""
    closes = _hourly()
    _seal(session, hourly=True)
    hl.start_book(session, H_KEY, now=T0 + timedelta(hours=3000))
    _add_hourly(session, closes, 0, len(closes[PAIRS[0]]))
    real = hl._replay

    def _replay(s: Session, book: Any, strat: Any, pair: str) -> Any:
        if pair == PAIRS[-1]:
            raise RuntimeError("bad bars")
        return real(s, book, strat, pair)

    monkeypatch.setattr(hl, "_replay", _replay)
    with pytest.raises(RuntimeError, match="bad bars"):
        hl.run_cycle(session, H_KEY, now=NOW)
    session.expire_all()
    assert _hourly_rows(session) == []


# --------------------------------------------------------------------------- #
# (c) the recorded book is unchanged: engine parity, idempotent replay,
#     kill switch still blocks opening and never opens late
# --------------------------------------------------------------------------- #
def test_hourly_replay_is_idempotent_and_matches_the_engine(session: Session) -> None:
    from signalforge.backtest.costs import CostModel
    from signalforge.research.fx.harness import backtest
    from signalforge.research.fx.hourly import load_hourly_series

    closes = _hourly()
    n = len(closes[PAIRS[0]])
    _seal(session, hourly=True)
    start = T0 + timedelta(hours=3000)
    hl.start_book(session, H_KEY, now=start)
    for lo, hi in ((0, 4000), (4000, 5000), (5000, n)):
        _add_hourly(session, closes, lo, hi)
        hl.run_cycle(session, H_KEY, now=NOW)
    first = _hourly_rows(session)
    again = hl.run_cycle(session, H_KEY, now=NOW)
    assert again.opened == [] and again.closed == [] and again.divergences == []
    session.expire_all()
    assert _hourly_rows(session) == first
    mk, strat, _ = sl._lookup("crypto_hourly", H_KEY)
    for pair in PAIRS:
        out = backtest(
            strat,
            load_hourly_series(session, pair),
            cost_model=CostModel(slippage_bps=1.0),
            spread_bps=mk.spread(pair),
        )
        engine = {t.entry_date: t for t in out.trades if t.entry_date >= start}
        rows = [r for r in first if r[0] == pair]
        assert engine and {r[2] for r in rows} == set(engine)
        for r in rows:
            assert r[3] == pytest.approx(engine[r[2]].entry_price) and r[12] == ""


def test_daily_replay_is_idempotent(session: Session) -> None:
    closes = _daily()
    _seal(session, hourly=False)
    cl.start_book(session, D_KEY, now=datetime(2020, 6, 1, tzinfo=UTC))
    for lo, hi in ((0, 400), (400, 650), (650, 900)):
        _add_daily(session, closes, lo, hi)
        cl.run_cycle(session, D_KEY, now=NOW)
    first = _daily_rows(session)
    assert first
    again = cl.run_cycle(session, D_KEY, now=NOW)
    assert again.opened == [] and again.closed == [] and again.divergences == []
    session.expire_all()
    assert _daily_rows(session) == first


def test_kill_switch_engaged_during_the_replay_still_blocks_opening(
    db_url: str, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The switch is re-checked inside the write transaction: engaging it
    while the (slow) replay runs blocks every new entry of that cycle."""
    closes = _hourly()
    _seal(session, hourly=True)
    hl.start_book(session, H_KEY, now=T0 + timedelta(hours=3000))
    _add_hourly(session, closes, 0, len(closes[PAIRS[0]]))
    real = hl._replay
    ks = get_kill_switch()

    def _replay(s: Session, book: Any, strat: Any, pair: str) -> Any:
        out = real(s, book, strat, pair)
        if pair == PAIRS[-1]:
            ks.engage("test: engaged mid-replay")
        return out

    monkeypatch.setattr(hl, "_replay", _replay)
    try:
        rep = hl.run_cycle(session, H_KEY, now=NOW)
    finally:
        ks.release("test")
    assert rep.opened == [] and rep.skipped_open_kill_switch
    session.expire_all()
    assert {r[5] for r in _hourly_rows(session)} == {"SKIPPED"}


# --------------------------------------------------------------------------- #
# overlapping cycles of ONE book (scheduled job + manual CLI run): the cycle
# whose read phase was overtaken must never write its older replay
# --------------------------------------------------------------------------- #
def _overtake(
    monkeypatch: pytest.MonkeyPatch, module: Any, other_cycle: Callable[[], None]
) -> list[int]:
    """Run ``other_cycle`` (a full cycle of the same book in another session)
    after the FIRST read phase's last-pair replay, before its write phase."""
    real: Callable[..., Any] = module._replay
    calls: list[int] = []

    def _replay(session: Session, book: Any, strat: Any, pair: str) -> Any:
        out = real(session, book, strat, pair)
        calls.append(1)
        if pair == PAIRS[-1] and len(calls) == len(PAIRS):
            monkeypatch.setattr(module, "_replay", real)
            other_cycle()
            monkeypatch.setattr(module, "_replay", _replay)
        return out

    monkeypatch.setattr(module, "_replay", _replay)
    return calls


def test_hourly_cycle_overtaken_by_a_newer_cycle_replays_again(
    db_url: str, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from signalforge.db.session import session_scope

    closes = _hourly()
    n, cut = len(closes[PAIRS[0]]), 5200
    _seal(session, hourly=True)
    hl.start_book(session, H_KEY, now=T0 + timedelta(hours=3000))
    _add_hourly(session, closes, 0, cut)
    hl.run_cycle(session, H_KEY, now=NOW)

    def newer_cycle() -> None:  # newer bars land and another process reconciles
        with session_scope(write=True) as s2:
            _add_hourly(s2, closes, cut, n)
        with session_scope(write=True) as s2:
            hl.run_cycle(s2, H_KEY, now=NOW)

    calls = _overtake(monkeypatch, hl, newer_cycle)
    with session_scope(write=True) as s:
        rep = hl.run_cycle(s, H_KEY, now=NOW)
    assert rep.concurrent_retries == 1 and len(calls) == 2 * len(PAIRS)
    assert rep.divergences == [] and rep.opened == []  # the newer cycle already did it
    session.rollback()
    session.expire_all()
    raced = _hourly_rows(session)
    raced_last = session.scalar(select(CryptoHourlyPaperBook.last_bar_at))
    assert raced and all(r[-1] == "" for r in raced)
    # identical to the same two cycles run one after another, never overlapping
    with session_scope(write=True) as s:
        s.execute(CryptoHourlyPaperTrade.__table__.delete())
        s.execute(CryptoHourlyPaperBook.__table__.update().values(last_bar_at=None))
    with session_scope(write=True) as s:
        _delete_hourly_from(s, cut)
    with session_scope(write=True) as s:
        hl.run_cycle(s, H_KEY, now=NOW)
    with session_scope(write=True) as s:
        _add_hourly(s, closes, cut, n)
    with session_scope(write=True) as s:
        hl.run_cycle(s, H_KEY, now=NOW)
    session.expire_all()
    assert _hourly_rows(session) == raced
    assert session.scalar(select(CryptoHourlyPaperBook.last_bar_at)) == raced_last


def _delete_hourly_from(session: Session, lo: int) -> None:
    session.execute(
        CryptoBarIntraday.__table__.delete().where(
            CryptoBarIntraday.bar_start >= T0 + timedelta(hours=lo)
        )
    )
    session.commit()


def test_daily_cycle_overtaken_by_a_newer_cycle_replays_again(
    db_url: str, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from signalforge.db.session import session_scope

    closes = _daily()
    n, cut = len(closes[PAIRS[0]]), 700
    _seal(session, hourly=False)
    cl.start_book(session, D_KEY, now=datetime(2020, 6, 1, tzinfo=UTC))
    _add_daily(session, closes, 0, cut)
    cl.run_cycle(session, D_KEY, now=NOW)

    def newer_cycle() -> None:
        with session_scope(write=True) as s2:
            _add_daily(s2, closes, cut, n)
        with session_scope(write=True) as s2:
            cl.run_cycle(s2, D_KEY, now=NOW)

    _overtake(monkeypatch, cl, newer_cycle)
    with session_scope(write=True) as s:
        rep = cl.run_cycle(s, D_KEY, now=NOW)
    assert rep.concurrent_retries == 1 and rep.divergences == []
    session.rollback()
    session.expire_all()
    rows = _daily_rows(session)
    assert rows and all(r[-1] == "" for r in rows)
    assert session.scalar(select(CryptoPaperBook.last_bar_date)) == D0 + timedelta(days=n - 1)


def test_cycle_overtaken_every_time_refuses_and_writes_nothing(
    db_url: str, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bounded: after ``_MAX_CYCLE_ATTEMPTS`` overtaken read phases the cycle
    refuses instead of looping, and its own (stale) replay is never written."""
    from signalforge.db.session import session_scope

    closes = _hourly(4500)
    _seal(session, hourly=True)
    hl.start_book(session, H_KEY, now=T0 + timedelta(hours=3000))
    _add_hourly(session, closes, 0, 4500)
    real = hl._replay
    stamps = iter(range(1, 100))

    def _replay(s: Session, book: Any, strat: Any, pair: str) -> Any:
        out = real(s, book, strat, pair)
        if pair == PAIRS[-1]:  # another cycle commits during EVERY read phase
            monkeypatch.setattr(hl, "_replay", real)
            with session_scope(write=True) as s2:
                hl.run_cycle(s2, H_KEY, now=NOW + timedelta(hours=next(stamps)))
            monkeypatch.setattr(hl, "_replay", _replay)
        return out

    monkeypatch.setattr(hl, "_replay", _replay)
    with session_scope(write=True) as s, pytest.raises(hl.PaperBookRefused, match="run the"):
        hl.run_cycle(s, H_KEY, now=NOW)
    session.rollback()
    session.expire_all()
    last = session.scalar(select(CryptoHourlyPaperBook.last_cycle_at))
    assert last == NOW + timedelta(hours=hl._MAX_CYCLE_ATTEMPTS)  # the other cycles' stamps
