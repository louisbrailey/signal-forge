"""An agent must never hold a write transaction across its LLM narrative call."""

from __future__ import annotations

from sqlalchemy.orm import Session

from signalforge.agents import base as base_mod
from signalforge.agents.operations import OperationsAgent


def test_run_drops_write_intent_before_collect_and_rearms_for_persist(
    session: Session, monkeypatch
) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(base_mod, "set_write_intent", lambda _s, flag: calls.append(flag))
    res = OperationsAgent().run(session)
    assert res.status in {"ok", "failed"}
    assert calls == [False, True]
