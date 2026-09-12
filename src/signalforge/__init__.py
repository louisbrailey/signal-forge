"""Signal Forge — local-first, paper-trading-only market research platform.

This package produces research output first. Orders can exist only in the
execution layer, which is OFF by default and places nothing unless the
operator has explicitly enabled it and armed a strategy (nothing is armed by default);
it never automates a trading venue. See ``DISCLAIMER.md``, ``ARCHITECTURE.md``
(safety invariants S1-S10, S15a/S15b) and ``docs/decisions/0003-execution-layer.md``.
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
