# Income-target evaluation: observation before optimization

The requested alternatives are $1,000 every calendar day **or** $5,000 per
Monday-Friday workweek plus $400 per Saturday-Sunday weekend. These are goals, not forecasts.
The weekend amount is treated as a combined weekend amount, not $400 per day.
Calendar-day, weekday-only, weekly and weekend results are reported separately: a profitable Friday
must not conceal four missed daily targets. Holidays/no-trade days remain in
the requested calendar periods. This first evaluator does not declare an income
strategy reliable, authorize execution, increase risk, or promote a strategy.

## What exists and what does not

The October 24 report records small hypothetical gains on two separate $30,000
books, including unrealized marks, and insufficient trades for an edge claim.
Those are dated observations, not a current account balance. See
[paper status](../reports/PAPER_STATUS_2026-10-24.md) and the
[current evidence assessment](../reports/INCOME_TARGET_READINESS_2026-11-03.md).

Sequential trade-R metrics are not daily funded-account P&L. Current-position
snapshots with an `as_of` price date are not historical equity curves. The crypto
paper ledger's illustrative R-to-dollar conversion is not a cash-funded account.
None is an acceptable substitute for the daily account panel below.

## Run the read-only evaluator

```sh
uv run python scripts/income_target_report.py /absolute/path/evidence.json
```

It reads that explicit JSON file and prints JSON to standard output. It does not
open a database, request market data, modify accounts, trade, or persist results.
The report contains an input SHA-256 for reproducibility. Do not provide secrets
or account identifiers; a private local dataset reference and version suffice.

Input shape (the numbers below illustrate the format, not strategy evidence):

```json
{
  "data_kind": "forward_paper",
  "source_reference": "audited-equity-export-v1",
  "strategy_version": "frozen-rule-version-and-config-hash",
  "cost_model_reference": "fees-spread-slippage-borrow-funding-v1",
  "costs_included": true,
  "timezone": "America/New_York",
  "weekend_market_access": false,
  "opening_date": "2026-11-01",
  "opening_valuation_quality": "complete",
  "opening_equity_usd": "30000.00",
  "through_date": "2026-11-02",
  "observations": [
    {
      "day": "2026-11-02",
      "net_liquidation_usd": "29950.00",
      "external_flow_usd": "0.00",
      "valuation_quality": "complete"
    }
  ]
}
```

Requirements and interpretation:

- USD only. Values have cent precision. Data kind is `fixture`, `backtest`, or
  `forward_paper`; fictional test data must never be labeled forward paper.
- Each observation is a daily closing net-liquidation value, including all open
  exposures and explicit external deposits/withdrawals. Positive external flow
  is a deposit; negative is a withdrawal. Unknown flows are not zero.
- Daily P&L = closing value − prior closing value − net external flow. Include
  costs exactly once in values: fees, spread, slippage, borrow/funding and other
  applicable trading costs. Personal tax treatment is not modeled by this tool.
- Net P&L includes unrealized marks. It is not a claim of withdrawable cash or
  realized trading income. Dividends/interest are account earnings, not deposits.
- Supply every calendar day at the same declared local valuation boundary.
  The timezone labels the source's dates; the tool does not convert timestamps.
  A closed-market valuation may use an audited unchanged official close when
  appropriate, but a failed/missing feed must not be labeled complete. No fills
  or weekend profit are inferred from closed markets.
- Missing/stale observations invalidate both their day and the next daily
  difference. Missing dates are not silently filled with zero or bridged into
  a one-day gain. A stale opening mark invalidates the first day's difference.
- Full-period P&L and drawdown are withheld if any daily difference is missing.
  Complete subperiods may still be described and their sample count is explicit.
  Partial boundary weeks/weekends are listed separately and never count as
  complete periods. Zero-P&L periods remain target misses.
- Costs not included: all net-profit statistics withheld. Weekend access not
  established: the report flags it and makes no weekend strategy claim even
  if hypothetical valuations show weekend gains.
- Drawdown uses starting capital plus cumulative cashflow-adjusted dollar P&L,
  not time-weighted returns. Daily closing data omit intraday drawdown. Do not
  use this measure to compare differently funded books as though risk were equal.
- Provenance, cost inclusion, valuation quality and access are supplied assertions,
  not independent verification. A perfect observed hit rate cannot prove future
  reliability; serial dependence, selection and regime changes remain unmeasured.

## Frozen research sequence

1. Preserve all earlier trials, failures, sealed-window boundaries and strategy
   versions. Never optimize against the already-viewed sealed results to chase
   a dollar target. Reconcile legacy corrections and mark quality first.
2. Establish a point-in-time, cash-constrained development replay with the actual
   capital base, simultaneous positions, fees, conservative fills after signals,
   volume/liquidity limits and all applicable borrow/funding costs. Keep current
   risk caps; do not solve an income target by increasing leverage.
3. Run chronological walk-forward with overlap purging appropriate to each holding
   period. Use only pre-sealed development data. Report all attempted rules and
   negative results, turnover, exposure, capital usage and cost stress.
4. For weekend research, first inspect the existing frozen
   [CRYPTO-H1 protocol](research/PREREGISTRATION_CRYPTO-H1_2026-10-27.md), verify
   the original snapshot/cutoffs and run its unchanged development folds only.
   Do not shift a previously frozen sealed boundary. Confirm permissible markets,
   short availability and cost/funding assumptions; a 24/7 dataset is not proof
   that a particular account or strategy can execute on weekends.
5. Report complete calendar P&L distributions and month/block-dependent uncertainty,
   not IID trade confidence. Only evaluate a genuinely untouched final holdout
   under a precommitted protocol. Follow with prospectively logged paper operation,
   including outages and no-trade days. Paper fills remain hypothetical.

No raw operating database or market-history snapshot is included in the cloud
checkout inspected on November 3. The evaluator can be fully tested with fixtures,
but producing current performance evidence or running fresh market-data experiments
requires an authorized, provenance-preserving data snapshot. No earnings target is
claimed achieved while that evidence is absent.
