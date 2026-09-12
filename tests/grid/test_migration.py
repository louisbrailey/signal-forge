"""The grid migration is additive and builds the schema the models declare."""

from __future__ import annotations

from alembic import command
from sqlalchemy import create_engine, inspect

from tests.support import alembic_config


def test_grid_tables_exist_on_a_fresh_db(db_url: str) -> None:
    """``db_url`` is already migrated to head by the fixture."""
    engine = create_engine(db_url)
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    assert {"grid_position", "grid_trade"} <= tables

    pos_cols = {c["name"] for c in insp.get_columns("grid_position")}
    assert {
        "id",
        "account_id",
        "symbol",
        "qty",
        "cost_basis",
        "anchor_price",
        "opened_at",
        "updated_at",
    } <= pos_cols

    trade_cols = {c["name"] for c in insp.get_columns("grid_trade")}
    assert {
        "id",
        "account_id",
        "symbol",
        "side",
        "qty",
        "price",
        "usd",
        "anchor_before",
        "anchor_after",
        "session_date",
        "evidence_json",
        "created_at",
    } <= trade_cols

    # Idempotency backstop for the daily job.
    uniques = {tuple(u["column_names"]) for u in insp.get_unique_constraints("grid_trade")}
    assert ("account_id", "symbol", "session_date") in uniques
    engine.dispose()


def test_grid_migration_matches_the_declared_models(db_url: str) -> None:
    from signalforge.db.models import Base

    engine = create_engine(db_url)
    insp = inspect(engine)
    for table in ("grid_position", "grid_trade"):
        declared = {c.name for c in Base.metadata.tables[table].columns}
        assert declared == {c["name"] for c in insp.get_columns(table)}
    engine.dispose()


#: The grid migration's own revision. Named rather than reached with ``-1``:
#: this test is about what the GRID migration adds, and ``-1`` means "one step
#: back from head", which silently becomes a different migration the moment
#: anything lands after it (it did, when the execution skeleton landed).
#: (An Alembic revision id. The secret-scan baseline auto-excludes the
#: `revision:`/`down_revision:` assignment form only, so referring to one by
#: name anywhere else needs the pragma inline — the baseline is never rewritten
#: to accommodate new code.)
GRID_REVISION = "f1c4a8b2d6e7"  # pragma: allowlist secret


def test_downgrade_removes_only_the_grid_tables(db_url: str) -> None:
    cfg = alembic_config(db_url)
    engine = create_engine(db_url)
    head_tables = set(inspect(engine).get_table_names())
    assert {"grid_position", "grid_trade"} <= head_tables

    # Rewind to the grid migration itself, so the delta measured below is the
    # grid migration's and nothing else's.
    command.downgrade(cfg, GRID_REVISION)
    before = set(inspect(engine).get_table_names())
    assert {"grid_position", "grid_trade"} <= before

    command.downgrade(cfg, "-1")
    after = set(inspect(engine).get_table_names())
    assert {"grid_position", "grid_trade"}.isdisjoint(after)
    # Nothing else was touched — the migration is purely additive.
    assert before - after == {"grid_position", "grid_trade"}

    command.upgrade(cfg, "head")
    assert set(inspect(engine).get_table_names()) == head_tables
    engine.dispose()
