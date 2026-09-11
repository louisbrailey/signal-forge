# W2 diagnostic — `trend_continuation.medium_swing` (version 3): does the entry ATR go stale?

**Question asked (`STRATEGY_COMPLETION_MAP.md` §2.1, hypothesis H3 — "stale volatility
scale").** ATR(14) at entry sets the risk unit (`stop = close − 1.5 × ATR(14)`,
`trend_continuation.py:105`). H3 says that scale may be a poor description of
volatility 40 bars later, so the stop distance chosen at entry becomes stale over a
MEDIUM_SWING hold. The map's own falsification criterion: *"Falsified if
ATR(14)@exit / ATR(14)@entry is tightly clustered near 1 across pre-sealed
medium_swing trades."*

**Answer, stated up front. H3 is NOT SUPPORTED as a mechanism that could motivate a
v0.2.0, and its stated falsification criterion is met.** On snapshot 3 the pre-sealed
distribution of ATR@exit / ATR@entry for v3 has median **1.0565 ± 0.0047**, IQR
**[0.963, 1.137]**, and **83.9%** of trades inside ±25% — and the v2 SHORT_SWING
control, which has a 10-bar leash rather than 40, is **statistically
indistinguishable** from it (median difference **+0.0012 ± 0.0062**, z = +0.19). The
40-bar leash does not measurably change the realised staleness of the risk unit,
because the leash almost never binds: **0.75%** of v3's pre-sealed trades exit on the
time stop and the median hold is **5 bars**.

Expectancy *does* differ sharply across ratio terciles (T3−T1 = **−0.4381R ± 0.1217**,
z = −3.60, snapshot 3, all pre-sealed) and that gradient is **snapshot-stable** to
three decimal places. But it is **entirely exit-composition**, not staleness: within
`stop` exits the gradient is **+0.0059R ± 0.0371** (z = +0.16) and within `target`
exits **−0.1515R ± 0.1196** (z = −1.27) — both under 2 SE. The at-exit ATR ratio is a
*consequence* of how the trade ended, not a property that precedes it, so under R1/R5
it cannot motivate a parameter, filter or exit change.

Two things *are* measurable at ≥ 2 SE and are reported honestly in §5, but neither
rescues H3: (i) v3's typical multiplicative mis-scaling at exit is marginally larger
than v2's (mean |log ratio| **0.1290 ± 0.0034** vs **0.1162 ± 0.0028**; difference
**+0.0128 ± 0.0044**, z ≈ +2.9) — an economically trivial ~1.3 percentage points; and
(ii) among the 9.5% of v3 trades held ≥ 21 bars, exit ATR sits **11.3% ± 2.1%** below
entry ATR (z = −5.4 against 1.0) — which is a *survivorship* consequence of the stop
rule, and is the mechanism by which those trades are v3's best (+0.79R ± 0.15).

---

## 0. Method, provenance and safety

**FACT — no write touched the live database, and no sealed look was consumed.**
Every number here comes from `run_backtest`
(`/Users/louisbrailey/signal-forge/src/signalforge/backtest/engine.py:82-142`) driven
through the same adapter the research path uses
(`research/strategies/base.py:29-45`), executed against a point-in-time
`sqlite3 -readonly ... .backup` copy of the live database at
`$TMPDIR/scratch-v3_atr_at_exit.sqlite`. `data/signalforge.sqlite` was opened only
read-only. No file under `src/` or `tests/` was modified; no provider API was called;
no `evaluate_promotion` was run, so **no `strategy_sealed_test` row was created and
the sealed-look count remains k = 5** (map §0.1, R2).

**FACT — the sealed window was never loaded.** Each run covers only
`[start, pre_sealed_end]` with `pre_sealed_end = sealed_start − 1 day`, exactly as
`research/promotion.py:557-563` computes it. Sealed windows are taken from
`strategy_sealed_test.window_start/window_end` (ids 2, 7, 12, 17 for version 3;
1, 6, 11, 16 for version 2), snapshot symbol sets from `data_snapshot.symbols_json`.

| Snapshot | key | symbols | source filter | pre-sealed run span | sealed window (untouched) |
|---|---|---|---|---|---|
| 1 | `universe_25_baseline_legacy` | 25 (incl. `META`) | `massive` | 2016-09-10 → **2025-09-06** | 2025-09-07 → 2026-09-07 |
| 2 | `universe_25_baseline` | 25 (incl. `META`) | `massive` | 2016-09-10 → **2025-09-07** | 2025-09-08 → 2026-09-08 |
| 3 | `universe_24_ex_meta` | 24 (**no** META) | `massive` | 2016-09-10 → **2025-09-07** | 2025-09-08 → 2026-09-08 |
| 4 | `universe_25_meta_continuity_corrected` | 25 (`META_CONT`) | `["massive", "continuity_bridge:1"]` | 2016-09-10 → **2025-09-07** | 2025-09-08 → 2026-09-08 |

Snapshot 4's two-element source filter follows
`research/fb_meta_universe_comparison.py:49-64`. All other arguments match
`promotion.py:585-594`: `proxy_symbol="SPY"`, default `CostModel()` (0 commission /
3.0 bps slippage / half-spread on → 11.0 bps round trip, `engine.py:94,143`),
`min_bars=60` with `warmup=min_bars // 2`, and **`allow_short` left at its default
`False`**.

**FACT — snapshots 1 and 2 are the same run.** Their pre-sealed ends (2025-09-06 and
2025-09-07) are a Saturday and a Sunday; the last trading bar in both is 2025-09-05.
Every figure below is identical for snapshots 1 and 2, as it is in the stored
evaluations (evals 9 and 15 both record 54,157 bars, coverage `2016-10-17..2025-09-05`).

**FACT — the reproduction is exact.** Re-running v2 and v3 over each pre-sealed span
reproduces the recorded gate evidence to the digit (gate 2/3 numbers from
`gates_json` on evals 32–36 and 39; gate 6/7 trade counts from map §0.6):

| | snap 1 | snap 2 | snap 3 | snap 4 |
|---|---|---|---|---|
| v3 pre-sealed trades | 1,091 | 1,091 | **1,071** ✓ | 1,112 |
| v3 OOS n / expectancy | 326 / +0.2936R | 326 / +0.2936R | **319 / +0.3064R** ✓ | **336 / +0.3169R** ✓ |
| v2 pre-sealed trades | 1,190 | 1,190 | **1,169** ✓ | 1,216 |
| v2 OOS n / expectancy | 348 / +0.2609R | 348 / +0.2609R | **341 / +0.2648R** ✓ | 359 / +0.2724R |

(✓ = matches the stored value in the map / `gates_json`.)

**FACT — the empirical per-trade sd corroborates map §0.3.** §0.3 recovered the
per-trade sd by inverting the bootstrap half-width under a normal approximation.
Measured directly from the trades: v3 OOS sd = **1.726** (§0.3 implied 1.741, −0.9%),
v2 OOS sd = **1.467** (§0.3 implied 1.420, +3.3%). Every SE in this document is the
**empirical** `sd/√n` on the stated subset, not §0.3's implied figure; differences
between two subsets use `√(SE₁² + SE₂²)`.

### 0.1 Exactly what was measured

| Symbol | Definition | Where it comes from |
|---|---|---|
| `atr_entry` | ATR(14) at the **signal bar** `t` | this is the ATR the strategy actually used: `a = atr(series, t, 14)` then `stop_price = close − 1.5·a` (`trend_continuation.py:89,105`). The entry fills at bar `t+1`'s open (`engine.py:99-101`), so `t = index(entry_date) − 1`. |
| `atr_exit` | ATR(14) at the **exit bar** index | `atr(series, exit_idx, 14)`, same arithmetic as `research/features/daily.py:46-50` (verified: a vectorised prefix-sum reimplementation, identical window `[t−13, t]`). |
| **`ratio`** | `atr_exit / atr_entry` | the quantity H3 is about. |
| `fwdH` | `ATR(14)@(t+H) / ATR(14)@t` | drift of the ATR process over H sessions **regardless of whether the trade was still open** — the exit-free control. |
| `survivor@H` | `fwdH` restricted to `bars_held ≥ H` | drift as *actually experienced* by trades still holding at bar H. |
| `contraction` | `ATR(14)/ATR(50)` at the signal bar | an **exogenous, known-at-entry** conditioner (§6). |

`ratio`, `fwdH` and `survivor@H` all use ATR values computed on bars at or after the
exit — that is legitimate for a *diagnostic* (no strategy rule consumes them) but it
is precisely why the tercile conditioning in §3 is not causal; see §4.

---

## 1. The distribution of ATR@exit / ATR@entry — H3's falsification criterion

**FACT.** Pre-sealed, all trades, by snapshot:

**v3 `medium_swing` (40-bar leash)**

| Snap | n | p05 | p25 | **median ± SE** | p75 | p95 | inside ±25% | mean \|log ratio\| ± SE |
|---|---|---|---|---|---|---|---|---|
| 1 | 1,091 | 0.754 | 0.963 | **1.0568 ± 0.0044** | 1.140 | 1.306 | 84.0% | 0.1294 ± 0.0034 |
| 2 | 1,091 | 0.754 | 0.963 | **1.0568 ± 0.0045** | 1.140 | 1.306 | 84.0% | 0.1294 ± 0.0035 |
| **3** | **1,071** | **0.753** | **0.963** | **1.0565 ± 0.0047** | **1.137** | **1.306** | **83.9%** | **0.1290 ± 0.0034** |
| 4 | 1,112 | 0.752 | 0.962 | **1.0560 ± 0.0045** | 1.137 | 1.307 | 83.7% | 0.1297 ± 0.0035 |

**v2 `short_swing` (10-bar leash) — control**

| Snap | n | p05 | p25 | **median ± SE** | p75 | p95 | inside ±25% | mean \|log ratio\| ± SE |
|---|---|---|---|---|---|---|---|---|
| 1 | 1,190 | 0.804 | 0.967 | **1.0562 ± 0.0040** | 1.133 | 1.295 | 87.2% | 0.1168 ± 0.0028 |
| 2 | 1,190 | 0.804 | 0.967 | **1.0562 ± 0.0040** | 1.133 | 1.295 | 87.2% | 0.1168 ± 0.0029 |
| **3** | **1,169** | **0.803** | **0.966** | **1.0553 ± 0.0042** | **1.131** | **1.295** | **87.3%** | **0.1162 ± 0.0028** |
| 4 | 1,216 | 0.803 | 0.966 | **1.0559 ± 0.0040** | 1.133 | 1.296 | 87.0% | 0.1174 ± 0.0028 |

(SEs are 2,000-draw non-parametric bootstraps, seed 20240101.)

**FACT — the criterion in §2.1 is met.** The ratio *is* tightly clustered near 1:
median 1.0565, interquartile range 0.963–1.137 (i.e. the middle half of trades exit
with an ATR within −3.7%/+13.7% of the one that sized their stop), and 84% within
±25%. The typical multiplicative error, `exp(mean |log ratio|) = e^0.129`, is
**13.8%**.

**FACT — the medium leash adds essentially nothing.** Snapshot 3, v3 minus v2:

| Statistic | v3 | v2 | difference ± SE | z |
|---|---|---|---|---|
| median ratio | 1.0565 | 1.0553 | **+0.0012 ± 0.0062** | **+0.19** |
| mean \|log ratio\| | 0.1290 | 0.1162 | **+0.0128 ± 0.0044** | **+2.89** |
| share outside ±25% | 16.06% | 12.75% | +3.31 pp ± 1.52 pp | +2.18 |

Snapshots 1/2 give +0.0126 ± 0.0044 (z = +2.85) and snapshot 4 +0.0122 ± 0.0044
(z = +2.79) for mean |log ratio| — perfectly stable. So there is **no systematic bias
difference at all** (medians identical), and a **small but ≥ 2 SE dispersion
difference**: v3's typical mis-scaling is 13.8% against v2's 12.3%, a gap of ~1.5
percentage points of ATR.

**CAVEAT (important, and it cuts against reading z = +2.9 too strongly).** v2 and v3
share the identical entry rule and differ only in `time_stop_bars`
(`trend_continuation.py:37-39`), so the two trade sets overlap heavily and are
positively correlated. The independent-sample SE above is therefore **not** the right
SE for the difference; the true SE is smaller (making z larger) but the *point
estimate* — 1.3 pp — is unaffected, and it is the point estimate that decides whether
this is worth acting on.

---

## 2. Why the leash barely matters: it almost never binds

**FACT (snapshot 3; snapshots 1/2/4 agree to ±0.5 pp on every figure).**

| | v3 `medium_swing` | v2 `short_swing` |
|---|---|---|
| `time_stop_bars` | 40 | 10 |
| mean bars held | **8.24** | 5.60 |
| median bars held | **5** | 5 |
| p90 / p99 / max bars held | 20 / 39 / **40** | 10 / 10 / 10 |
| share held ≥ 21 bars | **9.5%** (102) | 0% |
| share held ≥ 31 bars | **2.9%** (31) | 0% |
| exits on `stop` | 57.1% | 46.5% |
| exits on `target` | **41.5%** | 24.1% |
| exits on **`time_stop`** | **0.75%** (8 of 1,071) | 29.0% |
| exits on `eod` | 0.6% | 0.3% |

**DERIVED.** H3's premise — "ATR(14) at entry may be a poor risk scale *40 bars
later*" — describes a situation that arises for **8 of 1,071** pre-sealed v3 trades.
Half of v3's trades are closed within 5 sessions; at that horizon the ATR that set the
stop is still almost exactly right (§3, survivors@5 median 0.999). This is the single
biggest reason the realised distribution in §1 looks like v2's.

**Collateral FACT (confirms the sibling W2 diagnostic on H2).** The 3.0×ATR target is
reached by 41.5% of v3's trades and the time stop by 0.75%. H2 ("target unreachable
inside the leash, time stop becomes the modal exit") is falsified by the same run.

**Collateral FACT (H5).** All 1,071 v3 pre-sealed trades and all 1,169 v2 trades are
`LONG`. `allow_short` is `False` on the promotion path
(`promotion.py:585-594` never passes it; `backtest_runner.py:170` defaults it to
`False`), so the short branch at `trend_continuation.py:113-122` contributes **zero**
trades to any gate. H5's asymmetry is not merely negligible — it is structurally
absent from the evidence base.

---

## 3. How stale the ATR actually gets, with and without the exit rule

Three different questions hide behind "does ATR go stale", and they give three
different answers. **FACT**, snapshot 3 (other snapshots in the JSON sibling; all agree
within 1 SE):

| Horizon H | measure | n | median ± SE | IQR | outside ±25% ± SE | mean \|log\| ± SE |
|---|---|---|---|---|---|---|
| 5 | **all trades** (`fwd5`) | 1,067 | 1.0504 ± 0.0055 | [0.971, 1.151] | 13.7% ± 1.1% | 0.1164 ± 0.0032 |
| 10 | **all trades** | 1,065 | 1.0882 ± 0.0105 | [0.966, 1.266] | 31.6% ± 1.4% | 0.1848 ± 0.0049 |
| 20 | **all trades** | 1,058 | 1.0727 ± 0.0134 | [0.897, 1.313] | 41.3% ± 1.5% | 0.2570 ± 0.0073 |
| 40 | **all trades** | 1,041 | 1.1328 ± 0.0117 | [0.950, 1.467] | **49.4% ± 1.5%** | **0.3131 ± 0.0104** |
| 5 | **survivors** (`bars_held ≥ 5`) | 599 | 0.9989 ± 0.0053 | [0.933, 1.076] | 4.8% ± 0.9% | 0.0861 ± 0.0028 |
| 10 | **survivors** | 350 | 0.9713 ± 0.0087 | [0.867, 1.060] | 15.1% ± 1.9% | 0.1254 ± 0.0057 |
| 20 | **survivors** | 116 | **0.8413 ± 0.0140** | [0.740, 0.958] | 38.8% ± 4.4% | 0.2280 ± 0.0163 |
| 40 | **survivors** | 8 | — (n < 15, not reported) | — | — | — |

Three readings, each labelled:

1. **FACT — the ATR(14) *process* does go materially stale over 40 sessions.**
   Mean |log| rises monotonically 0.116 → 0.185 → 0.257 → 0.313 across H = 5, 10, 20,
   40. The 40-vs-10 difference is **+0.128 ± 0.011 (z ≈ 11.6)** and half of all
   40-session-ahead ATRs are off by more than 25%. This is a property of daily
   volatility, universally true, and **it is not by itself a finding about v3** —
   the same numbers hold for v2's trade set (0.3129 ± 0.0095 at H = 40), whose leash
   is 10 bars.

2. **FACT — conditioning on survival reverses the sign of the drift.** Among trades
   still open at bar 20, median ATR has *fallen* to 0.841, while in the population it
   has *risen* to 1.073. **DERIVED, and this is the whole explanation:** surviving 20
   sessions without touching a stop 1.5×ATR away or a target 3.0×ATR away is close to
   the definition of "realised volatility came in below the entry ATR". The
   contraction is manufactured by the exit rule, not by an independent drift in the
   volatility process.

3. **FACT — for the trades that genuinely hold long, the mis-scaling is large and
   one-directional.** Among v3's 102 trades held ≥ 21 bars, the at-exit ratio has
   median **0.8869 ± 0.0211**, i.e. **11.3% ± 2.1% below** entry ATR — **z = −5.36**
   against 1.0, comfortably ≥ 2 SE, and stable across snapshots (0.8852 ± 0.0207,
   0.8852 ± 0.0209, 0.8869 ± 0.0206, 0.8869 ± 0.0211). 35.3% ± 4.6% of them are
   outside ±25%. **DERIVED:** a stop pinned at 1.5 × ATR_entry is, by exit, sitting at
   `1.5 / 0.887 = 1.69 × ATR_exit` — roughly 13% wider in current-volatility terms.
   **HYPOTHESIS (not established here):** this is exactly the slack that lets those
   positions ride out noise, which is consistent with the ≥ 21-bar bucket being v3's
   *most* profitable (+0.7930R ± 0.1532, n = 102, snapshot 3) rather than its worst.
   Tightening the stop as ATR contracts would be a change motivated by a
   survivorship-selected statistic; §7 rules it out.

---

## 4. Expectancy conditioned on the ratio (terciles) — the headline number, and why it is not what it looks like

**FACT.** Terciles of the at-exit ratio, all pre-sealed trades, snapshot 3:

**v3 `medium_swing`** (tercile cuts at ratio 1.002 / 1.109)

| Tercile | n | ratio median | **expectancy ± SE** | mean bars | exit mix (stop / target / time) |
|---|---|---|---|---|---|
| T1 (ATR contracted) | 357 | 0.908 | **+0.5744R ± 0.0873** | 13.5 | 0.44 / **0.53** / 0.02 |
| T2 (ATR ≈ flat) | 357 | 1.056 | **−0.2106R ± 0.0738** | 5.0 | **0.69** / 0.30 / 0.00 |
| T3 (ATR expanded) | 357 | 1.182 | **+0.1363R ± 0.0848** | 6.2 | 0.58 / 0.42 / 0.00 |
| **T3 − T1** | | | **−0.4381R ± 0.1217** | | **z = −3.60** |

**v2 `short_swing` — control** (cuts at 1.005 / 1.105)

| Tercile | n | ratio median | **expectancy ± SE** | mean bars | exit mix (stop / target / time) |
|---|---|---|---|---|---|
| T1 | 390 | 0.922 | **+0.3031R ± 0.0646** | 7.7 | 0.31 / 0.15 / **0.53** |
| T2 | 389 | 1.055 | **−0.1581R ± 0.0651** | 4.5 | **0.59** / 0.22 / 0.19 |
| T3 | 390 | 1.170 | **+0.1539R ± 0.0828** | 4.7 | 0.50 / 0.35 / 0.15 |
| **T3 − T1** | | | **−0.1493R ± 0.1050** | | **z = −1.42** |

### 4.1 Snapshot stability of the tercile gradient

**FACT.** T3 − T1, all pre-sealed:

| | snap 1 | snap 2 | snap 3 | snap 4 |
|---|---|---|---|---|
| **v3** | −0.4511 ± 0.1205 (z −3.74) | −0.4511 ± 0.1205 (z −3.74) | **−0.4381 ± 0.1217 (z −3.60)** | −0.4774 ± 0.1205 (z −3.96) |
| **v2** | −0.1484 ± 0.1041 (z −1.43) | −0.1484 ± 0.1041 (z −1.43) | −0.1493 ± 0.1050 (z −1.42) | −0.1780 ± 0.1037 (z −1.72) |
| **v3 − v2** | −0.3027 ± 0.1592 (z −1.90) | −0.3027 ± 0.1592 (z −1.90) | **−0.2889 ± 0.1607 (z −1.80)** | −0.2993 ± 0.1590 (z −1.88) |

So: the v3 gradient is ≥ 2 SE and **highly snapshot-stable** (spread of 0.039R across
all four draws, well inside one SE). The v2 gradient is **under 2 SE on every
snapshot**. And the **v3 − v2 differential — the quantity H3 is actually about — is
under 2 SE on all four snapshots** (z = −1.80 to −1.90), even before the correlated-
samples caveat of §1 is applied.

### 4.2 The gradient is not stable between in-sample and out-of-sample

**FACT.** Splitting v3's pre-sealed trades at `backtest_runner.py:154-156`'s 60/40
boundary, snapshot 3:

| Cut | n | T1 | T2 | T3 | T3 − T1 | z |
|---|---|---|---|---|---|---|
| all pre-sealed | 1,071 | +0.5744 ± 0.0873 | −0.2106 ± 0.0738 | +0.1363 ± 0.0848 | **−0.4381 ± 0.1217** | −3.60 |
| in-sample | 752 | +0.5973 ± 0.0904 | −0.3278 ± 0.0856 | +0.0512 ± 0.1018 | **−0.5461 ± 0.1362** | −4.01 |
| **out-of-sample** | **319** | +0.5739 ± 0.2031 | −0.0979 ± 0.1344 | +0.4419 ± 0.1515 | **−0.1320 ± 0.2533** | **−0.52** |

The effect is **three to four times smaller out-of-sample and nowhere near 2 SE**
there (same on all snapshots: OOS z = −0.60, −0.60, −0.52, −0.64). A gradient that
survives a one-symbol change to the universe but not the IS→OOS split is not a
mechanism you can build on.

### 4.3 The gradient disappears entirely once the exit reason is held fixed

**FACT — the decisive control.** Re-computing the terciles *within* each exit reason,
snapshot 3:

| Subset | n | T1 | T2 | T3 | **T3 − T1** | z |
|---|---|---|---|---|---|---|
| v3, `stop` exits only | 612 | −1.0284 ± 0.0141 | −1.0616 ± 0.0325 | −1.0225 ± 0.0343 | **+0.0059 ± 0.0371** | **+0.16** |
| v3, `target` exits only | 445 | +1.9100 ± 0.0748 | +1.7785 ± 0.0868 | +1.7585 ± 0.0934 | **−0.1515 ± 0.1196** | **−1.27** |
| v2, `stop` exits only | 544 | −1.0195 ± 0.0187 | −1.0506 ± 0.0370 | −1.0715 ± 0.0744 | −0.0521 ± 0.0767 | −0.68 |
| v2, `target` exits only | 282 | +1.8536 ± 0.1166 | +1.6717 ± 0.0692 | +1.7115 ± 0.1402 | −0.1421 ± 0.1823 | −0.78 |

Both within-reason gradients are **under 2 SE**, and the `stop` gradient is
essentially exactly zero. Stop exits pay about −1.03R and target exits about +1.8R
whatever the ATR did; **all** of the −0.44R headline is the fact that T1 is 53%
targets and T2 is 69% stops.

**FACT — the endogeneity, shown directly.** Mean at-exit ratio by exit reason
(snapshot 3, v3): `stop` **1.073** (n = 612, mean P&L −1.038R, mean 5.9 bars),
`target` **1.024** (n = 445, +1.816R, 10.9 bars), `time_stop` **0.715** (n = 8),
`eod` 0.919 (n = 6). A trade stopped out on a large adverse bar puts that bar's true
range **into** ATR(14) at the exit index; ATR@exit is measured on a window that
contains the very move that ended the trade. **DERIVED:** ATR@exit / ATR@entry is
partly an *output* of the trade outcome, so §4's tercile split conditions on a
post-treatment variable. Under R1 ("no parameter, filter, exit, entry or universe
choice may be motivated by …") and R5 (multiple-testing discipline), a gradient with
this structure is not admissible evidence for a design change even though it clears
2 SE.

---

## 5. What is measurable at ≥ 2 SE — the honest list

| # | Claim | Estimate ± SE | z | Snapshot-stable? |
|---|---|---|---|---|
| 1 | ATR(14) drifts materially over 40 sessions (mean \|log\|, H = 40 vs H = 10, all trades) | +0.1283 ± 0.0115 | +11.2 | yes (all four within 0.001) |
| 2 | v3's realised at-exit mis-scaling exceeds v2's (mean \|log ratio\|) | +0.0128 ± 0.0044 | +2.89 | yes (+0.0122…+0.0128) |
| 3 | Among v3 trades held ≥ 21 bars, exit ATR is below entry ATR (median ratio vs 1.0) | −0.1131 ± 0.0211 | −5.36 | yes (−0.113…−0.115) |
| 4 | v3 expectancy gradient across at-exit ratio terciles (T3 − T1, all pre-sealed) | −0.4381R ± 0.1217 | −3.60 | yes (−0.438…−0.477) |
| — | **and what is NOT ≥ 2 SE** | | | |
| 5 | Median at-exit ratio, v3 vs v2 | +0.0012 ± 0.0062 | +0.19 | yes (all ≈ 0) |
| 6 | v3-minus-v2 tercile gradient (the leash effect on H3) | −0.2889R ± 0.1607 | −1.80 | yes, and under 2 SE on all four |
| 7 | v3 tercile gradient, **out-of-sample only** | −0.1320R ± 0.2533 | −0.52 | yes, and under 2 SE on all four |
| 8 | v3 tercile gradient **within `stop` exits** | +0.0059R ± 0.0371 | +0.16 | yes |
| 9 | v3 tercile gradient **within `target` exits** | −0.1515R ± 0.1196 | −1.27 | yes |
| 10 | Expectancy gradient across **entry-time** ATR(14)/ATR(50) terciles (§6) | +0.1374R ± 0.1209 | +1.14 | yes, under 2 SE on all four |

Rows 1–4 are real. Row 1 is a fact about daily volatility, not about v3 (v2's trade
set gives the same number). Row 2 is real but worth 1.3 percentage points of ATR.
Row 3 is real and survivorship-generated (§3, reading 3). Row 4 is real and fully
explained by rows 8–9. The four rows that would have to be ≥ 2 SE for H3 to motivate
anything — 6, 7, 8, 9 — are all under it.

**DERIVED, for scale.** The median ATR/price at v3's entries is **1.29%**
(IQR 0.98%–1.76%), so the modelled 11.0 bps round trip
(`engine.py:143`) costs a median of **0.057R per trade**
(`0.0011 / (1.5 × 0.0129)`; mean 0.060R, IQR 0.042–0.075R). Two consequences:
*(a)* map §0.4's 0.037R reference figure for the trend family assumed a 2% ATR/price
and therefore **understates** this family's real modelled cost by ~50% — the trend
strategies enter on lower-volatility names than that reference; *(b)* the entire
snapshot-3 sealed shortfall for v3 (0.0294R, map §2.1) is **half of one trade's
modelled transaction cost**, which strengthens rather than weakens §2.1's lever 1.

---

## 6. The exogenous control: does entry-time volatility state predict anything?

If ATR(14) at entry were a poor risk scale *from the start* — the design-actionable
version of H3, because it uses only information available at the signal bar — then
expectancy should vary with how stretched ATR(14) is against its own longer-run level.

**FACT.** Terciles of `ATR(14)/ATR(50)` at the signal bar, all pre-sealed:

| Snap | strategy | T1 (contracted) | T2 | T3 (expanded) | T3 − T1 | z |
|---|---|---|---|---|---|---|
| 3 | **v3** | +0.1341 ± 0.0896 | +0.0975 ± 0.0805 | +0.2716 ± 0.0811 | **+0.1374 ± 0.1209** | **+1.14** |
| 1/2 | v3 | +0.1366 ± 0.0886 | +0.1051 ± 0.0797 | +0.2828 ± 0.0809 | +0.1463 ± 0.1199 | +1.22 |
| 4 | v3 | +0.1298 ± 0.0874 | +0.1155 ± 0.0791 | +0.2689 ± 0.0819 | +0.1391 ± 0.1198 | +1.16 |
| 3 | v2 | +0.0327 ± 0.0808 | +0.0968 ± 0.0681 | +0.1727 ± 0.0664 | +0.1400 ± 0.1045 | +1.34 |

**FACT.** Under 2 SE for both strategies on every snapshot, and the same sign and
magnitude for v3 and v2 — so there is no medium-swing-specific entry-time volatility
effect either. The one conditioner that *could* legitimately have motivated a design
change carries no signal.

---

## 7. Verdict on H3, and what it licenses

**H3 is NOT SUPPORTED and its stated falsification criterion in §2.1 is met.**

1. **FACT.** ATR@exit / ATR@entry is tightly clustered near 1 for v3 (median
   1.0565 ± 0.0047, IQR [0.963, 1.137], 83.9% within ±25%) — the map's own explicit
   falsification condition.
2. **FACT.** It is statistically indistinguishable from the 10-bar v2 control in
   central tendency (median difference +0.0012 ± 0.0062, z = +0.19); the only ≥ 2 SE
   difference is a ~1.3 pp dispersion gap.
3. **FACT.** H3's premise is largely counterfactual: 0.75% of v3's pre-sealed trades
   exit on the 40-bar time stop, median hold 5 bars, only 9.5% hold ≥ 21 bars.
4. **FACT.** The one large, snapshot-stable expectancy gradient across ratio terciles
   is exit-composition: it vanishes within `stop` exits (+0.006 ± 0.037) and within
   `target` exits (−0.152 ± 0.120), and it is not stable IS → OOS (−0.546 → −0.132).
5. **FACT.** The v3-minus-v2 differential — the only version of the gradient that
   isolates the leash — is under 2 SE on **all four** snapshots.
6. **FACT.** The exogenous, known-at-entry version of the question (entry
   ATR(14)/ATR(50)) is under 2 SE on all four snapshots for both strategies.

**Snapshot stability, asked separately because the task asks it separately:** every
statistic in this document is stable across snapshots 1–4 to well within one SE, in
both directions — the significant ones stay significant and the non-significant ones
stay non-significant. Snapshots 1 and 2 are literally the same run (§0); 3 and 4
differ from them by removing or bridging one symbol, which changes the pre-sealed
trade count by −1.8% / +1.9% and moves no ratio statistic by more than 0.005.
**HYPOTHESIS:** snapshot stability here is weak evidence generally — a one-symbol
perturbation of a 25-symbol universe is a small shock — and it clearly did not protect
the tercile gradient from collapsing under the IS/OOS split, which is a far more
informative robustness cut. Future W2 diagnostics should treat "snapshot-stable" as
necessary, not sufficient.

### What this licenses under the rules of engagement

- **R1/R10.** H3 may **not** motivate any v0.2.0 parameter, filter, exit, entry or
  universe choice. Specifically: **no ATR-window change, no volatility-scaled or
  trailing stop, and no ATR re-estimation during the hold may cite this diagnostic as
  its motivation.** §2.1 lever 3 ("make the exit horizon-consistent") and lever 4
  ("re-scale risk geometry") gain **no** support here; lever 4's MAE/MFE
  justification is untouched by this work and remains to be tested separately.
- **R5.** This diagnostic evaluated **zero** strategy variants; the variant count for
  version 3 is unchanged.
- **R2.** No sealed test was computed or read into any argument above. The sealed-look
  count for every strategy family remains **k = 5**.
- **Consistent with §2.1 lever 1** (do nothing to the rule set; document honestly),
  which after this diagnostic, the sibling H1/H2 diagnostic, and §5's cost arithmetic
  is supported by three independent lines of pre-sealed evidence rather than one.

### Two loose ends, flagged not fixed

1. **HYPOTHESIS (untested).** The ≥ 21-bar bucket's systematic ATR contraction (§3,
   reading 3) means the effective stop widens to ~1.69 × ATR_exit precisely on v3's
   best trades. Whether *narrowing* it there would help or hurt cannot be answered
   from this data, because the bucket is defined by survival — the question is only
   answerable by simulating an alternative exit rule end-to-end on pre-sealed folds,
   which would be a v0.2.0 variant and would count under R5.
2. **FACT, worth propagating.** Map §0.4's cost table uses a 2% ATR/price reference
   for the trend family; the measured median at v3's own entries is 1.29%, making the
   modelled cost **0.057R per trade**, not 0.037R. Every place §0.4's trend-family
   cost figure is used downstream should be re-derived at the measured value.

---

## 8. Files

- Write-up: `/Users/louisbrailey/signal-forge/docs/research/diagnostics/v3_atr_at_exit.md`
- Raw numbers (all four snapshots, both strategies, every statistic above):
  `/Users/louisbrailey/signal-forge/docs/research/diagnostics/v3_atr_at_exit.json`
- Scratch DB copy used for the runs (not committed):
  `$TMPDIR/scratch-v3_atr_at_exit.sqlite`
