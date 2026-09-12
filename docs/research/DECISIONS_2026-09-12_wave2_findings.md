# Wave-2 integration findings (2026-09-12) — open items before any options evaluation

All five wave-2 tracks are merged on `main` (I-E3 paper_reference adapter, I-E4 arming /
dead man / reconciliation / calendar / guarded cycle, I-O2 short-commit backfill loop,
I-O4+I-O5 options gate ladder + O3 short vertical v0.1.0, I-O6 options paper mechanics).
Migration `b9d41e07c6aa` is applied live. Nothing is scheduled or armed by any of them.

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
  explicitly. **Still open:** the chain refuses (`OptionsEodUnpriceable`) a book spanning
  more than one underlying, because `mark_options_to_market` /
  `process_option_expiries` / `auto_simulate_options_scan_runs` each take ONE
  `OptionsPricingContext` per call and one `q` cannot honestly serve two names
  (decision 11). Widening that needs a per-underlying pricing resolver in
  `paper/options_marks.py`, which W3c deliberately did not open.
- The real options backfill (~29,376 requests, ~98.7 h) has not started; runbook
  `docs/research/options_designs/IO2_RUNBOOK.md` (nightly `--max-minutes 590`, never in the
  17:30–19:00 ET window, coverage-summary-only rule).

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
