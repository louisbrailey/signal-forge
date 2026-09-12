# SQLite concurrency — local multi-process MVP

## Who writes to the database

| Process | How it connects | Writes |
|---|---|---|
| **API** (`uvicorn signalforge.app.main:app`) | one session per request (`db/session.py::get_db`); GET = plain reader, POST/PUT/DELETE = write-intent | Settings, paper actions, kill switch, promotion run (long!), briefing build |
| **Worker** (`signalforge run-scheduler`) | one write-intent session per job (`session_scope(write=True)`), plus a heartbeat session every 30 s and a `JobRun`/`AuditLog` record after every job | Ingest, scans, approved-scope scan, mark-to-market, briefing, health monitor, alert log, universe update |
| **CLI one-offs** (`signalforge …`, `alembic`) | their own sessions | Ingest/scan/screen on demand, migrations |
| **API with `APP_RUN_SCHEDULER=true`** | an embedded worker inside the API process | Same as the worker — takes the same single-instance lock; refuses if a worker already holds it |
| `make dev` (`--reload`) | a reloader parent + a child API process | If Ctrl-C orphans the child, it keeps reading; harmless in WAL mode but stop it before smoke testing |

## Rules (enforced in code)

1. **WAL journal mode, `synchronous=NORMAL`** — readers never block the single writer.
2. **Bounded busy timeout** — `PRAGMA busy_timeout` and the DBAPI `timeout`, both from
   `SIGNALFORGE_SQLITE_BUSY_TIMEOUT_MS` (default 5000).
3. **Explicit transaction scope** — pysqlite's implicit BEGIN is disabled; every
   SQLAlchemy transaction starts with an explicit `BEGIN` (readers) or
   `BEGIN IMMEDIATE` (`session_scope(write=True)`). Write intent takes the WAL write
   lock up front and waits on the busy handler; a deferred read-then-write would fail
   instantly with `SQLITE_BUSY_SNAPSHOT`, which the busy timeout can never retry.
4. **No writer across network I/O** — `data/ingest.py` fetches a symbol first, then
   writes it in a short transaction and **commits per symbol**. `run_scan` commits after
   its tiny strategy-version upsert AND drops write intent (`set_write_intent(session,
   False)`) so the long compute phase runs as a plain reader; `persist_scan` re-arms
   write intent and starts a fresh `BEGIN IMMEDIATE`. Write intent is sticky on the
   session's bind — `commit()` alone never demotes a writer to a reader.
5. **Bounded retry for transient lock contention only** (`db/retry.py`): an idempotent job
   body is retried 3× (0.5 s, 2 s, 5 s) only on `database is locked`; jobs that persist
   per-unit results (scans per horizon, bulk files per session) retry per unit instead
   (`NO_JOB_LEVEL_LOCK_RETRY`) so nothing is duplicated. After that the job is recorded
   **failed** with `database lock contention: … after 3 attempts`. The alert cycle commits
   each `AlertLog` right after its send, so a retried cycle can never re-send an alert. Heartbeat and
   job-record writes retry briefly and log a WARNING if they still fail — they never raise.
6. **EOD update and catch-up never overlap** — they are different APScheduler jobs
   (cron vs interval), so `max_instances=1` cannot serialize them; a module lock
   (`scheduler._EOD_UPDATE_LOCK`) makes a second firing skip instead of stacking.
7. **One worker per database** — `worker_lock.py` takes an exclusive `flock` on
   `<data_dir>/worker.lock`; a second `run-scheduler` exits with code 1 naming the holder,
   and a live heartbeat from another pid/host is also refused.

## The bug this fixed (2026-09-09)

`make worker` → catch-up ingest failed with `sqlite3.OperationalError: database is locked`.
The ingest opened its write transaction (`get_or_create_instrument` flush) **before** the
paced provider fetch and held it across the whole universe (25 symbols × 12 s pacing ≈
5 min). Any other writer — heartbeat, `JobRun`, API POST, a second worker — timed out
after 5 s. Reproduced deterministically in `tests/db/test_sqlite_concurrency.py`
(`test_repro_writer_holding_lock_across_a_wait_starves_other_writers`) and covered by the
concurrent API-traffic + worker-ingest regression there.

## Known long transactions (documented, not fixed here)

`POST /strategies/promotion/run` runs the full 10-gate promotion pipeline inside one
request transaction (minutes). While it runs, worker jobs will report lock contention
and retry/fail honestly. Run promotion evaluations from the CLI with the worker stopped.

`signalforge options backfill` (the legacy nearest-N-expiries path) and
`signalforge options ingest` fetch option contracts and aggregates inside their
session while writing — the same pattern the daily ingest had. Run them with the
worker stopped, or accept that worker jobs may report lock contention (bounded
retry, then an honest failure) while they run.

**`signalforge options cycle-backfill` is no longer in that list.** It commits
per (underlying, cycle) — one short `BEGIN IMMEDIATE` holding that cycle's bars
and its coverage record together — and every paced provider request is issued
with no transaction open at all (`data/options_backfill.py::_Phases`). Its
`IngestionRun` row is committed before the first request, and `KillSwitchEngaged`
is caught at the loop boundary, so an interrupted run costs the cycle in flight
and nothing else. That makes it survivable beside the worker; for the multi-day
I-O2 job the designed route is still `--to-database` against a file-level copy,
merged back with `options merge` while the worker is stopped
(`docs/research/options_designs/IO2_RUNBOOK.md`).
