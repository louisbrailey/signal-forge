"""``signalforge.sandbox_http`` — the one HTTPS transport, under a mock."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from signalforge.sandbox_http import HttpxTransport


@dataclass(frozen=True)
class Req:
    method: str
    host: str
    path: str
    query: tuple[tuple[str, str], ...] = ()
    headers: tuple[tuple[str, str], ...] = ()
    body: str | None = None
    timeout_s: float = 3.0


def test_sends_https_with_query_headers_body_and_reports_the_wire_host() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    transport = HttpxTransport(transport=httpx.MockTransport(handler))
    response = transport(
        Req(
            "POST",
            "sandbox.example.invalid",
            "/v1/thing",
            query=(("a", "1"), ("b", "x y")),
            headers=(("x-test", "1"), ("Content-Type", "application/json")),
            body='{"k":"v"}',
        )
    )
    (request,) = seen
    assert request.url.scheme == "https"
    assert request.url.host == "sandbox.example.invalid"
    assert request.url.path == "/v1/thing"
    assert dict(request.url.params) == {"a": "1", "b": "x y"}
    assert request.headers["x-test"] == "1"
    assert request.content == b'{"k":"v"}'
    assert (response.status, response.body, response.host) == (
        200,
        '{"ok":true}',
        "sandbox.example.invalid",
    )


def test_a_redirect_is_returned_not_followed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://elsewhere.invalid/"})

    transport = HttpxTransport(transport=httpx.MockTransport(handler))
    response = transport(Req("GET", "sandbox.example.invalid", "/"))
    assert response.status == 302
    assert response.host == "sandbox.example.invalid"
