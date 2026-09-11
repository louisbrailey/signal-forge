# Cross-cutting diagnostic — the gate-4 bootstrap assumes iid trades

**Task key:** `clustered_bootstrap_all`
**Addresses:** `STRATEGY_COMPLETION_MAP.md` §4.3, standing risk *"The bootstrap assumes
iid trades and this universe violates it (§3a). … Every CI here is too narrow and every
required-n is a lower bound. Report a clustered/block bootstrap alongside as a diagnostic."*
**Date:** 2026-09-10 · **Scope:** snapshot **3** (`universe_24_ex_meta`), source `massive`,
**pre-sealed out-of-sample trades only**, evaluations **32–36**.

> **This is a diagnostic disclosure, not a gate change.** Nothing here proposes moving,
> relaxing, tightening or replacing gate 4. `PromotionThresholds.min_bootstrap_ci_low_r`
> stays at `+0.02` (`config/research.py:102`) and `backtest/montecarlo.py` is untouched.
> Reporting a stricter statistic alongside the gate statistic is explicitly permitted by
> **R4** (`STRATEGY_COMPLETION_MAP.md` §1: *"Adding a stricter reported statistic is never
> a weakening"*). No sealed-window data (2025-09-08 → 2026-09-08) was loaded, read or
> used anywhere in this analysis; every trade below has an entry date on or before
> **2025-09-05**, and the analysis window ends at the pre-sealed boundary **2025-09-07**.
> No design, parameter, filter or universe choice is recommended.

---

## 1. Headline

**FACT.** Under **(b) block bootstrap by entry calendar month**, **both currently
PAPER_APPROVED strategies fail gate 4's `+0.02R` lower bound**:

| Version | Strategy | Live status | (a) iid low | **(b) month-block low** | (c) symbol-cluster low |
|---|---|---|---|---|---|
| **2** | `trend_continuation.short_swing` v0.1.0 | **PAPER_APPROVED** | +0.1129 ✅ | **+0.0125 ❌** | +0.1381 ✅ |
| **5** | `relative_strength.medium_swing` v0.1.0 | **PAPER_APPROVED** | +0.0901 ✅ | **−0.0238 ❌** | +0.0493 ✅ |
| 3 | `trend_continuation.medium_swing` v0.1.0 | experimental | +0.1205 ✅ | **−0.0191 ❌** | +0.1644 ✅ |
| 4 | `mean_reversion.short_swing` v0.1.0 | experimental | −0.1739 ❌ | −0.2901 ❌ | −0.1569 ❌ |

Under **(c) cluster bootstrap by symbol**, **no strategy that passes gate 4 today would
fail it** — and for three of the four versions the symbol-clustered CI is *narrower* than
the iid one.

**The two clusterings disagree, and that disagreement is the substantive finding.** The
dependence that actually exists in this 24-symbol universe is **calendar-time
(cross-sectional co-movement on shared dates)**, not **within-symbol serial**. Clustering
by symbol is the wrong instrument for the risk §4.3 names: it *assumes* independence
across symbols, which is precisely what "15 of 24 symbols are ETFs, several containing the
others" violates. §4.3's blanket claim that "every CI here is too narrow" is therefore
**directionally right but attributed to the wrong axis** — see §6.

---

## 2. Method and reproduction of the stored gate-4 CI

### 2.1 What was recomputed, and against what

**FACT.** The gate-4 statistic is `full.oos_ci["expectancy_r"]["low"]`
(`research/promotion.py:679`), where `oos_ci` is produced by
`bootstrap_ci([t.pnl_r for t in oos_trades])` (`research/backtest_runner.py:228`) with the
function's defaults: `n_resamples=2000` (`backtest/montecarlo.py:18`), `seed=20240101`
(`:19`), percentile method at 95% (`:42-52`). The threshold is `+0.02R`
(`config/research.py:102`), tested strictly (`>`), at `promotion.py:680`.

The OOS trade set was regenerated in-process by replicating
`run_strategy_over_universe`'s loop exactly: `PriceSeries.load(..., source="massive")` per
symbol over `2016-09-10 .. 2025-09-07`, `run_backtest(series, signal_fn_for(strategy,
regime_by_date=regime_lookup(SPY)), cost_model=CostModel(), warmup=30)`, per-symbol IS/OOS
split at `_is_boundary` (`backtest_runner.py:158-160`, `_TRAIN_FRAC = 0.6`), keeping trades
with `entry_date > boundary`. Symbol iteration order is the stored `universe_json` order
from evaluation 32 (alphabetical, 24 symbols) — this matters, because `montecarlo.py`
draws a fixed index matrix and applies it to the array *in order*.

### 2.2 Reproduction check — exact, not "within rounding"

**FACT.** The replicated iid bootstrap reproduces every stored `gates_json` CI
**bit-for-bit in float64** (max absolute difference `0.0` on low, point and high, for all
five versions), and every OOS trade count matches gate 2's stored `n_oos_trades`:

| Ver | eval | stored n | recomputed n | stored CI (low, point, high) | recomputed CI | max abs diff |
|---|---|---|---|---|---|---|
| 2 | 32 | 341 | **341** | (+0.1128771564, +0.2648267109, +0.4142840774) | identical | **0.0** |
| 3 | 33 | 319 | **319** | (+0.1204654992, +0.3063923166, +0.5026805561) | identical | **0.0** |
| 4 | 34 | 309 | **309** | (−0.1738808005, −0.0837390534, +0.0060663963) | identical | **0.0** |
| 5 | 35 | 197 | **197** | (+0.0901373239, +0.3004072805, +0.5045817820) | identical | **0.0** |
| 6 | 36 | 51 | **51** | (−0.3552611586, +0.0613487388, +0.4978781048) | identical | **0.0** |

This is a stronger check than the task asked for and it validates the whole pipeline used
below: the trade sets, their order, the cost model, the IS/OOS split and the RNG stream all
match the production evaluation.

**FACT (corroborates §0.3).** The map's §0.3 per-trade `sd` figures were *inverted* from
the stored CI half-widths under a normal approximation and were flagged accurate to ~2
significant figures. The directly computed sample sd confirms that: v2 1.420 → **1.4673**,
v3 1.741 → **1.7259**, v4 0.807 → **0.8202**, v5 1.484 → **1.4879**, v6 1.554 → **1.5242**.
Use the direct figures from here on.

### 2.3 The three resampling schemes

All three use **2,000 resamples, seed 20240101, percentile method, 95%** — identical to the
gate — and differ only in the resampling unit.

- **(a) iid per-trade.** `montecarlo.py` verbatim: draw `n` trade indices with replacement,
  `n` times over, take the mean.
- **(b) block bootstrap by entry calendar month.** Trades are grouped into non-overlapping
  blocks keyed by `(entry_date.year, entry_date.month)`. Draw `G` blocks with replacement
  (`G` = number of distinct months with ≥1 OOS trade), pool the drawn blocks, take the
  **pooled mean** (a ratio estimator — block sizes are unequal, so the resampled `n`
  varies). This is the standard non-overlapping calendar-block cluster bootstrap.
- **(c) cluster bootstrap by symbol.** Identical construction with the cluster key set to
  the trade's symbol; `G` = number of symbols with ≥1 OOS trade.

**Deliberate design note.** Blocks/clusters are resampled, never re-ordered or shortened, so
no trade is split or duplicated within a block; this preserves whatever within-block
dependence exists, which is the entire point.

---

## 3. Results — all three CIs per version, with n

Point estimates, per-trade sd, and the analytic iid standard error `sd/√n`:

| Ver | Strategy | Status | **n** | expectancy | per-trade sd | **SE(iid)** |
|---|---|---|---|---|---|---|
| 2 | `trend_continuation.short_swing` | PAPER_APPROVED | **341** | **+0.2648R** | 1.4673 | **0.0795** |
| 3 | `trend_continuation.medium_swing` | experimental | **319** | **+0.3064R** | 1.7259 | **0.0966** |
| 4 | `mean_reversion.short_swing` | experimental | **309** | **−0.0837R** | 0.8202 | **0.0467** |
| 5 | `relative_strength.medium_swing` | PAPER_APPROVED | **197** | **+0.3004R** | 1.4879 | **0.1060** |
| 6 † | `volatility_breakout.short_swing` | experimental | **51** | **+0.0613R** | 1.5242 | **0.2134** |

† v6 was not in the task's version list (2, 3, 4, 5). It is included because it costs
nothing and completes the picture; every conclusion in §1 and §5 is stated over 2–5.

### 3.1 The three CIs (2,000 resamples, seed 20240101)

`deff` = design effect = (bootstrap SE under this scheme / bootstrap SE under iid)². The
`pass` column is against gate 4's `> +0.02R`.

| Ver | scheme | G (clusters) | 95% CI | SE(boot) | deff | lower bound vs +0.02 |
|---|---|---|---|---|---|---|
| **2** | (a) iid | — | **[+0.1129, +0.4143]** | 0.0778 | 1.00 | **PASS** (+0.093 above) |
| | (b) **month** | 28 | **[+0.0125, +0.4944]** | 0.1244 | **2.55** | **FAIL** (0.0075 below) |
| | (c) **symbol** | 24 | **[+0.1381, +0.3964]** | 0.0664 | **0.73** | **PASS** (+0.118 above) |
| **3** | (a) iid | — | **[+0.1205, +0.5027]** | 0.0965 | 1.00 | PASS |
| | (b) **month** | 28 | **[−0.0191, +0.6406]** | 0.1682 | **3.04** | **FAIL** (0.039 below) |
| | (c) **symbol** | 24 | **[+0.1644, +0.4501]** | 0.0737 | **0.58** | PASS |
| **4** | (a) iid | — | **[−0.1739, +0.0061]** | 0.0469 | 1.00 | FAIL |
| | (b) **month** | 35 | **[−0.2901, +0.1132]** | 0.1035 | **4.86** | FAIL |
| | (c) **symbol** | 24 | **[−0.1569, −0.0134]** | 0.0377 | **0.65** | FAIL |
| **5** | (a) iid | — | **[+0.0901, +0.5046]** | 0.1056 | 1.00 | **PASS** (+0.070 above) |
| | (b) **month** | 31 | **[−0.0238, +0.6467]** | 0.1705 | **2.60** | **FAIL** (0.044 below) |
| | (c) **symbol** | 22 | **[+0.0493, +0.5457]** | 0.1263 | **1.43** | **PASS** (+0.029 above) |
| 6 † | (a) iid | — | [−0.3553, +0.4979] | 0.2139 | 1.00 | FAIL |
| | (b) month | 12 | [−0.6192, +0.7426] | 0.3488 | 2.66 | FAIL |
| | (c) symbol | 23 | [−0.3104, +0.4505] | 0.1955 | 0.84 | FAIL |

**FACT.** The month-block design effect is **> 2.5 for all five versions** (2.55, 3.04,
4.86, 2.60, 2.66) — i.e. the iid bootstrap understates the standard error of expectancy by
a factor of **1.6× to 2.2×** once calendar-month dependence is admitted. The consistency of
the sign and rough magnitude across five structurally different strategies is the evidence;
no single version's deff is being leaned on.

**FACT.** The symbol-cluster design effect is **< 1 for four of five versions** (0.73, 0.58,
0.65, 0.84) and only 1.43 for v5. Clustering by symbol *narrows* most of these intervals.

---

## 4. Robustness of the two conclusions

### 4.1 Monte-Carlo error of the bootstrap lower bound

A 2,000-resample percentile bound is itself a random quantity. Each bound was recomputed at
**25 seeds** (20240101 plus 20240102…20240125) and at **50,000 resamples**:

| Ver | scheme | low @2k, seed 20240101 | mean of low over 25 seeds | sd over 25 seeds | min…max over 25 seeds | seeds with low > +0.02 | low @50k |
|---|---|---|---|---|---|---|---|
| 2 | month | **+0.0125** | **+0.0062** | 0.0090 | **−0.0133 … +0.0226** | **2 / 25** | **+0.0097** |
| 2 | symbol | +0.1381 | — | 0.0045 | +0.1249 … +0.1477 | 25 / 25 | +0.1363 |
| 3 | month | −0.0191 | — | 0.0096 | −0.0474 … −0.0098 | 0 / 25 | −0.0246 |
| 5 | month | **−0.0238** | **−0.0231** | 0.0104 | **−0.0488 … −0.0029** | **0 / 25** | **−0.0229** |
| 5 | symbol | **+0.0493** | — | 0.0076 | **+0.0235 … +0.0566** | 25 / 25 | +0.0485 |
| 4 | month | −0.2901 | — | 0.0055 | −0.3065 … −0.2860 | 0 / 25 | −0.2964 |

Reading this honestly:

- **v5's month-block failure is decisive.** The bound sits ~**0.044R below** the `+0.02`
  bar; **0 of 25 seeds** put it above the bar, the seed-to-seed range (−0.049 … −0.003)
  never reaches it, and the 50,000-resample bound is −0.0229. **FACT: v5 fails gate 4 under
  month-blocking.**
- **v2's month-block failure is marginal and must be reported as such.** The bound is only
  **0.0075R below** the bar at the canonical seed and **0.0103R below** at 50,000 resamples,
  against a seed-to-seed sd of 0.0090 — and **2 of the 25 seeds put the bound above +0.02**.
  The best estimate of v2's true month-block lower bound is the 25-seed mean **+0.0062**
  (50k: +0.0097), i.e. below the bar by roughly one MC standard deviation of a
  2,000-resample bound. **FACT: at the canonical seed, at the 25-seed mean, and at 50k
  resamples v2 fails; the margin is ~0.01R and is not robust to the seed at 2,000
  resamples.** Do not report v2's month-block failure as clean.
- **v5's symbol-cluster pass is also narrow**: +0.0493, only 0.029R above the bar, with
  seeds ranging down to +0.0235. It passes at every seed tried, but barely.

### 4.2 Sensitivity to the block definition

Calendar month is one arbitrary block length. The same cluster bootstrap at four calendar
granularities plus symbol (lower bound at seed 20240101; `G` = clusters):

| Ver | iid | day (G) | week (G) | **month (G)** | quarter (G) | symbol (G) |
|---|---|---|---|---|---|---|
| 2 | +0.1129 | +0.0692 (189) | +0.0462 (96) | **+0.0125 (28)** | −0.0236 (11) | +0.1381 (24) |
| 3 | +0.1205 | +0.0702 (180) | +0.0421 (94) | **−0.0191 (28)** | −0.0949 (11) | +0.1644 (24) |
| 4 | −0.1739 | −0.2619 (152) | −0.2836 (100) | **−0.2901 (35)** | −0.3063 (13) | −0.1569 (24) |
| 5 | +0.0901 | +0.0478 (155) | +0.0518 (96) | **−0.0238 (31)** | −0.1508 (12) | +0.0493 (22) |
| 6 † | −0.3553 | −0.4518 (31) | −0.4667 (22) | **−0.6192 (12)** | −0.6806 (9) | −0.3104 (23) |

**FACT.** The lower bound falls **monotonically** as the calendar block lengthens, for every
version. That monotone pattern is the signature of positive dependence in calendar time
that persists well beyond a single trading day. **FACT:** v2 and v5 both clear `+0.02` at
day- and week-blocks and both fail at month- and quarter-blocks; the pass/fail flip for the
approved pair happens **between one week and one month**.

**Caveat (important).** At quarter granularity `G` is only **9–13**. Cluster bootstraps with
fewer than ~30 clusters are unreliable and known to be erratic in both directions; the
quarter column is **indicative only** and no conclusion here rests on it. Month-blocking
(`G` = 28–35) is at the low end of acceptable and is itself worth treating as approximate —
which is a second reason not to read v2's 0.01R miss as decisive.

### 4.3 Independent cross-check — cluster-robust *t* interval

An entirely different construction: `expectancy ± t_{G−1,0.975} · CRSE`, where
`CRSE = √( G/(G−1) · Σ_g (S_g − μ·n_g)² ) / n` is the standard cluster-robust standard error
of the pooled mean. This does not resample at all.

| Ver | month CRSE | t(G−1) | CRSE-*t* low | agrees with (b)? | symbol CRSE | CRSE-*t* low | agrees with (c)? |
|---|---|---|---|---|---|---|---|
| 2 | 0.1286 | 2.052 | **+0.0010** | ✅ FAIL | 0.0668 | +0.1267 | ✅ PASS |
| 3 | 0.1708 | 2.052 | −0.0440 | ✅ FAIL | 0.0733 | +0.1547 | ✅ PASS |
| 4 | 0.1086 | 2.032 | −0.3045 | ✅ FAIL | 0.0382 | −0.1627 | ✅ FAIL |
| 5 | 0.1735 | 2.042 | **−0.0539** | ✅ FAIL | 0.1287 | **+0.0328** | ✅ PASS |
| 6 † | 0.3466 | 2.201 | −0.7015 | ✅ FAIL | 0.1939 | −0.3408 | ✅ FAIL |

**FACT.** The percentile cluster bootstrap and the cluster-robust *t* interval agree on the
pass/fail call at `+0.02R` in **all 10 comparisons**, at every granularity tested. The §1
headline is not an artefact of the percentile method.

### 4.4 No single symbol or month is carrying the result

Leave-one-out on the point estimate (not the CI):

| Ver | full expectancy | worst single-symbol deletion | worst single-month deletion |
|---|---|---|---|
| 2 | +0.2648 | drop `JPM` → **+0.2403** | drop `2023-12` (n=31) → **+0.2071** |
| 5 | +0.3004 | drop `NVDA` (n=20) → **+0.2038** | drop `2023-05` (n=9) → **+0.2207** |

**FACT.** Neither approved strategy's point estimate depends on one name or one month:
the largest single-symbol deletion effect is v5/NVDA at −0.0966R and the largest
single-month deletion is v2/2023-12 at −0.0577R. The clustered CIs widen because of
*many* correlated blocks, not one outlier block.

---

## 5. Why the two clusterings disagree — the structure of these trade sets

**FACT (structure of the OOS trade sets).**

| Ver | OOS entry span | distinct entry days | trades/day (mean) | max trades one day | mean bars held | ETF subset (n, exp) | single-stock subset (n, exp) |
|---|---|---|---|---|---|---|---|
| 2 | 2023-02-03 … 2025-09-05 | 189 | 1.80 | 9 | 5.8 | 204, **+0.2722** | 137, **+0.2538** |
| 3 | 2023-02-03 … 2025-09-05 | 180 | 1.77 | 9 | 8.2 | 189, +0.3087 | 130, +0.3030 |
| 4 | 2022-02-11 … 2025-09-03 | 152 | 2.03 | 17 | 3.2 | 181, −0.1008 | 128, −0.0596 |
| 5 | 2022-02-28 … 2025-09-05 | 155 | 1.27 | 6 | 19.4 | 81, **−0.0074** | 116, **+0.5153** |
| 6 † | 2023-04-10 … 2025-07-24 | 31 | 1.65 | 5 | 6.8 | 37, −0.0636 | 14, +0.3914 |

**FACT.** The 24-symbol universe is **15 ETFs** (`DIA IWM QQQ SPY XLB XLC XLE XLF XLI XLK
XLP XLRE XLU XLV XLY`) and **9 single stocks** (`AAPL AMZN GOOGL HD JPM MSFT NVDA UNH XOM`),
and **all nine single stocks are `SPY` constituents**, each also sitting in exactly one of
the sector ETFs in the set (`AAPL`/`MSFT`/`NVDA`→`XLK`, `AMZN`/`HD`→`XLY`, `GOOGL`→`XLC`,
`JPM`→`XLF`, `UNH`→`XLV`, `XOM`→`XLE`), with seven of the nine also in `DIA` and five in
`QQQ`. Trades entered on the same day are therefore repeated bets on the same underlying
moves.

**HYPOTHESIS (mechanism, consistent with every number above).** The dependence in this
universe runs along the **calendar axis**, not the **symbol axis**:

- Symbol-level *mean* R is fairly homogeneous (v2: ETF +0.2722 vs stock +0.2538; v3: +0.3087
  vs +0.3030), so the between-symbol variance that drives a symbol-cluster bootstrap is
  *smaller* than the within-symbol variance — hence deff < 1 and a narrower interval. A
  symbol-cluster bootstrap corrects for within-symbol serial dependence, which is
  approximately absent here (holding periods are 3–19 bars and re-entries in the same name
  are spread across months).
- Calendar blocks pool 1.3–2.0 trades per day across up to 9–17 simultaneous positions in
  mutually-overlapping instruments, so a single month's block carries one market realisation
  many times over. Monthly mean R for v2 ranges from **−1.026** (2025-03, n=2) to **+2.167**
  (2025-05, n=5), and for v5 from **−1.339** (2025-04) to **+2.812** (2022-02) — far more
  month-to-month dispersion than 1.47/√n per-month sampling noise would produce.

**Therefore (HYPOTHESIS, and the substantive correction to §4.3):** cluster-by-symbol is
**not** a valid diagnostic for the ETF-containment concern §4.3 raises. It *assumes*
independence between clusters — i.e. between `SPY` and `AAPL` — which is exactly the
assumption ETF containment violates. **Cluster-by-calendar-block is the appropriate
instrument for that risk, and (c) should not be cited as reassurance that (b)'s result is
overstated.**

**FACT (a second, separate concentration risk this exposed, for the record).** v5's entire
pre-sealed OOS edge sits in single stocks: its ETF subset expectancy is **−0.0074R on 81
trades** while its 9-stock subset is **+0.5153R on 116 trades**. This is not a bootstrap
question and is not pursued here, but it is a material fact about the weaker of the two
approved strategies and is recorded so a later phase can treat it properly. It is a
*disclosure*, not a proposed change (**R1**: no parameter, filter or universe choice
follows from it here).

**FACT (qualifies a §4.3 standing risk).** §4.3 warns that the per-symbol 60% IS/OOS
boundary "misaligns" across symbols. On snapshot 3 it barely does: 23 of 24 symbols have
**2,234** bars and an identical boundary of **2022-02-10**; only `XLC` differs (1,814 bars,
boundary 2022-10-12). The misalignment risk is real for a future expanded universe but is
**not** a live confound for these numbers.

---

## 6. Answer to the task's question, stated precisely

> *State which approved strategy (if any) would fail gate 4's +0.02R lower bound under (b)
> or (c) — as a diagnostic disclosure, not a gate change.*

**Under (b) block bootstrap by entry calendar month — BOTH approved strategies fail:**

- **version 5, `relative_strength.medium_swing` v0.1.0 — fails decisively.** Month-block
  lower bound **−0.0238R** (50k resamples: −0.0229; cluster-robust *t*: −0.0539), i.e.
  **≈0.044R below** the `+0.02R` bar, stable across 25 seeds and confirmed by an independent
  non-resampling construction.
- **version 2, `trend_continuation.short_swing` v0.1.0 — fails, but marginally.**
  Month-block lower bound **+0.0125R** (50k resamples: +0.0097; cluster-robust *t*:
  +0.0010), i.e. **≈0.01R below** the bar — within about one Monte-Carlo standard deviation
  of a 2,000-resample bound, and **2 of 25 seeds put it above the bar**. Report as *"fails,
  by a margin too small to be robust"*, never as a clean failure.

**Under (c) cluster bootstrap by symbol — neither approved strategy fails.** v2's bound is
**+0.1381R** (comfortable) and v5's is **+0.0493R** (a pass, but only 0.029R clear of the
bar). Per §5, (c) is the *weaker* diagnostic for this universe and its reassurance should be
discounted accordingly.

Non-approved versions, for completeness: **v3** fails under (b) (−0.0191R) and passes under
(c) (+0.1644R) — irrelevant to its actual blocker, which is gate 9. **v4** and **v6** fail
gate 4 under all three schemes, as they already do under (a).

### 6.1 What it would take to clear +0.02R under (b) — HYPOTHESIS

Holding the observed point estimate, per-month structure and stationarity fixed (all three
assumptions are strong; treat as an order-of-magnitude statement only): gate 4 under
month-blocking requires `expectancy > 0.02 + 1.96·SE_month`.

| Ver | observed exp | SE_month | required exp at today's G | required G at today's exp | months available |
|---|---|---|---|---|---|
| 2 | +0.2648 | 0.1286 | **+0.2721** | **≈ 30** | 28 |
| 5 | +0.3004 | 0.1735 | **+0.3601** | **≈ 46** | 31 |

v2 is ~2 further months of the same behaviour from clearing a month-clustered bar; v5 is
~15 further months (≈1.25 calendar years). **This is not a recommendation to wait, to
re-run, or to change anything** — it is the scale of the gap, stated so the disclosure can
be read quantitatively. Under **R8**, live paper is the confirming test and never the
promoting one.

---

## 7. Standing caveats on this diagnostic

1. **Not a gate.** Gate 4 remains the iid bootstrap at `+0.02R`. Nothing here is
   implemented, no threshold moved, no code under `src/` or `tests/` touched.
2. **`G` is small.** Month-blocking gives `G` = 28–35 and quarter-blocking `G` = 9–13.
   Cluster inference below ~30 clusters is approximate; the quarter row is indicative only,
   and even the month row deserves an error bar of its own — which §4.1 supplies.
3. **v2's month-block failure is inside the noise of the procedure.** §4.1. Anyone quoting
   §1 must quote §4.1 with it.
4. **The block bootstrap's ratio estimator has unequal block sizes** (v2: 2–31 trades per
   month; v5: 1–12). This contributes some of the extra width independently of true
   dependence. The CRSE-*t* cross-check (§4.3), which does not resample, agrees on every
   call — which bounds how much of the effect that could be.
5. **Snapshot 3 only.** Snapshots 1, 2 and 4 fail gate 8 (§0.1) and were not analysed.
6. **Pre-sealed only, and no sealed number informed anything here.** All entry dates
   ≤ 2025-09-05; the sealed window opens 2025-09-08.
7. **This diagnostic is not a "look".** No sealed test was computed, read or re-run, so the
   look count is unchanged: **k = 5** per strategy family (§0.1, R2).
8. **Single-stock concentration in v5 (§5) is disclosed, not acted on.**

## 8. Reproduction

- Raw numbers: `docs/research/diagnostics/clustered_bootstrap_all.json` (all CIs at every
  granularity, per-symbol and per-month trade counts, monthly mean R, jackknife, MC-error
  runs).
- Data access was **read-only throughout**. Analysis ran against a consistent
  `sqlite3 .backup` copy of `data/signalforge.sqlite` at
  `$TMPDIR/scratch-clustered_bootstrap_all.sqlite`; the live database was never opened for
  write, and no writing entry point (`evaluate_promotion`, `backtest-*`, sensitivity) was
  invoked. `run_backtest` / `PriceSeries.load` / `bootstrap_ci` contain no
  `session.add/flush/commit`.
- Load-bearing code references: `src/signalforge/backtest/montecarlo.py:15-21,30-34,42-52`;
  `src/signalforge/research/backtest_runner.py:158-160,195-212,228`;
  `src/signalforge/research/promotion.py:679-688`;
  `src/signalforge/config/research.py:102`.
