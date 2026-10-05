"""Pages that show the paper account show EVERY book and the combined
per-symbol exposure across books (operator decision 2026-10-03)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from signalforge.db.models import (
    Instrument,
    PaperAccount,
    PaperPosition,
    Strategy,
    StrategyVersion,
)
from signalforge.db.session import session_scope
from signalforge.domain import Horizon, PositionSide, StrategyStatus


@pytest.fixture
def two_books(registered_client: TestClient) -> TestClient:
    with session_scope(write=True) as s:
        inst = Instrument(symbol="MSFT", name="Microsoft", instrument_type="stock")
        s.add(inst)
        s.flush()
        book_ids = []
        for name, horizon, acct_name, qty in (
            ("trend_short", Horizon.SHORT_SWING, "book-sv-short", 3),
            ("trend_medium", Horizon.MEDIUM_SWING, "default", 5),
        ):
            strat = Strategy(name=name, horizon=horizon, status=StrategyStatus.PAPER_APPROVED)
            s.add(strat)
            s.flush()
            ver = StrategyVersion(
                strategy_id=strat.id,
                version="0.2.0",
                git_sha="x",
                spec_json={},
                status=StrategyStatus.PAPER_APPROVED,
            )
            s.add(ver)
            s.flush()
            acct = PaperAccount(
                name=acct_name,
                initial_cash=Decimal("30000"),
                cash=Decimal("30000") - Decimal("500") * qty,
                strategy_version_id=ver.id,
            )
            s.add(acct)
            s.flush()
            book_ids.append(acct.id)
            s.add(
                PaperPosition(
                    account_id=acct.id,
                    instrument_id=inst.id,
                    strategy_version_id=ver.id,
                    horizon=horizon,
                    side=PositionSide.LONG,
                    qty=qty,
                    avg_price=Decimal("500"),
                    stop_level=480.0,
                    opened_at=datetime(2026, 10, 1, 21, 30, tzinfo=UTC),
                )
            )
    return registered_client


@pytest.mark.parametrize("path", ["/portfolio", "/paper-console"])
def test_pages_show_each_book_and_combined_symbol_exposure(
    two_books: TestClient, path: str
) -> None:
    html = two_books.get(path).text
    assert 'id="paper-books"' in html and 'id="paper-symbol-exposure"' in html
    # one row per book, labelled by strategy and version
    assert "trend_short v0.2.0" in html and "trend_medium v0.2.0" in html
    assert "<code>book-sv-short</code>" in html and "<code>default</code>" in html
    # combined across books: MSFT 3 + 5 = 8 shares at 500 = 4,000 = 6.67% of 60,000
    assert "Symbol (all books combined)" in html
    assert "$4000.00" in html and "6.67%" in html
    assert "caps and the daily auto-simulation cap apply per book" in html


def test_overview_lists_each_book(two_books: TestClient) -> None:
    html = two_books.get("/").text
    assert "trend_short v0.2.0" in html and "trend_medium v0.2.0" in html
    assert "$60000.00" in html  # combined equity of the two books


def test_console_says_the_daily_cap_is_per_book(two_books: TestClient) -> None:
    assert "per book" in two_books.get("/paper-console").text
