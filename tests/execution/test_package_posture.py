"""D6 §2 — the default posture, and what this phase deliberately does not build.

The full boundary suite (T1-T13: the import-graph proofs, the outbound-host
allowlist, the extended call-string denylist) belongs to I-E1's
``tests/safety/test_s15_execution_boundary.py``. These are the assertions this
phase's own code must carry so that the posture cannot drift while that lands.
"""

from __future__ import annotations

import ast

import pytest

from signalforge.config.research import ResearchConfig
from tests.support import PKG_ROOT, iter_source_files, run_python

EXECUTION_MODULES = (
    "signalforge.execution",
    "signalforge.execution.brokers",
    "signalforge.execution.brokers.paper_reference",
    "signalforge.execution.arming",
    "signalforge.execution.calendarcheck",
    "signalforge.execution.credentials",
    "signalforge.execution.cycle",
    "signalforge.execution.deadman",
    "signalforge.execution.events",
    "signalforge.execution.intents",
    "signalforge.execution.limits",
    "signalforge.execution.oms",
    "signalforge.execution.protocol",
    "signalforge.execution.reconcile",
    "signalforge.execution.states",
)

#: S15a's forbidden list. Asserted here as a source-level check so the shape is
#: reviewed with the code rather than only in ``pyproject.toml``.
FORBIDDEN_FROM_EXECUTION = (
    "signalforge.llm",
    "signalforge.agents",
    "signalforge.alerts",
    "signalforge.research.scan",
    "signalforge.sf1000",
)


def test_the_package_is_disabled_by_default() -> None:
    from signalforge.execution import EXECUTION_DISABLED_BY_DEFAULT, execution_enabled

    assert EXECUTION_DISABLED_BY_DEFAULT is True
    assert ResearchConfig().execution.enabled is False
    assert execution_enabled() is False


def test_importing_every_submodule_performs_no_network_call_and_reads_no_credential() -> None:
    """A clean interpreter: no HTTP client is pulled in and no credential-shaped
    environment variable is read at import time."""
    code = "MODULES = " + repr(EXECUTION_MODULES) + """
import importlib, os, sys

os.environ["SF_EXECUTION_BROKER_KEY_ID"] = "would-be-read-if-anything-read-it"
read = []
real_get = os.environ.get


class Tripwire(dict):
    def __getitem__(self, key):
        read.append(key)
        return dict.__getitem__(self, key)

    def get(self, key, default=None):
        read.append(key)
        return real_get(key, default)


os.environ = Tripwire(os.environ)

for name in MODULES:
    importlib.import_module(name)

leaked = [k for k in read if "KEY" in k or "SECRET" in k or "TOKEN" in k]
assert not leaked, leaked
clients = {"httpx", "requests", "aiohttp"} & set(sys.modules)
assert not clients, clients
print("ok")
"""
    result = run_python(code)
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def _execution_sources() -> list:
    return list(iter_source_files("execution"))


def test_the_package_imports_no_http_client_and_no_socket() -> None:
    """I-E3 added the first adapter, and it still opens no socket.

    ``brokers/paper_reference.py`` is a local, deterministic simulator: it
    imports no HTTP client, no ``socket``, and no vendor package, so "nothing
    in this package opens a socket" is a property of the import graph rather
    than a claim about behaviour.
    """
    offenders: list[str] = []
    banned_modules = {"httpx", "requests", "aiohttp", "socket", "urllib", "http"}
    for path in _execution_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = {node.module.split(".")[0]}
            else:
                continue
            if names & banned_modules:
                offenders.append(f"{path}: {sorted(names & banned_modules)}")
    assert not offenders, "\n".join(offenders)


def test_the_execution_package_imports_nothing_s15a_forbids() -> None:
    offenders: list[str] = []
    for path in _execution_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = ""
            if isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
            elif isinstance(node, ast.Import):
                module = node.names[0].name
            for forbidden in FORBIDDEN_FROM_EXECUTION:
                if module == forbidden or module.startswith(forbidden + "."):
                    offenders.append(f"{path}: {module}")
    assert not offenders, "\n".join(offenders)


def test_signalforge_cli_is_the_only_thing_outside_the_package_that_names_it() -> None:
    """S15b's direction (D6 §2, §17.2 note 2, safety test T12).

    I-E2 left the tree with NO inbound edge at all. I-E4 adds exactly one, and
    it is the sanctioned one: the arming ceremony and the execution job spec are
    injected from ``signalforge.cli``, a human-typed entry point with no LLM on
    it. ``signalforge.scheduler`` must gain none (``signalforge.app`` imports it,
    and a forbidden contract reports indirect chains), and ``signalforge/app/**``
    must gain none either — so this list is one file long and stays that way.
    """
    offenders: list[str] = []
    for path in iter_source_files():
        if "execution" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        if "signalforge.execution" in text:
            offenders.append(str(path.relative_to(PKG_ROOT)))
    assert offenders == ["cli.py"], offenders


def test_the_scheduler_and_the_app_still_name_the_execution_layer_nowhere() -> None:
    """The two modules the §2 registration rule exists to keep clean."""
    paths = [PKG_ROOT / "scheduler.py", *sorted((PKG_ROOT / "app").rglob("*.py"))]
    named = [
        str(p.relative_to(PKG_ROOT))
        for p in paths
        if "signalforge.execution" in p.read_text(encoding="utf-8")
    ]
    assert named == [], named


def test_the_options_order_path_is_blocked_until_the_options_ledger_lands() -> None:
    """§5.3b rule 4 — and the shortcut out of it is explicitly refused."""
    from signalforge.execution.intents import OptionsStreamUnavailable, build_open_combo_intent

    with pytest.raises(OptionsStreamUnavailable, match="options_ledger"):
        build_open_combo_intent()


def test_assert_auto_simulate_allowed_is_still_stock_and_etf_only() -> None:
    """Map §3.6, binding: the existing guard is left UNCHANGED and is never
    widened to admit options."""
    import inspect

    from signalforge.paper import ledger

    source = inspect.getsource(ledger.assert_auto_simulate_allowed)
    body = source[source.index('"""', source.index('"""') + 3) :]  # past the docstring
    assert '("stock", "etf")' in body
    # The explicitly refused resolution: widening this tuple would "silently let
    # options trades flow through equity-shaped sizing, cash, and
    # mark-to-market logic that is provably wrong for options".
    assert "option" not in body


def test_importing_the_package_constructs_no_adapter() -> None:
    """D6 §2: an adapter exists only when the config selects one.

    Walking every submodule in a clean interpreter must leave the adapter
    class's construction counter at zero — "never instantiated by an import
    side effect" proved rather than asserted.
    """
    code = """
import importlib, pkgutil

import signalforge.execution as ex

for mod in pkgutil.walk_packages(ex.__path__, "signalforge.execution."):
    importlib.import_module(mod.name)

from signalforge.execution.brokers.paper_reference import PaperReferenceBroker

assert PaperReferenceBroker.instances_created == 0, PaperReferenceBroker.instances_created
print("ok")
"""
    result = run_python(code)
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_an_adapter_is_reachable_only_through_the_config_selector() -> None:
    """The registry maps a name to a LOADER, so no module-level object of the
    adapter class exists to be picked up by accident."""
    from signalforge.execution import brokers
    from signalforge.execution.brokers.paper_reference import PaperReferenceBroker

    module_level_adapters = [
        name
        for name, value in vars(brokers).items()
        if isinstance(value, PaperReferenceBroker)  # pragma: no cover - must stay empty
    ]
    assert not module_level_adapters
    assert brokers.ADAPTER_NAMES == ("paper_reference",)
