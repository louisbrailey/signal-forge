# Design — `mean_reversion.short_swing` v0.1.0 (version 4)

**Synthesis of three independent Phase-2 proposals and four judge verdicts.**
**Date:** 2026-09-10. **Author:** design synthesizer (Phase 2, `STRATEGY_COMPLETION_PLAN.md` step 2).
**Inputs:** `designs/proposals/mean_reversion_short_swing--signal_regime.md`,
`…--exits_risk.md`, `…--universe_breadth.md`, plus their `.json` siblings and the
four judge reports (legitimacy + impact/robustness/cost per angle, one angle having
two, scores 7.5 / 8 / 6.5 / 8 / 6 / 7).
**Governed by:** `STRATEGY_COMPLETION_MAP.md` §1 (R1–R10), §2.2, §4.2; `STRATEGY_COMPLETION_PLAN.md`.

> ## Bottom line
>
> **The chosen path is the null option: a documented, evidence-backed "does not pass"
> for `mean_reversion.short_swing`. No v0.2.0 is designed, implemented or promoted.
> Zero sealed looks are consumed; the count stays at k = 5.**
>
> All three angles independently reached the same disposition, and all three sets of
> judges upheld it. This document does **not** merely record that agreement — it
> re-ran the decisive computations, and the re-run **weakens** the case for change
> further than any of the three proposals or four judges stated:
>
> - **Signal/regime (H13, `market_ret_63d ≥ 0`).** The headline `+0.3038R at 2.005 SE
>   clustered` reproduces **exactly** — but it clears the 2-SE bar only under the strict
>   `r63 < 0` partition. Measured against the complement the *shipped fail-closed rule*
>   would actually block (273 trades, including two proxy-warmup trades that are both
>   winners), the difference is **+0.2963R at 1.96 SE clustered — below the bar**
>   (§C.3, new finding). And gate 3 / gate 6 are provably the same quantity: their
>   admissible parameter regions are disjoint.
> - **Exits/risk (fill-anchored stop).** The motivating `t = −3.02` is circular — the
>   partition variable is the denominator. On a denominator that does not contain it,
>   **t = −1.60 pre-sealed / −1.91 OOS**, both under 2 SE (§C.2, verified). The
>   accounting-invariant *ceiling* on the whole mechanism is **+0.0079R pre-sealed /
>   +0.0139R OOS**, against the proposal's own kill-test bar of ≥ +0.03R. The primary
>   variant is dead before it is run.
> - **Universe/breadth (H7).** All four of its own pre-registered falsifiers fire today.
>   Re-simulated **as a rule** rather than as a partition of v0.1.0's output, the filtered
>   strategy is 308 trades at +0.0140R, OOS 142 at −0.0335R, gate-6 bear **6**, and the
>   27-point gate-5 grid is **0 of 27 positive, 0 of 6 neighbours** (§C.4, verified).
>
> **Two separable, non-promotion items are put to the operator** (§14): an engine
> risk-unit correctness fix (P1) and a gate-5 axis integrity rule (P2). Neither is a
> `mean_reversion` change, neither bumps a strategy version, and neither costs a sealed
> look. **Both are recommended, and both require operator approval before any code is written.**

---

## A. Chosen path, and why no runner-up is grafted

### A.1 The decision

| Option | Verdict |
|---|---|
| Ship a v0.2.0 from **signal/regime** (H13 market-direction filter) | **Rejected.** Falsified by its own pre-registered F-6/F-7; gate 3 and gate 6 have disjoint admissible regions; gates 4, 5, 7 fail at every swept threshold. |
| Ship a v0.2.0 from **exits/risk** (V1 fill-anchored stop or V2 min-risk guard) | **Rejected.** No pre-sealed motivation survives an accounting-invariant measurement; the mechanism's ceiling is 4× below its own kill-test bar. |
| Ship a v0.2.0 from **universe/breadth** (H7 breadth filter) | **Rejected.** Four of four pre-registered falsifiers fire; requires a snapshot that does not exist; and even a pass would not be operable (§7.4). |
| **Graft** the best of two or three | **Rejected** — see §A.2. |
| **Null option: documented "does not pass"** | **CHOSEN.** |

### A.2 Why grafting is not available here

MAP §4.2 and the synthesis brief permit grafting "only if the runners-up's evidence and
falsification criteria carry over". They do not, for three separate reasons, each
sufficient:

1. **The candidate combinations are arithmetically incompatible with the gate-5
   requirement.** FACT (`sensitivity.py:29`): `MAX_GRID_POINTS = 120`, and
   `run_parameter_sensitivity` raises `ValueError` above it (`sensitivity.py:137-140`).
   MAP §4.2 item 6 requires **every** parameter a v0.2.0 introduces to become a
   pre-registered axis. H13 + V1 is 4 axes (`z_entry`, `stop_atr`,
   `market_ret_63d_min`, `stop_anchor_blend`) = 81 points — feasible; H13 + V1 + breadth,
   or V1 + V2, is 5 axes = **243 > 120**. Any three-way graft can only ship by shrinking
   an axis to two values, i.e. by weakening the neighbourhood — forbidden under R4.
2. **The evidence does not compose; two of the three components have no evidence left
   after correction.** A graft inherits the union of its components' weaknesses. H13's
   clustered margin is 1.96–2.01 SE depending on a definitional choice (§C.3); the anchor
   mechanism is 1.60–1.91 SE on an invariant denominator (§C.2); breadth is 1.02 SE
   clustered (§C.4). Stacking three sub-2-SE effects does not produce a 2-SE effect, and
   there is direct evidence that stacking *hurts*: FACT (proposal §3.4, snapshot 3 OOS)
   `Vol.LOW ∧ r63 ≥ 0` earns **−0.0740R** on 163 trades against H13 alone at +0.0373R
   on 212.
3. **The binding gates are point-estimate gates that no component addresses.** Gate 4
   needs an OOS point estimate the best single component reaches at 0.60 SE; gate 7 needs
   a Sharpe of +0.719 against a best measured +0.227. Adding a +0.008R invariant exit
   correction (§C.2) to a +0.037R filtered expectancy does not move either.

**A graft is therefore not a conservative middle path — it is the one option that would
combine three unsupported mechanisms while forcing a weakened sensitivity grid.**

### A.3 What each angle contributes to the record instead

| Angle | Kept as a finding | Not kept |
|---|---|---|
| signal/regime | H13 established as v4's strongest pre-sealed regime effect; the **gate-3/gate-6 structural conflict** that closes the whole market-direction lane; the measured hidden-fragility demonstration (§C.5) | the v0.2.0 |
| exits/risk | The **risk-unit anchor defect** as a shared-engine correctness fact (four `stop` exits booked as wins; one −3.099R off a 2.9-cent risk unit; median realised risk 2.127 ATR against an intended 2.000) | V1 and V2 as promotion candidates |
| universe/breadth | The **degeneracy** of any cross-sectional statistic on an ETF-majority universe; the **concentration** fact; the **operability blocker** for any cross-sectional v4 | the v0.2.0 and the W1 re-run as a v4 activity |

---

## B. Judge-defect adjudication

Every defect raised by the four judges is ruled on. **Accepted** defects are corrected in
§§1–11 below. **Rejected / partially rejected** defects are listed with reasons.

### B.1 Accepted in full (corrections carried into §§1–11)

**signal/regime — legitimacy judge**

| # | Defect | Verification |
|---|---|---|
| L1 | §2.1/§2.2 registration spec is unimplementable: `VERSION` is a module constant read by `spec()`, so two registered `MeanReversion()` instances report the same `versioned_key` | **FACT, re-verified:** `mean_reversion.py:17` `VERSION = "0.1.0"`, consumed at `:41`; `registry.py:94-95` raises `StrategyRegistrationError` on a duplicate `versioned_key`. The "seventh entry alongside the untouched v0.1.0" cannot exist without a distinct class/module. |
| L2 | The §11 "do it regardless" grid edit raises `TypeError` for v0.1.0 | **FACT, re-verified:** `promotion.py:189` dispatches on `key.startswith("mean_reversion")` and `:194` calls `_replace(base, **p)` on the instance's own params; `MeanReversionParams` has exactly 6 fields (`mean_reversion.py:21-27`). |
| L3 | The stacked `Vol.LOW ∧ r63 ≥ 0` check is an evaluated variant missing from the R5 ledger | Correct; it is variant 3 in §9. |
| L4 | §0's "the only sealed figures cited are in §10 and §11" omits the §9 stopping-rule argument | Correct as a disclosure defect. Every sealed-derived argument in this document is marked inline. |
| L5 | Gate-4 required n substitutes the measured filtered sd for MAP §0.3's 0.807 | Both are now reported (§5). |
| L6 | Fail-closed semantics depend on proxy **coverage**, not only on the 63-bar warmup: `signal_fn_for` (`base.py:39-41`) returns `NEUTRAL` for any date missing from the regime map, and `NEUTRAL.market_ret_63d` is `None` | Correct; carried into §7. |
| L7 | The proposed leakage-check addition is a no-op: `rolling_return(20)` is already in `_leakage_self_check` and `rolling_return` is window-parameterised | **FACT, re-verified:** `promotion.py:257-262` lists `sma(50)`, `rolling_return(20)`, `atr(14)`, `realized_vol(20)`. Carried into §7. |
| L8 | MAP is internally inconsistent on look numbering (§0.1/R2 say look 5; §4.2 item 10 says look 6) | **FACT, re-verified:** `pipeline_hardening_spec.md:538-545` records the same clash and adopts `k_prior = 4 / this_look = 5`. This document follows MAP §4.2 item 10 and the binding brief (**k = 5 → look 6**) and flags it for the operator (§10, §14). |

**signal/regime — impact judge**

| # | Defect | Verification |
|---|---|---|
| I1 | The gate-3/gate-6 frontier has a non-monotone bear count (12 at x=−0.08 → 13 at x=−0.06), so the sweep rows are re-simulations in which the flat-only engine redeployed freed capacity; §5's "a market-wide filter frees no capacity" is disproved by the proposal's own table | Accepted. **My own check confirms the identity holds only where it was tested:** at x = 0.00 the re-simulated set is **711 trades**, equal to the `r63 ≥ 0` partition of the 984 baseline trades, element for element (§C.3). I did not re-run the other frontier rows; they are labelled proposal-reported throughout. |
| I2 | Undisclosed gate-6 zero-margin case: bear = 11 against a floor of 10 at x = −0.04 and −0.03 | Accepted (§5.4). The disjointness conclusion survives in direction; the boundary's *location* is ±1 trade. |
| I3 | Two significance bars: F-3 graded at 1 SE while 2 SE is applied elsewhere | Accepted. Ex-F2 = +0.2636R at **1.73 SE clustered fails the 2-SE bar**; the tally is **4 of 7 survived, not 5 of 7** (§4). |
| I4 | §3.4's "209 profitable HIGH-vol trades" (+0.0624 ± 0.0654 = 0.95 SE) and "better than LOW-vol" (0.82 SE) are asserted above their evidence | Accepted; relabelled HYPOTHESIS with SEs (§3.4). |
| I5 | "Stacking H6 on H13 destroys the result" is not like-for-like (the stacked set is a 163-of-212 subset) | Accepted; restated as "no support for stacking" (§3.4). |
| I6 | Design-effect figures mutually inconsistent (1.9× / 1.87× / implied 2.20×) and the clustering scheme is never named | Accepted. **FACT:** `v4_regime_vol_stationarity.md:257-259` labels 1.87 "deff" but computes it as an **SE ratio** (0.0871/0.0467 = 1.865); `clustered_bootstrap_all.md:142` gives v4 a month-block **variance** deff of 4.86 (SE ratio 2.20). §3 now names the convention and the scheme. |
| I7 | "Both distinct populations" is near-tautological (snapshot 2 = snapshot 3 + META) | Accepted (§3, §4). |
| I8 | The spread table applies a flat 0.028R reference to a skewed realised-risk distribution | Accepted, and it strengthens the conclusion (§8). |
| I9 | §3.3's KEEP exit mix omits one `eod` trade (385+172+153+1 = 711) | Accepted (§3.3). |

**exits/risk — legitimacy judge**

| # | Defect | Verification |
|---|---|---|
| E1 | **The motivating statistic is circular**: the partition variable (realised `risk_per_share`) is the denominator of `pnl_r` | **CONFIRMED by my own read-only re-run.** On a denominator that does not contain the partition variable (`2 × ATR(14)` at the signal bar, identical for both arms): pre-sealed diff **−0.1190 ± 0.0742, t = −1.60**; OOS **−0.1863 ± 0.0975, t = −1.91**. Both under 2 SE. The claim "the only exits-and-risk effect with ≥ 2 SE support" is false. |
| E2 | F1 is pre-determined to fail; the invariant ceiling is computable now | **CONFIRMED:** zeroing the tail's entire excess at the fixed denominator is worth **+0.00786R pre-sealed / +0.01387R OOS**, against F1's own ≥ +0.03R bar. |
| E3 | §11's ceiling is quoted in the as-run denominator; V1's own ceiling is worse | **CONFIRMED:** −0.0328R ± 0.0252 pre-sealed / −0.0345R ± 0.0442 OOS at the λ=1 denominator. |
| E4 | Gate-7's bar uses v0.1.0's dispersion | **CONFIRMED:** λ=1 per-trade sd is **0.7521** (pre-sealed), so the gate-7 bar for V1 is `0.719 × 0.7521 / √110.76 = +0.0514R`, not +0.0596R. |
| E5 | V2's guard is sign-blind, so the inverted-stop class is not closed by construction | **FACT, re-verified:** `engine.py:166-168` exits a LONG at `sig.stop_price` whenever `lo <= sig.stop_price`, with no requirement that the stop lie below the fill. |
| E6 | The same 23 trades are presented three times (OOS tail ≡ fold-4 tail ⊂ pre-sealed) | Accepted. |
| E7 | V2's "3 of 4 folds" rests on sign flips at 0.04 SE and 0.28 SE | Accepted. |
| E8 | R5 under-count: `v4_mfe_target.md:325-330` instructs that Finding 7 be counted as one unplanned hypothesis; `min_risk_atr = 1.0` is a threshold read off the partition it is motivated by | **FACT, re-verified** at `v4_mfe_target.md:325-330`. Both carried into §9. |
| E9 | The "2×/5× spread" labels do not match the engine arithmetic | Partially accepted — see §B.2(b). |

**exits/risk — impact judge**

| # | Defect | Verification |
|---|---|---|
| E10 | The λ=1 accounting delta carries no SE, yet the whole gate-3/4 band rests on it | Accepted, **and measured here for the first time**: paired per-trade delta = **+0.02137R, sd 0.3849, SE 0.01227 → 1.74 SE** pre-sealed; **+0.03534R, SE 0.01858 → 1.90 SE** OOS. The judge's estimate of 2.0–2.7 SE was optimistic; the central quantity is **under 2 SE on both cuts**. |
| E11 | Gate 4's required-n table uses v0.1.0's sd for a variant that changes the denominator | Accepted. **Measured:** λ=1 OOS sd = **0.7296**, so the gate-4 bar at n = 309 is **+0.1013R**, not +0.1115R. |
| E12 | The live signal path is not covered: `scan.py` publishes and sizes off `sig.stop_price` | **FACT, re-verified:** `scan.py:367-368` (reward/risk), `:415` (sizing) → `risk/engine.py:70` `per_share_risk = abs(entry_price − stop_price)`, `:444` `invalidation_level`. See §B.2(c) for the one wording I reject. |
| E13 | F3's "while folds 1/3 deteriorate" has an unstated quantifier and already triggers under one reading | Accepted (§4). |
| E14 | 27 of 81 grid cells sit at λ = 0 (v0.1.0 behaviour), capping the attainable positive fraction | Partially accepted — see §B.2(d). |
| E15 | §1's "the entry deliberately selects the days on which the gap distribution is fattest" is unmeasured | Accepted; relabelled HYPOTHESIS (§1). |
| E16 | The gate-3 forecast band is one-sided while the text calls the behaviour term's sign unknown | Accepted (§5). |
| E17 | "Within 0.1 SE on every cell" is 0.16 SE; snapshot coverage is effectively one gate-8-clean snapshot | Accepted (§3). |

**universe/breadth — legitimacy judge**

| # | Defect | Verification |
|---|---|---|
| U1 | Every number labelled "Measured: v0.2.0 rule" is a **post-hoc partition** of v0.1.0's trades, not a backtest of the rule; `engine.py:149` (`t = exit_idx + 1`) makes the two differ | **CONFIRMED EXACTLY by my own re-simulation.** True values at `frac ≤ 0.125`, snapshot 3: n = **308** (not 312), pre-sealed **+0.01402 ± 0.04518**, OOS **142 / −0.03347 ± 0.06844**, folds **−0.0398/70, +0.2040/55, −0.1060/68, +0.0269/115**, gate 6 **bull 201 / bear 6 / range 75 / unbucketed 26**, Sharpe **+0.104**. Every one of the judge's replacement figures reproduces. |
| U2 | The gate-1 fragility argument rests on a misstated margin (+0.0102R) | **CONFIRMED:** the true F4 margin is **+0.0269R on n = 115**, 2.6× the claimed figure. The "flips to 1/4 at both adjacent grid values" claim was produced the same wrong way and is withdrawn. |
| U3 | `EXTREME_Z = −2.0` and the breadth z-lookback are new parameters kept off the gate-5 grid — a §4.2 item 6 violation, and precisely the "decisive new parameter" failure mode §0.5 names | Accepted. Reclassifying a tunable as a module constant is not compliance. 3×3×3×3 = 81 ≤ 120, so it is feasible. |
| U4 | 0.08 and 0.20 are also selection-informed (they are rows of the already-seen sweep) | Accepted; the neighbour fraction is **not** an independent robustness statistic on snapshot 3. |
| U5 | F1–F4 are defined only on a single W1 snapshot, so R10 is unmet for the killers | Accepted (§4). |
| U6 | Panel membership is filtered by `len(series) >= min_bars` over the **whole run window**, so denominator membership uses end-of-sample information | Accepted. Inert on snapshot 3 (verified: denominator 23–24, median 24, across all 2,214 pre-sealed sessions), live on 150 heterogeneous names. |
| U7 | Gate 5 was left as a forecast when it is cheap and decisive | **CONFIRMED by my own 27-point read-only grid (107 s):** **0 of 27 positive, 0 of 6 neighbours, worst −0.2679**, every cell ≥ 23 OOS trades so nothing is dropped from `evaluable`. |
| U8 | The no-op check records partition counts, not rule counts | **CONFIRMED:** true OOS counts across the axis are **75 / 142 / 179**. The axis is genuinely live; the recorded numbers were wrong. |
| U9 | Gate 10 is `health_monitor.enabled` and passes unconditionally, so a fail-closed v0.2.0 that emits zero live signals could still reach PAPER_APPROVED | **FACT, re-verified** (eval 34 gate-10 evidence; `scan.py:269-272` constructs `StrategyContext(regime=…, allow_short=…)` with no breadth). This is a promotion-integrity hole, not a disclosure item, and it is decisive against the angle. |

**universe/breadth — impact judge**

| # | Defect | Verification |
|---|---|---|
| U10 | F1 is calibrated to **day** clustering — the narrowest calendar block — while the diagnostic names calendar **month** the appropriate instrument | **FACT, re-verified:** `clustered_bootstrap_all.md:204` gives v4 iid −0.1739, day −0.2619 (G=152), week −0.2836 (G=100), **month −0.2901 (G=35)**, symbol −0.1569; `:289-294` names cluster-by-calendar-block the appropriate instrument and warns that symbol clustering is invalid. Accepted, and applied to **every** clustered figure in this document (§3, §4). |
| U11 | The gate-6 bear forecast (5 × 6.25 ≈ 31) ignores the multiplier range and an anti-correlation | **FACT, re-verified:** `w1_universe_preregistration.md:307-314` gives realised multipliers as low as 2.83–3.33×. At 3× the bear bucket is ~18 from the corrected base of 6; at 2× it is ~12. Accepted. |
| U12 | The spread table applies a flat 0.028R rather than each trade's own risk unit | Accepted (§8). Consistent with my own measurement: median ATR/price at these entries is 1.62%, so the reference figure understates cost by ~22%. |
| U13 | §2.2 / §7 / checklist item 6 contradict each other on panel membership | Accepted (same surface as U6). |
| U14 | The 6.25× multiplier is applied to the **retention rate** as well as the trade count | Accepted. |
| U15 | "deff 1.87 → variance ×3.5" states the opposite of the (correct) arithmetic that follows | Accepted (same convention fix as I6). |
| U16 | 57 sessions (2.57%) have k ≥ 8; 53 of them (2.39%) carried the 480 trades — the two are conflated | Accepted. |

### B.2 Rejected or partially rejected, with reasons

**(a) Gate-4 required n "moved in the favourable direction" (signal/regime L5) — partially rejected.**
The requirement to report both figures is accepted and applied. I reject the implication
that using the measured sd was an error. MAP §0.3's 0.807 is a **bootstrap-inverted
approximation of the unfiltered v0.1.0 OOS sample** — the wrong dispersion for a filtered
variant whose measured OOS sd is 0.7324. The faithful figure is the measured one. Both are
reported (**6,894** at sd 0.7324; **8,370** at sd 0.807), and both are 22–27× the available
212 trades, so nothing turns on it.

**(b) The "2×/5× spread" labelling (exits/risk E9; universe/breadth U6-analogue) — partially rejected.**
The arithmetic the judges give is right: FACT (`engine.py:94`) round trip
`= 2 × (3.0 + spread_bps/2)`, so a 26 bps round trip implies `spread_bps = 20` — **4×** the
modelled 5.0, not 2×. But the proposals were **complying with a binding instruction**: MAP
§4.2 item 8 requires "the result at **2× and 5× the modelled spread** (26 and 66 bps round
trip)", and MAP §0.4 itself glosses 26 bps as "an assumed 20 bps quoted spread". The
mislabelling is the map's, not the proposals'. I therefore reject this as a defect in the
proposals and accept it only as a **disclosure requirement**: state the round trip, the
implied `spread_bps`, and the multiple of the modelled quoted spread together (§8), and
raise the map's inconsistency with the operator (§14).

**(c) "V1 cannot be executed as modelled" (exits/risk E12) — partially rejected.**
The finding is real and important: the live candidate path would publish and size off the
stale signal-bar stop while the backtest used a fill-anchored one. But the wording
overstates it. The backtest is internally consistent and free of lookahead; what exists is
a **research/live divergence** — structurally the same defect the breadth proposal
discloses as its own bias 3 — which must be closed before any live use and which does not
make the backtest invalid. Recorded as a divergence, and as a release gate on P1 (§13).

**(d) "Gate 5 is structurally near-unpassable at 66.7%" (exits/risk E14) — partially rejected.**
The arithmetic (27 of 81 cells at λ = 0; max attainable positive fraction 54/81 = 66.7%) is
correct **only conditional on all 27 λ=0 cells being negative**, and that is an assumption,
not a measurement: the λ=0 plane is 9 (`z_entry` × `stop_atr`) × 3 (`time_stop_bars`), and
MAP §0.5 records `time_stop_bars` as one of the four parameters gate 5 has **never** tested
for this strategy. The requirement to state the arithmetic is accepted; the framing
"structurally near-unpassable" is a HYPOTHESIS resting on an untested plane and is not
carried forward as fact.

**(e) "§0's sentence is false" (signal/regime L4) — accepted in substance, rejected in
degree.** §9 paraphrases a sealed fact rather than quoting a figure. R1's disclosure clause
covers arguments, not only figures, so the inline marking is required and is applied here —
but "false" overstates a wording slip.

**(f) "The declared budget was exceeded" (signal/regime L3) — accepted in substance,
rejected in framing.** The stacked `Vol.LOW ∧ r63 ≥ 0` check was computed to **warn a
synthesiser off** a combination, which is a robustness check, not a shipping candidate.
R5 nonetheless requires every evaluated variant with a reported OOS number to be in the
ledger, so it is recorded as variant 3 and the budget is restated as **2 declared, 3
evaluated** (§9). No bad faith is implied.

### B.3 One defect neither proposer nor any judge found (new here)

**The H13 headline straddles the 2-SE line on a definitional choice.** The proposal, and
both its judges, measure the KEEP/DROP difference on the strict `r63 < 0` partition
(271 trades) and get **+0.3038R at 2.005 SE clustered** — which I reproduce to three
decimals. But the *shipped rule* is fail-closed: it also blocks the two trades whose
`market_ret_63d` is `None`. Measured against the complement the rule actually blocks
(273 trades), the difference is **+0.2963R at 1.96 SE clustered — below the 2-SE bar.**
FACT: both blocked warmup trades are winners (+0.892R, +0.585R), which is why including
them shrinks the gap. Under month-block clustering — the instrument
`clustered_bootstrap_all.md:289-294` names as appropriate, and which for v4 is wider than
day clustering at every measured point — it would fall further (HYPOTHESIS).

**Consequence:** H13's "clears 2 SE" is an artefact of choosing the more generous of two
defensible partitions and the narrower of several defensible clustering blocks. It is not a
2-SE effect. This alone would have sent the angle to the null option.

---

## C. Independent verification log

All computation below was run by this synthesizer, **read-only**, against
`data/signalforge.sqlite` through
`sqlite+pysqlite:///file:…/data/signalforge.sqlite?mode=ro&uri=true`, driving
`PriceSeries.load`, `research.regime.regime_lookup`,
`research.backtest_runner.run_strategy_over_universe`, `backtest.regime.label_regimes`
and `research.portfolio_metrics.compute_portfolio_metrics` — none of which contains
`session.add` / `flush` / `commit`. **No write of any kind reached the database; no scratch
copy was needed; no file under `src/` or `tests/` was modified; no package was installed;
no provider API was called; the live paper-probation worker was not touched.**
Candidate rules were re-simulated with wrapper strategy objects constructed in the analysis
process only. Span: snapshot 3 (`universe_24_ex_meta`), `2016-09-10 .. 2025-09-07`,
source `massive`, proxy `SPY`, `min_bars = 60`, `CostModel()` defaults.
**No sealed bar was read. Zero sealed looks consumed.**

### C.1 Baseline reproduction (this licenses everything else)

| Quantity | Recomputed | Recorded (eval 34) |
|---|---|---|
| pre-sealed trades / expectancy | **984 / −0.062063R** (sd 0.8725, SE 0.0278) | 984 / −0.0621R |
| OOS trades / expectancy | **309 / −0.083739R** (sd 0.8202, SE 0.0467) | 309 / −0.0837R (gates 2, 3) |
| sealed ledger, version 4 | ids **3 / 8 / 13 / 18**, snapshots 1/2/3/4, `+0.1230 / +0.1230 / +0.1278 / +0.1230`, all `passed` | MAP §0.1 |
| spec hashes | v2 `2ed97431…f382`, v5 `dfe696b6…6f6c32`, v4 `5e6e9613…7854` | evals 32 / 35 / 34 |

### C.2 Exits/risk — the anchor mechanism, measured both ways

| Partition on realised risk | denominator | tail n / exp ± SE | rest n / exp ± SE | difference | **t** |
|---|---|---|---|---|---|
| pre-sealed | **as run** (`\|fill − stale stop\|`) | 65 / −0.6710 ± 0.2141 | 919 / −0.0190 ± 0.0251 | −0.6520 ± 0.2156 | **−3.02** |
| OOS | as run | 23 / −0.8600 ± 0.2360 | 286 / −0.0213 ± 0.0449 | −0.8387 ± 0.2402 | **−3.49** |
| pre-sealed | **fixed** (`2 × ATR(14)` at signal bar) | 65 / −0.1518 ± 0.0698 | 919 / −0.0328 ± 0.0252 | −0.1190 ± 0.0742 | **−1.60** |
| OOS | fixed | 23 / −0.2208 ± 0.0869 | 286 / −0.0345 ± 0.0442 | −0.1863 ± 0.0975 | **−1.91** |

The as-run rows reproduce the proposal and diagnostic Finding 7 exactly; the fixed-denominator
rows are the same partition measured on a denominator that does not contain the partition
variable. **Under MAP §4.2 item 3 the mechanism has no qualifying pre-sealed evidence.**

Derived quantities (all FACT, this run):

| Quantity | pre-sealed | OOS |
|---|---|---|
| λ=1 accounting-only expectancy | **−0.040690R** | **−0.048402R** |
| paired per-trade (λ=1 − as run) | **+0.021373 ± 0.012271 → 1.74 SE** | **+0.035337 ± 0.018577 → 1.90 SE** |
| per-trade sd at λ=1 | **0.7521** | **0.7296** |
| **ceiling**: tail set to the non-tail mean, fixed denominator | −0.040690 → −0.032828, **gain +0.00786R** | −0.048402 → −0.034535, **gain +0.01387R** |
| median realised risk unit | **2.1272 ATR** (design intends 2.000) | — |
| `stop` exits booked as wins | **4** | — |

**F1's own bar is ≥ +0.03R on the invariant measure. The ceiling is +0.0079R / +0.0139R. The
primary variant fails its own kill test by a factor of 2–4 before it is run.**

### C.3 Signal/regime — H13, and the partition that decides it

| Partition | n | expectancy | se_iid | **se_cl (signal date)** |
|---|---|---|---|---|
| KEEP `r63 ≥ 0` | **711** | **+0.020145R** | 0.02976 | 0.05913 |
| DROP, strict `r63 < 0` | 271 | −0.283653R | 0.06182 | — |
| DROP, **rule complement** (`r63 < 0` **or** `None`) | 273 | −0.276164R | 0.06182 | 0.13900 |

| Difference | value | iid | **clustered** |
|---|---|---|---|
| strict (the proposal's, and both judges') | **+0.303798R** | 4.42 SE | **2.005 SE** |
| rule complement (what the fail-closed rule blocks) | **+0.296309R** | 4.32 SE | **1.96 SE** |

FACT: the two `None` trades are both winners (+0.892R, +0.585R). §B.3 states the consequence.

**Re-simulation at the threshold (`market_ret_63d ≥ 0.0`), snapshot 3** — and here the
partition/re-simulation identity **does** hold: the re-simulated set is 711 trades, equal to
the KEEP partition of the baseline 984:

| Gate quantity | value |
|---|---|
| pre-sealed trades / expectancy | 711 / **+0.020145R** ± 0.0298 |
| OOS trades / expectancy | **212 / +0.037289R ± 0.050302** (sd 0.7324) |
| gate-1 folds (boundaries reproduce eval 34 exactly) | 173 / **+0.0696**, 208 / −0.0842, 140 / **+0.0890**, 190 / **+0.0386** → **3 of 4** |
| gate-6 buckets | bull **559** (357 low-vol + 202 high-vol) / **bear 2** / range **92**; **unbucketed 58** |
| gate-7 Sharpe (all pre-sealed) | **+0.226** vs SPY **+0.719** |

### C.4 Universe/breadth — the rule, re-simulated rather than partitioned

Breadth panel (point-in-time, per date, `zscore_last_return(·,·,20) ≤ −2.0`): **2,214**
pre-sealed sessions, member count min **23** / median **24** / max **24**.

| Quantity | post-hoc partition (proposal) | **re-simulated rule (this run)** |
|---|---|---|
| pre-sealed n / expectancy | 312 / +0.0048R | **308 / +0.014022R ± 0.045185** |
| OOS n / expectancy | 142 / −0.0335R | **142 / −0.033466R ± 0.068444** (sd 0.8156) |
| gate-1 folds | −0.0410/78, +0.1848/54, −0.0930/69, **+0.0102**/111 | **−0.0398/70, +0.2040/55, −0.1060/68, +0.0269/115** → 2 of 4 |
| gate-6 buckets | bull 202 / bear 5 / range 73; unbucketed 32 | **bull 201 / bear 6 / range 75; unbucketed 26 (8.4%)** |
| gate-7 Sharpe | +0.036 | **+0.104** vs SPY +0.719 |

Breadth gradient, computed on baseline trades at `frac ≤ 0.125` vs `> 0.125`:
301 / +0.00781R vs 683 / −0.09286R, difference **+0.10067R**, se_iid 0.05746 → **1.75 SE**,
se_cl (signal date) 0.09879 → **1.02 SE**. Under month blocks it would be lower still
(HYPOTHESIS, per `clustered_bootstrap_all.md:204`).

### C.5 Gate 5 — both 27-point grids, actually run

Replicating `sensitivity.py`'s enumeration, its `n_trades >= 15` `evaluable` filter, and its
`_is_neighbour` definition (`:99-112`, differs on exactly one axis by one step):

| Grid | evaluable | positive | neighbours positive | min cell n | worst cell | gate 5 |
|---|---|---|---|---|---|---|
| H13: `z_entry × stop_atr × market_ret_63d_min` (27 pts) | 27/27 | **15/27 = 55.6%** | **4/6 = 66.7%** | 76 | −0.0662 | **FAIL** |
| — same v0.2.0 under the **legacy 2-axis** grid (new axis pinned at 0.0) | 9/9 | **8/9 = 88.9%** | **3/4 = 0.750** | 89 | −0.0033 | **PASS**, at the exact `nb_frac < min` knife-edge (`sensitivity.py:194`) |
| Breadth: `z_entry × stop_atr × breadth_max_frac` (27 pts) | 27/27 | **0/27 = 0.0%** | **0/6 = 0%** | 23 | −0.2679 | **FAIL** |

**The middle row is MAP §0.5's hidden-fragility warning demonstrated live, and independently
reproduced here.** Shipping the H13 v0.2.0 without amending the grid would have converted
v4's most emphatic failure (0/9, 0%) into an 88.9% pass, on a strategy whose robustness had
got worse. This is the evidentiary basis for P2 (§14).

---

# The eleven required sections (MAP §4.2), for the chosen design

## 1. Mechanism

**The chosen design has no market mechanism, because it makes no market claim.** Its claim
is evidentiary: *after three independent mechanism-motivated angles, ten distinct variants
and levers (§9), and a full read-only re-measurement, `mean_reversion.short_swing` has no
pre-sealed edge that survives the program's own 2-SE bar, and the two gates that bind it
(4 and 7) are point-estimate gates that none of the surviving mechanisms moves.*

What the record establishes about the *market*, stated as findings rather than as a design:

1. **FACT.** v4's OOS −0.0837R is **−0.96 SE** from zero under signal-date clustering
   (`v4_regime_vol_stationarity.md:259`) and further from significance under month blocks.
   **v4 has no measurable edge; it is not a measured loss.** Any future claim to have "fixed
   a 0.08R deficit" would be a claim to have fixed noise.
2. **FACT.** The existing `Trend.BEAR` guard never binds: across all 984 snapshot-3
   pre-sealed trades the strategy takes **zero** BEAR-labelled entries. The guard is a
   crossover label that needs months of damage before it turns.
3. **Established, and insufficient (H13).** Conditioning on the proxy's trailing 63-session
   return separates the population strongly — but see §3 for the corrected magnitude — and
   the separation is *the same quantity gate 6 demands coverage of*. §5.4.
4. **Established as a correctness defect, not an edge (the risk-unit anchor).** The stop is
   fixed from the signal-bar close while the fill happens at the next open, so the realised
   risk unit is randomised by the overnight gap: median **2.1272 ATR** against an intended
   2.000, four `stop` exits booked as **wins**, and one trade rendering 5.5 bps of slippage
   as **−3.099R** off a 2.9-cent risk unit. HYPOTHESIS (relabelled per E15): that the entry
   rule *selects* the fattest-tailed gap days is asserted, not measured; no signal-day vs
   unconditional gap comparison exists.
5. **Measured and closed (H7).** On this universe a cross-sectional breadth statistic is
   degenerate: FACT, mean k = **10.90** on the 81 sessions where SPY itself is at z ≤ −2.0
   versus **0.36** elsewhere; corr(ETF-breadth, single-name-breadth) = 0.752. FACT (corrected
   per U16): **57 sessions (2.57%)** have k ≥ 8, and **53 of them (2.39%)** carried **480 of
   the 984 trades (48.8%)**.

Hypotheses addressed: **H6 refuted**, **H9 refuted** (the trigger is self-normalising by
construction), **H8 surviving only as a much weaker claim** with three of four component
parts refuted, **H7 measured and sub-2-SE**, **H13 established and insufficient**.

## 2. Exact change

### 2.1 To `mean_reversion.short_swing`: **none**

No file under `src/signalforge/research/strategies/` is touched. `VERSION` stays `"0.1.0"`.
No `MeanReversionParams` field is added or changed. No `StrategyVersion` row is created, so
no gate 9 is computed and no sealed look is consumed. Version 4 remains **EXPERIMENTAL**.

### 2.2 To `promotion.py`: **none**

Specifically, the `_sensitivity_plan` grid at `promotion.py:189-197` is **left exactly as it
is**. This reverses the "worth doing regardless of disposition" recommendation in the
signal/regime proposal §11, for the verified reason in L2: with v0.1.0 still registered under
the key `mean_reversion.short_swing`, adding `market_ret_63d_min` to that grid makes
`_replace(base, **p)` raise `TypeError` on the first grid point and gate 5 crashes rather
than runs. The integrity principle it was trying to serve is real and is carried as **P2**
(§14) with its stated prerequisite.

### 2.3 Files this design does write

| Path | Content |
|---|---|
| `docs/research/designs/mean_reversion_short_swing.md` | this document |
| `reports/mean_reversion.short_swing-0.1.0-does-not-pass.md` | the §11 disposition record, written in the integrate phase |

### 2.4 The two separable items, specified exactly but **not** authorised here

Both are put to the operator in §14 and neither is a `mean_reversion` change.

**P1 — engine risk-unit correctness fix.** `src/signalforge/backtest/engine.py`:
`EntrySignal` (`:29-41`) gains `stop_distance: float | None = None` and
`stop_anchor_blend: float = 0.0`; `run_backtest` computes
`stop_level = (1−λ)·sig.stop_price + λ·(entry_fill − d·sig.stop_distance)` after the fill
(`:107-116`); `_resolve_exit` (`:154-184`) takes `stop_level` in place of reading
`sig.stop_price` at `:166,:167,:169,:170`. Defaults are byte-identical to today
(`λ = 0.0` reproduces current behaviour exactly), **no strategy opts in**, and **no strategy
`VERSION` is bumped**. Two corrections to the proposal are mandatory: (i) a guard must be
*directional*, `d·(entry_fill − stop_level) > 0`, because `abs(...)` is sign-blind and does
not close the inverted-stop class (E5); (ii) the live path
(`scan.py:367-368, :415, :444` → `risk/engine.py:70`) must either be brought into
consistency or the divergence explicitly recorded (E12, and §B.2(c)).

**P2 — gate-5 axis integrity rule.** A standing rule, not an edit: *every parameter a
v0.2.0 introduces becomes a pre-registered gate-5 axis in the same change*. Its prerequisite
is the declared-axis mechanism of `pipeline_hardening_spec.md` §2 (an optional
`sensitivity_axes()` on the strategy class, merged into `_sensitivity_plan`, **never** a
`StrategySpec` field, which would move every `spec_json_hash` and unscope both live
approvals). Evidence: §C.5.

## 3. Pre-sealed evidence, with standard errors

**Conventions, fixed here and used throughout** (I6, U15, U10):
"deff" means the **variance** inflation factor; the SE ratio is its square root. Unless a
row says otherwise, `se_cl` clusters on the **calendar signal date**. FACT: for v4 that
scheme gives an SE ratio of **2.20×** on the all-pre-sealed H13 contrast
(0.1515 / 0.0686) — while `v4_regime_vol_stationarity.md:259`'s "deff 1.87" is itself an
SE ratio (0.0871 / 0.0467), and `clustered_bootstrap_all.md:142` gives v4 a month-block
variance deff of **4.86** (SE ratio 2.20). Signal-date clustering is **not** among the three
schemes that diagnostic ran, and `:204` shows v4's bound widening monotonically
iid → day → week → month, so **every clustered figure below is a lower bound on the
correction required**.

**Snapshot coverage, stated honestly** (I7, E17, U5). "All four snapshots" is **four labels
over two samples**: snapshot 4 loads 24 symbols because `META_CONT` carries source
`continuity_bridge:1` and returns nothing under `source="massive"`, so snapshot 4 ≡
snapshot 3; snapshot 1 differs from snapshot 2 by one calendar day that changes no trade.
Snapshot 2 = snapshot 3 + META (24 of 25 symbols, 982 of 997 trades in common), so
cross-snapshot agreement is a **META-sensitivity check**, not replication. And snapshot 3 is
the **only** snapshot on which gate 8 passes for any version. All motivating evidence
therefore rests on **one gate-8-clean snapshot**.

### 3.1 Baseline (§C.1)

984 pre-sealed / −0.062063R (sd 0.8725); 309 OOS / −0.083739R (sd 0.8202, SE 0.0467,
**−0.96 SE clustered**).

### 3.2 H13 — the strongest effect found, and why it is not evidence

| measure | difference | iid | **clustered (signal date)** |
|---|---|---|---|
| strict `r63 ≥ 0` vs `r63 < 0` | +0.303798R | 4.42 SE | **2.005 SE** |
| vs the complement the fail-closed rule blocks | +0.296309R | 4.32 SE | **1.96 SE** |
| ex-fold-2 (proposal-reported) | +0.2636R | 3.52 SE | **1.73 SE** |

Calibration against the two mechanisms this angle was nominated for: H6 `Vol.LOW` vs `HIGH`
= +0.1491R at **1.14 SE clustered**, collapsing to +0.0106R / 0.16 SE ex-F2; H9 refuted by
construction. H13 is much the strongest — and it still does not robustly clear 2 SE (§B.3),
its ex-F2 figure **fails** the 2-SE bar the document applies elsewhere (I3), and its
threshold `x = 0.0` is the maximum of the all-pre-sealed column (the proposer's own
disclosed red flag).

FACT: all four folds agree in sign (+0.1797 / +0.3849 / +0.2003 / +0.4116) — the test H6
failed.

### 3.3 Mechanism corroboration for H13 (independent of the expectancy split)

FACT (snapshot 3): the collapsed-risk tail is **2.9× denser** in the DROP set (12.55%, mean
−1.3592R) than in KEEP (4.36%, mean +0.0839R). Exit mix, **corrected for the missing `eod`
trade** (I9): KEEP = target 385 (54.1%) / stop 172 (24.2%) / time_stop 153 (21.5%) / **eod 1
(0.1%)** = 711; DROP = target 57 (21.0%) / stop 115 (42.4%) / time_stop 99 (36.5%) = 271.

### 3.4 H13 versus H6 — corrected (I4, I5)

| | `r63 ≥ 0` | `r63 < 0` | within-vol difference |
|---|---|---|---|
| `Vol.HIGH` | n=209, +0.0624R ± 0.0654 | n=204, −0.3647R ± 0.0729 | +0.4271R, 4.36 SE iid / **1.84 SE clustered** |
| `Vol.LOW` | n=502, +0.0026R ± 0.0322 | n=67, −0.0369R ± 0.1128 | +0.0395R, 0.34 SE |

**HYPOTHESIS, not FACT** (corrected): "HIGH-vol `r63 ≥ 0` trades are profitable" is
+0.0624 ± 0.0654 = **0.95 SE** from zero; "better than LOW-vol trades" is a difference of
0.0598 ± 0.0729 = **0.82 SE**. Even the within-HIGH contrast is **1.84 SE clustered** — under
the bar. The cross-tabulation is *suggestive* that the vol label was a badly aligned proxy
for the quarterly-drawdown condition; it does not establish it.

**On stacking (corrected per I5):** `Vol.LOW ∧ r63 ≥ 0` earns −0.0740R OOS on 163 trades,
but that set is a 163-of-212 **subset** of H13's OOS set, so the comparison is not
like-for-like and the 49 excluded trades are never reported separately. The honest
statement is **"no support for stacking H6 on H13"**, not "stacking destroys the result".

### 3.5 The exits/risk mechanism (§C.2)

As-run t = −3.02 / −3.49 is **circular**. Invariant t = **−1.60 / −1.91**. Ceiling
**+0.0079R / +0.0139R**. Paired λ=1 accounting delta **1.74 SE / 1.90 SE**. Nothing here
clears 2 SE.

### 3.6 The breadth mechanism (§C.4)

Gradient **+0.10067R, 1.75 SE iid, 1.02 SE clustered**; non-monotone across single-name
counts (adjacent buckets swing 0.49R; the most idiosyncratic bucket k=1 is *worse* than
k=2–3); degenerate on this universe. The filtered rule earns +0.0140R pre-sealed and
−0.0335R OOS.

### 3.7 Refuted levers left alone (from the committed W2 diagnostics)

Tracking-SMA target Δ = **−0.0032R ± 0.0040** (0.8 SE, wrong sign); the 6-bar leash is a net
**positive** +0.0410R with 57.5% of leash exits profitable; target:stop ratio is 0.77:1, not
the ≈0.5:1 the map assumed; at MFE > 1R only 3.05% ± 0.55% of trades lose. Exit contribution
ledger: target **+0.2114R**, leash **+0.0410R**, stop **−0.3139R** — the entire deficit is
the stop bucket.

## 4. Falsification

### 4.1 What already fired (pre-registered before the runs, by the three proposers)

| Angle | Falsifier | Result |
|---|---|---|
| signal/regime | F-6: *the filtered strategy does not clear more gates than v0.1.0* | **FIRED** — v0.1.0 fails 3,4,5,7; v0.2.0 fails 4,5,6,7 |
| signal/regime | F-7: *the change breaks a gate v0.1.0 passes* | **FIRED** — gate-6 bear 46 → 2 against a floor of 10 |
| signal/regime | F-3: *the difference vanishes ex-F2* | **FIRED on the 2-SE bar** (1.73 SE clustered) — regraded per I3; tally **4 of 7 survived**, not 5 of 7 |
| exits/risk | F1: *paired invariant difference ≥ 2 SE and positive* | **FIRED** — the ceiling (+0.0079R) is below the bar (+0.03R); measured delta 1.74 SE |
| exits/risk | F2: *the effect must not live only in the 65-trade tail* | **FIRED** — invariant whole-sample difference is 1.60 SE |
| universe/breadth | F1: gradient < 2 SE clustered | **FIRED** — 1.02 SE (my re-measurement) |
| universe/breadth | F2: filtered OOS expectancy ≤ 0 | **FIRED** — −0.0335R |
| universe/breadth | F3: gate-6 bear bucket < 10 | **FIRED** — bear 6 (corrected from 5) |
| universe/breadth | F4: expectancy not weakly monotone in breadth | **FIRED** — non-monotone, 0.49R adjacent swings |

**Nine pre-registered kill conditions fired across three independent angles.** Under R10
that ends the matter.

### 4.2 Pre-registered **re-opening** criteria, fixed now, before any future run

The null option is a disposition, not a ban. v4 may be reopened **only** if *all* of the
following hold, on the stated snapshots, measured before any code is written. These are
binding and may not be renegotiated after a result is seen.

| # | Condition | Snapshot 3 (headline) | Snapshot 2 (META check) | W1 150-symbol, if built |
|---|---|---|---|---|
| **RO-1** | A mechanism-motivated conditioning variable separates pre-sealed expectancy by **≥ 2 SE on a calendar-MONTH block SE** (day and week reported alongside), and by ≥ 2 SE with fold 2 removed | required | required | required |
| **RO-2** | The rule's **re-simulated** (never partitioned) OOS expectancy is **> 0 and ≥ 2 SE above zero on the month-block measure** | required | required | required |
| **RO-3** | The re-simulated rule **breaks no gate v0.1.0 passes** — specifically gate 6's bear bucket stays **≥ 10** with the unbucketed count reported, and gate 1 stays ≥ 2 of 4 | required | required | required |
| **RO-4** | The full pre-registered gate-5 grid — **including every new parameter as an axis** — reaches ≥ 60% positive and ≥ 75% neighbours positive | required | reported | required |
| **RO-5** | The conditioning variable is **computable in the live scan path** (`scan.py:269`) over the live universe, or an operator decision to change that universe is already in hand | required | — | required |
| **RO-6** | The result survives the **2× and 5× spread** re-pricing required by MAP §4.2 item 8 with OOS expectancy still > 0 | required | — | required |

**Measured today, every candidate fails at least three of the six.** RO-1 fails for all three
angles even on the *narrower* day-clustered measure (H13 1.96–2.01, anchor 1.60/1.91, breadth
1.02). RO-3 fails for H13 (bear 2) and for breadth (bear 6). RO-4 fails for both grids
actually run (§C.5). RO-6 fails for H13 (+0.0003R at a 26 bps round trip) and for breadth
(negative at every priced point).

### 4.3 What would **not** reopen it

A better OOS number at a threshold outside a pre-registered grid; a gate-9 result of any
kind (R1, and see §10's standing warning); agreement between snapshots 2 and 3, which is a
META-sensitivity check; or any figure measured on a denominator containing the partition
variable.

## 5. Gate-by-gate forecast

Trade sets tagged per MAP §0.2: gates **2/3/4 OOS only**; gates **1/6/7 all pre-sealed**,
gate 7 included despite its docstring (`config/research.py:111-113` vs `promotion.py:775` —
the code is what runs; open item for the operator).

### 5.1 The chosen design

**The chosen design changes nothing, so every gate stays exactly as evaluation 34 recorded
it.** Version 4 remains NO TRADE, blocked on gates **3, 4, 5, 7**, with gate 6 passing at
bull 618 / bear 46 / range 260 and **60 unbucketed (6.1%)**, and gate 7 at Sharpe **−0.749**
vs SPY **+0.719** over all 984 pre-sealed trades. No new sealed test is created.

### 5.2 The three rejected candidates, measured (not estimated)

| Gate | set | v0.1.0 | H13 `r63 ≥ 0` | anchor V1 (λ=1) | breadth `frac ≤ 0.125` |
|---|---|---|---|---|---|
| 1 walk-forward (≥2 of 4) | all pre-sealed | 2/4 | **3/4** PASS | 2/4 (accounting only), fragile | 2/4, F4 margin **+0.0269R** |
| 2 OOS trades (≥30) | OOS | 309 | 212 PASS | ~300–320 PASS | 142 PASS |
| 3 net expectancy (>0) | OOS | −0.0837R **FAIL** | **+0.0373R ± 0.0503** PASS (0.60 SE clustered from zero) | **−0.048R** (two-sided band −0.07 … −0.01, per E16) **FAIL** | **−0.0335R** FAIL |
| 4 bootstrap CI low (>+0.02) | OOS | −0.1739 FAIL | −0.0568 **FAIL** | FAIL | FAIL |
| 5 sensitivity (≥60% / ≥75%) | OOS per cell | 0/9 = 0% FAIL | **15/27 = 55.6%, nbr 4/6 = 66.7% FAIL** | forecast FAIL (see §B.2(d) for the conditional ceiling) | **0/27 = 0%, nbr 0/6 FAIL** |
| 6 regime (≥10 each) | all pre-sealed | 618/**46**/260, unbuck 60 PASS | 559/**2**/92, unbuck 58 **PASS → FAIL** | ~unchanged PASS | 201/**6**/75, unbuck 26 **PASS → FAIL** |
| 7 benchmark Sharpe | all pre-sealed | −0.749 FAIL | **+0.226** FAIL (gap 0.492) | ≈ **−0.57** FAIL (at the variant's own sd 0.7521, per E4) | **+0.104** FAIL (gap 0.615) |
| 8 data/leakage | — | PASS (snap 3 only) | PASS | PASS | PASS **with zero coverage of the new surface** (§7) |

### 5.3 Gate 4 as a required n (mandatory per §4.2 item 5)

`n > (1.96·sd/(exp − 0.02))²`:

| Candidate | OOS exp | sd used | **required n** | has | multiple |
|---|---|---|---|---|---|
| H13, at the measured filtered sd | +0.0373R | 0.7324 | **6,894** | 212 | 32.5× |
| H13, at MAP §0.3's per-trade sd | +0.0373R | 0.807 | **8,370** | 212 | 39.5× |
| anchor V1 | negative | — | **never** | — | — |
| breadth | negative | — | **never** | — | — |
| v0.1.0 | negative | — | **never** | — | — |

FACT: W1's ≈6.25× breadth gives ≈1,325 OOS trades against a requirement of 6,894 — and
`w1_universe_preregistration.md:307-314` treats 6.25× as an **upper bound on an upper bound**,
with realised multipliers plausibly 2.83–3.33×. **Gate 4 fails powered.** All required-n
figures are **lower bounds** under clustering.

For the anchor variant specifically, the bar must be computed at its own dispersion (E11):
at λ=1 OOS sd = 0.7296 the gate-4 bar at n = 309 is **+0.1013R**, not the +0.1115R the
proposal quoted from v0.1.0's sd.

### 5.4 The structural finding that closes the market-direction lane

Swept across the full threshold range on both populations (proposal-reported; I re-ran only
`x = 0.00`): **gate 3 passes only for `x ≥ −0.01`; gate 6 passes only for `x ≤ −0.03`. The
admissible regions are disjoint.** The filter's content — *do not buy dips while the market's
quarter is down* — is very nearly the condition gate 6 demands ≥ 10 trades from. **Any v4
proposal conditioning on market direction hits this wall**, so the lane is *measured and
closed*, not untried.

**Zero-margin disclosure (mandatory, §4.2 item 5), corrected per I2:** on that frontier the
gate-6 bear bucket is **11 against a floor of 10** at both `x = −0.04` and `x = −0.03`, and
12/13 at −0.08/−0.06. The disjointness holds in direction (both gates fail at −0.02 and
−0.01 regardless), but the gate-6 boundary is located to **±1 trade** — the same magnitude as
the capacity-redeployment effect I1 demonstrates is present in the sweep.

### 5.5 All zero-margin cases carried forward

| Case | Value | Status under this design |
|---|---|---|
| v6 gate-5 neighbour fraction | exactly **0.750** on snapshot 3; already **0.500 FAIL** on snapshot 4 | untouched — nothing here is evaluated or re-run |
| v5 gate-6 bear bucket | **11** against a floor of 10 | untouched; v2/v5 are never evaluated on any new snapshot (R7b) |
| **new:** H13 v0.2.0 under the legacy 2-axis grid | neighbour fraction exactly **0.750** → PASS at the `nb_frac < min` knife-edge (`sensitivity.py:194`) | recorded as the evidence for P2 (§C.5) |
| **new:** H13 frontier gate-6 bear | **11** vs floor 10 at x = −0.04 and −0.03 | recorded (§5.4) |
| **new:** breadth gate-1 | 2 of 4 with F4 at **+0.0269R** (the proposal's +0.0102R was a partition artefact) | recorded, corrected |

## 6. Sensitivity-grid plan (pre-registered, before any run)

No grid runs under the chosen design. The following are **pre-registered now** and bind any
future reopening under §4.2 — fixed before results, not after.

| If this is ever revisited | Pre-registered gate-5 axes | Points | vs cap 120 |
|---|---|---|---|
| H13 market-direction filter | `z_entry [−2.5,−2.0,−1.5] × stop_atr [1.5,2.0,2.5] × market_ret_63d_min [−0.02, 0.0, +0.02]` | 27 | ✅ |
| Anchor/risk variant | `z_entry × stop_atr × time_stop_bars [4,6,8] × stop_anchor_blend [0.0,0.5,1.0]` (baseline 1.0 is an endpoint → **7** one-step neighbours, so ≥ 6 of 7 required) | 81 | ✅ |
| Breadth variant | `z_entry × stop_atr × breadth_max_frac [0.08,0.125,0.20] × EXTREME_Z [−2.5,−2.0,−1.5]` — **`EXTREME_Z` is an axis, not a module constant** (U3) | 81 | ✅ |
| Any two of the above combined | 5 axes × 3 = **243** | — | ❌ **exceeds the cap; cannot ship with a full neighbourhood (§A.2)** |

**The no-op check (§4.2 item 6) — performed, not promised.** Holding
`z_entry = −2.0, stop_atr = 2.0` and moving only the new axis (my run, §C.5):

| Axis | values | OOS n | OOS expectancy | live? |
|---|---|---|---|---|
| `market_ret_63d_min` | −0.02 / 0.00 / +0.02 | 225 / 212 / 179 | −0.0137 / +0.0373 / +0.0060 | **yes** |
| `breadth_max_frac` | 0.08 / 0.125 / 0.20 | **75 / 142 / 179** (corrected per U8) | −0.0636 / −0.0335 / −0.0451 | **yes** |

**Standing selection disclosure (U4).** For the breadth axis, **all three** values are
selection-informed on snapshot 3, not only the baseline: 0.08 and 0.20 correspond to rows of
a sweep the proposer had already seen. Its neighbour fraction is therefore **not** an
independent robustness statistic on this snapshot.

**Prerequisite for any of these (L2, P2).** `_sensitivity_plan` dispatches on
`key.startswith("mean_reversion")` and calls `_replace` on the instance's own params, so a
new axis cannot coexist with a registered v0.1.0. The declared-axis mechanism
(`pipeline_hardening_spec.md` §2) must ship first.

## 7. Leakage argument

**No new feature, no new plumbing, no shared-surface change is introduced by the chosen
design.** The following are recorded because they are findings about the *existing* surface
that survive the disposition and bind any future work.

1. **`assert_no_lookahead` cannot cover a cross-sectional term.** FACT
   (`backtest/leakage.py:14-16`): `FeatureFn = Callable[[PriceSeries, int], float]` — a
   single-series contract. A panel statistic has the wrong type and cannot be passed to the
   detector at all.
2. **Gate 8 would report "clean" with zero coverage of any new surface.** FACT
   (`promotion.py:249-268`, called at `:809` on the proxy symbol only): `_leakage_self_check`
   runs a hard-coded four features — `sma(50)`, `rolling_return(20)`, `atr(14)`,
   `realized_vol(20)`. It does not even check `zscore_last_return`, which v4 actually reads.
3. **Adding `rolling_return(63)` to that list would enforce nothing** (L7): `rolling_return`
   is window-parameterised with fixed `t`-relative offsets, so window 63 exercises the
   identical code path as the window 20 already listed. The surface with genuinely **zero**
   coverage is the regime layer: `regime_from_proxy` / `regime_lookup`
   (`regime.py:62-101`) is never passed to `assert_no_lookahead` anywhere in `src/`. A manual
   read finds no lookahead (all indices ≤ t; `sma(proxy, t−10, 200)` is backwards), so this
   is a **coverage gap, not a live leak** — recorded as such.
4. **The fail-closed convention depends on proxy coverage, not just warmup** (L6). FACT:
   `signal_fn_for` (`base.py:39-41`) falls back to `NEUTRAL` for **any** date absent from the
   regime map, and `NEUTRAL.market_ret_63d` is `None` (`regime.py:59`). A fail-closed
   `market_ret_63d` rule therefore suppresses entries wherever proxy bars are missing, not
   only during the 63-bar warmup. FACT: SPY's `massive` series on snapshot 3 spans
   2016-10-17 → 2025-09-05 (2,234 bars) against a 2016-09-10 span start; 2 of 984 trades are
   affected, both on 2017-01-17. That count is **snapshot-specific** and would have to be
   re-measured on any new snapshot.
5. **Panel membership would be a lookahead channel if a breadth term were ever built** (U6).
   The proposed `build_breadth_panel` is fed a `loaded` dict filtered by
   `len(series) >= min_bars` over the **whole run window**, so a symbol's presence in the
   date-`d` denominator depends on whether it eventually accumulates 60 bars. Inert on
   snapshot 3 (verified: denominator 23–24, median 24, across all 2,214 sessions); live on a
   150-name universe with heterogeneous listing history.
6. **The live/research divergences, recorded** (E12, U9, §B.2(c)). A fill-anchored stop is
   not represented anywhere on the live path: `scan.py:367-368` gates reward/risk on
   `sig.stop_price`, `:415` sizes off it via `risk/engine.py:70`, and `:444` publishes it as
   `invalidation_level` — a scalar with no representation for "stop = fill − 2×ATR". A
   breadth term is worse: `scan.py:269-272` passes no breadth, so a fail-closed v0.2.0 would
   emit **zero** live signals forever, and gate 10 (`health_monitor.enabled`) passes
   unconditionally — nothing in the ladder prevents a strategy that cannot trade from
   reaching PAPER_APPROVED. **That is a promotion-integrity hole and is raised with the
   operator in §14.**
7. **Walk-forward assumption preserved.** `walkforward.py` does not re-fit per fold, which is
   sound only while strategies fit nothing. Nothing here introduces a fitted quantity.

## 8. Cost-model statement (quantitative)

**The cost model is unchanged and untouched (R4).** FACT: `costs.py:11-16` —
`commission_per_share = 0.0`, `commission_min_per_order = 0.0`, `slippage_bps = 3.0`,
`half_spread_fill_penalty = True`; `engine.py:90` `spread_bps = 5.0`, never overridden by
`backtest_runner.py:205-206`; `engine.py:94` `slip = (3.0 + 5.0/2)/10,000 = 5.5 bps` per
side; `engine.py:143` **11.0 bps round trip**. `git status --porcelain src tests` is clean.

**Per-trade cost in R.** `stop_atr` is unchanged at 2.0, so at MAP §0.4's reference
ATR/price of 2% the cost is `11.0/10,000 ÷ 0.04 = ` **0.028R** — the lowest in the program.
**Corrected per I8/U12:** measured at these entries, ATR/price is **median 1.62% / mean
1.92%**, so the realised median cost is **0.0343R** (mean 0.0520R, max **8.19R** on the
collapsed-risk tail). MAP §0.4's 0.028R is a reference at an assumed ATR/price, not a
measurement, and it **understates** v4's realised cost by ~22% at the median.

**Turnover delta.** Zero — the chosen design changes nothing. For the record, the rejected
candidates: H13 cuts trades 984 → 711 (−27.7%) and turnover 110.8 → 80.0/yr with per-trade
cost unchanged; breadth cuts 984 → 308 (−68.7%) and turnover 110.8 → ~35/yr with per-trade
cost unchanged. Cost was never this strategy's problem — *and it is nonetheless decisive*,
see below.

**Spread sensitivity (MAP §4.2 item 8), with the labels disambiguated per §B.2(b).**
Round trip `= 2 × (3.0 + spread_bps/2)`:

| round trip | implied `spread_bps` | multiple of the modelled 5.0 quoted | cost/trade @ ATR/price 2% | **H13's OOS expectancy net of the increment** |
|---|---|---|---|---|
| 11.0 bps (baseline; already in every number above) | 5.0 | 1× | 0.028R | **+0.0373R** |
| **26 bps** — MAP §4.2 item 8's "2×" | 20.0 | **4×** | 0.065R | **+0.0003R** |
| 36 bps | 30.0 | 6× | 0.090R | −0.0247R |
| **66 bps** — MAP §4.2 item 8's "5×" | 60.0 | **12×** | 0.165R | **−0.0997R** |

**The single most decision-relevant cost finding for this strategy: the entire filtered edge
is smaller than one doubling of the assumed round trip.** At MAP's own "2×" column H13's OOS
expectancy is +0.0003R — indistinguishable from zero. Since W1's 150-name universe is
precisely where wider spreads live (§0.4: the flat 5 bps is universe-independent), *"expand
the universe to power this up"* is **self-defeating** for v4: breadth adds n while spread
removes the point estimate, and gate 4 needs the point estimate. Re-priced per trade from the
realised risk distribution rather than the flat reference, the conclusion strengthens.

**Unquantifiable bias, disclosed** (universe/breadth §8): an idiosyncratic −2σ day in one
name is plausibly when *that* name's quoted spread widens most, so a filter that retains
idiosyncratic dips may pay **more** spread than average. There is no quote data in this
database; recorded as an unmeasured downward bias on every filtered figure.

## 9. Variant budget and stopping rule — for the whole strategy, all angles combined

### 9.1 The complete R5 ledger

| # | Angle | Variant / lever | Status | Pre-sealed result |
|---|---|---|---|---|
| 1 | prior W2 | H6 `Vol.LOW` filter | refuted | +0.1491R diff, **1.14 SE clustered**; +0.0106R / 0.16 SE ex-F2; OOS −0.0754R |
| 2 | prior W2 | H8 tracking-SMA target | refuted | paired Δ **−0.0032R ± 0.0040** (wrong sign) |
| 3 | prior W2 | H8 leash lengthening | unmotivated | the 6-bar leash is a net **+0.0410R** |
| 4 | prior W2 | **unplanned** Finding-7 hypothesis (collapsed risk unit) — counted as `v4_mfe_target.md:325-330` instructs (E8) | carried into #6/#7 | 65 trades at −0.6710R as run; **−0.1190R / 1.60 SE invariant** |
| 5 | signal/regime | `market_ret_20d ≥ 0` | examined, rejected | +0.1265R diff, **1.10 SE clustered**; non-monotone quintiles; OOS +0.0736R |
| 6 | signal/regime | **`market_ret_63d ≥ 0` (H13)** | examined, **falsified** | diff +0.3038R / 2.005 SE (1.96 SE against the rule complement); OOS +0.0373R ± 0.0503; gates 4,5,6,7 fail |
| 7 | signal/regime | stacked `Vol.LOW ∧ r63 ≥ 0` (L3) | examined, rejected | OOS **−0.0740R**, n = 163 |
| 8 | exits/risk | V1 fill-anchored stop | **falsified before running** | invariant ceiling **+0.0079R** vs its own ≥ +0.03R bar |
| 9 | exits/risk | V2 minimum-risk guard (`min_risk_atr = 1.0` — a threshold read off the partition that motivates it, disclosed per E8) | falsified | same invariant evidence; guard is sign-blind (E5) |
| 10 | universe/breadth | breadth hard filter `frac ≤ 0.125` (one mechanism, five thresholds explored, one carried) | **falsified** | re-simulated 308 / +0.0140R; OOS 142 / −0.0335R; gate-6 bear 6; grid **0/27** |
| — | universe/breadth | V-U2 breadth-modulated `z_entry` | **never run** (its precondition — all four of V-U1's falsifiers surviving — failed) | — |

**Total: 10 distinct mechanism tests on version 4. Zero implemented. Zero sealed looks
consumed.** Declared budgets were 2 (signal/regime) + 2 (exits/risk) + 2 (universe/breadth)
= 6; **7 were evaluated in Phase 2** (#5–#10 plus the stacked check), and three prior
diagnostic levers precede them. This is the number that goes in the final report verbatim,
and it is the reason RO-1…RO-6 (§4.2) are set where they are: **a pass found after ten tries
would need to be very much stronger than a pass found on the first.**

### 9.2 Stopping rule (pre-registered by all three angles; it has fired)

> *Stop after the declared budget unless a variant produces a re-simulated pre-sealed OOS
> expectancy that is (i) positive and (ii) at least 2 SE above zero on the clustered measure,
> **without** breaking a gate v0.1.0 passes.*

Best candidate: H13, at **+0.0373R = 0.60 SE clustered** above zero, and it breaks gate 6.
**The rule fires. No third variant is attempted in any angle. The angle set is closed.**

### 9.3 Why the bar is raised here specifically

MAP §2.2 lever 5 records the asymmetry, and it is the single most important governance fact
about this strategy: *(sealed numbers used for **disposition** only, R1, marked inline)*
v4's gate 9 **already passes on all four snapshots** (+0.1230R to +0.1278R, PF 1.45–1.47) on
a calm, persistently bullish twelve months that is exactly the regime this dip-buy is built
for. A v0.2.0 that repaired gates 3/4/5/7 would inherit a friendly gate 9 that **cannot catch
an overfit**. The usual safety net at the end of the ladder is absent here, so the discipline
that protects the program is the stopping rule, not the ladder.

## 10. Sealed-look accounting

**Baseline: k = 5. Consumed by the design phase: 0. Planned: 0. The count stays at k = 5.**

FACT: no look counter exists anywhere in `src/signalforge` (grep for `second_look` /
`sealed_look` / `look_count` / `n_looks` returns nothing), so this disclosure is manual and
must be copied verbatim into the final report. The count is reconstructable only from
`strategy_sealed_test` — **20 rows, exactly 4 per version for versions 2–6**.

The §0.1 ledger, re-verified by read-only `SELECT` for this document:

| Ver | Strategy | snap 1 `universe_25_baseline_legacy` | snap 2 `universe_25_baseline` | snap 3 `universe_24_ex_meta` | snap 4 `universe_25_meta_continuity_corrected` |
|---|---|---|---|---|---|
| 2 | `trend_continuation.short_swing` | id 1: +0.3246R / 112 ✅ | id 6: +0.3246R / 112 ✅ | id 11: +0.2982R / 109 ✅ | id 16: +0.3246R / 112 ✅ |
| 3 | `trend_continuation.medium_swing` | id 2: +0.0109R / 98 ✅ | id 7: +0.0109R / 98 ✅ | id 12: −0.0294R / 95 ❌ | id 17: +0.0109R / 98 ✅ |
| **4** | **`mean_reversion.short_swing`** | **id 3: +0.1230R / 91 ✅** | **id 8: +0.1230R / 91 ✅** | **id 13: +0.1278R / 84 ✅** | **id 18: +0.1230R / 91 ✅** |
| 5 | `relative_strength.medium_swing` | id 4: +0.2935R / 16 ✅ | id 9: +0.2935R / 16 ✅ | id 14: +0.2935R / 16 ✅ | id 19: +0.2935R / 16 ✅ |
| 6 | `volatility_breakout.short_swing` | id 5: −0.0979R / 10 ❌ | id 10: −0.0979R / 10 ❌ | id 15: −0.0979R / 10 ❌ | id 20: −0.0979R / 10 ❌ |

*(Row 4 is reproduced because R2 requires the ledger in every report. Per R1 it is used only
for **disposition** — the argument in §9.3 — never for design, and that use is marked inline
there. No design choice in §§1–9 derives from any sealed number.)*

**What a hypothetical implementation would have cost.** FACT
(`db/models/research.py:263`): `StrategySealedTest` is unique per
`(strategy_version_id, dataset_snapshot_id)`, so any new `StrategyVersion` creates a fresh
sealed test. FACT (`promotion.py:838-844`, and eval 34 is itself proof — four gates failed
and the sealed test still ran): **gate 9 is computed unconditionally**, so a look is consumed
by *calling* `evaluate_promotion`, not by passing gates. Read-only screening via
`run_strategy_over_universe` / `run_parameter_sensitivity` consumes none. A v0.2.0 sealing on
snapshot 3 would be **look 6**; the same v0.2.0 evaluated on snapshot 3 **and** a W1 snapshot
would be looks **6 and 7**. A pass on look 6 must be reported as *"passed on look 6"*, never
unqualified.

**Convention clash, flagged for the operator, not silently resolved** (L8). MAP §0.1 and R2
say a v0.2.0 seal on snapshot 3 is "look 5"; MAP §4.2 item 10 and this synthesis brief say
baseline k = 5 → **look 6**; `pipeline_hardening_spec.md:538-545` adopts `k_prior = 4,
this_look = 5`. **This document uses k = 5 → look 6** (MAP §4.2 item 10 and the binding
brief). The operator should settle it once, before any counter ships.

**Pre-registered leading snapshot, per R1: snapshot 3.** Reason, fixed before any run and
independent of any outcome: FACT — gate 8 `data_quality_and_leakage` **fails on snapshots 1,
2 and 4 for every version** (snaps 1–2: META's 90 missing sessions; snap 4: `META_CONT`
carries `continuity_bridge:1`, re-confirmed here as 2,510 bridge bars and **zero** `massive`
bars), and passes only on snapshot 3. The choice is forced by a pre-sealed data-quality gate.
The other three sealed draws are disclosed alongside it in **every** report, as above.

**R3 staleness trap.** FACT (`persistence.py:46-93`): `upsert_strategy_version` refreshes
`spec_json` and `git_sha` on the *same row* when the version string is unchanged, so editing
`mean_reversion.py` without bumping `VERSION` would recompute gates 1–8 against new code
while gate 9 replays sealed test **id 13**, measured against the old code — a silently
invalid pass. **Because this design changes no strategy code, the trap is not engaged.** It
becomes a stop-ship check the moment P1 is approved (§13) or any v4 work reopens.

## 11. Null option — this **is** the design

The following is the disposition record. It is written in the integrate phase to
`reports/mean_reversion.short_swing-0.1.0-does-not-pass.md` and quoted verbatim in the final
program report.

> ### `mean_reversion.short_swing` v0.1.0 (version 4) — does not pass
>
> **Verdict: NO TRADE. Status stays EXPERIMENTAL. No v0.2.0 was written. Sealed looks
> consumed: 0; the count stays at k = 5.**
>
> **1 — What was tried.** Three independent design angles (signal quality/regime, exits and
> risk, universe breadth), **ten distinct mechanism tests** (§9.1), and a full read-only
> re-measurement by an independent synthesizer. **Nine pre-registered kill conditions fired.**
>
> **2 — The strategy has no measurable edge, and that is the honest headline.** Pre-sealed
> OOS expectancy is **−0.0837R**, which is **−0.96 SE from zero** once same-date clustering
> is respected — and further from significance under calendar-month blocks, the instrument
> `clustered_bootstrap_all.md:289-294` names as appropriate. **v4 has no measurable edge; it
> is not a measured loss.** Any future claim to have "fixed a 0.08R deficit" is a claim to
> have fixed noise.
>
> **3 — Every mechanism proposed falls below the program's own 2-SE bar once measured
> correctly.** H6 `Vol` filter 1.14 SE; `market_ret_20d` 1.10 SE; breadth **1.02 SE**; the
> risk-unit anchor **1.60 SE** pre-sealed / 1.91 SE OOS on a denominator that does not contain
> the partition variable (as-run t = −3.02 is circular); and the strongest, H13
> `market_ret_63d ≥ 0`, at **2.005 SE** on the strict partition but **1.96 SE** against the
> complement the shipped fail-closed rule would actually block.
>
> **4 — The two binding gates are point-estimate gates that no amount of data fixes.** Gate 4
> requires **6,894 OOS trades** at the best candidate's own dispersion (8,370 at the map's)
> against 212 available; W1's optimistic 6.25× breadth gives ≈1,325, and the realised
> multiplier may be as low as 2.83×. Gate 7 needs a Sharpe of **+0.719**; the best measured
> candidate reaches **+0.227**. Breadth cannot move a risk-adjusted point estimate at all.
>
> **5 — The best candidate trades one gate failure for another, and the trade is structural.**
> H13 flips gate 3 to pass (+0.0373R, 0.60 SE clustered from zero) and improves gate 7's
> Sharpe by +0.976 — while collapsing gate 6's bear bucket from **46 to 2** against a floor of
> 10. Swept across the full threshold range, **gate 3 passes only for x ≥ −0.01 and gate 6
> only for x ≤ −0.03: disjoint regions, on both populations.** The filter's content — *do not
> buy dips while the market's quarter is down* — is nearly the condition gate 6 demands
> evidence from. **The entire market-direction lane is measured and closed, not untried.**
>
> **6 — Sensitivity remains the decisive verdict, and it got worse, not better.** v0.1.0 is
> **0 of 9** grid points positive. The breadth v0.2.0 is **0 of 27, 0 of 6 neighbours**. The
> H13 v0.2.0 is **15 of 27 (55.6%), 4 of 6 neighbours (66.7%)** — still failing. And the
> legacy 2-axis grid would have scored that same H13 v0.2.0 at **88.9% / 0.750 = PASS**, at
> the exact `nb_frac < min` knife-edge. That gap is MAP §0.5's hidden-fragility warning
> demonstrated on a live case (§C.5).
>
> **7 — Cost closes the last escape.** At MAP §4.2 item 8's "2×" column (26 bps round trip,
> `spread_bps = 20`), the best candidate's OOS expectancy falls from +0.0373R to **+0.0003R**.
> Since a larger universe is exactly where wider spreads live, expanding the universe to power
> this strategy is self-defeating: breadth adds n while spread removes the point estimate, and
> gate 4 needs the point estimate.
>
> **8 — Even a pass would not have been operable, for the cross-sectional family.** A
> strategy conditioned on a 150-name cross-section cannot be run against the 25-symbol live
> scan (`scan.py:269`), and gate 10 passes unconditionally — so nothing in the ladder would
> have prevented a strategy structurally incapable of emitting a signal from reaching
> PAPER_APPROVED. That is a promotion-integrity hole, reported separately (§14, Q4).
>
> **9 — Gate 9 provides no independent check here, which is why we stopped.** *(sealed
> numbers, disposition use only, R1, marked)* v4's sealed test passes on all four snapshots at
> +0.1230R to +0.1278R, on a calm bullish year that is exactly this dip-buy's best regime and
> that the nine-year pre-sealed record says is the exception. A v0.2.0 that repaired the
> earlier gates would inherit a friendly gate 9 unable to catch an overfit. **Under R1 a
> sealed result may inform whether to stop trying — and it argues for stopping.**
>
> **10 — The gate-by-gate record, trade sets tagged (evaluation id 34, snapshot 3).**
> Gate 1 all pre-sealed (984): 2 of 4 folds, pass (bare). Gate 2 OOS: 309, pass. **Gate 3 OOS:
> −0.0837R, fail.** **Gate 4 OOS: CI [−0.1739, +0.0061], fail — no n fixes a negative point
> estimate.** **Gate 5: 0 of 9 positive, fail.** Gate 6 all pre-sealed: bull 618 / bear 46 /
> range 260, **60 unbucketed (6.1%)**, pass. **Gate 7 all pre-sealed: Sharpe −0.749 vs SPY
> +0.719, fail** (computed over all pre-sealed trades per `promotion.py:775`, despite the
> docstring at `config/research.py:111-113`). Gate 8: pass, snapshot 3 only. Gate 9: passes on
> all four snapshots. Gate 10: pass.
>
> **11 — The sealed ledger (R2).** Four locked draws for version 4: ids 3, 8, 13, 18 on
> snapshots 1–4. **k = 5; zero looks consumed by the design phase.**
>
> **12 — What remains unfalsified, correctly scoped.** The four gate-5-untested parameters
> `time_stop_bars`, `sma_window`, `z_lookback`, `atr_window` (MAP §0.5) — noting that the W2
> diagnostic already found the leash to be a **net positive**, so that region is less
> promising than MAP §2.2 assumed. Reopening requires RO-1…RO-6 (§4.2) to be met in advance.
>
> **13 — Two findings reusable beyond this strategy.** (a) Any cross-sectional statistic
> computed on an ETF-majority universe is degenerate: mean k = 10.90 on the 81 sessions where
> SPY is at z ≤ −2.0 versus 0.36 elsewhere, corr(ETF, single-name) = 0.752. (b) v4's entries
> are 20× concentrated: **57 sessions (2.57%)** have k ≥ 8, **53 of them (2.39%)** carried
> **480 of 984 trades**.

---

# 12. Consolidated pre-registration block

Everything in this section is fixed **before** any future run and may not be renegotiated
after a result is seen.

| Item | Pre-registered value |
|---|---|
| **Gate-5 axes** | §6's table, per candidate; `EXTREME_Z` is an axis, not a constant; any two-way combination exceeds `MAX_GRID_POINTS = 120` and is therefore not shippable |
| **Falsification / re-opening criteria** | RO-1 … RO-6 (§4.2), each required on snapshot 3 **and** snapshot 2, and on any W1 snapshot; RO-1/RO-2 bind on a **calendar-month block** SE with day and week reported alongside |
| **Variant budget (whole strategy, all angles)** | **6 declared, 7 evaluated in Phase 2, 3 prior diagnostic levers = 10 mechanism tests, 0 implemented.** Ledger at §9.1, to be reproduced verbatim in the final report |
| **Stopping rule** | §9.2 — positive **and** ≥ 2 SE clustered **and** breaking no gate v0.1.0 passes. **Fired.** No third variant in any angle |
| **Leading snapshot** | **Snapshot 3** (`universe_24_ex_meta`) — the only snapshot on which gate 8 passes for any version; forced by a pre-sealed data-quality gate. All four sealed draws disclosed alongside in every report |
| **Sealed-look accounting** | **k = 5 baseline. 0 consumed. 0 planned. Count stays 5.** A hypothetical v0.2.0 on snapshot 3 would be **look 6**; on snapshot 3 + a W1 snapshot, looks **6 and 7**. Convention clash flagged (§10) |
| **Mandatory disclosures on any future v4 result** | the four-draw sealed ledger; gate 6's unbucketed count beside the three buckets; gate 4 as a **required n**, at both the measured and the §0.3 sd; a clustered/block bootstrap beside the iid gate-4 CI with the half-width ratio; the per-symbol IS/OOS boundary dates; the 2× and 5× spread columns with their implied `spread_bps` |

---

# 13. Implementation checklist and validation commands

## 13.1 For the chosen design (null option) — no code, two documents

| # | Step | Check |
|---|---|---|
| 1 | Write `reports/mean_reversion.short_swing-0.1.0-does-not-pass.md` from §11 verbatim | contains the k = 5 ledger, the tagged gate table, gate 6's 60 unbucketed, the required-n figures, the ten-variant ledger |
| 2 | Commit this design document and the report | `git status --porcelain src tests` **must stay clean** |
| 3 | Assert nothing changed | `git diff --stat HEAD -- src tests` empty; `strategy_version` row for version 4 unmodified; **no new `strategy_sealed_test` row** |
| 4 | Assert no write reached the live DB | the worker and probation are untouched; no `evaluate-promotion` was run |

**No promotion command is run. No scratch database is needed for the null option itself.**

## 13.2 If — and only if — the operator approves **P1** (engine risk-unit fix)

| # | Release gate | Stop-ship condition |
|---|---|---|
| 1 | **Byte-identical default behaviour.** With `stop_anchor_blend = 0.0` and no strategy opting in, `run_backtest` returns identical `SimTrade` sequences | any difference |
| 2 | **No strategy opts in and no `VERSION` is bumped** — so R3's staleness trap is not engaged and gate 9 replays remain valid | any strategy setting a non-default value in the same change |
| 3 | **Approved scopes unmoved.** `spec_json_hash` stays `2ed9743170bd3bbdb450ea03a004a7ffaeb64ccbbe6075db312ffd544072f382` (v2) and `dfe696b662dd02b8fa3a02ce5b987c6eade84a40d88c1a2d8d52e206cb6f6c32` (v5); `scan_scope_matches` still True for both | any drift |
| 4 | **Zero-margin cases unmoved.** v6's `neighbour_positive_fraction` reads exactly **0.750** and v5's bear bucket exactly **11** on a scratch re-evaluation | any drift |
| 5 | **Directional guard.** The inverted-stop class is closed by construction, not by magnitude: assert `d·(entry_fill − stop_level) > 0` for every trade, and **zero** trades with `exit_reason == "stop" and pnl_r > 0` (today: 4) | any survivor |
| 6 | **Live-path divergence closed or recorded.** Either `scan.py:367-368, :415, :444` and `risk/engine.py:70` are made consistent with the engine, or the divergence is written into the change's own record | silent divergence |
| 7 | **No expectancy claim.** The change is justified by the correctness defect, **not** by expectancy; its invariant value is +0.0079R at 1.74 SE | any expectancy framing in the commit or report |

**Exact validation commands — SCRATCH DATABASE ONLY.** The live `data/signalforge.sqlite`
backs a running paper-probation worker; **every command below writes, so none may touch it.**

```bash
cd /Users/louisbrailey/signal-forge

# 0. one scratch copy per operator-approved item, named per the hard rules
cp data/signalforge.sqlite "$TMPDIR/scratch-mrsynth.sqlite"
export SCRATCH="sqlite+pysqlite:///$TMPDIR/scratch-mrsynth.sqlite"

# 1. baseline the three versions that must not move, BEFORE the change
DATABASE_URL="$SCRATCH" .venv/bin/python -m signalforge.cli evaluate-promotion \
  --strategy trend_continuation.short_swing --dataset ex_meta \
  --since 2016-09-10 --until 2026-09-08
DATABASE_URL="$SCRATCH" .venv/bin/python -m signalforge.cli evaluate-promotion \
  --strategy relative_strength.medium_swing --dataset ex_meta \
  --since 2016-09-10 --until 2026-09-08
DATABASE_URL="$SCRATCH" .venv/bin/python -m signalforge.cli evaluate-promotion \
  --strategy volatility_breakout.short_swing --dataset ex_meta \
  --since 2016-09-10 --until 2026-09-08

# 2. apply the change, then repeat step 1 on a FRESH scratch copy and diff gates_json
#    field-for-field against evals 32 / 35 / 36. v6 neighbour_positive_fraction must
#    read exactly 0.750 and v5's bear bucket exactly 11.

# 3. unit + regression gates
.venv/bin/python -m pytest tests/backtest -q
.venv/bin/python -m pytest tests/research -q
make lint && make typecheck && make secrets

# 4. confirm nothing touched the live database
git status --porcelain src tests            # expect empty before step 2, minimal after
sqlite3 data/signalforge.sqlite \
  "select count(*) from strategy_sealed_test;"   # must still be 20
```

**Never** run `evaluate-promotion`, `backtest-*`, `sensitivity` or
`promotion-dataset-comparison` without `DATABASE_URL` pointing at the scratch copy.

## 13.3 If the operator approves **P2** (gate-5 axis integrity rule)

| # | Step | Check |
|---|---|---|
| 1 | Ship `pipeline_hardening_spec.md` §2's declared-axis mechanism **first** — an optional `sensitivity_axes()` on the strategy class, merged into `_sensitivity_plan` via `getattr(strategy, "sensitivity_axes", lambda: {})()`, **never** a `StrategySpec` field | adding it to `StrategySpec` moves every `spec_json_hash` and permanently unscopes both live approvals — **stop-ship** |
| 2 | Assert `_sensitivity_plan` still returns the **9-point** grid for a v0.1.0 `MeanReversion()` instance | any `TypeError` from `_replace` (L2) |
| 3 | Adopt the rule in writing: *every parameter a v0.2.0 introduces becomes a pre-registered gate-5 axis in the same change* | — |
| 4 | Record §C.5 as the motivating evidence | 88.9% / 0.750 PASS vs 55.6% / 66.7% FAIL on the same v0.2.0 |

**No `mean_reversion` grid edit is made under P2** — see §2.2.

---

# 14. What the operator must approve, and what is reported if it fails

## 14.1 Nothing in the chosen design requires approval beyond the usual commit

The null option writes two documents and changes no code, no configuration, no threshold, no
cost constant and no database row. **No W1 API calls are requested by this design** — the
universe/breadth angle's 126-call backfill is explicitly **not** needed, because v4's binding
gates (4 and 7) are point-estimate gates that breadth cannot move (§5.3) and because spread
on a wider universe removes the very point estimate gate 4 needs (§8).

## 14.2 Decisions requested

| # | Question | Recommendation | If declined |
|---|---|---|---|
| **Q1** | Approve **P1**, the engine risk-unit correctness fix — behaviour-preserving by default, opt-in per strategy, **no strategy `VERSION` bump**, zero sealed looks, subject to all seven release gates in §13.2? | **Yes.** The defect is verified and real (4 `stop` exits booked as wins; a 0.0043-ATR risk unit rendering 5.5 bps as −3.099R; median realised risk 2.127 ATR against an intended 2.000) and it distorts R-accounting for **every** strategy, including the two live ones. It is a correctness fix, **not** an edge: its invariant value is +0.0079R at 1.74 SE and it is not to be framed otherwise. | Record the defect in the disposition report as a known, quantified distortion of R-accounting affecting all strategies, and re-raise it when the next engine change is proposed. |
| **Q2** | Approve **P2**, the gate-5 axis integrity rule, sequenced behind `pipeline_hardening_spec.md` §2? | **Yes.** §C.5 is the program's cleanest live demonstration that the legacy grid converts a worse-robustness variant into an 88.9% pass at the exact knife-edge. Cheapest integrity improvement available. | Record §C.5 in the map's §0.5 as measured evidence, and make the axis requirement a manual checklist item on every future v0.2.0. |
| **Q3** | Settle the **look-numbering convention** once: MAP §0.1/R2 say "look 5"; MAP §4.2 item 10 and this brief say **look 6**; the hardening spec adopts `k_prior = 4, this_look = 5`. | Adopt **k = 5 → look 6** (this document's convention) and correct MAP §0.1/R2, or adopt the counter's definition and correct MAP §4.2 item 10 — but pick one before any counter ships. | Every report must state which convention it uses, inline, every time. |
| **Q4** | Accept the **promotion-integrity finding**: gate 10 is `health_monitor.enabled` and passes unconditionally, so a strategy structurally incapable of emitting a live signal (e.g. any fail-closed cross-sectional rule, given `scan.py:269-272`) can reach PAPER_APPROVED. Should a research/live-parity check be added to the ladder? | Raise as a separate hardening item. It is out of scope for a `mean_reversion` design and must not be bundled with one. | Record it as a standing risk in MAP §4.3. |
| **Q5** | Confirm the **gate-7 docstring/code divergence** disposition (`config/research.py:111-113` says OOS; `promotion.py:775` computes all pre-sealed). All forecasts here use the code. | Correct the docstring, not the code — changing the code would alter a gate under R4. | Every gate-7 figure must keep carrying the "all pre-sealed trades" tag. |
| **Q6** | Confirm that MAP §4.2 item 8's "**2× and 5× the modelled spread** (26 and 66 bps round trip)" is understood as **4× and 12×** the modelled 5.0 bps *quoted* spread (§B.2(b)). | Fix the map's wording; keep the 26/66 bps columns as the binding requirement. | Report both the round trip and the implied `spread_bps` every time, as §8 does. |

## 14.3 What is reported if any approved item fails

| Item | Failure | Report |
|---|---|---|
| **P1** | Any of release gates §13.2 #1–#7 fails on the scratch database — in particular if v6's `neighbour_positive_fraction` moves off 0.750, v5's bear bucket moves off 11, or either live spec hash changes | **Stop-ship.** The change is reverted, the scratch evidence is committed to the diagnostics folder, and the anchor defect stays a documented, quantified property of the engine. No strategy is re-evaluated on the live database, and no sealed look is consumed. |
| **P2** | The declared-axis mechanism cannot be built off `StrategySpec`, or `_sensitivity_plan` cannot be made version-aware without breaking v0.1.0 re-evaluation | The rule is adopted as a **manual** pre-integration checklist item instead, and §C.5 is recorded in the map as the reason it matters. |
| **The null option** | The operator directs that a v0.2.0 be attempted anyway | Then RO-1…RO-6 (§4.2) and the §6 grids bind, the §9.1 ledger's **ten prior mechanism tests** are stated in the same report, the run consumes **look 6** on snapshot 3, and any pass is reported as *"passed on look 6, after ten variants, on a strategy whose gate 9 was already friendly on all four snapshots"*. On present evidence the forecast is that it fails gates 4, 5 and 7 regardless of which candidate is chosen, and that outcome would **not** count as new information (it is forecast here, in advance). |

---

## Appendix — reproduction

Read-only, deterministic (`engine.py` has no RNG and no wall-clock dependence;
`bootstrap_ci` is seeded, `montecarlo.py:18-20`, seed 20240101).

| Artefact | How to reproduce |
|---|---|
| §C.1 baseline, §C.2 exits partitions, §C.3 H13 partition and re-simulation, §C.4 breadth panel and re-simulation | one read-only pass over snapshot 3, `2016-09-10 .. 2025-09-07`, source `massive`, proxy SPY, `min_bars = 60`, `CostModel()` defaults — ~9 s |
| §C.5 both 27-point gate-5 grids | 54 read-only universe passes replicating `sensitivity.py`'s enumeration, `evaluable` filter and `_is_neighbour` — ~107 s |
| Sealed ledger, spec hashes, eval 34 gate evidence | read-only `SELECT` against `strategy_sealed_test`, `strategy_promotion_evaluation`, `data_snapshot` |

*Design document only. No strategy code, configuration, gate threshold, cost-model constant
or database row was changed in producing it, and no sealed look was consumed.*
