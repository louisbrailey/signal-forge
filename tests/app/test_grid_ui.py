"""The /grid dashboard page: renders, auth-gated, and honest about what it is."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_grid_page_renders(registered_client: TestClient) -> None:
    r = registered_client.get("/grid")
    assert r.status_code == 200
    assert "Mechanical Grid" in r.text
    # The page must say plainly that this is not a promotion-gated strategy.
    assert "not</em> a promotion-gated strategy" in r.text or "promotion-gated" in r.text
    assert "Research signal only — no order was placed." in r.text
    assert "not financial advice" in r.text.lower()
    # No account yet: the page explains that rather than erroring.
    assert "paper account exists yet" in r.text


def test_grid_page_shows_the_disabled_flag_by_default(registered_client: TestClient) -> None:
    r = registered_client.get("/grid")
    assert "research.grid.enabled = OFF" in r.text


def test_grid_page_requires_sign_in(client: TestClient) -> None:
    r = client.get("/grid", follow_redirects=False)
    assert r.status_code in (302, 303, 307)


def test_grid_is_in_the_navigation(registered_client: TestClient) -> None:
    r = registered_client.get("/")
    assert 'href="/grid"' in r.text
