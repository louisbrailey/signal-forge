"""S1 — no brokerage / execution / browser-automation surface anywhere.

Complements the Ruff ``banned-api`` rule and the import-linter S1 contract with a
source-level scan and a clean-interpreter import check.
"""

from __future__ import annotations

import ast

import pytest

from tests.support import iter_source_files, run_python

pytestmark = pytest.mark.safety

# Import names that must never appear anywhere in the package.
BANNED_IMPORTS = {
    "ib_insync",
    "ibapi",
    "ibkr",
    "alpaca_trade_api",
    "alpaca",
    "selenium",
    "playwright",
    "pyppeteer",
    "webdriver",
    "ccxt",
    "robin_stocks",
    "tda",
    "schwab",
    "fidelity_api",
    "MetaTrader5",
}

# Substrings that indicate an order-execution code path.
BANNED_CALL_SUBSTRINGS = (
    "place_order",
    "submit_order",
    "route_order",
    "execute_order",
    "execute_trade",
    "send_order",
    "cancel_order(",
    "buy_shares(",
    "sell_shares(",
)


def _imported_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_no_banned_imports_in_source() -> None:
    offenders: list[str] = []
    for path in iter_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        bad = _imported_names(tree) & BANNED_IMPORTS
        if bad:
            offenders.append(f"{path}: {sorted(bad)}")
    assert not offenders, "Brokerage/automation imports found:\n" + "\n".join(offenders)


def test_no_execution_call_strings_in_source() -> None:
    offenders: list[str] = []
    for path in iter_source_files():
        text = path.read_text(encoding="utf-8")
        for needle in BANNED_CALL_SUBSTRINGS:
            if needle in text:
                offenders.append(f"{path}: {needle!r}")
    assert not offenders, "Order-execution call sites found:\n" + "\n".join(offenders)


_IMPORT_ALL_AND_CHECK = """
import importlib, pkgutil, sys
import signalforge

for mod in pkgutil.walk_packages(signalforge.__path__, "signalforge."):
    importlib.import_module(mod.name)

banned = {
    "ib_insync", "ibapi", "alpaca_trade_api", "alpaca",
    "selenium", "playwright", "pyppeteer", "ccxt", "MetaTrader5",
}
hit = banned & set(sys.modules)
assert not hit, f"banned modules imported: {hit}"
print("ok")
"""


def test_importing_every_submodule_pulls_no_broker_module() -> None:
    result = run_python(_IMPORT_ALL_AND_CHECK)
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout
