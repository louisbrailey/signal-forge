# Results — R3-C: admission order, trim-to-budget and the luck band in a funded account (2026-11-10)

Pre-registration: `docs/research/PREREGISTRATION_r3_capacity_admission_2026-11-10.md` (commit
9bc9d24, written before any replay). Run on a private read-only copy of the operating database;
development window only (bars end 2025-09-05). Descriptive research: no sealed look, no
operating-database write, no change to any frozen study, risk limit or approved version. One
departure from the letter of the window is disclosed in point 19 under "Deviations and
clarifications": the library dividend loader reads split rows dated after the window for 5
symbols; no price after 2025-09-05 is read.

The two periods are IS (2016-10-17..2022-02-10) and OOS (2022-02-11..2025-09-05), each replayed
from a fresh $30,000. Nothing in this study is fitted, so they are two separate stretches of
already-observed development data.

## Answer

**Which same-day signals get admitted moves a capacity-bound book more than anything else
tested.** With nothing changed except the order in which same-day candidates are offered, 40
random orders of the 150-symbol trend_continuation.medium book span about 20 points of net
return on the operating caps (+1.1% to +21.1% in IS, −1.7% to +19.0% in OOS; 5th to 95th
percentile) and 22 to 29 points on the maximum caps.

**By the pre-registered rules there are four admission candidates, all on the operating caps
and all fragile.** Trim-to-budget qualifies for relative_strength.medium (26 of 40 paired wins
in IS, exactly the threshold, and 34 of 40 in OOS). Relative-strength
ordering (K1) qualifies for trend_continuation.medium with and without trim, and for
relative_strength.medium without trim. Volume-surge (K2) and stop-distance (K3) ordering
qualify nowhere, and trim-to-budget fails for the other three books. A 40-order win count
carries about 3 wins of seed noise, so the IS pass on 26 cannot be told apart from the IS
fails on 24 (high52) and 25 (trend_continuation.short) on the same caps.

**None of the four holds on the maximum caps, none keeps its standing in both periods at
stress costs, and no run of any arm earned as much as SPY** (+130.1% total return in IS and
+50.6% in OOS, against a best single run of +53.3% and +29.2%).

## The four candidates, and what the same grid says about them

"Candidate" is the pre-registered word for an arm that passed its rule at base costs. The last
two columns are cells of the same pre-registered grid, not new runs.

| Candidate (book / cap set / arm) | IS 2016-10-17..2022-02-10 | OOS 2022-02-11..2025-09-05 | Same arm on the maximum caps | Same arm at stress costs |
|---|---|---|---|---|
| RS medium / operating / trim-to-budget | 26 of 40 paired wins, median +2.44 pts | 34 of 40, median +2.94 pts | IS fails (14 of 40), OOS passes (29 of 40) | IS 16 of 40 (median −1.38 pts), OOS 32 of 40 (+3.05 pts) |
| TC medium / operating / K1, reject | +32.13% vs random p90 +18.41%; above all 40 random orders | +15.77% vs +13.83%; above 36 of 40 | IS 72.5th percentile, OOS 40.0th: fails both | IS above all 40; OOS 47.5th percentile (−0.23%) |
| TC medium / operating / K1, trim | +28.50% vs +20.59%; above all 40 on net return, 39 on Sharpe | +14.36% vs +11.76%; above 38 of 40 | IS passes (100.0th), OOS 30.0th: fails | IS above all 40; OOS 85.0th percentile (+5.03%) |
| RS medium / operating / K1, reject | +12.66% vs +11.45%; above all 40 | +6.85% vs +6.49%; above 36 of 40 on net return, 37 on Sharpe | IS 70.0th, OOS passes (97.5th): fails | IS 47.5th percentile (+4.44%); OOS above the stress p90 |

How to read this:

- **The luck band is the yardstick.** A single funded replay is one draw from it. The
  alphabetical order that the library's funded replay uses sits between the 20th and 72.5th
  percentile of the random orders in IS, but at the 92.5th to 100th percentile in five of the
  eight OOS cells (table below). Configurations should be compared only on differences larger
  than the band, or on a median over orders.
- **K1 is the only ordering that repeats.** Counting single periods, a key was above the random
  90th percentile on both measures in 18 of 96 cells: K1 in 9 of 32, K2 in 4 of 32, K3 in 5 of
  32. A random order would do so more often than one time in ten, about one in eight,
  because the threshold itself rests on only 40 orders (point 10 under "Deviations and
  clarifications"). That is about 4 chance passes per key in 32 cells, so K2 and K3 are at
  chance and K1 is at about twice chance. All nine K1 passes sit in trend_continuation.medium
  and relative_strength.medium; for relative_strength.medium K1 is the same quantity the
  entry rule already thresholds. Three candidates in 48 cells compares with about half a cell
  expected by the pre-registration's arithmetic, and with 0.6 to 0.8 once the noise in a
  40-order threshold is allowed for; two of the three are the same key on the same book.
- **Trim-to-budget takes more entries without a reliable gain.** It admits 6% to 65% more
  entries (for example a median of 598 against 399.5 for trend_continuation.medium on the
  operating caps in IS). The median paired change in net return runs from −1.96 to +2.94 points
  and is positive in 10 of 16 cells. Median max drawdown never rises by more than 1.27 points,
  so the drawdown condition passes everywhere; the sign test is what fails. A win count over
  40 pairs has a standard error of about 3 wins, so the IS counts of 24, 25 and 26 on the
  operating caps cannot be told apart, and which of them reaches the threshold of 26 depends on
  the seed set (point 12).
- **Against SPY.** None of the 1,376 base-cost runs reached SPY's net return in its period.
  Some runs have a higher daily Sharpe than SPY (42 of 688 in IS, 211 of 688 in OOS), with a
  mean of 11% to 45% of equity invested. The comparison is not like for like on dividends:
  SPY is a full total return, while the books are credited dividends only for the 22 symbols
  that have dividend rows in the database (22 of the 147 replayed symbols on snapshot 11, 22
  of 23 on snapshot 3). That understates the snapshot-11 books by a few points at most
  (point 17); the best single run is 77 points behind SPY in IS and 21 in OOS.

## What was run

- 1,376 base-cost replays: 4 books × 2 cap sets × 2 periods × (40 random orders × reject and
  trim + K1, K2, K3 × reject and trim). Nothing was cut; all 40 seeds ran in every cell.
- 326 stress-cost replays, for the final table only: the qualifying arms and the 40 random
  orders they are judged against.
- Identity check first: 16 of 16 cells identical to the library (below).
- Three worker processes; the whole pipeline takes about one minute end to end. After the
  runs the script was reformatted for lint with no change in behaviour; a complete re-run of
  the reformatted script into a separate folder reproduced every row, verdict and table
  exactly.
- After adversarial review the wording of this file was corrected (point 20), two
  comments were added to the study script (the parsed program is identical) and one data
  check was added to the verification script, which was run again. The grid was not re-run
  and no arm, seed, run, table or verdict changed.

## Identity check (alphabetical order, outright rejection, base costs)

| Book | Cap set | Period | Fills (library / local) | Final equity library $ | Final equity local $ | Fills identical | Marks identical | Decisions identical | Passed |
|---|---|---|---:|---:|---:|---|---|---|---|
| TC medium (11) | operating | IS | 808 / 808 | 32919.40 | 32919.40 | yes | yes | yes | yes |
| TC medium (11) | operating | OOS | 418 / 418 | 35583.17 | 35583.17 | yes | yes | yes | yes |
| TC medium (11) | maxima | IS | 1398 / 1398 | 36376.58 | 36376.58 | yes | yes | yes | yes |
| TC medium (11) | maxima | OOS | 770 / 770 | 37352.29 | 37352.29 | yes | yes | yes | yes |
| high52 (11) | operating | IS | 246 / 246 | 33101.32 | 33101.32 | yes | yes | yes | yes |
| high52 (11) | operating | OOS | 180 / 180 | 29077.22 | 29077.22 | yes | yes | yes | yes |
| high52 (11) | maxima | IS | 456 / 456 | 33953.28 | 33953.28 | yes | yes | yes | yes |
| high52 (11) | maxima | OOS | 304 / 304 | 29689.09 | 29689.09 | yes | yes | yes | yes |
| TC short (3) | operating | IS | 876 / 876 | 34737.90 | 34737.90 | yes | yes | yes | yes |
| TC short (3) | operating | OOS | 390 / 390 | 33544.47 | 33544.47 | yes | yes | yes | yes |
| TC short (3) | maxima | IS | 1210 / 1210 | 34156.78 | 34156.78 | yes | yes | yes | yes |
| TC short (3) | maxima | OOS | 514 / 514 | 34431.58 | 34431.58 | yes | yes | yes | yes |
| RS medium (3) | operating | IS | 290 / 290 | 32744.53 | 32744.53 | yes | yes | yes | yes |
| RS medium (3) | operating | OOS | 164 / 164 | 33383.53 | 33383.53 | yes | yes | yes | yes |
| RS medium (3) | maxima | IS | 472 / 472 | 33364.54 | 33364.54 | yes | yes | yes | yes |
| RS medium (3) | maxima | OOS | 282 / 282 | 33195.80 | 33195.80 | yes | yes | yes | yes |

## Luck band: 40 random same-day orders, outright rejection, base costs

| Book | Cap set | Period | Net % p5 | Net % p50 | Net % p95 | p95 - p5 (pts) | Sharpe p5 | Sharpe p50 | Sharpe p95 | Median CAGR % | Median max DD % | Median exposure % | Median entries / signals | Alphabetical order net % (percentile in the 40) | SPY total return % |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| TC medium (11) | operating | IS | +1.12 | +10.37 | +21.08 | 19.96 | 0.07 | 0.46 | 0.85 | +1.87 | 7.32 | 23.8 | 400 / 9318 (4.3%) | +9.73 (37.5) | +130.13 |
| TC medium (11) | operating | OOS | -1.71 | +6.28 | +19.00 | 20.71 | -0.10 | 0.42 | 1.17 | +1.72 | 5.18 | 17.8 | 216 / 4157 (5.2%) | +18.61 (92.5) | +50.60 |
| TC medium (11) | maxima | IS | +13.15 | +28.06 | +42.58 | 29.43 | 0.36 | 0.68 | 0.96 | +4.76 | 10.65 | 44.7 | 730 / 9318 (7.8%) | +21.26 (20.0) | +130.13 |
| TC medium (11) | maxima | OOS | +4.33 | +11.75 | +26.26 | 21.93 | 0.21 | 0.48 | 0.93 | +3.16 | 8.20 | 33.4 | 395 / 4157 (9.5%) | +24.51 (92.5) | +50.60 |
| high52 (11) | operating | IS | +2.46 | +6.93 | +15.98 | 13.52 | 0.17 | 0.45 | 0.90 | +1.27 | 5.12 | 12.5 | 135 / 1666 (8.1%) | +10.34 (72.5) | +130.13 |
| high52 (11) | operating | OOS | -4.27 | -1.67 | +2.29 | 6.56 | -0.37 | -0.13 | 0.22 | -0.47 | 4.57 | 12.5 | 90 / 854 (10.6%) | -3.08 (22.5) | +50.60 |
| high52 (11) | maxima | IS | +5.14 | +11.42 | +19.43 | 14.29 | 0.22 | 0.44 | 0.71 | +2.05 | 8.24 | 22.2 | 240 / 1666 (14.4%) | +13.18 (65.0) | +130.13 |
| high52 (11) | maxima | OOS | -3.60 | +2.40 | +6.55 | 10.14 | -0.18 | 0.16 | 0.40 | +0.67 | 6.84 | 22.4 | 147 / 854 (17.2%) | -1.04 (25.0) | +50.60 |
| TC short (3) | operating | IS | +10.86 | +15.28 | +19.34 | 8.48 | 0.61 | 0.86 | 1.07 | +2.71 | 5.69 | 17.8 | 436 / 1568 (27.8%) | +15.79 (55.0) | +130.13 |
| TC short (3) | operating | OOS | +7.57 | +9.29 | +10.79 | 3.22 | 0.68 | 0.84 | 0.97 | +2.52 | 2.73 | 11.7 | 197 / 615 (32.0%) | +11.81 (100.0) | +50.60 |
| TC short (3) | maxima | IS | +11.44 | +14.40 | +17.70 | 6.26 | 0.48 | 0.58 | 0.70 | +2.56 | 8.53 | 24.4 | 606 / 1568 (38.6%) | +13.86 (37.5) | +130.13 |
| TC short (3) | maxima | OOS | +11.93 | +13.73 | +14.51 | 2.58 | 0.88 | 0.99 | 1.06 | +3.67 | 4.21 | 15.2 | 260 / 615 (42.2%) | +14.77 (95.0) | +50.60 |
| RS medium (3) | operating | IS | +1.40 | +6.94 | +11.75 | 10.36 | 0.09 | 0.34 | 0.55 | +1.27 | 8.42 | 16.4 | 148 / 4972 (3.0%) | +9.15 (62.5) | +130.13 |
| RS medium (3) | operating | OOS | -0.39 | +3.65 | +8.88 | 9.27 | -0.01 | 0.30 | 0.66 | +1.01 | 6.77 | 15.5 | 92 / 2717 (3.4%) | +11.28 (100.0) | +50.60 |
| RS medium (3) | maxima | IS | +8.34 | +13.37 | +18.01 | 9.67 | 0.28 | 0.43 | 0.55 | +2.39 | 11.67 | 28.4 | 233 / 4972 (4.7%) | +11.22 (30.0) | +130.13 |
| RS medium (3) | maxima | OOS | +6.00 | +10.87 | +15.04 | 9.04 | 0.34 | 0.59 | 0.77 | +2.94 | 8.98 | 25.5 | 146 / 2717 (5.4%) | +10.65 (47.5) | +50.60 |

## Trim-to-budget vs outright rejection: the same 40 orders, paired, base costs

| Book | Cap set | Period | Trim wins / 40 | Losses | Ties | Median diff (pts) | Net % p50 reject | Net % p50 trim | Median max DD reject % | Median max DD trim % | DD diff (pts) | Median entries trim | Median entries admitted by a trim | Sign test >= 26 | DD <= +2 | Period pass |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| TC medium (11) | operating | IS | 21 | 19 | 0 | +0.86 | +10.37 | +11.61 | 7.32 | 7.11 | -0.21 | 598 | 346 | no | yes | fail |
| TC medium (11) | operating | OOS | 18 | 22 | 0 | -1.20 | +6.28 | +5.86 | 5.18 | 5.34 | +0.16 | 328 | 191 | no | yes | fail |
| TC medium (11) | maxima | IS | 18 | 22 | 0 | -1.67 | +28.06 | +25.59 | 10.65 | 10.67 | +0.02 | 1163 | 667 | no | yes | fail |
| TC medium (11) | maxima | OOS | 18 | 22 | 0 | -0.55 | +11.75 | +13.57 | 8.20 | 8.06 | -0.14 | 597 | 310 | no | yes | fail |
| high52 (11) | operating | IS | 24 | 16 | 0 | +1.09 | +6.93 | +8.16 | 5.12 | 5.40 | +0.28 | 216 | 124 | no | yes | fail |
| high52 (11) | operating | OOS | 33 | 7 | 0 | +2.48 | -1.67 | +0.96 | 4.57 | 3.71 | -0.86 | 140 | 84 | yes | yes | PASS |
| high52 (11) | maxima | IS | 31 | 9 | 0 | +2.70 | +11.42 | +12.95 | 8.24 | 8.15 | -0.09 | 345 | 166 | yes | yes | PASS |
| high52 (11) | maxima | OOS | 22 | 18 | 0 | +0.21 | +2.40 | +2.06 | 6.84 | 6.52 | -0.31 | 218 | 104 | no | yes | fail |
| TC short (3) | operating | IS | 25 | 15 | 0 | +0.57 | +15.28 | +16.13 | 5.69 | 5.61 | -0.09 | 487 | 79 | no | yes | fail |
| TC short (3) | operating | OOS | 10 | 30 | 0 | -0.45 | +9.29 | +8.57 | 2.73 | 2.87 | +0.15 | 217 | 30 | no | yes | fail |
| TC short (3) | maxima | IS | 33 | 7 | 0 | +1.01 | +14.40 | +15.79 | 8.53 | 8.52 | -0.01 | 658 | 69 | yes | yes | PASS |
| TC short (3) | maxima | OOS | 3 | 37 | 0 | -0.82 | +13.73 | +12.92 | 4.21 | 4.26 | +0.05 | 276 | 18 | no | yes | fail |
| RS medium (3) | operating | IS | 26 | 14 | 0 | +2.44 | +6.94 | +8.05 | 8.42 | 7.78 | -0.64 | 244 | 162 | yes | yes | PASS |
| RS medium (3) | operating | OOS | 34 | 6 | 0 | +2.94 | +3.65 | +7.45 | 6.77 | 6.12 | -0.65 | 150 | 94 | yes | yes | PASS |
| RS medium (3) | maxima | IS | 14 | 26 | 0 | -1.96 | +13.37 | +11.41 | 11.67 | 12.94 | +1.27 | 321 | 152 | no | yes | fail |
| RS medium (3) | maxima | OOS | 29 | 11 | 0 | +1.43 | +10.87 | +12.09 | 8.98 | 8.76 | -0.21 | 181 | 66 | yes | yes | PASS |

| Book | Cap set | IS | OOS | Trim-to-budget admission candidate |
|---|---|---|---|---|
| TC medium (11) | operating | fail | fail | no |
| TC medium (11) | maxima | fail | fail | no |
| high52 (11) | operating | fail | pass | no |
| high52 (11) | maxima | pass | fail | no |
| TC short (3) | operating | fail | fail | no |
| TC short (3) | maxima | pass | fail | no |
| RS medium (3) | operating | pass | pass | YES |
| RS medium (3) | maxima | fail | pass | no |

## Luck band with trim-to-budget (the same 40 orders), base costs

| Book | Cap set | Period | Net % p5 | Net % p50 | Net % p95 | Sharpe p5 | Sharpe p50 | Sharpe p95 | Median CAGR % | Median max DD % | Median exposure % | Median entries / signals |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| TC medium (11) | operating | IS | +3.43 | +11.61 | +22.55 | 0.18 | 0.51 | 0.92 | +2.09 | 7.11 | 22.7 | 598 / 9318 (6.4%) |
| TC medium (11) | operating | OOS | -2.39 | +5.86 | +12.25 | -0.16 | 0.40 | 0.81 | +1.61 | 5.34 | 17.3 | 328 / 4157 (7.9%) |
| TC medium (11) | maxima | IS | +15.07 | +25.59 | +41.64 | 0.39 | 0.64 | 0.94 | +4.38 | 10.67 | 44.2 | 1163 / 9318 (12.5%) |
| TC medium (11) | maxima | OOS | +6.24 | +13.57 | +21.95 | 0.28 | 0.54 | 0.83 | +3.63 | 8.06 | 33.2 | 597 / 4157 (14.4%) |
| high52 (11) | operating | IS | +3.81 | +8.16 | +16.46 | 0.26 | 0.51 | 1.02 | +1.49 | 5.40 | 12.5 | 216 / 1666 (12.9%) |
| high52 (11) | operating | OOS | -2.01 | +0.96 | +5.72 | -0.15 | 0.10 | 0.51 | +0.27 | 3.71 | 13.1 | 140 / 854 (16.4%) |
| high52 (11) | maxima | IS | +8.41 | +12.95 | +20.35 | 0.34 | 0.51 | 0.75 | +2.32 | 8.15 | 22.7 | 345 / 1666 (20.7%) |
| high52 (11) | maxima | OOS | -2.20 | +2.06 | +6.42 | -0.10 | 0.14 | 0.38 | +0.57 | 6.52 | 22.8 | 218 / 854 (25.6%) |
| TC short (3) | operating | IS | +11.30 | +16.13 | +19.10 | 0.64 | 0.89 | 1.03 | +2.85 | 5.61 | 18.2 | 487 / 1568 (31.1%) |
| TC short (3) | operating | OOS | +7.12 | +8.57 | +10.64 | 0.63 | 0.76 | 0.92 | +2.33 | 2.87 | 12.1 | 217 / 615 (35.3%) |
| TC short (3) | maxima | IS | +13.87 | +15.79 | +17.93 | 0.55 | 0.61 | 0.69 | +2.80 | 8.52 | 25.0 | 658 / 1568 (42.0%) |
| TC short (3) | maxima | OOS | +11.88 | +12.92 | +13.81 | 0.86 | 0.93 | 1.00 | +3.46 | 4.26 | 15.4 | 276 / 615 (44.9%) |
| RS medium (3) | operating | IS | +3.67 | +8.05 | +14.16 | 0.20 | 0.40 | 0.66 | +1.47 | 7.78 | 16.7 | 244 / 4972 (4.9%) |
| RS medium (3) | operating | OOS | +3.66 | +7.45 | +11.96 | 0.31 | 0.62 | 0.91 | +2.03 | 6.12 | 15.4 | 150 / 2717 (5.5%) |
| RS medium (3) | maxima | IS | +7.94 | +11.41 | +16.59 | 0.28 | 0.37 | 0.51 | +2.05 | 12.94 | 28.0 | 321 / 4972 (6.5%) |
| RS medium (3) | maxima | OOS | +8.84 | +12.09 | +15.61 | 0.48 | 0.66 | 0.85 | +3.25 | 8.76 | 24.5 | 181 / 2717 (6.7%) |

## Ranking keys against the random-order distribution, base costs

Percentile = share of the 40 random orders (same book, cap set, period and trim mode) strictly below the key's value. A cell passes only if net return and Sharpe are both above the random 90th percentile.

| Book | Cap set | Mode | Key | Period | Net % | Random p90 net % | Net percentile | Sharpe | Random p90 Sharpe | Sharpe percentile | CAGR % | Max DD % | Exposure % | Entries / signals | Period pass |
|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| TC medium (11) | operating | reject | K1 | IS | +32.13 | +18.41 | 100.0 | 1.15 | 0.77 | 100.0 | +5.38 | 6.00 | 21.7 | 346 / 9318 (3.7%) | PASS |
| TC medium (11) | operating | reject | K1 | OOS | +15.77 | +13.83 | 90.0 | 0.91 | 0.87 | 90.0 | +4.19 | 6.12 | 15.7 | 206 / 4157 (5.0%) | PASS |
| TC medium (11) | operating | reject | K2 | IS | +14.09 | +18.41 | 62.5 | 0.61 | 0.77 | 65.0 | +2.51 | 6.05 | 22.6 | 395 / 9318 (4.2%) | fail |
| TC medium (11) | operating | reject | K2 | OOS | +8.07 | +13.83 | 57.5 | 0.53 | 0.87 | 57.5 | +2.20 | 6.41 | 17.2 | 212 / 4157 (5.1%) | fail |
| TC medium (11) | operating | reject | K3 | IS | +21.62 | +18.41 | 97.5 | 0.79 | 0.77 | 92.5 | +3.75 | 7.40 | 20.2 | 341 / 9318 (3.7%) | PASS |
| TC medium (11) | operating | reject | K3 | OOS | +2.24 | +13.83 | 25.0 | 0.16 | 0.87 | 25.0 | +0.62 | 7.51 | 16.4 | 202 / 4157 (4.9%) | fail |
| TC medium (11) | operating | trim | K1 | IS | +28.50 | +20.59 | 100.0 | 1.05 | 0.85 | 97.5 | +4.83 | 6.60 | 18.6 | 513 / 9318 (5.5%) | PASS |
| TC medium (11) | operating | trim | K1 | OOS | +14.36 | +11.76 | 95.0 | 0.85 | 0.77 | 95.0 | +3.83 | 4.38 | 14.6 | 315 / 4157 (7.6%) | PASS |
| TC medium (11) | operating | trim | K2 | IS | +15.80 | +20.59 | 60.0 | 0.65 | 0.85 | 60.0 | +2.80 | 5.67 | 21.4 | 593 / 9318 (6.4%) | fail |
| TC medium (11) | operating | trim | K2 | OOS | +7.95 | +11.76 | 60.0 | 0.52 | 0.77 | 60.0 | +2.17 | 4.61 | 16.8 | 339 / 4157 (8.2%) | fail |
| TC medium (11) | operating | trim | K3 | IS | +15.71 | +20.59 | 60.0 | 0.60 | 0.85 | 57.5 | +2.78 | 7.32 | 16.5 | 513 / 9318 (5.5%) | fail |
| TC medium (11) | operating | trim | K3 | OOS | +8.81 | +11.76 | 65.0 | 0.57 | 0.77 | 65.0 | +2.40 | 4.15 | 13.4 | 305 / 4157 (7.3%) | fail |
| TC medium (11) | maxima | reject | K1 | IS | +34.84 | +41.60 | 72.5 | 0.78 | 0.93 | 67.5 | +5.78 | 8.58 | 41.6 | 685 / 9318 (7.4%) | fail |
| TC medium (11) | maxima | reject | K1 | OOS | +9.43 | +21.12 | 40.0 | 0.39 | 0.79 | 37.5 | +2.56 | 12.67 | 31.0 | 379 / 4157 (9.1%) | fail |
| TC medium (11) | maxima | reject | K2 | IS | +34.40 | +41.60 | 70.0 | 0.80 | 0.93 | 67.5 | +5.72 | 8.79 | 43.5 | 749 / 9318 (8.0%) | fail |
| TC medium (11) | maxima | reject | K2 | OOS | +27.22 | +21.12 | 97.5 | 0.99 | 0.79 | 97.5 | +6.98 | 7.34 | 32.5 | 388 / 4157 (9.3%) | PASS |
| TC medium (11) | maxima | reject | K3 | IS | +40.15 | +41.60 | 85.0 | 0.88 | 0.93 | 80.0 | +6.55 | 10.92 | 38.8 | 642 / 9318 (6.9%) | fail |
| TC medium (11) | maxima | reject | K3 | OOS | +15.06 | +21.12 | 62.5 | 0.58 | 0.79 | 57.5 | +4.01 | 7.50 | 31.0 | 331 / 4157 (8.0%) | fail |
| TC medium (11) | maxima | trim | K1 | IS | +46.11 | +39.33 | 100.0 | 0.98 | 0.88 | 97.5 | +7.39 | 9.66 | 40.6 | 1071 / 9318 (11.5%) | PASS |
| TC medium (11) | maxima | trim | K1 | OOS | +10.25 | +19.04 | 30.0 | 0.42 | 0.71 | 22.5 | +2.77 | 10.32 | 30.6 | 560 / 4157 (13.5%) | fail |
| TC medium (11) | maxima | trim | K2 | IS | +39.13 | +39.33 | 87.5 | 0.90 | 0.88 | 90.0 | +6.40 | 11.32 | 42.5 | 1101 / 9318 (11.8%) | fail |
| TC medium (11) | maxima | trim | K2 | OOS | +24.36 | +19.04 | 95.0 | 0.90 | 0.71 | 95.0 | +6.30 | 8.19 | 32.0 | 565 / 4157 (13.6%) | PASS |
| TC medium (11) | maxima | trim | K3 | IS | +46.17 | +39.33 | 100.0 | 1.02 | 0.88 | 100.0 | +7.40 | 10.57 | 37.4 | 954 / 9318 (10.2%) | PASS |
| TC medium (11) | maxima | trim | K3 | OOS | +8.76 | +19.04 | 17.5 | 0.35 | 0.71 | 10.0 | +2.38 | 8.31 | 29.5 | 535 / 4157 (12.9%) | fail |
| high52 (11) | operating | reject | K1 | IS | +5.16 | +13.57 | 20.0 | 0.32 | 0.87 | 20.0 | +0.95 | 6.43 | 12.6 | 135 / 1666 (8.1%) | fail |
| high52 (11) | operating | reject | K1 | OOS | -3.03 | +2.02 | 25.0 | -0.23 | 0.21 | 30.0 | -0.86 | 6.72 | 11.9 | 97 / 854 (11.4%) | fail |
| high52 (11) | operating | reject | K2 | IS | +4.27 | +13.57 | 15.0 | 0.27 | 0.87 | 15.0 | +0.79 | 9.56 | 12.0 | 134 / 1666 (8.0%) | fail |
| high52 (11) | operating | reject | K2 | OOS | -1.12 | +2.02 | 52.5 | -0.08 | 0.21 | 55.0 | -0.31 | 5.09 | 11.6 | 89 / 854 (10.4%) | fail |
| high52 (11) | operating | reject | K3 | IS | +2.36 | +13.57 | 2.5 | 0.16 | 0.87 | 2.5 | +0.44 | 8.36 | 12.4 | 125 / 1666 (7.5%) | fail |
| high52 (11) | operating | reject | K3 | OOS | +4.15 | +2.02 | 100.0 | 0.36 | 0.21 | 97.5 | +1.15 | 4.36 | 12.1 | 94 / 854 (11.0%) | PASS |
| high52 (11) | operating | trim | K1 | IS | +7.44 | +15.07 | 40.0 | 0.46 | 0.91 | 40.0 | +1.36 | 4.70 | 11.9 | 218 / 1666 (13.1%) | fail |
| high52 (11) | operating | trim | K1 | OOS | -7.07 | +4.17 | 0.0 | -0.60 | 0.37 | 0.0 | -2.03 | 8.32 | 12.8 | 144 / 854 (16.9%) | fail |
| high52 (11) | operating | trim | K2 | IS | +3.78 | +15.07 | 5.0 | 0.25 | 0.91 | 5.0 | +0.70 | 10.06 | 11.9 | 236 / 1666 (14.2%) | fail |
| high52 (11) | operating | trim | K2 | OOS | +1.56 | +4.17 | 65.0 | 0.15 | 0.37 | 62.5 | +0.44 | 3.55 | 13.0 | 148 / 854 (17.3%) | fail |
| high52 (11) | operating | trim | K3 | IS | +1.41 | +15.07 | 0.0 | 0.10 | 0.91 | 0.0 | +0.26 | 6.12 | 11.7 | 198 / 1666 (11.9%) | fail |
| high52 (11) | operating | trim | K3 | OOS | +0.92 | +4.17 | 50.0 | 0.10 | 0.37 | 50.0 | +0.26 | 3.25 | 11.8 | 139 / 854 (16.3%) | fail |
| high52 (11) | maxima | reject | K1 | IS | +13.67 | +16.14 | 70.0 | 0.53 | 0.63 | 72.5 | +2.44 | 9.21 | 22.2 | 237 / 1666 (14.2%) | fail |
| high52 (11) | maxima | reject | K1 | OOS | -0.94 | +5.61 | 25.0 | -0.03 | 0.33 | 25.0 | -0.27 | 6.19 | 22.6 | 149 / 854 (17.4%) | fail |
| high52 (11) | maxima | reject | K2 | IS | +13.83 | +16.14 | 72.5 | 0.53 | 0.63 | 72.5 | +2.46 | 8.41 | 22.4 | 240 / 1666 (14.4%) | fail |
| high52 (11) | maxima | reject | K2 | OOS | +3.61 | +5.61 | 67.5 | 0.24 | 0.33 | 67.5 | +1.00 | 6.92 | 21.8 | 148 / 854 (17.3%) | fail |
| high52 (11) | maxima | reject | K3 | IS | +7.31 | +16.14 | 17.5 | 0.30 | 0.63 | 17.5 | +1.33 | 13.87 | 21.2 | 231 / 1666 (13.9%) | fail |
| high52 (11) | maxima | reject | K3 | OOS | +4.76 | +5.61 | 85.0 | 0.30 | 0.33 | 85.0 | +1.31 | 6.18 | 21.7 | 146 / 854 (17.1%) | fail |
| high52 (11) | maxima | trim | K1 | IS | +14.49 | +18.55 | 67.5 | 0.55 | 0.69 | 67.5 | +2.58 | 7.29 | 22.4 | 344 / 1666 (20.6%) | fail |
| high52 (11) | maxima | trim | K1 | OOS | +0.74 | +5.85 | 27.5 | 0.07 | 0.35 | 27.5 | +0.21 | 6.69 | 22.1 | 215 / 854 (25.2%) | fail |
| high52 (11) | maxima | trim | K2 | IS | +12.42 | +18.55 | 37.5 | 0.49 | 0.69 | 45.0 | +2.23 | 7.16 | 22.6 | 349 / 1666 (20.9%) | fail |
| high52 (11) | maxima | trim | K2 | OOS | +1.86 | +5.85 | 45.0 | 0.13 | 0.35 | 45.0 | +0.52 | 5.93 | 22.3 | 219 / 854 (25.6%) | fail |
| high52 (11) | maxima | trim | K3 | IS | +14.41 | +18.55 | 67.5 | 0.53 | 0.69 | 57.5 | +2.56 | 9.36 | 22.0 | 337 / 1666 (20.2%) | fail |
| high52 (11) | maxima | trim | K3 | OOS | +6.06 | +5.85 | 90.0 | 0.35 | 0.35 | 90.0 | +1.66 | 5.73 | 21.9 | 211 / 854 (24.7%) | PASS |
| TC short (3) | operating | reject | K1 | IS | +15.92 | +17.98 | 55.0 | 0.87 | 0.99 | 52.5 | +2.82 | 5.61 | 17.4 | 418 / 1568 (26.7%) | fail |
| TC short (3) | operating | reject | K1 | OOS | +7.57 | +10.68 | 5.0 | 0.69 | 0.97 | 7.5 | +2.07 | 3.19 | 11.5 | 195 / 615 (31.7%) | fail |
| TC short (3) | operating | reject | K2 | IS | +16.63 | +17.98 | 72.5 | 0.93 | 0.99 | 72.5 | +2.93 | 5.20 | 17.8 | 431 / 1568 (27.5%) | fail |
| TC short (3) | operating | reject | K2 | OOS | +10.12 | +10.68 | 80.0 | 0.89 | 0.97 | 72.5 | +2.74 | 3.37 | 11.4 | 200 / 615 (32.5%) | fail |
| TC short (3) | operating | reject | K3 | IS | +16.45 | +17.98 | 70.0 | 0.87 | 0.99 | 55.0 | +2.90 | 6.21 | 17.6 | 420 / 1568 (26.8%) | fail |
| TC short (3) | operating | reject | K3 | OOS | +9.48 | +10.68 | 60.0 | 0.83 | 0.97 | 45.0 | +2.57 | 3.19 | 11.4 | 192 / 615 (31.2%) | fail |
| TC short (3) | operating | trim | K1 | IS | +16.82 | +18.75 | 60.0 | 0.92 | 1.01 | 60.0 | +2.97 | 5.95 | 17.7 | 488 / 1568 (31.1%) | fail |
| TC short (3) | operating | trim | K1 | OOS | +7.48 | +10.15 | 15.0 | 0.67 | 0.89 | 15.0 | +2.04 | 3.30 | 11.7 | 213 / 615 (34.6%) | fail |
| TC short (3) | operating | trim | K2 | IS | +17.84 | +18.75 | 75.0 | 0.98 | 1.01 | 75.0 | +3.13 | 3.91 | 18.4 | 485 / 1568 (30.9%) | fail |
| TC short (3) | operating | trim | K2 | OOS | +9.82 | +10.15 | 80.0 | 0.84 | 0.89 | 72.5 | +2.66 | 3.56 | 11.9 | 217 / 615 (35.3%) | fail |
| TC short (3) | operating | trim | K3 | IS | +18.92 | +18.75 | 92.5 | 1.00 | 1.01 | 82.5 | +3.31 | 6.44 | 17.9 | 475 / 1568 (30.3%) | fail |
| TC short (3) | operating | trim | K3 | OOS | +8.66 | +10.15 | 52.5 | 0.76 | 0.89 | 55.0 | +2.36 | 3.36 | 11.5 | 212 / 615 (34.5%) | fail |
| TC short (3) | maxima | reject | K1 | IS | +14.01 | +17.45 | 42.5 | 0.57 | 0.69 | 45.0 | +2.50 | 8.52 | 24.1 | 609 / 1568 (38.8%) | fail |
| TC short (3) | maxima | reject | K1 | OOS | +13.67 | +14.42 | 45.0 | 0.98 | 1.04 | 37.5 | +3.66 | 4.26 | 15.2 | 260 / 615 (42.3%) | fail |
| TC short (3) | maxima | reject | K2 | IS | +16.45 | +17.45 | 80.0 | 0.65 | 0.69 | 82.5 | +2.90 | 8.04 | 24.5 | 602 / 1568 (38.4%) | fail |
| TC short (3) | maxima | reject | K2 | OOS | +14.26 | +14.42 | 77.5 | 1.04 | 1.04 | 90.0 | +3.81 | 3.39 | 15.1 | 259 / 615 (42.1%) | fail |
| TC short (3) | maxima | reject | K3 | IS | +13.03 | +17.45 | 17.5 | 0.53 | 0.69 | 15.0 | +2.33 | 8.90 | 24.4 | 606 / 1568 (38.6%) | fail |
| TC short (3) | maxima | reject | K3 | OOS | +13.23 | +14.42 | 20.0 | 0.95 | 1.04 | 15.0 | +3.54 | 4.26 | 15.1 | 260 / 615 (42.3%) | fail |
| TC short (3) | maxima | trim | K1 | IS | +16.42 | +17.59 | 70.0 | 0.64 | 0.67 | 70.0 | +2.90 | 8.31 | 24.8 | 660 / 1568 (42.1%) | fail |
| TC short (3) | maxima | trim | K1 | OOS | +12.14 | +13.54 | 17.5 | 0.88 | 0.98 | 12.5 | +3.26 | 4.31 | 15.3 | 274 / 615 (44.6%) | fail |
| TC short (3) | maxima | trim | K2 | IS | +16.44 | +17.59 | 70.0 | 0.63 | 0.67 | 67.5 | +2.90 | 8.51 | 25.1 | 658 / 1568 (42.0%) | fail |
| TC short (3) | maxima | trim | K2 | OOS | +13.63 | +13.54 | 90.0 | 0.99 | 0.98 | 92.5 | +3.65 | 3.47 | 15.4 | 276 / 615 (44.9%) | PASS |
| TC short (3) | maxima | trim | K3 | IS | +13.51 | +17.59 | 2.5 | 0.53 | 0.67 | 0.0 | +2.41 | 9.25 | 24.9 | 660 / 1568 (42.1%) | fail |
| TC short (3) | maxima | trim | K3 | OOS | +12.30 | +13.54 | 25.0 | 0.88 | 0.98 | 17.5 | +3.31 | 4.31 | 15.3 | 275 / 615 (44.7%) | fail |
| RS medium (3) | operating | reject | K1 | IS | +12.66 | +11.45 | 100.0 | 0.60 | 0.54 | 100.0 | +2.27 | 8.85 | 15.9 | 140 / 4972 (2.8%) | PASS |
| RS medium (3) | operating | reject | K1 | OOS | +6.85 | +6.49 | 90.0 | 0.57 | 0.53 | 92.5 | +1.87 | 5.91 | 15.4 | 78 / 2717 (2.9%) | PASS |
| RS medium (3) | operating | reject | K2 | IS | +5.40 | +11.45 | 35.0 | 0.28 | 0.54 | 35.0 | +0.99 | 8.12 | 16.6 | 136 / 4972 (2.7%) | fail |
| RS medium (3) | operating | reject | K2 | OOS | +3.54 | +6.49 | 47.5 | 0.30 | 0.53 | 50.0 | +0.98 | 5.99 | 15.9 | 93 / 2717 (3.4%) | fail |
| RS medium (3) | operating | reject | K3 | IS | +8.15 | +11.45 | 60.0 | 0.38 | 0.54 | 55.0 | +1.48 | 10.98 | 15.2 | 144 / 4972 (2.9%) | fail |
| RS medium (3) | operating | reject | K3 | OOS | +3.82 | +6.49 | 52.5 | 0.30 | 0.53 | 50.0 | +1.06 | 7.91 | 14.5 | 96 / 2717 (3.5%) | fail |
| RS medium (3) | operating | trim | K1 | IS | +6.27 | +11.57 | 20.0 | 0.33 | 0.57 | 22.5 | +1.15 | 8.52 | 15.9 | 245 / 4972 (4.9%) | fail |
| RS medium (3) | operating | trim | K1 | OOS | +10.82 | +10.36 | 92.5 | 0.86 | 0.82 | 92.5 | +2.92 | 5.51 | 14.9 | 143 / 2717 (5.3%) | PASS |
| RS medium (3) | operating | trim | K2 | IS | +13.01 | +11.57 | 92.5 | 0.60 | 0.57 | 92.5 | +2.33 | 6.83 | 17.0 | 246 / 4972 (4.9%) | PASS |
| RS medium (3) | operating | trim | K2 | OOS | +7.37 | +10.36 | 47.5 | 0.61 | 0.82 | 47.5 | +2.01 | 5.60 | 15.6 | 156 / 2717 (5.7%) | fail |
| RS medium (3) | operating | trim | K3 | IS | +8.40 | +11.57 | 57.5 | 0.41 | 0.57 | 57.5 | +1.53 | 9.50 | 15.3 | 243 / 4972 (4.9%) | fail |
| RS medium (3) | operating | trim | K3 | OOS | +11.49 | +10.36 | 92.5 | 0.91 | 0.82 | 95.0 | +3.10 | 6.21 | 14.2 | 151 / 2717 (5.6%) | PASS |
| RS medium (3) | maxima | reject | K1 | IS | +15.32 | +17.19 | 70.0 | 0.48 | 0.53 | 72.5 | +2.72 | 10.57 | 27.4 | 231 / 4972 (4.6%) | fail |
| RS medium (3) | maxima | reject | K1 | OOS | +15.44 | +14.30 | 97.5 | 0.79 | 0.74 | 95.0 | +4.11 | 8.36 | 25.1 | 142 / 2717 (5.2%) | PASS |
| RS medium (3) | maxima | reject | K2 | IS | +16.39 | +17.19 | 80.0 | 0.50 | 0.53 | 80.0 | +2.89 | 10.86 | 28.7 | 236 / 4972 (4.7%) | fail |
| RS medium (3) | maxima | reject | K2 | OOS | +8.39 | +14.30 | 17.5 | 0.47 | 0.74 | 20.0 | +2.28 | 8.96 | 25.4 | 148 / 2717 (5.4%) | fail |
| RS medium (3) | maxima | reject | K3 | IS | +15.58 | +17.19 | 72.5 | 0.48 | 0.53 | 72.5 | +2.76 | 13.21 | 27.6 | 233 / 4972 (4.7%) | fail |
| RS medium (3) | maxima | reject | K3 | OOS | +9.88 | +14.30 | 32.5 | 0.52 | 0.74 | 27.5 | +2.68 | 9.67 | 24.9 | 148 / 2717 (5.4%) | fail |
| RS medium (3) | maxima | trim | K1 | IS | +13.30 | +15.39 | 75.0 | 0.42 | 0.48 | 67.5 | +2.37 | 12.91 | 27.1 | 317 / 4972 (6.4%) | fail |
| RS medium (3) | maxima | trim | K1 | OOS | +12.03 | +15.36 | 50.0 | 0.65 | 0.83 | 42.5 | +3.24 | 7.88 | 24.9 | 179 / 2717 (6.6%) | fail |
| RS medium (3) | maxima | trim | K2 | IS | +7.96 | +15.39 | 5.0 | 0.27 | 0.48 | 5.0 | +1.45 | 11.96 | 26.9 | 324 / 4972 (6.5%) | fail |
| RS medium (3) | maxima | trim | K2 | OOS | +12.36 | +15.36 | 57.5 | 0.69 | 0.83 | 60.0 | +3.32 | 8.85 | 24.9 | 187 / 2717 (6.9%) | fail |
| RS medium (3) | maxima | trim | K3 | IS | +10.50 | +15.39 | 30.0 | 0.34 | 0.48 | 30.0 | +1.89 | 12.73 | 27.5 | 323 / 4972 (6.5%) | fail |
| RS medium (3) | maxima | trim | K3 | OOS | +12.51 | +15.36 | 57.5 | 0.66 | 0.83 | 52.5 | +3.36 | 8.63 | 24.6 | 180 / 2717 (6.6%) | fail |

| Book | Cap set | Mode | Key | IS | OOS | Ranking-key admission candidate |
|---|---|---|---|---|---|---|
| TC medium (11) | operating | reject | K1 | pass | pass | YES |
| TC medium (11) | operating | reject | K2 | fail | fail | no |
| TC medium (11) | operating | reject | K3 | pass | fail | no |
| TC medium (11) | operating | trim | K1 | pass | pass | YES |
| TC medium (11) | operating | trim | K2 | fail | fail | no |
| TC medium (11) | operating | trim | K3 | fail | fail | no |
| TC medium (11) | maxima | reject | K1 | fail | fail | no |
| TC medium (11) | maxima | reject | K2 | fail | pass | no |
| TC medium (11) | maxima | reject | K3 | fail | fail | no |
| TC medium (11) | maxima | trim | K1 | pass | fail | no |
| TC medium (11) | maxima | trim | K2 | fail | pass | no |
| TC medium (11) | maxima | trim | K3 | pass | fail | no |
| high52 (11) | operating | reject | K1 | fail | fail | no |
| high52 (11) | operating | reject | K2 | fail | fail | no |
| high52 (11) | operating | reject | K3 | fail | pass | no |
| high52 (11) | operating | trim | K1 | fail | fail | no |
| high52 (11) | operating | trim | K2 | fail | fail | no |
| high52 (11) | operating | trim | K3 | fail | fail | no |
| high52 (11) | maxima | reject | K1 | fail | fail | no |
| high52 (11) | maxima | reject | K2 | fail | fail | no |
| high52 (11) | maxima | reject | K3 | fail | fail | no |
| high52 (11) | maxima | trim | K1 | fail | fail | no |
| high52 (11) | maxima | trim | K2 | fail | fail | no |
| high52 (11) | maxima | trim | K3 | fail | pass | no |
| TC short (3) | operating | reject | K1 | fail | fail | no |
| TC short (3) | operating | reject | K2 | fail | fail | no |
| TC short (3) | operating | reject | K3 | fail | fail | no |
| TC short (3) | operating | trim | K1 | fail | fail | no |
| TC short (3) | operating | trim | K2 | fail | fail | no |
| TC short (3) | operating | trim | K3 | fail | fail | no |
| TC short (3) | maxima | reject | K1 | fail | fail | no |
| TC short (3) | maxima | reject | K2 | fail | fail | no |
| TC short (3) | maxima | reject | K3 | fail | fail | no |
| TC short (3) | maxima | trim | K1 | fail | fail | no |
| TC short (3) | maxima | trim | K2 | fail | pass | no |
| TC short (3) | maxima | trim | K3 | fail | fail | no |
| RS medium (3) | operating | reject | K1 | pass | pass | YES |
| RS medium (3) | operating | reject | K2 | fail | fail | no |
| RS medium (3) | operating | reject | K3 | fail | fail | no |
| RS medium (3) | operating | trim | K1 | fail | pass | no |
| RS medium (3) | operating | trim | K2 | pass | fail | no |
| RS medium (3) | operating | trim | K3 | fail | pass | no |
| RS medium (3) | maxima | reject | K1 | fail | pass | no |
| RS medium (3) | maxima | reject | K2 | fail | fail | no |
| RS medium (3) | maxima | reject | K3 | fail | fail | no |
| RS medium (3) | maxima | trim | K1 | fail | fail | no |
| RS medium (3) | maxima | trim | K2 | fail | fail | no |
| RS medium (3) | maxima | trim | K3 | fail | fail | no |

## Final table: qualifying arms at base and stress costs (qualifying arms only, with their paired random orders)

The decision rules are base-cost rules; the stress columns are reported for the reader and carry no verdict. Stress = $0.005 per share with a $1 minimum, 10 bps slippage, 10 bps spread.

Trim-to-budget candidates (40 paired random orders):

| Book | Cap set | Period | Base: trim wins / 40 | Base: median diff (pts) | Stress: trim wins / 40 | Stress: median diff (pts) | Stress net % p50 reject | Stress net % p50 trim | Stress Sharpe p50 reject | Stress Sharpe p50 trim | Stress max DD % p50 reject | Stress max DD % p50 trim |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RS medium (3) | operating | IS | 26 | +2.44 | 16 | -1.38 | +4.63 | +3.26 | 0.24 | 0.18 | 9.12 | 9.15 |
| RS medium (3) | operating | OOS | 34 | +2.94 | 32 | +3.05 | +1.54 | +4.04 | 0.15 | 0.36 | 7.17 | 6.23 |

Ranking-key candidates (percentile within the 40 random orders of the same trim mode and cost case):

| Book | Cap set | Mode | Key | Period | Base net % | Base random p50 / p90 net % | Base percentile net / Sharpe | Stress net % | Stress random p50 / p90 net % | Stress Sharpe | Stress random p50 / p90 Sharpe | Stress percentile net / Sharpe | Stress max DD % | Above stress p90 on both |
|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| RS medium (3) | operating | reject | K1 | IS | +12.66 | +6.94 / +11.45 | 100.0 / 100.0 | +4.44 | +4.63 / +9.10 | 0.24 | 0.24 / 0.45 | 47.5 / 47.5 | 10.45 | no |
| RS medium (3) | operating | reject | K1 | OOS | +6.85 | +3.65 / +6.49 | 90.0 / 92.5 | +4.60 | +1.54 / +4.49 | 0.40 | 0.15 / 0.36 | 90.0 / 92.5 | 5.91 | yes |
| TC medium (11) | operating | reject | K1 | IS | +32.13 | +10.37 / +18.41 | 100.0 / 100.0 | +11.42 | +0.12 / +6.41 | 0.48 | 0.03 / 0.31 | 100.0 / 100.0 | 8.24 | yes |
| TC medium (11) | operating | reject | K1 | OOS | +15.77 | +6.28 / +13.83 | 90.0 / 90.0 | -0.23 | -0.06 / +8.15 | 0.01 | 0.02 / 0.57 | 47.5 / 47.5 | 7.57 | no |
| TC medium (11) | operating | trim | K1 | IS | +28.50 | +11.61 / +20.59 | 100.0 / 97.5 | +16.83 | +2.48 / +8.79 | 0.67 | 0.13 / 0.41 | 100.0 / 100.0 | 6.15 | yes |
| TC medium (11) | operating | trim | K1 | OOS | +14.36 | +5.86 / +11.76 | 95.0 / 95.0 | +5.03 | -0.61 / +5.48 | 0.35 | -0.02 / 0.38 | 85.0 / 85.0 | 6.59 | no |

Random-order medians at stress costs for every book and cap set that was run at stress (reject vs trim):

| Book | Cap set | Period | Reject net % p5 / p50 / p95 | Trim net % p5 / p50 / p95 | Reject Sharpe p50 | Trim Sharpe p50 | Trim wins / 40 | Median diff (pts) | SPY total return % (stress costs) |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| TC medium (11) | operating | IS | -9.27 / +0.12 / +7.34 | -6.92 / +2.48 / +10.64 | 0.03 | 0.13 | 24 | +1.60 | +129.65 |
| TC medium (11) | operating | OOS | -5.38 / -0.06 / +9.08 | -7.02 / -0.61 / +6.79 | 0.02 | -0.02 | 18 | -0.94 | +50.09 |
| RS medium (3) | operating | IS | -1.53 / +4.63 / +12.02 | -1.30 / +3.26 / +8.74 | 0.24 | 0.18 | 16 | -1.38 | +129.65 |
| RS medium (3) | operating | OOS | -3.57 / +1.54 / +5.10 | +2.04 / +4.04 / +9.98 | 0.15 | 0.36 | 32 | +3.05 | +50.09 |

## SPY total return for the same periods (reference)

| Period | Cost case | Net % | CAGR % | Max DD % | Sharpe |
|---|---|---:|---:|---:|---:|
| IS | base | +130.13 | +16.96 | 33.62 | 0.94 |
| OOS | base | +50.60 | +12.16 | 21.93 | 0.72 |
| IS | higher_cost_stress | +129.65 | +16.92 | 33.65 | 0.94 |
| OOS | higher_cost_stress | +50.09 | +12.06 | 21.95 | 0.72 |

## Scope actually run

- trend_continuation.medium_swing (strategy version 3, snapshot 11): 147 symbols replayed, skipped for incomplete bars: BKNG, VST, XLC; 13475 signal-days in the table; dividend rows for 22 symbols.
- high52_breakout.medium_swing (strategy version 13, snapshot 11): 147 symbols replayed, skipped for incomplete bars: BKNG, VST, XLC; 2520 signal-days in the table; dividend rows for 22 symbols.
- trend_continuation.short_swing (strategy version 2, snapshot 3): 23 symbols replayed, skipped for incomplete bars: XLC; 2183 signal-days in the table; dividend rows for 22 symbols.
- relative_strength.medium_swing (strategy version 5, snapshot 3): 23 symbols replayed, skipped for incomplete bars: XLC; 7689 signal-days in the table; dividend rows for 22 symbols.
- Cap sets: operating = open risk 1.5%, gross 60.0%, 2 accepts per day (read from the scratch copy); maxima = open risk 3.0%, gross 100.0%, no daily cap. Both: per-trade risk 0.5%, symbol 10.0%, sector 20.0%, $30000 cash.
- Books run: trend_continuation.medium_swing, high52_breakout.medium_swing, trend_continuation.short_swing, relative_strength.medium_swing. Runs saved: 1376 base, 326 stress.

## Expectations stated in advance, against the outcome

| Expectation in the pre-registration | Outcome |
|---|---|
| Capacity binds for trend_continuation.medium on 150 symbols and much less on the 24-symbol books | The band is widest there (20 to 29 points). It is also 9 to 10 points for relative_strength.medium on 24 symbols, where 3% to 5% of signal-days become entries, and narrowest for trend_continuation.short (2.6 to 8.5 points). |
| The luck band is wide, several points of net return | Wider than expected: 2.6 to 29.4 points between the 5th and 95th percentile, depending on the cell. |
| Trim-to-budget helps modestly | Mixed. Median paired change −1.96 to +2.94 points; the rule passes for one of eight book-and-cap-set cases. |
| No ranking key clears the bar | Not confirmed: K1 cleared it in 3 of 48 cells, all on the operating caps, against 0.5 to 0.8 expected by chance. None holds on the maximum caps or in both periods at stress costs. |

## Deviations and clarifications

No pre-registered arm was dropped, added or changed after results were seen. The points below
are choices the pre-registration left open; each was fixed in the script before the grid ran.
Points 10, 12, 13, 17 and 19 were extended and point 20 was added after adversarial review;
they change wording and disclosure only.

1. **Fresh cash in OOS.** The OOS replay loads bars from 2016-10-17 so every
   rule has its full history on 2022-02-11, and uses the library's own `entry_start` so the
   account stays in cash until that date. Metrics use only the 894 OOS sessions, starting from
   $30,000. The script asserts the account is worth exactly $30,000 on every earlier session
   and that no fill precedes 2022-02-11. The IS replay loads bars to 2022-02-10 only and
   liquidates at its last close. Loading OOS bars from 2022-02-11 alone would have left the
   252-session rule without signals for the first year.
2. **Warm-up inside IS.** No stock bars exist before 2016-10-17, so the IS window
   contains each rule's own warm-up. First signals: 2016-12-28 for both trend_continuation
   books, 2017-08-02 for relative_strength.medium, 2017-10-17 for high52_breakout.medium.
3. **Universe.** Symbols with complete bars over the whole development window, the rule
   `funded_replay_report` applies: 147 of 150 on snapshot 11 (BKNG, VST, XLC skipped) and 23 of
   24 on snapshot 3 (XLC skipped). SPY is a tradable member of both snapshots.
4. **Operating cap set.** Read from the scratch copy: open risk 1.5%, gross 60%, two accepts
   per day. The operating configuration also carries a per-trade risk setting of 10% and a
   sector limit of 25%; as pre-registered, per-trade risk is 0.5% and the sector cap 20%, which
   are also the paper ledger's hard maxima.
5. **Daily cap.** At most two accepted entries per session. A later candidate that would
   otherwise have been accepted that day is rejected with reason `daily_cap`. In the library
   reference the cap is expressed through the library's `entry_admission` hook. Unfilled
   signals do not carry over (library behaviour); a signal that still fires is offered again
   the next session.
6. **Random orders.** Seed 20261110 + i, i = 0..39. Each (session, symbol) gets one uniform
   priority from `numpy.random.default_rng(seed)`; same-day candidates are processed lowest
   first. The grid of priorities does not depend on trim mode, cap set or period, so the
   reject and trim runs of a seed are exactly paired.
7. **Trim-to-budget.** Only the three outright rejections in `risk.engine.size_position`
   (gross, sector, open risk) are replaced, each by the largest whole-share size that passes
   the library's own inequality. "Minimum one share" is read as: if not even one share fits,
   the entry is still rejected. Per-trade risk sizing, the symbol cap, the 1% volume cap and
   the library's final share-by-share reduction for cash and cost-inclusive risk are unchanged
   in both modes. A trimmed entry uses one of the day's two accepts on the operating caps.
8. **Ranking keys.** Computed with library feature functions on bars cut at the signal day.
   K1 = `rolling_return(63)` of the symbol minus SPY's at the same session. K2 = the library
   `volume_ratio(20)`, signal-day volume over the mean of the 19 sessions before it; dividing
   by a 20-session mean that includes the signal day is a monotone transform, so the order is
   the same. K3 = (close − the signal's stop) ÷ close. Highest first; ties and missing keys
   fall back to symbol order, missing last. K1 is missing for 112 of 13,475
   trend_continuation.medium signal-days and 25 of 2,183 trend_continuation.short signal-days,
   all between 2016-12-28 and 2017-01-17 (fewer than 63 sessions of history).
9. **No lookahead.** Every key is computed from a prefix that ends on the signal day
   (asserted), and a poison test recomputed 400 keys per book with all later bars set to NaN:
   identical. An independent pandas recomputation of 300 trend_continuation.medium keys from
   the database agreed to 1e-16 (`scripts/r3/capacity_admission_verify.py`).
10. **Percentiles.** numpy's default linear interpolation for the 5th, 50th, 90th and 95th
    percentile; "above" is strict. With 40 orders the 90th percentile lies just above the 36th
    smallest value, so a key passes when at least 36 random orders are below it and it clears
    the interpolated value. Two OOS passes sit at exactly 36 of 40 on net return; a
    stricter convention would fail them. Because the threshold is itself estimated from only
    40 orders, an uninformative order clears it more often than the nominal one time in ten.
    A 41st order drawn the same way is above the interpolated value with probability 4.9 in
    41 (12%) on one measure. On both measures the rate is about 11% (10.7% when each of the
    study's own 1,280 random-order runs is judged against the other 39 of its cell), and
    about 1.2% in both periods. That is about 0.6 chance candidates in 48 cells and 3.5
    chance single-period passes per key in 32 cells, against 0.48 and 3.2 by the
    pre-registration's arithmetic (10% × 10%). Against this study's actual thresholds the
    review's null simulation was higher still (point 20). The pre-registered rule and its
    verdicts are unchanged.
11. **Number of key cells.** The pre-registration counts twelve key-by-book comparisons per cap
    set. Each was run with and without trim, so 24 cells per cap set and 48 in all, each judged
    against the random orders of its own trim mode. All 48 are shown.
12. **Sign test.** A win is trim strictly above reject on net return for the same seed. There
    were no ties. A win count over 40 pairs has a binomial standard error of about 3 wins
    (3.2 at a 50% win rate, 3.0 at 65%), so counts within about 3 of the threshold of 26
    cannot be told apart. On the operating caps the IS counts are 21, 24, 25 and 26: the one
    candidate (relative_strength.medium, 26 in IS and 34 in OOS) and high52 (24 and 33) differ
    by two IS wins. The mechanical verdict stands as pre-registered.
13. **Entries ÷ signals.** "Signals" is every long signal-day of the book whose next session
    falls in the period, whether or not the symbol was already held, so the denominator is the
    same for every arm. `runs.csv` also carries the number actually offered (not already held).
    A median over 40 whole-number counts can end in .5; the tables print it as a whole number,
    a half going to the even neighbour (399.5 appears as 400, 216.5 as 216).
14. **Signal table.** A signal depends only on bars up to the signal day and the SPY regime
    that day, so each book's signals are computed once and reused by every run. The identity
    check compares against library runs that build their signals afresh.
15. **Identity check, wider than pre-registered.** Besides fills and final equity, the daily
    marks, every admission decision, total costs and dividend events are identical in all 16
    cells. Two additional checks also passed: the same 16 cells at stress costs, and the
    canonical `funded_replay_report.replay` on the IS / maxima / base cell of each book (fills,
    marks, skipped symbols, metrics and SPY benchmark identical).
16. **Stress case.** Because arms qualified, stress costs were run only for those arms and the
    40 random orders they are judged against (trend_continuation.medium and
    relative_strength.medium on the operating caps). The decision rules are base-cost rules;
    the stress columns carry no verdict.
17. **SPY reference.** `funded_replay_report.spy_benchmark`: $30,000 in whole SPY shares at the
    first open of the period, dividends reinvested, same cost model, liquidated at the last
    close. The comparison with the books is not like for like on dividends. SPY is a full
    total return, while a book is credited cash dividends only for symbols that have dividend
    rows in the database: 22 of the 147 replayed symbols on snapshot 11 and 22 of the 23 on
    snapshot 3 (library policy: a symbol without rows is credited none, which understates its
    holdings). Booked dividends run at 1.5% to 2.1% of invested capital per year on the two
    snapshot-3 books and at 0.1% to 0.5% on the two snapshot-11 books (medians over runs);
    the most any run booked is $811 in IS (2.7 points of net return) and $485 in OOS (1.6
    points). As rough arithmetic, a 2% yield on the largest mean exposure of any run (46% in
    IS, 35% in OOS) over 5.3 and 3.6 years is 4.9 and 2.5 points. Adding 2% a year to every
    run at its own exposure still leaves each one more than 72 points (IS) and almost 19
    points (OOS) below SPY, so the conclusion does not depend on it.
18. **Bars.** Loaded with `funded_replay_report._load` (source `massive` only, quality-gated),
    the loader the funded replay report uses, not `PriceSeries.load`. The last bar loaded is
    2025-09-05.
19. **Dividends and the end of the window.** Four dividend rows with ex-dates inside the
    window (2025-08-15 to 2025-09-04) carry declared pay dates after the end of the window,
    and two rows straddle the end of IS. As in the library, shares held into such an ex-date
    are credited the declared cash as a receivable in final equity; the pay date is a field
    of the dividend row. Separately, the library dividend loader the script calls
    (`funded_replay_report._dividends`) reads a symbol's split rows with no date bound and
    divides each dividend by the ratio of every later split, so that amounts are on the same
    share basis as the bars. For 5 replayed symbols those rows include a split dated after
    the window, and their 176 dividend rows (of 818 in the window) are rescaled by it. Read
    to the letter, that is outside the pre-registered "nothing on or after 2025-09-07 is
    loaded", and the first version of this file did not disclose it. It is kept because the
    stored bars of those symbols are already on the later share basis, so unscaled dividends
    would be on the wrong one, and because it is what the library replay does. The bar table
    carries no split factor of its own for these rows, so the split table is the only source
    of the conversion. An in-window check supports the basis: on those 176 ex-dates the
    overnight fall, net of the market, averages 1.04 times the booked dividend (standard
    error 0.08), against 0.87 (0.06) on the 607 ex-dates of the 16 other symbols; on the
    wrong basis the multiple would be the split ratio rather than about one
    (`capacity_admission_verify.py`, check 4, which selects no row dated after 2025-09-05).
    No price, bar or ex-date after 2025-09-05 is read.
20. **Changes after adversarial review.** An independent review re-ran the identity check and
    the whole grid (identical in every column but run time), rebuilt 984 of the 1,376
    base-cost runs through the library replay with its own ordering, trim and metrics code
    (identical), and recomputed the analysis and verdicts (identical). It raised four points
    of wording and disclosure. All four were accepted and none changes a run, a table or a
    verdict: the chance rate of the key rule (point 10), seed noise in the sign test (12),
    dividends in the comparison with SPY (17) and split rows dated after the window (19). In
    the same pass a median quoted in the text was made exact (399.5, printed as 400 in the
    tables; point 13) and a pay date after the window is no longer printed (19). The review
    also ran two diagnostics with this study's replay engine and fresh seeds. They are
    outside the pre-registration, are not study arms and carry no verdict.
    (a) Of 1,600 fresh random orders judged against this study's 40-order thresholds, 12.75%
    cleared the single-period bar in IS and 14.2% in OOS, and 1.75% cleared it in both
    periods (0.84 expected in 48 cells; 0.69 and 0.72 for two persistent kinds of
    uninformative order). Pooled with the study's own orders (140 per cell),
    relative_strength.medium / operating / K1 without trim falls to the 80th percentile on
    net return in OOS, while both trend_continuation.medium / operating K1 cells stay above
    the 90th percentile on both measures in both periods.
    (b) On 200 fresh paired orders per cell, trim won 56.5% of pairs for
    relative_strength.medium / operating in IS (65% in the study) and 64.5% for high52 /
    operating in IS (60% in the study); at those rates a 40-order draw reaches 26 wins about
    18% and 55% of the time.

## What a pass does and does not license

As pre-registered: admission order and trimming are ledger behaviour, not strategy rules.
Adopting either in the operating paper book is an operator decision and, while the v2 studies
are frozen, belongs to a future study generation. Nothing here changes the operating scan,
ledger, risk limits or any frozen study. All periods are already-observed development data.

## Reproduce

```sh
cd <scratch>/r3            # a directory with no .env
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=<worktree>/src:<worktree>/scripts MARKET_DATA_PROVIDER=massive \
SIGNALFORGE_DATA_DIR=<scratch>/r3/db \
DATABASE_URL="sqlite+pysqlite:///file:<scratch>/r3/db/signalforge.sqlite?mode=ro&uri=true" \
<venv>/bin/python <worktree>/scripts/r3/capacity_admission.py all        # prepare, grid, analyze, stress, report
<venv>/bin/python <worktree>/scripts/r3/capacity_admission_verify.py     # ordering, key, trim and dividend-basis checks
```

Raw outputs (not committed), under `<scratch>/r3/out/capacity/`: `identity.json`, `runs.csv`
(1,376 rows), `stress_runs.csv` (326 rows), `summary.json`, `tables.md`, the stage logs,
`rerun_check/` (the second complete run), `review/` (the reviewer's re-run and diagnostics)
and `repair/` (the checks behind points 10, 12, 17, 19 and 20).

Research signal only — no order was placed.
