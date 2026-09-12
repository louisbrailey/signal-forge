"""options I-O1: dividend/split reference tables, options scope identity, wider run kind

Three changes, in ascending order of how much they touch:

1. ``dividend_event`` / ``split_event`` — brand-new tables, plain
   ``create_table``. Nothing existing is read or written by them.
2. ``data_snapshot.options_scope_json`` — **ADD COLUMN ONLY**, nullable JSON, no
   constraint, no index. ``data_snapshot`` is the parent of
   ``strategy_sealed_test`` (ON DELETE CASCADE — the sealed-look ledger itself),
   and migrations run with ``render_as_batch`` on SQLite plus
   ``PRAGMA foreign_keys=ON``, so ANY change to its UNIQUE constraint would
   force a batch copy-and-swap rebuild of that parent table. A plain add-column
   does not trigger batch mode. ``UniqueConstraint("key")`` is deliberately NOT
   touched here or later: scope identity is enforced procedurally in
   ``research.promotion.get_or_create_dataset_snapshot``. If this column is ever
   to enter a constraint, it must FIRST be made NOT NULL with a ``'{}'``
   sentinel backfilled in its own migration — otherwise SQL NULL-inequality
   defeats the constraint silently (D1 §9.2a, blocker D15).
3. ``ingestion_run.kind`` 16 -> 32 chars. The options backfill has always
   written a 20-character value into a ``String(16)`` column; SQLite does not
   enforce VARCHAR length so it was silent there, but Postgres truncates or
   errors (D12 / OQ-8). ``ingestion_run`` is the parent of no foreign key and
   the child of none, so its batch rebuild has no cascade blast radius.

Before running this against the live probation database: stop the worker and
copy the file. The copy is the rollback.

Revision ID: a7f3c2b8e451
Revises: f1c4a8b2d6e7
Create Date: 2026-09-12 09:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import signalforge.db.types

revision: str = "a7f3c2b8e451"
down_revision: str | None = "f1c4a8b2d6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dividend_event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("ex_dividend_date", sa.Date(), nullable=False),
        sa.Column("cash_amount", sa.Float(), nullable=False),
        sa.Column("declaration_date", sa.Date(), nullable=True),
        sa.Column("record_date", sa.Date(), nullable=True),
        sa.Column("pay_date", sa.Date(), nullable=True),
        sa.Column("frequency", sa.Integer(), nullable=True),
        sa.Column("dividend_type", sa.String(length=8), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("ingested_at", signalforge.db.types.UTCDateTime(), nullable=False),
        sa.Column("created_at", signalforge.db.types.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_dividend_event"),
        sa.UniqueConstraint(
            "symbol", "ex_dividend_date", "source", name="uq_dividend_event_sym_ex_src"
        ),
    )
    op.create_index("ix_dividend_event_symbol", "dividend_event", ["symbol"])
    op.create_index("ix_dividend_event_ex_dividend_date", "dividend_event", ["ex_dividend_date"])
    op.create_index("ix_dividend_event_source", "dividend_event", ["source"])
    op.create_index("ix_dividend_event_symbol_ex", "dividend_event", ["symbol", "ex_dividend_date"])

    op.create_table(
        "split_event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("execution_date", sa.Date(), nullable=False),
        sa.Column("split_from", sa.Float(), nullable=False),
        sa.Column("split_to", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("ingested_at", signalforge.db.types.UTCDateTime(), nullable=False),
        sa.Column("created_at", signalforge.db.types.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_split_event"),
        sa.UniqueConstraint(
            "symbol", "execution_date", "source", name="uq_split_event_sym_exec_src"
        ),
    )
    op.create_index("ix_split_event_symbol", "split_event", ["symbol"])
    op.create_index("ix_split_event_execution_date", "split_event", ["execution_date"])
    op.create_index("ix_split_event_source", "split_event", ["source"])
    op.create_index("ix_split_event_symbol_exec", "split_event", ["symbol", "execution_date"])

    # ADD COLUMN only — no constraint, no index, no batch rebuild of the parent
    # of the sealed-look ledger.
    op.add_column("data_snapshot", sa.Column("options_scope_json", sa.JSON(), nullable=True))

    with op.batch_alter_table("ingestion_run") as batch:
        batch.alter_column(
            "kind",
            existing_type=sa.String(length=16),
            type_=sa.String(length=32),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("ingestion_run") as batch:
        batch.alter_column(
            "kind",
            existing_type=sa.String(length=32),
            type_=sa.String(length=16),
            existing_nullable=False,
        )
    with op.batch_alter_table("data_snapshot") as batch:
        batch.drop_column("options_scope_json")
    op.drop_table("split_event")
    op.drop_table("dividend_event")
