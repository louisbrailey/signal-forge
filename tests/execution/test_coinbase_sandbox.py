"""``brokers/coinbase_sandbox.py`` — against a fake transport, never a socket."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from signalforge.execution.brokers.coinbase_sandbox import (
    COINBASE_SANDBOX_HOST,
    PAPER_HOST_ALLOWLIST,
    CoinbaseSandboxBroker,
)
from signalforge.execution.brokers.vendor_base import CannedResponse, VendorRequest
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

NOW = datetime(2026, 11, 2, 15, 0, tzinfo=UTC)
PORTFOLIO = "b87a2d3f-8a1e-49b3-a4ea-402d8c389aca"
BASE = "/api/v3/brokerage"


@dataclass
class Sink:
    events: list[tuple[ExecutionEventType, dict[str, Any]]] = field(default_factory=list)

    def record(self, event_type: ExecutionEventType, /, **fields: Any) -> None:
        self.events.append((event_type, fields))


@dataclass
class FakeTransport:
    answers: dict[tuple[str, str], Any] = field(default_factory=dict)
    host: str = COINBASE_SANDBOX_HOST
    requests: list[VendorRequest] = field(default_factory=list)
    raise_on: set[tuple[str, str]] = field(default_factory=set)

    def __call__(self, request: VendorRequest) -> CannedResponse:
        self.requests.append(request)
        key = (request.method, request.path)
        if key in self.raise_on:
            raise TimeoutError("simulated transport timeout")
        answer = self.answers.get(key, (404, {"error": "not found"}))
        status, body = answer if isinstance(answer, tuple) else (200, answer)
        return CannedResponse(status=status, body=json.dumps(body), host=self.host)

    def sent(self, method: str, path: str) -> list[VendorRequest]:
        return [r for r in self.requests if (r.method, r.path) == (method, path)]


def _account(currency: str, available: str, hold: str = "0") -> dict[str, Any]:
    return {
        "uuid": f"uuid-{currency}",
        "name": f"{currency} Wallet",
        "currency": currency,
        "available_balance": {"value": available, "currency": currency},
        "hold": {"value": hold, "currency": currency},
        "retail_portfolio_id": PORTFOLIO,
        "type": "ACCOUNT_TYPE_FIAT" if currency == "USD" else "ACCOUNT_TYPE_CRYPTO",
    }


def _order(cid: str, status: str, filled: str = "0") -> dict[str, Any]:
    return {
        "order_id": f"cb-{cid}",
        "client_order_id": cid,
        "product_id": "BTC-USD",
        "side": "BUY",
        "status": status,
        "filled_size": filled,
        "average_filled_price": "0",
        "total_fees": "0",
    }


def _transport(overrides: dict[tuple[str, str], Any] | None = None) -> FakeTransport:
    answers: dict[tuple[str, str], Any] = {
        ("GET", f"{BASE}/accounts"): {
            "accounts": [_account("USD", "1000.50"), _account("BTC", "0.5", "0.25")],
            "has_next": False,
            "cursor": "",
            "size": 2,
        },
        ("GET", f"{BASE}/orders/historical/batch"): {"orders": [], "has_next": False},
        ("POST", f"{BASE}/orders"): {
            "success": True,
            "success_response": {
                "order_id": "cb-cid-1",
                "product_id": "BTC-USD",
                "side": "BUY",
                "client_order_id": "cid-1",
            },
        },
        ("POST", f"{BASE}/orders/batch_cancel"): {
            "results": [{"success": True, "order_id": "cb-cid-1"}]
        },
    }
    answers.update(overrides or {})
    return FakeTransport(answers=answers)


def _adapter(transport: FakeTransport, sink: Sink | None = None, *, expected: str = PORTFOLIO):
    return CoinbaseSandboxBroker(
        audit=sink or Sink(),
        expected_account_id=expected,
        transport=transport,
        now=lambda: NOW,
    )


def _intent(cid: str = "cid-1", **changes: Any) -> OrderIntent:
    base: dict[str, Any] = {
        "client_order_id": cid,
        "intent_kind": IntentKind.OPEN,
        "side": OrderSide.BUY_TO_OPEN,
        "qty": 1,
        "limit_price": 50000.0,
        "shares_per_contract": 1,
        "adapter_name": "coinbase_sandbox",
        "created_at": NOW,
        "expires_at": NOW + timedelta(minutes=15),
        "cost_model": CostModelFeedback(modelled_fill_price=50000.0, modelled_spread_bps=5.0),
        "symbol": "BTC-USD",
    }
    base.update(changes)
    return OrderIntent(**base)


def test_allowlist_names_exactly_the_sandbox_host_and_no_credential_exists() -> None:
    assert PAPER_HOST_ALLOWLIST == ("api-sandbox.coinbase.com",)
    transport = _transport()
    adapter = _adapter(transport)
    adapter.is_paper()
    for request in transport.requests:
        names = {k.lower() for k, _ in request.headers}
        assert not names & {"authorization", "cb-access-key", "cb-access-sign"}


def test_is_paper_matches_portfolio_or_account_uuid_and_fails_otherwise() -> None:
    assert _adapter(_transport()).is_paper().proven is True
    by_uuid = _adapter(_transport(), expected="uuid-BTC").is_paper()
    assert by_uuid.proven is True
    assert by_uuid.observed_account_id == "uuid-BTC"
    mismatch = _adapter(_transport(), expected="someone-else").is_paper()
    assert mismatch.proven is False
    assert "does not match" in mismatch.failure_reason
    off = _transport()
    off.host = "not-the-sandbox.invalid"
    bad_host = _adapter(off).is_paper()
    assert bad_host.proven is False
    assert "allowlist" in bad_host.failure_reason
    empty = _adapter(_transport({("GET", f"{BASE}/accounts"): {"accounts": []}})).is_paper()
    assert empty.proven is False


def test_account_is_quote_cash_only_and_positions_are_unmarked() -> None:
    adapter = _adapter(_transport())
    account = adapter.account()
    assert account.cash == 1000.5
    assert account.equity == 1000.5  # crypto NOT marked into equity
    (snapshot,) = adapter.positions()
    (leg,) = snapshot.legs
    assert leg.instrument_key == "BTC-USD"
    assert leg.signed_qty == 0.75  # available + hold
    assert snapshot.market_value == 0.0
    assert adapter.clock().is_open is True


def test_place_submits_a_gtd_limit_order_once_and_is_idempotent() -> None:
    transport = _transport()
    adapter = _adapter(transport)
    adapter.is_paper()
    result = adapter.place(_intent())
    assert result.state is OrderState.SUBMITTING
    assert result.broker_order_id == "cb-cid-1"
    (sent,) = transport.sent("POST", f"{BASE}/orders")
    assert json.loads(sent.body or "") == {
        "client_order_id": "cid-1",
        "product_id": "BTC-USD",
        "side": "BUY",
        "order_configuration": {
            "limit_limit_gtd": {
                "base_size": "1",
                "limit_price": "50000.00",
                "end_time": "2026-11-02T15:15:00Z",
                "post_only": False,
            }
        },
    }
    transport.answers[("GET", f"{BASE}/orders/historical/batch")] = {
        "orders": [_order("cid-1", "OPEN")]
    }
    again = adapter.place(_intent())
    assert again.state is OrderState.SUBMITTING
    assert len(transport.sent("POST", f"{BASE}/orders")) == 1


def test_duplicate_client_order_id_is_resolved_not_retried() -> None:
    transport = _transport(
        {
            ("POST", f"{BASE}/orders"): {
                "success": False,
                "error_response": {
                    "error": "DUPLICATE_CLIENT_ORDER_ID",
                    "message": "dup",
                    "new_order_failure_reason": "DUPLICATE_CLIENT_ORDER_ID",
                },
            }
        }
    )
    adapter = _adapter(transport)
    adapter.is_paper()
    # The lookup finds nothing, so we submit; the broker says duplicate; the
    # resolving lookup still finds nothing -> UNKNOWN, never a second submit.
    result_first = adapter.place(_intent())
    assert result_first.state is OrderState.UNKNOWN
    transport.answers[("GET", f"{BASE}/orders/historical/batch")] = {
        "orders": [_order("cid-1", "FILLED", "1")]
    }
    assert adapter.place(_intent()).state is OrderState.FILLED
    assert len(transport.sent("POST", f"{BASE}/orders")) == 1


def test_rejections_unknowns_and_refusals() -> None:
    t = _transport(
        {
            ("POST", f"{BASE}/orders"): {
                "success": False,
                "error_response": {"new_order_failure_reason": "INSUFFICIENT_FUND"},
            }
        }
    )
    a = _adapter(t)
    a.is_paper()
    rejected = a.place(_intent())
    assert rejected.state is OrderState.REJECTED
    assert "INSUFFICIENT_FUND" in rejected.error_verbatim

    t2 = _transport()
    t2.raise_on.add(("POST", f"{BASE}/orders"))
    a2 = _adapter(t2)
    a2.is_paper()
    assert a2.place(_intent()).state is OrderState.UNKNOWN

    t3 = _transport({("POST", f"{BASE}/orders"): (500, {"error": "boom"})})
    a3 = _adapter(t3)
    a3.is_paper()
    assert a3.place(_intent()).state is OrderState.UNKNOWN

    a4 = _adapter(_transport())
    assert a4.place(_intent()).state is OrderState.REJECTED  # no proof taken
    a4.is_paper()
    assert a4.place(_intent(symbol="SPY")).state is OrderState.REFUSED
    assert a4.place(_intent(side=OrderSide.SELL_TO_OPEN)).state is OrderState.REFUSED
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
        adapter_name="coinbase_sandbox",
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
        cost_model=CostModelFeedback(modelled_fill_price=1.0, modelled_spread_bps=5.0),
    )
    assert a4.place_combo(combo).state is OrderState.REFUSED


def test_order_status_filters_locally_and_resolves_terminal_states() -> None:
    transport = _transport(
        {
            ("GET", f"{BASE}/orders/historical/batch"): {
                "orders": [_order("other", "OPEN"), _order("cid-7", "EXPIRED", "0.4")]
            }
        }
    )
    adapter = _adapter(transport)
    status = adapter.order_status("cid-7")
    assert status is not None
    assert status.state is OrderState.PARTIAL  # expired after a partial fill
    assert status.filled_qty == 0.4
    assert adapter.order_status("nope") is None
    weird = _transport(
        {("GET", f"{BASE}/orders/historical/batch"): {"orders": [_order("cid-8", "NEW_THING")]}}
    )
    s = _adapter(weird).order_status("cid-8")
    assert s is not None and s.state is OrderState.UNKNOWN


def test_cancel_uses_the_learned_order_id_and_reports_the_state_after() -> None:
    transport = _transport()
    adapter = _adapter(transport)
    adapter.is_paper()
    adapter.place(_intent())
    transport.answers[("GET", f"{BASE}/orders/historical/batch")] = {
        "orders": [_order("cid-1", "CANCELLED")]
    }
    result = adapter.cancel("cid-1")
    assert result.state is OrderState.CANCELLED
    (sent,) = transport.sent("POST", f"{BASE}/orders/batch_cancel")
    assert json.loads(sent.body or "") == {"order_ids": ["cb-cid-1"]}
    unknown = _adapter(_transport()).cancel("never-seen")
    assert unknown.state is OrderState.UNKNOWN


def test_unparseable_reads_raise() -> None:
    with pytest.raises(Exception, match="accounts list"):
        _adapter(_transport({("GET", f"{BASE}/accounts"): {"nope": 1}})).account()
    with pytest.raises(ValueError, match="expected_account_id"):
        _adapter(_transport(), expected="")
