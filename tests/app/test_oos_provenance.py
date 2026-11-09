"""Actual strategy-page rendering preserves numbers while warning on forced inputs."""

import pytest
from fastapi.testclient import TestClient

from signalforge.db.session import session_scope
from tests.research.test_oos_provenance import _record


@pytest.mark.parametrize("forced", [True, False])
def test_strategy_page_displays_mismatch_as_ambiguous_not_valid_positive_evidence(
    registered_client: TestClient, forced: bool
) -> None:
    with session_scope() as session:
        metric = _record(
            session,
            {
                "allow_mismatch": forced,
                "mismatched_inputs": ["config_hash", "until"] if forced else [],
            },
        )
        run_id = metric.run_id
    response = registered_client.get("/strategies")
    assert response.status_code == 200
    html = response.text
    assert f"Run {run_id}" in html and "+0.500R" in html
    if forced:
        assert "Ambiguous OOS evidence: forced or mismatched inputs" in html
        assert "OOS provenance mismatch" in html
        assert "config_hash" in html and "until" in html
        assert "Positive OOS point estimate" not in html
    else:
        assert "Positive OOS point estimate" in html
        assert "Ambiguous OOS evidence" not in html


@pytest.mark.parametrize("damage", ["wrong_config", "unknown_config", "wrong_dataset"])
def test_strategy_page_marks_wrong_scope_ambiguous_without_changing_positive_numbers(
    registered_client: TestClient, damage: str
) -> None:
    with session_scope() as session:
        metric = _record(session, {})
        if damage == "wrong_dataset":
            params = dict(metric.run.params_json)
            params["dataset_snapshot"] = {"id": 987654, "key": "other-dataset"}
            metric.run.params_json = params
        else:
            metric.run.config_hash = "different-config" if damage == "wrong_config" else ""
        run_id = metric.run_id
    response = registered_client.get("/strategies")
    assert response.status_code == 200
    html = response.text
    assert f"Run {run_id}" in html and "+0.500R" in html
    assert "Ambiguous OOS evidence: config or approved dataset scope differs" in html
    assert "OOS scope mismatch" in html
    assert "Positive OOS point estimate" not in html
