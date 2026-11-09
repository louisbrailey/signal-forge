"""`record-oos-backtest`: the development-window OOS backtest the scan gate reads.

A version approved on a dataset snapshot has no ``BacktestRun`` until one is
recorded, so every scan candidate fails "no out-of-sample backtest on record".
The recorded run must be the SAME pre-sealed backtest promotion gates 1-8
measured (not a re-specified one) and must never reach into the sealed window.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from signalforge.cli import app
from signalforge.data.adapters.fixture import FixtureMarketDataAdapter
from signalforge.data.ingest import ingest_universe
from signalforge.db.models import BacktestRun, StrategyPromotionEvaluation, StrategySealedTest
from signalforge.research.persistence import latest_oos_metric, spec_json_hash
from signalforge.research.promotion import (
    development_sealed_boundary,
    evaluate_promotion,
    get_or_create_dataset_snapshot,
    persist_development_oos_record,
    record_development_oos_backtest,
    run_development_backtest,
)
from signalforge.research.strategies import MeanReversion
from signalforge.research.strategies.mean_reversion import MeanReversionParams
from signalforge.settings_store import effective_research_config

UNIVERSE = ["SPY", "AAPL"]
END = date(2024, 12, 31)
START = END - timedelta(days=365 * 8)


def _mr() -> MeanReversion:
    return MeanReversion(MeanReversionParams(trend_window=0))


def _evaluated(session: Session):
    """Seed fixture bars and run one promotion evaluation on a keyed snapshot,
    which locks a sealed test and so fixes the development span's end."""
    ingest_universe(session, FixtureMarketDataAdapter(), UNIVERSE, START, END)
    session.flush()
    snap = get_or_create_dataset_snapshot(session, key="dev_oos_test", symbols=UNIVERSE)
    cfg = effective_research_config(session)
    result = evaluate_promotion(
        session,
        _mr(),
        symbols=UNIVERSE,
        start=START,
        end=END,
        config=cfg,
        dataset_snapshot=snap,
    )
    sealed = session.get(StrategySealedTest, result.sealed_test_id)
    return snap, cfg, result, sealed.window_start - timedelta(days=1)


def _n_runs(session: Session) -> int:
    return int(session.scalar(select(func.count(BacktestRun.id))) or 0)


def test_recorded_oos_is_the_development_backtest_promotion_measured(session: Session) -> None:
    snap, cfg, result, dev_end = _evaluated(session)
    assert latest_oos_metric(session, _mr().spec()) is None

    rec = record_development_oos_backtest(
        session, _mr(), dataset_snapshot_id=snap.id, until=dev_end, config=cfg
    )

    gates = {g.number: g.evidence for g in result.gates}
    assert rec.result.out_of_sample.n_trades == gates[2]["n_oos_trades"]
    assert rec.result.out_of_sample.expectancy_r == pytest.approx(gates[3]["expectancy_r"])
    assert rec.result.oos_ci["expectancy_r"] == pytest.approx(gates[4]["ci"])
    assert rec.evaluation_id == result.evaluation_id
    assert rec.evaluation_oos["expectancy_r"] == pytest.approx(gates[3]["expectancy_r"])
    assert all(rec.reproduces_evaluation.values()), rec.reproduces_evaluation
    assert rec.start == START and rec.until == dev_end

    # persisted, with provenance, and now what the scan gate reads
    run = session.get(BacktestRun, rec.backtest_run_id)
    assert run is not None and run.date_end == dev_end
    params = run.params_json
    assert params["purpose"] == "development_oos"
    assert params["dataset_snapshot"] == {"id": snap.id, "key": "dev_oos_test"}
    assert params["window"] == {"start": START.isoformat(), "until": dev_end.isoformat()}
    assert params["sealed_boundary"] == (dev_end + timedelta(days=1)).isoformat()
    assert params["promotion_evaluation_id"] == result.evaluation_id
    assert sorted(params["symbols"]) == sorted(UNIVERSE)
    metric = latest_oos_metric(session, _mr().spec())
    assert metric is not None and metric.run_id == run.id
    assert metric.metrics_json["expectancy_r"] == pytest.approx(gates[3]["expectancy_r"])


def test_until_on_or_after_the_sealed_window_is_refused(session: Session) -> None:
    snap, cfg, _, dev_end = _evaluated(session)
    boundary = dev_end + timedelta(days=1)
    for bad in (boundary, boundary + timedelta(days=30)):
        with pytest.raises(ValueError, match="sealed window"):
            record_development_oos_backtest(
                session, _mr(), dataset_snapshot_id=snap.id, until=bad, config=cfg
            )
    assert _n_runs(session) == 0


def test_boundary_spans_every_sealed_test_on_the_snapshot(session: Session) -> None:
    snap, _, result, dev_end = _evaluated(session)
    assert development_sealed_boundary(
        session, strategy_version_id=result.strategy_version_id, dataset_snapshot_id=snap.id
    ) == dev_end + timedelta(days=1)
    # an unrelated version that never sealed anything still sees the snapshot's window
    assert development_sealed_boundary(
        session, strategy_version_id=987654, dataset_snapshot_id=snap.id
    ) == dev_end + timedelta(days=1)
    assert (
        development_sealed_boundary(session, strategy_version_id=987654, dataset_snapshot_id=999)
        is None
    )


def test_dry_run_writes_nothing_and_persist_rechecks_the_boundary(session: Session) -> None:
    snap, cfg, _, dev_end = _evaluated(session)
    rec = record_development_oos_backtest(
        session, _mr(), dataset_snapshot_id=snap.id, until=dev_end, config=cfg, persist=False
    )
    assert rec.backtest_run_id is None
    assert _n_runs(session) == 0

    saved = persist_development_oos_record(session, rec)
    assert saved.backtest_run_id is not None
    assert _n_runs(session) == 1


def test_refuses_without_an_evaluation_on_that_snapshot(session: Session) -> None:
    _evaluated(session)
    other = get_or_create_dataset_snapshot(session, key="never_evaluated", symbols=["AAPL"])
    with pytest.raises(ValueError, match="no promotion evaluation"):
        record_development_oos_backtest(
            session, _mr(), dataset_snapshot_id=other.id, until=date(2023, 1, 1)
        )
    with pytest.raises(ValueError, match="no dataset snapshot"):
        record_development_oos_backtest(
            session, _mr(), dataset_snapshot_id=424242, until=date(2023, 1, 1)
        )


def test_refuses_when_the_strategy_spec_has_drifted_since_evaluation(session: Session) -> None:
    snap, cfg, _, dev_end = _evaluated(session)
    drifted = MeanReversion(MeanReversionParams(trend_window=0, z_entry=-2.7))
    assert drifted.spec().name == _mr().spec().name
    assert drifted.spec().version == _mr().spec().version
    assert spec_json_hash(drifted.spec()) != spec_json_hash(_mr().spec())
    with pytest.raises(ValueError, match="spec has changed"):
        record_development_oos_backtest(
            session, drifted, dataset_snapshot_id=snap.id, until=dev_end, config=cfg
        )


def test_a_mismatched_run_is_refused_unless_explicitly_allowed(session: Session) -> None:
    """The scan reads the newest row, so a run gates 1-8 never measured must
    not be written silently; the override is recorded in provenance."""
    snap, cfg, _, dev_end = _evaluated(session)
    rec = record_development_oos_backtest(
        session,
        _mr(),
        dataset_snapshot_id=snap.id,
        until=dev_end - timedelta(days=90),
        config=cfg,
        persist=False,
    )
    assert rec.reproduces_evaluation["until"] is False
    assert rec.reproduces_evaluation["window_start"] is True

    with pytest.raises(ValueError, match=r"inputs differ .*\(until\)"):
        persist_development_oos_record(session, rec)
    assert _n_runs(session) == 0

    saved = persist_development_oos_record(session, rec, allow_mismatch=True)
    params = session.get(BacktestRun, saved.backtest_run_id).params_json
    assert params["allow_mismatch"] is True
    assert params["mismatched_inputs"] == ["until"]


def test_a_repeat_of_a_recorded_run_is_refused_unless_forced(session: Session) -> None:
    snap, cfg, _, dev_end = _evaluated(session)
    first = record_development_oos_backtest(
        session, _mr(), dataset_snapshot_id=snap.id, until=dev_end, config=cfg
    )
    again = record_development_oos_backtest(
        session, _mr(), dataset_snapshot_id=snap.id, until=dev_end, config=cfg, persist=False
    )
    with pytest.raises(ValueError, match=f"backtest_run {first.backtest_run_id} already"):
        persist_development_oos_record(session, again)
    assert _n_runs(session) == 1

    forced = persist_development_oos_record(session, again, allow_duplicate=True)
    assert _n_runs(session) == 2
    params = session.get(BacktestRun, forced.backtest_run_id).params_json
    assert params["duplicates_backtest_run_ids"] == [first.backtest_run_id]

    # a different (allowed) window is not a duplicate of the first
    other = record_development_oos_backtest(
        session,
        _mr(),
        dataset_snapshot_id=snap.id,
        until=dev_end - timedelta(days=90),
        config=cfg,
        persist=False,
    )
    assert persist_development_oos_record(session, other, allow_mismatch=True).backtest_run_id


def test_runs_in_the_evaluations_symbol_order_so_the_ci_reproduces(session: Session) -> None:
    """The bootstrap CI depends on trade order, which follows symbol order: a
    snapshot storing the evaluated set in another order must still reproduce
    gate 4's CI exactly, not a reshuffled one."""
    universe = ["SPY", "AAPL", "MSFT", "QQQ"]
    ingest_universe(session, FixtureMarketDataAdapter(), universe, START, END)
    session.flush()
    snap = get_or_create_dataset_snapshot(session, key="dev_oos_order", symbols=sorted(universe))
    assert snap.symbols_json != universe
    cfg = effective_research_config(session)
    result = evaluate_promotion(
        session, _mr(), symbols=universe, start=START, end=END, config=cfg, dataset_snapshot=snap
    )
    sealed = session.get(StrategySealedTest, result.sealed_test_id)
    rec = record_development_oos_backtest(
        session,
        _mr(),
        dataset_snapshot_id=snap.id,
        until=sealed.window_start - timedelta(days=1),
        config=cfg,
        persist=False,
    )
    gates = {g.number: g.evidence for g in result.gates}
    assert rec.result.symbols == universe
    assert all(rec.reproduces_evaluation.values()), rec.reproduces_evaluation
    assert rec.result.oos_ci["expectancy_r"] == pytest.approx(gates[4]["ci"])
    # and the order genuinely matters: the snapshot's order measures another CI
    reordered = run_development_backtest(
        session,
        _mr(),
        symbols=list(snap.symbols_json),
        start=START,
        pre_sealed_end=rec.until,
        source=rec.provenance["source"],
        config=cfg,
    )
    assert reordered.oos_ci["expectancy_r"] != pytest.approx(gates[4]["ci"])


# ---- CLI --------------------------------------------------------------------
def _cli(*args: str):
    return CliRunner().invoke(app, ["record-oos-backtest", *args])


def test_cli_refuses_an_unknown_strategy_key(db_url: str) -> None:
    out = _cli("--strategy", "no_such.strategy", "--snapshot-id", "1", "--until", "2025-09-07")
    assert out.exit_code == 1
    assert "no default strategy" in out.output


def test_cli_refuses_a_missing_snapshot_and_bad_dates(db_url: str) -> None:
    out = _cli(
        "--strategy",
        "mean_reversion.short_swing",
        "--snapshot-id",
        "999",
        "--until",
        "2025-09-07",
        "--dry-run",
    )
    assert out.exit_code == 1
    assert "no dataset snapshot with id 999" in out.output

    bad = _cli("--strategy", "mean_reversion.short_swing", "--snapshot-id", "1", "--until", "x")
    assert bad.exit_code == 1
    assert "YYYY-MM-DD" in bad.output


def test_cli_dry_run_then_record(db_url: str, session: Session) -> None:
    """End to end on a default strategy: dry run writes nothing; the real run
    writes one BacktestRun that latest_oos_metric then returns."""
    ingest_universe(session, FixtureMarketDataAdapter(), UNIVERSE, START, END)
    session.flush()
    snap = get_or_create_dataset_snapshot(session, key="dev_oos_cli", symbols=UNIVERSE)
    strat = MeanReversion()
    result = evaluate_promotion(
        session, strat, symbols=UNIVERSE, start=START, end=END, dataset_snapshot=snap
    )
    session.commit()
    sealed = session.get(StrategySealedTest, result.sealed_test_id)
    dev_end = sealed.window_start - timedelta(days=1)
    args = ("--strategy", strat.key, "--snapshot-id", str(snap.id), "--until", dev_end.isoformat())

    dry = _cli(*args, "--dry-run")
    assert dry.exit_code == 0, dry.output
    assert "dry run — nothing written" in dry.output
    assert "WARNING" not in dry.output
    assert f"evaluation {result.evaluation_id} recorded" in dry.output
    session.rollback()  # end the read snapshot so the CLI's commit is visible
    assert _n_runs(session) == 0

    real = _cli(*args)
    assert real.exit_code == 0, real.output
    assert "recorded backtest_run" in real.output
    session.rollback()  # end the read snapshot so the CLI's commit is visible
    assert _n_runs(session) == 1
    assert latest_oos_metric(session, strat.spec()) is not None
    ev = session.get(StrategyPromotionEvaluation, result.evaluation_id)
    assert ev is not None  # untouched

    repeat = _cli(*args)
    assert repeat.exit_code == 1
    assert "already records" in repeat.output
    session.rollback()
    assert _n_runs(session) == 1
    forced = _cli(*args, "--force")
    assert forced.exit_code == 0, forced.output
    session.rollback()
    assert _n_runs(session) == 2

    early = (dev_end - timedelta(days=90)).isoformat()
    mismatch = _cli("--strategy", strat.key, "--snapshot-id", str(snap.id), "--until", early)
    assert mismatch.exit_code == 1
    assert "--allow-mismatch" in mismatch.output
    session.rollback()
    assert _n_runs(session) == 2

    late = _cli(
        "--strategy",
        strat.key,
        "--snapshot-id",
        str(snap.id),
        "--until",
        sealed.window_start.isoformat(),
    )
    assert late.exit_code == 1
    assert "sealed window" in late.output
