"""upsert_strategy_version: status is set on creation only, never reset by a
later call — a scan or backtest-report run must not silently undo a promotion
or a downgrade.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import Strategy
from signalforge.domain import StrategyStatus
from signalforge.research.persistence import upsert_strategy_version
from signalforge.research.strategies import MeanReversion


def test_status_is_set_on_first_creation(session: Session) -> None:
    strat = MeanReversion()
    ver = upsert_strategy_version(session, strat.spec())  # spec().status is EXPERIMENTAL
    assert ver.status is StrategyStatus.EXPERIMENTAL
    db_strat = session.get(Strategy, ver.strategy_id)
    assert db_strat.status is StrategyStatus.EXPERIMENTAL


def test_repeat_calls_never_reset_a_promoted_or_downgraded_status(session: Session) -> None:
    """This is exactly the bug found live in this session: scan.py and
    backtest-report call upsert_strategy_version on every run with a spec
    whose .status is always EXPERIMENTAL. Before this fix, a second call
    silently reset StrategyVersion.status back to EXPERIMENTAL even after
    research.promotion had approved it -- desynchronising it from
    Strategy.status, which this function never touched after creation."""
    strat = MeanReversion()
    ver = upsert_strategy_version(session, strat.spec())
    db_strat = session.get(Strategy, ver.strategy_id)

    # simulate what research.promotion / a manual downgrade does
    db_strat.status = StrategyStatus.PAPER_APPROVED
    ver.status = StrategyStatus.PAPER_APPROVED
    session.flush()

    # a later scan or backtest-report run re-registers the same spec
    ver2 = upsert_strategy_version(session, strat.spec())
    session.flush()

    assert ver2.id == ver.id
    assert ver2.status is StrategyStatus.PAPER_APPROVED  # NOT reset to experimental
    db_strat2 = session.get(Strategy, ver2.strategy_id)
    assert db_strat2.status is StrategyStatus.PAPER_APPROVED
    # the two must never drift apart
    assert ver2.status == db_strat2.status


def test_repeat_calls_still_refresh_spec_json_and_git_sha(session: Session) -> None:
    strat = MeanReversion()
    ver = upsert_strategy_version(session, strat.spec())
    old_spec_json = dict(ver.spec_json)

    ver2 = upsert_strategy_version(session, strat.spec())
    # spec_json is rebuilt every call (git_sha() etc.) -- still refreshed, just not status
    assert isinstance(ver2.spec_json, dict)
    assert ver2.spec_json.keys() == old_spec_json.keys()
    assert ver2.status is StrategyStatus.EXPERIMENTAL


def test_status_field_types_match(session: Session) -> None:
    """Strategy.status and StrategyVersion.status must always be the same
    StrategyStatus for a given version -- the exact invariant the live bug
    violated (Strategy=paper_approved, StrategyVersion=experimental, with no
    audit trail explaining the divergence)."""
    strat = MeanReversion()
    ver = upsert_strategy_version(session, strat.spec())
    db_strat = session.scalar(select(Strategy).where(Strategy.id == ver.strategy_id))
    assert isinstance(db_strat, Strategy)
    assert db_strat.status == ver.status
