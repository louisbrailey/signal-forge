"""The chain-aware leakage harness (D2 §13 — §15.2 tests 6, 7, 8).

A harness that only ever passes proves nothing, so the deliberately-leaking feature
is tested as hard as the clean ones.
"""

from __future__ import annotations

from datetime import date

import pytest

from signalforge.backtest.leakage import LookaheadDetected
from signalforge.backtest.options_leakage import (
    OPTIONS_LEAKAGE_FEATURE_CHECKS,
    assert_no_lookahead_chain,
    chain_leakage_self_check,
    select_nearest_strike,
    visible_contract_count,
)
from signalforge.data.option_chain import OptionChainSeries
from signalforge.data.series import PriceSeries
from tests.options_chain_support import (
    LONG_STRIKE,
    LONG_TICKER,
    SHORT_STRIKE,
    SHORT_TICKER,
    build_fixture,
    put_contract,
    sessions_between,
)

FIRST = date(2024, 2, 1)
LAST = date(2024, 3, 20)


def _fx():
    dates = sessions_between(FIRST, LAST)
    late = dates[8]
    return build_fixture(
        dates,
        {d: 500.0 + i * 0.5 for i, d in enumerate(dates)},
        {
            SHORT_TICKER: {d: 2.0 + 0.01 * i for i, d in enumerate(dates)},
            LONG_TICKER: {d: 0.9 for d in dates if d >= late},
        },
        [
            put_contract(SHORT_TICKER, SHORT_STRIKE, dates[0]),
            put_contract(LONG_TICKER, LONG_STRIKE, late),
        ],
    )


def test_every_registered_check_passes_on_a_synthetic_chain() -> None:
    fx = _fx()
    assert OPTIONS_LEAKAGE_FEATURE_CHECKS  # the list must not be empty
    assert chain_leakage_self_check(fx.chain, fx.underlying) is None


def test_a_feature_reading_the_last_session_is_CAUGHT() -> None:
    fx = _fx()

    def leaks(chain: OptionChainSeries, underlying: PriceSeries, t: int) -> float:
        del underlying, t
        return chain.sessions[-1].underlying_close

    with pytest.raises(LookaheadDetected):
        assert_no_lookahead_chain(leaks, fx.chain, fx.underlying)


def test_a_feature_reading_the_untruncated_contract_set_is_CAUGHT() -> None:
    """Chain-MEMBERSHIP leakage: temporally clean, and still wrong (D2 §13.4 item 1)."""
    fx = _fx()

    def leaks_membership(chain: OptionChainSeries, underlying: PriceSeries, t: int) -> float:
        del underlying, t
        return float(len(chain.contracts))

    with pytest.raises(LookaheadDetected):
        assert_no_lookahead_chain(leaks_membership, fx.chain, fx.underlying, indices=[2, 3])


def test_the_strike_selector_is_on_the_list_and_is_leak_free() -> None:
    fx = _fx()
    names = {name for name, _ in OPTIONS_LEAKAGE_FEATURE_CHECKS}
    assert "select_nearest_strike" in names
    assert "select_nearest_strike@t-5" in names
    assert_no_lookahead_chain(select_nearest_strike, fx.chain, fx.underlying)


def test_visible_contract_count_asserts_the_visibility_rule_is_applied() -> None:
    fx = _fx()
    assert visible_contract_count(fx.chain.head(2), fx.underlying.head(2), 2) == 1.0
    assert visible_contract_count(fx.chain.head(9), fx.underlying.head(9), 9) == 2.0


def test_the_self_check_reports_the_failing_feature_by_name() -> None:
    fx = _fx()
    from signalforge.backtest import options_leakage as mod

    original = mod.OPTIONS_LEAKAGE_FEATURE_CHECKS

    def leaks(chain: OptionChainSeries, underlying: PriceSeries, t: int) -> float:
        del underlying, t
        return chain.sessions[-1].underlying_close

    try:
        mod.OPTIONS_LEAKAGE_FEATURE_CHECKS = (("deliberately_leaking", leaks),)
        problem = chain_leakage_self_check(fx.chain, fx.underlying)
    finally:
        mod.OPTIONS_LEAKAGE_FEATURE_CHECKS = original
    assert problem is not None
    assert problem.startswith("deliberately_leaking")


def test_the_harness_refuses_mismatched_session_indices() -> None:
    fx = _fx()
    with pytest.raises(ValueError, match="session index"):
        assert_no_lookahead_chain(visible_contract_count, fx.chain, fx.underlying.head(3))
