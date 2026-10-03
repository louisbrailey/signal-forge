# Paper-operation verification — October 2, 2026

## Verdict

Operational for **guarded paper research**, not validated as profitable. The local
API and worker were reloaded; database readiness passed at migration head. No
brokerage was contacted or armed. Existing strategy approvals, parameters and
configuration hashes were preserved; acceptance was narrowed by additional risk
checks. These checks do not constitute new strategy validation.

## End-to-end evidence

- Existing scheduled Massive update #34 finished partially: RCL network failure.
  A bounded, one-symbol retry #35 succeeded with one new bar. The original failed
  evidence remains. All 151 configured/approved-scope symbols were covered by the
  original run plus retry. Inputs remain END-OF-DAY, not real-time prices.
- Approved-scope job completed at 23:28:38 UTC: two scope groups, four qualified
  candidates, no blocked universes. Automatic local ledger acceptance created:

| Paper trade | Symbol | Shares | Hypothetical fill | Planned stop risk |
|---|---|---:|---:|---:|
| 18 | TSLA | 4 | $370.79 | $70.36 |
| 19 | ACN | 7 | $199.01 | $108.29 |

Both were bounded by the 5% symbol allocation ceiling. Two other candidates were
recorded as WATCH because the existing two-acceptance UTC-day cap was reached.
There were then six accepted decisions total, four open positions, eight rejected
decisions and seven watches. This is observed operation, not an investment result.
No test alert was sent and no notification settings were changed.

The existing account started at $30,000; it was not reset. Current new-entry
ceilings: 0.5% planned trade risk, 1.5% aggregate open stop risk, 5% per symbol,
20% per known sector, with stricter configured limits taking precedence. The
configured 60% gross exposure limit still applies. Cash and existing exposure are
re-read under the transaction lock. Stops cannot prevent gap losses.

## Kronos evidence

The optional cached local Kronos-small runtime consumes persisted real Massive
daily history only. No API keys are inherited, network use is blocked, inference
is bounded, and trading/risk/alert code cannot import its output. The dashboard
records experiments and exports full input/provenance/result JSON.

| AAPL replay | Context dates | Held-out dates | Kronos price MAE | Unchanged-price MAE |
|---|---|---|---:|---:|
| 5 sessions | 2026-03-24–2026-09-24 | 2026-09-25–2026-10-01 | $4.4806 | $4.5300 |
| 20 sessions | 2026-03-03–2026-09-02 | 2026-09-03–2026-10-01 | $16.5985 | $8.9960 |

Three seeded paths per run. Five-session error was slightly lower; twenty-session
error was substantially worse. These are two historical demonstrations, not
proof of prediction skill or profitability. Model pretraining overlap is unknown,
prices may incorporate later vendor revisions, and MAE excludes trading costs.
The 20-session experiment is persisted as audit record 203 for dashboard review.

## Changes and operating instructions

- Added `/paper-console`: persisted decisions, account estimates, scans, liveness,
  legacy-history warnings; refreshes every 30 seconds.
- Added `/kronos`: authenticated replay, baseline chart, accessible numeric table,
  provenance, saved experiments and JSON export. CSRF and emergency-stop guarded.
- Startup heartbeat continues during slow provider catch-up; exchange holidays
  no longer create phantom expected sessions. Liveness remains distinct from data
  readiness. On restart, the prior heartbeat can conservatively delay startup for
  up to two minutes.
- Scans check actual symbol and benchmark market dates. Paper acceptance rechecks
  freshness, clean adjusted source-qualified bars and current account risk.
- Corrected double-counted simulated costs, sizing rounding, entry-day lookahead,
  exit chronology, missed-session exit handling and custom-slippage risk budgeting.
  Exit processing also rejects flagged, unadjusted, simulated-as-real, nonfinite
  or inconsistent OHLCV rather than inventing an exit from suspect history.
- Added operating guide and corrected ADR links. See
  [PAPER_OPERATIONS](../docs/PAPER_OPERATIONS.md) for exact startup commands.

Open http://127.0.0.1:8787/paper-console and sign in with the existing local account.
LaunchAgents `com.signalforge.api` and `com.signalforge.worker` are already installed;
do not start duplicate workers. The browser reached the expected login protection.
Authenticated page rendering and mutations were tested with isolated test users;
no production password was requested or bypassed.

## Verification

Local checks covered all **2,069 collected tests** in partitions. The paper/app
partition passed 296 tests. The remaining partition passed 1,764 and reported two
failures: an old test used an expired fixed arming date; another inspected source
while the ledger was being edited and read stale line offsets. The first test now
freezes its intended clock; the second required no production change. A fresh run
of both complete affected files passed all 22 tests, resolving both failures.
The full run was not rerun after those targeted resolutions. Final review then
added seven bad-exit-bar regressions; the complete paper partition was rerun
after updating synthetic fixture adjustment flags. No real data was relabeled.

| Check | Result | Local evidence |
|---|---|---|
| Non-paper/app suite | 1,764 passed; two resolved as above | `.toolkit-runs/20261002T231943.485041Z.log` |
| Final paper suite, including seven exit-quality regressions | 234 passed | `.toolkit-runs/20261002T233724.249474Z.log` |
| Paper and app suite | 296 passed | `.toolkit-runs/20261002T232432.572314Z.log` |
| Affected execution files, fresh process | 22 passed | `.toolkit-runs/20261002T232758.038524Z.log` |
| Kronos, dashboard, worker focused checks | 42 passed | `.toolkit-runs/20261002T231944.827521Z.log` |
| Final Kronos latency-label route check | 6 passed | `.toolkit-runs/20261002T233252.194891Z.log` |
| Safety-marker tests | 113 passed | `.toolkit-runs/20261002T232926.757499Z.log` |
| mypy | 233 source files passed | `.toolkit-runs/20261002T232536.820855Z.log` |
| Import boundaries | 16 kept, zero broken | `.toolkit-runs/20261002T232434.196123Z.log` |
| Ruff / Black / diff whitespace | Passed | Local command results; 413 formatted files |
| Tracked-file secret check | Passed | `make secrets` after staging |

Commands: `devkit run --timeout 1800 -- .venv/bin/pytest -o addopts='' -q
--ignore=tests/paper --ignore=tests/app`; corresponding `tests/paper tests/app`
partition; focused files above; `pytest -m safety`; `ruff check src tests`;
`black --check src tests`; `mypy`; `lint-imports`; `make secrets`;
`git diff --check`. The first broad attempt hit the toolkit's default 600-second
timeout and was superseded by the completed longer run. A dependency deprecation
warning about AnyIO/Starlette remains. Local testing disabled coverage collection;
GitHub CI runs the configured coverage-enabled suite separately.

## Remaining limitations

Two legacy positions have impossible pre-entry exit timestamps; old cost accounting
was also defective. Original records remain untouched and the UI warns that legacy
P&L is not validated forward performance. Corrective research/accounting work must
be append-only. Existing larger positions are not silently sold or resized.

The paper fill model uses signal-zone reference prices with spread/slippage, not
observed executable NBBO. Daily OHLC cannot resolve entry-day event order. Real
forward performance must be measured after these repairs. Missing data, provider
failures, risk limits and evidence gates can legitimately produce no trades.

Kronos is optional and requires the existing separately installed cached runtime;
it is not bundled into a new machine's `uv sync`. This release does not certify
Windows operation, mobile layout, Docker deployment, or profitability. Current
provider calls and model runs were local operational checks, not CI tests.

Research signal only — no order was placed.
