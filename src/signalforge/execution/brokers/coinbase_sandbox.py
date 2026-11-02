"""Coinbase Advanced Trade **sandbox** adapter — spot pairs, limit orders.

Boundary, stated first (D6 §0, §13, ADR pointer "Increment W5"):

* The only host this adapter will accept a response from is Coinbase's
  Advanced Trade sandbox, ``api-sandbox.coinbase.com``, named once in
  :data:`PAPER_HOST_ALLOWLIST`. The production API host appears nowhere in
  this file, and the sandbox is **unauthenticated by Coinbase's design** —
  so this adapter holds no credential at all. There is no key to leak.
* The sandbox answers with static, canned bodies in the production format.
  That makes it a wire-format and state-machine rehearsal, not a market: no
  fill here is evidence of anything, exactly as ``paper_reference``'s are not.
* One spot product per order (``BASE-QUOTE``, quote ``USD``), ``LIMIT``,
  good-till-date at the intent's ``expires_at`` (the closest native match to
  the OMS's DAY-and-expire semantics), no short opening, and ``place_combo``
  is **refused** (A2: no leg-by-leg fallback exists).
* ``clock()`` reports the venue open, because spot crypto has no session. The
  cycle cross-checks that against the **local equity calendar** and blocks on
  disagreement (§11), so through this adapter opening is possible only while
  the local calendar also says open. That is deliberately conservative.

Eligibility:

* A1 — ``place`` looks the ``client_order_id`` up first, and Coinbase's own
  ``DUPLICATE_CLIENT_ORDER_ID`` rejection is resolved by a lookup, not a retry.
* A2 — satisfied by refusal.
* A3 — ``is_paper()`` reads the portfolio/account ids out of the accounts body
  and the host out of the transport's report, every call.
* A4 — ``order_status`` reads the historical orders list, which carries
  filled, cancelled, expired and failed orders, not only open ones.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from signalforge.execution.brokers.vendor_base import (
    Transport,
    VendorAdapterError,
    VendorRequest,
    VendorResponse,
    excerpt,
    parse_json,
    strict_number,
)
from signalforge.execution.events import ExecutionEventType
from signalforge.execution.intents import (
    AccountSnapshot,
    ComboOrderIntent,
    MarketClock,
    OrderIntent,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionLeg,
    PositionSnapshot,
    StructureType,
    TimeInForce,
)
from signalforge.execution.protocol import IsPaperProof
from signalforge.execution.states import OrderState

__all__ = [
    "COINBASE_SANDBOX_HOST",
    "COINBASE_SANDBOX_NAME",
    "PAPER_HOST_ALLOWLIST",
    "CoinbaseSandboxBroker",
]

COINBASE_SANDBOX_NAME = "coinbase_sandbox"

#: §13 rule 5 — the literal, reviewed paper-host allowlist. ONE host, the
#: sandbox. The production host appears nowhere in this file.
COINBASE_SANDBOX_HOST = "api-sandbox.coinbase.com"
PAPER_HOST_ALLOWLIST: tuple[str, ...] = (COINBASE_SANDBOX_HOST,)

_BASE = "/api/v3/brokerage"
_QUOTE = "USD"
_PRODUCT_RE = re.compile(r"^[A-Z0-9]{2,10}-USD$")

_WORKING = ("OPEN", "PENDING", "QUEUED", "CANCEL_QUEUED", "EDIT_QUEUED")
_STATUS_MAP: dict[str, OrderState] = {
    **dict.fromkeys(_WORKING, OrderState.SUBMITTING),
    "FILLED": OrderState.FILLED,
    "CANCELLED": OrderState.CANCELLED,
    "EXPIRED": OrderState.EXPIRED,
    "FAILED": OrderState.REJECTED,
}


class AdapterAudit:  # pragma: no cover - typing surface only
    def record(self, event_type: ExecutionEventType, /, **fields: Any) -> None: ...


class CoinbaseSandboxBroker:
    """A :class:`~signalforge.execution.protocol.BrokerAdapter` for Coinbase's
    Advanced Trade sandbox. Constructed only through ``brokers.build_adapter``."""

    name = COINBASE_SANDBOX_NAME
    instances_created = 0

    def __init__(
        self,
        *,
        audit: AdapterAudit,
        expected_account_id: str,
        transport: Transport,
        now: Callable[[], datetime],
        timeout_s: float = 15.0,
    ) -> None:
        if not expected_account_id:
            raise ValueError(
                "expected_account_id is required: it is the operator-typed value from the "
                "armed record (D6 §13 step 2), and a proof with nothing to match is not a proof"
            )
        self._audit = audit
        self._expected_account_id = expected_account_id
        self._transport = transport
        self._now = now
        self._timeout_s = timeout_s
        self._last_proof: IsPaperProof | None = None
        #: client_order_id -> order_id, learned from this process's own
        #: acceptances. A miss falls through to the broker's order list, so a
        #: restart loses nothing but a shortcut.
        self._order_ids: dict[str, str] = {}
        type(self).instances_created += 1

    # -- plumbing -----------------------------------------------------------

    def _record(self, event_type: ExecutionEventType, **fields: Any) -> None:
        fields["adapter_name"] = self.name
        self._audit.record(event_type, **fields)

    def _call(
        self,
        method: str,
        path: str,
        *,
        query: tuple[tuple[str, str], ...] = (),
        body: dict[str, Any] | None = None,
    ) -> VendorResponse:
        headers: tuple[tuple[str, str], ...] = (("Accept", "application/json"),)
        if body is not None:
            headers += (("Content-Type", "application/json"),)
        request = VendorRequest(
            method=method,
            host=COINBASE_SANDBOX_HOST,
            path=_BASE + path,
            query=query,
            headers=headers,
            body=json.dumps(body, separators=(",", ":")) if body is not None else None,
            timeout_s=self._timeout_s,
        )
        return self._transport(request)

    def _json(self, response: VendorResponse, *, what: str) -> Any:
        if response.host not in PAPER_HOST_ALLOWLIST:
            raise VendorAdapterError(
                f"{what}: response came from {response.host!r}, not the sandbox allowlist"
            )
        if response.status != 200:
            raise VendorAdapterError(f"{what}: HTTP {response.status}: {excerpt(response.body)}")
        return parse_json(response.body)

    def _accounts(self) -> list[dict[str, Any]]:
        response = self._call("GET", "/accounts", query=(("limit", "250"),))
        data = self._json(response, what="accounts")
        rows = data.get("accounts") if isinstance(data, dict) else None
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise VendorAdapterError("accounts body carries no accounts list")
        return rows

    # -- §13: the is_paper proof -------------------------------------------

    def is_paper(self) -> IsPaperProof:
        checked_at = self._now()
        observed = ""
        host = ""
        raw = ""
        reasons: list[str] = []
        try:
            response = self._call("GET", "/accounts", query=(("limit", "250"),))
            host = response.host
            raw = excerpt(response.body)
            if host not in PAPER_HOST_ALLOWLIST:
                reasons.append(
                    f"observed host {host!r} is not in the reviewed paper-host allowlist"
                )
            if response.status != 200:
                reasons.append(f"accounts returned HTTP {response.status}")
            else:
                data = parse_json(response.body)
                ids = _identifiers(data)
                if not ids:
                    reasons.append("the broker response body carried no account identifier")
                elif self._expected_account_id in ids:
                    observed = self._expected_account_id
                else:
                    observed = ids[0]
                    reasons.append(
                        f"observed account id {observed!r} does not match the armed record's "
                        f"expected {self._expected_account_id!r}"
                    )
        except VendorAdapterError as exc:
            reasons.append(f"unparseable accounts body: {exc}")
        except Exception as exc:
            reasons.append(f"accounts unreachable: {type(exc).__name__}")
        proven = not reasons
        proof = IsPaperProof(
            proven=proven,
            observed_account_id=observed,
            observed_host=host,
            expected_account_id=self._expected_account_id,
            checked_at=checked_at,
            raw_excerpt=raw,
            failure_reason="; ".join(reasons),
        )
        self._last_proof = proof
        self._record(
            ExecutionEventType.IS_PAPER_PROOF,
            reason=(
                "is_paper proven"
                if proven
                else "is_paper FAILED — a mismatch blocks arming and every submission: "
                f"{proof.failure_reason}"
            ),
            payload={
                "proven": proven,
                "observed_account_id": observed,
                "observed_host": host,
                "expected_account_id": self._expected_account_id,
                "raw_excerpt": raw,
            },
        )
        return proof

    # -- read-only views ----------------------------------------------------

    def account(self) -> AccountSnapshot:
        """Cash is the quote-currency balance. **Equity equals cash**: crypto
        holdings are not marked here because this adapter has no price source,
        and an unmarked holding must not inflate the equity the limits read."""
        cash = 0.0
        for row in self._accounts():
            if row.get("currency") == _QUOTE:
                cash += _amount(row.get("available_balance"), what="available USD")
        snapshot = AccountSnapshot(
            account_id=self._expected_account_id,
            equity=cash,
            buying_power=cash,
            cash=cash,
            as_of=self._now(),
        )
        self._record(ExecutionEventType.ADAPTER_CALL, reason="account()", payload={"cash": cash})
        return snapshot

    def positions(self) -> Sequence[PositionSnapshot]:
        legs: list[PositionLeg] = []
        for row in self._accounts():
            currency = row.get("currency")
            if not isinstance(currency, str) or currency == _QUOTE:
                continue
            total = _amount(row.get("available_balance"), what=f"{currency} available") + _amount(
                row.get("hold"), what=f"{currency} hold"
            )
            if total == 0:
                continue
            legs.append(PositionLeg(instrument_key=f"{currency}-{_QUOTE}", signed_qty=total))
        snapshots: tuple[PositionSnapshot, ...] = ()
        if legs:
            snapshots = (
                PositionSnapshot(
                    adapter_name=self.name,
                    legs=tuple(sorted(legs, key=lambda leg: leg.instrument_key)),
                    market_value=0.0,  # unmarked on purpose — see account()
                    as_of=self._now(),
                ),
            )
        self._record(
            ExecutionEventType.ADAPTER_CALL,
            reason="positions()",
            payload={
                "leg_count": len(legs),
                "legs": {leg.instrument_key: leg.signed_qty for leg in legs},
            },
        )
        return snapshots

    def _orders(self, query: tuple[tuple[str, str], ...] = ()) -> list[dict[str, Any]]:
        response = self._call("GET", "/orders/historical/batch", query=(("limit", "250"), *query))
        data = self._json(response, what="orders")
        rows = data.get("orders") if isinstance(data, dict) else None
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise VendorAdapterError("orders body carries no orders list")
        return rows

    def open_orders(self) -> Sequence[OrderStatus]:
        statuses = tuple(
            status
            for status in (
                _order_status_from(row) for row in self._orders((("order_status", "OPEN"),))
            )
            if status.state is OrderState.SUBMITTING
        )
        self._record(
            ExecutionEventType.ADAPTER_CALL,
            reason="open_orders()",
            payload={"working": [s.client_order_id for s in statuses]},
        )
        return statuses

    def order_status(self, client_order_id: str) -> OrderStatus | None:
        """A4 — filtered **locally** on ``client_order_id`` over the historical
        list, so no reliance on a server-side filter the sandbox may ignore."""
        rows = [r for r in self._orders() if r.get("client_order_id") == client_order_id]
        if not rows:
            self._record(
                ExecutionEventType.ADAPTER_CALL,
                reason="order_status()",
                payload={"client_order_id": client_order_id, "found": False},
            )
            return None
        status = _order_status_from(rows[0])
        if status.broker_order_id:
            self._order_ids[client_order_id] = status.broker_order_id
        self._record(
            ExecutionEventType.ADAPTER_CALL,
            reason="order_status()",
            payload={
                "client_order_id": client_order_id,
                "found": True,
                "state": status.state.value,
                "raw_status": status.raw_status_verbatim,
            },
        )
        return status

    def clock(self) -> MarketClock:
        """Spot crypto has no session: the venue is open. The cycle's local
        calendar cross-check (§11) is what gates opening through this adapter."""
        now = self._now()
        self._record(ExecutionEventType.ADAPTER_CALL, reason="clock()", payload={"is_open": True})
        return MarketClock(is_open=True, as_of=now)

    # -- submission ---------------------------------------------------------

    def _refuse(self, intent: OrderIntent | ComboOrderIntent, reason: str) -> OrderResult:
        self._record(
            ExecutionEventType.INTENT_REFUSED,
            client_order_id=intent.client_order_id,
            intent_kind=intent.intent_kind.value,
            reason=reason,
        )
        return OrderResult(
            client_order_id=intent.client_order_id,
            state=OrderState.REFUSED,
            error_verbatim=reason,
        )

    def place(self, intent: OrderIntent) -> OrderResult:
        if self._last_proof is None or not self._last_proof.proven:
            return OrderResult(
                client_order_id=intent.client_order_id,
                state=OrderState.REJECTED,
                error_verbatim="is_paper proof failed or was never taken; nothing is submitted",
            )
        if intent.structure_type is not StructureType.EQUITY or intent.option_ticker:
            return self._refuse(intent, "coinbase_sandbox submits single spot products only")
        if intent.order_type is not OrderType.LIMIT or intent.time_in_force is not TimeInForce.DAY:
            return self._refuse(intent, "coinbase_sandbox submits LIMIT/DAY orders only")
        if intent.side is OrderSide.SELL_TO_OPEN:
            return self._refuse(intent, "short opening is not permitted through coinbase_sandbox")
        if not intent.symbol or not _PRODUCT_RE.match(intent.symbol):
            return self._refuse(intent, "symbol must be a BASE-USD spot product id")
        if intent.qty <= 0 or intent.limit_price <= 0:
            return self._refuse(intent, "an order needs a positive qty and limit price")

        try:
            existing = self.order_status(intent.client_order_id)
        except Exception as exc:
            return OrderResult(
                client_order_id=intent.client_order_id,
                state=OrderState.UNKNOWN,
                error_verbatim=f"pre-submission lookup failed: {type(exc).__name__}",
            )
        if existing is not None:
            return OrderResult(
                client_order_id=intent.client_order_id,
                state=existing.state,
                broker_order_id=existing.broker_order_id,
                raw_status_verbatim=existing.raw_status_verbatim,
            )

        side = "BUY" if intent.side.sign > 0 else "SELL"
        end_time = intent.expires_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        body = {
            "client_order_id": intent.client_order_id,
            "product_id": intent.symbol,
            "side": side,
            "order_configuration": {
                "limit_limit_gtd": {
                    "base_size": str(intent.qty),
                    "limit_price": f"{intent.limit_price:.2f}",
                    "end_time": end_time,
                    "post_only": False,
                }
            },
        }
        self._record(
            ExecutionEventType.SUBMITTING,
            client_order_id=intent.client_order_id,
            intent_kind=intent.intent_kind.value,
            reason="place()",
            payload={"product_id": intent.symbol, "side": side, "qty": intent.qty},
        )
        try:
            response = self._call("POST", "/orders", body=body)
        except Exception as exc:
            return OrderResult(
                client_order_id=intent.client_order_id,
                state=OrderState.UNKNOWN,
                submitted_at=self._now(),
                error_verbatim=f"submission transport failure: {type(exc).__name__}",
            )
        submitted_at = self._now()
        if response.host not in PAPER_HOST_ALLOWLIST:
            return OrderResult(
                client_order_id=intent.client_order_id,
                state=OrderState.UNKNOWN,
                submitted_at=submitted_at,
                error_verbatim=f"submission answered from {response.host!r}, outside the allowlist",
            )
        if response.status != 200:
            state = OrderState.REJECTED if 400 <= response.status < 500 else OrderState.UNKNOWN
            if state is OrderState.REJECTED:
                self._record(
                    ExecutionEventType.REJECTION,
                    client_order_id=intent.client_order_id,
                    reason=f"HTTP {response.status}",
                    payload={"raw_excerpt": excerpt(response.body)},
                )
            return OrderResult(
                client_order_id=intent.client_order_id,
                state=state,
                submitted_at=submitted_at,
                error_verbatim=f"HTTP {response.status}: {excerpt(response.body)}",
            )
        try:
            data = parse_json(response.body)
        except VendorAdapterError as exc:
            return OrderResult(
                client_order_id=intent.client_order_id,
                state=OrderState.UNKNOWN,
                submitted_at=submitted_at,
                error_verbatim=str(exc),
            )
        if not isinstance(data, dict):
            return OrderResult(
                client_order_id=intent.client_order_id,
                state=OrderState.UNKNOWN,
                submitted_at=submitted_at,
                error_verbatim="broker acceptance is not an object",
            )
        if data.get("success") is True:
            ok = data.get("success_response")
            order_id = ok.get("order_id") if isinstance(ok, dict) else None
            echoed = ok.get("client_order_id") if isinstance(ok, dict) else None
            if not isinstance(order_id, str) or not order_id or echoed != intent.client_order_id:
                return OrderResult(
                    client_order_id=intent.client_order_id,
                    state=OrderState.UNKNOWN,
                    submitted_at=submitted_at,
                    error_verbatim="success_response did not echo client_order_id with an order_id",
                )
            self._order_ids[intent.client_order_id] = order_id
            return OrderResult(
                client_order_id=intent.client_order_id,
                state=OrderState.SUBMITTING,
                broker_order_id=order_id,
                submitted_at=submitted_at,
                raw_status_verbatim=excerpt(response.body),
            )
        error = data.get("error_response")
        reason = ""
        if isinstance(error, dict):
            reason = str(error.get("new_order_failure_reason") or error.get("error") or "")
        if reason == "DUPLICATE_CLIENT_ORDER_ID":
            # A1 — the first attempt landed. Resolve it rather than retry it.
            status = self.order_status(intent.client_order_id)
            if status is not None:
                return OrderResult(
                    client_order_id=intent.client_order_id,
                    state=status.state,
                    broker_order_id=status.broker_order_id,
                    submitted_at=submitted_at,
                    raw_status_verbatim=status.raw_status_verbatim,
                )
            return OrderResult(
                client_order_id=intent.client_order_id,
                state=OrderState.UNKNOWN,
                submitted_at=submitted_at,
                error_verbatim="duplicate client_order_id reported but the order was not found",
            )
        self._record(
            ExecutionEventType.REJECTION,
            client_order_id=intent.client_order_id,
            reason=reason or "rejected without a reason",
            payload={"raw_excerpt": excerpt(response.body)},
        )
        return OrderResult(
            client_order_id=intent.client_order_id,
            state=OrderState.REJECTED,
            submitted_at=submitted_at,
            error_verbatim=f"{reason or 'rejected'}: {excerpt(response.body)}",
        )

    def place_combo(self, intent: ComboOrderIntent) -> OrderResult:
        return self._refuse(
            intent,
            "coinbase_sandbox submits no multi-leg structure; there is no leg-by-leg fallback",
        )

    def cancel(self, client_order_id: str) -> OrderResult:
        order_id = self._order_ids.get(client_order_id)
        if order_id is None:
            status = self.order_status(client_order_id)
            order_id = status.broker_order_id if status is not None else ""
        if not order_id:
            return OrderResult(
                client_order_id=client_order_id,
                state=OrderState.UNKNOWN,
                error_verbatim="no broker order_id is known for this client_order_id",
            )
        try:
            response = self._call("POST", "/orders/batch_cancel", body={"order_ids": [order_id]})
        except Exception as exc:
            return OrderResult(
                client_order_id=client_order_id,
                state=OrderState.UNKNOWN,
                broker_order_id=order_id,
                error_verbatim=f"cancel transport failure: {type(exc).__name__}",
            )
        if response.host not in PAPER_HOST_ALLOWLIST:
            return OrderResult(
                client_order_id=client_order_id,
                state=OrderState.UNKNOWN,
                broker_order_id=order_id,
                error_verbatim=f"cancel answered from {response.host!r}, outside the allowlist",
            )
        self._record(
            ExecutionEventType.CANCELLATION,
            client_order_id=client_order_id,
            reason=f"cancel() HTTP {response.status}",
            payload={"raw_excerpt": excerpt(response.body)},
        )
        status = self.order_status(client_order_id)
        if status is None:
            return OrderResult(
                client_order_id=client_order_id,
                state=OrderState.UNKNOWN,
                broker_order_id=order_id,
                error_verbatim="order not found after cancel request",
            )
        return OrderResult(
            client_order_id=client_order_id,
            state=status.state,
            broker_order_id=status.broker_order_id or order_id,
            raw_status_verbatim=status.raw_status_verbatim,
        )

    def cancel_all(self) -> Sequence[OrderResult]:
        working = sorted(self.open_orders(), key=lambda s: s.client_order_id)
        return tuple(self.cancel(status.client_order_id) for status in working)


# ---------------------------------------------------------------------------
# Body readers
# ---------------------------------------------------------------------------


def _identifiers(data: Any) -> list[str]:
    """Portfolio ids first (what an operator types), then account uuids."""
    rows = data.get("accounts") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    portfolios: list[str] = []
    uuids: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        portfolio = row.get("retail_portfolio_id")
        if isinstance(portfolio, str) and portfolio and portfolio not in portfolios:
            portfolios.append(portfolio)
        account = row.get("uuid")
        if isinstance(account, str) and account and account not in uuids:
            uuids.append(account)
    return portfolios + uuids


def _amount(value: object, *, what: str) -> float:
    if not isinstance(value, dict):
        raise VendorAdapterError(f"{what} is not an amount object")
    return strict_number(value.get("value"), what=what)


def _order_status_from(row: dict[str, Any]) -> OrderStatus:
    client_order_id = row.get("client_order_id")
    if not isinstance(client_order_id, str) or not client_order_id:
        raise VendorAdapterError("order row carries no client_order_id")
    raw_status = str(row.get("status", ""))
    state = _STATUS_MAP.get(raw_status.upper(), OrderState.UNKNOWN)
    filled = row.get("filled_size")
    filled_qty = strict_number(filled, what="filled size") if filled not in (None, "") else 0.0
    if state in (OrderState.CANCELLED, OrderState.EXPIRED) and filled_qty > 0:
        state = OrderState.PARTIAL
    order_id = row.get("order_id")
    return OrderStatus(
        client_order_id=client_order_id,
        state=state,
        broker_order_id=order_id if isinstance(order_id, str) else "",
        filled_qty=filled_qty,
        raw_status_verbatim=raw_status,
        legs_filled_ratio=(),
    )
