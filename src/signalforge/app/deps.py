"""Shared FastAPI dependencies."""

from __future__ import annotations

from fastapi import HTTPException, status

from signalforge.killswitch import KillSwitch, get_kill_switch


def get_switch() -> KillSwitch:
    return get_kill_switch()


def require_not_killed() -> None:
    """Dependency for every state-changing route.

    Returns 423 Locked while the kill switch is engaged (invariant S6). This
    takes effect on the very next request after the switch is flipped.
    """
    state = get_kill_switch().state()
    if state.active:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=(
                f"Kill switch engaged ({state.reason!r}). Polling, jobs, alerts, and "
                "paper-trade creation are halted. Release it in Settings to resume."
            ),
        )
