# Backtest report — relative_strength.medium_swing v0.1.0

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
| In-sample (first 60%) | 33 | 66.7% | +1.79 | -1.00 | +0.859 | 3.57 | 2.07 | 1.87 | 23.8 | 2 | +28.3 |
| Out-of-sample (last 40%) | 72 | 44.4% | +1.41 | -0.92 | +0.114 | 1.22 | 16.56 | 0.31 | 19.6 | 9 | +8.2 |

Out-of-sample bootstrap 95% CI:

- Expectancy (R): -0.193 … +0.430 (point +0.114)
- Win rate: 33.3% … 55.6% (point 44.4%)
- Profit factor: 0.69 … 2.06

## Out-of-sample by market regime (entry-date regime)

| Segment | Trades | Win rate | Avg win (R) | Avg loss (R) | Expectancy (R) | Profit factor | Max drawdown (R) | Risk-adj ratio* | Avg bars held | Worst losing streak | Total return (R) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| bull/high | 23 | 47.8% | +1.07 | -0.99 | -0.004 | 0.99 | 5.07 | -0.01 | 22.7 | 4 | -0.1 |
| bull/low | 49 | 42.9% | +1.59 | -0.89 | +0.170 | 1.33 | 13.07 | 0.46 | 18.1 | 8 | +8.3 |

## Trades per symbol

| Symbol | Trades |
|---|---|
| AAPL | 7 |
| AMZN | 5 |
| DIA | 0 |
| GOOGL | 10 |
| HD | 3 |
| IWM | 5 |
| JPM | 4 |
| META | 4 |
| MSFT | 4 |
| NVDA | 7 |
| QQQ | 4 |
| SPY | 0 |
| UNH | 5 |
| XLB | 3 |
| XLC | 1 |
| XLE | 6 |
| XLF | 1 |
| XLI | 4 |
| XLK | 10 |
| XLP | 4 |
| XLRE | 2 |
| XLU | 3 |
| XLV | 5 |
| XLY | 0 |
| XOM | 8 |

\* Risk-adjusted ratio is a per-trade Sharpe-like figure annualised by trade frequency — not computed from a daily return stream. Read with that limitation in mind.

## Rule definition

LONG when the 63-session return exceeds the market proxy's return over the same window by at least 5%, price is above SMA(100), and the regime trend is BULL. Long only.

### Known failure modes

- momentum crash / sharp mean reversion of winners
- proxy-relative strength is not cross-sectional rank
- regime flips bull->bear mid-hold

