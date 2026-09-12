"""The options gate ladder (I-O4, D4).

The load-bearing test in this file is the last one: the equity ladder's
``gates_json`` must be **byte-identical** across this work.  Everything else
tests a rung.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge.data.adapters.fixture import FixtureMarketDataAdapter
from signalforge.data.ingest import ingest_universe
from signalforge.db.models import Strategy, StrategySealedTest, StrategyVersion
from signalforge.domain import Horizon, StrategyStatus
from signalforge.research.options_gates import (
    OPTIONS_LADDER_SHAPE,
    OptionsGate,
    OptionsGateThresholds,
    SealedAtNonBaselineCost,
)
from signalforge.research.options_promotion import (
    OPTIONS_FAMILY_NAMES,
    OPTIONS_LOOK_BUDGET,
    OptionsSnapshotNotScoped,
    evaluate_options_promotion,
    options_disposition_record,
    options_program_looks,
)
from signalforge.research.options_strategies import OptionsShortVertical
from signalforge.research.promotion import Gate, count_sealed_looks, evaluate_promotion
from signalforge.research.strategies import MeanReversion, TrendContinuation
from signalforge.settings_store import effective_research_config
from tests.research import options_gate_support as sup

SPEC = OptionsShortVertical().spec()


def _run(session: Session, evidence, **kwargs):
    return evaluate_options_promotion(
        session,
        SPEC,
        symbols=sup.SYMBOLS,
        window=sup.WINDOW,
        dataset_snapshot=kwargs.pop("snapshot", None) or sup.options_snapshot(session),
        evidence=evidence,
        **kwargs,
    )


def _gate(result, gate_id: str) -> OptionsGate:
    return next(g for g in result.gates if g.gate_id == gate_id)


# --------------------------------------------------------------------------- #
# ladder shape and gate identity
# --------------------------------------------------------------------------- #
def test_the_ladder_shape_is_asserted_on_ordered_number_label_pairs(session: Session) -> None:
    """D4 §1: the shape is a contract, re-specified deliberately and never deleted."""
    result = _run(session, sup.passing_evidence())
    assert result.ladder_shape == OPTIONS_LADDER_SHAPE
    assert len(result.gates) == 23
    # 0.5, 4b, 6b and 7b are expressible at all only because `label` exists.
    assert [g.gate_id for g in result.gates if g.label][:4] == ["0.a", "0.b", "0.c", "0.d"]
    assert {"0.5", "4b", "6b", "7b"} <= {g.gate_id for g in result.gates}


def test_a_sub_gate_carries_its_parents_integer_so_the_visual_link_survives(
    session: Session,
) -> None:
    result = _run(session, sup.passing_evidence())
    assert _gate(result, "4b").number == 4
    assert _gate(result, "6b").number == 6
    assert _gate(result, "7b").number == 7
    assert _gate(result, "0.5").number == 0


def test_the_passing_bundle_actually_passes_so_a_failure_below_means_something(
    session: Session,
) -> None:
    result = _run(session, sup.passing_evidence())
    assert result.passed, [g.gate_id for g in result.gates if not g.passed]
    assert result.verdict == "PAPER_APPROVED"


# --------------------------------------------------------------------------- #
# gate 0 is FAIL-FAST
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("gate_id", "override"),
    [
        ("0.a", {"horizon": Horizon.INTRADAY}),
        ("0.a", {"min_dte_at_entry_declared": 0}),
        ("0.b", {"required_source": "massive", "underlyings": ()}),
        ("0.c", {"cycles_bracketed": 50}),
        ("0.d", {"bar_continuity_min_observed": 0.55}),
        ("0.e", {"iv_source_unnamed_count": 3}),
        ("0.e", {"iv_source_mix": {"local_bs_inverted": 0.8, "pct_otm_proxy": 0.2}}),
        ("0.f", {"cost_model_frozen_at": ""}),
        ("0.g", {"q_defaulted_count": 1}),
        ("0.h", {"deliverable_refusal_count": 2}),
        ("0.i", {"r_max_observed_usd": 600.0}),
        ("0.i", {"limits_in_options_config_hash": False}),
    ],
)
def test_each_gate_0_subcheck_fails_fast_and_nothing_after_it_runs(
    session: Session, gate_id: str, override: dict
) -> None:
    """The precedent is ``promotion.py``'s INTRADAY branch: one failing Gate(0, ...)
    and an immediate return, never a fabricated pass on absent data."""
    evidence = sup.passing_evidence(availability=sup.availability(**override))
    result = _run(session, evidence)
    assert not result.passed
    assert not _gate(result, gate_id).passed
    # gate 0 is fail-fast: only 0.a-0.i and 0.5 were even evaluated
    assert result.ladder_shape == OPTIONS_LADDER_SHAPE[:10]
    assert all(g.number == 0 for g in result.gates)
    assert result.sealed_test_id is None


def test_a_failed_gate_0_takes_no_sealed_look(session: Session) -> None:
    """A pre-sealed diagnostic must leave ``count_sealed_looks`` UNCHANGED."""
    evidence = sup.passing_evidence(availability=sup.availability(cycles_bracketed=10))
    before = count_sealed_looks(session, SPEC.name)
    _run(session, evidence)
    assert count_sealed_looks(session, SPEC.name) == before == 0


def test_the_bracket_floor_binds_per_declared_cell_not_only_on_the_aggregate(
    session: Session,
) -> None:
    """D4 §2.3: the fraction is a MATRIX; a healthy aggregate must not hide a
    gated ``(dte, side)`` cell that the strategy's own grid will run through."""
    av = sup.availability(
        cycles_eligible=100,
        cycles_bracketed=99,
        bracket_fraction_matrix={
            "21": {"put": 0.99, "call": 0.99},
            "35": {"put": 0.99, "call": 0.40},  # the cell that matters
        },
    )
    result = _run(session, sup.passing_evidence(availability=av))
    g = _gate(result, "0.c")
    assert not g.passed
    assert g.evidence["bracket_fraction"] >= 0.90  # the aggregate alone would have passed
    assert g.evidence["bracket_fraction_failing_cells"] == ["35/call=0.400"]


def test_gate_0d_records_that_no_synthetic_fill_field_can_exist(session: Session) -> None:
    result = _run(session, sup.passing_evidence())
    g = _gate(result, "0.d")
    assert g.evidence["synthetic_fill_fraction"] is None
    assert "forbids synthetic fills" in g.evidence["synthetic_fill_note"]


def test_gate_0g_distinguishes_a_sourced_zero_q_from_a_defaulted_one(session: Session) -> None:
    sourced_zero = sup.availability(
        q_by_underlying={"SPY": {"value": 0.0, "source": "vendor_dividends", "as_of": "2024-12-31"}}
    )
    assert _gate(_run(session, sup.passing_evidence(availability=sourced_zero)), "0.g").passed

    unsourced = sup.availability(q_by_underlying={"SPY": {"value": 0.0, "source": ""}})
    assert not _gate(_run(session, sup.passing_evidence(availability=unsourced)), "0.g").passed


def test_gate_0f_emits_every_option_cost_model_field_with_no_default_elided(
    session: Session,
) -> None:
    """D4 §2.6's correction: the commissions and fees are the biggest single lever
    on gates 3 and 4, and revision 1 recorded only the two spread constants."""
    model = _gate(_run(session, sup.passing_evidence()), "0.f").evidence["option_cost_model"]
    assert set(model) == {
        "commission_per_contract",
        "commission_min_per_order",
        "exchange_fee_per_contract",
        "spread_pct_of_last_print",
        "spread_abs_floor_cents",
        "tick_grid",
        "assignment_fee",
        "exercise_fee",
        "spread_multiplier",
    }


def test_gate_0i_refuses_a_population_the_arming_limits_would_refuse(session: Session) -> None:
    """D4 §2.8a: the ladder must not certify an R stream gate 10 can never reproduce."""
    av = sup.availability(r_max_observed_usd=375.0, structures_breaching_per_structure_cap=12)
    g = _gate(_run(session, sup.passing_evidence(availability=av)), "0.i")
    assert not g.passed
    assert g.evidence["options_per_structure_max_loss"] == 250.0
    assert g.evidence["account_equity_basis"] == 25_000.0


# --------------------------------------------------------------------------- #
# gate 0.5
# --------------------------------------------------------------------------- #
def test_gate_0_5_refuses_an_adaptively_selected_width(session: Session) -> None:
    dual = sup.dual_report()
    ident = replace(sup.identity(dual), width_selected_adaptively=True)
    g = _gate(_run(session, sup.passing_evidence(dual=dual, identity=ident)), "0.5")
    assert not g.passed
    assert "no fixed scale" in g.detail


def test_gate_0_5_refuses_a_declared_r_scale_the_trades_do_not_match(session: Session) -> None:
    """Clause (d): a 3-wide and a 10-wide differ 3.3x in dollars at risk, and
    ``bootstrap_ci`` — a bare ``Sequence[float]`` — cannot see the difference."""
    dual = sup.dual_report()
    ident = replace(sup.identity(dual), width_declared=10.0)
    g = _gate(_run(session, sup.passing_evidence(dual=dual, identity=ident)), "0.5")
    assert not g.passed
    assert g.evidence["r_scale_usd"] == 1000.0
    assert "may not be pooled" in g.evidence["incomparability_notice"]


def test_gate_0_5_reports_the_structure_type_and_the_r_basis_formula(session: Session) -> None:
    g = _gate(_run(session, sup.passing_evidence()), "0.5")
    assert g.evidence["structure_type"] == "vertical_credit"
    assert g.evidence["structure_types_observed"] == ["vertical_credit"]
    assert "strike_width" in g.evidence["r_basis_formula"]
    assert g.evidence["m_declared"] == 100


# --------------------------------------------------------------------------- #
# gate 4b
# --------------------------------------------------------------------------- #
def test_gate_4b_gates_2_3_4_and_7_and_7b_at_the_stressed_setting(session: Session) -> None:
    g = _gate(_run(session, sup.passing_evidence()), "4b")
    assert g.evidence["gated_at_stressed"] == ["2", "3", "4", "7", "7b"]
    assert g.evidence["spread_multiple_stressed"] == 2.0
    assert g.evidence["applied_to"] == "options"


def test_gate_4b_fails_when_gate_7_survives_baseline_but_not_the_cost_stress(
    session: Session,
) -> None:
    """D4 §4.1's revision-3 correction.  The market benchmark is computed from raw
    proxy closes and pays no cost, so the stress moves only one side — which is
    exactly why gate 7 must be gated at 2x rather than merely reported there."""
    bench = sup.benchmark(
        strategy_sharpe_baseline=1.2, strategy_sharpe_stressed=0.4, market_sharpe=0.7
    )
    result = _run(session, sup.passing_evidence(benchmark=bench))
    assert _gate(result, "7").passed  # baseline clears
    assert not _gate(result, "4b").passed  # the stressed setting does not
    assert _gate(result, "4b").evidence["stressed"]["gate7"] is False
    assert not result.passed


def test_gate_4b_fails_when_the_mechanical_benchmark_wins_under_stress(session: Session) -> None:
    bench = sup.benchmark(mechanical_sharpe_stressed=1.5)
    result = _run(session, sup.passing_evidence(benchmark=bench))
    assert _gate(result, "7b").passed
    assert _gate(result, "4b").evidence["stressed"]["gate7b"] is False


def test_gate_4b_records_that_selection_is_frozen_at_the_baseline_cost(session: Session) -> None:
    """D5 §6.2c form (a) is the GATING form; form (b) is a reported diagnostic."""
    g = _gate(_run(session, sup.passing_evidence()), "4b")
    assert g.evidence["selection_frozen_form_a"] is True
    assert "re-selecting" in g.evidence["selection_frozen_note"]


def test_gate_4b_states_that_the_equity_application_is_a_disposition_input_only(
    session: Session,
) -> None:
    g = _gate(_run(session, sup.passing_evidence()), "4b")
    assert "DISPOSITION INPUT ONLY" in g.evidence["equity_application"]


# --------------------------------------------------------------------------- #
# gates 5, 6, 6b, 7, 7b
# --------------------------------------------------------------------------- #
def test_gate_5_fails_honestly_when_no_options_grid_was_run(session: Session) -> None:
    g = _gate(_run(session, sup.passing_evidence(sensitivity=None)), "5")
    assert not g.passed
    assert g.evidence["grid_run"] is False


def test_gate_5_fails_on_evaluability_even_when_the_evaluable_cells_are_positive(
    session: Session,
) -> None:
    """D5 §5.5: ``pos_frac``'s denominator is EVALUABLE points, so a grid where 92
    of 96 cells are too thin can still report '100% positive' off four cells."""
    sens = sup.sensitivity(n_evaluable=20, positive_fraction=1.0, fragile=False)
    g = _gate(_run(session, sup.passing_evidence(sensitivity=sens)), "5")
    assert not g.passed
    assert g.evidence["min_evaluable"] == 58


def test_gate_6b_gates_vol_marginals_and_joint_cells_separately(session: Session) -> None:
    thin_corner = sup.census(
        joint_cells={"bull_highvol": 20, "bull_lowvol": 20, "bear_highvol": 26, "bear_lowvol": 4},
        vol_marginals={"highvol": 46, "lowvol": 24},
    )
    g = _gate(_run(session, sup.passing_evidence(census=thin_corner)), "6b")
    assert not g.passed
    assert g.evidence["thin_cells"] == ["bear_lowvol"]
    assert g.evidence["min_joint_cell_trades"] == 5
    assert g.evidence["min_vol_marginal_trades"] == 10


def test_gate_6b_records_that_the_range_cell_carries_no_vol_label(session: Session) -> None:
    """D4 §5.1 correction C1: five non-warmup labels, not six, and the range cell
    is vol-unlabelled because ``regime.py:59-62`` returns before the compound
    label is formed."""
    g = _gate(_run(session, sup.passing_evidence()), "6b")
    assert g.evidence["range_bound_vol_labelled"] is False
    assert g.evidence["range_bound_vol_labelled_citation"] == "backtest/regime.py:59-62"
    marg = g.evidence["vol_marginals"]
    assert marg["highvol"] + marg["lowvol"] + g.evidence["range_bound_count"] == 90


def test_gate_6_carries_the_mandatory_two_partition_cross_tab(session: Session) -> None:
    """D4 §5.1a: the filter reads ``research/regime.py`` (D5 §3.2) and the census
    reads ``backtest/regime.py``.  A cycle the mirror fires on can be counted
    ``range``, so bear reachability is a count, never an assertion."""
    g = _gate(_run(session, sup.passing_evidence()), "6")
    assert g.evidence["regime_partition_mismatch_fraction"] == pytest.approx(0.20)
    assert g.evidence["signal_regime_label_source"].endswith("regime_from_proxy")
    assert g.evidence["regime_label_source"].endswith("label_regimes")
    assert "NECESSARY condition" in g.evidence["regime_partition_note"]


def test_gate_7_is_kept_and_7b_is_additive_never_a_replacement(session: Session) -> None:
    """A short-premium strategy can beat mechanical harvest while losing to SPY."""
    bench = sup.benchmark(
        strategy_sharpe_baseline=0.60, market_sharpe=0.70, mechanical_sharpe_baseline=0.40
    )
    result = _run(session, sup.passing_evidence(benchmark=bench))
    assert not _gate(result, "7").passed  # loses to buy-and-hold
    assert _gate(result, "7b").passed  # but beats mechanical harvest
    assert not result.passed  # and that is not a promotion


def test_gate_7b_cannot_pass_on_an_unrun_mechanical_benchmark(session: Session) -> None:
    bench = sup.benchmark(mechanical_sharpe_baseline=None, mechanical_sharpe_stressed=None)
    g = _gate(_run(session, sup.passing_evidence(benchmark=bench)), "7b")
    assert not g.passed
    assert g.evidence["mechanical_run"] is False


# --------------------------------------------------------------------------- #
# gate 8
# --------------------------------------------------------------------------- #
def test_gate_8_reports_the_clamp_pin_and_stop_binding_counts(session: Session) -> None:
    g = _gate(_run(session, sup.passing_evidence()), "8")
    for key in (
        "r_clamped_count",
        "r_clamped_fraction",
        "pnl_r_min_unclamped",
        "pinned_fraction",
        "expectancy_sign_survives_pin_removal",
        "stop_non_binding_count",
        "n_losing_trades",
        "stop_non_binding_fraction_all_trades",
        "stop_non_binding_fraction_of_losers",
    ):
        assert key in g.evidence, key
    assert g.evidence["stop_non_binding_ceiling_binds_on"] == "stop_non_binding_fraction_of_losers"


def test_gate_8_binds_the_stop_ceiling_on_the_losing_trade_denominator(session: Session) -> None:
    """D4 §6.3 item 9: the all-trade fraction is diluted by winners, and the two
    denominators are not convertible without the loss count — so BOTH are
    recorded and the ceiling names the one it binds on."""
    dual = sup.dual_report(short_fc=8.0, long_fc=3.0, under_fc=492.0)  # a max-loss cycle
    result = _run(session, sup.passing_evidence(dual=dual))
    g = _gate(result, "8")
    assert g.evidence["n_losing_trades"] == 1
    assert (
        g.evidence["stop_non_binding_fraction_of_losers"]
        >= g.evidence["stop_non_binding_fraction_all_trades"]
    )


def test_gate_8_fails_when_the_edge_does_not_survive_removing_pinned_trades(
    session: Session,
) -> None:
    """R10's falsification shape: the killing observation is named in advance."""
    dq = sup.data_quality(pinned_fraction=0.12, expectancy_excluding_pinned_r=-0.05)
    g = _gate(_run(session, sup.passing_evidence(data_quality=dq)), "8")
    assert not g.passed
    assert g.evidence["expectancy_sign_survives_pin_removal"] is False


def test_gate_8_synthetic_mark_ceiling_is_trade_weighted_and_can_actually_fail(
    session: Session,
) -> None:
    """D4 §6.3's item-3 repair: at 0.20 the ceiling was the complement of gate
    0.d's own per-leg 0.80 floor and could never bind."""
    dq = sup.data_quality(synthetic_mark_fraction_trade_weighted=0.15)
    g = _gate(_run(session, sup.passing_evidence(data_quality=dq)), "8")
    assert not g.passed
    assert g.evidence["synthetic_mark_fraction_max"] == 0.10


def test_gate_8_reports_the_clustered_ci_alongside_the_iid_one_without_gating_it(
    session: Session,
) -> None:
    g = _gate(_run(session, sup.passing_evidence()), "8")
    assert g.evidence["clustered_bootstrap_ci"]["low"] == 0.05
    assert g.evidence["clustering_unit"] == "(underlying, expiry cycle)"
    assert g.evidence["clustered_ci_is_reported_not_gated"] is True


def test_gate_8_names_the_assignment_bias_direction(session: Session) -> None:
    g = _gate(_run(session, sup.passing_evidence()), "8")
    assert "STRATEGY'S FAVOUR" in g.evidence["assignment_bias_direction"]


def test_the_d4_d5_threshold_conflicts_are_resolved_tighter_and_both_recorded() -> None:
    th = OptionsGateThresholds()
    assert th.r_clamped_fraction_max == 0.05 < th.r_clamped_fraction_f9_noship == 0.10
    assert th.stop_non_binding_of_losers_max == 0.20 < th.stop_non_binding_of_losers_d4 == 0.25


# --------------------------------------------------------------------------- #
# gate 9 and sealed-look accounting
# --------------------------------------------------------------------------- #
def test_the_options_family_starts_at_k_equals_zero(session: Session) -> None:
    assert count_sealed_looks(session, SPEC.name) == 0
    assert options_program_looks(session) == 0
    result = _run(session, sup.passing_evidence())
    assert result.sealed_look_prior == 0
    assert result.sealed_look_index == 1
    assert count_sealed_looks(session, SPEC.name) == 1
    assert options_program_looks(session) == 1


def test_a_second_run_on_the_same_snapshot_REPLAYS_and_takes_no_new_look(
    session: Session,
) -> None:
    snap = sup.options_snapshot(session)
    first = _run(session, sup.passing_evidence(), snapshot=snap)
    second = _run(
        session, sup.passing_evidence(sealed=sup.sealed(expectancy_r=9.99)), snapshot=snap
    )
    assert second.sealed_test_reused is True
    assert second.sealed_test_id == first.sealed_test_id
    assert second.sealed_look_index == 1  # the replayed row's own index, not 2
    assert count_sealed_looks(session, SPEC.name) == 1
    row = session.get(StrategySealedTest, first.sealed_test_id)
    assert row.metrics_json["expectancy_r"] == 0.14  # never overwritten


def test_the_equity_sealed_ledger_is_untouched_by_an_options_look(session: Session) -> None:
    """``count_sealed_looks`` joins through ``Strategy.name``, so conflation is
    impossible in either direction — this asserts it rather than assuming it."""
    _run(session, sup.passing_evidence())
    assert count_sealed_looks(session, "trend_continuation.short_swing") == 0
    assert count_sealed_looks(session, SPEC.name) == 1


def test_a_stressed_cost_model_can_never_reach_the_sealed_path() -> None:
    """D4 §4.3a rule 3: the assertion is on the INTENT, not the aftermath — a
    stressed run that would insert a sealed row RAISES rather than sealing."""
    with pytest.raises(SealedAtNonBaselineCost):
        sup.sealed(spread_multiplier=2.0)


def test_gate_9_cannot_pass_without_a_sealed_window_and_seals_nothing(session: Session) -> None:
    result = _run(session, sup.passing_evidence(sealed=None))
    g = _gate(result, "9")
    assert not g.passed
    assert result.sealed_test_id is None
    assert count_sealed_looks(session, SPEC.name) == 0


def test_the_program_look_total_sums_the_pre_registered_family_list(session: Session) -> None:
    """D4 §8.4: without the sum, a second structure's multiplicity would be
    invisible while every individual count stayed technically correct."""
    assert OPTIONS_FAMILY_NAMES == ("options_short_vertical.medium_swing",)
    g = _gate(_run(session, sup.passing_evidence()), "9")
    assert g.evidence["options_program_looks"] == options_program_looks(session) == 1


def test_k_effective_adds_recorded_pre_sealed_abandonments(session: Session) -> None:
    """D5 §10: ``count_sealed_looks`` cannot see a pre-sealed abandonment, so a
    v0.2.0 after a v0.1.0 stopped at F8 would print ``k_prior = 0``."""
    result = _run(session, sup.passing_evidence(presealed_abandonments=1))
    assert result.sealed_look_prior == 0
    assert result.k_effective == 1
    assert OPTIONS_LOOK_BUDGET == 2


# --------------------------------------------------------------------------- #
# snapshot identity
# --------------------------------------------------------------------------- #
def test_an_unscoped_snapshot_is_refused(session: Session) -> None:
    """D4 §2.9b: the unkeyed fallback resolves by symbol set alone, so an options
    run over the approved equity symbols would bind to the EQUITY snapshot."""
    with pytest.raises(OptionsSnapshotNotScoped):
        _run(session, sup.passing_evidence(), snapshot=sup.equity_snapshot(session))


# --------------------------------------------------------------------------- #
# the disposition record
# --------------------------------------------------------------------------- #
def test_the_disposition_record_carries_every_section_d4_9_requires(session: Session) -> None:
    result = _run(session, sup.passing_evidence())
    md = options_disposition_record(
        result,
        verdict="PAPER_APPROVED",
        status="PAPER_APPROVED",
        preregistration_ref="docs/research/options_designs/D5_first_strategy_preregistration.md",
        variant_grid=[
            {"cell": "(0.20, 0.35, 0.010, 35, 0.50, 0.25)", "reported": True, "result": "+0.17R"}
        ],
        falsification=[{"id": "F1", "condition": "OOS expectancy <= 0", "observed": "no"}],
        operator_decisions=["OP-1: per-structure max loss for the options paper account"],
    )
    for heading in (
        "## 0. Structure identity and R basis",
        "## 2. The sealed ledger",
        "## 3. Gate-by-gate result",
        "## 4. Data-provenance and disclosure block",
        "## 5. The measured-artefact block",
        "## 5a. Risk-limit fit block",
        "## 6. Variant ledger (R5)",
        "## 7. Falsification record (R10)",
        "## 9. Operator decisions outstanding",
    ):
        assert heading in md, heading
    assert "Incomparability notice" in md
    assert "Options program looks" in md
    assert "bias is in the strategy's" in md
    assert "| 0 | 0.c |" in md
    assert "| 4 | 4b |" in md


# --------------------------------------------------------------------------- #
# the guarantee: the equity ladder is byte-identical
# --------------------------------------------------------------------------- #
EQUITY_UNIVERSE = ["SPY", "AAPL"]
EQUITY_END = date(2024, 12, 31)
EQUITY_START = EQUITY_END - timedelta(days=365 * 8)


def _equity_gates_json(session: Session, strategy) -> list[dict]:
    ingest_universe(session, FixtureMarketDataAdapter(), EQUITY_UNIVERSE, EQUITY_START, EQUITY_END)
    session.flush()
    result = evaluate_promotion(
        session,
        strategy,
        symbols=EQUITY_UNIVERSE,
        start=EQUITY_START,
        end=EQUITY_END,
        config=effective_research_config(session),
    )
    return [g.to_dict() for g in result.gates]


def test_the_equity_gate_dataclass_still_emits_exactly_its_historical_five_keys() -> None:
    """D4 §1 proposed adding ``label`` to ``promotion.Gate``.  It is NOT added:
    ``Gate.to_dict()`` is what lands verbatim in ``gates_json``, so a new key
    would change the stored JSON of every historical equity evaluation."""
    keys = set(Gate(1, "n", True, "d").to_dict())
    assert keys == {"number", "name", "passed", "detail", "evidence"}
    assert "label" not in keys and "gate_id" not in keys
    assert not hasattr(Gate(1, "n", True, "d"), "label")


def test_equity_gates_json_is_byte_identical_with_the_options_ladder_imported(
    session: Session,
) -> None:
    """The I-O4 guarantee, as a mechanism rather than a promise.

    ``signalforge.research.options_promotion`` is imported at the top of this
    module, so the equity ladder below runs with every options module loaded.
    The shape, the numbering and the serialised bytes must be exactly what they
    were before this work: ten gates, contiguous 1..10, no ``label`` anywhere.
    """
    gates = _equity_gates_json(session, MeanReversion())
    assert len(gates) == 10
    assert [g["number"] for g in gates] == list(range(1, 11))
    # The ladder's shape as ordered (number, label) pairs — labels are all empty,
    # because the equity ladder has no sub-gates and gains none here.
    assert [(g["number"], g.get("label", "")) for g in gates] == [(i, "") for i in range(1, 11)]
    for g in gates:
        assert set(g) == {"number", "name", "passed", "detail", "evidence"}

    # No options key reaches an equity evidence blob at any depth.
    def _keys(obj: object) -> set[str]:
        if isinstance(obj, dict):
            return set(obj) | {k for v in obj.values() for k in _keys(v)}
        if isinstance(obj, list):
            return {k for v in obj for k in _keys(v)}
        return set()

    all_keys = _keys(gates)
    assert "label" not in all_keys
    assert "gate_id" not in all_keys
    assert not any(k.startswith("options_") or k.startswith("structure_") for k in all_keys)


def test_the_equity_ladder_is_deterministic_across_runs(session: Session) -> None:
    """Byte-identical means byte-identical: the same fixtures twice, hashed.

    Gate 9 is excluded and only gate 9: its detail legitimately records whether
    the row was sealed by this run or is a LOCKED REPLAY of an earlier one, which
    is provenance the second run is *supposed* to change.  Every other gate must
    serialise to the same bytes.
    """
    first = _equity_gates_json(session, TrendContinuation(Horizon.SHORT_SWING))
    second = _equity_gates_json(session, TrendContinuation(Horizon.SHORT_SWING))

    def digest(gs: list[dict]) -> str:
        payload = [g for g in gs if g["number"] != 9]
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()

    assert digest(first) == digest(second)
    # and gate 9 differs only in its replay provenance, never in its verdict
    g9_first = next(g for g in first if g["number"] == 9)
    g9_second = next(g for g in second if g["number"] == 9)
    assert g9_first["passed"] == g9_second["passed"]
    assert g9_second["evidence"]["reused"] is True


def test_an_options_evaluation_never_promotes_an_equity_strategy(session: Session) -> None:
    _run(session, sup.passing_evidence())
    for name in ("trend_continuation.short_swing", "mean_reversion.short_swing"):
        strat = session.scalar(select(Strategy).where(Strategy.name == name))
        assert strat is None or strat.status is StrategyStatus.EXPERIMENTAL


def test_a_pass_does_not_flip_status_by_default(session: Session) -> None:
    """``promote_on_pass`` defaults to FALSE — a deliberate deviation from D4 §9.

    ``approved_scope_scan.approved_scan_groups`` selects PAPER_APPROVED versions
    filtered by **horizon alone**, with no asset-class condition anywhere in it,
    so a PAPER_APPROVED ``options_*.medium_swing`` row is a candidate for an
    EQUITY scan group over the options snapshot's symbol set.  The status flip is
    an operator decision that belongs with D3/D6's fail-closed paper guards.
    """
    result = _run(session, sup.passing_evidence())
    assert result.passed
    assert result.verdict == "PAPER_APPROVED"  # the verdict is recorded
    ver = session.get(StrategyVersion, result.strategy_version_id)
    assert ver.status is StrategyStatus.EXPERIMENTAL  # the status is not flipped
    assert (
        session.scalar(
            select(func.count())
            .select_from(StrategyVersion)
            .where(StrategyVersion.status == StrategyStatus.PAPER_APPROVED)
        )
        == 0
    )


def test_an_explicit_promotion_flips_only_the_options_version(session: Session) -> None:
    result = _run(session, sup.passing_evidence(), promote_on_pass=True)
    assert result.passed
    ver = session.get(StrategyVersion, result.strategy_version_id)
    assert ver.status is StrategyStatus.PAPER_APPROVED
    assert (
        session.scalar(
            select(func.count())
            .select_from(StrategyVersion)
            .where(StrategyVersion.status == StrategyStatus.PAPER_APPROVED)
        )
        == 1
    )


def test_a_promoted_options_version_never_pulls_an_equity_scan_group(session: Session) -> None:
    """The hazard, asserted rather than assumed.

    Even with the status flipped, the options version must produce NO scan group
    — it is skipped, with a reason a reader can see, because its approved scope
    carries no single equity source.  This test is the tripwire: if a later
    change writes ``sources`` into the options ``data_provenance_json``, it fails
    here rather than silently scanning equities on an options universe.
    """
    from signalforge.research.approved_scope_scan import approved_scan_groups

    result = _run(session, sup.passing_evidence(), promote_on_pass=True)
    groups, skipped = approved_scan_groups(session)
    assert groups == []
    assert [s["strategy"] for s in skipped] == [SPEC.name]
    assert "sources" in skipped[0]["reason"] or "source" in skipped[0]["reason"]
    assert result.passed
