"""S6 — the kill switch halts guarded paths immediately."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from signalforge.killswitch import (
    KillSwitch,
    KillSwitchEngaged,
    ensure_not_engaged,
    get_kill_switch,
)
from signalforge.scheduler import InlineJobRunner

pytestmark = pytest.mark.safety


def test_default_state_is_inactive(isolated_data_dir: Path) -> None:
    assert get_kill_switch().is_active() is False


def test_engage_release_roundtrip_and_event_log(isolated_data_dir: Path) -> None:
    ks = KillSwitch()
    ks.engage(reason="test halt", actor="pytest")
    assert ks.is_active() is True
    assert ks.state().reason == "test halt"
    ks.release(reason="test resume", actor="pytest")
    assert ks.is_active() is False

    log_lines = (isolated_data_dir / "logs" / "kill_switch_events.jsonl").read_text().splitlines()
    assert len(log_lines) == 2
    assert json.loads(log_lines[0])["active"] is True
    assert json.loads(log_lines[1])["active"] is False


def test_ensure_not_engaged_raises_when_active(isolated_data_dir: Path) -> None:
    get_kill_switch().engage(reason="halt", actor="pytest")
    with pytest.raises(KillSwitchEngaged):
        ensure_not_engaged()


def test_scheduler_refuses_jobs_when_engaged(isolated_data_dir: Path) -> None:
    ran: list[str] = []

    class _Job:
        name = "demo"

        def run(self) -> None:
            ran.append("ran")

    runner = InlineJobRunner()
    runner.register(_Job())
    get_kill_switch().engage(reason="halt", actor="pytest")
    with pytest.raises(KillSwitchEngaged):
        runner.submit("demo")
    assert ran == []


def test_api_guarded_route_returns_423_when_engaged(isolated_data_dir: Path) -> None:
    from signalforge.app.main import create_app

    client = TestClient(create_app())
    assert client.post("/api/_demo/guarded").status_code == 200

    client.post("/api/killswitch/engage", json={"reason": "manual halt", "actor": "pytest"})
    assert client.post("/api/_demo/guarded").status_code == 423

    client.post("/api/killswitch/release", json={"reason": "resume", "actor": "pytest"})
    assert client.post("/api/_demo/guarded").status_code == 200
