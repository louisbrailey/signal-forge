"""Offline CSV import + analytics (invariant S2: no network, never scanned)."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge.db.models import (
    Candidate,
    ImportedPosition,
    ImportedTransaction,
    Instrument,
    PortfolioImport,
)
from signalforge.portfolio import import_csv, portfolio_analytics, sniff

POSITIONS_CSV = (
    "Symbol,Quantity,Cost Basis,Account\n"
    "AAPL,100,15000,Brokerage\n"
    "MSFT,50,18000,Brokerage\n"
    "XOM,80,7000,IRA\n"
)
FIDELITY_HISTORY_CSV = (
    "Some disclaimer line\n"
    "Run Date,Action,Symbol,Quantity,Price ($),Amount ($)\n"
    "01/02/2024,YOU BOUGHT,AAPL,10,150.00,-1500.00\n"
    "01/09/2024,YOU SOLD,AAPL,-5,160.00,800.00\n"
)

COINBASE_HISTORY_CSV = (
    "Transactions report\n"
    "Timestamp,Transaction Type,Asset,Quantity Transacted,Spot Price at Transaction,"
    "Total (inclusive of fees and/or spread)\n"
    "2026-10-27T15:30:00Z,Buy,BTC,0.01,100000,1001\n"
)


def test_sniff_detects_kinds() -> None:
    assert sniff(POSITIONS_CSV).kind == "positions"
    assert sniff(FIDELITY_HISTORY_CSV).kind == "transactions"
    assert sniff(FIDELITY_HISTORY_CSV).detected_format == "fidelity_history"
    assert sniff("a,b,c\n1,2,3\n").kind == "unknown"


def test_import_positions_persists_rows(session: Session) -> None:
    s = import_csv(session, "positions.csv", POSITIONS_CSV)
    session.flush()
    assert s.positions_imported == 3
    rows = list(session.scalars(select(ImportedPosition)))
    assert {r.symbol for r in rows} == {"AAPL", "MSFT", "XOM"}
    assert rows[0].cost_basis == Decimal("15000")


def test_import_is_idempotent_by_content_hash(session: Session) -> None:
    first = import_csv(session, "p.csv", POSITIONS_CSV)
    session.flush()
    second = import_csv(session, "p-again.csv", POSITIONS_CSV)
    assert second.already_imported is True
    assert second.batch_id == first.batch_id
    assert session.scalar(select(func.count()).select_from(PortfolioImport)) == 1


def test_import_transactions(session: Session) -> None:
    s = import_csv(session, "hist.csv", FIDELITY_HISTORY_CSV)
    session.flush()
    assert s.transactions_imported == 2
    txns = list(session.scalars(select(ImportedTransaction)))
    assert txns[0].action.upper().startswith("YOU BOUGHT")
    assert txns[0].symbol == "AAPL"


def test_coinbase_transaction_report_is_offline_and_preserves_time(session: Session) -> None:
    assert sniff(COINBASE_HISTORY_CSV).detected_format == "coinbase_history"
    summary = import_csv(session, "coinbase.csv", COINBASE_HISTORY_CSV)
    assert summary.transactions_imported == 1
    txn = session.scalar(select(ImportedTransaction))
    assert txn is not None
    assert txn.symbol == "BTC"
    assert txn.quantity == Decimal("0.01")
    assert txn.trade_date is not None and txn.trade_date.hour == 15
    assert session.scalar(select(func.count()).select_from(Candidate)) == 0


def test_manual_webull_and_coinbase_holdings_use_generic_format(session: Session) -> None:
    summary = import_csv(
        session,
        "holdings.csv",
        "Symbol,Quantity,Cost Basis,Account\nAAPL,2,300,Webull\nBTC,0.01,800,Coinbase\n",
    )
    assert summary.positions_imported == 2
    assert {row.symbol for row in session.scalars(select(ImportedPosition))} == {"AAPL", "BTC"}


def test_analytics_reports_exposure_and_never_scans(session: Session) -> None:
    session.add(Instrument(symbol="AAPL", sector="Tech"))
    session.add(Instrument(symbol="MSFT", sector="Tech"))
    session.flush()
    import_csv(session, "p.csv", POSITIONS_CSV)
    session.flush()

    a = portfolio_analytics(session)
    assert a["positions"] == 3
    assert a["exposure"]["by_sector_pct"]["Tech"] > 50  # AAPL+MSFT dominate
    assert "separate" in a["separation_note"]
    # nothing entered the candidate table
    assert session.scalar(select(func.count()).select_from(Candidate)) == 0
