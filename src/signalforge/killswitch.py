"""Emergency kill switch (invariant S6).

When engaged, the system must immediately stop:
* data polling and every scheduled job,
* alert dispatch,
* paper-trade creation and any other research/state mutation.

Design goals:
* **Predictable on error** — a missing state file means *not engaged* (fresh
  install). An unreadable or corrupt file is treated as *engaged* and logged at ERROR.
  An operator must explicitly repair or release it before guarded work resumes.
* **Cheap to check** — ``is_active()`` is a small JSON read; callers may cache
  for a single job tick but never longer.
* **Auditable** — every transition appends to a JSONL event log.
* **Process-safe** — atomic file replace; a threading lock guards writers in one
  process.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from signalforge.config import paths
from signalforge.observability import get_logger

_log = get_logger("killswitch")


@dataclass(frozen=True, slots=True)
class KillSwitchState:
    active: bool
    reason: str
    actor: str
    changed_at: datetime

    @classmethod
    def initial(cls) -> KillSwitchState:
        return cls(active=False, reason="initial state", actor="system", changed_at=_now())


def _now() -> datetime:
    return datetime.now(UTC)


class KillSwitch:
    """File-backed kill switch. One instance per state-file path."""

    def __init__(
        self,
        state_path: Path | None = None,
        log_path: Path | None = None,
    ) -> None:
        self._state_path = state_path or paths.kill_switch_state_path()
        self._log_path = log_path or paths.kill_switch_log_path()
        self._lock = threading.Lock()

    # -- reads -------------------------------------------------------------
    def state(self) -> KillSwitchState:
        try:
            raw = self._state_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return KillSwitchState.initial()
        except (OSError, UnicodeError):
            return self._invalid_state("unreadable")
        try:
            data = json.loads(raw)
            if not isinstance(data, dict) or type(data.get("active")) is not bool:
                return self._invalid_state("corrupt")
            changed_at = datetime.fromisoformat(data["changed_at"])
            if changed_at.tzinfo is None or changed_at.utcoffset() is None:
                return self._invalid_state("corrupt")
            return KillSwitchState(
                active=data["active"],
                reason=str(data.get("reason", "")),
                actor=str(data.get("actor", "unknown")),
                changed_at=changed_at,
            )
        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
            return self._invalid_state("corrupt")

    @staticmethod
    def _invalid_state(category: str) -> KillSwitchState:
        # Never include file contents or exception text: they may contain secrets.
        _log.error("killswitch.state_invalid", category=category)
        return KillSwitchState(
            active=True, reason=f"kill-switch state {category}", actor="system", changed_at=_now()
        )

    def is_active(self) -> bool:
        return self.state().active

    # -- writes ----------------------------------------------------------
    def engage(self, reason: str, actor: str = "system") -> KillSwitchState:
        return self._set(active=True, reason=reason, actor=actor)

    def release(self, reason: str, actor: str = "system") -> KillSwitchState:
        return self._set(active=False, reason=reason, actor=actor)

    def _set(self, *, active: bool, reason: str, actor: str) -> KillSwitchState:
        with self._lock:
            new = KillSwitchState(active=active, reason=reason, actor=actor, changed_at=_now())
            payload = {
                "active": new.active,
                "reason": new.reason,
                "actor": new.actor,
                "changed_at": new.changed_at.isoformat(),
            }
            self._atomic_write(self._state_path, json.dumps(payload, indent=2) + "\n")
            self._append_event(payload)
            _log.warning(
                "killswitch.transition",
                active=new.active,
                reason=new.reason,
                actor=new.actor,
            )
            return new

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".ks-", suffix=".tmp")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
                fh.flush()
                os.fsync(fh.fileno())
            tmp.replace(path)  # atomic on POSIX
        finally:
            tmp.unlink(missing_ok=True)

    def _append_event(self, payload: dict[str, object]) -> None:
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"event": "killswitch", **payload})
        with self._log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


_default_lock = threading.Lock()
_default: KillSwitch | None = None


def get_kill_switch() -> KillSwitch:
    """Return the process-wide default kill switch (bound to the configured path)."""
    global _default
    if _default is None:
        with _default_lock:
            if _default is None:
                _default = KillSwitch()
    return _default


class KillSwitchEngaged(RuntimeError):
    """Raised by guarded code paths when the kill switch is active."""

    def __init__(self, state: KillSwitchState) -> None:
        super().__init__(f"Kill switch engaged: {state.reason!r} (by {state.actor})")
        self.state = state


def ensure_not_engaged(switch: KillSwitch | None = None) -> None:
    """Raise :class:`KillSwitchEngaged` if the switch is active. Use at job entry."""
    sw = switch or get_kill_switch()
    st = sw.state()
    if st.active:
        raise KillSwitchEngaged(st)
