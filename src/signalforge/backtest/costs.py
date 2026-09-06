"""Transaction-cost & slippage models. Assumptions are displayed on every report.

Phase 0: pure, tested helpers usable immediately by Phase 1's engine.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CostModel:
    commission_per_share: float = 0.0
    commission_min_per_order: float = 0.0
    slippage_bps: float = 3.0
    half_spread_fill_penalty: bool = True

    def commission(self, shares: int) -> float:
        raw = abs(shares) * self.commission_per_share
        return max(raw, self.commission_min_per_order) if shares else 0.0

    def slippage(self, price: float, shares: int) -> float:
        return abs(price) * abs(shares) * (self.slippage_bps / 10_000.0)

    def spread_cost(self, price: float, shares: int, spread_bps: float) -> float:
        if not self.half_spread_fill_penalty:
            return 0.0
        return abs(price) * abs(shares) * (spread_bps / 10_000.0) / 2.0

    def total_entry_cost(self, price: float, shares: int, spread_bps: float) -> float:
        return (
            self.commission(shares)
            + self.slippage(price, shares)
            + self.spread_cost(price, shares, spread_bps)
        )
