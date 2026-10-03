"""Where the options risk configuration lives, and what it must never move.

D3 §1.4 is the load-bearing fact: adding a key to ``SCOPE_HASH_FIELDS`` adds a
dict entry and therefore changes ``config_hash``, which un-scopes **every** live
PAPER_APPROVED equity approval. That is the 2026-09-11 agents-section incident,
and the whole point of the ``options_risk`` / ``options_shaping`` split is that
it cannot be repeated by adding an options limit.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from signalforge.config.research import (
    OptionsRiskLimits,
    OptionsStructureLimits,
    ResearchConfig,
)

#: The default equity scope hash, recorded independently in D3 §1.4 as
#: ``7fb8213a...``. If a commit moves this, it has un-scoped every live approval.
DEFAULT_CONFIG_HASH_PREFIX = "7fb8213a"


def test_neither_options_object_is_in_the_approval_scope_hash() -> None:
    assert "options_risk" not in ResearchConfig.SCOPE_HASH_FIELDS
    assert "options_shaping" not in ResearchConfig.SCOPE_HASH_FIELDS
    assert "options" not in ResearchConfig.SCOPE_HASH_FIELDS


def test_the_default_equity_config_hash_did_not_move() -> None:
    """The sections I-O6 adds are absent from the hash, so the hash is the one
    D3 §1.4 recorded before any options code existed."""
    assert ResearchConfig().config_hash.startswith(DEFAULT_CONFIG_HASH_PREFIX)


def test_changing_any_options_limit_leaves_the_equity_config_hash_alone() -> None:
    base = ResearchConfig()
    for override in (
        {"options_risk": OptionsRiskLimits(per_structure_max_loss_dollars=700.0)},
        {"options_risk": OptionsRiskLimits(collateral_cap_dollars=1.0)},
        {"options_risk": OptionsRiskLimits(paper_account_name="something_else")},
        {"options_shaping": OptionsStructureLimits(max_short_delta=0.42)},
        {"options_shaping": OptionsStructureLimits(min_credit_to_width=0.0)},
        {"options_shaping": OptionsStructureLimits(time_stop_dte=21)},
    ):
        moved = base.model_copy(update=override)
        assert moved.config_hash == base.config_hash
        # but the FULL hash moves, so the change is still on the audit trail
        assert moved.full_config_hash != base.full_config_hash


def test_adding_an_options_key_to_the_scope_fields_WOULD_move_the_hash() -> None:
    """The counterfactual, asserted so the rule has teeth rather than being a
    comment: this is exactly what the split exists to prevent."""
    from signalforge.config.hashing import config_hash

    cfg = ResearchConfig()
    payload = cfg.model_dump(mode="json")
    scoped = {k: payload[k] for k in ResearchConfig.SCOPE_HASH_FIELDS if k in payload}
    assert config_hash(scoped) == cfg.config_hash
    widened = scoped | {"options_risk": payload["options_risk"]}
    assert config_hash(widened) != cfg.config_hash


def test_the_refusal_only_limits_carry_decision_4s_numbers() -> None:
    """Decision 4 of DECISIONS_2026-09-12_options_execution.md, as evaluation
    grid CENTRES, with the two max-loss caps as the operator re-set them under
    OP-1 (2026-09-23, DECISIONS_2026-09-12_wave3.md addendum 3): $900 / $3,600,
    i.e. 3.6% / 14.4% of the $25,000 options account. Collateral is NOT OP-1's."""
    limits = OptionsRiskLimits()
    assert limits.per_structure_max_loss_dollars == 900.0
    assert limits.total_open_max_loss_dollars == 3_600.0
    assert limits.per_structure_max_loss_dollars / limits.paper_account_initial_cash == 0.036
    assert limits.total_open_max_loss_dollars / limits.paper_account_initial_cash == 0.144
    # the book still caps at floor(3600 / 900) = 4 full-cap structures, so the
    # structure-count limit (5) stays dead configuration, as it was at 1000 / 250
    assert limits.total_open_max_loss_dollars // limits.per_structure_max_loss_dollars == 4
    assert limits.max_open_structures == 5
    assert limits.collateral_cap_dollars == 5_000.0
    assert limits.max_net_delta_notional_dollars == 10_000.0
    assert limits.max_net_vega_dollars_per_vol_pt == 50.0
    assert limits.per_order_notional_dollars == 1_000.0
    assert limits.daily_order_cap == 10
    assert limits.account_exposure_cap_pct == 40.0
    # decision 13: a separate $25,000 SIMULATED options account
    assert limits.paper_account_name == "options"
    assert limits.paper_account_initial_cash == 25_000.0


def test_the_shaping_pair_is_KEPT_and_carries_its_grid_centres() -> None:
    """``min_credit_to_width`` paired with ``max_short_delta``, per map §3.2's
    Rule. Rev 1's proposal to retire the credit hurdle was withdrawn: the
    "degeneracy" was -0.034..+0.064, monotone in sigma*sqrt(T), not +/-0.02."""
    shaping = OptionsStructureLimits()
    assert shaping.max_short_delta == 0.20
    assert shaping.min_credit_to_width == 0.25
    assert shaping.structure_type == "vertical_credit"
    assert (shaping.dte_entry_min, shaping.dte_entry_max) == (21, 45)
    assert (shaping.width_min_dollars, shaping.width_max_dollars) == (2.0, 3.0)
    assert shaping.profit_target_pct_of_credit == 0.50
    assert shaping.stop_multiple_of_credit == 2.0
    assert shaping.time_stop_dte == 7


def test_the_shaping_group_is_overridden_by_the_strategys_own_spec_json() -> None:
    """So a shaping change moves ``spec_json_hash`` — which the five-part scope
    match already compares — rather than leaving no artifact anywhere."""
    default = OptionsStructureLimits()
    assert OptionsStructureLimits.from_spec_json(None, default) == default
    assert OptionsStructureLimits.from_spec_json({}, default) == default
    assert OptionsStructureLimits.from_spec_json({"options": "not a dict"}, default) == default

    overridden = OptionsStructureLimits.from_spec_json(
        {"options": {"max_short_delta": 0.16, "time_stop_dte": 10, "unknown_key": 1}}, default
    )
    assert overridden.max_short_delta == 0.16
    assert overridden.time_stop_dte == 10
    assert overridden.min_credit_to_width == default.min_credit_to_width  # untouched
    assert overridden.options_shaping_hash != default.options_shaping_hash


def test_both_options_objects_are_frozen_and_reject_unknown_fields() -> None:
    """``frozen`` + ``extra="forbid"``: a limit cannot be mutated in place, and a
    typo'd field name is a construction error rather than a silently ignored
    setting that reads as the default."""
    limits = OptionsRiskLimits()
    with pytest.raises(ValidationError):
        limits.per_structure_max_loss_dollars = 1.0  # type: ignore[misc]
    with pytest.raises(ValidationError):
        OptionsRiskLimits(not_a_field=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        OptionsStructureLimits(not_a_field=1)  # type: ignore[call-arg]
