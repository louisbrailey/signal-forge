# Pre-registration — R3-E: entry execution and the risk unit (engine item H14)

Status: written 2026-11-10 before any backtest of this study. Operator request (2026-11-10):
"continue pushing for more profit within each strategy and the kronos ai part of the
workflow". No sealed look, no operating-database write and no change to any frozen
study, approved version, threshold or cost is authorised or performed. Results file,
named in advance: `docs/research/RESULTS_r3_entry_execution_2026-11-10.md`.

## Why

`docs/research/diagnostics/v3_duration_exits.md` §6(a) and
`docs/research/dispositions/trend_continuation_medium_swing.md` §8 record that trades
closed on their entry bar are the largest single loss bucket (about −0.75R each, 45% of
trend_continuation.medium's pre-sealed total R and 84% of trend_continuation.short's),
and that part of it is an artefact: the stop is fixed off bar *t*'s close while the fill
and the risk unit come from bar *t+1*'s open (`backtest/engine.py:108-111`), and an entry
that opens below its stop is booked as about +1R (`engine.py:166`). The size of that
distortion "has **not** been measured". A gap rule for the trend rules is untested.
The live scan sizes the order at signal time, so the operationally faithful risk unit is
the planned one, `U = close_t − stop_t`.

## Scope (fixed)

- Versions and universes: the four PAPER_APPROVED versions on their approved snapshots —
  trend_continuation.short_swing and relative_strength.medium_swing on snapshot 3;
  trend_continuation.medium_swing and high52_breakout.medium_swing on snapshot 11.
- Data: persisted `massive` adjusted daily bars from a read-only scratch copy of the
  operating database taken 2026-11-10. Window 2016-10-17..2025-09-05 (last development
  session). Nothing on or after 2025-09-07 is loaded.
- Costs: unchanged base model (5.5 bps per side). Stress sensitivity at 11 bps per side
  for the final candidates only.
- Selection sample (IS): entries before each symbol's 60% bar boundary, exactly as
  `research/backtest_runner.py` defines it. Confirmation sample (OOS): the rest. The
  runner's OOS has been inspected by earlier work on these versions; it is a confirmation
  sample, not an untouched holdout. Only prospective evidence is clean.

## Definitions

- **B0** — library engine unchanged. The study script must reproduce the recorded
  development OOS rows to four decimals before anything else is reported: 341 / +0.2648R,
  197 / +0.3004R, 1,986 / +0.2209R, 525 / +0.2274R (backtest_run 53, 54, 55, 49).
- **Stable R** — `(exit_fill − entry_fill) / U`, with `U = close_t − stop_t` fixed at the
  signal. This is the dollar result per dollar of planned risk for an order sized the
  evening before.
- **B1 (corrected baseline)** — same signals and exits as B0, measured in stable R, with
  an entry whose open is at or below the stop treated as *no trade* (the signal is
  invalid at the open). B1 is a measurement correction, not a candidate rule.

## Variants (all decidable from the opening print; each is a full re-simulation)

| Id | Rule | Cells |
|---|---|---|
| V1 | Opening limit: enter at the open only if `open ≤ close_t + g·ATR14_t`; otherwise no trade | g ∈ {0.3, 0.6, 1.0} |
| V2 | Weak-open skip: enter at the open only if `open ≥ close_t − h·ATR14_t`; otherwise no trade | h ∈ {0.3, 0.6, 1.0} |
| V3 | Fill-anchored bracket: stop and target recomputed from the fill with the version's own ATR multiples (target rule unchanged where the version has no ATR target) | 1 |

No other variant is run. A skipped entry frees the symbol for its next signal, as in the
engine. No intraday fills after the open are assumed.

## Metrics and tests

Per version and cell, on IS and OOS separately: trades, expectancy in stable R, total
stable R per year, share and mean R of entry-bar exits, worst trade.

1. **Correction (fact, no test):** B0 expectancy versus B1 expectancy, IS / OOS / all.
2. **Selection:** on IS only, per version, pick at most one V1 cell, one V2 cell and
   V3-or-not — each only if it raises IS expectancy *and* IS total R per year versus B1.
   The combination chosen is that version's candidate **E\***; if nothing qualifies,
   E\* = B1 and the version reports "no candidate".
3. **Confirmation (one test per version, four in total):** OOS expectancy of E\* minus
   OOS expectancy of B1, one-sided. Null distribution by calendar-month block bootstrap
   (10,000 resamples of entry months, both arms resampled with the same months, seed
   20261110). Holm adjustment across the four versions at α = 0.05.

## Decision rule (fixed)

E\* is reported as an **upgrade candidate** for a version only if all hold on OOS:
Holm-adjusted p < 0.05; total stable R per year not more than 10% below B1; the
difference has the same sign in at least three of the four calendar folds used by
promotion gate 1; and the difference stays positive at 11 bps per side. Anything else is
reported as "no upgrade", with every cell's numbers shown. No re-run after a fail, no
added cells.

## Expectations (stated in advance)

B1 will differ from B0 by a few hundredths of an R in either direction. V1 and V2 are
expected to cut trade count by 10–30%; whether expectancy rises enough to confirm on OOS
is genuinely uncertain. A null is a likely outcome and will be reported as such.

## What a pass does and does not license

A pass is evidence for a *new version* of that strategy (R3/R7: never changed in place),
which would still need the full gate ladder, an operator-authorised sealed look (look
k+1 for its family) and forward paper evidence. Nothing here changes any approved
version, the operating scan, the paper ledger or the frozen v2 studies.

Research signal only — no order was placed.
