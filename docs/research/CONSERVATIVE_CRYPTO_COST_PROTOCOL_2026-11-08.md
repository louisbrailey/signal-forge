# Conservative crypto cost study — registered 2026-11-08

This is a bounded, descriptive, offline study, separate from operating books and
frozen studies. Base: `bb624d7dcf8f86f75556894acc923877622074b4`.
Checkpoint 94836 and `RESULTS_crypto_funded_vs_hodl_2026-11-08.md` describe the
parent's 33%/100% allocation study; those allocations do not answer this study.
Commit this protocol before any evaluation. No desired-profit search or tuning.

## Frozen experiment

Run the two registered CRYPTO-5 Donchian-55 long-only rules, with their registered
pair lists, parameters, warmup and exit logic. Compare each with the LONG trades
of its actual two-sided parent's harness schedule (discard every SHORT before
portfolio accounting). Also check that filtering the parent's signal to LONG
before scheduling reproduces the registered variant. A parent's discarded SHORT
can occupy its harness schedule, so its LONG legs need not equal the variant.
There are no funded shorts, futures, margin or funding assumptions.

Exactly three independent, initially flat, $10,000 shared-cash windows:

* 2017-01-01–2020-12-31: development.
* 2021-01-01–2023-12-31: validation, already seen by prior research.
* 2024-01-01–2025-10-25: SEEN followup, never called sealed/OOS evidence.

Two schedules × two universes × three windows × two cost cases = 24 portfolio
runs. Reset cash, positions and drawdown high-water mark at each window start;
no carry-in. Prior bars are warmup only. No other configurations/start sweeps.

## Fixed controls and costs

Fractional spot units, rounded DOWN to 18 decimal places. At every admission:
max 5% initial all-in position allocation; 20% crypto theme; 60% gross; 0.5%
modeled all-in stop loss per trade; 1.5% aggregate open modeled stop risk.
All ratios use the lesser of prior-close equity and current-open equity, reduced
by the proposed entry's cost. Existing gross is marked at current actual opens.
Open-risk reserves are the greater of initial all-in stop risk and current-mark
all-in stop risk. Theme/gross caps restrict new entries; passive price drift is
reported, not silently rebalanced. The crypto theme cap dominates gross here.
No negative cash; alphabetical admission order; one position per symbol; no
minimum order assumption (exchange increments/minimums remain unvalidated).

Use `coinbase_spot_intro`: 90 bps taker + venue's existing estimated half-spread
+ `FxGates().slippage_bps` on BOTH sides. Use the harness's additive adverse-fill
convention exactly (no second fee subtraction). Stress multiplies
`venue.engine_spread_bps(pair)` by 2; slippage stays unchanged, as in the harness.
Thus stress doubles fees AND estimated half-spread, not the separate 1 bp slip.
Report fees/spread/slip separately. All-in initial loss per unit is
`raw_entry*(1+side_rate) - stop*(1-side_rate)`; a stop at/above the entry open is
ineligible. A subsequent gap can lose more than modeled stop risk.

A 10% drawdown observed at a close or an available portfolio open permanently
halts new entries for that window. Existing protective/harness exits continue.
This is an entry halt, not a guarantee that realized drawdown stays below 10%.
Entries are processed before ALL that day's exits, including gap exits; neither
exit proceeds nor released risk/gross room can fund entries at that same open.
Skipped harness trades do not trigger an alternative signal search.

## Data boundary, inception, gaps and liquidity

Use explicit sqlite3 `mode=ro` plus `PRAGMA query_only=ON` and one short read
transaction. Inspect the actual table schema. Every bar query is SQL-bounded
`session_date >= '2016-01-01' AND session_date < '2025-10-26'` AND exact
`source = 'massive_crypto'` and registered pair. Never load future history then
cut. No data at/after the parent sealed start is read, even for diagnostics.
No provider requests, operating writes, paper trades, alerts or study updates.
Hash the selected bounded rows for reproducibility; raw private data stays local.

Require valid finite positive OHLC, consistent high/low and unique daily rows;
exclude flagged or explicitly simulated/fixture rows. Absent quality/simulation
fields mean UNKNOWN, never clean/real by assumption. Exact Massive source
provenance is required. Inventory actual volume/spread fields and their coverage.
Without measured volume AND measured venue spreads, liquidity is UNVALIDATED;
no promotable or executable conclusion is permitted.

Admission is inception-aware: no symbol before its first stored qualifying bar
plus the registered warmup, and no requirement that later listings existed in
2017. Evaluate the existing <=1% missing / <=7-day interior-gap policy separately
per pair/window, from its first in-window bar through window end. Fail-closed
breaches remove the pair from BOTH strategy and benchmarks in that window.
Report exclusions, boundary gaps, expected/observed days and each gap interval.
Within tolerance, never invent/forward-fill OHLC bars. Signals require a complete
consecutive warmup history; cancel a candidate whose entry is not the next
calendar day's actual open. If an existing holding lacks today's bar, block new
portfolio entries, mark it at its last observed close for accounting ONLY, and
count stale marks. The harness still resolves exits on actual surviving bars;
stops inside missing intervals are unknown, so this is a data limitation.
Fixed-window final exits use the harness's last actual close, with costs.

## Benchmarks and reporting

For each admitted universe/window/cost case, buy and hold an inception-aware
basket: reserve equal shares of initial cash for every eligible symbol, buy each
once at its first eligible actual open after warmup, keep unlisted sleeves in
cash, liquidate at the last actual window close. Same data and both-side costs.
This fully funded, unmanaged reference is not subject to strategy stop/cap/DD
controls; label it explicitly. Also scale its initial allocation down, holding
the remainder as zero-return cash, by fixed 50-step bisection to match the
strategy's average calendar close gross/equity exposure. This uses realized
exposure and is an ex-post comparison, not a tradable forecast or profit search.

Report coverage, candidate/accepted/skipped counts and reasons, net return,
ending equity, costs by component, maximum observed drawdown, mean/maximum close
exposure, turnover, halt date, cap-at-admission maxima and passive drift. Compare
parent/variant schedules and account results explicitly. Preserve negative
results. Save local machine-readable curves/trades/audits as ignored evidence,
with their hash in the committed report.

For descriptive uncertainty only: 500 paired circular block resamples of daily
strategy-minus-exposure-matched benchmark returns, 20-calendar-day blocks, fixed
seed 20261108, 90% percentile interval for annualized mean excess return (365 days).
Do not use these seen-history intervals as promotion gates, independent test
evidence or assurances of future profitability. Surviving-universe selection,
unmeasured liquidity and daily-bar execution remain limitations.

Meaningful tests must cover SQL/source/sealed boundaries, schema unknowns,
warmup/inception/gaps, parent parity, next-open ordering, stop/gap fill parity,
both-side cost arithmetic using Decimal reference fixtures (never Qwen), cash,
allocation/theme/gross/trade/open-risk limits, DD entry halt and leakage guards.
Run focused tests and lint before the one fixed study. Main owns merge,
deployment and CI integration. Only the four assigned new files are owned here.

## Gatekeeper provenance repair — no economic parameter changes

Original registration remains commit `bb8c27e`, before the first evaluation.
This amendment changes publication/source checks only; strategy, windows, SQL
bounds, costs, sizing and all risk limits remain the original fixed experiment.

Require the entire Git checkout to be committed and clean (staged, unstaged and
untracked changes refuse admission; ignored research outputs are allowed).
Ignored untracked Python sources under `src`/`scripts` also refuse admission.
Hash every tracked file and bind HEAD before importing project decision code.
Before reading data, recheck that pin and hash every loaded module source/cache
file, compiled module and Python executable. Project imports must resolve to
this checkout's tracked source. Verify both pins after evaluation and again
after report rendering, before any evidence/report write. Changed source, HEAD,
loaded runtime files or newly loaded file modules refuse publication.
Record full file-hash manifests, their SHA256 digests, the original registration,
current protocol revision and execution commit in the evidence. A coherent
read-only database transaction and bounded-row hashes remain separately required.
Report outcome counts, benchmark comparisons and parent-account equivalence from
the supplied results; never hardcode successful conclusions. Regression tests
must include contrary outcomes and an imported helper modified during evaluation.
