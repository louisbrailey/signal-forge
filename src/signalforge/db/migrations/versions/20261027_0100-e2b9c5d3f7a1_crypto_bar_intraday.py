"""crypto_bar_intraday: hourly crypto bars for round-the-clock research

PURELY ADDITIVE: one new table. Separate from every equity table so no
equity scan, universe, Kronos or paper path can read a crypto bar.

Revision ID: e2b9c5d3f7a1
Revises: d1a8b4c2e6f9
Create Date: 2026-10-27 01:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import signalforge.db.types

revision: str = "e2b9c5d3f7a1"
down_revision: str | None = "d1a8b4c2e6f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TS = signalforge.db.types.UTCDateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "crypto_bar_intraday",
        sa.Column("pair", sa.String(length=16), nullable=False),
        sa.Column("bar_size", sa.String(length=8), nullable=False),
        sa.Column("bar_start", _TS, nullable=False),
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
        sa.Column("ingested_at", _TS, nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", _TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_crypto_bar_intraday")),
        sa.UniqueConstraint(
            "pair", "bar_size", "bar_start", "source", name=op.f("uq_crypto_bar_intraday_pair")
        ),
    )
    with op.batch_alter_table("crypto_bar_intraday", schema=None) as b:
        b.create_index(
            "ix_crypto_bar_intraday_pair_size_start",
            ["pair", "bar_size", "bar_start"],
            unique=False,
        )
        b.create_index(b.f("ix_crypto_bar_intraday_pair"), ["pair"], unique=False)
        b.create_index(b.f("ix_crypto_bar_intraday_bar_start"), ["bar_start"], unique=False)
        b.create_index(b.f("ix_crypto_bar_intraday_source"), ["source"], unique=False)
        b.create_index(b.f("ix_crypto_bar_intraday_created_at"), ["created_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("crypto_bar_intraday", schema=None) as b:
        b.drop_index(b.f("ix_crypto_bar_intraday_created_at"))
        b.drop_index(b.f("ix_crypto_bar_intraday_source"))
        b.drop_index(b.f("ix_crypto_bar_intraday_bar_start"))
        b.drop_index(b.f("ix_crypto_bar_intraday_pair"))
        b.drop_index("ix_crypto_bar_intraday_pair_size_start")
    op.drop_table("crypto_bar_intraday")
