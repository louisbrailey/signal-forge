# Funded replay of the approved equity set vs SPY total return (2026-11-08)

DESCRIPTIVE, development window only (2016-10-17..2025-09-07, snapshot 11, 147 replayable
symbols; BKNG, VST and XLC skipped for incomplete bars). Not a sealed test and not a promotion
input. Produced by `scripts/funded_replay_report.py` on scratch database copies via workflows
`sf-unblock-evidence` and `sf-funded-risk-scaling`; the scaling grid was attacked by a code
reviewer and a conclusions reviewer, and every finding was fixed and the grid re-run.
Raw outputs: `reports/funded/` and `reports/funded/scaling/` (not committed).

## Setup

One shared cash account, next-open fills, whole shares, base / stress / zero cost cases,
cash dividends booked (22 of 147 symbols have dividend rows), per-trade risk 0.5%, sector 20%,
per-symbol 5% or 10% (paper maximum), open risk 1.5% or 3.0% (paper maximum), gross 60% or
100%. SPY benchmark: total return, dividends reinvested in whole shares, same costs.
Exposure-matched SPY: SPY total return held at the run's mean exposure, rebalanced daily.

## Headline

**No approved equity strategy or composite beats SPY buy-and-hold on a risk-adjusted basis
once realistic costs and dividends are counted.**

| Configuration ($10k, 10% cap) | Case | Net % | CAGR % | Max DD % | Sharpe | Mean exposure % |
|---|---|---:|---:|---:|---:|---:|
| SPY total return | base | +245.0 | 14.9 | 33.3 | 0.86 | ~98 |
| high52, open risk 1.5% | base | +20.3 | 2.1 | 3.8 | 0.70 | 12.5 |
| high52, open risk 1.5% | stress | +6.3 | 0.7 | 7.3 | 0.25 | 11.8 |
| trend_continuation.short, open risk 3% | base | +60.1 | 5.4 | 13.6 | 0.77 | 37.3 |
| trend_continuation.short, open risk 3% | stress | −12.3 | −1.5 | 23.7 | −0.18 | 34.4 |
| relative_strength.medium, open risk 3% | base | +35.0 | 3.4 | 14.8 | 0.53 | 30.5 |
| high52 + RS composite, open risk 3% | base | +33.0 | 3.3 | 14.0 | 0.49 | 32.3 |
| high52 + TC-short + RS composite, open risk 3% | base | +29.5 | 3.0 | 14.7 | 0.43 | 39.0 |

- Exposure-matched SPY has Sharpe 0.86 at every exposure; no realistic-cost run reaches it.
  The only run ahead of it on return/drawdown (high52 at 1.5% open risk, base costs) is the best
  of 36 cases on already-seen data and falls behind under stress costs.
- trend_continuation.short and trend_continuation.medium turn negative under stress costs.
  trend_continuation.medium is also the weakest sealed pass (+0.039R / 602) and should not be
  counted as part of a profitable set.
- Raising open risk from 1.5% to 3.0% adds drawdown with no reliable return gain.
- Composites do not beat their best member in a way that survives the cost cases; in a shared
  account the higher-frequency rules fill the risk budget first (high52 got 22 entries inside
  the four-strategy composite at 1.5% open risk).

## Noise warning

Booking about $30–60 of dividend cash moved high52 (open risk 3%, gross 100%, base) from +12.6%
to −0.2% by changing which candidates were admitted. Cost-case spreads of net return are
7–22 percentage points for high52 and 39–92 for the others. Rank configurations only on
differences larger than that, ideally after a jittered admission-order test. At $10k
whole-share rounding is material; scaling conclusions come from $25k vs $50k.

## What this means

Per-trade edges measured in R are real in development and sealed data, but at the paper risk
limits these rules sit in cash 60–90% of the time and their invested returns do not compensate.
"Proven profitable" against the obvious alternative (holding SPY) is not established for the
equity book. Paths that could change this, none of them tested yet:

- Use the rules as an overlay on a core index position rather than as a standalone account.
- Trim-to-remaining-budget sizing instead of outright rejection (needs a pre-registered test).
- Forward paper evidence for high52 (unblocked on 2026-11-08 by recording its development OOS
  backtest, `backtest_run` 49: 525 OOS trades, +0.227R, CI [+0.098, +0.353]).
