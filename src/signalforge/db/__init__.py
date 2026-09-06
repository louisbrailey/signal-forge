"""Durable storage: SQLAlchemy models + Alembic migrations.

Phase 1: SQLite (``sqlite+pysqlite``), WAL mode, engine-agnostic models so the
Phase 2 Postgres swap is a ``DATABASE_URL`` change plus a migration review.

Phase 0: intentionally empty — the app and CLI do not require a database yet.
"""

from __future__ import annotations
