"""crypto_hourly_paper_book + crypto_hourly_paper_trade migration: additive, reversible, head."""

from __future__ import annotations

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from tests.support import alembic_config

REVISION = "f3a7c1d9e5b2"  # pragma: allowlist secret
PARENT = "e2b9c5d3f7a1"  # pragma: allowlist secret
TABLES = {"crypto_hourly_paper_book", "crypto_hourly_paper_trade"}


def test_revision_is_the_single_head_and_chains_to_the_intraday_bars(db_url: str) -> None:
    script = ScriptDirectory.from_config(alembic_config(db_url))
    assert script.get_heads() == [REVISION]
    assert script.get_revision(REVISION).down_revision == PARENT


def test_upgrade_creates_two_tables_and_downgrade_removes_only_them(db_url: str) -> None:
    cfg = alembic_config(db_url)
    command.upgrade(cfg, "head")
    before = set(inspect(create_engine(db_url)).get_table_names())
    assert before >= TABLES
    cols = {
        c["name"] for c in inspect(create_engine(db_url)).get_columns("crypto_hourly_paper_trade")
    }
    assert {"entry_at", "exit_at", "marked_at", "status", "pnl_r", "divergence"} <= cols
    command.downgrade(cfg, PARENT)
    after = set(inspect(create_engine(db_url)).get_table_names())
    assert before - after == TABLES
