"""crypto_bar_intraday migration: additive, single head, round-trips."""

from __future__ import annotations

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from tests.support import alembic_config

REVISION = "e2b9c5d3f7a1"  # pragma: allowlist secret
PARENT = "d1a8b4c2e6f9"  # pragma: allowlist secret


def test_revision_is_the_single_head(db_url: str) -> None:
    script = ScriptDirectory.from_config(alembic_config(db_url))
    assert script.get_heads() == [REVISION]
    assert script.get_revision(REVISION).down_revision == PARENT


def test_upgrade_creates_the_table_and_downgrade_removes_only_it(db_url: str) -> None:
    cfg = alembic_config(db_url)
    command.upgrade(cfg, "head")
    before = set(inspect(create_engine(db_url)).get_table_names())
    command.downgrade(cfg, PARENT)
    after = set(inspect(create_engine(db_url)).get_table_names())
    assert before - after == {"crypto_bar_intraday"}
