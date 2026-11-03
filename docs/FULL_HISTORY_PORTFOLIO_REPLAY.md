# Full-history funded portfolio replay — implementation contract

Status: planned; no funded historical performance is established by the existing sequential trade-R reporter.

## Boundaries

The descriptive replay covers all eligible observations in a pinned operating-data snapshot, with every excluded symbol/date and reason reported. It does not access the frozen Kronos comparison databases or award a new sealed look. Disclosed final-test periods must be labelled previously observed. “100% history” means an accounted-for input denominator, not forcing every instrument into every strategy.

## Existing components and missing integration

`backtest.engine` supplies next-bar entry timing and pessimistic stop-before-target exits with modeled fill costs. `backtest.costs.CostModel` supplies commission, half-spread and slippage assumptions. `risk.engine` owns existing sizing limits; `paper.ledger` owns account behavior. `research.portfolio_metrics` compounds sequential trade R and must not supply the funded portfolio equity curve.

The missing component is one chronological portfolio event loop across all selected instruments, with simultaneous reservations, a historical account state and daily net-liquidation marks. Reusing individual trades after seeing their eventual returns would violate causal candidate admission.

## Build slices and acceptance

1. Pin dataset identifier, source hashes, strategy/spec/config versions, development boundaries, benchmark and experiment ID before execution. Validate calendars, corporate actions, numeric sanity and gaps. Missing observations produce explicit exclusions or a halt; no interpolation or silent dropping.
2. At each session close, evaluate the unchanged rules with information available then. Persist input timestamps and all rejected signals. Reserve entries in deterministic contemporaneous ranking order; do not rank by eventual profitability. Process entries at the next available permitted open using the existing fill assumptions.
3. Maintain one funded cash balance, concurrent positions and reserved cash. Enforce the strictest applicable existing risk limits, no leverage, concentration, correlation, cash sufficiency and whole-share constraints. Rejections must name the binding rule. Every fill consumes fees, spread and slippage exactly once; gap risk may exceed a stop budget and must be reported.
4. Mark open positions each session, retain idle periods and cash flows, apply exits and corporate actions causally, and record daily net liquidation. Non-trading days require explicit valuation policy; do not treat missing marks as zero returns. Equity weekends cannot imply weekend executable opportunities.
5. Export the explicit daily panel to `scripts/income_target_report.py`. Report daily/weekly/weekend target misses, costs, exposure, drawdown, uncertainty, benchmarks, and per-regime contributions. Distinguish an unrealized mark gain from withdrawable income.

## Required tests before historical results

- Two simultaneous signals cannot spend the same cash or exceed combined risk limits.
- A signal never fills at the bar used to create it; changing future prices cannot change earlier admissions.
- Rising cash from a deposit is not trading profit; commission and spread are charged once on both sides.
- Missing marks, splits, delistings and unavailable event history fail explicitly.
- Gap-through-stop and same-bar stop/target cases use the existing conservative policy.
- Restart/replay produces identical records from pinned input and does not mutate operating accounts.
- A zero-trade portfolio matches cash, while the matched benchmark uses the same dates and capital constraints.

The dollar target is a reporting threshold. It must never select parameters, increase risk, force trades or suppress failed runs. Acceptance of the engine requires accounting and causal invariants, not a desired return.
