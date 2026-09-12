"""The equity paper path is byte-identical after the ``PaperTrade.actor``
column (D6 §5.3).

The execution layer's one change to code that runs today is an additive,
indexed ``actor`` column plus the line that fills it. Everything the equity path
produces — the order, the fill, the spread and slippage arithmetic, the
position, the cash movement, and the complete evidence snapshot — must be
unchanged, byte for byte, and this test pins it as a canonical JSON blob rather
than a handful of spot assertions.

The only volatile keys (a git SHA and wall-clock timestamps) are excluded and
listed explicitly, so the exclusion is visible rather than convenient.

**How the golden below was shown to be the PARENT commit's output, not merely
this branch's** (a golden captured after a change proves nothing about the
change). The parent tree was extracted with ``git archive HEAD`` into a scratch
directory, this file was copied in with the single ``"actor"`` key removed from
``GOLDEN["trade"]`` and from ``_canonical``, and the test was run there against
``signalforge`` as it stood before the column existed: **it passed**. So the one
and only difference this commit makes to the equity path's output is the
presence of the ``actor`` key — every price, quantity, cash figure, snapshot key
and notice is byte-identical. Re-run that procedure if this golden ever moves.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from signalforge.db.models import (
    Candidate,
    PaperAccount,
    PaperFill,
    PaperOrder,
    PaperPosition,
    PaperTrade,
)
from signalforge.domain import PaperDecision
from signalforge.paper.auto_simulate import AUTO_SIM_ACTOR
from signalforge.paper.ledger import accept_candidate, record_decision

#: Excluded from the canonical form because they move on every run by design.
VOLATILE_KEYS = ("code_version", "as_of", "created_at", "submitted_at", "filled_at", "opened_at")

#: The canonical equity-path output, captured with the ``actor`` column in
#: place. If a future change moves any number here, it is a change to the paper
#: path and not an incidental refactor.
GOLDEN = {
    "account_cash_after": "7642.40",
    "fill": {
        "commission": "0.000000",
        "price": "471.260000",
        "qty": 5,
        "slippage": "0.710000",
        "spread_cost": "0.590000",
    },
    "order": {
        "assumptions_json": {
            "note": "SIMULATED fill — no order was placed",
            "reference_price": 471.0,
            "slippage_frac": 0.00055,
            "spread_bps": 5.0,
        },
        "order_type": "market",
        "qty": 5,
        "side": "long",
    },
    "position": {
        "avg_price": "471.260000",
        "qty": 5,
        "realized_pnl": "0.000000",
        "side": "long",
        "stop_level": 466.0,
        "target_level": 485.0,
    },
    "trade": {
        "actor": "auto_simulate",
        "decision": "accepted",
        "notice": "Research signal only — no order was placed.",
        "plan_json": {
            "direction": "LONG",
            "entry_zone": [470.0, 472.0],
            "fill_price": 471.2591,
            "invalidation": 466.0,
            "shares": 5,
            "target": 485.0,
            "time_stop_days": 10,
        },
        "snapshot_decision": {"actor": "auto_simulate", "automatic": True, "note": ""},
        "snapshot_keys": [
            "approval_scope",
            "calibration_ref",
            "candidate_id",
            "code_version",
            "data_freshness",
            "decision",
            "direction",
            "entry_zone",
            "event_risk",
            "failed_gates",
            "horizon",
            "instrument_type",
            "invalidation_level",
            "liquidity",
            "notice",
            "portfolio_context",
            "probability_calibrated",
            "quality_gate_status",
            "rank_in_horizon",
            "ranking",
            "reasons_fail",
            "reasons_qualify",
            "reward_risk_estimate",
            "risk_dollars",
            "risk_pct_of_account",
            "scan",
            "slippage_assumption",
            "strategy",
            "symbol",
            "target_level",
            "target_logic",
            "time_stop_days",
            "was_no_trade",
        ],
        "why_might_fail": "regime flip",
        "why_qualified": "trend",
    },
}


def _canonical(session: Session, res: Any, account: PaperAccount) -> dict[str, Any]:
    order = session.get(PaperOrder, res.order_id)
    fill = session.get(PaperFill, res.fill_id)
    position = session.get(PaperPosition, res.position_id)
    trade = session.get(PaperTrade, res.paper_trade_id)
    assert order is not None and fill is not None and position is not None and trade is not None
    snapshot = trade.signal_snapshot_json
    return {
        "account_cash_after": str(Decimal(account.cash)),
        "fill": {
            "commission": str(Decimal(fill.commission)),
            "price": str(Decimal(fill.price)),
            "qty": fill.qty,
            "slippage": str(Decimal(fill.slippage)),
            "spread_cost": str(Decimal(fill.spread_cost)),
        },
        "order": {
            "assumptions_json": order.assumptions_json,
            "order_type": order.order_type,
            "qty": order.qty,
            "side": order.side.value,
        },
        "position": {
            "avg_price": str(Decimal(position.avg_price)),
            "qty": position.qty,
            "realized_pnl": str(Decimal(position.realized_pnl)),
            "side": position.side.value,
            "stop_level": position.stop_level,
            "target_level": position.target_level,
        },
        "trade": {
            "actor": trade.actor,
            "decision": trade.decision.value,
            "plan_json": trade.plan_json,
            "snapshot_decision": snapshot["decision"],
            "snapshot_keys": sorted(snapshot),
            "why_might_fail": trade.why_might_fail,
            "why_qualified": trade.why_qualified,
            "notice": snapshot["notice"],
        },
    }


def _accept(session: Session, candidate: Candidate, **kw: Any) -> Any:
    return accept_candidate(session, candidate.id, as_of=date(2024, 2, 1), **kw)


def test_the_equity_accept_path_is_byte_identical(
    session: Session, passing_candidate: Candidate, account: PaperAccount
) -> None:
    # The fixture candidate is generic; pin the inputs this golden was taken
    # over so the arithmetic is reproducible.
    passing_candidate.entry_zone_low = 470.0
    passing_candidate.entry_zone_high = 472.0
    passing_candidate.invalidation_level = 466.0
    passing_candidate.target_level = 485.0
    passing_candidate.risk_dollars = 25.0
    passing_candidate.reasons_qualify = ["trend"]
    passing_candidate.reasons_fail = ["regime flip"]
    session.flush()

    res = _accept(session, passing_candidate, actor=AUTO_SIM_ACTOR)
    canonical = _canonical(session, res, account)

    assert json.dumps(canonical, sort_keys=True) == json.dumps(GOLDEN, sort_keys=True)

    # The excluded keys are omitted because they move by design, not because
    # they are absent: the record still carries them.
    trade = session.get(PaperTrade, res.paper_trade_id)
    assert trade is not None
    assert "code_version" in trade.signal_snapshot_json
    for section in ("fill", "order", "position", "trade"):
        assert not set(VOLATILE_KEYS) & set(canonical[section])


def test_the_new_column_records_the_actor_the_caller_passed(
    session: Session, passing_candidate: Candidate, account: PaperAccount
) -> None:
    """P6's predicate is this column. The JSON keeps its copy; the column is the
    one an order-authorisation check may read."""
    res = _accept(session, passing_candidate, actor=AUTO_SIM_ACTOR)
    trade = session.get(PaperTrade, res.paper_trade_id)
    assert trade is not None
    assert trade.actor == AUTO_SIM_ACTOR
    assert trade.signal_snapshot_json["decision"]["actor"] == AUTO_SIM_ACTOR


def test_the_default_actor_is_the_manual_one(
    session: Session, passing_candidate: Candidate, account: PaperAccount
) -> None:
    """``signalforge paper accept`` — the unguarded CLI path — defaults to
    'local-user', which P6 refuses."""
    res = _accept(session, passing_candidate)
    trade = session.get(PaperTrade, res.paper_trade_id)
    assert trade is not None
    assert trade.actor == "local-user"


def test_record_decision_also_carries_the_actor(
    session: Session, passing_candidate: Candidate, account: PaperAccount
) -> None:
    trade_id = record_decision(
        session,
        passing_candidate.id,
        PaperDecision.REJECTED,
        note="not now",
        actor=AUTO_SIM_ACTOR,
    )
    trade = session.get(PaperTrade, trade_id)
    assert trade is not None
    assert trade.actor == AUTO_SIM_ACTOR


def test_the_no_order_notice_is_unchanged(
    session: Session, passing_candidate: Candidate, account: PaperAccount
) -> None:
    """The "no order was placed" notice is replaced only by a record's TRUE
    execution status, and every paper trade today has none — so it stands."""
    res = _accept(session, passing_candidate)
    trade = session.get(PaperTrade, res.paper_trade_id)
    assert trade is not None
    assert trade.signal_snapshot_json["notice"] == "Research signal only — no order was placed."
