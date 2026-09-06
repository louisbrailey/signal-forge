"""Migration fidelity: upgrade builds the schema, downgrade reverses it."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from sqlalchemy import create_engine, inspect

from tests.db.conftest import _alembic_config


def test_upgrade_then_downgrade_roundtrip(db_url: str, tmp_path: Path) -> None:
    cfg = _alembic_config(db_url)

    command.upgrade(cfg, "head")
    engine = create_engine(db_url)
    tables = set(inspect(engine).get_table_names())
    assert {"instrument", "ohlcv_daily", "candidate", "paper_trade", "user"} <= tables
    assert "alembic_version" in tables

    command.downgrade(cfg, "base")
    tables_after = set(inspect(engine).get_table_names())
    assert tables_after == {"alembic_version"}
    engine.dispose()


def test_head_has_single_revision(db_url: str) -> None:
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_config(db_url))
    heads = script.get_heads()
    assert len(heads) == 1, f"expected a single migration head, got {heads}"
