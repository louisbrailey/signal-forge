"""Charts, the global status strip, and the Markets / Crypto Paper pages.

Read-only. Every chart endpoint requires a signed-in user and returns the
stored data as of now; the browser re-polls them. No POST, no order surface.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.app import charts
from signalforge.app.routers.dashboard import _page
from signalforge.app.templating import templates
from signalforge.auth.deps import require_user, require_user_page
from signalforge.db.models import CryptoPaperBook, User
from signalforge.db.session import get_db

router = APIRouter()

DbDep = Annotated[Session, Depends(get_db)]
ApiUser = Annotated[User, Depends(require_user)]
PageUser = Annotated[User, Depends(require_user_page)]
Days = Annotated[int, Query(ge=5, le=charts.MAX_DAYS)]


# ---- chart JSON --------------------------------------------------------- #
@router.get("/api/charts/equity/{symbol}")
def chart_equity(symbol: str, db: DbDep, _: ApiUser, days: Days = 365) -> dict[str, Any]:
    return charts.equity_bars(db, symbol, days)


@router.get("/api/charts/fx/{pair}")
def chart_fx(pair: str, db: DbDep, _: ApiUser, days: Days = 365) -> dict[str, Any]:
    return charts.fx_bars(db, pair, days)


@router.get("/api/charts/crypto/{pair}")
def chart_crypto(pair: str, db: DbDep, _: ApiUser, days: Days = 365) -> dict[str, Any]:
    return charts.crypto_bars(db, pair, days)


@router.get("/api/charts/paper/equity")
def chart_paper_equity(db: DbDep, _: ApiUser) -> dict[str, Any]:
    return charts.paper_equity(db)


@router.get("/api/charts/paper/crypto/{key}")
def chart_paper_crypto(key: str, db: DbDep, _: ApiUser) -> dict[str, Any]:
    return charts.crypto_paper_curve(db, key)


@router.get("/api/charts/scanner/activity")
def chart_scanner(db: DbDep, _: ApiUser, days: Days = 180) -> dict[str, Any]:
    return charts.scanner_activity(db, days)


@router.get("/api/charts/grid")
def chart_grid(db: DbDep, _: ApiUser, days: Days = 365) -> dict[str, Any]:
    return charts.grid_activity(db, days)


@router.get("/api/charts/snapshot/{market}")
def chart_snapshot(market: str, db: DbDep, _: ApiUser) -> dict[str, Any]:
    from signalforge.config import get_settings

    s = get_settings()
    if market not in ("fx", "crypto"):
        return {"rows": []}
    pairs = (s.forex_pairs if market == "fx" else s.crypto_pairs).split(",")
    return {
        "rows": charts.pair_snapshot(db, market, [p.strip().upper() for p in pairs if p.strip()])
    }


# ---- status strip (htmx partial, every page) --------------------------- #
@router.get("/ui/status-strip", response_class=HTMLResponse)
def status_strip(request: Request, db: DbDep, _: ApiUser) -> HTMLResponse:
    from signalforge.killswitch import get_kill_switch

    feeds = charts.feed_ages(db)
    stale = [f for f in feeds if f["stale"]]
    return templates.TemplateResponse(
        request,
        "_status_strip.html",
        {
            "kill": get_kill_switch().state(),
            "feeds": feeds,
            "stale": stale,
            "generated_at": charts._now().strftime("%H:%M UTC"),
        },
    )


# ---- pages ------------------------------------------------------------- #
@router.get("/markets", response_class=HTMLResponse)
def markets(request: Request, db: DbDep, user: PageUser) -> HTMLResponse:
    from signalforge.config import get_settings
    from signalforge.settings_store import effective_research_config

    s = get_settings()
    return _page(
        request,
        user,
        "markets.html",
        {
            "stocks": list(effective_research_config(db).universe),
            "fx_pairs": [p.strip().upper() for p in s.forex_pairs.split(",") if p.strip()],
            "crypto_pairs": [p.strip().upper() for p in s.crypto_pairs.split(",") if p.strip()],
        },
    )


@router.get("/crypto-paper", response_class=HTMLResponse)
def crypto_paper(request: Request, db: DbDep, user: PageUser) -> HTMLResponse:
    from signalforge.paper.crypto_ledger import status

    keys = [b.strategy_key for b in db.scalars(select(CryptoPaperBook))]
    books = [status(db, k) for k in keys]
    return _page(request, user, "crypto_paper.html", {"books": books})
