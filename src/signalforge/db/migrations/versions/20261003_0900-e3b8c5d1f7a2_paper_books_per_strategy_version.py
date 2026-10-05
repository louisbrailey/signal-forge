"""paper books per approved strategy version

Revision ID: e3b8c5d1f7a2
Revises: d2f7a1c4e9b6
Create Date: 2026-10-03 09:00:00

Operator decision 2026-10-03 (paper simulation only): every PAPER_APPROVED
strategy version gets its own equity paper book. The book key is one nullable,
unique column on ``paper_account``.

* ADDITIVE. One nullable column and one unique index; no table is rebuilt, no
  existing row's money moves, ``paper_trade`` (immutable, S9) is not touched.
* ATTRIBUTION, not a transfer. Existing positions and trades stay in the
  account they were recorded in. The legacy equity account ``default`` becomes
  the book of the ONE strategy version that every one of its positions is
  attributed to (``paper_position.strategy_version_id``). On the live database
  that is the medium-swing version (all six accepted trades). If the account
  has no positions, or positions of more than one version (or an unattributed
  one), the key stays NULL and the account remains the unattributed/manual
  equity book — nothing is guessed.
* Books for other versions are created lazily by ``signalforge.paper.books``;
  this migration inserts no account.

NOTE on ordering: PR #7's revision ``d2f7a1c4e9b6`` (dividend_yield_daily) merged
first and also revises ``c1e5a9f37b24``; this revision therefore follows
``d2f7a1c4e9b6`` so the chain keeps exactly one head. The two are independent
(different tables), so the order carries no data dependency.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e3b8c5d1f7a2"
down_revision: str | None = "d2f7a1c4e9b6"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_ACCOUNT = "default"
_INDEX = "ix_paper_account_strategy_version_id"


def upgrade() -> None:
    # A plain ALTER TABLE ADD COLUMN — deliberately NOT a batch operation. On
    # SQLite a batch can fall back to copy-and-swap (DROP + recreate) of
    # ``paper_account``, and with foreign keys ON that DROP cascades into
    # ``paper_position`` / ``paper_order`` / ``paper_trade``.
    op.add_column("paper_account", sa.Column("strategy_version_id", sa.Integer(), nullable=True))
    op.create_index(_INDEX, "paper_account", ["strategy_version_id"], unique=True)

    bind = op.get_bind()
    acct_id = bind.execute(
        sa.text("SELECT id FROM paper_account WHERE name = :n"), {"n": LEGACY_ACCOUNT}
    ).scalar()
    if acct_id is None:
        return
    versions = [
        row[0]
        for row in bind.execute(
            sa.text(
                "SELECT DISTINCT strategy_version_id FROM paper_position WHERE account_id = :a"
            ),
            {"a": acct_id},
        )
    ]
    if len(versions) == 1 and versions[0] is not None:
        bind.execute(
            sa.text("UPDATE paper_account SET strategy_version_id = :v WHERE id = :a"),
            {"v": versions[0], "a": acct_id},
        )


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="paper_account")
    # Native DROP COLUMN (SQLite >= 3.35), never a batch rebuild: rebuilding
    # ``paper_account`` would DROP the parent table and cascade-delete every
    # paper position, order and trade that references it.
    op.execute("ALTER TABLE paper_account DROP COLUMN strategy_version_id")
