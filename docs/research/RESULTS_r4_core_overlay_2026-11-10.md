# Results — R4-O: do the approved rules add anything on top of holding the index? (2026-11-10)

Pre-registration: `docs/research/PREREGISTRATION_r4_core_overlay_2026-11-10.md` (commit 1b8cc3a,
written before any run of this study). Run on a private read-only copy of the operating
database; development window only (bars end 2025-09-05). Descriptive research: no sealed look,
no operating-database write, no change to any frozen study, risk limit or approved version. The
books are the ones R3-C prepared, so its disclosure about split rows read by the library
dividend loader applies unchanged (point 12 under "Deviations and clarifications"); no price
after 2025-09-05 is read.

The two periods are IS (2016-10-17..2022-02-10) and OOS (2022-02-11..2025-09-05), each started
from a fresh $30,000. Nothing in this study is fitted, so they are two separate stretches of
already-observed development data.

## Answer

**No. On top of an index core, every approved book left the account worse off than holding SPY
alone.** In all 16 combinations of book, cap set and period the median overlay account finished
below the SPY reference, by 3.1 to 56.7 points of net return, and with a lower Sharpe ratio in
every one. Of the 640 replays, 11 finished above the reference (2 in IS, 9 in OOS).

**No cell is an account-level candidate** under the pre-registered rule, so no stress-cost run
was made. Every overlay account is far above its standalone book (by 10 to 119 points), as
expected; that lift is the index, not the rules.

**The pre-registered result stands as it is: all 16 median increments are negative, and the
expectation of "near zero in OOS" was not met** (OOS medians −3.1 to −24.8 points).

**Description only, added after the first results were seen (not pre-registered, no verdict):
part of the gap is the accounting, not the trades.** The pre-registered accounting credits
exit proceeds to SPY at the open of the day they arrive, and exits cluster on days when SPY
falls between the open and the close. That convention and the 5.5 bps sleeve cost together
make up 2.3 to 24.1 points of the mean gap. The rest of the mean gap is negative in all eight
IS cells, though for relative_strength.medium on the operating caps it is close to zero
(−1.06 points, 16 of 40 orders positive); in OOS it is negative in five cells and about zero
in three.

## How to read this

- **The lift over the standalone book is the index.** Example, trend_continuation.short on the
  operating caps: the standalone book made +15.3% in IS and +9.3% in OOS (median of 40 orders);
  the same book with its idle cash in SPY made +107.2% and +45.8%; SPY alone made +131.6% and
  +51.3%. On average 62% to 92% of the account sat in the sleeve.
- **The rules' trades displaced index exposure and earned less than it.** The median increment
  is negative in every cell and period (table below). The mean daily active return against SPY
  is negative in all 16 cells, from −0.26 to −2.05 bps a day (−0.7% to −5.2% a year). It is
  more than two standard errors from zero in 7 of the 16 and within two in the other 9, so on
  a daily basis about half the cells cannot be told apart from zero; none is positive. The 40
  orders of a cell share one market history, so a count such as "0 of 40" is not 40
  independent results.
- **The shortfall is spread over the years, not one episode.** Both trend_continuation books
  trail SPY in every full IS year (2017 to 2021). The positive calendar years are few and
  small: relative_strength.medium in 2017 and in 2022 (it traded through the 2022 decline,
  while the two trend_continuation books and high52 made no trade between 2022-02-11 and
  2023-02-03), trend_continuation.short in 2024, and a handful of entries below one point.
- **The overlay does not reduce drawdown.** Median account max drawdown is within −0.6 to +1.0
  points of SPY's (33.7% in IS, 22.1% in OOS). The deepest falls came while the books were
  mostly out of the market, that is, while the money was in the sleeve. The drawdown condition
  therefore passes everywhere and is the only return condition that does.
- **One cell could not be run as stated.** trend_continuation.medium on the maximum caps, OOS:
  the book, which sizes on its own equity, asked for more than the sleeve held on 94 sessions
  in 33 of the 40 orders, by up to $2,097 (7.5% of account value, on 2023-02-03), after the
  index had fallen. That is above the 1% limit, so the cell is marked "not implementable as
  stated". No other cell had a shortfall.
- **How much of the gap is the accounting (a split added after the first results were seen;
  not pre-registered).** The pre-registered recursion takes every flow at
  the open of its session. For entries that is when the money leaves. For exits it books SPY's
  whole open-to-close move on proceeds that mostly arrive later in the day: only 4% to 12% of
  pay-ins are opening-gap stops, and under 0.2% are dividends. Stops are hit on days the market
  falls, so SPY's open-to-close return on pay-in days averages −14 to −42 bps (weighted by the
  money paid in) against +1.2 bps (IS) and +3.5 bps (OOS) over all days. The split table shows
  each part: this exit-day part is −1.3 to −15.2 points of the mean increment, sleeve cost is
  −1.0 to −8.9 points, and the remainder is −1.1 to −31.9 points in IS and −14.3 to +0.6
  points in OOS. In no cell and period is the remainder positive for more than 26 of the 40
  orders, so the verdicts do not hinge on either part. The three OOS cells where the remainder
  is about zero are trend_continuation.short on the operating caps (+0.62, 26 of 40 orders
  positive) and on the maximum caps (−0.50, 15 of 40), and relative_strength.medium on the
  maximum caps (+0.60, 23 of 40). The split is an exact arithmetic breakdown of the
  pre-registered number. No second account was run and it carries no verdict; the caption's
  "what the same account would show with pay-ins credited at the close" describes the
  remainder term, not a separate result. In the split, "the money a book paid in that day"
  is the day's net pay-in (the positive part of the day's net change in book cash), so
  entries and exits on the same day are netted, as they are in the recursion; the table of
  pay-in sources uses gross sell fills instead.
- **Dividends are not like for like, against the two snapshot-11 books.** The sleeve earns
  SPY's full total return, while a book is credited dividends only for symbols with dividend
  rows in the database: 22 of the 147 replayed on snapshot 11, 22 of 23 on snapshot 3 (R3-C,
  point 17). Adding 2% a year to the snapshot-11 books at their median exposure is worth
  roughly 4.8 points in IS and 2.4 in OOS as a simple sum. That is a rough size, not a
  ceiling: it ignores that the missing dividends would compound in the sleeve and that
  orders differ in exposure. The median increments for those books are −10.4 to −56.7
  points, so no verdict depends on it.

## Verdicts (decision rule applied mechanically, base costs)

| Book | Cap set | IS | OOS | Implementable as stated | Account-level candidate |
|---|---|---|---|---|---|
| TC medium (11) | operating | fail | fail | yes | no |
| TC medium (11) | maxima | fail | fail | NO (sleeve shortfall above 1%) | no |
| high52 (11) | operating | fail | fail | yes | no |
| high52 (11) | maxima | fail | fail | yes | no |
| TC short (3) | operating | fail | fail | yes | no |
| TC short (3) | maxima | fail | fail | yes | no |
| RS medium (3) | operating | fail | fail | yes | no |
| RS medium (3) | maxima | fail | fail | yes | no |

## Increment over the SPY reference and the decision rule, by period (40 orders, base costs)

Increment = overlay account minus the SPY reference of the same period. A period passes only if every condition holds.

| Book | Cap set | Period | Median net-return increment (pts) | p5 / p95 (pts) | Orders with a positive increment / 40 | Median CAGR increment (pts) | Median Sharpe increment | Median max DD: account % / SPY % (diff pts) | Net > 0 | Sharpe > 0 | >= 36 orders | DD <= +2 | Implementable | Period |
|---|---|---|---:|---:|---:|---:|---:|---:|---|---|---|---|---|---|
| TC medium (11) | operating | IS | -34.82 | -48.27 / -21.40 | 0 | -3.53 | -0.17 | 33.52 / 33.72 (-0.20) | no | no | no | yes | yes | fail |
| TC medium (11) | operating | OOS | -12.74 | -24.94 / +0.30 | 3 | -2.74 | -0.14 | 22.09 / 22.09 (+0.00) | no | no | no | yes | yes | fail |
| TC medium (11) | maxima | IS | -56.74 | -71.53 / -40.33 | 0 | -6.03 | -0.30 | 33.41 / 33.72 (-0.32) | no | no | no | yes | yes | fail |
| TC medium (11) | maxima | OOS | -24.76 | -33.26 / -8.25 | 0 | -5.49 | -0.28 | 22.09 / 22.09 (+0.00) | no | no | no | yes | no | fail |
| high52 (11) | operating | IS | -10.40 | -15.09 / -1.13 | 1 | -1.01 | -0.05 | 33.59 / 33.72 (-0.14) | no | no | no | yes | yes | fail |
| high52 (11) | operating | OOS | -13.99 | -18.06 / -9.25 | 0 | -3.01 | -0.15 | 22.09 / 22.09 (+0.00) | no | no | no | yes | yes | fail |
| high52 (11) | maxima | IS | -18.99 | -27.88 / -10.52 | 1 | -1.87 | -0.09 | 33.56 / 33.72 (-0.16) | no | no | no | yes | yes | fail |
| high52 (11) | maxima | OOS | -16.16 | -22.28 / -10.29 | 0 | -3.50 | -0.18 | 22.09 / 22.09 (+0.00) | no | no | no | yes | yes | fail |
| TC short (3) | operating | IS | -24.39 | -29.55 / -19.67 | 0 | -2.42 | -0.12 | 33.72 / 33.72 (-0.00) | no | no | no | yes | yes | fail |
| TC short (3) | operating | OOS | -5.48 | -7.67 / -3.45 | 0 | -1.16 | -0.06 | 22.09 / 22.09 (+0.00) | no | no | no | yes | yes | fail |
| TC short (3) | maxima | IS | -38.78 | -41.23 / -34.93 | 0 | -3.97 | -0.19 | 33.72 / 33.72 (-0.00) | no | no | no | yes | yes | fail |
| TC short (3) | maxima | OOS | -7.62 | -9.40 / -6.49 | 0 | -1.61 | -0.09 | 22.09 / 22.09 (+0.00) | no | no | no | yes | yes | fail |
| RS medium (3) | operating | IS | -10.63 | -17.54 / -3.18 | 0 | -1.03 | -0.06 | 34.09 / 33.72 (+0.37) | no | no | no | yes | yes | fail |
| RS medium (3) | operating | OOS | -7.20 | -13.31 / -2.15 | 0 | -1.52 | -0.07 | 21.46 / 22.09 (-0.63) | no | no | no | yes | yes | fail |
| RS medium (3) | maxima | IS | -19.31 | -23.11 / -12.11 | 0 | -1.90 | -0.10 | 34.67 / 33.72 (+0.95) | no | no | no | yes | yes | fail |
| RS medium (3) | maxima | OOS | -3.09 | -8.29 / +1.09 | 6 | -0.65 | -0.03 | 21.55 / 22.09 (-0.54) | no | no | no | yes | yes | fail |

## Overlay account, SPY reference and the standalone book (40 orders, base costs)

The standalone book and the sleeve share are context only and carry no verdict.

| Book | Cap set | Period | SPY reference net % | Standalone book net % p50 | Account net % p5 | Account net % p50 | Account net % p95 | Account CAGR % p50 | Account Sharpe p50 (SPY) | Account max DD % p50 (SPY) | Standalone Sharpe p50 | Standalone max DD % p50 | Standalone exposure % p50 | Mean share of account in the sleeve % |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| TC medium (11) | operating | IS | +131.57 | +10.37 | +83.31 | +96.75 | +110.17 | +13.57 | 0.77 (0.94) | 33.52 (33.72) | 0.46 | 7.32 | 23.8 | 81.8 |
| TC medium (11) | operating | OOS | +51.33 | +6.28 | +26.39 | +38.59 | +51.63 | +9.58 | 0.59 (0.73) | 22.09 (22.09) | 0.42 | 5.18 | 17.8 | 83.0 |
| TC medium (11) | maxima | IS | +131.57 | +28.06 | +60.05 | +74.84 | +91.25 | +11.07 | 0.65 (0.94) | 33.41 (33.72) | 0.68 | 10.65 | 44.7 | 61.7 |
| TC medium (11) | maxima | OOS | +51.33 | +11.75 | +18.07 | +26.57 | +43.08 | +6.83 | 0.45 (0.73) | 22.09 (22.09) | 0.48 | 8.20 | 33.4 | 66.4 |
| high52 (11) | operating | IS | +131.57 | +6.93 | +116.48 | +121.17 | +130.45 | +16.09 | 0.90 (0.94) | 33.59 (33.72) | 0.45 | 5.12 | 12.5 | 91.8 |
| high52 (11) | operating | OOS | +51.33 | -1.67 | +33.26 | +37.34 | +42.08 | +9.30 | 0.58 (0.73) | 22.09 (22.09) | -0.13 | 4.57 | 12.5 | 88.5 |
| high52 (11) | maxima | IS | +131.57 | +11.42 | +103.69 | +112.59 | +121.05 | +15.23 | 0.85 (0.94) | 33.56 (33.72) | 0.44 | 8.24 | 22.2 | 84.9 |
| high52 (11) | maxima | OOS | +51.33 | +2.40 | +29.05 | +35.17 | +41.04 | +8.81 | 0.55 (0.73) | 22.09 (22.09) | 0.16 | 6.84 | 22.4 | 78.9 |
| TC short (3) | operating | IS | +131.57 | +15.28 | +102.03 | +107.19 | +111.90 | +14.68 | 0.83 (0.94) | 33.72 (33.72) | 0.86 | 5.69 | 17.8 | 86.7 |
| TC short (3) | operating | OOS | +51.33 | +9.29 | +43.65 | +45.84 | +47.88 | +11.16 | 0.66 (0.73) | 22.09 (22.09) | 0.84 | 2.73 | 11.7 | 89.3 |
| TC short (3) | maxima | IS | +131.57 | +14.40 | +90.35 | +92.79 | +96.64 | +13.13 | 0.75 (0.94) | 33.72 (33.72) | 0.58 | 8.53 | 24.4 | 81.2 |
| TC short (3) | maxima | OOS | +51.33 | +13.73 | +41.93 | +43.71 | +44.84 | +10.70 | 0.64 (0.73) | 22.09 (22.09) | 0.99 | 4.21 | 15.2 | 85.8 |
| RS medium (3) | operating | IS | +131.57 | +6.94 | +114.04 | +120.94 | +128.40 | +16.07 | 0.89 (0.94) | 34.09 (33.72) | 0.34 | 8.42 | 16.4 | 89.2 |
| RS medium (3) | operating | OOS | +51.33 | +3.65 | +38.01 | +44.13 | +49.18 | +10.79 | 0.65 (0.73) | 21.46 (22.09) | 0.30 | 6.77 | 15.5 | 86.0 |
| RS medium (3) | maxima | IS | +131.57 | +13.37 | +108.46 | +112.26 | +119.46 | +15.20 | 0.84 (0.94) | 34.67 (33.72) | 0.43 | 11.67 | 28.4 | 80.4 |
| RS medium (3) | maxima | OOS | +51.33 | +10.87 | +43.03 | +48.23 | +52.42 | +11.67 | 0.69 (0.73) | 21.55 (22.09) | 0.59 | 8.98 | 25.5 | 76.6 |

## Sleeve shortfalls (sessions on which the book asked for more than the sleeve held)

| Book | Cap set | Period | Sessions with K < 0 (all 40 orders) | Orders affected / 40 | Largest shortfall $ | Largest shortfall, % of account value | On | Smallest sleeve value $ | Above the 1% limit |
|---|---|---|---:|---:|---:|---:|---|---:|---|
| TC medium (11) | operating | IS | 0 | 0 | 0.00 | 0.00 | - | 13737.24 | no |
| TC medium (11) | operating | OOS | 0 | 0 | 0.00 | 0.00 | - | 9775.62 | no |
| TC medium (11) | maxima | IS | 0 | 0 | 0.00 | 0.00 | - | 1924.74 | no |
| TC medium (11) | maxima | OOS | 94 | 33 | 2097.15 | 7.53 | 2023-02-03 | -2097.15 | YES |
| high52 (11) | operating | IS | 0 | 0 | 0.00 | 0.00 | - | 22028.12 | no |
| high52 (11) | operating | OOS | 0 | 0 | 0.00 | 0.00 | - | 15374.64 | no |
| high52 (11) | maxima | IS | 0 | 0 | 0.00 | 0.00 | - | 11128.58 | no |
| high52 (11) | maxima | OOS | 0 | 0 | 0.00 | 0.00 | - | 5950.30 | no |
| TC short (3) | operating | IS | 0 | 0 | 0.00 | 0.00 | - | 14110.75 | no |
| TC short (3) | operating | OOS | 0 | 0 | 0.00 | 0.00 | - | 12657.41 | no |
| TC short (3) | maxima | IS | 0 | 0 | 0.00 | 0.00 | - | 3129.59 | no |
| TC short (3) | maxima | OOS | 0 | 0 | 0.00 | 0.00 | - | 3876.40 | no |
| RS medium (3) | operating | IS | 0 | 0 | 0.00 | 0.00 | - | 24403.28 | no |
| RS medium (3) | operating | OOS | 0 | 0 | 0.00 | 0.00 | - | 16740.54 | no |
| RS medium (3) | maxima | IS | 0 | 0 | 0.00 | 0.00 | - | 13962.19 | no |
| RS medium (3) | maxima | OOS | 0 | 0 | 0.00 | 0.00 | - | 11594.12 | no |

## Stress costs (qualifying cells only)

No cell qualified at base costs, so no stress-cost replay was run (the pre-registration repeats qualifying cells only).

## Descriptive only: what the increment is made of (exact split of the pre-registered number; no verdict)

For each replay the final difference from the reference splits exactly into three parts; the table gives the mean over the 40 orders, in points of net return, so the three parts add up to the mean increment. Exit-day part: SPY's open-to-close return on the money a book paid in that day, carried to the end of the period; it is in the account only because the pre-registered accounting takes every flow at the open. Sleeve cost: 5.5 bps of every flow, carried to the end. Remainder: everything else, which is what the same account would show with pay-ins credited at the close of their day and a free sleeve.

| Book | Cap set | Period | Mean increment (pts) | Remainder (pts) | Exit-day part (pts) | Sleeve cost (pts) | Remainder: p5 / p50 / p95 (pts) | Orders with a positive remainder / 40 | Sleeve turnover $ p50 | SPY open-to-close on pay-in days (bps, flow-weighted) | on withdrawal days (bps) | on all days (bps) |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| TC medium (11) | operating | IS | -33.84 | -21.29 | -7.73 | -4.82 | -35.88 / -23.04 / -7.64 | 1 | 1659788 | -18.1 | +12.9 | +1.2 |
| TC medium (11) | operating | OOS | -12.44 | -7.54 | -2.75 | -2.15 | -18.95 / -7.91 / +5.92 | 4 | 884730 | -14.0 | +6.9 | +3.5 |
| TC medium (11) | maxima | IS | -55.97 | -31.87 | -15.20 | -8.90 | -48.47 / -32.79 / -13.42 | 0 | 3201492 | -19.4 | +11.9 | +1.2 |
| TC medium (11) | maxima | OOS | -23.66 | -14.34 | -5.55 | -3.77 | -25.25 / -16.23 / -1.16 | 2 | 1588629 | -15.9 | +11.2 | +3.5 |
| high52 (11) | operating | IS | -9.67 | -5.31 | -2.70 | -1.66 | -10.57 / -6.18 / +2.85 | 3 | 630934 | -16.1 | +6.1 | +1.2 |
| high52 (11) | operating | OOS | -13.81 | -11.26 | -1.54 | -1.01 | -15.79 / -11.10 / -6.21 | 0 | 415629 | -17.2 | +9.0 | +3.5 |
| high52 (11) | maxima | IS | -19.28 | -10.16 | -6.22 | -2.90 | -20.07 / -10.75 / -1.14 | 2 | 1129809 | -21.1 | +9.0 | +1.2 |
| high52 (11) | maxima | OOS | -16.44 | -11.75 | -3.11 | -1.58 | -17.06 / -11.46 / -5.56 | 0 | 673258 | -22.1 | +13.7 | +3.5 |
| TC short (3) | operating | IS | -24.50 | -9.46 | -10.09 | -4.95 | -14.25 / -9.05 / -3.98 | 1 | 1744553 | -23.3 | +12.4 | +1.2 |
| TC short (3) | operating | OOS | -5.51 | +0.62 | -4.01 | -2.11 | -2.02 / +0.75 / +2.97 | 26 | 887356 | -20.1 | +13.7 | +3.5 |
| TC short (3) | maxima | IS | -38.66 | -19.50 | -12.50 | -6.65 | -21.97 / -19.53 / -16.33 | 0 | 2348075 | -21.7 | +12.1 | +1.2 |
| TC short (3) | maxima | OOS | -7.64 | -0.50 | -4.52 | -2.62 | -2.44 / -0.45 / +1.18 | 15 | 1095850 | -18.6 | +14.7 | +3.5 |
| RS medium (3) | operating | IS | -10.24 | -1.06 | -7.44 | -1.74 | -8.12 / -1.39 / +5.77 | 16 | 640955 | -41.7 | +18.4 | +1.2 |
| RS medium (3) | operating | OOS | -7.71 | -5.39 | -1.30 | -1.01 | -10.79 / -5.24 / -0.34 | 1 | 421254 | -18.3 | +7.3 | +3.5 |
| RS medium (3) | maxima | IS | -18.63 | -4.12 | -11.71 | -2.81 | -8.17 / -4.76 / +1.92 | 5 | 1050402 | -40.7 | +10.1 | +1.2 |
| RS medium (3) | maxima | OOS | -3.43 | +0.60 | -2.35 | -1.67 | -4.75 / +0.62 / +5.22 | 23 | 695599 | -18.4 | +6.5 | +3.5 |

Where the books' pay-ins come from (share of dollars, all 40 orders pooled). Only exits on an opening gap and dividends are in hand at the open of their day; the rest arrive during the session or at its close.

| Book | Cap set | Period | Opening-gap stops % | Intraday stops % | Intraday targets % | Time stops at the close % | End-of-period liquidation % | Dividends % |
|---|---|---|---:|---:|---:|---:|---:|---:|
| TC medium (11) | operating | IS | 7.8 | 55.0 | 35.7 | 0.9 | 0.6 | 0.01 |
| TC medium (11) | operating | OOS | 7.6 | 54.3 | 35.3 | 1.0 | 1.8 | 0.01 |
| TC medium (11) | maxima | IS | 8.5 | 52.9 | 36.8 | 1.1 | 0.7 | 0.02 |
| TC medium (11) | maxima | OOS | 8.1 | 53.1 | 36.0 | 1.0 | 1.8 | 0.01 |
| high52 (11) | operating | IS | 8.6 | 47.9 | 37.2 | 5.4 | 0.9 | 0.02 |
| high52 (11) | operating | OOS | 6.0 | 55.8 | 29.7 | 6.2 | 2.3 | 0.01 |
| high52 (11) | maxima | IS | 11.6 | 46.1 | 35.8 | 5.9 | 0.5 | 0.02 |
| high52 (11) | maxima | OOS | 6.8 | 48.6 | 30.7 | 10.4 | 3.5 | 0.01 |
| TC short (3) | operating | IS | 5.7 | 44.8 | 21.7 | 27.5 | 0.3 | 0.04 |
| TC short (3) | operating | OOS | 5.0 | 44.8 | 21.6 | 27.1 | 1.6 | 0.04 |
| TC short (3) | maxima | IS | 7.1 | 45.1 | 20.7 | 26.9 | 0.2 | 0.04 |
| TC short (3) | maxima | OOS | 3.8 | 45.4 | 22.4 | 26.7 | 1.7 | 0.04 |
| RS medium (3) | operating | IS | 8.5 | 46.9 | 27.1 | 15.7 | 1.6 | 0.09 |
| RS medium (3) | operating | OOS | 9.2 | 46.0 | 27.7 | 13.8 | 3.3 | 0.09 |
| RS medium (3) | maxima | IS | 8.2 | 44.0 | 28.2 | 17.8 | 1.7 | 0.11 |
| RS medium (3) | maxima | OOS | 10.2 | 42.3 | 32.1 | 12.7 | 2.7 | 0.10 |

## Descriptive only: the increment by calendar year (median of 40 orders, points; no verdict)

Each entry is the account's return in that calendar year minus SPY's, in points; in brackets the number of the 40 orders with a positive difference. Yearly differences do not add up to the whole-period increment, because both sides compound.

IS:

| Book | Cap set | 2016 (from 10-17) | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 (to 02-10) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| SPY reference return % | | +5.46 | +21.70 | -4.57 | +31.22 | +18.31 | +28.74 | -5.40 |
| TC medium (11) | operating | +0.26 (40) | -4.44 (4) | -2.20 (4) | -6.31 (1) | -2.14 (3) | -4.33 (2) | -0.20 (10) |
| TC medium (11) | maxima | +0.26 (40) | -3.92 (7) | -4.90 (0) | -8.55 (0) | -4.31 (2) | -9.89 (1) | -0.18 (10) |
| high52 (11) | operating | +0.00 (0) | -0.37 (12) | -0.15 (19) | +0.30 (29) | -1.57 (0) | -3.86 (2) | +0.21 (25) |
| high52 (11) | maxima | +0.00 (0) | +0.64 (31) | -0.80 (9) | -0.91 (7) | -5.07 (0) | -4.06 (2) | +0.23 (27) |
| TC short (3) | operating | +0.15 (40) | -5.70 (0) | -2.10 (0) | -3.58 (0) | -1.31 (3) | -0.84 (8) | +0.24 (40) |
| TC short (3) | maxima | +0.15 (40) | -8.10 (0) | -3.08 (0) | -5.87 (0) | -2.46 (0) | -2.29 (0) | +0.25 (40) |
| RS medium (3) | operating | +0.00 (0) | +1.32 (40) | -3.13 (0) | -1.09 (7) | -1.28 (0) | -1.04 (12) | +0.28 (32) |
| RS medium (3) | maxima | +0.00 (0) | +0.91 (32) | -4.04 (0) | -1.58 (6) | -3.74 (0) | -1.98 (3) | +1.11 (40) |

OOS:

| Book | Cap set | 2022 (from 02-11) | 2023 | 2024 | 2025 (to 09-05) |
|---|---|---:|---:|---:|---:|
| SPY reference return % | | -13.56 | +26.18 | +24.89 | +11.10 |
| TC medium (11) | operating | +0.00 (0) | -3.60 (8) | -6.70 (0) | +0.36 (21) |
| TC medium (11) | maxima | +0.00 (0) | -5.53 (2) | -14.31 (0) | -0.55 (13) |
| high52 (11) | operating | +0.00 (0) | -5.66 (0) | -4.78 (1) | -0.96 (7) |
| high52 (11) | maxima | +0.00 (0) | -7.05 (0) | -5.46 (0) | -2.03 (3) |
| TC short (3) | operating | +0.00 (0) | -3.78 (0) | +0.99 (38) | -1.46 (0) |
| TC short (3) | maxima | +0.00 (0) | -5.13 (0) | +1.08 (40) | -2.03 (0) |
| RS medium (3) | operating | +1.64 (40) | -1.97 (9) | -4.05 (1) | -2.30 (1) |
| RS medium (3) | maxima | +2.53 (40) | -0.03 (20) | -4.77 (0) | -1.57 (3) |

## Descriptive only: mean daily active return of the account against SPY (no verdict)

Active return = the account's daily return minus the SPY reference's. The first three columns use the average of the 40 orders' daily active returns; the standard error is the sample standard deviation over sessions divided by the square root of the number of sessions (no allowance for autocorrelation).

| Book | Cap set | Period | Sessions | Mean daily active return (bps) | Standard error (bps) | Mean / SE | Annualised (% a year) | Single orders: mean bps p5 / p50 / p95 | Single orders: median SE (bps) | Orders with a positive mean / 40 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| TC medium (11) | operating | IS | 1340 | -1.174 | 0.259 | -4.53 | -2.96 | -1.730 / -1.204 / -0.717 | 0.421 | 0 |
| TC medium (11) | operating | OOS | 894 | -0.965 | 0.416 | -2.32 | -2.43 | -2.008 / -0.974 / +0.031 | 0.657 | 3 |
| TC medium (11) | maxima | IS | 1340 | -2.046 | 0.534 | -3.83 | -5.16 | -2.726 / -2.068 / -1.393 | 0.710 | 0 |
| TC medium (11) | maxima | OOS | 894 | -1.880 | 0.842 | -2.23 | -4.74 | -2.731 / -1.963 / -0.593 | 1.071 | 0 |
| high52 (11) | operating | IS | 1340 | -0.316 | 0.216 | -1.46 | -0.80 | -0.494 / -0.341 / -0.032 | 0.273 | 1 |
| high52 (11) | operating | OOS | 894 | -1.073 | 0.430 | -2.50 | -2.70 | -1.426 / -1.085 / -0.706 | 0.528 | 0 |
| high52 (11) | maxima | IS | 1340 | -0.639 | 0.365 | -1.75 | -1.61 | -0.942 / -0.626 / -0.334 | 0.413 | 1 |
| high52 (11) | maxima | OOS | 894 | -1.285 | 0.667 | -1.93 | -3.24 | -1.780 / -1.254 / -0.788 | 0.741 | 0 |
| TC short (3) | operating | IS | 1340 | -0.827 | 0.254 | -3.26 | -2.08 | -1.010 / -0.822 / -0.655 | 0.277 | 0 |
| TC short (3) | operating | OOS | 894 | -0.397 | 0.418 | -0.95 | -1.00 | -0.564 / -0.395 / -0.238 | 0.441 | 0 |
| TC short (3) | maxima | IS | 1340 | -1.347 | 0.340 | -3.96 | -3.39 | -1.447 / -1.351 / -1.204 | 0.349 | 0 |
| TC short (3) | maxima | OOS | 894 | -0.558 | 0.487 | -1.15 | -1.41 | -0.697 / -0.556 / -0.469 | 0.495 | 0 |
| RS medium (3) | operating | IS | 1340 | -0.318 | 0.238 | -1.34 | -0.80 | -0.567 / -0.330 / -0.083 | 0.288 | 0 |
| RS medium (3) | operating | OOS | 894 | -0.594 | 0.435 | -1.36 | -1.50 | -1.027 / -0.554 / -0.174 | 0.538 | 0 |
| RS medium (3) | maxima | IS | 1340 | -0.602 | 0.365 | -1.65 | -1.52 | -0.764 / -0.625 / -0.374 | 0.392 | 0 |
| RS medium (3) | maxima | OOS | 894 | -0.263 | 0.675 | -0.39 | -0.66 | -0.640 / -0.234 / +0.077 | 0.709 | 6 |

## Identity check A: the 640 R3-C replays re-run

Every replay must reproduce its row in R3-C's `runs.csv` (random order, outright rejection, base costs). Compared: final equity to the cent, entries and net return (required), and 11 further columns.

| Book | Cap set | Period | Replays | Final equity, entries and net return identical | All compared columns identical |
|---|---|---|---:|---:|---:|
| TC medium (11) | operating | IS | 40 | 40 | 40 |
| TC medium (11) | operating | OOS | 40 | 40 | 40 |
| TC medium (11) | maxima | IS | 40 | 40 | 40 |
| TC medium (11) | maxima | OOS | 40 | 40 | 40 |
| high52 (11) | operating | IS | 40 | 40 | 40 |
| high52 (11) | operating | OOS | 40 | 40 | 40 |
| high52 (11) | maxima | IS | 40 | 40 | 40 |
| high52 (11) | maxima | OOS | 40 | 40 | 40 |
| TC short (3) | operating | IS | 40 | 40 | 40 |
| TC short (3) | operating | OOS | 40 | 40 | 40 |
| TC short (3) | maxima | IS | 40 | 40 | 40 |
| TC short (3) | maxima | OOS | 40 | 40 | 40 |
| RS medium (3) | operating | IS | 40 | 40 | 40 |
| RS medium (3) | operating | OOS | 40 | 40 | 40 |
| RS medium (3) | maxima | IS | 40 | 40 | 40 |
| RS medium (3) | maxima | OOS | 40 | 40 | 40 |
| **All** | | | **640** | **640** | **640** |

## Identity check B: accounting unit tests

| Test | Result |
|---|---|
| (i) SPY returns set to zero and sleeve cost zero: V equals the book's own equity E on every session | passed for 640 of 640 replays; largest difference $2.9e-11 |
| (ii) a book with no trades, IS: V equals the SPY reference path (reference built separately as a share count) | passed on 1340 sessions; largest difference $1.6e-10 |
| (ii) a book with no trades, OOS: V equals the SPY reference path (reference built separately as a share count) | passed on 894 sessions; largest difference $1.1e-10 |
| (extra) every account rebuilt as a SPY share ledger, traded in shares at each open | equal to the recursion for 640 of 640 replays; largest difference $7.4e-10 |
| Sessions on which a book's cash was below zero (the floor at 0) | 0 |
| (extra) a three-session example worked by hand in the script (every K, V, cost and the three-part split) | passed |

### (iii) The pre-registered SPY reference next to the R3-C figure

| Period | Reference | Net % | CAGR % | Max DD % | Sharpe | Final value $ |
|---|---|---:|---:|---:|---:|---:|
| IS | R3-C (`funded_replay_report.spy_benchmark`, reproduced here) | +130.13 | +16.96 | 33.62 | 0.94 | 69038.91 |
| IS | R4-O pre-registered reference | +131.57 | +17.10 | 33.72 | 0.94 | 69472.37 |
| OOS | R3-C (`funded_replay_report.spy_benchmark`, reproduced here) | +50.60 | +12.16 | 21.93 | 0.72 | 45181.12 |
| OOS | R4-O pre-registered reference | +51.33 | +12.31 | 22.09 | 0.73 | 45397.84 |

Where the difference comes from, one convention at a time:

| Step | IS final $ | IS net % | OOS final $ | OOS net % |
|---|---:|---:|---:|---:|
| R3-C figure: whole shares, 5.5 bps on every buy, dividends paid and reinvested on the pay date, valued net of a 5.5 bps exit cost | 69038.91 | +130.13 | 45181.12 | +50.60 |
| the same without the exit cost | 69077.16 | +130.26 | 45205.96 | +50.69 |
| fractional shares with no idle cash, one 5.5 bps cost on the first purchase only, dividends still on the pay date | 69299.95 | +131.00 | 45350.15 | +51.17 |
| pre-registered reference: dividends credited on the ex-date and reinvested at that open | 69472.37 | +131.57 | 45397.84 | +51.33 |

## Scope actually run

- trend_continuation.medium_swing (strategy version 3, snapshot 11): 147 symbols replayed (22 with dividend rows), skipped for incomplete bars: BKNG, VST, XLC.
- high52_breakout.medium_swing (strategy version 13, snapshot 11): 147 symbols replayed (22 with dividend rows), skipped for incomplete bars: BKNG, VST, XLC.
- trend_continuation.short_swing (strategy version 2, snapshot 3): 23 symbols replayed (22 with dividend rows), skipped for incomplete bars: XLC.
- relative_strength.medium_swing (strategy version 5, snapshot 3): 23 symbols replayed (22 with dividend rows), skipped for incomplete bars: XLC.
- Cap sets: operating = open risk 1.5%, gross 60.0%, 2 accepts per day; maxima = open risk 3.0%, gross 100.0%, no daily cap. Both: per-trade risk 0.5%, symbol 10.0%, sector 20.0%, $30000 cash.
- Replays: 640 at base costs (4 books x 2 cap sets x 2 periods x 40 orders, seeds 20261110..20261149), 0 at stress costs. Sessions: IS 1340, OOS 894.
- SPY legs: 21 ex-dates in IS ($28.26 a share) and 14 in OOS ($23.48); price-only return +110.86% and +44.02%, total return before cost +131.70% and +51.41%.
- Sleeve cost: 5.5 bps of every flow at base costs. Reference: $69472.37 at the end of IS and $45397.84 at the end of OOS from $30,000.

## Expectations stated in advance, against the outcome

| Expectation in the pre-registration | Outcome |
|---|---|
| Every overlay account will be far above its standalone book | Confirmed: 640 of 640, by +10.4 to +118.8 points of net return (median +41.8). |
| No cell is expected to qualify | Confirmed: 0 of 8. Every cell fails the net-return, Sharpe and 36-of-40 conditions in both periods. |
| Increments negative in IS | Confirmed: median −10.4 to −56.7 points; 2 of 320 IS replays above the reference. |
| Increments near zero in OOS | Not confirmed on the pre-registered number: median −3.1 to −24.8 points, 9 of 320 OOS replays above the reference. Near zero only for the remainder of the split, and only in three cells. |
| The short trend book closest | Partly. In OOS the closest median is relative_strength.medium on the maximum caps (−3.1), then trend_continuation.short (−5.5 and −7.6). In IS trend_continuation.short is not close (−24.4 and −38.8). |

## Deviations and clarifications

No pre-registered cell, order, cap set or rule was dropped, added or changed, and nothing was
tuned after results were seen. Points 1 to 3 are choices the pre-registration left open and
were fixed in the script before its first run. Point 16 lists what was added afterwards.

1. **Total return from prices plus dividends.** The pre-registration says "adjusted prices".
   In this database the stored bars are split-adjusted but not dividend-adjusted: on all 2,234
   SPY bars of the window the adjusted close equals the close, the dividend field is zero and
   the split factor is one. Total return is therefore built from prices and SPY's 35 dividend
   rows (21 ex-dates in IS, 14 in OOS), loaded with the same library loader the R3-C SPY
   reference uses: overnight leg = (open + dividend on its ex-date) ÷ previous close − 1,
   intraday leg = close ÷ open − 1. That is a holder who puts each dividend back into SPY at
   the ex-date open. A dividend-adjusted price series would differ only in second order.
2. **Cost of the opening purchase.** The recursion as written charges flows only. The sleeve's
   first purchase of SPY with the starting $30,000 is charged the reference's own one-time
   cost (5.5 bps, $16.50), so a book that never trades reproduces the reference exactly
   (identity check B-ii). Without that charge every increment would be 0.13 points higher in
   IS and 0.08 in OOS.
3. **First session.** The account starts in cash and buys at the first open, so the first
   session has no overnight leg, in both periods. A book's own flow on the first session is
   charged by the recursion like any other, on top of the opening purchase. Only
   relative_strength.medium trades on the first OOS session (largest flow $10,617.90);
   netting that flow against the opening purchase would save at most about $12, or 0.06
   points by the end.
4. **Every flow at the open, exits included (pre-registered; its effect is measured, not
   changed).** `F_t` is the day's net change in book cash, taken at the open. Exit proceeds
   are thus invested in SPY from the open of the day they arrive, while the book also held the
   position until its exit. Only opening-gap stops and dividends are in hand at the open. The
   "exit-day part" of the split table is exactly what this adds to each increment (−1.3 to
   −15.2 points). The verdicts use the pre-registered accounting unchanged.
5. **Sleeve shortfall.** Counted on `K_t` as defined (the close of the session) and expressed
   as a share of `V_t` on the same session. The recursion continues with a negative sleeve, as
   stated; nothing is floored.
6. **Floor on book cash.** Book cash was never below zero (0 sessions in 640 replays), so the
   floor at 0 never applied.
7. **Statistics.** numpy's default linear interpolation for the 5th, 50th and 95th
   percentile, as in R3-C; "positive" is strictly above zero. The reference is one path per
   period, so a median increment is the median account figure minus the reference's.
8. **Metrics.** R3-C's own function (`funded_replay_report.equity_metrics`) on the daily
   account value from $30,000: Sharpe = mean ÷ sample standard deviation of daily simple
   returns × √252 with a zero cash rate; CAGR over calendar days; the drawdown peak starts at
   $30,000. The same function is applied to the reference.
9. **The reference against the R3-C figure.** The pre-registered reference is +131.57% in IS
   and +51.33% in OOS; R3-C printed +130.13% and +50.60%, which this script reproduces
   exactly from the same library function. The difference (+1.44 and +0.72 points) is
   convention: no exit cost in the final value (+0.13, +0.08), fractional shares with no
   idle cash and no cost on reinvested dividends (+0.74, +0.48), and dividends credited on
   the ex-date instead of the pay date (+0.57, +0.16). The bridge table shows each step.
10. **Stress costs.** Not run: no cell qualified, and the pre-registration repeats qualifying
    cells only. (The script would have charged the reference the same 11 bps as the sleeve.)
11. **Dividends are not like for like.** As in R3-C (point 17): the sleeve earns SPY's full
    total return, a book is credited cash dividends only for symbols that have dividend rows
    (22 of 147 on snapshot 11, 22 of 23 on snapshot 3). This understates the two snapshot-11
    books by roughly 4.8 points in IS and 2.4 in OOS on the 2%-a-year arithmetic above (a
    simple sum that ignores compounding in the sleeve; a rough size, not a ceiling).
12. **Split rows dated after the window (R3-C point 19, restated).** The four books are
    R3-C's cached books. Their dividends were loaded by the library loader
    (`funded_replay_report._dividends`), which reads a symbol's split rows with no date bound
    and divides each dividend by the ratio of every later split, so amounts are on the share
    basis of the stored bars. For 5 replayed symbols those rows include a split dated after
    the window, and their 176 dividend rows are rescaled by it. Read to the letter that is
    outside "nothing on or after 2025-09-07 is loaded"; it is kept for the reasons R3-C gives
    and is unchanged here. This study's own database read is SPY's bars and SPY's dividend
    rows inside the window; SPY has no split rows. No price, bar or ex-date after 2025-09-05
    is read.
13. **Cached books, checked.** Bars, sectors, dividends and signal tables come from R3-C's
    cache. SPY's bars and dividends in each cached book equal a fresh window-bounded read of
    the scratch copy, the cap sets equal those read from the scratch copy, and all 640
    replays reproduce their R3-C rows (identity check A).
14. **Warm-up and fresh cash (R3-C points 1 and 2).** IS contains each rule's own warm-up;
    first book flows are 2016-12-29 (both trend_continuation books), 2017-08-03
    (relative_strength.medium) and 2017-10-18 (high52). In OOS the account and the reference
    both start with $30,000 at the open of 2022-02-11; the first book flow is 2022-02-11 for
    relative_strength.medium and 2023-02-03 for the other three books. Until a book's first
    flow the account is the reference, to the cent.
15. **Last session.** The standalone replay liquidates the book at the last close; that cash
    is a flow into the sleeve like any other (0.2% to 3.5% of pay-ins).
16. **Added after the first results were seen; none carries a verdict.** The script was run
    in full three times. The first run produced every decision quantity and verdict. Checking
    its magnitudes against a rough close-to-close estimate exposed the exit-day effect of
    point 4, so the second run added the three-part split and took the reference from the
    same recursion as the accounts (so a stretch without trades differs by exactly zero); no
    per-replay figure moved by more than 1.2e-12. The third run added a hand-worked
    three-session example, the pay-in sources and a file of the SPY legs; it is identical to
    the second in every shared column. No accounting line, cell or rule changed between runs.
    Also beyond the pre-registration: a share-ledger re-implementation inside the script, and
    a separate verification script that shares no code with the study and rebuilds the SPY
    legs from the database, every account, the split, the cell statistics and the verdicts
    (all checks passed). The split's "exit-day part" is computed on each day's net pay-in,
    not on gross exit proceeds.
17. **CPU.** One process throughout; a full run takes about four minutes.
18. **Timing.** Every replay, account and check was computed on 2026-11-10 between 11:50
    and 12:09 UTC (final run saved 12:09 UTC, verification 12:09 UTC). The last step,
    rendering the tables from the saved `summary.json` and assembling this file, ran at
    23:00 UTC, after the round's 19:00 UTC cut-off for computing. It reads no market data
    and changes no number, but it is past the cut-off and is recorded here as a deviation. After the reviews, the
    wording of this file was edited by hand at about 23:06 UTC (the split labelled as added
    after the results wherever it is used, the relative_strength.medium IS remainder
    described as close to zero, "net pay-in" made explicit, "at most" replaced by "roughly"
    for the dividend size). No script was run for those edits, no number changed, and the
    study script is byte-identical to the one that produced `summary.json`.

## What the result does and does not license

As pre-registered: a fail means the rule subtracts from an index core on this sample; standing
alone it is profitable only because it is long equities part of the time. All eight cells
fail, and the OOS increments are not near zero as expected (medians −3.1 to −24.8 points).

Description only, from the split added after the first results were seen (not
pre-registered, no verdict): in IS the remainder is negative on average in all eight cells,
though for relative_strength.medium on the operating caps it is close to zero (−1.06 points,
16 of 40 orders positive); in OOS it is negative in five cells and about zero in three
(+0.62, −0.50, +0.60). The exit-day part and the sleeve cost make up the rest of each gap.

It does not say a standalone book is a worse thing to hold than the index for an operator who
values its much smaller drawdown (median 2.7% to 11.7%, against 22.1% and 33.7% for SPY). That
is a choice about how much index exposure to carry, which this study does not test. Nothing
here changes the operating scan, ledger, risk limits or any frozen study, and a sleeve in the
operating paper books is an operator decision for a future study generation. All periods are
already-observed development data.

## Reproduce

```sh
cd <scratch>/r3            # a directory with no .env
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=<worktree>/src:<worktree>/scripts MARKET_DATA_PROVIDER=massive \
SIGNALFORGE_DATA_DIR=<scratch>/r3/db \
DATABASE_URL="sqlite+pysqlite:///file:<scratch>/r3/db/signalforge.sqlite?mode=ro&uri=true" \
<venv>/bin/python <worktree>/scripts/r4/core_overlay.py all        # identity checks, accounts, verdicts, tables
<venv>/bin/python <worktree>/scripts/r4/core_overlay_verify.py     # independent re-computation
```

Needs the R3-C outputs (`<scratch>/r3/out/capacity/`: `identity.json`, `runs.csv`,
`cache/*.pkl`). Raw outputs (not committed), under `<scratch>/r3/out/r4-overlay/`:
`replays.csv` (640 rows), `replays_by_year.csv`, `marks_base.npz` (daily book equity and cash
of every replay), `spy_legs.csv`, `summary.json`, `tables.md`, `run.log`, `verify.log`, and
`firstpass/` and `secondpass/` (the outputs of the two earlier runs).

Research signal only — no order was placed.
