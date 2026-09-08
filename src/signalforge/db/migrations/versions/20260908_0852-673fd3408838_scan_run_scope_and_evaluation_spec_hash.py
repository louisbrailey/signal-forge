"""scan run scope and evaluation spec hash

Revision ID: 673fd3408838
Revises: 2ea68f289c37
Create Date: 2026-09-08 08:52:20.327829
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import signalforge.db.types

revision: str = "673fd3408838"
down_revision: str | None = "2ea68f289c37"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Deliberately NOT batch_alter_table anywhere on scan_run, including for
    # the follow-up nullable/default tweaks autogenerate would normally add:
    # candidate.scan_run_id references scan_run with ondelete="CASCADE", and
    # this project's env.py runs migrations with PRAGMA foreign_keys=ON --
    # SQLite's batch mode recreates the whole table (drop old -> create new ->
    # copy -> rename) for EVERY operation inside a batch_alter_table block,
    # even a no-op-looking alter_column, and dropping scan_run mid-recreate
    # would CASCADE-delete every candidate row. This is the exact class of bug
    # found and fixed in migration 2ea68f289c37 for data_snapshot/
    # strategy_sealed_test. SQLite (3.35+; this project's is 3.53) supports
    # ADD COLUMN natively (including an inline REFERENCES clause), with no
    # table recreation -- these columns stay DB-level nullable (the ORM model
    # always supplies a value on insert; existing rows are backfilled below)
    # rather than risk a second recreate solely to add a NOT NULL constraint.
    op.add_column("scan_run", sa.Column("universe_json", sa.JSON(), nullable=True))
    op.add_column("scan_run", sa.Column("source", sa.String(length=40), nullable=True))
    op.execute(
        sa.text(
            "ALTER TABLE scan_run ADD COLUMN dataset_snapshot_id INTEGER "
            "REFERENCES data_snapshot(id) ON DELETE SET NULL"
        )
    )
    op.execute(
        sa.text("UPDATE scan_run SET universe_json = '[]', source = '' WHERE universe_json IS NULL")
    )

    # strategy_promotion_evaluation has no incoming CASCADE foreign key (only
    # StrategySealedTest.dataset_snapshot_id -> data_snapshot and similar point
    # AWAY from it), so batch-recreating it here is safe.
    with op.batch_alter_table("strategy_promotion_evaluation", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("spec_json_hash", sa.String(length=64), nullable=False, server_default="")
        )
    with op.batch_alter_table("strategy_promotion_evaluation", schema=None) as batch_op:
        batch_op.alter_column("spec_json_hash", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("strategy_promotion_evaluation", schema=None) as batch_op:
        batch_op.drop_column("spec_json_hash")

    # Non-batch here for the same CASCADE-safety reason as upgrade().
    op.drop_column("scan_run", "dataset_snapshot_id")
    op.drop_column("scan_run", "source")
    op.drop_column("scan_run", "universe_json")
