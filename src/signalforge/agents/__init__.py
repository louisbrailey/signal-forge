"""Bounded research agents.

Each agent has ONE role, reads ONLY deterministic outputs already produced by
the research/data/paper layers, and writes ONLY its own ``AgentReport`` row
plus an audit event. An agent can never create a candidate, a paper trade, an
alert, a setting change, or a strategy status change — enforced by
import-linter contract S14 (``pyproject.toml``) and ``tests/agents``. Any LLM
text an agent produces is an explanatory narrative layered on top of a
deterministic summary; it is labelled as such, must pass the grounding guard,
and is never read by any decision path (contract S3).
"""

from signalforge.agents.base import AgentReportResult, ResearchAgent
from signalforge.agents.registry import all_agents, get_agent, run_agent, run_all_agents

__all__ = [
    "AgentReportResult",
    "ResearchAgent",
    "all_agents",
    "get_agent",
    "run_agent",
    "run_all_agents",
]
