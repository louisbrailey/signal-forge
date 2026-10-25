"""Read-model assembly for the server-rendered dashboard pages.

Pure query + shaping. No writes. Every value the templates show carries its
source, timestamp, and latency category where relevant (invariant S7); a stale
feed drives the "live alerts disabled" banner (invariant S8).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge.data.feeds import feed_status_report
from signalforge.data.market_context import read_context
from signalforge.data.series import PriceSeries
from signalforge.db.models import (
    Candidate,
    EarningsEvent,
    EntitlementCheck,
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
    from signalforge.research.candidates import not_universe_scan

    return session.scalar(
        select(ScanRun)
        .where(ScanRun.horizon == horizon, not_universe_scan(session))
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
    latest_check = session.scalar(
        select(EntitlementCheck).order_by(EntitlementCheck.checked_at.desc()).limit(1)
    )
    subscription_checks = (
        list(
            session.scalars(
                select(EntitlementCheck).where(EntitlementCheck.batch_id == latest_check.batch_id)
            )
        )
        if latest_check
        else []
    )
    return {
        "subscription_checks": subscription_checks,
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
        "cross_asset_context": read_context(session),
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
    enabled for the probation.

    It also carries ``options_paper`` (D3 §7.3): the SIMULATED options book's
    account, open structures, reconciliation age and last EOD-chain run. That
    block is built by ``research.paper_probation.options_paper_status``, which is
    the only hook this layer may use — it reads ORM models and nothing else.
    Contract S16 forbids ``signalforge.app`` from importing
    ``paper.options_ledger`` / ``options_marks`` / ``options_auto_simulate`` by
    any number of hops, so ``paper.options_marks.options_portfolio_snapshot`` —
    the richer reader the ``options-paper status`` CLI uses — is deliberately NOT
    reachable from here. The panel is therefore minimal by design, not by
    omission."""
    from signalforge.research.paper_probation import paper_probation_context as _ctx

    ctx = _ctx(session)
    ctx["paper_probation_enabled"] = bool(get_setting(session, "paper_probation_enabled", False))
    ctx["alerts_enabled"] = bool(get_setting(session, "alerts_enabled", False))
    return ctx


def _get_settings_provider() -> str:
    from signalforge.config import get_settings

    return get_settings().market_data_provider or "fixture"


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
        "alert_types": _alert_type_states(session),
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
            # multi-session catch-up (2026-10-04): the newest per-session rows,
            # so a session that was ingested but explicitly NOT scanned is
            # visible here rather than only in the database
            "catch_up_missed_sessions",
            "catchup_ingest_session",
            "scan_skipped_missed_session",
        ]
    )
    jobs: list[dict[str, Any]] = []
    for name in dict.fromkeys(job_names):
        last = session.scalar(
            select(JobRun).where(JobRun.name == name).order_by(JobRun.started_at.desc()).limit(1)
        )
        last_ok = session.scalar(
            select(JobRun)
            .where(JobRun.name == name, JobRun.status == "ok")
            .order_by(JobRun.started_at.desc())
            .limit(1)
        )

        def _dur(r: JobRun | None) -> float | None:
            if r is None or r.finished_at is None:
                return None
            return round((r.finished_at - r.started_at).total_seconds(), 1)

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
                "duration_s": _dur(last),
                "last_success_at": last_ok.started_at.isoformat() if last_ok else None,
                "last_success_duration_s": _dur(last_ok),
                # ``running`` / ``interrupted`` are a trace of an attempt, not an
                # outcome (incident 2026-10-05): shown, never counted as success.
                "failure_reason": (
                    last.detail
                    if last and last.status in ("failed", "skipped", "interrupted")
                    else ""
                ),
                "detail": last.detail if last else "",
                "next_run": None,  # filled from the worker heartbeat below
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

    # --- worker liveness + next scheduled run (from the worker's own heartbeat) ---
    from signalforge.db.models import OHLCVDaily, WorkerHeartbeat
    from signalforge.scheduler import (
        EOD_CRON,
        WORKER_STALE_AFTER_S,
        catch_up_pending,
        eod_gap,
        last_completed_session,
    )

    hb = session.scalar(select(WorkerHeartbeat).where(WorkerHeartbeat.worker == "scheduler"))
    hb_age = (now - hb.last_beat_at).total_seconds() if hb else None
    worker = {
        "seen": hb is not None,
        "running": hb is not None and hb_age is not None and hb_age <= WORKER_STALE_AFTER_S,
        "host": hb.host if hb else None,
        "pid": hb.pid if hb else None,
        "started_at": hb.started_at.isoformat() if hb else None,
        "last_beat_at": hb.last_beat_at.isoformat() if hb else None,
        "beat_age_s": round(hb_age) if hb_age is not None else None,
        "detail": hb.detail if hb else "",
    }
    next_runs: dict[str, str | None] = dict(hb.next_runs_json) if hb else {}
    for j in jobs:
        j["next_run"] = next_runs.get(j["name"])
    # what the cron table intends for the EOD job even when no worker is alive
    from zoneinfo import ZoneInfo

    et_now = now.astimezone(ZoneInfo("America/New_York"))
    intended = et_now.replace(hour=EOD_CRON[0], minute=EOD_CRON[1], second=0, microsecond=0)
    if intended <= et_now:
        intended += timedelta(days=1)
    while intended.weekday() >= 5:
        intended += timedelta(days=1)
    next_scheduled = {
        "eod_update_from_worker": next_runs.get("daily_eod_update"),
        "eod_update_intended_et": intended.isoformat(),
        "will_fire": worker["running"],
    }

    # --- the distinct approved universes (one per approved strategy version's
    # own dataset snapshot + source) — every data gate below is evaluated
    # PER UNIVERSE, so a stale 150-symbol universe never masks, or is masked
    # by, a fresh 24-symbol one.
    from signalforge.research.approved_scope_scan import (
        approved_horizons,
        approved_universes,
        universe_readiness,
    )

    universes_error: str | None = None
    try:
        universes, skipped_versions = approved_universes(session)
    except Exception as exc:  # never let the status page itself fail
        universes, skipped_versions, universes_error = [], [], str(exc)

    # --- daily-bar freshness vs the expected (last completed) session ---
    expected_session = last_completed_session(now)
    research_source = _get_settings_provider()
    research_symbols = list(effective_research_config(session).universe)

    def _sessions_behind(bar: date | None) -> int:
        n = 0
        if bar is not None:
            d = bar
            while d < expected_session:
                d += timedelta(days=1)
                if d.weekday() < 5:
                    n += 1
        return n

    def _newest_bar(symbols: list[str], src: str) -> date | None:
        return session.scalar(
            select(func.max(OHLCVDaily.session_date))
            .join(Instrument, Instrument.id == OHLCVDaily.instrument_id)
            .where(OHLCVDaily.source == src, Instrument.symbol.in_(symbols))
        )

    per_universe: list[dict[str, Any]] = []
    for u in universes:
        u_newest = _newest_bar(list(u.symbols), u.source)
        per_universe.append(
            {
                "dataset_snapshot_id": u.dataset_snapshot_id,
                "dataset_key": u.dataset_key,
                "source": u.source,
                "n_symbols": len(u.symbols),
                "newest_bar": u_newest.isoformat() if u_newest else None,
                "sessions_behind": _sessions_behind(u_newest) if u_newest else None,
                "current": u_newest is not None and u_newest >= expected_session,
            }
        )
    newest_bar = _newest_bar(research_symbols, research_source)
    freshness: dict[str, Any] = {
        "expected_session": expected_session.isoformat(),
        "newest_bar": newest_bar.isoformat() if newest_bar else None,
        "sessions_behind": _sessions_behind(newest_bar) if newest_bar else None,
        "current": newest_bar is not None and newest_bar >= expected_session,
        "source": research_source,
        "note": "exchange holidays are not modelled: a holiday shows as 1 session behind",
        # One entry per distinct approved universe — the configured research
        # universe above is NOT necessarily any approved strategy's universe.
        "per_universe": per_universe,
    }
    pending, pending_reason = catch_up_pending(now)
    catch_up = {"pending": pending, "reason": pending_reason}
    # A silent multi-day gap (2026-09-28..30): the last completed session is past
    # its expected EOD time + grace with no successful EOD job run on record.
    try:
        gap, gap_reason = eod_gap(now)
    except Exception as exc:  # never let the status page itself fail
        gap, gap_reason = True, f"EOD gap check failed: {exc}"
    eod_gap_ctx = {"gap": gap, "reason": gap_reason}

    # --- approved-scope scan readiness (the same gate the scheduled job uses) ---
    # /ops must never look "ready" while the daily data-freshness gate would
    # block the approved-scope scan: evaluate it live, per approved universe,
    # and show the exact reason plus the last SUCCESSFUL daily-bar ingest time.
    last_ok_ingest = session.scalar(
        select(IngestionRun)
        .where(IngestionRun.feed_type == FeedType.BAR_DAILY, IngestionRun.status == "ok")
        .order_by(IngestionRun.finished_at.desc())
        .limit(1)
    )
    readiness: dict[str, Any] = {
        "ready": False,
        "reason": "no PAPER_APPROVED strategy — nothing to scan",
        "last_ok_ingest_at": (
            (last_ok_ingest.finished_at or last_ok_ingest.started_at).isoformat()
            if last_ok_ingest
            else None
        ),
        "dataset_key": None,
        "n_symbols": 0,
        "universes": [],
        "skipped_versions": skipped_versions,
    }
    if universes_error is not None:
        readiness.update(ready=False, reason=f"readiness check failed: {universes_error}")
    elif not universes:
        if approved_horizons(session):
            readiness["reason"] = (
                "PAPER_APPROVED strategies exist but none has a usable approved scope — "
                "nothing can be scanned in scope"
            )
    else:
        try:
            rows = universe_readiness(session, universes, now=now)
            readiness.update(
                universes=rows,
                ready=all(r["ready"] for r in rows),
                reason=(
                    rows[0]["reason"]
                    if len(rows) == 1
                    else "; ".join(
                        f"snapshot {r['dataset_snapshot_id']} ({r['dataset_key']}): {r['reason']}"
                        for r in rows
                    )
                ),
                dataset_key=rows[0]["dataset_key"] if len(rows) == 1 else None,
                n_symbols=(
                    rows[0]["n_symbols"]
                    if len(rows) == 1
                    else len({s.upper() for u in universes for s in u.symbols})
                ),
            )
        except Exception as exc:  # never let the status page itself fail
            readiness.update(ready=False, reason=f"readiness check failed: {exc}")

    # --- readiness checklist --------------------------------------------------
    # The two data gates are listed ONCE PER APPROVED UNIVERSE: with two
    # approved snapshots a single collapsed verdict would either hide a
    # blocked universe or condemn a healthy one.
    def _universe_label(row: dict[str, Any]) -> str:
        return (
            f"snapshot {row['dataset_snapshot_id']} {row['dataset_key']} "
            f"({row['n_symbols']} symbols, {row['source']})"
        )

    readiness_checks: list[tuple[str, bool, str]] = [
        (
            f"Approved-scope scan data readiness — {_universe_label(r)}",
            bool(r["ready"]),
            f"{r['reason']} (last ok daily-bar ingest: "
            f"{readiness['last_ok_ingest_at'] or 'never'})",
        )
        for r in readiness["universes"]
    ] or [
        (
            "Approved-scope scan data readiness",
            bool(readiness["ready"]),
            f"{readiness['reason']} (last ok daily-bar ingest: "
            f"{readiness['last_ok_ingest_at'] or 'never'})",
        )
    ]
    bars_checks: list[tuple[str, bool, str]] = [
        (
            f"Daily bars current for last completed session — {_universe_label(r)}",
            bool(r["current"]),
            f"newest {r['newest_bar'] or 'none'} vs expected {freshness['expected_session']}"
            + (f" ({r['sessions_behind']} behind)" if r["sessions_behind"] else ""),
        )
        for r in per_universe
    ] or [
        (
            "Daily bars current for last completed session",
            bool(freshness["current"]),
            f"newest {freshness['newest_bar'] or 'none'} vs expected "
            f"{freshness['expected_session']}"
            + (f" ({freshness['sessions_behind']} behind)" if freshness["sessions_behind"] else ""),
        )
    ]
    checks = [
        *readiness_checks,
        (
            "Worker running (heartbeat)",
            bool(worker["running"]),
            (
                f"last beat {worker['beat_age_s']}s ago on {worker['host']} pid {worker['pid']}"
                if worker["seen"]
                else "no heartbeat ever recorded — run-scheduler has not been started"
            ),
        ),
        *bars_checks,
        ("No catch-up pending", not catch_up["pending"], catch_up["reason"]),
        (
            "EOD update ran for last completed session",
            not eod_gap_ctx["gap"],
            str(eod_gap_ctx["reason"]),
        ),
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
        (
            "Auto-simulation "
            + ("ON (operator-authorized 2026-09-10)" if switches["auto_simulate"] else "OFF"),
            True,
            "auto_simulate_qualified_signals",
        ),
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
        "readiness": readiness,
        "worker": worker,
        "next_scheduled": next_scheduled,
        "freshness": freshness,
        "catch_up": catch_up,
        "eod_gap": eod_gap_ctx,
        "checks": [{"label": lbl, "ok": ok, "note": note} for lbl, ok, note in checks],
        "overall_ready": all(ok for _lbl, ok, _n in checks),
    }


def universe_context(session: Session) -> dict[str, Any]:
    """Liquid-universe coverage dashboard: stage counts, exclusions, storage."""
    from signalforge.universe.pipeline import universe_status

    return {"u": universe_status(session)}


def agents_context(session: Session) -> dict[str, Any]:
    """Latest report per bounded research agent (read-only)."""
    from signalforge.agents import all_agents
    from signalforge.db.models import AgentReport

    rows: list[dict[str, Any]] = []
    for a in all_agents():
        row = session.scalar(
            select(AgentReport)
            .where(AgentReport.agent == a.name)
            .order_by(AgentReport.created_at.desc())
            .limit(1)
        )
        rows.append(
            {
                "name": a.name,
                "role": a.role,
                "allowed_inputs": list(a.allowed_inputs),
                "outputs": list(a.outputs),
                "prohibited": list(a.prohibited),
                "may_write": a.may_write,
                "llm_narrative": a.llm_narrative,
                "report": (
                    {
                        "id": row.id,
                        "status": row.status,
                        "created_at": row.created_at.isoformat(),
                        "as_of": row.as_of.isoformat(),
                        "summary": row.summary,
                        "narrative": row.narrative,
                        "missing_data": row.missing_data_json,
                        "citations": row.citations_json,
                        "duration_s": row.duration_s,
                        "error": row.error,
                    }
                    if row
                    else None
                ),
            }
        )
    return {"agents": rows, "generated_at": datetime.now(UTC).isoformat()}


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
        "alert_types": _alert_type_states(session),
        "quiet_hours": get_setting(session, "quiet_hours", {"start": 21, "end": 7}),
        "max_alerts_per_day": get_setting(session, "max_alerts_per_day", 2),
        "kill_switch": get_kill_switch().state(),
    }


def _alert_type_states(session: Session) -> dict[str, bool]:
    from signalforge.alerts.dispatch import alert_type_states

    return alert_type_states(session)


def _last_close_for(session: Session, symbol: str, on: date) -> float | None:
    from signalforge.data.repository import get_daily_bars

    bars = get_daily_bars(session, symbol, on - timedelta(days=15), on)
    return float(bars[-1].close) if bars else None


def grid_context(session: Session, *, trade_limit: int = 50) -> dict[str, Any]:
    """Read-model for /grid — the mechanical grid's live (paper) state.

    Read-only. The grid is NOT a promotion-gated strategy: it produces no
    candidate, no alert, and never touches the research paper account.
    """
    from signalforge.db.models import GridPosition, GridTradeRow, PaperAccount
    from signalforge.grid.live import params_from_config

    cfg = effective_research_config(session).grid
    params = params_from_config(cfg)
    acct = session.scalar(select(PaperAccount).where(PaperAccount.name == cfg.account_name))
    ctx: dict[str, Any] = {
        "enabled": cfg.enabled,
        "account_name": cfg.account_name,
        "exists": acct is not None,
        "params": params.to_dict(),
        "costs_label": params.costs_label,
        "budget_if_every_symbol_capped": params.max_committed_usd,
        "budget_is_consistent": params.budget_is_consistent,
        "source": cfg.source,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "positions": [],
        "trades": [],
        "cash": 0.0,
        "initial_cash": 0.0,
        "market_value": 0.0,
        "equity": 0.0,
        "total_return_pct": 0.0,
        "unrealized_pnl": 0.0,
        "cost_basis": 0.0,
        "n_positions": 0,
        "n_tracked": 0,
        "n_trades": 0,
        "symbols_at_cap": 0,
        "last_session": None,
    }
    if acct is None:
        return ctx

    rows = list(session.scalars(select(GridPosition).where(GridPosition.account_id == acct.id)))
    on = date.today()
    market_value = 0.0
    cost_basis = 0.0
    positions: list[dict[str, Any]] = []
    for row in rows:
        qty = float(row.qty)
        basis = float(row.cost_basis)
        cost_basis += basis
        if qty <= 0:
            continue
        last = _last_close_for(session, row.symbol, on)
        mv = qty * last if last is not None else basis
        market_value += mv
        positions.append(
            {
                "symbol": row.symbol,
                "qty": qty,
                "cost_basis": basis,
                "anchor_price": float(row.anchor_price),
                "last_close": last,
                "market_value": mv,
                "unrealized_pnl": mv - basis,
                "at_cap": basis + float(cfg.buy_usd) > float(cfg.per_symbol_cap),
            }
        )
    positions.sort(key=lambda p: float(p["market_value"]), reverse=True)

    trades = list(
        session.scalars(
            select(GridTradeRow)
            .where(GridTradeRow.account_id == acct.id)
            .order_by(GridTradeRow.session_date.desc(), GridTradeRow.id.desc())
            .limit(trade_limit)
        )
    )
    n_trades = int(
        session.scalar(
            select(func.count(GridTradeRow.id)).where(GridTradeRow.account_id == acct.id)
        )
        or 0
    )
    cash = float(acct.cash)
    equity = cash + market_value
    initial = float(acct.initial_cash)
    ctx.update(
        {
            "cash": cash,
            "initial_cash": initial,
            "market_value": market_value,
            "cost_basis": cost_basis,
            "equity": equity,
            "total_return_pct": ((equity / initial - 1.0) * 100.0) if initial > 0 else 0.0,
            "unrealized_pnl": market_value - cost_basis,
            "n_positions": len(positions),
            "n_tracked": len(rows),
            "n_trades": n_trades,
            "symbols_at_cap": sum(1 for p in positions if p["at_cap"]),
            "last_session": trades[0].session_date.isoformat() if trades else None,
            "positions": positions,
            "trades": [
                {
                    "symbol": t.symbol,
                    "side": t.side,
                    "qty": float(t.qty),
                    "price": float(t.price),
                    "usd": float(t.usd),
                    "anchor_before": float(t.anchor_before),
                    "anchor_after": float(t.anchor_after),
                    "session_date": t.session_date.isoformat(),
                    "created_at": t.created_at.isoformat(timespec="seconds"),
                }
                for t in trades
            ],
        }
    )
    return ctx
