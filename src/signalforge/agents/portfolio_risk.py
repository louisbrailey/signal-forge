"""Portfolio-risk agent (read-only).

Restates the deterministic risk outputs already produced by
``signalforge.paper.portfolio`` and ``signalforge.risk.portfolio`` — exposure,
concentration, the configured risk budgets, the maximum pairwise 60-session
return correlation among open positions, and a simple realized+unrealized
drawdown figure — against the configured limits. This agent never sizes,
never trades, and never changes a limit; it only explains the numbers.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from itertools import combinations, pairwise
from math import isfinite
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.agents.base import ResearchAgent
from signalforge.config import get_settings
from signalforge.data.calendar import last_closed_session, sessions
from signalforge.data.series import PriceSeries
from signalforge.db.models import Instrument
from signalforge.paper.portfolio import portfolio_snapshot
from signalforge.risk.portfolio import Holding, exposure_report
from signalforge.settings_store import effective_research_config

_CORRELATION_LOOKBACK_SESSIONS = 60
_CORRELATION_CALENDAR_DAYS = 150  # comfortably covers 60 trading sessions


def _session_returns(
    series: PriceSeries, calendar: tuple[date, ...]
) -> dict[tuple[date, date], float]:
    """Return only intervals with both adjacent exchange-session closes."""
    closes = dict(zip(series.dates, map(float, series.close), strict=True))
    if len(closes) != len(series):
        return {}
    returns = {}
    for previous, current in pairwise(calendar):
        before = closes.get(previous)
        after = closes.get(current)
        if before is None or after is None:
            continue
        if not all(isfinite(price) and price > 0 for price in (before, after)):
            continue
        value = after / before - 1
        if isfinite(value):
            returns[previous, current] = value
    return returns


def _max_abs_correlation(
    session: Session, symbols: list[str], source: str, *, end: date
) -> dict[str, Any] | None:
    """Rank pairs using their latest 60 common one-session returns."""
    start = end - timedelta(days=_CORRELATION_CALENDAR_DAYS)
    calendar = sessions(start, end)
    returns_by_symbol = {
        symbol: _session_returns(
            PriceSeries.load(session, symbol, start, end, source=source), calendar
        )
        for symbol in sorted(set(symbols))
    }
    best: dict[str, Any] | None = None
    best_abs = -1.0
    for a, b in combinations(returns_by_symbol, 2):
        left, right = returns_by_symbol[a], returns_by_symbol[b]
        common = sorted(left.keys() & right.keys())
        if len(common) < _CORRELATION_LOOKBACK_SESSIONS:
            continue
        sample = common[-_CORRELATION_LOOKBACK_SESSIONS:]
        x = [left[interval] for interval in sample]
        y = [right[interval] for interval in sample]
        if min(x) == max(x) or min(y) == max(y):
            continue
        corr = float(np.corrcoef(x, y)[0, 1])
        if isfinite(corr) and abs(corr) > best_abs:
            best_abs = abs(corr)
            best = {
                "symbols": [a, b],
                "corr": round(corr, 4),
                "sample_count": len(sample),
                "common_return_count": len(common),
                "first_close_session": sample[0][0].isoformat(),
                "last_close_session": sample[-1][1].isoformat(),
            }
    return best


class PortfolioRiskAgent(ResearchAgent):
    name = "portfolio_risk"
    role = "Portfolio-risk agent"
    allowed_inputs = (
        "signalforge.paper.portfolio.portfolio_snapshot",
        "signalforge.db.models.PaperPosition (open, qty/avg_price/side)",
        "signalforge.db.models.Instrument (sector)",
        "signalforge.risk.portfolio.exposure_report",
        "signalforge.settings_store.effective_research_config (risk budgets)",
        "signalforge.data.series.PriceSeries (60-session returns, research provider)",
    )
    outputs = ("agent_report",)
    prohibited = ("order", "position size", "rule override", "trade", "alert", "setting change")
    llm_narrative = True

    def collect(self, session: Session) -> dict[str, Any]:
        missing: list[str] = []
        provider = get_settings().market_data_provider or "fixture"
        risk_cfg = effective_research_config(session).risk

        snap = portfolio_snapshot(session)
        exists = bool(snap.get("exists"))
        if not exists:
            missing.append("no paper account named 'default' found")

        open_positions: list[dict[str, Any]] = snap.get("open_positions", []) if exists else []
        equity = float(snap.get("equity_estimate", 0.0)) if exists else 0.0

        holdings: list[Holding] = []
        for pos in open_positions:
            inst = session.scalar(select(Instrument).where(Instrument.symbol == pos["symbol"]))
            sector = (inst.sector or "unknown") if inst is not None else "unknown"
            sign = 1.0 if pos["side"] == "long" else -1.0
            holdings.append(
                Holding(
                    symbol=pos["symbol"],
                    sector=sector,
                    market_value=float(pos["last_price"]) * pos["qty"] * sign,
                )
            )
        exposure = exposure_report(holdings, account_equity=equity)
        gross_exposure_pct = (
            round(exposure.gross_exposure / equity * 100.0, 2) if equity > 0 else None
        )
        if not open_positions:
            missing.append("no open paper positions; exposure/concentration not meaningful")

        max_pair: dict[str, Any] | None = None
        correlation_cutoff = last_closed_session(datetime.now(UTC))
        if len(open_positions) >= 2:
            symbols = [pos["symbol"] for pos in open_positions]
            max_pair = _max_abs_correlation(session, symbols, provider, end=correlation_cutoff)
            if max_pair is None:
                missing.append(
                    f"pairwise correlation requires {_CORRELATION_LOOKBACK_SESSIONS} common "
                    "one-session returns with variation"
                )
        else:
            missing.append("fewer than 2 open positions; pairwise correlation not computed")

        n_open = int(snap.get("n_open", 0)) if exists else 0
        n_closed = int(snap.get("n_closed", 0)) if exists else 0
        drawdown: dict[str, Any] | None = None
        if exists and (n_open > 0 or n_closed > 0):
            realized = float(snap.get("realized_pnl", 0.0))
            unrealized = float(snap.get("unrealized_pnl", 0.0))
            initial_cash = float(snap.get("initial_cash", 0.0))
            total_pnl = realized + unrealized
            drawdown_pct = (
                round(min(0.0, total_pnl / initial_cash * 100.0), 2) if initial_cash > 0 else None
            )
            drawdown = {
                "realized_pnl": round(realized, 2),
                "unrealized_pnl": round(unrealized, 2),
                "drawdown_pct": drawdown_pct,
                "as_of": date.today().isoformat(),
            }
        else:
            missing.append("no closed or open positions; drawdown not computed")

        return {
            "source": "paper.portfolio.portfolio_snapshot",
            "as_of": date.today().isoformat(),
            "account": {
                "exists": exists,
                "equity_estimate": round(equity, 2),
                "n_open": n_open,
                "n_closed": n_closed,
            },
            "exposure": {**exposure.to_dict(), "gross_exposure_pct": gross_exposure_pct},
            "risk_limits": {
                "source": "effective_research_config",
                "per_trade_risk_pct": risk_cfg.per_trade_risk_pct,
                "max_position_concentration_pct": risk_cfg.max_position_concentration_pct,
                "max_portfolio_exposure_pct": risk_cfg.max_portfolio_exposure_pct,
            },
            "correlation": {
                "source": provider,
                "lookback_sessions": _CORRELATION_LOOKBACK_SESSIONS,
                "through_session": correlation_cutoff.isoformat(),
                "max_abs_pair": max_pair,
            },
            "drawdown": drawdown,
            "missing_data": missing,
        }

    def summarize(self, evidence: dict[str, Any]) -> str:
        acct = evidence["account"]
        exposure = evidence["exposure"]
        limits = evidence["risk_limits"]
        corr = evidence["correlation"]
        drawdown = evidence["drawdown"]
        lines: list[str] = []

        if not acct["exists"]:
            lines.append("No paper account found; portfolio risk cannot be assessed.")
        else:
            lines.append(
                f"Open positions: {acct['n_open']}, closed positions: {acct['n_closed']}. "
                f"Estimated equity: {acct['equity_estimate']}."
            )
            lines.append(
                f"Configured per-trade risk budget: {limits['per_trade_risk_pct']:.2f}% "
                "of account."
            )
            if exposure["n_positions"] > 0:
                lines.append(
                    f"Largest position: {exposure['largest_position_symbol']} at "
                    f"{exposure['largest_position_pct']:.2f}% of equity "
                    f"(configured concentration limit "
                    f"{limits['max_position_concentration_pct']:.2f}%)."
                )
                if exposure.get("gross_exposure_pct") is not None:
                    lines.append(
                        f"Gross exposure: {exposure['gross_exposure_pct']:.2f}% of equity "
                        "(configured portfolio exposure limit "
                        f"{limits['max_portfolio_exposure_pct']:.2f}%)."
                    )
            else:
                lines.append("No open positions to assess concentration or exposure against.")

        if corr.get("max_abs_pair"):
            pair = corr["max_abs_pair"]
            lines.append(
                f"Highest pairwise {corr['lookback_sessions']}-session return correlation "
                f"among open positions: {pair['symbols'][0]}/{pair['symbols'][1]} at "
                f"{pair['corr']:.4f}, using {pair['sample_count']} aligned returns "
                f"through {pair['last_close_session']}."
            )
        else:
            lines.append("Pairwise return correlation among open positions is unavailable.")

        if drawdown:
            tail = (
                f", current drawdown {drawdown['drawdown_pct']:.2f}%."
                if drawdown.get("drawdown_pct") is not None
                else "."
            )
            lines.append(
                f"Realized P&L {drawdown['realized_pnl']}, "
                f"unrealized P&L {drawdown['unrealized_pnl']}{tail}"
            )
        else:
            lines.append("Drawdown cannot be computed: no closed or open positions.")

        lines.append("This agent explains deterministic risk outputs and cannot override any rule.")
        return " ".join(lines)
