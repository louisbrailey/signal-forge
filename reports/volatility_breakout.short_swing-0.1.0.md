# Backtest report — volatility_breakout.short_swing v0.1.0

> **Hypothetical research output.** Simulated fills include modeled commission, spread and slippage. Past results do not predict future results. This strategy is **EXPERIMENTAL** (paper only, no alerts) until promoted.

- Generated: 2026-09-07T02:00:07+00:00
- git: `e77e3d1`  ·  config hash: `5e703f163d28f0f6bef63551e2e2d3d2fa8c750a7717198b38c376c7874656ae`
- Horizon: SHORT_SWING
- Window: 2024-08-27 → 2026-09-06
- Universe (25): AAPL, AMZN, DIA, GOOGL, HD, IWM, JPM, META, MSFT, NVDA, QQQ, SPY, UNH, XLB, XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, XLY, XOM
- Data: fixture/simulated unless a real provider was configured at run time

## In-sample vs out-of-sample

| Segment | Trades | Win rate | Avg win (R) | Avg loss (R) | Expectancy (R) | Profit factor | Max drawdown (R) | Risk-adj ratio* | Avg bars held | Worst losing streak | Total return (R) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| In-sample (first 60%) | 1 | 100.0% | +1.11 | +0.00 | +1.108 | inf | 0.00 | 0.00 | 4.0 | 0 | +1.1 |
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
| JPM | 0 |
| META | 0 |
| MSFT | 0 |
| NVDA | 0 |
| QQQ | 0 |
| SPY | 1 |
| UNH | 0 |
| XLB | 0 |
| XLC | 0 |
| XLE | 0 |
| XLF | 0 |
| XLI | 0 |
| XLK | 0 |
| XLP | 0 |
| XLRE | 0 |
| XLU | 0 |
| XLV | 0 |
| XLY | 0 |
| XOM | 0 |

\* Risk-adjusted ratio is a per-trade Sharpe-like figure annualised by trade frequency — not computed from a daily return stream. Read with that limitation in mind.

## Rule definition

When ATR(10)/ATR(50) <= 0.75 (volatility contracting) and price closes above the 20-day Donchian high, go LONG (SHORT on a break of the Donchian low when shorts are enabled and the regime is BEAR). ATR stop and target.

### Known failure modes

- false breakout / immediate reversal back into the range
- contraction filter admits low-volume drift that fails to follow through
- gap through the stop

