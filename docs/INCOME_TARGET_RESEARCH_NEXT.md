# Income-target diagnostic protocol — November 3, 2026

This is descriptive engineering research on already-observed history. It is not
an untouched test, a promotion decision, or an optimization toward dollar targets.
The frozen Kronos experiment, production settings and paper books are excluded.

## Fixed diagnostic run

Before running the broader-universe result, fix:

- Capital $10,000, no deposits, no borrowing; unchanged short-swing trend strategy.
- 2016-10-17 through 2026-11-02 inclusive; session warmup remains 50 bars.
- The repository's 25-symbol default universe, with **explicit data-only exclusions**:
  META lacks 1,273 requested sessions (history starts 2021-06-30); XLC lacks
  420 sessions before its 2018-06-19 inception. Neither is ranked by outcome.
  This leaves 23 symbols with 2,525 daily sessions each. This complete-case
  selection and today's survivor universe are biases, not point-in-time construction.
- Existing per-trade/open-risk limits, 5% initial position, 20% sector,
  60% portfolio notional cap, whole shares and previous-volume participation.
- Three fixed cost scenarios: default 3bps slippage + 5bps full spread, no
  commission; zero fees/spread/slippage with adverse cent rounding retained;
  stress 10bps slippage + 10bps full spread and $0.005/share/$1 minimum commission.
  These are sensitivity assumptions, not observed broker prices or a parameter search.
- A passive price-return reference buys up to 5% per name/20% per sector at the
  first opening price, subject to a 60% aggregate initial budget, holds to the
  same terminal close, and retains cash. It has
  no stop/open-risk budget and is not risk-equivalent. Both paths exclude dividends.
- Report all three outcomes, accounting reconciliation, exposure, target misses,
  cost sensitivity and symbol contributions. Never choose a scenario to promote.
- No future result in this diagnostic can authorize production trading or alter
  risk limits, study rules, candidate promotion or a sealed-test record.

## Required engineering and research changes

1. Fix listing/ticker lifecycle and point-in-time universe eligibility before
   claiming complete coverage. Do not fill pre-inception dates or silently stitch
   META/FB without corporate-action and identifier evidence.
2. Reconstruct contemporaneous raw share lots and split events rather than
   treating adjusted historical prices as historical executable ticks. Add
   dividend cash accounting, point-in-time earnings exclusions and historical
   sector assignments; cross-check corporate adjustments. The current hashes pin
   bar projections, not completeness of these missing datasets.
3. Mirror scanner price/ADV/event eligibility in the offline engine; its current
   previous-volume cap is insufficient. Add a separately tested portfolio drawdown
   entry halt and better liquidity and market-impact modeling before promotion. Do not loosen current caps to force income.
4. Evaluate unchanged baseline strategies and predeclared simple ablations on
   chronological development periods, using one funded ledger and comparable
   benchmarks. Record negative experiments. No selection on this full-history run.
5. Any genuinely new hypothesis needs a new version and prospective holdout or
   new forward-paper observations: already-reviewed history cannot become unseen.
6. Weekend research requires a separate validated continuous-market dataset and
   causal funded engine. Equity closure marks cannot establish weekend income.

At $10,000 opening equity the requested $1,000 daily threshold equals 10% of
initial equity per day; $5,000/workweek equals 50%, and $400/weekend equals 4%.
These are arithmetic requirements, not expected returns or feasible forecasts.
Raising capital alone cannot establish a reliable edge, and liquidity/whole-share
constraints make extrapolation from a small-account result invalid.

Benchmark implementation correction: the first diagnostic omitted the 60%
aggregate initial budget in the passive reference. That is now enforced and
tested. Superseded comparator results are not evidence for choosing a strategy;
the trading baseline and every income target result were unchanged.
