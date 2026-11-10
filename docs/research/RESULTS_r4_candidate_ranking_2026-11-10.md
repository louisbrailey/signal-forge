# Results — R4-K: does relative-strength ranking pick the better same-day candidates? (2026-11-10)

Pre-registration: `docs/research/PREREGISTRATION_r4_candidate_ranking_2026-11-10.md` (commit 1b8cc3a, written before any run of this study). Run on a private read-only copy of the operating database; development window only (bars end 2025-09-05). Descriptive research: no sealed look, no operating-database write, no change to any frozen study, risk limit or approved version. One hypothesis was pre-registered (trend_continuation.medium_swing, key K1); everything else is a control or a description.

Outcomes are in units of planned risk, written R: one R is the distance from the signal-day close to the signal's stop. IS means entered on or before 2022-02-10, OOS after it; nothing is fitted, so both are stretches of already-observed development data.

## Answer

**Not confirmed: ranking same-day candidates by relative strength did not pick the better ones.** On trend_continuation.medium, on days with at least three candidates, the two with the highest 63-session relative strength (K1) did 0.018 R worse than the day's average candidate in IS (665 sessions) and 0.041 R worse in OOS (334 sessions; one-sided p = 0.75); the within-day rank IC is -0.005 and -0.001. None of the four pre-registered conditions holds, so K1 is not confirmed as an admission ranker and, as pre-registered, the R3-C result for K1 on this book is read as admission luck.

For scale, 1,000 random picks of two a day move the OOS lift between -0.067 and +0.072 R (5th to 95th percentile). The K1 lift is above 15.5% of them in OOS and 28.1% in IS; the bar was the 95th percentile in OOS. The average candidate itself earned +0.108 R in IS and +0.145 R in OOS after base costs. That average was positive in both periods, but no test of it was pre-registered or run here, and these are development data in which many signals repeat inside an open holding window of the same symbol. K1 does not say which same-day signals did better.

Controls and descriptions, no verdict (top-2 lift, IS / OOS): on the same book K2 +0.002 / +0.000 R, K3 -0.024 / -0.021 R; K1 on the other three books high52 (11) +0.034 / -0.035 R; TC short (3) -0.015 / +0.001 R; RS medium (3) +0.030 / +0.022 R. Of these 22 control and descriptive cells, 3 are above the random-2 95th percentile (K3 on high52 (11) in OOS; K3 on RS medium (3) in IS; K3 on RS medium (3) in OOS); about 1 would be by chance.

## The pre-registered rule, applied mechanically

trend_continuation.medium_swing on snapshot 11, key K1 (63-session return minus SPY's), signal sessions with at least 3 candidates.

| Condition (all must hold) | IS | OOS | Holds |
|---|---:|---:|---|
| Top-2 lift positive in IS and in OOS | -0.0177 R | -0.0412 R | no |
| OOS one-sided bootstrap p below 0.05 | (IS p 0.7126, not in the rule) | 0.7497 | no |
| Within-day rank IC positive in IS and in OOS | -0.0049 | -0.0013 | no |
| OOS top-2 lift above the 95th percentile of the random-2 band | (IS band p95 +0.0462 R, not in the rule) | -0.0412 R against +0.0723 R | no |

**Verdict: K1 is NOT CONFIRMED as an admission ranker for trend_continuation.medium.** As pre-registered, the R3-C candidate (K1 ordering on the operating caps) is then read as admission luck.

## Reading the result

- **Against R3-C.** In R3-C's funded replay on the operating caps, K1 ordering earned +32.13% in IS and +15.77% in OOS against random-order medians of +10.37% and +6.28% (R3-C results file). A replay scores only the 4% to 5% of signals that get in, and each admission changes the later ones. Here every candidate is scored once, 6,623 in IS and 2,868 in OOS on days with three or more, and the highest-K1 pair is not better than the rest.
- **The one-position view (descriptive).** An account holds one position per symbol, so it would not see 43% (IS) and 40% (OOS) of these signals. On the candidates it would be offered, the K1 top-2 lift is +0.058 R in IS (p = 0.038, 506 sessions) and -0.034 R in OOS (p = 0.755, 224 sessions). This subset is an addition to the pre-registered statistics, chosen after R3-C was known; its p-values are unadjusted and it is one of 8 such cells, so it is a description and not evidence for K1. The positive IS sign does not carry into OOS.
- **Thirds of the ranking.** Pooled over sessions, the top, middle and bottom third by K1 earned +0.100, +0.101 and +0.114 R in IS, and +0.079, +0.146 and +0.225 R in OOS. In OOS the order runs the wrong way: the lowest-ranked third did best.
- **The alphabetical order was lucky.** The two alphabetically first candidates, which the library order offers first, beat the day's average by +0.036 R in IS and +0.058 R in OOS on this book (above 88.5% and 90.6% of the random picks), and by a positive amount in 7 of the 8 book-periods. That is a property of which tickers sort first, not a rule. R3-C found the same: the alphabetical order sat at the 92.5th to 100th percentile of random orders in five of its eight OOS cells.
- **Control cells that stand out.** 3 of the 22 control and descriptive cells are above their random-2 95th percentile (K3 on high52 (11) in OOS: +0.177 R, p = 0.012, 80 sessions, most frequent pick CLS on 14% of them; K3 on RS medium (3) in IS: +0.133 R, p = 0.011, 787 sessions, most frequent pick NVDA on 62% of them; K3 on RS medium (3) in OOS: +0.109 R, p = 0.067, 486 sessions, most frequent pick NVDA on 66% of them). None was a hypothesis and none carries a verdict. A key that keeps picking the same name on a 23-symbol book measures that name more than it ranks candidates. On relative_strength.medium 91% of the signals repeat inside a holding window that is already open, so its sessions are far from independent. Any of them would need its own pre-registration.
- **Dependence.** Neighbouring sessions share symbols and holding windows of up to 40 sessions, so they are not independent; the calendar-month bootstrap allows for part of that. The caveat would weaken a pass; it does not rescue this result, whose lift has the wrong sign in both periods.

## What was run

- Four candidate tables, 25,867 signals in all: every long signal each approved rule produces on signal sessions 2016-12-28 to 2025-09-04 on its approved snapshot (R3-C's signal table, rebuilt from the database and identical to the one R3-C saved).
- Each signal's isolated outcome: taken alone at the next open and closed by the funded replay's own exits at base costs. No account, cash limit, cap or other position enters it.
- Identity check first: 8 of 8 replay cells pass (below).
- Statistics exactly as pre-registered: top-2 lift, within-day Spearman rank IC, tercile buckets, 1,000 random two-a-day rankings and a 10,000-resample calendar-month block bootstrap, IS and OOS separately, for K1, K2 and K3 on all four books. No other key, threshold, horizon or book was run. Three descriptive tables beyond those statistics were added (one-position subset, alphabetical comparison, lift by year); see point 1 under Deviations and clarifications.
- 2 worker processes; prepare 236 s, analysis 22 s.

## Identity check (R3-C alphabetical order, outright rejection, operating caps, base costs)

Every admitted trade of the replay is compared with the isolated outcome of the same symbol and signal session: per-share result divided by planned risk, tolerance 1e-9 R, plus entry price, exit price, exit session and exit reason. The replay is R3-C's local loop, checked here again against a fresh library `run_funded_replay` (fills, marks, decisions, costs and dividend events identical) and against the fill count and final equity R3-C recorded.

| Book | Period | Fills / final equity $ | Same as R3-C's record | Same as a fresh library replay | Trades compared | Liquidated at the period end | Largest difference (R) | Refusals at the open checked | Mismatches | Passed |
|---|---|---:|---|---|---:|---:|---:|---:|---:|---|
| TC medium (11) | IS | 808 / 32919.40 | yes | yes | 404 | 3 | 0.0e+00 | 2424 | 0 | yes |
| TC medium (11) | OOS | 418 / 35583.17 | yes | yes | 209 | 4 | 0.0e+00 | 1071 | 0 | yes |
| high52 (11) | IS | 246 / 33101.32 | yes | yes | 123 | 2 | 0.0e+00 | 309 | 0 | yes |
| high52 (11) | OOS | 180 / 29077.22 | yes | yes | 90 | 4 | 0.0e+00 | 162 | 0 | yes |
| TC short (3) | IS | 876 / 34737.90 | yes | yes | 438 | 1 | 0.0e+00 | 408 | 0 | yes |
| TC short (3) | OOS | 390 / 33544.47 | yes | yes | 195 | 3 | 0.0e+00 | 147 | 0 | yes |
| RS medium (3) | IS | 290 / 32744.53 | yes | yes | 145 | 2 | 0.0e+00 | 352 | 0 | yes |
| RS medium (3) | OOS | 164 / 33383.53 | yes | yes | 82 | 3 | 0.0e+00 | 189 | 0 | yes |

1,686 admitted trades compared; largest difference 0.0e+00 R. 22 of them were still open when their replay ended and were liquidated at its last close. The 14 at the end of OOS (2025-09-05) sit at the end of the data for the candidate table too, so they match it directly. The 8 at the end of the IS replay (2022-02-10) were cut short by the replay window, not by the rule: each matches the isolated outcome computed on that same horizon. The candidate table itself lets an IS-entered candidate run to its own later exit, so its outcome for those 8 is a different one (see "IS and OOS, and the two period ends" under Deviations and clarifications). Every other trade matches the candidate table itself. Every refusal the replay made at the open (crossed stop, reward-to-risk) carries the same flag in the candidate table.

## Independent verification

`scripts/r4/candidate_ranking_verify.py` imports neither the study script nor R3-C, and found no difference (`verify.log`). It was started straight after the second run and, because the host was suspended, completed after the round's cut-off (see "Timing" under Deviations and clarifications); no study number depends on it.

- It read the bars straight from the database and recomputed the three keys and the isolated outcome of all 25,867 signals, finding the exit by array search instead of a session loop. Largest difference 0 on every key and every outcome; every refusal, exit session, exit reason and fill price is the same.
- With pandas it recomputed the top-2 lift, the rank IC and the alphabetical comparison for every book, key and period, on all candidates and on the kept subset, the terciles and by-year lifts on all candidates, and the one-position flags of every signal.
- It reproduced the twelve bootstrap p-values of trend_continuation.medium (lift and IC, three keys, two periods) by resampling month lists one resample at a time, random rankings 0, 500 and 999 of each book with a per-session sort, the 95th percentile of each random-2 band, and the decision.

## Candidates

| Book | Period | Signals | Refused at the open: crossed stop / reward-to-risk | Candidates with an outcome | Mean outcome (R) | Sessions with 3 or more | Candidates on those sessions (share) | Most in one session | Still open at the window end |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| TC medium (11) | IS | 9318 | 165 / 2361 | 6792 | +0.108 | 665 | 6623 (97.5%) | 74 | 0 |
| TC medium (11) | OOS | 4157 | 97 / 1014 | 3046 | +0.145 | 334 | 2868 (94.2%) | 82 | 47 |
| high52 (11) | IS | 1666 | 6 / 313 | 1347 | +0.051 | 201 | 1019 (75.6%) | 24 | 0 |
| high52 (11) | OOS | 854 | 5 / 158 | 691 | +0.167 | 80 | 401 (58.0%) | 23 | 15 |
| TC short (3) | IS | 1568 | 26 / 480 | 1062 | +0.030 | 120 | 596 (56.1%) | 15 | 0 |
| TC short (3) | OOS | 615 | 4 / 177 | 434 | +0.165 | 51 | 230 (53.0%) | 14 | 7 |
| RS medium (3) | IS | 4972 | 4 / 551 | 4417 | +0.187 | 787 | 4186 (94.8%) | 11 | 0 |
| RS medium (3) | OOS | 2717 | 6 / 277 | 2434 | +0.134 | 486 | 2297 (94.4%) | 9 | 66 |

A refused signal is one the funded replay would not fill at the next open: the open is at or below the stop, or the target is less than 1.5 times the remaining risk away. It is "not a candidate outcome" and is left out of every statistic.

## Primary and control statistics: trend_continuation.medium_swing (snapshot 11)

K1 is the pre-registered hypothesis. K2 (volume surge) and K3 (stop distance) are controls and carry no verdict.

| Key | Period | Sessions | Candidates | Day's mean, all candidates (R) | Top-2 mean (R) | Top-2 lift (R) | Bootstrap p | Random-2 lift p5 / p50 / p95 (R) | Share of the 1,000 random picks below the lift (%) | Rank IC | IC bootstrap p | Tercile mean, top / middle / bottom (R) | Tercile candidates |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| K1 | IS | 665 | 6623 | +0.137 | +0.119 | -0.0177 | 0.7126 | -0.051 / +0.000 / +0.046 | 28.1 | -0.0049 | 0.5752 | +0.100 / +0.101 / +0.114 | 2203 / 2217 / 2203 |
| K1 | OOS | 334 | 2868 | +0.070 | +0.029 | -0.0412 | 0.7497 | -0.067 / +0.001 / +0.072 | 15.5 | -0.0013 | 0.5127 | +0.079 / +0.146 / +0.225 | 945 / 978 / 945 |
| K2 | IS | 665 | 6623 | +0.137 | +0.139 | +0.0019 | 0.4697 | -0.051 / +0.000 / +0.046 | 52.5 | +0.0263 | 0.0406 | +0.089 / +0.081 / +0.145 | 2203 / 2217 / 2203 |
| K2 | OOS | 334 | 2868 | +0.070 | +0.070 | -0.0003 | 0.4997 | -0.067 / +0.001 / +0.072 | 48.5 | +0.0058 | 0.4133 | +0.155 / +0.145 / +0.151 | 945 / 978 / 945 |
| K3 | IS | 665 | 6623 | +0.137 | +0.113 | -0.0243 | 0.7328 | -0.051 / +0.000 / +0.046 | 20.4 | +0.0265 | 0.1035 | +0.076 / +0.119 / +0.120 | 2203 / 2217 / 2203 |
| K3 | OOS | 334 | 2868 | +0.070 | +0.049 | -0.0212 | 0.6424 | -0.067 / +0.001 / +0.072 | 29.0 | +0.0256 | 0.1976 | +0.124 / +0.170 / +0.155 | 945 / 978 / 945 |

How to read the columns. *Top-2 lift* is the mean over sessions of (mean outcome of the two highest-key candidates − mean outcome of all that session's candidates). *Bootstrap p* is one-sided, from resampling calendar months. *Random-2* is the same lift for 1,000 random two-a-day picks: it shows how far a pick with no information moves by luck. *Rank IC* is the within-day Spearman correlation between key and outcome, averaged over sessions. *Terciles* pool every candidate by its within-day third of the key.

## The other three approved books (descriptive, no verdict)

**high52 (11) — high52_breakout.medium_swing**

| Key | Period | Sessions | Candidates | Day's mean, all candidates (R) | Top-2 mean (R) | Top-2 lift (R) | Bootstrap p | Random-2 lift p5 / p50 / p95 (R) | Share of the 1,000 random picks below the lift (%) | Rank IC | IC bootstrap p | Tercile mean, top / middle / bottom (R) | Tercile candidates |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| K1 | IS | 201 | 1019 | +0.032 | +0.066 | +0.0337 | 0.2736 | -0.071 / +0.000 / +0.078 | 76.1 | +0.0112 | 0.4120 | +0.057 / +0.012 / -0.015 | 330 / 359 / 330 |
| K1 | OOS | 80 | 401 | +0.275 | +0.239 | -0.0355 | 0.7090 | -0.118 / +0.003 / +0.111 | 29.6 | -0.0158 | 0.5753 | +0.207 / +0.238 / +0.333 | 131 / 139 / 131 |
| K2 | IS | 201 | 1019 | +0.032 | +0.093 | +0.0607 | 0.0755 | -0.071 / +0.000 / +0.078 | 90.8 | +0.0840 | 0.0275 | +0.073 / -0.106 / +0.097 | 330 / 359 / 330 |
| K2 | OOS | 80 | 401 | +0.275 | +0.285 | +0.0106 | 0.4459 | -0.118 / +0.003 / +0.111 | 57.0 | -0.0310 | 0.6451 | +0.306 / +0.156 / +0.320 | 131 / 139 / 131 |
| K3 | IS | 201 | 1019 | +0.032 | +0.062 | +0.0293 | 0.2893 | -0.071 / +0.000 / +0.078 | 73.0 | +0.0268 | 0.3010 | +0.073 / +0.007 / -0.025 | 330 / 359 / 330 |
| K3 | OOS | 80 | 401 | +0.275 | +0.451 | +0.1767 | 0.0124 | -0.118 / +0.003 / +0.111 | 99.5 | +0.2084 | 0.0069 | +0.438 / +0.230 / +0.110 | 131 / 139 / 131 |

**TC short (3) — trend_continuation.short_swing**

| Key | Period | Sessions | Candidates | Day's mean, all candidates (R) | Top-2 mean (R) | Top-2 lift (R) | Bootstrap p | Random-2 lift p5 / p50 / p95 (R) | Share of the 1,000 random picks below the lift (%) | Rank IC | IC bootstrap p | Tercile mean, top / middle / bottom (R) | Tercile candidates |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| K1 | IS | 120 | 596 | -0.006 | -0.021 | -0.0148 | 0.6309 | -0.071 / -0.001 / +0.074 | 39.2 | -0.0622 | 0.8748 | +0.038 / -0.208 / +0.073 | 194 / 208 / 194 |
| K1 | OOS | 51 | 230 | +0.250 | +0.251 | +0.0012 | 0.4897 | -0.114 / +0.003 / +0.111 | 48.7 | -0.0859 | 0.8503 | +0.150 / +0.474 / +0.140 | 74 / 82 / 74 |
| K2 | IS | 120 | 596 | -0.006 | +0.064 | +0.0694 | 0.0517 | -0.071 / -0.001 / +0.074 | 94.0 | +0.0781 | 0.0760 | +0.143 / -0.137 / -0.108 | 194 / 208 / 194 |
| K2 | OOS | 51 | 230 | +0.250 | +0.169 | -0.0808 | 0.9095 | -0.114 / +0.003 / +0.111 | 11.6 | -0.0329 | 0.6220 | +0.126 / +0.262 / +0.399 | 74 / 82 / 74 |
| K3 | IS | 120 | 596 | -0.006 | +0.016 | +0.0222 | 0.3230 | -0.071 / -0.001 / +0.074 | 69.3 | -0.0234 | 0.6790 | +0.012 / -0.180 / +0.069 | 194 / 208 / 194 |
| K3 | OOS | 51 | 230 | +0.250 | +0.193 | -0.0565 | 0.7952 | -0.114 / +0.003 / +0.111 | 19.1 | -0.0949 | 0.8811 | +0.166 / +0.291 / +0.326 | 74 / 82 / 74 |

**RS medium (3) — relative_strength.medium_swing**

| Key | Period | Sessions | Candidates | Day's mean, all candidates (R) | Top-2 mean (R) | Top-2 lift (R) | Bootstrap p | Random-2 lift p5 / p50 / p95 (R) | Share of the 1,000 random picks below the lift (%) | Rank IC | IC bootstrap p | Tercile mean, top / middle / bottom (R) | Tercile candidates |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| K1 | IS | 787 | 4186 | +0.187 | +0.217 | +0.0302 | 0.2402 | -0.037 / +0.000 / +0.034 | 92.9 | +0.0243 | 0.2714 | +0.223 / +0.121 / +0.230 | 1377 / 1432 / 1377 |
| K1 | OOS | 486 | 2297 | +0.093 | +0.115 | +0.0219 | 0.3764 | -0.042 / +0.001 / +0.043 | 77.8 | -0.0431 | 0.8376 | +0.160 / +0.113 / +0.186 | 749 / 799 / 749 |
| K2 | IS | 787 | 4186 | +0.187 | +0.171 | -0.0154 | 0.7439 | -0.037 / +0.000 / +0.034 | 23.1 | -0.0073 | 0.6326 | +0.196 / +0.183 / +0.193 | 1377 / 1432 / 1377 |
| K2 | OOS | 486 | 2297 | +0.093 | +0.078 | -0.0155 | 0.6785 | -0.042 / +0.001 / +0.043 | 26.2 | -0.0066 | 0.5846 | +0.132 / +0.114 / +0.214 | 749 / 799 / 749 |
| K3 | IS | 787 | 4186 | +0.187 | +0.320 | +0.1331 | 0.0112 | -0.037 / +0.000 / +0.034 | 100.0 | +0.1278 | 0.0007 | +0.346 / +0.135 / +0.092 | 1377 / 1432 / 1377 |
| K3 | OOS | 486 | 2297 | +0.093 | +0.203 | +0.1093 | 0.0668 | -0.042 / +0.001 / +0.043 | 100.0 | +0.0492 | 0.1560 | +0.292 / +0.047 / +0.124 | 749 / 799 / 749 |

## Plain descriptive facts (no verdict)

### Signal sessions by number of candidates

| Book | Period | Signal sessions | 0 | 1 | 2 | 3 | 4 | 5 | 6-10 | 11-20 | 21-40 | 41+ |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| TC medium (11) | IS | 1289 | 516 | 47 | 61 | 68 | 53 | 73 | 258 | 172 | 29 | 12 |
| TC medium (11) | OOS | 894 | 445 | 52 | 63 | 56 | 66 | 39 | 106 | 46 | 14 | 7 |
| high52 (11) | IS | 1289 | 845 | 158 | 85 | 78 | 47 | 25 | 40 | 8 | 3 | 0 |
| high52 (11) | OOS | 894 | 605 | 128 | 81 | 36 | 14 | 6 | 21 | 2 | 1 | 0 |
| TC short (3) | IS | 1289 | 825 | 222 | 122 | 44 | 29 | 13 | 27 | 7 | 0 | 0 |
| TC short (3) | OOS | 894 | 683 | 116 | 44 | 23 | 12 | 6 | 9 | 1 | 0 | 0 |
| RS medium (3) | IS | 1289 | 360 | 53 | 89 | 121 | 155 | 163 | 344 | 4 | 0 | 0 |
| RS medium (3) | OOS | 894 | 328 | 23 | 57 | 113 | 137 | 101 | 135 | 0 | 0 | 0 |

Columns are the number of candidates with an outcome on a signal session. The share of candidates that sit on sessions with 3 or more is in the Candidates table above.

### Top-2 lift by calendar year of the signal session (K1)

| Book | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| TC medium (11) | -0.056 (182) | +0.027 (86) | -0.013 (139) | +0.097 (92) | -0.065 (163) | IS -0.093 (3); OOS none | -0.035 (136) | -0.071 (134) | +0.008 (64) |
| high52 (11) | -0.214 (20) | -0.111 (33) | +0.105 (28) | +0.029 (44) | +0.140 (75) | IS -0.003 (1); OOS none | -0.038 (29) | -0.129 (39) | +0.274 (12) |
| TC short (3) | +0.005 (33) | +0.049 (13) | -0.074 (32) | +0.001 (14) | -0.008 (28) | IS none; OOS none | -0.089 (24) | +0.109 (17) | +0.035 (10) |
| RS medium (3) | -0.068 (64) | -0.057 (191) | +0.206 (128) | +0.104 (149) | -0.031 (229) | IS +0.162 (26); OOS +0.575 (19) | +0.082 (163) | -0.081 (225) | +0.060 (79) |

Lift in R, with the number of sessions in brackets. 2022 holds both periods (IS is entered on or before 2022-02-10); "none" means no session with 3 or more candidates, which is what a risk-off regime gate produces.

### Against the two alphabetically first candidates (what the library order admits)

| Book | Period | Sessions | Day's mean, all candidates (R) | Mean of the alphabetical two (R) | Alphabetical two − day's mean (R) | K1 top 2 − alphabetical two (R) | K2 top 2 − alphabetical two (R) | K3 top 2 − alphabetical two (R) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| TC medium (11) | IS | 665 | +0.137 | +0.173 | +0.036 | -0.054 | -0.034 | -0.060 |
| TC medium (11) | OOS | 334 | +0.070 | +0.128 | +0.058 | -0.099 | -0.058 | -0.079 |
| high52 (11) | IS | 201 | +0.032 | +0.166 | +0.134 | -0.100 | -0.073 | -0.104 |
| high52 (11) | OOS | 80 | +0.275 | +0.265 | -0.010 | -0.025 | +0.021 | +0.187 |
| TC short (3) | IS | 120 | -0.006 | +0.000 | +0.006 | -0.021 | +0.063 | +0.016 |
| TC short (3) | OOS | 51 | +0.250 | +0.337 | +0.087 | -0.086 | -0.168 | -0.143 |
| RS medium (3) | IS | 787 | +0.187 | +0.240 | +0.054 | -0.023 | -0.069 | +0.080 |
| RS medium (3) | OOS | 486 | +0.093 | +0.142 | +0.049 | -0.027 | -0.065 | +0.060 |

Here the day's mean is replaced by the mean of the two candidates the current alphabetical order would offer first. Means over the same sessions.

### One position per symbol: signals inside an earlier candidate's holding window

The library holds at most one position per symbol, so an account does not see a signal while it holds that symbol. The isolated table deliberately includes every signal. The table counts the signals that fall inside the holding window of an earlier candidate, and repeats the primary statistic on the rest.

| Book | Period | Signals | Inside the window of an earlier candidate that a one-position account would hold | Inside the window of any earlier candidate | Candidates kept | Sessions with 3 or more kept | Top-2 lift K1, kept only (R) | Bootstrap p | Rank IC K1, kept only | Top-2 lift K1, all candidates (R) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| TC medium (11) | IS | 9318 | 3964 (42.5%) | 4532 (48.6%) | 3893 | 506 | +0.0578 | 0.0384 | +0.0286 | -0.0177 |
| TC medium (11) | OOS | 4157 | 1660 (39.9%) | 1914 (46.0%) | 1808 | 224 | -0.0338 | 0.7546 | -0.0155 | -0.0412 |
| high52 (11) | IS | 1666 | 508 (30.5%) | 584 (35.1%) | 923 | 127 | +0.0356 | 0.2887 | +0.0345 | +0.0337 |
| high52 (11) | OOS | 854 | 253 (29.6%) | 291 (34.1%) | 485 | 53 | +0.0886 | 0.1392 | +0.1345 | -0.0355 |
| TC short (3) | IS | 1568 | 518 (33.0%) | 586 (37.4%) | 714 | 77 | +0.0008 | 0.4985 | -0.0712 | -0.0148 |
| TC short (3) | OOS | 615 | 195 (31.7%) | 224 (36.4%) | 295 | 25 | +0.0178 | 0.4026 | -0.1647 | +0.0012 |
| RS medium (3) | IS | 4972 | 4545 (91.4%) | 4787 (96.3%) | 380 | 20 | -0.1207 | 0.8354 | -0.1342 | +0.0302 |
| RS medium (3) | OOS | 2717 | 2487 (91.5%) | 2620 (96.4%) | 197 | 8 | +0.0755 | 0.3116 | +0.2196 | +0.0219 |

"Kept" is descriptive and carries no verdict: the candidates a one-position-per-symbol account that takes every signal it sees would be offered (see "Non-overlapping candidates" under Deviations and clarifications). The pre-registered statistic is the one on all candidates.

## Expectations stated in advance, against the outcome

| Expectation in the pre-registration | Outcome |
|---|---|
| Uncertain; R3-C points to a positive lift for this book | Top-2 lift -0.0177 R in IS and -0.0412 R in OOS; rank IC -0.0049 and -0.0013. |
| A small positive lift that does not clear the bar is the most likely outcome | Did not clear the bar, and the lift is not positive: OOS p 0.7497; OOS lift above 15.5% of the random picks (95th percentile +0.0723 R). |

## Deviations and clarifications

1. **Nothing pre-registered was changed; three descriptive tables were added.** No key, threshold, horizon, book, pre-registered statistic or decision rule was added, dropped or changed after results were seen, and the verdict uses only the pre-registered statistics. Three tables go beyond the statistics the pre-registration lists (top-2 lift, rank IC, rank buckets, random-2 band): the one-position "kept" subset (K1 top-2 lift, bootstrap p and rank IC, 8 cells), the comparison with the two alphabetically first candidates, and the top-2 lift by calendar year. They were in the script from its first run, are descriptive and carry no verdict. Their p-values are unadjusted: the kept-subset IS cell on trend_continuation.medium is one of 8 such cells and is not a finding. The other points below are choices the pre-registration left open; each was fixed in the script before any outcome was computed. History of this file: after the first complete run, three descriptive counts were added to the report (sessions with a tied key, the most frequent top-2 symbol, and where the alphabetical pick sits among the random picks) and its wording was edited. The whole pipeline was then run again from that script and reproduced every number of the first run exactly (candidate tables and random-2 bands byte for byte; `summary.json` differs only in the added counts, the timestamps and the script hash). After review the report text and one git check were changed and only the report stage was run again (see "Review repairs" below); no number changed.
2. **Candidates.** The signal table is R3-C's `build_signal_table`, rebuilt from the database: every long signal of the version's rule on symbols with complete bars (147 of 150 on snapshot 11, 23 of 24 on snapshot 3), signal sessions 2016-12-28 to 2025-09-04. Dates, symbols, bars, signals, keys and dividend rows are identical to the table R3-C saved and used for its grid.
3. **Fill validity.** The funded replay's own two checks at the next open, at base costs: the fill (open plus 5.5 bps, rounded up to the cent) must be above the stop, and (target − fill) ÷ (fill − stop) must be at least 1.5. Because the target is two planned risks above the signal close, the second check refuses a signal whose open gaps up by more than about 0.2 planned risks. Refusals for size (risk budget, symbol, sector, gross, open-risk, cash, volume, daily cap) depend on the account and are not part of the isolated outcome; the pre-registration counts a signal "whether or not a funded account could have taken it".
4. **Outcome.** (exit fill − entry fill) ÷ (signal-day close − stop). Fills carry the base cost of 5.5 bps a side and are rounded to the cent exactly as the replay rounds them (buys up, sells down); base costs carry no commission. Dividends are not part of the outcome. The bars are split-adjusted only, so an ex-dividend drop counts against the holder here, as it does in the replay's per-share result; the replay credits cash dividends to the account separately, and only for the symbols that have dividend rows (22 of 147 on snapshot 11, 22 of 23 on snapshot 3; R3-C results, point 17).
5. **Exits.** The funded replay's rules, in its order: from the session after entry, an open at or below the stop exits at that open; then low at or below the stop exits at the stop; then high at or above the target exits at the target; then the time stop exits at the close of the 40th session after entry (10th for trend_continuation.short); then the last session of the data exits at its close. These differ slightly from the R-engine used for promotion (which fills a gap through the target at the open, refuses nothing at the open and measures risk from the fill).
6. **IS and OOS, and the two period ends.** A candidate belongs to the period of its entry session. An IS-entered candidate runs to its own exit even when that falls after 2022-02-10 (86 candidates across the four books; 10 on trend_continuation.medium), so its outcome is the rule's, not the replay window's. A candidate still open on 2025-09-05 is closed at that session's close, as the replay does, because no later bar may be loaded (135 candidates across the four books; 47 on trend_continuation.medium). They are kept in the statistics.
7. **Identity check.** Run on R3-C's local replay and, in the same pass, on a fresh library `run_funded_replay` of each cell (identical). Trades the IS replay liquidated at 2022-02-10 are compared with the isolated outcome on that horizon (see the check above); all others with the candidate table itself.
8. **Sessions with at least 3 candidates.** Counted on candidates that have an outcome; a refused signal does not count towards the 3. Which signals are refused is known only at the next open, which is also when the replay decides. Counting sessions by signals instead would add only sessions with one or two outcomes, where the top two are all the candidates and the lift is exactly zero; that reading could shrink the mean lift towards zero but could not turn it positive.
9. **Key order and ties.** R3-C's order: highest key first; ties broken by symbol, alphabetical; a missing key ranks last, in symbol order. This file's order was checked against R3-C's own order function on all 8,172 session-and-key orders. 0 qualifying sessions hold two candidates with the same finite key value (all books and keys), so the tie rule matters only where K1 is missing. K1 needs 63 earlier sessions, so on the first 10 qualifying sessions of trend_continuation.medium (2017-01-03 to 2017-01-17, all in IS) every candidate's K1 is missing and the "K1 order" is the symbol order. They are kept, because the pre-registration says every session with at least 3 candidates. Leaving them out would give an IS top-2 lift of -0.0166 R and an IS rank IC of -0.0043 (with them: -0.0177 R and -0.0049); this line is disclosure, not a study statistic, and OOS is not affected.
10. **No look-ahead in the keys.** R3-C's assertions and poison test ran again inside `build_signal_table`. In addition all 25,867 keys were recomputed three ways and matched: from prefixes that end on the signal session; with every bar after the signal session set to NaN; and from the formulas written out on raw arrays (K1 = close ÷ close 63 sessions earlier − 1, minus the same for SPY; K2 = signal-day volume ÷ mean of the 19 sessions before it; K3 = (close − stop) ÷ close).
11. **Top-2 lift.** Per session: mean outcome of the first two candidates in key order minus the mean outcome of all that session's candidates (the two included). The statistic is the plain mean over sessions, each session weighted equally.
12. **Rank IC.** Spearman: the correlation between key rank (from the order above) and outcome rank, tied outcomes sharing their average rank; mean over sessions. A session in which every outcome is identical has no correlation and would be left out of the IC mean (0 such sessions).
13. **Terciles.** The candidate in position r of n in key order (r = 0 is the highest key) goes to bucket floor(3 × (r + 0.5) ÷ n). With 3 candidates that is one each; with 4 it is 1 / 2 / 1; with 5 it is 2 / 1 / 2. The table pools all candidates of a bucket over sessions, so busy sessions weigh more; that is why the tercile means do not average to the day's-mean column, which weighs every session equally.
14. **Random-2 band.** Ranking i (i = 0..999) gives each (session, symbol) one uniform priority from `numpy.random.default_rng(20261110 + i)` on the full calendar × sorted-symbols grid, read on the entry session's row, lowest first: the construction of R3-C's random orders, so rankings 0 to 39 are R3-C's 40 orders (checked against R3-C's order function). Percentiles use numpy's linear interpolation; "above" is strict. One set of 1,000 rankings serves all three keys and both periods.
15. **Bootstrap.** Blocks are the calendar months (of the signal session) that hold at least one qualifying session of the period: 50 in IS and 27 in OOS for trend_continuation.medium (the rule is gated off in risk-off months, so not every month has one). Each of the 10,000 resamples draws that many months with replacement (`numpy.random.default_rng(20261110)`) and takes the mean over the sessions drawn. The null is the resampled mean minus the observed mean; p is the share of null draws at or above the observed mean, with the usual +1 correction. This is the convention of R3's entry-execution study.
16. **Non-overlapping candidates (descriptive).** Per symbol in date order, a signal is "kept" when the symbol would not be held at that close by an account that takes every signal it sees: its signal session is on or after the exit session of the last kept candidate. The second count in that table uses the stricter reading (inside the holding window of any earlier candidate, kept or not). A refused signal opens no window.
17. **Bars and dividends.** Bars come through R3-C's `load_book` (`funded_replay_report._load`, source `massive` only, quality-gated), not `PriceSeries.load`; the last bar loaded is 2025-09-05. The identity-check replays are R3-C's and need its dividend rows, so they inherit point 19 of the R3-C results: the library dividend loader reads split rows with no date bound for the 5 symbols that have a later split. No price after 2025-09-05 is read, and no dividend or split enters a candidate outcome.
18. **One hypothesis.** Only trend_continuation.medium / K1 carries a verdict. K2, K3 and the other three books are shown with the same tables. On the 23-symbol snapshot-3 books the same few names fill the top two again and again, and for relative_strength.medium K1 is the quantity the entry rule already thresholds.
19. **Timing.** Both complete runs of the study finished by 12:10 UTC on 2026-11-10, inside the round's 19:00 UTC cut-off. The verification script was started at 12:10 UTC. The host then appears to have been suspended: the script finished at 22:59 UTC having used 57 seconds of processor time in 10 hours 49 minutes, and how much of that fell after the host resumed is not known. So the verification, which only compares, completed after the cut-off; no study number depends on it. No study computation was started after the cut-off. After it came file comparisons, the reviewers' own checks, and the report-only run described in the next point.
20. **Review repairs.** After adversarial review, and after the cut-off, the script was changed in two ways and its report stage alone was run again (23:11 UTC); that stage reads `summary.json` and `identity.json`, writes this file and computes no statistic. (a) The check that the imported R3-C script equals the committed blob now fails closed when git is unavailable; in the recorded run git worked and the blobs were equal, so the recorded flag is unaffected. (b) Report text: the Answer counts the four pre-registered conditions (the script records them as six flags and the first report said "0 of the 6"); the sentence "the rule has an edge" was replaced by a plain description; the added descriptive tables are declared in point 1 and next to the kept-subset number; and the hand edits made to this file after the second run (the section "Independent verification", the last sentences of "Outcome" and "Sessions with at least 3 candidates", "Timing") now come from the script, so this file is again what the script writes. The script as it ran and the hand-edited file are kept beside the raw outputs under `as_run/`.

## What this does and does not license

As pre-registered: the data are the same development sessions R3-C used, so a pass would be a robustness result on an existing candidate, not independent confirmation; only prospective evidence is clean. The rule did not pass, so nothing here supports building ranked admission on K1 for this book. Nothing here changes the operating scan, ledger, risk limits or any frozen study.

## Reproduce

```sh
cd <scratch>/r3            # a directory with no .env
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=<worktree>/src:<worktree>/scripts MARKET_DATA_PROVIDER=massive \
SIGNALFORGE_DATA_DIR=<scratch>/r3/db \
DATABASE_URL="sqlite+pysqlite:///file:<scratch>/r3/db/signalforge.sqlite?mode=ro&uri=true" \
<venv>/bin/python <worktree>/scripts/r4/candidate_ranking.py all        # prepare, analyze, report
<venv>/bin/python <worktree>/scripts/r4/candidate_ranking_verify.py     # independent recomputation from the saved tables and the database
```

Raw outputs (not committed), under `<scratch>/r3/out/r4-ranking/`: `identity.json`, `candidates_<book>.csv` (one row per signal), `sessions_<book>.csv` and `sessions_nonoverlap_<book>.csv` (one row per session with 3 or more candidates), `random_band_<book>.csv` (1,000 rows), `summary.json`, `verify.log` and the stage logs. Script SHA-256 at the run: `fc3d007d5b6f61ac…`; R3-C script imported unmodified (SHA-256 `1a9b3cf9981e5fac…`, the same blob as the committed file). The script was changed after that run (see "Review repairs"); it now has SHA-256 `86649a9feb02c3c7…`, and the script as it ran is kept as `as_run/candidate_ranking.py` beside the raw outputs.

Research signal only — no order was placed.
