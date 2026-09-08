"""data snapshot reusable flag

Revision ID: 2ea68f289c37
Revises: eee776733a63
Create Date: 2026-09-08 03:01:07.261425
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import signalforge.db.types

revision: str = "2ea68f289c37"
down_revision: str | None = "eee776733a63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Deliberately NOT batch_alter_table: SQLite's batch mode recreates the
    # whole table (drop old -> create new -> copy -> rename), and this
    # project's env.py runs migrations with PRAGMA foreign_keys=ON — dropping
    # data_snapshot mid-recreate would CASCADE-delete every strategy_sealed_test
    # row whose dataset_snapshot_id points at it (ondelete="CASCADE" — see
    # research.py's StrategySealedTest), silently wiping locked, immutable
    # sealed-test evidence. Confirmed empirically against a scratch copy of
    # the real dev DB: the batch_alter_table version dropped all 20 sealed
    # test rows. SQLite (3.35+; this project's is 3.53) supports ADD COLUMN
    # with a constant NOT NULL DEFAULT natively, with no table recreation —
    # use that directly instead.
    op.add_column(
        "data_snapshot",
        sa.Column(
            "reusable_by_new_evaluations", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
    )

    # Every existing row defaults to reusable=True above (correct for any
    # deliberately-named snapshot). The one exception: a migration-backfilled
    # audit row whose own description already promises "never reused by new
    # evaluations" (see eee776733a63) must actually be excluded from the
    # unkeyed symbol-match fallback that promise depends on.
    conn = op.get_bind()
    data_snapshot = sa.table(
        "data_snapshot",
        sa.column("key", sa.String),
        sa.column("reusable_by_new_evaluations", sa.Boolean),
    )
    conn.execute(
        data_snapshot.update()
        .where(data_snapshot.c.key == "universe_25_baseline_legacy")
        .values(reusable_by_new_evaluations=False)
    )


def downgrade() -> None:
    # Also deliberately non-batch, for the same CASCADE-wipe reason as
    # upgrade() — SQLite 3.35+ supports DROP COLUMN natively too.
    op.drop_column("data_snapshot", "reusable_by_new_evaluations")
