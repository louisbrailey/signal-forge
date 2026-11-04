"""The one HTTPS transport the vendor sandbox adapters may be handed.

This module lives **outside** the execution package on purpose. The
execution package imports no HTTP client (a property its posture tests assert
over the whole import graph), and D6-A says the vendor adapter speaks plain
REST over ``httpx`` with no vendor SDK. Both hold at once by putting the
client here and injecting it: the adapter describes a request, this module
sends it, and the CLI — the only sanctioned importer of the execution layer —
is where the two meet.

What it refuses, each for a reason:

* a non-``https`` scheme — never built, the request carries no scheme at all;
* a redirect — ``follow_redirects=False``, and a 3xx is returned as-is so the
  adapter's §13 proof sees a host it did not expect and fails;
* an unbounded wait — every request carries the adapter's explicit timeout.

It imports nothing from the execution package and names no brokerage host.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx

__all__ = ["HttpResponse", "HttpxTransport", "RequestLike"]


class RequestLike(Protocol):
    """The attributes of the execution package's ``VendorRequest``, stated
    structurally so this module needs no import from that package."""

    @property
    def method(self) -> str: ...

    @property
    def host(self) -> str: ...

    @property
    def path(self) -> str: ...

    @property
    def query(self) -> tuple[tuple[str, str], ...]: ...

    @property
    def headers(self) -> tuple[tuple[str, str], ...]: ...

    @property
    def body(self) -> str | None: ...

    @property
    def timeout_s(self) -> float: ...


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    body: str
    #: The host the response actually came from — read from the response URL,
    #: not echoed from the request, so the adapter's proof is of the wire.
    host: str


class HttpxTransport:
    """A synchronous, redirect-refusing, timeout-bounded ``httpx`` client."""

    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        # ``transport`` exists for tests (``httpx.MockTransport``); production
        # passes nothing and gets the default connection pool.
        self._client = httpx.Client(follow_redirects=False, transport=transport)

    def __call__(self, request: RequestLike) -> HttpResponse:
        url = httpx.URL(
            scheme="https",
            host=request.host,
            path=request.path,
            query=httpx.QueryParams(list(request.query)).__str__().encode() or None,
        )
        content: Any = request.body.encode("utf-8") if request.body is not None else None
        response = self._client.request(
            request.method,
            url,
            headers=dict(request.headers),
            content=content,
            timeout=httpx.Timeout(request.timeout_s),
        )
        return HttpResponse(
            status=response.status_code,
            body=response.text,
            host=response.url.host,
        )

    def close(self) -> None:
        self._client.close()
