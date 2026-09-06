"""The AI narrative pass must be grounded in the frozen facts (S3 / §11)."""

from __future__ import annotations

import pytest

from signalforge.llm.client import LlmResult
from signalforge.llm.explain import explain_briefing
from signalforge.llm.guards import AI_FOOTER

pytestmark = pytest.mark.safety

FACTS = {"no_trade_total": 20, "paper_account": {"equity_estimate": 10000.0}, "warnings": []}
TEXT = "deterministic briefing text"


class _FakeClient:
    model = "fake-model"

    def __init__(self, reply: str) -> None:
        self._reply = reply

    def complete(self, *, system: str, prompt: str, max_tokens: int = 900) -> LlmResult:
        return LlmResult(text=self._reply, model=self.model, prompt_tokens=10, completion_tokens=5)


def test_grounded_narrative_is_accepted() -> None:
    reply = f"20 setups were evaluated and rejected. Paper equity is 10000.0. {AI_FOOTER}"
    res = explain_briefing(FACTS, TEXT, client=_FakeClient(reply))
    assert res is not None and AI_FOOTER in res.text


def test_fabricated_number_is_rejected() -> None:
    reply = f"The model shows a 73% win rate this week. {AI_FOOTER}"
    assert explain_briefing(FACTS, TEXT, client=_FakeClient(reply)) is None


def test_missing_footer_is_rejected() -> None:
    reply = "20 setups were evaluated and rejected."
    assert explain_briefing(FACTS, TEXT, client=_FakeClient(reply)) is None


def test_no_client_means_no_narrative() -> None:
    assert explain_briefing(FACTS, TEXT, client=None) is None


def test_build_and_store_records_an_llm_call_when_narrative_succeeds(
    session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import date

    from sqlalchemy import select

    import signalforge.briefing as briefing_mod
    from signalforge.db.models import LlmCall, PaperAccount

    session.add(PaperAccount(name="default", initial_cash=10_000, cash=10_000))
    session.flush()

    reply = f"Nothing qualified today. {AI_FOOTER}"
    monkeypatch.setattr(
        briefing_mod,
        "explain_briefing",
        lambda *a, **k: _FakeClient(reply).complete(system="", prompt=""),
    )
    payload = briefing_mod.build_and_store_briefing(session, as_of=date(2024, 1, 2))
    assert payload["narrative"] == reply
    assert session.scalars(select(LlmCall)).first() is not None
