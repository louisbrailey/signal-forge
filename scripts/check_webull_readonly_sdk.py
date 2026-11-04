"""Offline transport proof for installed SDK 3.0.0; synthetic secrets, zero sockets.

Run with PYTHONPATH=src and the existing Webull SDK interpreter. No private
configuration, account, token or provider endpoint is read/contacted.
"""

import contextlib
import io
import json
import logging
import os
import socket
import tempfile
import time
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from signalforge.execution.brokers.webull_readonly import response_data, sdk_reader


@contextlib.contextmanager
def working_directory(path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def assert_transport(observed):
    assert observed["method"] == "GET"
    assert observed["scheme"] == "https" and observed["host"] == "api.webull.com"
    assert observed["redirects"] is False and observed["verify"] is True
    assert observed["timeout"] == (10, 15)


def check():
    marker = "SYNTHETIC-NEVER-A-REAL-CREDENTIAL"
    captured = io.StringIO()
    # All socket paths are forbidden even if a mock ceases to match.
    with (
        patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")),
        patch.dict(os.environ, {"WEBULL_API_DEBUG": "sdk", "WEBULL_LIVE_TRADING": ""}),
        contextlib.redirect_stdout(captured),
        contextlib.redirect_stderr(captured),
        tempfile.TemporaryDirectory() as tmp,
        working_directory(Path(tmp)),
    ):
        import requests

        root = Path(tmp)
        token = root / "webull-tokens/production/token.txt"
        token.parent.mkdir(parents=True)
        token.write_text(marker + "\n" + str(int(time.time()) + 3600) + "\nNORMAL\n")
        token.chmod(0o600)
        config = root / "config.json"
        config.write_text(
            json.dumps(
                {
                    "WEBULL_ENV": "production",
                    "TRADEPILOT_RUNTIME": str(root),
                    "WEBULL_APP_KEY": marker,
                    "WEBULL_APP_SECRET": marker,
                }
            )
        )
        config.chmod(0o600)
        original = (config.read_bytes(), token.read_bytes())
        calls = []

        def send(_session, prepared, **kwargs):
            calls.append(
                {
                    "method": prepared.method,
                    "scheme": urlsplit(prepared.url).scheme,
                    "host": urlsplit(prepared.url).hostname,
                    "redirects": kwargs.get("allow_redirects"),
                    "verify": kwargs.get("verify"),
                    "timeout": kwargs.get("timeout"),
                }
            )
            response = requests.Response()
            response.status_code = 302
            response.headers["Location"] = "https://attacker.invalid/collect"
            response._content = json.dumps({"error": marker}).encode()
            return response

        reader = sdk_reader(config, root / "kill")
        assert not hasattr(reader, "order")
        with patch.object(requests.Session, "send", send):
            try:
                response_data(reader.get_account_list())
            except Exception:
                assert calls  # Neither SDK nor caller may disclose exception text.
            else:
                raise AssertionError("Redirect unexpectedly accepted")
        assert len(calls) == 1  # No redirect, retry, authentication or order request.
        assert_transport(calls[0])  # Outside the expected SDK-failure handler.
        # Negative controls: every unsafe transport mutation must actually fail.
        for field, value in (
            ("method", "POST"),
            ("scheme", "http"),
            ("host", "attacker.invalid"),
            ("redirects", True),
            ("verify", False),
            ("timeout", (0, 0)),
        ):
            try:
                assert_transport({**calls[0], field: value})
            except AssertionError:
                continue
            raise AssertionError("Unsafe transport negative control passed")
        with patch.object(requests.Session, "send", side_effect=OSError(marker)) as fault:
            try:
                reader.get_account_list()
            except Exception:
                assert fault.call_count == 1
            else:
                raise AssertionError("Injected transport failure not observed")
            assert fault.call_count == 1
        assert original == (config.read_bytes(), token.read_bytes())
        assert not list(root.rglob("*.log"))
    logging.disable(logging.NOTSET)
    assert marker not in captured.getvalue()
    print(
        "PASS: pinned SDK GET-only transport; redirects refused; TLS verified; no retries; "
        "debug/error output redacted; credentials unchanged; zero sockets"
    )


if __name__ == "__main__":
    check()
