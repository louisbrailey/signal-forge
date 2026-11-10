"""Explicit metadata pins and CURRENT writer TOCTOU; synthetic data/computation."""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from signalforge.db.models import DataSnapshot, Strategy, StrategyPromotionEvaluation
from signalforge.domain import StrategyStatus
from signalforge.research import promotion as p
from signalforge.settings_store import set_setting
from tests.research.test_development_calendar_cutoff import (
    FRIDAY,
    START,
    capture_sql,
    record,
)
from tests.research.test_development_calendar_cutoff import (
    setup_case as setup_case,
)


def approved(session, case):
    case.version.status = StrategyStatus.PAPER_APPROVED
    session.get(Strategy, case.version.strategy_id).status = StrategyStatus.PAPER_APPROVED
    session.commit()


def newer_evaluation(session, case, *, passed=True):
    e = case.evaluation
    newer = StrategyPromotionEvaluation(
        strategy_version_id=e.strategy_version_id,
        dataset_snapshot_id=e.dataset_snapshot_id,
        evaluated_at=e.evaluated_at + timedelta(days=1),
        config_hash=e.config_hash,
        spec_json_hash=e.spec_json_hash,
        universe_json=list(e.universe_json),
        window_start=e.window_start,
        window_end=e.window_end,
        data_provenance_json=dict(e.data_provenance_json),
        gates_json=[],
        passed=passed,
        sealed_test_id=e.sealed_test_id,
    )
    session.add(newer)
    session.commit()
    return newer


def test_none_preserves_existing_passing_selector_for_historical_api(session, setup_case):
    case = setup_case()
    newer_evaluation(session, case, passed=False)
    rec = record(session, case, evaluation_id=None)
    assert rec.evaluation_id == case.evaluation.id
    assert rec.provenance["evaluation_selection"]["mode"] == "historical_research"


def test_explicit_approved_current_identity_succeeds_without_changing_order(session, setup_case):
    case = setup_case()
    approved(session, case)
    rec = record(session, case, evaluation_id=case.evaluation.id, require_current_scope=True)
    assert rec.evaluation_id == case.evaluation.id and all(rec.reproduces_evaluation.values())
    assert rec.result.symbols == case.evaluation.universe_json
    assert rec.provenance["evaluation_selection"]["mode"] == "current_scope"


@pytest.mark.parametrize(
    "damage",
    [
        "wrong_id",
        "bool_id",
        "unapproved_status",
        "failed_evaluation",
        "wrong_config",
        "wrong_source",
        "stale_id",
        "wrong_version",
        "wrong_snapshot",
        "wrong_spec",
        "wrong_window",
    ],
)
def test_invalid_explicit_identity_refuses_before_bars(session, setup_case, damage):
    case = setup_case()
    approved(session, case)
    requested = case.evaluation.id
    cfg = case.cfg
    source = "massive"
    if damage == "wrong_id":
        requested = 987654
    elif damage == "bool_id":
        requested = True
    elif damage == "unapproved_status":
        case.version.status = StrategyStatus.EXPERIMENTAL
        session.commit()
    elif damage == "failed_evaluation":
        case.evaluation.passed = False
        session.commit()
    elif damage == "wrong_config":
        cfg = cfg.model_copy(update={"slippage_bps": cfg.slippage_bps + 1})
    elif damage == "wrong_source":
        source = "fixture"
    elif damage == "stale_id":
        newer_evaluation(session, case)
    elif damage == "wrong_version":
        case.evaluation.strategy_version_id = case.other.id
        session.commit()
    elif damage == "wrong_snapshot":
        other = DataSnapshot(key="other-explicit-snapshot", symbols_json=["SPY", "AAPL"])
        session.add(other)
        session.flush()
        case.evaluation.dataset_snapshot_id = other.id
        session.commit()
    elif damage == "wrong_spec":
        case.evaluation.spec_json_hash = "different-spec"
        session.commit()
    elif damage == "wrong_window":
        case.evaluation.window_start = START + timedelta(days=1)
        session.commit()
    statements, stop = capture_sql(session)
    try:
        with pytest.raises(ValueError):
            p.record_development_oos_backtest(
                session,
                case.strategy,
                dataset_snapshot_id=case.snapshot.id,
                since=START,
                until=FRIDAY,
                source=source,
                config=cfg,
                persist=False,
                evaluation_id=requested,
                require_current_scope=True,
            )
    finally:
        stop()
    assert case.calls == [] and not any("ohlcv_daily" in sql for sql, _ in statements)


@pytest.mark.parametrize("change", ["config", "approval", "status", "parameters"])
def test_current_writer_rechecks_live_scope_after_calculation(
    session, setup_case, monkeypatch, change
):
    case = setup_case()
    approved(session, case)
    rec = record(session, case, evaluation_id=case.evaluation.id, require_current_scope=True)
    if change == "config":
        set_setting(session, "research_overrides", {"slippage_bps": case.cfg.slippage_bps + 1})
        session.commit()
    elif change == "approval":
        newer_evaluation(session, case)
    elif change == "status":
        case.version.status = StrategyStatus.EXPERIMENTAL
        session.commit()
    else:
        from signalforge.research import strategies

        changed = replace(case.strategy.spec(), stop_logic="changed after calculation")
        monkeypatch.setattr(
            strategies, "default_strategies", lambda: [SimpleNamespace(spec=lambda: changed)]
        )
    writes = []
    monkeypatch.setattr(p, "persist_backtest_result", lambda *a, **k: writes.append(True))
    with pytest.raises(ValueError):
        p.persist_development_oos_record(
            session, rec, require_current_scope=True, allow_mismatch=True, allow_duplicate=True
        )
    assert writes == []


def test_current_writer_accepts_exact_unchanged_identity(session, setup_case, monkeypatch):
    case = setup_case()
    approved(session, case)
    rec = record(session, case, evaluation_id=case.evaluation.id, require_current_scope=True)
    writes = []

    def writer(*args, **kwargs):
        writes.append(kwargs["provenance"])
        return SimpleNamespace(id=77)

    monkeypatch.setattr(p, "persist_backtest_result", writer)
    monkeypatch.setattr(p.audit, "record", lambda *a, **k: None)
    saved = p.persist_development_oos_record(session, rec, require_current_scope=True)
    assert saved.backtest_run_id == 77 and len(writes) == 1
    assert writes[0]["promotion_evaluation_id"] == case.evaluation.id
