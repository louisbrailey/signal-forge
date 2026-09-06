# Signal Forge — Phased Implementation Plan

**Status:** Draft v0.1
**Last updated:** 2026-09-06
**Companion doc:** `ARCHITECTURE.md`

This plan is incremental. Each phase ends with: all tests run, an honest
"what was built / what is still simulated or unvalidated" report, and a
security + data-quality limitations list. Capabilities are never overstated.

Legend for acceptance criteria: **[AC]** = must be objectively demonstrable
(a test, a screenshot, or a command output).

---

## Phase 0 — Design & scaffold (this phase)

**Goal:** constraints fixed, repo skeleton exists, CI runs, nothing overstated.

### Tasks
1. `ARCHITECTURE.md` (done) and this plan (done).
2. Answer the 5 setup questions (see bottom of this doc).
3. Initialize git repo; add `.gitignore`, `.env.example`, `LICENSE` (personal),
   `README.md` skeleton, `docs/decisions/0001-frontend-choice.md`.
4. Backend skeleton: `uv` project, `signalforge/` package tree from
   ARCHITECTURE §4.1 with empty modules + docstrings stating each module's
   contract.
5. Tooling: Ruff, Black, mypy config, `import-linter` contracts for S1/S3,
   pytest, `detect-secrets` baseline, pre-commit.
6. CI workflow: lint + type + import-linter + pytest + secret scan.
7. `make dev` / `make test` / `make fmt` targets (or `just`).

### [AC]
- `make test` passes with the safety-suite stubs present (S1, S3, S5, S6 tests
  exist and pass against the skeleton).
- `import-linter` fails the build if a test file adds `import` of a brokerage
  name or `llm` into `research` (proven by a deliberately-broken local check,
  then reverted).
- CI is green on the first push.
- `.env.example` contains only the placeholder keys from the spec; no real
  values anywhere in history (`detect-secrets` clean).
- README states clearly: paper-only, research-only, not financial advice,
  no brokerage connection.

---

## Phase 1 — Local MVP (SQLite, daily bars, 2 strategies, evidence dashboard)

**Goal:** an end-to-end, honest research loop on daily data:
ingest → scan → ranked candidates with full evidence → paper trade → journal →
daily briefing, with a kill switch and data-freshness labelling throughout.

### 1.1 Persistence & config
- SQLAlchemy models + first Alembic migration for all Phase 1 tables
  (ARCHITECTURE §5, daily subset; intraday tables deferred).
- Typed settings (Pydantic) for the full config surface (§9); conservative
  defaults; UI-editable subset; `config_hash` computed.
- Local data dir resolution (XDG / `~/Library/Application Support/SignalForge`).

**[AC]** `alembic upgrade head` builds a clean DB; `alembic downgrade base`
reverses it; a round-trip test passes. Changing any risk-relevant setting
changes `config_hash`; changing a cosmetic setting does not.

### 1.2 Local authentication
- Single-user registration (first run) + login; argon2; session cookie
  (HttpOnly, SameSite=strict); CSRF on forms; app bound to `127.0.0.1`.

**[AC]** Unauthenticated request to any non-public route → 401/redirect. Test
covers login, bad password lockout-delay, logout, CSRF rejection.

### 1.3 Data adapters (daily)
- `base.py` Protocols + `AdapterCapability`.
- **Fixture adapter**: deterministic offline OHLCV + a small earnings/econ set +
  a few news items, all flagged `SIMULATED`, `latency_category=HISTORICAL`.
- **One real delayed/free/sandbox adapter** for daily bars + corporate actions
  (provider chosen from setup answers; e.g. Alpaca/Tiingo/Stooq-style).
  Declares its true `latency_category` (DELAYED or END_OF_DAY).
- Ingestion: normalize, write `raw_payload_cache`, dedupe, quality flags.
- `data_feed_status` updated on every fetch; `/feeds` endpoint.
- Reconciliation: if both fixture-baseline and the real adapter cover a symbol,
  run the close-price agreement check and record disagreements. (Full
  two-real-source reconciliation is Phase 2.)

**[AC]**
- Every bar row carries `source`, `ingested_at`, `latency_category`,
  `quality_flags`.
- Killing network (or an unset key) → real adapter reports `unavailable`,
  `/feeds` shows it, and the UI shows a stale/unavailable banner. **[S8]**
- No code path labels fixture or delayed data "live". **[S7]**
- `raw_payload_cache` contains the verbatim response for a replay test.

### 1.4 Backtest engine (daily)
- Event loop over adjusted daily bars; corporate-action adjustment; US session
  calendar; no look-ahead (features at bar *t* use data ≤ *t*; fills at *t+1*
  open or defined rule).
- Cost model: commission (configurable, default 0), bid-ask spread cost, and a
  slippage model (e.g. % of ADV / fixed bps). All assumptions displayed.
- Metrics: trades, win rate, avg win/loss, expectancy, profit factor, max
  drawdown, risk-adjusted metric (labelled with limitations), avg holding
  period, turnover, exposure, largest losing streak — all net of costs.
- Train/test temporal split + **rolling walk-forward** (report per fold).
- Bootstrap CIs on expectancy / profit factor.
- Regime segmentation of results (bull/bear/highvol/lowvol/range via the
  regime filter).
- Look-ahead / leakage detector test utilities.

**[AC]**
- Synthetic series with a known edge → engine recovers the expected sign and
  approximate magnitude of expectancy within CI. **[S4]** determinism test:
  same inputs+config_hash+seed → byte-identical metrics.
- A deliberately leaked feature is caught by the leakage detector test.
- Walk-forward report shows IS vs OOS side by side; OOS is the number used
  downstream.

### 1.5 Strategies (2 for Phase 1) + registry
- `StrategyRegistry` + full `StrategySpec` records (§6.1).
- **Strategy A — Trend continuation + volume confirmation** (SHORT_SWING and
  MEDIUM_SWING), long/short per config.
- **Strategy B — Mean reversion after a statistically unusual move**
  (SHORT_SWING), regime-gated.
- **Regime filter** implemented as a gating input (not itself a generator).
- Each ships `experimental` status → paper only, **no alerts** until walk-forward
  thresholds are met and the user promotes it.

**[AC]**
- A scan cannot run a strategy whose `StrategySpec` is missing any required
  field (test).
- Each strategy has a committed backtest + walk-forward report artifact under
  `reports/`.
- Promotion to `paper_approved` is a manual, audited action.

### 1.6 Scan → rank → risk → candidates
- Universe assembly from watchlist + ETF preset + filters.
- Scan accounting: scanned / excluded (with reasons) / no-candidate. **[S-scan]**
- Quality gates (§6.4); NO-TRADE is a first-class, recorded outcome with the
  specific failed gate.
- Ranking with every term + weight inspectable.
- Risk engine: sizing from per-trade risk % and stop distance; enforce
  concentration, exposure, correlated-exposure, daily-risk limits; reject →
  NO TRADE when limits can't be met.

**[AC]**
- `scan_run` row shows counts that reconcile:
  `scanned = candidates + no_trade + (excluded is separate)`.
- Property test: no produced size violates any configured limit. **[S4]**
- A candidate detail payload contains every field in ARCHITECTURE §7.2,
  including `reasons_qualify`, `reasons_fail`, `data_freshness_json`.
- With short candidates disabled, zero SHORT candidates are produced.

### 1.7 Paper-trading ledger + journal
- `paper_account` with user-set initial cash.
- Accept / reject / ignore / watch a candidate. **No auto-simulation** unless the
  user enables "auto-simulate qualified signals" (off by default).
- Simulated fills: use ref quote ± half-spread ± slippage; record every
  assumption on the fill.
- `paper_trade` append-only + immutable; corrections via `trade_correction`.
- Positions, realized/unrealized P&L, exposure, drawdown, sector concentration,
  performance by strategy/horizon.
- Journal entry template (§ spec): timestamp, signal snapshot, why-qualified,
  why-might-fail, plan (entry/exit/stop/time-stop), notes, outcome,
  rule-adherence, lessons.

**[AC]**
- Attempting to `UPDATE`/`DELETE` a `paper_trade` raises at the repository layer
  and there is no ORM mapping that permits it. **[S9]**
- Cash + position value is conserved across an accept→fill→close cycle
  (property test).
- Disabling auto-simulate ⇒ no `paper_order` is ever created without an explicit
  user action (test).

### 1.8 Manual CSV portfolio import (offline)
- Upload a broker CSV (positions + transactions); format detection + column
  mapping; store in `imported_position` / `imported_transaction`.
- Exposure / concentration analytics reuse the risk math; shown **separately**
  from paper trading; long-term holdings clearly segregated.

**[AC]**
- The `portfolio.import` package has **no HTTP client in its import graph**
  (import-linter test). **[S2]**
- Importing a sample CSV produces an analytics view; nothing enters the scanner
  as a tradable candidate.

### 1.9 Kill switch
- Single state row; `KillSwitch.active()` checked at every job entrypoint, alert
  dispatch, and as a FastAPI dependency on state-changing endpoints.
- UI control on Overview + Settings; flip is audited.

**[AC]**
- With kill switch ON: scheduled ingest/scan/briefing jobs no-op with a logged
  reason; `POST` to paper-trade / promote-strategy endpoints → 423 Locked;
  alert dispatch is suppressed. All covered by tests. **[S6]**
- Time from flipping ON to API paths refusing writes: immediate (same request).

### 1.10 Dashboard (frontend option A unless overridden)
Pages: **Overview**, **Candidate Scanner**, **Candidate Detail (evidence)**,
**Portfolio & Import**, **Strategy Lab** (definitions + walk-forward reports +
enable/disable), **Journal**, **Settings** (keys, alerts, risk limits, universe,
kill switch, retention/backup). Options Learning page is a Phase 3 stub link.

- Global, non-dismissable disclaimer bar: hypothetical research, not advice,
  verify independently.
- Every data value shows source + timestamp + latency category + age.
- Stale/unavailable feeds show a prominent banner and disable live alerts.

**[AC]**
- Playwright happy-paths: login → view a candidate's full evidence page →
  paper-accept → see it in the ledger → add a journal note → flip kill switch →
  see writes blocked.
- Candidate detail renders chart, triggered rules with values, invalidation,
  costs/risks, upcoming events, "why not to take it", and the backtest stats for
  that exact `strategy_version`.
- Scanner shows "Universe scanned / Excluded (reasons) / No valid candidate".

### 1.11 Daily briefing
- Deterministic assembly of: market status, feed status + latency, paper account
  summary, open paper risk, high-priority risk warnings, today's qualified
  candidates, NO-TRADE count + reasons.
- Optional LLM pass (only if `LLM_API_KEY` set) that renders prose around the
  **frozen facts dict**; `llm.guards` rejects new numbers or a missing
  "AI explanation, not a trading instruction." footer. Briefing works fully
  without an LLM.

**[AC]**
- Briefing generated with no LLM key configured is complete and correct.
- With an LLM key: `llm_call` row recorded; guard test rejects a synthetic
  response that injects an unsupported statistic. **[S3 / S-llm]**

### 1.12 Alerts (local + optional email)
- **Default: all alerts OFF** until setup completed.
- Channels: local (on-page + log file) always; email (SMTP) if configured.
- Policy: ≤ 2 high-priority candidate alerts/day; 1 daily briefing; none when
  data stale or strategy disabled; none overnight except system-health failures;
  no options alerts.
- Every alert body includes: instrument, horizon, strategy/version, price+ts,
  data freshness, entry zone, invalidation, upcoming event risk, reward/risk,
  why-qualified, why-might-fail, link to the local evidence page, and
  **"Research signal only — no order was placed."**

**[AC]**
- Fresh install sends nothing until the user completes setup and enables a
  channel (test).
- Cap test: the 3rd high-priority candidate in a day is suppressed with a logged
  reason.
- Stale-feed test: no candidate alert dispatched; system-health alert still can.
- Snapshot test of an alert body asserts the mandatory lines are present.

### 1.13 Docs & release notes for Phase 1
- `README.md`: what it is / is not, setup, `make dev`, first-run, disclaimers.
- `SECURITY.md`: threat model (ARCHITECTURE §12 expanded), secret handling,
  prompt-injection stance, kill switch, backup encryption.
- `docs/architecture-diagram.md`: the mermaid diagrams + narrative.
- `backup.sh` + restore instructions (SQLite copy + optional gpg/age).
- End-of-phase report (template in §"Phase exit report").

### Phase 1 exit criteria (all must hold)
- `make test` green; CI green; coverage reported.
- Safety suite S1–S10 all present and passing.
- A screen-recording or screenshot set of the 11-step happy path.
- Phase exit report written, honestly listing what is simulated (fixture data),
  delayed (real adapter latency), unsupported (intraday, options, streaming),
  and unvalidated (any strategy still `experimental`).

---

## Phase 2 — Durable deployment, intraday, more strategies, validation depth

**Goal:** move from "works on my laptop" to "runs reliably", add intraday, and
harden validation.

- Postgres + Docker Compose (api, worker, postgres, redis); `make up`.
- Migrate frontend to **React + TypeScript + Vite** (contract unchanged).
- Arq worker; move ingest/scan/briefing jobs off the API process; polling
  data-adapter layer with backoff + rate-limit accounting.
- Intraday bars + the INTRADAY horizon (A) with its own features/backtest/alert
  policy; session-aware (pre/RTH/post).
- Strategies 3 (relative strength / sector momentum) and 4
  (volatility-contraction breakout); post-earnings-drift module remains disabled
  until it passes thresholds.
- Two-real-source reconciliation where the user has two providers.
- **Strategy-health monitor**: compares rolling live-paper expectancy to backtest
  expectation; auto-downgrades (`paper_approved` → `experimental`) or disables on
  a material, sustained shortfall; all transitions audited and shown in
  Strategy Lab.
- Parameter-sensitivity grids + Monte Carlo in Strategy Lab UI.
- Additional alert channels: Discord, Slack, push (ntfy/Pushover), SMS if a
  provider key is supplied.
- Better charts; journal analytics (rule-adherence trends, expectancy by
  setup/tag), weekly review view.

### [AC] highlights
- `docker compose up` brings the whole stack up with migrations applied and seed
  data labelled simulated.
- Intraday scan honors the freshness gate at intraday budgets; if the quote feed
  is delayed, INTRADAY alerts are disabled automatically. **[S8]**
- Health monitor test: a synthetic live-paper losing streak triggers an audited
  downgrade and removes the strategy from alert eligibility.
- React app passes the same Playwright happy-paths as Phase 1.

---

## Phase 3 — Licensed real-time data, options education, research/LLM retrieval

- Integrate a licensed real-time provider behind the existing adapter interface;
  `latency_category=REALTIME` only with an explicit entitlement flag; "live"
  labels unlock only for entitled feeds.
- **Options education & paper-simulation module** (education/simulation only):
  call/put explainers, break-even calculator, long-option max-loss, theta/time-
  decay visualization, IV explanation, earnings-event risk; covered-call and
  cash-secured-put educational simulators (user-supplied assumptions);
  defined-risk vertical-spread simulator as an optional sub-module; paper-only
  options positions. Prominent expiry/worthless and complexity warnings. No
  naked/uncovered/margin/0DTE-alert/execution anything.
- **Research-document retrieval + LLM explanation layer**: fetch filings /
  transcripts / news from configured licensed sources; retrieval-augmented
  summaries with citations; conflicting-narrative detection with linked source
  text; journal behavioral-pattern analysis. All within the §11 boundaries;
  retrieved text is sandboxed as untrusted content.
- Advanced portfolio-risk controls: factor/beta exposure, scenario/stress views,
  correlation-cluster limits.
- External always-on deployment guide (single small VM): reverse proxy + TLS,
  host secret store, backup rotation offsite (user-controlled), monitoring.

### [AC] highlights
- With no real-time entitlement configured, nothing anywhere reads "live".
- Every options screen is simulation/education; there is no order surface and no
  margin-dependent strategy in the code.
- Every LLM summary carries citations, input timestamps, a stale/missing-data
  note, and the "AI explanation, not a trading instruction." line; guard tests
  cover fabricated-number and missing-footer rejection.

---

## Cross-cutting acceptance criteria (every phase)

1. **No brokerage surface.** import-linter + CI grep denylist pass; no broker
   hostname in any allowlist; no credential-shaped field in the schema. **[S1]**
2. **LLM out of the decision path.** import-linter contract passes. **[S3]**
3. **Determinism.** Re-running a scan/backtest with the same inputs, config_hash
   and seed yields identical outputs. **[S4]**
4. **Secret hygiene.** `detect-secrets` clean; logs redact key names; only
   `.env.example` placeholders in git. **[S5]**
5. **Kill switch.** Toggling ON halts polling, jobs, alerts, and paper-trade
   creation, verified by test. **[S6]**
6. **Honest labelling.** Latency category shown everywhere; stale feed disables
   live alerts and marks results. **[S7, S8]**
7. **No unearned confidence.** Probability/confidence shown only when it is a
   calibrated OOS number for that exact strategy version. **[S10]**
8. **Phase exit report** delivered, not overstating capabilities.

---

## Phase exit report (template used at the end of each phase)

```
## Phase N exit report — <date>

### Built (with evidence)
- <feature> — <test / screenshot / command>

### Still simulated
- <e.g. all market data is the fixture adapter unless a key is set>

### Delayed / not real-time
- <adapter> latency_category = <DELAYED 15m / EOD>

### Unsupported in this phase
- <intraday / options / streaming / provider X>

### Unvalidated
- <strategies still `experimental`; metrics with wide CIs; regimes not yet seen>

### Security limitations
- <e.g. local-only auth, no rate-limit on login beyond delay, backups
  unencrypted unless gpg configured>

### Data-quality limitations
- <single-source for field X; reconciliation not yet meaningful; survivorship
  bias in the free daily history>

### Test run
- <pytest summary line, coverage %, CI link/commit>
```

---

## Setup questions (minimum needed before scaffolding Phase 1)

Known already: macOS (Darwin 25.6); system Python 3.9 (will install 3.12 via
`uv`); no Node/Docker installed yet.

1. **Frontend for Phase 1:** Option A (HTMX/Jinja now, React in Phase 2 —
   recommended, no Node needed for the MVP) or Option B (React + TS now)?
2. **Market-data provider:** free/sandbox for now, or a specific provider you
   already pay for (Alpaca / Polygon.io / Tiingo / other)?
3. **Notifications for Phase 1:** local-only (on-page + log), email (SMTP), or a
   Discord/Slack webhook?
4. **Paper account starting size?** (default proposal: $25,000)
5. **Initial watchlist / ETF universe?** Default proposal below — edit freely:
   - Broad market: SPY, QQQ, IWM, DIA
   - Sectors (SPDR): XLK, XLF, XLE, XLV, XLY, XLP, XLI, XLB, XLU, XLRE, XLC
   - Liquid single names (watchlist): AAPL, MSFT, NVDA, AMZN, GOOGL, META, JPM,
     XOM, UNH, HD
6. **Always-on host** (Phase 2/3 only): Mac laptop only, or a Pi / VM you can run
   24/7 later?

---

## Phase 1 exit report — 2026-09-06

### Built (with evidence)
- **Persistence** — 43 SQLAlchemy tables (ARCHITECTURE §5), Alembic migration
  with `paper_trade` BEFORE UPDATE/DELETE triggers. `make migrate` round-trips;
  `tests/db/`.
- **Local auth** — Argon2id, first-run registration that then closes, session
  cookie (HttpOnly, SameSite=strict), CSRF on every form, login backoff, loopback
  bind. `tests/app/test_auth.py`.
- **Data** — adapter interfaces + capability descriptors; offline deterministic
  `fixture` adapter; free `stooq` EOD adapter; ingestion (normalize, raw-payload
  cache, dedupe, quality flags, feed status); cross-source reconciliation;
  `FreshnessGate` (S8). `tests/data/`.
- **Backtest** — event-loop engine (signal sees `head(t)`, fill at `t+1` open,
  stop→target→time-stop, costs in fills), full metric set, walk-forward IS/OOS,
  seeded bootstrap CIs, regime segmentation, leakage detector. `tests/backtest/`.
- **Strategies** — `trend_continuation` (2 horizons) + `mean_reversion`, each a
  versioned `StrategySpec`, all `EXPERIMENTAL`; regime filter as a gating input;
  committed `reports/*.md`. `tests/research/test_strategies.py`.
- **Scan → rank → risk → candidates** — separated accounting (scanned / excluded
  with reasons / NO-TRADE), quality gates (reward:risk, OOS expectancy + CI +
  trade count, risk-engine sizing), transparent ranking, S10 probability guard,
  persistence. `tests/research/test_scan.py`, `tests/risk/`.
- **Paper ledger + journal** — accept / reject / ignore / watch, simulated fills
  with spread + slippage, immutable `paper_trade` (S9) + append-only corrections,
  mark-to-market, weekly review. `tests/paper/`.
- **CSV portfolio import** — offline (S2), format detection, idempotent by
  content hash, exposure analytics, kept separate from the paper ledger.
  `tests/portfolio/`.
- **Kill switch integration** — `guarded()` no-ops every scheduled job; startup
  catch-up; 423 on state-changing routes. `tests/test_scheduler.py`,
  `tests/safety/test_s6_kill_switch.py`.
- **Dashboard** — Overview, Scanner, Candidate Detail (evidence + SVG sparkline +
  OOS stats for that exact strategy version), Portfolio & Import, Strategy Lab,
  Journal, Briefing, Options (learn stub), Settings. `tests/app/test_dashboard.py`.
- **Daily briefing** — deterministic frozen facts + Markdown, complete without an
  LLM; optional grounded LLM narrative with an `llm_call` audit row.
  `tests/research/test_briefing.py`, `tests/test_briefing_llm_guard.py`.
- **Alerts** — policy engine (OFF by default, caps, quiet hours, dedupe,
  stale-feed → health-only), local + optional email channels, mandatory lines in
  every body. `tests/alerts/`.
- **Backup / restore** — consistent SQLite snapshot, optional gpg, `.pre-restore`
  safety copy. `tests/test_backup.py`.
- **Gates** — Ruff, Black, mypy (strict on the decision core), import-linter
  (4/4 contracts KEPT), `detect-secrets` clean, GitHub Actions CI.
  **175 tests pass**, ~86% coverage.

### Still simulated
- All market data unless a real provider is configured — the default `fixture`
  adapter is a deterministic random walk, every datum `is_simulated=True` /
  `HISTORICAL`. Seed data, all backtests, and every scan on a fresh install run
  on it.

### Delayed / not real-time
- `stooq` adapter is `END_OF_DAY` (split-adjusted close only, no dividend
  adjustment). Nothing anywhere is labelled "live" — `latency_category=REALTIME`
  has no code path yet.

### Unsupported in Phase 1
- Intraday bars and the INTRADAY horizon (Phase 2).
- Streaming / polling adapter layer, second real data source, meaningful
  two-source reconciliation.
- Strategies 3–5 (relative strength, breakout, post-earnings drift),
  parameter-sensitivity grids, the strategy-health auto-downgrade monitor.
- Discord / Slack / push / SMS alert channels.
- Options education & simulation module; research-document retrieval; advanced
  factor/scenario portfolio risk (all Phase 3).
- Postgres, Docker Compose, a durable job worker (Phase 2).
- Frontend is server-rendered HTMX; the React + TypeScript SPA is Phase 2
  (ADR 0001). No Playwright E2E — covered by FastAPI TestClient integration tests.

### Unvalidated
- All three baseline strategies are `EXPERIMENTAL`. On the fixture data their
  out-of-sample expectancy is ≈ **−1R** with a ~6% win rate — no edge net of
  costs. The scanner therefore returns **NO TRADE for every candidate**, no
  strategy is promoted, and no candidate alert can fire. This is the correct,
  intended outcome; the strategies have not been validated on real data.
- Confidence / probability figures are never shown (no calibrated out-of-sample
  `calibration_ref` exists yet) — S10.
- Walk-forward re-fits no parameters in Phase 1 (the strategies have none); it is
  an IS-vs-OOS partition of a single run, documented as such.

### Security limitations
- Local single-user auth, no MFA; login backoff only (no lockout, no route rate
  limiting). App binds to `127.0.0.1`; `APP_ENCRYPTION_KEY` unset in dev uses an
  ephemeral session secret.
- Backups are plaintext unless a passphrase is supplied and `gpg` is installed.
- Restore is stop-the-app.
- Provider keys are read from `.env` only and shown as set/not-set in the UI; the
  encrypted local secret store is Phase 2/3.

### Data-quality limitations
- Single data source on a default install → reconciliation is inert.
- Free EOD history has survivorship bias (flagged in the UI, not corrected) and
  no dividend adjustment.
- The fixture session calendar is weekdays-only (no holidays); the NYSE calendar
  is used by the backtest engine but not yet by ingestion.

### Test run
- `uv run pytest` → **175 passed, 1 warning** (third-party starlette
  DeprecationWarning), ~86% line coverage.
- `uv run ruff check` / `black --check` / `mypy` / `lint-imports` → all clean,
  4/4 architectural contracts KEPT.
- CI workflow: `.github/workflows/ci.yml` runs the same gates on push / PR.
