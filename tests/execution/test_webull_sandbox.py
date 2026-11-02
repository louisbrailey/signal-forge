"""``brokers/webull_sandbox.py`` — against a fake transport, never a socket.

Every assertion here is about the adapter's behaviour at the boundary D6
draws: the §13 proof is of the broker's body and the wire's host; A1 looks
before it submits; A2 is satisfied by refusal; A4 resolves terminal orders;
and no credential value ever reaches an audit payload.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import SecretStr

from signalforge.execution.brokers.vendor_base import CannedResponse, VendorRequest
from signalforge.execution.brokers.webull_sandbox import (
    PAPER_HOST_ALLOWLIST,
    WEBULL_SANDBOX_HOST,
    WebullSandboxBroker,
    sign_request,
)
from signalforge.execution.events import ExecutionEventType
from signalforge.execution.intents import (
    ComboOrderIntent,
    CostModelFeedback,
    IntentKind,
    OrderIntent,
    OrderLeg,
    OrderSide,
    StructureType,
)
from signalforge.execution.states import OrderState

NOW = datetime(2026, 11, 2, 15, 0, tzinfo=UTC)  # Monday 10:00 New York
ACCOUNT = "SBX-ACCOUNT-1"
APP_KEY = "sandbox-app-key"  # pragma: allowlist secret
APP_SECRET = "sandbox-app-secret-value"  # pragma: allowlist secret


@dataclass
class Sink:
    events: list[tuple[ExecutionEventType, dict[str, Any]]] = field(default_factory=list)

    def record(self, event_type: ExecutionEventType, /, **fields: Any) -> None:
        self.events.append((event_type, fields))

    def of(self, event_type: ExecutionEventType) -> list[dict[str, Any]]:
        return [f for t, f in self.events if t is event_type]


@dataclass
class FakeTransport:
    """Canned answers keyed by ``(method, path)``; records every request."""

    answers: dict[tuple[str, str], Any] = field(default_factory=dict)
    host: str = WEBULL_SANDBOX_HOST
    requests: list[VendorRequest] = field(default_factory=list)
    raise_on: set[tuple[str, str]] = field(default_factory=set)

    def __call__(self, request: VendorRequest) -> CannedResponse:
        self.requests.append(request)
        key = (request.method, request.path)
        if key in self.raise_on:
            raise TimeoutError("simulated transport timeout")
        answer = self.answers.get(key, (404, {"message": "not found"}))
        status, body = answer if isinstance(answer, tuple) else (200, answer)
        text = body if isinstance(body, str) else json.dumps(body)
        return CannedResponse(status=status, body=text, host=self.host)

    def sent(self, method: str, path: str) -> list[VendorRequest]:
        return [r for r in self.requests if (r.method, r.path) == (method, path)]


def _order_row(cid: str, status: str, filled: str = "0") -> dict[str, Any]:
    return {
        "client_order_id": cid,
        "order_id": f"wb-{cid}",
        "status": status,
        "symbol": "SPY",
        "side": "BUY",
        "total_quantity": "10",
        "filled_quantity": filled,
    }


def _transport(overrides: dict[tuple[str, str], Any] | None = None) -> FakeTransport:
    answers: dict[tuple[str, str], Any] = {
        ("GET", "/trading/accounts/list"): [{"account_id": ACCOUNT, "account_type": "CASH"}],
        ("GET", "/account/balance"): {
            "total_net_liquidation_value": "25000.00",
            "total_cash_balance": "24000.50",
            "total_asset_currency": "USD",
        },
        ("GET", "/account/positions"): [
            {"symbol": "SPY", "quantity": "10", "instrument_type": "EQUITY", "market_value": "4700"}
        ],
        ("GET", "/trading/orders/open-orders/list"): {"orders": []},
        ("GET", "/trade/calendar"): [{"trade_day": "2026-11-02", "trade_date_type": "NORMAL"}],
        ("POST", "/trading/orders/place"): {"client_order_id": "cid-1", "order_id": "wb-cid-1"},
        ("POST", "/trading/orders/cancel"): {"client_order_id": "cid-1"},
    }
    answers.update(overrides or {})
    return FakeTransport(answers=answers)


def _adapter(transport: FakeTransport, sink: Sink | None = None, *, expected: str = ACCOUNT):
    return WebullSandboxBroker(
        audit=sink or Sink(),
        expected_account_id=expected,
        transport=transport,
        app_key=SecretStr(APP_KEY),
        app_secret=SecretStr(APP_SECRET),
        now=lambda: NOW,
        nonce=lambda: "fixed-nonce",
    )


def _intent(cid: str = "cid-1", **changes: Any) -> OrderIntent:
    base: dict[str, Any] = {
        "client_order_id": cid,
        "intent_kind": IntentKind.OPEN,
        "side": OrderSide.BUY_TO_OPEN,
        "qty": 10,
        "limit_price": 471.5,
        "shares_per_contract": 1,
        "adapter_name": "webull_sandbox",
        "created_at": NOW,
        "expires_at": NOW + timedelta(minutes=15),
        "cost_model": CostModelFeedback(modelled_fill_price=471.5, modelled_spread_bps=5.0),
        "symbol": "SPY",
    }
    base.update(changes)
    return OrderIntent(**base)


# -- the allowlist is one sandbox host ---------------------------------------


def test_allowlist_names_exactly_the_sandbox_host() -> None:
    assert PAPER_HOST_ALLOWLIST == ("api.sandbox.webull.com",)
    assert "sandbox" in WEBULL_SANDBOX_HOST


# -- signing ----------------------------------------------------------------


def test_sign_request_matches_the_documented_scheme_byte_for_byte() -> None:
    headers = dict(
        sign_request(
            method="POST",
            host=WEBULL_SANDBOX_HOST,
            path="/trading/orders/place",
            query=(("a", "1"),),
            body={"account_id": ACCOUNT, "x": "y&z"},
            app_key=APP_KEY,
            app_secret=APP_SECRET,
            timestamp="2026-11-02T15:00:00Z",
            nonce="fixed-nonce",
        )
    )
    # Independent re-derivation of Webull's scheme (sorted name=value pairs,
    # host included, uppercase SHA-256 of the compact body appended, the
    # whole string percent-encoded, HMAC-SHA256 keyed by secret + "&").
    params = {
        "x-app-key": APP_KEY,
        "x-timestamp": "2026-11-02T15:00:00Z",
        "x-signature-version": "1.0",
        "x-signature-algorithm": "HMAC-SHA256",
        "x-signature-nonce": "fixed-nonce",
        "host": WEBULL_SANDBOX_HOST,
        "a": "1",
    }
    body = json.dumps({"account_id": ACCOUNT, "x": "y&z"}, separators=(",", ":"))
    s = "/trading/orders/place&" + "&".join(f"{k}={params[k]}" for k in sorted(params))
    s += "&" + hashlib.sha256(body.encode()).hexdigest().upper()
    from urllib.parse import quote

    expected = base64.b64encode(
        hmac.new((APP_SECRET + "&").encode(), quote(s, safe="").encode(), hashlib.sha256).digest()
    ).decode()
    assert headers["x-signature"] == expected
    assert headers["x-version"] == "v3"
    assert headers["Content-Type"] == "application/json"
    assert APP_SECRET not in json.dumps(headers)


def test_the_app_secret_is_never_a_header_and_never_audited() -> None:
    sink = Sink()
    transport = _transport()
    adapter = _adapter(transport, sink)
    adapter.is_paper()
    adapter.account()
    adapter.place(_intent())
    for request in transport.requests:
        assert APP_SECRET not in json.dumps(request.headers)
        assert APP_SECRET not in (request.body or "")
    assert APP_SECRET not in json.dumps([f for _, f in sink.events], default=str)


# -- §13 proof --------------------------------------------------------------


def test_is_paper_is_proven_from_the_body_and_the_wire_host() -> None:
    sink = Sink()
    proof = _adapter(_transport(), sink).is_paper()
    assert proof.proven is True
    assert proof.observed_account_id == ACCOUNT
    assert proof.observed_host == WEBULL_SANDBOX_HOST
    assert sink.of(ExecutionEventType.IS_PAPER_PROOF)[0]["payload"]["proven"] is True


def test_is_paper_fails_on_account_mismatch_and_blocks_submission() -> None:
    adapter = _adapter(_transport(), expected="SOMEONE-ELSE")
    proof = adapter.is_paper()
    assert proof.proven is False
    assert "does not match" in proof.failure_reason
    result = adapter.place(_intent())
    assert result.state is OrderState.REJECTED
    assert "is_paper proof failed" in result.error_verbatim


def test_is_paper_fails_when_the_wire_host_is_not_the_sandbox() -> None:
    transport = _transport()
    transport.host = "not-the-sandbox.invalid"
    proof = _adapter(transport).is_paper()
    assert proof.proven is False
    assert "allowlist" in proof.failure_reason


def test_is_paper_fails_on_an_absent_id_and_on_unreachable() -> None:
    assert _adapter(_transport({("GET", "/trading/accounts/list"): []})).is_paper().proven is False
    t = _transport()
    t.raise_on.add(("GET", "/trading/accounts/list"))
    proof = _adapter(t).is_paper()
    assert proof.proven is False
    assert "unreachable" in proof.failure_reason


def test_place_without_a_proof_is_rejected() -> None:
    transport = _transport()
    result = _adapter(transport).place(_intent())
    assert result.state is OrderState.REJECTED
    assert transport.sent("POST", "/trading/orders/place") == []


# -- reads ------------------------------------------------------------------


def test_account_positions_and_clock_translate_the_bodies() -> None:
    adapter = _adapter(_transport())
    account = adapter.account()
    assert (account.equity, account.cash, account.buying_power) == (25000.0, 24000.5, 24000.5)
    (snapshot,) = adapter.positions()
    assert snapshot.legs[0].instrument_key == "SPY"
    assert snapshot.legs[0].signed_qty == 10.0
    assert snapshot.market_value == 4700.0
    clock = adapter.clock()
    assert clock.is_open is True
    assert clock.as_of == NOW


def test_clock_is_closed_outside_the_core_session_or_on_a_non_trading_day() -> None:
    late = datetime(2026, 11, 2, 21, 30, tzinfo=UTC)  # 16:30 New York
    adapter = WebullSandboxBroker(
        audit=Sink(),
        expected_account_id=ACCOUNT,
        transport=_transport(),
        app_key=SecretStr(APP_KEY),
        app_secret=SecretStr(APP_SECRET),
        now=lambda: late,
    )
    assert adapter.clock().is_open is False
    holiday = _adapter(_transport({("GET", "/trade/calendar"): []}))
    assert holiday.clock().is_open is False


def test_unparseable_reads_raise_rather_than_guess() -> None:
    bad = _adapter(_transport({("GET", "/account/balance"): {"total_cash_balance": "x"}}))
    with pytest.raises(Exception, match=r"not a number|missing"):
        bad.account()
    off_host = _transport()
    off_host.host = "not-the-sandbox.invalid"
    with pytest.raises(Exception, match="allowlist"):
        _adapter(off_host).positions()


# -- A1 / A4 ----------------------------------------------------------------


def test_place_submits_once_and_a_retry_finds_the_first_attempt() -> None:
    transport = _transport()
    adapter = _adapter(transport)
    adapter.is_paper()
    first = adapter.place(_intent())
    assert first.state is OrderState.SUBMITTING
    assert first.broker_order_id == "wb-cid-1"
    sent = transport.sent("POST", "/trading/orders/place")
    assert len(sent) == 1
    body = json.loads(sent[0].body or "")
    assert body["account_id"] == ACCOUNT
    (order,) = body["new_orders"]
    assert order == {
        "client_order_id": "cid-1",
        "combo_type": "NORMAL",
        "symbol": "SPY",
        "instrument_type": "EQUITY",
        "market": "US",
        "order_type": "LIMIT",
        "limit_price": "471.5",
        "quantity": "10",
        "side": "BUY",
        "time_in_force": "DAY",
        "support_trading_session": "CORE",
        "entrust_type": "QTY",
    }
    assert ("category", "US_EQUITY") in sent[0].headers

    # The broker now knows the order; the retry must NOT submit again.
    transport.answers[("GET", "/trading/orders/get")] = {
        "orders": [_order_row("cid-1", "FILLED", "10")]
    }
    again = adapter.place(_intent())
    assert again.state is OrderState.FILLED
    assert len(transport.sent("POST", "/trading/orders/place")) == 1


def test_order_status_resolves_terminal_orders_and_absent_ones() -> None:
    transport = _transport(
        {("GET", "/trading/orders/get"): {"orders": [_order_row("cid-9", "CANCELLED", "3")]}}
    )
    adapter = _adapter(transport)
    status = adapter.order_status("cid-9")
    assert status is not None
    assert status.state is OrderState.PARTIAL  # cancelled with a partial fill
    assert status.filled_qty == 3.0
    assert status.broker_order_id == "wb-cid-9"
    transport.answers[("GET", "/trading/orders/get")] = (404, {"message": "no such order"})
    assert adapter.order_status("cid-missing") is None


def test_unknown_broker_statuses_map_to_unknown_never_to_a_guess() -> None:
    transport = _transport(
        {("GET", "/trading/orders/get"): {"orders": [_order_row("cid-2", "SOMETHING_NEW")]}}
    )
    status = _adapter(transport).order_status("cid-2")
    assert status is not None
    assert status.state is OrderState.UNKNOWN
    assert status.raw_status_verbatim == "SOMETHING_NEW"


def test_submission_failures_are_unknown_or_rejected_by_their_nature() -> None:
    # A transport failure AFTER the decision to submit: the order MAY exist.
    t = _transport()
    t.raise_on.add(("POST", "/trading/orders/place"))
    a = _adapter(t)
    a.is_paper()
    assert a.place(_intent()).state is OrderState.UNKNOWN
    # A 4xx is the broker saying no.
    t2 = _transport({("POST", "/trading/orders/place"): (417, {"message": "insufficient"})})
    a2 = _adapter(t2)
    a2.is_paper()
    rejected = a2.place(_intent())
    assert rejected.state is OrderState.REJECTED
    assert "417" in rejected.error_verbatim
    # A 200 that does not echo our id is NOT a success.
    t3 = _transport({("POST", "/trading/orders/place"): {"order_id": "wb-x"}})
    a3 = _adapter(t3)
    a3.is_paper()
    assert a3.place(_intent()).state is OrderState.UNKNOWN
    # An answer from the wrong host after a submission is UNKNOWN too.
    t4 = _transport()
    a4 = _adapter(t4)
    a4.is_paper()
    t4.host = "not-the-sandbox.invalid"
    assert a4.place(_intent()).state is OrderState.UNKNOWN


# -- scope refusals ---------------------------------------------------------


def test_refuses_shorts_options_and_combos_without_submitting() -> None:
    transport = _transport()
    adapter = _adapter(transport)
    adapter.is_paper()
    assert adapter.place(_intent(side=OrderSide.SELL_TO_OPEN)).state is OrderState.REFUSED
    option = _intent(symbol=None, option_ticker="O:SPY261120C00470000")
    assert adapter.place(option).state is OrderState.REFUSED
    combo = ComboOrderIntent(
        client_order_id="combo-1",
        intent_kind=IntentKind.OPEN,
        legs=(
            OrderLeg(
                side=OrderSide.SELL_TO_OPEN,
                ratio=1,
                shares_per_contract=100,
                strike=470.0,
                option_ticker="O:SPY261120P00470000",
            ),
            OrderLeg(
                side=OrderSide.BUY_TO_OPEN,
                ratio=1,
                shares_per_contract=100,
                strike=465.0,
                option_ticker="O:SPY261120P00465000",
            ),
        ),
        contracts=1,
        net_limit_price=1.0,
        structure_type=StructureType.SHORT_VERTICAL,
        adapter_name="webull_sandbox",
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
        cost_model=CostModelFeedback(modelled_fill_price=1.0, modelled_spread_bps=5.0),
    )
    result = adapter.place_combo(combo)
    assert result.state is OrderState.REFUSED
    assert "leg-by-leg" in result.error_verbatim
    assert transport.sent("POST", "/trading/orders/place") == []


# -- cancel -----------------------------------------------------------------


def test_cancel_and_cancel_all_report_the_broker_state_afterwards() -> None:
    transport = _transport(
        {
            ("GET", "/trading/orders/open-orders/list"): {
                "orders": [_order_row("cid-1", "SUBMITTED")]
            },
            ("GET", "/trading/orders/get"): {"orders": [_order_row("cid-1", "CANCELLED")]},
        }
    )
    adapter = _adapter(transport)
    (working,) = adapter.open_orders()
    assert working.state is OrderState.SUBMITTING
    (result,) = adapter.cancel_all()
    assert result.state is OrderState.CANCELLED
    body = json.loads(transport.sent("POST", "/trading/orders/cancel")[0].body or "")
    assert body == {"account_id": ACCOUNT, "client_order_id": "cid-1"}


def test_constructor_refuses_an_empty_expected_id_or_empty_credentials() -> None:
    with pytest.raises(ValueError, match="expected_account_id"):
        _adapter(_transport(), expected="")
    with pytest.raises(ValueError, match="non-empty"):
        WebullSandboxBroker(
            audit=Sink(),
            expected_account_id=ACCOUNT,
            transport=_transport(),
            app_key=SecretStr(""),
            app_secret=SecretStr(APP_SECRET),
            now=lambda: NOW,
        )
