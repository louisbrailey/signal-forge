"""Common types for baseline strategies."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol, runtime_checkable

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


@runtime_checkable
class DeclaresSensitivityAxes(Protocol):
    """OPTIONAL, and deliberately separate from :class:`BaselineStrategy`.

    A strategy may declare extra parameter axes for gate 5 to perturb, so a
    version whose whole point is a new parameter cannot pass a sensitivity
    gate that never varied it (MAP §0.5: the decisive new parameter of a
    v0.2.0 is exactly the one gate 5 will not test unless it is added).
    ``research.promotion._sensitivity_plan`` picks this up via ``getattr``
    and merges it into the family grid.

    It lives on the strategy CLASS and must NEVER become a ``StrategySpec``
    field: ``persistence.spec_json_hash`` hashes every spec field except
    git_sha/status/notes, so adding one would change the hash of every
    strategy — including the two whose approvals are scoped by their current
    hashes, which would put them permanently out of scope."""

    def sensitivity_axes(self) -> Mapping[str, Sequence[float | int]]: ...


def signal_fn_for(
    strategy: BaselineStrategy,
    *,
    regime_by_date: dict[date, RegimeState] | None = None,
    allow_short: bool = False,
) -> SignalFn:
    """Adapt a strategy to the engine's ``(series, t) -> EntrySignal | None`` shape."""
    regimes = regime_by_date or {}

    def _fn(series: PriceSeries, t: int) -> EntrySignal | None:
        stamp = series.dates[t]
        key = stamp.date() if isinstance(stamp, datetime) else stamp
        regime = regimes.get(key, NEUTRAL)
        return strategy.evaluate(series, t, StrategyContext(regime=regime, allow_short=allow_short))

    return _fn
