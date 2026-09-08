"""``signalforge`` command-line entrypoint."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Annotated

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

    with session_scope() as session:
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
    with session_scope() as session:
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
        with session_scope() as session:
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

    with session_scope() as session:
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
    if max_total_bars:
        caps = replace(caps, max_total_bars=max_total_bars)
    end = _d.fromisoformat(until) if until else _d.today()
    start = _d.fromisoformat(since) if since else end - timedelta(days=caps.lookback_days)

    adapter = MassiveOptionsAdapter()
    with session_scope() as session:
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
) -> None:
    """Pull recent licensed headlines for the universe; dedupe + persist audit metadata."""
    ensure_not_engaged()
    from signalforge.config import get_settings
    from signalforge.data.adapters.massive_news import MassiveNewsAdapter
    from signalforge.data.news_ingest import ingest_news
    from signalforge.db.session import session_scope

    s = get_settings()
    tk = [x.strip().upper() for x in tickers.split(",") if x.strip()] or list(s.research.universe)
    with session_scope() as session:
        rep = ingest_news(
            session, MassiveNewsAdapter(), tk, lookback_days=lookback_days, limit=limit
        )
    if rep.error:
        typer.secho(f"news: {rep.error}", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    typer.secho(
        f"news: fetched {rep.fetched}, written {rep.written}, duplicates {rep.duplicates} "
        f"(publishers: {', '.join(rep.publishers or [])})",
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

    with session_scope() as session:
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
    with session_scope() as session:
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

    with session_scope() as session:
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

    with session_scope() as session:
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

    with session_scope() as session:
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


@paper_app.command("init")
def paper_init(
    cash: Annotated[float, typer.Option(help="Starting paper cash.")] = 10_000.0,
    name: Annotated[str, typer.Option(help="Account name.")] = "default",
) -> None:
    """Create the paper account if it does not exist (no fixture data, no orders)."""
    from decimal import Decimal

    from sqlalchemy import select

    from signalforge.db.models import PaperAccount
    from signalforge.db.session import session_scope

    with session_scope() as session:
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


@app.command("strategy-health")
def strategy_health() -> None:
    """Compare each strategy's live-paper expectancy to its OOS backtest.

    Auto-downgrades/disables on a sustained, material shortfall (rules in
    ResearchConfig.health_monitor). Every transition is written to the audit log.
    """
    ensure_not_engaged()
    from signalforge.db.session import session_scope
    from signalforge.research.health_monitor import run_health_monitor

    with session_scope() as session:
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
    name: Annotated[
        str,
        typer.Argument(
            help="daily_eod_update | paper_mtm | feed_probe | daily_briefing | alerts | "
            "strategy_health"
        ),
    ],
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
