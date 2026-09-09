"""Best-effort short git SHA for stamping strategy specs and backtest runs."""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def git_sha() -> str:
    try:
        out = subprocess.run(  # noqa: S603
            ["git", "-C", str(_REPO), "rev-parse", "--short", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        sha = out.stdout.strip()
        return sha or "unknown"
    except (OSError, subprocess.SubprocessError):  # pragma: no cover
        return "unknown"


@lru_cache(maxsize=1)
def git_branch() -> str:
    """Current branch name ("HEAD" when detached), for the Operational Status page."""
    try:
        out = subprocess.run(  # noqa: S603
            ["git", "-C", str(_REPO), "rev-parse", "--abbrev-ref", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):  # pragma: no cover
        return "unknown"
