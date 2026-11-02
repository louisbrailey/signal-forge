"""Production contract and cross-app admission tests. Every provider is a fake."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import SecretStr, ValidationError
from typer.testing import CliRunner

from signalforge.cli import app
from signalforge.execution.brokers.production import ProductionBroker, webull_headers
from signalforge.execution.brokers.vendor_base import CannedResponse
from signalforge.execution.credentials import CredentialRef, CredentialSource
from signalforge.execution.production import (
    Action,
    AdmissionLedger,
    ProductionRefusal,
    submit_review,
)

NOW = datetime(2026, 11, 2, tzinfo=UTC)
ACCOUNT = "00000000-0000-4000-8000-000000000001"
DEST = "00000000-0000-4000-8000-000000000002"
REF = CredentialRef(CredentialSource.ENV, "TEST_REFERENCE")


def action(**changes):
    return Action.model_validate(
        {
            "action_id": "a" * 32,
            "provider": "coinbase",
            "account_id": ACCOUNT,
            "kind": "cancel",
            "order_id": "order-1",
            "expires_at": NOW + timedelta(minutes=5),
            **changes,
        }
    )


def save(ledger, review):
    return review.confirmation(ledger.save(review))


class BrokerFake:
    provider = "coinbase"
    account_id = ACCOUNT

    def __init__(self, failure=False):
        self.failure = failure
        self.sent = 0

    def preflight(self, review):
        pass

    def send(self, review):
        self.sent += 1
        if self.failure:
            raise TimeoutError("DO NOT EXPOSE PRIVATE TRANSPORT VALUE")
        return "order-1"


def run(ledger, review, confirmation, broker, **kwargs):
    return submit_review(
        ledger,
        review.action_id,
        confirmation,
        broker,
        enabled=True,
        kill_active=lambda: False,
        now=lambda: NOW,
        **kwargs,
    )


def test_default_off_has_no_network_or_reservation(tmp_path):
    ledger = AdmissionLedger(tmp_path / "shared.db")
    review = action()
    confirmation = save(ledger, review)
    broker = BrokerFake()
    with pytest.raises(ProductionRefusal, match="disabled"):
        submit_review(
            ledger,
            review.action_id,
            confirmation,
            broker,
            kill_active=lambda: False,
            now=lambda: NOW,
        )
    assert broker.sent == 0
    assert ledger.read(review.action_id)[1] == "REVIEWED"


@pytest.mark.parametrize(
    "mutation", ["wrong-token", "wrong-digest", "expired", "different-account"]
)
def test_confirmation_identity_and_expiry(tmp_path, mutation):
    ledger = AdmissionLedger(tmp_path / "shared.db")
    review = action(expires_at=NOW if mutation == "expired" else NOW + timedelta(minutes=5))
    confirmation = save(ledger, review)
    if mutation == "wrong-token":
        confirmation += "X"
    if mutation == "wrong-digest":
        confirmation = confirmation.replace(review.digest(), "0" * 64)
    broker = BrokerFake()
    if mutation == "different-account":
        broker.account_id = DEST
    with pytest.raises(ProductionRefusal):
        run(ledger, review, confirmation, broker)
    assert broker.sent == 0


def test_unknown_is_durable_nonretryable_and_cross_action_blocking(tmp_path):
    path = tmp_path / "shared.db"
    ledger = AdmissionLedger(path)
    review = action()
    confirmation = save(ledger, review)
    broker = BrokerFake(failure=True)
    assert run(ledger, review, confirmation, broker).startswith("UNKNOWN")
    reopened = AdmissionLedger(path)
    with pytest.raises(ProductionRefusal):
        run(reopened, review, confirmation, broker)
    other = action(
        action_id="b" * 32,
        kind="transfer",
        order_id="",
        asset="USD",
        quantity="1",
        max_debit="1",
        destination=DEST,
    )
    with pytest.raises(ProductionRefusal, match="unresolved"):
        run(reopened, other, save(reopened, other), broker, transfers_enabled=True)
    assert broker.sent == 1
    assert reopened.read(review.action_id)[1] == "UNKNOWN"


def test_atomic_confirmation_only_one_sender(tmp_path):
    ledger = AdmissionLedger(tmp_path / "shared.db")
    review = action()
    confirmation = save(ledger, review)
    broker = BrokerFake()

    def attempt(_):
        try:
            return run(ledger, review, confirmation, broker)
        except ProductionRefusal:
            return "refused"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert results.count("refused") == 1
    assert broker.sent == 1


def test_presend_durable_and_no_sqlite_transaction_during_transport(tmp_path):
    ledger = AdmissionLedger(tmp_path / "shared.db")
    review = action()
    broker = BrokerFake()

    def send(_):
        with sqlite3.connect(ledger.path, timeout=0.1) as db:
            db.execute("BEGIN IMMEDIATE")
            assert db.execute("SELECT state FROM broker_admission").fetchone()[0] == "SUBMITTING"
        return "order-1"

    broker.send = send
    run(ledger, review, save(ledger, review), broker)
    assert ledger.read(review.action_id)[1] == "ACKNOWLEDGED"


def test_review_immutable_and_duplicate_id_refused(tmp_path):
    ledger = AdmissionLedger(tmp_path / "shared.db")
    review = action()
    save(ledger, review)
    with pytest.raises(ProductionRefusal):
        ledger.save(review)
    with ledger.connect() as db, pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE sf_broker_review SET terms='{}'")


def test_transfer_gates_and_dual_account_hold(tmp_path):
    ledger = AdmissionLedger(tmp_path / "shared.db")
    review = action(
        kind="transfer", order_id="", asset="USD", quantity="5", max_debit="5", destination=DEST
    )
    confirmation = save(ledger, review)
    broker = BrokerFake()
    with pytest.raises(ProductionRefusal, match="disabled"):
        run(ledger, review, confirmation, broker)
    run(ledger, review, confirmation, broker, transfers_enabled=True)
    with ledger.connect() as db:
        assert {r[0] for r in db.execute("SELECT account_id FROM broker_admission")} == {
            ACCOUNT,
            DEST,
        }


@pytest.mark.parametrize("kind,blocked", [("cancel", False), ("transfer", True)])
def test_kill_recheck_after_preflight(tmp_path, kind, blocked):
    ledger = AdmissionLedger(tmp_path / "shared.db")
    review = (
        action()
        if kind == "cancel"
        else action(
            kind=kind, order_id="", asset="USD", quantity="1", max_debit="1", destination=DEST
        )
    )
    confirmation = save(ledger, review)
    broker = BrokerFake()
    killed = False

    def preflight(_):
        nonlocal killed
        killed = True

    broker.preflight = preflight
    if blocked:
        with pytest.raises(ProductionRefusal, match="preflight"):
            submit_review(
                ledger,
                review.action_id,
                confirmation,
                broker,
                enabled=True,
                transfers_enabled=True,
                kill_active=lambda: killed,
                now=lambda: NOW,
            )
        assert broker.sent == 0
    else:
        submit_review(
            ledger,
            review.action_id,
            confirmation,
            broker,
            enabled=True,
            kill_active=lambda: killed,
            now=lambda: NOW,
        )
        assert broker.sent == 1


def test_process_death_retains_admission(tmp_path):
    ledger = AdmissionLedger(tmp_path / "shared.db")
    review = action()
    broker = BrokerFake()
    broker.send = Mock(side_effect=KeyboardInterrupt)
    with pytest.raises(KeyboardInterrupt):
        run(ledger, review, save(ledger, review), broker)
    assert AdmissionLedger(ledger.path).read(review.action_id)[1] == "SUBMITTING"


def test_cross_implementation_shared_ledger(tmp_path):
    """Loads the actual sibling implementation, not a local imitation.

    Local integration gate; CI skips only if the separate private checkout is absent.
    """
    path = Path(
        "/Users/louisbrailey/Projects/tradepilot/.worktrees/full-access-implementation/server/broker_admission.py"
    )
    if not path.exists():
        pytest.skip("separate TradePilot checkout absent")
    spec = importlib.util.spec_from_file_location("tradepilot_admission_contract", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    shared = tmp_path / "shared.db"
    tp = module.AdmissionLedger(shared)
    sf = AdmissionLedger(shared)
    tp.reserve("coinbase", "production", [ACCOUNT], "tp-action")
    tp.transition("tp-action", "SUBMITTING")
    tp.transition("tp-action", "UNKNOWN")
    review = action()
    confirmation = save(sf, review)
    with pytest.raises(ProductionRefusal, match="unresolved"):
        run(AdmissionLedger(shared), review, confirmation, BrokerFake())
    tp.release("tp-action")  # Test fixture: authoritative resolution simulated.
    run(sf, review, confirmation, BrokerFake(failure=True))
    with pytest.raises(module.AdmissionError):
        module.AdmissionLedger(shared).reserve("coinbase", "production", [ACCOUNT], "tp-new")


@pytest.mark.parametrize(
    "fields",
    [
        {"quantity": "NaN"},
        {"quantity": True},
        {"quantity": 1.1},
        {"environment": "sandbox"},
        {"account_id": "wallet-not-portfolio"},
        {"unexpected": "payload"},
        {"kind": "transfer", "provider": "webull"},
    ],
)
def test_action_validation(fields):
    with pytest.raises((ValidationError, ValueError)):
        action(**fields)


def test_canonical_coinbase_identity():
    upper = "ABCDEF00-0000-4000-8000-000000000001"
    assert action(account_id=upper).account_id == upper.lower()


@pytest.fixture
def cb(monkeypatch):
    # Signature tested separately with a generated ephemeral test key; never operator keys.
    monkeypatch.setattr(
        "signalforge.execution.brokers.production.coinbase_jwt", lambda *a: "fake-jwt"
    )
    calls = []
    responses = []

    def transport(request):
        calls.append(request)
        value = responses.pop(0)
        if isinstance(value, BaseException):
            raise value
        if isinstance(value, CannedResponse):
            return value
        return CannedResponse(200, json.dumps(value), "api.coinbase.com")

    broker = ProductionBroker(
        "coinbase",
        ACCOUNT,
        transport,
        REF,
        REF,
        enabled=True,
        resolver=lambda _: SecretStr("fixture"),
        now=lambda: NOW,
    )
    return broker, calls, responses


def permissions(**changes):
    return {
        "portfolio_uuid": ACCOUNT,
        "can_view": True,
        "can_trade": True,
        "can_transfer": True,
        **changes,
    }


def test_identity_attestation_is_not_paper(cb):
    broker, calls, responses = cb
    responses.append(permissions())
    proof = broker.attest()
    assert proof.environment == "production"
    assert proof.account_id == ACCOUNT
    assert not hasattr(broker, "is_paper")
    assert calls[0].path.endswith("key_permissions")


@pytest.mark.parametrize(
    "response",
    [
        permissions(portfolio_uuid=DEST),
        permissions(can_view=False),
        permissions(can_trade="true"),
        CannedResponse(200, "{}", "api-sandbox.coinbase.com"),
        CannedResponse(302, "private-value", "api.coinbase.com"),
    ],
)
def test_identity_origin_permission_failure(cb, response):
    broker, _, responses = cb
    responses.append(response)
    with pytest.raises(ProductionRefusal) as exc:
        broker.attest()
    assert "private-value" not in str(exc.value)


def test_default_disabled_adapter_never_resolves_credentials():
    resolver = Mock()
    broker = ProductionBroker("coinbase", ACCOUNT, Mock(), REF, REF, resolver=resolver)
    with pytest.raises(ProductionRefusal, match="disabled"):
        broker.attest()
    resolver.assert_not_called()


def test_complete_account_pagination(cb):
    broker, calls, responses = cb
    responses.extend(
        [
            permissions(),
            {"accounts": [{"retail_portfolio_id": ACCOUNT}], "has_next": True, "cursor": "next"},
            {"accounts": [{"retail_portfolio_id": ACCOUNT}], "has_next": False},
        ]
    )
    assert len(broker.read("accounts")) == 2
    assert ("cursor", "next") in calls[-1].query


def test_repeated_pagination_refuses(cb):
    broker, _, responses = cb
    responses.extend([permissions(), *[{"accounts": [], "has_next": True, "cursor": "same"}] * 2])
    with pytest.raises(ProductionRefusal, match="cursor"):
        broker.read("accounts")


def test_cancel_exact_account_permission_and_wire(cb):
    broker, calls, responses = cb
    responses.extend(
        [
            permissions(),
            permissions(),
            {"order": {"order_id": "order-1", "retail_portfolio_id": ACCOUNT}},
            {"results": [{"order_id": "order-1", "success": True}]},
        ]
    )
    broker.preflight(action())
    assert broker.send(action()) == "order-1"
    assert calls[-1].path == "/api/v3/brokerage/orders/batch_cancel"
    assert json.loads(calls[-1].body) == {"order_ids": ["order-1"]}


def test_cancel_partial_or_wrong_result_is_unknown(cb):
    broker, _, responses = cb
    responses.append({"results": [{"order_id": "other", "success": True}]})
    with pytest.raises(ProductionRefusal):
        broker.send(action())


def test_empty_reconciliation_never_resolves(cb):
    broker, _, responses = cb
    responses.extend([permissions(), {"order": {}}])
    with pytest.raises(ProductionRefusal):
        broker.reconcile(action())


def test_authoritative_terminal_cancellation(cb):
    broker, _, responses = cb
    responses.extend(
        [
            permissions(),
            {
                "order": {
                    "order_id": "order-1",
                    "retail_portfolio_id": ACCOUNT,
                    "status": "CANCELLED",
                }
            },
        ]
    )
    assert broker.reconcile(action())


def test_transfer_exact_scope_balance_and_payload(cb):
    broker, calls, responses = cb
    review = action(
        kind="transfer", order_id="", asset="USD", quantity="5", max_debit="5", destination=DEST
    )
    responses.extend(
        [
            permissions(),
            permissions(),
            {"orders": [], "has_next": False},
            {"orders": [], "has_next": False},
            permissions(),
            {"portfolios": [{"uuid": DEST}]},
            permissions(),
            {
                "accounts": [
                    {
                        "retail_portfolio_id": ACCOUNT,
                        "currency": "USD",
                        "available_balance": {"value": "10"},
                    }
                ],
                "has_next": False,
            },
            {"source_portfolio_uuid": ACCOUNT, "target_portfolio_uuid": DEST},
        ]
    )
    broker.preflight(review)
    assert broker.send(review) == review.action_id
    assert broker.send_evidence["request_funds"] == {"value": "5", "currency": "USD"}
    body = json.loads(calls[-1].body)
    assert body["source_portfolio_uuid"] == ACCOUNT
    assert body["target_portfolio_uuid"] == DEST
    assert body["funds"] == {"value": "5", "currency": "USD"}
    with pytest.raises(ProductionRefusal, match="hold retained"):
        broker.reconcile(review)


def test_unsupported_order_bounds_cannot_bypass_preflight(cb):
    broker, calls, _ = cb
    review = action(
        kind="order",
        order_id="",
        asset="BTC-USD",
        quantity="1",
        limit_price="5",
        max_debit="6",
        max_fee="1",
    )
    path, body = broker.wire(review)
    assert path.endswith("/orders")
    assert body["client_order_id"] == review.action_id
    with pytest.raises(ProductionRefusal, match="ceiling"):
        broker.send(review)
    assert not calls


def test_webull_signer_official_protocol():
    headers = dict(
        webull_headers(
            SecretStr("fixture-key"),
            SecretStr("fixture-secret"),
            SecretStr("fixture-token"),
            "/trading/accounts/list",
            (),
            None,
            NOW,
            "nonce",
        )
    )
    assert headers["x-signature-algorithm"] == "HMAC-SHA1"
    assert headers["x-access-token"] == "fixture-token"
    assert "fixture-secret" not in repr(headers)


def test_cli_offline_surfaces_and_noninteractive_submit(monkeypatch):
    runner = CliRunner()
    assert runner.invoke(app, ["broker", "capabilities"]).exit_code == 0
    assert runner.invoke(app, ["broker", "schema"]).exit_code == 0
    resolver = Mock(side_effect=AssertionError("must not assemble"))
    monkeypatch.setattr("signalforge.cli._production_broker", resolver)
    result = runner.invoke(app, ["broker", "submit", "a" * 32])
    assert result.exit_code == 1
    assert "trusted local" in result.stdout
    resolver.assert_not_called()


def test_production_not_in_strategy_registry():
    from signalforge.execution.brokers import ADAPTER_NAMES

    assert all("production" not in name for name in ADAPTER_NAMES)


def test_coinbase_jwt_verifies_signature_method_origin_and_lifetime():
    import base64

    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

    from signalforge.execution.brokers.production import coinbase_jwt

    private = ec.generate_private_key(ec.SECP256R1())
    pem = private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    token = coinbase_jwt(SecretStr("fixture-id"), SecretStr(pem), "GET", "/path", NOW, "nonce")
    header, payload, signature = token.split(".")

    def decode(text):
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))

    claims = json.loads(decode(payload))
    assert claims["uri"] == "GET api.coinbase.com/path"
    assert claims["exp"] - claims["nbf"] == 120
    assert json.loads(decode(header))["nonce"] == "nonce"
    raw = decode(signature)
    der = encode_dss_signature(int.from_bytes(raw[:32]), int.from_bytes(raw[32:]))
    private.public_key().verify(der, f"{header}.{payload}".encode(), ec.ECDSA(hashes.SHA256()))


def test_webull_fake_identity_read_cancel_and_redaction():
    calls = []
    answers = [
        [{"account_id": "WB-1", "account_class": "INDIVIDUAL_CASH"}],
        [{"account_id": "WB-1", "account_class": "INDIVIDUAL_CASH"}],
        {"account_id": "WB-1", "client_order_id": "order-1"},
        {"client_order_id": "order-1"},
    ]

    def transport(request):
        calls.append(request)
        return CannedResponse(200, json.dumps(answers.pop(0)), "api.webull.com")

    broker = ProductionBroker(
        "webull",
        "WB-1",
        transport,
        REF,
        REF,
        REF,
        enabled=True,
        resolver=lambda _: SecretStr("fixture-secret-value"),
        now=lambda: NOW,
    )
    review = action(provider="webull", account_id="WB-1")
    with pytest.raises(ProductionRefusal, match="authority unproven"):
        broker.preflight(review)
    assert len(calls) == 1
    assert "fixture-secret-value" not in repr(calls)
    assert "x-access-token" in dict(calls[0].headers)


def test_webull_partial_snapshot_refuses():
    answers = [
        [{"account_id": "WB-1", "account_class": "INDIVIDUAL_CASH"}],
        {"has_next": True, "positions": []},
    ]
    broker = ProductionBroker(
        "webull",
        "WB-1",
        lambda _: CannedResponse(200, json.dumps(answers.pop(0)), "api.webull.com"),
        REF,
        REF,
        REF,
        enabled=True,
        resolver=lambda _: SecretStr("fixture"),
    )
    with pytest.raises(ProductionRefusal, match="incomplete"):
        broker.read("positions")


def test_transfer_destination_conflict_rolls_back_source_reservation(tmp_path):
    ledger = AdmissionLedger(tmp_path / "shared.db")
    with ledger.connect() as db:
        db.execute(
            "INSERT INTO broker_admission VALUES (?,?,?,?,?,?)",
            ("coinbase", "production", DEST, "other", "tradepilot", "UNKNOWN"),
        )
    review = action(
        kind="transfer", order_id="", asset="USD", quantity="1", max_debit="1", destination=DEST
    )
    with pytest.raises(ProductionRefusal, match="unresolved"):
        run(ledger, review, save(ledger, review), BrokerFake(), transfers_enabled=True)
    assert ledger.read(review.action_id)[1] == "REVIEWED"
    with ledger.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM broker_admission").fetchone()[0] == 1


def test_account_snapshot_requires_explicit_pagination_flag(cb):
    broker, _, responses = cb
    responses.extend([permissions(), {"accounts": []}])
    with pytest.raises(ProductionRefusal, match="pagination"):
        broker.read("accounts")


def test_expiry_rechecked_after_slow_preflight(tmp_path):
    ledger = AdmissionLedger(tmp_path / "shared.db")
    review = action()
    broker = BrokerFake()
    clock = iter((NOW, NOW, NOW + timedelta(hours=1)))
    with pytest.raises(ProductionRefusal, match="preflight"):
        submit_review(
            ledger,
            review.action_id,
            save(ledger, review),
            broker,
            enabled=True,
            kill_active=lambda: False,
            now=lambda: next(clock),
        )
    assert broker.sent == 0
    assert ledger.read(review.action_id)[1] == "REFUSED"


def estimate_order(**changes):
    return action(
        kind="order",
        order_id="",
        asset="BTC-USD",
        quantity="1",
        limit_price="5",
        fee_policy="accept_rechecked_estimate",
        fee_estimate_ceiling="1",
        debit_admission_ceiling="7",
        headroom="1",
        fee_currency="USD",
        debit_currency="USD",
        **changes,
    )


def product(**changes):
    return {
        "product_id": "BTC-USD",
        "product_type": "SPOT",
        "status": "online",
        "base_currency_id": "BTC",
        "quote_currency_id": "USD",
        "base_increment": "0.001",
        "base_min_size": "0.001",
        "base_max_size": "100",
        "quote_increment": "0.01",
        **dict.fromkeys(
            ("trading_disabled", "is_disabled", "cancel_only", "view_only", "auction_mode"), False
        ),
        **changes,
    }


def queue_estimate(responses, *, product_data=None, preview=None, orders=None, balances=None):
    responses.extend(
        [
            permissions(),
            permissions(),
            {"orders": orders or [], "has_next": False},
            permissions(),
            product_data or product(),
            permissions(),
            {
                "accounts": (
                    balances
                    if balances is not None
                    else [
                        {
                            "retail_portfolio_id": ACCOUNT,
                            "currency": "USD",
                            "available_balance": {"value": "100", "currency": "USD"},
                        },
                        {
                            "retail_portfolio_id": ACCOUNT,
                            "currency": "BTC",
                            "available_balance": {"value": "2", "currency": "BTC"},
                        },
                    ]
                ),
                "has_next": False,
            },
            (
                preview
                if preview is not None
                else {
                    "preview_id": "preview-1",
                    "errs": [],
                    "warning": [],
                    "commission_total": "0.5",
                    "order_total": "5.5",
                    "commission_detail_total": {"total_commission": "0.5"},
                }
            ),
        ]
    )


def test_real_coinbase_estimate_order_under_durable_admission(cb, tmp_path):
    broker, calls, responses = cb
    ledger = AdmissionLedger(tmp_path / "shared.db")
    review = estimate_order()
    digest = review.digest()
    queue_estimate(responses)
    responses.append(
        {
            "success": True,
            "success_response": {
                "order_id": "order-1",
                "client_order_id": review.action_id,
                "product_id": review.asset,
                "side": "BUY",
            },
        }
    )
    assert run(ledger, review, save(ledger, review), broker).startswith("ACKNOWLEDGED")
    assert json.loads(calls[-1].body)["preview_id"] == "preview-1"
    assert ledger.read(review.action_id)[0].digest() == digest
    with ledger.connect() as db:
        evidence = json.loads(db.execute("SELECT payload FROM sf_broker_evidence").fetchone()[0])
    assert evidence["commission_total"] == "0.5"
    assert evidence["observed_at"] == NOW.isoformat()


@pytest.mark.parametrize(
    "preview",
    [
        {
            "errs": [],
            "preview_id": "x",
            "commission_total": "2",
            "order_total": "6",
            "commission_detail_total": {"total_commission": "2"},
        },
        {
            "errs": [],
            "preview_id": "x",
            "commission_total": "0.5",
            "order_total": "99",
            "commission_detail_total": {"total_commission": "0.5"},
        },
        {"errs": [], "preview_id": "x", "commission_total": "NaN", "order_total": "5.5"},
        {"errs": [], "preview_id": "x", "commission_total": "0.5", "order_total": "5.5"},
        {"errs": ["FAILED"], "preview_id": "x"},
    ],
)
def test_estimates_fail_closed(cb, tmp_path, preview):
    broker, calls, responses = cb
    ledger = AdmissionLedger(tmp_path / "shared.db")
    review = estimate_order()
    queue_estimate(responses, preview=preview)
    with pytest.raises(ProductionRefusal, match="preflight"):
        run(ledger, review, save(ledger, review), broker)
    assert not any(c.path.endswith("/orders") for c in calls)
    assert ledger.read(review.action_id)[1] == "REFUSED"


@pytest.mark.parametrize(
    "field",
    [
        "product_id",
        "status",
        "trading_disabled",
        "is_disabled",
        "view_only",
        "cancel_only",
        "auction_mode",
    ],
)
def test_product_missing_fields_never_admit(cb, field):
    broker, _, responses = cb
    data = product()
    del data[field]
    queue_estimate(responses, product_data=data)
    with pytest.raises(ProductionRefusal, match="eligibility"):
        broker.preflight(estimate_order())


def test_foreign_open_orders_refuse_before_preview(cb):
    broker, calls, responses = cb
    queue_estimate(responses, orders=[{"retail_portfolio_id": ACCOUNT, "status": "OPEN"}])
    with pytest.raises(ProductionRefusal, match="orders block"):
        broker.preflight(estimate_order())
    assert not any(c.method == "POST" for c in calls)


def test_missing_open_order_scope_refuses(cb):
    broker, _, responses = cb
    queue_estimate(responses, orders=[{"status": "FILLED"}])
    with pytest.raises(ProductionRefusal, match="scope"):
        broker.preflight(estimate_order())


def test_preview_stale_at_send(cb):
    broker, calls, responses = cb
    review = estimate_order()
    queue_estimate(responses)
    broker.preflight(review)
    broker._now = lambda: NOW + timedelta(seconds=6)
    with pytest.raises(ProductionRefusal, match="preview expired"):
        broker.send(review)
    assert not any(c.path.endswith("/orders") for c in calls)


def test_sell_requires_separate_quote_fee_funds(cb):
    broker, _, responses = cb
    queue_estimate(
        responses,
        balances=[
            {
                "retail_portfolio_id": ACCOUNT,
                "currency": "BTC",
                "available_balance": {"value": "2", "currency": "BTC"},
            }
        ],
    )
    review = estimate_order().model_copy(update={"kind": "protective_close", "side": "SELL"})
    with pytest.raises(ProductionRefusal, match="separate quote funds"):
        broker.preflight(review)


def test_pre_send_recovery_cannot_release_possible_send(tmp_path):
    ledger = AdmissionLedger(tmp_path / "shared.db")
    review = action()
    ledger.reserve(review, save(ledger, review), NOW)
    ledger.abort_unsent(review.action_id)
    with pytest.raises(ProductionRefusal):
        ledger.transition(review, "SUBMITTING")
    second = action(action_id="b" * 32)
    ledger.reserve(second, save(ledger, second), NOW)
    ledger.transition(second, "SUBMITTING")
    with pytest.raises(ProductionRefusal):
        ledger.abort_unsent(second.action_id)
    assert ledger.read(second.action_id)[1] == "SUBMITTING"


def terminal_order(review, **changes):
    return {
        "order_id": "order-1",
        "retail_portfolio_id": ACCOUNT,
        "client_order_id": review.action_id,
        "product_id": review.asset,
        "side": review.side,
        "order_configuration": {
            "limit_limit_gtd": {
                "base_size": str(review.quantity),
                "limit_price": str(review.limit_price),
                "end_time": review.expires_at.isoformat(),
                "post_only": False,
            }
        },
        "status": "CANCELLED",
        "total_fees": "2",
        "filled_value": "3",
        **changes,
    }


def test_cancel_existing_hold_preserves_parent_costs_and_overruns(cb, tmp_path):
    from signalforge.execution.production import reconcile_review

    broker, _, responses = cb
    ledger = AdmissionLedger(tmp_path / "shared.db")
    original = estimate_order()
    ledger.reserve(original, save(ledger, original), NOW)
    ledger.transition(original, "SUBMITTING")
    ledger.transition(original, "ACKNOWLEDGED", "order-1")
    cancel = action(action_id="b" * 32, original_action_id=original.action_id)
    confirmation = save(ledger, cancel)
    responses.extend(
        [
            permissions(),
            permissions(),
            {"order": terminal_order(original, status="OPEN")},
            {"results": [{"order_id": "order-1", "success": True}]},
        ]
    )
    assert submit_review(
        ledger,
        cancel.action_id,
        confirmation,
        broker,
        enabled=True,
        kill_active=lambda: True,
        now=lambda: NOW,
    ).startswith("ACKNOWLEDGED")
    with ledger.connect() as db:
        assert (
            db.execute("SELECT action_id FROM broker_admission").fetchone()[0] == original.action_id
        )
    responses.extend(
        [
            permissions(),
            {"order": terminal_order(original)},
            permissions(),
            {"order": terminal_order(original)},
        ]
    )
    result = reconcile_review(ledger, cancel.action_id, broker, now=lambda: NOW)
    assert '"fee_overrun": true' in result
    assert ledger.read(original.action_id)[1] == "RESOLVED"
    with ledger.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM broker_admission").fetchone()[0] == 0


def test_cancel_missing_original_fees_does_not_release(cb, tmp_path):
    from signalforge.execution.production import reconcile_review

    broker, _, responses = cb
    ledger = AdmissionLedger(tmp_path / "shared.db")
    original = estimate_order()
    ledger.reserve(original, save(ledger, original), NOW)
    ledger.transition(original, "SUBMITTING")
    ledger.transition(original, "ACKNOWLEDGED", "order-1")
    cancel = action(action_id="b" * 32, original_action_id=original.action_id)
    ledger.reserve(cancel, save(ledger, cancel), NOW)
    ledger.transition(cancel, "SUBMITTING")
    ledger.transition(cancel, "UNKNOWN")
    responses.extend(
        [
            permissions(),
            {"order": terminal_order(original)},
            permissions(),
            {"order": terminal_order(original, total_fees=None)},
        ]
    )
    with pytest.raises(ProductionRefusal):
        reconcile_review(ledger, cancel.action_id, broker)
    assert ledger.read(original.action_id)[1] == "ACKNOWLEDGED"
    with ledger.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM broker_admission").fetchone()[0] == 1


def test_second_cancel_and_other_owner_cannot_borrow_hold(tmp_path):
    ledger = AdmissionLedger(tmp_path / "shared.db")
    original = estimate_order()
    ledger.reserve(original, save(ledger, original), NOW)
    ledger.transition(original, "SUBMITTING")
    ledger.transition(original, "ACKNOWLEDGED", "order-1")
    first = action(action_id="b" * 32, original_action_id=original.action_id)
    ledger.reserve(first, save(ledger, first), NOW)
    second = action(action_id="c" * 32, original_action_id=original.action_id)
    with pytest.raises(ProductionRefusal, match="unresolved cancel"):
        ledger.reserve(second, save(ledger, second), NOW)


def test_transfer_success_record_and_release_are_atomic(tmp_path):
    review = action(
        kind="transfer", order_id="", asset="USD", quantity="1", max_debit="1", destination=DEST
    )
    ledger = AdmissionLedger(tmp_path / "shared.db")
    broker = BrokerFake()
    broker.send_evidence = {
        "action_digest": review.digest(),
        "source_portfolio_uuid": ACCOUNT,
        "target_portfolio_uuid": DEST,
        "http_status": 200,
    }
    assert run(ledger, review, save(ledger, review), broker, transfers_enabled=True).startswith(
        "RESOLVED"
    )
    reopened = AdmissionLedger(ledger.path)
    assert reopened.read(review.action_id)[1] == "RESOLVED"
    with reopened.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM broker_admission").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM sf_broker_evidence").fetchone()[0] == 2


def test_transfer_crash_after_response_before_commit_retains_holds(tmp_path, monkeypatch):
    review = action(
        kind="transfer", order_id="", asset="USD", quantity="1", max_debit="1", destination=DEST
    )
    ledger = AdmissionLedger(tmp_path / "shared.db")
    broker = BrokerFake()
    broker.send_evidence = {}
    monkeypatch.setattr(ledger, "finish_transfer", Mock(side_effect=KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):
        run(ledger, review, save(ledger, review), broker, transfers_enabled=True)
    assert AdmissionLedger(ledger.path).read(review.action_id)[1] == "SUBMITTING"
    with ledger.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM broker_admission").fetchone()[0] == 2


def test_actual_crossapp_uppercase_restart_and_destination_holds(tmp_path):
    path = Path(
        "/Users/louisbrailey/Projects/tradepilot/.worktrees/full-access-implementation/server/broker_admission.py"
    )
    if not path.exists():
        pytest.skip("separate TradePilot checkout absent")
    spec = importlib.util.spec_from_file_location("tradepilot_admission_uppercase", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    upper = "ABCDEF00-0000-4000-8000-000000000001"
    shared = tmp_path / "shared.db"
    tp = module.AdmissionLedger(shared)
    tp.reserve("coinbase", "production", [upper], "tp-action")
    tp.transition("tp-action", "SUBMITTING")
    tp.transition("tp-action", "UNKNOWN")
    sf = AdmissionLedger(shared)
    review = action(account_id=upper)
    with pytest.raises(ProductionRefusal, match="unresolved"):
        sf.reserve(review, save(sf, review), NOW)
    tp.release("tp-action")
    transfer = action(
        action_id="b" * 32,
        kind="transfer",
        account_id=upper,
        order_id="",
        asset="USD",
        quantity="1",
        max_debit="1",
        destination=DEST,
    )
    sf.reserve(transfer, save(sf, transfer), NOW)
    sf.transition(transfer, "SUBMITTING")
    sf.transition(transfer, "UNKNOWN")
    for account_id in (upper, DEST):
        with pytest.raises(module.AdmissionError):
            module.AdmissionLedger(shared).reserve("coinbase", "production", [account_id], "tp-new")
    assert AdmissionLedger(shared).read(transfer.action_id)[1] == "UNKNOWN"


def test_real_webull_equity_estimate_send_and_fee_reconciliation(tmp_path):
    from signalforge.execution.production import reconcile_review

    review = action(
        provider="webull",
        account_id="WB-1",
        kind="order",
        order_id="",
        asset="AAPL",
        instrument_type="EQUITY",
        quantity_unit="shares",
        time_in_force="DAY",
        quantity="1",
        limit_price="5",
        fee_policy="accept_rechecked_estimate",
        fee_estimate_ceiling="1",
        debit_admission_ceiling="7",
        headroom="1",
        fee_currency="USD",
        debit_currency="USD",
    )
    account_row = [{"account_id": "WB-1", "account_class": "INDIVIDUAL_CASH"}]
    answers = [
        account_row,
        account_row,
        {"data": []},
        account_row,
        {
            "total_asset_currency": "USD",
            "account_currency_assets": [
                {"currency": "USD", "settled_cash": "100", "frozen_amount": "1"}
            ],
        },
        {"estimated_cost": "5.5", "estimated_transaction_fee": "0.5"},
        {"client_order_id": review.action_id, "order_id": "wb-order"},
    ]
    calls = []

    def transport(request):
        calls.append(request)
        return CannedResponse(200, json.dumps(answers.pop(0)), "api.webull.com")

    broker = ProductionBroker(
        "webull",
        "WB-1",
        transport,
        REF,
        REF,
        REF,
        enabled=True,
        resolver=lambda _: SecretStr("fixture"),
        now=lambda: NOW,
    )
    ledger = AdmissionLedger(tmp_path / "shared.db")
    assert run(ledger, review, save(ledger, review), broker).startswith("ACKNOWLEDGED")
    assert calls[-1].path == "/trading/orders/place"
    assert json.loads(calls[-1].body)["new_orders"][0]["client_order_id"] == review.action_id
    answers.extend(
        [
            account_row,
            {
                "combo_type": "NORMAL",
                "orders": [
                    {
                        "client_order_id": review.action_id,
                        "order_id": "wb-order",
                        "symbol": "AAPL",
                        "side": "BUY",
                        "order_type": "LIMIT",
                        "time_in_force": "DAY",
                        "entrust_type": "QTY",
                        "instrument_type": "EQUITY",
                        "total_quantity": "1",
                        "limit_price": "5",
                        "status": "FILLED",
                        "filled_quantity": "1",
                        "filled_price": "5",
                        "commission": {"actual_commission": "0.2", "receivable_commission": "0.2"},
                        "fees": [
                            {"type": "REGULATORY", "actual_value": "0.1", "receivable_value": "0.1"}
                        ],
                    }
                ],
            },
        ]
    )
    result = reconcile_review(ledger, review.action_id, broker, now=lambda: NOW)
    assert '"total_fees": "0.3"' in result
    assert ledger.read(review.action_id)[1] == "RESOLVED"


def test_webull_current_cursor_pagination():
    calls = []
    replies = [
        [{"account_id": "WB-1"}],
        {"data": [{"client_order_id": "1"}], "pagination_key": "next"},
        {"data": [{"client_order_id": "2"}]},
    ]

    def transport(request):
        calls.append(request)
        return CannedResponse(200, json.dumps(replies.pop(0)), "api.webull.com")

    broker = ProductionBroker(
        "webull",
        "WB-1",
        transport,
        REF,
        REF,
        REF,
        enabled=True,
        resolver=lambda _: SecretStr("fixture"),
    )
    assert len(broker.read("open-orders")) == 2
    assert ("pagination_key", "next") in calls[-1].query


@pytest.mark.parametrize(
    "response",
    [
        CannedResponse(
            202,
            json.dumps({"source_portfolio_uuid": ACCOUNT, "target_portfolio_uuid": DEST}),
            "api.coinbase.com",
        ),
        {"source_portfolio_uuid": DEST, "target_portfolio_uuid": ACCOUNT},
        {"source_portfolio_uuid": ACCOUNT, "target_portfolio_uuid": DEST, "message": "error"},
        {"source_portfolio_uuid": ACCOUNT, "target_portfolio_uuid": DEST, "errors": []},
        TimeoutError("untrusted secret"),
    ],
)
def test_transfer_ambiguous_response_never_completes(cb, response):
    broker, _, replies = cb
    review = action(
        kind="transfer", order_id="", asset="USD", quantity="1", max_debit="1", destination=DEST
    )
    replies.append(response)
    with pytest.raises(ProductionRefusal):
        broker.send(review)
    assert broker.send_evidence == {}
