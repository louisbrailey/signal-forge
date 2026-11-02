"""Shared shapes for the vendor **sandbox** adapters (D6 §3, §13, §16).

A vendor adapter in this package never opens a socket itself. It builds a
:class:`VendorRequest` and hands it to a *transport* supplied by the caller —
in production, the ``httpx``-backed one in ``signalforge.sandbox_http``, wired
by the CLI; in tests, a fake that answers from canned bodies. That keeps the
import-posture invariants intact: nothing under ``signalforge.execution``
imports an HTTP client, and the one place a brokerage host literal may appear
is still this package (§19 T5).

The transport reports the **host it actually connected to** on every
response. The §13 proof reads that, not the host the adapter asked for, so a
transport that followed a redirect somewhere else fails the proof.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from signalforge.observability import redact

__all__ = [
    "EXCERPT_LIMIT",
    "Transport",
    "VendorAdapterError",
    "VendorRequest",
    "VendorResponse",
    "excerpt",
    "parse_json",
    "strict_number",
]

#: The most of a broker body that may ever be stored in an audit payload.
EXCERPT_LIMIT = 240


class VendorAdapterError(RuntimeError):
    """The broker answered in a shape the adapter refuses to interpret.

    Fail-closed: an unparseable body is never coerced into a state. The caller
    maps this to ``UNKNOWN`` (for a submission that may have reached the
    broker) or to a refusal (for a read), never to a success.
    """


@dataclass(frozen=True, slots=True)
class VendorRequest:
    """One HTTPS request, fully described, with no secret in it.

    Signing headers are added by the adapter *before* the request is built, so
    a transport sees the final header set. The App Secret itself never becomes
    a header: it only keys the HMAC.
    """

    method: str
    host: str
    path: str
    query: tuple[tuple[str, str], ...] = ()
    headers: tuple[tuple[str, str], ...] = ()
    body: str | None = None
    timeout_s: float = 15.0


@runtime_checkable
class VendorResponse(Protocol):
    """What a transport returns. ``host`` is the host actually reached."""

    @property
    def status(self) -> int: ...

    @property
    def body(self) -> str: ...

    @property
    def host(self) -> str: ...


@dataclass(frozen=True, slots=True)
class CannedResponse:
    """A concrete :class:`VendorResponse`, used by tests and by error paths."""

    status: int
    body: str
    host: str
    headers: Mapping[str, str] = field(default_factory=dict)


class Transport(Protocol):
    """``request -> response``; raises on a transport-level failure (timeout,
    connection refused). The adapter treats a raise after a submission as the
    §8 hazard — the order MAY have reached the broker — and reports UNKNOWN."""

    def __call__(self, request: VendorRequest) -> VendorResponse: ...


def parse_json(body: str) -> Any:
    try:
        return json.loads(body)
    except (TypeError, ValueError) as exc:
        raise VendorAdapterError(f"broker body is not JSON: {type(exc).__name__}") from None


def excerpt(text: str, limit: int = EXCERPT_LIMIT) -> str:
    """A bounded, redacted slice of a broker body for an audit payload."""
    redacted = redact(text)
    value = redacted if isinstance(redacted, str) else str(redacted)
    return value[:limit]


def strict_number(value: object, *, what: str) -> float:
    """A finite number from a broker field, or :class:`VendorAdapterError`.

    Brokers send numbers as strings. ``bool`` is excluded on purpose, and
    NaN/inf are refused: a quantity that is not a number is not a quantity.
    """
    if isinstance(value, bool) or value is None:
        raise VendorAdapterError(f"{what} is missing or not a number")
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise VendorAdapterError(f"{what} is not a number") from None
    if not math.isfinite(number):
        raise VendorAdapterError(f"{what} is not finite")
    return number
