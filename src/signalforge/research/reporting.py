"""Render a strategy backtest result as a committed Markdown report."""

from __future__ import annotations

from datetime import UTC, datetime

from signalforge.backtest.metrics import Metrics
from signalforge.research.backtest_runner import StrategyBacktestResult

_KEYS = [
    ("n_trades", "Trades", "{:d}"),
    ("win_rate", "Win rate", "{:.1%}"),
    ("avg_win_r", "Avg win (R)", "{:+.2f}"),
    ("avg_loss_r", "Avg loss (R)", "{:+.2f}"),
    ("expectancy_r", "Expectancy (R)", "{:+.3f}"),
    ("profit_factor", "Profit factor", "{:.2f}"),
    ("max_drawdown_r", "Max drawdown (R)", "{:.2f}"),
    ("risk_adjusted_ratio", "Risk-adj ratio*", "{:.2f}"),
    ("avg_bars_held", "Avg bars held", "{:.1f}"),
    ("largest_losing_streak", "Worst losing streak", "{:d}"),
    ("total_return_r", "Total return (R)", "{:+.1f}"),
]


def _row(label: str, m: Metrics) -> str:
    cells = []
    for key, _, fmt in _KEYS:
        val = getattr(m, key)
        try:
            cells.append(fmt.format(val))
        except (ValueError, TypeError):
            cells.append(str(val))
    return f"| {label} | " + " | ".join(cells) + " |"


def render_report_md(result: StrategyBacktestResult) -> str:
    spec = result.spec
    hdr = "| Segment | " + " | ".join(label for _, label, _ in _KEYS) + " |"
    sep = "|" + "---|" * (len(_KEYS) + 1)

    lines = [
        f"# Backtest report — {spec.key} v{spec.version}",
        "",
        "> **Hypothetical research output.** Simulated fills model spread and "
        "slippage; commission uses the configured `commission_per_share` (0 by "
        "default). Past results do not predict future results. This strategy is "
        "**EXPERIMENTAL** (paper only, no alerts) until promoted.",
        "",
        f"- Generated: {datetime.now(UTC).isoformat(timespec='seconds')}",
        f"- git: `{spec.git_sha}`  ·  config hash: `{result.config_hash or 'n/a'}`",
        f"- Horizon: {spec.horizon.value}",
        f"- Window: {result.start} → {result.end}",
        f"- Universe ({len(result.symbols)}): {', '.join(result.symbols)}",
        f"- Data: {result.data.label}",
        f"- Costs: {result.costs_label}",
        "",
        "## In-sample vs out-of-sample",
        "",
        hdr,
        sep,
        _row("In-sample (first 60%)", result.in_sample),
        _row("Out-of-sample (last 40%)", result.out_of_sample),
        "",
        "Out-of-sample bootstrap 95% CI:",
        "",
        f"- Expectancy (R): {result.oos_ci['expectancy_r']['low']:+.3f} … "
        f"{result.oos_ci['expectancy_r']['high']:+.3f} "
        f"(point {result.oos_ci['expectancy_r']['point']:+.3f})",
        (
            f"- Win rate: {result.oos_ci['win_rate']['low']:.1%} … "
            f"{result.oos_ci['win_rate']['high']:.1%} "
            f"(point {result.oos_ci['win_rate']['point']:.1%})"
            if "win_rate" in result.oos_ci
            else "- Win rate: n/a"
        ),
        f"- Profit factor: {result.oos_ci['profit_factor']['low']:.2f} … "
        f"{result.oos_ci['profit_factor']['high']:.2f}",
        "",
        "## Out-of-sample by market regime (entry-date regime)",
        "",
        hdr,
        sep,
        *[_row(label, m) for label, m in result.by_regime.items()],
        "",
        "## Trades per symbol",
        "",
        "| Symbol | Trades |",
        "|---|---|",
        *[f"| {s} | {n} |" for s, n in sorted(result.per_symbol_trades.items())],
        "",
        "\\* Risk-adjusted ratio is a per-trade Sharpe-like figure annualised by "
        "trade frequency — not computed from a daily return stream. Read with that "
        "limitation in mind.",
        "",
        "## Rule definition",
        "",
        spec.rule_definition,
        "",
        "### Known failure modes",
        "",
        *[f"- {fm}" for fm in spec.known_failure_modes],
        "",
    ]
    return "\n".join(lines) + "\n"
