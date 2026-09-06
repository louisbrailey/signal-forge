"""Daily briefing: deterministic assembly + storage; LLM narrative is optional."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.briefing import build_and_store_briefing, latest_briefing
from signalforge.data.adapters.fixture import FixtureMarketDataAdapter
from signalforge.data.ingest import ingest_universe
from signalforge.db.models import BacktestMetric, BacktestRun, LlmCall, PaperAccount
from signalforge.domain import Horizon
from signalforge.research.briefing import build_briefing_facts, render_briefing_text
from signalforge.research.candidates import persist_scan
from signalforge.research.persistence import upsert_strategy_version
from signalforge.research.scan import run_scan
from signalforge.research.strategies import default_strategies

SYMS = ["SPY", "AAPL", "MSFT", "NVDA"]


def _seed(session: Session) -> None:
    session.add(PaperAccount(name="default", initial_cash=10_000, cash=10_000))
    ingest_universe(session, FixtureMarketDataAdapter(), SYMS, date(2021, 1, 1), date(2024, 6, 30))
    session.flush()
    for strat in default_strategies():
        ver = upsert_strategy_version(session, strat.spec())
        run = BacktestRun(
            strategy_version_id=ver.id,
            params_json={},
            date_start=date(2022, 1, 1),
            date_end=date(2024, 6, 30),
            config_hash="t",
        )
        session.add(run)
        session.flush()
        session.add(
            BacktestMetric(
                run_id=run.id,
                segment="all",
                phase="out_of_sample",
                metrics_json={"expectancy_r": -0.9, "n_trades": 150},
                ci_json={"expectancy_r": {"low": -1.0, "high": -0.7}},
            )
        )
    result = run_scan(session, Horizon.SHORT_SWING, as_of=date(2024, 6, 30), symbols=SYMS)
    persist_scan(session, result)
    session.flush()


def test_facts_and_text_are_complete_without_an_llm(session: Session) -> None:
    _seed(session)
    facts = build_briefing_facts(session, as_of=date(2024, 6, 30))
    assert facts["feeds"], "feed status present"
    assert facts["no_trade_total"] > 0
    assert any("NO TRADE" in w for w in facts["warnings"])

    text = render_briefing_text(facts)
    assert "daily briefing" in text.lower()
    assert "Research signal only — no order was placed." in text
    assert "Today's qualified candidates" in text
    assert "NONE." in text  # no qualified candidates on fixture data


def test_build_and_store_then_read_back(session: Session) -> None:
    _seed(session)
    payload = build_and_store_briefing(session, as_of=date(2024, 6, 30))
    assert payload["narrative"] is None  # no LLM configured
    stored = latest_briefing(session)
    assert stored is not None and stored["as_of"] == "2024-06-30"
    assert session.scalars(select(LlmCall)).first() is None


def test_briefing_flags_stale_feed(session: Session) -> None:
    _seed(session)
    from signalforge.db.models import DataFeedStatus
    from signalforge.db.types import utcnow

    for row in session.scalars(select(DataFeedStatus)):
        row.last_success_at = utcnow() - timedelta(days=30)
    session.flush()
    facts = build_briefing_facts(session, as_of=date(2024, 6, 30))
    assert facts["any_feed_stale"] is True
    assert facts["live_alerts_enabled"] is False
