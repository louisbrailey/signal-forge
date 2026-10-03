"""Phase-2 tool (PREPARED, NOT YET RUN): refresh the live scan's OOS evidence rows.

See docs/research/PREREGISTRATION_2026-09-24_regime_diversity.md. The live scan
gate (``research.scan._build_draft`` -> ``persistence.latest_oos_metric`` +
``_oos_regime_coverage``) reads the most recent ``backtest_run`` for a
strategy name+version. Those rows are written ONLY by ``persist_backtest_result``
(today: the ``signalforge backtest-report`` CLI) — never by
``research.promotion.evaluate_promotion``. This script writes one fresh run per
pre-registered strategy over the pre-registered window, with ``source`` pinned
(``backtest-report`` passes ``source=None`` and, since the 2026-09-09
grouped-daily ingestion, would load duplicated ``massive`` + ``massive_grouped``
bars for 2025-01..2026-09).

It never calls ``evaluate_promotion``, never writes ``strategy_sealed_test``,
never changes a status, a setting, a threshold or an approval scope, and never
touches execution. Default is a dry run that prints OOS trade COUNTS per regime
only. ``--confirm`` persists; run it only with the worker stopped (one writer
per SQLite DB) and only after operator sign-off on the pre-registration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, timedelta

from sqlalchemy import select

from signalforge.backtest.costs import CostModel
from signalforge.db.models import BacktestRun, Strategy, StrategyVersion
from signalforge.db.session import session_scope
from signalforge.research.backtest_runner import run_strategy_over_universe
from signalforge.research.persistence import (
    _HASH_EXCLUDED_SPEC_FIELDS,
    persist_backtest_result,
    spec_json_hash,
)
from signalforge.research.strategies import default_strategies
from signalforge.settings_store import effective_research_config

PREREGISTERED = (
    "trend_continuation.short_swing",
    "trend_continuation.medium_swing",
    "relative_strength.medium_swing",
)
_WATCHLIST_RUN_ID = 41  # the current evidence rows' 25-symbol universe


def _stored_hash(spec_json: dict[str, object]) -> str:
    """``spec_json_hash`` of a stored row's spec, so a behavior drift between the
    approved version row and today's code refuses the write."""
    payload = {k: v for k, v in spec_json.items() if k not in _HASH_EXCLUDED_SPEC_FIELDS}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--end", type=date.fromisoformat, required=True)
    ap.add_argument("--years", type=int, required=True)
    ap.add_argument("--source", default="massive")
    ap.add_argument("--strategies", nargs="+", default=list(PREREGISTERED))
    ap.add_argument("--confirm", action="store_true", help="persist (default: dry run)")
    args = ap.parse_args()
    unknown = set(args.strategies) - set(PREREGISTERED)
    if unknown:
        raise SystemExit(f"not pre-registered: {sorted(unknown)}")

    start = args.end - timedelta(days=365 * args.years + 10)
    strategies = {s.spec().name: s for s in default_strategies()}
    results = []
    with session_scope() as session:
        cfg = effective_research_config(session)
        ref = session.get(BacktestRun, _WATCHLIST_RUN_ID)
        if ref is None:
            raise SystemExit(f"reference backtest_run {_WATCHLIST_RUN_ID} missing")
        symbols = list(ref.params_json["symbols"])
        cost_model = CostModel(
            commission_per_share=cfg.commission_per_share,
            commission_min_per_order=cfg.commission_min_per_order,
            slippage_bps=cfg.slippage_bps,
            half_spread_fill_penalty=cfg.half_spread_fill_penalty,
        )
        for name in args.strategies:
            strat = strategies[name]
            res = run_strategy_over_universe(
                session,
                strat,
                symbols,
                start,
                args.end,
                source=args.source,
                allow_short=cfg.allow_short_candidates,
                config_hash=cfg.config_hash,
                cost_model=cost_model,
                min_bars=60,
            )
            counts = {k: m.n_trades for k, m in res.by_regime.items()}
            print(f"{name}: window {start}..{args.end} OOS n={res.out_of_sample.n_trades} {counts}")
            results.append((strat, res))

    if not args.confirm:
        print("dry run — nothing persisted")
        return
    with session_scope(write=True) as session:
        for strat, res in results:
            spec = strat.spec()
            ver = session.scalar(
                select(StrategyVersion)
                .join(Strategy, Strategy.id == StrategyVersion.strategy_id)
                .where(Strategy.name == spec.name, StrategyVersion.version == spec.version)
            )
            if ver is None or _stored_hash(ver.spec_json) != spec_json_hash(spec):
                raise SystemExit(f"{spec.name} {spec.version}: stored spec differs; refusing")
            run = persist_backtest_result(session, ver, res)
            print(json.dumps({"strategy": spec.name, "version_id": ver.id, "run_id": run.id}))


if __name__ == "__main__":
    main()
