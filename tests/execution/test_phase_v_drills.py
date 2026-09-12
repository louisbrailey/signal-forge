"""The Phase V drills, as tests (D6 ADR §21).

``scripts/execution_drills.py`` is the runnable drill harness an operator uses
before an armed session; this module runs the **same functions**, one test per
drill, so CI fails the moment a drill stops passing. There is deliberately no
second copy of the assertions: a drill that is asserted differently in CI from
the way it is run by hand is two drills, and one of them is wrong.

Also here: the checks that keep
``docs/PREREGISTRATION_execution_limits_v1.md`` honest. §7b rule 1 makes that
document a hard precondition of arming, and the arming ceremony can only check
that a file with the right name exists. What it cannot check — that the
document states the row the code actually uses — is checked here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from scripts.execution_drills import (
    DRILL_NOW,
    DRILLS,
    Drill,
    run_drill,
)
from scripts.execution_drills import (
    LIMIT_GRID_CENTRES as SCRIPT_GRID_CENTRES,
)
from sqlalchemy.orm import Session

from tests.execution.conftest import LIMIT_GRID_CENTRES
from tests.support import REPO_ROOT

PREREGISTRATION_PATH = REPO_ROOT / "docs" / "PREREGISTRATION_execution_limits_v1.md"
PREREGISTRATION_ID = "PREREGISTRATION_execution_limits_v1"


@pytest.mark.parametrize("drill", DRILLS, ids=[d.name for d in DRILLS])
def test_phase_v_drill(drill: Drill, session: Session) -> None:
    result = run_drill(drill, session, DRILL_NOW)
    assert not result.error, f"{drill.name} raised:\n{result.error}"
    assert result.outcome.checks, f"{drill.name} asserted nothing"
    failures = [f"{c.label}: {c.detail}" for c in result.outcome.checks if not c.passed]
    assert not failures, f"{drill.name} — {drill.title}\n" + "\n".join(failures)


def test_every_adr_drill_is_implemented() -> None:
    """§21 lists V1–V19 by number. All nineteen must be here."""
    implemented = {d.name for d in DRILLS}
    missing = [f"V{n}" for n in range(1, 20) if f"V{n}" not in implemented]
    assert not missing, f"ADR §21 drills with no implementation: {missing}"
    assert {d.name for d in DRILLS if d.in_adr} == {f"V{n}" for n in range(1, 20)}


def test_the_drill_runner_refuses_a_live_looking_database() -> None:
    from scripts.execution_drills import LiveDatabaseRefused, refuse_if_live

    with pytest.raises(LiveDatabaseRefused):
        refuse_if_live(f"sqlite+pysqlite:///{REPO_ROOT / 'data' / 'signalforge.sqlite'}")
    with pytest.raises(LiveDatabaseRefused):
        refuse_if_live("sqlite+pysqlite:////somewhere/else/signalforge.sqlite")
    with pytest.raises(LiveDatabaseRefused):
        refuse_if_live("postgresql://host/db")
    refuse_if_live("sqlite+pysqlite:////tmp/scratch/drill.sqlite")


# ---------------------------------------------------------------------------
# The pre-registration document (§7b rule 1)
# ---------------------------------------------------------------------------


def _documented_values() -> dict[str, str]:
    """Parse ``| `column` | unit | **value** | ...` rows out of the document.

    The FIRST bold token in each row is the value; the rationale column may be
    bold too and must not be mistaken for one.
    """
    text = PREREGISTRATION_PATH.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells:
            continue
        head = re.fullmatch(r"`([A-Za-z_][A-Za-z0-9_]*)`", cells[0])
        if head is None or head.group(1) not in LIMIT_GRID_CENTRES:
            continue
        bold = re.search(r"\*\*(.+?)\*\*", line)
        if bold is None:
            continue
        out[head.group(1)] = bold.group(1).strip().strip("`")
    return out


def test_the_preregistration_document_exists_where_arming_looks_for_it() -> None:
    """The ceremony's S3 check is a stem match anywhere under ``docs/``."""
    from signalforge.execution.arming import _preregistration_exists

    assert PREREGISTRATION_PATH.exists(), PREREGISTRATION_PATH
    ok, detail = _preregistration_exists(PREREGISTRATION_ID)
    assert ok, detail
    assert detail.endswith("PREREGISTRATION_execution_limits_v1.md"), detail

    missing_ok, missing_detail = _preregistration_exists("PREREGISTRATION_execution_limits_v2")
    assert not missing_ok, "a v2 that does not exist yet must not resolve"
    assert "no pre-registration document" in missing_detail


def test_the_document_names_every_execution_limits_column() -> None:
    documented = _documented_values()
    missing = sorted(set(LIMIT_GRID_CENTRES) - set(documented))
    assert not missing, (
        "these execution_limits columns are not pre-registered in "
        f"{PREREGISTRATION_PATH.name}: {missing}. §7b rule 1 requires the COMPLETE row."
    )


def test_every_documented_value_equals_the_value_the_code_uses() -> None:
    documented = _documented_values()
    mismatches: list[str] = []
    for column, expected in LIMIT_GRID_CENTRES.items():
        stated = documented[column]
        if isinstance(expected, str):
            if stated != expected:
                mismatches.append(f"{column}: document says {stated!r}, code uses {expected!r}")
        elif float(stated.replace(",", "").lstrip("$")) != float(expected):
            mismatches.append(f"{column}: document says {stated}, code uses {expected}")
    assert not mismatches, "\n".join(mismatches)


def test_the_drill_runner_and_the_test_fixtures_agree_on_the_row() -> None:
    """Three copies of the grid centres exist — the suite's fixture, the drill
    runner's (scripts/ must not import tests/), and the document. All three are
    pinned to each other rather than trusted to stay in step."""
    assert SCRIPT_GRID_CENTRES == LIMIT_GRID_CENTRES


def test_the_document_carries_its_own_id_and_the_change_rule() -> None:
    text = PREREGISTRATION_PATH.read_text(encoding="utf-8")
    assert PREREGISTRATION_ID in text
    assert "PREREGISTRATION_execution_limits_v2" in text, "the v2 supersession rule must be stated"
    assert "pattern-day-trader" in text.lower() or "pattern day trader" in text.lower()
    assert "25,000" in text or "25000" in text
    assert "7 days" in text or "ARMING_EXPIRY_DAYS" in text


def test_the_document_matches_the_arming_expiry_the_code_enforces() -> None:
    from signalforge.execution.arming import ARMING_EXPIRY_DAYS

    text = PREREGISTRATION_PATH.read_text(encoding="utf-8")
    assert f"ARMING_EXPIRY_DAYS = {ARMING_EXPIRY_DAYS}" in text


def test_the_drill_report_directory_is_version_controlled() -> None:
    reports = REPO_ROOT / "docs" / "research" / "execution_drills"
    assert reports.is_dir(), "the drill runner writes its dated report here"
    assert any(p.suffix == ".md" for p in reports.iterdir()), (
        "at least one dated drill report must be committed: a drill suite with no recorded run "
        "is a claim, not evidence"
    )


def test_the_committed_report_records_a_full_pass() -> None:
    reports = sorted((REPO_ROOT / "docs" / "research" / "execution_drills").glob("DRILLS_*.md"))
    assert reports, "no dated drill report is committed"
    newest: Path = reports[-1]
    text = newest.read_text(encoding="utf-8")
    assert "**FAIL**" not in text, f"{newest.name} records a failing drill"
    assert re.search(rf"\*\*{len(DRILLS)}/{len(DRILLS)} PASS", text), (
        f"{newest.name} does not record a run of all {len(DRILLS)} drills; re-run "
        "`python scripts/execution_drills.py --all` and commit the report"
    )
