"""Signal Forge FastAPI app (Phase 0 skeleton).

Provides health endpoints, the non-dismissable disclaimer page, and the kill-switch
API + guard wiring. Research, data, scanner, portfolio, and journal routers are
added in Phase 1.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from signalforge import NOT_ADVICE_NOTICE, RESEARCH_ONLY_NOTICE, __version__
from signalforge.app.deps import require_not_killed
from signalforge.audit import record
from signalforge.config import get_settings
from signalforge.killswitch import get_kill_switch
from signalforge.observability import configure_logging, get_logger

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"
_log = get_logger("app")


class KillSwitchRequest(BaseModel):
    # Defined at module scope so FastAPI can resolve the annotation under
    # ``from __future__ import annotations`` (a closure-local model cannot be
    # resolved by typing.get_type_hints and would be mis-read as a query param).
    reason: str = Field(min_length=3, max_length=280)
    actor: str = Field(default="local-user", max_length=80)


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(json_output=settings.app_env.value != "dev")
    if not settings.app_encryption_key.get_secret_value() and settings.app_env.value == "dev":
        _log.warning("app.ephemeral_session_secret", detail="APP_ENCRYPTION_KEY unset (dev only)")
    _log.info("app.start", version=__version__, env=settings.app_env.value)
    yield
    _log.info("app.stop")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Signal Forge",
        version=__version__,
        summary="Local-first, paper-trading-only market research. Not financial advice.",
        lifespan=lifespan,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret(),
        same_site="strict",
        https_only=not settings.is_loopback_only,
    )
    if _STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    templates.env.globals.update(
        research_only_notice=RESEARCH_ONLY_NOTICE,
        not_advice_notice=NOT_ADVICE_NOTICE,
        app_version=__version__,
    )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/readyz")
    def readyz() -> dict[str, Any]:
        from signalforge.db.health import check_db

        ks = get_kill_switch().state()
        db = check_db()
        ready = db["connected"] and db["at_head"]
        return {
            "status": "ok" if ready else "degraded",
            "kill_switch_active": ks.active,
            "checks": {"process": "ok", "database": db},
        }

    @app.get("/api/feeds")
    def feeds() -> dict[str, Any]:
        return {
            "feeds": [],
            "note": "No data adapters wired in Phase 0. Every feed will report its "
            "source, latency_category, and last successful update here.",
        }

    @app.get("/api/killswitch")
    def killswitch_status() -> dict[str, Any]:
        st = get_kill_switch().state()
        return {
            "active": st.active,
            "reason": st.reason,
            "actor": st.actor,
            "changed_at": st.changed_at.isoformat(),
        }

    @app.post("/api/killswitch/engage")
    def killswitch_engage(body: KillSwitchRequest) -> dict[str, Any]:
        st = get_kill_switch().engage(reason=body.reason, actor=body.actor)
        record("killswitch.engage", actor=body.actor, entity="killswitch", reason=body.reason)
        return {"active": st.active, "reason": st.reason, "changed_at": st.changed_at.isoformat()}

    @app.post("/api/killswitch/release")
    def killswitch_release(body: KillSwitchRequest) -> dict[str, Any]:
        # Deliberately NOT guarded by require_not_killed — release must work while engaged.
        st = get_kill_switch().release(reason=body.reason, actor=body.actor)
        record("killswitch.release", actor=body.actor, entity="killswitch", reason=body.reason)
        return {"active": st.active, "reason": st.reason, "changed_at": st.changed_at.isoformat()}

    @app.post("/api/_demo/guarded", dependencies=[Depends(require_not_killed)])
    def guarded_demo() -> dict[str, str]:
        """Phase 0 wiring demo: any state-changing route depends on require_not_killed
        and returns 423 while the kill switch is engaged."""
        return {"result": "ok — this stands in for a state-changing research/paper route"}

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        st = get_kill_switch().state()
        return templates.TemplateResponse(
            request,
            "index.html",
            {"kill_switch": st, "settings_env": settings.app_env.value},
        )

    return app


app = create_app()
