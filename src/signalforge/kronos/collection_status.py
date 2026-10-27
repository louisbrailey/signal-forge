"""Bounded, read-only projection of collector health; no book or outcome access."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from signalforge.config.settings import get_settings

BOOKS = ("kronos-comparison-v1-short", "kronos-comparison-v1-medium")
LABELS = {
    "waiting_for_postclose_window": "Waiting for the next eligible post-close window",
    "waiting_for_completed_approved_scan": "Waiting for a completed approved scan",
    "waiting_for_successful_scan_job": "Waiting for a successful scan",
    "waiting_for_kronos_runtime": "Waiting for the model runtime",
    "ready": "Ready to collect",
    "complete": "Collection complete",
    "already_collected": "Already collected this session",
    "finalized": "Study finalized",
    "blocked": "Collection blocked",
    "blocked_emergency_stop": "Emergency stop active",
    "blocked_emergency_stop_unavailable": "Emergency-stop state unavailable",
}
MAX_BYTES = 262_144


def _stamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Missing timestamp")
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError("Timestamp must have timezone")
    return stamp.astimezone(UTC)


def collection_status(*, path: Path | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Expose only known statuses and validated times, never arbitrary file text."""
    result: dict[str, Any] = {"health": "Not configured", "checked_at": None, "books": []}
    configured = get_settings().kronos_comparison_status_path
    if path is None:
        if not configured:
            return result
        path = Path(configured)
    now = now or datetime.now(UTC)
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("Oversized metadata")
        data = json.loads(raw)
        checked = _stamp(data["checked_at"])
        age = (now - checked).total_seconds()
        if age < -5:
            raise ValueError("Future heartbeat")
        rows = data["results"]
        transitions = data.get("transitions", [])
        saved_successes = data.get("last_success", {})
        if not isinstance(saved_successes, dict):
            raise ValueError("Malformed success metadata")
        if not isinstance(rows, list) or not isinstance(transitions, list):
            raise ValueError("Malformed metadata")
        if len(rows) > 16 or len(transitions) > 64:
            raise ValueError("Unbounded metadata")
        books = []
        for name in BOOKS:
            matches = [r for r in rows if isinstance(r, dict) and r.get("experiment") == name]
            state = matches[0].get("status") if len(matches) == 1 else None
            if state not in LABELS:
                raise ValueError("Unknown collection status")
            last = None
            session = None
            saved = saved_successes.get(name)
            if saved is not None:
                last = _stamp(saved["at"])
                session = date.fromisoformat(saved["day"]).isoformat()
                if last > checked or date.fromisoformat(session) > last.date():
                    raise ValueError("Future success")
            # Status history is operational evidence; no private book is opened.
            for transition in transitions:
                timestamp = _stamp(transition["at"])
                if timestamp > checked:
                    raise ValueError("Future transition")
                for item in transition["results"]:
                    if item.get("experiment") == name and item.get("status") == "complete":
                        day = date.fromisoformat(item["day"])
                        if day > timestamp.date():
                            raise ValueError("Future session")
                        if last is None or timestamp > last:
                            last, session = timestamp, day.isoformat()
            books.append(
                {
                    "name": name,
                    "status": LABELS[state],
                    "blocked": state.startswith("blocked"),
                    "last_success": last.isoformat() if last else None,
                    "session": session,
                }
            )
        result.update(
            health=(
                "Stale — collector heartbeat overdue"
                if age > 180
                else "Blocked" if any(b["blocked"] for b in books) else "Healthy"
            ),
            checked_at=checked.isoformat(),
            books=books,
        )
    except FileNotFoundError:
        result["health"] = "Unavailable — no collector status file"
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        result["health"] = "Unavailable — invalid collector metadata"
    return result
