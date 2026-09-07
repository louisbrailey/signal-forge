# Backtest report — intraday_orb.intraday v0.1.0

> **Hypothetical research output.** Simulated fills model spread and slippage; commission uses the configured `commission_per_share` (0 by default). Past results do not predict future results. This strategy is **EXPERIMENTAL** (paper only, no alerts) until promoted.

- Generated: 2026-09-07T07:12:10+00:00
- git: `dd1aff6`  ·  config hash: `010b908750b2d42af161468dee1fcb449a7874954d2cf6e9d7e43ac0e0a6ad47`
- Horizon: INTRADAY
- Window: 2026-07-24 → 2026-09-07
- Universe (25): AAPL, AMZN, DIA, GOOGL, HD, IWM, JPM, META, MSFT, NVDA, QQQ, SPY, UNH, XLB, XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, XLY, XOM
- Data: none · real · 0 bars · no bars
- Costs: 0.0/sh commission (min 0.0/order) · 3.0 bps slippage · half-spread on

## In-sample vs out-of-sample

| Segment | Trades | Win rate | Avg win (R) | Avg loss (R) | Expectancy (R) | Profit factor | Max drawdown (R) | Risk-adj ratio* | Avg bars held | Worst losing streak | Total return (R) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| In-sample (first 60%) | 0 | 0.0% | +0.00 | +0.00 | +0.000 | 0.00 | 0.00 | 0.00 | 0.0 | 0 | +0.0 |
| Out-of-sample (last 40%) | 0 | 0.0% | +0.00 | +0.00 | +0.000 | 0.00 | 0.00 | 0.00 | 0.0 | 0 | +0.0 |

Out-of-sample bootstrap 95% CI:

- Expectancy (R): +0.000 … +0.000 (point +0.000)
- Win rate: 0.0% … 0.0% (point 0.0%)
- Profit factor: 0.00 … 0.00

## Out-of-sample by market regime (entry-date regime)

| Segment | Trades | Win rate | Avg win (R) | Avg loss (R) | Expectancy (R) | Profit factor | Max drawdown (R) | Risk-adj ratio* | Avg bars held | Worst losing streak | Total return (R) |
|---|---|---|---|---|---|---|---|---|---|---|---|

## Trades per symbol

| Symbol | Trades |
|---|---|

\* Risk-adjusted ratio is a per-trade Sharpe-like figure annualised by trade frequency — not computed from a daily return stream. Read with that limitation in mind.

## Rule definition

After the first 3 RTH bars set the opening range (OR). LONG when a bar closes above OR high (SHORT below OR low, if enabled) between bar 3 and 20 of the session, and the daily regime is not risk-off. Stop at the opposite OR edge; target 1.5x the OR width; time stop 12 bars.

### Known failure modes

- chop around the OR edge on a rangebound day
- gap-and-fade after the open
- thin liquidity in the first bars widening the effective spread

