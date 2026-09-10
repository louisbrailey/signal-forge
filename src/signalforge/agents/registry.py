"""Agent registry + runners. Agents are instantiated fresh per run."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.orm import Session

from signalforge.agents.base import AgentReportResult, ResearchAgent


def all_agents() -> list[ResearchAgent]:
    from signalforge.agents.data_quality import DataQualityAgent
    from signalforge.agents.journal_review import JournalReviewAgent
    from signalforge.agents.news_research import NewsResearchAgent
    from signalforge.agents.operations import OperationsAgent
    from signalforge.agents.portfolio_risk import PortfolioRiskAgent
    from signalforge.agents.regime import MarketRegimeAgent
    from signalforge.agents.strategy_validation import StrategyValidationAgent

    return [
        DataQualityAgent(),
        StrategyValidationAgent(),
        MarketRegimeAgent(),
        NewsResearchAgent(),
        PortfolioRiskAgent(),
        JournalReviewAgent(),
        OperationsAgent(),
    ]


def get_agent(name: str) -> ResearchAgent:
    for a in all_agents():
        if a.name == name:
            return a
    raise KeyError(f"unknown agent {name!r}")


def run_agent(session: Session, name: str) -> AgentReportResult:
    return get_agent(name).run(session)


def run_all_agents(session: Session, names: Iterable[str] | None = None) -> list[AgentReportResult]:
    wanted = set(names) if names else None
    out: list[AgentReportResult] = []
    for agent in all_agents():
        if wanted is None or agent.name in wanted:
            out.append(agent.run(session))
            session.commit()  # each report is its own short write transaction
    return out
