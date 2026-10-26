"""Revision ``f4c9d2e6a8b1``: price-source provenance on ``options_position``.

Two NOT NULL text columns with a server default of ``''``; nothing else. Runs
only against fresh throwaway databases.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from signalforge.db.models import Instrument, OptionsPosition, PaperAccount
from signalforge.db.types import utcnow
from tests.support import alembic_config

REVISION = "f4c9d2e6a8b1"  # pragma: allowlist secret
PARENT = "e3b8c5d1f7a2"  # pragma: allowlist secret


def test_the_revision_follows_the_books_revision_and_the_chain_has_one_head(db_url: str) -> None:
    script = ScriptDirectory.from_config(alembic_config(db_url))
    heads = script.get_heads()
    assert len(heads) == 1
    # later additive revisions sit on top; this one must stay in the single chain
    assert REVISION in {r.revision for r in script.walk_revisions("base", heads[0])}
    assert script.get_revision(REVISION).down_revision == PARENT


def test_upgrade_adds_two_non_null_source_columns_with_an_empty_default(db_url: str) -> None:
    cfg = alembic_config(db_url)
    command.upgrade(cfg, "head")
    engine = create_engine(db_url)
    cols = {c["name"]: c for c in inspect(engine).get_columns("options_position")}
    for name in ("option_source", "underlying_source"):
        assert name in cols
        assert cols[name]["nullable"] is False
        assert cols[name]["default"] in ("''", "")
    # a row written WITHOUT the two labels reads as UNRECORDED (''), which the
    # marks refuse — the server default is the empty string, never a vendor name
    with Session(engine) as s:
        acct = PaperAccount(name="options", initial_cash=Decimal("25000"), cash=Decimal("25000"))
        inst = Instrument(symbol="SPY", name="SPY", instrument_type="etf", sector="")
        s.add_all([acct, inst])
        s.flush()
        s.add(
            OptionsPosition(
                account_id=acct.id,
                underlying_instrument_id=inst.id,
                underlying_symbol="SPY",
                structure_type="vertical_credit",
                contracts=1,
                entry_net_premium=Decimal("50"),
                r_dollars=Decimal("150"),
                strike_width=2.0,
                expiration_date=date(2026, 3, 20),
                opened_at=utcnow(),
            )
        )
        s.commit()
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT option_source, underlying_source FROM options_position")
        ).one()
    assert tuple(row) == ("", "")
    command.downgrade(cfg, PARENT)
    assert not {"option_source", "underlying_source"} & {
        c["name"] for c in inspect(engine).get_columns("options_position")
    }
    engine.dispose()
