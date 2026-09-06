"""Helpers shared across test modules (not fixtures — those live in conftest.py)."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

from alembic import command
from alembic.config import Config

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
PKG_ROOT = SRC_ROOT / "signalforge"


def alembic_config(url: str) -> Config:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PKG_ROOT / "db/migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def migrate_to_head(url: str) -> None:
    command.upgrade(alembic_config(url), "head")


def run_python(code: str) -> subprocess.CompletedProcess[str]:
    """Run ``code`` in a clean interpreter (fresh ``sys.modules``)."""
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )


def iter_source_files(*subpackages: str) -> Iterator[Path]:
    """Yield ``.py`` files under the given subpackages (or the whole package)."""
    roots = [PKG_ROOT / s for s in subpackages] if subpackages else [PKG_ROOT]
    for root in roots:
        yield from sorted(root.rglob("*.py"))
