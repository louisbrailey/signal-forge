"""I-E3 — the ``paper_reference`` adapter (D6 §3, §3.1, §13, §14, §15).

The properties asserted here are the ones the drills in §21 rest on, and each
is asserted as a *property of the code* rather than of one happy path:

* the fill rule is deterministic, reads nothing stamped at or after submission,
  and is never kinder than the backtest's cost model;
* ``is_paper()`` is a proof that FAILS on an account-id mismatch, and a failed
  proof blocks every submission;
* the same ``client_order_id`` never fills twice, and neither does the same
  order under a fresh id after a timeout;
* a combo partial fills every leg proportionally and can never leave an
  unpaired short leg;
* every call writes an ``execution_event`` through the I-E2 audit path;
* no socket is opened, ever.
"""

from __future__ import annotations

import socket
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import ExecutionEvent
from signalforge.execution.brokers import (
    ExecutionDisabled,
    UnknownAdapter,
    build_adapter,
    selected_adapter_name,
)
from signalforge.execution.brokers.paper_reference import (
    MODEL_SPREAD_BPS_FLOOR,
    PAPER_HOST_ALLOWLIST,
    PAPER_REFERENCE_NAME,
    SIMULATED_ACCOUNT_PREFIX,
    AdapterAudit,
    ByLegPartialHalt,
    ExecutionEventAudit,
    InMemoryBook,
    LookaheadRefused,
    PaperReferenceBroker,
    PaperReferenceOrderStore,
    PreSubmissionInformation,
    ReferenceQuote,
    SimulatedAccount,
    SimulatedBrokerTimeout,
    assert_no_naked_short_leg,
    degraded_limit,
    effective_spread_bps,
    half_spread_fraction,
)
from signalforge.execution.events import ExecutionEventType
from signalforge.execution.intents import (
    ComboOrderIntent,
    CostModelFeedback,
    IntentKind,
    MarketClock,
    OrderIntent,
    OrderLeg,
    OrderSide,
    OrderStatus,
    StructureType,
    client_order_id_for,
)
from signalforge.execution.protocol import BrokerAdapter
from signalforge.execution.states import OrderState

NOW = datetime(2026, 9, 11, 15, 0, tzinfo=UTC)
EARLIER = NOW - timedelta(minutes=1)
ACCOUNT_ID = f"{SIMULATED_ACCOUNT_PREFIX}OPTIONS-1"

SHORT_PUT = "SPY260918P00460000"
LONG_PUT = "SPY260918P00455000"

SHORT_VERTICAL_LEGS = (
    OrderLeg(
        side=OrderSide.SELL_TO_OPEN, ratio=1, shares_per_contract=100, option_ticker=SHORT_PUT
    ),
    OrderLeg(side=OrderSide.BUY_TO_OPEN, ratio=1, shares_per_contract=100, option_ticker=LONG_PUT),
)


class RecordingAudit:
    """A test double for :class:`AdapterAudit`.

    The production sink is :class:`ExecutionEventAudit`, exercised against a
    real session further down; this one exists so the fill arithmetic can be
    asserted without a database in the way.
    """

    def __init__(self) -> None:
        self.rows: list[tuple[ExecutionEventType, dict[str, Any]]] = []

    def record(self, event_type: ExecutionEventType, /, **fields: Any) -> None:
        self.rows.append((event_type, fields))

    def types(self) -> list[ExecutionEventType]:
        return [t for t, _ in self.rows]

    def reasons(self) -> list[str]:
        return [str(f.get("reason", "")) for _, f in self.rows]


def information(
    *,
    spy_available: int | None = None,
    short_available: int | None = None,
    long_available: int | None = None,
    as_of: datetime = EARLIER,
) -> PreSubmissionInformation:
    return PreSubmissionInformation.of(
        [
            ReferenceQuote("SPY", 470.0, as_of, available_qty=spy_available),
            ReferenceQuote(SHORT_PUT, 3.00, as_of, available_qty=short_available),
            ReferenceQuote(LONG_PUT, 1.40, as_of, available_qty=long_available),
        ]
    )


def make_adapter(
    *,
    audit: AdapterAudit | None = None,
    expected_account_id: str = ACCOUNT_ID,
    info: PreSubmissionInformation | None = None,
    clock: MarketClock | None = None,
    initial_cash: float = 25_000.0,
) -> PaperReferenceBroker:
    return PaperReferenceBroker(
        audit=audit or RecordingAudit(),
        account=SimulatedAccount(account_id=ACCOUNT_ID, initial_cash=initial_cash),
        expected_account_id=expected_account_id,
        information=info or information(),
        clock=clock or MarketClock(is_open=True, as_of=NOW),
        # A throwaway book: these tests are about the FILL RULE, and each one
        # wants its own empty account. The durable store has its own tests.
        book=InMemoryBook(),
    )


def equity_intent(
    *,
    client_order_id: str = "cid-equity",
    side: OrderSide = OrderSide.BUY_TO_OPEN,
    qty: int = 10,
    limit_price: float = 471.0,
    modelled_spread_bps: float = 5.0,
    source_paper_trade_id: int | None = None,
    strategy_version_id: int | None = None,
) -> OrderIntent:
    return OrderIntent(
        client_order_id=client_order_id,
        intent_kind=IntentKind.OPEN,
        side=side,
        qty=qty,
        limit_price=limit_price,
        shares_per_contract=1,
        adapter_name=PAPER_REFERENCE_NAME,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
        cost_model=CostModelFeedback(
            modelled_fill_price=limit_price, modelled_spread_bps=modelled_spread_bps
        ),
        symbol="SPY",
        source_paper_trade_id=source_paper_trade_id,
        strategy_version_id=strategy_version_id,
        config_hash="cfg",
        spec_json_hash="spec",
    )


def combo_intent(
    *,
    client_order_id: str = "cid-combo",
    contracts: int = 5,
    net_limit_price: float = 1.50,
    modelled_spread_bps: float = 5.0,
    source_paper_trade_id: int | None = None,
    strategy_version_id: int | None = None,
) -> ComboOrderIntent:
    return ComboOrderIntent(
        client_order_id=client_order_id,
        intent_kind=IntentKind.OPEN,
        legs=SHORT_VERTICAL_LEGS,
        contracts=contracts,
        net_limit_price=net_limit_price,
        structure_type=StructureType.SHORT_VERTICAL,
        adapter_name=PAPER_REFERENCE_NAME,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
        cost_model=CostModelFeedback(
            modelled_fill_price=net_limit_price, modelled_spread_bps=modelled_spread_bps
        ),
        source_paper_trade_id=source_paper_trade_id,
        strategy_version_id=strategy_version_id,
        config_hash="cfg",
        spec_json_hash="spec",
    )


# ---------------------------------------------------------------------------
# The protocol (§3)
# ---------------------------------------------------------------------------


def test_the_adapter_satisfies_the_broker_adapter_protocol() -> None:
    adapter = make_adapter()
    assert isinstance(adapter, BrokerAdapter)
    # runtime_checkable only checks that the names exist; the signatures are
    # checked statically by the `_PROTOCOL_CHECK` binding in the module, which
    # mypy verifies. Both halves are needed and neither replaces the other.
    for method in (
        "is_paper",
        "account",
        "positions",
        "open_orders",
        "order_status",
        "place",
        "place_combo",
        "cancel",
        "cancel_all",
        "clock",
    ):
        assert callable(getattr(adapter, method)), method
    assert adapter.name == PAPER_REFERENCE_NAME


# ---------------------------------------------------------------------------
# §3.1 rule 2 — never better than the modelled spread
# ---------------------------------------------------------------------------


def test_the_spread_floor_is_the_constant_the_backtest_uses() -> None:
    """D6 §15 forbids an ``execution -> paper`` import, so the constant is
    duplicated. This is the test that stops the duplicate drifting: if the
    ledger's spread ever changes, the simulator stops being kinder-proof and
    this fails loudly."""
    from signalforge.paper import ledger

    assert MODEL_SPREAD_BPS_FLOOR == ledger._NOMINAL_SPREAD_BPS == 5.0


def test_half_spread_matches_the_ledgers_arithmetic() -> None:
    assert half_spread_fraction(5.0) == (5.0 / 10_000.0) / 2.0


def test_a_buy_pays_the_half_spread_and_a_sell_receives_it() -> None:
    adapter = make_adapter()
    adapter.place(equity_intent(client_order_id="buy", side=OrderSide.BUY_TO_OPEN))
    adapter.place(
        equity_intent(
            client_order_id="sell",
            side=OrderSide.SELL_TO_OPEN,
            limit_price=469.0,
        )
    )
    half = half_spread_fraction(5.0)
    assert adapter.fills_for("buy")[0].price == pytest.approx(471.0 * (1 + half))
    assert adapter.fills_for("sell")[0].price == pytest.approx(469.0 * (1 - half))


def test_an_intent_with_a_kinder_modelled_spread_still_gets_the_floor() -> None:
    """The hazard rule 2 exists for: an intent built with a tighter spread than
    the backtest's would otherwise make the simulator kinder than the model the
    evidence rests on."""
    adapter = make_adapter()
    adapter.place(equity_intent(client_order_id="kind", modelled_spread_bps=0.5))
    floor_half = half_spread_fraction(MODEL_SPREAD_BPS_FLOOR)
    assert adapter.fills_for("kind")[0].price == pytest.approx(471.0 * (1 + floor_half))
    assert effective_spread_bps(0.5) == MODEL_SPREAD_BPS_FLOOR


def test_a_wider_modelled_spread_is_honoured_rather_than_clipped_to_the_floor() -> None:
    adapter = make_adapter()
    adapter.place(equity_intent(client_order_id="wide", modelled_spread_bps=25.0))
    assert effective_spread_bps(25.0) == 25.0
    assert adapter.fills_for("wide")[0].price == pytest.approx(
        471.0 * (1 + half_spread_fraction(25.0))
    )


def test_the_degraded_limit_is_worse_for_a_credit_and_for_a_debit_alike() -> None:
    assert degraded_limit(1.50, 5.0) < 1.50  # a credit: receive less
    assert degraded_limit(-2.00, 5.0) < -2.00  # a debit: pay more


def test_a_combo_fills_at_the_degraded_net_and_the_legs_reconstruct_it_exactly() -> None:
    adapter = make_adapter(info=information(short_available=10, long_available=10))
    adapter.place_combo(combo_intent())
    fills = adapter.fills_for("cid-combo")
    net = sum(
        (fill.price if SHORT_VERTICAL_LEGS[fill.leg_index].side.sign < 0 else -fill.price)
        * SHORT_VERTICAL_LEGS[fill.leg_index].ratio
        for fill in fills
    )
    assert net == pytest.approx(degraded_limit(1.50, 5.0))
    assert net < 1.50, "the structure must never receive more credit than its limit"


# ---------------------------------------------------------------------------
# §3.1 rule 1 — the information set
# ---------------------------------------------------------------------------


def test_a_quote_stamped_at_the_submission_timestamp_is_refused() -> None:
    """Rule 1's two halves differ at the boundary instant; the prohibition ("no
    bar stamped at or after") is the operative one."""
    adapter = make_adapter(info=information(as_of=NOW))
    with pytest.raises(LookaheadRefused, match="strictly earlier"):
        adapter.place(equity_intent())


def test_a_quote_stamped_after_submission_is_refused() -> None:
    adapter = make_adapter(info=information(as_of=NOW + timedelta(seconds=1)))
    with pytest.raises(LookaheadRefused):
        adapter.place(equity_intent())


def test_the_latest_quote_strictly_before_submission_is_the_one_used() -> None:
    info = PreSubmissionInformation.of(
        [
            ReferenceQuote("SPY", 400.0, NOW - timedelta(minutes=30)),
            ReferenceQuote("SPY", 470.0, NOW - timedelta(minutes=1)),
            ReferenceQuote("SPY", 999.0, NOW),  # lookahead — must be invisible
        ]
    )
    assert info.quote("SPY", submitted_at=NOW).reference_price == 470.0


def test_an_instrument_with_no_quote_is_rejected_not_filled() -> None:
    adapter = make_adapter(info=PreSubmissionInformation.of([]))
    result = adapter.place(equity_intent())
    assert result.state is OrderState.REJECTED
    assert "no pre-submission quote" in result.error_verbatim
    assert adapter.fills_for("cid-equity") == ()


# ---------------------------------------------------------------------------
# §3.1 rule 3 — determinism
# ---------------------------------------------------------------------------


def test_the_same_intent_against_the_same_information_fills_identically() -> None:
    def run() -> tuple[Any, ...]:
        adapter = make_adapter(info=information(short_available=3, long_available=3))
        equity = adapter.place(equity_intent())
        combo = adapter.place_combo(combo_intent())
        return (
            equity,
            combo,
            adapter.fills_for("cid-equity"),
            adapter.fills_for("cid-combo"),
            adapter.account(),
            tuple(adapter.positions()),
        )

    first, second = run(), run()
    assert first == second


def test_the_broker_order_id_is_a_function_of_the_client_order_id_only() -> None:
    a = make_adapter()
    b = make_adapter(initial_cash=99_000.0)
    assert a.place(equity_intent()).broker_order_id == b.place(equity_intent()).broker_order_id


# ---------------------------------------------------------------------------
# §3.1 rule 4 — the output is never evidence
# ---------------------------------------------------------------------------


def test_equity_never_moves_because_the_book_is_marked_at_cost() -> None:
    """There is no performance number here to mistake for evidence."""
    adapter = make_adapter(info=information(short_available=10, long_available=10))
    before = adapter.account()
    adapter.place(equity_intent())
    adapter.place_combo(combo_intent())
    after = adapter.account()
    assert after.equity == before.equity == 25_000.0
    assert after.cash != before.cash, "cash moves; equity does not"


def test_every_event_is_tagged_with_the_adapter_name(session: Session) -> None:
    adapter = make_adapter(
        audit=ExecutionEventAudit(session), info=information(short_available=10, long_available=10)
    )
    adapter.place(equity_intent())
    adapter.place_combo(combo_intent())
    rows = session.scalars(select(ExecutionEvent)).all()
    assert rows
    assert {row.adapter_name for row in rows} == {PAPER_REFERENCE_NAME}


# ---------------------------------------------------------------------------
# §13 — the is_paper proof
# ---------------------------------------------------------------------------


def test_is_paper_is_proven_when_the_account_id_matches() -> None:
    proof = make_adapter().is_paper()
    assert proof.proven is True
    assert proof.observed_account_id == ACCOUNT_ID
    assert proof.observed_host in PAPER_HOST_ALLOWLIST
    assert proof.failure_reason == ""


def test_an_account_id_mismatch_fails_the_proof_and_every_submission() -> None:
    """V9 / T6. The local simulator can never reach real money — and that is
    still not why the proof passes."""
    audit = RecordingAudit()
    adapter = make_adapter(audit=audit, expected_account_id="PAPER-SIM-SOMEONE-ELSE")
    proof = adapter.is_paper()
    assert proof.proven is False
    assert "does not match" in proof.failure_reason

    result = adapter.place(equity_intent())
    assert result.state is OrderState.REJECTED
    assert "is_paper proof failed" in result.error_verbatim
    assert adapter.fills_for("cid-equity") == ()
    assert adapter.positions() == ()

    combo = adapter.place_combo(combo_intent())
    assert combo.state is OrderState.REJECTED
    assert ExecutionEventType.IS_PAPER_PROOF in audit.types()


def test_the_proof_is_retaken_on_every_call_never_cached() -> None:
    audit = RecordingAudit()
    adapter = make_adapter(audit=audit)
    adapter.is_paper()
    adapter.is_paper()
    assert audit.types().count(ExecutionEventType.IS_PAPER_PROOF) == 2


def test_a_submission_reproves_is_paper_rather_than_trusting_an_earlier_proof() -> None:
    audit = RecordingAudit()
    adapter = make_adapter(audit=audit)
    adapter.place(equity_intent())
    assert ExecutionEventType.IS_PAPER_PROOF in audit.types()


def test_the_simulated_account_id_must_say_it_is_simulated() -> None:
    with pytest.raises(ValueError, match=SIMULATED_ACCOUNT_PREFIX):
        SimulatedAccount(account_id="LIVE-ACCOUNT-1", initial_cash=1000.0)


def test_an_adapter_without_an_expected_account_id_cannot_be_built() -> None:
    with pytest.raises(ValueError, match="expected_account_id"):
        make_adapter(expected_account_id="")


# ---------------------------------------------------------------------------
# A1 — idempotency, and the post-timeout procedure (§8)
# ---------------------------------------------------------------------------


def test_resubmitting_the_same_client_order_id_returns_the_same_result(session: Session) -> None:
    adapter = make_adapter(audit=ExecutionEventAudit(session))
    first = adapter.place(equity_intent())
    cash_after_first = adapter.account().cash
    second = adapter.place(equity_intent())
    assert second == first
    assert adapter.account().cash == cash_after_first, "a duplicate id must not fill twice"
    assert len(adapter.fills_for("cid-equity")) == 1
    fills = session.scalars(
        select(ExecutionEvent).where(ExecutionEvent.event_type == ExecutionEventType.FILL.value)
    ).all()
    assert len(fills) == 1


def test_a_timeout_leaves_the_order_on_the_book_and_order_status_resolves_it() -> None:
    """V6 — ``open_orders()`` alone could not tell "never saw it" from "filled
    and no longer open"; the by-id lookup can (A4)."""
    adapter = make_adapter()
    adapter.arm_timeout_once()
    with pytest.raises(SimulatedBrokerTimeout):
        adapter.place(equity_intent())

    assert adapter.open_orders() == (), "a filled order is not an open order"
    status = adapter.order_status("cid-equity")
    assert isinstance(status, OrderStatus)
    assert status.state is OrderState.FILLED


def test_a_resubmission_after_a_timeout_does_not_double_fill() -> None:
    adapter = make_adapter()
    adapter.arm_timeout_once()
    with pytest.raises(SimulatedBrokerTimeout):
        adapter.place(equity_intent())
    cash_after_timeout = adapter.account().cash

    again = adapter.place(equity_intent())
    assert again.state is OrderState.FILLED
    assert adapter.account().cash == cash_after_timeout
    assert len(adapter.fills_for("cid-equity")) == 1


def test_a_fresh_client_order_id_after_a_timeout_is_refused_not_duplicated() -> None:
    """Stricter than a real broker, deliberately. §5.4 already makes minting a
    new id impossible from the factories (the id is a hash with no attempt
    counter); this closes the hazard from the adapter's side as well."""
    adapter = make_adapter()
    adapter.arm_timeout_once()
    with pytest.raises(SimulatedBrokerTimeout):
        adapter.place(equity_intent(client_order_id="cid-first"))
    cash = adapter.account().cash

    retry = adapter.place(equity_intent(client_order_id="cid-second-attempt"))
    assert retry.state is OrderState.REJECTED
    assert "cid-first" in retry.error_verbatim
    assert adapter.account().cash == cash
    assert adapter.fills_for("cid-second-attempt") == ()


def test_the_intent_factory_cannot_mint_a_new_id_for_a_retry() -> None:
    """The other half of the same guarantee, at the source (§5.4, T3)."""
    first = client_order_id_for(source_trade_id=7, legs=SHORT_VERTICAL_LEGS)
    second = client_order_id_for(source_trade_id=7, legs=SHORT_VERTICAL_LEGS)
    assert first == second


# ---------------------------------------------------------------------------
# §14 — combos are atomic, and a partial never leaves a naked short
# ---------------------------------------------------------------------------


def test_a_proportional_partial_fills_every_leg_by_the_same_ratio() -> None:
    adapter = make_adapter(info=information(short_available=3, long_available=3))
    result = adapter.place_combo(combo_intent(contracts=5))
    assert result.state is OrderState.PARTIAL
    status = adapter.order_status("cid-combo")
    assert status is not None
    assert status.filled_qty == 3.0
    assert status.legs_filled_ratio == (0.6, 0.6)
    assert len({round(r, 9) for r in status.legs_filled_ratio}) == 1


def test_the_scarcest_leg_binds_and_the_short_leg_never_fills_alone() -> None:
    """The exact hazard §14 names: the short leg fills, the long wing does not,
    and the account holds an accidental naked short option."""
    adapter = make_adapter(info=information(short_available=5, long_available=0))
    result = adapter.place_combo(combo_intent(contracts=5))
    assert result.state is OrderState.SUBMITTING, "unfilled, working — not a position"
    assert adapter.fills_for("cid-combo") == ()
    assert adapter.positions() == ()
    status = adapter.order_status("cid-combo")
    assert status is not None
    assert status.legs_filled_ratio == (0.0, 0.0)


def test_a_partial_leaves_a_defined_risk_structure_not_an_unpaired_leg() -> None:
    adapter = make_adapter(info=information(short_available=2, long_available=4))
    adapter.place_combo(combo_intent(contracts=5))
    (position,) = adapter.positions()
    by_key = {leg.instrument_key: leg.signed_qty for leg in position.legs}
    assert by_key[SHORT_PUT] == -2.0
    assert by_key[LONG_PUT] == 2.0
    assert by_key[SHORT_PUT] + by_key[LONG_PUT] == 0.0


def test_the_by_leg_partial_halt_bites_when_ratios_disagree() -> None:
    with pytest.raises(ByLegPartialHalt, match="naked short"):
        assert_no_naked_short_leg(SHORT_VERTICAL_LEGS, (1.0, 0.0), client_order_id="cid")
    # And it does not bite on the shape the adapter actually produces.
    assert_no_naked_short_leg(SHORT_VERTICAL_LEGS, (0.6, 0.6), client_order_id="cid")


def test_a_combo_submits_as_one_order_with_one_client_order_id() -> None:
    """A2: one atomic instruction, no loop over legs."""
    adapter = make_adapter(info=information(short_available=10, long_available=10))
    adapter.place_combo(combo_intent())
    assert sorted(adapter.book()) == ["cid-combo"]
    assert (
        len({fill.broker_fill_id.rsplit("-L", 1)[0] for fill in adapter.fills_for("cid-combo")})
        == 1
    )


def test_a_non_marketable_combo_rests_rather_than_filling_at_a_kinder_price() -> None:
    adapter = make_adapter(info=information(short_available=10, long_available=10))
    # Reference net credit is 3.00 - 1.40 = 1.60; asking 2.00 is not marketable.
    result = adapter.place_combo(combo_intent(net_limit_price=2.00))
    assert result.state is OrderState.SUBMITTING
    assert "not marketable" in result.raw_status_verbatim
    assert adapter.fills_for("cid-combo") == ()


# ---------------------------------------------------------------------------
# Cancel semantics and order status (§8, A4)
# ---------------------------------------------------------------------------


def test_a_working_order_cancels() -> None:
    adapter = make_adapter(info=information(short_available=10, long_available=10))
    adapter.place_combo(combo_intent(net_limit_price=2.00))
    result = adapter.cancel("cid-combo")
    assert result.state is OrderState.CANCELLED
    assert adapter.open_orders() == ()
    status = adapter.order_status("cid-combo")
    assert status is not None and status.state is OrderState.CANCELLED


def test_cancelling_a_filled_order_reports_it_filled_and_changes_nothing() -> None:
    """Telling the OMS that a filled order was cancelled is how a position goes
    missing."""
    adapter = make_adapter()
    adapter.place(equity_intent())
    result = adapter.cancel("cid-equity")
    assert result.state is OrderState.FILLED
    assert "already terminal" in result.error_verbatim
    assert len(adapter.fills_for("cid-equity")) == 1


def test_cancelling_an_unknown_id_is_refused_not_invented() -> None:
    result = make_adapter().cancel("never-submitted")
    assert result.state is OrderState.REJECTED
    assert "unknown client_order_id" in result.error_verbatim


def test_cancel_all_drains_working_orders_in_a_deterministic_order() -> None:
    adapter = make_adapter(info=information(short_available=10, long_available=10))
    adapter.place_combo(combo_intent(client_order_id="cid-b", net_limit_price=2.00))
    adapter.place_combo(combo_intent(client_order_id="cid-a", net_limit_price=2.10, contracts=4))
    adapter.place(equity_intent(client_order_id="cid-filled"))
    results = adapter.cancel_all()
    assert [r.client_order_id for r in results] == ["cid-a", "cid-b"]
    assert all(r.state is OrderState.CANCELLED for r in results)
    # The filled one was not touched.
    filled = adapter.order_status("cid-filled")
    assert filled is not None and filled.state is OrderState.FILLED


def test_order_status_resolves_terminal_orders_and_returns_none_for_unknown() -> None:
    adapter = make_adapter()
    adapter.place(equity_intent())
    assert adapter.order_status("cid-equity") is not None
    assert adapter.order_status("no-such-id") is None
    assert adapter.open_orders() == ()


def test_a_rejection_is_verbatim_and_is_not_retried() -> None:
    adapter = make_adapter(info=PreSubmissionInformation.of([]))
    first = adapter.place(equity_intent())
    second = adapter.place(equity_intent())
    assert first.state is OrderState.REJECTED
    assert second == first, "a rejected order is not resubmitted by re-placing the same id"


# ---------------------------------------------------------------------------
# §15 — audit records for every call, through the I-E2 path
# ---------------------------------------------------------------------------


def test_every_adapter_call_writes_an_execution_event(session: Session) -> None:
    adapter = make_adapter(
        audit=ExecutionEventAudit(session), info=information(short_available=10, long_available=10)
    )
    adapter.is_paper()
    adapter.account()
    adapter.positions()
    adapter.open_orders()
    adapter.clock()
    adapter.place(equity_intent())
    adapter.place_combo(combo_intent())
    adapter.order_status("cid-combo")
    adapter.cancel("cid-combo")
    adapter.cancel_all()

    reasons = [row.reason for row in session.scalars(select(ExecutionEvent)).all()]
    for fragment in (
        "is_paper",
        "account()",
        "positions()",
        "open_orders()",
        "clock()",
        "order_status(",
        "cancel",
    ):
        assert any(fragment in reason for reason in reasons), fragment


def test_fill_events_carry_the_cost_model_feedback(session: Session) -> None:
    """§4.2 — realized-vs-modelled must be computable from the audit trail
    rather than reconstructed."""
    adapter = make_adapter(audit=ExecutionEventAudit(session))
    adapter.place(equity_intent())
    row = session.scalars(
        select(ExecutionEvent).where(ExecutionEvent.event_type == ExecutionEventType.FILL.value)
    ).one()
    assert row.modelled_fill_price == 471.0
    assert row.modelled_spread_bps == 5.0
    assert row.realized_fill_price == pytest.approx(471.0 * (1 + half_spread_fraction(5.0)))
    assert row.realized_minus_modelled_bps == pytest.approx(2.5)
    assert row.config_hash == "cfg" and row.spec_json_hash == "spec"


def test_a_combo_writes_one_fill_event_per_leg(session: Session) -> None:
    adapter = make_adapter(
        audit=ExecutionEventAudit(session), info=information(short_available=10, long_available=10)
    )
    adapter.place_combo(combo_intent())
    rows = session.scalars(
        select(ExecutionEvent)
        .where(ExecutionEvent.event_type == ExecutionEventType.FILL.value)
        .order_by(ExecutionEvent.leg_index)
    ).all()
    assert [row.leg_index for row in rows] == [0, 1]
    assert all(row.client_order_id == "cid-combo" for row in rows)


def test_the_audit_row_carries_the_originating_paper_trade_and_strategy(
    session: Session, auto_paper_trade: Any, strategy_version: Any
) -> None:
    """The provenance columns are real foreign keys, so an event cannot name a
    paper trade or a strategy version that does not exist."""
    adapter = make_adapter(audit=ExecutionEventAudit(session))
    adapter.place(
        equity_intent(
            source_paper_trade_id=auto_paper_trade.id,
            strategy_version_id=strategy_version.id,
        )
    )
    row = session.scalars(
        select(ExecutionEvent).where(ExecutionEvent.event_type == ExecutionEventType.FILL.value)
    ).one()
    assert row.source_paper_trade_id == auto_paper_trade.id
    assert row.strategy_version_id == strategy_version.id


def test_a_rejection_is_recorded_with_its_verbatim_text(session: Session) -> None:
    adapter = make_adapter(
        audit=ExecutionEventAudit(session), expected_account_id="PAPER-SIM-OTHER"
    )
    adapter.place(equity_intent())
    row = session.scalars(
        select(ExecutionEvent).where(
            ExecutionEvent.event_type == ExecutionEventType.REJECTION.value
        )
    ).one()
    assert "is_paper proof failed" in row.error_verbatim
    assert row.state_to == OrderState.REJECTED.value


def test_the_audit_sink_is_required_and_has_no_null_default() -> None:
    with pytest.raises(TypeError):
        PaperReferenceBroker(  # type: ignore[call-arg]
            account=SimulatedAccount(account_id=ACCOUNT_ID, initial_cash=1.0),
            expected_account_id=ACCOUNT_ID,
            information=information(),
            clock=MarketClock(is_open=True, as_of=NOW),
            book=InMemoryBook(),
        )


# ---------------------------------------------------------------------------
# No socket, ever
# ---------------------------------------------------------------------------


def test_no_socket_is_ever_opened(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("paper_reference opened a socket")

    monkeypatch.setattr(socket, "socket", explode)
    monkeypatch.setattr(socket, "create_connection", explode)
    monkeypatch.setattr(socket, "socketpair", explode)
    monkeypatch.setattr(socket, "getaddrinfo", explode)

    adapter = make_adapter(info=information(short_available=10, long_available=10))
    adapter.is_paper()
    adapter.account()
    adapter.positions()
    adapter.open_orders()
    adapter.clock()
    adapter.place(equity_intent())
    adapter.place_combo(combo_intent())
    adapter.order_status("cid-combo")
    adapter.cancel_all()
    assert adapter.fills_for("cid-combo")


def test_the_module_imports_no_network_or_vendor_package() -> None:
    import ast
    from pathlib import Path

    from signalforge.execution.brokers import paper_reference

    path = Path(paper_reference.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    heads: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            heads.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            heads.add(node.module.split(".")[0])
    forbidden = {"httpx", "requests", "aiohttp", "socket", "urllib", "http", "ssl", "alpaca"}
    assert not heads & forbidden, sorted(heads & forbidden)


# ---------------------------------------------------------------------------
# §2 — selectable ONLY through the config, never by an import side effect
# ---------------------------------------------------------------------------


def test_the_adapter_is_not_selectable_while_execution_is_disabled() -> None:
    from signalforge.config.research import ResearchConfig

    with pytest.raises(ExecutionDisabled, match="enabled is False"):
        selected_adapter_name(ResearchConfig())
    with pytest.raises(ExecutionDisabled):
        build_adapter(ResearchConfig())


def test_an_unknown_adapter_name_is_refused_with_no_fallback() -> None:
    from signalforge.config.research import ExecutionConfig, ResearchConfig

    config = ResearchConfig(
        execution=ExecutionConfig(enabled=True, adapter_name="some_vendor_paper")
    )
    with pytest.raises(UnknownAdapter, match="no default to fall back to"):
        selected_adapter_name(config)


def test_the_adapter_is_built_when_the_config_selects_it(session: Session) -> None:
    from signalforge.config.research import ExecutionConfig, ResearchConfig

    config = ResearchConfig(execution=ExecutionConfig(enabled=True))
    adapter = build_adapter(
        config,
        audit=ExecutionEventAudit(session),
        account=SimulatedAccount(account_id=ACCOUNT_ID, initial_cash=25_000.0),
        expected_account_id=ACCOUNT_ID,
        information=information(),
        clock=MarketClock(is_open=True, as_of=NOW),
        book=PaperReferenceOrderStore(session),
    )
    assert isinstance(adapter, PaperReferenceBroker)
    assert adapter.name == PAPER_REFERENCE_NAME
    assert adapter.is_paper().proven is True


def test_the_default_config_selects_nothing_at_all() -> None:
    from signalforge.config.research import ResearchConfig

    assert ResearchConfig().execution.enabled is False
    assert ResearchConfig().execution.adapter_name == PAPER_REFERENCE_NAME


def test_an_option_leg_with_a_non_100_deliverable_is_refused() -> None:
    """§14 rule 5: a non-100 deliverable is the machine-readable signature of an
    OCC adjustment, and the intent is refused rather than priced."""
    adapter = make_adapter()
    adjusted = OrderIntent(
        client_order_id="cid-adjusted",
        intent_kind=IntentKind.OPEN,
        side=OrderSide.SELL_TO_OPEN,
        qty=1,
        limit_price=3.00,
        shares_per_contract=50,
        adapter_name=PAPER_REFERENCE_NAME,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
        cost_model=CostModelFeedback(modelled_fill_price=3.00, modelled_spread_bps=5.0),
        option_ticker=SHORT_PUT,
    )
    result = adapter.place(adjusted)
    assert result.state is OrderState.REJECTED
    assert "OCC adjustment" in result.error_verbatim
    assert adapter.fills_for("cid-adjusted") == ()


def test_a_reference_on_the_wrong_side_of_the_limit_refuses_rather_than_inventing_prices() -> None:
    """The degenerate allocation case, refused in the open rather than papered
    over: per-leg prices cannot be scaled out of a net that is on the other side
    of zero from the reference."""
    adapter = make_adapter(info=information(short_available=10, long_available=10))
    # The reference is a 1.60 credit; the intent asks to PAY a 0.50 debit.
    result = adapter.place_combo(combo_intent(net_limit_price=-0.50))
    assert result.state is OrderState.REJECTED
    assert "not on the same side" in result.error_verbatim
    assert adapter.fills_for("cid-combo") == ()


def test_a_reference_quote_must_be_a_real_quote() -> None:
    with pytest.raises(ValueError, match="instrument key"):
        ReferenceQuote("", 470.0, EARLIER)
    with pytest.raises(ValueError, match="reference_price"):
        ReferenceQuote("SPY", 0.0, EARLIER)
    with pytest.raises(ValueError, match="available_qty"):
        ReferenceQuote("SPY", 470.0, EARLIER, available_qty=-1)


def test_the_drill_controls_move_the_session_not_the_fill_rule() -> None:
    """``set_clock`` moves the simulated session for V10/V12; it is not a price
    source, and the fill still comes only from the information set."""
    adapter = make_adapter()
    later = NOW + timedelta(hours=1)
    adapter.set_clock(MarketClock(is_open=False, as_of=later, is_early_close=True))
    assert adapter.clock().is_open is False
    assert adapter.clock().is_early_close is True
    adapter.set_information(
        PreSubmissionInformation.of([ReferenceQuote("SPY", 480.0, later - timedelta(minutes=1))])
    )
    adapter.place(equity_intent(limit_price=481.0))
    assert adapter.fills_for("cid-equity")[0].price == pytest.approx(
        481.0 * (1 + half_spread_fraction(5.0))
    )
    assert adapter.fills_for("cid-equity")[0].filled_at == later


def test_the_selector_reads_the_live_settings_when_no_config_is_passed() -> None:
    """The shipped posture, through the same call the CLI will make."""
    with pytest.raises(ExecutionDisabled):
        selected_adapter_name()


def test_a_registry_key_that_disagrees_with_its_adapter_is_refused(
    monkeypatch: pytest.MonkeyPatch, session: Session
) -> None:
    """A registry whose key and adapter disagree would make the audit trail lie
    about which adapter ran."""
    from signalforge.config.research import ExecutionConfig, ResearchConfig
    from signalforge.execution import brokers

    class Impostor(PaperReferenceBroker):
        name = "something_else"

    monkeypatch.setitem(brokers._REGISTRY, "paper_reference", lambda: Impostor)
    with pytest.raises(UnknownAdapter, match="calling itself"):
        build_adapter(
            ResearchConfig(execution=ExecutionConfig(enabled=True)),
            audit=ExecutionEventAudit(session),
            account=SimulatedAccount(account_id=ACCOUNT_ID, initial_cash=25_000.0),
            expected_account_id=ACCOUNT_ID,
            information=information(),
            clock=MarketClock(is_open=True, as_of=NOW),
            book=PaperReferenceOrderStore(session),
        )
