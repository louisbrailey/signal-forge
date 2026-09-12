"""The I-O6 options-paper migration: additive, single-headed, trigger-guarded.

Everything here runs against a FRESH database built by ``alembic upgrade head``,
never against the live one.
"""

from __future__ import annotations

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from tests.support import alembic_config

NEW_TABLES = {
    "candidate_option_structure",
    "options_position",
    "options_position_leg",
    "options_trade",
    "options_collateral_entry",
    "options_mark",
    "options_reconcile_report",
}

#: Invariant S9, the ``paper_trade`` precedent: a pair of SQLite BEFORE triggers,
#: not an ORM exception class.
APPEND_ONLY_TABLES = {
    "options_trade",
    "options_collateral_entry",
    "options_mark",
    "options_reconcile_report",
}


def test_the_migration_chain_still_has_a_single_head(db_url: str) -> None:
    heads = ScriptDirectory.from_config(alembic_config(db_url)).get_heads()
    assert len(heads) == 1, f"expected a single migration head, got {heads}"


def test_the_options_paper_revision_is_chained_from_the_options_data_revision(
    db_url: str,
) -> None:
    """The I-O6 revision's own place in the chain, which no later work may move.

    The head assertion moved to :func:`test_the_w5b_revision_is_chained_from_the_
    options_paper_revision` when W5b added a revision on top; what is pinned here
    is the LINK — I-O6 still follows I-O1 and nothing was re-parented.
    """
    script = ScriptDirectory.from_config(alembic_config(db_url))
    rev = script.get_revision("b9d41e07c6aa")  # pragma: allowlist secret
    assert rev.down_revision == "a7f3c2b8e451"  # pragma: allowlist secret


def test_the_w5b_revision_is_chained_from_the_options_paper_revision(db_url: str) -> None:
    """W5b adds ``options_mark.q_source`` / ``.dividend_yield`` — the ``q`` each
    mark was taken under, per underlying (decision 11). One revision, chained
    from the single head that existed, and still a single head afterwards."""
    script = ScriptDirectory.from_config(alembic_config(db_url))
    rev = script.get_revision("c1e8f0a4d7b3")  # pragma: allowlist secret
    assert rev.down_revision == "b9d41e07c6aa"  # pragma: allowlist secret
    assert list(script.get_heads()) == ["c1e8f0a4d7b3"]  # pragma: allowlist secret


def test_the_mark_records_the_q_it_used_and_nothing_else_changed(db_url: str) -> None:
    """Additive on a table that is APPEND-ONLY and trigger-guarded.

    ``op.add_column`` rather than a batch rebuild, so ``options_mark``'s two
    immutability triggers survive: a copy-and-swap would leave the rebuilt table
    without them, which is the S9 mechanism itself.
    """
    cfg = alembic_config(db_url)
    command.upgrade(cfg, "head")
    engine = create_engine(db_url)
    insp = inspect(engine)

    cols = {c["name"]: c for c in insp.get_columns("options_mark")}
    assert cols["q_source"]["nullable"] is False  # defaulted to '' on every old row
    assert cols["dividend_yield"]["nullable"] is True  # NULL means "not a number", never 0.0

    with engine.begin() as conn:
        triggers = set(
            conn.execute(text("SELECT name FROM sqlite_master WHERE type = 'trigger'")).scalars()
        )
    assert {"options_mark_no_update", "options_mark_no_delete"} <= triggers
    engine.dispose()


def test_the_migration_is_additive_on_a_fresh_database(db_url: str) -> None:
    cfg = alembic_config(db_url)
    command.upgrade(cfg, "head")
    engine = create_engine(db_url)
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    assert tables >= NEW_TABLES

    # The two ALTERs, both additive. ``paper_account.collateral_reserved`` has a
    # server default, so every existing account — including the live equity one —
    # migrates to 0 and ``spendable_cash == cash`` there.
    account = {c["name"]: c for c in insp.get_columns("paper_account")}
    assert "collateral_reserved" in account
    assert account["collateral_reserved"]["nullable"] is False
    assert str(account["collateral_reserved"]["default"]).strip("'\"") == "0"
    # and none of the pre-existing columns was dropped, renamed or retyped
    assert {"id", "name", "initial_cash", "cash", "created_at"} <= set(account)

    candidate = {c["name"]: c for c in insp.get_columns("candidate")}
    assert candidate["structure_kind"]["nullable"] is True
    assert candidate["structure_kind"]["type"].length == 16  # type: ignore[attr-defined]

    # ``instrument.instrument_type`` is NOT retyped: this design introduces no
    # new instrument_type value at all (D3 §13).
    instrument = {c["name"]: c for c in insp.get_columns("instrument")}
    assert instrument["instrument_type"]["type"].length == 16  # type: ignore[attr-defined]

    engine.dispose()


def test_the_batch_rebuilds_did_not_break_any_foreign_key(db_url: str) -> None:
    """``batch_alter_table`` on SQLite copies, drops and renames the table. Both
    targets (``paper_account``, ``candidate``) are FK parents, so this asserts no
    child was left pointing at a renamed temp table."""
    cfg = alembic_config(db_url)
    command.upgrade(cfg, "head")
    engine = create_engine(db_url)
    insp = inspect(engine)
    names = set(insp.get_table_names())
    for table in names:
        for fk in insp.get_foreign_keys(table):
            assert fk["referred_table"] in names, (table, fk)
    assert {"candidate_id"} <= {
        c for fk in insp.get_foreign_keys("paper_trade") for c in fk["constrained_columns"]
    }
    with engine.connect() as conn:
        assert list(conn.execute(text("PRAGMA foreign_key_check"))) == []
        assert list(conn.execute(text("PRAGMA integrity_check"))) == [("ok",)]
    engine.dispose()


def test_the_s9_style_immutability_triggers_exist_and_abort(db_url: str) -> None:
    cfg = alembic_config(db_url)
    command.upgrade(cfg, "head")
    engine = create_engine(db_url)
    with engine.connect() as conn:
        triggers = {
            r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='trigger'"))
        }
        for table in APPEND_ONLY_TABLES:
            assert f"{table}_no_update" in triggers, table
            assert f"{table}_no_delete" in triggers, table
        # the pre-existing S9 triggers survived the batch rebuilds
        assert {"paper_trade_no_update", "paper_trade_no_delete"} <= triggers
        assert {"execution_event_no_update", "execution_event_no_delete"} <= triggers

        conn.execute(
            text(
                "INSERT INTO paper_account (name, initial_cash, cash, collateral_reserved, "
                "created_at) VALUES ('options', 25000, 25000, 0, '2026-02-18 00:00:00')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO options_reconcile_report (account_id, as_of, clean, findings_json, "
                "collateral_reserved_observed, collateral_reserved_expected, open_structures, "
                "created_at) VALUES (1, '2026-02-18', 1, '[]', 0, 0, 0, '2026-02-18 00:00:00')"
            )
        )
        conn.commit()
        with pytest.raises(Exception, match="append-only"):
            conn.execute(text("UPDATE options_reconcile_report SET clean = 0"))
        conn.rollback()
        with pytest.raises(Exception, match="append-only"):
            conn.execute(text("DELETE FROM options_reconcile_report"))
        conn.rollback()
    engine.dispose()


def test_the_migration_inserts_no_paper_account(db_url: str) -> None:
    """The options account is created deliberately by the operator with
    ``signalforge paper init --name options --cash 25000``, so its creation is an
    operator action with a timestamp rather than a schema side effect."""
    cfg = alembic_config(db_url)
    command.upgrade(cfg, "head")
    engine = create_engine(db_url)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM paper_account")).scalar() == 0
    engine.dispose()


def test_downgrade_drops_only_what_upgrade_created(db_url: str) -> None:
    cfg = alembic_config(db_url)
    command.upgrade(cfg, "head")
    engine = create_engine(db_url)
    command.downgrade(cfg, "a7f3c2b8e451")  # pragma: allowlist secret
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    assert not (NEW_TABLES & tables)
    assert "collateral_reserved" not in {c["name"] for c in insp.get_columns("paper_account")}
    assert "structure_kind" not in {c["name"] for c in insp.get_columns("candidate")}
    with engine.connect() as conn:
        triggers = {
            r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='trigger'"))
        }
        assert not any(t.startswith("options_") for t in triggers)
        assert {"paper_trade_no_update", "paper_trade_no_delete"} <= triggers

    command.downgrade(cfg, "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    engine.dispose()


def test_the_orm_metadata_and_the_migrated_schema_agree(db_url: str) -> None:
    """A model added without its migration (or vice versa) is caught here rather
    than at the first write against the live database."""
    import signalforge.db.models as models

    cfg = alembic_config(db_url)
    command.upgrade(cfg, "head")
    engine = create_engine(db_url)
    insp = inspect(engine)
    db_tables = set(insp.get_table_names()) - {"alembic_version"}
    orm_tables = set(models.Base.metadata.tables)
    assert orm_tables == db_tables
    for table in sorted(NEW_TABLES):
        assert {c["name"] for c in insp.get_columns(table)} == set(
            models.Base.metadata.tables[table].columns.keys()
        ), table
    engine.dispose()
