import json
import os
from datetime import UTC, datetime, timedelta

import pytest

from signalforge.observability.studies import LIMIT, forward_status

NOW = datetime(2026, 11, 4, 23, tzinfo=UTC)


def setup(root):
    (root / "plan.json").write_text(
        json.dumps(
            {
                "schema": "funded-forward-v1",
                "first_observation_session": "2026-11-04",
                "first_entry_session": "2026-11-05",
                "strategies": [{}] * 5,
                "secret": "do-not-display",  # pragma: allowlist secret
            }
        )
    )
    status = root / "status.json"
    status.write_text(
        json.dumps(
            {
                "status": "WAITING_FOR_FIRST_FUTURE_SESSION",
                "secret": "do-not-display",  # pragma: allowlist secret
            }
        )
    )
    os.utime(status, (NOW.timestamp(), NOW.timestamp()))


def test_forward_projection_is_bounded_and_does_not_read_outcomes(tmp_path):
    setup(tmp_path)
    out = forward_status(tmp_path, now=NOW)
    assert out["health"] == "Current" and out["observed_sessions"] == 0
    assert out["books"] == 10 and out["last_success"] is None
    directory = tmp_path / "collections"
    directory.mkdir()
    record = directory / "2026-11-04.json"
    record.write_text("not JSON; must never open or expose interim results")
    os.utime(record, (NOW.timestamp() - 1, NOW.timestamp() - 1))
    before = {p: p.read_bytes() for p in tmp_path.rglob("*.json")}
    out = forward_status(tmp_path, now=NOW)
    assert out["last_session"] == "2026-11-04" and out["observed_sessions"] == 1
    assert "do-not-display" not in json.dumps(out)
    assert {p: p.read_bytes() for p in before} == before
    assert forward_status(tmp_path, now=NOW + timedelta(hours=2))["health"] == "Stale"


@pytest.mark.parametrize("bad", ["secret-value", "{}", "[1]", "x" * (LIMIT + 1)])
def test_bad_status_fails_closed_without_disclosing_body(tmp_path, bad):
    setup(tmp_path)
    (tmp_path / "status.json").write_text(bad)
    out = forward_status(tmp_path, now=NOW)
    assert out["health"].startswith("Unavailable")
    assert "secret-value" not in str(out)


def test_gap_and_future_clock_fail_closed(tmp_path):
    setup(tmp_path)
    assert forward_status(tmp_path, now=NOW - timedelta(hours=1))["health"].startswith(
        "Unavailable"
    )
    d = tmp_path / "collections"
    d.mkdir()
    (d / "2026-11-05.json").touch()
    assert forward_status(tmp_path, now=NOW + timedelta(days=1))["health"].startswith("Unavailable")


def test_success_without_record_is_not_healthy(tmp_path):
    setup(tmp_path)
    status = tmp_path / "status.json"
    status.write_text(json.dumps({"status": "ALREADY_COLLECTED", "through": "2026-11-04"}))
    os.utime(status, (NOW.timestamp(), NOW.timestamp()))
    assert forward_status(tmp_path, now=NOW)["health"].startswith("Unavailable")


def test_route_auth_and_read_only_render(client, registered_client, tmp_path, monkeypatch):
    setup(tmp_path)
    monkeypatch.setenv("FUNDED_FORWARD_STUDY_ROOT", str(tmp_path))
    from signalforge.config.settings import get_settings

    get_settings.cache_clear()
    response = registered_client.get("/research-studies")
    assert response.status_code == 200
    for text in ("Kronos comparison", "Funded forward", "every 60s", "Research signal only"):
        assert text in response.text
    assert "do-not-display" not in response.text
    assert registered_client.post("/research-studies").status_code == 405
    client.cookies.clear()
    assert client.get("/research-studies", follow_redirects=False).status_code == 303
