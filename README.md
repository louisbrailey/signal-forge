# Signal Forge

A **local-first, paper-trading-only** market-research and trade-recommendation
platform for a single user. It ingests licensed market data, searches a
conservative U.S. instrument universe for statistically tested trade candidates,
and produces **transparent, ranked, evidence-based long / short / avoid**
recommendations across four independent holding-period horizons (≈1 hour to
6 months). Every recommendation is paper-traded and explained; every decision is
logged; the system continuously measures whether it has any **out-of-sample**
predictive value.

> **This is research, simulation, alerting, and education software. It is not
> financial advice, and it never places an order.** See [DISCLAIMER.md](DISCLAIMER.md).

## What it will not do

- No brokerage login, credential storage, order placement, or trade execution.
- No browser automation of any brokerage or trading venue; no scraping of sites
  that prohibit it; no unofficial/reverse-engineered brokerage APIs.
- No LLM deciding entries, exits, or position size — those are deterministic,
  version-controlled code. An LLM may only rephrase deterministic facts, and only
  when its output is grounded in those facts.
- Account data import is **manual CSV only**, offline, for analytics.
- An **emergency kill switch** halts polling, scheduled jobs, alerts, and
  paper-trade creation immediately.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the design and the safety invariants
(S1–S12), [docs/METHODOLOGY.md](docs/METHODOLOGY.md) for the verified data
entitlement, pipeline, evaluation method, coverage, and honest limitations,
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for local vs always-on operation,
[reports/EXTENDED_HISTORY_RESULTS.md](reports/EXTENDED_HISTORY_RESULTS.md) for the
10-year frozen-strategy results, and
[docs/architecture-diagram.md](docs/architecture-diagram.md) for diagrams.

## Status — Phase 1 MVP complete

Local end-to-end research loop on daily data: ingest → scan → ranked candidates
with full evidence → paper trade → journal → daily briefing, with a kill switch,
data-freshness labelling, and an alert policy engine. Deployed on SQLite with an
in-process scheduler and a server-rendered HTMX dashboard. **On the shipped
fixture data every candidate is `NO TRADE`** — the intended result: no baseline
strategy has positive out-of-sample expectancy net of costs, so none is promoted
and none alerts.

## Requirements

- macOS / Linux
- [`uv`](https://docs.astral.sh/uv/) — manages Python 3.12 and the virtualenv
- No Node, Docker, Postgres, or Redis for Phase 1

## Quick start

```bash
cp .env.example .env            # optional for local dev; set APP_ENCRYPTION_KEY for stable sessions
uv sync                         # venv + runtime + dev deps (add --extra llm for the narrative)
uv run alembic upgrade head     # create the SQLite schema
uv run signalforge seed         # load clearly-labelled SIMULATED demo data
uv run signalforge backtest-report   # backtests + reports/ + backtest_metric rows
uv run signalforge scan --horizon SHORT_SWING
uv run signalforge scan --horizon MEDIUM_SWING
make dev                        # dashboard on http://127.0.0.1:8787
```

Open the dashboard, create the single local account on first run, then explore
Overview / Scanner / Briefing / Portfolio / Strategy Lab / Journal / Settings.

## Commands

| Command | What |
|---|---|
| `make dev` | Dashboard (+ scheduler if `APP_RUN_SCHEDULER=true`) |
| `make test` / `make safety` | Full suite / just the S1–S10 invariant tests |
| `make lint` | Ruff + Black + mypy + import-linter |
| `make migrate` / `make downgrade` | Alembic up / down |
| `signalforge seed` | SIMULATED demo data (idempotent) |
| `signalforge providers verify` | Probe provider entitlements (read-only; never prints secrets) |
| `signalforge data discover-history` | Binary-search the provider's real history depth |
| `signalforge data ingest-history [--since …] [--resume N]` | Incremental, idempotent, audited deep-history ingest |
| `signalforge data validate` / `data coverage` | Data-quality pass / per-symbol coverage |
| `signalforge ingest [--provider stooq]` | Fetch recent daily bars (kill-switch guarded) |
| `signalforge backtest-report` | Backtests → `reports/` + DB metrics |
| `signalforge backtest-extended` | Frozen-strategy 10y backtest: train / walk-forward / sealed test / regimes / benchmark → `reports/EXTENDED_HISTORY_RESULTS.md` |
| `signalforge options ingest\|simulate` | Read-only options data / education payoff simulators (no execution) |
| `signalforge news ingest\|summarize` | Licensed read-only news / AI summary (never drives a recommendation) |
| `signalforge notify test-discord --yes` | Send one Discord test message (no policy, no paper trade) |
| `signalforge universe` | Preview the conservative liquid-universe screen |
| `signalforge strategy-health` / `sensitivity <k>` / `calibrate <k>` | Health monitor / parameter grid / probability calibration |
| `signalforge scan --horizon …` | Run + persist one horizon's scan |
| `signalforge briefing` | Build today's briefing (LLM narrative if configured) |
| `signalforge alerts` | Evaluate + dispatch alerts (nothing until enabled in Settings) |
| `signalforge paper accept\|mtm\|snapshot` | Paper ledger (SIMULATED — no order placed) |
| `signalforge portfolio import <csv>` / `analytics` | Offline CSV import + exposure |
| `signalforge run-scheduler` / `run-job <name>` | Background jobs |
| `signalforge killswitch on\|off\|status` | Emergency stop |
| `./backup.sh [--encrypt]` / `signalforge restore <path>` | Local DB backup / restore |

## Data providers

- **`fixture`** (default): deterministic, offline, `HISTORICAL` / `SIMULATED`.
  Every value is labelled simulated; nothing is ever shown as "live".
- **`stooq`**: free end-of-day CSV, `END_OF_DAY`, no API key. Split-adjusted
  close only; survivorship bias in free history — both surfaced in the UI.
- A paid real-time provider slots in behind the same adapter interface in
  Phase 3; `latency_category=REALTIME` and "live" labels unlock only with a
  confirmed entitlement.

## Layout

```
src/signalforge/     application package (see ARCHITECTURE.md §4.1)
tests/               unit / integration / safety (S1–S10) / app
reports/             committed backtest / walk-forward reports per strategy version
docs/decisions/      lightweight ADRs
data/                local runtime state — gitignored
```

## Security

Secrets come only from `.env` / the environment, are wrapped in `SecretStr`,
redacted from logs, and never persisted or shown in the UI (Settings shows
set / not-set only). See [SECURITY.md](SECURITY.md).
