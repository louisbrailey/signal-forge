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


def test_timestamp_fragments_do_not_ground_fabricated_numbers() -> None:
    """Digits inside evidence timestamps are not facts: "45%" must not be
    grounded by "…T18:45:00", nor "2026" by the date, nor "10" by the day."""
    facts = {
        "as_of": "2026-09-10T18:45:00+00:00",
        "items": [{"published_at": "2026-09-09T13:07:22Z", "session_date": "2026-09-08"}],
        "breadth_pct": 61.3,
    }
    assert_grounded(f"Breadth stands at 61.3%. {AI_FOOTER}", facts)
    for fabricated in ("45%", "18x", "2026", "07 publishers", "10 names"):
        with pytest.raises(GuardViolation, match="not present in facts"):
            assert_grounded(f"Breadth improved {fabricated}. {AI_FOOTER}", facts)


def test_datetime_objects_and_timestamp_keys_are_skipped() -> None:
    from datetime import UTC, date, datetime

    facts = {
        "checked_at": datetime(2026, 9, 10, 18, 45, tzinfo=UTC),
        "bar_date": date(2026, 9, 8),
        "count_ts": 1234,  # timestamp-shaped key → never a quantity
        "n_symbols": 24,
    }
    assert_grounded(f"24 symbols were checked. {AI_FOOTER}", facts)
    with pytest.raises(GuardViolation):
        assert_grounded(f"1234 symbols were checked. {AI_FOOTER}", facts)
    with pytest.raises(GuardViolation):
        assert_grounded(f"45 symbols were checked. {AI_FOOTER}", facts)
