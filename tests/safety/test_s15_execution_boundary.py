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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy.orm import Session

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
# The paper_reference adapter (I-E3). T6, T10 and T11 need it, so building one
# lives here once. Every argument is required by the adapter itself: there is no
# default account, information set or audit sink to fall back to.
# ---------------------------------------------------------------------------

PAPER_REFERENCE_DRILL_NOW = datetime(2026, 9, 11, 15, 0, tzinfo=UTC)


def _paper_reference_adapter(audit: object, *, expected_account_id: str) -> object:
    from signalforge.execution.brokers.paper_reference import (
        InMemoryBook,
        PaperReferenceBroker,
        PreSubmissionInformation,
        ReferenceQuote,
        SimulatedAccount,
    )
    from signalforge.execution.intents import MarketClock

    earlier = PAPER_REFERENCE_DRILL_NOW - timedelta(minutes=1)
    return PaperReferenceBroker(
        audit=audit,  # type: ignore[arg-type]
        account=SimulatedAccount(account_id="PAPER-SIM-DRILL-1", initial_cash=25_000.0),
        expected_account_id=expected_account_id,
        information=PreSubmissionInformation.of([ReferenceQuote("SPY", 470.0, earlier)]),
        clock=MarketClock(is_open=True, as_of=PAPER_REFERENCE_DRILL_NOW),
        book=InMemoryBook(),
    )


def _drill_intent(client_order_id: str, *, limit_price: float = 471.0) -> object:
    from signalforge.execution.intents import (
        CostModelFeedback,
        IntentKind,
        OrderIntent,
        OrderSide,
    )

    return OrderIntent(
        client_order_id=client_order_id,
        intent_kind=IntentKind.OPEN,
        side=OrderSide.BUY_TO_OPEN,
        qty=10,
        limit_price=limit_price,
        shares_per_contract=1,
        adapter_name="paper_reference",
        created_at=PAPER_REFERENCE_DRILL_NOW,
        expires_at=PAPER_REFERENCE_DRILL_NOW + timedelta(minutes=15),
        cost_model=CostModelFeedback(modelled_fill_price=limit_price, modelled_spread_bps=5.0),
        symbol="SPY",
    )


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

    # I-E2 landed build_open_intent. Two facts are asserted here; the behavioural
    # proof of each precondition (a DB-backed refusal per P1..P7) lives in
    # tests/execution/test_open_preconditions.py and is required to exist by name.
    import inspect

    from signalforge.execution import intents

    src = inspect.getsource(intents.build_open_intent)
    refused = set(re.findall(r'_refuse\(\s*"(P[1-7])"', src)) | set(
        re.findall(r'_guarded\(\s*"(P[1-7])"', src)
    )
    missing = {f"P{n}" for n in range(1, 8)} - refused
    assert not missing, f"build_open_intent no longer refuses on {sorted(missing)} (ADR §5)"

    proofs = (
        PKG_ROOT.parent.parent / "tests" / "execution" / "test_open_preconditions.py"
    ).read_text(encoding="utf-8")
    unproven = [f"P{n}" for n in range(1, 8) if not re.search(rf"^def test_p{n}_", proofs, re.M)]
    assert not unproven, f"no behavioural test for {unproven} in test_open_preconditions.py"

    # And the one precondition needing no database: an OPEN intent cannot carry a closing side.
    from signalforge.execution.intents import IntentRefused, OrderSide

    with pytest.raises(IntentRefused, match="P0"):
        intents.build_open_intent(
            None,  # type: ignore[arg-type]  # refused before the session is touched
            paper_trade_id=1,
            adapter_name="paper_reference",
            side=OrderSide.SELL_TO_CLOSE,
            qty=1,
            limit_price=1.0,
            cost_model=intents.CostModelFeedback(1.0, 0.0),
            limit_decision=None,
            now=datetime(2026, 1, 1, tzinfo=UTC),
            max_intent_age_minutes=30,
            session_end_utc=None,
        )


# ---------------------------------------------------------------------------
# T3 — client_order_id is stable across retries and distinct across structures.
# ---------------------------------------------------------------------------


def test_t3_client_order_id_is_stable_across_retries() -> None:
    from signalforge.execution.intents import (
        IntentRefused,
        OrderLeg,
        OrderSide,
        client_order_id_for,
    )

    def leg(
        symbol: str = "AAPL", side: OrderSide = OrderSide.BUY_TO_OPEN, ratio: int = 1
    ) -> OrderLeg:
        return OrderLeg(side=side, ratio=ratio, shares_per_contract=1, symbol=symbol)

    base = client_order_id_for(source_trade_id=7, legs=[leg()])
    # Stable across retries: the same (trade, structure) always hashes to the same id.
    assert client_order_id_for(source_trade_id=7, legs=[leg()]) == base
    # Distinct across trades and across structures (symbol, side, ratio, leg count).
    others = {
        client_order_id_for(source_trade_id=8, legs=[leg()]),
        client_order_id_for(source_trade_id=7, legs=[leg("MSFT")]),
        client_order_id_for(source_trade_id=7, legs=[leg(side=OrderSide.SELL_TO_OPEN)]),
        client_order_id_for(source_trade_id=7, legs=[leg(ratio=2)]),
        client_order_id_for(source_trade_id=7, legs=[leg(), leg("MSFT")]),
    }
    assert base not in others and len(others) == 5
    with pytest.raises(IntentRefused):
        client_order_id_for(source_trade_id=7, legs=[])


# ---------------------------------------------------------------------------
# T4 — default-disabled, and importing the package touches no network and no credential.
# ---------------------------------------------------------------------------


_T4_CLEAN_IMPORT = """
import importlib, os, pkgutil, socket, subprocess, sys


def _blocked(*args, **kwargs):
    raise RuntimeError("network or subprocess at import time")


class _BlockedSocket(socket.socket):
    def __init__(self, *a, **k):
        raise RuntimeError("network or subprocess at import time")


socket.socket = _BlockedSocket  # stays a class so ssl.SSLSocket(socket) still imports
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
    """D6 §13 / drill V9, asserted against ``paper_reference`` as §13 requires.

    The arming ceremony itself is I-E4; what exists today is the proof and the
    gate that consumes it, and all four links of the chain are asserted so that
    the ceremony has nothing left to get wrong:

    1. a stubbed broker response whose account id differs from the armed
       record's produces an **unproven** proof, with the mismatch named;
    2. an ``IsPaperProof`` cannot be *constructed* as proven with a mismatched
       account id, so no code path can hand the ceremony a forged proof;
    3. an unproven proof fails ``may_open``'s A2 check — the input the arming
       ceremony and every cycle feed;
    4. and it fails **every subsequent submission**, not merely arming.

    The local simulator can never reach real money. That is emphatically not
    why the proof passes: a proof that passed because the adapter "is paper"
    would be the config-flag proof §13 rejects.
    """
    from signalforge.execution.limits import may_open
    from signalforge.execution.protocol import IsPaperProof
    from signalforge.execution.states import OrderState
    from tests.execution.conftest import clean_limit_set, clean_open_context

    class _Sink:
        def record(self, event_type: object, /, **fields: object) -> None:
            return None

    # 1 — the armed record expects one account; the broker's body reports another.
    adapter = _paper_reference_adapter(_Sink(), expected_account_id="PAPER-SIM-SOMEONE-ELSE")
    proof = adapter.is_paper()  # type: ignore[attr-defined]
    assert proof.proven is False
    assert "does not match" in proof.failure_reason

    # 2 — the mismatch cannot be asserted away by constructing a "proven" proof.
    with pytest.raises(ValueError, match="observed account id matches"):
        IsPaperProof(
            proven=True,
            observed_account_id="PAPER-SIM-DRILL-1",
            observed_host="local.paper-reference.invalid",
            expected_account_id="PAPER-SIM-SOMEONE-ELSE",
            checked_at=PAPER_REFERENCE_DRILL_NOW,
        )

    # 3 — arming and every cycle read this gate, and it blocks.
    decision = may_open(
        clean_open_context(is_paper_proven_this_cycle=proof.proven), clean_limit_set()
    )
    assert decision.allowed is False
    assert any(check.name == "A2" for check in decision.failures)
    # The same context with a proven proof is otherwise clean, so A2 is what bit.
    assert may_open(clean_open_context(), clean_limit_set()).allowed is True

    # 4 — and every submission is refused while the proof fails.
    result = adapter.place(_drill_intent("cid-mismatch"))  # type: ignore[attr-defined]
    assert result.state is OrderState.REJECTED
    assert "is_paper proof failed" in result.error_verbatim
    assert adapter.fills_for("cid-mismatch") == ()  # type: ignore[attr-defined]

    # 5 — an ABSENT account id is equally refused: "absent" is not "matching" (§13).
    with pytest.raises(ValueError):
        IsPaperProof(
            proven=True,
            observed_account_id="",
            observed_host="paper.example.invalid",
            expected_account_id="PAPER-ACCOUNT-1",
            checked_at=PAPER_REFERENCE_DRILL_NOW,
        )

    # 6 — the arming ceremony (I-E4) compares the OBSERVED id against the id the
    # operator typed, and treats a missing proof as a failure, not an absence.
    import inspect

    from signalforge.execution.arming import check_arming_preconditions

    source = inspect.getsource(check_arming_preconditions)
    assert "is_paper_proof is None" in source
    assert "observed_account_id != request.broker_account_id_expected" in source


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

# A statement scoped to the execution package by name, or to the paper ledger, stays true.
_SCOPING_MARKERS = (
    "this ledger",
    "signalforge.execution",
    "adr-execution-layer",
    "outside",
)

# "this package" / "this module" scope a claim to the file that makes it — but only when that
# file speaks for a PART of the tree. In ``src/signalforge/__init__.py`` "this package" is the
# whole distribution, ``signalforge.execution`` included, so the promise there is exactly as
# unconditional as one with no marker at all; the same goes for a repo-root document that
# speaks for the project. Treating those two words as scoping everywhere gave the root
# docstring ("It never connects to a brokerage, never places an order") a free pass, which is
# the one file §18's rule least intends to excuse.
_SELF_SCOPING_MARKERS = ("this package", "this module")


def find_unconditional_no_order_claims(
    text: str, *, speaks_for_whole_project: bool = False
) -> list[str]:
    """Return the unconditional no-order phrases in ``text``.

    ``speaks_for_whole_project`` drops the self-scoping markers, for the root package
    docstring and the repo-root promise documents. Every occurrence of every phrase is
    checked, not just the first: a scoped sentence early in a file must not excuse an
    absolute one later in it.
    """
    markers = (
        _SCOPING_MARKERS if speaks_for_whole_project else _SCOPING_MARKERS + _SELF_SCOPING_MARKERS
    )
    lowered = text.lower()
    hits = []
    for phrase in UNCONDITIONAL_NO_ORDER_PHRASES:
        start = lowered.find(phrase)
        while start != -1:
            window = lowered[max(0, start - 160) : start + len(phrase) + 160]
            if not any(marker in window for marker in markers):
                hits.append(phrase)
                break
            start = lowered.find(phrase, start + 1)
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


def test_t9_this_package_does_not_excuse_the_root_docstring() -> None:
    """The whole-project reading of "this package" is not a scope (see _SELF_SCOPING_MARKERS)."""
    root_style = (
        "Signal Forge — paper-trading-only research platform.\n\n"
        "This package produces hypothetical research output only. It never connects to a "
        "brokerage, never places an order, and never automates a trading venue.\n"
    )
    assert find_unconditional_no_order_claims(root_style, speaks_for_whole_project=True), (
        "the root package docstring's promise must NOT be excused by its own words "
        '"this package" — there it means the whole tree, execution included'
    )
    # A genuine subpackage keeps the exemption: signalforge.options really does hold no order path.
    assert not find_unconditional_no_order_claims(
        "Options — education and simulation only.\n\n"
        "There is no options execution path anywhere in this package.\n"
    )


def test_t9_a_scoped_sentence_does_not_excuse_a_later_absolute_one() -> None:
    text = (
        "Paper-trading ledger (SIMULATED — this ledger places no order).\n\n"
        + "filler. " * 60
        + "\nNo order is ever placed.\n"
    )
    assert find_unconditional_no_order_claims(text), (
        "only the first occurrence of each phrase was checked; a scoped sentence early in a "
        "file excused an absolute one later"
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


# §18 names README.md and DISCLAIMER.md among the files the amendment commit must reach, and
# DISCLAIMER.md's "No orders are ever placed." is called out there as "the single most-read
# promise in the repo". `iter_source_files()` walks src/signalforge only, so neither would ever
# have been scanned. They are scanned here for the same reason T9 exists at all: a decision
# record that says a promise is mechanically guarded must be telling the truth about it.
ROOT_PROMISE_DOCUMENTS = ("README.md", "DISCLAIMER.md")


def test_t9_no_unconditional_no_order_promise_once_execution_exists() -> None:
    if not execution_package_exists():
        _requires_ie2(
            "signalforge.execution — the §18 amendment of the shipped strings lands with it"
        )
    root_init = PKG_ROOT / "__init__.py"
    offenders: list[str] = []
    for path in iter_source_files():
        for text in _docstrings_and_help_strings(path):
            hits = find_unconditional_no_order_claims(
                text, speaks_for_whole_project=path == root_init
            )
            if hits:
                offenders.append(f"{path}: {hits}")
    for name in ROOT_PROMISE_DOCUMENTS:
        doc = REPO_ROOT / name
        hits = find_unconditional_no_order_claims(
            doc.read_text(encoding="utf-8"), speaks_for_whole_project=True
        )
        if hits:
            offenders.append(f"{doc}: {hits}")
    assert (
        not offenders
    ), "Unconditional no-order promises still shipped in the binary (ADR §18):\n" + "\n".join(
        offenders
    )


# ---------------------------------------------------------------------------
# T10 / T11 — paper_reference output is never evidence; credentials never reach a log.
# ---------------------------------------------------------------------------


#: Every table a promotion gate, ``strategy_health``, an expectancy figure or
#: decision 10's closed-trade count reads. ``paper_reference`` must write to
#: none of them.
EVIDENCE_TABLES = (
    "paper_trade",
    "paper_order",
    "paper_fill",
    "paper_position",
    "strategy_health",
    "strategy_promotion_evaluation",
    "strategy_sealed_test",
    "backtest_run",
    "backtest_trade",
    "backtest_metric",
)


def test_t10_paper_reference_fills_are_excluded_from_every_gate(session: Session) -> None:
    """D6 §3.1 rule 4, against a fixture whose fills WOULD otherwise satisfy the
    arming precondition.

    Decision 10 requires ">= 20 closed paper trades with non-negative
    expectancy". The drill below closes 25 — more than enough — and the
    exclusion is asserted in the two forms that matter:

    * **the filter has something to bite on**: every row the adapter writes
      carries ``adapter_name = 'paper_reference'``, so excluding it removes all
      25 and leaves nothing;
    * **the stronger structural fact**: the adapter writes to ``execution_event``
      and to nothing else. Not one row reaches ``paper_trade``,
      ``strategy_health``, a promotion evaluation or a backtest table, so no
      gate that reads those tables can see a simulated fill at all — the
      exclusion does not depend on every future counter remembering to filter.

    And there is no statistic to count in the first place: the adapter marks its
    book at cost, so equity is identical before and after 25 filled structures.
    """
    from sqlalchemy import func, text
    from sqlalchemy import select as sa_select

    from signalforge.db.models import ExecutionEvent
    from signalforge.execution.brokers.paper_reference import ExecutionEventAudit

    adapter = _paper_reference_adapter(
        ExecutionEventAudit(session), expected_account_id="PAPER-SIM-DRILL-1"
    )
    equity_before = adapter.account().equity  # type: ignore[attr-defined]
    for index in range(25):
        # Distinct economics per structure: the adapter refuses a second order
        # with the SAME economics under a different id (the post-timeout
        # non-duplication guarantee), so 25 closed structures must be 25 real
        # ones rather than one order resubmitted 25 times.
        result = adapter.place(  # type: ignore[attr-defined]
            _drill_intent(f"drill-{index:02d}", limit_price=471.0 + index)
        )
        assert result.state.value == "FILLED"
    session.flush()

    total = session.scalar(sa_select(func.count()).select_from(ExecutionEvent))
    assert total and total >= 25
    not_paper_reference = session.scalar(
        sa_select(func.count())
        .select_from(ExecutionEvent)
        .where(ExecutionEvent.adapter_name != "paper_reference")
    )
    assert not_paper_reference == 0, (
        "the decision-10 counter filters on adapter_name; every row this adapter wrote must "
        "carry it, or the filter would silently admit a simulated fill"
    )

    for table in EVIDENCE_TABLES:
        count = session.execute(text(f"select count(*) from {table}")).scalar_one()
        assert count == 0, f"a paper_reference drill reached the evidence table {table}"

    assert adapter.account().equity == equity_before  # type: ignore[attr-defined]


T11_SENTINEL = "t11-sentinel-value-that-must-never-be-logged"  # pragma: allowlist secret


def test_t11_credential_value_reaches_no_log_and_no_execution_event(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D6 §16. T7 can only see source literals; this sees a RUNTIME value.

    A credential is read through ``credentials.py`` from a stubbed environment
    returning a known sentinel, and a full adapter drill then runs while the
    process holds it. The sentinel must appear in no structlog record and in no
    column or payload of any ``execution_event`` row.
    """
    import structlog
    from pydantic import SecretStr
    from sqlalchemy import select as sa_select

    from signalforge.db.models import ExecutionEvent
    from signalforge.execution import credentials as creds
    from signalforge.execution.brokers.paper_reference import ExecutionEventAudit

    monkeypatch.setenv("SF_EXECUTION_BROKER_KEY_ID", T11_SENTINEL)
    with structlog.testing.capture_logs() as captured:
        secret = creds.resolve_credential(
            creds.CredentialRef(creds.CredentialSource.ENV, "SF_EXECUTION_BROKER_KEY_ID")
        )
        adapter = _paper_reference_adapter(
            ExecutionEventAudit(session), expected_account_id="PAPER-SIM-DRILL-1"
        )
        adapter.is_paper()  # type: ignore[attr-defined]
        adapter.account()  # type: ignore[attr-defined]
        adapter.place(_drill_intent("t11"))  # type: ignore[attr-defined]
        adapter.order_status("t11")  # type: ignore[attr-defined]
        adapter.cancel_all()  # type: ignore[attr-defined]
    session.flush()

    assert isinstance(secret, SecretStr)
    assert secret.get_secret_value() == T11_SENTINEL, "the reader really did read the sentinel"
    assert captured, "there is log output to inspect, so the absence below is meaningful"
    assert T11_SENTINEL not in repr(captured)

    rows = session.scalars(sa_select(ExecutionEvent)).all()
    assert rows
    for row in rows:
        assert T11_SENTINEL not in repr(
            {column.name: getattr(row, column.name) for column in ExecutionEvent.__table__.columns}
        )


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
    assert set(cast("list[str]", contract["forbidden_modules"])) == {
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
    assert set(cast("list[str]", s1["forbidden_modules"])) == expected
    assert s1["source_modules"] == ["signalforge"]
