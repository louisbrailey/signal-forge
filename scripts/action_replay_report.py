"""Action-aware daily research; operating DB metadata read only, no frozen study access."""

import argparse
import json
import sqlite3
from datetime import date
from pathlib import Path

from signalforge.backtest.actions import TickerChange
from signalforge.research.action_replay import compare, load_dataset


def read_metadata(database, listing_evidence=None):
    if not database.is_file():
        raise ValueError("Existing database required")
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as c:
        c.execute("PRAGMA query_only=ON")
        c.execute("BEGIN")
        if c.execute("SELECT 1 FROM sqlite_master WHERE name LIKE 'comparison_%'").fetchone():
            raise ValueError("Frozen comparison databases excluded")
        metadata = {
            s: {"sector": sector, "instrument_type": kind}
            for s, sector, kind in c.execute("SELECT symbol,sector,instrument_type FROM instrument")
        }
        mappings = []
        for old, new, day, source, evidence in c.execute(
            """SELECT old_symbol,new_symbol,effective_date,
            source,validation_evidence_json FROM symbol_continuity_mapping
            WHERE validation_status='verified' AND ratio=1
            AND version=(SELECT MAX(m.version) FROM symbol_continuity_mapping m
                WHERE m.old_symbol=symbol_continuity_mapping.old_symbol
                  AND m.new_symbol=symbol_continuity_mapping.new_symbol)"""
        ):
            mappings.append(TickerChange(old, new, date.fromisoformat(day), source, evidence))
    if listing_evidence is not None:
        refs = json.loads(listing_evidence.read_text())
        for symbol, ref in refs.items():
            if ref["source"] != "massive" or not ref.get("sha256") or not ref.get("endpoint"):
                raise ValueError("Listing reference provenance required")
            if ref.get("list_date"):
                metadata[symbol]["listing_date"] = ref["list_date"]
            if ref.get("type") == "ETF":
                metadata[symbol]["instrument_type"] = "etf"
            metadata[symbol]["listing_reference"] = json.dumps(ref, sort_keys=True)
    return metadata, tuple(mappings)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("snapshot", type=Path)
    p.add_argument("--database", type=Path, required=True)
    p.add_argument("--listing-evidence", type=Path)
    a = p.parse_args()
    metadata, mappings = read_metadata(a.database, a.listing_evidence)
    print(json.dumps(compare(load_dataset(a.snapshot, mappings), metadata), default=str, indent=2))
