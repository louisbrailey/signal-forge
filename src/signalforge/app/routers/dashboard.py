"""Server-rendered dashboard (ARCHITECTURE.md §UI). HTMX + Jinja + Tailwind.

Read pages require a signed-in user. Every state-changing POST additionally
depends on ``require_not_killed`` (423 while the kill switch is engaged) and a
valid CSRF token. Paper actions are the only trade actions — there is no order
surface.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.status import HTTP_303_SEE_OTHER, HTTP_400_BAD_REQUEST

from signalforge.app.deps import require_not_killed
from signalforge.app.templating import templates
from signalforge.app.views import (
    agents_context,
    candidate_context,
    journal_context,
    ops_status_context,
    overview_context,
    paper_probation_context,
    scanner_context,
    settings_context,
    strategies_context,
    strategy_promotion_context,
    universe_context,
)
from signalforge.audit import record
from signalforge.auth import csrf
from signalforge.auth.deps import csrf_protect, require_user_page
from signalforge.db.models import Strategy, StrategyVersion, User
from signalforge.db.session import get_db
from signalforge.domain import PaperDecision, StrategyStatus
from signalforge.killswitch import get_kill_switch
from signalforge.paper.journal import add_entry
from signalforge.paper.ledger import accept_candidate, mark_to_market, record_decision
from signalforge.paper.portfolio import portfolio_snapshot
from signalforge.portfolio import import_csv, portfolio_analytics
from signalforge.settings_store import RESEARCH_OVERRIDES_KEY, set_setting

router = APIRouter()

DbDep = Annotated[Session, Depends(get_db)]
UserDep = Annotated[User, Depends(require_user_page)]
Guard = [Depends(require_user_page), Depends(require_not_killed), Depends(csrf_protect)]


def _page(request: Request, user: User, name: str, ctx: dict[str, object]) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        name,
        {**ctx, "user": user, "csrf_token": csrf.get_or_create_token(request), "nav_active": name},
    )


# ---- pages ---------------------------------------------------------------
@router.get("/", response_class=HTMLResponse)
def overview(request: Request, db: DbDep, user: UserDep) -> HTMLResponse:
    return _page(request, user, "overview.html", overview_context(db))


@router.get("/scanner", response_class=HTMLResponse)
def scanner(
    request: Request,
    db: DbDep,
    user: UserDep,
    horizon: str | None = None,
    strategy: str | None = None,
    sector: str | None = None,
    min_reward_risk: float = 0.0,
    exclude_event_risk: bool = False,
) -> HTMLResponse:
    ctx = scanner_context(
        db,
        horizon=horizon,
        strategy=strategy,
        sector=sector,
        min_reward_risk=min_reward_risk,
        exclude_event_risk=exclude_event_risk,
    )
    return _page(request, user, "scanner.html", ctx)


@router.get("/candidates/{candidate_id}", response_class=HTMLResponse)
def candidate_detail(request: Request, db: DbDep, user: UserDep, candidate_id: int) -> HTMLResponse:
    ctx = candidate_context(db, candidate_id)
    if ctx is None:
        return templates.TemplateResponse(
            request,
            "not_found.html",
            {"user": user, "what": f"candidate {candidate_id}"},
            status_code=404,
        )
    return _page(request, user, "candidate_detail.html", ctx)


@router.get("/portfolio", response_class=HTMLResponse)
def portfolio_page(request: Request, db: DbDep, user: UserDep) -> HTMLResponse:
    return _page(
        request,
        user,
        "portfolio.html",
        {"paper": portfolio_snapshot(db), "imported": portfolio_analytics(db)},
    )


@router.get("/strategies", response_class=HTMLResponse)
def strategies_page(request: Request, db: DbDep, user: UserDep) -> HTMLResponse:
    return _page(request, user, "strategies.html", strategies_context(db))


@router.get("/strategies/promotion", response_class=HTMLResponse)
def strategy_promotion_page(request: Request, db: DbDep, user: UserDep) -> HTMLResponse:
    return _page(request, user, "strategy_promotion.html", strategy_promotion_context(db))


@router.post("/strategies/promotion/run", dependencies=Guard)
def act_run_promotion(db: DbDep) -> RedirectResponse:
    """Runs the 10-gate pipeline for every default strategy. This is the *only*
    action that can move a strategy to paper_approved, and only when every gate
    passes — this handler does not decide anything itself."""
    from signalforge.research.promotion import evaluate_all_default_strategies

    evaluate_all_default_strategies(db)
    record("promotion.run", entity="all_strategies", actor="local-user")
    return RedirectResponse("/strategies/promotion", HTTP_303_SEE_OTHER)


@router.get("/paper-probation", response_class=HTMLResponse)
def paper_probation_page(request: Request, db: DbDep, user: UserDep) -> HTMLResponse:
    return _page(request, user, "paper_probation.html", paper_probation_context(db))


@router.post("/paper-probation/toggle", dependencies=Guard)
def act_toggle_paper_probation(
    db: DbDep, enable: Annotated[bool, Form()] = False
) -> RedirectResponse:
    """Turns candidate-trade alerts on/off for PAPER_APPROVED strategies —
    still further gated, per candidate, by an exact dataset-scope match
    (research.approval_scope). Never touches auto-simulation (stays off) or
    paper-trade acceptance (stays manual)."""
    from signalforge.settings_store import set_setting

    set_setting(db, "paper_probation_enabled", enable)
    record(
        "paper_probation.toggle",
        entity="paper_probation_enabled",
        actor="local-user",
        after=enable,
    )
    return RedirectResponse("/paper-probation", HTTP_303_SEE_OTHER)


@router.get("/journal", response_class=HTMLResponse)
def journal_page(request: Request, db: DbDep, user: UserDep) -> HTMLResponse:
    return _page(request, user, "journal.html", journal_context(db))


@router.get("/briefing", response_class=HTMLResponse)
def briefing_page(request: Request, db: DbDep, user: UserDep) -> HTMLResponse:
    from signalforge.briefing import latest_briefing

    return _page(request, user, "briefing.html", {"briefing": latest_briefing(db)})


@router.post("/briefing/build", dependencies=Guard)
def act_build_briefing(db: DbDep) -> RedirectResponse:
    from signalforge.briefing import build_and_store_briefing

    build_and_store_briefing(db)
    return RedirectResponse("/briefing", HTTP_303_SEE_OTHER)


@router.get("/options", response_class=HTMLResponse)
def options_page(
    request: Request,
    db: DbDep,
    user: UserDep,
    underlying: str | None = None,
    expiration: str | None = None,
    contract: str | None = None,
    sim: str = "long_call",
    spot: float | None = None,
    strike: float | None = None,
    premium: float | None = None,
) -> HTMLResponse:
    from signalforge.app.views import options_context

    ctx = options_context(
        db,
        underlying=underlying,
        expiration=expiration,
        contract=contract,
        sim=sim,
        spot=spot,
        strike=strike,
        premium=premium,
    )
    return _page(request, user, "options.html", ctx)


@router.get("/news", response_class=HTMLResponse)
def news_page(
    request: Request, db: DbDep, user: UserDep, symbol: str | None = None
) -> HTMLResponse:
    from signalforge.app.views import news_context

    return _page(request, user, "news.html", news_context(db, symbol=symbol))


@router.get("/ops", response_class=HTMLResponse)
def ops_status_page(request: Request, db: DbDep, user: UserDep) -> HTMLResponse:
    """Operational Status — read-only; no secrets, no actions."""
    return _page(request, user, "ops_status.html", ops_status_context(db))


@router.get("/universe", response_class=HTMLResponse)
def universe_page(request: Request, db: DbDep, user: UserDep) -> HTMLResponse:
    """Liquid-universe coverage — read-only; research only."""
    return _page(request, user, "universe.html", universe_context(db))


@router.get("/agents", response_class=HTMLResponse)
def agents_page(request: Request, db: DbDep, user: UserDep) -> HTMLResponse:
    """Research agents — read-only reports; no actions."""
    return _page(request, user, "agents.html", agents_context(db))


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: DbDep, user: UserDep) -> HTMLResponse:
    return _page(request, user, "settings.html", settings_context(db))


# ---- actions ----------------------------------------------------------------
@router.post("/candidates/{candidate_id}/accept", dependencies=Guard)
def act_accept(candidate_id: int, db: DbDep) -> RedirectResponse:
    res = accept_candidate(db, candidate_id)
    record("paper.accept", entity=f"candidate:{candidate_id}", actor="local-user")
    return RedirectResponse(
        f"/candidates/{candidate_id}?accepted={res.paper_trade_id}", HTTP_303_SEE_OTHER
    )


@router.post("/candidates/{candidate_id}/decision", dependencies=Guard)
def act_decision(
    candidate_id: int,
    db: DbDep,
    decision: Annotated[str, Form()],
    note: Annotated[str, Form()] = "",
) -> RedirectResponse:
    dec = PaperDecision(decision.lower())
    record_decision(db, candidate_id, dec, note=note)
    record("paper.decision", entity=f"candidate:{candidate_id}", actor="local-user")
    return RedirectResponse(f"/candidates/{candidate_id}?decision={dec.value}", HTTP_303_SEE_OTHER)


@router.post("/journal", dependencies=Guard)
def act_journal(
    db: DbDep,
    notes: Annotated[str, Form()] = "",
    lessons: Annotated[str, Form()] = "",
    rule_adherence_score: Annotated[int | None, Form()] = None,
    paper_trade_id: Annotated[int | None, Form()] = None,
    candidate_id: Annotated[int | None, Form()] = None,
) -> RedirectResponse:
    add_entry(
        db,
        paper_trade_id=paper_trade_id,
        candidate_id=candidate_id,
        notes=notes,
        lessons=lessons,
        rule_adherence_score=rule_adherence_score,
    )
    return RedirectResponse("/journal", HTTP_303_SEE_OTHER)


@router.post("/portfolio/import", dependencies=Guard)
async def act_import(db: DbDep, file: UploadFile) -> RedirectResponse:
    raw = (await file.read()).decode("utf-8", errors="replace")
    import_csv(db, file.filename or "upload.csv", raw)
    record("portfolio.import", entity=file.filename or "upload.csv", actor="local-user")
    return RedirectResponse("/portfolio", HTTP_303_SEE_OTHER)


@router.post("/strategies/{name}/status", dependencies=Guard)
def act_strategy_status(name: str, db: DbDep, status: Annotated[str, Form()]) -> RedirectResponse:
    """Manual status changes are downgrade-only. A human may move a strategy to
    ``experimental`` or ``disabled`` directly, but never to ``paper_approved`` —
    that status is earned exclusively by clearing every gate in
    ``research.promotion``. This is enforced here, not just by convention."""
    new_status = StrategyStatus(status.lower())
    if new_status is StrategyStatus.PAPER_APPROVED:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=(
                "paper_approved cannot be set manually — a strategy is promoted only by "
                "clearing every gate on the Strategy Promotion page (research.promotion)."
            ),
        )
    strat = db.scalar(select(Strategy).where(Strategy.name == name))
    if strat is not None:
        before = strat.status.value
        strat.status = new_status
        for ver in db.scalars(
            select(StrategyVersion).where(StrategyVersion.strategy_id == strat.id)
        ):
            ver.status = new_status
        db.flush()
        record(
            "strategy.status_change",
            entity=name,
            actor="local-user",
            before=before,
            after=new_status.value,
        )
    return RedirectResponse("/strategies", HTTP_303_SEE_OTHER)


@router.post("/settings", dependencies=Guard)
def act_settings(
    db: DbDep,
    per_trade_risk_pct: Annotated[float | None, Form()] = None,
    max_position_concentration_pct: Annotated[float | None, Form()] = None,
    max_portfolio_exposure_pct: Annotated[float | None, Form()] = None,
    watchlist: Annotated[str, Form()] = "",
    allow_short_candidates: Annotated[bool, Form()] = False,
    auto_simulate: Annotated[bool, Form()] = False,
    alerts_enabled: Annotated[bool, Form()] = False,
    max_alerts_per_day: Annotated[int | None, Form()] = None,
    quiet_start: Annotated[int | None, Form()] = None,
    quiet_end: Annotated[int | None, Form()] = None,
    alert_system_health: Annotated[bool, Form()] = False,
    alert_data_issue: Annotated[bool, Form()] = False,
    alert_daily_briefing: Annotated[bool, Form()] = False,
    alert_candidate: Annotated[bool, Form()] = False,
) -> RedirectResponse:
    risk: dict[str, float] = {}
    if per_trade_risk_pct:
        risk["per_trade_risk_pct"] = per_trade_risk_pct
    if max_position_concentration_pct:
        risk["max_position_concentration_pct"] = max_position_concentration_pct
    if max_portfolio_exposure_pct:
        risk["max_portfolio_exposure_pct"] = max_portfolio_exposure_pct
    overrides: dict[str, object] = {"allow_short_candidates": allow_short_candidates}
    if risk:
        overrides["risk"] = risk
    if watchlist.strip():
        overrides["watchlist"] = [s.strip().upper() for s in watchlist.split(",") if s.strip()]
    set_setting(db, RESEARCH_OVERRIDES_KEY, overrides)
    set_setting(db, "auto_simulate_qualified_signals", auto_simulate)
    set_setting(db, "alerts_enabled", alerts_enabled)
    from signalforge.alerts.dispatch import ALERT_TYPE_SETTING_KEYS
    from signalforge.domain import AlertType

    for alert_type, flag in (
        (AlertType.SYSTEM_HEALTH, alert_system_health),
        (AlertType.DATA_ISSUE, alert_data_issue),
        (AlertType.DAILY_BRIEFING, alert_daily_briefing),
        (AlertType.CANDIDATE, alert_candidate),
    ):
        set_setting(db, ALERT_TYPE_SETTING_KEYS[alert_type], flag)
    if max_alerts_per_day is not None:
        set_setting(db, "max_alerts_per_day", max_alerts_per_day)
    if quiet_start is not None and quiet_end is not None:
        set_setting(db, "quiet_hours", {"start": quiet_start, "end": quiet_end})
    record("settings.update", entity="research_overrides", actor="local-user")
    return RedirectResponse("/settings", HTTP_303_SEE_OTHER)


@router.post("/paper/mtm", dependencies=[Depends(require_user_page), Depends(csrf_protect)])
def act_mtm(db: DbDep) -> RedirectResponse:
    mark_to_market(db)
    return RedirectResponse("/portfolio", HTTP_303_SEE_OTHER)


@router.post("/killswitch", dependencies=[Depends(require_user_page), Depends(csrf_protect)])
def act_killswitch(
    request: Request, action: Annotated[str, Form()], reason: Annotated[str, Form()] = "manual (UI)"
) -> RedirectResponse:
    ks = get_kill_switch()
    if action == "engage":
        ks.engage(reason=reason, actor="local-user")
    else:
        ks.release(reason=reason, actor="local-user")
    record(f"killswitch.{action}", entity="killswitch", actor="local-user", reason=reason)
    return RedirectResponse(request.headers.get("referer", "/"), HTTP_303_SEE_OTHER)
