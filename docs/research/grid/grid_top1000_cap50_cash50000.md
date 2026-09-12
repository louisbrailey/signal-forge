# Grid backtest (b2) - top-1000 bulk universe, $50 cap, $50,000 cash

> **Hypothetical research output — not financial advice.** The grid is a mechanical rebalancing rule, not a researched edge: it has no promotion evidence, no walk-forward validation, and is not a registered strategy. Simulated fills only — no order was placed.

- Generated: 2026-09-12T03:50:51+00:00
- git: `f010889`
- Window: 2025-01-03 → 2026-09-08 (613 calendar days, 420 sessions)
- Data source: `massive_grouped`
- Universe: `top1000` (1000 requested) from `/Users/louisbrailey/signal-forge/data/grid_universe_top1000.json`
- Ranking: U.S.-listed common stocks only (incl. ADRs); ranked by 60-session median dollar volume; survivorship-biased (active names as of the screen date)
- Liquidity window: 2026-06-12 → 2026-09-08
- Symbols with bars: **1,000**; skipped for no/insufficient bars in the window: **0**
- Symbols that traded: **1,000**; symbols that reached the per-symbol cap: **15**

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
| Total return | +4.732% |
| CAGR | +2.793% |
| Max drawdown | 2.493% |
| Annualised vol | 3.216% |
| Sharpe (daily, rf=0) | 0.881 |
| Sortino (daily, rf=0) | 1.551 |
| Exposure (mean invested fraction) | 7.79% |
| Turnover / year | 2.889x |
| Trades | 40,860 (24,968 buys / 15,892 sells) |
| Trades / year | 24,346.0 |
| Start equity | $50,000.00 |
| End equity | $52,365.99 |
| Sessions | 420 |

## Benchmark

| Benchmark | Value |
|---|---|
| Benchmark | SPY buy-and-hold, same cash, same span, same cost model |
| Window | 2025-01-03 → 2026-09-08 |
| Total return | +30.298% |
| CAGR | +17.080% |
| Max drawdown | 18.999% |
| End equity | $65,148.92 |
| Grid − benchmark (total return) | -25.566 pp |

## Cash utilisation

| Cash utilisation | Value |
|---|---|
| Starting cash | $50,000.00 |
| Minimum cash held | $37,024.35 |
| Mean cash held | $47,042.95 |
| Final cash | $47,688.78 |
| Peak invested | $13,222.38 |
| Mean deployed fraction | 7.79% |
| Max deployed fraction | 26.31% |
| Budget if every symbol caps out | $50,000.00 |

## Per-symbol P&L distribution

| Per-symbol P&L | Value |
|---|---|
| Symbols that traded | 1,000 |
| Profitable symbols | 835 |
| Losing symbols | 165 |
| Total P&L (realised + unrealised) | $2,365.99 |
| Mean per symbol | $2.37 |
| p10 / p25 / median / p75 / p90 | $-1.14 / $0.74 / $1.93 / $3.67 / $6.98 |
| Worst / best symbol | $-24.94 / $34.03 |

| Rank | Best symbol | P&L | Worst symbol | P&L |
|---|---|---|---|---|
| 1 | AXTI | $34.03 | TTD | $-24.94 |
| 2 | NBIS | $26.25 | DUOL | $-17.04 |
| 3 | AEHR | $24.78 | MNDY | $-15.28 |
| 4 | RGTI | $24.15 | CSGP | $-14.20 |
| 5 | VSAT | $21.02 | FLUT | $-11.14 |
| 6 | LITE | $19.07 | TRI | $-10.51 |
| 7 | SNDK | $18.17 | FDS | $-9.21 |
| 8 | UCTT | $16.12 | ELF | $-9.04 |
| 9 | SEDG | $15.82 | IT | $-8.59 |
| 10 | CIFR | $15.77 | PRMB | $-8.25 |

## Skipped triggers

| Skipped trigger | Count |
|---|---|
| skip_at_fill | 2 |
| skip_no_position | 14,016 |
| skip_per_symbol_cap | 138 |

## Data limitations

- Daily bars are split/dividend adjusted AS OF THE FETCH DATE (not point-in-time). Dividends are embedded in the adjusted series, not paid as cash into the account.
- U.S.-listed symbols only. No non-U.S. exchanges are covered at all.
- The universe is ranked by *today's* liquidity, so it is survivorship-biased: names that delisted or collapsed before the screen date are absent, which flatters any buy-the-dip rule.
- Daily closes only — no intraday path, so a level breached and reversed inside a session is invisible to the rule.
- Exchange holidays and per-symbol listing dates are handled by simply using whatever sessions each symbol actually has; a symbol that lists mid-window starts tracking then.

## Notes

Configuration (b2): the operator's $50 cap kept, with starting cash raised to the $50,000 that 1000 x $50 actually implies. Span is the full extent of the massive_grouped bulk archive (2025-01-03 onwards); this is NOT a 10-year test, and the universe is ranked by 2026 liquidity, so it is survivorship-biased over its own window. The committed JSON is the summary only - re-run with --trades-in-json for the full trade list and daily equity curve.
