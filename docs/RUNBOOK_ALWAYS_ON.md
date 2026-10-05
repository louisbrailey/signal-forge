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

### What the daily ingest actually fetches (changed 2026-09-14, W6a)

`job_ingest` fetches the **union of the configured universe and every
PAPER_APPROVED strategy version's approved-scope universe**, de-duplicated, on
the primary adapter's source only. The extra symbols come from
`research.approved_scope_scan.ingest_scope`, which reads them from
`approved_universes()` — the same function that drives the scan, so the two
cannot drift apart.

Why: the approved-scope scan refuses to run on a universe that has no completed
bar for the latest session, but the ingest used to fetch only
`settings.research.universe` (~25 symbols). Strategy v3
(`trend_continuation.medium_swing`), PAPER_APPROVED on DataSnapshot 11
(`research_150_massive_10y_presealed_sel`, 150 symbols, source `massive`), was
therefore blocked **every session** with
`approved_scope_scan.blocked … only 24/150 approved symbols have a bar for …`.
Friday 2026-09-11 only worked because a 10-year full-history backfill happened
to include that session.

Consequences to know:

- **Order.** The configured universe is fetched first, in its own order, then
  each approved snapshot's extra symbols sorted, snapshots in id order. The
  ingest commits per symbol, so a run cut short (kill switch, provider outage,
  lid closed) has still topped up the watchlist every other scan reads.
- **Source filter.** An approved universe whose approval source is not the
  ingest adapter's `provider_name` is **skipped** and recorded in the run's
  provenance. Bars are stored tagged with the writing adapter's source and the
  readiness gate counts bars `WHERE source = the approved source`, so fetching
  it here would write rows that can never satisfy the gate they were fetched
  for.
- **Runtime.** ~151 symbols × 12.1 s provider pacing ≈ **30 min**, so the 17:30
  ET chain now finishes its ingest around **18:00–18:05 ET**, then rescans and
  runs the approved-scope scan (local compute, a few minutes). `universe_update`
  at 18:15 ET is a *different* APScheduler job and is **not** covered by
  `_EOD_UPDATE_LOCK`, so on a slow evening the two can overlap. That is safe by
  construction, not by luck: the ingest holds no write transaction across a
  provider call and commits per symbol (`docs/SQLITE_CONCURRENCY.md` rule 4), so
  the worst case is bounded lock contention with the usual retry, not a stuck
  writer. Cron times were deliberately **not** moved. If the chain does start
  running long, cut the ingest window (`start = end - 400 days`) before touching
  the schedule.
- **Provenance.** The `ingestion_run` row records which symbols came from which
  approved snapshot under the reserved `gaps_json` key `__approved_scope__`
  (configured list, per-snapshot `added` symbols, snapshots excluded for source,
  skipped versions), and `notes` names each contributing snapshot. With no
  approved contribution the note stays byte-identical to what it always was.
- **`status` is unchanged**: `ok` only when *every* requested symbol succeeded.
  What changed is who a non-ok run blocks — see below.

### Which universes a failed ingest blocks

`status` alone is now too coarse to gate a scan, because one run covers
config + every approved snapshot. `approved_scope_scan.data_readiness` decides
per approved universe:

| last daily-bar run | effect |
|---|---|
| `ok` | nothing blocked |
| `partial`, failed symbols named | blocks **only** the universes containing a failed symbol; the reason names them |
| `partial`, `symbols_failed` empty | blocks everything (unattributable — fails closed) |
| `failed` / `running` / `killed` / `stopped` | blocks everything, as before |

So a delisted watchlist ticker no longer silences a 150-symbol approved scope
whose own data arrived intact, and a bad approved-scope symbol no longer
silences the configured universe.

`catch_up_pending` follows the same logic: a `partial` run that finished after
the session's 17:30 cutoff and got the **whole configured universe** counts as
that session's update having run. Without this the 30-minute `catch_up` job
would see "no OK ingestion since the close" all evening and re-run a ~30-minute
EOD chain over and over on one permanently-bad ticker. A broad provider outage
fails configured symbols too, so it still triggers a catch-up.

### What the worker does for you (heartbeat + catch-up)

`signalforge run-scheduler` (also `make worker`, foreground) writes a
`worker_heartbeat` row every 30 s with the scheduler's real next-run times,
and runs a `catch_up` job every 30 min: if no daily-bar ingestion covering the
configured universe has finished since the last completed session's 17:30 ET
close, it runs the full EOD update (ingest → rescan → approved-scope scan)
right then — so a Mac that
slept through 17:30 catches up within 30 min of waking, and a failed attempt
backs off for 2 h before retrying. Both catch-up paths (the startup
`run_catch_up` and the 30-minute `catch_up` job) go through the same
`job_ingest`, so both fetch the same union. `/ops` shows: worker running / stale /
never, next scheduled EOD run (from the worker itself), daily-bar freshness
vs the expected session, and whether a catch-up is pending. Reviewed plist
files live in `deploy/launchd/` (`make launchd-check` validates them; nothing
installs them for you).

### 2026-10-04 — ingest deadline, multi-session catch-up, visible EOD gaps

**Incident (2026-09-28 → 10-01).** The 21:30 UTC (17:30 ET) `daily_eod_update`
on 09-28 fired ~4 h late — beyond the 1 h `misfire_grace_time`, so APScheduler
dropped it. A catch-up ingest then failed on provider network errors until
05:14 UTC 09-29, and no job ran again until a manual restart at 19:28 UTC on
10-01. No approved-scope scan exists for the sessions in between. Two code
weaknesses made that worse than it had to be, and a third hid it:

1. **The ingest had no overall deadline while holding the EOD lock.** A stuck
   or slow provider could hold `_EOD_UPDATE_LOCK` indefinitely, and with it
   every later EOD update, catch-up and intraday scan.
2. **Catch-up only ever looked at the latest completed session.** Sessions
   missed in the middle of an outage were never revisited.
3. **Nothing said "no EOD run happened".** `/ops` showed stale bars and a
   pending catch-up, but not that the EOD job itself had been absent for days.

**Fix 1 — ingest deadline.** `job_ingest` now stops when the locked unit has
run longer than `eod_ingest_deadline_minutes` (default **45**; a normal
~175-symbol pass at the 12.1 s Basic pace is ~35 min). The clock starts when
the EOD lock is taken and is polled **between symbols only** — after one
symbol's commit, before the next symbol's fetch — so no write transaction is
ever interrupted. One in-flight request is still bounded by the adapter's own
timeout/retry, not by this deadline. On expiry:

- the run is recorded as an `IngestionRun` with status **`stopped`** (never
  `ok`/`partial`, so `data_readiness` and `catch_up_pending` both treat the
  session as not covered) carrying the completed symbols;
- `IngestDeadlineExceeded` propagates, the lock is released, **neither scan
  runs**, and the job row reads
  `deadline exceeded after N/M symbols (45 min); resume on next catch-up`;
- the next ingest **resumes**: it skips the symbols the stopped run completed
  and finishes the same row. It resumes only when that run is the newest
  daily-bar run for the provider, has the same `requested_end`, and *started
  after the last completed session's 17:30 ET cutoff* — otherwise symbols
  fetched before the bar was published could be carried over, so a full pass
  is made instead.

The scans are local compute and are deliberately **not** under the deadline:
stopping after a completed ingest would leave a session ingested-but-unscanned
with nothing owed to retry it. A deadline failure is a failed job like any
other, so the existing 2 h catch-up back-off applies before the resume — a
stuck provider is not hammered. The kill switch is unchanged: `guarded()`
still skips the job, and the adapters still re-check it inside their waits.

**Fix 2 — multi-session catch-up.** The 30-minute `catch_up` job (and, for
past sessions, start-up via `catch_up_missed_sessions`) now resolves **every**
completed XNYS session since the last one with a readiness-enforced
`approved_scope_scan.completed` audit row, oldest first, bounded to the
`catch_up_lookback_sessions` (default **10**) sessions before the latest one.
No such audit row at all (fresh install) means nothing is owed. Per missed
session it writes two `job_run` rows:

| row | meaning |
|---|---|
| `catchup_ingest_session` (`ok`/`failed`) | `session=YYYY-MM-DD: covered by daily-bar ingestion run #N (fetched now / already ingested); k/n configured symbols have a bar for this session` |
| `scan_skipped_missed_session` (`skipped`) | the approved-scope scan was **not** run for that session, and why |

One provider pass serves all missed sessions: the incremental window is 400
days ending today, so the first missed session triggers the fetch and the
later ones are verified against that same run rather than re-fetched (three
identical ~35-minute passes would only re-request bars already stored). A
session whose ingest fails gets a `failed` row and **no** skip row, so it stays
owed and is retried after the back-off. A session with a skip row is never
processed again (idempotent).

**Why missed sessions are skipped, not scanned "as of".** `run_scan(as_of=…)`
bounds only the price read. A scan of a past session run today would still use
*today's* approval state, OOS evidence, earnings calendar, paper-account cash
and feed-freshness gate; it would bypass the completed-bar requirement
(computed only when `as_of` is `None`) and `data_readiness` (which is
"now"-based); and it would persist `ScanRun`/`Candidate` rows that carry no
as-of marker — there is no such column — so the alert planner, the scanner
page, manual paper acceptance and auto-simulation could not tell them from a
live scan. That is look-ahead plus a stale-signal hazard (audit finding P1,
`docs/PAPER_OPERATION_AUDIT.md`), so it is not faked. Doing it properly needs
a schema change and edits to the research gates and every candidate consumer.

**Auto-simulation.** Because no scan is produced for a missed past session,
nothing from one can reach `paper.auto_simulate`. Only the latest completed
session runs the real chain (`scan_all` → `approved_scope_scan` → guarded
auto-simulation), exactly as before.

**Fix 3 — visible EOD gap.** `/ops` has a new readiness check, **"EOD update
ran for last completed session"**, and a `DEGRADED — EOD GAP` pill in the
worker panel. It fails when the last completed session is more than
`eod_gap_grace_minutes` (default **120**) past its 17:30 ET cutoff with no
`ok` `job_run` for `daily_eod_update`, `approved_scope_scan` or
`catchup_approved_scope_scan` since that cutoff; the note also names earlier
sessions still unscanned. (The `catch_up` row itself is not evidence — it is
written `ok` even when it found nothing to do.) The 15-minute `health_check`
logs the same condition as `health.eod_gap status=degraded`; it logs rather
than fails, so it does not add a failed job row every 15 minutes.

**New settings** (process environment / `.env`, on `Settings` — *not* on
`ResearchConfig`, so `config_hash`, `full_config_hash` and every approved
scope are untouched):

| env var | default | meaning |
|---|---|---|
| `EOD_INGEST_DEADLINE_MINUTES` | `45` | wall-clock budget for the daily-bar ingest while the EOD lock is held |
| `CATCH_UP_LOOKBACK_SESSIONS` | `10` | how many sessions before the latest the catch-up looks back over (`0` disables) |
| `EOD_GAP_GRACE_MINUTES` | `120` | grace after the 17:30 ET cutoff before a missing EOD run is flagged |

**Operator notes.** After an outage, expect `scan_skipped_missed_session`
rows on `/ops` — they are the record that those sessions have no approved-scope
evidence, not an error to clear. What this does **not** fix: a host that is
asleep or a worker that is not running still runs nothing (see "Why a sleeping
laptop cannot run scheduled jobs"); the gap check makes that visible, it does
not prevent it.

### Manual smoke test (do this before installing launchd)

Run each step in its own terminal at the repo root; stop anything from `make dev`
first (a `--reload` child can outlive Ctrl-C — `pkill -f "uvicorn signalforge"`).

1. **Start the API**
   ```bash
   make api
   ```
   Expect `Uvicorn running on http://127.0.0.1:8787`; `curl -s http://127.0.0.1:8787/healthz`.
2. **Start one worker**
   ```bash
   make worker
   ```
   Expect `scheduler running — Ctrl-C to stop`. It first runs the catch-up (ingest →
   rescan → approved-scope scan) if the EOD update is owed; that takes ~30 min at the
   provider's 5 req/min pacing (~151 symbols since W6a — see "What the daily ingest
   actually fetches"; it was ~5 min when only the 25-symbol watchlist was
   fetched). Starting a **second** `make worker` must print
   `refusing to start: another scheduler worker already holds …` and exit 1.
3. **Verify the heartbeat** — open `http://127.0.0.1:8787/ops`: the worker row reads
   *running · pid … · beat Ns ago* within 30 s, and "Next scheduled EOD update" shows a
   time *from worker*.
4. **Verify catch-up** — in `/ops`, `catchup_ingest`, `catchup_scan`,
   `catchup_approved_scope_scan` show `ok` (or the exact failure reason), "Daily bars
   current for last completed session" turns green, and "Catch-up" reads *not pending*
   (`approved_scope_scan` may legitimately show *blocked* with its reason on a
   holiday/stale day).
5. **Confirm no lock errors** — the worker terminal shows no `database is locked`; in
   `/ops`, no job's failure reason mentions `lock contention`;
   `sqlite3 data/signalforge.sqlite "select name,status,detail from job_run order by id desc limit 10"`
   shows no `failed`.
6. **Stop cleanly** — Ctrl-C the worker (it writes a final `stopping` heartbeat and
   releases `data/worker.lock`), then Ctrl-C the API. `/ops` will then show the worker
   as *STALE — process gone* after 90 s, which is correct.

Only after all six pass, install the launchd agents below — and **stop the
smoke-test worker and API first** (Ctrl-C both): the launchd worker refuses to
start while another worker's heartbeat is fresh, and `KeepAlive` would keep
retrying every 30 s until the old one exits.

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

Valid names are the ones in `default_job_specs()`
(`src/signalforge/scheduler.py`) — `daily_eod_update`, `paper_mtm`,
`feed_probe`, `health_check`, `news_poll`, `daily_briefing`, `alerts`,
`strategy_health`, `universe_update` (18:15 ET, config-gated OFF via
`research.universe_pipeline.enabled`), `grid_daily` (18:50 ET, config-gated OFF),
`catch_up` — plus `MANUAL_JOBS` entries that are not on a
schedule of their own: `approved_scope_scan` (it normally only runs as the
last step of `daily_eod_update` and at catch-up) — plus two jobs that are
**injected from the CLI** and are therefore absent from `default_job_specs()`:
`execution_cycle` and `options_paper_eod`.

`options_paper_eod` (18:30 ET) is the SIMULATED options paper end-of-day chain:
mark → reconcile → expiry → auto-simulate, in that order. With
`research.options.paper_eod_enabled` off (the default) it returns before it opens
a write transaction and writes nothing but its own `JobRun` row. Turning it on
buys marks, the dated collateral reconciliation and expiry handling; it does
**not** let anything open a structure — that needs the separate
`auto_simulate_options_enabled` setting, which is off with a cap of 0/day.

Like the execution cycle, it exists **only in the CLI-launched worker**
(`signalforge run-scheduler`). `signalforge.scheduler` may not import the options
paper layer — `signalforge.app` imports the scheduler and contract S16 reports
indirect chains — so the spec is injected from `signalforge.cli` and an API
process started with `APP_RUN_SCHEDULER=true` carries no options job at all. It
is also only registered once the options paper account exists.

`signalforge paper-probation-status` prints the book's state (account, open
structures, reconciliation age, last chain run), and `signalforge options-paper
status --json` prints the full snapshot.

If specifically the approved-scope scan keeps showing `blocked` rather than
`ok`/`completed`, its readiness gate is refusing to run on the current data
— check the reason on `/ops` ("Last ingest · scans · approved-scope scan ·
briefing") or:

```bash
uv run signalforge scan-approved-scope
```

which prints the exact block reason (stale feed, the last ingestion failing for
one of *this* universe's symbols, newest bar older than 5 days, or under 90% of
the approved universe covered on the newest session) and exits non-zero. If the
reason is `incomplete data: only N/M approved symbols have a bar …`, check the
last `ingestion_run`'s `symbols_requested` — since W6a the scheduled ingest
should already contain that snapshot's symbols, and if it does not, the approval
source probably does not match the primary adapter (see "What the daily ingest
actually fetches"). `--force` bypasses the gate for a
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
