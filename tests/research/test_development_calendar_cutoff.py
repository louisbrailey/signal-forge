"""Synthetic metadata/cutoff rows only; computation and result writers are mocked."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, event, select

from signalforge.backtest.metrics import compute_metrics
from signalforge.config.research import ResearchConfig
from signalforge.db.models import (
    BacktestRun,
    DataSnapshot,
    Instrument,
    OHLCVDaily,
    StrategyPromotionEvaluation,
    StrategySealedTest,
)
from signalforge.domain import Horizon, LatencyCategory
from signalforge.research import promotion as p
from signalforge.research.backtest_runner import DataProvenance, StrategyBacktestResult
from signalforge.research.persistence import spec_json_hash, upsert_strategy_version
from signalforge.research.strategies import TrendContinuation

START = date(2025, 1, 2)
FRIDAY = date(2025, 9, 5)
NOW = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def setup_case(session, monkeypatch):
    def make(*, linked=date(2025, 9, 8), earliest=date(2025, 9, 7), cutoff=FRIDAY):
        strategy, cfg = TrendContinuation(), ResearchConfig()
        spec = strategy.spec()
        version = upsert_strategy_version(session, spec)
        other = upsert_strategy_version(session, replace(spec, name="calendar_probe"))
        snapshot = DataSnapshot(key="calendar-only-fixture", symbols_json=["SPY", "AAPL"])
        session.add(snapshot)
        session.flush()

        def lock(ver_id, boundary):
            row = StrategySealedTest(
                strategy_version_id=ver_id,
                dataset_snapshot_id=snapshot.id,
                window_start=boundary,
                window_end=boundary + timedelta(days=365),
                universe_json=["SPY", "AAPL"],
                evaluated_at=NOW,
                metrics_json={"never_read": 99999},
                benchmark_metrics_json={"never_read": 88888},
            )
            session.add(row)
            session.flush()
            return row

        linked_row = lock(version.id, linked)
        earlier_row = lock(other.id, earliest)
        evaluation = StrategyPromotionEvaluation(
            strategy_version_id=version.id,
            dataset_snapshot_id=snapshot.id,
            evaluated_at=NOW,
            config_hash=cfg.config_hash,
            spec_json_hash=spec_json_hash(spec),
            universe_json=["SPY", "AAPL"],
            window_start=START,
            window_end=linked,
            data_provenance_json={
                "coverage": f"{START}..{cutoff}",
                "sources": ["massive"],
                "bars": 4,
                "simulated": True,
            },
            gates_json=[],
            passed=True,
            sealed_test_id=linked_row.id,
        )
        session.add(evaluation)
        for symbol in ("SPY", "AAPL"):
            inst = Instrument(symbol=symbol)
            session.add(inst)
            session.flush()
            for stamp in (START, cutoff):
                session.add(
                    OHLCVDaily(
                        instrument_id=inst.id,
                        session_date=stamp,
                        open=100,
                        high=101,
                        low=99,
                        close=100,
                        volume=1000,
                        source="massive",
                        is_simulated=True,
                        latency_category=LatencyCategory.END_OF_DAY,
                        ingested_at=NOW,
                    )
                )
        session.commit()
        calls = []

        def compute(_session, chosen, **kwargs):
            calls.append(kwargs)
            metrics = compute_metrics([])
            return StrategyBacktestResult(
                spec=chosen.spec(),
                symbols=kwargs["symbols"],
                start=kwargs["start"],
                end=kwargs["pre_sealed_end"],
                n_trades=0,
                in_sample=metrics,
                out_of_sample=metrics,
                oos_ci={},
                config_hash=kwargs["config"].config_hash,
                data=DataProvenance(("massive",), True, 4, START, cutoff),
            )

        monkeypatch.setattr(p, "run_development_backtest", compute)
        return SimpleNamespace(
            strategy=strategy,
            cfg=cfg,
            version=version,
            snapshot=snapshot,
            evaluation=evaluation,
            linked=linked_row,
            other=other,
            earlier=earlier_row,
            calls=calls,
            lock=lock,
        )

    return make


def record(session, case, until=FRIDAY, **kwargs):
    return p.record_development_oos_backtest(
        session,
        case.strategy,
        dataset_snapshot_id=case.snapshot.id,
        since=START,
        until=until,
        source="massive",
        config=case.cfg,
        persist=False,
        **kwargs,
    )


def capture_sql(session):
    statements = []

    def capture(_conn, _cur, sql, params, _ctx, _many):
        statements.append((sql, params))

    connection = session.connection()
    event.listen(connection, "before_cursor_execute", capture)
    return statements, lambda: event.remove(connection, "before_cursor_execute", capture)


@pytest.mark.parametrize(
    ("linked", "earliest", "cutoff"),
    [
        (date(2025, 9, 8), date(2025, 9, 7), date(2025, 9, 5)),  # weekend
        (date(2025, 5, 27), date(2025, 5, 26), date(2025, 5, 23)),  # Memorial Day
        (date(2025, 9, 9), date(2025, 9, 9), date(2025, 9, 8)),  # unchanged weekday
    ],
)
def test_exact_daily_session_preserves_window_and_appends_boundary_provenance(
    session, setup_case, linked, earliest, cutoff
):
    case = setup_case(linked=linked, earliest=earliest, cutoff=cutoff)
    before = deepcopy(case.evaluation.data_provenance_json)
    statements, stop = capture_sql(session)
    try:
        result = record(session, case, cutoff)
    finally:
        stop()
    assert len(case.calls) == 1 and case.calls[0]["pre_sealed_end"] == cutoff
    assert all(result.reproduces_evaluation.values())
    provenance = result.provenance["development_calendar"]
    assert provenance["expected_trading_cutoff"] == cutoff.isoformat()
    assert provenance["linked_lock"]["id"] == case.linked.id
    assert provenance["linked_lock"]["window_start"] == linked.isoformat()
    assert provenance["earliest_locked_boundary"] == earliest.isoformat()
    assert provenance["evaluation_input_scope_sha256"] == provenance["requested_input_scope_sha256"]
    assert case.evaluation.data_provenance_json == before
    assert session.scalar(select(BacktestRun.id)) is None
    sealed = [sql for sql, _ in statements if "strategy_sealed_test" in sql]
    assert sealed and all("metrics_json" not in sql and "passed" not in sql for sql in sealed)
    bars = [(sql, params) for sql, params in statements if "ohlcv_daily" in sql]
    assert bars and all("session_date =" in sql for sql, _ in bars)
    assert all(cutoff.isoformat() in params for _, params in bars)


@pytest.mark.parametrize("requested", [date(2025, 9, 4), date(2025, 9, 6), date(2025, 9, 7)])
def test_noncanonical_dates_refuse_before_any_bars_even_with_override(
    session, setup_case, requested
):
    case = setup_case()
    statements, stop = capture_sql(session)
    try:
        with pytest.raises(ValueError, match=r"canonical XNYS|sealed window"):
            record(session, case, requested, allow_mismatch=True)
    finally:
        stop()
    assert case.calls == [] and not any("ohlcv_daily" in sql for sql, _ in statements)


def test_holiday_caller_is_not_implicitly_normalized(session, setup_case):
    case = setup_case(
        linked=date(2025, 5, 27), earliest=date(2025, 5, 27), cutoff=date(2025, 5, 23)
    )
    with pytest.raises(ValueError, match="canonical XNYS"):
        record(session, case, date(2025, 5, 26))
    assert case.calls == []


def test_conflicting_trading_boundary_never_chooses_an_earlier_session(session, setup_case):
    case = setup_case(earliest=FRIDAY)
    statements, stop = capture_sql(session)
    try:
        with pytest.raises(ValueError, match="conflicting trading boundaries"):
            record(session, case, date(2025, 9, 4), allow_mismatch=True)
    finally:
        stop()
    assert case.calls == [] and not any("ohlcv_daily" in sql for sql, _ in statements)


@pytest.mark.parametrize(
    "damage",
    [
        "missing_link",
        "wrong_link",
        "missing_coverage",
        "wrong_coverage",
        "missing_count",
        "wrong_symbols",
        "wrong_source",
    ],
)
def test_missing_or_wrong_metadata_refuses_before_bars(session, setup_case, damage):
    case = setup_case()
    if damage == "missing_link":
        case.evaluation.sealed_test_id = None
    elif damage == "wrong_link":
        case.evaluation.sealed_test_id = case.earlier.id
    elif damage in {"missing_coverage", "wrong_coverage", "wrong_source", "missing_count"}:
        data = dict(case.evaluation.data_provenance_json)
        if damage == "missing_coverage":
            data.pop("coverage")
        elif damage == "wrong_coverage":
            data["coverage"] = f"{START}..2025-09-04"
        elif damage == "missing_count":
            data.pop("bars")
        else:
            data["sources"] = ["different-source"]
        case.evaluation.data_provenance_json = data
    else:
        case.snapshot.symbols_json = ["SPY"]
    session.commit()
    statements, stop = capture_sql(session)
    try:
        with pytest.raises(ValueError, match=r"linked|coverage|identity|count"):
            record(session, case, allow_mismatch=True)
    finally:
        stop()
    assert case.calls == [] and not any("ohlcv_daily" in sql for sql, _ in statements)


def test_intraday_rejected_before_any_bars_or_computation(session, setup_case):
    case = setup_case()
    case.strategy_spec = case.strategy.spec()
    case.strategy = SimpleNamespace(
        spec=lambda: replace(case.strategy_spec, horizon=Horizon.INTRADAY)
    )
    statements, stop = capture_sql(session)
    try:
        with pytest.raises(ValueError, match="daily EOD only"):
            record(session, case)
    finally:
        stop()
    assert case.calls == [] and not any("ohlcv" in sql for sql, _ in statements)


def test_missing_required_session_fails_without_moving_cutoff(session, setup_case):
    case = setup_case()
    inst = session.scalar(select(Instrument.id).where(Instrument.symbol == "AAPL"))
    session.execute(
        delete(OHLCVDaily).where(
            OHLCVDaily.instrument_id == inst, OHLCVDaily.session_date == FRIDAY
        )
    )
    session.commit()
    with pytest.raises(ValueError, match="missing required XNYS cutoff session"):
        record(session, case, allow_mismatch=True)
    assert case.calls == []


@pytest.mark.parametrize("new_boundary", [date(2025, 9, 6), date(2025, 9, 5)])
def test_writer_independently_rechecks_new_locks_without_override(
    session, setup_case, monkeypatch, new_boundary
):
    case = setup_case()
    calculated = record(session, case)
    third = upsert_strategy_version(session, replace(case.strategy.spec(), name="new_lock_probe"))
    case.lock(third.id, new_boundary)
    session.commit()
    writes = []
    monkeypatch.setattr(p, "persist_backtest_result", lambda *a, **k: writes.append(True))
    with pytest.raises(
        ValueError, match=r"sealed window|boundary provenance changed|conflicting trading"
    ):
        p.persist_development_oos_record(
            session, calculated, allow_mismatch=True, allow_duplicate=True
        )
    assert writes == [] and session.scalar(select(BacktestRun.id)) is None


def test_writer_rechecks_lost_cutoff_coverage(session, setup_case, monkeypatch):
    case = setup_case()
    calculated = record(session, case)
    session.execute(delete(OHLCVDaily).where(OHLCVDaily.session_date == FRIDAY))
    session.commit()
    writes = []
    monkeypatch.setattr(p, "persist_backtest_result", lambda *a, **k: writes.append(True))
    with pytest.raises(ValueError, match="missing required XNYS cutoff session"):
        p.persist_development_oos_record(session, calculated, allow_mismatch=True)
    assert writes == []


def test_writer_rechecks_lost_linked_metadata_before_bars(session, setup_case, monkeypatch):
    case = setup_case()
    calculated = record(session, case)
    case.evaluation.sealed_test_id = None
    session.commit()
    writes = []
    monkeypatch.setattr(p, "persist_backtest_result", lambda *a, **k: writes.append(True))
    statements, stop = capture_sql(session)
    try:
        with pytest.raises(ValueError, match="linked sealed boundary metadata"):
            p.persist_development_oos_record(session, calculated, allow_mismatch=True)
    finally:
        stop()
    assert writes == [] and not any("ohlcv_daily" in sql for sql, _ in statements)
