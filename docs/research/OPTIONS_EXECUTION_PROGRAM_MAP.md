# Options + Live Execution — Program Map

Status: **MAP ONLY.** Nothing in this document is implemented. No code, config, schema,
contract, or gate was changed to produce it. Every claim is labelled **FACT** (with a
`file:line` or a read-only query behind it) or **HYPOTHESIS** (a design proposal that
nothing in the repo yet establishes).

Written: 2026-09-11. Revised: 2026-09-11 (rev 2, after an adversarial verification pass that
re-checked every quantitative claim against the source and the live DB; see the Critic
responses appendix for what changed and why). Repo: `/Users/louisbrailey/signal-forge`.
Produced by read-only mapping passes against a live paper-probation DB
(`data/signalforge.sqlite`) using SELECTs only.

This document is **not financial advice** and contains none. Where it states market
structure or regulatory facts (PDT, options approval levels, margin, settlement) it does so
as general information the operator must verify with their own broker. Where it states a
numeric risk limit, that number is a **grid centre point for evaluation**, never a
recommended setting — see §3.2.

---

## 0. Operator summary

### 0.1 The three facts that bound everything

**B1 — Paper-first evidence discipline is already law here, and options do not get an exception.**
FACT: the promotion ladder is eleven deterministic gates (gate 0 through gate 10) whose
thresholds live in version-controlled config (`config/research.py:96-126`
`PromotionThresholds`) and are folded into `config_hash`, so no gate can be weakened without
a visible diff (`research/promotion.py`). FACT: gate 0 already hard-fails a whole horizon
class outright — `spec.horizon is Horizon.INTRADAY` auto-fails with "no intraday bar history
is ingested" (`promotion.py:892-901`) — which is the exact precedent for an options gate 0.
FACT: the binding rules of engagement (`docs/research/STRATEGY_COMPLETION_MAP.md` §1 R1-R10)
say sealed data may inform *disposition* but never *design* (R1); only a version bump earns a
fresh sealed look (R3); `PromotionThresholds` and `CostModel` are frozen for the program and
gates may only be made *more* searching, never weaker (R4); every evaluated variant including
abandoned ones must be disclosed (R5); live paper is the confirming test, never the promoting
one (R8). None of R1-R10 is equity-specific in mechanism. They carry to options unchanged.

**B2 — Live execution is gated behind explicit per-strategy arming, and nothing is armed by default.**
FACT: `StrategyStatus` has exactly three values — EXPERIMENTAL, PAPER_APPROVED, DISABLED
(`domain.py`). There is no ARMED state anywhere. FACT: the existing auto-simulate guard
(`paper/ledger.py:490-515` `assert_auto_simulate_allowed`) is the house pattern for a
fail-closed entry point: it requires the setting ON **and** every quality gate PASSED **and**
`inst.instrument_type in ("stock","etf")` **and** `ver.status is PAPER_APPROVED` **and** an
exact five-part approved-scope match, raising `AutoSimulateForbidden` otherwise
(`ledger.py:492-505`). Arming for live execution must be a *new*, separate, revocable state
layered **on top of** PAPER_APPROVED — never a fourth enum value that some existing code path
might treat as "approved enough".

**Correction carried into §6.3 (FACT, and it is load-bearing):** that guard is on the
*automatic* path only. `accept_candidate` (`paper/ledger.py:129-160`) — reachable directly from
the CLI at `cli.py:1158-1165` with no guard — checks only `ensure_not_engaged()`, that the
direction is not AVOID, and that the risk width is non-zero. It checks **neither**
`quality_gate_status`, **nor** `StrategyVersion.status`, **nor** approved scope, **nor**
`instrument_type`. So an ACCEPTED `PaperTrade` is *not* by itself evidence that anything was
gated. Any execution design that treats "an ACCEPTED PaperTrade exists" as the authorisation
predicate inherits that hole. See §6.3.

**B3 — The operator supplies credentials and chooses the broker; no credential ever enters the repo, and no LLM ever decides an order.**
FACT: today every secret comes from env/`.env` via pydantic `SecretStr` in
`config/settings.py`; a repo-wide grep for any keychain mechanism returns zero hits — macOS
Keychain support would be wholly new. FACT: `audit.py::record()` already redacts `SecretStr`
and any dict key matching `/(?i)(api[_-]?key|secret|password|token|authorization|bearer|credential)/`
via `observability/logging.py::redact()` — directly reusable. FACT: import-linter contract S3
forbids `signalforge.research`, `.risk`, `.backtest`, `.paper` from importing `signalforge.llm`
(`pyproject.toml:179-186`), and `evaluate_promotion` is pure numpy/sqlalchemy with boolean
gates (`research/promotion.py`). The LLM boundary the operator asked for is *partly* structural
today — but S3 constrains only the research→llm direction. **FACT: nothing in the current
contract set would stop `signalforge.llm`, `signalforge.agents`, or `signalforge.app` from
importing a future `signalforge.execution`.** The guarantee therefore requires a *new* contract
in the opposite direction, not an inherited one. See §6.8 step 3.

### 0.2 What exists

| Area | State | Evidence |
|---|---|---|
| Equity research pipeline | Built and running; 11 gates, sealed tests, approval scope, paper probation live | `research/promotion.py`, `research/approval_scope.py` |
| Sealed-look counting | **Exists and is automatic**, per strategy family | `promotion.py:615` `count_sealed_looks`, `:634` `sealed_look_ledger`, `:888`, `:1293`, `cli.py:1287-1291` |
| Options **data schema** | Three tables exist and are migrated | `db/models/market.py:240-318`; migration `20260907_1654-c0b787616343` |
| Options **ingest/backfill** | Two code paths exist, `backfill_enabled=False` by default | `data/options_ingest.py`, `data/options_backfill.py`, `config/research.py:193-215` |
| Options **math** | Black-Scholes price/greeks/IV (with a dividend-yield input) + 4 payoff simulators | `options/blackscholes.py:48-101`, `options/simulators.py` |
| Options **strategy / backtest / promotion** | **Does not exist.** Zero lines. | `backtest/engine.py` is single-leg price-only |
| Options **paper mechanics** | **Does not exist**, and is hard-blocked | `paper/ledger.py:496-500` |
| Live execution | **Does not exist**, and is structurally banned in five places | S1 + Ruff banned-api + `tests/safety/test_s1_no_broker_surface.py` |

FACT: the options module declares its own scope ceiling in its docstring —
"There is no options execution path anywhere in this package... Naked short options,
uncovered calls, margin-dependent strategies, 0DTE alerting, and spreads are intentionally
absent" (`options/__init__.py:1-11`). Repurposing it is a deliberate scope change to a stated
contract, not an incidental refactor.

### 0.3 What is missing (the five real blockers, in dependency order)

1. **Options data depth.** FACT (live DB): `option_contract` = 888 rows, all SPY, expirations
   2026-09-08→2026-10-16. `option_aggregate_daily` = 110 rows, 10 contracts, all SPY, sessions
   2026-07-31→2026-09-04 (~5 weeks). `option_quote_snapshot` = 878 rows, **all sharing one
   `as_of` = 2026-09-07 18:30:00** — a single one-off pull, not a series. FACT: gate 0 already
   enforces `MIN_PRESEALED_DAYS = ceil(200*365.25/252)+60 = 350` calendar days plus
   `sealed_window_days=365` ≈ **715 days minimum** (`promotion.py:105,940`;
   `config/research.py:126`). Current options coverage fails that by roughly two orders of
   magnitude on breadth and ~20x on depth.
2. **No daily IV/greeks/OI series.** FACT: `OptionAggregateDaily` carries only
   OHLCV+vwap+transactions — no IV, greeks, OI, or bid/ask columns (`market.py:290-318`).
   IV/greeks/OI exist only in the single-timestamp `OptionQuoteSnapshot`. Nothing in the
   codebase schedules a repeated dated snapshot capture. A delta- or IV-rank-driven strategy
   has no historical input today.
3. **No NBBO — on *either* asset class.** FACT (`entitlement_check`, 7 distinct `batch_id`s,
   2026-09-07 18:13 → 2026-09-09 06:34): `/v3/quotes/{O:contract}` (options bid/ask) returns
   http_status 403, `error_category='not_authorized'` in **7 of 7** batches — **and
   `/v3/quotes/{sym}` (equities NBBO) returns 403 `not_authorized` in 7 of 7 batches as well.**
   Everything else probed returns 200: `/v3/reference/options/contracts`,
   `/v3/snapshot/options/{underlying}` (incl. greeks / IV / open_interest),
   `/v3/snapshot/options/{underlying}/{contract}`, `/v2/aggs/ticker/{O:contract}/...`,
   `/v3/trades/{O:contract}`, `/v2/last/trade/{O:contract}`.
   **This materially changes §0.4 and §5.2.** The missing-quote problem is *not* an
   options-specific handicap that a proven equity pipeline is lending discipline to — **both
   streams are modelled-spread-only, and neither has ever been validated against an observed
   spread.** The equity side's flat 11 bps is exactly as unverified as any options spread model
   this document proposes. FACT: `docs/CAPABILITY_MATRIX.md` records the same for options:
   greeks/IV/trades DELAYED, OI END_OF_DAY, NBBO UNSUPPORTED.
4. **No multi-leg anything.** FACT: `EntrySignal`/`SimTrade` (`backtest/engine.py:29-60`) model
   one instrument, one direction, one stop, one target. `PaperOrder`/`PaperFill`/`PaperPosition`
   (`db/models/paper.py:47-97`) are each 1:1 with one `instrument_id`. `Candidate`
   (`db/models/research.py:90-131`) is one instrument, one entry zone, one target.
   `Instrument.instrument_type` carries the code comment `# stock | etf` (`market.py:35`).
   `CostModel` (`backtest/costs.py:11-35`) is per-**share**.
5. **A standing committed decision says no.** FACT: `docs/PORTFOLIO_RESEARCH_ROADMAP.md`
   lines 27-67 ("Non-negotiable boundaries", no draft marker) states "No brokerage, no order
   placement, no trade mirroring, anywhere" and "No brokerage/Webull/order-placement
   integration is in scope for any module, at any phase. This roadmap does not create one and
   does not plan to." This directly contradicts the operator's new plan and must be
   **explicitly superseded in writing**, not routed around. See §6.8.

### 0.4 Honest evidence status of the equity strategies

Read this before treating equities as a proven template.

- FACT: exactly **two** strategies are PAPER_APPROVED — `trend_continuation.short_swing`
  v0.1.0 (sealed test id 11, +0.2982R, n=109) and `relative_strength.medium_swing` v0.1.0
  (sealed test id 14, +0.2935R, **n=16**) (`docs/PAPER_PROBATION_ACTIVATION.md`,
  `STRATEGY_COMPLETION_MAP.md` §0).
- FACT: v5 (`relative_strength.medium_swing`) sealed evidence is n=16, implied per-trade
  sd 1.484, SE 0.371R — the point estimate sits **0.79 standard errors from zero**. The
  completion map itself calls this "the weakest evidence supporting anything currently live"
  (§0.3).
- FACT: the bootstrap CI assumes iid trades; 15 of the 24 universe symbols are ETFs, several
  containing the others. The map's own §4.3 states "Every CI here is too narrow and every
  required-n is a lower bound" and recommends a clustered/block bootstrap as a diagnostic —
  **not yet computed** for either approved strategy.
- FACT (corrected, rev 2): the cost model is commission $0 and `slippage_bps=3.0`, plus a
  **5.0 bps spread assumption that enters through two structurally different doors**:
  - `backtest/engine.py:90` `spread_bps: float = 5.0` is a **keyword-argument default** on
    `run_backtest`, overridable per call site. It is *not* hard-coded.
  - `paper/ledger.py:50` `_NOMINAL_SPREAD_BPS = 5.0` is a module constant with **no override
    path** — this is the genuinely hard-coded one, and it prices every live paper fill
    (`ledger.py:166-171`).

  Both give 11 bps round trip, universe-independent — the same figure for SPY and a thin name.
  Described in-repo as "optimistic outside mega-caps". **Consequence for §5.2 gate 4b:** the
  dual-spread pass is *cheap* on the backtest side (the parameter already exists; it is a
  call-site/config plumbing job) and needs a constant lifted into config on the paper side.
  This is not an engine change.
- FACT (corrected, rev 2): **look counting is not manual and is not absent.**
  `promotion.py:615 count_sealed_looks(session, strategy_name)` counts sealed tests per
  strategy **family** (keyed on `Strategy.name`, across every version and every snapshot);
  `promotion.py:634 sealed_look_ledger(...)` enumerates them; `promotion.py:888` captures
  `k_prior` before the run; it is surfaced as gate-9 evidence under the key
  `sealed_look_ledger` (`:1293`), carried on `PromotionResult.sealed_look_prior` (`:150,174`),
  and printed by `cli.py:1287-1291`. It is derived from `strategy_sealed_test` on every read,
  so it cannot drift from reality.
- FACT (corrected, rev 2): **there is no single global k.** Read-only query against
  `data/signalforge.sqlite`:

  ```
  select count(*) from strategy_sealed_test                        -> 22
  select count(distinct dataset_snapshot_id) ...                   ->  5
  per family (join strategy_version -> strategy, group by name):
      mean_reversion.short_swing         5
      relative_strength.medium_swing     4      <- LIVE
      trend_continuation.medium_swing    5
      trend_continuation.short_swing     4      <- LIVE
      volatility_breakout.short_swing    4
  ```

  Both **live** strategies stand at k=4, not 5. Any multiplicity statement must name the
  family and read `count_sealed_looks`; an aggregate "k" is meaningless here.
- FACT: `paper_trade`, `paper_position`, and `strategy_health` all have **0 rows** (re-verified
  rev 2). Probation has been ON since 2026-09-10 20:00 UTC and has produced zero live paper
  trades to date.
- FACT: a real incident already happened — adding an `agents` section to `ResearchConfig`
  silently changed the config hash used in the five-part scope match, causing live scans to
  match no approved scope, masked only because those scans produced zero qualified candidates
  (`PAPER_PROBATION_ACTIVATION.md`, 2026-09-11 write-up; fixed by scoping the hash to
  signal-shaping fields only — commit `0cc4cf4`).

**HYPOTHESIS (recommendation):** the equity side is a proven *methodology*, not yet a proven
*edge*, and — given blocker 3 — its cost realism is exactly as unvalidated as options'. Cite it
as the discipline template; do not cite it as evidence that the system makes money, and do not
cite it as evidence that the *cost model* is sound. One concrete consequence for sequencing:
the operator should accumulate live paper evidence on the two approved equity strategies **in
parallel with** options build-out, and should not let "equities are live" function as the
argument for arming anything.

---

## 1. Options data plan

### 1.1 What must be ingested

**HYPOTHESIS (the coverage target), bounded by FACTs below.**

| Dimension | Proposal | Why |
|---|---|---|
| Underlyings | Tier A: SPY, QQQ, IWM (index ETFs, tightest spreads, full weekly chains). Tier B: 6-10 mega-cap singles from the already-approved equity universe, **restricted per §2.4a (dividend handling)**. | FACT: `OptionsConfig.underlyings` already defaults to `(SPY,QQQ,IWM,AAPL,MSFT,NVDA)` (`config/research.py:193-215`) — Tier A+B is a modest widening, not a new concept. Keeping underlyings ⊆ the approved equity universe means regime labelling, liquidity filters, and event filters reuse existing `OHLCVDaily` with zero new machinery. |
| Expiries | Every **monthly** (3rd-Friday) expiry cycle over the history window, plus the weekly nearest the 30-DTE target within each cycle. Not every weekly. | Monthlies are the liquid series and give one clean, non-overlapping trade cycle per month — ~12/yr/underlying, which is what makes the trade-count arithmetic in §5.3 work. |
| Strike band | ±15% of the **point-in-time** underlying close for that cycle's entry date, plus an absolute floor of ≥7 strikes either side. | FACT: default `backfill_strike_pct_band=0.15` already exists; the change needed is *point-in-time*, see the blocker in §1.3 D2. |
| DTE window at entry | 21-60 DTE (entry near 30-45). | Matches `Horizon.POSITION` (2-6 months, `domain.py:18`), the one declared horizon with **zero** registered strategies — FACT, confirmed in memory and by the registry sweep. |
| History depth | 3 full years minimum; 5 preferred. | FACT: gate 0's floor is ~715 calendar days before gates 1-9 run at all (`promotion.py:105,940`). 2 years is the bare minimum and leaves no margin; 3 gives one extra year of pre-sealed regime variety. |
| Per-day fields | Contract OHLCV (exists) **plus** a per-session IV input per contract, with a recorded `iv_source` (§1.3 D5). | FACT: the IV/greeks/OI daily series does not exist anywhere today (§0.3 item 2). |

### 1.2 API calls and time — what is actually known

- FACT: the only rate figure documented anywhere in the repo is the **equities Basic tier**:
  5 calls/min, enforced as `market_data_min_request_spacing_s = 12.1` (`config/settings.py:53`).
- FACT: `options_api_key` (`config/settings.py:59`) falls back to `market_data_api_key`
  (`massive_options.py:107-113`) — **by default options traffic shares the equities account's
  rate budget**.
- FACT: `docs/MARKET_DATA_SETUP.md` is 28 lines, documents only equities plans (Basic $0 /
  5 calls-min / 2yr; Starter $29 / 15-min delay; Advanced $199 / real-time), and line 15 says
  "Do not buy news/options add-ons yet". **No options plan price, rate limit, or history depth
  is documented anywhere in the repo.**
- FACT: `massive_options.py::_get` (lines 116-140) makes a **single HTTP attempt** and raises
  `AdapterError(rate_limited=True)` immediately on 429. There is no sleep, backoff, or retry
  anywhere in the file. By contrast the equities adapter self-paces at 12.1s and retries with
  exponential backoff up to `_MAX_ATTEMPTS` (`massive.py:109-162`).
- FACT (call shape): one `fetch_contracts` call per underlying (paginated, `_MAX_PAGES=20` ×
  1000 results, `massive_options.py:35,166`), then one `fetch_option_aggregates` call per
  selected contract covering that contract's whole date range (limit 50000, no pagination
  needed for one contract's life) (`options_backfill.py:249-441`).

**HYPOTHESIS (sizing arithmetic), explicitly bounded — do not quote this as a plan cost.**
A 10-underlying × 36-monthly-cycle × ~15-strikes-per-side × 2-rights target is on the order of
10 × 36 × 30 = **~10,800 contract-aggregate calls**, plus ~10 × 36 = 360 reference/chain calls.
At the only known pacing figure (12.1 s/request) that is **≈37 hours of serial wall clock**,
and the options adapter does not itself enforce that pacing, so an unpaced run will start
throwing unretried 429s long before completion. The smoke test is the sanity check on the
denominator: FACT — `reports/OPTIONS_BACKFILL_SMOKE_TEST.md` (production run 2026-09-08) found
**276 raw eligible contracts for SPY at only ±2% band over only 6 expirations**. At the shipped
±15% default, one liquid underlying for one cycle is already a large pool. The "10,800" figure
is therefore a floor, not a ceiling.

**Consequence (HYPOTHESIS):** the backfill must be built as a resumable, self-pacing,
multi-session job with progress persisted per (underlying, cycle), not as a single CLI
invocation. This is real engineering, and it precedes every other options work item.

### 1.3 Required code changes before any real backfill (all FACT-grounded blockers)

| # | Blocker | Evidence | Fix (HYPOTHESIS) |
|---|---|---|---|
| D1 | Lookback clamped to 365d, not overridable | `options_backfill.py:205-206`: `win_start = max(start, today - timedelta(days=caps.lookback_days))`; `cli.py:341-427` exposes no `--lookback-days`; `ResearchConfig` is a nested pydantic model with no `env_nested_delimiter` (`config/settings.py`), so it is not env-settable either | Add `--lookback-days` to the CLI **and** make `OptionsConfig` env-addressable. A source edit to reach 3 years is not acceptable provenance for a promotion-grade dataset. |
| D2 | Strike band centred on **today's** price for the whole run | `options_backfill.py:77-88` `_reference_price` = most recent stored `OHLCVDaily.close`; single value per underlying per run | Per-cycle point-in-time reference: for each expiry cycle, look up the underlying close on that cycle's entry date and centre the band there. Without this, a 3-year backfill systematically misses what was actually ATM in 2023. This is a **design** fix, not a config knob. |
| D3 | `contracts_per_underlying=40` cap is per-underlying across **all** expirations | `options_backfill.py:99-162`; default 40 (`config/research.py:193-215`) | Make the cap per-(underlying, expiry-cycle). Today the cap — not the strike band or expiry count — silently decides coverage, so an operator asking for "N underlyings × monthly expiries × a band" gets a small ATM-ranked slice with no error. Silent under-coverage is the worst failure mode for an evidence pipeline. |
| D4 | Options adapter has no pacing/retry | `massive_options.py:116-140` vs `massive.py:109-162` | Port the equities adapter's spacing + exponential backoff into the options adapter before any large run. |
| D5 | No dated IV/greeks/OI series, and no code path that would build one | `market.py:290-318` (no IV/greeks/OI on aggregates); `options_ingest.py` writes snapshots but not keyed by `session_date`, and nothing schedules repeated pulls | Either (a) a new `OptionGreeksDaily` table + a scheduled daily snapshot capture (builds forward from today only — useless for a 3-year backtest), or (b) compute greeks/IV locally from the contract's own daily close + the underlying's close via `options/blackscholes.py`. **(b) is the only path that yields history.** See §2.4b for the **circularity this creates and how it is resolved** — (b) inverts IV *from a print*, so it produces nothing for a contract that did not print. Whichever is used must be recorded per evaluation (see gate 0.e in §1.5). |
| D6 | `options_ingest.py` writes no `IngestionRun` row | Confirmed by query: `ingestion_run WHERE kind LIKE '%option%'` returns exactly 4 rows, ids 2-5, all `kind='options_agg_backfill'`, all `symbols_requested=['SPY']` | Every options data path must write an `IngestionRun` with gaps_json. Provenance is a gate-8 input; a path that leaves no trace cannot be audited. |
| D7 | No options corporate-action handling | `CorporateAction` exists for equities; nothing links option strikes to underlying splits/specials/ticker changes | A multi-year options history will cross these. At minimum: detect and **exclude** cycles crossing an adjustment event, and record the exclusion — do not silently include mis-struck contracts. **Enforce it mechanically, not by policy: see §2.3, `shares_per_contract != 100` is the machine-readable signature of an OCC adjustment and must refuse the contract at entry.** |
| D8 | No dividend-yield series anywhere | `options/blackscholes.py:48-101` accepts a continuous dividend yield `q` with **default `0.0`**; no dividend-yield or ex-date series exists in the schema (grep: no `dividend` model) | See §2.4a. `q=0` is a *systematic, one-directional* bias in a put-selling strategy's favour. Either restrict Phase 1 underlyings to a code-enforced no-/low-dividend allowlist, or source and record `q` per evaluation. Leaving `q` defaulted is not an option. |

### 1.4 Storage

FACT: `backfill_max_total_bars = 200_000` and `_MAX_BARS_PER_CONTRACT = 800`
(`config/research.py:193-215`, `options_backfill.py:55-63`).
HYPOTHESIS: the §1.1 target is roughly 10 underlyings × 36 cycles × ~30 contracts × ~45
sessions held ≈ **~490,000 bars**, i.e. ~2.5× the current global ceiling, and more if the
±15% band is honoured properly. On SQLite at ~120 B/row that is a few hundred MB — not a
storage problem, but it **is** a `max_total_bars` problem, and raising that cap must be an
explicit, recorded decision rather than a quiet default bump. FACT: the memory record says one
worker per DB and write-intent sessions are sticky — a long backfill must not be run
concurrently with the live probation worker against the same file.

### 1.5 Gate 0 data-availability rule for options

**HYPOTHESIS**, patterned directly on the existing `promotion.py:892-965` fail-fast.
A candidate options evaluation fails gate 0 — with no attempt at gates 1-10 — unless **all** hold:

- **0.a Horizon.** Same window arithmetic as today: `sealed_start > start` and pre-sealed span
  ≥ `MIN_PRESEALED_DAYS` (350), on top of `sealed_window_days` (365). FACT: 715-day floor.
- **0.b Underlying coverage.** Each underlying in the snapshot has continuous `OHLCVDaily`
  across the whole window from source `massive` (FACT: R6 — a blended/bulk source fails gate 8).
- **0.c Cycle coverage.** For each (underlying, monthly cycle) in the window, the stored chain
  actually **brackets the strategy's target strike** on the entry date — i.e. contracts exist
  both above and below the target on both sides of the structure. This is the options-specific
  check with no equity analogue, and it is the one that catches D2/D3 silent under-coverage.
  Fail if fewer than a stated fraction of cycles bracket.
- **0.d Bar continuity.** For each selected contract, daily bars exist for ≥ a stated fraction
  of the sessions between entry and exit/expiry, with gaps recorded.
- **0.c/0.d thresholds are PRE-REGISTERED, not chosen later (R1).** The two fractions above are
  the numbers most at risk of being set to whatever the delivered data happens to support. They
  must be written into the D5 pre-registration document (§7, Phase D) **before the backfill run
  completes**, alongside the disposition rule, and folded into `config_hash` so they cannot move
  silently. HYPOTHESIS for the pre-registered values, offered now precisely so they are on the
  record before any coverage is observed: **0.c = 90% of cycles bracket; 0.d = 80% of
  entry-to-exit sessions have a bar for every leg.** The derivation is a design judgement, not
  an empirical one: 0.c below ~90% means the strike-selection rule is being silently rewritten
  by data availability in ≥1 cycle in 10; 0.d below ~80% means more than one session in five is
  priced by a model rather than a print, which exceeds the synthetic-mark ceiling gate 8 will
  enforce anyway. If the delivered data cannot meet them, the correct response is more data or
  a narrower underlying set — **never a lower fraction chosen after the fact.**
- **0.e Greeks/IV provenance.** The run records, per evaluation, **which** delta/IV path was
  used — `local_bs_inverted` (IV inverted from the contract's own print), `same_session_surface`
  (§2.4b), `vendor` (only where a dated vendor value genuinely exists), or `pct_otm_proxy` —
  and the per-trade fraction from each. FACT: vendor IV/greeks are documented as "usually absent
  on this entitlement" (`market.py:264`) and today exist only for one timestamp.
- **0.f Fill-price provenance.** The run records that NBBO is unavailable **for both options and
  equities** (§0.3 item 3) and names the modelled spread function used (§2.4). FACT: `/v3/quotes`
  is 403 for `{O:contract}` *and* `{sym}` under the current entitlement — this is not a caveat to
  bury, it is a gate-0 disclosure field. Precedent: `SF1000_SPEC.md` §5 already requires an
  explicit "cost model: PLACEHOLDER spread proxy — not yet calibrated" label wherever a real
  quote is unavailable.
- **0.g Dividend-yield provenance.** The run records the `q` source per underlying, or asserts
  the underlying is on the code-enforced no-/low-dividend allowlist (§2.4a). A run that used
  `q=0.0` by default fails gate 0 outright.
- **0.h Deliverable integrity.** Every contract traded in the evaluation had
  `shares_per_contract == 100` at entry (§2.3). Any contract that did not was refused, and the
  refusals are counted and recorded — this is D7's exclusion, enforced mechanically.

**FACT-grounded consequence:** run against today's DB, an options gate 0 fails on 0.a, 0.b,
0.c, 0.d, and 0.g simultaneously (one underlying, five weeks, one snapshot timestamp, no
dividend series). That is the correct outcome and must not be worked around. FACT: R4 permits
making gates *more* searching, never weaker — gate 0.c-0.h are additions, which R4 allows.

---

## 2. Engine extension design

### 2.1 Placement — a sibling module, not a generalisation

**HYPOTHESIS:** create `src/signalforge/backtest/options_engine.py` as a **sibling** of
`engine.py`. Do not extend `EntrySignal`/`SimTrade`/`CandidateDraft` in place.

**FACT-grounded reasons.** (a) `engine.py` never branches on asset class, so leaving it
untouched keeps the equity path byte-identical by construction — the strongest possible
guarantee that the two live approved strategies are unaffected. (b) `EntrySignal.__post_init__`
rejects `Direction.AVOID` and knows only LONG/SHORT (`engine.py:30-41`) — a put credit spread is
simultaneously short and long and has no honest value for that field. (c) `SimTrade` is a
frozen dataclass consumed by `portfolio_metrics.py`, `walkforward.py`, and
`promotion.py` gate 7 by flat field access; none of those call sites was audited for
defensive handling of new fields. (d) FACT: `persistence.spec_json_hash()` hashes every
`StrategySpec` field except `{git_sha, status, notes}` (`persistence.py:32-43`) — **adding a
field to `StrategySpec` would retroactively change every existing strategy's hash and knock
both PAPER_APPROVED strategies out of their own approval scope.** This is why
`sensitivity_axes()` was deliberately kept off the spec as a Protocol
(`strategies/base.py:30-47,41-45`). The same reasoning forbids adding `structure_type` /
`target_delta` / `dte_range` as spec fields. Options structure parameters go in a `params`
dataclass (exactly as `TrendParams` does, `trend_continuation.py:20-29`) and are surfaced by
string interpolation into the existing text spec fields — which keeps them hash-detectable
with no field-set change.

### 2.2 What is reused unchanged (FACT — asset-class-agnostic today)

| Component | Why it already works | Ref |
|---|---|---|
| `montecarlo.bootstrap_ci` | Operates on a bare `Sequence[float]` of R-multiples | `backtest/montecarlo.py:15-64` |
| `backtest/regime.py`, `research/regime.py` | Regime derives purely from the SPY proxy series; trades are bucketed by `entry_date` only. **Note the label already carries a volatility half** — `regime.py:57` emits `f"{trend}_{vol}"` with `vol ∈ {highvol, lowvol}` — which gate 6 currently discards (§5.2). | `regime.py:1-79`, `research/regime.py:1-101` |
| `research/portfolio_metrics.py` | Uses only `.pnl_r`, `.entry_date`, `.exit_date`, `.bars_held`. A structurally-equivalent `OptionTrade` reuses it with no code change — **but see the caveat below.** | `portfolio_metrics.py:20,49-137` |
| `research/sensitivity.py` | Generic `ParamGrid = Mapping[str, Sequence[float\|int]]`, one-step-neighbour logic on named axes | `sensitivity.py:1-40` |
| `data/calendar.py` | NYSE sessions via `pandas_market_calendars` XNYS | `calendar.py:1-45` |
| `DataSnapshot` / `StrategySealedTest` immutability | Snapshot immutable per key+symbol set; sealed test unique on `(strategy_version_id, dataset_snapshot_id)` | `promotion.py:541-609`, `db/models/research.py:224-250` |
| `count_sealed_looks` / `sealed_look_ledger` | Keys on `Strategy.name`, derived from the table on every read — a new options family starts at k=0 by construction, no new code | `promotion.py:615,634,888,1293` |
| `audit.py` redaction, `killswitch.ensure_not_engaged` | Cross-cutting | `audit.py`, `killswitch.py` |

**Caveat on `bars_held` (HYPOTHESIS, and it is not cosmetic).** Reusing `bars_held` as "sessions
held" is structurally correct and keeps `portfolio_metrics` unchanged — but for options it is
**not the economically relevant duration**. Two trades each held 14 sessions, one entered at
21 DTE and one at 60 DTE, have entirely different theta profiles, gamma exposure, and
assignment risk, and `portfolio_metrics` cannot tell them apart. Fix: keep `bars_held` for
structural compatibility, **add `dte_at_entry` and `dte_at_exit` to `OptionTrade`**, and require
the gate 1 walk-forward report and the gate 5 sensitivity report to be **stratified by DTE
bucket** (e.g. 21-30 / 31-45 / 46-60). An options result reported only in `bars_held` terms is
under-specified.

### 2.3 Position / leg model (HYPOTHESIS)

```
OptionLeg           (frozen)  right: CALL|PUT ; strike: float ; expiration: date ;
                              qty: int (signed: +long / -short) ;
                              shares_per_contract: int   # READ FROM THE CONTRACT ROW.
                                                         # NOT a default. See below.
OptionStructure     (frozen)  structure_type: VERTICAL_CREDIT | VERTICAL_DEBIT |
                              CASH_SECURED_PUT | COVERED_CALL ; legs: tuple[OptionLeg, ...] ;
                              underlying_symbol: str
OptionsEntrySignal  (frozen)  structure ; entry_date ; net_premium (signed: credit>0) ;
                              max_loss_dollars ; max_gain_dollars ; break_evens: tuple[float,...] ;
                              profit_target_pct_of_credit ; stop_multiple_of_credit ;
                              time_stop_dte ; greeks_source ; iv_source ; q_source
OptionTrade         (frozen)  symbol, entry_date, exit_date, bars_held, pnl_r, pnl_pct,
                              pnl_dollars   # same field names as SimTrade -> reuses
                                            # portfolio_metrics unchanged
                              + dte_at_entry, dte_at_exit        # §2.2 caveat
                              + structure_json, entry_net_premium, exit_net_premium,
                                exit_reason, assignment_flag, pin_risk_flag,
                                greeks_source, iv_source, fill_model,
                                r_clamped: bool                  # §2.6
```

**The multiplier is data, not a constant (FACT-grounded correction, rev 2).**
FACT: `OptionContract.shares_per_contract` (`db/models/market.py:250`) is a real column,
defaulted to 100 in the schema but **populated from the vendor** on every write path —
`adapters/massive_options.py:183`, `data/options_ingest.py:97`, `data/options_backfill.py:151`.
Hard-coding `multiplier = 100` in the leg model and in every `× 100` formula in §2.6/§3.1
throws that away. OCC-adjusted contracts (splits, special dividends, mergers — **exactly the
D7 events**) carry non-100 deliverables; a 100 assumption mis-sizes collateral and mis-computes
R on precisely the contracts D7 is meant to exclude.

**Rule (HYPOTHESIS, Phase 1):** read `shares_per_contract` per leg from the contract row; **assert
it equals 100 at entry and refuse the contract otherwise**, recording the refusal. This converts
D7's "detect and exclude adjustment events" from a policy statement into a mechanical
precondition that cannot be forgotten, and it means every `× 100` downstream is provably
correct rather than assumed. Non-100 deliverables become a Phase 2 question, on the record.

**Phase 1 restriction (HYPOTHESIS, strongly recommended):** defined-risk structures only.
Max loss is then always finite and computable, so R is always well-defined (§2.6). Undefined-risk
structures (naked short options/strangles) have no natural R unit and would force a dollar or
percent basis — a different metrics stack, a different risk model, and a different broker
approval level. Defer them entirely; do not leave a code path that could accept one.

### 2.4 Pricing and fills (the honest part)

FACT: there is no bid/ask anywhere — not in `OptionQuoteSnapshot`, not in
`OptionAggregateDaily`, and not obtainable (403, **for equities too** — §0.3 item 3).
FACT: the equity engine fills at `series.open[t+1]` (`engine.py:85-151`); an option's daily
open is a thin, frequently-stale print.
FACT: `OptionAggregateDaily.close` (`db/models/market.py:290-318`) is a **last-trade print**.
There is no mid anywhere in the schema, and none can be derived.

**HYPOTHESIS — the fill model, stated as an assumption and labelled everywhere.**

**(1) The reference price is a print, not a mid — name it accordingly.**
Per leg per session, `last_print` = `OptionAggregateDaily.close` for that contract. Calling it
"mid" and then subtracting a half-spread is arbitrary **in sign**: a late-day print on a
one-sided option market is already sitting at the bid or at the ask, so half-spreading it is as
likely to improve the fill as to worsen it. Two defensible models; **pick one, state it, and
fold its constants into `config_hash`**:

- **(1a) Print-plus-full-spread (recommended for Phase 1).** Fill at
  `last_print ± full_modelled_spread` in the adverse direction — a **full** spread per leg per
  side, not a half. Rationale: the print's position within the true spread is unknown, so the
  conservative assumption is that it sat at the favourable touch and the fill must cross the
  whole way. A 2-leg vertical therefore pays a full modelled spread **four times** round trip
  (2 legs × 2 sides).
- **(1b) Re-centred mid.** Define `mid = BS_theoretical(underlying_close, iv_source, q, …)`
  re-centred so that it reproduces `last_print` on sessions where one exists, then fill at
  `mid ± half_spread`. Honest but strictly more machinery, and it inherits every §2.4a/§2.4b
  input assumption.

**(2) The modelled spread is a config constant, not a magic number.**
`spread = max(abs_floor_cents, pct_of_last_print × last_print)` as a function of moneyness and
DTE. Both parameters are **config constants folded into `config_hash`**, exactly like
`slippage_bps` today, and both are deliberately pessimistic.

**(3) A missing bar is a liquidity fact. It is never a fill. (Correction, rev 2.)**
No `OptionAggregateDaily` row for a contract on a session means **that contract did not trade
that session**. Booking a synthetic fill there — as an earlier draft of this map did, capping
only the *fraction* at gate 8 — records an unfillable trade as filled, in a contract with zero
volume, which is the single most edge-manufacturing thing an options backtest can do. The rule:

- **Entry:** no entry may be initiated on a session where **any** leg of the structure lacks a
  bar. Not a synthetic fill — a **non-entry**. The cycle is skipped and counted (gate 0.c/0.d
  read these counts).
- **Exit (target/stop/time-stop):** the exit is *signalled* on the close that triggers it but is
  **not executable** until the next session on which **every** leg has a bar. The trade is
  marked `exit_deferred_sessions = n`, and the fill is taken at that later session's prints.
  Deferral is a cost, and it must be borne, not assumed away.
- **Force-close at expiry−1:** see §2.7 — a structure whose legs cannot all be priced from
  prints on the force-close session **may not be entered in the first place**.
- **Synthetic marks are for mark-to-market only.** They may set an unrealised value and may
  trigger a *signal*; they may never set a *fill price*. `synthetic=True` on a fill is a
  contradiction in terms and the model must not be able to express it.

**(4) Disclosure.** Every result carries a `fill_model` string, the `iv_source`/`q_source`
mix, the non-entry and deferral counts, and the gate-0 disclosure "NBBO unavailable under the
active entitlement for options **and** equities — spread is modelled, not observed."

**Risk to state plainly (FACT-grounded):** option quoted spreads are proportionally far wider
than equity spreads, and the equity side already ships an admittedly optimistic flat 11 bps
round trip **against an equally unobserved quote**. A modelled options spread that is too
generous will manufacture edge. **HYPOTHESIS (recommendation):** run every evaluation — options
*and* equities — at two spread settings, baseline and 2× baseline, and require the gate ladder
to pass at **both**. This is a strictly *more* searching gate, which R4 permits, and it is the
single cheapest defence against the missing-NBBO problem on either asset class. See §5.2 gate 4b.

### 2.4a Dividend yield — `q` may not be left at its default

FACT: `options/blackscholes.py:48-101` takes a continuous dividend yield `q` with **default
`0.0`**, threaded through `price`, the greeks, and IV inversion. FACT: no dividend-yield or
ex-date series exists anywhere in the schema.

**Why this is not a rounding error (HYPOTHESIS, directionally certain).** At `q = 0` on a
dividend-paying underlying, over the life of the option: **puts are underpriced and calls are
overpriced**, by roughly the present value of the dividends in the interval. A put-*selling*
strategy priced at `q = 0` therefore systematically receives a *modelled* credit below the true
one on entry and is charged too little to close — **a one-directional bias in the strategy's
favour**, not noise. It also removes the single input that makes early assignment on short calls
predictable at all (§2.7), so the assignment discussion becomes unanchored.

**Rule (HYPOTHESIS, Phase 1):** exactly one of —

- **(a) Code-enforced no-/low-dividend allowlist.** Phase 1 underlyings are restricted to a
  frozen allowlist whose members have a trailing yield below a pre-registered ceiling; the
  allowlist is in config, folded into `config_hash`, and enforced at signal generation (not by
  a comment). Note this likely **excludes SPY/IWM** (distributing ETFs) — which cuts directly
  into §1.1's Tier A and into §5.3's trade-count arithmetic. That trade-off must be made
  knowingly.
- **(b) Source a dividend yield** per underlying per session (trailing 12-month yield is
  sufficient for a 21-60 DTE horizon), store it, and record `q_source` per evaluation (gate 0.g).

**(b) is the more honest path and (a) is the cheaper one; leaving `q` defaulted is neither.**
This is an operator decision — added as decision #11 in §7.

### 2.4b Where the IV comes from when nothing traded (the circularity, resolved)

**The hole in the previous draft, stated plainly.** §1.3 D5 resolves "no historical IV series"
by **inverting IV from the contract's own daily close**. §2.4's old fallback priced a missing
bar with "a Black-Scholes theoretical using the underlying's close and a documented IV input".
But where there is no bar there is **no close to invert**, hence no IV, hence no theoretical.
The fallback had no input. It was circular exactly where it mattered most — in the illiquid
contracts whose absence is the entire problem.

**Resolution (HYPOTHESIS).** Under §2.4(3) a missing bar can no longer produce a *fill*, so the
only remaining need is a mark. The mark's IV comes from a **same-session, same-underlying
surface**, never from the contract itself:

1. For underlying U and session S, collect **every** contract on U that **did** print on S.
2. Invert IV from each print via `blackscholes.implied_vol` using that session's underlying
   close, the pre-registered rate, and `q` from §2.4a.
3. Fit a minimal surface — per expiry, IV as a function of log-moneyness (a monotone or
   low-order fit, pre-registered; no free-form spline that can be tuned after the fact) — and
   interpolate across expiries for the term structure.
4. Mark the non-printing contract from that surface. Record `iv_source = same_session_surface`
   and the number of contracts the fit used.
5. **Hard exclusion:** if fewer than **N** contracts on that (underlying, expiry) printed on
   that session, there is no surface. Do not extrapolate. The position is marked
   `iv_unavailable`, and — per §2.4(3) — no fill may occur from it; if it is the force-close
   session, the structure was ineligible for entry (§2.7). **N is pre-registered in D5**
   (HYPOTHESIS: N = 5 per expiry, ≥3 distinct strikes on the relevant side).

**Explicitly forbidden: realised volatility as the fallback.** For a premium-selling strategy
this is not a neutral approximation. Realised vol is, on average and across regimes, **below**
implied — the volatility risk premium is precisely the thing these strategies are trying to
harvest. Marking unsold-back short premium at realised vol values it *cheaper than it is*,
which **inflates simulated credit capture on exactly the trades the strategy claims as its
edge**. If a run ever falls back to realised vol, it is not evidence; it is the assumption
restating the conclusion.

### 2.5 Cost model

**HYPOTHESIS:** a new `OptionCostModel` dataclass paralleling `CostModel`'s shape (not a
subclass — shares and contracts flow through different formulas):
`commission_per_contract`, `commission_min_per_order`, `exchange_fee_per_contract`,
`spread_pct_of_last_print`, `spread_abs_floor_cents`, `assignment_fee`, `exercise_fee`.
Cost scales with **legs × contracts**, so a 2-leg vertical carries 4 contract-commissions round
trip — and, under §2.4(1a), four full modelled spreads. FACT: R4 freezes `CostModel` for the
program's duration; `OptionCostModel` is a new object, so setting it is a one-time decision that
must be made **before** the first evaluation and then frozen identically.

### 2.6 R definition = max loss, and what that does and does not buy

**HYPOTHESIS, and this is the load-bearing definitional choice.**
FACT: the equity engine defines `risk_per_share = abs(entry_fill - stop_price)` and
`pnl_r = d*(exit-entry)/risk_per_share` (`engine.py:111,128`) — meaningless for a spread.

For a defined-risk options structure, with `M = shares_per_contract` read per leg (§2.3, always
100 in Phase 1 by assertion):

```
R (one unit of risk, dollars) = max loss at expiry, after entry costs
  vertical credit spread : (strike_width × M × contracts) − net_credit_received + entry_costs
  vertical debit spread  : net_debit_paid + entry_costs
  cash-secured put       : (strike × M × contracts) − net_credit_received + entry_costs
  covered call           : defined against the equity cost basis; the overlay's own R is the
                           forgone upside above the short strike — see §4.2, this one is not
                           a clean R and is the reason the covered call is sequenced late
pnl_r = realised_pnl_dollars / R
```

**What it buys.** R is known **at entry**, never path-dependent, and directly comparable to the
equity R stream *within one structure type* — so `bootstrap_ci`, `portfolio_metrics`, and gates
2/3/4 apply with no code modification. FACT: this is the discipline `options/simulators.py`
already encodes — every simulator returns a **finite** `max_loss` because only long/fully-
collateralised structures are supported.

**What it does NOT buy (correction, rev 2). The −1 bound is not enforced by the fill model.**
The previous draft asserted `pnl_r ∈ [−1, +x]` as a property the metrics stack relies on. It is
not one. Two mechanisms break it:

- **(a) Per-leg spread on exit.** Under §2.4(1a) a 2-leg exit pays a full modelled spread on
  each leg. If the structure is closed at or near max loss, `realised_debit + exit_costs` can
  exceed `strike_width × M`, giving `pnl_r < −1`.
- **(b) Intrinsic flooring interacting with a deferred or synthetic-marked exit.** §2.7's
  intrinsic floor and §2.4(3)'s exit deferral can each push the realised exit past the
  theoretical max loss.

**Rule (HYPOTHESIS): do not assert a bound the model does not enforce. Choose one and record
it.**

- **Option 1 (recommended): clamp and count.** Clamp realised loss at −1R, set
  `OptionTrade.r_clamped = True`, and **report the clamp count and the unclamped distribution
  at gate 8**. A clamp rate above a pre-registered ceiling is itself a gate-8 finding — it means
  the cost model and the exit rule are inconsistent with the structure.
- **Option 2: do not clamp**, and require every evaluation to report the **empirical minimum**
  `pnl_r` and the count below −1.

Either way, the assertion "R is bounded at −1" is removed from this document as a property and
becomes a *measured quantity*.

**Corollary:** a trade closed early at a profit target still divides by the same entry-time R.

**And the far more serious consequence — see §5.1. Because R is max loss, R is
structure-dependent, which makes the frozen gate thresholds mean different things for
different structures.** That is the single most important correction in this document.

### 2.7 Expiry, force-close pricing, pin risk, and assignment

FACT: nothing anywhere models expiry, assignment, exercise, or pin risk —
`engine.py:154-184 _resolve_exit` knows only stop / target / bar-count / end-of-data, and
`paper/ledger.py:266-319 mark_to_market` prices positions off the **underlying's** OHLCV bars
with no expiry branch.

**HYPOTHESIS — Phase 1 rule: force-close before expiry, never hold through, and price the
force-close explicitly.**

- Hard exit at `time_stop_dte` (grid centre: 7 DTE) or on profit target / stop, whichever first.
- Any structure still open at the `expiry − 1` session is force-closed there.
- **Entry eligibility (new, and it is the clean way to close the pricing hole).** A structure may
  be entered **only if** its force-close session can, in principle, price every leg from prints.
  Operationally this is enforced in the backtest as: if on the actual `expiry − 1` session any
  leg lacks a bar, the trade is **excluded from the evaluation entirely and counted as an
  exclusion** (a gate 0.d / gate 8 input), rather than being force-closed at a synthetic mark. A
  long OTM wing that stops trading near expiry — the routine case for a vertical — is therefore
  *removed from the sample*, not silently marked. This is a loss of trades, and it is the honest
  one: a wing that does not trade cannot be sold.
- **Per-leg force-close pricing, with an intrinsic floor.** Where all legs do print:
  `long leg exit = max(intrinsic, last_print) − spread`;
  `short leg exit (buy-back) = min(−intrinsic, −last_print) − spread` (mirrored sign) —
  i.e. a long leg is never valued below its intrinsic value and a short leg is never bought back
  for less than its intrinsic value. Without the floor, a stale print on a deep-ITM leg produces
  a fictional profit. Note the floor is one of the two mechanisms that can break the −1 bound
  (§2.6(b)), which is why §2.6 measures rather than asserts it.
- **Pin risk is recorded, not modelled away.** Define a pre-registered **pin band** around each
  short strike (HYPOTHESIS: ±0.5% of the underlying, or ±1 strike increment, whichever is
  narrower). If the underlying closes inside the band on the force-close session, set
  `OptionTrade.pin_risk_flag = True`. Gate 8 reports the pinned fraction and their R
  distribution separately. A strategy whose edge concentrates in pinned trades has not
  demonstrated an edge; it has demonstrated a modelling artefact.
- **Deep-ITM short leg.** If the short leg is ITM beyond a stated threshold on any close before
  the force-close session, set `assignment_risk`. Do **not** silently ignore it.
- FACT: `OptionContract.exercise_style` defaults to `'american'` (`market.py:250`) — early
  assignment is real, and a force-close rule *approximates it away* rather than modelling it.
  That approximation must be disclosed on every evaluation record. It is biased **in the
  strategy's favour** (it removes the tail where a short leg is assigned at the worst moment),
  which is exactly the direction of bias that must be stated, not buried.
- Dividend-driven early assignment on short calls (the main real-world case) is not modelled at
  all in Phase 1. Disclose; do not approximate. Note this is the second place where §2.4a's `q`
  matters: with `q = 0` the model cannot even *rank* which short calls were at risk.

### 2.8 Calendar

FACT: `data/calendar.py` gives NYSE sessions but has no expiration logic. **HYPOTHESIS:** add
`data/options_calendar.py` alongside it (not inside it) providing: third-Friday monthly expiry
resolution with the Thursday rule for holiday weeks; weekly Friday expiries; early-close
sessions; and an explicit `settlement_style` distinction (PM-settled ETF options vs AM-settled
cash index options). Phase 1 trades ETF and single-name options only — all PM-settled,
American-style, physically settled — so AM/cash settlement can be declared out of scope and
enforced by an underlying allowlist rather than modelled.

**This module is not backtest-only.** §6.4 requires the OMS to cross-check
`adapter.clock()` against `data/options_calendar.py` and to **block on disagreement**. Design it
with that second consumer in mind from the start — a calendar that only the backtest can call
is a calendar the execution layer will re-implement inconsistently.

---

## 3. Risk and paper mechanics

### 3.1 Collateral and buying power

FACT: `PaperAccount` (`db/models/paper.py:37-44`) has only `name`, `initial_cash`, and `cash`
(re-verified rev 2). There is nowhere to hold collateral separately from spendable cash. FACT: a
repo-wide grep across `risk/`, `paper/`, `alerts/` for `collateral`, `buying_power`, `margin`,
`multi_leg`, `assignment`, `exercise`, `option_leg` returns **zero** hits.

**HYPOTHESIS:** add `collateral_reserved` to `PaperAccount`, plus a `PaperCollateralEntry`
append-only ledger mirroring `PaperTrade`'s S9 immutability discipline. Two fields, one table —
the append-only ledger is what makes the reservation auditable rather than a mutable number
someone can quietly fix. Reservation per structure at entry (`M = shares_per_contract`, §2.3):

- cash-secured put: `strike × M × contracts − net_credit`
- defined-risk vertical: `strike_width × M × contracts − net_credit` (= R)
- covered call: the underlying shares themselves; reserve the shares, not cash
- debit spread: the debit paid (already cash-settled at entry)

`spendable_cash = cash − collateral_reserved`. Every entry checks spendable cash first and is
refused otherwise — the same fail-closed shape as the auto-simulate guard.

**Reconciliation against §5.3 (correction, rev 2) — the CSP does not fit the paper account.**
One SPY cash-secured put at a ~$450 strike reserves ~**$45,000**. Against §3.2's proposed
`options_collateral_pct_of_equity_max` of 30%, a $100k paper account supports **zero** such
positions (30% = $30k < $45k); a $250k account supports one. §5.3's backtest arithmetic assumes
~216 pre-sealed entries across 10 underlyings — **unreachable in *paper* at any plausible account
size for the CSP.** These two sections previously contradicted each other in silence. Resolve it
explicitly, and the resolution is an operator decision (§7 decision #12):

- **The backtest and the paper stream are different populations, by design, and they feed
  different gates.** Gates 1-9 are fed by the **backtest** (position-count-unconstrained, one
  structure per underlying per cycle). Gate 10 — live paper probation — is fed by the **paper**
  stream, which is collateral-constrained and will be **an order of magnitude thinner**.
- Therefore: state the expected paper trade rate per structure per month *before* probation
  starts, and set the probation observation window from that rate, not from the backtest count.
  A CSP probation on a $100k account is a multi-year proposition; a **vertical** probation is
  not (a 5-wide put spread reserves ~$500 − credit, ~90× less). **This is an independent
  argument for sequencing the defined-risk vertical ahead of the CSP**, and it cuts against
  §4.1's "ship O1 first" ordering on grounds §4.1 does not consider. Flagged, not resolved —
  decision #12.
- Alternatively, size the paper account to the strategy (raise `initial_cash`), and record that
  as a decision — but note that inflating paper equity also inflates every percent-of-equity
  limit in §3.2 and makes the paper stream less representative of the operator's real account,
  which is what gate 10 is supposed to be confirming.

### 3.2 Limits — every number below is an evaluation grid centre, not a recommendation

FACT: `RiskLimits` (`config/research.py:45-53`) defaults are per_trade 0.5%,
max_daily_portfolio_risk 1.5%, max_position_concentration 10%, max_portfolio_exposure 60%,
`max_correlated_exposure_pct = 25.0  # per sector / theme`, min_reward_to_risk 1.5 — **all
notional-dollar-based, none max-loss-based**.

**Framing (correction, rev 2 — this section previously contradicted §7 decision #4).**
Every numeric limit below is a **grid centre point for *evaluation*** — the value around which a
sensitivity grid is built so the ladder can measure how the result moves — **not a recommended
setting for the operator's capital.** "HYPOTHESIS" is a provenance label meaning "nothing in the
repo establishes this"; it is not a disclaimer, and it does not make a position-sizing number
safe to present as a default. **Every capital limit in this section is an operator decision**
(as §7 decision #4 already says), and this document does not make it.

**HYPOTHESIS — options limits are max-loss-based, and are separate config, not reused values:**

| Limit | Grid centre | Note |
|---|---|---|
| `options_per_structure_max_loss_pct` | 0.5% of equity | Matches the equity per-trade figure so the two streams size comparably in *risk* terms. Operator decision. |
| `options_total_open_max_loss_pct` | 2% | Aggregate across open options. Operator decision. |
| `options_max_structures_per_underlying` | 1 | Keyed on the **underlying**, not `instrument_id` — see §3.6. |
| `options_max_open_structures` | 5 | **Not a diversification statement on its own — see below.** |
| `options_collateral_pct_of_equity_max` | 30% | Interacts hard with §3.1's CSP reconciliation. Operator decision. |
| `options_max_net_delta_beta_weighted` | *to be set* | **New, and required — see below.** |
| `options_max_net_vega_pct_of_equity` | *to be set* | **New, and required — see below.** |

**Correlated exposure has no options analogue today, and the per-structure limits do not create
one (correction, rev 2).** FACT: `max_correlated_exposure_pct = 25.0` is per sector/theme
(`config/research.py:53`) and is an equity notional concept. Every options limit above is
per-structure, per-underlying, or a simple aggregate — **none of them prevents five short put
spreads on SPY, QQQ, IWM, AAPL, and NVDA simultaneously**, which satisfies
`options_max_structures_per_underlying = 1` and `options_max_open_structures = 5` while being
**one beta bet with five tickers on it**, plus one short-vol bet with five tickers on it. In a
2020-March-style session all five lose together and the "aggregate 2% max loss" is realised in
full, at the same time, alongside the equity book.

**Required addition (HYPOTHESIS):** an aggregate **net-delta** cap and an aggregate **net-vega**
cap **across all open options *plus* the open equity book**, expressed in **beta-weighted
underlying-equivalent** terms (beta to the same SPY proxy `regime.py` already uses, so no new
data). Without both, "5 open structures" is a count, not a risk limit. Note that a short-premium
book is short vega by construction, so the vega cap is the one that actually binds in a vol
spike; the delta cap is what stops the five-ticker beta bet.

**`min_reward_to_risk` must be replaced by a *pair*, not a single ratio (correction, rev 2).**
FACT: `min_reward_to_risk = 1.5` is **structurally unreachable** for a credit spread (max gain =
credit < max loss by construction), so a naive reuse rejects every credit spread. The previous
draft proposed `min_credit_to_width ≥ 0.25` as the analogue. That is necessary but **not a
risk-adjusted hurdle**: credit/width is trivially satisfiable by **moving the short strike
closer to the money**, which raises the credit *and* the loss probability together. Left alone,
it rewards taking more directional risk, and — worse — **gate 5's sensitivity grid on
`short_delta` will reliably prefer the highest-delta cell**, because that cell both clears the
credit hurdle most easily and (in a sample without a large adverse move) books the most wins.
The gate would then certify the least robust corner of the grid.

**Rule:** `min_credit_to_width` is always paired with a **maximum short-strike delta** (or,
where delta is proxied, a **minimum %-OTM**). Both are pre-registered, both are in
`config_hash`, and **both are sensitivity axes** so the ladder measures the trade-off rather
than optimising along it.

### 3.3 Mark to market

**KEEP VERBATIM — this is correct and re-verified.** FACT: `mark_to_market` (`ledger.py:266-319`)
prices every open position from the **underlying's** daily bars (`ledger.py:292`:
`get_daily_bars(session, inst.symbol, ...)`) and checks stop/target against the underlying's
high/low. FACT (risk): it has **no type check** preventing it from being called on an
option-typed instrument — it cannot be today only because no options `PaperPosition` can be
created. **The moment options positions exist without a parallel options-aware mark, this
function will silently misprice rather than error.**

**HYPOTHESIS:** a separate `mark_options_to_market` that (a) marks each leg from
`OptionAggregateDaily` for that contract, falling back to the §2.4b same-session surface with a
recorded `synthetic=True` **mark** (never a fill, §2.4(3)); (b) evaluates targets/stops against
the **structure's net premium**, never the underlying's price; (c) handles DTE-based time stops.
**And**, non-negotiably, add an explicit type assertion to the *existing* `mark_to_market` that
raises on any non-stock/etf instrument. Add that assertion **before** any options position can
exist, not after.

### 3.4 Expiry processing

**HYPOTHESIS:** a daily `process_option_expiries(session, as_of)` step in the worker's
end-of-session sequence, running **before** the heartbeat (FACT: memory records that worker
startup catch-up precedes the first heartbeat — same ordering discipline). It force-closes at
`expiry − 1` per §2.7, releases collateral, writes an immutable `PaperTrade`, and records
`exit_reason='forced_pre_expiry'` plus `pin_risk_flag`. Phase 1 never lets a position reach
expiry, so no assignment path executes; if one is ever reached, the correct behaviour is to
**raise and halt**, not to guess.

### 3.5 Evidence snapshot

**HYPOTHESIS:** `DataSnapshot` identity must be extended for options. FACT: today it is
`(key, symbols_json, description, source_note, continuity_mapping_id)`
(`db/models/research.py:224-250`) — a flat symbol list. That does not pin the strike band,
expirations-per-cycle, DTE window, lookback, IV source, `q` source, or spread model, so two
evaluations against materially different option datasets could resolve to the same snapshot.
Proposal: an `options_scope_json` column whose content is part of the snapshot key, so that
changing any coverage parameter creates a **new** snapshot and therefore a **new** sealed test —
preserving the existing immutability guarantee (FACT: `get_or_create_dataset_snapshot` already
raises `ValueError` on a key hit with a different symbol set; extend the same refusal to the
options scope).

**Which side of the S11 line writes it (clarification, rev 2 — see §3.6).**
`options_scope_json` is **scan-facing evidence metadata**, so it is composed and written by
`research/` (the options promotion path), from a **plain read-only coverage summary** that
`data/options_backfill` *returns* — the backfill never writes into `research.*` itself and never
imports it. This matters because S11 covers `signalforge.data.options_backfill`, not just
`signalforge.options`, and D1/I-O1's per-cycle caps and provenance work lives in exactly that
module.

### 3.6 Auto-simulate guard — explicit options scope

**KEEP VERBATIM — this two-guard shape is correct and re-verified.** FACT:
`assert_auto_simulate_allowed` (`ledger.py:490-515`) currently refuses anything whose
`instrument_type` is not `stock`/`etf` (`ledger.py:496-500`), and is a clean fail-closed
template. FACT (risk, verbatim from the reader pass): adding `"option"` to that tuple without a
fully separate gated path "would silently let options trades flow through equity-shaped sizing,
cash, and mark-to-market logic that is provably wrong for options."

**HYPOTHESIS — the only acceptable shape:**

```
assert_auto_simulate_allowed(...)          # UNCHANGED. Still stock/etf only. Never widened.
assert_options_auto_simulate_allowed(...)  # NEW, separate function, separate setting
  requires ALL of:
    options_auto_simulate_enabled            (new setting, default FALSE)
    candidate.quality_gate_status is PASSED
    instrument_type == 'option_structure'    (new type — NOT 'stock'/'etf')
    strategy_version.status is PAPER_APPROVED
    structure_type == the version's single approved structure type   (§5.2 gate 0.5)
    five-part approved-scope match, extended to a sixth part: the options scope of §3.5
    every leg's shares_per_contract == 100   (§2.3)
    collateral available under §3.1
    every §3.2 limit satisfied, including the new net-delta / net-vega caps
    options_auto_simulate_max_per_day (new cap, separate from the equity cap of 2)
    killswitch.ensure_not_engaged()
```

Two guards, two settings, two caps, one shared kill switch. FACT: this mirrors
`auto_simulate.py`'s existing pattern (kill-switch check, explicit allow-guard, daily cap,
per-decision commit, immutable rejection reasons).

**KEEP VERBATIM — one correction needed, re-verified.** FACT: the "one open position" check
(`auto_simulate.py:108-120,164-171`) is keyed on `instrument_id`; for a multi-leg structure
spanning several contract rows it **would not prevent a second structure on the same
underlying**. The options check must be keyed on the **underlying**.

**S11 covers two source modules, not one (correction, rev 2).** FACT: `pyproject.toml:210-220`:

```toml
name = "S11: options are education/simulation only — no alerts, no LLM, no decision path"
source_modules = ["signalforge.options", "signalforge.data.options_backfill"]
forbidden_modules = ["signalforge.alerts", "signalforge.llm",
                     "signalforge.research.scan", "signalforge.research.candidates",
                     "signalforge.paper.ledger"]
```

So S11 also freezes **`signalforge.data.options_backfill`** out of `research.scan`,
`research.candidates`, and `paper.ledger`. That is correct and should stay — but it is exactly
the module D1/I-O1 modifies (per-cycle caps, point-in-time reference, `IngestionRun`
provenance), and **any attempt to have the backfill write scan-facing scope metadata directly
will hit S11.** Hence §3.5's rule: the backfill *returns* a coverage summary; `research/` writes
`options_scope_json`.

**HYPOTHESIS:** keep S11 exactly as it is over **both** listed source modules, and put every new
strategy/backtest/paper code in **different packages** (`research/strategies/options/`,
`backtest/options_engine.py`, `paper/options_ledger.py`) that may import `options.blackscholes`
and `options.simulators` as pure-math libraries but never the reverse. S11 then remains true and
enforced, and the education module keeps its stated contract.

---

## 4. First options strategy set

Selection principle (HYPOTHESIS): order by **how little new machinery each needs**, and put the
structure that most reuses existing math first — so that the engine, cost model, collateral
ledger, and gate ladder each get proven on the simplest case before complexity is added.
**Note this principle is now in tension with §3.1's collateral finding and §5.3's gate-6 finding,
both of which argue for the vertical ahead of the CSP. See §7 decision #12.**

All four are fully deterministic: given the data and the params, entry, structure selection,
and exit are a pure function. No LLM anywhere (FACT: S3 already enforces this shape for
research/risk/backtest/paper — but see §0.1 B3 on the direction S3 does *not* cover).

**Every parameter value below is an evaluation grid centre (§3.2 framing), not a setting.**

### 4.1 O1 — Cash-secured put on an approved-universe underlying

- **Mechanism.** On an underlying already in the approved equity universe, when the underlying's
  regime is not `risk_off`/bear (FACT: reuse `research/regime.py` unchanged — it needs only the
  underlying's series), sell one put at a target delta/%-OTM, 30-45 DTE, fully cash-collateralised.
  Exit at 50% of credit captured, or at a stop of 2× credit, or at 7 DTE, whichever first.
- **Params (frozen dataclass, interpolated into the spec text — §2.1; values are grid centres):**
  `target_delta` (0.20), `dte_target` (35), `dte_window` (28,45), `profit_target_pct` (0.50),
  `stop_multiple` (2.0), `time_stop_dte` (7), `regime_filter`, `max_short_delta` (§3.2).
- **Sensitivity axes** (via the existing `DeclaresSensitivityAxes` Protocol,
  `strategies/base.py:30-47` — FACT: **zero** of the six shipped strategies implement it today,
  so options would be first): `target_delta` [0.10, 0.16, 0.20, 0.30]; `dte_target` [21, 35, 45,
  60]; `profit_target_pct` [0.25, 0.50, 0.75].
- **Data needs.** Contract daily bars for the selected strike; underlying daily bars; a delta
  input (local BS or %-OTM proxy, recorded per §1.5 0.e); a `q` input per §2.4a.
- **The case for first.** FACT: `options/simulators.py` already implements `cash_secured_put`
  with a finite `max_loss` — the payoff math is the only piece that exists today. Single leg =
  the modelled spread is paid once per side, the smallest possible exposure to the missing-NBBO
  problem. R is unambiguous. Collateral arithmetic is the simplest case.
- **The case against first (rev 2, and it is now the stronger case).** (i) §3.1: one CSP reserves
  ~$45k, so the **paper** stream that feeds gate 10 is effectively a single-position-at-a-time
  strategy and probation will take years. (ii) §5.3: O1's `regime_filter` skips bear, and
  **gate 6 requires ≥10 trades in each of bull, bear, AND range — so a bear-skipping strategy
  cannot pass gate 6 at all.** (iii) §2.4a: if the dividend allowlist route is taken, SPY/IWM
  may be excluded, which removes the cheapest CSP underlyings. All three point the same way.
  **Sequencing is now decision #12, not a settled recommendation.**

### 4.2 O2 — Covered call overlay on an existing paper equity position

- **Mechanism.** Where an open equity `PaperPosition` has ≥100 shares, sell one call per 100
  shares at a target delta, 30-45 DTE. Buy back at 50% of credit, or roll/close at 7 DTE, or
  close immediately if the short strike goes ITM by a threshold.
- **Params (grid centres).** `target_delta` (0.25), `dte_target` (35), `profit_target_pct` (0.50),
  `itm_close_threshold`, `min_shares` (100).
- **Sensitivity axes.** `target_delta` [0.15, 0.20, 0.25, 0.35]; `dte_target` [21, 35, 45].
- **Data needs.** Same as O1, plus the live paper position state.
- **Why later, and the honest caveat.** FACT: `PaperPosition` (`db/models/paper.py:77-93`) has
  no options-leg concept, so this needs new plumbing to attach a leg to an existing equity
  position. More importantly (HYPOTHESIS, and it is the reason this is not first): a covered
  call's R is not clean — the risk is forgone upside above the strike plus the unchanged
  downside of the shares, so `pnl_r` is not comparable to O1's **or to O3's** (§5.1). Its
  evidence should be evaluated as an **overlay delta** against the same equity position held
  naked, not as a standalone R stream. That is a different statistical question and arguably a
  different gate set. FACT: `paper_position` has 0 rows today, so there is nothing to overlay.
  **HYPOTHESIS (recommendation): defer O2 behind O3** on those grounds, despite its simpler
  plumbing.

### 4.3 O3 — Short vertical (credit) spread, regime-filtered

- **Mechanism.** Defined-risk premium sale on a liquid ETF underlying: short a put at a target
  delta, long a further-OTM put a fixed width below (put credit spread in bull/range regimes;
  the call-side mirror in bear regimes — **note this mirror is what makes gate 6 reachable, see
  §5.3**). 30-45 DTE. Exit at 50% of credit, 2× credit stop, or 7 DTE.
- **Params (grid centres).** `short_delta` (0.20), `max_short_delta` (a hard cap, §3.2),
  `width_strikes` or `width_pct_of_underlying`, `dte_target` (35), `profit_target_pct` (0.50),
  `stop_multiple` (2.0), `min_credit_to_width` (0.25 — **paired with `max_short_delta`, never
  alone**, per §3.2), `regime_filter`.
- **Sensitivity axes.** `short_delta` [0.10, 0.16, 0.20, 0.30]; `width` [3, 5, 10 strikes];
  `dte_target` [21, 35, 45]; `profit_target_pct` [0.25, 0.50, 0.75].
- **Data needs.** Two contracts per trade, both bracketed at entry (gate 0.c), both printing on
  entry and on the force-close session (§2.4(3), §2.7), both marked daily.
- **Why it may deserve to be first (rev 2).** R ≈ `width × 100 − credit` ≈ a few hundred dollars,
  so §3.1's collateral wall does not bind and the paper stream is thick enough for gate 10 in a
  realistic window; and the call-side mirror gives it bear-regime trades, so gate 6 is reachable.
  Against that: it is the first genuinely new engine surface (net credit, defined max loss =
  width − credit, two-leg fills, two-leg costs, two-leg force-close eligibility), and FACT:
  `options/simulators.py` explicitly excludes spreads by design, so none of the math exists.

### 4.4 O4 — Long vertical (debit) spread as a directional overlay

- **Mechanism.** When an already-registered equity strategy (`trend_continuation.short_swing` or
  `relative_strength.medium_swing`) fires a LONG signal, express it as a call debit spread —
  long at ~0.50 delta, short at ~0.25 delta, 30-60 DTE — instead of (or alongside) the share
  trade. Exit at a profit target as a fraction of max gain, or at the underlying's own
  invalidation level, or at 7 DTE.
- **Params (grid centres).** `long_delta` (0.50), `short_delta` (0.25), `dte_target` (45),
  `profit_target_pct_of_max_gain` (0.60), inherits the underlying strategy's invalidation.
- **Sensitivity axes.** `long_delta`, `short_delta`, `dte_target`.
- **Why last, and what makes it scientifically interesting.** It reuses an *already-evaluated*
  entry signal, so the only new question is whether the options expression beats the share
  expression of the same signal. That is a far tighter question than "does this signal work",
  and it comes with a natural benchmark (§5.2 gate 7b). It is last only because it depends on
  O3's two-leg engine. **Note R comparability: a debit spread's R is the debit paid, so its R
  stream is not poolable with O3's — §5.1.**

### 4.5 Explicitly deferred, with reasons

| Structure | Deferred because |
|---|---|
| **Iron condors** | 4 legs = 4× the modelled-spread drag on entry and exit (8× under §2.4(1a)'s full-spread rule), against a data layer with no observed spread at all (FACT: NBBO 403). The edge would be smaller than the error bar on the cost assumption. |
| **Calendars / diagonals** | Cross-expiration P&L is driven by term structure, which requires a dated IV series per expiry. FACT: no such series exists, and §2.4b's same-session surface can only interpolate a term structure from contracts that actually printed — thin at the far expiry, which is the leg that matters. Not deferrable-by-effort — deferred by **data impossibility**. |
| **Naked short options / strangles** | No finite max loss ⇒ no well-defined R ⇒ the entire metrics and gate stack (bootstrap CI on R, expectancy in R) does not apply. Also requires a higher broker approval level and margin. FACT: `options/__init__.py:1-6` declares these "intentionally absent" by design. **§6.5 adds a second reason: a leg-by-leg multi-leg submission that partially fills creates one of these by accident.** |
| **0DTE** | FACT: gate 0 already auto-fails `Horizon.INTRADAY` for want of intraday bars (`promotion.py:892-901`). 0DTE is an intraday product with daily bars that are meaningless. Structurally ungateable here. |
| **Ratio spreads, broken-wing butterflies** | Undefined or asymmetric risk plus 3+ legs. Same reasoning as condors and naked, compounded. |

---

## 5. Promotion gates for options

### 5.1 Carries over unchanged — *mechanically*. The thresholds do not mean the same thing.

| Gate | Mechanism | Unchanged because |
|---|---|---|
| 1 rolling_walkforward | 4 folds over the pre-sealed span; a fold counts only with ≥15 trades AND positive expectancy; need ≥2 of 4 | Operates on dated trades (`promotion.py:993-1017`) |
| 2 min_oos_trades | ≥30, on `full.out_of_sample` | Counts trades (`promotion.py:1034`) |
| 3 net_expectancy | OOS expectancy > 0.0R net of costs | R is defined in §2.6 |
| 4 bootstrap_ci | 95% CI lower bound > 0.02R | `bootstrap_ci` takes a bare float sequence |
| 5 parameter_sensitivity | ≥60% grid positive, ≥75% one-step neighbours positive, ≥15 trades/point | `ParamGrid` is name-agnostic; delta/DTE/width slot straight in |
| 6 regime_coverage | ≥3 buckets × ≥10 trades, buckets = `{bull, bear, range}` | Regime comes from the SPY proxy and the entry date (`promotion.py:381-400`) |
| 8 data_quality_and_leakage | `validate_daily()` + leakage self-check | Extended, see 5.2 |
| 9 sealed_final_test | One-time immutable, unique on (version, snapshot); `k_prior` from `count_sealed_looks` | Unchanged |
| 10 live_paper_probation | `HealthMonitorConfig.enabled` | Unchanged |

FACT: all thresholds live in `PromotionThresholds` (`config/research.py:96-126`) and are in
`config_hash`. FACT: R4 forbids weakening any of them. **No threshold number moves for options.**

**But a frozen number is not a frozen level of stringency, because R is structure-dependent
(correction, rev 2 — the most important correction in this document).**

§2.6 defines R = max loss. Max loss is a property of the *structure*, and it varies by nearly two
orders of magnitude between structures on the same underlying at the same delta:

```
5-wide put credit spread on SPY :  R ≈ 5 × 100 − credit          ≈ $   440
cash-secured put on SPY         :  R ≈ 450 × 100 − credit        ≈ $44,500     (~100×)
```

`min_net_expectancy_r = 0.0` and `min_bootstrap_ci_low_r = 0.02` are stated **in R**. A CSP that
earns $890 per trade on $44,500 at risk scores +0.02R; a vertical that earns $8.80 on $440 at
risk also scores +0.02R. These are not the same achievement, they are not the same strategy, and
**the two R streams cannot be pooled, averaged, bootstrapped together, or compared.** The
previous draft's flat assertion "None of these numbers moves for options" was true of the
*numbers* and false of the *stringency*, which is the thing the reader cares about.

**Rule (HYPOTHESIS, and it constrains everything downstream):**

1. **Forbid pooling across structures.** One structure type per strategy version. One R
   definition per sealed test. `bootstrap_ci` is never handed a mixed-structure R sequence.
2. **State the incomparability on the record.** Every options evaluation carries its
   `structure_type` and its R basis in the gate report, and §5.1's thresholds are explicitly
   documented as *not comparable across structures* — an equity +0.30R, a vertical +0.30R and a
   CSP +0.30R are three different claims.
3. **The alternative — normalising R to a common basis** (e.g. R = capital-at-risk over a stated
   horizon, so a CSP's R and a vertical's R are both "dollars at risk for T days") — is a
   defensible design and would restore comparability, but it **changes what gates 3 and 4 mean
   for the equity strategies too**, which R4 and R3 make a version-bump-level event. Not
   recommended for Phase 1. Recorded here so the choice is visible.

### 5.2 Must be added or replaced (HYPOTHESIS — all strictly *more* searching, per R4)

- **Gate 0 extension** — the eight sub-checks of §1.5 (0.a-0.h), including the greeks/IV source,
  the `q` source, the deliverable-integrity assertion, and the spread-model provenance field.
  The 0.c/0.d fractions are **pre-registered in D5 before the backfill completes** and folded
  into `config_hash` (§1.5).
- **Gate 0.5 (replaced, and strengthened — rev 2) — one structure type per strategy version.**
  The previous draft proposed a per-structure trade floor (≥20 OOS trades per structure) inside a
  version that could hold a *structure allowlist*. Given §5.1, that is not enough: an allowlist
  means one sealed test certifies several structures whose R units are **incomparable**, and the
  gate-2/3/4 statistics are computed on a pooled sequence that has no common unit. Replace it
  with the stronger rule: **a strategy version declares exactly one `structure_type`.** A second
  structure is a **different strategy version with its own sealed test**, and the multiplicity
  cost is paid explicitly and automatically via `count_sealed_looks` on the family
  (`promotion.py:615`). This is more searching, not less, and it costs look budget — which is
  the point.
- **Gate 4b (new) — dual spread-assumption pass, on BOTH asset classes.** Gates 2/3/4 must clear
  at **both** the baseline and 2× modelled spread (§2.4). Directly targets the missing-NBBO risk.
  **Correction, rev 2: the equity application is required, not a diagnostic.** FACT: `/v3/quotes/{sym}`
  is 403 in 7 of 7 entitlement batches — the equity 11 bps is exactly as unobserved as any
  options number, so exempting equities from a gate justified by "we cannot see the spread" is
  incoherent. FACT: it is also cheap — `run_backtest(spread_bps=...)` is already a parameter
  (`engine.py:90`); only `paper/ledger.py:50 _NOMINAL_SPREAD_BPS` needs lifting into config.
  **Constraint on how it is applied to the two live strategies (R1/R3):** `StrategySealedTest` is
  unique on `(version, snapshot)` and is **reused, never recomputed** (`promotion.py:1237-1296`),
  so a 2×-spread re-run cannot alter an existing sealed record. The required form is: (i) run 4b
  on the **pre-sealed** span for both approved strategies and publish it as evidence; (ii) if a
  strategy fails at 2×, that is a **disposition** input under R1 and a **version bump** under R3
  — it is not a silent re-seal.
- **Gate 6 extension — volatility buckets, using the label that already exists.** Bull/bear/range
  from the SPY proxy is necessary but not sufficient: a short-premium strategy's regime is
  **volatility**, not trend. FACT (rev 2): `backtest/regime.py:57` **already emits** a compound
  label `f"{trend}_{vol}"` with `vol ∈ {highvol, lowvol}`, and `segment_key` (`regime.py:66-79`)
  already decomposes it — but `_regime_census` (`promotion.py:381-400`) buckets **trend only**
  (`{"bull":0,"bear":0,"range":0}`) and discards the vol half. So the vol dimension is **free**;
  gate 6 simply does not count on it today. HYPOTHESIS: extend the census to the **joint**
  bucket and require a minimum per joint cell. Binary (3 trend × 2 vol = 6 cells) is the
  defensible Phase 1 version; a **tercile** version (9 cells) is a new computation *and* triples
  the trade requirement — see §5.3 before adopting it.
- **Gate 7 — KEPT AS IS. Gate 7b — ADDED. (Correction, rev 2.)** The previous draft *replaced*
  gate 7 (SPY buy-and-hold Sharpe over the matched span, `promotion.py:1161-1195`,
  `require_beat_benchmark_sharpe = True`) with a mechanical-structure benchmark. **That is a
  relaxation presented as a replacement, and R4 forbids it.** A short-premium strategy can
  comfortably beat a mechanical premium-harvest benchmark while losing to simply holding SPY —
  dropping the market benchmark removes exactly the comparison that would catch it. Therefore:
  - **Gate 7 (unchanged):** strategy Sharpe > proxy buy-and-hold Sharpe over the matched span.
  - **Gate 7b (new):** strategy Sharpe > a **naive mechanical version of the same structure**
    (fixed delta, fixed DTE, no regime filter, same cost model, same structure type) — i.e. "does
    the *signal* add anything over mechanical premium harvest". For O4, the mechanical benchmark
    is the **share expression of the same signal** (§4.4).
  - **Both must pass.** R4 permits adding 7b; it does not permit dropping 7.
- **Gate 8 extension** — add: options corporate-action exclusions recorded (D7) **and the
  `shares_per_contract != 100` refusal count** (§2.3); **synthetic-*mark* fraction** recorded and
  below a ceiling (there is no synthetic *fill* fraction to record — §2.4(3) forbids them);
  **non-entry count** (sessions skipped for a missing leg bar) and **exit-deferral distribution**;
  **`r_clamped` count and the unclamped `pnl_r` minimum** (§2.6); **pinned-trade fraction and
  their R distribution** (§2.7); **stop-binding diagnostics** (§5.2a below); assignment
  approximation disclosed; NBBO unavailability disclosed for **both** asset classes; and a
  **clustered bootstrap** diagnostic reported alongside the iid CI. FACT: the iid-violation
  problem is already acknowledged and unresolved on the equity side
  (`STRATEGY_COMPLETION_MAP.md` §4.3); options trades on overlapping monthly cycles of the same
  underlying are *more* correlated, not less. Do not repeat the equity omission here.

### 5.2a Gap risk — the stop is a close-basis stop, and that must be measured

**Hole in the previous draft (rev 2).** Every exit rule in §4 — "50% of credit", "2× credit stop",
"7 DTE" — is evaluated on **daily closes**. A short put spread that gaps through **both** strikes
overnight realises **max loss**, regardless of where the 2× stop sat. A backtest that checks a
close will book the exit at the stop level on the *next* close — a level that was never
reachable. FACT: the equity engine already handles the analogue explicitly at
`engine.py:154-184`, where a stop touched intrabar fills at `min(open, stop_price)` for a long
(i.e. a gap through the stop fills at the **open**, not the stop). The options design does not
port that, and it cannot port it directly — there is no intrabar option data at all.

**Rule (HYPOTHESIS):**

1. **The stop is explicitly a close-basis stop.** It is checked **only** against the session
   close of the structure's net premium, and never treated as an intraday trigger. This is
   recorded in the `fill_model` string so no reader can mistake it for a live stop order.
2. **Measure how often it failed to bind.** Every evaluation reports the full distribution of
   `realised_loss / R`, and specifically the **count and fraction of trades that closed worse
   than `stop_multiple × credit`** — those are the trades where the stop did not protect. A
   strategy whose expectancy depends on the stop binding, in a sample where it frequently did
   not, has not demonstrated what it claims.
3. **This is a gate 8 evidence field**, not a footnote. Pair it with the `r_clamped` count
   (§2.6): both measure the same underlying phenomenon from different ends.

### 5.3 Does the arithmetic close? Shown, not asserted. (Rewritten, rev 2.)

The previous draft asserted "360 candidate cycles × 60% ≈ 215 trades; the OOS slice is a fraction
of that" without ever stating the split, so it never demonstrated anything. Here is the full
arithmetic, with every input a FACT.

**FACT inputs:**

| Input | Value | Source |
|---|---|---|
| IS/OOS split | `_TRAIN_FRAC = 0.6` — OOS is the **last 40% of bars** per symbol | `research/backtest_runner.py:29,209-212` |
| Gates 2/3/4 read | `full.out_of_sample` (the 40%) | `promotion.py:1034,1044,1061` |
| Gate 1 reads | `full.trades` (**all** pre-sealed), 4 folds | `promotion.py:993-1017` |
| Gate 1 fold floor | ≥ `sensitivity_min_grid_trades` = **15** per fold, positive expectancy, in ≥ `4//2` = **2** of 4 folds | `promotion.py:1010-1017`, `config/research.py:107` |
| Gate 5 point floor | ≥ **15** trades per evaluable grid point | `config/research.py:107`, `promotion.py:1103` |
| Gate 6 reads | `full.trades` (all pre-sealed); needs **≥3** buckets × **≥10** trades | `promotion.py:1126-1129`, `config/research.py:110-111` |
| Gate 6 buckets | exactly `{bull, bear, range}` — all three required | `promotion.py:385` |
| Gate 2 floor | **30** OOS trades | `config/research.py:98` |

**The count, for the §1.1 dataset (10 underlyings, 3 pre-sealed years + 1 sealed year):**

```
pre-sealed candidate cycles   = 10 underlyings × 12 monthly cycles/yr × 3 yr   =  360
× regime filter trading ~60% of cycles                                         ≈  216 entries
  (one structure per underlying per cycle — §3.2 options_max_structures_per_underlying = 1)

IS  (first 60% of bars)  ≈ 130 trades
OOS (last  40% of bars)  ≈  86 trades
```

**Gate by gate:**

- **Gate 2 (≥30 OOS):** 86 ≥ 30. **Clears, ~2.9× margin.** ✓
- **Gate 1 (4 folds over 3 pre-sealed years, ≥15 trades and positive expectancy in ≥2):**
  216/4 ≈ **54 trades per 9-month fold**, well over 15. The *trade-count* half clears with large
  margin; the binding half is the expectancy sign in 2 of 4 folds, which is an edge question, not
  a data question. ✓ on counts.
- **Gate 5 (≥15 trades per grid point, ≥60% positive):** each grid point re-runs the whole
  pre-sealed backtest, so each point sees ~216 trades nominally. But a tighter `target_delta` or
  a narrower `dte_window` selects **fewer qualifying cycles**, and the corner cells (delta 0.10 ×
  dte 21) are the thin ones. O1's grid is 4 × 4 × 3 = **48 points**; at ~216 trades per point the
  centre clears easily, and the corners must be checked rather than assumed — `n_evaluable` is
  already reported (`promotion.py:1111`). ✓ with a caveat to verify at the corners.
- **Gate 4 (bootstrap CI low > 0.02R on n≈86):** this is where it gets tight and the previous
  draft said nothing. Approximately, the CI condition is
  `mean − 1.96·sd/√86 > 0.02`, i.e. `mean > 0.02 + 0.211·sd`. Credit-spread R-multiples are
  heavily left-skewed and bounded above by `credit/R` (~0.25-0.40 for a 0.20-delta 5-wide), so a
  plausible sd of **0.5** requires **mean > 0.13R** and an sd of **0.8** requires **mean > 0.19R**.
  For comparison, the two live equity strategies sealed at +0.298R and +0.294R. **This is a real
  bar, and it is the gate most likely to decide the program.** ⚠
- **Gate 6 (≥10 trades in EACH of bull, bear, range) — THIS DOES NOT CLEAR FOR O1, AND NOT FOR
  COUNT REASONS.** FACT: `_regime_census` buckets are exactly `{bull, bear, range}`
  (`promotion.py:385`) and `min_regimes_covered = 3` with the config comment "all three required,
  not 'at least two of three'" (`config/research.py:110`). **O1's design filter explicitly skips
  bear/risk_off** (§4.1). A strategy that refuses to trade in bear regimes books **0 bear
  trades** and can never satisfy `covered >= 3`. **O1 as specified is structurally unpassable at
  gate 6.** This was not visible in the previous draft because the arithmetic was never shown.
  Three ways out, all of which are design decisions that must be made **before** any data is
  looked at (R1):
  1. **Trade the mirror in bear** (O3's call-side construction, §4.3) so bear cycles produce
     trades. This is the cleanest, and it is another argument for sequencing O3 first.
  2. **Change the regime filter** from "skip bear" to "size down in bear" so bear trades exist.
  3. **Accept that a regime-avoiding strategy cannot pass gate 6** and treat that as the gate
     doing its job — R4 forbids relaxing `min_regimes_covered` to 2 to accommodate a design
     choice. **This is the default answer unless (1) or (2) is chosen up front.**
- **Gate 6 + vol buckets (the §5.2 extension):** binary (3 trend × 2 vol = **6 joint cells** × 10
  = 60 minimum) against 216 pre-sealed trades is nominally feasible **but not uniformly
  populated** — `bear_lowvol` is rare by construction (bear markets are high-vol), so the joint
  requirement is likely to fail on that cell even with plenty of total trades. A **tercile**
  version (3 × 3 = **9 cells** × 10 = 90 minimum, with even thinner corners) is **very unlikely to
  close at 10 underlyings over 3 years.** HYPOTHESIS: adopt the **binary** joint bucketing (free,
  §5.2) and require ≥10 in each **marginal** vol bucket plus ≥5 in each joint cell, pre-registered
  — rather than a tercile rule that will be quietly abandoned the first time it binds.

**Verdict (HYPOTHESIS): the arithmetic closes on counts for gates 1, 2, and 5 at the full
10-underlying / 3-year / monthly-cycle dataset of §1.1, and it does not close on 6 underlyings or
on 1 year. Gate 4 is a genuine edge bar, not a data bar. Gate 6 does not close for O1 as
currently specified, for a structural reason that no amount of data fixes.** The correct
responses are, in order: fix O1's regime filter or sequence O3 first (a design decision, made
now, pre-registration); get more data; **never** a lower floor.

### 5.4 Sealed-test discipline and look counting (rewritten, rev 2)

**The premise of the previous draft was false, and the recommendation it produced was a proposal
to build something that already exists under the same name.**

- **FACT: look counting is already automatic, and it is per strategy family.**
  `count_sealed_looks(session, strategy_name)` (`promotion.py:615`) counts every
  `StrategySealedTest` joined through `StrategyVersion` to `Strategy.name` — every version, every
  snapshot. `evaluate_promotion` captures `k_prior = count_sealed_looks(session, spec.name)` at
  `promotion.py:888` before anything is sealed; `sealed_look_ledger` (`:634`) enumerates the full
  history; it is attached as gate-9 evidence under the key `sealed_look_ledger` (`:1293`), carried
  on `PromotionResult.sealed_look_prior` (`:150,174,914,964,1334`), and printed by the CLI
  (`cli.py:1287-1291`). It is **derived from the table on every read**, so unlike a hand-kept
  count it cannot drift.
- **Consequence for options: a new options family starts at k=0 by construction, with no new
  code.** `count_sealed_looks` keys on `Strategy.name`; a strategy named
  e.g. `options_short_vertical.position` has no prior rows and therefore `k_prior = 0`
  automatically. There is nothing to build, nothing to remember, and no way to conflate the
  options ledger with the equity one — the join makes conflation impossible in either direction.
- **FACT: there is no global k, and the two live strategies are at k=4, not 5.** Per-family counts
  (read-only query, §0.4): mean_reversion.short_swing **5**, relative_strength.medium_swing **4**,
  trend_continuation.medium_swing **5**, trend_continuation.short_swing **4**,
  volatility_breakout.short_swing **4** — 22 rows over 5 distinct snapshots. Any statement about
  multiplicity must name a family and cite `count_sealed_looks` for it.
- **What is actually manual, and is therefore the real risk:** **R5 disclosure of abandoned
  variants.** `count_sealed_looks` counts what was *sealed*. It cannot count what was evaluated
  pre-sealed, looked wrong, and was quietly dropped — and with an options parameter space of
  structure × delta × DTE × width, the number of *unsealed* variants explored will dwarf anything
  the equity program has seen. **That, not the look count, is where multiplicity will leak.**
- FACT: `StrategySealedTest` is unique on `(strategy_version_id, dataset_snapshot_id)` and is
  reused, never recomputed, on replay (`promotion.py:1237-1296`) — so the structural protection
  against silent re-looks already exists and needs no options-specific work.
- FACT: R3 — only a version bump earns a fresh sealed look. R1 — sealed data may inform
  disposition, never design. R5 — every evaluated variant, including abandoned ones, is disclosed
  with its pre-sealed evidence.
- **HYPOTHESIS (the recommendation that actually follows):** since the *counting* is solved and
  the *disclosure* is not, the effort goes into disclosure. Pre-register the full parameter grid
  and the disposition rule **before** the first sealed look, exactly as
  `docs/research/PREREGISTRATION_2026-09-11_snapshot11.md` does for equities, and make the
  pre-registration document enumerate the **complete** grid so that "abandoned variant" is
  definable as "a pre-registered cell that was not reported". A variant that was never
  pre-registered and never reported is invisible to both mechanisms — which is precisely what R5
  exists to prevent, and precisely what a large options grid makes easy.
- **HYPOTHESIS (a small, real code addition, unlike the one the previous draft proposed):** since
  §5.2 gate 0.5 now requires one structure type per version, and each structure is therefore its
  own family member, surface `count_sealed_looks` for the **family** in the pre-registration
  template and in the disposition record, so the multiplicity cost of a second structure is
  visible at the moment it is paid.

---

## 6. Live execution layer design

Nothing in this section is implemented, and nothing in it should be implemented before §7's
phase gates are met.

### 6.1 Package layout (HYPOTHESIS)

```
src/signalforge/execution/
  __init__.py          # EXECUTION_DISABLED_BY_DEFAULT = True ; module contract docstring
  protocol.py          # BrokerAdapter Protocol — no vendor import anywhere in this file
  intents.py           # OrderIntent, OrderResult, Fill, PositionSnapshot (frozen dataclasses)
  oms.py               # the single guarded entry point; state machine; audit
  limits.py            # hard pre-trade limits, evaluated fail-closed; may_open / may_close
  arming.py            # ArmedStrategy lifecycle: arm / disarm / expiry / auto-disarm
  deadman.py           # fail-CLOSED heartbeat (deliberate inverse of killswitch.py)
  reconcile.py         # broker truth vs local truth; halts on divergence; max-age check
  credentials.py       # env + macOS Keychain readers only; never writes; never logs
  brokers/
    paper_reference.py # local deterministic simulator — the FIRST adapter, no network
    <vendor>_paper.py  # the operator's chosen broker's PAPER endpoint — second
```

FACT (naming hazard): `ARCHITECTURE.md` §4.1 already reserves `data/adapters/alpaca/` as a
*market-data* vendor namespace. A brokerage adapter must **not** live under
`signalforge.data.adapters` — several contracts assume that tree is market-data-only.

### 6.2 BrokerAdapter protocol (HYPOTHESIS)

```python
class BrokerAdapter(Protocol):
    name: str

    def is_paper(self) -> bool: ...     # PROVEN from the broker's own response — §6.6 step 5
    def account(self) -> AccountSnapshot: ...
    def positions(self) -> Sequence[PositionSnapshot]: ...
    def open_orders(self) -> Sequence[OrderStatus]: ...
    def place(self, intent: OrderIntent) -> OrderResult: ...   # idempotent on client_order_id
    def place_combo(self, intent: ComboOrderIntent) -> OrderResult: ...  # atomic multi-leg
    def cancel(self, client_order_id: str) -> OrderResult: ...
    def cancel_all(self) -> Sequence[OrderResult]: ...          # used by the kill switch
    def clock(self) -> MarketClock: ...
```

**Adapter eligibility (all three are hard, not preferences):** (1) `place` is **idempotent on
`client_order_id`** — a retry after a timeout must never double-fill; (2) the adapter can submit
a **multi-leg structure as one atomic native combo order** (§6.5); (3) `is_paper()` is
**provable** from the broker's own response (§6.6 step 5). An adapter that fails any of the three
is **ineligible**, full stop. Further constraints: every method is synchronous and bounded by a
timeout; no vendor type crosses this boundary (adapters translate); no method accepts free text
or an LLM-produced field.

**FACT (the concrete build blocker) — corrected counts and a precise diagnosis, rev 2.**
Read directly from `tests/safety/test_s1_no_broker_surface.py`:

- **`BANNED_IMPORTS` (lines 18-32) has 15 entries, not 18:** `ib_insync`, `ibapi`, `ibkr`,
  `alpaca_trade_api`, `alpaca`, `selenium`, `playwright`, `pyppeteer`, `webdriver`, `ccxt`,
  `robin_stocks`, `tda`, `schwab`, `fidelity_api`, `MetaTrader5`.
- **`BANNED_CALL_SUBSTRINGS` (lines 35-45) has 9 entries:** `place_order`, `submit_order`,
  `route_order`, `execute_order`, `execute_trade`, `send_order`, `cancel_order(`, `buy_shares(`,
  `sell_shares(`.
- **None of the 9 substrings matches `place`, `cancel`, `cancel_all`, or `place_combo`.**
  `cancel_order(` requires the literal `_order(`. The previous draft's claim that "`cancel_all`
  ... will still trip it" is **false**, and presenting a false trip-wire invites a broader
  relaxation than the real one needs.
- **The real blocker is the import scan.** `iter_source_files()` (`tests/support.py:39-43`) walks
  `PKG_ROOT` = `src/signalforge` only, and `_imported_names` takes the **first dotted segment**
  of every import. So `import alpaca...` — or `tda`, `schwab`, `ibkr`, `robin_stocks` — anywhere
  under `src/signalforge` fails the test on the **bare vendor name**, which is exactly what a
  vendor adapter must do.
- **The two mechanisms are not the same size, and neither subsumes the other.** FACT:
  import-linter S1 (`pyproject.toml:195-198`) forbids only **5** modules — `ib_insync`, `ibapi`,
  `alpaca_trade_api`, `selenium`, `ccxt` — from source module `signalforge`. The test's 15 bare
  names are a **superset**. Therefore: **narrowing S1 alone does not unblock the build** (the test
  still fails on `alpaca`, `tda`, `schwab`, `ibkr`, `robin_stocks`), and **relaxing the test alone
  does not satisfy S1** (for the 5 it names). Both must be changed, deliberately and in the same
  reviewed commit — and the change to the test is a **path-prefix allowlist for exactly
  `src/signalforge/execution/brokers/`**, never a global relaxation and never a removal of a name
  from either list. See §6.8.
- Same reasoning applies to Ruff's banned-api list (`pyproject.toml:104-110`).

### 6.3 OrderIntent — where an order may come from, and why the previous rule was not fail-closed

**The hole (FACT, and it invalidates the previous draft's central claim).** The previous draft
said an `OrderIntent` may be constructed only from an already-ACCEPTED `PaperTrade` of a
PAPER_APPROVED, ARMED, in-scope strategy, and asserted "There is no other constructor. No CLI
flag, no UI button, no manual path creates an intent." That is false in substance, because
**there is already a manual path to an ACCEPTED `PaperTrade` that passes through no gate at
all**:

- FACT: `accept_candidate` (`paper/ledger.py:129-160`) checks **only** `ensure_not_engaged()`
  (`:139`), `cand.direction is not Direction.AVOID` (`:143`), and `per_share_risk > 0` (`:154`).
  It checks **no** `quality_gate_status`, **no** `StrategyVersion.status`, **no** approved scope,
  and **no** `instrument_type`. Every one of those lives in `assert_auto_simulate_allowed`
  (`ledger.py:492-505`), which is on the **automatic** path only and which `accept_candidate`
  never calls.
- FACT: it is reachable directly from the CLI — `cli.py:1158-1165`,
  `paper_accept(candidate_id)` → `accept_candidate(session, candidate_id)`, no guard, no flag.
- FACT: it **silently invents a position size** when the candidate carries none
  (`ledger.py:156-159`): `shares = max(1, int((float(acct.cash) * 0.005) // per_share_risk))` —
  a 0.5%-of-cash fallback that nothing downstream can distinguish from a risk-sized position.
- **Consequence:** a gate-**FAILED** candidate, manually accepted by one CLI command, belonging to
  a strategy that is PAPER_APPROVED, armed, and in scope, produces an ACCEPTED `PaperTrade` that
  satisfies **every condition the previous draft listed** — and would have been submitted as a
  live order at a size the system made up.

**Rule (HYPOTHESIS, fail-closed, and stated as a hard precondition rather than a docstring):**
`OrderIntent.__init__` (or its only factory) re-verifies **all** of the following against the DB
at intent time, and raises otherwise. It does **not** trust that an ACCEPTED `PaperTrade`
implies any of them:

1. The source candidate's `quality_gate_status is QualityGate.PASSED`.
2. `StrategyVersion.status is PAPER_APPROVED`, re-read now.
3. The armed record exists, is unexpired, and names this version.
4. The full approved-scope match (`approval_scope.scan_scope_matches`) **re-verified at intent
   time**, not inherited from the scan.
5. `risk_dollars` was **present on the candidate**. A `PaperTrade` whose size came from the
   `ledger.py:156-159` 0.5%-of-cash fallback is **never** an order source.
6. **The source `PaperTrade` was created by the automatic actor.** FACT: the actor is recorded —
   `accept_candidate` writes `signal_snapshot_json["decision"] = {"actor": ..., "note": ...,
   "automatic": actor == "auto_simulate"}` (`ledger.py:229`), and `auto_simulate.py:54` defines
   `AUTO_SIM_ACTOR = "auto_simulate"` and passes it at `auto_simulate.py:191`. So the predicate is
   `signal_snapshot_json["decision"]["automatic"] is True`. **A manually accepted trade
   (`actor="local-user"`, the default) is refused as an order source.**
   **Caveat (FACT):** `PaperTrade` has **no `actor` column** (`db/models/paper.py:100-117`) — the
   actor lives inside a JSON blob. An authorisation predicate should not depend on a free-form
   JSON field that any future writer could shape differently. **HYPOTHESIS: add a first-class,
   indexed `actor` column to `PaperTrade` as part of I-E2**, and key the check on that.
7. Every §3.2 limit and §6.4 limit evaluates cleanly **now**.

Any check that cannot be *evaluated* counts as a failure.

```
OrderIntent (frozen):
  client_order_id     # deterministic hash of (paper_trade_id, leg_index) — NO attempt counter
  source_paper_trade_id
  strategy_version_id ; armed_strategy_id
  symbol | option_ticker ; side ; qty ; order_type (LIMIT only in Phase 1) ; limit_price
  time_in_force (DAY only in Phase 1)
  max_notional ; created_at ; expires_at ; config_hash ; spec_json_hash
  state               # see the terminal state set below
```

**Idempotency: `attempt` must NOT be in the key (correction, rev 2).** The previous draft's
`hash(paper_trade_id, leg_index, attempt)` means a retry produces a **different**
`client_order_id` — which defeats the exact property §6.2 requires ("`place` is idempotent on
`client_order_id`") and makes a post-timeout retry a double-fill risk. **Drop `attempt` from the
key.** Attempts are tracked in `execution_event`, never in the key. **Required post-timeout
procedure:** on any timeout or ambiguous response, **query `open_orders()` and fills for that
`client_order_id` BEFORE any resubmission**; resubmit only if the broker does not know it. If the
broker reports a `client_order_id` the local store has no record of, **halt and alert** — that is
a divergence, not a retry.

**Stale intents expire (correction, rev 2).** An `OrderIntent` built from yesterday's paper trade
and submitted after a gap is a stale order at a stale limit price. `OrderIntent` therefore carries
a hard `expires_at`: **same session, and a maximum age in minutes** (operator-set). Submission
past `expires_at` is refused — it is not a warning.

**Terminal state set, with `UNKNOWN` fail-closed (correction, rev 2).** The previous draft said
"state machine" and left it undefined. The full set is:
`CREATED → VALIDATED → SUBMITTING → {FILLED | PARTIAL | REJECTED | CANCELLED | EXPIRED | UNKNOWN}`.
**`UNKNOWN` is terminal-until-reconciled and blocks all further submission** for that strategy —
it is the state a timeout, an ambiguous response, or a `SUBMITTING` record with no outcome lands
in (§6.4, kill-switch race). An `UNKNOWN` cannot be cleared by a retry; only by reconciliation
plus an operator acknowledgement.

FACT: `paper_trade`, `paper_position`, and `strategy_health` are all empty today — so there is
currently **no** paper trade from which any intent could be built. That is the correct state.

### 6.4 OMS, limits, arming, kill switch, dead man, reconciliation, audit

**New tables (HYPOTHESIS):** `armed_strategy` (version_id, armed_at, armed_by, expires_at,
max_notional, max_orders_per_day, adapter_name, **broker_account_id_expected**, disarmed_at,
disarm_reason); `execution_limits` (account-level, one active row, versioned);
`execution_event` (append-only, every intent / submission / fill / rejection / reconciliation
divergence / arm / disarm, with the redacted payload).

**Limits are split into `may_open` and `may_close` (correction, rev 2 — the previous draft's
kill switch was actively dangerous).**

FACT: the existing code already documents the correct asymmetry, verbatim at
`paper/ledger.py:271-273`: *"Closing an existing position is allowed while the kill switch is
engaged (it is protective); only opening new positions is blocked."* The previous draft threw
that away, specifying "engaged ⇒ block, plus `cancel_all()` and disarm everything". **Engaging
the kill switch on an account with an open short option leg would then cancel the resting closing
order and block every subsequent one — leaving the riskiest position in the book unmanaged. That
is the opposite of protective.**

```
may_open(intent)   — ALL must pass, fail-closed, every failure written to execution_event:
    kill switch not engaged
    execution-local kill state readable AND not engaged      (unreadable ⇒ block)
    dead man alive
    market open per adapter.clock() AND agreeing with data/options_calendar.py
    outside the no-submit windows (open auction / pre-close / early-close) — see below
    strategy armed, unexpired, adapter matches, is_paper() proven this cycle
    intent not expired (§6.3 expires_at)
    no UNKNOWN intent outstanding for this strategy
    daily order count under cap
    per-order notional under cap ; account exposure under cap
    reconciliation clean AND fresher than max_reconciliation_age_s
    every §3.2 risk limit, including net-delta and net-vega

may_close(intent)  — a SEPARATE, NARROWLY-SCOPED path:
    the intent is flattening an existing, reconciled position (verified against
      adapter.positions(), not local state alone)
    it is a closing order only — it cannot increase exposure in any leg
    it has its own execution_event record type (`protective_close`)
    it is PERMITTED while: kill switch engaged, dead man lapsed, strategy disarmed
    it is BLOCKED while: reconciliation is diverged (broker truth is unknown — closing
      into an unknown book is not protective), or the adapter is unreachable
```

**What happens to a live position when the dead man lapses (previously unstated).** The dead man
lapsing blocks all opening and auto-disarms. It does **not** auto-liquidate — an automatic
liquidation is an unreviewed order, which §6.4's reconciliation rule already forbids. Therefore:
**the operator must close the position by hand, at the broker, and the arming ceremony must say
so in those words (§6.6 step 3).** Saying nothing here is not acceptable; an operator who does not
know this before arming will discover it during an outage.

**Kill switch.** FACT: `killswitch.py` is deliberately **fail-open** — a missing or corrupt state
file is treated as "not engaged" (module docstring lines 10-16). That is right for a research
tool and **wrong** for order submission. **HYPOTHESIS:** reuse `ensure_not_engaged()` as one
input (engaged ⇒ block **opening**, permit **closing**, run the drain-and-cancel sequence below),
but add a separate execution-local state whose *unreadable* case blocks. Do not change
`KillSwitch`'s existing semantics — **FACT: 39 call sites** depend on them
(`grep -c "ensure_not_engaged(" src/signalforge` = 40 including the definition at
`killswitch.py:157`).

**Kill-switch race — a submission lock is required (correction, rev 2).** The limit checks and the
network `place()` are separate steps with a network call between them, so an order submitted
microseconds before an engage will not appear in the broker's order list when `cancel_all()` runs.
Specify:

1. Write the intent as `SUBMITTING` to `execution_event` **before** the network call, with the
   `client_order_id`. The in-flight set is therefore durable, not in-memory.
2. On engage: stop admitting new submissions, then **wait (bounded) for the in-flight set to
   drain**.
3. Then run **reconciliation**, then `cancel_all()`, then reconciliation again.
4. **A `SUBMITTING` record with no terminal outcome is an `UNKNOWN`** (§6.3) and **blocks arming**
   until an operator resolves it. It is never assumed to have failed.

**Dead man.** FACT: `WorkerHeartbeat` (`db/models/system.py:130`) exists as the pattern.
**HYPOTHESIS:** the execution dead man is the explicit inverse of the kill switch — a heartbeat
older than N seconds, or unreadable, or ambiguous, **blocks opening** and triggers the drain-and-
cancel sequence plus auto-disarm, while leaving `may_close` open. Missing evidence of health is
evidence of ill health.

**Reconciliation — with a maximum age, and a no-shared-account rule (correction, rev 2).**
Every cycle: compare `adapter.positions()` / `open_orders()` against local state. Any divergence
⇒ halt opening, disarm, alert, require operator acknowledgement. Never auto-correct — an
automatic reconciliation fix is an unreviewed order. Additionally:

- **"Clean as of the last cycle" is a stale-state check and is not sufficient.** Between cycles the
  broker side can diverge on its own: a manual trade in the same account, a broker-initiated
  liquidation, an assignment. Add `max_reconciliation_age_s` to the limit set — **an unreconciled
  window older than N seconds blocks like a dead-man lapse** — and **require a fresh
  reconciliation immediately before the first order of any session**.
- **The account must not be shared with manual trading**, and this must be **detected, not
  assumed**: any position or open order the OMS did not originate (no matching
  `client_order_id` in `execution_event`) is a **divergence** and halts. State this in the arming
  record.

**Clock, calendar, and no-submit windows (correction, rev 2 — previously one protocol method with
no rules).** `adapter.clock()` alone is not a rule. Require:

- The OMS **cross-checks `adapter.clock()` against `data/options_calendar.py`** (§2.8) every
  cycle. **Disagreement blocks** — two sources of truth that disagree about whether the market is
  open is exactly the condition under which an order should not be sent.
- A **no-submit window after the open** (the opening auction and its immediate aftermath, when
  option spreads are widest and prints are least representative) and a **no-submit window before
  the close**, both operator-set and both in `execution_limits`.
- **Early-close sessions block by default.** FACT (general information, verify with the broker):
  on U.S. early-close days equity options stop at 13:00 ET. Submission on any session the local
  calendar marks early-close is **refused unless the early-close time is explicitly handled** by
  the calendar module and the adapter's clock agrees with it.
- Index options with a 15:00-16:15 ET window are **out of scope by §2.8's underlying allowlist**;
  the allowlist is the enforcement, and the OMS asserts it rather than assuming it.

**Audit.** FACT: `audit.py::record()` already redacts `SecretStr` and credential-shaped keys via
`redact()`. Reuse it verbatim. Every `execution_event` row is append-only with the same
immutability discipline as `PaperTrade` (S9). FACT precedent for why this matters: the
2026-09-11 config-hash incident was only detectable because the scope match was recorded —
record the intent's `config_hash` and `spec_json_hash` on every event for the same reason.

**Credentials.** Env vars or macOS Keychain only, read at process start, held as `SecretStr`,
never written anywhere, never logged, never in the repo, never in the DB. FACT: no keychain
mechanism exists today — this is new code. FACT: `.env` is already the established pattern for
`SecretStr` settings. **The operator supplies these; the system never acquires, stores, or
rotates them.**

### 6.5 Multi-leg submission and partial fills (new in rev 2)

**The hole.** §6 previously mentioned `Fill` once, in a type list, and never again. A multi-leg
structure submitted **leg by leg** can end with one leg filled and the other rejected. For a put
credit spread that means the **short** leg filled and the **long wing** rejected — i.e. an
**accidental naked short option**: the exact structure §4.5 bans by design, at an approval level
the operator may not even hold, with undefined max loss and therefore no R.

**Rules (HYPOTHESIS, hard):**

1. **Multi-leg structures are submitted as a single native combo order.** One
   `client_order_id`, one atomic broker-side instruction.
2. **"Cannot submit a combo atomically" is an adapter-ineligibility condition**, alongside the
   idempotency and `is_paper()` requirements (§6.2). It is not a limitation to work around in the
   OMS.
3. **If leg-by-leg is ever permitted** (it should not be in Phase 1), the design must specify the
   unwind procedure for a partial leg fill **before** the first submission, and **an unpaired
   short leg is a halt-and-alert condition, not a position** — the OMS refuses further opening,
   alerts, and routes the unwind through `may_close` (§6.4) only.
4. **A `PARTIAL` state on a combo** (partial contract quantity, all legs proportional) is a
   legitimate outcome and is reconciled like any other; a partial *by leg* is not.

### 6.6 Paper-broker-first, and what `is_paper` has to actually mean

**HYPOTHESIS, ordered:**
1. `brokers/paper_reference.py` — a local, deterministic, **no-network** adapter implementing the
   full protocol. Everything above it (OMS, limits, arming, dead man, reconciliation, audit,
   kill-switch integration, combo submission) is built and tested against this. No credentials, no
   vendor, no internet. This is where the OMS earns trust.
2. The operator's chosen broker's **paper/sandbox** endpoint, under the same protocol, with
   `is_paper()` **proven** at arm time and re-proven every cycle.
3. Anything beyond that is a separate operator decision and is out of scope for this map.

**`is_paper` must be proven, not asserted (correction, rev 2).** The previous draft said
"adapters that cannot prove this return False" and then defined no proof. **A misconfigured base
URL is the single most likely way real money gets touched**, and a boolean derived from a local
config flag would not catch it — the flag and the URL are set in the same place by the same
mistake.

**Required proof:** the adapter calls the broker, reads the **account identifier and/or endpoint
host out of the broker's own response body**, and matches it against
`armed_strategy.broker_account_id_expected` — a value the **operator typed into the arming
record** (§6.6 step 3) out of band. A mismatch, an absent field, or an unparseable response is a
**failure**, not a warning, and it blocks arming and every subsequent submission.
**A `True` that derives from a local config flag is not proof and must not be accepted.**

**Required safety test (I-E1/I-E3):** assert that **both** `paper_reference` and any vendor
adapter **fail arming** when the account id in the (stubbed) broker response does not match the
armed record. Write this test before the vendor adapter exists.

**The operator ceremony to arm a strategy (HYPOTHESIS).** Every step is an operator action. None
is automated. None can be triggered by a document, a message, a scan result, or an agent.

1. Strategy version is PAPER_APPROVED with a passing sealed test on a named snapshot.
2. It has accumulated a stated minimum of **live paper** trades over a stated minimum window,
   with health monitor green. (FACT: R8 — live paper is the confirming test. FACT: zero live
   paper trades exist today for anything. FACT: §3.1 — for a CSP the paper stream is thin enough
   that this criterion may take years; set the window from the *expected paper rate*, not the
   backtest count.)
3. Operator writes a signed arming record naming: version, `spec_json_hash`, `config_hash`,
   snapshot id, adapter, **the expected broker account identifier**, max notional, max
   orders/day, an **expiry timestamp**, and an explicit acknowledgement of two facts: **(i)** the
   backtest approximates early assignment away (§2.7), and **(ii)** if the dead man lapses or the
   kill switch engages, **the operator closes any open position by hand at the broker** (§6.4).
4. Operator supplies credentials via env/Keychain, out of band. The system reads; it never stores.
5. `execution arm --version <id> --adapter <name> --expires <ts>` — a CLI that refuses unless
   every precondition in step 3 re-verifies **live** against the DB **and `is_paper()` proves out
   against the typed account id**, and prints the full preconditions table before asking for a
   typed confirmation.
6. Arming writes an `armed_strategy` row and an `execution_event`. It **expires automatically**.
   There is no indefinite arming.
7. Auto-disarm on any of: status change away from PAPER_APPROVED; `spec_json_hash` or
   `config_hash` drift; scope mismatch; kill switch engaged; dead man lapse; reconciliation
   divergence or staleness; an outstanding `UNKNOWN` intent; `is_paper()` failing to re-prove;
   daily cap breach; expiry.

FACT (open question flagged by the reader pass): whether `armed_strategy` should auto-disarm on
**any** `StrategyVersion` status change or only on a downgrade away from PAPER_APPROVED is an
operator decision. **HYPOTHESIS:** any change, on the fail-closed principle.

### 6.7 Regulatory and market-structure facts, and the OMS requirements derived from them

**Split into two subsections deliberately (correction, rev 2).** The previous draft mixed factual
claims about regulation with design requirements *inside a section headed "not advice"* — the
mixing is what made it read as advice. The facts stand alone below; the requirements sit with the
other limits in §6.4.

#### 6.7a Facts the operator must verify with their own broker (general information only)

- **PDT.** In a U.S. margin account, a pattern-day-trader designation attaches at 4+ day trades
  in 5 business days where those trades are a significant share of activity, and carries a
  $25,000 minimum equity requirement; falling below it restricts day trading. Cash accounts
  avoid PDT but are bound by settlement instead.
- **Options approval levels.** Brokers tier options permissions. Covered calls and cash-secured
  puts typically sit at a lower tier; **spreads require a higher tier**; naked/uncovered requires
  higher still and is out of scope here by design (§4.5).
- **Margin.** Defined-risk spreads are typically margined at max loss; cash-secured puts at full
  strike value; covered calls against the shares. Requirements differ by broker and can change
  intraday.
- **Settlement.** U.S. equities settle T+1; options settle T+1. In a cash account, using
  unsettled proceeds can cause a good-faith violation. In a margin account this is generally not
  a constraint but interest and maintenance rules apply.
- **Assignment.** American-style options can be assigned early, most commonly on short calls
  before an ex-dividend date.
- **Early close.** U.S. equity options stop at 13:00 ET on early-close sessions.

**This document does not advise on any of the above, does not recommend an account type, and
does not recommend an approval level.**

#### 6.7b OMS requirements derived from them (design, belongs with §6.4's limits)

- **Round-trip counter.** The OMS counts and displays round trips per rolling 5 business days and
  **refuses to submit an order that would cross an operator-set threshold**. The threshold is an
  operator input; the counting and the refusal are the system's job.
- **Approval-level assertion.** The arming ceremony requires the operator to assert their options
  approval level; O3/O4 cannot be armed at a level that does not permit spreads. The adapter
  surfaces the broker's own rejection **verbatim** and does **not** retry.
- **Margin is reconciled, never modelled authoritatively.** The local collateral model (§3.1) is a
  **model**; the broker's own buying-power figure is authoritative and divergence halts (§6.4).
- **Assignment divergence is disclosed at arm time.** The backtest approximates early assignment
  away (§2.7), so live realised outcomes can differ in exactly that tail; the arming record says
  so (§6.6 step 3).
- **Early-close sessions block by default** (§6.4).

### 6.8 The standing decision that must be superseded

FACT: `docs/PORTFOLIO_RESEARCH_ROADMAP.md` lines 27-67 is a current, committed, undrafted
"Non-negotiable boundaries" section stating "No brokerage, no order placement, no trade
mirroring, anywhere" and "No brokerage/Webull/order-placement integration is in scope for any
module, at any phase. This roadmap does not create one and does not plan to." FACT: this is
enforced in five independent places — import-linter S1 (`pyproject.toml:195-198`, **5 forbidden
modules**), Ruff banned-api (`pyproject.toml:104-110`),
`tests/safety/test_s1_no_broker_surface.py` (**15 banned imports, 9 banned call substrings** —
corrected, §6.2), `ARCHITECTURE.md` §1.2 V1 non-goals + the §2 invariant table, and the
unconditional promises in `README.md`, `DISCLAIMER.md`, and `docs/METHODOLOGY.md`.

**This cannot be routed around.** The required sequence (HYPOTHESIS):

1. A new ADR under `docs/decisions/` (next number after 0002) that **names** the boundary being
   superseded, quotes it, states what replaces it, and states what remains absolutely prohibited.
2. Amend all of `PORTFOLIO_RESEARCH_ROADMAP.md`, `ARCHITECTURE.md`, `README.md`,
   `DISCLAIMER.md`, `docs/METHODOLOGY.md`, and `docs/CAPABILITY_MATRIX.md` **in one commit**.
   FACT (risk): amending some and not others leaves the documents contradicting each other,
   which is worse than either state alone.
3. **Contracts — and the direction the previous draft got wrong.** Narrow S1 to `S1a` (everything
   except `signalforge.execution.brokers` still forbidden) and add `S15`. The previous draft's
   S15 constrained only **what `signalforge.execution` may import**, plus "nothing outside
   `signalforge.execution` may import `signalforge.execution.brokers`". **That leaves
   `signalforge.oms` / `signalforge.execution` itself importable by the web app, the agents
   package, and the LLM package** — so the operator's "no LLM ever decides an order" guarantee
   would have **no structural enforcement at the layer that actually submits orders**. FACT:
   S14 (`pyproject.toml:256-270`) forbids `signalforge.agents` from a hard-coded list that a new
   `signalforge.execution` module is **not** on; S3 (`:179-186`) forbids research/risk/backtest/
   paper → llm and says nothing about the reverse or about execution. Required shape — **two
   contracts, in opposite directions**:

   ```toml
   # S15a — what execution may import (outbound)
   type = "forbidden"
   source_modules   = ["signalforge.execution"]
   forbidden_modules = ["signalforge.llm", "signalforge.agents", "signalforge.alerts",
                        "signalforge.research.scan", "signalforge.sf1000"]

   # S15b — who may import execution (INBOUND — this is the one that enforces the guarantee)
   type = "forbidden"
   source_modules   = ["signalforge.llm", "signalforge.agents", "signalforge.app",
                       "signalforge.research", "signalforge.alerts", "signalforge.sf1000"]
   forbidden_modules = ["signalforge.execution"]      # the WHOLE package, not just .brokers
   ```

   **And add `signalforge.execution` to S14's `forbidden_modules` in the same commit**, so the
   agents contract names it explicitly rather than relying on S15b alone. FACT (open question):
   whether to narrow S1 via `ignore_imports` or to replace it with an S1a+S15 pair is an operator
   choice; the S1a+S15 pair is more legible in a diff.
4. Rewrite `tests/safety/test_s1_no_broker_surface.py` with an explicit **path-prefix allowlist
   for exactly `src/signalforge/execution/brokers/`** — **before** any execution code is written,
   so the test's new shape is reviewed on its own rather than as a fix to a red build. The
   rewrite touches the **15-name `BANNED_IMPORTS` scan** (the real blocker); it does **not** need
   to touch `BANNED_CALL_SUBSTRINGS`, because none of the nine matches the protocol method names
   of §6.2 (§6.2, corrected). **Do not remove a name from either list.** Note that S1's 5-module
   list and the test's 15-name list are different sizes: **both** must be changed, and changing
   either alone leaves the build red or the contract violated.
5. Add new safety tests: no `signalforge.execution` import from research/paper/backtest/llm/
   agents/app (the S15b direction, tested as well as contracted); no credential literal anywhere;
   `OrderIntent` constructible only under the seven preconditions of §6.3 — including a test that
   a **manually accepted** `PaperTrade` is refused as an order source, and a test that a
   gate-FAILED candidate cannot produce an intent; `client_order_id` stable across retries;
   default-disabled asserted; `is_paper()` proof fails arming on an account-id mismatch (§6.6).

---

## 7. Phased team plan

Roles below are **agent roles**, not people. FACT (from the operator's standing delegation
rules): the orchestrator owns architecture, integration, and safety; Sonnet subagents take
bounded parallel work; all gates re-run after every integration.

### Phase U — Understand (this document, plus what it did not reach)

Produces: this map; a full read of `docs/research/designs/` and `docs/research/diagnostics/`
(FACT: untracked per git status, not opened in this pass — they contain the
volatility_breakout / mean_reversion / intraday_orb design docs referenced by
`DECISIONS_2026-09-10.md`); a full read of `research/approval_scope.py` (FACT: read only via its
call sites so far); and vendor-documentation answers to the three data questions in the decision
list below. **Exit criterion: the operator has read §0.4 and agrees with its characterisation
of the equity evidence — including the corrected facts that look counting is automatic, that
both live strategies stand at k=4, and that equities NBBO is 403 exactly as options NBBO is.**

### Phase D — Design (documents only; no code)

| Workstream | Produces | Role |
|---|---|---|
| D1 Options data spec | Point-in-time reference-price algorithm; per-cycle cap design; adapter pacing design; the IV-source decision incl. §2.4b's same-session surface and its N floor; the `q` decision (§2.4a); `options_scope_json` snapshot identity and **which side of S11 writes it** (§3.5) | data architect |
| D2 Options engine spec | `options_engine.py` interface; leg/structure dataclasses with `shares_per_contract` read per leg; fill model incl. print-not-mid, full-spread, missing-bar-is-a-non-entry; cost model; the two-spread rule; expiry/force-close pricing with intrinsic floor and pin band; `options_calendar.py` **designed for its execution-layer consumer too** | backtest architect |
| D3 Options risk/paper spec | Collateral ledger and its §3.1 reconciliation against the paper trade rate; options limits incl. net-delta/net-vega and the `min_credit_to_width` + `max_short_delta` pair; `mark_options_to_market`; `assert_options_auto_simulate_allowed`; the type assertion added to the *existing* `mark_to_market` | risk architect |
| D4 Options gate spec | Gate 0.a-0.h; gate 0.5 **one-structure-per-version**; gate 4b dual-spread **on both asset classes**; gate 6 joint trend×vol buckets; **gate 7 kept + gate 7b added**; gate 8 additions incl. clamp/pin/stop-binding counts; the §5.3 arithmetic re-run on the actual coverage summary | evidence architect |
| D5 Strategy pre-registration | The **first** strategy (O1 or O3 — decision #12) fully pre-registered: params, complete grid, disposition rule, falsification criteria, **the gate 0.c/0.d fractions, the §2.4b surface N floor, and the pin band** — before any price, IV, or return series is looked at | strategy author |
| D6 Execution design + ADR | The ADR of §6.8; protocol; OMS state machine incl. the full terminal state set; `may_open`/`may_close` split; the submission lock; reconciliation max-age; the `is_paper` proof; the combo-order requirement; the safety-test rewrite plan | orchestrator (not delegated) |

**Exit criterion: D6's ADR is approved by the operator in writing, and the amendment commit of
§6.8 step 2 is merged, before a single line of execution code is written.**

### Phase I — Implement

Two independent tracks. The execution track must **not** wait on the options track, and must
**not** ship ahead of its own gates.

**Options track, in strict order:**
I-O1 adapter pacing + `--lookback-days` + per-cycle caps + point-in-time reference (D1) →
I-O2 the real backfill run, resumable, with `IngestionRun` provenance →
I-O3 `options_engine.py` single-structure + `OptionCostModel` + `options_calendar.py` →
I-O4 options gate ladder wiring →
I-O5 the first strategy class (the first strategy anywhere to implement `sensitivity_axes()`) →
I-O6 options paper mechanics: collateral ledger, options mark, expiry processing, the second
guard. **Gate: I-O3 through I-O5 must pass on the first structure before a second structure type
is started** (and a second structure is a new version with a new sealed look, §5.2 gate 0.5).

**Pre-registration ordering — the conflict, and its resolution (correction, rev 2).**
I-O2 (the real backfill) necessarily runs **before** D5's pre-registration is complete in
wall-clock terms, while R1 requires pre-registration "before any data is looked at". These are
reconcilable only if what the backfill exposes is bounded. **Rule:**

- The **only** output of I-O2 visible before D5 is committed is a **coverage summary**:
  per (underlying, cycle) — whether the chain brackets the target, contract counts per side,
  bar-continuity fractions, exclusion counts, `shares_per_contract != 100` counts, and
  `IngestionRun` gaps. Counts and completeness, nothing else.
- **No price, IV, greek, return, credit, or P&L series may be inspected — by a person or by a
  script — until D5 is committed.** That includes summary statistics over them.
- The coverage summary is exactly what D1/§3.5 needs to fix `options_scope_json` and what §5.3
  needs to re-run its arithmetic on real counts. It is deliberately the minimum that lets D5's
  parameters be chosen without seeing any outcome.
- **The 0.c/0.d fractions are pre-registered before I-O2 completes** (§1.5), so they cannot be
  set to whatever the coverage summary happens to support.

**Execution track, in strict order:**
I-E1 safety-test rewrite + S1a/S15a/S15b contracts + the S14 addition (nothing else in the same
commit) →
I-E2 `execution/` skeleton, default-disabled, protocol + intents + limits + audit, no adapter;
**plus the `PaperTrade.actor` column of §6.3(6)** →
I-E3 `paper_reference` adapter, no network, incl. combo submission and the `is_paper`-mismatch
test →
I-E4 OMS + arming + dead man + reconciliation + submission lock, all exercised against
`paper_reference` →
I-E5 the operator's chosen broker paper adapter. **Gate: I-E4 must be complete and adversarially
tested before I-E5 begins.**

### Phase V — Validate

- Options: gate ladder end to end on the first structure; sealed look **k=1** for the options
  family (read from `count_sealed_looks`, not asserted); disposition recorded in
  `docs/research/dispositions/` in the existing format, naming the structure type and its R basis
  (§5.1).
- Execution drills against `paper_reference`: kill-switch **with an open position** (verifying
  `may_close` still works while `may_open` is blocked); dead-man lapse; reconciliation divergence;
  reconciliation **staleness**; duplicate-`client_order_id`; **post-timeout non-duplication**;
  **`SUBMITTING`-with-no-outcome → `UNKNOWN` → blocked arming**; **combo partial fill**;
  **`is_paper` account-id mismatch**; clock/calendar disagreement; intent expiry.
- Then the same drills against the vendor paper endpoint with **zero** armed strategies; then one
  armed strategy at the smallest viable size for a stated observation window with daily
  reconciliation review.
- FACT: all existing gates (`make secrets`, import-linter, Ruff, the safety tests) re-run after
  every integration. FACT (memory): the secret-scan gate is a real check-only gate and its
  baseline must never be casually rewritten.

### Decisions only the operator can make

| # | Decision | Blocks |
|---|---|---|
| 1 | Authorise superseding the "no brokerage, at any phase" boundary; approve the ADR | All of §6; Phase I-E entirely |
| 2 | Which broker, and paper endpoint only | I-E5 |
| 3 | The operator's actual options approval level | Whether O3/O4 are reachable at all |
| 4 | **Every capital limit in §3.2** — per-structure max loss, aggregate max loss, collateral cap, net-delta cap, net-vega cap, per-order notional, daily order cap, account exposure cap, arming expiry duration, PDT threshold | I-E4, D3 |
| 5 | Options data spend: plan/entitlement, and whether to buy NBBO — **noting that equities NBBO is also 403 today**, so the purchase decision covers both | §1.2 sizing; whether §2.4's modelled spread stays a permanent assumption; gate 4b's permanence |
| 6 | Raise `backfill_max_total_bars` past 200,000, recorded as a decision | I-O2 |
| 7 | Greeks/IV path: local Black-Scholes inversion + the §2.4b same-session surface (history-capable) vs a forward-only dated vendor snapshot series | D1, gate 0.e |
| 8 | Whether O2 (covered call) is deferred behind O3 on the R-comparability grounds of §4.2 | D5 sequencing |
| 9 | Whether `armed_strategy` auto-disarms on any status change or only on a downgrade | I-E4 |
| 10 | Whether to accumulate more live paper evidence on the two approved equity strategies before arming anything (§0.4) | Phase V gating |
| 11 | **Dividend yield (§2.4a): code-enforced low-dividend underlying allowlist, or source and record `q`** — noting the allowlist route may exclude SPY/IWM and thin out §5.3 | D1, D5, gate 0.g |
| 12 | **Which structure ships first — O1 (CSP) or O3 (vertical)** — given that §3.1 (collateral wall in paper), §5.3 (O1 cannot pass gate 6 while skipping bear), and §2.4a (allowlist may exclude SPY/IWM) all now argue for the vertical, against §4.1's "least new machinery" argument | D5, I-O3, I-O5 |
| 13 | **Whether paper-account size is raised to the strategy, or the backtest and paper streams are accepted as different populations feeding different gates** (§3.1) | D3, gate 10 window |

---

## Appendix A — Critic responses

An adversarial verification pass re-checked every quantitative claim in rev 1 against the source
tree and the live DB (read-only SELECTs; no files modified; no network). **38 defects were
raised. All 38 were accepted** — every one reproduced. Four were accepted **with a refinement**
noted below, and one **additional** defect was found during the re-verification and is recorded
at the end. **No defect was rejected.**

### Accepted as stated (34)

| # | Defect | Where fixed |
|---|---|---|
| 1 | "No look-counting code exists" is false, stated twice | §0.2 table, §0.4, §2.2 table, §5.4 (rewritten) |
| 2 | "k=5, 20 rows, 4 snapshots, 5 families" false on all three numbers | §0.4 (22 rows, 5 snapshots, per-family table), §5.4 |
| 4 | "29 call sites" wrong (39) | §6.4 |
| 5 | `spread_bps` is a kwarg default, not hard-coded | §0.4, §5.2 gate 4b |
| 7 | S11's scope understated (two source modules) | §3.5, §3.6 |
| 8 | Fill model circular — no IV where no bar | §1.3 D5, §2.4b (new) |
| 9 | Missing bar is a liquidity fact, not a fill | §2.4(3), §2.7, §5.2 gate 8 |
| 10 | Close treated as mid | §2.4(1), renamed `last_print`, full spread |
| 11 | `multiplier = 100` hard-coded; schema has the real one | §2.3, §2.6, §3.1, gate 0.h |
| 12 | No dividend yield in the pricing path | §2.4a (new), D8, gate 0.g, decision #11 |
| 13 | Expiry/pin behaviour unspecified | §2.7 (rewritten) |
| 14 | `pnl_r` not actually bounded at −1 | §2.6 (measure, don't assert) |
| 15 | `bars_held` understates the exposure dimension | §2.2 caveat, §2.3 `dte_at_entry/exit` |
| 16 | R = max loss makes frozen thresholds structure-dependent | §5.1 (rewritten) — **the document's most important correction** |
| 17 | Collateral never reconciled against §5.3's trade count | §3.1, decision #12, decision #13 |
| 18 | Gap risk never modelled | §5.2a (new) |
| 19 | No options analogue to correlated exposure | §3.2 (net-delta / net-vega caps) |
| 20 | `min_reward_to_risk` dismissed, not replaced with something binding | §3.2 (`min_credit_to_width` paired with `max_short_delta`) |
| 21 | A manual path to an ACCEPTED `PaperTrade` exists with no gates | §0.1 B2, §6.3 (rewritten) |
| 22 | Nothing stops app/agents/llm importing the OMS | §0.1 B3, §6.8 step 3 (S15a + S15b + S14) |
| 23 | Kill switch has no protective-exit path | §6.4 (`may_open` / `may_close`) |
| 24 | `attempt` in the idempotency key defeats idempotency | §6.3 |
| 25 | Partial fills never mentioned | §6.5 (new) |
| 26 | "Reconciliation clean as of the last cycle" is stale-state | §6.4 (max age, pre-session, no shared account) |
| 27 | Stale intents have no expiry | §6.3 (`expires_at`, terminal state set) |
| 28 | Clock/holiday handling is one method with no rules | §6.4, §2.8 |
| 29 | Kill-switch race with in-flight `place()` | §6.4 (submission lock, drain, `UNKNOWN`) |
| 30 | `is_paper` asserted, never proven | §6.2, §6.6 (proof + required test) |
| 31 | Gate 7 replacement is a relaxation and inverts R4 | §5.2 (gate 7 kept, 7b added) |
| 32 | Gate 0.c/0.d fractions set after the data is in hand | §1.5 (pre-registered, in `config_hash`) |
| 34 | §5.3's arithmetic asserted, not shown | §5.3 (rewritten with the split and every floor) |
| 35 | Phase-ordering conflict: I-O2 precedes D5 | §7 Phase I (coverage-summary-only rule) |
| 37 | §6.7's PDT paragraph edges into instruction | §6.7a / §6.7b split |
| 38 | Closing line reads as a standing property | Appendix C |

### Accepted with a refinement (4)

**3 — safety-test counts and the precise blocker.** Accepted and reproduced exactly: 15
`BANNED_IMPORTS` (not 18), 9 `BANNED_CALL_SUBSTRINGS`, none matching `place`/`cancel`/
`cancel_all`; `iter_source_files` walks `src/signalforge` only; S1 lists 5 modules against the
test's 15. **Refinement:** the critic's framing "narrowing S1 alone does not unblock, relaxing
the test alone does not satisfy S1" is right, and §6.2 now adds the operational consequence —
the two must change in the **same reviewed commit**, and §6.8 step 4 states that the rewrite does
**not** need to touch `BANNED_CALL_SUBSTRINGS` at all, which keeps the relaxation strictly
smaller than rev 1 implied.

**6 — equities NBBO is equally unentitled; 8→7 batches.** Accepted and reproduced: `/v3/quotes/
{O:contract}` and `/v3/quotes/{sym}` are both 403 `not_authorized` in **7 of 7** distinct
`batch_id`s (2026-09-07 18:13 → 2026-09-09 06:34). **Refinement on "make gate 4b's equity
application required":** accepted, with a constraint the critic did not state. FACT:
`StrategySealedTest` is unique on `(version, snapshot)` and is **reused, never recomputed**
(`promotion.py:1237-1296`), so a 2×-spread run **cannot** re-seal an existing record. §5.2 gate 4b
therefore specifies the only R1/R3-compatible form: run 4b on the **pre-sealed** span, publish it
as evidence, and treat a 2× failure as a **disposition** input requiring a **version bump** —
never a silent re-seal. Without that constraint, "required retroactively" would have invited
exactly the re-look R3 forbids.

**21 — manual-accept path.** Accepted in full and reproduced line by line (`ledger.py:129-160`,
`cli.py:1158-1165`, the 0.5%-of-cash fallback at `:156-159`). **Refinement on the fix:** the
critic's proposed predicate — "require the source `PaperTrade` to have been created by the *auto*
actor" — is correct but **not cleanly implementable today**. FACT: `PaperTrade`
(`db/models/paper.py:100-117`) has **no `actor` column**; the actor is written into
`signal_snapshot_json["decision"]` (`ledger.py:117,229`). §6.3(6) therefore states the predicate
**and** requires a first-class indexed `PaperTrade.actor` column as part of I-E2 — an order
authorisation predicate should not depend on the shape of a free-form JSON blob that a future
writer could change without breaking anything visible.

**33 — gate 0.5 does not go far enough.** Accepted, and strengthened past what was asked. The
critic proposed one structure type per strategy version with the multiplicity cost paid per
family. §5.2 adopts that **and** removes the per-structure trade floor it replaces, because with
one structure per version the floor is subsumed by `min_oos_trades = 30`; keeping both would have
implied a structure allowlist still existed somewhere. §3.6's guard and §5.1's anti-pooling rule
were updated to match, so no path can construct a mixed-structure R sequence.

### Also accepted, as framing rather than fact (36)

**36 — parameter values presented as defaults in the operator's own account context.** Accepted.
Every numeric risk limit is relabelled as an **evaluation grid centre** (§3.2 preamble, repeated
in §4's preamble and in each strategy block), and §3.2 now states explicitly that every capital
limit is an operator decision — resolving the contradiction with §7 decision #4, which has also
been widened to enumerate all of them.

### Found during re-verification, not in the critic's list (1 new)

**39 (new) — O1 as specified cannot pass gate 6, for a structural reason no amount of data
fixes.** Surfaced only when §5.3's arithmetic was actually worked rather than asserted. FACT:
`_regime_census` buckets are exactly `{"bull", "bear", "range"}` (`promotion.py:385`) and
`min_regimes_covered = 3` with the config comment "all three required, not 'at least two of
three'" (`config/research.py:110`), checked as `covered >= 3` (`promotion.py:1128-1129`). FACT:
O1's specified `regime_filter` is "skip bear/risk_off" (§4.1). **A strategy that refuses to trade
in bear regimes books zero bear trades and can never satisfy the gate.** Recorded in §5.3 with
three ways out — trade the call-side mirror in bear, size down rather than skip, or accept that
the gate is doing its job — all of which are **design** decisions that R1 requires be made before
any data is inspected. It is the third independent argument (with §3.1's collateral wall and
§2.4a's possible SPY/IWM exclusion) for sequencing the vertical ahead of the cash-secured put,
and it is now operator decision #12.

---

## Appendix B — claim ledger

Every FACT in this document traces to one of:
`src/signalforge/{backtest,research,risk,paper,data,db,config,options}/**`,
`tests/safety/test_s1_no_broker_surface.py`, `tests/support.py`, `pyproject.toml`,
`ARCHITECTURE.md`, `docs/PORTFOLIO_RESEARCH_ROADMAP.md`, `docs/CAPABILITY_MATRIX.md`,
`docs/PAPER_PROBATION_ACTIVATION.md`, `docs/research/STRATEGY_COMPLETION_MAP.md`,
`docs/research/DECISIONS_2026-09-10.md`, `docs/MARKET_DATA_SETUP.md`,
`reports/OPTIONS_BACKFILL_SMOKE_TEST.md`, `docs/SF1000_SPEC.md`, or a read-only SELECT against
`data/signalforge.sqlite` (tables: `option_contract`, `option_quote_snapshot`,
`option_aggregate_daily`, `ingestion_run`, `entitlement_check`, `strategy_sealed_test`,
`strategy_version`, `strategy`, `paper_trade`, `paper_position`, `strategy_health`,
`paper_account`).

Rev-2 verification queries, reproduced for audit (all read-only):

```sql
select count(*) from strategy_sealed_test;                          -- 22
select count(distinct dataset_snapshot_id) from strategy_sealed_test; -- 5
select s.name, count(*) from strategy_sealed_test t
  join strategy_version v on v.id = t.strategy_version_id
  join strategy s on s.id = v.strategy_id group by s.name;          -- per-family k
select endpoint, http_status, error_category, count(distinct batch_id)
  from entitlement_check group by 1,2,3;                            -- /v3/quotes 403 x2, 7 batches
select count(*) from paper_trade;                                   -- 0
```

Everything else is HYPOTHESIS: a proposal, not a finding. In particular the following are
**explicitly unverified** and must be resolved before they are relied on —
the historical depth of the options aggregates endpoint under the `options_developer`
entitlement; any options-specific rate limit or price; every vendor broker-API claim in §6
(no network calls were made in either pass); the contents of `docs/research/designs/` and
`docs/research/diagnostics/`; the full source of `research/approval_scope.py`; and the assumed
per-trade standard deviation used in §5.3's gate-4 sensitivity arithmetic, which is a plausibility
illustration and not a measurement.

---

## Appendix C — scope of the read-only passes that produced this document

**During the mapping pass (rev 1) and the verification pass (rev 2) that produced this document:
no order was placed, no credential was read, no provider or network endpoint was contacted, and
no repository file other than this one was created or modified.** All database access was
read-only `SELECT` against `data/signalforge.sqlite` while the live paper-probation worker was
running.

That statement describes **these two passes only**. It is not a standing property of the
document, of the repository, or of any future phase — §6 exists precisely because the operator
intends to change it, and §6.8 describes the written supersession that must happen first.
