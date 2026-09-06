"""Deterministic research engine: strategy registry, features, scan, rank, candidates.

Nothing in this package may import :mod:`signalforge.llm` (invariant S3, enforced
by import-linter). All logic is deterministic given (inputs, code version,
``ResearchConfig.config_hash``, seed) — invariant S4.
"""

from __future__ import annotations
