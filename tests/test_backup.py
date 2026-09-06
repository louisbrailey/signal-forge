"""Backup + restore for the local SQLite database.

Restore is a stop-the-app operation. These tests exercise the file mechanics
(consistent snapshot, pre-restore safety copy) rather than a live hot-swap.
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from pathlib import Path

from signalforge.backup import _sqlite_path, create_backup, restore_backup
from signalforge.db.models import PaperAccount
from signalforge.db.session import get_sessionmaker, reset_engine_cache


def test_snapshot_is_a_consistent_readable_database(db_url: str, tmp_path: Path) -> None:
    with get_sessionmaker()() as s:
        s.add(PaperAccount(name="default", initial_cash=Decimal("10000"), cash=Decimal("4200")))
        s.commit()

    res = create_backup(out_dir=tmp_path / "bak")
    assert res.path.exists() and res.bytes > 0 and res.encrypted is False

    con = sqlite3.connect(res.path)
    try:
        (cash,) = con.execute("SELECT cash FROM paper_account WHERE name='default'").fetchone()
    finally:
        con.close()
    assert float(cash) == 4200.0


def test_restore_keeps_a_pre_restore_copy(db_url: str, tmp_path: Path) -> None:
    with get_sessionmaker()() as s:
        s.add(PaperAccount(name="default", initial_cash=Decimal("10000"), cash=Decimal("10000")))
        s.commit()
    res = create_backup(out_dir=tmp_path / "bak")

    live = _sqlite_path()
    reset_engine_cache()  # release the connection pool — restore is stop-the-app
    dest = restore_backup(res.path)

    assert dest == live
    assert Path(f"{live}.pre-restore").exists()
    assert not Path(f"{live}-wal").exists()  # stale journal cleared
