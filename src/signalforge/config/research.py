"""Version-controlled research configuration (ARCHITECTURE.md §9).

Every field here can change *what the engine recommends*, so the model exposes a
stable ``config_hash`` recorded on scan/backtest runs. Cosmetic/UI-only settings
do NOT belong in this model — put them in ``app_setting`` instead.

Defaults ship conservative.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import (
    BaseModel,
    Field,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
)

from signalforge.config.hashing import config_hash
from signalforge.domain import Horizon

__all__ = [
    "DataQualityConfig",
    "EventFilters",
    "ExecutionConfig",
    "GridConfig",
    "HealthMonitorConfig",
    "Horizon",
    "IntradayOperationsConfig",
    "LiquidityFilters",
    "NewsConfig",
    "OptionsConfig",
    "OptionsRiskLimits",
    "OptionsStructureLimits",
    "PromotionThresholds",
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


class PromotionThresholds(BaseModel):
    """Gates a strategy *version* must clear, on genuine licensed data, to move
    ``experimental`` -> ``paper_approved`` (ARCHITECTURE.md §6.5). Fixed here —
    version-controlled and hashed into ``config_hash`` — *before* any evaluation
    runs, so gate 2's trade-count bar is "documented before testing" by
    construction, not chosen after seeing a result.

    These thresholds are read-only inputs to ``research.promotion``, the only
    code path allowed to set ``StrategyStatus.PAPER_APPROVED``. A human may
    disable or downgrade a strategy directly; only this pipeline may approve one.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    # Gate 1 — rolling walk-forward folds over the pre-sealed span.
    min_walkforward_folds: PositiveInt = 4
    # Gate 2 — OOS trades required before the number is trusted at all.
    min_oos_trades: PositiveInt = 30
    # Gate 3 — net expectancy after the project's conservative cost model
    # (commission + slippage_bps + half-spread) must clear this.
    min_net_expectancy_r: float = 0.0
    # Gate 4 — bootstrap lower bound must be *materially* above zero, not just
    # non-negative (0.02R, not 0.00R).
    min_bootstrap_ci_low_r: float = 0.02
    # Gate 5 — parameter-sensitivity grid (delegates to research.sensitivity).
    sensitivity_positive_fraction_min: float = 0.6
    sensitivity_neighbour_fraction_min: float = 0.75
    sensitivity_min_grid_trades: PositiveInt = 15
    # Gate 6 — evidence across bull / bear / range-bound, each with a minimum
    # trade count (all three required, not "at least two of three").
    min_regimes_covered: PositiveInt = 3
    min_trades_per_regime: PositiveInt = 10
    # Gate 7 — promoted only on a risk-adjusted benchmark comparison (Sharpe
    # over ALL pre-sealed trades, in-sample and out-of-sample together, vs SPY
    # buy-and-hold Sharpe over the same matched span; see promotion.py's gate-7
    # block, which passes `full.trades`) — cumulative return alone never
    # decides this. NOT out-of-sample only: gates 2/3/4 read
    # `full.out_of_sample`, gate 7 deliberately does not.
    require_beat_benchmark_sharpe: bool = True
    # Gate 8 — no unresolved data-quality/leakage finding may support the result.
    require_data_validation_pass: bool = True
    require_leakage_check_pass: bool = True
    # Gate 9 — sealed final out-of-sample window, evaluated once and locked to
    # the strategy *version* forever (a new evaluation on the same version
    # reuses the first result; only a new version can be re-sealed).
    sealed_window_days: PositiveInt = 365
    sealed_min_trades: PositiveInt = 10
    sealed_min_expectancy_r: float = 0.0


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


class UniversePipelineConfig(BaseModel):
    """Liquid U.S. research-universe pipeline (grouped-daily bulk path).

    OFF by default. Everything here is END_OF_DAY, split-adjusted AS OF the
    fetch date (not point-in-time), and survivorship-biased at discovery
    (active tickers only) — the pipeline records those facts on every
    snapshot; nothing downstream may treat bulk history as adjusted
    point-in-time research data."""

    model_config = {"frozen": True, "extra": "forbid"}

    enabled: bool = False  # scheduled post-close update is a no-op until True
    security_types: tuple[str, ...] = ("CS", "ETF")
    min_price: PositiveFloat = 5.0
    min_avg_dollar_volume: PositiveFloat = 20_000_000.0
    adv_sessions: PositiveInt = 20
    min_market_cap: PositiveFloat = 2_000_000_000.0  # CS only; ETFs have no cap
    require_market_cap: bool = True  # CS with UNKNOWN cap are never eligible (flag kept)
    min_history_sessions: PositiveInt = 400
    min_session_coverage: float = 0.95  # share of archived sessions a symbol must be present in
    max_sector_share: float = 0.25  # max fraction of the eligible set in one 2-digit SIC group
    max_abs_daily_return: float = 0.50  # data-quality spike flag
    max_zero_volume_share: float = 0.05
    min_listing_age_days: PositiveInt = 30
    backfill_sessions: PositiveInt = (
        420  # bulk files to keep (>= min_history_sessions + ADV window)
    )
    max_storage_bytes: PositiveInt = 5 * 1024**3  # raw archive + normalized rows budget
    max_runtime_seconds: PositiveInt = 20 * 60  # per scheduled run; resumable
    request_spacing_s: float = 2.0  # grouped-daily bulk requests only (1 per session)
    normalized_source: str = (
        "massive_grouped"  # ohlcv_daily.source label; never the research source
    )


class AgentsConfig(BaseModel):
    """Bounded research agents (read-only reporters). The scheduled daily run
    is OFF by default; agents can always be run by hand with
    `signalforge agents run`."""

    model_config = {"frozen": True, "extra": "forbid"}

    enabled: bool = False
    llm_narratives: bool = False  # even when the LLM layer is configured, narratives are opt-in


class ExecutionConfig(BaseModel):
    """Order-execution layer — OFF by default (D6 ADR §2).

    **This shapes no signal.** It decides only whether an already-gated decision
    may be *submitted* to a broker's paper endpoint, so these fields are
    deliberately **excluded from** ``ResearchConfig.SCOPE_HASH_FIELDS``: a
    given strategy on a given dataset produces identical candidates with
    ``enabled`` on or off, and moving ``config_hash`` here would put every live
    PAPER_APPROVED approval out of scope the moment this section appeared —
    exactly the 2026-09-11 incident this list was narrowed to prevent. They
    still appear in ``full_config_hash`` for the audit trail.

    ``enabled=True`` is necessary and nowhere near sufficient: with no unexpired
    ``armed_strategy`` row, zero orders can be submitted. Two independent gates,
    neither sufficient alone. Nothing is armed by default.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    enabled: bool = False
    # The FIRST adapter is local, deterministic and network-free. Its fills are
    # drill artifacts and are never evidence for any gate (D6 §3.1).
    adapter_name: str = "paper_reference"


class GridConfig(BaseModel):
    """Mechanical grid strategy — live (paper) parameters.

    **This is NOT a promotion-gated strategy.** The grid never produces a
    ``Candidate``, never enters the scan/promotion pipeline, never alerts, and
    has no walk-forward or sealed-test evidence behind it; it is a mechanical
    rebalancing rule run on its own dedicated paper account. Accordingly these
    fields are deliberately **excluded from**
    ``ResearchConfig.SCOPE_HASH_FIELDS`` — changing them cannot un-scope, and
    must never appear to re-scope, a genuinely PAPER_APPROVED strategy. They
    still appear in ``full_config_hash`` for the audit trail.

    OFF by default: with ``enabled=False`` the scheduled ``grid_daily`` job is
    a logged no-op that writes nothing.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    enabled: bool = False
    universe_name: str = "top1000"
    universe_size: PositiveInt = 1000
    starting_cash: PositiveFloat = 5_000.0
    per_symbol_cap: PositiveFloat = 50.0
    buy_usd: PositiveFloat = 5.0
    sell_usd: PositiveFloat = 10.0
    drop_pct: PositiveFloat = 0.05  # fraction, not percent: 0.05 == 5%
    rise_pct: PositiveFloat = 0.05
    min_order_usd: NonNegativeFloat = 1.0
    # See GridParams.reanchor_on_untradeable_rise: a rise past the sell level
    # with nothing to sell still ratchets the anchor up to that close.
    reanchor_on_untradeable_rise: bool = True
    account_name: str = "grid"
    source: str = "massive_grouped"  # ohlcv_daily.source the live job reads


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
    # Raised from 200,000 by decision 6 of
    # docs/research/DECISIONS_2026-09-12_options_execution.md. This is an
    # EXPLICIT, recorded decision, not a quiet default bump: every run that
    # relies on it records the raise (previous value, new value, the decision
    # that authorised it) in its own ``IngestionRun`` provenance, so a dataset
    # built under the higher ceiling is distinguishable from one built under
    # the old one. ``options`` is absent from SCOPE_HASH_FIELDS, so changing it
    # cannot move the equity ``config_hash`` — see ``options_config_hash``.
    backfill_max_total_bars: PositiveInt = 2_000_000  # global storage ceiling (decision 6)
    BACKFILL_MAX_TOTAL_BARS_PRIOR: ClassVar[int] = 200_000  # what decision 6 raised it FROM

    # --- per-cycle (monthly) backfill: the shape D1 fixes ---------------------
    # Additive: the legacy nearest-N-expiries path is untouched and nothing
    # schedules this one — it is CLI-only.
    #
    # ``cycle_backfill_enabled`` used to gate the CLI outright. It existed for
    # one reason: the run held a single ``BEGIN IMMEDIATE`` across every network
    # call, so starting it against the live probation database meant a multi-day
    # SQLite write lock, and a kill switch mid-run discarded every bar AND the
    # ``IngestionRun`` row a resume needs (blockers D9, D16). Both are fixed —
    # one short write transaction per (underlying, cycle), the run row committed
    # before the first request, the kill switch caught at the loop boundary — so
    # the flag was removed rather than left behind gating nothing. What replaces
    # it is not a config value anyone can forget: ``--dry-run`` prints the exact
    # request plan, the command confirms before it fetches unless ``--yes`` is
    # passed, and ``--max-cycles`` / ``--max-minutes`` bound a pass.
    cycle_rule: str = "monthly_third_friday"
    dte_entry_min: PositiveInt = 21  # map §1.1 verbatim
    dte_entry_max: PositiveInt = 60
    pre_entry_buffer_sessions: NonNegativeInt = 5  # context for the entry session's IV inversion
    min_rungs_per_side: PositiveInt = 7  # map §1.1 "absolute floor of >=7 strikes either side"
    max_contracts_per_cycle: PositiveInt = 40  # a runaway guard, NEVER the selector
    reference_max_staleness_sessions: NonNegativeInt = 3
    ladder_bracket_min_rungs: PositiveInt = 3  # vendor strikes required each side of the reference
    # ``expired=true`` is what makes an expired series visible at all; without it
    # a listing call for a 2023 expiry returns zero rows (D1 §7.0, Appendix P).
    listing_include_expired: bool = True
    # Point-in-time listing: pin the ladder to the state of the world on the
    # cycle's entry date. Without it the ladder for an expired series is its
    # END-OF-LIFE ladder, which selects short strikes in the direction the
    # market actually went (D1 §3.3a). Whether the vendor honours it is OQ-10;
    # the basis actually achieved is recorded per dataset.
    listing_as_of_enabled: bool = True


class OptionsRiskLimits(BaseModel):
    """REFUSAL-ONLY capital limits for the options paper book (D3 §4, decision 4).

    Nothing here selects a structure or times an exit; every field can only ever
    REFUSE an open. That is why the object sits **outside every hash**: an
    operator tightening a dollar cap must not un-scope an approval. ``options_risk``
    is deliberately absent from ``ResearchConfig.SCOPE_HASH_FIELDS`` — adding it
    would move ``config_hash`` for every live PAPER_APPROVED equity strategy and
    repeat the 2026-09-11 agents-section incident exactly (D3 §1.4). The
    selection/exit parameters live in :class:`OptionsStructureLimits`, which is
    read from the strategy's own ``spec_json`` when it carries one, so a shaping
    change moves ``spec_json_hash`` and costs a counted sealed look.

    Every value is decision 4's (``DECISIONS_2026-09-12_options_execution.md``),
    recorded as an evaluation-grid CENTRE. The operator may change any of them
    before arming.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    per_structure_max_loss_dollars: PositiveFloat = 250.0
    total_open_max_loss_dollars: PositiveFloat = 1_000.0
    collateral_cap_dollars: PositiveFloat = 5_000.0
    max_net_delta_notional_dollars: PositiveFloat = 10_000.0
    max_net_vega_dollars_per_vol_pt: PositiveFloat = 50.0
    # Computed over BOTH accounts and evaluated ONLY inside
    # ``assert_options_auto_simulate_allowed`` (D3 §5.2 Finding 2), so it can only
    # ever refuse an OPTIONS open. ``risk.size_position``, ``accept_candidate``
    # and ``assert_auto_simulate_allowed`` never consult it: the equity path is
    # byte-identical whether or not this limit exists.
    combined_max_net_delta_notional_dollars: PositiveFloat = 10_000.0
    per_order_notional_dollars: PositiveFloat = 1_000.0
    daily_order_cap: PositiveInt = 10
    account_exposure_cap_pct: PositiveFloat = 40.0
    # Dead configuration at decision 4's numbers — $1,000 / $250 already caps the
    # book at 4 structures (D3 §3.5). Kept because it binds if the per-structure
    # cap falls, and every refusal reports WHICH limit actually bound.
    max_open_structures: PositiveInt = 5
    max_structures_per_underlying: PositiveInt = 1  # keyed on the UNDERLYING
    # Decision 13's separate SIMULATED options account. The account is named in
    # CONFIGURATION, not by the caller: a required keyword stops a *forgotten*
    # account name and does nothing about a *wrong* one, and "default" is a
    # perfectly valid string that resolves to the live equity account (D3 §2).
    paper_account_name: str = "options"
    paper_account_initial_cash: PositiveFloat = 25_000.0


class OptionsStructureLimits(BaseModel):
    """SELECTION / EXIT parameters — the shaping group (D3 §4, §5.3).

    These do not limit capital: they decide **which** structure opens and
    **when** it closes, exactly as ``RiskLimits.min_reward_to_risk`` decides
    which candidates exist at all. They therefore belong inside a
    pre-registration hash, and the repo already has the right one: a strategy's
    ``spec_json["options"]`` is covered by ``spec_json_hash``, which
    ``research.approval_scope.scan_scope_matches`` compares as one of the five
    parts. The values here are **defaults** used when a strategy carries no
    ``spec_json["options"]`` block; a real options strategy overrides them there,
    where moving one is visible.

    ``min_credit_to_width`` and ``max_short_delta`` are KEPT as a PAIR, per map
    §3.2's Rule and D3 §5.3 (rev 1's proposal to retire the credit hurdle was
    withdrawn: the "degeneracy" was -0.034..+0.064, monotone in sigma*sqrt(T),
    not +/-0.02). D3 Finding 5 records that the pair and ``min_theta`` have a
    jointly empty feasible set under the *illustrative* cost constants — that is
    a finding about the cost model, not a licence to delete a gate, and it is
    D2's frozen ``OptionCostModel`` that must move first.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    structure_type: str = "vertical_credit"  # gate 0.5: exactly one per version
    max_short_delta: PositiveFloat = 0.20  # SELECTION — entry delta ceiling
    min_credit_to_width: NonNegativeFloat = 0.25  # SELECTION — kept as a gate
    # theta: (net credit - modelled round-trip costs) / R, evaluated at BOTH the
    # baseline and the 2x spread setting (gate 4b, decision 5).
    min_net_credit_after_costs_to_max_loss: float = 0.0
    dte_entry_min: PositiveInt = 21
    dte_entry_max: PositiveInt = 45
    width_min_dollars: PositiveFloat = 2.0
    width_max_dollars: PositiveFloat = 3.0
    profit_target_pct_of_credit: PositiveFloat = 0.50
    stop_multiple_of_credit: PositiveFloat = 2.0
    time_stop_dte: PositiveInt = 7  # EXIT — forces a close
    pin_band_pct: PositiveFloat = 0.002
    assignment_itm_threshold_pct: NonNegativeFloat = 0.0

    @classmethod
    def from_spec_json(
        cls, spec_json: dict[str, object] | None, default: OptionsStructureLimits
    ) -> OptionsStructureLimits:
        """The strategy's own ``spec_json["options"]`` wins over the config default.

        Returns ``default`` unchanged when the block is absent or is not a dict,
        so a strategy that carries no options block is shaped by the recorded
        configuration and a strategy that does carry one is shaped by a value
        inside ``spec_json_hash``."""
        block = (spec_json or {}).get("options")
        if not isinstance(block, dict):
            return default
        merged = default.model_dump(mode="json")
        merged.update({k: v for k, v in block.items() if k in merged})
        return cls.model_validate(merged)

    @property
    def options_shaping_hash(self) -> str:
        """A hash over the shaping group alone, recorded on every options
        evidence snapshot so two evaluations of one strategy version whose
        shaping differs are, by construction, two disclosable variants."""
        return config_hash(self.model_dump(mode="json"))


class OptionsEvaluationConfig(BaseModel):
    """The frozen, hashed identity of an options EVALUATION's assumptions.

    Deliberately separate from ``ResearchConfig.config_hash``. ``options`` is not
    in ``SCOPE_HASH_FIELDS``, so ``risk_free_rate`` (and every backfill
    parameter) could otherwise change every options IV, delta and mark without
    changing any hash at all — the same class of failure as the 2026-09-11
    agents-section incident. The fix is NOT to add ``options`` to
    ``SCOPE_HASH_FIELDS``: that would move ``config_hash`` for the two live
    PAPER_APPROVED equity strategies and un-scope them, repeating the incident
    exactly. A separate hash over a separate object touches nothing equity-side
    (D1 §5.5, blocker D11).
    """

    model_config = {"frozen": True, "extra": "forbid"}

    schema_version: PositiveInt = 1
    risk_free_rate: NonNegativeFloat = 0.04
    r_source: str = "config_constant"
    # IV rank-1 admissibility (D1 §5.2). ``implied_vol`` does NOT return None on
    # non-convergence — after max_iter bisection steps it returns the midpoint,
    # a float indistinguishable from a converged solve — so the caller must
    # re-price at the returned sigma and check vega. Rank 1 is the only source
    # permitted to price a FILL; an arbitrary sigma there is an arbitrary delta,
    # and an arbitrary delta is an arbitrary strike-selection rule.
    iv_max_price_residual: PositiveFloat = 1e-4
    iv_min_vega: PositiveFloat = 1e-3
    # Same-session surface floor (D1 §5.3). Below it there is no surface and the
    # contract is marked unavailable — never extrapolated.
    surface_min_prints_per_expiry: PositiveInt = 5
    surface_min_distinct_strikes: PositiveInt = 3
    surface_fit: str = "quadratic_log_moneyness"
    surface_term_interp: str = "linear_total_variance"
    surface_extrapolation: bool = False
    realised_vol_fallback: bool = False  # forbidden; never True
    # q precedence (decision 11). ``q = 0`` is never reached.
    q_precedence: tuple[str, ...] = ("vendor_dividends", "parity_implied")
    parity_min_pairs: PositiveInt = 3
    parity_max_abs_log_moneyness: PositiveFloat = 0.05
    parity_statistic: str = "median"
    q_default_zero_permitted: bool = False
    # Gate 4b: every evaluation runs at baseline AND 2x baseline spread, on both
    # asset classes (decision 5). The multiplier is part of an evaluation's
    # identity — two spread settings must never hash to one snapshot.
    spread_multipliers: tuple[float, ...] = (1.0, 2.0)
    # Coverage thresholds, pre-registered before any coverage was observed.
    # R4 permits making a gate MORE searching; neither may ever be lowered.
    gate_0c_cycles_bracket: PositiveFloat = 0.90
    gate_0d_session_bars: PositiveFloat = 0.80
    require_shares_per_contract: PositiveInt = 100

    @property
    def options_config_hash(self) -> str:
        return config_hash(self.model_dump(mode="json"))


class IntradayOperationsConfig(BaseModel):
    """Whether this deployment OPERATES on the INTRADAY horizon at all.

    One flag, consulted by every policy surface through
    ``research.intraday_policy`` — before it existed the policy was stated in
    four places that did not agree: ``ResearchConfig.enabled_horizons``
    *includes* INTRADAY, while ``approved_scope_scan.approved_horizons``
    excluded it, ``alerts.dispatch`` skipped it, and no scheduled job ever ran
    during the session.

    OFF by default, and OFF is not a placeholder: with it off, intraday
    candidates are never scanned on an approved dataset, never alerted on, and
    no intraday job is scheduled — byte-identical to the behaviour before this
    config section existed.

    Turning it ON does NOT make intraday execution realistic. The entitled feed
    is DELAYED >= 15 min against a 15m research bar, so the backtest's
    next-bar-open fill is permanently one bar early. That is disclosed at every
    surface rather than silently accepted; see docs/INTRADAY_OPERATION.md."""

    model_config = {"frozen": True, "extra": "forbid"}

    operating_enabled: bool = False
    # Cadence of the scheduled in-session scan. None = the bar size, which is
    # the only cadence at which a new bar can exist.
    scan_interval_minutes: PositiveInt | None = None
    # The in-session scan window, ET. Defaults to regular hours; the scan is a
    # no-op outside it and on non-session days.
    session_start_et: str = "09:30"
    session_end_et: str = "16:00"


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
    promotion: PromotionThresholds = Field(default_factory=PromotionThresholds)
    health_monitor: HealthMonitorConfig = Field(default_factory=HealthMonitorConfig)
    universe_filters: UniverseFilters = Field(default_factory=UniverseFilters)
    universe_pipeline: UniversePipelineConfig = Field(default_factory=UniversePipelineConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    # Mechanical grid strategy — NOT promotion-gated, deliberately absent from
    # SCOPE_HASH_FIELDS below (see GridConfig's docstring).
    grid: GridConfig = Field(default_factory=GridConfig)
    options: OptionsConfig = Field(default_factory=OptionsConfig)
    # Options paper risk (D3 / I-O6). BOTH are deliberately absent from
    # SCOPE_HASH_FIELDS: ``options_risk`` can only ever refuse an options open,
    # and ``options_shaping`` is a set of DEFAULTS that a real options strategy
    # overrides inside its own ``spec_json`` (hence inside ``spec_json_hash``).
    # Adding either here would move ``config_hash`` for every live
    # PAPER_APPROVED equity strategy — the 2026-09-11 incident, repeated.
    # Asserted by tests/paper/test_options_config_scope.py.
    options_risk: OptionsRiskLimits = Field(default_factory=OptionsRiskLimits)
    options_shaping: OptionsStructureLimits = Field(default_factory=OptionsStructureLimits)
    # Order execution — OFF by default, deliberately absent from
    # SCOPE_HASH_FIELDS below (see ExecutionConfig's docstring).
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    news: NewsConfig = Field(default_factory=NewsConfig)
    intraday: IntradayOperationsConfig = Field(default_factory=IntradayOperationsConfig)

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

    # The sections that shape WHICH signals a scan or backtest produces. The
    # approval scope (research/approval_scope.py) hashes these and ONLY these,
    # so adding or changing an unrelated section — agents, news, options, the
    # universe pipeline, the health monitor, the alert cap, or promotion
    # thresholds (which every evaluation records per gate in gates_json) — can
    # never silently un-scope a live PAPER_APPROVED strategy. Adding a field
    # that DOES change signals means adding it here, and that is a deliberate
    # re-approval event.
    #
    # `intraday` is deliberately EXCLUDED, and here is the argument. It decides
    # whether intraday candidates are scanned, scheduled and alerted on — an
    # OPERATING policy. It changes no strategy's rule, no threshold, no
    # universe and no cost: a given strategy evaluated on a given dataset
    # produces the identical signals with the flag on or off. `intraday_bar_size`
    # and `enabled_horizons`, which DO shape signals, are hashed and stay
    # hashed. Including `intraday` would also move config_hash the moment this
    # section appeared and put both live PAPER_APPROVED approvals out of scope
    # immediately — exactly the incident this SCOPE_HASH_FIELDS list was
    # narrowed to prevent — while buying no protection, because with the flag
    # off no intraday candidate exists to be scoped and with it on the
    # candidate's own hash is recorded like any other.
    #
    # The mechanical grid (``grid``) is likewise absent: it
    # is not a registered, promotion-gated strategy and produces no candidate.
    #
    # `execution` is absent for the same reason as `intraday`, and the argument
    # is the stronger one: it decides whether an already-gated decision may be
    # SUBMITTED, never which signals exist. A strategy evaluated on a given
    # dataset produces identical candidates with execution enabled or disabled.
    # Including it would move config_hash the moment the section appeared and
    # put every live PAPER_APPROVED approval out of scope — the 2026-09-11
    # incident, repeated. Asserted by tests/execution/test_config_scope.py.
    SCOPE_HASH_FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "watchlist",
        "etf_universe",
        "allow_short_candidates",
        "enabled_horizons",
        "intraday_bar_size",
        "liquidity",
        "risk",
        "events",
        "data_quality",
        "quality_gates",
        "universe_filters",
        "commission_per_share",
        "commission_min_per_order",
        "slippage_bps",
        "half_spread_fill_penalty",
    )

    @property
    def config_hash(self) -> str:
        """Stable hash over the signal-shaping sections only (``SCOPE_HASH_FIELDS``)."""
        payload = self.model_dump(mode="json")
        return config_hash({k: payload[k] for k in self.SCOPE_HASH_FIELDS if k in payload})

    @property
    def full_config_hash(self) -> str:
        """Hash over EVERY section — for audit trails, never for scope matching."""
        return config_hash(self.model_dump(mode="json"))
