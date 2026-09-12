"""Strategy registry, scans, candidates, backtests (ARCHITECTURE.md §5.3)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from signalforge.db.base import Base, CreatedAt, IntPK
from signalforge.db.types import UTCDateTime
from signalforge.domain import Direction, Horizon, QualityGate, StrategyStatus

_ENUM_KW: dict[str, Any] = {"native_enum": False, "length": 32, "validate_strings": True}


class Strategy(Base, IntPK, CreatedAt):
    __tablename__ = "strategy"
    __table_args__ = (UniqueConstraint("name"),)

    name: Mapped[str] = mapped_column(String(64))
    horizon: Mapped[Horizon] = mapped_column(SAEnum(Horizon, **_ENUM_KW))
    permits_long: Mapped[bool] = mapped_column(default=True)
    permits_short: Mapped[bool] = mapped_column(default=False)
    status: Mapped[StrategyStatus] = mapped_column(
        SAEnum(StrategyStatus, **_ENUM_KW), default=StrategyStatus.EXPERIMENTAL
    )
    versions: Mapped[list[StrategyVersion]] = relationship(back_populates="strategy")


class StrategyVersion(Base, IntPK, CreatedAt):
    """Immutable versioned spec (full §6.1 field set lives in ``spec_json``)."""

    __tablename__ = "strategy_version"
    __table_args__ = (UniqueConstraint("strategy_id", "version"),)

    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategy.id", ondelete="CASCADE"))
    version: Mapped[str] = mapped_column(String(24))
    git_sha: Mapped[str] = mapped_column(String(40))
    spec_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[StrategyStatus] = mapped_column(
        SAEnum(StrategyStatus, **_ENUM_KW), default=StrategyStatus.EXPERIMENTAL
    )

    strategy: Mapped[Strategy] = relationship(back_populates="versions")


class ScanRun(Base, IntPK):
    __tablename__ = "scan_run"

    horizon: Mapped[Horizon] = mapped_column(SAEnum(Horizon, **_ENUM_KW))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    config_hash: Mapped[str] = mapped_column(String(64), index=True)

    universe_size: Mapped[int] = mapped_column(Integer, default=0)
    scanned_count: Mapped[int] = mapped_column(Integer, default=0)
    excluded_count: Mapped[int] = mapped_column(Integer, default=0)
    no_trade_count: Mapped[int] = mapped_column(Integer, default=0)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    # reason -> {"count": int, "symbols": [str]}
    exclusions_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    data_snapshot_ref: Mapped[str] = mapped_column(String(120), default="")  # legacy, unused
    # The EXACT symbols and provider this run actually scanned, and the
    # DataSnapshot they resolve to (via get_or_create_dataset_snapshot, the
    # same mechanism the promotion pipeline uses) -- lets a candidate's
    # provenance be compared against the exact scope a strategy was actually
    # approved for (research.promotion.approval_scope), not just its status.
    universe_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(40), default="")
    dataset_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_snapshot.id", ondelete="SET NULL"), default=None
    )

    candidates: Mapped[list[Candidate]] = relationship(back_populates="scan_run")


class Candidate(Base, IntPK, CreatedAt):
    """One evidence-backed candidate (ARCHITECTURE.md §7.2)."""

    __tablename__ = "candidate"

    scan_run_id: Mapped[int] = mapped_column(ForeignKey("scan_run.id", ondelete="CASCADE"))
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id", ondelete="CASCADE"))
    strategy_version_id: Mapped[int] = mapped_column(
        ForeignKey("strategy_version.id", ondelete="CASCADE")
    )
    horizon: Mapped[Horizon] = mapped_column(SAEnum(Horizon, **_ENUM_KW))
    direction: Mapped[Direction] = mapped_column(SAEnum(Direction, **_ENUM_KW))

    entry_zone_low: Mapped[float] = mapped_column(Float)
    entry_zone_high: Mapped[float] = mapped_column(Float)
    invalidation_level: Mapped[float] = mapped_column(Float)
    target_level: Mapped[float | None] = mapped_column(Float, default=None)
    target_logic: Mapped[str] = mapped_column(String(200), default="")
    time_stop_days: Mapped[int] = mapped_column(Integer)

    reward_risk_estimate: Mapped[float] = mapped_column(Float)
    probability_calibrated: Mapped[float | None] = mapped_column(Float, default=None)
    calibration_ref: Mapped[str | None] = mapped_column(String(120), default=None)

    risk_dollars: Mapped[float] = mapped_column(Float)
    risk_pct_of_account: Mapped[float] = mapped_column(Float)

    liquidity_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    slippage_assumption_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    event_risk_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    portfolio_context_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    data_freshness_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ranking_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    reasons_qualify: Mapped[list[str]] = mapped_column(JSON, default=list)
    reasons_fail: Mapped[list[str]] = mapped_column(JSON, default=list)

    quality_gate_status: Mapped[QualityGate] = mapped_column(SAEnum(QualityGate, **_ENUM_KW))
    failed_gates: Mapped[list[str]] = mapped_column(JSON, default=list)
    rank_in_horizon: Mapped[int | None] = mapped_column(Integer, default=None)

    scan_run: Mapped[ScanRun] = relationship(back_populates="candidates")


class BacktestRun(Base, IntPK, CreatedAt):
    __tablename__ = "backtest_run"

    strategy_version_id: Mapped[int] = mapped_column(
        ForeignKey("strategy_version.id", ondelete="CASCADE")
    )
    params_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    date_start: Mapped[date] = mapped_column()
    date_end: Mapped[date] = mapped_column()
    is_start: Mapped[date | None] = mapped_column(default=None)
    is_end: Mapped[date | None] = mapped_column(default=None)
    oos_start: Mapped[date | None] = mapped_column(default=None)
    oos_end: Mapped[date | None] = mapped_column(default=None)
    costs_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    config_hash: Mapped[str] = mapped_column(String(64), index=True)
    git_sha: Mapped[str] = mapped_column(String(40), default="")
    seed: Mapped[int] = mapped_column(Integer, default=0)

    trades: Mapped[list[BacktestTrade]] = relationship(back_populates="run")
    metrics: Mapped[list[BacktestMetric]] = relationship(back_populates="run")
    windows: Mapped[list[WalkforwardWindow]] = relationship(back_populates="run")


class BacktestTrade(Base, IntPK):
    __tablename__ = "backtest_trade"

    run_id: Mapped[int] = mapped_column(ForeignKey("backtest_run.id", ondelete="CASCADE"))
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id", ondelete="CASCADE"))
    direction: Mapped[Direction] = mapped_column(SAEnum(Direction, **_ENUM_KW))
    entry_ts: Mapped[datetime] = mapped_column(UTCDateTime)
    entry_px: Mapped[float] = mapped_column(Float)
    exit_ts: Mapped[datetime] = mapped_column(UTCDateTime)
    exit_px: Mapped[float] = mapped_column(Float)
    bars_held: Mapped[int] = mapped_column(Integer)
    pnl: Mapped[float] = mapped_column(Float)
    pnl_r: Mapped[float] = mapped_column(Float)  # in R multiples
    mae: Mapped[float] = mapped_column(Float, default=0.0)
    mfe: Mapped[float] = mapped_column(Float, default=0.0)
    costs: Mapped[float] = mapped_column(Float, default=0.0)
    exit_reason: Mapped[str] = mapped_column(String(24), default="")

    run: Mapped[BacktestRun] = relationship(back_populates="trades")


class BacktestMetric(Base, IntPK):
    __tablename__ = "backtest_metric"
    __table_args__ = (UniqueConstraint("run_id", "segment", "phase"),)

    run_id: Mapped[int] = mapped_column(ForeignKey("backtest_run.id", ondelete="CASCADE"))
    # all | bull | bear | highvol | lowvol | range
    segment: Mapped[str] = mapped_column(String(16), default="all")
    # in_sample | out_of_sample | paper
    phase: Mapped[str] = mapped_column(String(16), default="out_of_sample")
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ci_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    run: Mapped[BacktestRun] = relationship(back_populates="metrics")


class WalkforwardWindow(Base, IntPK):
    __tablename__ = "walkforward_window"

    run_id: Mapped[int] = mapped_column(ForeignKey("backtest_run.id", ondelete="CASCADE"))
    fold_index: Mapped[int] = mapped_column(Integer)
    train_start: Mapped[date] = mapped_column()
    train_end: Mapped[date] = mapped_column()
    test_start: Mapped[date] = mapped_column()
    test_end: Mapped[date] = mapped_column()
    test_metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    run: Mapped[BacktestRun] = relationship(back_populates="windows")


class StrategyHealth(Base, IntPK, CreatedAt):
    """Rolling live-paper vs backtest-expectation tracking (Phase 2 monitor writes here)."""

    __tablename__ = "strategy_health"

    strategy_version_id: Mapped[int] = mapped_column(
        ForeignKey("strategy_version.id", ondelete="CASCADE")
    )
    window_label: Mapped[str] = mapped_column(String(24))  # e.g. "trailing_60_trades"
    paper_expectancy: Mapped[float] = mapped_column(Float)
    backtest_expectancy: Mapped[float] = mapped_column(Float)
    z_score: Mapped[float] = mapped_column(Float)
    action: Mapped[str] = mapped_column(String(12), default="none")  # none | downgrade | disable
    note: Mapped[str] = mapped_column(Text, default="")
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class DataSnapshot(Base, IntPK, CreatedAt):
    """An immutable, named definition of exactly which symbols — and, for a
    corrected/replaced symbol, which underlying derived instrument — a
    promotion evaluation used. Changing the universe (excluding a symbol,
    substituting a corrected continuous series) is a NEW data snapshot, never
    an edit to an existing one: ``StrategySealedTest`` is unique per
    ``(strategy_version_id, dataset_snapshot_id)``, not per strategy version
    alone, so switching snapshots can never reuse — or silently overwrite —
    another snapshot's sealed final test."""

    __tablename__ = "data_snapshot"
    __table_args__ = (UniqueConstraint("key"),)

    key: Mapped[str] = mapped_column(String(64))  # e.g. "universe_25_baseline"
    symbols_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    description: Mapped[str] = mapped_column(Text, default="")
    source_note: Mapped[str] = mapped_column(Text, default="")
    continuity_mapping_id: Mapped[int | None] = mapped_column(
        ForeignKey("symbol_continuity_mapping.id", ondelete="SET NULL"), default=None
    )
    # False only for audit-history rows a migration backfills to label data
    # that predates dataset snapshots (e.g. "universe_25_baseline_legacy") —
    # excluded from get_or_create_dataset_snapshot's unkeyed symbol-match
    # fallback so a new evaluation can never silently re-attach to a row
    # whose own description promises it will never be reused.
    reusable_by_new_evaluations: Mapped[bool] = mapped_column(default=True)
    # The options dataset's identity (D1 §9): band, ladder, IV policy, q policy,
    # rate policy, spread multiplier, strike-listing basis, coverage thresholds.
    # NULL on every equity snapshot, and deliberately NOT part of any database
    # constraint: ``UniqueConstraint("key")`` above is the ONLY declared identity
    # and is not altered, because a UNIQUE over a nullable column would let two
    # rows with the same key and a NULL scope both be legal — silently removing
    # the protection the two live PAPER_APPROVED equity snapshots rely on.
    # Scope identity is enforced procedurally in
    # ``research.promotion.get_or_create_dataset_snapshot`` instead: a key hit
    # whose stored scope differs from the request refuses, NULL-vs-present
    # included, and the unkeyed symbol-match fallback refuses to match at all
    # when a scope is supplied.
    options_scope_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)


class StrategySealedTest(Base, IntPK, CreatedAt):
    """The one-time, immutable sealed final out-of-sample evaluation for a
    strategy *version* on one *dataset snapshot* (promotion gate 9). At most
    one row per ``(strategy_version_id, dataset_snapshot_id)`` — enforced by
    the unique constraint *and* by ``research.promotion``, which reads an
    existing row rather than ever recomputing or overwriting one. A different
    result requires either a genuinely different strategy version or a
    genuinely different, separately-identified dataset snapshot — never
    re-sealing this exact (version, dataset) pair."""

    __tablename__ = "strategy_sealed_test"
    __table_args__ = (UniqueConstraint("strategy_version_id", "dataset_snapshot_id"),)

    strategy_version_id: Mapped[int] = mapped_column(
        ForeignKey("strategy_version.id", ondelete="CASCADE")
    )
    dataset_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("data_snapshot.id", ondelete="CASCADE")
    )
    window_start: Mapped[date] = mapped_column()
    window_end: Mapped[date] = mapped_column()
    universe_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    data_provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    benchmark_metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    passed: Mapped[bool] = mapped_column(default=False)
    detail: Mapped[str] = mapped_column(Text, default="")
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class StrategyPromotionEvaluation(Base, IntPK, CreatedAt):
    """One append-only record of a promotion-pipeline run for a strategy
    *version* — every gate, its evidence, and the verdict. Never updated after
    creation; a re-evaluation always inserts a new row (the version's whole
    history of attempts stays visible on the Strategy Promotion page). Only a
    row with ``passed=True`` may flip ``Strategy.status`` /
    ``StrategyVersion.status`` to ``PAPER_APPROVED`` — and only
    ``research.promotion`` does that, never a manual action."""

    __tablename__ = "strategy_promotion_evaluation"

    strategy_version_id: Mapped[int] = mapped_column(
        ForeignKey("strategy_version.id", ondelete="CASCADE"), index=True
    )
    dataset_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_snapshot.id", ondelete="SET NULL"), default=None, index=True
    )
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    config_hash: Mapped[str] = mapped_column(String(64))
    git_sha: Mapped[str] = mapped_column(String(40), default="")
    # sha256 of the strategy's own spec()/params at evaluation time -- NOT
    # git_sha (which changes on every commit to the repo, unrelated strategies
    # included). upsert_strategy_version refreshes StrategyVersion.spec_json on
    # every call, so a strategy's live params can drift after approval without
    # its `version` string changing; comparing this hash against the CURRENT
    # spec's hash at scan/alert time is what actually catches that (approval
    # scope's "strategy version" / "changed strategy parameters" match).
    spec_json_hash: Mapped[str] = mapped_column(String(64), default="")
    universe_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    window_start: Mapped[date] = mapped_column()
    window_end: Mapped[date] = mapped_column()
    data_provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    gates_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    passed: Mapped[bool] = mapped_column(default=False)
    verdict: Mapped[str] = mapped_column(String(80), default="")
    sealed_test_id: Mapped[int | None] = mapped_column(
        ForeignKey("strategy_sealed_test.id", ondelete="SET NULL"), default=None
    )
