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


@app.command()
def backup() -> None:
    """Snapshot the local database (Phase 1)."""
    typer.secho("`make backup` is implemented later in Phase 1 (§1.13).", fg="yellow")
    raise typer.Exit(code=1)


def main() -> None:
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
