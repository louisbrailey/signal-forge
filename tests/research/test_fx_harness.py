"""FX research harness — synthetic series only, no provider, no live DB."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import numpy as np
from sqlalchemy.orm import Session

from signalforge.backtest.engine import run_backtest
from signalforge.data.series import PriceSeries
from signalforge.db.models import FxBarDaily
from signalforge.domain import LatencyCategory
from signalforge.research.fx import harness as h
from signalforge.research.fx.strategies import FX_STRATEGIES


def _weekdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _series(pair: str, closes: np.ndarray, start: date = date(2015, 1, 5)) -> PriceSeries:
    days = _weekdays(start, len(closes))
    rows = []
    prev = float(closes[0])
    for d, c in zip(days, closes, strict=True):
        c = float(c)
        o = prev
        rows.append((d, o, max(o, c) * 1.002, min(o, c) * 0.998, c, 0.0))
        prev = c
    return PriceSeries.from_bars(pair, rows)


def _random_walk(seed: int, n: int = 2600) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return 1.10 * np.exp(np.cumsum(rng.normal(0, 0.005, n)))


def test_every_strategy_is_causal_future_bars_never_change_a_past_signal() -> None:
    base = _series("EURUSD", _random_walk(1))
    rng = np.random.default_rng(99)
    shocked_close = base.close.copy()
    shocked_close[1500:] *= np.exp(rng.normal(0, 0.05, len(base) - 1500))
    hi, lo = base.high.copy(), base.low.copy()
    hi[1500:] *= 2
    lo[1500:] /= 2
    shocked = PriceSeries(base.symbol, base.dates, base.open, hi, lo, shocked_close, base.volume)
    for s in FX_STRATEGIES:
        for t in range(s.warmup, 1499, 7):
            a = s.signal(base.head(t), t)
            b = s.signal(shocked.head(t), t)
            assert a == b, (s.key, t)


def test_strategies_trade_and_always_carry_a_stop() -> None:
    series = _series("GBPUSD", _random_walk(2))
    for s in FX_STRATEGIES:
        out = run_backtest(series, s.signal, spread_bps=1.5, warmup=s.warmup)
        assert out.trades, s.key
        assert all(t.exit_reason for t in out.trades)


def test_the_sealed_year_is_never_traded_and_tests_are_counted(session: Session) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    for i, pair in enumerate(("EURUSD", "USDJPY")):
        s = _series(pair, _random_walk(10 + i) * (100 if pair == "USDJPY" else 1))
        for d, o, hi, lo, c in zip(s.dates, s.open, s.high, s.low, s.close, strict=True):
            session.add(
                FxBarDaily(
                    pair=pair,
                    session_date=d,
                    open=float(o),
                    high=float(hi),
                    low=float(lo),
                    close=float(c),
                    source="massive_fx",
                    latency_category=LatencyCategory.END_OF_DAY,
                    ingested_at=now,
                    quality_flags=[],
                )
            )
    session.flush()

    report = h.run_fx_research(session, ["EURUSD", "USDJPY"])

    sealed = date.fromisoformat(report["sealed_from"])
    assert report["tests_run"] == len(FX_STRATEGIES) * 2
    for s in report["strategies"]:
        assert s["verdict"] in ("DEV_PASS", "DEV_FAIL")
        for p in s["pairs"]:
            assert date.fromisoformat(p["dev_end"]) < sealed
        if s["verdict"] == "DEV_FAIL":
            assert s["reasons"]
    md = h.render_markdown(report)
    assert "not evaluated" in md and "No order was placed" in md


def test_random_walks_do_not_pass_the_development_gates(session: Session) -> None:
    """A pure random walk has no edge net of costs; the gates must say so."""
    series = {f"P{i}USD"[:6].ljust(6, "X"): _series("X", _random_walk(100 + i)) for i in range(4)}
    seal = h.sealed_start(series, 365)
    for s in FX_STRATEGIES:
        res = h.evaluate_strategy(s, series, seal_from=seal, gates=h.FxGates())
        assert res.verdict == "DEV_FAIL", (s.key, res.pooled.get("expectancy_r"))


def test_too_few_trades_fails_with_a_named_reason() -> None:
    series = {"EURUSD": _series("EURUSD", _random_walk(5, n=500))}
    seal = h.sealed_start(series, 365)
    res = h.evaluate_strategy(FX_STRATEGIES[0], series, seal_from=seal, gates=h.FxGates())
    assert res.verdict == "DEV_FAIL"
    assert any("OOS trades" in r for r in res.reasons)


def test_crypto_research_uses_its_own_table_costs_and_version(session: Session) -> None:
    from signalforge.db.models import CryptoBarDaily
    from signalforge.research.fx.strategies import CRYPTO_STRATEGIES, CRYPTO_STRATEGY_VERSION

    now = datetime(2026, 1, 1, tzinfo=UTC)
    closes = _random_walk(7, n=1500) * 30000
    d0 = date(2021, 1, 1)
    prev = float(closes[0])
    for i, c in enumerate(closes):
        c = float(c)
        session.add(
            CryptoBarDaily(
                pair="BTCUSD",
                session_date=d0 + timedelta(days=i),  # every calendar day
                open=prev,
                high=max(prev, c) * 1.01,
                low=min(prev, c) * 0.99,
                close=c,
                source="massive_crypto",
                latency_category=LatencyCategory.END_OF_DAY,
                ingested_at=now,
                quality_flags=[],
            )
        )
        prev = c
    session.flush()

    report = h.run_crypto_research(session, ["BTCUSD"])

    assert report["market"] == "Crypto" and report["version"] == CRYPTO_STRATEGY_VERSION
    assert report["spread_bps"] == {"BTCUSD": h.CRYPTO_SPREAD_BPS["BTCUSD"]}
    assert [s["key"] for s in report["strategies"]] == [s.key for s in CRYPTO_STRATEGIES]
    assert all(k.startswith("crypto_") for k in (s.key for s in CRYPTO_STRATEGIES))
    # crypto rows never leak into the FX loader
    assert len(h.load_series(session, "BTCUSD")) == 0
