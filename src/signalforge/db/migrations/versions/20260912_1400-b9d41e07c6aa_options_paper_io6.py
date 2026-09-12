"""options paper mechanics I-O6: separate account tables, collateral ledger, second guard

PURELY ADDITIVE. Seven brand-new tables and two added columns; no column is
dropped, renamed, retyped, or made non-nullable on existing data, and no
existing index or constraint is touched. This rule has **no exceptions** in this
migration — in particular ``instrument.instrument_type`` is NOT retyped: this
design introduces no new ``instrument_type`` value at all (the discriminator is
``candidate.structure_kind``), and ``instrument`` has ~2,658 rows and 14 FK
children, so a batch rebuild there would have a cascade blast radius for nothing.

What it creates:

* ``candidate_option_structure`` — the legs an options candidate proposes.
* ``options_position`` / ``options_position_leg`` — the multi-leg structure and
  its legs, each leg carrying the contract multiplier copied from
  ``option_contract`` at entry, and the structure carrying the collateral held.
* ``options_trade`` — the IMMUTABLE evidence snapshot (S9-style triggers below).
* ``options_collateral_entry`` — the append-only buying-power ledger.
* ``options_mark`` — the append-only per-session mark.
* ``options_reconcile_report`` — the dated, positive precondition the second
  guard reads (a MISSING row refuses exactly as a divergent row refuses).

Two added columns, both with a server default so every existing row migrates to
a byte-identical state plus the default:

* ``paper_account.collateral_reserved`` DEFAULT 0 — 0 on the live equity
  account, so ``spendable_cash == cash`` there and no equity arithmetic moves.
* ``candidate.structure_kind`` NULL — NULL on every existing candidate.

Both use ``op.batch_alter_table``: SQLite needs the table rebuild even to add a
column with a server default. ``paper_account`` and ``candidate`` are small
(1 row and a few thousand); neither is the parent of the sealed-look ledger.

Immutability triggers are created on the four append-only tables with the same
``RAISE(ABORT, ...)`` shape and the same ``dialect.name in {"sqlite"}`` guard as
``paper_trade_no_update`` / ``paper_trade_no_delete``, and are dropped
symmetrically in ``downgrade()``.

Before running this against the live probation database: stop the worker and
copy the file. The copy is the rollback. No ``PaperAccount`` row is inserted —
the options account is created deliberately by the operator with
``signalforge paper init --name options --cash 25000``, so its creation is an
operator action with a timestamp rather than a schema side effect.

Revision ID: b9d41e07c6aa
Revises: a7f3c2b8e451
Create Date: 2026-09-12 14:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import signalforge.db.types

revision: str = "b9d41e07c6aa"
down_revision: str | None = "a7f3c2b8e451"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MONEY = sa.Numeric(precision=20, scale=6)

# Invariant S9, applied to the options append-only tables. Defence in depth on
# top of a repository layer that never issues UPDATE or DELETE against them.
_TRIGGER_DIALECTS = {"sqlite"}
_IMMUTABLE_TABLES: tuple[tuple[str, str], ...] = (
    ("options_trade", "options_trade is immutable (invariant S9); append a correcting row"),
    (
        "options_collateral_entry",
        "options_collateral_entry is append-only (D3 §3.1); release and re-reserve instead",
    ),
    ("options_mark", "options_mark is append-only (D3 §6)"),
    ("options_reconcile_report", "options_reconcile_report is append-only (D3 §3.4)"),
)


def _create_immutability_guards() -> None:
    if op.get_bind().dialect.name not in _TRIGGER_DIALECTS:
        return
    for table, message in _IMMUTABLE_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} "
            f"BEGIN SELECT RAISE(ABORT, '{message}'); END;"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} "
            f"BEGIN SELECT RAISE(ABORT, '{message}'); END;"
        )


def _drop_immutability_guards() -> None:
    if op.get_bind().dialect.name not in _TRIGGER_DIALECTS:
        return
    for table, _ in _IMMUTABLE_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_update")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_delete")


def upgrade() -> None:
    op.create_table(
        "candidate_option_structure",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("structure_type", sa.String(length=24), nullable=False),
        sa.Column("underlying_symbol", sa.String(length=16), nullable=False),
        sa.Column("contracts", sa.Integer(), nullable=False),
        sa.Column("legs_json", sa.JSON(), nullable=False),
        sa.Column("net_premium", sa.Float(), nullable=False),
        sa.Column("max_loss_dollars", sa.Float(), nullable=False),
        sa.Column("max_gain_dollars", sa.Float(), nullable=False),
        sa.Column("break_evens_json", sa.JSON(), nullable=False),
        sa.Column("short_leg_delta", sa.Float(), nullable=True),
        sa.Column("net_delta_shares", sa.Float(), nullable=False),
        sa.Column("net_vega_per_vol_pt", sa.Float(), nullable=False),
        sa.Column("credit_to_width", sa.Float(), nullable=True),
        sa.Column("dte_at_entry", sa.Integer(), nullable=False),
        sa.Column("signal_session", sa.Date(), nullable=True),
        sa.Column("fill_session", sa.Date(), nullable=True),
        sa.Column("created_at", signalforge.db.types.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidate.id"],
            name="fk_candidate_option_structure_candidate_id_candidate",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_candidate_option_structure"),
        sa.UniqueConstraint("candidate_id", name="uq_candidate_option_structure_candidate_id"),
    )
    op.create_index(
        "ix_candidate_option_structure_created_at", "candidate_option_structure", ["created_at"]
    )
    op.create_index(
        "ix_candidate_option_structure_underlying_symbol",
        "candidate_option_structure",
        ["underlying_symbol"],
    )

    op.create_table(
        "options_position",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=True),
        sa.Column("strategy_version_id", sa.Integer(), nullable=True),
        sa.Column("underlying_instrument_id", sa.Integer(), nullable=False),
        sa.Column("underlying_symbol", sa.String(length=16), nullable=False),
        sa.Column("structure_type", sa.String(length=24), nullable=False),
        sa.Column("contracts", sa.Integer(), nullable=False),
        sa.Column("entry_net_premium", _MONEY, nullable=False),
        sa.Column("exit_net_premium", _MONEY, nullable=True),
        sa.Column("entry_costs", _MONEY, nullable=False),
        sa.Column("exit_costs", _MONEY, nullable=False),
        sa.Column("r_dollars", _MONEY, nullable=False),
        sa.Column("collateral_reserved", _MONEY, nullable=False),
        sa.Column("strike_width", sa.Float(), nullable=False),
        sa.Column("expiration_date", sa.Date(), nullable=False),
        sa.Column("dte_at_entry", sa.Integer(), nullable=False),
        sa.Column("dte_at_exit", sa.Integer(), nullable=True),
        sa.Column("profit_target_pct_of_credit", sa.Float(), nullable=False),
        sa.Column("stop_multiple_of_credit", sa.Float(), nullable=False),
        sa.Column("time_stop_dte", sa.Integer(), nullable=False),
        sa.Column("signal_session", sa.Date(), nullable=True),
        sa.Column("fill_session", sa.Date(), nullable=True),
        sa.Column("opened_at", signalforge.db.types.UTCDateTime(), nullable=False),
        sa.Column("closed_at", signalforge.db.types.UTCDateTime(), nullable=True),
        sa.Column("exit_reason", sa.String(length=32), nullable=True),
        sa.Column("exit_signalled_at", sa.Date(), nullable=True),
        sa.Column("exit_deferred_sessions", sa.Integer(), nullable=False),
        sa.Column("realized_pnl", _MONEY, nullable=False),
        sa.Column("pnl_r", sa.Float(), nullable=True),
        sa.Column("r_clamped", sa.Boolean(), nullable=False),
        sa.Column("pin_risk_flag", sa.Boolean(), nullable=False),
        sa.Column("assignment_risk_flag", sa.Boolean(), nullable=False),
        sa.Column("forced_close_no_print", sa.Boolean(), nullable=False),
        sa.Column("fill_model", sa.String(length=200), nullable=False),
        sa.Column("iv_source", sa.String(length=32), nullable=False),
        sa.Column("q_source", sa.String(length=48), nullable=False),
        sa.Column("greeks_source", sa.String(length=32), nullable=False),
        sa.Column("created_at", signalforge.db.types.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["paper_account.id"],
            name="fk_options_position_account_id_paper_account",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidate.id"],
            name="fk_options_position_candidate_id_candidate",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["strategy_version_id"],
            ["strategy_version.id"],
            name="fk_options_position_strategy_version_id_strategy_version",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["underlying_instrument_id"],
            ["instrument.id"],
            name="fk_options_position_underlying_instrument_id_instrument",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_options_position"),
    )
    op.create_index("ix_options_position_created_at", "options_position", ["created_at"])
    op.create_index("ix_options_position_expiration_date", "options_position", ["expiration_date"])
    op.create_index(
        "ix_options_position_underlying_symbol", "options_position", ["underlying_symbol"]
    )
    op.create_index(
        "ix_options_position_account_closed", "options_position", ["account_id", "closed_at"]
    )
    op.create_index(
        "ix_options_position_underlying_closed",
        "options_position",
        ["underlying_instrument_id", "closed_at"],
    )
    op.create_index(
        "ix_options_position_version_closed",
        "options_position",
        ["strategy_version_id", "closed_at"],
    )

    op.create_table(
        "options_position_leg",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("position_id", sa.Integer(), nullable=False),
        sa.Column("option_contract_id", sa.Integer(), nullable=True),
        sa.Column("option_ticker", sa.String(length=40), nullable=False),
        sa.Column("right", sa.String(length=4), nullable=False),
        sa.Column("strike", sa.Float(), nullable=False),
        sa.Column("expiration_date", sa.Date(), nullable=False),
        sa.Column("qty_signed", sa.Integer(), nullable=False),
        sa.Column("shares_per_contract", sa.Integer(), nullable=False),
        sa.Column("exercise_style", sa.String(length=12), nullable=False),
        sa.Column("entry_print", _MONEY, nullable=False),
        sa.Column("entry_price", _MONEY, nullable=False),
        sa.Column("entry_spread_cost", _MONEY, nullable=False),
        sa.Column("entry_commission", _MONEY, nullable=False),
        sa.Column("exit_price", _MONEY, nullable=True),
        sa.Column("exit_spread_cost", _MONEY, nullable=False),
        sa.Column("exit_commission", _MONEY, nullable=False),
        sa.Column("exit_intrinsic_floor_applied", sa.Boolean(), nullable=False),
        sa.Column("created_at", signalforge.db.types.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["option_contract_id"],
            ["option_contract.id"],
            name="fk_options_position_leg_option_contract_id_option_contract",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["position_id"],
            ["options_position.id"],
            name="fk_options_position_leg_position_id_options_position",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_options_position_leg"),
        sa.UniqueConstraint("position_id", "option_ticker", name="uq_options_position_leg_ticker"),
    )
    op.create_index("ix_options_position_leg_created_at", "options_position_leg", ["created_at"])
    op.create_index("ix_options_position_leg_position_id", "options_position_leg", ["position_id"])
    op.create_index(
        "ix_options_position_leg_option_ticker", "options_position_leg", ["option_ticker"]
    )

    op.create_table(
        "options_trade",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=True),
        sa.Column("options_position_id", sa.Integer(), nullable=True),
        sa.Column("strategy_version_id", sa.Integer(), nullable=True),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("structure_type", sa.String(length=24), nullable=False),
        sa.Column("underlying_symbol", sa.String(length=16), nullable=False),
        sa.Column("signal_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("plan_json", sa.JSON(), nullable=False),
        sa.Column("why_qualified", sa.Text(), nullable=False),
        sa.Column("why_might_fail", sa.Text(), nullable=False),
        sa.Column("r_dollars", _MONEY, nullable=False),
        sa.Column("collateral_reserved", _MONEY, nullable=False),
        sa.Column("refused", sa.Boolean(), nullable=False),
        sa.Column("refused_condition", sa.String(length=4), nullable=False),
        sa.Column("actor", sa.String(length=60), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", signalforge.db.types.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["paper_account.id"],
            name="fk_options_trade_account_id_paper_account",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidate.id"],
            name="fk_options_trade_candidate_id_candidate",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["options_position_id"],
            ["options_position.id"],
            name="fk_options_trade_options_position_id_options_position",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["strategy_version_id"],
            ["strategy_version.id"],
            name="fk_options_trade_strategy_version_id_strategy_version",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_options_trade"),
    )
    op.create_index("ix_options_trade_created_at", "options_trade", ["created_at"])
    op.create_index("ix_options_trade_actor", "options_trade", ["actor"])
    op.create_index("ix_options_trade_underlying_symbol", "options_trade", ["underlying_symbol"])
    op.create_index(
        "ix_options_trade_account_created", "options_trade", ["account_id", "created_at"]
    )

    op.create_table(
        "options_collateral_entry",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("position_id", sa.Integer(), nullable=False),
        sa.Column("event", sa.String(length=16), nullable=False),
        sa.Column("amount", _MONEY, nullable=False),
        sa.Column("basis_json", sa.JSON(), nullable=False),
        sa.Column("balance_after", _MONEY, nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("created_at", signalforge.db.types.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["paper_account.id"],
            name="fk_options_collateral_entry_account_id_paper_account",
            ondelete="CASCADE",
        ),
        # RESTRICT, never CASCADE: a collateral entry may never be orphaned by a
        # structure being deleted, because the ledger is the audit of the
        # buying power that structure held.
        sa.ForeignKeyConstraint(
            ["position_id"],
            ["options_position.id"],
            name="fk_options_collateral_entry_position_id_options_position",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_options_collateral_entry"),
    )
    op.create_index(
        "ix_options_collateral_entry_created_at", "options_collateral_entry", ["created_at"]
    )
    op.create_index(
        "ix_options_collateral_entry_position_id", "options_collateral_entry", ["position_id"]
    )
    op.create_index(
        "ix_options_collateral_entry_account_asof",
        "options_collateral_entry",
        ["account_id", "as_of"],
    )

    op.create_table(
        "options_mark",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("position_id", sa.Integer(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("net_premium", _MONEY, nullable=False),
        sa.Column("unrealized_pnl", _MONEY, nullable=False),
        sa.Column("net_delta_shares", sa.Float(), nullable=False),
        sa.Column("net_delta_notional", sa.Float(), nullable=False),
        sa.Column("net_vega_per_vol_pt", sa.Float(), nullable=False),
        sa.Column("short_leg_delta", sa.Float(), nullable=True),
        sa.Column("synthetic", sa.Boolean(), nullable=False),
        sa.Column("iv_unavailable", sa.Boolean(), nullable=False),
        sa.Column("legs_priced", sa.Integer(), nullable=False),
        sa.Column("legs_total", sa.Integer(), nullable=False),
        sa.Column("iv_source", sa.String(length=32), nullable=False),
        sa.Column("surface_contracts_used", sa.Integer(), nullable=True),
        sa.Column("exit_reason", sa.String(length=32), nullable=True),
        sa.Column("created_at", signalforge.db.types.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["position_id"],
            ["options_position.id"],
            name="fk_options_mark_position_id_options_position",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_options_mark"),
        sa.UniqueConstraint("position_id", "as_of", name="uq_options_mark_pos_asof"),
    )
    op.create_index("ix_options_mark_created_at", "options_mark", ["created_at"])
    op.create_index("ix_options_mark_position_id", "options_mark", ["position_id"])
    op.create_index("ix_options_mark_as_of", "options_mark", ["as_of"])

    op.create_table(
        "options_reconcile_report",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("clean", sa.Boolean(), nullable=False),
        sa.Column("findings_json", sa.JSON(), nullable=False),
        sa.Column("collateral_reserved_observed", _MONEY, nullable=False),
        sa.Column("collateral_reserved_expected", _MONEY, nullable=False),
        sa.Column("open_structures", sa.Integer(), nullable=False),
        sa.Column("created_at", signalforge.db.types.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["paper_account.id"],
            name="fk_options_reconcile_report_account_id_paper_account",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_options_reconcile_report"),
        sa.UniqueConstraint("account_id", "as_of", name="uq_options_reconcile_report_acct_asof"),
    )
    op.create_index(
        "ix_options_reconcile_report_created_at", "options_reconcile_report", ["created_at"]
    )
    op.create_index("ix_options_reconcile_report_as_of", "options_reconcile_report", ["as_of"])

    # --- the two additive ALTERs -------------------------------------------
    # server_default is what makes them additive on existing rows: the live
    # equity account migrates to collateral_reserved = 0, so spendable_cash
    # equals cash there and no equity arithmetic moves.
    with op.batch_alter_table("paper_account") as batch:
        batch.add_column(
            sa.Column("collateral_reserved", _MONEY, nullable=False, server_default="0")
        )
    with op.batch_alter_table("candidate") as batch:
        batch.add_column(sa.Column("structure_kind", sa.String(length=16), nullable=True))

    _create_immutability_guards()


def downgrade() -> None:
    _drop_immutability_guards()

    with op.batch_alter_table("candidate") as batch:
        batch.drop_column("structure_kind")
    with op.batch_alter_table("paper_account") as batch:
        batch.drop_column("collateral_reserved")

    op.drop_table("options_reconcile_report")
    op.drop_table("options_mark")
    op.drop_table("options_collateral_entry")
    op.drop_table("options_trade")
    op.drop_table("options_position_leg")
    op.drop_table("options_position")
    op.drop_table("candidate_option_structure")
