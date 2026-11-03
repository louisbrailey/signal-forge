from datetime import UTC, date, datetime

import pytest

from signalforge.research.prospective_funded import freeze, record_collection, validate_plan


def plan(root):
    return freeze(
        root,
        {"SPY": {"instrument_type": "etf", "sector": "broad"}},
        (),
        ["SPY"],
        date(2023, 1, 1),
        now=datetime(2024, 1, 2, 20, tzinfo=UTC),
    )


def report(day, value="10000"):
    return {
        "end": str(day),
        "input_prefix_fingerprints": {"2024-01-03": "test-hash"},
        "books": {
            "A": {
                "scenarios": {
                    "base": {
                        "result": {
                            "marks": [{"day": "2024-01-03", "net_liquidation_usd": value}],
                            "fills": [],
                            "decisions": [],
                            "corporate_events": [],
                        }
                    }
                }
            }
        },
    }


def test_freeze_cannot_be_overwritten_and_code_change_halts(tmp_path, monkeypatch):
    p = plan(tmp_path)
    assert p["first_observation_session"] == "2024-01-03"
    assert p["first_entry_session"] == "2024-01-04"
    with pytest.raises(ValueError, match="Plan exists"):
        plan(tmp_path)
    monkeypatch.setattr("signalforge.research.prospective_funded.code_digest", lambda: "changed")
    with pytest.raises(ValueError, match="code changed"):
        validate_plan(tmp_path)


def test_forward_records_are_immutable_and_revisions_block(tmp_path):
    plan(tmp_path)
    day = date(2024, 1, 3)
    first = record_collection(tmp_path, day, report(day))
    assert record_collection(tmp_path, day, report(day)) == first
    with pytest.raises(ValueError, match="rewrite"):
        record_collection(tmp_path, day, report(day, "10001"))
    with pytest.raises(ValueError, match="history changed"):
        record_collection(tmp_path, date(2024, 1, 4), report(date(2024, 1, 4), "10001"))


def test_missed_future_session_is_not_backfilled_as_forward_evidence(tmp_path):
    plan(tmp_path)
    with pytest.raises(ValueError, match="Missing prospective"):
        record_collection(tmp_path, date(2024, 1, 4), report(date(2024, 1, 4)))


def test_raw_revision_blocks_even_when_trades_would_not_change(tmp_path):
    plan(tmp_path)
    record_collection(tmp_path, date(2024, 1, 3), report(date(2024, 1, 3)))
    revised = report(date(2024, 1, 4))
    revised["input_prefix_fingerprints"]["2024-01-03"] = "revision"
    with pytest.raises(ValueError, match="raw inputs changed"):
        record_collection(tmp_path, date(2024, 1, 4), revised)


def test_no_forward_outcome_is_claimed_at_freeze(tmp_path):
    from signalforge.research.prospective_funded import review_readiness

    plan(tmp_path)
    r = review_readiness(tmp_path)
    assert r["observed_sessions"] == 0
    assert r["status"] == "WAITING_FOR_FUTURE_EVIDENCE"
