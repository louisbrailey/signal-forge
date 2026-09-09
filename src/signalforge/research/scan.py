"""Universe scan: filters -> strategy evaluation -> quality gates -> candidates.

Every scan records three separate populations (ARCHITECTURE.md §7.1):
* **scanned**   — instruments actually evaluated
* **excluded**  — with a reason breakdown (liquidity / data / event / strategy / risk)
* **no-trade**  — passed the filters but no strategy triggered, or a triggered
  candidate failed a quality gate. NO TRADE is a first-class, recorded outcome.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.backtest.engine import EntrySignal
from signalforge.config import Settings, get_settings
from signalforge.config.research import EventFilters, ResearchConfig
from signalforge.data.adapters.base import FeedType
from signalforge.data.freshness import gate_for_horizon
from signalforge.data.series import PriceSeries
from signalforge.db.models import EarningsEvent, Instrument
from signalforge.db.session import set_write_intent
from signalforge.db.types import utcnow
from signalforge.domain import Direction, Horizon, QualityGate
from signalforge.research.features.daily import atr, sma
from signalforge.research.persistence import latest_oos_metric, upsert_strategy_version
from signalforge.research.regime import RegimeState, regime_from_proxy
from signalforge.research.registry import StrategySpec
from signalforge.research.strategies import default_strategies
from signalforge.research.strategies.base import BaselineStrategy, StrategyContext
from signalforge.risk.engine import OpenExposure, SizingRequest, size_position

_MIN_HISTORY = 220
_HORIZON_DAYS = {
    Horizon.INTRADAY: 1,
    Horizon.SHORT_SWING: 10,
    Horizon.MEDIUM_SWING: 40,
    Horizon.POSITION: 126,
}


class Exclusion(StrEnum):
    LIQUIDITY = "liquidity"
    MISSING_DATA = "missing_or_short_history"
    STALE_DATA = "stale_or_unavailable_feed"
    EVENT_WINDOW = "earnings_event_window"
    NO_STRATEGY = "no_strategy_for_horizon"


@dataclass(slots=True)
class CandidateDraft:
    symbol: str
    instrument_id: int
    strategy_version_id: int
    spec: StrategySpec
    horizon: Horizon
    direction: Direction
    entry_zone_low: float
    entry_zone_high: float
    invalidation_level: float
    target_level: float | None
    target_logic: str
    time_stop_days: int
    reward_risk_estimate: float
    risk_dollars: float
    risk_pct_of_account: float
    liquidity: dict[str, object]
    event_risk: dict[str, object]
    data_freshness: dict[str, object]
    reasons_qualify: list[str]
    reasons_fail: list[str]
    quality_gate_status: QualityGate
    failed_gates: list[str] = field(default_factory=list)
    ranking: dict[str, object] = field(default_factory=dict)
    score: float = 0.0
    rank_in_horizon: int | None = None
    probability_calibrated: float | None = None
    calibration_ref: str | None = None


@dataclass(slots=True)
class ScanResult:
    horizon: Horizon
    started_at: str
    finished_at: str
    config_hash: str
    universe: list[str]
    source: str = ""
    dataset_snapshot_id: int | None = None
    scanned: list[str] = field(default_factory=list)
    excluded: dict[str, list[str]] = field(default_factory=dict)
    no_trade: list[dict[str, str]] = field(default_factory=list)
    candidates: list[CandidateDraft] = field(default_factory=list)
    regime: dict[str, object] = field(default_factory=dict)
    live_alerts_enabled: bool = True
    notes: list[str] = field(default_factory=list)

    @property
    def excluded_count(self) -> int:
        return sum(len(v) for v in self.excluded.values())

    def _exclude(self, symbol: str, reason: Exclusion) -> None:
        self.excluded.setdefault(reason.value, []).append(symbol)


def _strategies_for(horizon: Horizon) -> list[BaselineStrategy]:
    return [s for s in default_strategies() if s.spec().horizon is horizon]


def _entry_band(close: float, atr_val: float) -> tuple[float, float]:
    half = max(atr_val * 0.25, close * 0.001)
    return round(close - half, 4), round(close + half, 4)


def _earnings_in_window(
    session: Session,
    instrument_id: int,
    as_of: date,
    horizon: Horizon,
    cfg_events: EventFilters,
) -> list[str]:
    lo = as_of - timedelta(days=cfg_events.exclude_days_before_earnings)
    hi = as_of + timedelta(days=_HORIZON_DAYS[horizon] * 2 + cfg_events.exclude_days_after_earnings)
    rows = session.scalars(
        select(EarningsEvent).where(
            EarningsEvent.instrument_id == instrument_id,
            EarningsEvent.scheduled_for >= lo,
            EarningsEvent.scheduled_for <= hi,
        )
    )
    return [r.scheduled_for.isoformat() for r in rows]


def run_scan(
    session: Session,
    horizon: Horizon,
    *,
    settings: Settings | None = None,
    research: ResearchConfig | None = None,
    as_of: date | None = None,
    source: str | None = None,
    proxy_symbol: str = "SPY",
    symbols: list[str] | None = None,
) -> ScanResult:
    settings = settings or get_settings()
    if research is not None:
        cfg = research
    else:
        from signalforge.settings_store import effective_research_config

        cfg = effective_research_config(session)
    universe = list(symbols) if symbols is not None else list(cfg.universe)
    started = utcnow()
    # Record the EXACT scope this scan used -- resolving/reusing a DataSnapshot
    # (the same mechanism research.promotion uses) is what lets a candidate's
    # provenance later be compared against a strategy's approved scope
    # (research.approval_scope), not just its status.
    from signalforge.research.promotion import get_or_create_dataset_snapshot

    resolved_source = source or ""
    snapshot = get_or_create_dataset_snapshot(session, symbols=universe) if universe else None
    result = ScanResult(
        horizon=horizon,
        started_at=started.isoformat(),
        finished_at=started.isoformat(),
        config_hash=cfg.config_hash,
        universe=universe,
        source=resolved_source,
        dataset_snapshot_id=snapshot.id if snapshot is not None else None,
    )

    strategies = _strategies_for(horizon)
    if not strategies:
        for sym in universe:
            result._exclude(sym, Exclusion.NO_STRATEGY)
        result.finished_at = utcnow().isoformat()
        return result

    intraday = horizon is Horizon.INTRADAY
    provider = settings.market_data_provider or "fixture"

    # Feed freshness is scan-wide (our feed status is per provider/feed_type).
    feed_type = FeedType.BAR_INTRADAY if intraday else FeedType.BAR_DAILY
    fresh = gate_for_horizon(session, horizon, [(provider, feed_type)])
    result.live_alerts_enabled = fresh.fresh
    if not fresh.fresh:
        result.notes.append("Live alerts disabled: " + "; ".join(fresh.reasons))

    end = as_of or date.today()
    start = end - timedelta(days=365 * 6)

    # Regime always comes from the daily proxy (it does not flip intraday).
    proxy = PriceSeries.load(session, proxy_symbol, start, end, source=source)
    regime = regime_from_proxy(proxy, len(proxy) - 1) if len(proxy) >= _MIN_HISTORY else None

    intraday_window = (
        datetime.combine(end - timedelta(days=6), datetime.min.time(), tzinfo=UTC),
        datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=UTC),
    )
    min_signal_bars = 30 if intraday else _MIN_HISTORY

    versions = {
        s.spec().versioned_key: upsert_strategy_version(session, s.spec()) for s in strategies
    }
    # End the (tiny) write transaction here AND drop write intent: the long
    # read/compute phase that follows must run as a plain reader (BEGIN, not
    # BEGIN IMMEDIATE) so it never holds the SQLite write lock; persist_scan
    # re-arms write intent for its own short write transaction.
    session.commit()
    set_write_intent(session, False)

    above_ma = 0
    total_priced = 0
    from signalforge.db.models import PaperAccount

    acct = session.scalar(select(PaperAccount).where(PaperAccount.name == "default"))
    equity = float(acct.cash) if acct else 10_000.0

    for sym in universe:
        inst = session.scalar(select(Instrument).where(Instrument.symbol == sym))
        daily = PriceSeries.load(session, sym, start, end, source=source)
        if inst is None or len(daily) < _MIN_HISTORY:
            result._exclude(sym, Exclusion.MISSING_DATA)
            continue
        if not fresh.fresh:
            result._exclude(sym, Exclusion.STALE_DATA)
            continue

        # Signal series: intraday bars for INTRADAY, the daily series otherwise.
        signal_series = (
            PriceSeries.load_intraday(
                session, sym, *intraday_window, bar_size=cfg.intraday_bar_size, source=source
            )
            if intraday
            else daily
        )
        if len(signal_series) < min_signal_bars:
            result._exclude(sym, Exclusion.MISSING_DATA)
            continue

        # Liquidity / breadth always use the daily series.
        d_last = len(daily) - 1
        close = float(signal_series.close[len(signal_series) - 1])
        addv = daily.dollar_volume(20)
        total_priced += 1
        if sma(daily, d_last, 50) == sma(daily, d_last, 50) and float(daily.close[d_last]) > sma(
            daily, d_last, 50
        ):
            above_ma += 1

        if float(daily.close[d_last]) < cfg.liquidity.min_price or addv < (
            cfg.liquidity.min_avg_dollar_volume
        ):
            result._exclude(sym, Exclusion.LIQUIDITY)
            continue

        earnings = _earnings_in_window(session, inst.id, end, horizon, cfg.events)
        if earnings and cfg.events.exclude_days_before_earnings > 0:
            result._exclude(sym, Exclusion.EVENT_WINDOW)
            continue

        result.scanned.append(sym)
        last = len(signal_series) - 1
        atr_val = atr(signal_series, last, 14)
        ctx = StrategyContext(
            regime=regime or _NEUTRAL_STATE(end),
            allow_short=cfg.allow_short_candidates,
        )

        triggered = False
        for strat in strategies:
            spec = strat.spec()
            sig = strat.evaluate(signal_series, last, ctx)
            if sig is None:
                continue
            triggered = True
            draft = _build_draft(
                session=session,
                sym=sym,
                inst=inst,
                version_id=versions[spec.versioned_key].id,
                spec=spec,
                horizon=horizon,
                sig=sig,
                close=close,
                atr_val=atr_val if atr_val == atr_val else close * 0.02,
                addv=addv,
                earnings=earnings,
                fresh=fresh.as_dict(),
                cfg=cfg,
                equity=equity,
                regime_label=f"{ctx.regime.trend.value}/{ctx.regime.vol.value}",
            )
            result.candidates.append(draft)  # both PASSED and NO_TRADE drafts are recorded
            if draft.quality_gate_status is not QualityGate.PASSED:
                result.no_trade.append(
                    {"symbol": sym, "strategy": spec.name, "reason": ", ".join(draft.failed_gates)}
                )

        if not triggered:
            result.no_trade.append(
                {"symbol": sym, "strategy": "-", "reason": "no strategy triggered"}
            )

    result.regime = (regime.to_dict() if regime else {"trend": "unknown"}) | {
        "breadth_pct_above_50dma": (
            round(100.0 * above_ma / total_priced, 1) if total_priced else None
        )
    }
    _rank(result)
    result.finished_at = utcnow().isoformat()
    return result


def _oos_regime_coverage(session: Session, run_id: int, min_trades: int) -> tuple[int, list[str]]:
    """Distinct OOS *trend* regimes (bull / bear / neutral) with >= ``min_trades``
    trades for this run. bull/high + bull/low count as **one** — different
    volatility inside the same trend is not "multiple market regimes"."""
    from signalforge.db.models import BacktestMetric

    rows = session.scalars(
        select(BacktestMetric).where(
            BacktestMetric.run_id == run_id, BacktestMetric.phase == "oos_by_regime"
        )
    )
    by_trend: dict[str, int] = {}
    for r in rows:
        mj = r.metrics_json
        label = str(mj.get("regime_label", r.segment))
        trend = label.split("/", 1)[0] or label
        by_trend[trend] = by_trend.get(trend, 0) + int(float(mj.get("n_trades", 0)))
    covered = sorted(t for t, n in by_trend.items() if n >= min_trades)
    return len(covered), covered


def _NEUTRAL_STATE(as_of: date) -> RegimeState:
    from signalforge.research.regime import Trend, Vol

    return RegimeState(Trend.NEUTRAL, Vol.LOW, as_of)


def _build_draft(
    *,
    session: Session,
    sym: str,
    inst: Instrument,
    version_id: int,
    spec: StrategySpec,
    horizon: Horizon,
    sig: EntrySignal,
    close: float,
    atr_val: float,
    addv: float,
    earnings: list[str],
    fresh: dict[str, object],
    cfg: ResearchConfig,
    equity: float,
    regime_label: str = "unknown",
) -> CandidateDraft:
    lo, hi = _entry_band(close, atr_val)
    entry_ref = (lo + hi) / 2
    rr = (
        abs((sig.target_price or entry_ref) - entry_ref) / abs(entry_ref - sig.stop_price)
        if sig.stop_price != entry_ref
        else 0.0
    )
    reasons_qualify = [sig.reason] if sig.reason else []
    reasons_fail = list(spec.known_failure_modes)
    failed: list[str] = []

    # gate: reward / risk
    if rr < cfg.risk.min_reward_to_risk:
        failed.append(f"reward/risk {rr:.2f} < {cfg.risk.min_reward_to_risk}")

    # gate: out-of-sample evidence
    metric = latest_oos_metric(session, spec)
    q = cfg.quality_gates
    if metric is None:
        if q.require_backtest:
            failed.append("no out-of-sample backtest on record")
    else:
        m = metric.metrics_json
        ci = (metric.ci_json or {}).get("expectancy_r", {})
        if float(m.get("n_trades", 0)) < q.min_oos_trades:
            failed.append(f"OOS trades {m.get('n_trades', 0)} < {q.min_oos_trades}")
        if float(m.get("expectancy_r", -1.0)) <= q.min_oos_expectancy_r:
            failed.append(
                f"OOS expectancy {float(m.get('expectancy_r', 0)):+.3f}R "
                f"<= {q.min_oos_expectancy_r}"
            )
        if ci and float(ci.get("low", -1.0)) < q.min_oos_ci_low_r:
            failed.append(
                f"OOS expectancy CI low {float(ci.get('low', 0)):+.3f}R < {q.min_oos_ci_low_r}"
            )
        n_regimes, regime_labels = _oos_regime_coverage(
            session, metric.run_id, q.min_trades_per_regime
        )
        if n_regimes < q.min_oos_regimes:
            failed.append(
                f"OOS regime coverage: {n_regimes} regime(s) with "
                f">={q.min_trades_per_regime} trades ({', '.join(regime_labels) or 'none'}) "
                f"< {q.min_oos_regimes} required — single-regime edge"
            )

    # gate: risk engine can size the position
    sizing = size_position(
        SizingRequest(
            symbol=sym,
            sector=inst.sector or "unknown",
            entry_price=entry_ref,
            stop_price=sig.stop_price,
            account_equity=equity,
        ),
        cfg.risk,
        OpenExposure(),
    )
    if sizing.rejected:
        failed.append(f"risk: {sizing.rejected_reason}")

    status = QualityGate.PASSED if not failed else QualityGate.NO_TRADE

    # Probability: shown only on a setup that already clears every quality gate
    # AND has a time-separated calibration artifact for this exact strategy
    # version + regime (invariant S10). Otherwise the candidate carries no
    # number and the UI shows the canonical NO-TRADE line.
    prob = None
    if status is QualityGate.PASSED:
        from signalforge.research.probability import calibrated_probability, load_calibration

        prob, _ = calibrated_probability(regime_label, load_calibration(spec.name, spec.version))
    return CandidateDraft(
        symbol=sym,
        instrument_id=inst.id,
        strategy_version_id=version_id,
        spec=spec,
        horizon=horizon,
        direction=sig.direction,
        entry_zone_low=lo,
        entry_zone_high=hi,
        invalidation_level=round(sig.stop_price, 4),
        target_level=round(sig.target_price, 4) if sig.target_price else None,
        target_logic=spec.exit_logic,
        time_stop_days=_HORIZON_DAYS[horizon],
        reward_risk_estimate=round(rr, 3),
        risk_dollars=sizing.risk_dollars,
        risk_pct_of_account=sizing.risk_pct_of_account,
        liquidity={
            "last_price": round(close, 4),
            "avg_dollar_volume_20d": round(addv, 0),
            "spread_bps": None,
            "note": "spread/market-cap not available from the configured feed",
        },
        event_risk={"upcoming_earnings": earnings},
        data_freshness=fresh,
        reasons_qualify=reasons_qualify,
        reasons_fail=reasons_fail,
        quality_gate_status=status,
        failed_gates=failed,
        ranking={},
        probability_calibrated=(prob.p if prob else None),
        calibration_ref=(prob.calibration_ref if prob else None),
    )


_RANK_WEIGHTS = {
    "expectancy_oos": 0.4,
    "reward_risk": 0.3,
    "liquidity_headroom": 0.2,
    "regime_alignment": 0.1,
    "event_penalty": -0.2,
}


def _rank(result: ScanResult) -> None:
    passing = [c for c in result.candidates if c.quality_gate_status is QualityGate.PASSED]
    for c in passing:
        terms = {
            "expectancy_oos": 0.0,  # filled from metric below if desired; kept transparent
            "reward_risk": min(c.reward_risk_estimate / 3.0, 1.0) * _RANK_WEIGHTS["reward_risk"],
            "liquidity_headroom": _RANK_WEIGHTS["liquidity_headroom"],
            "regime_alignment": _RANK_WEIGHTS["regime_alignment"],
            "event_penalty": (
                _RANK_WEIGHTS["event_penalty"] if c.event_risk.get("upcoming_earnings") else 0.0
            ),
        }
        c.score = round(sum(terms.values()), 4)
        c.ranking = {"weights": _RANK_WEIGHTS, "terms": terms, "score": c.score}
    passing.sort(key=lambda c: c.score, reverse=True)
    for i, c in enumerate(passing, start=1):
        c.rank_in_horizon = i
