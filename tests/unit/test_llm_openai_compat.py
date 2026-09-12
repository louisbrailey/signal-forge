"""OpenAI-compatible (LM Studio) LLM client: deterministic payload, think-block stripping,
no key required for a local provider, and the grounding guard still applies downstream."""

from __future__ import annotations

import json

import httpx
import pytest

from signalforge.llm.client import OpenAICompatClient, _strip_think


def _client(handler) -> OpenAICompatClient:  # type: ignore[no-untyped-def]
    c = OpenAICompatClient(base_url="http://lmstudio.test/v1", model="google/gemma-4-31b")
    c._client = httpx.Client(
        base_url="http://lmstudio.test/v1", transport=httpx.MockTransport(handler)
    )
    return c


def test_complete_posts_deterministic_payload_and_parses_usage() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "google/gemma-4-31b",
                "choices": [{"message": {"role": "assistant", "content": "SPY finished higher."}}],
                "usage": {"prompt_tokens": 52, "completion_tokens": 7},
            },
        )

    res = _client(handler).complete(system="sys", prompt="facts", max_tokens=80)
    assert seen["path"] == "/v1/chat/completions"
    body = seen["body"]
    assert body["temperature"] == 0 and body["max_tokens"] == 80
    assert body["reasoning_effort"] == "none"
    assert body["messages"][0] == {"role": "system", "content": "sys"}
    assert (
        res.text == "SPY finished higher."
        and res.prompt_tokens == 52
        and res.completion_tokens == 7
    )


def test_think_blocks_are_stripped() -> None:
    assert _strip_think("<think>secret reasoning 123</think>\nThe answer.") == "The answer."

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "<think>x 99</think>Calm markets."}}],
                "usage": {},
            },
        )

    assert _client(handler).complete(system="s", prompt="p").text == "Calm markets."


def test_http_error_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "loading"})

    with pytest.raises(httpx.HTTPStatusError):
        _client(handler).complete(system="s", prompt="p")


def test_local_provider_needs_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from signalforge.config import settings as settings_mod

    st = settings_mod.Settings(llm_provider="lmstudio", llm_api_key="")
    assert st.llm_enabled is True
    st2 = settings_mod.Settings(llm_provider="anthropic", llm_api_key="")
    assert st2.llm_enabled is False
