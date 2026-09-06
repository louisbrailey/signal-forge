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
- No browser automation of any brokerage or trading venue.
- No scraping of Fidelity or any site that prohibits automated access; no
  unofficial/reverse-engineered brokerage APIs.
- No LLM deciding entries, exits, or position size — those are deterministic,
  version-controlled code.
- Account data import is **manual CSV only**.
- An **emergency kill switch** halts polling, scheduled jobs, alerts, and
  paper-trade creation immediately.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design and the safety
invariants (S1–S10), and [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the
phased build plan and acceptance criteria.

## Status

**Phase 0 — scaffold.** Repo skeleton, tooling, CI, and the architectural safety
contracts are in place. No research or data functionality yet. See the
Phase 0 exit report at the bottom of `IMPLEMENTATION_PLAN.md` once complete.

## Requirements

- macOS / Linux
- [`uv`](https://docs.astral.sh/uv/) (manages Python 3.12 and the virtualenv)
- No Node, Docker, Postgres, or Redis needed for Phase 1 (SQLite +
  server-rendered HTMX UI + in-process scheduler).

## Quick start (Phase 1 target)

```bash
cp .env.example .env          # then edit; APP_ENCRYPTION_KEY is required
uv sync --extra dev           # create venv, install deps
make migrate                  # create the SQLite schema
make seed                     # load clearly-labelled SIMULATED demo data
make dev                      # API + scheduler on http://127.0.0.1:8787
```

First run walks you through creating the single local user account. All alerts
are **off** until you finish setup in **Settings**.

## Common commands

| Command | What it does |
|---|---|
| `make dev` | Run the app + in-process scheduler (reload) |
| `make test` | Full pytest suite with coverage |
| `make safety` | Run only the S1–S10 invariant tests |
| `make lint` | Ruff + Black check + mypy + import-linter |
| `make fmt` | Ruff --fix + Black |
| `make migrate` / `make downgrade` | Alembic up / down |
| `make seed` | Load simulated demo data |
| `make backup` | Snapshot the SQLite DB (+ optional gpg) |
| `make killswitch-on` / `-off` | Flip the kill switch from the CLI |

## Layout

```
src/signalforge/     application package (see ARCHITECTURE.md §4.1)
tests/               unit / integration / safety (S1-S10) / e2e
docs/decisions/      lightweight ADRs
reports/             committed backtest / walk-forward reports per strategy version
data/                local runtime state (gitignored)
```

## Security

Secrets come only from `.env` / a local encrypted store, are wrapped in
`SecretStr`, redacted from logs, and never persisted to the database or git.
See [SECURITY.md](SECURITY.md).
