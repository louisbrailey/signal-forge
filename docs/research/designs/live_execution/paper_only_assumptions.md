# Paper-only assumption inventory + live-execution layer design (read-only mapping)

Status: **design only — nothing implemented, nothing enabled, no repo file
changed except this one.** Written against `main` @ `d84bb46` (2026-09-10).
All DB reads below are read-only `SELECT`s against `data/signalforge.sqlite`;
no provider/network call was made; no package installed.

Scope per operator brief: (1) inventory every place the codebase currently
assumes "paper/research-only, no brokerage, ever" so a live-execution layer can
be added later as an explicitly gated module without silently breaking that
assumption anywhere; (2) design (not build) that module; (3) survey paper/sandbox
broker APIs as facts-with-caveats, no investment advice; (4) list regulatory/
practical constraints to disclose factually.

---

## Part 1 — Inventory: everywhere "no order was ever placed" is load-bearing

### 1.1 `RESEARCH_ONLY_NOTICE` / "no order was placed" — every usage (FACT)

Canonical string, defined twice, identically, in two places:
- `src/signalforge/__init__.py:13` — `RESEARCH_ONLY_NOTICE = "Research signal only — no order was placed."`, exported in `__all__` (line 19).
- `src/signalforge/sf1000/__init__.py:21` — same literal, independent constant (SF1000 module deliberately does not import the top-level one — see S13 below).
- `src/signalforge/options/__init__.py:16` — third independent constant `DISCLAIMER`, same literal string (options module deliberately does not import the top-level one either — see S11).
- `src/signalforge/llm/guards.py:18` — fourth independent constant `RESEARCH_ONLY_LINE`, same literal, used to validate LLM narrative output.

Consumers of the top-level `RESEARCH_ONLY_NOTICE`:
- `src/signalforge/alerts/render.py` — appended to **every** alert body type (candidate alert, briefing alert, data-issue alert, system-health alert), lines 7, 22, 49, 57, 71, 83. Candidate alerts carry it twice (top and bottom of body).
- `src/signalforge/alerts/channels/discord.py:22` — `_FOOTER` constant, same literal, appended to every Discord message.
- `src/signalforge/agents/base.py:137-138,157` — every `AgentReport.summary` gets the notice appended if not already present, and every failure summary carries it too — this is enforced code, not just convention.
- `src/signalforge/app/templating.py:16` — injected into every Jinja2 template context as `research_only_notice`, so it is renderable on any dashboard page.
- `src/signalforge/research/briefing.py:177` — daily briefing markdown footer, plus a second, longer disclaimer sentence at `briefing.py:253` ("...no order was placed. Verify every input independently.").
- `src/signalforge/paper/ledger.py:187` — `PaperTrade`/fill note: `"SIMULATED fill — no order was placed"` (slightly different literal, on the fill record itself, not the alert).
- `src/signalforge/paper/ledger.py:463` — portfolio snapshot dict key `"notice"` carries the full canonical string, i.e. it round-trips into the `/portfolio` API/UI payload.
- `src/signalforge/paper/auto_simulate.py:27` (module docstring) and `:60` (`ACCEPT_NOTE`, embedded in every auto-simulated `PaperTrade`'s acceptance note) — both carry the literal.
- `src/signalforge/cli.py` — printed via `typer.echo(...)` after essentially every mutating CLI command (paper accept, paper reject, scan, ingest, promote, etc.) — 20 call sites (lines 150, 271, 337, 425, 848, 1021, 1087, 1144, 1153, 1160 docstring, 1169, 1279, 1431, 1585, 1645, 1694, 1723, 1819, 1851, 1946, 2096, 2145, 2181).
- `docs/AGENT_ROLES.md:9` and `docs/CAPABILITY_MATRIX.md:49` document the same guarantee for agents and for the alerts capability row respectively.
- Tests that assert the exact string is present (not a paraphrase) span 13 files: `tests/app/test_health_and_disclaimer.py`, `tests/app/test_dashboard.py`, `tests/agents/test_agents_data_strategy_ops.py`, `tests/agents/test_boundaries.py`, `tests/agents/test_agents_regime_news_risk_journal.py`, `tests/alerts/test_dispatch.py`, `tests/alerts/test_discord.py`, `tests/alerts/test_approval_scope.py`, `tests/research/test_briefing.py`, `tests/paper/test_activation_guards.py`, `tests/paper/test_auto_simulate.py`, `tests/options/test_options_math.py`, `tests/sf1000/test_phase_a_boundaries.py`.

**Design implication (HYPOTHESIS):** none of these call sites can simply be
left alone once a live order can actually be placed — the sentence becomes
*false* for a live-armed strategy's alerts/CLI output/dashboard the moment
`signalforge.execution` submits a real order. The design in Part 2 keeps
`RESEARCH_ONLY_NOTICE` **unchanged** for every existing paper-only surface
(alerts, agents, briefing, SF1000, options, research CLI commands) and
requires any live-order-adjacent surface to render a **different, new**
notice sourced only from `signalforge.execution` (never by mutating the
shared constant) — see §2.7.

### 1.2 Import-linter contracts (`pyproject.toml:173-267`) — FACT, verbatim intent

`[tool.importlinter]` root package `signalforge`, `include_external_packages = true` (so `httpx`, `ib_insync`, etc. count as importable modules for contract purposes even though they're third-party).

| Contract | Forbids | Source packages |
|---|---|---|
| **S3** "LLM layer is never on the deterministic decision path" | `signalforge.llm` | `research`, `risk`, `backtest`, `paper` |
| **S2** "manual CSV portfolio import performs no network I/O" | `httpx`, `requests`, `aiohttp`, `socket`, `urllib`, `signalforge.data` | `portfolio` |
| **S1** "no brokerage / execution / browser-automation surface anywhere" | `ib_insync`, `ibapi`, `alpaca_trade_api`, `selenium`, `ccxt` | **`signalforge`** (whole package — root-level, applies everywhere) |
| Layering | `research`, `risk`, `backtest`, `paper`, `app`, `alerts` | `data.adapters` |
| **S11** "options are education/simulation only" | `alerts`, `llm`, `research.scan`, `research.candidates`, `paper.ledger` | `options`, `data.options_backfill` |
| **S12** "news never drives a recommendation or risk decision" | `data.news_ingest`, `data.adapters.massive_news`, `llm.summarize_news` | `research.scan`, `research.candidates`, `research.strategies`, `risk` |
| **S13** "SF1000 is simulated research only" | `alerts`, `paper.ledger`, `llm`, `research.promotion`, `httpx`, `requests` | `sf1000` |
| **S14** "research agents are read-only reporters" | `paper.ledger`, `alerts.dispatch`, `alerts.channels`, `research.scan`, `research.candidates`, `research.promotion`, `research.persistence`, `data.ingest`, four concrete data adapters, `universe.pipeline`, `killswitch`, `httpx`, `requests` | `agents` |

**S1 is root-scoped on `signalforge` itself** — this is the one contract a
new `signalforge.execution` package cannot simply sit beside; it is *the*
brokerage-surface ban, and it currently applies to every module including a
future `execution` one. Adding execution means S1 must be **narrowed
explicitly and visibly** (e.g. to `signalforge` minus `signalforge.execution`,
or replaced by a new pair of contracts — see §2.9) — never silently
weakened. `ib_insync`/`ibapi`/`ccxt` stay banned everywhere including inside
`execution` (equities/options paper trading doesn't need them); `alpaca_trade_api`
is the one banned name a paper-broker adapter would plausibly want to import.

Mirrored at the linter level by Ruff (`pyproject.toml:104-110`,
`[tool.ruff.lint.flake8-tidy-imports.banned-api]`): `ib_insync`, `ibapi`,
`alpaca_trade_api` (message: *"No brokerage/trading API. Data-only adapters
live in signalforge.data.adapters."*), `selenium`, `ccxt` are banned import
names project-wide, each with an explanatory `.msg`. This denylist must also
be edited (not silently, with the same explicit-scope discipline) when
`signalforge.execution` is added.

Mirrored a third time by a source-level scanner,
`tests/safety/test_s1_no_broker_surface.py` (not just import-linter):
- `BANNED_IMPORTS` set (18 names: `ib_insync`, `ibapi`, `ibkr`,
  `alpaca_trade_api`, `alpaca`, `selenium`, `playwright`, `pyppeteer`,
  `webdriver`, `ccxt`, `robin_stocks`, `tda`, `schwab`, `fidelity_api`,
  `MetaTrader5`) — scanned via `ast.walk` over every source file
  (`iter_source_files()`), not just declared imports.
- `BANNED_CALL_SUBSTRINGS` — **plain substring match over file text**, not
  AST-aware: `"place_order"`, `"submit_order"`, `"route_order"`,
  `"execute_order"`, `"execute_trade"`, `"send_order"`, `"cancel_order("`,
  `"buy_shares("`, `"sell_shares("`. A `BrokerAdapter.submit_order()` method
  name (exactly what the operator's brief asks for) **is a banned substring
  today** — this test would fail the instant that method name exists anywhere
  under `iter_source_files()`'s scan root, gated module or not.
- `test_importing_every_submodule_pulls_no_broker_module` — spins up a clean
  interpreter, `pkgutil.walk_packages`-imports every `signalforge.*` submodule,
  asserts none of `{ib_insync, ibapi, alpaca_trade_api, alpaca, selenium,
  playwright, pyppeteer, ccxt, MetaTrader5}` ends up in `sys.modules`. A paper
  broker SDK imported anywhere reachable by `walk_packages` (i.e. anywhere
  under `signalforge/`, including inside a gated `execution` subpackage) trips
  this even if the module is never *called*.

**This is the single largest concrete blocker to "add execution without
breaking existing safety tests":** `test_s1_no_broker_surface.py` today
encodes "this whole codebase" as the source scope for both the call-substring
scan and the import scan. It must be **rewritten to allow one explicitly
carved-out subpackage** (`signalforge.execution.brokers.*`) while continuing
to ban everything else at 100% of today's strictness — not loosened, not
deleted. `docs/AGENT_ROLES.md:61` also references
`test_no_broker_dependencies_or_connectors` (a `pyproject.toml`/`uv.lock`
scan) as proof S1 holds — same discipline applies there.

### 1.3 `ARCHITECTURE.md` §1.2 and §2 (FACT)

- §1.2 "Explicit non-goals (V1)": *"No brokerage connection of any kind. No
  order execution, no trade routing, no OMS... No unofficial/reverse-engineered
  brokerage APIs."* (lines 36-47). This is a **V1-scoped** non-goal list, so a
  V2 execution layer is not itself a contradiction of the document — but the
  document as written gives no forward pointer to a V2, and §2's invariant
  table (S1-S10) states S1 as *"No module imports a brokerage SDK, opens a
  brokerage URL, or stores a field named like a broker credential"* with no
  carve-out language at all. Any live-execution work needs an explicit
  ARCHITECTURE.md amendment (new §, e.g. "V2: gated live-execution layer") —
  not a deletion or a loosening of the existing S1 sentence, since S1 as
  literally written still holds for every package *except* the new one.
- §4.1 package layout (lines 197-249) already reserves
  `data/adapters/alpaca/ polygon/ tiingo/ ...` as a **market-data** adapter
  namespace ("added as configured"). **Naming collision risk (HYPOTHESIS):** a
  brokerage-facing Alpaca **paper-trading** adapter must not live under
  `signalforge.data.adapters.alpaca` — that path is already conceptually
  claimed for a market-data vendor adapter and is inside `signalforge.data`,
  which Layering and S14 forbid from touching `research`/`paper`/`app`/`alerts`
  in one direction and which the whole codebase treats as read-only market
  data. The execution-layer Alpaca adapter must live under
  `signalforge.execution.brokers.alpaca_paper` (or similar), a fully separate
  namespace, to avoid a very easy but very serious mistake (a network client
  meant for order routing accidentally reachable from the data layer's already
  broad import graph).

### 1.4 `alerts/render.py` wording (FACT — read in full, §1.1 above lists line numbers)

Every alert type — candidate, briefing, data-issue, system-health — embeds
the canonical notice, and the candidate alert additionally says *"No
brokerage was contacted"* (`render.py:22`, immediately under the notice) and
labels the underlying number as *"research signal"* in its subject line
(`f"... — research signal"`, `render.py:17`). This wording is specific enough
that it cannot be reused verbatim for a future "this candidate was armed and
an order was submitted to a paper broker" alert — that needs its own,
separately named render function (see §2.7), not a flag on the existing one.

### 1.5 `docs/METHODOLOGY.md`, `docs/CAPABILITY_MATRIX.md`, `docs/AGENT_ROLES.md`, `README.md` (FACT)

- `METHODOLOGY.md:1-4`: *"Signal Forge is research / paper-trading / education
  only. No brokerage connection, order placement, or trade mirroring exists
  anywhere in the codebase (enforced by import-linter contract S1)."* — this
  sentence is **currently true and cited as enforced by S1**; the moment S1 is
  narrowed (§1.2 above), this sentence becomes false as written and needs its
  own amendment describing the gated exception.
- `CAPABILITY_MATRIX.md:49`: alerts row states every body carries the notice —
  same forward dependency as §1.1/§1.4.
- `CAPABILITY_MATRIX.md:52`: paper ledger row cites `paper/ledger.py::accept_candidate`
  as "Manual acceptance only" plus `auto_simulate_enabled()` — this is the
  **existing single guarded acceptance path** an OMS `OrderIntent` producer
  should sit downstream of, not replace (§2.2).
- `AGENT_ROLES.md:9`: agents' shared contract line, same notice; `:61` cites
  the S1 proof test discussed in §1.2.
- `README.md:14-24`: *"What it will not do"* bullet list —
  *"No brokerage login, credential storage, order placement, or trade
  execution... No browser automation of any brokerage or trading venue; no
  scraping of sites that prohibit it; no unofficial/reverse-engineered
  brokerage APIs."* This is the most-visible public-facing promise in the
  repo and needs the most explicit amendment (new section describing the
  gated, disarmed-by-default execution module, its kill switch, and that it
  only ever talks to an operator-chosen **paper**-trading endpoint unless
  separately and explicitly re-scoped).
- `README.md:91`: CLI table row `signalforge paper accept|mtm|snapshot` →
  *"Paper ledger (SIMULATED — no order placed)"* — same forward dependency.
- `DISCLAIMER.md:1-11` (repo root, not under `docs/`): the most legally-worded
  version — *"No orders are ever placed. Signal Forge does not connect to any
  brokerage, does not store brokerage credentials, does not execute or route
  orders..."* — same amendment need, and probably the file requiring the most
  careful, precise rewording since it is the user-facing legal disclaimer.

### 1.6 Tests asserting paper-only / no-broker behaviour (FACT, grepped for `broker`/`order`/`no order`)

26 test files reference `broker` or `order` (excluding the mirrored
`.claude/worktrees/wf_a348290c-356-1/` copy, which is identical): the S1
surface test (§1.2), the two "no order was placed" assertion groups (§1.1),
plus behavioural tests whose *logic*, not just wording, assumes paper-only:
- `tests/paper/test_activation_guards.py` — asserts *"no automatic acceptance
  caller exists"* outside the guarded path; this is a structural assertion an
  execution layer must not casually break by adding a second, unguarded
  acceptance-adjacent caller.
- `tests/paper/test_auto_simulate.py:192` — asserts the literal note text is
  present on an auto-simulated decision (§1.1).
- `tests/agents/test_boundaries.py` — `test_no_broker_dependencies_or_connectors`,
  `test_agent_sources_contain_no_state_changing_calls` (also scans for
  `.send(`, `httpx`, `subprocess` substrings — an execution module invoked
  from an agent would trip this by design; agents must stay forbidden from
  ever reaching `execution`, exactly as they're forbidden from `paper.ledger`
  today).
- `tests/sf1000/test_phase_a_boundaries.py` — asserts SF1000's own
  independent `RESEARCH_ONLY_NOTICE` constant equals the exact literal, and
  (per contract S13) that `sf1000` cannot import `paper.ledger`, `alerts`,
  `llm`, or `httpx`/`requests` at all — SF1000 stays fully walled off from any
  future execution path with no changes needed.
- `tests/options/test_options_math.py:55` — same literal-string assertion on
  `res.disclaimer`; per S11, `signalforge.options` cannot import
  `paper.ledger` at all, so options stays structurally incapable of reaching
  execution even indirectly, unless S11 itself is later revisited (out of
  scope here — the operator's plan proposes a *separate* options v0.2.0 effort
  on the existing paper pipeline, not options execution).

### 1.7 Kill switch (`killswitch.py`) — FACT, read in full

`src/signalforge/killswitch.py` (169 lines). Behaviour:
- File-backed (`KillSwitchState`: `active`, `reason`, `actor`, `changed_at`),
  atomic write (`tempfile.mkstemp` + `Path.replace`, `fsync`'d), JSONL audit
  trail at a separate log path, one process-wide singleton
  (`get_kill_switch()`), a `threading.Lock` per instance.
- **Fail-open on read errors, by explicit design** (module docstring, lines
  10-16): a missing file → not engaged; a corrupt/unreadable file → not
  engaged, logged at ERROR. *"silently freezing a research tool on a parse
  glitch is worse than the operator re-engaging explicitly."* — this is a
  **deliberate research-tool tradeoff that a live-execution OMS must not
  inherit**: for the execution module, a missing/corrupt kill-switch state
  (or a missing/corrupt *arming* state — see §2.4) must fail **closed**
  (treated as disarmed/blocked), the inverse of today's default. This is a
  genuine, consequential design fork, not a copy-paste of the existing
  primitive.
- `ensure_not_engaged(switch=None)` raises `KillSwitchEngaged` if active; used
  as an entry guard, never a mid-function check. 29 call sites across
  `scheduler.py`, `cli.py` (26 commands), `paper/ledger.py` (`accept_candidate`,
  one other), `paper/auto_simulate.py`, `alerts/dispatch.py::run_alert_cycle`,
  `universe/bulk.py` (3 sites incl. mid-loop), `data/adapters/massive.py` (5
  sites, incl. mid-pagination), `data/adapters/massive_news.py`,
  `data/adapters/massive_options.py`.
- **Global only** — one switch, no per-strategy or per-module granularity
  today. The operator's brief asks for "per-strategy arming with expiry" *in
  addition to* a "global kill switch" for execution — that is new state, not
  reachable by reusing `KillSwitch` as-is (see §2.4).

### 1.8 Audit (`audit.py`) — FACT, read in full (37 lines)

`src/signalforge/audit.py`: single function `record(action, *, actor="system",
entity="", **fields)`, appends one JSON line to
`{paths.logs_dir()}/audit.jsonl`, fields passed through
`signalforge.observability.redact()` first. `redact()`
(`observability/logging.py:17-41`) masks any `SecretStr` value and any dict
key matching `(?i)(api[_-]?key|secret|password|passwd|token|authorization|auth|bearer|credential)`,
recursively, depth-capped at 8. Module docstring says Phase 0 is JSONL-only;
*"Phase 1 adds an `audit_log` table and this becomes a thin façade that writes
to both"* — and a DB-backed `AuditLog` model already exists
(`db/models/system.py`, used by `agents/base.py::_persist` and referenced
throughout `AGENT_ROLES.md`), so the façade described in the docstring is
**already partially built** on the DB side; `audit.record()` itself is still
JSONL-only as read. An execution-layer audit trail should call through this
same `record()` (reusing the existing redaction regex, which already catches
generic `token`/`credential`/`auth` key names a broker SDK would plausibly
use) rather than inventing a parallel logger — but see §2.6 for why intents/
submissions/fills/rejections need their own **immutable, queryable** table
too, not just JSONL.

### 1.9 `settings_store.py` toggles — FACT, read in full (60 lines)

DB-backed overlay pattern: `AppSetting` row per key, `AppSettingHistory` row
per change (old/new value + actor), `get_setting`/`set_setting`, and
`effective_research_config()` deep-merges a `research_overrides` JSON blob
onto the env-sourced `ResearchConfig`. Two known keys already in this store:
`RESEARCH_OVERRIDES_KEY = "research_overrides"`, `APP_OVERRIDES_KEY =
"app_overrides"` (the latter appears unused elsewhere in the files read for
this task — HYPOTHESIS: reserved/future). Existing toggles that already gate
*paper*-side behaviour through this mechanism (confirmed via
`CAPABILITY_MATRIX.md` + `auto_simulate.py`): `alerts_enabled`,
`paper_probation_enabled`, `auto_simulate_max_per_day` (default 2, per
memory: alerts/Discord/auto-sim caps are 2/day each as of the 2026-09-10
paper-probation activation). This is the right mechanism to extend for
per-strategy arming flags and OMS limit overrides (§2.4) **provided** the new
keys are read only by `signalforge.execution`, never by `research`/`paper`/
`agents` — i.e. the execution module becomes a *new* consumer of
`settings_store`, not a reason to loosen who else can read arming state.

---

## Part 2 — Design: `signalforge.execution` (NOT IMPLEMENTED)

Everything below is a design for future work; no file under `src/` was
touched to produce it.

### 2.1 Package shape

```
signalforge/execution/                  # NEW top-level package, gated
  __init__.py            EXECUTION_LIVE_NOTICE constant (see §2.7) — deliberately
                          NOT signalforge.RESEARCH_ONLY_NOTICE
  adapter.py              BrokerAdapter Protocol (below)
  brokers/
    paper_reference/      first concrete adapter: a LOCAL, in-repo paper
                           simulator reusing signalforge.paper.ledger fill
                           logic — see §2.8, ships before any real vendor
    alpaca_paper/          first REAL vendor paper adapter (env/keychain
                           creds only, sandbox base URL only, hard-pinned)
  intent.py                OrderIntent — produced ONLY from an ACCEPTED
                           PaperTrade of an ARMED StrategyVersion
  oms.py                   OMS: limits, arming, kill switch, dead-man timer,
                           reconciliation, idempotency
  credentials.py            env-var-name / macOS-Keychain lookup only —
                           never a literal secret in code or DB
  audit.py                 intents/submissions/fills/rejections, appends to
                           the existing signalforge.audit.record() sink AND
                           a new immutable execution_event table
  ceremony.py               the operator arming ceremony (CLI-only, §2.5)
```

Import-linter additions needed (proposed, not applied):
- **New S1a**: `forbidden_modules = ["ib_insync", "ibapi", "ccxt", "selenium"]`
  from `source_modules = ["signalforge"]` (unchanged — these stay banned
  everywhere, including inside `execution`).
- **Narrow the existing S1** `alpaca_trade_api` ban to exclude
  `signalforge.execution.brokers.alpaca_paper` specifically (import-linter
  supports this via `ignore_imports` on the contract, scoped to exactly that
  one module path — not a blanket carve-out of the whole `execution` package,
  so every *other* file in `execution` — `oms.py`, `intent.py`, `ceremony.py`
  — still cannot import a broker SDK directly, only the one adapter file can).
- **New S15**: "execution is reachable only from a single, audited entry
  point" — `forbidden_modules = ["signalforge.execution"]` from
  `source_modules = ["signalforge.research", "signalforge.agents",
  "signalforge.llm", "signalforge.sf1000", "signalforge.options",
  "signalforge.alerts"]`. Only `signalforge.paper` (specifically, one new
  module that watches for ACCEPTED trades of ARMED strategies) and
  `signalforge.cli` (for the arming ceremony) may import `execution` at all.
  This mirrors the existing S14 pattern (agents forbidden from `paper.ledger`)
  applied to the new, higher-stakes boundary.
- `tests/safety/test_s1_no_broker_surface.py` rewrite (§1.2): scope
  `BANNED_IMPORTS`/`BANNED_CALL_SUBSTRINGS` scanning to exclude exactly
  `signalforge/execution/brokers/*/` (a path-prefix allowlist, still denying
  every other file including the rest of `execution/`), and add a **new**
  test in the same file asserting the broker SDK import + `submit_order`-
  shaped call sites exist **only** inside that one allowlisted directory —
  i.e. convert a pure denylist into "denied everywhere except this one
  audited, narrow place," which is strictly more scrutiny, not less.

### 2.2 `BrokerAdapter` Protocol

```python
class BrokerAdapter(Protocol):
    def submit_order(self, intent: OrderIntent) -> OrderSubmission: ...
    def cancel(self, broker_order_id: str) -> CancelResult: ...
    def get_positions(self) -> list[BrokerPosition]: ...
    def get_account(self) -> BrokerAccount: ...
    def get_order_status(self, broker_order_id: str) -> OrderStatus: ...
```

Every method is synchronous, idempotent where the verb allows it
(`submit_order` keyed by `intent.idempotency_key`, never re-submitted if a
prior submission with that key is already recorded — §2.4), and returns a
typed dataclass, never a raw SDK object (keeps every concrete broker SDK
import confined to exactly one file per broker, per S1a/S15 above).

### 2.3 `OrderIntent` — provenance, not just a payload

`OrderIntent` is produced by **exactly one** function, called from **exactly
one** place: a new watcher in `signalforge.paper` (structurally parallel to
`auto_simulate.py`'s existing "watch for qualified candidates, apply a guard,
act" shape) that observes newly-`ACCEPTED` `PaperTrade` rows. Construction
requires, checked in this order, each a hard precondition (raise, don't
degrade):
1. The `PaperTrade.decision == PaperDecision.ACCEPTED` (reuse the existing
   enum — an execution-eligible trade is still, first, a normal accepted
   paper trade; nothing about acceptance changes).
2. `PaperTrade.strategy_version_id`'s `StrategyVersion.status ==
   StrategyStatus.PAPER_APPROVED` **and** a new, separate `ArmedStrategy` row
   exists for that exact `strategy_version_id` (§2.4) with `expires_at` in the
   future — "paper-approved" and "armed for live" are two different, both-
   required gates; the first is unchanged existing state, the second is new.
3. Dataset-scope match exactly as `research/approval_scope.py::scan_scope_matches`
   already requires for alerts — reused, not reinvented.
4. Kill switch not engaged (global) **and** this strategy not individually
   disarmed (§2.4) — checked at intent-construction time and *again*
   immediately before `submit_order` (two checks, since time passes between
   queueing and submission).
5. Every OMS limit (§2.4) still has headroom.

`OrderIntent` itself carries: `paper_trade_id` (FK, so every live order traces
back to the exact immutable `PaperTrade` evidence snapshot that authorized
it), `idempotency_key` (deterministic hash of `paper_trade_id` + broker name —
never a random UUID, so a crashed-and-retried submission cannot double-order),
`symbol`, `side`, `qty`, `order_type`, `limit_price`/`stop_price` as
applicable, `time_in_force`, `created_at`. **No LLM-produced field is ever
read while building an `OrderIntent`** — mirrors S3 exactly, extended: the
execution package itself should carry an S3-shaped contract (`forbidden_modules
= ["signalforge.llm"]` from `source_modules = ["signalforge.execution"]`).

### 2.4 OMS — hard limits and state

New DB tables (design only):
- `armed_strategy` — `strategy_version_id`, `armed_at`, `expires_at`,
  `armed_by` (operator identity string), `broker`, `max_notional_per_order`,
  `max_notional_per_day`, `disarmed_at` (nullable — an explicit early
  disarm, distinct from natural expiry). Arming is **per strategy version**,
  never "all strategies" — a new version requires a new, separate arming act
  even if the prior version was armed (mirrors the existing rule that a new
  strategy version is a new row entirely, never a mutation).
- `execution_limits` (singleton-ish, or one row per broker account) —
  `max_open_positions`, `max_daily_loss_dollars`, `allowed_instruments`
  (explicit allowlist, defaults to the existing research universe's equity/ETF
  scope — never inherits options/forex automatically), `trading_hours_start`,
  `trading_hours_end`, `trading_calendar` (reuse whatever XNYS-calendar
  dependency `METHODOLOGY.md` already cites for gap detection, rather than a
  second calendar implementation).
- `execution_event` — append-only, one row per intent/submission/fill/
  rejection/cancel, FK to `paper_trade_id` and `armed_strategy_id`, plus the
  broker's own order id once known. This is the OMS-specific complement to
  the generic `audit.record()` JSONL sink (§1.8) — both are written, the
  table because reconciliation (below) needs to query it, the JSONL because
  it's the existing durable append-only substrate every other subsystem
  already trusts.
- Dead-man timer: a new row on `worker_heartbeat`-shaped state (reuse the
  existing `WorkerHeartbeat` table's pattern — `db/models/system.py:130`,
  already has `worker`, `last_beat_at`) for an `execution` worker; the OMS
  refuses to submit any order if its own heartbeat is stale beyond a
  configured threshold (fail closed, per §1.7's fail-open-vs-closed fork —
  this is the concrete mechanism that makes execution fail closed where the
  research kill switch fails open).
- Reconciliation: a scheduled job (reusing the existing `scheduler.py` +
  `ensure_not_engaged()` + `JobRun` pattern) comparing `BrokerAdapter.get_positions()`
  against open `PaperPosition` rows tagged as live-armed; any mismatch beyond
  a tolerance immediately engages the kill switch (global) and pages the
  operator — never auto-corrects the broker side.

Global kill switch: reuse `signalforge.killswitch.KillSwitch` unmodified for
the "stop everything, including all research jobs" case (already does this
for every existing job); layer the execution-only, fail-closed dead-man timer
and per-strategy `armed_strategy.disarmed_at` **on top**, not as a
replacement — three independent stop mechanisms (global kill switch,
per-strategy disarm, dead-man timer), each sufficient alone to block a
submission.

### 2.5 Operator arming ceremony (CLI-only, design)

Mirrors the deliberateness of the existing kill-switch CLI verbs
(`ensure_not_engaged` gates 26 CLI commands today) but inverted — arming is
opt-in per strategy version, time-boxed, and requires re-confirmation:
1. `signalforge execution arm <strategy_version_id> --broker alpaca_paper
   --max-notional-per-order N --max-notional-per-day N --expires-in 24h`
   — refuses unless the strategy version is `PAPER_APPROVED` on the exact
   scope it was approved against (reuse `approval_scope.scan_scope_matches`),
   refuses unless the target broker adapter reports (via `get_account()`) that
   it is genuinely pointed at a **sandbox/paper** base URL (a capability flag
   the adapter must expose and the ceremony must check — not a URL substring
   guess), and echoes the full limit set back for operator confirmation before
   writing the `armed_strategy` row.
2. `signalforge execution status` — one table: every `armed_strategy` row,
   time remaining, kill-switch state, dead-man-timer freshness, today's
   notional used vs. cap.
3. `signalforge execution disarm <strategy_version_id> [--reason TEXT]` —
   always available, always audited, no confirmation needed (disarming is
   the safe direction, symmetric with how `killswitch.release()` still
   requires a reason but never a multi-step confirmation).
4. Arming **always defaults to expiry** — there is deliberately no
   "arm forever" verb; re-arming after expiry is the same ceremony again,
   so a stale arming can never silently persist across, say, a strategy that
   was later disabled or downgraded by the health monitor
   (`research/health_monitor.py` — an existing auto-downgrade path that
   `armed_strategy` must also listen to: a `StrategyStatus` downgrade away
   from `PAPER_APPROVED` should auto-disarm, not merely be ignored by a
   now-orphaned arming row).

### 2.6 Audit

Every `OrderIntent` construction, every `submit_order` call and its result,
every rejection (OMS-limit or broker-side), every fill, every reconciliation
mismatch → one `execution_event` row (§2.4) **and** one
`signalforge.audit.record()` call (§1.8), reusing the existing `redact()`
pass so any credential-shaped field the broker SDK returns (many broker
account payloads echo back API key metadata) is masked by the same regex
already protecting every other subsystem's logs.

### 2.7 Notices — new, not a mutation of the existing one

Per §1.1/§1.4, `RESEARCH_ONLY_NOTICE` stays byte-for-byte unchanged and keeps
meaning "no order was placed" for every surface that still doesn't place one
(which remains the overwhelming majority: SF1000, options, research agents,
briefings, unarmed-strategy alerts, every CLI command not under
`execution`). A **new** constant, e.g.
`signalforge.execution.EXECUTION_LIVE_NOTICE = "Live paper-broker order —
placed with <broker>, sandbox/paper account. Not a real-money order unless
this account is explicitly a funded live account."`, is rendered only on
alerts/pages that concern an armed-strategy fill, and must make the
sandbox-vs-real distinction explicit every time (never assume the reader
remembers which broker/account is configured).

### 2.8 First adapter is a local reference, not a vendor

Before any vendor integration, build `brokers/paper_reference/`: an adapter
implementing `BrokerAdapter` purely against the existing
`signalforge.paper.ledger` simulated-fill logic, so the entire OMS (limits,
arming, idempotency, reconciliation-against-itself) can be tested end-to-end
with zero network access and zero vendor credentials, before `alpaca_paper`
(or any vendor) is even configured. This also gives reconciliation (§2.4) a
trivial self-consistent case to validate against first.

### 2.9 Net effect on S1

Today: *"no module imports a brokerage SDK... anywhere."* After: *"no module
imports a brokerage SDK anywhere, except exactly one file
(`signalforge.execution.brokers.<vendor>_paper`), which may be reached only
through the audited `OrderIntent` → OMS path, only for a strategy version
that is both `PAPER_APPROVED` and individually, time-boxed-armed by an
explicit operator ceremony, only against that vendor's paper/sandbox
endpoint."* That sentence, or its equivalent, is the exact text
`ARCHITECTURE.md` §1.2/§2, `METHODOLOGY.md`, `README.md`, and
`DISCLAIMER.md` all need amended into them together, in the same change, so
no one document is left contradicting another.

---

## Part 3 — Paper/sandbox broker APIs for U.S. equities and options (FACTS with caveats; no recommendation)

No network calls were made to verify any of the following — this task ran
read-only against the local repo/DB only, per the hard rules. Everything
below is from general knowledge as of this writing and **must be re-verified
directly against each vendor's current developer docs before any integration
work starts**; API shapes, sandbox availability, and approval requirements
change without notice.

- **Alpaca (paper trading API)** — Alpaca has historically offered a
  dedicated, free paper-trading environment (separate base URL and separate
  paper-only API keys from the live-trading environment) covering US equities
  and, in more recent offerings, options, alongside its live brokerage API.
  This is the vendor already named by the operator's brief and the one the
  repo's existing banned-import list singles out (`alpaca_trade_api` — see
  §1.2), which itself is *evidence the team has already looked at Alpaca
  before*, though the banned-api message doesn't say why. **Caveat**: confirm
  current paper-endpoint availability, current options-trading support in
  paper mode specifically (options paper support has historically lagged
  equities paper support at some vendors), rate limits, and whether the
  legacy `alpaca-trade-api` Python package or a newer `alpaca-py` package is
  the currently maintained SDK, directly against Alpaca's docs before
  building `brokers/alpaca_paper/`.
- **Interactive Brokers (IB) paper trading** — IBKR has long offered a paper
  trading account reachable through its TWS/Gateway API (`ibapi`, the
  official package, or the community `ib_insync` wrapper — both already named
  in this repo's S1 banned-import list, §1.2) as well as, more recently, a
  web-based Client Portal API. IB's paper environment typically requires
  running a local gateway/TWS process the API connects to, which is a
  materially different integration shape (a local daemon dependency, not a
  pure REST/websocket vendor call) than Alpaca or Tradier. **Caveat**: confirm
  current Client Portal API sandbox/paper support, current session/auth
  model (IB's auth has historically been comparatively involved — OAuth plus
  a running gateway process), and options-trading support in paper mode,
  directly against IBKR's docs.
- **Tradier (sandbox API)** — Tradier has historically offered a developer
  sandbox environment with simulated order execution, covering equities and
  options, using the same REST API shape as its live/brokerage accounts
  (distinguished by base URL/token scope rather than a wrapper SDK). **Caveat**:
  confirm current sandbox availability/limits (Tradier's sandbox has
  historically had daily/rate limits distinct from its live-brokerage
  tiers), current options-order-type coverage in sandbox mode, and whether
  a funded brokerage relationship is still a prerequisite to obtaining sandbox
  keys at all, directly against Tradier's current developer docs.
- **Webull OpenAPI** — status unclear and explicitly flagged as needing
  verification: Webull has, at various points, offered (or been reported to
  offer) a developer/OpenAPI program, but its availability, paper/sandbox
  support, and geographic/account restrictions have been comparatively less
  stable and less documented publicly than Alpaca/Tradier/IBKR's. **This
  status must be verified directly and currently before Webull is considered
  a candidate at all** — do not assume paper-trading availability without a
  fresh check of Webull's own current developer documentation.

No ranking or recommendation is offered among these four; the operator's
brief explicitly asked for facts-with-caveats, not investment or vendor
advice, and confirms the first-adapter choice will be made separately.

## Part 4 — Regulatory/practical constraints to disclose factually (not personalized advice)

- **Pattern Day Trader (PDT) rule** — under FINRA rules, a margin account at
  a U.S. broker-dealer flagged as engaging in "pattern day trading" (four or
  more day trades within five business days, if day trades exceed 6% of total
  trading activity in that window) is generally required to maintain at least
  $25,000 in account equity, or is restricted from further day trading until
  that minimum is met. This applies to margin accounts; cash accounts are
  generally not subject to the PDT day-trade-count rule in the same way but
  are instead constrained by settled-funds availability (see below). Paper
  trading accounts typically do not enforce PDT restrictions identically to
  live accounts — a design/testing implication, not a workaround, since going
  live later reintroduces the real constraint. This is general regulatory
  information, not advice about any specific account or strategy.
- **Options approval levels** — U.S. brokers generally require account
  holders to apply for and be granted an options trading "level" (commonly
  tiered, e.g. covered calls/cash-secured puts at a lower level up through
  uncovered/naked options and complex multi-leg spreads at higher levels),
  based on the broker's own suitability review (experience, account size,
  stated objectives). A paper/sandbox environment may or may not gate order
  types by a simulated approval level depending on the vendor — verify per
  vendor (§3) rather than assuming parity with a live account's approval
  level.
- **Margin** — trading on margin involves borrowed funds, interest charges,
  and the possibility of a margin call or forced liquidation if equity falls
  below a maintenance requirement; margin requirements differ by instrument
  (equities vs. options) and by broker, and are set both by FINRA/exchange
  minimums and by each broker's own house requirements (often stricter than
  the regulatory minimum). A design that only ever operates in a
  broker-paper environment does not eliminate the need to model margin
  correctly if the OMS is ever pointed at a live, margin-enabled account.
- **Settlement** — U.S. equity trades generally settle on a T+1 basis (as of
  the industry-wide move to T+1 settlement); in a cash account, proceeds from
  a sale are generally not available to fund a new purchase until settlement,
  and trading with unsettled funds repeatedly can trigger a "good faith
  violation" or, in more serious/repeated cases, a "free-riding" restriction
  on the account. This constrains same-day round-trip strategies in a cash
  account specifically and is independent of the PDT rule (which concerns
  margin accounts and day-trade counts, not settlement of funds).

None of the above is personalized investment, tax, or legal advice; it is
general, publicly known regulatory/practical context appropriate for a
system-design document, and it must be re-verified against current
FINRA/SEC/exchange rules and the specific broker's current account
agreement before the execution layer is built or armed against any real
account.

---

## Summary of what changes, and where, when execution ships (recap)

| Surface | Change required | Kind |
|---|---|---|
| `RESEARCH_ONLY_NOTICE` and its 3 sibling constants | **None** — stays true for every non-execution surface | unchanged |
| New `EXECUTION_LIVE_NOTICE` | New constant, new render paths, execution-only | additive |
| `pyproject.toml` S1 contract | Narrow with `ignore_imports` scoped to exactly one adapter file | explicit, scoped |
| `pyproject.toml` new S1a/S15 contracts | Add | additive |
| Ruff banned-api list | Same narrowing as S1, same file | explicit, scoped |
| `tests/safety/test_s1_no_broker_surface.py` | Path-prefix allowlist for the one adapter dir; add a positive test asserting the boundary holds | rewritten, stricter net |
| `ARCHITECTURE.md` §1.2, §2, §4.1 | New "V2: gated execution layer" section; S1 sentence gets an explicit exception clause; new package-layout entry with collision note (§1.3) | amended |
| `METHODOLOGY.md`, `README.md`, `DISCLAIMER.md` | Same S1-exception language, consistently, in the same change | amended |
| `killswitch.py` | Reused unchanged for the global stop; execution adds its own fail-closed dead-man timer on top (not a modification of `KillSwitch`'s fail-open read semantics) | additive, no modification |
| `audit.py` | Reused unchanged (`record()` + `redact()`); execution adds its own `execution_event` table alongside | additive, no modification |
| `settings_store.py` | Reused unchanged; execution adds new keys, read only by `execution` | additive, no modification |
| `StrategyStatus` enum, `PaperTrade`/`PaperPosition` models | Reused unchanged; execution adds new `armed_strategy`/`execution_limits`/`execution_event` tables and FKs in, never a column added to the existing immutable `PaperTrade` | additive, no modification |
