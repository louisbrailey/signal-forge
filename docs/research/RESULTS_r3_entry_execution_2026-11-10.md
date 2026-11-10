# Results — R3-E: entry execution and the risk unit (engine item H14)

Pre-registration: `docs/research/PREREGISTRATION_r3_entry_execution_2026-11-10.md` (commit 9bc9d24), followed as written. Script: `scripts/r3/entry_execution.py`. Run 2026-11-10 on a read-only scratch copy of the database. Development window only: `massive` daily bars 2016-10-17 to 2025-09-05; no later bar was loaded. No sealed look was taken and nothing was written to any database. Revised the same day after adversarial review: no pre-registered number changed; sections 2 and 5 gained the checks that show how little the one pass can carry (clarification 14).

**Answer.** Three of the four approved versions show no upgrade; the fourth meets the pre-registered rule as written, but that pass does not hold up and is best read as not confirmed. On `trend_continuation.medium_swing`, skipping entries that open more than 0.3 ATR above the signal close and anchoring the stop and target to the fill lifts out-of-sample expectancy from +0.1804R (1,936 trades) to +0.2303R (1,717 trades) per unit of planned risk, with a Holm-adjusted p of 0.048 against the 0.05 line; but about 15% of that lift is the removal of 17 baseline trades that the engine books as bought above their target and sold at it on the same bar, a loss no live bracket would take, and the same test gives an adjusted p of 0.106 with those trades priced at the open and 0.070 against the corrected baseline read the other way its definition allows (section 5). On the other three the rules picked in-sample moved out-of-sample expectancy by +0.0120R (`trend_continuation.short_swing`), −0.0279R (`relative_strength.medium_swing`) and −0.0289R (`high52_breakout.medium_swing`), none near significance (smallest one-sided p 0.35).

**The correction.** The measurement correction alone (B1: risk counted as planned the evening before, and no trade when the open is at or below the stop) lowers the recorded out-of-sample expectancy of `trend_continuation.medium_swing` from +0.2209R to +0.1804R: −0.0172R from the risk unit, −0.0218R from not taking 58 out-of-sample entries that opened at or below their stop (+53.9R in stable R; the engine had booked them at +52.4R), and −0.0014R from the re-simulation that follows those skips (section 2). The other three move by −0.0035R, −0.0093R and +0.0264R.

R means result per unit of risk. *Engine R* divides by the distance from the fill to the stop (the library's unit). *Stable R* divides by the risk planned at the signal, U = signal close − stop, which is what an order sized the evening before actually risks. ATR is the 14-session average true range at the signal. IS is the in-sample (selection) part of each symbol's history, OOS the rest; the OOS part has been looked at by earlier work, so it is a confirmation sample, not an untouched holdout.

## 1. Checks passed before any result was read

| Version | Universe | Recorded run | IS recorded (n / R) | IS reproduced | OOS recorded (n / R) | OOS reproduced | Largest gap to recorded row | Gate-1 folds matched | Local engine copy, hooks off |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `trend_continuation.short_swing` | snapshot 3 (24 symbols) | 53 | 828 / +0.0319 | 828 / +0.0319 | 341 / +0.2648 | 341 / +0.2648 | 0 (exact) | 4 of 4 | identical, 1,169 trades |
| `relative_strength.medium_swing` | snapshot 3 (24 symbols) | 54 | 369 / +0.1588 | 369 / +0.1588 | 197 / +0.3004 | 197 / +0.3004 | 0 (exact) | 4 of 4 | identical, 566 trades |
| `trend_continuation.medium_swing` | snapshot 11 (150 symbols) | 55 | 4,169 / +0.1576 | 4,169 / +0.1576 | 1,986 / +0.2209 | 1,986 / +0.2209 | 0 (exact) | 4 of 4 | identical, 6,155 trades |
| `high52_breakout.medium_swing` | snapshot 11 (150 symbols) | 49 | 972 / +0.0882 | 972 / +0.0882 | 525 / +0.2274 | 525 / +0.2274 | 0 (exact) | 4 of 4 | identical, 1,497 trades |

- **B0 reproduces the record.** The library engine, looped as `research/backtest_runner.py` loops it (bars loaded once, symbols under 60 bars skipped, 30-bar warm-up, 5.5 bps per side, SPY regime series), gives the recorded development rows exactly: the four pre-registered out-of-sample targets to four decimals, the full-precision in-sample and out-of-sample rows, and all sixteen gate-1 fold rows.
- **The script's copy of the engine loop is exact.** With every hook off it returns the same trades as the library engine on every symbol (every field of every trade equal; asserted in the script).
- **The risk unit is what it should be.** ATR14 taken from U ÷ stop multiple equals the library's ATR14 at every signal (largest relative gap 2e-14).
- **Data.** 334,197 bars for 150 symbols, 2016-10-17 to 2025-09-05. No symbol was skipped. The in-sample part ends 2022-02-10 for full-history symbols.

## 2. The correction: B0 against B1 (fact, no test)

B0 is the library engine unchanged. B1 keeps the same signals and exits, measures each trade in stable R, and takes no trade when the entry bar opens at or below the stop; it is a re-simulation (clarification 2). The two middle columns are the steps in between: B0's own trades re-measured in stable R, then that same list without the entries that opened at or below the stop. That list is the other way the pre-registered definition of B1 can be read, and section 5 tests against it as well.

| Version | Sample | B0 trades | B0 expectancy (engine R) | Same B0 trades in stable R | …without the entries opening at or below the stop (n / stable R) | B1 trades | B1 expectancy (stable R) | B1 − B0 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `trend_continuation.short_swing` | IS | 828 | +0.0319 | +0.0562 | 810 / +0.0515 | 813 | +0.0567 | +0.0248 |
|  | OOS | 341 | +0.2648 | +0.2734 | 337 / +0.2652 | 338 | +0.2613 | −0.0035 |
|  | all | 1,169 | +0.0998 | +0.1195 | 1,147 / +0.1142 | 1,151 | +0.1168 | +0.0169 |
| `relative_strength.medium_swing` | IS | 369 | +0.1588 | +0.1542 | 369 / +0.1542 | 369 | +0.1542 | −0.0046 |
|  | OOS | 197 | +0.3004 | +0.2911 | 197 / +0.2911 | 197 | +0.2911 | −0.0093 |
|  | all | 566 | +0.2081 | +0.2019 | 566 / +0.2019 | 566 | +0.2019 | −0.0062 |
| `trend_continuation.medium_swing` | IS | 4,169 | +0.1576 | +0.1574 | 4,099 / +0.1495 | 4,110 | +0.1496 | −0.0080 |
|  | OOS | 1,986 | +0.2209 | +0.2036 | 1,928 / +0.1818 | 1,936 | +0.1804 | −0.0405 |
|  | all | 6,155 | +0.1780 | +0.1723 | 6,027 / +0.1598 | 6,046 | +0.1594 | −0.0186 |
| `high52_breakout.medium_swing` | IS | 972 | +0.0882 | +0.1045 | 969 / +0.0991 | 969 | +0.0991 | +0.0109 |
|  | OOS | 525 | +0.2274 | +0.2570 | 521 / +0.2537 | 521 | +0.2537 | +0.0264 |
|  | all | 1,497 | +0.1370 | +0.1580 | 1,490 / +0.1531 | 1,490 | +0.1531 | +0.0162 |

**The correction in three steps** (change in expectancy, R; the three steps add up to B1 − B0).

| Version | Sample | Risk unit (engine R to stable R) | Entries opening at or below the stop not taken | Re-simulation after those skips | B1 − B0 |
| --- | --- | ---: | ---: | ---: | ---: |
| `trend_continuation.short_swing` | IS | +0.0243 | −0.0047 | +0.0052 | +0.0248 |
|  | OOS | +0.0085 | −0.0082 | −0.0038 | −0.0035 |
|  | all | +0.0197 | −0.0053 | +0.0025 | +0.0169 |
| `relative_strength.medium_swing` | IS | −0.0046 | +0.0000 | +0.0000 | −0.0046 |
|  | OOS | −0.0093 | +0.0000 | +0.0000 | −0.0093 |
|  | all | −0.0062 | +0.0000 | +0.0000 | −0.0062 |
| `trend_continuation.medium_swing` | IS | −0.0002 | −0.0078 | +0.0001 | −0.0080 |
|  | OOS | −0.0172 | −0.0218 | −0.0014 | −0.0405 |
|  | all | −0.0057 | −0.0125 | −0.0004 | −0.0186 |
| `high52_breakout.medium_swing` | IS | +0.0163 | −0.0054 | +0.0000 | +0.0109 |
|  | OOS | +0.0296 | −0.0033 | +0.0000 | +0.0264 |
|  | all | +0.0210 | −0.0048 | +0.0000 | +0.0162 |

**Entries that opened at or below the stop under B0, and what the engine booked for them.**

| Version | Trades | IS / OOS | Booked as a gain | Booked as a loss | Total engine R booked | Total IS / OOS | Same entries in stable R, IS / OOS | Mean opening gap (ATR) |
| --- | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: |
| `trend_continuation.short_swing` | 22 | 18 / 4 | 18 at +0.79R on average (+0.21 to +0.99) | 4 at −5.20R on average (−12.38 to −0.22) | −6.6 | −7.4 / +0.9 | +4.8 / +3.9 | −2.19 |
| `relative_strength.medium_swing` | 0 | 0 / 0 | — | — | — | — | — | — |
| `trend_continuation.medium_swing` | 128 | 70 / 58 | 123 at +0.91R on average (+0.06 to +1.00) | 5 at −8.39R on average (−30.43 to −1.22) | +70.4 | +18.0 / +52.4 | +43.2 / +53.9 | −2.70 |
| `high52_breakout.medium_swing` | 7 | 3 / 4 | 7 at +0.97R on average (+0.91 to +0.99) | 0 | +6.8 | +2.9 / +3.9 | +5.6 / +2.7 | −4.44 |

All of them close on the entry bar as a "stop" at the stop price. Most are booked as a gain (+0.79R to +0.97R on average by version): the fill is below the stop, so "selling at the stop" is a sale above the purchase price, a trade that could not have happened. A few are booked as a large loss: when the fill lands within about 5.5 bps of the stop, the engine's risk unit shrinks to almost nothing and the two-way cost alone becomes many R. B1 takes none of these.

B1 is a re-simulation: a symbol freed by a skipped entry can take a signal B0 never reached, and that can displace a later B0 trade. Trades in B0 but not B1, and in B1 but not B0: `trend_continuation.short_swing` 27 dropped (22 that opened at or below the stop, 5 displaced) / 9 new; `relative_strength.medium_swing` 0 dropped / 0 new; `trend_continuation.medium_swing` 149 dropped (128 that opened at or below the stop, 21 displaced) / 40 new; `high52_breakout.medium_swing` 7 dropped / 0 new. Every trade present in both has the same exit and the same stable R (checked on the per-trade tables). The last step of the table above is those side effects: out-of-sample, for `trend_continuation.medium_swing`, 13 new trades totalling −3.2R and 5 displaced trades that had totalled −1.9R.

**Entry-bar exits (trades closed on the bar they were opened).**

| Version | Sample | B0 share (n) | B0 mean (engine R) | B0 total R | B1 share (n) | B1 mean (stable R) | B1 total R |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `trend_continuation.short_swing` | IS | 10.0% (83) | −0.8964 | −74.4 | 8.2% (67) | −0.7467 | −50.0 |
|  | OOS | 10.3% (35) | −0.6854 | −24.0 | 9.2% (31) | −0.5253 | −16.3 |
| `relative_strength.medium_swing` | IS | 1.1% (4) | −1.0227 | −4.1 | 1.1% (4) | −0.7335 | −2.9 |
|  | OOS | 2.0% (4) | −0.7238 | −2.9 | 2.0% (4) | −0.5462 | −2.2 |
| `trend_continuation.medium_swing` | IS | 10.2% (427) | −0.6005 | −256.4 | 8.8% (360) | −0.6357 | −228.8 |
|  | OOS | 11.7% (232) | −0.3032 | −70.3 | 9.0% (174) | −0.5040 | −87.7 |
| `high52_breakout.medium_swing` | IS | 5.6% (54) | −0.8254 | −44.6 | 5.3% (51) | −0.6722 | −34.3 |
|  | OOS | 5.3% (28) | −0.4703 | −13.2 | 4.6% (24) | −0.3636 | −8.7 |

Cross-check: B0's whole-window bucket for `trend_continuation.short_swing` is 118 trades at −0.8338R, −98.39R in total, which matches the figure recorded in `docs/research/diagnostics/v3_duration_exits.md` §6(a) (118 trades, −0.8338R, −98.39R).

**What B1's entry-bar exits are** (description of the saved B1 trades; not a pre-registered metric). Each pair is trades / total stable R.

| Version | Sample | All entry-bar exits | Stop hit during the entry bar | Opened above the target, closed at the target | Target reached during the entry bar | Last bar of the data |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `trend_continuation.short_swing` | IS | 67 / −50.0 | 64 / −48.3 | 1 / −1.9 | 2 / +0.2 | 0 / +0.0 |
|  | OOS | 31 / −16.3 | 24 / −16.0 | 2 / −2.8 | 3 / +2.7 | 2 / −0.2 |
| `relative_strength.medium_swing` | IS | 4 / −2.9 | 4 / −2.9 | 0 / +0.0 | 0 / +0.0 | 0 / +0.0 |
|  | OOS | 4 / −2.2 | 3 / −2.4 | 0 / +0.0 | 0 / +0.0 | 1 / +0.2 |
| `trend_continuation.medium_swing` | IS | 360 / −228.8 | 289 / −238.7 | 29 / −29.6 | 42 / +39.5 | 0 / +0.0 |
|  | OOS | 174 / −87.7 | 127 / −96.3 | 17 / −14.8 | 26 / +23.9 | 4 / −0.5 |
| `high52_breakout.medium_swing` | IS | 51 / −34.3 | 45 / −33.0 | 3 / −1.6 | 3 / +0.4 | 0 / +0.0 |
|  | OOS | 24 / −8.7 | 19 / −12.2 | 0 / +0.0 | 2 / +3.1 | 3 / +0.4 |

The third column is a second engine quirk that B1 keeps ("same exits as B0"): an entry that opens above its target is closed at the target price on the same bar, below where it was bought, so it is booked as a loss. V1 removes those entries and V3 moves the target above the fill.

**Opening gap in ATR units, (open − signal close) ÷ ATR14: all B1 trades against B1's entry-bar losers** (whole development window).

| Version | Group | Trades | Mean | 5% | 25% | Median | 75% | 95% | Min | Max |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `trend_continuation.short_swing` | all trades | 1,151 | +0.07 | −0.76 | −0.21 | +0.06 | +0.30 | +0.79 | −1.49 | +6.74 |
|  | entry-bar losers | 92 | −0.30 | −1.29 | −0.90 | −0.47 | −0.05 | +0.62 | −1.49 | +6.74 |
| `relative_strength.medium_swing` | all trades | 566 | +0.04 | −0.61 | −0.16 | +0.04 | +0.26 | +0.62 | −1.86 | +2.27 |
|  | entry-bar losers | 7 | −0.68 | −1.84 | −1.16 | −0.42 | −0.33 | +0.25 | −1.86 | +0.49 |
| `trend_continuation.medium_swing` | all trades | 6,046 | +0.10 | −0.62 | −0.16 | +0.04 | +0.26 | +0.83 | −1.49 | +9.31 |
|  | entry-bar losers | 464 | +0.12 | −1.20 | −0.65 | −0.27 | +0.11 | +3.66 | −1.49 | +9.31 |
| `high52_breakout.medium_swing` | all trades | 1,490 | +0.05 | −0.66 | −0.20 | +0.03 | +0.26 | +0.76 | −1.95 | +6.06 |
|  | entry-bar losers | 68 | −0.37 | −1.85 | −1.06 | −0.52 | −0.11 | +1.53 | −1.95 | +6.06 |

| Version | Group | Gap below −1.0 | below −0.6 | below −0.3 | above +0.3 | above +0.6 | above +1.0 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `trend_continuation.short_swing` | all trades | 2.5% | 8.6% | 18.9% | 25.3% | 10.2% | 3.5% |
|  | entry-bar losers | 22.8% | 44.6% | 57.6% | 9.8% | 5.4% | 3.3% |
| `relative_strength.medium_swing` | all trades | 1.4% | 5.1% | 14.5% | 22.1% | 5.7% | 0.9% |
|  | entry-bar losers | 28.6% | 28.6% | 71.4% | 14.3% | 0.0% | 0.0% |
| `trend_continuation.medium_swing` | all trades | 1.4% | 5.4% | 15.1% | 21.9% | 8.5% | 4.0% |
|  | entry-bar losers | 11.9% | 28.7% | 48.5% | 16.8% | 13.6% | 11.2% |
| `high52_breakout.medium_swing` | all trades | 2.0% | 6.7% | 18.7% | 21.5% | 8.3% | 2.5% |
|  | entry-bar losers | 26.5% | 45.6% | 64.7% | 7.4% | 5.9% | 5.9% |

In every version the entry-bar losers sit on weaker opens than trades in general: their median gap is −0.52 to −0.27 ATR against +0.03 to +0.06 ATR for all trades, and 48.5% to 71.4% of them opened more than 0.3 ATR below the signal close against 14.5% to 18.9% of all trades. The same tables for B0 are in `summary.json`.

## 3. Every pre-registered cell

Each cell is a full re-simulation of B1 plus one rule. V1 g: enter only if open ≤ signal close + g × ATR14. V2 h: enter only if open ≥ signal close − h × ATR14. V3: stop and target recomputed from the fill with the version's own ATR multiples. B0 is in engine R; every other row is in stable R. Total R per year divides by 5.32 years in-sample and 3.57 years out-of-sample for every cell. "Raises both" is the pre-registered screen: higher in-sample expectancy and higher in-sample total R per year than B1.

### `trend_continuation.short_swing` — snapshot 3, 24 symbols; stop 1.5 ATR, target 3 ATR, time stop 10 bars

| In-sample cell | Trades | Trades vs B1 | Expectancy (R) | Total R per year | Entry-bar exits (n) | Entry-bar mean R | Worst trade (R) | Raises both vs B1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| B0 | 828 | — | +0.0319 | +5.0 | 10.0% (83) | −0.8964 | −12.38 | — |
| B1 | 813 | — | +0.0567 | +8.7 | 8.2% (67) | −0.7467 | −4.33 | — |
| V1 g=0.3 | 720 | −11.4% | +0.0745 | +10.1 | 10.0% (72) | −0.7242 | −4.33 | yes |
| V1 g=0.6 | 779 | −4.2% | +0.0733 | +10.7 | 8.6% (67) | −0.7320 | −4.33 | yes |
| V1 g=1.0 | 804 | −1.1% | +0.0796 | +12.0 | 8.1% (65) | −0.7514 | −4.33 | yes |
| V2 h=0.3 | 724 | −10.9% | +0.0301 | +4.1 | 4.7% (34) | −0.9966 | −4.33 | no |
| V2 h=0.6 | 776 | −4.6% | +0.0510 | +7.4 | 5.3% (41) | −0.9918 | −4.33 | no |
| V2 h=1.0 | 800 | −1.6% | +0.0539 | +8.1 | 6.6% (53) | −0.8676 | −4.33 | no |
| V3 | 811 | −0.2% | +0.0654 | +10.0 | 6.5% (53) | −0.9199 | −4.33 | yes |
| E\* = V1 g=1.0 + V3 | 802 | −1.4% | +0.0792 | +11.9 | 6.2% (50) | −0.9131 | −4.33 | — |

| Out-of-sample cell | Trades | Trades vs B1 | Expectancy (R) | Total R per year | Entry-bar exits (n) | Entry-bar mean R | Worst trade (R) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| B0 | 341 | — | +0.2648 | +25.3 | 10.3% (35) | −0.6854 | −2.09 |
| B1 | 338 | — | +0.2613 | +24.8 | 9.2% (31) | −0.5253 | −2.56 |
| V1 g=0.3 | 297 | −12.1% | +0.2320 | +19.3 | 10.1% (30) | −0.4950 | −1.46 |
| V1 g=0.6 | 330 | −2.4% | +0.2690 | +24.9 | 8.8% (29) | −0.4906 | −2.07 |
| V1 g=1.0 | 337 | −0.3% | +0.2758 | +26.1 | 8.0% (27) | −0.5318 | −1.71 |
| V2 h=0.3 | 282 | −16.6% | +0.3069 | +24.3 | 5.7% (16) | −0.6239 | −2.56 |
| V2 h=0.6 | 314 | −7.1% | +0.2754 | +24.2 | 6.1% (19) | −0.6347 | −2.56 |
| V2 h=1.0 | 332 | −1.8% | +0.2708 | +25.2 | 7.2% (24) | −0.6039 | −2.56 |
| V3 | 332 | −1.8% | +0.2799 | +26.1 | 5.4% (18) | −0.7563 | −1.90 |
| E\* = V1 g=1.0 + V3 | 331 | −2.1% | +0.2734 | +25.4 | 5.1% (17) | −0.7403 | −1.90 |

### `relative_strength.medium_swing` — snapshot 3, 24 symbols; stop 2.5 ATR, target 5 ATR, time stop 40 bars

| In-sample cell | Trades | Trades vs B1 | Expectancy (R) | Total R per year | Entry-bar exits (n) | Entry-bar mean R | Worst trade (R) | Raises both vs B1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| B0 | 369 | — | +0.1588 | +11.0 | 1.1% (4) | −1.0227 | −2.54 | — |
| B1 | 369 | — | +0.1542 | +10.7 | 1.1% (4) | −0.7335 | −2.60 | — |
| V1 g=0.3 (= E\*) | 367 | −0.5% | +0.1788 | +12.3 | 2.2% (8) | −0.7859 | −2.60 | yes |
| V1 g=0.6 | 367 | −0.5% | +0.1499 | +10.3 | 1.1% (4) | −0.7335 | −2.60 | no |
| V1 g=1.0 | 368 | −0.3% | +0.1517 | +10.5 | 1.1% (4) | −0.7335 | −2.60 | no |
| V2 h=0.3 | 354 | −4.1% | +0.1606 | +10.7 | 0.3% (1) | −0.9055 | −2.60 | no |
| V2 h=0.6 | 362 | −1.9% | +0.1432 | +9.7 | 0.8% (3) | −0.8777 | −2.60 | no |
| V2 h=1.0 | 366 | −0.8% | +0.1552 | +10.7 | 0.8% (3) | −0.8777 | −2.60 | no |
| V3 | 378 | +2.4% | +0.1168 | +8.3 | 0.8% (3) | −1.0160 | −2.60 | no |

| Out-of-sample cell | Trades | Trades vs B1 | Expectancy (R) | Total R per year | Entry-bar exits (n) | Entry-bar mean R | Worst trade (R) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| B0 | 197 | — | +0.3004 | +16.6 | 2.0% (4) | −0.7238 | −1.63 |
| B1 | 197 | — | +0.2911 | +16.1 | 2.0% (4) | −0.5462 | −1.92 |
| V1 g=0.3 (= E\*) | 185 | −6.1% | +0.2633 | +13.7 | 1.1% (2) | −0.5690 | −1.42 |
| V1 g=0.6 | 194 | −1.5% | +0.2915 | +15.9 | 2.1% (4) | −0.5462 | −1.92 |
| V1 g=1.0 | 196 | −0.5% | +0.2891 | +15.9 | 2.0% (4) | −0.5462 | −1.92 |
| V2 h=0.3 | 186 | −5.6% | +0.3455 | +18.0 | 1.6% (3) | −0.6806 | −1.92 |
| V2 h=0.6 | 193 | −2.0% | +0.2950 | +16.0 | 1.6% (3) | −0.6345 | −1.92 |
| V2 h=1.0 | 196 | −0.5% | +0.2914 | +16.0 | 1.5% (3) | −0.6345 | −1.92 |
| V3 | 197 | +0.0% | +0.2871 | +15.9 | 2.0% (4) | −0.7172 | −1.92 |

### `trend_continuation.medium_swing` — snapshot 11, 150 symbols; stop 1.5 ATR, target 3 ATR, time stop 40 bars

| In-sample cell | Trades | Trades vs B1 | Expectancy (R) | Total R per year | Entry-bar exits (n) | Entry-bar mean R | Worst trade (R) | Raises both vs B1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| B0 | 4,169 | — | +0.1576 | +123.5 | 10.2% (427) | −0.6005 | −30.43 | — |
| B1 | 4,110 | — | +0.1496 | +115.6 | 8.8% (360) | −0.6357 | −7.36 | — |
| V1 g=0.3 | 3,675 | −10.6% | +0.1765 | +121.9 | 8.7% (318) | −0.6946 | −5.75 | yes |
| V1 g=0.6 | 3,950 | −3.9% | +0.1684 | +125.0 | 8.0% (315) | −0.7081 | −7.36 | yes |
| V1 g=1.0 | 4,031 | −1.9% | +0.1664 | +126.1 | 7.5% (303) | −0.7105 | −7.36 | yes |
| V2 h=0.3 | 3,773 | −8.2% | +0.1393 | +98.8 | 5.9% (221) | −0.7214 | −7.36 | no |
| V2 h=0.6 | 4,001 | −2.7% | +0.1461 | +109.9 | 7.1% (284) | −0.6936 | −7.36 | no |
| V2 h=1.0 | 4,084 | −0.6% | +0.1476 | +113.3 | 8.2% (333) | −0.6630 | −7.36 | no |
| V3 | 4,045 | −1.6% | +0.1633 | +124.2 | 6.9% (278) | −0.7648 | −7.36 | yes |
| E\* = V1 g=0.3 + V3 | 3,655 | −11.1% | +0.1820 | +125.1 | 5.9% (215) | −0.8841 | −5.75 | — |

| Out-of-sample cell | Trades | Trades vs B1 | Expectancy (R) | Total R per year | Entry-bar exits (n) | Entry-bar mean R | Worst trade (R) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| B0 | 1,986 | — | +0.2209 | +123.0 | 11.7% (232) | −0.3032 | −6.99 |
| B1 | 1,936 | — | +0.1804 | +97.9 | 9.0% (174) | −0.5040 | −6.44 |
| V1 g=0.3 | 1,733 | −10.5% | +0.2159 | +104.9 | 7.7% (133) | −0.6597 | −6.44 |
| V1 g=0.6 | 1,869 | −3.5% | +0.2078 | +108.9 | 7.2% (135) | −0.6263 | −6.44 |
| V1 g=1.0 | 1,900 | −1.9% | +0.1926 | +102.6 | 7.2% (136) | −0.6178 | −6.44 |
| V2 h=0.3 | 1,746 | −9.8% | +0.1873 | +91.7 | 6.2% (108) | −0.4769 | −6.44 |
| V2 h=0.6 | 1,866 | −3.6% | +0.1771 | +92.6 | 7.0% (131) | −0.5480 | −6.44 |
| V2 h=1.0 | 1,917 | −1.0% | +0.1853 | +99.6 | 7.8% (150) | −0.5464 | −6.44 |
| V3 | 1,909 | −1.4% | +0.2108 | +112.8 | 5.9% (112) | −0.8037 | −6.44 |
| E\* = V1 g=0.3 + V3 | 1,717 | −11.3% | +0.2303 | +110.8 | 4.4% (76) | −0.9383 | −6.44 |

### `high52_breakout.medium_swing` — snapshot 11, 150 symbols; stop 2 ATR, target 4 ATR, time stop 40 bars

| In-sample cell | Trades | Trades vs B1 | Expectancy (R) | Total R per year | Entry-bar exits (n) | Entry-bar mean R | Worst trade (R) | Raises both vs B1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| B0 | 972 | — | +0.0882 | +16.1 | 5.6% (54) | −0.8254 | −3.31 | — |
| B1 | 969 | — | +0.0991 | +18.0 | 5.3% (51) | −0.6722 | −3.81 | — |
| V1 g=0.3 | 857 | −11.6% | +0.0550 | +8.9 | 6.2% (53) | −0.7335 | −3.81 | no |
| V1 g=0.6 | 929 | −4.1% | +0.1046 | +18.3 | 5.1% (47) | −0.7284 | −3.81 | yes |
| V1 g=1.0 | 960 | −0.9% | +0.0965 | +17.4 | 4.9% (47) | −0.7245 | −3.81 | no |
| V2 h=0.3 | 829 | −14.4% | +0.1418 | +22.1 | 2.4% (20) | −0.7925 | −3.81 | yes |
| V2 h=0.6 | 912 | −5.9% | +0.1079 | +18.5 | 3.4% (31) | −0.8019 | −3.81 | yes |
| V2 h=1.0 | 951 | −1.9% | +0.1006 | +18.0 | 4.2% (40) | −0.7699 | −3.81 | no |
| V3 | 960 | −0.9% | +0.1445 | +26.1 | 3.8% (36) | −0.8535 | −3.81 | yes |
| E\* = V1 g=0.6 + V2 h=0.3 + V3 | 777 | −19.8% | +0.1508 | +22.0 | 2.4% (19) | −1.0206 | −3.81 | — |

| Out-of-sample cell | Trades | Trades vs B1 | Expectancy (R) | Total R per year | Entry-bar exits (n) | Entry-bar mean R | Worst trade (R) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| B0 | 525 | — | +0.2274 | +33.5 | 5.3% (28) | −0.4703 | −5.13 |
| B1 | 521 | — | +0.2537 | +37.1 | 4.6% (24) | −0.3636 | −4.83 |
| V1 g=0.3 | 463 | −11.1% | +0.1868 | +24.2 | 4.5% (21) | −0.5693 | −4.83 |
| V1 g=0.6 | 510 | −2.1% | +0.2199 | +31.4 | 4.7% (24) | −0.4974 | −4.83 |
| V1 g=1.0 | 517 | −0.8% | +0.2322 | +33.7 | 4.3% (22) | −0.4612 | −4.83 |
| V2 h=0.3 | 436 | −16.3% | +0.2789 | +34.1 | 2.1% (9) | −0.2562 | −4.83 |
| V2 h=0.6 | 489 | −6.1% | +0.2643 | +36.2 | 2.5% (12) | −0.3907 | −4.83 |
| V2 h=1.0 | 512 | −1.7% | +0.2577 | +37.0 | 3.1% (16) | −0.4335 | −4.83 |
| V3 | 528 | +1.3% | +0.2336 | +34.6 | 3.2% (17) | −0.5663 | −4.83 |
| E\* = V1 g=0.6 + V2 h=0.3 + V3 | 429 | −17.7% | +0.2249 | +27.0 | 1.6% (7) | −1.0154 | −4.83 |

## 4. Selection on the in-sample trades only

| Version | V1 cells that raise both (g) | V1 pick | V2 cells that raise both (h) | V2 pick | V3 raises both | Candidate E\* |
| --- | --- | --- | --- | --- | --- | --- |
| `trend_continuation.short_swing` | 0.3, 0.6, 1.0 | g = 1.0 | none | — | yes | V1 g=1.0 + V3 |
| `relative_strength.medium_swing` | 0.3 | g = 0.3 | none | — | no | V1 g=0.3 |
| `trend_continuation.medium_swing` | 0.3, 0.6, 1.0 | g = 0.3 | none | — | yes | V1 g=0.3 + V3 |
| `high52_breakout.medium_swing` | 0.6 | g = 0.6 | 0.3, 0.6 | h = 0.3 | yes | V1 g=0.6 + V2 h=0.3 + V3 |

Where several cells of one family qualify, the script takes the one with the highest in-sample expectancy (clarification 5). That choice changed the pick in one place — `trend_continuation.medium_swing` V1: highest in-sample expectancy is g=0.3 (+0.1765R, +121.9R per year), highest in-sample total R per year is g=1.0 (+0.1664R, +126.1R per year). The alternative combination was not run by the study (section 5).

## 5. Confirmation on the out-of-sample trades, and the decision rule

One test per version: out-of-sample expectancy of E\* minus that of B1, one-sided, calendar-month block bootstrap (10,000 resamples of entry months, the same months drawn for both arms, seed 20261110), Holm-adjusted across the four versions. Clarification 8 gives the exact construction of p.

| Version | E\* | B1 OOS (n / R) | E\* OOS (n / R) | Difference (R) | Bootstrap SE | Entry months resampled | p, one-sided | Holm-adjusted p |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `trend_continuation.short_swing` | V1 g=1.0 + V3 | 338 / +0.2613 | 331 / +0.2734 | +0.0120 | 0.0353 | 28 (2023-02 to 2025-09) | 0.3498 | 1.0000 |
| `relative_strength.medium_swing` | V1 g=0.3 | 197 / +0.2911 | 185 / +0.2633 | −0.0279 | 0.0455 | 31 (2022-02 to 2025-09) | 0.7372 | 1.0000 |
| `trend_continuation.medium_swing` | V1 g=0.3 + V3 | 1,936 / +0.1804 | 1,717 / +0.2303 | +0.0499 | 0.0234 | 28 (2023-02 to 2025-09) | 0.0119 | 0.0476 |
| `high52_breakout.medium_swing` | V1 g=0.6 + V2 h=0.3 + V3 | 521 / +0.2537 | 429 / +0.2249 | −0.0289 | 0.0383 | 28 (2023-02 to 2025-09) | 0.7517 | 1.0000 |

**The four conditions of the decision rule** (all must hold).

| Version | Holm p < 0.05 | Total R per year, E\* vs B1 (not more than 10% below) | Folds with the same sign as the OOS difference (at least 3) | Difference at 11 bps per side (> 0) | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| `trend_continuation.short_swing` | 1.0000: no | +25.4 vs +24.8 (102%): yes | 4 of 4: yes | +0.0269: yes | **no upgrade** |
| `relative_strength.medium_swing` | 1.0000: no | +13.7 vs +16.1 (85%): no | 1 of 4: no | −0.0278: no | **no upgrade** |
| `trend_continuation.medium_swing` | 0.0476: yes | +110.8 vs +97.9 (113%): yes | 4 of 4: yes | +0.0472: yes | **upgrade candidate** by the rule as run; it does not hold up (below) |
| `high52_breakout.medium_swing` | 1.0000: no | +27.0 vs +37.1 (73%): no | 2 of 4: no | −0.0345: no | **no upgrade** |

**Expectancy of E\* minus B1 in the four gate-1 calendar folds** (whole development window; trades B1 → E\* in brackets). Folds 1 and 2 lie wholly inside the selection sample, fold 3 straddles the boundary and fold 4 is wholly out-of-sample.

| Version | Fold 1, from 2016-10-17 | Fold 2, from 2019-01-06 | Fold 3, from 2021-03-28 | Fold 4, from 2023-06-18 |
| --- | ---: | ---: | ---: | ---: |
| `trend_continuation.short_swing` | +0.0340 (329 → 321) | +0.0062 (362 → 359) | +0.0065 (184 → 182) | +0.0278 (276 → 271) |
| `relative_strength.medium_swing` | +0.0370 (115 → 112) | +0.0043 (171 → 173) | +0.0024 (116 → 111) | −0.0109 (164 → 156) |
| `trend_continuation.medium_swing` | +0.0110 (1,656 → 1,476) | +0.0604 (1,840 → 1,611) | +0.0208 (900 → 823) | +0.0504 (1,650 → 1,462) |
| `high52_breakout.medium_swing` | +0.0419 (283 → 245) | +0.1079 (489 → 363) | −0.0809 (258 → 222) | −0.0187 (460 → 376) |

**At 11 bps per side** (slippage 6 bps plus half of a 10 bps spread; B1 and E\* only), out-of-sample.

| Version | B1 (n / R) | E\* (n / R) | Difference (R) |
| --- | ---: | ---: | ---: |
| `trend_continuation.short_swing` | 338 / +0.2099 | 330 / +0.2368 | +0.0269 |
| `relative_strength.medium_swing` | 197 / +0.2662 | 185 / +0.2384 | −0.0278 |
| `trend_continuation.medium_swing` | 1,936 / +0.1430 | 1,719 / +0.1902 | +0.0472 |
| `high52_breakout.medium_swing` | 521 / +0.2256 | 430 / +0.1911 | −0.0345 |

### How firm the `trend_continuation.medium_swing` pass is

By the rule as written the verdict is "upgrade candidate". It does not hold up. Of the 11 single changes in the table below, 9 turn the pass into a fail (rows 3 to 10 and 12) and 2 leave it a pass by the same hair (rows 2 and 11); the result is best read as **not confirmed**. The table and the bullets that refer to its rows were added after adversarial review (clarification 14). They re-measure the saved trades of the two pre-registered arms and repeat the pre-registered bootstrap; no entry rule was simulated for them, and nothing in them enters the selection, the test or the verdict.

**The same test with one thing changed at a time** (E\* minus the baseline, out-of-sample, one-sided; the registered seed and the same month blocks unless the row says otherwise). Adjusted p is p × 4, the Holm factor for this test; it passes only below 0.05, that is p below 0.0125.

| What is changed | Baseline OOS (n / R) | E\* − baseline (R) | p, one-sided | Adjusted p | Under 0.05? |
| --- | ---: | ---: | ---: | ---: | --- |
| 1. Nothing: the pre-registered test as run | 1,936 / +0.1804 | +0.0499 | 0.0119 | 0.0476 | yes |
| 2. 20,000,000 resamples instead of 10,000 (2,000 other seeds pooled) | 1,936 / +0.1804 | +0.0499 | 0.0122 | 0.0489 | yes |
| 3. The baseline's 17 above-target entries priced at the open, not at the target | 1,936 / +0.1877 | +0.0426 | 0.0265 | 0.1060 | no |
| 4. Those 17 entries left out of the baseline | 1,919 / +0.1897 | +0.0406 | 0.0311 | 0.1244 | no |
| 5. Baseline = B0's own trades without the entries opening at or below the stop (no re-simulation) | 1,928 / +0.1818 | +0.0485 | 0.0174 | 0.0696 | no |
| 6. p = share of resamples with a difference of zero or less | 1,936 / +0.1804 | +0.0499 | 0.0198 | 0.0792 | no |
| 7. Null centred on the bootstrap mean, not on the observed difference | 1,936 / +0.1804 | +0.0499 | 0.0138 | 0.0552 | no |
| 8. Normal reference with the bootstrap standard error | 1,936 / +0.1804 | +0.0499 | 0.0166 | 0.0664 | no |
| 9. Student t reference, 27 degrees of freedom, same standard error | 1,936 / +0.1804 | +0.0499 | 0.0212 | 0.0849 | no |
| 10. Studentised bootstrap (each resample divided by its own standard error) | 1,936 / +0.1804 | +0.0499 | 0.0264 | 0.1056 | no |
| 11. Blocks = every calendar month from the first to the last entry month (32, of which 4 hold no entry) | 1,936 / +0.1804 | +0.0499 | 0.0111 | 0.0444 | yes |
| 12. Blocks = every calendar month of the out-of-sample span (44, from 2022-02) | 1,936 / +0.1804 | +0.0499 | 0.0150 | 0.0600 | no |

Rows 3 to 5 apply the same re-measurement to every cell and repeat the in-sample screen. It names the same candidate for this version in each. Under row 3 it would name V2 h=0.3 + V3 for `high52_breakout.medium_swing` instead of V1 g=0.6 + V2 h=0.3 + V3; that combination was not run, and whatever it would give, this version's adjusted p is at least 0.0795. Under row 4 it would name V2 h=0.3 + V3 for `high52_breakout.medium_swing` instead of V1 g=0.6 + V2 h=0.3 + V3; that combination was not run, and whatever it would give, this version's adjusted p is at least 0.0933. Under row 5 it would name V1 g=1.0 + V2 h=1.0 + V3 for `trend_continuation.short_swing` instead of V1 g=1.0 + V3; that combination was not run, and whatever it would give, this version's adjusted p is at least 0.0522.

- **About 15% of the lift is a booking artefact in the baseline** (rows 3 and 4). B1 keeps B0's exits, as pre-registered. Among them are 17 out-of-sample entries that opened above their target (46 over the whole window): the engine closes each at the target price on the bar it was bought, below the purchase price, for −14.8R in total (−44.4R over the whole window). In 8 of the 17 the whole bar traded above the target, so the target price never traded that day (9 if the booked sale price, the target less costs, is set against the bar's low). A sell limit that is below the market when it is placed fills near the open; priced that way the 17 cost −0.7R (costs only), B1's out-of-sample expectancy is +0.1877R rather than +0.1804R, and the lift is +0.0426R rather than +0.0499R. E\* holds 0 such entries (V1 skips them and V3 puts the target above the fill), so 0.0073R of the lift is the removal of losses that no live bracket would take. That is more than the pass can spare: 118 of the 10,000 null draws were at or above the observed difference, and a pass allows at most 124. It is not seed noise either: with the entries priced at the open 0 of 300 other seeds pass (pooled p 0.0247, adjusted 0.0989); with them left out, 0 of 300 (pooled p 0.0302, adjusted 0.1206).
- **It depends on reading B1 as a re-simulation** (row 5, clarification 2). Against B0's own trades without the entries that opened at or below the stop, the baseline is 1,928 trades at +0.1818R and the test gives p 0.0174, adjusted 0.0696 (0 of 300 other seeds pass; pooled p 0.0167). Which reading the pre-registration meant is for its author to say; under this one the rule gives no upgrade for this version (adjusted p at least 0.0522).
- **It depends on how the bootstrap p is formed** (rows 6 to 12, clarification 8). The script reads "null distribution" as the resampled differences recentred on zero, which gives 0.0119. The share of resamples with a difference of zero or less is 0.0198; centring on the bootstrap mean gives 0.0138; a normal or a t reference with the bootstrap standard error (0.0234R) gives 0.0166 and 0.0212; a studentised bootstrap gives 0.0264. None of those is below 0.0125. The choice of blocks cuts both ways. The script resamples the 28 months that hold an entry. Counting the 4 months inside that stretch with no entry as blocks too gives 0.0111, which is a pass; counting every month of the out-of-sample span from 2022-02 gives 0.0150, which is a fail. The 95% percentile interval for the difference is +0.0025R to +0.0942R.
- **The margin is inside the simulation noise** (row 2). Adjusted p is 0.0476 against 0.05. Pooling 2,000 other seeds (20,000,000 resamples) gives p 0.0122, adjusted 0.0489; taken one seed at a time, 1,180 of the 2,000 (59%) pass and the rest do not. The seed was fixed in advance, so the verdict as run stands. Leaving out any one of the 28 entry months and repeating the test, 17 of the 28 deletions fail.
- **It depends on two more choices that only a new simulation could vary** (clarifications 3 and 5): keeping the planned stop as the validity test under V3, and picking among qualifying cells by in-sample expectancy (section 4). The study did not run the alternatives: they would be cells the pre-registration does not contain. An adversarial reviewer ran both outside the study, with an independently written engine loop that the review reports as matching every study cell trade for trade. Picking the V1 cell by in-sample total R per year names V1 g=1.0 + V3: out-of-sample 1,884 trades at +0.2133R, difference +0.0329R, p 0.0419, adjusted 0.1676. V3 without the planned-stop validity test: 1,768 trades at +0.2168R, difference +0.0364R, p 0.0397, adjusted 0.1588. Those are the reviewer's numbers, not study cells, and they were not re-run here.
- **The confirmation sample is short and covers one market stretch.** This version has no out-of-sample entry before 2023-02: the test rests on 28 entry months, 2023-02 to 2025-09. That sample has also been inspected by earlier work on this version, so it is not an untouched holdout.
- **What the fold condition adds, and what it does not.** The difference is positive in all 4 gate-1 folds, but folds 1 and 2 are the selection sample, 614 of the 900 B1 trades in fold 3 are too, and fold 4 holds 1,650 of the 1,936 out-of-sample trades the test already uses. Out-of-sample only, the difference is +0.0471R in fold 3's part (286 → 255 trades) and +0.0504R in fold 4; by entry year, +0.0411R (2023), +0.0681R (2024) and +0.0340R (2025). It is also positive at 11 bps per side (+0.0472R), and total R per year rises (+97.9 to +110.8). Each part alone has a higher out-of-sample point estimate than B1's +0.1804R (V1 g=0.3 alone +0.2159R and V3 alone +0.2108R), but neither was tested on its own and both also drop the above-target entries.
- **The V1 part is close to a check the code base already has elsewhere.** The funded replay rejects a fill at or below the stop and a fill whose reward-to-risk is under 1.5 (`backtest/funded.py:442-453`, `min_reward_to_risk = 1.5`). For this version's bracket (stop 1.5 ATR, target 3 ATR) that is the same line as fill ≤ signal close + 0.3 ATR; the selected V1 cell is g = 0.3. The promotion engine has no such check. Code reading only; the funded replay was not run here.
- **Scale.** The candidate's +0.2303R is close to the +0.2209R already on record for this version (engine R, uncorrected). Measured consistently the gain is against the corrected +0.1804R: the rule mostly wins back what the correction takes away.
- **What a pass licenses** (pre-registration): evidence for a *new version* of the strategy, which would still need the full gate ladder, an operator-authorised sealed look and forward paper evidence. Nothing here changes any approved version, the operating scan, the paper ledger or the frozen studies. A fair test of this rule needs a baseline with both booking artefacts corrected (the stop side, which B1 fixes, and the target side, which it keeps), and that needs its own pre-registration.

## 6. Expectations stated in advance, against the outcome

- *"B1 will differ from B0 by a few hundredths of an R in either direction."* Held. In-sample the change runs from −0.0080R to +0.0248R, out-of-sample from −0.0405R to +0.0264R.
- *"V1 and V2 are expected to cut trade count by 10–30%."* Mostly not. Over the whole window the change in trade count across the four versions is: V1 g=0.3 −11.6% to −2.5%; V1 g=0.6 −3.8% to −0.9%; V1 g=1.0 −1.9% to −0.4%; V2 h=0.3 −15.1% to −4.6%; V2 h=0.6 −6.0% to −1.9%; V2 h=1.0 −1.8% to −0.7%. Only the tightest cells come near 10%, because a skipped entry frees the symbol for its next signal.
- *"A null is a likely outcome."* Three of four versions are a null; the remaining one meets the rule as run, at the line, and does not hold up (section 5).

## Deviations and clarifications

**Deviations from the pre-registration: none.** Scope, cells, selection screen, test, Holm adjustment and decision rule were applied as written; no cell was added and nothing was re-run with a changed rule. The pre-registration left several points open (below). Four of them decide the one pass — clarifications 2, 3, 5 and 8 — and section 5 shows what the other reading of each gives. The pre-registered baseline also keeps a booking artefact that the candidate removes (section 5); that is the design as written, not a deviation, but the pass does not survive correcting it.

**Clarifications** — points the pre-registration left open. Items 1–12 were fixed in the script before its first run; item 13 lists the descriptive additions made by the implementer, item 14 those made after adversarial review.

1. *The open.* Every rule compares the raw opening print of the entry bar. The fill is that open plus costs, as in the engine.
2. *B1 is a re-simulation.* When an entry is not taken the loop moves to the next bar, as the engine's own skip does, so a freed symbol can take a later signal (counts in section 2). The pre-registration calls B1 "same signals and exits as B0 … a measurement correction" and says "each is a full re-simulation" of the variants only, so B1 can also be read as B0's own trades without the entries that opened at or below the stop. The build instruction for this study (written by the round's orchestrator before the run) lists "entry open at or below the stop = no trade" as a switch in the engine loop, which is what the script does; it also keeps both arms of every comparison on one engine path. Section 2 shows both baselines and section 5 tests against both: the one pass holds only against the re-simulated one.
3. *Every V cell is B1 plus one rule:* stable R, and no trade when the open is at or below the planned stop. That includes V3, where the stop planned at the signal remains the validity test.
4. *V3.* Stop = fill − stop multiple × ATR14; target = fill + target multiple × ATR14; the fill is the cost-inclusive entry price; ATR14 = U ÷ stop multiple; time stop unchanged; R is still measured against U. All four versions have an ATR target.
5. *Choosing among several qualifying cells.* The pre-registration says "pick at most one" per family but not how. The script takes the qualifying cell with the highest in-sample expectancy (the statistic the confirmation tests), then the higher in-sample total R per year, then the smaller parameter. Section 4 shows where this mattered.
6. *E\* is one combined rule,* simulated in a single pass. Its combined in-sample result is shown but not screened again against B1.
7. *Total R per year.* Total stable R divided by calendar years of the full-history split: 2016-10-17 to 2022-02-10 (5.32 years) in-sample, the rest to 2025-09-05 (3.57 years) out-of-sample. The same divisors are used for every cell, so every comparison of total R per year is a comparison of total R. BKNG, VST and XLC have shorter histories and later per-symbol boundaries, exactly as the runner defines them.
8. *Bootstrap.* Blocks are the calendar months holding at least one out-of-sample entry in either arm. Each resample draws that many months with replacement and applies the same draw to both arms; the statistic is the difference of the two pooled means. The null distribution is the resampled differences minus the observed difference; p = (1 + number of null draws at or above the observed difference) ÷ 10,001. Draws come from `numpy.random.default_rng(20261110).integers(0, M, size=(10000, M))`, re-seeded for each version.
9. *Holm.* Applied across all four versions. A version without a candidate would have entered with p = 1; all four had one.
10. *Fold condition* (clarified by the round's orchestrator before the run). Computed over the whole development window in the four gate-1 calendar folds, comparing E\* with B1 in each; "same sign" means the sign of the out-of-sample difference. Folds 1 and 2 are inside the selection sample and fold 3 straddles the boundary, so only part of fold 3 and fold 4 add out-of-sample information. Read instead as "any three folds sharing one sign", the condition would read differently for `relative_strength.medium_swing` (3 folds positive, 1 negative, out-of-sample difference −0.0279R); no verdict would change.
11. *11 bps per side.* Slippage 6 bps plus half of a 10 bps spread (the base model doubled), for B1 and E\* only. Because V3 anchors the bracket to the cost-inclusive fill, E\* takes a slightly different set of trades at the higher cost.
12. *Identity checks.* Beyond the pre-registered four-decimal check, B0 was also matched to the full-precision recorded rows and to the recorded gate-1 fold rows. The recorded high52 row was written with a window end two calendar days after the last session (a weekend); the bars are the same.
13. *Descriptive additions, not pre-registered and not used in any selection or test:* the column re-measuring B0's own trades in stable R (section 2), and the breakdown of entry-bar exits (section 2). The breakdown and the gain/loss split of the entries that opened at or below the stop were added after the first run, to describe what those buckets hold; they are counts over the saved per-trade tables. The script was re-run after the first run only to store these counts and after code formatting. Every pre-registered number is identical in every run (the first run's `summary.json` is kept as `summary.first_run.json` and was compared field by field). The cross-check against the earlier diagnostic (section 2) and the note on the funded replay's fill check (section 5) come from reading existing files, also after the first run.
14. *Added after adversarial review, the same day; descriptive only.* Two reviewers reproduced every number of the first version of this file and found no error in the code; they found that the file did not say how little the one pass can carry. Added in response: in section 2, the column for B0's own trades without the entries opening at or below the stop, the three-step table, the stable-R column for those entries and the split of dropped trades; in section 5, the wording of the verdict and, in the "How firm" subsection, the table and the bullets that refer to its rows (the baseline measured three other ways, other seeds, other ways of forming p), the reviewer's two runs, and the fold differences split by sample and by year; and the lead. One sentence of the first version was imprecise and is corrected there: it put all of −0.0233R down to not taking the 58 out-of-sample entries that opened at or below their stop; −0.0218R is those entries and −0.0014R is the re-simulation that follows. All of it re-measures the saved trades of the pre-registered cells or repeats the pre-registered bootstrap with other seeds (20261111 to 20263110). No entry rule was simulated for it, no cell was added, and no selection, test or verdict uses any of it. The script was re-run in full for this revision: every pre-registered field of `summary.json` and all sixteen per-trade tables are identical to the pre-review run (kept under `repair/`). The verdict by the rule is unchanged; how much it can carry is not.

## Files

- Script: `scripts/r3/entry_execution.py` (`--report-only` rebuilds this file from `summary.json`).
- Raw outputs, not committed: `/private/tmp/claude-501/-Users-louisbrailey-Projects-signal-forge/ec635db8-8e7c-46dd-bc95-83c88a678e74/scratchpad/r3/out/entry-exec/`
  - `summary.json` — every number in this file; `summary.first_run.json` — the first run, for comparison.
  - `trades_B0_<version>.csv`, `trades_B1_<version>.csv`, `trades_Estar_<version>.csv` — per-trade tables.
  - `trades_cells_<version>.csv` — per-trade table for every pre-registered cell.
  - `run.log` — identity checks and timings.
  - `repair/` — the pre-review copies of this file, the script and `summary.json`, and the checks run against the reviewers' numbers; `review/` — the reviewers' own scripts.

Research signal only — no order was placed.
