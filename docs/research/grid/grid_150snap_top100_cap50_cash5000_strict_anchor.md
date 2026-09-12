# Grid backtest (a1-strict) - same as (a1) under the STRICT anchor reading

> **Hypothetical research output — not financial advice.** The grid is a mechanical rebalancing rule, not a researched edge: it has no promotion evidence, no walk-forward validation, and is not a registered strategy. Simulated fills only — no order was placed.

- Generated: 2026-09-12T03:51:02+00:00
- git: `f010889`
- Window: 2016-10-17 → 2026-09-10 (3,615 calendar days, 2,488 sessions)
- Data source: `massive`
- Universe: `snapshot:research_150_massive_10y_presealed_sel` (100 requested) from `DataSnapshot #11 'research_150_massive_10y_presealed_sel'`
- Ranking: ordered by the grid universe file's 60-session median-dollar-volume rank
- Liquidity window: n/a
- Symbols with bars: **100**; skipped for no/insufficient bars in the window: **0**
- Symbols that traded: **65**; symbols that reached the per-symbol cap: **1**

## Rules

Per symbol, on DAILY closes, exactly one evaluation per session:

1. Anchor starts at the close of the first tracked session (that session never trades).
2. `close <= anchor x (1 - 5.00%)` → BUY $5.00 (fractional shares), then anchor = that close.
3. `close >= anchor x (1 + 5.00%)` → SELL $10.00, capped at the position's market value, then anchor = that close.
4. Fills at the **next session's open** with slippage + half-spread against the trade.
5. The anchor moves when an order fills. A buy skipped for the cap, for cash, or for the minimum notional leaves the level armed. A rise past the sell level with nothing to sell does NOT re-anchor (`reanchor_on_untradeable_rise` is off), so a symbol that rises before it ever dips can never trade again.
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
| re-anchor on a rise with nothing to sell | no (strict literal reading — a symbol that rises before it ever dips is stranded forever) |
| universe_name | snapshot:research_150_massive_10y_presealed_sel |
| universe_size | 100 |
| costs | slippage 3 bps + half-spread (5 bps quoted), commission 0/share, min order $1 |
| budget if every symbol caps out | $5,000.00 |
| budget consistent with starting cash | yes |

## Headline metrics

| Metric | Value |
|---|---|
| Total return | +1.221% |
| CAGR | +0.123% |
| Max drawdown | 1.067% |
| Annualised vol | 0.326% |
| Sharpe (daily, rf=0) | 0.378 |
| Sortino (daily, rf=0) | 0.580 |
| Exposure (mean invested fraction) | 0.38% |
| Turnover / year | 0.110x |
| Trades | 931 (545 buys / 386 sells) |
| Trades / year | 94.1 |
| Start equity | $5,000.00 |
| End equity | $5,061.03 |
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
| Grid − benchmark (total return) | -254.222 pp |

## Cash utilisation

| Cash utilisation | Value |
|---|---|
| Starting cash | $5,000.00 |
| Minimum cash held | $4,750.71 |
| Mean cash held | $5,016.70 |
| Final cash | $5,056.28 |
| Peak invested | $253.37 |
| Mean deployed fraction | 0.38% |
| Max deployed fraction | 5.06% |
| Budget if every symbol caps out | $5,000.00 |

## Per-symbol P&L distribution

| Per-symbol P&L | Value |
|---|---|
| Symbols that traded | 65 |
| Profitable symbols | 59 |
| Losing symbols | 6 |
| Total P&L (realised + unrealised) | $61.03 |
| Mean per symbol | $0.94 |
| p10 / p25 / median / p75 / p90 | $0.06 / $0.27 / $0.60 / $1.56 / $3.47 |
| Worst / best symbol | $-10.62 / $8.80 |

| Rank | Best symbol | P&L | Worst symbol | P&L |
|---|---|---|---|---|
| 1 | INTC | $8.80 | GE | $-10.62 |
| 2 | BA | $7.13 | XOM | $-6.02 |
| 3 | AAL | $4.59 | CLS | $-2.82 |
| 4 | DIS | $4.09 | CVX | $-1.23 |
| 5 | GILD | $3.92 | COP | $-0.80 |
| 6 | T | $3.51 | SCHW | $-0.43 |
| 7 | PFE | $3.48 | BKNG | $0.01 |
| 8 | NEM | $3.44 | AMD | $0.14 |
| 9 | CMCSA | $3.18 | WFC | $0.15 |
| 10 | MSTR | $2.89 | SHOP | $0.16 |

## Skipped triggers

| Skipped trigger | Count |
|---|---|
| skip_no_position | 230,579 |

## Data limitations

- Daily bars are split/dividend adjusted AS OF THE FETCH DATE (not point-in-time). Dividends are embedded in the adjusted series, not paid as cash into the account.
- U.S.-listed symbols only. No non-U.S. exchanges are covered at all.
- The universe is ranked by *today's* liquidity, so it is survivorship-biased: names that delisted or collapsed before the screen date are absent, which flatters any buy-the-dip rule.
- Daily closes only — no intraday path, so a level breached and reversed inside a session is invisible to the rule.
- Exchange holidays and per-symbol listing dates are handled by simply using whatever sessions each symbol actually has; a symbol that lists mid-window starts tracking then.

## Notes

Sensitivity run for the one genuine ambiguity in the operator's rule. Identical to (a1) except that a rise past the sell level with nothing to sell does NOT re-anchor. Under that reading any symbol which rises 5% before it ever falls 5% is stranded at its first anchor and can never trade again: only 65 of the 100 symbols ever trade, and NVDA, MSFT, AVGO, ORCL, COST and MA are among those that never do. That is why the default is to ratchet.
