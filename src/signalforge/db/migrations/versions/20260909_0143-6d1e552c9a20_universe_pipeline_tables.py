"""universe pipeline tables

Revision ID:
Revises:
Create Date: 2026-09-09 01:43:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import signalforge.db.types

revision: str = "6d1e552c9a20"
down_revision: str | None = "b4e7d2c9a1f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Four brand-new tables. Hand-rewritten from the autogenerate output:
    # (1) plain op.create_index instead of batch_alter_table (batch mode
    # recreates the table — pointless on a new table and hazardous on any
    # table with incoming ON DELETE CASCADE FKs, see 2ea68f289c37);
    # (2) the autogenerate drift "alter_column" on scan_run was DROPPED — a
    # batch recreate of scan_run would CASCADE-delete every candidate row.
    op.create_table(
        "universe_ticker",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("security_type", sa.String(length=8), nullable=False),
        sa.Column("primary_exchange", sa.String(length=12), nullable=False),
        sa.Column("locale", sa.String(length=4), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("list_date", sa.Date(), nullable=True),
        sa.Column("market_cap", sa.Float(), nullable=True),
        sa.Column("sic_code", sa.String(length=8), nullable=False),
        sa.Column("sic_description", sa.String(length=160), nullable=False),
        sa.Column("first_seen", sa.Date(), nullable=False),
        sa.Column("last_seen", sa.Date(), nullable=False),
        sa.Column("refreshed_at", signalforge.db.types.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticker"),
    )
    op.create_index("ix_universe_ticker_ticker", "universe_ticker", ["ticker"])
    op.create_index("ix_universe_ticker_security_type", "universe_ticker", ["security_type"])
    op.create_index("ix_universe_ticker_active", "universe_ticker", ["active"])
    op.create_index("ix_universe_ticker_last_seen", "universe_ticker", ["last_seen"])

    op.create_table(
        "bulk_file",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("path", sa.String(length=400), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("bytes_gz", sa.Integer(), nullable=False),
        sa.Column("bytes_raw", sa.Integer(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("adjusted_as_of", sa.Date(), nullable=False),
        sa.Column("fetched_at", signalforge.db.types.UTCDateTime(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("detail", sa.String(length=300), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "session_date"),
    )
    op.create_index("ix_bulk_file_source", "bulk_file", ["source"])
    op.create_index("ix_bulk_file_session_date", "bulk_file", ["session_date"])
    op.create_index("ix_bulk_file_fetched_at", "bulk_file", ["fetched_at"])

    op.create_table(
        "universe_screen_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("screen_date", sa.Date(), nullable=False),
        sa.Column("started_at", signalforge.db.types.UTCDateTime(), nullable=False),
        sa.Column("finished_at", signalforge.db.types.UTCDateTime(), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("sessions_used", sa.Integer(), nullable=False),
        sa.Column("archive_first", sa.Date(), nullable=True),
        sa.Column("archive_last", sa.Date(), nullable=True),
        sa.Column("discovered", sa.Integer(), nullable=False),
        sa.Column("in_scope_types", sa.Integer(), nullable=False),
        sa.Column("excluded_by_reason", sa.JSON(), nullable=False),
        sa.Column("eligible", sa.Integer(), nullable=False),
        sa.Column("dataset_snapshot_id", sa.Integer(), nullable=True),
        sa.Column("adjustment_basis", sa.String(length=120), nullable=False),
        sa.Column("survivorship_note", sa.String(length=160), nullable=False),
        sa.Column("storage_bytes", sa.Integer(), nullable=False),
        sa.Column("runtime_seconds", sa.Float(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_universe_screen_run_screen_date", "universe_screen_run", ["screen_date"])
    op.create_index("ix_universe_screen_run_started_at", "universe_screen_run", ["started_at"])

    op.create_table(
        "universe_member",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("security_type", sa.String(length=8), nullable=False),
        sa.Column("last_close", sa.Float(), nullable=True),
        sa.Column("avg_dollar_volume", sa.Float(), nullable=True),
        sa.Column("market_cap", sa.Float(), nullable=True),
        sa.Column("sessions_present", sa.Integer(), nullable=False),
        sa.Column("sic_group", sa.String(length=4), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("exclusion_reasons", sa.JSON(), nullable=False),
        sa.Column("flags", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "ticker"),
    )
    op.create_index("ix_universe_member_run_id", "universe_member", ["run_id"])
    op.create_index("ix_universe_member_ticker", "universe_member", ["ticker"])
    op.create_index("ix_universe_member_run_eligible", "universe_member", ["run_id", "eligible"])


def downgrade() -> None:
    for name in ("universe_member", "universe_screen_run", "bulk_file", "universe_ticker"):
        op.drop_table(name)
