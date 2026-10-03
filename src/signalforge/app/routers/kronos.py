"""Authenticated, local-only historical AI research; never a decision input."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.app.routers.dashboard import DbDep, Guard, UserDep, _page
from signalforge.db.models import AuditLog
from signalforge.db.session import set_write_intent
from signalforge.kronos.service import KronosUnavailable, replay, runtime_status
from signalforge.settings_store import effective_research_config

router = APIRouter()
ACTION = "kronos.replay"


def _chart(result: dict[str, Any]) -> dict[str, Any]:
    points = result["points"]
    values = [p[k] for p in points for k in ("actual", "predicted", "baseline")]
    lo, hi = min(values), max(values)
    span = max(hi - lo, 0.01)
    lines = {}
    for key in ("actual", "predicted", "baseline"):
        lines[key] = " ".join(
            f"{30 + i * 640 / max(len(points)-1, 1):.2f},{210 - (p[key]-lo)*180/span:.2f}"
            for i, p in enumerate(points)
        )
    return {"lines": lines, "low": lo, "high": hi}


def _context(
    db: Session,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    run_id: int | None = None,
) -> dict[str, Any]:
    recent = db.scalars(
        select(AuditLog).where(AuditLog.action == ACTION).order_by(AuditLog.id.desc()).limit(10)
    ).all()
    return {
        "runtime": runtime_status(),
        "result": result,
        "error": error,
        "run_id": run_id,
        "recent": recent,
        "chart": _chart(result) if result else None,
        "symbols": effective_research_config(db).universe,
    }


@router.get("/kronos", response_class=HTMLResponse)
def kronos_page(
    request: Request, db: DbDep, user: UserDep, run_id: int | None = None
) -> HTMLResponse:
    row = db.get(AuditLog, run_id) if run_id is not None else None
    if run_id is not None and (row is None or row.action != ACTION):
        raise HTTPException(404, "Replay not found")
    return _page(
        request, user, "kronos.html", _context(db, row.after_json if row else None, run_id=run_id)
    )


@router.post("/kronos/replay", dependencies=Guard, response_class=HTMLResponse)
def kronos_replay(
    request: Request,
    db: DbDep,
    user: UserDep,
    symbol: Annotated[str, Form()],
    horizon: Annotated[int, Form()] = 5,
) -> HTMLResponse:
    symbol = symbol.strip().upper()
    actor = user.username
    if symbol not in effective_research_config(db).universe:
        raise HTTPException(400, "Select a configured watchlist symbol")
    # Auth used the POST session. Release its write transaction BEFORE inference.
    db.commit()
    set_write_intent(db, write=False)
    try:
        result = replay(db, symbol, horizon)
    except (KronosUnavailable, ValueError) as exc:
        return _page(request, user, "kronos.html", _context(db, error=str(exc)))
    db.rollback()
    set_write_intent(db, write=True)
    row = AuditLog(
        ts=datetime.now(UTC),
        actor=actor,
        action=ACTION,
        entity=symbol,
        before_json={},
        after_json=result,
    )
    db.add(row)
    db.commit()
    run_id = row.id
    db.commit()
    set_write_intent(db, write=False)
    return _page(request, user, "kronos.html", _context(db, result, run_id=run_id))


@router.get("/kronos/results/{run_id}")
def export_replay(run_id: int, db: DbDep, user: UserDep) -> JSONResponse:
    row = db.get(AuditLog, run_id)
    if row is None or row.action != ACTION:
        raise HTTPException(404, "Replay not found")
    return JSONResponse(
        row.after_json,
        headers={"Content-Disposition": f'attachment; filename="kronos-{run_id}.json"'},
    )
