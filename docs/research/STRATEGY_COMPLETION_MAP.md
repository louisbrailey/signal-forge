# Strategy Completion Map — Phase 1 (Understand)

Read-only synthesis of ten parallel readers over `/Users/louisbrailey/signal-forge`,
the committed reports, and read-only `SELECT`s against `data/signalforge.sqlite`.
No repo file other than this one was written; no command that writes to the live
database was run; no provider API was called.

**Revision note (post-critique).** This edition corrects three load-bearing errors in
the first draft — the sealed-look count (understated 4×), the presentation of v3's
gate-9 failure as a strategy property rather than a snapshot-dependent one, and the
claim that universe expansion fixes v6's gate 4 — and adds the two things the brief
asked for that were missing: statistical-power arithmetic (§0.3) and a quantified
cost/slippage treatment (§0.4). A **Critic responses** appendix records the two
critique items that did not survive checking.

Scope of evidence: promotion evaluations **ids 1–42**, sealed tests **ids 1–20**,
across dataset snapshots **1–4**. The *headline* evaluations remain **ids 31–36**
(2026-09-08 10:13–10:16 UTC) on snapshot **id 3 = `universe_24_ex_meta`**, source
`massive`, sealed window **2025-09-08 → 2026-09-08** — but see §0.1: snapshot 3 is
not one arbitrary choice among four, it is the **only** snapshot on which gate 8
passes at all, and the other three snapshots nevertheless each hold a *locked* sealed
test per version.

Every claim below is labelled **FACT** (verified by file:line or a query result)
or **HYPOTHESIS** (inference that later phases must test). Anything unlabelled in
a table is a queried number. Numbers derived arithmetically from queried numbers are
labelled **DERIVED** and the derivation is shown.

---

## 0. Where the program stands

| Version | Strategy | DB status | Latest eval | Blocking gates (snap 3) | Sealed year (snap 3) |
|---|---|---|---|---|---|
| 2 | `trend_continuation.short_swing` v0.1.0 | PAPER_APPROVED | id 32, passed | — | +0.2982R / 109 trades |
| 5 | `relative_strength.medium_swing` v0.1.0 | PAPER_APPROVED | id 35, passed | — | +0.2935R / **16** trades |
| 3 | `trend_continuation.medium_swing` v0.1.0 | experimental | id 33, NO TRADE | 9 only | −0.0294R / 95 trades |
| 4 | `mean_reversion.short_swing` v0.1.0 | experimental | id 34, NO TRADE | 3, 4, 5, 7 | +0.1278R / 84 trades (gate 9 *passes*) |
| 6 | `volatility_breakout.short_swing` v0.1.0 | experimental | id 36, NO TRADE | 4, 6, 7, 9 | −0.0979R / 10 trades |
| 1 | `intraday_orb.intraday` v0.1.0 | experimental | id 31, NO TRADE | 0 (`data_availability`) | none (no sealed test row) |

FACT: `paper_trade`, `paper_position` and `strategy_health` all have **0 rows**
today; `paper_account` has 1. Probation is switched on
(`auto_simulate_qualified_signals=true`, `paper_probation_enabled=true`,
`alerts_enabled=true`, both daily caps = 2) but has accumulated **zero live
evidence** so far. Nothing downstream of promotion has been exercised on real data.

### 0.1 The sealed-test ledger — every version has been sealed **four** times

FACT (queried, `strategy_sealed_test`): **20 rows — exactly 4 per version for
versions 2–6**, one per dataset snapshot 1–4. `strategy_promotion_evaluation` has
**42 rows**. The first draft of this map treated snapshot 3 as the only sealed draw
and was wrong by 4×.

| Ver | Strategy | snap 1 `universe_25_baseline_legacy` | snap 2 `universe_25_baseline` | snap 3 `universe_24_ex_meta` | snap 4 `universe_25_meta_continuity_corrected` |
|---|---|---|---|---|---|
| 2 | `trend_continuation.short_swing` | id 1: **+0.3246R / 112** ✅ | id 6: **+0.3246R / 112** ✅ | id 11: **+0.2982R / 109** ✅ | id 16: **+0.3246R / 112** ✅ |
| 3 | `trend_continuation.medium_swing` | id 2: **+0.0109R / 98** ✅ | id 7: **+0.0109R / 98** ✅ | id 12: **−0.0294R / 95** ❌ | id 17: **+0.0109R / 98** ✅ |
| 4 | `mean_reversion.short_swing` | id 3: +0.1230R / 91 ✅ | id 8: +0.1230R / 91 ✅ | id 13: +0.1278R / 84 ✅ | id 18: +0.1230R / 91 ✅ |
| 5 | `relative_strength.medium_swing` | id 4: +0.2935R / 16 ✅ | id 9: +0.2935R / 16 ✅ | id 14: +0.2935R / 16 ✅ | id 19: +0.2935R / 16 ✅ |
| 6 | `volatility_breakout.short_swing` | id 5: −0.0979R / 10 ❌ | id 10: −0.0979R / 10 ❌ | id 15: −0.0979R / 10 ❌ | id 20: −0.0979R / 10 ❌ |

All four snapshots cover essentially the same calendar year (snap 1:
2025-09-07→2026-09-07; snaps 2–4: 2025-09-08→2026-09-08). Snapshots 1, 2 and 4 are
the **25-symbol** set (`META`, or `META_CONT` in snap 4); snapshot 3 is the same set
**minus META**. Every cross-snapshot sealed difference in the table above is
therefore exactly the META contribution.

**Consequence for R2: the baseline look count is k = 5, not k = 2.** k counts the
existing `StrategySealedTest` rows for the strategy family (all versions, all
snapshots); the next sealed evaluation is look k+1. A v0.2.0 that seals against
snapshot 3 is therefore **look 6**, not the second and not the fifth. Every
strategy report must state k=5 as the starting count and increment from there.

**Why snapshot 3 is nonetheless the right headline (FACT, and this rebuts the
"snapshot selection" charge).** Gate 8 `data_quality_and_leakage` **fails on
snapshots 1, 2 and 4 for every single version**:

- snaps 1 & 2 — `validate_daily: FAIL (META: 90 missing (6.9%) e.g. 2022-01-31,
  2022-02-01, 2022-02-02)` (evals 2, 8, 14, 26, and the same for versions 3–6);
- snap 4 — `validate_daily: FAIL (24/25 symbols have massive data; missing:
  ['META_CONT'])` (evals 37–42) — the continuity bridge symbol carries source
  `continuity_bridge:1`, not `massive`;
- snap 3 — `validate_daily: PASS; leakage self-check: clean` (evals 19–24, 31–36).

So snapshot 3 is the **only** snapshot on which the ladder can pass at all, and the
choice was forced by gate 8 — a pre-sealed data-quality gate — not selected after
seeing gate 9. That is a legitimate, disclosable reason. What is **not** legitimate
is reporting snapshot 3's gate-9 number as if it were the only draw: three other
locked sealed tests exist per version and must be disclosed alongside it (§2.1).

### 0.2 The gate ladder (exact, `research/promotion.py` + `config/research.py`)

The **trade set** column is new and matters: gates 2/3/4 read `full.out_of_sample`
(the last 40% of *each symbol's own* bars), while gates 1, 6 and 7 read `full.trades`
— the **entire pre-sealed span, IS+OOS**. The per-strategy tables in §2 mix the two,
so each row is now tagged.

| # | Gate | Threshold | Trade set | Source |
|---|---|---|---|---|
| 0 | `data_availability` | `Horizon.INTRADAY` → unconditional fail on the **declared horizon**, no data query; else pre-sealed span ≥ `MIN_PRESEALED_DAYS` (= `ceil(200×365.25/252)+60` = **350** calendar days) | — | promotion.py:512-534, :559-583, :94 |
| 1 | `rolling_walkforward` | **2 of 4** folds with `n_trades ≥ 15` **and** `expectancy_r > 0`. The `len(fold_rows) >= n_folds` conjunct is **definitional, not a test** — the loop appends exactly `n_folds` rows (:613-628), so it is always true. The per-fold trade floor is `th.sensitivity_min_grid_trades` (15) — **gate 1 reuses gate 5's constant** (:632) | all pre-sealed (`full.trades`, :616) | promotion.py:606-649, :632, :635; research.py:94, 106, 99 |
| 2 | `min_oos_trades` | ≥ 30 | **OOS only** (:652) | research.py:96 |
| 3 | `net_expectancy` | OOS `expectancy_r > 0.0` net of costs | **OOS only** (:652) | research.py:99 |
| 4 | `bootstrap_ci` | 95% CI lower bound `> +0.02R` (2,000 iid resamples, seed 20240101). **This is an n-dependent hurdle, not an effect-size bar**: approximately `exp > 0.02 + 1.96·sd/√n` (§0.3) | **OOS only** (:679) | research.py:102; montecarlo.py:18-20, 30-33 |
| 5 | `parameter_sensitivity` | ≥ 60% grid points positive, ≥ 75% one-step neighbours positive, each cell ≥ 15 trades. Grid perturbs **2 axes** per strategy (§0.5) | OOS within each re-run | research.py:104-106; promotion.py:161-210 |
| 6 | `regime_coverage` | all 3 of bull/bear/range with ≥ 10 trades each. **Buckets do not sum to the trade count** (§0.6) | all pre-sealed (`full.trades`, :743) | research.py:109-110; promotion.py:739-763 |
| 7 | `benchmark_comparison` | strategy Sharpe > SPY buy-and-hold Sharpe over the matched span. **Docstring/code divergence — see below** | all pre-sealed (`full.trades`, :775) | research.py:114; promotion.py:775 |
| 8 | `data_quality_and_leakage` | fresh `validate_daily` pass + `assert_no_lookahead` self-check | — | research.py:116-117 |
| 9 | `sealed_final_test` | ≥ 10 trades **and** expectancy ≥ 0.0R, computed **once** and pinned per `(version, snapshot)` | sealed window only | research.py:121-123; promotion.py:354-449, :402 |
| 10 | `live_paper_probation` | `health_monitor.enabled` | — | research.py:233 |

`passed = bool(gates) and all(g.passed for g in gates)` (**promotion.py:922**; the
verdict string is :923). `_finalize`'s insert is :926-943. Gates 1–8 run only on the
**pre-sealed** span `[start, sealed_start−1]`; gate 9 runs only on
`[sealed_start, end]`.

**Open item for the operator — gate 7 docstring contradicts the code.** FACT:
`config/research.py:111-113` documents gate 7 as *"OOS Sharpe vs SPY buy-and-hold
Sharpe over the same span"*. FACT: `promotion.py:775` computes
`pm_strategy = compute_portfolio_metrics(full.trades, …)` — **all pre-sealed trades,
IS+OOS**. The code is what runs; the docstring is wrong. This is flagged, not
"fixed": editing it is a repo write outside this phase, and correcting the comment
rather than the code is the operator's call. Until it is resolved, every gate-7
forecast in §4.2 must be stated over **all pre-sealed trades**.

### 0.3 Statistical power — what these gates can and cannot detect

DERIVED. The stored bootstrap CIs are the only dispersion information the pipeline
persists, so the per-trade standard deviation is recovered from the half-width:
`sd ≈ (hi − lo)/2 · √n / 1.96`. This inverts a **percentile** bootstrap under a
normal approximation, so treat every figure below as accurate to ~2 significant
figures, not exact. All inputs are queried from `gates_json` on evals 32–36.

| Ver | Strategy | OOS n | OOS exp | 95% CI | implied per-trade sd | SE(OOS) | **n required to clear gate 4 at this point estimate** |
|---|---|---|---|---|---|---|---|
| 2 | `trend.short_swing` | 341 | +0.2648 | [+0.1129, +0.4143] | 1.420 | 0.0769 | **129** (has 341) |
| 3 | `trend.medium_swing` | 319 | +0.3064 | [+0.1205, +0.5027] | 1.741 | 0.0975 | **142** (has 319) |
| 5 | `relative_strength.med` | 197 | +0.3004 | [+0.0901, +0.5046] | 1.484 | 0.1057 | **108** (has 197) |
| 4 | `mean_reversion.short` | 309 | −0.0837 | [−0.1739, +0.0061] | 0.807 | 0.0459 | **never** (point estimate negative) |
| 6 | `volatility_breakout` | 51 | +0.0613 | [−0.3553, +0.4979] | 1.554 | 0.2176 | **5,428** (has 51) |

**Gate 4 restated as an n-dependent hurdle.** `exp > 0.02 + 1.96·sd/√n`. For v6
(sd = 1.554):

| n | margin term `1.96·sd/√n` | required expectancy |
|---|---|---|
| 51 (today) | 0.4266 | **+0.4466R** |
| 100 | 0.3046 | +0.3246R |
| 319 (6.25× breadth) | 0.1706 | **+0.1906R** |
| 1,000 | 0.0963 | +0.1163R |
| 5,428 | 0.0413 | **+0.0613R** (= the observed point estimate) |

Every "shortfall" figure quoted against gate 4 in the first draft (notably v6's
"0.3753") is the distance to a bar whose height depends on the sample size, not an
effect-size gap. §2.3's table now reports **required n** instead.

**Sealed-test power, in SE units.** Sealed SE uses the same implied per-trade sd at
the sealed trade count.

| Sealed test | n | exp | SE | exp / SE |
|---|---|---|---|---|
| v2 snap 3 (approved) | 109 | +0.2982 | 0.136 | **+2.19** |
| v3 snaps 1/2/4 | 98 | +0.0109 | 0.176 | +0.06 |
| v3 snap 3 (the "failure") | 95 | −0.0294 | 0.179 | **−0.16** |
| v4 snap 3 | 84 | +0.1278 | 0.088 | +1.45 |
| v5 snap 3 (**approved**) | 16 | +0.2935 | **0.371** | **+0.79** |
| v6 snap 3 | 10 | −0.0979 | **0.491** | −0.20 |

Consequences the first draft did not state:

- **v3's sealed −0.0294R is −0.16 SE from zero.** The first draft's "~1
  standard-error-ish noise around zero" (old §2.1 lever 5) overstated the distance by
  about 6×. It is *far* closer to zero than one SE.
- **But it is also meaningfully below its own pre-sealed mean.** −0.0294 vs +0.3064
  is a gap of −0.3358R: **z = −1.88** treating the pre-sealed mean as a known
  constant, **z = −1.65** on the two-sample SE `√(SE_sealed² + SE_pre²)` that properly
  accounts for the pre-sealed mean's own uncertainty. Both are "wrong in the other
  direction" from "noise around zero": the sealed year is unremarkable relative to
  zero and mildly disappointing relative to the pre-sealed estimate.
- **Under the pre-sealed estimate, `P(sealed mean < 0 | n = 95) = 4.3%`** — a 1-in-23
  event. That is mild evidence the pre-sealed +0.3064R is optimistic (selection,
  regime, or both), not the neutral coin-flip the first draft implied.
- **Gate 9 at n = 10 has essentially no discriminating power.** v6's sealed SE is
  **0.49R**. Gate 9 would reject a genuinely **+0.30R** strategy **27%** of the time
  at n=10, and a genuinely +0.0613R strategy 45% of the time. v6's gate-9 sign is
  therefore a **fourth power failure**, not (as the first draft said) "an
  edge-quality failure on top of" the power failures.
- **v5 — the weakest evidence supporting anything currently live.** PAPER_APPROVED on
  a **16-trade** sealed test. At its own implied sd of 1.484, SE = **0.371R**, so
  +0.2935R is **0.79 SE** from zero: gate 9 passed it, but the sealed evidence for v5
  is under one standard error. This is a standing caveat on the live probation, and
  it interacts with §3(c): `health_monitor`'s z-score treats the backtest expectancy
  as a known constant, so for v5 both sides of the comparison are noisy.
- Gate 4's binding sample sizes (129/142/108) explain why v2, v3 and v5 clear it
  comfortably at n≈200–340 while v6 cannot at n=51.

### 0.4 Cost and slippage, quantified in R

The first draft asserted the cost model was "frozen" but never said what it costs.

FACT: `costs.py:11-16` — `commission_per_share = 0.0`, `commission_min_per_order =
0.0`, `slippage_bps = 3.0`, `half_spread_fill_penalty = True`.
FACT: `engine.py:90` — `run_backtest(..., spread_bps: float = 5.0, ...)`, and
`engine.py:94` `slip = (3.0 + 5.0/2)/10_000 = 5.5 bps` per side.
FACT: `engine.py:143` records `costs_bps = slip * 2 * 10_000` → **11.0 bps of
notional per round trip**, for every trade in the program.
FACT (the gap): `backtest_runner.py:205-206` calls
`run_backtest(series, fn, cost_model=cost_model, warmup=min_bars // 2)` — **without
`spread_bps`**. Every symbol therefore gets the same flat 5.0 bps assumed spread:
SPY and the 150th name by ADV alike. The spread term is **universe-independent**.

FACT: `engine.py:110` defines `risk_per_share = abs(entry_fill − sig.stop_price)`,
i.e. R ≈ `stop_atr × ATR`. So per-trade cost in R is
`round_trip_bps / 10_000 ÷ (stop_atr × ATR/price)`.

DERIVED, at a reference ATR/price of 2% (and 1.5% for `volatility_breakout`, whose
entry filter `ATR(10)/ATR(50) ≤ 0.75` selects a **contracted** ATR by construction,
`breakout.py:27`):

| Strategy | `stop_atr` | risk / price | cost @ **11 bps** (today) | @ 26 bps | @ 36 bps | @ 66 bps |
|---|---|---|---|---|---|---|
| `trend_continuation.*` | 1.50 | 3.00% | **0.037R** | 0.087R | 0.120R | 0.220R |
| `mean_reversion.short` | 2.00 | 4.00% | **0.028R** | 0.065R | 0.090R | 0.165R |
| `relative_strength.med` | 2.50 | 5.00% | **0.022R** | 0.052R | 0.072R | 0.132R |
| `volatility_breakout` | 1.75 (on contracted ATR) | 2.63% | **0.042R** | 0.099R | 0.137R | 0.251R |

Read the columns as: round trip `= 2 × (3.0 + spread_bps/2)` bps, so 26 bps
corresponds to an assumed 20 bps quoted spread, 36 bps to 30 bps quoted, 66 bps to
60 bps quoted (i.e. a 30 bps *half*-spread).

Two things follow immediately:

1. **`volatility_breakout` pays the highest cost in R of any strategy in the
   program** — because it deliberately enters when ATR is compressed, its risk unit
   is smaller and the same 11 bps buys a bigger slice of it. **0.042R is 68% of its
   entire +0.0613R OOS edge.** Any change that raises turnover, or any universe whose
   real spreads exceed the modelled 5 bps, attacks that edge directly.
2. **Universe expansion carries a cost term of the opposite sign to its power
   benefit, and the first draft treated expansion as pure upside.** Names ranked
   25–150 by ADV plausibly quote wider than the 5 bps flat assumption. At a 20–30 bps
   quoted spread the modelled round trip becomes 26–36 bps (2.4–3.3× today), taking
   trend-family cost from 0.037R to **0.087–0.120R** and breakout cost from 0.042R to
   **0.099–0.137R** — an *increment* of 0.05–0.10R per trade, which for v6 is larger
   than its whole point estimate. §4.2 item 8 now requires this to be forecast, and
   §3(a) requires a 2× and 5× spread sensitivity on any expanded snapshot.

### 0.5 What gate 5 actually perturbs (coverage fractions)

FACT (`promotion.py:161-210`), against the `baseline_params` recorded in each gate-5
evidence blob:

| Strategy | Grid axes (promotion.py) | Params dataclass fields | Coverage | The parameter gate 5 does **not** touch |
|---|---|---|---|---|
| `trend_continuation.*` | `sma_fast [15,20,25]` × `stop_atr [1.2,1.5,1.8]` (:187) | 8 (`TrendParams`, trend_continuation.py:21-29) | **2 / 8** | **`time_stop_bars`** — the *only* thing distinguishing v3 from v2 |
| `mean_reversion.short` | `z_entry [−2.5,−2.0,−1.5]` × `stop_atr [1.5,2.0,2.5]` (:197) | 6 (mean_reversion.py:22-27) | **2 / 6** | `time_stop_bars`, `sma_window`, `z_lookback`, `atr_window` |
| `volatility_breakout` | `contraction_max [0.65,0.75,0.85]` × `stop_atr [1.5,1.75,2.0]` (:208) | 7 (`BreakoutParams`, breakout.py:25-32) | **2 / 7** | `channel`, `target_atr`, `time_stop_short/medium`, `atr_window` |
| `relative_strength.med` | `excess_return_min [0.03,0.05,0.07]` × `lookback [42,63,84]` (:176) | 8 | **2 / 8** | `stop_atr`, `target_atr`, `time_stop_*`, `sma_window` |

**This is the single most consequential correction to §2.1.** `time_stop_bars`
(10 for SHORT_SWING vs 40 for MEDIUM_SWING, `trend_continuation.py:37-39`) is the
whole difference between v2 and v3, and gate 5 **never varies it**. The first
draft's claim that "the pre-sealed neighbourhood is already characterised as robust"
is true only inside a 2-of-8 slice that **excludes the map's own primary hypothesis**
(H1/H2). It has been deleted from lever 3 and replaced.

Generalised: **the decisive new parameter of a v0.2.0 is exactly the one gate 5 will
not test unless it is added as an axis.** That is the cleanest available route to a
hidden-fragility pass, and §4.2 item 6 now *requires* closing it.

### 0.6 Gate 6's buckets do not sum to the trade count

FACT: `promotion.py:744` labels each trade via
`regimes.get(t.entry_date, "warmup")`, where `regimes = label_regimes(proxy_full)`.
FACT: `backtest/regime.py:20,36-37` — `TREND_LOOKBACK = 200`, and every one of the
first 200 proxy sessions is labelled `"warmup"`. `"warmup"` matches none of the three
`if/elif` branches (:745-750), so those trades land in **no** bucket. The engine's own
warmup is only `min_bars // 2 = 30` bars (`backtest_runner.py:181, 206`), so real
trades do occur inside the proxy's 200-session warmup. A trade whose `entry_date` has
no proxy bar at all falls into the same hole.

DERIVED (gate 7's `full.trades` count vs the gate-6 buckets, evals 32–36):

| Ver | `full.trades` | bull | bear | range | bucketed | **unbucketed** | share |
|---|---|---|---|---|---|---|---|
| 2 | 1,169 | 939 | 22 | 75 | 1,036 | **133** | 11.4% |
| 3 | 1,071 | 857 | 22 | 69 | 948 | **123** | 11.5% |
| 4 | 984 | 618 | 46 | 260 | 924 | **60** | 6.1% |
| 5 | 566 | 466 | 11 | 89 | 566 | **0** | 0.0% |
| 6 | 211 | 167 | 0 | 30 | 197 | **14** | 6.6% |

v5's zero is consistent with `relative_strength`'s own long feature warmup
(`sma_window=100`, `lookback=63`) pushing its first trade past the proxy's
200-session mark. §4.2 item 5's mandatory gate-6 forecast is not answerable without
reporting this count, so it is now required.

---

## 1. Rules of engagement (binding on every later phase)

These extend, and do not relax, the seven rules in `STRATEGY_COMPLETION_PLAN.md:29-41`.
Each rule carries its enforcement mechanism, because several are *not* enforced by
code and therefore depend on discipline plus disclosure.

**R1 — Sealed data may inform *disposition*, never *design*.** (Restated; the first
draft's blanket "sealed numbers may never appear in a justification" was violated by
the map itself — see the Critic responses appendix, item 17.)

- **Permitted:** using a sealed result to decide *whether to ship, whether to stop
  trying, or whether to declare a documented fail*. Deciding **not** to change
  anything is a decision, and it is legitimately informed by the sealed outcome.
- **Forbidden:** letting any sealed number motivate a **parameter, filter, exit,
  entry, or universe** choice. v3 misses gate 9 on snapshot 3 by 0.0294R — that
  number must never be the target of a change.
- **Disclosure:** every place a sealed number appears inside an argument must be
  marked inline. In this document they are: §2.1 lever 5 (disposition — permitted),
  §2.2's closing diagnosis paragraph (disposition/illustrative — permitted, and
  marked), and §2.3 H11 (disposition — permitted, and marked). No lever, hypothesis
  or parameter recommendation in §2 is derived from a sealed number.
- **New: the choice of *which* sealed snapshot to cite is itself a sealed-window
  choice.** Five sealed draws now exist per family (§0.1). Which one a report leads
  with must be **pre-registered** — and the pre-registered answer today is "snapshot
  3, because it is the only snapshot on which gate 8 passes (§0.1)", with the other
  three disclosed alongside it in every case.

*Enforcement: none in code. Depends on written justification plus the inline marking above.*

**R2 — Sealed re-runs are "looks", counted and disclosed. The current count is k = 5.**
FACT: no counting mechanism exists anywhere in `src/signalforge` (grep for
`second_look`/`sealed_look`/`look_count`/`n_looks` returns zero hits). The only
structural protection is the unique constraint on
`(strategy_version_id, dataset_snapshot_id)` (`db/models/research.py:263`) plus
the read-before-recompute in `_get_or_create_sealed_test` (promotion.py:377-384):
a repeat call returns the *identical locked numbers*, never a new draw.
FACT: the implicit look count is reconstructable as the number of distinct
`(strategy_version_id, dataset_snapshot_id)` pairs in `strategy_sealed_test` —
**20 rows, 4 per version for versions 2–6** (§0.1) — plus, for evaluation history,
the append-only `StrategyPromotionEvaluation` rows (42, promotion.py:926-943). Nothing
computes or surfaces either.
Therefore each strategy's final report **must state explicitly**: the four existing
sealed draws with their ids and results (the §0.1 table), and then the new one. k is
the count of existing `StrategySealedTest` rows for the strategy family (all
versions, all snapshots); the next sealed evaluation is look k+1. **A v0.2.0 sealing
against snapshot 3 is look 6** (today k=5); a v0.3.0 would be look 7. A pass on
look *k+1* must be reported as "passed on look k+1", never as an unqualified pass.
Evaluating even an *unchanged* v0.1.0 against a new snapshot also creates a fresh
sealed test — see §3(a).

**R3 — Only a bumped `version` earns a fresh sealed look; never silently reuse one.**
FACT (a real trap): `upsert_strategy_version` (persistence.py:46-93) refreshes
`spec_json` and `git_sha` on the **same row** when the version string is unchanged,
and never touches `status`. So editing strategy code *without* bumping `version`
causes gates 1–8 to recompute against the new code while gate 9 **replays the old
sealed result measured against the old code**. That is a silently invalid pass.
Every behavioural change ships as `VERSION = "0.2.0"` (a new `StrategyVersion` row,
hence a never-before-sealed gate 9). No exceptions, including "tiny" parameter edits.

**R4 — No gate or threshold weakened; cost model unchanged. The carve-out is
symmetric.**
`PromotionThresholds` (config/research.py:93-123) and `CostModel`
(backtest/costs.py:11-16 — `slippage_bps=3.0`, `half_spread_fill_penalty=True`,
commission 0) are frozen for the duration of the program. No threshold in
`promotion.py` or `_sensitivity_plan` may be edited to make a strategy pass.

**Permitted, and the rule is now stated symmetrically:** a change to the promotion
path is allowed when it makes a gate *runnable or more faithful* without making it
*easier to pass*. Two instances:
1. *Adding* a sensitivity grid for a family that has none — gate 5 currently
   hard-fails such families (promotion.py:694-703). The grid must be a genuine
   ±1-step neighbourhood around the shipped parameters, chosen before results are seen.
2. *Replacing gate 0's declared-horizon test with an actual `OHLCVIntraday`
   availability query* (promotion.py:512). This is the same kind of change: it keeps
   failing for as long as no intraday data exists, and it can only ever be *harder*
   to satisfy than a hard-coded fail is to trip. The first draft claimed R4 forbade
   this; that was internally inconsistent with carve-out (1). **However** — this is
   a promotion-path edit on a strategy that remains blocked at two further,
   independent layers (§2.4 blocks 2 and 3), so it needs an operator decision and buys
   nothing on its own. It is permitted-in-principle, not recommended.

**Adding a stricter reported statistic is never a weakening.** Reporting a
date-clustered / block-bootstrap CI *alongside* the gate-4 iid CI (§3a) is a
diagnostic addition, not a gate change, and is explicitly permitted.

**R5 — Multiple-testing discipline.** Every variant evaluated — including ones
abandoned after a walk-forward run — is recorded per strategy: what was changed,
why (with pre-sealed evidence), and the pre-sealed OOS expectancy / CI it produced.
The final report states the variant count. A design that survives 1 of 12 tried
variants is reported as such, and its bootstrap CI is understood to be optimistic
by roughly the selection it survived. Prefer few, mechanism-motivated variants over
grid sweeps: each additional variant costs credibility that the gates cannot restore.

**R6 — Source isolation.** Research reads source `massive` only, via
`repository.get_daily_bars(..., source=…)` (repository.py:17-27, 47-65). The bulk
`massive_grouped` rows (2,655 symbols, 2025-01→2026-09 only) are for universe
screening, never for backtests. A larger research universe means a **new
`DataSnapshot` with a new key** and real per-symbol `massive` history — never a blend.
FACT (gap to respect, not to exploit): `research/universe.py:screen_universe`
(lines 45-76) queries `OHLCVDaily` **without a source filter** (:51-56, :59-64,
:69-74), so its history/price/ADV figures blend both sources for any dual-source
symbol. It feeds only the `signalforge universe screen` CLI display (cli.py:470) and
no gate — but its output must not be cited as evidence of how much `massive` history
a candidate symbol has.
FACT (related, and it bit snapshot 4): a symbol whose bars carry a non-`massive`
source — `META_CONT` at `continuity_bridge:1` — **fails gate 8** outright
(§0.1). Any expanded universe must be genuinely `massive`-sourced end to end.

**R7 — New behaviour ships as v0.2.0; v0.1.0 stays intact and scoped.**
v0.1.0 rows, sealed tests and approved scopes are never mutated, re-run or purged.
For the two PAPER_APPROVED strategies (v2, v5) the live approved scope must keep
matching their v0.1.0 spec hash: registering a v0.2.0 sibling must not disturb
`approval_scope.current_spec_json_hash()` for the approved version. Registering a
new version requires touching exactly three places (all FACT):
`research/strategies/__init__.py:43-51` (`default_strategies()` — 6 entries),
`research/promotion.py:161-210` (`_sensitivity_plan` grid), and — automatically —
`persistence.upsert_strategy_version` via `evaluate_promotion` (promotion.py:508).

**R7b — the `scopes[0]` ordering hazard (new).** FACT:
`paper_probation.py:113-122` picks which sealed test the probation dashboard displays
via `scopes[0].dataset_snapshot_id`, and `approved_scopes` (approval_scope.py:45-66)
issues its `select` with **no `order_by`** — row order is whatever SQLite returns.
FACT (current state, recorded now so a future change is detectable): v2 and v5 each
have **exactly two** passing evaluations, and **both are on snapshot 3** —
v2: evals **20** and **32** → sealed test **11** (+0.2982R / 109); v5: evals **23**
and **35** → sealed test **14** (+0.2935R / 16). Because both scopes carry the same
`dataset_snapshot_id`, the displayed sealed test is deterministic today regardless of
ordering. The hazard is **prospective**: any new passing evaluation on a *different*
snapshot adds a scope with a different `dataset_snapshot_id`, at which point which
sealed test the dashboard shows for a **live** strategy becomes order-dependent
(for v2 that would be +0.3246R/112 vs +0.2982R/109). Before any new evaluation is run
against an expanded snapshot, re-record the above and check the dashboard afterwards.

**R8 — Live paper is the confirming test, never the promoting one.**
FACT: no code path re-promotes from live evidence; `health_monitor` is a one-way
downgrade guard (PAPER_APPROVED → EXPERIMENTAL → DISABLED, health_monitor.py:100-113),
and `paper_probation.py` is read-only by design (docstring lines 1-8). Live paper
may confirm or contradict a promoted v0.2.0; it may never be used as an argument
for promoting one.

**R9 — Paper-only, no LLM decisions.** LLMs summarise audited evidence. No
brokerage, no discretionary override, no strategy logic that consults a model.

**R10 — Every proposal must be falsifiable before it is implemented.** Each design
states in advance what pre-sealed result would kill it (§2 gives these per hypothesis).
A proposal whose author cannot name a killing observation is not a hypothesis, it is
a preference, and should be dropped. **Added:** a falsification condition must be
stated to survive **all four snapshots**, not one — a diagnostic that holds only on
snapshot 3 is a snapshot artefact (§2.1).

---

## 2. Per-strategy map

### 2.1 `trend_continuation.medium_swing` v0.1.0 (version 3) — a 3-trade, snapshot-dependent miss

**Gate-by-gate (evaluation id 33, snapshot 3), with trade sets tagged:**

| Gate | Trade set | Achieved | Threshold | Margin |
|---|---|---|---|---|
| 1 walkforward | all pre-sealed (1,071) | 4 folds: +0.1822/310, +0.0772/323, +0.0343/179, +0.3513/259 → 4 of 4 clear | ≥ 2 of 4 with n≥15 & exp>0 | pass |
| 2 OOS trades | **OOS (319)** | 319 | ≥ 30 | pass |
| 3 net expectancy | **OOS (319)** | **+0.3064R** | > 0 | +0.306 |
| 4 bootstrap CI low | **OOS (319)** | **+0.1205R** | > +0.02 | pass; required n at this estimate = **142** |
| 5 sensitivity | OOS per grid point | **9/9 (100%)** positive — on `sma_fast` × `stop_atr` **only** | ≥ 60% / ≥ 75% nbr | wide, **but see §0.5** |
| 6 regime | all pre-sealed (1,071) | bull 857 / bear 22 / range 69; **123 unbucketed (11.5%)** | ≥ 10 each | pass |
| 7 benchmark | all pre-sealed (1,071) | Sharpe **1.156** vs SPY 0.719 | > SPY | +0.437 |
| 8 data/leakage | — | pass (snapshot 3 only — §0.1) | pass | — |
| **9 sealed** | sealed year | **−0.0294R on 95 trades (snapshot 3)**; **+0.0109R on 98 trades (snapshots 1, 2, 4)** | ≥ 0.0R | **fails on 1 of 4 snapshots** |
| 10 probation | — | pass | enabled | — |
| hit rate / PF / Sharpe / maxDD (sealed, snap 3) | sealed year | 0.379 / 0.957 / −0.187 / 8.91% | — | — |

**Diagnosis (restated — this is the correction the first draft most needed).**

FACT: **v3 passes gate 9 on three of its four sealed tests.** Sealed ids 2 (snap 1),
7 (snap 2) and 17 (snap 4) all return **+0.0109R on 98 trades, passed=1**; only id 12
(snap 3) returns **−0.0294R on 95 trades, passed=0** (§0.1).

FACT: the entire difference is the removal of META. Snapshot 3 is snapshots 1/2/4
minus one symbol, and 98 − 95 = **3 trades**. DERIVED: those 3 trades are worth
`98 × 0.0109 − 95 × (−0.0294) = 1.068 + 2.793 = **+3.86R**`.

FACT: on the pre-sealed side snapshot 3 is if anything the *weakest* of the four for
v3 — snap 4 gives OOS +0.3169R / n=336 / CI low +0.1331 (eval 39) against snapshot
3's +0.3064R / 319 / +0.1205. So this is not "snapshot 3 is a harder test"; it is
"three specific META trades in the sealed year".

FACT: the *only* coded difference between `short_swing` (approved, sealed +0.2982R
on 109 trades) and `medium_swing` is one line —
`TrendParams(time_stop_bars=40) if horizon is MEDIUM_SWING else TrendParams()`
(trend_continuation.py:37-39). `sma_fast=20`, `sma_slow=50`, `vol_window=20`,
`vol_mult=1.3`, `atr_window=14`, `stop_atr=1.5`, `target_atr=3.0` are byte-identical
across both horizons (trend_continuation.py:21-29). Entry and exit logic are shared
verbatim (:85-133). `domain.py:16-17` labels SHORT_SWING "2–10 trading days" and
MEDIUM_SWING "2–8 weeks" (≈10–40 sessions).

FACT: sealed profit factor 0.957 with hit rate 0.379 against a nominal 1:2 R:R
(stop 1.5×ATR, target 3.0×ATR) — the geometry needs ~33.3% winners to break even
gross, so the strategy is roughly at its break-even hit rate before costs and is
pushed under by them. DERIVED (§0.4): the cost is **0.037R/trade** at a 2% ATR, i.e.
the whole snapshot-3 sealed shortfall (0.0294R) is smaller than one trade's modelled
transaction cost.

DERIVED (§0.3): the snapshot-3 sealed mean is **−0.16 SE** from zero, and −1.65 to
−1.88 σ below its own pre-sealed mean; `P(sealed mean < 0 | pre-sealed estimate,
n=95) = 4.3%`.

**The honest statement of the gate-9 result is therefore:** *gate 9's outcome for v3
is snapshot-dependent, turning on 3 META trades worth +3.86R; the sealed mean is
statistically indistinguishable from zero on every snapshot (+0.06 SE to −0.16 SE);
and it is mildly (1.65σ) below the pre-sealed estimate on all of them.* It is **not**
"v3 fails gate 9", full stop, and it is **not** evidence of a duration defect.

FACT: there is nothing horizon-specific to have overfit here. Whatever passed
gates 1–8 is the *short-swing* rule set evaluated with a longer leash.

**Hypotheses — demoted from "diagnosis" to "unmotivated until a diagnostic supports
them".** H1–H4 were built on top of the snapshot-3 gate-9 number. That number does
not support them: it moves by 3 trades and it reverses on three of four snapshots.
Each is retained as a *possible* mechanism, but **none may motivate a v0.2.0 until a
pre-sealed diagnostic shows the effect and shows it on all four snapshots** (R10).

- **H1 (duration mismatch)** — *demoted, formerly "primary"*. A 40-bar leash on
  entry/exit machinery calibrated over 14–50-bar lookbacks may hold positions through
  more trend reversals than the 10-bar version sees. *Required before it may motivate
  anything*: pre-sealed OOS P&L by holding-bucket (1–10, 11–20, 21–40 bars) showing
  buckets 11–40 net negative in per-bar R, **on all four snapshots**. *Falsified if*
  those buckets are net positive and comparable in per-bar R to 1–10.
- **H2 (target unreachable inside the leash)** — *demoted*. A 3.0×ATR(14) target may
  frequently not be reached within 40 bars, making the time stop the modal exit.
  *Falsified if*: the pre-sealed exit-reason mix shows target hits dominate, or that
  time-stop exits are on average non-negative.
- **H3 (stale volatility scale)** — *demoted*. ATR(14) at entry may be a poor risk
  scale 40 bars later. *Falsified if*: ATR(14)@exit / ATR(14)@entry is tightly
  clustered near 1 across pre-sealed medium_swing trades.
- **H4 (volume confirmation decays)** — *demoted*. `vol_ratio ≥ 1.3` over 20 days is a
  short-horizon trigger whose content may decay well before a 40-bar hold ends.
  *Falsified if*: pre-sealed expectancy conditioned on entry `vol_ratio` bucket is flat.
- **H5 (short-side asymmetry).** Longs need only `not risk_off`; shorts additionally
  require `Trend.BEAR` (:115-122). Not medium-swing-specific, so unlikely to explain
  the differential, but it means short exposure is nearly absent outside confirmed
  bears. *Falsified if*: pre-sealed short trades are a negligible share of trade count.

**Candidate levers, re-ranked (lever 5 promoted to first):**

1. **Do nothing to the rule set; document the result honestly and completely.**
   *(Promoted from 5th.)* This is now the leading option on the evidence, and it is a
   **disposition** decision, so R1 permits the sealed numbers below.
   v3 has an 8/9 pre-sealed profile materially *stronger* than the approved v2 on
   gates 3, 4, 7 (+0.3064R vs +0.2648R; CI low +0.1205 vs +0.1129; Sharpe 1.156 vs
   0.807). Its gate-9 result passes on 3 of 4 snapshots, and the one failure is worth
   3 trades and 0.0294R — less than one trade's modelled cost. *Any* change targeted
   at closing that gap is selection, not improvement, and would additionally burn
   look 5. HYPOTHESIS: v3's snapshot-3 failure is sampling variation plus one symbol.
   The correct output is a documented "does not pass on snapshot 3, passes on 1/2/4,
   sealed evidence indistinguishable from zero everywhere" — with the §0.1 table and
   the §0.3 SE figures attached.
2. **Scale lookbacks with the horizon** (`sma_fast`/`sma_slow`/`atr_window`
   proportional to intended hold, e.g. ~2× the short-swing windows) — **only if a W2
   diagnostic first establishes a duration effect (H1) that holds on all four
   snapshots.** *Highest robustness of the change options*: a principled cross-horizon
   consistency argument, justifiable entirely on pre-sealed folds. Risk: fewer signals
   → watch gates 2 and 6 (bear bucket is only 22 today; a 40% signal reduction still
   clears the 10-trade floor but not by much) and note the 123 unbucketed trades
   (§0.6) sit outside that count entirely.
3. **Make the exit horizon-consistent** — an ATR-trailing stop after defined R
   progress, or a target scaled to the holding horizon. Addresses H2 and the 0.957
   profit factor. Robustness risk: the lever most easily overfit; restrict to one or
   two structurally distinct variants (R5). **Mandatory under §4.2 item 6:** if the
   change retains `time_stop_bars` as a field while ceasing to use it, gate 5's grid
   must be re-pointed — otherwise see the touchpoint note below.
4. **Re-scale risk geometry to the horizon** (`stop_atr`/`target_atr`). Only
   defensible if driven by measured pre-sealed MAE/MFE distributions for medium-hold
   trades, not by grid search. **Correction to the first draft:** gate 5 perturbs
   `stop_atr ∈ {1.2, 1.5, 1.8}` (promotion.py:187), so *that one axis* is measured —
   but the neighbourhood is **not** "characterised as robust" in any general sense:
   gate 5 covers **2 of 8** `TrendParams` fields and explicitly excludes
   `time_stop_bars`, the parameter this whole section is about (§0.5). The claim that
   the pre-sealed neighbourhood is robust has been withdrawn.
5. **Volume-filter horizon-appropriateness** (H4). Cheap to test, low expected impact.

**Implementation touchpoints for v0.2.0:**
`src/signalforge/research/strategies/trend_continuation.py` (`VERSION`, `TrendParams`
:21-29, horizon branch :32-40, `evaluate` :85-133, `spec()` :42-83 which is generated
from params and needs no manual sync);
`src/signalforge/research/strategies/__init__.py:43-51` (register the v0.2.0 instance);
`src/signalforge/research/promotion.py:178-187` (grid keyed on the
`trend_continuation` prefix);
tests under `tests/` covering leakage (`backtest/leakage.py:assert_no_lookahead`).

**Corrected gate-5 failure mode at this touchpoint.** The first draft said gate 5
"raises or mis-perturbs" if a grid field name disappears. FACT: `promotion.py:50`
imports `from dataclasses import replace as _replace`, and `_replace(base, **p)` on an
unknown field raises `TypeError` — verified: `TypeError: P.__init__() got an
unexpected keyword argument 'b'`. There is no mis-perturb branch; a renamed field is a
loud crash, which is the safe outcome. **The real hazard is the inverse, and it is
silent:** if a v0.2.0 **keeps** a field name but stops using it (e.g. retains
`time_stop_bars` while switching to a trailing exit), `_replace` succeeds, all 9 grid
points return **identical** results, `positive_fraction` and
`neighbour_positive_fraction` both come back 1.0, and **gate 5 passes at 100% having
tested nothing** — the `len(evaluable) >= 4 and len(positive) <= 1` guard
(sensitivity.py:199) does not catch it. §4.2 item 6 now requires a pre-integration
check that each grid axis measurably changes the OOS trade count or expectancy.

---

### 2.2 `mean_reversion.short_swing` v0.1.0 (version 4) — broad, structural failure

**Gate-by-gate (evaluation id 34, snapshot 3), with trade sets tagged:**

| Gate | Trade set | Achieved | Threshold | Shortfall |
|---|---|---|---|---|
| 1 walkforward | all pre-sealed (984) | 2 of 4 folds cleared | ≥ 2 of 4 | pass (bare) |
| 2 OOS trades | **OOS (309)** | 309 | ≥ 30 | pass |
| **3 net expectancy** | **OOS (309)** | **−0.0837R** | > 0 | **0.0837** |
| **4 bootstrap CI** | **OOS (309)** | **[−0.1739, +0.0061]**, low = −0.1739 | low > +0.02 | **no n fixes this** — point estimate is negative (§0.3) |
| **5 sensitivity** | OOS per grid point | **0/9 positive (0%)**, 0% neighbours; worst −0.1908R — on `z_entry` × `stop_atr` (**2 of 6** fields, §0.5) | ≥ 60% / ≥ 75% | **60pp / 75pp** |
| 6 regime | all pre-sealed (984) | bull 618 / bear 46 / range 260; **60 unbucketed (6.1%)** | ≥ 10 each | pass |
| **7 benchmark** | all pre-sealed (984) | Sharpe **−0.749** vs SPY +0.719 | > SPY | **1.468 Sharpe** |
| 8 data/leakage | — | pass (snapshot 3 only) | — | — |
| 9 sealed | sealed year | +0.1278R / 84 (snap 3); +0.1230R / 91 (snaps 1/2/4) | ≥ 0 | **passes on all four** |
| 10 probation | — | pass | — | — |

Full-span portfolio figures from gate 7 (**all 984 pre-sealed trades, IS+OOS**): CAGR
−3.48%, ann vol 4.59%, maxDD 37.93%, PF 0.831, 10,000 → 7,299.62 vs SPY CAGR +13.36%,
Sharpe +0.719.

Walk-forward folds (gate 1 evidence, **all pre-sealed trades**): F1 2016-09→2018-12
n=257 **+0.0175R**; F2 2018-12→2021-03 n=292 **−0.1949R** (Dec-2018 selloff + COVID
crash); F3 2021-03→2023-06 n=181 **+0.0436R** (2022 bear); F4 2023-06→2025-09 n=254
**−0.0651R**.

**Diagnosis.**
FACT: the entry is a single line — `z ≤ −2.0` **and** `close < SMA(20)` **and**
`regime.trend is not Trend.BEAR` (mean_reversion.py:88), long-only, params
`z_lookback=20, z_entry=−2.0, sma_window=20, atr_window=14, stop_atr=2.0,
time_stop_bars=6` (:22-27).
FACT: `RegimeState` already computes `vol: Vol.HIGH/LOW` and exposes
`risk_off = trend is BEAR or vol is HIGH` (regime.py:26-28, 41-42) — **the strategy
consults neither**. It reads `trend` only.
FACT: exits are `stop = close − 2.0×ATR(14)`, `target = SMA(20) frozen at entry`,
`time_stop_bars = 6` (:91-93). A dip-buy entered *below* a 20-day SMA has a target
that is typically well under 1×ATR away while the stop is 2×ATR away: the design
takes small wins and full-size losses, and the 6-bar leash truncates the slow
reversions that would justify it. DERIVED (§0.4): modelled cost is **0.028R/trade** —
the lowest in the program in R terms (widest stop), so cost is *not* the problem here.
FACT: gate 5's verdict is the decisive one — **0 of 9** grid points positive across
`z_entry ∈ {−2.5, −2.0, −1.5} × stop_atr ∈ {1.5, 2.0, 2.5}` (promotion.py:197),
worst −0.1908R, and loosening `z_entry` to −1.5 raises trade count to 606–634 while
expectancy stays −0.05 to −0.08R. There is no profitable plateau anywhere in the
tested region. Caveat from §0.5: that region is **2 of 6** parameters — `time_stop_bars`,
`sma_window`, `z_lookback` and `atr_window` are untested, and H8/H9 point at exactly
those. 0/9 is strong evidence against the tested slice, not proof the whole design is
dead.
FACT: gate 6 passes comfortably across all three regime buckets, so the loss is
**not** a mislabelled-regime artefact — it is broad.
FACT, **and a disposition argument under R1 (sealed numbers used deliberately, marked
as such)**: gate 9 passes on all four snapshots (+0.1230R to +0.1278R, PF 1.45–1.47)
on a calm, persistently bullish 12 months. This is the clearest illustration in the
whole program of why the ladder is ordered the way it is: the sealed year is exactly
the regime this dip-buy is built for, and the nine-year pre-sealed record says that
regime is the exception. *No parameter or filter recommendation below is derived from
these sealed numbers.*

- **H6 (volatility blindness, primary).** Entries fire on high-realised-vol
  "falling knife" days that a slow SMA50/SMA200 trend label (regime.py:62-77, which
  needs a crossover *plus* a 10-bar SMA200 slope) still calls non-BEAR. F2's
  −0.1949R spans precisely the two fastest vol shocks in the sample.
  *Falsified if*: pre-sealed expectancy split by `RegimeState.vol` (HIGH vs LOW at
  entry) is statistically indistinguishable **in SE units at the fold trade counts**
  (n≈250–290 per fold, so the detectable difference at sd≈0.81 is ~0.10R at 2 SE), or
  if excluding HIGH-vol entries leaves F2 still deeply negative.
- **H7 (systemic vs idiosyncratic dips).** A −2σ single-name day during a
  market-wide selloff is adverse selection; the same day in isolation is noise.
  The strategy has no breadth or cross-sectional term anywhere in the file.
  *Falsified if*: conditioning entries on the fraction of the universe
  simultaneously at z ≤ −2 shows no expectancy gradient on pre-sealed data. **Note
  §3(a):** with 15 of 24 snapshot-3 symbols being ETFs, several of which contain the
  other 9, a "breadth" term computed on this universe is near-degenerate; H7 is
  really a hypothesis about the *expanded* universe.
- **H8 (unfavourable exit geometry).** 2×ATR stop vs a sub-ATR frozen SMA target
  plus a 6-bar leash caps winners and leaves losers full-sized. Supporting FACT
  from the committed report: IS avg win +0.45R vs avg loss −0.80R
  (`reports/mean_reversion.short_swing-0.1.0.md:17-18`). Gate 5 does **not** perturb
  `time_stop_bars` (§0.5), so this region is genuinely unmeasured.
  *Falsified if*: pre-sealed MFE distribution shows most trades reach the frozen
  target comfortably within 6 bars.
- **H9 (fixed z-threshold, non-stationary vol).** A plain 20-day return z-score
  (`zscore_last_return`, features/daily.py) fires far more often in high-vol
  periods, precisely when mean reversion is least reliable — the trigger is
  pro-cyclical with the wrong cycle. *Falsified if*: entry rate per symbol-day is
  roughly stationary across the four folds.

**Candidate levers, ranked:**

1. **Volatility-regime exclusion** (skip entries when `ctx.regime.vol is Vol.HIGH`,
   or equivalently require `not risk_off`). Highest expected gate impact per unit of
   design freedom: it uses an *already-computed, already-audited* field, costs one
   condition, and is motivated by fold timing rather than by fitting. Cost: trade
   count falls (309 OOS today; the pre-sealed floor is 30 and gate 5 needs ≥ 15 per
   grid cell — with 984 full-span trades there is real headroom, but bear-bucket
   coverage at 46 trades is the constraint to watch, and 60 pre-sealed trades are
   currently unbucketed, §0.6).
2. **Vol-normalised entry threshold** (H9): z computed on vol-standardised returns,
   or a threshold that scales with realised vol. Addresses the same mechanism as (1)
   from the trigger side rather than the filter side; the two overlap, so testing both
   plus their combination is three variants — count them (R5).
3. **Exit-geometry redesign** (H8): target that tracks the SMA rather than freezing
   it at entry, and/or a leash proportional to the measured pre-sealed
   time-to-reversion rather than a flat 6 bars. Distinct mechanism, worth an
   independent proposal — **and it is the lever pointing at the untested 4 of 6
   parameters (§0.5)**, so it must ship with `time_stop_bars` (or its successor) added
   as a gate-5 axis.
4. **Cross-sectional breadth filter** (H7). Highest ceiling, highest implementation
   cost: nothing in `StrategyContext` (base.py:15-19) carries universe-wide state
   today, so this needs new plumbing that must itself be leakage-audited (the
   breadth value must be computed from data ≤ t only). Effectively requires W1.
5. **Honest documented fail.** Given 0/9 sensitivity positivity and a −0.749
   full-span Sharpe, the base rate for rescuing this strategy is low. If two or
   three mechanism-motivated variants do not move gate 5 above 60%, the correct
   outcome is a documented "does not pass", not a fourth, fifth and sixth variant.
   Note the asymmetry: this strategy is the one most likely to produce a spurious
   pass under repeated trying, because its sealed year already passes on all four
   snapshots — a v0.2.0 that fixes gates 3/4/5/7 inherits a gate 9 that is already
   friendly, so gate 9 provides *no* independent check here.

**Implementation touchpoints:** `src/signalforge/research/strategies/mean_reversion.py`
(`VERSION`, `MeanReversionParams` :20-27, `evaluate` :80-95);
`src/signalforge/research/regime.py` (read-only consumer of `Vol`/`risk_off`; do not
change the labeller);
`src/signalforge/research/strategies/base.py:15-19` **only if** a breadth term is
added to `StrategyContext` (a shared-surface change affecting every strategy —
treat as a separate, reviewed change with its own leakage audit);
`src/signalforge/research/strategies/__init__.py:43-51`;
`src/signalforge/research/promotion.py:189-197` (grid; see the silent-dead-parameter
hazard in §2.1).

---

### 2.3 `volatility_breakout.short_swing` v0.1.0 (version 6) — starved of data **and** short on point estimate

**Gate-by-gate (evaluation id 36, snapshot 3), with trade sets and required-n:**

| Gate | Trade set | Achieved | Threshold | Required to clear |
|---|---|---|---|---|
| 1 walkforward | all pre-sealed (211) | folds +0.4745/36, +0.1111/98, +0.0389/34, +0.1286/43 | ≥ 2 of 4 with n≥15 & exp>0 | pass |
| 2 OOS trades | **OOS (51)** | 51 | ≥ 30 | pass (thin) |
| 3 net expectancy | **OOS (51)** | +0.0613R | > 0 | pass — smallest positive margin of any version; **0.042R of modelled cost sits inside it (§0.4)** |
| **4 bootstrap CI** | **OOS (51)** | **low −0.3553R** | > +0.02 | **n ≥ 5,428 at this point estimate (106× today)**, *or* a point estimate ≥ +0.1906R at n≈319 (3.1×) |
| 5 sensitivity | OOS per grid point | pass; positive 0.667, neighbour fraction **exactly 0.750** | ≥ 0.60 / ≥ 0.75 | **zero margin — and it already fails on snapshot 4** (see below) |
| **6 regime** | all pre-sealed (211) | bull 167 / **bear 0** / range 30; **14 unbucketed (6.6%)** | ≥ 10 each | **10 bear trades** |
| **7 benchmark** | all pre-sealed (211) | Sharpe **0.666** vs SPY 0.719 | > SPY | **0.053 Sharpe** |
| 8 data/leakage | — | pass (snapshot 3 only) | — | — |
| **9 sealed** | sealed year | **−0.0979R on exactly 10 trades** (identical on all 4 snapshots) | ≥ 0R, ≥ 10 trades | **SE = 0.49R — see below** |
| 10 probation | — | pass | — | — |

**Diagnosis.**
FACT: entry requires two conditions on the *same* bar — `ATR(10)/ATR(50) ≤ 0.75`
(`contraction_max`, breakout.py:27) **and** a close through the 20-day Donchian
channel computed excluding today (`channel=20`, breakout.py:26; features/daily.py:92-99).
Params: `channel=20, contraction_max=0.75, atr_window=14, stop_atr=1.75,
target_atr=3.5, time_stop_short=10, time_stop_medium=40` (breakout.py:25-32).
FACT (structural, the core finding): those two conditions are **partially
anti-correlated states**. A genuine range breakout usually coincides with ATR
*expanding*; the filter demands recent ATR well *below* its 50-day baseline. The
strategy selects the intersection of two states that tend not to co-occur — scarcity
is by construction, not by accident.
FACT: the committed 2-year report (`reports/volatility_breakout.short_swing-0.1.0.md`)
shows 40 trades over 12,500 bars across 25 symbols (~1.6 trades/symbol over ~2 years,
≈0.3% of symbol-days), and highly uneven: SPY alone 8 of 40; AAPL, HD, XLF, XLP, XLU
zero. (That report's header lists **25** symbols while snapshot 3 is
`universe_24_ex_meta` — different universes, so the two documents are not directly
comparable; a documentation discrepancy, not a defect.)

**Corrected power statement.** The first draft said three of the four failing gates
(4, 6, 9) are power failures and gate 9's sign is "an edge-quality failure on top".
DERIVED (§0.3): **gate 9 is a *fourth* power failure.** At n=10 the sealed SE is
**0.49R**; −0.0979R is **0.20 SE** from zero, and gate 9 would reject a genuinely
+0.30R strategy 27% of the time and a genuinely +0.0613R strategy 45% of the time. It
carries no information about this strategy's sign. Gate 7 (0.053 Sharpe short of SPY)
is the only genuine edge-quality failure among the four.

**Corrected gate-5 statement — v6's sensitivity pass is already known to be
snapshot-fragile.** FACT: on snapshot 3 gate 5 passes at `positive_fraction = 0.667`,
`neighbour_positive_fraction = 0.750` — *exactly* the threshold (`sensitivity.py:194`
tests `nb_frac < min`, so 0.750 passes). FACT: on **snapshot 4** (eval 42) the same
v0.1.0 returns `0.556 / 0.500` and gate 5 **FAILS**: *"only 56% of evaluated points
have positive OOS expectancy (need 60%); only 50% of one-step neighbours of the
baseline stay positive (need 75%)"*. Adding one symbol flips gate 5. Any change that
reduces trade count risks pushing grid cells under the 15-trade floor and flipping it
again.

- **H10 (power — restated, and *narrowed*).** With a fixed signal rate, absolute
  trade count scales ~linearly with universe size. Going from 24 symbols to ~150 over
  the same span is roughly a 6.25× breadth multiplier. **This addresses gates 2, 5 and
  probably 6. It does NOT address gate 4** — see the arithmetic in §3(a) and the
  §0.3 hurdle table: at n≈319 the gate-4 hurdle is +0.1906R against an observed
  +0.0613R, so expansion alone leaves gate 4 failing. And it does not address gate 7.
  *Falsified (for gate 6) if*: on the expanded snapshot the bear bucket remains under
  10 trades — a strategy finding, not a data finding.
- **H11 (edge sign / magnitude is genuinely insufficient) — now the leading
  hypothesis.** Gate 4 is a *point-estimate* problem, not a sample-size problem: the
  observed +0.0613R would need to roughly **triple** (to +0.19R at n≈319) or the
  sample to grow **106×** (to n≈5,428). *Disposition note under R1 (marked): the
  sealed 10 trades at −0.0979R carry no evidential weight either way (0.20 SE) and
  must not be cited as support for H11.* *Falsified if*: expanded-universe pre-sealed
  OOS expectancy is positive with a CI low above +0.02R — which is exactly gate 4's job.
- **H12 (regime homogeneity was the window, not the strategy).** The 2-year report
  window (2024-08→2026-09) plausibly contained no bear-labelled proxy days at all, so
  zero bear trades may say nothing about the strategy. Note the promotion run's bear
  bucket is also 0 across a full ~9y pre-sealed span, so H12 explains the *report*,
  not the *gate*. *Falsified/confirmed by*: counting `label_regimes` bear days on the
  proxy over both windows — a cheap read-only check, and it must also report the
  **14 unbucketed** trades (§0.6), some of which may be genuine bear-regime entries
  inside the 200-session `label_regimes` warmup.

**Candidate levers, ranked:**

1. **Universe expansion first, strategy changes second — but with corrected
   expectations.** It is the only lever that addresses gates 2, 5 and 6 without
   touching the rule set, and under R5 it costs *zero* strategy variants. **It will
   not fix gate 4 or gate 7.** Do it anyway, because reasoning about the rule set on
   an n=51 sample with a 0.22R standard error is fitting noise; but write down in
   advance that a powered re-run is expected to leave gate 4 failing, so that "gate 4
   still fails" is not treated as new information. Watch the cost term: v6 pays the
   highest cost in R in the program (§0.4) and an expanded universe raises it.
2. **Diagnose regime availability** (H12) before anything else — a read-only proxy
   regime-day count over the relevant windows, plus the unbucketed-trade count.
3. **Only then**, if the powered sample still fails: revisit the
   contraction/breakout conjunction as a *mechanism* question (e.g. is the squeeze
   best measured at the breakout bar, or in the window *preceding* it — a
   coiled-then-released framing rather than coiled-and-releasing-simultaneously).
   That is a genuine hypothesis about market structure and can be argued on
   pre-sealed data; it is also the only class of change that can move the **point
   estimate**, which §0.3 shows is what gate 4 actually needs. **Not** acceptable:
   loosening `contraction_max` toward 0.85–0.90 purely to manufacture trade count —
   that trades away the strategy's stated premise and, per the strategy's own
   documented failure mode (breakout.py:80, "contraction filter admits low-volume
   drift that fails to follow through"), buys quantity at the direct expense of
   quality. `contraction_max ∈ {0.65, 0.75, 0.85}` is already the gate-5 axis
   (promotion.py:208), so its neighbourhood is measured — and on snapshot 4 that
   neighbourhood already fails.
4. **Shortening the Donchian channel** raises frequency but shortens the base being
   broken, raising false-breakout risk (breakout.py:79). Same trade-off direction as
   (3); low priority. Note `channel` is **not** a gate-5 axis (§0.5), so changing it
   must add it as one.

**Implementation touchpoints:** `src/signalforge/research/strategies/breakout.py`
(`VERSION`, `BreakoutParams` :25-32, `evaluate` :90-123);
`src/signalforge/research/features/daily.py:84-99` (`atr_contraction`, `donchian_*`
— point-in-time by construction; any new feature must preserve the `(series, t)`
slice-to-≤t contract and be added to the leakage self-check list);
`src/signalforge/research/strategies/__init__.py:43-51`;
`src/signalforge/research/promotion.py:199-208`;
plus the §3(a) data work, which is a prerequisite, not a touchpoint.

---

### 2.4 `intraday_orb.intraday` v0.1.0 (version 1) — blocked at three independent layers

**Gate status (evaluation id 31):** a **single** gate entry —
gate 0 `data_availability`, failed, detail *"no intraday bar history is ingested for
this horizon — evaluation not attempted"*. No sealed test row exists (hence 20 sealed
rows, not 24). Latest `BacktestRun` id 37 shows `n_trades=0` for both IS and OOS.

**Three independent blocks (all FACT):**

1. **Code gate.** `promotion.py:512-534`: `if spec.horizon is Horizon.INTRADAY:`
   appends a failing gate 0 and returns immediately. This triggers on the *declared
   horizon*, not on a data query — ingesting intraday bars would **not** make this
   strategy evaluable without editing the promotion path.
   **Corrected under R4 (see §1):** replacing this with a real `OHLCVIntraday`
   availability query would be *permitted in principle* — it keeps failing while no
   data exists and can only be harder to satisfy, which is the same carve-out that
   permits adding a missing sensitivity grid. The first draft said R4 forbade it; that
   was inconsistent with R4's own carve-out. It nevertheless buys nothing on its own,
   because blocks 2 and 3 are untouched, and it is an operator decision.
2. **Operating policy.** `research/approved_scope_scan.py:19-22, 77-81` excludes
   `Horizon.INTRADAY` from the horizons it will ever scan (`:81`), with the explicit
   comment that this holds *"even if a strategy were ever approved on it (EOD-only
   operation)"* (`:21-22`). `alerts/dispatch.py:241` independently skips INTRADAY
   candidates. So even a hypothetically promoted intraday strategy could never
   generate a live paper candidate under current policy.
3. **No data path.** `MassiveAdapter` declares exactly one capability,
   `FeedType.BAR_DAILY` (massive.py:86-100), and has no `fetch_intraday_bars` method;
   it does not satisfy the `IntradayBarAdapter` protocol (adapters/base.py:138-149).
   The only `BAR_INTRADAY` capability in the codebase is the **test fixture**
   (adapters/fixture/__init__.py:79). `ingest_intraday_symbol` /
   `ingest_intraday_universe` (ingest.py:455-489, 527-542) are fully implemented and
   write to `OHLCVIntraday`, but have no production adapter to call.

**Additional gap:** `_sensitivity_plan` (promotion.py:161-210) has grids for four
key prefixes only — `relative_strength`, `trend_continuation`, `mean_reversion`,
`volatility_breakout`. `intraday_orb` has none, so it would take an automatic,
permanent gate-5 **failure** (not a skip, promotion.py:694-703) even if gate 0 were
somehow satisfied.

**Conclusion (answering the brief's question directly):** yes — the EOD-only
operating policy makes `intraday_orb` **non-operational regardless of data**. Even a
perfect intraday pipeline plus a passing 10-gate run would produce a strategy that
`approved_scope_scan` refuses to scan and `dispatch` refuses to alert on. The "three
independent blocks" framing survives the R4 correction: block 1 becomes removable
in principle, blocks 2 and 3 do not, and removing one of three changes nothing. Any
work here is therefore a **data-and-policy requirements design**, explicitly not a
promotion attempt, and it needs an operator decision on intraday operation before
implementation — exactly as `STRATEGY_COMPLETION_PLAN.md` already states.

**What a future intraday capability would require (design inputs, not commitments):**
- An out-of-band confirmation that the Massive plan entitles an intraday-bars
  endpoint, and at what rate limit. Not documented in this repo; `CAPABILITY_MATRIX.md:26`
  says intraday bars are entitled (DELAYED) but not ingested for research.
- A real `MassiveAdapter.fetch_intraday_bars` implementing `IntradayBarAdapter`,
  with its own pacing and validation.
- Volume estimate (illustrative only, no verified requirement exists): 25 symbols ×
  ~500 sessions × 78 five-minute bars ≈ **975,000 bars**. The strategy's own
  `evaluate()` bound (`session_bar_count + time_stop_bars > 26 + or_bars`, with
  `or_bars=3`, `time_stop_bars=12`) implies a session of roughly 26–41 bars, i.e.
  ~10–15-minute bars over a 6.5h session, which would be ~6× smaller.
- A `_sensitivity_plan` grid for the `intraday_orb` prefix (permitted under R4 as
  making a gate runnable).
- A policy decision on how an intraday strategy would be scanned and alerted
  without weakening the EOD-only guarantees that `approved_scope_scan` currently
  enforces structurally.

**Touchpoints if ever authorised:** `data/adapters/massive.py`,
`data/adapters/base.py:138-149`, `data/ingest.py:455-542`,
`research/strategies/intraday_orb.py`, `research/features/intraday.py`,
`research/promotion.py:161-210` and `:512-534`, `research/approved_scope_scan.py`,
`alerts/dispatch.py:241`. Note that the last three are **policy surfaces**, not
research surfaces, and are out of scope for this program.

---

## 3. Cross-cutting

### (a) Research-universe expansion with 10-year history

**Current state (FACT, read-only queries):**

| Source | Instruments | Bars | Span |
|---|---|---|---|
| `massive` (research path) | 26 | 61,928 | 2016-09-12 → 2026-09-09 (~2,382 bars/symbol, ~9.4y) |
| `massive_grouped` (bulk screening) | 2,655 | 971,699 | 2025-01-03 → 2026-09-08 (~20 months) |
| `continuity_bridge:1` | 1 | 2,510 | 2016-09-12 → 2026-09-04 (META_CONT) |

Total instruments in DB: 2,658. Latest `UniverseScreenRun` id 3 (2026-09-09 18:52:52)
has **1,599 CS members with empty exclusion reasons** out of 10,746 — comfortably
more than 300 candidates to rank by `UniverseMember.avg_dollar_volume`.

**The `data_snapshot` table as it actually stands (FACT, queried — the first draft
mentioned only rows 1–4 of 10):**

| id | key | reusable | symbols | created |
|---|---|---|---|---|
| 1 | `universe_25_baseline_legacy` | **0** | 25 | 2026-09-08 09:11 |
| 2 | `universe_25_baseline` | 1 | 25 | 2026-09-08 09:24 |
| 3 | `universe_24_ex_meta` | 1 | 24 | 2026-09-08 09:26 |
| 4 | `universe_25_meta_continuity_corrected` (continuity_mapping_id=1) | 1 | 25 | 2026-09-08 09:27 |
| 5 | `liquid_us_2026-09-08` | **0** | 2,551 | 2026-09-09 08:51 |
| 6 | `universe_auto_2551sym_34051c18e4` | **1** | 2,551 | 2026-09-09 08:51 |
| 7 | `liquid_us_2026-09-08_300d727a` | **0** | 2,312 | 2026-09-09 09:01 |
| 8 | `universe_auto_2312sym_300d727a6e` | **1** | 2,312 | 2026-09-09 09:06 |
| 9 | `liquid_us_2026-09-08_ea6db586` | **0** | 2,181 | 2026-09-09 18:53 |
| 10 | `universe_auto_2181sym_ea6db58608` | **1** | 2,181 | 2026-09-09 18:53 |

**Restated key-collision argument (the first draft's version was right about the
named keys and silent about the rest).** FACT (`promotion.py:280-348`):

- A **keyed** call whose stored `symbols_json` or `continuity_mapping_id` no longer
  matches raises `ValueError` (:310-329) rather than mutating. So
  `universe_25_baseline` / `universe_24_ex_meta` /
  `universe_25_meta_continuity_corrected` **cannot be widened or shadowed** by a keyed
  call. That part stands.
- An **unkeyed** call matches *any* snapshot with `reusable_by_new_evaluations = True`
  on an exact symbol-set match (:331-337), and otherwise **mints a new row** named
  `universe_auto_{n}sym_{fingerprint}` (:339).
- FACT (the route the first draft missed): **`research/scan.py:165` calls
  `get_or_create_dataset_snapshot(session, symbols=universe)` unkeyed on every live
  scan.** That is where rows 6, 8 and 10 came from — the *operating* scan path mints
  reusable snapshots automatically. `universe/screen.py:257-268` mints the
  `liquid_us_*` rows and immediately sets `reusable_by_new_evaluations = False`
  (`screen.py:268`), so those are safe; the `universe_auto_*` rows are not.

**Therefore, before creating `universe_150_liquid_massive_10y`:**
1. Confirm no existing reusable snapshot (6, 8, 10, or any future scan-minted row) has
   the identical symbol set — otherwise an unkeyed evaluation would silently attach to
   it instead.
2. **Always pass the key explicitly.** An unkeyed evaluation on the new 150-symbol set
   would mint `universe_auto_150sym_<fp>` as a *separate* row, splitting the audit
   trail across two ids for the same universe.
3. Verify the chosen key cannot be produced by either generator — `universe_auto_*`
   (promotion.py:339) and `liquid_us_<date>_<digest>` (screen.py:259) — so the
   universe pipeline can neither produce nor shadow it. `universe_150_liquid_massive_10y`
   satisfies this; keep the check as a rule, not a one-off.

**Feasibility: high, and it requires no new code.** FACT: three existing primitives
compose to do the whole job.
1. *Select*: `universe/screen.py` `eligible_symbols_for(session, run.id)` sorted by
   `avg_dollar_volume` desc (the pattern `cap_enrichment_candidates` already uses).
2. *Ingest*: `signalforge data ingest-history --symbols … --since YYYY-MM-DD`
   (cli.py:92-141) → `ingest.ingest_daily_history` → `MassiveAdapter` → rows written
   with `source = adapter.provider_name = "massive"`. This is exactly how the current
   26-symbol set was built. Every symbol must end up genuinely `massive`-sourced —
   snapshot 4 fails gate 8 solely because `META_CONT` is not (§0.1).
3. *Register*: `get_or_create_dataset_snapshot` (promotion.py:280-348) with a **new,
   distinct key**, passed explicitly (above).

**API cost and wall-clock (analytical estimate; no API call was made).**
FACT: `MassiveAdapter.fetch_daily_bars` (massive.py:170-210) issues **one** GET per
symbol for the whole `[start, end]` range with `limit=50000`; ~10y of daily bars is
~2,520 rows, ≈5% of the cap, so no pagination is expected (a `next_url` response is
treated as an error, `AdapterError`). Pacing is `_MIN_REQUEST_SPACING_S = 12.1s`
(≈5 req/min, Massive Basic, settings.py:51-53), enforced inside `_request`, and
`ingest_symbol` commits after each symbol so the SQLite write lock is never held
across the paced network wait (ingest.py:270-276).

| New symbols | Requests | Wall clock at 12.1s spacing |
|---|---|---|
| 100 | ~100 | ~20.2 min |
| 200 | ~200 | ~40.3 min |
| 300 | ~300 | ~60.5 min |

Confirm the *runtime* value of `settings.market_data_min_request_spacing_s` before
scheduling — only the class default was read.

**Statistical-power gain — corrected, and much narrower than the first draft claimed.**

For a fixed per-symbol signal rate, trade count scales with (symbols × years). Going
24 → ~150 symbols on the same ~9.4y span is ≈**6.25×**. Applied to
`volatility_breakout`'s 51 OOS trades that projects to **n ≈ 319**.

DERIVED, using v6's implied per-trade sd of 1.554 (§0.3):

| Gate | Effect of 6.25× breadth | Verdict |
|---|---|---|
| 2 (n ≥ 30) | 51 → ~319 | **fixed** (already passing; comfortable) |
| 5 (≥ 15 per grid cell) | thin cells (some at n=19 today) become comfortable | **materially helped** — and needed, since gate 5 already fails on snapshot 4 |
| 6 (bear ≥ 10) | 0 → 0 × 6.25 is still 0 *if the strategy structurally never fires in bear regimes*; if the rate is merely low, ~6× more chances | **plausibly fixed, must be measured (H12)** |
| **4 (CI low > +0.02)** | CI half-width shrinks √6.25 = 2.5×, from ±0.4266 to **±0.1706**. New CI at the observed point estimate: **[−0.109, +0.232]** → **still FAIL** | **NOT fixed** |
| 7 (Sharpe > SPY) | breadth does not move a risk-adjusted point estimate | **not addressed** |

**Gate 4 for v6 is a point-estimate problem, not a sample-size problem.** The
condition `exp − 1.96·sd/√n > 0.02` requires, at the observed +0.0613R,
`n > (1.96 × 1.554 / (0.0613 − 0.02))² = **5,428** OOS trades` — **106× the current
51**, or ~17× what a 150-name universe delivers. Equivalently, at n ≈ 319 the point
estimate would have to reach **+0.1906R**, i.e. **3.1×** the observed value.
Expansion is therefore justified on gates **2, 5 and 6** — it is still the single
highest-leverage cross-cutting action, and it costs zero variants under R5 — but H10
must **not** be written as "expansion addresses gates 4, 6 and 9 simultaneously". It
addresses gate 6, helps gate 5, and leaves gates 4 and 7 exactly where they are.

**The √n argument is an upper bound: the bootstrap assumes iid trades and this
universe badly violates it.** FACT: `montecarlo.py:30-33` resamples the per-trade R
vector **iid with replacement** (`rng.integers(0, arr.size, size=(n_resamples,
arr.size))`, then `arr[idx]`). FACT: snapshot 3's 24 symbols are **15 ETFs and 9
single names** — `DIA, IWM, QQQ, SPY, XLB, XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU,
XLV, XLY` vs `AAPL, AMZN, GOOGL, HD, JPM, MSFT, NVDA, UNH, XOM`. SPY/QQQ/DIA/IWM/XLK
plus several of their own constituents all enter the same trend regime on the same
days. The effective sample size is materially below nominal n, so **every CI in this
document is too narrow**, every SE in §0.3 is too small, and adding 126 correlated
equities inflates nominal n far faster than it adds independent information. The
√6.25 = 2.5× shrinkage is an **upper bound** on the real gain; the required-n figures
(129 / 142 / 108 / 5,428) are **lower bounds**.
*Recommended (a diagnostic, not a gate change — permitted under R4):* report a
date-clustered or block bootstrap alongside the gate-4 iid CI on any expanded
snapshot, and report the ratio of the two half-widths as the effective-sample-size
haircut.

**Expansion is a distribution shift, not a more-powered version of the same
experiment.** 62.5% of snapshot 3 is ETFs. A 150-name liquid single-stock universe
changes gap behaviour, idiosyncratic volatility, spread, earnings-event exposure and
cross-sectional dispersion. Results on the new snapshot are **not comparable** to
snapshot 3 and must never be described as "the same strategy with more data".
Consequences to bake in:
- Report any expanded-snapshot run as a **separate experiment** with its own look
  count under R2 (it creates a fresh sealed test per version — see below), not as an
  update to the snapshot-3 numbers.
- **Pre-register the ETF / single-name composition rule** alongside the ADV rank rule.
  "Top 150 by ADV" on a 1,599-name CS screen is an all-single-name universe, which is
  a *different* distribution shift from "keep the 15 sector ETFs and add 126 names".
  Pick one and write it down first.
- **The cost model does not adapt.** Per §0.4, `backtest_runner.py:205-206` passes no
  `spread_bps`, so all 150 names are charged the same flat 5 bps (11 bps round trip)
  regardless of liquidity. Any expanded-snapshot result must be reported alongside a
  sensitivity at **2× and 5× the modelled spread** (26 bps and 66 bps round trip,
  i.e. trend-family cost 0.087R and 0.220R per trade against 0.037R today). For v6,
  whose whole edge is +0.0613R and whose current cost is already 0.042R, the 2× case
  alone removes the point estimate.

**Constraints to respect.**
- The new snapshot is an *additional* snapshot referenced explicitly by key in
  research runs; it is **not** a change to `cfg.research.universe` or to any live
  approved scope (that would be an operating change, out of scope).
- `UniverseFilters.max_universe_size = 150` (research.py:139) gates only
  `research/universe.py:screen_universe`'s display, not ingestion, snapshot size or
  promotion — but it is a sensible ceiling to adopt anyway.
- `avg_dollar_volume` in the screen is computed from ~20 months of `massive_grouped`
  bars. Using it to *rank which symbols to backfill* is exactly its purpose; it is
  **not** evidence of those symbols' 10-year `massive` history, which does not exist
  until the backfill runs.
- Selection must be defined **before** any backtest is run on the result (top-N by
  ADV with the existing liquidity/type screens, plus the composition rule), and the
  rule written down — a universe chosen after seeing which symbols help is the same
  offence as tuning on the sealed window.
- FACT: `StrategySealedTest` is unique per `(strategy_version_id, dataset_snapshot_id)`
  (`db/models/research.py:263`), so evaluating even an **unchanged** v0.1.0 against the
  new snapshot creates a **fresh sealed test** — a genuine additional look at the same
  calendar year through a different universe. Given the count is already **k=5**
  (§0.1), a new snapshot takes every version to **k=6**. This is a real
  multiple-testing cost and the main argument for building the snapshot **once**, with
  a pre-registered symbol rule.
- **Per-symbol IS/OOS misalignment worsens.** `_TRAIN_FRAC = 0.6` splits at 60% of
  *each symbol's own* bar count (`backtest_runner.py:29, 158-160`). 150 symbols with
  heterogeneous history lengths means the aggregated OOS mixes different calendar
  sub-periods per symbol far more than 24 near-identical-history symbols do.
- The backfill itself is 100–300 live paced calls to the Massive API — excluded by
  this phase's hard rules, and it must be run deliberately with the operator's
  knowledge, not as a side effect of a research script.

### (b) Intraday data requirements and the EOD-only policy

Covered in §2.4. Summary answer: **yes, the EOD-only operating policy makes
`intraday_orb` non-operational regardless of intraday data**, because
`approved_scope_scan.py:19-22, 81` and `alerts/dispatch.py:241` exclude the
horizon at the *operating* layer, independently of the `promotion.py:512` gate-0
block and independently of whether `OHLCVIntraday` is populated. Ingesting intraday
bars would remove one of three blocks; converting gate 0 to a real data query (now
recognised as R4-permissible, §1) would remove another, and the operating-policy
block would still stand alone. The program's correct output here is a documented
data-and-policy requirements design plus an explicit operator question; not a
promotion attempt, and not an edit to the scan or alert policy surfaces.

### (c) How live paper evidence will be used to confirm

**What the loop is (FACT).** `alerts/dispatch.plan_alerts` (dispatch.py:181-317)
surfaces candidates → manual accept or `paper/auto_simulate.auto_simulate_scan_runs`
(auto_simulate.py:126-217) → `paper/ledger.accept_candidate` (ledger.py:129-249)
writes `PaperOrder`/`PaperFill`/`PaperPosition`/`PaperTrade` with an immutable
evidence snapshot (`_candidate_snapshot`, ledger.py:369-458, invariant S9) →
`research/health_monitor.evaluate_strategy_health` (health_monitor.py:132-241) reads
**closed** `PaperPosition` rows → may flip `Strategy.status` →
`research/paper_probation.paper_probation_context` reports, and never writes
(docstring lines 1-8).

Acceptance is guarded by `assert_auto_simulate_allowed` (ledger.py:473-512), which
checks in order: the setting is on, `quality_gate_status == PASSED`, instrument type
in (`stock`, `etf`), version status `PAPER_APPROVED`, and `scan_scope_matches`.
FACT: `scan_scope_matches` (approval_scope.py:69-94) compares **four** fields —
`dataset_snapshot_id`, `config_hash`, `spec_json_hash`, `sources` (:89-92). The
`ApprovedScope` dataclass carries a fifth, `universe` (approval_scope.py:35-42, field
at :41), which is **not** compared. Flagged as an observed behaviour, not a proposal.

**What live paper can prove.** That a scope-matched, cost-modelled, rule-followed
signal stream produces R-multiples whose sample mean can be compared against *the
same version's own* OOS backtest expectancy, with `z = (paper_exp − bt_exp)/stderr(paper)`
(health_monitor.py:220-222). It can detect a material, sample-supported divergence
between live behaviour and the backtest a strategy was promoted on. Downgrade requires
**both** `paper_exp < 0` **and** `z ≤ −2.0` (disable at `z ≤ −3.5`,
health_monitor.py:100-113, config/research.py:239-240); `min_paper_trades = 20`
(config/research.py:235) before any assessment is produced at all.

**What live paper cannot prove (inferred from the code).**
- *Not* statistical significance against backtest uncertainty: the z-score uses only
  the paper sample's own standard error, treating `bt_exp` as a known constant. That
  is worst for **v5**, whose sealed test has 16 trades at SE ≈ 0.371R and whose OOS
  has SE ≈ 0.106R (§0.3) — both sides of the comparison are noisy, and z is
  overconfident in both directions.
- *Not* real fills: fills are simulated from a fixed nominal spread + slippage model
  (ledger.py:161-166) — the same universe-independent 5 bps assumption as the
  backtest (§0.4). No liquidity or market-impact information is generated.
- *Not* regime generalisation: `min_paper_trades` is a count floor, not a
  calendar-time or regime-diversity requirement. A fast run of 20 trades in one
  narrow regime clears it. DERIVED: at trend-family sd ≈ 1.4–1.7, 20 trades give
  SE ≈ 0.31–0.38R — enough to detect only a ≈0.7R divergence at 2 SE.
- *Nothing outside the approved scope*: drift outside the matched
  dataset/config/spec/source is invisible here by design.
- FACT: **no code path re-promotes** from live evidence. Re-approval requires the
  promotion pipeline to be re-run and pass again.

**How this program will therefore use it.** For each v0.2.0 that passes the ladder:
(i) record the promoted version's OOS expectancy **and its SE** as the pre-registered
prediction; (ii) let probation accumulate to at least `min_paper_trades = 20` closed
positions with valid `stop_level` (FACT: `_paper_returns_r`, health_monitor.py:55-73,
silently skips positions with a missing stop or non-positive risk — so a missing stop
*undercounts* n); (iii) report realised paper expectancy, the sequential equity curve,
and `shortfall_vs_expected_r` (paper_probation.py:165) alongside the backtest
prediction, stating the paper sample's own uncertainty **and the backtest's**, rather
than only z; (iv) treat a sustained shortfall as evidence the promotion was
optimistic — which, under R5, is exactly the outcome to expect if too many variants
were tried. Live paper is the **out-of-sample check on the research process itself**,
not a promotion input.
Caveat to state in every such report: as of today the loop has produced zero trades,
so none of it has been exercised on real data.

---

## 4. Proposed team plan for the design phase

Structure follows `STRATEGY_COMPLETION_PLAN.md` Phase 2: three independent proposals
per strategy from three distinct angles, scored by two judges, synthesised into one
design per strategy. This section fixes *which* strategies get proposals, *which*
angles apply to each, and *what every proposal must contain*.

### 4.0 Sequencing (do this before any strategy proposal)

Two cross-cutting work items gate the rest and cost zero strategy variants:

- **W1 — Universe expansion decision and build (§3a).** Pre-register the symbol
  selection rule **and the ETF/single-name composition rule**, verify the key against
  both auto-generators and against existing reusable snapshots, get operator sign-off
  for 100–300 paced API calls (~20–60 min), build the new keyed `DataSnapshot`. Write
  down in advance that a powered v6 re-run is **expected to leave gates 4 and 7
  failing** (§3a). `volatility_breakout` proposals should not be written before this
  is decided, because every one of them would be reasoning from an n=51 sample with
  SE = 0.218R.
- **W2 — Read-only diagnostics pack (no writes, no API).** Per failing strategy, on
  the **pre-sealed span only**: P&L by holding-duration bucket and exit-reason mix
  (v3, tests H1/H2); ATR-at-exit / ATR-at-entry distribution (v3, H3); expectancy
  split by `RegimeState.vol` at entry and entry-rate stationarity across folds (v4,
  H6/H9); MFE distribution vs the frozen target (v4, H8); proxy regime-day counts and
  unbucketed-trade counts per window (v6, H12 + §0.6). **Every v3 diagnostic must be
  run on all four snapshots** (R10) — a duration effect visible only on snapshot 3 is
  a META artefact, not a mechanism.

  **How to run W2 (corrected — the first draft's blanket rule was imprecise and would
  cause needless copies).** FACT: `walkforward_window` has **0 rows** and
  `backtest_trade` has **0 rows**, despite `backtest_trade` carrying exactly the
  needed columns (`bars_held, mae, mfe, exit_reason, pnl_r, costs, entry_ts,
  exit_ts`). The promotion pipeline never persists individual trades; only aggregates
  reach `gates_json`. **So every W2 item requires an in-process re-run of
  `run_strategy_over_universe`** — none of it can be read out of the database.
  FACT: `run_strategy_over_universe` (`backtest_runner.py:167`) contains **no**
  `session.add` / `session.flush` / `session.commit` — it is read-only. **Most W2
  items therefore need no scratch database at all**; run them in-process against the
  live DB with plain reads.
  The scratch copy is needed only for the writing entry points — `evaluate-promotion`,
  `backtest-*`, `sensitivity`, `promotion-dataset-comparison` — or if you choose to
  **populate `backtest_trade`** to get a queryable trade table, which is the
  recommended alternative for the heavier v3/v4 diagnostics. In that case copy the DB
  to `$TMPDIR/scratch.sqlite` and point the app at the copy via **`DATABASE_URL`**
  (`config/settings.py:44`, no env prefix, case-insensitive; empty value defaults to
  `data/signalforge.sqlite`), e.g.
  `DATABASE_URL="sqlite+pysqlite:///$TMPDIR/scratch.sqlite"`.
  These diagnostics are what make R1 satisfiable — without them, proposals are
  unfalsifiable preferences.

### 4.1 Which strategies get proposals

| Strategy | Proposals | Angles | Rationale |
|---|---|---|---|
| `trend_continuation.medium_swing` (v3) | 3 | **null option (primary)**; exits & risk; signal quality/regime | **Revised.** The gate-9 miss is snapshot-dependent and worth 3 META trades / +3.86R (§2.1), and the sealed mean is −0.16 SE from zero. The null option is now the *leading* proposal, argued on the merits, and the two change proposals are conditional on a W2 duration diagnostic that survives all four snapshots. The universe/power angle is dropped here — v3 clears gates 2/4/6 with room. |
| `mean_reversion.short_swing` (v4) | 3 | **signal quality/regime** (primary); exits & risk; universe/power (breadth-conditioning) | 0/9 sensitivity positivity means the entry selection is the prime suspect — but note that 0/9 covers **2 of 6** parameters (§0.5), so the exits-and-risk angle must add `time_stop_bars` as a gate-5 axis. The breadth idea lands in the universe/power slot and effectively requires W1 (a 15-ETF universe cannot support a breadth term). |
| `volatility_breakout.short_swing` (v6) | 2, **after W1** | universe/power (which is W1 itself); **signal quality/mechanism** (now co-primary) | **Revised.** Rule changes on an n=51 / SE=0.218R sample are fitting noise, so W1 comes first — but W1 cannot fix gate 4 (§3a), so a mechanism proposal that could move the *point estimate* is required, not optional. If the powered re-run passes on the unchanged v0.1.0 rules, no strategy proposal is needed at all — that is the best possible outcome and must be allowed to happen, though §0.3 says it is unlikely. |
| `intraday_orb.intraday` (v1) | 1, requirements only | data & policy | Non-operational under EOD-only policy regardless of data (§2.4). Output is a requirements design plus an explicit operator question, including whether to convert gate 0 to a real data query (R4-permissible, §1). **No promotion attempt.** |
| `trend_continuation.short_swing` (v2), `relative_strength.medium_swing` (v5) | 0 | — | PAPER_APPROVED and live-scoped. Do not touch. Any v0.2.0 sibling must be verified not to disturb their approved-scope spec hash (R7) or their `scopes[0]` sealed-test selection (R7b). **Standing caveat: v5 was approved on a 16-trade sealed test at 0.79 SE from zero (§0.3)** — the weakest evidence supporting anything live. |

Total: **9 proposals**, of which 2 are conditional on W1, 2 (v3's change proposals)
are conditional on a W2 diagnostic, and 1 is requirements-only.

### 4.2 What every proposal must include

Reject any proposal missing a section. Judges score on: legitimacy (no lookahead, no
sealed contamination), expected gate impact, robustness, and cost.

1. **Mechanism.** One paragraph on *why* this should work in markets — not "the
   backtest improves". Name the hypothesis from §2 it addresses (H1–H12) or state a
   new one in the same form. For v3, note which hypotheses are currently **demoted**
   (H1–H4) and what diagnostic re-motivates the one you are using.
2. **Exact change.** File, symbol, before → after. Which `*Params` fields change,
   which conditions are added or removed. New behaviour ships as `VERSION = "0.2.0"`
   (R3/R7).
3. **Pre-sealed evidence.** The W2 diagnostic or fold/sensitivity result that
   motivates it, with the number **and its standard error** (§0.3 gives the per-trade
   sd per strategy; SE = sd/√n). A difference under 2 SE is not evidence. If no
   diagnostic exists yet, say which must be run first. Nothing from the sealed window
   may motivate a design choice (R1).
4. **Falsification.** The specific pre-sealed observation that would kill the
   proposal, stated *before* it is run, **and stated to hold across all four
   snapshots** (§0.1, R10).
5. **Gate-impact forecast, gate by gate.** Predicted direction and rough magnitude
   for gates 1–8, including **which gates the change puts at risk**, with each
   forecast labelled by its **trade set** (OOS-only for gates 2/3/4; all pre-sealed
   for gates 1/6/7 — §0.2; gate 7 in particular is over *all* pre-sealed trades
   despite its docstring). Mandatory entries:
   - expected effect on trade count (gates 1, 2, 5's 15-per-cell floor, 6's
     10-per-regime floor);
   - **gate 4 stated as a required n**, not a shortfall: `n > (1.96·sd/(exp − 0.02))²`
     using §0.3's per-trade sd;
   - **gate 6's unbucketed count** as well as the three buckets (§0.6) — the forecast
     is not answerable without it;
   - the two zero-margin cases: v6's gate-5 neighbour fraction is exactly 0.750 on
     snapshot 3 **and already fails at 0.500 on snapshot 4**, and v5's bear bucket is
     11 against a floor of 10.
6. **Sensitivity-grid plan — now a hard requirement, not a checkbox.**
   **Every parameter the v0.2.0 introduces or changes must become a pre-registered
   gate-5 grid axis**, chosen before results are seen. Rationale (§0.5): gate 5 covers
   only 2 of 6–8 params per strategy today, and the parameter that defines a variant
   is precisely the one it will otherwise never test — that is the cleanest available
   route to a hidden-fragility pass. Adding an axis is permitted under R4 (it makes
   the gate more searching, never weaker); changing a threshold is not.
   Also required: a **pre-integration check that each grid axis measurably changes the
   OOS trade count or expectancy.** A retained-but-unused field (e.g. keeping
   `time_stop_bars` while switching to a trailing exit) makes all 9 grid points
   identical and gate 5 passes at 100% having tested nothing (§2.1). A *renamed* field
   is safe by comparison — `_replace` raises `TypeError` loudly (promotion.py:50).
7. **Leakage argument.** Every new feature reads `(series, t)` with slices ≤ t and is
   covered by `assert_no_lookahead` (backtest/leakage.py:23-41). Cross-sectional or
   breadth terms need an explicit point-in-time argument and new `StrategyContext`
   plumbing (base.py:15-19) — call that out as a shared-surface change.
8. **Cost-model statement — now quantitative.** Confirm the change is evaluated under
   the unchanged cost model, and state:
   - the **per-trade cost in R** at the proposal's `stop_atr`, using
     `round_trip_bps/10,000 ÷ (stop_atr × ATR/price)` — today's round trip is
     **11.0 bps** (`engine.py:94, 143`) and §0.4 gives the baseline figures
     (0.022R–0.042R);
   - the **turnover delta** and the resulting cost delta in R;
   - for any run on an **expanded snapshot**, the result at **26 and 66 bps round
     trip** (≈4× and ≈12× the modelled 5 bps quoted spread). The flat 5 bps in
     `engine.py:90` is universe-independent and optimistic for anything outside the
     current mega-cap/ETF set (`backtest_runner.py:205-206` never overrides it).
9. **Variant budget.** How many variants this angle intends to try, and the stopping
   rule. Total per strategy across all three angles should be small and stated up
   front; it goes in the final report verbatim (R5).
10. **Sealed-look accounting.** State explicitly that implementing this creates a new
    `StrategyVersion` and therefore a new sealed test on the target snapshot — and
    that **the baseline count is k = 5** (the existing `StrategySealedTest` rows for
    the strategy family, all versions, all snapshots, §0.1; the next sealed
    evaluation is look k+1), so a first v0.2.0 sealing on snapshot 3 is **look 6**,
    and a v0.2.0 evaluated on both snapshot 3 and a new expanded snapshot is looks 6
    **and** 7. Reproduce the §0.1 table. Also state, per R1, **which snapshot the
    report will lead with and why**, pre-registered before the run.
11. **Null option.** What happens if this fails: which documented "does not pass"
    would be written, and what evidence it would carry. A program in which no
    strategy is allowed to fail is a program that will manufacture a pass. For v3 the
    null option is not a fallback — it is proposal #1 (§4.1).

### 4.3 Standing risks for the design phase to carry

- **Sealed-test staleness trap (R3).** The single most likely way to produce an
  invalid pass. Any edit without a `VERSION` bump silently replays the old sealed
  result. Add a pre-integration check that every v0.2.0's
  `StrategySealedTest.strategy_version_id` is a row created by *this* run.
- **No look counter exists, and the true count is already 5.** Disclosure is manual.
  Reconstruct from `strategy_sealed_test` (20 rows, 4 per version — §0.1) and publish
  it in every report. The first draft of this map got the count wrong by 4×, which is
  itself the evidence that a manual count is fragile.
- **Gate 1 is coupled to a *sensitivity* constant.** FACT: gate 1's per-fold trade
  floor is `th.sensitivity_min_grid_trades` (promotion.py:632) — the **same constant**
  as gate 5's per-cell floor (config/research.py:106, value 15). Changing the
  sensitivity floor would silently move gate 1. Neither may be changed under R4, but
  any proposal that argues about grid-cell trade counts must note it is arguing about
  gate 1 as well. Relatedly, gate 1's `len(fold_rows) >= n_folds` conjunct is
  definitional and always true (§0.2) — the live condition is 2 of 4 folds.
- **Gate 5 tests 2 of 6–8 parameters (§0.5).** "9/9 positive" is not general
  robustness. For `trend_continuation` it specifically excludes `time_stop_bars`,
  the parameter that defines `medium_swing`.
- **Gate 5's silent no-op failure mode (§2.1).** A retained-but-unused parameter makes
  all 9 grid points identical and gate 5 passes at 100%. §4.2 item 6 is the mitigation.
- **Gate 6's buckets under-count by 6–11% (§0.6).** Trades entered inside
  `label_regimes`'s 200-session warmup, or on dates with no proxy bar, are counted in
  no bucket. Any gate-6 forecast must state the unbucketed count.
- **Gate 7's docstring contradicts its code (§0.2).** Open item for the operator; all
  gate-7 forecasts use *all pre-sealed trades* until it is resolved.
- **The bootstrap assumes iid trades and this universe violates it (§3a).** 15 of 24
  symbols are ETFs, several containing the others. Every CI here is too narrow and
  every required-n is a lower bound. Report a clustered/block bootstrap alongside as a
  diagnostic.
- **Two regime labellers.** `research/regime.py` (`RegimeState`, used by
  `backtest_runner` and by strategies via `signal_fn_for`) and `backtest/regime.py`
  (`label_regimes`, used by gate 6 and `cli.py`) compute bull/bear/vol *differently*.
  Gate-6 coverage numbers and in-strategy regime filters are therefore **not directly
  comparable**. Any proposal that filters on `RegimeState.vol` (v4's top lever) must
  not assume its effect on gate 6's buckets — it must be measured.
- **Per-symbol IS/OOS boundary.** `run_strategy_over_universe` splits at 60% of *each
  symbol's own* bar count (`_TRAIN_FRAC = 0.6`, backtest_runner.py:29, 158-160), not a
  shared calendar date. With an expanded universe of symbols with heterogeneous
  history lengths this misalignment grows — aggregated OOS mixes different calendar
  sub-periods per symbol. Interpret combined OOS accordingly and say so in reports.
- **Walk-forward does not re-fit per fold** (walkforward.py docstring) — correct today
  because baseline strategies fit nothing, but any v0.2.0 that introduces a fitted
  quantity breaks that assumption and needs it addressed explicitly.
- **`universe` is not compared in `scan_scope_matches`** (approval_scope.py:88-93; the
  field exists at :41). Observed gap; relevant if an expanded snapshot ever becomes
  live-scoped.
- **`scopes[0]` ordering (R7b).** `paper_probation.py:118` selects the displayed
  sealed test by `scopes[0].dataset_snapshot_id` and `approved_scopes` has no
  `order_by`. Deterministic today (v2 and v5 each have exactly two passing
  evaluations, both on snapshot 3 → sealed tests 11 and 14); order-dependent the
  moment a passing evaluation lands on a different snapshot.
- **Snapshot-key shadowing via the scan path (§3a).** `research/scan.py:165` mints
  reusable `universe_auto_*` snapshots on every live scan. Always pass an explicit key
  to `get_or_create_dataset_snapshot`, and check the symbol set against existing
  reusable rows first.
- **`screen_universe` blends sources** (research/universe.py:45-76). Do not cite its
  numbers as `massive` history evidence; the problem worsens as the universe grows.
  Relatedly, a non-`massive` source anywhere in a snapshot fails gate 8 outright
  (snapshot 4 / `META_CONT`, §0.1).
- **Cost is universe-independent and optimistic outside mega-caps (§0.4).** 11 bps
  round trip flat, for SPY and for the 150th name by ADV alike.
- **Zero live paper evidence exists.** Every claim about the confirming test is a
  claim about code behaviour, not about observed behaviour.

---

## Appendix — Critic responses

Two critique items did not survive verification, and two more were directionally
right but numerically off. Recorded here so the corrections are auditable.

**Critique 19 — "v2 and v5 each already have 4 passing evaluations across snapshots
1–4, so the probation dashboard's sealed-test choice already depends on scope
ordering." — WRONG on the facts, right on the prospective hazard.**
Queried `strategy_promotion_evaluation`: v2 has **2** passing rows (ids 20, 32),
v5 has **2** (ids 23, 35), and **all four are on snapshot 3**. Every other evaluation
on snapshots 1, 2 and 4 fails gate 8 (§0.1), so no approved scope exists on any other
snapshot. `scopes[0].dataset_snapshot_id` is therefore 3 either way and the displayed
sealed test is deterministic today (v2 → id 11, +0.2982R/109; v5 → id 14,
+0.2935R/16). The critique's *forward-looking* point is nonetheless valid and has been
adopted as **R7b**, together with the current selection recorded for later comparison.

**Critique 20 (partial) — line-reference drift.**
- "Gate 0 is `promotion.py:512-533` (map: 512-534)" — **the critique is wrong.** The
  block runs 512-534: line 533 is `dataset_snapshot.id,` and line 534 is the closing
  `)` of the `return _finalize(` call. The map's `512-534` was correct and is retained.
- "`passed = bool(gates) and all(...)` is `:923` (map: 922-923)" — **both are off by
  one in different directions.** It is **line 922**; line 923 is
  `verdict = VERDICT_APPROVED if passed else VERDICT_NO_TRADE`. Corrected to `:922`.
- "`_finalize`'s insert is `:926-943`" — confirmed correct.
- Two further drifts the critique itself introduced, corrected in this edition:
  gate 7's docstring is `config/research.py:111-113` (not 110-112); the v2/v3
  horizon branch is `trend_continuation.py:37-39` (not 34-37);
  `alerts/dispatch.py` skips INTRADAY at `:241`; `approved_scope_scan.py` excludes it
  at `:81` with the policy comment at `:19-22`.

**Critique 2 (partial) — "citing only snapshot 3 is itself sealed-window selection".**
The factual core is correct and has been adopted in full: v3 passes gate 9 on three of
four sealed tests, the difference is 3 META trades worth +3.86R, and the first draft's
presentation was wrong. But the *selection* charge does not hold: snapshot 3 is the
**only** snapshot on which gate 8 passes for any version (§0.1 — META has 90 missing
sessions on snaps 1/2, and `META_CONT` is not `massive`-sourced on snap 4), so the
headline snapshot was forced by a pre-sealed data-quality gate, not chosen after
seeing gate 9. What was genuinely wrong was failing to disclose the other three locked
sealed tests; that is now §0.1 and appears in every relevant table.

**Critique 3 (partial) — "v3's sealed result is −1.65σ from its own pre-sealed
mean".** Reproduced and reconciled: −1.65 is the **two-sample** z,
`Δ/√(SE_sealed² + SE_pre²)` = −0.3358/0.2036. Treating the pre-sealed mean as a known
constant gives **−1.88**. Both figures are now given, with the basis for each stated
(§0.3). The critique's other power figures (sd 1.420/1.741/0.807/1.554; SE
0.0769/0.0975/0.0459/0.2176; 4.3%; 27%; 5,428; 106×; CI [−0.109, +0.232]) all
reproduce exactly and are adopted. The critique's estimate for v5's sd ("comparable to
1.4–1.7, so SE ≈ 0.35–0.43R") is replaced by the value actually implied by v5's own
stored CI: **sd = 1.484, SE = 0.371R**.

**Critique 4 (partial) — "expansion cannot fix gate 4 unless the point estimate
roughly quintuples".** The required-n arithmetic (5,428; 106×; still-failing CI at
n≈319) reproduces exactly and is adopted. The multiple is **3.1×**, not ~5×: at
n≈319 the hurdle is +0.1906R against +0.0613R.

**Critique 7 (partial) — "names ranked 25–150 by ADV plausibly carry 0.1–0.4R/trade".**
The mechanism, the code facts (`engine.py:90` default 5.0 bps; `backtest_runner.py:205-206`
never passing it; 11 bps round trip; `commission_per_share = 0.0`) and the
sign of the omission are all confirmed and adopted. The magnitude depends on whether
"10–30 bps effective half-spreads" means the quoted spread or half of it, so §0.4
gives the formula and four explicit spread scenarios instead of a single range: total
cost runs 0.087–0.220R (trend) and 0.099–0.251R (breakout) across 20–60 bps quoted
spreads, an *increment* of 0.05–0.21R over today's 11 bps. The direction — several
times v6's entire +0.0613R edge, at the wider end — holds.

**Critiques 1, 5, 6, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18 — confirmed in full**
and incorporated at §0.1, §0.3/§0.2 row 4, §0.5, §3(a) (iid), §3(a) (distribution
shift), §0.2 (trade-set column), §0.6, §0.2 (gate-7 divergence), §0.2 row 1 + §4.3
(gate-1/gate-5 coupling), §2.1 (touchpoint failure mode), §3(a) (snapshot table),
§4.0 W2 (read-only correction), R1, and R4 respectively.

---

*Phase 1 output, revision 2. Read-only: no strategy code, no configuration, no
database row and no gate threshold was changed in producing this document. Every
number above is either a `SELECT` result, a `file:line` citation, or an arithmetic
derivation whose inputs are both.*
