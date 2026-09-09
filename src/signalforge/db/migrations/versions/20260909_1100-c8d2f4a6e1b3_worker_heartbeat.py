"""worker heartbeat

Revision ID: c8d2f4a6e1b3
Revises: 6d1e552c9a20
Create Date: 2026-09-09 11:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import signalforge.db.types

revision: str = "c8d2f4a6e1b3"
down_revision: str | None = "6d1e552c9a20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # New table only — no batch_alter_table on any existing table.
    op.create_table(
        "worker_heartbeat",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("worker", sa.String(length=40), nullable=False),
        sa.Column("host", sa.String(length=120), nullable=False),
        sa.Column("pid", sa.Integer(), nullable=False),
        sa.Column("started_at", signalforge.db.types.UTCDateTime(), nullable=False),
        sa.Column("last_beat_at", signalforge.db.types.UTCDateTime(), nullable=False),
        sa.Column("next_runs_json", sa.JSON(), nullable=False),
        sa.Column("detail", sa.String(length=300), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("worker"),
    )
    op.create_index("ix_worker_heartbeat_last_beat_at", "worker_heartbeat", ["last_beat_at"])


def downgrade() -> None:
    op.drop_table("worker_heartbeat")
