"""Portfolio-risk agent (read-only).

Restates the deterministic risk outputs already produced by
``signalforge.paper.portfolio`` and ``signalforge.risk.portfolio`` — exposure,
concentration, the configured risk budgets, the maximum pairwise 60-session
return correlation among open positions, and a simple realized+unrealized
drawdown figure — against the configured limits. This agent never sizes,
never trades, and never changes a limit; it only explains the numbers.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.agents.base import ResearchAgent
from signalforge.config import get_settings
from signalforge.data.series import PriceSeries
from signalforge.db.models import Instrument
from signalforge.paper.portfolio import portfolio_snapshot
from signalforge.research.features.daily import daily_returns
from signalforge.risk.portfolio import Holding, exposure_report
from signalforge.settings_store import effective_research_config

_CORRELATION_LOOKBACK_SESSIONS = 60
_CORRELATION_CALENDAR_DAYS = 150  # comfortably covers 60 trading sessions


def _max_abs_correlation(
    session: Session, symbols: list[str], source: str
) -> dict[str, Any] | None:
    """Max |corr| pair among ``symbols``' last 60-session daily returns.
    ``None`` when fewer than two symbols have a full 60-session history."""
    end = date.today()
    start = end - timedelta(days=_CORRELATION_CALENDAR_DAYS)
    returns_by_symbol: dict[str, np.ndarray] = {}
    for sym in symbols:
        series = PriceSeries.load(session, sym, start, end, source=source)
        if len(series) == 0:
            continue
        rets = daily_returns(series, len(series) - 1, _CORRELATION_LOOKBACK_SESSIONS)
        if rets.size == _CORRELATION_LOOKBACK_SESSIONS:
            returns_by_symbol[sym] = rets

    ordered = sorted(returns_by_symbol)
    best: dict[str, Any] | None = None
    best_abs = -1.0
    for i in range(len(ordered)):
        for j in range(i + 1, len(ordered)):
            a, b = ordered[i], ordered[j]
            corr = float(np.corrcoef(returns_by_symbol[a], returns_by_symbol[b])[0, 1])
            if corr == corr and abs(corr) > best_abs:  # not NaN
                best_abs = abs(corr)
                best = {"symbols": [a, b], "corr": round(corr, 4)}
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
        if len(open_positions) >= 2:
            symbols = [pos["symbol"] for pos in open_positions]
            max_pair = _max_abs_correlation(session, symbols, provider)
            if max_pair is None:
                missing.append(
                    f"insufficient {_CORRELATION_LOOKBACK_SESSIONS}-session price history "
                    "to compute pairwise correlation"
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
                f"{pair['corr']:.4f}."
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
