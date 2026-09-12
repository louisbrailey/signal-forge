# Grid backtest — top1000 (cap $5, cash $5,000)

> **Hypothetical research output — not financial advice.** The grid is a mechanical rebalancing rule, not a researched edge: it has no promotion evidence, no walk-forward validation, and is not a registered strategy. Simulated fills only — no order was placed.

- Generated: 2026-09-12T08:42:25+00:00
- git: `025ad7e`
- Window: 2016-10-17 → 2026-09-11 (3,616 calendar days, 2,489 sessions)
- Data source: `massive`
- Universe: `top1000` (1000 requested) from `/Users/louisbrailey/signal-forge/data/grid_universe_top1000.json`
- Ranking: U.S.-listed common stocks only (incl. ADRs); ranked by 60-session median dollar volume; survivorship-biased (active names as of the screen date)
- Liquidity window: 2026-06-12 → 2026-09-08
- Symbols with bars: **999**; skipped for no/insufficient bars in the window: **1**
- Symbols that traded: **999**; symbols that reached the per-symbol cap: **999**

## Rules

Per symbol, on DAILY closes, exactly one evaluation per session:

1. Anchor starts at the close of the first tracked session (that session never trades).
2. `close <= anchor x (1 - 5.00%)` → BUY $5.00 (fractional shares), then anchor = that close.
3. `close >= anchor x (1 + 5.00%)` → SELL $10.00, capped at the position's market value, then anchor = that close.
4. Fills at the **next session's open** with slippage + half-spread against the trade.
5. The anchor moves when an order fills. A buy skipped for the cap, for cash, or for the minimum notional leaves the level armed. A rise past the sell level with nothing to sell re-anchors anyway, so the grid follows price (`reanchor_on_untradeable_rise`).
6. A sell that would leave a remainder worth less than the minimum notional sells the WHOLE position instead, so no unsellable stub can freeze a symbol.
7. No leverage, no shorting: cash never goes negative and a sell never exceeds holdings.

## Parameters

| Parameter | Value |
|---|---|
| starting_cash | $5,000.00 |
| per_symbol_cap | $5.00 |
| buy_usd | $5.00 |
| sell_usd | $10.00 |
| drop_pct | 5.00% |
| rise_pct | 5.00% |
| min_order_usd | $1.00 |
| re-anchor on a rise with nothing to sell | yes (the grid ratchets up with price) |
| universe_name | top1000 |
| universe_size | 1000 |
| costs | slippage 3 bps + half-spread (5 bps quoted), commission 0/share, min order $1 |
| budget if every symbol caps out | $5,000.00 |
| budget consistent with starting cash | yes |

## Headline metrics

| Metric | Value |
|---|---|
| Total return | +108.051% |
| CAGR | +7.681% |
| Max drawdown | 21.368% |
| Annualised vol | 8.847% |
| Sharpe (daily, rf=0) | 0.883 |
| Sortino (daily, rf=0) | 1.244 |
| Exposure (mean invested fraction) | 37.51% |
| Turnover / year | 2.543x |
| Trades | 36,198 (18,531 buys / 17,667 sells) |
| Trades / year | 3,656.3 |
| Start equity | $5,000.00 |
| End equity | $10,402.57 |
| Sessions | 2,489 |

## Benchmark

| Benchmark | Value |
|---|---|
| Benchmark | SPY buy-and-hold, same cash, same span, same cost model |
| Window | 2016-10-17 → 2026-09-11 |
| Total return | +258.473% |
| CAGR | +13.764% |
| Max drawdown | 34.105% |
| End equity | $17,923.64 |
| Grid − benchmark (total return) | -150.422 pp |

## Cash utilisation

| Cash utilisation | Value |
|---|---|
| Starting cash | $5,000.00 |
| Minimum cash held | $2,098.81 |
| Mean cash held | $4,677.38 |
| Final cash | $6,847.93 |
| Peak invested | $3,735.55 |
| Mean deployed fraction | 37.51% |
| Max deployed fraction | 62.18% |
| Budget if every symbol caps out | $5,000.00 |

## Per-symbol P&L distribution

| Per-symbol P&L | Value |
|---|---|
| Symbols that traded | 999 |
| Profitable symbols | 907 |
| Losing symbols | 92 |
| Total P&L (realised + unrealised) | $5,402.57 |
| Mean per symbol | $5.41 |
| p10 / p25 / median / p75 / p90 | $0.11 / $2.30 / $4.49 / $6.95 / $10.28 |
| Worst / best symbol | $-5.76 / $293.34 |

| Rank | Best symbol | P&L | Worst symbol | P&L |
|---|---|---|---|---|
| 1 | AXON | $293.34 | QXO | $-5.76 |
| 2 | RPRX | $172.92 | RIVN | $-4.41 |
| 3 | SNOW | $60.30 | PCG | $-3.98 |
| 4 | GEN | $23.64 | SLS | $-3.80 |
| 5 | S | $22.56 | PATH | $-3.57 |
| 6 | KRYS | $22.12 | LYFT | $-3.30 |
| 7 | RELY | $21.30 | KHC | $-3.28 |
| 8 | VAL | $21.00 | CPB | $-3.21 |
| 9 | AEHR | $20.18 | TAP | $-3.13 |
| 10 | FN | $19.11 | CCL | $-3.11 |

## Skipped triggers

| Skipped trigger | Count |
|---|---|
| skip_no_position | 22,611 |
| skip_per_symbol_cap | 1,247,046 |

## Data limitations

- Daily bars are split/dividend adjusted AS OF THE FETCH DATE (not point-in-time). Dividends are embedded in the adjusted series, not paid as cash into the account.
- U.S.-listed symbols only. No non-U.S. exchanges are covered at all.
- The universe is ranked by *today's* liquidity, so it is survivorship-biased: names that delisted or collapsed before the screen date are absent, which flatters any buy-the-dip rule.
- Daily closes only — no intraday path, so a level breached and reversed inside a session is invisible to the rule.
- Exchange holidays and per-symbol listing dates are handled by simply using whatever sessions each symbol actually has; a symbol that lists mid-window starts tracking then.
