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


def test_scenarios_use_same_snapshot_without_database_writes(tmp_path):
    from signalforge.data.calendar import sessions

    path = tmp_path / "synthetic.sqlite"
    start, end = date(2024, 1, 2), date(2024, 4, 30)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE instrument(id INTEGER, symbol TEXT, sector TEXT)")
        conn.execute("INSERT INTO instrument VALUES (1, 'SPY', 'broad_etf')")
        conn.execute("""CREATE TABLE dividend_event(symbol TEXT, ex_dividend_date TEXT,
            cash_amount REAL, pay_date TEXT, currency TEXT, source TEXT)""")
        conn.execute("""CREATE TABLE split_event(symbol TEXT, execution_date TEXT,
            split_from REAL, split_to REAL)""")
        conn.execute("""CREATE TABLE ohlcv_daily(instrument_id INTEGER,session_date TEXT,
            open REAL,high REAL,low REAL,close REAL,volume REAL,is_adjusted INTEGER,
            is_simulated INTEGER,quality_flags TEXT,source TEXT,latency_category TEXT)""")
        # Synthetic contract data only: never used for performance evidence.
        conn.executemany(
            "INSERT INTO ohlcv_daily VALUES (1,?,100,101,99,100,100000,1,0,'[]',"
            "'massive','END_OF_DAY')",
            [(str(d),) for d in sessions(start, end)],
        )
    before = path.read_bytes()
    r = module.replay(path, ["SPY"], start, end, cost_scenarios=True)
    assert path.read_bytes() == before
    assert set(r["scenario_diagnostics"]) == {
        "base",
        "zero_fees_spread_slippage",
        "higher_cost_stress",
    }
    assumptions = r["replay_assumptions"]
    assert assumptions["calendar"] == "XNYS"
    assert assumptions["session_count"] == len(sessions(start, end))
    assert assumptions["first_session"] == str(start)
    assert assumptions["last_session"] == str(end)
    assert assumptions["max_prior_volume_fraction"] == 0.01
    md = module.markdown(r)
    assert assumptions["source_reference_sha256"] in md
    assert "| higher_cost_stress | 10 | 10 | 0.005 | 1 | yes |" in md
    for scenario in r["scenario_diagnostics"].values():
        targets = scenario["diagnostics"]["income_targets"]
        assert targets["full_period_net_pnl_usd"] == "0.00"
        assert targets["reliability_status"] == "not_established"
        assert targets["weekday_days"]["target_hits"] == 0
    assert r["result"]["fills"] == []
