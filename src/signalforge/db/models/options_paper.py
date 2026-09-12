"""Options paper-trading tables (D3, track I-O6) — a **sibling** of ``paper.py``.

Every table here is new. ``paper_position`` / ``paper_trade`` are not reused, and
that is the structural decision of D3 §13:

* ``research.health_monitor._paper_returns_r`` and
  ``research.paper_probation._paper_trade_summary`` read ``paper_position``
  filtered on ``strategy_version_id`` with **no account filter**, and both
  silently skip a row whose ``stop_level`` is NULL. An options structure stored
  as a ``PaperPosition`` would therefore be mis-measured, or invisible to the
  health monitor — and invisible means never downgraded, a fail-open in the one
  place the system must fail closed. A separate table makes both readers blind by
  default, so an options branch has to be written explicitly.
* A structure's P&L is a *net premium* across legs, not a per-share price times a
  quantity, so ``avg_price`` / ``qty`` / ``stop_level`` have no honest value.

Immutability (invariant S9, the ``paper_trade`` precedent): ``options_trade``,
``options_collateral_entry``, ``options_mark`` and ``options_reconcile_report``
are append-only. The mechanism is the pair of SQLite BEFORE UPDATE / BEFORE
DELETE triggers created in the same migration — an ORM exception class is not a
mechanism and must never be mistaken for one.

Nothing in this module is a brokerage order. Every row is SIMULATED, on a
dedicated options paper account.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
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

from signalforge.db.base import Base, CreatedAt, IntPK
from signalforge.db.types import UTCDateTime
from signalforge.domain import PaperDecision

__all__ = [
    "CandidateOptionStructure",
    "OptionsCollateralEntry",
    "OptionsMark",
    "OptionsPosition",
    "OptionsPositionLeg",
    "OptionsReconcileReport",
    "OptionsTrade",
]

_ENUM_KW: dict[str, Any] = {"native_enum": False, "length": 32, "validate_strings": True}
_MONEY = Numeric(20, 6)


class CandidateOptionStructure(Base, IntPK, CreatedAt):
    """The multi-leg structure an options ``Candidate`` proposes (D3 §10.1).

    ``Candidate.instrument_id`` points at the **underlying** (SPY is an ``etf``),
    so the equity guard's instrument-type check cannot discriminate an options
    candidate — it would pass. ``Candidate.structure_kind`` is the positive
    discriminator that closes that hole, and this row carries what the structure
    actually is. One row per candidate at most.
    """

    __tablename__ = "candidate_option_structure"
    __table_args__ = (
        UniqueConstraint("candidate_id", name="uq_candidate_option_structure_candidate_id"),
    )

    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidate.id", ondelete="CASCADE"))
    structure_type: Mapped[str] = mapped_column(String(24))
    underlying_symbol: Mapped[str] = mapped_column(String(16), index=True)
    contracts: Mapped[int] = mapped_column(Integer, default=1)
    # [{option_ticker, right, strike, expiration, qty_signed, shares_per_contract,
    #   exercise_style, entry_print}] — the legs as proposed, before any fill.
    legs_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    net_premium: Mapped[float] = mapped_column(Float, default=0.0)  # signed: credit > 0
    max_loss_dollars: Mapped[float] = mapped_column(Float, default=0.0)  # R
    max_gain_dollars: Mapped[float] = mapped_column(Float, default=0.0)
    break_evens_json: Mapped[list[float]] = mapped_column(JSON, default=list)
    short_leg_delta: Mapped[float | None] = mapped_column(Float, default=None)
    net_delta_shares: Mapped[float] = mapped_column(Float, default=0.0)
    net_vega_per_vol_pt: Mapped[float] = mapped_column(Float, default=0.0)
    credit_to_width: Mapped[float | None] = mapped_column(Float, default=None)
    dte_at_entry: Mapped[int] = mapped_column(Integer, default=0)
    signal_session: Mapped[date | None] = mapped_column(Date, default=None)
    fill_session: Mapped[date | None] = mapped_column(Date, default=None)


class OptionsPosition(Base, IntPK, CreatedAt):
    """One open (or closed) multi-leg options structure on the options account.

    ``r_dollars`` is the structure's max loss at entry **after entry costs** — the
    denominator every ``pnl_r`` here is divided by, and the quantity every capital
    limit in D3 §5 is stated against. ``collateral_reserved`` is the buying power
    this structure holds; the signed sum of its ``options_collateral_entry`` rows
    must equal it at all times (reconcile check 3/4).
    """

    __tablename__ = "options_position"
    __table_args__ = (
        Index("ix_options_position_account_closed", "account_id", "closed_at"),
        Index("ix_options_position_underlying_closed", "underlying_instrument_id", "closed_at"),
        Index("ix_options_position_version_closed", "strategy_version_id", "closed_at"),
    )

    account_id: Mapped[int] = mapped_column(ForeignKey("paper_account.id", ondelete="CASCADE"))
    candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("candidate.id", ondelete="SET NULL"), default=None
    )
    strategy_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("strategy_version.id", ondelete="SET NULL"), default=None
    )
    # The UNDERLYING, never a contract: D3 §10.2 condition X is keyed on it,
    # because a multi-leg structure spans several contract rows and an
    # instrument-keyed check would not stop a second structure on the same name.
    underlying_instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instrument.id", ondelete="CASCADE")
    )
    underlying_symbol: Mapped[str] = mapped_column(String(16), index=True)
    structure_type: Mapped[str] = mapped_column(String(24))
    contracts: Mapped[int] = mapped_column(Integer, default=1)

    entry_net_premium: Mapped[Decimal] = mapped_column(_MONEY)  # signed: credit > 0
    exit_net_premium: Mapped[Decimal | None] = mapped_column(_MONEY, default=None)
    entry_costs: Mapped[Decimal] = mapped_column(_MONEY, default=Decimal("0"))
    exit_costs: Mapped[Decimal] = mapped_column(_MONEY, default=Decimal("0"))
    r_dollars: Mapped[Decimal] = mapped_column(_MONEY)
    collateral_reserved: Mapped[Decimal] = mapped_column(_MONEY, default=Decimal("0"))
    strike_width: Mapped[float] = mapped_column(Float, default=0.0)

    expiration_date: Mapped[date] = mapped_column(Date, index=True)
    dte_at_entry: Mapped[int] = mapped_column(Integer, default=0)
    dte_at_exit: Mapped[int | None] = mapped_column(Integer, default=None)

    profit_target_pct_of_credit: Mapped[float] = mapped_column(Float, default=0.5)
    stop_multiple_of_credit: Mapped[float] = mapped_column(Float, default=2.0)
    time_stop_dte: Mapped[int] = mapped_column(Integer, default=7)

    signal_session: Mapped[date | None] = mapped_column(Date, default=None)
    fill_session: Mapped[date | None] = mapped_column(Date, default=None)
    opened_at: Mapped[datetime] = mapped_column(UTCDateTime)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    # target | stop | time_stop | forced_pre_expiry | expired_worthless | assigned
    exit_reason: Mapped[str | None] = mapped_column(String(32), default=None)
    exit_signalled_at: Mapped[date | None] = mapped_column(Date, default=None)
    exit_deferred_sessions: Mapped[int] = mapped_column(Integer, default=0)

    realized_pnl: Mapped[Decimal] = mapped_column(_MONEY, default=Decimal("0"))
    pnl_r: Mapped[float | None] = mapped_column(Float, default=None)
    r_clamped: Mapped[bool] = mapped_column(Boolean, default=False)
    pin_risk_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    assignment_risk_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    forced_close_no_print: Mapped[bool] = mapped_column(Boolean, default=False)

    fill_model: Mapped[str] = mapped_column(String(200), default="")
    iv_source: Mapped[str] = mapped_column(String(32), default="")
    q_source: Mapped[str] = mapped_column(String(48), default="")
    greeks_source: Mapped[str] = mapped_column(String(32), default="")

    legs: Mapped[list[OptionsPositionLeg]] = relationship(
        back_populates="position", cascade="all, delete-orphan"
    )


class OptionsPositionLeg(Base, IntPK, CreatedAt):
    """One leg of a structure.

    ``shares_per_contract`` is **copied from the contract row at entry**, never a
    module constant: the ``x 100`` arithmetic in R and in the collateral basis is
    auditable on the row rather than assumed (D3 §9).
    """

    __tablename__ = "options_position_leg"
    __table_args__ = (
        UniqueConstraint("position_id", "option_ticker", name="uq_options_position_leg_ticker"),
    )

    position_id: Mapped[int] = mapped_column(
        ForeignKey("options_position.id", ondelete="CASCADE"), index=True
    )
    option_contract_id: Mapped[int | None] = mapped_column(
        ForeignKey("option_contract.id", ondelete="RESTRICT"), default=None
    )
    option_ticker: Mapped[str] = mapped_column(String(40), index=True)
    right: Mapped[str] = mapped_column(String(4))  # call | put
    strike: Mapped[float] = mapped_column(Float)
    expiration_date: Mapped[date] = mapped_column(Date)
    qty_signed: Mapped[int] = mapped_column(Integer)  # + long / - short, per structure
    shares_per_contract: Mapped[int] = mapped_column(Integer, default=100)
    exercise_style: Mapped[str] = mapped_column(String(12), default="american")

    entry_print: Mapped[Decimal] = mapped_column(_MONEY, default=Decimal("0"))
    entry_price: Mapped[Decimal] = mapped_column(_MONEY)  # adverse, spread-crossed
    entry_spread_cost: Mapped[Decimal] = mapped_column(_MONEY, default=Decimal("0"))
    entry_commission: Mapped[Decimal] = mapped_column(_MONEY, default=Decimal("0"))
    exit_price: Mapped[Decimal | None] = mapped_column(_MONEY, default=None)
    exit_spread_cost: Mapped[Decimal] = mapped_column(_MONEY, default=Decimal("0"))
    exit_commission: Mapped[Decimal] = mapped_column(_MONEY, default=Decimal("0"))
    exit_intrinsic_floor_applied: Mapped[bool] = mapped_column(Boolean, default=False)

    position: Mapped[OptionsPosition] = relationship(back_populates="legs")


class OptionsTrade(Base, IntPK):
    """IMMUTABLE evidence record of a decision on an options candidate (S9).

    The options twin of ``paper_trade``, deliberately a separate table: the
    equity table's readers must not see an options structure, and the snapshot
    shape is different (structure, legs, fills at the modelled spread, R,
    collateral, every limit evaluated).

    Immutability is enforced by the ``options_trade_no_update`` /
    ``options_trade_no_delete`` SQLite triggers created in the same migration.
    """

    __tablename__ = "options_trade"
    __table_args__ = (Index("ix_options_trade_account_created", "account_id", "created_at"),)

    account_id: Mapped[int] = mapped_column(ForeignKey("paper_account.id", ondelete="CASCADE"))
    candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("candidate.id", ondelete="SET NULL"), default=None
    )
    options_position_id: Mapped[int | None] = mapped_column(
        ForeignKey("options_position.id", ondelete="SET NULL"), default=None
    )
    strategy_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("strategy_version.id", ondelete="SET NULL"), default=None
    )
    decision: Mapped[PaperDecision] = mapped_column(SAEnum(PaperDecision, **_ENUM_KW))
    structure_type: Mapped[str] = mapped_column(String(24), default="")
    underlying_symbol: Mapped[str] = mapped_column(String(16), default="", index=True)

    # The complete frozen evidence snapshot: the equity snapshot's keys plus the
    # "options" block of D3 §9 (legs, fills, R, collateral, limits_evaluated,
    # disclosures, refusal condition).
    signal_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    plan_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    why_qualified: Mapped[str] = mapped_column(Text, default="")
    why_might_fail: Mapped[str] = mapped_column(Text, default="")

    r_dollars: Mapped[Decimal] = mapped_column(_MONEY, default=Decimal("0"))
    collateral_reserved: Mapped[Decimal] = mapped_column(_MONEY, default=Decimal("0"))
    refused: Mapped[bool] = mapped_column(Boolean, default=False)
    refused_condition: Mapped[str] = mapped_column(String(4), default="")

    actor: Mapped[str] = mapped_column(String(60), default="local-user", index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)


class OptionsCollateralEntry(Base, IntPK, CreatedAt):
    """APPEND-ONLY collateral ledger entry (D3 §3.1).

    ``amount`` is always POSITIVE; ``event`` carries the sign. There is
    deliberately no ``adjust`` event: Phase 1 reserves once at entry and releases
    once at exit, and the honest record of a wrong reservation is
    ``release`` + ``reserve`` (two auditable rows), never a mutation of the first.
    """

    __tablename__ = "options_collateral_entry"
    __table_args__ = (Index("ix_options_collateral_entry_account_asof", "account_id", "as_of"),)

    account_id: Mapped[int] = mapped_column(ForeignKey("paper_account.id", ondelete="CASCADE"))
    position_id: Mapped[int] = mapped_column(
        ForeignKey("options_position.id", ondelete="RESTRICT"), index=True
    )
    event: Mapped[str] = mapped_column(String(16))  # reserve | release
    amount: Mapped[Decimal] = mapped_column(_MONEY)  # always positive
    basis_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    balance_after: Mapped[Decimal] = mapped_column(_MONEY)
    as_of: Mapped[date] = mapped_column(Date)


class OptionsMark(Base, IntPK, CreatedAt):
    """APPEND-ONLY per-session mark of one structure (D3 §6).

    The four honesty counters (``synthetic``, ``iv_unavailable``, ``legs_priced``
    vs ``legs_total``) are on the row rather than summarised away: a mark taken
    from a modelled surface may trigger a signal and may never set a fill price.

    ``q_source`` / ``dividend_yield`` are the same honesty applied to the input
    decision 11 requires per UNDERLYING (W5b). There is no JSON column on this
    table to hide them in, and they cannot be inferred from the position row:
    ``options_position.q_source`` records what was used at ENTRY, while a mark is
    a different session with its own trailing-twelve-month window. A NULL
    ``dividend_yield`` means the number was not finite, never that it was zero.
    """

    __tablename__ = "options_mark"
    __table_args__ = (UniqueConstraint("position_id", "as_of", name="uq_options_mark_pos_asof"),)

    position_id: Mapped[int] = mapped_column(
        ForeignKey("options_position.id", ondelete="CASCADE"), index=True
    )
    as_of: Mapped[date] = mapped_column(Date, index=True)
    net_premium: Mapped[Decimal] = mapped_column(_MONEY)
    unrealized_pnl: Mapped[Decimal] = mapped_column(_MONEY, default=Decimal("0"))
    net_delta_shares: Mapped[float] = mapped_column(Float, default=0.0)
    net_delta_notional: Mapped[float] = mapped_column(Float, default=0.0)
    net_vega_per_vol_pt: Mapped[float] = mapped_column(Float, default=0.0)
    short_leg_delta: Mapped[float | None] = mapped_column(Float, default=None)
    synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    iv_unavailable: Mapped[bool] = mapped_column(Boolean, default=False)
    legs_priced: Mapped[int] = mapped_column(Integer, default=0)
    legs_total: Mapped[int] = mapped_column(Integer, default=0)
    iv_source: Mapped[str] = mapped_column(String(32), default="")
    q_source: Mapped[str] = mapped_column(String(48), default="", server_default="")
    dividend_yield: Mapped[float | None] = mapped_column(Float, default=None)
    surface_contracts_used: Mapped[int | None] = mapped_column(Integer, default=None)
    exit_reason: Mapped[str | None] = mapped_column(String(32), default=None)


class OptionsReconcileReport(Base, IntPK, CreatedAt):
    """APPEND-ONLY collateral-reconciliation report for one session (D3 §3.4).

    The second guard requires a row for **this** account with ``as_of`` equal to
    the current completed session and ``clean`` true. A missing row refuses
    exactly as a divergent row refuses: absence is never evidence of health.
    """

    __tablename__ = "options_reconcile_report"
    __table_args__ = (
        UniqueConstraint("account_id", "as_of", name="uq_options_reconcile_report_acct_asof"),
    )

    account_id: Mapped[int] = mapped_column(ForeignKey("paper_account.id", ondelete="CASCADE"))
    as_of: Mapped[date] = mapped_column(Date, index=True)
    clean: Mapped[bool] = mapped_column(Boolean, default=False)
    findings_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    collateral_reserved_observed: Mapped[Decimal] = mapped_column(_MONEY, default=Decimal("0"))
    collateral_reserved_expected: Mapped[Decimal] = mapped_column(_MONEY, default=Decimal("0"))
    open_structures: Mapped[int] = mapped_column(Integer, default=0)
