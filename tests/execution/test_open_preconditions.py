"""D6 §5 — the seven OPEN preconditions, each one removed in turn.

The premise under test is §5.1's finding: an ACCEPTED ``PaperTrade`` is not by
itself evidence that anything was gated, because ``accept_candidate`` checks
none of P1-P7 and is reachable from the CLI with no guard.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from signalforge.db.models import (
    ArmedStrategy,
    Candidate,
    PaperAccount,
    PaperTrade,
    StrategyVersion,
)
from signalforge.domain import PaperDecision, QualityGate, StrategyStatus
from signalforge.execution.intents import (
    CostModelFeedback,
    IntentKind,
    IntentRefused,
    OrderSide,
    OrderState,
    StructureType,
    build_open_intent,
    default_scope_matcher,
)
from signalforge.execution.limits import LimitDecision, may_open
from tests.execution.conftest import ADAPTER, NOW, clean_open_context


def _passing_gate() -> LimitDecision:
    return LimitDecision(allowed=True, checks=())


def _build(session: Session, trade_id: int, **kw: object) -> object:
    defaults: dict[str, object] = {
        "paper_trade_id": trade_id,
        "adapter_name": ADAPTER,
        "side": OrderSide.BUY_TO_OPEN,
        "qty": 1,
        "limit_price": 471.0,
        "cost_model": CostModelFeedback(modelled_fill_price=471.0, modelled_spread_bps=5.0),
        "limit_decision": _passing_gate(),
        "now": NOW,
        "max_intent_age_minutes": 15,
        "session_end_utc": NOW + timedelta(hours=1),
        "scope_matcher": lambda *_a: True,
    }
    defaults.update(kw)
    return build_open_intent(session, **defaults)  # type: ignore[arg-type]


@pytest.mark.usefixtures("armed")
def test_all_seven_preconditions_met_builds_an_open_intent(
    session: Session, auto_paper_trade: PaperTrade
) -> None:
    intent = _build(session, auto_paper_trade.id)
    assert intent.intent_kind is IntentKind.OPEN  # type: ignore[union-attr]
    assert intent.state is OrderState.CREATED  # type: ignore[union-attr]
    assert intent.structure_type is StructureType.EQUITY  # type: ignore[union-attr]
    assert intent.symbol == "SPY"  # type: ignore[union-attr]
    assert intent.expires_at == NOW + timedelta(minutes=15)  # type: ignore[union-attr]
    assert intent.max_notional == pytest.approx(471.0)  # type: ignore[union-attr]


@pytest.mark.usefixtures("armed")
def test_p6_a_manually_accepted_paper_trade_is_never_an_order_source(
    session: Session, manual_paper_trade: PaperTrade
) -> None:
    """The §5.1 hole, closed. ``signalforge paper accept`` sets actor
    'local-user' and checks no gate, no status and no scope."""
    with pytest.raises(IntentRefused, match="P6"):
        _build(session, manual_paper_trade.id)


@pytest.mark.usefixtures("armed")
def test_p6_reads_the_column_not_the_json_blob(
    session: Session, account: PaperAccount, candidate: Candidate
) -> None:
    """A JSON blob claiming the automatic actor authorises nothing: the
    predicate is the indexed column. (``paper_trade`` is immutable at the
    database level, so the misleading blob is written at creation — which is
    also the only way a real writer could ever produce one.)"""
    trade = PaperTrade(
        account_id=account.id,
        candidate_id=candidate.id,
        decision=PaperDecision.ACCEPTED,
        signal_snapshot_json={"decision": {"actor": "auto_simulate", "automatic": True}},
        plan_json={"shares": 1},
        actor="local-user",
        created_at=NOW,
    )
    session.add(trade)
    session.flush()
    with pytest.raises(IntentRefused, match="P6"):
        _build(session, trade.id)


@pytest.mark.usefixtures("armed")
def test_p1_a_gate_failed_candidate_is_refused(
    session: Session, auto_paper_trade: PaperTrade, candidate: Candidate
) -> None:
    candidate.quality_gate_status = QualityGate.NO_TRADE
    session.flush()
    with pytest.raises(IntentRefused, match="P1"):
        _build(session, auto_paper_trade.id)


@pytest.mark.usefixtures("armed")
def test_p2_a_version_that_is_no_longer_paper_approved_is_refused(
    session: Session, auto_paper_trade: PaperTrade, strategy_version: StrategyVersion
) -> None:
    strategy_version.status = StrategyStatus.DISABLED
    session.flush()
    with pytest.raises(IntentRefused, match="P2"):
        _build(session, auto_paper_trade.id)


def test_p3_no_armed_row_at_all_is_refused(session: Session, auto_paper_trade: PaperTrade) -> None:
    with pytest.raises(IntentRefused, match="P3"):
        _build(session, auto_paper_trade.id)


def test_p3_a_disarmed_row_is_refused(
    session: Session, auto_paper_trade: PaperTrade, armed: ArmedStrategy
) -> None:
    armed.disarmed_at = NOW
    armed.disarm_reason = "operator"
    session.flush()
    with pytest.raises(IntentRefused, match="P3"):
        _build(session, auto_paper_trade.id)


def test_p3_an_expired_arming_is_refused(
    session: Session, auto_paper_trade: PaperTrade, armed: ArmedStrategy
) -> None:
    armed.expires_at = NOW - timedelta(seconds=1)
    session.flush()
    with pytest.raises(IntentRefused, match="P3"):
        _build(session, auto_paper_trade.id)


def test_p3_an_arming_on_another_adapter_is_refused(
    session: Session, auto_paper_trade: PaperTrade, armed: ArmedStrategy
) -> None:
    assert armed.adapter_name == ADAPTER
    with pytest.raises(IntentRefused, match="P3"):
        _build(session, auto_paper_trade.id, adapter_name="some_other_adapter")


@pytest.mark.usefixtures("armed")
def test_p4_a_scope_mismatch_is_refused(session: Session, auto_paper_trade: PaperTrade) -> None:
    with pytest.raises(IntentRefused, match="P4"):
        _build(session, auto_paper_trade.id, scope_matcher=lambda *_a: False)


@pytest.mark.usefixtures("armed")
def test_p4_a_scope_check_that_raises_is_a_refusal_not_a_pass(
    session: Session, auto_paper_trade: PaperTrade
) -> None:
    """§5.2: any check that cannot be EVALUATED counts as a failure."""

    def _boom(*_a: object) -> bool:
        raise RuntimeError("approval_scope unavailable")

    with pytest.raises(IntentRefused, match="P4: could not be evaluated"):
        _build(session, auto_paper_trade.id, scope_matcher=_boom)


def test_p4_the_real_matcher_is_fail_closed_on_an_unscoped_scan(
    session: Session, strategy_version: StrategyVersion, candidate: Candidate
) -> None:
    """``scan_scope_matches`` already refuses a ``None`` snapshot id, an empty
    source and an empty universe; the factory inherits that direction."""
    assert default_scope_matcher(session, strategy_version.id, candidate.scan_run_id) is False


@pytest.mark.usefixtures("armed")
def test_p5_a_candidate_with_no_risk_dollars_is_refused(
    session: Session, auto_paper_trade: PaperTrade, candidate: Candidate
) -> None:
    """The ``ledger.py`` 0.5%-of-cash fallback invents a size nothing downstream
    can distinguish from a risk-sized position."""
    candidate.risk_dollars = 0.0
    session.flush()
    with pytest.raises(IntentRefused, match="P5"):
        _build(session, auto_paper_trade.id)


@pytest.mark.usefixtures("armed")
def test_p7_no_limit_decision_at_all_is_refused(
    session: Session, auto_paper_trade: PaperTrade
) -> None:
    with pytest.raises(IntentRefused, match="P7"):
        _build(session, auto_paper_trade.id, limit_decision=None)


@pytest.mark.usefixtures("armed")
def test_p7_a_blocked_may_open_is_refused(
    session: Session, auto_paper_trade: PaperTrade, limit_set: object
) -> None:
    blocked = may_open(clean_open_context(dead_man_alive=False), limit_set)  # type: ignore[arg-type]
    assert not blocked.allowed
    with pytest.raises(IntentRefused, match="P7"):
        _build(session, auto_paper_trade.id, limit_decision=blocked)


@pytest.mark.usefixtures("armed")
def test_a_missing_paper_trade_is_refused(session: Session) -> None:
    with pytest.raises(IntentRefused):
        _build(session, 9_999)


@pytest.mark.usefixtures("armed")
def test_an_open_intent_cannot_carry_a_closing_side(
    session: Session, auto_paper_trade: PaperTrade
) -> None:
    with pytest.raises(IntentRefused):
        _build(session, auto_paper_trade.id, side=OrderSide.SELL_TO_CLOSE)


@pytest.mark.usefixtures("armed")
def test_an_intent_born_expired_is_refused(session: Session, auto_paper_trade: PaperTrade) -> None:
    with pytest.raises(IntentRefused, match="I1"):
        _build(session, auto_paper_trade.id, session_end_utc=NOW - timedelta(minutes=1))


@pytest.mark.usefixtures("armed")
def test_client_order_id_is_stable_across_retries(
    session: Session, auto_paper_trade: PaperTrade
) -> None:
    """A1 — a post-timeout retry must produce the SAME id, or idempotency is
    defeated exactly when it matters."""
    first = _build(session, auto_paper_trade.id)
    second = _build(session, auto_paper_trade.id)
    assert first.client_order_id == second.client_order_id  # type: ignore[union-attr]
