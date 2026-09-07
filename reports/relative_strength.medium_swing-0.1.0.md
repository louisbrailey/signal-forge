# Backtest report — relative_strength.medium_swing v0.1.0

> **Hypothetical research output.** Simulated fills include modeled commission, spread and slippage. Past results do not predict future results. This strategy is **EXPERIMENTAL** (paper only, no alerts) until promoted.

- Generated: 2026-09-07T02:00:07+00:00
- git: `e77e3d1`  ·  config hash: `5e703f163d28f0f6bef63551e2e2d3d2fa8c750a7717198b38c376c7874656ae`
- Horizon: MEDIUM_SWING
- Window: 2024-08-27 → 2026-09-06
- Universe (25): AAPL, AMZN, DIA, GOOGL, HD, IWM, JPM, META, MSFT, NVDA, QQQ, SPY, UNH, XLB, XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, XLY, XOM
- Data: fixture/simulated unless a real provider was configured at run time

## In-sample vs out-of-sample

| Segment | Trades | Win rate | Avg win (R) | Avg loss (R) | Expectancy (R) | Profit factor | Max drawdown (R) | Risk-adj ratio* | Avg bars held | Worst losing streak | Total return (R) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| In-sample (first 60%) | 4 | 0.0% | +0.00 | -1.07 | -1.069 | 0.00 | 4.27 | -69.08 | 9.8 | 4 | -4.3 |
| Out-of-sample (last 40%) | 0 | 0.0% | +0.00 | +0.00 | +0.000 | 0.00 | 0.00 | 0.00 | 0.0 | 0 | +0.0 |

Out-of-sample bootstrap 95% CI:

- Expectancy (R): +0.000 … +0.000 (point +0.000)
- Profit factor: 0.00 … 0.00

## Out-of-sample by market regime (entry-date regime)

| Segment | Trades | Win rate | Avg win (R) | Avg loss (R) | Expectancy (R) | Profit factor | Max drawdown (R) | Risk-adj ratio* | Avg bars held | Worst losing streak | Total return (R) |
|---|---|---|---|---|---|---|---|---|---|---|---|

## Trades per symbol

| Symbol | Trades |
|---|---|
| AAPL | 0 |
| AMZN | 0 |
| DIA | 0 |
| GOOGL | 0 |
| HD | 0 |
| IWM | 0 |
| JPM | 1 |
| META | 0 |
| MSFT | 0 |
| NVDA | 1 |
| QQQ | 0 |
| SPY | 0 |
| UNH | 0 |
| XLB | 0 |
| XLC | 0 |
| XLE | 0 |
| XLF | 1 |
| XLI | 1 |
| XLK | 0 |
| XLP | 0 |
| XLRE | 0 |
| XLU | 0 |
| XLV | 0 |
| XLY | 0 |
| XOM | 0 |

\* Risk-adjusted ratio is a per-trade Sharpe-like figure annualised by trade frequency — not computed from a daily return stream. Read with that limitation in mind.

## Rule definition

LONG when the 63-session return exceeds the market proxy's return over the same window by at least 5%, price is above SMA(100), and the regime trend is BULL. Long only.

### Known failure modes

- momentum crash / sharp mean reversion of winners
- proxy-relative strength is not cross-sectional rank
- regime flips bull->bear mid-hold

