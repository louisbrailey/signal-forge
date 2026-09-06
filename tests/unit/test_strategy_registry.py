"""Strategy registry: completeness gate + status filtering."""

from __future__ import annotations

import dataclasses

import pytest

from signalforge.config.research import Horizon
from signalforge.research.registry import (
    StrategyRegistrationError,
    StrategyRegistry,
    StrategySpec,
    StrategyStatus,
)


def _complete_spec(**overrides: object) -> StrategySpec:
    base = {
        "name": "trend_continuation",
        "version": "0.1.0",
        "git_sha": "abc1234",
        "horizon": Horizon.SHORT_SWING,
        "rule_definition": "close > SMA(50) and volume > 1.5x avg",
        "required_data_sources": ("BAR_DAILY",),
        "feature_definitions": ("sma_50", "vol_ratio_20"),
        "entry_conditions": "cross above with volume confirmation",
        "invalidation_conditions": "close back below SMA(50)",
        "exit_logic": "target = entry + 2 * ATR(14)",
        "stop_logic": "entry - 1 * ATR(14)",
        "time_stop": "10 sessions",
        "liquidity_requirements": "ADDV > 20M, spread < 15bps",
        "event_filters": "no earnings within 3 sessions",
        "assumed_transaction_costs": "0 commission",
        "slippage_model": "3 bps + half spread",
        "permits_long": True,
        "permits_short": False,
        "known_failure_modes": ("whipsaw in range regimes",),
        "test_date_range": "2015-01-01..2024-12-31",
        "in_sample_period": "2015-01-01..2021-12-31",
        "out_of_sample_period": "2022-01-01..2024-12-31",
        "walkforward_result_ref": "reports/trend_continuation-0.1.0.md",
    }
    base.update(overrides)
    return StrategySpec(**base)  # type: ignore[arg-type]


def test_incomplete_spec_is_rejected() -> None:
    incomplete = dataclasses.replace(_complete_spec(), entry_conditions="")
    reg = StrategyRegistry()
    with pytest.raises(StrategyRegistrationError, match="entry_conditions"):
        reg.register(incomplete)


def test_experimental_is_scan_eligible_but_not_alert_eligible() -> None:
    reg = StrategyRegistry()
    reg.register(_complete_spec(status=StrategyStatus.EXPERIMENTAL))
    assert len(reg.scan_eligible()) == 1
    assert reg.alert_eligible() == []


def test_disabled_is_neither() -> None:
    reg = StrategyRegistry()
    reg.register(_complete_spec(status=StrategyStatus.DISABLED))
    assert reg.scan_eligible() == []
    assert reg.alert_eligible() == []


def test_duplicate_registration_is_rejected() -> None:
    reg = StrategyRegistry()
    reg.register(_complete_spec())
    with pytest.raises(StrategyRegistrationError, match="already registered"):
        reg.register(_complete_spec())
