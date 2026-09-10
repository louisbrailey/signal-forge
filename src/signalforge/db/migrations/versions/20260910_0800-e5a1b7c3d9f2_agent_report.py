"""agent report

Revision ID: e5a1b7c3d9f2
Revises: c8d2f4a6e1b3
Create Date: 2026-09-10 08:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import signalforge.db.types

revision: str = "e5a1b7c3d9f2"
down_revision: str | None = "c8d2f4a6e1b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # New table only — no batch_alter_table on any existing table.
    op.create_table(
        "agent_report",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agent", sa.String(length=40), nullable=False),
        sa.Column("role", sa.String(length=120), nullable=False),
        sa.Column("as_of", signalforge.db.types.UTCDateTime(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("narrative", sa.Text(), nullable=True),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("citations_json", sa.JSON(), nullable=False),
        sa.Column("missing_data_json", sa.JSON(), nullable=False),
        sa.Column("duration_s", sa.Float(), nullable=False),
        sa.Column("error", sa.String(length=300), nullable=False),
        sa.Column("created_at", signalforge.db.types.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_report_agent", "agent_report", ["agent"])
    op.create_index("ix_agent_report_created_at", "agent_report", ["created_at"])
    op.create_index("ix_agent_report_agent_created", "agent_report", ["agent", "created_at"])


def downgrade() -> None:
    op.drop_table("agent_report")
