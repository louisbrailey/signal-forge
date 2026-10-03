from datetime import UTC, date, datetime
from threading import Event

import pytest

from signalforge.scheduler import last_completed_session
from signalforge.worker_health import startup_heartbeat


def test_startup_heartbeat_runs_during_work_and_stops_on_failure():
    beats = []
    second = Event()

    def beat():
        beats.append(1)
        if len(beats) >= 2:
            second.set()

    with pytest.raises(RuntimeError, match="work failed"), startup_heartbeat(beat, interval=0.01):
        assert second.wait(2)
        raise RuntimeError("work failed")
    assert len(beats) >= 2
    import threading

    assert not any(t.name == "startup-heartbeat" for t in threading.enumerate())


def test_holiday_does_not_require_nonexistent_bar():
    assert last_completed_session(datetime(2026, 9, 7, 23, tzinfo=UTC)) == date(2026, 9, 4)


def test_before_publication_cutoff_uses_previous_session():
    assert last_completed_session(datetime(2026, 9, 8, 18, tzinfo=UTC)) == date(2026, 9, 4)
