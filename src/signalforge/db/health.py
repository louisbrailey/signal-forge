"""Lightweight DB health checks for ``/readyz``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import text

from signalforge.db.session import get_engine

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _expected_head() -> str | None:
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config()
        cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
        heads = ScriptDirectory.from_config(cfg).get_heads()
        return heads[0] if len(heads) == 1 else None
    except Exception:  # pragma: no cover - alembic import/parse issues
        return None


def check_db() -> dict[str, Any]:
    """Return a JSON-safe status dict; never raises."""
    result: dict[str, Any] = {
        "connected": False,
        "current_revision": None,
        "expected_head": _expected_head(),
        "at_head": False,
        "error": None,
    }
    try:
        engine = get_engine()
        with engine.connect() as conn:
            result["connected"] = True
            row = conn.execute(text("SELECT version_num FROM alembic_version")).first()
            current = row[0] if row else None
            result["current_revision"] = current
            result["at_head"] = current is not None and current == result["expected_head"]
    except Exception as exc:  # health check must not raise
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result
