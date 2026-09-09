"""Read-model assembly for the server-rendered dashboard pages.

Pure query + shaping. No writes. Every value the templates show carries its
source, timestamp, and latency category where relevant (invariant S7); a stale
feed drives the "live alerts disabled" banner (invariant S8).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.data.feeds import feed_status_report
from signalforge.data.series import PriceSeries
from signalforge.db.models import (
    Candidate,
    EarningsEvent,
    Instrument,
    JournalEntry,
    PaperTrade,
    ScanRun,
    Strategy,
    StrategyVersion,
)
from signalforge.domain import FeedType, Horizon, QualityGate, StrategyStatus
from signalforge.killswitch import get_kill_switch
from signalforge.paper.journal import weekly_review
from signalforge.paper.portfolio import portfolio_snapshot
from signalforge.research.display import (
    NO_TRADE_MESSAGE,
    confidence_note,
    probability_display,
)
from signalforge.research.persistence import latest_oos_metric
from signalforge.research.strategies import default_strategies
from signalforge.settings_store import effective_research_config, get_setting


def _latest_scan(session: Session, horizon: Horizon) -> ScanRun | None:
    return session.scalar(
        select(ScanRun)
        .where(ScanRun.horizon == horizon)
        .order_by(ScanRun.started_at.desc())
        .limit(1)
    )


def _candidate_rows(
    session: Session, scan_run_id: int, *, only_passed: bool
) -> list[dict[str, Any]]:
    stmt = (
        select(Candidate, Instrument.symbol, Instrument.sector, Strategy.name)
        .join(Instrument, Candidate.instrument_id == Instrument.id)
        .join(StrategyVersion, Candidate.strategy_version_id == StrategyVersion.id)
        .join(Strategy, StrategyVersion.strategy_id == Strategy.id)
        .where(Candidate.scan_run_id == scan_run_id)
        .order_by(Candidate.rank_in_horizon.is_(None), Candidate.rank_in_horizon)
    )
    if only_passed:
        stmt = stmt.where(Candidate.quality_gate_status == QualityGate.PASSED)
    out: list[dict[str, Any]] = []
    for cand, symbol, sector, strat_name in session.execute(stmt):
        out.append(
            {
                "id": cand.id,
                "symbol": symbol,
                "sector": sector or "unknown",
                "strategy": strat_name,
                "horizon": cand.horizon.value,
                "direction": cand.direction.value,
                "entry_low": cand.entry_zone_low,
                "entry_high": cand.entry_zone_high,
                "stop": cand.invalidation_level,
                "target": cand.target_level,
                "reward_risk": cand.reward_risk_estimate,
                "risk_dollars": cand.risk_dollars,
                "risk_pct": cand.risk_pct_of_account,
                "rank": cand.rank_in_horizon,
                "status": cand.quality_gate_status.value,
                "failed_gates": cand.failed_gates,
                "reasons_qualify": cand.reasons_qualify,
                "event_risk": cand.event_risk_json,
                "liquidity": cand.liquidity_json,
            }
        )
    return out


def overview_context(session: Session) -> dict[str, Any]:
    feeds = feed_status_report(session)
    any_stale = any(f["is_stale"] for f in feeds["feeds"]) or not feeds["feeds"]
    snap = portfolio_snapshot(session)
    cfg = effective_research_config(session)

    horizons: list[dict[str, Any]] = []
    todays_candidates: list[dict[str, Any]] = []
    no_trade_total = 0
    for h in cfg.enabled_horizons:
        run = _latest_scan(session, h)
        if run is None:
            horizons.append({"horizon": h.value, "has_run": False})
            continue
        passed = _candidate_rows(session, run.id, only_passed=True)
        todays_candidates.extend(passed)
        no_trade_total += run.no_trade_count
        horizons.append(
            {
                "horizon": h.value,
                "has_run": True,
                "started_at": run.started_at.isoformat(),
                "scanned": run.scanned_count,
                "excluded": run.excluded_count,
                "exclusions": run.exclusions_json,
                "no_trade": run.no_trade_count,
                "qualified": run.candidate_count,
            }
        )

    warnings: list[str] = []
    if any_stale:
        warnings.append("A required data feed is stale or unregistered — live alerts are disabled.")
    if snap.get("exists") and snap.get("open_risk_pct_gt_limit"):
        warnings.append("Open paper risk exceeds the configured daily limit.")

    ks = get_kill_switch().state()
    last_bar = session.scalar(select(Instrument.symbol).where(Instrument.symbol == "SPY"))
    return {
        "feeds": feeds["feeds"],
        "any_stale": any_stale,
        "live_alerts_enabled": not any_stale,
        "paper": snap,
        "horizons": horizons,
        "todays_candidates": todays_candidates,
        "no_trade_total": no_trade_total,
        "warnings": warnings,
        "kill_switch": ks,
        "market_proxy_present": last_bar is not None,
        "config_hash": cfg.config_hash,
        "news": _news_items(session, None, 6),
    }


def scanner_context(
    session: Session,
    *,
    horizon: str | None = None,
    strategy: str | None = None,
    sector: str | None = None,
    min_reward_risk: float = 0.0,
    exclude_event_risk: bool = False,
) -> dict[str, Any]:
    cfg = effective_research_config(session)
    horizons = [h.value for h in cfg.enabled_horizons]
    selected = horizon if horizon in horizons else (horizons[0] if horizons else None)

    rows: list[dict[str, Any]] = []
    run_meta: dict[str, Any] | None = None
    if selected:
        run = _latest_scan(session, Horizon(selected))
        if run is not None:
            run_meta = {
                "started_at": run.started_at.isoformat(),
                "scanned": run.scanned_count,
                "excluded": run.excluded_count,
                "exclusions": run.exclusions_json,
                "no_trade": run.no_trade_count,
                "qualified": run.candidate_count,
            }
            rows = _candidate_rows(session, run.id, only_passed=True)

    def _keep(r: dict[str, Any]) -> bool:
        if strategy and r["strategy"] != strategy:
            return False
        if sector and r["sector"] != sector:
            return False
        if r["reward_risk"] < min_reward_risk:
            return False
        return not (exclude_event_risk and r["event_risk"].get("upcoming_earnings"))

    rows = [r for r in rows if _keep(r)]
    return {
        "horizons": horizons,
        "selected_horizon": selected,
        "run": run_meta,
        "candidates": rows,
        "strategies": sorted({s.spec().name for s in default_strategies()}),
        "sectors": sorted({r["sector"] for r in rows}) if rows else [],
        "filters": {
            "strategy": strategy,
            "sector": sector,
            "min_reward_risk": min_reward_risk,
            "exclude_event_risk": exclude_event_risk,
        },
    }


def _sparkline(closes: list[float], width: int = 480, height: int = 120) -> str:
    if len(closes) < 2:
        return ""
    lo, hi = min(closes), max(closes)
    span = (hi - lo) or 1.0
    step = width / (len(closes) - 1)
    pts = " ".join(
        f"{i * step:.1f},{height - (c - lo) / span * (height - 8) - 4:.1f}"
        for i, c in enumerate(closes)
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        f'preserveAspectRatio="none" role="img" aria-label="price sparkline">'
        f'<polyline fill="none" stroke="currentColor" stroke-width="1.5" points="{pts}"/>'
        f"</svg>"
    )


def _calibration_meta(
    strategy_name: str | None, version: str | None, calibration_ref: str | None
) -> dict[str, Any] | None:
    if not (strategy_name and version and calibration_ref):
        return None
    from signalforge.research.probability import load_calibration

    art = load_calibration(strategy_name, version)
    if art is None:
        return None
    return {
        "n_validation_trades": art.n_validation_trades,
        "validation_start": art.validation_start,
        "validation_end": art.validation_end,
        "version": art.version,
    }


def candidate_context(session: Session, candidate_id: int) -> dict[str, Any] | None:
    cand = session.get(Candidate, candidate_id)
    if cand is None:
        return None
    inst = session.get(Instrument, cand.instrument_id)
    ver = session.get(StrategyVersion, cand.strategy_version_id)
    strat = session.get(Strategy, ver.strategy_id) if ver else None
    spec_json = ver.spec_json if ver else {}

    end = date.today()
    series = (
        PriceSeries.load(session, inst.symbol, end - timedelta(days=260), end) if inst else None
    )
    closes = list(series.close[-120:]) if series and len(series) else []
    last_bar_date = series.dates[-1].isoformat() if series and len(series) else None

    # OOS backtest evidence for this exact strategy version

    spec_obj = None
    for s in default_strategies():
        if s.spec().name == (strat.name if strat else None):
            spec_obj = s.spec()
            break
    metric = latest_oos_metric(session, spec_obj) if spec_obj else None

    upcoming = []
    if inst:
        upcoming = [
            e.scheduled_for.isoformat()
            for e in session.scalars(
                select(EarningsEvent).where(
                    EarningsEvent.instrument_id == inst.id,
                    EarningsEvent.scheduled_for >= end,
                    EarningsEvent.scheduled_for <= end + timedelta(days=90),
                )
            )
        ]

    return {
        "candidate": cand,
        "symbol": inst.symbol if inst else "?",
        "sector": (inst.sector if inst else "") or "unknown",
        "strategy_name": strat.name if strat else "?",
        "strategy_version": ver.version if ver else "?",
        "spec": spec_json,
        "spec_obj": spec_obj,
        "sparkline_svg": _sparkline(closes),
        "last_bar_date": last_bar_date,
        "n_bars": len(series) if series else 0,
        "oos_metric": metric.metrics_json if metric else None,
        "oos_ci": (metric.ci_json if metric else None),
        "upcoming_earnings": upcoming,
        "probability_display": probability_display(
            cand.probability_calibrated, cand.calibration_ref
        ),
        "confidence_note": confidence_note(cand.calibration_ref),
        "calibration_meta": _calibration_meta(
            strat.name if strat else None, ver.version if ver else None, cand.calibration_ref
        ),
        "no_trade_message": (
            NO_TRADE_MESSAGE if cand.quality_gate_status is not QualityGate.PASSED else None
        ),
        "data_freshness": cand.data_freshness_json,
        "ranking": cand.ranking_json,
        "news": _news_items(session, inst.symbol if inst else None, 6),
    }


def _payoff_svg(points: list[tuple[float, float]], w: int = 520, h: int = 180) -> str:
    """Payoff chart: x = underlying price, y = P&L. Zero line drawn."""
    if len(points) < 2:
        return ""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    xlo, xhi = min(xs), max(xs)
    ylo, yhi = min([*ys, 0.0]), max([*ys, 0.0])
    xspan = (xhi - xlo) or 1.0
    yspan = (yhi - ylo) or 1.0

    def px(x: float) -> float:
        return (x - xlo) / xspan * (w - 8) + 4

    def py(y: float) -> float:
        return h - ((y - ylo) / yspan * (h - 16) + 8)

    line = " ".join(f"{px(x):.1f},{py(y):.1f}" for x, y in points)
    zero_y = py(0.0)
    return (
        f'<svg viewBox="0 0 {w} {h}" width="100%" height="{h}" role="img" '
        f'aria-label="option payoff at expiry">'
        f'<line x1="0" y1="{zero_y:.1f}" x2="{w}" y2="{zero_y:.1f}" stroke="#94a3b8" '
        f'stroke-dasharray="3 3" stroke-width="1"/>'
        f'<polyline fill="none" stroke="currentColor" stroke-width="2" points="{line}"/>'
        f"</svg>"
    )


_OPT_RISK_WARNINGS = [
    "Long options can expire worthless — the entire premium is at risk.",
    "Liquidity/spread: wide bid-ask on illiquid strikes materially raises real cost; "
    "this build has no live quote entitlement, so spread is estimated, not observed.",
    "Assignment: a short call (covered) or short put (cash-secured) can be assigned early, "
    "especially around ex-dividend dates.",
    "Event risk: earnings and macro releases can gap the underlying through your stop or strike.",
    "All figures are hypothetical, education-only. No order is ever placed.",
]


def options_context(
    session: Session,
    *,
    underlying: str | None = None,
    expiration: str | None = None,
    contract: str | None = None,
    sim: str = "long_call",
    spot: float | None = None,
    strike: float | None = None,
    premium: float | None = None,
) -> dict[str, Any]:
    from sqlalchemy import func

    from signalforge.db.models import EntitlementCheck as _EC
    from signalforge.db.models import OptionContract, OptionQuoteSnapshot
    from signalforge.options import COMPUTED_NOTE, DISCLAIMER
    from signalforge.options import simulators as _sim
    from signalforge.settings_store import effective_research_config

    cfg = effective_research_config(session).options
    underlyings = list(cfg.underlyings)
    u = (underlying or (underlyings[0] if underlyings else "SPY")).upper()

    # entitlement snapshot for the options-quote caveat
    quote_row = session.scalar(
        select(_EC)
        .where(_EC.feed == "options_quotes_bidask")
        .order_by(_EC.checked_at.desc())
        .limit(1)
    )
    quotes_available = bool(quote_row and quote_row.available)

    # chain explorer — latest snapshot per contract for this underlying
    latest_asof = session.scalar(
        select(func.max(OptionQuoteSnapshot.as_of)).where(
            OptionQuoteSnapshot.underlying_symbol == u
        )
    )
    chain: list[dict[str, Any]] = []
    expirations: list[str] = []
    if latest_asof is not None:
        rows = session.execute(
            select(OptionQuoteSnapshot, OptionContract)
            .join(
                OptionContract,
                OptionContract.option_ticker == OptionQuoteSnapshot.option_ticker,
            )
            .where(
                OptionQuoteSnapshot.underlying_symbol == u,
                OptionQuoteSnapshot.as_of == latest_asof,
            )
            .order_by(OptionContract.expiration_date, OptionContract.strike_price)
        ).all()
        expirations = sorted({c.expiration_date.isoformat() for _, c in rows})
        for snap, c in rows:
            if expiration and c.expiration_date.isoformat() != expiration:
                continue
            g = snap.vendor_greeks_json or {}
            chain.append(
                {
                    "ticker": c.option_ticker,
                    "type": c.contract_type,
                    "strike": c.strike_price,
                    "expiration": c.expiration_date.isoformat(),
                    "day_close": snap.day_close,
                    "last_trade": snap.last_trade_price,
                    "last_trade_at": snap.last_trade_at.isoformat() if snap.last_trade_at else None,
                    "volume": snap.day_volume,
                    "open_interest": snap.open_interest,
                    "iv": snap.vendor_iv,
                    "delta": g.get("delta"),
                    "gamma": g.get("gamma"),
                    "theta": g.get("theta"),
                    "vega": g.get("vega"),
                    "break_even": snap.break_even_price,
                    "underlying_price": snap.underlying_price,
                }
            )

    # contract detail
    detail = next((c for c in chain if c["ticker"] == contract), None)

    # simulator — pure math, always available
    ref_spot = spot or (detail["underlying_price"] if detail else None) or 100.0
    ref_strike = strike or (detail["strike"] if detail else round(ref_spot))
    ref_prem = premium or (
        (detail["last_trade"] or detail["day_close"]) if detail else round(ref_spot * 0.02, 2)
    )
    fns = {
        "long_call": _sim.long_call,
        "long_put": _sim.long_put,
        "covered_call": _sim.covered_call,
        "cash_secured_put": _sim.cash_secured_put,
    }
    sim_fn = fns.get(sim, _sim.long_call)
    res = sim_fn(float(ref_spot), float(ref_strike), float(ref_prem))
    payoff_pts = [(p.underlying, p.pnl) for p in res.payoff_at_expiry]
    decay = _sim.time_decay_curve(
        float(ref_spot),
        float(ref_strike),
        iv=(detail["iv"] if detail and detail.get("iv") else 0.25),
        days_to_expiry=30,
        call=sim not in ("long_put",),
    )

    return {
        "underlyings": underlyings,
        "selected_underlying": u,
        "expirations": expirations,
        "selected_expiration": expiration,
        "chain": chain,
        "chain_as_of": latest_asof.isoformat() if latest_asof else None,
        "detail": detail,
        "quotes_available": quotes_available,
        "quote_note": (
            "Live bid/ask (NBBO) quotes are NOT entitled on this plan — "
            "spread is estimated, not observed. Prices shown are the last delayed "
            "trade and the delayed daily close."
        ),
        "computed_note": COMPUTED_NOTE,
        "sim": {
            "kind": sim,
            "spot": ref_spot,
            "strike": ref_strike,
            "premium": ref_prem,
            "result": res,
            "payoff_svg": _payoff_svg(payoff_pts),
            "decay": decay,
        },
        "risk_warnings": _OPT_RISK_WARNINGS,
        "disclaimer": DISCLAIMER,
    }


def _news_items(session: Session, symbol: str | None, limit: int) -> list[dict[str, Any]]:
    """Shared news read-model row shaping (used by /news, overview, candidate)."""
    from signalforge.db.models import NewsItem

    stmt = select(NewsItem).order_by(NewsItem.published_at.desc()).limit(limit)
    if symbol:
        stmt = (
            select(NewsItem)
            .where(NewsItem.instrument_symbols.contains([symbol.upper()]))
            .order_by(NewsItem.published_at.desc())
            .limit(limit)
        )
    return [
        {
            "headline": r.headline,
            "url": r.url,
            "publisher": r.source,
            "provider": r.provider,
            "author": r.author,
            "category": r.category,
            "published_at": r.published_at.isoformat(),
            "retrieved_at": r.retrieved_at.isoformat() if r.retrieved_at else None,
            "tickers": r.instrument_symbols,
            "dedupe_key": r.dedupe_key,
        }
        for r in session.scalars(stmt)
    ]


def news_context(session: Session, *, symbol: str | None = None, limit: int = 40) -> dict[str, Any]:
    from signalforge.db.models import EntitlementCheck as _EC

    benz = session.scalar(
        select(_EC).where(_EC.feed == "benzinga_news").order_by(_EC.checked_at.desc()).limit(1)
    )
    benz_ok = bool(benz and benz.available)
    # The verifier distinguishes "not authenticated/entitled" from "authenticated
    # but the feed has stopped delivering fresh Benzinga content" — the latter
    # writes a detail string starting with "STALE" (signalforge.data.entitlements
    # ._benzinga_news_check). Surface that as its own state: the API key IS
    # subscribed, the provider just isn't delivering current Benzinga articles.
    benz_stale = bool(benz and not benz.available and (benz.detail or "").startswith("STALE"))
    if benz is None:
        benz_limitation = "not yet verified — run `signalforge providers verify`"
    elif benz.available:
        benz_limitation = ""
    else:
        _http = f"HTTP {benz.http_status} " if benz.http_status else ""
        # the verifier's detail already carries the precise reason (stale feed,
        # not_authorized, empty sample); surface it verbatim.
        benz_limitation = benz.detail or (
            f"{_http}{benz.error_category} on {benz.endpoint} — Benzinga not entitled on this key"
        )

    all_items = _news_items(session, symbol, limit)

    # Keep Benzinga-labelled articles visually and structurally separate from
    # every other licensed publisher — never blend a stale, un-refreshed feed
    # into "current" generic news. Primary signal is the DB-level `provider`
    # tag set by BenzingaNewsAdapter (massive_benzinga_news); the publisher
    # name is kept as a fallback for any row ingested before that adapter
    # existed.
    def _is_benzinga(n: dict[str, Any]) -> bool:
        return (
            n["provider"] == "massive_benzinga_news"
            or (n["publisher"] or "").strip().lower() == "benzinga"
        )

    benzinga_items = [n for n in all_items if _is_benzinga(n)]
    generic_items = [n for n in all_items if not _is_benzinga(n)]

    if benz_ok:
        source_label = "Benzinga News (licensed primary) + other licensed publishers"
    elif benz_stale:
        source_label = "Licensed multi-publisher feed (Benzinga content is STALE on this key)"
    else:
        source_label = "Licensed multi-publisher feed (Benzinga not currently entitled on this key)"

    return {
        "news_items": all_items,
        "benzinga_items": benzinga_items,
        "generic_items": generic_items,
        "news_symbol": symbol,
        "benzinga_available": benz_ok,
        "benzinga_stale": benz_stale,
        "benzinga_limitation": benz_limitation,
        "benzinga_note": (benz.detail if benz else ""),  # verifier's verbatim finding, either state
        "benzinga_checked_at": benz.checked_at.isoformat() if benz else None,
        "news_source_label": source_label,
    }


def journal_context(session: Session) -> dict[str, Any]:
    entries = list(
        session.scalars(select(JournalEntry).order_by(JournalEntry.created_at.desc()).limit(50))
    )
    trades = list(
        session.scalars(select(PaperTrade).order_by(PaperTrade.created_at.desc()).limit(50))
    )
    return {
        "entries": entries,
        "trades": trades,
        "weekly": weekly_review(session, week_start=date.today() - timedelta(days=7)),
    }


def strategies_context(session: Session) -> dict[str, Any]:
    from signalforge.research.health_monitor import latest_health_by_strategy

    health = latest_health_by_strategy(session)
    hm_cfg = effective_research_config(session).health_monitor
    out: list[dict[str, Any]] = []
    for strat in default_strategies():
        spec = strat.spec()
        db_strat = session.scalar(select(Strategy).where(Strategy.name == spec.name))
        metric = latest_oos_metric(session, spec)
        h = health.get(spec.name)
        sens = get_setting(session, f"sensitivity:{spec.name}", None)
        out.append(
            {
                "name": spec.name,
                "version": spec.version,
                "horizon": spec.horizon.value,
                "status": (db_strat.status.value if db_strat else spec.status.value),
                "permits_long": spec.permits_long,
                "permits_short": spec.permits_short,
                "rule_definition": spec.rule_definition,
                "known_failure_modes": list(spec.known_failure_modes),
                "report_ref": spec.walkforward_result_ref,
                "oos": metric.metrics_json if metric else None,
                "health": (
                    {
                        "window": h.window_label,
                        "paper_expectancy_r": round(h.paper_expectancy, 3),
                        "backtest_expectancy_r": round(h.backtest_expectancy, 3),
                        "z_score": round(h.z_score, 2),
                        "action": h.action,
                        "note": h.note,
                        "evaluated_at": h.evaluated_at.isoformat(),
                    }
                    if h
                    else None
                ),
                "sensitivity": (
                    {
                        "fragile": sens.get("fragile"),
                        "n_evaluable": sens.get("n_evaluable"),
                        "n_positive": sens.get("n_positive"),
                        "positive_fraction": sens.get("positive_fraction"),
                        "reasons": sens.get("reasons", []),
                    }
                    if isinstance(sens, dict)
                    else None
                ),
            }
        )
    return {
        "strategies": out,
        "health_rules": {
            "enabled": hm_cfg.enabled,
            "min_paper_trades": hm_cfg.min_paper_trades,
            "downgrade_z": hm_cfg.downgrade_z,
            "disable_z": hm_cfg.disable_z,
        },
    }


def strategy_promotion_context(session: Session) -> dict[str, Any]:
    """Every gate, its evidence, the verdict, and the exact data/version used —
    for the latest promotion-pipeline evaluation of every default strategy.
    Read-only: this page can *trigger* an evaluation (a POST action) but never
    sets status itself — only ``research.promotion`` does that."""
    from signalforge.db.models import StrategyVersion
    from signalforge.research.promotion import VERDICT_NO_TRADE, latest_evaluations

    latest = latest_evaluations(session)
    rows: list[dict[str, Any]] = []
    any_approved = False
    for strat in default_strategies():
        spec = strat.spec()
        db_strat = session.scalar(select(Strategy).where(Strategy.name == spec.name))
        current_status = db_strat.status.value if db_strat else spec.status.value
        any_approved = any_approved or current_status == "paper_approved"

        ver = session.scalar(
            select(StrategyVersion).where(
                StrategyVersion.strategy_id == (db_strat.id if db_strat else -1),
                StrategyVersion.version == spec.version,
            )
        )
        ev = latest.get(ver.id) if ver else None
        rows.append(
            {
                "key": spec.name,
                "version": spec.version,
                "horizon": spec.horizon.value,
                "current_status": current_status,
                "has_evaluation": ev is not None,
                "evaluated_at": ev.evaluated_at.isoformat() if ev else None,
                "config_hash": ev.config_hash if ev else None,
                "git_sha": ev.git_sha if ev else None,
                "universe": ev.universe_json if ev else [],
                "window": (
                    f"{ev.window_start.isoformat()}..{ev.window_end.isoformat()}" if ev else None
                ),
                "data_provenance": ev.data_provenance_json if ev else {},
                "passed": ev.passed if ev else None,
                "verdict": ev.verdict if ev else VERDICT_NO_TRADE,
                "gates": ev.gates_json if ev else [],
                "n_gates_passed": sum(1 for g in (ev.gates_json if ev else []) if g["passed"]),
            }
        )
    return {
        "strategies": rows,
        "any_approved": any_approved,
        "operational_result": (
            "at least one strategy is PAPER_APPROVED" if any_approved else VERDICT_NO_TRADE
        ),
    }


def paper_probation_context(session: Session) -> dict[str, Any]:
    """Every PAPER_APPROVED strategy's approved scope, sealed/walk-forward
    evidence, and real live-paper performance vs. what the promotion
    pipeline expected — plus whether candidate-trade alerts are currently
    enabled for the probation."""
    from signalforge.research.paper_probation import paper_probation_context as _ctx

    ctx = _ctx(session)
    ctx["paper_probation_enabled"] = bool(get_setting(session, "paper_probation_enabled", False))
    ctx["alerts_enabled"] = bool(get_setting(session, "alerts_enabled", False))
    return ctx


def ops_status_context(session: Session) -> dict[str, Any]:
    """Operational Status: is the always-on runtime healthy and are the safety
    switches where the operator expects them? Read-only. Never exposes a key
    or the Discord webhook URL — only "configured / not configured"."""
    from signalforge.alerts.channels.discord import DiscordChannel
    from signalforge.db.health import check_db
    from signalforge.db.models import (
        AuditLog,
        DataSnapshot,
        EntitlementCheck,
        IngestionRun,
        JobRun,
    )
    from signalforge.gitinfo import git_branch, git_sha
    from signalforge.research.approval_scope import approved_scopes
    from signalforge.research.approved_scope_scan import AUDIT_BLOCKED, AUDIT_COMPLETED
    from signalforge.scheduler import MANUAL_JOBS, default_job_specs

    now = datetime.now(UTC)

    # --- version + database -------------------------------------------------
    db = check_db()
    version = {"branch": git_branch(), "sha": git_sha()}

    # --- feeds ----------------------------------------------------------------
    feeds = feed_status_report(session)
    any_stale = any(f["is_stale"] for f in feeds["feeds"]) or not feeds["feeds"]

    # --- Benzinga -------------------------------------------------------------
    benz = session.scalar(
        select(EntitlementCheck)
        .where(EntitlementCheck.feed == "benzinga_news")
        .order_by(EntitlementCheck.checked_at.desc())
        .limit(1)
    )
    benzinga = {
        "checked": benz is not None,
        "available": bool(benz and benz.available),
        "stale": bool(benz and not benz.available and (benz.detail or "").startswith("STALE")),
        "endpoint": benz.endpoint if benz else None,
        "detail": benz.detail if benz else "not yet verified — run `signalforge providers verify`",
        "checked_at": benz.checked_at.isoformat() if benz else None,
    }

    # --- switches -------------------------------------------------------------
    discord_configured = DiscordChannel.from_settings() is not None
    switches = {
        "alerts_enabled": bool(get_setting(session, "alerts_enabled", False)),
        "paper_probation_enabled": bool(get_setting(session, "paper_probation_enabled", False)),
        "auto_simulate": bool(get_setting(session, "auto_simulate_qualified_signals", False)),
        "max_alerts_per_day": get_setting(session, "max_alerts_per_day", 2),
        "quiet_hours": get_setting(session, "quiet_hours", {"start": 21, "end": 7}),
        "discord_configured": discord_configured,
    }
    ks = get_kill_switch().state()

    # --- approved strategies + exact scope -----------------------------------
    approved: list[dict[str, Any]] = []
    for strat, ver in session.execute(
        select(Strategy, StrategyVersion)
        .join(StrategyVersion, StrategyVersion.strategy_id == Strategy.id)
        .where(
            Strategy.status == StrategyStatus.PAPER_APPROVED,
            StrategyVersion.status == StrategyStatus.PAPER_APPROVED,
        )
    ).all():
        scopes = []
        seen_scopes: set[tuple[int | None, str, str, tuple[str, ...]]] = set()
        for sc in approved_scopes(session, ver.id):
            key = (
                sc.dataset_snapshot_id,
                sc.config_hash,
                sc.spec_json_hash,
                tuple(sorted(sc.sources)),
            )
            if key in seen_scopes:
                continue  # repeated identical passing evaluations -> one scope line
            seen_scopes.add(key)
            snap = session.get(DataSnapshot, sc.dataset_snapshot_id)
            scopes.append(
                {
                    "dataset_snapshot_id": sc.dataset_snapshot_id,
                    "dataset_key": snap.key if snap else None,
                    "universe_size": len(sc.universe),
                    "sources": sorted(sc.sources),
                    "config_hash": sc.config_hash,
                    "spec_json_hash": sc.spec_json_hash,
                }
            )
        approved.append(
            {
                "strategy_key": strat.name,
                "version": ver.version,
                "horizon": strat.horizon.value,
                "scopes": scopes,
            }
        )

    # --- last job outcomes ----------------------------------------------------
    job_names = (
        [s.name for s in default_job_specs()]
        + list(MANUAL_JOBS)
        + [
            "catchup_ingest",
            "catchup_scan",
            "catchup_approved_scope_scan",
        ]
    )
    jobs: list[dict[str, Any]] = []
    for name in job_names:
        last = session.scalar(
            select(JobRun).where(JobRun.name == name).order_by(JobRun.started_at.desc()).limit(1)
        )
        jobs.append(
            {
                "name": name,
                "status": last.status if last else "never",
                "started_at": last.started_at.isoformat() if last else None,
                "finished_at": (
                    last.finished_at.isoformat() if last and last.finished_at else None
                ),
                "age_hours": (
                    round((now - last.started_at).total_seconds() / 3600, 1) if last else None
                ),
                "detail": last.detail if last else "",
            }
        )

    # daily-bar ingestion specifically (options backfills / news are separate)
    last_ingest = session.scalar(
        select(IngestionRun)
        .where(IngestionRun.feed_type == FeedType.BAR_DAILY)
        .order_by(IngestionRun.started_at.desc())
        .limit(1)
    )
    ingest = (
        {
            "status": last_ingest.status,
            "kind": last_ingest.kind,
            "provider": last_ingest.provider,
            "finished_at": (
                last_ingest.finished_at.isoformat() if last_ingest.finished_at else None
            ),
            "bars_written": last_ingest.bars_written,
            "symbols_ok": len(last_ingest.symbols_ok or []),
            "symbols_failed": len(last_ingest.symbols_failed or {}),
        }
        if last_ingest
        else None
    )

    scans: list[dict[str, Any]] = []
    for h in effective_research_config(session).enabled_horizons:
        run = _latest_scan(session, h)
        if run is None:
            scans.append({"horizon": h.value, "has_run": False})
            continue
        scans.append(
            {
                "horizon": h.value,
                "has_run": True,
                "started_at": run.started_at.isoformat(),
                "scanned": run.scanned_count,
                "no_trade": run.no_trade_count,
                "qualified": run.candidate_count,
                "dataset_snapshot_id": run.dataset_snapshot_id,
                "source": run.source,
            }
        )

    last_approved = session.scalar(
        select(AuditLog)
        .where(AuditLog.action.in_((AUDIT_COMPLETED, AUDIT_BLOCKED)))
        .order_by(AuditLog.ts.desc())
        .limit(1)
    )
    approved_scan = (
        {
            "outcome": "completed" if last_approved.action == AUDIT_COMPLETED else "blocked",
            "at": last_approved.ts.isoformat(),
            "payload": last_approved.after_json or {},
        }
        if last_approved
        else None
    )

    briefing = get_setting(session, "last_briefing", None)
    briefing_as_of = briefing.get("as_of") if isinstance(briefing, dict) else None

    # --- readiness checklist --------------------------------------------------
    checks = [
        ("Database at migration head", bool(db["at_head"]), db.get("current_revision") or "?"),
        ("All data feeds fresh", not any_stale, "stale or unregistered" if any_stale else "ok"),
        ("Benzinga feed current", benzinga["available"], benzinga["detail"] or ""),
        ("Kill switch released", not ks.active, ks.reason),
        (
            "Last ingestion ok",
            bool(ingest and ingest["status"] == "ok"),
            ingest["status"] if ingest else "never",
        ),
        (
            "Approved strategy with exact scope",
            bool(approved and all(a["scopes"] for a in approved)),
            f"{len(approved)} approved",
        ),
        (
            "Discord configured (URL never shown)",
            discord_configured,
            "set" if discord_configured else "not set",
        ),
        (
            "Alerts OFF (expected during preparation)",
            not switches["alerts_enabled"],
            "alerts_enabled",
        ),
        (
            "Paper probation OFF (expected during preparation)",
            not switches["paper_probation_enabled"],
            "paper_probation_enabled",
        ),
        ("Auto-simulation OFF", not switches["auto_simulate"], "auto_simulate_qualified_signals"),
    ]

    return {
        "generated_at": now.isoformat(),
        "version": version,
        "db": db,
        "feeds": feeds["feeds"],
        "any_stale": any_stale,
        "benzinga": benzinga,
        "switches": switches,
        "kill_switch": ks,
        "approved": approved,
        "jobs": jobs,
        "ingest": ingest,
        "scans": scans,
        "approved_scan": approved_scan,
        "briefing_as_of": briefing_as_of,
        "checks": [{"label": lbl, "ok": ok, "note": note} for lbl, ok, note in checks],
    }


def settings_context(session: Session) -> dict[str, Any]:
    from signalforge.config import get_settings

    s = get_settings()
    cfg = effective_research_config(session)

    def _isset(name: str) -> bool:
        return bool(getattr(s, name).get_secret_value())

    return {
        "research": cfg.model_dump(mode="json"),
        "config_hash": cfg.config_hash,
        "keys": {
            "MARKET_DATA_API_KEY": _isset("market_data_api_key"),
            "NEWS_API_KEY": _isset("news_api_key"),
            "LLM_API_KEY": _isset("llm_api_key"),
            "NOTIFICATION_API_KEY": _isset("notification_api_key"),
            "APP_ENCRYPTION_KEY": _isset("app_encryption_key"),
        },
        "market_data_provider": s.market_data_provider,
        "llm_enabled": s.llm_enabled,
        "auto_simulate": bool(get_setting(session, "auto_simulate_qualified_signals", False)),
        "alerts_enabled": bool(get_setting(session, "alerts_enabled", False)),
        "quiet_hours": get_setting(session, "quiet_hours", {"start": 21, "end": 7}),
        "max_alerts_per_day": get_setting(session, "max_alerts_per_day", 2),
        "kill_switch": get_kill_switch().state(),
    }
