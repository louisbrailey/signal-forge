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


def test_history_counts_every_row_without_treating_it_as_validated(tmp_path):
    db = tmp_path / "market.sqlite"
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            CREATE TABLE ohlcv_daily(instrument_id INTEGER,session_date TEXT,
                source TEXT,latency_category TEXT,is_simulated INTEGER,quality_flags TEXT);
            INSERT INTO ohlcv_daily VALUES
                (1,'2016-01-04','massive','END_OF_DAY',0,'[]'),
                (1,'2026-01-05','massive','END_OF_DAY',0,'["stale"]'),
                (2,'2026-01-05','fixture','HISTORICAL',1,'[]');
        """)
        result = module.historical_inventory(conn, {"ohlcv_daily"})
    groups = {g["source"]: g for g in result[0]["groups"]}
    assert sum(g["rows"] for g in groups.values()) == 3
    assert groups["fixture"]["simulated_rows"] == 1
    assert groups["massive"]["flagged_or_unknown_quality_rows"] == 1
    assert groups["massive"]["first"] == "2016-01-04"
    assert result[1]["status"] == "unavailable"
    assert "coverage_passed" not in result[0]


def test_missing_quality_metadata_is_unknown(tmp_path):
    with sqlite3.connect(tmp_path / "legacy.sqlite") as conn:
        conn.executescript("""
            CREATE TABLE crypto_bar_intraday(pair TEXT,bar_start TEXT,bar_size TEXT,
                source TEXT,latency_category TEXT);
            INSERT INTO crypto_bar_intraday VALUES
                ('BTCUSD','2026-01-01 00:00:00','1h','massive_crypto','HISTORICAL');
        """)
        result = module.historical_inventory(conn, {"crypto_bar_intraday"})[3]
    assert result["quality_metadata_available"] is False
    assert result["simulation_metadata_available"] is False
    assert result["groups"][0]["flagged_or_unknown_quality_rows"] == 1
    assert result["groups"][0]["simulated_rows"] is None
