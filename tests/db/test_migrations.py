"""Migration fidelity: upgrade builds the schema, downgrade reverses it."""

from __future__ import annotations

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from tests.support import alembic_config


def test_upgrade_then_downgrade_roundtrip(db_url: str) -> None:
    cfg = alembic_config(db_url)

    command.upgrade(cfg, "head")
    engine = create_engine(db_url)
    tables = set(inspect(engine).get_table_names())
    assert {"instrument", "ohlcv_daily", "candidate", "paper_trade", "user"} <= tables
    assert "alembic_version" in tables

    command.downgrade(cfg, "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    engine.dispose()


def test_head_has_single_revision(db_url: str) -> None:
    heads = ScriptDirectory.from_config(alembic_config(db_url)).get_heads()
    assert len(heads) == 1, f"expected a single migration head, got {heads}"
