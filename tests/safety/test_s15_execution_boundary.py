"""S15a/S15b — the execution boundary. Safety tests T1-T13 of the D6 execution ADR.

``docs/research/options_designs/D6_execution_adr.md`` §17.3 and §19. Written in **I-E1**,
before ``signalforge.execution`` exists, so the shape of these assertions is reviewed on its
own rather than as a fix to a red build.

Two of the thirteen live elsewhere: **T8** (append-only ``execution_event`` triggers) beside
``tests/db/test_s9_paper_trade_triggers.py``, and **T13** (the §17.1b call-string allowlist) in
``tests/safety/test_s1_no_broker_surface.py``, whose list it is about.

**On skipping.** Several assertions need symbols that only I-E2 creates. Those tests skip with
a reason that names the exact missing symbol — they never silently pass, and wherever something
*can* be asserted today (the source-level facts the future assertion depends on, or the scan
machinery itself driven against synthetic input) it is asserted now rather than deferred.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import tomllib
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.support import PKG_ROOT, REPO_ROOT, SRC_ROOT, iter_source_files, run_python

pytestmark = pytest.mark.safety

EXECUTION_MODULE = "signalforge.execution"
EXECUTION_PREFIX = f"{EXECUTION_MODULE}."

# T1: the packages S15b names as sources. `signalforge.scheduler` is in S15b too but is
# asserted by T12, which states the stronger property (signalforge.cli is the ONLY inbound edge).
T1_SOURCE_PACKAGES = (
    "signalforge.llm",
    "signalforge.agents",
    "signalforge.app",
    "signalforge.research",
    "signalforge.alerts",
    "signalforge.sf1000",
    "signalforge.backtest",
    "signalforge.paper",
    "signalforge.portfolio",
)

# The one sanctioned inbound edge (ADR §2, §17.2 note 2): the arming ceremony and the
# execution command group live in the CLI, which is a human-typed entry point with no LLM on it.
SANCTIONED_INBOUND_MODULE = "signalforge.cli"


def execution_package_exists() -> bool:
    """True once I-E2 has created ``src/signalforge/execution``."""
    return (PKG_ROOT / "execution" / "__init__.py").exists()


def _requires_ie2(symbol: str) -> None:
    pytest.skip(f"requires I-E2: {symbol} does not exist yet (D6 ADR §19)")


# ---------------------------------------------------------------------------
# Intra-package import graph — shared by T1 and T12.
#
# Mirrors `_imported_names` in test_s1_no_broker_surface.py but keeps the FULL dotted
# target instead of the first segment, and follows chains. A direct-edge scan would have
# the exact blind spot `allow_indirect_imports = true` would introduce (ADR §17.2, §19 T1).
# ---------------------------------------------------------------------------


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(SRC_ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _absolute_prefixes(target: str) -> set[str]:
    """``a.b.c`` -> {``a``, ``a.b``, ``a.b.c``}: importing a submodule executes its parents."""
    parts = target.split(".")
    return {".".join(parts[: i + 1]) for i in range(len(parts))}


def _import_targets(tree: ast.AST, module_name: str, *, is_package: bool) -> set[str]:
    base = module_name if is_package else module_name.rpartition(".")[0]
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                targets |= _absolute_prefixes(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = base.split(".")
                up = node.level - 1
                parts = parts[: len(parts) - up] if up <= len(parts) else []
                head = ".".join([*parts, node.module] if node.module else parts)
            else:
                head = node.module or ""
            if not head:
                continue
            targets |= _absolute_prefixes(head)
            # `from pkg import name` may import a submodule; keep both readings.
            targets |= {f"{head}.{alias.name}" for alias in node.names}
    return {t for t in targets if t == "signalforge" or t.startswith("signalforge.")}


def build_import_graph() -> dict[str, set[str]]:
    """Map every ``signalforge`` module to the full dotted ``signalforge`` names it imports."""
    graph: dict[str, set[str]] = {}
    for path in iter_source_files():
        if "migrations" in path.parts:
            continue
        name = _module_name(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        graph[name] = _import_targets(tree, name, is_package=path.name == "__init__.py")
    return graph


def _package_members(graph: dict[str, set[str]], package: str) -> set[str]:
    return {m for m in graph if m == package or m.startswith(f"{package}.")}


def chain_to_execution(graph: dict[str, set[str]], package: str) -> list[str] | None:
    """Return a shortest import chain from ``package`` to the execution layer, or None."""
    queue: list[list[str]] = [[m] for m in sorted(_package_members(graph, package))]
    seen = set(_package_members(graph, package))
    while queue:
        chain = queue.pop(0)
        for target in sorted(graph.get(chain[-1], set())):
            if target == EXECUTION_MODULE or target.startswith(EXECUTION_PREFIX):
                return [*chain, target]
            if target in graph and target not in seen:
                seen.add(target)
                queue.append([*chain, target])
    return None


# ---------------------------------------------------------------------------
# The graph machinery must be shown to work, or T1/T12 pass for the wrong reason.
# ---------------------------------------------------------------------------


def test_import_graph_is_nontrivial() -> None:
    graph = build_import_graph()
    assert len(graph) > 100, f"the import graph collapsed to {len(graph)} modules"
    for package in (*T1_SOURCE_PACKAGES, "signalforge.scheduler", SANCTIONED_INBOUND_MODULE):
        assert _package_members(graph, package), f"{package} is missing from the graph"
    # A real edge the ADR reasons about (D6 §2): app -> scheduler.
    assert "signalforge.scheduler" in graph["signalforge.app.views"]


def test_chain_finder_reports_direct_and_indirect_paths() -> None:
    """Driven with a synthetic graph: a two-hop chain must be found, an absent one must not."""
    graph = {
        "signalforge.app": {"signalforge.scheduler"},
        "signalforge.scheduler": {EXECUTION_MODULE},
        "signalforge.paper": {"signalforge.db"},
        "signalforge.db": set(),
    }
    assert chain_to_execution(graph, "signalforge.app") == [
        "signalforge.app",
        "signalforge.scheduler",
        EXECUTION_MODULE,
    ]
    assert chain_to_execution(graph, "signalforge.scheduler") is not None
    assert chain_to_execution(graph, "signalforge.paper") is None
    # A submodule edge must count as reaching the package.
    assert chain_to_execution({"signalforge.llm": {f"{EXECUTION_PREFIX}oms"}}, "signalforge.llm")


# ---------------------------------------------------------------------------
# T1 — no LLM/agent/app/research/alert/SF1000/backtest/paper/portfolio module reaches
#      signalforge.execution, transitively.
# ---------------------------------------------------------------------------


def test_t1_no_source_package_reaches_the_execution_layer() -> None:
    graph = build_import_graph()
    offenders = []
    for package in T1_SOURCE_PACKAGES:
        chain = chain_to_execution(graph, package)
        if chain is not None:
            offenders.append(f"{package}: " + " -> ".join(chain))
    assert not offenders, "S15b violated (transitively):\n" + "\n".join(offenders)


# ---------------------------------------------------------------------------
# T2 — OrderIntent is constructible only under all seven §5 preconditions.
# ---------------------------------------------------------------------------


def test_t2_open_intent_requires_all_seven_preconditions() -> None:
    # Assert the source-level facts P6 will be keyed on, so a silent change to either actor
    # constant breaks here rather than inside an order-authorisation predicate later.
    from signalforge.paper.auto_simulate import AUTO_SIM_ACTOR

    assert AUTO_SIM_ACTOR == "auto_simulate"
    ledger = (PKG_ROOT / "paper" / "ledger.py").read_text(encoding="utf-8")
    assert (
        'actor: str = "local-user"' in ledger
    ), "accept_candidate's manual-actor default moved; P6 (ADR §5.3) is keyed on it"
    _requires_ie2("signalforge.execution.intents.build_open_intent")


# ---------------------------------------------------------------------------
# T3 — client_order_id is stable across retries and distinct across structures.
# ---------------------------------------------------------------------------


def test_t3_client_order_id_is_stable_across_retries() -> None:
    _requires_ie2("signalforge.execution.intents.client_order_id")


# ---------------------------------------------------------------------------
# T4 — default-disabled, and importing the package touches no network and no credential.
# ---------------------------------------------------------------------------


_T4_CLEAN_IMPORT = """
import importlib, os, pkgutil, socket, subprocess, sys


def _blocked(*args, **kwargs):
    raise RuntimeError("network or subprocess at import time")


socket.socket = _blocked
socket.create_connection = _blocked
subprocess.run = _blocked
subprocess.check_output = _blocked

WATCHED = ("SF_EXECUTION_BROKER_KEY_ID", "SF_EXECUTION_BROKER_SECRET")
read = []
_real_getenv = os.getenv
_real_get = os.environ.get


def _getenv(name, default=None):
    if name in WATCHED:
        read.append(name)
    return _real_getenv(name, default)


def _get(name, default=None):
    if name in WATCHED:
        read.append(name)
    return _real_get(name, default)


os.getenv = _getenv
os.environ.get = _get

import signalforge.execution as ex

assert ex.EXECUTION_DISABLED_BY_DEFAULT is True, "execution must be disabled by default"
for mod in pkgutil.walk_packages(ex.__path__, "signalforge.execution."):
    importlib.import_module(mod.name)
assert not read, f"credential env var read at import time: {read}"
print("ok")
"""


def test_t4_execution_is_disabled_by_default_and_import_is_inert() -> None:
    if not execution_package_exists():
        assert importlib.util.find_spec(EXECUTION_MODULE) is None, (
            "signalforge.execution is importable from outside this source tree — "
            "the package must live at src/signalforge/execution"
        )
        _requires_ie2("signalforge.execution.EXECUTION_DISABLED_BY_DEFAULT")
    result = run_python(_T4_CLEAN_IMPORT)
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


# ---------------------------------------------------------------------------
# T5 — no brokerage host literal outside src/signalforge/execution/brokers/.
# ---------------------------------------------------------------------------

_BROKER_HOST_RE = re.compile(
    r"[\w.-]*\b(?:alpaca|interactivebrokers|ibkr|tdameritrade|schwabapi|robinhood|webull"
    r"|tradier|etrade|oanda|binance|coinbase|kraken|metatrader|tastytrade|tastyworks"
    r"|questrade|saxobank)\.[a-z]{2,}\b",
    re.IGNORECASE,
)

BROKERS_ALLOWLIST = PKG_ROOT / "execution" / "brokers"


def find_broker_hosts(text: str) -> list[str]:
    """Return brokerage hostname literals in ``text`` (a dotted domain, not a bare word).

    ``schwab_positions`` — a CSV column-mapping profile in
    ``signalforge/portfolio/mapping.py`` — is a bare word and must not match.
    """
    return _BROKER_HOST_RE.findall(text)


def test_find_broker_hosts_bites_on_a_host_and_not_on_a_bare_word() -> None:
    assert find_broker_hosts('BASE = "https://paper-api.alpaca.markets/v2"')
    assert find_broker_hosts("client = httpx.Client(base_url='https://api.tradier.com')")
    assert not find_broker_hosts('"schwab_positions": PositionColumns(')
    assert not find_broker_hosts("# no broker host here")


def test_t5_no_brokerage_host_literal_outside_the_brokers_package() -> None:
    offenders: list[str] = []
    for path in iter_source_files():
        if path == BROKERS_ALLOWLIST or BROKERS_ALLOWLIST in path.parents:
            continue
        hosts = find_broker_hosts(path.read_text(encoding="utf-8"))
        if hosts:
            offenders.append(f"{path}: {sorted(set(hosts))}")
    assert not offenders, "Brokerage host literals outside execution/brokers/:\n" + "\n".join(
        offenders
    )


def test_t5_protocol_and_intents_import_no_http_client() -> None:
    paths = [PKG_ROOT / "execution" / name for name in ("protocol.py", "intents.py")]
    missing = [f"{EXECUTION_PREFIX}{p.stem}" for p in paths if not p.exists()]
    if missing:
        _requires_ie2(" / ".join(missing))
    forbidden = {"httpx", "requests", "aiohttp", "urllib", "socket", "http"}
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        heads: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                heads.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                heads.add(node.module.split(".")[0])
        assert not heads & forbidden, f"{path} imports an HTTP client: {sorted(heads & forbidden)}"


# ---------------------------------------------------------------------------
# T6 — an is_paper() account-id mismatch fails arming.
# ---------------------------------------------------------------------------


def test_t6_is_paper_mismatch_fails_arming() -> None:
    _requires_ie2("signalforge.execution.protocol.IsPaperProof / execution.arming")


# ---------------------------------------------------------------------------
# T7 — no credential literal anywhere in src/signalforge.
# ---------------------------------------------------------------------------

_CREDENTIAL_LITERAL_RE = re.compile(
    r"(?i)\b(?:api[_-]?key|apikey|secret|password|passwd|token|authorization|bearer|credential)"
    r"[\"']?\s*(?::\s*str)?\s*[:=]\s*[\"'][^\"'\n]{8,}[\"']"
)


def find_credential_literals(text: str) -> list[str]:
    """Return credential-shaped assignments to a string literal.

    Complements ``make secrets`` (check-only, ``Makefile:80``) and
    ``tests/safety/test_s5_no_secret_leak.py``. It can only see literals in source; a runtime
    value is T11's job.
    """
    return _CREDENTIAL_LITERAL_RE.findall(text)


def test_find_credential_literals_bites() -> None:
    assert find_credential_literals('api_key = "AKIA1234567890ABCD"')  # pragma: allowlist secret
    assert find_credential_literals("SECRET: str = 'hunter2-hunter2'")  # pragma: allowlist secret
    assert not find_credential_literals("api_key = settings.market_data_api_key")
    assert not find_credential_literals('api_key: SecretStr = Field(default="")')


def test_t7_no_credential_literal_in_source() -> None:
    offenders: list[str] = []
    for path in iter_source_files():
        hits = find_credential_literals(path.read_text(encoding="utf-8"))
        if hits:
            offenders.append(f"{path}: {sorted(set(hits))}")
    assert not offenders, "Credential-shaped literals in source:\n" + "\n".join(offenders)


# ---------------------------------------------------------------------------
# T9 — no unconditional no-order / no-broker promise survives once execution exists.
# ---------------------------------------------------------------------------

UNCONDITIONAL_NO_ORDER_PHRASES = (
    "no order is ever placed",
    "no orders are ever placed",
    "never places an order",
    "no order placement",
    "no brokerage connection",
    "no broker contact",
    "no execution path",
    "there is no options execution path",
    "no trading.",
    "no order execution",
)

# A statement scoped to a module, a package, or the paper ledger stays true and must pass.
_SCOPING_MARKERS = (
    "this ledger",
    "this package",
    "this module",
    "signalforge.execution",
    "adr-execution-layer",
    "outside",
)


def find_unconditional_no_order_claims(text: str) -> list[str]:
    lowered = text.lower()
    hits = []
    for phrase in UNCONDITIONAL_NO_ORDER_PHRASES:
        start = lowered.find(phrase)
        if start == -1:
            continue
        window = lowered[max(0, start - 160) : start + len(phrase) + 160]
        if any(marker in window for marker in _SCOPING_MARKERS):
            continue
        hits.append(phrase)
    return hits


def test_t9_scan_distinguishes_absolute_from_scoped_claims() -> None:
    assert find_unconditional_no_order_claims("No orders are ever placed.")
    assert find_unconditional_no_order_claims(
        "Paper-trading ledger (SIMULATED).\n\nNo order is ever placed.\n"
    )
    assert not find_unconditional_no_order_claims(
        "Paper-trading ledger (SIMULATED — this ledger places no order; "
        "order placement lives in signalforge.execution, see ADR-execution-layer)."
    )
    assert not find_unconditional_no_order_claims(
        "No brokerage connection exists outside signalforge.execution (ADR-execution-layer)."
    )


def _docstrings_and_help_strings(path: Path) -> Iterator[str]:
    """Module docstrings plus every Typer/argparse ``help=``-style string in the file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    doc = ast.get_docstring(tree)
    if doc:
        yield doc
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.keyword)
            and node.arg in {"help", "short_help", "description"}
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            yield node.value.value


def test_t9_no_unconditional_no_order_promise_once_execution_exists() -> None:
    if not execution_package_exists():
        _requires_ie2(
            "signalforge.execution — the §18 amendment of the shipped strings lands with it"
        )
    offenders: list[str] = []
    for path in iter_source_files():
        for text in _docstrings_and_help_strings(path):
            hits = find_unconditional_no_order_claims(text)
            if hits:
                offenders.append(f"{path}: {hits}")
    assert (
        not offenders
    ), "Unconditional no-order promises still shipped in the binary (ADR §18):\n" + "\n".join(
        offenders
    )


# ---------------------------------------------------------------------------
# T10 / T11 — paper_reference output is never evidence; credentials never reach a log.
# ---------------------------------------------------------------------------


def test_t10_paper_reference_fills_are_excluded_from_every_gate() -> None:
    _requires_ie2("signalforge.execution.brokers.paper_reference and the execution_event table")


def test_t11_credential_value_reaches_no_log_and_no_execution_event() -> None:
    _requires_ie2("signalforge.execution.credentials")


# ---------------------------------------------------------------------------
# T12 — signalforge.cli is the ONLY static import path into the execution layer.
# ---------------------------------------------------------------------------


def test_t12_only_the_cli_reaches_the_execution_layer() -> None:
    graph = build_import_graph()
    allowed = {SANCTIONED_INBOUND_MODULE}
    offenders = []
    for module, targets in sorted(graph.items()):
        if module == EXECUTION_MODULE or module.startswith(EXECUTION_PREFIX):
            continue
        reaches = any(t == EXECUTION_MODULE or t.startswith(EXECUTION_PREFIX) for t in targets)
        if reaches and module not in allowed:
            offenders.append(module)
    assert (
        not offenders
    ), "modules other than signalforge.cli import signalforge.execution: " + ", ".join(offenders)
    for package in (*T1_SOURCE_PACKAGES, "signalforge.scheduler"):
        assert (
            chain_to_execution(graph, package) is None
        ), f"{package} reaches the execution layer; signalforge.cli must be the only inbound edge"


def test_t12_scheduler_and_app_name_the_execution_layer_nowhere() -> None:
    """D6 §2: the job spec is injected from the CLI; scheduler.py and app/** gain no edge."""
    paths = [PKG_ROOT / "scheduler.py", *sorted((PKG_ROOT / "app").rglob("*.py"))]
    offenders = [str(p) for p in paths if EXECUTION_MODULE in p.read_text(encoding="utf-8")]
    assert (
        not offenders
    ), "signalforge.execution is named in the scheduler or the app (D6 §2, Q11): " + ", ".join(
        offenders
    )


# ---------------------------------------------------------------------------
# The contracts themselves — a contract nobody checks is a contract nobody has.
# ---------------------------------------------------------------------------


def _contracts() -> list[dict[str, object]]:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["tool"]["importlinter"]["contracts"]


def _contract(prefix: str) -> dict[str, object] | None:
    for contract in _contracts():
        name = contract.get("name", "")
        if isinstance(name, str) and name.startswith(prefix):
            return contract
    return None


def test_s15b_contract_is_present_and_indirect_chains_are_not_allowed() -> None:
    contract = _contract("S15b:")
    assert contract is not None, "the S15b contract is gone from pyproject.toml"
    assert contract["forbidden_modules"] == [EXECUTION_MODULE]
    sources = contract["source_modules"]
    assert isinstance(sources, list)
    expected = {
        "signalforge.llm",
        "signalforge.agents",
        "signalforge.app",
        "signalforge.research",
        "signalforge.alerts",
        "signalforge.sf1000",
        "signalforge.backtest",
        "signalforge.paper",
        "signalforge.portfolio",
        "signalforge.scheduler",
    }
    assert expected <= set(sources), f"S15b lost sources: {sorted(expected - set(sources))}"
    assert (
        SANCTIONED_INBOUND_MODULE not in sources
    ), "signalforge.cli is the one sanctioned inbound edge (ADR §17.2 note 2)"
    assert "allow_indirect_imports" not in contract, (
        "allow_indirect_imports on S15b would hide app -> scheduler -> execution and any "
        "anything -> cli -> execution chain; the ADR forbids taking that way out of a red build"
    )


def test_s14_names_the_execution_layer() -> None:
    contract = _contract("S14:")
    assert contract is not None
    forbidden = contract["forbidden_modules"]
    assert isinstance(forbidden, list)
    assert EXECUTION_MODULE in forbidden, "S14 must name signalforge.execution (ADR §17.2)"
    assert contract.get("ignore_imports") == [
        "signalforge.llm.client -> httpx"
    ], "S14 gained a new ignore_imports exception; the ADR adds none"


def test_s15a_contract_is_active_once_execution_exists() -> None:
    """S15a is staged (commented out) only while the package does not exist. See pyproject.toml.

    import-linter 2.15 raises ``Module 'signalforge.execution' does not exist.`` for a missing
    *source* module, so S15a cannot be live before I-E2 without failing ``make lint``. The
    moment the package lands, this fails until the block is uncommented.
    """
    contract = _contract("S15a:")
    if not execution_package_exists():
        assert contract is None, (
            "S15a is active while signalforge.execution does not exist — lint-imports will "
            "fail with \"Module 'signalforge.execution' does not exist.\""
        )
        text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert (
            '# name = "S15a:' in text
        ), "the staged S15a contract block is missing from pyproject.toml"
        return
    assert contract is not None, (
        "signalforge.execution exists but S15a is still commented out in pyproject.toml — "
        "uncomment the staged block (D6 ADR §17.2)"
    )
    assert contract["source_modules"] == [EXECUTION_MODULE]
    assert set(contract["forbidden_modules"]) == {
        "signalforge.llm",
        "signalforge.agents",
        "signalforge.alerts",
        "signalforge.research.scan",
        "signalforge.sf1000",
    }
    assert "allow_indirect_imports" not in contract


def test_s1_ruff_and_importlinter_denylists_are_not_shortened() -> None:
    """R4: §17.1 keeps all five names in both mechanisms. Nothing is removed for execution."""
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    banned_api = data["tool"]["ruff"]["lint"]["flake8-tidy-imports"]["banned-api"]
    expected = {"ib_insync", "ibapi", "alpaca_trade_api", "selenium", "ccxt"}
    assert set(banned_api) == expected
    s1 = _contract("S1:")
    assert s1 is not None
    assert set(s1["forbidden_modules"]) == expected
    assert s1["source_modules"] == ["signalforge"]
