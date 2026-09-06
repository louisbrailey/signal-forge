"""``signalforge`` command-line entrypoint."""

from __future__ import annotations

from typing import Annotated

import typer

from signalforge import __version__
from signalforge.audit import record
from signalforge.killswitch import get_kill_switch
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
def seed() -> None:
    """Load clearly-labelled SIMULATED demo data (Phase 1)."""
    typer.secho("No database schema yet — `make seed` is implemented in Phase 1.", fg="yellow")
    raise typer.Exit(code=1)


@app.command()
def backup() -> None:
    """Snapshot the local database (Phase 1)."""
    typer.secho("No database yet — `make backup` is implemented in Phase 1.", fg="yellow")
    raise typer.Exit(code=1)


def main() -> None:
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
