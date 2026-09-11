# W2 diagnostic — `mean_reversion.short_swing` v0.1.0 (version 4): MFE / MAE vs the frozen target and stop

**Hypothesis under test:** H8 (`STRATEGY_COMPLETION_MAP.md` §2.2) — *"unfavourable exit
geometry: a 2×ATR stop vs a sub-ATR frozen SMA target plus a 6-bar leash caps winners and
leaves losers full-sized."*
**Stated falsification condition (§2.2):** *"Falsified if pre-sealed MFE distribution shows
most trades reach the frozen target comfortably within 6 bars."*

**Scope:** pre-sealed span only, `2016-09-10 .. 2025-09-07`, source `massive`, proxy `SPY`,
dataset snapshots **3** (`universe_24_ex_meta`, 24 symbols) and **2** (`universe_25_baseline`,
25 symbols). Nothing in the sealed window (2025-09-08 → 2026-09-08) was read, computed, or
consulted. This diagnostic consumes **zero sealed looks**; the baseline look count for this
strategy remains **k = 5** (`STRATEGY_COMPLETION_MAP.md` §0.1, R2).

**Compliance:** no file under `src/` or `tests/` was modified; no gate, threshold or cost
model was touched; the analysis ran against a **copy** of the live database
(`$TMPDIR/scratch-v4_mfe_target.sqlite`) with `DATABASE_URL` pointed at the copy, so no write
of any kind reached `data/signalforge.sqlite`. This is a **diagnostic**, not a tuned rule: no
parameter recommendation is made, and the one counterfactual computed (§7) was specified by
the task before it was run.

---

## 1. Method, and the reproduction check that validates it

The engine already records `mfe_r` and `mae_r` per trade (`src/signalforge/backtest/engine.py:118-127`),
but the **target distance in R** is not persisted anywhere, so the pre-sealed run was
re-executed with a recording wrapper around the strategy's signal function to capture each
trade's `stop_price` and `target_price` alongside its excursions. A second pass re-implemented
`run_backtest` verbatim in the scratchpad so the exit rule could be swapped for the §7
counterfactual.

**FACT (reproduction check).** Both re-runs reproduce the recorded promotion evaluations
exactly, which is what licenses every number below:

| Quantity | This diagnostic | Recorded evaluation | Match |
|---|---|---|---|
| snap 3, pre-sealed trades | **984** | 984 (eval 34, gate 6: 618+46+260+60 unbucketed) | ✅ |
| snap 3, OOS trades | **309** | 309 (eval 34, gate 2) | ✅ |
| snap 3, OOS expectancy | **−0.0837R** | −0.0837R (eval 34, gate 3) | ✅ |
| snap 2, pre-sealed trades | **999** | 999 | ✅ |
| snap 2, OOS trades | **320** | 320 (eval 28, gate 2) | ✅ |
| snap 2, OOS expectancy | **−0.0782R** | −0.0782R (eval 28, gate 3) | ✅ |

Snapshot 2 is snapshot 3 **plus META** and differs by 15 trades (1.5%). Every statistic below
is within 0.4 SE across the two snapshots, so **snapshot 3 is reported as primary and snapshot
2 is carried in the tables as the robustness check it is** — it adds no independent information
beyond confirming that no finding here is a META artefact.

Frame of reference throughout: R is defined by the engine as `|entry_fill − stop_price|`
(`engine.py:110-111`), so **the stop sits at exactly −1R by construction** and the frozen
target sits at `target_r = (target_price − entry_fill) / risk_per_share`. Excursions are
measured over `[entry_idx, exit_idx]` inclusive.

### 1.1 A prior citation that should be retired

**FACT.** §2.2 cites `reports/mean_reversion.short_swing-0.1.0.md:17-18` ("IS avg win +0.45R vs
avg loss −0.80R") as supporting evidence for H8. That report's window is
**`2024-08-28 → 2026-09-07`** (`reports/mean_reversion.short_swing-0.1.0.md:9`) on 243 trades —
a two-year window whose *out-of-sample* 40% lies almost entirely **inside the sealed span**.
It is not a pre-sealed statistic and should not be used to motivate a design choice (R1).
The pre-sealed replacements are in §5 below: avg win **+0.5767R** (SE 0.0235, n=521), avg loss
**−0.7808R** (SE 0.0262, n=463) over the 984 pre-sealed trades.

---

## 2. The geometry itself — where the target and stop actually sit

**FACT (snapshot 3, all 984 pre-sealed trades).**

| Quantity | median | mean | SE(mean) | p10 | p90 |
|---|---|---|---|---|---|
| Frozen target distance, in **R** | **+0.770** | +2.261 † | 0.845 † | +0.072 | +2.157 |
| Frozen target distance, in **ATR(14)** | **+1.598** | +1.716 | 0.0434 | +0.160 | +3.457 |
| Risk unit `\|entry_fill − stop\|`, in **ATR(14)** | **+2.127** | +2.051 | 0.0191 | +1.271 | +2.697 |
| Stop, in R | −1.000 | −1.000 | — | — | — |

† The mean and SE of `target_r` are **not usable**: they are dominated by a small tail of
trades whose risk unit collapses (§9.1). Use the median and the ATR-denominated row.

**FINDING 1 (FACT) — the asymmetry is real but roughly half the size §2.2's prose asserts.**
§2.2 states the target is *"typically well under 1×ATR away while the stop is 2×ATR away"*.
Measured: the median target is **1.598 ATR** away and the median risk unit is **2.127 ATR**, a
ratio of **0.77 : 1** in R terms, not the ≈0.5 : 1 the prose implies. **36.7% ± 1.5%** of
trades have a target **further than 1R** (i.e. further than the stop); only **34.8% ± 1.5%**
have a target inside 0.5R. The design does take a shorter shot than it risks, but "sub-ATR
target vs 2-ATR stop" overstates it, and any argument that leans on that specific ratio should
be restated.

Snapshot 2 is identical to three decimals (median target 1.599 ATR, median risk 2.128 ATR,
median `target_r` +0.770).

---

## 3. MFE distribution

**FACT (snapshot 3).** Percentiles of `mfe_r`:

| Set | n | p5 | p10 | p25 | **median** | p75 | p90 | p95 |
|---|---|---|---|---|---|---|---|---|
| all pre-sealed | 984 | +0.027 | +0.070 | +0.216 | **+0.457** | +0.862 | +1.309 | +1.726 |
| OOS only | 309 | +0.025 | +0.072 | +0.193 | **+0.395** | +0.772 | +1.227 | +1.572 |
| all pre-sealed (snap 2) | 999 | +0.026 | +0.069 | +0.217 | **+0.460** | +0.856 | +1.307 | +1.718 |

Means over the full set are outlier-contaminated (all pre-sealed: +0.769, sd 2.764). On the
**93.4%** of trades whose risk unit is a normal size (≥ 1×ATR) the distribution is well behaved:
mean MFE **+0.5546R**, sd 0.4690, **SE 0.0155**, median +0.4381 (OOS: mean +0.5265, SE 0.0273).

**FINDING 2 (FACT).** The median trade's best moment is **+0.457R** against a median target of
**+0.770R** — the typical trade gets a little over half way to its target and no further. The
upper tail is thin: only **18.5% ± 1.2%** of trades ever trade 1R in their favour, and
**7.4% ± 0.8%** ever reach 1.5R.

---

## 4. MAE distribution

**FACT (snapshot 3).** Percentiles of `mae_r` (stop = −1R):

| Set | n | p5 | p10 | p25 | **median** | p75 | p90 | p95 |
|---|---|---|---|---|---|---|---|---|
| all pre-sealed | 984 | −1.926 | −1.538 | −1.052 | **−0.519** | −0.206 | −0.090 | −0.043 |
| OOS only | 309 | −1.913 | −1.481 | −1.050 | **−0.554** | −0.198 | −0.088 | −0.040 |
| all pre-sealed (snap 2) | 999 | −1.923 | −1.522 | −1.049 | **−0.519** | −0.215 | −0.092 | −0.044 |

Robust subset (risk ≥ 1×ATR, n=919): mean MAE **−0.6290R**, sd 0.5462, **SE 0.0180**,
median −0.4777.

**FACT.** **29.07% ± 1.45%** of pre-sealed trades touch the stop (MAE ≤ −1R); **50.91% ± 1.59%**
give back at least half the risk unit at some point.

**FINDING 3 (FACT) — the stop does not hold at −1R.** Stop exits average **−1.0763R**
(n=287, SE 0.0303), i.e. **2.5 SE worse** than the nominal −1R, with a 5th-percentile tail to
−7.28R. This is gap-through slippage, and it is one of only two places in the whole trade
population where money is actually lost (§5).

---

## 5. Exit reasons, and where the expectancy actually goes

**FACT (snapshot 3, all 984 pre-sealed trades; expectancy −0.0621R, sd 0.8725, SE 0.0278).**

| Exit reason | n | share | mean pnl | SE | **contribution to expectancy** | mean MFE | SE | mean MAE | SE | mean bars |
|---|---|---|---|---|---|---|---|---|---|---|
| `target` | 444 | 45.1% ± 1.6 | **+0.4684** | 0.0256 | **+0.2114R** | +0.693 | 0.027 | −0.270 | 0.010 | 1.54 |
| `stop` | 287 | 29.2% ± 1.4 | **−1.0763** | 0.0303 | **−0.3139R** | +0.959 † | 0.298 | −2.498 † | 0.781 | 2.08 |
| `time_stop` | 252 | 25.6% ± 1.4 | **+0.1602** | 0.0419 | **+0.0410R** | +0.688 | 0.038 | −0.566 | 0.016 | 6.00 |
| `eod` | 1 | 0.1% | −0.5136 | — | −0.0005R | +0.376 | — | −0.977 | — | 3.00 |

† outlier-contaminated by the collapsed-risk tail (§9.1).

**FACT (OOS only, n=309, expectancy −0.0837R, SE 0.0467):** `target` 136 (44.0% ± 2.8) at
+0.4454R (SE 0.0402, contribution +0.1960R); `stop` 87 (28.2% ± 2.6) at −1.0554R (SE 0.0440,
contribution −0.2971R); `time_stop` 85 (27.5% ± 2.5) at +0.0692R (SE 0.0754, contribution
+0.0190R). Snapshot 2 differs by at most 0.01R in every cell.

**FACT.** Win/loss shape over the pre-sealed span: hit rate **52.95% ± 1.59%**, avg win
**+0.5767R** (SE 0.0235), avg loss **−0.7808R** (SE 0.0262). Mean holding period **2.84 bars**
(SE 0.079) against a 6-bar leash.

**FINDING 4 (FACT).** **The entire negative expectancy is the stop bucket.** Targets contribute
+0.2114R and the 6-bar leash contributes **+0.0410R** — the leash is a small *net positive*,
and 57.5% of time-stopped trades are closed in profit. §2.2's framing that the leash
"truncates the slow reversions that would justify" the design is not supported at the level of
realised expectancy: cutting at bar 6 currently *adds* to the total. (Whether a longer leash
would add more is a separate, tuning-shaped question this diagnostic deliberately does not
answer.)

---

## 6. Trades whose MFE exceeded a threshold but which exited at a loss

**FACT (snapshot 3).** `pnl_r < 0` is the loss criterion.

| Threshold | n with MFE > x | share of all | **n also exiting at a loss** | **share of all trades** | **P(loss \| MFE > x)** | mean pnl of the losers | exit reasons of the losers |
|---|---|---|---|---|---|---|---|
| **0.5R** | 451 | 45.8% | **95** | **9.65% ± 0.94%** | **0.211 ± 0.019** | −1.013R | 69 stop, 24 time_stop, 2 target |
| **1.0R** | 182 | 18.5% | **30** | **3.05% ± 0.55%** | **0.165 ± 0.028** | −1.502R | 27 stop, 3 time_stop |
| **1.5R** | 73 | 7.4% | **21** | **2.13% ± 0.46%** | **0.288 ± 0.053** | −1.771R | **21 stop** |

**FACT (OOS only, n=309):** MFE>0.5R & lost **27** = 8.74% ± 1.61% (P(loss|·) = 0.208 ± 0.036);
MFE>1.0R & lost **8** = 2.59% ± 0.90% (0.143 ± 0.047); MFE>1.5R & lost **5** = 1.62% ± 0.72%
(0.250 ± 0.097). Snapshot 2: 9.81% / 3.10% / 2.10% of all trades.

**Two mandatory qualifications on these counts.**

1. **FACT — roughly half are a modelling artefact of within-bar ordering, not a missed
   opportunity.** `engine.py:166-179` checks the stop **before** the target on every bar, so a
   bar that contains both levels is always resolved as a stop. Recomputing MFE over bars
   *strictly before* the exit bar — where an exit at that level would unambiguously have been
   available — cuts the counts to **58** (5.89%), **14** (1.42%) and **9** (0.91%) of all
   trades at the 0.5R / 1.0R / 1.5R thresholds. Of the 21 trades at MFE>1.5R that lost,
   **12 were resolved on the entry bar itself**.
2. **FACT — the MFE>1.5R losers are the collapsed-risk tail, not normal trades.** All 21 are
   stop exits, their mean risk unit is **0.540 ATR** (against a population median of 2.127 ATR),
   and they average **−1.771R**. Their MFE is large *because their R is small*, not because a
   large favourable move was thrown away.

**FINDING 5 (FACT).** The "gave back a big winner" population is small and mostly artefactual:
at the 1R threshold, at most **3.05% ± 0.55%** of trades qualify, and on the unambiguous
prior-bar definition only **1.42%**. There is no large reservoir of realised-then-surrendered
profit for a smarter exit to recover.

---

## 7. The counterfactual: closing at the SMA touch instead of the fixed target

The frozen target *is* SMA(20) sampled at the entry signal bar
(`mean_reversion.py:92`, `target_price=mean`). "Closing at the SMA touch" therefore means a
target that **tracks** SMA(20) instead of freezing it. Implemented leakage-free: on bar `u` the
target level is SMA(20) **as of bar `u−1`**, which is known before bar `u` opens, and which at
`u = entry_idx` equals the frozen target exactly. Stop, stop-first ordering, 6-bar leash, fills
and the 11 bps round-trip cost model are all unchanged.

Two versions were computed, because they answer different questions:

- **Paired** — the *same* entry set, re-exited. Correct for a per-trade comparison, since the
  SE of the paired difference is tiny.
- **Full re-simulation** — the whole loop re-run, so exit dates shift and the subsequent entry
  sequence changes (the engine is flat-only, `engine.py:149`).

**FACT (snapshot 3).**

| | n | expectancy | SE | vs frozen |
|---|---|---|---|---|
| Frozen target (**actual**), all pre-sealed | 984 | **−0.0621R** | 0.0278 | — |
| Tracking SMA, paired, all pre-sealed | 984 | −0.0652R | 0.0278 | **Δ = −0.0032R, SE 0.0040, t = −0.79** |
| Tracking SMA, full re-sim, all pre-sealed | 985 | −0.0647R | 0.0277 | −0.0026R |
| Frozen target (**actual**), OOS | 309 | **−0.0837R** | 0.0467 | — |
| Tracking SMA, paired, OOS | 309 | −0.0841R | 0.0459 | **Δ = −0.0004R, SE 0.0064, t = −0.05** |
| Tracking SMA, full re-sim, OOS | 310 | −0.0863R | 0.0458 | −0.0026R |

Snapshot 2, all pre-sealed: frozen −0.0622R (SE 0.0275), tracking paired −0.0650R,
**Δ = −0.0028R, SE 0.0040, t = −0.68**; full re-sim −0.0644R on 1,000 trades.

Exit-reason mix under the tracking rule (snap 3, full re-sim): `target` **493** (vs 444),
`stop` 287 (vs 287), `time_stop` 204 (vs 252). The tracking target converts ~49 time stops into
target exits and moves the expectancy by nothing.

**FINDING 6 (FACT) — this refutes the specific mechanism in §2.2 lever 3.** The paired
difference is **−0.003R ± 0.004** (0.8 SE, and the *wrong sign*); the OOS difference is
**−0.0004R ± 0.006** (0.05 SE). Under the map's own 2-SE rule this is not evidence of any
effect. The mechanical reason is visible in the data: the mean holding period is **2.84 bars**,
over which a 20-day SMA barely moves, so the tracked and frozen levels are nearly the same
number. "Make the target track the SMA rather than freezing it at entry" is a dead lever on
pre-sealed data, and a v0.2.0 built on it should not be attempted.

---

## 8. Verdict on H8

**H8's stated falsification condition is NOT met — narrowly.** "Most trades reach the frozen
target comfortably within 6 bars" requires >50%; measured, **45.12% ± 1.59%** of pre-sealed
trades reach it (**44.01% ± 2.82%** OOS). That is 3.1 SE below 50% on the full pre-sealed set
and 2.1 SE below OOS. So H8 survives its own pre-registered kill test.

**But it survives as a much weaker hypothesis than it was written as**, and two of its three
component claims are refuted by the same data:

| H8 component claim | Verdict | Evidence |
|---|---|---|
| Target is sub-ATR while the stop is 2×ATR | **Refuted as stated** | median target **1.598 ATR** vs median risk **2.127 ATR** → 0.77 : 1 in R, not ≈0.5 : 1 (§2) |
| The 6-bar leash truncates reversions that would have paid | **Refuted at the level of realised expectancy** | time stops contribute **+0.0410R**, 57.5% closed in profit (§5) |
| Winners are capped and losers are full-sized | **Supported** | avg win **+0.5767R** (SE 0.0235) vs avg loss **−0.7808R** (SE 0.0262); \|loss\| − win = **0.204R**, SE 0.035, **t = 5.8** (§5) |
| A smarter (SMA-tracking) target recovers the shortfall | **Refuted** | Δ = −0.003R ± 0.004 (§7) |

**FACT — a consistency check that came out clean.** The number of trades with
`MFE ≥ target_r` is **exactly** the number of `target` exits (444 of 444 on snap 3, 451 of 451
on snap 2, 0 discrepancies). The excursion and exit accounting agree perfectly, which is a
useful independent check on both the engine and this re-run.

**FINDING 7 (HYPOTHESIS) — the exit geometry is not where this strategy's money goes; the
entry fill is.** A tail of **6.6%** of pre-sealed trades (65 of 984) has a risk unit below
1×ATR because the next session **opens down by a median of −1.40 ATR**, placing the entry fill
most of the way to a stop that was fixed from the *previous* close. 56 of those 65 (86%) stop
out. They average **−0.6710R** (SE 0.2141) against **−0.0190R** (SE 0.0251) for the other 919
trades — a difference of **−0.652R, SE 0.216, t = −3.02** (OOS: −0.8387R, SE 0.2402, t = −3.49).

On the 93.4% of trades with a normal-sized risk unit, pre-sealed expectancy is
**−0.0190R ± 0.0251** and OOS expectancy is **−0.0213R ± 0.0449** — both **statistically
indistinguishable from zero** rather than the −0.06R / −0.08R the strategy actually posts.

This is a **hypothesis for a later phase, not a recommendation**, and it must be treated with
the following discipline if anyone acts on it:

- It is a *diagnostic partition of realised trades*, not a tested rule. Turning it into a rule
  (a gap filter, or recomputing the stop from the entry fill rather than the prior close)
  changes entry/exit behaviour, so it ships as **VERSION "0.2.0"** under R3/R7, and gate 5 must
  add the new parameter as an axis (§0.5) — the decisive parameter is exactly the one the
  current 2-of-6 grid does not perturb.
- Removing a losing subset from a sample **always** improves the remainder. −0.0190R ± 0.0251
  is "not distinguishable from zero", which is still not "positive"; gates 3 and 4 need
  `> 0` and a CI low `> +0.02R`, and this partition does not reach either. Gate 4 at
  sd ≈ 0.76 and n = 919 needs a point estimate above roughly +0.069R.
- It says nothing about gate 5 (0/9 grid points positive) or gate 7 (Sharpe −0.749 vs SPY
  +0.719), which remain unaddressed.

---

## 9. Caveats

**9.1 The `target_r`, MFE and MAE *means* over the full sample are not usable statistics.**
`risk_per_share` appears in the denominator of every R-quantity, and 2.44% of trades have it
below 0.5×ATR, so a routine price move renders as an enormous R value (max observed
`target_r` = +819.8). Every mean in this document over the *full* sample is flagged; the
medians, the percentile tables, and the risk ≥ 1×ATR subset statistics are the ones to quote.

**9.2 Within-bar ordering makes §6 conservative by construction.** The engine assumes the stop
is hit first on any bar containing both levels (`engine.py:166-179`). Roughly half the
"MFE exceeded x but lost" cases are same-bar. The prior-bar counts in §6 are the honest lower
bound; the truth lies between the two columns and cannot be resolved without intraday bars,
which do not exist in this database for these symbols (§2.4 of the map).

**9.3 The §7 counterfactual is an exit swap only.** It leaves the entry rule, the stop, the
leash, the cost model and the 5.0 bps flat spread assumption (`backtest_runner.py:205-206`,
`engine.py:90-94`) untouched. It is a diagnostic, not a candidate strategy, and it was not
tuned — one rule was specified in advance and run once per snapshot.

**9.4 Snapshot 2 adds no independent evidence.** It is snapshot 3 plus META, differing by 15
trades. It is reported because the task named it and because agreement across the two rules out
a META artefact — not as a second sample. Note that snapshot 2 **fails gate 8** for every
version (`validate_daily: FAIL (META: 90 missing (6.9%))`, eval 28), so nothing on snapshot 2
can support a promotion argument regardless.

**9.5 Multiple-testing accounting (R5).** This diagnostic ran **one** pre-specified
counterfactual exit rule (§7) and **zero** parameter searches. No parameter value was selected,
scored, or compared against alternatives. Finding 7 is a partition of the existing trade
population discovered while auditing the R-denominator outliers, not a swept variable — but it
is an *unplanned* observation and should be counted as such (one unplanned hypothesis) when
the strategy's variant ledger is compiled.

**9.6 Reproducibility.** Deterministic — the engine has no RNG and no wall-clock dependence
(`engine.py:12`). Raw per-trade output is in the `.json` sibling of this file.

---

## Appendix — snapshot 2 headline numbers

| Quantity | snap 3 | snap 2 |
|---|---|---|
| pre-sealed trades / OOS trades | 984 / 309 | 999 / 320 |
| pre-sealed expectancy | −0.0621R (SE 0.0278) | −0.0622R (SE 0.0275) |
| OOS expectancy | −0.0837R (SE 0.0467) | −0.0782R (SE 0.0454) |
| median target distance (R / ATR) | +0.770 / 1.598 | +0.770 / 1.599 |
| median MFE / median MAE (R) | +0.457 / −0.519 | +0.460 / −0.519 |
| target-exit share | 45.12% ± 1.59% | 45.15% ± 1.57% |
| stop-exit share / mean pnl | 29.17% / −1.0763R | 28.93% / −1.0759R |
| time-stop share / mean pnl | 25.61% / +0.1602R | 25.83% / +0.1526R |
| MFE>1R & lost, share of all | 3.05% ± 0.55% | 3.10% ± 0.55% |
| tracking-SMA paired Δ | −0.0032R (SE 0.0040) | −0.0028R (SE 0.0040) |
