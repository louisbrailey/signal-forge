"""Filesystem locations for local-first runtime state.

Everything the app writes at runtime (SQLite DB, logs, raw provider payload
cache, kill-switch state, local secret store, backups) lives under a single data
directory so it is easy to back up and easy to ``.gitignore``.

Resolution order for the data dir:
1. ``SIGNALFORGE_DATA_DIR`` environment variable, if set;
2. ``<current working directory>/data`` otherwise.

The cwd default keeps a checkout self-contained, which is what we want for a
single-user local tool.
"""

from __future__ import annotations

import os
from pathlib import Path

_ENV_VAR = "SIGNALFORGE_DATA_DIR"


def data_dir() -> Path:
    """Return the base data directory, creating it if needed."""
    raw = os.environ.get(_ENV_VAR)
    base = Path(raw).expanduser() if raw else Path.cwd() / "data"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _sub(name: str) -> Path:
    path = data_dir() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    return _sub("logs")


def raw_cache_dir() -> Path:
    """Verbatim provider responses, kept for audit and replay."""
    return _sub("raw_cache")


def backups_dir() -> Path:
    return _sub("backups")


def reports_dir() -> Path:
    """Committed-elsewhere backtest reports also get a local mirror here."""
    return _sub("reports")


def secret_store_path() -> Path:
    """Local encrypted secret store (Fernet, key = APP_ENCRYPTION_KEY)."""
    return data_dir() / "secret_store.enc"


def kill_switch_state_path() -> Path:
    return data_dir() / "kill_switch.json"


def kill_switch_log_path() -> Path:
    return logs_dir() / "kill_switch_events.jsonl"
