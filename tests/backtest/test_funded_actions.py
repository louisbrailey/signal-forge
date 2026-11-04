from datetime import date
from decimal import Decimal

import pytest

from signalforge.backtest.actions import (
    Dividend,
    Split,
    TickerChange,
    decision_series,
    stitch_ticker,
)
from signalforge.backtest.costs import CostModel
from signalforge.backtest.engine import EntrySignal
from signalforge.backtest.funded import run_funded_replay
from signalforge.config.research import RiskLimits
from signalforge.data.calendar import sessions
from signalforge.data.series import PriceSeries
from signalforge.domain import Direction
from signalforge.research.funded_diagnostics import diagnose

DATES = tuple(sessions(date(2024, 1, 2), date(2024, 1, 10)))


def bars(prices, symbol="A"):
    return PriceSeries.from_bars(
        symbol, [(d, p, p, p, p, 100000) for d, p in zip(DATES, prices, strict=True)]
    )


def run(b, **kw):
    return run_funded_replay(
        {"A": b},
        {"A": lambda s, t: EntrySignal(Direction.LONG, 50, 50)},
        {"A": "test"},
        limits=RiskLimits(),
        warmup=0,
        cost_model=CostModel(slippage_bps=0),
        spread_bps=0,
        **kw,
    )


def test_split_changes_shares_stops_basis_not_wealth():
    b = bars([100, 100, 50, 50, 50, 50, 50])
    r = run(b, splits=(Split("A", DATES[2], Decimal(2), "test"),))
    assert r.fills[0]["shares"] == 1
    assert r.fills[-1]["shares"] == 2
    assert r.fills[-1]["reason"] == "end_of_data"
    assert r.fills[-1]["realized_pnl_usd"] == "0.00"
    assert all(Decimal(m["net_liquidation_usd"]) == 10000 for m in r.marks)
    d = diagnose(
        r,
        start=DATES[0],
        end=DATES[-1],
        initial_cash=Decimal(10000),
        source_reference="test",
        strategy_version="test",
        cost_model_reference="zero",
    )
    assert d["income_targets"]["full_period_net_pnl_usd"] == "0.00"


def test_dividend_entitlement_receivable_payment_and_sale():
    b = bars([100, 100, 99, 99, 99, 99, 99])
    r = run(b, dividends=(Dividend("A", DATES[2], DATES[4], Decimal(1), "test"),))
    assert r.marks[2]["dividend_receivable_usd"] == "1.00"
    assert r.marks[2]["cash_usd"] == "9900.00"
    assert r.marks[4]["cash_usd"] == "9901.00"
    assert r.marks[-1]["net_liquidation_usd"] == "10000.00"
    assert [e["kind"] for e in r.corporate_events] == ["dividend_entitlement", "dividend_payment"]


def test_ex_date_new_buyer_gets_no_dividend():
    r = run(bars([100] * 7), dividends=(Dividend("A", DATES[1], DATES[4], Decimal(1), "test"),))
    assert not r.corporate_events


def test_unpaid_entitlement_remains_asset_not_spendable_cash():
    r = run(
        bars([100] * 7), dividends=(Dividend("A", DATES[2], date(2024, 2, 1), Decimal(1), "test"),)
    )
    assert r.marks[-1]["cash_usd"] == "10000.00"
    assert r.marks[-1]["net_liquidation_usd"] == "10001.00"


def test_future_splits_never_enter_visible_features():
    b = bars([100, 100, 50, 50, 50, 50, 50])
    splits = (Split("A", DATES[2], Decimal(2), "test"),)
    assert list(decision_series(b, 1, splits).close) == [100, 100]
    assert list(decision_series(b, 2, splits).close) == [50, 50, 50]
    assert decision_series(b, 2, splits).volume[0] == 200000
    assert b.close[0] == 100  # source immutable


def test_fractional_reverse_split_fails_without_cash_in_lieu():
    with pytest.raises(ValueError, match="cash-in-lieu"):
        run(
            bars([100, 100, 200, 200, 200, 200, 200]),
            splits=(Split("A", DATES[2], Decimal("0.5"), "test"),),
        )


def test_drawdown_latches_and_keeps_protective_exits():
    r = run(bars([100, 100, 40, 100, 100, 100, 100]), max_drawdown_pct=0.1)
    assert r.fills[-1]["reason"] == "gap_stop"
    assert len([f for f in r.fills if f["side"] == "buy"]) == 1
    assert any(d["reason"] == "portfolio_drawdown_halt" for d in r.decisions)
    assert all(m["drawdown_halted"] for m in r.marks[2:])


def test_staggered_listing_no_fabricated_prelisting_bars():
    a = bars([100] * 7)
    b = PriceSeries.from_bars("B", [(d, 100, 100, 100, 100, 100000) for d in DATES[3:]])
    seen = []

    def fn(s, t):
        seen.append((s.symbol, s.dates[0], s.dates[-1]))
        return None

    run_funded_replay(
        {"A": a, "B": b},
        {"A": fn, "B": fn},
        {"A": "x", "B": "x"},
        limits=RiskLimits(),
        warmup=0,
        allow_staggered_start=True,
    )
    assert all(first == DATES[3] for symbol, first, last in seen if symbol == "B")
    with pytest.raises(ValueError, match="calendars"):
        run_funded_replay(
            {"A": a, "B": b}, {"A": fn, "B": fn}, {"A": "x", "B": "x"}, limits=RiskLimits()
        )


def test_verified_ticker_bridge_no_phantom_overlap():
    old = bars([100] * 7, "OLD")
    new = bars([100] * 7, "NEW")
    change = TickerChange("OLD", "NEW", DATES[3], "vendor", "verified-source-id")
    combined = stitch_ticker(old, new, change)
    assert combined.dates == DATES and combined.symbol == "NEW"


def test_pending_signal_rescaled_on_next_open_split():
    b = bars([100, 50, 50, 50, 50, 50, 50])
    r = run(b, splits=(Split("A", DATES[1], Decimal(2), "test"),))
    assert r.fills[0]["price"] == "50.00"
    assert r.fills[-1]["reason"] == "end_of_data"
    assert r.marks[-1]["net_liquidation_usd"] == "10000.00"


def test_nonterminal_forward_replay_keeps_lots_and_prefixes_stable():
    full = bars([100] * 7)
    first = run(full.head(4), liquidate_at_end=False)
    later = run(full, liquidate_at_end=False)
    assert first.open_lots == later.open_lots
    assert first.marks == later.marks[:5]
    assert len(later.fills) == 1
    assert later.open_lots["A"]["shares"] == 1


def test_entry_start_does_not_trade_before_frozen_future_date():
    r = run(bars([100] * 7), entry_start=DATES[4], liquidate_at_end=False)
    assert r.fills[0]["day"] == str(DATES[4])
    assert all(m["open_positions"] == 0 for m in r.marks[:4])


def test_sale_on_ex_date_still_owns_receivable():
    b = bars([100, 100, 40, 40, 40, 40, 40])
    r = run(
        b, dividends=(Dividend("A", DATES[2], DATES[4], Decimal(1), "test"),), max_drawdown_pct=0.1
    )
    assert r.fills[-1]["reason"] == "gap_stop"
    assert r.corporate_events[-1]["kind"] == "dividend_payment"
    assert r.marks[-1]["cash_usd"] == "9941.00"


def test_held_lot_keeps_basis_across_verified_ticker_change():
    r = run(
        bars([100] * 7),
        ticker_changes=(TickerChange("OLD", "A", DATES[3], "test", "verified-identity"),),
    )
    assert r.fills[0]["ticker"] == "OLD"
    assert r.fills[-1]["ticker"] == "A"
    assert r.fills[-1]["realized_pnl_usd"] == "0.00"
    assert r.corporate_events[0]["kind"] == "ticker_change"


def test_same_day_split_and_dividend_use_post_split_entitlement():
    r = run(
        bars([100, 100, 49, 49, 49, 49, 49]),
        splits=(Split("A", DATES[2], Decimal(2), "test"),),
        dividends=(Dividend("A", DATES[2], DATES[4], Decimal(1), "test"),),
    )
    assert r.marks[2]["dividend_receivable_usd"] == "2.00"
    assert r.marks[4]["cash_usd"] == "9902.00"
    assert r.marks[-1]["net_liquidation_usd"] == "10000.00"
