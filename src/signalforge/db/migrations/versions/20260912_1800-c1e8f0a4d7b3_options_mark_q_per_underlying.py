"""options mark records the q it used, per underlying (W5b, decision 11)

PURELY ADDITIVE, and deliberately the smallest possible change: two nullable /
defaulted columns on ``options_mark`` and nothing else. No table is created, no
column is dropped, renamed, retyped or made non-nullable, and no index,
constraint or trigger is touched.

Why a column at all: ``options_mark`` has **no JSON column** to carry these, and
they cannot be read off the position row instead. ``options_position.q_source``
records what was used at ENTRY; a mark is a different session, with its own
trailing-twelve-month dividend window, and after W5b with its own PER-UNDERLYING
resolution. Decision 11 says ``q`` is sourced and recorded per underlying; a
recorded ``q`` that cannot be tied to the session and structure it valued is not
a record of anything.

``op.add_column`` rather than ``op.batch_alter_table``, and that is load-bearing
on SQLite: ``options_mark`` is APPEND-ONLY, enforced by the
``options_mark_no_update`` / ``options_mark_no_delete`` BEFORE triggers created
in b9d41e07c6aa. Batch mode rebuilds a table by copy-and-swap, which would have
to write into the copy and drop the original, and would leave the rebuilt table
without its triggers. A plain ``ALTER TABLE ... ADD COLUMN`` with a constant
default is a metadata-only operation on SQLite: it rewrites no row, moves no
data, and leaves both triggers attached to the same table object.

Every existing ``options_mark`` row (there are none on the live database, which
has no options paper account) migrates to ``q_source = ''`` and
``dividend_yield = NULL``. NULL is the honest value for "this row predates the
per-underlying resolver" — never 0.0, which is exactly the assumption decision 11
exists to refuse.

Revision ID: c1e8f0a4d7b3
Revises: b9d41e07c6aa
Create Date: 2026-09-12 18:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c1e8f0a4d7b3"
down_revision: str | None = "b9d41e07c6aa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "options_mark",
        sa.Column("q_source", sa.String(length=48), nullable=False, server_default=""),
    )
    op.add_column(
        "options_mark",
        sa.Column("dividend_yield", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("options_mark", "dividend_yield")
    op.drop_column("options_mark", "q_source")
