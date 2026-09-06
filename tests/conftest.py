"""Shared test fixtures.

Every test runs against an isolated data directory + SQLite database so
kill-switch state, logs, audit files, and rows never leak between tests.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import structlog
from hypothesis import settings as hypothesis_settings
from sqlalchemy.orm import Session

from tests.support import migrate_to_head

# Deterministic property-based testing so CI cannot flake on a newly-found example.
hypothesis_settings.register_profile(
    "deterministic", derandomize=True, max_examples=250, deadline=None
)
hypothesis_settings.load_profile("deterministic")


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("SIGNALFORGE_DATA_DIR", str(tmp_path))
    # TestClient sends Host: testserver; allow it (plus the real defaults) in tests.
    monkeypatch.setenv("APP_ALLOWED_HOSTS", "testserver,localhost,127.0.0.1")

    import signalforge.killswitch as ks
    from signalforge.config.settings import get_settings
    from signalforge.db.session import reset_engine_cache

    monkeypatch.setattr(ks, "_default", None)
    get_settings.cache_clear()
    reset_engine_cache()
    yield tmp_path
    reset_engine_cache()
    get_settings.cache_clear()
    # structlog caches bound loggers; a test that configured logging under capsys
    # would otherwise leave a logger pointing at a closed stream.
    structlog.reset_defaults()


@pytest.fixture
def db_url(isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A migrated SQLite DB inside the isolated data dir."""
    url = f"sqlite+pysqlite:///{isolated_data_dir / 'test.sqlite'}"
    monkeypatch.setenv("DATABASE_URL", url)

    from signalforge.config.settings import get_settings
    from signalforge.db.session import reset_engine_cache

    get_settings.cache_clear()
    reset_engine_cache()
    migrate_to_head(url)
    return url


@pytest.fixture
def session(db_url: str) -> Iterator[Session]:
    from signalforge.db.session import get_sessionmaker

    with get_sessionmaker()() as s:
        yield s
