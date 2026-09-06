"""Common types for baseline strategies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from signalforge.backtest.engine import EntrySignal, SignalFn
from signalforge.data.series import PriceSeries
from signalforge.research.regime import NEUTRAL, RegimeState
from signalforge.research.registry import StrategySpec


@dataclass(frozen=True, slots=True)
class StrategyContext:
    regime: RegimeState
    allow_short: bool = False


class BaselineStrategy(Protocol):
    key: str

    def spec(self) -> StrategySpec: ...

    def evaluate(self, series: PriceSeries, t: int, ctx: StrategyContext) -> EntrySignal | None: ...


def signal_fn_for(
    strategy: BaselineStrategy,
    *,
    regime_by_date: dict[date, RegimeState] | None = None,
    allow_short: bool = False,
) -> SignalFn:
    """Adapt a strategy to the engine's ``(series, t) -> EntrySignal | None`` shape."""
    regimes = regime_by_date or {}

    def _fn(series: PriceSeries, t: int) -> EntrySignal | None:
        regime = regimes.get(series.dates[t], NEUTRAL)
        return strategy.evaluate(series, t, StrategyContext(regime=regime, allow_short=allow_short))

    return _fn
