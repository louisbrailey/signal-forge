# Deployment

Signal Forge is **research / paper-trading / education only**. No service here
connects to a brokerage, places an order, or mirrors a trade. Alerts and
auto-simulation are OFF until you enable them in Settings.

## Local (default) — SQLite, run when you want

```bash
uv run uvicorn signalforge.app.main:app --host 127.0.0.1 --port 8787 --reload
# optionally, in a second terminal, the scheduled jobs:
APP_RUN_SCHEDULER=true uv run python -m signalforge.cli run-scheduler
```

Dashboard: <http://127.0.0.1:8787> (redirects to `/register` on first run).

**Local scheduling only runs while the Mac is awake and this process is up.**
If the machine sleeps, the post-close ingest/scan and news polling are simply
skipped for that day (missed cron jobs are coalesced, not back-run one-per-miss).
For unattended operation use the always-on option below.

## Always-on — Docker Compose, PostgreSQL, persistent worker

Prerequisites: Docker, and a filled-in local `./.env` (never committed).

```bash
docker compose up -d          # postgres + api + worker
docker compose logs -f worker # watch the scheduled jobs
docker compose ps             # health status
docker compose down           # stop; data persists in the named volumes
```

| Service | Role | Restart |
|---|---|---|
| `postgres` | `postgres:16-alpine`, data in the `sf_pg` volume, `pg_isready` healthcheck | `unless-stopped` |
| `api` | runs `alembic upgrade head` then uvicorn on `127.0.0.1:8787` (loopback only), `/healthz` healthcheck | `unless-stopped` |
| `worker` | `signalforge run-scheduler` — post-close EOD ingest/scan (17:30 ET cron), news polling (US sessions only, config-gated OFF), paper mark-to-market, strategy-health, 24/7 health check. A no-op while the kill switch is engaged. | `unless-stopped` |

- **Database**: the containers use `postgresql+psycopg://…` (the `postgres`
  optional dependency). Local dev stays on SQLite — nothing to change.
- **Secrets**: read from `./.env` at runtime via `env_file`; never baked into the
  image (`.dockerignore` excludes `.env`). The encrypted local secret store lives
  on the `sf_secrets` volume. The Discord webhook URL and every API key stay in
  `.env` only.
- **Encrypted secrets at rest**: set `APP_ENCRYPTION_KEY` (32+ bytes) in `.env`
  so the local secret store and session cookies are encrypted and stable across
  restarts.
- **Backups & retention**: `docker compose exec api python -m signalforge.cli backup`
  writes a consistent snapshot to the `sf_data` volume (`/data/backups`). Copy
  that volume off-box on your own schedule; prune old snapshots with your
  retention policy of choice (`find /data/backups -mtime +30 -delete`).
- **Health monitoring**: both `api` and `postgres` expose Docker healthchecks;
  `worker` runs `health_check` every 15 min (DB reachable + feed staleness) and
  emits `SYSTEM_HEALTH` alerts (local log always; Discord/email only if enabled).
- **Restart on failure**: every service is `restart: unless-stopped`.

## What always stays true

- No brokerage login, connector, order placement, execution API, trade mirroring,
  account scraping, or browser automation in any service.
- The LLM (if configured) only summarizes retrieved text and writes the research
  narrative — never entries, exits, sizing, probability, ranking, or risk.
- Every recommendation and Discord message carries
  `Research signal only — no order was placed.`
