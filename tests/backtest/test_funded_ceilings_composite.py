from datetime import date
from decimal import Decimal

import pytest

from signalforge.backtest.costs import CostModel
from signalforge.backtest.engine import EntrySignal
from signalforge.backtest.funded import (
    AttributedEntrySignal,
    composite_signal_fn,
    run_funded_replay,
)
from signalforge.config.research import RiskLimits
from signalforge.data.calendar import sessions
from signalforge.data.series import PriceSeries
from signalforge.domain import Direction
from signalforge.paper.ledger import HARD_MAX_SECTOR_PCT, HARD_MAX_SYMBOL_PCT

FREE = CostModel(slippage_bps=0)


def bars(symbol="A"):
    return PriceSeries.from_bars(
        symbol,
        [(d, 100, 101, 99, 100, 100000) for d in sessions(date(2024, 1, 2), date(2024, 1, 10))],
    )


def fires(stop=95.0, target=120.0, direction=Direction.LONG):
    def fn(series, t):
        return EntrySignal(direction, stop, 20, target, f"stop {stop}") if t == 0 else None

    return fn


def never(series, t):
    return None


def run(data, signals=None, sectors=None, limits=None, **kw):
    return run_funded_replay(
        data,
        signals or dict.fromkeys(data, fires()),
        sectors or {s: s for s in data},
        limits=limits
        or RiskLimits(max_portfolio_exposure_pct=100, max_daily_portfolio_risk_pct=100),
        warmup=0,
        cost_model=FREE,
        spread_bps=0,
        **kw,
    )


def buys(result):
    return [f for f in result.fills if f["side"] == "buy"]


def test_default_position_ceiling_unchanged_at_five_percent():
    data = {f"S{i:02}": bars(f"S{i:02}") for i in range(25)}
    r = run(data)
    # 0.5% risk / $5 stop distance allows 10 shares; the 5% default ceiling binds at 5.
    assert len(buys(r)) == 20 and {f["shares"] for f in buys(r)} == {5}
    assert all("strategy" not in f for f in r.fills)
    assert all("strategy" not in d for d in r.decisions)


def test_position_ceiling_parameter_widens_up_to_paper_maximum():
    data = {f"S{i:02}": bars(f"S{i:02}") for i in range(25)}
    r = run(data, max_position_ceiling_pct=HARD_MAX_SYMBOL_PCT)
    assert len(buys(r)) == 10 and {f["shares"] for f in buys(r)} == {10}
    # Stricter caller limits remain effective under a wider ceiling.
    r = run(
        data,
        limits=RiskLimits(
            max_position_concentration_pct=3,
            max_portfolio_exposure_pct=100,
            max_daily_portfolio_risk_pct=100,
        ),
        max_position_ceiling_pct=HARD_MAX_SYMBOL_PCT,
    )
    assert {f["shares"] for f in buys(r)} == {3}


@pytest.mark.parametrize(
    "kw",
    [
        {"max_position_ceiling_pct": HARD_MAX_SYMBOL_PCT + 0.01},
        {"max_position_ceiling_pct": 0.0},
        {"max_position_ceiling_pct": float("nan")},
        {"max_sector_ceiling_pct": HARD_MAX_SECTOR_PCT + 1},
        {"max_gross_ceiling_pct": 100.5},
        {"max_gross_ceiling_pct": -1.0},
    ],
)
def test_ceilings_cannot_exceed_paper_ledger_maxima(kw):
    with pytest.raises(ValueError, match="paper ledger hard maximum"):
        run({"A": bars()}, **kw)


def test_sector_and_gross_ceilings_are_honoured():
    data = {f"S{i:02}": bars(f"S{i:02}") for i in range(25)}
    same = dict.fromkeys(data, "tech")
    limits = RiskLimits(
        max_correlated_exposure_pct=25,
        max_portfolio_exposure_pct=100,
        max_daily_portfolio_risk_pct=100,
    )
    assert len(buys(run(data, sectors=same, limits=limits))) == 4  # default 20% sector ceiling
    assert len(buys(run(data, sectors=same, limits=limits, max_sector_ceiling_pct=10))) == 2
    assert len(buys(run(data, max_gross_ceiling_pct=50))) == 10


def test_composite_first_listed_strategy_wins():
    data = {"A": bars()}
    ab = composite_signal_fn([("a", fires(95)), ("b", fires(90))])
    r = run(data, {"A": ab})
    assert buys(r)[0]["strategy"] == "a" and buys(r)[0]["signal_reason"] == "stop 95"
    assert r.open_lots == {} and r.fills[-1]["strategy"] == "a"
    ba = composite_signal_fn([("b", fires(90)), ("a", fires(95))])
    assert buys(run(data, {"A": ba}))[0]["strategy"] == "b"


def test_composite_falls_through_and_short_never_blocks_a_long():
    sig = composite_signal_fn(
        [("none", never), ("short", fires(105, None, Direction.SHORT)), ("long", fires())]
    )(bars(), 0)
    assert isinstance(sig, AttributedEntrySignal) and sig.strategy == "long"
    assert composite_signal_fn([("none", never)])(bars(), 0) is None


def test_composite_rejects_duplicate_or_empty_keys():
    with pytest.raises(ValueError):
        composite_signal_fn([("a", never), ("a", fires())])
    with pytest.raises(ValueError):
        composite_signal_fn([])
    with pytest.raises(ValueError):
        composite_signal_fn([("", never)])


def test_attribution_carried_on_fills_and_decisions():
    data = {s: bars(s) for s in ("A", "B", "C")}
    signals = {
        "A": composite_signal_fn([("x", fires()), ("y", fires(90))]),
        "B": composite_signal_fn([("x", never), ("y", fires(90))]),
        # Crossed stop: rejected at admission, the rejection is still attributed.
        "C": composite_signal_fn([("x", fires(150, None))]),
    }
    r = run(data, signals)
    by_symbol = {(f["symbol"], f["side"]): f["strategy"] for f in r.fills}
    assert by_symbol == {
        ("A", "buy"): "x",
        ("A", "sell"): "x",
        ("B", "buy"): "y",
        ("B", "sell"): "y",
    }
    rejected = [d for d in r.decisions if d["status"] == "rejected"]
    assert [(d["symbol"], d["reason"], d["strategy"]) for d in rejected] == [
        ("C", "invalid_or_crossed_stop", "x")
    ]
    accepted = {d["symbol"]: d["strategy"] for d in r.decisions if d["status"] == "accepted"}
    assert accepted == {"A": "x", "B": "y"}
    assert sum(Decimal(f["realized_pnl_usd"]) for f in r.fills if f["side"] == "sell") == 0
