# Massive/Benzinga news connection — audit

Run 2026-09-08. Verifies whether the licensed news integration is
connected and how it is actually used, per your request.

## The short answer

**It is connected and technically functional, but two things are true at
once:**

1. **Benzinga-branded content specifically is stale on this API key** —
   confirmed, current as of today.
2. **By design, news can never enter trading decisions** — this is a
   hard, non-negotiable project rule (not a limitation to fix). Its
   *legitimate* use (human-readable context, LLM summaries) is real but
   narrower than "fully utilized" might imply: it currently never reaches
   the daily briefing/alert, only the dashboard's `/news` page and an
   on-demand summarize command.

## 1. Is the connection live?

**Yes — verified with a real, live fetch just now**, not from cached
state: `signalforge news ingest --tickers AAPL,META,MSFT --lookback-days 7
--limit 15` returned:

```
news: fetched 95, written 67, duplicates 28
(publishers: GlobeNewswire Inc., The Motley Fool, Zacks Investment Research)
```

Real headlines, real URLs, real publish timestamps, all through
`https://api.massive.com/v2/reference/news`, authenticated with your live
key (`market_data_api_key`, reused as a fallback since a separate
`news_api_key` isn't set — this is intentional existing behavior in
`MassiveNewsAdapter.__init__`, not a bug).

## 2. Is Benzinga specifically flowing?

**No — confirmed stale, twice, an hour apart, both today:**

```
[benzinga_news]
  ---- benzinga_news   200   err=empty   /v2/reference/news (publisher=Benzinga)
       STALE — 152 Benzinga articles in the sample but the newest is
       2026-06-18 (82d old); the feed is not currently delivering Benzinga
       (other publishers current to 2026-09-08). The account may show
       Benzinga active but this API key is not receiving it.
  OK   news_licensed_feed   200   /v2/reference/news
```

The endpoint itself responds (HTTP 200) and returns a real historical
sample of Benzinga articles — but the newest one is 82 days old, while
every other publisher on the same feed (Motley Fool, GlobeNewswire,
Zacks, etc.) is current to today. This is Signal Forge's own
already-built entitlement verifier (`signalforge providers verify`,
`data/entitlements.py`) correctly catching an account/plan-level gap: the
Massive account may show Benzinga as an active add-on, but this
particular API key is not actually receiving fresh Benzinga content.
`benzinga_ratings` and `benzinga_analyst_insights` are separately and
explicitly **403 not_authorized** ("upgrade your plan").

**This is not something in Signal Forge's control to fix in code** — it's
an account/subscription-entitlement gap on the provider side. If you want
current Benzinga content specifically, that requires resolving it with
Massive (their `/pricing`), not a config change here.

## 3. Where does news actually go once ingested?

Traced the real code paths, not assumptions:

| Surface | Uses news? |
|---|---|
| Dashboard `/news` page (`news_page` → `news_context`) | **Yes** — the only place a human sees ingested headlines, with an explicit Benzinga-availability banner |
| `signalforge news summarize` (on-demand LLM summary) | **Yes** — condenses a frozen list of already-retrieved headlines, cites every claim, ends with the mandatory `"AI explanation, not a trading instruction."` footer |
| `signalforge.research.candidates` / `signalforge.research.scan` / `signalforge.research.strategies` / `signalforge.risk` (the actual decision path) | **No — and structurally cannot be**, enforced by import-linter contract S12 |
| **The daily research briefing** (`research/briefing.py::build_briefing_facts`, the deterministic facts feeding the one alert type you asked to keep enabled) | **No.** Read in full: zero references to news, `NewsItem`, or anything news-related. The optional LLM narrative pass one layer up (`briefing.py::_maybe_narrative` → `llm.explain.explain_briefing`) also receives only the deterministic `facts` dict and rendered text — no news content flows into it either. |
| Scheduled polling (`scheduler.job_news_poll`) | **Never actually runs** in this environment: `research.news.poll_enabled` defaults `False`, confirmed still `False` in the live config. Manual `signalforge news ingest` is the only path that has ever populated `news_item`. |

**So: the honest answer to "is it fully utilized" is no, on two independent
axes** — (a) the specific Benzinga source is stale/not entitled on this
key, and (b) even the working multi-publisher feed never reaches the
automated daily briefing you actually see as an alert; it's only visible
if you manually open the `/news` page or run the summarize command.

## 4. A real defect found and fixed while verifying this

The import-linter contract meant to structurally guarantee "news never
drives a recommendation or risk decision" (S12) was checking a module
path, `signalforge.news`, **that does not exist anywhere in the source
tree**. It passed on every prior run only because import-linter can never
find an import of a module that isn't there — it was enforcing nothing.
The real news code lives at `signalforge.data.news_ingest`,
`signalforge.data.adapters.massive_news`, and
`signalforge.llm.summarize_news`. **Fixed**: the contract now names those
three real paths. `lint-imports` confirms no violation exists today
either way — this closes a real enforcement gap for the future, it did
not uncover a live breach.

## 5. What "fully utilized" cannot mean

To be direct about the one interpretation I will not implement without
you saying so explicitly: news — Benzinga or otherwise — **must never be
wired into `research.scan`, `research.candidates`, `research.strategies`,
or `risk`** to influence an entry, exit, size, probability, ranking, or
risk decision. That is a foundational, standing rule of this project (no
LLM/news on the decision path), independently enforced by import-linter
S12 and by every strategy module's own isolation. I have not changed
that, and would not without an explicit instruction to relax a
non-negotiable project rule — which I'd flag back to you rather than do
silently even then.

## What would make this a genuinely more useful resource, within that
constraint

1. **Resolve the Benzinga entitlement gap with Massive** (account/plan
   issue, not code) if Benzinga's specific coverage matters to you beyond
   the generic multi-publisher feed already working.
2. **Surface ingested headlines in the daily briefing/alert as read-only
   context** (e.g. "N new items for your qualified candidates' tickers,
   see /news") — a deterministic, LLM-free addition to
   `build_briefing_facts`, consistent with S3 (research stays LLM-free)
   and S12 (informational only, never decision-affecting). Not built
   here — flagging it as the concrete option if you want news to reach
   the briefing you actually read.
3. Optionally set `research.news.poll_enabled = True` if you want it
   ingested automatically on a schedule rather than only via manual `news
   ingest` — no code change needed, just the existing config flag.
