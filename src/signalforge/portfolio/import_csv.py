"""Offline broker-CSV parsing (Phase 1 §1.8).

STRICT RULE: no imports here may touch the network (no httpx / requests / socket /
urllib / data.adapters). Enforced by import-linter contract S2 and
``tests/safety/test_import_offline.py``.

Phase 0: shapes + a stdlib-only header sniff. Full broker-format detection and
persistence land in Phase 1.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class ImportedPosition:
    symbol: str
    quantity: Decimal
    cost_basis: Decimal | None
    source_row: int


@dataclass(frozen=True, slots=True)
class ImportPreview:
    detected_format: str
    columns: tuple[str, ...]
    row_count: int


def sniff(csv_text: str) -> ImportPreview:
    """Return a lightweight preview of an uploaded CSV without persisting anything."""
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    if not rows:
        return ImportPreview(detected_format="unknown", columns=(), row_count=0)
    header = tuple(c.strip() for c in rows[0])
    lowered = {c.lower() for c in header}
    if {"run date", "action", "symbol"} <= lowered:
        fmt = "fidelity_history"  # transaction history export
    elif {"symbol", "quantity"} <= lowered or {"symbol", "qty"} <= lowered:
        fmt = "generic_positions"
    else:
        fmt = "unknown"
    return ImportPreview(detected_format=fmt, columns=header, row_count=max(0, len(rows) - 1))
