"""Offline tests use synthetic bars marked as provider data ONLY in isolated fixtures."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime, timedelta

import pytest
from freezegun import freeze_time
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from signalforge.data.calendar import rth_bounds_utc, sessions
from signalforge.db.base import Base
from signalforge.db.models import (
    Candidate,
    DataSnapshot,
    Instrument,
    OHLCVDaily,
    PaperAccount,
    PaperPosition,
    ScanRun,
    Strategy,
    StrategyPromotionEvaluation,
    StrategyVersion,
)
from signalforge.domain import Direction, Horizon, LatencyCategory, QualityGate, StrategyStatus
from signalforge.experiments import comparison as c
from signalforge.experiments.report import finalize, paired_interval
from signalforge.killswitch import KillSwitchEngaged, get_kill_switch
from signalforge.paper.ledger import accept_candidate
from signalforge.settings_store import set_setting


@pytest.fixture
def experiment(tmp_path, monkeypatch):
    source = tmp_path / "operating.sqlite"
    engine = create_engine("sqlite:///" + str(source))
    Base.metadata.create_all(engine)
    with Session(engine) as s, s.begin():
        strat = Strategy(
            name="test", horizon=Horizon.SHORT_SWING, status=StrategyStatus.PAPER_APPROVED
        )
        s.add(strat)
        s.flush()
        version = StrategyVersion(
            strategy_id=strat.id,
            version="1",
            git_sha="test",
            spec_json={},
            status=StrategyStatus.PAPER_APPROVED,
        )
        s.add(version)
        s.flush()
        s.add(DataSnapshot(key="test", symbols_json=["SPY"]))
        s.flush()
        s.add(
            StrategyPromotionEvaluation(
                strategy_version_id=version.id,
                dataset_snapshot_id=1,
                evaluated_at=datetime(2026, 10, 22, tzinfo=UTC),
                config_hash="test",
                spec_json_hash="test",
                universe_json=["SPY"],
                window_start=date(2020, 1, 1),
                window_end=date(2025, 1, 1),
                data_provenance_json={"sources": ["massive"]},
                passed=True,
            )
        )
    engine.dispose()
    roots = []
    for name in ("model", "tokenizer", "implementation"):
        path = tmp_path / name
        path.write_text(name)
        roots.append(path)
    directory = tmp_path / "experiment"
    with freeze_time("2026-10-23 22:00:00"):
        manifest = c.freeze(source, directory, roots)
    monkeypatch.setattr(c, "current_spec_json_hash", lambda *args, **kwargs: "test")
    return source, directory, roots, manifest


def add_candidate(source, *, symbol="SPY", day=date(2026, 10, 26), future=False):
    engine = create_engine("sqlite:///" + str(source))
    with Session(engine) as s, s.begin():
        inst = s.scalar(select(Instrument).where(Instrument.symbol == symbol))
        if inst is None:
            inst = Instrument(symbol=symbol, instrument_type="etf", name=symbol, sector="broad")
            s.add(inst)
            s.flush()
            for d in list(sessions(day - timedelta(days=250), day))[-128:]:
                s.add(
                    OHLCVDaily(
                        instrument_id=inst.id,
                        session_date=d,
                        open=100,
                        high=101,
                        low=99,
                        close=100,
                        volume=1000000,
                        adj_close=100,
                        source="massive",
                        latency_category=LatencyCategory.END_OF_DAY,
                        is_simulated=False,
                        is_adjusted=True,
                        quality_flags=[],
                        ingested_at=rth_bounds_utc(d)[1] + timedelta(minutes=5),
                    )
                )
        scan = ScanRun(
            horizon=Horizon.SHORT_SWING,
            source="massive",
            config_hash="test",
            dataset_snapshot_id=1,
            universe_json=["SPY"],
            started_at=datetime.combine(day, datetime.min.time(), UTC)
            + timedelta(hours=20, minutes=10),
            finished_at=datetime.combine(day, datetime.min.time(), UTC)
            + timedelta(hours=20, minutes=12),
        )
        s.add(scan)
        s.flush()
        cand = Candidate(
            scan_run_id=scan.id,
            instrument_id=inst.id,
            strategy_version_id=1,
            horizon=Horizon.SHORT_SWING,
            direction=Direction.LONG,
            entry_zone_low=99.5,
            entry_zone_high=100.5,
            invalidation_level=96,
            target_level=110,
            time_stop_days=5,
            reward_risk_estimate=2.5,
            risk_dollars=50,
            risk_pct_of_account=0.5,
            quality_gate_status=QualityGate.PASSED,
            created_at=scan.finished_at + timedelta(days=1 if future else 0),
        )
        s.add(cand)
    engine.dispose()


def fake_forecast(history, symbol, horizon, **kwargs):
    return {"paths": [[102.0] * horizon] * 3, "unchanged_baseline": 100.0}


def test_freeze_isolated_immutable_and_source_readonly(experiment):
    source, directory, roots, manifest = experiment
    before = c.file_hash(source)
    assert c.status(directory)["books"] == 3
    assert c.status(directory)["performance"].startswith("sealed")
    with Session(c.source_engine(source)) as s, pytest.raises(Exception, match="readonly"):
        s.execute(text("DELETE FROM strategy"))
    with (
        sqlite3.connect(directory / "books.sqlite") as db,
        pytest.raises(sqlite3.IntegrityError, match="immutable"),
    ):
        db.execute("UPDATE comparison_manifest SET payload='{}'")
    assert c.file_hash(source) == before
    with pytest.raises(ValueError, match="must be new"):
        c.freeze(source, directory, roots)
    assert manifest["study_days"][0] == "2026-10-26"


def test_books_reuse_real_ledger_and_leave_source_unchanged(experiment, monkeypatch):
    source, directory, _, _ = experiment
    add_candidate(source)
    before = c.file_hash(source)
    monkeypatch.setattr(c, "forecast", fake_forecast)
    with freeze_time("2026-10-26 21:00:00"):
        assert c.advance(directory)["status"] == "complete"
        assert c.advance(directory)["status"] == "already_complete"
    engine, _ = c.open_books(directory)
    with Session(engine) as s, s.begin():
        positions = list(s.scalars(select(PaperPosition)))
        assert len(positions) == 3
        assert len({p.account_id for p in positions}) == 3
        assert len({(p.qty, p.avg_price, p.stop_level, p.time_stop_date) for p in positions}) == 1
        assert positions[0].opened_at.hour == 21
        s.add(PaperAccount(name="parity", initial_cash=10000, cash=10000))
        s.flush()
        with freeze_time("2026-10-26 21:00:00"):
            actual = accept_candidate(s, 1, account_name="parity", as_of=date(2026, 10, 26))
        assert actual.shares == positions[0].qty
        assert actual.fill_price == float(positions[0].avg_price)
    engine.dispose()
    assert c.file_hash(source) == before


def test_missing_forecast_is_not_negative_and_baseline_still_runs(experiment, monkeypatch):
    source, directory, _, _ = experiment
    add_candidate(source)

    def fail(*args, **kwargs):
        raise RuntimeError("do not log raw exception")

    monkeypatch.setattr(c, "forecast", fail)
    with freeze_time("2026-10-26 21:00:00"):
        c.advance(directory)
    with sqlite3.connect(directory / "books.sqlite") as db:
        forecast = json.loads(db.execute("SELECT payload FROM comparison_forecast").fetchone()[0])
        assert forecast == {"status": "missing", "reason": "RuntimeError"}
        assert db.execute("SELECT COUNT(*) FROM paper_position").fetchone()[0] == 1


def test_interrupted_attempt_not_retried(experiment, monkeypatch):
    source, directory, _, _ = experiment
    add_candidate(source)

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(c, "forecast", interrupt)
    with freeze_time("2026-10-26 21:00:00"):
        with pytest.raises(KeyboardInterrupt):
            c.advance(directory)
        monkeypatch.setattr(c, "forecast", lambda *args, **kwargs: pytest.fail("must not retry"))
        c.advance(directory)
    with sqlite3.connect(directory / "books.sqlite") as db:
        assert (
            "interrupted_attempt"
            in db.execute("SELECT payload FROM comparison_forecast").fetchone()[0]
        )


def test_future_candidate_excluded(experiment, monkeypatch):
    source, directory, _, _ = experiment
    add_candidate(source, future=True)
    monkeypatch.setattr(c, "forecast", lambda *args, **kwargs: pytest.fail("future candidate"))
    with freeze_time("2026-10-26 21:00:00"):
        assert c.advance(directory)["candidates"] == 0


def test_model_drift_and_kill_switch_block(experiment):
    _, directory, roots, _ = experiment
    roots[0].write_text("replaced")
    with freeze_time("2026-10-26 21:00:00"), pytest.raises(ValueError, match="artifacts changed"):
        c.advance(directory)
    get_kill_switch().engage(reason="test", actor="test")
    with pytest.raises(KillSwitchEngaged):
        c.advance(directory)


def test_config_drift_block(experiment):
    source, directory, _, _ = experiment
    engine = create_engine("sqlite:///" + str(source))
    with Session(engine) as s, s.begin():
        set_setting(s, "research_overrides", {"watchlist": ["DIFFERENT"]}, actor="test")
    engine.dispose()
    with freeze_time("2026-10-26 21:00:00"), pytest.raises(ValueError, match="config changed"):
        c.advance(directory)


def test_sealed_report_refuses_early_peek(experiment):
    _, directory, _, _ = experiment
    with freeze_time("2026-10-26 21:00:00"), pytest.raises(ValueError, match="sealed"):
        finalize(directory)


def test_control_count_deterministic_without_outcomes():
    a = c.matched_ids(list(range(20)), 7, "hash", "2026-10-26", 1)
    assert len(a) == 7
    assert a == c.matched_ids(list(reversed(range(20))), 7, "hash", "2026-10-26", 1)
    assert a != c.matched_ids(list(range(20)), 7, "hash", "2026-10-27", 1)
    assert paired_interval([0.01] * 30, [0.01] * 30, samples=50) == [0.0, 0.0]


def test_negative_filter_has_no_experimental_entries(experiment, monkeypatch):
    source, directory, _, _ = experiment
    add_candidate(source)
    monkeypatch.setattr(
        c, "forecast", lambda *args, **kwargs: {"paths": [[99] * 5] * 3, "unchanged_baseline": 100}
    )
    with freeze_time("2026-10-26 21:00:00"):
        c.advance(directory)
    with sqlite3.connect(directory / "books.sqlite") as db:
        records = {
            arm: json.loads(payload)
            for arm, payload in db.execute("SELECT arm,payload FROM comparison_choice")
        }
        assert records["baseline"]["status"] == "accepted"
        assert records["filtered"]["status"] == "not_selected"
        assert records["matched"]["status"] == "not_selected"


def test_next_session_exit_is_identical_in_three_books(experiment, monkeypatch):
    source, directory, _, _ = experiment
    add_candidate(source)
    monkeypatch.setattr(c, "forecast", fake_forecast)
    with freeze_time("2026-10-26 21:00:00"):
        c.advance(directory)
    engine = create_engine("sqlite:///" + str(source))
    with Session(engine) as s, s.begin():
        s.add(
            OHLCVDaily(
                instrument_id=1,
                session_date=date(2026, 10, 27),
                open=100,
                high=101,
                low=94,
                close=95,
                volume=100000,
                adj_close=95,
                source="massive",
                latency_category=LatencyCategory.END_OF_DAY,
                is_simulated=False,
                is_adjusted=True,
                ingested_at=datetime(2026, 10, 27, 20, 5, tzinfo=UTC),
                quality_flags=[],
            )
        )
    engine.dispose()
    with freeze_time("2026-10-27 21:00:00"):
        c.advance(directory, collect=False)
    engine, _ = c.open_books(directory)
    with Session(engine) as s:
        positions = list(s.scalars(select(PaperPosition)))
        assert all(p.closed_at is not None for p in positions)
        assert len({p.realized_pnl for p in positions}) == 1
        assert positions[0].realized_pnl < 0
    engine.dispose()


def test_missing_exit_session_blocks_all_books(experiment, monkeypatch):
    source, directory, _, _ = experiment
    add_candidate(source)
    monkeypatch.setattr(c, "forecast", fake_forecast)
    with freeze_time("2026-10-26 21:00:00"):
        c.advance(directory)
    with (
        freeze_time("2026-10-27 21:00:00"),
        pytest.raises(ValueError, match="Missing market sessions"),
    ):
        c.advance(directory, collect=False)
    with sqlite3.connect(directory / "books.sqlite") as db:
        assert (
            db.execute("SELECT COUNT(*) FROM paper_position WHERE closed_at IS NULL").fetchone()[0]
            == 3
        )


def test_revised_captured_bar_is_not_silently_used(experiment, monkeypatch):
    source, directory, _, _ = experiment
    add_candidate(source)
    monkeypatch.setattr(c, "forecast", fake_forecast)
    with freeze_time("2026-10-26 21:00:00"):
        c.advance(directory)
    engine = create_engine("sqlite:///" + str(source))
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE ohlcv_daily SET close=100.5 WHERE session_date='2026-10-26'")
        )
    engine.dispose()
    with freeze_time("2026-10-27 21:00:00"), pytest.raises(ValueError, match="data revised"):
        c.advance(directory, collect=False)


def test_late_resume_never_backdates_entry(experiment, monkeypatch):
    source, directory, _, _ = experiment
    add_candidate(source)

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(c, "forecast", interrupt)
    with freeze_time("2026-10-26 21:00:00"), pytest.raises(KeyboardInterrupt):
        c.advance(directory)
    with freeze_time("2026-10-27 01:00:00"):
        c.advance(directory)
    with sqlite3.connect(directory / "books.sqlite") as db:
        assert db.execute("SELECT COUNT(*) FROM paper_position").fetchone()[0] == 0
        assert (
            '"status": "missed"'
            in db.execute("SELECT payload FROM comparison_choice WHERE arm='baseline'").fetchone()[
                0
            ]
        )


def test_finalize_once_uses_only_paired_complete_records(experiment):
    _, directory, _, manifest = experiment
    engine, _ = c.open_books(directory)
    row = {
        "equity": 10000,
        "invested": 0,
        "closed_trades": 0,
        "winning_trades": 0,
        "gross_profit": 0,
        "gross_loss": 0,
        "entry_costs": 0,
    }
    with engine.begin() as conn:
        for day in manifest["study_days"]:
            for arm in c.ARMS:
                conn.exec_driver_sql(
                    "INSERT INTO comparison_daily VALUES (?,?,?)",
                    (day, f"experiment-v1-{arm}", json.dumps(row)),
                )
    engine.dispose()
    with freeze_time("2028-01-01 21:00:00"):
        result = finalize(directory)
        assert result == finalize(directory)
        assert result["results"]["1"]["verdict"] == "insufficient evidence of improvement"
    with sqlite3.connect(directory / "books.sqlite") as db, pytest.raises(sqlite3.IntegrityError):
        db.execute("DELETE FROM comparison_final")


def test_foreign_keys_and_storage_cap_on_private_connections(experiment):
    _, directory, _, _ = experiment
    engine, _ = c.open_books(directory)
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert conn.exec_driver_sql("PRAGMA max_page_count").scalar() == 65536
    engine.dispose()


def test_pinned_operating_kill_switch_blocks_even_from_other_checkout(experiment):
    source, directory, _, _ = experiment
    (source.parent / "kill_switch.json").write_text('{"active": true}')
    with (
        freeze_time("2026-10-26 21:00:00"),
        pytest.raises(ValueError, match="emergency stop active"),
    ):
        c.advance(directory)


def test_no_enrollment_before_first_session(experiment, monkeypatch):
    _, directory, _, _ = experiment
    monkeypatch.setattr(
        c, "forecast", lambda *args, **kwargs: pytest.fail("no inference during freeze")
    )
    with freeze_time("2026-10-24 12:00:00"):
        assert c.advance(directory)["status"] == "not_started"


def test_duplicate_symbol_not_stacked_in_any_book(experiment, monkeypatch):
    source, directory, _, _ = experiment
    add_candidate(source)
    add_candidate(source)
    monkeypatch.setattr(c, "forecast", fake_forecast)
    with freeze_time("2026-10-26 21:00:00"):
        c.advance(directory)
    with sqlite3.connect(directory / "books.sqlite") as db:
        assert db.execute("SELECT COUNT(*) FROM paper_position").fetchone()[0] == 3
        decisions = [json.loads(r[0]) for r in db.execute("SELECT payload FROM comparison_choice")]
        assert sum(d["status"] == "risk_rejected" for d in decisions) == 3


def test_changed_approval_evidence_blocks_collection(experiment, monkeypatch):
    source, directory, _, _ = experiment
    add_candidate(source)
    engine = create_engine("sqlite:///" + str(source))
    with engine.begin() as conn:
        conn.execute(text("UPDATE strategy_promotion_evaluation SET passed=0"))
    engine.dispose()
    monkeypatch.setattr(c, "forecast", lambda *args, **kwargs: pytest.fail("invalid approval"))
    with (
        freeze_time("2026-10-26 21:00:00"),
        pytest.raises(ValueError, match="Approval scope changed"),
    ):
        c.advance(directory)


def test_future_ingestion_timestamp_blocks_model_and_entry(experiment, monkeypatch):
    source, directory, _, _ = experiment
    add_candidate(source)
    engine = create_engine("sqlite:///" + str(source))
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE ohlcv_daily SET ingested_at='2026-10-27 20:00:00' "
                "WHERE session_date='2026-10-23'"
            )
        )
    engine.dispose()
    monkeypatch.setattr(c, "forecast", lambda *args, **kwargs: pytest.fail("future information"))
    with freeze_time("2026-10-26 21:00:00"), pytest.raises(ValueError, match="Future ingestion"):
        c.advance(directory)


def test_code_drift_refuses_old_manifest(experiment, monkeypatch):
    _, directory, _, _ = experiment
    monkeypatch.setattr(c, "code_hash", lambda: "different")
    with pytest.raises(ValueError, match="Code changed"):
        c.open_books(directory)


def test_finalization_without_complete_observations_refused(experiment):
    _, directory, _, _ = experiment
    with freeze_time("2028-01-01 21:00:00"), pytest.raises(ValueError, match="do not cover"):
        finalize(directory)


def test_operating_database_cannot_be_disguised_as_experiment(experiment, tmp_path):
    source, _, _, _ = experiment
    before = c.file_hash(source)
    alias = tmp_path / "not-an-experiment"
    alias.mkdir()
    (alias / "books.sqlite").hardlink_to(source)
    with pytest.raises(sqlite3.OperationalError, match="comparison_manifest"):
        c.advance(alias)
    assert c.file_hash(source) == before
