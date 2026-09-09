"""Phase A safety boundaries for the Signal Forge 1000 paper-index research
module: design only, nothing activated, and every switch that could move
money-shaped state stays OFF."""

from __future__ import annotations

import tomllib
from pathlib import Path

from sqlalchemy.orm import Session

import signalforge.sf1000 as sf1000
from signalforge.alerts.dispatch import alert_type_states
from signalforge.settings_store import effective_research_config, get_setting

_ROOT = Path(__file__).resolve().parents[2]


def test_sf1000_is_design_only_and_provisional() -> None:
    assert sf1000.STATUS == "design_only"
    assert sf1000.SPEC_VERSION.endswith("-provisional")
    assert "not eligible for paper probation" in sf1000.PROVISIONAL_LABEL
    assert sf1000.RESEARCH_ONLY_NOTICE == "Research signal only — no order was placed."


def test_sf1000_package_has_no_behaviour_and_no_forbidden_imports() -> None:
    src = (_ROOT / "src" / "signalforge" / "sf1000" / "__init__.py").read_text()
    imports = [ln for ln in src.splitlines() if ln.startswith(("import ", "from "))]
    assert imports == ["from __future__ import annotations"]  # nothing else imported
    assert "def " not in src and "class " not in src  # no behaviour in Phase A


def test_import_linter_contract_s13_exists() -> None:
    cfg = tomllib.loads((_ROOT / "pyproject.toml").read_text())
    contracts = cfg["tool"]["importlinter"]["contracts"]
    s13 = next(c for c in contracts if c["name"].startswith("S13"))
    assert s13["source_modules"] == ["signalforge.sf1000"]
    assert {"signalforge.alerts", "signalforge.paper.ledger", "signalforge.llm"} <= set(
        s13["forbidden_modules"]
    )


def test_every_activation_switch_defaults_off(session: Session) -> None:
    assert get_setting(session, "alerts_enabled", False) is False
    assert get_setting(session, "paper_probation_enabled", False) is False
    assert get_setting(session, "auto_simulate_qualified_signals", False) is False
    assert not any(alert_type_states(session).values())
    assert effective_research_config(session).universe_pipeline.enabled is False


def test_phase_a_docs_exist_and_carry_the_boundaries() -> None:
    for name in ("PORTFOLIO_RESEARCH_ROADMAP.md", "CAPABILITY_MATRIX.md", "SF1000_SPEC.md"):
        path = _ROOT / "docs" / name
        assert path.exists(), name
    spec = (_ROOT / "docs" / "SF1000_SPEC.md").read_text().lower()
    assert "not an etf" in spec or "not a real etf" in spec or "not an investment product" in spec
    assert "provisional" in spec and "survivorship" in spec and "look-ahead" in spec
