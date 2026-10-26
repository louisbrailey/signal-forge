"""currency_sealed_test: one-time sealed-year lock for FX/crypto research

PURELY ADDITIVE: one new table and nothing else. Unique per
(market, version, strategy_key) so each pre-registered strategy version can
see its sealed year exactly once.

Revision ID: c9e6a3b1d4f7
Revises: b8d4f2a0c3e5
Create Date: 2026-10-25 14:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import signalforge.db.types

revision: str = "c9e6a3b1d4f7"
down_revision: str | None = "b8d4f2a0c3e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "currency_sealed_test",
        sa.Column("market", sa.String(length=16), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("strategy_key", sa.String(length=64), nullable=False),
        sa.Column("sealed_from", sa.Date(), nullable=False),
        sa.Column("sealed_to", sa.Date(), nullable=False),
        sa.Column("pairs", sa.JSON(), nullable=False),
        sa.Column("data_sha256", sa.String(length=64), nullable=False),
        sa.Column("dev_summary", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("verdict", sa.String(length=16), nullable=False),
        sa.Column("evaluated_at", signalforge.db.types.UTCDateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", signalforge.db.types.UTCDateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_currency_sealed_test")),
        sa.UniqueConstraint(
            "market", "version", "strategy_key", name=op.f("uq_currency_sealed_test_market")
        ),
    )
    with op.batch_alter_table("currency_sealed_test", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_currency_sealed_test_created_at"), ["created_at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("currency_sealed_test", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_currency_sealed_test_created_at"))
    op.drop_table("currency_sealed_test")
