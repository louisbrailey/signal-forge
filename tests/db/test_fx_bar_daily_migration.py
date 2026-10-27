"""fx_bar_daily migration: additive, single head, round-trips."""

from __future__ import annotations

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from tests.support import alembic_config

REVISION = "a7c3e1f9b2d4"  # pragma: allowlist secret
PARENT = "f4c9d2e6a8b1"  # pragma: allowlist secret


def test_revision_is_the_single_head_on_the_price_sources_revision(db_url: str) -> None:
    script = ScriptDirectory.from_config(alembic_config(db_url))
    heads = script.get_heads()
    assert len(heads) == 1
    assert REVISION in {r.revision for r in script.walk_revisions("base", heads[0])}
    assert script.get_revision(REVISION).down_revision == PARENT


def test_upgrade_creates_the_table_and_downgrade_removes_only_it(db_url: str) -> None:
    cfg = alembic_config(db_url)
    command.upgrade(cfg, "head")
    engine = create_engine(db_url)
    before = set(inspect(engine).get_table_names())
    assert "fx_bar_daily" in before
    cols = {c["name"] for c in inspect(engine).get_columns("fx_bar_daily")}
    assert {"pair", "session_date", "open", "high", "low", "close", "source"} <= cols
    command.downgrade(cfg, PARENT)
    after = set(inspect(create_engine(db_url)).get_table_names())
    assert "fx_bar_daily" in before - after
    assert before - after <= {
        "fx_bar_daily",
        "crypto_bar_daily",
        "currency_sealed_test",
        "crypto_paper_book",
        "crypto_paper_trade",
        "crypto_bar_intraday",
    }
