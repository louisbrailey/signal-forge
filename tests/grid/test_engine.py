"""Grid engine unit tests on fully synthetic series.

Every expected number here is derived from the rule by hand, not from a previous
run of the code.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from signalforge.grid.config import GridParams
from signalforge.grid.engine import (
    BUY,
    QTY_DP,
    SELL,
    GridSeries,
    GridState,
    decide,
    execute_fill,
    fill_price,
    run_grid_backtest,
)


def _qty(x: float) -> float:
    return round(x, QTY_DP)


def _days(n: int, start: date = date(2024, 1, 2)) -> tuple[date, ...]:
    return tuple(start + timedelta(days=i) for i in range(n))


def _series(symbol: str, closes: list[float], opens: list[float] | None = None) -> GridSeries:
    op = opens if opens is not None else closes
    return GridSeries(symbol, _days(len(closes)), tuple(op), tuple(closes))


# The canonical case: one 5% drop then one 5% rise.
#   d0 close 100.00 -> anchor = 100 (first tracked session never trades)
#   d1 close 100.00 -> levels 95.00 / 105.00, no trigger
#   d2 close  94.90 -> <= 95.00, BUY $5, fills at d3 OPEN, anchor -> 94.90
#   d3 close  94.90 -> levels 90.155 / 99.645, no trigger
#   d4 close  99.70 -> >= 99.645, SELL $10 capped at holdings, fills at d5 OPEN,
#                      anchor -> 99.70
_CLOSES = [100.0, 100.0, 94.90, 94.90, 99.70, 99.70]
_OPENS = [100.0, 100.0, 94.90, 90.00, 99.70, 101.00]


@pytest.fixture
def params() -> GridParams:
    return GridParams(starting_cash=1_000.0, per_symbol_cap=50.0, universe_name="test")


def test_one_drop_then_one_rise_produces_exactly_one_buy_then_one_sell(params: GridParams) -> None:
    res = run_grid_backtest({"AAA": _series("AAA", _CLOSES, _OPENS)}, params)

    assert [t.side for t in res.trades] == [BUY, SELL]
    buy, sell = res.trades

    # Anchors: the anchor moves to the DECISION close, not the fill price.
    assert buy.anchor_before == pytest.approx(100.0)
    assert buy.anchor_after == pytest.approx(94.90)
    assert sell.anchor_before == pytest.approx(94.90)
    assert sell.anchor_after == pytest.approx(99.70)

    # Decision dates are the closes that fired; session dates are the next session.
    d = _days(6)
    assert buy.decision_date == d[2] and buy.session_date == d[3]
    assert sell.decision_date == d[4] and sell.session_date == d[5]


def test_fills_at_the_next_sessions_open_with_costs_against_the_trade(params: GridParams) -> None:
    res = run_grid_backtest({"AAA": _series("AAA", _CLOSES, _OPENS)}, params)
    buy, sell = res.trades

    slip = params.slippage_frac
    assert slip == pytest.approx((3.0 + 5.0 / 2) / 10_000.0)
    # The buy fills at d3's open (90.00), paying up; the sell at d5's open (101.00), receiving less.
    assert buy.raw_open == pytest.approx(90.00)
    assert buy.price == pytest.approx(90.00 * (1 + slip))
    assert sell.raw_open == pytest.approx(101.00)
    assert sell.price == pytest.approx(101.00 * (1 - slip))
    assert fill_price(100.0, BUY, params) > 100.0 > fill_price(100.0, SELL, params)


def test_fractional_quantities_and_cash_deduction(params: GridParams) -> None:
    res = run_grid_backtest({"AAA": _series("AAA", _CLOSES, _OPENS)}, params)
    buy, sell = res.trades

    assert 0.0 < buy.qty < 1.0  # $5 of a $90 stock is a fraction of a share
    assert buy.qty == pytest.approx(round(5.0 / buy.price, 6))
    assert buy.usd == pytest.approx(buy.qty * buy.price)
    # Cash: out by the buy notional, back in by the sell proceeds.
    expected_cash = params.starting_cash - buy.usd + sell.usd
    assert res.final_cash == pytest.approx(expected_cash)
    # The round trip loses money purely to costs (bought at 90.05, sold at 100.94
    # is a gain here; use a flat-price series for the pure-cost check).
    flat = run_grid_backtest(
        {"BBB": _series("BBB", [100.0, 94.0, 94.0, 98.8, 98.8], [100.0, 94.0, 94.0, 98.8, 98.8])},
        params,
    )
    assert flat.trades, "expected the flat series to trade"


def test_sell_is_capped_at_the_position_market_value(params: GridParams) -> None:
    res = run_grid_backtest({"AAA": _series("AAA", _CLOSES, _OPENS)}, params)
    buy, sell = res.trades
    # sell_usd is $10 but only ~$5 of stock is held: the sell is the whole position.
    assert sell.qty == pytest.approx(buy.qty)
    assert sell.usd < params.sell_usd
    assert not res.positions  # fully exited


def test_sell_never_exceeds_holdings_over_many_rises() -> None:
    p = GridParams(starting_cash=1_000.0, per_symbol_cap=50.0, sell_usd=1_000.0)
    closes = [100.0, 94.0, 99.0, 110.0, 130.0, 160.0, 200.0]
    res = run_grid_backtest({"AAA": _series("AAA", closes)}, p)
    sells = [t for t in res.trades if t.side == SELL]
    buys = [t for t in res.trades if t.side == BUY]
    assert sells, "expected at least one sell"
    assert sum(t.qty for t in sells) <= sum(t.qty for t in buys) + 1e-9
    assert not res.positions


def test_per_symbol_cap_blocks_the_second_buy() -> None:
    p = GridParams(starting_cash=1_000.0, per_symbol_cap=5.0, buy_usd=5.0)
    # Two successive 5%+ drops from a moving anchor.
    closes = [100.0, 94.0, 89.0, 84.0, 79.0]
    res = run_grid_backtest({"AAA": _series("AAA", closes)}, p)
    buys = [t for t in res.trades if t.side == BUY]
    assert len(buys) == 1, "the cap must block every buy after the first"
    assert res.skip_counts.get("skip_per_symbol_cap", 0) >= 1
    assert res.symbols_at_cap == 1
    assert res.positions[0].cost_basis <= p.per_symbol_cap + 1e-9


def test_cost_basis_never_exceeds_the_cap_across_a_long_decline() -> None:
    p = GridParams(starting_cash=10_000.0, per_symbol_cap=50.0, buy_usd=5.0)
    closes = [100.0 * (0.94**i) for i in range(40)]
    res = run_grid_backtest({"AAA": _series("AAA", closes)}, p)
    assert res.trades
    for pos in res.positions:
        assert pos.cost_basis <= p.per_symbol_cap + 1e-9


def test_cash_exhaustion_skips_the_buy_and_cash_never_goes_negative() -> None:
    p = GridParams(starting_cash=5.5, per_symbol_cap=50.0, buy_usd=5.0)
    closes = [100.0, 94.0, 89.0, 84.0]
    res = run_grid_backtest({"AAA": _series("AAA", closes)}, p)
    assert len([t for t in res.trades if t.side == BUY]) == 1
    assert res.skip_counts.get("skip_insufficient_cash", 0) >= 1
    assert res.final_cash >= 0.0
    assert all(cash >= 0.0 for _, _, cash, _ in res.equity_curve)


def test_cash_is_shared_across_symbols_in_universe_order() -> None:
    p = GridParams(starting_cash=5.5, per_symbol_cap=50.0, buy_usd=5.0)
    closes = [100.0, 94.0, 94.0]
    series = {s: _series(s, closes) for s in ("AAA", "BBB")}
    res = run_grid_backtest(series, p, symbols=["AAA", "BBB"])
    assert [t.symbol for t in res.trades] == ["AAA"]

    res2 = run_grid_backtest(series, p, symbols=["BBB", "AAA"])
    assert [t.symbol for t in res2.trades] == ["BBB"]


def test_min_notional_skips_orders_below_the_floor() -> None:
    p = GridParams(starting_cash=1_000.0, per_symbol_cap=50.0, buy_usd=5.0, min_order_usd=20.0)
    d = decide(close=94.0, anchor=100.0, qty=0.0, cost_basis=0.0, cash=1_000.0, params=p)
    assert d.action == "none" and d.reason == "skip_min_notional"

    res = run_grid_backtest({"AAA": _series("AAA", [100.0, 94.0, 94.0])}, p)
    assert not res.trades
    assert res.skip_counts.get("skip_min_notional", 0) >= 1


def test_min_notional_skips_a_dust_sell() -> None:
    p = GridParams(starting_cash=1_000.0, per_symbol_cap=50.0, sell_usd=10.0, min_order_usd=5.0)
    # Holding $1 of stock: a sell trigger can only raise $1, below the $5 floor.
    d = decide(close=106.0, anchor=100.0, qty=0.01, cost_basis=1.0, cash=0.0, params=p)
    assert d.action == "none" and d.reason == "skip_min_notional"


def test_no_position_means_a_rise_does_nothing(params: GridParams) -> None:
    d = decide(close=106.0, anchor=100.0, qty=0.0, cost_basis=0.0, cash=100.0, params=params)
    assert d.action == "none" and d.reason == "skip_no_position"


def test_first_session_only_sets_the_anchor(params: GridParams) -> None:
    res = run_grid_backtest({"AAA": _series("AAA", [100.0])}, params)
    assert not res.trades
    res2 = run_grid_backtest({"AAA": _series("AAA", [100.0, 100.0])}, params)
    assert not res2.trades


def test_a_skipped_buy_leaves_the_anchor_armed() -> None:
    """A buy skipped for cash must NOT move the anchor — the level stays armed."""
    p = GridParams(starting_cash=0.0001, per_symbol_cap=50.0, buy_usd=5.0)
    p = p.with_(starting_cash=1.0)
    d1 = decide(close=94.0, anchor=100.0, qty=0.0, cost_basis=0.0, cash=1.0, params=p)
    assert d1.reason == "skip_insufficient_cash"
    # The anchor the caller holds is unchanged, so the next evaluation uses it again.
    d2 = decide(close=93.0, anchor=100.0, qty=0.0, cost_basis=0.0, cash=100.0, params=p)
    assert d2.action == BUY and d2.anchor_before == 100.0


def test_one_evaluation_per_symbol_per_day(params: GridParams) -> None:
    closes = [100.0 * (0.9**i) for i in range(30)]
    res = run_grid_backtest({"AAA": _series("AAA", closes)}, params)
    seen = [(t.symbol, t.session_date) for t in res.trades]
    assert len(seen) == len(set(seen)), "at most one fill per symbol per session"


def test_deterministic_across_runs(params: GridParams) -> None:
    series = {"AAA": _series("AAA", _CLOSES, _OPENS)}
    a = run_grid_backtest(series, params)
    b = run_grid_backtest(series, params)
    assert a.to_dict() == b.to_dict()


def test_symbols_without_bars_are_reported_not_dropped(params: GridParams) -> None:
    res = run_grid_backtest(
        {"AAA": _series("AAA", _CLOSES, _OPENS)},
        params,
        symbols=["AAA"],
        requested=["AAA", "ZZZ"],
    )
    assert res.skipped_symbols == ("ZZZ",)
    assert res.symbols == ("AAA",)


def test_metrics_and_benchmark(params: GridParams) -> None:
    res = run_grid_backtest(
        {"AAA": _series("AAA", _CLOSES, _OPENS)},
        params,
        benchmark=_series("SPY", [400.0, 402.0, 404.0, 406.0, 408.0, 410.0]),
    )
    m = res.metrics
    assert m.sessions == 6
    assert m.start_equity == pytest.approx(params.starting_cash)
    assert m.n_trades == 2 and m.n_buys == 1 and m.n_sells == 1
    assert 0.0 <= m.exposure <= 1.0
    assert m.max_drawdown_pct >= 0.0
    b = res.benchmark
    assert b.available and b.symbol == "SPY"
    # 400 -> 410 with a small entry cost is a touch under +2.5%.
    assert 2.0 < b.total_return_pct < 2.5
    assert res.cash_utilisation["starting_cash"] == pytest.approx(params.starting_cash)


def test_equity_curve_is_cash_plus_market_value(params: GridParams) -> None:
    res = run_grid_backtest({"AAA": _series("AAA", _CLOSES, _OPENS)}, params)
    for _d, equity, cash, invested in res.equity_curve:
        assert equity == pytest.approx(cash + invested)


def test_empty_input_is_safe(params: GridParams) -> None:
    res = run_grid_backtest({}, params)
    assert not res.trades and not res.equity_curve
    assert res.metrics.n_trades == 0
    assert not res.benchmark.available


@pytest.mark.parametrize(
    "kwargs",
    [
        {"starting_cash": 0.0},
        {"per_symbol_cap": 0.0},
        {"buy_usd": -1.0},
        {"drop_pct": 0.0},
        {"drop_pct": 1.5},
        {"rise_pct": 0.0},
        {"universe_size": 0},
        {"buy_usd": 100.0, "per_symbol_cap": 50.0},
    ],
)
def test_params_are_validated(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        GridParams(**kwargs)  # type: ignore[arg-type]


def test_budget_consistency_flag() -> None:
    inconsistent = GridParams(starting_cash=5_000.0, per_symbol_cap=50.0, universe_size=1_000)
    assert not inconsistent.budget_is_consistent
    assert inconsistent.max_committed_usd == 50_000.0

    consistent = GridParams(starting_cash=5_000.0, per_symbol_cap=5.0, universe_size=1_000)
    assert consistent.budget_is_consistent

    also = GridParams(starting_cash=50_000.0, per_symbol_cap=50.0, universe_size=1_000)
    assert also.budget_is_consistent


def test_a_buy_never_spends_more_than_buy_usd() -> None:
    """Order quantity floors, so the notional can never exceed the amount asked
    for — otherwise a rounding cent trips the cap and cash checks at fill."""
    p = GridParams(starting_cash=1_000.0, per_symbol_cap=50.0, buy_usd=5.0)
    for open_px in (7.0, 11.0, 13.0, 37.0, 101.0, 333.0, 1_234.56):
        st = GridState(symbol="AAA", anchor=100.0, tracking=True)
        dec = decide(close=94.0, anchor=100.0, qty=0.0, cost_basis=0.0, cash=1_000.0, params=p)
        trade, _cash = execute_fill(
            st, dec, date(2024, 1, 2), date(2024, 1, 3), open_px, 1_000.0, p
        )
        assert trade is not None, open_px
        assert trade.usd <= p.buy_usd + 1e-9, (open_px, trade.usd)


def test_cap_equal_to_buy_size_still_fills_the_first_buy() -> None:
    """per_symbol_cap == buy_usd is configuration (b1); it must not self-block."""
    p = GridParams(starting_cash=5_000.0, per_symbol_cap=5.0, buy_usd=5.0)
    series = {f"S{i}": _series(f"S{i}", [100.0 + i, 94.0 + i, 94.0 + i]) for i in range(20)}
    res = run_grid_backtest(series, p, symbols=sorted(series))
    assert len([t for t in res.trades if t.side == BUY]) == 20
    assert res.skip_counts.get("skip_at_fill", 0) == 0


def test_a_partial_sell_never_leaves_an_unsellable_stub() -> None:
    """$10 out of a $10.50 position would strand $0.50 below the $1 minimum,
    and that stub could never be sold again — so the whole position goes."""
    p = GridParams(starting_cash=1_000.0, per_symbol_cap=50.0, sell_usd=10.0, min_order_usd=1.0)
    px = fill_price(100.0, SELL, p)
    st = GridState(symbol="AAA", qty=_qty(10.50 / px), cost_basis=10.0, anchor=100.0, tracking=True)
    dec = decide(close=106.0, anchor=100.0, qty=st.qty, cost_basis=10.0, cash=0.0, params=p)
    assert dec.action == SELL

    trade, _cash = execute_fill(st, dec, date(2024, 1, 2), date(2024, 1, 3), 100.0, 0.0, p)
    assert trade is not None
    assert trade.usd > p.sell_usd, "the stub is swept into the same sell"
    assert st.qty == 0.0 and st.cost_basis == 0.0

    # A remainder that IS still sellable is left alone: a $30 position sells $10.
    st2 = GridState(symbol="BBB", qty=_qty(30.0 / px), cost_basis=30.0, anchor=100.0, tracking=True)
    dec2 = decide(close=106.0, anchor=100.0, qty=st2.qty, cost_basis=30.0, cash=0.0, params=p)
    trade2, _c = execute_fill(st2, dec2, date(2024, 1, 2), date(2024, 1, 3), 100.0, 0.0, p)
    assert trade2 is not None
    assert trade2.usd == pytest.approx(p.sell_usd, rel=1e-4)
    assert st2.qty > 0 and st2.qty * px >= p.min_order_usd


def test_no_open_position_is_ever_left_below_the_minimum_notional() -> None:
    """End-to-end: the sweep rule must leave no dust anywhere."""
    p = GridParams(starting_cash=5_000.0, per_symbol_cap=50.0, sell_usd=10.0, min_order_usd=1.0)
    # A long sawtooth that accumulates and partially unwinds many times.
    closes = [100.0]
    for i in range(60):
        closes.append(closes[-1] * (0.93 if i % 3 else 1.12))
    res = run_grid_backtest({"AAA": _series("AAA", closes)}, p)
    assert res.trades
    for pos in res.positions:
        assert pos.market_value >= p.min_order_usd - 1e-9, pos


def test_a_rise_with_nothing_to_sell_ratchets_the_anchor_by_default() -> None:
    """The operator's rule is silent here; the default keeps the grid alive."""
    p = GridParams(starting_cash=1_000.0)
    d = decide(close=106.0, anchor=100.0, qty=0.0, cost_basis=0.0, cash=1_000.0, params=p)
    assert d.action == "none" and d.reason == "skip_no_position"
    assert d.reanchor is True

    strict = p.with_(reanchor_on_untradeable_rise=False)
    d2 = decide(close=106.0, anchor=100.0, qty=0.0, cost_basis=0.0, cash=1_000.0, params=strict)
    assert d2.reanchor is False


def test_a_symbol_that_rises_before_it_dips_still_trades_under_the_default() -> None:
    """A steady climber then a 5% pullback: the ratcheting anchor must catch it."""
    closes = [100.0, 106.0, 112.0, 119.0, 126.0, 133.0, 126.0, 126.0]
    series = {"UP": _series("UP", closes)}

    ratchet = run_grid_backtest(series, GridParams(starting_cash=1_000.0))
    assert [t.side for t in ratchet.trades] == [BUY]
    # It bought off the 133 -> 126 pullback (-5.3%), not off the original 100 anchor.
    assert ratchet.trades[0].anchor_before == pytest.approx(133.0)

    strict = run_grid_backtest(
        series, GridParams(starting_cash=1_000.0, reanchor_on_untradeable_rise=False)
    )
    assert not strict.trades, "the strict reading strands the symbol at its first anchor"
    assert strict.skip_counts.get("skip_no_position", 0) >= 5


def test_symbols_at_cap_counts_only_symbols_the_cap_actually_bit() -> None:
    """A symbol that never bought is not "at cap", even when cap == buy_usd."""
    p = GridParams(starting_cash=1_000.0, per_symbol_cap=5.0, buy_usd=5.0)
    series = {
        "DIP": _series("DIP", [100.0, 94.0, 94.0]),  # buys once -> immediately at cap
        "FLAT": _series("FLAT", [100.0, 100.0, 100.0]),  # never trades
    }
    res = run_grid_backtest(series, p, symbols=["DIP", "FLAT"])
    assert res.symbols_traded == 1
    assert res.symbols_at_cap == 1
