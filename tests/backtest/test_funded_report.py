import importlib.util
import sqlite3
from datetime import date
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "funded_replay_report", Path(__file__).parents[2] / "scripts/funded_replay_report.py"
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_report_refuses_frozen_database(tmp_path):
    path = tmp_path / "study.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE comparison_daily(day TEXT)")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="Frozen"):
        module.replay(path, ["SPY"], date(2024, 1, 2), date(2024, 1, 10))
    assert path.read_bytes() == before


def test_report_requires_existing_database(tmp_path):
    path = tmp_path / "missing.sqlite"
    with pytest.raises(ValueError, match="Existing"):
        module.replay(path, ["SPY"], date(2024, 1, 2), date(2024, 1, 10))
    assert not path.exists()
