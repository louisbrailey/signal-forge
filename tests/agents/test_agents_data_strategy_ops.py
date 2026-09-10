"""Behavioural tests for the three bounded read-only research agents:
DataQualityAgent, StrategyValidationAgent, OperationsAgent.

For every agent:
  (a) an empty, migrated DB yields status == "ok" with non-empty
      missing_data, and never raises;
  (b) with a few seeded rows, the deterministic summary mentions the
      seeded facts;
  (c) running the agent writes exactly one AgentReport row and one
      AuditLog(action="agent.run") row, and never touches trading-state
      tables (candidate, paper_trade, app_setting, strategy, alert_log);
  (d) the summary ends with the research-only notice;
  (e) a collect() failure (monkeypatched) yields status == "failed", never
      raises, and writes an AuditLog(action="agent.failed") row.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge import RESEARCH_ONLY_NOTICE
from signalforge.agents.base import ResearchAgent
from signalforge.agents.data_quality import DataQualityAgent
from signalforge.agents.operations import OperationsAgent
from signalforge.agents.strategy_validation import StrategyValidationAgent
from signalforge.db.models import (
    AgentReport,
    AlertLog,
    AppSetting,
    AuditLog,
    Candidate,
    DataFeedStatus,
    DataSnapshot,
    JobRun,
    PaperTrade,
    Strategy,
    StrategyPromotionEvaluation,
    StrategyVersion,
)
from signalforge.domain import FeedType, Horizon, LatencyCategory, StrategyStatus

_AGENT_CLASSES: tuple[type[ResearchAgent], ...] = (
    DataQualityAgent,
    StrategyValidationAgent,
    OperationsAgent,
)

_TRADING_STATE_MODELS = {
    "candidate": Candidate,
    "paper_trade": PaperTrade,
    "app_setting": AppSetting,
    "strategy": Strategy,
    "alert_log": AlertLog,
}


def _trading_state_counts(session: Session) -> dict[str, int]:
    return {
        name: int(session.scalar(select(func.count()).select_from(model)) or 0)
        for name, model in _TRADING_STATE_MODELS.items()
    }


def _count(session: Session, model: type, **where: object) -> int:
    stmt = select(func.count()).select_from(model)
    for k, v in where.items():
        stmt = stmt.where(getattr(model, k) == v)
    return int(session.scalar(stmt) or 0)


# --------------------------------------------------------------------------- #
# (a) empty DB -> status == "ok", non-empty missing_data, never raises
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("agent_cls", _AGENT_CLASSES)
def test_empty_db_yields_ok_with_missing_data(
    session: Session, agent_cls: type[ResearchAgent]
) -> None:
    result = agent_cls().run(session)
    assert result.status == "ok"
    assert result.missing_data, "missing_data must be non-empty on an empty DB"
    assert result.error == ""


# --------------------------------------------------------------------------- #
# (b) seeded facts show up in the deterministic summary
# --------------------------------------------------------------------------- #
def test_data_quality_summary_mentions_seeded_stale_feed(session: Session) -> None:
    old = datetime.now(UTC) - timedelta(days=10)
    session.add(
        DataFeedStatus(
            provider="acme_data",
            feed_type=FeedType.BAR_DAILY,
            latency_category=LatencyCategory.END_OF_DAY,
            last_success_at=old,
            updated_at=old,
        )
    )
    session.flush()

    result = DataQualityAgent().run(session)

    assert result.status == "ok"
    assert "acme_data" in result.summary
    assert any("acme_data" in m for m in result.missing_data) or "acme_data" in str(
        result.evidence.get("stale_feeds")
    )


def test_strategy_validation_summary_mentions_paper_approved_strategy(session: Session) -> None:
    strat = Strategy(
        name="alpha_breakout",
        horizon=Horizon.SHORT_SWING,
        status=StrategyStatus.PAPER_APPROVED,
    )
    session.add(strat)
    session.flush()

    ver = StrategyVersion(
        strategy_id=strat.id,
        version="v1",
        git_sha="deadbeef",
        spec_json={"lookback": 20},
        status=StrategyStatus.PAPER_APPROVED,
    )
    session.add(ver)
    session.flush()

    snap = DataSnapshot(key="universe_25_baseline", symbols_json=["AAA", "BBB"])
    session.add(snap)
    session.flush()

    session.add(
        StrategyPromotionEvaluation(
            strategy_version_id=ver.id,
            dataset_snapshot_id=snap.id,
            evaluated_at=datetime.now(UTC),
            config_hash="cfg-hash-123",
            spec_json_hash="spec-hash-456",
            window_start=date(2026, 1, 1),
            window_end=date(2026, 6, 1),
            data_provenance_json={"sources": ["massive"]},
            universe_json=["AAA", "BBB"],
            gates_json=[{"number": 1, "name": "walkforward_folds", "passed": True, "detail": "ok"}],
            passed=True,
            verdict="approved",
        )
    )
    session.flush()

    result = StrategyValidationAgent().run(session)

    assert result.status == "ok"
    assert "alpha_breakout" in result.summary


def test_operations_summary_mentions_failed_job_run(session: Session) -> None:
    started = datetime.now(UTC) - timedelta(hours=1)
    session.add(
        JobRun(
            name="daily_eod_update",
            started_at=started,
            finished_at=started + timedelta(minutes=5),
            status="failed",
            detail="provider timeout",
        )
    )
    session.flush()

    result = OperationsAgent().run(session)

    assert result.status == "ok"
    assert "daily_eod_update" in result.summary


# --------------------------------------------------------------------------- #
# (c) exactly one AgentReport + one AuditLog(agent.run); trading state untouched
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("agent_cls", _AGENT_CLASSES)
def test_run_writes_exactly_one_report_and_audit_row_and_touches_no_trading_state(
    session: Session, agent_cls: type[ResearchAgent]
) -> None:
    before_state = _trading_state_counts(session)
    before_reports = _count(session, AgentReport)
    before_audit_run = _count(session, AuditLog, action="agent.run")

    result = agent_cls().run(session)

    assert result.status == "ok"
    assert _trading_state_counts(session) == before_state
    assert _count(session, AgentReport) - before_reports == 1
    assert _count(session, AuditLog, action="agent.run") - before_audit_run == 1

    report = session.scalar(select(AgentReport).where(AgentReport.id == result.report_id))
    assert report is not None
    assert report.agent == agent_cls.name
    assert report.status == "ok"


# --------------------------------------------------------------------------- #
# (d) summary ends with the research-only notice
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("agent_cls", _AGENT_CLASSES)
def test_summary_ends_with_research_only_notice(
    session: Session, agent_cls: type[ResearchAgent]
) -> None:
    result = agent_cls().run(session)
    assert result.summary.endswith(RESEARCH_ONLY_NOTICE)


# --------------------------------------------------------------------------- #
# (e) collect() failure -> status == "failed", never raises, audited
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("agent_cls", _AGENT_CLASSES)
def test_collect_failure_yields_failed_status_never_raises_and_is_audited(
    session: Session, agent_cls: type[ResearchAgent], monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(self: ResearchAgent, session: Session) -> dict[str, object]:
        raise RuntimeError("synthetic collect failure")

    monkeypatch.setattr(agent_cls, "collect", _boom)

    result = agent_cls().run(session)  # must not raise

    assert result.status == "failed"
    assert "synthetic collect failure" in result.error

    row = session.scalar(
        select(AuditLog)
        .where(AuditLog.action == "agent.failed", AuditLog.entity == agent_cls.name)
        .order_by(AuditLog.id.desc())
    )
    assert row is not None
