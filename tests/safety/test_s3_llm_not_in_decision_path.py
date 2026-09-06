"""S3 — the LLM layer is never on the deterministic decision path.

Also covered by the import-linter contract in ``make lint`` / CI; this is a fast
inline check plus a clean-interpreter assertion.
"""

from __future__ import annotations

import ast

import pytest

from tests.support import iter_source_files, run_python

pytestmark = pytest.mark.safety

DECISION_PACKAGES = ("research", "risk", "backtest", "paper")


def test_decision_packages_never_import_llm_in_source() -> None:
    offenders: list[str] = []
    for pkg in DECISION_PACKAGES:
        for path in iter_source_files(pkg):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                    "signalforge.llm"
                ):
                    offenders.append(f"{path}:{node.lineno}")
                if isinstance(node, ast.Import) and any(
                    a.name.startswith("signalforge.llm") for a in node.names
                ):
                    offenders.append(f"{path}:{node.lineno}")
    assert not offenders, "signalforge.llm imported on the decision path:\n" + "\n".join(offenders)


def test_clean_interpreter_decision_import_loads_no_llm() -> None:
    code = (
        "import sys\n"
        "import signalforge.research, signalforge.risk, signalforge.backtest, signalforge.paper\n"
        "import signalforge.research.registry, signalforge.risk.engine\n"
        "import signalforge.backtest.costs, signalforge.paper.ledger\n"
        "bad = [m for m in sys.modules if m.startswith('signalforge.llm')]\n"
        "assert not bad, bad\n"
        "print('ok')\n"
    )
    result = run_python(code)
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout
