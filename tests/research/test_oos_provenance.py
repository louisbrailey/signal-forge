"""Explicit mismatch provenance blocks actual candidate quality, not storage."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from signalforge.backtest.engine import EntrySignal
from signalforge.config.research import ResearchConfig
from signalforge.db.models import BacktestMetric, BacktestRun, Instrument, Strategy
from signalforge.domain import Direction, Horizon, QualityGate
from signalforge.research.evidence import evidence_inventory, metric_evidence
from signalforge.research.persistence import latest_oos_metric, upsert_strategy_version
from signalforge.research.scan import _build_draft
from signalforge.research.strategies import TrendContinuation

SPEC = TrendContinuation().spec()
STAMP = datetime(2026, 1, 1, tzinfo=UTC)


def _record(
    session: Session, params: dict[str, Any], *, spec: Any = SPEC, at: datetime = STAMP
) -> BacktestMetric:
    version = upsert_strategy_version(session, spec)
    run = BacktestRun(
        strategy_version_id=version.id,
        params_json=deepcopy(params),
        date_start=date(2020, 1, 1),
        date_end=date(2024, 1, 1),
        config_hash="synthetic-regression",
        created_at=at,
    )
    session.add(run)
    session.flush()
    metric = BacktestMetric(
        run_id=run.id,
        segment="all",
        phase="out_of_sample",
        metrics_json={"n_trades": 200, "expectancy_r": 0.5},
        ci_json={"expectancy_r": {"low": 0.1, "high": 0.8}},
    )
    session.add(metric)
    for regime in ("bull/low", "bear/high"):
        session.add(
            BacktestMetric(
                run_id=run.id,
                segment=regime,
                phase="oos_by_regime",
                metrics_json={"regime_label": regime, "n_trades": 50, "expectancy_r": 0.5},
            )
        )
    session.flush()
    return metric


def _draft(session: Session):
    instrument = session.scalar(select(Instrument).where(Instrument.symbol == "SPY"))
    if instrument is None:
        instrument = Instrument(symbol="SPY")
        session.add(instrument)
        session.flush()
    version = upsert_strategy_version(session, SPEC)
    return _build_draft(
        session=session,
        sym="SPY",
        inst=instrument,
        version_id=version.id,
        spec=SPEC,
        horizon=Horizon.SHORT_SWING,
        sig=EntrySignal(Direction.LONG, stop_price=95, time_stop_bars=10, target_price=110),
        close=100,
        atr_val=2,
        addv=1e9,
        earnings=[],
        fresh={},
        cfg=ResearchConfig(),
        equity=10_000,
    )


@pytest.mark.parametrize(
    "params",
    [
        {"allow_mismatch": True},
        {"mismatched_inputs": ["until"]},
        {"allow_mismatch": False, "mismatched_inputs": ["config_hash"]},
        {
            "allow_mismatch": True,
            "mismatched_inputs": ["config_hash", "until"],
            "reproduces_evaluation": {"config_hash": False, "until": False, "source": True},
        },
        {"reproduces_evaluation": {"config_hash": False}},
        {"allow_mismatch": "true"},
        {"mismatched_inputs": "until"},
    ],
)
def test_positive_numeric_metrics_cannot_qualify_forced_or_mismatched_inputs(
    session: Session, params: dict[str, Any]
) -> None:
    metric = _record(session, params)
    original = deepcopy((metric.run.params_json, metric.metrics_json, metric.ci_json))
    draft = _draft(session)
    assert draft.quality_gate_status is QualityGate.NO_TRADE
    assert len(draft.failed_gates) == 1 and "OOS provenance mismatch" in draft.failed_gates[0]
    assert draft.probability_calibrated is None
    assert (metric.run.params_json, metric.metrics_json, metric.ci_json) == original
    display = metric_evidence(metric, SPEC)
    assert display["state"] == "ambiguous_provenance"
    assert display["expectancy_r"] == 0.5 and display["ci_low"] == 0.1
    assert any("OOS provenance mismatch" in warning for warning in display["warnings"])


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"allow_mismatch": False, "mismatched_inputs": []},
        {"reproduces_evaluation": {"config_hash": True, "until": True, "source": True}},
    ],
)
def test_unforced_passing_metrics_and_legacy_unknown_keep_their_existing_behavior(
    session: Session, params: dict[str, Any]
) -> None:
    metric = _record(session, params)
    draft = _draft(session)
    assert draft.quality_gate_status is QualityGate.PASSED and draft.failed_gates == []
    display = metric_evidence(metric, SPEC)
    assert display["state"] == "positive_point_estimate"
    assert display["data_kind"] == "unknown" and display["source"] == "unknown"
    assert any("provenance is unknown" in warning for warning in display["warnings"])


def test_latest_current_version_stays_selected_without_fallback_or_status_changes(
    session: Session,
) -> None:
    older = _record(session, {"allow_mismatch": False})
    forced = _record(session, {"allow_mismatch": True}, at=STAMP + timedelta(days=1))
    _record(session, {}, spec=replace(SPEC, version="superseded"), at=STAMP + timedelta(days=2))
    assert latest_oos_metric(session, SPEC).id == forced.id != older.id
    version = upsert_strategy_version(session, SPEC)
    strategy = session.get(Strategy, version.strategy_id)
    statuses = (version.status, strategy.status)
    assert _draft(session).quality_gate_status is QualityGate.NO_TRADE
    session.flush()
    statements: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    connection = session.connection()
    event.listen(connection, "before_cursor_execute", capture)
    try:
        inventory = evidence_inventory(session)
    finally:
        event.remove(connection, "before_cursor_execute", capture)
    row = next(r for r in inventory["current"] if r["name"] == SPEC.name)
    assert row["run_id"] == forced.run_id and row["state"] == "ambiguous_provenance"
    assert inventory["counts"]["ambiguous_provenance"] == 1
    assert (version.status, strategy.status) == statuses
    assert all(s.lstrip().upper().startswith("SELECT") for s in statements)
    assert not any("sealed" in s.lower() for s in statements)
