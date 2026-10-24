# Paper trading status — 2026-10-24

Simulated paper trading only. No broker orders, no live execution, no arming.
Marks use stored end-of-day bars (latest complete session: 2026-10-22; 2026-10-23
partly ingested).

## Bottom line

**The paper run is profitable, but only slightly, because it barely traded after
October 17.** Three scheduling defects stopped signals from reaching the
paper ledger. They are fixed in this change. Nothing about the strategy, its
risk limits or its freshness gates was relaxed.

## Accounts

| Book | Strategy | Start | Equity now | P&L | Closed | Open |
|---|---|---:|---:|---:|---:|---:|
| `default` (the original $30k run) | trend_continuation medium swing (#3) | $30,000 | $30,409.50 | **+$409.50 (+1.36%)** | 5 scored + 2 voided | AAPL, NOW |
| `book-sv2` (added Oct 8) | trend_continuation short swing (#2) | $30,000 | $30,074.33 | **+$74.33 (+0.25%)** | 2 | AAPL |
| `grid`, `options` | research lanes, switched off | $5,000 / $25,000 | unchanged | $0 | 0 | 0 |

For comparison, SPY moved from $763.99 (Oct 1) to $759.97 (Oct 23), −0.5%.
Nine scored trades are far too few to draw conclusions about edge.

### Trades in the original $30k book

| Symbol | Opened | Closed | Realized |
|---|---|---|---:|
| MSFT ×5 | Oct 1 | Oct 13 | +$175.65 |
| XLK ×15 | Oct 1 | Oct 14 | −$75.45 |
| ACN ×7 | Oct 2 | Oct 16 | +$212.03 |
| TSLA ×4 | Oct 2 | Oct 16 | −$70.36 |
| ABBV ×3 | Oct 3 | Oct 9 | +$41.73 |
| AAPL ×6 | Oct 18 | open | +$24.45 unrealized |
| NOW ×6 | Oct 18 | open | +$101.46 unrealized |

The two September MSFT positions are voided at $0 (invalid pre-entry exits,
corrected on Oct 2) and are not counted.

## Why it stopped trading

From Oct 14 to Oct 24 the daily pipeline only produced tradable candidates
once (Oct 18). The rest of the time:

1. **The scanner and paper acceptance disagreed about which day was "today".**
   The scanner counted a session as complete from 17:30 ET; acceptance (correctly)
   from the 16:00 close. On Oct 22 a catch-up scan at 17:28 ET produced six
   candidates from Oct 21 data, and acceptance refused all six as stale. Those
   decisions are immutable, so the day's signals were lost.
2. **The market-data provider now publishes bars hours after our 17:30 ET job.**
   The ingest fetched ~150 symbols (30 minutes of rate limit), received nothing
   new, still recorded "ok", and the catch-up logic then believed the day was
   covered. The scans excluded every symbol as stale and nothing retried until
   the next evening (ingestion runs #61 and #66 wrote 0 bars).
3. **Jobs collided after the Mac woke from sleep.** The universe update fired at
   the same moment as the EOD update, used the same API quota (HTTP 429) and held
   the database write lock, so the EOD update failed with "database is locked"
   (Oct 18, Oct 23).

A contributing factor outside the code: the MacBook sleeps for long stretches,
so scheduled jobs run late and in bursts when it wakes.

## What changed

| Fix | Effect |
|---|---|
| One shared definition of the latest completed session (`data/calendar.last_closed_session`) used by both the scanner and acceptance | Scans between the close and data publication now exclude everything instead of producing candidates that are guaranteed to be refused |
| One-request publication probe (SPY) before each daily ingest | If the provider has not published yet, nothing is fetched or written; the catch-up retries in ~30 minutes instead of 2 hours or the next day |
| `universe_update` waits for the EOD update instead of running alongside it | No more shared-quota 429s or write-lock failures between the two |

Regression tests: `tests/test_eod_publication_and_session.py` (17 tests).

## What to watch next

- After the next weekday close, the log should show either
  `ProviderBarsNotPublished` followed by a successful catch-up, or a normal EOD run,
  then `approved_scope_scan.done` with candidates and `auto_simulate.done`.
- The 2-per-day auto-simulation cap and the 0.5%-per-trade risk limit are
  unchanged, so position sizes stay small (~$1–3k per trade on $30k).
- Keep the Mac awake and on power around 17:30–00:00 ET (14:30–21:00 Pacific)
  for the pipeline to run on time.
