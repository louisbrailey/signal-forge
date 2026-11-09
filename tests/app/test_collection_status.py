import json
from datetime import UTC, datetime, timedelta

import pytest

from signalforge.kronos.collection_status import BOOKS, collection_status

NOW = datetime(2026, 10, 27, 0, 15, tzinfo=UTC)


def metadata():
    return {
        "checked_at": NOW.isoformat(),
        "results": [
            {"experiment": name, "status": "waiting_for_postclose_window"} for name in BOOKS
        ],
        "transitions": [
            {
                "at": "2026-10-26T22:39:12+00:00",
                "results": [
                    {
                        "experiment": name,
                        "status": "complete",
                        "day": "2026-10-26",
                        "pnl": "DO_NOT_RENDER",
                    }
                    for name in BOOKS
                ],
            }
        ],
        "unapproved_payload": "DO_NOT_RENDER",
    }


def test_status_preserves_success_during_wait_without_exposing_other_fields(tmp_path):
    path = tmp_path / "status.json"
    path.write_text(json.dumps(metadata()))
    status = collection_status(path=path, now=NOW)
    assert status["health"] == "Healthy"
    assert len(status["books"]) == 2
    assert all(b["last_success"] == "2026-10-26T22:39:12+00:00" for b in status["books"])
    assert "DO_NOT_RENDER" not in json.dumps(status)
    assert "Stale" in collection_status(path=path, now=NOW + timedelta(minutes=4))["health"]


@pytest.mark.parametrize("kind", ["future", "naive", "malformed", "oversized", "unknown"])
def test_invalid_status_fails_visibly_without_file_contents(tmp_path, kind):
    path = tmp_path / "status.json"
    data = metadata()
    if kind == "future":
        data["checked_at"] = (NOW + timedelta(days=1)).isoformat()
    elif kind == "naive":
        data["checked_at"] = "2026-10-27T00:15:00"
    elif kind == "unknown":
        data["results"][0]["status"] = "DO_NOT_RENDER"
    path.write_text(
        "DO_NOT_RENDER"
        if kind == "malformed"
        else "x" * 262_145 if kind == "oversized" else json.dumps(data)
    )
    status = collection_status(path=path, now=NOW)
    assert "Unavailable" in status["health"]
    assert status["books"] == []
    assert "DO_NOT_RENDER" not in json.dumps(status)


def test_missing_status_and_page(registered_client, tmp_path, monkeypatch):
    from signalforge.app.routers import kronos

    assert "Unavailable" in collection_status(path=tmp_path / "missing", now=NOW)["health"]
    path = tmp_path / "status.json"
    path.write_text(json.dumps(metadata()))
    monkeypatch.setattr(kronos, "collection_status", lambda: collection_status(path=path, now=NOW))
    response = registered_client.get("/kronos")
    assert response.status_code == 200
    assert "Comparison books · automatic collection" in response.text
    assert "2026-10-26T22:39:12+00:00" in response.text
    assert "DO_NOT_RENDER" not in response.text
    assert 'id="collection-panel"' in response.text


def test_persisted_success_survives_transition_retention(tmp_path):
    from tests.experiments.test_collector import collector

    path = tmp_path / "status.json"
    data = metadata()
    path.write_text(json.dumps(data))
    collector.save_status(path, data["results"])
    saved = json.loads(path.read_text())
    saved["transitions"] = []
    path.write_text(json.dumps(saved))
    status = collection_status(path=path)
    assert len(status["books"]) == 2
    assert all(b["session"] == "2026-10-26" for b in status["books"])


@pytest.fixture
def active_registry(tmp_path):
    from signalforge import study_registry as registry

    entries = []
    for kind, name in (
        ("kronos", "kronos-comparison-v2-short"),
        ("kronos", "kronos-comparison-v2-medium"),
        ("forward", "funded-validation-v2"),
    ):
        entries.append(
            {
                "kind": kind,
                "name": name,
                "directory": str(tmp_path / name),
                "request_hash": "1" * 64,
                "metadata_sha256": "2" * 64,
                "code_digest": "3" * 64,
                "config_sha256": "4" * 64,
                "modelweights_sha256": "5" * 64 if kind == "kronos" else None,
                "first_observation_session": "2026-10-27",
            }
        )
    old = tmp_path / "legacy-state" / "status.json"
    old.parent.mkdir()
    old.write_text(json.dumps(metadata()))
    active_status = tmp_path / "active-state" / "status.json"
    active_status.parent.mkdir()
    data = {
        "schema": registry.SCHEMA,
        "generation": 2,
        "activated_at": (NOW - timedelta(minutes=10)).isoformat(),
        "release_sha": "a" * 40,
        "active": entries,
        "status_path": str(active_status),
        "forward_status_path": str(tmp_path / "funded-validation-v2/status.json"),
        "archive": [{"generation": 1, "names": list(BOOKS), "status_path": str(old)}],
    }
    data["hash"] = registry.digest(data)
    path = tmp_path / "active.json"
    registry.atomic_json(path, data)
    heartbeat = {
        "checked_at": NOW.isoformat(),
        "generation": 2,
        "registry_hash": data["hash"],
        "results": [
            {"experiment": e["name"], "status": "ready"} for e in entries if e["kind"] == "kronos"
        ],
        "pnl": "DO_NOT_RENDER",
    }
    active_status.write_text(json.dumps(heartbeat))
    return path, data, active_status, heartbeat, old


@pytest.mark.parametrize(
    "fault", ["missing", "generation", "identity", "hash", "stale", "oversized"]
)
def test_active_v2_never_falls_back_to_healthy_v1(active_registry, fault):
    path, _, status_path, heartbeat, old = active_registry
    if fault == "missing":
        status_path.unlink()
    elif fault == "oversized":
        status_path.write_text("x" * 262145)
    else:
        if fault == "generation":
            heartbeat["generation"] = 1
        elif fault == "identity":
            heartbeat["results"][0]["experiment"] = BOOKS[0]
        elif fault == "hash":
            heartbeat["registry_hash"] = "0" * 64
        elif fault == "stale":
            heartbeat["checked_at"] = (NOW - timedelta(minutes=4)).isoformat()
        status_path.write_text(json.dumps(heartbeat))
    result = collection_status(path=old, registry_path=path, now=NOW)
    assert result["mode"] == "active" and result["generation"] == 2
    assert result["health"] != "Healthy"
    assert result["archive"][0]["health"] == "Healthy"
    assert all(b["name"].startswith("kronos-comparison-v2-") for b in result["books"])
    assert "DO_NOT_RENDER" not in json.dumps(result)


@pytest.mark.parametrize(
    "fault", ["missing", "checksum", "oversized", "duplicate", "path", "future"]
)
def test_bad_registry_is_visible_and_never_uses_legacy(active_registry, fault):
    from signalforge import study_registry as registry

    path, data, _, _, old = active_registry
    if fault == "missing":
        path.unlink()
    elif fault == "oversized":
        path.write_text("x" * (registry.MAX_BYTES + 1))
    else:
        if fault == "checksum":
            data["hash"] = "0" * 64
        else:
            if fault == "duplicate":
                data["active"][1] = data["active"][0]
            elif fault == "path":
                data["status_path"] = "relative/status.json"
            elif fault == "future":
                data["activated_at"] = (NOW + timedelta(days=1)).isoformat()
            data["hash"] = registry.digest({k: v for k, v in data.items() if k != "hash"})
        path.write_text(json.dumps(data))
    result = collection_status(path=old, registry_path=path, now=NOW)
    assert "Unavailable" in result["health"] and result["books"] == []
    assert result["mode"] == "active"


def test_dashboard_and_json_separate_active_and_archive(
    active_registry, registered_client, monkeypatch
):
    from signalforge.app.routers import kronos

    path, _, _, _, _ = active_registry
    monkeypatch.setattr(
        kronos, "collection_status", lambda: collection_status(registry_path=path, now=NOW)
    )
    response = registered_client.get("/kronos")
    assert response.status_code == 200
    html = response.text
    assert "Generation 2" in html and "Archived generation 1" in html
    active_html, archive_html = html.split('<details id="archived-study-status">')
    assert "kronos-comparison-v2-short" in active_html
    assert "kronos-comparison-v1-short" not in active_html
    assert "kronos-comparison-v1-short" in archive_html
    assert "DO_NOT_RENDER" not in html
    api = registered_client.get("/kronos/collection-status")
    assert api.status_code == 200 and api.json()["generation"] == 2
    assert "DO_NOT_RENDER" not in api.text


def test_prior_session_success_cannot_enter_new_generation(active_registry):
    path, data, status_path, heartbeat, _ = active_registry
    name = data["active"][0]["name"]
    heartbeat["last_success"] = {name: {"at": NOW.isoformat(), "day": "2026-10-26"}}
    status_path.write_text(json.dumps(heartbeat))
    result = collection_status(registry_path=path, now=NOW)
    assert "Unavailable" in result["health"] and result["books"] == []


def test_missing_forward_active_heartbeat_is_visibly_degraded(active_registry):
    path, _, _, _, _ = active_registry
    result = collection_status(registry_path=path, now=NOW)
    assert "Degraded" in result["health"]
    assert "Unavailable" in result["forward"]["health"]
