"""The evidence assembler and its clustered bootstrap (W3b).

Synthetic chains only: no provider is contacted and no real option price is read
anywhere in this file (R1).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge.backtest.options_engine import ExitReason, OptionTrade, RBasis, StructureType
from signalforge.backtest.options_pricing import IvSource
from signalforge.data.options_backfill import coverage_summary
from signalforge.db.models import (
    DataValidationReport,
    StrategyPromotionEvaluation,
    StrategySealedTest,
)
from signalforge.research.options_evidence import (
    CLUSTER_UNIT_D4,
    OPTIONS_CLUSTER_BOOTSTRAP_SEED,
    cluster_key_cycle_only,
    cluster_key_underlying_cycle,
    clustered_bootstrap_ci,
    coverage_preflight,
    expiry_cycle_of,
    latest_options_coverage_summary,
    load_option_chain_series,
    options_ladder_preview,
    preregistration_digest,
    preregistration_path,
)
from signalforge.research.options_evidence import (
    assemble_options_evidence as assemble,
)
from signalforge.research.options_gates import OPTIONS_LADDER_SHAPE
from tests.research.options_evidence_support import (
    EXPIRIES,
    SOURCE,
    StubOptionsStrategy,
    seed_coverage_run,
    seed_everything,
    seed_snapshot,
    window,
)


def _exit(i: int) -> date:
    """A distinct exit month per index, so each trade lands in its own cycle."""
    return date(2024, 3, 5) + timedelta(days=31 * i)


def _trade(symbol: str, entry: date, exit_: date, pnl_r: float, *, r: float = 380.0) -> OptionTrade:
    return OptionTrade(
        underlying_symbol=symbol,
        structure_type=StructureType.VERTICAL_CREDIT,
        r_basis=RBasis.INCL,
        entry_date=entry,
        exit_date=exit_,
        bars_held=10,
        pnl_r=pnl_r,
        pnl_dollars=pnl_r * r,
        r_dollars=r,
        r_at_print=r,
        r_incl=r,
        pnl_r_at_print=pnl_r,
        pnl_r_incl=pnl_r,
        net_credit_at_print=120.0,
        net_credit_received=118.0,
        entry_costs=2.0,
        exit_costs=2.0,
        dte_at_entry=35,
        dte_at_exit=5,
        exit_reason=ExitReason.PROFIT_TARGET,
        exit_deferred_sessions=0,
        unmarked_sessions=0,
        r_clamped=False,
        pin_risk_flag=False,
        assignment_risk=False,
        stop_non_binding=False,
        spread_multiplier=1.0,
        fill_model="test",
        iv_source=IvSource.LOCAL_BS_INVERTED,
        q_source="test",
        r_source="test",
    )


# --------------------------------------------------------------------------- #
# clustered bootstrap
# --------------------------------------------------------------------------- #
def test_expiry_cycle_is_the_monthly_expiry_containing_the_exit() -> None:
    tr = _trade("SPY", date(2024, 3, 1), date(2024, 3, 12), 0.4)
    assert expiry_cycle_of(tr) == EXPIRIES[0] == date(2024, 3, 15)
    late = _trade("SPY", date(2024, 3, 20), date(2024, 4, 2), 0.4)
    assert expiry_cycle_of(late) == date(2024, 4, 19)


def test_cluster_key_is_underlying_and_cycle_and_f11_is_cycle_only() -> None:
    spy = _trade("SPY", date(2024, 3, 1), date(2024, 3, 12), 0.4)
    qqq = _trade("QQQ", date(2024, 3, 1), date(2024, 3, 12), 0.4)
    assert cluster_key_underlying_cycle(spy) != cluster_key_underlying_cycle(qqq)
    # F11 pools across underlyings: one cycle, one cluster, regardless of symbol.
    assert cluster_key_cycle_only(spy) == cluster_key_cycle_only(qqq)


def test_clustered_bootstrap_is_deterministic_and_seed_sensitive() -> None:
    trades = [
        _trade("SPY", date(2024, 3, 1), date(2024, 3, 12), 0.5),
        _trade("SPY", date(2024, 3, 4), date(2024, 3, 13), -0.2),
        _trade("QQQ", date(2024, 3, 1), date(2024, 3, 12), 0.3),
        _trade("SPY", date(2024, 3, 20), date(2024, 4, 10), 0.1),
    ]
    a = clustered_bootstrap_ci(trades)
    b = clustered_bootstrap_ci(trades)
    assert (a.low, a.high, a.point) == (b.low, b.high, b.point)
    assert a.seed == OPTIONS_CLUSTER_BOOTSTRAP_SEED
    assert a.unit == CLUSTER_UNIT_D4
    # A seed IS a choice, so a different one must be able to move the interval.
    # Three clusters resample to too few distinct means for that to show, so the
    # check runs on a population with enough clusters to have a distribution.
    wide = [
        _trade("SPY", date(2024, 3, 1) + timedelta(days=31 * i), _exit(i), 0.1 * ((i % 7) - 3))
        for i in range(24)
    ]
    a_wide = clustered_bootstrap_ci(wide)
    other = clustered_bootstrap_ci(wide, seed=1234567)
    assert (other.low, other.high) != (a_wide.low, a_wide.high)
    # the point estimate is the population mean and does NOT move with the seed
    assert other.point == pytest.approx(a_wide.point)


def test_clustered_bootstrap_respects_cluster_boundaries() -> None:
    """Three (underlying, cycle) clusters, and the F11 unit collapses two of them."""
    trades = [
        _trade("SPY", date(2024, 3, 1), date(2024, 3, 12), 0.5),
        _trade("SPY", date(2024, 3, 4), date(2024, 3, 13), 0.4),
        _trade("QQQ", date(2024, 3, 1), date(2024, 3, 12), 0.3),
        _trade("SPY", date(2024, 3, 20), date(2024, 4, 10), 0.1),
    ]
    d4 = clustered_bootstrap_ci(trades, key_fn=cluster_key_underlying_cycle)
    f11 = clustered_bootstrap_ci(trades, key_fn=cluster_key_cycle_only)
    assert d4.n_clusters == 3
    assert f11.n_clusters == 2  # the March cycle now holds SPY *and* QQQ
    assert d4.n_trades == f11.n_trades == 4
    assert d4.mean_cluster_size == pytest.approx(4 / 3)
    assert f11.mean_cluster_size == pytest.approx(2.0)


def test_one_cluster_gives_a_degenerate_interval() -> None:
    """Every resample draws the same single cluster, so the CI cannot be narrower
    than the point — which is the honest statement that n_clusters = 1 carries no
    information about between-cluster variance."""
    trades = [
        _trade("SPY", date(2024, 3, 1), date(2024, 3, 12), 0.5),
        _trade("SPY", date(2024, 3, 4), date(2024, 3, 13), -0.5),
    ]
    res = clustered_bootstrap_ci(trades)
    assert res.n_clusters == 1
    assert res.low == pytest.approx(res.point) == pytest.approx(res.high)


def test_clustered_ci_is_wider_than_the_iid_one_on_correlated_clusters() -> None:
    """The whole reason the unit exists: within-cluster agreement inflates the
    interval the iid resample would report."""
    from signalforge.backtest.montecarlo import bootstrap_ci

    trades: list[OptionTrade] = []
    for c, (entry, exit_) in enumerate(
        [(date(2024, 3, 1), date(2024, 3, 12)), (date(2024, 3, 20), date(2024, 4, 10))]
    ):
        for i in range(10):
            trades.append(_trade(f"S{i}", entry, exit_, 1.0 if c == 0 else -0.5))
    clustered = clustered_bootstrap_ci(trades, key_fn=cluster_key_cycle_only)
    iid = bootstrap_ci([t.pnl_r for t in trades])
    assert clustered.n_clusters == 2
    assert clustered.high - clustered.low > iid["expectancy_r"]["high"] - iid["expectancy_r"]["low"]
    assert clustered.rho > 0.5
    assert clustered.deff > 1.0


def test_empty_population_is_a_zero_interval_not_a_crash() -> None:
    res = clustered_bootstrap_ci([])
    assert (res.n_clusters, res.n_trades, res.low, res.high, res.deff) == (0, 0, 0.0, 0.0, 1.0)


# --------------------------------------------------------------------------- #
# coverage / pre-registration refusals
# --------------------------------------------------------------------------- #
def test_coverage_preflight_refuses_without_a_backfill_run() -> None:
    pre = coverage_preflight(None)
    assert not pre.passed
    assert "no options cycle-backfill run" in pre.reasons[0]


def test_coverage_preflight_binds_on_both_floors(session: Session) -> None:
    run = seed_coverage_run(
        session, ["SPY"], cycles_total=10, cycles_covered=5, bars_written=100, sessions_expected=100
    )
    session.commit()
    pre = coverage_preflight(coverage_summary(run))
    assert not pre.passed
    assert any("cycle bracketing" in r for r in pre.reasons)

    good = seed_coverage_run(
        session,
        ["QQQ"],
        cycles_total=10,
        cycles_covered=10,
        bars_written=40,
        sessions_expected=40,
    )
    session.commit()
    assert coverage_preflight(coverage_summary(good)).passed


def test_latest_coverage_summary_reads_the_newest_run(session: Session) -> None:
    seed_coverage_run(session, ["SPY"])
    session.commit()
    summary = latest_options_coverage_summary(session)
    assert summary is not None and summary.underlyings == ("SPY",)
    # counts-only, mechanically
    summary.assert_price_free()


def test_preregistration_digest_is_empty_when_the_file_is_missing(tmp_path) -> None:  # type: ignore[no-untyped-def]
    assert preregistration_digest(tmp_path) == ""
    assert preregistration_digest().startswith("D5@")
    assert preregistration_path().is_file()


# --------------------------------------------------------------------------- #
# the assembler
# --------------------------------------------------------------------------- #
def test_chain_loader_builds_a_series_indexed_by_the_underlying(session: Session) -> None:
    seed_everything(session)
    w = window()
    chain = load_option_chain_series(session, "SPY", start=w.start, end=w.end, source=SOURCE)
    assert chain is not None
    assert chain.underlying == "SPY"
    assert len(chain) > 50
    # every contract carries real reference metadata, never a default
    assert all(c.shares_per_contract == 100 for c in chain.contracts.values())
    assert {c.expiration for c in chain.contracts.values()} == set(EXPIRIES)


def test_chain_loader_returns_none_without_rows(session: Session) -> None:
    w = window()
    assert (
        load_option_chain_series(session, "NOPE", start=w.start, end=w.end, source=SOURCE) is None
    )


def test_assembler_produces_a_complete_evidence_bundle(session: Session) -> None:
    snap, _ = seed_everything(session)
    strat = StubOptionsStrategy()
    assembled = assemble(
        session, strat, dataset_snapshot=snap, window=window(), source=SOURCE, proxy_symbol="SPY"
    )
    ev = assembled.evidence

    # shape: every field the ladder reads is populated by a measurement
    assert ev.availability.required_source == SOURCE
    assert {u.symbol for u in ev.availability.underlyings} == {"SPY", "QQQ"}
    assert ev.availability.fill_model
    assert ev.availability.cost_model_frozen_at.startswith("D5@")
    assert ev.identity.structure_type is StructureType.VERTICAL_CREDIT
    assert len(ev.folds) == 4
    assert ev.census.n_trades >= 0
    assert ev.partition.sessions > 0
    assert ev.benchmark.proxy_symbol == "SPY"
    assert ev.data_quality.clustering_unit == CLUSTER_UNIT_D4
    assert "low" in ev.data_quality.clustered_bootstrap_ci
    assert "f11_low" in ev.data_quality.clustered_bootstrap_ci
    assert ev.data_quality.clustered_bootstrap_ci["seed"] == float(OPTIONS_CLUSTER_BOOTSTRAP_SEED)
    assert ev.stressed_oos is not None

    # the population is real: the engine ran and produced structures
    assert len(ev.dual.baseline.trades) > 0
    assert {t.underlying_symbol for t in ev.dual.baseline.trades} == {"SPY", "QQQ"}
    # form (a): the stressed leg re-prices the SAME structures
    assert len(ev.dual.stressed.trades) == len(ev.dual.baseline.trades)
    assert ev.dual.binding_cell.spread_multiplier == 2.0

    # gate 5 is None because no grid was run — an honest failure, not a skip
    assert ev.sensitivity is None
    # the sealed year was not requested, so nothing can be sealed
    assert ev.sealed is None
    assert ev.extra_provenance["sealed_window_evaluated"] is False


def test_assembler_never_writes_a_row(session: Session) -> None:
    """A read-only assembly: no evaluation, no sealed test, and no validation row
    (``validate_daily`` is called with ``persist=False``)."""
    snap, _ = seed_everything(session)
    before = (
        session.scalar(select(func.count()).select_from(StrategyPromotionEvaluation)),
        session.scalar(select(func.count()).select_from(StrategySealedTest)),
        session.scalar(select(func.count()).select_from(DataValidationReport)),
    )
    assemble(
        session,
        StubOptionsStrategy(),
        dataset_snapshot=snap,
        window=window(),
        source=SOURCE,
        proxy_symbol="SPY",
    )
    session.commit()
    after = (
        session.scalar(select(func.count()).select_from(StrategyPromotionEvaluation)),
        session.scalar(select(func.count()).select_from(StrategySealedTest)),
        session.scalar(select(func.count()).select_from(DataValidationReport)),
    )
    assert before == after == (0, 0, 0)


def test_assembler_on_an_empty_snapshot_fails_gate_zero_rather_than_crashing(
    session: Session,
) -> None:
    snap = seed_snapshot(session, [], key="empty_options_snapshot")
    session.commit()
    assembled = assemble(
        session,
        StubOptionsStrategy(),
        dataset_snapshot=snap,
        window=window(),
        source=SOURCE,
        proxy_symbol="SPY",
    )
    gates = options_ladder_preview(assembled.evidence, window=window())
    # fail-fast: gate 0 returns on the first failure and nothing beyond it runs
    assert all(g.number == 0 for g in gates)
    assert not all(g.passed for g in gates)
    labels = tuple((g.number, g.label) for g in gates)
    assert labels == OPTIONS_LADDER_SHAPE[: len(labels)]
    assert any("no underlying passed coverage" in g.detail for g in gates)


def test_sealed_outcome_only_appears_when_asked_for(session: Session) -> None:
    snap, _ = seed_everything(session)
    strat = StubOptionsStrategy()
    w = window(sealed_days=120)  # wide enough that a structure lands inside it
    without = assemble(
        session, strat, dataset_snapshot=snap, window=w, source=SOURCE, proxy_symbol="SPY"
    )
    assert without.evidence.sealed is None
    with_sealed = assemble(
        session,
        strat,
        dataset_snapshot=snap,
        window=w,
        source=SOURCE,
        proxy_symbol="SPY",
        include_sealed=True,
    )
    assert with_sealed.evidence.sealed is not None
    # the sealed path is pinned to the BASELINE cost model, structurally
    assert with_sealed.evidence.sealed.spread_multiplier == 1.0


def test_pooling_keeps_every_trade_and_sums_the_counters(session: Session) -> None:
    from signalforge.research.options_evidence import pool_dual, run_underlying

    seed_everything(session)
    w = window()
    strat = StubOptionsStrategy()
    runs = [
        run_underlying(session, strat, s, window=w, source=SOURCE, dte_targets=[35])
        for s in ("SPY", "QQQ")
    ]
    duals = [r.dual for r in runs if r.dual is not None]
    assert len(duals) == 2
    pooled = pool_dual(duals)
    assert len(pooled.baseline.trades) == sum(len(d.baseline.trades) for d in duals)
    assert pooled.baseline.counters.held_sessions == sum(
        d.baseline.counters.held_sessions for d in duals
    )
    assert set(pooled.cells) == {"at_print@1x", "incl@1x", "at_print@2x", "incl@2x"}


# --------------------------------------------------------------------------- #
# dry run vs confirm — the look accounting
# --------------------------------------------------------------------------- #
def test_dry_run_preview_consumes_no_look(session: Session) -> None:
    from tests.research.options_gate_support import WINDOW, options_snapshot, passing_evidence

    options_snapshot(session)
    session.commit()
    gates = options_ladder_preview(passing_evidence(), window=WINDOW)
    assert [g.number for g in gates][-1] == 10
    gate9 = next(g for g in gates if g.number == 9)
    assert "DRY RUN — no sealed test was read, created or consumed" in gate9.detail
    assert gate9.evidence["sealed_test_id"] is None
    assert gate9.evidence["sealed_look_ledger"]["preview"] is True
    assert session.scalar(select(func.count()).select_from(StrategySealedTest)) == 0
    assert session.scalar(select(func.count()).select_from(StrategyPromotionEvaluation)) == 0


def test_confirm_consumes_exactly_one_look(session: Session) -> None:
    from signalforge.research.options_promotion import evaluate_options_promotion
    from signalforge.research.options_strategies import default_options_strategies
    from tests.research.options_gate_support import (
        SYMBOLS,
        WINDOW,
        options_snapshot,
        passing_evidence,
    )

    snap = options_snapshot(session)
    spec = default_options_strategies()[0].spec()
    evidence = passing_evidence()
    for _ in range(2):
        evaluate_options_promotion(
            session,
            spec,
            symbols=list(SYMBOLS),
            window=WINDOW,
            dataset_snapshot=snap,
            evidence=evidence,
        )
    session.commit()
    # two evaluations, ONE sealed test: the (version, snapshot) pair is the key
    assert session.scalar(select(func.count()).select_from(StrategySealedTest)) == 1
    assert session.scalar(select(func.count()).select_from(StrategyPromotionEvaluation)) == 2


def test_ladder_preview_matches_the_declared_ladder_shape() -> None:
    from tests.research.options_gate_support import WINDOW, passing_evidence

    gates = options_ladder_preview(passing_evidence(), window=WINDOW)
    assert tuple((g.number, g.label) for g in gates) == OPTIONS_LADDER_SHAPE


def test_stub_strategy_side_selection_is_not_read_by_the_assembler(session: Session) -> None:
    """The mechanical benchmark runs the SAME structure with the signal removed —
    gate 7b's whole question — and the assembler records both Sharpes."""
    snap, _ = seed_everything(session)
    assembled = assemble(
        session,
        StubOptionsStrategy(),
        dataset_snapshot=snap,
        window=window(),
        source=SOURCE,
        proxy_symbol="SPY",
    )
    assert assembled.evidence.benchmark.mechanical_sharpe_baseline is not None
    assert assembled.evidence.benchmark.mechanical_spec["regime_filter"] == "REMOVED"


def test_assembled_provenance_records_the_seed_and_the_two_units(session: Session) -> None:
    snap, _ = seed_everything(session)
    assembled = assemble(
        session,
        StubOptionsStrategy(),
        dataset_snapshot=snap,
        window=window(),
        source=SOURCE,
        proxy_symbol="SPY",
    )
    prov = assembled.provenance()
    assert prov["clustered_bootstrap"]["seed"] == OPTIONS_CLUSTER_BOOTSTRAP_SEED
    assert prov["clustered_bootstrap"]["d4_unit"] != prov["clustered_bootstrap"]["f11_unit"]
    assert prov["coverage_run_id"] is not None
    assert [u["symbol"] for u in prov["underlyings"]] == ["SPY", "QQQ"]


def test_replace_on_the_stub_does_not_change_the_protocol_surface() -> None:
    """Guards the Protocol: a strategy is anything with these members."""
    strat = replace(StubOptionsStrategy(), dte_target=21)
    assert strat.dte_target == 21
    assert callable(strat.sensitivity_axes) and callable(strat.oat_parameters)
