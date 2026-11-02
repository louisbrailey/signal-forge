"""Webull OpenAPI **sandbox** adapter — US equities, limit orders, DAY only.

Boundary, stated first (D6 §0, §13, ADR pointer "Increment W5"):

* The only host this adapter will accept a response from is the Webull
  **test environment**, ``api.sandbox.webull.com``, named once in
  :data:`PAPER_HOST_ALLOWLIST`. The production host appears nowhere in this
  file. A transport that reached anything else fails the §13 proof and every
  subsequent submission is refused.
* No vendor SDK (D6-A). The request signing below re-implements the documented
  scheme — HMAC-SHA256 over a sorted ``name=value`` string with the compact
  JSON body's uppercase SHA-256 appended, Base64 output, the App Secret
  suffixed with ``&`` as the key — from Webull's own signature reference.
* Credentials arrive as ``SecretStr`` resolved by NAME in the CLI (§16). This
  module never reads an environment variable, never logs a header, and the
  App Secret never becomes a header at all.
* Equities only, one instrument per order, ``LIMIT``/``DAY``, no short
  opening. ``place_combo`` is **refused**: there is no leg-by-leg fallback
  (A2), so a multi-leg structure simply cannot be opened through this adapter.

Eligibility (``protocol.ADAPTER_ELIGIBILITY_CONDITIONS``):

* A1 — ``place`` looks the ``client_order_id`` up at the broker *before*
  submitting; a retry after a timeout finds the first attempt and returns it.
* A2 — satisfied by refusal, never by looping over legs.
* A3 — ``is_paper()`` reads the account id out of the account-list body and
  the host out of the transport's report of the connection, every call.
* A4 — ``order_status`` uses the order-detail endpoint, which resolves filled,
  cancelled and rejected orders, not only open ones.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import SecretStr

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
    "PAPER_HOST_ALLOWLIST",
    "WEBULL_SANDBOX_HOST",
    "WEBULL_SANDBOX_NAME",
    "WebullSandboxBroker",
    "sign_request",
]

WEBULL_SANDBOX_NAME = "webull_sandbox"

#: §13 rule 5 — the literal, reviewed paper-host allowlist. ONE host, the test
#: environment. There is deliberately no production host anywhere in this file.
WEBULL_SANDBOX_HOST = "api.sandbox.webull.com"
PAPER_HOST_ALLOWLIST: tuple[str, ...] = (WEBULL_SANDBOX_HOST,)

_API_VERSION = "v3"
_MARKET = "US"
_SESSION_TZ = ZoneInfo("America/New_York")
_CORE_OPEN = time(9, 30)
_CORE_CLOSE = time(16, 0)
_ISO_8601 = "%Y-%m-%dT%H:%M:%SZ"

# Broker status -> OMS state. Anything not listed is UNKNOWN, never a guess.
_WORKING = ("SUBMITTED", "PENDING", "NEW", "WORKING", "ACCEPTED", "QUEUED", "PENDING_CANCEL")
_STATUS_MAP: dict[str, OrderState] = {
    **dict.fromkeys(_WORKING, OrderState.SUBMITTING),
    "FILLED": OrderState.FILLED,
    "PARTIAL_FILLED": OrderState.PARTIAL,
    "PARTIALLY_FILLED": OrderState.PARTIAL,
    "CANCELLED": OrderState.CANCELLED,
    "CANCELED": OrderState.CANCELLED,
    "REJECTED": OrderState.REJECTED,
    "FAILED": OrderState.REJECTED,
    "EXPIRED": OrderState.EXPIRED,
}


class AdapterAudit:  # pragma: no cover - typing surface only
    def record(self, event_type: ExecutionEventType, /, **fields: Any) -> None: ...


# ---------------------------------------------------------------------------
# Signing — Webull's documented scheme, re-implemented without the SDK
# ---------------------------------------------------------------------------

_UNRESERVED = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~")


def _percent_encode(text: str) -> str:
    """``urllib.parse.quote(text, safe="")`` without importing ``urllib`` —
    the execution package's posture test bans that module wholesale, and the
    encoding is ten lines."""
    out: list[str] = []
    for byte in text.encode("utf-8"):
        out.append(chr(byte) if byte in _UNRESERVED else f"%{byte:02X}")
    return "".join(out)


def sign_request(
    *,
    method: str,
    host: str,
    path: str,
    query: tuple[tuple[str, str], ...],
    body: dict[str, Any] | None,
    app_key: str,
    app_secret: str,
    timestamp: str,
    nonce: str,
) -> tuple[tuple[str, str], ...]:
    """Return the full header tuple for one request, ``x-signature`` included.

    Pure: no clock, no randomness, no I/O — ``timestamp`` and ``nonce`` are
    inputs so a test can pin them and check the signature byte for byte.
    """
    sign_headers = {
        "x-app-key": app_key,
        "x-timestamp": timestamp,
        "x-signature-version": "1.0",
        "x-signature-algorithm": "HMAC-SHA256",
        "x-signature-nonce": nonce,
    }
    params: dict[str, str] = {k.lower(): v for k, v in sign_headers.items()}
    params["host"] = host
    for name, value in query:
        params[name] = f"{params[name]}&{value}" if name in params else value
    string_to_sign = path + "&" + "&".join(f"{k}={params[k]}" for k in sorted(params))
    body_text: str | None = None
    if body is not None:
        body_text = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        string_to_sign += "&" + hashlib.sha256(body_text.encode("utf-8")).hexdigest().upper()
    digest = hmac.new(
        (app_secret + "&").encode("utf-8"),
        _percent_encode(string_to_sign).encode("utf-8"),
        hashlib.sha256,
    ).digest()
    headers = dict(sign_headers)
    headers["x-signature"] = base64.b64encode(digest).decode("ascii")
    headers["x-version"] = _API_VERSION
    if method == "POST":
        headers["Content-Type"] = "application/json"
    return tuple(headers.items())


# ---------------------------------------------------------------------------
# The adapter
# ---------------------------------------------------------------------------


class WebullSandboxBroker:
    """A :class:`~signalforge.execution.protocol.BrokerAdapter` for the Webull
    test environment. Constructed only through ``brokers.build_adapter``."""

    name = WEBULL_SANDBOX_NAME
    instances_created = 0

    def __init__(
        self,
        *,
        audit: AdapterAudit,
        expected_account_id: str,
        transport: Transport,
        app_key: SecretStr,
        app_secret: SecretStr,
        now: Callable[[], datetime],
        nonce: Callable[[], str] | None = None,
        timeout_s: float = 15.0,
    ) -> None:
        if not expected_account_id:
            raise ValueError(
                "expected_account_id is required: it is the operator-typed value from the "
                "armed record (D6 §13 step 2), and a proof with nothing to match is not a proof"
            )
        if not app_key.get_secret_value() or not app_secret.get_secret_value():
            raise ValueError("app_key and app_secret must both be non-empty SecretStr values")
        self._audit = audit
        self._expected_account_id = expected_account_id
        self._transport = transport
        self._app_key = app_key
        self._app_secret = app_secret
        self._now = now
        self._nonce = nonce or (lambda: uuid.uuid4().hex)
        self._timeout_s = timeout_s
        self._last_proof: IsPaperProof | None = None
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
        extra_headers: tuple[tuple[str, str], ...] = (),
    ) -> VendorResponse:
        """Sign, send, and return the response. Raises on transport failure."""
        timestamp = self._now().astimezone(UTC).strftime(_ISO_8601)
        headers = sign_request(
            method=method,
            host=WEBULL_SANDBOX_HOST,
            path=path,
            query=query,
            body=body,
            app_key=self._app_key.get_secret_value(),
            app_secret=self._app_secret.get_secret_value(),
            timestamp=timestamp,
            nonce=self._nonce(),
        )
        request = VendorRequest(
            method=method,
            host=WEBULL_SANDBOX_HOST,
            path=path,
            query=query,
            headers=headers + extra_headers,
            body=(
                json.dumps(body, ensure_ascii=False, separators=(",", ":"))
                if body is not None
                else None
            ),
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

    @staticmethod
    def _account_query(account_id: str) -> tuple[tuple[str, str], ...]:
        return (("account_id", account_id),)

    # -- §13: the is_paper proof -------------------------------------------

    def is_paper(self) -> IsPaperProof:
        """Read the account id out of the broker's own account list and the
        host out of the transport's report. Re-taken every call, never cached
        for the decision — ``_last_proof`` only gates submissions."""
        checked_at = self._now()
        observed = ""
        host = ""
        raw = ""
        reasons: list[str] = []
        try:
            response = self._call("GET", "/trading/accounts/list")
            host = response.host
            raw = excerpt(response.body)
            if host not in PAPER_HOST_ALLOWLIST:
                reasons.append(
                    f"observed host {host!r} is not in the reviewed paper-host allowlist"
                )
            if response.status != 200:
                reasons.append(f"account list returned HTTP {response.status}")
            else:
                accounts = parse_json(response.body)
                ids = _account_ids(accounts)
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
            reasons.append(f"unparseable account list: {exc}")
        except Exception as exc:
            reasons.append(f"account list unreachable: {type(exc).__name__}")
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
        response = self._call(
            "GET",
            "/account/balance",
            query=(
                *self._account_query(self._expected_account_id),
                ("total_asset_currency", "USD"),
            ),
        )
        data = self._json(response, what="account balance")
        if not isinstance(data, dict):
            raise VendorAdapterError("account balance is not an object")
        equity = strict_number(data.get("total_net_liquidation_value"), what="net liquidation")
        cash = strict_number(data.get("total_cash_balance"), what="cash balance")
        snapshot = AccountSnapshot(
            account_id=self._expected_account_id,
            equity=equity,
            # A cash account's buying power is its cash. Nothing here infers
            # margin; the sandbox does not grant it and the limits read this.
            buying_power=cash,
            cash=cash,
            as_of=self._now(),
        )
        self._record(
            ExecutionEventType.ADAPTER_CALL,
            reason="account()",
            payload={"equity": equity, "cash": cash},
        )
        return snapshot

    def positions(self) -> Sequence[PositionSnapshot]:
        response = self._call(
            "GET",
            "/account/positions",
            query=(*self._account_query(self._expected_account_id), ("page_size", "100")),
        )
        data = self._json(response, what="positions")
        rows = data.get("holdings", data.get("positions", data)) if isinstance(data, dict) else data
        if not isinstance(rows, list):
            raise VendorAdapterError("positions is not a list")
        legs: list[PositionLeg] = []
        market_value = 0.0
        for row in rows:
            if not isinstance(row, dict):
                raise VendorAdapterError("position row is not an object")
            symbol = row.get("symbol")
            if not isinstance(symbol, str) or not symbol:
                raise VendorAdapterError("position row carries no symbol")
            qty = strict_number(row.get("quantity"), what=f"{symbol} quantity")
            if qty == 0:
                continue
            legs.append(PositionLeg(instrument_key=symbol, signed_qty=qty))
            if row.get("market_value") is not None:
                market_value += strict_number(row.get("market_value"), what=f"{symbol} value")
        snapshots: tuple[PositionSnapshot, ...] = ()
        if legs:
            snapshots = (
                PositionSnapshot(
                    adapter_name=self.name,
                    legs=tuple(sorted(legs, key=lambda leg: leg.instrument_key)),
                    market_value=market_value,
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

    def open_orders(self) -> Sequence[OrderStatus]:
        response = self._call(
            "GET",
            "/trading/orders/open-orders/list",
            query=self._account_query(self._expected_account_id),
        )
        data = self._json(response, what="open orders")
        statuses = tuple(
            status
            for status in (_order_status_from(row) for row in _order_rows(data))
            if status.state is OrderState.SUBMITTING
        )
        self._record(
            ExecutionEventType.ADAPTER_CALL,
            reason="open_orders()",
            payload={"working": [s.client_order_id for s in statuses]},
        )
        return statuses

    def order_status(self, client_order_id: str) -> OrderStatus | None:
        """A4 — the order-detail endpoint resolves terminal orders too."""
        response = self._call(
            "GET",
            "/trading/orders/get",
            query=(
                *self._account_query(self._expected_account_id),
                ("client_order_id", client_order_id),
            ),
        )
        if response.host not in PAPER_HOST_ALLOWLIST:
            raise VendorAdapterError("order detail came from a host outside the sandbox allowlist")
        if response.status == 404:
            self._record(
                ExecutionEventType.ADAPTER_CALL,
                reason="order_status()",
                payload={"client_order_id": client_order_id, "found": False},
            )
            return None
        data = self._json(response, what="order detail")
        rows = [row for row in _order_rows(data) if row.get("client_order_id") == client_order_id]
        if not rows:
            self._record(
                ExecutionEventType.ADAPTER_CALL,
                reason="order_status()",
                payload={"client_order_id": client_order_id, "found": False},
            )
            return None
        status = _order_status_from(rows[0])
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
        """The broker's calendar for today, combined with the core session
        hours in New York. Cross-checked against the local calendar by the
        cycle (§11); disagreement blocks."""
        now = self._now()
        local = now.astimezone(_SESSION_TZ)
        today = local.date().isoformat()
        response = self._call(
            "GET",
            "/trade/calendar",
            query=(("market", _MARKET), ("start", today), ("end", today)),
        )
        data = self._json(response, what="trade calendar")
        days = data.get("trade_days", data) if isinstance(data, dict) else data
        if not isinstance(days, list):
            raise VendorAdapterError("trade calendar is not a list")
        trade_days = {row.get("trade_day") for row in days if isinstance(row, dict)}
        is_trading_day = today in trade_days
        in_session = _CORE_OPEN <= local.time() < _CORE_CLOSE
        clock = MarketClock(is_open=is_trading_day and in_session, as_of=now)
        self._record(
            ExecutionEventType.ADAPTER_CALL,
            reason="clock()",
            payload={"trade_day": is_trading_day, "in_core_session": in_session},
        )
        return clock

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
        """A single US equity, LIMIT, DAY. Idempotent on ``client_order_id``."""
        if self._last_proof is None or not self._last_proof.proven:
            return OrderResult(
                client_order_id=intent.client_order_id,
                state=OrderState.REJECTED,
                error_verbatim="is_paper proof failed or was never taken; nothing is submitted",
            )
        if intent.structure_type is not StructureType.EQUITY or intent.option_ticker:
            return self._refuse(intent, "webull_sandbox submits US equities only")
        if intent.order_type is not OrderType.LIMIT or intent.time_in_force is not TimeInForce.DAY:
            return self._refuse(intent, "webull_sandbox submits LIMIT/DAY orders only")
        if intent.side is OrderSide.SELL_TO_OPEN:
            return self._refuse(intent, "short opening is not permitted through webull_sandbox")
        if not intent.symbol or intent.qty <= 0 or intent.limit_price <= 0:
            return self._refuse(intent, "an equity order needs a symbol, a positive qty and price")

        # A1 — look before you submit. A retry after a timeout finds the first
        # attempt here and never submits twice.
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
        body = {
            "account_id": self._expected_account_id,
            "new_orders": [
                {
                    "client_order_id": intent.client_order_id,
                    "combo_type": "NORMAL",
                    "symbol": intent.symbol,
                    "instrument_type": "EQUITY",
                    "market": _MARKET,
                    "order_type": "LIMIT",
                    "limit_price": f"{intent.limit_price:.4f}".rstrip("0").rstrip("."),
                    "quantity": str(intent.qty),
                    "side": side,
                    "time_in_force": "DAY",
                    "support_trading_session": "CORE",
                    "entrust_type": "QTY",
                }
            ],
        }
        self._record(
            ExecutionEventType.SUBMITTING,
            client_order_id=intent.client_order_id,
            intent_kind=intent.intent_kind.value,
            reason="place()",
            payload={"symbol": intent.symbol, "side": side, "qty": intent.qty},
        )
        try:
            response = self._call(
                "POST",
                "/trading/orders/place",
                body=body,
                extra_headers=(("category", f"{_MARKET}_EQUITY"),),
            )
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
        if 400 <= response.status < 500:
            self._record(
                ExecutionEventType.REJECTION,
                client_order_id=intent.client_order_id,
                reason=f"HTTP {response.status}",
                payload={"raw_excerpt": excerpt(response.body)},
            )
            return OrderResult(
                client_order_id=intent.client_order_id,
                state=OrderState.REJECTED,
                submitted_at=submitted_at,
                error_verbatim=f"HTTP {response.status}: {excerpt(response.body)}",
            )
        if response.status != 200:
            return OrderResult(
                client_order_id=intent.client_order_id,
                state=OrderState.UNKNOWN,
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
        accepted = data[0] if isinstance(data, list) and data else data
        if (
            not isinstance(accepted, dict)
            or accepted.get("client_order_id") != intent.client_order_id
            or not isinstance(accepted.get("order_id"), str)
            or not accepted["order_id"]
        ):
            return OrderResult(
                client_order_id=intent.client_order_id,
                state=OrderState.UNKNOWN,
                submitted_at=submitted_at,
                error_verbatim="broker acceptance did not echo client_order_id with an order_id",
            )
        return OrderResult(
            client_order_id=intent.client_order_id,
            state=OrderState.SUBMITTING,
            broker_order_id=accepted["order_id"],
            submitted_at=submitted_at,
            raw_status_verbatim=excerpt(response.body),
        )

    def place_combo(self, intent: ComboOrderIntent) -> OrderResult:
        """Refused. No native combo is wired, and A2 forbids a leg-by-leg loop."""
        return self._refuse(
            intent, "webull_sandbox submits no multi-leg structure; there is no leg-by-leg fallback"
        )

    def cancel(self, client_order_id: str) -> OrderResult:
        try:
            response = self._call(
                "POST",
                "/trading/orders/cancel",
                body={"account_id": self._expected_account_id, "client_order_id": client_order_id},
            )
        except Exception as exc:
            return OrderResult(
                client_order_id=client_order_id,
                state=OrderState.UNKNOWN,
                error_verbatim=f"cancel transport failure: {type(exc).__name__}",
            )
        if response.host not in PAPER_HOST_ALLOWLIST:
            return OrderResult(
                client_order_id=client_order_id,
                state=OrderState.UNKNOWN,
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
                error_verbatim="order not found after cancel request",
            )
        return OrderResult(
            client_order_id=client_order_id,
            state=status.state,
            broker_order_id=status.broker_order_id,
            raw_status_verbatim=status.raw_status_verbatim,
        )

    def cancel_all(self) -> Sequence[OrderResult]:
        working = sorted(self.open_orders(), key=lambda s: s.client_order_id)
        return tuple(self.cancel(status.client_order_id) for status in working)


# ---------------------------------------------------------------------------
# Body readers — strict, and every miss is UNKNOWN rather than a guess
# ---------------------------------------------------------------------------


def _account_ids(accounts: Any) -> list[str]:
    rows = accounts.get("accounts", accounts) if isinstance(accounts, dict) else accounts
    if not isinstance(rows, list):
        return []
    ids: list[str] = []
    for row in rows:
        if isinstance(row, dict):
            account_id = row.get("account_id")
            if isinstance(account_id, str) and account_id:
                ids.append(account_id)
    return ids


def _order_rows(data: Any) -> list[dict[str, Any]]:
    rows = data.get("orders", data.get("data", [])) if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise VendorAdapterError("order list is not a list")
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise VendorAdapterError("order row is not an object")
        # A combo detail nests its legs; a plain order is the row itself.
        nested = row.get("orders")
        if isinstance(nested, list) and nested and isinstance(nested[0], dict):
            out.extend(r for r in nested if isinstance(r, dict))
        else:
            out.append(row)
    return out


def _order_status_from(row: dict[str, Any]) -> OrderStatus:
    client_order_id = row.get("client_order_id")
    if not isinstance(client_order_id, str) or not client_order_id:
        raise VendorAdapterError("order row carries no client_order_id")
    raw_status = str(row.get("status", ""))
    state = _STATUS_MAP.get(raw_status.upper(), OrderState.UNKNOWN)
    filled = row.get("filled_quantity")
    filled_qty = strict_number(filled, what="filled quantity") if filled not in (None, "") else 0.0
    if state is OrderState.CANCELLED and filled_qty > 0:
        state = OrderState.PARTIAL
    broker_order_id = row.get("order_id")
    return OrderStatus(
        client_order_id=client_order_id,
        state=state,
        broker_order_id=broker_order_id if isinstance(broker_order_id, str) else "",
        filled_qty=filled_qty,
        raw_status_verbatim=raw_status,
        legs_filled_ratio=(),
    )
