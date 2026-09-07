# Backtest report — volatility_breakout.short_swing v0.1.0

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
| In-sample (first 60%) | 30 | 36.7% | +0.79 | -0.95 | -0.311 | 0.48 | 12.97 | -1.88 | 6.6 | 4 | -9.3 |
| Out-of-sample (last 40%) | 10 | 30.0% | +1.50 | -0.84 | -0.141 | 0.76 | 4.23 | -0.72 | 6.3 | 4 | -1.4 |

Out-of-sample bootstrap 95% CI:

- Expectancy (R): -0.858 … +0.701 (point -0.141)
- Win rate: 0.0% … 60.0% (point 30.0%)
- Profit factor: 0.00 … 3.21

## Out-of-sample by market regime (entry-date regime)

| Segment | Trades | Win rate | Avg win (R) | Avg loss (R) | Expectancy (R) | Profit factor | Max drawdown (R) | Risk-adj ratio* | Avg bars held | Worst losing streak | Total return (R) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| bull/low | 10 | 30.0% | +1.50 | -0.84 | -0.141 | 0.76 | 4.23 | -0.72 | 6.3 | 4 | -1.4 |

## Trades per symbol

| Symbol | Trades |
|---|---|
| AAPL | 0 |
| AMZN | 1 |
| DIA | 2 |
| GOOGL | 1 |
| HD | 0 |
| IWM | 3 |
| JPM | 1 |
| META | 1 |
| MSFT | 2 |
| NVDA | 1 |
| QQQ | 3 |
| SPY | 8 |
| UNH | 1 |
| XLB | 1 |
| XLC | 3 |
| XLE | 1 |
| XLF | 0 |
| XLI | 3 |
| XLK | 2 |
| XLP | 0 |
| XLRE | 1 |
| XLU | 0 |
| XLV | 1 |
| XLY | 3 |
| XOM | 1 |

\* Risk-adjusted ratio is a per-trade Sharpe-like figure annualised by trade frequency — not computed from a daily return stream. Read with that limitation in mind.

## Rule definition

When ATR(10)/ATR(50) <= 0.75 (volatility contracting) and price closes above the 20-day Donchian high, go LONG (SHORT on a break of the Donchian low when shorts are enabled and the regime is BEAR). ATR stop and target.

### Known failure modes

- false breakout / immediate reversal back into the range
- contraction filter admits low-volume drift that fails to follow through
- gap through the stop

