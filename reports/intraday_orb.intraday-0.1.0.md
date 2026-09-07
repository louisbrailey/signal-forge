# Backtest report — intraday_orb.intraday v0.1.0

> **Hypothetical research output.** Simulated fills include modeled commission, spread and slippage. Past results do not predict future results. This strategy is **EXPERIMENTAL** (paper only, no alerts) until promoted.

- Generated: 2026-09-07T02:00:05+00:00
- git: `e77e3d1`  ·  config hash: `5e703f163d28f0f6bef63551e2e2d3d2fa8c750a7717198b38c376c7874656ae`
- Horizon: INTRADAY
- Window: 2026-07-23 → 2026-09-06
- Universe (25): AAPL, AMZN, DIA, GOOGL, HD, IWM, JPM, META, MSFT, NVDA, QQQ, SPY, UNH, XLB, XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, XLY, XOM
- Data: fixture/simulated unless a real provider was configured at run time

## In-sample vs out-of-sample

| Segment | Trades | Win rate | Avg win (R) | Avg loss (R) | Expectancy (R) | Profit factor | Max drawdown (R) | Risk-adj ratio* | Avg bars held | Worst losing streak | Total return (R) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| In-sample (first 60%) | 139 | 37.4% | +0.69 | -0.78 | -0.232 | 0.53 | 34.08 | -1.39 | 9.6 | 7 | -32.3 |
| Out-of-sample (last 40%) | 104 | 45.2% | +0.74 | -0.79 | -0.098 | 0.77 | 15.51 | -0.59 | 8.9 | 6 | -10.2 |

Out-of-sample bootstrap 95% CI:

- Expectancy (R): -0.273 … +0.072 (point -0.098)
- Profit factor: 0.48 … 1.21

## Out-of-sample by market regime (entry-date regime)

| Segment | Trades | Win rate | Avg win (R) | Avg loss (R) | Expectancy (R) | Profit factor | Max drawdown (R) | Risk-adj ratio* | Avg bars held | Worst losing streak | Total return (R) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| neutral/low | 104 | 45.2% | +0.74 | -0.79 | -0.098 | 0.77 | 15.51 | -0.59 | 8.9 | 6 | -10.2 |

## Trades per symbol

| Symbol | Trades |
|---|---|
| AAPL | 12 |
| AMZN | 12 |
| DIA | 11 |
| GOOGL | 11 |
| HD | 9 |
| IWM | 7 |
| JPM | 12 |
| META | 11 |
| MSFT | 10 |
| NVDA | 12 |
| QQQ | 9 |
| SPY | 8 |
| UNH | 9 |
| XLB | 11 |
| XLC | 10 |
| XLE | 7 |
| XLF | 10 |
| XLI | 9 |
| XLK | 11 |
| XLP | 9 |
| XLRE | 7 |
| XLU | 9 |
| XLV | 7 |
| XLY | 9 |
| XOM | 11 |

\* Risk-adjusted ratio is a per-trade Sharpe-like figure annualised by trade frequency — not computed from a daily return stream. Read with that limitation in mind.

## Rule definition

After the first 3 RTH bars set the opening range (OR). LONG when a bar closes above OR high (SHORT below OR low, if enabled) between bar 3 and 20 of the session, and the daily regime is not risk-off. Stop at the opposite OR edge; target 1.5x the OR width; time stop 12 bars.

### Known failure modes

- chop around the OR edge on a rangebound day
- gap-and-fade after the open
- thin liquidity in the first bars widening the effective spread

