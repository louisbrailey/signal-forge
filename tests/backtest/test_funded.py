from datetime import date
from decimal import Decimal

import pytest

from signalforge.backtest.costs import CostModel
from signalforge.backtest.engine import EntrySignal
from signalforge.backtest.funded import run_funded_replay
from signalforge.config.research import RiskLimits
from signalforge.data.calendar import sessions
from signalforge.data.series import PriceSeries
from signalforge.domain import Direction


def bars(symbol="A"):
    return PriceSeries.from_bars(
        symbol,
        [(d, 100, 101, 99, 100, 100000) for d in sessions(date(2024, 1, 2), date(2024, 1, 10))],
    )


def signal(series, t):
    assert len(series) == t + 1
    return EntrySignal(Direction.LONG, 95, 20, 120) if t == 0 else None


def run(data, **kw):
    return run_funded_replay(
        data,
        dict.fromkeys(data, signal),
        {s: s for s in data},
        limits=kw.pop("limits", RiskLimits()),
        warmup=0,
        **kw,
    )


def test_next_open_shared_cash_and_simultaneous_exposure():
    data = {f"S{i:02}": bars(f"S{i:02}") for i in range(25)}
    # A $2.50 stop keeps 20 five-share positions (2.5%) inside the 3% open-risk
    # hard maximum, so shared cash is what rejects the last five.
    result = run_funded_replay(
        data,
        dict.fromkeys(
            data, lambda s, t: EntrySignal(Direction.LONG, 97.5, 20, 120) if t == 0 else None
        ),
        {s: s for s in data},
        limits=RiskLimits(max_portfolio_exposure_pct=100, max_daily_portfolio_risk_pct=100),
        warmup=0,
        cost_model=CostModel(slippage_bps=0),
        spread_bps=0,
    )
    buys = [f for f in result.fills if f["side"] == "buy"]
    assert len(buys) == 20
    assert all(f["day"] == "2024-01-03" for f in buys)
    assert len([d for d in result.decisions if d["status"] == "rejected"]) == 5
    assert all(Decimal(m["cash_usd"]) >= 0 for m in result.marks)
    assert result.marks[-1]["net_liquidation_usd"] == "10000.00"


def test_fees_and_spread_charged_once_each_side():
    r = run(
        {"A": bars()},
        cost_model=CostModel(commission_min_per_order=1, slippage_bps=10),
        spread_bps=20,
    )
    buy, sell = r.fills
    assert buy["price"] == "100.20" and sell["price"] == "99.80"
    n = buy["shares"]
    assert Decimal(r.marks[-1]["net_liquidation_usd"]) == Decimal("10000") - Decimal("0.40") * n - 2
    assert r.costs == Decimal("0.40") * n + 2


def test_sector_and_combined_open_risk():
    data = {s: bars(s) for s in ("A", "B")}
    r = run(
        data,
        limits=RiskLimits(max_daily_portfolio_risk_pct=0.3),
        spread_bps=0,
        cost_model=CostModel(slippage_bps=0),
    )
    assert len([f for f in r.fills if f["side"] == "buy"]) == 1
    r = run_funded_replay(
        data,
        dict.fromkeys(data, signal),
        dict.fromkeys(data, "same"),
        limits=RiskLimits(max_correlated_exposure_pct=5),
        warmup=0,
        spread_bps=0,
        cost_model=CostModel(slippage_bps=0),
    )
    assert len([f for f in r.fills if f["side"] == "buy"]) == 1


def test_gaps_and_same_bar_stop_priority():
    b = bars()
    b.low[2] = 80
    b.open[2] = 85
    b.close[2] = 90
    r = run({"A": b}, spread_bps=0, cost_model=CostModel(slippage_bps=0))
    assert r.fills[-1]["reason"] == "gap_stop" and r.fills[-1]["price"] == "85.00"
    b = bars()
    b.low[1] = 90
    b.high[1] = 130
    r = run({"A": b}, spread_bps=0, cost_model=CostModel(slippage_bps=0))
    assert r.fills[-1]["reason"] == "stop"


def test_missing_calendar_and_invalid_numeric_fail():
    b = bars()
    with pytest.raises(ValueError, match="sessions"):
        run(
            {
                "A": PriceSeries.from_bars(
                    "A", [(b.dates[0], 100, 101, 99, 100, 1), (b.dates[2], 100, 101, 99, 100, 1)]
                )
            }
        )
    b = bars()
    b.close[2] = float("nan")
    with pytest.raises(ValueError, match="OHLCV"):
        run({"A": b})


def test_future_change_cannot_change_earlier_admissions():
    a = bars()
    r = run({"A": a})
    b = bars()
    b.high[-1] = 200
    b.close[-1] = 150
    altered = run({"A": b})
    assert r.decisions == altered.decisions
    assert r.fills[0] == altered.fills[0]


def test_empty_signals_leave_cash_and_reproducible():
    b = bars()
    args = ({"A": b}, {"A": lambda s, t: None}, {"A": "sector"})
    first = run_funded_replay(*args, limits=RiskLimits(), warmup=0)
    assert first == run_funded_replay(*args, limits=RiskLimits(), warmup=0)
    assert not first.fills
    assert all(m["net_liquidation_usd"] == "10000.00" for m in first.marks)
