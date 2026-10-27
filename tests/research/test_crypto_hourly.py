"""CRYPTO-H1 hourly research — synthetic hourly bars, no provider."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
from sqlalchemy.orm import Session

from signalforge.db.models import CryptoBarIntraday
from signalforge.domain import LatencyCategory
from signalforge.research.fx import hourly as hr


def _load(session: Session, pair: str, n: int, seed: int) -> None:
    rng = np.random.default_rng(seed)
    closes = 30000 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    t0 = datetime(2021, 1, 1, tzinfo=UTC)
    prev = float(closes[0])
    now = datetime(2026, 1, 1, tzinfo=UTC)
    for i, c in enumerate(closes):
        c = float(c)
        session.add(
            CryptoBarIntraday(
                pair=pair,
                bar_size="1h",
                bar_start=t0 + timedelta(hours=i),
                open=prev,
                high=max(prev, c) * 1.001,
                low=min(prev, c) * 0.999,
                close=c,
                source="massive_crypto",
                latency_category=LatencyCategory.HISTORICAL,
                ingested_at=now,
            )
        )
        prev = c
    session.flush()


def test_hourly_rules_are_causal() -> None:
    from signalforge.data.series import PriceSeries

    rng = np.random.default_rng(4)
    closes = list(100 * np.exp(np.cumsum(rng.normal(0, 0.004, 1200))))
    t0 = datetime(2021, 1, 1, tzinfo=UTC)
    rows = [
        (t0 + timedelta(hours=i), c, c * 1.001, c * 0.999, c, 0.0) for i, c in enumerate(closes)
    ]
    base = PriceSeries.from_bars("BTCUSD", rows)
    shocked_rows = rows[:800] + [
        (t, o * 3, h * 3, lo * 3, c * 3, v) for t, o, h, lo, c, v in rows[800:]
    ]
    shocked = PriceSeries.from_bars("BTCUSD", shocked_rows)
    for s in hr.CRYPTO_H1_STRATEGIES:
        for t in range(s.warmup, 799, 13):
            assert s.signal(base.head(t), t) == s.signal(shocked.head(t), t), (s.key, t)


def test_hourly_research_runs_end_to_end_and_seals_the_final_year(session: Session) -> None:
    _load(session, "BTCUSD", 24 * 900, 1)
    _load(session, "ETHUSD", 24 * 900, 2)
    report = hr.run_crypto_hourly_research(session, ["BTCUSD", "ETHUSD"])
    assert report["version"] == "CRYPTO-H1"
    assert report["tests_run"] == 3 * 2
    sealed = datetime.fromisoformat(report["sealed_from"])
    for s in report["strategies"]:
        assert s["verdict"] in ("DEV_PASS", "DEV_FAIL")
        for p in s["pairs"]:
            assert datetime.fromisoformat(p["dev_end"]) < sealed
    keys = [s["key"] for s in report["strategies"]]
    assert keys == [s.key for s in hr.CRYPTO_H1_STRATEGIES]
