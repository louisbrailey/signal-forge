# Backtest report — trend_continuation.short_swing v0.1.0

> **Hypothetical research output.** Simulated fills include modeled commission, spread and slippage. Past results do not predict future results. This strategy is **EXPERIMENTAL** (paper only, no alerts) until promoted.

- Generated: 2026-09-06T18:19:49+00:00
- git: `7f694d8`  ·  config hash: `fbe97fcb3031b439ccfbb5c6a8447e53bcfc1628c5755216382a92b70383f428`
- Horizon: SHORT_SWING
- Window: 2022-08-28 → 2026-09-06
- Universe (25): AAPL, AMZN, DIA, GOOGL, HD, IWM, JPM, META, MSFT, NVDA, QQQ, SPY, UNH, XLB, XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, XLY, XOM
- Data: fixture/simulated unless a real provider was configured at run time

## In-sample vs out-of-sample

| Segment | Trades | Win rate | Avg win (R) | Avg loss (R) | Expectancy (R) | Profit factor | Max drawdown (R) | Risk-adj ratio* | Avg bars held | Worst losing streak | Total return (R) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| In-sample (first 60%) | 279 | 0.0% | +0.00 | -1.10 | -1.099 | 0.00 | 306.74 | -44.83 | 3.0 | 279 | -306.7 |
| Out-of-sample (last 40%) | 168 | 0.0% | +0.00 | -1.08 | -1.084 | 0.00 | 182.07 | -71.87 | 2.8 | 168 | -182.1 |

Out-of-sample bootstrap 95% CI:

- Expectancy (R): -1.105 … -1.064 (point -1.084)
- Profit factor: 0.00 … 0.00

## Out-of-sample by market regime (entry-date regime)

| Segment | Trades | Win rate | Avg win (R) | Avg loss (R) | Expectancy (R) | Profit factor | Max drawdown (R) | Risk-adj ratio* | Avg bars held | Worst losing streak | Total return (R) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| bull/high | 4 | 0.0% | +0.00 | -1.13 | -1.133 | 0.00 | 4.53 | -103.92 | 2.2 | 4 | -4.5 |
| bull/low | 43 | 0.0% | +0.00 | -1.06 | -1.058 | 0.00 | 45.48 | -104.10 | 3.0 | 43 | -45.5 |
| neutral/high | 10 | 0.0% | +0.00 | -1.15 | -1.152 | 0.00 | 11.52 | -84.79 | 1.5 | 10 | -11.5 |
| neutral/low | 111 | 0.0% | +0.00 | -1.09 | -1.086 | 0.00 | 120.54 | -66.38 | 2.9 | 111 | -120.5 |

## Trades per symbol

| Symbol | Trades |
|---|---|
| AAPL | 19 |
| AMZN | 21 |
| DIA | 21 |
| GOOGL | 19 |
| HD | 10 |
| IWM | 19 |
| JPM | 20 |
| META | 19 |
| MSFT | 18 |
| NVDA | 14 |
| QQQ | 16 |
| SPY | 15 |
| UNH | 16 |
| XLB | 15 |
| XLC | 17 |
| XLE | 13 |
| XLF | 21 |
| XLI | 20 |
| XLK | 22 |
| XLP | 17 |
| XLRE | 16 |
| XLU | 20 |
| XLV | 20 |
| XLY | 20 |
| XOM | 19 |

\* Risk-adjusted ratio is a per-trade Sharpe-like figure annualised by trade frequency — not computed from a daily return stream. Read with that limitation in mind.

## Rule definition

LONG when close > SMA(slow), SMA(fast) > SMA(slow), close > SMA(fast), and today's volume >= 1.3x the 20-day average, with the market regime not risk-off. SHORT is the mirror image and only when shorts are enabled and the regime is risk-off.

### Known failure modes

- whipsaw in range-bound regimes
- volume spike on news that reverses
- gap through the stop

