"""Revision ``e3b8c5d1f7a2``: the paper BOOK key on ``paper_account``.

Additive (one nullable unique column), and it ATTRIBUTES the legacy ``default``
account to a strategy version instead of moving money: the account becomes the
book of the one version all of its positions belong to, or stays unkeyed when
that is not unambiguous. Runs only against fresh throwaway databases.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from tests.support import alembic_config

REVISION = "e3b8c5d1f7a2"  # pragma: allowlist secret
PARENT = "c1e5a9f37b24"  # pragma: allowlist secret


@pytest.fixture
def parent_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A database migrated to the PARENT revision (the pre-books schema)."""
    url = f"sqlite+pysqlite:///{tmp_path / 'books.sqlite'}"
    # The Alembic env resolves the URL from settings, exactly as ``db_url`` does.
    monkeypatch.setenv("DATABASE_URL", url)
    from signalforge.config.settings import get_settings
    from signalforge.db.session import reset_engine_cache

    get_settings.cache_clear()
    reset_engine_cache()
    command.upgrade(alembic_config(url), PARENT)
    return url


def _seed(url: str, position_versions: list[int | None]) -> None:
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO paper_account (id, name, initial_cash, cash, collateral_reserved, "
                "created_at) VALUES (1, 'default', 30000, 21447.12, 0, '2026-09-10 00:00:00'), "
                "(2, 'options', 10000, 10000, 0, '2026-09-12 00:00:00')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO instrument (id, symbol, name, instrument_type, sector, industry, "
                "exchange, is_active, created_at, updated_at) VALUES (1, 'MSFT', 'm', 'stock', "
                "'', '', '', 1, '2026-09-10 00:00:00', '2026-09-10 00:00:00')"
            )
        )
        for sid in (2, 3):
            conn.execute(
                text(
                    "INSERT INTO strategy (id, name, horizon, permits_long, permits_short, status, "
                    "created_at) VALUES (:i, :n, 'SHORT_SWING', 1, 0, 'PAPER_APPROVED', "
                    "'2026-09-10 00:00:00')"
                ),
                {"i": sid, "n": f"s{sid}"},
            )
            conn.execute(
                text(
                    "INSERT INTO strategy_version (id, strategy_id, version, git_sha, spec_json, "
                    "status, created_at) VALUES (:i, :i, '0.1.0', 'x', '{}', 'PAPER_APPROVED', "
                    "'2026-09-10 00:00:00')"
                ),
                {"i": sid},
            )
        for n, ver in enumerate(position_versions, start=1):
            conn.execute(
                text(
                    "INSERT INTO paper_position (id, account_id, instrument_id, "
                    "strategy_version_id, horizon, side, qty, avg_price, opened_at, realized_pnl, "
                    "created_at) VALUES (:i, 1, 1, :v, 'MEDIUM_SWING', 'LONG', 5, 516.45, "
                    "'2026-09-25 21:31:00', 0, '2026-09-25 21:31:00')"
                ),
                {"i": n, "v": ver},
            )
    engine.dispose()


def _accounts(url: str) -> dict[str, tuple[int | None, float, float]]:
    engine = create_engine(url)
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT name, strategy_version_id, initial_cash, cash FROM paper_account")
        ).all()
    engine.dispose()
    return {r[0]: (r[1], float(r[2]), float(r[3])) for r in rows}


def test_revision_follows_the_parent_and_the_chain_has_one_head(db_url: str) -> None:
    script = ScriptDirectory.from_config(alembic_config(db_url))
    rev = script.get_revision(REVISION)
    assert rev is not None and rev.down_revision == PARENT
    assert len(script.get_heads()) == 1


def test_column_is_nullable_and_unique(db_url: str) -> None:
    engine = create_engine(db_url)
    insp = inspect(engine)
    col = {c["name"]: c for c in insp.get_columns("paper_account")}["strategy_version_id"]
    assert col["nullable"] is True
    unique = {tuple(ix["column_names"]) for ix in insp.get_indexes("paper_account") if ix["unique"]}
    assert ("strategy_version_id",) in unique
    engine.dispose()


def test_legacy_account_becomes_the_book_of_its_single_version(parent_db: str) -> None:
    """The live shape: every position in ``default`` belongs to one version (3)."""
    _seed(parent_db, [3, 3, 3, 3, 3, 3])
    command.upgrade(alembic_config(parent_db), REVISION)
    accounts = _accounts(parent_db)
    # attributed, and not one cent moved
    assert accounts["default"] == (3, 30000.0, 21447.12)
    # other accounts are never keyed, and no account is created by the migration
    assert accounts["options"] == (None, 10000.0, 10000.0)
    assert set(accounts) == {"default", "options"}
    # the parent table was altered in place: no cascade touched its children
    engine = create_engine(parent_db)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM paper_position")).scalar() == 6
    engine.dispose()


@pytest.mark.parametrize("versions", [[], [2, 3], [3, None], [None]])
def test_ambiguous_or_empty_legacy_account_stays_unkeyed(
    parent_db: str, versions: list[int | None]
) -> None:
    _seed(parent_db, versions)
    command.upgrade(alembic_config(parent_db), REVISION)
    assert _accounts(parent_db)["default"][0] is None


def test_downgrade_removes_only_the_book_key(parent_db: str) -> None:
    """Regression guard: a batch (copy-and-swap) downgrade of this parent table
    cascade-deletes every paper position. The downgrade must not lose a row."""
    _seed(parent_db, [3])
    cfg = alembic_config(parent_db)
    command.upgrade(cfg, REVISION)
    command.downgrade(cfg, PARENT)
    engine = create_engine(parent_db)
    cols = {c["name"] for c in inspect(engine).get_columns("paper_account")}
    assert "strategy_version_id" not in cols
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM paper_position")).scalar() == 1
        assert conn.execute(
            text("SELECT cash FROM paper_account WHERE name = 'default'")
        ).scalar() == pytest.approx(21447.12)
    engine.dispose()
