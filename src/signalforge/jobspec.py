"""The scheduler's job specification, as a leaf module.

Lives apart from :mod:`signalforge.scheduler` so that a job *supplier* (the
order-execution cycle, injected from the CLI) can describe a job without
importing the scheduler module itself — which imports the agents, alerts and
briefing layers that the execution layer is forbidden (S15a) from reaching.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

JobFn = Callable[[], None]


@dataclass(frozen=True, slots=True)
class JobSpec:
    name: str
    fn: JobFn
    interval_minutes: int
    description: str
    # When set, the job runs on this daily wall-clock time in ``cron_tz`` instead
    # of a fixed interval (used for the single post-close end-of-day update).
    cron_hour: int | None = None
    cron_minute: int = 0
    cron_tz: str = "America/New_York"
    # The job supplies its OWN kill-switch-aware wrapper and must NOT be wrapped
    # in :func:`guarded`. Exactly one job sets this, and it is injected from the
    # CLI rather than listed in ``default_job_specs()``: the order-execution
    # cycle. ``guarded()`` RETURNS without running the body when the kill switch
    # is engaged, which for that job would mean no protective close, no drain, no
    # cancel_all and a dead-man lapse caused BY engaging the switch — i.e. a kill
    # switch that blocks closing. That job's own wrapper reads the same state and
    # branches to a protective-only cycle instead. No other spec may set this:
    # every job in ``default_job_specs()`` leaves it False and is guarded exactly
    # as it was before this field existed.
    self_guarded: bool = False


__all__ = ["JobFn", "JobSpec"]
