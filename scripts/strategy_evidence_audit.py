#!/usr/bin/env python3
"""Read saved strategy evidence without running tests of the market or writing a database.

Usage: PYTHONPATH=src uv run python scripts/strategy_evidence_audit.py /path/to/database.sqlite
Only published aggregate backtest metrics are read; sealed and study tables are untouched.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from signalforge.research.evidence import evidence_inventory


def audit(path: Path) -> dict:
    if not path.is_file():
        raise ValueError("An existing SQLite database is required")

    def connect() -> sqlite3.Connection:
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        connection.execute("PRAGMA query_only=ON")
        return connection

    engine = create_engine("sqlite://", creator=connect)
    try:
        with Session(engine, autoflush=False) as session:
            return evidence_inventory(session)
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.database), indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
