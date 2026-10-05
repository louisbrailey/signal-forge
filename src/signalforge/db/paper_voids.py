"""Which paper positions have been VOIDED by an append-only correction.

``paper_position`` has no status column and ``paper_trade`` is immutable (S9),
so the ``trade_correction`` row with field ``legacy_void.position.status``
(old "closed" -> new "void") IS the void marker. A voided position stays closed
(no exposure, no cap) and is not closed-trade performance evidence.

Lives under ``signalforge.db`` (models only, no ledger import) so both the
paper package, which writes the marker, and the research evidence readers can
use it without a dependency on each other.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import PaperTrade, TradeCorrection

__all__ = ["FIELD_VOID", "VOID_STATUS", "voided_position_ids"]

FIELD_VOID = "legacy_void.position.status"
VOID_STATUS = "void"


def voided_position_ids(session: Session) -> set[int]:
    """Ids of paper positions voided by an append-only correction."""
    rows = session.scalars(
        select(PaperTrade.position_id)
        .join(TradeCorrection, TradeCorrection.paper_trade_id == PaperTrade.id)
        .where(
            TradeCorrection.field == FIELD_VOID,
            TradeCorrection.new_value == VOID_STATUS,
            PaperTrade.position_id.is_not(None),
        )
    )
    return {int(pid) for pid in rows if pid is not None}
