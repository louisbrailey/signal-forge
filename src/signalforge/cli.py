"""``signalforge`` command-line entrypoint."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Annotated, Any

import typer

if TYPE_CHECKING:
    from signalforge.research.portfolio_metrics import PortfolioMetrics

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


options_app = typer.Typer(help="Options data + education simulators (no execution path).")
app.add_typer(options_app, name="options")
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
    from signalforge.data.options_ingest import ingest_options_for_underlying
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
    typer.echo(
        "Delayed data (>=15 min). Education/simulation only. "
        "Research signal only — no order was placed."
    )


@options_app.command("backfill")
def options_backfill_cmd(
    underlyings: Annotated[
        str, typer.Option(help="Comma-separated; default: configured set.")
    ] = "",
    since: Annotated[str, typer.Option(help="YYYY-MM-DD; default: today - lookback_days.")] = "",
    until: Annotated[str, typer.Option(help="YYYY-MM-DD; default: today.")] = "",
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
    days: Annotated[int, typer.Option(help="Trailing days to fetch.")] = 5,
    symbols: Annotated[
        str, typer.Option(help="Comma-separated; default: configured universe.")
    ] = "",
) -> None:
    """Fetch intraday bars into the local store (Phase 2)."""
    ensure_not_engaged()
    from datetime import UTC

    from signalforge.config import get_settings
    from signalforge.data.adapters.registry import get_primary_adapter
    from signalforge.data.ingest import ingest_intraday_universe
    from signalforge.db.session import session_scope

    settings = get_settings()
    adapter = get_primary_adapter(settings)
    if not hasattr(adapter, "fetch_intraday_bars"):
        typer.secho(f"{adapter.provider_name} has no intraday feed", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()] or list(
        settings.research.universe
    )
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    with session_scope(write=True) as session:
        report = ingest_intraday_universe(
            session, adapter, syms, start, end, bar_size=bar_size  # type: ignore[arg-type]
        )
    typer.secho(
        f"ingest-intraday[{adapter.provider_name}] {bar_size}: "
        f"{report.bars_written} bars across {len(syms)} symbols",
        fg=typer.colors.GREEN,
    )
    for err in report.errors:
        typer.secho(f"  ! {err}", fg=typer.colors.RED)


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
) -> None:
    """Run the formal 10-gate promotion pipeline for every default strategy.

    The only command that can move a strategy to paper_approved — and only when
    every gate passes on genuine licensed data. Prints a gate-by-gate table per
    strategy and, if nothing clears the bar, the canonical NO-TRADE line.
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
    """Scan every horizon that has a PAPER_APPROVED strategy, using EXACTLY
    that strategy's approved dataset (the ex_meta variant, not the default
    watchlist) so the candidates can pass research.approval_scope's five-way
    match. The same code runs automatically at the end of the daily EOD job;
    both are hard-gated on fresh, complete data unless --force.

    Read-only research: creates ScanRun/Candidate rows only, never an
    alert, paper position, or brokerage interaction.
    """
    ensure_not_engaged()
    from signalforge.db.session import session_scope
    from signalforge.research.approved_scope_scan import run_approved_scope_scan

    with session_scope(write=True) as session:
        report = run_approved_scope_scan(session, enforce_readiness=not force)
    if not report.ran:
        typer.secho(f"NOT RUN — {report.blocked_reason}", fg=typer.colors.YELLOW, bold=True)
        raise typer.Exit(code=2)
    typer.echo(
        f"Scanned {report.n_symbols} symbols (dataset_snapshot_id={report.dataset_snapshot_id}, "
        f"key={report.dataset_key!r}) for horizons: {', '.join(report.horizons)}"
        + ("  [readiness gate BYPASSED with --force]" if force else "")
    )
    for r in report.runs:
        typer.secho(
            f"  {r['horizon']}: scanned={r['scanned']} candidates={r['candidates']} "
            f"no_trade={r['no_trade']} dataset_snapshot_id={r['dataset_snapshot_id']}",
            fg=typer.colors.GREEN,
        )
    typer.echo("Research signal only — no order was placed.")


@app.command("paper-probation-status")
def paper_probation_status_cmd() -> None:
    """Show every PAPER_APPROVED strategy's exact approved scope and whether
    paper_probation_enabled is currently on."""
    from sqlalchemy import select

    from signalforge.db.models import Strategy, StrategyVersion
    from signalforge.db.session import session_scope
    from signalforge.domain import StrategyStatus
    from signalforge.research.approval_scope import approved_scopes
    from signalforge.settings_store import get_setting

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
            return
        for strat, ver in rows:
            typer.echo(f"\n{strat.name} v{ver.version} (strategy_version_id={ver.id})")
            for scope in approved_scopes(session, ver.id):
                typer.echo(
                    f"  approved scope: dataset_snapshot_id={scope.dataset_snapshot_id}  "
                    f"config_hash={scope.config_hash[:12]}  spec_hash={scope.spec_json_hash[:12]}  "
                    f"sources={sorted(scope.sources)}  universe={len(scope.universe)} symbols"
                )
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


@universe_app.command("status")
def universe_status_cmd() -> None:
    """Stage counts, exclusions by reason, storage vs budget, last update."""
    import json as _json

    from signalforge.db.session import session_scope
    from signalforge.universe.pipeline import universe_status

    with session_scope() as session:
        st = universe_status(session)
    typer.echo(_json.dumps(st, indent=2, default=str))


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


def _activation_preconditions() -> list[tuple[str, bool, str]]:
    """Every fact that must hold before the limited paper-only trial may be
    switched on. Read-only."""
    from sqlalchemy import select

    from signalforge.alerts.channels.discord import DiscordChannel
    from signalforge.alerts.dispatch import alert_type_states
    from signalforge.app.views import ops_status_context
    from signalforge.db.models import Strategy, StrategyVersion
    from signalforge.db.session import session_scope
    from signalforge.domain import StrategyStatus
    from signalforge.research.approval_scope import approved_scopes
    from signalforge.settings_store import get_setting

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
        checks.append(
            ("exactly two PAPER_APPROVED strategy versions", len(approved) == 2, ", ".join(names))
        )
        scoped = all(approved_scopes(session, v.id) for _s, v in approved)
        checks.append(
            ("every approved version has an exact approved scope", bool(approved) and scoped, "")
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
        checks.append(
            (
                "daily bars current for last completed session",
                bool(ops["freshness"]["current"]),
                f"newest {ops['freshness']['newest_bar']} vs "
                f"{ops['freshness']['expected_session']}",
            )
        )
        checks.append(
            (
                "approved-scope scan data readiness",
                bool(ops["readiness"]["ready"]),
                ops["readiness"]["reason"],
            )
        )
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


@app.command("run-scheduler")
def run_scheduler() -> None:
    """Run the in-process background scheduler.

    Jobs: one post-close daily EOD update (ingest + rescan, cron 17:30 ET),
    paper mark-to-market, feed-staleness probe, daily briefing, alert cycle
    (policy-gated, OFF by default), strategy-health monitor. Every job is a
    no-op while the kill switch is engaged.
    """
    import time

    from signalforge.killswitch import KillSwitchEngaged
    from signalforge.scheduler import build_scheduler, run_catch_up

    # Start even while the kill switch is engaged: every job is individually
    # guarded (a logged no-op until release), so refusing to start here would
    # only make a launchd KeepAlive / Docker restart policy crash-loop the
    # worker for the duration of an incident.
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
    record_heartbeat(None, started_at=started, detail="starting: catch-up check")
    run_catch_up()
    scheduler = build_scheduler()
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
            "daily_briefing | alerts | strategy_health | approved_scope_scan | agents_daily"
        ),
    ],
) -> None:
    """Run one scheduled job once (kill-switch guarded)."""
    from signalforge.scheduler import MANUAL_JOBS, default_job_specs, guarded

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


def main() -> None:
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
