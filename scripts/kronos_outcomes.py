#!/usr/bin/env python3
"""Resolve bounded shadow diagnostics without changing trading state."""

import argparse
import json
from pathlib import Path

from signalforge.kronos.outcome_store import run

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.source_db, args.ledger), sort_keys=True))
