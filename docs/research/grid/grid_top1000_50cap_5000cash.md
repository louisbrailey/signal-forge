# Grid backtest — top1000 (cap $50, cash $5,000)

> **Hypothetical research output — not financial advice.** The grid is a mechanical rebalancing rule, not a researched edge: it has no promotion evidence, no walk-forward validation, and is not a registered strategy. Simulated fills only — no order was placed.

- Generated: 2026-09-12T08:41:57+00:00
- git: `025ad7e`
- Window: 2016-10-17 → 2026-09-11 (3,616 calendar days, 2,489 sessions)
- Data source: `massive`
- Universe: `top1000` (1000 requested) from `/Users/louisbrailey/signal-forge/data/grid_universe_top1000.json`
- Ranking: U.S.-listed common stocks only (incl. ADRs); ranked by 60-session median dollar volume; survivorship-biased (active names as of the screen date)
- Liquidity window: 2026-06-12 → 2026-09-08
- Symbols with bars: **999**; skipped for no/insufficient bars in the window: **1**
- Symbols that traded: **999**; symbols that reached the per-symbol cap: **72**

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
| budget consistent with starting cash | **no** |

## Headline metrics

| Metric | Value |
|---|---|
| Total return | +355.250% |
| CAGR | +16.544% |
| Max drawdown | 40.899% |
| Annualised vol | 18.659% |
| Sharpe (daily, rf=0) | 0.916 |
| Sortino (daily, rf=0) | 1.372 |
| Exposure (mean invested fraction) | 47.78% |
| Turnover / year | 9.542x |
| Trades | 181,779 (109,944 buys / 71,835 sells) |
| Trades / year | 18,361.4 |
| Start equity | $5,000.00 |
| End equity | $22,762.51 |
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
| Grid − benchmark (total return) | +96.777 pp |

## Cash utilisation

| Cash utilisation | Value |
|---|---|
| Starting cash | $5,000.00 |
| Minimum cash held | $0.04 |
| Mean cash held | $6,062.02 |
| Final cash | $10,539.72 |
| Peak invested | $17,024.31 |
| Mean deployed fraction | 47.78% |
| Max deployed fraction | 100.00% |
| Budget if every symbol caps out | $50,000.00 |

## Per-symbol P&L distribution

| Per-symbol P&L | Value |
|---|---|
| Symbols that traded | 999 |
| Profitable symbols | 951 |
| Losing symbols | 48 |
| Total P&L (realised + unrealised) | $17,762.51 |
| Mean per symbol | $17.78 |
| p10 / p25 / median / p75 / p90 | $2.42 / $5.57 / $9.14 / $13.99 / $21.86 |
| Worst / best symbol | $-18.56 / $4,043.02 |

| Rank | Best symbol | P&L | Worst symbol | P&L |
|---|---|---|---|---|
| 1 | VAL | $4,043.02 | RIG | $-18.56 |
| 2 | SN | $1,641.39 | CNK | $-16.17 |
| 3 | GEN | $1,050.46 | OUST | $-15.82 |
| 4 | RELY | $185.11 | CCL | $-13.67 |
| 5 | SNOW | $68.97 | TXG | $-12.32 |
| 6 | MDGL | $68.96 | STLA | $-10.45 |
| 7 | AEHR | $67.94 | AGNC | $-9.14 |
| 8 | MARA | $66.66 | FLUT | $-8.99 |
| 9 | FRSH | $64.86 | RCL | $-8.56 |
| 10 | UEC | $61.39 | PRMB | $-8.39 |

## Skipped triggers

| Skipped trigger | Count |
|---|---|
| skip_at_fill | 15,980 |
| skip_insufficient_cash | 18,594 |
| skip_min_notional | 1 |
| skip_no_position | 60,915 |
| skip_per_symbol_cap | 6,305 |

## Data limitations

- Daily bars are split/dividend adjusted AS OF THE FETCH DATE (not point-in-time). Dividends are embedded in the adjusted series, not paid as cash into the account.
- U.S.-listed symbols only. No non-U.S. exchanges are covered at all.
- The universe is ranked by *today's* liquidity, so it is survivorship-biased: names that delisted or collapsed before the screen date are absent, which flatters any buy-the-dip rule.
- Daily closes only — no intraday path, so a level breached and reversed inside a session is invisible to the rule.
- Exchange holidays and per-symbol listing dates are handled by simply using whatever sessions each symbol actually has; a symbol that lists mid-window starts tracking then.
