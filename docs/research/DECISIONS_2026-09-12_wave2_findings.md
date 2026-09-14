# Wave-2 integration findings (2026-09-12) — open items before any options evaluation

All five wave-2 tracks are merged on `main` (I-E3 paper_reference adapter, I-E4 arming /
dead man / reconciliation / calendar / guarded cycle, I-O2 short-commit backfill loop,
I-O4+I-O5 options gate ladder + O3 short vertical v0.1.0, I-O6 options paper mechanics).
Migration `b9d41e07c6aa` is applied live. Nothing is scheduled or armed by any of them.
W5b adds migration `c1e8f0a4d7b3` (two columns on `options_mark`); it is **not** applied
live yet and the options paper account holds no structure, so there is nothing to migrate.

## Pre-registration defects found by the implementers (D5 amendments needed, k = 0)

1. **`min_credit_to_width` is unreachable.** On an arbitrage-free chain the credit-to-width
   ratio of a defined-risk short vertical is bounded near the short delta; at 0.20 delta /
   35 DTE the print ratio is 0.18–0.24 and the adverse (spread-charged) ratio 0.12–0.18 for
   IV 15–60 %. D5's floor (0.25) and both grid values (0.25, 0.30) admit **zero entries**.
   Resolution options: lower the floor to a reachable band, raise the delta band, or accept
   that v0.1.0 trades nothing. Asserted in `tests/research/test_options_short_vertical.py`.
2. **Fixed-R rule (D4 §3 d) vs `width_pct` as a fraction of the underlying (D5 §4.1).**
   R scales with price, so a multi-underlying v0.1.0 fails gate 0.5 as pre-registered.
3. **Gate 0.i fails by arithmetic today**: two of the three declared widths breach decision
   4's $250 per-structure cap before any data exists (D4 §2.8a predicted this).
4. **OQ-1** (MEDIUM_SWING vs POSITION horizon) is taken as D5 declares it and is baked into
   the family name, hence into `count_sealed_looks`. Ratify before the first evaluation.

## Implementation gaps that block the first options evaluation

- No caller assembles `OptionsEvidence` from real data (universe loop, coverage-summary
  reader, clustered bootstrap by `(underlying, expiry cycle)`).
- No options sensitivity-grid runner for gate 5 (96 pre-sealed re-runs; `None` fails gate 5).
- D2 §14.3 append-only variant ledger and D5 §5.3 same-session surface are not built.
- ~~I-O6's `auto_simulate_options_scan_runs` has **no scheduler caller** (asserted by test).
  Wiring it needs mark → reconcile → expiry in front of it in the EOD chain, plus the
  health-monitor / probation options branches (D3 §7.3) — both readers are options-blind.~~
  **CLOSED by W3c (branch `options-w3c-eod-chain`, same day.)** `options_paper_eod` runs
  mark → reconcile → expiry → auto-simulate at 18:30 ET, config-gated OFF behind the new
  `research.options.paper_eod_enabled`; off, it returns before it opens a write
  transaction. The auto-simulation step still needs its own `auto_simulate_options_enabled`
  (off, cap 0/day). Both readers gained their explicit D3 §7.3 options branch; the equity
  numbers are unchanged (`tests/research/test_options_health_and_probation.py`). The
  "no scheduled caller" test was replaced, not deleted, by one that pins the ordering and
  the single call site, and the equity single-entry-point test names the second door
  explicitly. **Registration follows D6 §2's rule, not the scheduler's:** the chain body is
  `paper/options_eod.py` and its `JobSpec` is injected from `cli.py`, because
  `signalforge.app` imports `signalforge.scheduler` and S16 reports indirect chains — the
  first cut put the body in `scheduler.py` and broke S16 three ways. Consequence, stated:
  the options chain runs **only in the CLI-launched worker**, never in an API process with
  `APP_RUN_SCHEDULER=true`, and `default_job_specs()` stays byte-identical to main.
  `paper.options_eod` is named in S11/S11b/S13/S14/S15/S16 as the fourth options sibling.
  ~~**Still open:** the chain refuses (`OptionsEodUnpriceable`) a book spanning
  more than one underlying, because `mark_options_to_market` /
  `process_option_expiries` / `auto_simulate_options_scan_runs` each take ONE
  `OptionsPricingContext` per call and one `q` cannot honestly serve two names
  (decision 11). Widening that needs a per-underlying pricing resolver in
  `paper/options_marks.py`, which W3c deliberately did not open.~~
  **CLOSED by W5b (branch `options-w5b-per-underlying-pricing`, same day.)** The
  three jobs now take a `PricingContextResolver` — a callable
  `(underlying, as_of) -> OptionsPricingContext` — instead of one context, so a
  **multi-underlying book is priceable** and each name carries its own `q`.
  `resolve_underlying_pricing()` sources decision 11 **rank 1 only**: that name's
  own trailing-twelve-month declared yield from `dividend_event`, expressed
  against that name's `ohlcv_daily` close for the session; `r` comes from
  `OptionsEvaluationConfig.risk_free_rate`, the same constant the backtest engine
  reads, and the pre-registered cost model is shared because neither is a
  property of an underlying. There is still **no `q = 0.0` fallback and no
  substituted `q`**: a name with no sourceable series or no close raises
  `UnderlyingNotPriceable` (which `OptionsEodUnpriceable` is now an alias of), and
  the refusal **names the underlying**.
  What changed is the blast radius, not the strictness. `_options_eod_pricing`
  resolves every name independently inside the survey reader and returns a
  `ResolvedPricing` pinned to that session (asking it for another session is a
  loud `ValueError` — `q` and its reference close are point-in-time). A refused
  name's structures are **left unmarked and unsettled** and reported by name
  (`OptionsMarkResult.unpriceable_underlyings`, `ExpiryReport.unpriceable_
  underlyings`, and an error log naming each reason); every other structure is
  marked as usual. An unmarked structure is then a **new reconcile check 11**
  (`11_open_structure_marked_this_session`), so the session's
  `OptionsReconcileReport` is **not clean** and the second guard's condition
  **AA** refuses every acceptance on it — the auto-simulation step still runs, so
  the refusal is a recorded decision naming AA rather than an absence. A
  structure opened ON the session is exempt from check 11: condition M already
  required every leg to print on its fill session, so the entry is its valuation.
  A candidate whose own name cannot be priced is **skipped, not rejected** —
  `_already_decided` never re-decides a candidate, and a reference-data gap is
  not a permanent judgement about a candidate.
  Recording (decision 11's second half): migration **`c1e8f0a4d7b3`** adds
  `options_mark.q_source` and `options_mark.dividend_yield` — `op.add_column`, not
  a batch rebuild, because `options_mark` is append-only and a copy-and-swap
  would drop its two S9 immutability triggers. `dividend_yield` is NULL when the
  number is not finite, never 0.0. Closes and expiry settlements carry the same
  pair in the immutable `options_trade` snapshot under `close.pricing` (a JSON
  field that already existed, so no column was added for them), and
  `options_portfolio_snapshot` surfaces both on each structure's `last_mark`.
- The real options backfill (~29,376 requests, ~98.7 h) has not started; runbook
  `docs/research/options_designs/IO2_RUNBOOK.md` (nightly `--max-minutes 590`, never in the
  17:30–19:00 ET window, coverage-summary-only rule).

## 2026-09-14 operations

- **The daily ingest now covers every approved universe, not just the watchlist (W6a).**
  `scheduler.job_ingest` fetched `settings.research.universe` only (~25 symbols), so
  strategy v3 (`trend_continuation.medium_swing`), PAPER_APPROVED on DataSnapshot 11
  (`research_150_massive_10y_presealed_sel`, 150 symbols, source `massive`), had its
  approved-scope scan blocked **every session** —
  `approved_scope_scan.blocked … only 24/150 approved symbols have a bar for 2026-09-14`
  (observed 23:04Z after a manual `run-job daily_eod_update`). Friday 2026-09-11 only
  worked because the 10-year full-history backfill (ingestion run 15) happened to include
  that session. `job_ingest` now fetches the union of the configured universe and every
  PAPER_APPROVED version's approved-scope universe **on the ingest adapter's source**,
  de-duplicated, configured symbols first (they commit first, so a truncated run still
  tops up the watchlist). The extra symbols come from
  `approved_scope_scan.ingest_scope`, which reads `approved_universes()` — the function
  that drives the scan — so ingest and scan cannot drift apart. An approved universe on
  another source is skipped and recorded, never fetched with the wrong adapter: bars are
  tagged with the writer's `provider_name` and the readiness gate counts bars
  `WHERE source = the approved source`.
- **`IngestionRun.status` semantics are unchanged; who a non-ok run blocks is not.**
  `ok` still means every requested symbol succeeded. But a single global "last ingestion
  must be `ok`" gate is too coarse once one run covers config + 150 approved symbols, so
  `data_readiness` now decides per universe: `partial` blocks **only** the universes
  containing a named failed symbol (naming them); `partial` with an empty
  `symbols_failed` is unattributable and fails closed; `failed`/`running`/`killed`/
  `stopped` still block everything. A delisted watchlist ticker can no longer silence an
  intact 150-symbol approved scope, and vice versa.
- **Catch-up had to follow, or it would loop.** `catch_up_pending` required an `ok` run
  since the 17:30 cutoff. With ~151 symbols the run is `partial` whenever any one of them
  fails, so the 30-minute `catch_up` job would have re-run a ~30-minute EOD chain all
  evening over one permanently-bad ticker. A `partial` that finished after the cutoff and
  got the **whole configured universe** now counts as the session's update having run;
  a broad provider outage fails configured symbols too and still triggers a catch-up.
  This is inert for the pre-W6a world (a partial then always had a failed configured
  symbol).
- **Budget, and the overlap that is accepted rather than avoided.** ~151 symbols × 12.1 s
  pacing ≈ 30 min (Massive makes one request per symbol — `fetch_corporate_actions` and
  `fetch_earnings` return empty on this feed). The 17:30 ET chain finishes its ingest
  ~18:00–18:05 ET, leaving the rescan and approved-scope scan (local compute) to run into
  the `universe_update` slot at 18:15 ET on a slow evening. `universe_update` is a
  different APScheduler job and is **not** covered by `_EOD_UPDATE_LOCK`, so they can
  overlap. That is safe by construction, not luck: the ingest holds no write transaction
  across a provider call and commits per symbol (`docs/SQLITE_CONCURRENCY.md` rule 4), so
  the worst case is bounded lock contention with the usual retry. **Cron times were not
  moved.** If the chain starts running long, shorten the ingest window (`end - 400 days`)
  before touching the schedule.
- Provenance lives in `ingestion_run.gaps_json["__approved_scope__"]` (per-snapshot
  `added` symbols, universes excluded for source, skipped versions) — a dunder key, the
  convention the options backfill already set with `"__run__"` — and in `notes`, which
  stays byte-identical when no approved universe contributed.

## Execution-layer facts worth knowing

- `JobSpec`/`JobFn` moved to the leaf module `signalforge.jobspec` so the execution cycle
  never imports `signalforge.scheduler` (S15a). `scheduler` re-exports them.
- The execution cycle's `JobSpec` is injected from `cli.py` only, `self_guarded=True`, and
  `default_job_specs()` is byte-identical.
- Arming still needs (a) a `execution_limits` row whose `preregistration_doc_id` names a
  real file under `docs/`, (b) ≥ 20 closed paper trades with non-negative expectancy (or an
  audited override), (c) the operator's broker / options-level / capital-limit answers.
- Options paper account `options` created 2026-09-12 with $25,000 SIMULATED (decision 13).

## Deviations accepted at integration

- I-O6 reserves the **gross** collateral requirement and credits cash (D3 §8.0 invariant)
  rather than D3 §3.2's formula, which double-counted the credit.
- I-O4: `Gate` gains no `label` (would rewrite stored `gates_json`); `OptionsGate` carries it.
  `promote_on_pass` defaults to False because `approved_scan_groups` selects by horizon only.
- I-O2: `IngestionRun.status` gains `killed` / `stopped`; alerts fire only on `failed`/`partial`.
- S11b's forbidden list was extended at integration with the options paper siblings
  (`paper.auto_simulate`, `paper.options_ledger`, `paper.options_marks`,
  `paper.options_auto_simulate`) per I-O6's sibling rule.
