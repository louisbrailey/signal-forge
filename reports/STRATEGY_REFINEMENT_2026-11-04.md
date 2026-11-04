# R1 strategy refinements: improvements in places, no validated replacement

Research signal only — no order was placed.

**Disposition: all ten proposed refinements are rejected for replacement or activation.** Six reduced losses or increased mean validation-year return under combined stress; four made it worse. None cleared the predeclared uncertainty and consistency criteria. No parameter was revised to rescue a failed result.

Protocol: [R1](../docs/research/REFINEMENT_STUDY_2026-11-04.md), committed as `144ca41` before variant evaluation. Completed **441 funded books in 231 paired/comparator jobs**: ten baselines, ten refinements, one simpler SPY comparator, seven periods and three cost cases. Raw/action history is real Massive data; results are hypothetical simulations.

## Evaluation boundaries

- Warm-up data begins 2016-10-17. Development book: 2017–2020.
- Validation: 2021, 2022 and 2023, each starts flat with its own $10,000.
- Previously observed follow-up: 2024, 2025 and 2026 through November 2, each starts flat. Validation dispositions were saved before this stage and cannot be rewritten on resume.
- Every period was previously available in other research. There is **no untouched final-test or new sealed-look claim**. Fixed rules are not fitted, so these are chronological rolling evaluations rather than model-training folds.
- Annual books cannot be summed or compounded into a claimed continuous portfolio. The 2026 period is partial.

Each book retains whole shares, no leverage, 5% initial position allocation, 20% sector cap, 0.5% trade risk, 1.5% aggregate risk, 60% exposure cap, 10% drawdown entry halt, next-open fills, volume limits, splits and dividends. Base costs are 3bp slippage/5bp spread/zero commission; friction costs 10bp/10bp/zero commission; stress adds $0.005/share with a $1/order minimum. Regulatory fee history and realized fills remain unmodeled. Stress commissions are assumptions, not Webull published stock commissions.

## Validation mean annual net return

Each cell is **baseline → refinement**, averaged across the three independently funded validation years. These are not full-history CAGR or cash income.

| Strategy/version | Base costs | Higher friction | Combined stress |
|---|---:|---:|---:|
| high52_breakout.medium_swing@0.1.0 | +0.260% → -0.039% | +0.229% → -0.042% | -0.051% → -0.048% |
| mean_reversion.short_swing@0.2.0 | +0.243% → -0.044% | +0.235% → -0.054% | +0.135% → -0.081% |
| relative_strength.medium_swing@0.1.0 | +1.575% → +1.132% | +1.369% → +1.018% | +0.845% → +0.670% |
| trend_continuation.medium_swing@0.1.0 | +1.041% → +0.813% | +0.326% → +0.359% | -0.811% → -0.087% |
| trend_continuation.short_swing@0.1.0 | +1.221% → +0.808% | +0.570% → +0.380% | -0.590% → -0.068% |
| trend_pullback.short_swing@0.1.0 | +0.903% → +0.871% | +0.623% → +0.593% | +0.323% → +0.300% |
| tsmom_etf.medium_swing@0.1.0 | -0.710% → -0.320% | -1.003% → -0.666% | -1.620% → -1.172% |
| tsmom_etf.position@0.1.0 | +0.533% → +0.849% | +0.397% → +0.663% | -0.159% → +0.111% |
| turn_of_month.short_swing@0.1.0 | +0.553% → +0.226% | +0.114% → -0.421% | -1.480% → -1.729% |
| volatility_breakout.short_swing@0.2.0 | +0.130% → +0.206% | +0.123% → +0.156% | +0.057% → +0.122% |

## Combined-stress evidence and failed gates

The lower bound applies to the candidate-minus-baseline monthly return difference, in percentage points, using paired 3-month blocks and the predeclared multiplicity adjustment for 30 comparisons. None is above zero. It remains descriptive on reused history.

| Strategy/version | Candidate validation trades | Adjusted lower bound (pp/month) | Other failed stress gates |
|---|---:|---:|---|
| high52_breakout.medium_swing@0.1.0 | 1 | -0.0985 | positive mean annual return, thirty trades, two improved years, two positive years |
| mean_reversion.short_swing@0.2.0 | 4 | -0.0710 | positive mean annual return, thirty trades, two improved years, two positive years |
| relative_strength.medium_swing@0.1.0 | 55 | -0.1039 | two improved years |
| trend_continuation.medium_swing@0.1.0 | 67 | -0.1038 | positive mean annual return, two positive years |
| trend_continuation.short_swing@0.1.0 | 68 | -0.1202 | positive mean annual return, two positive years |
| trend_pullback.short_swing@0.1.0 | 44 | -0.0075 | two improved years |
| tsmom_etf.medium_swing@0.1.0 | 100 | -0.0350 | positive mean annual return, two positive years |
| tsmom_etf.position@0.1.0 | 60 | -0.0596 | two improved years, two positive years |
| turn_of_month.short_swing@0.1.0 | 206 | -0.1525 | positive mean annual return, two improved years, two positive years |
| volatility_breakout.short_swing@0.2.0 | 5 | -0.0106 | thirty trades, two improved years |

## Previously observed follow-up, combined stress

Baseline → refinement. This stage does not rescue failed validation.

| Strategy/version | 2024 | 2025 | 2026 through Nov 2 |
|---|---:|---:|---:|
| high52_breakout.medium_swing@0.1.0 | +0.392% → +0.000% | +0.274% → +0.000% | +0.211% → +0.000% |
| mean_reversion.short_swing@0.2.0 | -0.080% → +0.108% | +0.007% → +0.000% | -0.290% → +0.000% |
| relative_strength.medium_swing@0.1.0 | -0.158% → +0.488% | -2.005% → -1.810% | +0.112% → -0.008% |
| trend_continuation.medium_swing@0.1.0 | -0.196% → -0.196% | -0.806% → -0.937% | -1.290% → -0.559% |
| trend_continuation.short_swing@0.1.0 | -0.668% → -0.001% | -0.503% → -0.122% | -1.080% → -0.275% |
| trend_pullback.short_swing@0.1.0 | +0.178% → +0.302% | +0.013% → -0.121% | -0.113% → -0.454% |
| tsmom_etf.medium_swing@0.1.0 | -0.320% → -0.320% | -1.381% → +0.293% | +1.438% → +1.455% |
| tsmom_etf.position@0.1.0 | +1.469% → +1.469% | -0.970% → -0.218% | -0.003% → -0.369% |
| turn_of_month.short_swing@0.1.0 | -4.742% → -5.169% | -3.132% → -2.679% | +0.457% → +0.212% |
| volatility_breakout.short_swing@0.2.0 | -0.152% → +0.000% | +0.117% → +0.000% | -0.100% → -0.142% |

## What changed and what did not improve

- The extension limit reduced validation stress losses in short trend continuation from −0.590% to −0.068%, and medium trend continuation from −0.811% to −0.087%. Both still lost money and failed the uncertainty gate.
- The broad-market gate moved position momentum from −0.159% to +0.111% mean validation-year return, but failed positive-year, paired-improvement and uncertainty criteria. Its 2026 follow-up was worse than baseline.
- Breakout confirmation produced +0.122% versus +0.057% in validation, but only **five closed trades**, insufficient for inference. Follow-up 2024/2025 was cash-only; 2026 lost money.
- Mean-reversion confirmation worsened validation returns, from +0.135% to −0.081%, with four trades. Turn-of-month filtering also worsened validation. Neither becomes a replacement.
- The extension limit removed nearly all 52-week-high opportunities: one validation trade, zero follow-up trades. Cash-only is not evidence of a successful profitable strategy.
- Relative strength and trend pullback retained positive mean validation returns but earned less after refinement. Preserve their unchanged baselines; this does not newly approve those baselines.

## Simpler comparator and structural limitations

- SPY monthly trend-only, 2021: +0.993%, 4 closed trades.
- SPY monthly trend-only, 2022: -0.941%, 3 closed trades.
- SPY monthly trend-only, 2023: -0.179%, 6 closed trades.
- SPY monthly trend-only, 2024: +0.185%, 1 closed trades.
- SPY monthly trend-only, 2025: +0.000%, 0 closed trades.
- SPY monthly trend-only, 2026: +0.000%, 0 closed trades.

The $10,000 account/5% cap permits approximately $500 per initial position. Whole-share SPY purchases exceeded that cap in the 2025/2026 books; each had nine rejected entry attempts for `position concentration cap below one share`. This is a genuine execution-model/capital limitation, not missing trades to invent. Fractional-share simulation would require its own implementation, costs and separately registered comparison; neither larger positions nor leverage is introduced here.

The fixed surviving universe and current classifications/sectors introduce selection and point-in-time limitations. Corporate stocks remain excluded without decision-time earnings coverage. The snapshot contains zero earnings events; the existing key was previously verified as not entitled to the separate earnings endpoint. These ETF-heavy books are not complete stock-system validation. Benchmark and candidate exposure paths differ. Regulatory fees, cash interest, taxes, true historical spread and intraday price paths are unresolved.

## Reproducibility and tests

Baseline source: `cbc7acf7c0636ef66d6014b3d49d56dd0daf66ef`; study implementation at execution: `063e260`. A later source annotation identifies the manifest checksum as a non-secret; no strategy arithmetic changed. Dataset manifest: `edb199c01af7811a9ac8dd4237209af97cea476a9088949d7f84daa018dd8eb1`.

Final summary SHA256: `ec240ac8fb16799c23c78235eec4f2b57d834b08db5c1e2f7b139ce7ab51dcfc`.

The repeat run reproduced all 441 performance summaries after correcting report-only warm-up rejection counts. Resume verified all 231 case checksums and preserved timestamps/content of all 236 existing JSON artifacts. Changed source/protocol/data refuses resume. Future-price invariance, delayed fills, missing context, short rejection, multiplicity adjustment, no-trade rejection, future-fold isolation and corrupt-checkpoint tests pass.

Local full parallel suite: **2,815 passed**; serial suite: **1 passed**. Final focused suite after reporting/resume tests: **14 passed**. Ruff, Black, mypy and all **21 import contracts** passed. A manifest checksum triggered the secret scanner; its exact non-secret literal is annotated, with no broad secret-rule bypass.

```sh
PYTHONPATH=/absolute/archived-cbc7acf-source/src uv run python scripts/refinement_study.py \
  /absolute/raw-actions-v1 /absolute/new-r1-output \
  --database /absolute/market-snapshot.sqlite \
  --listing-evidence /absolute/listing-evidence.json --workers 3
# For interrupted runs, repeat the exact same inputs/source and add --resume.
```

The CLI refuses a different snapshot or strategy registry. Private local artifacts: `.toolkit-runs/refinement-r1-final-20261104/` contains design, case fills/decisions/marks, all costs/exposures/drawdowns, monthly returns, regime P&L, validation dispositions, metrics CSV and completion evidence. No source prices or private databases are committed.

## Disposition

Keep all R1 candidates offline. No operating registry, approval, collector, strategy parameter, risk limit, broker setting or frozen Kronos/forward study changed. No automatic paper trade or alert was created. Further work should first address execution-model fidelity and missing point-in-time inputs, then use a new prospective protocol. The observed history is not a fresh test set for repeatedly trying variants until returns turn positive.
