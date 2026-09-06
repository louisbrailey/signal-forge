"""Shared test fixtures.

Every test runs against an isolated data directory so kill-switch state, logs, and
audit files never leak between tests or into the real ``data/`` dir.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import structlog


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("SIGNALFORGE_DATA_DIR", str(tmp_path))
    # TestClient sends Host: testserver; allow it (plus the real defaults) in tests.
    monkeypatch.setenv("APP_ALLOWED_HOSTS", "testserver,localhost,127.0.0.1")

    # Reset cached singletons / config that may bind to the previous env.
    import signalforge.killswitch as ks
    from signalforge.config.settings import get_settings

    monkeypatch.setattr(ks, "_default", None)
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()
    # structlog caches bound loggers; a test that configured logging under capsys
    # would otherwise leave a logger pointing at a closed stream.
    structlog.reset_defaults()
