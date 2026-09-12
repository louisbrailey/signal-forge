# Grid backtest — top1000 (cap $50, cash $50,000)

> **Hypothetical research output — not financial advice.** The grid is a mechanical rebalancing rule, not a researched edge: it has no promotion evidence, no walk-forward validation, and is not a registered strategy. Simulated fills only — no order was placed.

- Generated: 2026-09-12T08:42:51+00:00
- git: `025ad7e`
- Window: 2016-10-17 → 2026-09-11 (3,616 calendar days, 2,489 sessions)
- Data source: `massive`
- Universe: `top1000` (1000 requested) from `/Users/louisbrailey/signal-forge/data/grid_universe_top1000.json`
- Ranking: U.S.-listed common stocks only (incl. ADRs); ranked by 60-session median dollar volume; survivorship-biased (active names as of the screen date)
- Liquidity window: 2026-06-12 → 2026-09-08
- Symbols with bars: **999**; skipped for no/insufficient bars in the window: **1**
- Symbols that traded: **999**; symbols that reached the per-symbol cap: **86**

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
| starting_cash | $50,000.00 |
| per_symbol_cap | $50.00 |
| buy_usd | $5.00 |
| sell_usd | $10.00 |
| drop_pct | 5.00% |
| rise_pct | 5.00% |
| min_order_usd | $1.00 |
| re-anchor on a rise with nothing to sell | yes (the grid ratchets up with price) |
| universe_name | top1000 |
| universe_size | 1000 |
| costs | slippage 3 bps + half-spread (5 bps quoted), commission 0/share, min order $1 |
| budget if every symbol caps out | $50,000.00 |
| budget consistent with starting cash | yes |

## Headline metrics

| Metric | Value |
|---|---|
| Total return | +35.248% |
| CAGR | +3.097% |
| Max drawdown | 8.631% |
| Annualised vol | 3.837% |
| Sharpe (daily, rf=0) | 0.816 |
| Sortino (daily, rf=0) | 1.208 |
| Exposure (mean invested fraction) | 9.66% |
| Turnover / year | 2.128x |
| Trades | 195,570 (118,500 buys / 77,070 sells) |
| Trades / year | 19,754.4 |
| Start equity | $50,000.00 |
| End equity | $67,624.04 |
| Sessions | 2,489 |

## Benchmark

| Benchmark | Value |
|---|---|
| Benchmark | SPY buy-and-hold, same cash, same span, same cost model |
| Window | 2016-10-17 → 2026-09-11 |
| Total return | +258.473% |
| CAGR | +13.764% |
| Max drawdown | 34.105% |
| End equity | $179,236.44 |
| Grid − benchmark (total return) | -223.225 pp |

## Cash utilisation

| Cash utilisation | Value |
|---|---|
| Starting cash | $50,000.00 |
| Minimum cash held | $37,041.09 |
| Mean cash held | $50,817.42 |
| Final cash | $55,164.06 |
| Peak invested | $17,118.59 |
| Mean deployed fraction | 9.66% |
| Max deployed fraction | 27.54% |
| Budget if every symbol caps out | $50,000.00 |

## Per-symbol P&L distribution

| Per-symbol P&L | Value |
|---|---|
| Symbols that traded | 999 |
| Profitable symbols | 928 |
| Losing symbols | 71 |
| Total P&L (realised + unrealised) | $17,624.04 |
| Mean per symbol | $17.64 |
| p10 / p25 / median / p75 / p90 | $1.35 / $5.06 / $8.48 / $13.48 / $22.22 |
| Worst / best symbol | $-14.97 / $4,272.92 |

| Rank | Best symbol | P&L | Worst symbol | P&L |
|---|---|---|---|---|
| 1 | VAL | $4,272.92 | OUST | $-14.97 |
| 2 | SN | $1,647.91 | TXG | $-13.59 |
| 3 | GEN | $1,059.40 | HAL | $-12.52 |
| 4 | RELY | $185.11 | CCL | $-12.45 |
| 5 | CORZ | $87.74 | RIG | $-11.31 |
| 6 | MDGL | $70.92 | AGNC | $-10.30 |
| 7 | AEHR | $70.76 | STLA | $-10.12 |
| 8 | SNOW | $68.97 | NCLH | $-9.85 |
| 9 | FRSH | $64.01 | FLUT | $-8.99 |
| 10 | UEC | $58.53 | SNAP | $-8.77 |

## Skipped triggers

| Skipped trigger | Count |
|---|---|
| skip_at_fill | 3 |
| skip_min_notional | 1 |
| skip_no_position | 63,854 |
| skip_per_symbol_cap | 6,530 |

## Data limitations

- Daily bars are split/dividend adjusted AS OF THE FETCH DATE (not point-in-time). Dividends are embedded in the adjusted series, not paid as cash into the account.
- U.S.-listed symbols only. No non-U.S. exchanges are covered at all.
- The universe is ranked by *today's* liquidity, so it is survivorship-biased: names that delisted or collapsed before the screen date are absent, which flatters any buy-the-dip rule.
- Daily closes only — no intraday path, so a level breached and reversed inside a session is invisible to the rule.
- Exchange holidays and per-symbol listing dates are handled by simply using whatever sessions each symbol actually has; a symbol that lists mid-window starts tracking then.
