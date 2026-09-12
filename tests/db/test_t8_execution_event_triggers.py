"""T8 (D6 execution ADR §19, §15) — ``execution_event`` is append-only at the DATABASE level.

Written in I-E1, before the table exists. It skips with a reason until the I-E2 migration
creates ``execution_event`` and its two triggers, and it asserts *now* the thing the future
assertion is modelled on: that the ``paper_trade`` pair of triggers is the real S9 mechanism
and is present in the migrated schema.

The mechanism is the trigger, not an ORM exception class. FACT (ADR §15): the declared
``ImmutablePaperTradeError`` has no raise site anywhere in ``src/signalforge``; S9 is enforced
by ``paper_trade_no_update`` / ``paper_trade_no_delete``. ``execution_event`` must be enforced
the same way, by re-implementing the trigger DDL in the execution migration — never by
importing anything from ``signalforge.paper`` (S15b forbids ``paper -> execution`` and this
ADR does not create the reverse dependency either).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

EXPECTED_EXECUTION_TRIGGERS = ("execution_event_no_update", "execution_event_no_delete")
PAPER_TRADE_TRIGGERS = ("paper_trade_no_update", "paper_trade_no_delete")


def _tables(session: Session) -> set[str]:
    rows = session.execute(text("select name from sqlite_master where type='table'")).all()
    return {r[0] for r in rows}


def _triggers(session: Session, table: str) -> set[str]:
    rows = session.execute(
        text("select name from sqlite_master where type='trigger' and tbl_name=:t"),
        {"t": table},
    ).all()
    return {r[0] for r in rows}


def test_paper_trade_trigger_pattern_exists_to_be_copied(session: Session) -> None:
    """The shape T8 mirrors. If this ever goes away, T8's model is gone with it."""
    assert set(PAPER_TRADE_TRIGGERS) <= _triggers(session, "paper_trade")


def test_t8_execution_event_rejects_update_and_delete(session: Session) -> None:
    if "execution_event" not in _tables(session):
        pytest.skip(
            "requires I-E2: the execution_event table and its "
            f"{EXPECTED_EXECUTION_TRIGGERS} triggers do not exist yet (D6 ADR §15, §19 T8)"
        )
    found = _triggers(session, "execution_event")
    assert set(EXPECTED_EXECUTION_TRIGGERS) <= found, (
        "execution_event exists without its append-only triggers; an ORM exception class is "
        f"not the mechanism (D6 ADR §15). Found: {sorted(found)}"
    )
    session.execute(
        text(
            "insert into execution_event (ts, event_type, adapter_name) "
            "values (datetime('now'), 'INTENT_BUILT', 'paper_reference')"
        )
    )
    session.commit()
    row_id = session.execute(text("select id from execution_event limit 1")).scalar_one()

    with pytest.raises(Exception, match=r"immutable|append-only"):
        session.execute(
            text("update execution_event set event_type='X' where id=:i"), {"i": row_id}
        )
    session.rollback()
    with pytest.raises(Exception, match=r"immutable|append-only"):
        session.execute(text("delete from execution_event where id=:i"), {"i": row_id})
    session.rollback()

    still_there = session.execute(
        text("select event_type from execution_event where id=:i"), {"i": row_id}
    ).scalar_one()
    assert still_there == "INTENT_BUILT"
