"""Order-execution layer — DISABLED BY DEFAULT, and nothing is armed by default.

Authorised by the D6 execution ADR (`docs/research/options_designs/D6_execution_adr.md`),
which supersedes the "no brokerage, at any phase" roadmap boundary **for this
package only, paper endpoints only**. Every other module keeps the prohibition.

What this package may become: a path that submits orders to a broker's
**paper/sandbox** endpoint, disabled by default, armed only by an audited
operator ceremony per strategy version, with a hard expiry.

What it may never do, and what is re-prohibited here rather than merely omitted:

* reach any real-money endpoint;
* carry any order decided, shaped, ranked, sized, timed, or described by an LLM;
* source an order from a manually accepted paper trade (§5 precondition P6);
* hold any structure with undefined max loss, submit any multi-leg structure
  leg by leg, trade 0DTE, or open a naked short option;
* liquidate automatically, repair a reconciliation automatically, or retry a
  broker rejection;
* acquire, store, rotate, or log a credential.

**The kill switch blocks opening and never blocks closing.** The OPEN lane and
the PROTECTIVE_CLOSE lane are built by two different factories with two
different precondition sets and **opposite** fail directions: a check that
cannot be evaluated blocks opening and never blocks closing.

State of this phase (I-E2): protocol, intent data model, the two factories, the
state machine, limits, audit records and credential resolution. **There is no
adapter here — nothing in this package opens a socket** — no arming ceremony,
and no scheduler registration. Importing this package performs no network call
and reads no credential.
"""

from __future__ import annotations

#: Asserted by a safety test. Two independent gates exist, neither sufficient
#: alone: this constant plus the ``execution.enabled`` setting (default False),
#: and even with both, zero orders can be submitted while no unexpired
#: ``armed_strategy`` row exists.
EXECUTION_DISABLED_BY_DEFAULT = True

__all__ = ["EXECUTION_DISABLED_BY_DEFAULT", "execution_enabled"]


def execution_enabled() -> bool:
    """Whether the execution layer is enabled at all.

    Reads the version-controlled ``ResearchConfig.execution.enabled`` flag,
    which ships **False** and is deliberately excluded from the approval-scope
    hash (``SCOPE_HASH_FIELDS``): an execution setting shapes no signal, and
    moving ``config_hash`` would put every live PAPER_APPROVED approval out of
    scope — the exact incident of 2026-09-11.

    This being True is necessary and nowhere near sufficient: nothing is armed
    by default, and arming is a separate, audited, expiring operator ceremony.
    """
    from signalforge.config import get_settings

    return bool(get_settings().research.execution.enabled)
