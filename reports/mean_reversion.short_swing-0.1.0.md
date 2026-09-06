# Backtest report — mean_reversion.short_swing v0.1.0

> **Hypothetical research output.** Simulated fills include modeled commission, spread and slippage. Past results do not predict future results. This strategy is **EXPERIMENTAL** (paper only, no alerts) until promoted.

- Generated: 2026-09-06T18:11:12+00:00
- git: `e94fe71`  ·  config hash: `3964441158a7f324ddf7b38dcea49a4c847cd9a493297eb3e6e3046f2db6f59b`
- Horizon: SHORT_SWING
- Window: 2023-08-28 → 2026-09-06
- Universe (25): AAPL, AMZN, DIA, GOOGL, HD, IWM, JPM, META, MSFT, NVDA, QQQ, SPY, UNH, XLB, XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, XLY, XOM
- Data: fixture/simulated unless a real provider was configured at run time

## In-sample vs out-of-sample

| Segment | Trades | Win rate | Avg win (R) | Avg loss (R) | Expectancy (R) | Profit factor | Max drawdown (R) | Risk-adj ratio* | Avg bars held | Worst losing streak | Total return (R) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| In-sample (first 60%) | 133 | 6.0% | +0.25 | -1.06 | -0.981 | 0.02 | 130.53 | -26.49 | 2.6 | 62 | -130.5 |
| Out-of-sample (last 40%) | 88 | 5.7% | +0.18 | -1.04 | -0.973 | 0.01 | 85.63 | -28.98 | 2.5 | 27 | -85.6 |

Out-of-sample bootstrap 95% CI:

- Expectancy (R): -1.040 … -0.900 (point -0.973)
- Profit factor: 0.00 … 0.02

## Out-of-sample by market regime (entry-date regime)

| Segment | Trades | Win rate | Avg win (R) | Avg loss (R) | Expectancy (R) | Profit factor | Max drawdown (R) | Risk-adj ratio* | Avg bars held | Worst losing streak | Total return (R) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| bear/low | 2 | 0.0% | +0.00 | -1.01 | -1.007 | 0.00 | 2.01 | -31784.91 | 3.0 | 2 | -2.0 |
| neutral/high | 63 | 7.9% | +0.18 | -1.04 | -0.940 | 0.02 | 59.19 | -25.30 | 2.3 | 20 | -59.2 |
| neutral/low | 23 | 0.0% | +0.00 | -1.06 | -1.062 | 0.00 | 24.42 | -72.74 | 2.8 | 23 | -24.4 |

## Trades per symbol

| Symbol | Trades |
|---|---|
| AAPL | 7 |
| AMZN | 7 |
| DIA | 10 |
| GOOGL | 7 |
| HD | 11 |
| IWM | 9 |
| JPM | 3 |
| META | 9 |
| MSFT | 11 |
| NVDA | 9 |
| QQQ | 5 |
| SPY | 14 |
| UNH | 10 |
| XLB | 5 |
| XLC | 8 |
| XLE | 9 |
| XLF | 5 |
| XLI | 12 |
| XLK | 6 |
| XLP | 13 |
| XLRE | 14 |
| XLU | 6 |
| XLV | 13 |
| XLY | 9 |
| XOM | 9 |

\* Risk-adjusted ratio is a per-trade Sharpe-like figure annualised by trade frequency — not computed from a daily return stream. Read with that limitation in mind.

## Rule definition

LONG when the 1-day return's z-score over 20 days is <= -2.0 and price is below SMA(20), unless the regime is strongly bearish. Target is a reversion to that SMA.

### Known failure modes

- catching a falling knife in a real downtrend
- gap-down through the stop after a news shock
- regime filter too permissive near a top

