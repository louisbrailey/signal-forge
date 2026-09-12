"""Options activation guards: exactly one guarded entry point, by PATH.

The twin of ``test_activation_guards.py``'s
``test_automatic_acceptance_has_exactly_one_guarded_entry_point``, specified by
**path equality, never by basename**. The existing equity test matched
``p.name in {"ledger.py", "cli.py"}`` — a ``Path.name``, so any file anywhere
under ``src/signalforge`` called ``ledger.py`` or ``cli.py`` could call
``accept_candidate`` and the suite stayed green (``agents/cli.py`` is the obvious
example, and the agents layer is live). That hole is repaired in
``test_activation_guards.py`` in the same commit, because this twin is copied
from it, and the repair is strictly more restrictive.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "signalforge"

#: Compared as ``rel == ...``, never ``p.name in ...``.
#: ``app/routers/`` is deliberately NOT here: the equity precedent it would copy
#: is ``app/routers/dashboard.py``'s unguarded ``accept_candidate`` call, and an
#: HTTP route that can open an options structure is not a Phase 1 surface.
OPTIONS_ACCEPT_CALLERS = {
    "paper/options_ledger.py",
    "paper/options_auto_simulate.py",
}
OPTIONS_AUTO_SIM_CALLERS = {"paper/options_auto_simulate.py", "scheduler.py"}


def _sources() -> list[tuple[str, str]]:
    return [(str(p.relative_to(SRC)), p.read_text()) for p in SRC.rglob("*.py")]


def test_the_options_acceptance_has_exactly_one_guarded_entry_point() -> None:
    for rel, text in _sources():
        if "accept_options_candidate(" in text:
            assert rel in OPTIONS_ACCEPT_CALLERS, (
                f"{rel} must not open options structures; the acceptance is reachable only "
                "through the second guard"
            )
        if "auto_simulate_options_scan_runs(" in text:
            assert rel in OPTIONS_AUTO_SIM_CALLERS, f"{rel} may not invoke options auto-simulation"


def test_the_second_guard_precedes_the_acceptance_in_source_order() -> None:
    src = (SRC / "paper" / "options_auto_simulate.py").read_text()
    assert src.index("assert_options_auto_simulate_allowed(") < src.index(
        "accept_options_candidate("
    )


def test_the_options_branch_is_reachable_through_no_other_door() -> None:
    """The only caller of the acceptance outside its own module is the
    auto-simulation sibling, and that sibling calls the SECOND guard — never
    ``assert_auto_simulate_allowed``, which now refuses an options candidate."""
    auto = (SRC / "paper" / "options_auto_simulate.py").read_text()
    code = "\n".join(
        line for line in auto.splitlines() if not line.lstrip().startswith(("#", '"', "*"))
    )
    assert "assert_auto_simulate_allowed(" not in code
    assert "from signalforge.paper.ledger import" not in auto
    assert "accept_candidate(" not in code.replace("accept_options_candidate(", "")


def test_the_only_scheduled_caller_is_the_options_eod_chain() -> None:
    """W3c REPLACES I-O6's ``test_there_is_no_scheduled_caller_yet``.

    I-O6 asserted ``"auto_simulate_options_scan_runs(" not in scheduler.py`` and
    said, in the assertion's own docstring, exactly what would have to be true
    before that line could be deleted: the wiring must land *with* the mark /
    reconcile / expiry step in FRONT of it, because the second guard's condition
    AA refuses without a dated, clean reconciliation report for the fill session,
    so a scan wired in ahead of that step would refuse everything — safe, but not
    the same as wired correctly.

    That is the change this test now pins, rather than the absence it used to.
    The negative assertion is kept in the strongest form still available: the
    scheduler invokes the options auto-simulation EXACTLY ONCE, from
    ``job_options_paper_eod``, it never calls the acceptance directly, and the
    three protective steps precede the auto-simulation in source order inside
    that one job.
    """
    sched = (SRC / "scheduler.py").read_text()
    assert "accept_options_candidate(" not in sched
    assert sched.count("auto_simulate_options_scan_runs(") == 1

    body = sched[sched.index("def job_options_paper_eod(") :]
    body = body[: body.index("\ndef ", 1)]  # up to the next top-level def
    order = [
        body.index("mark_options_to_market("),
        body.index("reconcile_options_collateral("),
        body.index("process_option_expiries("),
        body.index("auto_simulate_options_scan_runs("),
    ]
    assert order == sorted(order), "mark -> reconcile -> expiry -> auto-simulate, in that order"


def test_the_equity_caller_allowlist_is_repaired_to_path_equality() -> None:
    """The template this twin is copied from must not keep its basename hole."""
    existing = (Path(__file__).parent / "test_activation_guards.py").read_text()
    assert "p.name in manual_ok" not in existing
    assert 'manual_ok = {"paper/ledger.py", "cli.py"}' in existing
    assert "rel in manual_ok" in existing


def test_every_contract_naming_the_equity_ledger_also_names_the_options_siblings() -> None:
    """The meta-test of D3 §12.1.

    An import-linter *forbidden* contract matches a module **and its
    descendants**. ``signalforge.paper.options_ledger`` is a SIBLING of
    ``signalforge.paper.ledger``, not a descendant, so every contract that named
    only ``paper.ledger`` left the options decision path uncovered. This asserts
    the repair holds for every such contract, so the next sibling module cannot
    quietly reopen the hole and a future edit that reverts the tightening fails
    CI rather than passing it.
    """
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    contracts = data["tool"]["importlinter"]["contracts"]
    siblings = {
        "signalforge.paper.options_ledger",
        "signalforge.paper.options_marks",
        "signalforge.paper.options_auto_simulate",
    }
    checked = 0
    for contract in contracts:
        forbidden = set(contract.get("forbidden_modules") or ())
        if "signalforge.paper.ledger" not in forbidden:
            continue
        checked += 1
        assert siblings <= forbidden or "signalforge.paper" in forbidden, (
            f"{contract['name']!r} names signalforge.paper.ledger but leaves its options "
            f"siblings uncovered: missing {sorted(siblings - forbidden)}"
        )
    assert checked >= 4, f"expected at least 4 contracts naming paper.ledger, found {checked}"


def test_the_reverse_direction_contract_exists_and_names_every_options_module() -> None:
    """Nothing in the pre-existing set covered the INBOUND direction:
    ``signalforge.llm`` is never a *source* module anywhere, it appears only as a
    forbidden target, so nothing stopped ``llm -> paper.options_ledger``."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    contracts = data["tool"]["importlinter"]["contracts"]
    s16 = next((c for c in contracts if c["name"].startswith("S16")), None)
    assert s16 is not None, "the reverse-direction options contract is missing"
    assert set(s16["forbidden_modules"]) == {
        "signalforge.paper.options_ledger",
        "signalforge.paper.options_marks",
        "signalforge.paper.options_auto_simulate",
    }
    assert {
        "signalforge.llm",
        "signalforge.agents",
        "signalforge.app",
        "signalforge.alerts",
    } <= set(s16["source_modules"])


def test_the_options_modules_import_the_shared_maths_and_nothing_from_the_llm_layer() -> None:
    for name in ("options_ledger.py", "options_marks.py", "options_auto_simulate.py"):
        text = (SRC / "paper" / name).read_text()
        assert "signalforge.llm" not in text, name
        assert "signalforge.alerts" not in text, name
    assert "signalforge.options" in (SRC / "paper" / "options_ledger.py").read_text()
