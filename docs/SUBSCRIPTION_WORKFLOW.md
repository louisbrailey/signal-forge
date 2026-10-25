# Subscription workflow — verified 2026-10-24

Paper research only. Additional subscriptions do not prove an edge or promote a strategy.

## Observed access

- Stocks: daily/history, 5-minute aggregates, last trade and NBBO quote requests succeeded.
- Options: contracts, snapshots, aggregates, trades, bid/ask, IV, Greeks and OI checks succeeded.
- Benzinga: dedicated `/benzinga/v2/news` delivered current articles. Ratings and analyst-insights returned 403; News does not include these.
- Currencies: completed daily EURUSD, USDJPY and spot gold XAUUSD bars ingested.
- Indices: SPX and VIX daily requests returned 403. They remain visibly unavailable; no subscription upgrade is attempted.
- Futures: ESZ6 contract and five session aggregates succeeded. This is one explicitly pinned December 2026 contract, not a continuous series or futures strategy. Do not splice its returns to another contract. After expiration it becomes stale until a separately reviewed rollover update.

Checks prove sampled endpoint access, not every endpoint or historical coverage. Existing history and research reports remain unchanged. The verifier now groups by asset class rather than incorrectly naming every account Developer.

## Operational use

`uv run signalforge providers verify` records endpoint-level results without credentials.
`uv run signalforge providers refresh-context` caches six small context feeds, at most once per UTC date, including failed attempts. No same-day retry storm. Requests are spaced 12.1 seconds; kill switch is checked while waiting. HTTP calls run outside write transactions. Under concurrent invocations writes are deduplicated under a write lock (duplicate network requests remain possible).

Overview and deterministic daily briefing read the same cached data. The scheduler registers `market_context` once daily; a running worker must restart to load new jobs. Context requires only existing DB tables. Raw successful responses are retained separately from UI-derived percentage changes. Responses over 64 KiB or containing the configured key are discarded. Errors retain only an error category. Growth is capped per refresh, not by total lifetime retention; existing backup/retention operations still apply.

- EURUSD/USDJPY: dollar exposure context for the equities portfolio.
- XAUUSD: gold context; it is a quote-derived spot series, not a traded equity.
- SPX/VIX: benchmark/volatility context only when actually entitled.
- ESZ6: historical equity-index futures context; session-start UTC differs from settlement date. No futures order path.
- Stocks: existing deterministic strategies and portfolio risk checks remain authoritative.
- Options: existing education/evidence/paper safeguards remain authoritative; better quote access does not establish positive expectancy.
- Benzinga: source-linked explanation and event context; never independently scores or sizes a trade.

All context is END-OF-DAY. The dashboard does not call the provider. Missing and failed feeds are unavailable; observations older than four calendar days are stale (conservative simple threshold, not a complete FX/futures calendar). Percentage changes compare adjacent available bars, not guaranteed consecutive sessions. Market-data timestamps are bar starts. Existing stock/options DELAYED labels are conservative: HTTP 200 alone does not certify real-time delivery. Session-time freshness/entitlement verification is needed before changing that label; this check ran on Saturday.

## Research boundary

New context is not consumed by signals, rankings, position sizing or risk overrides. No profit claim is supported by this integration. To test incremental value, pre-register a frozen baseline comparison using point-in-time context, chronological validation, costs and a fresh untouched test. Existing sealed outcomes must not be reused for tuning. Kronos remains disconnected after its negative study.

## Sources

- https://massive.com/docs/rest/forex/overview
- https://massive.com/docs/rest/indices/overview
- https://massive.com/docs/rest/futures/contracts
- https://massive.com/docs/rest/futures/aggregates (Basic: eight-hour historical; not streaming)

Research signal only — no order was placed.
