# launchd agents (this Mac) — NOT installed by the repo

Two per-user LaunchAgents keep the dashboard API and the scheduler worker
running while you are logged in. Nothing here is loaded automatically;
`make launchd-check` only validates the files. Installing them is a manual,
reviewed step (see `docs/RUNBOOK_ALWAYS_ON.md`, Option A).

| Agent | Runs | Log |
|---|---|---|
| `com.signalforge.api` | `.venv/bin/uvicorn signalforge.app.main:app --host 127.0.0.1 --port 8787` | `~/Library/Logs/signalforge/api.*.log` |
| `com.signalforge.worker` | `.venv/bin/python -m signalforge.cli run-scheduler` | `~/Library/Logs/signalforge/worker.*.log` |

The worker writes a heartbeat row (`worker_heartbeat`) every 30 s and runs a
`catch_up` job every 30 min that performs the EOD update if it is owed for
the last completed session — so a Mac that slept through 17:30 ET catches up
within 30 min of waking. `/ops` shows the heartbeat, the next scheduled run,
freshness vs the expected session, and whether a catch-up is pending.

The paths are absolute for `/Users/louisbrailey/signal-forge`; edit them if
the repo lives elsewhere. `KeepAlive` restarts a crashed process after
`ThrottleInterval` (30 s). Alerts, paper probation, and auto-simulation stay
OFF regardless of these agents — they only keep ingestion/scans/health running.

## Isolated Kronos comparison collector

The separate `com.signalforge.kronos-comparison` LaunchAgent observes successful
post-close scans and advances the frozen private comparison books once per session.
It does not add jobs to, or restart, the operating worker. See
[the collector runbook](../../docs/KRONOS-COMPARISON-COLLECTOR.md) for pinned paths,
status, installation and stopping only this service. Keep both its runner worktree
and the frozen comparison worktree while the experiment is active.
