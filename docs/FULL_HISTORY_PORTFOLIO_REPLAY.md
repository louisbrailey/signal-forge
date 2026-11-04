# Full-history funded portfolio replay — implementation contract

Status: an offline daily long-only core and read-only baseline runner are implemented. This is a descriptive research engine, not strategy promotion or production execution.

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

## Implemented core and first data run

`backtest.funded.run_funded_replay` maintains shared cash and concurrent positions, calls the existing sizing engine, caps each initial position at 5% and sector exposure at 20% (or stricter caller limits), and caps allocation by 1% of the previous session’s volume. Stop risk includes entry/exit commissions and modeled exit costs. A crossed stop is rejected at the opening price. Only opening gap stops release cash before new entries; intrabar exits cannot retroactively finance that morning. Stops take priority over targets. Signals see only the prefix through their decision close. Terminal positions are liquidated with costs. Admission order is alphabetical and fixed in advance.

```sh
PYTHONPATH=src uv run python scripts/funded_replay_report.py /absolute/path/signalforge.sqlite \
  --symbols SPY QQQ --since 2016-10-17 --until 2026-11-02
```

The runner opens the operating database read-only, rejects comparison databases, requires complete equal XNYS calendars and clean adjusted non-simulated Massive bars, and records input hashes. Missing data halts rather than silently shortening the period.

A November 3 engineering smoke run used the unchanged short-swing trend baseline on SPY/QQQ: 2,525 sessions, 77 closed round trips, $10,000 initial cash, $10,038.53 final cash, and $33.36 modeled fill/commission costs. This final figure uses adverse cent rounding on both sides; the earlier nearest-cent development run returned $10,039.84 and is superseded. Default commission is zero, slippage 3bps and assumed full spread 5bps; these assumptions are not observed execution costs. This is an already-observed descriptive sample, not a sealed or full-universe validation.

## Remaining before full-history validation

Corporate-action cash/dividend accounting, point-in-time event/liquidity eligibility and sector data, a risk-equivalent benchmark, delisting and changing-universe lifecycle handling, and drawdown-triggered entry suspension need implementation and tests. Existing risk controls cover per-trade, total open risk, notional, sector, cash and volume; no new drawdown guard is claimed. No cash-flow API is exposed by this first core. No all-asset or all-history profitability claim follows from the smoke run.

## Income-target diagnostics

The runner now exports calendar-day income evidence, explicit target misses,
round-trip reconciliation, per-symbol P&L, exposure and rejection counts.
`--cost-scenarios` adds fixed zero-fee/spread/slippage and higher-cost cases;
cent rounding remains active. A capped passive reference is reported with its
different risk profile disclosed. Closure carry is allowed only on known XNYS
non-sessions; missing session marks fail. See
[diagnostic results](../reports/INCOME_TARGET_DIAGNOSTICS_2026-11-03.md) and
[research protocol](INCOME_TARGET_RESEARCH_NEXT.md). No strategy or live settings changed.
