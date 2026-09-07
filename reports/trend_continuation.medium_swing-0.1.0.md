# Backtest report — trend_continuation.medium_swing v0.1.0

> **Hypothetical research output.** Simulated fills model spread and slippage; commission uses the configured `commission_per_share` (0 by default). Past results do not predict future results. This strategy is **EXPERIMENTAL** (paper only, no alerts) until promoted.

- Generated: 2026-09-07T07:35:06+00:00
- git: `79a5b05`  ·  config hash: `e96861ba16f3f717651b1e9a52115060328dd3b5d82dcd5c6834a0e622a6fa1c`
- Horizon: MEDIUM_SWING
- Window: 2024-08-28 → 2026-09-07
- Universe (25): AAPL, AMZN, DIA, GOOGL, HD, IWM, JPM, META, MSFT, NVDA, QQQ, SPY, UNH, XLB, XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, XLY, XOM
- Data: massive · real · 12500 bars · 2024-09-09..2026-09-04
- Costs: 0.0/sh commission (min 0.0/order) · 3.0 bps slippage · half-spread on

## In-sample vs out-of-sample

| Segment | Trades | Win rate | Avg win (R) | Avg loss (R) | Expectancy (R) | Profit factor | Max drawdown (R) | Risk-adj ratio* | Avg bars held | Worst losing streak | Total return (R) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| In-sample (first 60%) | 124 | 41.9% | +1.82 | -1.04 | +0.160 | 1.27 | 13.73 | 0.53 | 8.5 | 7 | +19.9 |
| Out-of-sample (last 40%) | 93 | 37.6% | +1.73 | -1.12 | -0.049 | 0.93 | 14.82 | -0.18 | 7.9 | 7 | -4.6 |

Out-of-sample bootstrap 95% CI:

- Expectancy (R): -0.363 … +0.274 (point -0.049)
- Win rate: 28.0% … 47.3% (point 37.6%)
- Profit factor: 0.56 … 1.49

## Out-of-sample by market regime (entry-date regime)

| Segment | Trades | Win rate | Avg win (R) | Avg loss (R) | Expectancy (R) | Profit factor | Max drawdown (R) | Risk-adj ratio* | Avg bars held | Worst losing streak | Total return (R) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| bull/high | 4 | 50.0% | +1.50 | -1.03 | +0.233 | 1.45 | 2.07 | 0.56 | 24.8 | 2 | +0.9 |
| bull/low | 89 | 37.1% | +1.74 | -1.12 | -0.062 | 0.91 | 12.75 | -0.23 | 7.2 | 7 | -5.5 |

## Trades per symbol

| Symbol | Trades |
|---|---|
| AAPL | 7 |
| AMZN | 7 |
| DIA | 13 |
| GOOGL | 14 |
| HD | 6 |
| IWM | 8 |
| JPM | 8 |
| META | 8 |
| MSFT | 8 |
| NVDA | 9 |
| QQQ | 7 |
| SPY | 7 |
| UNH | 6 |
| XLB | 7 |
| XLC | 11 |
| XLE | 7 |
| XLF | 7 |
| XLI | 10 |
| XLK | 12 |
| XLP | 7 |
| XLRE | 8 |
| XLU | 6 |
| XLV | 15 |
| XLY | 9 |
| XOM | 10 |

\* Risk-adjusted ratio is a per-trade Sharpe-like figure annualised by trade frequency — not computed from a daily return stream. Read with that limitation in mind.

## Rule definition

LONG when close > SMA(slow), SMA(fast) > SMA(slow), close > SMA(fast), and today's volume >= 1.3x the 20-day average, with the market regime not risk-off. SHORT is the mirror image and only when shorts are enabled and the regime is risk-off.

### Known failure modes

- whipsaw in range-bound regimes
- volume spike on news that reverses
- gap through the stop

