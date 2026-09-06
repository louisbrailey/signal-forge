"""Position sizing from per-trade risk % and stop distance (Phase 1).

Phase 0: the public shape only. The real implementation (concentration, exposure,
correlated-exposure, daily-risk checks) lands in Phase 1 §1.6 with property tests
asserting no produced size can violate a configured limit.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SizingRequest:
    symbol: str
    entry_price: float
    stop_price: float
    account_equity: float
    sector: str


@dataclass(frozen=True, slots=True)
class SizingResult:
    shares: int
    risk_dollars: float
    risk_pct_of_account: float
    rejected_reason: str | None = None


def size_position(request: SizingRequest) -> SizingResult:  # pragma: no cover - Phase 1
    raise NotImplementedError("Risk engine sizing is implemented in Phase 1 (§1.6).")
