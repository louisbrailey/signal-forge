"""Offline broker-CSV import for portfolio analytics only (invariant S2).

STRICT: no imports here may touch the network (no httpx / requests / socket /
urllib / signalforge.data). Enforced by the import-linter S2 contract and
``tests/safety/test_s2_import_offline.py``.

Imported positions/transactions are for exposure/concentration visualisation.
They are NEVER fed to the scanner as tradable candidates — different tables,
different code paths.
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import (
    ImportedPosition,
    ImportedTransaction,
    Instrument,
    PortfolioImport,
)
from signalforge.db.types import utcnow
from signalforge.portfolio.mapping import (
    POSITION_FORMATS,
    TRANSACTION_FORMATS,
    pick,
)
from signalforge.risk.portfolio import Holding, exposure_report


@dataclass(frozen=True, slots=True)
class ImportPreview:
    detected_format: str
    kind: str  # "positions" | "transactions" | "unknown"
    columns: tuple[str, ...]
    row_count: int


@dataclass
class ImportSummary:
    batch_id: int
    detected_format: str
    kind: str
    positions_imported: int = 0
    transactions_imported: int = 0
    already_imported: bool = False
    warnings: list[str] = field(default_factory=list)


def _num(raw: str | None) -> Decimal | None:
    if raw is None:
        return None
    s = raw.strip().replace(",", "").replace("$", "").replace("(", "-").replace(")", "")
    if not s or s in {"-", "--", "n/a", "N/A"}:
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def sniff(csv_text: str) -> ImportPreview:
    rows = list(csv.reader(io.StringIO(csv_text)))
    # Some brokers prepend disclaimer lines; find the first row that looks like a header.
    header_idx = next((i for i, r in enumerate(rows) if any("symbol" in c.lower() for c in r)), 0)
    if not rows or header_idx >= len(rows):
        return ImportPreview("unknown", "unknown", (), 0)
    header = [c.strip() for c in rows[header_idx]]
    lowered = {c.lower() for c in header}
    data_rows = max(0, len(rows) - header_idx - 1)

    for name, tc in TRANSACTION_FORMATS.items():
        if pick(header, tc.date) and pick(header, tc.action) and pick(header, tc.symbol):
            return ImportPreview(name, "transactions", tuple(header), data_rows)
    for name, pc in POSITION_FORMATS.items():
        if pick(header, pc.symbol) and pick(header, pc.quantity):
            return ImportPreview(name, "positions", tuple(header), data_rows)
    if {"symbol"} <= lowered:
        return ImportPreview("unknown_positions", "positions", tuple(header), data_rows)
    return ImportPreview("unknown", "unknown", tuple(header), data_rows)


def _dictreader_from(csv_text: str) -> csv.DictReader[str]:
    rows = list(csv.reader(io.StringIO(csv_text)))
    header_idx = next((i for i, r in enumerate(rows) if any("symbol" in c.lower() for c in r)), 0)
    body = "\n".join(",".join(_quote(c) for c in r) for r in rows[header_idx:])
    return csv.DictReader(io.StringIO(body))


def _quote(cell: str) -> str:
    if "," in cell or '"' in cell:
        return '"' + cell.replace('"', '""') + '"'
    return cell


def import_csv(
    session: Session, filename: str, csv_text: str, *, actor: str = "local-user"
) -> ImportSummary:
    sha = hashlib.sha256(csv_text.encode("utf-8")).hexdigest()
    existing = session.scalar(select(PortfolioImport).where(PortfolioImport.sha256 == sha))
    preview = sniff(csv_text)
    if existing is not None:
        return ImportSummary(
            batch_id=existing.id,
            detected_format=existing.broker_format,
            kind=preview.kind,
            already_imported=True,
        )

    batch = PortfolioImport(
        filename=filename,
        sha256=sha,
        broker_format=preview.detected_format,
        row_count=preview.row_count,
        imported_at=utcnow(),
    )
    session.add(batch)
    session.flush()
    summary = ImportSummary(
        batch_id=batch.id, detected_format=preview.detected_format, kind=preview.kind
    )

    reader = _dictreader_from(csv_text)
    header = list(reader.fieldnames or [])

    if preview.kind == "transactions":
        tcols = (
            TRANSACTION_FORMATS.get(preview.detected_format)
            or TRANSACTION_FORMATS["generic_history"]
        )
        c_date, c_action = pick(header, tcols.date), pick(header, tcols.action)
        c_sym, c_qty = pick(header, tcols.symbol), pick(header, tcols.quantity)
        c_price, c_amt = pick(header, tcols.price), pick(header, tcols.amount)
        for i, row in enumerate(reader, start=1):
            sym = (row.get(c_sym or "", "") or "").strip().upper()
            if not sym:
                continue
            session.add(
                ImportedTransaction(
                    batch_id=batch.id,
                    trade_date=_parse_date(row.get(c_date or "", "")),
                    action=(row.get(c_action or "", "") or "").strip()[:24],
                    symbol=sym[:16],
                    quantity=_num(row.get(c_qty or "")),
                    price=_num(row.get(c_price or "")),
                    amount=_num(row.get(c_amt or "")),
                    source_row=i,
                )
            )
            summary.transactions_imported += 1
    else:
        pcols = (
            POSITION_FORMATS.get(preview.detected_format) or POSITION_FORMATS["generic_positions"]
        )
        c_sym, c_qty = pick(header, pcols.symbol), pick(header, pcols.quantity)
        c_cost = pick(header, pcols.cost_basis)
        c_acct = pick(header, pcols.account)
        for i, row in enumerate(reader, start=1):
            sym = (row.get(c_sym or "", "") or "").strip().upper()
            qty = _num(row.get(c_qty or ""))
            if not sym or qty is None:
                continue
            session.add(
                ImportedPosition(
                    batch_id=batch.id,
                    symbol=sym[:16],
                    quantity=qty,
                    cost_basis=_num(row.get(c_cost or "")),
                    account_label=(row.get(c_acct or "", "") or "").strip()[:60],
                    source_row=i,
                )
            )
            summary.positions_imported += 1

    session.flush()
    return summary


def _parse_date(raw: str) -> datetime | None:
    raw = raw.strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%d-%b-%Y"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=utcnow().tzinfo)
        except ValueError:
            continue
    return None


def portfolio_analytics(session: Session, *, batch_id: int | None = None) -> dict[str, object]:
    """Exposure / concentration from imported positions (analytics only).

    Market value = the CSV's cost_basis when present, else quantity * latest
    close from our own bars, else quantity alone. Sector comes from a known
    instrument row when we have one, else 'unknown'.
    """
    stmt = select(ImportedPosition)
    if batch_id is not None:
        stmt = stmt.where(ImportedPosition.batch_id == batch_id)
    positions = list(session.scalars(stmt))
    if not positions:
        return {"positions": 0, "note": "no imported positions"}

    holdings: list[Holding] = []
    rows_out: list[dict[str, object]] = []
    total_value = Decimal("0")
    for p in positions:
        inst = session.scalar(select(Instrument).where(Instrument.symbol == p.symbol))
        mv = float(p.cost_basis) if p.cost_basis is not None else float(p.quantity)
        total_value += Decimal(str(mv))
        holdings.append(
            Holding(
                symbol=p.symbol, sector=(inst.sector if inst else "") or "unknown", market_value=mv
            )
        )
        rows_out.append(
            {
                "symbol": p.symbol,
                "quantity": float(p.quantity),
                "value": round(mv, 2),
                "sector": (inst.sector if inst else "") or "unknown",
                "known_instrument": inst is not None,
            }
        )

    report = exposure_report(holdings, account_equity=float(total_value))
    return {
        "positions": len(positions),
        "total_value": round(float(total_value), 2),
        "rows": rows_out,
        "exposure": report.to_dict(),
        "separation_note": (
            "These are long-term holdings imported for analytics. They are kept "
            "entirely separate from the paper-trading ledger and are never scanned "
            "as tradable candidates."
        ),
    }
