"""Bounded, read-only projection of collector health; no book or outcome access."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from signalforge import study_registry as registry
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


def _project(
    path: Path, names: tuple[str, ...], now: datetime, active: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Expose only known statuses and validated times, never arbitrary file text."""
    result: dict[str, Any] = {"health": "Not configured", "checked_at": None, "books": []}
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("Oversized metadata")
        data = json.loads(raw)
        if active is not None and (
            data.get("generation") != active["generation"]
            or data.get("registry_hash") != active["hash"]
        ):
            raise ValueError("Active heartbeat generation mismatch")
        checked = _stamp(data["checked_at"])
        beginning = _stamp(active["activated_at"]) if active else None
        if beginning and checked < beginning:
            raise ValueError("Heartbeat predates activation")
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
        if active and (len(rows) != len(names) or {r["experiment"] for r in rows} != set(names)):
            raise ValueError("Heartbeat active study set mismatch")
        books = []
        for name in names:
            first = (
                date.fromisoformat(
                    next(
                        e["first_observation_session"]
                        for e in active["active"]
                        if e["name"] == name
                    )
                )
                if active
                else None
            )
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
                if beginning and last < beginning:
                    raise ValueError("Success predates active generation")
                if first and date.fromisoformat(session) < first:
                    raise ValueError("Success predates first prospective session")
            # Status history is operational evidence; no private book is opened.
            for transition in transitions:
                timestamp = _stamp(transition["at"])
                if timestamp > checked:
                    raise ValueError("Future transition")
                if not isinstance(transition["results"], list) or len(transition["results"]) > 16:
                    raise ValueError("Unbounded transition metadata")
                if beginning and timestamp < beginning:
                    raise ValueError("Transition predates active generation")
                for item in transition["results"]:
                    if item.get("experiment") == name and item.get("status") == "complete":
                        day = date.fromisoformat(item["day"])
                        if day > timestamp.date():
                            raise ValueError("Future session")
                        if first and day < first:
                            raise ValueError("Transition predates first prospective session")
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


def _forward_status(snapshot: dict[str, Any], now: datetime) -> dict[str, Any]:
    entry = next(e for e in snapshot["active"] if e["kind"] == "forward")
    result: dict[str, Any] = {
        "name": entry["name"],
        "start": entry["first_observation_session"],
        "health": "Unavailable — no active forward heartbeat",
        "checked_at": None,
    }
    labels = {
        "WAITING_FOR_FIRST_FUTURE_SESSION": "Waiting for first future session",
        "ALREADY_COLLECTED": "Already collected this session",
        "COLLECTING_UNVALIDATED": "Collecting unvalidated future evidence",
        "BLOCKED": "Collection blocked",
        "READY_FOR_COLLECTION": "Ready for collection",
    }
    try:
        data = registry.read_json(Path(snapshot["forward_status_path"]))
        if (
            data.get("generation") != snapshot["generation"]
            or data.get("registry_hash") != snapshot["hash"]
        ):
            raise ValueError("Forward generation mismatch")
        if data.get("study_name") != entry["name"] or data["status"] not in labels:
            raise ValueError("Unknown forward operational identity/status")
        checked = registry.timestamp(data["checked_at"])
        age = (now - checked).total_seconds()
        if age < -5 or checked < registry.timestamp(snapshot["activated_at"]):
            raise ValueError("Invalid forward heartbeat time")
        result.update(
            checked_at=checked.isoformat(),
            health=("Stale — forward heartbeat overdue" if age > 3900 else labels[data["status"]]),
        )
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        pass
    return result


def collection_status(
    *, path: Path | None = None, now: datetime | None = None, registry_path: Path | None = None
) -> dict[str, Any]:
    """An active registry takes precedence; invalid v2 never falls back to v1."""
    now = now or datetime.now(UTC)
    settings = get_settings()
    configured = registry_path or (
        Path(settings.study_active_registry_path) if settings.study_active_registry_path else None
    )
    if configured is None:
        legacy = path or (
            Path(settings.kronos_comparison_status_path)
            if settings.kronos_comparison_status_path
            else None
        )
        result = (
            _project(legacy, BOOKS, now)
            if legacy
            else {"health": "Not configured", "books": [], "checked_at": None}
        )
        result.update(mode="legacy", generation=1, archive=[], forward=None, release_sha=None)
        return result
    result = {
        "health": "Unavailable — invalid active registry",
        "books": [],
        "checked_at": None,
        "mode": "active",
        "generation": None,
        "archive": [],
        "forward": None,
        "release_sha": None,
    }
    try:
        snapshot = registry.load_registry(configured)
        if registry.timestamp(snapshot["activated_at"]) > now:
            raise ValueError("Future activation")
        names = tuple(e["name"] for e in snapshot["active"] if e["kind"] == "kronos")
        result.update(_project(Path(snapshot["status_path"]), names, now, snapshot))
        result.update(
            generation=snapshot["generation"],
            release_sha=snapshot["release_sha"],
            forward=_forward_status(snapshot, now),
        )
        forward_health = result["forward"]["health"]
        if result["health"] == "Healthy" and (
            forward_health.startswith(("Unavailable", "Stale"))
            or forward_health == "Collection blocked"
        ):
            result["health"] = "Degraded — active forward collector unavailable"
        identities = {e["name"]: e for e in snapshot["active"]}
        for book in result["books"]:
            entry = identities[book["name"]]
            book.update(
                start=entry["first_observation_session"], request_hash=entry["request_hash"]
            )
        result["archive"] = [
            dict(
                _project(Path(a["status_path"]), tuple(a["names"]), now), generation=a["generation"]
            )
            for a in snapshot["archive"]
        ]
        registry.assert_current(configured, snapshot)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        result.update(
            health="Unavailable — invalid active registry", books=[], archive=[], forward=None
        )
    return result
