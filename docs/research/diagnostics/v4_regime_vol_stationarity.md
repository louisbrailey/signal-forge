# W2 diagnostic — `mean_reversion.short_swing` v0.1.0 (version 4)

## Regime-conditioned expectancy (H6) and entry-rate stationarity (H9)

Produced 2026-09-10. Scope: `STRATEGY_COMPLETION_MAP.md` §2.2 hypotheses **H6**
(volatility blindness) and **H9** (fixed z-threshold under non-stationary vol).
Raw numbers: `docs/research/diagnostics/v4_regime_vol_stationarity.json`.

---

## 0. Compliance statement

**FACT.** Every number in this document is computed over the **pre-sealed span
`2016-09-10 .. 2025-09-07`** only. The sealed window on snapshots 2 and 3 begins
**2025-09-08** (`strategy_sealed_test` ids 8, 13: `window_start = 2025-09-08`),
and `pre_sealed_end = sealed_start − 1 day` (`promotion.py:555`). No sealed bar was
loaded, no sealed number is cited, and nothing here is motivated by a sealed
result. Snapshot 1 (sealed start 2025-09-07) is not used.

**FACT.** No database write occurred. All work ran through a read-only SQLAlchemy
engine (`sqlite+pysqlite:///file:…?mode=ro&uri=true`) against
`data/signalforge.sqlite`, using `PriceSeries.load`, `research.regime.regime_lookup`,
`strategies.base.signal_fn_for` and `backtest.engine.run_backtest` — none of which
contain `session.add`/`flush`/`commit`. No file under `src/` or `tests/` was
modified. No package installed, no provider called.

**Sealed-look count: k = 5** (§0.1 / R2 of the map). This diagnostic adds **zero**
looks — it never evaluates gate 9.

**R4 note.** Section 4 adds a *date-clustered* standard error alongside the gate-4
iid bootstrap. Under R4 this is an explicitly permitted **stricter** reported
statistic, not a gate change. No threshold was touched.

---

## 1. Method and reproduction check

The strategy's own regime view was reconstructed exactly as the strategy sees it:

**FACT** (`strategies/base.py:31-45`): `signal_fn_for` looks the regime up by
`series.dates[t]` — the **signal bar**, index `t`. **FACT** (`engine.py:99, 129`):
the engine fills at `entry_idx = t + 1`, so `SimTrade.entry_date` is the bar
*after* the one whose regime gated the entry. This diagnostic keys every trade to
the **signal-bar** regime (the decision-relevant one — a `vol is HIGH` filter would
be evaluated there). Entry-bar labels are reported too and differ only marginally
(snapshot 3: 413 vs 435 HIGH-vol trades).

Note in passing (**FACT**, not a defect this diagnostic acts on):
`backtest_runner.py:216-219` builds its own `by_regime` breakdown keyed on
`tr.entry_date`, i.e. one bar *later* than the label the strategy consulted. The two
disagree on ~2% of trades.

Configuration replicated from evaluation id 34 / id 28: symbols per
`data_snapshot`, `start = 2016-09-10`, `pre_sealed_end = 2025-09-07`,
`source = "massive"`, `proxy = SPY`, `CostModel()` defaults (0 commission, 3.0 bps
slippage, half-spread on → 11.0 bps round trip), `warmup = 30`, `min_bars = 60`,
per-symbol IS/OOS cut at 60% of that symbol's own bars.

**Reproduction is exact** — this is the validity check for everything below:

| | stored gate value | recomputed here |
|---|---|---|
| snap 3 pre-sealed trades (gate 7 set) | 984 | **984** |
| snap 3 OOS trades (gate 2) | 309 | **309** |
| snap 3 OOS expectancy (gate 3) | −0.0837R | **−0.0837R** |
| snap 3 folds (gate 1) | 257/+0.0175, 292/−0.1949, 181/+0.0436, 254/−0.0651 | **identical** |
| snap 2 OOS trades / expectancy | 320 / −0.0782R | **320 / −0.0782R** |
| snap 2 folds | 257, 292, 184, 266 | **identical** |

Per-trade sd measured directly: **0.8202** (snap 3 OOS). The map §0.3 recovered
0.807 by inverting the stored bootstrap half-width — agreement to 1.6%, which
validates that inversion for this strategy.

**IS/OOS geometry (matters for everything below).** The per-symbol 60% cut lands on
**2022-02-10** for 23 of 24 snapshot-3 symbols (XLC: 2022-10-12). So the OOS set is
a subset of folds **F3 and F4 only**; fold F2 (2018-12 → 2021-03) is entirely
in-sample.

---

## 2. Structural facts about v4's regime exposure

**FACT — v4 takes zero BEAR-labelled entries, by construction.** The entry requires
`ctx.regime.trend is not Trend.BEAR` (`mean_reversion.py:88`). Recomputed
distribution of the 984 snapshot-3 pre-sealed trades by signal-bar trend:

| trend at signal | trades | share |
|---|---|---|
| `bull` | 843 | 85.7% |
| `neutral` (= "range") | 141 | 14.3% |
| `bear` | **0** | 0.0% |
| no proxy bar | 0 | 0.0% |

**Two consequences the design phase must carry.**

1. **`risk_off` ≡ `vol is HIGH` for this strategy.** `RegimeState.risk_off` is
   `trend is BEAR or vol is HIGH` (`regime.py:41-42`). Since no BEAR entry can
   exist, the two formulations of §2.2 lever 1 — "skip when `vol is Vol.HIGH`" and
   "require `not risk_off`" — are **the same filter**, not two variants. Counting
   them as two under R5 would overstate the variant count; counting them as one is
   correct.
2. **Gate 6's "bear 46" is a different labeller.** Gate 6 buckets with
   `backtest/regime.py:label_regimes` (bull 618 / bear 46 / range 260 / 60
   unbucketed, §0.6). The strategy's own view (`research/regime.py`) is 843/0/141
   with **nothing unbucketed** — `regime_lookup` returns a state for every proxy
   session, including its own warmup, where the SMA-200 NaN falls through to
   `Trend.NEUTRAL`. Any design that reasons about "the strategy's bear exposure"
   from gate 6's numbers is reading the wrong labeller.

**FACT (labeller behaviour that limits how much "HIGH vol" means).**
`regime.py:78-84` sets `Vol.HIGH` when 20-day realised vol exceeds **1.15 × the
median** of a 5-session-strided trailing-252-day history of itself. It is a
*relative, self-rebasing* threshold: 36.7% of the 2,234 pre-sealed proxy sessions
are HIGH, and that share is roughly constant era to era (fold shares 0.343 / 0.409 /
0.407 / 0.306). March 2020 and a choppy week in 2017 receive the same label. This is
the mechanical reason the split in §3 is unstable.

---

## 3. H6 — expectancy split by `RegimeState.vol` at entry

### 3.1 Headline split (snapshot 3, pre-sealed)

`se_iid` is the ordinary per-trade standard error; `se_cl` clusters by calendar
signal date (see §4 for why). CI is the pipeline's own `bootstrap_ci` (2,000 iid
resamples, seed 20240101) for comparability with gate 4.

| vol at signal | n | expectancy | sd | se_iid | se_cl | bootstrap CI | win rate |
|---|---|---|---|---|---|---|---|
| **HIGH** | 413 | **−0.1486R** | 1.0157 | 0.0500 | 0.1203 | [−0.2533, −0.0509] | 0.477 |
| **LOW** | 571 | **+0.0005R** | 0.7468 | 0.0313 | 0.0511 | [−0.0602, +0.0590] | 0.567 |
| difference | | **−0.1491R** | | se 0.0590 → **2.53 SE** | se 0.1305 → **1.14 SE** | | |

Snapshot 2 reproduces this to three decimals: HIGH n=419 −0.1479R, LOW n=580
−0.0003R, difference −0.1476R (2.54 SE iid, 1.14 SE clustered). META changes nothing.

On the iid measure the gap clears 2 SE. On the honest clustered measure it does not.

### 3.2 The gap is one fold

| fold | span | HIGH n / exp | LOW n / exp | difference | t_iid | t_clustered |
|---|---|---|---|---|---|---|
| F1 | 2016-09 → 2018-12 | 155 / **+0.0582** | 102 / −0.0444 | **+0.1027** | +0.99 | +0.53 |
| F2 | 2018-12 → 2021-03 | 126 / **−0.4875** | 166 / **+0.0272** | **−0.5147** | **−4.64** | −1.99 |
| F3 | 2021-03 → 2023-06 | 44 / −0.0810 | 137 / +0.0836 | −0.1646 | −1.11 | −0.68 |
| F4 | 2023-06 → 2025-09 | 88 / −0.0614 | 166 / −0.0672 | +0.0058 | +0.05 | +0.02 |

Drop F2 and the effect **vanishes and changes sign**:

| set | HIGH n / exp | LOW n / exp | difference | t_iid |
|---|---|---|---|---|
| all pre-sealed **ex-F2** | 287 / **+0.0002R** | 405 / −0.0104R | **+0.0106R** | **+0.16** |
| **OOS only** (⊂ F3+F4) | 110 / −0.0989R | 199 / −0.0754R | −0.0236R | −0.23 |
| IS only (⊃ F2) | 303 / −0.1666R | 372 / +0.0411R | −0.2077R | −2.92 |

Snapshot 2: ex-F2 difference +0.0094R (t_iid +0.14); OOS difference −0.0324R
(t_iid −0.32). Same picture.

Whatever the vol filter buys, it is bought **entirely in F2 and entirely
in-sample**. Out of sample — the trade set gates 2/3/4 actually read — the two vol
buckets are 0.23 SE apart, i.e. indistinguishable.

### 3.3 Against the map's stated falsifier

The map's H6 falsifier (§2.2) is: *"falsified if pre-sealed expectancy split by
`RegimeState.vol` is statistically indistinguishable in SE units at the fold trade
counts (…detectable difference ~0.10R at 2 SE), **or** if excluding HIGH-vol entries
leaves F2 still deeply negative."*

- **Clause 1 — met in 3 of 4 folds.** F1 (+0.99 SE), F3 (−1.11 SE) and F4 (+0.05 SE)
  are all indistinguishable at the fold trade counts. Only F2 exceeds 2 SE.
- **Clause 2 — not met.** Excluding HIGH-vol entries leaves F2 at **+0.0272R on 166
  trades** (se_iid 0.0630) — not "still deeply negative". The F2 disaster is
  genuinely a high-vol phenomenon.

**Verdict — H6 is a fold-specific fact, not a strategy property (HYPOTHESIS H6:
refuted as a general mechanism, supported only inside F2).** The mechanism it names
is real for the Dec-2018 / COVID window and absent in the other 6½ years. Under R10
as amended ("a falsification condition must be stated to survive all four
snapshots" — and, by the same logic, not to rest on one fold), a lever justified by
this evidence is justified by a single 27-month episode.

### 3.4 The number that decides lever 1

The design question is not "is HIGH vol worse than LOW vol" but **"what does the
filtered strategy earn"**. Snapshot 3, LOW-vol entries only:

| set | n | expectancy | se_iid | se_cl | bootstrap CI | gate verdict |
|---|---|---|---|---|---|---|
| all pre-sealed | 571 | **+0.0005R** | 0.0313 | 0.0511 | [−0.0602, +0.0590] | — |
| all pre-sealed ex-F2 | 405 | −0.0104R | 0.0357 | 0.0518 | — | — |
| **OOS (gates 2/3/4)** | **199** | **−0.0754R** | 0.0529 | 0.0698 | **[−0.1773, +0.0250]** | g2 **pass**, g3 **FAIL**, g4 **FAIL** |

Walk-forward folds under the filter (gate 1 needs 2 of 4 with n ≥ 15 and exp > 0):
F1 −0.0444 (n=102), F2 **+0.0272** (n=166), F3 **+0.0836** (n=137), F4 −0.0672
(n=166) → **2 of 4 → gate 1 still a bare pass**, unchanged.

**FACT: lever 1 alone does not fix anything that is broken.** It discards 110 of 309
OOS trades (36%) and moves OOS expectancy from **−0.0837R to −0.0754R** — an
improvement of **+0.0083R, which is 0.16 SE (iid) / 0.10 SE (clustered)**. Gate 3
still fails (needs > 0). Gate 4 still fails (CI low −0.1773 vs the +0.02 bar) and,
per §0.3's arithmetic, *no* n fixes a negative point estimate. Over the whole
pre-sealed span the filtered strategy earns **+0.0005R ± 0.0511** — a strategy with
exactly zero edge, which after the modelled 0.028R/trade cost (§0.4) is a
gross edge of ~+0.029R being entirely consumed by frictions.

Snapshot 2 is identical in kind: LOW-vol OOS −0.0667R, CI [−0.1722, +0.0322].

### 3.5 Full trend × vol cross-tabulation, and the "is there a good slice?" question

Snapshot 3, pre-sealed, signal-bar labels:

| trend / vol | n (all) | exp (all) | se_iid | t | n (OOS) | exp (OOS) | se_iid |
|---|---|---|---|---|---|---|---|
| bull / HIGH | 339 | −0.1987R | 0.0571 | −3.48 | 95 | −0.0282R | 0.0991 |
| bull / LOW | 504 | −0.0145R | 0.0338 | −0.43 | 182 | −0.0889R | 0.0559 |
| neutral / HIGH | 74 | +0.0810R | 0.0926 | +0.87 | 15 | −0.5466R | 0.1633 |
| **neutral / LOW** | **67** | **+0.1137R** | 0.0792 | **+1.44** | **17** | +0.0700R | 0.1584 |
| bear / any | 0 | — | — | — | 0 | — | — |

Marginals: trend `neutral` overall +0.0965R (n=141, se 0.0613, t=+1.58, CI
[−0.0288, +0.2201]) but **OOS `neutral` is −0.2190R** (n=32, se 0.1248) — the sign
flips out of sample. Snapshot 2 is identical for every neutral cell (META
contributed no neutral-regime trades).

**Answer to the task's question: no regime slice qualifies.** The criterion was
≥ 2 SE positive expectancy **and** ≥ 30 OOS-equivalent trades.

| candidate slice | ≥ 2 SE positive? | ≥ 30 OOS trades? | verdict |
|---|---|---|---|
| vol = LOW | no (+0.01 SE) | yes (199) | **fail** |
| trend = neutral | no (+1.58 SE iid, +1.11 clustered) | no (32 OOS, but −0.2190R) | **fail** |
| neutral / LOW | no (+1.44 SE iid, +1.11 clustered) | **no (17)** | **fail** |
| neutral / HIGH | no (+0.87 SE) | no (15) | **fail** |
| bull / LOW | negative | yes (182) | **fail** |
| bull / HIGH | negative | yes (95) | **fail** |

The best candidate, `neutral/LOW`, is +1.44 SE on 67 pre-sealed trades. **DERIVED**,
using §0.3's restatement of gate 4 (`exp > 0.02 + 1.96·sd/√n`) at its measured
sd = 0.6482 and holding its point estimate fixed: it needs **n ≈ 184 OOS trades** to
clear gate 4, i.e. roughly **460 pre-sealed trades** in that cell against the 67 it
has — about **7× the current universe breadth**, and only if the point estimate
survives. That is a W1/universe-expansion question, not a v0.2.0 filter question.

---

## 4. Why the clustered standard error is reported

**FACT.** The 984 snapshot-3 pre-sealed trades occur on only **352 distinct signal
dates**, with up to **19 trades sharing one date**. A −2σ day is a market-wide
event: 15 of the 24 snapshot-3 symbols are ETFs, several of which hold the other 9,
so same-day trades are close to the same bet placed repeatedly.

Design effect (clustered SE ÷ iid SE), clustering on calendar signal date:

| trade set | n | clusters | expectancy | se_iid | se_cl | **deff** | t_clustered |
|---|---|---|---|---|---|---|---|
| all pre-sealed | 984 | 352 | −0.0621R | 0.0278 | 0.0601 | **2.16×** | −1.03 |
| **OOS (gate 4's input)** | 309 | 152 | −0.0837R | 0.0467 | 0.0871 | **1.87×** | −0.96 |
| IS | 675 | 200 | −0.0521R | 0.0345 | 0.0781 | 2.26× | −0.67 |

**HYPOTHESIS (diagnostic, not a gate change).** Gate 4's bootstrap resamples trades
**iid** (`montecarlo.py:18-20, 30-33`). For v4 that understates the OOS CI
half-width by roughly **1.9×**. Applied symmetrically this cuts both ways and the
second direction is the one the design phase should hear: v4's OOS expectancy of
−0.0837R is only **−0.96 SE** from zero once clustering is respected. The honest
statement is *"v4's OOS edge is indistinguishable from zero in either direction"*,
not *"v4 loses money out of sample"*. This does not rescue the strategy — gate 3
needs a positive point estimate and gate 4 needs a CI low above +0.02R, and
widening the CI makes gate 4 strictly harder — but it does mean the −0.0837R is not
the solid negative it reads as, and any v0.2.0 claiming to have "fixed" a 0.08R
deficit is claiming to have fixed noise.

---

## 5. H9 — entry-rate stationarity across the four walk-forward folds

Denominator: every bar on which the signal function was actually invoked
(`t` from `warmup=30` to `n−2`, skipping bars inside an open position — the engine
sets `t = exit_idx + 1`). This is the correct "opportunity" count, not the raw bar
count. Fold boundaries are `promotion.py:606-612`'s exactly.

### 5.1 Entry rate per eligible symbol-session (snapshot 3)

| fold | span | eligible bars | entries | **rate /1000** | se_iid | **se_clustered** | HIGH-vol session share |
|---|---|---|---|---|---|---|---|
| F1 | 2016-09-10 → 2018-12-10 | 10,796 | 257 | **23.81** | 1.47 | 3.88 | 0.343 |
| F2 | 2018-12-10 → 2021-03-10 | 12,539 | 292 | **23.29** | 1.35 | 3.85 | 0.409 |
| F3 | 2021-03-10 → 2023-06-09 | 12,899 | 181 | **14.03** | 1.04 | 2.32 | 0.407 |
| F4 | 2023-06-09 → 2025-09-07 | 12,439 | 254 | **20.42** | 1.27 | 2.60 | 0.306 |

Pairwise differences (clustered on calendar date; the iid figure is shown to make
the clustering correction visible, and is **not** the one to act on):

| pair | Δ rate/1000 | t_iid | **t_clustered** |
|---|---|---|---|
| F1 − F2 | +0.52 | +0.26 | **+0.09** |
| F1 − F3 | +9.77 | +5.44 | **+2.16** |
| F1 − F4 | +3.39 | +1.75 | **+0.72** |
| F2 − F3 | +9.26 | +5.45 | **+2.06** |
| F2 − F4 | +2.87 | +1.55 | **+0.62** |
| F3 − F4 | −6.39 | −3.90 | **−1.83** |

Snapshot 2 reproduces: 23.81 / 23.29 / 13.89 / 20.54, F1−F3 t_clustered +2.20.

**Reading.** Five of six pairs are within 2 SE; F1 and F2 are 0.09 SE apart. The
only real deviation is **F3, which sits ~2.1 SE *below* F1 and F2**. The
peak-to-trough ratio is 1.70×. So the entry rate is *not* strictly stationary —
but the departure is marginal, one-fold, and it is in the **wrong direction for H9**.

### 5.2 H9's actual mechanism, tested directly

H9 claims the fixed z-threshold *"fires far more often in high-vol periods,
precisely when mean reversion is least reliable — the trigger is pro-cyclical with
the wrong cycle."* Two independent tests:

**(a) Fold level — no relationship, and the sign is backwards.** F1 has the
**lowest** HIGH-vol session share (0.343) and the **highest** entry rate (23.81).
F3 has essentially the **highest** HIGH-vol share (0.407) and the **lowest** entry
rate (14.03). Across the four folds the rank correlation between HIGH-vol share and
entry rate is negative.

**(b) Day level — a weak effect that is itself non-stationary and inverts.**

| fold | rate on HIGH-vol days /1000 | rate on LOW-vol days /1000 | ratio |
|---|---|---|---|
| F1 | 42.02 (155 / 3,689) | 14.35 (102 / 7,107) | **2.93×** |
| F2 | 25.49 (126 / 4,944) | 21.86 (166 / 7,595) | 1.17× |
| F3 | **8.34** (44 / 5,273) | **17.96** (137 / 7,626) | **0.46× — reversed** |
| F4 | 23.67 (88 / 3,718) | 19.03 (166 / 8,721) | 1.24× |
| **pooled** | **23.43** (413 / 17,624) | **18.39** (571 / 31,049) | **1.27×** |

The pooled 1.27× pro-cyclicality is driven almost entirely by F1's 2.93×, and F3
runs the other way at 0.46×.

**FACT — the mechanism H9 posits is not in the code.**
`zscore_last_return` (`features/daily.py:66-73`) divides the last return by the
**standard deviation of that same symbol's own trailing 20 returns**. The trigger is
self-normalising: raising the level of volatility raises numerator and denominator
together, so a fixed `z ≤ −2.0` is *not* mechanically pro-cyclical with the level of
vol. Whatever residual 1.27× exists comes from second-order effects — vol
*accelerating* inside the 20-day window (today's move measured against a still-low
trailing sd), return kurtosis, and the `close < SMA(20)` conjunct being easier to
satisfy in drawdowns — not from the level of vol. That is consistent with an effect
that is small, unstable, and sign-reversing.

**(c) Does the entry-rate variation cost anything?** Cross-tabulating fold × vol
expectancy (§3.2) answers this: outside F2 the HIGH-vol entries earn **+0.0002R**
against LOW-vol's −0.0104R. The extra HIGH-vol entries are not the losing ones,
except in F2.

### 5.3 Per-symbol × per-fold entry counts (snapshot 3)

Cells are `entries / eligible bars = rate per 1,000`.

| symbol | F1 | F2 | F3 | F4 | max/min |
|---|---|---|---|---|---|
| AAPL | 7/478 = 14.6 | 9/536 = 16.8 | 4/558 = 7.2 | 12/504 = 23.8 | 3.32 |
| AMZN | 14/473 = 29.6 | 10/523 = 19.1 | 6/538 = 11.2 | 11/531 = 20.7 | 2.65 |
| DIA | 10/480 = 20.8 | 17/522 = 32.6 | 10/534 = 18.7 | 6/537 = 11.2 | 2.91 |
| GOOGL | 11/480 = 22.9 | 9/528 = 17.0 | 5/543 = 9.2 | 12/503 = 23.9 | 2.59 |
| HD | 9/468 = 19.2 | 14/516 = 27.1 | 8/532 = 15.0 | 13/508 = 25.6 | 1.80 |
| IWM | 16/443 = 36.1 | 14/497 = 28.2 | 10/536 = 18.7 | 6/541 = 11.1 | 3.26 |
| JPM | 11/453 = 24.3 | 10/528 = 18.9 | 10/524 = 19.1 | 12/509 = 23.6 | 1.28 |
| MSFT | 13/467 = 27.8 | 9/529 = 17.0 | 8/536 = 14.9 | 11/503 = 21.9 | 1.87 |
| NVDA | 14/449 = 31.2 | 10/520 = 19.2 | **2/558 = 3.6** | 11/518 = 21.2 | **8.70** |
| QQQ | 14/462 = 30.3 | 12/518 = 23.2 | 6/546 = 11.0 | 11/522 = 21.1 | 2.76 |
| SPY | 13/450 = 28.9 | 17/524 = 32.4 | 10/539 = 18.6 | 10/525 = 19.0 | 1.75 |
| UNH | 9/479 = 18.8 | 9/534 = 16.9 | 8/529 = 15.1 | 17/485 = 35.1 | 2.32 |
| XLB | 8/478 = 16.7 | 13/517 = 25.1 | 9/525 = 17.1 | 11/516 = 21.3 | 1.50 |
| XLC | 3/75 = 40.0 † | 12/518 = 23.2 | 7/539 = 13.0 | 12/508 = 23.6 | 3.08 |
| XLE | 10/463 = 21.6 | 12/521 = 23.0 | 8/530 = 15.1 | 12/506 = 23.7 | 1.57 |
| XLF | 13/447 = 29.1 | 14/521 = 26.9 | 11/521 = 21.1 | 12/519 = 23.1 | 1.38 |
| XLI | 14/442 = 31.7 | 16/522 = 30.7 | 8/534 = 15.0 | 7/526 = 13.3 | 2.38 |
| XLK | 15/463 = 32.4 | 10/529 = 18.9 | 7/547 = 12.8 | 11/515 = 21.4 | 2.53 |
| XLP | 9/477 = 18.9 | 16/514 = 31.1 | 10/530 = 18.9 | 10/534 = 18.7 | 1.66 |
| XLRE | 11/454 = 24.2 | 12/518 = 23.2 | 6/548 = 10.9 | 12/532 = 22.6 | 2.21 |
| XLU | 7/482 = 14.5 | 11/541 = 20.3 | 10/532 = 18.8 | 8/528 = 15.2 | 1.40 |
| XLV | 8/479 = 16.7 | 14/511 = 27.4 | 5/543 = 9.2 | 9/521 = 17.3 | 2.98 |
| XLY | 12/466 = 25.8 | 14/521 = 26.9 | 9/535 = 16.8 | 7/530 = 13.2 | 2.03 |
| XOM | 6/488 = 12.3 | 8/531 = 15.1 | 4/542 = 7.4 | 11/518 = 21.2 | 2.88 |

† XLC has only 75 eligible bars in F1 (its history starts mid-2018); its 40.0 is
3 entries and is not meaningful.

Median per-symbol max/min fold-rate ratio: **2.35**. But almost all of that is the
common F3 trough, not symbol-specific behaviour: a Pearson χ² of the 24 × 4 entry
counts against the pooled fold rates gives **χ² = 69.07 over 95 cells** (≈ 91 df
after fitting the four fold rates) — **no evidence** of symbol-specific entry-rate
heterogeneity beyond the shared fold pattern. Caveat: that χ² assumes within-cell
independence, which same-day cross-symbol clustering violates in the
*anti*-conservative direction; it would over-reject, and it still does not reject.

### 5.4 H9 verdict

The map's falsifier for H9 is: *"falsified if entry rate per symbol-day is roughly
stationary across the four folds."*

- Strictly, it is **not** stationary: F3 sits ~2.1 SE (clustered) below F1 and F2,
  a 1.70× peak-to-trough range. The falsifier as literally worded does not fire.
- But H9's **substantive claim is refuted**: the departure is in the opposite
  direction (the *lower*-entry-rate fold is one of the *higher*-vol folds), the
  day-level pro-cyclicality is a weak 1.27× that inverts to 0.46× in F3, the trigger
  is self-normalising by construction (`features/daily.py:66-73`), and the extra
  HIGH-vol entries carry no expectancy penalty outside F2 (+0.0002R ex-F2).

**HYPOTHESIS H9: refuted.** The instability in v4's entry rate is real but small,
is not vol-driven, and costs nothing. A "vol-normalised entry threshold" (§2.2
lever 2) is a fix for a defect this diagnostic could not find. It should be
**demoted or dropped** rather than counted as one of the two or three variants R5
budgets for this strategy.

---

## 6. Consolidated findings

1. **FACT.** Reproduction of evals 34 (snap 3) and 28 (snap 2) is exact; every
   number below is computed on the pre-sealed span only.
2. **FACT.** v4 takes **zero** BEAR-regime entries by construction, so
   `not risk_off` and `vol is LOW` are the *same* filter. Gate 6's bear/range counts
   come from a different labeller (`backtest/regime.py`) than the one the strategy
   reads (`research/regime.py`).
3. **HYPOTHESIS H6 — refuted as a general mechanism, supported only inside F2.**
   HIGH-vol −0.1486R vs LOW-vol +0.0005R pooled (2.53 SE iid, **1.14 SE clustered**),
   but +0.1027R the *other* way in F1, +0.0058R in F4, and **+0.0106R (0.16 SE) with
   F2 removed**. Out of sample the two buckets are 0.23 SE apart.
4. **FACT — the decisive number for lever 1.** Filtering to LOW-vol entries leaves
   OOS expectancy at **−0.0754R** (n=199, CI [−0.1773, +0.0250]) versus −0.0837R
   unfiltered: a **+0.0083R / 0.16 SE** change bought with a 36% cut in trade count.
   Gates 3 and 4 still fail; gate 1 still bare-passes on 2 of 4 folds. Over the whole
   pre-sealed span the filtered strategy earns **+0.0005R ± 0.0511**. Lever 1 does
   not produce a positive-expectancy strategy — it produces a zero-expectancy one.
5. **FACT — no regime slice qualifies.** Of the six non-empty trend × vol slices,
   none has ≥ 2 SE positive expectancy with ≥ 30 OOS trades. The best,
   `neutral/LOW` (+0.1137R, n=67, +1.44 SE iid / +1.11 SE clustered, 17 OOS trades),
   would need **~184 OOS trades ≈ 7× the current breadth** to clear gate 4 at its own
   point estimate.
6. **HYPOTHESIS H9 — refuted.** Entry rate 23.81 / 23.29 / 14.03 / 20.42 per 1,000
   eligible symbol-sessions; only F3 deviates (~2.1 SE clustered), in the direction
   opposite to H9, and the z-trigger is self-normalising by construction.
7. **HYPOTHESIS (diagnostic addition, permitted under R4).** Trades cluster on 352
   distinct dates; the date-clustered design effect on gate 4's own OOS trade set is
   **1.87×**. Gate 4's iid bootstrap CI is roughly half as wide as it should be, and
   symmetrically, v4's OOS −0.0837R is only −0.96 SE from zero. v4's out-of-sample
   result is best described as *no measurable edge*, not *a measured loss*.
8. **Implication for the design phase.** Both mechanisms §2.2 nominated as
   volatility-related (levers 1 and 2, hypotheses H6 and H9) are now measured and
   neither carries the effect the map hypothesised. Under R5 the remaining
   mechanism-motivated candidates for v4 are **lever 3 (exit geometry / H8 — the
   untested 4 of 6 parameters, §0.5)** and **lever 4 (cross-sectional breadth / H7 —
   which requires universe expansion)**. Lever 5 (documented honest fail) gains
   weight: two of four hypotheses are now falsified on pre-sealed evidence, and
   §2.2's own warning applies — v4's gate 9 already passes on all four snapshots, so
   a v0.2.0 that fixed gates 3/4/5/7 would inherit a friendly sealed test that
   provides **no independent check**.

---

## 7. Caveats and limits

- **Clustering choice.** Clusters are calendar signal dates (352 of them on
  snapshot 3, small-G corrected). Clustering by symbol instead would give a
  different, smaller inflation; clustering by both would give a larger one. The
  reported design effect is a lower bound on the correction needed, not a precise
  one.
- **The proxy is inside the universe.** SPY supplies the regime label *and* trades:
  **50 of the 984 snapshot-3 pre-sealed trades are SPY trades gated by SPY's own
  regime** (13/17/10/10 across F1–F4), and QQQ, DIA and IWM are near-duplicates of
  it. This is a property of the existing pipeline, not of this diagnostic, but it
  is another reason the same-day cluster is the right unit of evidence.
- **`Vol.HIGH` is relative, not absolute** (§2). ~37% of sessions are HIGH in every
  era by construction, so the label conflates March 2020 with ordinary chop. A
  design that wants "crisis" rather than "above-median chop" needs a different
  statistic, and that would be a new labeller — a shared-surface change requiring its
  own leakage audit.
- **Multiple testing (R5).** Slices reported here were fixed by the task before any
  result was seen: `vol` (2), `trend` (3), their cross (6), and the four folds. No
  slice was chosen after inspecting outcomes, and none is proposed as a shipping
  filter. This diagnostic proposes **zero** strategy variants and consumes **zero**
  sealed looks; the count remains **k = 5**.
- **IS/OOS and folds are not independent partitions.** The per-symbol 60% cut lands
  at 2022-02-10, so OOS ⊂ F3 ∪ F4 and F2 is wholly in-sample. "OOS" and "ex-F2"
  therefore overlap heavily and are not two independent confirmations of §3.2 —
  they are two views of the same fact.
- **Snapshot coverage.** Snapshots 2 and 3 were run, as tasked; both agree closely
  (META adds 15 trades and moves no conclusion). Snapshot 1 has a different sealed
  boundary and snapshot 4's `META_CONT` carries a non-`massive` source (§0.1); neither
  was run. Under R10 as amended, the conclusions here are verified on 2 of 4
  snapshots and should be treated as provisional on the other two — though snapshots
  1, 2 and 4 differ only by META's treatment, which §3.5 shows contributes nothing
  to any regime cell that matters.
- **`bootstrap_ci` is the pipeline's own iid implementation**, used here for
  comparability with gate 4. Where a CI and a clustered SE disagree, §4 says which
  to believe.
