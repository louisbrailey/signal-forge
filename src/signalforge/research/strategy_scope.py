"""Resolve frozen daily strategy definitions without changing their parameters."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from signalforge.domain import Horizon
from signalforge.research.strategies import BaselineStrategy, default_strategies


def normalized_spec(spec: dict[str, Any]) -> dict[str, Any]:
    value: dict[str, Any] = json.loads(json.dumps(spec))
    value.pop("git_sha", None)  # Code provenance may change; every definition field must match.
    return value


def resolve_strategy_scope(
    strategy_specs: list[dict[str, Any]] | None = None,
) -> list[BaselineStrategy]:
    registered = [s for s in default_strategies() if s.spec().horizon is not Horizon.INTRADAY]
    if strategy_specs is None:
        return registered
    if not isinstance(strategy_specs, list) or not 1 <= len(strategy_specs) <= 64:
        raise ValueError("Frozen strategy scope must be a bounded nonempty list")
    by_key = {(s.spec().name, s.spec().version): s for s in registered}
    selected = []
    seen = set()
    for frozen in strategy_specs:
        if not isinstance(frozen, dict):
            raise ValueError("Malformed frozen strategy definition")
        key = (frozen.get("name"), frozen.get("version"))
        if not all(isinstance(part, str) for part in key):
            raise ValueError("Malformed frozen strategy identity")
        if key in seen or key not in by_key:
            raise ValueError("Unknown or duplicate frozen strategy")
        current = by_key[key]
        if normalized_spec(frozen) != normalized_spec(asdict(current.spec())):
            raise ValueError("Frozen strategy definition differs from current registered spec")
        seen.add(key)
        selected.append(current)
    return selected
