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
    DataSnapshot,
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
    get_or_create_dataset_snapshot,
)
from signalforge.research.strategies import (
    IntradayORB,
    MeanReversion,
    RelativeStrength,
    TrendContinuation,
    VolatilityBreakout,
)
from signalforge.settings_store import effective_research_config

# The spec_json_hashes the LIVE approvals of strategy versions 2 and 5 are
# recorded under (evals 20/32 and 23/35). Public content hashes, not secrets.
HV2 = "2ed9743170bd3bbdb450ea03a004a7ffaeb64ccbbe6075db312ffd544072f382"  # pragma: allowlist secret
HV5 = "dfe696b662dd02b8fa3a02ce5b987c6eade84a40d88c1a2d8d52e206cb6f6c32"  # pragma: allowlist secret

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


# ---- dataset snapshots: a changed universe is new data, never a silent overwrite --------
def test_get_or_create_dataset_snapshot_reuses_by_exact_key(session: Session) -> None:
    a = get_or_create_dataset_snapshot(session, key="my_variant", symbols=UNIVERSE)
    b = get_or_create_dataset_snapshot(session, key="my_variant", symbols=UNIVERSE)
    assert a.id == b.id
    assert b.symbols_json == UNIVERSE


def test_get_or_create_dataset_snapshot_refuses_a_key_reused_with_different_symbols(
    session: Session,
) -> None:
    """Regression test: a keyed snapshot's contents are immutable — silently
    reusing an existing key for a genuinely different symbol set would
    misrepresent every future evaluation's provenance."""
    get_or_create_dataset_snapshot(session, key="my_variant", symbols=UNIVERSE)
    with pytest.raises(ValueError, match="different data"):
        get_or_create_dataset_snapshot(session, key="my_variant", symbols=["SPY"])


def test_get_or_create_dataset_snapshot_unkeyed_fallback_ignores_non_reusable_rows(
    session: Session,
) -> None:
    """Regression test: an audit-history snapshot marked
    reusable_by_new_evaluations=False (e.g. a migration-backfilled legacy
    row) must never be silently re-attached to by a new, unkeyed evaluation
    that happens to share its symbol set."""
    legacy = DataSnapshot(
        key="some_legacy_row",
        symbols_json=UNIVERSE,
        description="never reused by new evaluations",
        reusable_by_new_evaluations=False,
    )
    session.add(legacy)
    session.flush()

    resolved = get_or_create_dataset_snapshot(session, symbols=UNIVERSE)
    assert resolved.id != legacy.id  # a NEW snapshot was created, not the legacy one reused


def test_get_or_create_dataset_snapshot_reuses_by_matching_symbol_set(session: Session) -> None:
    a = get_or_create_dataset_snapshot(session, symbols=["AAPL", "SPY"])
    b = get_or_create_dataset_snapshot(
        session, symbols=["SPY", "AAPL"]
    )  # same set, different order
    assert a.id == b.id


def test_get_or_create_dataset_snapshot_creates_a_new_row_for_a_different_universe(
    session: Session,
) -> None:
    n0 = session.scalar(select(func.count()).select_from(DataSnapshot))
    a = get_or_create_dataset_snapshot(session, symbols=["AAPL", "SPY"])
    b = get_or_create_dataset_snapshot(session, symbols=["AAPL", "SPY", "MSFT"])
    assert a.id != b.id
    n = session.scalar(select(func.count()).select_from(DataSnapshot))
    assert n == n0 + 2


def test_two_dataset_snapshots_get_independent_sealed_tests(session: Session) -> None:
    """The core dataset-snapshot guarantee: evaluating the SAME strategy
    version against two DIFFERENT dataset snapshots must never reuse — or be
    blocked by — the other snapshot's locked sealed test."""
    _seed(session)
    cfg = _permissive_config(session)
    strat = MeanReversion()

    snap_a = get_or_create_dataset_snapshot(session, key="variant_a", symbols=UNIVERSE)
    snap_b = get_or_create_dataset_snapshot(
        session, key="variant_b", symbols=list(reversed(UNIVERSE))
    )

    r_a = evaluate_promotion(
        session, strat, symbols=UNIVERSE, start=START, end=END, config=cfg, dataset_snapshot=snap_a
    )
    r_b = evaluate_promotion(
        session, strat, symbols=UNIVERSE, start=START, end=END, config=cfg, dataset_snapshot=snap_b
    )

    assert r_a.dataset_snapshot_id == snap_a.id
    assert r_b.dataset_snapshot_id == snap_b.id
    assert r_a.sealed_test_id != r_b.sealed_test_id  # independently sealed, not shared/reused

    n_sealed = session.scalar(
        select(func.count())
        .select_from(StrategySealedTest)
        .where(StrategySealedTest.strategy_version_id == r_a.strategy_version_id)
    )
    assert n_sealed == 2  # one per dataset snapshot, neither overwrote the other

    # re-evaluating variant_a again must reuse ITS OWN sealed test, not variant_b's
    r_a2 = evaluate_promotion(
        session, strat, symbols=UNIVERSE, start=START, end=END, config=cfg, dataset_snapshot=snap_a
    )
    assert r_a2.sealed_test_id == r_a.sealed_test_id


def test_evaluate_promotion_without_a_dataset_snapshot_resolves_one_automatically(
    session: Session,
) -> None:
    """The common case: omitting dataset_snapshot must not error, and must
    transparently resolve/reuse a snapshot matching the given symbols."""
    _seed(session)
    cfg = _permissive_config(session)
    result = evaluate_promotion(
        session, MeanReversion(), symbols=UNIVERSE, start=START, end=END, config=cfg
    )
    assert result.dataset_snapshot_id is not None
    snap = session.get(DataSnapshot, result.dataset_snapshot_id)
    assert sorted(snap.symbols_json) == sorted(UNIVERSE)


# ---- item 5: gate 7's trade set is pinned so the comment can never drift ----
def test_gate7_uses_all_pre_sealed_trades_not_only_oos(session: Session) -> None:
    """Gate 7 measures ``full.trades`` — every pre-sealed trade, IS+OOS — not
    ``full.out_of_sample``. ``config/research.py`` used to document it as "OOS
    Sharpe"; the comment was corrected, the code deliberately was not. This
    test pins the behaviour so the two can never silently diverge again."""
    from signalforge.backtest.costs import CostModel
    from signalforge.research.backtest_runner import run_strategy_over_universe
    from signalforge.research.portfolio_metrics import compute_portfolio_metrics

    _seed(session)
    cfg = _permissive_config(session)
    result = evaluate_promotion(
        session, MeanReversion(), symbols=UNIVERSE, start=START, end=END, config=cfg
    )
    gate7 = next(g for g in result.gates if g.number == 7)

    sealed_start = END - timedelta(days=cfg.promotion.sealed_window_days)
    pre_sealed_end = sealed_start - timedelta(days=1)
    cost_model = CostModel(
        commission_per_share=cfg.commission_per_share,
        commission_min_per_order=cfg.commission_min_per_order,
        slippage_bps=cfg.slippage_bps,
        half_spread_fill_penalty=cfg.half_spread_fill_penalty,
    )
    full = run_strategy_over_universe(
        session,
        MeanReversion(),
        UNIVERSE,
        START,
        pre_sealed_end,
        cost_model=cost_model,
    )
    proxy = PriceSeries.load(session, "SPY", START, pre_sealed_end)
    span = [d for d in proxy.dates if START <= d <= pre_sealed_end]
    lo, hi = (span[0], span[-1]) if span else (START, pre_sealed_end)

    all_trades = compute_portfolio_metrics(full.trades, span_start=lo, span_end=hi)

    assert gate7.evidence["strategy"] == all_trades.to_dict()
    assert gate7.evidence["strategy"]["n_trades"] == len(full.trades)
    # the two really are different populations on this fixture, so the
    # assertion above is not vacuous: gate 7 sees strictly more trades than
    # the out-of-sample slice gates 2/3/4 read.
    assert full.out_of_sample.n_trades < len(full.trades)
    assert gate7.evidence["strategy"]["n_trades"] != full.out_of_sample.n_trades


# ---- item 1: gate 6 never drops a trade in silence -------------------------
def _legacy_bucket_counts(trades, regimes) -> dict[str, int]:
    """The pre-hardening gate-6 loop, verbatim, as a golden reference."""
    counts = {"bull": 0, "bear": 0, "range": 0}
    for t in trades:
        lbl = regimes.get(t.entry_date, "warmup")
        if lbl == "range_bound":
            counts["range"] += 1
        elif lbl.startswith("bull"):
            counts["bull"] += 1
        elif lbl.startswith("bear"):
            counts["bear"] += 1
    return counts


def test_gate6_reports_warmup_trades_and_never_drops_one(session: Session) -> None:
    """Trades inside the proxy's 200-session warmup used to be counted in no
    bucket and mentioned nowhere. They must now be reported, and the census
    must close: bucketed + unbucketed == every trade considered."""
    _seed(session)
    cfg = _permissive_config(session)
    result = evaluate_promotion(
        session, MeanReversion(), symbols=UNIVERSE, start=START, end=END, config=cfg
    )
    gate6 = next(g for g in result.gates if g.number == 6)
    ub = gate6.evidence["unbucketed"]
    buckets = gate6.evidence["trades_per_regime"]

    assert ub["census_closes"] is True
    assert (
        sum(buckets.values()) + ub["warmup"] + ub["no_proxy_bar"] + ub["unlabelled"]
        == gate6.evidence["n_trades_considered"]
    )
    assert ub["total"] == ub["warmup"] + ub["no_proxy_bar"] + ub["unlabelled"]
    assert ub["trend_lookback_sessions"] == 200
    assert ub["warmup"] > 0  # this fixture really does trade inside the warmup
    assert "unbucketed:" in gate6.detail
    assert "with no proxy bar" in gate6.detail
    assert f"{ub['warmup']} inside the 200-session proxy warmup" in gate6.detail


def test_gate6_distinguishes_warmup_from_a_missing_proxy_bar() -> None:
    """The old ``regimes.get(date, "warmup")`` default made a genuine data
    defect (a trade on a session the proxy has no bar for) indistinguishable
    from the labeller's own warmup. They are now separate counters."""
    from signalforge.research.promotion import _regime_census

    class _T:
        def __init__(self, d: date) -> None:
            self.entry_date = d

    d0, d1, d2, d3 = (date(2020, 1, i) for i in (6, 7, 8, 9))
    regimes = {d0: "warmup", d1: "bull_lowvol", d2: "range_bound"}
    trades = [_T(d0), _T(d1), _T(d2), _T(d3)]  # d3 has no proxy bar at all

    census = _regime_census(trades, regimes)
    assert census.buckets == {"bull": 1, "bear": 0, "range": 1}
    assert census.warmup == 1
    assert census.no_proxy_bar == 1
    assert census.unlabelled == 0
    assert census.unbucketed == 2
    assert census.closes is True

    # removing the proxy bar for a bucketed trade moves exactly one trade from
    # its bucket to no_proxy_bar — the warmup count is untouched
    without = _regime_census(trades, {d0: "warmup", d2: "range_bound"})
    assert without.buckets == {"bull": 0, "bear": 0, "range": 1}
    assert without.no_proxy_bar == 2
    assert without.warmup == 1


def test_gate6_census_reports_a_discrepancy_instead_of_hiding_it() -> None:
    """If the accounting ever fails to close, the detail string says so — a
    trade must never vanish quietly."""
    from signalforge.research.promotion import _RegimeCensus, _unbucketed_detail

    broken = _RegimeCensus(
        buckets={"bull": 5, "bear": 1, "range": 2},
        warmup=1,
        no_proxy_bar=0,
        unlabelled=0,
        n_trades=20,
    )
    assert broken.closes is False
    detail = _unbucketed_detail(broken, {"warmup_last_date": "2017-08-02", "share_of_trades": 0.05})
    assert "CENSUS DOES NOT CLOSE" in detail
    assert "8 bucketed + 1 unbucketed != 20 trades" in detail


def test_gate6_bucket_counts_are_unchanged_by_the_reporting_change(session: Session) -> None:
    """The scoring-neutrality guarantee: the decomposition changed what is
    REPORTED, never what is counted. Buckets and the pass verdict must equal
    the pre-hardening loop's output on the same trades and labels."""
    from signalforge.backtest.costs import CostModel
    from signalforge.backtest.regime import label_regimes
    from signalforge.research.backtest_runner import run_strategy_over_universe

    _seed(session)
    cfg = _permissive_config(session)
    strict = cfg.model_copy(
        update={
            "promotion": cfg.promotion.model_copy(
                update={"min_regimes_covered": 3, "min_trades_per_regime": 10}
            )
        }
    )
    result = evaluate_promotion(
        session, MeanReversion(), symbols=UNIVERSE, start=START, end=END, config=strict
    )
    gate6 = next(g for g in result.gates if g.number == 6)

    sealed_start = END - timedelta(days=strict.promotion.sealed_window_days)
    pre_sealed_end = sealed_start - timedelta(days=1)
    full = run_strategy_over_universe(
        session,
        MeanReversion(),
        UNIVERSE,
        START,
        pre_sealed_end,
        cost_model=CostModel(
            commission_per_share=strict.commission_per_share,
            commission_min_per_order=strict.commission_min_per_order,
            slippage_bps=strict.slippage_bps,
            half_spread_fill_penalty=strict.half_spread_fill_penalty,
        ),
    )
    regimes = label_regimes(PriceSeries.load(session, "SPY", START, pre_sealed_end))
    legacy = _legacy_bucket_counts(full.trades, regimes)

    assert gate6.evidence["trades_per_regime"] == legacy
    covered = sum(1 for c in legacy.values() if c >= 10)
    assert gate6.passed is bool(covered >= 3)


def test_gate6_extended_proxy_labelling_is_diagnostic_only(session: Session) -> None:
    """Change C: when pre-window proxy history exists, the extended labelling
    recovers warmup trades — and is reported as a diagnostic ONLY. The pass
    verdict still follows the strict labelling, because moving trades into
    buckets can only make gate 6 easier to clear (R4)."""
    _seed(session)
    cfg = _permissive_config(session)
    later_start = START + timedelta(days=800)  # leaves real proxy history before `start`
    result = evaluate_promotion(
        session, MeanReversion(), symbols=UNIVERSE, start=later_start, end=END, config=cfg
    )
    gate6 = next(g for g in result.gates if g.number == 6)
    ext = gate6.evidence["unbucketed"]["extended_labelling"]

    assert ext["bars_gained"] > 0  # the extension really did find earlier bars
    assert ext["used_for_scoring"] is False
    assert ext["warmup"] < gate6.evidence["unbucketed"]["warmup"]  # labels recovered
    assert sum(ext["trades_per_regime"].values()) >= sum(
        gate6.evidence["trades_per_regime"].values()
    )
    # the scored buckets are the STRICT ones, not the extended ones
    covered = sum(
        1
        for c in gate6.evidence["trades_per_regime"].values()
        if c >= gate6.evidence["min_trades_per_regime"]
    )
    assert gate6.passed is bool(covered >= cfg.promotion.min_regimes_covered)


def test_gate6_extension_is_a_noop_when_no_earlier_proxy_history_exists(session: Session) -> None:
    """On a window that starts at (or before) the proxy's first bar — exactly
    the live snapshot-3 case — the extension gains nothing and the diagnostic
    says so explicitly rather than implying a fix happened."""
    _seed(session)
    cfg = _permissive_config(session)
    result = evaluate_promotion(
        session, MeanReversion(), symbols=UNIVERSE, start=START, end=END, config=cfg
    )
    ext = next(g for g in result.gates if g.number == 6).evidence["unbucketed"][
        "extended_labelling"
    ]
    assert ext["bars_gained"] == 0
    assert ext["identical_to_strict"] is True


# ---- items 4 + 6: the sealed-look ledger and the staleness report ----------
def _insert_sealed(
    session: Session,
    *,
    strategy_name: str,
    version: str,
    snapshot_key: str,
    evaluated_at,
    n_trades: int = 12,
    expectancy_r: float = 0.1,
    passed: bool = True,
) -> StrategySealedTest:
    """A sealed test row, inserted directly — the ledger is a read-only
    derivation, so it must be provable against hand-built history."""
    from signalforge.domain import Horizon

    strat = session.scalar(select(Strategy).where(Strategy.name == strategy_name))
    if strat is None:
        strat = Strategy(
            name=strategy_name,
            horizon=Horizon.SHORT_SWING,
            permits_long=True,
            permits_short=False,
            status=StrategyStatus.EXPERIMENTAL,
        )
        session.add(strat)
        session.flush()
    ver = session.scalar(
        select(StrategyVersion).where(
            StrategyVersion.strategy_id == strat.id, StrategyVersion.version == version
        )
    )
    if ver is None:
        ver = StrategyVersion(
            strategy_id=strat.id, version=version, git_sha="deadbeef", spec_json={}
        )
        session.add(ver)
        session.flush()
    snap = session.scalar(select(DataSnapshot).where(DataSnapshot.key == snapshot_key))
    if snap is None:
        snap = DataSnapshot(key=snapshot_key, symbols_json=list(UNIVERSE))
        session.add(snap)
        session.flush()
    row = StrategySealedTest(
        strategy_version_id=ver.id,
        dataset_snapshot_id=snap.id,
        window_start=date(2024, 1, 1),
        window_end=date(2024, 12, 31),
        universe_json=list(UNIVERSE),
        data_provenance_json={},
        metrics_json={"n_trades": n_trades, "expectancy_r": expectancy_r},
        benchmark_metrics_json={},
        passed=passed,
        detail="seeded",
        evaluated_at=evaluated_at,
    )
    session.add(row)
    session.flush()
    return row


def test_sealed_look_ledger_counts_every_snapshot_for_a_family(session: Session) -> None:
    """k is a count over the whole family — every snapshot the family was ever
    sealed against, not just the one in front of you."""
    from datetime import UTC, datetime

    from signalforge.research.promotion import count_sealed_looks, sealed_look_ledger

    for i in range(3):
        _insert_sealed(
            session,
            strategy_name="fake_family.short_swing",
            version="0.1.0",
            snapshot_key=f"snap_{i}",
            evaluated_at=datetime(2024, 1, i + 1, tzinfo=UTC),
        )

    assert count_sealed_looks(session, "fake_family.short_swing") == 3
    ledger = sealed_look_ledger(session, "fake_family.short_swing", k_prior=3)
    assert ledger["k_prior"] == 3
    assert [x["index"] for x in ledger["looks"]] == [1, 2, 3]
    assert len({x["dataset_snapshot_id"] for x in ledger["looks"]}) == 3
    # a fourth evaluation that seals would be look 4
    fourth = _insert_sealed(
        session,
        strategy_name="fake_family.short_swing",
        version="0.1.0",
        snapshot_key="snap_3",
        evaluated_at=datetime(2024, 1, 9, tzinfo=UTC),
    )
    after = sealed_look_ledger(
        session, "fake_family.short_swing", k_prior=3, this_run_sealed_test_id=fourth.id
    )
    assert after["this_look"] == 4
    assert after["reused_this_run"] is False
    assert "look 4 of this strategy family (3 prior sealed tests: ids " in _look_line(after)


def _look_line(ledger) -> str:
    from signalforge.research.promotion import format_sealed_look_line

    return format_sealed_look_line(ledger)


def test_sealed_look_ledger_spans_versions_within_a_family(session: Session) -> None:
    """A v0.2.0 does not reset the multiple-testing budget its v0.1.0 spent:
    k counts every version of the same Strategy.name."""
    from datetime import UTC, datetime

    from signalforge.research.promotion import count_sealed_looks, sealed_look_ledger

    for i in range(4):
        _insert_sealed(
            session,
            strategy_name="fake_family.short_swing",
            version="0.1.0",
            snapshot_key=f"snap_{i}",
            evaluated_at=datetime(2024, 1, i + 1, tzinfo=UTC),
        )
    assert count_sealed_looks(session, "fake_family.short_swing") == 4

    new = _insert_sealed(
        session,
        strategy_name="fake_family.short_swing",
        version="0.2.0",
        snapshot_key="snap_0",
        evaluated_at=datetime(2024, 2, 1, tzinfo=UTC),
    )
    ledger = sealed_look_ledger(
        session, "fake_family.short_swing", k_prior=4, this_run_sealed_test_id=new.id
    )
    assert ledger["k_prior"] == 4
    assert ledger["this_look"] == 5
    assert {x["version"] for x in ledger["looks"]} == {"0.1.0", "0.2.0"}
    assert [x["is_this_run"] for x in ledger["looks"]] == [False, False, False, False, True]


def test_sealed_look_ledger_ordering_is_deterministic(session: Session) -> None:
    """Ordered by (evaluated_at, id) — including when timestamps tie, which is
    exactly when 'whatever SQLite returns' would otherwise decide."""
    from datetime import UTC, datetime

    from signalforge.research.promotion import sealed_look_ledger

    same = datetime(2024, 3, 1, tzinfo=UTC)
    ids = [
        _insert_sealed(
            session,
            strategy_name="fake_family.short_swing",
            version="0.1.0",
            snapshot_key=f"snap_tie_{i}",
            evaluated_at=same,
        ).id
        for i in range(3)
    ]
    a = sealed_look_ledger(session, "fake_family.short_swing")
    b = sealed_look_ledger(session, "fake_family.short_swing")
    assert a == b
    assert [x["sealed_test_id"] for x in a["looks"]] == sorted(ids)


def test_sealed_look_index_does_not_advance_on_a_reused_sealed_test(session: Session) -> None:
    """Re-running the same (version, snapshot) replays a locked row. That is
    not a new look and must never be reported as one."""
    _seed(session)
    cfg = _permissive_config(session)
    strat = TrendContinuation()

    first = evaluate_promotion(session, strat, symbols=UNIVERSE, start=START, end=END, config=cfg)
    second = evaluate_promotion(session, strat, symbols=UNIVERSE, start=START, end=END, config=cfg)

    assert first.sealed_test_reused is False
    assert first.sealed_look_prior == 0
    assert first.sealed_look_index == 1

    assert second.sealed_test_reused is True
    assert second.sealed_test_id == first.sealed_test_id
    assert second.sealed_look_index == 1  # the replayed row's own index, not 2
    g9 = next(g for g in second.gates if g.number == 9)
    assert g9.evidence["sealed_look_ledger"]["reused_this_run"] is True
    assert "no new look taken" in g9.detail


def test_sealed_look_ledger_is_reported_on_a_failing_evaluation(session: Session) -> None:
    """An undisclosed FAILED look is exactly the multiple-testing leak the
    counter exists to close, so it is reported on failures too."""
    _seed(session)
    cfg = effective_research_config(session)  # strict: this will not pass
    result = evaluate_promotion(
        session, MeanReversion(), symbols=UNIVERSE, start=START, end=END, config=cfg
    )
    assert result.passed is False
    g9 = next(g for g in result.gates if g.number == 9)
    assert g9.evidence["sealed_look_ledger"]["this_look"] == 1
    assert "look 1 of this strategy family" in g9.detail
    assert result.sealed_look_index == 1
    assert result.to_dict()["sealed_look_index"] == 1


def test_gate9_reports_a_locked_replay_with_its_id_and_evaluated_at(session: Session) -> None:
    """Item 6: the sealed row a run READ is either created by that run or
    explicitly reported as a LOCKED replay, with id and timestamp, in the
    evidence — no automated check should have to parse prose."""
    _seed(session)
    cfg = _permissive_config(session)
    strat = TrendContinuation()

    first = evaluate_promotion(session, strat, symbols=UNIVERSE, start=START, end=END, config=cfg)
    g9a = next(g for g in first.gates if g.number == 9)
    assert g9a.evidence["reused"] is False
    assert g9a.evidence["created_by_this_run"] is True
    assert g9a.evidence["sealed_evaluated_at"] is not None

    second = evaluate_promotion(session, strat, symbols=UNIVERSE, start=START, end=END, config=cfg)
    g9b = next(g for g in second.gates if g.number == 9)
    assert g9b.evidence["reused"] is True
    assert g9b.evidence["created_by_this_run"] is False
    assert g9b.evidence["sealed_evaluated_at"] == g9a.evidence["sealed_evaluated_at"]
    assert second.sealed_test_evaluated_at == g9a.evidence["sealed_evaluated_at"]
    assert f"LOCKED REPLAY of sealed test {g9a.evidence['sealed_test_id']}" in g9b.detail
    assert "NOT created by this run" in g9b.detail


def test_a_new_version_never_silently_reuses_the_previous_versions_sealed_row(
    session: Session,
) -> None:
    """The R3 trap: a v0.2.0 must seal its own row. Sealed tests are keyed on
    (strategy_version_id, dataset_snapshot_id), so verify that the row gate 9
    read really belongs to the version being evaluated."""
    from dataclasses import replace as _dc_replace

    _seed(session)
    cfg = _permissive_config(session)
    snap = get_or_create_dataset_snapshot(session, key="shared_snap", symbols=list(UNIVERSE))

    class _BumpedVersion(TrendContinuation):
        def spec(self):  # type: ignore[override]
            return _dc_replace(super().spec(), version="0.2.0")

    v1 = evaluate_promotion(
        session,
        TrendContinuation(),
        symbols=UNIVERSE,
        start=START,
        end=END,
        config=cfg,
        dataset_snapshot=snap,
    )
    v2 = evaluate_promotion(
        session,
        _BumpedVersion(),
        symbols=UNIVERSE,
        start=START,
        end=END,
        config=cfg,
        dataset_snapshot=snap,
    )

    assert v2.version == "0.2.0"
    assert v2.strategy_version_id != v1.strategy_version_id
    assert v2.sealed_test_id != v1.sealed_test_id
    assert v2.sealed_test_reused is False  # it sealed its own row, on the same snapshot

    g9 = next(g for g in v2.gates if g.number == 9)
    assert g9.evidence["sealed_strategy_version_id"] == v2.strategy_version_id
    assert g9.evidence["evaluated_strategy_version_id"] == v2.strategy_version_id
    # and the family ledger counts the v0.1.0 look the v0.2.0 inherited
    assert v2.sealed_look_prior == 1
    assert v2.sealed_look_index == 2
    assert {x["version"] for x in g9.evidence["sealed_look_ledger"]["looks"]} == {"0.1.0", "0.2.0"}


# ---- item 2: declared gate-5 axes live on the CLASS, never on StrategySpec --
def _declaring(axes):
    """A TrendContinuation that declares extra sensitivity axes."""

    class _Declaring(TrendContinuation):
        def sensitivity_axes(self):  # type: ignore[override]
            return axes

    return _Declaring()


def test_declared_axes_extend_the_family_grid() -> None:
    """`time_stop_bars` is the only thing distinguishing v2 from v3 and gate 5
    never varies it (MAP §0.5). A declaration adds it without touching the
    shipped grid."""
    import math as _math

    plan = _sensitivity_plan(_declaring({"time_stop_bars": [5, 10, 20]}))
    assert plan is not None
    _factory, grid = plan
    assert set(grid) == {"sma_fast", "stop_atr", "time_stop_bars"}
    assert grid["sma_fast"] == [15, 20, 25]  # shipped axis untouched
    assert grid["stop_atr"] == [1.2, 1.5, 1.8]
    assert _math.prod(len(v) for v in grid.values()) == 27


def test_undeclared_strategies_keep_their_shipped_nine_point_grid() -> None:
    """The R4 floor for this item: every v0.1.0 grid is unchanged."""
    import math as _math

    expected = {
        "relative_strength.medium_swing": {
            "excess_return_min": [0.03, 0.05, 0.07],
            "lookback": [42, 63, 84],
        },
        "trend_continuation.short_swing": {
            "sma_fast": [15, 20, 25],
            "stop_atr": [1.2, 1.5, 1.8],
        },
        "mean_reversion.short_swing": {
            "z_entry": [-2.5, -2.0, -1.5],
            "stop_atr": [1.5, 2.0, 2.5],
        },
        "volatility_breakout.short_swing": {
            "contraction_max": [0.65, 0.75, 0.85],
            "stop_atr": [1.5, 1.75, 2.0],
        },
    }
    for strat in (RelativeStrength(), TrendContinuation(), MeanReversion(), VolatilityBreakout()):
        plan = _sensitivity_plan(strat)
        assert plan is not None
        _f, grid = plan
        assert grid == expected[strat.key], strat.key
        assert _math.prod(len(v) for v in grid.values()) == 9


def test_declared_axis_not_on_params_raises_at_plan_time() -> None:
    """Better a loud failure at plan time than dataclasses.replace blowing up
    mid-grid, after hours of backtests."""
    with pytest.raises(ValueError, match="not a field of TrendParams"):
        _sensitivity_plan(_declaring({"no_such_param": [1, 2, 3]}))


def test_declared_axis_without_the_baseline_value_raises() -> None:
    with pytest.raises(ValueError, match="without its baseline value"):
        _sensitivity_plan(_declaring({"time_stop_bars": [5, 20, 40]}))  # baseline is 10


def test_a_declaration_may_not_shrink_a_shipped_axis() -> None:
    with pytest.raises(ValueError, match="never shrink"):
        _sensitivity_plan(_declaring({"sma_fast": [15, 20]}))  # drops the shipped 25


def test_a_declaration_may_widen_a_shipped_axis() -> None:
    plan = _sensitivity_plan(_declaring({"sma_fast": [10, 15, 20, 25]}))
    assert plan is not None
    assert plan[1]["sma_fast"] == [10, 15, 20, 25]


def test_declared_axes_over_the_grid_cap_raise() -> None:
    from signalforge.research.sensitivity import MAX_GRID_POINTS

    big = {"time_stop_bars": [10, *range(100, 100 + MAX_GRID_POINTS)]}
    with pytest.raises(ValueError, match="cap is"):
        _sensitivity_plan(_declaring(big))


def test_declared_axes_are_usable_by_the_factory() -> None:
    plan = _sensitivity_plan(_declaring({"time_stop_bars": [5, 10, 20]}))
    assert plan is not None
    factory, grid = plan
    built = factory({k: v[0] for k, v in grid.items()})
    assert built.params.time_stop_bars == 5


def test_declaring_axes_does_not_change_spec_json_hash() -> None:
    """The R7 guard. The axis declaration lives on the strategy CLASS
    precisely so ``asdict(spec)`` — and therefore ``spec_json_hash`` — cannot
    move. These two literals are the hashes the LIVE approved scopes of
    versions 2 and 5 are recorded under (evals 20/32 and 23/35): if either
    ever changes, ``scan_scope_matches`` returns False forever and both
    PAPER_APPROVED strategies fall permanently out of scope. A red test here
    is the intended outcome of any future spec-shape change."""
    from signalforge.research.persistence import spec_json_hash

    assert spec_json_hash(TrendContinuation().spec()) == HV2
    assert spec_json_hash(RelativeStrength().spec()) == HV5
    # declaring axes changes nothing about the spec or its hash
    assert spec_json_hash(_declaring({"time_stop_bars": [5, 10, 20]}).spec()) == spec_json_hash(
        TrendContinuation().spec()
    )


def test_gate5_evidence_records_per_axis_movement(session: Session) -> None:
    """The pipeline records the no-op check's per-axis verdict, so a grid that
    tested nothing on an axis is visible in the stored evidence rather than
    only in a reason string."""
    _seed(session)
    cfg = _permissive_config(session)
    result = evaluate_promotion(
        session, TrendContinuation(), symbols=UNIVERSE, start=START, end=END, config=cfg
    )
    gate5 = next(g for g in result.gates if g.number == 5)
    assert set(gate5.evidence["axis_moved"]) == {"sma_fast", "stop_atr"}
    assert gate5.evidence["inert_axes"] == []


# ---- item 7: gate 8 exercises the breakout family's own entry features -----
def test_gate8_leakage_check_covers_the_breakout_entry_features() -> None:
    """`atr_contraction`, `donchian_high` and `true_range` are what
    volatility_breakout's entry rule is built on, and gate 8 never touched
    them — so its v0.1.0 pass said nothing about them. R4 carve-out: adding
    checks can only create new ways to fail."""
    from signalforge.research.promotion import LEAKAGE_FEATURE_CHECKS

    names = [name for name, _fn in LEAKAGE_FEATURE_CHECKS]
    assert names == [
        "sma(50)",
        "rolling_return(20)",
        "atr(14)",
        "realized_vol(20)",
        "atr_contraction(10,50)",
        "atr_contraction(10,50) @ t-5",
        "donchian_high(20)",
        "true_range",
    ]


def test_the_four_new_leakage_checks_pass_on_real_series(session: Session) -> None:
    """Verify assert_no_lookahead on each of the four additions directly. If
    one of these ever fails, the finding is about features/daily.py — which
    the already-approved v2 and v5 also depend on — not about any one
    strategy, and must be reported that way."""
    from signalforge.backtest.leakage import assert_no_lookahead
    from signalforge.research.promotion import LEAKAGE_FEATURE_CHECKS

    _seed(session)
    series = PriceSeries.load(session, "SPY", START, END)
    assert len(series) > 200
    new_checks = dict(LEAKAGE_FEATURE_CHECKS)
    for name in (
        "atr_contraction(10,50)",
        "atr_contraction(10,50) @ t-5",
        "donchian_high(20)",
        "true_range",
    ):
        assert_no_lookahead(new_checks[name], series)  # raises LookaheadDetected if dirty


def test_gate8_leakage_self_check_is_clean_on_the_fixture_universe(session: Session) -> None:
    from signalforge.research.promotion import _leakage_self_check

    _seed(session)
    assert _leakage_self_check(session, "SPY", START, END, None) is None


def test_cli_sealed_look_summary_reads_the_gate9_ledger() -> None:
    """The CLI's disclosure line is derived from gate 9's stored ledger, so
    the printed count can never disagree with the recorded evidence."""
    from types import SimpleNamespace

    from signalforge.cli import _sealed_look_summary
    from signalforge.research.promotion import Gate

    ledger = {
        "strategy_key": "trend_continuation.short_swing",
        "k_prior": 4,
        "this_look": 5,
        "reused_this_run": False,
        "total_sealed_tests": 5,
        "looks": [{"sealed_test_id": i, "is_this_run": i == 21} for i in (1, 6, 11, 16, 21)],
    }
    result = SimpleNamespace(
        strategy_key="trend_continuation.short_swing",
        sealed_look_prior=4,
        gates=[Gate(9, "sealed_final_test", True, "", {"sealed_look_ledger": ledger})],
    )
    line = _sealed_look_summary(result)
    assert "look 5 of this strategy family" in line
    assert "4 prior sealed tests: ids 1, 6, 11, 16" in line

    # a replay says so, and does not advance the count
    ledger_replay = {**ledger, "this_look": 3, "reused_this_run": True}
    ledger_replay["looks"] = [{"sealed_test_id": i, "is_this_run": i == 11} for i in (1, 6, 11, 16)]
    replay = SimpleNamespace(
        strategy_key="trend_continuation.short_swing",
        sealed_look_prior=4,
        gates=[Gate(9, "sealed_final_test", True, "", {"sealed_look_ledger": ledger_replay})],
    )
    line_replay = _sealed_look_summary(replay)
    assert "no new look taken" in line_replay
    # the replayed row IS one of the prior looks, so it stays in the id list
    assert "4 prior sealed tests: ids 1, 6, 11, 16; replayed id 11" in line_replay

    # a gate-0 short circuit takes no look at all and says that too
    early = SimpleNamespace(
        strategy_key="intraday_orb.intraday",
        sealed_look_prior=0,
        gates=[Gate(0, "data_availability", False, "", {})],
    )
    assert "no sealed look taken by this evaluation" in _sealed_look_summary(early)
