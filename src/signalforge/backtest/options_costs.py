"""Per-contract cost model for the options engine (D2 §7).

A **sibling** of :mod:`signalforge.backtest.costs`, never a subclass: shares and
contracts flow through different formulas, and R4 freezes ``CostModel`` for the
program's duration.  Nothing in this module touches the equity path.

**No field carries a default, and that is a correction, not a style choice**
(D2 §7.4).  A model whose fields default to zero yields a zero-commission,
zero-fee, zero-spread backtest, and because gate 4b is a *multiplier*,
``2 x 0 == 0`` — the dual-spread gate would pass **vacuously** on a cost model
that charges nothing, on every options evaluation for the life of the program.
An omission is therefore a ``TypeError`` at construction.  D2 proposes no
*values*; it proposes that there be no way to avoid choosing them.  Once chosen
(at D5 commit) the values are frozen for the program exactly as ``CostModel`` is.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

TickGrid = tuple[tuple[float, float], ...]


class Side(StrEnum):
    """Which way the engine is transacting a leg."""

    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True, slots=True)
class OptionCostModel:
    """Every field is required.  See the module docstring for why.

    ``tick_grid`` is ``((price_threshold, tick), ...)`` ascending, where ``tick``
    applies to prices strictly below ``price_threshold`` and the final threshold
    must be ``math.inf``.  Like ``options_close_time`` and ``settlement_style`` it
    is an asserted market-structure fact, pre-registered and recorded verbatim in
    the evaluation record — never assumed (D2 §6.3).

    ``spread_multiplier`` is the **single recorded scalar** by which the gate-4b
    run differs from the baseline run (D2 §8.2).
    """

    commission_per_contract: float
    commission_min_per_order: float
    exchange_fee_per_contract: float
    spread_pct_of_last_print: float
    spread_abs_floor_cents: float
    tick_grid: TickGrid
    assignment_fee: float
    exercise_fee: float
    spread_multiplier: float

    def __post_init__(self) -> None:
        if self.spread_pct_of_last_print == 0.0 and self.spread_abs_floor_cents == 0.0:
            raise ValueError("a zero-spread options cost model is not a cost model")
        if self.spread_pct_of_last_print < 0.0 or self.spread_abs_floor_cents < 0.0:
            raise ValueError("spread parameters must be non-negative")
        if self.spread_multiplier not in (1.0, 2.0):
            raise ValueError("spread_multiplier is 1.0 (baseline) or 2.0 (gate 4b)")
        if not self.tick_grid:
            raise ValueError("tick_grid must be pre-registered and non-empty")
        thresholds = [t for t, _ in self.tick_grid]
        if thresholds != sorted(thresholds) or len(set(thresholds)) != len(thresholds):
            raise ValueError("tick_grid thresholds must be strictly ascending")
        if not math.isinf(thresholds[-1]):
            raise ValueError("the final tick_grid threshold must be math.inf (a total function)")
        if any(tick <= 0.0 for _, tick in self.tick_grid):
            raise ValueError("every tick_grid tick must be > 0")

    # -- costs ---------------------------------------------------------------

    def commission(self, n_contract_sides: int) -> float:
        """Commission for ``n_contract_sides`` contract-sides in one order.

        A 2-leg vertical, 1 structure, round trip is **4** contract-sides: the
        engine computes ``sum(abs(qty) * contracts)`` over legs, never a structure
        count (D2 §7.2).
        """
        n = abs(int(n_contract_sides))
        if n == 0:
            return 0.0
        return max(n * self.commission_per_contract, self.commission_min_per_order)

    def fees(self, n_contract_sides: int) -> float:
        return abs(int(n_contract_sides)) * self.exchange_fee_per_contract

    def spread(self, last_print: float, *, moneyness: float, dte: int) -> float:
        """The **full** modelled spread for one leg-side (D2 §6.2, §6.3).

        ``max(floor, pct * last_print)``, times ``spread_multiplier``.  Phase 1
        applies no moneyness/DTE multiplier: D2 §6.3 permits one only as a
        *pre-registered, monotone* function, and nothing is pre-registered until
        D5, so the arguments are carried in the signature (so adding one later is
        not a signature change that invalidates callers) and are deliberately
        unused.  A free-form table tunable after an outcome is seen is forbidden.
        """
        del moneyness, dte  # see docstring — Phase 1 multiplier is identically 1.0
        base = max(self.spread_abs_floor_cents / 100.0, self.spread_pct_of_last_print * last_print)
        return base * self.spread_multiplier

    # -- tick grid -----------------------------------------------------------

    def tick_for(self, price: float) -> float:
        for threshold, tick in self.tick_grid:
            if abs(price) < threshold:
                return tick
        raise ValueError(f"tick_grid does not cover price {price!r}")

    def round_to_tick(self, price: float, *, side: Side) -> float:
        """Round **away from the engine**: up on a buy, down on a sale.

        Rounding can therefore never improve a fill (D2 §6.3 rule 2).
        """
        tick = self.tick_for(price)
        steps = price / tick
        rounded = (
            math.ceil(steps - 1e-9) * tick if side is Side.BUY else math.floor(steps + 1e-9) * tick
        )
        return round(rounded, 10)
