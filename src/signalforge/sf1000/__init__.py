"""Signal Forge 1000 — paper index research module (Phase A: design only).

A SIMULATED model portfolio for research and education. Not an ETF, not an
investment product, not an offer. Nothing in this package is activated: it
carries the versioned specification identifiers and the safety boundary that
import-linter contract S13 enforces (no alerts, no paper ledger acceptance,
no LLM, no brokerage). Implementation lands in Phase B behind provisional
labels; the strategy cannot be approved for paper probation until
point-in-time fundamentals and historical constituent membership exist (see
docs/SF1000_SPEC.md "missing data before validation").
"""

from __future__ import annotations

SPEC_VERSION = "0.1.0-provisional"
STATUS = "design_only"  # Phase A — no ledger, no rebalance, no ranking runs
PROVISIONAL_LABEL = (
    "PROVISIONAL — survivorship-biased, as-of-adjusted inputs; not validated; "
    "not eligible for paper probation"
)
RESEARCH_ONLY_NOTICE = "Research signal only — no order was placed."
