"""Signal Forge — local-first, paper-trading-only market research platform.

This package produces **hypothetical research output only**. It never connects to
a brokerage, never places an order, and never automates a trading venue. See
``DISCLAIMER.md`` and ``ARCHITECTURE.md`` (safety invariants S1-S10).
"""

from __future__ import annotations

__version__ = "0.1.0"

# Text that must appear verbatim on every recommendation and alert.
RESEARCH_ONLY_NOTICE = "Research signal only — no order was placed."
NOT_ADVICE_NOTICE = (
    "Hypothetical research output, not financial advice. "
    "Verify every input independently and make your own decisions."
)

__all__ = ["NOT_ADVICE_NOTICE", "RESEARCH_ONLY_NOTICE", "__version__"]
