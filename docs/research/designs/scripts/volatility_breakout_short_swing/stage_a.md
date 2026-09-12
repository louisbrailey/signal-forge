# Stage A — `volatility_breakout.short_swing` v0.2.0 vs v0.1.0

**Verdict: STOP — write §11.**

**Zero sealed looks. Zero database rows.** Everything below was computed read-only, over the PRE-SEALED span **2016-09-10 → 2025-09-07** only. Nothing inside 2025-09-08 .. 2026-09-08 was computed. `evaluate_promotion`, `_get_or_create_sealed_test` and every other sealed or minting entry point were replaced with functions that raise before the run began; the database was a `mode=ro` backup copy and a driver-level hook would have raised on any write.

Design: `docs/research/designs/volatility_breakout_short_swing.md` §12.5, §12.7. Script: `scripts/stage_a_v6.py`.

## 0. The baseline is really v0.1.0 (checked before anything was read)

**FACT.** The degenerate cell `squeeze_lag=0, release_min=0.0` on snapshot 3 (`universe_24_ex_meta`, 24 symbols) reproduces **211 pre-sealed / 51 OOS trades at +0.06135R** — matching stored evaluation 36 exactly. E01 below is measured through this cell, so it is v0.1.0's rule, not a paraphrase of it.

## 1. E01 and E02 — the decisive comparison (§12.7)

Snapshot **11** `research_150_massive_10y_presealed_sel` — 150 symbols (15 ETFs + 135 single names), 126 of them new since snapshot 3.

| | OOS expectancy | all pre-sealed | in-sample |
|---|---|---|---|
| **v0.1.0** (E01) | +0.1065R ± 0.0912 (n = 212, sd 1.3286) | +0.1642R ± 0.0485 (n = 785, sd 1.3581) | +0.1856R ± 0.0572 (n = 573, sd 1.3694) |
| **v0.2.0** (E02) | +0.1762R ± 0.0908 (n = 184, sd 1.2322) | +0.2010R ± 0.0561 (n = 712, sd 1.4979) | +0.2096R ± 0.0688 (n = 528, sd 1.5811) |

**DERIVED.** E02 − E01 = **+0.06967R**, iid SE of the difference 0.1288 → **0.54 SE**; entry-month clustered SE 0.2109 (the pre-registered iid × 1.638) → **0.33 SE**. The clustered form binds (§4 K3).

## 2. The pre-registered kill tests

| test | bar | result | outcome |
|---|---|---|---|
| **K3a** — sign | `E02 > E01` | +0.17618R vs +0.10651R | **PASSED** |
| **K3b** — magnitude | ≥ 2.0 clustered SE (= +0.4218R) | +0.06967R = 0.33 SE | **FIRED** |
| **K5** — grid no-op | all 4 axes move OOS count or expectancy | {'contraction_max': True, 'stop_atr': True, 'squeeze_lag': True, 'release_min': True} | **PASSED** |

**K3b fired.** Under the pre-registration this is a hard kill: *stop, no Stage B, write §11*. The improvement is in the predicted direction but is not measurable at the achievable power, and a difference under 2 SE is not evidence. No re-parameterisation, no second variant, no second universe follows from this — those are explicitly forbidden by §12.1's stopping rule.

## 3. Composition — ETF vs single name (§12.7 item 1)

| | v0.1.0 OOS | v0.2.0 OOS | v0.1.0 all | v0.2.0 all |
|---|---|---|---|---|
| **ETFs** | -0.0636R ± 0.2456 (n = 37, sd 1.4938) | +0.2129R ± 0.2335 (n = 17, sd 0.9627) | +0.0412R ± 0.0915 (n = 157, sd 1.1471) | -0.0083R ± 0.1294 (n = 67, sd 1.0593) |
| **single names** | +0.1425R ± 0.0977 (n = 175, sd 1.2928) | +0.1724R ± 0.0974 (n = 167, sd 1.2587) | +0.1950R ± 0.0561 (n = 628, sd 1.4051) | +0.2227R ± 0.0605 (n = 645, sd 1.5353) |

**§7.2 item 3, pre-registered:** the expanded run's single-name expectancy was EXPECTED to come in below snapshot 3's +0.5251R, and it does. That is confirmation of the caveat, not a disappointment.

## 4. The new-symbols-only runs (§12.7 item 2)

| universe | n | v0.1.0 OOS | v0.2.0 OOS | difference |
|---|---|---|---|---|
| `single_names_135` | 135 | +0.1425R ± 0.0977 (n = 175, sd 1.2928) | +0.1724R ± 0.0974 (n = 167, sd 1.2587) | +0.02998R |
| `new_vs_snapshot3_126` | 126 | +0.1208R ± 0.0997 (n = 161, sd 1.2653) | +0.1466R ± 0.1029 (n = 152, sd 1.2689) | +0.02576R |

`single_names_135` is W1-COMP's common-stock block; `new_vs_snapshot3_126` is the stricter cut — every symbol absent from snapshot 3, and the only genuinely quasi-out-of-sample universe evidence available.

## 5. Gate-4 CI, iid and month-clustered (§12.7 item 4)

| version | iid 95% CI | half-width | month-clustered 95% CI | half-width | ratio | G |
|---|---|---|---|---|---|---|
| v0.1.0 | [-0.0678, +0.2897] | 0.1788 | [-0.1833, +0.4321] | 0.3077 | **1.721×** | 23 |
| v0.2.0 | [+0.0018, +0.3545] | 0.1763 | [-0.0449, +0.3165] | 0.1807 | **1.025×** | 23 |

Gate 4's bar is a lower bound above +0.0200R. Both bootstraps are 2,000 resamples, seed 20240101, percentile method — identical to `backtest/montecarlo.py`'s defaults, so the iid column is the number gate 4 would actually read.

**Caveat, and it is exactly why K3b's SE was pre-registered rather than measured.** The OOS pool spans only **23 distinct entry months**, and `clustered_bootstrap_all.md` §4.2 records that a cluster bootstrap on fewer than ~30 clusters is unreliable and erratic in both directions. The measured half-width ratios above (1.721×, 1.025×) straddle the pre-registered 1.638 rather than confirming it, and must not be read as a better estimate of it. K3b binds on the **fixed** factor precisely so that the SE could not be chosen once the difference was known.

## 6. Leave-one-month-out and leave-one-symbol-out (§12.7 item 5)

- **v0.1.0 leave-one-month-out** (23 months): pooled +0.10651R, range **-0.02604R … +0.16405R**; worst drop `2023-12` (29 trades) → -0.02604R — **sign flips**
- **v0.1.0 leave-one-symbol-out** (115 symbols): pooled +0.10651R, range **+0.07489R … +0.12483R**; worst drop `CAT` (2 trades) → +0.07489R
- **v0.2.0 leave-one-month-out** (23 months): pooled +0.17618R, range **+0.12459R … +0.22201R**; worst drop `2023-12` (39 trades) → +0.12459R
- **v0.2.0 leave-one-symbol-out** (111 symbols): pooled +0.17618R, range **+0.14932R … +0.20240R**; worst drop `ORCL` (3 trades) → +0.14932R

## 7. Spread re-pricings (§12.7 item 6, §8)

| round trip | quoted spread | v0.1.0 OOS | v0.2.0 OOS |
|---:|---:|---|---|
| **11 bps** (frozen — what the gates use) | 5 bps | +0.1065R | +0.1762R |
| **16 bps** | 10 bps | +0.0853R | +0.1589R |
| **26 bps** | 20 bps | +0.0446R | +0.1253R |
| **31 bps** | 25 bps | +0.0249R | +0.1090R |
| **66 bps** | 60 bps | -0.1006R | +0.0020R |

The 2×/5× convention is ambiguous between MAP §0.4 and W1 §7.1, so **all four non-baseline points are reported rather than guessing** (§13 Q1). `run_strategy_over_universe` never overrides `spread_bps`, so these were produced by driving `run_backtest` directly at the same warm-up, cost model and per-symbol IS/OOS boundary.

## 8. Gate 5 — the 81-cell grid, with its realised denominators (§12.7 item 7)

Axes (pre-registered §12.1): `{'contraction_max': [0.65, 0.75, 0.85], 'stop_atr': [1.5, 1.75, 2.0], 'squeeze_lag': [3, 5, 10], 'release_min': [0.8, 1.0, 1.2]}` — 81 points.

| quantity | realised |
|---|---|
| evaluable (≥ 15 OOS trades) | **81 / 81** |
| positive of evaluable | **80 / 81** = 98.8% (need 60%) |
| one-step neighbours, evaluable | **8 / 8** |
| neighbours positive | 100.0% (need 75%) |
| baseline expectancy | +0.1762R |
| median / worst evaluable | +0.1860R / -0.0076R |
| **fragile?** | **False** |

**K5 (no-op check):** `axis_moved` = `{'contraction_max': True, 'stop_atr': True, 'squeeze_lag': True, 'release_min': True}`, `inert_axes` = `[]`. Every axis moves the OOS trade count or expectancy, so gate 5 is testing something real.

## 9. Gates 1, 6 and 7 (§12.7 item 3)

### v0.1.0

- **Gate 1** — 3 of 4 rolling folds clear both the per-fold trade floor and positive expectancy (need 2): **PASS**. Folds: 145@+0.292R, 339@+0.215R, 126@-0.106R, 175@+0.155R
- **Gate 6** — bull **582**, bear **0**, range **131** (need ≥ 10 in 3 of 3; 2/3 met): **FAIL**. **Unbucketed 72** = warm-up 72 + no-proxy-bar 0 + unlabelled 0; census closes over 785 trades: True.
- **Gate 7** — strategy Sharpe +1.137 vs SPY +0.719: **PASS**. **Identity:** per-trade mean/sd = +0.1210, √(trades/yr) = √88.4 = 9.400, product = +1.137. Turnover 88.4/yr, exposure 1.00.

### v0.2.0

- **Gate 1** — 4 of 4 rolling folds clear both the per-fold trade floor and positive expectancy (need 2): **PASS**. Folds: 172@+0.333R, 285@+0.155R, 103@+0.119R, 152@+0.194R
- **Gate 6** — bull **567**, bear **4**, range **63** (need ≥ 10 in 3 of 3; 2/3 met): **FAIL**. **Unbucketed 78** = warm-up 78 + no-proxy-bar 0 + unlabelled 0; census closes over 712 trades: True.
- **Gate 7** — strategy Sharpe +1.202 vs SPY +0.719: **PASS**. **Identity:** per-trade mean/sd = +0.1343, √(trades/yr) = √80.1 = 8.952, product = +1.202. Turnover 80.1/yr, exposure 1.00.

**§13 A3 disclosure, pre-registered:** gate 7 as coded (`portfolio_metrics.py:109-111`) is `Sharpe = (mean/sd) × √(trades/year)`. Any gate-7 margin attributable to the second factor is a **turnover artefact** and contributes no independent evidence of edge quality. It is reported here whether or not the operator approves A3, because it is a verified property of the code.

## 10. Gate-by-gate forecast for v0.2.0 on the expanded snapshot

| gate | forecast | basis |
|---|---|---|
| `gate1_rolling_walkforward` | **PASS** | 4 of 4 folds clear the floor and are positive (need 2) |
| `gate2_min_oos_trades` | **PASS** | 184 OOS trades vs threshold 30 |
| `gate3_net_expectancy` | **PASS** | +0.1762R vs > +0.0000R |
| `gate4_bootstrap_ci` | **FAIL** | iid CI low +0.0018R vs > +0.0200R (month-clustered low -0.0449R) |
| `gate5_parameter_sensitivity` | **PASS** | 81/81 evaluable, 0.988 positive, 1.0 neighbours positive |
| `gate6_regime_coverage` | **FAIL** | bull 567, bear 4, range 63; unbucketed 78 |
| `gate7_benchmark` | **PASS** | Sharpe +1.20 vs SPY +0.72; turnover 80.1/yr |
| `gate8_data_quality_and_leakage` | —  | not run in Stage A: validate_daily(persist=True) writes rows. The four v0.2.0 entry features are covered by LEAKAGE_FEATURE_CHECKS and are unit-tested in tests/research/test_breakout_v020.py. |
| `gate9_sealed_test` | —  | NOT COMPUTED. This is the look Stage A exists to avoid (§0.1(2)). |

This is a forecast of gates 1-8 computed read-only, not a promotion run. **Gate 9 is not forecast and was not computed**: it is precisely the sealed look Stage A exists to avoid.

## 11. Per-symbol IS/OOS boundary dates (§12.7 item 9)

`_TRAIN_FRAC = 0.6` splits **per symbol**, so the aggregate OOS pool mixes calendar sub-periods — a worse problem at 150 symbols than at 24. The full per-symbol table (boundary date, first/last bar, bar count, trade counts) is in `stage_a.json` under `v0_2_0.per_symbol_boundary`. Summary:

- earliest boundary **2022-02-10**, latest **2022-10-12**, median **2022-02-10**
- 150 symbols carried enough data to run (of 150)

## 12. The §10.1 sealed-look ledger, and the look statement

| Ver | Strategy | snap 1 | snap 2 | snap 3 | snap 4 |
|---|---|---|---|---|---|
| 2 | `trend_continuation.short_swing` | id 1: +0.3246R / 112 ✅ | id 6: +0.3246R / 112 ✅ | id 11: +0.2982R / 109 ✅ | id 16: +0.3246R / 112 ✅ |
| 3 | `trend_continuation.medium_swing` | id 2: +0.0109R / 98 ✅ | id 7: +0.0109R / 98 ✅ | id 12: −0.0294R / 95 ❌ | id 17: +0.0109R / 98 ✅ |
| 4 | `mean_reversion.short_swing` | id 3: +0.1230R / 91 ✅ | id 8: +0.1230R / 91 ✅ | id 13: +0.1278R / 84 ✅ | id 18: +0.1230R / 91 ✅ |
| 5 | `relative_strength.medium_swing` | id 4: +0.2935R / 16 ✅ | id 9: +0.2935R / 16 ✅ | id 14: +0.2935R / 16 ✅ | id 19: +0.2935R / 16 ✅ |
| **6** | **`volatility_breakout.short_swing`** | **id 5: −0.0979R / 10 ❌** | **id 10: −0.0979R / 10 ❌** | **id 15: −0.0979R / 10 ❌** | **id 20: −0.0979R / 10 ❌** |

All four v6 draws are the **identical** 10 trades at −0.0979R; SE = 0.491R, so −0.0979R is **0.20 SE** from zero and carries no information about sign. No sealed number motivated anything in this document.

**The look statement.** Baseline **k = 5**. **Stage A spent 0 looks** and wrote 0 rows. Stage B would have been **look 6** under MAP §4.2 item 10 (**look 5** under MAP §0.1 — the two conventions differ by one and the ambiguity is operator question Q2). **Stage B is not reached: K3b fired, so k stays at 5.**

**FACT (read-only, this run):** `strategy_sealed_test` holds **22 rows** on the backup copy — unchanged by Stage A, which creates none.

## 13. Mandatory disclosures

### §0.5 — an abstention that was already broken, carried forward

The mechanism proposal deliberately never computed the proposed rule's P&L so that no parameter could be selected on it. That abstention was broken in the design phase while settling a judge dispute about per-trade dispersion: v0.2.0's snapshot-3 figures (pre-sealed +0.2937R ± 0.1523, OOS +0.3168R ± 0.1851) were computed and reported there. **No parameter was changed as a result, and none is changed here:** `squeeze_lag = 5` and `release_min = 1.0` are the values fixed before any expectancy existed, and the grid neighbours (3/10 and 0.8/1.2) are the pre-registered ones.

### §7.2 — universe-level exposure, survivorship

**Discovery is active-tickers-only, so names delisted or failed between 2016 and 2026 can never enter this universe, regardless of which liquidity window ranks the survivors. The size of the effect is unmeasurable with the data held.** This disclosure is required verbatim in every report on this snapshot. The related sealed-window selection defect (W1-SEL ranked by dollar volume computed inside the sealed year) was found and fixed before the snapshot was built — this run uses `research_150_massive_10y_presealed_sel`, selected on a pre-sealed window. Bars are also split-adjusted as of fetch date, not point-in-time, and `source="massive"` was passed explicitly everywhere so the dual-source hazard (loading `massive_grouped` duplicates every session inside the sealed window) cannot arise.

### Cost, restated (§8, unchanged by this run)

Modelled cost at v0.1.0's own OOS entries is **89% of its net edge** on snapshot 3, so MAP §0.4's 0.042R is an understatement. On this snapshot the spread table above is the live version of that statement: at the mandated 2× spread both versions lose most of the measured edge.

## 14. What follows

Per §12.1's stopping rule and §11: **write `docs/research/designs/volatility_breakout.short_swing--does_not_pass.md`**. v0.1.0 stays EXPERIMENTAL; v0.2.0 stays EXPERIMENTAL. Neither is promoted, neither is deleted, no gate or threshold is touched, the cost model is unchanged, and the variant ledger closes at **1 of 1** (cap 2). The variant budget is not spent again: a second parameterisation chosen because this point estimate disappointed is exactly what the pre-registration forbids.

**The finding is not 'the mechanism failed'.** E02 > E01 in the predicted direction by +0.06967R. It is **0.33 clustered SE**, against a 2.0 SE bar — the mechanism is *unsupported at the achievable power*, which is the outcome §11 pre-registered as most likely.

---

*Stage A output. No row in `data/signalforge.sqlite` was written, no promotion / sensitivity-writing / sealed entry point was invoked, no provider API was called, and no quantity inside the sealed window was computed. The sealed-look count is unchanged by the production of this document.*
