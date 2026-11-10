# Pre-registration — R3-P: do the entry signals beat random entries with the same exits?

Status: written 2026-11-10 before any backtest of this study. Operator request
(2026-11-10): "continue pushing for more profit within each strategy and the kronos ai
part of the workflow". No sealed look, no operating-database write, no change to any
frozen study or approved version. Results file, named in advance:
`docs/research/RESULTS_r3_placebo_timing_2026-11-10.md`.

## Why

Every approved rule is long-only, regime-gated and run on a universe chosen in 2025 from
names with ten years of history (survivors). Long entries with a stop at 1.5–2.5 ATR and
a target at twice that can earn positive R on such names with no timing skill at all.
`docs/research/RESULTS_funded_approved_set_2026-11-08.md` found no approved rule ahead
of exposure-matched SPY. No document in `docs/research` tests the signals against a
random-entry null. Where the R comes from decides what to improve next: the trigger
(if it has timing value) or exposure and capacity (if it does not).

## Scope (fixed)

- The four PAPER_APPROVED versions on their approved snapshots (3 or 11), daily
  `massive` adjusted bars from the read-only scratch copy of 2026-11-10, window
  2016-10-17..2025-09-05. Nothing on or after 2025-09-07 is loaded.
- Library engine, costs and regime series unchanged. Results are reported in engine R
  and, where the R3-E script is available, in stable R (`(exit − entry)/(close_t − stop_t)`).

## Placebo construction

For each version, K = 200 placebo runs (seed 20261110 + run index):

- **P-gate (primary null):** for every symbol and calendar year, draw as many entry
  signal dates as the actual rule produced *trades* in that symbol-year, uniformly from
  that symbol-year's bars on which the version's own regime gate allows an entry. Stop,
  target and time stop are built from ATR14 at the drawn bar with the version's own
  multiples, exactly as the rule would. The engine's one-position-per-symbol rule
  applies; a draw that falls inside an open placebo trade is redrawn up to 20 times, then
  dropped (the shortfall is reported).
- **P-trend (secondary null):** as P-gate, but dates are drawn only from bars that also
  satisfy the minimal trend state `close > SMA50`. This separates "be long in an
  uptrend" from the specific trigger.

## Metrics

Per version, for IS, OOS (runner definition) and the whole window: actual expectancy and
total R; placebo mean, 2.5th and 97.5th percentiles; **timing alpha** = actual expectancy
− placebo mean; one-sided p = share of placebo runs with expectancy ≥ actual (reported
with the (k+1)/(K+1) correction). Also the same comparison for win rate, mean hold and
total R per year.

## Reading the result (fixed in advance; no pass/fail gate)

- Timing alpha with p < 0.05 against P-gate on **both** IS and OOS: the trigger adds
  value beyond gated exposure. Against P-trend as well: the trigger adds value beyond a
  simple trend state.
- Otherwise the version's R is not distinguishable from gated (or trend-state) exposure
  with its exit geometry on this universe. That does not make the rule unprofitable; it
  means refinement effort belongs in exposure, capacity and costs, and that a looser
  trigger with the same exits is a legitimate candidate to pre-register next.
- Holm adjustment across the four versions for the primary (P-gate, OOS) comparison.

## Expectations (stated in advance)

Placebo expectancy will be clearly positive on both universes. Timing alpha is expected
to be positive but small for the two trend_continuation versions and high52 (volume
surge and new-high conditions), and uncertain for relative_strength. A null for one or
more versions is a likely outcome and will be reported plainly.

## Limits

The placebo inherits the same survivorship and the same regime gate as the rule; it
measures the trigger's value only. It says nothing about a different universe or about
the sealed year. No sealed data is used.

Research signal only — no order was placed.
