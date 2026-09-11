# W2 diagnostic — `trend_continuation.medium_swing` (version 3): holding duration and exit mix

**Question asked (STRATEGY_COMPLETION_MAP.md §2.1, H1/H2).**
H1 *duration mismatch* — does the 40-bar leash hold positions through reversals the
10-bar version never sees? H2 *target unreachable inside the leash* — is the
3.0×ATR(14) target so rarely reached within 40 bars that the time stop becomes the
modal exit?

**Answer, stated up front: both hypotheses are FALSIFIED, on all four dataset
snapshots, on the pre-sealed span, on both the all-pre-sealed and OOS cuts.**
There is no duration defect to fix. The long-duration buckets are v3's *most*
profitable, the 40-bar time stop is reached by **0.7%** of pre-sealed trades
(8 of 1,071 on snapshot 3), and a matched-pair experiment shows the extra leash is
worth **+0.18R ± 0.08** per affected trade pre-sealed. Under R10 neither H1 nor H2
may motivate a v0.2.0.

---

## 0. Method, provenance and safety

**FACT.** Everything below is computed in-process by
`research.backtest_runner.run_strategy_over_universe`
(`/Users/louisbrailey/signal-forge/src/signalforge/research/backtest_runner.py:161-243`),
which contains no `session.add`, `flush` or `commit` — it is a pure read path. The
run was executed against a point-in-time `.backup` copy of the live database at
`$TMPDIR/scratch-v3_duration_exits.sqlite` with
`DATABASE_URL="sqlite+pysqlite:///$TMPDIR/scratch-v3_duration_exits.sqlite"`. The live
`data/signalforge.sqlite` was read only by `SELECT` and by the backup copy. No file
under `src/` or `tests/` was modified. **No promotion evaluation was run and no
`strategy_sealed_test` row was created: the sealed-look count remains k = 5 (§0.1/R2).**

**FACT — the sealed window was not touched.** Each run covers only
`[start, pre_sealed_end]`, where `pre_sealed_end = sealed_start − 1 day` exactly as
`promotion.py:557-563` computes it:

| Snapshot | key | symbols | source filter | run span (pre-sealed) | sealed window (untouched) |
|---|---|---|---|---|---|
| 1 | `universe_25_baseline_legacy` | 25 (incl. `META`) | `massive` | 2016-09-09 → **2025-09-06** | 2025-09-07 → 2026-09-07 |
| 2 | `universe_25_baseline` | 25 (incl. `META`) | `massive` | 2016-09-10 → **2025-09-07** | 2025-09-08 → 2026-09-08 |
| 3 | `universe_24_ex_meta` | 24 (**no** META) | `massive` | 2016-09-10 → **2025-09-07** | 2025-09-08 → 2026-09-08 |
| 4 | `universe_25_meta_continuity_corrected` | 25 (`META_CONT`) | `["massive", "continuity_bridge:1"]` | 2016-09-10 → **2025-09-07** | 2025-09-08 → 2026-09-08 |

(Snapshot symbol sets queried from `data_snapshot.symbols_json`; sealed windows from
`strategy_sealed_test.window_start/window_end` ids 1, 2, 6, 7, 11, 12, 16, 17. The
source filter for snapshot 4 follows
`research/fb_meta_universe_comparison.py:49-64`.) Other call arguments match
`promotion.py:585-594`: `proxy_symbol="SPY"`, default `CostModel()`
(0 commission / 3.0 bps slippage / half-spread on — the model recorded in every
evaluation's `data_provenance_json`), `min_bars=60`, and **`allow_short` left at its
default `False`**.

**FACT — the reproduction is exact.** Re-running v2 and v3 over each pre-sealed span
reproduces the stored evaluation numbers to the digit:

| | snap 1 | snap 2 | snap 3 | snap 4 |
|---|---|---|---|---|
| v3 pre-sealed trades | 1,091 | 1,091 | **1,071** | 1,112 |
| v3 OOS n / expectancy | 326 / +0.2936R | 326 / +0.2936R | **319 / +0.3064R** | **336 / +0.3169R** |
| v2 pre-sealed trades | 1,190 | 1,190 | **1,169** | 1,216 |
| v2 OOS n / expectancy | 348 / +0.2609R | 348 / +0.2609R | **341 / +0.2648R** | 359 / +0.2724R |

Snapshot 3's v3 (1,071 / 319 / +0.3064R) and v2 (1,169 / 341 / +0.2648R) match
§2.1 and §0.3 exactly; snapshot 4's v3 (336 / +0.3169R) matches the §2.1 quotation of
eval 39. Snapshots 1 and 2 are numerically identical (identical symbol sets; the
one-day span offset falls outside the data). This is the control that the harness
below is the same computation the gates ran.

**FACT — a useful side-validation of §0.3.** The map's per-trade `sd` was *inferred*
by inverting the stored bootstrap CI. The directly-measured OOS sample sd is
**1.726** for v3 snapshot 3 (§0.3 inferred 1.741, 0.9% apart) and **1.467** for v2
(§0.3 inferred 1.420, 3.3% apart). §0.3's SE arithmetic is sound.

**Direction mix (answers H5 in passing).** FACT: **every one of the 9,130 collected
trades is LONG** for both versions on all four snapshots. `evaluate_promotion` never
passes `allow_short`, so `signal_fn_for(..., allow_short=False)` suppresses the short
branch entirely (`trend_continuation.py:113-133` is dead code under the gates).
H5's falsification condition — "pre-sealed short trades are a negligible share" — is
met in its strongest form: the share is **zero**.

---

## 1. P&L by holding-duration bucket

Buckets are on `SimTrade.bars_held = exit_idx − entry_idx` (`engine.py:133`). **A
`bars_held = 0` bucket exists and is not optional to report**: 106 of v3's 1,071
snapshot-3 pre-sealed trades (9.9%) exit on the entry bar itself. The task's bucket
list starts at 1; suppressing bucket 0 would silently drop the single worst bucket in
the sample, so it is shown separately throughout.

`exp` = mean pnl_r; `SE` = sample sd / √n; `R/bar` = Σpnl_r / Σbars_held (a
capital-efficiency figure, not a per-trade one, so it carries no SE here).

### 1a. v3 `medium_swing` (time_stop_bars = 40) — ALL pre-sealed trades

| snap | bucket | n | exp | SE | total R | R/bar | exit mix |
|---|---|---|---|---|---|---|---|
| 1 | 0 | 106 | −0.7527 | 0.0889 | −79.79 | — | stop 97 / target 7 / eod 2 |
| 1 | 1–5 | 444 | −0.1822 | 0.0682 | −80.90 | −0.0658 | stop 301 / target 142 / eod 1 |
| 1 | 6–10 | 222 | **+0.5270** | 0.1153 | +117.00 | +0.0681 | stop 104 / target 118 |
| 1 | 11–20 | 216 | **+0.6990** | 0.1105 | +150.99 | +0.0482 | stop 87 / target 127 / eod 2 |
| 1 | 21–40 | 103 | **+0.7996** | 0.1519 | +82.36 | +0.0284 | stop 32 / target 62 / **time_stop 8** / eod 1 |
| 2 | *(identical to snapshot 1 in every cell)* | | | | | | |
| 3 | 0 | 106 | −0.7527 | 0.0889 | −79.79 | — | stop 97 / target 7 / eod 2 |
| 3 | 1–5 | 434 | −0.1843 | 0.0691 | −79.98 | −0.0666 | stop 295 / target 138 / eod 1 |
| 3 | 6–10 | 217 | **+0.5171** | 0.1162 | +112.20 | +0.0669 | stop 102 / target 115 |
| 3 | 11–20 | 212 | **+0.6850** | 0.1115 | +145.23 | +0.0473 | stop 86 / target 124 / eod 2 |
| 3 | 21–40 | 102 | **+0.7930** | 0.1532 | +80.89 | +0.0281 | stop 32 / target 61 / **time_stop 8** / eod 1 |
| 4 | 0 | 108 | −0.7390 | 0.0887 | −79.81 | — | stop 99 / target 7 / eod 2 |
| 4 | 1–5 | 450 | −0.2044 | 0.0687 | −91.98 | −0.0741 | stop 307 / target 142 / eod 1 |
| 4 | 6–10 | 227 | **+0.5069** | 0.1138 | +115.07 | +0.0655 | stop 108 / target 119 |
| 4 | 11–20 | 221 | **+0.7274** | 0.1092 | +160.76 | +0.0501 | stop 87 / target 132 / eod 2 |
| 4 | 21–40 | 106 | **+0.8066** | 0.1497 | +85.50 | +0.0287 | stop 33 / target 64 / **time_stop 8** / eod 1 |

### 1b. v3 `medium_swing` — OOS only (the cut H1 was written against)

| snap | bucket | n | exp | SE | total R | R/bar |
|---|---|---|---|---|---|---|
| 1 / 2 | 0 | 36 | −0.6383 | 0.1420 | −22.98 | — |
| 1 / 2 | 1–5 | 125 | −0.1000 | 0.1256 | −12.50 | −0.0350 |
| 1 / 2 | 6–10 | 65 | **+0.9350** | 0.2456 | +60.78 | +0.1220 |
| 1 / 2 | 11–20 | 73 | **+0.5654** | 0.2097 | +41.28 | +0.0394 |
| 1 / 2 | 21–40 | 27 | **+1.0791** | 0.3919 | +29.14 | +0.0393 |
| 3 | 0 | 36 | −0.6383 | 0.1420 | −22.98 | — |
| 3 | 1–5 | 122 | −0.1002 | 0.1273 | −12.23 | −0.0349 |
| 3 | 6–10 | 62 | **+0.9921** | 0.2535 | +61.51 | +0.1295 |
| 3 | 11–20 | 72 | **+0.5875** | 0.2114 | +42.30 | +0.0409 |
| 3 | 21–40 | 27 | **+1.0791** | 0.3919 | +29.14 | +0.0393 |
| 4 | 0 | 36 | −0.6383 | 0.1420 | −22.98 | — |
| 4 | 1–5 | 129 | −0.1204 | 0.1223 | −15.53 | −0.0420 |
| 4 | 6–10 | 67 | **+0.9896** | 0.2429 | +66.30 | +0.1290 |
| 4 | 11–20 | 76 | **+0.6324** | 0.2051 | +48.06 | +0.0438 |
| 4 | 21–40 | 28 | **+1.0931** | 0.3779 | +30.61 | +0.0401 |

### 1c. v2 `short_swing` (time_stop_bars = 10) — the control

By construction v2 cannot occupy the 11–20 or 21–40 buckets: `_resolve_exit`
(`engine.py:167-168`) forces an exit at `u − entry_idx >= 10`, and the only longer
exit reason, `eod`, fires only when fewer than 10 bars remain in the series.
**FACT: v2 has zero trades with `bars_held > 10` on all four snapshots.** The
duration comparison between the two versions therefore exists only in 0–10 bars,
plus v3's tail — which is exactly the object of interest.

ALL pre-sealed:

| snap | bucket | n | exp | SE | total R | R/bar | exit mix |
|---|---|---|---|---|---|---|---|
| 1 / 2 | 0 | 118 | −0.8338 | 0.1291 | −98.39 | — | stop 108 / target 8 / eod 2 |
| 1 / 2 | 1–5 | 482 | −0.2034 | 0.0647 | −98.04 | −0.0740 | stop 328 / target 152 / eod 2 |
| 1 / 2 | 6–10 | 590 | **+0.5475** | 0.0520 | +323.00 | +0.0604 | stop 116 / target 130 / **time_stop 344** |
| 3 | 0 | 118 | −0.8338 | 0.1291 | −98.39 | — | stop 108 / target 8 / eod 2 |
| 3 | 1–5 | 472 | −0.2057 | 0.0655 | −97.11 | −0.0749 | stop 322 / target 148 / eod 2 |
| 3 | 6–10 | 579 | **+0.5392** | 0.0523 | +312.22 | +0.0594 | stop 114 / target 126 / **time_stop 339** |
| 4 | 0 | 121 | −0.8148 | 0.1269 | −98.59 | — | stop 110 / target 9 / eod 2 |
| 4 | 1–5 | 491 | −0.2217 | 0.0650 | −108.86 | −0.0810 | stop 336 / target 153 / eod 2 |
| 4 | 6–10 | 604 | **+0.5410** | 0.0512 | +326.74 | +0.0596 | stop 120 / target 131 / **time_stop 353** |

OOS only:

| snap | bucket | n | exp | SE | total R | R/bar |
|---|---|---|---|---|---|---|
| 1 / 2 | 0 | 35 | −0.6854 | 0.1383 | −23.99 | — |
| 1 / 2 | 1–5 | 130 | −0.1399 | 0.1213 | −18.19 | −0.0501 |
| 1 / 2 | 6–10 | 183 | **+0.7266** | 0.1071 | +132.97 | +0.0800 |
| 3 | 0 | 35 | −0.6854 | 0.1383 | −23.99 | — |
| 3 | 1–5 | 127 | −0.1411 | 0.1229 | −17.91 | −0.0503 |
| 3 | 6–10 | 179 | **+0.7386** | 0.1085 | +132.21 | +0.0811 |
| 4 | 0 | 35 | −0.6854 | 0.1383 | −23.99 | — |
| 4 | 1–5 | 134 | −0.1583 | 0.1182 | −21.22 | −0.0564 |
| 4 | 6–10 | 190 | **+0.7526** | 0.1053 | +142.99 | +0.0828 |

### 1d. Holding-duration distribution (v3, snapshot 3, all pre-sealed)

FACT: median 5 bars; p75 = 12; p90 = 20; p95 = 26; p99 = 39. **29.3%** of trades run
past bar 10 (the length of v2's leash); **9.5%** past bar 20; **9 trades** reach
exactly 40 bars.

---

## 2. Exit-reason mix and expectancy per exit reason

The four reasons the engine can emit are `stop`, `target`, `time_stop`, `eod`
(`engine.py:155-179`); "other" in this program is exactly `eod` — an exit forced at
the last available close because the series ran out.

### 2a. v3 `medium_swing`

ALL pre-sealed:

| snap | reason | n | share | exp | SE | total R | mean bars |
|---|---|---|---|---|---|---|---|
| 1 / 2 | stop | 621 | 56.9% | −1.0372 | 0.0162 | −644.11 | 5.84 |
| 1 / 2 | target | 456 | 41.8% | +1.8162 | 0.0486 | +828.19 | 10.90 |
| 1 / 2 | **time_stop** | **8** | **0.7%** | **+0.3493** | 0.1716 | +2.79 | 40.00 |
| 1 / 2 | eod | 6 | 0.5% | +0.4645 | 0.3510 | +2.79 | 10.17 |
| 1 / 2 | **all** | 1,091 | 100% | **+0.1738** | 0.0480 | +189.65 | 8.23 |
| 3 | stop | 612 | 57.1% | −1.0375 | 0.0164 | −634.95 | 5.86 |
| 3 | target | 445 | 41.5% | +1.8156 | 0.0493 | +807.92 | 10.93 |
| 3 | **time_stop** | **8** | **0.7%** | **+0.3493** | 0.1716 | +2.79 | 40.00 |
| 3 | eod | 6 | 0.6% | +0.4645 | 0.3510 | +2.79 | 10.17 |
| 3 | **all** | 1,071 | 100% | **+0.1667** | 0.0484 | +178.55 | 8.24 |
| 4 | stop | 634 | 57.0% | −1.0418 | 0.0181 | −660.47 | 5.83 |
| 4 | target | 464 | 41.7% | +1.8199 | 0.0480 | +844.43 | 11.01 |
| 4 | **time_stop** | **8** | **0.7%** | **+0.3493** | 0.1716 | +2.79 | 40.00 |
| 4 | eod | 6 | 0.5% | +0.4645 | 0.3510 | +2.79 | 10.17 |
| 4 | **all** | 1,112 | 100% | **+0.1704** | 0.0478 | +189.54 | 8.26 |

OOS only:

| snap | reason | n | share | exp | SE | total R |
|---|---|---|---|---|---|---|
| 1 / 2 | stop | 180 | 55.2% | −1.0133 | 0.0242 | −182.40 |
| 1 / 2 | target | 139 | 42.6% | +1.9826 | 0.1100 | +275.59 |
| 1 / 2 | **time_stop** | **1** | **0.3%** | −0.2718 | n/a | −0.27 |
| 1 / 2 | eod | 6 | 1.8% | +0.4645 | 0.3510 | +2.79 |
| 1 / 2 | **all** | 326 | 100% | **+0.2936** | 0.0951 | +95.71 |
| 3 | stop | 175 | 54.9% | −1.0131 | 0.0249 | −177.29 |
| 3 | target | 137 | 42.9% | +1.9892 | 0.1115 | +272.52 |
| 3 | **time_stop** | **1** | **0.3%** | −0.2718 | n/a | −0.27 |
| 3 | eod | 6 | 1.9% | +0.4645 | 0.3510 | +2.79 |
| 3 | **all** | 319 | 100% | **+0.3064** | 0.0966 | +97.74 |
| 4 | stop | 183 | 54.5% | −1.0133 | 0.0238 | −185.44 |
| 4 | target | 146 | 43.5% | +1.9821 | 0.1068 | +289.39 |
| 4 | **time_stop** | **1** | **0.3%** | −0.2718 | n/a | −0.27 |
| 4 | eod | 6 | 1.8% | +0.4645 | 0.3510 | +2.79 |
| 4 | **all** | 336 | 100% | **+0.3169** | 0.0939 | +106.46 |

The eight pre-sealed 40-bar time-stop exits (identical set on all four snapshots, one
of them OOS): −0.297, +0.190, −0.272, +0.846, +0.301, +1.083, +0.502, +0.441.

### 2b. v2 `short_swing` — the control

ALL pre-sealed:

| snap | reason | n | share | exp | SE | total R | mean bars |
|---|---|---|---|---|---|---|---|
| 1 / 2 | stop | 552 | 46.4% | −1.0468 | 0.0280 | −577.85 | 3.10 |
| 1 / 2 | target | 290 | 24.4% | +1.7454 | 0.0641 | +506.17 | 5.25 |
| 1 / 2 | **time_stop** | **344** | **28.9%** | **+0.5733** | 0.0444 | +197.20 | 10.00 |
| 1 / 2 | eod | 4 | 0.3% | +0.2622 | 0.2796 | +1.05 | 1.00 |
| 1 / 2 | **all** | 1,190 | 100% | **+0.1064** | 0.0412 | +126.58 | 5.61 |
| 3 | stop | 544 | 46.5% | −1.0473 | 0.0284 | −569.71 | 3.09 |
| 3 | target | 282 | 24.1% | +1.7456 | 0.0649 | +492.26 | 5.24 |
| 3 | **time_stop** | **339** | **29.0%** | **+0.5697** | 0.0447 | +193.12 | 10.00 |
| 3 | eod | 4 | 0.3% | +0.2622 | 0.2796 | +1.05 | 1.00 |
| 3 | **all** | 1,169 | 100% | **+0.0998** | 0.0415 | +116.72 | 5.60 |
| 4 | stop | 566 | 46.5% | −1.0520 | 0.0290 | −595.42 | 3.12 |
| 4 | target | 293 | 24.1% | +1.7433 | 0.0638 | +510.80 | 5.21 |
| 4 | **time_stop** | **353** | **29.0%** | **+0.5747** | 0.0435 | +202.86 | 10.00 |
| 4 | eod | 4 | 0.3% | +0.2622 | 0.2796 | +1.05 | 1.00 |
| 4 | **all** | 1,216 | 100% | **+0.0981** | 0.0409 | +119.29 | 5.61 |

OOS only:

| snap | reason | n | share | exp | SE | total R |
|---|---|---|---|---|---|---|
| 1 / 2 | stop | 145 | 41.7% | −1.0181 | 0.0263 | −147.62 |
| 1 / 2 | target | 89 | 25.6% | +1.8765 | 0.1297 | +167.00 |
| 1 / 2 | **time_stop** | **110** | **31.6%** | **+0.6397** | 0.0963 | +70.36 |
| 1 / 2 | eod | 4 | 1.1% | +0.2622 | 0.2796 | +1.05 |
| 1 / 2 | **all** | 348 | 100% | **+0.2609** | 0.0785 | +90.79 |
| 3 | stop | 141 | 41.3% | −1.0181 | 0.0270 | −143.55 |
| 3 | target | 87 | 25.5% | +1.8843 | 0.1325 | +163.93 |
| 3 | **time_stop** | **109** | **32.0%** | **+0.6318** | 0.0969 | +68.87 |
| 3 | eod | 4 | 1.2% | +0.2622 | 0.2796 | +1.05 |
| 3 | **all** | 341 | 100% | **+0.2648** | 0.0795 | +90.31 |
| 4 | stop | 148 | 41.2% | −1.0180 | 0.0257 | −150.67 |
| 4 | target | 93 | 25.9% | +1.8758 | 0.1280 | +174.45 |
| 4 | **time_stop** | **114** | **31.8%** | **+0.6399** | 0.0942 | +72.95 |
| 4 | eod | 4 | 1.1% | +0.2622 | 0.2796 | +1.05 |
| 4 | **all** | 359 | 100% | **+0.2724** | 0.0774 | +97.79 |

**The structural read.** The 40-bar leash converts v2's 29% "time_stop at +0.57R"
bucket into a 41.5% "target at +1.82R" bucket and a larger 57% "stop at −1.04R"
bucket. Target share rises from 24.1% to 41.5% (snapshot 3, all pre-sealed) while
stop share rises from 46.5% to 57.1%. The 3.0×ATR target is *far* from unreachable
inside 40 bars — it is reached by 41.5% of all trades, at a mean of 10.9 bars.

---

## 3. Controlling the endogeneity — the duration gradient is composition, not decay

**Bucketing realised P&L by realised holding duration conditions on the outcome.** A
trade that gets stopped is *mechanically* short; a trade that reaches a 3×ATR target
is *mechanically* longer. The apparent "long holds are better" gradient in §1 could
be nothing but that composition. It is:

**FACT — expectancy *within* an exit reason is flat across duration** (v3, all
pre-sealed):

| snap | reason | bucket 0 | 1–5 | 6–10 | 11–20 | 21–40 |
|---|---|---|---|---|---|---|
| 3 | stop | −0.831 ± 0.091 (n=97) | −1.076 ± 0.013 (n=295) | −1.072 ± 0.012 (n=102) | −1.088 ± 0.018 (n=86) | −1.060 ± 0.021 (n=32) |
| 3 | target | +0.149 ± 0.261 (n=7) | +1.714 ± 0.089 (n=138) | +1.927 ± 0.105 (n=115) | +1.904 ± 0.080 (n=124) | +1.846 ± 0.127 (n=61) |
| 1 / 2 | stop | −0.831 ± 0.091 | −1.075 ± 0.012 | −1.071 ± 0.012 | −1.087 ± 0.018 | −1.060 ± 0.021 |
| 1 / 2 | target | +0.149 ± 0.261 | +1.702 ± 0.088 | +1.936 ± 0.104 | +1.913 ± 0.079 | +1.840 ± 0.125 |
| 4 | stop | −0.815 ± 0.091 | −1.091 ± 0.021 | −1.069 ± 0.012 | −1.087 ± 0.018 | −1.059 ± 0.021 |
| 4 | target | +0.149 ± 0.261 | +1.704 ± 0.088 | +1.937 ± 0.104 | +1.914 ± 0.078 | +1.848 ± 0.121 |

A stop is worth ≈ −1.07R whether it lands on bar 3 or bar 35 (spread across buckets
1–5 → 21–40 is 0.028R against SEs of 0.012–0.021, i.e. **≈ 1 SE**). A target is worth
≈ +1.9R whether it lands on bar 4 or bar 30 (the 1–5 bucket is ~0.2R lower than the
rest, which is the opposite sign to H1). **So the whole duration gradient in §1 is
exit-reason composition.** Any "P&L by duration bucket" table — including the one H1
asked for — must be read this way; it is not, on its own, a statement about the
leash.

**FACT — the same is true for v2**, which rules out the composition being a
medium-swing artefact: v2 stops are −1.081 ± 0.013 (1–5) vs −1.074 ± 0.011 (6–10),
targets +1.687 ± 0.085 vs +1.917 ± 0.097 (snapshot 3).

---

## 4. The actual causal test of the leash: a matched-pair experiment

v2 and v3 differ in exactly one line —
`TrendParams(time_stop_bars=40) if horizon is MEDIUM_SWING else TrendParams()`
(`trend_continuation.py:37-39`) — so their entry signals are identical. Matching
trades on `(symbol, entry_date)` isolates the leash's effect from every other
difference.

**FACT (snapshot 3, all pre-sealed):** 1,026 of v3's 1,071 trades share an exact
`(symbol, entry_date)` with a v2 trade. Of those, **304 diverged** (different
`bars_held`), and in **every single divergence v2's exit reason was `time_stop`** —
i.e. divergence happens exactly when v2's 10-bar leash bit and v3's did not. What
happened next:

| snapshot | v2 exit → v3 exit | n | v2 exp | v3 exp | paired diff | SE |
|---|---|---|---|---|---|---|
| 3 | time_stop → **target** | 180 (59.2%) | +0.756 | **+1.881** | **+1.125** | 0.050 |
| 3 | time_stop → **stop** | 113 (37.2%) | +0.236 | **−1.082** | **−1.318** | 0.066 |
| 3 | time_stop → time_stop (40) | 8 | +0.139 | +0.349 | +0.210 | 0.155 |
| 3 | time_stop → eod | 3 | +1.195 | +0.686 | −0.509 | 0.586 |
| 1 / 2 | time_stop → target | 184 (59.5%) | +0.753 | +1.885 | +1.132 | 0.050 |
| 1 / 2 | time_stop → stop | 114 (36.9%) | +0.247 | −1.082 | −1.328 | 0.067 |
| 4 | time_stop → target | 191 (60.3%) | +0.752 | +1.889 | +1.137 | 0.049 |
| 4 | time_stop → stop | 115 (36.3%) | +0.243 | −1.081 | −1.325 | 0.066 |

**Net effect of the extra leash, per trade:**

| cut | snap | matched n | diverged n | mean paired diff over **all matched** | SE | mean paired diff over **diverged only** | SE |
|---|---|---|---|---|---|---|---|
| all pre-sealed | 1 / 2 | 1,046 | 309 | **+0.0545** | 0.0230 (**+2.4 SE**) | **+0.1843** | 0.0774 (**+2.4 SE**) |
| all pre-sealed | 3 | 1,026 | 304 | **+0.0524** | 0.0231 (**+2.3 SE**) | **+0.1770** | 0.0777 (**+2.3 SE**) |
| all pre-sealed | 4 | 1,067 | 317 | **+0.0609** | 0.0228 (**+2.7 SE**) | **+0.2049** | 0.0763 (**+2.7 SE**) |
| OOS | 1 / 2 | 316 | 99 | +0.0239 | 0.0437 (+0.5 SE) | +0.0764 | 0.1398 (+0.5 SE) |
| OOS | 3 | 309 | 98 | +0.0326 | 0.0439 (+0.7 SE) | +0.1029 | 0.1386 (+0.7 SE) |
| OOS | 4 | 326 | 103 | +0.0406 | 0.0433 (+0.9 SE) | +0.1285 | 0.1372 (+0.9 SE) |

**Interpretation.** Holding past bar 10 is a positive-expectancy bet: 59–60% of the
positions v2 abandons go on to make the full 3×ATR target, 36–37% give back the open
profit and take the −1R stop, and the arithmetic nets to **+0.18 to +0.20R per
affected trade** over the whole pre-sealed span (2.3–2.7 SE, i.e. **just over the
2 SE bar** set by the rules of engagement, on all four snapshots) and to
**+0.08 to +0.13R** on the OOS subset alone (0.5–0.9 SE — **under 2 SE, therefore not
evidence** on its own; it is however the same sign on all four snapshots and
consistent with the better-powered full-span figure).

**Cross-check on total R (no matching, no conditioning).** FACT:

| snap | v3 n / total R | v2 n / total R | v3 R per bar held | v2 R per bar held |
|---|---|---|---|---|
| 1 / 2 | 1,091 / **+189.65** | 1,190 / +126.58 | +0.0211 | +0.0190 |
| 3 | 1,071 / **+178.55** | 1,169 / +116.72 | +0.0202 | +0.0178 |
| 4 | 1,112 / **+189.54** | 1,216 / +119.29 | +0.0206 | +0.0175 |

v3 earns **more total R from fewer trades** on every snapshot, and is also better per
*bar of exposure* — so the longer hold is not simply buying return with capital
occupancy. (v2's higher trade count comes from being flat sooner and re-entering:
143 of its snapshot-3 trades have no v3 counterpart, against 45 the other way.)

---

## 5. Verdicts against the §2.1 falsification conditions

### H1 — duration mismatch: **FALSIFIED on all four snapshots**

§2.1's condition: *"Required before it may motivate anything: pre-sealed OOS P&L by
holding-bucket showing buckets 11–40 net negative in per-bar R, on all four
snapshots. Falsified if those buckets are net positive and comparable in per-bar R to
1–10."*

FACT: on OOS the 11–20 bucket is **+0.0394 / +0.0409 / +0.0438** R per bar and the
21–40 bucket **+0.0393 / +0.0393 / +0.0401** R per bar (snaps 1-2 / 3 / 4). Both are
**positive on every snapshot**, and both are *far above* the 1–5 bucket's
**−0.035 to −0.042** R per bar. The condition for H1 to survive ("net negative in
per-bar R") is not met anywhere; the explicit falsification condition ("net positive
and comparable") is met, and in fact overshot — long buckets are net positive *and*
have higher per-trade expectancy than the short buckets (+0.57R to +1.09R vs
−0.10R to −0.20R). §3 then shows even that gradient is composition, and §4 shows the
mechanism the leash actually adds is worth +0.18R per affected trade pre-sealed.
**H1 is dead. It may not motivate a v0.2.0 (R10).**

### H2 — target unreachable inside the leash: **FALSIFIED on all four snapshots**

§2.1's condition: *"Falsified if: the pre-sealed exit-reason mix shows target hits
dominate, or that time-stop exits are on average non-negative."*

FACT, both limbs are satisfied and the hypothesis's own premise is false:

1. The time stop is **not** the modal exit for v3 — it is the *rarest* real exit.
   **8 of 1,071–1,112 pre-sealed trades (0.7%)**, and **1 of 319–336 OOS trades
   (0.3%)**, on every snapshot. The modal exit is `stop` (57%), then `target` (42%).
2. Target hits dominate in R. On snapshot 3, **+807.92R of the +813.50R of gross
   positive exit-reason P&L (99.3%) comes from targets** (time_stop +2.79R, eod
   +2.79R), against stops at −634.95R. v3's entire edge is target-driven; the time
   stop contributes 0.3% of gross positive R.
3. Time-stop exits are **non-negative on average**: **+0.3493R ± 0.1716 (n = 8)**
   pre-sealed on all four snapshots. (n = 8 is far too small to be evidence of
   anything on its own — the point is only that the sign is not negative, which is
   what the falsification condition asks.)
4. Targets are reached in a **mean of 10.9 bars**, well inside the 40-bar leash — and
   also inside it comfortably enough that v2's 10-bar leash is the one that truncates
   them (§4).

**H2 is dead. It may not motivate a v0.2.0 (R10).**

### Snapshot dependence — is any of this a META artefact?

FACT: **no.** Every finding above holds on snapshots 1, 2, 3 **and** 4 with
essentially identical magnitudes. Snapshots 1 and 2 are numerically identical to each
other; snapshot 3 (META removed) and snapshot 4 (META replaced by the continuity
bridge) shift bucket counts by ≤ 5% and expectancies by ≤ 0.05R — always far under
1 SE. There is **no snapshot-3-only effect anywhere in this diagnostic**, so the
§0.1/R10 META-artefact caveat does not bite. The one place META does move a number
materially is the sealed year (§2.1: 3 trades worth +3.86R), which this diagnostic
deliberately never touched.

---

## 6. Incidental findings (not part of H1/H2; flagged, not acted on)

**(a) FACT — the entry-bar exit bucket is the single largest destroyer of R in both
versions, and nobody has looked at it.** 106 of v3's 1,071 snapshot-3 pre-sealed
trades (9.9%) exit on the *entry bar itself* (`bars_held = 0`), at a mean of
**−0.7527R ± 0.0889**, totalling **−79.79R** — that is **45% of v3's entire
pre-sealed +178.55R**, thrown away on the day of entry. v2's is worse: 118 trades,
−0.8338R ± 0.1291, −98.39R (84% of v2's +116.72R). 97 of v3's 106 are `stop`.

HYPOTHESIS (needs its own diagnostic before it may motivate anything): part of this
is a *risk-unit* artefact rather than a market effect. `engine.py:110` sets
`risk_per_share = |entry_fill − stop_price|` from the **entry bar's open**, while
`stop_price` was fixed off the **prior bar's close** (`trend_continuation.py:104`).
When the entry bar gaps down toward the stop, the risk unit collapses and the fixed
5.5 bps-per-side slippage becomes enormous *in R*: the snapshot-3 tail contains
2 trades below −2R (min **−6.13R**) for v3 and 3 for v2 (min **−12.38R**), together
−8.22R and −20.60R. Also note `_resolve_exit` uses `sig.stop_price` (not
`min(open, stop)`) when the exit lands on the entry bar (`engine.py:157`), which is
the *optimistic* branch — 21 of v3's 106 bucket-0 trades post a positive pnl_r.
This is an **engine/risk-scaling question**, it is present identically in the
PAPER_APPROVED v2, and it is out of scope here: it cannot explain any v2/v3
difference. Recommend a separate W2 item.

**(b) FACT — v3's short branch is unreachable under the gates.** All 9,130 trades are
LONG (§0). `evaluate_promotion` never sets `allow_short`, so
`trend_continuation.py:113-133` never executes in any promotion evidence. H5's
falsification condition is met at zero. Any v0.2.0 reasoning about short-side
behaviour would be reasoning about untested code.

**(c) FACT — `time_stop_bars` is measurable and it matters.** §0.5 warns that gate 5
never perturbs `time_stop_bars`, and §2.1 flags the *silent* gate-5 failure mode
where a retained-but-unused field makes all 9 grid points identical. This diagnostic
is direct evidence that the axis is live: changing `time_stop_bars` from 10 to 40
changes the pre-sealed trade count by ~8%, the exit mix by ~17pp of target share, and
the total R by +53 to +70R. If any v0.2.0 in this family ships, adding
`time_stop_bars` as a gate-5 axis would be a genuine test, not a no-op.

---

## 7. What this licenses, and what it does not

**Licensed conclusions.**

1. H1 and H2 are refuted on pre-sealed data on all four snapshots. Under R10 they are
   removed from the candidate-mechanism list for `trend_continuation.medium_swing`
   v0.2.0. §2.1's lever 2 ("scale lookbacks with the horizon") was explicitly
   conditioned on *"only if a W2 diagnostic first establishes a duration effect (H1)
   that holds on all four snapshots"* — **that condition has now failed, so lever 2 is
   closed.** §2.1's lever 3 ("make the exit horizon-consistent", motivated by H2) has
   lost its stated motivation: the time stop is reached 0.7% of the time and pays
   +0.35R when it is.
2. On the pre-sealed evidence the *longer* leash is the better of the two exits, not
   the worse one: +0.052 to +0.061R per matched trade (2.3–2.7 SE), +0.18 to +0.20R
   per trade it actually affects, more total R from fewer trades, and more R per bar
   of exposure — on every snapshot. HYPOTHESIS (not tested here): the same logic
   suggests a leash *longer* than 40 bars might add further value. **This is not a
   recommendation** — it is precisely the kind of parameter search R5 warns costs
   credibility, it would burn look 5, and §2.1 lever 1 ("do nothing") is unaffected by
   anything in this document.
3. §2.1's lever 1 is strengthened, not weakened. The diagnostic that was supposed to
   justify changing v3 has instead found the medium-swing exit to be the sounder of
   the two on nine years of pre-sealed data. There is no mechanism-motivated change
   left standing from H1/H2.

**Not licensed.**

- Nothing here says anything about the sealed year. The pre-sealed/sealed gap
  documented in §0.3 (v3's sealed mean 1.65–1.88σ below its pre-sealed mean) is
  untouched by this diagnostic and is **not** explained by duration or exit mix.
- The OOS paired difference (+0.024 to +0.041R, 0.5–0.9 SE) is **under 2 SE and is
  not evidence**. Only the full pre-sealed span clears 2 SE. Anyone quoting the leash
  benefit must quote the OOS figure alongside it.
- The 2.3–2.7 SE paired result is a *single* pre-registered comparison of the two
  shipped configurations, not a search. It must not be turned into a grid over
  `time_stop_bars` and then reported as if the surviving point had been the only one
  tried (R5).
- The bucket-0 finding (§6a) is a hypothesis about the engine's risk scaling. It has
  not been tested and must not motivate a change to `src/` until it has been.

**Variant count for R5:** this diagnostic evaluated **zero** new strategy variants. It
re-ran the two already-shipped configurations (v0.1.0 `short_swing` and v0.1.0
`medium_swing`) on the pre-sealed span. No sealed look was consumed; k remains 5.

---

*Raw per-bucket / per-reason / per-pair numbers: `v3_duration_exits.json` (sibling).
Trade-level CSV (9,130 rows) was written to the session scratchpad only and is not
committed.*
