"""Backtest cost model."""

from __future__ import annotations

from signalforge.backtest.costs import CostModel


def test_zero_commission_default() -> None:
    assert CostModel().commission(100) == 0.0


def test_commission_min_per_order_applies() -> None:
    m = CostModel(commission_per_share=0.001, commission_min_per_order=1.0)
    assert m.commission(100) == 1.0  # 0.10 -> floored to min
    assert m.commission(5000) == 5.0  # 5.00 -> above min


def test_slippage_and_half_spread_scale_with_notional() -> None:
    m = CostModel(slippage_bps=10, half_spread_fill_penalty=True)
    assert m.slippage(100.0, 100) == 100.0 * 100 * 0.001
    assert m.spread_cost(100.0, 100, spread_bps=20) == 100.0 * 100 * 0.002 / 2


def test_half_spread_penalty_can_be_disabled() -> None:
    assert CostModel(half_spread_fill_penalty=False).spread_cost(100.0, 100, 20) == 0.0
