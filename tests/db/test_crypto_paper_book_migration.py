"""crypto_paper_book migration: additive, single head, round-trips."""

from __future__ import annotations

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from tests.support import alembic_config

REVISION = "d1a8b4c2e6f9"  # pragma: allowlist secret
PARENT = "c9e6a3b1d4f7"  # pragma: allowlist secret


def test_revision_is_the_single_head(db_url: str) -> None:
    script = ScriptDirectory.from_config(alembic_config(db_url))
    assert script.get_heads() == [REVISION]
    assert script.get_revision(REVISION).down_revision == PARENT


def test_upgrade_creates_two_tables_and_downgrade_removes_only_them(db_url: str) -> None:
    cfg = alembic_config(db_url)
    command.upgrade(cfg, "head")
    before = set(inspect(create_engine(db_url)).get_table_names())
    command.downgrade(cfg, PARENT)
    after = set(inspect(create_engine(db_url)).get_table_names())
    assert before - after == {"crypto_paper_book", "crypto_paper_trade"}
