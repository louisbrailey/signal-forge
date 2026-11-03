"""Fetch a bounded, resumable offline raw-price/actions dataset; no account writes."""

import argparse
from datetime import date
from pathlib import Path

from dotenv import dotenv_values

from signalforge.data.accounting_snapshot import fetch_accounting_snapshot
from signalforge.data.adapters.massive import MassiveAdapter

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("destination", type=Path)
    p.add_argument("--env-file", type=Path, required=True)
    p.add_argument("--symbols", nargs="+", required=True)
    p.add_argument("--since", type=date.fromisoformat, required=True)
    p.add_argument("--until", type=date.fromisoformat, required=True)
    a = p.parse_args()
    key = dotenv_values(a.env_file).get("MARKET_DATA_API_KEY")
    if not key:
        raise SystemExit("MARKET_DATA_API_KEY is not set")
    manifest = fetch_accounting_snapshot(
        MassiveAdapter(api_key=key, min_request_spacing_s=12.1),
        a.destination,
        a.symbols,
        a.since,
        a.until,
    )
    print(f"Completed {len(manifest['records'])} endpoint snapshots; END_OF_DAY, adjusted=false")
