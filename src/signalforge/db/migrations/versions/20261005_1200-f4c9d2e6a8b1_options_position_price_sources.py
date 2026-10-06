"""options_position price-source provenance

Revision ID: f4c9d2e6a8b1
Revises: e3b8c5d1f7a2
Create Date: 2026-10-05 12:00:00

PR #14's review found that the options paper path read ``option_aggregate_daily``
by ticker + date with NO source filter (highest id won) and the underlying's
bars with no source filter either. Every read now names its source, and the
source comes from provenance recorded ON THE POSITION at entry:

* ``option_source`` — the ``option_aggregate_daily.source`` label of the legs'
  prints, resolved from the scan's DataSnapshot (never guessed, never the
  underlying-bar label);
* ``underlying_source`` — the ``ohlcv_daily.source`` label of the scan that
  produced the candidate (``scan_run.source``).

ADDITIVE: two NOT NULL text columns with a server default of ``''`` on
``options_position``. An empty label means "unrecorded", and the marks REFUSE such
a position (``paper.options_mark_refused`` audit row) rather than pick a row. The
live database has zero ``options_position`` rows, so nothing is backfilled and
nothing is guessed about an existing structure.

A plain ALTER TABLE ADD COLUMN, deliberately NOT a batch operation: on SQLite a
batch can fall back to copy-and-swap of ``options_position``, and with foreign
keys ON that DROP cascades into ``options_position_leg`` / ``options_mark`` /
``options_collateral_entry``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4c9d2e6a8b1"
down_revision: str | None = "e3b8c5d1f7a2"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "options_position"
_COLUMNS = ("option_source", "underlying_source")


def upgrade() -> None:
    for name in _COLUMNS:
        op.add_column(
            _TABLE,
            sa.Column(name, sa.String(length=40), nullable=False, server_default=""),
        )


def downgrade() -> None:
    # Native DROP COLUMN (SQLite >= 3.35), never a batch rebuild: rebuilding
    # ``options_position`` would DROP the parent table and cascade-delete every
    # leg, mark and collateral entry that references it.
    for name in reversed(_COLUMNS):
        op.execute(f"ALTER TABLE {_TABLE} DROP COLUMN {name}")
