# Methodology & data entitlement

Signal Forge is **research / paper-trading / education only**, with one narrow,
written exception recorded on 2026-09-12 in `docs/decisions/0003-execution-layer.md`:
a `signalforge.execution` package may submit orders to a broker's **paper/sandbox**
endpoint, disabled by default and armed only by an audited per-strategy-version
operator ceremony. **No such code exists yet.** Outside that one package there is no
brokerage connection, order placement, or trade mirroring anywhere in the codebase,
and no module of the research/backtest/paper/alerts/LLM/agent/app stack may import it
(import-linter contracts **S1**, **S15a**, **S15b**). No LLM can reach an order. No
real-money endpoint is authorised. Everything in this document — the entitlement, the
pipeline, the evaluation method, the limitations — describes the research path, which
that ADR leaves unchanged: no promotion gate or threshold is weakened by it.

## Verified provider entitlement

Checked with `signalforge providers verify` against the live key (secret-safe —
the key travels only in the Authorization header and is scrubbed from every
output):

| Feed | Status | Notes |
|---|---|---|
| Stocks daily bars | **available** | Split-adjusted (`adjusted=true`). Provider API is Polygon-shaped. |
| Stocks deep history | **~10 years** | Binary-searched: oldest servable `from` ≈ **2016-09-02** (10.0y back); 403 `NOT_AUTHORIZED` at ~10.5y. Discovered per run — never hard-coded. |
| Options contracts + chain snapshot | **available** | Delayed (>= 15 min). Vendor Greeks + IV present for near-the-money strikes; open interest is end-of-day. Education/simulation only — no options recommendations or alerts. |
| News (`/v2/reference/news`) | **available** | General licensed publisher feed (Benzinga, Zacks, Motley Fool, …); items labelled by actual publisher. A Benzinga-*only* entitlement is **not** confirmed. Read-only; never on the decision path (S12). |
| Real-time / streaming | **not entitled** | All prices are labelled `END_OF_DAY` or `DELAYED`. Nothing is ever labelled live. |

## Historical-data pipeline

`signalforge data discover-history | ingest-history | validate | coverage`.

- **Discovery**: `discover_history_depth()` binary-searches the oldest servable
  date; ingestion starts with a +45-day margin inside it so routine runs never
  trip the 403 boundary.
- **Ingestion** (`ingest_daily_history`): incremental and **idempotent** — a
  re-run only fetches sessions not already stored (`(instrument, session_date,
  source)` unique). **Resumable** via `resume_run_id`: symbols already completed
  are skipped. Checkpoints after every symbol. Per-symbol gap detection against
  the XNYS calendar.
- **Retry / backoff**: the adapter retries 429 / 5xx / network errors up to 5
  times with exponential backoff, honours `Retry-After`, and stays responsive to
  the kill switch. Request spacing is configurable
  (`MARKET_DATA_MIN_REQUEST_SPACING_S`).
- **Audit** (`ingestion_run` table): provider, feed, kind, requested window,
  adjusted flag, discovered earliest date + probe time, actual coverage
  first/last, bars written/skipped, per-symbol ok/failed, gaps.
- **Raw vs normalized**: verbatim provider JSON is kept in `raw_payload_cache`;
  normalized bars in `ohlcv_daily` carry `source`, `latency_category`,
  `is_simulated`, `ingested_at`, `quality_flags`.
- **Validation** (`validate_daily`, persisted to `data_validation_report`):
  symbol coverage, chronological order, duplicate sessions (list + DB group-by),
  missing sessions vs XNYS, OHLCV relations, split/dividend back-adjustment
  behaviour, timezone/date consistency.

### Current coverage (`massive`, ingestion_run #1)

- **2016-10-17 → 2026-09-04**, 60,432 daily bars, **25 / 25** symbols.
- 23 symbols: full ~2,485 sessions.
- **META: 1,212 sessions from 2021-06-30** — `META` ticker history only, not the
  full `FB` series (the ticker was renamed June 2022). Known discontinuity.
- **XLC: 2,065 sessions from 2018-06-19** — the ETF's actual launch date.
- Validation currently **FAILS** on `session_completeness` because of META's
  gapped series; every other check passes.

## Evaluation method (frozen strategy)

`signalforge backtest-extended`. The strategy rules, thresholds, scoring, and
sizing are **unchanged** from the prior baseline — results are directly
comparable and **no parameter was tuned in this phase**.

- **Leakage-free**: the backtest engine only ever passes `series.head(t)` to a
  signal; entries fill at `t+1` open; costs (3 bps slippage + half-spread) are
  baked into fills.
- **Segmentation**: train + **rolling walk-forward** (4 contiguous folds) over
  the pre-sealed span, and a **sealed final-test window** (the most recent
  365 days) reported separately and evaluated once.
- **Regime breakdown**: trades bucketed by the SPY-derived regime label on their
  entry date (bull/bear × high/low vol, plus range-bound). With 10 years of real
  data these buckets now include 2018-Q4, the 2020 crash, and the 2022 bear.
- **Benchmark**: SPY buy-and-hold over the same span.

## Limitations (unresolved)

- **Survivorship bias**: the universe is a *fixed, hand-picked list of large-cap
  survivors*. No delisted names, no point-in-time index membership. Real-world
  results would be worse. The `universe_filters` screen operates on this list; it
  does not expand it (no "all liquid US equities" feed).
- **Corporate actions**: bars are split-adjusted only. No dividend adjustment, no
  separate corporate-action feed; the earnings-window exclusion had nothing to
  act on for the deep history. MEDIUM_SWING holds absorb dividend gaps as losses.
- **Commission** is modelled as zero (`commission_per_share=0`); slippage +
  half-spread are applied.
- **No forward / live-paper validation** has accumulated yet.
- Options Greeks/IV shown from `signalforge.options` simulators are **computed
  locally** (Black-Scholes), clearly labelled — not vendor values.

## Results summary (10-year, net of costs)

Full detail: [`reports/EXTENDED_HISTORY_RESULTS.md`](../reports/EXTENDED_HISTORY_RESULTS.md).

| strategy | full total ret | CAGR | Sharpe | max DD | sealed test | walk-forward |
|---|--:|--:|--:|--:|--:|---|
| SPY buy & hold (benchmark) | **+262.6%** | — | — | — | +18.7% | — |
| relative_strength.medium_swing | +114% | 8.0% | **1.33** | 17.8% | +8.3% (Sh 1.31) | all 4 folds positive |
| trend_continuation.medium_swing | +155% | 9.9% | 1.12 | 28.5% | **+1.1% (Sh 0.17)** | decays; edge doesn't persist |
| trend_continuation.short_swing | +124% | 8.5% | 1.00 | 27.8% | +21.3% (Sh 1.86) | +15 / −0.5 / −1 / +62 (unstable) |
| mean_reversion.short_swing | **−20.6%** | −2.3% | −0.49 | 37.9% | +8.4% (small n) | 3 of 4 folds negative |
| volatility_breakout.short_swing | +16.8% | 1.6% | 0.56 | 6.4% | −0.7% (10 trades) | positive but tiny & decaying |

**No frozen strategy beats the passive benchmark.** Performance is a
bull-market phenomenon (bear/high-vol regimes are unprofitable or barely
traded). Every strategy remains `experimental`, alert-ineligible, and
non-promotable.
