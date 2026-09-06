# Security notes & threat model

Signal Forge runs on your machine, for you only. This document records what it
protects, what it does not, and how the safety invariants are enforced.

## Assets

| Asset | Sensitivity |
|---|---|
| Data-provider / LLM / SMTP API keys | High — paid entitlements, abuse potential |
| `APP_ENCRYPTION_KEY` | High — protects the local secret store & backups |
| Local user password hash | Medium — single-user local auth |
| Paper-trading ledger & journal | Low/Medium — personal research record |
| Imported broker CSV (positions/transactions) | Medium — personal financial data |
| Cached raw market data | Low — licensed third-party data, keep local |

## Trust boundaries

- **Inside:** everything in `src/signalforge/` on localhost.
- **Read-only external:** market-data / news / calendar / fundamentals provider
  APIs, and the optional LLM API. These are data sources. Their responses are
  **never treated as instructions** (see Prompt injection).
- **Outbound only:** notification channels (local log always; email/webhook if
  configured).
- **No trading surface exists.** There is no code path to a brokerage.

## Enforced invariants (also in ARCHITECTURE.md §2)

| # | Invariant | Mechanism |
|---|---|---|
| S1 | No brokerage / execution / browser-automation surface | `import-linter` forbidden contract on the whole package + Ruff `banned-api` + `tests/safety/test_no_broker_surface.py` (source grep denylist) |
| S2 | CSV import does no network I/O | `import-linter` forbids `httpx`/`socket`/`urllib.request`/`data.adapters` in `signalforge.portfolio` |
| S3 | LLM never on the decision path | `import-linter` forbids `signalforge.llm` in `research`/`risk`/`backtest`/`paper` |
| S4 | Determinism of signals/backtests | seeded RNG, no wall-clock in pure functions, `config_hash` recorded on every run |
| S5 | Secret hygiene | `SecretStr` types, `structlog` redaction processor, `.gitignore`, `detect-secrets` pre-commit + CI |
| S6 | Kill switch halts everything | central `KillSwitch`, checked at every job entrypoint, alert dispatch, and as a FastAPI dependency on state-changing routes |
| S7 | "Live" only with a real entitlement | `latency_category` comes from an adapter capability flag, never hard-coded |
| S8 | Stale feed ⇒ no live alerts, results marked | `FreshnessGate` in scan + alert pipeline |
| S9 | Paper trades immutable | repository exposes no update/delete; corrections are separate append-only rows; DB-level guard |
| S10 | No unearned confidence | probability rendered only with a calibrated out-of-sample `calibration_ref` for that strategy version |

Any PR weakening S1–S10 must say so explicitly and update the corresponding
safety test.

## Secret handling

- Loaded via `pydantic-settings` from `.env` / environment only.
- Wrapped in `pydantic.SecretStr`; `str()` / logs show `**********`.
- A `structlog` processor redacts values for keys matching
  `(?i)(key|token|secret|password|authorization)`.
- Optional local encrypted store (`Fernet`, key = `APP_ENCRYPTION_KEY`) for keys
  entered through the Settings UI instead of `.env`.
- `.env`, `*.key`, `secrets/`, `.secret_store/` are gitignored.
- `detect-secrets` runs in pre-commit and CI against the whole tree.

## Local auth

- Single user; password hashed with Argon2id.
- Session cookie: `HttpOnly`, `SameSite=Strict`, `Secure` when not on
  `127.0.0.1`.
- CSRF token required on all state-changing form posts.
- App binds to `127.0.0.1` by default; `TrustedHostMiddleware` with
  `APP_ALLOWED_HOSTS`.
- Failed-login backoff delay (no lockout, to avoid a local self-DoS).

## Prompt injection / untrusted content

- News headlines, filing text, transcripts, and any fetched document are
  **content to be summarized**, never instructions.
- The LLM prompt template places retrieved text inside a fenced, labelled block
  with a fixed system instruction to treat it as untrusted data.
- `llm.guards` rejects any LLM output that introduces numeric tokens not present
  in the frozen facts dict, or that omits the required "AI explanation, not a
  trading instruction." footer.
- Adapters fetch only from configured provider base URLs — never a URL taken
  from content.

## LLM layer (Phase 1)

- The LLM is optional and off unless `LLM_PROVIDER` + `LLM_API_KEY` are set.
- It only rephrases the **frozen facts dict** for the daily briefing. It never
  sees a trade decision, never sizes a position, never runs on the scan/rank/risk
  path (import-linter S3: `research`/`risk`/`backtest`/`paper` cannot import
  `signalforge.llm`; the briefing orchestrator lives at the top level).
- `signalforge.llm.explain` rejects any narrative that introduces a numeric token
  absent from the facts, or that omits the `AI explanation, not a trading
  instruction.` footer. Rejected → no narrative; the deterministic briefing is
  always complete on its own.
- Every accepted narrative writes an `llm_call` row (purpose, model, prompt SHA,
  token counts) for audit.

## Alerts (Phase 1)

- All channels are OFF until `alerts_enabled` is set in Settings. The local
  on-disk `alerts.jsonl` is always written.
- Policy caps: ≤ N high-priority candidate alerts/day (only `paper_approved`
  strategies on a fresh feed), one daily briefing, quiet-hours suppression, and
  dedupe by key. A stale feed yields only a system-health alert (which may fire
  overnight); no candidate/briefing alerts while a feed is stale.
- `run_alert_cycle` calls `ensure_not_engaged()` first (S6). Email uses stdlib
  `smtplib` + STARTTLS when SMTP settings are present.

## Data at rest & backups

- SQLite/Postgres file lives in a user-only-readable `data/` dir.
- `./backup.sh` / `signalforge backup` take a **consistent** snapshot via
  SQLite's online backup API; `--encrypt` prompts for a passphrase and pipes it
  to `gpg --symmetric` (AES-256) via `--passphrase-fd 0` — never stored, never on
  the command line. `signalforge restore` keeps a `.pre-restore` copy and clears
  stale WAL sidecars.
- Raw provider payloads are cached locally for audit/replay and are gitignored.

## Prompt injection — Phase 1 posture

- The only external text the LLM currently sees is the app's own frozen facts
  dict (numbers and timestamps it produced). Retrieved news/filings are a Phase 3
  addition and will be sandboxed as untrusted content.
- Adapters fetch only from a fixed provider base URL, never a URL taken from
  content.

## Known limitations (Phase 1)

- Local-only auth; no MFA (single-user localhost app). Login has a backoff delay,
  no lockout.
- No rate limiting on other routes.
- Backups are unencrypted unless you pass a passphrase; `gpg` must be installed.
- Reconciliation is only meaningful once a second data source is configured.
- Free/EOD data carries survivorship bias; flagged in the UI, not corrected.
- Restore is a stop-the-app operation (don't restore into a running instance).
- The scheduler runs in-process; a laptop that is asleep misses jobs and runs one
  catch-up on wake (Phase 2 moves to a durable worker).
