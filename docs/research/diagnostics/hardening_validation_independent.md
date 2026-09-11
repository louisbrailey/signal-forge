# `pipeline-hardening` — INDEPENDENT before/after gate-table equivalence validation

Branch `pipeline-hardening` (code state `a25d941`) against `main` as it stood at
`acf8cfb`, seven hardening items from `pipeline_hardening_spec.md`. This
document records a read-only differential validation: the same three promotion
evaluations run twice — once on `main`'s code, once on the branch's — against
two independent scratch copies of the live database, with the resulting
`gates_json` diffed field for field.

**This is a second, independent pass.** The implementing session's own record
lives beside it at `hardening_validation.md` (committed as `f1996c9`, amended
by `27ad7e6`, now on `main`). The two were produced separately, with separate
scratch databases, separate driver scripts and separate diff tooling, and they
**agree on every finding**; §10 reconciles them line by line. This file was
written under a distinct name specifically so the implementer's record is not
overwritten — see §10.1.

**Nothing here wrote to `data/signalforge.sqlite`.** Every evaluation ran against
a `.backup` copy under `$TMPDIR`, taken through a `mode=ro` URI. The live paper
probation and the background worker were untouched; the post-run row counts in
§6 confirm it.

**Headline.** Equivalence holds. Across 3 strategies × 10 gates: every `passed`
flag, every verdict, every numeric metric and every pre-existing structured
evidence field is identical. 659 identical leaf fields, 246 new fields, 0
removed fields, and exactly 6 changed fields — all six are the two prose
`detail` strings (gates 6 and 9) that the hardening was written to extend.

One **spec-vs-code divergence** was found independently and confirmed (§8): two
*stricter* gate-6 failure conditions that `pipeline_hardening_spec.md` §1.5
Change B and §8 book as adopted are not in the code. It is **not undisclosed** —
the implementer's record discloses it in its §1.1, with the reason. What remains
open is that the spec document itself was never corrected, so §1.5, §7 and §8
still credit gate 6 with two failure modes it does not have. Not a regression,
and it cannot cause a false PASS relative to `main`.

---

## 1. Environment and provenance

| | |
|---|---|
| Worktree | `/Users/louisbrailey/signal-forge/.claude/worktrees/wf_cfb7bab7-b74-1` |
| Branch code under test | `pipeline-hardening` @ `a25d941275d015445a72398dd76c57cd1a77ef12` |
| Baseline code | `main` @ `acf8cfb5c0c17310a81d04e0b9ab0b0776269578` |
| Branch HEAD when this was written | `27ad7e63eac8723c866fe1cad9de1c638c43f40e` (docs-only ahead of `a25d941`; `git diff a25d941..27ad7e6 -- src tests` is empty) |
| Interpreter | `/Users/louisbrailey/signal-forge/.venv/bin/python` (3.12.14) |
| BEFORE code | `/Users/louisbrailey/signal-forge/src/signalforge/__init__.py` (verified) |
| AFTER code | `…/worktrees/wf_cfb7bab7-b74-1/src/signalforge/__init__.py` (verified) |
| Effective research `config_hash` | `76500f3c44e761b64528562e0e16d828e790d864bc715f5dc62105454ffc96a3` (both runs) |
| Dataset | `ex_meta`, `dataset_snapshot_id = 3`, 24 symbols, source `massive` |
| Window | `2016-09-10 .. 2026-09-08` (pre-sealed span `2016-09-10 .. 2025-09-07`) |

### 1.1 A harness correction worth recording

The first AFTER attempt was run with the worktree as the working directory, as
originally planned. It produced a **false negative on every data-dependent
gate**: `validate_daily: FAIL (0/24 symbols have fixture data)`, 0 OOS trades,
gates 1-8 all FAIL. The cause is environmental, not a branch defect: the
worktree has no `.env`, so `get_settings().market_data_provider` fell back to
`fixture` instead of `massive` and no bars resolved.

That attempt was **discarded**, its scratch database deleted and recreated from
scratch, and the AFTER run repeated with the **main checkout as the working
directory** (so `.env` and every setting resolve exactly as in the BEFORE run)
and `PYTHONPATH` pointing at the worktree's `src` (so the *code* is the
branch's). Import provenance was asserted in-process on both sides. This makes
the code the only difference between the two runs, which is the comparison the
exercise needs. `.env` was deliberately **not** copied into the worktree — it
carries a provider API key.

### 1.2 The repository moved underneath this validation

Recorded because it bears on reproducibility, not because it invalidates
anything. While this validation was running, another session advanced the repo:

| time (UTC) | event |
|---|---|
| 04:56 | this validation starts; `main` @ `acf8cfb`, branch @ `a25d941` |
| 04:58 – 05:04 | **BEFORE** run executes against `main`'s working tree at `acf8cfb` |
| 05:06 – 05:14 | **AFTER** run executes against the worktree at `a25d941` |
| 05:13 | `f1996c9` lands on the branch — the implementer's `hardening_validation.md` (docs only) |
| 05:41 | `27ad7e6` lands on the branch — amends that document (docs only) |
| later | `bf0d605` (W1 150-symbol universe backfill) and `3f242ed` (**merge of `pipeline-hardening` into `main`**) land on `main` |

Consequences, each checked:

* **Neither BEFORE nor AFTER was contaminated.** The two later branch commits
  touch no `src/` or `tests/` file (`git diff --name-only a25d941..27ad7e6`
  returns docs only), and the BEFORE outputs are self-certifying: all three
  print `git_sha acf8cfb`, a gate-6 `detail` with no census clause, a gate-9
  `detail` reading `reused, locked on a prior evaluation`, and no sealed-look
  line — i.e. pre-hardening behaviour end to end.
* **The BEFORE baseline is no longer reproducible from `main`'s HEAD.** `main`
  is now `3f242ed`, which *contains* the hardening. Anyone re-running the
  BEFORE half must check out `acf8cfb` explicitly; running it from today's
  `main` would silently produce AFTER behaviour.
* **The live database changed, but not in any table this validation asserts
  on.** The W1 backfill added rows (`data_snapshot` is now 11). Re-checked
  read-only after the merge landed: `strategy_sealed_test` = 20,
  `strategy_promotion_evaluation` = 42, `scan_run` = 39 — the three counts §6
  pins are unmoved.

---

## 2. Every command run, in order

```sh
# ---- live-database baseline, read-only -------------------------------------
sqlite3 "file:/Users/louisbrailey/signal-forge/data/signalforge.sqlite?mode=ro" "
  select 'sealed_rows', count(*) from strategy_sealed_test;
  select 'eval_rows',   count(*) from strategy_promotion_evaluation;"
#   sealed_rows|20   eval_rows|42

# ---- scratch copies (never the live file) ----------------------------------
sqlite3 "file:/Users/louisbrailey/signal-forge/data/signalforge.sqlite?mode=ro" \
  ".backup $TMPDIR/scratch-before.sqlite"
sqlite3 "file:/Users/louisbrailey/signal-forge/data/signalforge.sqlite?mode=ro" \
  ".backup $TMPDIR/scratch-after.sqlite"      # recreated fresh after §1.1
sqlite3 "file:/Users/louisbrailey/signal-forge/data/signalforge.sqlite?mode=ro" \
  ".backup $TMPDIR/scratch-liveview.sqlite"   # pristine, for the scope invariants

# ---- import-provenance assertions ------------------------------------------
cd /Users/louisbrailey/signal-forge && unset PYTHONPATH
.venv/bin/python -c "import signalforge; print(signalforge.__file__)"
#   /Users/louisbrailey/signal-forge/src/signalforge/__init__.py

PYTHONPATH=/Users/louisbrailey/signal-forge/.claude/worktrees/wf_cfb7bab7-b74-1/src \
  /Users/louisbrailey/signal-forge/.venv/bin/python -c \
  "import signalforge; print(signalforge.__file__)"
#   …/worktrees/wf_cfb7bab7-b74-1/src/signalforge/__init__.py

# ---- BEFORE: main's code, scratch-before -----------------------------------
cd /Users/louisbrailey/signal-forge
unset PYTHONPATH
export DATABASE_URL="sqlite+pysqlite:///$TMPDIR/scratch-before.sqlite"
for S in trend_continuation.short_swing relative_strength.medium_swing \
         volatility_breakout.short_swing; do
  /usr/bin/time -p .venv/bin/python -m signalforge.cli evaluate-promotion \
    --strategy "$S" --dataset ex_meta --since 2016-09-10 --until 2026-09-08
done

# ---- AFTER: branch code, scratch-after -------------------------------------
cd /Users/louisbrailey/signal-forge     # main cwd -> identical .env / settings
export PYTHONPATH=/Users/louisbrailey/signal-forge/.claude/worktrees/wf_cfb7bab7-b74-1/src
export DATABASE_URL="sqlite+pysqlite:///$TMPDIR/scratch-after.sqlite"
for S in trend_continuation.short_swing relative_strength.medium_swing \
         volatility_breakout.short_swing; do
  /usr/bin/time -p .venv/bin/python -m signalforge.cli evaluate-promotion \
    --strategy "$S" --dataset ex_meta --since 2016-09-10 --until 2026-09-08
done

# ---- extract and diff gates_json -------------------------------------------
.venv/bin/python $TMPDIR/hv/dump_gates.py "$TMPDIR/scratch-before.sqlite" before_gates.json
.venv/bin/python $TMPDIR/hv/dump_gates.py "$TMPDIR/scratch-after.sqlite"  after_gates.json
.venv/bin/python $TMPDIR/hv/diff_gates.py before_gates.json after_gates.json
#   (dump_gates.py: SELECT over evaluations with id > 42 joined to
#    strategy_version/strategy; diff_gates.py: recursive leaf flatten of every
#    gate's dict, then set-compare keys and values.)

# ---- approval-scope invariants, pristine copy, both code paths -------------
export DATABASE_URL="sqlite+pysqlite:///$TMPDIR/scratch-liveview.sqlite"
unset PYTHONPATH;                            .venv/bin/python $TMPDIR/hv/check_scope.py
export PYTHONPATH=…/wf_cfb7bab7-b74-1/src;   .venv/bin/python $TMPDIR/hv/check_scope.py

# ---- gate-8 leakage coverage, branch code ----------------------------------
.venv/bin/python $TMPDIR/hv/check_leakage.py

# ---- targeted test suites, branch code -------------------------------------
PYTHONPATH=…/wf_cfb7bab7-b74-1/src .venv/bin/python -m pytest \
  tests/research tests/alerts tests/paper -q

# ---- live database re-checked, read-only, after everything -----------------
sqlite3 "file:/Users/louisbrailey/signal-forge/data/signalforge.sqlite?mode=ro" "
  select count(*) from strategy_sealed_test;
  select count(*) from strategy_promotion_evaluation;"
```

Both runs produced evaluation ids **43, 44, 45** in their own scratch database
(the live maximum is 42), so the two sides are directly comparable row for row.

---

## 3. Gate tables, before vs after

"equal" compares the rendered key-metric string on the two sides. **30 of 30
gate rows are equal.**

#### `trend_continuation.short_swing` — BEFORE eval 43 vs AFTER eval 43

Verdict BEFORE `PAPER_APPROVED` / AFTER `PAPER_APPROVED`. `spec_json_hash` = `2ed9743170bd3bbdb450ea03a004a7ffaeb64ccbbe6075db312ffd544072f382` on both sides.

| # | gate | pass B | pass A | key metrics BEFORE | key metrics AFTER | equal |
|---|---|:--:|:--:|---|---|:--:|
| 1 | `rolling_walkforward` | True | True | 4 folds; n_trades=[333, 367, 189, 280]; exp_r=[0.0906, -0.0014, -0.008, 0.3163] | 4 folds; n_trades=[333, 367, 189, 280]; exp_r=[0.0906, -0.0014, -0.008, 0.3163] | yes |
| 2 | `min_oos_trades` | True | True | n_oos_trades=341 (threshold 30) | n_oos_trades=341 (threshold 30) | yes |
| 3 | `net_expectancy` | True | True | expectancy_r=0.2648267109 (need > 0.0) | expectancy_r=0.2648267109 (need > 0.0) | yes |
| 4 | `bootstrap_ci` | True | True | ci low=0.1128771564 point=0.2648267109 high=0.4142840774 (need low > 0.02) | ci low=0.1128771564 point=0.2648267109 high=0.4142840774 (need low > 0.02) | yes |
| 5 | `parameter_sensitivity` | True | True | n_evaluable=9/9; positive_fraction=1.0; neighbour_positive_fraction=1.0; fragile=False; reasons=[] | n_evaluable=9/9; positive_fraction=1.0; neighbour_positive_fraction=1.0; fragile=False; reasons=[] | yes |
| 6 | `regime_coverage` | True | True | bull=939, bear=22, range=75 (floor 10) | bull=939, bear=22, range=75 (floor 10) | yes |
| 7 | `benchmark_comparison` | True | True | strategy sharpe=0.807 n_trades=1169 cagr=6.435% maxDD=27.825%; benchmark sharpe=0.719 cagr=13.36% | strategy sharpe=0.807 n_trades=1169 cagr=6.435% maxDD=27.825%; benchmark sharpe=0.719 cagr=13.36% | yes |
| 8 | `data_quality_and_leakage` | True | True | validate_daily=True, leakage_error=None | validate_daily=True, leakage_error=None | yes |
| 9 | `sealed_final_test` | True | True | sealed_test_id=11, window=2025-09-08..2026-09-08, n_trades=109, expectancy_r=0.2982 | sealed_test_id=11, window=2025-09-08..2026-09-08, n_trades=109, expectancy_r=0.2982 | yes |
| 10 | `live_paper_probation` | True | True | enabled=True, downgrade_z=-2.0, disable_z=-3.5 | enabled=True, downgrade_z=-2.0, disable_z=-3.5 | yes |

#### `relative_strength.medium_swing` — BEFORE eval 44 vs AFTER eval 44

Verdict BEFORE `PAPER_APPROVED` / AFTER `PAPER_APPROVED`. `spec_json_hash` = `dfe696b662dd02b8fa3a02ce5b987c6eade84a40d88c1a2d8d52e206cb6f6c32` on both sides.

| # | gate | pass B | pass A | key metrics BEFORE | key metrics AFTER | equal |
|---|---|:--:|:--:|---|---|:--:|
| 1 | `rolling_walkforward` | True | True | 4 folds; n_trades=[115, 170, 113, 168]; exp_r=[0.1626, 0.1246, 0.5445, 0.0975] | 4 folds; n_trades=[115, 170, 113, 168]; exp_r=[0.1626, 0.1246, 0.5445, 0.0975] | yes |
| 2 | `min_oos_trades` | True | True | n_oos_trades=197 (threshold 30) | n_oos_trades=197 (threshold 30) | yes |
| 3 | `net_expectancy` | True | True | expectancy_r=0.3004072805 (need > 0.0) | expectancy_r=0.3004072805 (need > 0.0) | yes |
| 4 | `bootstrap_ci` | True | True | ci low=0.0901373239 point=0.3004072805 high=0.5045817820 (need low > 0.02) | ci low=0.0901373239 point=0.3004072805 high=0.5045817820 (need low > 0.02) | yes |
| 5 | `parameter_sensitivity` | True | True | n_evaluable=9/9; positive_fraction=1.0; neighbour_positive_fraction=1.0; fragile=False; reasons=[] | n_evaluable=9/9; positive_fraction=1.0; neighbour_positive_fraction=1.0; fragile=False; reasons=[] | yes |
| 6 | `regime_coverage` | True | True | bull=466, bear=11, range=89 (floor 10) | bull=466, bear=11, range=89 (floor 10) | yes |
| 7 | `benchmark_comparison` | True | True | strategy sharpe=1.171 n_trades=566 cagr=6.679% maxDD=17.835%; benchmark sharpe=0.719 cagr=13.36% | strategy sharpe=1.171 n_trades=566 cagr=6.679% maxDD=17.835%; benchmark sharpe=0.719 cagr=13.36% | yes |
| 8 | `data_quality_and_leakage` | True | True | validate_daily=True, leakage_error=None | validate_daily=True, leakage_error=None | yes |
| 9 | `sealed_final_test` | True | True | sealed_test_id=14, window=2025-09-08..2026-09-08, n_trades=16, expectancy_r=0.2935 | sealed_test_id=14, window=2025-09-08..2026-09-08, n_trades=16, expectancy_r=0.2935 | yes |
| 10 | `live_paper_probation` | True | True | enabled=True, downgrade_z=-2.0, disable_z=-3.5 | enabled=True, downgrade_z=-2.0, disable_z=-3.5 | yes |

#### `volatility_breakout.short_swing` — BEFORE eval 45 vs AFTER eval 45

Verdict BEFORE `NO TRADE — insufficient evidence or poor risk/reward` / AFTER `NO TRADE — insufficient evidence or poor risk/reward`. `spec_json_hash` = `2ef86785839bfd6ae320094bf3626642077212e45eaa0fd424f8862bbdf45e20` on both sides.

| # | gate | pass B | pass A | key metrics BEFORE | key metrics AFTER | equal |
|---|---|:--:|:--:|---|---|:--:|
| 1 | `rolling_walkforward` | True | True | 4 folds; n_trades=[36, 98, 34, 43]; exp_r=[0.4745, 0.1111, 0.0389, 0.1286] | 4 folds; n_trades=[36, 98, 34, 43]; exp_r=[0.4745, 0.1111, 0.0389, 0.1286] | yes |
| 2 | `min_oos_trades` | True | True | n_oos_trades=51 (threshold 30) | n_oos_trades=51 (threshold 30) | yes |
| 3 | `net_expectancy` | True | True | expectancy_r=0.0613487388 (need > 0.0) | expectancy_r=0.0613487388 (need > 0.0) | yes |
| 4 | `bootstrap_ci` | False | False | ci low=-0.3552611586 point=0.0613487388 high=0.4978781048 (need low > 0.02) | ci low=-0.3552611586 point=0.0613487388 high=0.4978781048 (need low > 0.02) | yes |
| 5 | `parameter_sensitivity` | True | True | n_evaluable=9/9; positive_fraction=0.667; neighbour_positive_fraction=0.75; fragile=False; reasons=[] | n_evaluable=9/9; positive_fraction=0.667; neighbour_positive_fraction=0.75; fragile=False; reasons=[] | yes |
| 6 | `regime_coverage` | False | False | bull=167, bear=0, range=30 (floor 10) | bull=167, bear=0, range=30 (floor 10) | yes |
| 7 | `benchmark_comparison` | False | False | strategy sharpe=0.666 n_trades=211 cagr=1.935% maxDD=5.849%; benchmark sharpe=0.719 cagr=13.36% | strategy sharpe=0.666 n_trades=211 cagr=1.935% maxDD=5.849%; benchmark sharpe=0.719 cagr=13.36% | yes |
| 8 | `data_quality_and_leakage` | True | True | validate_daily=True, leakage_error=None | validate_daily=True, leakage_error=None | yes |
| 9 | `sealed_final_test` | False | False | sealed_test_id=15, window=2025-09-08..2026-09-08, n_trades=10, expectancy_r=-0.0979 | sealed_test_id=15, window=2025-09-08..2026-09-08, n_trades=10, expectancy_r=-0.0979 | yes |
| 10 | `live_paper_probation` | True | True | enabled=True, downgrade_z=-2.0, disable_z=-3.5 | enabled=True, downgrade_z=-2.0, disable_z=-3.5 | yes |

---

## 4. Field-level diff of `gates_json`

Method: each evaluation's `gates_json` was flattened to leaf paths
(`gateN_name → detail`, `evidence.…`, list elements indexed) and the two key
sets compared.

```
TOTALS: 659 identical leaf fields, 6 changed, 246 new, 0 removed
```

| gate | identical | changed | new | removed |
|---|--:|--:|--:|--:|
| 1 `rolling_walkforward` | 28 | 0 | 0 | 0 |
| 2 `min_oos_trades` | 6 | 0 | 0 | 0 |
| 3 `net_expectancy` | 6 | 0 | 0 | 0 |
| 4 `bootstrap_ci` | 8 | 0 | 0 | 0 |
| 5 `parameter_sensitivity` | 96 (95 for v6) | 0 | 2 | 0 |
| 6 `regime_coverage` | 7 | 1 (`detail`) | 22 | 0 |
| 7 `benchmark_comparison` | 25 | 0 | 0 | 0 |
| 8 `data_quality_and_leakage` | 7 | 0 | 0 | 0 |
| 9 `sealed_final_test` | 29 | 1 (`detail`) | 58 | 0 |
| 10 `live_paper_probation` | 8 | 0 | 0 | 0 |

Per-strategy top-level fields — `version`, `window`, `dataset_snapshot_id`,
`passed`, `config_hash`, `spec_json_hash`, `verdict`, `sealed_test_id` —
**identical for all three strategies**.

### 4.1 The 6 changed fields — all `detail` prose, all additive

Gates 6 and 9 carry their new reporting in the `detail` string, which is a
pre-existing field. Nothing else changed.

**Gate 6 `detail` (×3).** The BEFORE string is a **strict prefix** of the AFTER
string on all three strategies (verified programmatically; +176 / +170 / +172
characters appended). The original clause is byte-identical; the census clause
is appended:

```
before: trades per regime — bull 939, bear 22, range 75 (need >= 10 each in 3 of 3 regimes; 3/3 met)
after : …same… ; unbucketed: 133 inside the 200-session proxy warmup (ends 2017-08-02),
        0 with no proxy bar, 0 with an unrecognised label — 133 of 1169 trades (11.38%)
        are in no regime bucket
```

**Gate 9 `detail` (×3).** Two edits: the seal note is reworded, and the
sealed-look line is appended. The sealed window, trade count and expectancy in
the string are unchanged.

```
before: sealed window 2025-09-08..2026-09-08 (reused, locked on a prior evaluation;
        never recomputed once locked): 109 trades, net expectancy +0.2982R …
after : sealed window 2025-09-08..2026-09-08 (LOCKED REPLAY of sealed test 11 locked at
        2026-09-08T09:26:25.384177+00:00 — NOT created by this run; never recomputed once
        locked): 109 trades, net expectancy +0.2982R …; replay of look 3 of this strategy
        family — no new look taken (4 prior sealed tests: ids 1, 6, 11, 16; replayed id 11)
```

This is the only place where a *pre-existing* field's value differs. It is
prose, it is the intended payload of items 1, 4 and 6, and no consumer parses
it — gate 9's structured evidence now carries `reused` / `created_by_this_run`
as booleans precisely so nothing has to.

### 4.2 The 246 new fields

Deduplicated paths (indices collapsed):

* **Gate 5** (2 per strategy) — `evidence.axis_moved.<axis>` for each of the two
  shipped axes. `evidence.inert_axes` is present on both branches of the diff as
  an **empty list** on all three strategies, so it contributes no leaf.
* **Gate 6** (22) — `evidence.n_trades_considered`, and under
  `evidence.unbucketed`: `warmup`, `no_proxy_bar`, `unlabelled`, `total`,
  `share_of_trades`, `warmup_last_date`, `proxy_first_bar`, `proxy_bars`,
  `trend_lookback_sessions`, `census_closes`, plus the ten
  `extended_labelling.*` diagnostic keys.
* **Gate 9** (58) — `evidence.reused`, `created_by_this_run`,
  `sealed_evaluated_at`, `sealed_strategy_version_id`,
  `evaluated_strategy_version_id`, and the whole `sealed_look_ledger`
  (`strategy_key`, `k_prior`, `this_look`, `reused_this_run`,
  `total_sealed_tests`, and 4 × 12 per-look fields).

No pre-existing field was removed anywhere.

---

## 5. Item-by-item observations

### Item 1 — gate-6 warm-up census

Bucket counts are byte-identical to `main`'s loop on all three strategies
(939/22/75, 466/11/89, 167/0/30), and `covered` is unchanged, so the pass
computation is provably scoring-neutral here. The census closes on all three
(`census_closes: true`; bucketed + unbucketed == `n_trades_considered`).

| strategy | trades | bucketed | warmup | no proxy bar | unlabelled | share unbucketed |
|---|--:|--:|--:|--:|--:|--:|
| `trend_continuation.short_swing` | 1169 | 1036 | 133 | 0 | 0 | 11.38% |
| `relative_strength.medium_swing` | 566 | 566 | 0 | 0 | 0 | 0.00% |
| `volatility_breakout.short_swing` | 211 | 197 | 14 | 0 | 0 | 6.64% |

The 133 previously-silent v2 trades are now named, which was the point of the
item. `no_proxy_bar == 0` everywhere, as the spec predicted.

**Extended labelling (spec §1.5 Change C) is inert on snapshot 3, as predicted
and now measured in-band:** `requested_from: 2015-09-26`, `proxy_bars: 2234`,
`bars_gained: 0`, `identical_to_strict: true`, `used_for_scoring: false` on all
three. The short-circuit ("when the extension gains no bars … do not pay for a
second `label_regimes` pass") is therefore the path actually taken.

### Item 2 — declared gate-5 axes with a no-op check

No strategy declares `sensitivity_axes()` (grep over
`src/signalforge/research/strategies/`: only the Protocol definition). Every
shipped v0.1.0 grid is therefore unedited — 9 points, 2 axes — which the
diff confirms: all 95-96 gate-5 leaf fields identical, only `axis_moved` added.

| strategy | `axis_moved` | `inert_axes` | `fragile` |
|---|---|---|---|
| `trend_continuation.short_swing` | `sma_fast: true`, `stop_atr: true` | `[]` | false |
| `relative_strength.medium_swing` | `excess_return_min: true`, `lookback: true` | `[]` | false |
| `volatility_breakout.short_swing` | `contraction_max: true`, `stop_atr: true` | `[]` | false |

4 of 4 live axes on the two approved strategies move, so the new failure mode
is a no-op on them — matching the spec's §2.3 prediction from the stored grids.

The mechanism does fire when a grid genuinely tests nothing: the discarded
zero-data run of §1.1 printed *"axis 'sma_fast' does not change OOS trade count
or expectancy — the grid tested nothing on it"* for both axes on a degenerate
0/9-evaluable grid. Unintended, but a useful live demonstration that the check
is wired to the real gate-5 path and not only to fixtures.

### Item 3 — `approval_scope` universe compare + deterministic ordering

Run against the pristine `scratch-liveview` copy with both code paths:

| | `main` | branch |
|---|---|---|
| `approved_scopes(session, 2)` | evals **20, 32** | evals **32, 20** |
| `approved_scopes(session, 5)` | evals **23, 35** | evals **35, 23** |
| all scopes' `dataset_snapshot_id` | 3 | 3 |
| all scopes' `sources` | `{massive}` | `{massive}` |
| all scopes' universe == the live 24-symbol set | true | true |
| v2 scopes' `spec_json_hash` == `2ed97431…f382` | true | true |
| v5 scopes' `spec_json_hash` == `dfe696b6…6c32` | true | true |
| `scan_scope_matches(…3, 11b54aee…, massive[, 24 symbols])` | **True** (no `universe` arg exists) | **True** |

Membership is unchanged; only the order flipped, to newest-passing-first, as
specified. **Each version has two approved scopes, not one** — both on
`dataset_snapshot_id = 3`, i.e. exactly one distinct snapshot. This matches
`pipeline_hardening_spec.md` §3.3 ("for v2, evaluations 20 and 32, and for v5,
23 and 35"); a validation brief that expects "exactly one scope" is reading the
snapshot count, not the row count.

The universe conjunct is now exercised and satisfied: the live approved-scope
scan runs (ids 5 and 6, `config_hash 11b54aee64dbc265…`, `dataset_snapshot_id 3`,
`source massive`) carry a 24-symbol `universe_json` **set-equal** to all four
approved scopes' universes, so `scan_scope_matches` stays `True` for both
approved strategies. No verdict moves.

*Standing, pre-existing, and not changed by this branch* (spec §3.3, §10): the
latest live scan run (id 33) carries `config_hash 76500f3c44e761b6…`, not the
`11b54aee64dbc265…` both approvals were recorded under, so on the *current*
config both approved strategies remain out of live scope. That is an operator
decision, not a branch defect, and the universe comparison neither causes nor
cures it.

### Item 4 — sealed-look counter

Exactly what the CLI printed, verbatim, one line per strategy:

```
  sealed looks: this is replay of look 3 of this strategy family — no new look taken
                (4 prior sealed tests: ids 1, 6, 11, 16; replayed id 11) [trend_continuation.short_swing]
  sealed looks: this is replay of look 3 of this strategy family — no new look taken
                (4 prior sealed tests: ids 4, 9, 14, 19; replayed id 14) [relative_strength.medium_swing]
  sealed looks: this is replay of look 3 of this strategy family — no new look taken
                (4 prior sealed tests: ids 5, 10, 15, 20; replayed id 15) [volatility_breakout.short_swing]
```

**`k = 4` prior sealed tests for each of the three families**, as the spec
predicted, with the exact id lists §4.2 predicted for v2 (1, 6, 11, 16) and v5
(4, 9, 14, 19). The same line appears inside gate 9's `detail`, derived from the
same ledger, so the printed count cannot disagree with the stored evidence.

The stored ledger agrees: `k_prior = 4`, `total_sealed_tests = 4`,
`reused_this_run = true`, `this_look = 3` for all three. `this_look = 3` is the
**replayed row's own index** in the family ledger (id 11 is the third of 1, 6,
11, 16), not `k+1` — a replay takes no new look, which is the whole point of
commit `82cddcd`. Worth flagging for report authors: "replay of look 3 … 4 prior
sealed tests" reads oddly at a glance but is internally consistent, and the
convention (`k = 4`, a genuinely new look would be look 5) still contradicts
MAP §4.2 item 10's "look 6". That convention clash is unresolved and is a
documentation decision, not a code defect.

### Item 5 — gate-7 docstring

No executable change; `config_hash` is unmoved
(`76500f3c44e761b6…` on both sides). The corrected comment is confirmed by the
evidence: gate 7 reports `n_trades = 1169` for v2 while gate 2 reports
`n_oos_trades = 341`, i.e. gate 7 measures every pre-sealed trade, exactly as
the new wording says and the old wording denied.

### Item 6 — sealed-test LOCKED-replay report

All three evaluations replayed a locked row. Structured evidence:

| strategy | `sealed_test_id` | `reused` | `created_by_this_run` | `sealed_evaluated_at` | sealed / evaluated version id |
|---|--:|---|---|---|---|
| `trend_continuation.short_swing` | 11 | true | false | `2026-09-08T09:26:25.384177+00:00` | 2 / 2 |
| `relative_strength.medium_swing` | 14 | true | false | `2026-09-08T09:27:22.847931+00:00` | 5 / 5 |
| `volatility_breakout.short_swing` | 15 | true | false | `2026-09-08T09:27:51.364495+00:00` | 6 / 6 |

The `reused` boolean is now machine-readable instead of buried in prose, and
`sealed_strategy_version_id == evaluated_strategy_version_id` on all three makes
the "a v0.2.0 cannot inherit a v0.1.0's sealed row" claim checkable rather than
merely true. No new sealed row was created: `strategy_sealed_test` still holds
20 rows in the AFTER scratch after three evaluations.

### Item 7 — leakage self-check additions

`LEAKAGE_FEATURE_CHECKS` is a module-level constant of **8** entries. Run
against the same SPY series gate 8 uses (2234 bars, `2016-10-17 .. 2025-09-05`,
source `massive`):

```
  [PASS] sma(50)                        [PASS] atr_contraction(10,50)
  [PASS] rolling_return(20)             [PASS] atr_contraction(10,50) @ t-5
  [PASS] atr(14)                        [PASS] donchian_high(20)
  [PASS] realized_vol(20)               [PASS] true_range
_leakage_self_check(SPY) -> None
```

All four **new** functions (`atr_contraction`, its t-5 lagged form,
`donchian_high`, `true_range`) are present and pass `assert_no_lookahead`. Gate
8 reported `leakage self-check: clean` on all three AFTER evaluations, so the
expanded list ran inside the real pipeline, not only in this probe. No finding
against `features/daily.py`.

---

## 6. Invariants checklist

| # | invariant | result |
|--:|---|---|
| 1 | Every pre-existing **structured** `gates_json` field identical | **PASS** — 659 identical leaves, 0 removed, 0 changed outside `detail` |
| 2 | Only new reporting fields differ | **PASS with a noted nuance** — 246 new fields, and the 6 changed fields are the gate-6/gate-9 `detail` prose strings, which *are* the new reporting. Gate 6's before-string is a strict prefix of its after-string; gate 9's differs only in the seal-note clause and the appended sealed-look line |
| 3 | Version 2 still `passed = True` | **PASS** — `PAPER_APPROVED`, 10/10 gates |
| 4 | Version 5 still `passed = True` | **PASS** — `PAPER_APPROVED`, 10/10 gates |
| 5 | v6 gate-5 `neighbour_positive_fraction` reads exactly 0.750 | **PASS** — `0.75` stored (`round(…, 4)`), printed as `75%`, byte-identical before and after |
| 6 | v5 gate-6 bear bucket reads exactly 11 | **PASS** — `{'bull': 466, 'bear': 11, 'range': 89}`, both sides |
| 7 | v2 `spec_json_hash` == `2ed9743170bd3bbdb450ea03a004a7ffaeb64ccbbe6075db312ffd544072f382` | **PASS** — byte-identical, both sides |
| 8 | v5 `spec_json_hash` == `dfe696b662dd02b8fa3a02ce5b987c6eade84a40d88c1a2d8d52e206cb6f6c32` | **PASS** — byte-identical, both sides |
| 9 | `approved_scopes(session, 2)` / `(session, 5)` unchanged on `dataset_snapshot_id = 3` | **PASS on membership; wording corrected** — two scopes each (v2: 20, 32; v5: 23, 35), all on snapshot 3, i.e. exactly one distinct snapshot. Order flips to newest-first by design |
| 10 | `scan_scope_matches` still `True` for the live approved-scope scan | **PASS** — `True` on both code paths for dataset 3, `config_hash 11b54aee64dbc265…`, source `massive`, and (branch only) the 24-symbol universe |
| 11 | The live scan's symbol set equals the scope's `universe_json` | **PASS** — scan runs 5, 6 and 33 all set-equal to all four approved scopes' universes |
| 12 | Sealed-look counter says `k = 4` prior for each family | **PASS** — see §5 item 4 for the verbatim CLI lines |
| 13 | LOCKED replay reported for these re-runs | **PASS** — all three, with id and original `evaluated_at`, and no new sealed row |
| 14 | Leakage self-check ran the four new feature functions and passed | **PASS** — 8/8 checks clean; gate 8 `leakage_error = None` on all three |
| 15 | Live DB `strategy_sealed_test` still 20 rows | **PASS** — 20, `max(id) = 20` |
| 16 | Live DB `strategy_promotion_evaluation` still 42 rows | **PASS** — 42, `max(id) = 42` |
| 17 | No write to `data/signalforge.sqlite` | **PASS** — every run used a `$TMPDIR` `.backup` copy via `DATABASE_URL`; counts above re-checked read-only after everything, including after another session merged the branch to `main` |
| 18 | Branch test suites green | **PASS** — 195 passed, 0 failed across `tests/research`, `tests/alerts`, `tests/paper` (§9) |

Post-run scratch state, for contrast: `scratch-after.sqlite` holds **45**
evaluations (3 new) and still **20** sealed tests — writes landed where they
were supposed to, and no new sealed look was taken anywhere.

---

## 7. Timing

| phase | wall clock |
|---|--:|
| BEFORE `trend_continuation.short_swing` | 74.60 s |
| BEFORE `relative_strength.medium_swing` | 141.52 s |
| BEFORE `volatility_breakout.short_swing` | 148.08 s |
| **BEFORE total** | **364.20 s** |
| AFTER `trend_continuation.short_swing` | 106.45 s |
| AFTER `relative_strength.medium_swing` | 109.45 s |
| AFTER `volatility_breakout.short_swing` | 252.80 s |
| **AFTER total** | **468.70 s** |
| discarded AFTER attempt (§1.1) | ~21 s |
| three 384 MB `.backup` copies | ~11 s |
| `tests/research` + `tests/alerts` + `tests/paper` | ~13 min |
| **total validation wall clock** | **~50 min** (04:56:49Z → 05:46:34Z) |

Per-strategy wall clock is not a usable cost measurement here: the two runs
overlapped with a background `pytest` sweep and with each other's page-cache
effects, and the machine also hosts the live worker. The +104 s AFTER total is
therefore **not** attributable to the branch. The one cost the branch does add
per evaluation is bounded and known: one extra `PriceSeries.load` of the proxy
for the extended-labelling diagnostic, which on snapshot 3 gains 0 bars and
short-circuits before a second `label_regimes` pass.

---

## 8. Finding — specified gate-6 failure conditions are not implemented, and the spec was never corrected

**Severity: low. It cannot cause a false PASS relative to `main` (the branch is
strictly no laxer than `main` here), and it is disclosed in the implementer's
record. What is open is the spec document, not the code.**

`pipeline_hardening_spec.md` specifies two *stricter* gate-6 conditions and
books both in its R4 ledger as adopted:

* §1.5 Change A: *"Assert the census closes … If it does not, gate 6 **fails**
  with the discrepancy in `detail` — a trade must never vanish."*
* §1.5 Change B: *"`gate6_pass = bool(covered >= th.min_regimes_covered and
  no_proxy_bar == 0)`"*, with §8 listing it as **stricter — new failure
  condition**, and §7 listing "Gate 6 `no_proxy_bar == 0` hard fail — satisfied
  (0)" for both approved strategies.

The implementation reports both and fails on neither:

```
src/signalforge/research/promotion.py:1131
    gate6_pass = bool(covered >= th.min_regimes_covered)
```

`census.closes` is computed (`:377-382`) and surfaced as
`evidence.unbucketed.census_closes`, and `_unbucketed_detail` appends a loud
`— CENSUS DOES NOT CLOSE: …` clause when it is false, but neither feeds
`gate6_pass`. `no_proxy_bar` is counted and reported and never gated on. The
test suite matches the code, not the spec: the spec's
`test_gate6_fails_when_a_trade_has_no_proxy_bar` does not exist; in its place is
`test_gate6_census_reports_a_discrepancy_instead_of_hiding_it`.

This is a deliberate choice, not an oversight, and it is **disclosed**: commit
`b9eb2d7`'s message says "none of which moves a threshold or **changes a pass
condition** (R4)", and the implementer's `hardening_validation.md` §1.1
deviation 1 states it plainly — their task brief said "Do not change the pass
condition", and they note adopting Change B later is a one-line change with the
reporting already in place. This independent pass found the same gap from the
code before reading their record, which is worth recording as corroboration.

What remains open is the **spec document**. `pipeline_hardening_spec.md` §1.5,
§7 and §8 still describe gate 6 as having two new ways to fail that it does not
have, and §7's per-strategy table lists "Gate 6 `no_proxy_bar == 0` hard fail |
satisfied (0)" as though the condition exists. Either the code adopts them or
the spec retracts them; leaving both standing means a future reader will credit
gate 6 with integrity checks it does not enforce. Today the two variants are
indistinguishable on the data (`no_proxy_bar == 0` everywhere on snapshot 3), so
the cost of the ambiguity is deferred, not avoided.

Reported, not fixed, per the rules of this exercise. Nothing under `src/` was
modified.

### 8.1 Non-defects, recorded so they are not re-discovered

* **`git_sha` differs between the two runs** (`acf8cfb` vs `a25d941`). Expected
  and unavoidable — it is the checkout's HEAD, it is excluded from
  `spec_json_hash`, and it is not part of the gate evidence compared above.
* **`config_hash` is `76500f3c44e761b6…`, not the approvals' `11b54aee64dbc265…`.**
  Both runs use the current effective research config, which changed at the
  2026-09-10 probation activation. Identical on both sides, so it does not
  affect the comparison; it is the pre-existing live-scope issue of spec §3.3.
* **The §1.1 false negative** is an `.env` resolution artefact of running from
  the worktree, not a branch behaviour.

---

## 9. Test suites

`tests/research`, `tests/alerts` and `tests/paper` were run against the branch
code (`PYTHONPATH` at the worktree's `src`):

```
PYTHONPATH=…/wf_cfb7bab7-b74-1/src .venv/bin/python -m pytest \
  tests/research tests/alerts tests/paper -q
```

**195 tests, 195 passed, 0 failed, exit 0.** This covers all 37 tests the branch
adds, including the two R7 guards that pin the live approved spec hashes as
literals (`test_declaring_axes_does_not_change_spec_json_hash`) and the shipped
nine-point grids (`test_undeclared_strategies_keep_their_shipped_nine_point_grid`).

`tests/deploy` was not run here. The implementer's record §6.2 documents two
worktree-only failures there
(`test_program_arguments_start_with_an_absolute_venv_bin_path`, both plist
parametrisations), caused by the test deriving `VENV_BIN` from the repo root it
runs in; they pass from the main checkout. Nothing in this branch touches that
path, and this pass did not re-verify it.

---

## 10. Reconciliation with the implementer's record

`hardening_validation.md` (commits `f1996c9`, `27ad7e6`) is the implementing
session's own before/after record. It was produced independently of this one —
different scratch database names, a different driver script, a different diff
script — and this pass did not read it until after its own numbers were fixed.

**Every overlapping claim agrees.** Same verdicts (v2 and v5 `PAPER_APPROVED`,
v6 `NO TRADE` failing gates 4, 6, 7, 9); same gate values on both sides; same
`0.750` and same bear bucket `11`; same bucket/warmup census (1169 · 133 · 0,
566 · 0 · 0, 211 · 14 · 0) and same `census_closes: true`; same
`bars_gained: 0` / `identical_to_strict: true` extended-labelling diagnostic;
same `inert_axes: []` with every axis moving; same gate-9 replay table (rows
11, 14, 15, `k_prior = 4`, "replay of look 3"); same conclusion that the only
pre-existing fields whose content moves are the gate-6 and gate-9 `detail`
strings; same live-DB invariants (20 / 42).

Differences are of granularity and coverage, not of substance:

| | this pass | implementer's record |
|---|---|---|
| new-field count | 246 (flattened leaves) | "two / two / six" (top-level `evidence` keys) — the same fields counted at a different depth |
| identical-field count | 659 leaves, stated explicitly | stated per gate as "IDENTICAL" |
| repo gates | `tests/research` + `tests/alerts` + `tests/paper` only | full suite plus black / ruff / mypy / lint-imports / detect-secrets |
| approved-scope invariants | `approved_scopes` and `scan_scope_matches` executed on **both** code paths against a pristine copy (§5 item 3) | covered as a standing caveat, not re-executed |
| gate-6 Change B | found independently from the code, §8 | disclosed up front, §1.1 deviation 1 |

Two small corrections this pass can offer the shared record:

1. **`approved_scopes` returns two scopes per approved version, not one** — v2:
   evals 32, 20; v5: evals 35, 23 — all four on `dataset_snapshot_id = 3`.
   Anything phrased as "exactly one scope" is counting distinct snapshots.
2. **The ordering change is observable**, even though membership is not: the
   list order flips from `[20, 32]` to `[32, 20]` (and `[23, 35]` to
   `[35, 23]`) under the new `order_by`. Since `paper_probation` selects via
   `scopes[0].dataset_snapshot_id`, this is exactly the latent behaviour the
   item was meant to make deterministic; it is invisible today only because
   both scopes share snapshot 3.

### 10.1 Why this file has a different name

The task that produced this document specified the path
`docs/research/diagnostics/hardening_validation.md`. By the time it was written
that path was occupied by the implementer's record, committed during this
session (`f1996c9` at 05:13 UTC) and since merged to `main` via `3f242ed`.
Writing here would have overwritten a document that is already on `main`, so
the independent report was given its own name and the implementer's file was
restored untouched (`git checkout --`). Rename or merge the two at the
operator's discretion; nothing in either is lost.

---

## 11. Conclusion

The seven hardening items are **behaviour-preserving on the two `PAPER_APPROVED`
strategies and on the zero-margin `volatility_breakout` case**. Both approvals
survive with 10/10 gates, identical metrics and byte-identical `spec_json_hash`
values; the zero-margin readings the exercise pinned (`0.750` neighbour
fraction, bear bucket `11`) are unmoved; the approved-scope path still resolves
`True` with the universe now genuinely compared; 195 targeted tests pass; and
the live database is untouched at 20 sealed tests and 42 evaluations.

Two things need a decision rather than a re-run:

1. the §8 spec/code divergence on gate 6's two specified failure conditions —
   the code is disclosed-and-deliberate, the spec is stale;
2. the pre-existing `config_hash` mismatch (§5 item 3) that keeps both approved
   strategies out of live scope, which this branch neither causes nor cures.
