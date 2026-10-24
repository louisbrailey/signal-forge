"""Deterministic daily-briefing assembly (ARCHITECTURE.md §1.11).

This module produces the **frozen facts dict** and a complete, correct Markdown
briefing with NO LLM involvement. It lives in ``research`` and therefore must not
import :mod:`signalforge.llm` (invariant S3). The optional LLM narrative pass is
orchestrated one level up, in :mod:`signalforge.briefing`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge import RESEARCH_ONLY_NOTICE
from signalforge.data.feeds import feed_status_report
from signalforge.data.market_context import read_context
from signalforge.db.models import Instrument, OHLCVDaily, PaperPosition, ScanRun
from signalforge.db.types import utcnow
from signalforge.domain import PositionSide, QualityGate
from signalforge.paper.portfolio import portfolio_snapshot
from signalforge.settings_store import effective_research_config


def _market_status(session: Session, as_of: date) -> dict[str, Any]:
    last = session.scalar(
        select(OHLCVDaily.session_date)
        .join(Instrument)
        .where(Instrument.symbol == "SPY")
        .order_by(OHLCVDaily.session_date.desc())
        .limit(1)
    )
    return {
        "as_of": as_of.isoformat(),
        "proxy": "SPY",
        "last_proxy_session": last.isoformat() if last else None,
        "proxy_data_current": bool(last and (as_of - last).days <= 4),
    }


def _open_risk(
    session: Session, account_name: str | None, cfg_daily_risk_pct: float
) -> dict[str, Any]:
    """Open stop risk of one named account, or of every equity book (the cap
    applies PER BOOK, so ``over_limit`` is true when any one book is over)."""
    from signalforge.db.models import PaperAccount
    from signalforge.paper.books import equity_books

    if account_name is not None:
        named = session.scalar(select(PaperAccount).where(PaperAccount.name == account_name))
        accounts = [named] if named is not None else []
    else:
        accounts = equity_books(session)
    if not accounts:
        return {"exists": False}
    n_open = 0
    total_risk = 0.0
    total_cap = 0.0
    over = False
    for acct in accounts:
        positions = list(
            session.scalars(
                select(PaperPosition).where(
                    PaperPosition.account_id == acct.id, PaperPosition.closed_at.is_(None)
                )
            )
        )
        open_risk = 0.0
        for p in positions:
            if p.stop_level is None:
                continue
            d = 1 if p.side is PositionSide.LONG else -1
            open_risk += abs(d * (float(p.avg_price) - p.stop_level)) * p.qty
        cap = float(acct.initial_cash) * cfg_daily_risk_pct / 100.0
        n_open += len(positions)
        total_risk += open_risk
        total_cap += cap
        over = over or open_risk > cap
    return {
        "exists": True,
        "open_positions": n_open,
        "open_risk_dollars": round(total_risk, 2),
        "daily_risk_cap_dollars": round(total_cap, 2),
        "over_limit": over,
    }


def build_briefing_facts(
    session: Session, *, account_name: str | None = None, as_of: date | None = None
) -> dict[str, Any]:
    on = as_of or date.today()
    cfg = effective_research_config(session)
    feeds = feed_status_report(session)
    any_stale = (not feeds["feeds"]) or any(f["is_stale"] for f in feeds["feeds"])

    horizons: list[dict[str, Any]] = []
    qualified: list[dict[str, Any]] = []
    no_trade_reasons: dict[str, int] = {}
    no_trade_total = 0
    for h in cfg.enabled_horizons:
        run = session.scalar(
            select(ScanRun).where(ScanRun.horizon == h).order_by(ScanRun.started_at.desc()).limit(1)
        )
        if run is None:
            horizons.append({"horizon": h.value, "has_run": False})
            continue
        no_trade_total += run.no_trade_count
        for reason, info in (run.exclusions_json or {}).items():
            no_trade_reasons[reason] = no_trade_reasons.get(reason, 0) + int(info.get("count", 0))
        from signalforge.db.models import Candidate

        passed = list(
            session.scalars(
                select(Candidate).where(
                    Candidate.scan_run_id == run.id,
                    Candidate.quality_gate_status == QualityGate.PASSED,
                )
            )
        )
        for c in passed:
            inst = session.get(Instrument, c.instrument_id)
            qualified.append(
                {
                    "symbol": inst.symbol if inst else "?",
                    "horizon": h.value,
                    "direction": c.direction.value,
                    "entry_zone": [c.entry_zone_low, c.entry_zone_high],
                    "invalidation": c.invalidation_level,
                    "reward_risk": c.reward_risk_estimate,
                    "risk_pct": c.risk_pct_of_account,
                    "candidate_id": c.id,
                }
            )
        horizons.append(
            {
                "horizon": h.value,
                "has_run": True,
                "started_at": run.started_at.isoformat(),
                "scanned": run.scanned_count,
                "excluded": run.excluded_count,
                "no_trade": run.no_trade_count,
                "qualified": run.candidate_count,
            }
        )

    snap = portfolio_snapshot(session, account_name=account_name)
    risk = _open_risk(session, account_name, cfg.risk.max_daily_portfolio_risk_pct)

    warnings: list[str] = []
    if any_stale:
        warnings.append("A required data feed is stale/unregistered — live alerts are disabled.")
    if risk.get("over_limit"):
        warnings.append("Open paper risk exceeds the daily portfolio-risk limit.")
    if not qualified:
        warnings.append("No qualified candidates — NO TRADE across all horizons (normal).")

    return {
        "generated_at": utcnow().isoformat(),
        "cross_asset_context": read_context(
            session, as_of=min(utcnow(), datetime.combine(on, time.max, UTC))
        ),
        "config_hash": cfg.config_hash,
        "market": _market_status(session, on),
        "feeds": feeds["feeds"],
        "any_feed_stale": any_stale,
        "live_alerts_enabled": not any_stale,
        "paper_account": (
            {
                k: snap[k]
                for k in (
                    "cash",
                    "equity_estimate",
                    "return_pct",
                    "unrealized_pnl",
                    "realized_pnl",
                    "n_open",
                    "n_closed",
                )
                if k in snap
            }
            if snap.get("exists")
            else {"exists": False}
        ),
        "open_risk": risk,
        "horizons": horizons,
        "qualified_candidates": qualified,
        "no_trade_total": no_trade_total,
        "no_trade_reasons": no_trade_reasons,
        "warnings": warnings,
    }


def render_briefing_text(facts: dict[str, Any]) -> str:
    lines = [
        f"# Signal Forge daily briefing — {facts['market']['as_of']}",
        "",
        f"_{RESEARCH_ONLY_NOTICE}_  Hypothetical research output, not financial advice.",
        f"_Generated {facts['generated_at']} · config hash `{facts['config_hash'][:16]}`_",
        "",
        "## Market & data",
        f"- Proxy {facts['market']['proxy']}, last session "
        f"{facts['market']['last_proxy_session'] or 'n/a'} "
        f"({'current' if facts['market']['proxy_data_current'] else 'STALE'})",
        f"- Live alerts: {'enabled' if facts['live_alerts_enabled'] else 'DISABLED (stale feed)'}",
    ]
    for f in facts["feeds"]:
        lines.append(
            f"  - {f['provider']}/{f['feed_type']} · {f['latency_category']}"
            f"{' · SIMULATED' if f['is_simulated'] else ''}"
            f"{' · STALE' if f['is_stale'] else ''}"
        )

    lines.append("## Cross-asset context (END-OF-DAY; not a trade input)")
    for row in facts.get("cross_asset_context", []):
        lines.append(
            f"- {row['symbol']}: {row['close']} · {row['timestamp']} · "
            f"{row['source']} · {row['status']}"
        )

    pa = facts["paper_account"]
    lines += ["", "## Paper account"]
    if pa.get("exists") is False:
        lines.append("- No paper account. Run `signalforge seed`.")
    else:
        lines.append(
            f"- Equity ~${pa.get('equity_estimate', 0):.2f} "
            f"({pa.get('return_pct', 0):+.2f}%) · cash ${pa.get('cash', 0):.2f}"
        )
        u = pa.get("unrealized_pnl", 0)
        rl = pa.get("realized_pnl", 0)
        lines.append(
            f"- {pa.get('n_open', 0)} open · {pa.get('n_closed', 0)} closed · "
            f"unrealized {u:+.2f} · realized {rl:+.2f}"
        )
    r = facts["open_risk"]
    if r.get("exists"):
        lines.append(
            f"- Open risk ${r['open_risk_dollars']:.2f} of ${r['daily_risk_cap_dollars']:.2f} cap"
            f"{'  ⚠ OVER LIMIT' if r['over_limit'] else ''}"
        )

    lines += ["", "## Scans"]
    for h in facts["horizons"]:
        if not h["has_run"]:
            lines.append(f"- {h['horizon']}: no scan yet")
            continue
        lines.append(
            f"- {h['horizon']}: scanned {h['scanned']}, excluded {h['excluded']}, "
            f"NO TRADE {h['no_trade']}, qualified {h['qualified']}"
        )

    lines += ["", "## Today's qualified candidates"]
    if not facts["qualified_candidates"]:
        lines.append(
            f"- **NONE.** {facts['no_trade_total']} setup(s) evaluated and rejected — "
            "a normal, frequent result."
        )
        if facts["no_trade_reasons"]:
            lines.append(
                "- Exclusion reasons: "
                + ", ".join(f"{k} {v}" for k, v in facts["no_trade_reasons"].items())
            )
    else:
        for c in facts["qualified_candidates"]:
            lines.append(
                f"- {c['symbol']} {c['direction']} ({c['horizon']}) — entry "
                f"{c['entry_zone'][0]:.2f}–{c['entry_zone'][1]:.2f}, stop {c['invalidation']:.2f}, "
                f"R:R {c['reward_risk']:.2f}, risk {c['risk_pct']:.2f}% "
                f"→ /candidates/{c['candidate_id']}"
            )

    if facts["warnings"]:
        lines += ["", "## Warnings"]
        lines += [f"- ⚠ {w}" for w in facts["warnings"]]

    lines += [
        "",
        "---",
        "Every candidate is a hypothetical research output. No brokerage was "
        "contacted and no order was placed. Verify every input independently.",
        "",
    ]
    return "\n".join(lines)
