"""Income arithmetic must not be promoted into a forecast or a study peek."""

import importlib.util
import sqlite3
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "income_target_assessment", Path(__file__).parents[1] / "scripts/income_target_assessment.py"
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_keeps_books_separate_and_excludes_open_positions(tmp_path):
    db = tmp_path / "paper.sqlite"
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            CREATE TABLE paper_account(id INTEGER,name TEXT,initial_cash NUMERIC);
            CREATE TABLE paper_position(account_id INTEGER,realized_pnl NUMERIC,closed_at TEXT);
            INSERT INTO paper_account VALUES (1,'a',10000),(2,'b',30000);
            INSERT INTO paper_position VALUES (1,20,'2026-11-02'),(1,-5,'2026-11-02'),(1,500,NULL);
        """)
    before = db.read_bytes()
    result = module.assess(db)
    assert result["status"] == "INCOME_TARGET_NOT_ESTABLISHED"
    assert result["books"][0]["required_weekday_return_pct"] == "10.0"
    assert result["books"][0]["recorded_realized_pnl"] == "15"
    assert result["books"][1]["closed_positions"] == 0
    assert db.read_bytes() == before


def test_refuses_frozen_study_and_does_not_create_missing_database(tmp_path):
    db = tmp_path / "missing.sqlite"
    with pytest.raises(ValueError):
        module.assess(db)
    assert not db.exists()
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE comparison_daily(day TEXT)")
    with pytest.raises(ValueError, match="excluded"):
        module.assess(db)
