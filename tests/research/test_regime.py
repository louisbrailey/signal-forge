"""Regime filter: trend/vol classification, no look-ahead."""

from __future__ import annotations

from datetime import date, timedelta

from signalforge.data.series import PriceSeries
from signalforge.research.regime import Trend, regime_from_proxy


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
