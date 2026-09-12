"""Parameters for the mechanical grid strategy.

Every number the operator quoted is a parameter here, because the quoted set is
internally inconsistent: 1000 symbols x a $50 per-symbol cap is $50,000 of
budget against $5,000 of starting cash. Three configurations are therefore
supported and documented (see ``docs/research/grid/README.md``):

* ``universe_size=1000``, ``per_symbol_cap=5``, ``starting_cash=5_000``
* ``universe_size=100``,  ``per_symbol_cap=50``, ``starting_cash=5_000``
* ``universe_size=1000``, ``per_symbol_cap=50``, ``starting_cash=50_000``

``GridParams`` is a plain frozen dataclass so the engine stays pure and
importable without a database or settings layer. The *live* parameters live in
:class:`signalforge.config.research.GridConfig`, which carries the same fields.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

__all__ = ["GridParams"]


@dataclass(frozen=True, slots=True)
class GridParams:
    """Validated grid parameters.

    ``drop_pct``/``rise_pct`` are fractions (0.05 = 5%), not percentages.
    """

    starting_cash: float = 5_000.0
    per_symbol_cap: float = 50.0
    buy_usd: float = 5.0
    sell_usd: float = 10.0
    drop_pct: float = 0.05
    rise_pct: float = 0.05
    # Per-order minimum notional: an order smaller than this is skipped rather
    # than sent, because a real fractional-share broker will not route it.
    min_order_usd: float = 1.0
    # The operator's rule says a rise past ``anchor x (1 + rise_pct)`` sells and
    # re-anchors, but it is silent on what happens when there is NOTHING to sell.
    #
    # True (default): the anchor still ratchets up to that close. The grid
    #   follows price, which is what makes it a grid.
    # False (strict literal reading): no sell means no action at all, so the
    #   anchor stays put. A symbol that rises before it ever dips is then
    #   stranded forever — its anchor can never be reached again, so it never
    #   trades. Measured on the 10-year 100-symbol run that silently excluded 35
    #   of 100 symbols, including NVDA, MSFT and AVGO, so the default is True and
    #   every report states which reading produced it.
    #
    # Buy triggers skipped for the cap, for cash, or for the minimum notional
    # NEVER re-anchor under either setting: those are capacity limits on an order
    # the rule genuinely wanted, so the level stays armed.
    reanchor_on_untradeable_rise: bool = True
    # Project cost model: 3 bps slippage + half of a 5 bps spread, commission 0.
    slippage_bps: float = 3.0
    spread_bps: float = 5.0
    commission_per_share: float = 0.0
    commission_min_per_order: float = 0.0
    # Universe selection (recorded on every report so a run is reproducible).
    universe_name: str = "top1000"
    universe_size: int = 1000

    def __post_init__(self) -> None:
        if self.starting_cash <= 0:
            raise ValueError("starting_cash must be > 0")
        if self.per_symbol_cap <= 0:
            raise ValueError("per_symbol_cap must be > 0")
        if self.buy_usd <= 0:
            raise ValueError("buy_usd must be > 0")
        if self.sell_usd <= 0:
            raise ValueError("sell_usd must be > 0")
        if not 0 < self.drop_pct < 1:
            raise ValueError("drop_pct must be a fraction in (0, 1) — 0.05 means 5%")
        if self.rise_pct <= 0:
            raise ValueError("rise_pct must be a fraction > 0 — 0.05 means 5%")
        if self.min_order_usd < 0:
            raise ValueError("min_order_usd must be >= 0")
        if self.slippage_bps < 0 or self.spread_bps < 0:
            raise ValueError("slippage_bps and spread_bps must be >= 0")
        if self.commission_per_share < 0 or self.commission_min_per_order < 0:
            raise ValueError("commission fields must be >= 0")
        if self.universe_size < 1:
            raise ValueError("universe_size must be >= 1")
        if self.buy_usd > self.per_symbol_cap:
            raise ValueError(
                f"buy_usd {self.buy_usd} exceeds per_symbol_cap {self.per_symbol_cap} — "
                "no buy could ever be placed"
            )

    @property
    def slippage_frac(self) -> float:
        """Fraction applied against every fill: slippage + half the spread."""
        return (self.slippage_bps + self.spread_bps / 2.0) / 10_000.0

    @property
    def max_committed_usd(self) -> float:
        """Budget the configuration can commit if every symbol reaches its cap."""
        return self.per_symbol_cap * self.universe_size

    @property
    def budget_is_consistent(self) -> bool:
        """Whether ``starting_cash`` can actually fund every symbol to its cap."""
        return self.max_committed_usd <= self.starting_cash

    def with_(self, **changes: Any) -> GridParams:
        """A validated copy with ``changes`` applied."""
        return replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "starting_cash": self.starting_cash,
            "per_symbol_cap": self.per_symbol_cap,
            "buy_usd": self.buy_usd,
            "sell_usd": self.sell_usd,
            "drop_pct": self.drop_pct,
            "rise_pct": self.rise_pct,
            "min_order_usd": self.min_order_usd,
            "reanchor_on_untradeable_rise": self.reanchor_on_untradeable_rise,
            "slippage_bps": self.slippage_bps,
            "spread_bps": self.spread_bps,
            "commission_per_share": self.commission_per_share,
            "commission_min_per_order": self.commission_min_per_order,
            "universe_name": self.universe_name,
            "universe_size": self.universe_size,
        }

    @property
    def costs_label(self) -> str:
        return (
            f"slippage {self.slippage_bps:g} bps + half-spread "
            f"({self.spread_bps:g} bps quoted), commission "
            f"{self.commission_per_share:g}/share, min order ${self.min_order_usd:g}"
        )
