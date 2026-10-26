"""D5a §3.5 / Amendment 2 §3.3: the pre-registered 4-structure portfolio cap."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from signalforge.backtest.options_engine import (
    OptionsBacktestOutcome,
    OptionsCounters,
    RBasis,
)
from signalforge.research.options_backtest_runner import DualSpreadReport, _cells_for
from signalforge.research.options_evidence import cap_concurrent, pool_dual
from signalforge.research.options_strategies.short_vertical import OptionsShortVertical
from tests.research.test_options_evidence import _trade

D = date(2025, 3, 3)


def test_short_vertical_declares_the_preregistered_cap_of_four() -> None:
    # floor(3600 / 801.60) = 4 (Amendment 2 §3.3)
    assert OptionsShortVertical.portfolio_concurrency_cap == 4
    assert int(3600 // 801.60) == 4


def test_cap_keeps_four_and_skips_the_rest_by_ascending_symbol() -> None:
    same_day = [_trade(s, D, D + timedelta(days=20), 0.1) for s in "FEDCBA"]
    kept, skipped = cap_concurrent(same_day, 4)
    assert [t.underlying_symbol for t in kept] == ["A", "B", "C", "D"]
    assert [t.underlying_symbol for t in skipped] == ["E", "F"]


def test_priority_ignores_the_outcome() -> None:
    a = _trade("ZZZ", D, D + timedelta(days=5), 5.0)  # great trade, late symbol
    b = _trade("AAA", D, D + timedelta(days=5), -1.0)
    kept, skipped = cap_concurrent([a, b], 1)
    assert [t.underlying_symbol for t in kept] == ["AAA"]
    assert skipped == [a]


def test_a_slot_frees_the_session_after_the_exit_not_the_same_day() -> None:
    first = _trade("AAA", D, D + timedelta(days=10), 0.1)
    same_day_as_exit = _trade("BBB", D + timedelta(days=10), D + timedelta(days=30), 0.1)
    next_day = _trade("CCC", D + timedelta(days=11), D + timedelta(days=30), 0.1)
    kept, skipped = cap_concurrent([first, same_day_as_exit, next_day], 1)
    assert [t.underlying_symbol for t in kept] == ["AAA", "CCC"]
    assert [t.underlying_symbol for t in skipped] == ["BBB"]


def test_no_cap_keeps_everything_and_a_bad_cap_is_refused() -> None:
    ts = [_trade(s, D, D + timedelta(days=3), 0.1) for s in "ABCDEF"]
    assert cap_concurrent(ts, None) == (sorted(ts, key=lambda t: t.underlying_symbol), [])
    with pytest.raises(ValueError):
        cap_concurrent(ts, 0)


def _outcome(sym: str, trades: list, mult: float) -> OptionsBacktestOutcome:
    return OptionsBacktestOutcome(
        underlying_symbol=sym,
        r_basis=RBasis.INCL,
        spread_multiplier=mult,
        trades=trades,
        excluded=[],
        counters=OptionsCounters(),
        sessions=100,
        first_date=D,
        last_date=D + timedelta(days=100),
    )


def _dual(sym: str, pnl: float) -> DualSpreadReport:
    base = _outcome(sym, [_trade(sym, D, D + timedelta(days=20), pnl)], 1.0)
    stress = _outcome(sym, [_trade(sym, D, D + timedelta(days=20), pnl - 0.05)], 2.0)
    return DualSpreadReport(
        cells=_cells_for(base) | _cells_for(stress), baseline=base, stressed=stress
    )


def test_pooled_population_is_capped_identically_in_both_spread_cells() -> None:
    duals = [_dual(s, 0.2) for s in ("QQQ", "IWM", "SPY", "DIA", "XLK")]
    uncapped = pool_dual(duals)
    capped = pool_dual(duals, concurrency_cap=4)

    assert len(uncapped.baseline.trades) == 5
    assert [t.underlying_symbol for t in capped.baseline.trades] == ["DIA", "IWM", "QQQ", "SPY"]
    assert [t.underlying_symbol for t in capped.stressed.trades] == ["DIA", "IWM", "QQQ", "SPY"]
    assert capped.baseline.counters.skipped_portfolio_concurrency == 1
    assert capped.stressed.counters.skipped_portfolio_concurrency == 1
    # the source reports are never mutated
    assert all(d.baseline.counters.skipped_portfolio_concurrency == 0 for d in duals)
