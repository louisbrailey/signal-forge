"""Human-reviewed production actions, isolated from the automated strategy registry.

Shared admission protocol: one unresolved write per provider/environment/account,
across applications. No lease, expiry, retry, or takeover of an uncertain admission.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ProductionRefusal(RuntimeError):
    """Safe operator-facing refusal; never contains provider bodies or credentials."""


class Action(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    action_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    provider: Literal["coinbase", "webull"]
    environment: Literal["production"] = "production"
    account_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    original_action_id: str = Field(default="", pattern=r"^(?:[a-f0-9]{32})?$")
    fee_policy: Literal["require_provider_cap", "accept_rechecked_estimate"] = (
        "require_provider_cap"
    )
    fee_estimate_ceiling: Decimal = Decimal(0)
    debit_admission_ceiling: Decimal = Decimal(0)
    headroom: Decimal = Decimal(0)
    fee_currency: str = Field(default="", pattern=r"^[A-Z0-9]*$")
    debit_currency: str = Field(default="", pattern=r"^[A-Z0-9]*$")
    kind: Literal["order", "protective_close", "cancel", "transfer"]
    expires_at: datetime
    asset: str = Field(default="", pattern=r"^[A-Z0-9.-]*$")
    quantity: Decimal = Decimal(0)
    limit_price: Decimal = Decimal(0)
    max_debit: Decimal = Decimal(0)
    max_fee: Decimal = Decimal(0)
    side: Literal["BUY", "SELL"] = "BUY"
    instrument_type: Literal["SPOT", "EQUITY"] = "SPOT"
    quantity_unit: Literal["base", "shares"] = "base"
    time_in_force: Literal["GTD", "DAY"] = "GTD"
    order_id: str = Field(default="", pattern=r"^[A-Za-z0-9_-]*$")
    destination: str = Field(default="", pattern=r"^[A-Za-z0-9_-]*$")
    network: Literal["internal_portfolio"] = "internal_portfolio"

    @model_validator(mode="before")
    @classmethod
    def canonical_identity(cls, value: Any) -> Any:
        if isinstance(value, dict) and value.get("provider") == "coinbase":
            value = dict(value)
            for key in ("account_id", "destination"):
                if value.get(key):
                    value[key] = str(uuid.UUID(value[key]))
        return value

    def accounts(self) -> tuple[str, ...]:
        return (
            tuple(sorted({self.account_id, self.destination}))
            if self.kind == "transfer"
            else (self.account_id,)
        )

    @field_validator(
        "quantity",
        "limit_price",
        "max_debit",
        "max_fee",
        "fee_estimate_ceiling",
        "debit_admission_ceiling",
        "headroom",
        mode="before",
    )
    @classmethod
    def finite(cls, value: Any) -> Decimal:
        if isinstance(value, (bool, float)):
            raise ValueError("use exact decimal strings")
        number = Decimal(value)
        if not number.is_finite() or number < 0:
            raise ValueError("amounts must be finite and non-negative")
        return number

    @model_validator(mode="after")
    def valid_action(self) -> Action:
        if self.original_action_id and (
            self.kind != "cancel" or self.original_action_id == self.action_id
        ):
            raise ValueError("only cancellation may reference a different original action")
        if self.fee_policy == "accept_rechecked_estimate":
            if self.kind not in {"order", "protective_close"}:
                raise ValueError("estimate contract applies only to orders")
            if self.max_fee or self.max_debit:
                raise ValueError("estimate policy cannot promise hard fee/debit caps")
            if not self.fee_currency or not self.debit_currency:
                raise ValueError("explicit fee/debit currencies required")
            needed = (
                (self.quantity * self.limit_price if self.side == "BUY" else Decimal(0))
                + self.fee_estimate_ceiling
                + self.headroom
            )
            if self.debit_admission_ceiling < needed:
                raise ValueError("admission ceiling must cover limit notional, fees and headroom")
        elif self.fee_estimate_ceiling or self.debit_admission_ceiling or self.headroom:
            raise ValueError("estimate terms require explicit estimate-policy opt in")
        if self.expires_at.tzinfo is None:
            raise ValueError("expiry must carry timezone")
        if self.kind == "cancel":
            if not self.order_id or self.quantity or self.max_debit or self.max_fee:
                raise ValueError("cancel needs exact order id and no economic amount")
        else:
            if not self.asset or self.quantity <= 0:
                raise ValueError("asset and positive quantity required")
            if self.kind == "transfer":
                if self.provider != "coinbase":
                    raise ValueError("Webull retail transfers unsupported; Broker API is separate")
                if not self.destination or self.destination == self.account_id:
                    raise ValueError("distinct destination portfolio required")
                if self.max_debit != self.quantity or self.max_fee != 0:
                    raise ValueError("internal transfer requires exact debit and zero fees")
            else:
                if self.limit_price <= 0:
                    raise ValueError("only bounded LIMIT orders supported")
                expected = (
                    ("SPOT", "base", "GTD")
                    if self.provider == "coinbase"
                    else ("EQUITY", "shares", "DAY")
                )
                if (self.instrument_type, self.quantity_unit, self.time_in_force) != expected:
                    raise ValueError("unsupported instrument, quantity units, or TIF")
                if self.provider == "webull" and self.quantity != self.quantity.to_integral_value():
                    raise ValueError("fractional equity orders unsupported")
                if self.kind == "protective_close" and self.side != "SELL":
                    raise ValueError("protective close only reduces a proven long holding")
                if self.side == "SELL" and self.kind != "protective_close":
                    raise ValueError("sell must be a verified protective close; no short opening")
                if (
                    self.fee_policy == "require_provider_cap"
                    and self.max_debit < self.quantity * self.limit_price + self.max_fee
                ):
                    raise ValueError("maximum debit must cover limit notional plus fee limit")
        return self

    def canonical(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.canonical().encode()).hexdigest()

    def confirmation(self, token: str) -> str:
        return f"CONFIRM {self.provider} production {self.account_id} {self.digest()} {token}"


def default_admission_path() -> Path:
    return Path.home() / "Library/Application Support/BrokerAccess/admission.sqlite3"


class AdmissionLedger:
    """Cross-app table is deliberately the six-column protocol agreed with TradePilot.

    The private review table contains no credentials or raw broker responses. The
    confirmation secret is hashed; review terms cannot be updated or deleted.
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = path
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS broker_admission (
                    provider TEXT, environment TEXT, account_id TEXT,
                    action_id TEXT, owner TEXT, state TEXT,
                    PRIMARY KEY(provider,environment,account_id)
                );
                CREATE TABLE IF NOT EXISTS sf_broker_review (
                    action_id TEXT PRIMARY KEY, terms TEXT NOT NULL, digest TEXT NOT NULL,
                    token_hash TEXT NOT NULL, state TEXT NOT NULL,
                    outcome_id TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS sf_broker_cancel (
                    parent_action_id TEXT PRIMARY KEY, child_action_id TEXT UNIQUE NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sf_broker_evidence (
                    action_id TEXT NOT NULL, observed_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS sf_review_immutable
                BEFORE UPDATE OF terms,digest,token_hash,action_id ON sf_broker_review
                BEGIN SELECT RAISE(ABORT,'immutable review'); END;
                CREATE TRIGGER IF NOT EXISTS sf_review_no_delete
                BEFORE DELETE ON sf_broker_review
                BEGIN SELECT RAISE(ABORT,'immutable review'); END;
            """)
        path.chmod(0o600)

    @contextmanager
    def connect(self):  # type: ignore[no-untyped-def]
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        try:
            yield db
        except BaseException:
            if db.in_transaction:
                db.rollback()
            raise
        finally:
            db.close()

    def save(self, action: Action) -> str:
        token = secrets.token_hex(16)
        with self.connect() as db:
            try:
                db.execute(
                    "INSERT INTO sf_broker_review VALUES (?,?,?,?,?,?)",
                    (
                        action.action_id,
                        action.canonical(),
                        action.digest(),
                        hashlib.sha256(token.encode()).hexdigest(),
                        "REVIEWED",
                        "",
                    ),
                )
            except sqlite3.IntegrityError:
                raise ProductionRefusal(
                    "action id already exists; no replacement or retry"
                ) from None
        return token

    def read(self, action_id: str) -> tuple[Action, str, str]:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM sf_broker_review WHERE action_id=?", (action_id,)
            ).fetchone()
        if row is None:
            raise ProductionRefusal("unknown review")
        action = Action.model_validate_json(row["terms"])
        if not hmac.compare_digest(action.digest(), row["digest"]):
            raise ProductionRefusal("review integrity failure")
        return action, row["state"], row["outcome_id"]

    def reserve(self, action: Action, confirmation: str, now: datetime) -> None:
        # Validate confirmation and consume it in the same transaction as admission.
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM sf_broker_review WHERE action_id=?", (action.action_id,)
            ).fetchone()
            token = confirmation.rsplit(" ", 1)[-1]
            if (
                row is None
                or row["state"] != "REVIEWED"
                or row["terms"] != action.canonical()
                or not hmac.compare_digest(
                    row["token_hash"], hashlib.sha256(token.encode()).hexdigest()
                )
                or not hmac.compare_digest(action.confirmation(token), confirmation)
                or action.expires_at <= now
            ):
                raise ProductionRefusal("expired, consumed, changed, or unconfirmed review")
            if action.original_action_id:
                parent = db.execute(
                    "SELECT * FROM sf_broker_review WHERE action_id=?", (action.original_action_id,)
                ).fetchone()
                hold = db.execute(
                    "SELECT * FROM broker_admission WHERE provider=? "
                    "AND environment='production' AND account_id=?",
                    (action.provider, action.account_id),
                ).fetchone()
                if parent is None or hold is None:
                    raise ProductionRefusal("original order hold missing")
                original = Action.model_validate_json(parent["terms"])
                if (
                    hold["owner"] != "signalforge"
                    or hold["action_id"] != original.action_id
                    or parent["state"] not in {"ACKNOWLEDGED", "UNKNOWN"}
                    or original.kind not in {"order", "protective_close"}
                    or original.account_id != action.account_id
                    or original.provider != action.provider
                    or (
                        action.provider == "coinbase"
                        and parent["outcome_id"]
                        and parent["outcome_id"] != action.order_id
                    )
                    or (action.provider == "webull" and action.order_id != original.action_id)
                ):
                    raise ProductionRefusal("cancel must bind an owned unresolved original order")
                try:
                    db.execute(
                        "INSERT INTO sf_broker_cancel VALUES (?,?)",
                        (original.action_id, action.action_id),
                    )
                except sqlite3.IntegrityError:
                    raise ProductionRefusal(
                        "original order already has an unresolved cancel"
                    ) from None
            else:
                try:
                    for account in action.accounts():
                        db.execute(
                            "INSERT INTO broker_admission VALUES (?,?,?,?,?,?)",
                            (
                                action.provider,
                                "production",
                                account,
                                action.action_id,
                                "signalforge",
                                "RESERVED",
                            ),
                        )
                except sqlite3.IntegrityError:
                    raise ProductionRefusal(
                        "account has an unresolved write; no takeover or retry"
                    ) from None
            db.execute(
                "UPDATE sf_broker_review SET state='RESERVED' WHERE action_id=?",
                (action.action_id,),
            )
            db.commit()

    def transition(self, action: Action, state: str, outcome_id: str = "") -> None:
        if state not in {"SUBMITTING", "UNKNOWN", "ACKNOWLEDGED", "REFUSED", "RESOLVED"}:
            raise ProductionRefusal("invalid admission transition")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM broker_admission "
                "WHERE provider=? AND environment=? AND account_id=?",
                (action.provider, "production", action.account_id),
            ).fetchone()
            hold_id = action.original_action_id or action.action_id
            if row is None or row["owner"] != "signalforge" or row["action_id"] != hold_id:
                raise ProductionRefusal("admission ownership mismatch")
            review_row = db.execute(
                "SELECT state FROM sf_broker_review WHERE action_id=?", (action.action_id,)
            ).fetchone()
            if action.original_action_id:
                guard = db.execute(
                    "SELECT child_action_id FROM sf_broker_cancel WHERE parent_action_id=?",
                    (hold_id,),
                ).fetchone()
                if guard is None or guard[0] != action.action_id:
                    raise ProductionRefusal("cancellation ownership mismatch")
            allowed = {
                "RESERVED": {"SUBMITTING", "REFUSED"},
                "SUBMITTING": {"UNKNOWN", "ACKNOWLEDGED"},
                "UNKNOWN": {"RESOLVED"},
                "ACKNOWLEDGED": {"RESOLVED"},
            }
            if state not in allowed.get(review_row["state"], set()):
                raise ProductionRefusal("invalid admission state transition")
            db.execute(
                "UPDATE sf_broker_review SET state=?,outcome_id=? WHERE action_id=?",
                (state, outcome_id, action.action_id),
            )
            if action.original_action_id:
                if state in {"REFUSED", "RESOLVED"}:
                    db.execute(
                        "DELETE FROM sf_broker_cancel WHERE child_action_id=?", (action.action_id,)
                    )
                if state == "RESOLVED":
                    db.execute(
                        "UPDATE sf_broker_review SET state='RESOLVED' WHERE action_id=?", (hold_id,)
                    )
                    db.execute(
                        "DELETE FROM broker_admission WHERE action_id=? AND owner='signalforge'",
                        (hold_id,),
                    )
            elif state in {"REFUSED", "RESOLVED"}:
                guard = db.execute(
                    "SELECT child_action_id FROM sf_broker_cancel WHERE parent_action_id=?",
                    (hold_id,),
                ).fetchone()
                if guard is not None:
                    raise ProductionRefusal("resolve the outstanding cancellation first")
                db.execute(
                    "DELETE FROM broker_admission WHERE action_id=? AND owner='signalforge'",
                    (hold_id,),
                )
            else:
                db.execute(
                    "UPDATE broker_admission SET state=? WHERE action_id=? AND owner='signalforge'",
                    (state, hold_id),
                )
            db.commit()

    def evidence(self, action: Action, payload: dict[str, Any], now: datetime) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO sf_broker_evidence VALUES (?,?,?)",
                (action.action_id, now.isoformat(), json.dumps(payload, sort_keys=True)),
            )

    def finish_transfer(self, action: Action, evidence: dict[str, Any], now: datetime) -> None:
        if (
            action.kind != "transfer"
            or evidence.get("action_digest") != action.digest()
            or evidence.get("source_portfolio_uuid") != action.account_id
            or evidence.get("target_portfolio_uuid") != action.destination
            or evidence.get("http_status") != 200
        ):
            raise ProductionRefusal(
                "synchronous transfer evidence does not match immutable request"
            )
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            holds = db.execute(
                "SELECT account_id,state FROM broker_admission "
                "WHERE action_id=? AND owner='signalforge'",
                (action.action_id,),
            ).fetchall()
            if {r["account_id"] for r in holds} != set(action.accounts()) or any(
                r["state"] != "SUBMITTING" for r in holds
            ):
                raise ProductionRefusal("transfer admission ownership mismatch")
            db.execute(
                "INSERT INTO sf_broker_evidence VALUES (?,?,?)",
                (action.action_id, now.isoformat(), json.dumps(evidence, sort_keys=True)),
            )
            db.execute(
                "UPDATE sf_broker_review SET state='RESOLVED',outcome_id=? "
                "WHERE action_id=? AND state='SUBMITTING'",
                (action.action_id, action.action_id),
            )
            db.execute(
                "DELETE FROM broker_admission WHERE action_id=? AND owner='signalforge'",
                (action.action_id,),
            )
            db.commit()

    def abort_unsent(self, action_id: str) -> None:
        action, state, _ = self.read(action_id)
        if state != "RESERVED":
            raise ProductionRefusal("only a definitively pre-send RESERVED action can be abandoned")
        # Competes atomically with SUBMITTING; the losing sender cannot proceed.
        self.transition(action, "REFUSED")


def submit_review(
    ledger: AdmissionLedger,
    action_id: str,
    confirmation: str,
    broker: Any,
    *,
    enabled: bool = False,
    transfers_enabled: bool = False,
    kill_active: Callable[[], bool],
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> str:
    """One local operator action, never called from strategy, app, or scheduler.

    Admission is durable before *any* preflight. Read-only preflight failures are
    definitively unsent and consume the review. After SUBMITTING, every error is
    UNKNOWN. Process death leaves RESERVED/SUBMITTING blocking other applications.
    """
    action, _, _ = ledger.read(action_id)
    if not enabled or (action.kind == "transfer" and not transfers_enabled):
        raise ProductionRefusal("production actions/transfers disabled")
    if broker.provider != action.provider or broker.account_id != action.account_id:
        raise ProductionRefusal("configured account differs from review")
    ledger.reserve(action, confirmation, now())
    try:
        if action.original_action_id:
            original, _, _ = ledger.read(action.original_action_id)
            broker.cancel_original = original
        broker.preflight(action)
        ledger.evidence(action, getattr(broker, "preflight_evidence", {}), now())
        if action.expires_at <= now():
            raise ProductionRefusal("review expired during preflight")
        if action.kind in {"order", "transfer"} and kill_active():
            raise ProductionRefusal("kill switch blocks opening and transfers")
    except Exception:
        ledger.transition(action, "REFUSED")
        raise ProductionRefusal("preflight refused; review consumed; no write sent") from None
    ledger.transition(action, "SUBMITTING")
    try:
        outcome_id = broker.send(action)
        if action.kind == "transfer":
            ledger.finish_transfer(action, broker.send_evidence, now())
            return (
                "RESOLVED — provider confirmed synchronous internal transfer; local action id "
                + action.action_id
            )
        ledger.transition(action, "ACKNOWLEDGED", outcome_id)
    except Exception:
        ledger.transition(action, "UNKNOWN")
        return "UNKNOWN — account held; never retry based on missing lookup"
    # ACK is not fill/settlement. Keep hold until authoritative read resolution.
    return "ACKNOWLEDGED — account held pending authoritative reconciliation"


def reconcile_review(
    ledger: AdmissionLedger,
    action_id: str,
    broker: Any,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> str:
    action, state, outcome_id = ledger.read(action_id)
    if state not in {"UNKNOWN", "ACKNOWLEDGED", "SUBMITTING"}:
        raise ProductionRefusal("no sent action to reconcile")
    if broker.provider != action.provider or broker.account_id != action.account_id:
        raise ProductionRefusal("reconciliation account mismatch")
    original = None
    if action.original_action_id:
        original, _, _ = ledger.read(action.original_action_id)
        broker.cancel_original = original
    if not broker.reconcile(action, outcome_id):
        return "No authoritative terminal evidence; hold retained. Do not retry."
    evidence = dict(broker.reconciliation_evidence)
    if original is not None:
        if not broker.reconcile(original, action.order_id):
            return "Original execution costs unresolved; hold retained."
        evidence["original_execution"] = dict(broker.reconciliation_evidence)
        evidence["original_action_digest"] = original.digest()
    ledger.evidence(action, evidence, now())
    if state == "SUBMITTING":
        ledger.transition(action, "UNKNOWN")
    ledger.transition(action, "RESOLVED")
    return "RESOLVED — authoritative terminal evidence; " + json.dumps(evidence, sort_keys=True)
