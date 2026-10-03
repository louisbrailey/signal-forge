"""Signal Forge FastAPI application.

Wires: local auth, the non-dismissable disclaimer, health + kill-switch API, and
the server-rendered dashboard (see ``app/routers/dashboard.py``).
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Depends, FastAPI
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.staticfiles import StaticFiles

from signalforge import __version__
from signalforge.app.deps import require_not_killed
from signalforge.app.routers import auth as auth_router
from signalforge.app.routers import dashboard as dashboard_router
from signalforge.app.templating import STATIC_DIR
from signalforge.audit import record
from signalforge.auth.deps import install_redirect_handler
from signalforge.config import get_settings
from signalforge.killswitch import get_kill_switch
from signalforge.observability import configure_logging, get_logger

_log = get_logger("app")


class KillSwitchRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=280)
    actor: str = Field(default="local-user", max_length=80)


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(json_output=settings.app_env.value != "dev")
    if not settings.app_encryption_key.get_secret_value() and settings.app_env.value == "dev":
        _log.warning("app.ephemeral_session_secret", detail="APP_ENCRYPTION_KEY unset (dev only)")
    _log.info("app.start", version=__version__, env=settings.app_env.value)

    scheduler = None
    worker_lock = None
    if os.environ.get("APP_RUN_SCHEDULER", "").lower() in {"1", "true", "yes"}:
        from signalforge.scheduler import build_scheduler, run_catch_up
        from signalforge.worker_lock import WorkerAlreadyRunning, acquire_worker_lock

        try:
            worker_lock = acquire_worker_lock()
        except WorkerAlreadyRunning as exc:
            # Never run a second scheduler against the same database.
            _log.error("app.scheduler_not_started", reason=str(exc))
        else:
            from signalforge.scheduler import other_live_worker

            other = other_live_worker()
            if other:
                _log.error("app.scheduler_not_started", reason=other)
                worker_lock.release()
                worker_lock = None
            else:
                run_catch_up()
                scheduler = build_scheduler()
                scheduler.start()
                _log.info("app.scheduler_started")
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        if worker_lock is not None:
            worker_lock.release()
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
    app.include_router(dashboard_router.router)
    from signalforge.app.routers import kronos, paper_console

    app.include_router(paper_console.router)
    app.include_router(kronos.router)

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

    # ---- kill switch API -----------------------------------------------------
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
        st = get_kill_switch().release(reason=body.reason, actor=body.actor)
        record("killswitch.release", actor=body.actor, entity="killswitch", reason=body.reason)
        return {"active": st.active, "reason": st.reason, "changed_at": st.changed_at.isoformat()}

    @app.post("/api/_demo/guarded", dependencies=[Depends(require_not_killed)])
    def guarded_demo() -> dict[str, str]:
        """Wiring demo: any state-changing route depends on require_not_killed."""
        return {"result": "ok — stands in for a state-changing research/paper route"}

    return app


app = create_app()
