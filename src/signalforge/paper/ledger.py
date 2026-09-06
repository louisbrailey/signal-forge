"""Paper-trading ledger (Phase 1 §1.7).

Phase 0: public shapes + the immutability rule expressed as an exception the
repository layer raises. The SQLAlchemy-backed implementation and property tests
(cash + position value conserved) land in Phase 1.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Decision(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    IGNORED = "ignored"
    WATCH = "watch"


class ImmutablePaperTradeError(RuntimeError):
    """Raised on any attempt to mutate an existing ``paper_trade`` row (S9)."""


@dataclass(frozen=True, slots=True)
class FillAssumptions:
    reference_price: float
    spread_bps: float
    slippage_bps: float
    note: str = ""


def accept_candidate(candidate_id: str, assumptions: FillAssumptions) -> str:  # pragma: no cover
    raise NotImplementedError("Paper ledger is implemented in Phase 1 (§1.7).")
