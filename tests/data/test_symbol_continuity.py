"""Symbol continuity across a corporate action (ticker/name change): the
effective-date detection must ignore contaminating data under the new
symbol, the seam validator's six checks, materialization is idempotent and
verified-only, and mappings are immutable/versioned."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.data.repository import get_daily_bars, get_or_create_instrument
from signalforge.data.symbol_continuity import (
    MAX_UNEXPLAINED_JUMP_PCT,
    build_and_validate_mapping,
    materialize_continuous_series,
)
from signalforge.db.models import OHLCVDaily, SymbolContinuityMapping
from signalforge.db.types import utcnow
from signalforge.domain import LatencyCategory

SOURCE = "test_source"


def _add_bar(
    session: Session,
    symbol: str,
    d: date,
    price: float,
    *,
    volume: float = 1_000_000.0,
    source: str = SOURCE,
    split_factor: float = 1.0,
) -> None:
    inst = get_or_create_instrument(session, symbol)
    session.add(
        OHLCVDaily(
            instrument_id=inst.id,
            session_date=d,
            open=price,
            high=price * 1.01,
            low=price * 0.99,
            close=price,
            volume=volume,
            adj_close=price,
            split_factor=split_factor,
            is_adjusted=True,
            source=source,
            latency_category=LatencyCategory.END_OF_DAY,
            is_simulated=False,
            ingested_at=utcnow(),
            quality_flags=[],
        )
    )


def _seed_clean_pair(session: Session, *, old="OLD", new="NEW") -> None:
    """OLD trades every day 2022-01-03..2022-01-07 (Mon-Fri), NEW picks up the
    very next session (2022-01-10, Monday) with a mundane price move — a
    textbook clean rename."""
    for i, price in enumerate([100.0, 101.0, 99.0, 102.0, 103.0]):
        _add_bar(session, old, date(2022, 1, 3) + timedelta(days=i), price)
    _add_bar(session, new, date(2022, 1, 10), 104.0)
    _add_bar(session, new, date(2022, 1, 11), 105.0)
    session.flush()


def test_effective_date_ignores_pre_transition_contamination_under_new_symbol(
    session: Session,
) -> None:
    """Regression test for the exact bug found while building this module:
    if NEW already has bars from an unrelated earlier period (a different
    entity that held the same ticker), the effective date must be the first
    NEW session strictly AFTER OLD's last session — never simply "the
    earliest bar ever ingested under NEW"."""
    _seed_clean_pair(session)
    # contaminating data: an unrelated entity traded as "NEW" back in 2019,
    # at a wildly different price level, long before OLD's own history here.
    _add_bar(session, "NEW", date(2019, 6, 3), 8.50)
    _add_bar(session, "NEW", date(2019, 6, 4), 8.75)
    session.flush()

    mapping = build_and_validate_mapping(session, old_symbol="OLD", new_symbol="NEW", source=SOURCE)

    assert mapping.validation_status == "verified"
    assert mapping.effective_date == date(2022, 1, 10)  # NOT 2019-06-03
    assert mapping.last_old_session == date(2022, 1, 7)
    diag = mapping.validation_evidence_json["diagnostics"]["pre_transition_contamination"]
    assert diag["found"] is True
    assert diag["n_bars"] == 2
    assert diag["first_date"] == "2019-06-03"
    assert diag["last_date"] == "2019-06-04"


def test_validation_passes_on_a_clean_seam_with_no_contamination(session: Session) -> None:
    _seed_clean_pair(session)
    mapping = build_and_validate_mapping(session, old_symbol="OLD", new_symbol="NEW", source=SOURCE)

    assert mapping.validation_status == "verified"
    assert all(c["passed"] for c in mapping.validation_evidence_json["checks"])
    diag = mapping.validation_evidence_json["diagnostics"]["pre_transition_contamination"]
    assert diag["found"] is False
    assert mapping.derived_symbol == "NEW_CONT"


def test_validation_fails_on_an_unexplained_price_jump(session: Session) -> None:
    for i, price in enumerate([100.0, 101.0]):
        _add_bar(session, "OLD2", date(2022, 1, 3) + timedelta(days=i), price)
    # a >15% overnight jump with no declared split ratio is not plain 1:1 continuity
    _add_bar(session, "NEW2", date(2022, 1, 5), 101.0 * (1 + MAX_UNEXPLAINED_JUMP_PCT / 100 + 0.05))
    session.flush()

    mapping = build_and_validate_mapping(
        session, old_symbol="OLD2", new_symbol="NEW2", source=SOURCE
    )

    assert mapping.validation_status == "failed"
    assert mapping.derived_symbol == ""
    price_check = next(
        c for c in mapping.validation_evidence_json["checks"] if c["name"] == "price_continuity"
    )
    assert price_check["passed"] is False


def test_validation_fails_when_new_symbol_has_no_data_after_old_symbols_last_session(
    session: Session,
) -> None:
    _add_bar(session, "OLD3", date(2022, 1, 3), 100.0)
    _add_bar(session, "NEW3", date(2021, 12, 1), 50.0)  # only BEFORE old's last session
    session.flush()

    with pytest.raises(ValueError, match="nothing to bridge to"):
        build_and_validate_mapping(session, old_symbol="OLD3", new_symbol="NEW3", source=SOURCE)


def test_mapping_requires_both_symbols_already_ingested(session: Session) -> None:
    _add_bar(session, "OLD4", date(2022, 1, 3), 100.0)
    session.flush()
    with pytest.raises(ValueError, match="must be ingested"):
        build_and_validate_mapping(session, old_symbol="OLD4", new_symbol="NOPE", source=SOURCE)


def test_mappings_are_versioned_and_never_overwritten(session: Session) -> None:
    _seed_clean_pair(session, old="OLD5", new="NEW5")
    m1 = build_and_validate_mapping(session, old_symbol="OLD5", new_symbol="NEW5", source=SOURCE)
    m2 = build_and_validate_mapping(session, old_symbol="OLD5", new_symbol="NEW5", source=SOURCE)

    assert m1.id != m2.id
    assert m1.version == 1
    assert m2.version == 2
    n = session.scalar(
        select(SymbolContinuityMapping)
        .where(SymbolContinuityMapping.old_symbol == "OLD5")
        .order_by(SymbolContinuityMapping.version.desc())
    )
    assert n.id == m2.id  # v1 still exists in the DB, untouched, just not "latest"
    v1_still_there = session.get(SymbolContinuityMapping, m1.id)
    assert v1_still_there is not None
    assert v1_still_there.version == 1


def test_materialize_refuses_an_unverified_mapping(session: Session) -> None:
    for i, price in enumerate([100.0, 101.0]):
        _add_bar(session, "OLD6", date(2022, 1, 3) + timedelta(days=i), price)
    _add_bar(session, "NEW6", date(2022, 1, 5), 101.0 * 2.0)  # big unexplained jump -> fails
    session.flush()
    mapping = build_and_validate_mapping(
        session, old_symbol="OLD6", new_symbol="NEW6", source=SOURCE
    )
    assert mapping.validation_status == "failed"

    with pytest.raises(ValueError, match="not 'verified'"):
        materialize_continuous_series(session, mapping)


def test_materialize_is_idempotent_and_never_touches_the_raw_symbols(session: Session) -> None:
    _seed_clean_pair(session, old="OLD7", new="NEW7")
    mapping = build_and_validate_mapping(
        session, old_symbol="OLD7", new_symbol="NEW7", source=SOURCE
    )

    inst1, written1 = materialize_continuous_series(session, mapping)
    assert written1 == 5 + 2  # 5 OLD7 bars + 2 NEW7 bars
    inst2, written2 = materialize_continuous_series(session, mapping)
    assert inst2.id == inst1.id
    assert written2 == 0  # idempotent — nothing recomputed or duplicated

    bridged = get_daily_bars(
        session,
        "NEW7_CONT",
        date(1990, 1, 1),
        date.today(),
        source=f"continuity_bridge:{mapping.id}",
    )
    assert len(bridged) == 7
    assert bridged[0].session_date == date(2022, 1, 3)
    assert bridged[-1].session_date == date(2022, 1, 11)

    # the raw symbols' own bars are completely untouched
    old_raw = get_daily_bars(session, "OLD7", date(1990, 1, 1), date.today(), source=SOURCE)
    new_raw = get_daily_bars(session, "NEW7", date(1990, 1, 1), date.today(), source=SOURCE)
    assert len(old_raw) == 5
    assert len(new_raw) == 2


def test_materialize_refuses_to_duplicate_onto_a_derived_symbol_from_a_different_mapping(
    session: Session,
) -> None:
    """Regression test for a review finding: _derived_symbol_name has no
    version component, so materializing a second mapping version for the
    same (old,new) pair onto the same already-materialized derived symbol
    must refuse rather than silently duplicate every bridged session date."""
    _seed_clean_pair(session, old="OLD8", new="NEW8")
    m1 = build_and_validate_mapping(session, old_symbol="OLD8", new_symbol="NEW8", source=SOURCE)
    materialize_continuous_series(session, m1)

    m2 = build_and_validate_mapping(session, old_symbol="OLD8", new_symbol="NEW8", source=SOURCE)
    assert m2.id != m1.id  # a genuinely different (though here identical-evidence) mapping row

    with pytest.raises(ValueError, match="already holds bars from a different mapping"):
        materialize_continuous_series(session, m2)

    # m1's bridge is untouched — no duplicate session dates were written
    bridged = get_daily_bars(session, "NEW8_CONT", date(1990, 1, 1), date.today())
    assert len(bridged) == 7
    assert len({b.session_date for b in bridged}) == 7  # no duplicate dates


def test_materialize_raises_rather_than_report_false_success_if_source_data_vanished(
    session: Session,
) -> None:
    """Regression test: if a mapping's source data is gone by the time
    materialize runs (purged/re-tagged after validation), it must raise —
    not silently return bars_written=0 indistinguishable from genuine
    idempotency."""
    _seed_clean_pair(session, old="OLD9", new="NEW9")
    mapping = build_and_validate_mapping(
        session, old_symbol="OLD9", new_symbol="NEW9", source=SOURCE
    )

    # simulate the source data vanishing after validation but before materialize
    for b in get_daily_bars(session, "OLD9", date(1990, 1, 1), date.today(), source=SOURCE):
        b.source = "some_other_provider"
    for b in get_daily_bars(session, "NEW9", date(1990, 1, 1), date.today(), source=SOURCE):
        b.source = "some_other_provider"
    session.flush()

    with pytest.raises(ValueError, match="no longer available"):
        materialize_continuous_series(session, mapping)


def test_same_source_provenance_check_is_genuinely_reachable_and_can_fail(session: Session) -> None:
    """Regression test: same_source_provenance must be able to actually fail
    — not be tautologically guaranteed true by the same filter used to fetch
    the bars it inspects."""
    _seed_clean_pair(session, old="OLD10", new="NEW10")
    # contaminate OLD10 with a bar from an unrelated source, anywhere in its history
    _add_bar(session, "OLD10", date(2010, 1, 4), 50.0, source="some_other_provider")
    session.flush()

    mapping = build_and_validate_mapping(
        session, old_symbol="OLD10", new_symbol="NEW10", source=SOURCE
    )
    assert mapping.validation_status == "failed"
    check = next(
        c
        for c in mapping.validation_evidence_json["checks"]
        if c["name"] == "same_source_provenance"
    )
    assert check["passed"] is False
    assert "some_other_provider" in check["detail"]
