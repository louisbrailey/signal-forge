# Support request: Benzinga-published articles missing from /v2/reference/news since 2026-06-18

**Account:** [your Massive account email / account ID]
**Plan:** Paid subscription including Benzinga News entitlement ($99/mo tier)
**Product:** `/v2/reference/news` (unified news feed)

## Issue

Benzinga-published articles have not appeared in `/v2/reference/news` for **81 days**. The
feed itself works and other publishers are current; only Benzinga content has stopped.

- **Last Benzinga article observed:** 2026-06-18
- **Checked as of:** 2026-09-08 — still no Benzinga content, 81 days stale
- **Other publishers in the same feed, same window:** Motley Fool, GlobeNewswire, Zacks,
  Investing.com — all continuous and current through today, zero gap

This is a hard, dated cutoff, not a gradual thinning — Benzinga volume was normal and then
went to zero on 2026-06-18 across every ticker we sampled.

## Evidence

Sampled 6 liquid tickers (SPY, AAPL, NVDA, TSLA, MSFT, NFLX), 4 pages deep each
(`order=desc&limit=50`, following `next_url`), plus a dedicated 600-article deep-paginated
pull on AAPL and a full multi-month scan on SPY:

- 152 Benzinga-published articles found in the sample window; newest is dated 2026-06-18
- 0 Benzinga articles dated after 2026-06-18, across every ticker sampled
- Non-Benzinga publishers in the identical feed/window are current to 2026-09-08 (today)

Two Benzinga structured sub-products are also rejecting our key outright, which we believe
is a related entitlement gap on the same subscription:

- `GET /benzinga/v1/ratings` → **HTTP 403**: "You are not entitled to this data. Please
  upgrade your plan at https://massive.com/pricing"
- `GET /benzinga/v1/analyst-insights` → **HTTP 403**: same message

We also confirmed `?publisher=Benzinga` on `/v2/reference/news` is silently ignored
server-side — it has no filtering effect, so we cannot work around this by querying more
narrowly.

## Questions

1. Why did Benzinga-published articles stop flowing into `/v2/reference/news` on
   2026-06-18, while every other publisher in the same feed continued uninterrupted?
2. Is our Benzinga News entitlement still active on this API key? The account portal shows
   the subscription as active; the delivered content does not match.
3. Are `/benzinga/v1/ratings` and `/benzinga/v1/analyst-insights` included in our current
   plan, or is that a separate add-on? The 403 message ("upgrade your plan") suggests they
   were never included — please confirm which Benzinga products our $99/mo subscription
   actually entitles us to.

We are paying for Benzinga News specifically and would like it restored, or a clear
explanation of what changed on 2026-06-18.

Happy to provide our API key (out of band, not in this thread) or exact request/response
logs on request.
