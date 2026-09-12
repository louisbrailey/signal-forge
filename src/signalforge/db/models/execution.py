"""Execution-layer tables (D6 ADR §16).

Three tables, all of them inert until an operator arms a strategy version —
which this phase (I-E2) deliberately provides no way to do:

* ``armed_strategy``  — the per-version, expiring authority to OPEN. Written by
  the arming ceremony (I-E4); read here so a precondition can refuse without it.
* ``execution_limits`` — one active row, versioned by supersession, never
  edited. Every numeric column carries its unit in its name (§4.1): where
  decision 4 states a dollar cap and map §3.2 states a percent-of-equity cap,
  BOTH are stored and the binding limit is the tighter of the two.
* ``execution_event`` — the append-only audit spine. SQLite BEFORE UPDATE /
  BEFORE DELETE triggers are the mechanism (§15); an ORM exception class is
  not, and must never be mistaken for one.

No row in any of these tables authorises anything on its own: opening requires
every §5 precondition and every §7 ``may_open`` limit to pass in the same cycle.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from signalforge.db.base import Base, IntPK
from signalforge.db.types import UTCDateTime


class ArmedStrategy(Base, IntPK):
    """The revocable, expiring authority to submit OPENING orders for one
    strategy version against one adapter (§12).

    This is deliberately NOT a fourth ``StrategyStatus`` value: it is a
    separate record layered on top of PAPER_APPROVED, so no existing code path
    can mistake it for "approved enough" (map §0.1 B2). Disarming sets
    ``disarmed_at``/``disarm_reason`` and writes an ``execution_event``; the row
    itself is never deleted, because reconciliation and the ``is_paper`` proof
    read the most recent row for an adapter *including* disarmed and expired
    ones (§13 rule 4b) — disarming ends the authority to open, not the record of
    which account this adapter was pointed at.
    """

    __tablename__ = "armed_strategy"

    strategy_version_id: Mapped[int] = mapped_column(
        ForeignKey("strategy_version.id", ondelete="CASCADE"), index=True
    )
    structure_type: Mapped[str] = mapped_column(String(40), default="equity")
    armed_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    armed_by: Mapped[str] = mapped_column(String(60), default="local-user")
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    adapter_name: Mapped[str] = mapped_column(String(40), index=True)
    broker_account_id_expected: Mapped[str] = mapped_column(String(120))
    options_approval_level_asserted: Mapped[int | None] = mapped_column(Integer, default=None)

    max_notional_usd: Mapped[float] = mapped_column(Float)
    max_orders_per_day: Mapped[int] = mapped_column(Integer)

    # Decision 10: >= 20 closed paper trades with non-negative expectancy, or an
    # audited override. The override is taken AFTER seeing the outcome, so what
    # was seen is part of the record: both evidence columns are required
    # whenever a reason is present (enforced in the arming CLI, I-E4).
    evidence_paper_trade_count: Mapped[int | None] = mapped_column(Integer, default=None)
    evidence_expectancy_r: Mapped[float | None] = mapped_column(Float, default=None)
    evidence_override_reason: Mapped[str | None] = mapped_column(Text, default=None)

    # Multiplicity at the moment risk is taken (§12 step 1): count_sealed_looks()
    # for the FAMILY at arm time, and the pre-registration document the sealed
    # test traces to.
    sealed_look_prior_at_arm: Mapped[int | None] = mapped_column(Integer, default=None)
    preregistration_doc_id: Mapped[str] = mapped_column(String(120), default="")
    execution_limits_id: Mapped[int | None] = mapped_column(
        ForeignKey("execution_limits.id", ondelete="RESTRICT"), default=None
    )

    spec_json_hash: Mapped[str] = mapped_column(String(64), default="")
    config_hash: Mapped[str] = mapped_column(String(64), default="")
    dataset_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_snapshot.id", ondelete="SET NULL"), default=None
    )

    disarmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    disarm_reason: Mapped[str] = mapped_column(String(200), default="")


class ExecutionLimits(Base, IntPK):
    """One active row (``superseded_at IS NULL``), versioned by supersession and
    never edited (§7, §7b).

    A missing or unparseable row BLOCKS opening: the limits are not optional,
    and "no limits row" is not "no limits". Superseding a row resets the
    decision-10 live-evidence counter for every strategy armed under it (§7b
    rule 3), which is why ``execution_event`` and ``armed_strategy`` both carry
    ``execution_limits_id``.
    """

    __tablename__ = "execution_limits"

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    created_by: Mapped[str] = mapped_column(String(60), default="local-user")
    superseded_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None, index=True)

    # -- capital limits: both forms stored, the tighter binds (§4.1) ----------
    max_orders_per_day: Mapped[int] = mapped_column(Integer)
    max_order_notional_usd: Mapped[float] = mapped_column(Float)
    max_account_exposure_pct: Mapped[float] = mapped_column(Float)
    per_structure_max_loss_usd: Mapped[float] = mapped_column(Float)
    per_structure_max_loss_pct: Mapped[float] = mapped_column(Float)
    aggregate_open_max_loss_usd: Mapped[float] = mapped_column(Float)
    aggregate_open_max_loss_pct: Mapped[float] = mapped_column(Float)
    collateral_cap_usd: Mapped[float] = mapped_column(Float)
    collateral_cap_pct: Mapped[float] = mapped_column(Float)
    max_net_delta_notional_usd: Mapped[float] = mapped_column(Float)
    max_net_vega_per_volpt_usd: Mapped[float] = mapped_column(Float)

    # -- timing parameters: pre-registered with a declared grid (§7b) ---------
    cycle_interval_s: Mapped[int] = mapped_column(Integer)
    max_intent_age_minutes: Mapped[int] = mapped_column(Integer)
    max_reconciliation_age_s: Mapped[int] = mapped_column(Integer)
    execution_stale_after_s: Mapped[int] = mapped_column(Integer)
    drain_timeout_s: Mapped[int] = mapped_column(Integer)
    no_submit_after_open_minutes: Mapped[int] = mapped_column(Integer)
    no_submit_before_close_minutes: Mapped[int] = mapped_column(Integer)

    buying_power_tolerance_usd: Mapped[float] = mapped_column(Float)
    buying_power_tolerance_pct: Mapped[float] = mapped_column(Float)
    round_trips_per_5_sessions_max: Mapped[int] = mapped_column(Integer)
    pdt_equity_threshold_usd: Mapped[float] = mapped_column(Float)

    # §7b rule 1: no row without a pre-registration document.
    preregistration_doc_id: Mapped[str] = mapped_column(String(120))


class ExecutionEvent(Base, IntPK):
    """APPEND-ONLY execution audit record (§15).

    Immutability is enforced by the ``execution_event_no_update`` /
    ``execution_event_no_delete`` SQLite triggers created in the same migration
    that creates this table — the same mechanism as ``paper_trade`` (S9).
    Corrections are new rows, never edits.

    Every row carries ``config_hash`` and ``spec_json_hash`` because the
    2026-09-11 config-hash incident was detectable only because the scope match
    was recorded.
    """

    __tablename__ = "execution_event"
    __table_args__ = (
        Index("ix_execution_event_client_order_id", "client_order_id"),
        Index("ix_execution_event_ts", "ts"),
        Index("ix_execution_event_strategy_ts", "strategy_version_id", "ts"),
    )

    ts: Mapped[datetime] = mapped_column(UTCDateTime)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    client_order_id: Mapped[str] = mapped_column(String(64), default="")
    source_paper_trade_id: Mapped[int | None] = mapped_column(
        ForeignKey("paper_trade.id", ondelete="SET NULL"), default=None
    )
    # The options ledger (map §3.6) does not exist yet, so this column carries
    # no foreign key: it is the placeholder the options stream fills once
    # `assert_options_auto_simulate_allowed` and the options trade table land.
    # No options intent can be built until then (§5.3b rule 4).
    source_options_trade_id: Mapped[int | None] = mapped_column(Integer, default=None)
    strategy_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("strategy_version.id", ondelete="SET NULL"), default=None
    )
    armed_strategy_id: Mapped[int | None] = mapped_column(
        ForeignKey("armed_strategy.id", ondelete="SET NULL"), default=None
    )
    adapter_name: Mapped[str] = mapped_column(String(40), default="", index=True)
    state_from: Mapped[str] = mapped_column(String(16), default="")
    state_to: Mapped[str] = mapped_column(String(16), default="")
    execution_limits_id: Mapped[int | None] = mapped_column(
        ForeignKey("execution_limits.id", ondelete="SET NULL"), default=None
    )
    intent_kind: Mapped[str] = mapped_column(String(20), default="")
    reason: Mapped[str] = mapped_column(String(300), default="")

    config_hash: Mapped[str] = mapped_column(String(64), default="")
    spec_json_hash: Mapped[str] = mapped_column(String(64), default="")
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    raw_status_verbatim: Mapped[str] = mapped_column(Text, default="")
    error_verbatim: Mapped[str] = mapped_column(Text, default="")

    # Cost-model feedback (§4.2): the first place in this program's history
    # where a realized spread is observable. Disclosed, never used to justify a
    # looser cost model inside the same version (R3).
    modelled_fill_price: Mapped[float | None] = mapped_column(Float, default=None)
    modelled_spread_bps: Mapped[float | None] = mapped_column(Float, default=None)
    realized_fill_price: Mapped[float | None] = mapped_column(Float, default=None)
    realized_minus_modelled_bps: Mapped[float | None] = mapped_column(Float, default=None)
    leg_index: Mapped[int | None] = mapped_column(Integer, default=None)


class PaperReferenceOrder(Base, IntPK):
    """The ``paper_reference`` simulator's OWN book, made durable (D6 §3.1).

    The adapter used to hold its book in a Python dict, which made it useless
    for the one thing reconciliation is for: a fresh instance — the next cycle,
    or the next process — started FLAT and therefore reconciled CLEAN because it
    held nothing, not because anything had been explained. "Clean because we
    forgot" is the failure mode §10 exists to prevent, so the simulator's book
    outlives the object.

    This table is the SIMULATOR's, not the OMS's. ``execution_event`` remains the
    OMS's append-only record of what it did; this is the broker side of the same
    story, and reconciliation compares the two. They are deliberately separate
    tables written by separate code: a reconciliation whose two sides are the
    same rows is not a reconciliation.

    Rows are keyed by ``client_order_id`` and are UPDATED in place as the
    simulated order's state moves — this is a broker's book, not an audit log,
    and no immutability trigger belongs on it.
    """

    __tablename__ = "paper_reference_order"
    __table_args__ = (
        Index("ix_paper_reference_order_account", "account_id"),
        Index("ix_paper_reference_order_fingerprint", "account_id", "fingerprint"),
    )

    #: The simulated account this order belongs to. One adapter answers for one
    #: account (§13), and two accounts must not share a book.
    account_id: Mapped[str] = mapped_column(String(120))
    client_order_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    broker_order_id: Mapped[str] = mapped_column(String(64), default="")
    #: The economic fingerprint §5.4 / A1 dedupes on — a fresh id is not a fresh
    #: order, and that rule has to survive a restart too.
    fingerprint: Mapped[str] = mapped_column(String(64), default="")
    state: Mapped[str] = mapped_column(String(16))
    submitted_at: Mapped[datetime] = mapped_column(UTCDateTime)

    legs_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    requested_units: Mapped[int] = mapped_column(Integer, default=0)
    filled_units: Mapped[int] = mapped_column(Integer, default=0)
    leg_fill_prices_json: Mapped[list[float]] = mapped_column(JSON, default=list)
    net_fill_price: Mapped[float] = mapped_column(Float, default=0.0)

    intent_kind: Mapped[str] = mapped_column(String(20), default="")
    structure_type: Mapped[str] = mapped_column(String(40), default="")
    raw_status_verbatim: Mapped[str] = mapped_column(Text, default="")
    error_verbatim: Mapped[str] = mapped_column(Text, default="")

    source_paper_trade_id: Mapped[int | None] = mapped_column(Integer, default=None)
    strategy_version_id: Mapped[int | None] = mapped_column(Integer, default=None)
    armed_strategy_id: Mapped[int | None] = mapped_column(Integer, default=None)
    execution_limits_id: Mapped[int | None] = mapped_column(Integer, default=None)
    config_hash: Mapped[str] = mapped_column(String(64), default="")
    spec_json_hash: Mapped[str] = mapped_column(String(64), default="")
    modelled_fill_price: Mapped[float] = mapped_column(Float, default=0.0)
    modelled_spread_bps: Mapped[float] = mapped_column(Float, default=0.0)
