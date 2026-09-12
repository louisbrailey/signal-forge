# Grid backtest (a2) - 150-symbol snapshot (all 150), $50 cap, $7,500 cash

> **Hypothetical research output — not financial advice.** The grid is a mechanical rebalancing rule, not a researched edge: it has no promotion evidence, no walk-forward validation, and is not a registered strategy. Simulated fills only — no order was placed.

- Generated: 2026-09-12T03:50:28+00:00
- git: `f010889`
- Window: 2016-10-17 → 2026-09-10 (3,615 calendar days, 2,488 sessions)
- Data source: `massive`
- Universe: `snapshot:research_150_massive_10y_presealed_sel` (150 requested) from `DataSnapshot #11 'research_150_massive_10y_presealed_sel'`
- Ranking: ordered by the grid universe file's 60-session median-dollar-volume rank
- Liquidity window: n/a
- Symbols with bars: **150**; skipped for no/insufficient bars in the window: **0**
- Symbols that traded: **150**; symbols that reached the per-symbol cap: **5**

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
| starting_cash | $7,500.00 |
| per_symbol_cap | $50.00 |
| buy_usd | $5.00 |
| sell_usd | $10.00 |
| drop_pct | 5.00% |
| rise_pct | 5.00% |
| min_order_usd | $1.00 |
| re-anchor on a rise with nothing to sell | yes (the grid ratchets up with price) |
| universe_name | snapshot:research_150_massive_10y_presealed_sel |
| universe_size | 150 |
| costs | slippage 3 bps + half-spread (5 bps quoted), commission 0/share, min order $1 |
| budget if every symbol caps out | $7,500.00 |
| budget consistent with starting cash | yes |

## Headline metrics

| Metric | Value |
|---|---|
| Total return | +18.330% |
| CAGR | +1.715% |
| Max drawdown | 6.776% |
| Annualised vol | 2.670% |
| Sharpe (daily, rf=0) | 0.652 |
| Sortino (daily, rf=0) | 0.928 |
| Exposure (mean invested fraction) | 6.04% |
| Turnover / year | 1.854x |
| Trades | 24,599 (14,813 buys / 9,786 sells) |
| Trades / year | 2,485.4 |
| Start equity | $7,500.00 |
| End equity | $8,874.73 |
| Sessions | 2,488 |

## Benchmark

| Benchmark | Value |
|---|---|
| Benchmark | SPY buy-and-hold, same cash, same span, same cost model |
| Window | 2016-10-17 → 2026-09-10 |
| Total return | +255.443% |
| CAGR | +13.671% |
| Max drawdown | 34.105% |
| End equity | $26,658.22 |
| Grid − benchmark (total return) | -237.113 pp |

## Cash utilisation

| Cash utilisation | Value |
|---|---|
| Starting cash | $7,500.00 |
| Minimum cash held | $5,673.65 |
| Mean cash held | $7,622.58 |
| Final cash | $8,256.56 |
| Peak invested | $2,063.08 |
| Mean deployed fraction | 6.04% |
| Max deployed fraction | 26.39% |
| Budget if every symbol caps out | $7,500.00 |

## Per-symbol P&L distribution

| Per-symbol P&L | Value |
|---|---|
| Symbols that traded | 150 |
| Profitable symbols | 145 |
| Losing symbols | 5 |
| Total P&L (realised + unrealised) | $1,374.73 |
| Mean per symbol | $9.16 |
| p10 / p25 / median / p75 / p90 | $2.58 / $5.02 / $7.92 / $11.54 / $17.60 |
| Worst / best symbol | $-12.45 / $38.93 |

| Rank | Best symbol | P&L | Worst symbol | P&L |
|---|---|---|---|---|
| 1 | SHOP | $38.93 | CCL | $-12.45 |
| 2 | AMD | $37.50 | GE | $-6.16 |
| 3 | MARA | $34.72 | RCL | $-6.16 |
| 4 | NVDA | $28.37 | SLB | $-1.81 |
| 5 | MRVL | $27.26 | BMY | $-0.42 |
| 6 | MU | $27.25 | ACN | $0.04 |
| 7 | TSLA | $26.00 | CHTR | $0.35 |
| 8 | KLAC | $21.81 | PFE | $0.92 |
| 9 | MELI | $21.29 | USB | $1.36 |
| 10 | NOW | $20.55 | BSX | $1.81 |

## Skipped triggers

| Skipped trigger | Count |
|---|---|
| skip_no_position | 9,220 |
| skip_per_symbol_cap | 163 |

## Data limitations

- Daily bars are split/dividend adjusted AS OF THE FETCH DATE (not point-in-time). Dividends are embedded in the adjusted series, not paid as cash into the account.
- U.S.-listed symbols only. No non-U.S. exchanges are covered at all.
- The universe is ranked by *today's* liquidity, so it is survivorship-biased: names that delisted or collapsed before the screen date are absent, which flatters any buy-the-dip rule.
- Daily closes only — no intraday path, so a level breached and reversed inside a session is invisible to the rule.
- Exchange holidays and per-symbol listing dates are handled by simply using whatever sessions each symbol actually has; a symbol that lists mid-window starts tracking then.

## Notes

Configuration (a2): all 150 symbols of the pre-sealed research snapshot (135 ranked common stocks plus 15 broad/sector ETFs the stocks-only ranking never covered, which sort last). Starting cash $7,500 against a $7,500 theoretical cap budget (150 x $50), so this is the one 10-year run whose budget is internally consistent. The committed JSON is the summary only - re-run with --trades-in-json for the full trade list and daily equity curve.
