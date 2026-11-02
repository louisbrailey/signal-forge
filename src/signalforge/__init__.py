"""Signal Forge — local-first market research and paper simulation.

Broker operations exist only in the isolated execution boundary and are OFF by
default. Sandbox strategies require explicit arming. Production is a separate,
human-confirmed CLI workflow with immutable reviews and durable account admission;
it is never an automated strategy or LLM decision path. See DISCLAIMER.md,
ARCHITECTURE.md and ADR 0006 for the supported scope and provider limitations.
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
