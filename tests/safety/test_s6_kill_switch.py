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
from signalforge.scheduler import guarded

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


def test_scheduler_jobs_noop_when_engaged(isolated_data_dir: Path) -> None:
    ran: list[str] = []
    job = guarded("demo", lambda: ran.append("ran"))

    job()
    assert ran == ["ran"]

    get_kill_switch().engage(reason="halt", actor="pytest")
    job()  # guarded: logs + returns, does not raise, does not run
    assert ran == ["ran"]


def test_api_guarded_route_returns_423_when_engaged(isolated_data_dir: Path) -> None:
    from signalforge.app.main import create_app

    client = TestClient(create_app())
    assert client.post("/api/_demo/guarded").status_code == 200

    client.post("/api/killswitch/engage", json={"reason": "manual halt", "actor": "pytest"})
    assert client.post("/api/_demo/guarded").status_code == 423

    client.post("/api/killswitch/release", json={"reason": "resume", "actor": "pytest"})
    assert client.post("/api/_demo/guarded").status_code == 200


@pytest.mark.parametrize(
    "raw",
    [
        b"{",
        b"null",
        b"[]",
        b"false",
        b"\xff",
        b'{"active": 0, "changed_at": "2026-10-26T00:00:00+00:00"}',
        b'{"active": "false", "changed_at": "2026-10-26T00:00:00+00:00"}',
        b'{"active": false, "changed_at": null}',
        b'{"active": false, "changed_at": "2026-10-26T00:00:00"}',
    ],
)
def test_invalid_state_blocks_and_explicit_release_recovers(tmp_path: Path, raw: bytes) -> None:
    path = tmp_path / "kill.json"
    path.write_bytes(raw)
    ks = KillSwitch(path, tmp_path / "events.jsonl")
    before = path.read_bytes()
    with pytest.raises(KillSwitchEngaged):
        ensure_not_engaged(ks)
    assert path.read_bytes() == before  # reading does not repair or overwrite evidence
    ks.release("operator repaired state", actor="pytest")
    assert not ks.is_active()


def test_unreadable_state_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ks = KillSwitch(tmp_path / "kill.json")

    def denied(*args: object, **kwargs: object) -> str:
        raise PermissionError("private content must not be logged")

    monkeypatch.setattr(Path, "read_text", denied)
    with pytest.raises(KillSwitchEngaged, match="unreadable"):
        ensure_not_engaged(ks)
