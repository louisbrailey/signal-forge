# Pre-registration — 500-symbol liquid universe, development evaluation (2026-11-02)

**Status: pre-registered BEFORE any backtest on this universe.** Written 2026-11-02 at the
operator's request ("more symbols traded month to month"). Scratch-copy run; the live
database is not written.

## Hypothesis

The daily strategies' per-trade edge thins as the universe widens (24 → 150 symbols cut
`trend_continuation.short_swing` OOS expectancy from +0.265R to +0.155R). A 500-symbol
liquid universe is expected to thin it further; the question this run answers is whether
each strategy still clears gates 1–8 at 500 symbols, and at what expectancy, so the
operator can trade off breadth against per-trade edge with evidence.

## Universe rule (frozen; `docs/research/diagnostics/universe500_selection_presealed.json`)

Rule **W1-SEL-P** from `docs/research/diagnostics/w1_selection_presealed.md`, with these
two changes and nothing else:

1. Composition: the 15 snapshot-3 ETFs verbatim **plus the top 485 common stocks** (was 135).
2. Additional filter: the symbol must have `source='massive'` daily bars from on or before
   2016-10-17 through at least 2025-09-05 with ≥ 2,200 sessions (the backtest reads that
   source; 751 of the 1,240 filtered pool members qualify).

Liquidity statistic unchanged: median of close × volume over the 60 most recent pre-sealed
`massive_grouped` sessions, 2025-06-11 → 2025-09-05. META excluded (blended series). Ranks
1–15 of the common stocks are identical to snapshot 11's. Rank-485 median dollar volume is
≈ $127M/day. Reserve: next 20 by rank.

Known biases, disclosed not fixed: bars are split-adjusted as of fetch, not point-in-time;
discovery was active-only, so the set is survivorship-biased (same as snapshot 11).

## Command (scratch copy, one writer)

```
SIGNALFORGE_DATA_DIR=<scratch> DATABASE_URL=sqlite+pysqlite:///<scratch>/signalforge.sqlite \
uv run signalforge evaluate-promotion --symbols "$(cat syms500.txt)" \
  --snapshot-key research_500_massive_presealed_liq --since 2016-10-17 --until 2025-09-07
```

All six default strategies run. Gates and thresholds are the shipped ones, unchanged.
`--until 2025-09-07` keeps the sealed year (≥ 2025-09-08) out of the development window;
gate 9 on this new snapshot is therefore a **diagnostic** window (2024-09-07..2025-09-07,
development data), not a sealed look.

## What the result can and cannot do

- A gate 1–8 pass on 500 symbols is **development evidence only**. Approval on this universe
  would need (a) an operator-authorised one-time sealed look on the real sealed year for
  this snapshot key, and (b) a passing evaluation in the live database, exactly as for the
  existing approvals.
- A fail is recorded as such in `docs/research/RESULTS_full_pipeline_2026-11-02.md`.
- Cost model is the shipped one (11 bps round trip); rank-485 liquidity makes that
  optimistic for the tail, which is noted against any pass.
