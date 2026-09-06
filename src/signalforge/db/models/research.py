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
    data_snapshot_ref: Mapped[str] = mapped_column(String(120), default="")

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
