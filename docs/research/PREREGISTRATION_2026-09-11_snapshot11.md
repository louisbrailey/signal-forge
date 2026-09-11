# Pre-registration — powered evaluations on the 150-symbol snapshot (2026-09-11)

Operator instruction (2026-09-11): finish work on every unapproved strategy and
approve/arm the ones that pass. Approval is decided by the ten promotion gates on
sealed data — never by hand. This record is written BEFORE the runs.

## What is run

`scripts/evaluate_on_snapshot.py --confirm` for the UNCHANGED v0.1.0 of:

| Strategy | Version id | Prior sealed looks (family) | This run |
|---|---|---|---|
| trend_continuation.medium_swing | 3 | 5 (snapshots 1–4; the hardened counter reports 4 prior tests + the replayed one) | look 6 |
| mean_reversion.short_swing | 4 | 5 | look 6 |

Dataset: `research_150_massive_10y_presealed_sel` (DataSnapshot 11; 150 symbols, 15
ETFs + 135 common stocks selected on a PRE-SEALED liquidity window; 10-year `massive`
history; W1-COMPLETE passed). Window 2016-09-10 → 2026-09-08, proxy SPY, source
`massive`, effective research config (scope hash `fe365720…`). Sealed window
2025-09-08 → 2026-09-08 has never been evaluated for these versions on this snapshot.

## Pre-registered expectations (from docs/research/STRATEGY_COMPLETION_MAP.md and the designs)

- v3: gates 1–8 expected to pass with more power; gate 9 is a fresh sealed test with
  roughly 6× the trades of snapshot 3. Its snapshot-3 miss was −0.16 SE from zero and
  snapshot-dependent. Outcome genuinely uncertain.
- v4: gates 3/4/7 are point-estimate gates that breadth cannot move (map §2.2, design
  §5.3); expected to FAIL again. The run is still made because the operator asked for
  every strategy's strongest legitimate test, and a fail is reported as such.

## Rules

- No parameter, threshold, or cost changes. Both outcomes are reported verbatim.
- A pass writes PAPER_APPROVED automatically and a new approved scope on snapshot 11;
  the per-strategy approved-universe scan (in progress) is what makes such a scope
  operable.
- No further sealed look for these versions on this snapshot afterwards.
- Run with the worker stopped; sealed-test row count must go from 20 to 22 exactly.
