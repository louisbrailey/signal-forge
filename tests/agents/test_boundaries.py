"""Proof that no research agent can bypass the deterministic trading/risk
rules: source-level, contract-level, and runtime-level."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

_ROOT = Path(__file__).resolve().parents[2]
_AGENTS_DIR = _ROOT / "src" / "signalforge" / "agents"

# Anything that could create/alter trading state or reach the outside world.
_FORBIDDEN_TOKENS = (
    "set_setting(",
    "accept_candidate",
    "record_decision(",
    "mark_to_market(",
    "run_alert_cycle",
    "dry_run_cycle",
    ".send(",
    "session.delete(",
    "persist_scan(",
    "run_scan(",
    "evaluate_promotion",
    "run_health_monitor(",
    "ingest_universe(",
    "ingest_news(",
    "engage(",
    "release(",
    "httpx",
    "requests.",
    "subprocess",
    "PaperTrade(",
    "PaperOrder(",
    "Candidate(",
    "StrategyStatus.PAPER_APPROVED)",  # never assigned; reads compare with 'is'
)


def _agent_sources() -> dict[str, str]:
    return {p.name: p.read_text() for p in _AGENTS_DIR.glob("*.py")}


def test_agent_sources_contain_no_state_changing_calls() -> None:
    for name, src in _agent_sources().items():
        for tok in _FORBIDDEN_TOKENS:
            assert tok not in src, f"{name} contains forbidden token {tok!r}"
        # the only ORM writes allowed anywhere in the package are the report + audit rows in base.py
        adds = re.findall(r"session\.add\(", src)
        if name == "base.py":
            assert len(adds) == 2  # AgentReport + AuditLog
        else:
            assert not adds, f"{name} must not write rows"


def test_import_linter_contract_s14_present() -> None:
    import tomllib

    cfg = tomllib.loads((_ROOT / "pyproject.toml").read_text())
    s14 = next(c for c in cfg["tool"]["importlinter"]["contracts"] if c["name"].startswith("S14"))
    assert s14["source_modules"] == ["signalforge.agents"]
    for forbidden in (
        "signalforge.paper.ledger",
        "signalforge.alerts.dispatch",
        "signalforge.alerts.channels",
        "signalforge.research.scan",
        "signalforge.research.promotion",
        "signalforge.killswitch",
        "httpx",
    ):
        assert forbidden in s14["forbidden_modules"]


def _counts(session: Session) -> dict[str, int]:
    from signalforge.db.models import (
        AlertLog,
        AppSetting,
        Candidate,
        PaperPosition,
        PaperTrade,
        ScanRun,
        Strategy,
        StrategyVersion,
    )

    return {
        m.__tablename__: int(session.scalar(select(func.count()).select_from(m)) or 0)
        for m in (
            Candidate,
            PaperTrade,
            PaperPosition,
            AppSetting,
            Strategy,
            StrategyVersion,
            ScanRun,
            AlertLog,
        )
    }


def test_running_every_agent_changes_no_trading_state(session: Session) -> None:
    from signalforge.agents import all_agents, run_all_agents
    from signalforge.db.models import AgentReport, AuditLog

    before = _counts(session)
    results = run_all_agents(session)
    assert [r.agent for r in results] == [a.name for a in all_agents()]
    assert all(r.status in ("ok", "failed") for r in results)
    assert _counts(session) == before
    n_reports = session.scalar(select(func.count()).select_from(AgentReport))
    n_audit = session.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.action.in_(("agent.run", "agent.failed")))
    )
    assert n_reports == len(results) == n_audit
    for r in results:
        assert "Research signal only — no order was placed." in r.summary


def test_agent_narrative_cannot_inject_numbers_or_instructions(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even a hostile LLM output cannot reach the summary: ungrounded numbers
    are rejected by the guard and, when accepted, the text lives ONLY in the
    labelled narrative field."""
    import signalforge.llm.client as llm_client
    from signalforge.agents.base import NARRATIVE_LABEL, ResearchAgent

    class _Fake:
        model = "fake"

        def __init__(self, text: str) -> None:
            self._text = text

        def complete(self, *, system: str, prompt: str, max_tokens: int = 0):  # type: ignore[no-untyped-def]
            class _R:
                pass

            r = _R()
            r.text = self._text  # type: ignore[attr-defined]
            return r

    class _Toy(ResearchAgent):
        name = "toy"
        role = "toy"
        allowed_inputs = ("nothing",)
        outputs = ("summary",)
        prohibited = ("everything else",)
        llm_narrative = True

        def collect(self, session: Session) -> dict[str, object]:
            return {"value": 7, "source": "test", "as_of": "2026-09-10"}

        def summarize(self, evidence: dict[str, object]) -> str:
            return "value is 7"

    import types

    fake_cfg = types.SimpleNamespace(
        research=types.SimpleNamespace(agents=types.SimpleNamespace(llm_narratives=True))
    )
    monkeypatch.setattr("signalforge.config.get_settings", lambda: fake_cfg)

    monkeypatch.setattr(
        llm_client,
        "build_client",
        lambda: _Fake("BUY 12345 shares now. AI explanation, not a trading instruction."),
    )
    r = _Toy().run(session)
    assert r.narrative is None and r.summary.startswith("value is 7")
    assert "llm_narrative_unavailable_or_rejected" in r.missing_data

    monkeypatch.setattr(
        llm_client,
        "build_client",
        lambda: _Fake("The value is 7. AI explanation, not a trading instruction."),
    )
    r2 = _Toy().run(session)
    assert r2.narrative is not None and r2.narrative.startswith(NARRATIVE_LABEL)
    assert r2.summary.startswith("value is 7")  # deterministic summary untouched


def test_failed_agent_never_raises_and_is_audited(session: Session) -> None:
    from signalforge.agents.base import ResearchAgent
    from signalforge.db.models import AuditLog

    class _Broken(ResearchAgent):
        name = "broken"
        role = "broken"
        allowed_inputs = ()
        outputs = ()
        prohibited = ()

        def collect(self, session: Session) -> dict[str, object]:
            raise RuntimeError("boom")

        def summarize(self, evidence: dict[str, object]) -> str:
            return "never"

    r = _Broken().run(session)
    assert r.status == "failed" and "boom" in r.error and r.report_id is not None
    row = session.scalar(select(AuditLog).where(AuditLog.action == "agent.failed"))
    assert row is not None and row.entity == "broken"


def test_no_broker_dependencies_or_connectors() -> None:
    """Paper only: no brokerage/execution package may be a dependency."""
    import tomllib

    banned = (
        "ib_insync",
        "ibapi",
        "alpaca",
        "webull",
        "ccxt",
        "tradier",
        "robin_stocks",
        "tda",
        "schwab",
        "etrade",
        "interactive-brokers",
    )
    py = (_ROOT / "pyproject.toml").read_text().lower()
    cfg = tomllib.loads((_ROOT / "pyproject.toml").read_text())
    deps = " ".join(cfg["project"].get("dependencies", [])).lower()
    for group in cfg["project"].get("optional-dependencies", {}).values():
        deps += " " + " ".join(group).lower()
    for b in banned:
        assert b not in deps, b
    lock = (_ROOT / "uv.lock").read_text().lower() if (_ROOT / "uv.lock").exists() else ""
    for b in ("ib_insync", "ibapi", "alpaca", "webull", "ccxt"):
        assert f'name = "{b}' not in lock, b
    assert "banned-api" in py or "S1" in py  # the import contract stays
