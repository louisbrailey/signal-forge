"""job run table

Revision ID: b4e7d2c9a1f0
Revises: 673fd3408838
Create Date: 2026-09-09 09:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import signalforge.db.types

revision: str = "b4e7d2c9a1f0"
down_revision: str | None = "673fd3408838"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A brand-new table only — no batch_alter_table on any existing table, so
    # none of the CASCADE-on-recreate hazards documented in 2ea68f289c37 /
    # 673fd3408838 apply here.
    op.create_table(
        "job_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("started_at", signalforge.db.types.UTCDateTime(), nullable=False),
        sa.Column("finished_at", signalforge.db.types.UTCDateTime(), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("detail", sa.String(length=300), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_run_name", "job_run", ["name"], unique=False)
    op.create_index("ix_job_run_started_at", "job_run", ["started_at"], unique=False)
    op.create_index("ix_job_run_name_started", "job_run", ["name", "started_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_job_run_name_started", table_name="job_run")
    op.drop_index("ix_job_run_started_at", table_name="job_run")
    op.drop_index("ix_job_run_name", table_name="job_run")
    op.drop_table("job_run")
