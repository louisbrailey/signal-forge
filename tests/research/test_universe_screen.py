"""Universe screen + news-summary guard + market-session helper."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from signalforge.config.research import ResearchConfig, UniverseFilters
from signalforge.data.adapters.fixture import FixtureMarketDataAdapter
from signalforge.data.ingest import ingest_universe
from signalforge.research.universe import screen_universe
from signalforge.scheduler import _in_us_market_session


def test_screen_keeps_liquid_symbols_and_reports_unavailable_filters(session: Session) -> None:
    from datetime import date

    ingest_universe(
        session,
        FixtureMarketDataAdapter(),
        ["SPY", "AAPL", "MSFT"],
        date(2022, 1, 1),
        date(2024, 6, 30),
    )
    session.flush()
    cfg = ResearchConfig(
        watchlist=("AAPL", "MSFT", "GHOST"),
        etf_universe=("SPY",),
        universe_filters=UniverseFilters(min_history_days=100, min_avg_dollar_volume=1.0),
    )
    scr = screen_universe(session, cfg, as_of=date(2024, 6, 30))
    assert set(scr.kept) == {"AAPL", "MSFT", "SPY"}
    assert "GHOST" in scr.dropped  # no data
    # market-cap + spread cannot be checked with the feeds we ingest
    joined = " ".join(scr.data_unavailable)
    assert "min_market_cap" in joined and "spread" in joined


def test_universe_cap_is_enforced(session: Session) -> None:
    from datetime import date

    ingest_universe(
        session,
        FixtureMarketDataAdapter(),
        ["SPY", "AAPL", "MSFT"],
        date(2022, 1, 1),
        date(2024, 6, 30),
    )
    session.flush()
    cfg = ResearchConfig(
        watchlist=("AAPL", "MSFT"),
        etf_universe=("SPY",),
        universe_filters=UniverseFilters(
            min_history_days=1, min_avg_dollar_volume=1.0, max_universe_size=2
        ),
    )
    scr = screen_universe(session, cfg, as_of=date(2024, 6, 30))
    assert len(scr.kept) == 2
    capped = [s for s, rs in scr.dropped.items() if any("cap" in r for r in rs)]
    assert len(capped) == 1


def test_market_session_helper_weekday_vs_weekend() -> None:
    from zoneinfo import ZoneInfo

    et = ZoneInfo("America/New_York")
    wed_open = datetime(2024, 6, 26, 10, 0, tzinfo=et).astimezone(UTC)
    sat = datetime(2024, 6, 29, 10, 0, tzinfo=et).astimezone(UTC)
    wed_night = datetime(2024, 6, 26, 23, 0, tzinfo=et).astimezone(UTC)
    assert _in_us_market_session(wed_open) is True
    assert _in_us_market_session(sat) is False
    assert _in_us_market_session(wed_night) is False


def test_news_summary_needs_the_footer() -> None:
    from signalforge.llm.summarize_news import summarize_news

    class _Stub:
        model = "stub"

        def complete(self, *, system: str, prompt: str):
            from signalforge.llm.client import LlmResult

            return LlmResult(
                text="Two items about AAPL [1][2].",
                model="stub",
                prompt_tokens=1,
                completion_tokens=1,
            )

    items = [
        {
            "headline": "h1",
            "source": "Benzinga",
            "url": "u1",
            "published_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        },
        {
            "headline": "h2",
            "source": "Zacks",
            "url": "u2",
            "published_at": (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
        },
    ]
    # no AI footer -> rejected
    assert summarize_news(items, client=_Stub()) is None


def test_news_summary_accepts_grounded_output_with_footer() -> None:
    from signalforge.llm.client import LlmResult
    from signalforge.llm.summarize_news import summarize_news

    class _Stub:
        model = "stub"

        def complete(self, *, system: str, prompt: str):
            return LlmResult(
                text="Summary of [1] and [2].\nAI explanation, not a trading instruction.",
                model="stub",
                prompt_tokens=1,
                completion_tokens=1,
            )

    items = [
        {
            "headline": "h1",
            "source": "Benzinga",
            "url": "u1",
            "published_at": (datetime.now(UTC) - timedelta(hours=40)).isoformat(),
        },
    ]
    out = summarize_news(items, client=_Stub(), stale_after_hours=24)
    assert out is not None and out.stale is True and out.n_items == 1
