"""Daily-briefing orchestrator.

Ties the deterministic assembly (:mod:`signalforge.research.briefing`) to the
optional LLM narrative (:mod:`signalforge.llm.explain`). This module lives at the
top level precisely so it can import both — ``research`` itself must not import
``llm`` (invariant S3).
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from signalforge.db.models import LlmCall
from signalforge.db.types import utcnow
from signalforge.llm.explain import explain_briefing
from signalforge.observability import get_logger
from signalforge.research.briefing import build_briefing_facts, render_briefing_text
from signalforge.settings_store import get_setting, set_setting

_log = get_logger("briefing")
LAST_BRIEFING_KEY = "last_briefing"


def _maybe_narrative(session: Session, facts: dict[str, Any], text: str) -> str | None:
    result = explain_briefing(facts, text)
    if result is None:
        return None
    session.add(
        LlmCall(
            purpose="daily_briefing",
            model=result.model,
            prompt_sha=hashlib.sha256(
                json.dumps(facts, sort_keys=True, default=str).encode()
            ).hexdigest(),
            input_snapshot_ref=LAST_BRIEFING_KEY,
            output_ref="app_setting:last_briefing.narrative",
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            created_at=utcnow(),
        )
    )
    session.flush()
    return result.text


def build_and_store_briefing(
    session: Session, *, account_name: str = "default", as_of: date | None = None
) -> dict[str, Any]:
    facts = build_briefing_facts(session, account_name=account_name, as_of=as_of)
    text = render_briefing_text(facts)
    narrative = _maybe_narrative(session, facts, text)
    payload = {
        "generated_at": facts["generated_at"],
        "as_of": facts["market"]["as_of"],
        "facts": facts,
        "text": text,
        "narrative": narrative,
        "narrative_footer": bool(narrative),
    }
    set_setting(session, LAST_BRIEFING_KEY, payload, actor="scheduler")
    _log.info(
        "briefing.built",
        as_of=payload["as_of"],
        qualified=len(facts["qualified_candidates"]),
        no_trade=facts["no_trade_total"],
        has_narrative=narrative is not None,
    )
    return payload


def latest_briefing(session: Session) -> dict[str, Any] | None:
    return get_setting(session, LAST_BRIEFING_KEY, None)
