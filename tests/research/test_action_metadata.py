import importlib.util
import json
import sqlite3
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "action_replay_report", Path(__file__).parents[2] / "scripts/action_replay_report.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_verified_etf_metadata_does_not_rewrite_operating_defaults(tmp_path):
    db = tmp_path / "data.sqlite"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE instrument(symbol,sector,instrument_type)")
        c.execute("INSERT INTO instrument VALUES ('SPY','ETF:SPY','stock')")
        c.execute("""CREATE TABLE symbol_continuity_mapping(old_symbol,new_symbol,effective_date,
            source,validation_evidence_json,validation_status,ratio,version)""")
    evidence = tmp_path / "references.json"
    evidence.write_text(
        json.dumps(
            {
                "SPY": {
                    "source": "massive",
                    "sha256": "synthetic-test-hash",
                    "endpoint": "/v3/reference/tickers/SPY",
                    "list_date": "1993-01-22",
                    "type": "ETF",
                }
            }
        )
    )
    before = db.read_bytes()
    meta, _ = module.read_metadata(db, evidence)
    assert meta["SPY"]["instrument_type"] == "etf"
    assert db.read_bytes() == before


def test_stored_reference_corrects_replay_types_without_database_writes(tmp_path):
    db = tmp_path / "data.sqlite"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE instrument(symbol,sector,instrument_type)")
        c.executemany(
            "INSERT INTO instrument VALUES (?,?,?)",
            [
                ("SPY", "broad", "stock"),
                ("AAPL", "technology", "etf"),
                ("UNKNOWN", "unknown", "stock"),
            ],
        )
        c.execute("CREATE TABLE universe_ticker(ticker,security_type,refreshed_at)")
        c.executemany(
            "INSERT INTO universe_ticker VALUES (?,?,?)",
            [
                ("SPY", "ETF", "2026-11-03 00:00:00"),
                ("AAPL", "CS", "2026-11-03 00:00:00"),
                ("UNKNOWN", "ETV", "2026-11-03 00:00:00"),
            ],
        )
        c.execute("""CREATE TABLE symbol_continuity_mapping(old_symbol,new_symbol,effective_date,
            source,validation_evidence_json,validation_status,ratio,version)""")
    before = db.read_bytes()
    meta, _ = module.read_metadata(db)
    assert meta["SPY"]["instrument_type"] == "etf"
    assert meta["AAPL"]["instrument_type"] == "stock"
    assert meta["UNKNOWN"]["instrument_type"] == "stock"
    evidence = json.loads(meta["SPY"]["classification_reference"])
    assert evidence["source_table"] == "universe_ticker"
    assert evidence["point_in_time"] is False
    assert evidence["previous_type"] == "stock"
    assert db.read_bytes() == before
