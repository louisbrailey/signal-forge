"""Trade journal + weekly review (ARCHITECTURE.md §1.7)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import Candidate, JournalEntry, PaperTrade
from signalforge.db.types import utcnow
from signalforge.domain import PaperDecision


def add_entry(
    session: Session,
    *,
    paper_trade_id: int | None = None,
    candidate_id: int | None = None,
    notes: str = "",
    outcome: str = "",
    rule_adherence_score: int | None = None,
    lessons: str = "",
) -> int:
    snapshot: dict[str, Any] = {}
    plan: dict[str, Any] = {}
    why_q = why_f = ""
    if paper_trade_id is not None:
        tr = session.get(PaperTrade, paper_trade_id)
        if tr is None:
            raise ValueError(f"paper_trade {paper_trade_id} not found")
        snapshot, plan, why_q, why_f = (
            tr.signal_snapshot_json,
            tr.plan_json,
            tr.why_qualified,
            tr.why_might_fail,
        )
        candidate_id = candidate_id or tr.candidate_id
    elif candidate_id is not None:
        cand = session.get(Candidate, candidate_id)
        if cand is None:
            raise ValueError(f"candidate {candidate_id} not found")
        why_q = "; ".join(cand.reasons_qualify)
        why_f = "; ".join(cand.reasons_fail)

    entry = JournalEntry(
        paper_trade_id=paper_trade_id,
        candidate_id=candidate_id,
        signal_snapshot_json=snapshot,
        why_qualified=why_q,
        why_might_fail=why_f,
        plan_json=plan,
        notes=notes,
        outcome=outcome,
        rule_adherence_score=rule_adherence_score,
        lessons=lessons,
    )
    session.add(entry)
    session.flush()
    return entry.id


def list_entries(session: Session, *, limit: int = 100) -> list[JournalEntry]:
    return list(
        session.scalars(select(JournalEntry).order_by(JournalEntry.created_at.desc()).limit(limit))
    )


def weekly_review(session: Session, week_start: date | None = None) -> dict[str, Any]:
    start = week_start or (date.today() - timedelta(days=7))
    end = start + timedelta(days=7)
    start_dt = utcnow().replace(
        year=start.year, month=start.month, day=start.day, hour=0, minute=0, second=0, microsecond=0
    )
    end_dt = start_dt + timedelta(days=7)

    trades = list(
        session.scalars(
            select(PaperTrade).where(
                PaperTrade.created_at >= start_dt, PaperTrade.created_at < end_dt
            )
        )
    )
    entries = list(
        session.scalars(
            select(JournalEntry).where(
                JournalEntry.created_at >= start_dt, JournalEntry.created_at < end_dt
            )
        )
    )
    by_decision: dict[str, int] = {}
    for tr in trades:
        by_decision[tr.decision.value] = by_decision.get(tr.decision.value, 0) + 1
    scores = [e.rule_adherence_score for e in entries if e.rule_adherence_score is not None]
    return {
        "week_start": start.isoformat(),
        "week_end": end.isoformat(),
        "trades_logged": len(trades),
        "by_decision": by_decision,
        "accepted": by_decision.get(PaperDecision.ACCEPTED.value, 0),
        "journal_entries": len(entries),
        "avg_rule_adherence": round(sum(scores) / len(scores), 1) if scores else None,
        "lessons": [e.lessons for e in entries if e.lessons],
    }
