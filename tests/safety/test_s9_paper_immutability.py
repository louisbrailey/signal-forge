"""S9 — paper trades are immutable after creation.

This module holds the dependency-free contract checks. The database-level proof
(BEFORE UPDATE/DELETE triggers reject mutation) is in
``tests/db/test_s9_paper_trade_triggers.py`` (also marked ``safety``).
"""

from __future__ import annotations

import pytest

from signalforge.paper.ledger import Decision, ImmutablePaperTradeError

pytestmark = pytest.mark.safety


def test_immutability_error_is_a_runtime_error() -> None:
    assert issubclass(ImmutablePaperTradeError, RuntimeError)


def test_decision_enum_has_exactly_the_four_outcomes() -> None:
    assert {d.value for d in Decision} == {"accepted", "rejected", "ignored", "watch"}
