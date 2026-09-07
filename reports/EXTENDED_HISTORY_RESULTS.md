# Extended-history backtest (frozen strategy)

> Hypothetical research output. Costs from the project cost model are baked in. The strategy, thresholds, scoring and sizing are unchanged from the prior baseline — results are directly comparable. No parameter was tuned in this phase.

- Data: `massive` real daily bars, 2016-10-17..2026-09-04
- Universe: 25 symbols (24 with >=2000 sessions)
- Cost model: 3.0 bps slippage + half-spread; commission 0.0/sh
- Sealed final-test window: **2025-09-04 .. 2026-09-04** (evaluated once)
- Rolling walk-forward: 4 contiguous folds over 2016-10-17 .. 2025-09-04
- Benchmark (SPY buy&hold): +262.6% full span, +18.7% sealed

## Symbol coverage (survivorship note)

| symbol | sessions | first |
|---|--:|---|
| AAPL | 2485 | 2016-10-17 |
| AMZN | 2485 | 2016-10-17 |
| DIA | 2485 | 2016-10-17 |
| GOOGL | 2485 | 2016-10-17 |
| HD | 2485 | 2016-10-17 |
| IWM | 2485 | 2016-10-17 |
| JPM | 2485 | 2016-10-17 |
| META | 1212 | 2021-06-30 |
| MSFT | 2485 | 2016-10-17 |
| NVDA | 2485 | 2016-10-17 |
| QQQ | 2485 | 2016-10-17 |
| SPY | 2485 | 2016-10-17 |
| UNH | 2485 | 2016-10-17 |
| XLB | 2485 | 2016-10-17 |
| XLC | 2065 | 2018-06-19 |
| XLE | 2485 | 2016-10-17 |
| XLF | 2485 | 2016-10-17 |
| XLI | 2485 | 2016-10-17 |
| XLK | 2485 | 2016-10-17 |
| XLP | 2485 | 2016-10-17 |
| XLRE | 2485 | 2016-10-17 |
| XLU | 2485 | 2016-10-17 |
| XLV | 2485 | 2016-10-17 |
| XLY | 2485 | 2016-10-17 |
| XOM | 2485 | 2016-10-17 |

META has a short/gapped series (ticker discontinuity FB→META); XLC starts at its 2018 launch. The universe is a *fixed hand-picked list* of large-cap survivors — **it embeds survivorship bias**: no delisted names, no point-in-time membership.

## Per strategy

### intraday_orb.intraday

_intraday — no intraday history; skipped_

### trend_continuation.short_swing  (v0.1.0, status experimental)

| segment | trades | total ret | CAGR | ann vol | Sharpe | Sortino | maxDD | hit | PF | turnover/yr | exposure |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| full 2016-2026 | 1337 | +124.0% | +8.5% | 8.5% | +1.00 | +1.76 | 27.8% | 47% | 1.24 | 135.3 | 1.00 |
| train+WF (pre-sealed) | 1188 | +84.7% | +7.2% | 8.2% | +0.88 | +1.49 | 27.8% | 48% | 1.21 | 133.8 | 1.00 |
| SEALED final-test | 149 | +21.3% | +21.3% | 10.7% | +1.86 | +4.36 | 6.3% | 45% | 1.55 | 149.1 | 1.00 |

Rolling walk-forward folds (pre-sealed span):

| fold | trades | total ret | Sharpe | maxDD | hit |
|---|--:|--:|--:|--:|--:|
| fold 1 (2016-10-17..2019-01-06) | 333 | +15.5% | +0.85 | 13.5% | 47% |
| fold 2 (2019-01-06..2021-03-27) | 370 | -0.5% | +0.03 | 26.1% | 45% |
| fold 3 (2021-03-27..2023-06-16) | 194 | -1.0% | -0.05 | 16.7% | 45% |
| fold 4 (2023-06-16..2025-09-04) | 291 | +62.3% | +2.59 | 8.5% | 52% |

By entry-date regime (full span):

| regime | trades | total ret | Sharpe | maxDD |
|---|--:|--:|--:|--:|
| bear_highvol | 1 | +0.1% | +0.00 | 0.0% |
| bear_lowvol | 22 | -4.3% | -2.29 | 8.8% |
| bull_highvol | 173 | +38.7% | +1.11 | 3.7% |
| bull_lowvol | 930 | +49.4% | +0.64 | 32.8% |
| range_bound | 78 | +14.6% | +0.71 | 6.2% |
| warmup | 133 | -1.6% | -0.22 | 11.7% |

Concentration: top-3 symbols ['DIA', 'XLK', 'GOOGL'] account for 17% of trades. Frozen strategy — no tuning applied.

### trend_continuation.medium_swing  (v0.1.0, status experimental)

| segment | trades | total ret | CAGR | ann vol | Sharpe | Sortino | maxDD | hit | PF | turnover/yr | exposure |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| full 2016-2026 | 1223 | +155.0% | +9.9% | 8.8% | +1.12 | +2.09 | 28.5% | 43% | 1.26 | 123.8 | 1.00 |
| train+WF (pre-sealed) | 1089 | +152.2% | +11.0% | 8.8% | +1.23 | +2.34 | 28.5% | 44% | 1.29 | 122.6 | 1.00 |
| SEALED final-test | 134 | +1.1% | +1.1% | 8.7% | +0.17 | +0.27 | 8.3% | 40% | 1.03 | 134.1 | 1.00 |

Rolling walk-forward folds (pre-sealed span):

| fold | trades | total ret | Sharpe | maxDD | hit |
|---|--:|--:|--:|--:|--:|
| fold 1 (2016-10-17..2019-01-06) | 310 | +31.5% | +1.43 | 13.3% | 45% |
| fold 2 (2019-01-06..2021-03-27) | 327 | +13.1% | +0.63 | 23.0% | 43% |
| fold 3 (2021-03-27..2023-06-16) | 183 | +4.8% | +0.35 | 17.7% | 41% |
| fold 4 (2023-06-16..2025-09-04) | 269 | +61.9% | +2.28 | 9.8% | 46% |

By entry-date regime (full span):

| regime | trades | total ret | Sharpe | maxDD |
|---|--:|--:|--:|--:|
| bear_highvol | 1 | +0.1% | +0.00 | 0.0% |
| bear_lowvol | 22 | -4.7% | -2.51 | 9.2% |
| bull_highvol | 165 | +44.9% | +1.14 | 4.2% |
| bull_lowvol | 841 | +37.9% | +0.52 | 33.2% |
| range_bound | 71 | +23.0% | +0.98 | 7.0% |
| warmup | 123 | +8.7% | +1.29 | 8.9% |

Concentration: top-3 symbols ['XLK', 'DIA', 'NVDA'] account for 17% of trades. Frozen strategy — no tuning applied.

### mean_reversion.short_swing  (v0.1.0, status experimental)

| segment | trades | total ret | CAGR | ann vol | Sharpe | Sortino | maxDD | hit | PF | turnover/yr | exposure |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| full 2016-2026 | 1114 | -20.6% | -2.3% | 4.5% | -0.49 | -0.66 | 37.9% | 54% | 0.89 | 112.7 | 1.00 |
| train+WF (pre-sealed) | 999 | -26.8% | -3.5% | 4.6% | -0.74 | -0.98 | 37.9% | 53% | 0.83 | 112.5 | 1.00 |
| SEALED final-test | 115 | +8.4% | +8.4% | 3.8% | +2.12 | +3.35 | 2.3% | 65% | 1.62 | 115.1 | 1.00 |

Rolling walk-forward folds (pre-sealed span):

| fold | trades | total ret | Sharpe | maxDD | hit |
|---|--:|--:|--:|--:|--:|
| fold 1 (2016-10-17..2019-01-06) | 257 | +2.0% | +0.21 | 10.7% | 57% |
| fold 2 (2019-01-06..2021-03-27) | 293 | -25.0% | -2.37 | 32.4% | 48% |
| fold 3 (2021-03-27..2023-06-16) | 184 | +3.7% | +0.49 | 8.1% | 58% |
| fold 4 (2023-06-16..2025-09-04) | 265 | -7.7% | -0.78 | 19.8% | 51% |

By entry-date regime (full span):

| regime | trades | total ret | Sharpe | maxDD |
|---|--:|--:|--:|--:|
| bear_highvol | 44 | -16.6% | -3.26 | 17.1% |
| bear_lowvol | 3 | +0.0% | +0.03 | 0.5% |
| bull_highvol | 311 | +23.6% | +0.96 | 7.5% |
| bull_lowvol | 425 | -3.4% | -0.14 | 14.6% |
| range_bound | 271 | -26.0% | -1.30 | 26.4% |
| warmup | 60 | +7.7% | +3.45 | 3.1% |

Concentration: top-3 symbols ['XLF', 'SPY', 'IWM'] account for 14% of trades. Frozen strategy — no tuning applied.

### relative_strength.medium_swing  (v0.1.0, status experimental)

| segment | trades | total ret | CAGR | ann vol | Sharpe | Sortino | maxDD | hit | PF | turnover/yr | exposure |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| full 2016-2026 | 679 | +114.0% | +8.0% | 5.9% | +1.33 | +2.55 | 17.8% | 47% | 1.44 | 68.7 | 1.00 |
| train+WF (pre-sealed) | 591 | +97.6% | +8.0% | 5.9% | +1.34 | +2.56 | 17.8% | 47% | 1.45 | 66.5 | 1.00 |
| SEALED final-test | 88 | +8.3% | +8.3% | 6.2% | +1.31 | +2.43 | 3.3% | 47% | 1.37 | 88.1 | 1.00 |

Rolling walk-forward folds (pre-sealed span):

| fold | trades | total ret | Sharpe | maxDD | hit |
|---|--:|--:|--:|--:|--:|
| fold 1 (2016-10-17..2019-01-06) | 115 | +9.5% | +0.87 | 9.9% | 44% |
| fold 2 (2019-01-06..2021-03-27) | 171 | +12.3% | +0.86 | 16.2% | 43% |
| fold 3 (2021-03-27..2023-06-16) | 121 | +41.2% | +2.93 | 6.5% | 58% |
| fold 4 (2023-06-16..2025-09-04) | 184 | +13.8% | +0.91 | 11.7% | 44% |

By entry-date regime (full span):

| regime | trades | total ret | Sharpe | maxDD |
|---|--:|--:|--:|--:|
| bear_highvol | 6 | -3.0% | -62.15 | 3.0% |
| bear_lowvol | 5 | +4.9% | +4.37 | 0.0% |
| bull_highvol | 219 | +27.4% | +0.85 | 7.3% |
| bull_lowvol | 345 | +74.6% | +1.36 | 11.8% |
| range_bound | 104 | -5.5% | -0.27 | 16.6% |

Concentration: top-3 symbols ['NVDA', 'AAPL', 'GOOGL'] account for 24% of trades. Frozen strategy — no tuning applied.

### volatility_breakout.short_swing  (v0.1.0, status experimental)

| segment | trades | total ret | CAGR | ann vol | Sharpe | Sortino | maxDD | hit | PF | turnover/yr | exposure |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| full 2016-2026 | 223 | +16.8% | +1.6% | 2.9% | +0.56 | +1.00 | 6.4% | 51% | 1.32 | 22.6 | 0.63 |
| train+WF (pre-sealed) | 213 | +17.7% | +1.8% | 3.0% | +0.64 | +1.14 | 6.4% | 52% | 1.36 | 24.0 | 0.67 |
| SEALED final-test | 10 | -0.7% | -0.7% | 1.9% | -0.36 | -0.59 | 1.9% | 30% | 0.76 | 10.0 | 0.24 |

Rolling walk-forward folds (pre-sealed span):

| fold | trades | total ret | Sharpe | maxDD | hit |
|---|--:|--:|--:|--:|--:|
| fold 1 (2016-10-17..2019-01-06) | 36 | +8.8% | +1.60 | 2.1% | 61% |
| fold 2 (2019-01-06..2021-03-27) | 98 | +5.5% | +0.70 | 4.9% | 53% |
| fold 3 (2021-03-27..2023-06-16) | 35 | +0.0% | +0.01 | 4.7% | 54% |
| fold 4 (2023-06-16..2025-09-04) | 44 | +2.5% | +0.34 | 5.2% | 41% |

By entry-date regime (full span):

| regime | trades | total ret | Sharpe | maxDD |
|---|--:|--:|--:|--:|
| bull_highvol | 18 | +2.9% | +0.39 | 1.6% |
| bull_lowvol | 160 | +11.8% | +0.50 | 6.4% |
| range_bound | 31 | +1.7% | +0.26 | 4.1% |
| warmup | 14 | -0.2% | -0.10 | 2.1% |

Concentration: top-3 symbols ['SPY', 'QQQ', 'DIA'] account for 32% of trades. Frozen strategy — no tuning applied.

