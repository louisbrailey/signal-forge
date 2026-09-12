# Grid backtest (b1) - top-1000 bulk universe, $5 cap, $5,000 cash

> **Hypothetical research output — not financial advice.** The grid is a mechanical rebalancing rule, not a researched edge: it has no promotion evidence, no walk-forward validation, and is not a registered strategy. Simulated fills only — no order was placed.

- Generated: 2026-09-12T03:50:40+00:00
- git: `f010889`
- Window: 2025-01-03 → 2026-09-08 (613 calendar days, 420 sessions)
- Data source: `massive_grouped`
- Universe: `top1000` (1000 requested) from `/Users/louisbrailey/signal-forge/data/grid_universe_top1000.json`
- Ranking: U.S.-listed common stocks only (incl. ADRs); ranked by 60-session median dollar volume; survivorship-biased (active names as of the screen date)
- Liquidity window: 2026-06-12 → 2026-09-08
- Symbols with bars: **1,000**; skipped for no/insufficient bars in the window: **0**
- Symbols that traded: **1,000**; symbols that reached the per-symbol cap: **1,000**

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
| Total return | +23.699% |
| CAGR | +13.510% |
| Max drawdown | 15.686% |
| Annualised vol | 13.391% |
| Sharpe (daily, rf=0) | 1.022 |
| Sortino (daily, rf=0) | 1.575 |
| Exposure (mean invested fraction) | 53.44% |
| Turnover / year | 6.497x |
| Trades | 11,597 (6,215 buys / 5,382 sells) |
| Trades / year | 6,910.0 |
| Start equity | $5,000.00 |
| End equity | $6,184.95 |
| Sessions | 420 |

## Benchmark

| Benchmark | Value |
|---|---|
| Benchmark | SPY buy-and-hold, same cash, same span, same cost model |
| Window | 2025-01-03 → 2026-09-08 |
| Total return | +30.298% |
| CAGR | +17.080% |
| Max drawdown | 18.999% |
| End equity | $6,514.89 |
| Grid − benchmark (total return) | -6.599 pp |

## Cash utilisation

| Cash utilisation | Value |
|---|---|
| Starting cash | $5,000.00 |
| Minimum cash held | $414.03 |
| Mean cash held | $2,570.88 |
| Final cash | $2,765.98 |
| Peak invested | $4,250.30 |
| Mean deployed fraction | 53.44% |
| Max deployed fraction | 91.12% |
| Budget if every symbol caps out | $5,000.00 |

## Per-symbol P&L distribution

| Per-symbol P&L | Value |
|---|---|
| Symbols that traded | 1,000 |
| Profitable symbols | 741 |
| Losing symbols | 259 |
| Total P&L (realised + unrealised) | $1,184.95 |
| Mean per symbol | $1.18 |
| p10 / p25 / median / p75 / p90 | $-1.21 / $-0.04 / $1.06 / $2.06 / $3.64 |
| Worst / best symbol | $-3.47 / $11.58 |

| Rank | Best symbol | P&L | Worst symbol | P&L |
|---|---|---|---|---|
| 1 | SLS | $11.58 | LULU | $-3.47 |
| 2 | BE | $10.74 | HUBS | $-3.40 |
| 3 | VSAT | $10.56 | WIX | $-3.38 |
| 4 | LITE | $10.06 | IT | $-3.33 |
| 5 | SEDG | $8.66 | RH | $-3.27 |
| 6 | AEHR | $8.34 | WHR | $-3.26 |
| 7 | OSCR | $8.32 | TTD | $-3.14 |
| 8 | PL | $8.28 | BLDR | $-3.09 |
| 9 | AXTI | $8.25 | STLA | $-2.90 |
| 10 | VICR | $8.20 | FRPT | $-2.71 |

## Skipped triggers

| Skipped trigger | Count |
|---|---|
| skip_no_position | 7,383 |
| skip_per_symbol_cap | 182,837 |

## Data limitations

- Daily bars are split/dividend adjusted AS OF THE FETCH DATE (not point-in-time). Dividends are embedded in the adjusted series, not paid as cash into the account.
- U.S.-listed symbols only. No non-U.S. exchanges are covered at all.
- The universe is ranked by *today's* liquidity, so it is survivorship-biased: names that delisted or collapsed before the screen date are absent, which flatters any buy-the-dip rule.
- Daily closes only — no intraday path, so a level breached and reversed inside a session is invisible to the rule.
- Exchange holidays and per-symbol listing dates are handled by simply using whatever sessions each symbol actually has; a symbol that lists mid-window starts tracking then.

## Notes

Configuration (b1): the internally consistent reading of the operator's spec - 1000 symbols x a $5 per-symbol cap = $5,000, exactly the starting cash. With cap == buy_usd every symbol is at its cap after a single buy, so the rule degenerates to 'hold at most one $5 lot per name'. Span is the full extent of the massive_grouped bulk archive, which starts 2025-01-03; this is NOT a 10-year test, and the universe is ranked by 2026 liquidity, so it is survivorship-biased over its own window. The committed JSON is the summary only - re-run with --trades-in-json for the full trade list and daily equity curve.
