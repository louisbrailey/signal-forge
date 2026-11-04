# Income-target evidence assessment — November 3, 2026

**Outcome: not established.** This is a repository/source review, not a current
account audit, trading recommendation, or prediction of income. No real trades,
provider calls, account changes, risk increases or deployments were performed.

## Goal and capital context

The alternatives are $1,000 every calendar day or $5,000 per workweek plus $400
per combined weekend. On a hypothetical $30,000 starting book those amounts are
3.33%, 16.67% and 1.33% of initial capital respectively, before compounding.
These are arithmetic target-to-capital ratios, not attainable return forecasts.
Current authorized investable capital is unknown; the $30,000 is from historical
paper documentation. Separate $30,000 books must not be combined while counting
only one book's starting capital.

## What the committed evidence actually says

- [October 24 paper report](PAPER_STATUS_2026-10-24.md): +$409.50 on the original
  $30,000 book and +$74.33 on a second $30,000 book, including unrealized value.
  The report says nine scored trades are insufficient for an edge conclusion.
  Market marks were stale/partial through October 22–23, not current November data.
- [October 26 development round](../docs/research/RESULTS_backtest_round_2026-10-26.md):
  relative-strength development results pass, but its EXPERIMENTAL status requires
  reconciliation with previous audited scope. Mean-reversion/breakout fail gates;
  intraday ORB lacks the needed intraday sessions in that report.
- [FX-2 development results](../docs/research/RESULTS_FX-2_2026-10-26.md): negative
  expectancy and four negative folds. This is not a candidate for a target claim.
- [Calendar-cluster diagnostic](../docs/research/diagnostics/clustered_bootstrap_all.md):
  month-block lower confidence bounds are +0.0125R short-swing, −0.0191R
  medium-swing and −0.0238R relative-strength. All miss that diagnostic's +0.02R
  threshold; short-swing is marginal and seed-sensitive. Correlated trades/books
  must not be treated as independent evidence.
- [Crypto protocol](../docs/research/PREREGISTRATION_backtest_round_2026-10-26.md)
  records one CRYPTO-1 paper rule; not all crypto research failed. The existing
  [CRYPTO-H1 preregistration](../docs/research/PREREGISTRATION_CRYPTO-H1_2026-10-27.md)
  is a bounded possible weekend-development experiment, not verified profitability.

## Critical measurement safeguards

`paper.portfolio` snapshots using `as_of` still read current cash and current
position state and can fall back to entry-price marks. Do not call these a daily
historical net-liquidation series. Crypto's reported dollars are illustrative
R-times-risk values, not a funded-account equity path. Legacy voided trades and
entry-cost corrections must be accounted for before evaluating dollars.

The new read-only [income-target evaluator](../docs/INCOME_TARGET_EVALUATION.md)
accepts an explicit daily USD equity panel, subtracts external flows, preserves
zero/no-trade days, separates calendar-day/weekday/workweek/weekend targets, rejects duplicate
or out-of-window records, withholds invalid/missing/cost-free measures, and reports
cashflow-adjusted drawdown. It never changes strategies or execution state.

No raw database/history dataset exists in this checkout. Therefore no fresh
backtest, forward-paper result, observed target-hit rate or current capital amount
can honestly be reported from this work. The next evidence step is an authorized
read-only snapshot with original provenance and frozen development/holdout boundaries,
followed by the unchanged preregistered development experiment and prospectively
logged paper outcomes. Do not retune on previously disclosed sealed results.

## Integration note

The historical-source discussion above describes the supplied patch's original checkout. In this integration, operating data was inventoried read-only; see [the current assessment](../docs/INCOME_TARGET_ASSESSMENT.md). The November 2 repair audit supersedes earlier expanded-crypto promotion claims. No full-history performance or reliable-income claim follows from this inventory.
