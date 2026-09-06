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


def build_client() -> LlmClient | None:
    settings = get_settings()
    provider = settings.llm_provider.strip().lower()
    key = settings.llm_api_key.get_secret_value()
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
