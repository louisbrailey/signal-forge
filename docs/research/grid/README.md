# The mechanical grid strategy

> **Hypothetical research output — not financial advice.** The grid is a mechanical
> rebalancing rule, not a researched edge. It has no walk-forward validation, no sealed
> out-of-sample test, and no promotion evidence; it is deliberately **not** a registered,
> promotion-gated strategy, produces no `Candidate`, and never sends an alert. Every fill
> below is SIMULATED — no brokerage is contacted and no order is ever placed.

## 1. The rules, exactly

All rules operate on **daily bars**. Exactly **one** evaluation happens per symbol per session.

1. Each symbol carries an **anchor price**. The anchor starts at the close of the first
   session on which the symbol is tracked. That first session never trades.
2. On each later session's **close**:
   - `close <= anchor x (1 - drop_pct)` → **BUY `buy_usd`** of stock (fractional shares
     allowed), then `anchor = that close`;
   - `close >= anchor x (1 + rise_pct)` → **SELL `sell_usd`** of stock, capped at the
     position's market value, then `anchor = that close`;
   - otherwise nothing happens and the anchor does not move.
3. A triggered order fills at the **next session's open** for that symbol — the project's
   existing next-open convention — with the project cost model applied **against** the
   trade: `3 bps slippage + half of a 5 bps quoted spread = 5.5 bps`, commission `0`.
4. Per-order **minimum notional**: an order below `min_order_usd` (default `$1`) is skipped.
5. **Per-symbol budget cap**: a symbol's cost basis may never exceed `per_symbol_cap`. A buy
   that would breach it is skipped.
6. **Global cash**: a buy is skipped if there is not enough cash. Cash never goes negative.
7. **No leverage, no shorting.** A sell can never exceed the shares held.

### Three places the operator's rule was silent, and what was chosen

| Situation | Decision | Why |
|---|---|---|
| A buy is skipped for the cap, for cash, or for the minimum notional | The anchor does **not** move — the level stays armed | The rule genuinely wanted that order; only capacity stopped it. Moving the anchor would silently cancel the signal. |
| A rise fires past the sell level with **nothing to sell** | The anchor **ratchets up** to that close (`reanchor_on_untradeable_rise`, default on) | Under the strict literal reading (no sell ⇒ no action ⇒ no re-anchor) a symbol that rises 5% before it ever falls 5% is stranded at its first anchor and can never trade again. Measured: only 65 of 100 symbols ever traded over ten years, and NVDA, MSFT, AVGO, ORCL, COST and MA were among those that never did. The flag exists so the strict reading can still be run — see the sensitivity row in §5. |
| A sell would leave a remainder worth less than `min_order_usd` | The **whole position** is sold | A $10 sell out of a $10.50 position leaves $0.50, which can never clear the $1 minimum again. The sell is then skipped forever, the anchor never moves, and because the stranded anchor also sits far below price the buy level is unreachable too — the symbol freezes. Measured: 69 of 92 open positions were dead dust before this was fixed. |

### Ordering inside one session

Sells fill before buys (so the day's proceeds can fund the day's purchases), and within each
group symbols are processed in **universe order** — which is what decides who gets scarce
cash when the grid is cash-constrained. This is deterministic and stated on every report.

Notional order quantities are floored to 6 decimal places, so a buy never spends more than
`buy_usd`. (Rounding to nearest let `qty x price` land a fraction of a cent over the
requested amount, which then tripped the cap and cash checks at fill time.)

## 2. Parameters

| Parameter | Default | Meaning |
|---|---|---|
| `starting_cash` | `5000.0` | Opening cash for the (paper) account. |
| `per_symbol_cap` | `50.0` | Maximum cost basis any one symbol may reach. |
| `buy_usd` | `5.0` | Dollars bought on each BUY trigger. |
| `sell_usd` | `10.0` | Dollars sold on each SELL trigger, capped at market value. |
| `drop_pct` | `0.05` | Buy trigger, as a **fraction** (0.05 = 5%). |
| `rise_pct` | `0.05` | Sell trigger, as a **fraction**. |
| `min_order_usd` | `1.0` | Orders below this notional are skipped. |
| `reanchor_on_untradeable_rise` | `True` | Ratchet the anchor when a rise fires with nothing to sell. |
| `universe_name` | `"top1000"` | Which universe to resolve. |
| `universe_size` | `1000` | How many symbols to take from it. |
| `slippage_bps` | `3.0` | Project cost model. |
| `spread_bps` | `5.0` | Half of this is charged against every fill. |
| `commission_per_share` | `0.0` | Commission-free assumption. |

Live (paper) values live in `research.grid` (`signalforge.config.research.GridConfig`), which
carries the same fields plus `enabled`, `account_name` and `source`.

## 3. The operator's numbers do not add up

The brief specified **1000 symbols**, a **$50 per-symbol cap**, and **$5,000 of starting
cash**. But `1000 x $50 = $50,000`, ten times the cash. The cap can therefore never bind —
cash runs out first — so `per_symbol_cap` would be decorative at that size.

Rather than pick one silently, `universe_size`, `per_symbol_cap` and `starting_cash` are all
parameters, and all three readings are runnable and reported:

| Config | Universe | Cap | Cash | Cap budget | Consistent? |
|---|---|---|---|---|---|
| **b1** | 1000 | $5 | $5,000 | $5,000 | yes — cap and cash agree exactly |
| **a1** | 100 | $50 | $5,000 | $5,000 | yes — the operator's other stated shape |
| **b2** | 1000 | $50 | $50,000 | $50,000 | yes — the $50 cap kept, cash raised to match |

`grid backtest` prints a warning whenever the chosen cap x universe size exceeds starting
cash, and every report states the cap budget alongside the cash.

## 4. Data limitations

- **U.S.-listed only.** The universe is U.S.-listed common stocks including ADRs. No
  non-U.S. exchange is covered at all, so this says nothing about non-U.S. markets.
- **Survivorship bias.** `data/grid_universe_top1000.json` ranks by *today's* 60-session
  median dollar volume. Names that delisted, were acquired, or collapsed before the screen
  date are simply absent. That systematically flatters any buy-the-dip rule, because the
  dips that never recovered are not in the sample.
- **Bars are adjusted as of the fetch date, not point-in-time.** A split or dividend that
  happened after a bar was written is already reflected in it. The grid therefore behaves as
  if every historical price had always been quoted on today's share-count basis, and
  dividends are embedded in the adjusted series rather than paid as cash into the account.
- **Daily closes only.** No intraday path is modelled, so a level breached and reversed
  inside a session is invisible to the rule.
- **Two different spans.** The `massive` research feed covers ~10 years for 167 symbols; the
  `massive_grouped` bulk archive covers ~1.7 years (from 2025-01-03) for ~2,655 symbols. The
  1000-symbol runs are therefore **not** ten-year tests, and their window is a single strong
  bull market. `--source` is always explicit so the two are never silently blended.
- **No holiday calendar.** Each symbol is evaluated on whatever sessions it actually has; a
  symbol that lists mid-window starts tracking then.

## 5. Results on the data available as of 2026-09-11

Costs: 3 bps slippage + half of a 5 bps spread, commission 0, $1 minimum order. Benchmark is
SPY buy-and-hold over exactly the same span with the same entry cost.

### 10-year runs — `massive`, 2016-10-17 → 2026-09-10 (2,488 sessions)

| Metric | (a1) top 100, $50 cap, $5,000 | (a2) all 150, $50 cap, $7,500 |
|---|---|---|
| Total return | **+21.09%** | **+18.33%** |
| CAGR | +1.95% | +1.72% |
| Max drawdown | 5.74% | 6.78% |
| Ann. vol / Sharpe | 2.62% / 0.75 | 2.67% / 0.65 |
| Trades | 16,488 (9,902 B / 6,586 S) | 24,599 (14,813 B / 9,786 S) |
| Trades / year | 1,666 | 2,485 |
| Turnover / year | 1.84x | 1.85x |
| Exposure (mean invested) | **5.84%** | **6.04%** |
| Peak invested / min cash | $1,361 / $3,854 | $2,063 / $5,674 |
| Symbols traded / at cap | 100 / 2 | 150 / 5 |
| Profitable symbols | 99 of 100 | 145 of 150 |
| End equity | $6,054 | $8,875 |
| **SPY buy-and-hold** | **+255.44%** (CAGR 13.67%, maxDD 34.10%) | same |
| **Grid − SPY** | **−234.35 pp** | **−237.11 pp** |

### ~1.7-year runs — `massive_grouped`, 2025-01-03 → 2026-09-08 (420 sessions)

| Metric | (b1) 1000, $5 cap, $5,000 | (b2) 1000, $50 cap, $50,000 |
|---|---|---|
| Total return | **+23.70%** | **+4.73%** |
| CAGR | +13.51% | +2.79% |
| Max drawdown | 15.69% | 2.49% |
| Ann. vol / Sharpe | 13.39% / 1.02 | 3.22% / 0.88 |
| Trades | 11,597 (6,215 B / 5,382 S) | 40,860 (24,968 B / 15,892 S) |
| Trades / year | 6,910 | 24,346 |
| Turnover / year | 6.50x | 2.89x |
| Exposure (mean invested) | **53.44%** | **7.79%** |
| Peak invested / min cash | $4,250 / $414 | $13,222 / $37,024 |
| Symbols traded / at cap | 1000 / 1000 | 1000 / 15 |
| Profitable symbols | 741 of 1000 | 835 of 1000 |
| End equity | $6,185 | $52,366 |
| **SPY buy-and-hold** | **+30.30%** (CAGR 17.08%, maxDD 19.00%) | same |
| **Grid − SPY** | **−6.60 pp** | **−25.57 pp** |

### Sensitivity: the strict anchor reading

Configuration (a1) re-run with `--no-reanchor-on-untradeable-rise`:

| | (a1) ratcheting (default) | (a1) strict literal |
|---|---|---|
| Total return | +21.09% | **+1.22%** |
| Trades | 16,488 | 931 |
| Exposure | 5.84% | 0.38% |
| Symbols that ever traded | 100 of 100 | **65 of 100** |
| Dead `skip_no_position` evaluations | 6,451 | **230,579** |

### What the numbers say

1. **The binding constraint is exposure, not edge.** At a $50 cap the grid holds 6-8% of the
   account in stock on average and leaves the rest in cash earning nothing in this model. Its
   absolute return is roughly its exposure times a long-equity return, so it cannot get near
   a fully-invested benchmark. Over ten years that is +21% against SPY's +255%.
2. **Raising exposure raises return roughly proportionally.** (b1) is the only configuration
   that deploys real capital (53% mean, 91% peak) and it is the only one that comes close to
   SPY (−6.6 pp over the window). That is an *exposure* result, not evidence of skill.
3. **It is not the same risk.** Max drawdown is 5.7% (a1) and 15.7% (b1) against SPY's 34.1%
   / 19.0%. Most of the drawdown reduction is just the cash, and the 10-year runs' Sharpe
   (0.65-0.75) is computed on a nearly-flat curve.
4. **The high hit rate is mechanical, not predictive.** 99 of 100 symbols "profitable" in
   (a1) is what a rule that sells every 5% pop out of a rising market produces; it caps
   winners and keeps losers, so per-symbol P&L skews tiny and positive (median $8.86 over ten
   years) while the market's compounding is left on the table.
5. **The 1000-symbol window is a bull market with a survivorship-biased universe.** Treat
   (b1)/(b2) as a description of 2025-2026 for names that were liquid in 2026, not as an
   estimate of future return.

**None of this is a promotion result.** No walk-forward, no sealed test, no regime coverage
analysis, and no approval scope — the grid cannot be promoted and is excluded from the
approval-scope hash by construction.

## 6. What real execution would require

- A **fractional-share broker** — every order is a $5 or $10 notional, i.e. a fraction of a
  share for almost every symbol in the universe.
- **Commission-free trading.** At 1,666-24,346 trades a year, even $0.35 per order would
  cost $583-$8,521 a year against an account of $5,000-$50,000. Any per-order commission
  destroys the strategy outright.
- **Notional (dollar) orders** that the broker accepts at or below a $1 minimum, and that
  fill at the open.
- **Market-on-open capacity for hundreds of simultaneous tiny orders.** (b2) averages ~97
  orders per session across 1000 names.
- The modelled **5.5 bps** of slippage + half-spread is optimistic for $5 orders in anything
  but the most liquid names; a real book would also pay the full spread more often than half.
- **Wash-sale and tax-lot accounting** for thousands of small round trips a year, which this
  model does not attempt at all.

## 7. How to run the backtests

`grid backtest` is **read-only**: it loads bars through the existing data access and writes
only the report files. It never creates a `grid_trade`, `grid_position`, or paper account.

```bash
export PYTHONPATH=<repo>/src

# (a1) 100 most liquid names of the pre-sealed 150-symbol research snapshot, 10 years
signalforge grid backtest \
  --snapshot-key research_150_massive_10y_presealed_sel --top 100 \
  --source massive --since 2016-10-17 --until 2026-09-10 \
  --starting-cash 5000 --per-symbol-cap 50 \
  --slug grid_150snap_top100_cap50_cash5000

# (a2) all 150 symbols of that snapshot, cash matched to the cap budget
signalforge grid backtest \
  --snapshot-key research_150_massive_10y_presealed_sel \
  --source massive --since 2016-10-17 --until 2026-09-10 \
  --starting-cash 7500 --per-symbol-cap 50 \
  --slug grid_150snap_all150_cap50_cash7500

# (b1) the full top-1000 bulk universe, $5 cap / $5,000 cash
signalforge grid backtest \
  --universe top1000 --source massive_grouped \
  --since 2025-01-03 --until 2026-09-08 \
  --starting-cash 5000 --per-symbol-cap 5 \
  --slug grid_top1000_cap5_cash5000

# (b2) the same universe with the $50 cap and matching cash
signalforge grid backtest \
  --universe top1000 --source massive_grouped \
  --since 2025-01-03 --until 2026-09-08 \
  --starting-cash 50000 --per-symbol-cap 50 \
  --slug grid_top1000_cap50_cash50000

# sensitivity: the strict literal anchor reading
signalforge grid backtest ... --no-reanchor-on-untradeable-rise
```

Other options: `--universe top100|topN|all|<file.json>|<file.txt>`, `--symbols A,B,C`,
`--buy-usd`, `--sell-usd`, `--drop-pct`, `--rise-pct`, `--min-order-usd`, `--benchmark`,
`--out <dir>`, `--title`, `--notes`, and `--trades-in-json` / `--no-trades-in-json`.

**The committed JSON reports are summaries only** (`--no-trades-in-json`) — metrics,
benchmark, cash utilisation, per-symbol P&L, positions and skip counts. Re-run any command
above with `--trades-in-json` to regenerate the full trade list and daily equity curve
locally; for the 1000-symbol runs that is several megabytes.

### Running against a copy of the live database

The live database is in use by the worker and the paper probation. Work on a read-only copy:

```bash
sqlite3 "file:<data>/signalforge.sqlite?mode=ro" ".backup $TMPDIR/scratch-grid.sqlite"
DATABASE_URL="sqlite+pysqlite:///$TMPDIR/scratch-grid.sqlite" signalforge grid backtest ...
```

## 8. The live (paper) side

- A dedicated `PaperAccount` named **`grid`** with its own cash. The grid can never touch the
  research paper account.
- Tables `grid_position` (symbol, fractional qty, cost basis, anchor, timestamps) and
  `grid_trade` (append-only: side, qty, price, usd, anchor before/after, session date, and an
  `evidence_json` snapshot of the close, open, params, cost model and code version), added by
  an **additive** migration (plain `create_table`, no `batch_alter_table` on anything
  existing).
- A scheduled job **`grid_daily`**, chained at the end of `job_daily_eod_update` and also
  available as `signalforge run-job grid_daily`. It evaluates the **previous** session's
  close and fills at **today's** open, calling the same `decide()` and `execute_fill()` the
  backtest uses — the live path cannot drift from the backtested rule.
- **OFF by default** (`research.grid.enabled`). Disabled means a logged no-op that never even
  takes the SQLite write lock.
- Kill-switch guarded (invariant S6), and **idempotent per `(account, symbol, session_date)`**
  — enforced by a pre-check and backstopped by a unique constraint on `grid_trade`.
- Every fill writes an `AuditLog("grid.trade")` row alongside the trade.
- `signalforge grid status` prints the live state; the **/grid** dashboard page shows equity,
  cash, positions, the last 50 trades and the parameters.
- `GridConfig` is deliberately **excluded** from `ResearchConfig.SCOPE_HASH_FIELDS`: the grid
  is not promotion-gated, so its settings must never appear able to re-scope a genuinely
  `PAPER_APPROVED` strategy. A test asserts `config_hash` is unchanged by any grid setting
  while `full_config_hash` moves.
