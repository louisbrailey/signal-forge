"""Config surface + research-config behaviour."""

from __future__ import annotations

from signalforge.config.research import Horizon, ResearchConfig


def test_universe_is_deduped_union_of_watchlist_and_etfs() -> None:
    cfg = ResearchConfig(watchlist=("AAPL", "SPY"), etf_universe=("SPY", "QQQ"))
    assert cfg.universe == ("AAPL", "QQQ", "SPY")


def test_defaults_are_conservative() -> None:
    cfg = ResearchConfig()
    assert cfg.allow_short_candidates is False
    assert cfg.risk.per_trade_risk_pct <= 1.0
    assert set(cfg.enabled_horizons) == set(Horizon)  # Phase 2: all four horizons on
    assert cfg.liquidity.min_avg_dollar_volume >= 1_000_000


def test_research_config_is_frozen() -> None:
    cfg = ResearchConfig()
    try:
        cfg.allow_short_candidates = True  # type: ignore[misc]
    except (AttributeError, TypeError, ValueError):
        return
    raise AssertionError("ResearchConfig should be immutable")


def test_freshness_budget_orders_by_horizon() -> None:
    b = ResearchConfig().data_quality.freshness_budget_minutes
    assert b[Horizon.INTRADAY] < b[Horizon.SHORT_SWING] < b[Horizon.POSITION]
