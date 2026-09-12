# Limited U.S. Equity Paper-Probation Trial — Activation Preparation

**Status: prepared, NOT activated (2026-09-10).** Alerts OFF, every alert type OFF,
paper probation OFF, auto-simulation OFF, no Discord message sent. Research /
paper-trading only: no order is ever placed; every candidate and alert carries
"Research signal only — no order was placed."

## Eligible strategy versions (and nothing else)

| Strategy | Version | strategy_version_id | Approved scope (five-part, exact) |
|---|---|---|---|
| `trend_continuation.short_swing` | 0.1.0 | 2 | dataset snapshot **#3 `universe_24_ex_meta`** (24 symbols, META excluded) · source `massive` · config_hash `11b54aee64db…` · spec_json_hash `2ed9743170bd…` |
| `relative_strength.medium_swing` | 0.1.0 | 5 | dataset snapshot **#3 `universe_24_ex_meta`** · source `massive` · config_hash `11b54aee64db…` · spec_json_hash `dfe696b662dd…` |

Enforcement: a candidate can only be alerted when `Strategy.status == PAPER_APPROVED`
**and** its `ScanRun` matches one of that version's passing evaluations on all five
parts (`research/approval_scope.py::scan_scope_matches`); otherwise it is logged as
`NO TRADE — approval does not apply to this dataset.` Only the scheduled
`approved_scope_scan` (end of `daily_eod_update`, gated on fresh, complete data)
produces matching candidates. Universe-pipeline scans and any other scan cannot.

## Gates retained (unchanged)

| Gate | Where |
|---|---|
| Stale data | `alerts/dispatch.py` (any stale feed ⇒ no candidate alerts); `research/approved_scope_scan.py::data_readiness` (source feed fresh, last daily ingest ok <24 h, newest bar ≤5 days, ≥90 % coverage) |
| Liquidity, event window, missing/short history | `research/scan.py` exclusions (`min_price`, `min_avg_dollar_volume`, earnings window) |
| Cost / slippage | `Candidate.slippage_assumption_json`; `paper/ledger.py` simulated fill with spread + slippage |
| Portfolio risk / concentration | `risk/engine.py::size_position`, `risk/portfolio.py::exposure_report`, `ResearchConfig.risk` limits |
| Quiet hours, 2-per-day cap, briefing once/day, dedupe | `alerts/dispatch.py::run_alert_cycle` |
| Kill switch | every job/action (`killswitch.ensure_not_engaged`) |

## Auto-simulation is impossible

There is **no scheduled or automatic caller** of paper acceptance anywhere in
`src/signalforge` (verified by `tests/paper/test_activation_guards.py::test_nothing_in_the_scheduler_calls_automatic_acceptance`).
The only acceptance paths are the manual dashboard action and the CLI. The guard
`paper/ledger.py::assert_auto_simulate_allowed` documents and enforces what any
future automatic path would need: setting ON **and** every quality gate passed
**and** a U.S. stock/ETF instrument **and** `PAPER_APPROVED` version **and** an
exact scope match — options, futures, forex, unapproved strategies, and scope
mismatches raise `AutoSimulateForbidden`.

## Evidence on every paper trade

`PaperTrade.signal_snapshot_json` (immutable — invariant S9 triggers reject UPDATE/DELETE)
now holds the complete candidate record: entry/stop/target/time-stop, reward:risk,
calibrated probability, sizing, liquidity, slippage assumption, event risk, portfolio
context, data freshness, ranking, every failed gate and failure reason, the exact scan
scope (scan id, source, dataset snapshot, config hash), the strategy version and live
parameter hash, whether the scan matched the approved scope, and the code SHA.
`why_might_fail` carries the failure rationale text.

## Pending settings (exact) — applied only by the activation action

| Setting | Now | Pending |
|---|---|---|
| `alerts_enabled` | False | **True** |
| `paper_probation_enabled` | unset (False) | **True** |
| `alert_type_enabled:candidate` | False | **True** |
| `alert_type_enabled:system_health` / `data_issue` / `daily_briefing` | False | stays **False** |
| `auto_simulate_qualified_signals` | False | stays **False** |
| `max_alerts_per_day` | 2 | 2 (re-asserted) |
| Discord | webhook configured, nothing sent | candidate-only delivery once the above are on |

## Dry-run result (2026-09-10 12:2x UTC, `signalforge paper-probation-dry-run`)

```
DRY RUN — nothing was changed, logged, or sent
assumed settings: alerts_enabled=True, paper_probation_enabled=True,
                  alert_type_enabled:candidate=True, max_alerts_per_day=2
channels configured: local, discord · quiet hours now: True · candidate alerts sent today: 0
  blocked  daily_briefing "Daily research briefing — 2026-09-07" — alert type daily_briefing is off
would send: 0
```
No qualified candidate exists on the latest research scans (all 24 NO-TRADE on
both approved horizons), so nothing would go out today even if activated.

## Activation preconditions (live, `signalforge paper-probation-activate` without `--yes`)

OK: exactly two approved versions · exact scopes · non-candidate types OFF · auto-sim
OFF · Discord configured · worker running · kill switch released · approved-scope
readiness. **FAIL: daily bars current** (newest 2026-09-08 vs expected 2026-09-09) —
the launchd worker is still on the pre-fix adapter (`de7e414` fetches the day's
closed bar from 17:30 ET); it clears after `launchctl kickstart -k
gui/$(id -u)/com.signalforge.worker` and the next 17:30 ET run. The activation
command refuses until every precondition is green.

## Remaining data limitations

- Research universe is 24 symbols (`ex_meta`); no survivorship-free history; no
  delisted names; adjustments as-of-fetch on the bulk universe (not used here).
- NBBO spread not licensed — costs use a nominal spread + slippage model.
- Exchange holidays not modelled (freshness shows "1 behind" on a holiday).
- Calibrated win probabilities are provisional (small paper sample).
- 0 live paper trades yet for either strategy — probation evidence starts at activation.

## Independent adversarial review (2026-09-10) — findings and fixes

A read-only review agent tried to refute every safety claim above. It found no
path by which an agent writes trading state, sends anything, reaches the network,
or activates alerts/probation/auto-sim/options/forex. Four hardening items were
raised and fixed before commit:

| # | Where | Finding | Fix |
|---|---|---|---|
| 1 | `llm/guards.py` | digits inside evidence timestamps (`…T18:45:00`) could "ground" a fabricated `45%`/`18x` in an LLM narrative | timestamps skipped by key (`*_at`, `as_of`, `*_date`, …) and by shape (ISO-8601, `datetime`/`date`); regression tests added |
| 2 | `alerts/dispatch.py` | the real send cycle read `alerts_enabled` / `max_alerts_per_day` / per-type switches through the same helper the dry-run overlay uses | real cycle reads persisted settings only and fails fast (`RuntimeError`) if entered under an overlay; test added |
| 3 | `docs/AGENT_ROLES.md` | overstated S14 as forbidding all of `data.adapters` | doc now lists the five concrete adapters the contract forbids |
| 4 | `scheduler.py` | disabled `agents_daily` took the SQLite write lock before checking its flag | flag read under a plain read session first |

## The single final activation action

```bash
uv run signalforge paper-probation-activate --yes
```
It re-checks every precondition, refuses on any failure, and otherwise applies the
four pending settings in one audited transaction (`AppSettingHistory` +
`AuditLog paper_probation.activated`). Reverse with
`uv run signalforge paper-probation-deactivate`. Not run.


## Operator authorization — 2026-09-10 (supersedes the "kept OFF" statements above)

The operator authorized, in chat: alerts ON, Discord delivery ON, the paper
probation lifted (activation to proceed), and **automatic SIMULATED paper
acceptance ("auto-simulation")**. Paper only, as before: no brokerage
integration, no order placement, no LLM decisions.

| Item | State | How |
|---|---|---|
| Discord webhook | verified — one test message delivered (HTTP 204) | `signalforge notify test-discord --yes`, audited `notify.discord_test` |
| `auto_simulate_qualified_signals` | **ON** | audited `auto_simulation.authorized` (AppSettingHistory + AuditLog + file audit) |
| `auto_simulate_max_per_day` | 2 | same change |
| Activation (`alerts_enabled`, `paper_probation_enabled`, candidate alerts, cap 2) | **DONE 2026-09-10 20:00 UTC** — `paper-probation-activate --yes`, all nine preconditions OK after the restarted worker's startup catch-up ingested the 9/9 bars | audited `paper_probation.activated`; the "auto-simulation is OFF" precondition became informational |
| Options / forex | **not possible yet** — no options or forex candidate pipeline, strategy, risk model, or forex data adapter exists; the guard still refuses anything that is not a U.S. stock/ETF | requires a separate build phase |

### How auto-simulation works (`paper/auto_simulate.py`)

Runs only inside `job_approved_scope_scan`, right after the approved-scope scan,
on that scan's own gate-PASSED candidates. Each candidate must pass
`assert_auto_simulate_allowed` (setting ON, every quality gate PASSED, U.S.
stock/ETF, PAPER_APPROVED version, exact five-part approved scope), then:

- kill switch engaged → nothing runs;
- candidate already has any PaperTrade decision → skipped (idempotent on retry);
- open paper position on the instrument → REJECTED with that reason;
- daily cap reached (all ACCEPTED trades today, manual included) → WATCH;
- guard refusal → REJECTED with the exact refusal reason frozen into the evidence;
- otherwise `accept_candidate` (same ledger call, fill model, and immutable
  evidence snapshot as a manual acceptance) + `AuditLog paper.auto_simulated`.
  Each decision commits on its own.

Tests: `tests/paper/test_auto_simulate.py` (inert unless ON; single accepted
trade with full evidence + audit; idempotent; guard refusal recorded immutably;
scope mismatch refused; daily cap and one-open-position rule; kill switch) and
`test_automatic_acceptance_has_exactly_one_guarded_entry_point`.


## Incident 2026-09-11 — approval scope silently un-matched by a config addition (fixed)

**What happened.** Adding the `agents` section to `ResearchConfig` on 2026-09-10 changed
the full-config hash that the five-part approval scope compares. Every live
approved-scope scan from that point (scan runs 34–39) carried config hash
`76500f3c…` while both approvals were granted under `11b54aee…`, so no candidate could
have matched an approved scope. It was masked because every scan produced 0 qualified
candidates. Found 2026-09-11 01:50 ET while verifying the pipeline-hardening merge.

**Fix (commit 0cc4cf4).** The scope hash now covers only the signal-shaping sections
(`ResearchConfig.SCOPE_HASH_FIELDS`); `full_config_hash` remains for audit. Both
approved versions were re-evaluated once with the worker stopped (05:53 UTC): both
PAPER_APPROVED again, sealed tests replayed as LOCKED rows (20 sealed tests before and
after; no new look), new scopes carry `fe365720…`, and `paper-probation-status` plus
the activation preconditions now report whether the live hash matches an approved
scope. Precondition list re-run: all OK.

**Exposure.** No trade, alert, or decision was affected (0 candidates in the window).


## Change 2026-09-11 — the approved-scope scan is per strategy version

**Why.** `research/approved_scope_scan.py` scanned every PAPER_APPROVED horizon on
ONE fixed dataset (the `ex_meta` variant → `DataSnapshot` #3, 24 symbols). Approval
scope is per `StrategyVersion`, so when `trend_continuation.medium_swing` v3 was
approved on `DataSnapshot` #11 (`research_150_massive_10y_presealed_sel`, 150 symbols)
while versions 2 and 5 stayed on #3, v3's approval could never have produced an
in-scope candidate — and therefore never an alert or an auto-simulated paper trade.

**Now.** Each PAPER_APPROVED version's **newest** approved scope decides its dataset.
Versions are grouped by `(dataset_snapshot_id, horizon, source)` and each group is
scanned once, over that snapshot's exact `symbols_json`, from that scope's single
recorded source. The live grouping is three scans:

| Snapshot | Horizon | Symbols | Strategy versions |
|---|---|---|---|
| #3 `universe_24_ex_meta` | SHORT_SWING | 24 | 2 (`trend_continuation.short_swing`) |
| #3 `universe_24_ex_meta` | MEDIUM_SWING | 24 | 5 (`relative_strength.medium_swing`) |
| #11 `research_150_massive_10y_presealed_sel` | MEDIUM_SWING | 150 | 3 (`trend_continuation.medium_swing`) |

**Gates.** Every gate above is retained. The data-readiness gate is now evaluated
**per approved universe** — a stale or incomplete 150-symbol universe blocks only its
own scans, never the 24-symbol one — and each block records its own `AUDIT_BLOCKED`
row naming the snapshot. A version whose newest scope could never match (no passing
evaluation, no snapshot, no single source, a missing/empty snapshot, or a universe
that disagrees with the snapshot) is skipped with an explicit reason rather than
scanned on another version's data. Each persisted run is verified against the approved
scope on dataset snapshot, source **and** universe; a mismatch raises loudly.
INTRADAY is excluded exactly as before, but now via the one flag
`research.intraday.operating_enabled` (default off) that `research/intraday_policy.py`
owns, rather than a hard-coded condition in the grouping.

**Surfaces.** `job_approved_scope_scan` is unchanged as a call, but now hands
`paper/auto_simulate.py` every group's `scan_run_id`. `/ops` and the activation
preconditions report "daily bars current" and "approved-scope scan data readiness"
once per distinct approved universe. The activation precondition
"exactly two PAPER_APPROVED strategy versions" is replaced by
**"every PAPER_APPROVED version has a live-matching scope"** — no count is hard-coded.


---

# Execution layer — arming ONE strategy on `paper_reference` (2026-09-12)

**This section is DOCUMENTATION ONLY. None of it has been run against the live
database. Nothing is armed, the execution layer is disabled, and `execution_limits` has
no row.** What changed on 2026-09-12 (W4a) is that it is now a **runnable** command
sequence rather than a description of one: every command below exists, and the whole
sequence is rehearsed end to end against a scratch database by
`tests/execution/test_activation_rehearsal.py`. If that test and this section ever
disagree, one of them is wrong and the suite says so.

It is the exact, reviewed command sequence for the D6 execution ADR's §12 ceremony
against the LOCAL `paper_reference` adapter — a simulator that opens no socket and
reaches no broker. It is a separate thing from the equity paper probation documented
above: that one produces SIMULATED fills in `paper_trade`; this one produces order
records in `execution_event` against an adapter.

Read `docs/PREREGISTRATION_execution_limits_v1.md` first. Arming is refused without it.

**As of W4c the cycle can SUBMIT.** Step 6 is no longer "start the worker and
watch"; with a strategy armed, the worker's cycle builds and submits orders on
its own. Read "The OPEN lane" below before running step 5, not after.

## Before anything: what is true today

| Fact | Where |
|---|---|
| `EXECUTION_DISABLED_BY_DEFAULT is True` | `src/signalforge/execution/__init__.py` |
| `research.execution.enabled` ships **False** | `config/research.py::ExecutionConfig` |
| Zero `armed_strategy` rows; zero `execution_limits` rows | the live database |
| The kill switch blocks **opening** and never blocks **closing** | §7, drilled as V1/V18 |
| Arming EXPIRES after at most 7 days, and there is no "resume" | `arming.ARMING_EXPIRY_DAYS` |
| `paper_reference` fills are **drill artifacts**, excluded from every gate | §3.1 rule 4, T10 |

## The four blockers found on 2026-09-12, and what closed them

Writing this sequence for the first time found four gaps that made it unrunnable. They
are recorded here rather than quietly fixed, because "the ceremony was prose" is the kind
of fact that has to stay visible next to the ceremony.

| # | Blocker as found | Closed by |
|---|---|---|
| B1 | **No supported interface set `research.execution.enabled`.** No CLI command, and the `/settings` form builds its overrides dict from a fixed field list with no `execution` section. The only path was a direct `set_setting(...)` call. | `signalforge execution enable --yes` / `disable --yes` (`cli.py`). It writes `research_overrides.execution.enabled` through `settings_store` — the same mechanism every other override uses — plus an `audit_log` row and a JSONL audit line. **Deliberately NOT added to the `/settings` form**: §12 keeps enabling and arming on the human-typed CLI, with no LLM and no app route on the path (S15b). |
| B2 | **No supported interface created an `execution_limits` row.** The model, the loader and the validator existed; the writer did not. With no row, `load_active_limits` returns `None`, `may_open` blocks on L0, and the ceremony fails. | `signalforge execution limits set --from-preregistration <id> --yes` (+ `limits show`). Values come from `execution/preregistration.py::PREREGISTERED_LIMIT_ROWS` and are checked **at write time** against the document on disk; a disagreement, a missing document, or a missing column refuses the write. |
| B3 | **The CLI could not build an adapter.** `_execution_adapter()` looked up `brokers.resolve_adapter`, which has never existed; the `AttributeError` was swallowed, the function always returned `None`, the ceremony took **no `is_paper` proof**, and it refused on S8 every single run. | `_execution_adapter(session, expected_account_id=...)` now calls the real `brokers.build_adapter` with the five required keyword arguments and swallows nothing. `execution arm` builds the adapter inside its own session, so the proof and the flat-account read are themselves on the `execution_event` record. |
| GAP | **`paper_reference` could never reconcile CLEAN while holding a position.** Its `positions()` returns the net book with no `originating_client_order_id` (a broker owes us none), §10 assigns the reconstruction to the OMS, and nothing in `src/` performed it — so `reconcile()` raised `FOREIGN_POSITION` after any fill, and the drills ran against a local wrapper that was not production code. | `execution/oms.py::attribute_positions`, called by `reconcile()`. It explains a broker position from the OMS's **own** `SUBMITTING` records (instrument, side, filled quantity), exactly, leg by leg — or not at all. It never repairs anything: an unexplained position stays `FOREIGN_POSITION`. Drill V0 now records the gap as **CLOSED**; V3's divergence path still fails correctly. |

What is still true, and is not a blocker: the operator's own three items in
`docs/PREREGISTRATION_execution_limits_v1.md` §4 (broker confirmation and paper keys, the
options approval level, and confirming the capital limits) are outstanding and are the
operator's, not the software's.

**One sharp edge to know about.** The `/settings` web form **replaces** the whole
`research_overrides` dict when it is submitted, so saving that form after enabling the
layer will silently set `execution.enabled` back to False (the form has no execution
field to write). That direction is fail-safe — it disables, never enables — but it is
surprising: re-run `signalforge execution enable --yes` and check `execution status`
after touching `/settings`.

## The sequence, in one block

Read the steps below before running any of it; this block is the index, not a substitute
for them. `<SVID>` is the `StrategyVersion.id`, and `<ACCOUNT>` is the account id read
**out of band** from the broker's own interface.

```bash
uv run signalforge execution drill --all                       # step 0: scratch DB only
uv run signalforge execution status                            # step 1: read-only
uv run signalforge execution enable --yes                      # step 2
uv run signalforge execution limits set \
  --from-preregistration PREREGISTRATION_execution_limits_v1 --yes   # step 3
uv run signalforge execution limits show                       # step 3: verify
uv run signalforge strategy-health                             # step 4: evidence, read-only
uv run signalforge execution arm <SVID> \
  --account-id 'PAPER-SIM-<ACCOUNT>' \
  --preregistration PREREGISTRATION_execution_limits_v1 \
  --adapter paper_reference \
  --structure-type equity \
  --approval-level 0 \
  --max-notional 1000 \
  --max-orders-per-day 10 \
  --expires-days 7 \
  --yes                                                        # step 5: prompts for the phrase
uv run signalforge execution status                            # step 5: verify ARMED
uv run python -m signalforge.cli run-scheduler                 # step 6: the worker
```

To stop: `uv run signalforge execution disarm <SVID> --reason "..."` for one strategy, or
`uv run signalforge execution disable --yes` for the whole layer (which disarms
everything). Neither closes a position.

## Step 0 — prove the drills pass, on a scratch database

```bash
uv run signalforge execution drill --all
```

Runs the D6 §21 Phase V drills against `paper_reference` in a throwaway SQLite file
(the runner refuses any URL that resolves to the live database) and writes a dated
report to `docs/research/execution_drills/`. `--dry-run` lists them without opening a
database at all. A drill failure is a stop, not a warning.

## Step 1 — read the posture, and confirm nothing is armed

```bash
uv run signalforge execution status
```

Read-only: it never arms, never disarms and never contacts a broker. Expect
`execution.enabled = False`, `execution_limits: NO active, parseable row`, and
`armed strategies: NONE`.

## Step 2 — enable the layer

```bash
uv run signalforge execution enable --yes
```

`--yes` is required; without it the command changes nothing and exits 2. It writes
`research_overrides.execution.enabled = true` through `settings_store` (so
`AppSettingHistory` records the change), plus an `audit_log` row `execution.enabled` with
actor `local-user`, and prints the resulting live posture and the number of live armings.

It is necessary and nowhere near sufficient: with no unexpired `armed_strategy` row, zero
orders can be submitted whatever this flag says. It is deliberately excluded from
`SCOPE_HASH_FIELDS`, so turning it on does **not** move `config_hash` and does not put
any live approval out of scope — that exclusion is the fix for the 2026-09-11 incident,
and `tests/execution/test_cli_execution.py` asserts the hash is unchanged across this
command.

The inverse is `uv run signalforge execution disable --yes`, and it **also disarms every
live arming**. That is not a convenience: with the flag off the execution cycle is not
registered with the scheduler, so nothing would run the per-cycle auto-disarm sweep, and
a live arming would sit there and come back the moment the flag went on again. Disabling
closes nothing and liquidates nothing.

## Step 3 — write the pre-registered `execution_limits` row

```bash
uv run signalforge execution limits set \
  --from-preregistration PREREGISTRATION_execution_limits_v1 --yes
uv run signalforge execution limits show
```

Exactly the row tabulated in `docs/PREREGISTRATION_execution_limits_v1.md`, with
`preregistration_doc_id = "PREREGISTRATION_execution_limits_v1"`. **There is no flag for
any individual value and there never will be one**: a number typed at a command line is a
number nobody pre-registered. The command reads the values from
`execution/preregistration.py` and refuses the write if they disagree with the document
on disk, if the document does not exist under `docs/`, or if it does not state every
column.

Rows are never edited. A second `set` is refused; changing the row is
`--supersede`, which stamps `superseded_at` on the old row and inserts a new one — and
**superseding RESETS the decision-10 evidence counter** for every strategy armed under it
(§7b rule 3). The command prints that consequence in full before it finishes.

That reset is also a scheduling constraint on the operator, not just a sentence: the ≥ 20
closed paper trades of step 4 are counted **only from the active row's `created_at`**, so
the limits row has to exist *before* the evidence window opens.

Verify with `signalforge execution limits show` or `signalforge execution status`: the
`execution_limits id=…` line must print, and it must name the pre-registration document.

## Step 4 — prove the account is flat and the evidence exists

The ceremony re-verifies both live and refuses on either, so this is a read, not a
promise:

* **decision 10** — ≥ 20 closed paper trades with non-negative expectancy under the
  health monitor, counted **only since the active limits row was created**. Check with
  `uv run signalforge strategy-health`.
* **§10 rule 2** — `adapter.positions()` and `adapter.open_orders()` must both be empty.
  Arming begins from a flat, empty account; "could not check" is not "is flat" and blocks
  identically.

## Step 5 — the ceremony

```bash
uv run signalforge execution arm <STRATEGY_VERSION_ID> \
  --account-id 'PAPER-SIM-<the id you read OUT OF BAND from the broker>' \
  --preregistration PREREGISTRATION_execution_limits_v1 \
  --adapter paper_reference \
  --structure-type equity \
  --approval-level 0 \
  --max-notional 1000 \
  --max-orders-per-day 10 \
  --expires-days 7 \
  --yes
```

What each part is doing, and what refuses:

* `--account-id` is typed **out of band** — read from the broker's own interface, not
  copied from a config file. `is_paper()` must prove the broker's own response body names
  exactly this string (S8). A local flag is not a proof: the flag and a wrong base URL are
  set in the same place by the same mistake.
* `--preregistration` must name a real file under `docs/` (S3). The check is a filename
  match; that the document enumerated the grid is a review fact, and the id is written
  onto the arming row so a reviewer can follow it here.
* `--approval-level 0` is equities only. An options structure needs the operator's real
  level, which is decision 3 and is still outstanding.
* `--expires-days 7` is the **maximum** (decision 4). A larger number is refused, not
  clamped. There is no indefinite arming.
* `--yes` acknowledges the four §12 step 3 facts the command prints above the prompt.
  Read them; (ii) and (iv) are the two an operator otherwise discovers during an outage:
  **nothing is auto-liquidated**, and **engaging the kill switch while the worker is down
  cancels nothing at the broker.**
* Omit `--confirm` so the command **prompts** for the typed phrase. It is exactly
  `ARM <STRATEGY_VERSION_ID> ON paper_reference`, and it names the version and the adapter
  so a confirmation typed for one arming cannot be pasted into another.

`--account-id` must start with `PAPER-SIM-` for this adapter: the simulated account
refuses any other id, so a real-looking brokerage account id cannot be typed at
`paper_reference` by accident, and no adapter is built if one is.

The command prints the full precondition table (A0, S1–S15) before it asks for anything,
and refuses on the first failure. Do not pass `--override-evidence` unless you intend the
override to be audited with the observed `n` and expectancy recorded beside your typed
reason — that is what it does, deliberately, because an override is taken **after** seeing
the outcome.

## The OPEN lane — what the cycle can now do, once a strategy is armed

**Added 2026-09-12 (W4c). Read this before arming anything.** Until W4c the
execution cycle could evaluate, reconcile, sweep and report, and it could not
submit: nothing in `src/signalforge/` called `adapter.place()`. It can now. Here
is exactly what happens, and exactly what has to be true first.

### What it does

Once — and only once — every one of the following holds **in the same cycle**,
the lane submits **one LIMIT order per eligible paper trade**:

| # | Condition | Where it is enforced |
|---|---|---|
| 1 | `research.execution.enabled` is True | `execution enable --yes`; ships False |
| 2 | An adapter was built for the armed account | `cli._execution_cycle_adapter_factory` |
| 3 | A live, unexpired `armed_strategy` row for that strategy version | `arming.live_armings`, after the §12 step 7 sweep has run |
| 4 | Every live arming names the SAME broker account | `cycle._account_scope_ok` (§10 rule 2) |
| 5 | `is_paper()` proved out against the armed account id THIS cycle | `cycle._is_paper_proven` (§13) |
| 6 | The FULL branch — neither kill switch engaged | `read_cycle_posture` (K1, K2) |
| 7 | The dead man is alive | `deadman.assess` (D1) |
| 8 | Reconciliation is CLEAN and fresh | `reconcile` + `max_reconciliation_age_s` (R1) |
| 9 | Broker clock and local calendar AGREE the market is open, outside both no-submit windows | `calendarcheck` (C1, C2, C3) |
| 10 | All seven §5 preconditions, re-verified live per order | `intents.build_open_intent` |
| 11 | Every `may_open` limit, evaluated for THAT order | `limits.may_open` (L0-L3, I1, I2, A1, A2, P, R1, R2) |

The order it sends is **the one the simulation already made**: the size and the
limit price come from the `PaperTrade`'s own `plan_json` (`shares`,
`fill_price`), written by `paper/ledger.py`. The lane computes neither. If the
simulated plan is missing either, the lane refuses rather than inventing one.

### What it cannot do

* **It cannot open anything while nothing is armed** — and nothing is armed by
  default. With no live arming the lane runs no query, builds no intent and
  calls no adapter method: it is absent, not merely inert.
* **It cannot open from a manual accept.** The source must be a `PaperTrade`
  whose indexed `actor` column is the automatic simulator's (§5.3 P6).
  `accept_candidate` is reachable from the CLI with no guard, so "an ACCEPTED
  PaperTrade exists" is not an authorisation.
* **It cannot open the same paper trade twice, ever.** `client_order_id` is a
  hash of (paper trade, leg signature) with no attempt counter; any recorded
  state for that id makes the lane skip it forever.
* **It cannot retry an ambiguous submission.** If `place()` does not return, the
  committed `SUBMITTING` record stands, the next cycle promotes it to `UNKNOWN`,
  and an `UNKNOWN` blocks every further open for that strategy AND blocks
  re-arming it. A retry there is how an ambiguous response becomes a double fill.
* **It cannot reach a real broker.** The only registered adapter is
  `paper_reference`: local, deterministic, network-free, no credential. Its fills
  are drill artifacts and are excluded from every gate.
* **It cannot run in the app process.** The cycle exists only in the
  CLI-launched worker.

### The order of operations, which is not negotiable

`build_open_intent` (all seven §5 preconditions) → `may_open` (every limit, for
this order) → `INTENT_CREATED` → `VALIDATED` → **`SUBMITTING` written and
COMMITTED** → `adapter.place()` → the outcome recorded. The commit before the
call is the whole point: a process killed in between leaves a durable row the
next cycle can promote, rather than losing an order that may have reached the
broker.

### A number to know before you arm: the binding cap is $125

`PREREGISTRATION_execution_limits_v1` pairs a **$1,000** per-order dollar cap
with a **0.5%-of-equity** cap, and `binding_cap` takes the **tighter**. On the
$25,000 reference account that is **$125**.

**So under v1 the lane cannot open any instrument priced above $125 — not even
one share.** A $470 ETF is refused on L2 every time. This is the
pre-registration's own arithmetic working exactly as §1.1 tabulates it, not a
defect, but it is the kind of thing that is much better known before an armed
session than during one. Drill **V30** exists solely to keep it visible.

If that is not what the operator intends, the fix is a **v2 pre-registration
document** and a superseding row — which **RESETS the decision-10 evidence
counter** (§7b rule 3), because evidence accumulated under different limits is
evidence about a different system.

### Watching it

`signalforge execution status` still shows the posture. The cycle's `JobRun`
note now carries an `open_lane[...]` segment whenever the lane ran at all —
`considered=N; submitted=N; filled=N; refused=N`. Every refusal is an
`INTENT_REFUSED` row in `execution_event` naming the precondition or limit that
refused it, and every submission and fill is on the same spine.

## Step 6 — run the worker that carries the cycle

```bash
uv run python -m signalforge.cli run-scheduler
```

**The execution cycle exists only in the CLI-launched worker.** Started from the app
process there is no execution job at all: no submissions, and equally no heartbeat, no
reconciliation, no drain and no protective cycle (drilled as V19). One run by hand:

```bash
uv run signalforge execution cycle
```

## Step 7 — the observation window

One armed strategy, smallest viable size, a stated window, and **daily reconciliation
review by the operator** (§21). Read `signalforge execution status` every session:
`dead man: ALIVE`, a recent clean reconciliation, and the arming's own expiry.

## Stopping — three separate levers, none of which blocks closing

```bash
uv run signalforge execution kill --engage --reason "..."   # K2, execution-only, fail-CLOSED
uv run signalforge killswitch on --reason "..."             # K1, the existing global switch
uv run signalforge execution disarm <STRATEGY_VERSION_ID> --reason "..."
```

Any of them ends the authority to **open**. None of them closes a position, and none of
them is an auto-liquidation: close by hand, at the broker, or through the protective
close lane. Disarming keeps the row — reconciliation and the `is_paper` proof read the
most recent `armed_strategy` row for an adapter **including disarmed and expired ones**,
and deleting it would create a state the system cannot leave without a manual database
write.

If the worker is not running, none of the above reaches the broker at all. That is
acknowledgement (iv), and it is why it is an acknowledgement rather than a footnote.
