"""dividend_yield_daily: a point-in-time per-underlying q series (decision 11, gate 0.g)

PURELY ADDITIVE: one new table and nothing else. No existing table, column,
index, constraint or trigger is touched.

Why a table rather than a computation at evaluation time: the short-vertical
strategy needs ``q`` on EVERY signal session of every underlying, and gate 0.g
needs to see what was used, per underlying, over the pre-sealed span. A
trailing yield computed ad hoc at one ``as_of`` date is neither — and the only
``as_of`` the evidence assembler had to hand was ``window.end``, a sealed date.
The series is derived from stored ``dividend_event`` rows and the stored daily
close with the same ex-date-on-or-before-S rule ``trailing_dividend_yield``
applies, so it is point-in-time by construction; a session with no dividend
history in its window has NO row, never a 0.0 row.

``derived_from_run_id`` is ``ON DELETE SET NULL``: deleting an ingestion_run
row must never silently delete the reference data it produced.

Revision ID: d2f7a1c4e9b6
Revises: c1e5a9f37b24
Create Date: 2026-10-02 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import signalforge.db.types

revision: str = "d2f7a1c4e9b6"
down_revision: str | None = "c1e5a9f37b24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dividend_yield_daily",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("q", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("payments", sa.Integer(), nullable=False),
        sa.Column("window_start", sa.Date(), nullable=False),
        sa.Column("reference_close", sa.Float(), nullable=False),
        sa.Column(
            "derived_from_run_id",
            sa.Integer(),
            sa.ForeignKey("ingestion_run.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", signalforge.db.types.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_dividend_yield_daily"),
        sa.UniqueConstraint(
            "symbol", "session_date", "source", name="uq_dividend_yield_daily_sym_sess_src"
        ),
    )
    op.create_index("ix_dividend_yield_daily_symbol", "dividend_yield_daily", ["symbol"])
    op.create_index(
        "ix_dividend_yield_daily_session_date", "dividend_yield_daily", ["session_date"]
    )
    op.create_index("ix_dividend_yield_daily_source", "dividend_yield_daily", ["source"])
    op.create_index(
        "ix_dividend_yield_daily_symbol_session", "dividend_yield_daily", ["symbol", "session_date"]
    )
    op.create_index("ix_dividend_yield_daily_created_at", "dividend_yield_daily", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_dividend_yield_daily_created_at", table_name="dividend_yield_daily")
    op.drop_index("ix_dividend_yield_daily_symbol_session", table_name="dividend_yield_daily")
    op.drop_index("ix_dividend_yield_daily_source", table_name="dividend_yield_daily")
    op.drop_index("ix_dividend_yield_daily_session_date", table_name="dividend_yield_daily")
    op.drop_index("ix_dividend_yield_daily_symbol", table_name="dividend_yield_daily")
    op.drop_table("dividend_yield_daily")
