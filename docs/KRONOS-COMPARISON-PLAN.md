# Kronos prospective comparison — frozen protocol v1

Status: **pre-registered experimental protocol**, not operating approval. No
comparison outcomes were consulted to choose these rules. ADR 0004 and the
previous null/negative Kronos study remain unchanged. This study cannot promote
a strategy or connect Kronos to the operating decision path.

## Question and books

Does one fixed Kronos filter improve net hypothetical portfolio performance
compared with accepting the same otherwise-qualified daily strategy candidates?

Freeze separately for SHORT_SWING (5-session forecast) and MEDIUM_SWING
(20-session forecast). Each currently PAPER_APPROVED strategy version receives
three independent $10,000 accounts in a **new, private SQLite database**:

1. Baseline accepts all eligible candidates, subject to existing ledger risk checks.
2. Filtered accepts candidates only when the mean terminal close of the three
   pinned Kronos paths exceeds the latest observed close by **11 basis points**.
   This is a fixed gross-return cost hurdle (3bps slippage + half of a 5bps spread
   per side); it is neither an estimated edge nor a calibrated probability.
3. Matched selection chooses exactly as many pre-risk candidates as filtered,
   using SHA256(seed 42817, manifest hash, day, strategy version, candidate id).
   Selection is independent of outcomes. Realized counts/exposure may diverge
   because subsequent portfolio risk checks and holding times differ.

No pooling across strategies or horizons; no best-arm/model search. No options,
forex, crypto, bonds, or intraday recommendations. Approved stocks/ETFs only.
Source candidate PASSED, long, exact passing approval scope, current version and frozen approval scope,
current completed Massive scan, and clean current daily bars are required.
Missing predictions remain **missing**, not bearish. Baseline still participates;
filtered and matched take zero candidates when all predictions are missing.
Report missingness and operational failures alongside performance.

## Frozen inputs and inference

The manifest pins strategy specs, full effective research configuration, source
path, source-code/lockfile/plan hashes, model/tokenizer/implementation file hashes,
and model-environment metadata. The runtime uses the existing offline worker:
Kronos-small, base tokenizer, eval mode, three seeded paths (42, 43, 44), T=1,
top-p=0.9, 128 completed continuous daily OHLCV observations, horizons 5 or 20.
Local cached weights are pinned, **not independently certified training data**.
Historical model-training overlap remains unknown; this is a prospective study.

The first study session closes after manifest creation. Enrollment ends after
252 XNYS sessions on dates frozen in the manifest. Never extend the period after
seeing results. Missed collection days are not retrospectively reconstructed.
Each session admits at most 250 candidates and 25 unique symbol forecasts. Each
inference attempt is reserved durably before launch. Crashes produce unavailable
predictions on resume, not repeated draws. Inference must finish on the origin's
UTC date; late batches produce no entries in any arm. Run post-close, before UTC
midnight. On early-close days use the exchange calendar, not a fixed wall clock.

Only explicit CLI invocation writes experiment state. No scheduler or service
is added. Run once after the operating daily ingest and scan finish. Repeating a
completed session is a no-op. Both the process emergency stop and the pinned source-directory
`kill_switch.json` apply, including cancellation during inference. Source DB is
opened SQLite read-only; operating accounts, alerts, auto-simulation, model
watcher, and existing shadow-outcomes-v1 stay unchanged.

## Portfolio simulation and validity limits

All arms call the **existing paper ledger**, with the same frozen research risk
limits and its hard risk caps. Preserve the frozen operating per-book daily
acceptance cap, one open position per instrument per book, and rank/id ordering. Entries use candidate-zone midpoint plus modeled
spread/slippage and cents rounding; this is NOT next-open or observed NBBO
execution. Entry-day exits are not simulated. Exit processing starts with the
next daily bar and retains existing stop/target/time-stop priority and costs.
The private order/fill/position record carries actual decision time; the ledger's
plan labels its date-based valuation as historical replay. Immutable comparison
records supply the prospective capture time and source approval evidence.

Baseline is a NEW counterfactual book, not a copy of the operating portfolio.
Historical decisions/trades, operating cash, and existing positions are not
imported. Existing candidates' risk budgets remain frozen, then are capped by
each private account's actual cash/exposure limits. Cash earns zero. No leverage.
No signal, risk, stop, target, model parameter, or production setting is changed.

Copy observations separately from the source. Preserve source, latency category,
quality flags, session date and ingestion time. Reject simulated, future,
unadjusted, malformed, missing-session, or revised captured observations. Do
not silently skip a missing earlier stop opportunity. Source adjustments,
corporate actions, delistings and metadata revisions can halt progression; these
need independent investigation, not favorable data substitution. Fixed surviving
universe, missing dividends and daily-fill realism remain limitations.

## Sealed analysis

`status` exposes operational counts only. No interim P&L report or win-rate
leaderboard. Performance stays logically sealed until the 252-session enrollment
period ends **and all open positions settle** under their original exits. Continue
marks-only after enrollment. The owner can inspect SQLite directly; this is an
audit protocol, not cryptographic prevention of manual peeking.

`finalize` records exactly one immutable report; later calls return that report.
Each strategy reports net return, drawdown, volatility, zero-cash-rate Sharpe,
closed count, hit rate, profit factor, average exposure and entry-cost attribution.
Net equity includes exit costs; entry attribution must not be called total costs.
Paired DAILY return differences compare filtered vs baseline and filtered vs
matched, with 5,000 circular calendar-block bootstrap samples, 21-session blocks,
seed 42817 and 97.5% intervals (two within-family comparisons). This preserves
contemporaneous portfolio dependence; it is not a profit probability.

Fewer than 100 closed baseline trades => insufficient evidence. Otherwise both
lower interval bounds must exceed zero to warrant **independent review**, never
automatic promotion. All strategy families are reported, without selecting a
winner; any cross-family claim requires multiplicity review. Review regime
coverage, drawdown, exposure differences, missing forecasts, outage days and
symbol concentration before considering a NEW preregistered study. Regime
coverage cannot be guaranteed by waiting one year. A failure/null stands; do not
tune against these outcomes or reopen historical sealed looks.

## Storage and operations

A new directory is required; manifest/forecast/attempt/choice/daily/final records
and paper trades have UPDATE/DELETE rejection triggers. One advisory writer lock
per private database, bounded inputs, and a 65,536-page SQLite cap (normally
256MiB plus rollback journal) prevent unbounded concurrent accumulation. The
manifest and DB are mode 0600 inside a 0700 directory. Private state is ignored
by Git. Model caches and operating DB are never copied into the repository.

From the frozen checkout, with the project environment installed (add
`--env-file /absolute/path/to/operating/.env` to each command when the operating
configuration uses that file; it is read locally and never copied or printed):

```sh
uv sync --frozen --extra llm
PYTHONPATH=src uv run python scripts/kronos_comparison.py freeze data/comparison-short \
  --source /absolute/path/to/operating/signalforge.sqlite --horizon short_swing
PYTHONPATH=src uv run python scripts/kronos_comparison.py status data/comparison-short
# After each completed daily ingest + scan, before UTC midnight:
PYTHONPATH=src uv run python scripts/kronos_comparison.py advance data/comparison-short
# After enrollment ends (or explicitly skip new entries):
PYTHONPATH=src uv run python scripts/kronos_comparison.py advance data/comparison-short --marks-only
# Once the full calendar has passed and all positions have settled:
PYTHONPATH=src uv run python scripts/kronos_comparison.py finalize data/comparison-short
```

Use a different new directory and `--horizon medium_swing` for the second horizon.
No inference runs during freeze. Missing approved versions/artifacts stop freeze.
Keep the frozen checkout: changed code/config/model hashes refuse admission;
never edit an existing manifest to bypass this guard. No credentials needed
beyond already-ingested local data. No provider calls, notifications or live
orders are made by the experiment.

**Research signal only — no order was placed.**
