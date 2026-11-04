# Slow trend v1: positive net P&L, no established incremental edge

Paper research only. Fixed protocol: [SLOW_TREND_V1](../docs/research/SLOW_TREND_V1.md).
No strategy, threshold, operating account, frozen Kronos study or forward plan was
changed. This candidate is not in the operating strategy registry.

Real cached Massive raw daily history: SPY, QQQ, IWM, DIA each have **2,525 bars**,
2016-10-17–2026-11-02 (10,100 observations). Input manifest SHA256:
`edb199c01af7811a9ac8dd4237209af97cea476a9088949d7f84daa018dd8eb1`.
Raw-price quantities and dividends use the existing action-aware funded engine.
No provider calls, fixture performance data, or live account writes.

Continuous portfolio replay: 2018-01-02–2026-11-02, $10,000 shared starting cash,
5% position cap, 20% sector cap, no leverage; 10% drawdown entry halt. Prices,
features and decisions are point-in-time prefixes. Base: 3bp slippage + 5bp full
spread. Stress: 10bp slippage + 10bp full spread + $0.005/share ($1/order minimum).

| Book | Base net return | Stress net return | Stress trades | Stress modeled costs | Stress max drawdown |
|---|---:|---:|---:|---:|---:|
| Monthly slow trend | 5.353% | 1.994% ($199.36) | 108 | $343.15 | 3.668% |
| Same rules without trend filter | 8.576% | 3.353% | 140 | $442.89 | 5.744% |
| Cash, no interest | 0% | 0% | 0 | $0 | 0% |

Candidate stress CAGR is **0.224%**, with average exposure **6.29%**. This is
whole-account performance; do not extrapolate it to fully invested capital.
The simpler book averaged 8.76% exposure under identical risk limits; different
utilization is part of the comparison, not evidence of risk-adjusted superiority.
Cash interest, taxes, historical quotes and intraday path uncertainty are omitted.

| Annual fold | Candidate stress return | Simpler stress return | Interpretation |
|---|---:|---:|---|
| 2021 | +1.061% | +1.272% | Validation |
| 2022 | −2.022% | −4.676% | Validation |
| 2023 | −0.419% | +1.033% | Validation |
| 2024 | +1.407% | +1.407% | Previously observed follow-up |
| 2025 | −0.612% | −0.136% | Previously observed follow-up |
| 2026 through Nov 2 | +0.716% | +0.858% | Previously observed follow-up |

Annual books each reset to $10,000; never sum them as one compounded portfolio.
Parameters were not fitted. The continuous replay overlaps development history;
all historical intervals were previously available, so there is **no untouched
final-test claim**, and no sealed study look was spent.

Paired 3-month block bootstrap across 107 monthly marks, 2,000 draws, fixed seed:
candidate-minus-simpler mean monthly difference **−0.0132 percentage points** under
stress; 95% interval **[−0.0727, +0.0517]**. Base interval **[−0.0981, +0.0383]**.
Both span zero. This does not establish an incremental edge. The interval is
descriptive on already-seen history, not a multiple-experiment-adjusted claim.

Predeclared one-factor stress sensitivity net returns: SMA160 2.071%, SMA240
2.303%; stop2.4ATR 3.372%, stop3.6ATR 4.368%; hold100 2.084%, hold151 2.680%.
No alternative is selected or promoted. Stress entries by market state: bull/low
70, bull/high31, neutral/high4, neutral/low1, bear/high2. Non-bull evidence is thin.

Net trade P&L by symbol excluding separate dividend credits: DIA −$51.99,
IWM +$21.99, QQQ +$124.81, SPY +$36.03. Dividend credits +$68.52. Removing the
best trade leaves +$127.17; that is still not independent evidence of skill.
Four current surviving, correlated ETFs limit breadth and introduce selection
bias. Income targets are not met. **Disposition: experimental; no promotion or
automatic paper entries.** Preserve the result instead of tuning until it wins.

Reproduce from the existing verified raw cache (output must not already exist):

```sh
PYTHONPATH=src uv run python scripts/slow_trend_report.py /absolute/raw-actions-v1 \
  .toolkit-runs/slow-trend-reproduction \
  --database /absolute/signalforge.sqlite \
  --listing-evidence /absolute/verified-security-metadata.json
```

Design and code hashes, exact fills/decisions, annual results and sensitivity are
written locally. The database is opened read-only for instrument metadata.
See [study operations](../docs/RESEARCH-STUDY-OPERATIONS.md) for the independent
ongoing evidence collectors. Research signal only — no order was placed.
