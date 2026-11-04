"""CRYPTO-4 (round 2, PREREGISTRATION_round2_2026-11-03.md §1 R2-E1): the 52-week-high
anchor on daily crypto — fires only on a close above the prior 252-day high, long only,
causal, registered under its own version for the sealed-test ledger."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from signalforge.data.series import PriceSeries
from signalforge.domain import Direction
from signalforge.research.fx import sealed
from signalforge.research.fx.harness import CRYPTO4_MARKET
from signalforge.research.fx.strategies import CRYPTO4_STRATEGIES


def _series(closes: np.ndarray) -> PriceSeries:
    days = [date(2019, 1, 1) + timedelta(days=i) for i in range(len(closes))]
    rows = [(d, c, c * 1.01, c * 0.99, c, 0.0) for d, c in zip(days, closes, strict=True)]
    return PriceSeries.from_bars("BTCUSD", rows)


def test_high252_fires_only_on_a_close_above_the_prior_252_day_high_long_only() -> None:
    (strat,) = CRYPTO4_STRATEGIES
    assert strat.key == "crypto_high252_u9" and strat.params["channel"] == 252
    rng = np.random.default_rng(5)
    base = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, 400)))
    closes = base.copy()
    closes[-1] = base[:-1].max() * 1.03  # a new high: prior highs are close*1.01 at most
    s = _series(closes)
    sig = strat.signal(s, len(s))
    assert sig is not None and sig.direction is Direction.LONG
    assert sig.time_stop_bars == 40 and sig.stop_price < closes[-1]
    inside = base.copy()
    prior_hi = (base[-253:-1] * 1.01).max()  # the prior 252 bars' highs (high = close * 1.01)
    inside[-1] = prior_hi * 0.99  # below the prior 252-day high: no signal
    assert strat.signal(_series(inside), 400) is None
    crash = base.copy()
    crash[-1] = base[:-1].min() * 0.5  # a new low never shorts
    assert strat.signal(_series(crash), 400) is None


def test_crypto4_has_its_own_version_in_the_sealed_registry() -> None:
    assert CRYPTO4_MARKET.version == "CRYPTO-4"
    mk, strat, _gates = sealed._lookup("crypto", "crypto_high252_u9")
    assert mk.version == "CRYPTO-4" and strat is CRYPTO4_STRATEGIES[0]
