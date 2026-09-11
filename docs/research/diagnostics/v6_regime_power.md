# W2 diagnostic — `volatility_breakout.short_swing` v0.1.0 (version 6): regime availability and statistical power

**Scope.** Hypothesis **H12** and `STRATEGY_COMPLETION_MAP.md` §0.6 / §2.3, plus the
clustered-bootstrap diagnostic §3(a) asks for. Pre-sealed span only
(**2016-09-10 → 2025-09-07**), dataset snapshots **3** (`universe_24_ex_meta`) and
**2** (`universe_25_baseline`), source `massive`, proxy `SPY`.

**Method / provenance (FACT).** Every number below was computed against a read-only
copy of the live database (`sqlite3` backup API over a `mode=ro` connection, taken
2026-09-10) at `$TMPDIR/scratch-v6_regime_power.sqlite`. No command in this work wrote
to `data/signalforge.sqlite`; no promotion, sensitivity or sealed entry point was
invoked; no network call was made. Strategy trades were reproduced in-process with
`research.backtest_runner.run_strategy_over_universe` (no `session.add/flush/commit`)
using the frozen cost model (`commission 0`, `slippage_bps=3.0`,
`half_spread_fill_penalty=True`, `backtest/costs.py:11-16`). Regime labels use
`backtest/regime.py:label_regimes` — the same function gate 6 calls
(`research/promotion.py:740-741`).

**Reproduction check (FACT).** The recomputation matches the stored evaluations
exactly, so the diagnostic is measuring the same objects the gates measured:

| | stored (eval 36 / 30) | recomputed |
|---|---|---|
| v6 snap 3 pre-sealed trades | 211 | **211** |
| v6 snap 3 OOS trades / expectancy | 51 / +0.0613R | **51 / +0.06135R** |
| v6 snap 3 gate-6 buckets | bull 167 / bear 0 / range 30 | **167 / 0 / 30** |
| v6 snap 2 pre-sealed trades | 213 | **213** |
| v6 snap 2 OOS trades / expectancy | 52 / +0.0541R | **52 / +0.05408R** |
| v6 snap 2 gate-6 buckets | bull 168 / bear 0 / range 31 | **168 / 0 / 31** |
| v2 snap 3 OOS | 341 / +0.2648R | **341 / +0.2648R** |
| v5 snap 3 OOS | 197 / +0.3004R | **197 / +0.3004R** |

**Sealed-window discipline (R1).** No quantity inside 2025-09-08 → 2026-09-08 was
computed, including proxy regime labels. H12 as written asks for a count "over both
windows"; the 2-year report window (2024-08 → 2026-09) straddles the seal, so only its
**pre-sealed portion** (2024-08-01 → 2025-09-07) is reported below, and the sealed
portion is deliberately left uncomputed. The baseline sealed-look count for this
strategy remains **k = 5** (§0.1); nothing here creates a new look.

---

## 1. Headline

**H12 is refuted as stated, and replaced by a sharper mechanism.** The pre-sealed span
is *not* regime-homogeneous: it contains **267 bear-labelled proxy sessions** out of
2,234 (11.95%), including a 144-session bear stretch in 2022. The reason v6 has zero
bear trades is not an absence of bear days. It is that **v6's own regime gate is shut
on 93% of them**: `breakout.py:102` requires `not ctx.regime.risk_off`, and
`research/regime.py:41-42` defines `risk_off = (trend is BEAR) or (vol is HIGH)`. Only
**19 of the 267** bear-labelled sessions (7.1%) are sessions on which v6 was permitted
to take a long at all — and all 19 fall in just two years (3 in 2020, 16 in 2023).

Consequences, all of which change the §2.3 lever ordering:

1. **Gate 6's bear bucket is a breadth problem with a hard calendar ceiling, not a
   strategy-quality problem.** The supply of gate-open bear *proxy sessions* is fixed
   by the calendar and by a filter v6 shares with v2; only the symbol count can raise
   the symbol-day count. §2.3's "Falsified (for gate 6) if the bear bucket remains
   under 10 on the expanded snapshot — a strategy finding, not a data finding" is
   **wrong as a falsification rule**: at 24 symbols the bear rate is unmeasured
   (0 events in 432 opportunities), so an expanded run that still shows < 10 bear
   trades would be a *power* outcome, not a strategy finding.
2. **The 14 unbucketed trades cannot rescue gate 6.** All 14 are warmup, all fall
   2017-01-05 → 2017-07-25, and none can be labelled with any data in the database.
3. **Gate 4 needs ~2,550 ten-year symbols at the current point estimate** — more than a
   150-name universe can deliver by a factor of ~17, and more than the whole
   `massive_grouped` screen has history for. §2.3's H11 stands and strengthens.
4. **A month-clustered bootstrap widens every CI in the program by ~1.6×**, and under
   it **v2 and v5 would also fail gate 4**. Reported as a diagnostic only (R4 permits
   a stricter statistic alongside the gate); it is not a proposal to change gate 4.
5. **v6's entire positive OOS point estimate rests on one month.** Dropping
   2023-12 (7 of 51 trades) takes OOS expectancy from **+0.0613R to −0.2623R**.

---

## 2. Proxy regime-day counts (pre-sealed, `label_regimes` on SPY)

**FACT.** `PriceSeries.load(SPY, 2016-09-10, 2025-09-07, source="massive")` returns
**2,234 sessions**, first bar **2016-10-17**, last **2025-09-05**. The proxy series is
loaded independently of the universe (`promotion.py:740`), and SPY is in both snapshots
with identical `massive` bars, so **the regime-day counts are byte-identical for
snapshot 3 and snapshot 2.** Every count in this section therefore applies to both.

`TREND_LOOKBACK = 200` (`backtest/regime.py:20`), so sessions 1–200
(**2016-10-17 → 2017-08-02**) are `"warmup"` and match none of gate 6's three branches
(`promotion.py:745-750`).

### 2.1 Full pre-sealed span

| `label_regimes` raw label | sessions | gate-6 bucket | sessions | share |
|---|---:|---|---:|---:|
| `bull_lowvol` | 884 | | | |
| `bull_highvol` | 508 | **bull** | **1,392** | 62.3% |
| `bear_highvol` | 227 | | | |
| `bear_lowvol` | 40 | **bear** | **267** | **11.95%** |
| `range_bound` | 375 | **range** | **375** | 16.8% |
| `warmup` | 200 | *(no bucket)* | **200** | 9.0% |
| **total** | **2,234** | | **2,234** | |

These are a census of the realised calendar, not a sample, so no standard error
attaches to them.

### 2.2 By calendar year, with v6's own eligibility overlaid

"gate-open" = the session's research-regime state is **not** `risk_off`, i.e. the day on
which v6 (and v2) may open a long at all. Format `all / gate-open`.

| year | sessions | gate-open | bull | bear | range |
|---|---:|---:|---:|---:|---:|
| 2016 | 53 | 53 | 0/0 | 0/0 | 0/0 |
| 2017 | 251 | 209 | 104/84 | 0/0 | 0/0 |
| 2018 | 251 | 93 | 156/87 | **22/0** | 73/6 |
| 2019 | 252 | 176 | 169/131 | **14/0** | 69/45 |
| 2020 | 253 | 113 | 172/110 | **48/3** | 33/0 |
| 2021 | 252 | 212 | 252/212 | 0/0 | 0/0 |
| **2022** | 251 | **3** | 24/0 | **144/0** | 83/3 |
| 2023 | 250 | 226 | 155/152 | **21/16** | 74/58 |
| 2024 | 252 | 170 | 252/170 | 0/0 | 0/0 |
| 2025 (to 09-05) | 169 | 82 | 108/78 | **18/0** | 43/4 |
| **total** | **2,234** | **1,337** | 1,392/1,024 | **267/19** | 375/116 |

FACT: **2022 has 251 sessions of which 3 are gate-open.** v6 took **zero trades in
2022** (entry-year counts: 2017: 25, 2018: 11, 2019: 63, 2020: 33, 2021: 28, **2022: 0**,
2023: 21, 2024: 9, 2025: 21). The single largest bear episode in the span is invisible
to this strategy by construction.

FACT: the 25 contiguous bear episodes are listed in the JSON sibling; the longest are
**2022-04-22 → 2022-08-09**, **2022-08-26 → 2022-11-10**, **2020-03-11 → 2020-04-28**
and **2018-12-07 → 2019-01-15**. Of these, **only** 2020-03/04 (3 days) and the 2023
episodes contribute any gate-open session.

### 2.3 Cross-tab: gate-6 bucket × v6 eligibility (proxy sessions)

| bucket | gate-open | gate-shut (`risk_off`) | gate-open share |
|---|---:|---:|---:|
| bull | 1,024 | 368 | 73.6% |
| **bear** | **19** | **248** | **7.1%** |
| range | 116 | 259 | 30.9% |
| warmup | 178 | 22 | 89.0% |
| **all** | **1,337** | **897** | 59.8% |

*(The entry-date version — gate evaluated on the prior session, since the engine fills
at `t+1`, `engine.py:108,134` — gives bear 18/249; the difference is one boundary day.)*

### 2.4 Pre-sealed portion of the 2-year report window

**FACT.** 2024-08-01 → 2025-09-07: **275 sessions — bull 214, range 43, bear 18** — and
**zero gate-open bear sessions**.

So H12's premise ("the 2-year report window plausibly contained no bear-labelled proxy
days at all") is **false on its face** — the window's pre-sealed portion has 18 bear
days — while H12's *conclusion* about the report is right for a different reason: none
of those 18 days was tradeable by v6. The map's own qualifier ("H12 explains the
*report*, not the *gate*") is also superseded: **the same mechanism explains the gate.**

---

## 3. v6 trades per regime, including the unbucketed count

**FACT**, recomputed and matching evals 36 and 30 exactly.

| | snapshot 3 (24 sym) | snapshot 2 (25 sym) |
|---|---:|---:|
| pre-sealed trades (`full.trades`) | **211** | **213** |
| bull | 167 | 168 |
| **bear** | **0** | **0** |
| range | 30 | 31 |
| bucketed | 197 | 199 |
| **unbucketed** | **14 (6.64%)** | **14 (6.57%)** |
| in-sample / out-of-sample | 160 / 51 | 161 / 52 |
| OOS expectancy | +0.0613R | +0.0541R |
| OOS per-trade sd (empirical) | **1.5242** | **1.5101** |

The map's §0.3 implied sd for v6, **1.554**, recovered by inverting the stored bootstrap
half-width, is confirmed against the empirical **1.5242** (2.0% high). Both are used
below where it matters; the difference never changes a verdict.

### 3.1 The 14 unbucketed trades are all warmup, and all unlabelable

**FACT.** All 14 fall between **2017-01-05 and 2017-07-25**, i.e. inside the proxy's
200-session warmup, which ends **2017-08-02**. None is a "no proxy bar on the entry
date" case. Identical set on both snapshots:

`AAPL 2017-01-10`, `AMZN 2017-01-25`, `AMZN 2017-02-21`, `GOOGL 2017-01-09`,
`GOOGL 2017-01-26`, `HD 2017-03-17`, `QQQ 2017-02-16`, `QQQ 2017-05-16`,
`QQQ 2017-07-25`, `SPY 2017-05-16`, `XLK 2017-01-23`, `XLK 2017-02-21`,
`XLK 2017-07-25`, `XLV 2017-01-05`.

Their pooled expectancy is **−0.0201R (sd 1.0008, SE 0.2675, n = 14)** — indistinguishable
from zero and from the rest of the sample.

**FACT (this closes §2.3's open speculation).** `SPY`'s `massive` history begins
**2016-10-17** (2,487 bars to 2026-09-09; the only other SPY source is
`massive_grouped`, 2025-01-03 onward, which R6 bars from research). Loading SPY from
`2000-01-01` returns the same 2,234 sessions, and the first labelable session under the
**longest possible** proxy is still **2017-08-03**. There is no data in the database
that can label these 14 trades.

**HYPOTHESIS (well supported, cannot be made FACT without pre-2016 bars):** all 14 would
label **bull**. On each of the 11 distinct entry dates SPY closed above a rising
truncated 100-session SMA, with a positive 10-session SMA slope on every one (e.g.
2017-01-05 close 226.40 vs SMA100 219.55, slope +1.264; 2017-07-25 close 247.42 vs
239.73, slope +0.930). The map's suggestion that "some of which may be genuine
bear-regime entries" is therefore **not supportable** — the 14 cannot move gate 6.

### 3.2 Is zero bear trades evidence of a bear-specific defect?

**No — it is under 2 SE, so it is not evidence.** Restricting to **gate-open symbol-days**
(the only days on which an entry was possible), across the 24 snapshot-3 symbols:

| bucket | symbol-days | gate-open symbol-days | v6 entries | entry rate per 1,000 gate-open symbol-days |
|---|---:|---:|---:|---|
| bull | 33,221 | 24,399 | 167 | **6.845 ± 0.530** |
| **bear** | 6,408 | **432** | **0** | **0.000** (95% upper bound **6.944**, rule of three) |
| range | 8,967 | 2,880 | 30 | **10.417 ± 1.902** |
| warmup | 4,577 | 4,071 | 14 | 3.439 ± 0.919 |

(Rates are Poisson; SE = √k / N.)

**DERIVED.** If v6's bear-bucket entry rate equalled its bull-bucket rate, the expected
number of bear trades over the whole pre-sealed span would be
`6.845e-3 × 432 = ` **2.96**, Poisson sd **1.72**. Observing 0 is **1.72 SE** below that
expectation — **under 2 SE, therefore not evidence** of a bear-specific block. `P(0 | λ =
2.96) = 5.2%`.

The honest statement is: **v6's bear-regime entry rate has never been measured.** Zero of
432 opportunities is consistent with anything from 0 to 6.9 entries per 1,000 gate-open
symbol-days.

**Contrast with v2 (FACT, same proxy, same 24 symbols, same `risk_off` gate).** v2 takes
22 bear-bucket trades on the same 432-ish gate-open bear symbol-days — a rate of
**50.93 ± 10.86** per 1,000 — nominally *above* its own bull rate of **38.49 ± 1.26**,
though that difference is only 1.14 SE and is not itself evidence of anything. The point
that matters is that the rate is demonstrably **non-zero**: gate-open bear days are
tradeable; **v6 simply fires ~5.5× less often
than v2 overall** (§4). The bear-bucket zero is the frequency problem, not a separate one.

---

## 4. Signal frequency per symbol-year (snapshot 3, pre-sealed)

**FACT.** 53,196 symbol-bars over 24 symbols = **211.1 symbol-years** (at 252
sessions/yr). v6 produced **211** trades → **1.00 trades per symbol-year**, i.e. one
entry per ~252 symbol-bars (**0.397% of symbol-bars**). For comparison on the identical
span and universe: **v2 = 5.54/symbol-year** (1,169 trades), **v5 = 2.68/symbol-year**
(566 trades).

| symbol | bars | trades | trades/yr | % of bars |
|---|---:|---:|---:|---:|
| SPY | 2,234 | 28 | 3.16 | 1.25% |
| QQQ | 2,234 | 21 | 2.37 | 0.94% |
| DIA | 2,234 | 19 | 2.14 | 0.85% |
| XLK | 2,234 | 18 | 2.03 | 0.81% |
| XLY | 2,234 | 12 | 1.35 | 0.54% |
| GOOGL | 2,234 | 11 | 1.24 | 0.49% |
| XLI | 2,234 | 11 | 1.24 | 0.49% |
| AMZN | 2,234 | 10 | 1.13 | 0.45% |
| MSFT | 2,234 | 10 | 1.13 | 0.45% |
| XLF | 2,234 | 9 | 1.01 | 0.40% |
| XLC | 1,814 | 9 | 1.25 | 0.50% |
| AAPL | 2,234 | 8 | 0.90 | 0.36% |
| XLB | 2,234 | 8 | 0.90 | 0.36% |
| XLP | 2,234 | 5 | 0.56 | 0.22% |
| HD | 2,234 | 4 | 0.45 | 0.18% |
| IWM | 2,234 | 4 | 0.45 | 0.18% |
| XLRE | 2,234 | 4 | 0.45 | 0.18% |
| JPM | 2,234 | 3 | 0.34 | 0.13% |
| UNH | 2,234 | 3 | 0.34 | 0.13% |
| XLE | 2,234 | 3 | 0.34 | 0.13% |
| XLU | 2,234 | 3 | 0.34 | 0.13% |
| XLV | 2,234 | 3 | 0.34 | 0.13% |
| XOM | 2,234 | 3 | 0.34 | 0.13% |
| NVDA | 2,234 | 2 | 0.23 | 0.09% |

**Notes for the design phase.**
- The four broad-index ETFs (SPY, QQQ, DIA, XLK) supply **86 of 211 trades (40.8%)** on
  4 of 24 symbols. §3(a)'s warning that expansion is a *distribution shift* bites hardest
  here: a 150-name single-stock universe removes the very symbols that generate most of
  v6's current sample.
- The engine takes at most one position per symbol at a time (`engine.py:149`,
  `t = exit_idx + 1`), so trade count is capped per symbol. With a 10-session time stop
  and ~1 trade/symbol-year, that cap is nowhere near binding — so **linear scaling with
  symbol count is a sound assumption** for the projections in §5.
- Per-year trade counts are extremely uneven: 2019 alone contributes 63 of 211 (29.9%),
  and 2022 contributes 0.

---

## 5. Exact sample sizes gates 2 / 4 / 5 / 6 require

Formula from §0.3: gate 4 clears when `exp > 0.02 + 1.96·sd/√n`, i.e.
**`n > (1.96·sd / (exp − 0.02))²`**. All rows use v6's observed OOS point estimate
**+0.0613R** and the §0.3 implied per-trade sd **1.554** (empirical 1.5242 in brackets).
"Breadth multiple" is relative to the current OOS n = 51 / current 24 symbols, assuming
the linear scaling justified in §4.

| gate | requirement | have | **need** | breadth multiple | ≈ symbols at 9.4y |
|---|---|---:|---:|---:|---:|
| **2** `min_oos_trades` | OOS n ≥ 30 | 51 | **30** | 0.59× | **≈ 14** — already met |
| **4** `bootstrap_ci` | iid 95% CI low > +0.02R | n = 51, low −0.3553R | **n = 5,426** (empirical sd: 5,220) | **106.4×** | **≈ 2,554** |
| **5** `parameter_sensitivity` | every grid cell ≥ 15 trades | thinnest cell 19 | **15** | 0.79× | already met |
| **5** *(for the positive-fraction to mean anything — see below)* | per-cell n giving a 95%-reliable sign | 51 | **1,736** | **34.0×** | **≈ 816** |
| **6** `regime_coverage` | ≥ 10 bear trades | 0 of 432 gate-open bear symbol-days | **1,461 gate-open bear symbol-days** *at the bull rate* | **3.38×** | **≈ 81** |

### 5.1 Gate 4 — the hurdle as a function of n (sd = 1.554)

| n | `1.96·sd/√n` | required expectancy | v6 at +0.0613R |
|---:|---:|---:|---|
| 51 (today) | 0.4265 | **+0.4465R** | fail by 0.385R |
| 100 | 0.3046 | +0.3246R | fail |
| 200 | 0.2154 | +0.2354R | fail |
| 319 (6.25× breadth, §3a) | 0.1705 | **+0.1905R** | fail |
| 500 | 0.1362 | +0.1562R | fail |
| 1,000 | 0.0963 | +0.1163R | fail |
| 2,000 | 0.0681 | +0.0881R | fail |
| **5,426** | 0.0413 | **+0.0613R** | breaks even |

**DERIVED, the load-bearing figure for §2.3.** 5,426 OOS trades at v6's measured
frequency of 1.00 trades/symbol-year, with OOS ≈ 24.2% of trades
(51/211, from the per-symbol 60/40 split at `backtest_runner.py:29,158-159`), implies
≈ 22,400 pre-sealed trades over ~8.87 years, i.e. **≈ 2,554 symbols each with 10 years of
`massive` history**. FACT: the database holds **2,658 instruments in total**, of which
**26** have `massive` (10-year) history and 2,655 have only `massive_grouped` (2025-01
onward, and R6-barred from research). FACT: `UniverseFilters.max_universe_size = 150`
(`config/research.py:139`). **Gate 4 at the current point estimate is not reachable by
universe expansion at any feasible scale.** This corroborates and sharpens §2.3's H11
("the edge magnitude is genuinely insufficient") as the leading hypothesis.

### 5.2 Gate 5 — the positive-fraction test is a coin flip at n = 51

**DERIVED.** If the true per-cell expectancy equals the observed +0.0613R with
sd 1.554, then a grid cell of n = 51 reads positive with probability
`Φ(0.0613 / (1.554/√51)) = ` **0.611**. Under independence, `P(≥ 6 of 9 positive)` —
gate 5's 60% floor — is **0.510**.

That is the whole explanation of the snapshot-3 / snapshot-4 flip recorded in §2.3
(0.667/0.750 pass on snapshot 3 vs 0.556/0.500 fail on snapshot 4 from adding one
symbol): **gate 5's positive fraction for v6 is, statistically, a fair coin.** It is not
evidence of robustness on snapshot 3 and not evidence of fragility on snapshot 4.

To make each cell's *sign* 95% reliable at this effect size needs **1,736 trades per
cell** (99%: 3,472) — and the baseline cell holds essentially the whole OOS sample, so
that is ~34× the current OOS n, ≈ 816 symbols.

### 5.3 Gate 6 — how much breadth buys 10 bear trades

The supply of gate-open bear **proxy sessions** (19 in nine years) is fixed by the
calendar and the shared `risk_off` filter; only symbol count scales the symbol-day count.

- Today: **432** gate-open bear symbol-days (24 symbols).
- At v6's bull-bucket rate (6.845 per 1,000), 10 bear trades need **1,461** gate-open bear
  symbol-days = **3.38× breadth ≈ 81 symbols**.
- At 150 symbols (6.25×, §3a): 2,700 gate-open bear symbol-days, Poisson mean **18.5**,
  `P(≥ 10) = 0.988`.

**CAVEAT, and it is the important one.** Both projections assume the counterfactual
`bear rate = bull rate`, which the data cannot support *or* refute (0 of 432, §3.2).
Using the rule-of-three 95% upper bound instead (6.944 per 1,000), the 95% upper bound on
bear trades at 150 symbols is **18.8** — the *upper* bound, with a lower bound of **0**.
So: **a 150-name expansion is likely but not guaranteed to clear gate 6, and if it does
not, that outcome carries no information about the strategy.** This must be pre-registered
before the expanded run, per §2.3's own instruction not to treat an expected failure as
new information.

**Corrected falsification rule for H12 (replaces §2.3's).** H12 is falsified only if,
on an expanded snapshot with **≥ 1,461 gate-open bear symbol-days**, the bear bucket is
still under 10 trades. Below that threshold the test has no power and must not be run as
a falsification.

---

## 6. Clustered / block bootstrap of OOS expectancy

**Rationale (R4-permitted diagnostic, §3(a)).** `backtest/montecarlo.py:30-33` resamples
the per-trade R vector **iid**. Snapshot 3 is 15 ETFs and 9 single names whose entries
cluster in time; trades entered in the same month share a market state. A cluster
bootstrap that resamples **entry months** (with replacement, same number of clusters,
2,000 resamples, seed 20240101, percentile CI — the same convention gate 4 uses) is the
matched stricter statistic. **This is reported alongside the gate-4 iid CI, not in place
of it. It is not a proposal to change gate 4 or any threshold.**

| ver | OOS n | month clusters | expectancy | **iid 95% CI** | iid half-width | **month-cluster 95% CI** | cluster half-width | **ratio** | n_eff | ESS haircut |
|---|---:|---:|---:|---|---:|---|---:|---:|---:|---:|
| **v6** | 51 | 12 | **+0.0613R** | [−0.3553, +0.4979] | 0.4266 | **[−0.6248, +0.7638]** | **0.6943** | **1.628** | **19.3** | 62% |
| **v2** | 341 | 28 | **+0.2648R** | [+0.1129, +0.4143] | 0.1507 | **[+0.0156, +0.5029]** | **0.2436** | **1.617** | **130.5** | 62% |
| **v5** | 197 | 31 | **+0.3004R** | [+0.0901, +0.5046] | 0.2072 | **[−0.0279, +0.6514]** | **0.3396** | **1.639** | **73.3** | 63% |

(`n_eff = n / ratio²`.)

### 6.1 How much wider — and how stable is the answer

**FACT.** Over 10 independent seeds the month-cluster / iid half-width ratio is:

| ver | mean ratio | sd over seeds | range | analytic CR1 cluster-robust SE ratio | moving-block ratio (L = n^{1/3}) | same-day-cluster ratio |
|---|---:|---:|---|---:|---:|---:|
| v6 | **1.638** | 0.044 | 1.584–1.718 | **1.624** | 1.281 (L = 4) | 1.222 |
| v2 | **1.595** | 0.037 | 1.542–1.653 | **1.618** | 1.439 (L = 7) | 1.277 |
| v5 | **1.593** | 0.073 | 1.477–1.692 | **1.637** | 1.417 (L = 6) | 1.252 |

Three independent estimators agree: **the iid bootstrap understates the half-width of
OOS expectancy by ~1.6×**, equivalently the effective sample size is **~38% of nominal
n**. The analytic CR1 sandwich SE (month clusters) reproduces the bootstrap ratio to
within 0.03 in all three cases, and the ratio is nearly identical across three strategies
with very different n — which is what one expects if the dependence is a shared
market-state factor rather than anything strategy-specific.

Same-day clustering alone (co-entry on one session) explains only ~1.22–1.28× of it; the
remaining widening comes from **within-month regime persistence**, which the day-cluster
bootstrap does not capture. §3(a)'s statement that "every CI in this document is too
narrow" is confirmed and now quantified: **too narrow by a factor of ~1.6, so every
required-n figure in §0.3 is too small by a factor of ~2.6** (1.6²). Restated:

| gate-4 required OOS n for v6 | iid basis | month-cluster basis (×2.65) |
|---|---:|---:|
| at +0.0613R | 5,426 | **≈ 14,380** |

### 6.2 Gate 4 verdicts under each statistic

| ver | iid CI low | verdict (gate 4 as coded) | month-cluster CI low | verdict under the stricter statistic |
|---|---:|---|---:|---|
| v6 | −0.3553 | **FAIL** | −0.6248 | FAIL |
| v2 | +0.1129 | **PASS** | **+0.0156** | **would FAIL** (needs > +0.02) |
| v5 | +0.0901 | **PASS** | **−0.0279** | **would FAIL** |

**This is a disclosure, not a finding against the two approved strategies' status.**
Gate 4 is defined as the iid bootstrap (`config/research.py:102`,
`montecarlo.py:18-20,30-33`); v2 and v5 passed the gate that exists, and R4 forbids
changing it. But the operator should know that **the margin by which the two live
PAPER_APPROVED strategies clear gate 4 does not survive clustering by entry month** —
v2 by 0.0044R and v5 by −0.0479R against a +0.02R bar. This compounds §0.3's standing
caveat that v5's sealed evidence is 0.79 SE. It is a reason to weight the live paper
probation heavily, not a reason to re-run anything.

### 6.3 v6's point estimate is one month deep

**FACT.** v6's 51 OOS trades span **2023-04-10 → 2025-07-24** and occupy only **12
distinct entry months**, the largest holding 14 trades (2025-06, 27% of the sample):
2023-04:5, 2023-05:3, 2023-07:2, 2023-09:2, 2023-11:2, 2023-12:7, 2024-02:1, 2024-05:5,
2024-10:3, 2025-02:2, 2025-06:14, 2025-07:5.

Leave-one-month-out expectancy:

| month dropped | n | that month's own expectancy | remaining OOS expectancy |
|---|---:|---:|---:|
| **2023-12** | **7** | **+2.0955R** | **−0.2623R** |
| 2023-11 | 2 | +1.4887R | +0.0031R |
| 2023-05 | 3 | +0.8150R | +0.0142R |
| … | | | |
| 2024-05 | 5 | −0.4607R | +0.1181R |
| 2025-07 | 5 | −0.8406R | +0.1594R |
| 2023-04 | 5 | −0.9695R | +0.1734R |

**Removing a single month — 7 trades of 51 — flips gate 3 from a pass (+0.0613R) to a
clear fail (−0.2623R).** The shift is −0.3236R = 1.52 iid SE, 0.93 cluster SE. The same
exercise on v2 moves the estimate by at most ±0.067R and never changes its sign; on v5
by at most ±0.080R, also never changing sign. **v6's gate-3 pass is the least robust
single number in the program**, and §2.3's characterisation of gate 3 as a pass with
"the smallest positive margin of any version" understates it: with a 12-cluster sample
it is not a margin at all.

For comparison, §0.4's modelled cost for `volatility_breakout` is **0.042R per trade**,
68% of the +0.0613R estimate — so the pre-cost estimate is ≈ +0.103R and the *entire*
post-cost edge sits inside the sampling noise of one month.

**Methodological caveat (HYPOTHESIS about the estimator, not the strategy).** A cluster
bootstrap with **G = 12** clusters (v6) is itself imprecise; with few clusters the
percentile interval tends to be conservative in some regimes and anti-conservative in
others. That is why the CR1 analytic SE and the moving-block bootstrap are reported
alongside: all three point the same way, and the ratio is stable across v2 (G = 28) and
v5 (G = 31) where the estimator is better behaved. Treat 1.6× as accurate to ~±0.1, not
to 3 significant figures.

---

## 7. What this changes in `STRATEGY_COMPLETION_MAP.md` §2.3

| §2.3 statement | status after this diagnostic |
|---|---|
| H12: "the 2-year report window plausibly contained no bear-labelled proxy days at all" | **Refuted.** Its pre-sealed portion has 18 bear days of 275. The report's zero bear trades is explained by **zero gate-open** bear days, not zero bear days. |
| H12: "explains the *report*, not the *gate*" | **Superseded.** The same mechanism (`not ctx.regime.risk_off`, `breakout.py:102`) explains the gate: 19 gate-open bear sessions in nine years. |
| "the 14 unbucketed … some of which may be genuine bear-regime entries" | **Not supportable.** All 14 are 2017-01→2017-07 warmup, unlabelable with any data in the DB; all 11 distinct dates sit above a rising SPY SMA. |
| Lever 1: expansion "addresses gates 2, 5 and 6" | **Gate 2 already met** (needs 30, has 51). **Gate 5's cell floor already met** (thinnest cell 19 ≥ 15) — what expansion actually fixes is that gate 5's positive fraction is currently a coin flip (P(pass) = 0.51). **Gate 6 plausibly fixed at ~81+ symbols, but on an unmeasured rate.** |
| Lever 2: "diagnose regime availability before anything else" | **Done — this document.** Availability is the binding constraint, and it is a property of the shared regime gate, not of the contraction filter. |
| H11 "leading hypothesis" | **Strengthened.** Gate 4 needs ≈ 2,554 ten-year symbols on the iid bootstrap, ≈ 6,800 once entry-month clustering is accounted for; the DB has 26. |
| Gate 6 falsification rule | **Replaced** (§5.3): falsification requires ≥ 1,461 gate-open bear symbol-days on the expanded snapshot. |

**A design implication that is legitimately motivated on pre-sealed data only
(HYPOTHESIS, for the design phase to score).** The parameter that actually gates v6's
bear-regime coverage is not `contraction_max` or `channel` — it is the inherited
`not ctx.regime.risk_off` conjunct at `breakout.py:102`, which excludes *every*
high-volatility session, bull or bear (`regime.py:41-42`). That is a strange filter for a
**volatility-contraction breakout**: `risk_off` fires on `Vol.HIGH`, defined as the
proxy's 20-day realised vol above 1.15× its own trailing median (`regime.py:79-85`),
while the strategy's own entry condition already demands *contracted* ATR on the traded
symbol. The two vol filters are stacked — one on the index, one on the name — and the
index one costs 368 bull sessions and 248 bear sessions. Note also that gate 5's grid
(`promotion.py:199-208`) perturbs neither, consistent with §0.5's general finding that
"the decisive parameter of a v0.2.0 is exactly the one gate 5 will not test". **No sealed
number informs this observation**; it rests entirely on pre-sealed proxy-session counts
and source reading. Any such change ships as `VERSION = "0.2.0"` (R3/R7), counts as a
variant under R5, and takes the sealed-look count from k = 5 to k = 6.

---

## 8. Standing caveats

1. **Under 2 SE is not evidence.** 0 bear trades vs 2.96 expected is 1.72 SE. The v6
   bear entry rate is *unmeasured*, not measured-as-zero.
2. All required-n figures assume the per-trade sd is constant as the universe grows.
   §3(a) argues a single-name universe changes gap behaviour, idiosyncratic vol and
   spread, all of which plausibly **raise** sd — so the required-n figures are lower
   bounds twice over (once for clustering, once for sd).
3. Linear scaling of trade count with symbol count is justified (§4) but is a projection.
4. The month-cluster ratio ≈ 1.6 is estimated on 12–31 clusters; treat it as ±0.1.
5. Regime-day counts are a census of one realised calendar. A different nine years would
   give different counts; nothing here estimates the *long-run* frequency of gate-open
   bear days. In particular the 19 gate-open bear sessions come from two years only, so
   the 3.38× breadth figure in §5.3 is specific to this span.
6. Cost is unchanged and unmodelled per-symbol (`backtest_runner.py:205-206` passes no
   `spread_bps`): every projection above holds costs at the current flat 11 bps round
   trip, which §0.4 shows is already 0.042R — 68% of v6's point estimate — and which an
   expanded universe would raise.
7. Nothing in this document is derived from the sealed window; no sealed quantity was
   computed; the sealed-look count is unchanged at **k = 5**.

**Raw numbers:** `docs/research/diagnostics/v6_regime_power.json`.
