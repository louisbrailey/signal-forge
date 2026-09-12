"""grid strategy tables (mechanical grid — not promotion-gated)

Additive only: two brand-new tables, plain ``create_table``. No existing table
is touched and no ``batch_alter_table`` is used, so this migration is safe to
apply to the live paper-probation database while the worker runs.

Revision ID: f1c4a8b2d6e7
Revises: e5a1b7c3d9f2
Create Date: 2026-09-11 21:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import signalforge.db.types

revision: str = "f1c4a8b2d6e7"
down_revision: str | None = "e5a1b7c3d9f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # New tables only — no batch_alter_table on any existing table.
    op.create_table(
        "grid_position",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("qty", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("cost_basis", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("anchor_price", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("opened_at", signalforge.db.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at", signalforge.db.types.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["paper_account.id"],
            name="fk_grid_position_account_id_paper_account",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_grid_position"),
        sa.UniqueConstraint("account_id", "symbol", name="uq_grid_position_account_sym"),
    )
    op.create_index("ix_grid_position_symbol", "grid_position", ["symbol"])

    op.create_table(
        "grid_trade",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("side", sa.String(length=4), nullable=False),
        sa.Column("qty", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("price", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("usd", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("anchor_before", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("anchor_after", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("created_at", signalforge.db.types.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["paper_account.id"],
            name="fk_grid_trade_account_id_paper_account",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_grid_trade"),
        # Idempotency for the daily job: at most one grid trade per symbol per session.
        sa.UniqueConstraint(
            "account_id", "symbol", "session_date", name="uq_grid_trade_sym_session"
        ),
    )
    op.create_index("ix_grid_trade_symbol", "grid_trade", ["symbol"])
    op.create_index("ix_grid_trade_session_date", "grid_trade", ["session_date"])
    op.create_index("ix_grid_trade_created_at", "grid_trade", ["created_at"])


def downgrade() -> None:
    op.drop_table("grid_trade")
    op.drop_table("grid_position")
