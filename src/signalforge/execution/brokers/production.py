"""Pinned official production REST surfaces, NEVER a sandbox BrokerAdapter.

Sources (reviewed 2026-11-01):
https://docs.cdp.coinbase.com/coinbase-app/authentication-authorization/api-key-authentication
https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders/create-order
https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/portfolios/move-portfolios-funds
https://developer.webull.com/apis/docs/authentication/signature/
https://developer.webull.com/apis/docs/rate-limits/

No arbitrary endpoints, redirects, credential acquisition, SDKs, or retry loops.
Hard provider caps are required by default. Explicit immutable estimate-policy
reviews may use a fresh Coinbase preview; actual fees/debit can exceed estimates.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from pydantic import SecretStr

from signalforge.execution.brokers.vendor_base import Transport, VendorRequest
from signalforge.execution.credentials import CredentialRef, resolve_credential
from signalforge.execution.production import Action, ProductionRefusal

PRODUCTION_HOSTS = {"coinbase": "api.coinbase.com", "webull": "api.webull.com"}
CB = "/api/v3/brokerage"


@dataclass(frozen=True, slots=True)
class ProductionRequest(VendorRequest):
    """Auth headers and account payloads must never appear in diagnostic repr."""

    headers: tuple[tuple[str, str], ...] = field(default=(), repr=False)
    body: str | None = field(default=None, repr=False)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def coinbase_jwt(
    key_id: SecretStr, private_key: SecretStr, method: str, path: str, now: datetime, nonce: str
) -> str:
    """Short-lived ES256 JWT, bound to the exact method, host and path."""
    try:
        key = serialization.load_pem_private_key(private_key.get_secret_value().encode(), None)
        if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(
            key.curve, ec.SECP256R1
        ):
            raise ValueError("P-256 required")
        header = {"alg": "ES256", "typ": "JWT", "kid": key_id.get_secret_value(), "nonce": nonce}
        payload = {
            "sub": key_id.get_secret_value(),
            "iss": "cdp",
            "nbf": int(now.timestamp()),
            "exp": int(now.timestamp()) + 120,
            "uri": f"{method} {PRODUCTION_HOSTS['coinbase']}{path}",
        }
        message = ".".join(
            _b64(json.dumps(v, separators=(",", ":")).encode()) for v in (header, payload)
        )
        r, s = decode_dss_signature(key.sign(message.encode(), ec.ECDSA(hashes.SHA256())))
        return message + "." + _b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    except Exception:
        raise ProductionRefusal(
            "Coinbase signing failed; operator must provision an ES256 key"
        ) from None


def webull_headers(
    key_id: SecretStr,
    secret: SecretStr,
    token: SecretStr,
    path: str,
    query: tuple[tuple[str, str], ...],
    body: str | None,
    now: datetime,
    nonce: str,
) -> tuple[tuple[str, str], ...]:
    """Official production HMAC-SHA1/MD5 protocol; independent of sandbox signer."""
    headers = {
        "x-app-key": key_id.get_secret_value(),
        "x-timestamp": now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "x-signature-algorithm": "HMAC-SHA1",
        "x-signature-version": "1.0",
        "x-signature-nonce": nonce,
    }
    params = {**dict(query), **headers, "host": PRODUCTION_HOSTS["webull"]}
    text = path + "&" + "&".join(f"{k}={params[k]}" for k in sorted(params))
    if body is not None:
        text += "&" + hashlib.md5(body.encode(), usedforsecurity=False).hexdigest().upper()
    unreserved = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~"
    encoded = "".join(chr(b) if b in unreserved else f"%{b:02X}" for b in text.encode())
    signature = hmac.new(
        (secret.get_secret_value() + "&").encode(), encoded.encode(), hashlib.sha1
    ).digest()
    headers.update(
        {
            "x-signature": base64.b64encode(signature).decode(),
            "x-version": "v3",
            "x-access-token": token.get_secret_value(),
            "Content-Type": "application/json",
        }
    )
    return tuple(headers.items())


def amount(value: Any) -> Decimal:
    try:
        if not isinstance(value, (str, int)) or isinstance(value, bool):
            raise ValueError
        result = Decimal(value)
        if not result.is_finite() or result < 0:
            raise ValueError
        return result
    except (InvalidOperation, ValueError):
        raise ProductionRefusal("missing or invalid provider amount") from None


@dataclass(frozen=True)
class ProductionAttestation:
    provider: str
    environment: str
    account_id: str
    observed_host: str
    checked_at: datetime
    # None means provider has no reviewed metadata endpoint, not permission granted.
    can_view: bool | None
    can_trade: bool | None
    can_transfer: bool | None


class ProductionBroker:
    def __init__(
        self,
        provider: str,
        account_id: str,
        transport: Transport,
        key_ref: CredentialRef,
        secret_ref: CredentialRef,
        token_ref: CredentialRef | None = None,
        *,
        enabled: bool = False,
        resolver: Callable[[CredentialRef], SecretStr] = resolve_credential,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if provider not in PRODUCTION_HOSTS or not account_id:
            raise ProductionRefusal("unsupported provider or absent expected account")
        self.provider = provider
        try:
            self.account_id = str(uuid.UUID(account_id)) if provider == "coinbase" else account_id
        except ValueError:
            raise ProductionRefusal("Coinbase account identity must be a portfolio UUID") from None
        if account_id.strip() != account_id:
            raise ProductionRefusal("account identifiers must not contain surrounding whitespace")
        self._transport, self._resolver, self._now = transport, resolver, now
        self._key_ref, self._secret_ref, self._token_ref = key_ref, secret_ref, token_ref
        self.enabled = enabled
        self.preflight_evidence: dict[str, Any] = {}
        self.send_evidence: dict[str, Any] = {}
        self._last_http_status = 0
        self.reconciliation_evidence: dict[str, Any] = {}
        self.cancel_original: Action | None = None
        self._webull_account: dict[str, Any] = {}

    def _call(
        self,
        method: str,
        path: str,
        *,
        query: tuple[tuple[str, str], ...] = (),
        body: dict[str, Any] | None = None,
    ) -> Any:
        if not self.enabled:
            raise ProductionRefusal("production access disabled")
        raw_body = json.dumps(body, separators=(",", ":")) if body is not None else None
        try:
            key = self._resolver(self._key_ref)
            secret = self._resolver(self._secret_ref)
            if self.provider == "coinbase":
                jwt = coinbase_jwt(key, secret, method, path, self._now(), uuid.uuid4().hex)
                headers: tuple[tuple[str, str], ...] = (
                    ("Authorization", f"Bearer {jwt}"),
                    ("Content-Type", "application/json"),
                )
            else:
                if self._token_ref is None:
                    raise ProductionRefusal(
                        "operator-provisioned Webull access token reference required"
                    )
                headers = webull_headers(
                    key,
                    secret,
                    self._resolver(self._token_ref),
                    path,
                    query,
                    raw_body,
                    self._now(),
                    uuid.uuid4().hex,
                )
            response = self._transport(
                ProductionRequest(
                    method, PRODUCTION_HOSTS[self.provider], path, query, headers, raw_body
                )
            )
            if response.host != PRODUCTION_HOSTS[self.provider] or not 200 <= response.status < 300:
                raise ProductionRefusal("provider origin/status refused")
            self._last_http_status = response.status
            data = json.loads(response.body)
            if not isinstance(data, (dict, list)):
                raise ProductionRefusal("provider response shape refused")
            if isinstance(data, dict) and (
                data.get("error")
                or data.get("error_code")
                or data.get("errors")
                or data.get("success") is False
            ):
                raise ProductionRefusal("provider rejected request")
            return data
        except Exception:
            # Do not echo provider bodies, headers, credential resolver exceptions, or URLs.
            raise ProductionRefusal("provider request failed; no automatic retry") from None

    def attest(self) -> ProductionAttestation:
        if self.provider == "coinbase":
            data = self._call("GET", CB + "/key_permissions")
            if not isinstance(data, dict) or data.get("portfolio_uuid") != self.account_id:
                raise ProductionRefusal("production portfolio identity mismatch")
            if any(
                type(data.get(k)) is not bool for k in ("can_view", "can_trade", "can_transfer")
            ):
                raise ProductionRefusal("permission metadata incomplete")
            permissions = (data["can_view"], data["can_trade"], data["can_transfer"])
            if not permissions[0]:
                raise ProductionRefusal("view permission absent")
        else:
            data = self._call("GET", "/trading/accounts/list")
            if not isinstance(data, list) or not any(
                isinstance(r, dict) and r.get("account_id") == self.account_id for r in data
            ):
                raise ProductionRefusal("production account identity mismatch")
            matches = [r for r in data if r.get("account_id") == self.account_id]
            if len(matches) != 1:
                raise ProductionRefusal("ambiguous account identity")
            self._webull_account = matches[0]
            permissions = (True, None, None)
        return ProductionAttestation(
            self.provider,
            "production",
            self.account_id,
            PRODUCTION_HOSTS[self.provider],
            self._now(),
            *permissions,
        )

    def _pages(
        self, path: str, key: str, query: tuple[tuple[str, str], ...] = ()
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        cursor = ""
        for _ in range(100):
            data = self._call(
                "GET", path, query=(*query, *((("cursor", cursor),) if cursor else ()))
            )
            if not isinstance(data, dict) or not isinstance(data.get(key), list):
                raise ProductionRefusal("incomplete snapshot: missing collection")
            if any(not isinstance(row, dict) for row in data[key]):
                raise ProductionRefusal("invalid collection row")
            rows.extend(data[key])
            more = data.get("has_next")
            next_cursor = data.get("cursor", "")
            if key in {"accounts", "orders"} and type(more) is not bool:
                raise ProductionRefusal("incomplete snapshot: pagination flag missing")
            if more is False or (more is None and not next_cursor):
                return rows
            if (
                more not in (True, None)
                or not isinstance(next_cursor, str)
                or not next_cursor
                or next_cursor in seen
            ):
                raise ProductionRefusal("incomplete snapshot: invalid/repeated cursor")
            cursor = next_cursor
            seen.add(cursor)
        raise ProductionRefusal("incomplete snapshot: pagination limit reached")

    def _webull_pages(self, path: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        cursor = ""
        for _ in range(100):
            query: tuple[tuple[str, str], ...] = (("account_id", self.account_id),)
            if cursor:
                query += (("pagination_key", cursor),)
            page = self._call("GET", path, query=query)
            if not isinstance(page, dict) or not isinstance(page.get("data"), list):
                raise ProductionRefusal("incomplete Webull order snapshot")
            if any(
                not isinstance(r, dict) or r.get("account_id", self.account_id) != self.account_id
                for r in page["data"]
            ):
                raise ProductionRefusal("Webull order account mismatch")
            rows.extend(page["data"])
            cursor = page.get("pagination_key", "")
            if not cursor:
                return rows
            if not isinstance(cursor, str) or cursor in seen or not page["data"]:
                raise ProductionRefusal("incomplete Webull pagination")
            seen.add(cursor)
        raise ProductionRefusal("Webull pagination limit reached")

    def read(self, resource: str, identifier: str = "") -> Any:
        self.attest()
        if identifier and not all(c.isalnum() or c in "-_." for c in identifier):
            raise ProductionRefusal("invalid resource identifier")
        if self.provider == "coinbase":
            if resource in {"accounts", "positions", "balances"}:
                rows = self._pages(CB + "/accounts", "accounts", (("limit", "250"),))
                # Never present accounts from another portfolio as the selected account.
                if any(r.get("retail_portfolio_id") != self.account_id for r in rows):
                    raise ProductionRefusal("account snapshot scope missing or mismatched")
                return rows
            if resource == "orders":
                rows = self._pages(
                    CB + "/orders/historical/batch",
                    "orders",
                    (("retail_portfolio_id", self.account_id),),
                )
                if any(r.get("retail_portfolio_id") != self.account_id for r in rows):
                    raise ProductionRefusal("order collection account scope incomplete")
                return rows
            if resource == "fills":
                return self._pages(
                    CB + "/orders/historical/fills",
                    "fills",
                    (("retail_portfolio_id", self.account_id),),
                )
            if resource == "portfolios":
                return self._call("GET", CB + "/portfolios")
            if resource == "product" and identifier:
                return self._call("GET", CB + "/products/" + identifier)
            if resource == "order" and identifier:
                data = self._call("GET", CB + "/orders/historical/" + identifier)
                row = data.get("order", {})
                if (
                    row.get("retail_portfolio_id") != self.account_id
                    or row.get("order_id") != identifier
                ):
                    raise ProductionRefusal("order account mismatch")
                return row
        else:
            routes = {
                "balances": "/trading/assets/balances/get",
                "positions": "/trading/assets/positions/list",
                "orders": "/trading/orders/historical-orders/list",
                "open-orders": "/trading/orders/open-orders/list",
                "order": "/trading/orders/get",
            }
            if resource == "accounts":
                return self._call("GET", "/trading/accounts/list")
            if resource in {"orders", "open-orders"}:
                return self._webull_pages(routes[resource])
            if resource in routes:
                query: tuple[tuple[str, str], ...] = (("account_id", self.account_id),)
                if resource == "order":
                    if not identifier:
                        raise ProductionRefusal("exact client order id required")
                    query += (("client_order_id", identifier),)
                data = self._call("GET", routes[resource], query=query)
                if resource == "order":
                    if (
                        not isinstance(data, dict)
                        or data.get("combo_type") != "NORMAL"
                        or not isinstance(data.get("orders"), list)
                        or len(data["orders"]) != 1
                    ):
                        raise ProductionRefusal("expected one simple Webull order")
                    row = data["orders"][0]
                    if (
                        not isinstance(row, dict)
                        or row.get("client_order_id") != identifier
                        or row.get("account_id", self.account_id) != self.account_id
                        or data.get("account_id", self.account_id) != self.account_id
                    ):
                        raise ProductionRefusal("Webull order identity mismatch")
                    return row
                # Unknown pagination is reported explicitly; never label a page complete.
                if isinstance(data, dict) and any(
                    data.get(k) for k in ("has_next", "has_next_page", "next", "next_cursor")
                ):
                    raise ProductionRefusal("incomplete Webull snapshot: continuation unsupported")
                return data
        raise ProductionRefusal("unsupported provider resource/product; no endpoint fallback")

    def wire(self, action: Action) -> tuple[str, dict[str, Any]]:
        if action.provider != self.provider or action.account_id != self.account_id:
            raise ProductionRefusal("action identity differs from configured identity")
        if action.kind == "transfer":
            if self.provider != "coinbase":
                raise ProductionRefusal(
                    "Webull retail funding unsupported; separate institutional product"
                )
            return CB + "/portfolios/move_funds", {
                "funds": {"value": str(action.quantity), "currency": action.asset},
                "source_portfolio_uuid": self.account_id,
                "target_portfolio_uuid": action.destination,
            }
        if action.kind == "cancel":
            if self.provider == "coinbase":
                return CB + "/orders/batch_cancel", {"order_ids": [action.order_id]}
            return "/trading/orders/cancel", {
                "account_id": self.account_id,
                "client_order_id": action.order_id,
            }
        if self.provider == "coinbase":
            return CB + "/orders", {
                "client_order_id": action.action_id,
                "product_id": action.asset,
                "retail_portfolio_id": self.account_id,
                "side": action.side,
                "order_configuration": {
                    "limit_limit_gtd": {
                        "base_size": str(action.quantity),
                        "limit_price": str(action.limit_price),
                        "end_time": action.expires_at.isoformat(),
                        "post_only": False,
                    }
                },
            }
        return "/trading/orders/place", {
            "account_id": self.account_id,
            "new_orders": [
                {
                    "client_order_id": action.action_id,
                    "combo_type": "NORMAL",
                    "symbol": action.asset,
                    "instrument_type": "EQUITY",
                    "market": "US",
                    "side": action.side,
                    "order_type": "LIMIT",
                    "limit_price": str(action.limit_price),
                    "quantity": str(action.quantity),
                    "time_in_force": "DAY",
                    "support_trading_session": "CORE",
                    "entrust_type": "QTY",
                }
            ],
        }

    def preflight(self, action: Action) -> None:
        self.preflight_evidence = {}
        proof = self.attest()
        self.wire(action)
        if action.expires_at <= self._now():
            raise ProductionRefusal("expired review")
        if self.provider == "webull":
            self._webull_preflight(action)
            return
        if action.kind == "cancel":
            if proof.can_trade is not True:
                raise ProductionRefusal(
                    "provider-specific trade authority unproven; cancel refused"
                )
            row = self.read("order", action.order_id)
            if (
                action.original_action_id
                and row.get("client_order_id") != action.original_action_id
            ):
                raise ProductionRefusal("cancel order differs from original held action")
            return
        # Complete account-bound inventory while shared admission is held. Unknown
        # statuses are not silently treated as terminal or non-conflicting.
        orders = self.read("orders")
        terminal = {"FILLED", "CANCELLED", "CANCELED", "EXPIRED", "FAILED", "REJECTED"}
        if not isinstance(orders, list) or any(row.get("status") not in terminal for row in orders):
            raise ProductionRefusal("foreign/open/unknown orders block exposure and transfers")
        if action.kind == "transfer":
            if proof.can_transfer is not True:
                raise ProductionRefusal("transfer permission missing")
            destination_orders = self._pages(
                CB + "/orders/historical/batch",
                "orders",
                (("retail_portfolio_id", action.destination),),
            )
            if any(
                r.get("retail_portfolio_id") != action.destination
                or r.get("status") not in terminal
                for r in destination_orders
            ):
                raise ProductionRefusal("destination open-order scope incomplete or conflicting")
            portfolios = self.read("portfolios")
            if not isinstance(portfolios, dict) or not any(
                r.get("uuid") == action.destination and r.get("deleted") is not True
                for r in portfolios.get("portfolios", [])
            ):
                raise ProductionRefusal("destination portfolio not verified")
            accounts = self.read("accounts")
            transfer_available = sum(
                (
                    amount(r.get("available_balance", {}).get("value"))
                    for r in accounts
                    if r.get("currency") == action.asset
                ),
                Decimal(0),
            )
            if transfer_available < action.quantity:
                raise ProductionRefusal("insufficient available transfer funds")
            return
        if self.provider != "coinbase" or action.fee_policy != "accept_rechecked_estimate":
            raise ProductionRefusal(
                "provider-enforced fee/debit cap unavailable; no silent fallback"
            )
        if proof.can_trade is not True:
            raise ProductionRefusal("trade permission missing")
        product = self.read("product", action.asset)
        flags = ("trading_disabled", "is_disabled", "cancel_only", "view_only", "auction_mode")
        if (
            product.get("product_type") != "SPOT"
            or product.get("product_id") != action.asset
            or product.get("status") != "online"
            or any(product.get(k) is not False for k in flags)
        ):
            raise ProductionRefusal("product identity/status/eligibility missing or not spot")
        base, quote = product.get("base_currency_id"), product.get("quote_currency_id")
        if action.fee_currency != quote or action.debit_currency != quote:
            raise ProductionRefusal("fee/debit currencies must match the spot quote currency")
        for value, increment_field, minimum_field, maximum_field in (
            (action.quantity, "base_increment", "base_min_size", "base_max_size"),
            (action.limit_price, "quote_increment", None, None),
        ):
            increment = amount(product.get(increment_field))
            if increment <= 0 or value % increment:
                raise ProductionRefusal("quantity/price not a valid product increment")
            if minimum_field and not amount(product.get(minimum_field)) <= value <= amount(
                product.get(maximum_field)
            ):
                raise ProductionRefusal("quantity outside product bounds")
        rows = self.read("accounts")

        def available(currency: str) -> Decimal:
            selected = [r for r in rows if r.get("currency") == currency]
            if any(r.get("available_balance", {}).get("currency") != currency for r in selected):
                raise ProductionRefusal("balance currency unproven")
            return sum(
                (amount(r.get("available_balance", {}).get("value")) for r in selected), Decimal(0)
            )

        notional = action.quantity * action.limit_price
        if action.side == "SELL":
            if available(base) < action.quantity:
                raise ProductionRefusal("protective close exceeds available long holdings")
            # Do not assume sale proceeds can fund fees before settlement.
            if available(quote) < action.fee_estimate_ceiling + action.headroom:
                raise ProductionRefusal("separate quote funds required for sell fees/headroom")
        elif available(quote) < notional + action.fee_estimate_ceiling + action.headroom:
            raise ProductionRefusal("insufficient quote funds for notional plus fees/headroom")
        _, body = self.wire(action)
        preview_body = {k: v for k, v in body.items() if k != "client_order_id"}
        started = self._now()
        preview = self._call("POST", CB + "/orders/preview", body=preview_body)
        observed = self._now()
        if observed - started > timedelta(seconds=5) or observed < started:
            raise ProductionRefusal("stale preview")
        if (
            not isinstance(preview, dict)
            or preview.get("errs") != []
            or preview.get("warning", []) != []
            or not isinstance(preview.get("preview_id"), str)
            or not preview["preview_id"]
        ):
            raise ProductionRefusal("preview failed or fee coverage uncertain")
        fee = amount(preview.get("commission_total"))
        total = amount(preview.get("order_total"))
        detail = preview.get("commission_detail_total", {})
        if not isinstance(detail, dict) or amount(detail.get("total_commission")) != fee:
            raise ProductionRefusal("complete commission coverage unproven")
        if any(
            amount(detail.get(k, "0")) != 0 for k in ("gst_commission", "withholding_commission")
        ):
            raise ProductionRefusal("tax/withholding fee coverage unsupported")
        if fee > action.fee_estimate_ceiling or total > action.debit_admission_ceiling:
            raise ProductionRefusal("fresh estimate exceeds approved ceiling; create a new review")
        self.preflight_evidence = {
            "action_digest": action.digest(),
            "preview_id": preview["preview_id"],
            "observed_at": observed.isoformat(),
            "commission_total": str(fee),
            "order_total": str(total),
            "fee_currency": quote,
            "policy": "accept_rechecked_estimate",
            "disclosure": "Actual fees and debit may exceed pre-send admission ceilings.",
        }

    def _webull_preflight(self, action: Action) -> None:
        if self._webull_account.get("account_class") not in {
            "INDIVIDUAL_CASH",
            "INDIVIDUAL_MARGIN",
            "ROTH_IRA",
            "TRADITIONAL_IRA",
            "ROLLOVER_IRA",
        }:
            raise ProductionRefusal("Webull equity account eligibility unproven")
        if action.kind == "cancel":
            original = self.cancel_original
            if original is None or action.original_action_id != original.action_id:
                raise ProductionRefusal(
                    "Webull cancel authority unproven: tracked original order required"
                )
            row = self.read("order", action.order_id)
            self._match_webull_order(original, row)
            if row.get("status") not in {"PENDING", "SUBMITTED", "PARTIAL_FILLED"}:
                raise ProductionRefusal(
                    "Webull cancellation requires a positively identified open API order"
                )
            self.preflight_evidence = {
                "authority_basis": "exact owned API order",
                "client_order_id": action.order_id,
            }
            return
        if (
            action.kind not in {"order", "protective_close"}
            or action.fee_policy != "accept_rechecked_estimate"
        ):
            raise ProductionRefusal(
                "Webull hard fee caps/funding unsupported; explicit estimate policy required"
            )
        if action.fee_currency != "USD" or action.debit_currency != "USD":
            raise ProductionRefusal("Webull equity estimate coverage is USD only")
        if self.read("open-orders"):
            raise ProductionRefusal("foreign/open Webull orders block new exposure")
        balance = self.read("balances")
        if not isinstance(balance, dict) or balance.get("total_asset_currency") != "USD":
            raise ProductionRefusal("Webull settlement currency unproven")
        rows = balance.get("account_currency_assets")
        if not isinstance(rows, list):
            raise ProductionRefusal("Webull funds incomplete")
        usd = [r for r in rows if isinstance(r, dict) and r.get("currency") == "USD"]
        if len(usd) != 1:
            raise ProductionRefusal("Webull USD funds ambiguous")
        available = amount(usd[0].get("settled_cash")) - amount(usd[0].get("frozen_amount"))
        required = action.fee_estimate_ceiling + action.headroom
        if action.side == "BUY":
            required += action.quantity * action.limit_price
        else:
            positions = self.read("positions")
            if not isinstance(positions, list):
                raise ProductionRefusal("Webull holdings incomplete")
            owned = sum(
                (
                    amount(r.get("quantity"))
                    for r in positions
                    if r.get("symbol") == action.asset
                    and r.get("instrument_type") == "EQUITY"
                    and r.get("currency") == "USD"
                ),
                Decimal(0),
            )
            if owned < action.quantity:
                raise ProductionRefusal("Webull close exceeds available long holding")
        if available < required:
            raise ProductionRefusal("insufficient unreserved settled USD; no margin borrowing")
        _, body = self.wire(action)
        started = self._now()
        preview = self._call("POST", "/trading/orders/preview", body=body)
        observed = self._now()
        if observed < started or observed - started > timedelta(seconds=5):
            raise ProductionRefusal("stale Webull preview")
        if not isinstance(preview, dict):
            raise ProductionRefusal("Webull preview incomplete")
        fee, cost = amount(preview.get("estimated_transaction_fee")), amount(
            preview.get("estimated_cost")
        )
        if fee > action.fee_estimate_ceiling or (
            action.side == "BUY" and cost > action.debit_admission_ceiling
        ):
            raise ProductionRefusal("Webull estimate exceeds approved ceiling")
        self.preflight_evidence = {
            "action_digest": action.digest(),
            "observed_at": observed.isoformat(),
            "estimated_transaction_fee": str(fee),
            "estimated_cost": str(cost),
            "fee_currency": "USD",
            "policy": "accept_rechecked_estimate",
            "authority_basis": "eligible account and authenticated exact equity order preview",
            "disclosure": "Actual fees/debit may exceed pre-send admission ceilings.",
        }

    @staticmethod
    def _match_webull_order(action: Action, row: dict[str, Any]) -> None:
        expected = {
            "client_order_id": action.action_id,
            "symbol": action.asset,
            "side": action.side,
            "order_type": "LIMIT",
            "time_in_force": "DAY",
            "instrument_type": "EQUITY",
            "entrust_type": "QTY",
        }
        if any(row.get(k) != v for k, v in expected.items()):
            raise ProductionRefusal("Webull original order terms mismatch")
        if (
            amount(row.get("total_quantity")) != action.quantity
            or amount(row.get("limit_price")) != action.limit_price
        ):
            raise ProductionRefusal("Webull original order amount mismatch")

    def send(self, action: Action) -> str:
        # Defense in depth: no caller can bypass unsupported economic guarantees.
        path, body = self.wire(action)
        if action.kind in {"order", "protective_close"}:
            evidence = self.preflight_evidence
            if (
                action.fee_policy != "accept_rechecked_estimate"
                or evidence.get("action_digest") != action.digest()
            ):
                raise ProductionRefusal(
                    "provider-enforced fee ceiling unavailable or preview missing"
                )
            observed = datetime.fromisoformat(evidence["observed_at"])
            if not timedelta(0) <= self._now() - observed <= timedelta(seconds=5):
                raise ProductionRefusal("preview expired before submission")
            if self.provider == "coinbase":
                body["preview_id"] = evidence["preview_id"]
        if action.expires_at <= self._now():
            raise ProductionRefusal("action expired before submission")
        data = self._call("POST", path, body=body)
        if not isinstance(data, dict):
            raise ProductionRefusal("ambiguous write response")
        if action.kind == "cancel":
            if self.provider == "coinbase":
                results = data.get("results", [])
                if (
                    len(results) != 1
                    or results[0].get("order_id") != action.order_id
                    or results[0].get("success") is not True
                ):
                    raise ProductionRefusal("cancellation not acknowledged")
            elif data.get("client_order_id") != action.order_id:
                raise ProductionRefusal("cancellation not acknowledged")
            return action.order_id
        if action.kind in {"order", "protective_close"}:
            if self.provider == "webull":
                if (
                    data.get("client_order_id") != action.action_id
                    or not isinstance(data.get("order_id"), str)
                    or not data["order_id"]
                ):
                    raise ProductionRefusal("Webull order acknowledgement ambiguous")
                return data["order_id"]
            result = data.get("success_response", {})
            if (
                data.get("success") is not True
                or not isinstance(result, dict)
                or any(result.get(k) != body[k] for k in ("client_order_id", "product_id", "side"))
                or not isinstance(result.get("order_id"), str)
                or not result["order_id"]
            ):
                raise ProductionRefusal("order acknowledgement identity ambiguous")
            return result["order_id"]
        # Official Advanced Trade guide: synchronous, instantaneous, free movement.
        # Request binds asset/amount; response confirms endpoints, without echoing
        # funds or supplying a transfer id. Do not invent an absent response field.
        if (
            self._last_http_status != 200
            or any(
                k in data for k in ("error", "errors", "error_code", "code", "message", "details")
            )
            or data.get("source_portfolio_uuid") != action.account_id
            or data.get("target_portfolio_uuid") != action.destination
        ):
            raise ProductionRefusal("portfolio-move acknowledgement ambiguous; hold retained")
        self.send_evidence = {
            "action_digest": action.digest(),
            "http_status": 200,
            "source_portfolio_uuid": action.account_id,
            "target_portfolio_uuid": action.destination,
            "request_funds": body["funds"],
            "local_action_id": action.action_id,
            "outcome": "provider-confirmed synchronous completion",
            "disclosure": "No independent balance measurement; no provider transfer id returned.",
        }
        return action.action_id

    def reconcile(self, action: Action, outcome_id: str = "") -> bool:
        """Positive terminal evidence only. Missing lookup never releases or retries."""
        self.reconciliation_evidence = {}
        if action.kind == "transfer":
            raise ProductionRefusal("authoritative transfer resolution unsupported; hold retained")
        if self.provider == "webull":
            client_id = action.order_id if action.kind == "cancel" else action.action_id
            row = self.read("order", client_id)
            original = self.cancel_original if action.kind == "cancel" else action
            if original is None:
                raise ProductionRefusal("tracked Webull original required for reconciliation")
            self._match_webull_order(original, row)
            if row.get("status") not in {"CANCELLED", "FILLED", "FAILED"}:
                return False
            commission, fees = row.get("commission"), row.get("fees")
            if not isinstance(commission, dict) or not isinstance(fees, list):
                raise ProductionRefusal("actual Webull fees incomplete; hold retained")
            actual = amount(commission.get("actual_commission"))
            if amount(commission.get("receivable_commission")) != actual:
                raise ProductionRefusal("commission settlement incomplete")
            for fee in fees:
                if (
                    not isinstance(fee, dict)
                    or not fee.get("type")
                    or amount(fee.get("actual_value")) != amount(fee.get("receivable_value"))
                ):
                    raise ProductionRefusal("fee settlement incomplete")
                actual += amount(fee["actual_value"])
            qty = amount(row.get("filled_quantity"))
            filled = qty * amount(row.get("filled_price")) if qty else Decimal(0)
            debit = filled + actual if original.side == "BUY" else actual
            self.reconciliation_evidence = {
                "total_fees": str(actual),
                "filled_value": str(filled),
                "fee_currency": "USD",
                "fee_overrun": actual > original.fee_estimate_ceiling,
                "debit_overrun": debit > original.debit_admission_ceiling,
                "status": row["status"],
            }
            return True
        order_id = action.order_id or outcome_id
        if not order_id:
            matches = [
                row for row in self.read("orders") if row.get("client_order_id") == action.action_id
            ]
            if len(matches) != 1:
                return False
            order_id = matches[0].get("order_id", "")
        row = self.read("order", order_id)
        if action.original_action_id and row.get("client_order_id") != action.original_action_id:
            raise ProductionRefusal("terminal cancellation identity differs from held order")
        if action.kind in {"order", "protective_close"}:
            _, body = self.wire(action)
            if any(
                row.get(k) != body[k]
                for k in ("client_order_id", "product_id", "side", "order_configuration")
            ):
                raise ProductionRefusal("reconciliation terms mismatch")
        if row.get("status") not in {"CANCELLED", "FILLED", "EXPIRED", "FAILED"}:
            return False
        if action.kind in {"order", "protective_close"}:
            fees = amount(row.get("total_fees"))
            filled = amount(row.get("filled_value"))
            self.reconciliation_evidence = {
                "total_fees": str(fees),
                "filled_value": str(filled),
                "fee_currency": action.fee_currency,
                "fee_overrun": fees > action.fee_estimate_ceiling,
                "debit_overrun": (filled + fees if action.side == "BUY" else fees)
                > action.debit_admission_ceiling,
                "order_id": order_id,
                "status": row["status"],
            }
        return True
