"""Journal-review agent (read-only, education only).

Turns 30 days of paper-trade decisions and journal entries into deterministic
behavioural-pattern statistics — acceptance rate, how often an accepted
trade's stated failure mode is risk-aware, median rule-adherence, and the
most common gate behind a rejection. This agent never changes a rule, a
size, or a signal; it only reports on what already happened.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime, timedelta
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.agents.base import ResearchAgent
from signalforge.db.models import Candidate, JournalEntry, PaperTrade
from signalforge.domain import PaperDecision
from signalforge.paper.journal import weekly_review

_WINDOW_DAYS = 30
_RISK_KEYWORDS = ("earnings", "liquidity", "stale")
_EDUCATION_ONLY_SENTENCE = "Education only — this review does not change any rule, size, or signal."


class JournalReviewAgent(ResearchAgent):
    name = "journal_review"
    role = "Journal-review agent"
    allowed_inputs = (
        "signalforge.paper.journal.weekly_review",
        "signalforge.db.models.PaperTrade (last 30 days)",
        "signalforge.db.models.JournalEntry (last 30 days)",
        "signalforge.db.models.Candidate (failed_gates, joined via rejected PaperTrade)",
    )
    outputs = ("agent_report",)
    prohibited = ("rule change", "size change", "signal change", "recommendation", "alert")
    llm_narrative = True

    def collect(self, session: Session) -> dict[str, Any]:
        missing: list[str] = []
        now = datetime.now(UTC)
        window_start = now - timedelta(days=_WINDOW_DAYS)

        review = weekly_review(session, week_start=date.today() - timedelta(days=7))

        trades = list(
            session.scalars(select(PaperTrade).where(PaperTrade.created_at >= window_start))
        )
        by_decision: dict[str, int] = {d.value: 0 for d in PaperDecision}
        for tr in trades:
            by_decision[tr.decision.value] += 1
        total_trades = len(trades)

        accepted_trades = [tr for tr in trades if tr.decision is PaperDecision.ACCEPTED]
        risk_aware = [
            tr
            for tr in accepted_trades
            if any(kw in (tr.why_might_fail or "").lower() for kw in _RISK_KEYWORDS)
        ]
        acceptance_rate = (
            round(len(accepted_trades) / total_trades * 100.0, 2) if total_trades else None
        )
        risk_awareness_share = (
            round(len(risk_aware) / len(accepted_trades) * 100.0, 2) if accepted_trades else None
        )
        if not trades:
            missing.append(f"no paper trades in the last {_WINDOW_DAYS} days")

        entries = list(
            session.scalars(select(JournalEntry).where(JournalEntry.created_at >= window_start))
        )
        scores = [e.rule_adherence_score for e in entries if e.rule_adherence_score is not None]
        median_adherence = round(float(median(scores)), 2) if scores else None
        if not scores:
            missing.append(
                f"no journal entries with a rule-adherence score in the last {_WINDOW_DAYS} days"
            )

        rejected_trades = [tr for tr in trades if tr.decision is PaperDecision.REJECTED]
        gate_counter: Counter[str] = Counter()
        for tr in rejected_trades:
            if tr.candidate_id is None:
                continue
            cand = session.get(Candidate, tr.candidate_id)
            if cand is None:
                continue
            gate_counter.update(cand.failed_gates or [])
        most_common_failed_gate: dict[str, Any] | None = None
        if gate_counter:
            gate, count = gate_counter.most_common(1)[0]
            most_common_failed_gate = {"gate": gate, "count": count}
        else:
            missing.append(
                "no rejected candidates with recorded failed gates in the last "
                f"{_WINDOW_DAYS} days"
            )

        return {
            "source": "paper_trade + journal_entry + candidate",
            "as_of": now.isoformat(),
            "window_days": _WINDOW_DAYS,
            "trade_counts_by_decision": by_decision,
            "total_trades": total_trades,
            "acceptance_rate_pct": acceptance_rate,
            "risk_awareness_share_pct": risk_awareness_share,
            "median_rule_adherence": median_adherence,
            "most_common_failed_gate": most_common_failed_gate,
            "weekly_review": review,
            "missing_data": missing,
        }

    def summarize(self, evidence: dict[str, Any]) -> str:
        counts = evidence["trade_counts_by_decision"]
        lines = [
            f"Over the last {evidence['window_days']} days: "
            f"{counts.get('accepted', 0)} accepted, {counts.get('rejected', 0)} rejected, "
            f"{counts.get('ignored', 0)} ignored, {counts.get('watch', 0)} watch decisions "
            f"({evidence['total_trades']} total)."
        ]
        if evidence.get("acceptance_rate_pct") is not None:
            lines.append(f"Acceptance rate: {evidence['acceptance_rate_pct']:.2f}%.")
        if evidence.get("risk_awareness_share_pct") is not None:
            lines.append(
                "Share of accepted trades whose stated risk (why_might_fail) mentions "
                f"earnings, liquidity, or staleness: {evidence['risk_awareness_share_pct']:.2f}%."
            )
        if evidence.get("median_rule_adherence") is not None:
            lines.append(
                "Median rule-adherence score from journal entries: "
                f"{evidence['median_rule_adherence']:.2f}."
            )
        gate = evidence.get("most_common_failed_gate")
        if gate:
            lines.append(
                f"Most common failed gate among rejected candidates: {gate['gate']} "
                f"({gate['count']} occurrences)."
            )
        lines.append(_EDUCATION_ONLY_SENTENCE)
        return " ".join(lines)
