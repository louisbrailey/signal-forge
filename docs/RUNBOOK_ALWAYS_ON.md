# Always-On Operations Runbook

Signal Forge is **research / paper-trading / education only**. Nothing in this
runbook connects to a brokerage, places an order, or mirrors a trade — "always
on" here means the scheduled data-ingest, scan, mark-to-market, and
health-monitor jobs keep running unattended; it does not mean anything trades.
Alerts (`alerts_enabled`) and paper probation (`paper_probation_enabled`) ship
**OFF** and stay off through everything in Options A and B below — do not
enable them as part of setup. They are enabled deliberately, by the operator,
using the steps in [Manual enable steps](#manual-enable-steps) at the end of
this document, only after the system has been observed healthy.

---

## Why a sleeping laptop cannot run scheduled jobs

Signal Forge's scheduler (`src/signalforge/scheduler.py`) is
[APScheduler](https://apscheduler.readthedocs.io/)'s `BackgroundScheduler`,
running **in-process** — inside whichever Python process called
`build_scheduler()` (either `signalforge run-scheduler`, or the API process
itself if `APP_RUN_SCHEDULER=true`). It is not a system service, not `cron`,
and it does not exist independently of that process.

Be explicit about what that means:

- **If the Mac is asleep, no job fires.** Not the 17:30 `America/New_York`
  `daily_eod_update` cron job (which, as of this change, also runs the
  approved-scope scan once ingest + rescan finish — see below), not
  `paper_mtm`, not `feed_probe`, not `health_check`, not `news_poll`, not
  `daily_briefing`, not `alerts`, not `strategy_health`. Every one of them is
  a timer inside a process that isn't scheduled to run by the OS while the
  machine is asleep.
- **If the process exits or crashes** (terminal closed, laptop rebooted,
  `uv run` session killed), the same is true — the in-memory scheduler and all
  its timers are gone until something starts a new `run-scheduler` process.
- **Missed jobs are coalesced, not backfilled.** `build_scheduler()` sets
  `job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time":
  3600}` — if the process was down across several missed intervals, only one
  run happens on recovery (not one per miss), and only if the process comes
  back within `misfire_grace_time` (3600s / 1 hour) of a job's scheduled time.
  Miss that window and the job is simply skipped for that cycle.
- **`run_catch_up()` covers only ingest + scan + the approved-scope scan, and
  only on startup.** Both `signalforge run-scheduler` and the API's embedded
  scheduler (when `APP_RUN_SCHEDULER=true`) call
  `run_catch_up(stale_after_hours=18)` once at startup: if the last `ScanRun`
  is missing or more than 18 hours old, it runs `job_ingest`, then
  `job_scan_all`, then `job_approved_scope_scan`, each individually
  kill-switch-guarded. This repairs a stale scan after a long outage — it
  does **not** back-run `paper_mtm`, `alerts`, `strategy_health`,
  `daily_briefing`, `news_poll`, or `health_check` for the time that was
  missed.

The practical conclusion: a MacBook that sleeps overnight, or on lid-close,
will not run the 17:30 ET end-of-day update that night. Nothing "catches up"
that specific miss beyond the next scan being flagged stale and re-run once
the process is next started. For genuinely unattended daily operation, the
machine (or container host) must be powered on, awake, and the scheduler
process running through 17:30 `America/New_York` (with margin for the 1-hour
misfire grace window) every trading day. That is what Option A and Option B
below set up.

---

## Option A — this Mac, always on (do this first)

Runs the existing SQLite/in-process setup from `docs/DEPLOYMENT.md`, kept
alive by `launchd` instead of a foreground terminal.

### Prerequisites

- macOS, with [`uv`](https://docs.astral.sh/uv/) installed (manages Python
  3.12 and the virtualenv — see `README.md` "Requirements").
- The repo cloned to a stable, permanent local path (not a removable or
  network volume) — this runbook uses `/Users/louisbrailey/signal-forge`;
  adjust every path below if yours differs.
- A local `.venv` and applied migrations.

```bash
cd /Users/louisbrailey/signal-forge
uv sync --extra llm
```

```bash
uv run alembic upgrade head
```

This creates `.venv/bin/python`, `.venv/bin/uvicorn`, and `.venv/bin/signalforge`
— the two `launchd` agents below invoke those directly (no `uv run` wrapper,
since `launchd` does not source your shell profile). Everywhere else in this
document, `signalforge ...` / `uv run signalforge ...` commands are meant to
be typed by hand from a terminal at the repo root — matching `README.md`'s
Quick start and `backup.sh` — and assume either an activated venv or the
`uv run` prefix; they are not copy-paste-safe from an arbitrary directory.

### `.env` — variable names to set

Copy `.env.example` to `.env` (git-ignored) and fill in values — this runbook
never reads or prints those values.

```bash
cp .env.example .env
```

| Variable | Purpose |
|---|---|
| `MARKET_DATA_PROVIDER` / `MARKET_DATA_API_KEY` | Primary market-data adapter (`fixture` needs no key) |
| `MARKET_DATA_PROVIDER_SECONDARY` / `MARKET_DATA_API_KEY_SECONDARY` | Optional cross-source reconciliation feed |
| `NEWS_PROVIDER` / `NEWS_API_KEY` | Optional licensed news feed |
| `LLM_PROVIDER` / `LLM_API_KEY` / `LLM_MODEL` | Optional narrative layer only — never on the decision path |
| `NOTIFICATION_PROVIDER` / `NOTIFICATION_API_KEY` | Notification channel selector |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USERNAME` / `SMTP_PASSWORD` / `SMTP_FROM` / `SMTP_TO` | Only used if `NOTIFICATION_PROVIDER=email` |
| `DATABASE_URL` | Leave blank for the default local SQLite file |
| `APP_ENCRYPTION_KEY` | 32+ byte random string — **required** for stable sessions/secrets across restarts; generate below |
| `APP_HOST` / `APP_PORT` / `APP_ENV` / `APP_ALLOWED_HOSTS` | Bind address/port, `dev`/`test`/`prod`, comma-separated allowed hosts |

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Paste the output into `APP_ENCRYPTION_KEY=` in `.env`.

Discord alerting reads `DISCORD_WEBHOOK_URL` (`src/signalforge/config/settings.py`,
`discord_webhook_url`), consumed only by `DiscordChannel`. It is listed in
`.env.example`; leave it blank to keep Discord unconfigured. It must be an
incoming-webhook URL (`https://discord.com/api/webhooks/...`), never a bot
token, and it is never logged, displayed, or sent anywhere but Discord.

Leave `APP_RUN_SCHEDULER` **unset** in this `.env` for Option A. The worker
`launchd` agent below runs `signalforge run-scheduler` as its own process;
also setting `APP_RUN_SCHEDULER=true` on the API process would start a
second, duplicate in-process scheduler inside `uvicorn`.

### Keeping the Mac awake

An in-process scheduler is only as reliable as the machine's power settings.

```bash
pmset -g
```

`(verify on your macOS version)` — labels and locations move between
releases: System Settings → Battery → Options → "Prevent automatic sleeping
on power adapter when the display is off" (called "Energy Saver" on older
macOS). Turn that on, and keep the Mac on AC power.

```bash
sudo pmset -c sleep 0
```

```bash
sudo pmset -c disksleep 0
```

`-c` scopes these to the AC-power ("charger") profile only, so the machine
still sleeps normally on battery. `(verify on your macOS version)` — running
with the lid closed (clamshell) generally requires staying on AC power, and on
some Mac/macOS combinations also requires an external display or being
signed in already; a Mac mini avoids the question entirely and is what
Option B assumes for a headless host.

```bash
caffeinate -i
```

`caffeinate -i` is a **session-level stopgap only** — useful while testing in
a terminal — not a substitute for the `pmset` settings above plus `launchd`
(below). It stops preventing sleep the moment that terminal session ends and
does not survive logout or reboot.

### `launchd` LaunchAgents

Two agents keep the API and the scheduler running independently, each
restarted automatically if it exits.

| Plist key | `com.signalforge.api` | `com.signalforge.worker` |
|---|---|---|
| `Label` | `com.signalforge.api` | `com.signalforge.worker` |
| `WorkingDirectory` | `/Users/louisbrailey/signal-forge` | `/Users/louisbrailey/signal-forge` |
| `ProgramArguments` | `.venv/bin/uvicorn signalforge.app.main:app --host 127.0.0.1 --port 8787` | `.venv/bin/python -m signalforge.cli run-scheduler` |
| `EnvironmentVariables.PATH` | `<repo>/.venv/bin:/usr/bin:/bin:/usr/sbin:/sbin` | same |
| `RunAtLoad` | `true` | `true` |
| `KeepAlive` | `true` | `true` (see kill-switch caveat below) |
| `StandardOutPath` | `~/Library/Logs/signalforge/api.out.log` | `~/Library/Logs/signalforge/worker.out.log` |
| `StandardErrorPath` | `~/Library/Logs/signalforge/api.err.log` | `~/Library/Logs/signalforge/worker.err.log` |

```bash
mkdir -p ~/Library/LaunchAgents ~/Library/Logs/signalforge
```

```bash
cat > ~/Library/LaunchAgents/com.signalforge.api.plist <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.signalforge.api</string>
  <key>WorkingDirectory</key><string>/Users/louisbrailey/signal-forge</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/louisbrailey/signal-forge/.venv/bin/uvicorn</string>
    <string>signalforge.app.main:app</string>
    <string>--host</string>
    <string>127.0.0.1</string>
    <string>--port</string>
    <string>8787</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/Users/louisbrailey/signal-forge/.venv/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/Users/louisbrailey/Library/Logs/signalforge/api.out.log</string>
  <key>StandardErrorPath</key><string>/Users/louisbrailey/Library/Logs/signalforge/api.err.log</string>
</dict>
</plist>
PLIST
```

```bash
cat > ~/Library/LaunchAgents/com.signalforge.worker.plist <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.signalforge.worker</string>
  <key>WorkingDirectory</key><string>/Users/louisbrailey/signal-forge</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/louisbrailey/signal-forge/.venv/bin/python</string>
    <string>-m</string>
    <string>signalforge.cli</string>
    <string>run-scheduler</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/Users/louisbrailey/signal-forge/.venv/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/Users/louisbrailey/Library/Logs/signalforge/worker.out.log</string>
  <key>StandardErrorPath</key><string>/Users/louisbrailey/Library/Logs/signalforge/worker.err.log</string>
</dict>
</plist>
PLIST
```

Load both (macOS Big Sur+ syntax; `(verify on your macOS version)` — older
macOS uses `launchctl load`/`unload` instead of `bootstrap`/`bootout`):

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.signalforge.api.plist
```

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.signalforge.worker.plist
```

```bash
launchctl enable gui/$(id -u)/com.signalforge.api
```

```bash
launchctl enable gui/$(id -u)/com.signalforge.worker
```

Status / restart / stop:

```bash
launchctl print gui/$(id -u)/com.signalforge.worker
```

```bash
launchctl kickstart -k gui/$(id -u)/com.signalforge.api
```

```bash
launchctl kickstart -k gui/$(id -u)/com.signalforge.worker
```

```bash
launchctl bootout gui/$(id -u)/com.signalforge.worker
```

**Kill switch and the worker:** `run-scheduler` starts even while the kill
switch is engaged (it prints a yellow warning instead of exiting), so
`KeepAlive` never crash-loops it during an incident. Every job is
individually guarded — each fires on schedule and immediately no-ops (logged
as `job.skipped_kill_switch`, and shown as `skipped` on `/ops`) until the
switch is released. You never need to stop or restart the worker to engage
or release the switch.

Logs:

```bash
tail -f ~/Library/Logs/signalforge/worker.out.log ~/Library/Logs/signalforge/worker.err.log
```

```bash
tail -f ~/Library/Logs/signalforge/api.out.log ~/Library/Logs/signalforge/api.err.log
```

### Daily backup

`signalforge backup` (`src/signalforge/backup.py`) takes a consistent
snapshot via SQLite's online backup API into `data/backups/` (or
`SIGNALFORGE_DATA_DIR/backups` if set). **It works against SQLite
`DATABASE_URL`s only** — `_sqlite_path()` raises if `DATABASE_URL` is not a
`sqlite:///` / `sqlite+pysqlite:///` URL, which is exactly what Option A uses.

```bash
uv run signalforge backup
```

Add `--encrypt` to gpg-encrypt (prompts for a passphrase) — see
`./backup.sh` for a thin wrapper. Run this by hand daily, or add a third,
optional `launchd` agent with a `StartCalendarInterval` (no `KeepAlive`, since
it's a one-shot) if you want it automatic — the two agents above are the ones
this runbook requires; a backup agent is a convenience on top.

### Updating

```bash
cd /Users/louisbrailey/signal-forge && git pull
```

```bash
make migrate
```

```bash
launchctl kickstart -k gui/$(id -u)/com.signalforge.api
```

```bash
launchctl kickstart -k gui/$(id -u)/com.signalforge.worker
```

### Verifying it's healthy

```bash
curl -s http://127.0.0.1:8787/healthz
```

```bash
curl -s http://127.0.0.1:8787/readyz
```

`/readyz` (`src/signalforge/app/main.py`) reports kill-switch state and
whether the database is connected and at the migration head.

```bash
open http://127.0.0.1:8787/ops
```

The Operational Status page (new in this change — `GET /ops`,
`src/signalforge/app/templates/ops_status.html`, context built by
`ops_status_context()` in `src/signalforge/app/views.py`) is the single "is
it healthy?" view. It shows, and self-evaluates as a 10-item readiness
checklist:

- current git branch + SHA, and whether the database is at the Alembic
  migration head;
- every data feed's freshness, and the Benzinga News feed's freshness
  specifically (from the latest `entitlement_check` row, feed
  `benzinga_news`);
- kill-switch state;
- the last ingestion run's outcome;
- every `PAPER_APPROVED` strategy and its exact approved data scope
  (dataset snapshot, universe size, sources, config/spec hashes);
- whether `DISCORD_WEBHOOK_URL` is configured (never the URL itself);
- `alerts_enabled`, `paper_probation_enabled`, and `auto_simulate` — the
  checklist expects all three **off** "during preparation";
- the last outcome (`ok` / `failed` / `skipped` / `never`) and age of every
  scheduled and catch-up job, including `approved_scope_scan`;
- the last ingest, the latest scan per horizon, and the last approved-scope
  scan outcome (`completed` or `blocked`, with its reason).

Note the checklist item "Alerts OFF (expected during preparation)" and
"Paper probation OFF (expected during preparation)" will correctly turn
**red** once you complete [Manual enable steps](#manual-enable-steps) — that
is expected, not a fault; it is telling you the switches moved, which is
what you asked them to do.

```bash
uv run signalforge providers verify
```

The liquid-universe pipeline (`/universe` page; `signalforge universe status`)
is a separate, config-gated post-close job (`universe_update`, 18:15 ET, OFF
until `research.universe_pipeline.enabled` is true). Run it by hand with
`signalforge universe update` (resumable; stops at its runtime/storage
budgets). Its scans are research-only and never feed alerts.

Probes every configured provider endpoint and records the result to
`entitlement_check` — never prints or logs a key or the Discord webhook URL.

---

## Option B — Docker Compose + PostgreSQL on an always-on Mac mini or VPS (later)

`docker-compose.yml` — no brokerage connector in any service; the API and
worker containers are the same image, built from the repo's `Dockerfile`.

### `.env`

Same file, same rules as Option A (git-ignored, never baked into the image —
`.dockerignore` excludes it), plus one addition: as part of this change,
`docker-compose.yml` no longer hardcodes a Postgres password.
`.env.example` now documents it directly:

```
# Docker Compose only (docker-compose.yml): the password for the bundled
# `postgres` service. Required there — compose refuses to start without it.
# Generate with: python -c "import secrets;print(secrets.token_urlsafe(24))"
POSTGRES_PASSWORD=
```

| Variable | Purpose |
|---|---|
| `POSTGRES_PASSWORD` | Password for the `signalforge` Postgres role. `docker-compose.yml` interpolates it into both the `postgres` service's `POSTGRES_PASSWORD` and the `api`/`worker` containers' `DATABASE_URL` as `${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in .env}` — `docker compose up` refuses to start with that exact error if it's unset or empty. |
| `APP_ENCRYPTION_KEY` | 32+ bytes — encrypts the local secret store (`sf_secrets` volume) and session cookies |
| `MARKET_DATA_PROVIDER` / `MARKET_DATA_API_KEY` (+ `_SECONDARY` variants) | Market data |
| `NEWS_PROVIDER` / `NEWS_API_KEY` | Optional news feed |
| `LLM_PROVIDER` / `LLM_API_KEY` / `LLM_MODEL` | Optional narrative layer |
| `NOTIFICATION_PROVIDER` / `NOTIFICATION_API_KEY`, `SMTP_*` | Notification channel |
| `DISCORD_WEBHOOK_URL` | Optional Discord incoming webhook (see the note in Option A) |

`DATABASE_URL` itself is **not** something you set in `.env` for Option B —
leave it blank as documented for the SQLite default. `docker-compose.yml`'s
`x-app` anchor overrides it in-container, built from `POSTGRES_PASSWORD` as
shown above.

Docker Compose reads `./.env` for two separate purposes here: to resolve the
`${POSTGRES_PASSWORD:?...}` interpolation in `docker-compose.yml` itself
(compose-file substitution, from the shell/`.env` in the project directory),
and — via each service's `env_file: [.env]` — to inject every variable into
the `api`/`worker` containers' own environment. Both read the same file.

```bash
cd /Users/louisbrailey/signal-forge
cp .env.example .env
```

Edit `.env`: set `POSTGRES_PASSWORD`, `APP_ENCRYPTION_KEY`, and whichever
provider keys you use.

```bash
docker compose up -d
```

| Service | Role | Restart policy |
|---|---|---|
| `postgres` | `postgres:16-alpine`; data in the `sf_pg` volume; `pg_isready` healthcheck; `POSTGRES_PASSWORD` now comes from `.env` (no hardcoded default) | `unless-stopped` |
| `api` | Runs `alembic upgrade head`, then `uvicorn signalforge.app.main:app --host 0.0.0.0 --port 8787`; bound `127.0.0.1:8787:8787` (loopback only); `/healthz` healthcheck | `unless-stopped` |
| `worker` | `python -m signalforge.cli run-scheduler` — the same job set as Option A, including the 17:30 ET `daily_eod_update` (ingest → rescan → approved-scope scan). Starts fine with the kill switch engaged; jobs no-op until release | `unless-stopped` |

```bash
docker compose ps
```

```bash
docker compose logs -f worker
```

### Reaching it safely

The `api` port is bound `127.0.0.1:8787:8787` on the host — reachable only
from that host itself, by design. From your laptop, tunnel in over SSH:

```bash
ssh -N -L 8787:127.0.0.1:8787 <user>@<mac-mini-or-vps-host>
```

Then open `http://127.0.0.1:8787` (and `/ops`) locally as if it were running
on your own machine.

### Backups

`docker compose exec api python -m signalforge.cli backup`, as documented in
`docs/DEPLOYMENT.md`, does **not** work here: `create_backup()` only supports
`sqlite:///` / `sqlite+pysqlite:///` `DATABASE_URL`s and raises
`RuntimeError` on a `postgresql+psycopg://` one, which is what this
deployment always uses `(unverified — flagging the discrepancy with
docs/DEPLOYMENT.md's Docker section rather than repeating a command that
appears not to work against Postgres)`. Use `pg_dump` for the database:

```bash
docker compose exec postgres pg_dump -U signalforge signalforge > signalforge_$(date +%F).sql
```

And back up the `sf_data` volume (kill-switch state, raw-payload cache, logs)
separately — `(unverified: standard docker volume-backup pattern, not
scripted anywhere in this repo)`:

```bash
docker run --rm -v sf_data:/from -v "$PWD":/to alpine tar czf /to/sf_data_$(date +%F).tar.gz -C /from .
```

Copy both off-box on your own schedule and prune old snapshots per your own
retention policy.

### Updating

```bash
cd /Users/louisbrailey/signal-forge && git pull
```

```bash
docker compose build
```

```bash
docker compose up -d
```

```bash
docker compose logs -f api
```

The `api` container re-runs `alembic upgrade head` on every start, so a
schema migration lands automatically the next time it starts (`docker
compose up -d` recreates it).

### SQLite → Postgres migration

Moving existing SQLite research/paper history into this Postgres deployment
is **not provided** `(unvalidated: no migration/export tool exists in this
repo — confirmed by search)`. Standing up Option B starts from an empty
database: run the usual ingest (`signalforge data ingest-history` /
`signalforge ingest`, or just let the daily `job_ingest` top up
incrementally) rather than expecting your Option A history to appear here.

---

## Daily operating checklist

- Open `/ops` and read its own readiness checklist top to bottom — it is
  the authoritative "is it healthy?" view (see above); the items below are
  what it does **not** already tell you.
- Confirm `daily_eod_update` and `approved_scope_scan` both show a same-day
  `ok` outcome after 17:30 `America/New_York` in `/ops`'s "Last scheduled-job
  outcomes", and that the "Approved-scope scan" panel says `completed` rather
  than `blocked` (a `blocked` result is still an `ok` job — it ran and
  correctly refused to scan; the panel shows why).
- Tail `worker.err.log` (Option A) or `docker compose logs worker` (Option B)
  for `job.failed` entries since your last check.
- If alerts are enabled (see below), confirm any Discord messages received
  match what you expect — no more than the documented cap.
- Confirm the Mac didn't sleep overnight (`pmset -g log` around 17:30 ET, or
  simply that `/ops`'s job timestamps are current) — Option A only.
- Weekly: confirm a recent snapshot exists in `data/backups/` (Option A) or
  that your last `pg_dump` + volume copy (Option B) succeeded.

## Incident basics

**Kill switch**

```bash
uv run signalforge killswitch on --reason "<why>"
```

```bash
uv run signalforge killswitch off --reason "<why>"
```

```bash
uv run signalforge killswitch status
```

Engaging it does not need anything to be stopped — every scheduled job and
`run-job` invocation checks it and no-ops while active, and the worker can be
restarted freely while it is engaged.

**Stale feed**

```bash
curl -s http://127.0.0.1:8787/api/feeds
```

Or check `/ops`. Then:

```bash
uv run signalforge providers verify
```

**Failed job**

Check `worker.err.log` / `docker compose logs worker`, or `/ops`'s "Last
scheduled-job outcomes" table, for the `job.failed` entry, then re-run that
job once by hand (kill-switch guarded):

```bash
uv run signalforge run-job daily_eod_update
```

Valid names are the eight in `default_job_specs()`
(`src/signalforge/scheduler.py`) — `daily_eod_update`, `paper_mtm`,
`feed_probe`, `health_check`, `news_poll`, `daily_briefing`, `alerts`,
`strategy_health`, `universe_update` (18:15 ET, config-gated OFF via
`research.universe_pipeline.enabled`) — plus `MANUAL_JOBS` entries that are not on a
schedule of their own: `approved_scope_scan` (it normally only runs as the
last step of `daily_eod_update` and at catch-up).

If specifically the approved-scope scan keeps showing `blocked` rather than
`ok`/`completed`, its readiness gate is refusing to run on the current data
— check the reason on `/ops` ("Last ingest · scans · approved-scope scan ·
briefing") or:

```bash
uv run signalforge scan-approved-scope
```

which prints the exact block reason (stale feed, last ingestion not `ok`,
newest bar older than 5 days, or under 90% of the approved universe covered
on the newest session) and exits non-zero. `--force` bypasses the gate for a
supervised, manual run only — the scheduled path never bypasses it:

```bash
uv run signalforge scan-approved-scope --force
```

**Discord silent**

1. Check `/ops` for `Discord configured: yes` — if `no`, `DISCORD_WEBHOOK_URL`
   isn't set (or isn't a well-formed `https://discord(app).com/api/webhooks/...`
   URL).
2. Check `alerts_enabled` (Settings) and `paper_probation_enabled`
   (`signalforge paper-probation-status`) — if either is off, no alert will
   ever reach Discord regardless of webhook validity; this is expected until
   you complete the manual enable steps below.
3. Send one test message, bypassing the alert policy entirely:

```bash
uv run signalforge notify test-discord --yes
```

---

## Manual enable steps

Everything above brings the system to "healthy and ingesting, alerts and
paper probation still off." These steps are how an operator turns alerting
on, by hand, only when ready — do **not** fold them into setup. Do them in
this order, on a day when `/ops` shows every checklist item green and
`approved_scope_scan` shows `completed`.

**Step 1 — one Discord test message** (reads only `DISCORD_WEBHOOK_URL`;
evaluates no alert policy; creates no paper trade; works while alerts are OFF):

```bash
uv run signalforge notify test-discord --yes
```

Expect one message in the channel and `test message delivered` in the
terminal. If it fails, fix the webhook before going further.

**Step 2 — turn on paper-probation candidate alerts** (candidates from
`PAPER_APPROVED` strategies only, and only when the candidate's scan matches
the strategy's exact approved dataset scope; auto-simulation stays OFF and
paper-trade acceptance stays manual):

```bash
uv run signalforge paper-probation-enable
```

**Step 3 — open the outbound alert gate for candidate alerts only.** In the
dashboard, `/settings` → tick "enable outbound alerts" AND, under "Alert
types", tick only "approved paper-probation candidate" → Save. Every alert
type is OFF by default and stays off until ticked; with only the candidate
type on, the informational types (`system_health`, `data_issue`,
`daily_briefing`) remain suppressed and logged locally as
"alert type … is off in Settings". Tick those separately later if you want
them on Discord too. Everything is still subject to quiet hours and the
2-per-day candidate cap.

**Verify:** `/ops` now shows Alerts ON and Paper probation ON (those two
checklist rows go red on purpose — they flag that the switches moved), and

```bash
uv run signalforge paper-probation-status
```

**Reverse at any time:** `signalforge paper-probation-disable`, or untick
"enable outbound alerts" in `/settings`, or engage the kill switch.
