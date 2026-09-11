"""Strategy 5 (Phase 2) — intraday opening-range breakout (INTRADAY horizon).

After the first ``or_bars`` bars of the regular session define the opening range,
enter on a bar close beyond it, stop at the opposite edge, target a multiple of
the range, and force a time stop well before the close. Regime-gated on the daily
market regime (a coarse risk-on/off filter — the regime does not flip intraday).

v0.2.0 — the regime read is LAGGED (the one behavioural change)
---------------------------------------------------------------
v0.1.0 gated an entry inside session *D* on the regime label derived from *D*'s
**own daily close** (``backtest_runner`` builds ``regime_lookup(proxy)`` keyed by
session date, and ``strategies.base`` normalised an intraday stamp to its own
session date). For a 10:15 entry that is future information, and it is invisible
to ``assert_no_lookahead`` because it lives in the plumbing rather than in a
feature. v0.2.0 reads the label derived from session **D-1**'s daily close
instead, via ``ORBParams.regime_lag_sessions`` (>= 1, enforced).

That is a behavioural change, so it ships as ``VERSION = "0.2.0"`` (map rules
R3/R7): a new ``StrategyVersion`` row, hence a never-before-sealed gate 9. No
promotion evaluation of v0.1.0 is admissible (design §7, falsifier F8).

Degenerate / identity relationships of the parameters (stated in advance, so a
gate-5 grid cannot silently test nothing — design §6):

* ``regime_lag_sessions = 0`` is the **identity with v0.1.0**: it restores the
  same-session read, i.e. the lookahead. It is rejected in ``__post_init__`` and
  is deliberately NOT a grid value — an axis that can be tuned back onto future
  information is not a robustness axis.
* ``regime_lag_sessions >= 1`` moves which sessions are tradeable, so it moves
  ``n_trades`` AND expectancy. Values large enough to run off the front of the
  proxy history degenerate to ``NEUTRAL`` (risk-on), i.e. to "no regime gate".
* ``or_bars`` is definitional: it sets the opening range *and*, through the
  ``26 + or_bars`` guard below, the entry window — so it must move ``n_trades``.
  ``or_bars >= 26`` is degenerate (the range never completes inside an RTH
  session at 15m, so ``opening_range`` returns NaN and the strategy is silent).
* ``target_range_mult`` appears only in the exit target: it cannot change which
  bars trigger, so ``n_trades`` is INVARIANT along that axis by construction and
  only ``expectancy_r`` may move. A grid whose ``expectancy_r`` is also flat
  along it has tested nothing (``sensitivity.axis_moved`` reports this).
* ``min_bars_before_entry > max_bars_after_open`` is degenerate (empty entry
  window, no trades). These two and ``time_stop_bars`` are NOT grid axes —
  declared coverage is 3 of 6 fields, not hidden.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from signalforge.backtest.engine import EntrySignal
from signalforge.data.series import PriceSeries
from signalforge.domain import Direction, Horizon
from signalforge.gitinfo import git_sha
from signalforge.research.features.intraday import (
    bars_since_open,
    opening_range,
    session_bar_count,
)
from signalforge.research.registry import StrategySpec, StrategyStatus
from signalforge.research.strategies.base import StrategyContext

VERSION = "0.2.0"


@dataclass(frozen=True, slots=True)
class ORBParams:
    or_bars: int = 3  # bars that define the opening range
    min_bars_before_entry: int = 3
    max_bars_after_open: int = 20  # do not initiate late in the session
    target_range_mult: float = 1.5
    time_stop_bars: int = 12
    # v0.2.0: completed daily sessions between the regime label read and the
    # session being traded. 1 = "the label from yesterday's close", the newest
    # label an intraday entry could actually have had. 0 would be v0.1.0's
    # lookahead and is rejected rather than merely discouraged.
    regime_lag_sessions: int = 1

    def __post_init__(self) -> None:
        if self.regime_lag_sessions < 1:
            raise ValueError(
                "regime_lag_sessions must be >= 1: an intraday entry inside session D may "
                "not read the regime derived from D's own daily close (that is the v0.1.0 "
                "lookahead this version exists to remove)"
            )


class IntradayORB:
    horizon = Horizon.INTRADAY
    key = "intraday_orb.intraday"

    def __init__(self, params: ORBParams | None = None) -> None:
        self.params = params or ORBParams()

    @property
    def regime_lag_sessions(self) -> int:
        """Read by ``strategies.base.signal_fn_for`` (and the live scan path) to
        lag ``ctx.regime`` by whole completed daily sessions. See the module
        docstring: this is v0.2.0's whole behavioural change."""
        return self.params.regime_lag_sessions

    def sensitivity_axes(self) -> Mapping[str, Sequence[float | int]]:
        """Gate-5 axes this version DECLARES on top of its family grid
        (``strategies.base.DeclaresSensitivityAxes``).

        ``regime_lag_sessions`` is the parameter v0.2.0 introduces, so map rule
        §4.2/6 requires it to be a pre-registered axis rather than the one knob
        gate 5 never varies. The values are ``[1, 2]``: 1 is the shipped
        baseline and 2 is the one-step neighbour. **0 is deliberately absent** —
        it is the identity with v0.1.0's lookahead (module docstring), and a
        grid that can reach it would let gate 5 be passed by reading the
        future. Pre-registered here, before any intraday bar exists."""
        return {"regime_lag_sessions": [1, 2]}

    def spec(self) -> StrategySpec:
        p = self.params
        return StrategySpec(
            name=self.key,
            version=VERSION,
            git_sha=git_sha(),
            horizon=self.horizon,
            rule_definition=(
                f"After the first {p.or_bars} RTH bars set the opening range (OR). "
                f"LONG when a bar closes above OR high (SHORT below OR low, if enabled) between "
                f"bar {p.min_bars_before_entry} and {p.max_bars_after_open} of the session, "
                f"and the daily regime — read from the close {p.regime_lag_sessions} completed "
                "session(s) BEFORE the session being traded, never from its own close — is not "
                "risk-off. Stop at the opposite OR edge; target "
                f"{p.target_range_mult}x the OR width; time stop {p.time_stop_bars} bars."
            ),
            required_data_sources=("BAR_INTRADAY", "BAR_DAILY"),
            feature_definitions=(
                f"opening_range(k={p.or_bars})",
                "bars_since_open",
                "session_bar_count",
                f"regime_lookup(proxy) lagged {p.regime_lag_sessions} session(s)",
            ),
            entry_conditions=(
                "close beyond the OR within the entry window + lagged (D-"
                f"{p.regime_lag_sessions}) daily regime gate"
            ),
            invalidation_conditions="close back inside the opening range",
            exit_logic=f"target = entry +/- {p.target_range_mult} * OR width",
            stop_logic="stop = opposite opening-range edge",
            time_stop=f"{p.time_stop_bars} bars (well before the close)",
            liquidity_requirements="daily ADDV / price / spread from ResearchConfig.liquidity",
            event_filters="excluded earnings window from ResearchConfig.events",
            assumed_transaction_costs="ResearchConfig commission model (default 0)",
            slippage_model="ResearchConfig slippage_bps + half spread (intraday spreads are wider)",
            permits_long=True,
            permits_short=True,
            known_failure_modes=(
                "chop around the OR edge on a rangebound day",
                "gap-and-fade after the open",
                "thin liquidity in the first bars widening the effective spread",
            ),
            test_date_range="set per backtest run (intraday bars)",
            in_sample_period="first 60% of the intraday sessions tested",
            out_of_sample_period="last 40% of the intraday sessions tested",
            walkforward_result_ref=f"reports/{self.key}-{VERSION}.md",
            status=StrategyStatus.EXPERIMENTAL,
        )

    def evaluate(self, series: PriceSeries, t: int, ctx: StrategyContext) -> EntrySignal | None:
        p = self.params
        or_hi, or_lo = opening_range(series, t, p.or_bars)
        if math.isnan(or_hi) or or_hi <= or_lo:
            return None
        since_open = bars_since_open(series, t)
        if not (p.min_bars_before_entry <= since_open <= p.max_bars_after_open):
            return None
        # keep enough room before the close for the time stop
        if session_bar_count(series, t) + p.time_stop_bars > 26 + p.or_bars:
            return None

        close = float(series.close[t])
        width = or_hi - or_lo
        if width <= 0:
            return None

        if close > or_hi and not ctx.regime.risk_off:
            return EntrySignal(
                direction=Direction.LONG,
                stop_price=or_lo,
                target_price=close + p.target_range_mult * width,
                time_stop_bars=p.time_stop_bars,
                reason=(
                    f"close {close:.2f} > OR high {or_hi:.2f} (width {width:.2f}); "
                    f"bar {since_open} of session; regime {ctx.regime.trend.value}"
                ),
            )
        if ctx.allow_short and close < or_lo and ctx.regime.risk_off:
            return EntrySignal(
                direction=Direction.SHORT,
                stop_price=or_hi,
                target_price=close - p.target_range_mult * width,
                time_stop_bars=p.time_stop_bars,
                reason=(
                    f"close {close:.2f} < OR low {or_lo:.2f} (width {width:.2f}); "
                    f"bar {since_open}; regime risk-off"
                ),
            )
        return None
