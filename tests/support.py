"""Helpers shared across test modules (not fixtures — those live in conftest.py)."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
PKG_ROOT = SRC_ROOT / "signalforge"


def run_python(code: str) -> subprocess.CompletedProcess[str]:
    """Run ``code`` in a clean interpreter (fresh ``sys.modules``)."""
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )


def iter_source_files(*subpackages: str) -> Iterator[Path]:
    """Yield ``.py`` files under the given subpackages (or the whole package)."""
    roots = [PKG_ROOT / s for s in subpackages] if subpackages else [PKG_ROOT]
    for root in roots:
        yield from sorted(root.rglob("*.py"))
