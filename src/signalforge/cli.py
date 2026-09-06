"""``signalforge`` command-line entrypoint."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Annotated

import typer

from signalforge import __version__
from signalforge.audit import record
from signalforge.killswitch import ensure_not_engaged, get_kill_switch
from signalforge.observability import configure_logging

app = typer.Typer(add_completion=False, help="Signal Forge — research/education only. No trading.")
killswitch_app = typer.Typer(help="Emergency kill switch (S6): halt polling, jobs, alerts, paper.")
app.add_typer(killswitch_app, name="killswitch")


@app.callback()
def _root() -> None:
    configure_logging()


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(__version__)


@killswitch_app.command("on")
def killswitch_on(
    reason: Annotated[str, typer.Option(help="Why the switch is being engaged.")] = "manual",
    actor: Annotated[str, typer.Option()] = "cli",
) -> None:
    """Engage the kill switch."""
    st = get_kill_switch().engage(reason=reason, actor=actor)
    record("killswitch.engage", actor=actor, entity="killswitch", reason=reason)
    typer.secho(f"Kill switch ENGAGED — {st.reason}", fg=typer.colors.RED)


@killswitch_app.command("off")
def killswitch_off(
    reason: Annotated[str, typer.Option(help="Why the switch is being released.")] = "manual",
    actor: Annotated[str, typer.Option()] = "cli",
) -> None:
    """Release the kill switch."""
    st = get_kill_switch().release(reason=reason, actor=actor)
    record("killswitch.release", actor=actor, entity="killswitch", reason=reason)
    typer.secho(f"Kill switch released — {st.reason}", fg=typer.colors.GREEN)


@killswitch_app.command("status")
def killswitch_status() -> None:
    """Show the current kill-switch state."""
    st = get_kill_switch().state()
    typer.echo(f"active={st.active} reason={st.reason!r} actor={st.actor} since={st.changed_at}")


@app.command()
def seed(years: Annotated[int, typer.Option(help="Years of simulated history.")] = 3) -> None:
    """Load clearly-labelled SIMULATED demo data (fixture adapter only)."""
    from signalforge.seed import seed_demo_data

    summary = seed_demo_data(years=years)
    typer.secho("Seeded SIMULATED demo data:", fg=typer.colors.GREEN)
    typer.echo(f"  instruments:    {summary.instruments}")
    typer.echo(f"  bars written:   {summary.bars_written}  (source=fixture, is_simulated=True)")
    typer.echo(f"  paper account:  {summary.paper_account}")
    typer.echo(f"  watchlist:      {summary.watchlist}")
    typer.secho("  All prices are synthetic. Not market data.", fg=typer.colors.YELLOW)


@app.command()
def ingest(
    provider: Annotated[str, typer.Option(help="Adapter name (default: configured).")] = "",
    since: Annotated[str, typer.Option(help="Start date YYYY-MM-DD.")] = "",
    symbols: Annotated[
        str, typer.Option(help="Comma-separated; default: configured universe.")
    ] = "",
) -> None:
    """Fetch daily bars into the local store via the configured adapter."""
    ensure_not_engaged()
    from signalforge.config import get_settings
    from signalforge.data.adapters.registry import build_adapter, get_primary_adapter
    from signalforge.data.ingest import ingest_universe
    from signalforge.db.session import session_scope

    settings = get_settings()
    adapter = build_adapter(provider) if provider else get_primary_adapter(settings)
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()] or list(
        settings.research.universe
    )
    start = date.fromisoformat(since) if since else (datetime.now().date() - timedelta(days=400))
    end = datetime.now().date()

    with session_scope() as session:
        report = ingest_universe(session, adapter, syms, start, end)

    typer.secho(
        f"ingest[{adapter.provider_name}] {start}..{end}: "
        f"{report.bars_written} bars written across {len(syms)} symbols",
        fg=typer.colors.GREEN,
    )
    for err in report.errors:
        typer.secho(f"  ! {err}", fg=typer.colors.RED)


@app.command("backtest-report")
def backtest_report(
    out_dir: Annotated[str, typer.Option(help="Directory for the markdown reports.")] = "reports",
    years: Annotated[int, typer.Option(help="History window to test over.")] = 3,
) -> None:
    """Run every baseline strategy over the configured universe and write reports/."""
    from pathlib import Path

    from signalforge.config import get_settings
    from signalforge.db.session import session_scope
    from signalforge.research.backtest_runner import run_strategy_over_universe
    from signalforge.research.reporting import render_report_md
    from signalforge.research.strategies import default_strategies

    settings = get_settings()
    symbols = list(settings.research.universe)
    end = date.today()
    start = end - timedelta(days=365 * years + 10)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    from signalforge.research.persistence import (
        persist_backtest_result,
        upsert_strategy_version,
    )

    with session_scope() as session:
        for strat in default_strategies():
            result = run_strategy_over_universe(
                session,
                strat,
                symbols,
                start,
                end,
                allow_short=settings.research.allow_short_candidates,
                config_hash=settings.research.config_hash,
            )
            version = upsert_strategy_version(session, strat.spec())
            persist_backtest_result(session, version, result)
            path = out / f"{strat.spec().key}-{strat.spec().version}.md"
            path.write_text(render_report_md(result), encoding="utf-8")
            typer.secho(
                f"  {strat.spec().key}: {result.n_trades} trades  "
                f"OOS expectancy {result.out_of_sample.expectancy_r:+.3f}R  -> {path}",
                fg=typer.colors.GREEN,
            )


@app.command()
def scan(
    horizon: Annotated[
        str, typer.Option(help="SHORT_SWING | MEDIUM_SWING | POSITION")
    ] = "SHORT_SWING",
) -> None:
    """Run one horizon's scan and persist the scan_run + candidate rows."""
    ensure_not_engaged()
    from signalforge.db.session import session_scope
    from signalforge.domain import Horizon
    from signalforge.research.candidates import persist_scan
    from signalforge.research.scan import run_scan

    h = Horizon(horizon.upper())
    with session_scope() as session:
        result = run_scan(session, h)
        run = persist_scan(session, result)

    passing = [c for c in result.candidates if c.quality_gate_status.value == "PASSED"]
    typer.secho(f"scan[{h.value}] run #{run.id}", fg=typer.colors.CYAN)
    typer.echo(f"  universe scanned:        {len(result.scanned)}")
    typer.echo(f"  excluded:                {result.excluded_count}")
    for reason, syms in result.excluded.items():
        typer.echo(f"    - {reason}: {len(syms)}")
    typer.echo(f"  NO TRADE:                {len(result.no_trade)}")
    typer.echo(f"  qualified candidates:    {len(passing)}")
    if not result.live_alerts_enabled:
        typer.secho("  live alerts DISABLED (stale/unavailable feed)", fg=typer.colors.YELLOW)
    for c in passing:
        typer.secho(
            f"    {c.symbol} {c.direction.value} rr={c.reward_risk_estimate} "
            f"entry {c.entry_zone_low}-{c.entry_zone_high} stop {c.invalidation_level}",
            fg=typer.colors.GREEN,
        )


@app.command()
def backup() -> None:
    """Snapshot the local database (Phase 1)."""
    typer.secho("`make backup` is implemented later in Phase 1 (§1.13).", fg="yellow")
    raise typer.Exit(code=1)


def main() -> None:
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
