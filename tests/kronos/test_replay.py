"""Hermetic persistence and inference-boundary checks; no model or provider calls."""

import json
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from signalforge.data.calendar import sessions as xnys_sessions
from signalforge.db.models.market import Instrument, OHLCVDaily
from signalforge.domain import LatencyCategory
from signalforge.kronos import service


@pytest.fixture
def stored():
    engine = create_engine("sqlite://")
    Instrument.__table__.create(engine)
    OHLCVDaily.__table__.create(engine)
    with Session(engine) as session:
        instrument = Instrument(symbol="TEST")
        session.add(instrument)
        session.flush()
        for i, session_date in enumerate(xnys_sessions(date(2024, 1, 1), date(2024, 12, 31))[:148]):
            session.add(
                OHLCVDaily(
                    instrument_id=instrument.id,
                    session_date=session_date,
                    open=100 + i,
                    high=102 + i,
                    low=99 + i,
                    close=101 + i,
                    volume=1000,
                    source="massive",
                    is_simulated=False,
                    is_adjusted=True,
                    latency_category=LatencyCategory.END_OF_DAY,
                    ingested_at=datetime(2025, 1, 1, tzinfo=UTC),
                    quality_flags=[],
                )
            )
        session.commit()
        yield session
    engine.dispose()


@pytest.mark.parametrize("horizon", [5, 20])
def test_replay_no_leakage_and_baseline(stored, monkeypatch, horizon):
    seen = []

    def infer(history, dates):
        seen.append((history, dates))
        assert len(history) == 128
        assert max(b["date"] for b in history) < min(dates)
        return [[history[-1]["close"]] * len(dates)] * 3

    monkeypatch.setattr(service, "infer", infer)
    result = service.replay(stored, "TEST", horizon)
    assert result["mae"] == result["baseline_mae"] == (horizon + 1) / 2
    assert len(result["dates"]) == horizon
    assert result["pretraining_overlap"] == "unknown"
    json.dumps(result, allow_nan=False)
    row = stored.query(OHLCVDaily).order_by(OHLCVDaily.session_date.desc()).first()
    row.close += 0.5
    stored.commit()
    service.replay(stored, "TEST", horizon)
    assert seen[0] == seen[1]  # Held-out price changes never enter worker input.


@pytest.mark.parametrize(
    "field,value",
    [
        ("is_simulated", True),
        ("is_adjusted", False),
        ("quality_flags", ["bad"]),
        ("volume", -1),
        ("high", 0),
        ("source", "fixture"),
    ],
)
def test_reject_bad_history(stored, monkeypatch, field, value):
    row = stored.query(OHLCVDaily).order_by(OHLCVDaily.session_date.desc()).first()
    setattr(row, field, value)
    stored.commit()
    monkeypatch.setattr(service, "infer", lambda *a: pytest.fail("Must not infer"))
    with pytest.raises(service.KronosUnavailable):
        service.replay(stored, "TEST", 20)


@pytest.mark.parametrize("symbol,horizon", [("../bad", 5), ("TEST", True), ("TEST", 6)])
def test_invalid_request(stored, symbol, horizon):
    with pytest.raises(ValueError):
        service.replay(stored, symbol, horizon)


def test_no_autoflush(stored, monkeypatch):
    stored.add(Instrument(symbol="UNSAVED"))
    monkeypatch.setattr(service, "infer", lambda h, d: [[1.0] * len(d)] * 3)
    service.replay(stored, "TEST")
    assert next(iter(stored.new)).id is None


@pytest.mark.parametrize(
    "paths", [None, {}, [None] * 3, [[float("nan")] * 5] * 3, [[-1] * 5] * 3, [[1] * 4] * 3]
)
def test_invalid_output(stored, monkeypatch, paths):
    monkeypatch.setattr(service, "infer", lambda h, d: paths)
    with pytest.raises(service.KronosUnavailable):
        service.replay(stored, "TEST")


def test_as_of_and_future_exclusion(stored, monkeypatch):
    monkeypatch.setattr(service, "infer", lambda h, d: [[1.0] * len(d)] * 3)
    cutoff = xnys_sessions(date(2024, 1, 1), date(2024, 12, 31))[140]
    result = service.replay(stored, "TEST", as_of=cutoff)
    assert result["heldout_end"] == cutoff.isoformat()
    latest = stored.query(OHLCVDaily).order_by(OHLCVDaily.session_date.desc()).first()
    latest.session_date = date(2099, 1, 1)
    stored.commit()
    result = service.replay(stored, "TEST")
    assert result["heldout_end"] < "2099-01-01"
    with pytest.raises(ValueError):
        service.replay(stored, "TEST", as_of=date(2099, 1, 1))


def test_database_error_sanitized(stored, monkeypatch):
    from sqlalchemy.exc import OperationalError

    def fail(*args):
        raise OperationalError("private database detail", {}, Exception("secret"))

    monkeypatch.setattr(stored, "scalars", fail)
    with pytest.raises(
        service.KronosUnavailable, match=r"^Persisted daily history is unavailable$"
    ):
        service.replay(stored, "TEST")


@pytest.mark.parametrize("mutation", ["missing", "weekend"])
def test_session_continuity_rejected_before_inference(stored, monkeypatch, mutation):
    row = stored.query(OHLCVDaily).order_by(OHLCVDaily.session_date).all()[60]
    if mutation == "missing":
        stored.delete(row)
    else:
        row.session_date = date(2024, 4, 6)  # Saturday inside the selected window.
    stored.commit()
    monkeypatch.setattr(service, "infer", lambda *a: pytest.fail("Must not infer"))
    with pytest.raises(service.KronosUnavailable, match="missing or non-XNYS"):
        service.replay(stored, "TEST", 5)


def test_daily_and_mixed_latency_labels(stored, monkeypatch):
    row = stored.query(OHLCVDaily).order_by(OHLCVDaily.session_date.desc()).first()
    row.latency_category = LatencyCategory.HISTORICAL
    stored.commit()
    monkeypatch.setattr(service, "infer", lambda h, d: [[1.0] * len(d)] * 3)
    result = service.replay(stored, "TEST")
    assert result["bar_size"] == "1d"
    assert result["calendar"] == "XNYS"
    assert result["latency_category"] == "HISTORICAL"
    assert result["source_latency_categories"] == ["END_OF_DAY", "HISTORICAL"]
    assert result["provenance"][-1]["latency_category"] == "HISTORICAL"
    assert result["provenance"][-2]["latency_category"] == "END_OF_DAY"


def test_calendar_failure_sanitized(stored, monkeypatch):
    def fail(*args):
        raise RuntimeError("internal detail")

    monkeypatch.setattr(service, "xnys_sessions", fail)
    monkeypatch.setattr(service, "infer", lambda *a: pytest.fail("Must not infer"))
    with pytest.raises(service.KronosUnavailable, match="calendar is unavailable"):
        service.replay(stored, "TEST")
