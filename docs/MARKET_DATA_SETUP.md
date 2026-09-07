# Market-data setup

Recommendation checked September 6, 2026: Massive Stocks Basic for initial
integration; Stocks Advanced for real-time U.S. trades and quotes after validation.

| Plan | Monthly list price | Freshness |
| --- | --- | --- |
| Basic | $0 | End of day; 5 API calls/minute; 2 years history |
| Starter | $29 | 15-minute delayed |
| Advanced | $199 | Real-time trades, quotes, WebSockets |

Source: https://massive.com/pricing?product=stocks
These are individual plans. Advanced is listed for non-professionals. Complete
provider agreements and verify eligibility, automated personal research use,
and local caching rights before activation. Do not buy news/options add-ons yet.

Create your own provider account and keep its API key out of chat. Configure
MARKET_DATA_PROVIDER=massive and MARKET_DATA_API_KEY in the local ignored .env.
Never use brokerage credentials. Account purchase and provider agreements remain
user actions. The integration must fail closed without a key and remain EOD until
a separate licensed streaming integration verifies real-time entitlement.

Continuously running software requires an awake Mac or an always-on host.
The assistant conversation itself does not run ingestion after a turn ends.
Daily-bar strategies evaluate completed sessions, not every quote update.
All strategies remain experimental until real out-of-sample validation passes.

Research signal only — no order was placed.
