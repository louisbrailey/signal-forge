"""Equity accounting/evidence golden and actor authorization regressions.

Updated for the conservative ledger correction: one share under the 5% cap,
rounded execution-price cash accounting, and explicit acceptance risk evidence.
Automatic-actor coverage uses a genuinely approved, fresh, enabled fixture.
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
    "account_cash_after": "9528.740000",
    "fill": {
        "commission": "0.000000",
        "price": "471.260000",
        "qty": 1,
        "slippage": "0.140000",
        "spread_cost": "0.120000",
    },
    "order": {
        "assumptions_json": {
            "note": "SIMULATED fill — no order was placed",
            "reference_price": 471.0,
            "slippage_frac": 0.00055,
            "spread_bps": 5.0,
        },
        "order_type": "market",
        "qty": 1,
        "side": "long",
    },
    "position": {
        "avg_price": "471.260000",
        "qty": 1,
        "realized_pnl": "0.000000",
        "side": "long",
        "stop_level": 466.0,
        "target_level": 485.0,
    },
    "trade": {
        "actor": "local-user",
        "decision": "accepted",
        "notice": "Research signal only — no order was placed.",
        "plan_json": {
            "direction": "LONG",
            "entry_zone": [470.0, 472.0],
            "fill_price": 471.26,
            "invalidation": 466.0,
            "shares": 1,
            "target": 485.0,
            "time_stop_days": 10,
            "acceptance_context": {"mode": "historical_replay", "as_of": "2024-02-01"},
            "risk_decision": {
                "policy": "conservative-long-only-v1",
                "equity": "10000.000000",
                "cash": "10000.000000",
                "reserved_collateral": "0.000000",
                "gross_before": "0",
                "open_risk_before": "0",
                "symbol_before": "0",
                "sector_before": "0",
                "sector": "tech",
                "configured_limits": {
                    "per_trade_risk_pct": 0.5,
                    "max_daily_portfolio_risk_pct": 1.5,
                    "max_position_concentration_pct": 10.0,
                    "max_portfolio_exposure_pct": 60.0,
                    "max_correlated_exposure_pct": 25.0,
                    "min_reward_to_risk": 1.5,
                },
                "effective_limits": {
                    "per_trade_risk_pct": 0.5,
                    "max_daily_portfolio_risk_pct": 1.5,
                    "max_position_concentration_pct": 5.0,
                    "max_portfolio_exposure_pct": 60.0,
                    "max_correlated_exposure_pct": 20.0,
                },
                "candidate_risk_dollars": "25.0",
                "risk_per_share": "5.52",
                "exit_slippage_bps": 3.0,
                "accepted_risk_dollars": "5.52",
                "share_caps": {
                    "candidate_risk": 4,
                    "per_trade_risk": 9,
                    "open_risk": 27,
                    "cash": 21,
                    "symbol": 1,
                    "gross": 12,
                    "sector": 4,
                },
                "shares": 1,
                "reduced": True,
                "reductions": ["symbol"],
                "binding_caps": ["symbol"],
                "limit_overrides_narrowed": [
                    "max_position_concentration_pct",
                    "max_correlated_exposure_pct",
                ],
            },
        },
        "snapshot_decision": {"actor": "local-user", "automatic": False, "note": ""},
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

    res = _accept(session, passing_candidate)
    canonical = _canonical(session, res, account)

    assert json.dumps(canonical, sort_keys=True) == json.dumps(GOLDEN, sort_keys=True)

    # The excluded keys are omitted because they move by design, not because
    # they are absent: the record still carries them.
    trade = session.get(PaperTrade, res.paper_trade_id)
    assert trade is not None
    assert "code_version" in trade.signal_snapshot_json
    for section in ("fill", "order", "position", "trade"):
        assert not set(VOLATILE_KEYS) & set(canonical[section])


def test_the_new_column_records_the_actor_the_caller_passed(session: Session, monkeypatch) -> None:
    """P6's indexed actor and its immutable snapshot must agree on a valid auto fill."""
    from signalforge.research import approval_scope
    from signalforge.settings_store import set_setting
    from tests.paper.test_auto_simulate import SPEC_HASH, _seed

    monkeypatch.setattr(approval_scope, "current_spec_json_hash", lambda _s, _v: SPEC_HASH)
    _, (candidate,) = _seed(session)
    set_setting(session, "auto_simulate_qualified_signals", True)
    res = accept_candidate(session, candidate.id, actor=AUTO_SIM_ACTOR)
    trade = session.get(PaperTrade, res.paper_trade_id)
    assert trade is not None
    assert trade.actor == AUTO_SIM_ACTOR
    assert trade.signal_snapshot_json["decision"]["actor"] == AUTO_SIM_ACTOR
    assert trade.signal_snapshot_json["decision"]["automatic"] is True


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
