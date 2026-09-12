"""Single-instance lock for the scheduler worker.

Two workers against one SQLite file would double-run every job and fight for
the write lock. ``acquire_worker_lock`` takes an exclusive, non-blocking
``flock`` on ``<data_dir>/worker.lock`` for the life of the process; a second
worker fails fast with the holder's pid. The lock is released by the OS when
the process exits, however it exits.
"""

from __future__ import annotations

import fcntl
import os
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from signalforge.config.paths import data_dir

LOCK_FILENAME = "worker.lock"


class WorkerAlreadyRunning(RuntimeError):
    pass


@dataclass(slots=True)
class WorkerLock:
    path: Path
    handle: IO[str]

    def release(self) -> None:
        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()


def lock_path() -> Path:
    return data_dir() / LOCK_FILENAME


def worker_lock_holder(path: Path | None = None) -> str | None:
    """Who holds the worker lock right now, or ``None`` if nobody does.

    Read-only on purpose: unlike :func:`acquire_worker_lock` it never truncates
    the file and never writes this process's pid, so a probe cannot corrupt the
    holder record it is trying to read. Used by one-off jobs that must not
    contend with the worker for the SQLite write lock — a bulk merge holds it
    far longer than the 5 s busy timeout any worker job will wait.
    """
    p = path or lock_path()
    if not p.exists():
        return None
    try:
        handle = p.open("r+", encoding="utf-8")
    except OSError:  # pragma: no cover - unusual
        return None
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.seek(0)
        return handle.read().strip() or "unknown pid"
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return None
    finally:
        handle.close()


def acquire_worker_lock(path: Path | None = None) -> WorkerLock:
    """Take the exclusive worker lock or raise ``WorkerAlreadyRunning``."""
    p = path or lock_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    handle = p.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.seek(0)
        holder = handle.read().strip() or "unknown pid"
        handle.close()
        raise WorkerAlreadyRunning(
            f"another scheduler worker already holds {p} (holder: {holder})"
        ) from None
    handle.seek(0)
    handle.truncate()
    handle.write(f"{os.getpid()}\n")
    handle.flush()
    return WorkerLock(path=p, handle=handle)
