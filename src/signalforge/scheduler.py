"""Background job scheduling.

Phase 1: APScheduler in-process (SQLAlchemy jobstore) for ingest / scan /
briefing / feed-health-probe / paper mark-to-market. Every job entrypoint calls
:func:`signalforge.killswitch.ensure_not_engaged` first (invariant S6). Missed
jobs (laptop asleep) are detected and a catch-up run is triggered on wake.

Phase 2: swap to Arq + Redis behind the same ``JobRunner`` protocol.

Phase 0: protocol + a no-op runner so wiring can be tested.
"""

from __future__ import annotations

from typing import Protocol

from signalforge.killswitch import ensure_not_engaged
from signalforge.observability import get_logger

_log = get_logger("scheduler")


class JobRunner(Protocol):
    def submit(self, name: str) -> None: ...


class InlineJobRunner:
    """Runs a named job immediately, guarded by the kill switch. Test/CLI use."""

    def __init__(self, jobs: dict[str, Job] | None = None) -> None:
        self._jobs: dict[str, Job] = jobs or {}

    def register(self, job: Job) -> None:
        self._jobs[job.name] = job

    def submit(self, name: str) -> None:
        ensure_not_engaged()
        job = self._jobs[name]
        _log.info("job.start", job=name)
        job.run()
        _log.info("job.done", job=name)


class Job(Protocol):
    name: str

    def run(self) -> None: ...
