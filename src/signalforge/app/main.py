"""Signal Forge FastAPI application.

Wires: local auth, the non-dismissable disclaimer, health endpoints, the
kill-switch API + guard, and (incrementally through Phase 1) the dashboard
routers.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from signalforge import __version__
from signalforge.app.deps import require_not_killed
from signalforge.app.routers import auth as auth_router
from signalforge.app.templating import STATIC_DIR, templates
from signalforge.audit import record
from signalforge.auth import csrf
from signalforge.auth.deps import install_redirect_handler, require_user_page
from signalforge.config import get_settings
from signalforge.db.models import User
from signalforge.killswitch import get_kill_switch
from signalforge.observability import configure_logging, get_logger

_log = get_logger("app")


class KillSwitchRequest(BaseModel):
    # Module scope so FastAPI can resolve the annotation under
    # ``from __future__ import annotations``.
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
    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    install_redirect_handler(app)
    app.include_router(auth_router.router)

    # ---- health (public) -------------------------------------------------
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
        from signalforge.data.feeds import feed_status_report

        return feed_status_report()

    # ---- kill switch API ----------------------------------------------------
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
        """Phase 0 wiring demo: any state-changing route depends on require_not_killed."""
        return {"result": "ok — this stands in for a state-changing research/paper route"}

    # ---- overview (auth-protected) ----------------------------------------
    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, user: Annotated[User, Depends(require_user_page)]) -> HTMLResponse:
        st = get_kill_switch().state()
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "kill_switch": st,
                "settings_env": settings.app_env.value,
                "user": user,
                "csrf_token": csrf.get_or_create_token(request),
            },
        )

    return app


app = create_app()
