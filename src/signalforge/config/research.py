"""Version-controlled research configuration (ARCHITECTURE.md §9).

Every field here can change *what the engine recommends*, so the model exposes a
stable ``config_hash`` recorded on scan/backtest runs. Cosmetic/UI-only settings
do NOT belong in this model — put them in ``app_setting`` instead.

Defaults ship conservative.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, NonNegativeFloat, PositiveFloat, PositiveInt

from signalforge.config.hashing import config_hash
from signalforge.domain import Horizon

__all__ = [
    "DataQualityConfig",
    "EventFilters",
    "HealthMonitorConfig",
    "Horizon",
    "LiquidityFilters",
    "NewsConfig",
    "OptionsConfig",
    "QualityThresholds",
    "ResearchConfig",
    "RiskLimits",
    "UniverseFilters",
]


class LiquidityFilters(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    min_price: PositiveFloat = 5.0
    min_avg_dollar_volume: PositiveFloat = 20_000_000.0
    max_avg_spread_bps: PositiveFloat = 15.0
    min_market_cap: PositiveFloat = 1_000_000_000.0
    max_market_cap: PositiveFloat | None = None


class RiskLimits(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    per_trade_risk_pct: PositiveFloat = 0.5  # % of paper account at risk to stop
    max_daily_portfolio_risk_pct: PositiveFloat = 1.5
    max_position_concentration_pct: PositiveFloat = 10.0
    max_portfolio_exposure_pct: PositiveFloat = 60.0
    max_correlated_exposure_pct: PositiveFloat = 25.0  # per sector / theme
    min_reward_to_risk: PositiveFloat = 1.5


class EventFilters(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    exclude_days_before_earnings: PositiveInt = 3
    exclude_days_after_earnings: PositiveInt = 1
    block_on_major_econ_event: bool = True


class QualityThresholds(BaseModel):
    """Gates a candidate must clear (ARCHITECTURE.md §6.4)."""

    model_config = {"frozen": True, "extra": "forbid"}

    min_oos_expectancy_r: float = 0.0  # OOS expectancy net of costs must exceed this
    min_oos_ci_low_r: float = -0.15  # bootstrap lower bound not deeply negative
    min_oos_trades: PositiveInt = 20  # enough OOS trades to trust the number
    require_backtest: bool = True  # no committed backtest => NO TRADE
    # Genuine out-of-sample evidence must span more than one *trend* regime
    # (bull / bear / neutral): at least ``min_oos_regimes`` of them, each with at
    # least ``min_trades_per_regime`` OOS trades. bull/high + bull/low is still
    # one trend — a bull-only edge is not eligible.
    min_oos_regimes: PositiveInt = 2
    min_trades_per_regime: PositiveInt = 10


class UniverseFilters(BaseModel):
    """Conservative liquid-U.S. universe screen. Applied on top of the watchlist +
    ETF set; a symbol must clear every active filter to be scanned."""

    model_config = {"frozen": True, "extra": "forbid"}

    min_price: PositiveFloat = 5.0
    min_market_cap: PositiveFloat = 2_000_000_000.0
    min_avg_dollar_volume: PositiveFloat = 20_000_000.0
    max_avg_spread_bps: PositiveFloat = 20.0
    min_history_days: PositiveInt = 400  # data-coverage floor
    excluded_sectors: tuple[str, ...] = ()
    exclude_within_days_of_earnings: PositiveInt = 3
    max_universe_size: PositiveInt = 150


class OptionsConfig(BaseModel):
    """Options coverage (education / simulation only). Deliberately narrow —
    a small liquid ETF + large-cap set, bounded expirations and strikes."""

    model_config = {"frozen": True, "extra": "forbid"}

    underlyings: tuple[str, ...] = ("SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA")
    expiration_min_days: PositiveInt = 14
    expiration_max_days: PositiveInt = 120
    strike_pct_band: PositiveFloat = 0.25  # +/- around the reference price
    poll_enabled: bool = False  # OFF by default; snapshots are on-demand
    risk_free_rate: NonNegativeFloat = 0.04  # simulator assumption, not vendor data

    # --- bounded historical-aggregates backfill (education only) --------------
    # OFF by default. Every limit below is a HARD cap the backfill enforces
    # *before* any per-contract fetch; whatever it drops to stay under a cap is
    # logged, never silently truncated.
    backfill_enabled: bool = False
    backfill_lookback_days: PositiveInt = 365  # window depth (~1 trading year)
    backfill_expirations_per_underlying: PositiveInt = 4  # nearest N expiries only
    backfill_contracts_per_underlying: PositiveInt = 40  # ATM-ranked, per underlying
    backfill_strike_pct_band: PositiveFloat = 0.15  # tighter than the snapshot band
    backfill_max_total_bars: PositiveInt = 200_000  # global storage ceiling


class NewsConfig(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    poll_enabled: bool = False  # OFF by default
    poll_interval_minutes: PositiveInt = 30
    lookback_days: PositiveInt = 3
    per_ticker_limit: PositiveInt = 25
    us_session_only: bool = True  # poll only around U.S. market sessions


class HealthMonitorConfig(BaseModel):
    """Rules for downgrading/disabling a strategy after sustained live-paper
    underperformance versus its out-of-sample expectation (ARCHITECTURE.md §5.3).

    All rules are here (version-controlled, hashed into ``config_hash``), shown in
    Strategy Lab, and every transition is written to ``audit_log``.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    enabled: bool = True
    # Closed paper trades required before live expectancy is compared at all.
    min_paper_trades: PositiveInt = 20
    # z = (paper_expectancy - oos_expectancy) / stderr(paper). Both gates also
    # require paper expectancy to be outright negative, so a strategy that is
    # merely below a high backtest bar but still profitable is left alone.
    downgrade_z: float = -2.0  # paper_approved -> experimental
    disable_z: float = -3.5  # experimental -> disabled (severe, sustained)


class DataQualityConfig(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    reconciliation_max_pct_diff: PositiveFloat = 0.5  # close-price disagreement threshold
    # Max age (minutes) a required feed may be before an instrument is "stale"
    # for that horizon and is excluded from candidates / live alerts.
    freshness_budget_minutes: dict[Horizon, PositiveInt] = Field(
        default_factory=lambda: {
            Horizon.INTRADAY: 15,
            Horizon.SHORT_SWING: 1_440,
            Horizon.MEDIUM_SWING: 2_880,
            Horizon.POSITION: 4_320,
        }
    )


class ResearchConfig(BaseModel):
    """The complete research-relevant configuration surface."""

    model_config = {"frozen": True, "extra": "forbid"}

    schema_version: int = 1

    # Universe
    watchlist: tuple[str, ...] = (
        "AAPL",
        "MSFT",
        "NVDA",
        "AMZN",
        "GOOGL",
        "META",
        "JPM",
        "XOM",
        "UNH",
        "HD",
    )
    etf_universe: tuple[str, ...] = (
        "SPY",
        "QQQ",
        "IWM",
        "DIA",
        "XLK",
        "XLF",
        "XLE",
        "XLV",
        "XLY",
        "XLP",
        "XLI",
        "XLB",
        "XLU",
        "XLRE",
        "XLC",
    )
    allow_short_candidates: bool = False
    enabled_horizons: tuple[Horizon, ...] = (
        Horizon.INTRADAY,
        Horizon.SHORT_SWING,
        Horizon.MEDIUM_SWING,
        Horizon.POSITION,
    )
    intraday_bar_size: str = "15m"

    liquidity: LiquidityFilters = Field(default_factory=LiquidityFilters)
    risk: RiskLimits = Field(default_factory=RiskLimits)
    events: EventFilters = Field(default_factory=EventFilters)
    data_quality: DataQualityConfig = Field(default_factory=DataQualityConfig)
    quality_gates: QualityThresholds = Field(default_factory=QualityThresholds)
    health_monitor: HealthMonitorConfig = Field(default_factory=HealthMonitorConfig)
    universe_filters: UniverseFilters = Field(default_factory=UniverseFilters)
    options: OptionsConfig = Field(default_factory=OptionsConfig)
    news: NewsConfig = Field(default_factory=NewsConfig)

    # Backtest cost assumptions (displayed on every candidate + report)
    commission_per_share: NonNegativeFloat = 0.0
    commission_min_per_order: NonNegativeFloat = 0.0
    slippage_bps: NonNegativeFloat = 3.0
    half_spread_fill_penalty: bool = True

    # Alerting policy that affects *which* signals are eligible to alert
    max_high_priority_alerts_per_day: PositiveInt = 2

    @property
    def universe(self) -> tuple[str, ...]:
        """De-duplicated, sorted union of the watchlist and ETF universe."""
        return tuple(sorted({*self.watchlist, *self.etf_universe}))

    @property
    def config_hash(self) -> str:
        """Stable hash over every research-relevant value."""
        return config_hash(self.model_dump(mode="json"))
