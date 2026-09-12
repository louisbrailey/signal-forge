"""Credential resolution — by NAME only (D6 ADR §16).

This module is a prohibition before it is a design.

* Credentials are read **only** from (a) an environment variable, or (b) a macOS
  Keychain item, **by name**. The operator supplies them out of band.
* The system never acquires, stores, writes, rotates, or logs a credential.
  There is no ``security add-generic-password`` here and no write API of any
  kind — this module only reads.
* This file names only env-var names and keychain item names, **never values**,
  and nothing in this package may place a credential in the database, in an
  ``execution_event`` payload, or in a log record.

The one subtle rule, and the reason it is not paranoia: ``redact()`` masks
``pydantic.SecretStr`` **always** and masks values under sensitive key names —
so a plain ``str`` returned from a reader and logged under a neutral key would
be **unredacted by construction**. Therefore the subprocess's stdout is wrapped
in ``SecretStr`` at the call boundary and the plain ``str`` never escapes that
function: not into a local that outlives it, not into an f-string, not into a
log call, not into an exception message. ``stderr`` is read and logged;
``stdout`` is never passed to ``structlog`` under any condition, including
error paths.

A missing or failing source is a **refusal**, never a fallback to a less safe
one.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from enum import StrEnum

from pydantic import SecretStr

from signalforge.observability import get_logger

__all__ = [
    "CredentialRef",
    "CredentialSource",
    "CredentialUnavailable",
    "KEYCHAIN_SERVICE",
    "resolve_credential",
]

_log = get_logger("execution.credentials")

#: The Keychain service name. An ITEM NAME, not a value.
KEYCHAIN_SERVICE = "signalforge-execution"

#: The proposed env-var NAMES (§16). Named here so a review has one place to
#: look; no value of either ever appears in this repository.
ENV_VAR_NAMES: tuple[str, ...] = (
    "SF_EXECUTION_BROKER_KEY_ID",
    "SF_EXECUTION_BROKER_SECRET",
)

_SECURITY_BINARY = "/usr/bin/security"
_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
_LOOKUP_TIMEOUT_S = 10


class CredentialSource(StrEnum):
    ENV = "env"
    KEYCHAIN = "keychain"


class CredentialUnavailable(RuntimeError):
    """The named credential could not be read.

    The message names the SOURCE and the NAME and never the value — including on
    every error path.
    """


@dataclass(frozen=True, slots=True)
class CredentialRef:
    """A reference to a credential by name. Never a value."""

    source: CredentialSource
    name: str
    service: str = KEYCHAIN_SERVICE

    def __post_init__(self) -> None:
        if self.source is CredentialSource.ENV:
            if not _ENV_NAME_RE.match(self.name):
                raise CredentialUnavailable(f"not a valid environment variable name: {self.name!r}")
        elif not _NAME_RE.match(self.name) or not _NAME_RE.match(self.service):
            raise CredentialUnavailable(
                f"not a valid keychain item name: service={self.service!r} account={self.name!r}"
            )

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.source.value}:{self.service}/{self.name}"


def _from_env(ref: CredentialRef) -> SecretStr:
    raw = os.environ.get(ref.name)
    if not raw:
        raise CredentialUnavailable(
            f"environment variable {ref.name} is unset or empty — the operator supplies it "
            "out of band; there is no fallback to a less safe source"
        )
    return SecretStr(raw)


def _from_keychain(ref: CredentialRef) -> SecretStr:
    """``/usr/bin/security find-generic-password -s <service> -a <account> -w``.

    Fixed argument vector, no shell, no interpolation of anything but names that
    have already been validated. stdout goes straight into a ``SecretStr``.
    """
    argv = [
        _SECURITY_BINARY,
        "find-generic-password",
        "-s",
        ref.service,
        "-a",
        ref.name,
        "-w",
    ]
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, validated names, no shell
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=_LOOKUP_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CredentialUnavailable(
            f"keychain lookup failed for {ref.service}/{ref.name}: {type(exc).__name__}"
        ) from None
    if completed.returncode != 0:
        # stderr is safe to log; stdout is NEVER logged, on any path.
        _log.error(
            "execution.credentials.keychain_miss",
            service=ref.service,
            account=ref.name,
            returncode=completed.returncode,
            stderr=(completed.stderr or "").strip()[:200],
        )
        raise CredentialUnavailable(
            f"no keychain item {ref.service}/{ref.name} (rc={completed.returncode})"
        )
    # The plain str exists only inside this expression; it is wrapped here and
    # the local is never re-read, never formatted, never logged.
    secret = SecretStr((completed.stdout or "").rstrip("\n"))
    if not secret.get_secret_value():
        raise CredentialUnavailable(f"keychain item {ref.service}/{ref.name} is empty")
    return secret


def resolve_credential(ref: CredentialRef) -> SecretStr:
    """Read the named credential, or raise :class:`CredentialUnavailable`.

    Returns a ``SecretStr`` so that ``observability.redact`` masks it by type
    wherever it subsequently travels — the established pattern for every secret
    setting in ``config/settings.py``.
    """
    secret = _from_env(ref) if ref.source is CredentialSource.ENV else _from_keychain(ref)
    _log.info(
        "execution.credentials.resolved",
        source=ref.source.value,
        # NAMES only. There is no branch of this module that logs a value.
        service=ref.service if ref.source is CredentialSource.KEYCHAIN else "",
        name=ref.name,
    )
    return secret
