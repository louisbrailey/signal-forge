# D6 — Execution-layer ADR (draft for approval)

**Status: DRAFT, awaiting operator approval. Nothing here is implemented.**
No code, config, schema, contract, test, or gate was changed to produce this document. The only
file written by this workstream is this file.

- **Intended destination once approved:** `docs/decisions/0003-execution-layer.md` (FACT: the
  `docs/decisions/` tree currently holds exactly `0001-frontend-stack.md` and
  `0002-phase1-stack-simplifications.md`, so the next number is 0003; house format is
  Status / Deciders / Context / Decision / Consequences per
  `docs/decisions/0002-phase1-stack-simplifications.md:1-5`).
- **Deciders:** Louis Brailey (operator). Direction of 2026-09-11: Signal Forge is "no longer
  research use only"; end-to-end operational control granted.
- **Supersedes:** `docs/PORTFOLIO_RESEARCH_ROADMAP.md:32-36` and `:64-66` (quoted verbatim in §1).
- **Binding inputs, not re-litigated here:** `docs/research/OPTIONS_EXECUTION_PROGRAM_MAP.md` §6,
  §6.8, §7 (the map) and `docs/research/DECISIONS_2026-09-12_options_execution.md` decisions
  1, 2, 4, 9, 10 (and 3, 12, 13 where they touch execution).
- **Scope guard obeyed throughout:** `docs/research/STRATEGY_COMPLETION_MAP.md` §1 R1–R10 — no gate
  is weakened anywhere below; every addition is strictly more searching.

Every claim is labelled **FACT** (with `file:line` or a read-only SQL query) or **HYPOTHESIS**
(a design proposal this ADR is asking to have approved). Open questions are enumerated in §21.

**Read-only pass disclosure.** Producing this document placed no order, contacted no provider or
network endpoint, read no credential, and modified no repository file other than this one. All
database access was read-only `SELECT` against `data/signalforge.sqlite` while the live
paper-probation worker was running.

**Citation provenance (rev 3).** Every `file:line` in this document was re-read against the working
tree **again in this revision**, not inherited from rev 2. Corrections made in this pass:
`scheduler.py:150` → **`:151`** for `ensure_not_engaged()` inside `guarded()` (and the range
`145-152` → **`145-155`**); Q6's `scheduler.py:508` → **`:610-611`**; V14's `cli.py:1159` →
**`:1261`** (→ `:1267`); §11's `calendar.py:20-21`/`:25-34`/`:39-58` → **`:13`, `:34-35`, `:39-42`,
`:53-62`, `:64-71`**; `killswitch.py:9-13` → **`:9-12`**; S14's "four `data.adapters.*`" →
**five**. Re-verified unchanged in this pass: `scheduler.py:541`, `:610-611`, `:685`, `:821`,
`:837`, `:814-816`; `cli.py:19-25`, `:275-276`, `:1261`, `:1267`, `:1886-1889`, `:2347`;
`app/main.py:50`, `:59`; `app/views.py:736`, `:931`; `ledger.py:50`, `:129-160`, `:136`, `:156-159`,
`:163`, `:166`, `:185`, `:229`, `:272-275`, `:474-515`; `approval_scope.py:83`, `:109-110`;
`promotion.py:151`, `:175`, `:647`, `:978`, `:1023`, `:1414`; `settings.py:42/51/62/69/73`;
`settings_store.py:33`; `session.py:118-124`; `paper.py:100-117`, `:120-130`; `market.py:254-255`;
`system.py:95-104`, `:130-147`; `audit.py:26`; `logging.py:24`; `worker_lock.py:43`;
`pyproject.toml:104-110`, `:177-186`, `:194-198`, `:255-277`, `:280`;
`test_s1_no_broker_surface.py:15`, `:18-34`, `:37-47`, `:50-57`, `:80-100`; `tests/support.py:15`,
`:39-43`; the initial-schema trigger lines `:1267`, `:1274`, `:1285-1286`; `Makefile:65/76/80/84/88`;
`ARCHITECTURE.md:38-40/64/75/207`; `DISCLAIMER.md:9-13`; `README.md:17-19`, `:91`;
`CAPABILITY_MATRIX.md:49`; `options/__init__.py:1-11`. **No citation in this document is inherited
from the map: where the map and the working tree disagree (`cli.py:1158-1165`), the working tree
wins and the map is flagged for correction.**

**Citation provenance (rev 2, and this is a correction of a real failure in rev 1).** Rev 1
transcribed five `scheduler.py:` / `cli.py:` line citations from
`docs/research/OPTIONS_EXECUTION_PROGRAM_MAP.md` rather than re-reading the working tree, and all
five were wrong (two of them wrong in the map as well — the map's `cli.py:1158-1165` at map `:53`,
`:1378`, `:1947`). Every `file:line` citation in this revision has now been **re-read against the
working tree in this pass**; the corrections are listed in the closing appendix. The rule going
forward: a citation inherited from another document is not a FACT until it is re-read here, and any
citation this ADR carries is asserted to have been re-read.

---

## 0. What this ADR authorises, and what it does not

**Authorises (HYPOTHESIS, pending approval):**

1. The existence of a `signalforge.execution` package that can submit orders to a broker's
   **paper/sandbox** endpoint, disabled by default, and armed only by an audited operator
   ceremony per strategy version with a hard expiry.
2. The written supersession of the roadmap's "no brokerage, at any phase" boundary (§1, §18).
3. The schema, contracts, tests, and drills in §§2–20.

**Does not authorise, and this ADR explicitly re-prohibits:**

- Any real-money endpoint. Phase D6/I-E covers `paper_reference` (local, no network) and one
  vendor **paper** endpoint. A live-money endpoint is a separate operator decision and a separate
  ADR (§22).
- Any order decided, shaped, ranked, sized, timed, or described by an LLM. Enforced structurally
  by S15a/S15b and the S14 addition (§17), not by convention.
- Any order sourced from a manually accepted paper trade (§5, precondition P6).
- Any structure with undefined max loss, any leg-by-leg multi-leg submission, any 0DTE, any
  naked short option (map §4.5; §14 below explains why leg-by-leg creates one by accident).
- Any automatic liquidation, any automatic reconciliation repair, any retry of a broker
  rejection (§10, §12).
- Any credential acquisition, storage, rotation, or logging by the system (§16).

**Nothing is armed by default. The kill switch blocks opening and never blocks closing. No LLM
ever decides an order. Credentials exist only as env-var names or macOS Keychain item names.**

**The close lane is separately constructed and inversely fail-directed (rev 2, §5.2b, §7).** An
OPEN intent and a PROTECTIVE_CLOSE intent are built by **two different factories** with two
different precondition sets, and their fail-closed directions are **opposite**: a check that cannot
be evaluated **blocks opening** and **never blocks closing**. Rev 1 routed both through one factory
that required all seven opening preconditions, which made a protective close unconstructible in
exactly the disarmed/expired/kill-switched states §7 promises it works in — i.e. rev 1's own design
would have made the kill switch block closing. That is corrected below and drilled (V1, V2, V15,
and V18 — disarm a strategy holding an open short leg and prove the protective close still submits).

---

## 1. Context — the boundary being superseded, and the five places it is enforced

### 1.1 The committed text, quoted

FACT: `docs/PORTFOLIO_RESEARCH_ROADMAP.md` carries an undrafted, committed section headed
**"Non-negotiable boundaries"** ("These hold across every module in this document, with no exception planned at any phase",
`:29-30`). Two of its bullets are the ones superseded:

> "**No brokerage, no order placement, no trade mirroring, anywhere.** Enforced structurally by
> import-linter contract **S1** (`pyproject.toml`) and by `ruff`'s `flake8-tidy-imports`
> banned-api list (`ib_insync`, `ibapi`, `alpaca_trade_api`, `selenium`, `ccxt` are unimportable
> project-wide)." — `docs/PORTFOLIO_RESEARCH_ROADMAP.md:32-36`

> "**No brokerage/Webull/order-placement integration is in scope for any module, at any phase.**
> This roadmap does not create one and does not plan to." — `docs/PORTFOLIO_RESEARCH_ROADMAP.md:64-66`

FACT: `ARCHITECTURE.md:38-40` lists as V1 non-goals "No brokerage connection of any kind", "No
order execution, no trade routing, no OMS", "No browser automation of any brokerage or trading
venue". FACT: `DISCLAIMER.md:9-11` states "**No orders are ever placed.** Signal Forge does not
connect to any brokerage, does not store brokerage credentials, does not execute or route orders".
FACT: `README.md:17` "No brokerage login, credential storage, order placement, or trade
execution." FACT: `docs/METHODOLOGY.md:3-4` "research / paper-trading / education only. No
brokerage connection, order placement, or trade mirroring exists anywhere in the codebase".

### 1.2 The five independent enforcement points (all FACT, re-verified for this ADR)

| # | Mechanism | Exact current content | Location |
|---|---|---|---|
| E1 | import-linter **S1** | `type = "forbidden"`, `source_modules = ["signalforge"]`, `forbidden_modules = ["ib_insync", "ibapi", "alpaca_trade_api", "selenium", "ccxt"]` — **5 modules** | `pyproject.toml:194-198` |
| E2 | Ruff `flake8-tidy-imports.banned-api` | the same **5** names, each with a message citing "ARCHITECTURE.md S1" | `pyproject.toml:104-110` |
| E3 | Safety test, import scan | `BANNED_IMPORTS` = **15** names: `ib_insync, ibapi, ibkr, alpaca_trade_api, alpaca, selenium, playwright, pyppeteer, webdriver, ccxt, robin_stocks, tda, schwab, fidelity_api, MetaTrader5` | `tests/safety/test_s1_no_broker_surface.py:18-34` |
| E3b | Safety test, call-string scan | `BANNED_CALL_SUBSTRINGS` = **9** strings: `place_order, submit_order, route_order, execute_order, execute_trade, send_order, cancel_order(, buy_shares(, sell_shares(` | `tests/safety/test_s1_no_broker_surface.py:37-47` |
| E3c | Safety test, clean-interpreter check | imports every `signalforge.*` submodule in a fresh interpreter and asserts none of 9 banned modules landed in `sys.modules` | `tests/safety/test_s1_no_broker_surface.py:80-100` |
| E4 | `ARCHITECTURE.md` invariant table | "S1 \| No module imports a brokerage SDK, opens a brokerage URL, or stores a field named like a broker credential." + "Any change that would weaken S1–S10 must be called out explicitly in the PR description." | `ARCHITECTURE.md:64`, `:75` |
| E5 | Unconditional prose promises | `README.md:17-19`, `DISCLAIMER.md:9-13`, `docs/METHODOLOGY.md:3-4`, `docs/CAPABILITY_MATRIX.md:49` | as cited |

FACT (mechanism sizes differ, and neither subsumes the other): E1 forbids **5** module names; E3
forbids **15**. Narrowing E1 alone leaves E3 red on `alpaca`, `ibkr`, `tda`, `schwab`,
`robin_stocks`, `fidelity_api`, `playwright`, `pyppeteer`, `webdriver`, `MetaTrader5`; relaxing E3
alone leaves E1 violated for its 5.

FACT (the scan's reach): `iter_source_files()` walks `PKG_ROOT = src/signalforge` only
(`tests/support.py:13-15`, `:39-43`), and `_imported_names` takes the **first dotted segment** of
every `import` / `from … import` (`tests/safety/test_s1_no_broker_surface.py:50-57`). So the
import scan fires on a bare vendor top-level name anywhere under `src/signalforge`.

FACT (the call-string scan is **not** a blocker for the §3 protocol): none of the 9 substrings
matches `place`, `place_combo`, `cancel`, or `cancel_all`. `cancel_order(` requires the literal
`_order(`. Verified against `tests/safety/test_s1_no_broker_surface.py:37-47`.

FACT (doc hygiene found while verifying): `ARCHITECTURE.md:64` names the S1 test as
`tests/safety/test_no_broker_surface.py`; the file on disk is
`tests/safety/test_s1_no_broker_surface.py`. The S2 and S3 rows (`ARCHITECTURE.md:65,66`) are
stale in the same way (`test_import_offline.py` / `test_llm_not_in_decision_path.py` vs
`test_s2_import_offline.py` / `test_s3_llm_not_in_decision_path.py`). Fix these in the §18
amendment commit; they are not load-bearing but a stale pointer in the invariant table is exactly
the kind of drift this ADR is trying not to add to.

### 1.3 Why the boundary is superseded rather than routed around

HYPOTHESIS: a boundary enforced in five places and promised in four user-facing documents cannot
be changed by adding a module and fixing whatever goes red. Amending some documents and not others
leaves them contradicting each other, which is a worse state than either alone: a reader who finds
`DISCLAIMER.md:9` ("No orders are ever placed") while an execution package exists has been misled
by the repository itself. §18 therefore specifies a single commit that amends all of them
together, and §17 specifies the contract changes as a separate, earlier, reviewed commit.

---

## 2. Decision — package layout and default posture

**HYPOTHESIS (approve or amend):**

```
src/signalforge/execution/
  __init__.py          # EXECUTION_DISABLED_BY_DEFAULT = True ; module contract docstring;
                       # no side effects, no network, no credential read at import time
  protocol.py          # BrokerAdapter Protocol + MarketClock/AccountSnapshot/OrderStatus types.
                       # NO vendor import, no httpx import, anywhere in this file.
  intents.py           # OrderIntent, ComboOrderIntent, OrderLeg, OrderResult, Fill,
                       # PositionSnapshot — all frozen dataclasses
  states.py            # OrderState enum + the legal-transition table (§6)
  oms.py               # the single guarded entry point; state machine; submission lock; audit
  limits.py            # pre-trade limits, fail-closed; may_open / may_close (§7)
  arming.py            # ArmedStrategy lifecycle: arm / disarm / expiry / auto-disarm (§12)
  deadman.py           # fail-CLOSED heartbeat — the deliberate inverse of killswitch.py (§9)
  reconcile.py         # broker truth vs local truth; halt on divergence; max-age (§10)
  calendarcheck.py     # adapter.clock() vs data/options_calendar.py; no-submit windows (§11)
  credentials.py       # env + macOS Keychain readers ONLY; never writes; never logs (§16)
  brokers/
    __init__.py
    paper_reference.py # local deterministic simulator — the FIRST adapter, no network
    alpaca_paper.py    # the operator's chosen broker's PAPER endpoint — SECOND (decision 2)
```

**FACT (naming hazard, and it is real):** `ARCHITECTURE.md:207` reserves `data/adapters/alpaca/`
as a **market-data** vendor namespace, and the "Layering" contract
(`pyproject.toml:200-207`) treats `signalforge.data.adapters` as a market-data-only tree. A
brokerage adapter must **not** live under `signalforge.data.adapters`. `signalforge.execution.brokers`
is a distinct package with its own contracts.

**Default posture (HYPOTHESIS, hard):**

1. `EXECUTION_DISABLED_BY_DEFAULT = True` is a module constant asserted by a safety test (§19 T4).
2. A new app setting `execution_enabled` defaults **False** (pattern: `auto_simulate_qualified_signals`,
   read via `settings_store.get_setting` — `src/signalforge/settings_store.py:33`).
3. Even with `execution_enabled = True`, **zero orders** can be submitted while no unexpired
   `armed_strategy` row exists. Two independent gates, neither sufficient alone.
4. Importing `signalforge.execution` performs no network call and reads no credential (§19 T4).
   FACT precedent: `tests/safety/test_s1_no_broker_surface.py:80-100` already imports every
   submodule in a clean interpreter, so an import-time side effect would be caught by an existing
   test shape.

**Process placement (HYPOTHESIS, rewritten in rev 2 — the rev 1 version was unbuildable).** The
execution cycle runs inside the existing scheduler worker process, under the existing single-worker
discipline. FACT: `src/signalforge/worker_lock.py:43` `acquire_worker_lock` and the recorded rule
"one worker per DB". FACT (re-read this pass): guarded jobs are registered via `default_job_specs()`
(`src/signalforge/scheduler.py:541`) and `build_scheduler` wraps **every** spec unconditionally in
`guarded()` (`scheduler.py:837`, inside `build_scheduler` at `:821-842`), as does `run_catch_up`
(`:814-816`). There is no unguarded registration path in the repo today.

**FACT (the defect this corrects, verified line by line, re-read again in this revision):**
`guarded()` (`scheduler.py:145-155`) calls `ensure_not_engaged()` at `:151`, and on
`KillSwitchEngaged` it logs (`:153`), records a `"skipped"` `JobRun` (`:154`), and **`return`s
(`:155`) — the job body never runs.** If `job_execution_cycle` were registered
through `scheduler.guarded` as rev 1 said, then with the kill switch engaged: §8's
drain → `cancel_all()` → reconcile sequence would never run; §7's `may_close` protective close could
never be submitted by the system; §9's dead-man heartbeat (written at the top of every execution
cycle) would stop, so the dead man would lapse as a *side effect of engaging the kill switch*; and
reconciliation would age past `max_reconciliation_age_s`. Drill V1's pass condition would be
unachievable. **The kill switch would, in fact, block closing.**

**HYPOTHESIS (the correction, hard):** `signalforge.execution` defines its own wrapper,
`execution.oms.execution_guarded(name, fn)`. It is **not** `scheduler.guarded`. It:

1. records a `JobRun` row with the same shape and the same `retry_on_lock` discipline, so the
   Operational Status page still sees the job;
2. reads the kill-switch state itself (K1) **and** the execution-local kill state (K2, §8) and
   **branches** rather than returning:
   - **not engaged** → the full cycle (heartbeat, reconcile, calendar, limits, open, close);
   - **engaged, or K2 unreadable** → a **protective-only cycle**: heartbeat → reconcile →
     bounded drain → `cancel_all()` → reconcile again → `may_close` only. No `may_open` path is
     reachable in this branch, by construction, not by a flag.
3. never swallows the branch: the `JobRun` note records which branch ran, and an
   `execution_event` of type `CYCLE_PROTECTIVE` is written whenever the protective branch runs.

**This is a new scheduler registration path and it touches the live worker's job list.** Stated
plainly because it is the one place this ADR changes the behaviour of a process that is running
today. `job_execution_cycle` is registered **only when `execution_enabled` is True** (default
False), so on today's deployment the job list is byte-identical.

**Cycle cadence (HYPOTHESIS, and it was missing entirely from rev 1).** The cycle interval is
`execution_limits.cycle_interval_s`, grid centre **30s**, and it is the number from which
`execution_stale_after_s` (§9) is derived rather than the reverse: the dead man must tolerate at
least two missed cycles, so `execution_stale_after_s >= 3 * cycle_interval_s`. At a 30s cadence the
per-cycle broker call budget is `clock` + `account` + `positions` + `open_orders` + the per-cycle
`is_paper` re-proof ≈ **4–5 REST calls**, i.e. **~3,900–4,900 calls per 6.5-hour session** before
any submission. FACT: **no vendor rate limit was verified in this pass (no network call was made)**.
Q6 is therefore reframed: the cadence and the derived per-session call budget must be checked
against the broker's documented rate limit **before I-E5**, and if the budget does not fit, the
cadence changes and `execution_stale_after_s` changes with it.

**Registering the cycle without creating ANY inbound import edge into `signalforge.execution`
(HYPOTHESIS, hard — corrected again in rev 3; rev 2 satisfied only half of this).** Two constraints
apply at once:

1. `signalforge.scheduler` must **not** import `signalforge.execution`, because `signalforge.app`
   imports `signalforge.scheduler` in four places (FACT, re-read this pass:
   `src/signalforge/app/main.py:50`, `:59`; `src/signalforge/app/views.py:736`, `:931`), and
   import-linter `forbidden` contracts report **indirect** chains unless `allow_indirect_imports`
   is set — which §17.2 deliberately does **not** set. `signalforge.app → signalforge.scheduler →
   signalforge.execution` would violate S15b transitively.
2. **`signalforge.app` must not resolve `signalforge.execution` either — and rev 2's own text
   violated this directly.** Rev 2 said "the two call sites that build the worker (`cli.py:2347`,
   `app/main.py:50`) append the execution spec themselves, resolved from `signalforge.execution` at
   that call site". FACT (re-read this pass): `app/main.py:50` is **inside `signalforge.app`**
   (`from signalforge.scheduler import build_scheduler, run_catch_up`, in the app's startup hook),
   and `signalforge.app` is in S15b's **own source list** — so that sentence specified a direct
   S15b violation while the section around it argued for S15b.

**The rule (HYPOTHESIS, hard).** The execution job spec is injected from **exactly one place:
`signalforge.cli`** (FACT: `src/signalforge/cli.py:2347`
`from signalforge.scheduler import build_scheduler, run_catch_up` — the CLI worker entry point).
The CLI resolves the spec from `signalforge.execution` and passes it to
`build_scheduler(specs=...)`, which already accepts an explicit spec list (`scheduler.py:821`).
`scheduler.py` gains no import; `signalforge/app/**` gains none either. The CLI is the one
sanctioned inbound edge (§17.2 note 2) and it is the **only** one.

**The operator-visible consequence, stated rather than discovered later.** The execution cycle
therefore exists **only in the CLI-launched worker** (`signalforge worker`). If the worker is
started from the app process instead, there is **no execution job at all**: no submissions, and
equally **no heartbeat, no reconciliation, no drain, and no protective cycle** — §8's "worker is
not running" case applies in full, including that engaging the kill switch cancels nothing at the
broker. To stop that from being silent, the app's embedded-scheduler path (`app/main.py:50`)
**refuses to start a scheduler** while the `execution_enabled` setting is True, and says to run the
CLI worker instead. That check reads a **setting name** — a string, via `settings_store.get_setting`
(FACT: `src/signalforge/settings_store.py:33`) — and imports nothing from `signalforge.execution`,
so S15b stays clean and the one-worker-per-DB rule (`worker_lock.py:43`) is unchanged. Drilled as
**V19**. See §17.2 and Q11.

**SQLite discipline (HYPOTHESIS, and it is load-bearing — see §8).** FACT:
`src/signalforge/db/session.py:118-124` `set_write_intent(session, write)` exists precisely so a
job can "stop holding the write lock … and `set_write_intent(session, True)` again before it
writes". The OMS **never holds a transaction across a network call**: the `SUBMITTING` record is
written and **committed**, write intent released, then `place()` is called, then a fresh
write-intent session records the outcome. Any design that wraps `place()` in an open transaction
is rejected (it would hold the SQLite write lock for the duration of a broker round trip, on the
same file the live probation worker uses).

---

## 3. BrokerAdapter protocol

**HYPOTHESIS (map §6.2, adopted verbatim in shape, with the types named):**

```python
class BrokerAdapter(Protocol):
    name: str

    def is_paper(self) -> IsPaperProof: ...          # §13 — a PROOF object, not a bool
    def account(self) -> AccountSnapshot: ...
    def positions(self) -> Sequence[PositionSnapshot]: ...
    def open_orders(self) -> Sequence[OrderStatus]: ...
    def order_status(self, client_order_id: str) -> OrderStatus | None: ...   # §5, §8
    def place(self, intent: OrderIntent) -> OrderResult: ...        # idempotent on client_order_id
    def place_combo(self, intent: ComboOrderIntent) -> OrderResult: ...   # ATOMIC multi-leg
    def cancel(self, client_order_id: str) -> OrderResult: ...
    def cancel_all(self) -> Sequence[OrderResult]: ...              # used by the kill switch
    def clock(self) -> MarketClock: ...
```

**Change from the map (HYPOTHESIS, and it is required by §8's post-timeout procedure):**
`is_paper()` returns an `IsPaperProof` value object rather than `bool` (§13), and a
`order_status(client_order_id)` method is **added**. The map's §6.3 post-timeout rule says "query
`open_orders()` and fills for that `client_order_id` BEFORE any resubmission" — but a filled or
rejected order is by definition **not** in `open_orders()`, so `open_orders()` alone cannot
distinguish "the broker never saw it" from "the broker filled it and it is no longer open". Without
a by-id lookup the post-timeout rule is not implementable and the double-fill hazard it exists to
prevent stays open. `order_status()` is that lookup.

**Adapter eligibility — four hard conditions. An adapter failing any one is ineligible, full stop:**

| # | Condition | Why hard |
|---|---|---|
| A1 | `place`/`place_combo` are **idempotent on `client_order_id`** | a retry after a timeout must never double-fill (§5) |
| A2 | a multi-leg structure submits as **one atomic native combo order** | leg-by-leg partial fill manufactures a naked short option (§14) |
| A3 | `is_paper()` is **provable from the broker's own response body** | a misconfigured base URL is the single most likely way real money gets touched (§13) |
| A4 | `order_status(client_order_id)` resolves a **terminal** order, not only an open one | otherwise §8's post-timeout non-duplication cannot be implemented |

**Further protocol constraints (HYPOTHESIS):** every method is synchronous and bounded by an
explicit timeout; no vendor type crosses this boundary (adapters translate to the `intents.py`
dataclasses); no method accepts free text, a natural-language field, or any value produced by
`signalforge.llm`; `protocol.py` imports no HTTP client and no vendor package (asserted by §19 T5).

**Decision D6-A (HYPOTHESIS, and it makes the §17 relaxation *zero*): no vendor SDK is imported.**
The vendor paper adapter speaks the broker's documented REST API over `httpx`, the client already
used by `signalforge.data.adapters.massive`. Rationale, in order of weight:

1. A1 (idempotency) and the §8 submission lock must be **ours**. An SDK brings its own retry,
   ordering, and async semantics that we would have to audit and could not pin.
2. FACT: `httpx` is not in `BANNED_IMPORTS` (`test_s1_no_broker_surface.py:18-34`), is not in
   S1's forbidden list (`pyproject.toml:198`), and is not in Ruff's banned-api list
   (`pyproject.toml:104-110`). So **no denylist entry needs to be removed or carved out** for the
   adapter to exist. The relaxation of E1/E2/E3 is not "narrow" — it is **nil**.
3. FACT: the `alpaca-py` SDK's top-level module is `alpaca`, which is in E3's 15 but **not** in
   E1's 5 or E2's 5. Adding it to E1/E2 in order to then carve it out again would enlarge the
   denylist and immediately punch a hole in it — strictly worse than not importing it.

**The honest consequence of D6-A, stated rather than buried (HYPOTHESIS).** With no vendor name
imported, the three name-based denylists no longer *mechanically* catch a brokerage surface built
on `httpx`. The denylists must not become decorative. §17 therefore adds a **positive** boundary
that is stronger than the one it replaces: an outbound-host allowlist test (§19 T5) asserting that
no module outside `src/signalforge/execution/brokers/` contains a brokerage host literal, plus
S15a/S15b/S14 constraining the import graph in both directions. The denylists stay **exactly as
they are, with nothing removed**, as a second line of defence against a future SDK import.

### 3.1 The `paper_reference` fill rule — specified, and fenced off from every gate

`brokers/paper_reference.py` is the **first** adapter, is the **sole substrate for all of §21's
drills**, and in rev 1 had **no specified fill rule at all**. That is a real hole in two directions:
a simulator that consults any bar at or after the submission timestamp to decide a fill is
**lookahead**, and every drill would still pass; and a deterministic local simulator whose fills the
implementer controls is a path to a **manufactured arming precondition** (decision 10's "≥20 closed
paper trades with non-negative expectancy").

**HYPOTHESIS (hard, all four):**

1. **Information set.** A `paper_reference` fill may be decided **only from information strictly at
   or before the intent's submission timestamp**. No bar, quote, or aggregate stamped at or after
   the submission timestamp may be read. There is no "fill at the next bar's better price".
2. **Fill price is never better than the modelled spread.** A limit order fills at
   `limit ± modelled half-spread`, using **the same spread constant the backtest uses** — FACT
   (re-read this pass): `_NOMINAL_SPREAD_BPS = 5.0`, `src/signalforge/paper/ledger.py:50`, applied
   at `:166` as `abs(entry_ref) * shares * (bps / 10_000) / 2`. Decision 5 makes modelled spreads a
   permanent disclosed assumption and gate 4b permanent, so the simulator must not quietly be
   kinder than the model the evidence rests on (map §2.4, §5.2 gate 4b).
3. **Determinism.** Given the same intent and the same pre-submission information set, the fill is
   identical across runs. A drill that passes by luck is not a drill.
4. **Its output is never evidence.** `paper_reference` fills, P&L, and any statistic derived from
   them are **drill artifacts**, excluded from decision 10's ≥20-closed-trade count, from
   `strategy_health`, from expectancy, and from **every** promotion gate. They are tagged as such in
   `execution_event` (`adapter_name = 'paper_reference'`) and the decision-10 counter filters on it.
   Asserted by **T10** (§19).

---

## 4. Intents and results — the frozen data model

**HYPOTHESIS:**

```
OrderLeg (frozen)
  option_ticker | symbol      # exactly one; option_ticker is the OCC ticker
  side                        # BUY_TO_OPEN | SELL_TO_OPEN | BUY_TO_CLOSE | SELL_TO_CLOSE
  ratio: int                  # signed leg ratio within the combo
  shares_per_contract: int    # READ from OptionContract; asserted == 100 at intent time

OrderIntent (frozen)
  client_order_id             # deterministic hash — see §5. NO attempt counter.
  source_paper_trade_id
  strategy_version_id ; armed_strategy_id
  symbol | option_ticker ; side ; qty
  order_type                  # LIMIT only in Phase 1
  limit_price
  time_in_force               # DAY only in Phase 1
  max_notional                # see "notional, defined" below — never an undefined word
  modelled_fill_price         # §4.2 — what the cost model said this would fill at
  modelled_spread_bps         # §4.2 — the spread constant the model used, carried forward
  created_at ; expires_at     # §5 — same session, plus a max age in minutes
  config_hash ; spec_json_hash
  execution_limits_id         # the limits row in force when this intent was built (Q8)
  intent_kind                 # OPEN | PROTECTIVE_CLOSE    (§7)
  state                       # OrderState, §6

ComboOrderIntent (frozen)
  … all of the above, minus (symbol|option_ticker, side, qty) …
  legs: tuple[OrderLeg, ...]  # >= 2 ; ONE client_order_id for the whole combo
  net_limit_price             # signed: credit > 0
  structure_type              # the version's single approved structure type (map §5.2 gate 0.5)

OrderResult (frozen)   broker_order_id, state, submitted_at, raw_status_verbatim, error_verbatim
Fill (frozen)          client_order_id, leg_index, qty, price, fee, filled_at, broker_fill_id
PositionSnapshot / AccountSnapshot / OrderStatus / MarketClock — vendor-neutral, adapter-translated
```

`raw_status_verbatim` and `error_verbatim` exist because §20 requires broker rejections to be
surfaced **verbatim and never retried** (map §6.7b). A paraphrased rejection is an unreviewable
one.

### 4.1 "Notional", defined — because an undefined word in a limit is not a limit

**HYPOTHESIS (rev 2; rev 1 used the bare word and that was a real defect).** For a single-instrument
`OrderIntent`, `notional = abs(qty * limit_price * shares_per_contract)` (with
`shares_per_contract = 1` for equities). For a `ComboOrderIntent` the word is ambiguous across two
orders of magnitude and must be fixed per `structure_type`:

| `structure_type` | `notional` is | Not this |
|---|---|---|
| `short_vertical` (decision 12) | **maximum loss** = `(strike_width - net_credit_per_contract) * shares_per_contract * contracts` | not the net credit (trivially passes every cap), and not the gross strike value of the short leg (one SPY put ≈ $60k+, which blocks every spread the strategy can produce) |
| `cash_secured_put` (O1, deferred) | **full collateral** = `strike * shares_per_contract * contracts` | not the premium |
| `covered_call` (O2, deferred behind O3 — decision 8) | **underlying market value** of the covered shares | not the premium |
| any equity intent | `abs(qty * limit_price)` | — |

**A `structure_type` with no row in this table cannot produce an intent.** That is the fail-closed
form: a new structure requires an explicit notional definition here *before* it can be built, not a
default.

**Worked arithmetic for one concrete O3 structure**, because a limit nobody has multiplied out is a
limit nobody has checked. Take decision 13's **$25,000** SIMULATED options paper account, a 5-wide
SPY put credit spread, 1 contract, net credit $1.50:

- max loss per structure = `(5.00 - 1.50) * 100 * 1` = **$350**
- `notional` (the row above) = **$350**
- L2 per-order notional cap (decision 4: **$1,000**) → passes; (map §3.2 as a percent: 0.5% of
  $25,000 = **$125**) → **fails**
- per-structure max loss (decision 4: **$250**) → **fails**; (map §3.2: 0.5% = **$125**) → fails
- aggregate open max loss (decision 4: **$1,000** → 2 such structures; map §3.2: 2% = **$500** → 1)
- collateral for a defined-risk spread is margined at max loss (§20.1), so the collateral cap
  (decision 4: **$5,000**) binds at ~14 structures while the aggregate max-loss cap binds at 2–4.
  **The collateral cap can therefore never fire for this structure.** A limit that cannot fire is
  not protection; it is recorded here as such rather than left to look like one.

**FACT (a divergence rev 1 imported silently and did not name):** map §3.2 states the same three
limits as **percent of equity** — `options_per_structure_max_loss_pct` 0.5%, `options_total_open_max_loss_pct`
2%, `options_collateral_pct_of_equity_max` 30% — under the heading "every number below is an
**evaluation grid centre, not a recommendation**", while decision 4 states them as **dollars**
($250 / $1,000 / $5,000). On a $25,000 account the percentages are **$125 / $500 / $7,500** — all
three different from decision 4. **They are not the same limits and one of the two must win.**

**HYPOTHESIS (the resolution, and it is the conservative one):** `execution_limits` stores **both**
— an absolute-dollar column and a percent-of-live-equity column for each of the three — and the
binding limit is **`min(dollars, pct * live equity from `adapter.account()`)`**, recomputed each
cycle. Neither source is discarded, neither is silently widened, and the stricter of the operator's
two recorded intents is the one that binds. Every `execution_limits` numeric column carries its
unit in its name (`_usd` / `_pct` / `_s` / `_minutes`). Q3 is extended to ask the operator to
confirm both sets, not one.

### 4.2 The cost-model feedback record (new in rev 2)

**FACT:** decision 5 (`DECISIONS_2026-09-12_options_execution.md:15`) makes modelled spreads "a
disclosed assumption on both asset classes" and makes gate 4b (dual-spread) **permanent**. FACT
(re-read this pass): the equity paper ledger's spread constant is
`_NOMINAL_SPREAD_BPS = 5.0` (`src/signalforge/paper/ledger.py:50`), used at `:163`, `:166`, and
recorded into the trade snapshot at `:185`.

**The execution layer is the first place in this program's history where a *realized* spread is
observable.** Rev 1 threw that away: `Fill` carried only `price`/`fee` and `OrderIntent` only
`limit_price`, so realized-vs-modelled slippage was not computable from the audit trail at all.

**HYPOTHESIS (hard):**

1. `OrderIntent` / `ComboOrderIntent` carry `modelled_fill_price` and `modelled_spread_bps` (§4),
   written at intent time from the same cost model the backtest uses.
2. Every `execution_event` of type `FILL` records `realized_fill_price`, `modelled_fill_price`,
   `modelled_spread_bps`, and the derived `realized_minus_modelled_bps`, per leg for a combo.
3. **R3 rule, stated explicitly because the optimistic move is the obvious one:** revising
   `_NOMINAL_SPREAD_BPS`, the options spread model, or any other cost-model constant **on the
   evidence of live fills is a version bump requiring a fresh sealed look** — never an in-place
   retune of an existing sealed record. Live fills looking tighter than modelled is precisely the
   observation that would retroactively improve every backtest, and R1/R3 exist to stop that. Map
   §5.2 gate 4b already fixes this form for the dual-spread 2x re-run; this ADR states it for the
   execution layer.
4. The realized-vs-modelled series is **disclosed, never used to justify a looser cost model**
   inside the same version. It is evidence *about* the assumption, not permission to change it.

---

## 5. Where an OrderIntent may come from — the seven preconditions

### 5.1 The hole this closes (FACT, verified line by line for this ADR)

An ACCEPTED `PaperTrade` is **not** by itself evidence that anything was gated:

- FACT: `accept_candidate` (`src/signalforge/paper/ledger.py:129-160`) checks **only**
  `ensure_not_engaged()` (`:139`), `cand.direction is not Direction.AVOID` (`:143-144`), and
  `per_share_risk > 0` (`:153-154`). It checks **no** `quality_gate_status`, **no**
  `StrategyVersion.status`, **no** approved scope, and **no** `instrument_type`.
- FACT: every one of those checks lives instead in `assert_auto_simulate_allowed`
  (`ledger.py:474-515`): the setting at `:492-493`, `QualityGate.PASSED` at `:494-495`,
  `instrument_type not in ("stock", "etf")` at `:496-500`, `StrategyStatus.PAPER_APPROVED` at
  `:501-503`, and the five-part `scan_scope_matches` at `:504-512`. That function is on the
  **automatic** path only, and `accept_candidate` never calls it.
- FACT (re-read this pass; rev 1 carried the map's wrong numbers): `accept_candidate` is reachable
  directly from the CLI with no guard and no flag — `src/signalforge/cli.py:1261`
  `paper_accept(candidate_id)` → `:1267` `accept_candidate(session, candidate_id)`. (The map's
  `cli.py:1158-1165`, at map `:53`, `:1378`, `:1947`, points at an unrelated regime/backtest
  command and should be corrected there too.)
- FACT: it **invents a position size** when the candidate carries none —
  `ledger.py:156-159`: `shares = round((cand.risk_dollars or 0.0) / per_share_risk) if
  cand.risk_dollars else 0`, then `if shares < 1: shares = max(1, int((float(acct.cash) * 0.005)
  // per_share_risk))`. Nothing downstream can distinguish that 0.5%-of-cash fallback from a
  risk-sized position.

**Consequence:** a gate-FAILED candidate, manually accepted by one CLI command, belonging to a
PAPER_APPROVED and armed strategy, would produce an ACCEPTED `PaperTrade` satisfying a naive
"ACCEPTED PaperTrade of an armed strategy" rule — and would be submitted as a live order at a size
the system made up.

### 5.2 The OPEN rule (HYPOTHESIS, fail-closed)

`OrderIntent` with `intent_kind = OPEN` has **one factory**,
`execution.intents.build_open_intent(...)`. It re-verifies **all seven** preconditions against the
DB *at intent time* and raises `IntentRefused(reason)` otherwise. It does not trust that an
ACCEPTED `PaperTrade` implies any of them.

| # | Precondition | Evaluated against |
|---|---|---|
| P1 | source candidate's `quality_gate_status is QualityGate.PASSED` | `Candidate`, re-read now |
| P2 | `StrategyVersion.status is StrategyStatus.PAPER_APPROVED` | re-read now (FACT: the enum has exactly EXPERIMENTAL / PAPER_APPROVED / DISABLED, `src/signalforge/domain.py:27-30` — there is no ARMED value and this ADR adds none) |
| P3 | an `armed_strategy` row exists, is unexpired, names **this** version and **this** adapter | §12 |
| P4 | full approved-scope match **re-verified now** — `scan_scope_matches(...)` (`src/signalforge/research/approval_scope.py:83-120`) over `dataset_snapshot_id`, `config_hash`, `spec_json_hash`, `source`, and the exact `universe` set; never inherited from the scan record | FACT: the function returns False on a `None` snapshot id, an empty source, or an empty universe (`approval_scope.py:109-110`) — it is already fail-closed in the right direction |
| P5 | `risk_dollars` was **present on the source candidate**. A `PaperTrade` sized by the `ledger.py:156-159` fallback is never an order source | `Candidate.risk_dollars is not None and > 0` |
| P6 | the source `PaperTrade` was created by the **automatic actor** | §5.3 |
| P7 | every §7 `may_open` limit and every map-§3.2 risk limit evaluates cleanly **now** | §7 |

**Any check that cannot be *evaluated* counts as a failure** — **for an OPEN intent.** A missing
row, an unreadable file, an exception, a `None` — all refuse. This is the
`assert_auto_simulate_allowed` shape (`ledger.py:474-515`), which raises naming the first failed
condition, and it is the house pattern this ADR deliberately copies rather than inventing a new one.
**The close path inverts this direction — see §5.2b.**

### 5.2b The CLOSE rule — a separate factory, with the fail direction inverted (new in rev 2)

**The defect this corrects.** Rev 1 routed every intent through one factory requiring all seven
preconditions. P3 requires a live, unexpired `armed_strategy` row. But §7 says `may_close` is
permitted while the strategy is **disarmed** or its arming has **expired** — exactly the states §9
and §12 step 7 auto-disarm put the system into. Under rev 1 as written, **no PROTECTIVE_CLOSE
intent could be constructed once the strategy was disarmed**, so the kill switch would block
closing: the one outcome §0 and §7 promise it never does. P1/P4/P5/P6 (candidate gate status,
approved scope, `risk_dollars`, auto-sim actor) are additionally *meaningless* for a flatten — a
close is not a new opinion about a candidate, it is the removal of an exposure that already exists.

**HYPOTHESIS (hard).** `execution.intents.build_close_intent(...)` is a **separate factory**. It
requires **none** of P1–P7. It requires exactly five things, all of them derived from the broker's
own state rather than from research state:

| # | Close precondition | Evaluated against |
|---|---|---|
| C-P1 | the position **exists at the broker** and is **RECONCILED** | `adapter.positions()` this cycle, not local state alone (§10) |
| C-P2 | the position traces to an **originating `execution_event`** with a `client_order_id` this OMS wrote | `execution_event`, `INDEX(client_order_id)` (§16) |
| C-P3 | **every leg is non-increasing** — asserted per leg, not per net position | the intent's legs vs the reconciled position's legs (§7) |
| C-P4 | `intent_kind is PROTECTIVE_CLOSE` and the intent writes its own `execution_event` record type | §7, §15 |
| C-P5 | the adapter is **reachable** and reconciliation is **not DIVERGED** | §10 — closing into an unknown book is not protective |

**No `armed_strategy` row is required. No `Candidate` is required. No `PaperTrade` is required.**
A position that exists at the broker is a fact about the world; the research state that produced it
may be gone, superseded, or disarmed, and none of that changes the operator's need to flatten it.

**The fail direction is inverted, and this is the single most important sentence in §5.** For an
OPEN intent, *a check that cannot be evaluated is a failure*. For a CLOSE intent, **a check that
cannot be evaluated blocks nothing except C-P1, C-P2, C-P3 and C-P5 themselves** — which are the
only four checks the close path has, and each of which is a *positive* proof about the broker's own
book rather than a research-state lookup that could be missing. Concretely: an unreadable kill-switch
file, an unreadable execution-local kill state, a lapsed dead man, a missing `armed_strategy` row,
a drifted `config_hash`, a failed scope match, an expired arming, and an outstanding `UNKNOWN` on
some *other* intent all **block opening and none of them block closing**.

**The close path still cannot do the dangerous thing.** C-P3 is asserted **per leg**: a net-reducing
intent that increases any single leg is refused (so a "close" cannot be used to roll into a new
short leg), and C-P2 means the OMS will not flatten a position it never opened — that is a §10
divergence and a halt, not a close. Drilled as V15 and V16.

### 5.3 P6 needs a schema change, and here is why a JSON field is not enough

FACT: the actor **is** recorded today, but only inside a JSON blob —
`ledger.py:229` writes `signal_snapshot_json["decision"] = {"actor": actor, "note": note,
"automatic": actor == "auto_simulate"}` (identically at `ledger.py:117` for `record_decision`), and
`src/signalforge/paper/auto_simulate.py:54` defines `AUTO_SIM_ACTOR = "auto_simulate"`, passed at
`auto_simulate.py:191`. FACT: `accept_candidate`'s default is `actor: str = "local-user"`
(`ledger.py:136`).

FACT: `PaperTrade` has **no `actor` column** — its columns are `account_id`, `candidate_id`,
`position_id`, `decision`, `signal_snapshot_json`, `plan_json`, `why_qualified`, `why_might_fail`,
`created_at` (`src/signalforge/db/models/paper.py:100-117`).

**HYPOTHESIS: add a first-class, indexed `PaperTrade.actor` column in I-E2 and key P6 on that
column**, not on the JSON. An order-authorisation predicate must not depend on the shape of a
free-form JSON blob that a future writer could change without breaking anything visible. FACT
precedent for the exact column shape: `TradeCorrection.actor: Mapped[str] = mapped_column(String(60),
default="local-user")` (`db/models/paper.py:130`) — same type, same default, same table file.

**Migration (HYPOTHESIS).** Additive column, `String(60)`, default `'local-user'`, indexed.
Backfill rule: `coalesce(json_extract(signal_snapshot_json, '$.decision.actor'), 'local-user')`.
FACT (read-only query, this session): `select count(*) from paper_trade` → **0**, so the backfill
is empty today; the rule is specified anyway so that it is correct whenever it runs. FACT
(memory): Alembic revision ids are auto-excluded from the secret-scan baseline, so a new migration
needs no baseline change — and the baseline must not be rewritten casually.

**P6 for the EQUITY stream** is strictly stronger than the map's phrasing: the predicate is
`paper_trade.actor == auto_simulate.AUTO_SIM_ACTOR`, and — because the automatic path is the only
one that runs `assert_auto_simulate_allowed` — it transitively carries P1, P2, P4 and the
instrument-type check. P1/P2/P4 are still re-evaluated independently at intent time, because a
status or scope can change between acceptance and submission (FACT precedent: the 2026-09-11
config-hash incident, where a `ResearchConfig` change silently moved the hash used in the
five-part scope match; recorded in `docs/PAPER_PROBATION_ACTIVATION.md`, fixed by commit `0cc4cf4`).

### 5.3b P6 for the OPTIONS stream — and why rev 1 could not authorise the program's first structure

**The defect this corrects, stated plainly.** The transitive instrument-type check P6 inherits is
**stock/ETF only**. FACT (re-read this pass): `assert_auto_simulate_allowed`
(`src/signalforge/paper/ledger.py:474-515`) refuses anything whose `instrument_type` is not
`'stock'`/`'etf'` at `ledger.py:496-500`. FACT: decision 12
(`DECISIONS_2026-09-12_options_execution.md:22`) makes an **O3 short vertical (credit) spread** the
**first** options structure. So under rev 1 as written, **the first options structure could never
produce an `OrderIntent` at all**, while every §4.1/§11/§13/§14 combo-and-approval-level apparatus
in this ADR exists for exactly that structure. That is not a conservative failure; it is an
incoherence, and the cheap way out of it — relaxing P6 to "any actor" — would silently delete the
strongest precondition in §5.

**FACT (map §3.6, `docs/research/OPTIONS_EXECUTION_PROGRAM_MAP.md:839-877`, binding):**
`assert_auto_simulate_allowed` must be left "**UNCHANGED. Still stock/etf only. Never widened**",
with a **separate** `assert_options_auto_simulate_allowed`, a **separate** setting
(`options_auto_simulate_enabled`, default FALSE), a **new** `instrument_type == 'option_structure'`,
a separate daily cap, and (map `:895`) a separate `paper/options_ledger.py`.

**HYPOTHESIS (the resolution, and it widens nothing):**

1. An options `ComboOrderIntent` sources from the **options** ledger row, not `paper_trade`. Its P6
   predicate is `options_paper_trade.actor == AUTO_SIM_OPTIONS_ACTOR` — a **new, distinct** actor
   constant on the options ledger, not `auto_simulate.AUTO_SIM_ACTOR` and not `paper_trade.actor`.
2. The new indexed `actor` column of §5.3 is added to **both** tables — `paper_trade` (equity) and
   the options trade table — in the same I-E2 migration, with the same `String(60)`, default
   `'local-user'`, same backfill rule.
3. For an options intent, P6's transitive carry is
   `assert_options_auto_simulate_allowed`, which carries `instrument_type == 'option_structure'`,
   the structure-type match (map §5.2 gate 0.5), the **sixth** options scope part (map §3.5), the
   per-leg `shares_per_contract == 100` assertion (§14), and the §3.1 collateral check. It carries
   **more** than the equity path, not less.
4. **I-E2 is BLOCKED on map §3.6 landing first** — specifically on
   `assert_options_auto_simulate_allowed`, the `option_structure` instrument type, and
   `paper/options_ledger.py` existing. This ADR does not authorise building any of the three, and
   does not authorise reaching the options path by any other route.

**Explicitly refused resolutions, recorded so they cannot be reached for later:** relaxing P6 to
"any actor"; adding `'option'` or `'option_structure'` to `assert_auto_simulate_allowed`'s tuple
(map §3.6 quotes the reader-pass finding that this "would silently let options trades flow through
equity-shaped sizing, cash, and mark-to-market logic that is provably wrong for options"); or
keying options P6 on `paper_trade.actor`. Each is a gate weakening in disguise and each is
prohibited by this ADR.

### 5.4 Idempotency and expiry

**`client_order_id` = a deterministic hash of `(source_paper_trade_id, structure_leg_signature)`
— and `attempt` is NOT in the key.** HYPOTHESIS, and this corrects a real defect: an attempt
counter in the key means a retry produces a *different* id, which defeats A1 exactly when it
matters (a post-timeout retry) and converts an ambiguous response into a double-fill. Attempts are
counted in `execution_event` rows, never in the key. For a combo, there is **one**
`client_order_id` for the whole structure (§14), and `structure_leg_signature` is the ordered tuple
of `(option_ticker, side, ratio)` so that two different structures on the same paper trade cannot
collide.

**`expires_at` is hard.** An intent built from yesterday's paper trade and submitted after a gap is
a stale order at a stale limit price. `expires_at = min(end of the current session, created_at +
max_intent_age_minutes)`, the latter operator-set in `execution_limits`. Submission past
`expires_at` is **refused**, not warned.

---

## 6. OMS state machine

**HYPOTHESIS — the complete state set and the only legal transitions:**

```
CREATED ──validate()──▶ VALIDATED ──submit()──▶ SUBMITTING ──▶ FILLED
   │                        │                        │        ├▶ PARTIAL
   │                        │                        │        ├▶ REJECTED
   ├──▶ REFUSED             ├──▶ EXPIRED             │        ├▶ CANCELLED
   (precondition failed,    (expires_at passed       │        ├▶ EXPIRED
    §5; terminal)            before submission)      │        └▶ UNKNOWN
                                                     │
                     (no terminal outcome recorded) ─┘
```

- `CREATED` — the factory produced an intent; nothing verified yet.
- `VALIDATED` — all seven §5 preconditions and all §7 `may_open`/`may_close` checks passed **in
  this cycle**. Validation is not cacheable across cycles.
- `SUBMITTING` — written and **committed** to `execution_event` *before* the network call, with
  the `client_order_id` (§8). The in-flight set is durable, not in memory.
- `FILLED` / `PARTIAL` / `REJECTED` / `CANCELLED` / `EXPIRED` — terminal, recorded from the
  broker's own response or from reconciliation.
- `REFUSED` — terminal; the intent never reached the adapter.
- **`UNKNOWN` — terminal-until-reconciled, and it blocks.** It is the state a timeout, an
  ambiguous response, or a `SUBMITTING` record with no recorded outcome lands in.

**`UNKNOWN` semantics (HYPOTHESIS, hard):**

1. An outstanding `UNKNOWN` for a strategy **blocks every further `may_open`** for that strategy
   (§7) and **blocks arming** that strategy (§12 auto-disarm trigger).
2. An `UNKNOWN` is **never** cleared by a retry. It is cleared only by (a) reconciliation
   resolving the `client_order_id` to a terminal broker state via `order_status()`, **and** (b) an
   explicit operator acknowledgement recorded in `execution_event`.
3. A `SUBMITTING` record found with no terminal outcome at the start of any cycle — including the
   first cycle after a process restart — is promoted to `UNKNOWN` automatically. It is **never**
   assumed to have failed.
4. `PARTIAL` on a combo (proportional across all legs) is a legitimate terminal outcome and is
   reconciled like any other. A partial **by leg** is not a state — it is a halt (§14).
5. **The `UNKNOWN` path must have an exit that requires no manual DB write (new in rev 2 — rev 1
   deadlocked).** The rev 1 sequence was: crash mid-submit → restart → `UNKNOWN` (rule 3) →
   auto-disarm (§12 step 7) → and then, under rev 1's single factory, **no close intent was
   constructible** (§5.2b) while clearing the `UNKNOWN` required a reconciliation whose `is_paper`
   proof read `expected_account_id` from `armed_strategy.broker_account_id_expected` — a row that
   now has `disarmed_at` set. The system could enter a state it could not leave without editing the
   DB by hand, which §16's append-only discipline forbids. **Two rules close it:**
   - **(a)** reconciliation and the `is_paper` proof read the **most recent `armed_strategy` row
     for that adapter, including disarmed and expired rows**. The row is the durable record of
     *which account this adapter was pointed at*; disarming ends the authority to open, not the
     record of the account. If **no** row has ever existed for that adapter, the expected account
     id comes from the adapter's own reviewed configuration and, failing that, reconciliation
     **halts and alerts** rather than proceeding against an unproven account.
   - **(b)** `build_close_intent` (§5.2b) requires no armed row at all, so the flatten is available
     throughout. Drilled end to end as **V15**: crash mid-submit, restart, clear the `UNKNOWN`,
     close the position, **with no manual DB write at any step**.

---

## 7. Limits — the `may_open` / `may_close` split

**FACT: the existing code already documents the correct asymmetry, verbatim.**
`src/signalforge/paper/ledger.py:272-275`, in `mark_to_market`'s docstring:

> "Closing an existing position is allowed while the kill switch is engaged (it is protective);
> only *opening* new positions is blocked."

A single "engaged ⇒ block everything, `cancel_all()`, disarm" rule would cancel the resting closing
order on an open short option leg and block every subsequent one, leaving the riskiest position in
the book unmanaged. That is the opposite of protective. The split below is not a convenience; it is
the correction.

```
may_open(intent) — ALL must pass, fail-closed; EVERY failure is written to execution_event:

  K1  killswitch.ensure_not_engaged() does not raise
  K2  the execution-local kill state is READABLE and not engaged      (unreadable ⇒ BLOCK)
  D1  dead man alive (§9)
  C1  market open per adapter.clock() AND agreeing with data/options_calendar.py (§11)
  C2  outside the post-open and pre-close no-submit windows (§11)
  C3  the session is not an early-close session, unless §11's explicit handling applies
  A1  strategy armed, unexpired, adapter name matches, approval level permits the structure
  A2  is_paper() proven THIS cycle against armed_strategy.broker_account_id_expected (§13)
  I1  intent not past expires_at (§5.4)
  I2  no UNKNOWN intent outstanding for this strategy (§6)
  L1  daily order count under execution_limits.max_orders_per_day
  L2  per-order notional under cap ; account exposure under cap
  L3  rolling-5-business-day round-trip counter under the operator-set threshold (§20)
  R1  reconciliation CLEAN and fresher than max_reconciliation_age_s (§10)
  R2  every options risk limit of map §3.2, including net-delta and net-vega
  P   all seven §5 preconditions re-evaluated in THIS cycle

may_close(intent) — a SEPARATE, NARROWLY-SCOPED path, built by a SEPARATE FACTORY (§5.2b):

  C-P1 the intent is flattening an EXISTING, RECONCILED position, verified against
       adapter.positions() — not against local state alone
  C-P2 the position traces to an originating execution_event this OMS wrote
  C-P3 it is a closing order only: it cannot increase exposure in ANY leg (asserted per leg,
       not per net position — a "reducing" net that increases one leg is refused)
  C-P4 its intent_kind is PROTECTIVE_CLOSE and it writes its own execution_event record type
  C-P5 the adapter is reachable and reconciliation is not DIVERGED

  PERMITTED while: kill switch engaged ; execution-local kill state unreadable ;
                   dead man lapsed ; strategy disarmed ; expired arming ;
                   config_hash / spec_json_hash drifted ; approved scope no longer matches ;
                   an UNKNOWN is outstanding on some OTHER intent ;
                   no armed_strategy row exists at all
  BLOCKED while:   reconciliation is DIVERGED (closing into an unknown book is not protective)
                   or the adapter is unreachable

  NOT REQUIRED:    P1-P7. No Candidate, no PaperTrade, no armed_strategy row, no scope match,
                   no risk_dollars, no actor check. A close is the removal of an exposure that
                   already exists, not a new opinion about a candidate.
```

**Fail direction, stated once and relied on everywhere (§5.2b).** A check that cannot be
**evaluated** blocks **opening** and **never blocks closing**. Rev 1 had one factory requiring all
seven opening preconditions for both lanes, which made every `may_close` row above unreachable in
exactly the states it was written for. **`may_open` and `may_close` do not share a factory, do not
share a precondition set, and do not share a fail direction.**

**Numbers (FACT: taken from `docs/research/DECISIONS_2026-09-12_options_execution.md:14`,
decision 4; every one is an operator default the operator may change before arming):**
per-structure max loss **$250**; aggregate open max loss **$1,000**; collateral cap **$5,000**; net
delta **±$10,000** notional; net vega cap **$50/vol-pt**; per-order notional **$1,000**; daily
order cap **10**; account exposure cap **40%**; arming expiry **7 days**; PDT threshold
acknowledged at **$25,000** equity.

**"Notional" in L2 and `max_notional` means what §4.1 defines it to mean, per `structure_type`,
and a structure type with no definition there cannot produce an intent.** Rev 1 used the bare word
and, for decision 12's short vertical, the candidate readings spanned two orders of magnitude
(net credit ≈ $50–150, max loss $250, gross short-leg strike value $60k+) — so the cap was either
inert or a total ban depending on who implemented it. §4.1 also shows the worked arithmetic for one
concrete O3 structure through L2, R2, per-structure and aggregate max loss and the collateral cap,
and records that **the collateral cap can never bind for a defined-risk spread** at these numbers.

**The three limits above are stated in dollars by decision 4 and as percent-of-equity by map §3.2
(0.5% / 2% / 30%), and on decision 13's $25,000 account those are different numbers ($125 / $500 /
$7,500).** §4.1 resolves it: `execution_limits` stores **both**, every column carries its unit in
its name, and the binding limit is **`min(dollars, pct × live equity)`** recomputed each cycle. The
stricter of the operator's two recorded intents wins; neither is discarded.

**A reconciliation the operator should see before arming (FACT + HYPOTHESIS).** FACT (read-only
query, this session): `select id,name,initial_cash,cash from paper_account` → one row,
`1 | default | 30000 | 30000`. FACT: decision 13 sizes a **separate** options paper account at
**$25,000 SIMULATED**. FACT: decision 4 acknowledges the PDT threshold at **$25,000 equity**.
HYPOTHESIS: an account sized *exactly at* the PDT minimum falls below it after any loss, so the
round-trip counter (L3) and the PDT threshold interact from day one rather than after a drawdown.
This is not advice about account type or size; it is a note that the two numbers in decision 4 and
decision 13 meet exactly, and the OMS should therefore treat the PDT threshold as a **live,
recomputed** figure read from `adapter.account()` each cycle rather than a constant. Recorded as
open question Q5.

**All limits live in one versioned `execution_limits` row (§16), are read fresh each cycle, and a
missing or unparseable row blocks.**

### 7b. The execution-timing parameters are outcome-tunable, and rev 1 did not say so

**The hazard, named (R1/R4, `docs/research/STRATEGY_COMPLETION_MAP.md` §1).** Seven parameters this
ADR *invents* — `no_submit_after_open_minutes`, `no_submit_before_close_minutes`,
`max_intent_age_minutes`, `execution_stale_after_s`, `max_reconciliation_age_s`, the §8 drain
timeout, and the §10 buying-power tolerance — are described in rev 1 only as "operator-set" and
stored in a row that is mutable by supersession and read fresh each cycle. **Several of them
materially change realized fills**, and realized fills change the live expectancy that §12 step 2 /
decision 10 uses as the **arming gate**. Choosing a no-submit window after observing which windows
produced bad fills is a parameter selected after seeing the outcome. That is exactly R1/R4, and
rev 1 imported decision 4's ten numbers without carrying map §3.2's framing — "every number below is
an **evaluation grid centre, not a recommendation**" — to the seven parameters it added itself.

**HYPOTHESIS (hard, and it blocks I-E4):**

1. **The complete `execution_limits` row is fixed and recorded in a pre-registration document
   BEFORE the first armed session** — same form as
   `docs/research/PREREGISTRATION_2026-09-11_snapshot11.md`, naming every column, its value, and
   its unit.
2. **Each timing parameter carries a declared grid**, as map §3.2 does for the capital limits, so
   that a later change is visibly a move within a pre-registered grid rather than a fresh choice.
   Grid centres proposed (HYPOTHESIS): `cycle_interval_s` 30 (grid 15/30/60);
   `execution_stale_after_s` 90 (grid 60/90/180, constrained to ≥ 3 × cadence);
   `max_reconciliation_age_s` 120 (grid 60/120/300); `max_intent_age_minutes` 15 (grid 5/15/60);
   `no_submit_after_open_minutes` 15 (grid 5/15/30); `no_submit_before_close_minutes` 15 (grid
   5/15/30); drain timeout 30s (grid 10/30/60); buying-power tolerance (Q9) — see §10.
3. **Superseding an `execution_limits` row RESETS the decision-10 live-evidence counter for every
   strategy armed under it.** The ≥20 closed paper trades must be accumulated under the limits row
   actually in force. Without this rule, a parameter tuned mid-window inherits evidence generated
   under the old parameter, which is the precise shape of an outcome-tuned gate.
4. **Q6, Q7 and Q9 are resolved BEFORE I-E4, not after the first fills exist.** A number chosen
   after the first fills is not a pre-registered number.
5. Every `execution_event` carries `execution_limits_id` (§4, Q8 answered **yes**), so which row an
   order was submitted under is a matter of record rather than reconstruction.

---

## 8. Kill switch, the submission lock, and the drain sequence

**FACT: `killswitch.py` is deliberately fail-OPEN.** Module docstring, `src/signalforge/killswitch.py:9-12` (re-read this pass; rev 2 cited `:9-13`):
"a missing state file means *not engaged* (fresh install). An unreadable or corrupt file is also
treated as *not engaged* but logged at ERROR, because silently freezing a research tool on a parse
glitch is worse than the operator re-engaging explicitly." This is implemented at
`killswitch.py:65-83`: `FileNotFoundError`, `OSError`, `JSONDecodeError`, `KeyError` and
`ValueError` all return `KillSwitchState.initial()` — i.e. not engaged.

That is right for a research tool and **wrong for order submission.**

**HYPOTHESIS:** do **not** change `KillSwitch`'s semantics. FACT: `grep -rn "ensure_not_engaged("
src/signalforge` returns **39 call sites** excluding the definition at `killswitch.py:157`;
changing fail-open to fail-closed would silently alter all of them. Instead:

- `ensure_not_engaged()` is **one input** (K1): engaged ⇒ block **opening**, permit **closing**,
  run the drain-and-cancel sequence below.
- A **separate execution-local kill state** is added (K2), whose *unreadable/corrupt* case
  **blocks**. Missing evidence of safety is not evidence of safety. This state is
  execution-only; nothing else reads it; the 39 existing call sites are untouched.

**The race, and the lock (HYPOTHESIS, hard).** The limit checks and the network `place()` are
separate steps with a network call between them, so an order submitted microseconds before an
engage will not appear in the broker's order list when `cancel_all()` runs. Required sequence:

1. **Before** the network call, write `SUBMITTING` to `execution_event` with the
   `client_order_id`, **commit**, and release write intent (`db/session.py:118-124`). The in-flight
   set is durable across a crash, not in memory.
2. Call `place()` / `place_combo()` with **no open transaction**.
3. On engage: **stop admitting new submissions**, then **wait (bounded) for the in-flight set to
   drain**. The bound is operator-set (`execution_limits.drain_timeout_s`, grid centre 30s — §7b);
   on timeout, the undrained entries become `UNKNOWN`.
4. Then run **reconciliation**, then `cancel_all()`, then reconciliation **again**. Both
   reconciliation results are recorded.
5. A `SUBMITTING` record with no terminal outcome is an `UNKNOWN` (§6) and **blocks arming** until
   an operator resolves it.

**Who triggers the drain, and how long it takes (new in rev 2 — rev 1 wrote "on engage" as if
engagement were an event delivered to the OMS, and it is not).** FACT (re-read this pass):
`KillSwitch.state()` is an **on-demand JSON file read** (`src/signalforge/killswitch.py:65-83`),
engaged from a **different process** (CLI or app). There is **no watcher, no signal, and no
callback anywhere in the repo**. The OMS cannot be told; it can only **look**.

**HYPOTHESIS (the observation point, named):**

- The **only** observation point is K1/K2 at the top of each execution cycle, inside
  `execution_guarded` (§2). The **poll interval is `execution_limits.cycle_interval_s`**, grid
  centre 30s.
- **Worst case between engage and `cancel_all()`** = `cycle_interval_s` (up to 30s to notice)
  + `drain_timeout_s` (up to 30s to drain) + one reconciliation round trip ≈ **~60–70 seconds** at
  the grid centres. That number is a design output, not an aspiration; if the operator needs it
  smaller, `cycle_interval_s` is the knob and §2's call-budget arithmetic moves with it.
- **If the worker is not running when the operator engages, NOTHING happens at the broker.** No
  cycle runs, so nothing is polled, nothing drains, and `cancel_all()` is never called: **resting
  orders stay live at the broker indefinitely, and open positions stay open.** This is a property
  of a file-read kill switch observed by a polling loop, and no design in this ADR changes it.
- It is therefore added to the arming ceremony as acknowledgement **(iv)**, in the same plain words
  as (ii): *engaging the kill switch while the worker is down cancels nothing at the broker; the
  operator must cancel by hand, at the broker.*

**Post-timeout non-duplication (HYPOTHESIS, hard).** On any timeout or ambiguous response:

1. Call `order_status(client_order_id)` and `open_orders()` **before** any resubmission.
2. Resubmit **only** if the broker does not know the id at all.
3. If the broker reports a `client_order_id` the local `execution_event` store has no record of,
   **halt and alert**. That is a divergence, not a retry.
4. A broker **rejection** is surfaced verbatim (`OrderResult.error_verbatim`) and is **never**
   retried automatically (map §6.7b).

---

## 9. Dead man — the deliberate inverse of the kill switch

FACT: the pattern already exists. `WorkerHeartbeat` (`src/signalforge/db/models/system.py:130-147`)
is one upserted row per worker with `last_beat_at` indexed;
`src/signalforge/scheduler.py:610-611` sets `HEARTBEAT_INTERVAL_S = 30` and
`WORKER_STALE_AFTER_S = 3 * HEARTBEAT_INTERVAL_S` (= 90s), used at `scheduler.py:685`.
(Rev 1 cited `:507-508`; that range is inside `_intraday_scan_spec`'s docstring. Re-read this pass.)

**HYPOTHESIS:** the execution dead man writes its own heartbeat at the top of every execution
cycle — **including the protective-only branch of `execution_guarded` (§2)**, so that engaging the
kill switch does not lapse the dead man as a side effect — and is evaluated fail-**CLOSED**: a
heartbeat older than `execution_stale_after_s` (grid centre: 90s, mirroring `WORKER_STALE_AFTER_S`,
and constrained to **≥ 3 × `cycle_interval_s`** so the two numbers cannot be set into contradiction
— §7b), **or unreadable, or ambiguous**, blocks all opening, triggers the §8 drain-and-cancel
sequence, and auto-disarms — while leaving `may_close` open. **Missing evidence of health is
evidence of ill health.** The lapse does **not** make a protective close unconstructible: §5.2b's
close factory requires no armed row.

**What happens to a live position when the dead man lapses (stated, because saying nothing here is
not acceptable).** The lapse blocks opening and auto-disarms. It does **not** auto-liquidate: an
automatic liquidation is an unreviewed order, which §10's rule already forbids. Therefore **the
operator must close the position by hand, at the broker**, and the arming ceremony must say so in
those words (§12 step 3(ii)). An operator who does not know this before arming will discover it
during an outage.

---

## 10. Reconciliation

**HYPOTHESIS:** every cycle, compare `adapter.positions()` and `adapter.open_orders()` against
local `execution_event`-derived state. Any divergence ⇒ **halt opening, disarm, alert, require
operator acknowledgement. Never auto-correct** — an automatic reconciliation fix is an unreviewed
order.

Additions beyond "compare once a cycle", each of which closes a specific hole:

- **Maximum age.** "Clean as of the last cycle" is a stale-state check. Between cycles the broker
  side can diverge on its own: a manual trade in the same account, a broker-initiated liquidation,
  an assignment. `max_reconciliation_age_s` joins the limit set (R1): an unreconciled window older
  than N seconds **blocks like a dead-man lapse**.
- **A fresh reconciliation is required immediately before the first order of any session**,
  regardless of age.
- **No shared account, detected rather than assumed — and, from rev 2, machine-checked at arm time
  rather than left as an operator acknowledgement.** Any position or open order the OMS did not
  originate — no matching `client_order_id` in `execution_event` — is a **divergence** and halts.

  **Why an acknowledgement is not enough (the defect rev 1 carried).** FACT: decision 2
  (`DECISIONS_2026-09-12_options_execution.md:12`) justifies the assumed broker partly by
  "fractional shares — **also required by the grid strategy's $5 orders**", i.e. a *second*,
  equity order stream is already anticipated in the same broker relationship; decision 13 sizes a
  separate **options** paper account and says nothing about where the equity execution stream
  lives. If two armed strategies, or a manual grid, ever share one account, §10 halts
  **permanently** on the first foreign position — and the operator will have acknowledged a
  sentence rather than been stopped by a check.

  **HYPOTHESIS (hard):** one account per armed adapter, enforced:
  1. `armed_strategy.broker_account_id_expected` is **UNIQUE across live armings**
     (`WHERE disarmed_at IS NULL`) — two strategies cannot be armed against the same account id.
  2. The arming CLI **refuses** if `adapter.positions()` or `adapter.open_orders()` returns
     **anything** at arm time. Arming begins from a flat, empty account; an account with something
     already in it is either shared or carrying a position from a prior arming the operator has not
     resolved, and neither is a state to arm into.
  3. §12 step 3(iii) stays as an acknowledgement **in addition**, because the operator still has to
     not go trading in that account afterwards — but it is no longer the only thing standing there.
  4. Drilled as **V17**.
- **Margin/buying power is reconciled, never modelled authoritatively.** The local collateral model
  (map §3.1) is a model; the broker's own buying-power figure from `adapter.account()` is
  authoritative, and divergence beyond a **pre-registered** tolerance halts. "Pre-registered" is
  literal: the tolerance is a column of the `execution_limits` row fixed in the §7b
  pre-registration document **before the first armed session**, with a declared grid, because a
  tolerance widened after seeing which divergences were "just rounding" is a parameter chosen after
  the outcome (Q9, resolved before I-E4). **HYPOTHESIS: both forms, and the binding tolerance is
  the tighter — `min(tolerance_usd, tolerance_pct × buying power)` — with grid centres $1.00 and
  0.1%.** Zero is not an option: it halts on rounding.
- **Assignment shows up here first.** A position the OMS did not open, appearing after an
  expiry-adjacent session, is the live signature of an early assignment — the exact tail the
  backtest approximates away (map §2.7). It halts as a divergence, which is the correct behaviour:
  the system must not trade on in a book it does not understand.

---

## 11. Clock, calendar, and no-submit windows

`adapter.clock()` alone is not a rule. **HYPOTHESIS:**

- The OMS **cross-checks `adapter.clock()` against `data/options_calendar.py`** every cycle, and
  **disagreement blocks**. Two sources of truth that disagree about whether the market is open is
  exactly the condition under which an order must not be sent.
- FACT (citations re-read in this revision; rev 2's were wrong): `data/options_calendar.py` does
  not exist yet; `src/signalforge/data/calendar.py` (101 lines total) provides NYSE sessions via
  `pandas_market_calendars` XNYS — `import pandas_market_calendars as mcal` at `calendar.py:13`,
  `_xnys()` returning `mcal.get_calendar("XNYS")` at `:34-35`, `sessions()` at `:39-42` — plus RTH
  bounds (`rth_bounds_utc` `:53-62`, `rth_bounds` `:64-71`), and has **no expiration and no
  early-close logic anywhere** (the only occurrence of "holiday" is a docstring line at `:3`). The options calendar is a D2
  deliverable, and **this ADR is its second consumer**: it must be designed for the OMS from the
  start, or the execution layer will re-implement it inconsistently.
- **No-submit window after the open** (the opening auction and its immediate aftermath, when option
  spreads are widest and prints least representative) and **before the close**, both operator-set,
  both stored in `execution_limits`.
- **Early-close sessions block by default.** FACT (general information, to be verified with the
  broker — §20): on U.S. early-close days equity options stop at 13:00 ET. Submission on any
  session the local calendar marks early-close is **refused** unless the early-close time is
  explicitly handled by the calendar module **and** the adapter's clock agrees with it.
- **AM-settled cash index options are out of scope** by the underlying allowlist (map §2.8). The
  allowlist is the enforcement; the OMS **asserts** it per intent rather than assuming it.

---

## 12. The arming ceremony

**Every step is an operator action. None is automated. None can be triggered by a document, a
message, a scan result, an agent, or an LLM.**

1. The strategy version is PAPER_APPROVED with a passing sealed test on a named snapshot,
   **and that sealed test is traceable to a pre-registration document that enumerated the full
   grid** (new in rev 2 — see "multiplicity at the moment risk is taken", below).
   FACT (read-only query, this session): three versions are PAPER_APPROVED —
   `relative_strength.medium_swing 0.1.0`, `trend_continuation.medium_swing 0.1.0`,
   `trend_continuation.short_swing 0.1.0` (the third is the v3 disposition of commit `68b533c`);
   the other three registered versions are EXPERIMENTAL.

   **Multiplicity at the moment risk is taken (new in rev 2).** Rev 1's `armed_strategy` recorded
   `spec_json_hash`, `config_hash`, `dataset_snapshot_id`, `evidence_paper_trade_count` and
   `evidence_expectancy_r` — but **not k**. So the multiplicity cost was invisible at the exact
   moment capital was put at risk. FACT (re-read this pass): `count_sealed_looks(session,
   strategy_name)` already exists (`src/signalforge/research/promotion.py:647`) and
   `sealed_look_prior` is already carried on `PromotionResult` (`promotion.py:151`, `:175`, `:978`,
   `:1023`, `:1414`) — so this is **free**. Map §5.4 names R5 disclosure of abandoned variants, not
   the count, as "where multiplicity will leak", and recommends surfacing `count_sealed_looks` for
   the family in the pre-registration and disposition record; the arming record is the natural
   third place and rev 1 omitted it. **HYPOTHESIS (hard):**
   - `armed_strategy` gains **`sealed_look_prior_at_arm`** (from `count_sealed_looks` for the
     **family**, computed at arm time) and **`preregistration_doc_id`** (§16).
   - Both are printed in the step-5 preconditions table, above the typed confirmation.
   - **The CLI REFUSES to arm a version whose sealed test is not traceable to a pre-registration
     document that enumerated the full grid.** Sealed-look accounting for the options family starts
     at k=0 by construction (map §5.4: `count_sealed_looks` keys on `Strategy.name`, and a new
     options family has no prior rows) — this rule is what keeps the *reported* k honest as the
     family grows.
2. **Live paper evidence precondition (decision 10, binding).** FACT:
   `DECISIONS_2026-09-12_options_execution.md:20` — "a strategy may be armed only after **≥ 20
   closed paper trades with non-negative expectancy under the health monitor**, unless the operator
   overrides explicitly and the override is audited." The CLI evaluates this itself and refuses
   otherwise; the override is a separate flag that writes its own `execution_event` with the
   operator's typed reason. **The override must additionally record the observed `n` and the
   observed expectancy alongside that reason** (`evidence_paper_trade_count` and
   `evidence_expectancy_r` are made **NOT NULL whenever `evidence_override_reason` is set`) — the
   override is by construction taken *after* seeing the outcome, so what was seen is part of the
   record, not context the operator is trusted to remember. FACT (read-only query, this session): `paper_trade` = **0** rows,
   `paper_position` = **0**, `strategy_health` = **0** — so **nothing is armable today**, and that
   is the correct state. FACT (map §3.1): for a cash-secured put the paper stream is thin enough
   that 20 closed trades may take years; the observation window is set from the **expected paper
   rate**, never from the backtest count.
3. The operator writes a signed arming record naming: version id, `spec_json_hash`, `config_hash`,
   snapshot id, adapter name, **the expected broker account identifier** (typed out of band —
   §13), max notional, max orders/day, **options approval level asserted by the operator**, an
   **expiry timestamp**, and an explicit acknowledgement of three facts:
   **(i)** the backtest **approximates early assignment away** (map §2.7), so live outcomes can
   differ in exactly that tail — and the approximation is biased *in the strategy's favour*;
   **(ii)** if the dead man lapses or the kill switch engages, **the operator closes any open
   position by hand at the broker** (§9);
   **(iii)** the broker account **must not be shared with manual trading**; any position the OMS
   did not originate halts the system (§10) — and, from rev 2, arming is **machine-refused** if the
   account is not flat and empty, and the account id is UNIQUE across live armings (§10);
   **(iv)** **engaging the kill switch while the worker is down cancels nothing at the broker.**
   Resting orders stay live and open positions stay open; the operator must cancel by hand, at the
   broker. Worst case between an engage and `cancel_all()` with the worker *running* is
   ~60–70 seconds at the grid centres (§8).
4. The operator supplies credentials via env var or macOS Keychain, out of band. The system reads;
   it never stores, never writes, never rotates, never logs (§16).
5. `signalforge execution arm --version <id> --adapter <name> --expires <ts>` — a CLI that
   **refuses** unless every precondition in steps 1–3 re-verifies **live against the DB** and
   `is_paper()` **proves out against the typed account id** (§13), prints the full preconditions
   table, and then requires a **typed** confirmation (not a y/N). FACT (CLI shape precedent, re-read this pass): the
   app is a `typer.Typer` with per-area sub-apps added by `app.add_typer(...)` —
   `src/signalforge/cli.py:19-25`, `:275-276`, and the universe sub-app at `:1886-1889` (rev 1
   cited `:1868-1869`, which is inside `paper_probation_enable`). A new `execution_app` follows the
   same shape, with a help string that states the package is disabled by default — and that help
   string must **not** assert an unconditional no-order promise (§18).
6. Arming writes an `armed_strategy` row and an `execution_event`, and calls
   `audit.record("execution.armed", ...)`. **It expires automatically. There is no indefinite
   arming.** FACT: arming expiry default **7 days** (decision 4).
7. **Auto-disarm on ANY of** (decision 9: FACT — "**On any status change** (not only
   downgrades)", `DECISIONS_2026-09-12_options_execution.md:19`):
   - any `StrategyVersion.status` change, in either direction, away from the armed value;
   - `spec_json_hash` or `config_hash` drift;
   - approved-scope mismatch;
   - kill switch engaged;
   - dead-man lapse;
   - reconciliation divergence **or** staleness past `max_reconciliation_age_s`;
   - an outstanding `UNKNOWN` intent for this strategy;
   - `is_paper()` failing to re-prove in any cycle;
   - daily order-cap breach;
   - `expires_at` passing.

   Each disarm writes `armed_strategy.disarmed_at` + `disarm_reason` and an `execution_event`.
   **Re-arming is the full ceremony again.** There is no "resume".

---

## 13. The `is_paper` proof

**A boolean derived from a local config flag is not proof and must not be accepted.** A
misconfigured base URL is the single most likely way real money gets touched, and the flag and the
URL are set in the same place by the same mistake — so a local flag cannot catch it.

**Required proof (HYPOTHESIS, hard):**

```
IsPaperProof (frozen)
  proven: bool
  observed_account_id: str        # read out of the BROKER'S OWN response body
  observed_host: str              # the host actually connected to
  expected_account_id: str        # from armed_strategy.broker_account_id_expected
  checked_at: datetime
  raw_excerpt: str                # redacted via observability.redact before storage
```

1. The adapter calls the broker and reads the **account identifier and/or endpoint host out of the
   broker's own response body**.
2. It matches that against `armed_strategy.broker_account_id_expected` — a value the **operator
   typed into the arming record** (§12 step 3), out of band.
3. **A mismatch, an absent field, or an unparseable response is a FAILURE, not a warning.** It
   blocks arming and every subsequent submission, and it is an auto-disarm trigger (§12 step 7).
4. The proof is re-taken **every cycle**, not once at arm time.
4b. **`expected_account_id` is read from the most recent `armed_strategy` row for that adapter,
   including disarmed and expired rows** (§6 rule 5a). Disarming ends the authority to open; it does
   not erase the record of which account this adapter was pointed at, and the reconciliation that
   clears an `UNKNOWN` runs *after* an auto-disarm by construction. If no row has ever existed for
   the adapter, the expected id comes from the adapter's own reviewed configuration; failing that,
   reconciliation **halts and alerts** rather than proceeding against an unproven account.
5. The host observed is additionally checked against a literal, reviewed paper-host allowlist
   constant in `execution/brokers/<vendor>_paper.py` (§19 T5).

**Required safety test, written BEFORE the vendor adapter exists (I-E1/I-E3):** assert that
**both** `paper_reference` and any vendor adapter **fail arming** when the account id in the
(stubbed) broker response does not match the armed record.

---

## 14. Combo submission and partial fills

**The hazard, stated concretely.** A multi-leg structure submitted **leg by leg** can end with one
leg filled and the other rejected. For a put credit spread that means the **short** leg filled and
the **long wing** rejected — i.e. an **accidental naked short option**: the exact structure map
§4.5 bans by design, at an approval level the operator may not hold, with undefined max loss and
therefore **no defined R** — which takes the position outside the entire
metrics stack (map §2.6).

**Rules (HYPOTHESIS, hard):**

1. **Multi-leg structures are submitted as a single native combo order.** One `client_order_id`,
   one atomic broker-side instruction, one `ComboOrderIntent`.
2. **"Cannot submit a combo atomically" is an adapter-ineligibility condition** (A2, §3), alongside
   idempotency and the `is_paper` proof. It is not a limitation for the OMS to work around.
3. **Leg-by-leg submission is not implemented in Phase 1, and the OMS has no code path that could
   express it.** `place()` accepts an `OrderIntent` (single instrument); `place_combo()` accepts a
   `ComboOrderIntent` (≥2 legs). There is no loop over legs anywhere. If leg-by-leg is ever
   permitted, the unwind procedure must be specified **before** the first submission, and **an
   unpaired short leg is a halt-and-alert condition, not a position** — the OMS refuses all further
   opening, alerts, and routes the unwind through `may_close` only.
4. **`PARTIAL` on a combo** — partial contract quantity, all legs proportional — is a legitimate
   terminal outcome, reconciled like any other. A partial **by leg** is a halt (rule 3), detected
   by comparing filled ratios across legs against the intent's declared ratios.
**FACT (the full docstring sentence, quoted whole this time — rev 2 quoted only the half that
suited it):** `src/signalforge/options/__init__.py:1-11` reads "There is no options execution path
anywhere in this package: no order placement, no broker contact, no recommendations, no alerts.
Nothing here reads a brokerage credential. **Naked short options, uncovered calls,
margin-dependent strategies, 0DTE alerting, and spreads are intentionally absent**". Decision 12
makes a short vertical **spread** the first structure, so this docstring becomes **false** the day
the options strategy package exists — not the day this ADR is approved. It is therefore on §18's
one-commit amendment list, and quoting only the naked-short clause (as rev 2 did) hid exactly the
clause that changes.

5. **Every leg asserts `shares_per_contract == 100` at intent time.** FACT:
   `OptionContract.shares_per_contract` is a real column populated from the vendor
   (`src/signalforge/db/models/market.py:255`), and FACT:
   `OptionContract.exercise_style` defaults to `'american'` (`market.py:254`) — early assignment is
   real. A non-100 deliverable is the machine-readable signature of an OCC adjustment; the intent
   is **refused** and the refusal counted (map §2.3, gate 0.h).

---

## 15. Audit

**HYPOTHESIS: reuse the existing sink verbatim; add no second redaction implementation.**

FACT: `src/signalforge/audit.py:26-36` `record(action, *, actor, entity, **fields)` appends one
JSONL event and passes `fields` through `redact()`. FACT:
`src/signalforge/observability/logging.py:24-42` `redact()` masks `pydantic.SecretStr` always and
recurses through dicts and sequences. FACT: `AuditLog` (`db/models/system.py:95-104`) is the DB
table with `ts`, `actor`, `action`, `entity`, `request_id`, `before_json`, `after_json`.

Every intent, validation refusal, submission, fill, rejection, cancellation, reconciliation result,
reconciliation divergence, arm, disarm, kill-switch interaction, dead-man lapse, and `is_paper`
proof writes **both** an `execution_event` row (§16) and an `audit.record(...)` call. Every event
carries the intent's `config_hash` and `spec_json_hash`.

FACT (why the hashes matter, and it is not hypothetical): the 2026-09-11 config-hash incident —
adding an `agents` section to `ResearchConfig` silently changed the hash used in the five-part
scope match, so live scans matched no approved scope — was detectable **only because the scope
match was recorded**. It was masked further only because those scans produced zero qualified
candidates (`docs/PAPER_PROBATION_ACTIVATION.md`; fixed by commit `0cc4cf4`). Record the hashes on
every execution event for exactly that reason.

`execution_event` is **append-only**, with the same immutability discipline as `PaperTrade` (S9).
Corrections are new rows, never edits — the `TradeCorrection` pattern (`db/models/paper.py:120-130`).

**The mechanism, corrected (rev 1 cited the wrong one, and the difference is load-bearing).** FACT
(re-read this pass): `ImmutablePaperTradeError` is declared at `src/signalforge/paper/ledger.py:54-55`
and exported (`paper/__init__.py:16`, `:27`) but has **no raise site anywhere in `src/signalforge`** —
`tests/safety/test_s9_paper_immutability.py:18` only asserts it is a `RuntimeError` subclass. The
**real** S9 enforcement is a pair of SQLite triggers, `paper_trade_no_update` and
`paper_trade_no_delete`, created in
`src/signalforge/db/migrations/versions/20260906_1041-839214f66f31_initial_schema.py:1267` and
`:1274` (dropped at `:1285-1286`) and proved by `tests/db/test_s9_paper_trade_triggers.py`.

**HYPOTHESIS (consequences for I-E2, all three required):**

1. The I-E2 migration creates **equivalent `BEFORE UPDATE` / `BEFORE DELETE` triggers on
   `execution_event`** — `execution_event_no_update`, `execution_event_no_delete` — with the same
   `RAISE(ABORT, ...)` shape as the `paper_trade` pair. An ORM-level exception class is **not** the
   mechanism and must not be mistaken for one.
2. **T8** (§19) asserts that `UPDATE` and `DELETE` on `execution_event` both fail **at the database
   level**, in the shape of `tests/db/test_s9_paper_trade_triggers.py`.
3. The pattern is copied by **re-implementing the trigger DDL in the execution migration**, not by
   importing anything from `signalforge.paper` — S15b forbids `paper → execution` and this ADR does
   not create the reverse dependency either.

---

## 16. Credentials

**HYPOTHESIS, and it is a prohibition before it is a design:**

- Credentials are read **only** from (a) an environment variable, or (b) a macOS Keychain item, by
  name. Read once at process start, held as `pydantic.SecretStr`, never written anywhere, never
  logged, never placed in the DB, never in the repo, never in an `execution_event` payload.
- **This document names only env-var names and keychain item names, never values.** Proposed names
  (HYPOTHESIS): env `SF_EXECUTION_BROKER_KEY_ID`, `SF_EXECUTION_BROKER_SECRET`; keychain service
  `signalforge-execution`, account `<adapter_name>`.
- FACT (re-read this pass): `SecretStr` is already the established pattern for every secret
  setting — `src/signalforge/config/settings.py:42` (`app_encryption_key`), `:51`
  (`market_data_api_key`), `:62` (`options_api_key`), `:69` (`discord_webhook_url`), `:73`
  (`llm_api_key`). (Rev 1 cited `:74` for `llm_api_key`.)
- FACT: **no keychain mechanism exists anywhere in the repo today** — a repo-wide grep for any
  keychain mechanism returns zero hits. `credentials.py` is entirely new code, and it **reads
  only**: no `security add-generic-password`, no write API, no rotation.

**The Keychain reader, named exactly (new in rev 2 — rev 1 left the mechanism unspecified, and the
only obvious route leaks the secret).** **HYPOTHESIS: no new dependency is added.** The reader
shells out to the system binary:

```
/usr/bin/security find-generic-password -s signalforge-execution -a <adapter_name> -w
```

with these rules, each closing a specific leak:

- The subprocess is invoked with `capture_output=True`; **its stdout is read into a `SecretStr` at
  the call boundary and the plain `str` never escapes that function** — not into a local that
  outlives it, not into an f-string, not into a log call, not into an exception message.
- **`stderr` is read and logged; `stdout` is never passed to `structlog` under any condition**,
  including error paths. FACT (why this rule is not paranoia): `redact()`
  (`src/signalforge/observability/logging.py:24-42`) masks `pydantic.SecretStr` **always** and masks
  values under **sensitive key names** — so a plain `str` returned from the reader and logged under
  a neutral key is **unredacted by construction**. T7 scans for credential *literals in source*; it
  cannot see a runtime value.
- The invocation is a fixed argument vector (no shell, no interpolation of anything but the
  adapter name, which is validated against the adapter registry).
- A missing or failing keychain item is **not** a fallback to a less safe source. It is a refusal.
- **T11** (§19) asserts the secret value appears in **no log record and no `execution_event`
  payload**, by capturing structlog output around a stubbed reader whose value is a known sentinel.
- **The operator supplies these. The system never acquires, stores, or rotates them.**
- FACT (gate): `make secrets` is a real check-only gate (`Makefile:80`) that fails on any secret
  not already audited into `.secrets.baseline` and **never rewrites the baseline**
  (`Makefile:84` is the separate, manual regeneration target). Test fixtures needing a
  credential-shaped literal use an inline pragma; the baseline is not rewritten to accommodate
  execution code.

### Schema additions (HYPOTHESIS) — three tables and one column

```
armed_strategy            (append-only in spirit; disarm is an UPDATE of disarmed_at/disarm_reason
                           plus an execution_event row)
  id, strategy_version_id (FK), structure_type, armed_at, armed_by, expires_at,
  adapter_name, broker_account_id_expected, options_approval_level_asserted,
  max_notional, max_orders_per_day, evidence_paper_trade_count, evidence_expectancy_r,
  evidence_override_reason (NULL unless decision-10 override used;
                            when set, the two evidence_* columns are NOT NULL — §12 step 2),
  sealed_look_prior_at_arm,        -- count_sealed_looks() for the FAMILY, at arm time (§12 step 1)
  preregistration_doc_id,          -- the pre-registration document the sealed test traces to
  execution_limits_id,             -- the limits row in force at arm time (§7b rule 3)
  spec_json_hash, config_hash, dataset_snapshot_id,
  disarmed_at, disarm_reason
  UNIQUE(strategy_version_id) WHERE disarmed_at IS NULL     -- at most one live arming per version
  UNIQUE(broker_account_id_expected) WHERE disarmed_at IS NULL   -- one account per live arming (§10)
  -- BOTH are SQLite PARTIAL indexes and Alembic must emit them via
  --   op.create_index(..., unique=True, sqlite_where=sa.text("disarmed_at IS NULL"))
  -- A plain UNIQUE constraint here would forbid ever re-arming a version, which §12 requires.

execution_limits          (account-level; ONE active row; versioned by supersession, never edited)
  id, created_at, created_by, superseded_at,
  -- EVERY numeric column carries its unit in its name (§4.1). Where decision 4 and map §3.2
  -- disagree, BOTH are stored and the binding limit is min(usd, pct x live equity).
  max_orders_per_day, max_order_notional_usd, max_account_exposure_pct,
  per_structure_max_loss_usd, per_structure_max_loss_pct,
  aggregate_open_max_loss_usd, aggregate_open_max_loss_pct,
  collateral_cap_usd, collateral_cap_pct,
  max_net_delta_notional_usd, max_net_vega_per_volpt_usd,
  cycle_interval_s,                       -- §2; execution_stale_after_s >= 3 x this
  max_intent_age_minutes, max_reconciliation_age_s, execution_stale_after_s,
  drain_timeout_s,                        -- §8 step 3 (Q7)
  buying_power_tolerance_usd, buying_power_tolerance_pct,   -- §10 (Q9); binding = the tighter
  no_submit_after_open_minutes, no_submit_before_close_minutes,
  round_trips_per_5_sessions_max, pdt_equity_threshold_usd,
  preregistration_doc_id                  -- §7b rule 1: no row without one

execution_event           (APPEND-ONLY; no UPDATE, no DELETE — enforced by SQLite triggers
                           execution_event_no_update / execution_event_no_delete, §15, T8)
  id, ts, event_type, client_order_id, source_paper_trade_id, source_options_trade_id,
  strategy_version_id, armed_strategy_id, adapter_name, state_from, state_to,
  execution_limits_id,                                     -- Q8 answered: yes (§7b rule 5)
  config_hash, spec_json_hash, payload_json (redacted), raw_status_verbatim, error_verbatim,
  modelled_fill_price, modelled_spread_bps,                -- §4.2
  realized_fill_price, realized_minus_modelled_bps         -- §4.2, on FILL events
  INDEX(client_order_id), INDEX(ts)

paper_trade.actor         (NEW COLUMN — §5.3; String(60), default 'local-user', indexed)
<options trade table>.actor
                          (NEW COLUMN — §5.3b; SAME type, default, index, and backfill rule.
                           The options ledger is map §3.6's deliverable, not this ADR's; this
                           column is added to it in the same I-E2 migration, and I-E2 is BLOCKED
                           until that table and assert_options_auto_simulate_allowed exist.)
```

FACT (naming convention for the migration file): `src/signalforge/db/migrations/versions/` uses
`YYYYMMDD_HHMM-<rev>_<slug>.py` (e.g. `20260910_0800-e5a1b7c3d9f2_agent_report.py`).

---

## 17. Contracts — the exact changes, and the direction the map got right

### 17.1 What stays exactly as it is (this is the decision, not an omission)

Because of decision **D6-A** (§3 — no vendor SDK is imported; the adapter speaks REST over
`httpx`):

- **import-linter S1 keeps all 5 forbidden modules, unchanged** (`pyproject.toml:194-198`).
- **Ruff `banned-api` keeps all 5 entries, unchanged** (`pyproject.toml:104-110`).
- **`BANNED_IMPORTS` keeps all 15 names, unchanged** (`tests/safety/test_s1_no_broker_surface.py:18-34`).
- **`BANNED_CALL_SUBSTRINGS` keeps all 9 and *gains four* — see §17.1b.** Nothing is removed.
- No name is removed from any list, and the **import** scan needs no path-prefix allowlist,
  because the adapter imports no banned name.

This is a **strictly smaller** change than the map's §6.8 step 4 anticipated, and it is smaller for
a reason that can be checked rather than trusted: the adapter imports no banned name, so no
exception is required. The map's plan (a path-prefix allowlist for exactly
`src/signalforge/execution/brokers/`) remains the **pre-agreed** form of the carve-out **if** a
future broker can only be reached through an SDK — see open question Q1. In that event the carve-out
must be: path-prefix allowlist only; no removal from any list; S1, Ruff, and the test changed in
**one reviewed commit**; and the allowlisted name added to Ruff's message as an explicit exception.

### 17.1b The call-string scan is EXTENDED, not left inert (new in rev 3)

**The defect this corrects.** §1.2 correctly establishes that none of the 9 `BANNED_CALL_SUBSTRINGS`
matches the §3 protocol's `place`, `place_combo`, `cancel`, `cancel_all`, or `order_status`, and rev 2
presented that as "not a blocker" and moved on. Combined with D6-A (no vendor name imported, so
E1/E2/E3 never fire), the net effect was that **both** mechanical barriers became inert against the
one surface they were written for, leaving only T5 — which §22 itself concedes is a **weaker** kind
of check (a string scan over source, not an import-graph proof). A denylist that provably cannot see
the thing it exists to see is decorative, and §3 says the denylists must not become that.

**HYPOTHESIS (hard, in the same I-E1 commit):** `BANNED_CALL_SUBSTRINGS` **gains four entries** —
`place_combo(`, `cancel_all(`, `.place(`, `order_status(` — under a **path-prefix allowlist for
exactly `src/signalforge/execution/`**. Every other path in `src/signalforge` fails on them.

- This **removes nothing** and is **strictly more searching** than today's list, so it does not
  touch §17.1's "nothing removed" guarantee and does not weaken any gate (R4).
- FACT (verified in this pass, so the addition lands green rather than red):
  `grep -rF` over `src/signalforge` returns **0** hits for each of `place_combo(`, `cancel_all(`,
  `.place(`, and `order_status(` today. `.place(` is written with the leading dot deliberately —
  bare `place(` would match `.replace(`.
- The allowlist is the **path prefix**, never the substring: an order-submission call appearing
  anywhere outside `src/signalforge/execution/` fails the safety suite exactly as it would have
  before this ADR existed.
- Asserted by **T13** (§19): the allowlist covers `src/signalforge/execution/` and nothing else,
  and a planted `cancel_all(` under `src/signalforge/app/` fails the scan.

### 17.2 What is added — two contracts in opposite directions, plus one amendment

FACT (the gap being closed): **nothing in the current contract set would stop
`signalforge.llm`, `signalforge.agents`, or `signalforge.app` from importing a future
`signalforge.execution`.** S3 (`pyproject.toml:177-186`) forbids
`research`/`risk`/`backtest`/`paper` → `llm` and says nothing about the reverse or about
execution. S14 (`pyproject.toml:255-277`) forbids `signalforge.agents` from a hard-coded list of
**17** modules — `paper.ledger`, `alerts.dispatch`, `alerts.channels`, `research.scan`,
`research.candidates`, `research.promotion`, `research.persistence`, `data.ingest`, **five**
`data.adapters.*` (`massive`, `massive_news`, `massive_options`, `stooq`, `registry` — rev 2 said
four; re-counted line by line in this pass, `pyproject.toml:259-277`), `universe.pipeline`,
`killswitch`, `httpx`, `requests` — on which a new
`signalforge.execution` does **not** appear. So the operator's "no LLM ever decides an order"
guarantee has **no structural enforcement at the layer that actually submits orders**. An outbound
contract alone does not fix this; the **inbound** one does.

```toml
# --- append to pyproject.toml, in the I-E1 commit, nothing else in that commit ---

[[tool.importlinter.contracts]]
name = "S15a: the execution layer never imports the LLM, agents, alerts, scan, or SF1000 layers"
type = "forbidden"
source_modules = ["signalforge.execution"]
forbidden_modules = [
    "signalforge.llm",
    "signalforge.agents",
    "signalforge.alerts",
    "signalforge.research.scan",
    "signalforge.sf1000",
]

[[tool.importlinter.contracts]]
name = "S15b: nothing outside the execution layer may import it — no LLM, agent, app, research, alert, or SF1000 code path reaches an order"
type = "forbidden"
source_modules = [
    "signalforge.llm",
    "signalforge.agents",
    "signalforge.app",
    "signalforge.research",
    "signalforge.alerts",
    "signalforge.sf1000",
    "signalforge.backtest",
    "signalforge.paper",
    "signalforge.portfolio",
    "signalforge.scheduler",                      # rev 3 — see §2: the spec is injected, never imported
]
forbidden_modules = ["signalforge.execution"]     # the WHOLE package, not just .brokers
```

**`allow_indirect_imports` is NOT set on either contract, and that is load-bearing (new in rev 3).**
FACT (verified in this pass): import-linter **2.15** is the pinned version in the venv
(`pyproject.toml:56` `import-linter>=2.1`), and a `forbidden` contract reports **indirect** chains
unless `allow_indirect_imports = true` is set on it. Leaving it unset is the whole point: the
guarantee the operator asked for is "no LLM decides an order", and an LLM that reaches an order
through two hops has still reached it. **The cheap way out of a red build here would be to set
`allow_indirect_imports = true`, and that must not be taken** — it would degrade S15b to direct
edges only, at which point both chains that actually carry traffic (`app → scheduler → execution`
and anything → `cli` → `execution`) become invisible and §22's claim of structural enforcement
becomes false.

**The compensating requirements, because an unset flag is not self-enforcing:**

1. §2's rule stands: the execution spec is injected from `signalforge.cli` **only**. Neither
   `signalforge.scheduler` nor `signalforge/app/**` imports `signalforge.execution`, so no indirect
   chain exists to flag.
2. **Before I-E1 is declared done, `make lint` is run against a stub
   `src/signalforge/execution/__init__.py`** (the module constant and the docstring, nothing else)
   with S15a/S15b/the S14 amendment already in `pyproject.toml`. A contract that has never been
   evaluated against a real module is a contract nobody has tested.
3. **T12** (§19) asserts, transitively, that the only static import path into `signalforge.execution`
   from anywhere in `src/signalforge` is `signalforge.cli`, and **T1 is a transitive-chain scan**,
   not a direct-edge scan — rev 2 specified T1 as a direct AST scan, which shares the exact blind
   spot `allow_indirect_imports = true` would have introduced.

**And amend S14 in the same commit** by adding `"signalforge.execution"` to its
`forbidden_modules` list (`pyproject.toml:259-277`), so the agents contract names execution
explicitly rather than relying on S15b alone. FACT: S14 already carries an
`ignore_imports = ["signalforge.llm.client -> httpx"]` exception (`pyproject.toml:280`); no new
exception is added.

**Two notes on S15b's source list (HYPOTHESIS, both deliberate):**

1. `signalforge.paper` and `signalforge.backtest` are **in** the list, which the map's draft did
   not include. The direction of dependency is one-way by design: `execution` reads `PaperTrade`
   and `Candidate` (§5), and `paper` must never call `execution`. Putting `paper` in the source
   list makes that one-way-ness structural rather than conventional, and it costs nothing today
   (no such import exists).
2. `signalforge.cli` is **not** in the list, because the arming ceremony and the `execution`
   command group live there (§12 step 5). The CLI is the operator's hand; it is the one sanctioned
   inbound edge, and it is a human-typed entry point with no LLM on it. That asymmetry is the
   point, and it is recorded here so a reviewer does not read the omission as an oversight.
   **`signalforge.scheduler` IS in the list, from rev 3.** Rev 2 left it out as a second sanctioned
   inbound edge; §2's corrected registration rule means it never needs one — the spec is injected
   from the CLI and `scheduler.py` gains no import — so putting it in the source list makes that
   structural instead of conventional, and costs nothing today. `signalforge.cli` is therefore the
   **only** exemption, which is exactly what T12 asserts.

### 17.3 The safety-test plan

`tests/safety/test_s1_no_broker_surface.py` is **not relaxed** (§17.1). A **new** file
`tests/safety/test_s15_execution_boundary.py` is written in I-E1, **before any execution code
exists**, so its shape is reviewed on its own rather than as a fix to a red build. Its assertions
are listed as **T1–T13** in §19. Two of them do not live in that file: **T8** (database triggers)
belongs beside `tests/db/test_s9_paper_trade_triggers.py`, and **T13** is an assertion *about*
`tests/safety/test_s1_no_broker_surface.py`'s own extended list (§17.1b) and lands in that file's
commit. Everything else is in the new file.

---

## 18. The documentation amendment commit

**One commit, all of these files, or none of them** (FACT of risk: amending some and not others
leaves the repository contradicting itself, which is worse than either state alone):

| File | Change (HYPOTHESIS) |
|---|---|
| `docs/decisions/0003-execution-layer.md` | **new** — this ADR, approved, naming the boundary superseded, quoting it, stating what replaces it, and stating what remains absolutely prohibited (§0) |
| `docs/PORTFOLIO_RESEARCH_ROADMAP.md:32-36`, `:64-66` | amend both bullets: the boundary is superseded **by ADR 0003 for `signalforge.execution` only, paper endpoints only, nothing armed by default**; every other module keeps the prohibition |
| `ARCHITECTURE.md:38-40` (V1 non-goals) | amend "No brokerage connection of any kind" / "No order execution … no OMS" to name ADR 0003 and the paper-only scope |
| `ARCHITECTURE.md:64` (S1 row) | restate S1 as "no brokerage surface **outside `signalforge.execution`**", add S15a/S15b rows, and **fix the stale test paths** in the S1/S2/S3 rows (§1.2) |
| `README.md:17-19` | amend the unconditional promise |
| `DISCLAIMER.md:9-13` | amend "**No orders are ever placed.**" — this is the single most-read promise in the repo and the one a reader is most entitled to rely on |
| `docs/METHODOLOGY.md:3-4` | amend |
| `docs/CAPABILITY_MATRIX.md` | add an execution row with the honest status (disabled by default, paper only, nothing armed) |
| `src/signalforge/options/__init__.py:1-11` | **new in rev 3.** FACT: the module docstring states "There is no options execution path anywhere in this package… Naked short options, uncovered calls, margin-dependent strategies, 0DTE alerting, **and spreads** are intentionally absent" — and decision 12 makes a short vertical **spread** the first structure (§14). Amend to state what remains true of *this package* (pure math + education simulators; no order path **in `signalforge.options`**) and to name ADR 0003 for where execution lives. This is **shipped code**, not a doc |
| `src/signalforge/cli.py:19`, `:22`, `:24`, `:275` | **new in rev 3.** FACT (re-read this pass), four user-facing help strings shipped in the binary: `:19` "Signal Forge — research/education only. **No trading.**"; `:22` "Paper-trading ledger (SIMULATED — **no order is ever placed**)"; `:24` "Manual CSV portfolio import — analytics only, **no broker contact**"; `:275` "Options data + education simulators (**no execution path**)". Each is an *unconditional* promise that an `execution` package makes false. Amend each to a scoped statement (e.g. `:22` becomes "SIMULATED — this ledger places no order"), never to silence |

**The "Research signal only — no order was placed" notice.** FACT: it appears on every alert and
candidate artifact (`docs/PORTFOLIO_RESEARCH_ROADMAP.md:55-57`;
`docs/CAPABILITY_MATRIX.md:49`; `README.md:91`). HYPOTHESIS: it is **not** deleted. It is replaced
**per record** by that record's **true execution status** — `no order was placed` remains correct
and remains printed for every artifact that did not produce one, which will be all of them until a
strategy is armed. A blanket removal would overstate what changed.

**The rule that keeps this list from going stale (HYPOTHESIS, hard, new in rev 3).** Amending eight
documents and leaving four shipped strings and one module docstring asserting the opposite is the
same failure this section exists to prevent — it is worse for being *in the binary*, where a user
reads it without opening the repo. **T9** (§19) therefore asserts mechanically that, once
`signalforge.execution` exists, **no module docstring and no CLI help string under `src/signalforge`
asserts an unconditional no-order / no-broker promise** (the scan is over the same
`iter_source_files()` walk the S1 test uses, matching the phrases this ADR falsifies). A scoped
statement passes; an absolute one fails.

**Ordering (HYPOTHESIS, hard): the §17 contract commit (I-E1) and this amendment commit both land
BEFORE a single line of execution code is written.** Map §7's Phase D exit criterion says the same:
"D6's ADR is approved by the operator in writing, and the amendment commit of §6.8 step 2 is
merged, before a single line of execution code is written."

---

## 19. Safety tests — T1 through T13

New file `tests/safety/test_s15_execution_boundary.py`, `pytestmark = pytest.mark.safety` (FACT:
the house pattern, `tests/safety/test_s1_no_broker_surface.py:15`; `make safety` runs only these,
`Makefile:76`). Written in I-E1.

| # | Assertion | Closes |
|---|---|---|
| **T1** | No module under `src/signalforge/{llm,agents,app,research,alerts,sf1000,backtest,paper,portfolio}` reaches `signalforge.execution` — **transitively**, not by direct edge. An AST scan mirroring `_imported_names` (`test_s1_no_broker_surface.py:50-57`) but matching the full dotted prefix builds the intra-package import graph and asserts **no path** from any of those packages to `signalforge.execution`. Rev 2 specified a direct-edge scan, which has the exact blind spot `allow_indirect_imports = true` would introduce (§17.2) | the S15b direction, tested as well as contracted |
| **T2** | `OrderIntent` is constructible **only** under all seven §5 preconditions. Includes: a **manually accepted** `PaperTrade` (`actor='local-user'`) is refused; a **gate-FAILED** candidate is refused; a candidate with `risk_dollars is None` is refused (the `ledger.py:156-159` fallback path) | §5 |
| **T3** | `client_order_id` is **stable across retries** for the same `(paper_trade_id, leg signature)`, and differs across different structures on the same paper trade | §5.4, A1 |
| **T4** | `signalforge.execution.EXECUTION_DISABLED_BY_DEFAULT is True`; importing every `signalforge.execution.*` submodule in a clean interpreter performs no network call and reads no env credential | §2 |
| **T5** | No brokerage host literal, and no HTTP client construction pointed at one, exists anywhere under `src/signalforge` **outside `src/signalforge/execution/brokers/`**; `protocol.py` and `intents.py` import no HTTP client and no vendor package | replaces the mechanical protection D6-A gives up (§3) |
| **T6** | `is_paper()` **fails arming** when the account id in a stubbed broker response does not match `armed_strategy.broker_account_id_expected` — asserted for `paper_reference` **and** for any vendor adapter | §13 |
| **T7** | No credential literal anywhere in `src/signalforge` (complements `make secrets`, `Makefile:80`, and `tests/safety/test_s5_no_secret_leak.py`) | §16 |
| **T8** | `UPDATE` and `DELETE` on `execution_event` both fail **at the database level**, in the shape of `tests/db/test_s9_paper_trade_triggers.py` — the triggers, not an ORM exception class, are the mechanism (§15) | §15, §16 |
| **T9** | Once `signalforge.execution` exists, **no module docstring and no CLI help string** under `src/signalforge` asserts an unconditional no-order / no-broker promise (scan over `iter_source_files()`, matching the phrases §18 amends). A scoped statement passes; an absolute one fails | §18 |
| **T10** | Every `execution_event` whose `adapter_name = 'paper_reference'` is **excluded** from the decision-10 closed-trade count, from `strategy_health`, from expectancy, and from every promotion gate — asserted against a fixture where the simulator's fills would otherwise satisfy the arming precondition | §3.1 |
| **T11** | A credential read through `credentials.py` appears in **no log record and no `execution_event` payload**: structlog output is captured around a stubbed Keychain/env reader returning a known sentinel, and the sentinel appears nowhere. Complements T7, which can only see source literals | §16 |
| **T12** | The **only** static import path into `signalforge.execution` from anywhere in `src/signalforge` is `signalforge.cli`. Transitive, computed from the same graph as T1. Also asserts `signalforge.scheduler` and `src/signalforge/app/**` contain **no** reference to `signalforge.execution` (§2) | §2, §17.2, Q11 |
| **T13** | The four added `BANNED_CALL_SUBSTRINGS` (`place_combo(`, `cancel_all(`, `.place(`, `order_status(`) are allowlisted for **exactly** `src/signalforge/execution/` and nowhere else: a planted `cancel_all(` under `src/signalforge/app/` fails the scan | §17.1b |

**Placement.** T1–T7 and T9–T12 live in `tests/safety/test_s15_execution_boundary.py`; T8 lives in
`tests/db/` beside the existing trigger test; T13 lands with the §17.1b change to
`tests/safety/test_s1_no_broker_surface.py`. All carry `pytestmark = pytest.mark.safety` except T8,
which follows the `tests/db/` convention of its neighbour.

**All existing gates re-run after every integration** (FACT: `make check` = `lint test`,
`Makefile:88`; `make lint` = Ruff + Black --check + mypy + import-linter, `Makefile:65`;
`make safety`, `Makefile:76`; `make secrets`, `Makefile:80`).

---

## 20. Regulatory and market-structure facts to disclose

**Deliberately split in two.** Mixing factual claims about regulation with design requirements
inside a section headed "not advice" is what makes such a section read as advice.

### 20.1 Facts the operator must verify with their own broker — general information only

- **PDT.** In a U.S. margin account, a pattern-day-trader designation attaches at 4+ day trades in
  5 business days where those trades are a significant share of activity, and carries a **$25,000**
  minimum equity requirement; falling below it restricts day trading. Cash accounts avoid PDT but
  are bound by settlement instead.
- **Options approval levels.** Brokers tier options permissions. Covered calls and cash-secured
  puts typically sit at a lower tier; **spreads require a higher tier**; naked/uncovered requires
  higher still and is out of scope here by design. FACT: decision 3
  (`DECISIONS_2026-09-12_options_execution.md:13`) records that the design **assumes Level 2**
  (defined-risk spreads, cash-secured puts, covered calls) and that the actual level is
  **operator-only** — nothing is armed for real money until it is confirmed.
- **Margin.** Defined-risk spreads are typically margined at max loss; cash-secured puts at full
  strike value; covered calls against the shares. Requirements differ by broker and can change
  intraday.
- **Settlement.** U.S. equities settle T+1; options settle T+1. In a cash account, using unsettled
  proceeds can cause a good-faith violation. In a margin account this is generally not a constraint
  but interest and maintenance rules apply.
- **Assignment.** American-style options can be assigned early, most commonly on short calls before
  an ex-dividend date. FACT: `OptionContract.exercise_style` defaults to `'american'`
  (`src/signalforge/db/models/market.py:254`).
- **Early close.** U.S. equity options stop at 13:00 ET on early-close sessions.

**This ADR does not advise on any of the above, does not recommend an account type, does not
recommend an approval level, and does not recommend a position size.**

### 20.2 OMS requirements derived from them — design, and they belong with §7's limits

| Requirement | Where enforced |
|---|---|
| **Round-trip counter.** The OMS counts and displays round trips per rolling 5 business days and **refuses** to submit an order that would cross the operator-set threshold. The threshold is an operator input; the counting and the refusal are the system's job. | §7 L3, `execution_limits.round_trips_per_5_sessions_max` |
| **PDT equity read live.** `pdt_equity_threshold` is compared against `adapter.account()` equity **each cycle**, not against a constant. | §7, §10 |
| **Approval-level assertion.** The arming ceremony requires the operator to assert their options approval level; a spread structure cannot be armed at a level that does not permit spreads. The adapter surfaces the broker's own rejection **verbatim** and does **not** retry. | §12 step 3, §8 rule 4 |
| **Margin reconciled, never modelled authoritatively.** The broker's buying-power figure is authoritative; divergence halts. | §10 |
| **Assignment divergence disclosed at arm time.** The backtest approximates early assignment away, biased in the strategy's favour; the arming record says so. | §12 step 3(i) |
| **Early-close sessions block by default.** | §11 |
| **AM-settled cash index options excluded by allowlist, asserted per intent.** | §11 |

---

## 21. Phase V drills — the exact list, against `paper_reference` first

FACT (map §7 Phase V): each drill below must pass against `brokers/paper_reference.py` (local,
deterministic, **no network**) before the vendor paper adapter is written, and then be repeated
against the vendor paper endpoint with **zero** armed strategies.

| # | Drill | Pass condition |
|---|---|---|
| V1 | **Kill switch engaged with an open position** | **the cycle body executes** — `execution_guarded` takes the protective branch and writes a `CYCLE_PROTECTIVE` `execution_event` and a `JobRun` (this is the sub-condition rev 1 could not meet at all, §2); `may_open` blocked; **`may_close` still works** and a protective close submits; the drain-then-`cancel_all`-then-reconcile sequence runs in order (§8) |
| V2 | **Dead-man lapse** | opening blocked, auto-disarm fires, **no auto-liquidation occurs**, `may_close` remains open (§9) |
| V3 | **Reconciliation divergence** | a broker position with no matching `client_order_id` halts opening, disarms, alerts, and is **not** auto-corrected (§10) |
| V4 | **Reconciliation staleness** | with no fresh reconciliation inside `max_reconciliation_age_s`, `may_open` blocks exactly as a dead-man lapse does (§10) |
| V5 | **Duplicate `client_order_id`** | the second `place()` with the same id produces no second fill (A1) |
| V6 | **Post-timeout non-duplication** | after a simulated timeout, `order_status()` is queried **before** any resubmission; a broker that already knows the id produces **no** resubmission (§8) |
| V7 | **`SUBMITTING` with no outcome → `UNKNOWN` → blocked arming** | a killed process mid-submission leaves a durable `SUBMITTING` row; the next cycle promotes it to `UNKNOWN`; arming that strategy is **refused**; a retry does **not** clear it; only reconciliation + operator acknowledgement does (§6) |
| V8 | **Combo partial fill** | a proportional partial is `PARTIAL` and reconciles; a **by-leg** partial halts, alerts, refuses all further opening, and routes the unwind through `may_close` only (§14) |
| V9 | **`is_paper` account-id mismatch** | a stubbed response whose account id differs from the armed record **fails arming** and fails every subsequent submission (§13) |
| V10 | **Clock/calendar disagreement** | `adapter.clock()` disagreeing with `data/options_calendar.py` blocks (§11) |
| V11 | **Intent expiry** | an intent past `expires_at` is refused, not warned (§5.4) |
| V12 | **Early-close session** | submission refused unless the calendar's early-close handling is explicit and the adapter clock agrees (§11) |
| V13 | **Round-trip threshold** | the order that would cross the rolling-5-session threshold is refused (§20.2) |
| V14 | **Manual-accept refusal, end to end** | a `PaperTrade` accepted via `signalforge paper accept` (FACT, re-read this pass: `cli.py:1261` → `:1267`; rev 2 still carried `:1159` here) produces **no** intent (T2, §5) |
| V15 | **Crash mid-submit → `UNKNOWN` → cleared, end to end** | kill the process between the durable `SUBMITTING` write and the network call; on restart the row promotes to `UNKNOWN` (§6 rule 3), auto-disarm fires (§12 step 7), and the operator then **clears the `UNKNOWN` and closes the position with NO manual DB write at any step** — the `is_paper` proof reads the disarmed `armed_strategy` row (§13 rule 4b) and `build_close_intent` requires no armed row (§5.2b) |
| V16 | **Close cannot be used to open** | a PROTECTIVE_CLOSE intent that is net-reducing but **increases any single leg** is refused (C-P3); a close against a broker position with **no originating `execution_event`** is refused as a §10 divergence, not executed (C-P2) |
| V17 | **Shared-account refusal at arm time** | arming is machine-**refused** when `adapter.positions()` or `adapter.open_orders()` returns anything at all, and a second arming against an already-armed `broker_account_id_expected` is refused by the partial UNIQUE index (§10, §16) |
| V18 | **Disarmed strategy with an open short leg** | disarm a strategy holding an open short option leg, then prove a **protective close still constructs and still submits** — no `armed_strategy` row, no `Candidate`, no `PaperTrade`, kill switch engaged, dead man lapsed. This is the drill that proves the headline promise ("the kill switch never blocks closing") rather than asserting it (§5.2b, §7) |
| V19 | **The app process never carries the execution job** | with `execution_enabled` True, the app's embedded-scheduler path **refuses to start** and names the CLI worker (§2); with it False, the app starts exactly as it does today and the job list is byte-identical; no module under `src/signalforge/app/**` references `signalforge.execution` (T1, T12) |

**Then, and only then:** one armed strategy, at the smallest viable size, for a stated observation
window, with **daily reconciliation review** by the operator.

---

## 22. Consequences

**Positive.**

- The "no LLM ever decides an order" guarantee gains **structural** enforcement (S15b + the S14
  amendment) rather than resting on convention.
- The manual-accept hole (§5.1) — which exists **today** and is independent of execution — is
  closed by an indexed `PaperTrade.actor` column that also makes the equity paper stream auditable.
- The `may_open`/`may_close` split makes the kill switch protective in the one scenario where the
  previous design would have been actively dangerous (§7).
- The vendor-SDK-free decision (D6-A) means **zero** relaxation of S1, Ruff banned-api, or the
  15-name import scan — and the call-string scan is **extended** by four entries (§17.1b) rather
  than left inert, so the change to the safety suite is net *more* searching in both directions.
- The four unconditional promises shipped inside the binary (`cli.py:19`, `:22`, `:24`, `:275`) and
  the `options/__init__.py` docstring are amended in the same commit as the documents, and **T9**
  keeps them amended. Rev 2 amended the docs and left the strings.

**Negative, and stated rather than buried.**

- The three **name**-based denylists stop being a *mechanical* barrier to a brokerage surface built
  on `httpx`. §19 T5 and the four added call substrings (§17.1b) replace that barrier with
  **string scans over source** — a **weaker** kind of check than an import-graph proof, and one
  that a rename defeats. This is the single largest safety cost of D6-A and the reviewer should
  weigh it deliberately. The import-graph proof that *does* survive is S15a/S15b + T1/T12, and it
  constrains who may reach the execution package rather than what that package may call.
- The execution cycle runs **only in the CLI-launched worker** (§2). An operator who runs the
  worker from the app process gets no execution job at all — which is fail-safe for submission and
  **not** fail-safe for protection: no heartbeat, no reconciliation, no drain. The app refuses to
  start its embedded scheduler while `execution_enabled` is True precisely so this cannot be
  discovered during an incident, but it is a real operational constraint that did not exist before.
- `DISCLAIMER.md:9` ("**No orders are ever placed.**") becomes conditional. Any reader who relied
  on it — including the operator's future self — must now read a scope qualifier instead of an
  absolute.
- The execution layer adds a second consumer to `data/options_calendar.py` before that module
  exists, so D2's design is now constrained by a module that is not yet written (§11).
- `execution_event` and `armed_strategy` add write traffic to the **same SQLite file** the live
  probation worker uses. §2's write-intent discipline is what keeps that safe; it is a rule, not a
  mechanism, and it must be honoured in every code path.

**Unchanged and re-affirmed.** No real-money endpoint. Nothing armed by default. No LLM on any
order path. No automatic liquidation, no automatic reconciliation repair, no automatic retry of a
rejection. No naked short options, no leg-by-leg submission, no 0DTE. No credential acquisition,
storage, rotation, or logging by the system. R1–R10 unchanged; no promotion gate weakened
anywhere in this document.

---

## 23. Open questions

| # | Question | Blocks | Status |
|---|---|---|---|
| **Q1** | If the operator's chosen broker cannot be reached by documented REST and **requires an SDK**, D6-A fails and the §17.1 carve-out becomes necessary. The pre-agreed form is fixed (path-prefix allowlist for exactly `src/signalforge/execution/brokers/`, no name removed from any list, S1 + Ruff + test changed in one reviewed commit). Confirm Alpaca's paper trading API is fully reachable over documented REST before I-E5. | I-E5 | **operator + a vendor-doc check; no network call was made in this pass, so every vendor-API claim in this ADR is unverified** |
| **Q2** | Operator's actual **options approval level** (decision 3 remains operator-only). The design assumes Level 2. | arming any options structure | operator |
| **Q3** | Confirm or change the **capital limits** of decision 4 (§7). All ten numbers. | arming; `execution_limits` seed row | operator |
| **Q4** | Confirm the **broker** (Alpaca paper assumed, decision 2) and place its paper API keys in env or Keychain **yourself**. | I-E5 only | operator |
| **Q5** | The options paper account is sized **$25,000** (decision 13) and the PDT threshold is **$25,000** (decision 4). They meet exactly, so any loss puts the account below the threshold. Confirm this is intended, or change one of the two numbers. | `execution_limits`, §7 L3 | operator |
| **Q6** | `execution_stale_after_s` grid centre 90s mirrors `WORKER_STALE_AFTER_S` (FACT, re-read this pass: `scheduler.py:610-611`; rev 2 still carried the map's `:508` in this row, which is inside `_intraday_scan_spec`'s docstring). Is 90s right for an order-submitting loop, or should the dead man be tighter than the research worker's? | I-E4 | orchestrator + operator |
| **Q7** | The bounded **drain timeout** in §8 step 3 has no proposed value. Too short manufactures `UNKNOWN`s; too long delays the kill switch. | I-E4 | orchestrator |
| **Q8** | `execution_limits` is specified as "one active row, versioned by supersession". Is a superseded row ever read again (for auditing a past order), and if so does an order carry its limits row id? **Proposal: yes — add `execution_limits_id` to `execution_event`.** | I-E2 schema | orchestrator |
| **Q9** | Whether the **buying-power divergence tolerance** (§10) is absolute dollars, a percentage, or both. A tolerance of zero will halt on rounding. | I-E4 | orchestrator |
| **Q10** | §12 step 2 requires ≥20 closed paper trades with non-negative expectancy "under the health monitor". FACT: `strategy_health` has **0 rows**; the exact health-monitor field the CLI reads is not yet named. | I-E4 CLI | orchestrator, once D3's health surface is fixed |
| **Q11** | Whether `signalforge.cli` staying **out** of S15b's source list (§17.2 note 2) is accepted — **and whether the exemption's transitivity is accepted with it**. `allow_indirect_imports` is deliberately **not** set (§17.2), so the exemption is not merely "the CLI may import execution": it is "anything that imports `signalforge.cli` inherits the exemption's target". FACT (re-read this pass): **nothing in `src/signalforge` imports `signalforge.cli` today** (`grep -rn 'signalforge\.cli'` over `src/signalforge`, excluding `cli.py` itself, returns zero hits), so the exemption is currently a leaf and T12 asserts it stays one. `signalforge.scheduler` is **no longer** an exemption at all — under §2's rev 3 rule it never imports execution, and the app never does either. | I-E1 | **operator review of this ADR** |
| **Q12** | The map's §6.8 step 3 asked whether to narrow S1 via `ignore_imports` or replace it with an S1a+S15 pair. **This ADR answers: neither — S1 is untouched** (§17.1). Confirm that answer, since it departs from the map's wording. | I-E1 | **operator review of this ADR** |

---

## Appendix — claim ledger for this document

Every FACT above traces to one of: `src/signalforge/{paper,execution-absent,db,config,research,data,options}/**`
as cited inline; `tests/safety/test_s1_no_broker_surface.py`; `tests/support.py`; `pyproject.toml`;
`Makefile`; `ARCHITECTURE.md`; `docs/PORTFOLIO_RESEARCH_ROADMAP.md`; `README.md`; `DISCLAIMER.md`;
`docs/METHODOLOGY.md`; `docs/CAPABILITY_MATRIX.md`; `docs/PAPER_PROBATION_ACTIVATION.md`;
`docs/decisions/0002-phase1-stack-simplifications.md`;
`docs/research/OPTIONS_EXECUTION_PROGRAM_MAP.md`;
`docs/research/DECISIONS_2026-09-12_options_execution.md`; or one of these read-only SELECTs run
against `data/signalforge.sqlite` during this pass:

```sql
select count(*) from paper_trade;                                      -- 0
select count(*) from paper_position;                                   -- 0
select count(*) from strategy_health;                                  -- 0
select id,name,initial_cash,cash from paper_account;                   -- 1|default|30000|30000
select s.name, v.version, v.status from strategy_version v
  join strategy s on s.id = v.strategy_id order by s.name;             -- 3 PAPER_APPROVED, 3 EXPERIMENTAL
select name from sqlite_master where type='table'
  and (name like '%exec%' or name like '%arm%' or name like '%order%');-- paper_order only
```

**Explicitly unverified, and must be resolved before it is relied on:** every vendor broker-API
claim (no network call was made in this pass — Q1); whether Alpaca's paper endpoint supports
native atomic multi-leg combo orders and by-id order lookup (A2 and A4 are hard eligibility
conditions, and an adapter that cannot meet them is ineligible); the exact early-close times and
approval-level tiers of the operator's broker (§20.1 is general information only).

Everything not labelled FACT is HYPOTHESIS: a proposal, not a finding.

---

## Appendix — Judge responses (rev 3)

Two adversarial review passes were run against this ADR: a **legitimacy/evidence** lens (11
defects) and a **safety/feasibility** lens (8 defects). Every defect was re-verified against the
working tree and the live DB in this pass before being acted on. Nothing below was taken on the
reviewer's word.

**Where each stands.** "Carried" = the defect was already closed in the draft this revision
started from and was re-verified here; "fixed in rev 3" = closed by this revision; "rejected" =
verified and declined, with the reason.

| Defect (lens) | Disposition | Where |
|---|---|---|
| Protective-close path unbuildable under one factory (L) / `may_close` unreachable (S) | carried, **and newly drilled** — V18 now disarms a strategy holding an open short leg and proves the close still submits, which is the drill the reviewer asked for and which rev 2 did not have | §5.2b, §7, V15/V16/V18 |
| P6 is equity-only, so the program's first structure could not produce an intent (L) | carried | §5.3b |
| S15b fails on an indirect chain; the cheap fix guts it (L, S) | **fixed in rev 3, and the reviewer's own option (b) is rejected** — see below | §2, §17.2, T1/T12, Q11 |
| Five wrong `scheduler.py` / `cli.py` citations (L) | carried for most; **three stale ones survived into rev 2 and are fixed here** (Q6 `scheduler.py:508`, V14 `cli.py:1159`, §11's `calendar.py` range), plus three the reviewers did not catch (`:150`→`:151`, `killswitch.py:9-13`→`:9-12`, "four `data.adapters.*`"→**five**) | citation provenance (rev 3), §11, Q6, V14, §17.2 |
| Execution-timing parameters are outcome-tunable with no pre-registration (L) | carried | §7b |
| `paper_reference` has no fill rule and its output is not fenced off (L) | carried; **T10 is now actually listed** in §19 (rev 2 referenced it from §3.1 and never defined it) | §3.1, T10 |
| No cost-model feedback record (L) | carried | §4.2 |
| Arming record carries no sealed-look / pre-registration binding (L) | carried | §12 step 1, §16 |
| §18's amendment commit is incomplete (L) | **fixed in rev 3** — `options/__init__.py` and the four shipped `cli.py` help strings added, the docstring quoted whole (including the "**and spreads**" clause rev 2 cropped), and **T9** added so the strings cannot drift back | §14, §18, T9 |
| The call-string scan is left inert against the new surface (L) | **fixed in rev 3** — `BANNED_CALL_SUBSTRINGS` gains four entries under a path-prefix allowlist for exactly `src/signalforge/execution/`, asserted by **T13** | §17.1, §17.1b, T13 |
| Shared-account risk is an acknowledgement, not a check (L) | carried | §10, V17 |
| Kill switch makes the execution cycle a no-op via `scheduler.guarded` (S) | carried; **V1 now asserts the cycle body executed** with the switch engaged and wrote `CYCLE_PROTECTIVE` | §2, V1 |
| "Notional" undefined for a combo; limits do not reconcile with the map (S) | carried | §4.1, §7 |
| Kill-switch engagement has no delivery path to the OMS (S) | carried | §8, §12 step 3(iv) |
| `UNKNOWN` deadlock; `is_paper` loses its expected account id after disarm (S) | carried | §6 rule 5, §13 rule 4b, V15 |
| Append-only claim cites the wrong mechanism; no test (S) | carried; **T8 is now actually listed** in §19 | §15, §16, T8 |
| Keychain reader and cycle cadence unspecified (S) | carried; **T11 is now actually listed** in §19 | §2, §16, T11 |

### Accepted with a change to the remedy

- **`allow_indirect_imports`.** The safety lens offered two remedies: (a) register the cycle with no
  static `scheduler → execution` edge, or (b) set `allow_indirect_imports = true` on S15b plus a
  compensating test. **(b) is rejected.** Setting it would degrade S15b to direct edges only, which
  is precisely the blind spot that makes the "no LLM decides an order" guarantee unenforceable at
  the layer that submits orders; a compensating *test* is not a substitute for the contract the
  operator is being asked to approve. This ADR takes (a), states that the flag is deliberately
  unset, and adds the verification the flag's absence needs: `make lint` against a stub
  `execution/__init__.py` before I-E1 is declared done (§17.2).
- **The Keychain reader.** The safety lens asked for "a dependency + pinned version, **or** the
  precise `security find-generic-password -w` invocation". The dependency route is **declined**: a
  new dependency to read one string enlarges the supply chain for no gain. §16 specifies the
  invocation, the `SecretStr`-at-the-boundary rule, the never-to-structlog rule, and **T11**.
- **`.place(` rather than `place(`** in §17.1b: a bare `place(` matches `.replace(` and would have
  made the addition red on day one for an unrelated reason. Verified: all four added substrings
  have **zero** hits under `src/signalforge` today.

### A defect the reviewers did not find, introduced by the fix for the one they did

Rev 2's answer to the S15b problem was to inject the job spec from "the two call sites that build
the worker (`cli.py:2347`, `app/main.py:50`)". FACT (re-read in this pass): `app/main.py:50` is
**inside `signalforge.app`**, which is in S15b's **own source list** — so the remedy specified a
**direct** S15b violation while the surrounding section argued for S15b. Rev 3 narrows the
injection to `signalforge.cli` alone, states the operator-visible consequence (the execution cycle
exists only in the CLI-launched worker, so an app-started worker has no heartbeat, no
reconciliation and no drain), makes the app refuse to start its embedded scheduler while
`execution_enabled` is True, and drills it as **V19**. Recorded here because it is the second time
in this document's history that a fix for the import graph created a worse edge than the one it
closed.

### Rejected

- **Nothing in either defect list was rejected as wrong.** Two *remedies* were declined and
  replaced (above), and one reviewer instruction was taken further than asked: rather than "state
  which citations were re-read versus inherited from the map", **no citation in this document is
  inherited from the map at all**. Where the map and the working tree disagree — the map's
  `cli.py:1158-1165` for `paper_accept` — the working tree wins (`:1261` → `:1267`) and the map is
  flagged for correction by whoever owns it. This document does not edit the map; correcting it is
  outside this workstream's single-output rule.
- **One reviewer framing is narrowed rather than adopted:** the legitimacy lens described C-P2 (a
  close must trace to an originating `execution_event`) as absent from its own proposed close
  precondition set. It is kept, deliberately and as a *stricter* rule: the OMS will not flatten a
  position it never opened. Such a position is a §10 divergence — it halts, alerts, and the
  operator closes by hand at the broker. Letting the system close a foreign position would be an
  unreviewed order, which §10 forbids everywhere else.

### What this revision did not change

No gate, threshold, contract, test, or precondition was weakened anywhere in this pass. Every
change above is additive: three amendment targets, five safety tests (T9–T13), five drills
(V15–V19), four call-string denylist entries, and six citation corrections. R1–R10 are unchanged;
sealed-look accounting for the options family still starts at k=0 by construction; no LLM is on any
order path; nothing is armed by default; and the kill switch still blocks opening and never blocks
closing — which V18 now proves rather than asserts.
