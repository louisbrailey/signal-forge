# ADR 0002 — Phase 1 stack simplifications (SQLite, APScheduler, no Docker)

- **Status:** accepted (2026-09-06)
- **Deciders:** Louis Brailey

## Context

The target stack lists PostgreSQL, a Celery/RQ/Arq worker with Redis, and Docker
Compose. Phase 1 is a single-user local MVP on daily-bar data with two
strategies. The brief explicitly permits SQLite for an MVP and permits proposing
a simpler stack when it improves reliability for a beginner setup, with the
tradeoff documented.

## Decision

Phase 1 uses:

- **SQLite** (`sqlite+pysqlite`) via SQLAlchemy 2.x + Alembic. Models and
  migrations are written engine-agnostically so the Postgres swap in Phase 2 is a
  `DATABASE_URL` change plus a migration review.
- **APScheduler** in-process (SQLAlchemy jobstore) for ingest / scan / briefing /
  health-probe jobs. Missed jobs (laptop asleep) are detected and a catch-up run
  is triggered on wake.
- **No Docker / Redis / separate worker** in Phase 1. `make dev` runs the API and
  scheduler together.

Job logic is written against a thin `JobRunner` protocol so Phase 2 can move to
**Arq + Redis** without touching job bodies.

## Consequences

- **+** `uv sync && make migrate && make dev` is the entire setup. No services to
  run.
- **+** Matches a Mac that is not always on.
- **−** No cross-process concurrency; long backtests block a scheduler thread
  (mitigated: run heavy backtests via the CLI, not the scheduler, in Phase 1).
- **−** SQLite write concurrency is limited (fine for one user; WAL mode on).
- **−** A second migration review is needed when moving to Postgres (types,
  `JSONB`, partial indexes).

## Phase 2 triggers

Intraday polling, concurrent multi-feed ingestion, or a move to an always-on host
→ adopt Postgres + Arq + Redis + Docker Compose as originally specified.
