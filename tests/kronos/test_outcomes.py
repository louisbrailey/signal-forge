from dataclasses import asdict

from signalforge.backtest.costs import CostModel
from signalforge.kronos.outcomes import PROTOCOL, evaluate


def example():
    dates = [f"2026-10-{d}" for d in (19, 20, 21, 22, 23)]
    payload = {
        "evaluation_protocol": PROTOCOL,
        "mode": "prospective_shadow",
        "data_stale": False,
        "completed_at": "2026-10-18T12:01:00+00:00",
        "dates": dates,
        "paths": [[102.0] * 5] * 3,
        "unchanged_baseline": 100,
        "candidate_snapshot": [],
        "evaluation_costs": {"model": asdict(CostModel()), "spread_bps": 5.0},
    }
    bars = [
        {
            "date": d,
            "open": 100,
            "close": 102,
            "source": "massive",
            "simulated": False,
            "adjusted": True,
            "flags": [],
        }
        for d in dates
    ]
    return payload, "2026-10-18T12:00:00+00:00", bars


def test_costs_and_cohorts_use_stored_inputs():
    p, t, bars = example()
    r = evaluate(p, t, bars)
    assert r["status"] == "mature"
    assert 0 < r["net_fixed_horizon_return"] < 0.02
    assert r["mae"] == 0 and r["baseline_mae"] == 2
    assert r["cohorts"] == ["kronos_positive"]
    assert r["strategy_context"] == "unavailable_no_candidate"
    assert r["observations"] == bars


def test_pending_and_invalid_observations():
    p, t, bars = example()
    assert evaluate(p, t, bars[:-1])["status"] == "pending"
    bars[0]["simulated"] = True
    assert evaluate(p, t, bars)["status"] == "excluded"


def test_legacy_replay_and_late_completion_excluded():
    p, t, bars = example()
    assert evaluate({}, t, bars)["status"] == "excluded"
    p["completed_at"] = "2026-10-19T15:00:00+00:00"
    assert evaluate(p, t, bars)["reason"] == "forecast_not_before_entry"
    p["mode"] = "historical_replay"
    assert evaluate(p, t, bars)["reason"] == "replay_or_stale"


def test_future_candidate_context_excluded():
    p, t, bars = example()
    p["candidate_snapshot"] = [
        {"created_at": "2026-10-19T12:00:00+00:00", "direction": "LONG", "gate": "PASSED"}
    ]
    assert evaluate(p, t, bars)["status"] == "excluded"


def test_outcome_store_is_idempotent_and_source_readonly(db_url, tmp_path):
    import json
    import sqlite3
    from pathlib import Path

    from sqlalchemy.engine import make_url

    from signalforge.kronos.monitor import shadow_status
    from signalforge.kronos.outcome_store import run

    source = Path(make_url(db_url).database)
    before = source.read_bytes()
    ledger = tmp_path / "shadow.sqlite"
    with sqlite3.connect(ledger) as db:
        db.execute(
            "CREATE TABLE forecasts (symbol TEXT, origin TEXT, horizon INTEGER, "
            "generated_at TEXT, status TEXT, payload TEXT)"
        )
        db.execute(
            "INSERT INTO forecasts VALUES (?,?,?,?,?,?)",
            ("SPY", "2026-10-16", 5, "2026-10-18T12:00:00+00:00", "complete", json.dumps({})),
        )
    assert run(source, ledger) == {"excluded": 1}
    assert run(source, ledger) == {}
    assert source.read_bytes() == before
    report = shadow_status(ledger)
    assert report["outcomes"] == {"excluded": 1}
    assert report["recent_outcomes"][0]["reason"] == "legacy_without_frozen_context"


def test_agreement_requires_recorded_candidate_context():
    p, t, bars = example()
    p["candidate_snapshot"] = [
        {"created_at": "2026-10-18T11:00:00+00:00", "direction": "LONG", "gate": "PASSED"}
    ]
    assert evaluate(p, t, bars)["cohorts"] == ["strategy_positive", "kronos_positive", "agreement"]
    p["candidate_snapshot"][0]["gate"] = "NO_TRADE"
    assert evaluate(p, t, bars)["cohorts"] == ["kronos_positive", "disagreement"]


def test_candidate_window_keeps_postclose_scans_across_utc_midnight():
    from datetime import UTC, date, datetime

    from signalforge.kronos.outcomes import candidate_window_start

    start = candidate_window_start(date(2026, 10, 26))
    scan = datetime(2026, 10, 26, 22, tzinfo=UTC)
    forecast = datetime(2026, 10, 27, 0, 5, tzinfo=UTC)
    assert start <= scan < forecast
    assert start == datetime(2026, 10, 26, 20, tzinfo=UTC)
