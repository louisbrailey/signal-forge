"""Crypto paper ledger — synthetic bars, no provider, no broker."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.backtest.costs import CostModel
from signalforge.backtest.engine import run_backtest
from signalforge.db.models import CryptoBarDaily, CryptoPaperTrade, CurrencySealedTest
from signalforge.domain import LatencyCategory
from signalforge.killswitch import get_kill_switch
from signalforge.paper import crypto_ledger as cl
from signalforge.research.fx.harness import CRYPTO_MARKET, load_series
from signalforge.research.fx.strategies import CRYPTO_STRATEGIES

STRATEGY = "crypto_donchian_55"
D0 = date(2020, 1, 1)
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _closes(n: int = 900, seed: int = 3) -> np.ndarray:
    rng = np.random.default_rng(seed)
    drift = np.where((np.arange(n) // 120) % 2 == 0, 0.004, -0.004)  # alternating trends
    return 20000 * np.exp(np.cumsum(drift + rng.normal(0, 0.02, n)))


def _add_bars(
    session: Session, closes: np.ndarray, start: int = 0, stop: int | None = None
) -> None:
    stop = len(closes) if stop is None else stop
    for i in range(start, stop):
        prev = float(closes[i - 1]) if i else float(closes[0])
        c = float(closes[i])
        session.add(
            CryptoBarDaily(
                pair="BTCUSD",
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


def _sealed(session: Session, verdict: str = "SEALED_PASS") -> CurrencySealedTest:
    row = CurrencySealedTest(
        market="Crypto",
        version=CRYPTO_MARKET.version,
        strategy_key=STRATEGY,
        sealed_from=date(2025, 1, 1),
        sealed_to=date(2025, 12, 31),
        pairs=["BTCUSD"],
        result={"metrics": {"expectancy_r": 0.9}},
        verdict=verdict,
    )
    session.add(row)
    session.commit()
    return row


def _engine_trades(session: Session, after: date) -> list:
    s = load_series(session, "BTCUSD", CRYPTO_MARKET)
    strat = next(x for x in CRYPTO_STRATEGIES if x.key == STRATEGY)
    out = run_backtest(
        s,
        strat.signal,
        cost_model=CostModel(slippage_bps=1.0),
        spread_bps=CRYPTO_MARKET.spread("BTCUSD"),
        warmup=strat.warmup,
    )
    return [t for t in out.trades if t.entry_date > after]


def test_a_book_needs_a_sealed_pass(session: Session) -> None:
    with pytest.raises(cl.PaperBookRefused, match="no sealed test"):
        cl.start_book(session, STRATEGY, now=NOW)
    _sealed(session, "SEALED_FAIL")
    with pytest.raises(cl.PaperBookRefused, match="SEALED_FAIL"):
        cl.start_book(session, STRATEGY, now=NOW)


def test_book_start_is_fixed_and_unique(session: Session) -> None:
    _sealed(session)
    book = cl.start_book(session, STRATEGY, now=NOW)
    assert book.start_date == date(2026, 1, 1)
    assert book.observation_end == date(2026, 1, 1) + timedelta(days=cl.OBSERVATION_DAYS)
    assert book.pairs == ["BTCUSD"]
    with pytest.raises(cl.PaperBookRefused, match="already exists"):
        cl.start_book(session, STRATEGY, now=NOW)


def test_cycles_match_the_backtest_engine_exactly_as_bars_arrive(session: Session) -> None:
    closes = _closes()
    _sealed(session)
    book = cl.start_book(session, STRATEGY, now=datetime(2020, 6, 1, tzinfo=UTC))
    # bars arrive in three batches; the book must end identical to one replay
    for lo, hi in ((0, 400), (400, 650), (650, len(closes))):
        _add_bars(session, closes, lo, hi)
        cl.run_cycle(session, STRATEGY, now=NOW)

    expected = _engine_trades(session, book.start_date)
    rows = list(session.scalars(select(CryptoPaperTrade).order_by(CryptoPaperTrade.entry_date)))
    assert expected, "fixture must produce trades"
    assert [r.entry_date for r in rows] == [t.entry_date for t in expected]
    for r, t in zip(rows, expected, strict=True):
        assert r.direction == t.direction.value
        assert r.entry_price == pytest.approx(t.entry_price)
        if r.status == "CLOSED":
            assert r.exit_date == t.exit_date
            assert r.pnl_r == pytest.approx(t.pnl_r)
        else:
            assert t.exit_reason == "eod"
            assert r.mark_r == pytest.approx(t.pnl_r)
        assert not r.divergence
        # stop is on the losing side of the entry
        assert (r.stop_price < r.entry_price) == (r.direction == "LONG")


def test_only_trades_entered_after_the_start_date_count(session: Session) -> None:
    _add_bars(session, _closes())
    _sealed(session)
    cl.start_book(session, STRATEGY, now=datetime(2030, 1, 1, tzinfo=UTC))
    rep = cl.run_cycle(session, STRATEGY, now=NOW)
    assert rep.opened == [] and session.scalars(select(CryptoPaperTrade)).all() == []


def test_kill_switch_blocks_opening_but_not_closing(session: Session) -> None:
    closes = _closes()
    _sealed(session)
    cl.start_book(session, STRATEGY, now=datetime(2020, 6, 1, tzinfo=UTC))
    _add_bars(session, closes, 0, 500)
    cl.run_cycle(session, STRATEGY, now=NOW)
    before = {r.entry_date: r.status for r in session.scalars(select(CryptoPaperTrade))}
    open_before = [d for d, s in before.items() if s == "OPEN"]

    get_kill_switch().engage(reason="test", actor="test")
    try:
        _add_bars(session, closes, 500, len(closes))
        rep = cl.run_cycle(session, STRATEGY, now=NOW)
    finally:
        get_kill_switch().release(reason="test", actor="test")

    after = {r.entry_date: r.status for r in session.scalars(select(CryptoPaperTrade))}
    new_rows = {d: st for d, st in after.items() if d not in before}
    assert all(st == "SKIPPED" for st in new_rows.values())  # nothing new opened
    assert rep.skipped_open_kill_switch  # and it says so
    for d in open_before:  # an open trade still closes/marks normally
        row = session.scalar(select(CryptoPaperTrade).where(CryptoPaperTrade.entry_date == d))
        assert row is not None and (row.status == "CLOSED" or row.marked_at is not None)


def test_closed_trades_are_immutable_and_disagreement_is_flagged(session: Session) -> None:
    _add_bars(session, _closes())
    _sealed(session)
    cl.start_book(session, STRATEGY, now=datetime(2020, 6, 1, tzinfo=UTC))
    cl.run_cycle(session, STRATEGY, now=NOW)
    row = session.scalar(
        select(CryptoPaperTrade).where(CryptoPaperTrade.status == "CLOSED").limit(1)
    )
    assert row is not None
    row.exit_price = row.exit_price * 1.5  # simulate a stored value the replay disagrees with
    tampered = row.exit_price
    session.commit()

    rep = cl.run_cycle(session, STRATEGY, now=NOW)

    session.refresh(row)
    assert row.exit_price == tampered  # never overwritten
    assert row.divergence and rep.divergences
    assert cl.status(session, STRATEGY)["divergences"]


def test_status_reports_the_record_against_the_sealed_result(session: Session) -> None:
    _add_bars(session, _closes())
    _sealed(session)
    cl.start_book(session, STRATEGY, now=datetime(2020, 6, 1, tzinfo=UTC))
    cl.run_cycle(session, STRATEGY, now=NOW)
    st = cl.status(session, STRATEGY)
    assert st["sealed_expectancy_r"] == 0.9
    assert st["closed_trades"] >= 1
    assert "No order was placed" in st["notice"]


def test_scheduled_cycle_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from signalforge import scheduler

    called: list[bool] = []
    monkeypatch.setattr(cl, "run_cycle", lambda *a, **k: called.append(True))
    scheduler.job_crypto_paper()
    assert called == []


def test_a_trade_declined_under_the_kill_switch_is_never_opened_later(session: Session) -> None:
    closes = _closes()
    _sealed(session)
    cl.start_book(session, STRATEGY, now=datetime(2020, 6, 1, tzinfo=UTC))
    _add_bars(session, closes, 0, 500)
    cl.run_cycle(session, STRATEGY, now=NOW)

    get_kill_switch().engage(reason="test", actor="test")
    try:
        _add_bars(session, closes, 500, len(closes))
        rep = cl.run_cycle(session, STRATEGY, now=NOW)
    finally:
        get_kill_switch().release(reason="test", actor="test")
    declined = {
        r.entry_date
        for r in session.scalars(
            select(CryptoPaperTrade).where(CryptoPaperTrade.status == "SKIPPED")
        )
    }
    assert declined and len(declined) == len(rep.skipped_open_kill_switch)

    rep2 = cl.run_cycle(session, STRATEGY, now=NOW)  # switch released: replay sees them again

    assert rep2.opened == [] and rep2.skipped_open_kill_switch == []
    for d in declined:
        row = session.scalar(select(CryptoPaperTrade).where(CryptoPaperTrade.entry_date == d))
        assert row is not None and row.status == "SKIPPED" and row.pnl_r is None
    st = cl.status(session, STRATEGY)
    assert st["skipped_kill_switch"] == len(declined)
    assert all(o["entry_date"] not in {d.isoformat() for d in declined} for o in st["open"])


def test_crypto_chart_open_marks_have_unique_timestamps(session: Session) -> None:
    from signalforge.app.charts import crypto_paper_curve

    _sealed(session)
    book = cl.start_book(session, STRATEGY, now=NOW)
    book.last_bar_date = NOW.date() + timedelta(days=3)
    session.add(
        CryptoPaperTrade(
            book_id=book.id,
            pair="BTCUSD",
            direction="long",
            entry_date=NOW.date() + timedelta(days=1),
            entry_price=100,
            stop_price=90,
            status="OPEN",
            mark_r=0.5,
            marked_at=book.last_bar_date,
            costs_bps=1,
            reason="test",
            divergence="",
        )
    )
    session.commit()
    chart = crypto_paper_curve(session, STRATEGY)
    for series in chart["series"]:
        times = [point["time"] for point in series["data"]]
        assert times == sorted(set(times))
    assert chart["series"][1]["data"] == [{"time": book.last_bar_date.isoformat(), "value": 0.5}]
