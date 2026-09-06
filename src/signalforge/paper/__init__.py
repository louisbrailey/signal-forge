"""Paper-trading ledger + journal.

No real orders. ``paper_trade`` rows are immutable after creation; corrections are
separate append-only events (invariant S9). Auto-simulation is OFF unless the
user explicitly enables it. Creating a paper trade is guarded by the kill switch
(invariant S6). Never imports :mod:`signalforge.llm`.
"""

from __future__ import annotations

from signalforge.paper.corrections import record_correction
from signalforge.paper.journal import add_entry, list_entries, weekly_review
from signalforge.paper.ledger import (
    AcceptResult,
    Decision,
    ImmutablePaperTradeError,
    accept_candidate,
    auto_simulate_enabled,
    mark_to_market,
    record_decision,
)
from signalforge.paper.portfolio import portfolio_snapshot

__all__ = [
    "AcceptResult",
    "Decision",
    "ImmutablePaperTradeError",
    "accept_candidate",
    "auto_simulate_enabled",
    "mark_to_market",
    "record_decision",
    "record_correction",
    "add_entry",
    "list_entries",
    "weekly_review",
    "portfolio_snapshot",
]
