"""Stable, order-independent hashing of research-relevant configuration.

The hash must:
* be identical for the same logical config regardless of key order or of
  cosmetic keys that do not affect research output;
* change whenever a value that *does* affect research output changes.

It is recorded on every ``scan_run`` and ``backtest_run`` (ARCHITECTURE.md S4).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def _canonical(value: Any) -> Any:
    """Recursively convert to a JSON-canonical, order-stable structure."""
    if isinstance(value, Mapping):
        return {str(k): _canonical(value[k]) for k in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_canonical(v) for v in value), key=repr)
    if isinstance(value, float):
        # Avoid 1.0 vs 1 vs 1.0000001 noise; 9 dp is well beyond config precision.
        return round(value, 9)
    return value


def config_hash(payload: Mapping[str, Any]) -> str:
    """Return a hex sha256 over the canonicalised mapping."""
    canonical = _canonical(payload)
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
