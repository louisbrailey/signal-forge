from contextlib import contextmanager
from datetime import UTC, date, datetime

import pytest
from scripts import resume_intraday_backfill as runner

from signalforge.db.models import IngestionRun
from signalforge.domain import FeedType
from signalforge.killswitch import KillSwitchEngaged, KillSwitchState


@pytest.fixture
def run(session, monkeypatch):
    row = IngestionRun(
        provider="fixture",
        feed_type=FeedType.BAR_INTRADAY,
        requested_start=date(2020, 1, 1),
        requested_end=date(2021, 1, 1),
        symbols_requested=["AAPL", "SPY"],
        symbols_ok=["AAPL"],
        status="running",
        notes="intraday 15m RTH-only backfill — fixture",
        started_at=datetime.now(UTC),
    )
    session.add(row)
    session.commit()

    @contextmanager
    def scope(*, write=False):
        assert not write
        yield session

    monkeypatch.setattr(runner, "session_scope", scope)
    return row


def test_resume_uses_recorded_scope_and_no_shell(run, monkeypatch):
    calls = []

    def fake_exec(executable, args):
        calls.append((executable, args))
        raise SystemExit(0)

    monkeypatch.setattr(runner.os, "execv", fake_exec)
    with pytest.raises(SystemExit):
        runner.resume(run.id, "15m")
    executable, args = calls[0]
    assert args[-8:] == [
        "--since",
        "2020-01-01",
        "--until",
        "2021-01-01",
        "--symbols",
        "AAPL,SPY",
        "--resume-run-id",
        str(run.id),
    ]
    assert executable == args[0]


def test_complete_and_kill_switch_never_launch(run, monkeypatch):
    monkeypatch.setattr(runner.os, "execv", lambda *a, **kw: pytest.fail("unexpected launch"))
    run.status = "ok"
    run.symbols_ok = ["AAPL", "SPY"]
    assert runner.resume(run.id, "15m") == 0
    monkeypatch.setattr(
        runner,
        "ensure_not_engaged",
        lambda: (_ for _ in ()).throw(
            KillSwitchEngaged(KillSwitchState(True, "stopped", "test", datetime.now(UTC)))
        ),
    )
    assert runner.resume(run.id, "15m") == 0


def test_wrong_scope_is_rejected(run, monkeypatch):
    monkeypatch.setattr(runner.os, "execv", lambda *a, **kw: pytest.fail("unexpected launch"))
    with pytest.raises(ValueError, match="Bar size"):
        runner.resume(run.id, "5m")
    run.provider = "other"
    with pytest.raises(ValueError, match="provider"):
        runner.resume(run.id, "15m")


def test_overlapping_poll_does_not_launch(run, monkeypatch, isolated_data_dir):
    import fcntl

    monkeypatch.setattr(runner.os, "execv", lambda *a, **kw: pytest.fail("unexpected launch"))
    with (isolated_data_dir / f"intraday-backfill-{run.id}.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert runner.resume(run.id, "15m") == 0
