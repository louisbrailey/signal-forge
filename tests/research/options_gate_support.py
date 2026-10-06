"""A fully-PASSING synthetic options evidence bundle, so a test can break one thing.

Every number here is invented to make the ladder pass; **no real chain, no real
price, no real IV and no real P&L is read anywhere** (R1: I-O4 wires the ladder,
it does not run an evaluation).  The one exception is the ``DualSpreadReport``,
which is produced by running the real engine over the synthetic chain of
``tests/options_chain_support.py`` — because a gate that reads engine counters
should be tested against counters the engine actually produced.
"""

from __future__ import annotations

from datetime import date, timedelta

from signalforge.backtest.options_engine import RBasis, StructureType
from signalforge.db.models import DataSnapshot
from signalforge.domain import Horizon
from signalforge.research.options_backtest_runner import (
    DualSpreadReport,
    JointRegimeCensus,
    RegimePartitionDisclosure,
    run_dual_spread,
)
from signalforge.research.options_gates import (
    BenchmarkPair,
    OptionsDataAvailability,
    OptionsDataQuality,
    OptionsSensitivitySummary,
    OptionsWindow,
    SealedOptionsOutcome,
    StressedOos,
    StructureIdentity,
    UnderlyingCoverage,
)
from signalforge.research.options_promotion import OptionsEvidence
from tests.options_chain_support import (
    LONG_STRIKE,
    LONG_TICKER,
    SHORT_STRIKE,
    SHORT_TICKER,
    build_fixture,
    put_contract,
    sessions_between,
    signal_at,
    worked_example_cost_model,
)

FIRST = date(2024, 2, 1)
LAST = date(2024, 3, 20)
FORCE_CLOSE = date(2024, 3, 14)

END = date(2024, 12, 31)
SEALED_START = END - timedelta(days=365)
WINDOW = OptionsWindow(
    start=SEALED_START - timedelta(days=400),
    pre_sealed_end=SEALED_START - timedelta(days=1),
    sealed_start=SEALED_START,
    end=END,
)
SYMBOLS = ["SPY"]


def _signal_fn(chain, underlying, t):
    return signal_at(t) if t == 0 else None


def dual_report(*, short_fc: float = 0.02, long_fc: float = 0.01, under_fc: float = 505.0):
    """One profitable synthetic cycle, priced at both spread settings."""
    dates = sessions_between(FIRST, LAST)
    shorts = dict.fromkeys(dates, 2.0) | {FORCE_CLOSE: short_fc}
    longs = dict.fromkeys(dates, 0.9) | {FORCE_CLOSE: long_fc}
    unders = dict.fromkeys(dates, 505.0) | {FORCE_CLOSE: under_fc}
    fx = build_fixture(
        dates,
        unders,
        {SHORT_TICKER: shorts, LONG_TICKER: longs},
        [
            put_contract(SHORT_TICKER, SHORT_STRIKE, dates[0]),
            put_contract(LONG_TICKER, LONG_STRIKE, dates[0]),
        ],
    )
    return run_dual_spread(
        fx.chain,
        fx.underlying,
        _signal_fn,
        baseline=worked_example_cost_model(),
        stressed=worked_example_cost_model(spread_multiplier=2.0),
        warmup=0,
    )


def availability(**overrides) -> OptionsDataAvailability:
    base: dict[str, object] = {
        "horizon": Horizon.MEDIUM_SWING,
        "min_dte_at_entry_declared": 7,
        "underlyings": (
            UnderlyingCoverage(
                "SPY", "massive", WINDOW.start, WINDOW.end, 0, option_source="massive_options"
            ),
        ),
        "required_source": "massive",
        "required_option_source": "massive_options",
        "cycles_eligible": 100,
        "cycles_bracketed": 95,
        "bracket_fraction_matrix": {
            "21": {"put": 0.95, "call": 0.94},
            "35": {"put": 0.96, "call": 0.93},
        },
        "bracket_gated_cells": ((21, "put"), (21, "call"), (35, "put"), (35, "call")),
        "eligible_cycle_definition": (
            "(i) the underlying passes 0.b over that cycle, and (ii) the cycle's expiry falls "
            "inside the evaluation window. Nothing else."
        ),
        "bracket_failures_by_underlying": {"SPY": 5},
        "bracket_failures_by_side": {"put": 2, "call": 3},
        "bar_continuity_min_observed": 0.92,
        "bar_continuity_median": 0.97,
        "non_entry_count": 4,
        "non_entry_reasons": {"missing_leg_bar": 3, "credit_floor": 1},
        "exit_deferral_histogram": {"0": 90, "1": 5},
        "gap_sessions": 0,
        "iv_source_mix": {"local_bs_inverted": 0.9, "same_session_surface": 0.1},
        "iv_source_unnamed_count": 0,
        "surface_n_actual_min": 6,
        "fill_model": "print_not_mid; full_modelled_spread_per_leg_per_side; close_basis_stop",
        "cost_model": worked_example_cost_model(),
        "cost_model_frozen_at": "d5-commit-sha",
        "cost_per_structure_roundtrip_usd": {"1.0": 18.90, "2.0": 34.60},
        "entitlement_batches_checked": 7,
        "q_by_underlying": {
            "SPY": {"value": 0.013, "source": "vendor_dividends", "as_of": "2024-12-31"}
        },
        "q_defaulted_count": 0,
        "deliverable_refusal_count": 0,
        "deliverable_refusals": (),
        "r_max_observed_usd": 225.0,
        "r_max_by_width": {"3": 225.0},
        "concurrent_open_r_max_usd": 900.0,
        "structures_breaching_per_structure_cap": 0,
        "width_grid_declared": (3.0,),
        "limits_source": "D5 §9.2 / decisions #4 and #13",
        "limits_in_options_config_hash": True,
    }
    base.update(overrides)
    return OptionsDataAvailability(**base)


def identity(dual: DualSpreadReport) -> StructureIdentity:
    """The declared identity that MATCHES the synthetic trades' realised R scale."""
    trade = dual.baseline.trades[0]
    scale = trade.r_at_print + trade.net_credit_at_print  # width x M x C
    return StructureIdentity(
        structure_type=StructureType.VERTICAL_CREDIT,
        r_basis_formula="R = strike_width x M x contracts - net_credit_received + entry_costs",
        legs_per_structure=2,
        leg_sign_pattern=(-1, +1),
        width_declared=scale / 100.0,
        m_declared=100,
        width_selected_adaptively=False,
    )


def census(**overrides) -> JointRegimeCensus:
    base: dict[str, object] = {
        "regime_label_source": "signalforge.backtest.regime:label_regimes",
        "trend_buckets": {"bull": 40, "bear": 30, "range": 20},
        "joint_cells": {
            "bull_highvol": 20,
            "bull_lowvol": 20,
            "bear_highvol": 22,
            "bear_lowvol": 8,
        },
        "vol_marginals": {"highvol": 42, "lowvol": 28},
        "range_bound_count": 20,
        "range_bound_vol_labelled": False,
        "warmup": 0,
        "no_proxy_bar": 0,
        "unlabelled": 0,
        "n_trades": 90,
    }
    base.update(overrides)
    return JointRegimeCensus(**base)


def partition(**overrides) -> RegimePartitionDisclosure:
    base: dict[str, object] = {
        "signal_label_source": "signalforge.research.regime:regime_from_proxy",
        "census_label_source": "signalforge.backtest.regime:label_regimes",
        "crosstab": {"bear": {"bear_highvol": 80, "range_bound": 20}, "bull": {"bull_lowvol": 400}},
        "bear_sessions_signal": 100,
        "bear_sessions_called_range": 20,
        "sessions": 500,
    }
    base.update(overrides)
    return RegimePartitionDisclosure(**base)


def benchmark(**overrides) -> BenchmarkPair:
    base: dict[str, object] = {
        "strategy_sharpe_baseline": 1.20,
        "strategy_sharpe_stressed": 0.95,
        "market_sharpe": 0.70,
        "mechanical_sharpe_baseline": 0.80,
        "mechanical_sharpe_stressed": 0.60,
        "mechanical_n_trades": 95,
        "mechanical_spec": {"regime_filter": "REMOVED — always the put side"},
        "eff_start": WINDOW.start,
        "eff_end": WINDOW.pre_sealed_end,
    }
    base.update(overrides)
    return BenchmarkPair(**base)


def data_quality(**overrides) -> OptionsDataQuality:
    base: dict[str, object] = {
        "data_validation_passed": True,
        "data_validation_findings": (),
        "leakage_error": None,
        "chain_leakage_error": None,
        "corporate_action_exclusions": {},
        "synthetic_mark_fraction_trade_weighted": 0.02,
        "pinned_fraction": 0.04,
        "expectancy_excluding_pinned_r": 0.18,
        "pinned_r_distribution": {"min": -1.0, "median": 0.1, "max": 0.3},
        "clustered_bootstrap_ci": {"low": 0.05, "high": 0.30, "deff": 1.8, "rho": 0.2},
    }
    base.update(overrides)
    return OptionsDataQuality(**base)


def sensitivity(**overrides) -> OptionsSensitivitySummary:
    base: dict[str, object] = {
        "n_points": 96,
        "n_evaluable": 80,
        "positive_fraction": 0.82,
        "neighbour_positive_fraction": 0.86,
        "fragile": False,
        "axes": (
            "short_delta_target",
            "max_short_delta",
            "width_pct",
            "dte_target",
            "profit_target_pct",
            "min_credit_to_width",
        ),
    }
    base.update(overrides)
    return OptionsSensitivitySummary(**base)


def sealed(**overrides) -> SealedOptionsOutcome:
    base: dict[str, object] = {
        "window_start": SEALED_START,
        "window_end": END,
        "n_trades": 24,
        "expectancy_r": 0.14,
        "spread_multiplier": 1.0,
        "r_basis": RBasis.INCL,
        "metrics": {"sharpe": 0.9},
        "benchmark": {"sharpe": 0.7},
        "data_provenance": {"sources": ["massive"], "simulated": False},
    }
    base.update(overrides)
    return SealedOptionsOutcome(**base)


def folds() -> list[dict[str, object]]:
    return [{"fold": i + 1, "n_trades": 30, "expectancy_r": 0.15, "sharpe": 0.9} for i in range(4)]


def passing_evidence(**overrides) -> OptionsEvidence:
    dual = overrides.pop("dual", None) or dual_report()
    base: dict[str, object] = {
        "availability": availability(),
        "identity": identity(dual),
        "dual": dual,
        "census": census(),
        "partition": partition(),
        "benchmark": benchmark(),
        "data_quality": data_quality(),
        "folds": folds(),
        "sensitivity": sensitivity(),
        "sealed": sealed(),
        "n_oos_trades": 90,
        "oos_expectancy_r": 0.17,
        "oos_ci_low_r": 0.06,
        # Selection is frozen at the baseline cost model, so the stressed leg
        # re-prices the SAME 90 structures (D5 §6.2c form (a)).
        "stressed_oos": StressedOos(n_trades=90, expectancy_r=0.11, ci_low_r=0.035),
    }
    base.update(overrides)
    return OptionsEvidence(dual=dual, **{k: v for k, v in base.items() if k != "dual"})


def options_snapshot(session, key: str = "options_test_snapshot") -> DataSnapshot:
    """An options-SCOPED snapshot, resolved by key so repeated calls reuse it.

    ``DataSnapshot`` is unique on ``key`` and immutable once created, so a test
    that evaluates twice must land on the same row — which is also what makes the
    locked-replay path reachable at all.
    """
    from sqlalchemy import select as _select

    existing = session.scalar(_select(DataSnapshot).where(DataSnapshot.key == key))
    if existing is not None:
        return existing
    snap = DataSnapshot(
        key=key,
        symbols_json=list(SYMBOLS),
        description="synthetic options snapshot (test)",
        source_note="SIMULATED",
        options_scope_json={
            "schema_version": 1,
            "underlyings": SYMBOLS,
            "options_config_hash": "x",
        },
    )
    session.add(snap)
    session.flush()
    return snap


def equity_snapshot(session, key: str = "equity_test_snapshot") -> DataSnapshot:
    from sqlalchemy import select as _select

    existing = session.scalar(_select(DataSnapshot).where(DataSnapshot.key == key))
    if existing is not None:
        return existing
    snap = DataSnapshot(
        key=key,
        symbols_json=list(SYMBOLS),
        description="equity snapshot with NO options scope (test)",
        source_note="SIMULATED",
    )
    session.add(snap)
    session.flush()
    return snap


__all__ = [
    "END",
    "SEALED_START",
    "SYMBOLS",
    "WINDOW",
    "availability",
    "benchmark",
    "census",
    "data_quality",
    "dual_report",
    "equity_snapshot",
    "folds",
    "identity",
    "options_snapshot",
    "partition",
    "passing_evidence",
    "sealed",
    "sensitivity",
]
