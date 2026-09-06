"""Login / first-run registration / logout."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from starlette.status import HTTP_303_SEE_OTHER

from signalforge.app.templating import templates
from signalforge.auth import csrf
from signalforge.auth.deps import (
    apply_login_backoff,
    clear_login_failures,
    csrf_protect,
    login_user,
    logout_user,
    record_login_failure,
)
from signalforge.auth.passwords import WeakPasswordError
from signalforge.auth.service import authenticate, create_initial_user, has_any_user
from signalforge.db.session import get_db

router = APIRouter(tags=["auth"])

DbDep = Annotated[Session, Depends(get_db)]


def _safe_next(raw: str) -> str:
    return raw if raw.startswith("/") and not raw.startswith("//") else "/"


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, db: DbDep, next: str = "/") -> Response:
    if not has_any_user(db):
        return RedirectResponse("/register", status_code=HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request,
        "auth/login.html",
        {"csrf_token": csrf.get_or_create_token(request), "next": _safe_next(next), "error": None},
    )


@router.post("/login", dependencies=[Depends(csrf_protect)])
async def login_submit(
    request: Request,
    db: DbDep,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    next: Annotated[str, Form()] = "/",
) -> Response:
    await apply_login_backoff(username)
    user = authenticate(db, username, password)
    if user is None:
        record_login_failure(username)
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {
                "csrf_token": csrf.get_or_create_token(request),
                "next": _safe_next(next),
                "error": "Incorrect username or password.",
            },
            status_code=401,
        )
    clear_login_failures(username)
    login_user(request, user)
    return RedirectResponse(_safe_next(next), status_code=HTTP_303_SEE_OTHER)


@router.get("/register", response_class=HTMLResponse)
def register_form(request: Request, db: DbDep) -> Response:
    if has_any_user(db):
        return RedirectResponse("/login", status_code=HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request,
        "auth/register.html",
        {"csrf_token": csrf.get_or_create_token(request), "error": None},
    )


@router.post("/register", dependencies=[Depends(csrf_protect)])
def register_submit(
    request: Request,
    db: DbDep,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
) -> Response:
    if has_any_user(db):
        return RedirectResponse("/login", status_code=HTTP_303_SEE_OTHER)
    try:
        user = create_initial_user(db, username, password)
    except WeakPasswordError as exc:
        return templates.TemplateResponse(
            request,
            "auth/register.html",
            {"csrf_token": csrf.get_or_create_token(request), "error": str(exc)},
            status_code=400,
        )
    login_user(request, user)
    return RedirectResponse("/", status_code=HTTP_303_SEE_OTHER)


@router.post("/logout", dependencies=[Depends(csrf_protect)])
def logout(request: Request) -> Response:
    logout_user(request)
    return RedirectResponse("/login", status_code=HTTP_303_SEE_OTHER)
