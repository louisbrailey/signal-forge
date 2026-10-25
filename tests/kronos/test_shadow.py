from datetime import date

import pytest
from sqlalchemy import select

from signalforge.db.models import Instrument, OHLCVDaily
from signalforge.kronos import runtime, shadow

pytest_plugins = ["tests.kronos.test_replay"]


def test_partition_is_stable_and_bounded():
    assert [shadow.partition(s) for s in ("SPY", "QQQ")] == [
        shadow.partition(s) for s in ("SPY", "QQQ")
    ]
    assert all(0 <= shadow.partition(str(i)) < 25 for i in range(1000))


def test_prospective_only_completed_input(stored, monkeypatch):
    cutoff = stored.scalar(select(OHLCVDaily.session_date).order_by(OHLCVDaily.session_date.desc()))
    history = shadow.inputs(stored, "TEST", cutoff)

    def infer(rows, dates, **kwargs):
        assert rows[-1]["date"] < dates[0]
        return [[rows[-1]["close"]] * len(dates)] * 3

    monkeypatch.setattr(shadow, "infer", infer)
    result = shadow.forecast(history, "TEST")
    assert result["probability_of_profit"] is None
    assert result["trade_approved"] is False
    assert len(history) == 128


def test_unsupported_asset_refused(stored):
    stored.scalar(select(Instrument)).instrument_type = "option"
    stored.flush()
    with pytest.raises(ValueError, match="unsupported"):
        shadow.inputs(stored, "TEST", date(2024, 7, 31))


def test_stale_data_refused(stored):
    with pytest.raises(ValueError, match="stale"):
        shadow.inputs(stored, "TEST", date(2026, 10, 23))


def test_bad_output_refused(stored, monkeypatch):
    cutoff = stored.scalar(select(OHLCVDaily.session_date).order_by(OHLCVDaily.session_date.desc()))
    history = shadow.inputs(stored, "TEST", cutoff)
    monkeypatch.setattr(shadow, "infer", lambda *a, **kw: [[float("nan")] * 5] * 3)
    with pytest.raises(ValueError, match="invalid forecast"):
        shadow.forecast(history, "TEST")


def test_cancelled_child_is_reaped(monkeypatch):
    from tests.kronos.test_runtime import child

    child(monkeypatch, "import time; time.sleep(5)")
    with pytest.raises(runtime.KronosError, match="cancelled"):
        runtime.run_worker(b"{}", cancelled=lambda: True)


def load_script():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).parents[2] / "scripts/kronos_shadow.py"
    spec = importlib.util.spec_from_file_location("shadow_script", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_queue_budget_and_resume(db_url, tmp_path, monkeypatch):
    import sqlite3
    from argparse import Namespace
    from pathlib import Path

    from sqlalchemy.engine import make_url

    script = load_script()
    calls = []
    monkeypatch.setattr(script, "inputs", lambda *args: [])

    def forecast(*args, **kw):
        calls.append(args[1])
        return {"trade_approved": False}

    monkeypatch.setattr(script, "forecast", forecast)
    args = Namespace(
        source_db=Path(make_url(db_url).database),
        output_db=tmp_path / "shadow.sqlite",
        kill_switch=tmp_path / "kill.json",
        symbols=["SPY", "QQQ"],
        max_calls=1,
        horizon=5,
    )
    script.run(args)
    script.run(args)
    assert len(calls) == 1
    with sqlite3.connect(args.output_db) as db:
        assert db.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0] == 1
    args.kill_switch.write_text('{"active": true}')
    args.max_calls = 2
    script.run(args)
    assert len(calls) == 1


def test_same_database_refused(tmp_path):
    from argparse import Namespace

    script = load_script()
    p = tmp_path / "source.sqlite"
    p.write_bytes(b"unchanged")
    with pytest.raises(ValueError, match="separate"):
        script.run(Namespace(source_db=p, output_db=p))
    assert p.read_bytes() == b"unchanged"


def test_malformed_stop_state_fails_closed(tmp_path):
    script = load_script()
    p = tmp_path / "kill.json"
    for value in ("[]", "null", "{}", "{", '{"active": 0}'):
        p.write_text(value)
        assert script.stopped(p)
    p.write_text('{"active": false}')
    assert not script.stopped(p)


def test_combined_tickers_rejected_before_ledger(db_url, tmp_path):
    from argparse import Namespace
    from pathlib import Path

    from sqlalchemy.engine import make_url

    script = load_script()
    args = Namespace(
        source_db=Path(make_url(db_url).database),
        output_db=tmp_path / "shadow.sqlite",
        symbols=["SPY QQQ"],
        max_calls=25,
    )
    with pytest.raises(ValueError, match="separate valid"):
        script.run(args)
    assert not args.output_db.exists()


@pytest.mark.parametrize("replay_mode", [False, True])
def test_old_data_requires_explicit_replay(db_url, stored, tmp_path, monkeypatch, replay_mode):
    import json
    import sqlite3
    from argparse import Namespace
    from pathlib import Path

    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session

    engine = create_engine(db_url)
    with Session(engine) as s:
        instrument = Instrument(symbol="TEST", instrument_type="stock")
        s.add(instrument)
        s.flush()
        for old in stored.scalars(select(OHLCVDaily)):
            values = {
                c.name: getattr(old, c.name)
                for c in OHLCVDaily.__table__.columns
                if c.name not in ("id", "instrument_id")
            }
            s.add(OHLCVDaily(instrument_id=instrument.id, **values))
        s.commit()
    script = load_script()
    monkeypatch.setattr(script, "last_closed_session", lambda now: date(2026, 10, 23))
    calls = []

    def forecast(*args, **kwargs):
        calls.append(args)
        return {"trade_approved": False}

    monkeypatch.setattr(script, "forecast", forecast)
    args = Namespace(
        source_db=Path(make_url(db_url).database),
        output_db=tmp_path / "shadow.sqlite",
        kill_switch=tmp_path / "kill.json",
        symbols=["TEST"],
        max_calls=25,
        horizon=5,
        replay_latest=replay_mode,
    )
    script.run(args)
    with sqlite3.connect(args.output_db) as db:
        record = db.execute("SELECT status,payload FROM forecasts").fetchone()
        exclusions = db.execute("SELECT reason FROM input_checks").fetchall()
    if replay_mode:
        status, raw = record
        payload = json.loads(raw)
        assert len(calls) == 1
        assert status == "complete"
        assert payload["mode"] == "historical_replay"
        assert payload["data_stale"] is True
    else:
        assert calls == []
        assert record is None
        assert exclusions == [("stale_history",)]
        # Once publication arrives, the same session can be processed rather
        # than being permanently deduplicated as a failed forecast.
        monkeypatch.setattr(script, "inputs", lambda *a: [])
        script.run(args)
        assert len(calls) == 1
    engine.dispose()


def test_monitor_empty_corrupt_and_legacy_ledger(tmp_path):
    import sqlite3

    from signalforge.kronos.monitor import shadow_status

    path = tmp_path / "shadow.sqlite"
    assert shadow_status(path)["status"] == "not_started"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE forecasts (symbol,origin,generated_at,status,payload)")
        db.execute("INSERT INTO forecasts VALUES ('SPY','2026-01-01','2026-01-02','complete','{}')")
    report = shadow_status(path)
    assert report["status"] == "not_running_or_stale"
    assert report["rows"][0]["mode"] == "legacy_unclassified"
    with sqlite3.connect(path) as db:
        db.execute("UPDATE forecasts SET payload='['")
    assert shadow_status(path)["status"] == "unavailable_or_invalid"
