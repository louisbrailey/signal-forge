"""Cross-source agreement checks (ARCHITECTURE.md §8.3).

Where two sources cover the same daily close, compare them. A disagreement above
the configured threshold writes a ``reconciliation_disagreement`` quality flag and
is used downstream to downgrade any candidate that depends on that value.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import DataQualityFlagRow, Instrument, OHLCVDaily, ReconciliationCheck
from signalforge.db.types import utcnow
from signalforge.domain import DataQualityFlag


@dataclass
class ReconciliationSummary:
    symbol: str
    compared: int = 0
    flagged: int = 0
    max_pct_diff: float = 0.0


def reconcile_closes(
    session: Session,
    symbol: str,
    source_a: str,
    source_b: str,
    *,
    max_pct_diff: float,
    start: date | None = None,
    end: date | None = None,
) -> ReconciliationSummary:
    inst = session.scalar(select(Instrument).where(Instrument.symbol == symbol.strip().upper()))
    summary = ReconciliationSummary(symbol=symbol.upper())
    if inst is None:
        return summary

    def _closes(source: str) -> dict[date, float]:
        stmt = select(OHLCVDaily.session_date, OHLCVDaily.close).where(
            OHLCVDaily.instrument_id == inst.id, OHLCVDaily.source == source
        )
        if start is not None:
            stmt = stmt.where(OHLCVDaily.session_date >= start)
        if end is not None:
            stmt = stmt.where(OHLCVDaily.session_date <= end)
        return {d: c for d, c in session.execute(stmt)}

    a, b = _closes(source_a), _closes(source_b)
    now = utcnow()
    for d in sorted(a.keys() & b.keys()):
        va, vb = a[d], b[d]
        denom = max(abs(va), abs(vb), 1e-9)
        pct = abs(va - vb) / denom * 100.0
        summary.compared += 1
        summary.max_pct_diff = max(summary.max_pct_diff, pct)
        verdict = "flagged" if pct > max_pct_diff else "ok"
        session.add(
            ReconciliationCheck(
                instrument_id=inst.id,
                field="close",
                session_date=d,
                source_a=source_a,
                source_b=source_b,
                value_a=va,
                value_b=vb,
                pct_diff=pct,
                verdict=verdict,
                checked_at=now,
            )
        )
        if verdict == "flagged":
            summary.flagged += 1
            session.add(
                DataQualityFlagRow(
                    flag=DataQualityFlag.RECONCILIATION_DISAGREEMENT,
                    provider=f"{source_a}|{source_b}",
                    instrument_id=inst.id,
                    session_date=d,
                    detail=f"close {va} vs {vb} ({pct:.2f}% > {max_pct_diff}%)",
                )
            )
    return summary
