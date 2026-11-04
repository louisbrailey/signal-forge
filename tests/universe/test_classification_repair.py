from datetime import UTC, date, datetime

from sqlalchemy import select

from signalforge.config.research import UniversePipelineConfig
from signalforge.data.repository import get_or_create_instrument
from signalforge.db.models import AuditLog, UniverseTicker
from signalforge.universe.normalize import normalize_symbols


def test_normalization_repairs_reference_type_and_audits_once(session):
    inst = get_or_create_instrument(session, "SPY")
    session.add(
        UniverseTicker(
            ticker="SPY",
            security_type="ETF",
            first_seen=date(2020, 1, 1),
            last_seen=date(2026, 1, 1),
            refreshed_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    session.flush()
    report = normalize_symbols(session, ["SPY"], UniversePipelineConfig(), extra=())
    session.flush()
    assert inst.instrument_type == "etf"
    assert report.classifications_corrected == 1
    events = list(
        session.scalars(
            select(AuditLog).where(AuditLog.action == "instrument.classification_reconciled")
        )
    )
    assert len(events) == 1
    assert events[0].before_json == {"instrument_type": "stock"}
    assert events[0].after_json["source_table"] == "universe_ticker"
    assert events[0].after_json["instrument_type"] == "etf"
    # Routine bar ingestion with its default arguments must not demote it.
    assert get_or_create_instrument(session, "SPY").instrument_type == "etf"
    again = normalize_symbols(session, ["SPY"], UniversePipelineConfig(), extra=())
    assert again.classifications_corrected == 0


def test_absent_reference_does_not_reclassify_an_existing_etf(session):
    inst = get_or_create_instrument(session, "SPY", instrument_type="etf")
    report = normalize_symbols(session, ["SPY"], UniversePipelineConfig(), extra=())
    assert inst.instrument_type == "etf"
    assert report.classifications_corrected == 0
