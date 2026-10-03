"""The options family is registered SEPARATELY, and the equity side cannot feel it.

R7: registering a new strategy must not disturb
``approval_scope.current_spec_json_hash()`` for a live approved version.  The two
PAPER_APPROVED approvals are scoped by exactly these hashes, so an options
strategy that leaked into ``default_strategies()`` would put them permanently out
of their own scope — which is why this file exists and why it asserts the hashes
as literals rather than as "whatever the code says today".
"""

from __future__ import annotations

import math

import pytest
from sqlalchemy.orm import Session

from signalforge.domain import Horizon
from signalforge.research.approval_scope import current_spec_json_hash
from signalforge.research.options_promotion import OPTIONS_FAMILY_NAMES
from signalforge.research.options_strategies import (
    OAT_PARAMETERS,
    SENSITIVITY_GRID,
    STRATEGY_KEY,
    VERSION,
    OptionsShortVertical,
    ShortVerticalParams,
    build_options_registry,
    default_options_strategies,
)
from signalforge.research.persistence import spec_json_hash, upsert_strategy_version
from signalforge.research.promotion import (
    _merge_declared_axes,
    _sensitivity_plan,
    declared_sensitivity_axes,
)
from signalforge.research.sensitivity import MAX_GRID_POINTS
from signalforge.research.strategies import (
    MeanReversion,
    RelativeStrength,
    TrendContinuation,
    default_strategies,
)

# The hashes the live approvals of versions 2, 3 and 5 are recorded under.
# Public content hashes, not secrets.
HV2 = "2ed9743170bd3bbdb450ea03a004a7ffaeb64ccbbe6075db312ffd544072f382"  # pragma: allowlist secret
HV3 = "9b31cc38315766f15a9002c5e046140aed87642cffbccd51652fcd59178c2207"  # pragma: allowlist secret
HV5 = "dfe696b662dd02b8fa3a02ce5b987c6eade84a40d88c1a2d8d52e206cb6f6c32"  # pragma: allowlist secret


# --------------------------------------------------------------------------- #
# registry isolation
# --------------------------------------------------------------------------- #
def test_default_strategies_is_unchanged_by_the_options_family() -> None:
    """Importing the options registry (this module does, at the top) must leave
    the equity list byte-identical in membership and order."""
    keys = [s.key for s in default_strategies()]
    assert keys == [
        "intraday_orb.intraday",
        "trend_continuation.short_swing",
        "trend_continuation.medium_swing",
        "mean_reversion.short_swing",
        "relative_strength.medium_swing",
        "volatility_breakout.short_swing",
    ]
    assert not any(k.startswith("options") for k in keys)


def test_the_options_strategy_lives_only_in_its_own_registry() -> None:
    options_keys = [s.key for s in default_options_strategies()]
    assert options_keys == [STRATEGY_KEY]
    assert set(options_keys).isdisjoint({s.key for s in default_strategies()})
    reg = build_options_registry()
    assert reg.alert_eligible() == []  # EXPERIMENTAL until the ladder says otherwise


def test_the_pre_registered_family_list_matches_the_shipped_registry() -> None:
    """A family name in one and not the other is, by definition, an undisclosed
    look (D4 §8.4)."""
    assert tuple(s.spec().name for s in default_options_strategies()) == OPTIONS_FAMILY_NAMES


def test_registering_the_options_class_does_not_move_an_equity_spec_hash() -> None:
    assert spec_json_hash(TrendContinuation(Horizon.SHORT_SWING).spec()) == HV2
    assert spec_json_hash(TrendContinuation(Horizon.MEDIUM_SWING).spec()) == HV3
    assert spec_json_hash(RelativeStrength(Horizon.MEDIUM_SWING).spec()) == HV5


def test_current_spec_json_hash_for_versions_2_3_and_5_is_unchanged(session: Session) -> None:
    """The function walks ``default_strategies()`` computing a hash per entry —
    the exact call site an options entry would have contaminated."""
    for strat in default_strategies():
        upsert_strategy_version(session, strat.spec())
    for opt in default_options_strategies():
        upsert_strategy_version(session, opt.spec())
    session.flush()

    for strat, expected in (
        (TrendContinuation(Horizon.SHORT_SWING), HV2),
        (TrendContinuation(Horizon.MEDIUM_SWING), HV3),
        (RelativeStrength(Horizon.MEDIUM_SWING), HV5),
    ):
        spec = strat.spec()
        ver = upsert_strategy_version(session, spec)
        assert current_spec_json_hash(session, ver.id) == expected

    # the options version resolves to NOTHING through the equity helper
    opt_ver = upsert_strategy_version(session, OptionsShortVertical().spec())
    assert current_spec_json_hash(session, opt_ver.id) is None


# --------------------------------------------------------------------------- #
# spec hash cannot collide
# --------------------------------------------------------------------------- #
def test_the_options_spec_hash_collides_with_no_equity_spec_hash() -> None:
    options_hash = spec_json_hash(OptionsShortVertical().spec())
    equity_hashes = {spec_json_hash(s.spec()) for s in default_strategies()}
    assert options_hash not in equity_hashes
    assert len(equity_hashes) == 6  # and the equity set itself is still collision-free


def test_the_options_spec_is_distinguishable_without_hashing_it_at_all() -> None:
    """Belt and braces: the name, the data sources and the horizon each differ
    from every equity spec, so a collision would need a sha256 break."""
    spec = OptionsShortVertical().spec()
    assert spec.name.startswith("options_")
    assert "OPTION_AGGREGATE_DAILY" in spec.required_data_sources
    for s in default_strategies():
        other = s.spec()
        assert other.name != spec.name
        assert "OPTION_AGGREGATE_DAILY" not in other.required_data_sources


def test_the_options_spec_is_complete_and_experimental() -> None:
    spec = OptionsShortVertical().spec()
    assert spec.missing_fields() == []
    assert spec.version == VERSION == "0.1.2"  # D5a Amendment 2 (OP-1)
    assert spec.horizon is Horizon.MEDIUM_SWING  # OQ-1 ratified, D5a §5
    assert spec.status.value == "experimental"
    assert "authorises NO order" in spec.notes


# --------------------------------------------------------------------------- #
# the pre-registered params and grid
# --------------------------------------------------------------------------- #
def test_the_params_are_exactly_the_d5a_pre_registration() -> None:
    """D5 §4.1 as amended by D5a §6.1 and Amendment 2 — the v0.1.2 baseline, as literals.

    D5a moved three for derived reasons: ``min_credit_to_width`` 0.25 -> 0.10
    (0.25 was above the attainable maximum of 0.155, so v0.1.0 entered nothing),
    ``width_pct`` 0.010 of ``U`` -> ``width_usd`` $2.00 per contract (one R scale,
    so gate 0.5 passes and the then-$250 cap cleared), and ``width_tolerance_pct``
    0.50 -> 0.0.  Amendment 2 moved two more under OP-1's $900 cap: ``width_usd``
    $2.00 -> $8.00 (the widest $1-ladder width with ``8 x 100 + 1.60 <= 900``) and
    ``min_credit_to_width`` 0.10 -> 0.150 (the rounded-down median of the $8
    attainable ratios; 0.10 would admit 29 of 30 cells there).
    """
    p = ShortVerticalParams()
    assert (
        p.short_delta_target,
        p.max_short_delta,
        p.stop_multiple,
        p.dte_target,
        p.profit_target_pct,
        p.min_credit_to_width,
    ) == (0.20, 0.35, 2.0, 35, 0.50, 0.150)
    assert (p.width_usd, p.time_stop_dte) == (8.00, 7)
    assert (p.dte_window_lo, p.dte_window_hi) == (28, 45)
    assert (p.delta_tolerance, p.width_tolerance_pct) == (0.05, 0.0)
    assert (p.min_leg_volume, p.min_leg_transactions) == (10, 5)
    assert not hasattr(p, "width_pct")  # superseded by D5a §3


def test_the_declared_grid_is_six_axes_and_ninety_six_points() -> None:
    """Seven free axes are ARITHMETICALLY impossible, not merely undesirable:
    ``2**7 = 128 > MAX_GRID_POINTS``.

    D5a §6.2 swaps *which* parameter the cap forces out — ``width`` leaves because
    gate 0.5 forbids two R scales in one gate-5 statistic, and ``stop_multiple``
    takes the freed slot — but the shape is unchanged.
    """
    strat = OptionsShortVertical()
    axes = strat.sensitivity_axes()
    assert len(axes) == 6
    assert strat.grid_points() == 96 <= MAX_GRID_POINTS
    assert MAX_GRID_POINTS < 2**7
    assert math.prod(len(v) for v in axes.values()) == 96
    assert set(axes) == {
        "short_delta_target",
        "max_short_delta",
        "stop_multiple",
        "dte_target",
        "profit_target_pct",
        "min_credit_to_width",
    }
    # the width is a declared CONSTANT of the version, never an axis
    assert "width_usd" not in axes
    assert OAT_PARAMETERS["width_usd"] == (2.00, 8.00)  # v0.1.1 width as the control
    assert axes["min_credit_to_width"] == [0.150, 0.155]
    assert axes["stop_multiple"] == [2.0, 3.0]


def test_every_declared_axis_is_a_params_field_carrying_its_baseline_value() -> None:
    """``_merge_declared_axes`` raises on each of those conditions — a declaration
    that does not take effect reads as pre-registered coverage that was never
    actually tested."""
    strat = OptionsShortVertical()
    merged = _merge_declared_axes(strat, {})
    assert merged == {k: list(v) for k, v in SENSITIVITY_GRID.items()}
    assert declared_sensitivity_axes(strat) == merged


def test_every_parameter_is_either_a_grid_axis_or_a_disclosed_oat_cell() -> None:
    """R5: "abandoned variant" is definable only as "a pre-registered cell that
    was not reported", so a parameter in neither list would be invisible to both
    mechanisms."""
    from dataclasses import fields

    names = {f.name for f in fields(ShortVerticalParams)}
    covered = set(SENSITIVITY_GRID) | set(OAT_PARAMETERS)
    assert names - covered == set()


def test_the_equity_sensitivity_planner_has_no_options_branch() -> None:
    """``_sensitivity_plan`` returns ``None`` for an unknown key, which is an
    honest gate-5 failure on the equity path — never a reused equity grid."""
    assert _sensitivity_plan(OptionsShortVertical()) is None
    for strat in default_strategies():
        assert _sensitivity_plan(strat) is not None


def test_the_equity_planner_still_returns_its_own_grids_unchanged() -> None:
    _, grid = _sensitivity_plan(TrendContinuation(Horizon.SHORT_SWING))
    assert grid == {"sma_fast": [15, 20, 25], "stop_atr": [1.2, 1.5, 1.8]}
    _, grid = _sensitivity_plan(MeanReversion())
    assert grid == {"z_entry": [-2.5, -2.0, -1.5], "stop_atr": [1.5, 2.0, 2.5]}


# --------------------------------------------------------------------------- #
# derived exclusions and structural refusals
# --------------------------------------------------------------------------- #
def test_dte_target_45_is_refused_by_derivation(session: Session) -> None:
    """D5 §4.2: at 45 DTE the signal session falls before the prior cycle's time
    stop, so under one-structure-per-underlying every cycle is skipped."""
    with pytest.raises(ValueError, match="excluded by derivation"):
        OptionsShortVertical(ShortVerticalParams(dte_target=45))
    assert 45 not in SENSITIVITY_GRID["dte_target"]


def test_the_selection_cost_model_is_pinned_to_the_baseline_spread() -> None:
    """D5 §6.2c: pricing the credit floor at 2x would re-select a credit-richer
    population — form (b), a reported diagnostic, never the gating form."""
    from signalforge.research.options_strategies import PREREGISTERED_COST_MODEL

    assert PREREGISTERED_COST_MODEL.spread_multiplier == 1.0
    from dataclasses import replace

    with pytest.raises(ValueError, match=r"pinned to spread_multiplier = 1\.0"):
        OptionsShortVertical(
            selection_cost_model=replace(PREREGISTERED_COST_MODEL, spread_multiplier=2.0)
        )


def test_the_mechanical_benchmark_differs_in_exactly_the_regime_filter() -> None:
    """Gate 7b means something only because the benchmark was named in D5 §7
    before any outcome was looked at."""
    strat = OptionsShortVertical()
    mech = strat.mechanical_benchmark()
    assert mech.regime_filter is False
    assert mech.params == strat.params
    assert mech.selection_cost_model == strat.selection_cost_model
    assert "REMOVED" in strat.mechanical_spec()["regime_filter"]
