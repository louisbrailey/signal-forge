"""D6 §7 — ``may_open`` is fail-closed on every single input.

"Missing evidence of safety is not evidence of safety": each check below is
driven to ``None`` in turn — unreadable, unreachable, not computed this cycle —
and each one must BLOCK rather than pass.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from signalforge.db.models import ExecutionLimits
from signalforge.execution.limits import (
    ArmedFacts,
    LimitSet,
    binding_cap,
    limit_set_from_row,
    load_active_limits,
    may_open,
)
from tests.execution.conftest import ADAPTER, NOW, clean_open_context

TRI_STATE_FIELDS = [
    ("kill_switch_engaged", "K1"),
    ("execution_kill_engaged", "K2"),
    ("dead_man_alive", "D1"),
    ("market_open_broker", "C1"),
    ("market_open_calendar", "C1"),
    ("minutes_since_open", "C2"),
    ("minutes_until_close", "C2"),
    ("is_early_close_session", "C3"),
    ("armed", "A1"),
    ("is_paper_proven_this_cycle", "A2"),
    ("intent_expires_at", "I1"),
    ("unknown_outstanding_for_strategy", "I2"),
    ("orders_today", "L1"),
    ("order_notional_usd", "L2"),
    ("account_equity_usd", "L2"),
    ("round_trips_last_5_sessions", "L3"),
    ("reconciliation_clean", "R1"),
    ("reconciliation_age_s", "R1"),
    ("options_risk_within_limits", "R2"),
    ("preconditions_ok", "P"),
]


def test_a_clean_cycle_is_allowed(limit_set: LimitSet) -> None:
    decision = may_open(clean_open_context(), limit_set)
    assert decision.allowed, decision.first_failure
    assert decision.first_failure is None


@pytest.mark.parametrize(("field", "check"), TRI_STATE_FIELDS)
def test_every_unevaluable_input_blocks_opening(
    field: str, check: str, limit_set: LimitSet
) -> None:
    decision = may_open(clean_open_context(**{field: None}), limit_set)
    assert not decision.allowed
    assert check in {c.name for c in decision.failures}


def test_no_limits_row_blocks(limit_set: LimitSet) -> None:
    """ "No limits row" is not "no limits"."""
    decision = may_open(clean_open_context(), None)
    assert not decision.allowed
    assert decision.first_failure is not None
    assert decision.first_failure.startswith("L0")


@pytest.mark.parametrize(
    ("override", "check"),
    [
        ({"kill_switch_engaged": True}, "K1"),
        ({"execution_kill_engaged": True}, "K2"),
        ({"dead_man_alive": False}, "D1"),
        ({"market_open_broker": False}, "C1"),  # broker says closed, calendar open
        ({"minutes_since_open": 5.0}, "C2"),
        ({"minutes_until_close": 5.0}, "C2"),
        ({"is_early_close_session": True}, "C3"),
        ({"is_paper_proven_this_cycle": False}, "A2"),
        ({"unknown_outstanding_for_strategy": True}, "I2"),
        ({"orders_today": 10}, "L1"),
        ({"order_notional_usd": 5_000.0}, "L2"),
        ({"round_trips_last_5_sessions": 3}, "L3"),
        ({"reconciliation_clean": False}, "R1"),
        ({"reconciliation_age_s": 600.0}, "R1"),
        ({"options_risk_within_limits": False}, "R2"),
        ({"preconditions_ok": False}, "P"),
    ],
)
def test_each_negative_condition_blocks_opening(
    override: dict[str, object], check: str, limit_set: LimitSet
) -> None:
    decision = may_open(clean_open_context(**override), limit_set)
    assert not decision.allowed
    assert check in {c.name for c in decision.failures}


def test_the_clock_and_the_calendar_must_agree(limit_set: LimitSet) -> None:
    """Two sources of truth disagreeing about whether the market is open is
    exactly when an order must not be sent."""
    decision = may_open(
        clean_open_context(market_open_broker=True, market_open_calendar=False), limit_set
    )
    assert not decision.allowed
    failure = next(c for c in decision.failures if c.name == "C1")
    assert "disagree" in failure.detail


def test_an_early_close_session_passes_only_when_explicitly_handled(limit_set: LimitSet) -> None:
    blocked = may_open(clean_open_context(is_early_close_session=True), limit_set)
    assert not blocked.allowed
    allowed = may_open(
        clean_open_context(is_early_close_session=True, early_close_explicitly_handled=True),
        limit_set,
    )
    assert allowed.allowed


@pytest.mark.parametrize(
    "armed_override",
    [
        {"disarmed": True},
        {"expires_at": NOW - timedelta(seconds=1)},
        {"adapter_name": "another_adapter"},
        {"structure_type": "short_vertical"},
        {"approval_level_permits_structure": False},
        {"approval_level_permits_structure": None},
    ],
)
def test_a1_rejects_every_broken_arming(
    armed_override: dict[str, object], limit_set: LimitSet
) -> None:
    base = {
        "adapter_name": ADAPTER,
        "expires_at": NOW + timedelta(days=1),
        "disarmed": False,
        "structure_type": "equity",
        "approval_level_permits_structure": True,
    }
    base.update(armed_override)
    decision = may_open(clean_open_context(armed=ArmedFacts(**base)), limit_set)  # type: ignore[arg-type]
    assert not decision.allowed
    assert "A1" in {c.name for c in decision.failures}


def test_an_expired_intent_is_refused_not_warned(limit_set: LimitSet) -> None:
    decision = may_open(clean_open_context(intent_expires_at=NOW - timedelta(seconds=1)), limit_set)
    assert not decision.allowed
    assert "I1" in {c.name for c in decision.failures}


def test_every_failure_is_reported_not_only_the_first(limit_set: LimitSet) -> None:
    decision = may_open(
        clean_open_context(dead_man_alive=False, reconciliation_clean=False, orders_today=99),
        limit_set,
    )
    assert {c.name for c in decision.failures} >= {"D1", "R1", "L1"}


# --- the binding limit -----------------------------------------------------


def test_the_binding_cap_is_the_tighter_of_the_two_recorded_intents() -> None:
    """Decision 4 says $1,000; map §3.2 says 0.5% of equity. On $25,000 those
    are $1,000 and $125 — and the stricter binds."""
    assert binding_cap(usd=1_000.0, pct=0.5, equity=25_000.0) == pytest.approx(125.0)
    assert binding_cap(usd=100.0, pct=0.5, equity=25_000.0) == pytest.approx(100.0)


def test_an_uncomputable_cap_is_none_so_the_caller_must_block() -> None:
    assert binding_cap(usd=None, pct=0.5, equity=25_000.0) is None
    # With no live equity the dollar cap still binds — it is never widened.
    assert binding_cap(usd=1_000.0, pct=0.5, equity=None) == pytest.approx(1_000.0)


def test_the_percent_form_binds_when_it_is_the_tighter_one(limit_set: LimitSet) -> None:
    decision = may_open(
        clean_open_context(order_notional_usd=350.0, account_equity_usd=25_000.0), limit_set
    )
    assert not decision.allowed
    failure = next(c for c in decision.failures if c.name == "L2")
    assert "binding cap" in failure.detail


# --- the limits row itself -------------------------------------------------


def test_the_active_row_is_loaded_and_parsed(session: Session, limits_row: ExecutionLimits) -> None:
    loaded = load_active_limits(session)
    assert loaded is not None
    assert loaded.id == limits_row.id
    assert loaded.max_orders_per_day == 10


def test_a_superseded_row_is_not_active(session: Session, limits_row: ExecutionLimits) -> None:
    limits_row.superseded_at = NOW
    session.flush()
    assert load_active_limits(session) is None


def test_no_row_at_all_returns_none(session: Session) -> None:
    assert load_active_limits(session) is None


def test_the_dead_man_cannot_be_set_into_contradiction_with_the_cadence(
    limits_row: ExecutionLimits,
) -> None:
    """§7b / §9: ``execution_stale_after_s >= 3 x cycle_interval_s``."""
    limits_row.execution_stale_after_s = 60
    limits_row.cycle_interval_s = 60
    with pytest.raises(ValueError, match="3 x cycle_interval_s"):
        limit_set_from_row(limits_row)


def test_an_unparseable_row_blocks_rather_than_loading(
    session: Session, limits_row: ExecutionLimits
) -> None:
    limits_row.execution_stale_after_s = 1
    session.flush()
    assert load_active_limits(session) is None


def test_a_row_without_a_preregistration_document_is_invalid(
    limits_row: ExecutionLimits,
) -> None:
    """§7b rule 1: the complete row is fixed in a pre-registration document
    BEFORE the first armed session."""
    limits_row.preregistration_doc_id = ""
    with pytest.raises(ValueError, match="preregistration_doc_id"):
        limit_set_from_row(limits_row)
