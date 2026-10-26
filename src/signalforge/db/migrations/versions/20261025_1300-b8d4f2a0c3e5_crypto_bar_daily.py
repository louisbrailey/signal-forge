"""crypto_bar_daily: completed daily bars per crypto pair (Massive Currencies)

PURELY ADDITIVE: one new table and nothing else. No existing table, column,
index, constraint or trigger is touched. Crypto bars live apart from
``ohlcv_daily`` so no equity scan, universe, Kronos or paper path can read one.

Revision ID: b8d4f2a0c3e5
Revises: a7c3e1f9b2d4
Create Date: 2026-10-25 13:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import signalforge.db.types

revision: str = "b8d4f2a0c3e5"
down_revision: str | None = "a7c3e1f9b2d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "crypto_bar_daily",
        sa.Column("pair", sa.String(length=16), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=True),
        sa.Column("vwap", sa.Float(), nullable=True),
        sa.Column("transactions", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column(
            "latency_category",
            sa.Enum(
                "REALTIME",
                "DELAYED",
                "END_OF_DAY",
                "HISTORICAL",
                name="latencycategory",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("ingested_at", signalforge.db.types.UTCDateTime(timezone=True), nullable=False),
        sa.Column("quality_flags", sa.JSON(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", signalforge.db.types.UTCDateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_crypto_bar_daily")),
        sa.UniqueConstraint(
            "pair", "session_date", "source", name=op.f("uq_crypto_bar_daily_pair")
        ),
    )
    with op.batch_alter_table("crypto_bar_daily", schema=None) as batch_op:
        batch_op.create_index(
            "ix_crypto_bar_daily_pair_date", ["pair", "session_date"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_crypto_bar_daily_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_crypto_bar_daily_pair"), ["pair"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_crypto_bar_daily_session_date"), ["session_date"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_crypto_bar_daily_source"), ["source"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("crypto_bar_daily", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_crypto_bar_daily_source"))
        batch_op.drop_index(batch_op.f("ix_crypto_bar_daily_session_date"))
        batch_op.drop_index(batch_op.f("ix_crypto_bar_daily_pair"))
        batch_op.drop_index(batch_op.f("ix_crypto_bar_daily_created_at"))
        batch_op.drop_index("ix_crypto_bar_daily_pair_date")
    op.drop_table("crypto_bar_daily")
