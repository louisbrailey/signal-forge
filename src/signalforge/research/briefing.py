"""Daily research briefing (ARCHITECTURE.md §1.11).

Deterministic assembly of the day's state (market status, feed status + latency,
paper account summary, open paper risk, high-priority risk warnings, today's
qualified candidates, NO-TRADE count + reasons). An optional LLM pass renders
prose around the **frozen facts dict** — the briefing is complete and correct
without an LLM.

Filled in Increment 1.11; this module exists now so the scheduler can register
the briefing job.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session


def build_briefing_facts(session: Session, *, account_name: str = "default") -> dict[str, Any]:
    raise NotImplementedError("Daily briefing lands in Phase 1 §1.11.")


def build_and_store_briefing(session: Session) -> dict[str, Any]:
    raise NotImplementedError("Daily briefing lands in Phase 1 §1.11.")
