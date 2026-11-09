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
from functools import lru_cache, partial
from pathlib import Path
from typing import Any

from fastapi import Request
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from signalforge.config import get_settings

DEFAULT_BUSY_TIMEOUT_MS = 5000
_BUSY_TIMEOUT_ENV = "SIGNALFORGE_SQLITE_BUSY_TIMEOUT_MS"


def sqlite_busy_timeout_ms() -> int:
    raw = os.environ.get(_BUSY_TIMEOUT_ENV, "")
    try:
        return max(0, int(raw)) if raw else DEFAULT_BUSY_TIMEOUT_MS
    except ValueError:
        return DEFAULT_BUSY_TIMEOUT_MS


def _apply_sqlite_pragmas(
    dbapi_conn: Any, _rec: Any, *, busy_timeout_ms: int | None = None
) -> None:
    # Disable pysqlite's implicit transaction management: we emit BEGIN /
    # BEGIN IMMEDIATE ourselves in the "begin" event (explicit scope).
    dbapi_conn.isolation_level = None
    cur = dbapi_conn.cursor()
    timeout = sqlite_busy_timeout_ms() if busy_timeout_ms is None else max(0, busy_timeout_ms)
    cur.execute(f"PRAGMA busy_timeout={timeout}")  # first: the pragmas below may wait
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def _sqlite_begin(conn: Any) -> None:
    write = bool(conn.get_execution_options().get("sqlite_write", False))
    conn.exec_driver_sql("BEGIN IMMEDIATE" if write else "BEGIN")


def build_engine(url: str, *, busy_timeout_ms: int | None = None, pooled: bool = True) -> Engine:
    """An engine for ``url`` with this project's SQLite discipline attached.

    Separated from :func:`get_engine` so a second, explicitly-addressed database
    file can be opened under exactly the same pragmas, busy timeout and explicit
    ``BEGIN`` / ``BEGIN IMMEDIATE`` scoping as the configured one. A bulk run
    against a copy of the live file must not get a *different* concurrency
    contract from the file it will be merged back into.

    ``busy_timeout_ms`` overrides the configured busy timeout for this engine
    only; ``pooled=False`` closes every connection when it is released, so a
    caller holds nothing open between uses (see :func:`isolated_write_scope`).
    """
    is_sqlite = url.startswith("sqlite")
    timeout_ms = sqlite_busy_timeout_ms() if busy_timeout_ms is None else max(0, busy_timeout_ms)
    extra: dict[str, Any] = {} if pooled else {"poolclass": NullPool}
    engine = create_engine(
        url,
        echo=False,
        future=True,
        pool_pre_ping=not is_sqlite,
        connect_args=(
            {"check_same_thread": False, "timeout": timeout_ms / 1000.0} if is_sqlite else {}
        ),
        **extra,
    )
    if is_sqlite:
        event.listen(engine, "connect", partial(_apply_sqlite_pragmas, busy_timeout_ms=timeout_ms))
        event.listen(engine, "begin", _sqlite_begin)
    return engine


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return build_engine(get_settings().database_url)


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


@lru_cache(maxsize=4)
def _isolated_engine(url: str, busy_timeout_ms: int) -> Engine:
    return build_engine(url, busy_timeout_ms=busy_timeout_ms, pooled=False)


@contextmanager
def isolated_write_scope(*, busy_timeout_ms: int) -> Iterator[Session]:
    """One short write transaction on its OWN connection to the configured
    database, with its own busy timeout, closed again on exit.

    For tiny bookkeeping writes that must land even while a long job is busy
    (the worker heartbeat): the shared pool's 5 s busy timeout is sized for
    jobs that retry, and a pooled connection would stay open between beats.
    Nothing is held once the block exits — not a transaction, not a connection.
    """
    engine = _isolated_engine(get_settings().database_url, max(0, busy_timeout_ms))
    is_sqlite = engine.url.get_backend_name().startswith("sqlite")
    bind = engine.execution_options(sqlite_write=True) if is_sqlite else engine
    session = Session(bind=bind, autoflush=False, expire_on_commit=False, future=True)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def read_phase(session: Session) -> Iterator[Session]:
    """Run a slow read/compute block on ``session`` as a plain reader.

    Ends whatever transaction is open (committing it), runs the block under
    ``BEGIN`` (never ``IMMEDIATE``, so the WAL write lock is NOT held however
    long the block takes), ends that read transaction and hands the session
    back with the write intent it arrived with. Its next transaction therefore
    begins fresh — a writer's ``BEGIN IMMEDIATE`` — never a read->write upgrade.
    ORM objects loaded inside stay usable (``expire_on_commit=False``).
    """
    restore = has_write_intent(session)
    session.commit()
    set_write_intent(session, False)
    try:
        yield session
    except Exception:
        session.rollback()
        set_write_intent(session, restore)
        raise
    session.commit()
    set_write_intent(session, restore)


def set_write_intent(session: Session, write: bool) -> None:
    """Switch the session's NEXT transactions between ``BEGIN`` (plain reader)
    and ``BEGIN IMMEDIATE`` (writer). Write intent lives on the session's
    bind, so it is sticky across ``commit()`` — a long read/compute phase in a
    ``session_scope(write=True)`` must call ``commit()`` then
    ``set_write_intent(session, False)`` to stop holding the write lock, and
    ``set_write_intent(session, True)`` again before it writes.

    The new bind is derived from the session's OWN bind, never from the cached
    configured engine: a session opened against a different database file (see
    :func:`external_session_scope`) must keep writing to that file. Deriving it
    from ``get_engine()`` would silently re-point such a session at the live
    database on its first write phase.
    """
    if session.in_transaction():
        raise RuntimeError("commit() or rollback() before changing write intent")
    bind = session.get_bind()
    if not isinstance(bind, Engine) or not bind.url.get_backend_name().startswith("sqlite"):
        return
    session.bind = bind.execution_options(sqlite_write=write)


def has_write_intent(session: Session) -> bool:
    """Whether the session's NEXT transaction begins ``IMMEDIATE`` (see
    :func:`set_write_intent`). A helper that splits a caller's session into
    read and short write phases uses it to hand the session back with the
    intent it arrived with."""
    bind = session.get_bind()
    return isinstance(bind, Engine) and bool(
        bind.get_execution_options().get("sqlite_write", False)
    )


@contextmanager
def external_session_scope(path: str | Path, *, write: bool = False) -> Iterator[Session]:
    """A transactional scope against a SQLite file OTHER than the configured one.

    This is the separate-database-file half of the long-backfill safety design
    (D1 §7.7 fix 2): a multi-day options run writes into a file-level copy of
    the live database, so the live file keeps exactly one writer — the paper
    probation worker — for the whole run, and the result is merged back in one
    short pass afterwards.

    The file must already exist and be migrated. Creating one on demand is
    refused deliberately: SQLite would happily create an empty database, the
    run would then find no ``instrument`` / ``ohlcv_daily`` rows, and a
    multi-day job would end with every cycle excluded ``no_instrument`` instead
    of failing in the first second.
    """
    p = Path(path).expanduser()
    if not p.is_file():
        raise FileNotFoundError(
            f"{p} does not exist. The bulk database is a FILE-LEVEL COPY of the live "
            "database taken with the worker stopped — it is never created empty, because "
            "an empty file would run for days and exclude every cycle for want of an "
            "equity reference price."
        )
    engine = build_engine(f"sqlite+pysqlite:///{p}")
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    bind: Engine | Any = engine.execution_options(sqlite_write=True) if write else engine
    session = factory(bind=bind)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()


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
    _isolated_engine.cache_clear()
