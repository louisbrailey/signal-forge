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
