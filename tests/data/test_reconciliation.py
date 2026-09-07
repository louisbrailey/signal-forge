"""Cross-source reconciliation of daily closes."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.data.reconciliation import reconcile_closes
from signalforge.data.repository import get_or_create_instrument
from signalforge.db.models import DataQualityFlagRow, OHLCVDaily, ReconciliationCheck
from signalforge.domain import DataQualityFlag, LatencyCategory


def _bar(inst_id: int, d: date, close: float, source: str) -> OHLCVDaily:
    return OHLCVDaily(
        instrument_id=inst_id,
        session_date=d,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1_000_000,
        adj_close=close,
        source=source,
        latency_category=LatencyCategory.END_OF_DAY,
        is_simulated=False,
        ingested_at=datetime.now(UTC),
        quality_flags=[],
    )


def test_agreeing_sources_produce_ok_verdicts(session: Session) -> None:
    inst = get_or_create_instrument(session, "AAPL")
    for d, c in [(date(2024, 1, 2), 185.0), (date(2024, 1, 3), 186.0)]:
        session.add(_bar(inst.id, d, c, "stooq"))
        session.add(_bar(inst.id, d, c * 1.0005, "fixture"))  # 0.05% apart
    session.flush()

    summary = reconcile_closes(session, "AAPL", "stooq", "fixture", max_pct_diff=0.5)
    session.commit()
    assert summary.compared == 2
    assert summary.flagged == 0
    assert all(r.verdict == "ok" for r in session.scalars(select(ReconciliationCheck)))
    assert session.scalars(select(DataQualityFlagRow)).first() is None


def test_disagreeing_sources_are_flagged(session: Session) -> None:
    inst = get_or_create_instrument(session, "MSFT")
    session.add(_bar(inst.id, date(2024, 1, 2), 400.0, "stooq"))
    session.add(_bar(inst.id, date(2024, 1, 2), 420.0, "fixture"))  # 5% apart
    session.flush()

    summary = reconcile_closes(session, "MSFT", "stooq", "fixture", max_pct_diff=0.5)
    session.commit()
    assert summary.flagged == 1
    flag = session.scalars(select(DataQualityFlagRow)).one()
    assert flag.flag is DataQualityFlag.RECONCILIATION_DISAGREEMENT
