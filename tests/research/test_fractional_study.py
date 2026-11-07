import importlib
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from signalforge.backtest.costs import CostModel
from signalforge.backtest.engine import EntrySignal
from signalforge.backtest.funded import run_funded_replay
from signalforge.config.research import RiskLimits
from signalforge.data.calendar import sessions
from signalforge.data.series import PriceSeries
from signalforge.domain import Direction

DATES = sessions(date(2024, 1, 2), date(2024, 1, 5))


@pytest.fixture
def study(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[2] / "scripts"))
    return importlib.import_module("fractional_study")


def prices(symbol, opens, *, first_volume=1_000_000):
    return PriceSeries.from_bars(
        symbol,
        [
            (day, price, price, price, price, first_volume if index == 0 else 1_000_000)
            for index, (day, price) in enumerate(zip(DATES, opens, strict=True))
        ],
    )


def first_close(series, index):
    assert len(series) == index + 1
    return EntrySignal(Direction.LONG, 550, 20, 800) if index == 0 else None


def replay(engine, bars, *, limits=None, costs=None, signal=first_close, **kwargs):
    return engine(
        bars,
        dict.fromkeys(bars, signal),
        dict.fromkeys(bars, "broad"),
        limits=limits or RiskLimits(max_position_concentration_pct=5),
        cost_model=costs or CostModel(slippage_bps=0),
        spread_bps=0,
        warmup=0,
        **kwargs,
    )


def test_fractional_affordability_uses_next_open_without_changing_whole_engine(study):
    data = {"SPY": prices("SPY", [600] * 4)}
    engine, _ = study.load_fractional_engine()
    whole = replay(run_funded_replay, data)
    fraction = replay(engine, data)
    assert not whole.fills
    assert whole.decisions[0]["reason"] == "position concentration cap below one share"
    buy, sell = fraction.fills
    assert buy["shares"] == sell["shares"] == Decimal("0.833")
    assert (buy["signal_day"], buy["day"]) == (str(DATES[0]), str(DATES[1]))
    assert fraction.marks[1]["cash_usd"] == "9500.20"
    assert fraction.marks[-1]["net_liquidation_usd"] == "10000.00"
    audit = study.audit_entries(vars(fraction))
    assert audit == {"verified_entries": 1, "max_entry_equity_fraction": "0.04998"}


def test_fractional_settlement_and_per_order_fees_reconcile(study):
    data = {"SPY": prices("SPY", [600.03] * 4)}
    engine, _ = study.load_fractional_engine()
    book = replay(engine, data, costs=CostModel(slippage_bps=0, commission_min_per_order=1))
    buy, sell = book.fills
    assert buy["shares"] == sell["shares"] == Decimal("0.833")
    assert buy["commission"] == sell["commission"] == "1.00"
    assert book.marks[1]["cash_usd"] == "9499.17"
    assert sell["realized_pnl_usd"] == "-2.01"
    assert book.marks[-1]["net_liquidation_usd"] == "9997.99"
    assert book.costs == Decimal("2.01")


def test_fractional_split_and_dividend_accounting(study):
    from signalforge.backtest.actions import Dividend, Split

    data = {"SPY": prices("SPY", [600, 600, 1200, 1200])}
    engine, _ = study.load_fractional_engine()
    book = replay(
        engine,
        data,
        splits=(Split("SPY", DATES[2], Decimal("0.5"), "test"),),
        dividends=(Dividend("SPY", DATES[2], DATES[3], Decimal(1), "test"),),
    )
    assert book.fills[-1]["shares"] == Decimal("0.4165")
    assert book.fills[-1]["realized_pnl_usd"] == "0.00"
    assert book.marks[2]["dividend_receivable_usd"] == "0.42"
    assert book.marks[-1]["net_liquidation_usd"] == "10000.42"


@pytest.mark.parametrize(
    ("limit", "reason"),
    [
        ({"max_correlated_exposure_pct": 5}, "sector_exposure_cap"),
        ({"max_portfolio_exposure_pct": 6}, "portfolio_exposure_cap"),
        ({"max_daily_portfolio_risk_pct": 0.5}, "aggregate_risk_cap"),
    ],
)
def test_fractional_entry_uses_prior_volume_and_concurrent_limits(study, limit, reason):
    engine, _ = study.load_fractional_engine()
    data = {symbol: prices(symbol, [600] * 4, first_volume=25) for symbol in ("A", "B")}
    book = replay(engine, data, limits=RiskLimits(**limit))
    buys = [fill for fill in book.fills if fill["side"] == "buy"]
    assert [(fill["symbol"], fill["shares"]) for fill in buys] == [("A", Decimal("0.250"))]
    assert any(decision["reason"] == reason for decision in book.decisions)


def test_stop_budget_includes_round_trip_commission_and_rounding(study):
    lots = study.fractional_lots
    costs = CostModel(commission_min_per_order=1)
    quantity, rejection = lots.size_fractional(
        fill=Decimal(500),
        stop=Decimal(450),
        stop_fill=Decimal(450),
        equity=Decimal(10000),
        cash=Decimal(10000),
        gross=Decimal(0),
        sector=Decimal(0),
        open_risk=Decimal(0),
        volume_cap=Decimal(10000),
        limits=RiskLimits(max_position_concentration_pct=5),
        costs=costs,
    )
    assert rejection is None
    assert quantity == Decimal("0.959")
    assert lots.stop_risk(Decimal(500), Decimal(450), quantity, Decimal(2)) <= 50


def test_fractional_drawdown_halts_entries_but_gap_stop_closes(study):
    engine, _ = study.load_fractional_engine()
    data = {"SPY": prices("SPY", [600, 600, 400, 600])}
    book = replay(
        engine,
        data,
        max_drawdown_pct=0.1,
        signal=lambda bars, index: EntrySignal(Direction.LONG, 550, 20, 800),
    )
    assert [fill["side"] for fill in book.fills] == ["buy", "sell"]
    assert book.fills[-1]["reason"] == "gap_stop"
    assert book.fills[-1]["price"] == "400.00"
    assert book.decisions[-1]["reason"] == "portfolio_drawdown_halt"


def test_fractional_checkpoint_keeps_decimal_quantity_and_refuses_overwrite(study, tmp_path):
    job = ("simple_spy", "2025", "stress")
    case = {"key": job[0], "period": job[1], "cost_case": job[2], "shares": Decimal("0.833")}
    path = study.case_path(tmp_path, job)
    study.save_case(path, job, case)
    assert study.r1.load_record(path, job)["shares"] == "0.833"
    with pytest.raises(ValueError, match="Immutable record conflict"):
        study.save_case(path, job, case | {"shares": Decimal("0.834")})
