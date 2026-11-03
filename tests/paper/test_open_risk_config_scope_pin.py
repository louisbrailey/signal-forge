"""The SHIPPED default for configured open risk stays 1.5%.

The paper ledger's open-risk ceiling is 12.33% (operator decision 2026-11-02;
3.0% before that), but the effective limit is ``min(configured, ceiling)`` and
the shipped default ``max_daily_portfolio_risk_pct`` is 1.5, so on a default
config the ceiling has no effect. Raising the live value is done through the
``research_overrides`` setting, never by editing this default. The ``risk``
section is inside the approval scope hash: raising the configured value changes
``config_hash`` and takes the approved strategy versions out of scope until they
are re-evaluated. No default configuration changes here, so the default config's
scope hash is the value pinned before it.
"""

from __future__ import annotations

from signalforge.config.research import ResearchConfig
from signalforge.paper.ledger import HARD_MAX_OPEN_RISK_PCT, HARD_MAX_SYMBOL_PCT

#: The default config's scope hash as pinned on main BEFORE this PR — the same
#: literal as ``CONFIG_HASH_BEFORE_EXECUTION_SECTION`` in
#: ``tests/execution/test_config_scope.py`` (which this PR leaves untouched).
DEFAULT_SCOPE_HASH_BEFORE_THIS_PR = (
    "7fb8213a9df09fb8ac134616ecc18f1879f15b2c5ae999b459d9ea173bef3850"  # pragma: allowlist secret
)


def test_default_scope_hash_is_unchanged_by_the_paper_limit_changes() -> None:
    assert ResearchConfig().config_hash == DEFAULT_SCOPE_HASH_BEFORE_THIS_PR


def test_configured_open_risk_is_still_one_and_a_half_percent_and_binds() -> None:
    risk = ResearchConfig().risk
    assert risk.max_daily_portfolio_risk_pct == 1.5
    assert HARD_MAX_OPEN_RISK_PCT == 12.33
    # Effective = min(configured, ceiling): the 12.33% ceiling has NO effect by default.
    assert min(HARD_MAX_OPEN_RISK_PCT, risk.max_daily_portfolio_risk_pct) == 1.5
    # Per symbol the configured 10% and the 10% ceiling agree: 10% is effective.
    assert min(HARD_MAX_SYMBOL_PCT, risk.max_position_concentration_pct) == 10.0


def test_raising_configured_open_risk_would_move_the_scope_hash() -> None:
    base = ResearchConfig()
    assert "risk" in ResearchConfig.SCOPE_HASH_FIELDS
    raised = base.model_copy(
        update={"risk": base.risk.model_copy(update={"max_daily_portfolio_risk_pct": 3.0})}
    )
    assert raised.config_hash != base.config_hash
    assert raised.config_hash != DEFAULT_SCOPE_HASH_BEFORE_THIS_PR
