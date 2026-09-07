# Backtest report — mean_reversion.short_swing v0.1.0

> **Hypothetical research output.** Simulated fills model spread and slippage; commission uses the configured `commission_per_share` (0 by default). Past results do not predict future results. This strategy is **EXPERIMENTAL** (paper only, no alerts) until promoted.

- Generated: 2026-09-07T07:12:11+00:00
- git: `dd1aff6`  ·  config hash: `010b908750b2d42af161468dee1fcb449a7874954d2cf6e9d7e43ac0e0a6ad47`
- Horizon: SHORT_SWING
- Window: 2024-08-28 → 2026-09-07
- Universe (25): AAPL, AMZN, DIA, GOOGL, HD, IWM, JPM, META, MSFT, NVDA, QQQ, SPY, UNH, XLB, XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, XLY, XOM
- Data: massive · real · 12500 bars · 2024-09-09..2026-09-04
- Costs: 0.0/sh commission (min 0.0/order) · 3.0 bps slippage · half-spread on

## In-sample vs out-of-sample

| Segment | Trades | Win rate | Avg win (R) | Avg loss (R) | Expectancy (R) | Profit factor | Max drawdown (R) | Risk-adj ratio* | Avg bars held | Worst losing streak | Total return (R) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| In-sample (first 60%) | 161 | 47.8% | +0.45 | -0.80 | -0.198 | 0.52 | 33.36 | -2.41 | 2.9 | 6 | -31.8 |
| Out-of-sample (last 40%) | 82 | 67.1% | +0.63 | -0.70 | +0.192 | 1.83 | 2.04 | 2.22 | 3.3 | 2 | +15.7 |

Out-of-sample bootstrap 95% CI:

- Expectancy (R): +0.021 … +0.352 (point +0.192)
- Win rate: 56.1% … 76.8% (point 67.1%)
- Profit factor: 1.07 … 3.18

## Out-of-sample by market regime (entry-date regime)

| Segment | Trades | Win rate | Avg win (R) | Avg loss (R) | Expectancy (R) | Profit factor | Max drawdown (R) | Risk-adj ratio* | Avg bars held | Worst losing streak | Total return (R) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| bull/high | 16 | 81.2% | +0.63 | -1.01 | +0.322 | 2.70 | 2.03 | 3.48 | 3.6 | 2 | +5.2 |
| bull/low | 66 | 63.6% | +0.63 | -0.66 | +0.160 | 1.67 | 2.04 | 1.89 | 3.3 | 3 | +10.6 |

## Trades per symbol

| Symbol | Trades |
|---|---|
| AAPL | 13 |
| AMZN | 9 |
| DIA | 8 |
| GOOGL | 9 |
| HD | 7 |
| IWM | 7 |
| JPM | 10 |
| META | 14 |
| MSFT | 8 |
| NVDA | 9 |
| QQQ | 10 |
| SPY | 11 |
| UNH | 10 |
| XLB | 9 |
| XLC | 11 |
| XLE | 9 |
| XLF | 14 |
| XLI | 8 |
| XLK | 11 |
| XLP | 9 |
| XLRE | 12 |
| XLU | 12 |
| XLV | 5 |
| XLY | 9 |
| XOM | 9 |

\* Risk-adjusted ratio is a per-trade Sharpe-like figure annualised by trade frequency — not computed from a daily return stream. Read with that limitation in mind.

## Rule definition

LONG when the 1-day return's z-score over 20 days is <= -2.0 and price is below SMA(20), unless the regime is strongly bearish. Target is a reversion to that SMA.

### Known failure modes

- catching a falling knife in a real downtrend
- gap-down through the stop after a news shock
- regime filter too permissive near a top

