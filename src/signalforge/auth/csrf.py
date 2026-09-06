"""Synchroniser-token CSRF protection for state-changing form posts."""

from __future__ import annotations

import hmac
import secrets

from starlette.requests import Request

_SESSION_KEY = "csrf_token"


def get_or_create_token(request: Request) -> str:
    token = request.session.get(_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[_SESSION_KEY] = token
    return token


def is_valid(request: Request, submitted: str | None) -> bool:
    expected = request.session.get(_SESSION_KEY)
    if not expected or not submitted:
        return False
    return hmac.compare_digest(str(expected), str(submitted))
