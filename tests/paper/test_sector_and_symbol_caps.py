"""Sector cap: unknown is ONE capped bucket; legacy oversized positions count.

Before 2026-10-03 the ledger only applied the 20% sector budget when the
instrument's sector was known, and ``instrument.sector`` was blank on every
live row — so the cap never operated. Now a blank/unknown sector is the single
conservative bucket ``UNKNOWN``, capped at 20% like any other sector.

All arithmetic below is on a book with equity 10,000 and a candidate that fills
at 100.06 (entry 100.00 * 1.00055) with stop 96 (adverse stop fill 95.95,
risk/share 4.11).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import Candidate, Instrument, PaperPosition, PaperTrade
from signalforge.domain import PositionSide
from signalforge.paper.ledger import UNKNOWN_SECTOR, sector_bucket
from tests.paper.test_ledger_risk_safety import ON, accept, bar, holding


def _set_sector(session: Session, cand: Candidate, sector: str) -> None:
    inst = session.get(Instrument, cand.instrument_id)
    assert inst is not None
    inst.sector = sector
    session.flush()


@pytest.mark.parametrize("raw", ["", "   ", None, "unknown", "Unknown", "UNKNOWN_SECTOR", "n/a"])
def test_blank_and_unknown_spellings_share_the_unknown_bucket(raw: str | None) -> None:
    assert sector_bucket(raw) == UNKNOWN_SECTOR


def test_known_sectors_are_case_and_whitespace_insensitive() -> None:
    assert sector_bucket(" Technology ") == sector_bucket("technology") == "technology"
    assert sector_bucket("ETF:SPY") == "etf:spy" != sector_bucket("ETF:QQQ")


def test_unknown_sector_is_capped_as_one_sector_never_unlimited(
    session: Session, passing_candidate: Candidate, account
) -> None:
    """Two unknown holdings (one blank, one literally "unknown") total 1,950 of
    the 2,000 UNKNOWN budget (20% of 10,000). A candidate whose own sector is
    blank gets floor(50 / 100.06) = 0 shares. Under the old rule it had no
    sector cap at all."""
    _set_sector(session, passing_candidate, "")
    holding(session, account, passing_candidate, qty=100, price=10, sector=None, stop=10)
    holding(session, account, passing_candidate, qty=95, price=10, sector="unknown", stop=10)
    account.cash = Decimal("8050")
    with pytest.raises(ValueError, match="limits"):
        accept(session, passing_candidate)
    assert account.cash == Decimal("8050")


def test_unknown_bucket_budget_is_recorded_in_the_evidence(
    session: Session, passing_candidate: Candidate, account
) -> None:
    """UNKNOWN already holds 1,400; budget 2,000 - 1,400 = 600 -> floor(600 /
    100.06) = 5 shares, tighter than the symbol ceiling (1,000 / 100.06 -> 9)."""
    _set_sector(session, passing_candidate, "")
    holding(session, account, passing_candidate, qty=140, price=10, sector="", stop=10)
    account.cash = Decimal("8600")
    res = accept(session, passing_candidate)
    assert res.shares == 5
    risk = session.get(PaperTrade, res.paper_trade_id).plan_json["risk_decision"]  # type: ignore[union-attr]
    assert risk["sector"] == UNKNOWN_SECTOR
    assert Decimal(risk["sector_before"]) == Decimal("1400")
    assert risk["share_caps"]["sector"] == 5 and risk["share_caps"]["symbol"] == 9
    assert risk["binding_caps"] == ["sector"]


def test_a_known_sector_does_not_consume_the_unknown_budget(
    session: Session, passing_candidate: Candidate, account
) -> None:
    """Tech holds 1,950; the candidate is UNKNOWN, so its own bucket is empty and
    the symbol ceiling binds: floor(1,000 / 100.06) = 9."""
    _set_sector(session, passing_candidate, "")
    holding(session, account, passing_candidate, qty=195, price=10, sector="Tech", stop=10)
    account.cash = Decimal("8050")
    assert accept(session, passing_candidate).shares == 9


def test_each_non_sector_etf_is_its_own_bucket_and_sector_etfs_join_their_sector(
    session: Session, passing_candidate: Candidate, account
) -> None:
    # ETF:QQQ holds 1,950 -> does not limit an ETF:SPY candidate (symbol binds: 9).
    _set_sector(session, passing_candidate, "ETF:SPY")
    held = holding(
        session, account, passing_candidate, qty=195, price=10, sector="ETF:QQQ", stop=10
    )
    account.cash = Decimal("8050")
    assert accept(session, passing_candidate).shares == 9

    # A sector SPDR is labelled with its sector ("Technology"), so a technology
    # stock shares its bucket: relabel the holding and a second candidate-symbol
    # purchase is refused by the sector budget (and by the symbol budget).
    held_inst = session.get(Instrument, held.instrument_id)
    assert held_inst is not None
    held_inst.sector = "Technology"
    _set_sector(session, passing_candidate, "technology")
    bar(session, passing_candidate, ON)
    with pytest.raises(ValueError, match="limits"):
        accept(session, passing_candidate)


def test_legacy_oversized_position_is_not_resized_but_counts_toward_caps(
    session: Session, passing_candidate: Candidate, account
) -> None:
    """Report §3 / release note: positions opened before the caps existed are
    left as they are, but they must still count for NEW entries.

    A pre-fix position of 15 shares in the candidate's own symbol, marked at
    100.00, is 1,500 = 15% of the 10,000 book — over the 10% symbol ceiling
    (1,000). Symbol budget = 1,000 - 1,500 < 0 -> 0 shares: refused."""
    legacy = PaperPosition(
        account_id=account.id,
        instrument_id=passing_candidate.instrument_id,
        horizon=passing_candidate.horizon,
        side=PositionSide.LONG,
        qty=15,
        avg_price=Decimal("100"),
        stop_level=96.0,
        opened_at=datetime(2024, 1, 31, tzinfo=UTC),
    )
    session.add(legacy)
    bar(session, passing_candidate, ON)  # current clean mark at 100.00
    account.cash = Decimal("8500")

    with pytest.raises(ValueError, match="limits"):
        accept(session, passing_candidate)

    session.refresh(legacy)
    assert legacy.qty == 15 and legacy.closed_at is None  # not resized, not closed
    assert account.cash == Decimal("8500")
    assert session.scalars(select(PaperTrade)).first() is None


def test_legacy_oversized_position_also_consumes_sector_and_open_risk_budgets(
    session: Session, passing_candidate: Candidate, account
) -> None:
    """The same kind of legacy position in ANOTHER Tech symbol: 190 shares at
    10.00 = 1,900 (19%, over the 10% symbol ceiling, never resized). It leaves
    Tech 2,000 - 1,900 = 100 -> floor(100 / 100.06) = 0 shares for a new Tech
    entry. With stop 9.00 its open risk is (10 - 9.00 * 0.99945 -> 9.00) * 190 =
    190.00, which also exceeds the configured 1.5% (150) open-risk limit."""
    holding(session, account, passing_candidate, qty=190, price=10, sector="Tech", stop=9)
    account.cash = Decimal("8100")
    with pytest.raises(ValueError, match="limits"):
        accept(session, passing_candidate)
