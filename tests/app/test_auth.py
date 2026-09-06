"""Local authentication: first-run registration, login, logout, CSRF."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.app.conftest import _csrf

GOOD_PW = "correct horse battery"


def test_first_run_registration_then_access(client: TestClient) -> None:
    assert client.get("/", follow_redirects=False).status_code == 303
    # /login bounces to /register while no user exists
    assert client.get("/login", follow_redirects=False).headers["location"] == "/register"

    r = client.post(
        "/register",
        data={"username": "Trader", "password": GOOD_PW, "csrf_token": _csrf(client, "/register")},
        follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert client.get("/").status_code == 200  # now signed in


def test_registration_closes_after_first_user(registered_client: TestClient) -> None:
    registered_client.post("/logout", data={"csrf_token": _csrf(registered_client, "/login")})
    assert (
        registered_client.get("/register", follow_redirects=False).headers["location"] == "/login"
    )
    r = registered_client.post(
        "/register",
        data={
            "username": "x",
            "password": GOOD_PW,
            "csrf_token": _csrf(registered_client, "/login"),
        },
        follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_weak_password_is_rejected(client: TestClient) -> None:
    r = client.post(
        "/register",
        data={"username": "t", "password": "short", "csrf_token": _csrf(client, "/register")},
    )
    assert r.status_code == 400
    assert "at least 10" in r.text


def test_login_wrong_password_401_then_correct_303(registered_client: TestClient) -> None:
    registered_client.post("/logout", data={"csrf_token": _csrf(registered_client, "/login")})

    bad = registered_client.post(
        "/login",
        data={
            "username": "trader",
            "password": "wrong-password-xx",
            "csrf_token": _csrf(registered_client, "/login"),
        },
        follow_redirects=False,
    )
    assert bad.status_code == 401
    assert "incorrect" in bad.text.lower()

    ok = registered_client.post(
        "/login",
        data={
            "username": "trader",
            "password": GOOD_PW,
            "csrf_token": _csrf(registered_client, "/login"),
        },
        follow_redirects=False,
    )
    assert ok.status_code == 303 and ok.headers["location"] == "/"


def test_logout_clears_session(registered_client: TestClient) -> None:
    assert registered_client.get("/", follow_redirects=False).status_code == 200
    registered_client.post("/logout", data={"csrf_token": _csrf(registered_client, "/login")})
    assert registered_client.get("/", follow_redirects=False).status_code == 303


def test_post_without_csrf_is_forbidden(client: TestClient) -> None:
    client.get("/register")  # establish a session
    r = client.post("/register", data={"username": "t", "password": GOOD_PW})
    assert r.status_code == 403


def test_open_redirect_via_next_is_neutralised(registered_client: TestClient) -> None:
    registered_client.post("/logout", data={"csrf_token": _csrf(registered_client, "/login")})
    r = registered_client.post(
        "/login",
        data={
            "username": "trader",
            "password": GOOD_PW,
            "next": "https://evil.example/phish",
            "csrf_token": _csrf(registered_client, "/login"),
        },
        follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"] == "/"
