# Backtest report — mean_reversion.short_swing v0.1.0

> **Hypothetical research output.** Simulated fills include modeled commission, spread and slippage. Past results do not predict future results. This strategy is **EXPERIMENTAL** (paper only, no alerts) until promoted.

- Generated: 2026-09-06T18:19:50+00:00
- git: `7f694d8`  ·  config hash: `fbe97fcb3031b439ccfbb5c6a8447e53bcfc1628c5755216382a92b70383f428`
- Horizon: SHORT_SWING
- Window: 2022-08-28 → 2026-09-06
- Universe (25): AAPL, AMZN, DIA, GOOGL, HD, IWM, JPM, META, MSFT, NVDA, QQQ, SPY, UNH, XLB, XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, XLY, XOM
- Data: fixture/simulated unless a real provider was configured at run time

## In-sample vs out-of-sample

| Segment | Trades | Win rate | Avg win (R) | Avg loss (R) | Expectancy (R) | Profit factor | Max drawdown (R) | Risk-adj ratio* | Avg bars held | Worst losing streak | Total return (R) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| In-sample (first 60%) | 200 | 8.0% | +0.14 | -1.07 | -0.974 | 0.01 | 194.82 | -26.59 | 2.5 | 35 | -194.8 |
| Out-of-sample (last 40%) | 117 | 4.3% | +0.18 | -1.04 | -0.990 | 0.01 | 115.80 | -33.16 | 2.5 | 33 | -115.8 |

Out-of-sample bootstrap 95% CI:

- Expectancy (R): -1.039 … -0.932 (point -0.990)
- Profit factor: 0.00 … 0.02

## Out-of-sample by market regime (entry-date regime)

| Segment | Trades | Win rate | Avg win (R) | Avg loss (R) | Expectancy (R) | Profit factor | Max drawdown (R) | Risk-adj ratio* | Avg bars held | Worst losing streak | Total return (R) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| bear/low | 2 | 0.0% | +0.00 | -1.01 | -1.007 | 0.00 | 2.01 | -31784.91 | 3.0 | 2 | -2.0 |
| neutral/high | 79 | 6.3% | +0.18 | -1.04 | -0.959 | 0.01 | 75.78 | -28.46 | 2.4 | 24 | -75.8 |
| neutral/low | 36 | 0.0% | +0.00 | -1.06 | -1.056 | 0.00 | 38.01 | -76.01 | 2.8 | 36 | -38.0 |

## Trades per symbol

| Symbol | Trades |
|---|---|
| AAPL | 10 |
| AMZN | 10 |
| DIA | 12 |
| GOOGL | 12 |
| HD | 16 |
| IWM | 14 |
| JPM | 7 |
| META | 14 |
| MSFT | 16 |
| NVDA | 13 |
| QQQ | 9 |
| SPY | 17 |
| UNH | 15 |
| XLB | 8 |
| XLC | 11 |
| XLE | 14 |
| XLF | 10 |
| XLI | 15 |
| XLK | 8 |
| XLP | 14 |
| XLRE | 17 |
| XLU | 12 |
| XLV | 16 |
| XLY | 15 |
| XOM | 12 |

\* Risk-adjusted ratio is a per-trade Sharpe-like figure annualised by trade frequency — not computed from a daily return stream. Read with that limitation in mind.

## Rule definition

LONG when the 1-day return's z-score over 20 days is <= -2.0 and price is below SMA(20), unless the regime is strongly bearish. Target is a reversion to that SMA.

### Known failure modes

- catching a falling knife in a real downtrend
- gap-down through the stop after a news shock
- regime filter too permissive near a top

