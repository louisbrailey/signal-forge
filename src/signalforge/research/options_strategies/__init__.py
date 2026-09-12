"""The options strategy registry — **separate from the equity one, on purpose**.

``research.strategies.default_strategies()`` is read by
``approval_scope.current_spec_json_hash``, by ``promotion.evaluate_all_default_
strategies``, by the scanner and by the dashboard.  Adding an options strategy to
it would put an options object into every one of those call sites, and
``current_spec_json_hash`` in particular walks the whole list computing
``spec_json_hash`` for each — so the two live PAPER_APPROVED approvals would
start depending on a list that an options change can move.

So the options family is registered **here** and nowhere else.  The guarantee is
a test, not a convention: ``tests/research/test_options_strategy_registry.py``
asserts that importing this package leaves ``default_strategies()`` byte-identical
and leaves versions 2, 3 and 5's ``current_spec_json_hash`` unchanged.

D4 §8.4's family list lives in ``research.options_promotion.OPTIONS_FAMILY_NAMES``
and must stay in step with :func:`default_options_strategies` — a family name that
appears in one and not the other is, by definition, an undisclosed look.
"""

from __future__ import annotations

from signalforge.research.options_strategies.short_vertical import (
    ATTAINABLE_ADVERSE_RATIO_MAX,
    CREDIT_TO_WIDTH_QUANTILES,
    DECLARED_STRIKE_INCREMENT,
    FAMILY,
    OAT_PARAMETERS,
    OPTIONS_PER_STRUCTURE_MAX_LOSS,
    PREREGISTERED_COST_MODEL,
    SENSITIVITY_GRID,
    STRATEGY_KEY,
    VERSION,
    OptionsShortVertical,
    ShortVerticalParams,
)
from signalforge.research.registry import StrategyRegistry

__all__ = [
    "ATTAINABLE_ADVERSE_RATIO_MAX",
    "CREDIT_TO_WIDTH_QUANTILES",
    "DECLARED_STRIKE_INCREMENT",
    "FAMILY",
    "OAT_PARAMETERS",
    "OPTIONS_PER_STRUCTURE_MAX_LOSS",
    "PREREGISTERED_COST_MODEL",
    "SENSITIVITY_GRID",
    "STRATEGY_KEY",
    "VERSION",
    "OptionsShortVertical",
    "ShortVerticalParams",
    "build_options_registry",
    "default_options_strategies",
]


def default_options_strategies() -> list[OptionsShortVertical]:
    """Every options strategy this program ships.  **Never** merged into
    ``research.strategies.default_strategies()``.

    The default instance carries no ``q_lookup``, so it produces **zero
    entries** until a real per-underlying dividend series exists.  That is the
    correct, fail-closed posture today — no dividend series is ingested anywhere,
    and ``blackscholes``' ``q = 0.0`` default is exactly what gate 0.g forbids.
    """
    return [OptionsShortVertical()]


def build_options_registry() -> StrategyRegistry:
    """A registry holding only options specs, so a completeness failure in one
    can never block the equity registry from building."""
    reg = StrategyRegistry()
    for strat in default_options_strategies():
        reg.register(strat.spec())
    return reg
