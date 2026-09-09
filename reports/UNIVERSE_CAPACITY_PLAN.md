# U.S. Equities Universe — Capacity Plan

**Status: plan for review. Nothing below is implemented.** Per your instruction,
only the *liquid U.S. research universe* tier will be built, and only after you
review this. Every figure marked *measured* was taken live from Massive on
2026-09-09 with the existing Stocks Developer key; everything else is an
estimate with its arithmetic shown.

Scope guard (unchanged by any tier): U.S.-listed common stocks and ETFs only —
no OTC, crypto, futures, FX, non-U.S. exchanges, brokerage data, or
options-contract-wide scanning. All stock data stays labelled `END_OF_DAY` /
`DELAYED`, never live. A larger universe does **not** promote a strategy, widen
alert eligibility, auto-simulate, or create a paper trade — the five-way
approval-scope match and `paper_probation_enabled` gate are untouched.

---

## 1. What Massive actually serves (measured)

| Fact | Measured value | How |
|---|---|---|
| Active U.S. common stocks (`type=CS`) | **5,317** (XNAS 3,334 · XNYS 1,750 · XASE 232) | `/v3/reference/tickers?market=stocks&active=true&locale=us&type=CS` |
| Active U.S. ETFs (`type=ETF`) | **5,429** (ARCX 2,482 · BATS 1,613 · XNAS 1,257) | same, `type=ETF` |
| ADRs / preferreds (excluded by scope) | 376 ADRC · 429 PFD | same |
| Every active `market=stocks` ticker, any type | 13,155 | same, no type filter |
| Rows in one grouped-daily response (all U.S. stocks, one session) | **12,510–13,242** rows, **~1.37 MB** JSON | `/v2/aggs/grouped/locale/us/market/stocks/{date}?adjusted=true` |
| Reference detail per ticker | `market_cap`, `list_date`, `sic_code`, `share_class_shares_outstanding`, `primary_exchange` — **current values only** | `/v3/reference/tickers/AAPL` |
| Splits / dividends reference | available (HTTP 200) | `/v3/reference/splits`, `/v3/reference/dividends` |
| Flat files (`files.massive.com`) | **HTTP 403 with the REST key** | needs separate S3 access keys from the dashboard — *unvalidated whether Stocks Developer includes them* |
| NBBO quotes (for spread) | HTTP 403 — not entitled | `providers verify` |
| Adapter REST throttle in this repo | `rate_limit_per_min=5` (`data/adapters/massive.py`) | — |

Liquidity tiers, from 20 real sessions (2026-08-08 → 2026-09-04, adjusted grouped
daily, `ADV$ = mean(volume × vwap)`, price ≥ $5, present on ≥ 90 % of sessions):

| Filter | CS | ETF | CS + ETF |
|---|---|---|---|
| ADV$ ≥ $50M | 1,319 | 387 | 1,706 |
| **ADV$ ≥ $20M (repo default `min_avg_dollar_volume`)** | **1,924** | **655** | **2,579** |
| ADV$ ≥ $10M | 2,318 | 927 | 3,245 |
| ADV$ ≥ $5M | 2,656 | 1,243 | 3,899 |
| ADV$ ≥ $1M | 3,175 | 2,273 | 5,448 |
| any volume, price ≥ $1 | 4,667 | 5,324 | 9,991 |

The repo's existing `UniverseFilters` defaults (`config/research.py`: price ≥ $5,
ADV$ ≥ $20M, market cap ≥ $2B, ≥ 400 days history, `max_universe_size` 150)
already describe the liquid tier; the $2B cap floor and history floor will trim
the 2,579 further (estimate **~1,800–2,200** after cap/history, ETFs have no
market cap so they pass on ADV$ alone).

## 2. Storage model (measured on the current DB)

Current SQLite: 27 instruments, 64,388 daily rows (2016-09 → 2026-09), file
30.5 MB. Per daily row: **~150 B in the table, ~280 B with the five indexes**;
`raw_payload_cache` (verbatim per-request JSON) adds ~140 B/row on the
per-symbol REST path. Per symbol-year (252 rows): ~70 KB normalized.

Bulk path (grouped daily / flat file): one file per session for the whole
market — ~1.4 MB JSON or ~0.4 MB gzip CSV, kept **separately** from normalized
rows and only parsed into `ohlcv_daily` for eligible symbols.

## 3. The three tiers

| | Current 25-symbol watchlist | Liquid U.S. research universe | Entire active U.S. CS + ETF |
|---|---|---|---|
| Symbols (discovered → eligible) | 25 → 24 (ex-META) | 10,746 discovered → **~2,580** pass price/ADV$ → **~2,000** after cap/history/quality (estimate) | 10,746 discovered → **~10,000** with any data |
| Daily rows, 10-year history | 64K (measured) | ~5.0M (2,000 × 2,520 sessions) | ~19M (avg ~7.5 y history × 10,000) |
| Normalized storage, SQLite (table + indexes) | 18 MB (measured) | **~1.4 GB** | **~5.3 GB** |
| Normalized storage, Postgres | n/a | ~1.0–1.5 GB + indexes | ~4–6 GB + indexes |
| Raw bulk archive (grouped JSON / flat files, all symbols, 10 y) | 9 MB per-symbol JSON (measured) | ~3.5 GB JSON or **~1 GB gzip flat files** | same file set — the bulk archive is market-wide regardless of tier |
| Daily update: requests | 25 per-symbol REST calls | **1** grouped/flat-file fetch (+ ~2,000 upserts) | **1** fetch (+ ~12,500 upserts) |
| Daily update: wall time | ~5 min at 5 req/min (measured throttle) | **< 1 min** | **~1–2 min** (SQLite) |
| 10-year backfill | done | 2,520 grouped requests: **~8.4 h at 5/min**, ~1 h unthrottled; or flat files: minutes to download, ~30–60 min to parse | same download; parse ~2–4 h SQLite, less on Postgres |
| Per-symbol REST backfill instead (for comparison) | 5 min | 2,000 × 12 s = **6.7 h/day** — infeasible for daily use | 36 h — infeasible |
| Scan time (today's strategies, EOD) | seconds | ~2–5 min (linear in symbols, unmeasured) | ~10–25 min (unmeasured) |
| Promotion re-evaluation (10 gates, walk-forward) | ~minutes (measured earlier) | hours; must be run per approved dataset snapshot, not per symbol | not intended — this tier is a *discovery/screening* universe, never a promotion universe |

## 4. Data-quality limits that apply at every tier (must be designed around)

1. **Adjustment is as-of-now, not point-in-time.** Grouped daily with
   `adjusted=true` (and any flat file) re-states history with *today's* split
   factors; the repo already refuses unadjusted responses for research
   (`massive.py` raises "Incomplete or unadjusted response"). Backtests and
   promotion must use `ohlcv_daily.adj_close` built from the splits/dividends
   reference with effective dates — never treat flat-file history as adjusted.
   Raw bulk files stay unadjusted and separate; normalization applies factors.
2. **Survivorship.** `active=true` discovery excludes delisted names; a
   backtest over the liquid tier needs the `active=false` list and each
   symbol's `list_date`/delist date to build a point-in-time membership
   snapshot (`DataSnapshot` already exists for exactly this).
3. **Ticker continuity / corporate actions.** The FB→META case is the
   template: `SymbolContinuityMapping` must be applied before a symbol is
   eligible; tickers that changed hands need an exclusion or a mapped
   continuous series.
4. **Market cap is current only.** Usable as an eligibility filter for
   *today's* scan universe; not usable point-in-time for backtests (would leak
   the future). Sector comes from `sic_code`, not GICS.
5. **No spread estimate.** NBBO is not entitled (403); `max_avg_spread_bps`
   cannot be applied from quote data. Options: skip the filter and label it
   "not licensed", or use a documented proxy (Corwin–Schultz high–low spread
   estimator) clearly marked as an estimate.
6. **Latency label.** Everything here is `END_OF_DAY`; the grouped daily
   endpoint is only complete after the session (≈ 17:30 ET, matching the
   existing cron). Intraday scanning is out of scope.
7. **Flat-file access is unvalidated.** Until S3 keys are confirmed, the
   grouped-daily REST endpoint (1 request/session) is the bulk path; it is
   functionally equivalent for daily bars and already entitled.
8. **Throttle.** The 5 req/min adapter setting is self-imposed; Massive's
   actual limit is higher (the measurements above ran 20+ requests in ~10 s
   without a 429). Keep 5/min for per-symbol paths; the bulk path needs one
   request per session and is unaffected.

## 5. Recommendation

Build the **liquid U.S. research universe** on the grouped-daily bulk path
(flat files swapped in later if the S3 keys exist), with:

- discovery from `/v3/reference/tickers` (CS + ETF, `locale=us`, active and
  inactive for point-in-time membership), stored as `UniverseMember` rows
  with `first_seen`/`last_seen`;
- a `RawBulkFile` table + on-disk archive for each session's grouped payload
  (checksum, byte size, row count, fetched_at) — resumable, idempotent, with a
  configurable storage budget (default 5 GB) that refuses to ingest past it;
- a normalization step writing only eligible symbols to `ohlcv_daily`, with
  split/dividend factors from the reference endpoints and validation
  (gaps, zero-volume, price spikes) recorded per run;
- the configurable eligibility filters you listed, evaluated nightly, with
  every stage count persisted:
  `discovered → excluded-by-reason (type, price, ADV$, cap, spread-n/a,
  history, sector concentration, corporate action / continuity / quality)
  → eligible → scanned → no-trade → qualified`;
- a coverage dashboard page (counts per stage, storage used vs budget,
  last bulk file per session, validation failures);
- `DataSnapshot` rows for the eligible set per session so any future
  promotion runs on a frozen, named membership list.

Not in scope until you say so: the 10,000-symbol discovery tier as a scan
universe, any change to which strategies are approved or alert-eligible,
options beyond the approved liquid underlyings, and any intraday data.

Estimated build: the bulk ingestion, normalization, filters, counts, and
coverage page are ~2–3 focused sessions; the point-in-time membership and
adjustment-factor work is the part that needs the most tests.
