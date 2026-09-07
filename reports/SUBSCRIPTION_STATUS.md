# Massive subscription integration — status

_Generated 2026-09-07. Entitlement batch `6fe6702cddb8` (live probe, recorded to
`entitlement_check`). Re-run with `signalforge providers verify`._

All three subscriptions share one Massive API key. It is sent only in the
`Authorization: Bearer` header, scrubbed from every stored string, and never
printed, logged, cached, or committed. Discord is presence/format-checked only —
no request is made.

---

## 1. Stocks Developer

| Field | Status |
|---|---|
| **Verified endpoints** | `daily bars` (`/v2/aggs/.../1/day`) → OK · `10y history` (same, 9y back) → OK · `5-min intraday aggs` (`/v2/aggs/.../5/minute`) → OK · `last trade` (`/v2/last/trade`) → OK · **`NBBO quotes` (`/v3/quotes`) → 403 not_authorized** |
| **History available** | 2016-09-02 → present (exactly ~10y; 2016-08-31 returns 403). Discovered by binary search, recorded per `ingestion_run`, not hard-coded. |
| **Latency** | daily bars `END_OF_DAY`; 10y history `HISTORICAL`; intraday 5-min + last-trade `DELAYED` (≥15 min). No real-time feed on this plan. |
| **Real vs simulated** | **Real.** `ingestion_run #1`: 60,432 daily bars, 25 instruments, 2016-10-17 → 2026-09-04, split/div-adjusted, raw payloads cached, idempotent re-ingest (12,500 skipped on re-run). |
| **UI coverage** | Overview, Scanner, Candidate Detail (sparkline + bar count + freshness), Portfolio, Strategy Lab, Briefing. Every equities chart/scan is labelled `DELAYED` / `END-OF-DAY`; `.is_live` is false for all of them (S7 contract). |
| **Test coverage** | `tests/data/test_massive.py` (10), `test_ingest.py`, `test_pipeline_upgrade.py` (2), `test_entitlements.py` (5), `test_providers_options_news.py`, S7 latency-labelling safety test. |
| **Unsupported / gaps** | NBBO bid/ask quotes (403 — not on this plan). No real-time trades/quotes. `session_completeness` validation fails on the FB→META ticker change (90 missing bars Jan–Feb 2022) and XLC's 2018 launch — both explained, both legitimate, recorded in `data_validation_report`. |

## 2. Options Developer

| Field | Status |
|---|---|
| **Verified endpoints** | `contracts` (`/v3/reference/options/contracts`) → OK · `chain snapshot` (`/v3/snapshot/options/{u}`) → OK · `contract snapshot` (`/v3/snapshot/options/{u}/{c}`) → OK · `historical aggs` (`/v2/aggs/ticker/O:.../1/day`) → OK · `delayed trades` (`/v3/trades`) → OK · `last trade` (`/v2/last/trade`) → OK · `greeks` (snapshot field) → OK · `implied_volatility` (snapshot field) → OK · `open_interest` (snapshot field) → OK · **`NBBO bid/ask quotes` (`/v3/quotes`) → 403 not_authorized** |
| **History available** | Contract reference + historical daily aggregates per contract are entitled (`HISTORICAL`). No bulk historical options store has been ingested yet — see gaps. |
| **Latency** | trades / last-trade / greeks / IV → `DELAYED`; `open_interest` → `END_OF_DAY`; contract reference + per-contract aggs → `HISTORICAL`. Nothing live. Each field is labelled independently in the snapshot row; a field being present is never taken to mean it is live. |
| **Real vs simulated** | **Real chain data** (bounded ingest just run): 878 SPY contracts + 878 delayed snapshots, exp 2026-09-30…2026-10-16, strikes 709–831, vendor greeks + IV present on all 878. **Simulated:** payoff / break-even / max-loss / time-decay in the learning UI are Black-Scholes computations from those inputs, clearly marked "computed, not a vendor quote". |
| **UI coverage** | New **`/options` — Education & Simulation** page: chain explorer (select underlying/expiration; type/strike/exp/last-delayed/day-close/vol/OI-EOD/IV/Δ/Θ/break-even), contract detail (bid/ask row reads *"not entitled (spread estimated)"*), paper simulator for long call, long put, covered call, cash-secured put (payoff SVG + entry cost / max loss / max gain / break-even + Black-Scholes time-decay table), and a red risk-warning panel (expiry, liquidity/spread, assignment/ex-div, event risk, education-only). |
| **Test coverage** | `tests/options/test_options_math.py` (8: Black-Scholes price/greeks/IV, all four simulators), `tests/data/test_providers_options_news.py` (6: offline adapter parsing, DELAYED labels, no secrets), `tests/app/test_options_news_ui.py` (route smoke + quote-caveat + payoff math), `tests/data/test_entitlements.py` (per-endpoint classification). |
| **Unsupported / gaps** | NBBO bid/ask quotes (403 — spread is *estimated*, never observed). **Not yet built:** a staged, bounded *historical* options-aggregates ingester (`/v2/aggs/ticker/O:.../1/day`) with its own validation pass — the entitlement is confirmed and the adapter path exists, but no scheduled backfill is wired. By design: no options recommendations, no options alerts, no naked/uncovered/margin/spread/0DTE, no execution. |

## 3. Benzinga News

| Field | Status |
|---|---|
| **Verified endpoints** | `/v2/reference/news` (the licensed feed; Benzinga news, when entitled, is delivered *through* it — there is no `/benzinga/v1/news` path: it 404s with an empty body) → OK · **`/benzinga/v1/ratings` → 403 not_authorized** · **`/benzinga/v1/analyst-insights` → 403 not_authorized** (structured Benzinga sub-products; a separate entitlement, not active) |
| **Benzinga-news check** | **Content + freshness.** The verifier samples `/v2/reference/news` across 6 liquid tickers, 4 pages deep, and requires a Benzinga-published article ≤ 10 days old (a lapsed feed still returns *old* Benzinga items). **Result (batch `78360da4cd70`): NOT available — STALE.** 152 Benzinga articles in the sample but the newest is **2026-06-18 (81 days old)**; every other publisher is current to 2026-09-07. The API key is not currently receiving Benzinga, regardless of what the account dashboard shows. |
| **History available** | Licensed feed: recent headlines per ticker (`order=desc`, vendor-paginated). No dedicated Benzinga archive endpoint. |
| **Latency** | `DELAYED`. |
| **Real vs simulated** | **Real, not Benzinga.** Publishers currently flowing: The Motley Fool, Zacks, GlobeNewswire, Investing.com — no live Benzinga. Each item stores real publisher, URL, publish time, retrieval time, category, ticker tags, dedupe key. |
| **UI coverage** | **`/news`** page (timeline, ticker filter) + compact partials on Overview and Candidate Detail. Label: *"Licensed multi-publisher feed (Benzinga not currently entitled on this key)"*, with the exact verifier finding shown (STALE, newest Benzinga 2026-06-18, 81d old) and the check timestamp. When the feed starts delivering fresh Benzinga, the label auto-switches to *"Benzinga News (licensed primary) + other licensed publishers"* (covered by `test_news_context_label_switches_when_benzinga_is_live`). No item is ever relabelled as Benzinga. |
| **Test coverage** | `tests/data/test_entitlements.py` — `test_benzinga_news_available_only_when_feed_is_currently_delivering_it` (fresh → available/DELAYED; 81d stale → not available; none → distinct message). `tests/app/test_options_news_ui.py` — page states the stale limitation; label switch when live; symbol filter. `tests/data/test_providers_options_news.py` — dedupe + publisher labelling offline. |
| **Unsupported / gaps** | **Benzinga is NOT live on this API key.** `/benzinga/v1/{ratings,analyst-insights}` → 403; `/v2/reference/news` carries no Benzinga article newer than 2026-06-18. If the account truly has Benzinga, the entitlement has not propagated to this key (or it is a different key). To confirm once fixed: `signalforge providers verify` — `benzinga_news` flips to `available` and the UI label switches automatically. LLM summaries stay gated (citations + timestamps + "AI explanation, not a trading instruction"); news never creates, ranks, modifies, or overrides a recommendation, risk limit, entry, exit, or size (import-linter **S12**). |

## 4. Discord

| Field | Status |
|---|---|
| **State** | Notifications **OFF** (default). Webhook presence/format-checked only — never contacted during verification. |
| **UI / control** | `signalforge notify test-discord --yes` sends one test message (explicit confirmation required). Footer *"Research signal only — no order was placed."* appended to every message; webhook URL never logged. |
| **Allowed uses** | System-health pings, post-close briefing, and — later, only after genuine out-of-sample validation passes every gate — validated stock-research alerts. **Never** option-trade alerts. |
| **Gating** | Stays off until all entitlement + UI tests pass and a strategy clears validation; `alerts_enabled` + `auto_simulate` both default false. |

---

## Test suite

`265 passed` (`pytest -o addopts=""`). Clean: ruff, black, mypy (`127` files),
import-linter (**6/6** contracts incl. S11 options-not-on-decision-path, S12
news-not-on-decision-path), detect-secrets.

## One-line summary

| Subscription | Entitled | Key limitation |
|---|---|---|
| Stocks Developer | ✅ bars, 10y history, delayed intraday, delayed last-trade | ✗ NBBO quotes (403); no real-time |
| Options Developer | ✅ contracts, chain, snapshots, historical aggs, delayed trades, greeks, IV, OI | ✗ NBBO bid/ask (403); historical-aggs backfill not yet wired |
| Benzinga News | ⚠️ generic multi-publisher feed only | ✗ dedicated Benzinga (404), ratings + analyst-insights (403) |
| Discord | ✅ configured, OFF by design | held until validation passes |
