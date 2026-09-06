# Backtest report — trend_continuation.short_swing v0.1.0

> **Hypothetical research output.** Simulated fills include modeled commission, spread and slippage. Past results do not predict future results. This strategy is **EXPERIMENTAL** (paper only, no alerts) until promoted.

- Generated: 2026-09-06T18:11:10+00:00
- git: `e94fe71`  ·  config hash: `3964441158a7f324ddf7b38dcea49a4c847cd9a493297eb3e6e3046f2db6f59b`
- Horizon: SHORT_SWING
- Window: 2023-08-28 → 2026-09-06
- Universe (25): AAPL, AMZN, DIA, GOOGL, HD, IWM, JPM, META, MSFT, NVDA, QQQ, SPY, UNH, XLB, XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, XLY, XOM
- Data: fixture/simulated unless a real provider was configured at run time

## In-sample vs out-of-sample

| Segment | Trades | Win rate | Avg win (R) | Avg loss (R) | Expectancy (R) | Profit factor | Max drawdown (R) | Risk-adj ratio* | Avg bars held | Worst losing streak | Total return (R) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| In-sample (first 60%) | 215 | 0.0% | +0.00 | -1.10 | -1.098 | 0.00 | 236.00 | -42.12 | 3.0 | 215 | -236.0 |
| Out-of-sample (last 40%) | 130 | 0.0% | +0.00 | -1.09 | -1.086 | 0.00 | 141.18 | -71.00 | 2.8 | 130 | -141.2 |

Out-of-sample bootstrap 95% CI:

- Expectancy (R): -1.113 … -1.064 (point -1.086)
- Profit factor: 0.00 … 0.00

## Out-of-sample by market regime (entry-date regime)

| Segment | Trades | Win rate | Avg win (R) | Avg loss (R) | Expectancy (R) | Profit factor | Max drawdown (R) | Risk-adj ratio* | Avg bars held | Worst losing streak | Total return (R) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| bull/low | 13 | 0.0% | +0.00 | -1.08 | -1.081 | 0.00 | 14.06 | -100.84 | 2.5 | 13 | -14.1 |
| neutral/high | 10 | 0.0% | +0.00 | -1.15 | -1.152 | 0.00 | 11.52 | -84.79 | 1.5 | 10 | -11.5 |
| neutral/low | 107 | 0.0% | +0.00 | -1.08 | -1.080 | 0.00 | 115.61 | -69.09 | 2.9 | 107 | -115.6 |

## Trades per symbol

| Symbol | Trades |
|---|---|
| AAPL | 13 |
| AMZN | 17 |
| DIA | 15 |
| GOOGL | 15 |
| HD | 7 |
| IWM | 14 |
| JPM | 16 |
| META | 15 |
| MSFT | 16 |
| NVDA | 10 |
| QQQ | 15 |
| SPY | 11 |
| UNH | 12 |
| XLB | 11 |
| XLC | 13 |
| XLE | 10 |
| XLF | 16 |
| XLI | 16 |
| XLK | 16 |
| XLP | 12 |
| XLRE | 11 |
| XLU | 16 |
| XLV | 17 |
| XLY | 16 |
| XOM | 15 |

\* Risk-adjusted ratio is a per-trade Sharpe-like figure annualised by trade frequency — not computed from a daily return stream. Read with that limitation in mind.

## Rule definition

LONG when close > SMA(slow), SMA(fast) > SMA(slow), close > SMA(fast), and today's volume >= 1.3x the 20-day average, with the market regime not risk-off. SHORT is the mirror image and only when shorts are enabled and the regime is risk-off.

### Known failure modes

- whipsaw in range-bound regimes
- volume spike on news that reverses
- gap through the stop

