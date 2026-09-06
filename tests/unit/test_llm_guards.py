"""Unit tests for the AI-narrative guards (ARCHITECTURE.md §11)."""

from __future__ import annotations

import pytest

from signalforge.llm.guards import (
    AI_FOOTER,
    GuardViolation,
    assert_grounded,
    extract_numeric_tokens,
)


def test_extract_numeric_tokens_normalises() -> None:
    toks = extract_numeric_tokens("Entry near $101.50, target +3.2%, size 1,000 shares, 2x ADV")
    assert "101.50" in toks
    assert "3.2%" in toks
    assert "1000" in toks
    assert "2x" in toks


def test_grounded_narrative_passes() -> None:
    facts = {"entry": 101.5, "target_pct": 3.2, "reward_risk": 1.8}
    narrative = (
        "The rule triggered with an entry zone around 101.5 and a target of about 3.2%, "
        f"a reward-to-risk of 1.8. {AI_FOOTER}"
    )
    assert_grounded(narrative, facts)


def test_missing_footer_is_rejected() -> None:
    with pytest.raises(GuardViolation, match="footer"):
        assert_grounded("Entry near 101.5.", {"entry": 101.5})


def test_fabricated_statistic_is_rejected() -> None:
    facts = {"entry": 101.5}
    narrative = f"Backtests show a 73% win rate and entry near 101.5. {AI_FOOTER}"
    with pytest.raises(GuardViolation, match="not present in facts"):
        assert_grounded(narrative, facts)
