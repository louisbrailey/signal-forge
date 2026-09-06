"""Journal entries, weekly review, and append-only corrections."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import Candidate, JournalEntry, TradeCorrection
from signalforge.domain import PaperDecision
from signalforge.paper.corrections import record_correction
from signalforge.paper.journal import add_entry, weekly_review
from signalforge.paper.ledger import accept_candidate, record_decision


def test_journal_entry_from_a_paper_trade(
    session: Session, passing_candidate: Candidate, account
) -> None:
    res = accept_candidate(session, passing_candidate.id, as_of=date(2024, 2, 1))
    eid = add_entry(
        session,
        paper_trade_id=res.paper_trade_id,
        notes="followed the plan",
        rule_adherence_score=90,
        lessons="size was fine",
    )
    entry = session.get(JournalEntry, eid)
    assert entry is not None
    assert entry.paper_trade_id == res.paper_trade_id
    assert entry.candidate_id == passing_candidate.id
    assert entry.why_qualified  # copied from the trade snapshot


def test_weekly_review_counts_decisions(
    session: Session, passing_candidate: Candidate, account
) -> None:
    record_decision(session, passing_candidate.id, PaperDecision.REJECTED)
    add_entry(session, candidate_id=passing_candidate.id, rule_adherence_score=80, lessons="wait")
    review = weekly_review(session, week_start=date.today())
    assert review["trades_logged"] >= 1
    assert review["by_decision"].get("rejected", 0) >= 1
    assert review["avg_rule_adherence"] == 80.0


def test_correction_is_append_only(session: Session, passing_candidate: Candidate, account) -> None:
    res = accept_candidate(session, passing_candidate.id, as_of=date(2024, 2, 1))
    cid = record_correction(
        session,
        res.paper_trade_id,
        field="why_might_fail",
        old_value="whipsaw",
        new_value="whipsaw; also gap risk",
        reason="add detail",
    )
    corr = session.get(TradeCorrection, cid)
    assert corr is not None and corr.paper_trade_id == res.paper_trade_id
    assert len(list(session.scalars(select(TradeCorrection)))) == 1


def test_correction_rejects_unknown_trade(session: Session) -> None:
    with pytest.raises(ValueError, match="not found"):
        record_correction(session, 999, field="x", old_value="", new_value="", reason="y")
