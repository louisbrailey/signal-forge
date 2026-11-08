# Strategy evidence audit — November 8, 2026

The evidence pipeline had defects. This repair does **not** make losing strategies
profitable. Strategy rules, thresholds, sizing, costs, registrations, operating
settings, frozen Kronos/forward studies and their recorded outcomes are unchanged.
No promotion, provider request, sealed evaluation or paper trade was run.

## Verified inventory

The operating SQLite database was opened with SQLite `mode=ro` and
`PRAGMA query_only=ON`. Its ordinary `backtest_run`/`backtest_metric` inventory at
22:49 UTC contained **11 current equity strategies and 14 registered versions**.
Three versions (ORB, mean reversion and volatility breakout v0.1.0) are superseded
by v0.2.0. Those old records are retained, excluded from current-version counts,
and never deleted. Other strategy families, if registered, are reported separately.

| Current equity version | Latest recorded ordinary OOS state | Trades | Expectancy R |
|---|---|---:|---:|
| trend_continuation.short_swing 0.1.0 | Positive point estimate | 228 | +0.213 |
| trend_continuation.medium_swing 0.1.0 | Positive point estimate | 205 | +0.083 |
| relative_strength.medium_swing 0.1.0 | Positive point estimate | 127 | +0.152 |
| high52_breakout.medium_swing 0.1.0 | Positive point estimate | 525 | +0.227 |
| intraday_orb.intraday 0.2.0 | No ordinary OOS record | — | — |
| mean_reversion.short_swing 0.2.0 | No ordinary OOS record | — | — |
| volatility_breakout.short_swing 0.2.0 | No ordinary OOS record | — | — |
| tsmom_etf.medium_swing 0.1.0 | No ordinary OOS record | — | — |
| tsmom_etf.position 0.1.0 | No ordinary OOS record | — | — |
| turn_of_month.short_swing 0.1.0 | No ordinary OOS record | — | — |
| trend_pullback.short_swing 0.1.0 | No ordinary OOS record | — | — |

This table is **not a reproduction of a 14-strategy portfolio-performance study**.
It inventories what the current equity dashboard/scanner actually reads. Absence
of an ordinary OOS record does not mean no other development experiment exists.
The four runs use different windows/universes; their R values cannot be summed
into account dollars. Their old saved rows have no measured `data_provenance`
object; the new UI correctly labels that provenance unknown. Existing input bars
cannot retroactively establish exactly what an older run loaded.

## Confirmed repairs

1. The provenance source query previously considered all dates for the symbols,
   even when the bar-count query used a bounded window. It now uses the same
   window. Intraday provenance also uses the loaded interval and RTH filter,
   preventing unrelated 5-minute or pre-market rows from contaminating a
   15-minute RTH report. Bar loading and trade calculations are unchanged.
2. Persistence previously discarded measured input provenance. Newly saved runs
   retain source, simulation flag, bar count and actual dates, plus the executable
   spec hash. Caller-supplied metadata cannot replace these measured fields.
   A result cannot be saved under a different strategy/version. No old row is
   rewritten or silently certified as real.
3. Strategy Lab displays explicit missing/zero-trade/invalid/positive/negative
   evidence states, the run and window, timestamps, input provenance, confidence
   interval and saved cost assumptions. Missing numbers stay unavailable.
   A positive point estimate is explicitly separate from promotion and paper P&L.
4. The new offline inventory command reads published aggregate evidence only;
   it never reads sealed metrics or runs a study. Current and superseded versions
   have separate totals.

## Economic findings remain unresolved

Existing development-only snapshot-11 funded reports in the operating checkout
use 147 complete symbols, October 17, 2016 through September 7, 2025, $10,000,
5% initial allocation, 20% sector cap, 60% gross and 1.5% aggregate open risk.
These existing reports show:

| Strategy | Base total return | Higher-cost stress total return |
|---|---:|---:|
| Short trend | +36.47% | **−16.40%** |
| Medium trend | +25.07% | **−4.75%** |
| Relative strength | +16.31% | +3.59% |
| 52-week breakout | +8.79% | +2.38% |

Stress models $0.005/share with a $1 minimum per side, 10 bps slippage and
10 bps spread; base uses 3 bps slippage, 5 bps spread and zero commission.
These are price-only, survivor-universe descriptive replays without historical
scanner earnings eligibility or a dividend cash ledger. They are **not** fresh
holdout evidence, reliable-income evidence or permission to increase risk.
The source artifacts are the four `reports/funded/*_snap11_10k_cap5.json`
files in the operating checkout, not fixture tests. They were inspected, not
rerun or overwritten by this repair.

A priority composite additionally suppresses medium trend behind short trend:
their entry predicates are identical, and short trend is evaluated first.
The existing composite explicitly specifies that arbitration policy. Zero
medium-trend fills in that composite are not evidence that its standalone rule
was evaluated and lost. No policy was changed after observing these returns.

The earlier fixed refinement and fractional studies found no replacement that
cleared every prespecified criterion. Their conclusions are preserved. Changing
denominators, deleting losing experiments or relaxing risk limits would not
repair the economic losses.

## Reproduce the inventory

```sh
PYTHONPATH=src uv run python scripts/strategy_evidence_audit.py /absolute/path/signalforge.sqlite
```

The JSON lists current versions, superseded versions, source and confidence
limitations and exact saved aggregate values. The dashboard shows the same
read model at `/strategies`. No credential values, raw account data or secret
environment variables are included.

The next evidence requirement remains cost-realistic prospective paper results
for a fixed, separately registered candidate. This audit creates no new
profitable strategy and supplies no basis to promote a rejected strategy.

Research signal only — no order was placed.
