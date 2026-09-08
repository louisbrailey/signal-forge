"""Strategy-promotion pipeline: gate mechanics, sealed-test immutability,
NO-TRADE as the honest default, and that only this module ever approves.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge.data.adapters.fixture import FixtureMarketDataAdapter
from signalforge.data.ingest import ingest_universe
from signalforge.data.series import PriceSeries
from signalforge.db.models import (
    AuditLog,
    Strategy,
    StrategyPromotionEvaluation,
    StrategySealedTest,
    StrategyVersion,
)
from signalforge.domain import StrategyStatus
from signalforge.research.promotion import (
    VERDICT_APPROVED,
    VERDICT_NO_TRADE,
    _benchmark_metrics,
    _sensitivity_plan,
    evaluate_promotion,
)
from signalforge.research.strategies import (
    IntradayORB,
    MeanReversion,
    RelativeStrength,
    TrendContinuation,
    VolatilityBreakout,
)
from signalforge.settings_store import effective_research_config

UNIVERSE = ["SPY", "AAPL"]
END = date(2024, 12, 31)
START = END - timedelta(days=365 * 8)


def _seed(session: Session) -> None:
    ingest_universe(session, FixtureMarketDataAdapter(), UNIVERSE, START, END)
    session.flush()


def _permissive_config(session: Session):
    """A config whose promotion thresholds every real trade stream can clear —
    used to test the mechanics of a PASS without depending on fixture-data luck."""
    cfg = effective_research_config(session)
    lenient = cfg.promotion.model_copy(
        update={
            "min_walkforward_folds": 2,
            "min_oos_trades": 1,
            "min_net_expectancy_r": -999.0,
            "min_bootstrap_ci_low_r": -999.0,
            "sensitivity_positive_fraction_min": 0.0,
            "sensitivity_neighbour_fraction_min": 0.0,
            "sensitivity_min_grid_trades": 0,
            "min_regimes_covered": 0,
            "min_trades_per_regime": 0,
            "require_beat_benchmark_sharpe": False,
            "require_data_validation_pass": False,
            "require_leakage_check_pass": False,
            "sealed_min_trades": 0,
            "sealed_min_expectancy_r": -999.0,
        }
    )
    return cfg.model_copy(update={"promotion": lenient})


# ---------------------------------------------------------------------------
def test_no_trade_is_the_default_when_gates_are_strict(session: Session) -> None:
    """The canonical operational result when nothing clears the bar."""
    _seed(session)
    cfg = effective_research_config(session)  # real, strict, version-controlled thresholds
    strat = MeanReversion()
    result = evaluate_promotion(session, strat, symbols=UNIVERSE, start=START, end=END, config=cfg)

    assert len(result.gates) == 10
    assert all(g.number == i + 1 for i, g in enumerate(result.gates))
    if not result.passed:
        assert result.verdict == VERDICT_NO_TRADE
        row = session.get(
            Strategy,
            session.scalar(
                select(StrategyVersion.strategy_id).where(
                    StrategyVersion.id == result.strategy_version_id
                )
            ),
        )
        assert row.status is StrategyStatus.EXPERIMENTAL  # never silently promoted


def test_permissive_thresholds_still_run_every_gate_honestly(session: Session) -> None:
    """Loosening every *numeric* threshold does not fabricate a pass: gate 5
    (sensitivity) and gate 8 (data-quality) apply their own internal robustness
    rules regardless, so this only proves the pipeline evaluates real evidence
    end-to-end without crashing or silently promoting on a technicality."""
    _seed(session)
    cfg = _permissive_config(session)
    strat = MeanReversion()
    result = evaluate_promotion(session, strat, symbols=UNIVERSE, start=START, end=END, config=cfg)

    assert len(result.gates) == 10
    ver = session.get(StrategyVersion, result.strategy_version_id)
    if result.passed:
        assert ver.status is StrategyStatus.PAPER_APPROVED
    else:
        assert ver.status is StrategyStatus.EXPERIMENTAL
        assert result.verdict == VERDICT_NO_TRADE

    persisted = session.get(StrategyPromotionEvaluation, result.evaluation_id)
    assert persisted.passed == result.passed
    assert len(persisted.gates_json) == 10
    assert persisted.sealed_test_id is not None  # gate 9 always runs and locks


def test_finalize_promotes_and_records_when_every_gate_passes(session: Session) -> None:
    """Direct, deterministic check of the promotion mechanism itself: given ten
    passing gates, _finalize flips both Strategy and StrategyVersion status,
    writes the audit trail, and persists the evaluation — independent of
    whether any real strategy's evidence happens to clear every gate today."""
    from signalforge.research.persistence import upsert_strategy_version
    from signalforge.research.promotion import Gate, _finalize

    strat = MeanReversion()
    version = upsert_strategy_version(session, strat.spec())
    session.flush()
    cfg = _permissive_config(session)
    gates = [Gate(i, f"gate_{i}", True, "synthetic pass for this test") for i in range(1, 11)]

    result = _finalize(session, strat, version, cfg, UNIVERSE, START, END, gates, None, {})

    assert result.passed is True
    assert result.verdict == VERDICT_APPROVED

    ver = session.get(StrategyVersion, result.strategy_version_id)
    strat_row = session.get(Strategy, ver.strategy_id)
    assert ver.status is StrategyStatus.PAPER_APPROVED
    assert strat_row.status is StrategyStatus.PAPER_APPROVED

    persisted = session.get(StrategyPromotionEvaluation, result.evaluation_id)
    assert persisted.passed is True
    assert len(persisted.gates_json) == 10

    audit_row = session.scalar(
        select(AuditLog).where(
            AuditLog.action == "strategy.promote",
            AuditLog.entity == f"{strat.key}@{strat.spec().version}",
        )
    )
    assert audit_row is not None
    assert audit_row.after_json["status"] == "paper_approved"


def test_finalize_never_promotes_when_one_gate_fails(session: Session) -> None:
    from signalforge.research.persistence import upsert_strategy_version
    from signalforge.research.promotion import Gate, _finalize

    strat = TrendContinuation()
    version = upsert_strategy_version(session, strat.spec())
    session.flush()
    cfg = _permissive_config(session)
    gates = [Gate(i, f"gate_{i}", i != 7, "one gate fails") for i in range(1, 11)]

    result = _finalize(session, strat, version, cfg, UNIVERSE, START, END, gates, None, {})

    assert result.passed is False
    assert result.verdict == VERDICT_NO_TRADE
    ver = session.get(StrategyVersion, result.strategy_version_id)
    assert ver.status is StrategyStatus.EXPERIMENTAL
    assert (
        session.scalar(
            select(AuditLog).where(
                AuditLog.action == "strategy.promote",
                AuditLog.entity == f"{strat.key}@{strat.spec().version}",
            )
        )
        is None
    )


def test_sealed_test_is_computed_once_and_never_recomputed(session: Session) -> None:
    _seed(session)
    cfg = _permissive_config(session)
    strat = TrendContinuation()

    r1 = evaluate_promotion(session, strat, symbols=UNIVERSE, start=START, end=END, config=cfg)
    n_sealed = session.scalar(select(func.count()).select_from(StrategySealedTest))
    first_metrics = session.get(StrategySealedTest, r1.sealed_test_id).metrics_json

    # A second evaluation (e.g. re-run after a config tweak) must reuse the
    # SAME sealed row, byte-for-byte, never insert a second one.
    cfg2 = cfg.model_copy(
        update={"promotion": cfg.promotion.model_copy(update={"min_oos_trades": 2})}
    )
    r2 = evaluate_promotion(session, strat, symbols=UNIVERSE, start=START, end=END, config=cfg2)

    assert r2.sealed_test_id == r1.sealed_test_id
    assert session.scalar(select(func.count()).select_from(StrategySealedTest)) == n_sealed
    assert session.get(StrategySealedTest, r2.sealed_test_id).metrics_json == first_metrics

    # Two evaluation attempts are both preserved (append-only history).
    n_eval = session.scalar(
        select(func.count())
        .select_from(StrategyPromotionEvaluation)
        .where(StrategyPromotionEvaluation.strategy_version_id == r1.strategy_version_id)
    )
    assert n_eval == 2


def test_sealed_test_unique_constraint_is_enforced_at_the_db_level(session: Session) -> None:
    """review finding (sealed-test-integrity, medium): a concurrent
    ``evaluate_promotion`` race is survived by catching the IntegrityError a
    UniqueConstraint(strategy_version_id) throws on a second concurrent
    insert. Confirm that constraint is actually present and enforced — the
    safety net this depends on."""
    from sqlalchemy.exc import IntegrityError

    _seed(session)
    cfg = _permissive_config(session)
    result = evaluate_promotion(
        session, RelativeStrength(), symbols=UNIVERSE, start=START, end=END, config=cfg
    )
    sealed = session.get(StrategySealedTest, result.sealed_test_id)

    dupe = StrategySealedTest(
        strategy_version_id=sealed.strategy_version_id,
        window_start=sealed.window_start,
        window_end=sealed.window_end,
        universe_json=sealed.universe_json,
        data_provenance_json=sealed.data_provenance_json,
        metrics_json=sealed.metrics_json,
        benchmark_metrics_json=sealed.benchmark_metrics_json,
        passed=sealed.passed,
        detail=sealed.detail,
        evaluated_at=sealed.evaluated_at,
    )
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(dupe)
        session.flush()


def test_intraday_strategy_short_circuits_without_fabricating_a_result(session: Session) -> None:
    _seed(session)
    cfg = _permissive_config(session)
    result = evaluate_promotion(
        session, IntradayORB(), symbols=UNIVERSE, start=START, end=END, config=cfg
    )
    assert result.passed is False
    assert result.verdict == VERDICT_NO_TRADE
    assert len(result.gates) == 1
    assert result.gates[0].name == "data_availability"
    assert "intraday" in result.gates[0].detail


def test_benchmark_metrics_on_a_known_price_path() -> None:
    """A steady uptrend with tiny noise should show a strongly positive Sharpe
    and near-zero drawdown; a straight crash should show a deep drawdown."""
    dates = tuple(date(2020, 1, 1) + timedelta(days=i) for i in range(300))
    up = np.linspace(100, 150, 300)
    series_up = PriceSeries(
        symbol="X", dates=dates, open=up, high=up, low=up, close=up, volume=up * 0 + 1
    )
    m = _benchmark_metrics(series_up, dates[0], dates[-1])
    assert m["sharpe"] > 1.0
    assert m["max_drawdown_pct"] < 1.0

    down = np.linspace(150, 75, 300)
    series_down = PriceSeries(
        symbol="X", dates=dates, open=down, high=down, low=down, close=down, volume=down * 0 + 1
    )
    m2 = _benchmark_metrics(series_down, dates[0], dates[-1])
    assert m2["max_drawdown_pct"] > 40.0
    assert m2["sharpe"] < 0.0


@pytest.mark.parametrize(
    "strat",
    [
        RelativeStrength(),
        TrendContinuation(),
        MeanReversion(),
        VolatilityBreakout(),
    ],
)
def test_sensitivity_plan_covers_every_swing_strategy(strat) -> None:
    plan = _sensitivity_plan(strat)
    assert plan is not None
    factory, grid = plan
    assert 2 <= len(grid) <= 4
    # the factory must actually build a usable strategy instance
    overrides = {k: v[0] for k, v in grid.items()}
    built = factory(overrides)
    assert built.key == strat.key


def test_sensitivity_plan_is_none_for_an_unknown_strategy() -> None:
    class _Unknown:
        key = "totally_new_strategy.v1"

    assert _sensitivity_plan(_Unknown()) is None  # type: ignore[arg-type]


# ---- regression tests for the adversarial-review findings -----------------
def test_gate1_requires_actual_edge_not_just_any_trade_in_the_fold(session: Session) -> None:
    """review finding (gate-correctness, high): gate 1 used to pass as soon as
    half the folds had ANY trade, even a net-losing one. With an impossibly
    high per-fold expectancy bar, every fold has trades but none clears it —
    gate 1 must now fail, where the old logic would have passed it."""
    _seed(session)
    cfg = _permissive_config(session)
    strict_gate1 = cfg.model_copy(
        update={"promotion": cfg.promotion.model_copy(update={"min_net_expectancy_r": 999.0})}
    )
    result = evaluate_promotion(
        session, MeanReversion(), symbols=UNIVERSE, start=START, end=END, config=strict_gate1
    )
    gate1 = next(g for g in result.gates if g.number == 1)
    assert gate1.passed is False
    assert "folds_with_edge" not in gate1.detail or "clearing both" in gate1.detail
    assert gate1.evidence["folds"]  # still has real fold data to inspect
    assert any(f["n_trades"] > 0 for f in gate1.evidence["folds"])  # trades exist...
    # ...but none clear the (impossible) expectancy bar, so folds_with_edge must be 0


def test_min_presealed_span_is_tied_to_regime_warmup(session: Session) -> None:
    """review finding (stats-gate-soundness, low): the old fixed 180-day floor
    was below regime.py's 200-session TREND_LOOKBACK, so a span just above it
    would guarantee gate 6 fails with zero regime coverage regardless of
    strategy quality. Gate 0 must now reject such a span up front."""
    from signalforge.research.promotion import MIN_PRESEALED_DAYS

    assert MIN_PRESEALED_DAYS > 300  # meaningfully above the old 180-day floor
    short_end = START + timedelta(days=200)  # well under MIN_PRESEALED_DAYS + sealed window
    ingest_universe(session, FixtureMarketDataAdapter(), UNIVERSE, START, short_end)
    session.flush()
    cfg = _permissive_config(session)
    result = evaluate_promotion(
        session, MeanReversion(), symbols=UNIVERSE, start=START, end=short_end, config=cfg
    )
    assert result.passed is False
    assert len(result.gates) == 1
    assert result.gates[0].name == "data_availability"
    assert "regime" in result.gates[0].detail.lower()


def test_pre_sealed_and_sealed_windows_never_share_a_calendar_day(session: Session) -> None:
    """review finding (gate-correctness / sealed-test-integrity, low): the
    single calendar day at the pre-sealed/sealed boundary used to be loaded
    into BOTH windows (inclusive/inclusive on both sides of the same cutoff).
    The sealed window must now start strictly after every date gate 1's folds
    could have used."""
    _seed(session)
    cfg = _permissive_config(session)
    result = evaluate_promotion(
        session, TrendContinuation(), symbols=UNIVERSE, start=START, end=END, config=cfg
    )
    sealed_row = session.get(StrategySealedTest, result.sealed_test_id)
    gate1 = next(g for g in result.gates if g.number == 1)
    last_fold_end = date.fromisoformat(gate1.evidence["folds"][-1]["end"])
    assert last_fold_end < sealed_row.window_start


def test_sealed_window_is_pinned_across_a_later_reevaluation(session: Session) -> None:
    """review finding (sealed-test-integrity, high): re-evaluating the same
    strategy version after more data has been ingested must NOT let the
    pre-sealed span creep forward into what is already the locked sealed
    window from the first evaluation."""
    _seed(session)  # ingests [START, END]
    cfg = _permissive_config(session)
    strat = VolatilityBreakout()

    r1 = evaluate_promotion(session, strat, symbols=UNIVERSE, start=START, end=END, config=cfg)
    sealed1 = session.get(StrategySealedTest, r1.sealed_test_id)

    # more data arrives; a later "today" is used for the second evaluation
    later_end = END + timedelta(days=60)
    ingest_universe(session, FixtureMarketDataAdapter(), UNIVERSE, END, later_end)
    session.flush()
    r2 = evaluate_promotion(
        session, strat, symbols=UNIVERSE, start=START, end=later_end, config=cfg
    )

    assert r2.sealed_test_id == r1.sealed_test_id  # reused, not re-sealed
    sealed2 = session.get(StrategySealedTest, r2.sealed_test_id)
    assert sealed2.window_start == sealed1.window_start
    assert sealed2.window_end == sealed1.window_end

    gate1_r2 = next(g for g in r2.gates if g.number == 1)
    last_fold_end_r2 = date.fromisoformat(gate1_r2.evidence["folds"][-1]["end"])
    assert last_fold_end_r2 < sealed1.window_start  # gates 1-8 never crept into the locked window
