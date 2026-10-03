# Operating Signal Forge's paper research system

Signal Forge runs deterministic equity scans and accepts only qualified, approved,
in-scope candidates into a **local simulated ledger**. It is not an autonomous
profit guarantee. No brokerage credentials or connection are needed. Kronos has
no authority over entries, exits, ranking, position sizing, approval, or alerts.

## Start and verify

```bash
cd ~/signal-forge
uv sync --frozen --extra llm
uv run alembic upgrade head
uv run uvicorn signalforge.app.main:app --host 127.0.0.1 --port 8787
```

Run the worker in a separate terminal only if the installed launchd worker is
not already running:

```bash
uv run signalforge run-scheduler
```

This Mac already uses `com.signalforge.api` and `com.signalforge.worker`
LaunchAgents. Check `launchctl list` before starting another instance. Do not run
`seed` against an existing real-data account. Local scheduling requires the Mac
to remain awake and logged in; catch-up runs after missed sessions. Safe provider
pacing means a 151-symbol update can take about half an hour.

Open http://127.0.0.1:8787/paper-console and sign in with the existing local
account. The page refreshes every 30 seconds and shows persisted scans, decisions,
account estimates and worker liveness. `/ops` supplies feed and job detail;
`/scanner` and `/candidates/{id}` show evidence; `/journal` shows decisions.
A fresh heartbeat only proves the process is responding, not that data is fresh.
The startup heartbeat now explicitly says catch-up is running during ingestion.

The active accounts and switches are read from the database. This release does
not reset cash or enable an execution adapter. The October 2 audit found a
$30,000 equity paper account, automatic acceptance enabled, and a two-acceptance
UTC-day cap (now applied per book, see below). A cap, open position, stale data,
missing scope, or failed evidence gate can correctly prevent trading. Rejected and watched decisions are retained;
new sessions produce new candidates rather than rewriting old decisions.

## Separate books per approved strategy version (2026-10-03)

Each `PAPER_APPROVED` strategy version trades its **own equity paper book**: a
`paper_account` row whose `strategy_version_id` is that version (unique).

- **Why.** With one shared book, the medium-swing version took a symbol and the
  short-swing version was refused with "an open paper position already exists";
  auto-simulation also ordered candidates by the horizon *string*, so
  `MEDIUM_SWING` always decided before `SHORT_SWING`. The short-swing version
  accumulated no forward evidence at all.
- **How books are keyed.** `paper_account.strategy_version_id`. A book is created
  lazily and idempotently the first time an approved version needs it, named
  `book-sv<id>`, starting from the same reference equity as the legacy `default`
  account's `initial_cash`. Creation is recorded in `audit_log`
  (`paper.book_created`).
- **How existing rows are attributed.** Nothing is moved. The migration keys the
  legacy `default` account to the one strategy version all of its positions
  belong to — on the live database the medium-swing version, which owns all six
  accepted trades — so `default` **is** that version's book. If an account's
  positions belong to more than one version (or none), it stays unkeyed.
  Historical REJECTED/WATCH decisions of other versions remain recorded where
  they were written (`paper_trade` is immutable); they carry no position or cash.
- **Unattributed decisions.** A candidate whose version is not `PAPER_APPROVED`
  (a manual acceptance of an experimental signal) never lands in an approved
  version's book: it goes to the unkeyed `default` account or, once `default` is
  a version's book, to the unkeyed `manual` account (created the same lazy way).
- **Per book:** the open-position rule (the same symbol may be held by two
  versions at once), every risk cap below, and the auto-simulation daily cap
  (`auto_simulate_max_per_day`, default 2 **per book**).
- **Order.** Books are decided in strategy-version-id order; inside a book,
  candidates by rank then id. Deterministic and repeatable.
- **Views.** `/portfolio`, `/paper-console` and the overview show one row per
  book. Because a book's caps cannot see another book's position, those pages
  also show the **combined exposure per symbol across all books**; treat that
  table as the account-level concentration figure. `signalforge paper snapshot`
  prints the same `books` and `symbol_exposure` data.
- **Not changed.** Scan-time candidate sizing still reads the `default`
  account's cash; the ledger re-sizes against the candidate's own book at
  acceptance and takes the smaller size.

## Acceptance safeguards

New equity paper fills are long-only and cash-funded. At acceptance, the ledger
rechecks the candidate's **book** under a write lock and uses the stricter of the
configured limit and these ceilings (constants in `paper/ledger.py`):

| Limit | Ceiling | Note |
|---|---|---|
| Planned risk per trade | 0.5% of book equity | unchanged |
| Aggregate open stop risk | **3.0%** | raised from 1.5% — operator decision 2026-10-03, paper only |
| Allocation per symbol | **10%** | raised from 5% — operator decision 2026-10-03, paper only |
| Allocation per sector | 20% | unchanged; now applies to every instrument |
| Gross exposure | 100% (no leverage) | unchanged |

The ceilings only bound the configured values. The shipped configuration is
`max_position_concentration_pct = 10`, so the 10% symbol ceiling is in effect.
`max_daily_portfolio_risk_pct` ships as **1.5**, so aggregate open risk is still
limited to 1.5% until that setting is raised — and `risk` is part of the
approved-scope `config_hash`, so raising it puts every existing approval out of
scope until the strategies are re-evaluated. That is a separate operator
decision; this release does not change the configured value.

Stops and ATR-based candidate sizing remain deterministic. Stops cannot guarantee
maximum loss through a gap. Existing larger positions are not resized or
liquidated, but they count in full toward every cap for new entries.
The immutable decision record stores the book, the binding limits and size reductions.

### Sectors

`instrument.sector` was blank on every row, so the sector cap never operated.

- **Unknown is one capped bucket.** An instrument with a blank or "unknown"
  sector belongs to the single bucket `UNKNOWN`, capped at 20% like any sector.
  Unknown never means unlimited.
- **Populating sectors.** `uv run signalforge universe sectors --refresh` derives
  a stable label per instrument: stocks from the provider SIC code (the same
  2-digit SIC grouping the universe screen uses, named in
  `universe/sectors.py`, with a few 3–4 digit refinements such as 737 software →
  Technology); a sector SPDR maps to its sector (`XLK` → Technology); every other
  ETF is its own bucket `ETF:<symbol>`. Stored SIC codes are used first; a stock
  without one costs one reference request (`--max-requests`, resumable). Without
  `--refresh` the command is a read-only count per sector.
- SIC-derived labels are approximate (not GICS) and exist only to bound
  correlated paper exposure. No signal reads them.

### Time stop

`time_stop_days = N` is the **N-th XNYS session after the entry date** — the
backtested N-bar rule — not entry + N calendar days. Weekends and exchange
holidays do not count. Positions opened under the old calendar rule are moved to
the session rule by an explicit migration that runs on the next mark: each change
is written to `audit_log` as `paper.time_stop_recomputed` with the old and new
date, and it is idempotent.

Fresh scan timestamps and a current, source-qualified completed market bar are
required for normal acceptance. Automatic acceptance additionally requires the
existing approval, scope, quality and daily-cap checks. Historical replay cannot
masquerade as automatic current acceptance. Scans also reject symbols whose actual
bar date is stale even when the provider's last HTTP request succeeded.

Spread and slippage are included once in the simulated fill price. Daily-bar exits
start on the session after entry and inspect missed sessions chronologically;
entry-day OHLC cannot reveal event order. Suspect exit bars block valuation or
closing with an explicit error; they are never silently skipped. Stop gaps receive adverse open-price
handling. All fills are hypothetical; daily price zones are not executable quotes.

## Research model

Open `/kronos`. The app reuses the installed local runtime at
`~/my-stack/Kronos/.venv/bin/python` and cached `NeoQuasar/Kronos-small` weights.
No model download, paid inference, or provider call occurs. This Python/model
installation is optional and separate from `uv sync`: a new machine must supply
it before inference is available. Missing runtime/weights/data is shown as an
error, never replaced with invented predictions.

Choose a configured watchlist symbol and 5 or 20 held-out sessions. Input is
128 preceding real Massive daily bars. Actual future prices are not sent to the
model. Three seeded paths are compared with the unchanged-price baseline. The
mean absolute price error is **not** investment return, and model pretraining
overlap is unknown. Published adjusted history can contain later vendor revisions.
The sample min/max is not a calibrated confidence interval.

The page charts actual, predicted and baseline prices, tabulates exact values,
records each successful experiment, and exports the input/provenance/result JSON.
Inference is bounded and runs outside the web event loop, without inherited API
keys. The POST releases its SQLite write transaction before model work so it does
not block ingestion for the duration of inference. Import contracts prevent
Kronos from reaching trading and prevent trading from consuming Kronos.

## Known historical defects and their correction

The read-only audit in `PAPER_OPERATION_AUDIT.md` found two legacy positions with
exit timestamps before entry and a cost-accounting defect. Original audit rows
are preserved. The paper console flags impossible chronology; accumulated legacy
P&L must not be presented as validated forward performance.

`signalforge paper correct-legacy --dry-run | --confirm` repairs both with
append-only `trade_correction` rows; `paper_trade` rows are never modified.

- **Invalid exits.** A closed position whose exit date is not after its entry
  date is reversed (exit proceeds taken back out of the book's cash, realised P&L
  zeroed, position re-opened) and then re-resolved with the current rules: only
  bars strictly after the entry date, in order, with the session time stop. It
  either stays open or closes on a later, valid bar.
- **Double-counted entry costs.** The old ledger embedded spread and slippage in
  the fill price and also debited them from cash. For every accepted long trade
  it wrote (those whose plan has no `risk_decision`), the second debit is
  credited back to the book.
- `--dry-run` runs the identical code inside a savepoint that is rolled back and
  prints every change, the per-book cash before and after, and any duplicate
  open positions the corrections leave behind. `--confirm` writes. Re-running
  finds nothing more to do.
- **Duplicates are reported, not voided.** If a second position was opened in a
  symbol only because the first had been wrongly closed, both are re-opened and
  the command prints a WARNING. They count toward that book's caps. Voiding an
  accepted decision is an operator judgement and is not automated.

## Deploying the 2026-10-03 release

Run in this order. Take a file-level backup of `data/signalforge.sqlite` first.

1. **Stop the worker** (and the API if it is serving writes):
   `launchctl bootout gui/$(id -u)/com.signalforge.worker`
2. `uv sync --frozen --extra llm`
3. `uv run alembic upgrade head` — adds `paper_account.strategy_version_id` and
   keys `default` to the version that owns all its positions. Verify with
   `uv run signalforge paper snapshot` (the `books` list).
4. `uv run signalforge universe sectors --refresh` — re-run until it reports no
   instruments awaiting a reference request. Unknown sectors stay capped.
5. `uv run signalforge paper correct-legacy --dry-run` — read every line.
6. Review: the reversed exits, the cost credits, each book's cash delta, and any
   duplicate-position WARNING (expected on the live MSFT rows).
7. `uv run signalforge paper correct-legacy --confirm`
8. **Start the worker**
   (`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.signalforge.worker.plist`).
   The first mark logs `paper.time_stop_recomputed` for
   each open position that moves to the session time stop; the first
   approved-scope scan creates the short-swing version's book.

The alembic revision follows `c1e5a9f37b24`. If another revision that also
follows it has been merged first, re-point one `down_revision` before upgrading
so the chain keeps a single head (`uv run alembic heads` must print one line).

## Known gap: missed sessions

No approved-scope scan ran for the 2026-09-28, 09-29 and 09-30 sessions. The
cause was operational, not a gate: the worker was not executing jobs (the Mac
slept through the 21:30 UTC scan on 09-28, a catch-up ingest then stalled on
repeated provider network failures while holding the end-of-day lock, and no job
ran again until the restart on 10-01 19:28 UTC). Start-up catch-up ingests the
missed bars but scans only the latest session, so signals on the missed sessions
are never evaluated. Keep the Mac awake and online across the close; launchd
`KeepAlive` restarts a crashed process, not a sleeping or stalled one.

A good replay is not a reason to promote a strategy. Evaluate model usefulness
on preregistered unseen windows before considering any separately specified
research component; never repeatedly tune against the same held-out period.

Research signal only — no order was placed.
