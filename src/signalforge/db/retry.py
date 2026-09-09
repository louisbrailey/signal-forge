"""Bounded retry for TRANSIENT SQLite lock contention only.

Retries a unit of work when SQLite reports ``database is locked`` /
``database table is locked`` (SQLITE_BUSY / SQLITE_LOCKED), with a short
exponential backoff. Anything else — and the lock error itself once the
attempts are exhausted — is re-raised untouched, so a persistent failure is
never hidden and a job is never marked successful without succeeding.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from sqlalchemy.exc import OperationalError

from signalforge.observability import get_logger

_log = get_logger("db.retry")

_LOCK_MARKERS = ("database is locked", "database table is locked", "database schema is locked")
DEFAULT_ATTEMPTS = 3
DEFAULT_BACKOFF_S = (0.5, 2.0, 5.0)


def is_lock_error(exc: BaseException) -> bool:
    if not isinstance(exc, OperationalError):
        return False
    msg = str(exc.orig if exc.orig is not None else exc).lower()
    return any(m in msg for m in _LOCK_MARKERS)


class LockRetryExhausted(RuntimeError):
    """Raised (from the original OperationalError) after the last attempt."""

    def __init__(self, attempts: int, last: OperationalError) -> None:
        super().__init__(
            f"SQLite lock contention persisted after {attempts} attempts: "
            f"{str(last.orig or last)[:120]}"
        )
        self.attempts = attempts
        self.last = last


def retry_on_lock[T](
    fn: Callable[[], T],
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    backoff_s: tuple[float, ...] = DEFAULT_BACKOFF_S,
    label: str = "",
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Run ``fn`` up to ``attempts`` times, sleeping between attempts only
    when the failure is a transient SQLite lock. Returns ``fn``'s result."""
    last: OperationalError | None = None
    for i in range(1, attempts + 1):
        try:
            return fn()
        except OperationalError as exc:
            if not is_lock_error(exc):
                raise
            last = exc
            if i >= attempts:
                break
            delay = backoff_s[min(i - 1, len(backoff_s) - 1)]
            _log.warning("db.lock_retry", label=label, attempt=i, of=attempts, retry_in_s=delay)
            sleep(delay)
    assert last is not None
    raise LockRetryExhausted(attempts, last) from last
