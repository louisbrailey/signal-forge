"""Offline orchestration tests; source observations here are synthetic fixtures."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

import pytest
from freezegun import freeze_time
from scripts import kronos_comparison_collect as collector
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from tests.experiments.test_comparison import add_candidate, fake_forecast
from tests.experiments.test_comparison import experiment as experiment

from signalforge.db.models import AuditLog, JobRun
from signalforge.experiments import comparison as c

NOW = datetime(2026, 10, 26, 21, tzinfo=UTC)


def ready_source(
    experiment, *, job_status="ok", readiness=True, horizon="SHORT_SWING", versions=None
):
    source, directory, _, _ = experiment
    (source.parent / "kill_switch.json").write_text(
        json.dumps(
            {"active": False, "reason": "test", "actor": "test", "changed_at": NOW.isoformat()}
        )
    )
    add_candidate(source)
    engine = create_engine("sqlite:///" + str(source))
    with Session(engine) as s, s.begin():
        s.add(
            JobRun(
                name="approved_scope_scan",
                started_at=NOW.replace(hour=20, minute=9),
                finished_at=NOW.replace(hour=20, minute=20),
                status=job_status,
            )
        )
        s.add(
            AuditLog(
                ts=NOW.replace(hour=20, minute=15),
                actor="scheduler",
                action="approved_scope_scan.completed",
                before_json={},
                after_json={
                    "readiness_enforced": readiness,
                    "runs": [
                        {
                            "scan_run_id": 1,
                            "source": "massive",
                            "horizon": horizon,
                            "dataset_snapshot_id": 1,
                            "strategy_version_ids": versions or [1],
                        }
                    ],
                },
            )
        )
    engine.dispose()
    return source, directory


def test_completed_zero_candidate_scan_triggers(experiment):
    source, directory = ready_source(experiment)
    with sqlite3.connect(source) as db:
        db.execute("DELETE FROM candidate")
    result = collector.trigger(directory, NOW)
    assert result["status"] == "ready"
    assert result["scan_ids"] == [1]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"job_status": "running"},
        {"job_status": "failed"},
        {"readiness": False},
        {"horizon": "MEDIUM_SWING"},
        {"versions": [999]},
        {"versions": "1"},
    ],
)
def test_incomplete_failed_or_wrong_scope_never_triggers(experiment, kwargs):
    _, directory = ready_source(experiment, **kwargs)
    assert collector.trigger(directory, NOW)["status"].startswith("waiting")


def test_no_market_close_no_dispatch(experiment, monkeypatch):
    _, directory = ready_source(experiment)
    monkeypatch.setattr(collector, "advance", lambda *args: pytest.fail("market still open"))
    assert (
        collector.poll([directory], now=NOW.replace(hour=19))[0]["status"]
        == "waiting_for_postclose_window"
    )


def test_initial_absence_matches_runner_but_invalid_or_active_stop_blocks(experiment):
    source, directory, _, _ = experiment
    assert collector.trigger(directory, NOW)["status"] == "waiting_for_completed_approved_scan"
    (source.parent / "kill_switch.json").write_text("invalid-json")
    assert collector.trigger(directory, NOW)["status"] == "blocked_emergency_stop_unavailable"
    (source.parent / "kill_switch.json").write_text('{"active":true}')
    assert collector.trigger(directory, NOW)["status"] == "blocked_emergency_stop"


def test_poll_collects_once_and_preserves_source(experiment, monkeypatch):
    source, directory = ready_source(experiment)
    before = c.file_hash(source)
    monkeypatch.setattr(c, "forecast", fake_forecast)
    monkeypatch.setattr(collector, "runtime_busy", lambda: False)
    with freeze_time(NOW):
        assert collector.poll([directory])[0]["status"] == "complete"
        assert collector.poll([directory])[0]["status"] == "already_collected"
    assert c.file_hash(source) == before
    with sqlite3.connect(directory / "books.sqlite") as db:
        assert db.execute("SELECT COUNT(*) FROM paper_position").fetchone()[0] == 3
        assert db.execute("SELECT COUNT(*) FROM comparison_forecast").fetchone()[0] == 1


def test_latest_failed_job_cannot_reuse_previous_success(experiment):
    source, directory = ready_source(experiment)
    with sqlite3.connect(source) as db:
        db.execute(
            "INSERT INTO job_run(name,started_at,finished_at,status,detail) VALUES (?,?,?,?,?)",
            ("approved_scope_scan", "2026-10-26 20:30:00", "2026-10-26 20:40:00", "failed", ""),
        )
    assert collector.trigger(directory, NOW)["status"] == "waiting_for_successful_scan_job"


def test_future_completed_timestamp_never_triggers(experiment):
    source, directory = ready_source(experiment)
    with sqlite3.connect(source) as db:
        db.execute("UPDATE job_run SET finished_at='2026-10-27 21:00:00'")
    assert collector.trigger(directory, NOW)["status"] == "waiting_for_successful_scan_job"


def test_missing_audit_never_triggers(experiment):
    source, directory = ready_source(experiment)
    with sqlite3.connect(source) as db:
        db.execute("DELETE FROM audit_log")
    assert collector.trigger(directory, NOW)["status"] == "waiting_for_completed_approved_scan"


def test_runtime_busy_does_not_reserve_inference(experiment, monkeypatch):
    _, directory = ready_source(experiment)
    monkeypatch.setattr(collector, "runtime_busy", lambda: True)
    monkeypatch.setattr(collector, "advance", lambda *args: pytest.fail("must defer"))
    assert collector.poll([directory], now=NOW)[0]["status"] == "waiting_for_kronos_runtime"
    with sqlite3.connect(directory / "books.sqlite") as db:
        assert db.execute("SELECT COUNT(*) FROM comparison_attempt").fetchone()[0] == 0


def test_errors_are_sanitized_and_backed_off(experiment, monkeypatch):
    _, directory = ready_source(experiment)
    monkeypatch.setattr(collector, "runtime_busy", lambda: False)

    def fail(*args):
        raise ValueError("SENTINEL_DO_NOT_EXPOSE")

    monkeypatch.setattr(collector, "advance", fail)
    with freeze_time(NOW):
        result = collector.poll([directory])
    assert "SENTINEL" not in json.dumps(result)
    assert result[0]["error_category"] == "ValueError"
    monkeypatch.setattr(collector, "trigger", lambda *args: pytest.fail("backoff required"))
    assert collector.poll([directory], now=NOW, previous={directory.name: result[0]}) == result


def test_status_history_is_bounded_private_and_deduplicated(tmp_path):
    path = tmp_path / "status.json"
    for i in range(80):
        collector.save_status(
            path, [{"experiment": "short", "status": str(i), "checked_at": "now"}]
        )
    collector.save_status(path, [{"experiment": "short", "status": "79", "checked_at": "later"}])
    assert len(json.loads(path.read_text())["transitions"]) == 64
    assert path.stat().st_mode & 0o777 == 0o600


def test_captured_batch_can_resume_without_retriggering_scan(experiment):
    _, directory, _, _ = experiment
    with sqlite3.connect(directory / "books.sqlite") as db:
        db.execute("INSERT INTO comparison_batch VALUES (?,?,?)", ("2026-10-26", "captured", "{}"))
    result = collector.trigger(directory, NOW.replace(day=27, hour=1))
    assert result["reason"] == "resume_captured_batch"


def test_after_utc_deadline_does_not_create_new_batch(experiment, monkeypatch):
    _, directory = ready_source(experiment)
    monkeypatch.setattr(collector, "advance", lambda *args: pytest.fail("late new admission"))
    assert (
        collector.poll([directory], now=NOW.replace(day=27, hour=1))[0]["status"]
        == "waiting_for_postclose_window"
    )


def test_launch_agent_is_separate_and_uses_pinned_imports():
    import plistlib
    from pathlib import Path

    job = plistlib.loads(
        (
            Path(__file__).parents[2] / "deploy/launchd/com.signalforge.kronos-comparison.plist"
        ).read_bytes()
    )
    assert job["Label"] not in {
        "com.signalforge.worker",
        "com.signalforge.api",
        "com.signalforge.kronos",
    }
    assert job["StartInterval"] == 60 and job["RunAtLoad"] is True
    args = job["ProgramArguments"]
    checkout = Path(args[args.index("--checkout") + 1])
    assert job["EnvironmentVariables"]["PYTHONPATH"] == str(checkout / "src")
    assert not any("KEY" in k or "TOKEN" in k for k in job["EnvironmentVariables"])
    assert "--check-only" not in args
    assert args.count("--experiment") == 2
