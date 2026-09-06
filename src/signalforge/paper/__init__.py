"""Paper-trading ledger + journal.

No real orders. ``paper_trade`` rows are immutable after creation; corrections are
separate append-only events (invariant S9). Auto-simulation is OFF unless the user
explicitly enables it. Never imports :mod:`signalforge.llm`.
"""

from __future__ import annotations
