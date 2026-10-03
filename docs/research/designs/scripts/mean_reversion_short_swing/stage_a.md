# Stage A — `mean_reversion.short_swing` exits/risk redesign (V1 / V2) vs v0.1.0

**Verdict: STOP — both variants dead; write §11 null disposition.**

**Zero sealed looks. Zero database rows.** Everything below was computed read-only over the PRE-SEALED span **2016-09-10 → 2025-09-07** (snapshot 1: → 2025-09-06). `evaluate_promotion`, `_get_or_create_sealed_test`, `persist_promotion_evaluation`, `get_or_create_dataset_snapshot` and `persist_backtest_result` were replaced with functions that raise before the run began; the database was a `mode=ro` copy and a driver-level hook would have raised on any write. `strategy_sealed_test` rows: 22 before, 22 after.

Design: `docs/research/designs/proposals/mean_reversion_short_swing--exits_risk.md` §4 (F1–F5), §9 (stopping rule).
Script: `scripts/stage_a_mr.py`.

## 0. The baseline is really v0.1.0, and the wrapper is the identity at λ = 0

**FACT.** `run_strategy_over_universe` on snapshot 3 (`universe_24_ex_meta`) gives **984 pre-sealed / 309 OOS at -0.08374R** — eval 34 reproduced (MATCH). The script's variant wrapper at `stop_anchor_blend = 0.0` reproduces that trade list exactly (identity holds), so every V1/V2 number below is a controlled change to v0.1.0's rule, not a paraphrase of it. Provenance: ['massive'], last bar 2025-09-05.

The engine does not yet carry `stop_distance` / `stop_anchor_blend` / `min_risk_distance`; the wrapper rewrites each `EntrySignal.stop_price` to the §2.1 `stop_level` using the same next-bar open the engine uses for the fill, so `risk_per_share` and `_resolve_exit` run the proposed arithmetic unchanged. No file under `src/` was modified.

## 1. V1 — `{'stop_anchor_blend': 1.0}`

| snapshot | n (v0.1.0 / variant) | v0.1.0 pre-sealed | variant pre-sealed | v0.1.0 OOS | variant OOS |
|---|---|---|---|---|---|
| 3 `universe_24_ex_meta` | 984 / 975 | -0.0621R ± 0.0278 (n = 984, sd 0.8725) | -0.0580R ± 0.0254 (n = 975, sd 0.7939) | -0.0837R ± 0.0467 (n = 309, sd 0.8202) | -0.0843R ± 0.0452 (n = 311, sd 0.7967) |
| 2 `universe_25_baseline` | 999 / 990 | -0.0622R ± 0.0275 (n = 999, sd 0.8684) | -0.0547R ± 0.0251 (n = 990, sd 0.7908) | -0.0782R ± 0.0454 (n = 320, sd 0.8119) | -0.0737R ± 0.0440 (n = 322, sd 0.7891) |
| 1 `universe_25_baseline_legacy` | 999 / 990 | -0.0622R ± 0.0275 (n = 999, sd 0.8684) | -0.0547R ± 0.0251 (n = 990, sd 0.7908) | -0.0782R ± 0.0454 (n = 320, sd 0.8119) | -0.0737R ± 0.0440 (n = 322, sd 0.7891) |
| 4 `universe_25_meta_continuity_corrected` | 1031 / 1021 | -0.0604R ± 0.0270 (n = 1031, sd 0.8681) | -0.0536R ± 0.0248 (n = 1021, sd 0.7924) | -0.0854R ± 0.0452 (n = 323, sd 0.8118) | -0.0748R ± 0.0438 (n = 325, sd 0.7894) |

### F1 — accounting-invariant paired test (the kill test)

Fixed denominator `stop_atr × ATR(14)` at the signal bar for both versions; paired per-trade difference over the matched (symbol, entry date) set.

| snapshot | matched | paired Δ | SE | σ | unmatched (base / variant) | F1 |
|---|---|---|---|---|---|---|
| `universe_24_ex_meta` | 962 | **-0.01647R** | 0.01179 | **-1.40** | 22 / 13 | **FAIL** |
| `universe_25_baseline` | 977 | **-0.01346R** | 0.01178 | **-1.14** | 22 / 13 | **FAIL** |
| `universe_25_baseline_legacy` | 977 | **-0.01346R** | 0.01178 | **-1.14** | 22 / 13 | **FAIL** |
| `universe_25_meta_continuity_corrected` | 1007 | **-0.01212R** | 0.01173 | **-1.03** | 24 / 14 | **FAIL** |

- `universe_24_ex_meta` unpaired raw-R pre-sealed Δ (context only, not accounting-invariant): +0.00406R ± 0.03768 (+0.11 SE)
- `universe_25_baseline` unpaired raw-R pre-sealed Δ (context only, not accounting-invariant): +0.00746R ± 0.03724 (+0.20 SE)
- `universe_25_baseline_legacy` unpaired raw-R pre-sealed Δ (context only, not accounting-invariant): +0.00746R ± 0.03724 (+0.20 SE)
- `universe_25_meta_continuity_corrected` unpaired raw-R pre-sealed Δ (context only, not accounting-invariant): +0.00679R ± 0.03669 (+0.19 SE)

**Note on F2.** F2 fires only when the whole-sample paired Δ is positive while the risk ≥ 1 ATR subset is under 2 SE. With a non-positive whole-sample Δ the F2 PASS below is vacuous and carries no evidence for the variant.

### F2 — does the effect live only in the gapped tail?

| snapshot | risk ≥ 1 ATR: Δ (σ, n) | risk < 1 ATR: Δ (σ, n) | F2 |
|---|---|---|---|
| `universe_24_ex_meta` | -0.00782R (-0.91σ, n=897) | -0.13578R (-1.06σ, n=65) | **PASS** |
| `universe_25_baseline` | -0.00585R (-0.67σ, n=911) | -0.11863R (-0.93σ, n=66) | **PASS** |
| `universe_25_baseline_legacy` | -0.00585R (-0.67σ, n=911) | -0.11863R (-0.93σ, n=66) | **PASS** |
| `universe_25_meta_continuity_corrected` | -0.00406R (-0.46σ, n=940) | -0.12513R (-1.00σ, n=67) | **PASS** |

### F3 — walk-forward folds (gate 1 replication)

| snapshot | v0.1.0 folds (n @ R) | variant folds (n @ R) | Δ per fold | positive | F3 |
|---|---|---|---|---|---|
| `universe_24_ex_meta` | 257@+0.0175, 292@-0.1949, 181@+0.0436, 254@-0.0651 | 257@+0.0312, 285@-0.1643, 177@-0.0212, 256@-0.0547 | +0.0137, +0.0306, -0.0648, +0.0104 | 1/4 | **FAIL** |
| `universe_25_baseline` | 257@+0.0175, 292@-0.1949, 184@+0.0379, 266@-0.0628 | 257@+0.0312, 285@-0.1643, 180@-0.0267, 268@-0.0395 | +0.0137, +0.0306, -0.0646, +0.0233 | 1/4 | **FAIL** |
| `universe_25_baseline_legacy` | 257@+0.0175, 291@-0.1959, 185@+0.0383, 266@-0.0628 | 257@+0.0312, 284@-0.1653, 181@-0.0258, 268@-0.0395 | +0.0137, +0.0306, -0.0641, +0.0233 | 1/4 | **FAIL** |
| `universe_25_meta_continuity_corrected` | 269@+0.0148, 307@-0.1734, 189@+0.0196, 266@-0.0628 | 269@+0.0283, 300@-0.1500, 184@-0.0367, 268@-0.0395 | +0.0135, +0.0234, -0.0563, +0.0233 | 1/4 | **FAIL** |

### F4 — the artefact class must disappear

| snapshot | v0.1.0 profitable stops | variant profitable stops | variant risk < 0.5 ATR | F4 |
|---|---|---|---|---|
| `universe_24_ex_meta` | 4 | 0 | 0 | **PASS** |
| `universe_25_baseline` | 4 | 0 | 0 | **PASS** |
| `universe_25_baseline_legacy` | 4 | 0 | 0 | **PASS** |
| `universe_25_meta_continuity_corrected` | 4 | 0 | 0 | **PASS** |

### F5 — snapshot invariance: same F1 sign on all four = **True**, F1–F4 hold everywhere = **False** → **FAIL**

**Verdicts:** F1 **FAIL**, F2 **PASS**, F3 **FAIL**, F4 **PASS**, F5 **FAIL**.

## 2. V2 — `{'min_risk_atr': 1.0}`

| snapshot | n (v0.1.0 / variant) | v0.1.0 pre-sealed | variant pre-sealed | v0.1.0 OOS | variant OOS |
|---|---|---|---|---|---|
| 3 `universe_24_ex_meta` | 984 / 936 | -0.0621R ± 0.0278 (n = 984, sd 0.8725) | -0.0134R ± 0.0250 (n = 936, sd 0.7658) | -0.0837R ± 0.0467 (n = 309, sd 0.8202) | -0.0136R ± 0.0456 (n = 291, sd 0.7784) |
| 2 `universe_25_baseline` | 999 / 950 | -0.0622R ± 0.0275 (n = 999, sd 0.8684) | -0.0133R ± 0.0247 (n = 950, sd 0.7625) | -0.0782R ± 0.0454 (n = 320, sd 0.8119) | -0.0069R ± 0.0444 (n = 301, sd 0.7694) |
| 1 `universe_25_baseline_legacy` | 999 / 950 | -0.0622R ± 0.0275 (n = 999, sd 0.8684) | -0.0133R ± 0.0247 (n = 950, sd 0.7625) | -0.0782R ± 0.0454 (n = 320, sd 0.8119) | -0.0069R ± 0.0444 (n = 301, sd 0.7694) |
| 4 `universe_25_meta_continuity_corrected` | 1031 / 981 | -0.0604R ± 0.0270 (n = 1031, sd 0.8681) | -0.0120R ± 0.0244 (n = 981, sd 0.7654) | -0.0854R ± 0.0452 (n = 323, sd 0.8118) | -0.0153R ± 0.0442 (n = 304, sd 0.7705) |

### F1 — accounting-invariant paired test (the kill test)

Fixed denominator `stop_atr × ATR(14)` at the signal bar for both versions; paired per-trade difference over the matched (symbol, entry date) set.

| snapshot | matched | paired Δ | SE | σ | unmatched (base / variant) | F1 |
|---|---|---|---|---|---|---|
| `universe_24_ex_meta` | 914 | **+0.00000R** | 0.00000 | **+0.00** | 70 / 22 | **FAIL** |
| `universe_25_baseline` | 928 | **+0.00000R** | 0.00000 | **+0.00** | 71 / 22 | **FAIL** |
| `universe_25_baseline_legacy` | 928 | **+0.00000R** | 0.00000 | **+0.00** | 71 / 22 | **FAIL** |
| `universe_25_meta_continuity_corrected` | 959 | **+0.00000R** | 0.00000 | **+0.00** | 72 / 22 | **FAIL** |

- `universe_24_ex_meta` unpaired raw-R pre-sealed Δ (context only, not accounting-invariant): +0.04862R ± 0.03742 (+1.30 SE)
- `universe_25_baseline` unpaired raw-R pre-sealed Δ (context only, not accounting-invariant): +0.04890R ± 0.03697 (+1.32 SE)
- `universe_25_baseline_legacy` unpaired raw-R pre-sealed Δ (context only, not accounting-invariant): +0.04890R ± 0.03697 (+1.32 SE)
- `universe_25_meta_continuity_corrected` unpaired raw-R pre-sealed Δ (context only, not accounting-invariant): +0.04843R ± 0.03644 (+1.33 SE)

**Note on a degenerate F1.** This variant is a *no-trade* rule: every matched entry is simulated identically, so the paired difference is identically zero and F1 cannot clear a 2 SE bar by construction. Its whole effect lives in the removed trades (the unpaired Δ above). §4 requires F1 of every variant and §9 step 3 names F1 for V2 explicitly, so the pre-registered reading is FAIL; the alternative reading (treat F1 as inapplicable to V2) is noted for the operator and would still leave the OOS point estimate negative on every snapshot.

**Note on F2.** F2 fires only when the whole-sample paired Δ is positive while the risk ≥ 1 ATR subset is under 2 SE. With a non-positive whole-sample Δ the F2 PASS below is vacuous and carries no evidence for the variant.

### F2 — does the effect live only in the gapped tail?

| snapshot | risk ≥ 1 ATR: Δ (σ, n) | risk < 1 ATR: Δ (σ, n) | F2 |
|---|---|---|---|
| `universe_24_ex_meta` | +0.00000R (+0.00σ, n=914) | +0.00000R (+0.00σ, n=0) | **PASS** |
| `universe_25_baseline` | +0.00000R (+0.00σ, n=928) | +0.00000R (+0.00σ, n=0) | **PASS** |
| `universe_25_baseline_legacy` | +0.00000R (+0.00σ, n=928) | +0.00000R (+0.00σ, n=0) | **PASS** |
| `universe_25_meta_continuity_corrected` | +0.00000R (+0.00σ, n=959) | +0.00000R (+0.00σ, n=0) | **PASS** |

### F3 — walk-forward folds (gate 1 replication)

| snapshot | v0.1.0 folds (n @ R) | variant folds (n @ R) | Δ per fold | positive | F3 |
|---|---|---|---|---|---|
| `universe_24_ex_meta` | 257@+0.0175, 292@-0.1949, 181@+0.0436, 254@-0.0651 | 249@+0.0060, 275@-0.1099, 176@+0.0612, 236@+0.0228 | -0.0115, +0.0850, +0.0176, +0.0879 | 3/4 | **PASS** |
| `universe_25_baseline` | 257@+0.0175, 292@-0.1949, 184@+0.0379, 266@-0.0628 | 249@+0.0060, 275@-0.1099, 179@+0.0551, 247@+0.0252 | -0.0115, +0.0850, +0.0172, +0.0880 | 3/4 | **PASS** |
| `universe_25_baseline_legacy` | 257@+0.0175, 291@-0.1959, 185@+0.0383, 266@-0.0628 | 249@+0.0060, 274@-0.1107, 180@+0.0553, 247@+0.0252 | -0.0115, +0.0852, +0.0170, +0.0880 | 3/4 | **PASS** |
| `universe_25_meta_continuity_corrected` | 269@+0.0148, 307@-0.1734, 189@+0.0196, 266@-0.0628 | 260@+0.0077, 290@-0.0916, 184@+0.0357, 247@+0.0252 | -0.0071, +0.0818, +0.0161, +0.0880 | 3/4 | **PASS** |

### F4 — the artefact class must disappear

| snapshot | v0.1.0 profitable stops | variant profitable stops | variant risk < 0.5 ATR | F4 |
|---|---|---|---|---|
| `universe_24_ex_meta` | 4 | 0 | 0 | **PASS** |
| `universe_25_baseline` | 4 | 0 | 0 | **PASS** |
| `universe_25_baseline_legacy` | 4 | 0 | 0 | **PASS** |
| `universe_25_meta_continuity_corrected` | 4 | 0 | 0 | **PASS** |

### F5 — snapshot invariance: same F1 sign on all four = **True**, F1–F4 hold everywhere = **False** → **FAIL**

**Verdicts:** F1 **FAIL**, F2 **PASS**, F3 **PASS**, F4 **PASS**, F5 **FAIL**.

## 3. Decision under §9

**Both variants are dead.** §9 steps 1–3 exhausted: F1 is the test that decides the proposal, and it did not clear its pre-registered bar. Per §9 step 5 there is no third variant, no λ tuning and no promotion run. **Write the §11 null disposition** at `docs/research/dispositions/mean_reversion_short_swing.md`. v0.1.0 stays EXPERIMENTAL; its four sealed tests (ids 3, 8, 13, 18) are untouched; k stays at 5.

---

*Stage A output. No row in `data/signalforge.sqlite` was written, no promotion / sensitivity-writing / sealed entry point was invoked, no provider API was called, and no quantity inside the sealed window was computed. The sealed-look count is unchanged.*
