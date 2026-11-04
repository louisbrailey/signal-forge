from datetime import date

import pytest

from signalforge.backtest.costs import CostModel
from signalforge.research.backtest_runner import run_strategy_over_universe
from signalforge.research.strategies import TrendContinuation


@pytest.mark.parametrize(
    "costs",
    [
        CostModel(commission_per_share=0.005),
        CostModel(commission_min_per_order=1),
    ],
)
def test_legacy_runner_refuses_unsupported_commissions_before_data_reads(costs):
    class NoReads:
        def scalars(self, *args, **kwargs):
            raise AssertionError("Should refuse before loading market data")

    with pytest.raises(ValueError, match="funded"):
        run_strategy_over_universe(
            NoReads(),
            TrendContinuation(),
            ["SPY"],
            date(2020, 1, 1),
            date(2024, 1, 1),
            cost_model=costs,
        )
