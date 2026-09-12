"""Provider-agnostic LLM client (optional dependency).

The system is fully functional without an LLM. ``build_client`` returns ``None``
when no provider/key is configured or the SDK is missing, and every caller must
degrade gracefully to "no narrative".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from signalforge.config import get_settings
from signalforge.observability import get_logger

_log = get_logger("llm.client")
_DEFAULT_MAX_TOKENS = 900


@dataclass(frozen=True, slots=True)
class LlmResult:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int


class LlmClient(Protocol):
    model: str

    def complete(
        self, *, system: str, prompt: str, max_tokens: int = _DEFAULT_MAX_TOKENS
    ) -> LlmResult: ...


class AnthropicClient:
    def __init__(self, api_key: str, model: str) -> None:
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def complete(
        self, *, system: str, prompt: str, max_tokens: int = _DEFAULT_MAX_TOKENS
    ) -> LlmResult:
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(
            getattr(block, "text", "")
            for block in resp.content
            if getattr(block, "type", "") == "text"
        )
        usage = getattr(resp, "usage", None)
        return LlmResult(
            text=text,
            model=self.model,
            prompt_tokens=getattr(usage, "input_tokens", 0) or 0,
            completion_tokens=getattr(usage, "output_tokens", 0) or 0,
        )


class OpenAICompatClient:
    """Any OpenAI-compatible ``/v1/chat/completions`` server — used for LM Studio
    on this Mac (local 27-31B models). Deterministic settings (temperature 0),
    hidden reasoning disabled by default, and ``<think>`` blocks stripped so the
    grounding guard only ever sees the final answer. No key required locally."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str = "",
        reasoning_effort: str = "none",
        timeout_s: float = 120.0,
    ) -> None:
        import httpx

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"), headers=headers, timeout=timeout_s
        )
        self.model = model
        self._reasoning_effort = reasoning_effort

    def complete(
        self, *, system: str, prompt: str, max_tokens: int = _DEFAULT_MAX_TOKENS
    ) -> LlmResult:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": 0,
        }
        if self._reasoning_effort:
            payload["reasoning_effort"] = self._reasoning_effort
        resp = self._client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices") or []
        text = str(((choices[0] if choices else {}).get("message") or {}).get("content") or "")
        text = _strip_think(text)
        usage = data.get("usage") or {}
        return LlmResult(
            text=text,
            model=str(data.get("model") or self.model),
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
        )


def _strip_think(text: str) -> str:
    """Drop any ``<think>…</think>`` reasoning block a local model may emit."""
    import re

    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def build_client() -> LlmClient | None:
    settings = get_settings()
    provider = settings.llm_provider.strip().lower()
    key = settings.llm_api_key.get_secret_value()
    if provider in {"lmstudio", "openai_compat", "openai-compatible"}:
        try:
            return OpenAICompatClient(
                base_url=settings.llm_base_url,
                model=settings.llm_model,
                api_key=key,
                reasoning_effort=settings.llm_reasoning_effort,
                timeout_s=settings.llm_timeout_s,
            )
        except ImportError:
            _log.warning("llm.sdk_missing", provider=provider, hint="httpx is required")
            return None
    if not provider or not key:
        return None
    if provider in {"anthropic", "claude"}:
        try:
            return AnthropicClient(api_key=key, model=settings.llm_model or "claude-sonnet-5")
        except ImportError:
            _log.warning(
                "llm.sdk_missing", provider=provider, hint="pip install 'signalforge[llm]'"
            )
            return None
    _log.warning("llm.unknown_provider", provider=provider)
    return None
