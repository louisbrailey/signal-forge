# Fractional share replay restores SPY entries under the 5% cap

Research signal only — no order was placed.

R2 compared 441 fractional books against 441 exactly reproduced whole-share
books in 231 jobs. Every fractional purchase met the 5% initial position cap
and available cash requirements. Fractional sizing restored four SPY entries
in each of 2025 and partial 2026. All ten strategy refinements failed the
predeclared validation criteria.

The [protocol](../docs/research/FRACTIONAL_STUDY_2026-11-06.md) was committed as
`6916b26` before replay. The comparison uses the R1 data archive through
November 2, 2026, the `cbc7acf` strategy source, and the study implementation
at `2c23ccd`. R2 uses 0.001-share entry increments and adverse cent rounding
on fractional settlements. The risk calculation reserves both commissions and
two cents for settlement rounding. These assumptions are part of the simulated
fill model. The $10,000 capital, percentage limits, corporate-action timing,
signals, and three cost scenarios come from R1.

## SPY sizing result

The whole-share SPY comparator recorded zero trades and nine affordability
rejections per period in 2025 and 2026 across each cost case. Fractional entry
sizes fit the available notional. Each of these periods has its own $10,000 book.

| Period | Modeled costs | Whole trades | Fractional trades | Fractional net return | Drawdown | Average exposure | Modeled cost |
|---|---|---:|---:|---:|---:|---:|---:|
| 2025 | Base | 0 | 4 | +0.294% | 0.33% | 2.89% | $2.28 |
| 2025 | Higher friction | 0 | 4 | +0.255% | 0.34% | 2.88% | $6.13 |
| 2025 | Combined stress | 0 | 4 | +0.175% | 0.36% | 2.89% | $14.12 |
| 2026 through Nov 2 | Base | 0 | 4 | −0.034% | 0.24% | 2.78% | $2.27 |
| 2026 through Nov 2 | Higher friction | 0 | 4 | −0.071% | 0.24% | 2.78% | $6.03 |
| 2026 through Nov 2 | Combined stress | 0 | 4 | −0.151% | 0.25% | 2.78% | $14.04 |

## Strategy validation under combined cost stress

Figures are mean annual returns for 2021–2023. The final two columns describe
the comparison of each fractional refinement against its fractional baseline.
The adjusted bound is a candidate-minus-baseline monthly difference in
percentage points, based on the R1 paired block method.

| Strategy | Whole baseline | Fractional baseline | Fractional refinement | Refinement trades | Adjusted lower bound (pp/month) |
|---|---:|---:|---:|---:|---:|
| 52-week-high breakout | −0.051% | −0.027% | −0.051% | 1 | −0.1164 |
| Mean reversion | +0.135% | +0.149% | −0.081% | 4 | −0.0812 |
| Relative strength | +0.845% | +0.947% | +0.701% | 55 | −0.1212 |
| Medium trend continuation | −0.811% | −0.792% | −0.040% | 67 | −0.1235 |
| Short trend continuation | −0.590% | −0.546% | −0.009% | 68 | −0.1416 |
| Trend pullback | +0.323% | +0.353% | +0.325% | 44 | −0.0092 |
| Medium ETF momentum | −1.620% | −1.762% | −1.428% | 90 | −0.0412 |
| Position ETF momentum | −0.159% | −0.626% | −0.451% | 54 | −0.0907 |
| Turn of month | −1.480% | −1.620% | −1.599% | 184 | −0.0741 |
| Volatility breakout | +0.057% | +0.090% | +0.150% | 5 | −0.0147 |

The position momentum refinement's whole-share mean of +0.111% became
−0.451% with fractional sizing. Volatility breakout's improvement rests on
five trades. The validation gate dispositions were saved before the follow-up
jobs. All periods use previously observed history. Interpret these results as
sensitivity to the fill model within an ETF-heavy dataset with missing historical
earnings coverage for corporate stocks.

## Reproduce

Use the archived strategy source and completed R1 results as explicit inputs.
The runner applies a checked patch to a temporary copy of the funded engine.
It audits entry timing, size, settlement, and cash for each fractional book,
reconciles end-of-period P&L, and verifies the whole-share record for every job.
The source, results, and summary are fingerprinted. Each resume verifies the
existing records and keeps their original bytes. R1 resumes use the source
revision recorded in the [R1 report](STRATEGY_REFINEMENT_2026-11-04.md).

```sh
PYTHONPATH=/absolute/archived-cbc7acf-source/src uv run python scripts/fractional_study.py \
  /absolute/raw-actions-v1 /absolute/completed-r1 /absolute/new-r2-output \
  --database /absolute/market-snapshot.sqlite \
  --listing-evidence /absolute/listing-evidence.json --workers 4
# Add --resume to repeat the same run with existing checkpoints.
```

Both runs produced identical performance summaries for all 441 pairs. The
entry audit covered 15,604 fractional fills and found a maximum allocation of
5.00%. Resuming the final run verified and preserved all 235 JSON artifacts.

The paired summary contains each book's returns, trade count, drawdown, exposure,
costs, and entry audit across all periods and costs. The final local study is
in `.toolkit-runs/fractional-r2-final-20261106/`. The archive, database, and
fill-level results stay in local study storage.

The focused suite passed 45 tests, covering next-open timing, cash reconciliation,
commissions, fractional splits and dividends, risk and volume caps, drawdown stops,
and checkpoint integrity. Lint, type checks, 21 import contracts, and the local
secret scans passed.
