"""Markdown + JSON report writer for grid backtests.

Reports land under ``docs/research/grid/`` so a run is reviewable in the repo.
Every report restates the rules, the exact parameters, the cost model, the data
limitations, and the SPY benchmark, because the grid is a mechanical rule with
no promotion evidence behind it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from signalforge.grid.data import ADJUSTMENT_NOTE
from signalforge.grid.engine import GridBacktestResult
from signalforge.grid.universe import GridUniverse

__all__ = ["default_report_dir", "render_report_md", "write_report"]

_DISCLAIMER = (
    "> **Hypothetical research output — not financial advice.** The grid is a "
    "mechanical rebalancing rule, not a researched edge: it has no promotion "
    "evidence, no walk-forward validation, and is not a registered strategy. "
    "Simulated fills only — no order was placed."
)


def default_report_dir() -> Path:
    """``<repo root>/docs/research/grid``."""
    return Path(__file__).resolve().parents[3] / "docs" / "research" / "grid"


def _fmt(x: float, spec: str = "{:,.2f}") -> str:
    try:
        return spec.format(x)
    except (ValueError, TypeError):
        return str(x)


def _kv_table(rows: Mapping[str, Any], key_label: str = "Field", val_label: str = "Value") -> str:
    lines = [f"| {key_label} | {val_label} |", "|---|---|"]
    for k, v in rows.items():
        lines.append(f"| {k} | {v} |")
    return "\n".join(lines)


def render_report_md(
    result: GridBacktestResult,
    *,
    title: str,
    universe: GridUniverse | None = None,
    source: str = "",
    notes: str = "",
    git_sha: str = "",
) -> str:
    p = result.params
    m = result.metrics
    b = result.benchmark
    vs_spy = (
        f"{m.total_return_pct - b.total_return_pct:+.3f} pp"
        if b.available
        else "n/a (no benchmark bars)"
    )

    params_tbl = _kv_table(
        {
            "starting_cash": f"${_fmt(p.starting_cash)}",
            "per_symbol_cap": f"${_fmt(p.per_symbol_cap)}",
            "buy_usd": f"${_fmt(p.buy_usd)}",
            "sell_usd": f"${_fmt(p.sell_usd)}",
            "drop_pct": f"{p.drop_pct:.2%}",
            "rise_pct": f"{p.rise_pct:.2%}",
            "min_order_usd": f"${_fmt(p.min_order_usd)}",
            "re-anchor on a rise with nothing to sell": (
                "yes (the grid ratchets up with price)"
                if p.reanchor_on_untradeable_rise
                else "no (strict literal reading — a symbol that rises before it ever dips "
                "is stranded forever)"
            ),
            "universe_name": p.universe_name,
            "universe_size": p.universe_size,
            "costs": p.costs_label,
            "budget if every symbol caps out": f"${_fmt(p.max_committed_usd)}",
            "budget consistent with starting cash": "yes" if p.budget_is_consistent else "**no**",
        },
        "Parameter",
        "Value",
    )

    headline = _kv_table(
        {
            "Total return": f"{m.total_return_pct:+.3f}%",
            "CAGR": f"{m.cagr_pct:+.3f}%",
            "Max drawdown": f"{m.max_drawdown_pct:.3f}%",
            "Annualised vol": f"{m.ann_vol_pct:.3f}%",
            "Sharpe (daily, rf=0)": f"{m.sharpe:.3f}",
            "Sortino (daily, rf=0)": f"{m.sortino:.3f}",
            "Exposure (mean invested fraction)": f"{m.exposure:.2%}",
            "Turnover / year": f"{m.turnover_per_year:.3f}x",
            "Trades": f"{m.n_trades:,} ({m.n_buys:,} buys / {m.n_sells:,} sells)",
            "Trades / year": f"{m.trades_per_year:,.1f}",
            "Start equity": f"${_fmt(m.start_equity)}",
            "End equity": f"${_fmt(m.end_equity)}",
            "Sessions": f"{m.sessions:,}",
        },
        "Metric",
        "Value",
    )

    bench_tbl = (
        _kv_table(
            {
                "Benchmark": f"{b.symbol} buy-and-hold, same cash, same span, same cost model",
                "Window": f"{b.start_date} → {b.end_date}",
                "Total return": f"{b.total_return_pct:+.3f}%",
                "CAGR": f"{b.cagr_pct:+.3f}%",
                "Max drawdown": f"{b.max_drawdown_pct:.3f}%",
                "End equity": f"${_fmt(b.end_equity)}",
                "Grid − benchmark (total return)": vs_spy,
            },
            "Benchmark",
            "Value",
        )
        if b.available
        else f"Benchmark unavailable: {b.detail}"
    )

    cash = dict(result.cash_utilisation)
    cash_tbl = _kv_table(
        {
            "Starting cash": f"${_fmt(cash.get('starting_cash', 0.0))}",
            "Minimum cash held": f"${_fmt(cash.get('min_cash', 0.0))}",
            "Mean cash held": f"${_fmt(cash.get('mean_cash', 0.0))}",
            "Final cash": f"${_fmt(cash.get('final_cash', 0.0))}",
            "Peak invested": f"${_fmt(cash.get('peak_invested', 0.0))}",
            "Mean deployed fraction": f"{cash.get('mean_deployed_fraction', 0.0):.2%}",
            "Max deployed fraction": f"{cash.get('max_deployed_fraction', 0.0):.2%}",
            "Budget if every symbol caps out": (
                f"${_fmt(cash.get('budget_if_every_symbol_capped', 0.0))}"
            ),
        },
        "Cash utilisation",
        "Value",
    )

    dist = dict(result.pnl_distribution)
    dist_tbl = (
        _kv_table(
            {
                "Symbols that traded": f"{int(dist.get('n', 0)):,}",
                "Profitable symbols": f"{int(dist.get('n_positive', 0)):,}",
                "Losing symbols": f"{int(dist.get('n_negative', 0)):,}",
                "Total P&L (realised + unrealised)": f"${_fmt(float(dist.get('total', 0.0)))}",
                "Mean per symbol": f"${_fmt(float(dist.get('mean', 0.0)))}",
                "p10 / p25 / median / p75 / p90": (
                    f"${_fmt(float(dist.get('p10', 0.0)))} / "
                    f"${_fmt(float(dist.get('p25', 0.0)))} / "
                    f"${_fmt(float(dist.get('median', 0.0)))} / "
                    f"${_fmt(float(dist.get('p75', 0.0)))} / "
                    f"${_fmt(float(dist.get('p90', 0.0)))}"
                ),
                "Worst / best symbol": (
                    f"${_fmt(float(dist.get('min', 0.0)))} / ${_fmt(float(dist.get('max', 0.0)))}"
                ),
            },
            "Per-symbol P&L",
            "Value",
        )
        if dist.get("n")
        else "No symbol traded."
    )

    skips = dict(result.skip_counts)
    skip_tbl = (
        _kv_table({k: f"{v:,}" for k, v in sorted(skips.items())}, "Skipped trigger", "Count")
        if skips
        else "No trigger was ever skipped."
    )

    worst = sorted(result.per_symbol_pnl.items(), key=lambda kv: kv[1])[:10]
    best = sorted(result.per_symbol_pnl.items(), key=lambda kv: kv[1], reverse=True)[:10]
    tails = "\n".join(
        ["| Rank | Best symbol | P&L | Worst symbol | P&L |", "|---|---|---|---|---|"]
        + [
            f"| {i + 1} | {best[i][0] if i < len(best) else ''} | "
            f"{('$' + _fmt(best[i][1])) if i < len(best) else ''} | "
            f"{worst[i][0] if i < len(worst) else ''} | "
            f"{('$' + _fmt(worst[i][1])) if i < len(worst) else ''} |"
            for i in range(max(len(best[:10]), len(worst[:10])))
        ]
    )

    uni_lines = []
    if universe is not None:
        uni_lines = [
            f"- Universe: `{universe.name}` ({len(universe.symbols)} requested) from "
            f"`{universe.source}`",
            f"- Ranking: {universe.ranking_note or 'n/a'}",
            f"- Liquidity window: {' → '.join(universe.liquidity_window) or 'n/a'}",
        ]

    lines = [
        f"# {title}",
        "",
        _DISCLAIMER,
        "",
        f"- Generated: {datetime.now(UTC).isoformat(timespec='seconds')}",
        f"- git: `{git_sha or 'n/a'}`",
        f"- Window: {result.start} → {result.end} ({m.span_days:,} calendar days, "
        f"{m.sessions:,} sessions)",
        f"- Data source: `{source or 'n/a'}`",
        *uni_lines,
        f"- Symbols with bars: **{len(result.symbols):,}**; "
        f"skipped for no/insufficient bars in the window: **{len(result.skipped_symbols):,}**",
        f"- Symbols that traded: **{result.symbols_traded:,}**; "
        f"symbols that reached the per-symbol cap: **{result.symbols_at_cap:,}**",
        "",
        "## Rules",
        "",
        "Per symbol, on DAILY closes, exactly one evaluation per session:",
        "",
        "1. Anchor starts at the close of the first tracked session (that session never trades).",
        f"2. `close <= anchor x (1 - {p.drop_pct:.2%})` → BUY ${_fmt(p.buy_usd)} "
        "(fractional shares), then anchor = that close.",
        f"3. `close >= anchor x (1 + {p.rise_pct:.2%})` → SELL ${_fmt(p.sell_usd)}, capped at the "
        "position's market value, then anchor = that close.",
        "4. Fills at the **next session's open** with slippage + half-spread against the trade.",
        "5. The anchor moves when an order fills. A buy skipped for the cap, for cash, or for "
        "the minimum notional leaves the level armed."
        + (
            " A rise past the sell level with nothing to sell re-anchors anyway, so the grid "
            "follows price (`reanchor_on_untradeable_rise`)."
            if p.reanchor_on_untradeable_rise
            else " A rise past the sell level with nothing to sell does NOT re-anchor "
            "(`reanchor_on_untradeable_rise` is off), so a symbol that rises before it ever "
            "dips can never trade again."
        ),
        "6. A sell that would leave a remainder worth less than the minimum notional sells the "
        "WHOLE position instead, so no unsellable stub can freeze a symbol.",
        "7. No leverage, no shorting: cash never goes negative and a sell never exceeds holdings.",
        "",
        "## Parameters",
        "",
        params_tbl,
        "",
        "## Headline metrics",
        "",
        headline,
        "",
        "## Benchmark",
        "",
        bench_tbl,
        "",
        "## Cash utilisation",
        "",
        cash_tbl,
        "",
        "## Per-symbol P&L distribution",
        "",
        dist_tbl,
        "",
        tails,
        "",
        "## Skipped triggers",
        "",
        skip_tbl,
        "",
        "## Data limitations",
        "",
        f"- {ADJUSTMENT_NOTE}",
        "- U.S.-listed symbols only. No non-U.S. exchanges are covered at all.",
        "- The universe is ranked by *today's* liquidity, so it is survivorship-biased: names "
        "that delisted or collapsed before the screen date are absent, which flatters any "
        "buy-the-dip rule.",
        "- Daily closes only — no intraday path, so a level breached and reversed inside a "
        "session is invisible to the rule.",
        "- Exchange holidays and per-symbol listing dates are handled by simply using whatever "
        "sessions each symbol actually has; a symbol that lists mid-window starts tracking then.",
        "",
    ]
    if notes:
        lines += ["## Notes", "", notes, ""]
    return "\n".join(lines)


def write_report(
    result: GridBacktestResult,
    *,
    slug: str,
    title: str,
    out_dir: Path | str | None = None,
    universe: GridUniverse | None = None,
    source: str = "",
    notes: str = "",
    git_sha: str = "",
    include_trades: bool = True,
) -> tuple[Path, Path]:
    """Write ``<slug>.md`` and ``<slug>.json``; returns both paths."""
    directory = Path(out_dir) if out_dir else default_report_dir()
    directory.mkdir(parents=True, exist_ok=True)
    md_path = directory / f"{slug}.md"
    json_path = directory / f"{slug}.json"

    md_path.write_text(
        render_report_md(
            result, title=title, universe=universe, source=source, notes=notes, git_sha=git_sha
        ),
        encoding="utf-8",
    )

    payload = result.to_dict()
    payload["title"] = title
    payload["slug"] = slug
    payload["source"] = source
    payload["git_sha"] = git_sha
    payload["generated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    payload["adjustment_note"] = ADJUSTMENT_NOTE
    if universe is not None:
        payload["universe"] = universe.to_dict()
    if not include_trades:
        payload.pop("trades", None)
        payload.pop("equity_curve", None)
    json_path.write_text(json.dumps(payload, indent=1, sort_keys=False), encoding="utf-8")
    return md_path, json_path
