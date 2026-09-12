"""D6 §16 — credentials exist as NAMES only, and a value reaches no log record
and no ``execution_event`` payload.

The rule this file exists to hold: ``redact()`` masks ``SecretStr`` always and
masks values under sensitive KEY names — so a plain ``str`` logged under a
neutral key would be unredacted by construction. The reader therefore wraps the
subprocess's stdout at the call boundary and the plain ``str`` never escapes it.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace
from typing import Any

import pytest
import structlog
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import ExecutionEvent
from signalforge.execution import credentials as creds
from signalforge.execution.events import ExecutionEventType, record_execution_event

SENTINEL = "sentinel-value-that-must-never-be-logged"  # pragma: allowlist secret


def test_an_env_credential_is_returned_as_a_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SF_EXECUTION_BROKER_KEY_ID", SENTINEL)
    ref = creds.CredentialRef(creds.CredentialSource.ENV, "SF_EXECUTION_BROKER_KEY_ID")
    secret = creds.resolve_credential(ref)
    assert isinstance(secret, SecretStr)
    assert secret.get_secret_value() == SENTINEL
    # The established masking pattern applies by TYPE, wherever it travels.
    assert SENTINEL not in str(secret)
    assert SENTINEL not in repr(secret)


def test_a_missing_env_credential_is_a_refusal_not_a_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SF_EXECUTION_BROKER_KEY_ID", raising=False)
    ref = creds.CredentialRef(creds.CredentialSource.ENV, "SF_EXECUTION_BROKER_KEY_ID")
    with pytest.raises(creds.CredentialUnavailable, match="no fallback"):
        creds.resolve_credential(ref)


def test_a_name_that_is_not_a_name_is_rejected() -> None:
    with pytest.raises(creds.CredentialUnavailable):
        creds.CredentialRef(creds.CredentialSource.ENV, "not a var name")
    with pytest.raises(creds.CredentialUnavailable):
        creds.CredentialRef(creds.CredentialSource.KEYCHAIN, "acct; rm -rf /")


def test_the_keychain_reader_uses_a_fixed_argument_vector_and_no_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def fake_run(argv: list[str], **kwargs: Any) -> SimpleNamespace:
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout=SENTINEL + "\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    ref = creds.CredentialRef(creds.CredentialSource.KEYCHAIN, "paper_reference")
    secret = creds.resolve_credential(ref)

    assert secret.get_secret_value() == SENTINEL
    assert seen["argv"] == [
        "/usr/bin/security",
        "find-generic-password",
        "-s",
        creds.KEYCHAIN_SERVICE,
        "-a",
        "paper_reference",
        "-w",
    ]
    assert "shell" not in seen["kwargs"]
    assert seen["kwargs"]["capture_output"] is True


def test_a_missing_keychain_item_is_a_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(_argv: list[str], **_kw: Any) -> SimpleNamespace:
        return SimpleNamespace(returncode=44, stdout="", stderr="item not found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    ref = creds.CredentialRef(creds.CredentialSource.KEYCHAIN, "paper_reference")
    with pytest.raises(creds.CredentialUnavailable, match="no keychain item"):
        creds.resolve_credential(ref)


def test_the_secret_appears_in_no_log_record_on_the_success_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(_argv: list[str], **_kw: Any) -> SimpleNamespace:
        return SimpleNamespace(returncode=0, stdout=SENTINEL + "\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with structlog.testing.capture_logs() as captured:
        creds.resolve_credential(
            creds.CredentialRef(creds.CredentialSource.KEYCHAIN, "paper_reference")
        )
    assert captured, "the reader logs its NAMES, so there is something to inspect"
    assert SENTINEL not in repr(captured)


def test_the_secret_appears_in_no_log_record_on_the_failure_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """stderr is read and logged; stdout is never passed to structlog under any
    condition, including error paths."""

    def fake_run(_argv: list[str], **_kw: Any) -> SimpleNamespace:
        return SimpleNamespace(returncode=1, stdout=SENTINEL, stderr="keychain says no")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with (
        structlog.testing.capture_logs() as captured,
        pytest.raises(creds.CredentialUnavailable) as excinfo,
    ):
        creds.resolve_credential(
            creds.CredentialRef(creds.CredentialSource.KEYCHAIN, "paper_reference")
        )
    assert SENTINEL not in repr(captured)
    assert "keychain says no" in repr(captured)
    assert SENTINEL not in str(excinfo.value)


def test_a_secret_in_an_execution_event_payload_is_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SF_EXECUTION_BROKER_SECRET", SENTINEL)
    secret = creds.resolve_credential(
        creds.CredentialRef(creds.CredentialSource.ENV, "SF_EXECUTION_BROKER_SECRET")
    )
    # This is the second line of defence, not the first: §16's rule is that the
    # value never leaves the reader's call boundary at all.
    from signalforge.observability import redact

    masked = redact({"broker_secret": secret, "nested": [secret]})
    assert SENTINEL not in repr(masked)


def test_a_redacted_payload_reaches_the_table(session: Session) -> None:
    record_execution_event(
        session,
        event_type=ExecutionEventType.IS_PAPER_PROOF,
        adapter_name="paper_reference",
        payload={"api_key": SENTINEL, "observed_account_id": "PAPER-1"},
    )
    row = session.scalars(select(ExecutionEvent)).one()
    assert SENTINEL not in repr(row.payload_json)
    assert row.payload_json["observed_account_id"] == "PAPER-1"


def test_no_credential_value_is_ever_written_by_this_module() -> None:
    """The module reads only: no ``add-generic-password``, no write API, no
    rotation. Asserted over the string literals the code actually USES —
    docstrings, which name the prohibited calls in order to prohibit them, are
    excluded."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(creds))
    docstrings = {
        ast.get_docstring(node, clean=False)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.FunctionDef | ast.ClassDef)
    }
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value not in docstrings
    }
    for forbidden in ("add-generic-password", "delete-generic-password", "set_password"):
        assert not any(forbidden in lit for lit in literals)
    assert any(lit == "find-generic-password" for lit in literals)
