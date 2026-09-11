# Promotion-pipeline hardening — implementation and validation record

Branch `pipeline-hardening`. Implements the seven items of
`docs/research/diagnostics/pipeline_hardening_spec.md` (§1–§6) plus the gate-8
addition from `docs/research/designs/volatility_breakout_short_swing.md`
§2.5/§7.3.

Claims are labelled **FACT** (reproduced by a command recorded below) or
**HYPOTHESIS**. Nothing here was run against the live database with write
access: every writing command ran against a scratch copy taken read-only.

---

## 0. Result in one paragraph

**FACT.** On the `ex_meta` snapshot over `2016-09-10 .. 2026-09-08`, the three
strategies evaluated before and after the change produce **identical gate
verdicts and identical values for every pre-existing `gates_json` field**.
Versions 2 (`trend_continuation.short_swing`) and 5
(`relative_strength.medium_swing`) still PASS all ten gates; version 6
(`volatility_breakout.short_swing`) still fails the same four (4, 6, 7, 9).
The only differences are **new** evidence keys and two **appended** clauses on
the gate-6 and gate-9 `detail` strings, both of which the spec mandates
(§1.5 Change A, §4.2). `spec_json_hash` is byte-identical for versions 2, 5
and 6, and matches the values stored on the live approving evaluations 32/35/36.
The live database still holds exactly 20 `strategy_sealed_test` rows, 42
promotion evaluations and 0 paper trades — unchanged.

---

## 1. What was implemented

| # | Item | Files | R4 direction |
|---|---|---|---|
| 1 | Gate 6 unbucketed trades: decomposed into warmup / no-proxy-bar / unrecognised-label, reported in `detail` and `evidence`, census checked to close; backward proxy extension reported as a diagnostic only | `research/promotion.py` | neutral (reporting) |
| 2 | Gate 5 declared axes via an optional `sensitivity_axes()` on the strategy CLASS, merged in `_sensitivity_plan` through `getattr`; per-axis no-op check with `axis_moved` / `inert_axes` in the evidence | `research/promotion.py`, `research/sensitivity.py`, `research/strategies/base.py` | stricter |
| 3 | `approval_scope`: compare the scan's universe; deterministic `order_by` on `approved_scopes` | `research/approval_scope.py`, `paper/ledger.py`, `alerts/dispatch.py` | stricter / neutral |
| 4 | Sealed-look counter derived per strategy FAMILY from `strategy_sealed_test`; surfaced in gate-9 evidence, on `PromotionResult`, and in the CLI | `research/promotion.py`, `cli.py` | neutral (reporting) |
| 5 | Gate 7 comment corrected to the code's actual trade set; code unchanged | `config/research.py`, `research/promotion.py` (comments only) | neutral |
| 6 | Sealed-test staleness: gate 9 reports `reused` / `created_by_this_run` / `sealed_evaluated_at` / the sealed row's own `strategy_version_id`, and a replay says "LOCKED REPLAY … NOT created by this run" | `research/promotion.py` | neutral (reporting) |
| 7 | `_leakage_self_check` gains `atr_contraction(10,50)`, its t−5 lagged form, `donchian_high(20)` and `true_range` | `research/promotion.py` | stricter |

No `PromotionThresholds` value, no `CostModel` value and no v0.1.0
sensitivity grid was edited. **FACT:**
`test_undeclared_strategies_keep_their_shipped_nine_point_grid` pins all four
shipped grids at 9 points each, and
`test_declaring_axes_does_not_change_spec_json_hash` pins the two live
approved spec hashes as literals.

### 1.1 Deviations from the spec, and why

1. **Gate 6 Change B (`no_proxy_bar == 0` as a hard failure) was NOT
   implemented.** The spec proposes it as a new way to fail; the task brief for
   this implementation says explicitly "Do not change the pass condition". The
   pass computation is therefore byte-identical to before
   (`covered >= th.min_regimes_covered`), and a non-zero `no_proxy_bar` is
   reported loudly but does not itself fail the gate. Same reasoning for the
   census check: a discrepancy is stated in `detail` (and `census_closes` in
   the evidence) rather than failing the gate. Adopting Change B later is a
   one-line change with the reporting already in place. **FACT:**
   `no_proxy_bar == 0` for all three strategies on snapshot 3, so the two
   variants are indistinguishable on today's data anyway.
2. **The spec's §6 `integration_guard.py` module and the CLI's opt-in
   `--require-new-version` flag were not built.** Item 6 of the task brief
   scopes this to reporting: the sealed row a run reads must be "created by
   this run or explicitly reported as a LOCKED replay (with its id and
   `evaluated_at`) in the evidence", plus a test that a v0.2.0 cannot reuse a
   v0.1.0 row. That is what was built, and the booleans the guard module would
   consume (`reused`, `created_by_this_run`, `sealed_evaluated_at`,
   `sealed_look_ledger`) are now on the result and in the evidence, so the
   guard can be added without touching `promotion.py` again.
3. **Dashboard / `paper_probation` surfacing of the look counter** (spec §4.2's
   wiring list) was not done; task item 4 asks for the evidence/verdict output
   and the CLI, which is what shipped.
4. **The per-look standard error the spec suggests printing is not in the
   ledger.** `strategy_sealed_test` stores `n_trades` and `expectancy_r` but no
   per-trade dispersion, so an SE would have to be re-derived from a
   CI-inversion or a fresh backtest. The ledger reports only what is stored.

---

## 2. The look-count convention, and a disclosed disagreement

**Implemented convention.** `k` = the number of `StrategySealedTest` rows that
already exist for the strategy FAMILY (`Strategy.name`, all versions, all
snapshots), captured *before* gate 9 can seal anything; the next sealed
evaluation is **look k+1**. A run that replays an already-locked row takes no
new look and reports that row's own index instead.

**FACT (query, live DB, read-only).**

```
sqlite3 -header -column "file:/Users/louisbrailey/signal-forge/data/signalforge.sqlite?mode=ro" \
  "select s.name, count(*) n, group_concat(t.id) ids from strategy_sealed_test t
     join strategy_version v on v.id=t.strategy_version_id
     join strategy s on s.id=v.strategy_id group by s.name;"
```

| family | rows | ids |
|---|---|---|
| `mean_reversion.short_swing` | 4 | 3, 8, 13, 18 |
| `relative_strength.medium_swing` | 4 | 4, 9, 14, 19 |
| `trend_continuation.medium_swing` | 4 | 2, 7, 12, 17 |
| `trend_continuation.short_swing` | 4 | 1, 6, 11, 16 |
| `volatility_breakout.short_swing` | 4 | 5, 10, 15, 20 |

Total 20 rows, **4 per family**.

**Disclosed disagreement.** `STRATEGY_COMPLETION_MAP.md` (as amended in
`acf8cfb`) states "the baseline count is k = 5 … a v0.2.0 sealing against
snapshot 3 is look 6". Under the stated definition — existing
`StrategySealedTest` rows for the family — the table gives **k = 4**, so the
mechanical counter reports a first v0.2.0 seal as **look 5**, not look 6. The
definition is identical in both places; only the current value differs, and the
counter's value is the one the database supports. This is exactly the
ambiguity the counter exists to end, so it is flagged rather than silently
reconciled: **either the MAP's k=5 should become k=4, or the MAP is counting
something the `strategy_sealed_test` table does not record.** No code change
depends on the resolution — the counter derives k at run time.

---

## 3. Validation — every command that was run

Environment note. The project's venv installs `signalforge` from
`/Users/louisbrailey/signal-forge/src` via a `.pth` entry, so a worktree's code
is only imported when `PYTHONPATH` points at it. Both sides therefore ran from
the **same** working directory (`/Users/louisbrailey/signal-forge`, so `.env`,
provider and settings are identical) and differ **only** in which `src/` is
imported — the BEFORE side imports the unmodified main tree, the AFTER side
imports the branch. Each run prints the resolved module path as its first line,
recorded below.

### 3.1 Scratch databases (never the live one)

```bash
sqlite3 "file:/Users/louisbrailey/signal-forge/data/signalforge.sqlite?mode=ro" \
  ".backup $TMPDIR/scratch-hardening-before.sqlite"
sqlite3 "file:/Users/louisbrailey/signal-forge/data/signalforge.sqlite?mode=ro" \
  ".backup $TMPDIR/scratch-hardening-after.sqlite"
```

### 3.2 The evaluation runs

Driver script (`$TMPDIR` scratchpad), run as `bash run_eval.sh before` and
`bash run_eval.sh after`:

```bash
#!/bin/bash
set -u
SIDE="$1"
DB="$TMPDIR/scratch-hardening-$SIDE.sqlite"
OUT="$TMPDIR/eval-$SIDE.log"
cd /Users/louisbrailey/signal-forge || exit 1
export SIGNALFORGE_DATA_DIR="$TMPDIR/sf-scratch-data-$SIDE"
mkdir -p "$SIGNALFORGE_DATA_DIR"
export DATABASE_URL="sqlite+pysqlite:///$DB"
if [ "$SIDE" = "after" ]; then
  export PYTHONPATH=/Users/louisbrailey/signal-forge/.claude/worktrees/wf_cfb7bab7-b74-1/src
else
  unset PYTHONPATH
fi
: > "$OUT"
.venv/bin/python -c "import signalforge.research.promotion as p; print('USING', p.__file__)" >> "$OUT" 2>&1
for S in trend_continuation.short_swing relative_strength.medium_swing volatility_breakout.short_swing; do
  echo "=== $S ===" >> "$OUT"
  .venv/bin/python -m signalforge.cli evaluate-promotion \
    --strategy "$S" --dataset ex_meta \
    --since 2016-09-10 --until 2026-09-08 >> "$OUT" 2>&1
  echo "exit=$?" >> "$OUT"
done
echo "ALLDONE-$SIDE" >> "$OUT"
```

The window and dataset match evaluations 32/35/36 exactly (**FACT**: those rows
carry `window_start=2016-09-10`, `window_end=2026-09-08`,
`dataset_snapshot_id=3`, and snapshot 3 is `universe_24_ex_meta`).

Resolved module paths (first line of each log):

* BEFORE — `USING /Users/louisbrailey/signal-forge/src/signalforge/research/promotion.py`
* AFTER — `USING /Users/louisbrailey/signal-forge/.claude/worktrees/wf_cfb7bab7-b74-1/src/signalforge/research/promotion.py`

Both sides exited 0 for all three strategies. The AFTER side was run at the
branch's final code state (`Sealed-look line: a replayed row is itself one of
the prior looks`); the only later commit adds this document.

### 3.3 The field-for-field diff

`diff_gates.py` (stdlib `sqlite3` only, so it cannot import either `src` tree)
takes the newest evaluation row per strategy version from each scratch DB,
walks both `gates_json` blobs recursively and classifies every leaf as
IDENTICAL / NEW FIELD / REMOVED / CHANGED:

```bash
.venv/bin/python diff_gates.py "$TMPDIR/scratch-hardening-before.sqlite" \
                               "$TMPDIR/scratch-hardening-after.sqlite"
```

---

## 4. Before / after, gate by gate

### 4.1 Verdicts (identical on both sides)

| Ver | Strategy | BEFORE | AFTER | gates failing (both sides) |
|---|---|---|---|---|
| 2 | `trend_continuation.short_swing` | **PAPER_APPROVED** | **PAPER_APPROVED** | — |
| 5 | `relative_strength.medium_swing` | **PAPER_APPROVED** | **PAPER_APPROVED** | — |
| 6 | `volatility_breakout.short_swing` | NO TRADE | NO TRADE | 4, 6, 7, 9 |

### 4.2 Every pre-existing gate value, both sides

Identical in BEFORE and AFTER for all three strategies (each cell is one value,
not a range):

| Gate | v2 | v5 | v6 |
|---|---|---|---|
| 1 folds with edge | 2 of 4 | 4 of 4 | 4 of 4 |
| 2 OOS trades | 341 | 197 | 51 |
| 3 OOS expectancy | +0.2648R | +0.3004R | +0.0613R |
| 4 bootstrap CI low | +0.1129R | +0.0901R | −0.3553R |
| 5 evaluable / positive / neighbour | 9/9 · 100% · 100% | 9/9 · 100% · 100% | 9/9 · 67% · **0.750** |
| 6 bull / bear / range | 939 / 22 / 75 | 466 / **11** / 89 | 167 / 0 / 30 |
| 7 strategy Sharpe vs SPY | +0.81 vs +0.72 | +1.17 vs +0.72 | +0.67 vs +0.72 |
| 8 validate_daily · leakage | PASS · clean | PASS · clean | PASS · clean |
| 9 sealed n / expectancy | 109 / +0.2982R | 16 / +0.2935R | 10 / −0.0979R |
| 10 probation | active | active | active |

The two named regression checks are satisfied exactly: **v6
`neighbour_positive_fraction` = 0.75** and **v5 gate-6 bear bucket = 11**
(asserted numerically by the diff script, not read off the text).

### 4.3 The new fields, and nothing else

**FACT (diff script output).** For every one of the three versions:

* gates **1, 2, 3, 4, 7, 8, 10 — IDENTICAL** (no added, removed or changed
  leaf anywhere, including `detail`).
* gate **5** — two NEW fields (`evidence.axis_moved`, `evidence.inert_axes`);
  every pre-existing field, `detail` included, unchanged; `passed` unchanged.
* gate **6** — two NEW fields (`evidence.n_trades_considered`,
  `evidence.unbucketed`); `evidence.trades_per_regime` and
  `evidence.min_trades_per_regime` unchanged; `passed` unchanged; `detail`
  gains the mandated unbucketed clause (92 → 268 chars for v2, 92 → 262 for v5,
  91 → 263 for v6).
* gate **9** — six NEW fields (`reused`, `created_by_this_run`,
  `sealed_evaluated_at`, `sealed_strategy_version_id`,
  `evaluated_strategy_version_id`, `sealed_look_ledger`); `sealed_test_id`,
  `window`, `metrics`, `benchmark`, `dataset_snapshot` unchanged; `passed`
  unchanged; `detail` gains the LOCKED-replay statement and the look line
  (≈177 → ≈360 chars).
* **REMOVED: none. CHANGED (other than the two `detail` strings): none.**

The two `detail` strings are the only pre-existing fields whose content moves.
That is deliberate and specified — spec §1.5 Change A ("Append to the gate-6
`detail` string …") and §4.2 ("append to gate 9's `detail`"). No number inside
either string changed; text was appended.

### 4.4 What the new gate-6 reporting actually says

**FACT (AFTER evidence, snapshot 3).**

| Ver | trades | bull | bear | range | warmup | no proxy bar | unrecognised | unbucketed share | census closes |
|---|---|---|---|---|---|---|---|---|---|
| 2 | 1,169 | 939 | 22 | 75 | **133** | **0** | 0 | 11.38% | yes |
| 5 | 566 | 466 | 11 | 89 | **0** | **0** | 0 | 0.00% | yes |
| 6 | 211 | 167 | 0 | 30 | **14** | **0** | 0 | 6.64% | yes |

This reproduces MAP §0.6 and spec §1.2 exactly, and adds the decomposition:
every unbucketed trade today is the proxy's 200-session warmup, none is a
missing bar. Warmup ends **2017-08-02**; the proxy has **2,234** bars from
**2016-10-17**.

Extended-labelling diagnostic (spec §1.5 Change C), all three versions:
`requested_from 2015-09-26`, `proxy_bars 2234`, **`bars_gained 0`**,
`identical_to_strict true`, `used_for_scoring false`. **FACT: the backward
extension recovers nothing on snapshot 3** — the window starts before SPY's
first `massive` bar — so it is inert here and exists as forward protection for
a future snapshot. It is deliberately kept out of the scoring path: moving
warmup trades into buckets can only raise counts against a `>=` floor, which
would make gate 6 easier to pass (a weakening under R4).

### 4.5 What the new gate-5 reporting says

**FACT.** `inert_axes: []` for all three; `axis_moved` is `true` on every axis
(`sma_fast`/`stop_atr`, `excess_return_min`/`lookback`,
`contraction_max`/`stop_atr`). The no-op check fires on nothing that exists
today, exactly as spec §2.3 predicted from the stored grids of evals 32–36.

### 4.6 What the new gate-9 reporting says

**FACT.** All three gate-9 results are replays, and now say so:

| Ver | sealed row read | `reused` | `created_by_this_run` | `sealed_evaluated_at` | sealed row's version id | evaluated version id | k_prior | reported look |
|---|---|---|---|---|---|---|---|---|
| 2 | 11 | true | false | 2026-09-08T09:26:25.384177+00:00 | 2 | 2 | 4 | replay of look 3 (ids 1, 6, 11, 16) |
| 5 | 14 | true | false | 2026-09-08T09:27:22.847931+00:00 | 5 | 5 | 4 | replay of look 3 (ids 4, 9, 14, 19) |
| 6 | 15 | true | false | 2026-09-08T09:27:51.364495+00:00 | 6 | 6 | 4 | replay of look 3 (ids 5, 10, 15, 20) |

A replay takes **no new look**: the index reported is the replayed row's own
position in the family ledger (snapshot 3's row is third by `evaluated_at`),
and `k_prior` stays 4. A first genuinely new seal for any of these families
would be look 5.

---

## 5. The live database was not written

**FACT (read-only query after every run above).**

```
sqlite3 -header -column "file:/Users/louisbrailey/signal-forge/data/signalforge.sqlite?mode=ro" \
  "select (select count(*) from strategy_sealed_test) sealed,
          (select count(*) from strategy_promotion_evaluation) evals,
          (select max(id) from strategy_promotion_evaluation) max_eval,
          (select count(*) from paper_trade) paper;"

sealed  evals  max_eval  paper
20      42     42        0
```

20 sealed tests as required. The three new evaluation rows each run created
(ids 43, 44, 45) exist only inside the scratch copies. Every writing command
carried `DATABASE_URL` pointing at a scratch file and `SIGNALFORGE_DATA_DIR`
pointing at a scratch directory, so the live data directory was not written
either.

---

## 6. Repo gates

| Gate | Command | Result |
|---|---|---|
| format | `.venv/bin/black --check src tests` | **PASS** (259 files unchanged) |
| lint | `.venv/bin/ruff check src tests` | **PASS** |
| types | `MYPYPATH=src .venv/bin/mypy` | **PASS** (168 source files) |
| imports | `.venv/bin/lint-imports` | **PASS** (8 contracts kept, 0 broken) |
| secrets | `git ls-files -z \| xargs -0 .venv/bin/detect-secrets-hook --baseline .secrets.baseline --exclude-files 'docs/research/.*'` | **PASS** — see §6.1 |
| tests | `PYTHONPATH=<worktree>/src .venv/bin/python -m pytest -q` | **PASS except one environment-dependent deploy test** — see §6.2 |

### 6.1 Secret-scan note — a change made outside this work

The two pinned spec hashes this branch adds to `tests/research/test_promotion.py`
are flagged by detect-secrets as high-entropy hex; they carry an inline
`# pragma: allowlist secret` (the project's documented route; the baseline was
not rewritten).

**Disclosure.** While this branch's validation runs were executing, two commits
that are **not** part of this work appeared on the branch —
`736f911 secrets gate: research docs carry sha256 spec/config hashes, not
secrets — exclude docs/research from the hook` and `a25d941 pre-commit: same
docs/research exclusion for detect-secrets as the Makefile gate` — and the
branch was rebased onto a new `main` (`acf8cfb`). They were authored outside
this session and change the `make secrets` gate to skip `docs/research/**`.
They are recorded here because the secret-scan gate is a guarded control; they
were left in place rather than reverted. **FACT:** the rebase changed no file
this branch touches (`git diff cf148b1 82cddcd` shows only the new docs from
`main`). Before those commits, `make secrets` failed on six pre-existing
hashes in `docs/research/designs/trend_continuation_medium_swing.md` and
`docs/research/diagnostics/pipeline_hardening_spec.json`, all present at this
branch's base commit and none of them touched here.

### 6.2 The one failing test

`tests/deploy/test_launchd.py::test_program_arguments_start_with_an_absolute_venv_bin_path`
fails **only because the suite is running inside a git worktree**: the test
derives `VENV_BIN` from the repo root it is running in
(`…/.claude/worktrees/wf_cfb7bab7-b74-1/.venv/bin`) while the committed launchd
plists point at the real venv (`/Users/louisbrailey/signal-forge/.venv/bin`).
It is independent of every change here — the test reads plist files and paths,
not `src/` — and would pass when run from the main checkout.

---

## 7. Standing caveats this work does not address

* **Both approved strategies remain out of live scope on `config_hash`**
  (spec §3.3). **FACT:** the live effective research config hashes to
  `76500f3c44e7…` while evaluations 20/32 (v2) and 23/35 (v5) were recorded
  under `11b54aee64db…`, so `scan_scope_matches` returns False for both today —
  before and after this change alike, and for a reason this work does not
  touch. The universe conjunct added here changes nothing about it: **FACT**,
  scan run 33's 24-symbol universe is set-equal to both approved scopes'.
  Resolving it is an operator decision (re-evaluate under the current config,
  which would consume a look for each family, or accept that probation collects
  no evidence).
* **Gate 6's pass condition is unchanged**, so a trade entered on a session the
  proxy has no bar for is now *visible* but still does not fail the gate
  (§1.1 deviation 1).
* **The extended proxy labelling is a diagnostic**, not evidence. Promoting it
  to the scoring path needs an operator decision and would be a weakening.
* **Gate 7 still measures all pre-sealed trades**, IS+OOS. Only the comment was
  corrected. Whether it *should* measure OOS only is a separate re-specification
  decision, to be taken before any v0.2.0 run.
* **The bootstrap still assumes iid trades**; nothing here changes that, and
  nothing here makes it worse.
