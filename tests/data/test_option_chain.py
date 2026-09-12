"""``OptionChainSeries`` point-in-time discipline (D2 §3 — §15.2 test 5).

The visibility rule is the load-bearing one: ``OptionContract`` carries no listing
date and ``ingested_at`` is our retrieval time, so "which contracts existed on
2024-03-15" is not answerable from the schema.  The only data-grounded rule is
"a contract is visible at session ``t`` only if it has printed at some session
``<= t``", and ``head(t)`` must apply it — a ``head`` that truncated sessions but
left the contract set at full extent would let a feature read a strike that did not
yet exist, and the leakage harness would pass.
"""

from __future__ import annotations

from datetime import date

import pytest

from signalforge.data.option_chain import ContractPrint, OptionChainSeries, Right
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
LAST = date(2024, 3, 1)


def _fx(late_listing_index: int = 5):
    dates = sessions_between(FIRST, LAST)
    late = dates[late_listing_index]
    shorts = dict.fromkeys(dates, 2.0)
    longs = {d: 0.9 for d in dates if d >= late}
    return (
        build_fixture(
            dates,
            dict.fromkeys(dates, 505.0),
            {SHORT_TICKER: shorts, LONG_TICKER: longs},
            [
                put_contract(SHORT_TICKER, SHORT_STRIKE, dates[0]),
                put_contract(LONG_TICKER, LONG_STRIKE, late),
            ],
        ),
        dates,
        late_listing_index,
    )


def test_head_truncates_sessions_and_the_visible_contract_set() -> None:
    fx, _dates, late_idx = _fx()
    before = fx.chain.head(late_idx - 1)
    assert len(before) == late_idx
    assert SHORT_TICKER in before.contracts
    assert LONG_TICKER not in before.contracts, (
        "a contract whose first_print_session is after head(t)'s last session must be "
        "absent from head(t).contracts"
    )
    after = fx.chain.head(late_idx)
    assert LONG_TICKER in after.contracts


def test_visible_contracts_matches_head_contracts() -> None:
    fx, _, late_idx = _fx()
    for t in (0, late_idx - 1, late_idx, len(fx.chain) - 1):
        assert dict(fx.chain.visible_contracts(t)) == dict(fx.chain.head(t).contracts)


def test_print_at_returns_none_and_that_none_is_the_answer() -> None:
    fx, _dates, late_idx = _fx()
    assert fx.chain.print_at(0, LONG_TICKER) is None
    assert fx.chain.print_at(late_idx, LONG_TICKER) is not None
    assert fx.chain.print_at(0, "O:SPY240315P00001000") is None
    assert fx.chain.print_at(10_000, SHORT_TICKER) is None


def test_printed_tickers_reports_only_what_traded_that_session() -> None:
    fx, _, late_idx = _fx()
    assert fx.chain.printed_tickers(0) == frozenset({SHORT_TICKER})
    assert fx.chain.printed_tickers(late_idx) == frozenset({SHORT_TICKER, LONG_TICKER})


def test_last_print_is_the_close_not_the_thin_daily_open() -> None:
    pr = ContractPrint(open=1.0, high=3.0, low=0.5, close=2.25, volume=7.0)
    assert pr.last_print == 2.25


def test_sessions_must_be_ordered_and_unique() -> None:
    ref = put_contract(SHORT_TICKER, SHORT_STRIKE, FIRST)
    good = OptionChainSeries.from_rows(
        "SPY",
        contracts=[ref],
        underlying_closes={date(2024, 2, 1): 500.0, date(2024, 2, 2): 501.0},
        prints={},
    )
    assert good.session_dates() == (date(2024, 2, 1), date(2024, 2, 2))
    with pytest.raises(ValueError, match="ordered"):
        OptionChainSeries(
            underlying="SPY",
            sessions=tuple(reversed(good.sessions)),
            contracts={ref.option_ticker: ref},
        )


def test_index_of_and_underlying_close() -> None:
    fx, dates, _unused = _fx()
    assert fx.chain.index_of(dates[3]) == 3
    assert fx.chain.index_of(date(1999, 1, 1)) is None
    assert fx.chain.underlying_close(3) == pytest.approx(505.0)
    assert fx.chain.underlying_close(10_000) is None


def test_head_rejects_a_negative_index() -> None:
    fx, _, _ = _fx()
    with pytest.raises(IndexError):
        fx.chain.head(-1)


def test_contract_ref_carries_the_right_as_an_enum() -> None:
    ref = put_contract(SHORT_TICKER, SHORT_STRIKE, FIRST)
    assert ref.right is Right.PUT
    assert ref.shares_per_contract == 100
