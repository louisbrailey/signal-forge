"""App test fixtures: a TestClient backed by a migrated, isolated SQLite DB."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.support import migrate_to_head


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    url = f"sqlite+pysqlite:///{tmp_path / 'app.sqlite'}"
    monkeypatch.setenv("DATABASE_URL", url)

    from signalforge.config.settings import get_settings
    from signalforge.db.session import reset_engine_cache

    get_settings.cache_clear()
    reset_engine_cache()
    migrate_to_head(url)

    from signalforge.app.main import create_app

    with TestClient(create_app(), base_url="http://localhost") as c:
        yield c

    reset_engine_cache()
    get_settings.cache_clear()


@pytest.fixture
def registered_client(client: TestClient) -> TestClient:
    """A client that has completed first-run registration and is signed in."""
    resp = client.post(
        "/register",
        data={
            "username": "trader",
            "password": "correct horse battery",
            "csrf_token": _csrf(client, "/register"),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text
    return client


def _csrf(client: TestClient, path: str) -> str:
    html = client.get(path).text
    marker = 'name="csrf_token" value="'
    start = html.index(marker) + len(marker)
    return html[start : html.index('"', start)]
