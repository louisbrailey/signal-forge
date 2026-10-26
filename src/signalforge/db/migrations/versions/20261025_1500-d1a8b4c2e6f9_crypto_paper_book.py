"""crypto_paper_book + crypto_paper_trade: simulated crypto paper ledger

PURELY ADDITIVE: two new tables. No broker, order or account table is
involved; the book is a deterministic replay of the backtest engine.

Revision ID: d1a8b4c2e6f9
Revises: c9e6a3b1d4f7
Create Date: 2026-10-25 15:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import signalforge.db.types

revision: str = "d1a8b4c2e6f9"
down_revision: str | None = "c9e6a3b1d4f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TS = signalforge.db.types.UTCDateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "crypto_paper_book",
        sa.Column("strategy_key", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column(
            "sealed_test_id",
            sa.Integer(),
            sa.ForeignKey(
                "currency_sealed_test.id",
                name="fk_crypto_paper_book_sealed_test_id_currency_sealed_test",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("pairs", sa.JSON(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("observation_end", sa.Date(), nullable=False),
        sa.Column("risk_usd_per_trade", sa.Float(), nullable=False),
        sa.Column("last_cycle_at", _TS, nullable=True),
        sa.Column("last_bar_date", sa.Date(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", _TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_crypto_paper_book")),
        sa.UniqueConstraint(
            "strategy_key", "version", name=op.f("uq_crypto_paper_book_strategy_key")
        ),
    )
    with op.batch_alter_table("crypto_paper_book", schema=None) as b:
        b.create_index(b.f("ix_crypto_paper_book_created_at"), ["created_at"], unique=False)
    op.create_table(
        "crypto_paper_trade",
        sa.Column(
            "book_id",
            sa.Integer(),
            sa.ForeignKey(
                "crypto_paper_book.id",
                name="fk_crypto_paper_trade_book_id_crypto_paper_book",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("pair", sa.String(length=16), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("stop_price", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=8), nullable=False),
        sa.Column("exit_date", sa.Date(), nullable=True),
        sa.Column("exit_price", sa.Float(), nullable=True),
        sa.Column("exit_reason", sa.String(length=16), nullable=True),
        sa.Column("pnl_r", sa.Float(), nullable=True),
        sa.Column("mark_r", sa.Float(), nullable=True),
        sa.Column("marked_at", sa.Date(), nullable=True),
        sa.Column("costs_bps", sa.Float(), nullable=False),
        sa.Column("divergence", sa.String(length=300), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("bars_held", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", _TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_crypto_paper_trade")),
        sa.UniqueConstraint(
            "book_id", "pair", "entry_date", name=op.f("uq_crypto_paper_trade_book_id")
        ),
    )
    with op.batch_alter_table("crypto_paper_trade", schema=None) as b:
        b.create_index(b.f("ix_crypto_paper_trade_book_id"), ["book_id"], unique=False)
        b.create_index(b.f("ix_crypto_paper_trade_created_at"), ["created_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("crypto_paper_trade", schema=None) as b:
        b.drop_index(b.f("ix_crypto_paper_trade_created_at"))
        b.drop_index(b.f("ix_crypto_paper_trade_book_id"))
    op.drop_table("crypto_paper_trade")
    with op.batch_alter_table("crypto_paper_book", schema=None) as b:
        b.drop_index(b.f("ix_crypto_paper_book_created_at"))
    op.drop_table("crypto_paper_book")
