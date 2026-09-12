# Grid backtest (a1) - 150-symbol snapshot, top 100 by liquidity rank, $50 cap, $5,000 cash

> **Hypothetical research output — not financial advice.** The grid is a mechanical rebalancing rule, not a researched edge: it has no promotion evidence, no walk-forward validation, and is not a registered strategy. Simulated fills only — no order was placed.

- Generated: 2026-09-12T03:50:17+00:00
- git: `f010889`
- Window: 2016-10-17 → 2026-09-10 (3,615 calendar days, 2,488 sessions)
- Data source: `massive`
- Universe: `snapshot:research_150_massive_10y_presealed_sel` (100 requested) from `DataSnapshot #11 'research_150_massive_10y_presealed_sel'`
- Ranking: ordered by the grid universe file's 60-session median-dollar-volume rank
- Liquidity window: n/a
- Symbols with bars: **100**; skipped for no/insufficient bars in the window: **0**
- Symbols that traded: **100**; symbols that reached the per-symbol cap: **2**

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
| universe_name | snapshot:research_150_massive_10y_presealed_sel |
| universe_size | 100 |
| costs | slippage 3 bps + half-spread (5 bps quoted), commission 0/share, min order $1 |
| budget if every symbol caps out | $5,000.00 |
| budget consistent with starting cash | yes |

## Headline metrics

| Metric | Value |
|---|---|
| Total return | +21.089% |
| CAGR | +1.952% |
| Max drawdown | 5.736% |
| Annualised vol | 2.621% |
| Sharpe (daily, rf=0) | 0.753 |
| Sortino (daily, rf=0) | 1.103 |
| Exposure (mean invested fraction) | 5.84% |
| Turnover / year | 1.841x |
| Trades | 16,488 (9,902 buys / 6,586 sells) |
| Trades / year | 1,665.9 |
| Start equity | $5,000.00 |
| End equity | $6,054.44 |
| Sessions | 2,488 |

## Benchmark

| Benchmark | Value |
|---|---|
| Benchmark | SPY buy-and-hold, same cash, same span, same cost model |
| Window | 2016-10-17 → 2026-09-10 |
| Total return | +255.443% |
| CAGR | +13.671% |
| Max drawdown | 34.105% |
| End equity | $17,772.15 |
| Grid − benchmark (total return) | -234.354 pp |

## Cash utilisation

| Cash utilisation | Value |
|---|---|
| Starting cash | $5,000.00 |
| Minimum cash held | $3,854.41 |
| Mean cash held | $5,148.63 |
| Final cash | $5,644.79 |
| Peak invested | $1,361.23 |
| Mean deployed fraction | 5.84% |
| Max deployed fraction | 26.02% |
| Budget if every symbol caps out | $5,000.00 |

## Per-symbol P&L distribution

| Per-symbol P&L | Value |
|---|---|
| Symbols that traded | 100 |
| Profitable symbols | 99 |
| Losing symbols | 1 |
| Total P&L (realised + unrealised) | $1,054.44 |
| Mean per symbol | $10.54 |
| p10 / p25 / median / p75 / p90 | $4.27 / $6.34 / $8.86 / $12.42 / $18.81 |
| Worst / best symbol | $-6.16 / $38.93 |

| Rank | Best symbol | P&L | Worst symbol | P&L |
|---|---|---|---|---|
| 1 | SHOP | $38.93 | GE | $-6.16 |
| 2 | AMD | $37.50 | ACN | $0.04 |
| 3 | NVDA | $28.37 | PFE | $0.92 |
| 4 | MRVL | $27.26 | BSX | $1.81 |
| 5 | MU | $27.25 | NKE | $1.85 |
| 6 | TSLA | $26.00 | MCD | $2.59 |
| 7 | KLAC | $21.81 | MDT | $3.04 |
| 8 | MELI | $21.29 | PEP | $3.68 |
| 9 | NOW | $20.55 | XOM | $4.01 |
| 10 | LRCX | $20.30 | BRK.B | $4.21 |

## Skipped triggers

| Skipped trigger | Count |
|---|---|
| skip_no_position | 6,451 |
| skip_per_symbol_cap | 9 |

## Data limitations

- Daily bars are split/dividend adjusted AS OF THE FETCH DATE (not point-in-time). Dividends are embedded in the adjusted series, not paid as cash into the account.
- U.S.-listed symbols only. No non-U.S. exchanges are covered at all.
- The universe is ranked by *today's* liquidity, so it is survivorship-biased: names that delisted or collapsed before the screen date are absent, which flatters any buy-the-dip rule.
- Daily closes only — no intraday path, so a level breached and reversed inside a session is invisible to the rule.
- Exchange holidays and per-symbol listing dates are handled by simply using whatever sessions each symbol actually has; a symbol that lists mid-window starts tracking then.

## Notes

Configuration (a1): the operator's '100 symbols / $50 cap' shape, run on the pre-sealed 150-symbol research snapshot (DataSnapshot research_150_massive_10y_presealed_sel) reduced to its 100 most liquid names by the grid universe file's 60-session median-dollar-volume ranking. The 15 sector/broad ETFs in that snapshot are absent from the stocks-only ranking and sort last; with 135 of the 150 ranked, the top 100 are all ranked common stocks. The committed JSON is the summary only - re-run with --trades-in-json for the full trade list and daily equity curve.
