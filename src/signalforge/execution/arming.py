"""The arming ceremony and the auto-disarm sweep (D6 §12, decisions 4, 9, 10).

**Every step is an operator action. None is automated. None can be triggered by
a document, a message, a scan result, an agent, or an LLM.** Nothing is armed by
default, arming EXPIRES (7 days, decision 4), and there is no "resume":
re-arming is the full ceremony again.

``armed_strategy`` is deliberately not a fourth ``StrategyStatus``. It is a
separate record layered on top of PAPER_APPROVED so that no existing code path
can mistake it for "approved enough".

Three refusals in this module are worth naming on their own, because each one is
a hole the cheap version of this ceremony would leave open:

1. **The decision-10 evidence precondition** (>= 20 closed paper trades with
   non-negative expectancy under the health monitor) is evaluated by this code
   against the database, not asserted by the operator. The override exists —
   decision 10 grants it — but it is a separate flag, it requires a typed
   reason, and it **records the observed n and the observed expectancy
   alongside that reason**, because an override is by construction taken *after*
   seeing the outcome and what was seen is part of the record rather than
   context the operator is trusted to remember.
2. **The ``is_paper`` proof** (§13) must prove out THIS ceremony against the
   account id the operator typed out of band. A boolean derived from a local
   config flag is not proof: a misconfigured base URL is the single most likely
   way real money gets touched, and the flag and the URL are set in the same
   place by the same mistake.
3. **The account must be flat and empty at arm time** (§10). Arming into an
   account that already holds something is arming into either a shared account
   or an unresolved prior arming, and neither is a state to arm into. The rule
   is machine-checked here rather than left as an acknowledgement the operator
   reads.

Auto-disarm (decision 9: "**on any status change**, not only downgrades") is
implemented as a check at the top of **every cycle**, not as a database trigger.
The trade-off is stated rather than hidden: a cycle check sees the state at
cycle boundaries, so a status that changes and changes back between two cycles
is not observed by the status comparison alone. :func:`auto_disarm_sweep`
therefore ALSO reads the audit trail for a status transition recorded after
``armed_at``, which catches the flap on the one path that changes status
automatically (the health monitor).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING

from signalforge.execution.events import ExecutionEventType, record_execution_event
from signalforge.execution.limits import LimitCheck, LimitDecision

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.orm import Session

    from signalforge.db.models import ArmedStrategy
    from signalforge.execution.protocol import BrokerAdapter, IsPaperProof

__all__ = [
    "ARMING_EXPIRY_DAYS",
    "MIN_CLOSED_PAPER_TRADES",
    "ArmingRefused",
    "Disarm",
    "DisarmTrigger",
    "EvidenceAssessment",
    "arm",
    "auto_disarm_sweep",
    "check_arming_preconditions",
    "confirmation_phrase",
    "disarm",
    "evaluate_evidence",
    "live_armings",
]

#: Decision 4. There is no indefinite arming and no way to ask for one.
ARMING_EXPIRY_DAYS = 7

#: Decision 10, binding. Closed PAPER trades, counted by the health monitor's own
#: definition of a closed trade (``research.health_monitor.closed_paper_r_multiples``).
MIN_CLOSED_PAPER_TRADES = 20


class ArmingRefused(RuntimeError):
    """Arming or disarming was refused. The message names the FIRST failed
    condition, in the house shape of ``paper.ledger.AutoSimulateForbidden``."""


class DisarmTrigger(StrEnum):
    """§12 step 7's list, verbatim, plus the operator's own hand.

    Each value is written into ``armed_strategy.disarm_reason`` and into an
    ``execution_event``, so "why is this disarmed" is answered from the record
    rather than reconstructed.
    """

    OPERATOR = "operator"
    STATUS_CHANGE = "strategy_version_status_change"
    HASH_DRIFT = "spec_or_config_hash_drift"
    SCOPE_MISMATCH = "approved_scope_mismatch"
    KILL_SWITCH = "kill_switch_engaged"
    DEAD_MAN = "dead_man_lapse"
    RECONCILIATION = "reconciliation_divergence_or_staleness"
    UNKNOWN_OUTSTANDING = "unknown_intent_outstanding"
    IS_PAPER = "is_paper_failed_to_reprove"
    ORDER_CAP = "daily_order_cap_breach"
    EXPIRED = "expires_at_passed"


@dataclass(frozen=True, slots=True)
class Disarm:
    armed_strategy_id: int
    strategy_version_id: int
    trigger: DisarmTrigger
    detail: str


@dataclass(frozen=True, slots=True)
class EvidenceAssessment:
    """Decision 10's evidence, as measured — never as asserted.

    ``expectancy_r`` is ``None`` when there are no closed trades at all, which is
    distinct from an expectancy of 0.0 and must not be rendered as one.
    """

    n_closed: int
    expectancy_r: float | None
    sufficient: bool
    window_since: datetime | None
    detail: str


# ---------------------------------------------------------------------------
# Evidence (decision 10) — measured against the database
# ---------------------------------------------------------------------------


def evaluate_evidence(
    session: Session,
    strategy_version_id: int,
    *,
    limits_created_at: datetime | None = None,
) -> EvidenceAssessment:
    """>= 20 closed paper trades with non-negative expectancy under the health
    monitor (decision 10).

    ``limits_created_at`` implements §7b rule 3: superseding an
    ``execution_limits`` row RESETS this counter, because several of the timing
    parameters materially change realized fills and therefore the very
    expectancy this gate reads. Evidence accumulated under a different row is
    evidence about a different system, and inheriting it is the precise shape of
    an outcome-tuned gate.
    """
    from signalforge.research.health_monitor import closed_paper_r_multiples

    returns = closed_paper_r_multiples(session, strategy_version_id, closed_since=limits_created_at)
    n = len(returns)
    expectancy = (sum(returns) / n) if n else None
    window = (
        f" (counted since the active execution_limits row was created at "
        f"{limits_created_at.isoformat()})"
        if limits_created_at is not None
        else ""
    )
    if n < MIN_CLOSED_PAPER_TRADES:
        return EvidenceAssessment(
            n_closed=n,
            expectancy_r=expectancy,
            sufficient=False,
            window_since=limits_created_at,
            detail=(
                f"{n} closed paper trades < the {MIN_CLOSED_PAPER_TRADES} decision 10 "
                f"requires{window}"
            ),
        )
    if expectancy is None or expectancy < 0:
        return EvidenceAssessment(
            n_closed=n,
            expectancy_r=expectancy,
            sufficient=False,
            window_since=limits_created_at,
            detail=f"paper expectancy {expectancy:+.4f}R is negative over {n} closed trades",
        )
    return EvidenceAssessment(
        n_closed=n,
        expectancy_r=expectancy,
        sufficient=True,
        window_since=limits_created_at,
        detail=f"{n} closed paper trades, expectancy {expectancy:+.4f}R{window}",
    )


# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------


def live_armings(
    session: Session,
    *,
    adapter_name: str | None = None,
    strategy_version_id: int | None = None,
) -> list[ArmedStrategy]:
    """Every arming with no ``disarmed_at``. Expiry is NOT filtered here: an
    expired-but-not-yet-disarmed row is exactly what the sweep must find and
    disarm, and hiding it would make the expiry invisible to the one thing that
    acts on it."""
    from sqlalchemy import select

    from signalforge.db.models import ArmedStrategy

    stmt = select(ArmedStrategy).where(ArmedStrategy.disarmed_at.is_(None))
    if adapter_name is not None:
        stmt = stmt.where(ArmedStrategy.adapter_name == adapter_name)
    if strategy_version_id is not None:
        stmt = stmt.where(ArmedStrategy.strategy_version_id == strategy_version_id)
    return list(session.scalars(stmt.order_by(ArmedStrategy.id)))


def confirmation_phrase(strategy_version_id: int, adapter_name: str) -> str:
    """§12 step 5 requires a TYPED confirmation, not a y/N.

    The phrase names the version and the adapter, so a confirmation typed for
    one arming cannot be pasted into another.
    """
    return f"ARM {strategy_version_id} ON {adapter_name}"


def _scope_still_approved(
    session: Session, *, strategy_version_id: int, armed_like: object
) -> bool:
    """The armed hashes still correspond to a PASSING approved scope.

    The full five-part ``scan_scope_matches`` needs a live scan to match against
    and is re-run at intent time by ``build_open_intent`` (P4). What the arming
    ceremony and the sweep can check without a scan is the pair of hashes the
    approval was granted under, which is exactly what the 2026-09-11 config-hash
    incident moved.
    """
    from signalforge.research.approval_scope import approved_scopes

    config_hash = str(getattr(armed_like, "config_hash", "") or "")
    spec_hash = str(getattr(armed_like, "spec_json_hash", "") or "")
    snapshot_id = getattr(armed_like, "dataset_snapshot_id", None)
    scopes = approved_scopes(session, strategy_version_id)
    return any(
        s.config_hash == config_hash
        and s.spec_json_hash == spec_hash
        and (snapshot_id is None or s.dataset_snapshot_id == snapshot_id)
        for s in scopes
    )


def _live_hashes(session: Session, strategy_version_id: int) -> tuple[str, str]:
    """(live config hash, live spec hash) as they are RIGHT NOW.

    Both are recomputed rather than read off a stored column: ``config_hash``
    moved silently once already (the 2026-09-11 incident, fixed by commit
    ``0cc4cf4``), and a stored hash cannot detect its own drift.
    """
    from signalforge.research.approval_scope import current_spec_json_hash
    from signalforge.settings_store import effective_research_config

    config_hash = effective_research_config(session).config_hash
    spec_hash = current_spec_json_hash(session, strategy_version_id) or ""
    return config_hash, spec_hash


def _sealed_look_prior(session: Session, strategy_name: str) -> int:
    """``k`` at the moment risk is taken (§12 step 1).

    Counted per FAMILY, not per version: a v0.2.0 does not reset the
    multiple-testing budget its v0.1.0 already spent. Queried directly rather
    than through ``research.promotion`` so the execution layer keeps one narrow
    dependency on research state instead of importing the promotion engine.
    """
    from sqlalchemy import func, select

    from signalforge.db.models import Strategy, StrategySealedTest, StrategyVersion

    return int(
        session.scalar(
            select(func.count())
            .select_from(StrategySealedTest)
            .join(StrategyVersion, StrategyVersion.id == StrategySealedTest.strategy_version_id)
            .join(Strategy, Strategy.id == StrategyVersion.strategy_id)
            .where(Strategy.name == strategy_name)
        )
        or 0
    )


@dataclass(frozen=True, slots=True)
class ArmingRequest:
    """Everything §12 step 3's signed arming record names.

    Frozen and explicit: an arming assembled from defaults is an arming nobody
    typed, and every field here is one the operator must state.
    """

    strategy_version_id: int
    adapter_name: str
    broker_account_id_expected: str
    preregistration_doc_id: str
    max_notional_usd: float
    max_orders_per_day: int
    structure_type: str = "equity"
    options_approval_level: int | None = None
    expires_at: datetime | None = None
    override_evidence_reason: str = ""
    acknowledged: bool = False


def check_arming_preconditions(
    session: Session,
    request: ArmingRequest,
    *,
    now: datetime,
    is_paper_proof: IsPaperProof | None,
    account_is_flat: bool | None,
    limits_id: int | None = None,
    limits_created_at: datetime | None = None,
) -> LimitDecision:
    """Re-verify every step 1-3 precondition LIVE against the database.

    Returns the full table — every check, passed or failed — because §12 step 5
    prints it above the typed confirmation. ``arm()`` refuses on the first
    failure; this function never raises, so the operator sees *all* of what is
    wrong rather than fixing one thing per attempt.
    """
    from signalforge.db.models import Strategy, StrategySealedTest, StrategyVersion
    from signalforge.domain import StrategyStatus
    from signalforge.execution.oms import has_outstanding_unknown

    checks: list[LimitCheck] = []

    ver = session.get(StrategyVersion, request.strategy_version_id)
    if ver is None:
        return LimitDecision(
            allowed=False,
            checks=(
                LimitCheck(
                    "A0", False, f"strategy version {request.strategy_version_id} does not exist"
                ),
            ),
        )
    strat = session.get(Strategy, ver.strategy_id)
    checks.append(
        LimitCheck(
            "A0",
            strat is not None,
            f"{strat.name}@{ver.version}" if strat is not None else "orphaned strategy version",
        )
    )

    # --- step 1: PAPER_APPROVED with a sealed test traceable to a pre-registration
    checks.append(
        LimitCheck(
            "S1",
            ver.status is StrategyStatus.PAPER_APPROVED,
            (
                ""
                if ver.status is StrategyStatus.PAPER_APPROVED
                else f"status is {ver.status.value}, not PAPER_APPROVED"
            ),
        )
    )
    from sqlalchemy import select

    sealed = list(
        session.scalars(
            select(StrategySealedTest).where(
                StrategySealedTest.strategy_version_id == ver.id,
                StrategySealedTest.passed.is_(True),
            )
        )
    )
    checks.append(
        LimitCheck(
            "S2",
            bool(sealed),
            "" if sealed else "no PASSING sealed final test exists for this version",
        )
    )
    # The CLI REFUSES to arm a version whose sealed test is not traceable to a
    # pre-registration document that enumerated the full grid. The traceability
    # this code can machine-check is that the operator named a document that
    # EXISTS in the repository; that the document enumerated the grid is a
    # review fact, recorded on the arming row so a reviewer can check it.
    doc_ok, doc_detail = _preregistration_exists(request.preregistration_doc_id)
    checks.append(LimitCheck("S3", doc_ok, doc_detail))

    # --- step 2: decision 10's live paper evidence, or an audited override ----
    evidence = evaluate_evidence(session, ver.id, limits_created_at=limits_created_at)
    if request.override_evidence_reason:
        # Decision 10 grants the override. What it does not grant is an
        # unrecorded one: n and expectancy as OBSERVED are written beside the
        # reason, because the override is taken after seeing them.
        checks.append(
            LimitCheck(
                "S4",
                True,
                f"decision-10 evidence OVERRIDDEN by the operator: "
                f"{request.override_evidence_reason!r} (observed n={evidence.n_closed}, "
                f"expectancy="
                + (
                    f"{evidence.expectancy_r:+.4f}R"
                    if evidence.expectancy_r is not None
                    else "undefined"
                )
                + ")",
            )
        )
    else:
        checks.append(LimitCheck("S4", evidence.sufficient, evidence.detail))

    # --- step 3: the signed record, the account, the acknowledgements ---------
    checks.append(
        LimitCheck(
            "S5",
            bool(request.broker_account_id_expected),
            "" if request.broker_account_id_expected else "no expected broker account id was typed",
        )
    )
    checks.append(
        LimitCheck(
            "S6",
            request.acknowledged,
            (
                ""
                if request.acknowledged
                else "the four §12 step 3 acknowledgements were not confirmed"
            ),
        )
    )

    expires_at = request.expires_at or (now + timedelta(days=ARMING_EXPIRY_DAYS))
    max_expiry = now + timedelta(days=ARMING_EXPIRY_DAYS)
    if expires_at <= now:
        checks.append(LimitCheck("S7", False, "the requested expiry is already in the past"))
    elif expires_at > max_expiry:
        checks.append(
            LimitCheck(
                "S7",
                False,
                f"the requested expiry {expires_at.isoformat()} is beyond the "
                f"{ARMING_EXPIRY_DAYS}-day maximum (decision 4); there is no indefinite arming",
            )
        )
    else:
        checks.append(LimitCheck("S7", True, f"expires {expires_at.isoformat()}"))

    # --- §13: the is_paper proof, against the TYPED account id ---------------
    if is_paper_proof is None:
        checks.append(LimitCheck("S8", False, "no is_paper() proof was taken this ceremony"))
    elif not is_paper_proof.proven:
        checks.append(
            LimitCheck(
                "S8",
                False,
                "is_paper() did not prove out: "
                + (is_paper_proof.failure_reason or "no reason given"),
            )
        )
    elif is_paper_proof.observed_account_id != request.broker_account_id_expected:
        checks.append(
            LimitCheck(
                "S8",
                False,
                f"the broker's own response names account "
                f"{is_paper_proof.observed_account_id!r}, not the typed "
                f"{request.broker_account_id_expected!r}",
            )
        )
    else:
        checks.append(
            LimitCheck(
                "S8",
                True,
                f"account {is_paper_proof.observed_account_id} on "
                f"{is_paper_proof.observed_host}",
            )
        )

    # --- §10: one account per armed adapter, and it starts FLAT ---------------
    if account_is_flat is None:
        checks.append(
            LimitCheck("S9", False, "could not read the broker's positions/open orders at arm time")
        )
    else:
        checks.append(
            LimitCheck(
                "S9",
                account_is_flat,
                (
                    ""
                    if account_is_flat
                    else "the account already holds a position or an open order; arming begins "
                    "from a flat, empty account"
                ),
            )
        )

    already_armed_version = live_armings(session, strategy_version_id=ver.id)
    checks.append(
        LimitCheck(
            "S10",
            not already_armed_version,
            (
                ""
                if not already_armed_version
                else f"version {ver.id} already has a live arming (id "
                f"{already_armed_version[0].id}); disarm it first — there is no resume"
            ),
        )
    )
    account_clash = _account_already_armed(session, request.broker_account_id_expected)
    checks.append(
        LimitCheck(
            "S11",
            account_clash is None,
            (
                ""
                if account_clash is None
                else f"broker account {request.broker_account_id_expected!r} is already armed by "
                f"armed_strategy {account_clash}; one account per live arming (§10)"
            ),
        )
    )

    # --- §6 / §12 step 7: an outstanding UNKNOWN blocks ARMING ---------------
    unknown = has_outstanding_unknown(session, ver.id)
    checks.append(
        LimitCheck(
            "S12",
            not unknown,
            (
                ""
                if not unknown
                else "an UNKNOWN intent is outstanding for this strategy; it is cleared only by "
                "order_status() reconciliation AND an operator acknowledgement, never by a retry"
            ),
        )
    )

    # --- hashes and scope, re-read NOW --------------------------------------
    live_config, live_spec = _live_hashes(session, ver.id)
    checks.append(
        LimitCheck(
            "S13",
            bool(live_config) and bool(live_spec),
            (
                f"config_hash={live_config[:12]} spec_json_hash={live_spec[:12]}"
                if live_config and live_spec
                else "the live config/spec hashes could not be computed"
            ),
        )
    )
    armed_like = _HashesOnly(config_hash=live_config, spec_json_hash=live_spec)
    scope_ok = _scope_still_approved(session, strategy_version_id=ver.id, armed_like=armed_like)
    checks.append(
        LimitCheck(
            "S14",
            scope_ok,
            (
                ""
                if scope_ok
                else "no PASSING evaluation matches the live config_hash and spec_json_hash — "
                "the approval does not apply to what this code would run now"
            ),
        )
    )

    checks.append(
        LimitCheck(
            "S15",
            limits_id is not None,
            (
                f"execution_limits id={limits_id}"
                if limits_id is not None
                else "no active, parseable execution_limits row — a missing limits row is not "
                "'no limits'"
            ),
        )
    )

    return LimitDecision(allowed=all(c.passed for c in checks), checks=tuple(checks))


@dataclass(frozen=True, slots=True)
class _HashesOnly:
    config_hash: str
    spec_json_hash: str
    dataset_snapshot_id: int | None = None


def _preregistration_exists(doc_id: str) -> tuple[bool, str]:
    """§7b rule 1 / §12 step 1: no arming without a pre-registration document.

    The check is deliberately a file-existence check under ``docs/``: it proves
    the operator named something real and reviewable rather than typing a
    placeholder. It cannot prove the document enumerated the full grid — that is
    a review fact — so the id is recorded on the arming row where a reviewer can
    follow it.
    """
    from pathlib import Path

    if not doc_id:
        return False, "no pre-registration document id was named (§7b rule 1)"
    root = Path(__file__).resolve().parents[3] / "docs"
    if not root.exists():  # pragma: no cover - only in a stripped install
        return False, f"cannot verify {doc_id!r}: no docs/ tree in this install"
    stem = doc_id.removesuffix(".md")
    matches = [p for p in root.rglob("*.md") if p.stem == stem]
    if not matches:
        return False, f"no pre-registration document named {doc_id!r} exists under docs/"
    return True, str(matches[0].relative_to(root.parent))


def _account_already_armed(session: Session, account_id: str) -> int | None:
    if not account_id:
        return None
    for row in live_armings(session):
        if row.broker_account_id_expected == account_id:
            return row.id
    return None


# ---------------------------------------------------------------------------
# Arm / disarm
# ---------------------------------------------------------------------------


def arm(
    session: Session,
    request: ArmingRequest,
    *,
    now: datetime,
    is_paper_proof: IsPaperProof | None,
    account_is_flat: bool | None,
    actor: str,
    limits_id: int | None = None,
    limits_created_at: datetime | None = None,
) -> ArmedStrategy:
    """Write the arming record, or raise :class:`ArmingRefused` naming the first
    failed precondition.

    Writes an ``armed_strategy`` row, an ``execution_event`` and an
    ``audit.record`` — all three, because §15 requires both spines and the audit
    JSONL is the one that survives a database restore from before the arming.
    """
    from signalforge.db.models import ArmedStrategy, Strategy, StrategyVersion

    decision = check_arming_preconditions(
        session,
        request,
        now=now,
        is_paper_proof=is_paper_proof,
        account_is_flat=account_is_flat,
        limits_id=limits_id,
        limits_created_at=limits_created_at,
    )
    if not decision.allowed:
        record_execution_event(
            session,
            event_type=ExecutionEventType.INTENT_REFUSED,
            adapter_name=request.adapter_name,
            strategy_version_id=request.strategy_version_id,
            reason=f"arming refused — {decision.first_failure}",
            payload={"checks": [[c.name, c.passed, c.detail] for c in decision.checks]},
            actor=actor,
        )
        raise ArmingRefused(f"arming refused — {decision.first_failure}")

    ver = session.get(StrategyVersion, request.strategy_version_id)
    assert ver is not None  # S1/A0 above proved it
    strat = session.get(Strategy, ver.strategy_id)
    evidence = evaluate_evidence(session, ver.id, limits_created_at=limits_created_at)
    live_config, live_spec = _live_hashes(session, ver.id)
    expires_at = request.expires_at or (now + timedelta(days=ARMING_EXPIRY_DAYS))

    row = ArmedStrategy(
        strategy_version_id=ver.id,
        structure_type=request.structure_type,
        armed_at=now,
        armed_by=actor,
        expires_at=expires_at,
        adapter_name=request.adapter_name,
        broker_account_id_expected=request.broker_account_id_expected,
        options_approval_level_asserted=request.options_approval_level,
        max_notional_usd=request.max_notional_usd,
        max_orders_per_day=request.max_orders_per_day,
        # §12 step 2: whenever an override reason is set, what was OBSERVED is
        # part of the record — the override is by construction taken after
        # seeing it. The count is always written. The expectancy is written
        # whenever one exists; with zero closed trades there is no expectancy,
        # and writing 0.0 there would fabricate a measurement nobody made, so
        # the column stays NULL and the event payload says so explicitly.
        evidence_paper_trade_count=evidence.n_closed,
        evidence_expectancy_r=evidence.expectancy_r,
        evidence_override_reason=request.override_evidence_reason or None,
        sealed_look_prior_at_arm=_sealed_look_prior(session, strat.name) if strat else None,
        preregistration_doc_id=request.preregistration_doc_id,
        execution_limits_id=limits_id,
        spec_json_hash=live_spec,
        config_hash=live_config,
    )
    session.add(row)
    session.flush()

    record_execution_event(
        session,
        event_type=ExecutionEventType.ARMED,
        adapter_name=request.adapter_name,
        strategy_version_id=ver.id,
        armed_strategy_id=row.id,
        execution_limits_id=limits_id,
        config_hash=live_config,
        spec_json_hash=live_spec,
        reason=(
            f"armed until {expires_at.isoformat()} on {request.adapter_name} "
            f"(structure {request.structure_type})"
        ),
        payload={
            "expires_at": expires_at.isoformat(),
            "broker_account_id_expected": request.broker_account_id_expected,
            "options_approval_level_asserted": request.options_approval_level,
            "max_notional_usd": request.max_notional_usd,
            "max_orders_per_day": request.max_orders_per_day,
            "evidence_paper_trade_count": evidence.n_closed,
            "evidence_expectancy_r": evidence.expectancy_r,
            "evidence_override_reason": request.override_evidence_reason or None,
            "sealed_look_prior_at_arm": row.sealed_look_prior_at_arm,
            "preregistration_doc_id": request.preregistration_doc_id,
            "strategy_status_at_arm": ver.status.value,
            "checks": [[c.name, c.passed, c.detail] for c in decision.checks],
        },
        actor=actor,
    )
    return row


def disarm(
    session: Session,
    armed: ArmedStrategy,
    *,
    trigger: DisarmTrigger,
    detail: str,
    now: datetime,
    actor: str = "system",
) -> Disarm:
    """End the authority to open. The row is never deleted.

    Reconciliation and the ``is_paper`` proof read the most recent
    ``armed_strategy`` row for an adapter *including* disarmed and expired ones
    (§13 rule 4b): disarming ends the authority to open, not the record of which
    account this adapter was pointed at. Deleting the row would re-create the
    deadlock rev 1 of the ADR shipped.
    """
    if armed.disarmed_at is not None:
        return Disarm(
            armed_strategy_id=armed.id,
            strategy_version_id=armed.strategy_version_id,
            trigger=trigger,
            detail=f"already disarmed at {armed.disarmed_at.isoformat()}",
        )
    armed.disarmed_at = now
    armed.disarm_reason = f"{trigger.value}: {detail}"[:200]
    session.flush()
    record_execution_event(
        session,
        event_type=ExecutionEventType.DISARMED,
        adapter_name=armed.adapter_name,
        strategy_version_id=armed.strategy_version_id,
        armed_strategy_id=armed.id,
        execution_limits_id=armed.execution_limits_id,
        config_hash=armed.config_hash,
        spec_json_hash=armed.spec_json_hash,
        reason=armed.disarm_reason,
        payload={"trigger": trigger.value, "detail": detail},
        actor=actor,
    )
    return Disarm(
        armed_strategy_id=armed.id,
        strategy_version_id=armed.strategy_version_id,
        trigger=trigger,
        detail=detail,
    )


# ---------------------------------------------------------------------------
# The per-cycle auto-disarm sweep (§12 step 7, decision 9)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CycleFacts:
    """The cycle-level facts the sweep cannot read for itself.

    Every field is tri-state and ``None`` means "could not be evaluated". For a
    DISARM decision, ``None`` is deliberately **not** a trigger: disarming on an
    unevaluated fact would disarm the whole book on a transient read failure,
    while the ``may_open`` gate already blocks on exactly that ``None``. The
    fail-closed direction lives in the gate; the sweep acts only on facts it
    actually has.
    """

    kill_switch_engaged: bool | None = None
    execution_kill_engaged: bool | None = None
    dead_man_alive: bool | None = None
    reconciliation_diverged: bool | None = None
    reconciliation_age_s: float | None = None
    max_reconciliation_age_s: int | None = None
    is_paper_proven: bool | None = None
    orders_today: int | None = None


def auto_disarm_sweep(
    session: Session,
    *,
    now: datetime,
    facts: CycleFacts | None = None,
    adapter_name: str | None = None,
    actor: str = "system",
) -> list[Disarm]:
    """Run §12 step 7 against every live arming. Called at the top of every
    cycle, in BOTH branches.

    Decision 9 is "on any status change (not only downgrades)". Arming refuses
    unless the version is PAPER_APPROVED, so "changed away from the armed value"
    is exactly "is no longer PAPER_APPROVED" — no stored status column is needed
    and none is added. The flap case (changed and changed back between two
    cycles) is caught separately by :func:`_status_transition_recorded_since`.
    """
    f = facts or CycleFacts()
    out: list[Disarm] = []
    for armed in live_armings(session, adapter_name=adapter_name):
        trigger, detail = _first_disarm_trigger(session, armed, now=now, facts=f)
        if trigger is None:
            continue
        out.append(disarm(session, armed, trigger=trigger, detail=detail, now=now, actor=actor))
    return out


def _first_disarm_trigger(
    session: Session, armed: ArmedStrategy, *, now: datetime, facts: CycleFacts
) -> tuple[DisarmTrigger | None, str]:
    """The first §12 step 7 trigger that fires for this arming, in the order the
    ADR lists them. One reason is recorded, not a set: the first one is the one
    that ended the authority, and a list would invite arguing about which
    mattered."""
    from signalforge.db.models import StrategyVersion
    from signalforge.domain import StrategyStatus
    from signalforge.execution.oms import has_outstanding_unknown

    ver = session.get(StrategyVersion, armed.strategy_version_id)
    if ver is None:
        return DisarmTrigger.STATUS_CHANGE, "the armed strategy version no longer exists"
    if ver.status is not StrategyStatus.PAPER_APPROVED:
        return (
            DisarmTrigger.STATUS_CHANGE,
            f"status is now {ver.status.value}; arming requires PAPER_APPROVED and decision 9 "
            "disarms on ANY status change, not only a downgrade",
        )
    flap = _status_transition_recorded_since(session, armed)
    if flap:
        return DisarmTrigger.STATUS_CHANGE, flap

    live_config, live_spec = _live_hashes(session, armed.strategy_version_id)
    if live_config != armed.config_hash:
        return (
            DisarmTrigger.HASH_DRIFT,
            f"config_hash drifted from {armed.config_hash[:12]} to {live_config[:12]} — the "
            "2026-09-11 incident in the one place it would matter most",
        )
    if live_spec != armed.spec_json_hash:
        return (
            DisarmTrigger.HASH_DRIFT,
            f"spec_json_hash drifted from {armed.spec_json_hash[:12]} to {live_spec[:12]}",
        )
    if not _scope_still_approved(
        session, strategy_version_id=armed.strategy_version_id, armed_like=armed
    ):
        return (
            DisarmTrigger.SCOPE_MISMATCH,
            "no PASSING evaluation matches the armed config_hash / spec_json_hash any more",
        )

    if facts.kill_switch_engaged is True or facts.execution_kill_engaged is True:
        return (
            DisarmTrigger.KILL_SWITCH,
            "the kill switch is engaged — opening is blocked and this arming ends; closing is "
            "NOT blocked and the protective close needs no armed row",
        )
    if facts.dead_man_alive is False:
        return (
            DisarmTrigger.DEAD_MAN,
            "the execution dead man has lapsed; nothing is auto-liquidated — the operator "
            "closes any open position by hand, at the broker",
        )
    if facts.reconciliation_diverged is True:
        return (
            DisarmTrigger.RECONCILIATION,
            "reconciliation is DIVERGED; it is never auto-corrected",
        )
    if (
        facts.reconciliation_age_s is not None
        and facts.max_reconciliation_age_s is not None
        and facts.reconciliation_age_s > facts.max_reconciliation_age_s
    ):
        return (
            DisarmTrigger.RECONCILIATION,
            f"the last clean reconciliation is {facts.reconciliation_age_s:.0f}s old > "
            f"{facts.max_reconciliation_age_s}s",
        )
    if has_outstanding_unknown(session, armed.strategy_version_id):
        return (
            DisarmTrigger.UNKNOWN_OUTSTANDING,
            "an UNKNOWN intent is outstanding for this strategy",
        )
    if facts.is_paper_proven is False:
        return DisarmTrigger.IS_PAPER, "is_paper() failed to re-prove this cycle"
    if facts.orders_today is not None and facts.orders_today > armed.max_orders_per_day:
        return (
            DisarmTrigger.ORDER_CAP,
            f"{facts.orders_today} orders today breached the armed cap "
            f"{armed.max_orders_per_day}",
        )
    if armed.expires_at <= now:
        return (
            DisarmTrigger.EXPIRED,
            f"the arming expired at {armed.expires_at.isoformat()}; re-arming is the full "
            "ceremony again — there is no resume",
        )
    return None, ""


def _status_transition_recorded_since(session: Session, armed: ArmedStrategy) -> str:
    """A recorded status transition for this strategy after ``armed_at``.

    The cycle check compares the CURRENT status, which cannot see a status that
    changed and changed back between two cycles. The health monitor — the one
    path that changes status without an operator — writes an ``AuditLog`` row
    for every transition it makes, so the flap is visible there even though it is
    invisible to a point-in-time comparison. A DB trigger would catch more; the
    ADR's instruction is a per-cycle check, and this is how much of the gap a
    per-cycle check can close honestly.
    """
    from sqlalchemy import select

    from signalforge.db.models import AuditLog, Strategy, StrategyVersion

    ver = session.get(StrategyVersion, armed.strategy_version_id)
    if ver is None:  # pragma: no cover - handled by the caller first
        return ""
    strat = session.get(Strategy, ver.strategy_id)
    if strat is None:  # pragma: no cover - orphaned version
        return ""
    entity = f"{strat.name}@{ver.version}"
    row = session.scalars(
        select(AuditLog)
        .where(
            AuditLog.entity == entity,
            AuditLog.action.in_(("strategy.downgrade", "strategy.disable", "strategy.promote")),
            AuditLog.ts > armed.armed_at,
        )
        .order_by(AuditLog.ts.desc())
        .limit(1)
    ).first()
    if row is None:
        return ""
    return (
        f"a recorded status transition ({row.action}) for {entity} at {row.ts.isoformat()} is "
        "later than the arming; decision 9 disarms on ANY status change"
    )


def acknowledgements() -> Sequence[str]:
    """§12 step 3's four acknowledgements, in the plain words the ADR requires.

    Printed by the CLI above the typed confirmation. They are not decoration: an
    operator who does not know (ii) and (iv) before arming will discover them
    during an outage.
    """
    return (
        "(i) The backtest APPROXIMATES EARLY ASSIGNMENT AWAY, and the approximation is biased "
        "in the strategy's favour, so live outcomes can differ in exactly that tail.",
        "(ii) If the dead man lapses or the kill switch engages, THE OPERATOR CLOSES ANY OPEN "
        "POSITION BY HAND, AT THE BROKER. Nothing is auto-liquidated.",
        "(iii) The broker account MUST NOT be shared with manual trading. Any position this OMS "
        "did not originate halts the system, and arming is machine-refused unless the account "
        "is flat and empty.",
        "(iv) ENGAGING THE KILL SWITCH WHILE THE WORKER IS DOWN CANCELS NOTHING AT THE BROKER. "
        "Resting orders stay live and open positions stay open; cancel by hand, at the broker. "
        "With the worker running, worst case from engage to cancel_all() is ~60-70 seconds.",
    )


def read_adapter_account_is_flat(adapter: BrokerAdapter) -> bool | None:
    """§10 rule 2 — arming begins from a flat, empty account.

    ``None`` on any failure to read: "could not check" is not "is flat", and the
    precondition table blocks on ``None``.
    """
    try:
        return not list(adapter.positions()) and not list(adapter.open_orders())
    except Exception:
        return None
