"""Exactly one scheduler worker per database."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from signalforge.worker_lock import WorkerAlreadyRunning, acquire_worker_lock, lock_path


def test_second_worker_is_refused_until_the_first_releases(isolated_data_dir: Path) -> None:
    first = acquire_worker_lock()
    assert lock_path().read_text().strip().isdigit()
    with pytest.raises(WorkerAlreadyRunning, match="already holds"):
        acquire_worker_lock()
    first.release()
    second = acquire_worker_lock()
    second.release()


def test_run_scheduler_refuses_to_start_when_the_lock_is_held(
    db_url: str, isolated_data_dir: Path
) -> None:
    from signalforge.cli import app

    held = acquire_worker_lock()
    try:
        result = CliRunner().invoke(app, ["run-scheduler"])
    finally:
        held.release()
    assert result.exit_code == 1
    assert "refusing to start" in result.output and "already holds" in result.output


def test_embedded_api_scheduler_does_not_start_when_a_worker_holds_the_lock(
    db_url: str, isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import signalforge.scheduler as sched

    monkeypatch.setenv("APP_RUN_SCHEDULER", "true")
    started: list[str] = []
    monkeypatch.setattr(sched, "run_catch_up", lambda: started.append("catch_up"))
    held = acquire_worker_lock()
    try:
        from fastapi.testclient import TestClient

        from signalforge.app.main import create_app

        with TestClient(create_app()) as client:
            assert client.get("/healthz").status_code == 200
    finally:
        held.release()
    assert started == []  # the API refused to run a second scheduler
