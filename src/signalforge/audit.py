"""Append-only decision/event log (ARCHITECTURE.md §12).

Phase 0: a JSONL sink under the data dir so early modules (kill switch, CLI) can
record actions before the DB exists. Phase 1 adds an ``audit_log`` table and this
becomes a thin façade that writes to both.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from signalforge.config import paths
from signalforge.observability import redact

_lock = threading.Lock()


def _log_file() -> Path:
    return paths.logs_dir() / "audit.jsonl"


def record(action: str, *, actor: str = "system", entity: str = "", **fields: Any) -> None:
    """Append one audit event. Secrets in ``fields`` are redacted."""
    event = {
        "ts": datetime.now(UTC).isoformat(),
        "actor": actor,
        "action": action,
        "entity": entity,
        "fields": redact(fields),
    }
    line = json.dumps(event, ensure_ascii=False, sort_keys=True)
    with _lock, _log_file().open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
