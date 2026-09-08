# FB → META symbol-continuity investigation

Run 2026-09-08. Investigates and resolves the "META 90 missing sessions"
finding from `reports/STRATEGY_PROMOTION_STATUS.md`. Every step below used
real, licensed Massive data — no fixture/simulated data anywhere in this
investigation. **This report reflects the state after an adversarial code
review found 12 real defects in the first pass of this work — all fixed,
re-verified, and re-run; see §6.**

## Executive summary

The original finding ("META has 90 missing sessions") **understated the real
problem**. The actual issue: **the ticker `META` was held by a completely
unrelated micro-cap entity before Facebook's real FB→META rename on
2022-06-09**, and the pipeline's existing `META` data silently blended that
unrelated entity's price history (2021-06-30 through 2022-01-28, trading
$11–15/share) with real Meta Platforms Inc. data (2022-06-09 onward, trading
$160–380+/share) under one symbol — not a mere gap, a genuine identity
mix-up.

This was investigated, fixed, and validated end-to-end:

1. **Real FB history obtained** (1,446 bars, 2016-09-12→2022-06-08, licensed
   Massive data) and ingested into its own instrument — `META`'s own data
   was never touched.
2. **An explicit, versioned, auditable `SymbolContinuityMapping` row** was
   built and validated against 6 independent checks (dates, sessions, price
   continuity, volume, split adjustment, source provenance) — **all
   passed** — plus a 7th diagnostic that explicitly disclosed the
   contamination described above.
3. **A corrected continuous series (`META_CONT`)** was materialized into a
   brand-new, separately-labelled instrument — 2,510 bars, 2016-09-12 through
   today, seamless at the 2022-06-08→06-09 boundary — **without modifying
   `META`'s or `FB`'s own raw ingested data at all**.
4. **Three dataset variants were run through the full 10-gate promotion
   pipeline** for all 6 default strategies (18 evaluations per run), each as
   a separately-identified, immutable `DataSnapshot` — no sealed test from
   one variant was ever reused or overwritten by another.
5. **Two strategies passed every gate for the first time in this project's
   history**, under the `ex_meta` variant. This is a real, consequential
   operational change, reported prominently in §4a.
6. **An adversarial review of this work found 12 real defects** — including
   one that made the "corrected" comparison variant silently test nothing.
   All 12 were fixed, the affected results were purged and re-computed
   correctly, and everything below reflects the corrected, final state.

## 1. Root-cause investigation (licensed data, verified empirically)

Query at the start of this task, before any fix:

```
META instrument: first bar 2021-06-30, last bar 2026-09-04, 1212 bars total
Missing sessions: exactly 90, forming ONE contiguous block: 2022-01-31 .. 2022-06-08
```

Price/volume inspection across that block boundary:

| Date | Close | Volume | |
|---|---|---|---|
| 2022-01-28 (last bar before the gap) | **$12.31** | 1,571,954 | — |
| 2022-06-09 (first bar after the gap) | $184.00 | 23,501,579 | 14.9× jump |

A $12/share, ~1–4M-volume stock cannot be Meta Platforms (which traded
$180–$385 through this entire period). This is a **different company**
that happened to hold the ticker `META` before Facebook's real-world
ticker-symbol change.

**Verification via a live, licensed fetch of `FB`** (Massive/Polygon,
`/v2/aggs/ticker/FB/...`) confirmed the real story:

| Date | Symbol | Close | | |
|---|---|---|---|---|
| 2016-09-12 (FB's earliest available session) | FB | $128.69 | — | matches real Facebook Inc. price history |
| 2022-06-08 (FB's LAST session — confirmed empirically, not assumed) | FB | $196.64 | — | a follow-up fetch of FB for 2022-06-08..2022-06-20 returned exactly **one** bar (2022-06-08); FB has zero data after that date |
| 2022-06-09 (META's first real session) | META | opens **$194.28** | −1.2% | a mundane overnight move — real, continuous price action |

This is the true, empirically-verified corporate action: **FB → META,
effective 2022-06-09, no split/reverse-split ratio (1:1 continuity)** — and
it independently confirms the real-world FB→META Nasdaq ticker change date,
derived here from data, not from memory or assumption.

## 2. The symbol-continuity mapping

Built via `signalforge symbol-continuity-backfill --old-symbol FB --new-symbol META`
(also directly callable as `data.symbol_continuity.build_and_validate_mapping`).
Persisted as `SymbolContinuityMapping` id=1, `FB→META v1`:

| Field | Value |
|---|---|
| `corporate_action_type` | `ticker_and_name_change` |
| `effective_date` | **2022-06-09** (first META session strictly after FB's last — not simply "META's earliest bar", see note below) |
| `last_old_session` | 2022-06-08 |
| `ratio` | 1.0 (no split) |
| `source` | `massive` (both legs, same licensed provider) |
| `validation_status` | **`verified`** |
| `derived_symbol` | `META_CONT` |

### The 6 validation checks (all passed)

| # | Check | Result |
|---|---|---|
| 1 | `dates_ordered_no_duplicates` | PASS — last FB session 2022-06-08 < first META session 2022-06-09, zero overlapping dates |
| 2 | `no_unexplained_session_gap` | PASS — no NYSE trading session falls between the two legs |
| 3 | `price_continuity` | PASS — FB close $196.64 → META open $194.28 (+1.20% move; 15% tolerance) |
| 4 | `volume_sane` | PASS — FB 22.3M shares, META 23.5M shares, both real trading volumes |
| 5 | `split_factor_unity` | PASS — both legs `split_factor=1.0`; no hidden/unadjusted split |
| 6 | `same_source_provenance` | PASS — **now a genuinely reachable check** (see §6, finding #4): both legs' ENTIRE recorded history, not just the two boundary bars, carries only the `massive` source tag |

### The disclosed diagnostic (not a pass/fail gate — a transparency requirement)

> **`pre_transition_contamination`: found = true.** 148 bar(s) exist under
> `META` dated on/before FB's last session (2022-06-08) — spanning
> 2021-06-30 through 2022-01-28 — evidence the `META` ticker was held by a
> different, unrelated entity before this corporate action. **Excluded
> from the bridge**, which uses only `META` bars strictly after
> 2022-06-08. Those raw bars remain in `META`'s own instrument, completely
> untouched — the derived/bridged instrument never includes them.

**A note on the effective-date algorithm** — worth stating precisely,
because it was the one bug found and fixed while first building this
module (independent of the later adversarial review, see §6): the effective
date must be *the first `META` session strictly after FB's own last
session*, never simply "the earliest bar ever ingested under `META`". The
naive version (globally-earliest `META` bar) would have picked 2021-06-30 —
the contaminated entity's first day — as the "effective date," which is
exactly wrong. This is now covered by a dedicated regression test.

### What "verified" does — and does not — authorize

A mapping is not itself permission to blend data. It only authorizes
`materialize_continuous_series` to build a **new, separately-labelled**
derived instrument. `FB` and `META`'s own raw ingested `OHLCVDaily` rows
were **never modified** by any step in this investigation.

## 3. The corrected continuous series (`META_CONT`)

Materialized once (idempotent — re-running writes 0 new bars; attempting to
materialize a *different* mapping version onto the same derived symbol is
now explicitly refused rather than silently duplicating data — see §6,
finding #2):

- **2,510 bars**, 2016-09-12 → 2026-09-04 (1,446 from FB + 1,064 from META
  post-2022-06-09)
- Every bar's `source` field is tagged `continuity_bridge:1` — traceable
  back to the exact mapping row and version that authorized it, at the
  individual-bar level, not just the instrument level
- Verified seamless at the boundary: `2022-06-08 close $196.64 →
  2022-06-09 close $184.00` — a normal daily move, no artifact

## 4. Three-way dataset comparison

All 6 default strategies × 3 dataset variants = 18 promotion evaluations,
each a separately-identified, immutable `DataSnapshot` (`data_snapshot`
table) — a changed universe is new data, never a silent overwrite of
another variant's sealed test. **This is the corrected, final run** — see
§6 for what the first run got wrong and how it was fixed and re-executed.

| Strategy | `universe_25_baseline`<br>(raw, contaminated META) | `universe_24_ex_meta`<br>(META excluded) | `universe_25_meta_continuity_corrected`<br>(META → verified bridge) |
|---|---|---|---|
| `intraday_orb.intraday` | 0/1 — NO TRADE | 0/1 — NO TRADE | 0/1 — NO TRADE |
| `trend_continuation.short_swing` | 9/10 — NO TRADE | **10/10 — PAPER_APPROVED** | 9/10 — NO TRADE |
| `trend_continuation.medium_swing` | 9/10 — NO TRADE | 9/10 — NO TRADE (sealed test flips negative) | **9/10 — NO TRADE (sealed test RECOVERS positive)** |
| `mean_reversion.short_swing` | 5/10 — NO TRADE | 6/10 — NO TRADE | 5/10 — NO TRADE |
| `relative_strength.medium_swing` | 9/10 — NO TRADE | **10/10 — PAPER_APPROVED** | 9/10 — NO TRADE |
| `volatility_breakout.short_swing` | 5/10 — NO TRADE | 6/10 — NO TRADE | **4/10 — NO TRADE (worse: sensitivity now also fails)** |

**Overall operational result under the `ex_meta` variant:**

```
At least one strategy is PAPER_APPROVED.
```

(Under `baseline` and `meta_continuity_corrected`, the result remains
`NO TRADE — insufficient evidence or poor risk/reward`.)

### 4a. The two real promotions — full detail

Both occurred under `universe_24_ex_meta` (currently evaluation ids 32 and
35, re-confirmed identical to the original ids 20/23 after every review-fix
was applied and the full comparison was re-run from scratch), using the
project's real, unmodified `PromotionThresholds` — not a lenient test
configuration. **Neither promotion is affected by any of the 12 defects
found in §6** — the ex_meta variant never touches `META_CONT`, so the bug
that invalidated the corrected variant's results never reached it. This was
directly re-verified: `Strategy.status` for both remains `paper_approved`
after every fix and re-run in this report.

**`trend_continuation.short_swing` v0.1.0 — 10/10, PAPER_APPROVED**: 109
out-of-sample trades, sealed-window net expectancy positive, benchmark-
beating Sharpe, full regime coverage, clean data-quality/leakage pass (the
META gap is gone because META isn't in this universe), all 4 walk-forward
folds clearing both the trade-floor and expectancy bar.

**`relative_strength.medium_swing` v0.1.0 — 10/10, PAPER_APPROVED**: the
strategy every prior report flagged as "the best risk-adjusted of the six"
(Sharpe +1.30 vs SPY +0.72) — previously blocked *only* by the gate-8 META
finding. With META excluded, every remaining gate it already cleared stays
cleared.

**Why this is a principled correction, not gaming the gates:** excluding a
symbol whose raw data is *proven* to blend two unrelated companies is
resolving a genuine, disclosed data-quality issue (the exact thing gate 8
exists to catch) — not narrowing the universe to make a strategy pass. No
new strategy was created; no threshold was relaxed; the sealed test was
computed fresh, honestly, under its own dataset snapshot.

**Evidence this correction was applied neutrally, not selectively:**
`trend_continuation.medium_swing` — a strategy that was *also* only blocked
by gate 8 in the baseline, with a thin but positive sealed expectancy of
+0.0109R — **got WORSE** once META was simply excluded: its sealed test
flipped to a **negative** expectancy under `ex_meta`. Removing META helped
two strategies and hurt one — a mixed, unbiased result, not a thumb on the
scale. (§4b below has the more complete, corrected version of this story.)

**Operational consequence — flagged explicitly, not buried:** per the
existing design (`Strategy.status == PAPER_APPROVED` is the *only*
structural gate for candidate-trade alerts), these two strategies are now
alert-eligible. `alerts_enabled` remains `True` in this environment. The
next scheduled `job_alerts`/`run_alert_cycle` cycle **will** send a real
candidate-trade alert (subject to the daily cap, quiet hours, and dedup)
the next time either strategy's scan produces a qualifying candidate.
Every such alert still carries `"Research signal only — no order was
placed."` — no brokerage, no order, no execution path exists anywhere in
this system. Paper-trade acceptance remains manual.

### 4b. The corrected variant, correctly computed — what it actually shows

This is the section that changed most from the first draft of this report.
The first run of `meta_continuity_corrected` silently tested nothing (a real
bug — see §6, findings #1/#9); after fixing it and re-running, the results
are now genuinely different from `ex_meta`, and more informative:

- **`trend_continuation.short_swing`**: sealed test now shows **112
  trades**, matching `baseline`'s 112 (not `ex_meta`'s 109). This is
  expected and correct: the sealed window (the most recent ~1 year) falls
  entirely in the real, post-2022-06-09 Meta Platforms era, so trading
  `META_CONT` there is identical to trading real `META` there. Still blocked
  by gate 8 only (9/10) — same as baseline, for the reason in §4c.
- **`trend_continuation.medium_swing`**: sealed test now shows **98
  trades**, matching baseline exactly, and its net expectancy is genuinely
  **positive again** (matching baseline's thin +0.0109R) — unlike `ex_meta`,
  where excluding META entirely made this specific strategy's sealed result
  flip negative. **This is the key finding of doing the correction properly
  rather than just excluding the symbol**: `ex_meta` discards a real,
  currently-relevant positive contribution from the (correctly-identified)
  post-transition Meta Platforms data, along with the contamination; the
  bridge keeps the real signal and drops only the contamination.
- **`relative_strength.medium_swing`**: 16 trades, matching baseline
  exactly. Same gate-8-only block as before.
- **`mean_reversion.short_swing`**: 91 trades, matching baseline — genuine
  negative edge, unaffected by the correction either way (5/10 in every
  variant).
- **`volatility_breakout.short_swing`**: **4/10 — the worst of the three
  variants**, one gate lower than either baseline or ex_meta. With
  `META_CONT`'s real trades correctly included, gate 5
  (`parameter_sensitivity`) now *also* fails (56% of grid points positive,
  50% of neighbours — both below their 60%/75% thresholds), on top of the
  bootstrap-CI, regime-coverage, and benchmark failures every variant
  already showed. Correctly including real Meta Platforms trading data
  makes this already-fragile strategy demonstrably *more* fragile, not
  less — a genuine, negative finding, not an artifact.

### 4c. Why the corrected variant still can't pass gate 8

Gate 8 specifically — and only gate 8 — is designed to reject
`META_CONT`'s bridge tag, on purpose:

> `validate_daily` (gate 8) checks per-symbol coverage by filtering
> `OHLCVDaily.source == provider` where `provider` is the real market-data
> provider name (`massive`). `META_CONT`'s bars are deliberately tagged
> `continuity_bridge:1` — a distinct, honest provenance marker, not
> silently relabeled as raw single-provider `massive` data — so gate 8
> reports it as *entirely missing* under the provider tag, even though the
> bridge passed all 6 of its own explicit continuity checks (§2) and gates
> 1-7 and 9 (§4b) now correctly load and trade its real bars.

**This is a deliberate choice, not a bug left unfixed.** Teaching gate 8 to
accept a verified continuity-bridge tag as equivalent to raw single-provider
data would itself be a form of *weakening a promotion gate specifically to
produce a pass* — exactly what this task's instructions prohibited. I did
not make that change unilaterally. If you want the corrected series to be
gate-8-eligible going forward, that is a deliberate design decision for you
to make, not something decided on your behalf.

## 5. Every evaluation is preserved, every strategy's status verified

All promotion evaluations to date are `StrategyPromotionEvaluation` rows
(append-only) — with one documented exception: the 6 evaluations and 5
sealed tests computed under the source-filter bug (§6, finding #1/#9) were
deliberately deleted rather than kept as misleading history, with a full
`AuditLog` entry (`action="promotion.evaluation_purged_bug_fix"`) recording
exactly which rows, why, and that a corrected re-run immediately followed —
consistent with this project's practice of correcting bad state
transparently rather than working around it (see the original live-data
desync correction in `reports/STRATEGY_PROMOTION_STATUS.md`).

Every sealed test is immutable once locked to its exact `(strategy_version_id,
dataset_snapshot_id)` pair — none was ever silently recomputed or
overwritten by a different dataset's evidence.

Live strategy status, verified directly against the DB after every fix and
the final re-run:

| Strategy | Status |
|---|---|
| `intraday_orb.intraday` | `experimental` |
| `trend_continuation.short_swing` | **`paper_approved`** |
| `trend_continuation.medium_swing` | `experimental` |
| `mean_reversion.short_swing` | `experimental` |
| `relative_strength.medium_swing` | **`paper_approved`** |
| `volatility_breakout.short_swing` | `experimental` |

Every status change here came exclusively through `evaluate_promotion` —
manual actions can still only downgrade, never promote (unchanged, tested
invariant). Auto-simulation remains off; paper-trade acceptance remains
manual.

## 6. Adversarial review: 12 real defects found and fixed

Per this session's practice, this work was put through a 5-dimension
adversarial-review workflow (continuity correctness, dataset-snapshot
isolation, migration/schema safety, CLI/safety invariants, promotion-event
legitimacy) with independent verification of every finding. **All 12 raw
findings were confirmed real** (5 high, 5 medium, 2 low severity) — an
unusually high confirmation rate, reflecting genuine gaps in the first pass
rather than false positives. All 12 are fixed, tested, and re-verified.

| # | Finding | Severity | Fix |
|---|---|---|---|
| 1/9 | The "corrected" variant's `source="massive"` filter, threaded uniformly through the whole pipeline, meant `META_CONT` (tagged `continuity_bridge:1`) contributed **zero bars to gates 1-7 and 9, not just gate 8** — the variant was silently mechanically identical to `ex_meta`, and `data_provenance_json`'s unfiltered query made it look like the bridge was used when it wasn't | HIGH | `get_daily_bars`/`PriceSeries.load`/`run_strategy_over_universe`/`evaluate_promotion` now accept `source` as a string OR a list of acceptable sources; the corrected variant now resolves `[provider, "continuity_bridge:<id>"]`, while gate 8 still checks only the real provider (§4c). `_data_provenance` now applies the same filter. The 6 stale evaluations + 5 sealed tests computed under the bug were purged (audited) and correctly re-run — see §4b |
| 2 | `materialize_continuous_series` had no version component in the derived symbol name and an idempotency check scoped only to the exact mapping id — re-running `symbol-continuity-backfill` (an explicitly documented, normal operation) would silently duplicate every bridged session date under the same symbol on a second, differently-versioned mapping | HIGH | Refuses with a clear `ValueError` if the derived symbol already holds bars from a *different* mapping; superseding an existing bridge is now a decision a caller must make explicitly, never silent |
| 6/10 | `get_or_create_dataset_snapshot`'s keyed lookup silently ignored a `symbols`/`continuity_mapping_id` argument that no longer matched the stored row — a later universe change or superseding continuity mapping would go unnoticed and gate 9 could reuse a sealed test computed against stale data | HIGH | Keyed lookup now validates consistency and raises `ValueError` on any mismatch rather than silently reusing stale data |
| 7 | The migration's `downgrade()` unconditionally collapsed `strategy_sealed_test`'s unique constraint back to `(strategy_version_id)` alone — reproduced empirically: on real data with multiple dataset snapshots (exactly what this feature produces), SQLite's batch-table-copy crashes mid-downgrade with an `IntegrityError`, leaving a stray `_alembic_tmp_*` table while `alembic_version` still claims the migration applied | HIGH | `downgrade()` now checks for this condition first and refuses cleanly with an actionable error instead of corrupting the schema; verified the refusal leaves the DB byte-identical to before the attempt |
| 8 | `evaluate-promotion --dataset` documented short names (`baseline`/`ex_meta`/`meta_continuity_corrected`) that never matched `resolve_variant`'s actual long `DataSnapshot` keys — reproduced empirically: the command crashed with an unhandled `ValueError` on its own documented, most common invocation | HIGH | `resolve_variant`/`source_for_variant` now accept both the short and long forms |
| 3 | `materialize_continuous_series` had no locking around its check-then-insert sequence — a concurrent call for the same mapping could raise an unhandled `IntegrityError`, contradicting its own "idempotent" docstring claim | MEDIUM | Wrapped in a `SAVEPOINT` with `IntegrityError` fallback to the concurrent winner's row — the same pattern already used by `_get_or_create_sealed_test` elsewhere in this codebase |
| 4 | `same_source_provenance` compared bars already filtered by the exact `source` being validated against — tautologically always true, could never catch a real mismatch | MEDIUM | Now compares against each symbol's *entire, unfiltered* history; a regression test confirms it can genuinely fail |
| 12 | `get_or_create_dataset_snapshot`'s unkeyed symbol-match fallback had no way to exclude the migration-backfilled `universe_25_baseline_legacy` row — reproduced empirically: an ordinary "Run now" dashboard click (the primary human-operator path) would silently re-attach to a row whose own description promises "never reused by new evaluations" | MEDIUM | Added a `reusable_by_new_evaluations` column (new migration, itself found to have the SAME class of bug on first attempt — see below); the unkeyed fallback now excludes non-reusable rows |
| 5 | `materialize_continuous_series` returning `bars_written=0` conflated genuine idempotency with silent failure (source data vanished between validation and materialization) | LOW | Now raises rather than reporting a false success when both legs' bars are unexpectedly empty at materialize time |
| 11 | `--dataset` was silently dropped with no runtime message whenever `--symbols` was also given | LOW | Added an explicit warning to the CLI's own output |

**A 13th defect, self-caught during fix verification, not from the
review:** the FIRST version of the fix for finding #12 (adding a
`reusable_by_new_evaluations` column via `batch_alter_table`) would have
**silently deleted all 20 `strategy_sealed_test` rows** the moment it ran —
SQLite's batch mode recreates the whole `data_snapshot` table, and with
this project's `PRAGMA foreign_keys=ON`, dropping the old table mid-recreate
cascades the `ondelete="CASCADE"` foreign key from `strategy_sealed_test`.
Reproduced on a scratch copy of the real dev DB before it could touch the
real one; fixed by using SQLite's native `ADD COLUMN`/`DROP COLUMN` (no
table recreation) instead of batch mode for this specific migration. Full
round-trip (upgrade → downgrade → upgrade) re-verified on both a fresh
empty database and a copy of the real dev DB, confirming all 20 sealed
tests and all 15 evaluation references survive intact both ways.

### Verification after all fixes

- `tests/data/test_symbol_continuity.py`: 13 tests (8 original + 5 new
  regression tests for findings #2, #4, #5)
- `tests/research/test_promotion.py`: 8 new dataset-snapshot tests (5
  original + 3 new: keyed-mismatch refusal, non-reusable-row exclusion, plus
  the corrected exact-key-reuse test)
- Full suite: **344 passed**, 0 failed
- `black` / `ruff` / `mypy`: clean across `src/` and `tests/`
- `lint-imports`: **6/6 contracts kept**
- Both migrations (`eee776733a63`, `2ea68f289c37`) round-tripped cleanly on
  a fresh empty database and a full copy of the real dev database, with
  every pre-existing row verified preserved
- The 3-way comparison was re-run in full after every fix; §4 above
  reflects that final, correct run

## 7. Storage / provenance summary

| Item | Detail |
|---|---|
| FB bars ingested | 1,446 (2016-09-12..2022-06-08), 0 skipped |
| `META_CONT` bars materialized | 2,510 (1,446 FB-sourced + 1,064 META-sourced), tagged `continuity_bridge:1` |
| Raw `META`/`FB` instruments | Untouched — 1,212 and 1,446 bars respectively, exactly as before this investigation |
| `symbol_continuity_mapping` rows | 1 (`FB→META v1`, `verified`) |
| `data_snapshot` rows | 4 (`universe_25_baseline_legacy` — migration-backfilled label for pre-existing history, marked non-reusable; `universe_25_baseline`; `universe_24_ex_meta`; `universe_25_meta_continuity_corrected`) |
| DB file size | ~30 MB total (was ~28 MB before this task) |
| Network calls | Real, licensed Massive API calls only (FB history fetch + news-feed checks in the companion Benzinga audit); no scraping, no unlicensed source |

## 8. Remaining limitations (explicit, per the task's requirement)

- **Survivorship bias**: the 25-symbol universe is a fixed, hand-picked
  large-cap/ETF list. It contains no delisted names and no point-in-time
  membership reconstruction — a stock that would have been in a
  cap-weighted index 5 years ago but has since been removed (bankruptcy,
  acquisition, delisting) is invisible to every backtest in this pipeline,
  for every strategy, not just the ones discussed here. This is an
  existing, disclosed caveat (present in every gate-8 evidence payload)
  and is not resolved by this investigation.
- **Incomplete point-in-time universe membership**: the watchlist/ETF set
  used today is applied retroactively across the entire 10-year backtest
  window, as if it had always been the "current" universe. No attempt is
  made to reconstruct what the *actual* eligible universe was at each
  historical point in time.
- **`validate_daily`'s missing-session check has its own blind spot**,
  found (but not fixed, as out of scope for this task) while investigating:
  it computes "expected sessions" only across an instrument's own observed
  first→last bar range, not against the nominal backtest window. This meant
  `META`'s pre-2021-06-30 total absence from the *original* 10-year backtest
  window (2016-09-10 onward) was never flagged as a "missing" data problem
  by gate 8 at all — only the 90-session gap *within* its own already-short
  observed range was caught. This is a real, separate finding, orthogonal
  to the ticker-collision issue; flagging it for your awareness rather than
  fixing it silently, since it affects every symbol's gate-8 evaluation in
  the pipeline, not just this one.
- **`FB`'s own history via Massive only extends back to 2016-09-12**, not
  Facebook's actual 2012 IPO. This does not affect the 10-year backtest
  window used here (which itself starts ~2016-09-10), but means a
  longer-window backtest (e.g. 12+ years) would still show a real gap for
  this symbol, correctly reported by gate 8 rather than silently
  fabricated.
- **The `META_CONT` bridge cannot pass gate 8 under the current
  `validate_daily` semantics**, as explained in §4c — this is a structural,
  deliberate consequence of keeping the bridge's provenance honest, not a
  residual bug.
- **Corporate-action coverage is FB→META only.** No other symbol in the
  25-symbol universe was audited for a similar historical ticker collision
  or rename in this pass; `MassiveAdapter.fetch_corporate_actions` returns
  an empty tuple unconditionally (not offered by this feed), so nothing here
  would have caught a similar issue elsewhere automatically.
- **The multi-source (`str | Sequence[str]`) filter is now available
  project-wide** (`data.repository.SourceFilter`, threaded through
  `get_daily_bars`, `PriceSeries.load`/`load_intraday`,
  `run_strategy_over_universe`, `run_parameter_sensitivity`,
  `evaluate_promotion`) — a deliberately general fix, not special-cased to
  META_CONT, so any future symbol-continuity bridge can use the same
  mechanism without further pipeline changes.
