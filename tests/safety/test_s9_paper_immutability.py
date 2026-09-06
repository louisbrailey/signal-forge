"""S9 — paper trades are immutable after creation (Phase 0: contract shape)."""

from __future__ import annotations

import pytest

from signalforge.paper.ledger import Decision, ImmutablePaperTradeError

pytestmark = pytest.mark.safety


def test_immutability_error_is_a_runtime_error() -> None:
    assert issubclass(ImmutablePaperTradeError, RuntimeError)


def test_decision_enum_has_exactly_the_four_outcomes() -> None:
    assert {d.value for d in Decision} == {"accepted", "rejected", "ignored", "watch"}


@pytest.mark.skip(reason="Phase 1 §1.7: repository rejects UPDATE/DELETE on paper_trade rows")
def test_repository_rejects_mutation_of_existing_paper_trade() -> None: ...
