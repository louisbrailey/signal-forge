# Wave-3 decisions and status (2026-09-12)

Merged on `main`: W3-A (D5 Amendment 1 → `options_designs/D5a_amendment_1_reachable_credit_floor_and_fixed_R.md`,
O3 short vertical **v0.1.1**), W3-B (`research/options_evidence.py`, `research/options_sensitivity.py`,
`signalforge options evaluate-promotion --dry-run|--confirm [--grid]`), W3-D
(`docs/PREREGISTRATION_execution_limits_v1.md`, Phase V drills 23/23 PASS in
`docs/research/execution_drills/DRILLS_2026-09-12.md`, worktree-safe launchd test), and the
Stage A post-mortem fix (D1 Appendix P, P6: `as_of` alone; `expired=true&as_of` returns zero rows).
In flight: W3-C (options paper EOD chain, injected from the CLI so S16 holds), W4-A (arming
ceremony runnable: B1 enable/disable CLI, B2 limits writer, B3 adapter lookup, OMS position
attribution for reconciliation).

## Rulings taken by the orchestrator (research design, k = 0, before any options evaluation)

| # | Question | Ruling |
|---|---|---|
| R-1 | Cluster unit: D4 §6.3 item 12 `(underlying, expiry cycle)` vs D5 §6.3b F11 cycle-month pooled across underlyings | **Both bind.** Gate 8's CI uses the D4 unit (finer, ICC/deff disclosed); F11 stays a separate NO-SHIP rule (`f11_breached`). A version ships only if neither fails. Conservative by construction; no threshold moved. |
| R-2 | `--confirm` without `--grid` | A sealed look must not be spent on an automatic gate-5 failure: `--confirm` **requires** `--grid` (follow-up code change, W4). |
| R-3 | OQ-1 horizon | MEDIUM_SWING, per D5a §5 (holding period 14–34 days; POSITION's floor is 2.17× the longest hold). |
| R-4 | OQ-10 | Answered by P6: the vendor honours `as_of`; the credit floor is now a cost filter (D5a), disclosed at gate 8, not compensated. |
| R-5 | Options EOD chain placement | 18:30 ET, injected from `cli.py` (`run-scheduler`) like the execution cycle so `scheduler.py` never imports an options paper module (S16). Default OFF (`research.options.paper_eod_enabled=false`). |

## Operator items (money / risk — not taken here)

| # | Item | Why it is yours | Recommendation |
|---|---|---|---|
| OP-1 | Decision 4's **$250 per-structure max loss** makes every cost-viable short-vertical width impossible: at the cap-compliant $2.00 width the target-win outcome is negative in every Stage A cell; cost-viable widths imply max losses of **$254–$842** (D5a §2.3, F14). D4 §2.8a forbids raising the cap after a gate result, so this must be decided **before** the first evaluation. | It is a capital limit on the account that would eventually trade real money; paper and live must share one population (decision 13). | Raise per-structure max loss to **$900** and aggregate open max loss to **$3,600** for the $25,000 options paper account (3.6 % / 14.4 %); keep the $1,000 per-order notional and daily order cap. Then D5a gets a dated Amendment 2 with widths re-derived under the new cap, still at k = 0. If you keep $250, O3 is expected to be the null result and the program's next structure is O2 (covered call) or O1 with a bear-regime carve-out. |
| OP-2 | Broker + paper API keys (Alpaca assumed) | Credentials | — |
| OP-3 | Options approval level | Account permission | Level 2 assumed in every design |
| OP-4 | Gate 0.i aggregate leg: 14 structures × $201.60 = $2,822 vs the $1,000 aggregate cap → at most 4 concurrent structures under the current limits | Follows from OP-1 | Resolved by OP-1's aggregate figure |

## Stage A backfill status

Pass 1 (run #17) excluded all 102 units (`no_contracts_returned`) — cause P6, fixed in `5d37284`.
Pass 2 started 2026-09-12 09:56 UTC on a fresh bulk copy (`data/io2_bulk.sqlite`), bounded to
590 min; first cycles committed (contracts and bars growing). Merge into the live DB only via
`signalforge options merge --from data/io2_bulk.sqlite` after `--dry-run`, with the worker stopped
(runbook §7). No options evaluation runs until OP-1 is decided and D5a is re-derived if needed.

## Addendum (2026-09-12, later): OP-1 now gates the whole options program

- ~~**O3 short vertical v0.1.1** (D5a): expected null under the $250 per-structure cap (F14); viable widths need ≈ $254–$842.~~
  **Superseded 2026-09-23 (addendum 3):** OP-1 confirmed at $900 / $3,600; O3 is now **v0.1.2** at `width_usd` $8.00 and is
  cost-viable in 7 of 9 F14 cells (D5a Amendment 2 §3.2). The $254–$842 figures were credit-net R; on the hard bound the
  same widths cost $301.60–$1,001.60.
- **O2 covered call** (D7 DRAFT, `options_designs/D7_o2_covered_call_preregistration_DRAFT.md`): gates 0.5 and 0.i are jointly unsatisfiable under any cap below ≈ $3,428 (Stage A) / $1,061 (IWM only), and 100 shares of SPY or QQQ exceed the $25,000 account outright; the $5,000 collateral cap admits zero structures on all three underlyings. Not a fallback.
- **O1 cash-secured put**: excluded by decision 12 (gate 6 / collateral wall).

Consequence: no defined-risk options structure can pass the ladder on this account under decision 4's
limits as they stand. *(2026-09-23: the operator took option (a); see addendum 3.)* The operator's choices are (a) OP-1 as recommended (per-structure ≈ $900,
aggregate ≈ $3,600) which makes O3 evaluable, (b) a larger options paper account and collateral cap,
which would additionally open O2 on IWM, or (c) keep the limits and accept that the options program's
pre-registered expectation is the null result. Nothing in the code chooses among these.

Execution layer status: the arming ceremony is runnable end-to-end on `paper_reference` (W4-A: enable/
disable, limits from the pre-registration document, adapter lookup, OMS position attribution; W4-B:
per-cycle adapter with account-scope refusal). The cycle's OPEN LANE (intent → OMS → adapter.place) is
being built as its own increment (W4-C) under the orchestrator's decision recorded here: it is the
ADR's designed body, default-disabled, unreachable unless a strategy is armed by the operator's ceremony.

## Addendum 2 (2026-09-12): the open lane is merged; two more operator items

W4-C (`7af463d`) merged the cycle's OPEN lane (`execution/open_lane.py`: ACCEPTED SIMULATED paper
trades of ARMED versions with the auto-simulate actor only → `build_open_intent` → `may_open` →
`record_submitting` committed first → `adapter.place` → fills; idempotent via `client_order_id_for`;
one intent per paper trade ever) and a durable `paper_reference` book (migration `c1e5a9f37b24`,
table `paper_reference_order`, applied live). Phase V drills 31/31 PASS. `ADAPTER_NAMES` is still
`("paper_reference",)`; `execution.enabled` is False; nothing is armed.

| # | Item | Why it is yours | Recommendation |
|---|---|---|---|
| OP-5 | Under `PREREGISTRATION_execution_limits_v1` the binding per-order notional cap is min($1,000, 0.5 % × $25,000) = **$125**, so an armed session on v1 cannot open any instrument priced above $125 (drill V30). | Capital limit; a v2 document supersedes the row and resets the decision-10 evidence counter. | Write `PREREGISTRATION_execution_limits_v2` with `max_order_notional_pct` = 4 % (→ $1,000 binding on $25k) **before** the first arming, so the evidence window is not reset later. |
| OP-6 | The lane submits on the cycle cadence (30 s grid centre) with no human per order. Acceptable for the network-free simulator; when a **vendor** paper adapter is registered, decide whether it ships with the lane enabled or with a per-order confirmation. | Operational risk on a real (paper) broker account. | Per-order confirmation for the first 20 closed trades on the vendor adapter, then cadence. |

## Addendum 3 (2026-09-23): OP-1 confirmed by the operator — $900 per-structure, $3,600 aggregate

**Decision (operator's).** OP-1 is confirmed at the orchestrator's recommended values:
**`per_structure_max_loss` = $900.00** and **`total_open_max_loss` (aggregate) = $3,600.00**. For
the $25,000 options paper account these are 3.6 % / 14.4 %. The authorization was given in chat on
2026-09-23, verbatim: *"i want you to fully fix it any use all the tools i have enabled you with to
do so"*. It came in reply to being told that O3 cannot qualify because decision 4's $250 cap sits
below the ~$254–$842 minimum viable width. **`collateral_cap_dollars` ($5,000) is UNCHANGED**; it is
not part of OP-1. The per-order notional ($1,000) and daily order cap (10) are also unchanged, as
the OP-1 row recommended. The OP-1 row above is left as written.

**Scope.** This moves the research-promotion limits only: gate 0.i's `OptionsGateThresholds`, the
strategy's fail-closed cap, and the paper book's `OptionsRiskLimits`. It does **not** move
`docs/PREREGISTRATION_execution_limits_v1.md`. Arming remains a separate, later operator gate, and
v1's limits would still refuse every O3 structure.

**Timing.** k = 0, before any options evaluation, which is the route D4 §2.8a permits.

**Consequences, derived in `options_designs/D5a_amendment_2_raised_cap_and_viable_width.md`:**

- O3 becomes **v0.1.2**. `width_usd` goes from $2.00 to **$8.00**, the widest $1-ladder width with
  `W×100 + $1.60 <= $900`, giving `R_hard` = $801.60. The credit-floor band goes from
  0.10 / (0.10, 0.13) / 0.05 to **0.150 / (0.150, 0.155) / 0.140**.
- F14 is resolved in part (F14′). The target win is positive in 7 of 9 Stage A cells at $8. SPY and
  QQQ at sigma 0.30 still need $10 / $9 ($1,001.60 / $901.60 hard bound) and stay excluded. The
  recommendation's "~$900 for SPY at sigma 0.30" was a credit-net figure.
- OP-4 is closed as a limit question. At $3,600 the book holds floor(3600 / 801.60) = **4**
  concurrent O3 structures of the 14 declared, so D5a §3.5's pre-registered 4-structure concurrency
  branch applies. **That cap is not implemented yet** (IMPL-3.3), and it blocks the first evaluation.
- **F15 (new):** the call-side mirror enters nothing at the v0.1.2 band, so the bear bucket is
  expected empty. Orchestrator item **OR-F15**: keep this band, or adopt the pooled put + call band
  0.110 / 0.130 / 0.150, before the first look.
- `OptionsRiskLimits.max_open_structures` = 5 remains dead configuration:
  floor(3600 / 900) = 4, as floor(1000 / 250) = 4 was.

| # | Item | Status |
|---|---|---|
| OP-1 | Per-structure / aggregate caps | **Closed 2026-09-23: $900 / $3,600** |
| OP-4 | Aggregate leg | Closed as a limit; 4-structure concurrency cap applies (IMPL-3.3 open) |
| OR-F15 | Band population (put-only vs pooled) | **Decided 2026-10-26: pooled band, v0.1.3** |


## Addendum 4 (2026-10-04): the first options evaluation runs on the index ETFs only

**Decision (operator's).** Stage B (21 underlyings, bulk run 18) finished `ok` at cycle bracketing
**0.420** and bar continuity **0.644**, below the pre-registered floors 0.90 / 0.80. Stage A (SPY,
QQQ, IWM, bulk run 17) is at **0.902** / **0.851**. Of the two responses the I-O2 runbook permits,
the operator chose to **drop the Stage B underlyings**. Chosen on coverage alone; no option price
or result was viewed, and k = 0.

**Recorded in** `options_designs/D5a_amendment_3_index_underlyings.md`, with the consequences
(sample size below D5 §2.2's floor of 12 underlyings; results do not generalise to single stocks).

**Code.** `signalforge options snapshot` creates the options-scoped `DataSnapshot`; the coverage
pre-flight now judges a snapshot on its own underlyings, at the same floors.

| # | Item | Status |
|---|---|---|
| OR-0c | Gate 0.c read pooled over the set (SPY, QQQ, IWM: 0.902) or per symbol (QQQ and IWM are 0.882 each, leaving SPY alone) | **Decided 2026-10-26: pooled** (see line below) |
| OR-F15 | Band population (put-only vs pooled) | **Decided 2026-10-26: pooled band, v0.1.3** |
| IMPL-3.3 | 4-structure concurrency cap | **Implemented 2026-10-26** (`options_evidence.cap_concurrent`; see addendum) |

OR-0c: DECIDED pooled — 2026-10-26, operator Louis Brailey (instructed in chat; recorded by Claude). The evaluated set stays SPY/QQQ/IWM; floors unchanged; `--confirm` still requires `--accept-pooled-coverage OR-0c`. Ref: options_designs/OR-0c_DECISION_MEMO_2026-10-06.md.

OR-F15: DECIDED pooled band — 2026-10-26, operator Louis Brailey (instructed in chat; recorded by Claude). Adopt the pooled put + call credit-floor band 0.110 / 0.130 / 0.150 as **v0.1.3** (D5a Amendment 4). Disclosure: chosen after the development-window rejection breakdown (0 of 11 setups cleared the v0.1.2 floor); no sealed data was consulted.

*Decision memo: `options_designs/OR-0c_DECISION_MEMO_2026-10-06.md` (states both readings, the numbers, and how to record either decision; decides nothing).*

*OR-0c is enforced in code (2026-10-04; Amendment 3 §3 item 7, runbook §12.4):
`options evaluate-promotion --confirm` refuses a snapshot with a member below a floor on its own
numbers unless the command carries `--accept-pooled-coverage OR-0c` and this file contains a
line beginning with the exact text* `OR-0c: DECIDED pooled`*. This note is not that line and the
item is still Open. Only the operator adds it.*


---

*Addendum (2026-10-26, implementation status only — not a decision): IMPL-3.3 is
implemented exactly as D5a §3.5 and Amendment 2 §3.3 pre-register it. The evidence
assembler and the sensitivity grid both cap the pooled population at
`OptionsShortVertical.portfolio_concurrency_cap = 4` open structures, take candidates in
entry-date then ascending-symbol order, keep the same structures in the 2x-spread cell, and
count refused entries as `skipped_portfolio_concurrency` (gate-8 evidence). A slot occupied
through an exit date is reusable from the next session. The sensitivity cache key gained a
`cc1` tag so grids cached before the cap are misses. No look was taken; k = 0 is unchanged.
OR-0c and OR-F15 remain Open and are the operator's.*
