"""Auth, settings, alerts, audit, LLM call log, and CSV-import tables (§5.4/§5.5)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from signalforge.db.base import Base, CreatedAt, IntPK, TimestampedMixin
from signalforge.db.types import UTCDateTime
from signalforge.domain import AlertChannel, AlertStatus, AlertType

_ENUM_KW: dict[str, Any] = {"native_enum": False, "length": 32, "validate_strings": True}


class User(Base, IntPK, CreatedAt):
    """Single local user (Phase 1). Password hashed with Argon2id."""

    __tablename__ = "user"

    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    is_active: Mapped[bool] = mapped_column(default=True)


class AppSetting(Base, IntPK, TimestampedMixin):
    """Typed key/value for non-research config (UI prefs, alert toggles, etc.)."""

    __tablename__ = "app_setting"

    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    value_json: Mapped[Any] = mapped_column(JSON)
    updated_by: Mapped[str] = mapped_column(String(60), default="local-user")


class AppSettingHistory(Base, IntPK, CreatedAt):
    __tablename__ = "app_setting_history"

    key: Mapped[str] = mapped_column(String(80), index=True)
    old_value_json: Mapped[Any] = mapped_column(JSON, default=None)
    new_value_json: Mapped[Any] = mapped_column(JSON, default=None)
    changed_by: Mapped[str] = mapped_column(String(60), default="local-user")


class AlertSetting(Base, IntPK, TimestampedMixin):
    __tablename__ = "alert_setting"
    __table_args__ = (UniqueConstraint("channel"),)

    channel: Mapped[AlertChannel] = mapped_column(SAEnum(AlertChannel, **_ENUM_KW))
    enabled: Mapped[bool] = mapped_column(default=False)  # OFF until setup complete
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AlertLog(Base, IntPK, CreatedAt):
    __tablename__ = "alert_log"
    __table_args__ = (UniqueConstraint("dedupe_key"),)

    alert_type: Mapped[AlertType] = mapped_column(SAEnum(AlertType, **_ENUM_KW))
    channel: Mapped[AlertChannel] = mapped_column(SAEnum(AlertChannel, **_ENUM_KW))
    dedupe_key: Mapped[str] = mapped_column(String(120))
    status: Mapped[AlertStatus] = mapped_column(SAEnum(AlertStatus, **_ENUM_KW))
    suppressed_reason: Mapped[str] = mapped_column(String(200), default="")
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)


class KillSwitchEvent(Base, IntPK):
    """DB mirror of the file-backed kill switch transitions (current state = latest row)."""

    __tablename__ = "kill_switch_event"

    active: Mapped[bool] = mapped_column()
    reason: Mapped[str] = mapped_column(String(300))
    actor: Mapped[str] = mapped_column(String(60), default="system")
    changed_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)


class AuditLog(Base, IntPK):
    __tablename__ = "audit_log"

    ts: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    actor: Mapped[str] = mapped_column(String(60), default="system")
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity: Mapped[str] = mapped_column(String(80), default="")
    request_id: Mapped[str] = mapped_column(String(48), default="")
    before_json: Mapped[Any] = mapped_column(JSON, default=None)
    after_json: Mapped[Any] = mapped_column(JSON, default=None)


class AgentReport(Base, IntPK):
    """One run of a bounded research agent: deterministic summary + evidence
    (with per-item sources/timestamps), an optional LLM narrative stored
    SEPARATELY and labelled, citations, and explicit missing-data disclosures.
    The only table an agent may write."""

    __tablename__ = "agent_report"
    __table_args__ = (Index("ix_agent_report_agent_created", "agent", "created_at"),)

    agent: Mapped[str] = mapped_column(String(40), index=True)
    role: Mapped[str] = mapped_column(String(120), default="")
    as_of: Mapped[datetime] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(12), default="ok")  # ok | failed
    summary: Mapped[str] = mapped_column(Text, default="")
    narrative: Mapped[str | None] = mapped_column(Text, default=None)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    citations_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    missing_data_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    duration_s: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)


class WorkerHeartbeat(Base, IntPK):
    """Liveness of a background worker process (the in-process APScheduler).
    One row per worker name, upserted every ``scheduler.HEARTBEAT_INTERVAL_S``
    seconds with the scheduler's own next-run times, so /ops can say whether
    the worker is ACTUALLY running and when the next job will fire — not
    merely what the cron table intends."""

    __tablename__ = "worker_heartbeat"
    __table_args__ = (UniqueConstraint("worker"),)

    worker: Mapped[str] = mapped_column(String(40))
    host: Mapped[str] = mapped_column(String(120), default="")
    pid: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_beat_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    next_runs_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    detail: Mapped[str] = mapped_column(String(300), default="")


class JobRun(Base, IntPK):
    """One execution of a guarded scheduled job — ok, failed, or skipped by the
    kill switch — so the Operational Status page can show the last outcome per
    job without scanning the audit log. A failure is ALSO still written to
    ``AuditLog(action="job.failed")`` for the alert policy; this is the operator
    view, not a replacement."""

    __tablename__ = "job_run"
    __table_args__ = (Index("ix_job_run_name_started", "name", "started_at"),)

    name: Mapped[str] = mapped_column(String(60), index=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    status: Mapped[str] = mapped_column(String(12), default="running")  # running|ok|failed|skipped
    detail: Mapped[str] = mapped_column(String(300), default="")


class LlmCall(Base, IntPK):
    """Every LLM call is auditable (ARCHITECTURE.md §11)."""

    __tablename__ = "llm_call"

    purpose: Mapped[str] = mapped_column(String(48), index=True)
    model: Mapped[str] = mapped_column(String(64))
    prompt_sha: Mapped[str] = mapped_column(String(64))
    input_snapshot_ref: Mapped[str] = mapped_column(String(200), default="")
    output_ref: Mapped[str] = mapped_column(String(200), default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)


# --------------------------------------------------------------------------- #
# Manual CSV portfolio import — analytics only, never fed to the scanner (S2)
# --------------------------------------------------------------------------- #
class PortfolioImport(Base, IntPK, CreatedAt):
    __tablename__ = "portfolio_import"

    filename: Mapped[str] = mapped_column(String(200))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    broker_format: Mapped[str] = mapped_column(String(40), default="unknown")
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    imported_at: Mapped[datetime] = mapped_column(UTCDateTime)

    positions: Mapped[list[ImportedPosition]] = relationship(back_populates="batch")
    transactions: Mapped[list[ImportedTransaction]] = relationship(back_populates="batch")


class ImportedPosition(Base, IntPK):
    __tablename__ = "imported_position"

    batch_id: Mapped[int] = mapped_column(ForeignKey("portfolio_import.id", ondelete="CASCADE"))
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    cost_basis: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), default=None)
    account_label: Mapped[str] = mapped_column(String(60), default="")
    source_row: Mapped[int] = mapped_column(Integer)

    batch: Mapped[PortfolioImport] = relationship(back_populates="positions")


class ImportedTransaction(Base, IntPK):
    __tablename__ = "imported_transaction"

    batch_id: Mapped[int] = mapped_column(ForeignKey("portfolio_import.id", ondelete="CASCADE"))
    trade_date: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    action: Mapped[str] = mapped_column(String(24), default="")
    symbol: Mapped[str] = mapped_column(String(16), index=True, default="")
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), default=None)
    price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), default=None)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), default=None)
    source_row: Mapped[int] = mapped_column(Integer)

    batch: Mapped[PortfolioImport] = relationship(back_populates="transactions")
