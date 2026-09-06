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
paper_app = typer.Typer(help="Paper-trading ledger (SIMULATED — no order is ever placed).")
app.add_typer(paper_app, name="paper")
portfolio_app = typer.Typer(help="Manual CSV portfolio import — analytics only, no broker contact.")
app.add_typer(portfolio_app, name="portfolio")


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


@paper_app.command("accept")
def paper_accept(candidate_id: int) -> None:
    """Paper-accept a candidate (SIMULATED fill). Research signal only — no order was placed."""
    from signalforge.db.session import session_scope
    from signalforge.paper.ledger import accept_candidate

    with session_scope() as session:
        res = accept_candidate(session, candidate_id)
    typer.secho(
        f"SIMULATED {res.side.value} {res.shares} @ {res.fill_price} "
        f"(cost {res.total_cost:.2f}) — trade #{res.paper_trade_id}. "
        "Research signal only — no order was placed.",
        fg=typer.colors.GREEN,
    )


@paper_app.command("mtm")
def paper_mtm() -> None:
    """Mark open paper positions to market; close any that hit stop/target/time-stop."""
    from signalforge.db.session import session_scope
    from signalforge.paper.ledger import mark_to_market

    with session_scope() as session:
        r = mark_to_market(session)
    typer.echo(
        f"checked {r.checked}, closed {r.closed}, realized {r.realized_pnl:+.2f}, "
        f"unrealized {r.unrealized_pnl:+.2f}"
    )


@paper_app.command("snapshot")
def paper_snapshot() -> None:
    """Print the paper account portfolio snapshot."""
    import json

    from signalforge.db.session import session_scope
    from signalforge.paper.portfolio import portfolio_snapshot

    with session_scope() as session:
        typer.echo(json.dumps(portfolio_snapshot(session), indent=2, default=str))


@portfolio_app.command("import")
def portfolio_import(path: str) -> None:
    """Import a broker CSV (positions or transactions) for analytics. No broker is contacted."""
    from pathlib import Path

    from signalforge.db.session import session_scope
    from signalforge.portfolio import import_csv

    text = Path(path).read_text(encoding="utf-8", errors="replace")
    with session_scope() as session:
        s = import_csv(session, Path(path).name, text)
    if s.already_imported:
        typer.secho(f"Already imported (batch #{s.batch_id}).", fg=typer.colors.YELLOW)
        return
    typer.secho(
        f"Imported batch #{s.batch_id} [{s.detected_format}]: "
        f"{s.positions_imported} positions, {s.transactions_imported} transactions. "
        "Analytics only — never scanned as tradable.",
        fg=typer.colors.GREEN,
    )


@portfolio_app.command("analytics")
def portfolio_analytics_cmd() -> None:
    """Show exposure / concentration from imported positions."""
    import json

    from signalforge.db.session import session_scope
    from signalforge.portfolio import portfolio_analytics

    with session_scope() as session:
        typer.echo(json.dumps(portfolio_analytics(session), indent=2, default=str))


@app.command()
def briefing(
    show_facts: Annotated[bool, typer.Option(help="Also print the raw frozen facts dict.")] = False,
) -> None:
    """Build and store today's daily research briefing (deterministic; LLM narrative optional)."""
    import json

    from signalforge.briefing import build_and_store_briefing
    from signalforge.db.session import session_scope

    with session_scope() as session:
        payload = build_and_store_briefing(session)
    typer.echo(payload["text"])
    if payload["narrative"]:
        typer.secho("\n--- AI narrative (explanation, not a trading instruction) ---", fg="cyan")
        typer.echo(payload["narrative"])
    if show_facts:
        typer.echo("\n--- frozen facts ---")
        typer.echo(json.dumps(payload["facts"], indent=2, default=str))


@app.command()
def alerts() -> None:
    """Evaluate the alert policy and dispatch anything due (nothing until enabled in Settings)."""
    ensure_not_engaged()
    from signalforge.alerts.dispatch import run_alert_cycle
    from signalforge.db.session import session_scope

    with session_scope() as session:
        r = run_alert_cycle(session)
    typer.echo(
        f"alerts: enabled={r.enabled} planned={r.planned} sent={r.sent} "
        f"suppressed={len(r.suppressed)}"
    )
    for s in r.suppressed:
        typer.secho(f"  - suppressed: {s}", fg=typer.colors.YELLOW)


@app.command("run-scheduler")
def run_scheduler() -> None:
    """Run the in-process background scheduler (ingest / scan / MTM / feed probe).

    Every job is a no-op while the kill switch is engaged.
    """
    import time

    from signalforge.scheduler import build_scheduler, run_catch_up

    ensure_not_engaged()
    run_catch_up()
    scheduler = build_scheduler()
    scheduler.start()
    typer.secho("scheduler running — Ctrl-C to stop", fg=typer.colors.CYAN)
    try:
        while True:
            time.sleep(2)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown(wait=False)


@app.command("run-job")
def run_job(
    name: Annotated[str, typer.Argument(help="ingest | scan_all | paper_mtm | feed_probe")],
) -> None:
    """Run one scheduled job once (kill-switch guarded)."""
    from signalforge.scheduler import default_job_specs, guarded

    spec = next((s for s in default_job_specs() if s.name == name), None)
    if spec is None:
        typer.secho(f"unknown job {name!r}", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    guarded(spec.name, spec.fn)()
    typer.secho(f"job {name} finished", fg=typer.colors.GREEN)


@app.command()
def backup() -> None:
    """Snapshot the local database (Phase 1)."""
    typer.secho("`make backup` is implemented later in Phase 1 (§1.13).", fg="yellow")
    raise typer.Exit(code=1)


def main() -> None:
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
