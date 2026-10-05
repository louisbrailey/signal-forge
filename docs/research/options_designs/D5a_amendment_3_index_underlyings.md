# D5 — Amendment 3: the first evaluation's underlyings are the index ETFs SPY, QQQ, IWM

**Amends:** `docs/research/options_designs/D5_first_strategy_preregistration.md` §2.2 (the
underlying set), as already amended by D5a and D5a Amendment 2.
**Applies to:** `options_short_vertical.medium_swing` **v0.1.2** — the strategy version is
**unchanged**. This amendment changes the *dataset* the first evaluation runs on, not the
strategy.
**Written:** 2026-10-04. **Status: PRE-REGISTRATION — written before any evaluation, dry run or
otherwise, on the snapshot it defines. Legitimate only at k = 0.**

---

## 0. Why a sibling file, why it is legitimate today, and what was read

### 0.1 Why a sibling file

The same argument as D5a §0.1 and Amendment 2 §0.1. D5 §2.2 and Amendment 2 §5 ("the underlying
set … stays exactly as D5a left it") are records of what was fixed first; editing them in place
would erase that. They are left unchanged. D5's Appendix P and Amendment 2 each gain a dated
pointer that moves nothing (§7).

### 0.2 Why it is legitimate now

**The operator's decision (FACT).** On 2026-10-04 the operator chose, of the two responses the
I-O2 runbook permits to a coverage shortfall (§6 of `IO2_RUNBOOK.md`; D1 §12
`LADDER_SHORTFALL_RESPONSE`: *drop the underlying, or pre-register a finer rung set*), the first:
**drop the Stage B underlyings and run the first evaluation on the Stage A index ETFs.**

**The decision was made on coverage alone.** The inputs were the two coverage summaries in §1 —
counts, fractions, dates and identities, the only thing the runbook permits anyone to read. No
option price, IV, greek, credit, return or P&L was viewed, by a person or a script, for any of
the 24 underlyings, and no evaluation of any kind has been run on any options snapshot: no
options-scoped `DataSnapshot` exists yet, so none could have been.

**k = 0 (measured read-only on 2026-10-04).** The live database was opened **read-only**
(`mode=ro`) and asked four counts: rows in `strategy` whose name begins `options` — **0**;
`strategy_sealed_test` rows for that family — **0**; `strategy_promotion_evaluation` rows for
that family — **0**; `data_snapshot` rows carrying an `options_scope_json` — **0**. Whoever runs
the first `--confirm` evaluation must still run `count_sealed_looks` for the family first, as
the first look already requires.

### 0.3 Attestation for this pass (FACT)

- No provider API was called. No database was opened for writing.
- The bulk file `data/io2_bulk.sqlite` was opened **read-only** and only `ingestion_run` rows of
  kind `options_cycle_backfill` were read (runs 17 and 18): cycle counts, exclusion reasons,
  contract counts, bar counts, dates. `option_aggregate_daily` was not queried.
- The live database was opened read-only for the four counts in §0.2 and nothing else.
- Every number in this document is a count, a fraction of counts, a date or an identity.

---

## 1. The coverage that forced the choice

Pre-registered floors, unchanged by this amendment and asserted as constants by the suite
(`tests/research/test_options_snapshot_coverage.py::test_the_coverage_floors_are_unchanged`):
gate 0.c cycle bracketing **≥ 0.90**, gate 0.d bar continuity **≥ 0.80** (D1 §12, D5 §5.1/§5.2).

| Run (bulk-file id) | Underlyings | Cycles covered / total | Bracketing | Bar continuity | vs floors |
|---|---|---|---|---|---|
| **17** — Stage A, `ok` | SPY, QQQ, IWM | **92 / 102** | **0.902** | **0.851** (run counter: 124,806 / 146,577) | passes both |
| **18** — Stage B, `ok` | the other 21 | **300 / 714** | **0.420** | **0.644** (303,154 / 470,974) | **fails both** |

Both runs: window 2023-09-04 → 2026-09-04, `monthly_third_friday`, `LADDER_17`,
`strike_listing_basis = vendor_as_of`. Run 17's ten exclusions are all deterministic:
`no_contracts_returned` 6, `insufficient_rungs_per_side` 2, `ladder_too_coarse` 1,
`reference_price_outside_ladder` 1. (The ids are the bulk file's; `options merge` re-keys each
run and prints the new id.)

Stage B is far below both floors, and its exclusions are dominated by the ladder being too
coarse for lower-priced names — the case D1 §3.3 anticipated. The 21 Stage B underlyings are
dropped **as a block**.

### 1.1 The same numbers per underlying — disclosed, because the pool hides them

| Underlying | Run | Cycles | Bracketing | Per-cycle bars / expected | Continuity |
|---|---|---|---|---|---|
| SPY | 17 | 32 / 34 | 0.941 | 43,150 / 52,326 | 0.825 |
| QQQ | 17 | 30 / 34 | **0.882** | 41,987 / 49,164 | 0.854 |
| IWM | 17 | 30 / 34 | **0.882** | 36,229 / 45,087 | 0.804 |
| **pooled** | 17 | **92 / 102** | **0.902** | **121,366 / 146,577** | **0.828** |

Two things in that table are stated here so nobody has to discover them later.

**(a) Continuity is 0.828 on the per-cycle records, not 0.851.** The run-level counter (124,806)
includes 3,440 bars written by cycle attempts that were later re-attempted after a network
failure (runbook §10, Stage A passes 2–3); a re-attempted cycle's record keeps only the bars its
last attempt added. The run counter cannot be split by underlying, so the per-snapshot
pre-flight (§3) sums the per-cycle records. That figure can only be lower than or equal to the
true one. Both are above 0.80.

**(b) QQQ and IWM are each at 30/34 = 0.882, individually below 0.90.** The set passes 0.c only
as a pool. Which reading binds is the subject of §2.

---

## 2. What is declared

> **The first evaluation's underlying set is exactly `{SPY, QQQ, IWM}`.** The snapshot is the
> options-scoped `DataSnapshot` built by `signalforge options snapshot --symbols SPY,QQQ,IWM
> --since 2023-09-04 --until 2026-09-04`, whose key carries its scope hash:
> `options_idx3_massive_2023-09-04_2026-09-04_0ae681d590`.
>
> (The hash suffix was derived read-only from run 17's provenance with the committed code. The
> command prints the canonical key; if it ever prints a different suffix, the scope differs from
> the one described here and that must be explained before anything is written.)

### 2.1 The key moved on 2026-10-04, and snapshot id 16 is superseded (explained, as required)

The key first written here was `options_idx3_massive_2023-09-04_2026-09-04_6fa62e29d7`, and a
`DataSnapshot` (live id **16**) was created under it. **That snapshot is superseded and must
not be evaluated.** The suffix changed because two identity fields entered the scope, both by
design and neither in response to a result:

1. **Gate 0.i's risk-limit set is now inside `options_config_hash`** (D4 §2.8a / §2.9b, which
   always required it): `OptionsEvaluationConfig` carries
   `options_per_structure_max_loss = 900` and `options_total_open_max_loss = 3600` (OP-1). The
   values are unchanged; only where they are hashed changed. `options_config_hash` went from
   `554de314…` to `eae47124…`, and it is a member of the scope.
2. **The scope names the option-data source**: `option_data.source = massive_options`, the
   provider of the cycle-backfill run that wrote the option rows. The underlying's daily bars
   are stored under `massive`; the two labels are different data kinds and R6 holds per kind.

Snapshot 16's key is bound to neither. Under the committed code gate 0.i fails on it by name
(its recorded `options_config_hash` is not the hash of the config that carries the limits), and
`options evaluate-promotion --confirm` refuses it. **A snapshot is immutable: 16 is left in
place, not edited and not relabelled; a new row is written under the new key** (runbook §12
step 6b). The underlying set, window, coverage run (live id 44 — bulk run 17 re-keyed by the
merge), floors and strategy version are all unchanged.

**What had been run on snapshot 16, stated exactly.** One `evaluate-promotion --dry-run` on the
live database. It loaded **no option chain for any underlying** — the evidence path passed the
bar source `massive` to the option tables, which hold their rows under `massive_options` — so it
evaluated zero structures and printed no option-derived quantity. No `--confirm` was run, no
evaluation row or sealed test exists for it, and **k stays 0**.

- **Membership rule.** The Stage A set, which the runbook fixed as a stage on 2026-09-12 before
  any coverage existed (§2, "SPY, QQQ, IWM only — 102 units"). It is not a selection of
  individually passing names: MSFT (32/34 = 0.941, continuity 0.926) passes both floors alone
  and is **not** included, and DIA and HD pass bracketing alone and are not included. No name
  was added or removed on its own numbers.
- **The floors are asked of the pooled set**, as D5 §5.1 defines gate 0.c ("≥ 90 % of
  (underlying, monthly cycle) pairs in the window") and as the coverage pre-flight has always
  computed it. Pooled: 0.902 and 0.828.
- **OR-0c (orchestrator/operator item, open, must be closed before the first `--confirm`).**
  D5 §2.2's coverage-exclusion sentence reads per symbol: "a symbol is dropped if its chain
  coverage summary … fails gate 0.c or 0.d". Read that way, QQQ and IWM (0.882 each) are dropped
  and the set is SPY alone. This amendment adopts the pooled reading and says so before any
  result exists; it does **not** claim the per-symbol reading is wrong. The stricter alternative
  is fully specified — `{SPY}`, 32/34 = 0.941, continuity 0.825 — and choosing it now costs no
  look. Choosing between them after a result is forbidden.
- **Everything else is exactly as Amendment 2 left it:** v0.1.2, `width_usd` $8.00, the band
  0.140 / 0.150 / 0.155, the 96-point grid, the cost model, every gate threshold, the $900 /
  $3,600 caps, the horizon, the proxy (SPY), the sealed window (365 days).

No threshold, floor or constant is moved. `MIN_RUNGS_PER_SIDE`, `LADDER_BRACKET_MIN_RUNGS`,
`GATE_0C_CYCLES_BRACKET` and `GATE_0D_SESSION_BARS` are untouched.

---

## 3. The code change that makes the declaration enforceable

Before this change the pre-flight read **the newest** `options_cycle_backfill` run overlapping
the window and judged it whole. Run 18 is newer than run 17, so an index-only snapshot would
have been refused on the stocks' numbers — and, had the order been reversed, a snapshot holding
a stock would have been passed on the index numbers.

Now (`research/options_evidence.py`: `snapshot_options_coverage`, `dataset_snapshot_coverage`,
`coverage_preflight`):

1. For **each underlying of the snapshot**, the newest overlapping cycle run that requested it
   is read (never an older, better one), restricted to that underlying's own cycle records.
2. The counts are pooled over exactly the snapshot's symbols — cycles covered / total, and
   per-cycle bars written / (sessions expected × contracts fetched).
3. The **same two floors** are applied to that pool.
4. Further refusals: an underlying with no recorded coverage; runs that disagree on provider,
   cycle rule, ladder or strike-listing basis; a run status other than `ok` / `partial`.
   **A member is never pooled silently** (added 2026-10-04 after safety review): an underlying
   its run merely *requested* — with no per-cycle records, with zero expected sessions, or
   listed in that run's `symbols_failed` — is refused **by name**. Such a member adds nothing
   (or only part of itself) to the pooled counts, so without this refusal the other members
   would carry it past both floors (`{SPY 10/10, QQQ no records}` pooled to 1.0 / 1.0).
5. A snapshot is judged **only** on the runs its scope recorded (`ingestion_run_ids`). A
   snapshot that records none is refused; so is one whose recorded run is absent. There is no
   fallback to "the newest overlapping run" on the evaluation path. `ingestion_run_ids` is
   provenance and is **not** part of `options_scope_hash` (a resume must not mint a new key for
   the same dataset definition, and `options merge` re-keys run ids), so `options snapshot`
   compares the recorded ids itself and refuses to report "nothing to write" over an existing
   row pinned to different runs.
6. The per-underlying fractions are printed with every pre-flight, so a pooled pass never hides
   which member carried it.
7. **The OR-0c guard** (added 2026-10-04 after safety review). The pre-flight result is still the
   pooled computation, but it also reports `members_below_floor`: every member whose **own**
   bracketing is below 0.90 or whose own continuity is below 0.80, with its numbers. While that
   list is non-empty:
   - `options snapshot` (dry run and `--confirm`) and `options evaluate-promotion --dry-run`
     proceed and print `WARNING: OR-0c is open: pooled reading passes, per-symbol reading fails
     for: …`;
   - `options evaluate-promotion --confirm` **refuses** — exit 2, nothing assembled, nothing
     written, no sealed look — unless **both** hold: the command carries
     `--accept-pooled-coverage OR-0c`, **and** `docs/research/DECISIONS_2026-09-12_wave3.md`
     contains a line beginning `OR-0c: DECIDED pooled`. The flag without the recorded line is
     refused; the recorded line without the flag is refused. The flag never overrides a pooled
     floor failure or any other refusal.

   For this amendment's set the list is QQQ (0.882) and IWM (0.882), so the first `--confirm`
   cannot run until the operator closes OR-0c in writing. If the operator instead decides the
   per-symbol reading, no flag exists for it: the snapshot is rebuilt as `{SPY}` (§2), where
   the list is empty.

For an underlying set equal to one run's set this is the old computation, except that
continuity uses the per-cycle bar records (§1.1a), which can only lower it. Measured against the
real run provenance: `{SPY, QQQ, IWM}` passes (0.902 / 0.828); `{SPY, QQQ, IWM, AAPL}` is refused
(102/136 = 0.750). **Pooling is not per-member strictness**: `{SPY, QQQ, IWM, MSFT}` would pass
(124/136 = 0.912, 0.854), as would any set whose pool clears the floors. That is the pooled
reading of §2, and OR-0c is where it is decided — and, per item 7, a `--confirm` on such a set is
refused until it is.

---

## 4. Consequences, stated in advance

1. **Far fewer trades.** 3 underlyings × 34 monthly cycles = 102 units, 92 with a usable chain,
   before the regime filter, the credit floor and the delta band remove more. D5 §2.2 sized the
   set at 14 and **floored it at 12 "so that gate 5's per-cell trade counts survive"**. Three is
   below that floor. Expect grid points under `min_trades` (15), regime buckets under
   `min_trades_per_regime` (10), and a sealed year of at most 3 × 12 cycle entries against
   `sealed_min_trades` (10). **A gate that fails for sample size fails.** No count threshold is
   lowered to accommodate the smaller set, now or after.
2. **The window is 3 years, not D5 §2.3's 8 (floor 6).** That is the entitlement depth already
   recorded in the runbook, not something this amendment changes, but with 3 underlyings it
   binds harder. D5 §2.3 wrote the expected consequence in advance: F11's clustered CI does not
   close and the disposition is the §10 null option. That expectation stands and is repeated
   here so a null result is read as predicted, not as a surprise to be explained away.
3. **F14′ and F15 apply in full** (Amendment 2 §3.2, §4.6): SPY and QQQ are cost-unviable at
   sigma 0.30, and the bear bucket is expected empty. OR-F15 is still open.
4. **The result does not generalise to single stocks or sector ETFs.** Whatever the first look
   returns, it is evidence about monthly short verticals on three highly correlated index ETFs.
   It says nothing about the 21 dropped names — and they were dropped because their chains are
   listed too coarsely for this ladder, which is itself a reason to expect them to behave
   differently.
5. **Three correlated underlyings are close to one independent series.** D5 §6.3b's clustered
   accounting (unit: cycle-month) is unchanged and is the binding one; per-trade `n` overstates
   the evidence.
6. **D5 §2.2's shortfall ladder is not invoked.** Its trigger and response (expand top-11 →
   top-19) concern the net entry rate; the response actually taken is the runbook's
   drop-the-underlying. The two are different mechanisms and this is recorded as a departure
   from §2.2's "no other change to the population is permitted", made at k = 0, on coverage
   only, and disclosed at gate 8.
7. **Gate 0.i(ii).** With at most one open structure per underlying, 3 × $801.60 = $2,404.80 is
   inside the $3,600 aggregate cap. IMPL-3.3 (the 4-structure concurrency cap) is still not
   implemented; if overlapping cycles put more than 4 structures open at once the gate fails as
   the code stands.

---

## 5. Sealed-look accounting

| Item | Value |
|---|---|
| Family | `options_short_vertical.medium_swing` |
| Sealed looks spent before this amendment | **0** (§0.2) |
| Looks spent by this amendment | **0** |
| Looks spent by `options snapshot --dry-run` / `--confirm` | **0** — it writes at most one `DataSnapshot` row and evaluates nothing |
| Looks spent by `options evaluate-promotion … --dry-run` | **0** — no evaluation row, no sealed test |
| The next `--confirm` evaluation | **look index 1** of the family, on the index snapshot |
| D5 §10 variant budget | untouched: 1 variant, hard cap 2 |

A dry run on the index snapshot does show pre-sealed diagnostics. After it, the underlying set,
the OR-0c reading and OR-F15 are frozen: none may be changed in response to anything a dry run
printed.

---

## 6. What a later single-stock evaluation would require

Not authorised here. All of the following, in order:

1. **A pre-registered finer rung set** — the runbook's other permitted response — written and
   committed *before* any re-fetch: the ladder offsets, `MIN_RUNGS_PER_SIDE` and the band stated
   as constants, with the reason, and with **no** floor lowered.
2. **A re-backfill** of the stock underlyings on that ladder (a new `options_cycle_backfill`
   run), read through the coverage report only.
3. **Its own options-scoped snapshot.** A different ladder is a different `options_scope_hash`
   and therefore a different key; it can never share a snapshot with the index data (D1 §9.2).
   The per-snapshot pre-flight must pass on *that* snapshot's underlyings at the same 0.90 /
   0.80.
4. **Its own pre-registration amendment** naming the set and the membership rule before any
   price on it is read.
5. **Its own sealed look**, counted in the same family: it is look *k + 1* of
   `options_short_vertical.medium_swing`, not a fresh start, and it is disclosed alongside the
   index result whatever either shows.

---

## 7. The D5 digest (gate 0.f), and the pointers

Gate 0.f records `cost_model_frozen_at = "D5@" + sha256(D5 file)[:12]`
(`options_evidence.preregistration_digest`). The digest covers **the D5 file only**; adding this
sibling file does not change it. The pointer row added to D5's Appendix P does, exactly as the
pointers for D5a (2026-09-12) and Amendment 2 (2026-09-23) did — which is the disclosure the
digest exists to force.

| | Digest |
|---|---|
| D5 before this amendment's pointer | `D5@0582b9e282ad` |
| D5 after it (as committed with this file) | `D5@3cc6d5120efd` |

No evaluation has recorded either value (k = 0), so nothing stored is invalidated. The digest
the first look records will be the post-pointer one. Nothing in D5 above Appendix P is changed,
and the frozen cost model itself (`PREREGISTERED_COST_MODEL`) is not touched.

Pointers added, each moving nothing: D5 Appendix P (a dated addendum); Amendment 2 (a dated
appendix after §8); `DECISIONS_2026-09-12_wave3.md` (addendum 4).

---

## 8. Open items after this amendment

- **OR-0c (new; before the first `--confirm`).** Pooled reading (`{SPY, QQQ, IWM}`, adopted
  here) or per-symbol reading (`{SPY}`), §2. **Enforced in code since 2026-10-04 (§3 item 7):**
  it is no longer a reminder — `--confirm` refuses the index set until the decision is recorded
  and named on the command line. This file does not record that decision.
- **OR-F15** — unchanged, still open, before the first look.
- **IMPL-3.3** — unchanged, still open.
- **Scope fields fixed by the snapshot command** (`spread_model.model_id =
  d2_pct_of_last_print_abs_floor`, `fill_timing.basis = next_session`,
  `multiplier_this_evaluation = 1.0`, with `spread_multipliers = [1.0, 2.0]` both run inside one
  evaluation). They are part of the scope hash; changing any of them is a new snapshot.
- **Snapshot id 16 superseded (2026-10-04, §2.1).** The new key is
  `options_idx3_massive_2023-09-04_2026-09-04_0ae681d590`; the operator writes the new row with
  runbook §12 step 6b (worker stopped). Until then no options snapshot on the live database is
  evaluable.
- **Resuming run 44 / 45 is now refused.** Their provenance records the old
  `options_config_hash`, which is one of the cycle backfill's identity keys, so a resume under
  the new hash is "a different dataset" by the backfill's own rule. Both runs are `ok` and
  complete; this matters only if a top-up is ever wanted, which would be a new run.

## 9. Change record

| Item | Before (D5 §2.2 / Amendment 2 §5) | **After this amendment** |
|---|---|---|
| First evaluation's underlyings | 14 declared (3 index ETFs + top-11 stocks); 24 backfilled | **SPY, QQQ, IWM** |
| Reason | — | Stage B fails 0.c / 0.d: 0.420 / 0.644 (run 18) vs 0.90 / 0.80 |
| Coverage floors | 0.90 / 0.80 | 0.90 / 0.80 (**unchanged**) |
| Pre-flight reads | the newest cycle run, whole | **the snapshot's own underlyings**, pooled, same floors |
| A requested member with no cycle records / failed in its run | pooled silently | **refused by name** |
| Snapshot with no recorded `ingestion_run_ids` | fell back to the newest overlapping runs | **refused** |
| OR-0c while a member is below a floor on its own | a note in this file | **warning on every run; `--confirm` refused** without flag + recorded decision |
| Strategy version | v0.1.2 | v0.1.2 (unchanged) |
| Sealed looks spent | 0 | 0 |
| Gate 0.i limit set ($900 / $3,600) | outside every hash; 0.i failed by construction | **inside `options_config_hash`** (values unchanged); 0.i also requires the snapshot to be keyed on that hash |
| Option-data source | the bar source `massive` passed to the option tables (no chain loaded) | **read from recorded provenance** (`massive_options`); recorded in the scope; refused if unnamed |
| Snapshot key | `…_6fa62e29d7` (live id 16) | **`…_0ae681d590`**; id 16 superseded, never evaluated (§2.1) |
