"""Base class every research agent extends.

Lifecycle of ``run()``:

1. ``collect(session)`` — deterministic evidence: a JSON-safe dict whose
   every leaf that came from a data source carries its own timestamp/source
   (agents raise ``MissingEvidence`` instead of guessing).
2. ``summarize(evidence)`` — deterministic text built ONLY from the evidence.
3. ``narrate(evidence, summary)`` — optional, LLM-based, explanatory only:
   runs only when the LLM layer is configured, must pass
   ``llm.guards.assert_grounded`` (no number that is not in the evidence,
   mandatory AI footer), and is stored separately, labelled, never merged
   into the deterministic summary.
4. One ``AgentReport`` row + one ``AuditLog`` event (``agent.run`` or
   ``agent.failed``). Nothing else is ever written.

Failure behaviour: any exception inside collect/summarize is caught, recorded
as ``status="failed"`` with the reason, audited, and NOT re-raised — an agent
can neither crash the scheduler nor leave a half-written report. A narrative
failure (LLM unavailable, guard violation) degrades to ``narrative=None`` and
is recorded in ``missing_data``.
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy.orm import Session

from signalforge import RESEARCH_ONLY_NOTICE
from signalforge.db.models import AgentReport, AuditLog
from signalforge.observability import get_logger

_log = get_logger("agents")

NARRATIVE_LABEL = "LLM narrative — explanatory only; not a decision input"


class MissingEvidence(RuntimeError):
    """A required deterministic input is absent; the agent must say so, not guess."""


@dataclass(slots=True)
class AgentReportResult:
    agent: str
    status: str  # ok | failed
    summary: str
    evidence: dict[str, Any]
    narrative: str | None
    missing_data: list[str] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    report_id: int | None = None
    duration_s: float = 0.0
    error: str = ""


class ResearchAgent(ABC):
    """One bounded role. Subclasses set the class attributes and implement
    ``collect`` and ``summarize``; ``narrate`` is opt-in."""

    name: ClassVar[str]
    role: ClassVar[str]
    allowed_inputs: ClassVar[tuple[str, ...]]
    outputs: ClassVar[tuple[str, ...]]
    prohibited: ClassVar[tuple[str, ...]]
    may_write: ClassVar[str] = "agent_report + audit_log only"
    llm_narrative: ClassVar[bool] = False  # opt-in per agent

    # ---- role contract -------------------------------------------------
    @abstractmethod
    def collect(self, session: Session) -> dict[str, Any]:
        """Deterministic evidence with per-item source + timestamp."""

    @abstractmethod
    def summarize(self, evidence: dict[str, Any]) -> str:
        """Deterministic text derived only from ``evidence``."""

    def citations(self, evidence: dict[str, Any]) -> list[dict[str, Any]]:
        return []

    def missing_data(self, evidence: dict[str, Any]) -> list[str]:
        return list(evidence.get("missing_data", []))

    # ---- optional explanatory narrative -------------------------------
    def narrate(
        self, evidence: dict[str, Any], summary: str, *, enabled: bool | None = None
    ) -> str | None:
        """Explain the deterministic summary. Never decides anything."""
        allowed = self._narratives_enabled() if enabled is None else enabled
        if not self.llm_narrative or not allowed:
            return None
        from signalforge.llm.client import build_client
        from signalforge.llm.guards import AI_FOOTER, GuardViolation, assert_grounded

        client = build_client()
        if client is None:
            return None
        system = (
            f"You are the {self.role} for a paper-trading research system. Explain the "
            "deterministic summary below in plain language for a human reader. You may only "
            "restate numbers that appear in the FROZEN EVIDENCE; you must not recommend, rank, "
            "size, or predict; you must not suggest buying or selling anything. End with the "
            f"exact footer: {AI_FOOTER}"
        )
        prompt = (
            "FROZEN EVIDENCE (JSON):\n"
            + json.dumps(evidence, indent=2, default=str)
            + "\n\nDETERMINISTIC SUMMARY:\n"
            + summary
        )
        try:
            text = client.complete(system=system, prompt=prompt).text
            # The deterministic summary is itself frozen, code-generated fact text;
            # restating its (rounded) numbers is exactly what a narrative may do.
            assert_grounded(text, {"evidence": evidence, "summary": summary})
        except GuardViolation as exc:
            _log.warning("agent.narrative_rejected", agent=self.name, reason=str(exc)[:160])
            return None
        except Exception as exc:
            _log.warning("agent.narrative_failed", agent=self.name, error=repr(exc)[:160])
            return None
        return f"{NARRATIVE_LABEL}\n\n{text}"

    @staticmethod
    def _narratives_enabled() -> bool:
        from signalforge.config import get_settings

        return bool(get_settings().research.agents.llm_narratives)

    @staticmethod
    def _narratives_enabled_for(session: Session) -> bool:
        """Effective (DB-override-aware) switch; falls back to static settings."""
        static = ResearchAgent._narratives_enabled()
        try:
            from signalforge.settings_store import effective_research_config

            return static or bool(effective_research_config(session).agents.llm_narratives)
        except Exception:  # pragma: no cover - defensive: never block a report
            return static

    # ---- run ------------------------------------------------------------
    def run(self, session: Session, *, as_of: datetime | None = None) -> AgentReportResult:
        started = time.monotonic()
        as_of = as_of or datetime.now(UTC)
        try:
            evidence = json.loads(json.dumps(self.collect(session), default=str))
            summary = self.summarize(evidence)
            if RESEARCH_ONLY_NOTICE not in summary:
                summary = f"{summary}\n\n{RESEARCH_ONLY_NOTICE}"
            missing = self.missing_data(evidence)
            # The operator switch lives in the DB-backed effective research config
            # (research_overrides.agents.llm_narratives), not only in static settings.
            narrative = self.narrate(
                evidence, summary, enabled=self._narratives_enabled_for(session)
            )
            if self.llm_narrative and narrative is None:
                missing = [*missing, "llm_narrative_unavailable_or_rejected"]
            result = AgentReportResult(
                agent=self.name,
                status="ok",
                summary=summary,
                evidence=evidence,
                narrative=narrative,
                missing_data=missing,
                citations=self.citations(evidence),
            )
        except Exception as exc:
            _log.exception("agent.failed", agent=self.name)
            result = AgentReportResult(
                agent=self.name,
                status="failed",
                summary=f"{self.name} failed: {exc!r}\n\n{RESEARCH_ONLY_NOTICE}",
                evidence={},
                narrative=None,
                missing_data=["agent_failed"],
                error=repr(exc)[:300],
            )
        result.duration_s = round(time.monotonic() - started, 2)
        self._persist(session, result, as_of)
        return result

    def _persist(self, session: Session, result: AgentReportResult, as_of: datetime) -> None:
        row = AgentReport(
            agent=self.name,
            role=self.role,
            as_of=as_of,
            status=result.status,
            summary=result.summary,
            narrative=result.narrative,
            evidence_json=result.evidence,
            citations_json=result.citations,
            missing_data_json=result.missing_data,
            duration_s=result.duration_s,
            error=result.error,
            created_at=datetime.now(UTC),
        )
        session.add(row)
        session.flush()
        result.report_id = row.id
        session.add(
            AuditLog(
                ts=datetime.now(UTC),
                actor=f"agent:{self.name}",
                action="agent.run" if result.status == "ok" else "agent.failed",
                entity=self.name,
                before_json={},
                after_json={
                    "report_id": row.id,
                    "status": result.status,
                    "duration_s": result.duration_s,
                    "missing_data": result.missing_data,
                    "narrative": result.narrative is not None,
                    "error": result.error,
                },
            )
        )
        session.flush()
