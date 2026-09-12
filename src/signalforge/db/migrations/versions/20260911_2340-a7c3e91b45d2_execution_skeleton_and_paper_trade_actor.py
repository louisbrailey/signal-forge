"""execution skeleton tables + paper_trade.actor

Additive. Three new tables (``execution_limits``, ``armed_strategy``,
``execution_event``) and ONE new column on an existing table
(``paper_trade.actor``), added with a plain ``ALTER TABLE ... ADD COLUMN`` and a
constant default — no ``batch_alter_table``, so ``paper_trade`` is never
rebuilt and its S9 immutability triggers are never dropped by a table copy.

Two details that are deliberate rather than incidental:

* The backfill of ``paper_trade.actor`` is an UPDATE, and ``paper_trade`` carries
  a BEFORE UPDATE trigger that aborts every UPDATE (invariant S9). The trigger is
  therefore dropped for the duration of the one-statement backfill and recreated
  immediately, in the same transaction. ``paper_trade`` has zero rows today, so
  the backfill is empty in practice; the rule is implemented anyway so it is
  correct whenever it does run.
* ``execution_event`` gets its own ``BEFORE UPDATE`` / ``BEFORE DELETE`` triggers,
  re-implemented here in the shape of the ``paper_trade`` pair rather than
  imported from anywhere. An ORM exception class is not the mechanism (D6 §15).

Revision ID: a7c3e91b45d2
Revises: f1c4a8b2d6e7
Create Date: 2026-09-11 23:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import signalforge.db.types

revision: str = "a7c3e91b45d2"
down_revision: str | None = "f1c4a8b2d6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TRIGGER_DIALECTS = {"sqlite"}


def _create_execution_event_immutability_guards() -> None:
    if op.get_bind().dialect.name not in _TRIGGER_DIALECTS:
        return
    op.execute("""
        CREATE TRIGGER execution_event_no_update
        BEFORE UPDATE ON execution_event
        BEGIN
            SELECT RAISE(ABORT, 'execution_event is immutable (D6 ADR §15); append a correcting row');
        END;
        """)
    op.execute("""
        CREATE TRIGGER execution_event_no_delete
        BEFORE DELETE ON execution_event
        BEGIN
            SELECT RAISE(ABORT, 'execution_event is append-only (D6 ADR §15)');
        END;
        """)


def _drop_execution_event_immutability_guards() -> None:
    if op.get_bind().dialect.name not in _TRIGGER_DIALECTS:
        return
    op.execute("DROP TRIGGER IF EXISTS execution_event_no_update")
    op.execute("DROP TRIGGER IF EXISTS execution_event_no_delete")


def _recreate_paper_trade_update_guard() -> None:
    if op.get_bind().dialect.name not in _TRIGGER_DIALECTS:
        return
    op.execute("""
        CREATE TRIGGER paper_trade_no_update
        BEFORE UPDATE ON paper_trade
        BEGIN
            SELECT RAISE(ABORT, 'paper_trade is immutable (invariant S9); record a trade_correction');
        END;
        """)


def _backfill_paper_trade_actor() -> None:
    """``coalesce(json_extract(signal_snapshot_json, '$.decision.actor'), 'local-user')``.

    The S9 BEFORE UPDATE trigger is dropped and recreated around the single
    statement; on a non-SQLite dialect there is no such trigger and the UPDATE
    runs on its own.
    """
    sqlite = op.get_bind().dialect.name in _TRIGGER_DIALECTS
    if sqlite:
        op.execute("DROP TRIGGER IF EXISTS paper_trade_no_update")
    op.execute(
        "UPDATE paper_trade "
        "SET actor = coalesce("
        "json_extract(signal_snapshot_json, '$.decision.actor'), 'local-user')"
    )
    if sqlite:
        _recreate_paper_trade_update_guard()


def upgrade() -> None:
    # --- 1. the new column on paper_trade (§5.3) ---------------------------
    op.add_column(
        "paper_trade",
        sa.Column(
            "actor",
            sa.String(length=60),
            nullable=False,
            server_default="local-user",
        ),
    )
    op.create_index("ix_paper_trade_actor", "paper_trade", ["actor"])
    _backfill_paper_trade_actor()

    # --- 2. execution_limits (§7b) -----------------------------------------
    op.create_table(
        "execution_limits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", signalforge.db.types.UTCDateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=60), nullable=False),
        sa.Column("superseded_at", signalforge.db.types.UTCDateTime(), nullable=True),
        sa.Column("max_orders_per_day", sa.Integer(), nullable=False),
        sa.Column("max_order_notional_usd", sa.Float(), nullable=False),
        sa.Column("max_account_exposure_pct", sa.Float(), nullable=False),
        sa.Column("per_structure_max_loss_usd", sa.Float(), nullable=False),
        sa.Column("per_structure_max_loss_pct", sa.Float(), nullable=False),
        sa.Column("aggregate_open_max_loss_usd", sa.Float(), nullable=False),
        sa.Column("aggregate_open_max_loss_pct", sa.Float(), nullable=False),
        sa.Column("collateral_cap_usd", sa.Float(), nullable=False),
        sa.Column("collateral_cap_pct", sa.Float(), nullable=False),
        sa.Column("max_net_delta_notional_usd", sa.Float(), nullable=False),
        sa.Column("max_net_vega_per_volpt_usd", sa.Float(), nullable=False),
        sa.Column("cycle_interval_s", sa.Integer(), nullable=False),
        sa.Column("max_intent_age_minutes", sa.Integer(), nullable=False),
        sa.Column("max_reconciliation_age_s", sa.Integer(), nullable=False),
        sa.Column("execution_stale_after_s", sa.Integer(), nullable=False),
        sa.Column("drain_timeout_s", sa.Integer(), nullable=False),
        sa.Column("no_submit_after_open_minutes", sa.Integer(), nullable=False),
        sa.Column("no_submit_before_close_minutes", sa.Integer(), nullable=False),
        sa.Column("buying_power_tolerance_usd", sa.Float(), nullable=False),
        sa.Column("buying_power_tolerance_pct", sa.Float(), nullable=False),
        sa.Column("round_trips_per_5_sessions_max", sa.Integer(), nullable=False),
        sa.Column("pdt_equity_threshold_usd", sa.Float(), nullable=False),
        sa.Column("preregistration_doc_id", sa.String(length=120), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_execution_limits"),
    )
    op.create_index("ix_execution_limits_created_at", "execution_limits", ["created_at"])
    op.create_index("ix_execution_limits_superseded_at", "execution_limits", ["superseded_at"])

    # --- 3. armed_strategy (§12, §16) --------------------------------------
    op.create_table(
        "armed_strategy",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("strategy_version_id", sa.Integer(), nullable=False),
        sa.Column("structure_type", sa.String(length=40), nullable=False),
        sa.Column("armed_at", signalforge.db.types.UTCDateTime(), nullable=False),
        sa.Column("armed_by", sa.String(length=60), nullable=False),
        sa.Column("expires_at", signalforge.db.types.UTCDateTime(), nullable=False),
        sa.Column("adapter_name", sa.String(length=40), nullable=False),
        sa.Column("broker_account_id_expected", sa.String(length=120), nullable=False),
        sa.Column("options_approval_level_asserted", sa.Integer(), nullable=True),
        sa.Column("max_notional_usd", sa.Float(), nullable=False),
        sa.Column("max_orders_per_day", sa.Integer(), nullable=False),
        sa.Column("evidence_paper_trade_count", sa.Integer(), nullable=True),
        sa.Column("evidence_expectancy_r", sa.Float(), nullable=True),
        sa.Column("evidence_override_reason", sa.Text(), nullable=True),
        sa.Column("sealed_look_prior_at_arm", sa.Integer(), nullable=True),
        sa.Column("preregistration_doc_id", sa.String(length=120), nullable=False),
        sa.Column("execution_limits_id", sa.Integer(), nullable=True),
        sa.Column("spec_json_hash", sa.String(length=64), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("dataset_snapshot_id", sa.Integer(), nullable=True),
        sa.Column("disarmed_at", signalforge.db.types.UTCDateTime(), nullable=True),
        sa.Column("disarm_reason", sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(
            ["strategy_version_id"],
            ["strategy_version.id"],
            name="fk_armed_strategy_strategy_version_id_strategy_version",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["execution_limits_id"],
            ["execution_limits.id"],
            name="fk_armed_strategy_execution_limits_id_execution_limits",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_snapshot_id"],
            ["data_snapshot.id"],
            name="fk_armed_strategy_dataset_snapshot_id_data_snapshot",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_armed_strategy"),
    )
    op.create_index(
        "ix_armed_strategy_strategy_version_id", "armed_strategy", ["strategy_version_id"]
    )
    op.create_index("ix_armed_strategy_adapter_name", "armed_strategy", ["adapter_name"])
    op.create_index("ix_armed_strategy_armed_at", "armed_strategy", ["armed_at"])
    op.create_index("ix_armed_strategy_expires_at", "armed_strategy", ["expires_at"])
    # PARTIAL unique indexes: at most one LIVE arming per version, and one live
    # arming per broker account (§10). A plain UNIQUE constraint here would
    # forbid ever re-arming a version, which §12 requires.
    op.create_index(
        "uq_armed_strategy_live_version",
        "armed_strategy",
        ["strategy_version_id"],
        unique=True,
        sqlite_where=sa.text("disarmed_at IS NULL"),
        postgresql_where=sa.text("disarmed_at IS NULL"),
    )
    op.create_index(
        "uq_armed_strategy_live_account",
        "armed_strategy",
        ["broker_account_id_expected"],
        unique=True,
        sqlite_where=sa.text("disarmed_at IS NULL"),
        postgresql_where=sa.text("disarmed_at IS NULL"),
    )

    # --- 4. execution_event (§15, §16) -------------------------------------
    op.create_table(
        "execution_event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ts", signalforge.db.types.UTCDateTime(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("client_order_id", sa.String(length=64), nullable=False),
        sa.Column("source_paper_trade_id", sa.Integer(), nullable=True),
        sa.Column("source_options_trade_id", sa.Integer(), nullable=True),
        sa.Column("strategy_version_id", sa.Integer(), nullable=True),
        sa.Column("armed_strategy_id", sa.Integer(), nullable=True),
        sa.Column("adapter_name", sa.String(length=40), nullable=False),
        sa.Column("state_from", sa.String(length=16), nullable=False),
        sa.Column("state_to", sa.String(length=16), nullable=False),
        sa.Column("execution_limits_id", sa.Integer(), nullable=True),
        sa.Column("intent_kind", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=300), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("spec_json_hash", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("raw_status_verbatim", sa.Text(), nullable=False),
        sa.Column("error_verbatim", sa.Text(), nullable=False),
        sa.Column("modelled_fill_price", sa.Float(), nullable=True),
        sa.Column("modelled_spread_bps", sa.Float(), nullable=True),
        sa.Column("realized_fill_price", sa.Float(), nullable=True),
        sa.Column("realized_minus_modelled_bps", sa.Float(), nullable=True),
        sa.Column("leg_index", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["source_paper_trade_id"],
            ["paper_trade.id"],
            name="fk_execution_event_source_paper_trade_id_paper_trade",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["strategy_version_id"],
            ["strategy_version.id"],
            name="fk_execution_event_strategy_version_id_strategy_version",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["armed_strategy_id"],
            ["armed_strategy.id"],
            name="fk_execution_event_armed_strategy_id_armed_strategy",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["execution_limits_id"],
            ["execution_limits.id"],
            name="fk_execution_event_execution_limits_id_execution_limits",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_execution_event"),
    )
    op.create_index("ix_execution_event_event_type", "execution_event", ["event_type"])
    op.create_index("ix_execution_event_adapter_name", "execution_event", ["adapter_name"])
    op.create_index("ix_execution_event_client_order_id", "execution_event", ["client_order_id"])
    op.create_index("ix_execution_event_ts", "execution_event", ["ts"])
    op.create_index(
        "ix_execution_event_strategy_ts", "execution_event", ["strategy_version_id", "ts"]
    )
    _create_execution_event_immutability_guards()


def downgrade() -> None:
    _drop_execution_event_immutability_guards()
    op.drop_table("execution_event")
    op.drop_index("uq_armed_strategy_live_account", table_name="armed_strategy")
    op.drop_index("uq_armed_strategy_live_version", table_name="armed_strategy")
    op.drop_table("armed_strategy")
    op.drop_table("execution_limits")
    op.drop_index("ix_paper_trade_actor", table_name="paper_trade")
    op.drop_column("paper_trade", "actor")
