"""Database test fixtures: a fresh SQLite file per test, schema via migrations."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from tests.support import migrate_to_head


@pytest.fixture
def db_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    url = f"sqlite+pysqlite:///{tmp_path / 'test.sqlite'}"
    monkeypatch.setenv("DATABASE_URL", url)

    from signalforge.config.settings import get_settings
    from signalforge.db.session import reset_engine_cache

    get_settings.cache_clear()
    reset_engine_cache()
    yield url
    reset_engine_cache()
    get_settings.cache_clear()


@pytest.fixture
def migrated_db(db_url: str) -> str:
    migrate_to_head(db_url)
    return db_url


@pytest.fixture
def session(migrated_db: str) -> Iterator[Session]:
    from signalforge.db.session import get_sessionmaker

    with get_sessionmaker()() as s:
        yield s
