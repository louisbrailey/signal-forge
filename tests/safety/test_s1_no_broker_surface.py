"""S1 — no brokerage / execution / browser-automation surface OUTSIDE ``signalforge.execution``.

S1 used to read "nowhere". Since the D6 execution ADR
(``docs/research/options_designs/D6_execution_adr.md``, superseding
``docs/PORTFOLIO_RESEARCH_ROADMAP.md``'s "no brokerage, at any phase" boundary) it reads:

    ``signalforge.execution`` is the ONLY place a broker surface may exist, it is
    disabled by default, nothing is armed by default, and no module outside it may
    import it (import-linter S15b, and S15a in the opposite direction).

**Nothing is relaxed by that restatement** (ADR §17.1). All 15 ``BANNED_IMPORTS`` and all 9
original ``BANNED_CALL_SUBSTRINGS`` still apply to every path under ``src/signalforge``,
including ``src/signalforge/execution/`` itself — the adapter speaks REST over ``httpx`` and
imports no vendor SDK (ADR decision D6-A), so it needs no exception and gets none.

What *is* added (ADR §17.1b) is four **more** call substrings, so the scan can actually see
the order-submission surface the ADR introduces. None of the original 9 matches ``place``,
``place_combo``, ``cancel``, ``cancel_all`` or ``order_status``, so without this addition both
mechanical barriers would have gone inert against the one surface they exist for. The four new
strings are allowlisted for the **path prefix** ``src/signalforge/execution/`` and nowhere
else; everywhere else in the package they fail exactly as the original 9 do.

The inbound/outbound import halves of the new invariant are asserted in
``tests/safety/test_s15_execution_boundary.py`` (T1, T12) and contracted in ``pyproject.toml``
(S15b live, S15a staged).
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Iterator
from pathlib import Path

import pytest

from tests.support import PKG_ROOT, iter_source_files, run_python

pytestmark = pytest.mark.safety

# Import names that must never appear anywhere in the package — including under
# src/signalforge/execution/. Unchanged by the execution ADR (§17.1): no name is removed.
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

# Substrings that indicate an order-execution code path. Banned in EVERY path under
# src/signalforge, with no allowlist. Unchanged by the execution ADR.
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

# ADR §17.1b: the order-submission surface of the D6 BrokerAdapter protocol. Banned
# everywhere EXCEPT the one package the ADR authorises to hold it. ".place(" carries the
# leading dot deliberately — a bare "place(" would match ".replace(".
EXECUTION_ONLY_CALL_SUBSTRINGS = (
    "place_combo(",
    "cancel_all(",
    ".place(",
    "order_status(",
)

# The allowlist is a PATH PREFIX, never a substring: the strings above are permitted only in
# files under this directory, and this directory is the only entry there will ever be.
EXECUTION_PATH_ALLOWLIST = (PKG_ROOT / "execution",)


def _imported_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def is_allowlisted_path(path: Path) -> bool:
    """True when ``path`` lies under an execution-allowlisted directory."""
    return any(path == root or root in path.parents for root in EXECUTION_PATH_ALLOWLIST)


def scan_call_strings(sources: Iterable[tuple[Path, str]]) -> list[str]:
    """Return one offender line per banned call substring found in ``sources``.

    Split out from the filesystem walk so T13 can drive it with synthetic paths — planting a
    real ``cancel_all(`` under ``src/signalforge/app/`` to prove the scan bites would mean
    writing into the shipped package from a test.
    """
    offenders: list[str] = []
    for path, text in sources:
        for needle in BANNED_CALL_SUBSTRINGS:
            if needle in text:
                offenders.append(f"{path}: {needle!r}")
        if is_allowlisted_path(path):
            continue
        for needle in EXECUTION_ONLY_CALL_SUBSTRINGS:
            if needle in text:
                offenders.append(f"{path}: {needle!r} (allowed only under signalforge/execution/)")
    return offenders


def _package_sources() -> Iterator[tuple[Path, str]]:
    for path in iter_source_files():
        yield path, path.read_text(encoding="utf-8")


def test_no_banned_imports_in_source() -> None:
    offenders: list[str] = []
    for path in iter_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        bad = _imported_names(tree) & BANNED_IMPORTS
        if bad:
            offenders.append(f"{path}: {sorted(bad)}")
    assert not offenders, "Brokerage/automation imports found:\n" + "\n".join(offenders)


def test_no_execution_call_strings_in_source() -> None:
    offenders = scan_call_strings(_package_sources())
    assert not offenders, "Order-execution call sites found:\n" + "\n".join(offenders)


# ---------------------------------------------------------------------------
# T13 (ADR §19) — the §17.1b allowlist covers EXACTLY src/signalforge/execution/.
# ---------------------------------------------------------------------------


def test_t13_execution_only_strings_are_allowed_under_execution_only() -> None:
    """A planted ``cancel_all(`` fails outside signalforge/execution/ and passes inside it."""
    outside = PKG_ROOT / "app" / "views.py"
    inside = PKG_ROOT / "execution" / "oms.py"
    body = "def go(self):\n    self.adapter.cancel_all()\n"

    assert scan_call_strings([(outside, body)]), (
        "the §17.1b additions did not fire outside signalforge/execution/ — "
        "the scan cannot see the surface it exists for"
    )
    assert not scan_call_strings([(inside, body)]), (
        "the §17.1b additions fired inside signalforge/execution/ — the allowlist is the "
        "path prefix the ADR authorises"
    )


def test_t13_allowlist_is_exactly_the_execution_package() -> None:
    assert EXECUTION_PATH_ALLOWLIST == (
        PKG_ROOT / "execution",
    ), "the call-string allowlist must cover src/signalforge/execution/ and nothing else"
    assert not is_allowlisted_path(PKG_ROOT / "app" / "views.py")
    assert not is_allowlisted_path(PKG_ROOT / "paper" / "ledger.py")
    assert not is_allowlisted_path(
        PKG_ROOT / "executionish" / "mod.py"
    ), "the allowlist must match a path segment, not a name prefix"
    assert is_allowlisted_path(PKG_ROOT / "execution" / "brokers" / "paper_reference.py")


def test_t13_original_substrings_have_no_allowlist_anywhere() -> None:
    """The original 9 are banned even inside signalforge/execution/ — nothing is relaxed."""
    inside = PKG_ROOT / "execution" / "brokers" / "paper_reference.py"
    for needle in BANNED_CALL_SUBSTRINGS:
        assert scan_call_strings(
            [(inside, f"x = {needle}\n")]
        ), f"{needle!r} must stay banned under signalforge/execution/ too"


def test_banned_call_substring_lists_are_not_shortened() -> None:
    """R4: a gate may be made more searching, never weaker. Guard against quiet removals."""
    assert len(BANNED_IMPORTS) == 15
    assert len(BANNED_CALL_SUBSTRINGS) == 9
    assert len(EXECUTION_ONLY_CALL_SUBSTRINGS) == 4


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
