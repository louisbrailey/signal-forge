"""Explicit, isolated account snapshot exporter. Three allowlisted GET endpoints.

Runs in the existing official Webull SDK environment (Python 3.9+). Reads the
operator's existing private TradePilot store; never creates or refreshes tokens.
The app reads the sanitized snapshot only and cannot import this module.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import io
import json
import logging
import os
import stat
import tempfile
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any

from signalforge.account_view import MAX_ACCOUNTS, MAX_BYTES, normalize_account, project_snapshot

# Compatible with the installed SDK environment, without changing its packages.
# ruff: noqa: UP017
UTC = timezone.utc
HOST = "api.webull.com"
READ_PATHS = frozenset(
    {
        "/trading/accounts/list",
        "/trading/assets/balances/get",
        "/trading/assets/positions/list",
    }
)


class ReadRefused(Exception):
    """Fixed category only; never includes response bodies, credentials or account IDs."""


def private_text(path: Path) -> str:
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ReadRefused("private_file_permissions")
        raw = stream.read(65537)
        if len(raw) > 65536:
            raise ReadRefused("private_file_size")
    return raw.decode()


def ensure_read_allowed(kill_path: Path) -> None:
    if kill_path.is_symlink():
        raise ReadRefused("emergency_stop_unavailable")
    if not kill_path.exists():
        return  # Same initial-install policy as Signal Forge's kill switch.
    try:
        with kill_path.open("rb") as f:
            raw = f.read(16385)
        if len(raw) > 16384:
            raise ReadRefused("emergency_stop_unavailable")
        data = json.loads(raw)
        changed = datetime.fromisoformat(data["changed_at"].replace("Z", "+00:00"))
        if changed.tzinfo is None or changed.utcoffset() is None:
            raise ReadRefused("emergency_stop_unavailable")
        if data.get("active") is not False:
            raise ReadRefused("emergency_stop")
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise ReadRefused("emergency_stop_unavailable") from None


def validate_request(endpoint: str, request: Any) -> None:
    if (
        endpoint != HOST
        or request.get_method() != "GET"
        or request.get_action_name() not in READ_PATHS
        or request.get_version() != "v3"
        or request.get_protocol_type().lower() != "https"
        or request.get_body_params()
    ):
        raise ReadRefused("read_only_endpoint_guard")


def sdk_reader(config_path: Path, kill_path: Path) -> Any:
    """No TradeClient/initializer: those can initiate MFA or refresh saved tokens."""
    logging.disable(logging.CRITICAL)  # Isolated process, including SDK HTTP debug logging.
    values = json.loads(private_text(config_path))
    if values.get("WEBULL_ENV") != "production" or values.get("WEBULL_LIVE_TRADING") == "enabled":
        raise ReadRefused("production_reads_require_trading_disabled")
    if os.environ.get("WEBULL_LIVE_TRADING") == "enabled":
        raise ReadRefused("production_reads_require_trading_disabled")
    runtime = Path(values["TRADEPILOT_RUNTIME"])
    lines = private_text(runtime / "webull-tokens/production/token.txt").splitlines()
    if len(lines) < 3 or not lines[0] or lines[2] != "NORMAL":
        raise ReadRefused("operator_authentication_required")
    expiry = int(lines[1] or "0")
    expiry_seconds = expiry / 1000 if expiry > 100_000_000_000 else expiry
    if expiry and expiry_seconds <= datetime.now(UTC).timestamp():
        raise ReadRefused("operator_authentication_required")
    if version("webull-openapi-python-sdk") != "3.0.0":
        raise ReadRefused("sdk_version_requires_review")
    from webull.core.client import ApiClient  # type: ignore[import-not-found]
    from webull.trade.trade.v2.account_info_v2 import AccountV2  # type: ignore[import-not-found]

    class ReadOnlyClient(ApiClient):
        def _make_http_response(
            self, endpoint: str, request: Any, *args: Any, **kwargs: Any
        ) -> Any:
            ensure_read_allowed(kill_path)
            validate_request(endpoint, request)
            return super()._make_http_response(endpoint, request, *args, **kwargs)

    client = ReadOnlyClient(
        values["WEBULL_APP_KEY"],
        values["WEBULL_APP_SECRET"],
        "us",
        auto_retry=False,
        timeout=15,
        connect_timeout=10,
        verify=True,
    )
    client.set_stream_logger(log_level=logging.CRITICAL + 1, stream=io.StringIO())
    client.add_endpoint("us", HOST)
    client.set_token(lines[0])
    return AccountV2(client)


def response_data(response: Any) -> Any:
    if response.status_code != 200:
        raise ReadRefused("provider_read_unavailable")
    if len(response.content) > MAX_BYTES:
        raise ReadRefused("provider_response_cap")
    return response.json()


def collect(reader: Any, kill_path: Path) -> list[dict[str, Any]]:
    ensure_read_allowed(kill_path)
    accounts = response_data(reader.get_account_list())
    if not isinstance(accounts, list) or not 1 <= len(accounts) <= MAX_ACCOUNTS:
        raise ReadRefused("account_list_incomplete")
    output = []
    seen = set()
    for account in accounts:
        account_id = account["account_id"]
        if not isinstance(account_id, str) or account_id in seen:
            raise ReadRefused("account_list_incomplete")
        seen.add(account_id)
        ensure_read_allowed(kill_path)
        balance = response_data(reader.get_account_balance(account_id))
        ensure_read_allowed(kill_path)
        positions = response_data(reader.get_account_position(account_id))
        output.append(normalize_account(account_id, balance, positions))
    ensure_read_allowed(kill_path)
    return output


def publish(path: Path, data: dict[str, Any]) -> None:
    # No journal, portfolio, ledger, study database or raw provider cache writes.
    project_snapshot(data)
    raw = json.dumps(data).encode()
    if len(raw) > MAX_BYTES:
        raise ReadRefused("snapshot_cap")
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
        temporary = Path(f.name)
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def run(config: Path, output: Path, kill_path: Path) -> int:
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if output.parent.stat().st_mode & 0o077 or output.parent.stat().st_uid != os.getuid():
        raise ReadRefused("snapshot_directory_permissions")
    with (output.parent / "collector.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        prior = {}
        if output.exists():
            try:
                with output.open("rb") as f:
                    raw = f.read(MAX_BYTES + 1)
                if len(raw) <= MAX_BYTES:
                    prior = project_snapshot(json.loads(raw))
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                pass
        data = {
            "schema": "webull-readonly-v1",
            "environment": "production",
            "trading_enabled": False,
            "status": "unavailable",
            "checked_at": datetime.now(UTC).isoformat(),
            "last_success": prior.get("last_success"),
            "accounts": prior.get("accounts", []),
        }
        code = 1
        category = "read_unavailable"
        try:
            ensure_read_allowed(kill_path)
            accounts = collect(sdk_reader(config, kill_path), kill_path)
            stamp = datetime.now(UTC).isoformat()
            successful = {
                **data,
                "status": "connected",
                "accounts": accounts,
                "checked_at": stamp,
                "last_success": stamp,
            }
            project_snapshot(successful)
            # Reserve space for a later failure status. Do this BEFORE replacing
            # last-good data so an oversize aggregate is an explicit failed refresh.
            if len(json.dumps(successful).encode()) > MAX_BYTES - 256:
                raise ReadRefused("snapshot_cap")
            data = successful
            code, category = 0, "none"
        except ReadRefused as e:
            category = str(e)  # Our fixed messages only; never SDK exception strings.
            if category.startswith("emergency_stop"):
                data["status"] = "paused"
        except Exception:
            category = "read_unavailable"  # SDK exception strings can contain credentials.
        publish(output, data)
        print(
            json.dumps(
                {
                    "status": data["status"],
                    "error_category": category,
                    "account_count": len(data["accounts"]),
                    "checked_at": data["checked_at"],
                }
            )
        )
        return code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--kill-switch", type=Path, required=True)
    parser.add_argument("--allow-account-reads", action="store_true")
    args = parser.parse_args()
    if not args.allow_account_reads:
        parser.error("Account reads require explicit --allow-account-reads; trading stays disabled")
    logging.disable(logging.CRITICAL)
    # Vendor stdout/stderr is suppressed; only our fixed status is emitted afterward.
    captured = io.StringIO()
    try:
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(io.StringIO()):
            code = run(args.private_config, args.output, args.kill_switch)
        # run prints only the fixed summary; SDK is configured never to log.
        summary = captured.getvalue().splitlines()[-1:]
        if summary:
            value = json.loads(summary[0])
            print(
                json.dumps(
                    {
                        k: value[k]
                        for k in ("status", "error_category", "account_count", "checked_at")
                    }
                )
            )
        return code
    except Exception:
        print('{"status":"unavailable","error_category":"collector_unavailable"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
