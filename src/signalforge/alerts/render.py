"""Alert body rendering. Every alert must carry the mandatory lines and fields."""

from __future__ import annotations

from typing import Any

from signalforge import RESEARCH_ONLY_NOTICE

_BASE_URL = "http://127.0.0.1:8787"


def _link(path: str) -> str:
    return f"{_BASE_URL}{path}"


def render_candidate_alert(c: dict[str, Any]) -> tuple[str, str]:
    subject = f"[Signal Forge] {c['symbol']} {c['direction']} ({c['horizon']}) — research signal"
    freshness = c.get("data_freshness") or {}
    events = ", ".join(c["event_risk"].get("upcoming_earnings", [])) or "none on record"
    body = "\n".join(
        [
            RESEARCH_ONLY_NOTICE,
            "Hypothetical research output, not financial advice. No brokerage was contacted.",
            "",
            f"Instrument:      {c['symbol']} ({c.get('sector', 'unknown')})",
            f"Horizon:         {c['horizon']}",
            f"Strategy:        {c['strategy']} v{c.get('strategy_version', '?')}",
            f"Reference price: {c.get('reference_price', 'n/a')}  as of {c.get('as_of', 'n/a')}",
            f"Data freshness:  {freshness.get('fresh', 'unknown')} "
            f"({', '.join(freshness.get('reasons', [])) or 'ok'})",
            f"Entry zone:      {c['entry_low']:.2f} – {c['entry_high']:.2f}",
            f"Invalidation:    {c['stop']:.2f}",
            (
                f"Target:          {c['target']:.2f}"
                if c.get("target")
                else "Target:          rule-based"
            ),
            f"Reward : risk:   {c['reward_risk']:.2f}",
            f"Max risk:        ${c['risk_dollars']:.0f} ({c['risk_pct']:.2f}% of paper account)",
            f"Event risk:      {events}",
            "",
            "Why it qualified:",
            *[f"  - {r}" for r in c.get("reasons_qualify", [])],
            "Why it could fail:",
            *[f"  - {r}" for r in c.get("reasons_fail", [])],
            "",
            f"Evidence page:   {_link('/candidates/' + str(c['id']))}",
            "",
            RESEARCH_ONLY_NOTICE,
        ]
    )
    return subject, body


def render_briefing_alert(payload: dict[str, Any]) -> tuple[str, str]:
    subject = f"[Signal Forge] Daily research briefing — {payload['as_of']}"
    body = payload["text"] + "\n\n" + RESEARCH_ONLY_NOTICE
    if payload.get("narrative"):
        body += "\n\n--- AI narrative (explanation, not a trading instruction) ---\n"
        body += payload["narrative"]
    return subject, body


def render_health_alert(reasons: list[str]) -> tuple[str, str]:
    subject = "[Signal Forge] System health — data feed problem"
    body = (
        "A data feed is stale or unavailable. Live alerts are disabled until it recovers.\n\n"
        + "\n".join(f"- {r}" for r in reasons)
        + f"\n\n{RESEARCH_ONLY_NOTICE}"
    )
    return subject, body
