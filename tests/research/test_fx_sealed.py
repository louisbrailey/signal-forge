"""One-time sealed-year test — synthetic data only."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import CurrencySealedTest, FxBarDaily
from signalforge.domain import LatencyCategory
from signalforge.research.fx import harness as h
from signalforge.research.fx import sealed as sl
from tests.research.test_fx_harness import _random_walk, _series

# Lenient dev gates so a random walk can reach the sealed step in tests.
OPEN = h.FxGates(
    min_oos_trades=1,
    min_oos_expectancy_r=-99.0,
    min_ci_low_r=-99.0,
    min_positive_folds=0,
    min_stress_expectancy_r=-99.0,
    min_positive_pair_frac=0.0,
)


def _load(session: Session, pairs: tuple[str, ...] = ("EURUSD", "GBPUSD")) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    for i, pair in enumerate(pairs):
        s = _series(pair, _random_walk(40 + i))
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
    session.commit()


def test_refused_without_a_development_pass_and_nothing_is_consumed(session: Session) -> None:
    _load(session)
    with pytest.raises(sl.SealedTestRefused, match="DEV_FAIL"):
        sl.run_sealed_test(session, "fx", "fx_donchian_55", ["EURUSD", "GBPUSD"])
    assert session.scalars(select(CurrencySealedTest)).all() == []


def test_runs_once_counts_only_sealed_entries_then_refuses(session: Session) -> None:
    _load(session)
    row = sl.run_sealed_test(session, "fx", "fx_zfade_20", ["EURUSD", "GBPUSD"], gates=OPEN)

    assert row.verdict in ("SEALED_PASS", "SEALED_FAIL")
    assert row.version == "FX-1" and row.market == "FX"
    assert len(row.data_sha256) == 64
    assert row.sealed_to >= row.sealed_from
    assert (row.sealed_to - row.sealed_from).days == 364
    assert row.result["metrics"]["n_trades"] == sum(p["trades"] for p in row.result["pairs"])
    assert row.dev_summary["pooled"]["n_trades"] >= 1
    if row.verdict == "SEALED_FAIL":
        assert row.result["reasons"]

    with pytest.raises(sl.SealedTestRefused, match="already used"):
        sl.run_sealed_test(session, "fx", "fx_zfade_20", ["EURUSD", "GBPUSD"], gates=OPEN)
    assert len(session.scalars(select(CurrencySealedTest)).all()) == 1


def test_a_crash_mid_evaluation_still_consumes_the_look(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _load(session)

    def boom(*a: object, **k: object) -> None:
        raise RuntimeError("crash")

    monkeypatch.setattr(sl, "run_backtest", boom)
    with pytest.raises(RuntimeError):
        sl.run_sealed_test(session, "fx", "fx_tsmom_126_ma50", ["EURUSD"], gates=OPEN)
    session.rollback()
    row = sl.existing(session, "fx", "fx_tsmom_126_ma50")
    assert row is not None and row.verdict == "IN_PROGRESS"
    monkeypatch.undo()
    with pytest.raises(sl.SealedTestRefused):
        sl.run_sealed_test(session, "fx", "fx_tsmom_126_ma50", ["EURUSD"], gates=OPEN)


def test_unknown_market_or_strategy_is_an_error(session: Session) -> None:
    with pytest.raises(ValueError):
        sl.run_sealed_test(session, "stocks", "fx_zfade_20", ["EURUSD"])
    with pytest.raises(ValueError):
        sl.run_sealed_test(session, "crypto", "fx_zfade_20", ["BTCUSD"])


def test_sealed_window_is_the_final_365_calendar_days() -> None:
    s = {"EURUSD": _series("EURUSD", _random_walk(1, n=800))}
    assert h.sealed_start(s, 365) == s["EURUSD"].dates[-1] - timedelta(days=364)
