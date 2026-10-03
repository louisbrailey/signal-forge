"""Keep startup liveness visible while a bounded provider catch-up is running."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager


@contextmanager
def startup_heartbeat(beat: Callable[[], None], interval: float = 30.0) -> Iterator[None]:
    """Pulse during synchronous catch-up; stop before scheduled heartbeats take over.

    The callback must be best-effort (the scheduler's record_heartbeat is). This
    reports liveness only, never data readiness or success of an ingestion job.
    """
    if interval <= 0:
        raise ValueError("heartbeat interval must be positive")
    stopped = threading.Event()

    def pulse() -> None:
        while not stopped.wait(interval):
            beat()

    thread = threading.Thread(target=pulse, name="startup-heartbeat", daemon=True)
    beat()
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join()
