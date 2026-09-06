"""Position sizing + portfolio-limit enforcement."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from signalforge.config.research import RiskLimits
from signalforge.risk.engine import OpenExposure, SizingRequest, size_position

LIMITS = RiskLimits()


def _req(**kw: object) -> SizingRequest:
    base = {
        "symbol": "AAPL",
        "sector": "Tech",
        "entry_price": 100.0,
        "stop_price": 95.0,
        "account_equity": 10_000.0,
    }
    base.update(kw)
    return SizingRequest(**base)  # type: ignore[arg-type]


def test_basic_sizing_from_risk_budget() -> None:
    r = size_position(_req(), LIMITS)
    assert not r.rejected
    # 0.5% of 10k = $50 budget / $5 per-share risk = 10 shares
    assert r.shares == 10
    assert r.risk_dollars == pytest.approx(50.0)
    assert r.risk_pct_of_account == pytest.approx(0.5)


def test_concentration_cap_trims_shares() -> None:
    # tiny stop distance -> risk budget would buy a huge notional; must trim to 10%
    r = size_position(_req(stop_price=99.9), LIMITS)
    assert not r.rejected
    assert r.notional <= 10_000.0 * 0.10 + 1e-6
    assert r.checks["concentration"].startswith("trimmed")


def test_portfolio_exposure_limit_rejects() -> None:
    exp = OpenExposure(gross_dollars=10_000.0 * 0.60)  # already at the 60% cap
    r = size_position(_req(), LIMITS, exp)
    assert r.rejected
    assert "portfolio exposure" in (r.rejected_reason or "")


def test_correlated_sector_limit_rejects() -> None:
    exp = OpenExposure(by_sector_dollars={"Tech": 10_000.0 * 0.25})
    r = size_position(_req(), LIMITS, exp)
    assert r.rejected
    assert "correlated exposure" in (r.rejected_reason or "")


def test_daily_risk_limit_rejects() -> None:
    exp = OpenExposure(open_risk_dollars=10_000.0 * 0.015)  # at the 1.5% daily cap
    r = size_position(_req(), LIMITS, exp)
    assert r.rejected
    assert "daily portfolio risk" in (r.rejected_reason or "")


@pytest.mark.safety
@given(
    equity=st.floats(2_000, 500_000),
    entry=st.floats(5, 800),
    stop_frac=st.floats(0.005, 0.4),
)
def test_produced_size_never_violates_limits(equity: float, entry: float, stop_frac: float) -> None:
    stop = entry * (1 - stop_frac)
    r = size_position(_req(entry_price=entry, stop_price=stop, account_equity=equity), LIMITS)
    if r.rejected:
        return
    assert r.risk_dollars <= equity * LIMITS.per_trade_risk_pct / 100.0 + 1e-6
    assert r.notional <= equity * LIMITS.max_position_concentration_pct / 100.0 + 1e-6
