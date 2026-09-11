"""Common types for baseline strategies."""

from __future__ import annotations

from bisect import bisect_left
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


def declared_regime_lag_sessions(strategy: BaselineStrategy) -> int:
    """How many completed daily sessions back a strategy's regime read must be
    lagged. ``0`` (the default for every strategy that declares nothing) means
    "the label of the session the bar belongs to".

    Why this exists, and why it lives on the strategy CLASS rather than in the
    plumbing: ``regime_lookup`` labels a session from **that session's own
    daily bar**, whose close is not known while the session is still being
    traded. For a DAILY strategy that is harmless — the signal fires at bar
    *t*'s close and fills at *t+1*'s open, so the label is strictly past. For
    an INTRADAY strategy trading inside session *D* it is a genuine lookahead:
    a 10:15 entry would be gated on *D*'s 16:00 close.
    ``backtest.leakage.assert_no_lookahead`` cannot see it, because it lives in
    the ``regime_by_date`` plumbing and not in any feature function.

    Reading it off the strategy (rather than switching on ``intraday=``
    anywhere in the runner) keeps the fix tied to a strategy VERSION: the lag
    is part of what ``intraday_orb`` v0.2.0 *is*, it shows up in its
    ``StrategySpec``, and every other strategy's behaviour is byte-identical
    because ``getattr`` returns the 0 default."""
    return max(0, int(getattr(strategy, "regime_lag_sessions", 0) or 0))


def lagged_regime(regimes: Mapping[date, RegimeState], as_of: date, lag: int) -> RegimeState:
    """The regime label in force ``lag`` completed sessions before ``as_of``.

    ``lag=0`` is ``regimes.get(as_of, NEUTRAL)`` — the same-session read.
    ``lag=1`` is the label derived from the most recent daily close STRICTLY
    BEFORE ``as_of``, which is the newest information an intraday entry inside
    ``as_of`` could actually have had. ``as_of`` itself need not be present in
    ``regimes`` (an intraday session whose daily bar is not ingested yet still
    resolves to the previous session's label).

    Falls back to ``NEUTRAL`` when the history does not reach back far enough —
    the same fallback the unlagged path uses for an unlabelled date."""
    if lag <= 0:
        return regimes.get(as_of, NEUTRAL)
    ordered = sorted(regimes)
    i = bisect_left(ordered, as_of) - lag
    return regimes[ordered[i]] if i >= 0 else NEUTRAL


def signal_fn_for(
    strategy: BaselineStrategy,
    *,
    regime_by_date: dict[date, RegimeState] | None = None,
    allow_short: bool = False,
) -> SignalFn:
    """Adapt a strategy to the engine's ``(series, t) -> EntrySignal | None`` shape."""
    regimes = regime_by_date or {}
    lag = declared_regime_lag_sessions(strategy)

    if lag == 0:

        def _fn(series: PriceSeries, t: int) -> EntrySignal | None:
            stamp = series.dates[t]
            key = stamp.date() if isinstance(stamp, datetime) else stamp
            regime = regimes.get(key, NEUTRAL)
            return strategy.evaluate(
                series, t, StrategyContext(regime=regime, allow_short=allow_short)
            )

        return _fn

    # Sorted once per run, not per bar: the lookup is the hot path of an
    # intraday backtest (tens of thousands of bars per symbol).
    ordered = sorted(regimes)

    def _lagged_fn(series: PriceSeries, t: int) -> EntrySignal | None:
        stamp = series.dates[t]
        key = stamp.date() if isinstance(stamp, datetime) else stamp
        i = bisect_left(ordered, key) - lag
        regime = regimes[ordered[i]] if i >= 0 else NEUTRAL
        return strategy.evaluate(series, t, StrategyContext(regime=regime, allow_short=allow_short))

    return _lagged_fn
