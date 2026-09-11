# Promotion-pipeline hardening — implementation spec (no code changed)

Scope: the six R4-permissible items named in
`docs/research/STRATEGY_COMPLETION_MAP.md` §0.5, §0.6 and §4.3. Each either
**fixes a counting defect** or makes a gate **more searching**. None weakens a
gate, moves a threshold, or touches the cost model (R4).

**This document changes no code.** Nothing under `src/` or `tests/` was
modified; no command that writes `data/signalforge.sqlite` was run. Every
number below comes from read-only `SELECT`s or from in-process calls to
`research.backtest_runner.run_strategy_over_universe`, which contains no
`session.add` / `session.flush` / `session.commit` (`backtest_runner.py:167`
onward). All sessions were opened with `_make_session(write=False)`,
rolled back, and closed.

Claims are labelled **FACT** (verified, with `file:line` or the query /
computation) or **HYPOTHESIS**. Estimates carry standard errors; a difference
under 2 SE is not treated as evidence.

Raw numbers: `pipeline_hardening_spec.json` (sibling).

---

## 0. Verification base — the read-only re-run reproduces evals 32–36 exactly

Before proposing any change I re-ran the pre-sealed evidence the pipeline
computed for evaluations 31–36, to be sure the counterfactuals below are
measured against the real thing and not an approximation.

**FACT (query).** Evals 31–36 all carry `window_start=2016-09-10`,
`window_end=2026-09-08`, `dataset_snapshot_id=3`, 24 symbols, source
`massive`. Sealed tests 11–15 all carry `window_start=2025-09-08`, so the
pre-sealed span the gates actually used is `[2016-09-10 .. 2025-09-07]`
(`promotion.py:557` — `pre_sealed_end = sealed_start - timedelta(days=1)`).

**FACT (in-process re-run, read-only).** Re-running
`run_strategy_over_universe` over that exact span with the live effective
research config's cost model reproduces the stored gate-2/3/4 numbers to
4 decimal places for all five swing strategies:

| Ver | Strategy | OOS n (re-run / stored) | OOS expectancy (re-run / stored) | Bootstrap CI low (re-run / stored) |
|---|---|---|---|---|
| 2 | `trend_continuation.short_swing` | 341 / 341 | +0.2648 / +0.2648 | +0.1129 / +0.1129 |
| 3 | `trend_continuation.medium_swing` | 319 / 319 | +0.3064 / +0.3064 | +0.1205 / +0.1205 |
| 4 | `mean_reversion.short_swing` | 309 / 309 | −0.0837 / −0.0837 | −0.1739 / −0.1739 |
| 5 | `relative_strength.medium_swing` | 197 / 197 | +0.3004 / +0.3004 | +0.0901 / +0.0901 |
| 6 | `volatility_breakout.short_swing` | 51 / 51 | +0.0613 / +0.0613 | −0.3553 / −0.3553 |

**FACT.** `full.trades` counts also reproduce exactly: 1,169 / 1,071 / 984 /
566 / 211 (MAP §0.6). The re-run is therefore a faithful oracle for the
counterfactuals in §1.

**FACT (cost model, unchanged).** The live effective config yields
`CostModel(commission_per_share=0.0, commission_min_per_order=0.0,
slippage_bps=3.0, half_spread_fill_penalty=True)` — identical to
`backtest/costs.py:11-16`. No item in this spec touches it.

---

## 1. Gate 6 — unbucketed trades (MAP §0.6, §4.3)

### 1.1 The defect, exactly

**FACT** (`promotion.py:739-763`):

```
741    regimes = label_regimes(proxy_full) if len(proxy_full) else {}
742    bucket_counts = {"bull": 0, "bear": 0, "range": 0}
744        lbl = regimes.get(t.entry_date, "warmup")
745-750    if lbl == "range_bound": ... elif lbl.startswith("bull"): ... elif lbl.startswith("bear"): ...
751    covered = sum(1 for c in bucket_counts.values() if c >= th.min_trades_per_regime)
```

Two distinct populations fall through all three branches and are counted
nowhere, and the `.get(..., "warmup")` default **conflates them**:

1. **warmup** — `backtest/regime.py:34-37` labels the first
   `TREND_LOOKBACK = 200` proxy sessions `"warmup"`, which matches no branch.
   The engine's own warmup is only `min_bars // 2 = 30` bars
   (`backtest_runner.py:206`), so real trades occur inside the proxy's warmup.
2. **no proxy bar** — a trade whose `entry_date` is absent from `regimes`
   entirely (a genuine data defect: the strategy traded on a session the proxy
   has no bar for) is given the same `"warmup"` label by the default argument
   and is indistinguishable in the output.

Neither the gate's `detail` string nor its `evidence` blob mentions either
count, so the trades are **silently dropped**.

### 1.2 Quantified, read-only, on evals 32–36

**FACT (recomputed).** Splitting the two causes for the first time:

| Ver | Strategy | `full.trades` | bull | bear | range | **warmup** | **no proxy bar** | unbucketed share |
|---|---|---|---|---|---|---|---|---|
| 2 | `trend_continuation.short_swing` | 1,169 | 939 | 22 | 75 | **133** | **0** | 11.38% |
| 3 | `trend_continuation.medium_swing` | 1,071 | 857 | 22 | 69 | **123** | **0** | 11.48% |
| 4 | `mean_reversion.short_swing` | 984 | 618 | 46 | 260 | **60** | **0** | 6.10% |
| 5 | `relative_strength.medium_swing` | 566 | 466 | 11 | 89 | **0** | **0** | 0.00% |
| 6 | `volatility_breakout.short_swing` | 211 | 167 | 0 | 30 | **14** | **0** | 6.64% |

This reproduces MAP §0.6's bucket table exactly and adds the decomposition.

**FACT (new).** `no proxy bar` is **0 for every version**. The entire
under-count today is the 200-session warmup; the missing-bar hole exists in
code but is unoccupied. Separating the two causes therefore costs nothing
today and turns a future data defect into a visible failure instead of a
silent one.

**FACT.** SPY `massive` bars run 2016-10-17 → 2026-09-09 (2,487 rows). Over
the pre-sealed span the proxy has 2,234 bars, first 2016-10-17, and the 200th
is **2017-08-02** — the last `"warmup"` date. v5's first trade is 2017-08-03,
one session later, which is why v5's unbucketed count is exactly zero (MAP
§0.6 hypothesised this from feature-warmup lengths; it is now measured).

### 1.3 The "extend the proxy backwards" fix is a **no-op today** — measured

The obvious fix (load the proxy from before `start` so the 200-session warmup
is consumed by pre-window bars) was tested read-only by loading SPY from
`start − 1200 days` instead of `start`:

**FACT.** `proxy_ext` returns **2,234 bars, first 2016-10-17** — identical to
`proxy_now`. **Bars gained by extension: 0.** The evaluation window
(`2016-09-10`) already starts 37 days *before* the first SPY `massive` bar,
so there is no earlier proxy history in the database to borrow, and none can
be obtained without a provider call (forbidden here). Recomputed bucket counts
under the extended load are byte-identical to the current ones for all five
versions.

**Conclusion (FACT):** on snapshot 3 the backward-extension fix cannot recover
a single trade. It is worth implementing only as forward protection for a
future snapshot whose window starts after the proxy's first bar.

### 1.4 An upper bound on what labelling the warmup would do — and why it is an R4 hazard

To bound the effect, warmup sessions were relabelled with an *expanding-window*
variant of `label_regimes` (bars 20…199 use the mean of all bars so far instead
of emitting `"warmup"`; ≥ 200 unchanged). This is a diagnostic, not a proposal.

**FACT (recomputed):**

| Ver | current bull/bear/range | expanding bull/bear/range | Δbull | Δbear | Δrange | regimes covered (current → expanding) |
|---|---|---|---|---|---|---|
| 2 | 939 / 22 / 75 | 1058 / 22 / 89 | +119 | **0** | +14 | 3 → 3 |
| 3 | 857 / 22 / 69 | 964 / 22 / 85 | +107 | **0** | +16 | 3 → 3 |
| 4 | 618 / 46 / 260 | 669 / 46 / 269 | +51 | **0** | +9 | 3 → 3 |
| 5 | 466 / 11 / 89 | 466 / 11 / 89 | 0 | 0 | 0 | 3 → 3 |
| 6 | 167 / 0 / 30 | 179 / 0 / 32 | +12 | **0** | +2 | **2 → 2** |

**FACT.** Every recovered trade lands in `bull` or `range`; **zero** land in
`bear` (2016-10 → 2017-08 was an uninterrupted bull tape). No gate-6 verdict
changes for any version — including v6, whose blocking `bear = 0` is untouched.

**The R4 hazard, stated plainly (HYPOTHESIS about direction, FACT about the
mechanism).** Moving warmup trades into buckets can only *increase* bucket
counts, and gate 6's condition is `count >= min_trades_per_regime`. So any
labelling change of this kind is **monotonically easier to pass**. It is a
weakening in the R4 sense even though it is motivated as a defect fix. It is
verdict-neutral today only by luck of which regime the recovered trades fall in.

### 1.5 Specified behaviour (R4-clean)

**Files/functions:** `src/signalforge/research/promotion.py`, gate 6 block
(currently lines 739-763), inside `evaluate_promotion`.

**Change A — decompose and report (mandatory, R4-neutral).**

* Replace `lbl = regimes.get(t.entry_date, "warmup")` with an explicit
  three-way classification: `missing = t.entry_date not in regimes`,
  `warmup = regimes.get(t.entry_date) == "warmup"`, else bucket.
* Accumulate `warmup_trades` and `no_proxy_bar_trades` alongside
  `bucket_counts`.
* Assert the census closes:
  `bull + bear + range + warmup + no_proxy_bar == len(full.trades)`. If it does
  not, gate 6 fails with the discrepancy in `detail` — a trade must never
  vanish.
* Append to the gate-6 `detail` string:
  `"; unbucketed: {warmup} inside the {TREND_LOOKBACK}-session proxy warmup
  (ends {last_warmup_date}), {no_proxy_bar} with no proxy bar"`.
* Add to `evidence`:
  `{"unbucketed": {"warmup": w, "no_proxy_bar": nb, "total": w+nb,
  "share_of_trades": round((w+nb)/n, 4), "warmup_last_date": <iso>,
  "proxy_first_bar": <iso>, "proxy_bars": len(proxy_full)},
  "n_trades_considered": len(full.trades)}`.
* **The pass computation (`covered >= th.min_regimes_covered`) is unchanged.**

**Change B — make the missing-bar hole a hard failure (more searching).**

* `gate6_pass = bool(covered >= th.min_regimes_covered and no_proxy_bar == 0)`.
* Rationale: a trade on a date the proxy has no bar for means the strategy and
  the regime labeller disagree about which sessions exist. That is a
  data-integrity finding, not a coverage question. It is strictly a **new way
  to fail**, so it is R4-permissible.
* **Verified safe:** `no_proxy_bar == 0` for all five versions on snapshot 3
  (§1.2), so v2 and v5 are unaffected.
* Note it consumes no new threshold — the bar is literally zero, so nothing in
  `PromotionThresholds` moves.

**Change C — forward-proof the proxy load (defect fix, no scoring effect).**

* Load the proxy for *labelling* from
  `start - timedelta(days=ceil(TREND_LOOKBACK * 365.25 / 252) + 60)`
  (= the same 350-day constant already used as `MIN_PRESEALED_DAYS`,
  `promotion.py:94`), then **restrict scoring** to trades in
  `[start, pre_sealed_end]`.
* Because bucket counts can only rise, this changes gate 6's difficulty. To
  keep R4 exact, the pass computation uses the **strict** labelling (proxy
  loaded from `start`, as today); the extended labelling is reported in
  `evidence["unbucketed"]["extended_labelling"]` as a diagnostic only.
* On snapshot 3 both are identical (§1.3), so this is provably inert today.
* Promoting the extended labelling to the scoring path is an **operator
  decision**, not a code decision, and must be recorded as such.

**Tests to add** (`tests/research/test_promotion.py`):

1. `test_gate6_reports_warmup_trades_and_never_drops_one` — a fixture whose
   trades straddle the proxy's 200-session warmup; assert
   `bull+bear+range+warmup+no_proxy_bar == n_trades` and that both counts
   appear in `detail` and `evidence`.
2. `test_gate6_distinguishes_warmup_from_a_missing_proxy_bar` — delete one
   proxy session on which a trade is entered; assert `no_proxy_bar == 1`,
   `warmup` unchanged, and the two are reported separately.
3. `test_gate6_fails_when_a_trade_has_no_proxy_bar` — same fixture; assert
   `gate6_pass is False` even though all three buckets clear their floor.
4. `test_gate6_bucket_counts_are_unchanged_by_the_reporting_change` — golden
   test pinning bull/bear/range for a fixture, guaranteeing Change A is
   scoring-neutral.
5. `test_gate6_extended_proxy_labelling_is_diagnostic_only` — assert that when
   pre-window proxy bars exist, `evidence` reports a different extended count
   while `passed` still follows the strict labelling.

**Expected effect on the two APPROVED strategies (verified read-only):**

| | v2 `trend_continuation.short_swing` | v5 `relative_strength.medium_swing` |
|---|---|---|
| buckets after Change A | 939 / 22 / 75 — unchanged | 466 / 11 / 89 — unchanged |
| `covered` | 3/3 — unchanged | 3/3 — unchanged |
| Change B (`no_proxy_bar == 0`) | satisfied (0) | satisfied (0) |
| Change C (strict scoring) | identical labelling, 0 bars gained | identical, and 0 warmup trades anyway |
| **gate 6 verdict** | **PASS (unchanged)** | **PASS (unchanged)** |

Standing caveat that survives the fix: v5's bear bucket is **11** against a
floor of 10 (MAP §4.2 item 5). Nothing here moves it.

### 1.6 A substantive reason not to drop these trades silently — with SEs

The excluded trades are not a random subsample. Per-trade R over the pre-sealed
span, warmup vs bucketed (**FACT**, recomputed; sd is the sample sd of `pnl_r`,
SE = sd/√n):

| Ver | warmup n | warmup mean R | warmup sd | warmup SE | bucketed n | bucketed mean R | bucketed sd | bucketed SE | diff (warmup − bucketed) | SE(diff) | \|z\| |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2 | 133 | −0.0198 | 1.305 | 0.113 | 1,036 | +0.1152 | 1.435 | 0.045 | −0.1350 | 0.122 | 1.11 |
| 3 | 123 | +0.1420 | 1.498 | 0.135 | 948 | +0.1699 | 1.595 | 0.052 | −0.0279 | 0.145 | 0.19 |
| 4 | 60 | **+0.2494** | 0.758 | 0.098 | 924 | **−0.0823** | 0.876 | 0.029 | **+0.3317** | 0.102 | **3.25** |
| 5 | 0 | — | — | — | 566 | +0.2081 | 1.419 | 0.060 | — | — | — |
| 6 | 14 | −0.0201 | 1.001 | 0.268 | 197 | +0.1782 | 1.224 | 0.087 | −0.1983 | 0.281 | 0.70 |

**FACT.** For v2, v3 and v6 the difference is under 2 SE — no evidence of a
different population. **For v4 it is +0.3317R at 3.25 SE**: the 60 silently
dropped trades are the best-performing slice of that strategy's whole
pre-sealed sample, and dropping them from *any* reported regime breakdown
biases every narrative about v4 downward. This is the concrete cost of the
present silence and the strongest argument for Change A.

(These sample sds also supersede MAP §0.3's CI-inverted approximations, which
were explicitly accurate to ~2 s.f.: e.g. v2 1.435 vs 1.420 assumed, v4 0.876
vs 0.807 assumed. §0.3's `required n` figures move by a few percent and none of
its qualitative conclusions change.)

---

## 2. Gate 5 — a declared, pre-registered axis-extension mechanism (MAP §0.5, §4.2 item 6)

### 2.1 Problem

**FACT** (`promotion.py:161-210`). `_sensitivity_plan` hard-codes exactly two
axes per strategy family, covering 2 of 6–8 `*Params` fields (MAP §0.5). A
v0.2.0's *defining* new parameter is therefore the one axis gate 5 will never
perturb — and a retained-but-unused field makes all grid points identical, so
gate 5 passes at 100% having tested nothing.

**FACT** (`sensitivity.py:135-136`). `run_parameter_sensitivity` already
supports N axes: `axes = list(grid.keys()); combos = itertools.product(...)`.
`_is_neighbour` (`:100-112`) is axis-count agnostic. **FACT**
(`sensitivity.py:29`): `MAX_GRID_POINTS = 120`, so 3 axes × 3 values = 27
points and 4 axes × 3 = 81 both fit, while 5 axes × 3 = 243 raises `ValueError`
(`:137-140`). **No engine change is needed to support more axes — only a
declaration mechanism and a validity check.**

### 2.2 The hazard that dictates the design (verified)

**FACT.** `persistence.spec_json_hash` (`persistence.py:32-43`) hashes **every**
`StrategySpec` field except `git_sha`, `status`, `notes`
(`_HASH_EXCLUDED_SPEC_FIELDS`, `:29`). Adding a `sensitivity_axes` field to the
`StrategySpec` dataclass therefore changes the hash of **every** strategy.
Demonstrated read-only by hashing the current specs with one extra key:

* `trend_continuation.short_swing`: `2ed97431…` → `6e35dbe5…` (changed)
* `relative_strength.medium_swing`: `dfe696b6…` → `3138ed57…` (changed)

**FACT.** Those two current hashes are exactly the ones stored on the passing
evaluations that scope the live approvals (evals 20 & 32 for v2, 23 & 35 for
v5). Changing them would make `current_spec_json_hash` disagree with every
approved scope, so `scan_scope_matches` would return `False` forever and the
approved strategies would be permanently out of scope. **The axis declaration
must therefore live outside `StrategySpec`.**

### 2.3 Specified behaviour

**Files/functions:**

* `src/signalforge/research/strategies/base.py` — extend the
  `BaselineStrategy` Protocol with an **optional** method:

  ```
  def sensitivity_axes(self) -> Mapping[str, Sequence[float | int]]: ...
  ```

  Declared on the *strategy class*, never on `StrategySpec`, so
  `asdict(spec)` and hence `spec_json_hash` are untouched. Absent method ⇒
  fall back to `_sensitivity_plan`.
* `src/signalforge/research/promotion.py` — `_sensitivity_plan(strategy)`:
  after resolving the family factory and its base grid, merge in
  `getattr(strategy, "sensitivity_axes", lambda: {})()`. Declared axes
  **extend** the family grid; an axis name already present is **overridden by
  the declaration** only if the declared value list is a superset containing
  the baseline value (else raise — a declaration may not shrink the shipped
  grid). Return `(factory, merged_grid)`.
* Validation at plan time (raise `ValueError`, never silently skip):
  1. every declared axis name is a field of the strategy's `*Params`
     dataclass — otherwise `_replace` would raise late, mid-grid
     (`promotion.py:50`);
  2. the baseline value of each declared axis is present in its value list
     (otherwise there is no baseline grid point and `_is_neighbour` degenerates);
  3. `prod(len(v) for v in merged_grid.values()) <= MAX_GRID_POINTS`.

**Change — the pre-integration inert-axis check (this is the "more searching"
part).**

In `run_parameter_sensitivity` (`sensitivity.py`), after the grid runs, for each
axis `a` compare every point that differs from the baseline **only** on `a`
against the baseline point. If **all** such points have identical `n_trades`
**and** identical `oos_expectancy_r` (compare rounded to 4 d.p., matching
`to_dict`), the axis is **inert**:

* add `inert_axes: list[str]` to `SensitivityReport` and to `to_dict()`;
* append a reason: `"axis '<a>' does not change OOS trade count or expectancy —
  the grid tested nothing on it"`;
* `fragile = bool(reasons)` already makes this a **gate-5 failure** with no
  threshold change.

This is a new failure condition only — strictly more searching, R4-permissible.

**Tests to add:**

* `tests/research/test_sensitivity.py`
  * `test_inert_axis_is_detected_and_makes_the_report_fragile` — factory that
    ignores one parameter; assert `inert_axes == ["ignored"]` and `fragile`.
  * `test_a_live_axis_is_not_flagged_inert` — factory where every axis moves
    trade count; assert `inert_axes == []`.
  * `test_three_axis_grid_neighbour_fraction_counts_all_axes` — 3×3×3 grid;
    assert the neighbour denominator is 6, not 4.
* `tests/research/test_promotion.py`
  * `test_declared_axes_extend_the_family_grid` — a stub strategy declaring
    `time_stop_bars`; assert the merged grid has 3 axes / 27 points.
  * `test_declared_axis_not_on_params_raises_at_plan_time`.
  * `test_declared_axis_without_the_baseline_value_raises`.
  * `test_declared_axes_over_the_grid_cap_raise`.
  * `test_declaring_axes_does_not_change_spec_json_hash` — **the R7 guard**:
    assert `spec_json_hash(spec)` for `TrendContinuation(SHORT_SWING)` equals
    the literal `2ed9743170bd3bbdb450ea03a004a7ffaeb64ccbbe6075db312ffd544072f382`
    and for `RelativeStrength(MEDIUM_SWING)` equals
    `dfe696b662dd02b8fa3a02ce5b987c6eade84a40d88c1a2d8d52e206cb6f6c32`. Pinning
    the live approved hashes as literals turns any future spec-shape change into
    a red test instead of a silent live-scope break.

**Expected effect on the two APPROVED strategies (verified read-only from
stored gate-5 evidence — no recomputation needed):**

Per-axis inertness on the stored `gates_json` grids of evals 32–36:

| Eval | Strategy | axis | off-baseline points (value, n, exp) | inert? |
|---|---|---|---|---|
| 32 | v2 | `sma_fast` | (15, 329, +0.2409), (25, 354, +0.2526) | no |
| 32 | v2 | `stop_atr` | (1.2, 349, +0.1484), (1.8, 331, +0.2287) | no |
| 35 | v5 | `excess_return_min` | (0.03, 247, +0.2967), (0.07, 155, +0.3877) | no |
| 35 | v5 | `lookback` | (42, 188, +0.2880), (84, 277, +0.2154) | no |
| 33 | v3 | both | all four differ from baseline | no |
| 34 | v4 | both | all four differ from baseline | no |
| 36 | v6 | both | all four differ from baseline | no |

**FACT: no axis is inert on any of the five stored evaluations.** The
inert-axis check is a no-op on every existing v0.1.0 grid, and
`_sensitivity_plan`'s v0.1.0 grids are not edited by this item, so v2 and v5's
gate 5 stays `fragile=False`, `positive_fraction=1.0`,
`neighbour_positive_fraction=1.0` — **PASS, unchanged**. (Recorded for
regression detection: v6's neighbour fraction is exactly 0.750 — 3 of 4 — and
v4's is 0.0.)

**Cost.** Each grid point is a full universe backtest. Measured: a single
24-symbol, 9-year pass costs ≈ 2 s wall-clock on this machine, so 9 → 27 points
takes gate 5 from ≈ 20 s to ≈ 55 s per strategy. Acceptable; note it in the
v0.2.0 runbook.

---

## 3. `approval_scope` — compare `universe`, and make `approved_scopes` deterministic (MAP §4.3)

### 3.1 Problems

**FACT** (`approval_scope.py:41`). `ApprovedScope` carries
`universe: frozenset[str]`, populated at `:62`, and
`scan_scope_matches` (`:88-93`) compares `dataset_snapshot_id`, `config_hash`,
`spec_json_hash` and `sources` — **never `universe`**. The field is collected
and thrown away.

**FACT** (`approval_scope.py:50-55`). `approved_scopes` issues its `select`
with **no `order_by`**; row order is whatever SQLite returns.

**FACT** (`paper_probation.py:113-122`). The probation dashboard picks which
sealed test to display via `scopes[0].dataset_snapshot_id` — order-dependent
the moment a strategy has passing evaluations on two different snapshots
(R7b).

**FACT.** `ScanRun.universe_json` exists and is populated
(`db/models/research.py:81`), so the comparison has a real input at every call
site: `paper/ledger.py:386-396` (evidence snapshot), `paper/ledger.py:504-511`
(auto-simulate guard), `alerts/dispatch.py:272-284` (alert scope).

### 3.2 Specified behaviour

**File:** `src/signalforge/research/approval_scope.py`.

**Change A — deterministic ordering.**

```
select(StrategyPromotionEvaluation)
  .where(... passed.is_(True))
  .order_by(
      StrategyPromotionEvaluation.evaluated_at.desc(),
      StrategyPromotionEvaluation.id.desc(),
  )
```

Newest passing evaluation first. Document in the docstring that `scopes[0]` is
"the most recent passing evaluation" and that `paper_probation.py:118` relies
on it. Ordering changes no membership, so `scan_scope_matches`'s `any(...)`
verdict is unaffected by construction.

**Change B — compare universe (more searching).**

* Add a required keyword `universe: frozenset[str] | None` to
  `scan_scope_matches`.
* Reject `None` and the empty set the same way `source` is already rejected
  (`:86`): an unspecified universe must never trivially satisfy an approval
  carrying a real one.
* Add `s.universe == universe` to the `any(...)` conjunction (`:88-93`), with
  symbols upper-cased on both sides, matching `:62`.
* Update the three call sites to pass
  `universe=frozenset(x.upper() for x in run.universe_json)`.
* Extend the docstring: the approval is scoped to *this exact symbol set*, so a
  scan of a subset or superset of the approved universe is out of scope even
  when it resolves to the same `DataSnapshot` id.

This can only turn `True` into `False`. It is strictly stricter — R4-permissible.

**Tests to add** (`tests/alerts/test_approval_scope.py`):

1. `test_scan_scope_requires_the_universe_to_match` — same snapshot/config/spec/
   source, one symbol removed from the scan universe ⇒ `False`.
2. `test_scan_scope_rejects_an_empty_or_none_universe` — mirrors the existing
   empty-`source` test at `:185`.
3. `test_scan_scope_universe_comparison_is_case_insensitive`.
4. `test_approved_scopes_is_ordered_newest_first` — three passing evaluations
   with distinct `evaluated_at`; assert `[s.evaluation_id for s in scopes]` is
   descending and that repeated calls are identical.
5. `test_approved_scopes_order_is_stable_when_evaluated_at_ties` — two rows
   sharing `evaluated_at`; the `id.desc()` tiebreak makes it deterministic.
6. `test_probation_picks_the_newest_scope_sealed_test` (in
   `tests/research/` alongside the probation tests) — two passing evaluations
   on different snapshots; assert the displayed sealed test is the newer
   snapshot's, deterministically.

### 3.3 Expected effect on the two APPROVED strategies (verified read-only)

**FACT.** `approved_scopes` today returns, for v2, evaluations **20** and
**32**, and for v5, evaluations **23** and **35** — all four on
`dataset_snapshot_id = 3`, all `sources = {massive}`, all with 24-symbol
universes. Because both scopes of each strategy share a snapshot id, the
ordering fix changes nothing observable today (MAP R7b predicted exactly this);
it removes a prospective hazard.

**FACT.** The latest scan run (id 33, 2026-09-10) has
`dataset_snapshot_id = 3`, `source = massive`, and a 24-symbol
`universe_json` **set-equal to both approved scopes' universes for v2 and for
v5**. So Change B changes no verdict for either approved strategy.

**FACT, and it is important, though outside the six items.** Calling
`scan_scope_matches` today with run 33 and the live spec hashes returns
**`False` for both v2 and v5** — not because of the universe, but because the
live effective research `config_hash` is
`76500f3c44e761b6…` while both approvals were recorded under
`11b54aee64dbc265…`. The approved strategies are therefore **already out of
scope on live scans**, so paper probation is emitting
`NO TRADE — approval does not apply to this dataset.` and auto-simulation is
blocked at `paper/ledger.py:505`. That is consistent with `paper_trade` having
0 rows. The config hash covers the whole `ResearchConfig`
(`config/research.py:333-335`), and the 2026-09-10 probation activation changed
several of its values at once; the pre-change config is not reconstructable
from the database, because evaluations store only the hash. **Neither this item
nor any other in this spec changes that state** — it is flagged for the
operator, and it means the two strategies' `PAPER_APPROVED` *status* is intact
while their *live scope* is not.

---

## 4. A sealed-look counter (MAP §0.1, R2, §4.3)

### 4.1 Problem

**FACT.** No look counter exists anywhere in `src/signalforge` (MAP §0.1;
re-verified: `strategy_sealed_test` is referenced only by `promotion.py`,
`paper_probation.py`, `agents/strategy_validation.py`, the models and the
migrations — none of them counts looks). Disclosure is manual, and MAP records
that a manual count was wrong by 4× in its own first draft.

**FACT (query).** Sealed looks per strategy family today:

| family | existing sealed tests | distinct snapshots | distinct versions | sealed-test ids |
|---|---|---|---|---|
| `trend_continuation.short_swing` | 4 | 4 | 1 | 1, 6, 11, 16 |
| `trend_continuation.medium_swing` | 4 | 4 | 1 | 2, 7, 12, 17 |
| `mean_reversion.short_swing` | 4 | 4 | 1 | 3, 8, 13, 18 |
| `relative_strength.medium_swing` | 4 | 4 | 1 | 4, 9, 14, 19 |
| `volatility_breakout.short_swing` | 4 | 4 | 1 | 5, 10, 15, 20 |

**Documentation defect the counter resolves (FACT).** MAP is internally
inconsistent about `k`. §0.1 and R2 say a v0.2.0 sealing on snapshot 3 "is the
**fifth** look"; §4.2 item 10 says "the baseline count is k = 5 … so a first
v0.2.0 sealing on snapshot 3 is **look 6**". A mechanical counter with one
stated definition ends the ambiguity. **This spec adopts: `k_prior` = the
number of `StrategySealedTest` rows that already exist for the family (4
today); `this_look` = `k_prior + 1` (5 for a first v0.2.0 seal).** That matches
§0.1, R2 and the task brief's "k = 5 per strategy"; MAP §4.2 item 10 should be
corrected to agree.

### 4.2 Specified behaviour

**File:** `src/signalforge/research/promotion.py` (new helper, near
`_get_or_create_sealed_test`).

```
def sealed_look_ledger(session, strategy_name: str) -> dict[str, Any]:
    """Every sealed test ever locked for a strategy FAMILY (all its versions),
    oldest first. Read-only."""
```

Query `StrategySealedTest` joined `StrategyVersion` joined `Strategy` on
`Strategy.name == strategy_name`, ordered by
`(StrategySealedTest.evaluated_at, StrategySealedTest.id)`. Return:

```
{
  "strategy_key": ...,
  "k_prior": <count of rows locked BEFORE this run>,
  "this_look": <k_prior + 1 if a new row was sealed this run, else the index of the reused row>,
  "reused_this_run": <bool>,
  "looks": [
    {"index": 1..n, "sealed_test_id":…, "strategy_version_id":…, "version":…,
     "dataset_snapshot_id":…, "dataset_snapshot_key":…,
     "window": "start..end", "n_trades":…, "expectancy_r":…, "passed":…,
     "evaluated_at": <iso>, "is_this_run": <bool>}
  ]
}
```

**Wiring:**

* Capture `k_prior` **before** calling `_get_or_create_sealed_test`, so the
  count is unambiguous.
* Add the ledger to gate 9's `evidence` under `"sealed_look_ledger"`, and
  append to gate 9's `detail`:
  `"; look {this_look} of this strategy family ({k_prior} prior sealed
  tests: ids …)"`.
* Add `sealed_look_index: int` and `sealed_look_prior: int` to
  `PromotionResult` and `to_dict()` (`promotion.py:118-155`).
* CLI (`cli.py:1387-1401`, `evaluate-promotion`): after the per-gate lines,
  print
  `"  sealed looks: this is look {n} for {strategy_key} ({k_prior} prior: ids …)"`,
  and print it for **failing** evaluations too — an undisclosed failed look is
  exactly the multiple-testing leak R2 is guarding against.
* Dashboard (`app/views.py` promotion view + `templates/strategy_promotion.html`)
  and `research/paper_probation.py` rows: surface `k_prior` / `this_look` and
  the per-look table (this is the §0.1 table, generated instead of hand-copied).
* Every strategy report must reproduce the generated table verbatim (R2, MAP
  §4.2 item 10).

**Tests to add** (`tests/research/test_promotion.py`):

1. `test_sealed_look_ledger_counts_every_snapshot_for_a_family` — one version,
   three snapshots; assert `k_prior == 3` on the fourth evaluation and
   `this_look == 4`.
2. `test_sealed_look_ledger_spans_versions_within_a_family` — v0.1.0 and
   v0.2.0 of the same `Strategy.name`; assert the v0.2.0 seal reports
   `k_prior` including the v0.1.0 rows.
3. `test_sealed_look_index_does_not_advance_on_a_reused_sealed_test` — second
   evaluation of the same `(version, snapshot)`; assert `reused_this_run is
   True` and `this_look` equals the reused row's index, not `k_prior + 1`.
4. `test_sealed_look_ledger_is_reported_on_a_failing_evaluation`.
5. `test_sealed_look_ledger_ordering_is_deterministic`.

**Expected effect on the two APPROVED strategies:** **none.** The ledger is
read-only reporting; it adds no gate condition and cannot change `passed`
(`promotion.py:922`). Running it against today's database would print, for
`trend_continuation.short_swing`, `k_prior = 4` with sealed ids 1, 6, 11, 16
(+0.3246R/112, +0.3246R/112, +0.2982R/109, +0.3246R/112) and for
`relative_strength.medium_swing`, `k_prior = 4` with ids 4, 9, 14, 19
(+0.2935R/16 on all four).

**SEs on the sealed numbers that the ledger will surface** (using the direct
per-trade sds measured in §1.6 rather than MAP §0.3's CI-inverted values):
v2 snapshot 3, +0.2982R on 109 trades, SE ≈ 1.435/√109 = **0.137**, i.e.
**+2.17 SE** from zero; v5 snapshot 3, +0.2935R on 16 trades,
SE ≈ 1.419/√16 = **0.355**, i.e. **+0.83 SE** from zero. v5's approval remains
the weakest evidence supporting anything live (MAP §0.3), and the ledger should
print the SE next to each look so this is visible without arithmetic.

---

## 5. Gate 7 — the docstring/code contradiction (MAP §0.2, §4.3)

### 5.1 The code's actual trade set

**FACT** (`promotion.py:765-776`):

```
765    # Gate 7: risk-adjusted benchmark comparison. …
773    proxy_span_dates = [d for d in proxy_full.dates if start <= d <= pre_sealed_end]
774    eff_start = proxy_span_dates[0] if proxy_span_dates else start
775    eff_end   = proxy_span_dates[-1] if proxy_span_dates else pre_sealed_end
776    pm_strategy = compute_portfolio_metrics(full.trades, span_start=eff_start, span_end=eff_end)
```

Gate 7 uses **`full.trades`** — *every* trade over the pre-sealed span,
in-sample and out-of-sample together — annualised over the proxy's actual
matched session range within `[start, pre_sealed_end]`. It does **not** use
`full.out_of_sample`. (Contrast gates 2/3/4, which read `oos` at `:652`, `:652`
and `:679`.)

**FACT.** `config/research.py:111-113` says the opposite:

```
111    # Gate 7 — promoted only on a risk-adjusted benchmark comparison (OOS
112    # Sharpe vs SPY buy-and-hold Sharpe over the same span) — cumulative return
113    # alone never decides this.
```

**FACT.** The module docstring at `promotion.py:22-23` says "Sharpe vs SPY
buy-and-hold over the same span" — no "OOS" — so it is *not* wrong. The single
incorrect token in the repository is **"OOS" on `config/research.py:111`**
(`grep -rn "OOS Sharpe" src docs tests` returns exactly one source hit: this
line, plus MAP's own citation of it).

### 5.2 The one-line fix

Replace line 111 so the three-line comment reads:

```
    # Gate 7 — promoted only on a risk-adjusted benchmark comparison (Sharpe
    # over ALL pre-sealed trades, in-sample and out-of-sample, vs SPY
    # buy-and-hold Sharpe over the same matched span; see promotion.py:776)
    # — cumulative return alone never decides this.
```

**This is a comment change only.** Do **not** "fix" the code to use
`full.out_of_sample`: that would alter what gate 7 measures for every strategy,
is not obviously stricter in either direction, and would in effect re-specify a
gate mid-programme — forbidden by R4's freeze. Which of the two the operator
actually wants is a separate decision to be taken on its own merits, before any
v0.2.0 run, and recorded.

**Tests to add** (`tests/research/test_promotion.py`):

* `test_gate7_uses_all_pre_sealed_trades_not_only_oos` — a fixture whose IS and
  OOS trades have deliberately different Sharpe; assert the gate-7 evidence's
  `strategy` metrics equal `compute_portfolio_metrics(full.trades, …)` and
  differ from the OOS-only metrics. This pins the behaviour so the comment can
  never drift from the code again.
* `test_gate7_comment_matches_behaviour` is not testable; the assertion above
  is the durable substitute.

**Expected effect on the two APPROVED strategies:** **none** — no executable
line changes. Gate 7 for v2 and v5 stays exactly as recorded on evals 32 and
35. Consequence for later phases (MAP §4.2 item 5): every gate-7 forecast must
be stated over all pre-sealed trades — 1,169 for v2 and 566 for v5, not 341 and
197.

---

## 6. Pre-integration guard: the v0.2.0 sealed test must be created by **this** run (R3, MAP §4.3)

### 6.1 The trap

**FACT** (`persistence.py:46-93`). `upsert_strategy_version` refreshes
`spec_json` and `git_sha` on the **same row** when the version string is
unchanged, and never touches `status`. **FACT** (`promotion.py:377-384`).
`_get_or_create_sealed_test` returns any existing `(version, snapshot)` row
as-is. So editing strategy code without bumping `VERSION` makes gates 1–8
recompute against the *new* code while gate 9 replays a sealed result measured
against the *old* code — a silently invalid pass. MAP §4.3 calls this "the
single most likely way to produce an invalid pass".

**FACT.** The information needed to detect it already exists but is thrown
away: `_get_or_create_sealed_test` returns `(row, reused)` (`:366`), and
`evaluate_promotion` uses `reused` only to build a **human-readable string**
(`promotion.py:851`, `seal_note`). Neither `PromotionResult` nor the gate-9
`evidence` blob (`:858-865`) carries the boolean, so an automated
pre-integration check would have to parse English prose.

### 6.2 Specified behaviour

**File:** `src/signalforge/research/promotion.py`.

1. **Expose the fact.**
   * Add `"reused": sealed_reused` and
     `"sealed_evaluated_at": sealed_row.evaluated_at.isoformat()` to gate 9's
     `evidence` dict (`:858-865`).
   * Add `sealed_test_reused: bool` and `strategy_version_created: bool` to
     `PromotionResult` (`:118-137`) and `to_dict()` (`:138-155`), threaded
     through `_finalize`'s signature.
   * `strategy_version_created`: in `evaluate_promotion`, before
     `upsert_strategy_version` (`:508`), check whether a `StrategyVersion` row
     already exists for `(spec.name, spec.version)`; the negation of that is
     the flag. (Do not change `upsert_strategy_version`'s return type — it has
     many callers.)

2. **The guard itself** — a new module
   `src/signalforge/research/integration_guard.py`, pure and read-only:

   ```
   @dataclass(frozen=True, slots=True)
   class IntegrationCheck:
       name: str
       passed: bool
       detail: str

   def check_new_version_integration(
       session, result: PromotionResult, *, run_started_at: datetime,
       expect_new_version: bool = True,
   ) -> list[IntegrationCheck]:
   ```

   Checks, all failing loudly:

   * **G1 sealed test is fresh** — `result.sealed_test_reused is False`.
     A v0.2.0 whose gate 9 was *reused* means a sealed test already existed for
     that `(version, snapshot)`: either the version was not bumped, or the
     snapshot was already sealed for it.
   * **G2 sealed row was written by this run** —
     `StrategySealedTest.evaluated_at >= run_started_at`, where
     `run_started_at` is captured before the evaluation begins. This catches
     the case where a concurrent process sealed the same pair and
     `_get_or_create_sealed_test`'s `IntegrityError` branch (`:428-441`)
     returned the winner with `reused=True` — belt and braces with G1.
   * **G3 the strategy version row is new** —
     `result.strategy_version_created is True` when `expect_new_version`.
   * **G4 `git_sha` agreement** — `StrategyVersion.git_sha == result.git_sha`,
     i.e. the row was not left carrying a different commit's sha.
   * **G5 the family's look index advanced by exactly one** — using §4's
     ledger: `this_look == k_prior + 1`. A v0.2.0 that did **not** advance the
     count did not really take a new look.
   * **G6 v0.1.0 untouched (R7)** — for every sibling version of the same
     `Strategy.name`, assert no `StrategySealedTest` row's `evaluated_at`
     changed and no `StrategyPromotionEvaluation` row was deleted: concretely,
     record `(count, max(id))` of both tables per sibling version before the
     run and assert the counts for siblings are unchanged afterwards.

3. **Call site.** `cli.py`'s `evaluate-promotion` gains an opt-in flag
   `--require-new-version` (default off, so the two live v0.1.0 strategies are
   never affected). When set, the command captures `run_started_at`, runs the
   guard after each `evaluate_promotion` call, prints each check, and **exits
   non-zero** if any fails, even when the gate ladder passed. The v0.2.0
   runbook makes the flag mandatory.

**Tests to add** (new `tests/research/test_integration_guard.py`):

1. `test_guard_fails_when_the_sealed_test_was_reused` — evaluate the same
   version/snapshot twice; the second call fails G1 and G2.
2. `test_guard_passes_on_a_genuinely_new_version` — bump `VERSION` on a stub
   strategy; all six checks pass.
3. `test_guard_catches_an_edit_without_a_version_bump` — the R3 trap end to
   end: change the stub's params, keep `VERSION`, re-evaluate; assert G1, G3
   and G5 all fail and that `spec_json_hash` changed while
   `sealed_test_id` did not.
4. `test_guard_fails_when_the_sealed_row_predates_the_run`.
5. `test_guard_reports_v010_siblings_untouched`.
6. `test_cli_exits_non_zero_when_require_new_version_and_the_guard_fails`.

**Expected effect on the two APPROVED strategies:** **none.** The guard is
opt-in, read-only, and runs *after* `evaluate_promotion` returns. It sets no
status and writes nothing. Its only observable effect on a v0.1.0 re-run would
be a non-zero exit if `--require-new-version` were passed — which the runbook
reserves for v0.2.0 integrations.

---

## 7. Combined effect on the two APPROVED strategies

Required outcome: v2 `trend_continuation.short_swing` and v5
`relative_strength.medium_swing` must remain `PAPER_APPROVED`. Verified item by
item, read-only.

| Item | v2 | v5 | Basis |
|---|---|---|---|
| 1 Gate 6 decompose + report | buckets 939/22/75, covered 3/3 — unchanged | 466/11/89, covered 3/3 — unchanged | recomputed (§1.2) |
| 1 Gate 6 `no_proxy_bar == 0` hard fail | satisfied (0) | satisfied (0) | recomputed (§1.2) |
| 1 Gate 6 extended-proxy labelling | 0 bars gained; diagnostic only | 0 warmup trades | recomputed (§1.3) |
| 2 Declared gate-5 axes | v0.1.0 grid unedited | v0.1.0 grid unedited | spec (§2.3) |
| 2 Inert-axis failure | no axis inert on eval 32 | no axis inert on eval 35 | stored `gates_json` (§2.3) |
| 2 Axis mechanism off `StrategySpec` | `spec_json_hash` `2ed97431…` preserved | `dfe696b6…` preserved | hash demo (§2.2) |
| 3 `order_by` on `approved_scopes` | scopes 20, 32 — both snapshot 3 | scopes 23, 35 — both snapshot 3 | query (§3.3) |
| 3 Universe comparison | run 33 universe set-equal to both scopes | set-equal to both scopes | query (§3.3) |
| 4 Sealed-look counter | reporting only, `k_prior = 4` | reporting only, `k_prior = 4` | query (§4.1) |
| 5 Gate-7 comment fix | no executable change | no executable change | §5.2 |
| 6 Integration guard | opt-in, post-hoc, read-only | opt-in, post-hoc, read-only | §6.2 |

**No item changes any gate verdict for either approved strategy.** Two of the
checks (gate-6 `no_proxy_bar == 0`, gate-5 inert axis) are genuinely new ways
to fail; both were evaluated against the actual stored/recomputed evidence and
both are satisfied with margin (0 missing bars; 4 of 4 live axes).

**Separate, pre-existing (FACT):** both strategies are already **out of live
scope** because the effective research `config_hash` no longer matches their
approvals (§3.3). Their DB `status` is `PAPER_APPROVED` and this spec does not
change either fact. It needs an operator decision, not a code change.

---

## 8. R4 ledger — is each change stricter, neutral, or looser?

| Change | Direction | Justification |
|---|---|---|
| Gate 6 decomposition + reporting | **neutral** | `covered` computation byte-identical; only `detail`/`evidence` grow |
| Gate 6 census assertion | **stricter** | new failure when trades don't reconcile |
| Gate 6 `no_proxy_bar == 0` | **stricter** | new failure condition; no threshold introduced (bar is zero) |
| Gate 6 extended-proxy labelling **in scoring** | **LOOSER — not adopted** | bucket counts can only rise ⇒ easier to clear the floor. Diagnostic only; promoting it needs operator sign-off |
| Gate 5 declared axes | **stricter** | more of the parameter space perturbed; thresholds unchanged |
| Gate 5 inert-axis detection | **stricter** | new `fragile` reason |
| `approved_scopes` `order_by` | **neutral** | membership unchanged; only order fixed |
| `scan_scope_matches` universe | **stricter** | adds a conjunct; can only turn `True` → `False` |
| Sealed-look counter | **neutral** | reporting; cannot affect `passed` |
| Gate 7 comment | **neutral** | comment only; code untouched (and explicitly *not* changed) |
| Integration guard | **stricter** | new post-hoc precondition on integrating a v0.2.0 |

No `PromotionThresholds` value, no `CostModel` value, and no
`_sensitivity_plan` v0.1.0 grid is edited anywhere in this spec.

---

## 9. Suggested order of work

1. **§5** gate-7 comment (one line, zero risk) — removes a standing ambiguity
   that every later forecast depends on.
2. **§1** gate-6 decomposition and reporting — unblocks MAP §4.2 item 5, which
   is unanswerable without the unbucketed count.
3. **§4** sealed-look counter — needed by every report from here on, and it
   resolves MAP's own k=5-vs-6 contradiction.
4. **§3** approval-scope determinism and universe comparison — self-contained,
   and it hardens the live path before any new snapshot appears.
5. **§2** gate-5 axis mechanism — required *before* the first v0.2.0 is written,
   because the axis set must be pre-registered ahead of results.
6. **§6** integration guard — required *before* the first v0.2.0 is integrated.

Items 1–4 are independent of each other. Items 5 and 6 are prerequisites of the
implementation phase, not of the design phase.

After every item: re-run the full test suite and the repo's own gates
(`make secrets` and the rest) before committing, per the standing rules.

---

## 10. Caveats and things this spec deliberately does not do

* **The two approved strategies are already out of live scope** on
  `config_hash` (§3.3). Nothing here fixes it; it is the single most consequential
  live-state finding of this exercise and needs an operator decision (re-evaluate
  under the current config, creating look 5 on snapshot 3 for both families — or
  accept that probation collects no evidence).
* **Nothing sealed motivated anything here.** Every number used to design a
  change comes from the pre-sealed span `[2016-09-10 .. 2025-09-07]`. Sealed
  numbers appear only in §4's illustration of what the counter would print, which
  is disposition/reporting, not design (R1).
* **The extended-proxy labelling is not proposed for the scoring path.** It is
  the one candidate fix that would make a gate easier, and it is quarantined as
  a diagnostic for that reason (§1.5 Change C, §8).
* **Gate 7's code is not changed**, only its comment (§5.2). Changing the trade
  set gate 7 measures is a re-specification, not a hardening.
* **Bucket counts are censuses, not estimates.** The §1.2 and §1.4 tables are
  deterministic recomputations of the same code over the same data, so they carry
  no sampling error; the only SEs in this document attach to expectancies (§1.6,
  §4.2), where they belong.
* **The bootstrap still assumes iid trades** and 15 of the 24 symbols are ETFs
  (MAP §3a). Every CI quoted here inherits that; none of the six items addresses
  it, and none makes it worse.
* **`k` definition.** This spec fixes `k_prior = 4`, `this_look = 5` for a first
  v0.2.0 seal, matching MAP §0.1/R2 and the task brief. MAP §4.2 item 10 says
  "look 6" and should be corrected when this counter ships.
* **Runtime.** Item 2 roughly triples gate 5's cost per strategy (≈ 20 s → ≈ 55 s
  measured on this machine for a 24-symbol, 9-year, 3-axis grid). Item 1 adds one
  extra proxy load. Everything else is free.
