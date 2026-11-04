"""Hourly crypto paper ledger — synthetic hourly bars, no provider, no broker."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.backtest.costs import CostModel
from signalforge.db.models import CryptoBarIntraday, CryptoHourlyPaperTrade, CurrencySealedTest
from signalforge.domain import LatencyCategory
from signalforge.killswitch import get_kill_switch
from signalforge.paper import crypto_hourly_ledger as hl
from signalforge.research.fx import sealed as sl
from signalforge.research.fx.harness import backtest
from signalforge.research.fx.hourly import load_hourly_series

KEY = "crypto_h_donchian168_trail72_volx"
T0 = datetime(2024, 1, 1, tzinfo=UTC)
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _closes(n: int = 6000, seed: int = 4) -> np.ndarray:
    rng = np.random.default_rng(seed)
    drift = np.where((np.arange(n) // 400) % 2 == 0, 0.0015, -0.0015)  # alternating trends
    return 40000 * np.exp(np.cumsum(drift + rng.normal(0, 0.008, n)))


def _add_bars(
    session: Session, closes: np.ndarray, start: int = 0, stop: int | None = None
) -> None:
    stop = len(closes) if stop is None else stop
    for i in range(start, stop):
        prev = float(closes[i - 1]) if i else float(closes[0])
        c = float(closes[i])
        session.add(
            CryptoBarIntraday(
                pair="BTCUSD",
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


def _sealed(session: Session, verdict: str = "SEALED_PASS") -> CurrencySealedTest:
    mk, _, _ = sl._lookup("crypto_hourly", KEY)
    row = CurrencySealedTest(
        market=mk.name,
        version=mk.version,
        strategy_key=KEY,
        sealed_from=date(2025, 11, 3),
        sealed_to=date(2026, 11, 2),
        pairs=["BTCUSD"],
        result={"metrics": {"expectancy_r": 0.373}},
        verdict=verdict,
    )
    session.add(row)
    session.commit()
    return row


def _engine_trades(session: Session, after: datetime) -> list:
    s = load_hourly_series(session, "BTCUSD")
    mk, strat, _ = sl._lookup("crypto_hourly", KEY)
    out = backtest(strat, s, cost_model=CostModel(slippage_bps=1.0), spread_bps=mk.spread("BTCUSD"))
    return [t for t in out.trades if t.entry_date >= after]


def test_a_book_needs_an_hourly_sealed_pass_and_a_daily_key_is_refused(session: Session) -> None:
    with pytest.raises(hl.PaperBookRefused):
        hl.start_book(session, KEY, now=NOW)
    _sealed(session, "SEALED_FAIL")
    with pytest.raises(hl.PaperBookRefused):
        hl.start_book(session, KEY, now=NOW)
    with pytest.raises(hl.PaperBookRefused):
        hl.start_book(session, "crypto_donchian_55", now=NOW)  # daily key, not an hourly rule


def test_book_start_is_the_floored_hour_and_unique(session: Session) -> None:
    _sealed(session)
    book = hl.start_book(session, KEY, now=datetime(2026, 1, 1, 13, 37, tzinfo=UTC))
    assert book.start_at == datetime(2026, 1, 1, 13, 0, tzinfo=UTC)
    assert book.observation_end == book.start_at + timedelta(days=hl.OBSERVATION_DAYS)
    assert book.pairs == ["BTCUSD"] and book.version == "CRYPTO-H4"
    with pytest.raises(hl.PaperBookRefused):
        hl.start_book(session, KEY, now=NOW)


def test_cycles_match_the_engine_exactly_as_hourly_bars_arrive(session: Session) -> None:
    closes = _closes()
    _sealed(session)
    start = T0 + timedelta(hours=3000)
    book = hl.start_book(session, KEY, now=start)
    for stop in (4000, 5000, len(closes)):
        _add_bars(session, closes, start=stop - 1000, stop=stop)
        hl.run_cycle(session, KEY, now=NOW)
    rows = list(
        session.scalars(
            select(CryptoHourlyPaperTrade).where(CryptoHourlyPaperTrade.book_id == book.id)
        )
    )
    engine = _engine_trades(session, start)
    assert engine, "the synthetic series must produce trades after the start hour"
    assert {r.entry_at for r in rows} == {t.entry_date for t in engine}
    by_entry = {t.entry_date: t for t in engine}
    for r in rows:
        t = by_entry[r.entry_at]
        assert r.entry_price == pytest.approx(t.entry_price)
        if r.status == "CLOSED":
            assert r.exit_at == t.exit_date and r.pnl_r == pytest.approx(t.pnl_r)
        assert r.divergence == ""
    assert all(r.entry_at >= start for r in rows)


def test_kill_switch_blocks_opening_but_not_closing_and_never_opens_late(session: Session) -> None:
    closes = _closes()
    _sealed(session)
    hl.start_book(session, KEY, now=T0 + timedelta(hours=3000))
    _add_bars(session, closes, stop=4500)
    hl.run_cycle(session, KEY, now=NOW)
    ks = get_kill_switch()
    ks.engage("test")
    try:
        _add_bars(session, closes, start=4500, stop=len(closes))
        rep = hl.run_cycle(session, KEY, now=NOW)
    finally:
        ks.release("test")
    assert rep.opened == []
    assert rep.skipped_open_kill_switch, "entries during the switch are recorded as SKIPPED"
    # Positions opened BEFORE the switch are untouched by it: still OPEN or CLOSED, never SKIPPED.
    before = session.scalars(
        select(CryptoHourlyPaperTrade).where(CryptoHourlyPaperTrade.status != "SKIPPED")
    ).all()
    assert before and all(r.status in ("OPEN", "CLOSED") for r in before)
    rep2 = hl.run_cycle(session, KEY, now=NOW)  # switch released: nothing opened retroactively
    assert rep2.opened == []
    skipped = session.scalars(
        select(CryptoHourlyPaperTrade).where(CryptoHourlyPaperTrade.status == "SKIPPED")
    ).all()
    assert skipped and all(r.exit_reason == "kill_switch" for r in skipped)


def test_status_reports_the_record_against_the_sealed_result(session: Session) -> None:
    closes = _closes()
    _sealed(session)
    hl.start_book(session, KEY, now=T0 + timedelta(hours=3000))
    _add_bars(session, closes)
    hl.run_cycle(session, KEY, now=NOW)
    st = hl.status(session, KEY)
    assert st["paper_version"] == "CRYPTO-PAPER-H1" and st["version"] == "CRYPTO-H4"
    assert st["sealed_expectancy_r"] == 0.373
    assert st["closed_trades"] >= 1 and isinstance(st["total_r"], float)
    assert "No order was placed" in st["notice"]


def test_scheduled_hourly_cycle_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """``CRYPTO_HOURLY_PAPER_ENABLED`` defaults to false (its own flag, separate from the
    daily book's): the job returns before touching any book."""
    from signalforge import scheduler

    called: list[bool] = []
    monkeypatch.setattr(hl, "run_cycle", lambda *a, **k: called.append(True))
    scheduler.job_crypto_hourly_paper()
    assert called == []
