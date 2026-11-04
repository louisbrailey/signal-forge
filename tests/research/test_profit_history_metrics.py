"""Historical risk-dollar illustrations use the requested calendar denominator."""

import importlib.util
from datetime import date
from pathlib import Path
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location(
    "profit_history", Path(__file__).parents[2] / "scripts/profit_backtest_full_history.py"
)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_requested_history_includes_idle_time_and_is_not_a_portfolio_forecast() -> None:
    trade = SimpleNamespace(entry_date=date(2020, 11, 1), exit_date=date(2020, 12, 1), pnl_r=12)
    result = module.stats([trade], {"100": 100}, date(2020, 1, 1), date(2021, 1, 1))
    assert result["usd_per_month@100"] == 100
    assert result["forecast"] is False
    assert result["portfolio_constraints_applied"] is False
    assert result["span"] == "2020-01-01..2021-01-01"


def test_trade_span_uses_earliest_entry_even_when_that_trade_exits_later() -> None:
    trades = [
        SimpleNamespace(entry_date=date(2020, 1, 1), exit_date=date(2021, 1, 1), pnl_r=2),
        SimpleNamespace(entry_date=date(2020, 8, 1), exit_date=date(2020, 9, 1), pnl_r=-1),
    ]
    result = module.stats(trades, {"100": 100})
    assert result["span"] == "2020-01-01..2021-01-01"
    assert result["max_dd_r"] == 1
