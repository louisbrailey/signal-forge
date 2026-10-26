"""D6 §9 — the dead man is the INVERSE of the kill switch, and it fails CLOSED.

The property that matters most is the asymmetry, and it is asserted twice over:
a lapse blocks opening (``may_open``'s D1) and a lapse blocks **nothing** on the
close lane (``may_close`` has no D1 to fail, and ``build_close_intent`` never
consults one). Drill V2.

Both the shared kill switch and the execution-specific K2 reader now block
opening on corrupt state. Their independent guards remain in place; protective
closing still does not depend on the shared kill-switch read.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import WorkerHeartbeat
from signalforge.execution import deadman
from signalforge.execution.limits import CloseGateContext, may_close, may_open
from tests.execution.conftest import NOW, clean_open_context


def test_no_heartbeat_row_at_all_is_a_lapse(session: Session) -> None:
    """Fail-CLOSED from the very first cycle: "the cycle has never run" is not
    evidence that it is healthy."""
    state = deadman.assess(session, now=NOW, stale_after_s=90)

    assert state.alive is False
    assert state.lapsed is True
    assert state.age_s is None
    assert "has never run" in state.detail


def test_feeding_makes_it_alive_and_the_row_is_upserted(session: Session) -> None:
    deadman.feed(session, now=NOW, detail="cycle full")
    deadman.feed(session, now=NOW + timedelta(seconds=30), detail="cycle full")

    rows = list(session.scalars(select(WorkerHeartbeat)))
    assert len(rows) == 1
    assert rows[0].worker == deadman.DEAD_MAN_WORKER
    state = deadman.assess(session, now=NOW + timedelta(seconds=40), stale_after_s=90)
    assert state.alive is True
    assert state.age_s == pytest.approx(10.0)


def test_the_execution_dead_man_is_not_the_scheduler_heartbeat(session: Session) -> None:
    """A live research worker is not evidence that the execution cycle ran."""
    session.add(WorkerHeartbeat(worker="scheduler", started_at=NOW, last_beat_at=NOW))
    session.flush()

    assert deadman.assess(session, now=NOW, stale_after_s=90).alive is False


def test_a_stale_heartbeat_lapses(session: Session) -> None:
    deadman.feed(session, now=NOW)
    state = deadman.assess(session, now=NOW + timedelta(seconds=91), stale_after_s=90)

    assert state.alive is False
    assert "91s old > 90s" in state.detail
    # The words the operator needs during an outage, in the record itself.
    assert "closing is NOT blocked" in state.detail
    assert "nothing is auto-liquidated" in state.detail


def test_a_heartbeat_from_the_future_is_ambiguous_and_therefore_lapsed(
    session: Session,
) -> None:
    """A clock that jumped backwards would otherwise make a stale beat look fresh
    forever."""
    deadman.feed(session, now=NOW + timedelta(seconds=300))
    state = deadman.assess(session, now=NOW, stale_after_s=90)

    assert state.alive is False
    assert "FUTURE" in state.detail


def test_a_zero_window_is_not_a_window(session: Session) -> None:
    deadman.feed(session, now=NOW)
    assert deadman.assess(session, now=NOW, stale_after_s=0).alive is False


def test_the_stale_window_must_tolerate_two_missed_cycles() -> None:
    assert deadman.min_stale_after_s(30) == 90
    from signalforge.execution.limits import LimitSet

    with pytest.raises(ValueError, match="3 x cycle_interval_s"):
        LimitSet(
            id=1,
            max_orders_per_day=10,
            max_order_notional_usd=1000.0,
            max_account_exposure_pct=40.0,
            per_structure_max_loss_usd=250.0,
            per_structure_max_loss_pct=0.5,
            aggregate_open_max_loss_usd=1000.0,
            aggregate_open_max_loss_pct=2.0,
            collateral_cap_usd=5000.0,
            collateral_cap_pct=30.0,
            max_net_delta_notional_usd=10_000.0,
            max_net_vega_per_volpt_usd=50.0,
            cycle_interval_s=30,
            max_intent_age_minutes=15,
            max_reconciliation_age_s=120,
            execution_stale_after_s=60,  # < 3 x 30
            drain_timeout_s=30,
            no_submit_after_open_minutes=15,
            no_submit_before_close_minutes=15,
            buying_power_tolerance_usd=1.0,
            buying_power_tolerance_pct=0.1,
            round_trips_per_5_sessions_max=3,
            pdt_equity_threshold_usd=25_000.0,
            preregistration_doc_id="doc",
        )


# ---------------------------------------------------------------------------
# The asymmetry — drill V2
# ---------------------------------------------------------------------------


def test_a_lapse_blocks_opening(limit_set: object) -> None:
    decision = may_open(clean_open_context(dead_man_alive=False), limit_set)  # type: ignore[arg-type]

    assert not decision.allowed
    assert any(c.name == "D1" and not c.passed for c in decision.checks)
    assert "dead man has lapsed" in decision.first_failure


def test_an_unevaluated_dead_man_also_blocks_opening(limit_set: object) -> None:
    decision = may_open(clean_open_context(dead_man_alive=None), limit_set)  # type: ignore[arg-type]

    assert not decision.allowed
    assert "could not be evaluated" in {c.name: c.detail for c in decision.checks}["D1"]


def test_a_lapse_blocks_nothing_on_the_close_lane() -> None:
    """``may_close`` has five checks and a dead man is not among them: a close is
    the removal of an exposure that already exists."""
    decision = may_close(
        CloseGateContext(
            position_exists_and_reconciled=True,
            originating_event_exists=True,
            non_increasing_in_every_leg=True,
            intent_kind_is_protective_close=True,
            adapter_reachable=True,
            reconciliation_diverged=False,
        )
    )

    assert decision.allowed
    assert {c.name for c in decision.checks} == {"C-P1", "C-P2", "C-P3", "C-P4", "C-P5"}


def test_the_shared_kill_switch_also_fails_closed(tmp_path: object) -> None:
    """Corruption blocks shared callers as well as the independent K2 guard."""
    from pathlib import Path

    from signalforge.killswitch import KillSwitch

    state_path = Path(str(tmp_path)) / "ks.json"
    state_path.write_text("{not json", encoding="utf-8")
    switch = KillSwitch(state_path=state_path, log_path=Path(str(tmp_path)) / "ks.log")

    assert switch.state().active is True
