# Backtest report — trend_continuation.short_swing v0.1.0

> **Hypothetical research output.** Simulated fills model spread and slippage; commission uses the configured `commission_per_share` (0 by default). Past results do not predict future results. This strategy is **EXPERIMENTAL** (paper only, no alerts) until promoted.

- Generated: 2026-09-07T07:12:10+00:00
- git: `dd1aff6`  ·  config hash: `010b908750b2d42af161468dee1fcb449a7874954d2cf6e9d7e43ac0e0a6ad47`
- Horizon: SHORT_SWING
- Window: 2024-08-28 → 2026-09-07
- Universe (25): AAPL, AMZN, DIA, GOOGL, HD, IWM, JPM, META, MSFT, NVDA, QQQ, SPY, UNH, XLB, XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, XLY, XOM
- Data: massive · real · 12500 bars · 2024-09-09..2026-09-04
- Costs: 0.0/sh commission (min 0.0/order) · 3.0 bps slippage · half-spread on

## In-sample vs out-of-sample

| Segment | Trades | Win rate | Avg win (R) | Avg loss (R) | Expectancy (R) | Profit factor | Max drawdown (R) | Risk-adj ratio* | Avg bars held | Worst losing streak | Total return (R) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| In-sample (first 60%) | 134 | 49.3% | +1.26 | -0.90 | +0.163 | 1.36 | 6.81 | 0.83 | 6.0 | 5 | +21.8 |
| Out-of-sample (last 40%) | 105 | 42.9% | +1.84 | -0.91 | +0.269 | 1.52 | 13.93 | 1.00 | 4.9 | 7 | +28.2 |

Out-of-sample bootstrap 95% CI:

- Expectancy (R): -0.086 … +0.651 (point +0.269)
- Win rate: 33.3% … 52.4% (point 42.9%)
- Profit factor: 0.86 … 2.47

## Out-of-sample by market regime (entry-date regime)

| Segment | Trades | Win rate | Avg win (R) | Avg loss (R) | Expectancy (R) | Profit factor | Max drawdown (R) | Risk-adj ratio* | Avg bars held | Worst losing streak | Total return (R) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| bull/high | 4 | 75.0% | +0.65 | -0.31 | +0.413 | 6.31 | 0.31 | 2.83 | 10.0 | 1 | +1.7 |
| bull/low | 101 | 41.6% | +1.92 | -0.92 | +0.263 | 1.49 | 13.95 | 0.98 | 4.7 | 6 | +26.6 |

## Trades per symbol

| Symbol | Trades |
|---|---|
| AAPL | 7 |
| AMZN | 8 |
| DIA | 16 |
| GOOGL | 17 |
| HD | 6 |
| IWM | 9 |
| JPM | 8 |
| META | 8 |
| MSFT | 8 |
| NVDA | 10 |
| QQQ | 7 |
| SPY | 7 |
| UNH | 7 |
| XLB | 9 |
| XLC | 11 |
| XLE | 10 |
| XLF | 9 |
| XLI | 11 |
| XLK | 12 |
| XLP | 7 |
| XLRE | 9 |
| XLU | 6 |
| XLV | 15 |
| XLY | 10 |
| XOM | 12 |

\* Risk-adjusted ratio is a per-trade Sharpe-like figure annualised by trade frequency — not computed from a daily return stream. Read with that limitation in mind.

## Rule definition

LONG when close > SMA(slow), SMA(fast) > SMA(slow), close > SMA(fast), and today's volume >= 1.3x the 20-day average, with the market regime not risk-off. SHORT is the mirror image and only when shorts are enabled and the regime is risk-off.

### Known failure modes

- whipsaw in range-bound regimes
- volume spike on news that reverses
- gap through the stop

