"""Auth-related FastAPI dependencies."""

from __future__ import annotations

import asyncio
import time
from typing import Annotated

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from signalforge.auth import csrf
from signalforge.db.models import User
from signalforge.db.session import get_db

_SESSION_UID = "uid"

# Per-username failed-login counter for a small escalating delay (no lockout, to
# avoid a local self-DoS).
_failed: dict[str, int] = {}
_MAX_BACKOFF_SECONDS = 5.0


async def apply_login_backoff(username: str) -> None:
    count = _failed.get(username.strip().lower(), 0)
    if count:
        await asyncio.sleep(min(count * 0.5, _MAX_BACKOFF_SECONDS))


def record_login_failure(username: str) -> None:
    key = username.strip().lower()
    _failed[key] = _failed.get(key, 0) + 1


def clear_login_failures(username: str) -> None:
    _failed.pop(username.strip().lower(), None)


def get_current_user(request: Request, db: Annotated[Session, Depends(get_db)]) -> User | None:
    uid = request.session.get(_SESSION_UID)
    if not uid:
        return None
    user = db.get(User, int(uid))
    return user if (user and user.is_active) else None


CurrentUser = Annotated[User | None, Depends(get_current_user)]


def login_user(request: Request, user: User) -> None:
    request.session[_SESSION_UID] = user.id
    request.session["login_at"] = int(time.time())


def logout_user(request: Request) -> None:
    request.session.pop(_SESSION_UID, None)
    request.session.pop("login_at", None)


def require_user(user: CurrentUser) -> User:
    """API guard: 401 when not signed in."""
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


def require_user_page(request: Request, user: CurrentUser) -> User:
    """HTML guard: redirect to /login when not signed in."""
    if user is None:
        raise _RedirectException(f"/login?next={request.url.path}")
    return user


class _RedirectException(Exception):
    def __init__(self, location: str) -> None:
        self.location = location


def install_redirect_handler(app: FastAPI) -> None:
    @app.exception_handler(_RedirectException)
    async def _handle(_request: Request, exc: _RedirectException) -> RedirectResponse:
        return RedirectResponse(exc.location, status_code=status.HTTP_303_SEE_OTHER)


def csrf_protect(request: Request, csrf_token: Annotated[str, Form()] = "") -> None:
    if not csrf.is_valid(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")
