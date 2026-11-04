import importlib
from datetime import date
from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest

from signalforge.backtest.costs import CostModel
from signalforge.data.calendar import sessions
from signalforge.data.series import PriceSeries
from signalforge.research.action_replay import ActionDataset
from signalforge.research.slow_trend import SlowTrendParams


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    return importlib.import_module("slow_trend_report")


def test_paired_blocks_are_deterministic_aligned_and_do_not_claim_unpaired_evidence(runner):
    candidate = {str(i): 0.002 for i in range(12)}
    simpler = {str(i): 0.001 for i in range(12)}
    result = runner.paired_interval(candidate, simpler)
    assert result == runner.paired_interval(candidate, simpler)
    assert result["ci95_pct"] == pytest.approx([0.1, 0.1])
    with pytest.raises(ValueError):
        runner.paired_interval(candidate, {"different": 0})


def test_new_signal_uses_funded_next_open_risk_and_costs(runner):
    dates = sessions(date(2020, 1, 2), date(2022, 1, 31))
    close = np.linspace(100, 150, len(dates))
    b = PriceSeries("SPY", dates, close, close + 1, close - 1, close, close * 1e6)
    data = ActionDataset({"SPY": b}, (), (), (), "fixture-not-performance", dates[0], dates[-1])
    metadata = {"SPY": {"sector": "broad", "instrument_type": "etf"}}
    result = runner.replay(
        data,
        metadata,
        date(2021, 1, 1),
        CostModel(commission_min_per_order=1, slippage_bps=10),
        10,
        SlowTrendParams(),
    )
    assert result.fills and result.costs > 0
    for fill in result.fills:
        if fill["side"] == "buy":
            assert fill["day"] > fill["signal_day"]
            assert Decimal(fill["shares"]) * Decimal(fill["price"]) <= Decimal(510)
    assert all(Decimal(m["cash_usd"]) >= 0 for m in result.marks)
    assert result == runner.replay(
        data,
        metadata,
        date(2021, 1, 1),
        CostModel(commission_min_per_order=1, slippage_bps=10),
        10,
        SlowTrendParams(),
    )
