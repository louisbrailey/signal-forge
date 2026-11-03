# Action-aware funded replay and independent forward validation

This extension is offline, long-only research. It changes neither operating paper
books nor the frozen Kronos configuration, data, collector, or interim results.
It does not approve strategies or permit live execution.

## Data and accounting contract

- Fetch `adjusted=false` daily bars into a separate raw cache. Never infer actual
  share lots by treating today's split-adjusted prices as historical raw ticks.
- Retrieve complete per-symbol `/stocks/v1/splits` and `/stocks/v1/dividends`
  responses. Use `cash_amount`, not `split_adjusted_cash_amount`. Raw responses,
  request windows, retrieval timestamps, source, EOD labels and content hashes are
  retained. Missing pages are a hard failure. Empty successful action lists are
  explicit evidence; absent files are not evidence of no actions.
- Apply effective splits before the session opens: shares multiply, cost basis
  remains unchanged, and per-share entry/stop/target prices divide by the ratio.
  Pending orders are rescaled too. Execution uses actual raw prices, quantities,
  commissions, spread and slippage. Fractional reverse-split entitlements require
  cash-in-lieu evidence; the engine blocks rather than inventing a settlement.
- For features, adjust only earlier bars for splits already effective at the
  decision date. Future splits never enter past feature inputs. Adjust volume
  inversely to price to preserve dollar volume.
- Dividend entitlement belongs to the holder entering the ex-date, before any
  opening sale. It becomes an asset then, but cannot fund purchases until paid.
  Sales after ex-date retain the receivable. Payment is credited on the first
  observed session on/after pay date. Unpaid terminal receivables are reported
  separately from cash. Unknown pay dates, non-USD amounts and conflicting
  same-date dividends block rather than silently becoming zero.
- Verified 1:1 ticker lineage selects exactly one dated leg per session; a seam
  with missing sessions blocks. No mergers, spin-offs, or cash acquisitions are
  inferred. A later listing has no fabricated pre-listing prices. Delisting or
  missing final sessions remain blocked until actual settlement evidence exists.

Provider references:
[raw aggregates](https://massive.com/knowledge-base/article/is-massives-stock-data-adjusted-for-splits-or-dividends),
[splits](https://massive.com/docs/rest/stocks/corporate-actions/splits),
[dividends](https://massive.com/docs/rest/stocks/corporate-actions/dividends).

## Eligibility and risk

The research path reproduces the daily scanner's 220-bar minimum, price and
20-session average dollar-volume floors, and horizon-specific earnings window.
An earnings coverage interval must have been available at the decision date;
unknown coverage blocks stock entries. ETFs do not have corporate earnings.
A modeled spread is disclosed and checked against the configured spread cap.
Current sector metadata and survivor selection remain limitations, not historical
point-in-time facts. Production promotion is never applied retroactively: these
are research-admission books, not replicas of historical approved live trading.

Each strategy/cost book starts with the same $10,000. All instruments within a
book share cash and concurrent risk. Book profits must never be summed as though
all books share the same original $10,000. Existing 0.5% per-trade/1.5% open-risk
limits, 5% initial position/20% sector/60% portfolio notional caps, and 1% previous
session volume participation apply. The independent new default is a **10%**
opening/closing liquidation-value drawdown entry halt. It latches for that run;
existing stops/exits remain active. It is not a guaranteed maximum loss.

Base costs: 3bps slippage and 5bps full spread, zero commission. Stress: 10bps
slippage, 10bps full spread, $0.005/share with $1 minimum each side. These fixed
assumptions are sensitivity checks, not observed NBBO or a profitability target.
All five unchanged daily baselines are compared; intraday ORB is excluded.

## Commands

```sh
uv sync --frozen --extra llm
PYTHONPATH=src uv run python scripts/accounting_snapshot.py /absolute/isolated/raw \
  --env-file /absolute/path/.env --symbols SPY QQQ AAPL FB META \
  --since 2016-10-17 --until 2026-11-02
PYTHONPATH=src uv run python scripts/action_replay_report.py /absolute/isolated/raw \
  --database /absolute/path/signalforge.sqlite > action-report.json
```

The raw fetch caps 30 named symbols/12 years and paces requests at least 12.1
seconds apart using existing retry/backoff and kill-switch checks. Rerun the same
command after interruption: completed endpoint files are checked and reused.
Database metadata reads are read-only; comparison databases are rejected. To use
a verified old/new mapping, include both ticker legs in the snapshot.

## Forward validation is separate and takes time

```sh
PYTHONPATH=src uv run python scripts/funded_forward.py freeze /absolute/new-study \
  --database /absolute/path/signalforge.sqlite \
  --symbols SPY QQQ AAPL FB META --since 2016-10-17
PYTHONPATH=src uv run python scripts/funded_forward.py collect /absolute/new-study \
  --env-file /absolute/path/.env
```

Freeze pins code hashes, strategy specifications, universe, metadata, two cost
scenarios and cash/risk policy. First observation is the next market session;
first fills are allowed no sooner than the following session, after a recorded
forward decision. The collector preserves open positions at each observation
boundary, retains dividend receivables, and never liquidates merely to generate
an interim report. Prior fills/marks/decisions must match on the next collection.
Revised historical inputs, changed code, missing sessions or attempts to rewrite
records block the study. Failed collection does not authorize retrospective
backfill labelled as forward evidence.

At least 126 sessions, 30 closed trades per book and two trend regimes are required
before an evidence review; maximum collection is 252 sessions. These are review
floors, not automatic pass criteria. Confidence intervals, stress performance,
benchmark comparisons and economic limitations still require review. The collector
never changes a strategy or promotes a book. Historical results do not establish
prospective improvements; no prospective result is available on setup day.

A separately installed local LaunchAgent can call `collect` every 30 minutes. It
fetches only when a new completed session is due; repeats are idempotent. Its cache
has a 2 GiB cap. macOS must be awake with the paths available. Check the isolated
`status.json`, plan, collection records and dedicated log; this job is not part
of the existing worker or Kronos study. A code change intentionally stops it;
start a separately versioned study rather than editing the original plan.

Research signal only — no order was placed.

## Verified reference metadata

The operating instrument table may contain legacy defaults (`instrument_type=stock`
for ETF symbols). Do not infer earnings applicability from that default. Pass a
verified Massive reference-evidence JSON with `--listing-evidence` to both
`action_replay_report.py` and the forward `freeze` command. Each entry is keyed
by symbol and records source, endpoint, response hash, list date and provider type.
`type=ETF` changes only the isolated research metadata; operating tables are not
rewritten. A staggered series requires listing evidence. Listing sessions lacking
bars are listed explicitly and never filled with invented prices; the symbol
cannot qualify until 220 real observations exist.

On November 3 the Benzinga earnings endpoint returned HTTP 403. News entitlement
is not evidence of earnings entitlement. Historical event coverage remains
unavailable and stock entries are blocked in this run. Supplying a current earnings
calendar later would not retroactively prove what was known historically.

The launchd template is `deploy/launchd/com.signalforge.funded-validation.plist`.
Replace `__CHECKOUT__`, `__STUDY_ROOT__`, and `__ENV_FILE__` with absolute paths;
keep credentials inside the referenced environment file. Install the rendered
plist under `~/Library/LaunchAgents`, then use
`launchctl bootstrap gui/$(id -u) /absolute/path/to/rendered.plist`. It has a
separate label and does not replace existing Signal Forge/Kronos services.
`funded_forward.py status /absolute/new-study` reports observation/trade/regime
readiness without declaring a strategy profitable. Stop this collector alone with
`launchctl bootout gui/$(id -u)/com.signalforge.funded-validation`; keep its plan,
cache and collection files for audit. It resumes at login after reboot; a Mac
without an active logged-in user or while asleep cannot collect.
