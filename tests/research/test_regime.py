"""Regime filter: trend/vol classification, no look-ahead."""

from __future__ import annotations

from datetime import date, timedelta

from signalforge.data.series import PriceSeries
from signalforge.research.regime import Trend, Vol, regime_from_proxy, regime_lookup


def _series(fn) -> PriceSeries:  # type: ignore[no-untyped-def]
    d = date(2019, 1, 1)
    rows = []
    for i in range(400):
        c = fn(i)
        rows.append((d, c, c * 1.004, c * 0.996, c, 1_000_000.0))
        d += timedelta(days=1)
    return PriceSeries.from_bars("SPY", rows)


def test_steady_uptrend_is_bull() -> None:
    proxy = _series(lambda i: 100.0 * (1.0007**i))
    r = regime_from_proxy(proxy, len(proxy) - 1)
    assert r.trend is Trend.BULL
    assert r.risk_on or r.vol.value == "high"  # bull; vol may be either


def test_steady_downtrend_is_bear() -> None:
    proxy = _series(lambda i: 200.0 * (0.9990**i))
    r = regime_from_proxy(proxy, len(proxy) - 1)
    assert r.trend is Trend.BEAR
    assert r.risk_off


def test_short_history_is_neutral() -> None:
    proxy = _series(lambda i: 100.0 + i)
    assert regime_from_proxy(proxy, 30).trend is Trend.NEUTRAL


def test_no_lookahead_in_regime() -> None:
    proxy = _series(lambda i: 100.0 * (1.0006**i) + (5 if i % 20 == 0 else 0))
    for t in range(300, len(proxy) - 1, 7):
        truncated = regime_from_proxy(proxy.head(t), t)
        full = regime_from_proxy(proxy, t)
        assert truncated.trend == full.trend
        assert truncated.vol == full.vol


def test_regime_lookup_equals_the_per_session_classification() -> None:
    """``regime_lookup`` caches each session's 20-day vol instead of letting every
    session recompute ~50 trailing ones. The cache must be invisible: every
    state, including vol and trend flips on a choppy path, is exactly what
    ``regime_from_proxy`` returns for that session alone."""
    import math

    proxy = _series(lambda i: 100.0 * (1.0004**i) * (1.0 + 0.03 * math.sin(i / 9.0)))
    lookup = regime_lookup(proxy)
    assert list(lookup) == list(proxy.dates)
    for t, d in enumerate(proxy.dates):
        assert lookup[d] == regime_from_proxy(proxy, t)
    assert {s.vol for s in lookup.values()} == {Vol.LOW, Vol.HIGH}  # both branches exercised
