"""Engine + session management.

Phase 1 uses SQLite. Local multi-process MVP rules (API + one worker + ad-hoc
CLI against the same file):

* WAL journal mode (readers never block the single writer), ``synchronous=NORMAL``.
* A bounded busy timeout (``SIGNALFORGE_SQLITE_BUSY_TIMEOUT_MS``, default 5000)
  applied both as ``PRAGMA busy_timeout`` and the DBAPI ``timeout``.
* Explicit transaction scope: pysqlite's implicit BEGIN is disabled and every
  SQLAlchemy transaction starts with an explicit ``BEGIN`` — ``BEGIN IMMEDIATE``
  for write-intent scopes (``session_scope(write=True)``) so a writer takes the
  WAL write lock up front and waits on the busy handler instead of failing
  later with SQLITE_BUSY_SNAPSHOT (a read-then-write upgrade that the busy
  timeout can never retry). Read scopes stay DEFERRED and never block writers.
* No writer may hold a transaction across network I/O — see ``data/ingest.py``.

The engine URL comes from ``Settings.database_url`` so the Postgres swap is a
config change; every SQLite-specific branch below is a no-op elsewhere.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

from fastapi import Request
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from signalforge.config import get_settings

DEFAULT_BUSY_TIMEOUT_MS = 5000
_BUSY_TIMEOUT_ENV = "SIGNALFORGE_SQLITE_BUSY_TIMEOUT_MS"


def sqlite_busy_timeout_ms() -> int:
    raw = os.environ.get(_BUSY_TIMEOUT_ENV, "")
    try:
        return max(0, int(raw)) if raw else DEFAULT_BUSY_TIMEOUT_MS
    except ValueError:
        return DEFAULT_BUSY_TIMEOUT_MS


def _apply_sqlite_pragmas(dbapi_conn: Any, _rec: Any) -> None:
    # Disable pysqlite's implicit transaction management: we emit BEGIN /
    # BEGIN IMMEDIATE ourselves in the "begin" event (explicit scope).
    dbapi_conn.isolation_level = None
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute(f"PRAGMA busy_timeout={sqlite_busy_timeout_ms()}")
    cur.close()


def _sqlite_begin(conn: Any) -> None:
    write = bool(conn.get_execution_options().get("sqlite_write", False))
    conn.exec_driver_sql("BEGIN IMMEDIATE" if write else "BEGIN")


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    settings = get_settings()
    url = settings.database_url
    is_sqlite = url.startswith("sqlite")
    engine = create_engine(
        url,
        echo=False,
        future=True,
        pool_pre_ping=not is_sqlite,
        connect_args=(
            {"check_same_thread": False, "timeout": sqlite_busy_timeout_ms() / 1000.0}
            if is_sqlite
            else {}
        ),
    )
    if is_sqlite:
        event.listen(engine, "connect", _apply_sqlite_pragmas)
        event.listen(engine, "begin", _sqlite_begin)
    return engine


@lru_cache(maxsize=1)
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False, future=True)


def _make_session(*, write: bool) -> Session:
    bind = get_engine()
    if write and bind.url.get_backend_name().startswith("sqlite"):
        bind = bind.execution_options(sqlite_write=True)
    return get_sessionmaker()(bind=bind)


@contextmanager
def session_scope(*, write: bool = False) -> Iterator[Session]:
    """Transactional scope: commit on success, rollback on error.

    ``write=True`` declares write intent: on SQLite the transaction begins
    ``IMMEDIATE`` so the write lock is taken (or waited for, bounded by the
    busy timeout) at the start instead of failing on a later read->write
    upgrade. Keep write scopes SHORT and never span network I/O inside one.
    """
    session = _make_session(write=write)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def set_write_intent(session: Session, write: bool) -> None:
    """Switch the session's NEXT transactions between ``BEGIN`` (plain reader)
    and ``BEGIN IMMEDIATE`` (writer). Write intent lives on the session's
    bind, so it is sticky across ``commit()`` — a long read/compute phase in a
    ``session_scope(write=True)`` must call ``commit()`` then
    ``set_write_intent(session, False)`` to stop holding the write lock, and
    ``set_write_intent(session, True)`` again before it writes."""
    if session.in_transaction():
        raise RuntimeError("commit() or rollback() before changing write intent")
    base = get_engine()
    if not base.url.get_backend_name().startswith("sqlite"):
        return
    session.bind = base.execution_options(sqlite_write=True) if write else base


def get_db(request: Request) -> Iterator[Session]:
    """FastAPI dependency: one session per request. State-changing methods get
    write intent (BEGIN IMMEDIATE); GET requests are plain readers that never
    block the worker."""
    with session_scope(write=request.method.upper() not in ("GET", "HEAD", "OPTIONS")) as s:
        yield s


def reset_engine_cache() -> None:
    """Drop cached engine/sessionmaker (tests that switch DATABASE_URL)."""
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
