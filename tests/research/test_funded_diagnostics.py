from datetime import date
from decimal import Decimal

import pytest

from signalforge.backtest.costs import CostModel
from signalforge.backtest.funded import FundedReplay
from signalforge.data.calendar import sessions
from signalforge.data.series import PriceSeries
from signalforge.research.funded_diagnostics import diagnose, passive_comparator


def cash_result():
    return FundedReplay(
        marks=[
            {
                "day": str(d),
                "net_liquidation_usd": "10000.00",
                "gross_exposure_usd": "0",
                "open_positions": 0,
            }
            for d in sessions(date(2024, 1, 5), date(2024, 1, 8))
        ]
    )


def report(result):
    return diagnose(
        result,
        start=date(2024, 1, 5),
        end=date(2024, 1, 8),
        initial_cash=Decimal("10000"),
        source_reference="test",
        strategy_version="test",
        cost_model_reference="test",
    )


def test_calendar_closures_carried_and_no_weekend_income_claim():
    r = report(cash_result())
    assert r["closed_market_carry_dates"] == ["2024-01-06", "2024-01-07"]
    assert r["income_targets"]["usable_daily_changes"] == 4
    assert r["income_targets"]["weekends"]["target_hits"] == 0
    assert r["income_targets"]["reliability_status"] == "not_established"
    assert not r["calendar_evidence"]["weekend_market_access"]
    assert r["average_session_exposure_pct"] == 0


@pytest.mark.parametrize("case", ["missing", "duplicate", "reversed"])
def test_missing_sessions_never_filled(case):
    r = cash_result()
    if case == "missing":
        r.marks.pop()
    elif case == "duplicate":
        r.marks.append(r.marks[-1])
    else:
        r.marks.reverse()
    with pytest.raises(ValueError, match="session marks"):
        report(r)


def test_closed_trade_attribution_and_reconciliation():
    r = cash_result()
    r.fills = [
        {"side": "buy", "symbol": "A", "price": "100", "shares": 2, "commission": "1"},
        {"side": "sell", "symbol": "A", "price": "110", "shares": 2, "commission": "1"},
    ]
    r.marks[-1]["net_liquidation_usd"] = "10018.00"
    assert report(r)["net_pnl_by_symbol_usd"] == {"A": "18"}
    assert report(r)["net_pnl_excluding_best_trade_usd"] == "0.00"
    r.marks[-1]["net_liquidation_usd"] = "10019.00"
    with pytest.raises(ValueError, match="reconcile"):
        report(r)


def test_passive_caps_cash_fees_and_sector():
    dates = sessions(date(2024, 1, 5), date(2024, 1, 8))
    data = {
        s: PriceSeries.from_bars(s, [(d, 100, 100, 100, 100, 10000) for d in dates])
        for s in ["A", "B", "C", "D", "E"]
    }
    r = passive_comparator(
        data,
        dict.fromkeys(data, "same"),
        initial_cash=Decimal("10000"),
        cost_model=CostModel(commission_min_per_order=1, slippage_bps=0),
        spread_bps=0,
    )
    assert sum(r["shares_by_symbol"].values()) == 19
    assert Decimal(r["cash_after_entry_usd"]) >= 8000
    assert r["final_cash_usd"] == "9990.00"
    assert r["modeled_costs_usd"] == "10.00"


def test_passive_total_initial_budget_is_capped():
    dates = sessions(date(2024, 1, 5), date(2024, 1, 8))
    data = {
        str(i): PriceSeries.from_bars(str(i), [(d, 100, 100, 100, 100, 10000) for d in dates])
        for i in range(25)
    }
    r = passive_comparator(
        data,
        {s: s for s in data},
        initial_cash=Decimal("10000"),
        cost_model=CostModel(slippage_bps=0),
        spread_bps=0,
    )
    assert r["cash_after_entry_usd"] == "4000.00"
    assert sum(r["shares_by_symbol"].values()) == 60


def test_terminal_open_position_cannot_be_reported_as_closed_cash():
    r = cash_result()
    r.marks[-1]["open_positions"] = 1
    with pytest.raises(ValueError, match="Terminal liquidation"):
        report(r)
