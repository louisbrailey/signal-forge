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


def test_options_io1_migration_is_additive_on_a_fresh_database(db_url: str) -> None:
    """The options I-O1 revision adds two NEW tables, ONE nullable column, and
    widens a free-standing ``VARCHAR``. It must add no constraint to
    ``data_snapshot`` — that table is the parent of the sealed-look ledger
    (ON DELETE CASCADE), and on SQLite a constraint change there is satisfied by
    a batch copy-and-swap rebuild of the parent."""
    cfg = alembic_config(db_url)
    command.upgrade(cfg, "head")
    engine = create_engine(db_url)
    insp = inspect(engine)

    assert {"dividend_event", "split_event"} <= set(insp.get_table_names())

    div = {c["name"]: c for c in insp.get_columns("dividend_event")}
    assert {"symbol", "ex_dividend_date", "cash_amount", "source", "ingested_at"} <= set(div)
    assert div["declaration_date"]["nullable"] is True  # optional vendor fields stay optional
    assert {tuple(uc["column_names"]) for uc in insp.get_unique_constraints("dividend_event")} == {
        ("symbol", "ex_dividend_date", "source")
    }
    assert {tuple(uc["column_names"]) for uc in insp.get_unique_constraints("split_event")} == {
        ("symbol", "execution_date", "source")
    }

    snap = {c["name"]: c for c in insp.get_columns("data_snapshot")}
    assert snap["options_scope_json"]["nullable"] is True
    snap_unique = {
        tuple(uc["column_names"]) for uc in insp.get_unique_constraints("data_snapshot")
    } | {tuple(ix["column_names"]) for ix in insp.get_indexes("data_snapshot") if ix["unique"]}
    assert ("key",) in snap_unique
    assert not any("options_scope_json" in cs for cs in snap_unique)

    # D12: the options backfill writes a 20- and a 22-character kind
    kind = {c["name"]: c for c in insp.get_columns("ingestion_run")}["kind"]
    assert kind["type"].length == 32  # type: ignore[attr-defined]

    command.downgrade(cfg, "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    engine.dispose()
