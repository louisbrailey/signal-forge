"""Optional LLM explanation layer.

Permitted: summarise deterministic signals, explain terms/risk, summarise
retrieved news/filings, daily briefing prose, journal pattern analysis, doc
generation.

Forbidden: inventing recommendations, overriding risk limits, claiming price
certainty, fabricating statistics, using future information in historical
summaries, making execution decisions.

This package is NEVER imported by ``research``/``risk``/``backtest``/``paper``
(invariant S3, enforced by import-linter). Every AI narrative carries the footer
``AI explanation, not a trading instruction.`` and passes ``guards``.
"""

from __future__ import annotations

from signalforge.llm.guards import (
    AI_FOOTER,
    GuardViolation,
    assert_grounded,
    extract_numeric_tokens,
)

__all__ = ["AI_FOOTER", "GuardViolation", "assert_grounded", "extract_numeric_tokens"]
