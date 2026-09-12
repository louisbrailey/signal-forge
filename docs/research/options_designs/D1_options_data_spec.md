# D1 — Options data spec

Workstream **D1** of `docs/research/OPTIONS_EXECUTION_PROGRAM_MAP.md` §7 Phase D.
Status: **DESIGN ONLY.** No code, config, schema, contract, or gate was changed to produce
this document. No provider API was called. No package was installed. Every database access
was a read-only `SELECT` against `data/signalforge.sqlite` while a live paper probation was
running.

Written 2026-09-11. Repo `/Users/louisbrailey/signal-forge`.

Binding inputs, not re-litigated here:
`docs/research/DECISIONS_2026-09-12_options_execution.md` (decisions 5, 6, 7, 11, 12, 13),
`docs/research/OPTIONS_EXECUTION_PROGRAM_MAP.md` §0, §1, §2.4a, §2.4b, §3.5, §3.6, §5.4, §7,
and `docs/research/STRATEGY_COMPLETION_MAP.md` §1 (R1–R10).

Labelling convention, as required: **FACT** carries a `file:line` or a read-only query.
**HYPOTHESIS** is a design proposal that nothing in the repo yet establishes.

---

## 0. What this document decides, and what it hands to D5

D1 fixes the **shape of the options dataset** and the **provenance of every derived
quantity** before any of it exists. It does not choose a strategy, a delta target, a
spread width, or a disposition rule — those are D5's.

Everything in §12 is **pre-registered**: written down here, before the backfill has run and
before any price, IV, greek, return, credit, or P&L series has been looked at. R1 requires
that ordering, and §7's "Pre-registration ordering" rule makes it operational. §11 states
exactly what was and was not observed to produce this document.

### 0.1 Disclosure — what was inspected to write this (R1 compliance)

Read-only queries were run against the live DB. They returned, in full:

| Inspected | Kind of thing | Permitted before D5? |
|---|---|---|
| `option_contract`: row counts, distinct underlyings, expiration dates, strike ranges, distinct-strike counts per expiry | Reference metadata + counts | Yes — counts and contract identity, no prices |
| `option_aggregate_daily`: row count (110), min/max `session_date` | Counts and dates | Yes |
| `option_quote_snapshot`: row count (878) | Count | Yes |
| `ingestion_run` where `kind LIKE '%option%'`: ids, status, windows, `bars_written` | Provenance | Yes |
| `entitlement_check`: endpoint / http_status / error_category counts | Entitlement | Yes |
| `ohlcv_daily` for the 24 underlyings: per-symbol row counts, first/last session, source split, and the **single latest close (2026-09-11) per symbol** | Equity bars | Yes — equity, not options; used only for the strike-ladder sizing arithmetic in §7, which fixes call counts, not outcomes |
| `ohlcv_daily` NVDA closes 2024-06-05..2024-06-13 | Equity bars | Yes — used only to demonstrate the split-adjustment hazard in §2.3 |
| `corporate_action`: row count (0), `data_snapshot` rows | Counts / metadata | Yes |
| **(rev 2)** `ohlcv_daily` closes for the 24 underlyings on **each of the 34 cycle entry dates** 2023-09..2026-08 | Equity bars | Yes — equity, not options; used only for the strike-ladder coverage arithmetic in §3.3/§7.2, which fixes call counts and a pre-registered exclusion rule, not outcomes |
| **(rev 2)** `ohlcv_daily` total row count and the count of rows violating `div_cash<>0` / `split_factor<>1.0` / `adj_close<>close` | Counts | Yes — restates F24 reproducibly |
| **(rev 2)** `option_contract` `created_at` min/max | Provenance timestamps | Yes — establishes F41 (no expired contract has ever been returned) |
| **(rev 2)** `entitlement_check` distinct endpoint count | Entitlement | Yes |

**No option price, IV, greek, return, credit, or P&L value — and no summary statistic over
any of them — was read.** The 110 existing `option_aggregate_daily` rows were counted and
date-bounded, never priced.

**Revision note (rev 2, 2026-09-11).** This document was revised in place after an adversarial
verification pass re-checked every quantitative and citation claim against the source tree and
the live DB. Twenty defects were confirmed and fixed; see the **Judge responses** appendix for
what changed, what was rejected, and why. Three of the fixes are new blockers (D13, D14, D15)
and one of them — D13 — **voids every figure in §7 until a single probe request returns rows**.

---

## 1. FACT baseline — what exists today

| # | Fact | Evidence |
|---|---|---|
| F1 | Options reference/aggregate/snapshot tables exist and are migrated | `src/signalforge/db/models/market.py:240-318` |
| F2 | `OptionAggregateDaily` carries OHLCV + vwap + transactions only — **no IV, greeks, OI, bid, or ask** | `market.py:290-318` |
| F3 | `OptionQuoteSnapshot` carries `vendor_iv`, `vendor_greeks_json`, `open_interest`, but is a point-in-time row keyed on `as_of`, not on a session date | `market.py:260-288` |
| F4 | Live options coverage: `option_contract` 888 rows, **all SPY**, expirations 2026-09-08 → 2026-10-16; `option_aggregate_daily` 110 rows, sessions 2026-07-31 → 2026-09-04; `option_quote_snapshot` 878 rows | read-only query, 2026-09-11 |
| F5 | Four `ingestion_run` rows with `kind='options_agg_backfill'` (ids 2-5), all `symbols_requested=["SPY"]`, `bars_written` 100 / 0 / 0 / 10 | read-only query |
| F6 | NBBO is 403 `not_authorized` in 7 of 7 batches on **both** `/v3/quotes/{O:contract}` and `/v3/quotes/{sym}` | `entitlement_check` query |
| F7 | `/v3/reference/options/contracts`, `/v3/snapshot/options/{underlying}` (incl. greeks / IV / OI), `/v2/aggs/ticker/{O:contract}/...`, `/v3/trades/{O:contract}`, `/v2/last/trade/{O:contract}` all return 200 | `entitlement_check` query |
| F8 | The only documented pacing figure anywhere is `market_data_min_request_spacing_s = 12.1` (equities Basic, 5 req/min) | `src/signalforge/config/settings.py:54-56` |
| F9 | `options_api_key` falls back to `market_data_api_key` | `src/signalforge/data/adapters/massive_options.py:107-113` |
| F10 | The options adapter makes **one HTTP attempt** and raises immediately on 429 — no sleep, no backoff, no spacing | `massive_options.py:116-140` (429 at `:132`) |
| F11 | The equities adapter self-paces to `_spacing_s` and retries `{429,500,502,503,504}` up to `_MAX_ATTEMPTS=5` with exponential backoff `1.5s → 30s` cap, honouring `retry-after` | `massive.py:43-46,109-162` |
| F12 | `_reference_price` is the single most recent stored `OHLCVDaily.close`, one value per underlying per run, source-unfiltered | `data/options_backfill.py:77-89` |
| F13 | `win_start = max(start, date.today() - timedelta(days=caps.lookback_days))`; `lookback_days` defaults to 365 and there is no `--lookback-days` CLI flag | `options_backfill.py:205`; `cli.py:341-427`; `config/research.py:212` |
| F14 | `Settings.model_config` has no `env_nested_delimiter`, so `OptionsConfig` is **not** env-settable | `config/settings.py:29-34` |
| F15 | `contracts_per_underlying` (default 40) caps the ATM-ranked pool **per underlying across all kept expirations** | `options_backfill.py:140-141`; `config/research.py:214` |
| F16 | `expirations_per_underlying` (default 4) keeps only the **nearest** N expirations from the whole returned set | `options_backfill.py:130-132`; `config/research.py:213` |
| F17 | The per-contract fetch range is `[max(win_start, last_covered+1), min(win_end, expiration)]` — i.e. **the whole backfill window**, not the cycle's trade window | `options_backfill.py:317,325-327` |
| F18 | `_MAX_BARS_PER_CONTRACT = 800`; `backfill_max_total_bars` default 200,000 | `options_backfill.py:55`; `config/research.py:216` |
| F19 | `backfill_option_aggregates` writes a real resumable `IngestionRun` with caps in `notes`, per-underlying `gaps_json`, `symbols_ok`, `symbols_failed`, and a per-contract checkpoint flush | `options_backfill.py:214-232,406-418` |
| F20 | `options_ingest.py` writes **no** `IngestionRun` row — the string does not appear in the file | grep, `data/options_ingest.py` |
| F21 | The whole backfill runs inside **one** `session_scope(write=True)`, spanning every network call | `cli.py:389-419` |
| F22 | `session_scope(write=True)` begins `IMMEDIATE` on SQLite and its own docstring says "Keep write scopes SHORT and never span network I/O inside one" | `db/session.py:99-115` |
| F23 | `corporate_action` has **0 rows**, and `MassiveAdapter.fetch_corporate_actions` returns `()` — "not offered by this feed" | query; `massive.py:225-228` |
| F24 | `ohlcv_daily` rows **violating** `div_cash <> 0`: **0**; violating `split_factor <> 1.0`: **0**; violating `adj_close <> close`: **0**; NULLs in any of the three: **0**. Table stood at **1,686,930** rows when counted, 2026-09-11 (it grows under the live worker, so the denominator is a timestamped observation, not a constant). *(rev 2: the previous wording quoted two different denominators — 1,457,903 and 1,460,392 — for one table, neither reproducible. The conclusion is unchanged and re-verified: there is no dividend or split information anywhere in the equity series.)* | query, 2026-09-11 |
| F25 | NVDA closes 2024-06-05..2024-06-13 run $122.44 → $129.61 with no discontinuity across the 2024-06-10 10:1 split — the stored series is **back-adjusted**, and nothing in the schema marks the event | query |
| F26 | `blackscholes.price/greeks/implied_vol` take continuous dividend yield `q` with **default 0.0**. `implied_vol` returns `None` in exactly three cases: `t <= 0`, `target_price <= 0`, or `target_price` outside `[lo_bound - tol, hi_bound + tol]` where `lo_bound = price(σ=1e-6)` and `hi_bound = price(σ=5.0)` (`blackscholes.py:106-111`). **It does NOT return `None` on non-convergence** — after `max_iter=100` bisection steps it falls out of the loop and returns `0.5*(lo+hi)`, a float indistinguishable from a converged solve (`blackscholes.py:112-123`). *(rev 2: the previous wording said "returns `None` … or does not converge", which is false and made §5.2's `non_convergent` reason unreachable — see §5.2.)* | `options/blackscholes.py:48,63,92-123` (`return 0.5 * (lo + hi)` at `:123`) |
| F27 | `OptionsConfig.risk_free_rate = 0.04` — a single constant, no term structure, no point-in-time series | `config/research.py:205` |
| F28 | `SCOPE_HASH_FIELDS` **excludes** `options` (and `promotion`, `news`, `agents`, `universe_pipeline`, `health_monitor`) | `config/research.py:392-409` *(rev 2: the previous citation `:345-362` was wrong — that range is unrelated `ResearchConfig` field declarations. The listed values are unchanged and re-verified.)* |
| F29 | **The database enforces `key` ALONE.** `__table_args__ = (UniqueConstraint("key"),)` — nothing else is in the constraint. `symbols_json` and `continuity_mapping_id` are checked only **procedurally**, inside `if key is not None` (`promotion.py:605-622`, `ValueError` on mismatch); `description` and `source_note` are **never checked at all**. When `key is None` a second branch (`promotion.py:624-631`) returns the **first** snapshot marked `reusable_by_new_evaluations` whose sorted symbol set matches, consulting nothing else — that branch minted live rows ids 6, 8 and 10 (`universe_auto_*`). *(rev 2: the previous wording asserted a five-part composite identity. It was false, and §9.2 was built on it — see §9.2.)* | `db/models/research.py:235`; `research/promotion.py:573-631`; query (data_snapshot ids 6/8/10) |
| F30 | Gate 0's window arithmetic: `MIN_PRESEALED_DAYS = ceil(200 * 365.25 / 252) + 60 = 350`; `sealed_window_days = 365`; the fail condition is `sealed_start <= start or (pre_sealed_end - start).days < 350` | `promotion.py:106,954-966`; `config/research.py:127` |
| F31 | `count_sealed_looks(session, strategy_name)` keys on `Strategy.name`, so a new options family starts at **k=0 with no new code** | `promotion.py:647`, captured at `:924`; map §5.4 (whose `:615` citation is stale) |
| F32 | S11 forbids `signalforge.options` **and** `signalforge.data.options_backfill` from importing `alerts`, `llm`, `research.scan`, `research.candidates`, `paper.ledger` | `pyproject.toml:210-220` |
| F33 | `MassiveOptionsAdapter._get` calls `ensure_not_engaged()` before every request — the kill switch already halts the backfill | `massive_options.py:117` |
| F34 | `IngestionRun.kind` is `String(16)`, but the value written is `'options_agg_backfill'` (20 chars) | `market.py:367-369`; `options_backfill.py:214-217` |
| F35 | The 24-symbol approved universe is `data_snapshot` id 3, `universe_24_ex_meta` = the 25-symbol configured universe minus META | query; `config/research.py:270-299` |
| F36 | All 24 of those symbols have `ohlcv_daily` rows from source `massive` spanning 2016-10-17 → 2026-09-11 (2,489 sessions; XLC 2,069 from 2018-06-19) | query |
| F37 | For SPY expiry 2026-09-30, the stored chain holds 123 distinct strikes over 709.0 → 831.0 — a **$1.00 ladder** across a ±8% band | query |
| F38 | The `fetch_contracts` request is filtered **server-side** by `strike_price.gte/lte`, so contracts outside the band were never returned to Signal Forge | `massive_options.py:152-180`; `reports/OPTIONS_BACKFILL_SMOKE_TEST.md` |
| F39 | A smoke-test SPY pull at ±2% over 6 expirations produced a 972-contract candidate pool, 276 inside the kept expirations | `reports/OPTIONS_BACKFILL_SMOKE_TEST.md` |
| **F40** | `fetch_contracts` builds its query from `underlying_ticker`, `expiration_date.gte/lte`, `limit`, `sort` and optional `strike_price.gte/lte` — **and nothing else**. It sends **no `as_of` (point-in-time) parameter** and **no expired-contracts flag** | `massive_options.py:152-180` |
| **F41** | `OptionContract` carries **no listing / first-traded date** — `option_ticker`, `underlying_symbol`, `contract_type`, `strike_price`, `expiration_date`, `exercise_style`, `shares_per_contract`, `source`, `ingested_at` only. So point-in-time strike existence cannot be established from any stored column | `market.py:240-258` |
| **F42** | All 888 `option_contract` rows were created 2026-09-07 18:30 → 2026-09-08 03:21 with expirations 2026-09-08 → 2026-10-16 — i.e. **every contract ever returned to this repo was unexpired at fetch time**. No expired contract has ever come back through this code path | query, 2026-09-11 |
| **F43** | `_paginate` loops `while next_path and pages < _MAX_PAGES` with `_MAX_PAGES = 20` and **raises nothing when it stops at the cap**; `fetch_contracts` defaults to `limit: int = 250` (not 1000) and **silently `continue`s past any row that fails parsing** | `massive_options.py:35,142-150,160,186-187` |
| **F44** | `options_backfill.py` contains `session.flush()` at 7 sites (`:186,232,260,285,386,428,432`) and **no `commit()` anywhere**. `KillSwitchEngaged` is a `RuntimeError` (`killswitch.py:148`), not an `AdapterError`, so it is **not** caught by the `except AdapterError` handlers at `:257` and `:332` and propagates through `session_scope`, which rolls back (`db/session.py:110-112`) | grep; `killswitch.py:148-152` |
| **F45** | The equities adapter's pacing wait chunks at **0.1 s** (`massive.py:160-166`) and its backoff `_sleep` chunks at **0.2 s** (`massive.py:144-149`) — neither is at `:52-56` or `:118-124`. `MassiveOptionsAdapter` sets `_TIMEOUT = 20.0` and calls `ensure_not_engaged()` once per `_get` (`massive_options.py:34,117`) | `massive.py:144-149,160-166`; `massive_options.py:34,117` |
| **F46** | `data_snapshot` is the parent of three foreign keys — `research.py:84` (SET NULL), `research.py:269` (**ON DELETE CASCADE**, `strategy_sealed_test`, **22 live rows**), `research.py:297` (SET NULL). Migrations run with `render_as_batch=_is_sqlite()` and `PRAGMA foreign_keys=ON` (`db/migrations/env.py:50,67,71`), so altering a UNIQUE constraint on that table forces a batch copy-and-swap rebuild of the parent of the sealed-look ledger | `research.py:84,269,297`; `migrations/env.py:50,67,71`; query (22 rows) |
| **F47** | `entitlement_check` holds **21** distinct endpoints, not 25. `/v3/reference/dividends` and `/v3/reference/splits` are absent from all of them | query, 2026-09-11 |
| **F48** | The `$1.00` SPY ladder of F37 is FACT only over **709.0–831.0**, i.e. roughly **±8%** of a ~770 reference. Because the band filter is server-side (F38), nothing in the DB establishes any increment outside ±8% for SPY or at any distance for the other 23 | query; F38 |

### 1.1 The universe is 24 symbols, not 27

The brief names "the 24-symbol approved universe + SPY/QQQ/IWM". **FACT (F35):**
`universe_24_ex_meta` already contains SPY, QQQ and IWM:

```
AAPL AMZN DIA GOOGL HD IWM JPM MSFT NVDA QQQ SPY UNH
XLB XLC XLE XLF XLI XLK XLP XLRE XLU XLV XLY XOM
```

The union is therefore **24 underlyings**, of which 15 are ETFs. Every arithmetic figure in
§7 uses 24. Tier A (SPY, QQQ, IWM) is a *staging* label inside that 24, not an addition to it.

---

## 2. Point-in-time reference price

### 2.1 The defect being fixed

**FACT (F12):** `_reference_price(session, underlying)` (`options_backfill.py:77-89`) returns
the most recent stored close for the underlying, with **no date argument, no source filter,
and no staleness bound**. One value is computed per underlying per run (`:253`) and used to
centre the strike band for **every** expiration in the run (`:113-115`). Over a 3-year window
this centres 2023 chains on a 2026 price.

### 2.2 The algorithm (HYPOTHESIS)

```
reference_price(session, underlying, as_of_date) -> ReferencePrice | None

  ReferencePrice = (price: float,
                    priced_on: date,          # the session the close came from
                    staleness_sessions: int,  # XNYS sessions between priced_on and as_of_date
                    source: str)              # always 'massive'

  1. inst = Instrument where symbol == underlying.upper()
     if inst is None -> None, reason='no_instrument'
  2. row = the single OHLCVDaily row with
         instrument_id == inst.id
         AND source == 'massive'                      # NOT 'massive_grouped', NOT 'continuity_bridge'
         AND is_simulated IS FALSE
         AND session_date <= as_of_date                # strict: never a future bar
     ordered by session_date DESC, limit 1
     if none -> None, reason='no_bar_on_or_before'
  3. staleness = calendar.session_count(row.session_date, as_of_date) - 1
     if staleness > REFERENCE_MAX_STALENESS_SESSIONS (=3) -> None, reason='reference_stale'
  4. return ReferencePrice(row.close, row.session_date, staleness, 'massive')
```

Properties and why each clause is there:

- **`session_date <= as_of_date`** is the whole point-in-time guarantee. `as_of_date` is the
  cycle's **entry date** (§4.2), never `date.today()`.
- **`source == 'massive'`** — **FACT (F36):** all 24 underlyings have a complete `massive`
  series; **FACT (query):** they also carry a 420-session `massive_grouped` overlay from
  2025-01-03. Mixing the two inside one window would make the reference price depend on which
  bulk sessions happen to be archived, and map §1.5 gate 0.b already requires source `massive`
  (R6: a blended/bulk source fails gate 8). Pinning the source here makes the band and the
  gate agree by construction.
- **Staleness bound** — a cycle whose reference is more than 3 sessions stale is
  **excluded and counted**, never silently centred on an old price.
- **Close, not open, not intraday** — **FACT:** no intraday bar history is ingested
  (`promotion.py:926-940` fails `Horizon.INTRADAY` outright for exactly this reason). The
  entry convention is therefore "decide on session E's close" and the reference is session
  E's close. If D5 later chooses an open-based entry it must use `as_of_date = E - 1 session`
  and say so; the function takes the date, so the convention lives in D5, not here.
- **Returns `None` with a reason, never a fallback value.** Every `None` is a counted
  exclusion in the coverage summary (§9).

### 2.3 The split-adjustment hazard — a blocker the map does not list

This is the most consequential finding in D1 and it is **new**.

**FACT (F24, F25):** stored `ohlcv_daily` bars are back-adjusted — NVDA's 10:1 split of
2024-06-10 leaves no discontinuity ($121.79 on 06-10, $120.91 on 06-11), `split_factor` is
1.0 on every one of 1,460,392 rows, `adj_close == close` everywhere, and `div_cash` is 0
everywhere. **FACT (F23):** `corporate_action` has 0 rows and
`MassiveAdapter.fetch_corporate_actions` returns `()` — so the table will *stay* empty on the
current adapter. **FACT:** the `data_snapshot` descriptions for ids 5/7/9/11 state the bars
are "split-adjusted AS OF the fetch date (NOT point-in-time)".

Option **strikes are not back-adjusted**. A contract listed in May 2024 on pre-split NVDA
carries a strike near $1,000. A point-in-time reference price taken from the stored
(adjusted) series for that date is ~$95. Centring a ±15% band on $95 asks the vendor for
strikes $80.75–$109.25 and the correct chain returns **zero rows** — or, worse, returns the
handful of deep-ITM leaps that happen to sit there. **FACT (F38):** the band filter is applied
server-side, so this failure is invisible: it looks like "that cycle had no contracts".

That is precisely the silent-under-coverage failure mode map §1.3 D3 names as "the worst
failure mode for an evidence pipeline", and it cannot be detected from any table in the DB
today.

**Mitigations (HYPOTHESIS), all three required:**

1. **Ladder-bracket sanity check (free, mechanical).** §3's selection makes an *unfiltered*
   single-expiry reference call. If the returned ladder's `[min(strike), max(strike)]` does
   not bracket the reference price with at least `LADDER_BRACKET_MIN_RUNGS = 3` vendor
   strikes on each side, the cycle is **excluded** with reason
   `reference_price_outside_ladder` and counted. A split offset of 4x, 10x or 20x fails this
   test by orders of magnitude; so does a stale or wrong-symbol reference. This is the
   mechanical enforcement map §1.3 D7 asks for, and it needs no new feed.
   **Caveat added in rev 2, and it is load-bearing:** this check is only as good as the
   ladder it reads, and **FACT (F43)** the paginator stops silently at `_MAX_PAGES = 20` and
   `fetch_contracts` silently drops any row that fails parsing. A truncated or row-dropped
   ladder is indistinguishable from a complete one, so it could pass the bracket test while
   being wrong. §3.4 therefore requires the ladder call to record pages walked, whether
   `next_url` was exhausted or the cap was hit, and the parse-failure count, and adds the
   exclusion reason `ladder_incomplete` — a truncated ladder **excludes the cycle**, it never
   silently shortens it.
2. **Deliverable check.** Every selected contract must have `shares_per_contract == 100` at
   selection *and* at entry. **FACT:** the vendor field is already parsed
   (`massive_options.py:183`) and carried onto `OptionContract`
   (`options_backfill.py:151`; `market.py:255`). Refusals are counted — this is gate 0.h.
3. **Named exclusion of adjusted cycles.** A cycle whose `[entry, expiry]` interval contains a
   known adjustment event for that underlying is excluded and counted. **Today there is no
   source for that list (F23).** Until one exists, mitigation 1 is the only enforcement, and
   the coverage summary must report `cycles_excluded_reference_outside_ladder` prominently —
   a nonzero count on a specific underlying is the signature of an unrecorded adjustment.
   This is **open question OQ-3**.

---

## 3. Per-cycle caps and the selection ladder

### 3.1 The defect being fixed

**FACT (F15, F16):** the two selection caps are per-underlying across all kept expirations,
and the expiration cap keeps only the **nearest** N expiries of whatever the reference call
returned. Over a 3-year, 34-cycle window with `expirations_per_underlying=4` the run would
cover the four nearest expiries and silently drop 30 cycles; with
`contracts_per_underlying=40` an ATM-ranked 40-contract slice would be shared across all of
them. **FACT (F39):** at ±2% over 6 expirations SPY already produced a 972-contract candidate
pool — the caps, not the band or the expiry count, decide coverage today.

### 3.2 Cap redesign (HYPOTHESIS)

Replace the two global caps with **per-(underlying, cycle)** caps, and make the selection a
**deterministic moneyness ladder** rather than an ATM-ranked truncation:

```
BackfillCaps (revised)
  window_start: date                      # explicit; no today()-relative clamp  (fixes D1)
  window_end:   date
  cycle_rule:              'monthly_third_friday'
  dte_entry_min / max:     21 / 60        # map §1.1 verbatim (rev 2: rev 1's 20 is withdrawn, §4.1)
  strike_band_pct:         0.15
  moneyness_ladder:        LADDER_17 (below)
  min_rungs_per_side:      7              # map §1.1 "absolute floor of >=7 strikes either side"
  rights:                  ('call','put')
  max_contracts_per_cycle: 40             # a ceiling on the ladder, never the selector
  max_total_bars:          2_000_000      # decision 6
```

`max_contracts_per_cycle` exists only as a runaway guard. **The ladder, not the cap, decides
what is fetched** — that is the whole point of D3's fix. If the ladder ever wants more than
the cap, the run **fails loudly** for that cycle rather than truncating.

### 3.3 `LADDER_17` — the pre-registered moneyness ladder

Defined in **moneyness**, `m = K/S − 1`, relative to the cycle's point-in-time reference `S`:

```
m ∈ { 0.000,
     ±0.015, ±0.030, ±0.045, ±0.060,
     ±0.080, ±0.100, ±0.125, ±0.150 }      → 17 rungs
```

Selection, per (underlying, cycle, right):

1. Fetch the **unfiltered, point-in-time** ladder for that single expiry (§3.4) → the vendor
   strike set **as it stood on the cycle's entry date**. Point-in-time is not a nicety here;
   see the lookahead blocker immediately below.
2. For each rung `m`, take the single vendor strike nearest `S·(1+m)` **among strikes whose
   existence on the entry date is established** (§3.4). A strike whose point-in-time existence
   cannot be established is **ineligible**; the rung falls to the next-nearest eligible strike,
   and if none exists within the band the cycle is excluded with reason
   `strike_not_listed_as_of_entry` and counted.
3. De-duplicate (on a coarse ladder two adjacent rungs can resolve to the same strike).
4. Require ≥ `min_rungs_per_side` (7) distinct strikes on each side after de-duplication,
   else exclude the cycle with reason `ladder_too_coarse` and count it.
5. Repeat for both rights. Upper bound **34 contracts per (underlying, cycle)**.

#### 3.3a The lookahead in the strike ladder (BLOCKER D14, new in rev 2)

**This is a severe defect in the rev-1 design and it would have invalidated the dataset.**

**FACT (F40):** `fetch_contracts` sends no `as_of` parameter. **FACT (F41):** `OptionContract`
carries no listing or first-traded date. So a single-expiry reference call issued in 2026 for
an expiry in 2023 returns — at best — **the ladder as it stood at the END of that series'
life**, including every strike the exchange listed *after* the cycle's entry date.

Exchanges list new strikes **in the direction the underlying has already moved**. Choosing the
8 OTM rungs from an end-of-life ladder therefore preferentially finds well-placed short strikes
in the direction the market actually went. That is **favourable selection on realised outcomes**
— a lookahead in the selection rule itself, not a coverage question, and rev 1 did not mention
it anywhere.

**Requirements (HYPOTHESIS, all three, pre-registered in §12):**

- **(a) Point-in-time reference call.** The single-expiry `fetch_contracts` call MUST carry the
  vendor's point-in-time parameter set to the cycle's entry date. The parameter is added to
  `fetch_contracts` in the §14 touchpoint list (`massive_options.py:152-180`).
- **(b) Fallback, if and only if the vendor exposes no such parameter — a first-bar proxy.**
  A strike is treated as existing on the entry date only if its contract's **earliest
  `OptionAggregateDaily` session** is on or before that date. This is strictly conservative
  (a listed-but-never-traded strike is excluded, which is the safe direction) and uses only
  bar *presence*, which §10 permits before D5. It establishes a **sufficient** condition for
  existence, never a necessary one, so it is a weaker instrument than (a) and must be labelled
  as such wherever it is used.
- **(c) If neither (a) nor (b) can be applied, the ladder may not be used for selection at
  all.** In that case the contamination is recorded as a **named falsification risk carried
  into D5** — not absorbed into a coverage fraction. Whichever of (a)/(b)/(c) applied is
  recorded per cycle in `options_scope_json` as `strike_listing_basis`, so two datasets built
  on different bases can never share a snapshot identity (§9.2).

Whether (a) is available is **OQ-10**, and it ranks ahead of OQ-1 and OQ-2.

Why this shape:

- **Dense where the strategy lives, sparse where it does not.** Decision 12 makes O3 (short
  vertical credit spread) first. Its short leg sits at a target delta in the 0.15-0.30 band —
  roughly 3-8% OTM on an index ETF at 30-45 DTE, further on a single name. The 1.5% spacing
  from ATM out to ±6% gives D5 several candidate short strikes *and* the adjacent strikes a
  1-3 rung spread width needs, without paying for tails nobody trades.
- **It satisfies gate 0.c bracketing by construction** — 8 rungs each side always straddle
  any target inside ±15%.
- **It feeds the §2.4b surface.** 17 strikes per right per expiry is the pool the same-session
  IV fit draws from; the N≥5 floor (§5.3) is a *realised-prints* floor on top of it.
- **It is NOT spot-invariant, and rev 1's claim that it was is withdrawn.** The *rung set* is
  defined in moneyness, but the *delivered* rung count is the de-duplicated count against the
  underlying's **absolute** strike increment, which falls as the price level falls. Recomputed
  over all 34 cycles at each underlying's point-in-time entry-date close (equity closes only —
  §0.1), at the uniform **$1.00** increment that exactly reproduces rev 1's own §7.2 figures:

  | Increment (HYPOTHESIS, OQ-5) | Contracts/cycle, all 24 | (underlying, cycle) pairs below the 7-rung floor | Underlyings whose bracket fraction is **below** `GATE_0C_CYCLES_BRACKET = 0.90` |
  |---|---|---|---|
  | $0.50 | 27,738 total | 0 of 816 | none |
  | **$1.00** | **26,560 total**, per cycle **762–794** (mean 781.2) | **73 of 816** (overall bracket fraction **0.911**) | **XLRE 0.26, XLU 0.29, XLF 0.65, XLE 0.82, XLB 0.85** |
  | $2.50 | 22,296 total | 216 of 816 | XLB, XLE, XLF, XLRE, XLU (0.00), XLC 0.32, XLY 0.47, XLK 0.65, NVDA 0.71, XOM 0.79, XLP 0.00 |

  Two consequences, both pre-registered here **before any options data exists**:

  1. **§7.2's rev-1 figure of 798 contracts/cycle was computed at the window's HIGHEST prices**
     (2026-09-11 closes) and is an upper bound, not a constant. Delivered coverage is worse than
     tabulated, and worst in the earliest cycles.
  2. **At the $1.00 assumption the overall bracket fraction is 0.911 — 1.1 points of margin
     against a pre-registered constant**, and five underlyings are individually far below it.
     This is exactly the situation that creates an incentive to loosen a constant after a
     coverage summary is read. It is therefore pre-registered now: **the ONLY permitted
     responses to a rung shortfall are (i) dropping the affected underlying from the snapshot,
     or (ii) adding a finer rung set, pre-registered and committed before Stage A begins.
     Lowering `MIN_RUNGS_PER_SIDE`, `LADDER_BRACKET_MIN_RUNGS`, or `GATE_0C_CYCLES_BRACKET` is
     forbidden, now and after.** Either response changes `options_scope_json` and therefore
     mints a new snapshot and a new sealed look (§9.2).

  The arithmetic above rests entirely on the increment assumption, which is **OQ-5** and is FACT
  only for SPY and only within ±8% (F48).
- **It is the cap that decision 6's ceiling implies.** §7.4 shows the "every vendor strike in
  ±15%" alternative needs ~4.14M bars — more than twice `backfill_max_total_bars = 2,000,000`.
  The ladder is not a convenience; it is the selection the operator's own ceiling forces.

### 3.4 Two reference calls per cycle, not one

**FACT (F38):** today's single `fetch_contracts` call is band-filtered server-side, so the
code never sees the true strike ladder — which is exactly what §2.3 mitigation 1 needs and
what step 2 above needs to pick rungs. **HYPOTHESIS:** issue **one unfiltered
single-expiry** `fetch_contracts(underlying, expiration_gte=E, expiration_lte=E, as_of=entry)`
per (underlying, cycle), apply the band and the ladder client-side, and record the full
ladder's `[min, max]` and rung count in the coverage summary.

**Four requirements on that call, all new in rev 2, all FACT-driven:**

1. **`as_of` = the cycle's entry date** (§3.3a (a)). **FACT (F40):** the parameter is not sent
   today and is not in `fetch_contracts`' signature. Without it the ladder is an end-of-life
   ladder and the selection has a lookahead. If the vendor exposes no such parameter, §3.3a (b)
   or (c) applies — **never** the raw end-of-life ladder.
2. **The expired-contracts flag** (§7.0 / blocker D13). **FACT (F40, F42):** no such flag is
   sent, and no expired contract has ever been returned to this repo. Without it a call for a
   2023 expiry may legitimately return **zero rows**.
3. **`limit=1000` passed explicitly.** **FACT (F43):** the parameter defaults to **250**, not
   1000; rev 1 asserted 1000 and it was wrong. At 250 a deep chain needs four times the pages.
4. **Pagination and parse accounting.** **FACT (F43):** `_paginate` stops silently at
   `_MAX_PAGES = 20` and `fetch_contracts` silently skips unparseable rows. The call must record
   `pages_walked`, `next_url_exhausted` (true) vs `page_cap_hit` (false), and
   `rows_unparseable`. A cycle whose ladder call hit the page cap or dropped any row is
   **excluded** with reason `ladder_incomplete` and counted — a truncated ladder must never
   silently shorten a cycle, because §2.3 mitigation 1 is computed from exactly that set.

**The "2 pages per cycle" figure is HYPOTHESIS, not FACT** — rev 1 labelled it FACT and cited
`_paginate`, which establishes only the mechanism. F37's 123 strikes is the **band-filtered,
stored** set, not a full vendor ladder. §7 budgets 2 pages per cycle as a planning assumption;
Stage A measures it, and §7.2's request total is a **no-retry lower bound** in any case (the
§7.6 retry loop allows up to 5 attempts per request).

### 3.5 Narrow the per-contract fetch range

**FACT (F17):** `fetch_from = max(win_start, last_covered + 1)` and
`hard_end = min(win_end, expiration)` — so a contract expiring two years into a three-year
window is fetched from the window start, pulling ~500 bars where ~43 are needed.

**HYPOTHESIS:** the fetch range becomes the **cycle's own trade window**:

```
fetch_start = max(window_start, first XNYS session with (expiry - session) <= dte_entry_max,
                  minus PRE_ENTRY_BUFFER_SESSIONS)
fetch_end   = min(window_end, expiry)
```

with `PRE_ENTRY_BUFFER_SESSIONS = 5` (so the entry session's IV inversion and surface fit have
context, and so a 1-2 session entry slip does not fall off the edge).

**FACT (computed, XNYS via `pandas_market_calendars`, the same calendar
`data/calendar.py:39` uses):** across the 34 cycles of §4.1 —

| Span | Sessions | Mean |
|---|---|---|
| DTE-60 → expiry (**no** buffer) | 40–45 | **43.09** |
| DTE-60 **− 5 sessions** → expiry (the span this section actually specifies) | **45–50** | **48.09** |
| DTE-45 → expiry | 31–34 | 32.79 |

**Correction (rev 2):** rev 1 defined the fetch span *with* `PRE_ENTRY_BUFFER_SESSIONS = 5` and
then costed it *without* — it reported 43.1, which is the unbuffered span. Every bar figure in
§7 was therefore **~11.6% low**. §7 now uses **48.1** throughout. The buffer is kept (the entry
session's IV inversion and surface fit need context, and a 1-2 session entry slip must not fall
off the edge); the alternative — dropping the buffer and using 43.1 — is rejected because the
buffer is what makes rank-1 inversion available on the entry session itself.

Narrowing the fetch range is still what brings the run under the 2,000,000-bar ceiling, but the
margin is **~34%, not ~41%**, and a pre-registered constant's binding constraint must not be
understated.

---

## 4. Expiries, window, and history depth

### 4.1 The cycle set

**Rule:** every **monthly** expiry = the **third Friday** of each calendar month in the
window. No weeklies. Map §1.1's rationale: monthlies are the liquid series and give one
clean, non-overlapping cycle per month, which is what makes §5.3's trade-count arithmetic
work.

**Window (HYPOTHESIS):**

```
window_end   = 2026-09-04      # the last settled session already present in option_aggregate_daily
window_start = 2023-09-04      # window_end - 1096 days (3 calendar years)
```

**FACT (F30, arithmetic):** gate 0 fails unless `sealed_start > start` **and**
`(pre_sealed_end - start).days >= 350`, where `sealed_start = end - 365` and
`pre_sealed_end = sealed_start - 1`. Solving: `start <= end - 716`. **The true floor is 716
days, not 715** — map §0.3 and §1.5 round to "≈715"; the strict inequality at
`promotion.py:940` makes 716 the first passing span. 1,096 days clears it by 380 days, i.e.
one full extra year of pre-sealed regime variety, exactly as map §1.1 recommends.

**Cycles (computed):** third Fridays E with `window_start + 60d <= E <= window_end` →
**34 cycles**, 2023-11-17 → 2026-08-21. The 60-day offset drops the two cycles whose DTE-60
entry would precede the window start.

Per cycle the entry search window is **DTE 21-60**, adopted **verbatim** from map §1.1.

**Correction (rev 2), and it matters more than the one day.** Rev 1 set the floor at 20 and
justified it on the ground that "a wider entry window can only make gate 6's regime buckets
easier to populate". That justification is **gate weakening in disguise** and is withdrawn.
20-60 is not "inside" 21-60, it is wider than it (map line 218: "DTE window at entry | 21-60
DTE"); and widening the candidate pool *because it eases* `min_trades_per_regime = 10`
(`config/research.py:113`) is the same act R4 forbids, by another name. Rev 1 also called 20
"the wider, safer floor" with no argument — a 20-DTE short vertical is **higher**-gamma than a
21-DTE one, not safer. The map's value stands; no rationale of D1's own is needed for it.

**Deviation from map §1.1, disclosed (new in rev 2).** Map §1.1 specifies "Every monthly
(3rd-Friday) expiry cycle over the history window, **plus the weekly nearest the 30-DTE target
within each cycle**". This document ingests **monthlies only** and rev 1 stated that as "No
weeklies" without acknowledging it as a deviation. It is one, and it is the map's own slack for
the trade-count problem:

- **Cost to gate 2** (`min_oos_trades = 30`, `config/research.py:99`): the candidate ceiling
  falls from ~2 × 24 × 34 ≈ 1,632 to 24 × 34 = **816** entries before any regime, liquidity or
  event filter removes one.
- **Cost to gate 6** (`min_trades_per_regime = 10` in **each** of bull/bear/range,
  `config/research.py:113`): the bear bucket is the binding one over 2023-09..2026-09, and
  halving the candidate pool halves it.
- **Why the deviation is taken anyway:** a weekly per cycle roughly doubles §7's request count
  and bar count — from ~29,400 requests / ~1.33M bars to ~58,800 / ~2.67M, i.e. **above**
  `BACKFILL_MAX_TOTAL_BARS = 2,000,000`. Monthlies-only is the choice decision 6's ceiling
  forces, exactly as the ladder is (§7.4).
- **Consequence, recorded not buried:** this is the first place to widen if D4's re-run of the
  §5.3 arithmetic on the real coverage summary shows gate 2 or gate 6 short. That is **OQ-7**,
  and widening to weeklies would be a new `options_scope_json` and a new sealed look (§9.2) —
  never a quiet addition.

### 4.2 `as_of_date` for the reference price

For cycle with expiry `E`, `as_of_date = ` the **first XNYS session S with `(E - S).days <=
dte_entry_max` (60)**. That session's close is the band centre for the entire cycle. The
strike ladder is therefore fixed once per cycle, before any entry decision, and does not
drift as the entry search walks forward through DTE 60→20. D5 may place the actual entry
anywhere in that window; it may not re-centre the ladder.

---

## 5. IV source (decision 7) and the surface floor

**Decision 7 (binding):** local Black-Scholes inversion from daily aggregates + the §2.4b
same-session surface; dated vendor snapshots collected forward as a secondary series.

### 5.1 The four sources, in strict precedence

`iv_source` is recorded **per (contract, session)**, and the per-evaluation fraction from each
is gate 0.e evidence.

| Rank | `iv_source` | Input | May price a **fill**? | May price a **mark**? |
|---|---|---|---|---|
| 1 | `local_bs_inverted` | the contract's **own** `OptionAggregateDaily.close` on that session | **Yes — but only if the inversion is *admissible* per §5.2's re-price and vega guard, and subject to §5.4's fill-timing requirement** | Yes |
| 2 | `same_session_surface` | §2.4b fit over other contracts on the same (underlying, expiry, session) | **No** (map §2.4(3): a missing bar can never produce a fill) | Yes |
| 3 | `vendor` | a genuinely dated `OptionQuoteSnapshot.vendor_iv` | No | Yes |
| 4 | `pct_otm_proxy` | moneyness only | No | Yes, counted and flagged |
| — | `iv_unavailable` | — | No | No — the position is marked unavailable |

An **inadmissible** rank-1 inversion (§5.2) does not stay at rank 1 with a caveat — it falls to
rank 2, **for marking only**, and is counted. Rank 1 is the only row in this table that may price
a fill, so anything doubtful must leave it.

**FACT (F4):** rank 3 is empty as a history: all 878 `option_quote_snapshot` rows share one
`as_of`. **FACT (`market.py:262-264`):** vendor IV/greeks are "usually absent on this
entitlement". Rank 3 therefore contributes 0 to any backfilled evaluation and exists only so
the forward-collected series has somewhere to land.

**Explicitly forbidden (map §2.4b, carried verbatim):** realised volatility as a fallback.
For a premium-selling strategy it values unsold short premium below its true worth and
inflates simulated credit capture on exactly the trades the strategy claims as its edge. A run
that falls back to realised vol is not evidence.

### 5.2 Rank 1 — the inversion, precisely

```
t     = (expiration_date - session_date).days / 365.0        # calendar-day ACT/365
s     = reference_price(underlying, session_date).price      # §2.2, source 'massive'
k     = OptionContract.strike_price
r     = OptionsConfig.risk_free_rate                         # FACT: 0.04 constant (F27)
q     = q_for(underlying, session_date)                      # §6; NEVER 0.0 by default
call  = (contract_type == 'call')
sigma = blackscholes.implied_vol(target_price=close, s, k, t, r, call=call, q=q)
```

**FACT (F26), and rev 1 described this function incorrectly.** `implied_vol` returns `None` in
exactly three cases — `t <= 0`, `target_price <= 0`, or `target_price` outside
`[lo_bound - tol, hi_bound + tol]` (`blackscholes.py:106-111`). It **does not** return `None` on
non-convergence: after `max_iter = 100` bisection steps it returns `0.5*(lo+hi)`
(`blackscholes.py:123`), a float indistinguishable from a converged solve.

Two consequences, both severe, both fixed here:

**(i) `non_convergent` was unreachable at the call site.** Rev 1 listed three recorded reasons;
only a `None` was observable, and the band check collapses `below_intrinsic` and
`above_upper_bound` into a single bare `None`. Corrected taxonomy, defined against the function's
own variables rather than against a returned status it does not produce:

| Recorded reason | Test at the call site |
|---|---|
| `expired_or_nonpositive` | `t <= 0` or `close <= 0` |
| `below_intrinsic` | `close < price(s,k,t,r,1e-6,…) - tol` — i.e. below `lo_bound` (`blackscholes.py:109`) |
| `above_upper_bound` | `close > price(s,k,t,r,5.0,…) + tol` — i.e. above `hi_bound` (`blackscholes.py:110`) |
| `non_convergent` | a sigma **was** returned, but re-pricing at it gives `abs(price(σ) - close) > IV_MAX_PRICE_RESIDUAL` |
| `vega_too_low` | a sigma was returned and re-prices, but `vega(σ) < IV_MIN_VEGA` |

The `non_convergent` and `vega_too_low` rows are only obtainable because the caller **re-prices
at the returned sigma**. That re-price is therefore mandatory, not optional. (The alternative —
changing `implied_vol` to return a status alongside sigma — is cleaner and is listed as an
option in §14; the caller-side re-price is specified here because it needs no change to a
function four payoff simulators already depend on.)

**(ii) A non-converged or near-zero-vega sigma would otherwise reach the ONE rank allowed to
price a fill.** For a deep-OTM contract whose vega is near zero the Black-Scholes price is flat
in sigma: `abs(diff) < tol` (with `tol = 1e-6` in **price** units) may never trigger, and the
returned sigma is essentially arbitrary within the flat region. Rank 1 is the only row in §5.1's
table marked "May price a fill: **Yes**", and it is the number that will set every delta D5 uses
to pick a short strike. An arbitrary sigma there is an arbitrary delta, and an arbitrary delta
is an arbitrary strike-selection rule.

**Rank-1 admissibility guard — PRE-REGISTERED NOW, before any IV has been computed (§12):**

```
IV_MAX_PRICE_RESIDUAL = 1e-4        # absolute, in option price units (dollars per share)
IV_MIN_VEGA           = 1e-3        # absolute vega at the solved sigma, per 1.00 of vol
```

A rank-1 inversion is **admissible** only if `implied_vol` returned a float **and**
`abs(price(σ) - close) <= IV_MAX_PRICE_RESIDUAL` **and** `vega(σ) >= IV_MIN_VEGA`
(`blackscholes.greeks`, `:63`). An inadmissible inversion is recorded with its reason and the
contract-session falls to **rank 2, for marking only** — it may never price a fill. The counts
per reason are coverage evidence (permitted before D5: they are counts) and a gate-8 input.
`IV_MAX_PRICE_RESIDUAL` is deliberately two orders of magnitude looser than the solver's own
`tol = 1e-6` so the guard rejects genuine non-convergence rather than float noise, and
`IV_MIN_VEGA` is an absolute floor rather than a relative one so it does not itself depend on
the sigma being tested.

A close below intrinsic remains a data-quality signal (a stale or crossed print) and its count
is a gate-8 input.

`t == 0` on the expiry session: **FACT (`blackscholes.py:52-55,92-94`)** `price` returns
intrinsic and `implied_vol` returns `None`. Expiry-session pricing is intrinsic by
construction; that is D2's force-close problem, not D1's, and D1 records only the count.

### 5.3 Rank 2 — the same-session surface and its N floor (PRE-REGISTERED)

Per map §2.4b, for underlying U, session S, expiry E:

1. Collect every contract on (U, E) that **printed** on S (a row in `OptionAggregateDaily`).
2. Invert IV from each print via rank 1.
3. Fit IV as a function of log-moneyness `ln(K/S)`: a **quadratic least-squares fit in
   log-moneyness, per expiry**, weighted equally. No spline, no free knots, no per-run tuning
   — the functional form is pre-registered here so it cannot be chosen after a result is seen.
4. Interpolate **linearly in total variance** `σ²·t` across expiries for the term structure;
   never extrapolate beyond the nearest and farthest fitted expiries.
5. Mark the non-printing contract from the fit. Record `iv_source = same_session_surface`,
   `surface_n` (contracts used), and `surface_rmse`.

**The N floor, pre-registered (map §2.4b HYPOTHESIS, adopted here and proposed to D5 — see the
standing note at the head of §12):**

```
SURFACE_MIN_PRINTS_PER_EXPIRY   = 5      # printing contracts on (U, E, S)
SURFACE_MIN_DISTINCT_STRIKES    = 3      # distinct strikes on the side being marked
SURFACE_MAX_LOG_MONEYNESS_EXTRAP = 0.0   # no extrapolation beyond the fitted strike range
```

If any of the three is violated there is **no surface**. The contract is marked
`iv_unavailable`; per map §2.4(3) no fill may occur from it; if it is the force-close session,
the structure was ineligible for entry (map §2.7). The counts of each violation are coverage
evidence.

A quadratic needs 3 points to be determined; requiring 5 prints and 3 distinct strikes means
the fit is over-determined in strikes on the relevant side, not interpolating between two
points and a repeat.

### 5.4 The fill price and the entry decision are not time-aligned (new in rev 2)

**Stated as a named, unquantified bias, because that is what it is.**

**FACT (§2.2):** the entry convention is "decide on session E's **close**", using the
underlying's 16:00 equity close. **FACT (§5.1/§5.2):** the option's `OptionAggregateDaily.close`
is then used as both the IV input **and** the fill-authorised price. **FACT (map §2.4,
`market.py:290-318`):** that close is a **last-trade print** whose intraday time is unknown and
is not recorded anywhere in the schema — on a thin series a strike may print once a day.

So a 10:00 print can be used as the fill for a decision taken at 16:00 — a fill that **precedes
the information the decision is based on**. And because the print's position within the
unobserved spread is unknown (F6: NBBO is 403 on both asset classes), the inverted IV, and
hence the selected strike's delta, carries bid/ask sign noise. D1 defers the *spread model* to
D2, but the **inversion** is D1's and inherits the same defect.

**Nothing in D1 establishes that the net effect is conservative** in the direction map §2.4a
warns about for a short-premium strategy. Rev 1 made no such argument and implied none is
needed; that was wrong.

**Requirements (HYPOTHESIS), exactly one of which D2 must adopt, and D1 records which:**

- **(a) Next-session fill.** The fill is taken from session **E+1**'s print, matching the equity
  engine's own convention — **FACT:** `raw_entry = series.open[entry_idx]` where `entry_idx` is
  the bar after the signal (`backtest/engine.py:109`). This makes the options path consistent
  with the asset class that already has a gate ladder behind it, at the cost of one session of
  slippage that is borne rather than assumed away.
- **(b) Same-session fill plus an explicit timing penalty.** D2 carries a stated, pessimistic
  penalty for the unknown print time, folded into `options_config_hash` like any other cost
  constant.

**Recorded either way, per contract-session, as a gate-0.f disclosure field:**
`print_time_known = false`. The coverage summary reports the count (a count, so §10 permits it).
This is a falsification risk D5 must carry by name; it is not closed by this document.

### 5.5 The rate `r` — a hole that must be closed with the IV decision

**FACT (F27):** `risk_free_rate = 0.04` is a single constant with no term structure and no
point-in-time series. Over 2023-09 → 2026-09 the actual short rate did not sit at 4%.
**FACT (F28):** `options` is **not** in `SCOPE_HASH_FIELDS`, so changing `risk_free_rate`
changes every options IV, delta and mark **without changing `config_hash`** — the exact class
of failure as the 2026-09-11 agents-section incident (commit `0cc4cf4`).

**HYPOTHESIS (required, and it is a D1 deliverable not a D5 one):**

- Record `r_source = 'config_constant'` and the value on every evaluation (gate 0.e extension).
- Do **not** add `options` to `SCOPE_HASH_FIELDS` — that would change `config_hash` for the two
  live PAPER_APPROVED equity strategies and un-scope them, repeating the incident.
- Instead introduce a **separate** `options_config_hash` over a new frozen
  `OptionsEvaluationConfig` (§8.2), recorded on the options evaluation and folded into
  `options_scope_json`. The equity scope hash is untouched.
- D5's sensitivity grid must include `r`, because a constant rate is an assumption, not data.

---

## 6. Dividend yield `q` (decision 11)

**Decision 11 (binding):** source and record `q` per underlying — no allowlist — so SPY and
IWM stay in scope. **Map §1.5 gate 0.g:** a run that used `q = 0.0` by default fails gate 0
outright.

### 6.1 There is no dividend data in this repo — at all

**FACT (F23):** `corporate_action` = 0 rows, and `MassiveAdapter.fetch_corporate_actions`
returns `()` ("not offered by this feed", `massive.py:225-228`).
**FACT (F24):** `ohlcv_daily.div_cash` is 0 in all 1,457,903 rows.
**FACT (F6/F7, `entitlement_check`):** `/v3/reference/dividends` and `/v3/reference/splits`
were **never probed** — they are absent from all **21** distinct probed endpoints (**F47**;
rev 1 said 25, which was wrong; the conclusion is unchanged). Their entitlement is **unknown**.

So decision 11 is not a configuration choice; it requires a **new data path**. That is a
blocker the map's D1-D8 list does not carry.

### 6.2 The `q` precedence (HYPOTHESIS)

`q_source` is recorded per (underlying, session); the per-trade fraction from each is gate 0.g
evidence.

| Rank | `q_source` | Method | Prerequisite |
|---|---|---|---|
| 1 | `vendor_dividends` | trailing-12-month declared cash dividends ÷ point-in-time close, recomputed on each ex-date | `/v3/reference/dividends` proves entitled — **must be probed before I-O2**, OQ-1 |
| 2 | `parity_implied` | put-call parity on the same-session surface | needs a call/put pair at a common strike that both printed |
| — | *(none)* | **gate 0.g fails** | — |

There is deliberately no rank 3. `q = 0.0` is never reached.

**Rank 2, precisely.** For (U, E, S) with a call and a put that both printed at the same
strike K, European parity gives `C − P = S·e^(−qT) − K·e^(−rT)`, hence

```
q = −(1/T) · ln( (C − P + K·e^(−rT)) / S )
```

Take the **median** over all qualifying strikes on (U, E, S) — pre-registered as the median,
not the mean, so a single crossed print cannot move it — and require
`PARITY_MIN_PAIRS = 3` qualifying strike pairs, else the session falls to *no source* and the
cycle is excluded and counted.

**Why this is attractive and where it is wrong.** It uses only data the backfill already
collects, needs no new entitlement, and is point-in-time correct by construction — it cannot
leak a future dividend. But: (a) US equity options are **American** (`exercise_style`,
`market.py:254`), and early-exercise premium breaks the parity identity, biasing `q` on
deep-ITM pairs; (b) it conflates dividend yield with borrow/financing spread; (c) it inherits
whatever error `r = 0.04` carries. Mitigations: restrict parity strikes to
`|ln(K/S)| <= 0.05` (near-ATM, where early exercise is least valuable), record
`q_parity_pairs` and the interquartile range per session, and make `q` a D5 sensitivity axis.

**This is why rank 1 must be probed first.** A one-call entitlement probe of
`/v3/reference/dividends` — the same probe shape already used to build `entitlement_check` —
decides whether `q` rests on declared dividends or on an American-parity approximation. That
probe is a prerequisite to I-O2 and costs one request.

### 6.3 Coverage-summary compliance

`q` is derived from option **prices**. Computing it before D5 is committed would be looking at
a price series. **Rule:** `q` is computed **inside the evaluation, at run time** — never as a
pre-D5 series. The coverage summary may report only the **count** of (underlying, cycle,
session) triples that have ≥ `PARITY_MIN_PAIRS` parity-eligible pairs. A count is exactly
what §7's "counts and completeness, nothing else" permits, and it is what D5 needs to know
whether rank 2 is viable at all.

---

## 7. The backfill plan

### 7.0 BLOCKER D13 — every figure below is VOID until one probe returns rows

**This ranks above everything else in §7 and was absent from rev 1.**

§3.4 specifies `fetch_contracts(underlying, expiration_gte=E, expiration_lte=E)` per
(underlying, cycle), and §7.2 costs 1,632 such calls over cycles reaching back to 2023-11-17.

- **FACT (F40):** `massive_options.py:162-171` builds the query from `underlying_ticker`,
  `expiration_date.gte/lte`, `limit` and `sort` only. **It never sends an expired-contracts
  flag.** Reference-contract endpoints commonly default to **live contracts only**.
- **FACT (F42):** all 888 rows in `option_contract` carry expirations 2026-09-08 → 2026-10-16
  and were created 2026-09-07/08 — i.e. **every contract ever returned to this repo was
  unexpired at fetch time**. No expired contract has ever come back through this code path, so
  the repo contains no evidence either way.

If the endpoint defaults to live contracts only, **every cycle except the last returns zero
rows**, and the entire §7 arithmetic — 34 cycles, ~29,400 requests, ~99 hours, ~1.33M bars, the
Stage A/B split, and §7.4's counterfactual — is uncosted fiction.

**Requirement, before Stage A and before any other §7 work:**

1. One request to `/v3/reference/options/contracts` for a **single 2023 SPY monthly expiry**
   (e.g. 2023-11-17), with and without the vendor's expired-contracts parameter.
2. The result is recorded in `entitlement_check` in the same shape as the existing 21 endpoint
   rows (F47), so it is auditable rather than remembered.
3. Combine it with the **OQ-10** `as_of` probe (§3.3a) and the **OQ-1** dividends probe (§6.2)
   — three requests total, one sitting.

**Until that probe returns rows, §7.1–§7.4 are planning arithmetic on an unestablished
premise and must not be quoted as a plan cost.** This is **OQ-9**, and with OQ-10 it ranks
ahead of OQ-1 and OQ-2.

### 7.1 Parameters

| Parameter | Value | Source |
|---|---|---|
| Underlyings | the 24 of `universe_24_ex_meta` (SPY/QQQ/IWM included) | FACT F35, §1.1 |
| Window | 2023-09-04 → 2026-09-04 (1,096 days) | §4.1; ≥716-day floor F30 |
| Cycles | monthly third Friday, 34 cycles 2023-11-17 → 2026-08-21 | computed, §4.1 |
| DTE at entry | **21-60** | map §1.1 verbatim (§4.1) |
| Strike band | ±15% of the point-in-time reference | map §1.1; `backfill_strike_pct_band=0.15` (`config/research.py:215`) |
| Strike selection | `LADDER_17` on the true vendor ladder, both rights | §3.3 |
| Per-contract fetch span | DTE-60 − 5 sessions → expiry; **48.1 sessions mean** (45–50) | computed, §3.5 *(rev 2: rev 1's 43.1 omitted the 5-session buffer it had itself specified)* |
| `backfill_max_total_bars` | **2,000,000** | decision 6 |
| Pacing | 12.1 s/request | FACT F8 |

### 7.2 Contract and call counts (computed, rev 2)

**Rev 1 computed this at a single date — the 2026-09-11 closes, the highest price level in the
window — and reported one flat figure of 798 contracts/cycle.** That was an upper bound
presented as a constant. Rev 2 recomputes the de-duplicated ladder at **each of the 34 cycles'
own point-in-time entry-date closes** (equity closes only, §0.1) and reports a range.

Strike increments remain **HYPOTHESIS** (OQ-5): only SPY's $1.00 ladder is FACT, and only
within ±8% (F48). The planning figures below use the **$0.50** column, because that is the
increment at which no underlying falls below `GATE_0C_CYCLES_BRACKET` and it is therefore the
**largest** bar count of the three — the conservative direction for a ceiling constraint.

| Increment (HYPOTHESIS) | Contracts/cycle | Total contracts over 34 cycles | Aggregate calls | Bars @ 48.09 | % of 2,000,000 |
|---|---|---|---|---|---|
| **$0.50 (planning figure)** | 796–816 | **27,738** | 27,738 | **≈1,334,000** | **66.7%** |
| $1.00 (reproduces rev 1's §7.2 exactly at the 2026-09-11 date) | 762–794 (mean 781.2) | 26,560 | 26,560 | ≈1,277,000 | 63.9% |
| $2.50 | — | 22,296 | 22,296 | ≈1,072,000 | 53.6% |

```
aggregate calls   = 27,738 contracts (planning figure, $0.50)  =  27,738
reference calls   = 24 underlyings × 34 cycles × 2 pages       =   1,632   (2 pages = HYPOTHESIS, §3.4)
                                                     TOTAL     =  29,370 requests   (no-retry LOWER bound)
wall clock @ 12.1 s/request                                    =  355,377 s
                                                               =  98.7 hours = 4.11 days (serial)
bars              = 27,738 contracts × 48.09 sessions          ≈ 1,334,000
                    vs backfill_max_total_bars = 2,000,000     =  66.7% of the ceiling
```

**Three things this table is not.** It is not a delivered-coverage figure — §3.3's ladder
exclusions remove (underlying, cycle) pairs before any contract is fetched, and at the $1.00
assumption 73 of 816 pairs go (bracket fraction **0.911**, against a pre-registered 0.90). It is
not a retry-inclusive figure — §7.6 permits up to 5 attempts per request, so 29,370 is a floor.
And it is not valid at all until **D13** (§7.0) is resolved.

### 7.3 Staging

| Stage | Underlyings | Requests | Hours @12.1s | Bars |
|---|---|---|---|---|
| **A** | SPY, QQQ, IWM | 3,672 | **12.3** | **~167,000** |
| **B** | the other 21 | 25,698 | **86.4** | **~1,167,000** |
| Total | 24 | 29,370 | 98.7 | ~1,334,000 |

*(rev 2: all four bar figures rose by ~11.6% with the 48.09-session correction of §3.5; Stage B's
request count rose with the $0.50 planning increment of §7.2.)*

Stage A is a single overnight-plus run that exercises every mechanism (point-in-time
reference, ladder, pacing, resume, provenance, coverage summary) on the three deepest chains
before 84 hours are committed. Its coverage summary is also the first real test of the
0.c/0.d fractions — which are already pre-registered (§12), so it cannot move them.

### 7.4 Why the ladder, and not "every strike in the band"

The counterfactual, at today's price levels and assumed increments. **Every figure in this
block is HYPOTHESIS, and rev 1 labelled it as computed fact. It is not.**

```
full-band contracts / cycle across 24 underlyings           =  2,826   HYPOTHESIS
  (SPY 460, QQQ 430, DIA 318, IWM 176, MSFT 120, ...)               HYPOTHESIS
aggregate calls  = 2,826 × 34                               =  96,084  HYPOTHESIS
total requests   (+1,632 reference)                         =  97,716  HYPOTHESIS
wall clock @12.1 s                                          =  328.4 hours = 13.7 days
bars             = 96,084 × 48.09                           ≈ 4,621,000   (rev 2: was 4,141,000 at 43.1)
```

**≈4.62M bars would be 2.31× `backfill_max_total_bars = 2,000,000`.**

**Why this is labelled HYPOTHESIS, and what follows (new in rev 2).** This argument is
load-bearing — it is the **sole** justification for preferring `LADDER_17` over full-band
coverage — and rev 1 resolved it with an assumption in the direction that favours the design it
had already chosen. **FACT (F48):** SPY's $1.00 ladder is established only over 709.0–831.0,
about ±8% of a ~770 reference, and **FACT (F38):** the band filter was applied server-side, so
nothing in the DB establishes the increment beyond that. The "460 contracts per SPY cycle"
figure extrapolates $1.00 out to ±15%. US index ETFs commonly **widen to $5 in the wings**; if
they do, the full-band count is materially smaller and the multiple narrows — partly offset in
the other direction by the 48.09-session correction above.

**Commitment:** the comparison is **recomputed from Stage A's actual unfiltered ladders**, which
cost nothing extra (§3.4 already records each ladder's rung count and `[min, max]`), and the
recomputation is reported in the coverage summary. **It may not be used to loosen any §12
constant.** Its only permitted uses are widening or narrowing the underlying set, and — if the
full band turns out to fit under the ceiling — pre-registering a denser rung set **before**
Stage B begins. This is **OQ-5**.

### 7.5 Pacing and rate-limit uncertainty

**FACT (F8):** 12.1 s/request is the **equities Basic** figure and the only rate documented
anywhere in the repo. **FACT (F9):** options traffic shares that key by default. **FACT:**
`docs/MARKET_DATA_SETUP.md` documents no options plan, rate limit, or history depth.

So 98.7 hours is the figure **at the only pacing the repo knows**, and it is a **no-retry lower
bound** (§7.6 permits up to 5 attempts per request). It is a planning number, not a vendor
guarantee — and per §7.0 it is void until D13 is resolved. Three consequences:

1. If the options entitlement has its own, higher rate, the run is proportionally shorter —
   **OQ-2**. The adapter must read its pacing from a setting (§8.1), never a literal.
2. If a dedicated options key is configured, its budget is independent of the equities worker
   — but the equities worker's own pacing is unchanged, so no arithmetic here moves.
3. **The backfill's own provenance must record the pacing actually used**, so a later run at a
   different rate is distinguishable.

### 7.6 Adapter pacing design (fixes D4)

**FACT (F10 vs F11):** the options adapter is a single unretried attempt; the equities adapter
self-paces and backs off. The fix is a direct port, not an invention:

```
MassiveOptionsAdapter.__init__(..., min_request_spacing_s: float | None = None)
    self._spacing_s     = min_request_spacing_s
                          ?? settings.options_min_request_spacing_s        # NEW setting
                          ?? settings.market_data_min_request_spacing_s    # fallback: 12.1
    self._last_request  = 0.0

_get(path):
    ensure_not_engaged()                        # FACT F33 — already present, keep it first
    for attempt in 1.._MAX_ATTEMPTS (5):
        pace to self._spacing_s, re-checking ensure_not_engaged() each 0.1s   # massive.py:118-125
        issue the request
        200                -> return
        401/403            -> raise AdapterError(not authorized)   # never retried
        in {429,500,502,503,504} and attempt < 5
                           -> sleep min(30.0, 1.5 * 2**(attempt-1)), honouring `retry-after`
        else               -> break
    raise AdapterError(..., rate_limited=(last_status == 429))
```

Three properties carried over verbatim from `massive.py:109-162`, each load-bearing:

- The pacing wait is **chunked with `ensure_not_engaged()` inside it**. **FACT (F45), and rev 1
  got both the numbers and the citations wrong:** the pacing loop chunks at **0.1 s**
  (`massive.py:160-166`) and the backoff `_sleep` chunks at **0.2 s** (`massive.py:144-149`) —
  neither is at `:52-56` or `:118-124`. More importantly, the real worst case is **an in-flight
  HTTP request**: `_TIMEOUT = 20.0` (`massive_options.py:34`) and `ensure_not_engaged()` is
  checked **once per `_get`** (`massive_options.py:117`). So the true bound is

  ```
  kill latency  <=  max(pacing chunk 0.1 s, backoff chunk 0.2 s, in-flight request timeout 20.0 s)
                 =  20.0 s
  ```

  — **not** "a tenth of a second", which was off by two orders of magnitude. 20 s is still a
  bound an operator does not wait out, and it is the honest one. If a tighter bound is wanted it
  is a requirement on `_TIMEOUT` (and on cancelling an in-flight request), not a property the
  current code has; it is listed as such in §14.
- `retry-after` is honoured when the header parses as a number (`massive.py:146-151`).
- 401/403 is terminal and never retried — burning the budget against an entitlement wall is
  how a 4-day run turns into a 4-day no-op.

New setting: `options_min_request_spacing_s: float | None = None` on `Settings`, defaulting to
`None` so the equities figure is inherited until the options rate is actually known.

### 7.7 Concurrency with the live probation worker — a blocker not in the map

**FACT (F21):** `cli.py:389-419` runs the entire backfill inside **one**
`session_scope(write=True)`. **FACT (F22):** that begins `IMMEDIATE` on SQLite and holds the
write lock for the scope's lifetime; the function's own docstring says "Keep write scopes
SHORT and never span network I/O inside one." **FACT (memory):** one worker per DB;
write-intent sessions are sticky. **FACT:** paper probation has been live since
2026-09-10 20:00 UTC against `data/signalforge.sqlite`.

A 96-hour run under today's CLI would hold the SQLite write lock for four days and lock the
probation worker out. This is **blocker D9** and it must be fixed before I-O2.

**Fix (HYPOTHESIS), two parts:**

1. **Short write scopes — and real `commit()`s, which today do not exist.**
   **FACT (F44), and this corrects §8.1's claim that the existing run is "genuinely
   resumable":** `options_backfill.py` calls `session.flush()` at seven sites and **`commit()`
   at none**; the only enclosing scope is `cli.py:389`, and `session_scope` rolls back on any
   exception (`db/session.py:110-112`). `KillSwitchEngaged` is a `RuntimeError`, **not** an
   `AdapterError`, so it is not caught by the handlers at `:257`/`:332` and propagates straight
   through that scope. **Engaging the kill switch mid-run therefore discards every bar written
   so far AND the `IngestionRun` row itself — leaving no id to `--resume`.** The run is resumable
   only on the paths that end normally, which is not the path a 99-hour run actually takes.

   The fix has four parts, all required:
   - The run loop moves outside the `session_scope`; the network fetch happens with **no
     transaction open**. Where a single long-lived session is kept, `commit()` then
     `set_write_intent(session, False)` before the fetch and `set_write_intent(session, True)`
     before the write (`db/session.py:118-129`).
   - Each per-contract checkpoint is **`commit()`ed**, not flushed.
   - The `IngestionRun` row is **committed before the first network call**, so a resume id
     survives an abort of any kind.
   - `KillSwitchEngaged` is caught **at the loop boundary**, which commits the checkpoint and
     exits with a terminal run status, rather than propagating through the scope. It must remain
     terminal — the kill switch is never retried — but it must not be destructive.
2. **Separate database file for the bulk run.** Even with short scopes, a 4-day writer
   contending with the probation worker violates the one-worker-per-DB rule. Run the backfill
   against a dedicated file via `DATABASE_URL`, then merge the option tables into the live DB in
   one short transaction **while the probation worker is stopped**. Three specifications rev 1
   left out, each of which decides whether this is buildable:
   - **Where the bulk DB comes from.** The backfill needs `instrument` and `ohlcv_daily` to
     compute §2.2 reference prices. **FACT:** the live file is ~618 MB with 1,686,930
     `ohlcv_daily` rows (F24). The bulk DB is a **file-level copy of the live DB taken with the
     probation worker stopped**, and its copy timestamp is recorded on the `IngestionRun`. It is
     not re-ingested (that would be a second multi-day job and a second provenance chain), and
     it is **not refreshed mid-run** — the equity series the ladder is centred on must be
     point-in-time consistent for the whole four days, and a mid-run refresh would silently
     re-centre already-fetched cycles.
   - **`IngestionRun` is merged too, and its id changes.** Its primary key is an integer that
     will collide with live rows. The merged row gets a **new** id with the **original** id
     recorded on it (`notes`/`gaps_json`), because F19's whole provenance argument depends on
     that row surviving the merge and staying traceable to the bulk file.
   - **The validation artefact is merged too.** **FACT:** `cli.py:~418` runs
     `validate_option_aggregates(..., persist=True)` inside the same scope, writing a further
     row that rev 1's merge plan did not mention.

   `(option_ticker, session_date, source)` / `(option_ticker, source)` uniqueness makes the
   option-table merge idempotent (`market.py:245,301`). **Which of the two fixes is sufficient
   is OQ-4.**

---

## 8. Resumable `IngestionRun` provenance

### 8.1 What already works and must not be lost

**Corrected in rev 2 — see §7.7 fix 1.** The design below is right and is kept, but the run as
shipped is resumable **only on paths that end normally**: **FACT (F44)** there is no `commit()`
anywhere in `options_backfill.py`, and a `KillSwitchEngaged` propagates through
`session_scope` and rolls back the `IngestionRun` row along with every bar. What follows
describes the intended design, which §7.7 fix 1 makes real.

**FACT (F19):** `backfill_option_aggregates` writes the structure of a resumable run —
`requested_start/end`, `symbols_requested`, caps in `notes`, per-underlying `gaps_json`
(contracts, bars, `dropped_by_cap`, `dropped_expirations`, `bars_clamped`, `expirations`),
`symbols_ok`, `symbols_failed`, `bars_written/skipped`, `coverage_first/last`, a per-contract
checkpoint flush, and the deliberate rule that budget-limited or fetch-failed underlyings stay
retryable while cap-trimmed ones are marked done (`options_backfill.py:406-418`). That design
is correct and is kept.

### 8.2 What must be added

`gaps_json` becomes **per (underlying, cycle)**, not per underlying — without that,
`dropped_by_cap` cannot answer gate 0.c, which is a per-cycle question:

```jsonc
gaps_json = {
  "SPY": {
    "cycles": {
      "2023-11-17": {
        "entry_as_of": "2023-09-18",
        "reference_price": 0.0,            // recorded; a scalar, not a series
        "reference_priced_on": "2023-09-18",
        "reference_staleness_sessions": 0,
        "ladder_rungs_seen": 0,            // true vendor ladder size, unfiltered
        "ladder_min_strike": 0.0, "ladder_max_strike": 0.0,
        "selected_calls": 17, "selected_puts": 17,
        "rungs_per_side": [8, 8],
        "brackets_band": true,
        "contracts_fetched": 34,
        "bars_written": 1465,
        "sessions_expected": 48,     // DTE-60 minus the 5-session buffer, §3.5
        "bar_continuity_fraction": 0.0,    // per-contract min and mean, both recorded
        "excluded": null,                  // or one of the reasons below
        "shares_per_contract_refusals": 0,
        "parity_eligible_sessions": 0      // §6.3 — a COUNT only
      }
    },
    "cycles_total": 34, "cycles_covered": 34, "cycles_excluded": {}
  }
}
```

Exclusion reason vocabulary — frozen here so the coverage summary is machine-comparable:
`no_instrument`, `no_bar_on_or_before`, `reference_stale`,
`reference_price_outside_ladder`, `ladder_too_coarse`, `insufficient_rungs_per_side`,
`no_contracts_returned`, `contract_fetch_failed`, `bar_budget_exhausted`,
`shares_per_contract_not_100`,
**`strike_not_listed_as_of_entry`** (§3.3a, new in rev 2),
**`ladder_incomplete`** (§3.4 — page cap hit or a row failed to parse, new in rev 2).

Per-cycle fields added in rev 2, all counts or identities and therefore §10-permissible:
`strike_listing_basis` (`vendor_as_of` | `first_bar_proxy` | `none`), `pages_walked`,
`next_url_exhausted`, `rows_unparseable`, `iv_rank1_inadmissible_by_reason`
(`{expired_or_nonpositive, below_intrinsic, above_upper_bound, non_convergent, vega_too_low}`),
and `print_time_known` (always `false` today, §5.4).

Also required:

- **`options_ingest.py` must write an `IngestionRun`.** **FACT (F20):** it writes none. Map
  §1.3 D6: a path that leaves no trace cannot be audited, and provenance is a gate-8 input.
- **Record the run's own parameters on the run**, not only in prose `notes`: window, cycle
  rule, DTE window, band, ladder identity (`LADDER_17`), `max_total_bars = 2,000,000`, the
  **pacing actually used**, the adapter version, and the `options_config_hash` of §5.5. A
  free-text `notes` field cannot be diffed; these belong in a structured column or a reserved
  `gaps_json` key.
- **`IngestionRun.kind` is `String(16)` and the written value is 20 characters** (FACT F34).
  SQLite does not enforce it; Postgres would truncate or error. Widen the column in the same
  migration that adds anything else, or shorten the literal — do not leave it.
- **Decision 6 is recorded with the run** (`backfill_max_total_bars = 2,000,000`, raised from
  200,000), as decision 6 itself requires.

---

## 9. `options_scope_json` — snapshot identity, and which side of S11 writes it

### 9.1 The problem

**FACT (F29), restated correctly in rev 2 — rev 1's version of this fact was wrong and the
design built on it was unsound.** `DataSnapshot`'s **database** identity is
`UniqueConstraint("key")` and nothing else (`research.py:235`). `symbols_json` and
`continuity_mapping_id` are checked only **procedurally**, inside `if key is not None`
(`promotion.py:605-622`); `description` and `source_note` are never checked at all. There is no
composite key to extend.

Two options evaluations against materially different option datasets — a different band, a
different ladder, a different IV source, a different `q` policy, a different spread multiplier
— would resolve to the **same** snapshot, and `StrategySealedTest` is unique on
`(strategy_version_id, dataset_snapshot_id)` (`db/models/research.py:263`). Sealed-look
protection would then be silently defeated: a second look on a genuinely different dataset
would reuse the first sealed row rather than counting as a new look.

**And there is a second, worse path that rev 1 missed entirely.** When `key is None`,
`get_or_create_dataset_snapshot` takes a different branch (`promotion.py:624-631`): it iterates
snapshots with `reusable_by_new_evaluations = True` and returns the **first** whose sorted
symbol set matches the request, **consulting nothing else**. **FACT (query):** `data_snapshot`
id 3, key `universe_24_ex_meta`, `reusable = 1`, holds exactly the 24 symbols §1.1 names. So an
options evaluation over those 24 symbols called **without an explicit key** binds silently to
the **live equity snapshot**, ignoring `options_scope_json` entirely — and
`promotion.py:945` then reuses `existing_sealed.window_start` keyed on that snapshot id. This
is not hypothetical: ids 6, 8 and 10 in the live DB are `universe_auto_*` rows minted by that
branch. **FACT:** `_symbols_fingerprint` (`promotion.py:567-569`) hashes symbols only, so the
auto-generated key cannot distinguish two options scopes either.

### 9.2 The content of `options_scope_json` (HYPOTHESIS)

A new column on `DataSnapshot`, **part of the snapshot key**, whose canonical JSON is hashed
into `options_scope_hash`:

```jsonc
{
  "schema_version": 1,
  "underlyings": ["AAPL", "...", "XOM"],          // the 24, sorted
  "window": {"start": "2023-09-04", "end": "2026-09-04"},
  "cycle_rule": "monthly_third_friday",
  "cycles": 34,
  "dte_entry": {"min": 21, "max": 60},
  "strike_band_pct": 0.15,
  "ladder": {"id": "LADDER_17", "offsets": [-0.150, ..., 0.150], "min_rungs_per_side": 7},
  "rights": ["call", "put"],
  "fetch_span": {"from_dte": 60, "pre_entry_buffer_sessions": 5},
  "reference_price": {"source": "massive", "basis": "close",
                      "max_staleness_sessions": 3},
  "iv_policy": {"primary": "local_bs_inverted",
                "mark_fallback": "same_session_surface",
                "surface_fit": "quadratic_log_moneyness",
                "term_interp": "linear_total_variance",
                "min_prints_per_expiry": 5, "min_distinct_strikes": 3,
                "extrapolation": false,
                "realised_vol_fallback": false},
  "q_policy": {"precedence": ["vendor_dividends", "parity_implied"],
               "parity_min_pairs": 3, "parity_max_abs_log_moneyness": 0.05,
               "parity_statistic": "median", "default_zero_permitted": false},
  "r_policy": {"source": "config_constant", "value": 0.04},
  "spread_model": {"nbbo_available": false, "model_id": "<D2's modelled spread>",
                   "spread_multipliers": [1.0, 2.0],      // decision 5 / gate 4b, §9.2b
                   "multiplier_this_evaluation": 1.0},
  "strike_listing_basis": "vendor_as_of",         // or "first_bar_proxy" / "none" — §3.3a
  "fill_timing": {"basis": "<D2: next_session | same_session_with_penalty>",  // §5.4
                  "print_time_known": false},
  "iv_admissibility": {"max_price_residual": 1e-4, "min_vega": 1e-3},         // §5.2
  "deliverable": {"require_shares_per_contract": 100},
  "coverage_thresholds": {"gate_0c_cycles_bracket": 0.90,
                          "gate_0d_session_bars": 0.80},
  "options_config_hash": "<hash of OptionsEvaluationConfig, §5.5>",
  "ingestion_run_ids": [/* every run that produced this dataset */]
}
```

**Identity rule (rewritten in rev 2).** Rev 1 proposed making `options_scope_json` "part of the
snapshot key". **That must not be implemented as a database constraint change.** There is no
composite key to join (F29), and `UniqueConstraint("key", "options_scope_json")` on a
**nullable** column would mean SQL NULL-inequality lets two rows with `key='universe_24_ex_meta'`
and NULL scope both be legal — **silently removing the single-key uniqueness that today protects
the two live PAPER_APPROVED equity strategies' snapshots.** The rule is therefore enforced
**procedurally**, as an extension of the refusal that already exists:

1. **`UniqueConstraint("key")` is NOT altered.** See the migration plan below for why this is
   not merely a preference.
2. **Keyed path (`promotion.py:605-622`).** `get_or_create_dataset_snapshot` gains an
   `options_scope` argument. A `key` hit whose stored `options_scope_json` differs from what was
   just requested raises `ValueError`, exactly as a differing symbol set does today. The NULL
   case is a difference: a request **with** a scope against a row **without** one refuses, and
   the reverse refuses too.
3. **Unkeyed path (`promotion.py:624-631`) — the hole rev 1 left open.** The symbol-match
   fallback must **skip** any snapshot whose stored `options_scope_json` differs from the
   request, **including the NULL-vs-present case**. Equivalently and preferably, both together:
   **the options promotion path must always pass an explicit `key`**, and the fallback must
   refuse rather than match when an `options_scope` is supplied. Belt and braces, because this
   is the path that would otherwise collapse the options ledger onto the equity one.
4. **`description` and `source_note` are checked by nothing today** and must not be relied on to
   carry any part of identity. Stated explicitly because rev 1's F29 implied they were.

Changing any coverage parameter therefore forces a **new snapshot** and a **new sealed test**,
preserving immutability. `ingestion_run_ids` is carried for provenance but **excluded from the
hash** — re-running a resume must not mint a new snapshot for an identical dataset definition.

#### 9.2a Migration plan (BLOCKER D15, new in rev 2)

Rev 1 added a column to the parent of the sealed-look ledger on a live probation database and
stated no migration, no rollback, and no blocker entry.

**FACT (F46):** `data_snapshot` is the parent of three foreign keys, one of them
`strategy_sealed_test` with **ON DELETE CASCADE** over **22 live rows** — the R1/R3 sealed-look
record itself. Migrations run with `render_as_batch=_is_sqlite()` and `PRAGMA foreign_keys=ON`
(`migrations/env.py:50,67,71`), so **any change to that table's UNIQUE constraint forces a batch
copy-and-swap rebuild of the parent table** — a documented SQLite/alembic hazard — against a
~618 MB file a live worker is writing.

**Requirements:**

- The migration is **`ADD COLUMN` only**: `options_scope_json`, JSON, nullable, no constraint,
  no index. Batch mode is not triggered by a plain add-column.
- **`UniqueConstraint("key")` is not touched**, now or later. Scope identity lives in
  `get_or_create_dataset_snapshot` (above), not in DDL.
- If `options_scope_json` is **ever** to enter a constraint in some future revision, it must
  first be made `NOT NULL` with a `'{}'` sentinel backfilled on every existing row, in its own
  migration — otherwise NULL-inequality defeats the constraint silently. Recorded here so a
  later implementer does not rediscover it the hard way.
- **Before the migration runs:** the probation worker is stopped and the DB file is copied. The
  rollback is `DROP COLUMN` (batch-mode on SQLite) or, if that is unavailable, restoring the
  copy — the copy is the real rollback and must exist before the migration starts.

#### 9.2b Gate 4b (dual-spread) must be part of the identity (new in rev 2)

**Decision 5 (binding):** "gate 4b (dual-spread) becomes permanent", on both asset classes. Map
§2.4 makes running every evaluation at baseline and 2× baseline "the single cheapest defence
against the missing-NBBO problem". **FACT (grep): the strings `4b` and `dual-spread` appeared
nowhere in rev 1 of this document.**

The consequence was a direct defeat of §9.1's own mechanism: rev 1's `options_scope_json`
carried only `spread_model: {nbbo_available: false, model_id: "<D2's modelled spread>"}`, with
no spread constant pre-registered in §12 — so **an evaluation at baseline spread and the same
evaluation at 2× spread would resolve to the same `options_scope_hash`**, the same snapshot, and
the same sealed row.

**Requirement:** `spread_model` carries `spread_multipliers: [1.0, 2.0]` and, on a single
evaluation record, the multiplier that evaluation used. `SPREAD_MULTIPLIERS` is pre-registered in
§12. Whether the pair is **two snapshots** or **one snapshot carrying both results** is D2/D4's
choice — but the identity must distinguish them, and a run reporting only one of the two is not
a gate-4b run.

### 9.3 Which side of S11 writes it

**FACT (F32):** S11's `source_modules` are `signalforge.options` **and**
`signalforge.data.options_backfill`; `forbidden_modules` include `signalforge.research.scan`
and `signalforge.research.candidates`. `options_scope_json` is scan-facing evidence metadata
on a `research` model.

**Rule (map §3.5, restated operationally):**

```
signalforge.data.options_backfill
    RETURNS  an OptionsCoverageSummary  — a plain frozen dataclass of counts and
             completeness, no research imports, no writes into research.* tables

signalforge.research.<options promotion path>
    COMPOSES options_scope_json from (a) the pre-registered parameters of §12 and
             (b) that returned summary, and WRITES it onto DataSnapshot
```

The backfill never imports `research`, never writes a `research.*` row, and never learns that
`options_scope_json` exists. S11 stays exactly as written over both modules — which is
essential, because `data.options_backfill` is precisely the module D1/I-O1 modifies.

**Direction check:** the coverage summary is a return value, so the dependency arrow is
`research → data.options_backfill`, which S11 does not forbid (it forbids the reverse). The
existing `OptionsCoverage` dataclass in `data/options_ingest.py:26-37` is the shape to
follow — a dataclass of counts, returned, not written.

`IngestionRun` is a `db.models.market` row, not a `research` row, so the backfill continues to
write it directly with no S11 exposure.

---

## 10. The COVERAGE-SUMMARY-ONLY rule

Map §7's pre-registration ordering rule, made mechanical for D1.

### 10.1 What I-O2 may expose before D5 is committed

**Only** the `OptionsCoverageSummary`: per (underlying, cycle) — whether the chain brackets
the target, contract counts per side, bar-continuity fractions, exclusion counts by reason,
`shares_per_contract != 100` refusal counts, `IngestionRun` gaps, and the §6.3 count of
parity-eligible sessions. **Counts, dates, identities and completeness fractions. Nothing else.**

### 10.2 What is sealed

**No option price, IV, greek, return, credit, or P&L value — and no summary statistic over any
of them — may be inspected by a person or by a script until D5 is committed.** Specifically
sealed: `OptionAggregateDaily.{open,high,low,close,vwap}`, `volume`, `transactions`, every
inverted IV, every surface fit output, every parity-implied `q` value, and every quantity
derived from them.

`volume` and `transactions` are sealed even though they are not prices: a per-strike volume
profile is a liquidity signal that would let a strike-selection rule be reverse-engineered from
outcomes. Their **presence** (a bar exists) is the 0.d continuity fraction and is permitted;
their **values** are not.

**Rewritten in rev 2, because "sealed" was ambiguous between two very different things and the
ambiguity cut both ways.** As written it could be read as forbidding any volume-based options
liquidity filter at all — leaving the strategy with no liquidity control other than bar
presence, against the spirit of map §2.4(3) — or, later, as permitting one chosen **after** a
coverage summary has been read. The rule is therefore split:

- **Inspection: never.** `volume` and `transactions` may **never** be inspected by a person or
  by an exploratory script — not their values, not distributions, quantiles, or any other
  summary over them, at any point in the program. This does not expire when D5 is committed.
- **Programmatic use: only through a pre-registered filter.** They may be consumed **inside** a
  liquidity filter whose thresholds are pre-registered in D5 **before any coverage summary is
  read**, and which never returns a value — only an admit/reject decision and its count.
- **Any such threshold is a §12 constant and a field in `options_scope_json`**, so it cannot
  move silently and so a change to it mints a new snapshot and a new sealed look (§9.2). D1
  pre-registers none, because the thresholds are D5's; what D1 pre-registers is that they must
  exist before the summary is read, or not at all.

`reference_price` per cycle is permitted in the summary — it is an equity close, it is what
fixes the ladder, and it must be auditable. It is a scalar per cycle, not a series.

### 10.3 Enforcement (HYPOTHESIS)

Policy is not enforcement. Three mechanisms:

1. **The summary is a typed return value with no price fields.** If `OptionsCoverageSummary`
   has no attribute that can hold a price, a script cannot accidentally print one.
2. **The CLI's backfill output prints the summary only** — never a bar. Today
   `cli.py:399-412` already prints counts only; that must be preserved.
3. **A disclosure line in D5.** The pre-registration document states, as this document does in
   §0.1, exactly which queries were run to produce it. R5's disclosure obligation is the real
   protection; the other two only make accidental violation harder.

### 10.4 Sealed-look accounting starts at k=0

**FACT (F31):** `count_sealed_looks` keys on `Strategy.name`, so an options family
(e.g. `options_short_vertical.position`, per decision 12) has no prior `strategy_sealed_test`
rows and starts at `k_prior = 0` automatically. Nothing needs to be built and the equity
ledger cannot be conflated with it in either direction. **FACT (map §5.4, §0.4):** the two live
equity strategies stand at k=4, on a different family; no statement about options multiplicity
may cite them.

The real multiplicity risk is R5 disclosure of **unsealed abandoned variants**, which the
options parameter space (structure × delta × DTE × width × `q` policy × `r`) makes easy to
leak. D5 must enumerate the **complete** grid so that "abandoned variant" is definable as "a
pre-registered cell that was not reported".

---

## 11. Blockers, consolidated

D1-D8 are the map's (§1.3). D9-D12 are new in this document; **D13-D16 are new in rev 2, and
D13 and D14 outrank every other item here** — D13 because it can void §7 entirely, D14 because
it would invalidate the dataset rather than merely delay it.

| # | Blocker | Status after D1 | Fix lands in |
|---|---|---|---|
| D1 | Lookback clamped to 365d, not overridable; `OptionsConfig` not env-settable (F13, F14) | Designed: explicit `window_start`/`window_end` on `BackfillCaps`, `--since/--until` already exist at `cli.py:345-347` but are re-clamped at `options_backfill.py:205` — remove the clamp | I-O1 |
| D2 | Strike band centred on today's price (F12) | Designed §2.2 | I-O1 |
| D3 | Caps are per-underlying, not per-cycle (F15, F16) | Designed §3.2-3.3 | I-O1 |
| D4 | No pacing/retry in the options adapter (F10) | Designed §7.6 | I-O1 |
| D5 | No dated IV/greeks/OI series (F2, F4) | Designed §5 — decision 7's local inversion + same-session surface, N floor pre-registered | I-O1/I-O3 |
| D6 | `options_ingest.py` writes no `IngestionRun` (F20) | Designed §8.2 | I-O1 |
| D7 | No options corporate-action handling (F23) | **Partly unresolved** — mechanical ladder-bracket check designed (§2.3); no adjustment-event source exists | I-O1 + OQ-3 |
| D8 | No dividend-yield series (F23, F24) | Designed §6 with a precedence that never reaches `q=0`; rank 1 needs an unprobed endpoint | I-O1 + OQ-1 |
| **D9** | The whole backfill runs in one `session_scope(write=True)` spanning all network I/O — a 96-hour SQLite write lock against the live probation DB (F21, F22) | **New.** Designed §7.7 | I-O1, before I-O2 |
| **D10** | The per-contract fetch range is the whole window, not the cycle's trade window — ~10× the bars needed (F17) | **New.** Designed §3.5; this is what keeps the run under 2,000,000 bars | I-O1 |
| **D11** | `options` is excluded from `SCOPE_HASH_FIELDS`, so `risk_free_rate` and every backfill parameter can change without changing `config_hash` (F27, F28) | **New.** Designed §5.5 — a separate `options_config_hash`; never touch the equity scope hash | I-O1/I-O4 |
| **D12** | `IngestionRun.kind` is `String(16)`; `'options_agg_backfill'` is 20 chars (F34) | **New.** Widen the column or shorten the literal | I-O1 |
| **D13** | `fetch_contracts` sends **no expired-contracts flag** (F40), and no expired contract has ever been returned to this repo (F42). If the endpoint defaults to live contracts only, **33 of 34 cycles return zero rows** and every figure in §7 is uncosted | **New, rev 2. BLOCKING and ranked first.** Designed §7.0 — a one-request probe of a 2023 SPY expiry, recorded in `entitlement_check`, before Stage A | probe **before** I-O2; parameter in I-O1 |
| **D14** | `fetch_contracts` sends **no `as_of`** (F40) and `OptionContract` has no listing date (F41), so the ladder used to pick strikes for a 2023 cycle is the ladder as it stood at that series' **end of life** — a lookahead that favourably selects short strikes in the direction the market actually went | **New, rev 2. BLOCKING.** Designed §3.3a: point-in-time call, else a first-bar proxy, else the ladder may not be used for selection at all | probe **before** I-O2; parameter in I-O1 |
| **D15** | `options_scope_json` was to be added to `DataSnapshot` — the parent of `strategy_sealed_test` (ON DELETE CASCADE, 22 live rows) — with no migration, no rollback, and a proposed constraint change that batch-mode SQLite would satisfy by rebuilding that parent table (F46) | **New, rev 2.** Designed §9.2a: `ADD COLUMN` only, `UniqueConstraint("key")` untouched, worker stopped and file copied first, copy is the rollback | I-O1/I-O4 |
| **D16** | `options_backfill.py` has **no `commit()`** (F44) and `KillSwitchEngaged` is not caught by its `except AdapterError` handlers — engaging the kill switch mid-run discards every bar **and** the `IngestionRun` row, leaving no id to `--resume` | **New, rev 2.** Designed §7.7 fix 1 | I-O1, before I-O2 |

---

## 12. Pre-registered constants (the D5 hand-off)

Fixed **now**, before the backfill runs and before any outcome is observed. R1 and map §1.5
require this ordering. Each is folded into `options_config_hash` and hence into
`options_scope_json`, so none can move silently. R4 permits making a gate more searching; none
of these may be loosened after a coverage summary is seen.

**Standing of this table (corrected in rev 2).** Map §7 Phase D assigns the gate 0.c/0.d
fractions, the §2.4b surface N floor and the pin band to **D5**, not to D1. Pre-registering them
earlier is **stricter**, not weaker, so stating them here is not an R1 violation — but D1 has no
authority to bind D5 under the map's own role split, and rev 1's phrase "binding for D5" claimed
one. The correct standing: **every value below is PROPOSED to D5 and is to be restated verbatim
there. Any difference between D5's value and this table is a deviation requiring disclosure
under R5, with D5's value governing and this table cited as the earlier pre-registration.** D5
must cite this table by name so the ordering is auditable.

| Constant | Value | Origin |
|---|---|---|
| `GATE_0C_CYCLES_BRACKET` | **0.90** | map §1.5 HYPOTHESIS, adopted |
| `GATE_0D_SESSION_BARS` | **0.80** | map §1.5 HYPOTHESIS, adopted |
| `SURFACE_MIN_PRINTS_PER_EXPIRY` | **5** | map §2.4b HYPOTHESIS, adopted |
| `SURFACE_MIN_DISTINCT_STRIKES` | **3** (on the side being marked) | map §2.4b |
| `SURFACE_FIT` | quadratic in `ln(K/S)`, per expiry, unweighted | §5.3 |
| `SURFACE_TERM_INTERP` | linear in total variance `σ²·t`; **no extrapolation** | §5.3 |
| `REALISED_VOL_FALLBACK` | **forbidden** | map §2.4b |
| `REFERENCE_SOURCE` | `massive`, `close`, `session_date <= as_of` | §2.2 |
| `REFERENCE_MAX_STALENESS_SESSIONS` | **3** | §2.2 |
| `LADDER_BRACKET_MIN_RUNGS` | **3** per side of the reference on the true vendor ladder | §2.3 |
| `LADDER_17` offsets | 0, ±0.015, ±0.030, ±0.045, ±0.060, ±0.080, ±0.100, ±0.125, ±0.150 | §3.3 |
| `MIN_RUNGS_PER_SIDE` | **7** | map §1.1 |
| `PRE_ENTRY_BUFFER_SESSIONS` | **5** | §3.5 |
| `DTE_ENTRY_MIN` / `MAX` | **21 / 60** | map §1.1 verbatim (§4.1; rev 1's 20 withdrawn) |
| `CYCLE_RULE` | monthly third Friday | §4.1 |
| `WINDOW` | 2023-09-04 → 2026-09-04 (1,096 days; floor is 716) | §4.1, F30 |
| `Q_PRECEDENCE` | `vendor_dividends` → `parity_implied`; **`q=0` never reached** | §6.2, decision 11 |
| `PARITY_MIN_PAIRS` | **3** | §6.2 |
| `PARITY_MAX_ABS_LOG_MONEYNESS` | **0.05** | §6.2 |
| `PARITY_STATISTIC` | median | §6.2 |
| `R_SOURCE` | `config_constant`, 0.04, recorded per evaluation, a D5 sensitivity axis | §5.5, F27 |
| `REQUIRE_SHARES_PER_CONTRACT` | **100**, refusals counted (gate 0.h) | map §2.3, §1.5 |
| `BACKFILL_MAX_TOTAL_BARS` | **2,000,000** | decision 6 |
| `IV_MAX_PRICE_RESIDUAL` | **1e-4** absolute, in option price units — a rank-1 inversion is inadmissible above this when re-priced at the solved sigma | §5.2 (new in rev 2) |
| `IV_MIN_VEGA` | **1e-3** absolute at the solved sigma — below it the price function is flat and the sigma is arbitrary; the contract-session falls to rank 2, marking only | §5.2 (new in rev 2) |
| `SPREAD_MULTIPLIERS` | **(1.0, 2.0)** — every evaluation runs at both; the multiplier is part of the evaluation's identity | decision 5, map §2.4, §9.2b (new in rev 2) |
| `STRIKE_LISTING_BASIS` | `vendor_as_of` → `first_bar_proxy` → `none`; recorded per dataset. Under `none` the ladder may not be used for selection | §3.3a (new in rev 2) |
| `LADDER_SHORTFALL_RESPONSE` | drop the underlying, **or** pre-register a finer rung set before Stage A — **never** lower `MIN_RUNGS_PER_SIDE`, `LADDER_BRACKET_MIN_RUNGS` or `GATE_0C_CYCLES_BRACKET` | §3.3 (new in rev 2) |
| `VOLUME_INSPECTION` | **forbidden, permanently**; programmatic use only through a D5-pre-registered filter whose thresholds are §12 constants | §10.2 (new in rev 2) |

**Derivations, stated so they are visibly design judgements and not empirical ones:** 0.c
below ~90% means the strike-selection rule is being rewritten by data availability in ≥1 cycle
in 10; 0.d below ~80% means more than one session in five is priced by a model rather than a
print, exceeding the synthetic-mark ceiling gate 8 enforces anyway (map §1.5). If the
delivered data cannot meet them, the response is more data or a narrower underlying set —
**never a lower fraction chosen after the fact.**

---

## 13. Open questions

**Ranking (rev 2): OQ-9 and OQ-10 rank ahead of OQ-1 and OQ-2.** Both are answered by single
requests, both are prerequisites to Stage A, and both can invalidate work already done rather
than merely delay it. Probe all four together in one sitting.

**OQ-9 — does `/v3/reference/options/contracts` return EXPIRED contracts? (blocker D13.)**
Unknown, and nothing in the repo bears on it: **FACT (F40)** no expired-contracts flag is sent,
**FACT (F42)** every one of the 888 stored contracts was unexpired at fetch time. If the answer
is no, 33 of 34 cycles return zero rows and §7.0-§7.4 are void. *Recommendation: one request for
a single 2023 SPY monthly expiry, with and without the vendor's expired parameter, recorded in
`entitlement_check`. **Blocks: Stage A, and the validity of all of §7.***

**OQ-10 — does the contracts endpoint accept a point-in-time (`as_of`) parameter? (blocker
D14.)** Unknown. Without it the strike ladder for a 2023 cycle is an end-of-life ladder and the
selection in §3.3 has a lookahead (§3.3a). *Recommendation: the same probe as OQ-9, adding the
vendor's `as_of` set to a 2023 date and comparing the returned strike set against the
unparameterised call — a smaller set proves the parameter works. If it does not, §3.3a's
first-bar proxy applies and the weaker basis is recorded in `options_scope_json`; if neither, the
ladder may not be used for selection and the contamination becomes a named D5 falsification
risk. **Blocks: Stage A.***

**OQ-1 — `/v3/reference/dividends` entitlement.** Unknown; the endpoint is absent from all **21**
distinct probed endpoints in `entitlement_check` (F47; rev 1 said 25, which was wrong — the
conclusion is unchanged). It decides whether `q` rests on declared
dividends (rank 1) or on an American-parity approximation (rank 2, §6.2). One probe request
answers it. **Blocks:** I-O2 sequencing, gate 0.g provenance, D5's `q` sensitivity axis.
*Recommendation: probe `/v3/reference/dividends` and `/v3/reference/splits` together, in the
same shape that produced the existing `entitlement_check` rows, before the Stage A backfill.*

**OQ-2 — options rate limit and history depth.** Undocumented anywhere in the repo (F8;
`docs/MARKET_DATA_SETUP.md`). 98.7 hours is computed at the **equities Basic** 12.1 s/request
and options traffic shares that key by default (F9). Also unknown: how far back
`/v2/aggs/ticker/{O:contract}` history actually reaches — if it is shallower than 2023-09 the
window in §4.1 must move, and with it the cycle count and every figure in §7.
*Recommendation: before Stage A, run one `fetch_option_aggregates` on a single long-dated
expired SPY contract from 2023 and record the earliest date returned, on an `IngestionRun`
with `earliest_available_date` — the column already exists (`market.py:375`).*

**OQ-3 — no corporate-action source (D7).** `corporate_action` is empty, `div_cash` and
`split_factor` are uniformly 0/1.0, and the adapter returns `()` (F23, F24). The ladder-bracket
check (§2.3) detects a split's *effect* but cannot name the event or date, so an excluded cycle
cannot be distinguished from a genuinely empty chain. **Blocks:** a clean gate-0.h record.
*Recommendation: if OQ-1's probe shows `/v3/reference/splits` is entitled, ingest it into the
existing `CorporateAction` table before I-O2; if not, accept the ladder-bracket check as the
sole mechanism and record the limitation in `options_scope_json`.*

**OQ-4 — which D9 fix is sufficient.** Short write scopes alone, or a separate database file
plus a merge (§7.7)? The separate-file route is safer but adds a merge step that must itself be
idempotent and auditable. **Blocks:** I-O2 start. *This one is the orchestrator's, not a data
question.*

**OQ-5 — strike increments, and the whole of §7.2/§7.4 (materially expanded in rev 2).** Only
SPY's $1.00 ladder is FACT, and **only within ±8%** (F37, F48); everything else in §7.2 and
**all** of §7.4 is a standard-conventions HYPOTHESIS. Rev 1 said a coarser ladder is "the safe
direction"; that is true for the **bar budget** and **false for coverage** — §3.3's recomputation
shows that at a $1.00 increment five underlyings (XLRE 0.26, XLU 0.29, XLF 0.65, XLE 0.82, XLB
0.85) fall below `GATE_0C_CYCLES_BRACKET = 0.90` and the overall bracket fraction is 0.911, while
at $2.50 the ladder collapses. The increment assumption is therefore load-bearing in **two**
directions and in §7.4 it is the sole support for preferring `LADDER_17` over full-band coverage.
*Stage A's unfiltered ladders resolve it at no extra cost (§3.4 already records rung counts and
`[min, max]`). The recomputation may be used to widen or narrow the underlying set, or to
pre-register a denser rung set before Stage B — **never** to loosen a §12 constant (§3.3).*

**OQ-6 — American early exercise in the parity-implied `q`.** §6.2 rank 2 assumes European
parity on American contracts (`exercise_style`, `market.py:254`). The near-ATM restriction
(`|ln(K/S)| <= 0.05`) limits but does not remove the bias, and the bias direction on a
dividend-paying underlying is not obviously conservative for a **short** premium strategy —
which is the direction map §2.4a warns about. *If OQ-1 resolves in favour of rank 1, this
question disappears. If not, D5 must carry it as a named falsification risk.*

**OQ-7 — whether 34 cycles × 24 underlyings clears gate 2 and gate 6.** D1 fixes the data
shape, not the trade count. **Note (rev 2):** the monthlies-only choice is a disclosed deviation
from map §1.1, which also specifies a weekly per cycle; §4.1 quantifies what that costs gate 2
and gate 6, and widening to weeklies is the first lever if this question resolves short. At one structure per (underlying, cycle) the ceiling is
24 × 34 = 816 candidate entries before any regime filter, liquidity filter or event filter
removes any. Gate 2 needs ≥30 OOS trades and gate 6 needs ≥10 trades in **each** of
bull/bear/range (`config/research.py:99,112-113`). *That arithmetic is D4's to re-run on the
actual coverage summary (map §7, D4), and it is the single most likely reason this dataset
shape has to widen.*

**OQ-8 — Postgres.** `DATABASE_URL` may point at Postgres (`config/settings.py:45-47`). The
`String(16)` overflow (D12) is silent on SQLite and is not on Postgres. If any environment
uses Postgres, D12 is a bug today, not a tidiness item.

---

## 14. Code touchpoints

Every file D1 implies a change to, with the anchor line.

| File | Line(s) | Change |
|---|---|---|
| `src/signalforge/data/options_backfill.py` | `:77-89` | `_reference_price` → `reference_price(session, underlying, as_of_date)`, source-pinned, staleness-bounded (§2.2) |
| | `:58-75` | `BackfillCaps` → explicit window, cycle rule, DTE window, ladder, per-cycle caps (§3.2) |
| | `:99-162` | `_select_contracts` → per-cycle, unfiltered single-expiry reference call + client-side ladder (§3.3-3.4) |
| | `:205` | remove the `today() - lookback_days` clamp (D1) |
| | `:317,325-327` | narrow the per-contract fetch range to the cycle trade window (§3.5, D10) |
| | `:214-232,406-418` | per-(underlying, cycle) `gaps_json`; run parameters recorded structurally (§8.2) |
| `src/signalforge/data/adapters/massive_options.py` | `:100-140` | spacing + backoff + retry, kill-switch-responsive (§7.6, D4). The kill-latency bound is `max(0.1 s, 0.2 s, _TIMEOUT)` = **20 s**, not 0.1 s; tightening it is a change to `_TIMEOUT` (`:34`) plus in-flight cancellation, not a property the code has (§7.6) |
| | `:152-180` | allow an unfiltered single-expiry contracts call (§3.4); **add the vendor's expired-contracts parameter (D13)**; **add the vendor's `as_of` point-in-time parameter (D14)**; pass `limit=1000` explicitly (default is 250, F43) |
| | `:142-150` | `_paginate` must report `pages_walked` and whether `next_url` was exhausted or `_MAX_PAGES` was hit; `fetch_contracts` must count rows it skipped as unparseable (`:186-187`) — both feed the `ladder_incomplete` exclusion (§3.4) |
| `src/signalforge/options/blackscholes.py` | `:92-123` | **No behaviour change is required**, but the caller-side guard of §5.2 must exist somewhere: either re-price at the returned sigma and check `vega` in the backfill/engine caller, **or** change `implied_vol` to return a status alongside sigma. Rev 1 omitted this file from the touchpoint table while depending on a taxonomy the function cannot produce; if the second option is taken, the four payoff simulators in `options/simulators.py` are its blast radius |
| `src/signalforge/data/options_ingest.py` | whole file | write an `IngestionRun` (D6) |
| `src/signalforge/config/settings.py` | `:56-62` | add `options_min_request_spacing_s` (§7.6) |
| `src/signalforge/config/research.py` | `:192-216` | `OptionsConfig` → window/cycle/ladder/`max_total_bars=2_000_000`; new `OptionsEvaluationConfig` + `options_config_hash` (§5.5) |
| | `:392-409` | **do not touch** `SCOPE_HASH_FIELDS` (D11). *(rev 2: rev 1 cited `:345-362`, which is an unrelated block of `ResearchConfig` field declarations — an implementer following it would have been pointed at the wrong code.)* |
| `src/signalforge/db/models/market.py` | `:367-369` | widen `IngestionRun.kind` (D12) |
| `src/signalforge/db/models/research.py` | `:235-250` | add `DataSnapshot.options_scope_json`, **nullable JSON, ADD COLUMN only**; `__table_args__ = (UniqueConstraint("key"),)` at `:235` is **not** modified (§9.2, §9.2a, D15) |
| *(new alembic revision)* | — | the `ADD COLUMN` migration of §9.2a; run with the probation worker stopped and the DB file copied first; the copy is the rollback (D15) |
| `src/signalforge/research/promotion.py` | `:573-631` | `get_or_create_dataset_snapshot` takes an `options_scope`; the **keyed** branch (`:605-622`) refuses on a difference including NULL-vs-present, **and the unkeyed symbol-match fallback (`:624-631`) must refuse rather than match** when an `options_scope` is supplied (§9.2). *(rev 2: rev 1's `:573-622` stopped one line short of the branch that would have collapsed the options ledger onto the equity one.)* |
| `src/signalforge/cli.py` | `:341-427` | `--since/--until` reach the window unclamped; short write scopes with real `commit()`s; `IngestionRun` committed before the first network call; `KillSwitchEngaged` caught at the loop boundary; the `validate_option_aggregates(persist=True)` artefact included in any merge (§7.7, D9, D16) |
| `pyproject.toml` | `:210-220` | **S11 unchanged** — the backfill returns a summary, `research/` writes the scope (§9.3) |

Nothing under `src/` or `tests/` was changed to produce this document.

---

## Appendix — Judge responses (rev 2, 2026-09-11)

Two adversarial verification passes reviewed rev 1 of this document under a
legitimacy/evidence lens and a safety/feasibility lens. **Twenty distinct defects were raised.
Every one was re-verified independently against the source tree and the live DB (read-only
`SELECT`s; no files under `src/` or `tests/` changed; no provider API called; no package
installed). All twenty were confirmed and all twenty are fixed. Nothing was rejected as wrong.**
Two were accepted with a narrowed scope, noted below.

Where a judge's own arithmetic and mine differ in detail, the figure recorded in this document
is the one I recomputed here, and the difference is stated.

| # | Defect | Verified? | Fix, and where |
|---|---|---|---|
| 1 | **Lookahead in the strike ladder.** The ladder for an expired series is its end-of-life ladder, including strikes listed after the entry date, and exchanges list in the direction the underlying has moved | **Confirmed.** `massive_options.py:152-180` sends no `as_of` (F40); `market.py:240-258` has no listing date (F41) | New **§3.3a** + blocker **D14** + **OQ-10**: point-in-time call, else a first-bar proxy, else the ladder may not be used for selection; `strike_listing_basis` enters `options_scope_json`; exclusion reason `strike_not_listed_as_of_entry` |
| 2 | **The 99-hour plan may return zero rows for 33 of 34 cycles** — no expired-contracts flag is sent | **Confirmed.** No such parameter in the query builder (F40); all 888 stored contracts were unexpired at fetch (F42) | New **§7.0** + blocker **D13** + **OQ-9**, ranked first. §7's figures are stated as **void** until a one-request probe returns rows |
| 3 | **§3.5 and §7 contradicted each other on the fetch span; every §7 bar figure ~11.6% low** | **Confirmed by recomputation** (XNYS, 34 cycles): DTE-60→expiry 40–45, mean **43.09**; with the specified 5-session buffer 45–50, mean **48.09** | §3.5 now tabulates both and states the correction; §7.1/7.2/7.3/7.4 all use **48.1**. Ceiling headroom restated |
| 4 | **`LADDER_17` is not spot-invariant; §7.2 was computed at the window's highest prices** | **Confirmed by recomputation** at every cycle's own entry-date close. At $1.00: 762–794/cycle, **73 of 816** pairs below the 7-rung floor, bracket fraction **0.911** vs a pre-registered 0.90; XLRE 0.26, XLU 0.29, XLF 0.65, XLE 0.82, XLB 0.85 | §3.3's spot-invariance bullet **deleted** and replaced with the three-increment table; §7.2 rewritten as a range; the permitted responses to a shortfall are pre-registered (`LADDER_SHORTFALL_RESPONSE`, §12) |
| 5 | **Gate weakening in disguise: DTE 20 justified by easing gate 6; the map's weekly dropped silently** | **Confirmed.** Map line 218 reads "21-60 DTE"; `min_trades_per_regime = 10` at `config/research.py:113` | §4.1 **adopts 21-60 verbatim** and withdraws both the gate-6 rationale and the "wider, safer floor" claim; the weekly omission is disclosed as a deviation with its cost to gate 2 (`research.py:99`) and gate 6 quantified, and tied to OQ-7 |
| 6 | **Gate 4b (dual-spread) absent from D1, so two spread settings hash to one snapshot** | **Confirmed** by grep: `4b` and `dual-spread` appeared nowhere in rev 1 | New **§9.2b**; `spread_multipliers` and `multiplier_this_evaluation` added to `options_scope_json`; `SPREAD_MULTIPLIERS = (1.0, 2.0)` pre-registered in §12 |
| 7 | **F29 was wrong about `DataSnapshot` identity, and §9.2 as written would have destroyed the existing equity protection** | **Confirmed.** `research.py:235` is `UniqueConstraint("key")` alone | F29 rewritten; §9.2's identity rule rewritten as a **procedural** refusal; `UniqueConstraint("key")` explicitly not altered; the NOT-NULL-sentinel requirement recorded for any future constraint |
| 8 | **The unkeyed snapshot fallback defeats §9.2 and collapses the options ledger onto the equity one** | **Confirmed.** `promotion.py:624-631` matches on symbols only; `data_snapshot` id 3 `universe_24_ex_meta` is reusable and holds exactly the 24 symbols; ids 6/8/10 were minted by that branch | §9.1 now states the second path; §9.2 rule 3 requires the fallback to refuse **and** the options path to pass an explicit key; §14 touchpoint corrected to `:573-631` |
| 9 | **`non_convergent` can never fire, and low-vega garbage IV gets fill authority** | **Confirmed.** `blackscholes.py:123` returns `0.5*(lo+hi)` after `max_iter`; `None` only at `:106-111` | F26 corrected; §5.2 rewritten with a taxonomy defined against `lo_bound`/`hi_bound` and a mandatory re-price; **`IV_MAX_PRICE_RESIDUAL` and `IV_MIN_VEGA` pre-registered in §12 now, before any IV exists**; `blackscholes.py` added to §14 |
| 10 | **The rank-1 fill and the entry decision are not time-aligned, and no conservatism argument was made** | **Confirmed.** The option close is a last-trade print of unknown intraday time; the equity engine fills at the next bar's open (`backtest/engine.py:109`) | New **§5.4**: the bias is named and left unquantified; D2 must adopt either an E+1 fill or an explicit timing penalty; `print_time_known = false` becomes a gate-0.f disclosure field and enters `options_scope_json` |
| 11 | **§10.2's sealing of `volume`/`transactions` was ambiguous against map §2.4(3)** | **Confirmed as an ambiguity** (accepted as a clarification rather than a factual error) | §10.2 split into never-inspect / pre-registered-programmatic-use-only, with any threshold a §12 constant and an `options_scope_json` field |
| 12 | **§7.4's "the ceiling requires the ladder" rests on an extrapolation that favours the chosen design** | **Confirmed.** SPY's $1.00 ladder is FACT only over 709.0–831.0 (≈±8%), and F38 makes the band filter server-side | §7.4's figures relabelled **HYPOTHESIS** line by line, restated at 48.09 (≈4.62M bars), with a commitment to recompute from Stage A's unfiltered ladders and an explicit bar on using that recomputation to loosen any constant |
| 13 | **Minor factual and citation slips** — (a) F28's `SCOPE_HASH_FIELDS` citation, (b) F24's two denominators, (c) §12 "binding for D5" | **All three confirmed.** (a) the tuple is at `config/research.py:392-409`; (b) `ohlcv_daily` stood at **1,686,930** rows with **zero** NULLs and **zero** violations, so neither denominator was "all rows"; (c) map §7 assigns these to D5 | (a) fixed in F28 and §14; (b) F24 restated as "rows violating the condition: 0, as of 2026-09-11, table then at N rows"; (c) §12's preamble reworded to "proposed to D5, restated verbatim there, any difference a disclosed deviation with D5's value governing" |
| 14 | **The run is not resumable on the failure path a 99-hour run will actually take** | **Confirmed.** Seven `flush()` sites and **no `commit()`** in `options_backfill.py`; `KillSwitchEngaged` is a `RuntimeError` not caught by the `except AdapterError` handlers (F44) | §8.1 corrected; §7.7 fix 1 expanded to four parts (commit per checkpoint, `IngestionRun` committed before the first network call, `KillSwitchEngaged` caught at the loop boundary, fetch outside any transaction); new blocker **D16** |
| 15 | **No migration plan for a schema change to the parent of the sealed-look ledger, on a live probation DB** | **Confirmed.** `strategy_sealed_test` FK is ON DELETE CASCADE over 22 live rows; `render_as_batch=_is_sqlite()` and `PRAGMA foreign_keys=ON` (F46) | New **§9.2a** + blocker **D15**: ADD COLUMN only, constraint untouched, worker stopped and file copied first, the copy is the rollback |
| 16 | **The kill-switch responsiveness claim is false and its citations do not exist** | **Confirmed.** Pacing chunks at 0.1 s (`massive.py:160-166`), backoff at 0.2 s (`:144-149`), and `_TIMEOUT = 20.0` with one kill check per `_get` | §7.6 restates the bound as **20 s** with correct citations; F45 added; §14 records that tightening it is a change to `_TIMEOUT` plus in-flight cancellation |
| 17 | **The API budget rests on an unverified page count fed by a paginator that truncates and drops rows silently** | **Confirmed.** `_MAX_PAGES = 20` with no signal, `limit` defaults to **250** not 1000, unparseable rows silently skipped (F43) | §3.4 rewritten: `limit=1000` explicit, pagination and parse accounting required, new exclusion reason `ladder_incomplete`; the 2-page figure relabelled **HYPOTHESIS**; §7.2's request total labelled a **no-retry lower bound** |
| 18 | **§7.7 fix 2 under-specified in three ways** | **Confirmed.** The bulk run needs `instrument`/`ohlcv_daily`; `IngestionRun` ids are integer PKs that collide; `cli.py:~418` writes a validation row inside the same scope | §7.7 fix 2 now names the bulk DB's source (a file copy taken with the worker stopped, timestamp recorded, never refreshed mid-run), specifies the `IngestionRun` id remap, and includes the validation artefact; the merge runs with the worker stopped |
| 19 | **Stale FACT citations make the labelling rule non-load-bearing** (same ground as 13(a)/(b), raised independently) | **Confirmed** | Fixed as at 13; §14's "do not touch" anchor corrected so it points at the real code |
| 20 | **"All 25 probed endpoints"** in §6.1 and OQ-1 | **Confirmed wrong:** `entitlement_check` holds **21** distinct endpoints | F47 added; §6.1 and OQ-1 corrected. The conclusion — `/v3/reference/dividends` and `/v3/reference/splits` were never probed — is unchanged and re-verified |

### Accepted with a narrowed scope (2)

- **#11 (volume sealing)** is accepted as a **clarification**, not a factual error: rev 1's rule
  was sound for inspection and merely silent on pre-registered programmatic use. The rewrite is
  strictly tightening in both readings, so it costs nothing to adopt.
- **#12 (§7.4)** is accepted in full as to labelling and the recomputation commitment. The judge
  also suggested the full-band multiple "narrows sharply" if the wings widen to $5. That is
  plausible and is now stated as such — but it is **not** asserted as a finding here, because
  nothing in the DB establishes it either (F48 cuts both ways), and the 48.09-session correction
  pushes the counterfactual the other way (2.07× → 2.31×). The honest position is that the
  comparison is unresolved until Stage A, which is what §7.4 now says.

### Nothing was rejected

Every defect raised was independently reproducible against the repo or the live DB. Three claims
in the judges' *strengths* lists were also re-verified and are retained unchanged: the 716-day
gate-0 floor (first passing span = 716, recomputed), the split-adjustment hazard of §2.3 (0
corporate-action rows, 0 violating `ohlcv_daily` rows, `massive.py:225-228` returns `()`), and
the S11 direction argument of §9.3 (`pyproject.toml:209-219`).

### What this revision did NOT change

The structure, the section numbering (one insertion each at §3.3a, §5.4, §7.0, §9.2a, §9.2b),
the decisions it inherits, and the direction of every gate. No pre-registered constant was
loosened. Four were added (`IV_MAX_PRICE_RESIDUAL`, `IV_MIN_VEGA`, `SPREAD_MULTIPLIERS`,
`STRIKE_LISTING_BASIS`) and two rules were pre-registered that did not previously exist
(`LADDER_SHORTFALL_RESPONSE`, `VOLUME_INSPECTION`) — all of them strictly more searching, which
R4 permits. One constant moved **toward** the map: `DTE_ENTRY_MIN` 20 → 21.

Nothing under `src/` or `tests/` was changed to produce this revision.
