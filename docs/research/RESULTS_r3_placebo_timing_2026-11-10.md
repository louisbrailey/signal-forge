# Results — R3-P: do the entry signals beat random entries with the same exits?

None of the four approved versions beats the pre-registered placebo (P-gate) at p < 0.05 on both IS and OOS, so the pre-registered reading for each is that its R is "not distinguishable from gated (or trend-state) exposure with its exit geometry on this universe". Against that placebo, OOS timing alpha is positive for trend_continuation.short_swing (+0.135R, p 0.020, Holm 0.080) and trend_continuation.medium_swing (+0.033R, p 0.144, Holm 0.433), and negative for relative_strength.medium_swing (-0.061R, p 0.801) and high52_breakout.medium_swing (-0.121R, p 0.985); on IS every version earned less per trade than the placebo (p 0.930 to 1.000). The placebo is not plain random entry: for each symbol and calendar year it draws as many random gate-allowed dates as the rule had trades there, with the same stop, target and time stop, so the comparison tests whether a trigger picked better days than chance inside the symbol-years it traded and says nothing about whether a rule earns more than plain gated exposure.

Being told the symbol-years favours the placebo. A post hoc check that is not pre-registered and decides nothing (under "Deviations and clarifications") puts a rough size on it: a signal on every gate-allowed bar, with the same exits through the same engine, earned +0.089R to +0.255R per trade OOS, so the placebo's OOS expectancy is 1.4 to 2.4 times that of plain gated exposure. The pre-registration also said a "no" would make "a looser trigger with the same exits" a legitimate candidate to pre-register next; this study does not support that step, because a looser trigger would not know which symbol-years to trade and the placebo does.

Pre-registration: `docs/research/PREREGISTRATION_r3_placebo_timing_2026-11-10.md` (commit 9bc9d24). Script: `scripts/r3/placebo_timing.py`. Development window 2016-10-17..2025-09-05, daily `massive` bars from the read-only scratch copy of 2026-11-10. K = 200 placebo runs per version and null, seeds 20261110 + run index. No sealed data, no database write, no change to any frozen study or approved version.

The two placebos. **P-gate** (primary): for every symbol and calendar year, as many random signal dates as the real rule had trades in that symbol-year, drawn uniformly from that symbol-year's bars on which the version's own regime gate allows an entry; stop, target and time stop from ATR14 at the drawn bar with the version's own multiples; one position per symbol. **P-trend** (secondary): the same, drawn only from bars that also have close > SMA50. Both are told how many trades the rule had in each symbol-year. "Placebo" below always means these, never plain random entry.

## Primary comparison — P-gate, OOS, engine R

| Version (snapshot) | OOS trades | Actual exp. R | Placebo mean [2.5%, 97.5%] | Timing alpha | p (one-sided) | Holm p | K |
|---|---:|---:|---:|---:|---:|---:|---:|
| trend_continuation.short_swing (3) | 341 | +0.265 | +0.130 [+0.008, +0.259] | +0.135 | 0.020 | 0.080 | 200 |
| relative_strength.medium_swing (3) | 197 | +0.300 | +0.361 [+0.220, +0.485] | -0.061 | 0.801 | 1.000 | 200 |
| trend_continuation.medium_swing (11) | 1,986 | +0.221 | +0.188 [+0.128, +0.242] | +0.033 | 0.144 | 0.433 | 200 |
| high52_breakout.medium_swing (11) | 525 | +0.227 | +0.349 [+0.239, +0.482] | -0.121 | 0.985 | 1.000 | 200 |

Timing alpha = actual expectancy − placebo mean. p = (number of placebo runs with expectancy ≥ actual + 1) / (K + 1); with K = 200 the smallest possible p is 0.005. OOS is the runner's definition: each symbol's last 40% of bars by entry date, from 2022-02-10 for full-history symbols. No rule parameter is fitted on IS, so IS and OOS are simply the earlier and the later period.

The same comparison in stable R, `(exit − entry) / (close_t − stop_t)`:

| Version | Actual exp. stable R | Placebo mean [2.5%, 97.5%] | Timing alpha | p (one-sided) | Holm p |
|---|---:|---:|---:|---:|---:|
| trend_continuation.short_swing | +0.273 | +0.127 [+0.013, +0.240] | +0.146 | 0.005 | 0.020 |
| relative_strength.medium_swing | +0.291 | +0.359 [+0.223, +0.484] | -0.068 | 0.826 | 1.000 |
| trend_continuation.medium_swing | +0.204 | +0.183 [+0.125, +0.241] | +0.020 | 0.239 | 0.716 |
| high52_breakout.medium_swing | +0.257 | +0.348 [+0.244, +0.480] | -0.091 | 0.965 | 1.000 |

## Pre-registered reading, per version

Rule fixed in advance: timing alpha with p < 0.05 against P-gate on both IS and OOS means the trigger adds value beyond gated exposure; against P-trend as well, beyond a simple trend state; otherwise the version's R is not distinguishable from gated (or trend-state) exposure with its exit geometry on this universe. Engine R decides; the P-gate OOS leg uses the Holm-adjusted p. The rule is applied as written. Its words "gated exposure" stand for the P-gate placebo as pre-registered, which draws inside the symbol-years the rule traded and is not plain gated exposure (Limits).

| Version | P-gate p IS | P-gate p OOS (raw / Holm) | Beats P-gate on both | P-trend p IS | P-trend p OOS | Beats P-trend on both | Same reading in stable R |
|---|---:|---:|:---:|---:|---:|:---:|:---:|
| trend_continuation.short_swing | 1.000 | 0.020 / 0.080 | no | 1.000 | 0.010 | no | yes |
| relative_strength.medium_swing | 0.930 | 0.801 / 1.000 | no | 0.841 | 0.726 | no | yes |
| trend_continuation.medium_swing | 1.000 | 0.144 / 0.433 | no | 1.000 | 0.010 | no | yes |
| high52_breakout.medium_swing | 1.000 | 0.985 / 1.000 | no | 1.000 | 0.935 | no | yes |

- **trend_continuation.short_swing** — Does not beat the P-gate placebo at p < 0.05 on both IS and OOS. Pre-registered reading: its R is "not distinguishable from gated (or trend-state) exposure with its exit geometry on this universe". P-gate p: IS 1.000, OOS 0.020 raw / 0.080 Holm. P-trend p: IS 1.000, OOS 0.010.
- **relative_strength.medium_swing** — Does not beat the P-gate placebo at p < 0.05 on both IS and OOS. Pre-registered reading: its R is "not distinguishable from gated (or trend-state) exposure with its exit geometry on this universe". P-gate p: IS 0.930, OOS 0.801 raw / 1.000 Holm. P-trend p: IS 0.841, OOS 0.726.
- **trend_continuation.medium_swing** — Does not beat the P-gate placebo at p < 0.05 on both IS and OOS. Pre-registered reading: its R is "not distinguishable from gated (or trend-state) exposure with its exit geometry on this universe". P-gate p: IS 1.000, OOS 0.144 raw / 0.433 Holm. P-trend p: IS 1.000, OOS 0.010.
- **high52_breakout.medium_swing** — Does not beat the P-gate placebo at p < 0.05 on both IS and OOS. Pre-registered reading: its R is "not distinguishable from gated (or trend-state) exposure with its exit geometry on this universe". P-gate p: IS 1.000, OOS 0.985 raw / 1.000 Holm. P-trend p: IS 1.000, OOS 0.935.

A "no" does not make a rule unprofitable, and it does not say the rule earns no more than plain gated exposure. It says the rule did not earn more, on both segments, than random gate-allowed dates inside the same symbol-years with the same number of trades and the same exits. The pre-registration attached two consequences to a "no": refinement effort "belongs in exposure, capacity and costs", and "a looser trigger with the same exits is a legitimate candidate to pre-register next". The second does not follow from this placebo: a looser trigger would not know in advance which symbol-years to trade, and the placebo does (Limits).

## Every pre-registered cell

Placebo columns are the mean over K runs with the 2.5th and 97.5th percentiles in brackets. Total R is the sum over all trades of the segment. p is one-sided (share of placebo runs at or above the actual value), so p = 1.000 means the real rule came in below every placebo run. Limits explains why these p-values overstate the evidence in both directions (the placebo dates do not bunch in time as the real signals do).

### trend_continuation.short_swing — snapshot 3 (24 symbols); stop 1.5 × ATR14, target 3 × ATR14, time stop 10 bars

Engine R:

| Null | Segment | Actual trades | Placebo trades (mean) | Actual exp. R | Placebo exp. R | Timing alpha | p | Actual total R | Placebo total R | K |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P-gate | IS | 828 | 828.0 | +0.032 | +0.197 [+0.124, +0.274] | -0.165 | 1.000 | +26.4 | +163.0 [+102.7, +226.8] | 200 |
| P-gate | OOS | 341 | 341.0 | +0.265 | +0.130 [+0.008, +0.259] | +0.135 | 0.020 | +90.3 | +44.2 [+2.8, +88.3] | 200 |
| P-gate | All | 1,169 | 1,169.0 | +0.100 | +0.177 [+0.118, +0.232] | -0.077 | 0.985 | +116.7 | +207.2 [+138.2, +271.1] | 200 |
| P-trend | IS | 828 | 827.9 | +0.032 | +0.164 [+0.090, +0.238] | -0.132 | 1.000 | +26.4 | +136.1 [+74.8, +197.2] | 200 |
| P-trend | OOS | 341 | 341.0 | +0.265 | +0.091 [-0.018, +0.198] | +0.173 | 0.010 | +90.3 | +31.2 [-6.0, +67.5] | 200 |
| P-trend | All | 1,169 | 1,168.9 | +0.100 | +0.143 [+0.085, +0.199] | -0.043 | 0.925 | +116.7 | +167.3 [+99.7, +232.4] | 200 |

Stable R:

| Null | Segment | Actual exp. stable R | Placebo exp. stable R | Timing alpha | p | Actual total stable R | Placebo total stable R |
|---|---|---:|---:|---:|---:|---:|---:|
| P-gate | IS | +0.056 | +0.208 [+0.140, +0.288] | -0.152 | 1.000 | +46.5 | +172.4 [+116.0, +238.2] |
| P-gate | OOS | +0.273 | +0.127 [+0.013, +0.240] | +0.146 | 0.005 | +93.2 | +43.4 [+4.4, +81.7] |
| P-gate | All | +0.120 | +0.185 [+0.122, +0.244] | -0.065 | 0.980 | +139.7 | +215.8 [+142.2, +285.0] |
| P-trend | IS | +0.056 | +0.165 [+0.094, +0.234] | -0.109 | 1.000 | +46.5 | +136.9 [+77.7, +193.7] |
| P-trend | OOS | +0.273 | +0.093 [-0.022, +0.193] | +0.181 | 0.005 | +93.2 | +31.6 [-7.6, +65.7] |
| P-trend | All | +0.120 | +0.144 [+0.092, +0.197] | -0.025 | 0.816 | +139.7 | +168.5 [+107.4, +230.1] |

Win rate, mean hold (bars) and total R per year (engine R):

| Null | Segment | Win rate actual | Win rate placebo | p | Hold actual | Hold placebo | p | Total R/yr actual | Total R/yr placebo | p |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P-gate | IS | 46.4% | 50.9% [48.2, 53.9] | 1.000 | 5.5 | 6.1 [5.9, 6.4] | 1.000 | +5.0 | +30.7 [+19.3, +42.7] | 1.000 |
| P-gate | OOS | 49.9% | 47.3% [42.2, 51.3] | 0.164 | 5.8 | 6.1 [5.7, 6.4] | 0.896 | +25.3 | +12.4 [+0.8, +24.8] | 0.020 |
| P-gate | All | 47.4% | 49.9% [47.2, 52.4] | 0.970 | 5.6 | 6.1 [5.9, 6.3] | 1.000 | +13.1 | +23.3 [+15.6, +30.5] | 0.985 |
| P-trend | IS | 46.4% | 49.5% [47.0, 52.3] | 0.995 | 5.5 | 6.1 [5.9, 6.4] | 1.000 | +5.0 | +25.6 [+14.1, +37.1] | 1.000 |
| P-trend | OOS | 49.9% | 46.0% [41.6, 50.5] | 0.070 | 5.8 | 6.0 [5.7, 6.3] | 0.866 | +25.3 | +8.7 [-1.7, +18.9] | 0.010 |
| P-trend | All | 47.4% | 48.5% [46.4, 50.7] | 0.836 | 5.6 | 6.1 [5.9, 6.3] | 1.000 | +13.1 | +18.8 [+11.2, +26.2] | 0.925 |

Total R by calendar year of the signal (engine R):

| Year | Actual trades | Actual total R | P-gate placebo total R | p | P-trend placebo total R | p |
|---|---:|---:|---:|---:|---:|---:|
| 2016 | 2 | -2.0 | +0.8 [-2.0, +4.5] | 0.836 | -2.0 [-2.0, -2.0] | 0.527 |
| 2017 | 217 | +24.5 | +59.7 [+30.5, +91.4] | 0.985 | +53.2 [+24.6, +81.9] | 0.975 |
| 2018 | 114 | +7.6 | +22.9 [+3.1, +43.5] | 0.915 | +23.0 [+1.0, +44.2] | 0.905 |
| 2019 | 181 | -24.7 | +32.4 [+8.9, +58.6] | 1.000 | +28.1 [-1.2, +53.7] | 1.000 |
| 2020 | 127 | +16.2 | +32.2 [+8.6, +63.4] | 0.915 | +26.7 [+1.9, +54.2] | 0.771 |
| 2021 | 185 | +2.5 | +12.3 [-19.8, +44.0] | 0.721 | +4.5 [-27.7, +34.9] | 0.507 |
| 2022 | 2 | +2.3 | +2.6 [+1.6, +4.1] | 0.652 | +2.7 [+1.6, +4.1] | 0.652 |
| 2023 | 137 | +25.5 | +19.6 [-7.2, +49.4] | 0.323 | +11.0 [-12.5, +39.1] | 0.159 |
| 2024 | 133 | +61.7 | +19.4 [-8.0, +46.3] | 0.005 | +12.5 [-8.6, +38.9] | 0.005 |
| 2025 | 71 | +3.2 | +5.1 [-13.0, +25.5] | 0.582 | +7.8 [-11.5, +26.4] | 0.692 |

### relative_strength.medium_swing — snapshot 3 (24 symbols); stop 2.5 × ATR14, target 5 × ATR14, time stop 40 bars

Engine R:

| Null | Segment | Actual trades | Placebo trades (mean) | Actual exp. R | Placebo exp. R | Timing alpha | p | Actual total R | Placebo total R | K |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P-gate | IS | 369 | 358.6 | +0.159 | +0.243 [+0.137, +0.343] | -0.084 | 0.930 | +58.6 | +87.0 [+49.3, +122.9] | 200 |
| P-gate | OOS | 197 | 196.2 | +0.300 | +0.361 [+0.220, +0.485] | -0.061 | 0.801 | +59.2 | +70.8 [+43.6, +96.3] | 200 |
| P-gate | All | 566 | 554.7 | +0.208 | +0.285 [+0.193, +0.362] | -0.077 | 0.945 | +117.8 | +157.9 [+107.6, +201.2] | 200 |
| P-trend | IS | 369 | 351.0 | +0.159 | +0.206 [+0.121, +0.298] | -0.047 | 0.841 | +58.6 | +72.3 [+42.5, +103.5] | 200 |
| P-trend | OOS | 197 | 190.5 | +0.300 | +0.334 [+0.200, +0.456] | -0.034 | 0.726 | +59.2 | +63.6 [+38.2, +87.6] | 200 |
| P-trend | All | 566 | 541.5 | +0.208 | +0.251 [+0.184, +0.321] | -0.043 | 0.836 | +117.8 | +136.0 [+100.1, +173.5] | 200 |

Stable R:

| Null | Segment | Actual exp. stable R | Placebo exp. stable R | Timing alpha | p | Actual total stable R | Placebo total stable R |
|---|---|---:|---:|---:|---:|---:|---:|
| P-gate | IS | +0.154 | +0.252 [+0.150, +0.342] | -0.098 | 0.965 | +56.9 | +90.3 [+54.4, +121.4] |
| P-gate | OOS | +0.291 | +0.359 [+0.223, +0.484] | -0.068 | 0.826 | +57.4 | +70.3 [+43.8, +95.6] |
| P-gate | All | +0.202 | +0.290 [+0.215, +0.365] | -0.088 | 0.985 | +114.3 | +160.7 [+119.8, +202.1] |
| P-trend | IS | +0.154 | +0.207 [+0.127, +0.290] | -0.053 | 0.861 | +56.9 | +72.8 [+44.8, +101.7] |
| P-trend | OOS | +0.291 | +0.336 [+0.212, +0.465] | -0.045 | 0.771 | +57.4 | +64.0 [+40.6, +88.4] |
| P-trend | All | +0.202 | +0.253 [+0.179, +0.310] | -0.051 | 0.905 | +114.3 | +136.8 [+97.2, +167.9] |

Win rate, mean hold (bars) and total R per year (engine R):

| Null | Segment | Win rate actual | Win rate placebo | p | Hold actual | Hold placebo | p | Total R/yr actual | Total R/yr placebo | p |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P-gate | IS | 44.4% | 47.8% [43.8, 51.3] | 0.950 | 20.0 | 18.9 [17.9, 20.0] | 0.025 | +11.0 | +16.4 [+9.3, +23.1] | 0.920 |
| P-gate | OOS | 48.7% | 51.6% [46.9, 56.2] | 0.836 | 19.4 | 19.6 [18.2, 21.4] | 0.517 | +16.6 | +19.9 [+12.2, +27.0] | 0.796 |
| P-gate | All | 45.9% | 49.1% [45.9, 52.1] | 0.980 | 19.8 | 19.2 [18.2, 20.1] | 0.104 | +13.3 | +17.8 [+12.1, +22.6] | 0.945 |
| P-trend | IS | 44.4% | 46.2% [42.9, 49.4] | 0.826 | 20.0 | 18.6 [17.7, 19.6] | 0.005 | +11.0 | +13.6 [+8.0, +19.5] | 0.816 |
| P-trend | OOS | 48.7% | 50.5% [45.7, 55.5] | 0.776 | 19.4 | 18.7 [17.5, 20.2] | 0.189 | +16.6 | +17.8 [+10.7, +24.6] | 0.632 |
| P-trend | All | 45.9% | 47.7% [44.9, 50.4] | 0.891 | 19.8 | 18.6 [17.7, 19.5] | 0.010 | +13.3 | +15.3 [+11.3, +19.5] | 0.771 |

Total R by calendar year of the signal (engine R):

| Year | Actual trades | Actual total R | P-gate placebo total R | p | P-trend placebo total R | p |
|---|---:|---:|---:|---:|---:|---:|
| 2016 | 0 | +0.0 | no draws | n/a | no draws | n/a |
| 2017 | 29 | +23.6 | +22.2 [+9.6, +33.9] | 0.433 | +16.6 [+6.3, +24.7] | 0.075 |
| 2018 | 86 | -4.9 | -3.1 [-18.8, +13.2] | 0.597 | -3.4 [-15.8, +9.6] | 0.587 |
| 2019 | 55 | +14.6 | +26.0 [+11.0, +41.3] | 0.920 | +21.7 [+8.9, +34.3] | 0.861 |
| 2020 | 92 | -0.0 | +12.5 [-6.3, +33.2] | 0.891 | +20.6 [+3.7, +42.0] | 0.985 |
| 2021 | 94 | +29.1 | +29.9 [+11.1, +51.0] | 0.517 | +18.6 [+1.5, +37.0] | 0.114 |
| 2022 | 18 | +0.9 | +1.0 [-5.1, +8.6] | 0.498 | +0.5 [-6.2, +6.1] | 0.453 |
| 2023 | 73 | +33.4 | +44.3 [+29.8, +58.2] | 0.915 | +36.4 [+21.4, +49.5] | 0.711 |
| 2024 | 86 | +25.3 | +31.8 [+12.7, +49.2] | 0.721 | +26.2 [+8.3, +43.3] | 0.552 |
| 2025 | 33 | -4.1 | -6.8 [-19.5, +6.6] | 0.318 | -1.4 [-11.3, +7.9] | 0.746 |

### trend_continuation.medium_swing — snapshot 11 (150 symbols); stop 1.5 × ATR14, target 3 × ATR14, time stop 40 bars

Engine R:

| Null | Segment | Actual trades | Placebo trades (mean) | Actual exp. R | Placebo exp. R | Timing alpha | p | Actual total R | Placebo total R | K |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P-gate | IS | 4,169 | 4,165.9 | +0.158 | +0.287 [+0.250, +0.330] | -0.130 | 1.000 | +656.9 | +1196.7 [+1040.0, +1374.1] | 200 |
| P-gate | OOS | 1,986 | 1,985.5 | +0.221 | +0.188 [+0.128, +0.242] | +0.033 | 0.144 | +438.7 | +373.5 [+253.1, +481.3] | 200 |
| P-gate | All | 6,155 | 6,151.4 | +0.178 | +0.255 [+0.223, +0.291] | -0.077 | 1.000 | +1095.6 | +1570.3 [+1374.3, +1787.4] | 200 |
| P-trend | IS | 4,169 | 4,159.5 | +0.158 | +0.221 [+0.187, +0.253] | -0.064 | 1.000 | +656.9 | +921.3 [+776.3, +1054.4] | 200 |
| P-trend | OOS | 1,986 | 1,984.3 | +0.221 | +0.149 [+0.094, +0.201] | +0.071 | 0.010 | +438.7 | +296.6 [+186.5, +399.1] | 200 |
| P-trend | All | 6,155 | 6,143.8 | +0.178 | +0.198 [+0.173, +0.220] | -0.020 | 0.945 | +1095.6 | +1218.0 [+1062.0, +1350.1] | 200 |

Stable R:

| Null | Segment | Actual exp. stable R | Placebo exp. stable R | Timing alpha | p | Actual total stable R | Placebo total stable R |
|---|---|---:|---:|---:|---:|---:|---:|
| P-gate | IS | +0.157 | +0.297 [+0.263, +0.333] | -0.140 | 1.000 | +656.0 | +1237.9 [+1096.1, +1387.2] |
| P-gate | OOS | +0.204 | +0.183 [+0.125, +0.241] | +0.020 | 0.239 | +404.4 | +364.0 [+249.1, +479.1] |
| P-gate | All | +0.172 | +0.260 [+0.231, +0.292] | -0.088 | 1.000 | +1060.5 | +1601.9 [+1423.2, +1794.8] |
| P-trend | IS | +0.157 | +0.232 [+0.200, +0.263] | -0.074 | 1.000 | +656.0 | +964.4 [+830.7, +1092.2] |
| P-trend | OOS | +0.204 | +0.146 [+0.089, +0.197] | +0.057 | 0.020 | +404.4 | +290.3 [+177.4, +390.7] |
| P-trend | All | +0.172 | +0.204 [+0.179, +0.227] | -0.032 | 0.990 | +1060.5 | +1254.7 [+1100.4, +1395.2] |

Win rate, mean hold (bars) and total R per year (engine R):

| Null | Segment | Win rate actual | Win rate placebo | p | Hold actual | Hold placebo | p | Total R/yr actual | Total R/yr placebo | p |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P-gate | IS | 42.8% | 46.1% [45.1, 47.2] | 1.000 | 8.6 | 9.7 [9.5, 10.0] | 1.000 | +123.6 | +225.1 [+195.6, +258.4] | 1.000 |
| P-gate | OOS | 43.4% | 42.3% [40.4, 43.9] | 0.095 | 8.0 | 8.8 [8.4, 9.1] | 1.000 | +123.0 | +104.7 [+71.0, +134.9] | 0.144 |
| P-gate | All | 43.0% | 44.9% [43.9, 45.9] | 1.000 | 8.4 | 9.4 [9.2, 9.6] | 1.000 | +123.3 | +176.7 [+154.7, +201.2] | 1.000 |
| P-trend | IS | 42.8% | 43.9% [42.9, 45.0] | 0.975 | 8.6 | 9.4 [9.2, 9.6] | 1.000 | +123.6 | +173.3 [+146.0, +198.3] | 1.000 |
| P-trend | OOS | 43.4% | 40.8% [39.1, 42.4] | 0.005 | 8.0 | 8.3 [8.0, 8.6] | 1.000 | +123.0 | +83.2 [+52.3, +111.9] | 0.010 |
| P-trend | All | 43.0% | 42.9% [42.2, 43.7] | 0.403 | 8.4 | 9.1 [8.9, 9.2] | 1.000 | +123.3 | +137.1 [+119.5, +152.0] | 0.935 |

Total R by calendar year of the signal (engine R):

| Year | Actual trades | Actual total R | P-gate placebo total R | p | P-trend placebo total R | p |
|---|---:|---:|---:|---:|---:|---:|
| 2016 | 4 | -4.0 | +3.2 [-1.5, +7.7] | 0.995 | -2.8 [-4.1, -1.4] | 0.667 |
| 2017 | 1,127 | +325.3 | +543.7 [+458.8, +642.0] | 1.000 | +476.9 [+399.7, +540.2] | 1.000 |
| 2018 | 538 | +34.6 | +100.5 [+54.4, +154.5] | 1.000 | +69.1 [+25.1, +114.5] | 0.920 |
| 2019 | 911 | +70.4 | +219.1 [+147.6, +312.4] | 1.000 | +167.9 [+85.6, +245.9] | 0.985 |
| 2020 | 643 | +186.4 | +237.9 [+173.3, +309.4] | 0.930 | +197.7 [+135.5, +260.0] | 0.642 |
| 2021 | 928 | +67.5 | +95.7 [+23.8, +174.4] | 0.786 | +37.2 [-17.7, +108.9] | 0.169 |
| 2022 | 18 | -23.2 | -3.4 [-28.1, +11.3] | 0.786 | -24.7 [-29.0, -20.6] | 0.279 |
| 2023 | 832 | +132.1 | +166.5 [+96.4, +238.0] | 0.806 | +119.2 [+44.0, +189.3] | 0.333 |
| 2024 | 759 | +179.0 | +154.8 [+75.3, +224.8] | 0.299 | +121.9 [+57.4, +186.0] | 0.055 |
| 2025 | 395 | +127.6 | +52.2 [+7.8, +97.6] | 0.005 | +55.5 [+5.3, +108.9] | 0.005 |

### high52_breakout.medium_swing — snapshot 11 (150 symbols); stop 2 × ATR14, target 4 × ATR14, time stop 40 bars

Engine R:

| Null | Segment | Actual trades | Placebo trades (mean) | Actual exp. R | Placebo exp. R | Timing alpha | p | Actual total R | Placebo total R | K |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P-gate | IS | 972 | 971.9 | +0.088 | +0.374 [+0.306, +0.459] | -0.286 | 1.000 | +85.7 | +363.2 [+297.3, +445.8] | 200 |
| P-gate | OOS | 525 | 525.0 | +0.227 | +0.349 [+0.239, +0.482] | -0.121 | 0.985 | +119.4 | +183.1 [+125.3, +253.0] | 200 |
| P-gate | All | 1,497 | 1,496.9 | +0.137 | +0.365 [+0.298, +0.436] | -0.228 | 1.000 | +205.1 | +546.3 [+445.5, +652.2] | 200 |
| P-trend | IS | 972 | 971.9 | +0.088 | +0.320 [+0.242, +0.399] | -0.232 | 1.000 | +85.7 | +310.7 [+234.8, +387.7] | 200 |
| P-trend | OOS | 525 | 525.0 | +0.227 | +0.316 [+0.198, +0.421] | -0.088 | 0.935 | +119.4 | +165.7 [+103.9, +220.9] | 200 |
| P-trend | All | 1,497 | 1,496.8 | +0.137 | +0.318 [+0.251, +0.384] | -0.181 | 1.000 | +205.1 | +476.4 [+376.2, +575.3] | 200 |

Stable R:

| Null | Segment | Actual exp. stable R | Placebo exp. stable R | Timing alpha | p | Actual total stable R | Placebo total stable R |
|---|---|---:|---:|---:|---:|---:|---:|
| P-gate | IS | +0.104 | +0.378 [+0.308, +0.463] | -0.274 | 1.000 | +101.6 | +367.6 [+299.7, +449.6] |
| P-gate | OOS | +0.257 | +0.348 [+0.244, +0.480] | -0.091 | 0.965 | +134.9 | +182.9 [+128.3, +251.9] |
| P-gate | All | +0.158 | +0.368 [+0.304, +0.436] | -0.210 | 1.000 | +236.5 | +550.5 [+454.9, +652.3] |
| P-trend | IS | +0.104 | +0.323 [+0.236, +0.400] | -0.219 | 1.000 | +101.6 | +314.1 [+229.5, +388.4] |
| P-trend | OOS | +0.257 | +0.312 [+0.206, +0.411] | -0.055 | 0.886 | +134.9 | +163.9 [+108.0, +215.7] |
| P-trend | All | +0.158 | +0.319 [+0.255, +0.383] | -0.161 | 1.000 | +236.5 | +478.0 [+381.9, +573.4] |

Win rate, mean hold (bars) and total R per year (engine R):

| Null | Segment | Win rate actual | Win rate placebo | p | Hold actual | Hold placebo | p | Total R/yr actual | Total R/yr placebo | p |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P-gate | IS | 39.9% | 49.4% [47.0, 52.3] | 1.000 | 12.8 | 14.7 [14.1, 15.4] | 1.000 | +16.1 | +68.3 [+55.9, +83.9] | 1.000 |
| P-gate | OOS | 44.2% | 48.4% [45.1, 52.6] | 0.995 | 12.9 | 13.9 [13.0, 14.7] | 0.990 | +33.5 | +51.3 [+35.1, +70.9] | 0.985 |
| P-gate | All | 41.4% | 49.0% [47.0, 51.2] | 1.000 | 12.8 | 14.4 [13.9, 14.9] | 1.000 | +23.1 | +61.5 [+50.1, +73.4] | 1.000 |
| P-trend | IS | 39.9% | 47.4% [44.6, 50.0] | 1.000 | 12.8 | 14.1 [13.5, 14.8] | 1.000 | +16.1 | +58.4 [+44.2, +72.9] | 1.000 |
| P-trend | OOS | 44.2% | 46.8% [42.9, 50.1] | 0.925 | 12.9 | 13.5 [12.6, 14.5] | 0.900 | +33.5 | +46.4 [+29.1, +61.9] | 0.935 |
| P-trend | All | 41.4% | 47.2% [45.1, 49.3] | 1.000 | 12.8 | 13.9 [13.5, 14.4] | 1.000 | +23.1 | +53.6 [+42.3, +64.8] | 1.000 |

Total R by calendar year of the signal (engine R):

| Year | Actual trades | Actual total R | P-gate placebo total R | p | P-trend placebo total R | p |
|---|---:|---:|---:|---:|---:|---:|
| 2016 | 0 | +0.0 | no draws | n/a | no draws | n/a |
| 2017 | 116 | +65.3 | +78.5 [+50.2, +106.1] | 0.846 | +69.5 [+40.9, +104.7] | 0.617 |
| 2018 | 168 | -32.4 | +37.1 [+4.5, +65.8] | 1.000 | +31.6 [-1.5, +66.5] | 1.000 |
| 2019 | 171 | +26.8 | +71.1 [+40.6, +112.2] | 0.995 | +63.1 [+21.7, +107.6] | 0.960 |
| 2020 | 215 | +17.0 | +110.6 [+73.6, +146.6] | 1.000 | +104.1 [+63.1, +148.0] | 1.000 |
| 2021 | 299 | +3.7 | +62.6 [+14.8, +113.3] | 1.000 | +39.3 [-3.1, +77.3] | 0.950 |
| 2022 | 3 | +5.3 | +3.4 [-0.9, +6.0] | 0.239 | +3.1 [-0.9, +5.8] | 0.139 |
| 2023 | 199 | +48.4 | +80.1 [+44.3, +116.1] | 0.920 | +66.7 [+22.4, +102.3] | 0.826 |
| 2024 | 246 | +63.3 | +78.8 [+35.7, +123.9] | 0.766 | +70.7 [+26.1, +111.5] | 0.647 |
| 2025 | 80 | +7.6 | +24.2 [+1.5, +46.2] | 0.915 | +28.2 [+9.4, +50.8] | 0.980 |

## Shortfall from dropped draws

Target = the real rule's trade count (draws per run). A draw that still fell inside an open placebo trade after 20 redraws was dropped; under P-trend a symbol-year with no bar above SMA50 on a gate-allowed day cannot be drawn at all.

| Version | Null | K | Target per run | Placed (mean / min) | Dropped after 20 redraws (mean / max) | No eligible bar (mean) | Shortfall % (mean / max) | Redraws per run (mean) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| trend_continuation.short_swing | P-gate | 200 | 1,169 | 1,169.0 / 1,168 | 0.02 / 1 | 0.00 | 0.00% / 0.09% | 612 |
| trend_continuation.short_swing | P-trend | 200 | 1,169 | 1,168.9 / 1,168 | 0.09 / 1 | 0.00 | 0.01% / 0.09% | 799 |
| relative_strength.medium_swing | P-gate | 200 | 566 | 554.7 / 545 | 11.29 / 21 | 0.00 | 1.99% / 3.71% | 1,486 |
| relative_strength.medium_swing | P-trend | 200 | 566 | 541.5 / 533 | 24.52 / 33 | 0.00 | 4.33% / 5.83% | 2,102 |
| trend_continuation.medium_swing | P-gate | 200 | 6,155 | 6,151.4 / 6,147 | 3.60 / 8 | 0.00 | 0.06% / 0.13% | 4,617 |
| trend_continuation.medium_swing | P-trend | 200 | 6,155 | 6,143.8 / 6,134 | 11.15 / 21 | 0.00 | 0.18% / 0.34% | 6,934 |
| high52_breakout.medium_swing | P-gate | 200 | 1,497 | 1,496.9 / 1,495 | 0.12 / 2 | 0.00 | 0.01% / 0.13% | 338 |
| high52_breakout.medium_swing | P-trend | 200 | 1,497 | 1,496.8 / 1,495 | 0.17 / 2 | 0.00 | 0.01% / 0.13% | 422 |

Eligible bars (all symbols, whole window) and the share of the real rule's signal bars that are themselves P-trend-eligible:

| Version | Bars loaded | P-gate eligible | P-trend eligible | Real signal bars with close > SMA50 |
|---|---:|---:|---:|---:|
| trend_continuation.short_swing | 53,196 | 31,068 | 23,493 | 100.0% |
| relative_strength.medium_swing | 53,196 | 36,277 | 24,701 | 87.1% |
| trend_continuation.medium_swing | 334,197 | 195,251 | 131,428 | 100.0% |
| high52_breakout.medium_swing | 334,197 | 195,251 | 131,428 | 100.0% |

## Identity and construction checks

The identity check, the replay of the real dates and the redraw-rule comparison run before any placebo run and stop the study on a mismatch; the whole-run comparison is made after the runs.

| Version | Snapshot | Recorded OOS (trades / exp. R) | Reproduced OOS (trades / exp. R) | Match | Placebo function on the real dates: trades reproduced | Stop/target/time-stop mismatches |
|---|---:|---:|---:|:---:|---:|---:|
| trend_continuation.short_swing | 3 | 341 / +0.2648 | 341 / +0.2648 | yes | 1,169 of 1,169 | 0 |
| relative_strength.medium_swing | 3 | 197 / +0.3004 | 197 / +0.3004 | yes | 566 of 566 | 0 |
| trend_continuation.medium_swing | 11 | 1,986 / +0.2209 | 1,986 / +0.2209 | yes | 6,155 of 6,155 | 0 |
| high52_breakout.medium_swing | 11 | 525 / +0.2274 | 525 / +0.2274 | yes | 1,497 of 1,497 | 0 |

The last two columns feed the placebo signal function the real rule's own signal dates: it must return the same stop, target and time stop, and the library engine must then produce the same trades (dates, fills and R, compared exactly). One-symbol examples:

| Version | Symbol | Signals compared | Equal | First signal date | Real stop / target | Placebo stop / target |
|---|---|---:|---:|---|---:|---:|
| trend_continuation.short_swing | AAPL | 52 | 52 | 2017-01-17 | 29.4916 / 31.0168 | 29.4916 / 31.0168 |
| relative_strength.medium_swing | AAPL | 49 | 49 | 2017-08-29 | 38.9905 / 44.2014 | 38.9905 / 44.2014 |
| trend_continuation.medium_swing | AAL | 27 | 27 | 2017-01-10 | 46.8209 / 51.7982 | 46.8209 / 51.7982 |
| high52_breakout.medium_swing | AAL | 3 | 3 | 2018-01-11 | 54.0116 / 61.2368 | 54.0116 / 61.2368 |

Window: the bars loaded run from 2016-10-17 to 2025-09-05. Bars are requested up to 2025-09-05 only, and the loader stops if a later bar ever appears.

Redraw rule: the date planner was compared with a slow twin that finds blocked draws by running the library engine itself and seeing which dates it never evaluated, on the five busiest symbols of each version under both nulls. 40 of 40 cases gave identical dates, drops and redraw counts (3,701 redraws exercised).

Whole runs: runs 0 and 137 of every version and null were redone from the seed with that slow twin as the planner, so the library engine alone decided which draws were blocked. 16 of 16 reproduced the study's run-level rows exactly.

In every placebo run the planned entry and exit dates and the library engine's trades were compared symbol by symbol; a disagreement would have stopped the run. None occurred.

## Stated expectations against the outcome

- "Placebo expectancy will be clearly positive on both universes": the P-gate 2.5th percentile is above zero on both IS and OOS for all four versions.
- trend_continuation.short_swing: P-gate timing alpha -0.165R IS (p 1.000), +0.135R OOS (p 0.020).
- relative_strength.medium_swing: P-gate timing alpha -0.084R IS (p 0.930), -0.061R OOS (p 0.801).
- trend_continuation.medium_swing: P-gate timing alpha -0.130R IS (p 1.000), +0.033R OOS (p 0.144).
- high52_breakout.medium_swing: P-gate timing alpha -0.286R IS (p 1.000), -0.121R OOS (p 0.985).
- Expected in advance: positive but small alpha for the two trend_continuation versions and high52, uncertain for relative_strength; a null for one or more versions was called a likely outcome.
- Outcome for the three versions with a stated sign: alpha positive on both IS and OOS for none; positive OOS but negative IS for trend_continuation.short_swing and trend_continuation.medium_swing; negative OOS for high52_breakout.medium_swing. The expectation of a positive alpha did not hold on IS for any of them.

## Deviations and clarifications

1. No deviation from the pre-registered design. Items 2 to 10 are choices the pre-registration left open. The later items record what an adversarial review of the first write-up led to: wording, descriptive splits of the same runs, a re-run from the same seeds and, where shown, one post hoc check. None changes a pre-registered number or a reading. Nothing in the placebo construction changed after the first placebo run: a smoke test of runs 0–5 made before the first full run matches that run's rows exactly. The calendar-year tables were added to the write-up after the runs; every run had recorded its per-year totals from the start.
2. **Symbol-year of a trade.** A real trade is counted in the calendar year of its signal bar (the session before the fill), because the placebo draws signal dates.
3. **Eligible bars.** P-gate: bars where the version's own regime gate allows an entry (`not risk_off` for trend_continuation and high52_breakout; trend BULL for relative_strength), limited to bars the engine can act on (bar index ≥ 30, the runner's warm-up; not the last bar) with ATR14 defined. The rule's own indicator warm-up (SMA50/SMA100, 252-bar high) is not imposed, as the pre-registration says "that symbol-year's bars on which the regime gate allows an entry". P-trend adds close > SMA50 (library `sma`).
4. **Redraw rule.** Each draw is an independent uniform draw from its symbol-year's eligible bars. Draws are played in date order as the engine does: a draw on a bar the engine does not evaluate because an earlier placebo trade is open — from that trade's signal bar through its exit bar, which includes a second draw on the same bar — is redrawn uniformly from the same symbol-year, up to 20 times, then dropped. A new earlier trade can displace a later one, which is then the one redrawn. No draw is ever rejected because of its own outcome.
5. **No look-ahead in the signal.** Dates are drawn in advance; the signal function receives the engine's `series.head(t)` and builds stop, target and time stop from ATR14 at the drawn bar. The date planner uses the library's exit resolution only to know when an earlier placebo trade is still open; every reported trade comes from `run_backtest`.
6. **Seeds.** Run r (0-based) of every version and null uses `numpy.random.default_rng(20261110 + r)`; symbols are processed alphabetically, years ascending.
7. **Stable R** is computed inside this script as engine R × |entry fill − stop| / (close_t − stop_t), which equals (exit − entry) / (close_t − stop_t) on unrounded fills. The R3-E script is not used.
8. **Holm.** Applied to the four P-gate OOS expectancy p-values (engine R; shown for stable R too). The per-version reading uses the Holm-adjusted p for the P-gate OOS leg and raw p elsewhere.
9. **Total R per year** is shown both ways the phrase can be read: the segment's total R divided by its length in years (IS 5.32, OOS 3.57, whole window 8.88; full-history IS/OOS boundary 2022-02-10), and total R by calendar year of the signal.
10. **p for win rate, hold and total R per year** is the same one-sided share of placebo runs at or above the actual value.
11. **Wording of the reading.** The pre-registered rule is applied as written and its yes/no outcome is unchanged. The pre-registration's sentence calls the P-gate placebo "gated exposure" and names a looser trigger as a candidate to pre-register next. Because the P-gate placebo, as pre-registered, also matches the rule's realised trade count in every symbol-year, this file quotes those words as the pre-registration's and does not repeat them as findings.
12. **Descriptive additions, not pre-registered and used in no reading.** Two splits of the pre-registered runs and of the real trades are quoted under Limits: trades whose entry fill is at or below the stop (run-level columns `*_gap_n` and `*_gap_total_r`), and how the real signals bunch in time (signal dates, a week-clustered standard error). They add no run and change no pre-registered number.
13. **Runs redone after the review.** The first results file had been rebuilt by a script that was edited after the placebo runs had finished. Every run row now carries a fingerprint of the script, the library modules it calls, the bars and the real rule's trade counts, and rows with another fingerprint are refused; `--out` has no default. All runs of every cell were redone from the same seeds with the script as committed (SHA-256 `90a0612545ec…`). Every earlier run row was reproduced exactly on all the columns it shares with the new rows: 1,600 of 1,600 rows of the first full run (49 columns); 48 of 48 rows of the smoke run made before it (49 columns).
14. **Post hoc check — not pre-registered, asked for by the adversarial review, used in no reading.** How much does the P-gate placebo gain from being told the symbol-years? The placebo signal function was offered every bar instead of drawn bars, so it enters whenever the version's regime gate allows and the symbol is flat ("always in when the gate allows"): same ATR14 stop, target and time stop, same library engine, one position per symbol, no random number and no parameter. It differs from the placebo in a second way, trading back to back instead of on a matched number of random dates, so the ratios are a rough size and not a decomposition. The table below this list sets it beside the real rule and the P-gate placebo mean. OOS the placebo mean is 1.4 to 2.4 times the always-in figure (IS: 1.0 to 2.8 times), and the always-in figure is 33% to 85% of the real rule's OOS expectancy. The real rule is above the always-in figure OOS for 4 of 4 versions and below it IS for 3 of 4. This is one fixed path per version with no error band and no test: the OOS gaps between the real rules and the always-in figure are 0.4 to 1.6 times the real rule's own week-clustered standard error (Limits), so it is not evidence that the triggers add value. It shows only that the P-gate placebo is not plain gated exposure.

Post hoc check (not pre-registered, no reading): always in when the gate allows, engine R per trade, beside the pre-registered figures.

| Version | Segment | Real rule exp. R | P-gate placebo mean | Always in when the gate allows: exp. R (trades) | Placebo mean ÷ always-in | Real rule − always-in |
|---|---|---:|---:|---:|---:|---:|
| trend_continuation.short_swing | IS | +0.032 | +0.197 | +0.189 (2,578) | 1.04 | -0.157 |
| trend_continuation.short_swing | OOS | +0.265 | +0.130 | +0.089 (1,505) | 1.46 | +0.176 |
| relative_strength.medium_swing | IS | +0.159 | +0.243 | +0.087 (1,097) | 2.81 | +0.072 |
| relative_strength.medium_swing | OOS | +0.300 | +0.361 | +0.255 (660) | 1.42 | +0.046 |
| trend_continuation.medium_swing | IS | +0.158 | +0.287 | +0.217 (11,441) | 1.32 | -0.059 |
| trend_continuation.medium_swing | OOS | +0.221 | +0.188 | +0.112 (6,991) | 1.69 | +0.109 |
| high52_breakout.medium_swing | IS | +0.088 | +0.374 | +0.276 (7,911) | 1.35 | -0.188 |
| high52_breakout.medium_swing | OOS | +0.227 | +0.349 | +0.146 (4,758) | 2.40 | +0.082 |

## Limits

- The placebo inherits the same survivorship and the same regime gate as the rule; it measures the trigger's value only, and only as a choice of days inside the symbol-years the rule traded (next point).
- Matching trade counts per symbol-year tells the placebo which symbol-years the rule ended up trading, and how often. Each rule fires after strength (price above its averages, 63-day outperformance, a new 52-week high), so a symbol-year in which it fired often is likely one that turned out strong, and a random date in the same symbol-year can fall before the rise the rule waited for. That favours the placebo. The pre-registered design does not measure by how much; the post hoc check under "Deviations and clarifications" gives a rough size: OOS the placebo mean is 1.4 to 2.4 times what always being in when the gate allows earned. A negative timing alpha therefore says the trigger did not pick better days than chance *inside the symbol-years it traded*; it does not test the trigger's choice of symbol-years, and it does not mean the rule earns less than plain gated exposure.
- The p-values compare each rule with random dates, which are spread across the calendar, while the real rules' trades bunch on common market days: trend_continuation.medium_swing's 4,169 IS trades fall on 738 signal dates, and the ten busiest dates hold 9% to 18% of a segment's trades. A no-skill rule that bunched the same way would stray further from the placebo mean than the placebo runs do, in both directions. As a yardstick (not a test), the spread of the P-gate runs (SD 0.021R to 0.072R) is 1.5 to 2.4 times smaller than the standard error of the real rule's own expectancy when trades signalled in the same week count as one cluster (0.049R to 0.130R). So the p-values overstate the evidence both ways: for the 3 versions whose IS expectancy is below every placebo run (p 1.000), the IS timing alpha is -4.2 to -7.1 placebo SDs but -2.4 to -3.7 of those standard errors; trend_continuation.short_swing's OOS +0.135R is +2.1 placebo SDs but +1.1 standard errors. No reading changes. The first table after this list has every cell.
- With K = 200 the Holm-adjusted P-gate OOS leg has little resolution: the best of the 4 versions passes it only if at most 1 of its 200 placebo runs is at or above the rule (4 × 2/201 = 0.040; 4 × 3/201 = 0.060). trend_continuation.short_swing has 3 of 200 runs at or above it in engine R (Holm 0.080) and 0 of 200 in stable R (Holm 0.020), so that leg turns on a handful of runs. Its IS leg (p 1.000) settles the reading either way.
- Engine R books an entry that fills at or below its stop as closed on the entry bar at the stop price. Of the 154 such real trades across the four versions, 148 are booked as gains (median +0.97R); the few whose fill is only just below the stop are booked as losses, down to -30.4R. The R3-E study of this round takes no trade when the entry bar opens at or below the stop (its corrected baseline, pre-registered as a measurement correction). The real rules have such fills more often than the placebo in 6 of the 8 P-gate IS and OOS cells, which moves timing alpha in engine R. The largest effect is in trend_continuation.medium_swing OOS: 57 of 1,986 real trades (2.87%) are such fills and add +0.0274R to expectancy, against 0.55% and +0.0045R in the placebo, so +0.0229R of the +0.0328R timing alpha comes from these fills and +0.0098R from all other trades (counted by the raw open rather than the fill, as R3-E counts them, the same segment has 58). In the other 7 cells they move timing alpha by -0.0112R to +0.0068R (second table after this list). The stable-R tables, which divide by the risk planned at the signal, show part of the same effect. The engine was pre-registered as unchanged, so no pre-registered table is adjusted.
- P-gate draws from every gate-allowed bar of a symbol-year, including bars before a rule's own indicators could have fired (the 252-bar high cannot fire before October 2017). For high52_breakout the 2017 gap between actual and P-gate placebo total R is -13.2R, against -277.5R for the whole IS segment, so the IS result does not rest on that year.
- A draw is dropped only after 21 consecutive draws landed inside open placebo trades. The shortfall is largest for relative_strength.medium_swing (1.99% of draws under P-gate, 4.33% under P-trend) and below 0.2% elsewhere. Twenty-one misses in a row need a symbol-year already crowded with open placebo trades, so the dropped draws thin out the busiest symbol-years.
- The calendar-year p-values are dozens of separate comparisons with no multiplicity adjustment; they are shown to locate the gaps in time, not as tests.
- It says nothing about a different universe or about the sealed year.

Time-clustering of the real signals against the spread of the P-gate runs (descriptive, not pre-registered, no reading; engine R). The clustered standard error treats trades signalled in the same ISO week as one cluster.

| Version | Segment | Real trades | Signal dates | Ten busiest dates | P-gate placebo SD | Real rule SE, week-clustered | Timing alpha | in placebo SDs | in clustered SEs |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| trend_continuation.short_swing | IS | 828 | 398 | 9.4% | 0.0394 | 0.0683 | -0.1649 | -4.2 | -2.4 |
| trend_continuation.short_swing | OOS | 341 | 189 | 17.6% | 0.0629 | 0.1189 | +0.1353 | +2.1 | +1.1 |
| relative_strength.medium_swing | IS | 369 | 263 | 13.0% | 0.0531 | 0.1029 | -0.0840 | -1.6 | -0.8 |
| relative_strength.medium_swing | OOS | 197 | 155 | 17.8% | 0.0723 | 0.1300 | -0.0608 | -0.8 | -0.5 |
| trend_continuation.medium_swing | IS | 4,169 | 738 | 8.8% | 0.0205 | 0.0494 | -0.1297 | -6.3 | -2.6 |
| trend_continuation.medium_swing | OOS | 1,986 | 413 | 16.2% | 0.0303 | 0.0686 | +0.0328 | +1.1 | +0.5 |
| high52_breakout.medium_swing | IS | 972 | 386 | 12.8% | 0.0402 | 0.0781 | -0.2856 | -7.1 | -3.7 |
| high52_breakout.medium_swing | OOS | 525 | 254 | 16.0% | 0.0606 | 0.0928 | -0.1214 | -2.0 | -1.3 |

Entry fills at or below the stop, real rule against the P-gate placebo (descriptive, not pre-registered, no reading; engine R). The last two columns split the timing alpha.

| Version | Segment | Real: such fills | Real: R they add to expectancy | Placebo: such fills (mean) | Placebo: R they add (mean) | Timing alpha | from these fills | from all other trades |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| trend_continuation.short_swing | IS | 18 of 828 (2.17%) | -0.0090 | 0.64% | +0.0023 | -0.1649 | -0.0112 | -0.1537 |
| trend_continuation.short_swing | OOS | 3 of 341 (0.88%) | +0.0086 | 0.38% | +0.0019 | +0.1353 | +0.0068 | +0.1285 |
| relative_strength.medium_swing | IS | 0 of 369 (0.00%) | +0.0000 | 0.10% | +0.0008 | -0.0840 | -0.0008 | -0.0832 |
| relative_strength.medium_swing | OOS | 0 of 197 (0.00%) | +0.0000 | 0.15% | +0.0013 | -0.0608 | -0.0013 | -0.0595 |
| trend_continuation.medium_swing | IS | 69 of 4,169 (1.66%) | +0.0048 | 0.57% | +0.0017 | -0.1297 | +0.0032 | -0.1328 |
| trend_continuation.medium_swing | OOS | 57 of 1,986 (2.87%) | +0.0274 | 0.55% | +0.0045 | +0.0328 | +0.0229 | +0.0098 |
| high52_breakout.medium_swing | IS | 3 of 972 (0.31%) | +0.0030 | 0.23% | +0.0015 | -0.2856 | +0.0015 | -0.2871 |
| high52_breakout.medium_swing | OOS | 4 of 525 (0.76%) | +0.0075 | 0.28% | +0.0016 | -0.1214 | +0.0059 | -0.1273 |

Raw outputs (not committed): one run-level CSV per version and null (`placebo__<version>__<null>.csv`), `actual_trades__<version>.csv`, `identity.json` and `summary.json` under the round's scratch output directory `r3/out/placebo/`. To reproduce, run `scripts/r3/placebo_timing.py --k 200 --out <an empty directory>` with `DATABASE_URL` set to a read-only (`mode=ro`) copy of the database. Each run row carries a fingerprint of the script (SHA-256 `90a0612545ec…`), the library modules it calls, the bars and the real rule's trade counts; finished runs in the output directory are reused only if that fingerprint matches, and are refused otherwise. The 1,600 placebo runs here took 779 worker-seconds on 4 processes.

Research signal only — no order was placed.
