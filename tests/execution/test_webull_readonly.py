import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from signalforge.account_view import MAX_BYTES, normalize_account, project_snapshot, read_snapshot
from signalforge.execution.brokers import webull_readonly as export

UTC = UTC
STAMP = "2026-11-04T02:00:00+00:00"


def balance():
    return {
        "total_asset_currency": "USD",
        "total_net_liquidation_value": "123.40",
        "total_cash_balance": "123.40",
        "secret": "private-sentinel",  # pragma: allowlist secret
    }


def record():
    return {
        "schema": "webull-readonly-v1",
        "environment": "production",
        "trading_enabled": False,
        "checked_at": STAMP,
        "last_success": STAMP,
        "status": "connected",
        "accounts": [normalize_account("ACCOUNT1234", balance(), [])],
    }


class Response:
    status_code = 200
    content = b"bounded"

    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


class Reader:
    def __init__(self):
        self.calls = []

    def get_account_list(self):
        self.calls.append("accounts")
        return Response([{"account_id": "ACCOUNT1234"}])

    def get_account_balance(self, account):
        self.calls.append("balance")
        return Response(balance())

    def get_account_position(self, account):
        self.calls.append("positions")
        return Response([])


def request(path="/trading/accounts/list", method="GET", version="v3", protocol="https"):
    return SimpleNamespace(
        get_method=lambda: method,
        get_action_name=lambda: path,
        get_version=lambda: version,
        get_protocol_type=lambda: protocol,
        get_body_params=lambda: None,
    )


@pytest.mark.safety
def test_only_three_read_endpoints_no_orders_redirect_hosts_or_http():
    for path in export.READ_PATHS:
        export.validate_request(export.HOST, request(path))
    for host, req in (
        (export.HOST, request("/trade/order/place")),
        (export.HOST, request(method="POST")),
        (export.HOST, request(version="v1")),
        (export.HOST, request(protocol="http")),
        ("attacker.invalid", request()),
    ):
        with pytest.raises(export.ReadRefused):
            export.validate_request(host, req)


def test_actual_read_projection_masks_ids_and_drops_unknown_fields(tmp_path):
    reader = Reader()
    accounts = export.collect(reader, tmp_path / "kill.json")
    assert reader.calls == ["accounts", "balance", "positions"]
    assert accounts[0]["positions"] == []
    assert accounts[0]["balances"]["total_market_value"] is None
    assert "ACCOUNT1234" not in json.dumps(accounts)
    assert "private-sentinel" not in json.dumps(accounts)


@pytest.mark.safety
def test_kill_switch_before_and_during_collection(tmp_path):
    path = tmp_path / "kill.json"
    path.write_text('{"active":true}')
    reader = Reader()
    with pytest.raises(export.ReadRefused):
        export.collect(reader, path)
    assert not reader.calls
    path.write_text(json.dumps({"active": False, "changed_at": STAMP}))

    def first_call():
        path.write_text('{"active":true}')
        return Response([{"account_id": "ACCOUNT1234"}])

    reader.get_account_list = first_call
    with pytest.raises(export.ReadRefused):
        export.collect(reader, path)
    assert not reader.calls
    path.write_text("malformed")
    with pytest.raises(export.ReadRefused):
        export.ensure_read_allowed(path)


@pytest.mark.parametrize("changed", [None, "bad-date", "2026-11-04T02:00:00", 123])
def test_kill_switch_timestamp_matches_canonical_fail_closed(tmp_path, changed):
    path = tmp_path / "kill.json"
    path.write_text(json.dumps({"active": False, "changed_at": changed}))
    with pytest.raises(export.ReadRefused):
        export.ensure_read_allowed(path)


def test_oversized_aggregate_publishes_failure_without_losing_last_good(tmp_path, monkeypatch):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    output = root / "snapshot.json"
    monkeypatch.setattr(export, "sdk_reader", lambda *_: Reader())
    assert export.run(tmp_path / "unused", output, tmp_path / "kill") == 0
    original = json.loads(output.read_text())
    reader = Reader()
    reader.get_account_position = lambda _: Response(
        [
            {
                "position_id": str(i),
                "symbol": "AAPL",
                "quantity": "1",
                "last_price": "100",
                "cost_price": "95",
                "unrealized_profit_loss": "5",
                "instrument_type": "EQUITY",
                "currency": "USD",
            }
            for i in range(200)
        ]
    )
    monkeypatch.setattr(export, "MAX_BYTES", 16_000)
    monkeypatch.setattr(export, "sdk_reader", lambda *_: reader)
    assert export.run(tmp_path / "unused", output, tmp_path / "kill") == 1
    failed = json.loads(output.read_text())
    assert failed["status"] == "unavailable" and failed["accounts"] == original["accounts"]
    assert failed["last_success"] == original["last_success"]


def test_atomic_private_snapshot_and_retained_last_good_on_failure(tmp_path, monkeypatch, capsys):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    output = root / "snapshot.json"
    monkeypatch.setattr(export, "sdk_reader", lambda *_: Reader())
    assert export.run(tmp_path / "not-read", output, tmp_path / "kill") == 0
    saved = json.loads(output.read_text())
    assert output.stat().st_mode & 0o077 == 0

    def broken(*_):
        raise ValueError("private-sentinel")

    monkeypatch.setattr(export, "sdk_reader", broken)
    assert export.run(tmp_path / "not-read", output, tmp_path / "kill") == 1
    failed = json.loads(output.read_text())
    assert failed["status"] == "unavailable"
    assert (
        failed["last_success"] == saved["last_success"] and failed["accounts"] == saved["accounts"]
    )
    assert "private-sentinel" not in output.read_text() + capsys.readouterr().out


@pytest.mark.parametrize("value", ["NaN", "Infinity", "1e999999", True, "1e-999999"])
def test_bad_numbers_refused(value):
    with pytest.raises(ValueError):
        normalize_account("ACCOUNT1234", {**balance(), "total_cash_balance": value}, [])


def test_projection_stale_future_missing_and_unexpected_metadata(tmp_path):
    r = record()
    r["secret"] = "private-sentinel"  # pragma: allowlist secret
    assert project_snapshot(r, now=datetime(2026, 11, 4, 2, 1, tzinfo=UTC))["health"] == "Connected"
    assert project_snapshot(r, now=datetime(2026, 11, 4, 3, tzinfo=UTC))["health"] == "Stale"
    with pytest.raises(ValueError):
        project_snapshot(r, now=datetime(2026, 11, 3, tzinfo=UTC))
    output = tmp_path / "snapshot.json"
    assert read_snapshot(output)["health"] == "Unavailable"
    output.write_text("x" * (MAX_BYTES + 1))
    assert read_snapshot(output)["health"] == "Unavailable"
    r["trading_enabled"] = True
    with pytest.raises(ValueError):
        project_snapshot(r)


def test_missing_token_and_insecure_config_do_not_start_auth(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"WEBULL_ENV": "production", "TRADEPILOT_RUNTIME": str(tmp_path)}))
    config.chmod(0o644)
    with pytest.raises(export.ReadRefused):
        export.sdk_reader(config, tmp_path / "kill")
    config.chmod(0o600)
    with pytest.raises(FileNotFoundError):
        export.sdk_reader(config, tmp_path / "kill")
    config.write_text('{"WEBULL_LIVE_TRADING":"enabled"}')
    with pytest.raises(export.ReadRefused):
        export.sdk_reader(config, tmp_path / "kill")
