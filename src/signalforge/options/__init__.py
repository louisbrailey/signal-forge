"""Options — **education and simulation only**.

There is no options execution path anywhere in this package: no order placement,
no broker contact, no recommendations, no alerts. Nothing here reads a brokerage
credential. Naked short options, uncovered calls, margin-dependent strategies,
0DTE alerting, and spreads are intentionally absent.

- :mod:`signalforge.options.blackscholes` — closed-form price / Greeks / implied
  vol. Any Greek or IV shown from here is **computed locally**, not vendor data.
- :mod:`signalforge.options.simulators` — payoff / break-even / max-loss / time
  decay for long calls, long puts, covered calls, and cash-secured puts.
"""

from __future__ import annotations

DISCLAIMER = "Research signal only — no order was placed."
COMPUTED_NOTE = "Greeks/IV shown here are computed locally (Black-Scholes), not vendor data."

__all__ = ["DISCLAIMER", "COMPUTED_NOTE"]
