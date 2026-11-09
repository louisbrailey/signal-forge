"""Saved evidence stays traceable and missing/obsolete tests cannot masquerade as losses."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from scripts.strategy_evidence_audit import audit
from sqlalchemy import event
from sqlalchemy.orm import Session

from signalforge.backtest.metrics import compute_metrics
from signalforge.data.series import PriceSeries
from signalforge.db.models import BacktestMetric, BacktestRun, Instrument, OHLCVDaily, OHLCVIntraday
from signalforge.domain import LatencyCategory
from signalforge.research.backtest_runner import (
    DataProvenance,
    StrategyBacktestResult,
    _data_provenance,
)
from signalforge.research.evidence import evidence_inventory, metric_evidence
from signalforge.research.persistence import (
    latest_oos_metric,
    persist_backtest_result,
    spec_json_hash,
    upsert_strategy_version,
)
from signalforge.research.strategies import TrendContinuation

DAY = date(2024, 6, 3)
SPEC = TrendContinuation().spec()


def _metric(session, *, n=20, expectancy=-0.2, params=None, ci=None):
    version = upsert_strategy_version(session, SPEC)
    run = BacktestRun(
        strategy_version_id=version.id,
        params_json=params or {},
        date_start=DAY,
        date_end=DAY,
        config_hash="test",
    )
    session.add(run)
    session.flush()
    metric = BacktestMetric(
        run_id=run.id,
        segment="all",
        phase="out_of_sample",
        metrics_json={"n_trades": n, "expectancy_r": expectancy},
        ci_json=ci or {},
    )
    session.add(metric)
    session.flush()
    return metric


@pytest.mark.parametrize(
    ("n", "expectancy", "state"),
    [
        (20, -0.2, "negative_point_estimate"),
        (20, 0.2, "positive_point_estimate"),
        (20, 0, "zero_point_estimate"),
        (0, 0, "no_trades"),
        (20, None, "invalid_metrics"),
        (None, 0.2, "invalid_metrics"),
        (1.5, 0.2, "invalid_metrics"),
        (True, 0.2, "invalid_metrics"),
    ],
)
def test_distinct_evidence_states(session, n, expectancy, state):
    metric = _metric(session, n=n, expectancy=expectancy)
    assert metric_evidence(metric, SPEC)["state"] == state


def test_missing_nonfinite_and_legacy_evidence_are_never_called_real(session):
    assert metric_evidence(None, SPEC)["state"] == "unrecorded"
    metric = _metric(session)
    for value in (float("nan"), float("inf"), float("-inf")):
        metric.metrics_json = {"n_trades": 20, "expectancy_r": value}
        row = metric_evidence(metric, SPEC)
        assert row["state"] == "invalid_metrics" and row["expectancy_r"] is None
    assert row["data_kind"] == "unknown" and row["source"] == "unknown"
    assert row["ci_low"] is None


def test_real_simulated_and_stale_spec_provenance(session):
    params = {
        "data_provenance": {"sources": ["massive"], "bars": 1000, "simulated": False},
        "spec_json_hash": spec_json_hash(SPEC),
    }
    metric = _metric(
        session, expectancy=0.2, params=params, ci={"expectancy_r": {"low": -0.1, "high": 0.5}}
    )
    row = metric_evidence(metric, SPEC)
    assert row["data_kind"] == "real_recorded" and row["source"] == "massive"
    assert any("includes zero" in w for w in row["warnings"])
    assert row["ci_low"] == -0.1
    assert not any("spec hash" in w for w in row["warnings"])
    params["data_provenance"]["simulated"] = True
    metric.run.params_json = params
    row = metric_evidence(metric, replace(SPEC, stop_logic="changed rule"))
    assert row["data_kind"] == "simulated"
    assert any("SIMULATED" in w for w in row["warnings"])
    assert any("differs" in w for w in row["warnings"])


def test_inventory_separates_current_superseded_and_other_families_without_writes(session):
    _metric(session)
    upsert_strategy_version(session, replace(SPEC, version="old-version"))
    upsert_strategy_version(session, replace(SPEC, name="another-family"))
    session.flush()
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    connection = session.connection()
    event.listen(connection, "before_cursor_execute", capture)
    try:
        inventory = evidence_inventory(session)
    finally:
        event.remove(connection, "before_cursor_execute", capture)
    assert inventory["registered_version_count"] == 3
    assert len(inventory["superseded"]) == len(inventory["unlisted"]) == 1
    assert inventory["counts"]["negative_point_estimate"] == 1
    assert inventory["counts"]["unrecorded"] == inventory["current_strategy_count"] - 1
    assert all(s.lstrip().upper().startswith("SELECT") for s in statements)
    assert not any("sealed" in s.lower() or "kronos" in s.lower() for s in statements)


def test_daily_provenance_ignores_sources_outside_the_requested_window(session: Session):
    instrument = Instrument(symbol="SPY")
    session.add(instrument)
    session.flush()
    for day, source, simulated in (
        (date(2023, 1, 3), "fixture", True),
        (DAY, "massive", False),
        (date(2025, 1, 3), "future_source", False),
    ):
        session.add(
            OHLCVDaily(
                instrument_id=instrument.id,
                session_date=day,
                open=100,
                high=101,
                low=99,
                close=100,
                volume=1e6,
                source=source,
                is_simulated=simulated,
                latency_category=LatencyCategory.END_OF_DAY,
                ingested_at=datetime.now(UTC),
            )
        )
    session.flush()
    data = _data_provenance(session, ["SPY"], DAY, DAY, intraday=False)
    assert data.sources == ("massive",) and data.bars == 1 and data.simulated is False
    assert data.first == data.last == DAY
    assert _data_provenance(session, [" spy "], DAY, DAY, intraday=False) == data
    empty = _data_provenance(session, ["SPY"], DAY, DAY, intraday=False, source="fixture")
    assert empty.bars == 0 and empty.sources == ()


def test_intraday_provenance_matches_the_loaded_interval_and_session(session: Session):
    instrument = Instrument(symbol="SPY")
    session.add(instrument)
    session.flush()
    for bar_size, trading_session, source in (
        ("15m", "rth", "massive"),
        ("5m", "rth", "fixture"),
        ("15m", "pre", "pre_source"),
    ):
        session.add(
            OHLCVIntraday(
                instrument_id=instrument.id,
                bar_start=datetime(2024, 6, 3, 14, tzinfo=UTC),
                bar_size=bar_size,
                session=trading_session,
                open=100,
                high=101,
                low=99,
                close=100,
                volume=1000,
                source=source,
                is_simulated=source == "fixture",
                latency_category=LatencyCategory.DELAYED,
                ingested_at=datetime.now(UTC),
            )
        )
    session.flush()
    data = _data_provenance(session, ["SPY"], DAY, date(2024, 6, 4), intraday=True)
    series = PriceSeries.load_intraday(
        session,
        "SPY",
        datetime(2024, 6, 3, tzinfo=UTC),
        datetime(2024, 6, 4, tzinfo=UTC),
        bar_size="15m",
    )
    assert data.bars == len(series) == 1
    assert data.sources == ("massive",) and data.simulated is False


def test_persistence_keeps_measured_provenance_and_spec_hash_over_caller_claims(session):
    metrics = compute_metrics([])
    result = StrategyBacktestResult(
        spec=SPEC,
        symbols=["SPY"],
        start=DAY,
        end=DAY,
        n_trades=0,
        in_sample=metrics,
        out_of_sample=metrics,
        oos_ci={},
        data=DataProvenance(("fixture",), True, 10, DAY, DAY),
        costs={"slippage_bps": 3.0},
    )
    version = upsert_strategy_version(session, SPEC)
    run = persist_backtest_result(
        session,
        version,
        result,
        provenance={
            "purpose": "test",
            "data_provenance": {"simulated": False},
            "spec_json_hash": "wrong",
        },
    )
    session.flush()
    session.expire_all()
    saved = session.get(BacktestRun, run.id)
    assert saved.params_json["data_provenance"] == {
        "schema_version": 1,
        "sources": ["fixture"],
        "simulated": True,
        "bars": 10,
        "first": DAY.isoformat(),
        "last": DAY.isoformat(),
    }
    assert saved.params_json["spec_json_hash"] == spec_json_hash(SPEC)
    assert saved.params_json["purpose"] == "test"
    row = metric_evidence(latest_oos_metric(session, SPEC), SPEC)
    assert row["data_kind"] == "simulated" and row["state"] == "no_trades"


def test_result_cannot_be_recorded_under_another_strategy_or_version(session):
    metrics = compute_metrics([])
    result = StrategyBacktestResult(
        spec=SPEC,
        symbols=["SPY"],
        start=DAY,
        end=DAY,
        n_trades=0,
        in_sample=metrics,
        out_of_sample=metrics,
        oos_ci={},
    )
    for wrong in (replace(SPEC, name="wrong-strategy"), replace(SPEC, version="wrong-version")):
        version = upsert_strategy_version(session, wrong)
        with pytest.raises(ValueError, match="does not match"):
            persist_backtest_result(session, version, result)


def test_cli_inventory_never_creates_a_missing_database(tmp_path):
    missing = tmp_path / "missing.sqlite"
    with pytest.raises(ValueError, match="existing SQLite"):
        audit(missing)
    assert not missing.exists()


def test_cli_inventory_reads_an_existing_database_without_mutating_it(session, tmp_path):
    _metric(session)
    session.commit()
    database = Path(session.get_bind().url.database)
    copied = tmp_path / "database with spaces.sqlite"
    with sqlite3.connect(database) as source, sqlite3.connect(copied) as destination:
        source.backup(destination)
    before = hashlib.sha256(copied.read_bytes()).hexdigest()
    report = audit(copied)
    assert report["counts"]["negative_point_estimate"] == 1
    assert report["registered_version_count"] == 1
    assert hashlib.sha256(copied.read_bytes()).hexdigest() == before
