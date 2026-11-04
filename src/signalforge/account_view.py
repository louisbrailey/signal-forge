"""Validated, network-free account display contract. Never an input to paper books."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

# Also used by the existing isolated Webull SDK's Python 3.9 interpreter.
# ruff: noqa: UP017
UTC = timezone.utc
MAX_BYTES = 1_048_576
MAX_ACCOUNTS = 10
MAX_POSITIONS = 500
BALANCES = {
    "total_net_liquidation_value": "Net liquidation value",
    "total_market_value": "Market value",
    "total_cash_balance": "Cash balance",
    "total_unrealized_profit_loss": "Unrealized P&L",
    "total_day_profit_loss": "Day P&L",
}
POSITION_FIELDS = ("quantity", "last_price", "cost_price", "unrealized_profit_loss")


def number(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool) or len(str(value)) > 40:
        raise ValueError("Invalid number")
    try:
        n = Decimal(str(value))
        exponent = n.as_tuple().exponent
        if (
            not n.is_finite()
            or abs(n) > Decimal("1e15")
            or not isinstance(exponent, int)
            or exponent < -12
        ):
            raise ValueError("Invalid number")
        return format(n, "f")
    except InvalidOperation:
        raise ValueError("Invalid number") from None


def label(value: Any, pattern: str, limit: int) -> str:
    if (
        not isinstance(value, str)
        or not 0 < len(value) <= limit
        or not re.fullmatch(pattern, value)
    ):
        raise ValueError("Invalid label")
    return value


def normalize_account(
    account_id: str, balance: dict[str, Any], positions: list[dict[str, Any]]
) -> dict[str, Any]:
    """Project only known fields; never store raw payloads, account numbers or secrets."""
    label(account_id, r"[A-Za-z0-9_-]+", 128)
    if not isinstance(balance, dict) or not isinstance(positions, list):
        raise ValueError("Invalid account response")
    if len(positions) > MAX_POSITIONS:
        raise ValueError("Position cap exceeded; do not truncate")
    result: dict[str, Any] = {
        "label": "Webull account ••••" + account_id[-4:],
        "currency": label(balance.get("total_asset_currency"), r"[A-Z]{3}", 3),
        "balances": {k: number(balance.get(k)) for k in BALANCES},
        "positions": [],
    }
    identities = set()
    for p in positions:
        identity = label(p.get("position_id"), r"[A-Za-z0-9_-]+", 128)
        if identity in identities:
            raise ValueError("Duplicate position")
        identities.add(identity)
        result["positions"].append(
            {
                "symbol": label(p.get("symbol"), r"[A-Za-z0-9. :/_-]+", 80),
                "kind": label(p.get("instrument_type"), r"[A-Za-z0-9_ -]+", 40),
                "currency": label(p.get("currency"), r"[A-Z]{3}", 3),
                **{k: number(p.get(k)) for k in POSITION_FIELDS},
            }
        )
    return result


def project_snapshot(data: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Validate persisted display data again; unexpected strings never reach the UI."""
    now = now or datetime.now(UTC)
    if data.get("schema") != "webull-readonly-v1":
        raise ValueError("Unknown schema")
    if data.get("environment") != "production" or data.get("trading_enabled") is not False:
        raise ValueError("Invalid posture")
    status = data.get("status")
    if status not in {"connected", "unavailable", "paused"}:
        raise ValueError("Invalid status")
    checked = datetime.fromisoformat(data["checked_at"])
    if checked.tzinfo is None or (now - checked).total_seconds() < -5:
        raise ValueError("Invalid clock")
    accounts = data.get("accounts", [])
    if not isinstance(accounts, list) or len(accounts) > MAX_ACCOUNTS:
        raise ValueError("Invalid accounts")
    cleaned = []
    for a in accounts:
        masked = label(a["label"], r"Webull account ••••[A-Za-z0-9_-]{1,4}", 32)
        currency = label(a["currency"], r"[A-Z]{3}", 3)
        positions = a["positions"]
        if not isinstance(positions, list) or len(positions) > MAX_POSITIONS:
            raise ValueError("Invalid positions")
        clean = normalize_account(
            masked[-4:],
            {"total_asset_currency": currency, **{k: a["balances"].get(k) for k in BALANCES}},
            [
                {
                    "position_id": str(i),
                    **{k: p.get(k) for k in (*POSITION_FIELDS, "symbol", "currency")},
                    "instrument_type": p.get("kind"),
                }
                for i, p in enumerate(positions)
            ],
        )
        clean["label"] = masked
        cleaned.append(clean)
    success = None
    if data.get("last_success"):
        success = datetime.fromisoformat(data["last_success"])
        if success.tzinfo is None or success > checked:
            raise ValueError("Invalid success time")
    if status == "connected" and (success != checked or not cleaned):
        raise ValueError("Incomplete successful snapshot")
    stale = success is None or (now - success).total_seconds() > 900
    return {
        "health": "Stale" if status == "connected" and stale else status.capitalize(),
        "checked_at": checked.astimezone(UTC).isoformat(),
        "last_success": success.astimezone(UTC).isoformat() if success else None,
        "stale": stale or status != "connected",
        "accounts": cleaned,
        "balance_labels": BALANCES,
    }


def read_snapshot(path: Path, *, now: datetime | None = None) -> dict[str, Any]:
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("Snapshot cap exceeded")
        return project_snapshot(json.loads(raw), now=now)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {
            "health": "Unavailable",
            "checked_at": None,
            "last_success": None,
            "stale": True,
            "accounts": [],
            "balance_labels": BALANCES,
        }
