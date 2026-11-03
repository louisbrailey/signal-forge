#!/usr/bin/env python3
"""Print read-only income-target diagnostics from an explicit local JSON evidence file."""

import argparse
import hashlib
import json
from pathlib import Path

from signalforge.research.income_targets import IncomeEvidence, assess_income_targets

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    source = args.evidence.read_bytes()
    report = assess_income_targets(IncomeEvidence.model_validate_json(source))
    report["input_sha256"] = hashlib.sha256(source).hexdigest()
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
