"""Dashboard integration: pages render, auth-gated, paper actions, kill switch."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.app.conftest import _csrf


@pytest.fixture
def seeded(registered_client: TestClient) -> TestClient:
    """Registered client + a scan with NO-TRADE candidates and one PASSED candidate."""
    from signalforge.data.adapters.fixture import FixtureMarketDataAdapter
    from signalforge.data.ingest import ingest_universe
    from signalforge.db.models import (
        BacktestMetric,
        BacktestRun,
        Candidate,
        PaperAccount,
    )
    from signalforge.db.session import session_scope
    from signalforge.domain import Direction, Horizon, QualityGate
    from signalforge.research.candidates import persist_scan
    from signalforge.research.persistence import upsert_strategy_version
    from signalforge.research.scan import run_scan
    from signalforge.research.strategies import default_strategies

    syms = ["SPY", "AAPL", "MSFT", "NVDA"]
    with session_scope() as s:
        s.add(PaperAccount(name="default", initial_cash=10_000, cash=10_000))
        ingest_universe(s, FixtureMarketDataAdapter(), syms, date(2021, 1, 1), date(2024, 6, 30))
        for strat in default_strategies():
            ver = upsert_strategy_version(s, strat.spec())
            run = BacktestRun(
                strategy_version_id=ver.id,
                params_json={},
                date_start=date(2022, 1, 1),
                date_end=date(2024, 6, 30),
                config_hash="t",
            )
            s.add(run)
            s.flush()
            s.add(
                BacktestMetric(
                    run_id=run.id,
                    segment="all",
                    phase="out_of_sample",
                    metrics_json={"expectancy_r": -0.9, "n_trades": 150},
                    ci_json={"expectancy_r": {"low": -1.0, "high": -0.7}},
                )
            )
        result = run_scan(s, Horizon.SHORT_SWING, as_of=date(2024, 6, 30), symbols=syms)
        scan_run = persist_scan(s, result)

        # a hand-built PASSED candidate so the accept path can be exercised
        from signalforge.db.models import Instrument

        ver = upsert_strategy_version(s, default_strategies()[0].spec())
        aapl = s.scalar(select(Instrument).where(Instrument.symbol == "AAPL"))
        s.add(
            Candidate(
                scan_run_id=scan_run.id,
                instrument_id=aapl.id,
                strategy_version_id=ver.id,
                horizon=Horizon.SHORT_SWING,
                direction=Direction.LONG,
                entry_zone_low=99.0,
                entry_zone_high=101.0,
                invalidation_level=95.0,
                target_level=112.0,
                target_logic="x",
                time_stop_days=10,
                reward_risk_estimate=2.4,
                risk_dollars=50.0,
                risk_pct_of_account=0.5,
                liquidity_json={"last_price": 100.0},
                slippage_assumption_json={},
                event_risk_json={"upcoming_earnings": []},
                portfolio_context_json={},
                data_freshness_json={"fresh": True},
                ranking_json={"score": 0.4},
                reasons_qualify=["hand-built for the accept test"],
                reasons_fail=["synthetic"],
                quality_gate_status=QualityGate.PASSED,
                failed_gates=[],
                rank_in_horizon=1,
            )
        )
    return registered_client


def _first_candidate_id(client: TestClient) -> int:
    from signalforge.db.models import Candidate
    from signalforge.db.session import session_scope

    with session_scope() as s:
        return s.scalars(select(Candidate).order_by(Candidate.id).limit(1)).one().id


PAGES = ["/", "/scanner", "/portfolio", "/strategies", "/journal", "/options", "/settings"]


@pytest.mark.parametrize("path", PAGES)
def test_pages_render_for_a_signed_in_user(seeded: TestClient, path: str) -> None:
    r = seeded.get(path)
    assert r.status_code == 200, path
    assert "not financial advice" in r.text.lower()


def test_pages_redirect_when_signed_out(client: TestClient) -> None:
    client.post(
        "/register",
        data={
            "username": "u",
            "password": "correct horse battery",
            "csrf_token": _csrf(client, "/register"),
        },
    )
    client.post("/logout", data={"csrf_token": _csrf(client, "/login")})
    r = client.get("/scanner", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")


def test_scanner_reports_no_trade_accounting(seeded: TestClient) -> None:
    r = seeded.get("/scanner?horizon=SHORT_SWING")
    assert r.status_code == 200
    assert "NO TRADE" in r.text  # the "universe scanned / excluded / NO TRADE" line
    assert "universe scanned" in r.text


def test_overview_lists_the_qualified_candidate(seeded: TestClient) -> None:
    r = seeded.get("/")
    assert "Today&#39;s qualified candidates" in r.text or "qualified candidate" in r.text
    assert "evidence" in r.text


def test_candidate_detail_shows_evidence_and_research_only_line(seeded: TestClient) -> None:
    cid = _first_candidate_id(seeded)
    r = seeded.get(f"/candidates/{cid}")
    assert r.status_code == 200
    assert "Research signal only — no order was placed." in r.text
    assert "Why it could fail" in r.text
    assert "Paper action" in r.text


def test_missing_candidate_is_404(seeded: TestClient) -> None:
    assert seeded.get("/candidates/999999").status_code == 404


def test_paper_accept_from_the_evidence_page(seeded: TestClient) -> None:
    from signalforge.db.models import Candidate, PaperTrade
    from signalforge.db.session import session_scope
    from signalforge.domain import QualityGate

    with session_scope() as s:
        cid = (
            s.scalars(
                select(Candidate)
                .where(Candidate.quality_gate_status == QualityGate.PASSED)
                .limit(1)
            )
            .one()
            .id
        )
    r = seeded.post(
        f"/candidates/{cid}/accept",
        data={"csrf_token": _csrf(seeded, f"/candidates/{cid}")},
        follow_redirects=False,
    )
    assert r.status_code == 303
    with session_scope() as s:
        assert s.scalars(select(PaperTrade)).all()


@pytest.mark.safety
def test_kill_switch_blocks_state_changing_routes(seeded: TestClient) -> None:
    from signalforge.db.models import Candidate
    from signalforge.db.session import session_scope
    from signalforge.domain import QualityGate

    seeded.post(
        "/killswitch",
        data={"action": "engage", "reason": "test halt", "csrf_token": _csrf(seeded, "/")},
        follow_redirects=False,
    )
    with session_scope() as s:
        cid = (
            s.scalars(
                select(Candidate)
                .where(Candidate.quality_gate_status == QualityGate.PASSED)
                .limit(1)
            )
            .one()
            .id
        )
    r = seeded.post(f"/candidates/{cid}/accept", data={"csrf_token": _csrf(seeded, "/settings")})
    assert r.status_code == 423

    seeded.post(
        "/killswitch",
        data={"action": "release", "reason": "resume", "csrf_token": _csrf(seeded, "/")},
        follow_redirects=False,
    )
    assert seeded.get("/readyz").json()["kill_switch_active"] is False


def test_settings_override_is_persisted(seeded: TestClient) -> None:
    r = seeded.post(
        "/settings",
        data={
            "per_trade_risk_pct": "0.75",
            "watchlist": "AAPL, MSFT",
            "csrf_token": _csrf(seeded, "/settings"),
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    from signalforge.db.session import session_scope
    from signalforge.settings_store import effective_research_config

    with session_scope() as s:
        cfg = effective_research_config(s)
    assert cfg.risk.per_trade_risk_pct == 0.75
    assert cfg.watchlist == ("AAPL", "MSFT")


def test_post_without_csrf_is_forbidden(seeded: TestClient) -> None:
    assert seeded.post("/killswitch", data={"action": "engage"}).status_code == 403
