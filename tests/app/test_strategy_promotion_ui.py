"""Strategy Promotion dashboard page + the manual-override restriction: a human
may downgrade a strategy directly, but paper_approved is earned only by the
promotion pipeline (research.promotion), never set through this UI.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from signalforge.db.session import session_scope
from signalforge.domain import StrategyStatus
from tests.app.conftest import _csrf


def _seed_strategy(status: StrategyStatus = StrategyStatus.EXPERIMENTAL) -> tuple[int, int]:
    from signalforge.db.models import Strategy, StrategyVersion
    from signalforge.domain import Horizon

    with session_scope() as s:
        strat = Strategy(
            name="mean_reversion.short_swing", horizon=Horizon.SHORT_SWING, status=status
        )
        s.add(strat)
        s.flush()
        ver = StrategyVersion(
            strategy_id=strat.id, version="0.1.0", git_sha="abc1234", spec_json={}, status=status
        )
        s.add(ver)
        s.flush()
        return strat.id, ver.id


def _seed_evaluation(strategy_version_id: int, *, passed: bool) -> None:
    from signalforge.db.models import StrategyPromotionEvaluation

    with session_scope() as s:
        s.add(
            StrategyPromotionEvaluation(
                strategy_version_id=strategy_version_id,
                evaluated_at=datetime(2026, 9, 1, tzinfo=UTC),
                config_hash="deadbeef" * 8,
                git_sha="abc1234",
                universe_json=["SPY", "AAPL"],
                window_start=date(2016, 1, 1),
                window_end=date(2026, 1, 1),
                data_provenance_json={"sources": ["fixture"], "simulated": True},
                gates_json=[
                    {
                        "number": i,
                        "name": f"gate_{i}",
                        "passed": passed,
                        "detail": "x",
                        "evidence": {},
                    }
                    for i in range(1, 11)
                ],
                passed=passed,
                verdict=(
                    "PAPER_APPROVED"
                    if passed
                    else "NO TRADE — insufficient evidence or poor risk/reward"
                ),
                sealed_test_id=None,
            )
        )


def test_promotion_page_shows_no_trade_by_default(registered_client: TestClient) -> None:
    r = registered_client.get("/strategies/promotion")
    assert r.status_code == 200
    assert "NO TRADE" in r.text
    assert "insufficient evidence" in r.text


def test_promotion_page_renders_a_persisted_evaluation(registered_client: TestClient) -> None:
    _, ver_id = _seed_strategy()
    _seed_evaluation(ver_id, passed=False)
    r = registered_client.get("/strategies/promotion")
    assert r.status_code == 200
    assert "gate_1" in r.text
    assert "0/10 gates passed" in r.text


def test_promotion_page_shows_approved_status_and_gate_count(registered_client: TestClient) -> None:
    _, ver_id = _seed_strategy(status=StrategyStatus.PAPER_APPROVED)
    _seed_evaluation(ver_id, passed=True)
    r = registered_client.get("/strategies/promotion")
    assert r.status_code == 200
    assert "10/10 gates passed" in r.text
    assert "paper_approved" in r.text


def test_manual_status_change_cannot_set_paper_approved(registered_client: TestClient) -> None:
    _seed_strategy(status=StrategyStatus.EXPERIMENTAL)
    r = registered_client.post(
        "/strategies/mean_reversion.short_swing/status",
        data={"status": "paper_approved", "csrf_token": _csrf(registered_client, "/strategies")},
    )
    assert r.status_code == 400

    from signalforge.db.models import Strategy

    with session_scope() as s:
        strat = s.scalar(select(Strategy).where(Strategy.name == "mean_reversion.short_swing"))
        assert strat.status is StrategyStatus.EXPERIMENTAL  # unchanged


def test_manual_status_change_can_still_downgrade(registered_client: TestClient) -> None:
    _, ver_id = _seed_strategy(status=StrategyStatus.PAPER_APPROVED)
    r = registered_client.post(
        "/strategies/mean_reversion.short_swing/status",
        data={"status": "disabled", "csrf_token": _csrf(registered_client, "/strategies")},
        follow_redirects=False,
    )
    assert r.status_code == 303

    from signalforge.db.models import Strategy, StrategyVersion

    with session_scope() as s:
        strat = s.scalar(select(Strategy).where(Strategy.name == "mean_reversion.short_swing"))
        ver = s.get(StrategyVersion, ver_id)
        assert strat.status is StrategyStatus.DISABLED
        assert ver.status is StrategyStatus.DISABLED  # version status kept in sync too


def test_run_promotion_action_invokes_the_pipeline_and_never_sets_status_itself(
    registered_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dashboard action must call research.promotion, not decide anything
    on its own — verified here by stubbing the pipeline call itself."""
    calls: list[str] = []

    def _fake_evaluate_all(session, **kw):
        calls.append("called")
        return []

    import signalforge.research.promotion as promotion_mod

    monkeypatch.setattr(promotion_mod, "evaluate_all_default_strategies", _fake_evaluate_all)

    r = registered_client.post(
        "/strategies/promotion/run",
        data={"csrf_token": _csrf(registered_client, "/strategies/promotion")},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert calls == ["called"]
