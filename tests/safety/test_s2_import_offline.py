"""S2 — the manual CSV portfolio importer performs no network I/O."""

from __future__ import annotations

import ast

import pytest

from tests.support import iter_source_files, run_python

pytestmark = pytest.mark.safety

NETWORK_MODULES = {
    "httpx",
    "requests",
    "aiohttp",
    "socket",
    "ssl",
    "urllib",
    "http",
    "ftplib",
    "telnetlib",
    "websockets",
    "smtplib",
}


def _imported_modules(tree: ast.AST) -> set[str]:
    """Every fully-qualified module name referenced by an import statement."""
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods.add(node.module)
    return mods


def test_portfolio_package_imports_nothing_network() -> None:
    offenders: list[str] = []
    for path in iter_source_files("portfolio"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        roots = {m.split(".")[0] for m in _imported_modules(tree)}
        bad = roots & NETWORK_MODULES
        if bad:
            offenders.append(f"{path}: {sorted(bad)}")
    assert not offenders, "Network imports in signalforge.portfolio:\n" + "\n".join(offenders)


def test_portfolio_does_not_import_data_adapters() -> None:
    offenders: list[str] = []
    for path in iter_source_files("portfolio"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for mod in _imported_modules(tree):
            if mod == "signalforge.data" or mod.startswith("signalforge.data."):
                offenders.append(f"{path}: imports {mod}")
    assert not offenders, "signalforge.data import in portfolio:\n" + "\n".join(offenders)


def test_clean_interpreter_import_loads_no_adapter_or_http() -> None:
    code = (
        "import sys, signalforge.portfolio.import_csv\n"
        "bad = [m for m in sys.modules if m.startswith('signalforge.data')"
        " or m in {'httpx','requests','aiohttp'}]\n"
        "assert not bad, bad\n"
        "print('ok')\n"
    )
    result = run_python(code)
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout
