"""Market-regime research agent (read-only).

Reports the deterministic market-regime state already computed by
``signalforge.research.regime`` (trend/vol from the SPY proxy), breadth (the
share of the configured research universe whose last close sits above its
50-session SMA), and a per-sector breakdown of that same breadth figure.
Every number is tagged with the bar date(s) and provider it came from. This
agent never forecasts and never recommends anything — it only restates what
the gating machinery already reads.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.agents.base import ResearchAgent
from signalforge.config import get_settings
from signalforge.data.series import PriceSeries
from signalforge.db.models import Instrument
from signalforge.research.features.daily import sma
from signalforge.research.regime import regime_from_proxy
from signalforge.settings_store import effective_research_config

_PROXY_SYMBOL = "SPY"
_LOOKBACK_YEARS = 6
_BREADTH_WINDOW = 50


def _breadth(
    session: Session,
    symbols: tuple[str, ...],
    start: date,
    end: date,
    source: str,
) -> tuple[float | None, int, int, date | None, dict[str, dict[str, Any]]]:
    """Share of ``symbols`` whose last close is above its 50-session SMA, plus a
    per-``Instrument.sector`` breakdown of the same figure. A symbol with no or
    insufficient history is skipped — never guessed."""
    above = 0
    total = 0
    last_seen: date | None = None
    sector_counts: dict[str, dict[str, int]] = {}
    for sym in symbols:
        series = PriceSeries.load(session, sym, start, end, source=source)
        if len(series) < _BREADTH_WINDOW:
            continue
        t = len(series) - 1
        sma50 = sma(series, t, _BREADTH_WINDOW)
        if sma50 != sma50:  # NaN: not enough history despite len() >= window
            continue
        inst = session.scalar(select(Instrument).where(Instrument.symbol == sym))
        sector = (inst.sector or "unknown") if inst is not None else "unknown"
        bucket = sector_counts.setdefault(sector, {"above": 0, "total": 0})
        bucket["total"] += 1
        total += 1
        bar_date = series.dates[t]
        if last_seen is None or bar_date > last_seen:
            last_seen = bar_date
        if float(series.close[t]) > sma50:
            above += 1
            bucket["above"] += 1
    pct = round(above / total * 100.0, 2) if total else None
    sector_regime = {
        sector: {
            "pct_above_50sma": (
                round(counts["above"] / counts["total"] * 100.0, 2) if counts["total"] else None
            ),
            "above_count": counts["above"],
            "total_count": counts["total"],
        }
        for sector, counts in sorted(sector_counts.items())
    }
    return pct, above, total, last_seen, sector_regime


def _realized_vol_20d_log(series: PriceSeries) -> float | None:
    """Annualized 20-session realized volatility computed from LOG returns
    (distinct from ``research.features.daily.realized_vol``, which uses simple
    returns)."""
    if len(series) < 21:
        return None
    closes = series.close[-21:]
    if np.any(closes <= 0):
        return None
    log_rets = np.diff(np.log(closes))
    if log_rets.size < 20:
        return None
    vol = float(np.std(log_rets, ddof=1) * math.sqrt(252))
    return round(vol, 4)


class MarketRegimeAgent(ResearchAgent):
    name = "market_regime"
    role = "Market-regime research agent"
    allowed_inputs = (
        "signalforge.data.series.PriceSeries (SPY proxy + research universe, research provider)",
        "signalforge.research.regime.regime_from_proxy",
        "signalforge.research.features.daily.sma",
        "signalforge.settings_store.effective_research_config (universe)",
        "signalforge.db.models.Instrument (sector)",
    )
    outputs = ("agent_report",)
    prohibited = ("forecast", "recommendation", "trade", "candidate", "alert", "setting change")
    llm_narrative = True

    def collect(self, session: Session) -> dict[str, Any]:
        missing: list[str] = []
        provider = get_settings().market_data_provider or "fixture"
        cfg = effective_research_config(session)
        universe = cfg.universe

        end = datetime.now(UTC).date()
        start = end - timedelta(days=365 * _LOOKBACK_YEARS)

        proxy = PriceSeries.load(session, _PROXY_SYMBOL, start, end, source=provider)
        spy_bars = len(proxy)

        regime_dict: dict[str, Any] | None = None
        spy_as_of: str | None = None
        vol_20d: float | None = None

        if spy_bars == 0:
            missing.append(
                f"no {_PROXY_SYMBOL} price history for provider={provider!r} in "
                f"[{start.isoformat()}, {end.isoformat()}]"
            )
        else:
            spy_as_of = proxy.dates[-1].isoformat()
            vol_20d = _realized_vol_20d_log(proxy)
            if vol_20d is None:
                missing.append(
                    f"fewer than 21 {_PROXY_SYMBOL} sessions available; "
                    "realized volatility not computed"
                )

        if universe:
            breadth_pct, above, total, breadth_as_of, sector_regime = _breadth(
                session, universe, start, end, provider
            )
            if total == 0:
                missing.append(
                    f"no price history for any of {len(universe)} research-universe symbols "
                    f"(provider={provider!r}); breadth not computed"
                )
        else:
            breadth_pct, above, total, breadth_as_of, sector_regime = None, 0, 0, None, {}
            missing.append("research universe is empty; breadth not computed")

        if spy_bars > 0:
            regime_state = regime_from_proxy(proxy, spy_bars - 1, breadth_pct=breadth_pct)
            regime_dict = regime_state.to_dict()

        return {
            "source": provider,
            "as_of": end.isoformat(),
            "window": {"start": start.isoformat(), "end": end.isoformat()},
            "spy": {
                "symbol": _PROXY_SYMBOL,
                "source": provider,
                "as_of": spy_as_of,
                "bars_available": spy_bars,
                "regime": regime_dict,
                "realized_vol_20d_annualized": vol_20d,
            },
            "breadth": {
                "source": provider,
                "as_of": breadth_as_of.isoformat() if breadth_as_of else None,
                "pct_above_50sma": breadth_pct,
                "above_count": above,
                "total_count": total,
                "universe_size": len(universe),
            },
            "sector_regime": sector_regime,
            "missing_data": missing,
        }

    def summarize(self, evidence: dict[str, Any]) -> str:
        spy = evidence["spy"]
        breadth = evidence["breadth"]
        regime = spy.get("regime")
        lines: list[str] = []

        if regime:
            lines.append(
                f"SPY trend is {regime['trend']} and volatility regime is {regime['vol']} "
                f"as of {regime['as_of']} (source: {spy['source']})."
            )
            if regime.get("market_ret_20d") is not None:
                lines.append(f"SPY trailing 20-session return: {regime['market_ret_20d']:.4f}.")
            if regime.get("market_ret_63d") is not None:
                lines.append(f"SPY trailing 63-session return: {regime['market_ret_63d']:.4f}.")
        else:
            lines.append("SPY regime is unavailable: no price history for the research provider.")

        if spy.get("realized_vol_20d_annualized") is not None:
            lines.append(
                "SPY realized 20-session volatility (annualized, log returns): "
                f"{spy['realized_vol_20d_annualized']:.4f} as of {spy['as_of']}."
            )

        if breadth.get("pct_above_50sma") is not None:
            lines.append(
                f"Breadth: {breadth['pct_above_50sma']:.2f}% of the "
                f"{breadth['total_count']}-symbol research universe closed above its "
                f"50-session SMA as of {breadth['as_of']} (source: {breadth['source']})."
            )
        else:
            lines.append("Breadth is unavailable: no price history for the research universe.")

        sector_regime = evidence.get("sector_regime") or {}
        parts = [
            f"{sector} {stats['pct_above_50sma']:.2f}%"
            for sector, stats in sorted(sector_regime.items())
            if stats.get("pct_above_50sma") is not None
        ]
        if parts:
            lines.append("Sector breadth (share above 50-session SMA): " + ", ".join(parts) + ".")

        return " ".join(lines)
