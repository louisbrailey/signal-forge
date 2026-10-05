"""Append-only corrections to immutable paper_trade rows (invariant S9)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from signalforge.db.models import PaperTrade, TradeCorrection
from signalforge.db.paper_voids import FIELD_VOID, VOID_STATUS, voided_position_ids
from signalforge.observability import get_logger

__all__ = ["FIELD_VOID", "VOID_STATUS", "record_correction", "voided_position_ids"]

_log = get_logger("paper.corrections")


def record_correction(
    session: Session,
    paper_trade_id: int,
    *,
    field: str,
    old_value: str,
    new_value: str,
    reason: str,
    actor: str = "local-user",
) -> int:
    if session.get(PaperTrade, paper_trade_id) is None:
        raise ValueError(f"paper_trade {paper_trade_id} not found")
    corr = TradeCorrection(
        paper_trade_id=paper_trade_id,
        field=field,
        old_value=old_value,
        new_value=new_value,
        reason=reason,
        actor=actor,
    )
    session.add(corr)
    session.flush()
    _log.info("paper.correction", paper_trade=paper_trade_id, field=field, actor=actor)
    return corr.id
