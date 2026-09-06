"""Provider-agnostic LLM client (optional dependency).

Phase 0: interface only. The Anthropic-backed implementation (default model
``claude-sonnet-5``) lands with the daily-briefing work in Phase 1 §1.11 and is
import-guarded so a missing ``anthropic`` package or key degrades gracefully to
"no narrative".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class LlmResult:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int


class LlmClient(Protocol):
    def complete(self, *, system: str, prompt: str, max_tokens: int) -> LlmResult: ...


def build_client() -> LlmClient | None:  # pragma: no cover - Phase 1
    raise NotImplementedError("LLM client is implemented in Phase 1 (§1.11).")
