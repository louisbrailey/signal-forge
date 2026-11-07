# R2 fractional share study protocol

Research signal only — no order was placed.

Measure how share increments affect the R1 books. Compare each fractional book
with the corresponding whole-share book and report how many SPY entries the
fractional model can fund in 2025 and partial 2026. The dates and data have
already been examined. These are historical sensitivity results.

## Comparison

Use the R1 archive, verified listing evidence, ten unchanged baselines, ten R1
refinements, and the SPY monthly trend comparator. Reproduce all 441 saved
whole-share books before accepting the paired results. The seven periods, signal
and exit rules, cost cases, liquidity and earnings filters, and starting cash
come from the [R1 protocol](REFINEMENT_STUDY_2026-11-04.md). Each book has $10,000,
a 5% initial position cap, a 20% sector cap, 0.5% per-trade and 1.5% aggregate
risk limits, a 60% exposure cap, 1% volume participation, and a 10% drawdown
entry halt. Cash is shared within each book.

The fractional arm uses 0.001-share entry increments. It retains the original
adverse rounding on each per-share fill price, rounds purchase debits up and
sale proceeds down to cents, and charges the same commission schedule per
actual quantity and side. The stop-risk estimate includes up to two cents of
settlement rounding and both commissions. It floors quantity within available
cash, risk, and volume. The same concurrent portfolio checks run before sizing
reductions for cash, volume, and transaction costs. This precision and cent
settlement policy are study assumptions. Fractional exits liquidate the entire
simulated lot, including sub-increment balances after splits. Dividends use the
held quantity on the ex-date with cent-rounded entitlements and the original
pay-date accounting. This is an offline model of fills and corporate actions.

## Evaluation

Record the 2021–2023 validation comparison before running the 2024–2026
follow-up. Apply the same R1 criteria to compare each refinement with its
fractional baseline. Preserve every disposition, including failed gates. Report
the effect of quantity on entries, returns, drawdown, exposure, and costs for
both arms and all three scenarios. The test of the affordability constraint is
whether fractional SPY entries occur under the same cap where whole-share
entries were refused. Evidence for a strategy change requires a separate
prospective protocol. Keep the study separate from scheduled and operating
books.
