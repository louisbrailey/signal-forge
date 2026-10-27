"""``signalforge`` command-line entrypoint."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import typer

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from signalforge.data.options_backfill import (
        BackfillRequestPlan,
        OptionsCoverageSummary,
        RunBounds,
    )
    from signalforge.data.options_merge import MergeResult
    from signalforge.execution.protocol import BrokerAdapter
    from signalforge.jobspec import JobSpec
    from signalforge.research.portfolio_metrics import PortfolioMetrics

from signalforge import __version__
from signalforge.audit import record
from signalforge.killswitch import ensure_not_engaged, get_kill_switch
from signalforge.observability import configure_logging

app = typer.Typer(
    add_completion=False,
    help="Signal Forge — research first; execution is off by default and requires arming.",
)
killswitch_app = typer.Typer(help="Emergency kill switch (S6): halt polling, jobs, alerts, paper.")
app.add_typer(killswitch_app, name="killswitch")
paper_app = typer.Typer(
    help="Paper-trading ledger (SIMULATED fills; no broker order unless execution is armed)."
)
app.add_typer(paper_app, name="paper")
portfolio_app = typer.Typer(
    help="Manual CSV portfolio import — analytics only; this import never contacts a broker."
)
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


providers_app = typer.Typer(help="Verify provider entitlements (read-only; never prints secrets).")
app.add_typer(providers_app, name="providers")
data_app = typer.Typer(help="Historical-data pipeline: discover depth, ingest, validate, coverage.")
app.add_typer(data_app, name="data")


@data_app.command("discover-history")
def data_discover_history() -> None:
    """Probe how far back the provider actually serves daily bars (no config change)."""
    ensure_not_engaged()
    from signalforge.config import get_settings
    from signalforge.data.adapters.registry import get_primary_adapter
    from signalforge.data.discover import discover_history_depth

    depth = discover_history_depth(get_primary_adapter(get_settings()))
    typer.secho(
        f"earliest available: {depth.earliest_available}  "
        f"(first 403 at {depth.first_unavailable}; ref {depth.reference_symbol})",
        fg=typer.colors.GREEN,
    )
    typer.echo(f"safe ingest start (+45d margin): {depth.safe_start()}")
    typer.echo("Recorded per ingestion run — not hard-coded.")


@data_app.command("ingest-history")
def data_ingest_history(
    since: Annotated[
        str, typer.Option(help="Override start YYYY-MM-DD; default = discovered.")
    ] = "",
    symbols: Annotated[
        str, typer.Option(help="Comma-separated; default: configured universe.")
    ] = "",
    resume: Annotated[int, typer.Option(help="Resume an existing ingestion_run id.")] = 0,
) -> None:
    """Incremental, idempotent, auditable deep-history ingest with a recorded run."""
    ensure_not_engaged()
    from datetime import date as _date

    from signalforge.config import get_settings
    from signalforge.data.adapters.registry import get_primary_adapter
    from signalforge.data.discover import discover_history_depth
    from signalforge.data.ingest import ingest_daily_history
    from signalforge.db.session import session_scope

    s = get_settings()
    adapter = get_primary_adapter(s)
    syms = [x.strip().upper() for x in symbols.split(",") if x.strip()] or list(s.research.universe)
    end = _date.today()
    earliest = probe_at = None
    if since:
        start = _date.fromisoformat(since)
    else:
        depth = discover_history_depth(adapter)
        start = depth.safe_start()
        earliest, probe_at = depth.earliest_available, None
        from datetime import datetime as _dt

        probe_at = _dt.fromisoformat(depth.probed_at)
        typer.echo(f"discovered earliest {depth.earliest_available}; ingesting from {start}")

    with session_scope(write=True) as session:
        run = ingest_daily_history(
            session,
            adapter,
            syms,
            start,
            end,
            kind="full_history",
            earliest_available=earliest,
            earliest_probe_at=probe_at,
            resume_run_id=resume or None,
        )
        run_id, status, w, sk = run.id, run.status, run.bars_written, run.bars_skipped
        cov = (run.coverage_first, run.coverage_last)
        failed = dict(run.symbols_failed or {})
    typer.secho(
        f"ingestion_run #{run_id}: {status} — {w} written, {sk} already present; "
        f"coverage {cov[0]}..{cov[1]}",
        fg=typer.colors.GREEN if status == "ok" else typer.colors.YELLOW,
    )
    for sym, err in failed.items():
        typer.secho(f"  ! {sym}: {err}", fg=typer.colors.RED)
    typer.echo("Research signal only — no order was placed.")


@data_app.command("validate")
def data_validate(
    symbols: Annotated[
        str, typer.Option(help="Comma-separated; default: configured universe.")
    ] = "",
) -> None:
    """Run the data-quality validation pass and persist a report."""
    from signalforge.config import get_settings
    from signalforge.data.validate import validate_daily
    from signalforge.db.session import session_scope

    s = get_settings()
    syms = [x.strip().upper() for x in symbols.split(",") if x.strip()] or list(s.research.universe)
    with session_scope(write=True) as session:
        res = validate_daily(session, syms, source=s.market_data_provider)
        checks = [(c.name, c.passed, c.detail) for c in res.checks]
        passed = res.passed
    typer.secho(
        f"validation: {'PASS' if passed else 'FAIL'}",
        fg=typer.colors.GREEN if passed else typer.colors.RED,
    )
    for name, ok, detail in checks:
        typer.secho(
            f"  [{'ok ' if ok else 'FAIL'}] {name}: {detail}", fg=None if ok else typer.colors.RED
        )


@data_app.command("coverage")
def data_coverage(
    symbols: Annotated[str, typer.Option()] = "",
) -> None:
    """Per-symbol first/last/n-bars for the configured provider."""
    from sqlalchemy import func, select

    from signalforge.config import get_settings
    from signalforge.db.models import Instrument, OHLCVDaily
    from signalforge.db.session import session_scope

    s = get_settings()
    syms = [x.strip().upper() for x in symbols.split(",") if x.strip()] or list(s.research.universe)
    with session_scope() as session:
        rows = session.execute(
            select(
                Instrument.symbol,
                func.count(OHLCVDaily.id),
                func.min(OHLCVDaily.session_date),
                func.max(OHLCVDaily.session_date),
            )
            .join(Instrument, OHLCVDaily.instrument_id == Instrument.id)
            .where(Instrument.symbol.in_(syms), OHLCVDaily.source == s.market_data_provider)
            .group_by(Instrument.symbol)
            .order_by(Instrument.symbol)
        ).all()
    total = 0
    for sym, n, lo, hi in rows:
        total += n
        typer.echo(f"  {sym:8} {n:6d}  {lo}..{hi}")
    typer.echo(f"  {'TOTAL':8} {total:6d}  across {len(rows)}/{len(syms)} symbols")


@providers_app.command("refresh-context")
def providers_refresh_context() -> None:
    """Refresh bounded FX/metal/index context; no signals, alerts or trades."""
    from signalforge.data.market_context import refresh

    count = refresh()
    typer.echo(f"Recorded {count} context responses. Research signal only — no order was placed.")


@data_app.command("forex-ingest")
def data_forex_ingest(
    pairs: Annotated[
        str | None,
        typer.Option(help="Comma-separated pairs, e.g. EURUSD,USDJPY (default: FOREX_PAIRS)."),
    ] = None,
    lookback_days: Annotated[
        int | None,
        typer.Option(
            help="Days back for a pair with no stored bars (default: FOREX_LOOKBACK_DAYS)."
        ),
    ] = None,
    from_date: Annotated[
        str | None,
        typer.Option(
            "--from-date",
            help="Backfill OLDER history from this date (YYYY-MM-DD) up to the oldest stored bar.",
        ),
    ] = None,
) -> None:
    """Top up completed daily forex bars into fx_bar_daily. Research data only:
    no signal, alert, candidate or paper trade reads them."""
    from signalforge.config import get_settings
    from signalforge.data.forex import ingest_forex, parse_pairs
    from signalforge.db.session import session_scope

    settings = get_settings()
    chosen = parse_pairs(pairs if pairs is not None else settings.forex_pairs)
    days = lookback_days if lookback_days is not None else settings.forex_lookback_days
    with session_scope(write=True) as session:
        rep = ingest_forex(
            session,
            chosen,
            lookback_days=days,
            from_date=date.fromisoformat(from_date) if from_date else None,
        )
    typer.echo(f"Forex daily bars through {rep.end} (UTC, END-OF-DAY):")
    for pr in rep.pairs:
        detail = (
            pr.error
            if pr.status == "failed"
            else (
                f"+{pr.written} written, {pr.skipped_existing} existing, "
                f"{pr.weekend_dropped} weekend dropped, {len(pr.gaps)} weekday gaps"
            )
        )
        typer.echo(f"  {pr.pair:7} {pr.status:10} {detail}")
    typer.echo("Research data only — no order was placed.")
    if rep.failed:
        raise typer.Exit(1)


@data_app.command("crypto-ingest")
def data_crypto_ingest(
    pairs: Annotated[
        str | None,
        typer.Option(help="Comma-separated pairs, e.g. BTCUSD,ETHUSD (default: CRYPTO_PAIRS)."),
    ] = None,
    lookback_days: Annotated[
        int | None,
        typer.Option(
            help="Days back for a pair with no stored bars (default: CRYPTO_LOOKBACK_DAYS)."
        ),
    ] = None,
    from_date: Annotated[
        str | None,
        typer.Option(
            "--from-date",
            help="Backfill OLDER history from this date (YYYY-MM-DD) up to the oldest stored bar.",
        ),
    ] = None,
) -> None:
    """Top up completed daily crypto bars into crypto_bar_daily. Research data
    only: no signal, alert, candidate or paper trade reads them."""
    from signalforge.config import get_settings
    from signalforge.data.forex import CRYPTO, ingest_crypto, parse_pairs
    from signalforge.db.session import session_scope

    settings = get_settings()
    chosen = parse_pairs(pairs if pairs is not None else settings.crypto_pairs, CRYPTO)
    days = lookback_days if lookback_days is not None else settings.crypto_lookback_days
    with session_scope(write=True) as session:
        rep = ingest_crypto(
            session,
            chosen,
            lookback_days=days,
            from_date=date.fromisoformat(from_date) if from_date else None,
        )
    typer.echo(f"Crypto daily bars through {rep.end} (UTC, END-OF-DAY, 7 days/week):")
    for pr in rep.pairs:
        detail = (
            pr.error
            if pr.status == "failed"
            else (f"+{pr.written} written, {pr.skipped_existing} existing, {len(pr.gaps)} day gaps")
        )
        typer.echo(f"  {pr.pair:9} {pr.status:10} {detail}")
    typer.echo("Research data only — no order was placed.")
    if rep.failed:
        raise typer.Exit(1)


fx_app = typer.Typer(help="Forex research (research only; never a signal, alert or trade).")
app.add_typer(fx_app, name="fx")


@fx_app.command("research")
def fx_research(
    pairs: Annotated[
        str | None,
        typer.Option(help="Comma-separated pairs (default: FOREX_PAIRS)."),
    ] = None,
    out: Annotated[
        Path | None,
        typer.Option(help="Write the markdown report here (default: <data dir>/research/fx/)."),
    ] = None,
    version: Annotated[
        str, typer.Option(help="Pre-registered strategy set: FX-1 or FX-2.")
    ] = "FX-1",
) -> None:
    """Evaluate the pre-registered FX strategies on the development window.
    The sealed final year is never evaluated here. Research only."""
    import json as _json

    from signalforge.config import get_settings
    from signalforge.config.paths import data_dir
    from signalforge.data.forex import parse_pairs
    from signalforge.db.session import session_scope
    from signalforge.research.fx.harness import (
        render_markdown,
        run_fx2_research,
        run_fx_research,
    )

    if version not in ("FX-1", "FX-2"):
        typer.echo("--version must be FX-1 or FX-2")
        raise typer.Exit(2)
    chosen = parse_pairs(pairs if pairs is not None else get_settings().forex_pairs)
    runner = run_fx2_research if version == "FX-2" else run_fx_research
    with session_scope() as session:
        report = runner(session, chosen)
    md = render_markdown(report)
    target = out or (
        data_dir() / "research" / "fx" / f"fx_research_{report['version']}_{date.today()}.md"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(md)
    target.with_suffix(".json").write_text(_json.dumps(report, indent=2, default=str))
    for s in report["strategies"]:
        m = s["pooled"]
        typer.echo(
            f"  {s['key']:24} {s['verdict']:9} trades={m['n_trades']:4d} "
            f"exp={m['expectancy_r']:+.3f}R ci_low={s['ci_expectancy_r']['low']:+.3f}R "
            f"2x={s['stress_expectancy_r']:+.3f}R"
            + (
                f" hold={s['holding_stress_expectancy_r']:+.3f}R"
                if s.get("holding_stress_expectancy_r") is not None
                else ""
            )
        )
    typer.echo(f"Sealed from {report['sealed_from']} (not evaluated). Report: {target}")
    typer.echo("Research only — no order was placed.")


crypto_app = typer.Typer(help="Crypto research (research only; never a signal, alert or trade).")
app.add_typer(crypto_app, name="crypto")


@crypto_app.command("research")
def crypto_research(
    pairs: Annotated[
        str | None,
        typer.Option(help="Comma-separated pairs (default: CRYPTO_PAIRS)."),
    ] = None,
    out: Annotated[
        Path | None,
        typer.Option(help="Write the markdown report here (default: <data dir>/research/crypto/)."),
    ] = None,
) -> None:
    """Evaluate the pre-registered crypto strategies on the development window.
    The sealed final year is never evaluated here. Research only."""
    import json as _json

    from signalforge.config import get_settings
    from signalforge.config.paths import data_dir
    from signalforge.data.forex import CRYPTO, parse_pairs
    from signalforge.db.session import session_scope
    from signalforge.research.fx.harness import render_markdown, run_crypto_research

    chosen = parse_pairs(pairs if pairs is not None else get_settings().crypto_pairs, CRYPTO)
    with session_scope() as session:
        report = run_crypto_research(session, chosen)
    target = out or (
        data_dir()
        / "research"
        / "crypto"
        / f"crypto_research_{report['version']}_{date.today()}.md"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_markdown(report))
    target.with_suffix(".json").write_text(_json.dumps(report, indent=2, default=str))
    for s in report["strategies"]:
        m = s["pooled"]
        typer.echo(
            f"  {s['key']:24} {s['verdict']:9} trades={m['n_trades']:4d} "
            f"exp={m['expectancy_r']:+.3f}R ci_low={s['ci_expectancy_r']['low']:+.3f}R "
            f"2x={s['stress_expectancy_r']:+.3f}R"
        )
    typer.echo(f"Sealed from {report['sealed_from']} (not evaluated). Report: {target}")
    typer.echo("Research only — no order was placed.")


@fx_app.command("sealed-test")
def fx_sealed_test(
    strategy: Annotated[str, typer.Argument(help="Strategy key, e.g. fx_zfade_20.")],
    confirm: Annotated[
        bool,
        typer.Option("--confirm", help="Required: the sealed year can be evaluated only once."),
    ] = False,
    pairs: Annotated[
        str | None, typer.Option(help="Comma-separated pairs (default: FOREX_PAIRS).")
    ] = None,
) -> None:
    """ONE-TIME sealed-year test of a strategy that passes development.
    Refused if the strategy is not DEV_PASS or already used its sealed year."""
    from signalforge.config import get_settings
    from signalforge.data.forex import parse_pairs
    from signalforge.db.session import session_scope
    from signalforge.research.fx.sealed import (
        SealedTestRefused,
        describe,
        existing,
        run_sealed_test,
    )

    with session_scope(write=True) as session:
        prior = existing(session, "fx", strategy)
        if prior is not None:
            typer.echo(describe(prior))
            typer.echo("Already evaluated; the sealed year is used. Research only.")
            return
        if not confirm:
            typer.echo("Refusing without --confirm: the sealed year can be evaluated only once.")
            raise typer.Exit(2)
        try:
            row = run_sealed_test(
                session,
                "fx",
                strategy,
                parse_pairs(pairs if pairs is not None else get_settings().forex_pairs),
            )
        except SealedTestRefused as exc:
            typer.echo(f"Refused: {exc}")
            raise typer.Exit(1) from None
        typer.echo(describe(row))
    typer.echo("Research only — no order was placed.")


@crypto_app.command("sealed-test")
def crypto_sealed_test(
    strategy: Annotated[str, typer.Argument(help="Strategy key, e.g. crypto_zfade_20.")],
    confirm: Annotated[
        bool,
        typer.Option("--confirm", help="Required: the sealed year can be evaluated only once."),
    ] = False,
    pairs: Annotated[
        str | None, typer.Option(help="Comma-separated pairs (default: CRYPTO_PAIRS).")
    ] = None,
) -> None:
    """ONE-TIME sealed-year test of a strategy that passes development.
    Refused if the strategy is not DEV_PASS or already used its sealed year."""
    from signalforge.config import get_settings
    from signalforge.data.forex import CRYPTO, parse_pairs
    from signalforge.db.session import session_scope
    from signalforge.research.fx.sealed import (
        SealedTestRefused,
        describe,
        existing,
        run_sealed_test,
    )

    with session_scope(write=True) as session:
        prior = existing(session, "crypto", strategy)
        if prior is not None:
            typer.echo(describe(prior))
            typer.echo("Already evaluated; the sealed year is used. Research only.")
            return
        if not confirm:
            typer.echo("Refusing without --confirm: the sealed year can be evaluated only once.")
            raise typer.Exit(2)
        try:
            row = run_sealed_test(
                session,
                "crypto",
                strategy,
                parse_pairs(pairs if pairs is not None else get_settings().crypto_pairs, CRYPTO),
            )
        except SealedTestRefused as exc:
            typer.echo(f"Refused: {exc}")
            raise typer.Exit(1) from None
        typer.echo(describe(row))
    typer.echo("Research only — no order was placed.")


crypto_paper_app = typer.Typer(
    help="SIMULATED crypto paper book for a SEALED_PASS strategy. No broker; no order is placed."
)
crypto_app.add_typer(crypto_paper_app, name="paper")


@crypto_paper_app.command("start")
def crypto_paper_start(
    strategy: Annotated[str, typer.Argument(help="e.g. crypto_donchian_55")],
    confirm: Annotated[bool, typer.Option("--confirm", help="Required.")] = False,
) -> None:
    """Create the prospective paper book (start date = today UTC, 180-day
    observation). Refused unless the strategy version is SEALED_PASS."""
    from signalforge.db.session import session_scope
    from signalforge.paper.crypto_ledger import PaperBookRefused, start_book

    if not confirm:
        typer.echo("Refusing without --confirm: the start date is fixed once set.")
        raise typer.Exit(2)
    with session_scope(write=True) as session:
        try:
            book = start_book(session, strategy)
        except PaperBookRefused as exc:
            typer.echo(f"Refused: {exc}")
            raise typer.Exit(1) from None
        typer.echo(
            f"Paper book {book.strategy_key} {book.version}: {', '.join(book.pairs)}; "
            f"trades entered after {book.start_date}; observation to {book.observation_end}."
        )
    typer.echo("SIMULATED — no order was placed; no broker is connected.")


@crypto_paper_app.command("run")
def crypto_paper_run(strategy: Annotated[str, typer.Argument()] = "crypto_donchian_55") -> None:
    """Run one cycle now (the scheduler does this daily when CRYPTO_PAPER_ENABLED)."""
    from signalforge.db.session import session_scope
    from signalforge.paper.crypto_ledger import PaperBookRefused, run_cycle

    with session_scope(write=True) as session:
        try:
            rep = run_cycle(session, strategy)
        except PaperBookRefused as exc:
            typer.echo(f"Refused: {exc}")
            raise typer.Exit(1) from None
    typer.echo(f"Cycle through {rep.last_bar}:")
    for label, items in (
        ("opened", rep.opened),
        ("closed", rep.closed),
        ("marked", rep.marked),
        ("NOT opened (kill switch)", rep.skipped_open_kill_switch),
        ("DIVERGENCE", rep.divergences),
    ):
        for it in items:
            typer.echo(f"  {label}: {it}")
    typer.echo("SIMULATED — no order was placed; no broker is connected.")


@crypto_paper_app.command("status")
def crypto_paper_status(
    strategy: Annotated[str, typer.Argument()] = "crypto_donchian_55",
) -> None:
    """Show the paper book: open trades, closed record vs the sealed result."""
    from signalforge.db.session import session_scope
    from signalforge.paper.crypto_ledger import status as _status

    with session_scope() as session:
        st = _status(session, strategy)
    if st.get("book") is None and "start_date" not in st:
        typer.echo(f"No paper book for {strategy}.")
        return
    typer.echo(
        f"{st['strategy_key']} {st['version']} ({st['paper_version']}): "
        f"from {st['start_date']} to {st['observation_end']}, bars through {st['last_bar_date']}"
    )
    exp = st["expectancy_r"]
    typer.echo(
        f"  closed {st['closed_trades']}, expectancy "
        f"{'n/a' if exp is None else f'{exp:+.3f}R'} (sealed {st['sealed_expectancy_r']:+.3f}R), "
        f"total {st['total_r']:+.2f}R (illustrative ${st['illustrative_usd']:+,.0f})"
    )
    for o in st["open"]:
        mark = "n/a" if o["mark_r"] is None else f"{o['mark_r']:+.2f}R"
        typer.echo(
            f"  OPEN {o['pair']} {o['direction']} since {o['entry_date']} "
            f"@ {o['entry_price']} stop {o['stop_price']} mark {mark}"
        )
    for d in st["divergences"]:
        typer.echo(f"  DIVERGENCE {d}")
    typer.echo(st["notice"])


@data_app.command("crypto-hourly-ingest")
def data_crypto_hourly_ingest(
    since: Annotated[str, typer.Option(help="First UTC day to fetch (YYYY-MM-DD).")] = "2017-01-01",
    until: Annotated[str, typer.Option(help="Last UTC day (default: last complete hour).")] = "",
    pairs: Annotated[
        str | None, typer.Option(help="Comma-separated pairs (default: CRYPTO_PAIRS).")
    ] = None,
) -> None:
    """Backfill / top up hourly crypto bars into crypto_bar_intraday, one
    request per pair-month (months already complete are skipped). Research only."""
    from signalforge.config import get_settings
    from signalforge.data.crypto_intraday import ingest_crypto_hourly
    from signalforge.data.forex import CRYPTO, parse_pairs
    from signalforge.db.session import session_scope

    chosen = parse_pairs(pairs if pairs is not None else get_settings().crypto_pairs, CRYPTO)
    with session_scope(write=True) as session:
        rep = ingest_crypto_hourly(
            session,
            chosen,
            start=date.fromisoformat(since),
            end=date.fromisoformat(until) if until else None,
        )
    typer.echo(f"Hourly crypto bars {rep.start}..{rep.end} (UTC, completed hours only):")
    for pr in rep.pairs:
        typer.echo(
            f"  {pr.pair:8} requests={pr.requests} +{pr.written} written, "
            f"{pr.skipped_existing} existing, {pr.missing_hours} missing hours, "
            f"{len(pr.failed_months)} failed months"
        )
        for f in pr.failed_months[:5]:
            typer.echo(f"    ! {f}")
    typer.echo("Research data only — no order was placed.")
    if any(pr.failed_months for pr in rep.pairs):
        raise typer.Exit(1)


@crypto_app.command("research-hourly")
def crypto_research_hourly(
    pairs: Annotated[
        str | None, typer.Option(help="Comma-separated pairs (default: CRYPTO_PAIRS).")
    ] = None,
    out: Annotated[
        Path | None,
        typer.Option(help="Report path (default: <data dir>/research/crypto/)."),
    ] = None,
) -> None:
    """Evaluate the pre-registered CRYPTO-H1 hourly rules on the development
    window. The sealed final year is never evaluated here. Research only."""
    import json as _json

    from signalforge.config import get_settings
    from signalforge.config.paths import data_dir
    from signalforge.data.forex import CRYPTO, parse_pairs
    from signalforge.db.session import session_scope
    from signalforge.research.fx.harness import render_markdown
    from signalforge.research.fx.hourly import run_crypto_hourly_research

    chosen = parse_pairs(pairs if pairs is not None else get_settings().crypto_pairs, CRYPTO)
    with session_scope() as session:
        report = run_crypto_hourly_research(session, chosen)
    target = out or (
        data_dir() / "research" / "crypto" / f"crypto_hourly_{report['version']}_{date.today()}.md"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_markdown(report))
    target.with_suffix(".json").write_text(_json.dumps(report, indent=2, default=str))
    for s in report["strategies"]:
        m = s["pooled"]
        typer.echo(
            f"  {s['key']:30} {s['verdict']:9} trades={m['n_trades']:5d} "
            f"exp={m['expectancy_r']:+.3f}R ci_low={s['ci_expectancy_r']['low']:+.3f}R "
            f"2x={s['stress_expectancy_r']:+.3f}R"
        )
    typer.echo(f"Sealed from {report['sealed_from']} (not evaluated). Report: {target}")
    typer.echo("Research only — no order was placed.")


@providers_app.command("verify")
def providers_verify(
    no_store: Annotated[
        bool, typer.Option(help="Skip persisting the run to entitlement_check.")
    ] = False,
) -> None:
    """Probe every concrete endpoint per subscription and record the result.

    Records only: subscription / feed / endpoint / source / timestamp / HTTP
    status / available / latency category / error category. Never prints, logs,
    caches, or commits an API key or the Discord webhook URL.
    """
    import uuid

    from signalforge.data.entitlements import verify_entitlements
    from signalforge.db.models import EntitlementCheck
    from signalforge.db.session import session_scope

    report = verify_entitlements()
    batch = uuid.uuid4().hex[:12]

    last_sub = ""
    for c in report.checks:
        if c.subscription != last_sub:
            typer.secho(f"\n[{c.subscription}]", fg=typer.colors.CYAN)
            last_sub = c.subscription
        mark = "OK  " if c.available else "----"
        colour = typer.colors.GREEN if c.available else typer.colors.YELLOW
        typer.secho(
            f"  {mark} {c.feed:28} {c.http_status or 'n/a'!s:5} "
            f"lat={c.latency_category:10} err={c.error_category:14} {c.endpoint}",
            fg=colour,
        )
        if c.detail:
            typer.echo(f"       {c.detail}")
    typer.secho(f"\n[discord] {report.discord_note}", fg=typer.colors.CYAN)

    if not no_store:
        with session_scope(write=True) as session:
            for c in report.checks:
                session.add(
                    EntitlementCheck(
                        batch_id=batch,
                        subscription=c.subscription,
                        feed=c.feed,
                        endpoint=c.endpoint,
                        source=c.source,
                        checked_at=datetime.fromisoformat(c.checked_at),
                        http_status=c.http_status,
                        available=c.available,
                        latency_category=c.latency_category,
                        error_category=c.error_category,
                        detail=c.detail[:300],
                    )
                )
        typer.echo(f"\nrecorded {len(report.checks)} checks (batch {batch}) to entitlement_check.")
    typer.echo(
        "Unavailable feeds are treated as unavailable — access is never inferred. "
        "Research signal only — no order was placed."
    )


options_app = typer.Typer(
    help="Options data + education simulators (execution only via the armed execution layer)."
)
app.add_typer(options_app, name="options")
options_paper_app = typer.Typer(
    help=(
        "The SIMULATED options paper account (D3 / I-O6): a separate account, separate "
        "tables, a collateral ledger, and a second guard that is OFF by default."
    )
)
app.add_typer(options_paper_app, name="options-paper")
news_app = typer.Typer(help="Licensed read-only news (never drives a recommendation).")
app.add_typer(news_app, name="news")


@options_app.command("ingest")
def options_ingest_cmd(
    underlyings: Annotated[
        str, typer.Option(help="Comma-separated; default: configured set.")
    ] = "",
    exp_min_days: Annotated[int, typer.Option()] = 14,
    exp_max_days: Annotated[int, typer.Option()] = 120,
    strike_pct: Annotated[float, typer.Option(help="+/- band around the reference price.")] = 0.25,
) -> None:
    """Fetch contract metadata + a delayed chain snapshot for a small liquid set."""
    ensure_not_engaged()
    from sqlalchemy import select

    from signalforge.config import get_settings
    from signalforge.data.adapters.massive_options import MassiveOptionsAdapter
    from signalforge.data.options_ingest import (
        ingest_options_for_underlying,
        record_snapshot_ingestion_run,
    )
    from signalforge.data.series import PriceSeries
    from signalforge.db.models import Instrument
    from signalforge.db.session import session_scope

    s = get_settings()
    us = [x.strip().upper() for x in underlyings.split(",") if x.strip()] or list(
        s.research.options.underlyings
    )
    adapter = MassiveOptionsAdapter()
    from datetime import date as _d

    with session_scope(write=True) as session:
        covs = []
        for u in us:
            ref = None
            inst = session.scalar(select(Instrument).where(Instrument.symbol == u))
            if inst is not None:
                series = PriceSeries.load(session, u, _d(2000, 1, 1), _d.today())
                ref = float(series.close[-1]) if len(series) else None
            cov = ingest_options_for_underlying(
                session,
                adapter,
                u,
                expiration_min_days=exp_min_days,
                expiration_max_days=exp_max_days,
                strike_pct=strike_pct,
                reference_price=ref,
            )
            covs.append(cov)
            if cov.error:
                typer.secho(f"  {u}: {cov.error}", fg=typer.colors.RED)
                continue
            typer.secho(
                f"  {u}: {cov.contracts_written} new contracts ({cov.contracts_seen} seen), "
                f"{cov.snapshots_written} delayed snapshots "
                f"(greeks {cov.greeks_present}, iv {cov.iv_present}); "
                f"exp {cov.expirations[:1]}..{cov.expirations[-1:]} "
                f"strikes {cov.strike_min}-{cov.strike_max}",
                fg=typer.colors.GREEN,
            )
        if covs:
            run = record_snapshot_ingestion_run(session, adapter, covs)
            typer.echo(f"  ingestion_run #{run.id} [{run.status}] recorded")
    typer.echo(
        "Delayed data (>=15 min). Education/simulation only. "
        "Research signal only — no order was placed."
    )


@options_app.command("backfill")
def options_backfill_cmd(
    underlyings: Annotated[
        str, typer.Option(help="Comma-separated; default: configured set.")
    ] = "",
    since: Annotated[str, typer.Option(help="YYYY-MM-DD; default: until - lookback-days.")] = "",
    until: Annotated[str, typer.Option(help="YYYY-MM-DD; default: today.")] = "",
    lookback_days: Annotated[
        int,
        typer.Option(
            help=(
                "Window depth when --since is not given. The window is NEVER "
                "re-clamped to it afterwards: --since reaches the run unchanged."
            )
        ),
    ] = 0,
    max_contracts: Annotated[int, typer.Option(help="Override contracts-per-underlying cap.")] = 0,
    max_expirations: Annotated[
        int, typer.Option(help="Override expirations-per-underlying cap (narrows the range).")
    ] = 0,
    strike_band: Annotated[
        float, typer.Option(help="Override the +/- ATM strike band, e.g. 0.05 for +/-5%.")
    ] = 0.0,
    max_total_bars: Annotated[int, typer.Option(help="Override the total-bar ceiling.")] = 0,
    resume: Annotated[int, typer.Option(help="Resume an existing ingestion_run id.")] = 0,
    validate: Annotated[bool, typer.Option(help="Run data-validation after the backfill.")] = True,
) -> None:
    """Bounded historical options-aggregates backfill for the approved liquid set.

    HISTORICAL settled bars only — never live/delayed. Storage caps are enforced
    before any per-contract fetch; whatever a cap drops is recorded on the run.
    """
    ensure_not_engaged()
    from datetime import date as _d

    from signalforge.config import get_settings
    from signalforge.data.adapters.massive_options import MassiveOptionsAdapter
    from signalforge.data.options_backfill import BackfillCaps, backfill_option_aggregates
    from signalforge.data.validate import validate_option_aggregates
    from signalforge.db.session import session_scope

    s = get_settings()
    opt = s.research.options
    us = [x.strip().upper() for x in underlyings.split(",") if x.strip()] or list(opt.underlyings)
    caps = BackfillCaps.from_config(opt)
    if lookback_days:
        caps = replace(caps, lookback_days=lookback_days)
    if max_contracts:
        caps = replace(caps, contracts_per_underlying=max_contracts)
    if max_expirations:
        caps = replace(caps, expirations_per_underlying=max_expirations)
    if strike_band:
        caps = replace(caps, strike_pct_band=strike_band)
    if max_total_bars:
        caps = replace(caps, max_total_bars=max_total_bars)
    end = _d.fromisoformat(until) if until else _d.today()
    start = _d.fromisoformat(since) if since else end - timedelta(days=caps.lookback_days)

    adapter = MassiveOptionsAdapter()
    with session_scope(write=True) as session:
        run = backfill_option_aggregates(
            session,
            adapter,
            us,
            start=start,
            end=end,
            caps=caps,
            resume_run_id=resume or None,
        )
        run_id = run.id
        typer.secho(
            f"run #{run_id} [{run.status}] {run.coverage_first}..{run.coverage_last} "
            f"bars_written={run.bars_written} skipped={run.bars_skipped}",
            fg=typer.colors.GREEN if run.status == "ok" else typer.colors.YELLOW,
        )
        for u, d in (run.gaps_json or {}).items():
            typer.echo(
                f"  {u}: {d.get('contracts', 0)} contracts, {d.get('bars', 0)} bars, "
                f"dropped_by_cap={d.get('dropped_by_cap', 0)}, exp={d.get('expirations', [])}"
            )
        if run.symbols_failed:
            for k, v in run.symbols_failed.items():
                typer.secho(f"  FAIL {k}: {v}", fg=typer.colors.RED)
        if validate:
            res = validate_option_aggregates(
                session, us, start=start, end=end, caps=caps, persist=True
            )
            mark = "PASS" if res.passed else "FAIL"
            colour = typer.colors.GREEN if res.passed else typer.colors.RED
            typer.secho(f"validation: {mark}", fg=colour)
            for c in res.checks:
                if not c.passed:
                    typer.secho(f"  - {c.name}: {c.detail}", fg=typer.colors.RED)
    typer.echo(
        "HISTORICAL settled bars only — never live. Education/simulation only. "
        "Research signal only — no order was placed."
    )


@options_app.command("cycle-backfill")
def options_cycle_backfill_cmd(
    underlyings: Annotated[
        str, typer.Option(help="Comma-separated; default: configured set.")
    ] = "",
    since: Annotated[str, typer.Option(help="YYYY-MM-DD window start (required).")] = "",
    until: Annotated[str, typer.Option(help="YYYY-MM-DD window end (required).")] = "",
    lookback_days: Annotated[int, typer.Option(help="Window depth when --since is not given.")] = 0,
    max_total_bars: Annotated[int, typer.Option(help="Override the total-bar ceiling.")] = 0,
    max_cycles: Annotated[
        int, typer.Option(help="Stop this PASS after N (underlying, cycle) units. 0 = no bound.")
    ] = 0,
    max_minutes: Annotated[
        float,
        typer.Option(
            help=(
                "Stop this PASS after N minutes, at a cycle boundary (so it may overrun "
                "by up to one cycle). 0 = no bound."
            )
        ),
    ] = 0.0,
    to_database: Annotated[
        str,
        typer.Option(
            help=(
                "Write to this SQLite file instead of the configured database. It must "
                "already exist: take a file-level copy of the live DB with the worker "
                "stopped, run against the copy, then `options merge --from` it back."
            )
        ),
    ] = "",
    resume: Annotated[int, typer.Option(help="Resume an existing ingestion_run id.")] = 0,
    dry_run: Annotated[
        bool, typer.Option(help="Print the exact request plan and fetch nothing.")
    ] = False,
    yes: Annotated[
        bool, typer.Option(help="Skip the confirmation prompt (use in scheduled windows).")
    ] = False,
) -> None:
    """Per-(underlying, monthly cycle) historical options backfill.

    Every cycle is centred on its OWN point-in-time reference close and selected
    by the pre-registered moneyness ladder against that single expiry's true
    vendor strike set. Anything the run cannot serve is excluded and counted by
    reason — never silently shortened.

    This is a multi-day job (~29,000 requests, ~99 hours at 12.1 s pacing for the
    full 24-underlying window), so it is built to be run in pieces:

    * ``--dry-run`` prints the exact request plan and touches no network;
    * ``--max-cycles`` / ``--max-minutes`` bound ONE PASS, ending it at a
      committed cycle boundary so a nightly window never overlaps the live
      17:30-19:00 ET EOD / universe / grid jobs;
    * ``--resume <run id>`` re-enters the run and skips what is already covered;
    * ``--to-database`` runs the whole thing against a copy of the database, to
      be merged back with ``options merge`` in one short pass.

    Each (underlying, cycle) is committed on its own with the write lock held
    only for the store, so the run is safe beside the probation worker and a
    kill switch costs at most the cycle in flight.
    """
    ensure_not_engaged()
    from datetime import date as _d

    from signalforge.config import get_settings
    from signalforge.config.research import OptionsEvaluationConfig
    from signalforge.data.adapters.massive_options import MassiveOptionsAdapter
    from signalforge.data.options_backfill import (
        CycleBackfillCaps,
        RunBounds,
        backfill_option_cycles,
        completed_cycle_units,
        coverage_summary,
        plan_cycle_backfill,
    )
    from signalforge.db.models import IngestionRun
    from signalforge.db.session import external_session_scope, session_scope
    from signalforge.worker_lock import worker_lock_holder

    s = get_settings()
    opt = s.research.options
    us = [x.strip().upper() for x in underlyings.split(",") if x.strip()] or list(opt.underlyings)
    end = _d.fromisoformat(until) if until else _d.today()
    start = (
        _d.fromisoformat(since)
        if since
        else end - timedelta(days=lookback_days or opt.backfill_lookback_days)
    )
    caps = CycleBackfillCaps.from_config(opt, window_start=start, window_end=end)
    if max_total_bars:
        caps = replace(caps, max_total_bars=max_total_bars)
    bounds = RunBounds(max_cycles=max_cycles or None, max_minutes=max_minutes or None)

    adapter = MassiveOptionsAdapter()
    scope = (
        external_session_scope(to_database, write=True)
        if to_database
        else session_scope(write=True)
    )
    try:
        with scope as session:
            units_done = 0
            if resume:
                prior = session.get(IngestionRun, resume)
                if prior is None:
                    typer.secho(f"ingestion_run {resume} not found", fg=typer.colors.RED)
                    raise typer.Exit(code=1)
                units_done = completed_cycle_units(prior)
            plan = plan_cycle_backfill(
                us,
                caps=caps,
                pacing_s=adapter.min_request_spacing_s,
                units_done=units_done,
            )
            _print_backfill_plan(plan, bounds=bounds, to_database=to_database)
            if dry_run:
                typer.echo("DRY RUN — no request was issued and nothing was written.")
                return
            if not to_database:
                holder = worker_lock_holder()
                if holder:
                    typer.secho(
                        f"the scheduler worker is running ({holder}) against this database. "
                        "Each cycle commits in its own short write transaction, so this is "
                        "survivable — but the designed route for a multi-day run is "
                        "--to-database against a copy, merged back afterwards.",
                        fg=typer.colors.YELLOW,
                    )
            if not yes:
                typer.confirm("Start fetching now?", abort=True)
            run = backfill_option_cycles(
                session,
                adapter,
                us,
                caps=caps,
                options_config_hash=OptionsEvaluationConfig().options_config_hash,
                resume_run_id=resume or None,
                bounds=bounds,
            )
            _print_options_coverage(coverage_summary(run))
    except FileNotFoundError as exc:
        # --to-database names a file that is not there. SQLite would create an
        # empty one and the run would spend days excluding every cycle.
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from None
    typer.echo(
        "HISTORICAL settled bars only — never live. Education/simulation only. "
        "Research signal only — no order was placed."
    )


def _print_backfill_plan(plan: BackfillRequestPlan, *, bounds: RunBounds, to_database: str) -> None:
    """The exact request plan: underlyings, cycles, ladder, requests, hours.

    Counts and identities only, and an explicit upper bound rather than an
    estimate — the ladder de-duplicates downward, an excluded cycle costs no
    aggregate calls, and the adapter may retry a request up to five times.
    """
    typer.secho(
        f"plan: {len(plan.underlyings)} underlyings x {len(plan.cycles)} cycles "
        f"= {plan.units_total} units ({plan.units_done} already settled, "
        f"{plan.units_remaining} to go)",
        fg=typer.colors.CYAN,
    )
    typer.echo(
        f"  window {plan.window_start}..{plan.window_end} {plan.cycle_rule}; "
        f"basis={plan.strike_listing_basis}"
    )
    typer.echo(f"  underlyings: {', '.join(plan.underlyings)}")
    if plan.cycles:
        typer.echo(
            f"  cycles: {plan.cycles[0]} .. {plan.cycles[-1]} "
            f"({len(plan.cycles)} third-Friday expiries)"
        )
    typer.echo(
        f"  ladder: {plan.ladder_id}, {plan.ladder_rungs} rungs x {len(plan.rights)} rights "
        f"= <={plan.contracts_per_cycle_max} contracts/cycle"
    )
    typer.echo(
        f"  requests: {plan.listing_requests:,} listing "
        f"({plan.listing_pages_assumed} page(s)/cycle, ASSUMED) + "
        f"{plan.aggregate_requests:,} aggregate = {plan.requests_total:,} total"
    )
    typer.echo(
        f"  pacing {plan.pacing_s}s => {plan.hours_at_pacing:.1f} h "
        f"({plan.hours_at_pacing / 24:.2f} days) serial, no-retry lower bound"
    )
    typer.echo(
        f"  sessions/cycle {plan.sessions_per_cycle_min}-{plan.sessions_per_cycle_max} "
        f"(mean {plan.sessions_per_cycle_mean:.2f}) => <={plan.bars_max:,} bars, "
        f"{plan.bars_fraction_of_ceiling:.1%} of the {plan.max_total_bars:,} ceiling"
    )
    if bounds.max_cycles is not None or bounds.max_minutes is not None:
        typer.echo(
            f"  this PASS is bounded: max_cycles={bounds.max_cycles}, "
            f"max_minutes={bounds.max_minutes} (checked between cycles, so it may "
            "overrun by one)"
        )
    typer.echo(f"  destination: {to_database or 'the configured database'}")


@options_app.command("coverage-report")
def options_coverage_report_cmd(
    run_id: Annotated[int, typer.Option("--run", help="ingestion_run id of a cycle backfill.")],
) -> None:
    """COVERAGE SUMMARY ONLY — counts and completeness, nothing else.

    This is the one thing a backfill may expose before the strategy
    pre-registration is committed. No option price, IV, greek, return, credit or
    P&L value — and no summary statistic over any of them — is printed, and none
    can be: the summary type has no field that could hold one, which the suite
    asserts mechanically rather than by review.
    """
    from signalforge.data.options_backfill import OptionsCoverageSummary, coverage_summary
    from signalforge.db.models import IngestionRun
    from signalforge.db.session import session_scope

    OptionsCoverageSummary.assert_price_free()
    with session_scope() as session:
        run = session.get(IngestionRun, run_id)
        if run is None:
            typer.secho(f"ingestion_run {run_id} not found", fg=typer.colors.RED)
            raise typer.Exit(code=1)
        _print_options_coverage(coverage_summary(run))
    typer.echo(
        "Counts and completeness only. No price, IV, greek, return, credit or P&L "
        "value is reported here, and none may be inspected until the strategy "
        "pre-registration is committed."
    )


def _print_options_coverage(cov: OptionsCoverageSummary) -> None:
    """Render an ``OptionsCoverageSummary``. Counts, fractions, dates, identities."""
    typer.secho(
        f"run #{cov.run_id} [{cov.status}] {cov.window_start}..{cov.window_end} "
        f"{cov.cycle_rule} {cov.ladder_id} basis={cov.strike_listing_basis}",
        fg=typer.colors.GREEN if cov.status == "ok" else typer.colors.YELLOW,
    )
    typer.echo(
        f"  cycles: {cov.cycles_covered}/{cov.cycles_total} covered "
        f"({cov.cycles_bracket_fraction:.3f}), {cov.cycles_excluded} excluded"
    )
    for reason, n in cov.exclusions_by_reason:
        typer.echo(f"    - {reason}: {n}")
    typer.echo(
        f"  contracts: {cov.contracts_selected} selected, {cov.contracts_fetched} fetched; "
        f"shares_per_contract refusals {cov.shares_per_contract_refusals}"
    )
    typer.echo(
        f"  bars: {cov.bars_written} written, {cov.bars_skipped} skipped; "
        f"continuity {cov.bar_continuity_fraction:.3f} of {cov.sessions_expected} expected"
    )
    typer.echo(
        f"  ceiling {cov.max_total_bars:,} (raised from {cov.max_total_bars_prior:,}, "
        f"decision 6); pacing {cov.pacing_s}s; earliest available "
        f"{cov.earliest_available_date}"
    )
    if cov.stopped_reason:
        typer.secho(
            f"  pass ended early [{cov.status}]: {cov.stopped_reason} — "
            f"resume with --resume {cov.run_id}",
            fg=typer.colors.YELLOW,
        )
    if cov.underlyings_failed:
        typer.secho(f"  retryable: {', '.join(cov.underlyings_failed)}", fg=typer.colors.YELLOW)


@options_app.command("merge")
def options_merge_cmd(
    from_database: Annotated[
        str, typer.Option("--from", help="SQLite file a bulk options backfill wrote to.")
    ],
    dry_run: Annotated[
        bool, typer.Option(help="Do the identical work and roll it back; report the counts.")
    ] = False,
    allow_worker_running: Annotated[
        bool, typer.Option(help="Merge even while the scheduler worker holds its lock.")
    ] = False,
) -> None:
    """Merge a bulk options database file into the configured one, idempotently.

    ``INSERT OR IGNORE`` on each table's natural key, so re-running inserts
    nothing and reports it; ``ingestion_run`` rows are re-keyed with their
    original id, source file and merge time recorded, so the bulk run's
    provenance survives the merge and stays traceable to the file it was built
    in. Equity tables are never copied back — the bulk file is a copy of this
    one, so its instrument and bar rows came from here.

    Run it with the worker stopped: this holds the SQLite write lock for the
    whole pass, which is far longer than the 5 s any worker job will wait.
    """
    ensure_not_engaged()
    from signalforge.data.options_merge import MergeError, merge_options_from_file
    from signalforge.db.session import get_engine
    from signalforge.worker_lock import worker_lock_holder

    holder = worker_lock_holder()
    if holder and not allow_worker_running and not dry_run:
        typer.secho(
            f"the scheduler worker is running ({holder}). A bulk merge holds the SQLite "
            "write lock for the whole pass — far longer than the 5 s busy timeout its jobs "
            "wait — so stop the worker first, or pass --allow-worker-running deliberately.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)
    try:
        result = merge_options_from_file(get_engine(), from_database, dry_run=dry_run)
    except (MergeError, FileNotFoundError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from None
    _print_merge_result(result)
    typer.echo("Counts and identities only. Research signal only — no order was placed.")


def _print_merge_result(result: MergeResult) -> None:
    typer.secho(
        f"{'DRY RUN — rolled back' if result.dry_run else 'merged'}: {result.source_path} "
        f"-> {result.destination_url}",
        fg=typer.colors.YELLOW if result.dry_run else typer.colors.GREEN,
    )
    for t in result.tables:
        typer.echo(
            f"  {t.table}: {t.inserted:,} inserted, {t.already_present:,} already present "
            f"of {t.source_rows:,} (key {'+'.join(t.natural_key)})"
        )
    for src_id, new_id in result.runs_merged:
        typer.echo(f"  ingestion_run #{src_id} (bulk) -> #{new_id} (here)")
    if result.runs_already_merged:
        ids = ", ".join(f"#{i}" for i in result.runs_already_merged)
        typer.echo(f"  ingestion_run already merged, left alone: {ids}")
    for table, why in result.not_merged:
        typer.echo(f"  not merged — {table}: {why}")


@options_app.command("corp-actions")
def options_corp_actions_cmd(
    symbols: Annotated[
        str, typer.Option(help="Comma-separated; default: configured underlyings.")
    ] = "",
    resume: Annotated[int, typer.Option(help="Resume an existing ingestion_run id.")] = 0,
) -> None:
    """Ingest declared dividends + executed splits (the rank-1 source for ``q``).

    The options pricing path takes a continuous dividend yield defaulted to 0.0,
    and at q=0 a put-selling result is biased in its own favour. Decision 11
    sources and records q rather than restricting the underlying set; gate 0.g
    fails any run that used the default.
    """
    ensure_not_engaged()
    from signalforge.config import get_settings
    from signalforge.data.adapters.massive_options import MassiveOptionsAdapter
    from signalforge.data.options_corporate_actions import ingest_dividends_and_splits
    from signalforge.db.session import session_scope

    s = get_settings()
    syms = [x.strip().upper() for x in symbols.split(",") if x.strip()] or list(
        s.research.options.underlyings
    )
    adapter = MassiveOptionsAdapter()
    with session_scope(write=True) as session:
        run = ingest_dividends_and_splits(session, adapter, syms, resume_run_id=resume or None)
        typer.secho(
            f"run #{run.id} [{run.status}] rows_written={run.bars_written} "
            f"skipped={run.bars_skipped}",
            fg=typer.colors.GREEN if run.status == "ok" else typer.colors.YELLOW,
        )
        for sym, d in (run.gaps_json or {}).items():
            typer.echo(
                f"  {sym}: {d.get('dividends_written', 0)} dividends "
                f"({d.get('dividends_seen', 0)} seen), {d.get('splits_written', 0)} splits "
                f"({d.get('splits_seen', 0)} seen)"
            )
        for k, v in (run.symbols_failed or {}).items():
            typer.secho(f"  FAIL {k}: {v}", fg=typer.colors.RED)
    typer.echo("Reference data only. Research signal only — no order was placed.")


@options_app.command("q-series")
def options_q_series_cmd(
    symbols: Annotated[
        str, typer.Option(help="Comma-separated; default: configured underlyings.")
    ] = "",
    since: Annotated[str, typer.Option(help="YYYY-MM-DD; first session to derive.")] = "",
    until: Annotated[str, typer.Option(help="YYYY-MM-DD; last session (default: today).")] = "",
) -> None:
    """Derive the per-(underlying, session) trailing dividend yield ``q`` series.

    Pure arithmetic over the stored ``dividend_event`` rows and the stored daily
    close — run ``options corp-actions`` first. A session with no dividend
    history in its trailing window gets NO row (never 0.0), and the
    short-vertical strategy takes no entry on a session without a row.
    """
    ensure_not_engaged()
    from signalforge.config import get_settings
    from signalforge.data.options_corporate_actions import derive_dividend_yield_series
    from signalforge.db.session import session_scope
    from signalforge.scheduler import other_live_worker
    from signalforge.worker_lock import worker_lock_holder

    s = get_settings()
    syms = [x.strip().upper() for x in symbols.split(",") if x.strip()] or list(
        s.research.options.underlyings
    )
    end = date.fromisoformat(until) if until else date.today()
    start = date.fromisoformat(since) if since else end - timedelta(days=365 * 8)
    if start > end:
        typer.secho(f"--since {start} is after --until {end}", fg=typer.colors.RED)
        raise typer.Exit(code=2)
    # The same refusal `options evaluate-promotion --confirm` makes, plus the
    # heartbeat row for a worker on another host/container sharing this database:
    # this command rewrites the series gate 0.g and the gate-5 cache key read.
    holder = worker_lock_holder()
    live = other_live_worker()
    if holder or live:
        why = f"the scheduler worker holds the write lock (holder: {holder})" if holder else live
        typer.secho(
            f"REFUSED: {why}. Deriving the q series opens write transactions against the "
            "worker's database; stop the worker first (docs/SQLITE_CONCURRENCY.md). "
            "Nothing was derived and no row was written.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=2)
    # No network I/O inside this scope, and each underlying commits in its own
    # short write transaction with the lock-retry helper (per-unit rule,
    # docs/SQLITE_CONCURRENCY.md) rather than one write lock for the whole pass.
    with session_scope(write=True) as session:
        run = derive_dividend_yield_series(session, syms, start, end, commit_per_symbol=True)
        typer.secho(
            f"run #{run.id} [{run.status}] sessions_written={run.bars_written} "
            f"unchanged={run.bars_skipped} coverage {run.coverage_first}..{run.coverage_last}",
            fg=typer.colors.GREEN if run.status == "ok" else typer.colors.YELLOW,
        )
        for sym, d in (run.gaps_json or {}).items():
            typer.echo(
                f"  {sym}: {d.get('sessions_written', 0)} written, "
                f"{d.get('sessions_unchanged', 0)} unchanged, "
                f"{d.get('sessions_without_history', 0)} sessions without dividend history "
                f"({d.get('first_session')}..{d.get('last_session')})"
            )
        for k, v in (run.symbols_failed or {}).items():
            typer.secho(f"  FAIL {k}: {v}", fg=typer.colors.RED)
    typer.echo("Reference data only. Research signal only — no order was placed.")


@options_app.command("snapshot")
def options_snapshot_cmd(
    symbols: Annotated[
        str,
        typer.Option(help="Comma-separated underlyings the snapshot holds, e.g. SPY,QQQ,IWM."),
    ],
    since: Annotated[str, typer.Option(help="YYYY-MM-DD; the backfill window start.")],
    until: Annotated[str, typer.Option(help="YYYY-MM-DD; the backfill window end.")],
    key: Annotated[
        str,
        typer.Option(
            help=(
                "DataSnapshot key. Default: the canonical "
                "options_<set>_<provider>_<since>_<until>_<scopehash10>. A key given by hand "
                "must carry the same 10-character scope hash (D3 §1 item 4)."
            )
        ),
    ] = "",
    run_id: Annotated[
        int,
        typer.Option(
            "--run",
            help=(
                "ingestion_run id of the options_cycle_backfill run to read. Default: for "
                "each underlying, the newest such run overlapping the window that requested it."
            ),
        ),
    ] = 0,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Print the scope, its hash and the key. Writes nothing."),
    ] = True,
    confirm: Annotated[
        bool, typer.Option("--confirm", help="Write ONE immutable DataSnapshot row.")
    ] = False,
) -> None:
    """Create the options-scoped DataSnapshot an options evaluation must name.

    The scope (D1 §9) is composed from the pre-registered parameters plus the
    coverage summary of the cycle-backfill run(s) that fetched the named
    underlyings, restricted to those underlyings. Counts, dates and identities
    only: no option bar is read.

    ``--dry-run`` (the default) prints the scope, the scope hash, the
    ``options_config_hash``, the coverage of the named set against gate
    0.c/0.d's floors and the key that would be written. ``--confirm`` writes one
    row. Refused, exiting non-zero: coverage of the named set below either
    pre-registered floor (or absent for any underlying); an underlying whose run
    recorded no cycles or no expected sessions for it, or lists it as failed;
    coverage runs whose
    window is not exactly ``--since``..``--until``; a key that does not carry the
    scope hash; a key that already exists with different symbols or a different
    scope; and, on ``--confirm``, a live worker. Re-running ``--confirm`` for an
    identical snapshot writes nothing and says so.

    Creating a snapshot spends no sealed look and evaluates nothing.
    """
    ensure_not_engaged()
    import json as _json

    from sqlalchemy import select

    from signalforge.db.models import DataSnapshot
    from signalforge.db.session import session_scope
    from signalforge.research.options_evidence import coverage_preflight, snapshot_options_coverage
    from signalforge.research.options_scope import (
        DEFAULT_FILL_TIMING_BASIS,
        DEFAULT_SPREAD_MODEL_ID,
        SNAPSHOT_KEY_HASH_CHARS,
        build_options_scope,
        canonical_options_snapshot_key,
        options_scope_hash,
        scopes_match,
    )
    from signalforge.research.promotion import get_or_create_dataset_snapshot
    from signalforge.scheduler import other_live_worker
    from signalforge.worker_lock import worker_lock_holder

    syms = sorted({x.strip().upper() for x in symbols.split(",") if x.strip()})
    if not syms:
        typer.secho("--symbols named no underlying", fg=typer.colors.RED)
        raise typer.Exit(code=2)
    try:
        start, end = date.fromisoformat(since), date.fromisoformat(until)
    except ValueError as exc:
        typer.secho(f"--since/--until must be YYYY-MM-DD: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=2) from None
    if start > end:
        typer.secho(f"--since {start} is after --until {end}", fg=typer.colors.RED)
        raise typer.Exit(code=2)
    if confirm:
        # --dry-run defaults to True, so --confirm must win when both are present.
        dry_run = False

    refusals: list[str] = []
    with session_scope(write=False) as session:
        cov = snapshot_options_coverage(
            session,
            syms,
            window_start=start,
            window_end=end,
            run_ids=[run_id] if run_id else None,
        )
        pre = coverage_preflight(cov)
        summary = cov.summary
        if summary is None:
            typer.secho("\nREFUSED:", fg=typer.colors.RED, bold=True)
            for r in pre.reasons:
                typer.secho(f"  - {r}", fg=typer.colors.RED)
            typer.secho("no scope could be built; nothing was written.", fg=typer.colors.YELLOW)
            raise typer.Exit(code=2)
        refusals.extend(pre.reasons)
        if (summary.window_start, summary.window_end) != (start, end):
            refusals.append(
                f"the coverage run(s) {list(cov.run_ids)} cover {summary.window_start}.."
                f"{summary.window_end}, not the requested {start}..{end}; a snapshot's window "
                "is the window its data was fetched for, never a relabelled one"
            )
        scope = build_options_scope(
            summary,
            spread_model_id=DEFAULT_SPREAD_MODEL_ID,
            spread_multiplier=1.0,
            fill_timing_basis=DEFAULT_FILL_TIMING_BASIS,
            ingestion_run_ids=cov.run_ids,
        )
        scope_hash = options_scope_hash(scope)
        canonical = canonical_options_snapshot_key(scope)
        snap_key = key.strip() or canonical
        if scope_hash[:SNAPSHOT_KEY_HASH_CHARS] not in snap_key:
            refusals.append(
                f"key {snap_key!r} does not carry this scope's hash "
                f"({scope_hash[:SNAPSHOT_KEY_HASH_CHARS]}); the options snapshot key must carry "
                f"the scope hash (D3 §1 item 4). Canonical key: {canonical}"
            )
        existing = session.scalar(select(DataSnapshot).where(DataSnapshot.key == snap_key))
        existing_id = existing.id if existing is not None else None
        if existing is not None:
            have = sorted(str(x).upper() for x in existing.symbols_json)
            if have != syms:
                refusals.append(
                    f"key {snap_key!r} already exists (id={existing.id}) with different symbols "
                    f"({have}); a DataSnapshot is immutable — use a new, distinct key"
                )
            elif not scopes_match(existing.options_scope_json, scope):
                refusals.append(
                    f"key {snap_key!r} already exists (id={existing.id}) with a different "
                    "options scope; the scope IS the dataset's identity — use a new, distinct key"
                )
            else:
                # ``ingestion_run_ids`` is provenance and outside the scope hash, so
                # the scope comparison above cannot see it.  An existing row pinned
                # to OTHER runs is not "this exact snapshot": say so, never report
                # "nothing to write" over a different coverage basis.
                recorded = sorted(
                    int(i) for i in (existing.options_scope_json or {}).get("ingestion_run_ids", [])
                )
                if recorded != sorted(cov.run_ids):
                    refusals.append(
                        f"key {snap_key!r} already exists (id={existing.id}) and is pinned to "
                        f"ingestion run(s) {recorded}, but the coverage read now comes from "
                        f"run(s) {sorted(cov.run_ids)}; the existing snapshot stays judged on "
                        "its recorded runs — pass --run to read those, or explain the difference"
                    )

    if confirm:
        holder = worker_lock_holder()
        live = other_live_worker()
        if holder or live:
            why = (
                f"the scheduler worker holds the write lock (holder: {holder})"
                if holder
                else str(live)
            )
            refusals.append(
                why + "; writing the snapshot opens a write transaction against the worker's "
                "database — stop the worker first (docs/SQLITE_CONCURRENCY.md)"
            )

    typer.secho(f"options snapshot {snap_key!r}", bold=True)
    typer.echo(f"  underlyings ({len(syms)}): {', '.join(syms)}")
    typer.echo(f"  window: {start}..{end}   coverage run(s): {list(cov.run_ids)}")
    typer.echo(f"  options_scope_hash:  {scope_hash}")
    typer.echo(f"  options_config_hash: {scope['options_config_hash']}")
    typer.echo(
        f"  option-data source:  {scope['option_data']['source']} "
        f"(underlying bars: {scope['reference_price']['source']})"
    )
    typer.echo(f"  canonical key:       {canonical}")
    thresholds = scope["coverage_thresholds"]
    typer.echo(
        f"  coverage of this set: cycles {summary.cycles_covered}/{summary.cycles_total} "
        f"({summary.cycles_bracket_fraction:.3f}, floor "
        f"{thresholds['gate_0c_cycles_bracket']:.2f}); bars {summary.bars_written:,}/"
        f"{summary.sessions_expected:,} ({summary.bar_continuity_fraction:.3f}, floor "
        f"{thresholds['gate_0d_session_bars']:.2f})"
    )
    for sym, bracket, continuity, rid in pre.per_underlying:
        typer.echo(f"    {sym}: cycles {bracket:.3f}, bars {continuity:.3f} (run #{rid})")
    typer.echo("  options_scope_json:")
    for line in _json.dumps(scope, indent=2, sort_keys=True).splitlines():
        typer.echo(f"    {line}")
    _print_or0c_warning(pre)

    if refusals:
        typer.secho("\nREFUSED:", fg=typer.colors.RED, bold=True)
        for r in refusals:
            typer.secho(f"  - {r}", fg=typer.colors.RED)
        typer.secho("no DataSnapshot row was written.", fg=typer.colors.YELLOW)
        raise typer.Exit(code=2)

    if existing_id is not None:
        typer.secho(
            f"\nDataSnapshot {snap_key!r} already exists (id={existing_id}) with these exact "
            "symbols and this exact scope; nothing to write.",
            fg=typer.colors.GREEN,
        )
        return
    if dry_run:
        typer.secho(
            f"\nDRY RUN — would write ONE DataSnapshot row: key {snap_key!r}, {len(syms)} "
            "symbols, the scope above. Nothing was written. Re-run with --confirm.",
            fg=typer.colors.YELLOW,
        )
        return

    with session_scope(write=True) as session:
        try:
            snap = get_or_create_dataset_snapshot(
                session,
                key=snap_key,
                symbols=syms,
                description=(
                    f"options-scoped snapshot: {', '.join(syms)}, {start}..{end}, "
                    f"cycle-backfill run(s) {list(cov.run_ids)}"
                ),
                source_note=(
                    f"created by 'signalforge options snapshot'; options_scope_hash {scope_hash}"
                ),
                options_scope=scope,
            )
        except ValueError as exc:
            typer.secho(f"REFUSED: {exc}", fg=typer.colors.RED)
            raise typer.Exit(code=2) from None
        typer.secho(
            f"\nwrote DataSnapshot id={snap.id} key {snap.key!r} ({len(syms)} symbols).",
            fg=typer.colors.GREEN,
        )
    typer.echo("No evaluation was run and no sealed look was spent. Research data only.")


@options_app.command("simulate")
def options_simulate_cmd(
    strategy: Annotated[
        str, typer.Argument(help="long_call|long_put|covered_call|cash_secured_put")
    ],
    spot: Annotated[float, typer.Option()],
    strike: Annotated[float, typer.Option()],
    premium: Annotated[float, typer.Option()],
) -> None:
    """Hypothetical payoff / break-even / max-loss for a long or collateralised position."""
    from signalforge.options import simulators as sim

    fns = {
        "long_call": sim.long_call,
        "long_put": sim.long_put,
        "covered_call": sim.covered_call,
        "cash_secured_put": sim.cash_secured_put,
    }
    if strategy not in fns:
        typer.secho(
            f"unknown strategy {strategy!r}. Choose from {sorted(fns)}", fg=typer.colors.RED
        )
        raise typer.Exit(code=1)
    res = fns[strategy](spot, strike, premium)
    typer.echo(
        f"{res.strategy}: entry_cost {res.entry_cost:+.2f}  max_loss {res.max_loss:.2f}  "
        f"max_gain {res.max_gain}  break-even {res.break_evens}"
    )
    for n in res.notes:
        typer.echo(f"  - {n}")
    typer.echo(f"  {res.disclaimer}")


def _print_or0c_warning(pre: Any) -> None:
    """The OR-0c disclosure: printed by every command whose pre-flight found a
    member below a floor on its own numbers, whatever the pooled result."""
    text = pre.or0c_warning()
    if not text:
        return
    typer.secho(f"\nWARNING: {text}", fg=typer.colors.YELLOW, bold=True)
    typer.secho(
        "  The pre-flight result above is the POOLED reading (D5 §5.1); D5 §2.2 reads the same "
        "floors per symbol.\n  Until the operator records the decision in "
        "docs/research/DECISIONS_2026-09-12_wave3.md, 'options evaluate-promotion --confirm' "
        "refuses this set.",
        fg=typer.colors.YELLOW,
    )


def _options_gate_line(g: Any) -> tuple[str, str]:
    label = f"{g.number}{'.' + g.label.split('.', 1)[-1] if g.label else ''}"
    return ("PASS" if g.passed else "FAIL", f"{g.label or label}. {g.name}: {g.detail}")


@options_app.command("evaluate-promotion")
def options_evaluate_promotion_cmd(
    strategy: Annotated[
        str, typer.Option(help="Options strategy key, e.g. 'options_short_vertical.medium_swing'.")
    ],
    snapshot_key: Annotated[
        str,
        typer.Option(
            help=(
                "The EXACT key of an options-scoped DataSnapshot. Mandatory: the unkeyed "
                "fallback resolves by symbol set alone, so an options run would bind to the "
                "live equity snapshot and collapse the two sealed ledgers (D4 §2.9b)."
            )
        ),
    ],
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Assemble the evidence and print the ladder. Writes nothing, seals nothing.",
        ),
    ] = True,
    confirm: Annotated[
        bool,
        typer.Option(
            "--confirm",
            help=(
                "Actually run the ladder: writes a StrategyPromotionEvaluation and, for a "
                "never-sealed (version, snapshot) pair, CONSUMES A SEALED LOOK."
            ),
        ),
    ] = False,
    since: Annotated[str, typer.Option(help="YYYY-MM-DD; window start.")] = "",
    until: Annotated[str, typer.Option(help="YYYY-MM-DD; window end (default: today).")] = "",
    sealed_days: Annotated[
        int, typer.Option(help="Length of the sealed window at the end of the span.")
    ] = 365,
    proxy: Annotated[str, typer.Option(help="Regime / benchmark proxy symbol.")] = "SPY",
    grid: Annotated[
        bool,
        typer.Option(
            "--grid",
            help=(
                "Also run gate 5's sensitivity grid (96 pre-sealed re-runs per underlying). "
                "Cached on (version, snapshot key, options_config_hash)."
            ),
        ),
    ] = False,
    accept_pooled_coverage: Annotated[
        str,
        typer.Option(
            "--accept-pooled-coverage",
            help=(
                "Must be exactly 'OR-0c'. Required for --confirm when a snapshot member is "
                "below a coverage floor on its own numbers, and honoured ONLY if "
                "docs/research/DECISIONS_2026-09-12_wave3.md carries the line "
                "'OR-0c: DECIDED pooled'. It never overrides the pooled floors."
            ),
        ),
    ] = "",
) -> None:
    """Run the OPTIONS gate ladder for one strategy on one options-scoped snapshot.

    Mirrors ``evaluate-promotion`` and ``scripts/evaluate_on_snapshot.py``, and is
    a **separate command** for the same reason ``evaluate_options_promotion`` is a
    separate function: the equity path must not gain an asset-class branch.

    ``--dry-run`` (the default) assembles the evidence and prints the ladder
    through the read-only preview — no evaluation row, no sealed test, no look.
    ``--confirm`` runs the real ladder and can spend a look, which is why it
    refuses while the worker holds the SQLite write lock.

    Refusals, all exiting non-zero: a missing D5 pre-registration file,
    coverage of the snapshot's own underlyings below gate 0.c/0.d's
    pre-registered floors (or absent for any of them, or a member with no cycle
    records, or one its run lists as failed), a snapshot that records no
    ``ingestion_run_ids``, and (``--confirm`` only) a worker holding the write
    lock. On a ``--dry-run`` the refusal is printed and the ladder is still shown
    as a diagnostic, but the exit code stays non-zero so nothing can mistake a
    refused rehearsal for a pass.

    OR-0c: the floors are computed pooled over the snapshot's underlyings. When a
    member is below a floor on its OWN numbers, every run prints a WARNING, and
    ``--confirm`` REFUSES unless ``--accept-pooled-coverage OR-0c`` is passed AND
    the decisions file records ``OR-0c: DECIDED pooled``. The flag alone is not
    enough, and neither is the record alone.
    """
    ensure_not_engaged()
    from collections.abc import Mapping
    from datetime import date as _date

    from sqlalchemy import select

    from signalforge.data.options_corporate_actions import Q_SERIES_SOURCE, build_q_lookup
    from signalforge.db.models import DataSnapshot
    from signalforge.db.session import session_scope, set_write_intent
    from signalforge.research import options_evidence as _oe
    from signalforge.research.options_evidence import (
        assemble_options_evidence,
        coverage_preflight,
        dataset_snapshot_coverage,
        options_ladder_preview,
        preregistration_path,
    )
    from signalforge.research.options_gates import OptionsGateThresholds, OptionsWindow
    from signalforge.research.options_strategies import (
        OptionsShortVertical,
        default_options_strategies,
    )
    from signalforge.worker_lock import worker_lock_holder

    base = next((s for s in default_options_strategies() if s.key == strategy), None)
    if base is None:
        known = [s.key for s in default_options_strategies()]
        typer.secho(f"unknown options strategy {strategy!r}; known: {known}", fg=typer.colors.RED)
        raise typer.Exit(code=2)

    end = _date.fromisoformat(until) if until else _date.today()
    start = _date.fromisoformat(since) if since else end - timedelta(days=365 * 8)
    sealed_start = end - timedelta(days=sealed_days)
    if sealed_start <= start:
        typer.secho(
            f"--sealed-days {sealed_days} leaves no pre-sealed span between {start} and {end}",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=2)
    window = OptionsWindow(
        start=start,
        pre_sealed_end=sealed_start - timedelta(days=1),
        sealed_start=sealed_start,
        end=end,
    )
    th = OptionsGateThresholds()

    refusals: list[str] = []
    prereg = preregistration_path()
    if not prereg.is_file():
        refusals.append(
            f"the D5 pre-registration file is missing ({prereg}); an options evaluation may not "
            "run without the document that froze its parameters (R1)"
        )
    if confirm and not grid:
        # Ruling R-2 (docs/research/DECISIONS_2026-09-12_wave3.md): a sealed look is
        # consumed exactly once per family index, so spending one on an automatic
        # gate-5 failure ("no sensitivity summary") would waste it. --confirm needs
        # --grid; --dry-run without --grid stays informative.
        refusals.append(
            "--confirm without --grid would spend a sealed look on an automatic gate-5 "
            "failure; run the sensitivity grid in the same invocation (--grid)"
        )
    if confirm:
        holder = worker_lock_holder()
        if holder:
            refusals.append(
                f"the scheduler worker holds the write lock (holder: {holder}); a --confirm run "
                "opens a write transaction and would starve every worker job for longer than the "
                "busy timeout. Stop the worker first (docs/SQLITE_CONCURRENCY.md)"
            )

    with session_scope(write=False) as session:
        snap = session.scalar(select(DataSnapshot).where(DataSnapshot.key == snapshot_key))
        if snap is None:
            typer.secho(f"no DataSnapshot with key {snapshot_key!r}", fg=typer.colors.RED)
            raise typer.Exit(code=2)
        if snap.options_scope_json is None:
            typer.secho(
                f"DataSnapshot {snapshot_key!r} carries no options_scope_json — an options "
                "evaluation needs an options-scoped snapshot (D4 §2.9b)",
                fg=typer.colors.RED,
            )
            raise typer.Exit(code=2)
        # Coverage is asked of THIS snapshot's underlyings (pooled over exactly
        # its symbols, each read from the run that fetched it) — not of whichever
        # cycle-backfill run happens to be newest.  Same two floors.
        pre = coverage_preflight(
            dataset_snapshot_coverage(
                session, snap, window_start=window.start, window_end=window.end
            )
        )
        refusals.extend(pre.reasons)
        options_config_hash = str(
            (snap.options_scope_json or {}).get("options_config_hash", "") or ""
        )
        # The option rows' source is read from recorded provenance, never guessed
        # and never the underlying-bar source.  Without one there is no chain to
        # load, so not even a diagnostic dry run can proceed.
        try:
            option_source = _oe.resolve_option_data_source(session, snap)
        except _oe.OptionSourceUnresolved as exc:
            option_source = ""
            refusals.append(str(exc))
        # D4 §2.9b: the snapshot key is bound to ``options_config_hash``, which
        # carries gate 0.i's risk limits.  A snapshot minted under a different
        # hash is a different pre-registration; it is superseded, not reused.
        from signalforge.config.research import OptionsEvaluationConfig as _OptionsEvalCfg

        current_hash = _OptionsEvalCfg().options_config_hash
        if options_config_hash != current_hash:
            refusals.append(
                f"DataSnapshot {snapshot_key!r} records options_config_hash "
                f"{options_config_hash[:12] or '(none)'}, but the evaluation config in force "
                f"hashes to {current_hash[:12]}; the snapshot key is not bound to this "
                "config (gate 0.i's risk limits included). Build a new snapshot with "
                "'signalforge options snapshot' — the old one is superseded, never relabelled"
            )

    # OR-0c guard.  Pooled is what ``pre.passed`` computed; the per-symbol reading
    # is ``pre.members_below_floor``.  A dry run only warns.  A --confirm run can
    # spend a sealed look, so it refuses while the two readings disagree, unless
    # the operator both recorded the decision AND named it on the command line.
    if accept_pooled_coverage and accept_pooled_coverage != _oe.OR0C_ITEM:
        refusals.append(
            f"--accept-pooled-coverage takes exactly {_oe.OR0C_ITEM!r}, not "
            f"{accept_pooled_coverage!r}"
        )
    if pre.members_below_floor:
        _print_or0c_warning(pre)
        if confirm:
            below = ", ".join(row[0] for row in pre.members_below_floor)
            decided = _oe.or0c_pooled_decision_recorded()
            if accept_pooled_coverage != _oe.OR0C_ITEM:
                refusals.append(
                    f"{_oe.OR0C_ITEM} is open and {below} is below a coverage floor on its own "
                    "numbers (per-symbol reading, D5 §2.2); --confirm refuses to spend a sealed "
                    "look on an undecided reading. Record the operator's decision in "
                    f"{_oe.OR0C_DECISIONS_FILE.name} and pass --accept-pooled-coverage "
                    f"{_oe.OR0C_ITEM}, or rebuild the snapshot without those members"
                )
            elif not decided:
                refusals.append(
                    f"--accept-pooled-coverage {_oe.OR0C_ITEM} was passed, but "
                    f"{_oe.OR0C_DECISIONS_FILE} has no line 'OR-0c: DECIDED pooled' — the item "
                    f"is still open, so the flag is not honoured ({below} below a floor on its "
                    "own numbers). Only the operator records that decision"
                )
            else:
                typer.secho(
                    f"{_oe.OR0C_ITEM}: DECIDED pooled is recorded in "
                    f"{_oe.OR0C_DECISIONS_FILE.name} and was named on the command line; "
                    f"proceeding on the pooled reading with {below} below a per-symbol floor.",
                    fg=typer.colors.YELLOW,
                )

    if refusals:
        typer.secho("\nREFUSED:", fg=typer.colors.RED, bold=True)
        for r in refusals:
            typer.secho(f"  - {r}", fg=typer.colors.RED)
        if confirm:
            typer.secho(
                "no evidence was assembled, no row was written and no sealed look was spent.",
                fg=typer.colors.YELLOW,
            )
            raise typer.Exit(code=2)
        if not option_source:
            typer.secho(
                "no option-data source is named, so no chain can be loaded and no evidence "
                "assembled — not even as a diagnostic.",
                fg=typer.colors.YELLOW,
            )
            raise typer.Exit(code=2)
        typer.secho(
            "--dry-run continues as a DIAGNOSTIC; the exit code stays non-zero.",
            fg=typer.colors.YELLOW,
        )

    if confirm and dry_run:
        # --dry-run defaults to True, so --confirm must win when both are present;
        # the alternative (refusing the combination) would make --confirm unusable
        # without also typing --no-dry-run.
        dry_run = False

    sensitivity_summary = None
    with session_scope(write=confirm) as session:
        if confirm:
            # Rule 4 (docs/SQLITE_CONCURRENCY.md): drop write intent for the long
            # read/compute phase, re-arm it only for the write.
            session.commit()
            set_write_intent(session, False)
        snap = session.scalar(select(DataSnapshot).where(DataSnapshot.key == snapshot_key))
        assert snap is not None  # re-read in this scope; existence checked above

        # Decision 11 / gate 0.g: the ladder instance and every grid point price
        # with the SAME per-(underlying, session) dividend series, read from the
        # derived ``dividend_yield_daily`` table (``options q-series``). A session
        # without a row is a non-entry — never q = 0.0.
        strat = OptionsShortVertical(
            base.params,
            selection_cost_model=base.selection_cost_model,
            q_lookup=build_q_lookup(session, list(snap.symbols_json)),
            q_source=Q_SERIES_SOURCE,
            risk_free_rate=base.risk_free_rate,
            r_source=base.r_source,
            proxy_regimes=base.proxy_regimes,
        )

        if grid:
            from dataclasses import replace as _dc_replace

            from signalforge.research.options_sensitivity import run_options_sensitivity
            from signalforge.research.options_strategies import VERSION

            base_params = strat.params

            def _factory(p: Mapping[str, Any]) -> Any:
                return OptionsShortVertical(
                    _dc_replace(base_params, **dict(p)),
                    selection_cost_model=strat.selection_cost_model,
                    q_lookup=strat.q_lookup,
                    q_source=strat.q_source,
                    risk_free_rate=strat.risk_free_rate,
                    r_source=strat.r_source,
                    proxy_regimes=strat.proxy_regimes,
                )

            report = run_options_sensitivity(
                session,
                strat,
                _factory,
                baseline_params={k: getattr(base_params, k) for k in strat.sensitivity_axes()},
                dataset_snapshot=snap,
                window=window,
                version=VERSION,
                options_config_hash=options_config_hash,
                thresholds=th,
            )
            sensitivity_summary = report.summary(th)
            typer.secho(
                f"gate-5 grid: {report.evaluated_points}/{report.declared_points} points "
                f"evaluated, {len(report.dropped_points)} dropped, "
                f"cache_hit={report.cache_hit}",
                fg=typer.colors.CYAN,
            )

        assembled = assemble_options_evidence(
            session,
            strat,
            dataset_snapshot=snap,
            window=window,
            thresholds=th,
            proxy_symbol=proxy,
            sensitivity=sensitivity_summary,
            include_sealed=confirm,
        )
        typer.secho(
            f"\n{strat.key} on {snap.key!r} (id {snap.id}, {len(snap.symbols_json)} symbols)  "
            f"window {window.start}..{window.end}  sealed from {window.sealed_start}",
            bold=True,
        )
        typer.echo(
            f"  underlyings evaluable: "
            f"{sum(1 for u in assembled.per_underlying if u.dual is not None)}"
            f"/{len(assembled.per_underlying)}   "
            f"pooled structures: {len(assembled.evidence.dual.baseline.trades)}   "
            f"OOS: {assembled.evidence.n_oos_trades}"
        )
        typer.echo(
            f"  clustered CI {assembled.clustered_d4.unit}: "
            f"[{assembled.clustered_d4.low:+.4f}, {assembled.clustered_d4.high:+.4f}]R  "
            f"k={assembled.clustered_d4.n_clusters}  deff={assembled.clustered_d4.deff:.2f}  "
            f"seed={assembled.clustered_d4.seed}"
        )
        typer.echo(
            f"  F11 {assembled.clustered_f11.unit}: low {assembled.clustered_f11.low:+.4f}R "
            f"(NO-SHIP if <= {th.min_bootstrap_ci_low_r:+.4f}R)"
        )
        for note in assembled.notes:
            typer.secho(f"  note: {note}", fg=typer.colors.YELLOW)

        if dry_run:
            gates = options_ladder_preview(assembled.evidence, window=window, thresholds=th)
            typer.secho("\n  DRY RUN — no evaluation row, no sealed test, no look", bold=True)
            for g in gates:
                mark, line = _options_gate_line(g)
                typer.secho(
                    f"  [{mark}] {line}",
                    fg=typer.colors.GREEN if g.passed else typer.colors.RED,
                )
            typer.echo("  sealed looks: none — a dry run cannot read or create a sealed test.")
        else:
            from signalforge.research.options_promotion import evaluate_options_promotion
            from signalforge.settings_store import effective_research_config

            cfg = effective_research_config(session)
            session.commit()
            set_write_intent(session, True)
            result = evaluate_options_promotion(
                session,
                strat.spec(),
                symbols=list(snap.symbols_json),
                window=window,
                dataset_snapshot=snap,
                evidence=assembled.evidence,
                thresholds=th,
                config=cfg,
                options_config_hash=options_config_hash,
            )
            colour = typer.colors.GREEN if result.passed else typer.colors.YELLOW
            typer.secho(f"\n  -> {result.verdict}", fg=colour, bold=True)
            for g in result.gates:
                mark, line = _options_gate_line(g)
                typer.secho(
                    f"  [{mark}] {line}",
                    fg=typer.colors.GREEN if g.passed else typer.colors.RED,
                )
            typer.echo(f"  sealed looks: {_sealed_look_summary(result)}")
            typer.echo(
                f"  k_effective {result.k_effective} "
                f"(prior {result.sealed_look_prior} + abandonments "
                f"{result.presealed_abandonments}); program looks {result.options_program_looks}"
            )

    typer.echo("Research signal only — SIMULATION ONLY. No order was placed.")
    if refusals:
        raise typer.Exit(code=2)


@app.command()
def universe() -> None:
    """Preview the conservative liquid-universe screen against the local data."""
    from signalforge.db.session import session_scope
    from signalforge.research.universe import screen_universe
    from signalforge.settings_store import effective_research_config

    with session_scope() as session:
        scr = screen_universe(session, effective_research_config(session))
    typer.secho(f"kept {len(scr.kept)}: {', '.join(scr.kept)}", fg=typer.colors.GREEN)
    for sym, reasons in sorted(scr.dropped.items()):
        typer.secho(f"  dropped {sym}: {'; '.join(reasons)}", fg=typer.colors.YELLOW)
    if scr.data_unavailable:
        typer.echo("filters not evaluable (no feed): " + "; ".join(scr.data_unavailable))


@news_app.command("summarize")
def news_summarize_cmd(
    ticker: Annotated[str, typer.Argument(help="Ticker to summarize recent headlines for.")],
    limit: Annotated[int, typer.Option()] = 8,
) -> None:
    """AI summary of *retrieved* headlines with citations (never a trade instruction)."""
    from sqlalchemy import select

    from signalforge.db.models import NewsItem
    from signalforge.db.session import session_scope
    from signalforge.llm.summarize_news import summarize_news

    with session_scope() as session:
        rows = list(
            session.scalars(
                select(NewsItem)
                .where(NewsItem.instrument_symbols.contains([ticker.upper()]))
                .order_by(NewsItem.published_at.desc())
                .limit(limit)
            )
        )
        items = [
            {
                "headline": r.headline,
                "source": r.source,
                "url": r.url,
                "published_at": r.published_at.isoformat(),
            }
            for r in rows
        ]
    if not items:
        typer.secho(f"no stored news for {ticker.upper()} — run `signalforge news ingest` first.")
        raise typer.Exit(code=1)
    summary = summarize_news(items)
    if summary is None:
        typer.secho(
            "LLM layer not configured or output rejected by a guard.", fg=typer.colors.YELLOW
        )
        raise typer.Exit(code=1)
    typer.echo(summary.text)
    typer.echo(
        f"\n[{summary.n_items} items · retrieved {summary.retrieved_at} · "
        f"feed stale: {summary.stale} · model {summary.model}]"
    )


@news_app.command("ingest")
def news_ingest_cmd(
    tickers: Annotated[
        str, typer.Option(help="Comma-separated; default: configured universe.")
    ] = "",
    lookback_days: Annotated[int, typer.Option()] = 3,
    limit: Annotated[int, typer.Option()] = 50,
    source: Annotated[
        str, typer.Option(help="generic | benzinga | both — which feed(s) to pull.")
    ] = "both",
) -> None:
    """Pull recent licensed headlines for the universe; dedupe + persist audit metadata.

    The generic multi-publisher feed and the Benzinga News add-on feed
    (GET /benzinga/v2/news) are two separate adapters — each ingest call
    tags its rows with a distinct ``provider``, so the two never mix."""
    ensure_not_engaged()
    from signalforge.config import get_settings
    from signalforge.data.adapters.massive_news import BenzingaNewsAdapter, MassiveNewsAdapter
    from signalforge.data.news_ingest import ingest_news
    from signalforge.db.session import session_scope

    if source not in ("generic", "benzinga", "both"):
        typer.secho(f"news: unknown --source {source!r} (expected generic|benzinga|both)")
        raise typer.Exit(code=1)

    s = get_settings()
    tk = [x.strip().upper() for x in tickers.split(",") if x.strip()] or list(s.research.universe)

    adapters: list[Any] = []
    if source in ("generic", "both"):
        adapters.append(MassiveNewsAdapter())
    if source in ("benzinga", "both"):
        adapters.append(BenzingaNewsAdapter())

    for adapter in adapters:
        with session_scope(write=True) as session:
            rep = ingest_news(session, adapter, tk, lookback_days=lookback_days, limit=limit)
        if rep.error:
            typer.secho(f"news [{adapter.provider_name}]: {rep.error}", fg=typer.colors.RED)
            raise typer.Exit(code=1)
        typer.secho(
            f"news [{adapter.provider_name}]: fetched {rep.fetched}, written {rep.written}, "
            f"duplicates {rep.duplicates} (publishers: {', '.join(rep.publishers or [])})",
            fg=typer.colors.GREEN,
        )
    typer.echo("News is for context and LLM summaries only — it never drives a recommendation.")


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

    with session_scope(write=True) as session:
        report = ingest_universe(session, adapter, syms, start, end)

    typer.secho(
        f"ingest[{adapter.provider_name}] {start}..{end}: "
        f"{report.bars_written} bars written across {len(syms)} symbols",
        fg=typer.colors.GREEN,
    )
    for err in report.errors:
        typer.secho(f"  ! {err}", fg=typer.colors.RED)


@app.command("ingest-intraday")
def ingest_intraday_cmd(
    bar_size: Annotated[str, typer.Option(help="5m | 15m | 30m | 1h")] = "5m",
    days: Annotated[
        int, typer.Option(help="Trailing days to fetch. Ignored when --since is given.")
    ] = 5,
    since: Annotated[
        str,
        typer.Option(
            help="YYYY-MM-DD. Dated backfill: calendar-chunked, resumable, records an "
            "IngestionRun. Required for anything longer than a few days."
        ),
    ] = "",
    until: Annotated[str, typer.Option(help="YYYY-MM-DD; default: today. Used with --since.")] = "",
    symbols: Annotated[
        str, typer.Option(help="Comma-separated; default: configured universe.")
    ] = "",
    chunk_months: Annotated[
        int,
        typer.Option(
            help="Calendar months per provider request (2 keeps each under the provider's "
            "50,000 one-minute base-aggregate cap; must divide 12)."
        ),
    ] = 2,
    resume_run_id: Annotated[
        int, typer.Option(help="Resume this ingestion_run id; symbols already OK are skipped.")
    ] = 0,
    dry_run: Annotated[
        bool, typer.Option(help="Print the request plan and cost; make no provider call.")
    ] = False,
) -> None:
    """Fetch intraday bars into the local store (Phase 2).

    Two modes. With --since it is a DATED BACKFILL: the span is split into
    two-month calendar chunks that each stay under the provider's 50,000
    one-minute base-aggregate cap (the adapter rejects a paginated answer
    rather than silently truncating it), only RTH bars are stored, progress is
    committed per symbol and recorded on an ``IngestionRun`` row that
    --resume-run-id can re-enter. Without it, the original trailing --days
    top-up.

    The cap counts one-minute base aggregates, not rows of the requested bar
    size (ingestion_run 71: year-long 15m chunks came back paginated). The
    24-symbol ex-META universe at 15m from 2016-09-01 to 2026-10-26 is 61
    two-month chunks per symbol = 1,464 paced requests, ~4.9 h at 12.1 s
    spacing, and ~1.59M RTH rows. Use --dry-run to print the exact plan for
    the arguments you intend to run.

    A backfill deliberately does NOT register a BAR_INTRADAY feed-status row:
    a one-off historical fetch is not a live feed, and a stale feed row blocks
    every candidate and briefing alert.
    """
    ensure_not_engaged()
    from datetime import UTC

    from signalforge.config import get_settings
    from signalforge.data.adapters.registry import get_primary_adapter
    from signalforge.data.ingest import (
        ingest_intraday_history,
        ingest_intraday_universe,
        intraday_request_plan,
    )
    from signalforge.db.session import session_scope

    settings = get_settings()
    adapter = get_primary_adapter(settings)
    if not hasattr(adapter, "fetch_intraday_bars"):
        typer.secho(f"{adapter.provider_name} has no intraday feed", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()] or list(
        settings.research.universe
    )

    if not since:
        if dry_run or resume_run_id:
            typer.secho("--dry-run and --resume-run-id require --since", fg=typer.colors.RED)
            raise typer.Exit(code=1)
        end_dt = datetime.now(UTC)
        start_dt = end_dt - timedelta(days=days)
        with session_scope(write=True) as session:
            report = ingest_intraday_universe(
                session, adapter, syms, start_dt, end_dt, bar_size=bar_size  # type: ignore[arg-type]
            )
        typer.secho(
            f"ingest-intraday[{adapter.provider_name}] {bar_size}: "
            f"{report.bars_written} bars across {len(syms)} symbols",
            fg=typer.colors.GREEN,
        )
        for err in report.errors:
            typer.secho(f"  ! {err}", fg=typer.colors.RED)
        return

    start_d = date.fromisoformat(since)
    end_d = date.fromisoformat(until) if until else date.today()
    try:
        plan = intraday_request_plan(
            syms, start_d, end_d, bar_size=bar_size, chunk_months=chunk_months
        )
    except ValueError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from None

    typer.secho(f"plan: {plan.summary()}", fg=typer.colors.CYAN)
    if dry_run:
        typer.echo("dry run — no provider request was made.")
        return

    with session_scope(write=True) as session:
        run = ingest_intraday_history(
            session,
            adapter,  # type: ignore[arg-type]
            syms,
            start_d,
            end_d,
            bar_size=bar_size,
            chunk_months=chunk_months,
            resume_run_id=resume_run_id or None,
        )
        run_id, status, written, skipped = (
            run.id,
            run.status,
            run.bars_written,
            run.bars_skipped,
        )
        failures = dict(run.symbols_failed or {})
        gap_symbols = sorted(run.gaps_json or {})

    colour = typer.colors.GREEN if status == "ok" else typer.colors.YELLOW
    typer.secho(
        f"ingest-intraday[{adapter.provider_name}] {bar_size} {start_d}..{end_d}: {status} — "
        f"{written} RTH bars written, {skipped} skipped (duplicate or non-RTH), "
        f"ingestion_run id {run_id}",
        fg=colour,
    )
    for sym, err in failures.items():
        typer.secho(f"  ! {sym}: {err}", fg=typer.colors.RED)
    if gap_symbols:
        typer.secho(
            f"  coverage gaps remain for: {', '.join(gap_symbols)} — promotion gate 0 "
            f"requires 100% session coverage and will fail until they are filled",
            fg=typer.colors.YELLOW,
        )
    if failures:
        typer.echo(f"resume with: signalforge ingest-intraday --resume-run-id {run_id} ...")


@app.command("backtest-extended")
def backtest_extended(
    out_file: Annotated[str, typer.Option()] = "reports/EXTENDED_HISTORY_RESULTS.md",
    sealed_days: Annotated[
        int, typer.Option(help="Length of the untouched final-test window.")
    ] = 365,
    n_folds: Annotated[
        int, typer.Option(help="Rolling walk-forward folds over the pre-sealed span.")
    ] = 4,
) -> None:
    """Frozen-strategy backtest over the full ingested history, with train / rolling
    walk-forward / sealed-test segmentation, per-regime breakdown, portfolio-level
    metrics (CAGR, vol, Sharpe/Sortino, max DD, turnover, exposure, hit rate,
    profit factor) net of the project's cost model, and a benchmark comparison.
    Does not tune or modify any strategy."""
    ensure_not_engaged()
    from pathlib import Path

    from sqlalchemy import func, select

    from signalforge.backtest.costs import CostModel
    from signalforge.backtest.regime import label_regimes
    from signalforge.config import get_settings
    from signalforge.data.series import PriceSeries
    from signalforge.db.models import Instrument, OHLCVDaily
    from signalforge.db.session import session_scope
    from signalforge.domain import Horizon
    from signalforge.research.backtest_runner import run_strategy_over_universe
    from signalforge.research.portfolio_metrics import compute_portfolio_metrics
    from signalforge.research.strategies import default_strategies

    rc = get_settings().research
    symbols = list(rc.universe)
    cost_model = CostModel(
        commission_per_share=rc.commission_per_share,
        commission_min_per_order=rc.commission_min_per_order,
        slippage_bps=rc.slippage_bps,
        half_spread_fill_penalty=rc.half_spread_fill_penalty,
    )
    lines: list[str] = []

    with session_scope() as session:
        first, last = session.execute(
            select(func.min(OHLCVDaily.session_date), func.max(OHLCVDaily.session_date)).where(
                OHLCVDaily.source == get_settings().market_data_provider
            )
        ).one()
        if first is None:
            typer.secho("no real daily data ingested", fg=typer.colors.RED)
            raise typer.Exit(code=1)
        sealed_start = last - timedelta(days=sealed_days)

        # benchmark: SPY buy-and-hold over the same span
        spy = PriceSeries.load(session, "SPY", first, last)
        bench_ret = (spy.close[-1] / spy.close[0] - 1.0) * 100 if len(spy) > 1 else 0.0
        bench_sealed = None
        if len(spy) > 1:
            idx = [i for i, d in enumerate(spy.dates) if d >= sealed_start]
            if idx:
                bench_sealed = (spy.close[-1] / spy.close[idx[0]] - 1.0) * 100

        regimes = label_regimes(spy) if len(spy) else {}
        cov_rows = session.execute(
            select(Instrument.symbol, func.count(OHLCVDaily.id), func.min(OHLCVDaily.session_date))
            .join(Instrument, OHLCVDaily.instrument_id == Instrument.id)
            .where(
                Instrument.symbol.in_(symbols),
                OHLCVDaily.source == get_settings().market_data_provider,
            )
            .group_by(Instrument.symbol)
        ).all()

        lines += [
            "# Extended-history backtest (frozen strategy)",
            "",
            "> Hypothetical research output. Costs from the project cost model are baked in. "
            "The strategy, thresholds, scoring and sizing are unchanged from the prior baseline — "
            "results are directly comparable. No parameter was tuned in this phase.",
            "",
            f"- Data: `{get_settings().market_data_provider}` real daily bars, {first}..{last}",
            f"- Universe: {len(symbols)} symbols "
            f"({sum(1 for _, n, _ in cov_rows if n >= 2000)} with >=2000 sessions)",
            f"- Cost model: {cost_model.slippage_bps} bps slippage + half-spread; "
            f"commission {cost_model.commission_per_share}/sh",
            f"- Sealed final-test window: **{sealed_start} .. {last}** (evaluated once)",
            f"- Rolling walk-forward: {n_folds} contiguous folds over {first} .. {sealed_start}",
            f"- Benchmark (SPY buy&hold): {bench_ret:+.1f}% full span"
            + (f", {bench_sealed:+.1f}% sealed" if bench_sealed is not None else ""),
            "",
            "## Symbol coverage (survivorship note)",
            "",
            "| symbol | sessions | first |",
            "|---|--:|---|",
        ]
        for sym, n, f0 in sorted(cov_rows):
            lines.append(f"| {sym} | {n} | {f0} |")
        lines += [
            "",
            "META has a short/gapped series (ticker discontinuity FB→META); XLC starts at its "
            "2018 launch. The universe is a *fixed hand-picked list* of large-cap survivors — "
            "**it embeds survivorship bias**: no delisted names, no point-in-time membership.",
            "",
            "## Per strategy",
            "",
        ]

        for strat in default_strategies():
            spec = strat.spec()
            if spec.horizon is Horizon.INTRADAY:
                lines += [f"### {spec.key}", "", "_intraday — no intraday history; skipped_", ""]
                continue
            full = run_strategy_over_universe(
                session,
                strat,
                symbols,
                first,
                last,
                cost_model=cost_model,
                config_hash=rc.config_hash,
            )
            trades = full.trades
            sealed = [t for t in trades if t.entry_date >= sealed_start]
            pre = [t for t in trades if t.entry_date < sealed_start]
            # rolling folds over the pre-sealed span
            span = (sealed_start - first).days
            fold_lines = []
            for k in range(n_folds):
                lo = first + timedelta(days=span * k // n_folds)
                hi = first + timedelta(days=span * (k + 1) // n_folds)
                ft = [t for t in pre if lo <= t.entry_date < hi]
                pm = compute_portfolio_metrics(ft, span_start=lo, span_end=hi)
                fold_lines.append(
                    f"| fold {k + 1} ({lo}..{hi}) | {pm.n_trades} | {pm.total_return_pct:+.1f}% | "
                    f"{pm.sharpe:+.2f} | {pm.max_drawdown_pct:.1f}% | {pm.hit_rate:.0%} |"
                )
            pm_full = compute_portfolio_metrics(trades, span_start=first, span_end=last)
            pm_pre = compute_portfolio_metrics(pre, span_start=first, span_end=sealed_start)
            pm_sealed = compute_portfolio_metrics(sealed, span_start=sealed_start, span_end=last)

            by_regime: dict[str, list] = {}
            for t in trades:
                lbl = regimes.get(t.entry_date, "warmup")
                by_regime.setdefault(lbl, []).append(t)

            lines += [
                f"### {spec.key}  (v{spec.version}, status {spec.status.value})",
                "",
                "| segment | trades | total ret | CAGR | ann vol | Sharpe | Sortino | maxDD | "
                "hit | PF | turnover/yr | exposure |",
                "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|",
                _pm_row("full 2016-2026", pm_full),
                _pm_row("train+WF (pre-sealed)", pm_pre),
                _pm_row("SEALED final-test", pm_sealed),
                "",
                "Rolling walk-forward folds (pre-sealed span):",
                "",
                "| fold | trades | total ret | Sharpe | maxDD | hit |",
                "|---|--:|--:|--:|--:|--:|",
                *fold_lines,
                "",
                "By entry-date regime (full span):",
                "",
                "| regime | trades | total ret | Sharpe | maxDD |",
                "|---|--:|--:|--:|--:|",
            ]
            for lbl in sorted(by_regime):
                pm = compute_portfolio_metrics(by_regime[lbl])
                lines.append(
                    f"| {lbl} | {pm.n_trades} | {pm.total_return_pct:+.1f}% | {pm.sharpe:+.2f} | "
                    f"{pm.max_drawdown_pct:.1f}% |"
                )
            top_sym = sorted(
                {t.symbol for t in trades},
                key=lambda s: -sum(1 for t in trades if t.symbol == s),
            )[:3]
            conc = sum(1 for t in trades if t.symbol in top_sym) / max(len(trades), 1)
            lines += [
                "",
                f"Concentration: top-3 symbols {top_sym} account for {conc:.0%} of trades. "
                f"Frozen strategy — no tuning applied.",
                "",
            ]

    Path(out_file).parent.mkdir(parents=True, exist_ok=True)
    Path(out_file).write_text("\n".join(lines) + "\n", encoding="utf-8")
    typer.secho(f"wrote {out_file}", fg=typer.colors.GREEN)
    typer.echo("Research signal only — no order was placed.")


def _pm_row(label: str, p: PortfolioMetrics) -> str:
    return (
        f"| {label} | {p.n_trades} | {p.total_return_pct:+.1f}% | {p.cagr_pct:+.1f}% | "
        f"{p.ann_vol_pct:.1f}% | {p.sharpe:+.2f} | {p.sortino:+.2f} | {p.max_drawdown_pct:.1f}% | "
        f"{p.hit_rate:.0%} | {p.profit_factor:.2f} | {p.turnover_per_year:.1f} | {p.exposure:.2f} |"
    )


@app.command("backtest-report")
def backtest_report(
    out_dir: Annotated[str, typer.Option(help="Directory for the markdown reports.")] = "reports",
    years: Annotated[int, typer.Option(help="History window to test over.")] = 3,
) -> None:
    """Run every baseline strategy over the configured universe and write reports/."""
    from pathlib import Path

    from signalforge.backtest.costs import CostModel
    from signalforge.config import get_settings
    from signalforge.db.session import session_scope
    from signalforge.research.backtest_runner import run_strategy_over_universe
    from signalforge.research.reporting import render_report_md
    from signalforge.research.strategies import default_strategies

    settings = get_settings()
    rc = settings.research
    symbols = list(rc.universe)
    end = date.today()
    start = end - timedelta(days=365 * years + 10)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cost_model = CostModel(
        commission_per_share=rc.commission_per_share,
        commission_min_per_order=rc.commission_min_per_order,
        slippage_bps=rc.slippage_bps,
        half_spread_fill_penalty=rc.half_spread_fill_penalty,
    )

    from signalforge.domain import Horizon
    from signalforge.research.persistence import (
        persist_backtest_result,
        upsert_strategy_version,
    )

    with session_scope(write=True) as session:
        for strat in default_strategies():
            is_intraday = strat.spec().horizon is Horizon.INTRADAY
            result = run_strategy_over_universe(
                session,
                strat,
                symbols,
                (end - timedelta(days=45)) if is_intraday else start,
                end,
                allow_short=rc.allow_short_candidates,
                config_hash=rc.config_hash,
                cost_model=cost_model,
                intraday=is_intraday,
                bar_size=rc.intraday_bar_size,
                min_bars=40 if is_intraday else 60,
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


def _sensitivity_grid_builders() -> (
    dict[str, tuple[object, dict[str, object], dict[str, list[object]]]]
):
    """strategy key -> (factory(params)->strategy, baseline params dict, grid)."""
    from dataclasses import asdict

    from signalforge.domain import Horizon
    from signalforge.research.strategies.breakout import BreakoutParams, VolatilityBreakout
    from signalforge.research.strategies.mean_reversion import MeanReversion, MeanReversionParams
    from signalforge.research.strategies.relative_strength import (
        RelativeStrength,
        RelativeStrengthParams,
    )
    from signalforge.research.strategies.trend_continuation import TrendContinuation, TrendParams

    return {
        "trend_continuation.short_swing": (
            lambda p: TrendContinuation(Horizon.SHORT_SWING, TrendParams(**p)),
            asdict(TrendParams()),
            {"sma_fast": [15, 20, 25], "vol_mult": [1.1, 1.3, 1.5], "stop_atr": [1.25, 1.5, 1.75]},
        ),
        "mean_reversion.short_swing": (
            lambda p: MeanReversion(MeanReversionParams(**p)),
            asdict(MeanReversionParams()),
            {
                "z_lookback": [15, 20, 25],
                "z_entry": [-2.5, -2.0, -1.5],
                "stop_atr": [1.5, 2.0, 2.5],
            },
        ),
        "relative_strength.medium_swing": (
            lambda p: RelativeStrength(Horizon.MEDIUM_SWING, RelativeStrengthParams(**p)),
            asdict(RelativeStrengthParams()),
            {"lookback": [42, 63, 84], "excess_return_min": [0.03, 0.05, 0.08]},
        ),
        "volatility_breakout.short_swing": (
            lambda p: VolatilityBreakout(Horizon.SHORT_SWING, BreakoutParams(**p)),
            asdict(BreakoutParams()),
            {
                "channel": [15, 20, 25],
                "contraction_max": [0.6, 0.75, 0.9],
                "stop_atr": [1.5, 1.75, 2.0],
            },
        ),
    }


@app.command()
def sensitivity(
    strategy: Annotated[
        str, typer.Argument(help="Strategy key, e.g. trend_continuation.short_swing")
    ],
    years: Annotated[int, typer.Option(help="History window to test over.")] = 3,
) -> None:
    """Parameter-sensitivity grid: reject a strategy whose edge lives at one lucky point."""
    ensure_not_engaged()
    from signalforge.config import get_settings
    from signalforge.db.session import session_scope
    from signalforge.research.sensitivity import run_parameter_sensitivity
    from signalforge.settings_store import set_setting

    builders = _sensitivity_grid_builders()
    if strategy not in builders:
        typer.secho(
            f"no grid defined for {strategy!r}. Known: {sorted(builders)}", fg=typer.colors.RED
        )
        raise typer.Exit(code=1)
    factory, baseline, grid = builders[strategy]

    settings = get_settings()
    symbols = list(settings.research.universe)
    end = date.today()
    start = end - timedelta(days=365 * years + 10)

    with session_scope(write=True) as session:
        report = run_parameter_sensitivity(
            session,
            strategy_key=strategy,
            version="0.1.0",
            factory=factory,  # type: ignore[arg-type]
            baseline_params=baseline,  # type: ignore[arg-type]
            grid=grid,  # type: ignore[arg-type]
            symbols=symbols,
            start=start,
            end=end,
        )
        set_setting(session, f"sensitivity:{strategy}", report.to_dict(), actor="cli")

    typer.echo(
        f"{strategy}: {report.n_points} grid points, {report.n_evaluable} evaluable, "
        f"{report.n_positive} positive (baseline {report.baseline_expectancy_r:+.3f}R, "
        f"median {report.median_expectancy_r:+.3f}R, worst {report.worst_expectancy_r:+.3f}R)"
    )
    verdict = "FRAGILE" if report.fragile else "robust across the grid"
    typer.secho(
        f"  verdict: {verdict}",
        fg=typer.colors.RED if report.fragile else typer.colors.GREEN,
    )
    for r in report.reasons:
        typer.secho(f"    - {r}", fg=typer.colors.YELLOW)
    typer.echo("Research signal only — no order was placed.")


@app.command()
def calibrate(
    strategy: Annotated[str, typer.Argument(help="Strategy key, e.g. mean_reversion.short_swing")],
    years: Annotated[int, typer.Option(help="History window to test over.")] = 5,
) -> None:
    """Fit a regime-conditional, shrunk, validation-calibrated win-probability model.

    A probability is only ever shown for setups whose strategy version has an
    artifact from this command with enough validation trades (invariant S10).
    """
    ensure_not_engaged()
    from datetime import date as _date

    from signalforge.config import get_settings
    from signalforge.data.series import PriceSeries
    from signalforge.db.session import session_scope
    from signalforge.domain import Horizon
    from signalforge.research.backtest_runner import run_strategy_over_universe
    from signalforge.research.probability import fit_calibration, save_calibration
    from signalforge.research.regime import regime_lookup
    from signalforge.research.strategies import default_strategies

    strat = next((s for s in default_strategies() if s.spec().key == strategy), None)
    if strat is None:
        typer.secho(f"unknown strategy {strategy!r}", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    if strat.spec().horizon is Horizon.INTRADAY:
        typer.secho("intraday calibration is not supported yet", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    settings = get_settings()
    symbols = list(settings.research.universe)
    end = _date.today()
    start = end - timedelta(days=365 * years + 10)

    with session_scope(write=True) as session:
        result = run_strategy_over_universe(session, strat, symbols, start, end)
        proxy = PriceSeries.load(session, "SPY", start, end)
        regimes = regime_lookup(proxy) if len(proxy) else {}
        rows: list[tuple[_date, str, bool]] = []
        for tr in result.trades:
            rs = regimes.get(tr.entry_date)
            label = f"{rs.trend.value}/{rs.vol.value}" if rs else "unknown"
            rows.append((tr.entry_date, label, tr.pnl_r > 0))

        artifact = fit_calibration(
            strategy_key=strat.spec().name, version=strat.spec().version, trades=rows
        )
        if artifact is None:
            typer.secho(
                f"{strategy}: only {len(rows)} trades — not enough to calibrate. "
                "No probability will be shown for this strategy (correct per S10).",
                fg=typer.colors.YELLOW,
            )
            raise typer.Exit(code=0)
        ref = save_calibration(artifact)

    typer.secho(
        f"{strategy}: calibrated on {artifact.n_validation_trades} validation trades "
        f"({artifact.validation_start}..{artifact.validation_end}); "
        f"{len(artifact.regime_estimates)} regimes, {len(artifact.bins)} reliability bins -> {ref}",
        fg=typer.colors.GREEN,
    )
    typer.echo("Research signal only — no order was placed.")


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
    with session_scope(write=True) as session:
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


@paper_app.command("init")
def paper_init(
    cash: Annotated[float, typer.Option(help="Starting paper cash.")] = 30_000.0,
    name: Annotated[str, typer.Option(help="Account name.")] = "default",
) -> None:
    """Create the paper account if it does not exist (no fixture data, no orders)."""
    from decimal import Decimal

    from sqlalchemy import select

    from signalforge.db.models import PaperAccount
    from signalforge.db.session import session_scope

    with session_scope(write=True) as session:
        acct = session.scalar(select(PaperAccount).where(PaperAccount.name == name))
        if acct is not None:
            typer.secho(
                f"paper account {name!r} already exists: cash {float(acct.cash):,.2f}. "
                "Research signal only — no order was placed.",
                fg=typer.colors.YELLOW,
            )
            return
        session.add(
            PaperAccount(name=name, initial_cash=Decimal(str(cash)), cash=Decimal(str(cash)))
        )
    typer.secho(
        f"created paper account {name!r} with ${cash:,.2f} (SIMULATED). "
        "Research signal only — no order was placed.",
        fg=typer.colors.GREEN,
    )


@paper_app.command("accept")
def paper_accept(candidate_id: int) -> None:
    """Paper-accept a candidate (SIMULATED fill). Research signal only — no order was placed."""
    from signalforge.db.session import session_scope
    from signalforge.paper.ledger import accept_candidate

    with session_scope(write=True) as session:
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

    with session_scope(write=True) as session:
        r = mark_to_market(session)
    typer.echo(
        f"checked {r.checked}, closed {r.closed}, realized {r.realized_pnl:+.2f}, "
        f"unrealized {r.unrealized_pnl:+.2f}"
    )


@paper_app.command("correct-legacy")
def paper_correct_legacy(
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Print exactly what would change; write nothing.")
    ] = False,
    confirm: Annotated[
        bool, typer.Option("--confirm", help="Write the corrections (append-only).")
    ] = False,
    resolution: Annotated[
        str,
        typer.Option(
            "--resolution",
            help="What to do with a trade whose exit is not after its entry: 'void' "
            "(default: reverse exit and entry, mark closed-as-void) or 'reopen' "
            "(reverse the exit and re-resolve on later bars).",
        ),
    ] = "void",
    void: Annotated[
        bool, typer.Option("--void", help="Shorthand for --resolution void (the default).")
    ] = False,
) -> None:
    """Correct legacy paper-ledger defects with append-only trade_correction rows:
    trades whose exit was recorded on or before the entry bar are VOIDED by
    default (exit P&L reversed, entry cash returned, position closed-as-void so it
    holds no exposure and counts toward no cap) or, with --resolution reopen,
    reversed and re-resolved on later bars; double-counted legacy entry costs
    are credited back. paper_trade rows are never modified. Stop the worker
    first; review --dry-run before --confirm. Research signal only — no order
    was placed."""
    if dry_run == confirm:
        typer.secho("pass exactly one of --dry-run or --confirm", fg=typer.colors.RED)
        raise typer.Exit(2)
    if resolution not in ("void", "reopen"):
        typer.secho("--resolution must be 'void' or 'reopen'", fg=typer.colors.RED)
        raise typer.Exit(2)
    if void and resolution != "void":
        typer.secho("--void conflicts with --resolution reopen", fg=typer.colors.RED)
        raise typer.Exit(2)
    from signalforge.db.session import session_scope
    from signalforge.paper.legacy_corrections import correct_legacy

    with session_scope(write=True) as session:
        rep = correct_legacy(
            session, confirm=confirm, resolution="void" if resolution == "void" else "reopen"
        )
    for line in rep.lines():
        typer.echo(line)
    typer.echo("SIMULATED paper ledger only. Research signal only — no order was placed.")


@options_paper_app.command("status")
def options_paper_status(
    account: Annotated[
        str | None,
        typer.Option(help="Account name; defaults to the configured options account."),
    ] = None,
    as_of: Annotated[str | None, typer.Option(help="Session date (YYYY-MM-DD).")] = None,
    json_out: Annotated[bool, typer.Option("--json", help="Print the raw snapshot.")] = False,
) -> None:
    """Show the SIMULATED options paper book: cash, collateral, open structures,
    greeks against their caps, the last reconciliation, and whether the second
    guard's setting is on. Read-only — it opens, closes and reconciles nothing."""
    import json
    from datetime import date as _date

    from signalforge.db.session import session_scope
    from signalforge.paper.options_marks import options_portfolio_snapshot
    from signalforge.settings_store import effective_research_config

    with session_scope() as session:
        name = account or effective_research_config(session).options_risk.paper_account_name
        snap = options_portfolio_snapshot(
            session,
            account_name=name,
            as_of=_date.fromisoformat(as_of) if as_of else None,
        )
    if json_out:
        typer.echo(json.dumps(snap, indent=2, default=str))
        return
    if not snap["exists"]:
        typer.secho(
            f"options paper account {snap['account']!r} does not exist — {snap['hint']}",
            fg=typer.colors.YELLOW,
        )
        return
    g = snap["greeks"]
    lim = snap["limits"]
    typer.secho(f"options paper account {snap['account']!r} (SIMULATED)", fg=typer.colors.CYAN)
    typer.echo(
        f"  cash {snap['cash']:,.2f}   collateral {snap['collateral_reserved']:,.2f}   "
        f"spendable {snap['spendable_cash']:,.2f}   (initial {snap['initial_cash']:,.2f})"
    )
    typer.echo(
        f"  open {snap['n_open']}/{lim['max_open_structures']} structures, open max loss "
        f"{snap['open_max_loss_total']:,.2f}/{lim['total_open_max_loss_dollars']:,.2f}   "
        f"closed {snap['n_closed']}"
    )
    typer.echo(
        f"  P&L: unrealized {snap['unrealized_pnl']:+,.2f}  realized {snap['realized_pnl']:+,.2f}"
        + (f"  expectancy {snap['expectancy_r']:+.4f}R" if snap["expectancy_r"] is not None else "")
    )
    typer.echo(
        f"  net delta {g['options_net_delta_notional']:+,.2f}/"
        f"{lim['max_net_delta_notional_dollars']:,.0f}   "
        f"combined {g['combined_net_delta_notional']:+,.2f}/"
        f"{lim['combined_max_net_delta_notional_dollars']:,.0f}   "
        f"net vega {g['options_net_vega_per_vol_pt']:+,.2f}/"
        f"{lim['max_net_vega_dollars_per_vol_pt']:,.0f}"
    )
    for s in snap["open_structures"]:
        mark = s["last_mark"]
        typer.echo(
            f"    #{s['position_id']} {s['underlying']} {s['structure_type']} x{s['contracts']} "
            f"exp {s['expiration']} (dte {s['dte']})  R {s['r_dollars']:,.2f}  "
            f"collateral {s['collateral_reserved']:,.2f}"
            + (
                f"  mark {mark['net_premium']:,.2f} ({mark['legs_priced']} legs priced"
                + (", SYNTHETIC" if mark["synthetic"] else "")
                + ")"
                if mark
                else "  (never marked)"
            )
        )
    rec = snap["reconciliation"]
    if rec is None:
        typer.secho(
            "  reconciliation: NONE — the second guard refuses to open without a dated, "
            "clean report (condition AA)",
            fg=typer.colors.YELLOW,
        )
    else:
        typer.secho(
            f"  reconciliation {rec['as_of']}: "
            + ("clean" if rec["clean"] else f"DIVERGENT {rec['findings']}"),
            fg=typer.colors.GREEN if rec["clean"] else typer.colors.RED,
        )
    auto = snap["auto_simulate"]
    typer.echo(
        f"  {auto['setting_key']}: {'ON' if auto['enabled'] else 'OFF'} "
        f"(cap {auto['max_per_day']}/day)"
    )
    typer.secho(f"  {snap['notice']}", fg=typer.colors.YELLOW)


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
    with session_scope(write=True) as session:
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

    with session_scope(write=True) as session:
        payload = build_and_store_briefing(session)
    typer.echo(payload["text"])
    if payload["narrative"]:
        typer.secho("\n--- AI narrative (explanation, not a trading instruction) ---", fg="cyan")
        typer.echo(payload["narrative"])
    if show_facts:
        typer.echo("\n--- frozen facts ---")
        typer.echo(json.dumps(payload["facts"], indent=2, default=str))


@app.command("strategy-health")
def strategy_health() -> None:
    """Compare each strategy's live-paper expectancy to its OOS backtest.

    Auto-downgrades/disables on a sustained, material shortfall (rules in
    ResearchConfig.health_monitor). Every transition is written to the audit log.
    """
    ensure_not_engaged()
    from signalforge.db.session import session_scope
    from signalforge.research.health_monitor import run_health_monitor

    with session_scope(write=True) as session:
        assessments = run_health_monitor(session)

    for a in assessments:
        line = (
            f"{a.strategy}@{a.version:<7} {a.action:<17} "
            f"n={a.n_paper_trades:<4} live={a.paper_expectancy_r:+.3f}R "
            f"oos={a.backtest_expectancy_r:+.3f}R z={a.z_score:+.2f}"
        )
        if a.action in ("downgrade", "disable"):
            typer.secho(f"  {line}  {a.from_status} -> {a.to_status}", fg=typer.colors.RED)
        else:
            typer.echo(f"  {line}")
    typer.echo("Research signal only — no order was placed.")


def _sealed_look_summary(result: Any) -> str:
    """The sealed-look disclosure line for one promotion result. Derived from
    the gate-9 ledger when gate 9 ran, so the CLI can never state a different
    count from the stored evidence."""
    gate9 = next((g for g in result.gates if g.number == 9), None)
    ledger = gate9.evidence.get("sealed_look_ledger") if gate9 is not None else None
    if not ledger:
        return (
            f"no sealed look taken by this evaluation "
            f"({result.sealed_look_prior} prior sealed tests for {result.strategy_key})"
        )
    from signalforge.research.promotion import format_sealed_look_line

    line = format_sealed_look_line(ledger)
    return f"this is {line} [{result.strategy_key}]"


@app.command("evaluate-promotion")
def evaluate_promotion_cmd(
    strategy: Annotated[
        str, typer.Option(help="Strategy key filter, e.g. 'relative_strength'; default: all.")
    ] = "",
    symbols: Annotated[
        str, typer.Option(help="Comma-separated; default: configured universe.")
    ] = "",
    since: Annotated[
        str, typer.Option(help="YYYY-MM-DD; default: earliest ingested history.")
    ] = "",
    until: Annotated[str, typer.Option(help="YYYY-MM-DD; default: today.")] = "",
    dataset: Annotated[
        str,
        typer.Option(
            help=(
                "Named dataset snapshot variant: 'baseline' (default, unmodified universe), "
                "'ex_meta' (META excluded), or 'meta_continuity_corrected' (META replaced by a "
                "verified continuity-bridged series — requires a prior "
                "'symbol-continuity-backfill' run). Ignored if --symbols is also given. "
                "See DataSnapshot."
            )
        ),
    ] = "baseline",
    snapshot_key: Annotated[
        str,
        typer.Option(
            help=(
                "Evaluate against the DataSnapshot with this EXACT key, creating it from the "
                "resolved symbols if it does not exist yet. For a dataset that is not one of "
                "the three named variants — e.g. the intraday snapshot "
                "'research_24_intraday15m_2016_2025'. A key whose stored symbol set differs "
                "from the one just requested is refused, never reinterpreted."
            )
        ),
    ] = "",
) -> None:
    """Run the formal 10-gate promotion pipeline for every default strategy.

    The only command that can move a strategy to paper_approved — and only when
    every gate passes on genuine licensed data. Prints a gate-by-gate table per
    strategy and, if nothing clears the bar, the canonical NO-TRADE line.

    --snapshot-key exists because an UNKEYED evaluation resolves its snapshot by
    exact symbol-set match among reusable snapshots. An intraday run on the
    24-symbol ex-META universe would therefore silently attach to the DAILY
    snapshot the two live paper approvals sit on — same symbols, different data.
    A distinct key keeps gate 9's sealed test keyed to its own dataset, so it can
    neither reuse nor be blocked by the daily snapshot's locked result.
    """
    ensure_not_engaged()
    from datetime import date as _date

    from signalforge.config import get_settings
    from signalforge.db.session import session_scope
    from signalforge.research.promotion import evaluate_promotion
    from signalforge.research.strategies import default_strategies
    from signalforge.settings_store import effective_research_config

    strategies = default_strategies()
    if strategy:
        strategies = [s for s in strategies if s.key.startswith(strategy)]
        if not strategies:
            typer.secho(f"no strategy key starts with {strategy!r}", fg=typer.colors.RED)
            raise typer.Exit(code=1)

    end = _date.fromisoformat(until) if until else _date.today()
    syms = None
    with session_scope(write=True) as session:
        cfg = effective_research_config(session)
        explicit_symbols = [x.strip().upper() for x in symbols.split(",") if x.strip()]
        start = _date.fromisoformat(since) if since else end - timedelta(days=365 * 10)

        from signalforge.data.repository import SourceFilter

        snap = None
        eval_source: SourceFilter = get_settings().market_data_provider
        if explicit_symbols:
            syms = explicit_symbols
            if dataset != "baseline":
                typer.secho(
                    f"--dataset {dataset!r} is ignored because --symbols was also given "
                    "(the explicit symbol list wins; no named dataset snapshot is resolved)",
                    fg=typer.colors.YELLOW,
                )
        else:
            from signalforge.data.symbol_continuity import latest_mapping
            from signalforge.research.fb_meta_universe_comparison import (
                resolve_variant,
                source_for_variant,
            )

            derived_symbol = mapping_id = None
            if dataset == "meta_continuity_corrected":
                mapping = latest_mapping(session, "FB", "META")
                if mapping is None or mapping.validation_status != "verified":
                    typer.secho(
                        "no verified FB->META continuity mapping exists yet — run "
                        "'signalforge symbol-continuity-backfill --old-symbol FB "
                        "--new-symbol META' first",
                        fg=typer.colors.RED,
                    )
                    raise typer.Exit(code=1)
                derived_symbol, mapping_id = mapping.derived_symbol, mapping.id
            syms, snap = resolve_variant(
                session, variant=dataset, derived_symbol=derived_symbol, mapping_id=mapping_id
            )
            eval_source = source_for_variant(
                dataset, get_settings().market_data_provider, mapping_id
            )

        if snapshot_key:
            # The key wins over whatever the variant resolver or the unkeyed
            # symbol-set match would have picked: this is the whole point of
            # the flag. get_or_create_dataset_snapshot REFUSES a key whose
            # stored symbols differ from the ones just requested (a DataSnapshot
            # is immutable once created), so a typo cannot quietly reinterpret
            # an existing dataset's provenance.
            from signalforge.research.promotion import get_or_create_dataset_snapshot

            try:
                snap = get_or_create_dataset_snapshot(
                    session,
                    key=snapshot_key,
                    symbols=list(syms or cfg.universe),
                    description=f"keyed evaluation dataset {snapshot_key!r}",
                    source_note=f"symbols resolved from --symbols/--dataset {dataset!r}",
                )
            except ValueError as exc:
                typer.secho(str(exc), fg=typer.colors.RED)
                raise typer.Exit(code=1) from None
            syms = list(snap.symbols_json)
            typer.secho(
                f"dataset snapshot {snap.key!r} (id {snap.id}, {len(syms)} symbols) — "
                f"gate 9's sealed test is keyed to THIS dataset",
                fg=typer.colors.CYAN,
            )

        any_passed = False
        for strat in strategies:
            result = evaluate_promotion(
                session,
                strat,
                symbols=syms,
                start=start,
                end=end,
                source=eval_source,
                config=cfg,
                dataset_snapshot=snap,
            )
            any_passed = any_passed or result.passed
            colour = typer.colors.GREEN if result.passed else typer.colors.YELLOW
            typer.secho(
                f"\n{result.strategy_key} v{result.version}  ->  {result.verdict}",
                fg=colour,
                bold=True,
            )
            typer.echo(
                f"  window {result.window_start}..{result.window_end}  "
                f"universe {len(result.universe)} symbols  config_hash {result.config_hash[:12]}  "
                f"git_sha {result.git_sha}  dataset_snapshot_id {result.dataset_snapshot_id}"
            )
            for g in result.gates:
                mark = "PASS" if g.passed else "FAIL"
                mark_colour = typer.colors.GREEN if g.passed else typer.colors.RED
                typer.secho(f"  [{mark}] {g.number}. {g.name}: {g.detail}", fg=mark_colour)
            # Multiple-testing disclosure (R2) — printed for FAILING
            # evaluations too: an undisclosed failed look is exactly the leak
            # this counter exists to close.
            typer.echo(f"  sealed looks: {_sealed_look_summary(result)}")

        if not any_passed:
            typer.echo()
            typer.secho(
                "NO TRADE — insufficient evidence or poor risk/reward",
                fg=typer.colors.YELLOW,
                bold=True,
            )
    typer.echo("Research signal only — no order was placed.")


@app.command("symbol-continuity-backfill")
def symbol_continuity_backfill_cmd(
    old_symbol: Annotated[str, typer.Option(help="Predecessor symbol, e.g. FB.")],
    new_symbol: Annotated[str, typer.Option(help="Successor symbol, already ingested, e.g. META.")],
    since: Annotated[str, typer.Option(help="YYYY-MM-DD; predecessor backfill start.")] = "",
    until: Annotated[
        str,
        typer.Option(
            help="YYYY-MM-DD; outer bound for the predecessor backfill "
            "(its actual last session is detected empirically, not assumed)."
        ),
    ] = "",
) -> None:
    """Investigate and (only if verified) bridge a symbol rename / ticker change.

    1. Ingests ``old_symbol``'s own history via the configured licensed
       provider — into its own instrument; never touches ``new_symbol``'s data.
    2. Builds a new, versioned ``SymbolContinuityMapping`` from the two
       symbols' already-ingested bars and validates continuity around the
       seam: session gaps, price continuity, volume, split-adjustment status,
       date ordering, duplicate prevention, and source provenance.
    3. Only if every check passes, materializes a derived, separately-labelled
       continuous series (old_symbol before the seam + new_symbol after it).
       ``old_symbol``/``new_symbol``'s own instruments are never modified.

    Prints the full evidence either way, including any pre-transition data
    found under ``new_symbol`` (evidence of an unrelated prior ticker holder)
    — disclosed, never silently dropped. Research data only: this command
    creates no paper position, alert, brokerage interaction, or trade
    recommendation.
    """
    ensure_not_engaged()
    from signalforge.config import get_settings
    from signalforge.data.adapters.registry import get_primary_adapter
    from signalforge.data.symbol_continuity import (
        backfill_predecessor_symbol,
        build_and_validate_mapping,
        materialize_continuous_series,
    )
    from signalforge.db.session import session_scope

    settings = get_settings()
    end = date.fromisoformat(until) if until else date.today()
    start = date.fromisoformat(since) if since else end - timedelta(days=365 * 10)

    with session_scope(write=True) as session:
        adapter = get_primary_adapter(settings)
        typer.echo(
            f"Backfilling {old_symbol.upper()} [{start}..{end}] via {adapter.provider_name}..."
        )
        result = backfill_predecessor_symbol(session, adapter, old_symbol, start, end)
        if result.error:
            typer.secho(f"backfill error: {result.error}", fg=typer.colors.RED)
            raise typer.Exit(code=1)
        typer.echo(f"  {result.bars_written} bars written, {result.bars_skipped} skipped")

        mapping = build_and_validate_mapping(
            session, old_symbol=old_symbol, new_symbol=new_symbol, source=adapter.provider_name
        )
        colour = typer.colors.GREEN if mapping.validation_status == "verified" else typer.colors.RED
        typer.secho(
            f"\n{old_symbol.upper()} -> {new_symbol.upper()} mapping v{mapping.version}: "
            f"{mapping.validation_status.upper()}",
            fg=colour,
            bold=True,
        )
        typer.echo(
            f"  effective_date={mapping.effective_date}  "
            f"last_old_session={mapping.last_old_session}"
        )
        for c in mapping.validation_evidence_json.get("checks", []):
            mark = "PASS" if c["passed"] else "FAIL"
            mcolour = typer.colors.GREEN if c["passed"] else typer.colors.RED
            typer.secho(f"  [{mark}] {c['name']}: {c['detail']}", fg=mcolour)
        contam = mapping.validation_evidence_json.get("diagnostics", {}).get(
            "pre_transition_contamination", {}
        )
        if contam.get("found"):
            typer.secho(f"  [DISCLOSED] {contam['note']}", fg=typer.colors.YELLOW)

        if mapping.validation_status == "verified":
            inst, written = materialize_continuous_series(session, mapping)
            typer.echo(
                f"\nMaterialized {inst.symbol}: {written} bars written (0 = already materialized)"
            )
        else:
            typer.secho(
                f"\nNo bridge materialized. {new_symbol.upper()} must be EXCLUDED from any "
                "backtest/promotion evaluation needing continuous history through this "
                "corporate action, rather than silently blended.",
                fg=typer.colors.YELLOW,
            )
    typer.echo(
        "Research data only — no paper position, alert, brokerage interaction, or trade "
        "recommendation was created."
    )


@app.command("promotion-dataset-comparison")
def promotion_dataset_comparison_cmd(
    since: Annotated[str, typer.Option(help="YYYY-MM-DD; default: 10 years back.")] = "",
    until: Annotated[str, typer.Option(help="YYYY-MM-DD; default: today.")] = "",
) -> None:
    """Run every default strategy through the promotion pipeline once per FB/META
    dataset variant (baseline, ex_meta, and — if a verified continuity mapping
    exists — meta_continuity_corrected) and print a side-by-side summary.

    Each variant's sealed test is independently locked (see DataSnapshot) —
    running this never recomputes or overwrites another variant's result.
    """
    ensure_not_engaged()
    from signalforge.config import get_settings
    from signalforge.data.symbol_continuity import latest_mapping
    from signalforge.db.session import session_scope
    from signalforge.research.fb_meta_universe_comparison import run_comparison

    end = date.fromisoformat(until) if until else date.today()
    start = date.fromisoformat(since) if since else end - timedelta(days=365 * 10)

    with session_scope(write=True) as session:
        mapping = latest_mapping(session, "FB", "META")
        derived_symbol = (
            mapping.derived_symbol if mapping and mapping.validation_status == "verified" else None
        )
        mapping_id = mapping.id if mapping and derived_symbol else None
        if derived_symbol is None:
            typer.secho(
                "no verified FB->META continuity mapping found — running baseline and ex_meta "
                "only (skipping meta_continuity_corrected)",
                fg=typer.colors.YELLOW,
            )

        results = run_comparison(
            session,
            derived_symbol=derived_symbol,
            mapping_id=mapping_id,
            start=start,
            end=end,
            provider=get_settings().market_data_provider,
        )

        for variant, rows in results.items():
            typer.secho(f"\n=== {variant} ===", bold=True)
            for r in rows:
                colour = typer.colors.GREEN if r.passed else typer.colors.YELLOW
                n_pass = sum(1 for g in r.gates if g.passed)
                typer.secho(
                    f"  {r.strategy_key} v{r.version}: {n_pass}/{len(r.gates)} gates  ->  "
                    f"{r.verdict}",
                    fg=colour,
                )
    typer.echo("\nResearch signal only — no order was placed.")


@app.command()
def alerts() -> None:
    """Evaluate the alert policy and dispatch anything due (nothing until enabled in Settings)."""
    ensure_not_engaged()
    from signalforge.alerts.dispatch import run_alert_cycle
    from signalforge.db.session import session_scope

    with session_scope(write=True) as session:
        r = run_alert_cycle(session)
    typer.echo(
        f"alerts: enabled={r.enabled} planned={r.planned} sent={r.sent} "
        f"suppressed={len(r.suppressed)}"
    )
    for s in r.suppressed:
        typer.secho(f"  - suppressed: {s}", fg=typer.colors.YELLOW)


@app.command("scan-approved-scope")
def scan_approved_scope_cmd(
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Bypass the fresh/complete-data gate (manual, supervised use only; "
            "the scheduled path never bypasses it).",
        ),
    ] = False,
) -> None:
    """Scan, per PAPER_APPROVED strategy version, EXACTLY the dataset that
    version's own approval was granted on (its newest passing evaluation's
    dataset snapshot and source — not the default watchlist) so the
    candidates can pass research.approval_scope's five-part match. Versions
    sharing a (snapshot, horizon, source) are scanned together. The same
    code runs automatically at the end of the daily EOD job; both are
    hard-gated, per approved universe, on fresh, complete data unless
    --force.

    Read-only research: creates ScanRun/Candidate rows only, never an
    alert, paper position, or brokerage interaction.
    """
    ensure_not_engaged()
    from signalforge.db.session import session_scope
    from signalforge.research.approved_scope_scan import run_approved_scope_scan

    with session_scope(write=True) as session:
        report = run_approved_scope_scan(session, enforce_readiness=not force)
    for s in report.skipped_versions:
        typer.secho(
            f"  SKIPPED strategy_version_id={s['strategy_version_id']} "
            f"({s['strategy']} v{s['version']}): {s['reason']}",
            fg=typer.colors.YELLOW,
        )
    for b in report.blocked_universes:
        typer.secho(
            f"  BLOCKED snapshot {b['dataset_snapshot_id']} ({b['dataset_key']}, "
            f"{b['n_symbols']} symbols, {b['source']}): {b['reason']}",
            fg=typer.colors.YELLOW,
        )
    if not report.ran:
        typer.secho(f"NOT RUN — {report.blocked_reason}", fg=typer.colors.YELLOW, bold=True)
        raise typer.Exit(code=2)
    typer.echo(
        f"Scanned {len(report.runs)} approved group(s) over {report.n_symbols} distinct symbols; "
        f"horizons: {', '.join(report.horizons)}"
        + ("  [readiness gate BYPASSED with --force]" if force else "")
    )
    for r in report.runs:
        typer.secho(
            f"  {r['horizon']} on snapshot {r['dataset_snapshot_id']} ({r['dataset_key']}, "
            f"{r['n_symbols']} symbols, {r['source']}) for strategy_version_ids="
            f"{r['strategy_version_ids']}: scanned={r['scanned']} "
            f"candidates={r['candidates']} no_trade={r['no_trade']}",
            fg=typer.colors.GREEN,
        )
    typer.echo("Research signal only — no order was placed.")


def _echo_options_paper_section(session: Session) -> None:
    """Print the SIMULATED options paper book's operating state. READ-ONLY.

    Deliberately printed even when the account does not exist: "no options
    account" is the state of this deployment today and the honest thing to show,
    not something to hide behind a conditional."""
    from signalforge.research.paper_probation import options_paper_status

    s = options_paper_status(session)
    chain = s["eod_chain"]
    auto = s["auto_simulate"]
    typer.secho("\noptions paper book (SIMULATED, separate account)", fg=typer.colors.CYAN)
    if not s["exists"]:
        typer.secho(
            f"  account {s['account']!r}: DOES NOT EXIST — the options EOD chain returns "
            "immediately and nothing options-side can run",
            fg=typer.colors.YELLOW,
        )
    else:
        typer.echo(
            f"  account {s['account']!r}: cash {s['cash']:,.2f}  collateral "
            f"{s['collateral_reserved']:,.2f}  spendable {s['spendable_cash']:,.2f}"
        )
        typer.echo(f"  open structures: {s['n_open']}")
        for st in s["open_structures"]:
            typer.echo(
                f"    #{st['position_id']} {st['underlying']} {st['structure_type']} "
                f"x{st['contracts']} exp {st['expiration']} (dte {st['dte']})  "
                f"R {st['r_dollars']:,.2f}  collateral {st['collateral_reserved']:,.2f}"
            )
    rec = s["reconciliation"]
    if rec is None:
        typer.secho(
            "  reconciliation: NONE — condition AA refuses to open without a dated, clean "
            "report (absence is never evidence of health)",
            fg=typer.colors.YELLOW,
        )
    else:
        typer.secho(
            f"  reconciliation {rec['as_of']} ({rec['age_days']}d old): "
            + ("clean" if rec["clean"] else f"DIVERGENT {rec['findings']}"),
            fg=typer.colors.GREEN if rec["clean"] and rec["age_days"] <= 1 else typer.colors.YELLOW,
        )
    typer.echo(
        f"  {chain['setting_key']}: {'ON' if chain['enabled'] else 'OFF'}"
        f"   {auto['setting_key']}: {'ON' if auto['enabled'] else 'OFF'} "
        f"(cap {auto['max_per_day']}/day)"
    )
    if chain["last_run_at"] is None:
        typer.echo(f"  {chain['job']}: never run")
    else:
        typer.echo(
            f"  {chain['job']}: last {chain['last_run_status']} at {chain['last_run_at']} "
            f"({chain['hours_since_last_run']}h ago)"
        )
    typer.secho(f"  {s['notice']}", fg=typer.colors.YELLOW)


@app.command("paper-probation-status")
def paper_probation_status_cmd() -> None:
    """Show every PAPER_APPROVED strategy's exact approved scope, whether
    paper_probation_enabled is currently on, and the SIMULATED options paper
    book's state (account, open structures, reconciliation age, last EOD chain
    run). Read-only."""
    from sqlalchemy import select

    from signalforge.db.models import Strategy, StrategyVersion
    from signalforge.db.session import session_scope
    from signalforge.domain import StrategyStatus
    from signalforge.research.approval_scope import approved_scopes
    from signalforge.research.approved_scope_scan import approved_scan_groups
    from signalforge.settings_store import effective_research_config, get_setting

    with session_scope() as session:
        enabled = bool(get_setting(session, "paper_probation_enabled", False))
        typer.secho(
            f"paper_probation_enabled = {enabled}",
            fg=typer.colors.GREEN if enabled else typer.colors.YELLOW,
            bold=True,
        )
        rows = session.execute(
            select(Strategy, StrategyVersion)
            .join(StrategyVersion, StrategyVersion.strategy_id == Strategy.id)
            .where(Strategy.status == StrategyStatus.PAPER_APPROVED)
        ).all()
        if not rows:
            typer.echo("No PAPER_APPROVED strategy exists.")
            _echo_options_paper_section(session)
            return
        groups, skipped = approved_scan_groups(session)
        scanned_by_version = {vid: g for g in groups for vid in g.strategy_version_ids}
        skipped_by_version = {int(s["strategy_version_id"]): s["reason"] for s in skipped}
        for strat, ver in rows:
            typer.echo(f"\n{strat.name} v{ver.version} (strategy_version_id={ver.id})")
            for scope in approved_scopes(session, ver.id):
                typer.echo(
                    f"  approved scope: dataset_snapshot_id={scope.dataset_snapshot_id}  "
                    f"config_hash={scope.config_hash[:12]}  spec_hash={scope.spec_json_hash[:12]}  "
                    f"sources={sorted(scope.sources)}  universe={len(scope.universe)} symbols"
                )
            live_hash = effective_research_config(session).config_hash
            in_scope = any(sc.config_hash == live_hash for sc in approved_scopes(session, ver.id))
            verdict = (
                "MATCHES an approved scope"
                if in_scope
                else "matches NO approved scope — re-evaluate before a live scan can qualify"
            )
            typer.secho(
                f"  live research config hash {live_hash[:12]} {verdict}",
                fg=typer.colors.GREEN if in_scope else typer.colors.RED,
            )
            grp = scanned_by_version.get(ver.id)
            if grp is not None:
                typer.secho(
                    f"  approved-scope scan: {grp.horizon.value} on snapshot "
                    f"{grp.dataset_snapshot_id} ({grp.dataset_key}, {len(grp.symbols)} symbols, "
                    f"{grp.source})",
                    fg=typer.colors.GREEN,
                )
            else:
                typer.secho(
                    "  approved-scope scan: NOT SCANNED — "
                    + skipped_by_version.get(
                        ver.id, "version is not eligible (INTRADAY, or version not PAPER_APPROVED)"
                    ),
                    fg=typer.colors.RED,
                )
        _echo_options_paper_section(session)
    typer.echo("\nResearch signal only — no order was placed.")


@app.command("paper-probation-enable")
def paper_probation_enable_cmd(
    yes: Annotated[bool, typer.Option("--yes", help="Skip the confirmation prompt.")] = False,
) -> None:
    """Turn ON candidate-trade alerts for PAPER_APPROVED strategies, scoped
    strictly to their exact approved dataset (research.approval_scope).

    Does NOT touch auto-simulation (stays off) or paper-trade acceptance
    (stays manual). Does NOT bypass the two-alerts-per-day cap, quiet hours,
    the stale-data block, or the mandatory "Research signal only" text --
    all unchanged. Run this only after reviewing the dataset-scope test
    results and the Paper Probation dashboard page.
    """
    ensure_not_engaged()
    from signalforge.db.session import session_scope
    from signalforge.settings_store import set_setting

    if not yes:
        typer.confirm(
            "Enable candidate-trade alerts for PAPER_APPROVED strategies "
            "(scoped to their exact approved dataset)?",
            abort=True,
        )
    with session_scope(write=True) as session:
        set_setting(session, "paper_probation_enabled", True)
    typer.secho("paper_probation_enabled = True", fg=typer.colors.GREEN, bold=True)
    typer.echo("Research signal only — no order was placed.")


@app.command("paper-probation-disable")
def paper_probation_disable_cmd() -> None:
    """Turn candidate-trade alerts back OFF (e.g. to pause the probation)."""
    ensure_not_engaged()
    from signalforge.db.session import session_scope
    from signalforge.settings_store import set_setting

    with session_scope(write=True) as session:
        set_setting(session, "paper_probation_enabled", False)
    typer.secho("paper_probation_enabled = False", fg=typer.colors.YELLOW, bold=True)


universe_app = typer.Typer(
    help="Liquid U.S. research-universe pipeline (grouped-daily bulk; EOD only; research only)."
)
app.add_typer(universe_app, name="universe")


@universe_app.command("update")
def universe_update_cmd(
    sessions: Annotated[int | None, typer.Option(help="Override backfill_sessions.")] = None,
    max_minutes: Annotated[int | None, typer.Option(help="Override the runtime budget.")] = None,
    no_scan: Annotated[
        bool, typer.Option("--no-scan", help="Skip the research scan stage.")
    ] = False,
) -> None:
    """Run one budgeted, resumable update now (discovery -> bulk backfill ->
    screen -> normalize eligible -> scan). Ignores the config `enabled` flag
    because this is an explicit operator action; never alerts or trades."""
    ensure_not_engaged()
    from signalforge.db.session import session_scope
    from signalforge.settings_store import effective_research_config
    from signalforge.universe.pipeline import run_universe_update

    with session_scope(write=True) as session:
        cfg = effective_research_config(session).universe_pipeline
        overrides: dict[str, object] = {}
        if sessions is not None:
            overrides["backfill_sessions"] = sessions
        if max_minutes is not None:
            overrides["max_runtime_seconds"] = max_minutes * 60
        if overrides:
            cfg = cfg.model_copy(update=overrides)
        rep = run_universe_update(session, cfg=cfg, do_scan=not no_scan)
    _print_universe_report(rep)


def _print_universe_report(rep: Any) -> None:
    b = rep.backfill or {}
    sc = rep.screen or {}
    typer.secho(f"universe update: {rep.seconds}s  stopped={rep.stopped_reason or '-'}", bold=True)
    if rep.discovery:
        typer.echo(
            f"  discovered {rep.discovery['discovered_all_types']} tickers (all types), "
            f"in scope {rep.discovery['in_scope']}"
        )
    typer.echo(
        f"  backfill: fetched {b.get('fetched')} skipped {b.get('skipped_existing')} "
        f"empty {b.get('empty')} failed {b.get('failed')} -> {b.get('sessions_archived')} sessions "
        f"({b.get('archive_bytes', 0) / 1e6:.1f} MB) stopped={b.get('stopped_reason') or '-'}"
    )
    if sc:
        typer.echo(
            f"  screen: {sc['discovered']} discovered -> {sc['in_scope']} in scope -> "
            f"{sc['eligible']} eligible  (sessions {sc['sessions_used']}, "
            f"snapshot #{sc['dataset_snapshot_id']})"
        )
        for reason, n in sorted(sc.get("excluded_by_reason", {}).items(), key=lambda kv: -kv[1]):
            typer.echo(f"    excluded {reason}: {n}")
        for flag, n in sorted(sc.get("flags", {}).items()):
            typer.echo(f"    flag {flag}: {n}")
    if rep.normalize:
        nz = rep.normalize
        typer.echo(
            f"  normalize: {nz['symbols']} symbols, {nz['rows_written']} rows written, "
            f"{nz['rows_skipped']} skipped, {nz['sessions']} sessions, {nz['seconds']}s"
        )
    for st in rep.scans:
        typer.echo(
            f"  scan {st['horizon']}: scanned {st['scanned']} excluded {st['excluded']} "
            f"no-trade {st['no_trade']} qualified {st['qualified']}"
        )
    if rep.storage:
        so = rep.storage
        typer.echo(
            f"  storage: archive {so['archive_bytes'] / 1e6:.1f} MB "
            f"({so['archive_sessions']} sessions) + {so['normalized_rows']} normalized rows "
            f"(~{so['normalized_bytes_estimate'] / 1e6:.0f} MB) = "
            f"{so['used_share'] * 100:.1f}% of {so['budget_bytes'] / 1e9:.1f} GB budget; "
            f"db file {(so['db_file_bytes'] or 0) / 1e6:.1f} MB"
        )
    typer.echo(
        "Split-adjusted as of fetch date (NOT point-in-time); active-only discovery (NOT "
        "survivorship-free). Research signal only — no order was placed."
    )


@universe_app.command("enrich-caps")
def universe_enrich_caps_cmd(
    max_requests: Annotated[
        int, typer.Option(help="Reference requests this run (resumable).")
    ] = 500,
    spacing: Annotated[float, typer.Option(help="Seconds between requests.")] = 0.5,
) -> None:
    """Fill CURRENT market caps (never point-in-time) for common stocks that are
    eligible except for an unknown cap, highest ADV$ first. Resumable: re-run
    until it reports 0 remaining, then `universe update` to re-screen."""
    ensure_not_engaged()
    from signalforge.db.session import session_scope
    from signalforge.universe.bulk import GroupedDailyClient
    from signalforge.universe.discovery import enrich_market_caps
    from signalforge.universe.pipeline import cap_enrichment_candidates

    client = GroupedDailyClient(spacing_s=spacing)
    with session_scope(write=True) as session:
        todo = cap_enrichment_candidates(session)
        typer.echo(f"market caps missing for {len(todo)} otherwise-eligible common stocks")
        done = enrich_market_caps(session, client, todo, max_requests=max_requests)
    typer.secho(
        f"enriched {done}; remaining ≈ {max(0, len(todo) - done)} — re-run to continue, then "
        "`signalforge universe update` to re-screen",
        fg=typer.colors.GREEN,
    )
    typer.echo(
        "Current-value market cap only (NOT point-in-time). "
        "Research signal only — no order was placed."
    )


@universe_app.command("sectors")
def universe_sectors_cmd(
    refresh: Annotated[
        bool,
        typer.Option("--refresh", help="Derive and store sectors (without it: read-only status)."),
    ] = False,
    only_missing: Annotated[
        bool, typer.Option("--only-missing", help="Leave instruments that already have a sector.")
    ] = False,
    max_requests: Annotated[
        int, typer.Option(help="Reference requests this run (resumable).")
    ] = 500,
    spacing: Annotated[float, typer.Option(help="Seconds between requests.")] = 0.5,
) -> None:
    """Populate instrument.sector from provider reference data (SIC code ->
    stable sector label; ETFs -> sector-SPDR sector or ETF:<symbol>) so the paper
    ledger's per-sector cap can operate. Unknown stays blank and is capped as
    the single UNKNOWN bucket. Never alerts or trades."""
    import json as _json

    from signalforge.db.session import session_scope
    from signalforge.universe.sectors import refresh_sectors, sector_status

    if not refresh:
        with session_scope() as session:
            typer.echo(_json.dumps(sector_status(session), indent=2))
        typer.echo("read-only status — pass --refresh to derive and store sectors")
        return
    ensure_not_engaged()
    from signalforge.universe.bulk import GroupedDailyClient

    client = GroupedDailyClient(spacing_s=spacing)
    with session_scope(write=True) as session:
        rep = refresh_sectors(session, client, max_requests=max_requests, only_missing=only_missing)
    typer.echo(_json.dumps(rep.to_dict(), indent=2))
    typer.secho(
        f"sectors: {rep.updated} updated, {rep.unknown} still unknown (capped as UNKNOWN), "
        f"{rep.skipped_budget} awaiting a reference request — re-run to continue",
        fg=typer.colors.GREEN,
    )
    typer.echo(
        "SIC-derived labels are approximate (not GICS). "
        "Research signal only — no order was placed."
    )


@universe_app.command("status")
def universe_status_cmd() -> None:
    """Stage counts, exclusions by reason, storage vs budget, last update."""
    import json as _json

    from signalforge.db.session import session_scope
    from signalforge.universe.pipeline import universe_status

    with session_scope() as session:
        st = universe_status(session)
    typer.echo(_json.dumps(st, indent=2, default=str))


grid_app = typer.Typer(
    help=(
        "Mechanical grid strategy (SIMULATED). Not a promotion-gated strategy — "
        "no candidates, no alerts, no brokerage."
    )
)
app.add_typer(grid_app, name="grid")


@grid_app.command("backtest")
def grid_backtest_cmd(
    universe: Annotated[
        str, typer.Option(help="top1000 | top100 | topN | all | a .json/.txt file | A,B,C")
    ] = "top1000",
    top: Annotated[
        int, typer.Option(help="Slice the resolved universe to the top N (0 = all).")
    ] = 0,
    source: Annotated[
        str, typer.Option(help="ohlcv_daily.source — massive | massive_grouped (always explicit).")
    ] = "massive_grouped",
    since: Annotated[
        str, typer.Option(help="Start YYYY-MM-DD (default: earliest available).")
    ] = "",
    until: Annotated[str, typer.Option(help="End YYYY-MM-DD (default: today).")] = "",
    starting_cash: Annotated[float, typer.Option(help="Starting cash.")] = 5_000.0,
    per_symbol_cap: Annotated[float, typer.Option(help="Max cost basis per symbol.")] = 50.0,
    buy_usd: Annotated[float, typer.Option(help="Dollars bought per BUY trigger.")] = 5.0,
    sell_usd: Annotated[float, typer.Option(help="Dollars sold per SELL trigger.")] = 10.0,
    drop_pct: Annotated[float, typer.Option(help="Buy trigger as a FRACTION (0.05 = 5%).")] = 0.05,
    rise_pct: Annotated[float, typer.Option(help="Sell trigger as a FRACTION (0.05 = 5%).")] = 0.05,
    min_order_usd: Annotated[float, typer.Option(help="Skip orders below this notional.")] = 1.0,
    reanchor_on_untradeable_rise: Annotated[
        bool,
        typer.Option(
            help=(
                "Re-anchor when a rise fires with nothing to sell (the grid ratchets up with "
                "price). Off = the strict literal reading, which strands any symbol that rises "
                "before it ever dips."
            )
        ),
    ] = True,
    benchmark: Annotated[str, typer.Option(help="Buy-and-hold benchmark symbol.")] = "SPY",
    snapshot_key: Annotated[
        str, typer.Option(help="Take the symbol list from this DataSnapshot key instead.")
    ] = "",
    symbols: Annotated[
        str, typer.Option(help="Explicit comma-separated symbols; overrides --universe.")
    ] = "",
    rank_by_universe: Annotated[
        bool,
        typer.Option(help="Order the symbols by the grid universe file's liquidity ranking."),
    ] = True,
    out: Annotated[str, typer.Option(help="Report directory (default docs/research/grid).")] = "",
    slug: Annotated[str, typer.Option(help="Report filename stem.")] = "",
    title: Annotated[str, typer.Option(help="Report title.")] = "",
    notes: Annotated[str, typer.Option(help="Extra markdown appended to the report.")] = "",
    trades_in_json: Annotated[
        bool, typer.Option(help="Include every trade + the daily curve in the JSON report.")
    ] = True,
) -> None:
    """READ-ONLY grid backtest over a large daily-close universe.

    Never writes a row: it loads bars through the existing data access and
    writes only the markdown/JSON report. Symbols with no bars in the window
    are reported, not silently dropped.
    """
    from datetime import date as _date

    from signalforge.db.session import session_scope
    from signalforge.gitinfo import git_sha
    from signalforge.grid.config import GridParams
    from signalforge.grid.data import load_grid_series
    from signalforge.grid.engine import run_grid_backtest
    from signalforge.grid.report import write_report
    from signalforge.grid.universe import GridUniverse, load_universe, order_by_rank

    end = _date.fromisoformat(until) if until else _date.today()
    start = _date.fromisoformat(since) if since else _date(1990, 1, 1)
    if start > end:
        typer.secho("--since is after --until", fg=typer.colors.RED)
        raise typer.Exit(code=2)

    with session_scope() as session:
        if symbols:
            uni = load_universe(
                symbols=[s for s in symbols.replace(",", " ").split() if s], top=top or None
            )
        elif snapshot_key:
            from sqlalchemy import select as _select

            from signalforge.db.models import DataSnapshot

            snap = session.scalar(_select(DataSnapshot).where(DataSnapshot.key == snapshot_key))
            if snap is None:
                typer.secho(f"no DataSnapshot with key {snapshot_key!r}", fg=typer.colors.RED)
                raise typer.Exit(code=2)
            syms = [str(s).strip().upper() for s in snap.symbols_json]
            if rank_by_universe:
                try:
                    syms = order_by_rank(syms, top=top or None)
                    note = (
                        "ordered by the grid universe file's 60-session median-dollar-volume rank"
                    )
                except (FileNotFoundError, ValueError) as exc:
                    typer.secho(
                        f"ranking unavailable ({exc}); keeping snapshot order",
                        fg=typer.colors.YELLOW,
                    )
                    syms = syms[:top] if top else syms
                    note = "snapshot order (ranking file unavailable)"
            else:
                syms = syms[:top] if top else syms
                note = "snapshot order"
            uni = GridUniverse(
                name=f"snapshot:{snapshot_key}",
                symbols=tuple(syms),
                source=f"DataSnapshot #{snap.id} {snapshot_key!r}",
                ranking_note=note,
                requested_size=top or len(syms),
            )
        else:
            uni = load_universe(universe, top=top or None)

        params = GridParams(
            starting_cash=starting_cash,
            per_symbol_cap=per_symbol_cap,
            buy_usd=buy_usd,
            sell_usd=sell_usd,
            drop_pct=drop_pct,
            rise_pct=rise_pct,
            min_order_usd=min_order_usd,
            reanchor_on_untradeable_rise=reanchor_on_untradeable_rise,
            universe_name=uni.name,
            universe_size=len(uni.symbols),
        )
        if not params.budget_is_consistent:
            typer.secho(
                f"note: {len(uni.symbols)} symbols x ${per_symbol_cap:,.0f} cap = "
                f"${params.max_committed_usd:,.0f} of budget against "
                f"${starting_cash:,.0f} of cash — cash will bind before the caps do.",
                fg=typer.colors.YELLOW,
            )

        typer.echo(f"loading {len(uni.symbols)} symbols from source={source!r} ...")
        series, _missing = load_grid_series(session, uni.symbols, start, end, source=source or None)
        bench = None
        if benchmark:
            bser, _ = load_grid_series(session, [benchmark], start, end, source=source or None)
            bench = bser.get(benchmark.upper())

    result = run_grid_backtest(
        series,
        params,
        symbols=list(uni.symbols),
        requested=list(uni.symbols),
        benchmark=bench,
        benchmark_symbol=benchmark.upper() if benchmark else "SPY",
    )

    stem = (
        slug
        or f"grid_{uni.name.replace(':', '_')}_{int(per_symbol_cap)}cap_{int(starting_cash)}cash"
    )
    md, js = write_report(
        result,
        slug=stem,
        title=title
        or f"Grid backtest — {uni.name} (cap ${per_symbol_cap:,.0f}, cash ${starting_cash:,.0f})",
        out_dir=out or None,
        universe=uni,
        source=source,
        notes=notes,
        git_sha=git_sha(),
        include_trades=trades_in_json,
    )

    m, b = result.metrics, result.benchmark
    typer.secho(
        f"grid {uni.name}: {len(result.symbols)} symbols with bars "
        f"({len(result.skipped_symbols)} skipped), {result.start} → {result.end}",
        fg=typer.colors.CYAN,
    )
    typer.echo(
        f"  total return {m.total_return_pct:+.2f}%  CAGR {m.cagr_pct:+.2f}%  "
        f"maxDD {m.max_drawdown_pct:.2f}%  trades {m.n_trades:,} "
        f"({m.n_buys:,}b/{m.n_sells:,}s)  exposure {m.exposure:.1%}"
    )
    typer.echo(
        f"  end equity ${m.end_equity:,.2f}  final cash ${result.final_cash:,.2f}  "
        f"symbols at cap {result.symbols_at_cap:,}"
    )
    if b.available:
        typer.echo(
            f"  {b.symbol} buy-and-hold: {b.total_return_pct:+.2f}%  CAGR {b.cagr_pct:+.2f}%  "
            f"maxDD {b.max_drawdown_pct:.2f}%  "
            f"(grid − benchmark {m.total_return_pct - b.total_return_pct:+.2f} pp)"
        )
    else:
        typer.secho(f"  benchmark unavailable: {b.detail}", fg=typer.colors.YELLOW)
    typer.secho(f"reports: {md}  {js}", fg=typer.colors.GREEN)
    typer.echo("Hypothetical research output — no order was placed.")


@grid_app.command("status")
def grid_status_cmd() -> None:
    """Live (paper) grid state: flag, params, cash, positions, recent trades."""
    import json as _json

    from signalforge.app.views import grid_context
    from signalforge.db.session import session_scope

    with session_scope() as session:
        ctx = grid_context(session, trade_limit=10)
    ctx.pop("positions", None)
    ctx.pop("trades", None)
    typer.echo(_json.dumps(ctx, indent=2, default=str))
    typer.echo("Research signal only — no order was placed.")


agents_app = typer.Typer(help="Bounded research agents — read-only reports (contract S14).")
app.add_typer(agents_app, name="agents")


@agents_app.command("run")
def agents_run_cmd(
    agent: Annotated[str, typer.Option(help="Agent name, or 'all'.")] = "all",
) -> None:
    """Run one or every agent now; each writes ONE agent_report row + an audit
    event and nothing else. Never creates a candidate, trade, alert, or setting."""
    ensure_not_engaged()
    from signalforge.agents import all_agents, run_all_agents
    from signalforge.db.session import session_scope

    names = None if agent == "all" else [agent]
    known = {a.name for a in all_agents()}
    if names and names[0] not in known:
        typer.secho(f"unknown agent {agent!r}; known: {sorted(known)}", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    with session_scope(write=True) as session:
        results = run_all_agents(session, names)
    for r in results:
        colour = typer.colors.GREEN if r.status == "ok" else typer.colors.RED
        typer.secho(
            f"\n[{r.agent}] {r.status} ({r.duration_s}s) report #{r.report_id}",
            fg=colour,
            bold=True,
        )
        typer.echo(r.summary)
        if r.missing_data:
            typer.echo(f"missing data: {', '.join(r.missing_data)}")
        if r.narrative:
            typer.echo(r.narrative)


@agents_app.command("roles")
def agents_roles_cmd() -> None:
    """Print every agent's role contract (inputs, outputs, prohibitions, write
    policy) as Markdown — generated from the code, so docs cannot drift."""
    from signalforge.agents import all_agents

    typer.echo(
        "| Agent | Role | Allowed inputs | Outputs | Prohibited | May write | LLM narrative |"
    )
    typer.echo("|---|---|---|---|---|---|---|")
    for a in all_agents():
        typer.echo(
            f"| `{a.name}` | {a.role} | {'; '.join(a.allowed_inputs)} | {'; '.join(a.outputs)} | "
            f"{'; '.join(a.prohibited)} | {a.may_write} | "
            f"{'opt-in, explanatory only' if a.llm_narrative else 'never'} |"
        )


@agents_app.command("status")
def agents_status_cmd() -> None:
    """Latest report per agent."""
    from sqlalchemy import select

    from signalforge.agents import all_agents
    from signalforge.db.models import AgentReport
    from signalforge.db.session import session_scope

    with session_scope() as session:
        for a in all_agents():
            row = session.scalar(
                select(AgentReport)
                .where(AgentReport.agent == a.name)
                .order_by(AgentReport.created_at.desc())
                .limit(1)
            )
            if row is None:
                typer.echo(f"{a.name:22} never run")
            else:
                typer.echo(
                    f"{a.name:22} {row.status:6} {row.created_at.isoformat()[:16]} "
                    f"missing={len(row.missing_data_json)} "
                    f"narrative={'yes' if row.narrative else 'no'}"
                )
    typer.echo("Research signal only — no order was placed.")


ACTIVATION_SETTINGS: dict[str, object] = {
    "alerts_enabled": True,
    "paper_probation_enabled": True,
    "alert_type_enabled:candidate": True,
    "max_alerts_per_day": 2,
}


def _options_activation_rows(session: Session) -> list[tuple[str, bool, str]]:
    """The options paper book, REPORTED inside the activation checklist.

    Every row here is ``True`` by construction and that is deliberate: the
    activation ceremony switches on candidate-only alerts for the EQUITY trial,
    and the options book can neither block it nor be enabled by it. Reporting the
    options state as a *gate* would let an absent options account refuse the
    equity activation, which is exactly backwards. It is reported because an
    operator about to turn something on is owed the state of everything that is
    already wired — the same reason the auto-simulation row is informational.
    """
    from signalforge.research.paper_probation import options_paper_status

    s = options_paper_status(session)
    chain = s["eod_chain"]
    auto = s["auto_simulate"]
    rec = s["reconciliation"]
    if not s["exists"]:
        account_detail = f"{s['account']!r} does not exist — nothing options-side can run"
    else:
        account_detail = (
            f"{s['account']!r} exists: cash {s['cash']:,.0f}, "
            f"collateral {s['collateral_reserved']:,.0f}"
        )
    return [
        ("options paper account (reported; never gates the equity trial)", True, account_detail),
        (
            "options open structures (reported)",
            True,
            f"{s['n_open']} open"
            + (
                ""
                if not s["open_structures"]
                else " on " + ", ".join(sorted({o["underlying"] for o in s["open_structures"]}))
            ),
        ),
        (
            "options collateral reconciliation (reported; condition AA reads it)",
            True,
            (
                "NONE — the second guard refuses to open without a dated clean report"
                if rec is None
                else f"{rec['as_of']} ({rec['age_days']}d old), "
                + ("clean" if rec["clean"] else f"DIVERGENT {rec['findings']}")
            ),
        ),
        (
            f"options EOD chain {chain['job']} (reported)",
            True,
            f"{chain['setting_key']}={'ON' if chain['enabled'] else 'OFF'}; "
            + (
                "never run"
                if chain["last_run_at"] is None
                else f"last {chain['last_run_status']} {chain['hours_since_last_run']}h ago"
            ),
        ),
        (
            "options auto-simulation (reported; separate second setting)",
            True,
            f"{'ON' if auto['enabled'] else 'OFF'} (cap {auto['max_per_day']}/day)",
        ),
    ]


def _activation_preconditions() -> list[tuple[str, bool, str]]:
    """Every fact that must hold before the limited paper-only trial may be
    switched on, plus a read-only options section that reports and never gates.
    Read-only throughout."""
    from sqlalchemy import select

    from signalforge.alerts.channels.discord import DiscordChannel
    from signalforge.alerts.dispatch import alert_type_states
    from signalforge.app.views import ops_status_context
    from signalforge.db.models import Strategy, StrategyVersion
    from signalforge.db.session import session_scope
    from signalforge.domain import StrategyStatus
    from signalforge.research.approval_scope import approved_scopes
    from signalforge.research.approved_scope_scan import approved_scan_groups
    from signalforge.settings_store import effective_research_config, get_setting

    checks: list[tuple[str, bool, str]] = []
    with session_scope() as session:
        approved = session.execute(
            select(Strategy, StrategyVersion)
            .join(StrategyVersion, StrategyVersion.strategy_id == Strategy.id)
            .where(
                Strategy.status == StrategyStatus.PAPER_APPROVED,
                StrategyVersion.status == StrategyStatus.PAPER_APPROVED,
            )
        ).all()
        names = [f"{s.name} v{v.version}" for s, v in approved]
        # NOT a fixed count: any number of approved versions is fine, on any
        # number of dataset snapshots — what must hold is that EVERY one of
        # them is actually reachable by the approved-scope scan, i.e. its
        # newest approved scope resolves to a live, scannable universe.
        groups, skipped = approved_scan_groups(session)
        scannable = {vid for g in groups for vid in g.strategy_version_ids}
        unreachable = [
            f"{s.name} v{v.version} (id={v.id})" for s, v in approved if v.id not in scannable
        ]
        checks.append(
            (
                "every PAPER_APPROVED version has a live-matching scope",
                bool(approved) and not unreachable,
                (
                    f"{len(approved)} approved ({', '.join(names)}) on "
                    f"{len({g.dataset_snapshot_id for g in groups})} snapshot(s)"
                    if not unreachable
                    else "unreachable: "
                    + "; ".join(unreachable)
                    + (" — " + "; ".join(str(s["reason"]) for s in skipped) if skipped else "")
                ),
            )
        )
        scoped = all(approved_scopes(session, v.id) for _s, v in approved)
        checks.append(
            ("every approved version has an exact approved scope", bool(approved) and scoped, "")
        )
        live_hash = effective_research_config(session).config_hash
        hash_ok = bool(approved) and all(
            any(sc.config_hash == live_hash for sc in approved_scopes(session, v.id))
            for _s, v in approved
        )
        checks.append(
            (
                "live research config hash matches an approved scope for every approved version",
                hash_ok,
                live_hash[:12],
            )
        )
        types = alert_type_states(session)
        others_off = not any(v for k, v in types.items() if k != "candidate")
        checks.append(("every non-candidate alert type is OFF", others_off, str(types)))
        auto_sim = bool(get_setting(session, "auto_simulate_qualified_signals", False))
        checks.append(
            (
                "auto-simulation state (operator-authorized either way; guard-gated)",
                True,
                "ON" if auto_sim else "OFF",
            )
        )
        checks.append(
            (
                "Discord webhook configured (URL never shown)",
                DiscordChannel.from_settings() is not None,
                "",
            )
        )
        ops = ops_status_context(session)
        checks.append(
            (
                "worker running (heartbeat)",
                bool(ops["worker"]["running"]),
                ops["worker"].get("detail", ""),
            )
        )
        checks.append(
            ("kill switch released", not ops["kill_switch"].active, ops["kill_switch"].reason)
        )
        # Both data gates are reported PER APPROVED UNIVERSE: with approved
        # versions on more than one dataset snapshot, one collapsed verdict
        # would either hide a stale universe or condemn a healthy one.
        per_universe = ops["freshness"]["per_universe"]
        if per_universe:
            for u in per_universe:
                checks.append(
                    (
                        "daily bars current for last completed session — snapshot "
                        f"{u['dataset_snapshot_id']} {u['dataset_key']} "
                        f"({u['n_symbols']} symbols, {u['source']})",
                        bool(u["current"]),
                        f"newest {u['newest_bar']} vs {ops['freshness']['expected_session']}",
                    )
                )
        else:
            checks.append(
                (
                    "daily bars current for last completed session",
                    bool(ops["freshness"]["current"]),
                    f"newest {ops['freshness']['newest_bar']} vs "
                    f"{ops['freshness']['expected_session']}",
                )
            )
        readiness_rows = ops["readiness"]["universes"]
        if readiness_rows:
            for r in readiness_rows:
                checks.append(
                    (
                        "approved-scope scan data readiness — snapshot "
                        f"{r['dataset_snapshot_id']} {r['dataset_key']} "
                        f"({r['n_symbols']} symbols, {r['source']})",
                        bool(r["ready"]),
                        str(r["reason"]),
                    )
                )
        else:
            checks.append(
                (
                    "approved-scope scan data readiness",
                    bool(ops["readiness"]["ready"]),
                    ops["readiness"]["reason"],
                )
            )
        # Appended LAST and always True: reported, never a gate (see the
        # helper's docstring). The equity verdict above is unchanged.
        checks.extend(_options_activation_rows(session))
    return checks


@app.command("paper-probation-activate")
def paper_probation_activate_cmd(
    yes: Annotated[bool, typer.Option("--yes", help="Actually apply the settings.")] = False,
) -> None:
    """THE single activation action for the limited paper-only U.S. equity trial.

    Verifies every precondition, then — only with --yes — applies exactly:
    alerts_enabled=True, paper_probation_enabled=True,
    alert_type_enabled:candidate=True, max_alerts_per_day=2, in one audited
    transaction. Every other alert type stays OFF, auto-simulation stays OFF,
    paper acceptance stays manual. Refuses if any precondition fails.
    Nothing here places an order: candidates are research signals only.
    """
    ensure_not_engaged()
    from signalforge.db.session import session_scope
    from signalforge.settings_store import get_setting, set_setting

    checks = _activation_preconditions()
    ok_all = True
    for label, ok, note in checks:
        typer.secho(
            f"  {'OK  ' if ok else 'FAIL'} {label} {note[:80]}",
            fg=typer.colors.GREEN if ok else typer.colors.RED,
        )
        ok_all = ok_all and ok
    if not ok_all:
        typer.secho("preconditions not met — nothing changed", fg=typer.colors.RED, bold=True)
        raise typer.Exit(code=2)
    typer.echo(f"pending settings: {ACTIVATION_SETTINGS}")
    if not yes:
        typer.secho("dry pass only — re-run with --yes to apply", fg=typer.colors.YELLOW)
        raise typer.Exit(code=0)
    with session_scope(write=True) as session:
        before = {k: get_setting(session, k) for k in ACTIVATION_SETTINGS}
        for key, value in ACTIVATION_SETTINGS.items():
            set_setting(session, key, value, actor="paper-probation-activate")
    record(
        "paper_probation.activated",
        actor="cli",
        entity="limited_equity_trial",
        before=before,
        after=ACTIVATION_SETTINGS,
    )
    typer.secho(
        "ACTIVATED: candidate-only alerts for the two approved strategies (max 2/day)",
        fg=typer.colors.GREEN,
        bold=True,
    )
    typer.echo("Research signal only — no order was placed.")


@app.command("paper-probation-deactivate")
def paper_probation_deactivate_cmd() -> None:
    """Reverse the activation: alerts OFF, paper probation OFF, candidate type OFF."""
    from signalforge.db.session import session_scope
    from signalforge.settings_store import set_setting

    with session_scope(write=True) as session:
        for key in ("alerts_enabled", "paper_probation_enabled", "alert_type_enabled:candidate"):
            set_setting(session, key, False, actor="paper-probation-deactivate")
    record("paper_probation.deactivated", actor="cli", entity="limited_equity_trial")
    typer.secho(
        "DEACTIVATED: alerts OFF, paper probation OFF, candidate alerts OFF",
        fg=typer.colors.YELLOW,
        bold=True,
    )


@app.command("paper-probation-dry-run")
def paper_probation_dry_run_cmd() -> None:
    """Show exactly what the alert cycle WOULD do if paper probation and
    candidate alerts were enabled — with no side effects: no setting is
    changed, nothing is logged to alert_log, no channel is contacted."""
    from signalforge.alerts.dispatch import ALERT_TYPE_SETTING_KEYS, dry_run_cycle
    from signalforge.db.session import session_scope
    from signalforge.domain import AlertType

    assume = {
        "alerts_enabled": True,
        "paper_probation_enabled": True,
        ALERT_TYPE_SETTING_KEYS[AlertType.CANDIDATE]: True,
        "max_alerts_per_day": 2,
    }
    with session_scope() as session:
        res = dry_run_cycle(session, assume=assume)
    typer.secho("DRY RUN — nothing was changed, logged, or sent", bold=True)
    typer.echo(f"assumed settings: {res.assumed_settings}")
    typer.echo(
        f"channels configured: {res.channels or ['none']} · quiet hours now: {res.quiet_hours} · "
        f"candidate alerts already sent today: {res.already_sent_today}"
    )
    if not res.planned:
        typer.echo("planned alerts: none (no qualified candidate on the latest research scans)")
    for p in res.planned:
        mark = "WOULD SEND" if p.would_send else "blocked   "
        typer.echo(f"  {mark} {p.alert_type:14} {p.subject[:60]!r} — {p.reason}")
    typer.echo(f"would send: {res.would_send}")
    typer.echo("Research signal only — no order was placed.")


notify_app = typer.Typer(help="Notification-channel checks (never creates a paper trade).")
app.add_typer(notify_app, name="notify")


@notify_app.command("test-discord")
def notify_test_discord(
    yes: Annotated[bool, typer.Option("--yes", help="Confirm sending the test message.")] = False,
) -> None:
    """Send ONE test message to the configured Discord webhook. Requires --yes.

    Reads only DISCORD_WEBHOOK_URL. Does not evaluate the alert policy, does not
    enable alerts, and never creates a paper trade.
    """
    from signalforge.alerts.channels.discord import DiscordChannel

    ch = DiscordChannel.from_settings()
    if ch is None:
        typer.secho(
            "No usable DISCORD_WEBHOOK_URL in the local environment (must be a "
            "well-formed https://discord.com/api/webhooks/... URL).",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)
    if not yes:
        typer.secho(
            "This will POST one message to your Discord channel. Re-run with --yes to confirm.",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(code=1)
    ok = ch.send_test()
    record("notify.discord_test", actor="cli", entity="discord", ok=ok)
    typer.secho(
        f"test message {'delivered' if ok else 'FAILED'} — no alert policy evaluated, "
        "no paper trade created. Research signal only — no order was placed.",
        fg=typer.colors.GREEN if ok else typer.colors.RED,
    )
    raise typer.Exit(code=0 if ok else 1)


def _insert_options_eod(specs: list[JobSpec], options_spec: JobSpec | None) -> list[JobSpec]:
    """Place the options EOD chain after ``catch_up`` and before ``agents_daily``.

    Position is not cosmetic here even though APScheduler fires on the cron, not
    on list order: the pinned job-list tests and the Operational Status page both
    read this order, and an operator reading either one should see the options
    chain where it actually runs — after the 17:30 equity chain (and its
    catch-up), before the 18:45 agent reports that read the book it marks.

    ``None`` (no options paper account, or the database momentarily unreadable)
    returns the list unchanged, so the worker's job list is then byte-identical to
    ``default_job_specs()``.
    """
    if options_spec is None:
        return list(specs)
    out = list(specs)
    names = [s.name for s in out]
    at = names.index("agents_daily") if "agents_daily" in names else len(out)
    out.insert(at, options_spec)
    return out


@app.command("run-scheduler")
def run_scheduler() -> None:
    """Run the in-process background scheduler.

    Jobs: one post-close daily EOD update (ingest + rescan, cron 17:30 ET),
    paper mark-to-market, feed-staleness probe, daily briefing, alert cycle
    (policy-gated, OFF by default), strategy-health monitor. Every one of them is
    a no-op while the kill switch is engaged.

    The one exception, and it is deliberate: with the `execution.enabled` setting
    True this worker also carries `execution_cycle`, which brings its own
    kill-switch handling and BRANCHES to a protective-only cycle instead of
    skipping — because a cycle that does not run while the switch is engaged is a
    kill switch that blocks closing. Nothing is armed by default, so the cycle
    submits nothing either way; see `signalforge execution status`.
    """
    import time

    from signalforge.killswitch import KillSwitchEngaged
    from signalforge.scheduler import build_scheduler, run_catch_up

    # Start even while the kill switch is engaged: every job is individually
    # guarded (a logged no-op until release, or — for the execution cycle — a
    # protective-only branch), so refusing to start here would only make a
    # launchd KeepAlive / Docker restart policy crash-loop the worker for the
    # duration of an incident. It would also be the worst possible moment to
    # have no execution heartbeat, reconciliation or drain (D6 §8).
    try:
        ensure_not_engaged()
    except KillSwitchEngaged as exc:
        typer.secho(
            f"kill switch ENGAGED ({exc.state.reason}) — scheduler starting anyway; every job "
            "is a no-op until it is released",
            fg=typer.colors.YELLOW,
        )
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    from signalforge.scheduler import HEARTBEAT_INTERVAL_S, other_live_worker, record_heartbeat
    from signalforge.worker_lock import WorkerAlreadyRunning, acquire_worker_lock

    try:
        lock = acquire_worker_lock()
    except WorkerAlreadyRunning as exc:
        typer.secho(f"refusing to start: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from None
    other = other_live_worker()
    if other:
        typer.secho(f"refusing to start: {other}", fg=typer.colors.RED)
        lock.release()
        raise typer.Exit(code=1)

    started = _dt.now(_UTC)
    from signalforge.worker_health import startup_heartbeat

    with startup_heartbeat(
        lambda: record_heartbeat(None, started_at=started, detail="starting: catch-up running")
    ):
        run_catch_up()
    # D6 ADR §2: the execution job spec is resolved HERE and nowhere else.
    # signalforge.scheduler must not import signalforge.execution (signalforge.app
    # imports the scheduler, and S15b reports indirect chains), and
    # signalforge/app/** must not resolve it either — so the CLI worker is the one
    # sanctioned inbound edge. It returns [] unless execution.enabled is True, so
    # with the default configuration the job list below is byte-identical to
    # default_job_specs().
    from signalforge.execution.cycle import execution_job_specs
    from signalforge.scheduler import default_job_specs

    extra = execution_job_specs(adapter_factory=_execution_cycle_adapter_factory())
    if extra:
        typer.secho(
            f"execution.enabled is True — registering {len(extra)} execution job(s). "
            "Nothing is armed by default; see `signalforge execution status`.",
            fg=typer.colors.YELLOW,
            bold=True,
        )
    # Same rule, same reason, second decision path: signalforge.scheduler must
    # not import signalforge.paper.options_* either, because signalforge.app
    # imports the scheduler and S16 reports indirect chains. The options EOD
    # chain therefore exists ONLY in this worker — started from the app process
    # there is no options job at all. It returns None unless the options paper
    # account exists, so on a deployment that never created one the job list
    # below is byte-identical to default_job_specs().
    from signalforge.paper.options_eod import options_paper_eod_spec

    options_spec = options_paper_eod_spec()
    if options_spec is not None:
        typer.secho(
            f"options paper account present — registering {options_spec.name} at "
            f"{options_spec.cron_hour:02d}:{options_spec.cron_minute:02d} "
            f"{options_spec.cron_tz}. The chain itself is off unless "
            "research.options.paper_eod_enabled is true, and it can open nothing "
            "unless auto_simulate_options_enabled is also on (default off, cap 0/day).",
            fg=typer.colors.YELLOW,
        )
    ordered = _insert_options_eod(default_job_specs(), options_spec)
    scheduler = build_scheduler(specs=[*ordered, *extra])
    scheduler.start()
    record_heartbeat(scheduler, started_at=started)
    typer.secho("scheduler running — Ctrl-C to stop", fg=typer.colors.CYAN)
    last_beat = time.monotonic()
    try:
        while True:
            time.sleep(2)
            if time.monotonic() - last_beat >= HEARTBEAT_INTERVAL_S:
                record_heartbeat(scheduler, started_at=started)
                last_beat = time.monotonic()
    except (KeyboardInterrupt, SystemExit):
        record_heartbeat(scheduler, started_at=started, detail="stopping")
        scheduler.shutdown(wait=False)
    finally:
        lock.release()


@app.command("run-job")
def run_job(
    name: Annotated[
        str,
        typer.Argument(
            help="daily_eod_update | paper_mtm | feed_probe | health_check | news_poll | "
            "daily_briefing | alerts | strategy_health | approved_scope_scan | agents_daily | "
            "universe_update | grid_daily | execution_cycle | options_paper_eod"
        ),
    ],
) -> None:
    """Run one scheduled job once (kill-switch guarded).

    ``execution_cycle`` is the one exception to "kill-switch guarded" and it is
    the deliberate one: ``guarded()`` returns WITHOUT running the body while the
    switch is engaged, which for that job would mean no protective close, no
    drain and no ``cancel_all`` — a kill switch that blocks closing. It carries
    its own wrapper, which reads the same state and branches to a protective-only
    cycle instead.

    ``options_paper_eod`` is resolved here rather than through
    ``default_job_specs()`` for the same reason it is injected into
    ``run-scheduler`` here: the scheduler module may not import the options paper
    layer. It is guarded exactly like every other job, and it is a logged no-op
    while ``research.options.paper_eod_enabled`` is off — which is the point of
    being able to run it by hand.
    """
    from signalforge.execution.cycle import manual_job_entries
    from signalforge.paper.options_eod import OPTIONS_EOD_JOB, job_options_paper_eod
    from signalforge.scheduler import MANUAL_JOBS, default_job_specs, guarded

    execution_jobs = manual_job_entries(adapter_factory=_execution_cycle_adapter_factory())
    if name in execution_jobs:
        execution_jobs[name]()
        typer.secho(f"job {name} finished (self-guarded)", fg=typer.colors.GREEN)
        return
    if name == OPTIONS_EOD_JOB:
        guarded(OPTIONS_EOD_JOB, job_options_paper_eod)()
        typer.secho(f"job {name} finished", fg=typer.colors.GREEN)
        return
    spec = next((s for s in default_job_specs() if s.name == name), None)
    fn = spec.fn if spec is not None else MANUAL_JOBS.get(name)
    if fn is None:
        typer.secho(f"unknown job {name!r}", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    guarded(name, fn)()
    typer.secho(f"job {name} finished", fg=typer.colors.GREEN)


@app.command()
def backup(
    encrypt: Annotated[bool, typer.Option(help="Prompt for a passphrase and gpg-encrypt.")] = False,
    out_dir: Annotated[str, typer.Option(help="Destination directory.")] = "",
) -> None:
    """Consistent snapshot of the local SQLite database."""
    from pathlib import Path

    from signalforge.backup import create_backup

    passphrase = (
        typer.prompt("Backup passphrase", hide_input=True, confirmation_prompt=True)
        if encrypt
        else None
    )
    res = create_backup(out_dir=Path(out_dir) if out_dir else None, gpg_passphrase=passphrase)
    typer.secho(
        f"backup written: {res.path}  ({res.bytes:,} bytes, "
        f"{'encrypted' if res.encrypted else 'plaintext'})",
        fg=typer.colors.GREEN,
    )


@app.command()
def restore(
    path: str,
    yes: Annotated[bool, typer.Option("--yes", help="Skip the confirmation prompt.")] = False,
) -> None:
    """Overwrite the live database with a backup (a .pre-restore copy is kept)."""
    from pathlib import Path

    from signalforge.backup import restore_backup

    if not yes:
        typer.confirm(f"This overwrites the current database with {path}. Continue?", abort=True)
    passphrase = (
        typer.prompt("Backup passphrase", hide_input=True) if path.endswith(".gpg") else None
    )
    dest = restore_backup(Path(path), gpg_passphrase=passphrase)
    typer.secho(f"restored into {dest}", fg=typer.colors.GREEN)


# ---------------------------------------------------------------------------
# The execution command group (D6 ADR §12) — the one sanctioned inbound edge.
#
# `signalforge.cli` is deliberately the ONLY module in the tree that names
# `signalforge.execution` (S15b note 2, safety test T12). The arming ceremony is
# a human-typed entry point with no LLM anywhere on it, and the job spec for the
# execution cycle is injected into `build_scheduler` from here rather than from
# `signalforge.scheduler`, which must gain no import edge because
# `signalforge.app` imports the scheduler and S15b reports indirect chains.
# ---------------------------------------------------------------------------
execution_app = typer.Typer(
    help=(
        "Order execution against a broker's PAPER endpoint. The package is DISABLED by "
        "default and nothing is armed by default; arming is a separate, audited, expiring "
        "operator ceremony per strategy version. The kill switch blocks opening and never "
        "blocks closing."
    )
)
app.add_typer(execution_app, name="execution")


#: The simulated reference equity the ``paper_reference`` account is stood up
#: with: decision 13's "$25,000 SIMULATED" options paper account, which
#: ``docs/PREREGISTRATION_execution_limits_v1.md`` §1 also uses as the reference
#: equity for every percent figure. It is a simulator artifact and is never
#: evidence for any gate; percent limits are evaluated against the broker's own
#: live equity each cycle, never against this number.
PAPER_REFERENCE_SIMULATED_EQUITY = 25_000.0


def _execution_adapter(
    session: Session | None = None, *, expected_account_id: str = ""
) -> BrokerAdapter | None:
    """Build the configured broker adapter, or ``None``.

    The registry's one sanctioned constructor is
    ``execution.brokers.build_adapter``, which refuses twice before it builds
    anything — ``execution.enabled`` must be True, and ``adapter_name`` must name
    a registered adapter, with no default to fall back to — and then passes its
    keyword arguments through to the adapter, none of which has a default:

    ``audit``
        the ``execution_event`` sink, which needs the caller's session, so the
        adapter is bound to the transaction that will record its calls;
    ``expected_account_id``
        the operator-typed account id from the arming request. §13's proof is a
        comparison against a value typed OUT OF BAND; a proof with nothing to
        match is not a proof, and the adapter refuses to be constructed without
        one.
    ``information``
        the pre-submission information set. The ceremony submits nothing, so it
        is handed an EMPTY set deliberately: an accidental submission through a
        ceremony-built adapter then raises rather than inventing a price.
    ``clock``
        the simulated session, taken from the local options calendar so the
        simulator and the calendar cannot disagree by construction.

    ``None`` is returned only when the registry refuses (the layer is disabled,
    or the configured name is unknown) or when no session was supplied — every
    other failure propagates. The old implementation looked up a
    ``resolve_adapter`` attribute that has never existed and swallowed the
    resulting ``AttributeError``, so no adapter was ever built and
    ``execution arm`` failed check S8 ("no is_paper() proof was taken this
    ceremony") on every run.

    ``None`` is not a degraded mode. Every adapter-dependent check then reports
    "could not be evaluated", which BLOCKS opening, and the arming ceremony
    refuses outright because it cannot take an ``is_paper`` proof.
    """
    if session is None:
        # The cycle paths (`run-scheduler`, `run-job`, `execution cycle`) build
        # their session inside the job body, so there is none to bind an audit
        # sink to here. The cycle runs its whole local half with adapter=None
        # and reports "R1: no adapter is configured, so nothing is reconciled",
        # which blocks opening — the fail-closed answer, not a degraded one.
        return None

    from signalforge.execution import brokers as brokers_mod
    from signalforge.execution.brokers.paper_reference import (
        ExecutionEventAudit,
        PaperReferenceOrderStore,
        PreSubmissionInformation,
        SimulatedAccount,
    )
    from signalforge.execution.calendarcheck import evaluate as calendar_evaluate
    from signalforge.execution.intents import MarketClock
    from signalforge.settings_store import effective_research_config

    cfg = effective_research_config(session)
    now = _dt_now_utc()
    try:
        name = brokers_mod.selected_adapter_name(cfg)
    except brokers_mod.AdapterNotSelectable as exc:
        typer.secho(f"no adapter: {exc}", fg=typer.colors.YELLOW)
        return None

    if name != "paper_reference":  # pragma: no cover - only one adapter exists
        raise RuntimeError(
            f"execution.adapter_name={name!r} is registered but this CLI knows how to "
            "assemble the constructor arguments for 'paper_reference' only"
        )
    try:
        account = SimulatedAccount(
            account_id=expected_account_id,
            initial_cash=PAPER_REFERENCE_SIMULATED_EQUITY,
        )
    except ValueError as exc:
        # A mistyped or real-looking account id. Refused here rather than
        # papered over: the whole point of §13 is that the account the adapter
        # answers for is the one the operator typed.
        typer.secho(f"no adapter: {exc}", fg=typer.colors.RED)
        return None

    adapter: BrokerAdapter = brokers_mod.build_adapter(
        cfg,
        audit=ExecutionEventAudit(session),
        account=account,
        expected_account_id=expected_account_id,
        information=PreSubmissionInformation.of([]),
        clock=MarketClock(
            is_open=bool(calendar_evaluate(now, None).market_open_calendar),
            as_of=now,
        ),
        # The DURABLE book. A fresh adapter is built every cycle, so an
        # in-memory one would start flat each time and reconcile CLEAN because
        # the simulator forgot rather than because the OMS explained anything.
        book=PaperReferenceOrderStore(session),
    )
    return adapter


def _dt_now_utc() -> datetime:
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    return _dt.now(_UTC)


def _execution_cycle_adapter_factory() -> Callable[[Session], BrokerAdapter | None]:
    """The adapter factory the execution cycle is registered with.

    Called with the CYCLE's own session, once per cycle, which is the whole
    reason a factory exists rather than an instance: an adapter's audit sink
    writes ``execution_event`` rows through a session, and at registration time
    — inside ``run-scheduler``, before the job has ever fired — there is no such
    session to bind to.

    The expected account id comes from ``expected_account_id_for``, §13 rule 4b's
    own resolver: the most recent ``armed_strategy`` row for this adapter,
    **including disarmed and expired ones**. That inclusion is deliberate and is
    not laxity — disarming ends the authority to open, not the record of which
    account this adapter was pointed at, and the reconciliation that clears an
    ``UNKNOWN`` runs *after* an auto-disarm by construction. Without it the
    system can enter a state it cannot leave without editing the database by
    hand.

    No row has ever been written for this adapter -> ``""`` -> **no adapter**.
    §13 rule 4b's last step is a refusal, not a default: there is nothing to
    prove the account against, so nothing is built and every adapter-dependent
    check reports "could not be evaluated", which blocks opening.
    """

    def factory(session: Session) -> BrokerAdapter | None:
        from signalforge.execution.reconcile import expected_account_id_for
        from signalforge.settings_store import effective_research_config

        adapter_name = effective_research_config(session).execution.adapter_name
        account_id = expected_account_id_for(session, adapter_name)
        if not account_id:
            return None
        return _execution_adapter(session, expected_account_id=account_id)

    return factory


#: Every audited operator action on this group runs as this actor. Not "cli" and
#: not "system": §12's ceremony is a human-typed one, and the audit row has to
#: say a human typed it.
EXECUTION_OPERATOR_ACTOR = "local-user"


def _audit_row(
    session: Session,
    action: str,
    *,
    entity: str = "execution",
    before: object = None,
    after: object = None,
) -> None:
    """Write one ``audit_log`` row, beside the JSONL ``record(...)`` line.

    Both, never one: the JSONL file is what the operator greps during an
    incident and the table is what the Operational Status page reads, and an
    action visible in only one of them is an action that looks like it never
    happened from wherever the reviewer is standing.
    """
    from signalforge.db.models import AuditLog
    from signalforge.db.types import utcnow

    session.add(
        AuditLog(
            ts=utcnow(),
            actor=EXECUTION_OPERATOR_ACTOR,
            action=action,
            entity=entity,
            before_json=before,
            after_json=after,
        )
    )


def _set_execution_enabled(session: Session, *, enabled: bool) -> None:
    """Write ``research_overrides.execution.enabled`` — the SAME mechanism every
    other research override uses (``settings_store``), deep-merged so nothing
    else in the override dict is disturbed."""
    from signalforge.settings_store import (
        RESEARCH_OVERRIDES_KEY,
        get_setting,
        set_setting,
    )

    overrides = dict(get_setting(session, RESEARCH_OVERRIDES_KEY, {}) or {})
    execution = dict(overrides.get("execution") or {})
    execution["enabled"] = enabled
    overrides["execution"] = execution
    set_setting(session, RESEARCH_OVERRIDES_KEY, overrides, actor=EXECUTION_OPERATOR_ACTOR)


def _print_live_execution_posture(session: Session) -> None:
    from signalforge.settings_store import effective_research_config

    cfg = effective_research_config(session)
    typer.secho(
        f"live: execution.enabled = {cfg.execution.enabled}  "
        f"(adapter: {cfg.execution.adapter_name})",
        fg=typer.colors.GREEN if cfg.execution.enabled else typer.colors.YELLOW,
        bold=True,
    )


@execution_app.command("enable")
def execution_enable(
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Required. Without it this command changes nothing."),
    ] = False,
) -> None:
    """Turn the execution layer ON — audited, and nowhere near sufficient.

    Sets `research.execution.enabled` True.
    The one supported way to turn the layer on. Deliberately here and not on the
    web `/settings` form: D6 §12 keeps enabling and arming on the human-typed
    CLI, with no LLM and no app route anywhere on the path (S15b).

    Enabling registers the execution cycle with the scheduler and lets an adapter
    be built. It arms nothing. With no unexpired `armed_strategy` row — and
    nothing is armed by default — zero orders can be submitted whatever this
    flag says. Two independent gates, neither sufficient alone.
    """
    from signalforge.db.session import session_scope

    if not yes:
        typer.secho(
            "REFUSED: --yes is required. Enabling the execution layer is an operator "
            "decision, not a default.",
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(code=2)

    with session_scope(write=True) as session:
        from signalforge.execution import arming as arming_mod
        from signalforge.settings_store import effective_research_config

        before = effective_research_config(session).execution.enabled
        _set_execution_enabled(session, enabled=True)
        _audit_row(
            session,
            "execution.enabled",
            before={"enabled": before},
            after={"enabled": True},
        )
        live = arming_mod.live_armings(session)
        _print_live_execution_posture(session)
        typer.secho(
            f"armed strategies: {len(live)}. Enabling arms nothing; `signalforge execution arm` "
            "is a separate, expiring, audited ceremony per strategy version.",
            fg=typer.colors.YELLOW if live else typer.colors.GREEN,
        )
    record(
        "execution.enabled",
        actor=EXECUTION_OPERATOR_ACTOR,
        entity="execution",
        enabled=True,
    )
    typer.echo("Next: `signalforge execution status`, then `execution limits set`, then `arm`.")


@execution_app.command("disable")
def execution_disable(
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Required. Without it this command changes nothing."),
    ] = False,
    reason: Annotated[str, typer.Option("--reason")] = "operator disabled execution",
) -> None:
    """Turn the execution layer OFF and DISARM every live arming.

    Sets `research.execution.enabled` False.
    Disabling has to disarm, and this is why: the flag stops the cycle being
    registered, so with the layer off nothing runs the per-cycle auto-disarm
    sweep — a live `armed_strategy` row would sit there unexpiring-in-practice
    and come back the moment the flag went on again. Ending the authority to
    open is the whole point of disabling, so it is ended here rather than
    depending on a worker that is no longer scheduled.

    It does NOT close a position, cancel anything at the broker, or liquidate
    anything. Disarming ends the authority to OPEN; `build_close_intent`
    requires no armed row and the protective close lane stays constructible.
    """
    from signalforge.db.session import session_scope
    from signalforge.execution import arming as arming_mod

    if not yes:
        typer.secho(
            "REFUSED: --yes is required.",
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(code=2)

    now = _dt_now_utc()
    disarmed: list[int] = []
    with session_scope(write=True) as session:
        from signalforge.settings_store import effective_research_config

        before = effective_research_config(session).execution.enabled
        _set_execution_enabled(session, enabled=False)

        # The §12 step 7 sweep first, so anything with its own trigger is
        # recorded under that trigger rather than under this one — the reason a
        # row was disarmed is part of the record, and "operator disabled the
        # layer" must not overwrite "the config hash drifted".
        for swept in arming_mod.auto_disarm_sweep(session, now=now, actor=EXECUTION_OPERATOR_ACTOR):
            disarmed.append(swept.armed_strategy_id)
            typer.secho(
                f"DISARMED armed_strategy id={swept.armed_strategy_id} "
                f"({swept.trigger.value}) — {swept.detail}",
                fg=typer.colors.YELLOW,
            )
        for row in arming_mod.live_armings(session):
            arming_mod.disarm(
                session,
                row,
                trigger=arming_mod.DisarmTrigger.OPERATOR,
                detail=reason,
                now=now,
                actor=EXECUTION_OPERATOR_ACTOR,
            )
            disarmed.append(row.id)
            typer.secho(
                f"DISARMED armed_strategy id={row.id} (operator) — {reason}",
                fg=typer.colors.YELLOW,
            )
        _audit_row(
            session,
            "execution.disabled",
            before={"enabled": before},
            after={"enabled": False, "disarmed_armed_strategy_ids": disarmed},
        )
        _print_live_execution_posture(session)
    record(
        "execution.disabled",
        actor=EXECUTION_OPERATOR_ACTOR,
        entity="execution",
        enabled=False,
        disarmed=disarmed,
        reason=reason,
    )
    typer.secho(
        f"{len(disarmed)} arming(s) ended. Any open position is unaffected and is NOT "
        "auto-liquidated: close it by hand, at the broker, or through the protective close lane.",
        fg=typer.colors.GREEN,
    )


# ---------------------------------------------------------------------------
# `signalforge execution limits` — the ONLY constructor for an execution_limits
# row (D6 §7b rule 1). Values come from a pre-registration document and from
# nowhere else: there is no --max-orders-per-day option, and there never will be
# one, because a number typed at the command line is a number nobody
# pre-registered.
# ---------------------------------------------------------------------------
limits_app = typer.Typer(
    help=(
        "The active execution_limits row. Created ONLY from a pre-registration document; "
        "rows are versioned by supersession and never edited. No active, parseable row "
        "BLOCKS opening — 'no limits row' is not 'no limits'."
    )
)
execution_app.add_typer(limits_app, name="limits")


@limits_app.command("show")
def execution_limits_show() -> None:
    """Print the active `execution_limits` row. Read-only."""
    from signalforge.db.session import session_scope
    from signalforge.execution.limits import load_active_limits
    from signalforge.execution.preregistration import active_limits_rows

    with session_scope() as session:
        rows = active_limits_rows(session)
        parsed = load_active_limits(session)
        if not rows:
            typer.secho(
                "execution_limits: NO active row. Opening is BLOCKED — 'no limits row' is not "
                "'no limits'. Create one with:\n"
                "  signalforge execution limits set "
                "--from-preregistration PREREGISTRATION_execution_limits_v1 --yes",
                fg=typer.colors.RED,
            )
            raise typer.Exit(code=1)
        if len(rows) > 1:
            typer.secho(
                f"WARNING: {len(rows)} rows have superseded_at IS NULL; load_active_limits takes "
                f"the newest (id={rows[0].id}) and the others silently shadow nothing.",
                fg=typer.colors.RED,
            )
        row = rows[0]
        typer.secho(
            f"execution_limits id={row.id}  created_at={row.created_at.isoformat()}  "
            f"created_by={row.created_by}",
            bold=True,
        )
        typer.echo(f"  pre-registration: {row.preregistration_doc_id}")
        for column in sorted(_limits_columns()):
            typer.echo(f"  {column} = {getattr(row, column)}")
        if parsed is None:
            typer.secho(
                "…but the row does NOT parse as a LimitSet, so load_active_limits reads it as "
                "None and opening is BLOCKED.",
                fg=typer.colors.RED,
                bold=True,
            )
            raise typer.Exit(code=1)


def _limits_columns() -> tuple[str, ...]:
    from signalforge.execution.preregistration import (
        PREREGISTERED_LIMIT_ROWS,
        PREREGISTRATION_EXECUTION_LIMITS_V1,
    )

    return tuple(PREREGISTERED_LIMIT_ROWS[PREREGISTRATION_EXECUTION_LIMITS_V1])


@limits_app.command("set")
def execution_limits_set(
    from_preregistration: Annotated[
        str,
        typer.Option(
            "--from-preregistration",
            help="The pre-registration document id (a docs/ filename stem). The row's values "
            "come from there and from nowhere else.",
        ),
    ] = "",
    supersede: Annotated[
        bool,
        typer.Option(
            "--supersede",
            help="Deactivate the existing active row and insert a new one. Required whenever "
            "one exists: rows are never edited.",
        ),
    ] = False,
    yes: Annotated[
        bool, typer.Option("--yes", help="Required. Without it this command changes nothing.")
    ] = False,
) -> None:
    """Create the active `execution_limits` row from a pre-registration document.

    Refuses, rather than defaulting, when: no document with that id exists under
    `docs/`; no row is registered in `execution.preregistration` for it; the
    document does not state every column; any stated value differs from the one
    the code would write; or an active row already exists and `--supersede` was
    not asked for.

    Creating the row is necessary for opening and nowhere near sufficient. It
    arms nothing.
    """
    from signalforge.db.session import session_scope
    from signalforge.execution.preregistration import (
        PreregistrationRefused,
        resolve_preregistered_limits,
        set_limits_from_preregistration,
        supersede_note,
    )

    if not from_preregistration:
        typer.secho(
            "REFUSED: --from-preregistration is required. There is no way to type the numbers "
            "in directly, by design (§7b rule 1).",
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(code=2)
    if not yes:
        typer.secho("REFUSED: --yes is required.", fg=typer.colors.RED, bold=True)
        raise typer.Exit(code=2)

    try:
        values, path = resolve_preregistered_limits(from_preregistration)
    except PreregistrationRefused as exc:
        typer.secho(f"REFUSED — {exc}", fg=typer.colors.RED, bold=True)
        raise typer.Exit(code=1) from None
    typer.secho(f"pre-registration: {path}", fg=typer.colors.CYAN)

    now = _dt_now_utc()
    superseded_ids: list[int] = []
    with session_scope(write=True) as session:
        try:
            row, superseded = set_limits_from_preregistration(
                session,
                doc_id=from_preregistration,
                now=now,
                actor=EXECUTION_OPERATOR_ACTOR,
                supersede=supersede,
            )
        except PreregistrationRefused as exc:
            typer.secho(f"REFUSED — {exc}", fg=typer.colors.RED, bold=True)
            raise typer.Exit(code=1) from None

        superseded_ids = [old.id for old in superseded]
        for old in superseded:
            typer.secho(
                f"superseded execution_limits id={old.id} (created {old.created_at.isoformat()})",
                fg=typer.colors.YELLOW,
            )
        _audit_row(
            session,
            "execution.limits_set",
            entity=from_preregistration,
            before={"superseded_execution_limits_ids": superseded_ids},
            after={"execution_limits_id": row.id, "values": dict(values)},
        )
        typer.secho(
            f"execution_limits id={row.id} is active, from {from_preregistration}.",
            fg=typer.colors.GREEN,
            bold=True,
        )
        for column in sorted(values):
            typer.echo(f"  {column} = {values[column]}")
        if superseded_ids:
            typer.secho(f"\n{supersede_note()}", fg=typer.colors.RED, bold=True)
    record(
        "execution.limits_set",
        actor=EXECUTION_OPERATOR_ACTOR,
        entity=from_preregistration,
        superseded=superseded_ids,
    )
    typer.echo(
        "A limits row authorises nothing on its own: every §5 precondition and every §7 "
        "may_open limit must also pass in the same cycle, and nothing is armed."
    )


@execution_app.command("status")
def execution_status() -> None:
    """Show the posture: enabled flag, kill states, dead man, limits, armings.

    Read-only. It never arms, never disarms, and never contacts a broker.
    """
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    from signalforge.db.models import Strategy, StrategyVersion
    from signalforge.db.session import session_scope
    from signalforge.execution import EXECUTION_DISABLED_BY_DEFAULT
    from signalforge.execution import arming as arming_mod
    from signalforge.execution import deadman as deadman_mod
    from signalforge.execution.limits import load_active_limits
    from signalforge.execution.oms import read_cycle_posture
    from signalforge.settings_store import effective_research_config

    now = _dt.now(_UTC)
    posture = read_cycle_posture()
    typer.secho(
        f"EXECUTION_DISABLED_BY_DEFAULT = {EXECUTION_DISABLED_BY_DEFAULT}",
        fg=typer.colors.CYAN,
    )
    with session_scope() as session:
        cfg = effective_research_config(session)
        typer.secho(
            f"execution.enabled = {cfg.execution.enabled}  (adapter: {cfg.execution.adapter_name})",
            fg=typer.colors.GREEN if cfg.execution.enabled else typer.colors.YELLOW,
            bold=True,
        )
        typer.echo(f"cycle branch if it ran now: {posture.branch.value} — {posture.detail}")
        typer.secho(
            f"  may_open={posture.may_open}  may_close={posture.may_close}"
            "   (closing is never blocked)",
            fg=typer.colors.GREEN if posture.may_open else typer.colors.YELLOW,
        )

        limits = load_active_limits(session)
        if limits is None:
            typer.secho(
                "execution_limits: NO active, parseable row — opening is blocked. "
                "'No limits row' is not 'no limits'.",
                fg=typer.colors.RED,
            )
        else:
            typer.echo(
                f"execution_limits id={limits.id}  cycle={limits.cycle_interval_s}s  "
                f"stale_after={limits.execution_stale_after_s}s  "
                f"drain_timeout={limits.drain_timeout_s}s  "
                f"recon_max_age={limits.max_reconciliation_age_s}s  "
                f"pre-registration={limits.preregistration_doc_id}"
            )
        state = deadman_mod.assess(
            session,
            now=now,
            stale_after_s=limits.execution_stale_after_s if limits else 0,
        )
        typer.secho(
            f"dead man: {'ALIVE' if state.alive else 'LAPSED'} — {state.detail}",
            fg=typer.colors.GREEN if state.alive else typer.colors.RED,
        )

        live = arming_mod.live_armings(session)
        if not live:
            typer.secho(
                "armed strategies: NONE. Nothing is armed by default, and that is the "
                "correct state.",
                fg=typer.colors.GREEN,
                bold=True,
            )
        for row in live:
            ver = session.get(StrategyVersion, row.strategy_version_id)
            strat = session.get(Strategy, ver.strategy_id) if ver is not None else None
            expired = row.expires_at <= now
            typer.secho(
                f"ARMED  {strat.name if strat else '?'}@{ver.version if ver else '?'} "
                f"(strategy_version_id={row.strategy_version_id}) on {row.adapter_name} "
                f"account {row.broker_account_id_expected} — expires {row.expires_at.isoformat()}"
                + ("  [EXPIRED; the next cycle disarms it]" if expired else ""),
                fg=typer.colors.RED if expired else typer.colors.YELLOW,
                bold=True,
            )
            typer.echo(
                f"       evidence n={row.evidence_paper_trade_count} "
                f"expectancy={row.evidence_expectancy_r} "
                f"override={row.evidence_override_reason or 'none'}  "
                f"k_prior={row.sealed_look_prior_at_arm}  "
                f"pre-registration={row.preregistration_doc_id}"
            )
    typer.echo(
        "\nArming is necessary and not sufficient: every §5 precondition and every §7 "
        "may_open limit must also pass in the same cycle."
    )


@execution_app.command("arm")
def execution_arm(
    strategy_version_id: Annotated[int, typer.Argument(help="The StrategyVersion.id to arm.")],
    account_id: Annotated[
        str,
        typer.Option(
            "--account-id",
            help="The broker account identifier, typed OUT OF BAND. is_paper() must "
            "prove the broker's own response names exactly this.",
        ),
    ] = "",
    preregistration: Annotated[
        str,
        typer.Option(
            "--preregistration",
            help="The pre-registration document id (a docs/ filename stem). No arming "
            "without one.",
        ),
    ] = "",
    adapter: Annotated[str, typer.Option("--adapter", help="Adapter name.")] = "",
    structure_type: Annotated[str, typer.Option("--structure-type")] = "equity",
    approval_level: Annotated[
        int,
        typer.Option(
            "--approval-level",
            help="The options approval level the OPERATOR asserts (0 = equities only).",
        ),
    ] = 0,
    max_notional: Annotated[float, typer.Option("--max-notional")] = 1000.0,
    max_orders_per_day: Annotated[int, typer.Option("--max-orders-per-day")] = 10,
    expires_days: Annotated[
        int,
        typer.Option(
            "--expires-days",
            help="At most 7 (decision 4). There is no indefinite arming.",
        ),
    ] = 7,
    override_evidence: Annotated[
        str,
        typer.Option(
            "--override-evidence",
            help="Override decision 10's >=20-closed-trades precondition, with a typed "
            "reason. Audited, and the observed n and expectancy are recorded beside it.",
        ),
    ] = "",
    confirm: Annotated[
        str,
        typer.Option(
            "--confirm",
            help="The typed confirmation phrase (see the printed preconditions table).",
        ),
    ] = "",
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Acknowledge the four §12 step 3 facts printed above."),
    ] = False,
) -> None:
    """Arm ONE strategy version against ONE adapter, for at most 7 days.

    Refuses unless every step 1-3 precondition re-verifies LIVE against the
    database and is_paper() proves out against the typed account id. Prints the
    full preconditions table, then requires a TYPED confirmation — not a y/N.
    """
    from datetime import UTC as _UTC
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    from signalforge.db.session import session_scope
    from signalforge.execution import arming as arming_mod
    from signalforge.execution.cycle import active_limits_created_at
    from signalforge.execution.limits import load_active_limits

    now = _dt.now(_UTC)
    adapter_name = adapter or _configured_adapter_name()
    request = arming_mod.ArmingRequest(
        strategy_version_id=strategy_version_id,
        adapter_name=adapter_name,
        broker_account_id_expected=account_id,
        preregistration_doc_id=preregistration,
        max_notional_usd=max_notional,
        max_orders_per_day=max_orders_per_day,
        structure_type=structure_type,
        options_approval_level=approval_level or None,
        expires_at=now + _td(days=expires_days),
        override_evidence_reason=override_evidence,
        acknowledged=yes,
    )
    with session_scope(write=True) as session:
        # Built INSIDE the session: the adapter's audit sink writes
        # ``execution_event`` rows through it, so §13's proof and §10's
        # flat-account read are themselves on the record.
        broker = _execution_adapter(session, expected_account_id=account_id)
        proof = None
        flat: bool | None = None
        if broker is not None:
            try:
                proof = broker.is_paper()
            except Exception as exc:
                typer.secho(f"is_paper() raised: {exc!r}", fg=typer.colors.RED)
            flat = arming_mod.read_adapter_account_is_flat(broker)

        limits = load_active_limits(session)
        created_at = active_limits_created_at(session)
        decision = arming_mod.check_arming_preconditions(
            session,
            request,
            now=now,
            is_paper_proof=proof,
            account_is_flat=flat,
            limits_id=limits.id if limits else None,
            limits_created_at=created_at,
        )
        typer.secho("\nARMING PRECONDITIONS", bold=True)
        for check in decision.checks:
            typer.secho(
                f"  [{'PASS' if check.passed else 'FAIL'}] {check.name}: {check.detail}",
                fg=typer.colors.GREEN if check.passed else typer.colors.RED,
            )
        typer.secho("\nYOU ARE ACKNOWLEDGING:", bold=True)
        for line in arming_mod.acknowledgements():
            typer.echo(f"  {line}")

        if not decision.allowed:
            typer.secho(
                f"\nREFUSED — {decision.first_failure}",
                fg=typer.colors.RED,
                bold=True,
            )
            raise typer.Exit(code=1)

        phrase = arming_mod.confirmation_phrase(strategy_version_id, adapter_name)
        typed = confirm or typer.prompt(f"\nType exactly: {phrase}")
        if typed.strip() != phrase:
            typer.secho(
                "confirmation phrase did not match — nothing was armed", fg=typer.colors.RED
            )
            raise typer.Exit(code=1)

        try:
            row = arming_mod.arm(
                session,
                request,
                now=now,
                is_paper_proof=proof,
                account_is_flat=flat,
                actor="cli",
                limits_id=limits.id if limits else None,
                limits_created_at=created_at,
            )
        except arming_mod.ArmingRefused as exc:
            typer.secho(f"REFUSED — {exc}", fg=typer.colors.RED, bold=True)
            raise typer.Exit(code=1) from None
        record(
            "execution.arm",
            actor="cli",
            entity=str(strategy_version_id),
            armed_strategy_id=row.id,
            adapter=adapter_name,
            expires_at=row.expires_at.isoformat(),
            override_evidence=bool(override_evidence),
        )
        typer.secho(
            f"\nARMED strategy_version_id={strategy_version_id} on {adapter_name} until "
            f"{row.expires_at.isoformat()}. It expires automatically; re-arming is the full "
            "ceremony again.",
            fg=typer.colors.YELLOW,
            bold=True,
        )


@execution_app.command("disarm")
def execution_disarm(
    strategy_version_id: Annotated[int, typer.Argument(help="The StrategyVersion.id to disarm.")],
    reason: Annotated[str, typer.Option("--reason")] = "operator request",
) -> None:
    """End the authority to open for one strategy version.

    Disarming never blocks a protective close: build_close_intent requires no
    armed row, and the row itself is kept (not deleted) so reconciliation and the
    is_paper proof can still read which account this adapter was pointed at.
    """
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    from signalforge.db.session import session_scope
    from signalforge.execution import arming as arming_mod

    now = _dt.now(_UTC)
    with session_scope(write=True) as session:
        rows = arming_mod.live_armings(session, strategy_version_id=strategy_version_id)
        if not rows:
            typer.secho(
                f"no live arming for strategy_version_id={strategy_version_id}",
                fg=typer.colors.YELLOW,
            )
            raise typer.Exit(code=1)
        for row in rows:
            arming_mod.disarm(
                session,
                row,
                trigger=arming_mod.DisarmTrigger.OPERATOR,
                detail=reason,
                now=now,
                actor="cli",
            )
            record(
                "execution.disarm",
                actor="cli",
                entity=str(strategy_version_id),
                armed_strategy_id=row.id,
                reason=reason,
            )
            typer.secho(
                f"DISARMED armed_strategy id={row.id} (strategy_version_id="
                f"{strategy_version_id}) — {reason}",
                fg=typer.colors.GREEN,
            )
        typer.echo(
            "Any open position is unaffected and is NOT auto-liquidated: close it by hand, "
            "at the broker, or through the protective close lane."
        )


@execution_app.command("feed-dead-man")
def execution_feed_dead_man(
    detail: Annotated[str, typer.Option("--detail")] = "manual feed",
) -> None:
    """Write the execution dead-man heartbeat by hand.

    The cycle feeds it at the top of every run in both branches; this exists so
    an operator can prove the row moves, and so a supervised manual session can
    hold it alive. It grants no authority: a fed dead man with nothing armed
    still opens nothing.
    """
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    from signalforge.db.session import session_scope
    from signalforge.execution import deadman as deadman_mod

    now = _dt.now(_UTC)
    with session_scope(write=True) as session:
        deadman_mod.feed(session, now=now, detail=detail)
    record("execution.dead_man_fed", actor="cli", entity="execution", detail=detail)
    typer.secho(f"execution dead man fed at {now.isoformat()}", fg=typer.colors.GREEN)


@execution_app.command("kill")
def execution_kill(
    engage: Annotated[
        bool, typer.Option("--engage/--release", help="Engage or release the execution kill state.")
    ] = True,
    reason: Annotated[str, typer.Option("--reason")] = "manual",
) -> None:
    """Engage or release the EXECUTION-LOCAL kill state (K2).

    Separate from `signalforge killswitch`, which is left exactly as it is: that
    one is fail-OPEN by design across 39 call sites, and this one is fail-CLOSED
    because an unreadable state is not evidence that opening is safe. Both block
    opening. Neither blocks closing.
    """
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    from signalforge.execution.oms import write_execution_kill_state

    state = write_execution_kill_state(
        engaged=engage, reason=reason, actor="cli", now=_dt.now(_UTC)
    )
    record("execution.kill_state", actor="cli", entity="execution", engaged=engage, reason=reason)
    typer.secho(
        f"execution kill state {'ENGAGED' if engage else 'released'} — {state.reason}",
        fg=typer.colors.RED if engage else typer.colors.GREEN,
        bold=True,
    )


@execution_app.command("cycle")
def execution_cycle_cmd() -> None:
    """Run ONE execution cycle by hand (the manual-job entry).

    Runnable while the layer is disabled, which is the point: it is then a cycle
    that finds nothing armed and says so, so the operator can prove what it would
    do without enabling anything.
    """
    from signalforge.execution.cycle import EXECUTION_CYCLE_JOB, manual_job_entries

    manual_job_entries(adapter_factory=_execution_cycle_adapter_factory())[EXECUTION_CYCLE_JOB]()
    typer.secho(f"{EXECUTION_CYCLE_JOB} finished", fg=typer.colors.GREEN)


@execution_app.command("drill")
def execution_drill(
    all_drills: Annotated[
        bool, typer.Option("--all", help="Run every Phase V drill (D6 ADR §21).")
    ] = False,
    name: Annotated[
        list[str] | None,
        typer.Option("--name", help="Run one drill by name, e.g. --name V1. Repeatable."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="List what would run. Opens no database and runs nothing."),
    ] = False,
    report: Annotated[
        bool, typer.Option("--report/--no-report", help="Write the dated drill report.")
    ] = True,
) -> None:
    """Run the Phase V drills against `paper_reference` on a SCRATCH database.

    Each drill builds its own world in a throwaway SQLite file under a temporary
    directory, exercises one refusal the execution layer has to make, and
    records the audit rows it observed. `scripts/execution_drills.py` refuses
    outright if the database it is handed resolves to the live file.

    Run in a SUBPROCESS deliberately: the drills redirect `DATABASE_URL` and
    `SIGNALFORGE_DATA_DIR` at their scratch tree, and that redirection must not
    survive into this process, where the next command would inherit it.

    The drill harness lives under `scripts/` and therefore only exists in a
    source checkout; from an installed wheel this command says so rather than
    guessing.
    """
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parents[2] / "scripts" / "execution_drills.py"
    if not script.is_file():
        typer.secho(
            f"the drill harness is not present at {script} — it ships with the source "
            "checkout, not with an installed package. Clone the repository to run the drills.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=2)

    argv = [sys.executable, str(script)]
    if all_drills:
        argv.append("--all")
    for one in name or []:
        argv += ["--name", one]
    if dry_run:
        argv.append("--dry-run")
    if not report:
        argv.append("--no-report")
    if not all_drills and not name:
        typer.secho(
            "nothing selected: pass --all, or --name V1 (repeatable). --dry-run lists them.",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(code=2)

    completed = subprocess.run(argv, check=False)  # noqa: S603 - fixed argv, no shell
    record(
        "execution.drill",
        actor="cli",
        entity="paper_reference",
        selected="all" if all_drills else ",".join(name or []),
        dry_run=dry_run,
        exit_code=completed.returncode,
    )
    raise typer.Exit(code=completed.returncode)


def _configured_adapter_name() -> str:
    from signalforge.db.session import session_scope
    from signalforge.settings_store import effective_research_config

    try:
        with session_scope() as session:
            return effective_research_config(session).execution.adapter_name
    except Exception:
        return "paper_reference"


def main() -> None:
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
