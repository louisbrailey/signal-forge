"""App skeleton: health endpoints, disclaimer, and feed-status placeholder."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from signalforge import RESEARCH_ONLY_NOTICE
from signalforge.app.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_readyz_reports_kill_switch(client: TestClient) -> None:
    r = client.get("/readyz")
    assert r.status_code == 200
    body = r.json()
    assert body["kill_switch_active"] is False
    assert "database" in body["checks"]


def test_index_shows_non_dismissable_disclaimer(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "not financial advice" in r.text.lower()
    assert RESEARCH_ONLY_NOTICE in r.text
    assert "no order is ever placed" in r.text.lower()


def test_feeds_endpoint_is_explicit_about_phase_0(client: TestClient) -> None:
    r = client.get("/api/feeds")
    assert r.status_code == 200
    assert r.json()["feeds"] == []
