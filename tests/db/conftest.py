"""Database test fixtures: a fresh SQLite file per test, schema via migrations."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

REPO_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config(url: str) -> Config:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "src/signalforge/db/migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


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
    command.upgrade(_alembic_config(db_url), "head")
    return db_url


@pytest.fixture
def session(migrated_db: str) -> Iterator[Session]:
    from signalforge.db.session import get_sessionmaker

    with get_sessionmaker()() as s:
        yield s
