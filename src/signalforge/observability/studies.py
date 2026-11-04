"""Read-only operational study projection. Never opens reports or outcome books."""

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime
from itertools import islice
from pathlib import Path
from typing import Any

from signalforge.config.settings import get_settings
from signalforge.data.calendar import sessions
from signalforge.kronos.collection_status import collection_status

LIMIT = 262_144
STATES = {
    "WAITING_FOR_FIRST_FUTURE_SESSION": "Waiting for first future session",
    "ALREADY_COLLECTED": "Already collected latest eligible session",
    "COLLECTING_UNVALIDATED": "Collection recorded; evidence not validated",
    "BLOCKED": "Collection blocked — inspect local collector log",
}


def _read(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError("Oversized metadata")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Invalid metadata")
    return value


def forward_status(root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    """Counts file names only; frozen fingerprints remain the pinned collector's job."""
    now = now or datetime.now(UTC)
    result: dict[str, Any] = {"health": "Unavailable", "checked_at": None}
    try:
        plan = _read(root / "plan.json")
        if plan["schema"] != "funded-forward-v1":
            raise ValueError("Unknown study")
        first = date.fromisoformat(plan["first_observation_session"])
        entry = date.fromisoformat(plan["first_entry_session"])
        if first >= entry:
            raise ValueError("Invalid boundaries")
        if not isinstance(plan["strategies"], list):
            raise ValueError("Invalid strategy list")
        count = len(plan["strategies"])
        if not 1 <= count <= 20:
            raise ValueError("Unbounded books")
        result.update(first_observation=str(first), first_entry=str(entry), books=count * 2)
        path = root / "status.json"
        # The legacy collector has no checked_at. Explicitly label filesystem time.
        before = path.stat()
        status = _read(path)
        after = path.stat()
        if before.st_mtime_ns != after.st_mtime_ns or before.st_ino != after.st_ino:
            raise ValueError("Partial collector update")
        checked = datetime.fromtimestamp(after.st_mtime, UTC)
        age = (now - checked).total_seconds()
        if age < -5 or status["status"] not in STATES:
            raise ValueError("Invalid heartbeat")
        files = list(islice((root / "collections").glob("*.json"), 253))
        if len(files) > 252:
            raise ValueError("Collection bound exceeded")
        days = sorted(date.fromisoformat(p.stem) for p in files)
        if days and (
            days[-1] > now.date()
            or not 0 <= (days[-1] - first).days <= 550
            or tuple(days) != sessions(first, days[-1])
        ):
            raise ValueError("Invalid or missing collection session")
        if status["status"] in ("COLLECTING_UNVALIDATED", "ALREADY_COLLECTED") and (
            not days or status.get("through") != str(days[-1])
        ):
            raise ValueError("Successful status has no matching collection record")
        last_time = None
        if days:
            last = root / "collections" / f"{days[-1]}.json"
            last_time = datetime.fromtimestamp(last.stat().st_mtime, UTC)
            if last_time > checked:
                raise ValueError("Collection newer than status; refresh required")
        result.update(
            health=(
                "Stale" if age > 5400 else "Blocked" if status["status"] == "BLOCKED" else "Current"
            ),
            state=STATES[status["status"]],
            checked_at=checked.isoformat(),
            observed_sessions=len(days),
            last_session=str(days[-1]) if days else None,
            last_success=last_time.isoformat() if last_time else None,
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        result.update(health="Unavailable — missing or invalid operational metadata")
    return result


def studies_context() -> dict[str, Any]:
    settings = get_settings()
    root = (
        Path(settings.funded_forward_study_root)
        if settings.funded_forward_study_root
        else Path(os.environ.get("SIGNALFORGE_DATA_DIR", str(Path.cwd() / "data")))
        / "funded-validation-v1"
    )
    return {"kronos": collection_status(), "forward": forward_status(root)}
