"""Tests for the four bounded research agents: MarketRegimeAgent,
NewsResearchAgent, PortfolioRiskAgent, JournalReviewAgent.

For each agent: (a) an empty DB never raises and reports ``status="ok"`` with
non-empty ``missing_data``; (b) seeded data shows up verbatim in the
deterministic summary; (c) exactly one ``AgentReport`` + one
``AuditLog(action="agent.run")`` are written and no trading-state table is
touched; (d) the summary ends with the research-only notice; (e) a fake LLM
narrative is grounding-checked — a fabricated number is rejected, a clean
restatement is stored under the narrative label.
"""

from __future__ import annotations

import types
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import signalforge.llm.client as llm_client_mod
from signalforge.agents.base import NARRATIVE_LABEL, AgentReportResult
from signalforge.agents.journal_review import JournalReviewAgent
from signalforge.agents.news_research import NewsResearchAgent
from signalforge.agents.portfolio_risk import PortfolioRiskAgent
from signalforge.agents.regime import MarketRegimeAgent
from signalforge.db.models import (
    AgentReport,
    AlertLog,
    AppSetting,
    AuditLog,
    Candidate,
    EntitlementCheck,
    Instrument,
    JournalEntry,
    NewsItem,
    PaperAccount,
    PaperPosition,
    PaperTrade,
    ScanRun,
    Strategy,
    StrategyVersion,
)
from signalforge.domain import Direction, Horizon, PaperDecision, PositionSide, QualityGate
from signalforge.llm.client import LlmResult
from signalforge.settings_store import set_setting

RESEARCH_ONLY = "Research signal only — no order was placed."

_STATE_TABLES = (Candidate, PaperTrade, AppSetting, Strategy, AlertLog)


def _state_counts(session: Session) -> dict[str, int]:
    return {
        m.__tablename__: int(session.scalar(select(func.count()).select_from(m)) or 0)
        for m in _STATE_TABLES
    }


def _report_audit_counts(session: Session) -> tuple[int, int]:
    n_reports = int(session.scalar(select(func.count()).select_from(AgentReport)) or 0)
    n_audit = int(
        session.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "agent.run")
        )
        or 0
    )
    return n_reports, n_audit


def _assert_single_report_no_side_effects(session: Session, run: AgentReportResult) -> None:
    assert run.status == "ok"
    n_reports, n_audit = _report_audit_counts(session)
    assert n_reports == 1
    assert n_audit == 1
    assert run.summary.endswith(RESEARCH_ONLY)


def _enable_narratives(monkeypatch: pytest.MonkeyPatch) -> None:
    """``ResearchAgent._narratives_enabled`` reads ``get_settings().research.agents
    .llm_narratives`` via a fresh ``from signalforge.config import get_settings``
    at call time, so patching the module attribute is enough — agent modules
    that imported ``get_settings`` at load time keep the real Settings object."""
    fake_settings = types.SimpleNamespace(
        research=types.SimpleNamespace(agents=types.SimpleNamespace(llm_narratives=True))
    )
    monkeypatch.setattr("signalforge.config.get_settings", lambda: fake_settings)


class _FakeLlmClient:
    model = "fake-model"

    def __init__(self, text: str) -> None:
        self._text = text

    def complete(self, *, system: str, prompt: str, max_tokens: int = 900) -> LlmResult:
        return LlmResult(text=self._text, model=self.model, prompt_tokens=1, completion_tokens=1)


AGENT_CLASSES = [MarketRegimeAgent, NewsResearchAgent, PortfolioRiskAgent, JournalReviewAgent]


# ---------------------------------------------------------------------------
# empty-DB behaviour: (a) for every agent
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("agent_cls", AGENT_CLASSES, ids=lambda c: c.name)
def test_agent_empty_db_is_ok_with_missing_data(session: Session, agent_cls: type) -> None:
    before = _state_counts(session)
    result = agent_cls().run(session)
    assert result.status == "ok"
    assert result.missing_data  # non-empty
    _assert_single_report_no_side_effects(session, result)
    assert _state_counts(session) == before


# ---------------------------------------------------------------------------
# (e) grounding guard, generic across all four agents
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("agent_cls", AGENT_CLASSES, ids=lambda c: c.name)
def test_agent_narrative_grounding(
    session: Session, monkeypatch: pytest.MonkeyPatch, agent_cls: type
) -> None:
    _enable_narratives(monkeypatch)

    monkeypatch.setattr(
        llm_client_mod,
        "build_client",
        lambda: _FakeLlmClient("BUY NOW 12345 shares. AI explanation, not a trading instruction."),
    )
    rejected = agent_cls().run(session)
    assert rejected.narrative is None
    assert "llm_narrative_unavailable_or_rejected" in rejected.missing_data
    deterministic_summary = rejected.summary

    monkeypatch.setattr(
        llm_client_mod,
        "build_client",
        lambda: _FakeLlmClient("Markets look calm. AI explanation, not a trading instruction."),
    )
    accepted = agent_cls().run(session)
    assert accepted.narrative is not None
    assert accepted.narrative.startswith(NARRATIVE_LABEL)
    assert accepted.summary == deterministic_summary


# ---------------------------------------------------------------------------
# MarketRegimeAgent: seeded data
# ---------------------------------------------------------------------------


def test_market_regime_agent_seeded(session: Session) -> None:
    from signalforge.data.adapters.fixture import FixtureMarketDataAdapter
    from signalforge.data.ingest import ingest_universe

    # Shrink the research universe so ingestion stays fast; the agent reads
    # it via effective_research_config(session), not a hardcoded list.
    set_setting(session, "research_overrides", {"watchlist": ["AAPL"], "etf_universe": ["SPY"]})

    end = date.today()
    start = end - timedelta(days=365 * 6)
    ingest_universe(session, FixtureMarketDataAdapter(), ["AAPL", "SPY"], start, end)
    session.commit()

    before = _state_counts(session)
    result = MarketRegimeAgent().run(session)
    _assert_single_report_no_side_effects(session, result)
    assert _state_counts(session) == before

    trend_label = result.evidence["spy"]["regime"]["trend"]
    assert trend_label in result.summary
    assert result.summary.endswith(RESEARCH_ONLY)


# ---------------------------------------------------------------------------
# NewsResearchAgent: seeded data
# ---------------------------------------------------------------------------


def test_news_research_agent_seeded(session: Session) -> None:
    now = datetime.now(UTC)
    session.add(
        NewsItem(
            headline="Company reports record quarter",
            url="https://example.com/a",
            published_at=now - timedelta(hours=2),
            source="Benzinga",
            provider="massive_benzinga_news",
            dedupe_key="bz-1",
            instrument_symbols=["AAPL"],
        )
    )
    session.add(
        NewsItem(
            headline="Analysts weigh in on the same story",
            url="https://example.com/b",
            published_at=now - timedelta(hours=1),
            source="Reuters",
            provider="generic_wire",
            dedupe_key="gen-1",
            instrument_symbols=["AAPL"],
        )
    )
    session.add(
        EntitlementCheck(
            batch_id="b1",
            subscription="benzinga_news",
            feed="benzinga_news",
            endpoint="/benzinga/v2/news",
            source="benzinga",
            checked_at=now,
            available=True,
            detail="",
        )
    )
    session.flush()

    before = _state_counts(session)
    result = NewsResearchAgent().run(session)
    _assert_single_report_no_side_effects(session, result)
    assert _state_counts(session) == before

    assert "Benzinga" in result.summary
    assert "News is context only and cannot affect any trade decision." in result.summary
    for forbidden in ("buy", "sell", "long", "short"):
        assert forbidden not in result.summary.lower()

    # cross-publisher conflict on AAPL
    assert result.evidence["conflicts"]
    assert result.evidence["conflicts"][0]["ticker"] == "AAPL"

    citations = result.citations
    assert citations and {"headline", "publisher", "url", "published_at"} <= citations[0].keys()


# ---------------------------------------------------------------------------
# PortfolioRiskAgent: seeded data
# ---------------------------------------------------------------------------


def test_portfolio_risk_agent_seeded(session: Session) -> None:
    acct = PaperAccount(name="default", initial_cash=Decimal("10000"), cash=Decimal("5000"))
    session.add(acct)
    session.flush()

    aapl = Instrument(symbol="AAPL", name="Apple", instrument_type="stock", sector="Technology")
    msft = Instrument(symbol="MSFT", name="Microsoft", instrument_type="stock", sector="Technology")
    session.add_all([aapl, msft])
    session.flush()

    now = datetime.now(UTC)
    session.add(
        PaperPosition(
            account_id=acct.id,
            instrument_id=aapl.id,
            horizon=Horizon.SHORT_SWING,
            side=PositionSide.LONG,
            qty=50,
            avg_price=Decimal("150"),
            opened_at=now,
        )
    )
    session.add(
        PaperPosition(
            account_id=acct.id,
            instrument_id=msft.id,
            horizon=Horizon.SHORT_SWING,
            side=PositionSide.LONG,
            qty=5,
            avg_price=Decimal("100"),
            opened_at=now,
        )
    )
    session.flush()

    before = _state_counts(session)
    result = PortfolioRiskAgent().run(session)
    _assert_single_report_no_side_effects(session, result)
    assert _state_counts(session) == before

    assert result.evidence["exposure"]["largest_position_symbol"] == "AAPL"
    assert "AAPL" in result.summary
    assert (
        "This agent explains deterministic risk outputs and cannot override any rule."
        in result.summary
    )


# ---------------------------------------------------------------------------
# JournalReviewAgent: seeded data
# ---------------------------------------------------------------------------


def test_journal_review_agent_seeded(session: Session) -> None:
    acct = PaperAccount(name="default", initial_cash=Decimal("10000"), cash=Decimal("10000"))
    session.add(acct)
    strat = Strategy(name="t1", horizon=Horizon.SHORT_SWING, permits_long=True, permits_short=False)
    session.add(strat)
    session.flush()
    ver = StrategyVersion(strategy_id=strat.id, version="0.1.0", git_sha="x", spec_json={})
    session.add(ver)
    inst = Instrument(symbol="AAPL", name="Apple", instrument_type="stock", sector="Technology")
    session.add(inst)
    session.flush()
    scan = ScanRun(horizon=Horizon.SHORT_SWING, started_at=datetime.now(UTC), config_hash="h")
    session.add(scan)
    session.flush()

    rejected_cand = Candidate(
        scan_run_id=scan.id,
        instrument_id=inst.id,
        strategy_version_id=ver.id,
        horizon=Horizon.SHORT_SWING,
        direction=Direction.LONG,
        entry_zone_low=99.0,
        entry_zone_high=101.0,
        invalidation_level=95.0,
        target_level=110.0,
        target_logic="",
        time_stop_days=10,
        reward_risk_estimate=2.0,
        risk_dollars=50.0,
        risk_pct_of_account=0.5,
        quality_gate_status=QualityGate.NO_TRADE,
        failed_gates=["LIQUIDITY"],
    )
    session.add(rejected_cand)
    session.flush()

    now = datetime.now(UTC)
    accepted_trade = PaperTrade(
        account_id=acct.id,
        candidate_id=None,
        decision=PaperDecision.ACCEPTED,
        signal_snapshot_json={},
        plan_json={},
        why_qualified="trend + volume",
        why_might_fail="possible earnings surprise risk",
        created_at=now,
    )
    rejected_trade = PaperTrade(
        account_id=acct.id,
        candidate_id=rejected_cand.id,
        decision=PaperDecision.REJECTED,
        signal_snapshot_json={},
        plan_json={},
        why_qualified="",
        why_might_fail="liquidity too thin",
        created_at=now,
    )
    session.add_all([accepted_trade, rejected_trade])
    session.flush()

    session.add(JournalEntry(paper_trade_id=accepted_trade.id, rule_adherence_score=8))
    session.add(JournalEntry(paper_trade_id=rejected_trade.id, rule_adherence_score=6))
    session.flush()

    before = _state_counts(session)
    result = JournalReviewAgent().run(session)
    _assert_single_report_no_side_effects(session, result)
    assert _state_counts(session) == before

    assert "1 accepted" in result.summary
    assert "1 rejected" in result.summary
    assert (
        "Education only — this review does not change any rule, size, or signal." in result.summary
    )
