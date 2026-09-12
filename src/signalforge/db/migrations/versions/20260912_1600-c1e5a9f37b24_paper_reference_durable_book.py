"""paper_reference durable book (D6 §3.1): one new table, nothing else touched

PURELY ADDITIVE. One brand-new table, ``paper_reference_order``. No existing
table, column, index, constraint or trigger is touched in any way, and there is
no data migration: on the live probation database this migration adds an empty
table and changes nothing that any running code reads.

**Why the table exists.** ``brokers/paper_reference.py`` is the local,
deterministic, network-free simulator every Phase V drill runs against, and it
held its order book in a Python dict. That made the book die with the object —
so a fresh adapter instance (the next cycle, or the next process) started FLAT
and reconciled CLEAN because it held nothing rather than because anything had
been explained. "Clean because we forgot" is precisely the failure §10 exists to
catch, and a simulator that cannot reproduce it cannot drill it.

**What it is NOT.** It is not a second copy of ``execution_event``. That table is
the OMS's append-only record of what the OMS did; this one is the BROKER's book,
written by the simulator. Reconciliation compares the two, and a reconciliation
whose two sides are the same rows is not a reconciliation — so they are separate
tables written by separate code, on purpose.

**No immutability triggers here, also on purpose.** ``execution_event``,
``paper_trade``, ``options_trade`` and the collateral ledger are append-only
because they are evidence. A broker's order book is not evidence; it is state,
and an order's state legitimately moves (SUBMITTING -> FILLED). Rows are keyed by
``client_order_id`` and updated in place. The S9-style ``RAISE(ABORT, ...)``
triggers would be wrong here and are deliberately absent.

Nothing in this migration enables execution, arms anything, or creates a row.
``research.execution.enabled`` ships False and no ``armed_strategy`` row exists.

Before running this against the live probation database: stop the worker and
copy the file. The copy is the rollback. ``downgrade()`` drops the table, which
is lossless in the only direction that matters — the table is empty on every
deployment that has never armed anything.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "c1e5a9f37b24"
down_revision: str | None = "c1e8f0a4d7b3"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "paper_reference_order",
        sa.Column("id", sa.Integer(), nullable=False),
        # One adapter answers for ONE account (§13); two accounts must never
        # share a book, so the account id is on every row and is indexed.
        sa.Column("account_id", sa.String(length=120), nullable=False),
        sa.Column("client_order_id", sa.String(length=64), nullable=False),
        sa.Column("broker_order_id", sa.String(length=64), nullable=False, server_default=""),
        # The economic fingerprint A1 / §5.4 dedupes on: "a fresh id is not a
        # fresh order" has to survive a restart, which is why it is stored.
        sa.Column("fingerprint", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("legs_json", sa.JSON(), nullable=False),
        sa.Column("requested_units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("filled_units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("leg_fill_prices_json", sa.JSON(), nullable=False),
        sa.Column("net_fill_price", sa.Float(), nullable=False, server_default="0"),
        sa.Column("intent_kind", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("structure_type", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("raw_status_verbatim", sa.Text(), nullable=False, server_default=""),
        sa.Column("error_verbatim", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_paper_trade_id", sa.Integer(), nullable=True),
        sa.Column("strategy_version_id", sa.Integer(), nullable=True),
        sa.Column("armed_strategy_id", sa.Integer(), nullable=True),
        sa.Column("execution_limits_id", sa.Integer(), nullable=True),
        sa.Column("config_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("spec_json_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("modelled_fill_price", sa.Float(), nullable=False, server_default="0"),
        sa.Column("modelled_spread_bps", sa.Float(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
        # No foreign keys, deliberately: this is the BROKER's table. A broker
        # does not hold referential integrity against our research rows, and a
        # cascade from a research delete into a simulated book would be a lie
        # about what a broker would have done.
    )
    op.create_index(
        "ix_paper_reference_order_client_order_id",
        "paper_reference_order",
        ["client_order_id"],
        unique=True,
    )
    op.create_index(
        "ix_paper_reference_order_account", "paper_reference_order", ["account_id"], unique=False
    )
    op.create_index(
        "ix_paper_reference_order_fingerprint",
        "paper_reference_order",
        ["account_id", "fingerprint"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_paper_reference_order_fingerprint", table_name="paper_reference_order")
    op.drop_index("ix_paper_reference_order_account", table_name="paper_reference_order")
    op.drop_index("ix_paper_reference_order_client_order_id", table_name="paper_reference_order")
    op.drop_table("paper_reference_order")
