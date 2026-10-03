"""Read-only, automatically refreshed operational paper-trading evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge.app.routers.dashboard import DbDep, UserDep, _page
from signalforge.db.models import (
    Candidate,
    Instrument,
    PaperPosition,
    PaperTrade,
    ScanRun,
    WorkerHeartbeat,
)
from signalforge.paper.portfolio import portfolio_snapshot
from signalforge.settings_store import get_setting

router = APIRouter()


def console_context(db: Session) -> dict[str, Any]:
    latest = db.scalars(select(ScanRun).order_by(ScanRun.started_at.desc()).limit(8)).all()
    decisions = db.execute(
        select(PaperTrade, Instrument.symbol)
        .join(Candidate, PaperTrade.candidate_id == Candidate.id)
        .join(Instrument, Candidate.instrument_id == Instrument.id)
        .order_by(PaperTrade.created_at.desc())
        .limit(30)
    ).all()
    hb = db.scalar(select(WorkerHeartbeat).where(WorkerHeartbeat.worker == "scheduler"))
    healthy = bool(hb and (datetime.now(UTC) - hb.last_beat_at).total_seconds() < 120)
    return {
        "account": portfolio_snapshot(db),
        "invalid_history": db.scalar(
            select(func.count(PaperPosition.id)).where(
                PaperPosition.closed_at < PaperPosition.opened_at
            )
        ),
        "worker": hb,
        "worker_healthy": healthy,
        "scans": latest,
        "decisions": decisions,
        "accepted": db.scalar(
            select(func.count(PaperTrade.id)).where(PaperTrade.decision == "ACCEPTED")
        ),
        "open_count": db.scalar(
            select(func.count(PaperPosition.id)).where(PaperPosition.closed_at.is_(None))
        ),
        "automatic": get_setting(db, "auto_simulate_qualified_signals", False) is True,
        "daily_cap": get_setting(db, "auto_simulate_max_per_day", 2),
        "refreshed_at": datetime.now(UTC).isoformat(),
    }


@router.get("/paper-console", response_class=HTMLResponse)
def paper_console(request: Request, db: DbDep, user: UserDep) -> HTMLResponse:
    return _page(request, user, "paper_console.html", console_context(db))
