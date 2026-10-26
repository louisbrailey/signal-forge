"""One final paired comparison; no model selection or promotion authority."""

from __future__ import annotations

import fcntl
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from signalforge.db.models import PaperPosition
from signalforge.experiments.comparison import ARMS, NOTICE, digest, open_books


def metrics(rows: list[dict], initial: float = 10000.0) -> dict:
    equity = np.asarray([initial] + [r["equity"] for r in rows], dtype=float)
    returns = np.diff(equity) / equity[:-1]
    sigma = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    last = rows[-1]
    return {
        "net_return": float(equity[-1] / initial - 1),
        "maximum_drawdown": float(np.max(1 - equity / np.maximum.accumulate(equity))),
        "annualized_volatility": sigma * float(np.sqrt(252)),
        "sharpe_zero_cash_rate": float(returns.mean() / sigma * np.sqrt(252)) if sigma else None,
        "closed_trades": last["closed_trades"],
        "hit_rate": (
            last["winning_trades"] / last["closed_trades"] if last["closed_trades"] else None
        ),
        "profit_factor": last["gross_profit"] / last["gross_loss"] if last["gross_loss"] else None,
        "mean_exposure": float(np.mean([r["invested"] / r["equity"] for r in rows])),
        "entry_cost_attribution": last["entry_costs"],
        "cost_note": "Net equity includes entry/exit costs; attribution is entry-only.",
    }


def paired_interval(
    a: list[float], b: list[float], *, samples: int = 5000, block: int = 21
) -> list[float]:
    """Circular calendar-block bootstrap of paired daily return differences.

    Interval is for mean DAILY incremental return, not profit probability.
    Keep simultaneous symbols/trades together by resampling portfolio days.
    """
    delta = np.asarray(a) - np.asarray(b)
    rng = np.random.default_rng(42817)
    draws = []
    for _ in range(samples):
        starts = rng.integers(0, len(delta), size=(len(delta) + block - 1) // block)
        indices = ((starts[:, None] + np.arange(block)) % len(delta)).ravel()[: len(delta)]
        draws.append(float(delta[indices].mean()))
    # Two comparisons within one strategy family: Bonferroni-adjusted 97.5% CIs.
    return [float(x) for x in np.quantile(draws, [0.0125, 0.9875])]


def finalize(directory: Path) -> dict:
    """Idempotent sealed reveal after calendar end and all positions settled."""
    with (directory / "writer.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Comparison writer already running") from exc
        engine, manifest = open_books(directory)
        try:
            with Session(engine) as s, s.begin():
                existing = s.scalar(text("SELECT payload FROM comparison_final WHERE id=1"))
                if existing:
                    return json.loads(existing)
                end = manifest["study_days"][-1]
                if str(datetime.now(UTC).date()) <= end:
                    raise ValueError("Final period is still sealed")
                if s.scalar(
                    select(PaperPosition.id).where(PaperPosition.closed_at.is_(None)).limit(1)
                ):
                    raise ValueError("Open positions must settle before final analysis")
                raw = list(
                    s.execute(
                        text("SELECT day,book,payload FROM comparison_daily ORDER BY day,book")
                    )
                )
                if not raw or max(r[0] for r in raw) < end:
                    raise ValueError("Portfolio observations do not cover final session")
                books: dict[str, list] = {}
                for day, book, payload in raw:
                    books.setdefault(book, []).append((day, json.loads(payload)))
                results = {}
                for version in manifest["versions"]:
                    arms = {arm: books.get(f"experiment-v{version}-{arm}", []) for arm in ARMS}
                    dates = [d for d, _ in arms["baseline"]]
                    if not dates or any([d for d, _ in rows] != dates for rows in arms.values()):
                        raise ValueError("Unpaired portfolio observations")
                    if not set(manifest["study_days"]).issubset(dates):
                        raise ValueError("Missing study sessions")
                    summaries = {arm: metrics([r for _, r in rows]) for arm, rows in arms.items()}
                    rets = {}
                    for arm, rows in arms.items():
                        equity = np.asarray([10000.0] + [r["equity"] for _, r in rows])
                        rets[arm] = (np.diff(equity) / equity[:-1]).tolist()
                    intervals = {
                        arm: paired_interval(
                            rets["filtered"],
                            rets[arm],
                            samples=manifest["bootstrap_samples"],
                            block=manifest["bootstrap_block_sessions"],
                        )
                        for arm in ("baseline", "matched")
                    }
                    sufficient = (
                        summaries["baseline"]["closed_trades"]
                        >= manifest["min_closed_baseline_trades"]
                    )
                    results[version] = {
                        "books": summaries,
                        "paired_daily_increment_intervals": intervals,
                        "sample_floor_met": sufficient,
                        "verdict": (
                            "requires independent review"
                            if sufficient and all(ci[0] > 0 for ci in intervals.values())
                            else "insufficient evidence of improvement"
                        ),
                    }
                output = {
                    "manifest_hash": manifest["hash"],
                    "input_hash": digest([list(r) for r in raw]),
                    "evaluated_at": datetime.now(UTC).isoformat(),
                    "results": results,
                    "limitations": [
                        "Exploratory across strategy families; no pooled winner selection.",
                        "Interval is not a profit probability. Review regimes and outages.",
                        "Cash earns zero. Midpoint fills and daily-bar exits are hypothetical.",
                        "No promotion or operating changes are authorized by this report.",
                    ],
                    "notice": NOTICE,
                }
                s.execute(
                    text("INSERT INTO comparison_final VALUES (1,:payload)"),
                    {"payload": json.dumps(output)},
                )
                return output
        finally:
            engine.dispose()
