"""App skeleton: health endpoints, disclaimer, feed-status, and auth gating."""

from __future__ import annotations

from fastapi.testclient import TestClient

from signalforge import RESEARCH_ONLY_NOTICE


def test_healthz_is_public(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_readyz_reports_db_at_head(client: TestClient) -> None:
    r = client.get("/readyz")
    assert r.status_code == 200
    body = r.json()
    assert body["kill_switch_active"] is False
    assert body["checks"]["database"]["connected"] is True
    assert body["checks"]["database"]["at_head"] is True
    assert body["status"] == "ok"


def test_root_redirects_to_auth_when_signed_out(client: TestClient) -> None:
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith(("/login", "/register"))


def test_first_run_shows_registration_with_disclaimer(client: TestClient) -> None:
    r = client.get("/register")
    assert r.status_code == 200
    assert "not financial advice" in r.text.lower()
    assert RESEARCH_ONLY_NOTICE in r.text
    assert "no order is ever placed" in r.text.lower()


def test_feeds_endpoint_reports_no_feeds_initially(client: TestClient) -> None:
    r = client.get("/api/feeds")
    assert r.status_code == 200
    assert r.json()["feeds"] == []
