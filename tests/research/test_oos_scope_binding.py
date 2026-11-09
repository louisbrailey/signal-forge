"""Adversarial OOS scope contracts over synthetic, isolated database rows only.

Positive metrics are deliberately invented to clear ordinary quality gates;
they are not research results. A matching config alone must never authorize
metrics from another dataset, source, universe, strategy or approval evaluation.
"""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from freezegun import freeze_time
from sqlalchemy import event
from sqlalchemy.orm import Session

from signalforge.backtest.engine import EntrySignal
from signalforge.config.research import ResearchConfig
from signalforge.db.models import (
    BacktestMetric,
    BacktestRun,
    DataFeedStatus,
    DataSnapshot,
    Instrument,
    OHLCVDaily,
    Strategy,
    StrategyPromotionEvaluation,
    StrategyVersion,
)
from signalforge.domain import (
    Direction,
    FeedType,
    Horizon,
    LatencyCategory,
    QualityGate,
    StrategyStatus,
)
from signalforge.research import persistence, scan
from signalforge.research.strategies import TrendContinuation

SPEC = TrendContinuation().spec()
SYMBOLS = ["SPY", "QQQ"]
SOURCE = "synthetic_scope_source"
CREATED = datetime(2024, 1, 2, tzinfo=UTC)
SCAN_DAY = date(2024, 6, 28)
NOW = datetime(2024, 6, 28, 22, tzinfo=UTC)


@dataclass
class ScopeCase:
    cfg: ResearchConfig
    version: StrategyVersion
    snapshot: DataSnapshot
    other_snapshot: DataSnapshot
    evaluation: StrategyPromotionEvaluation
    other_evaluation: StrategyPromotionEvaluation
    metric: BacktestMetric = field(init=False)


def _evaluation(
    session: Session, version: StrategyVersion, snapshot: DataSnapshot, cfg: ResearchConfig
) -> StrategyPromotionEvaluation:
    row = StrategyPromotionEvaluation(
        strategy_version_id=version.id,
        dataset_snapshot_id=snapshot.id,
        evaluated_at=CREATED - timedelta(days=1),
        config_hash=cfg.config_hash,
        spec_json_hash=persistence.spec_json_hash(SPEC),
        universe_json=list(SYMBOLS),
        window_start=date(2017, 1, 3),
        window_end=date(2023, 12, 29),
        data_provenance_json={"sources": [SOURCE], "simulated": False},
        passed=True,
        verdict="PASSED synthetic scope fixture",
    )
    session.add(row)
    session.flush()
    return row


def _metric(
    session: Session,
    case: ScopeCase,
    *,
    snapshot: DataSnapshot | None = None,
    evaluation: StrategyPromotionEvaluation | None = None,
    created: datetime = CREATED,
) -> BacktestMetric:
    snapshot = snapshot or case.snapshot
    evaluation = evaluation or case.evaluation
    run = BacktestRun(
        strategy_version_id=case.version.id,
        config_hash=case.cfg.config_hash,
        created_at=created,
        date_start=date(2017, 1, 3),
        date_end=date(2022, 12, 30),
        params_json={
            "purpose": "development_oos",
            "dataset_snapshot": {"id": snapshot.id, "key": snapshot.key},
            "promotion_evaluation_id": evaluation.id,
            "symbols": list(SYMBOLS),
            "source": SOURCE,
            "spec_json_hash": persistence.spec_json_hash(SPEC),
            "window": {"start": "2017-01-03", "until": "2022-12-30"},
            "sealed_boundary": "2023-01-03",
            "data_provenance": {"sources": [SOURCE], "simulated": False, "bars": 1000},
            "reproduces_evaluation": {
                "symbols": True,
                "window_start": True,
                "until": True,
                "source": True,
                "config_hash": True,
            },
        },
    )
    session.add(run)
    session.flush()
    metric = BacktestMetric(
        run_id=run.id,
        phase="out_of_sample",
        segment="all",
        metrics_json={"n_trades": 200, "expectancy_r": 0.5},
        ci_json={"expectancy_r": {"low": 0.1, "high": 0.8}},
    )
    session.add(metric)
    for label in ("bull/low", "bear/high"):
        session.add(
            BacktestMetric(
                run_id=run.id,
                phase="oos_by_regime",
                segment=label,
                metrics_json={"regime_label": label, "n_trades": 50, "expectancy_r": 0.5},
            )
        )
    session.flush()
    return metric


@pytest.fixture
def scope_case(session: Session) -> ScopeCase:
    cfg = ResearchConfig()
    version = persistence.upsert_strategy_version(session, SPEC)
    version.status = StrategyStatus.PAPER_APPROVED
    session.get(Strategy, version.strategy_id).status = StrategyStatus.PAPER_APPROVED
    # Equal symbol sets, different immutable identities: universe/config equality
    # must not collapse the A/B dataset distinction.
    a = DataSnapshot(key="synthetic_scope_A", symbols_json=list(SYMBOLS))
    b = DataSnapshot(key="synthetic_scope_B", symbols_json=list(SYMBOLS))
    session.add_all([a, b])
    session.flush()
    e_a, e_b = (_evaluation(session, version, snap, cfg) for snap in (a, b))
    case = ScopeCase(cfg, version, a, b, e_a, e_b)
    case.metric = _metric(session, case)
    return case


def _context(case: ScopeCase) -> dict[str, Any]:
    return {
        "config_hash": case.cfg.config_hash,
        "dataset_snapshot_id": case.snapshot.id,
        "source": SOURCE,
        "symbols": list(SYMBOLS),
    }


def _failures(session: Session, case: ScopeCase, **context: Any) -> list[str]:
    result = persistence.oos_scope_failures(
        session, case.metric, SPEC, **(_context(case) | context)
    )
    assert isinstance(result, list) and all(isinstance(reason, str) and reason for reason in result)
    return result


def _params(session: Session, case: ScopeCase, key: str, value: Any) -> None:
    params = deepcopy(case.metric.run.params_json)
    if value is _ABSENT:
        params.pop(key, None)
    else:
        params[key] = value
    case.metric.run.params_json = params
    session.flush()


_ABSENT = object()


def test_fully_matched_scope_accepts_unchanged_numeric_evidence(session, scope_case):
    original = deepcopy((scope_case.metric.metrics_json, scope_case.metric.ci_json))
    assert _failures(session, scope_case) == []
    assert (scope_case.metric.metrics_json, scope_case.metric.ci_json) == original


def test_same_config_and_symbol_set_do_not_bind_dataset_A_metric_to_B_scan(session, scope_case):
    assert scope_case.evaluation.config_hash == scope_case.other_evaluation.config_hash
    assert scope_case.snapshot.symbols_json == scope_case.other_snapshot.symbols_json
    assert scope_case.snapshot.id != scope_case.other_snapshot.id
    assert _failures(session, scope_case, dataset_snapshot_id=scope_case.other_snapshot.id)


@pytest.mark.parametrize(
    "field,value",
    [
        ("config_hash", "different-scan-config"),
        ("config_hash", ""),
        ("source", "different-scan-source"),
        ("source", ""),
        ("source", None),
        ("symbols", ["SPY"]),
        ("symbols", ["SPY", "QQQ", "DIA"]),
        ("symbols", ["SPY", "DIA"]),
        ("symbols", []),
        ("dataset_snapshot_id", None),
        ("dataset_snapshot_id", "1"),
        ("dataset_snapshot_id", True),
    ],
)
def test_actual_scan_context_must_match_every_scope_dimension(session, scope_case, field, value):
    assert _failures(session, scope_case, **{field: value})


@pytest.mark.parametrize(
    "field,value",
    [
        ("purpose", _ABSENT),
        ("purpose", "ordinary_backtest"),
        ("dataset_snapshot", _ABSENT),
        ("dataset_snapshot", {}),
        ("dataset_snapshot", {"id": True}),
        ("dataset_snapshot", "1"),
        ("source", _ABSENT),
        ("source", "different-recorded-source"),
        ("source", []),
        ("symbols", _ABSENT),
        ("symbols", ["SPY"]),
        ("symbols", "SPY,QQQ"),
        ("spec_json_hash", _ABSENT),
        ("spec_json_hash", "different-recorded-spec"),
        ("promotion_evaluation_id", _ABSENT),
        ("promotion_evaluation_id", 999999),
        ("promotion_evaluation_id", True),
        ("promotion_evaluation_id", "1"),
        ("data_provenance", {"sources": ["different-measured-source"], "simulated": False}),
    ],
)
def test_saved_run_scope_cannot_be_missing_forged_or_coerced(session, scope_case, field, value):
    _params(session, scope_case, field, value)
    assert _failures(session, scope_case)


def test_dataset_id_in_provenance_must_match_run_approval_and_scan(session, scope_case):
    _params(
        session,
        scope_case,
        "dataset_snapshot",
        {"id": scope_case.other_snapshot.id, "key": scope_case.other_snapshot.key},
    )
    assert _failures(session, scope_case)


def test_run_config_hash_is_checked_independently_of_matching_saved_scope(session, scope_case):
    scope_case.metric.run.config_hash = "wrong-run-config"
    session.flush()
    assert _failures(session, scope_case)


@pytest.mark.parametrize(
    "field,value",
    [
        ("dataset_snapshot_id", "other"),
        ("config_hash", "wrong-evaluation-config"),
        ("spec_json_hash", "wrong-evaluation-spec"),
        ("universe_json", ["SPY"]),
        ("data_provenance_json", {"sources": ["wrong-evaluation-source"]}),
        ("passed", False),
    ],
)
def test_exact_linked_evaluation_must_pass_and_match_even_if_another_passes(
    session, scope_case, field, value
):
    _evaluation(session, scope_case.version, scope_case.snapshot, scope_case.cfg)
    setattr(
        scope_case.evaluation, field, scope_case.other_snapshot.id if value == "other" else value
    )
    session.flush()
    assert _failures(session, scope_case)


def test_link_to_a_passed_evaluation_on_another_dataset_is_not_approval(session, scope_case):
    _params(session, scope_case, "promotion_evaluation_id", scope_case.other_evaluation.id)
    assert scope_case.other_evaluation.passed is True
    assert _failures(session, scope_case)


def test_evaluation_strategy_version_cannot_be_substituted(session, scope_case):
    other = persistence.upsert_strategy_version(session, replace(SPEC, version="synthetic-old"))
    scope_case.evaluation.strategy_version_id = other.id
    session.flush()
    assert _failures(session, scope_case)


@pytest.mark.parametrize(
    "field,value", [("version", "synthetic-other-version"), ("name", "synthetic_other_strategy")]
)
def test_forged_spec_hashes_cannot_hide_actual_run_strategy_identity(
    session, scope_case, field, value
):
    different = replace(SPEC, **{field: value})
    other_hash = persistence.spec_json_hash(different)
    _params(session, scope_case, "spec_json_hash", other_hash)
    scope_case.evaluation.spec_json_hash = other_hash
    session.flush()
    assert persistence.oos_scope_failures(
        session, scope_case.metric, different, **_context(scope_case)
    )


def test_changed_live_rule_parameters_fail_without_a_version_bump(session, scope_case):
    drifted = replace(SPEC, entry_conditions=SPEC.entry_conditions + "; synthetic parameter drift")
    assert drifted.name == SPEC.name and drifted.version == SPEC.version
    assert persistence.spec_json_hash(drifted) != persistence.spec_json_hash(SPEC)
    assert persistence.oos_scope_failures(
        session, scope_case.metric, drifted, **_context(scope_case)
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("allow_mismatch", True),
        ("allow_mismatch", "false"),
        ("allow_mismatch", 0),
        ("allow_mismatch", None),
        ("mismatched_inputs", ["config_hash"]),
        ("mismatched_inputs", "source"),
        ("mismatched_inputs", None),
        ("reproduces_evaluation", _ABSENT),
        ("reproduces_evaluation", None),
        ("reproduces_evaluation", []),
    ],
)
def test_forced_unknown_and_malformed_provenance_flags_cannot_authorize_evidence(
    session, scope_case, field, value
):
    _params(session, scope_case, field, value)
    assert _failures(session, scope_case)


@pytest.mark.parametrize("flag", ["symbols", "window_start", "until", "source", "config_hash"])
@pytest.mark.parametrize("value", [False, "true", 1, None, _ABSENT])
def test_reproduction_flags_require_actual_booleans_and_complete_fields(
    session, scope_case, flag, value
):
    flags = deepcopy(scope_case.metric.run.params_json["reproduces_evaluation"])
    if value is _ABSENT:
        flags.pop(flag)
    else:
        flags[flag] = value
    _params(session, scope_case, "reproduces_evaluation", flags)
    assert _failures(session, scope_case)


def test_non_mapping_run_provenance_is_unknown_and_rejected(session, scope_case):
    scope_case.metric.run.params_json = []
    session.flush()
    assert _failures(session, scope_case)


def test_scan_symbol_order_is_not_a_different_universe(session, scope_case):
    assert _failures(session, scope_case, symbols=list(reversed(SYMBOLS))) == []


def test_clean_optional_flags_and_singleton_source_list_preserve_matching_scope(
    session, scope_case
):
    params = deepcopy(scope_case.metric.run.params_json)
    params.update(allow_mismatch=False, mismatched_inputs=[], source=[SOURCE])
    scope_case.metric.run.params_json = params
    session.flush()
    assert _failures(session, scope_case) == []


def test_recorded_order_can_differ_from_scan_when_it_matches_linked_evaluation(session, scope_case):
    order = list(reversed(SYMBOLS))
    _params(session, scope_case, "symbols", order)
    scope_case.evaluation.universe_json = order
    session.flush()
    assert _failures(session, scope_case) == []


@pytest.mark.parametrize("bad", [False, True])
def test_scope_helper_is_select_only_and_does_not_autoflush_pending_state(session, scope_case, bad):
    context = _context(scope_case)
    if bad:
        context["dataset_snapshot_id"] = scope_case.other_snapshot.id
    original = deepcopy(
        (
            scope_case.metric.run.params_json,
            scope_case.metric.metrics_json,
            scope_case.metric.ci_json,
            scope_case.version.status,
            scope_case.evaluation.passed,
        )
    )
    session.expire(scope_case.metric, ["run"])
    pending = Instrument(symbol="PENDING_SCOPE_PROBE", name="must not flush")
    session.add(pending)
    before_new, before_dirty = set(session.new), set(session.dirty)
    statements, flushes = [], []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    def on_flush(*args):
        flushes.append(True)

    connection = session.connection()
    event.listen(connection, "before_cursor_execute", capture)
    event.listen(session, "before_flush", on_flush)
    try:
        result = persistence.oos_scope_failures(session, scope_case.metric, SPEC, **context)
    finally:
        event.remove(connection, "before_cursor_execute", capture)
        event.remove(session, "before_flush", on_flush)
    assert bool(result) is bad
    assert flushes == [] and pending.id is None
    assert set(session.new) == before_new and set(session.dirty) == before_dirty
    assert all(s.lstrip().upper().startswith("SELECT") for s in statements)
    # A linked evaluation's sealed_test_id FK is ordinary metadata; only
    # reading the sealed-test table itself (or prices/trades) is forbidden here.
    forbidden = re.compile(
        r"\b(?:FROM|JOIN)\s+(?:ohlcv_\w+|backtest_trade|strategy_sealed_test)\b", re.IGNORECASE
    )
    assert not any(forbidden.search(s.replace('"', "")) for s in statements)
    with session.no_autoflush:
        current = (
            scope_case.metric.run.params_json,
            scope_case.metric.metrics_json,
            scope_case.metric.ci_json,
            scope_case.version.status,
            scope_case.evaluation.passed,
        )
    assert current == original
    assert pending.id is None and set(session.new) == before_new


@pytest.mark.parametrize("mismatch", ["dataset", "config", "source"])
def test_latest_wrong_scope_never_falls_back_to_older_valid_metric(session, scope_case, mismatch):
    older = scope_case.metric
    kwargs = {"snapshot": scope_case.other_snapshot, "evaluation": scope_case.other_evaluation}
    if mismatch != "dataset":
        kwargs = {}
    latest = _metric(session, scope_case, created=CREATED + timedelta(days=1), **kwargs)
    if mismatch == "config":
        latest.run.config_hash = "newest-other-config"
    if mismatch == "source":
        params = deepcopy(latest.run.params_json)
        params["source"] = "newest-other-source"
        latest.run.params_json = params
    session.flush()
    selected = persistence.latest_oos_metric(session, SPEC)
    assert selected.id == latest.id != older.id
    assert persistence.oos_scope_failures(session, selected, SPEC, **_context(scope_case))
    assert persistence.latest_oos_metric(session, SPEC).id == latest.id


def _scan_bars(session: Session) -> None:
    for symbol in SYMBOLS:
        instrument = Instrument(symbol=symbol, instrument_type="etf")
        session.add(instrument)
        session.flush()
        for i in range(300):
            session.add(
                OHLCVDaily(
                    instrument_id=instrument.id,
                    session_date=SCAN_DAY - timedelta(days=299 - i),
                    open=100,
                    high=101,
                    low=99,
                    close=100,
                    volume=10_000_000,
                    source=SOURCE,
                    latency_category=LatencyCategory.END_OF_DAY,
                    ingested_at=NOW - timedelta(minutes=1),
                    is_simulated=True,
                )
            )
    session.add(
        DataFeedStatus(
            provider="fixture",
            feed_type=FeedType.BAR_DAILY,
            latency_category=LatencyCategory.END_OF_DAY,
            last_success_at=NOW - timedelta(minutes=1),
            updated_at=NOW,
        )
    )
    session.flush()


def _actual_scan(session: Session, case: ScopeCase, monkeypatch):
    strategy = TrendContinuation()
    monkeypatch.setattr(
        strategy,
        "evaluate",
        lambda series, t, ctx: EntrySignal(
            Direction.LONG,
            stop_price=95,
            time_stop_bars=10,
            target_price=110,
            reason="synthetic scope signal",
        ),
    )
    monkeypatch.setattr(scan, "_strategies_for", lambda horizon: [strategy])
    with freeze_time(NOW):
        return scan.run_scan(
            session,
            Horizon.SHORT_SWING,
            research=case.cfg,
            as_of=SCAN_DAY,
            source=SOURCE,
            symbols=list(SYMBOLS),
        )


@pytest.mark.parametrize("matched", [True, False])
def test_actual_scan_candidate_uses_resolved_dataset_not_just_matching_config(
    session, scope_case, monkeypatch, matched
):
    _scan_bars(session)
    scope_case.snapshot.reusable_by_new_evaluations = matched
    scope_case.other_snapshot.reusable_by_new_evaluations = not matched
    session.flush()
    result = _actual_scan(session, scope_case, monkeypatch)
    wanted = scope_case.snapshot if matched else scope_case.other_snapshot
    assert result.dataset_snapshot_id == wanted.id
    assert result.config_hash == scope_case.metric.run.config_hash == scope_case.cfg.config_hash
    assert result.universe == SYMBOLS and result.source == SOURCE
    assert len(result.candidates) == len(SYMBOLS) and result.excluded_count == 0
    for candidate in result.candidates:
        assert candidate.quality_gate_status is (
            QualityGate.PASSED if matched else QualityGate.NO_TRADE
        )
        assert bool(candidate.failed_gates) is not matched
        if not matched:
            assert candidate.probability_calibrated is None
            assert candidate.rank_in_horizon is None


@pytest.mark.parametrize("mismatch", ["dataset", "config", "source"])
def test_actual_scan_rejects_latest_wrong_scope_even_when_older_metric_matches_scan(
    session, scope_case, monkeypatch, mismatch
):
    _scan_bars(session)
    scope_case.snapshot.reusable_by_new_evaluations = False
    scope_case.other_snapshot.reusable_by_new_evaluations = True
    older = _metric(
        session,
        scope_case,
        snapshot=scope_case.other_snapshot,
        evaluation=scope_case.other_evaluation,
        created=CREATED - timedelta(hours=1),
    )
    if mismatch != "dataset":
        # Isolate a config/source mismatch in an otherwise fully matched B run.
        params = deepcopy(scope_case.metric.run.params_json)
        params["dataset_snapshot"] = {
            "id": scope_case.other_snapshot.id,
            "key": scope_case.other_snapshot.key,
        }
        params["promotion_evaluation_id"] = scope_case.other_evaluation.id
        if mismatch == "config":
            scope_case.metric.run.config_hash = "newest-wrong-config"
        else:
            params["source"] = "newest-wrong-source"
        scope_case.metric.run.params_json = params
    session.flush()
    assert persistence.latest_oos_metric(session, SPEC).id == scope_case.metric.id != older.id
    result = _actual_scan(session, scope_case, monkeypatch)
    assert result.dataset_snapshot_id == scope_case.other_snapshot.id
    assert len(result.candidates) == len(SYMBOLS)
    assert all(c.quality_gate_status is QualityGate.NO_TRADE for c in result.candidates)
    assert all(c.probability_calibrated is None and c.failed_gates for c in result.candidates)
    assert persistence.latest_oos_metric(session, SPEC).id == scope_case.metric.id
