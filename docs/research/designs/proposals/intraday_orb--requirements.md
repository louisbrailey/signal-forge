# Proposal — `intraday_orb.intraday` v0.1.0 (version 1): data & policy REQUIREMENTS

**Angle:** data and policy requirements. **This is not a promotion attempt and it
proposes no strategy change.** `research/strategies/intraday_orb.py` is untouched;
`VERSION` stays `"0.1.0"`; no `v0.2.0` is created here (§4.1 of
`STRATEGY_COMPLETION_MAP.md` assigns this strategy 1 requirements-only proposal).

**Conformance:** written to `STRATEGY_COMPLETION_MAP.md` §4.2 (all eleven sections
below, in order), under §1 rules R1–R10 and `STRATEGY_COMPLETION_PLAN.md`'s seven
rules of engagement. Every claim is labelled **FACT** (with `file:line`, a read-only
`SELECT`, or a reproducible in-process computation), **DERIVED** (arithmetic on
stated inputs), or **HYPOTHESIS**.

**Sealed-window discipline:** *nothing in this document is derived from the sealed
window.* Every computed number below is either code arithmetic, a read-only query,
or a computation over the **pre-sealed** proxy span `2016-10-17 … 2025-09-07`. The
sealed window is referenced only twice, both for *disposition* (permitted under R1):
in §10 (the look ledger) and §11 (the null option).

**Work performed to produce this document:** read-only. No file under `src/` or
`tests/` was modified, no database write was issued, no provider API was called, no
package installed, no service restarted. In-process calls were limited to
`PriceSeries.load`, `backtest/regime.label_regimes`, `research/regime.regime_lookup`,
`research/backtest_runner.run_strategy_over_universe` (verified `session.add`-free,
per §4.0 W2), `backtest/engine.run_backtest` on synthetic arrays, and
`backtest/leakage.assert_no_lookahead` on synthetic arrays.

---

## 0. Executive summary (the four findings that decide this)

1. **FACT — the data-latency entitlement equals the bar size, so live intraday
   operation cannot reproduce the modelled fill.** Intraday 5-minute aggregates are
   entitled but `DELAYED` (≥15 min) — `data/entitlements.py:250-257` probes feed
   `stocks_intraday_aggs_5m` with `latency="DELAYED"`;
   `docs/CAPABILITY_MATRIX.md:26` and `reports/SUBSCRIPTION_STATUS.md:19` record the
   measured result. The configured research bar size is **15 m**
   (`config/research.py:303 intraday_bar_size = "15m"`). The engine enters at the
   **next bar's open** (`backtest/engine.py:108-109`). With a ≥15-minute feed delay
   and 15-minute bars, the signal bar's close is not visible until the modelled entry
   bar has already completed. The backtest fill is unattainable live on this plan,
   and `LatencyCategory.REALTIME` is never set anywhere in the codebase
   (`docs/CAPABILITY_MATRIX.md`, "Real-time anything → unsupported"). **The EOD-only
   policy is therefore not merely a policy; it is currently also an entitlement fact.**
2. **FACT — the frozen cost model charges this strategy 4–10× what it charges any
   daily strategy, per trade, in R.** Its risk unit is the opening-range width, not
   an ATR multiple. At the unchanged 11.0 bps round trip (`engine.py:94, 144`) and an
   OR width of 0.3–0.8 % of price, cost is **0.14R – 0.37R per round trip** (§8) —
   against `volatility_breakout`'s 0.042R, the most expensive strategy in the program
   today (`STRATEGY_COMPLETION_MAP.md` §0.4). Gate 3, not gate 4, becomes the binding
   gate — a reversal of the pattern for every other strategy.
3. **FACT — the promotion path is intraday-incapable in at least five places beyond
   gate 0, and one of them makes gate 6 fail unconditionally.** Gate 6 looks trades up
   in a `dict[date, str]` using `t.entry_date`, which for an intraday run is a
   `datetime` (`promotion.py:744`; `backtest/regime.py:25`; verified: a `datetime`
   key never matches a `date` key). Every intraday trade would land in the "warmup"
   hole → buckets `0/0/0`, 100 % unbucketed, gate 6 fails whatever the data says.
   Converting gate 0 alone (the R4-permissible change) is therefore **necessary but
   must not ship alone** (§2).
4. **FACT — gate 6's bear bucket sets a hard nine-year floor on how much intraday
   history must be bought.** The strategy's inherited regime gate
   (`not ctx.regime.risk_off`, `intraday_orb.py:105`) is shut on **93 % of
   bear-labelled sessions**: over the full pre-sealed span only **19 of 267**
   bear-labelled proxy sessions are tradeable (7.12 % ± 1.57 %), and **zero** of them
   fall after 2023-06-02. A pre-sealed span starting on or after 2022-09-08 has **0**
   tradeable bear sessions and gate 6 is arithmetically unreachable (§3). This is the
   same mechanism `v6_regime_power.md` established for `volatility_breakout`, and my
   recomputation reproduces that diagnostic's 267 / 11.95 % figures exactly.

**Recommendation: do not build the pipeline. Take the null option (§11) unless the
operator answers Q1 (§ Operator questions) with a decision to acquire a real-time
equities entitlement.** The requirements below are specified in full so that the
decision is made on costed facts rather than on the absence of a plan.

---

## 1. Mechanism

The hypothesis under test here is not a market hypothesis about opening-range
breakouts — this proposal changes no rule and forecasts no edge. It is a
**capability hypothesis**, stated in the §2 form the map requires so it can be
killed:

> **H13 (new).** `intraday_orb.intraday` is blocked by three *independent* layers
> (`STRATEGY_COMPLETION_MAP.md` §2.4: promotion-path gate, EOD-only operating policy,
> absent data path). H13 asserts that **removing all three is neither sufficient nor
> economically sensible**, because two further layers — provider *latency* and the
> frozen *cost model* — independently prevent an honest, operable pass, and both are
> quantifiable **today, with no intraday data at all**.

Why this should be true in markets, not just in the backtest: an opening-range
breakout is a *microstructure* strategy. Its edge, if any, lives in the first hour,
when the effective spread and adverse selection are at their daily maximum, and its
risk unit is the opening range — a few tens of basis points — rather than a
multi-percent ATR stop. Both facts push in the same direction: the ratio of
transaction cost to risk unit is an order of magnitude worse than for a swing
strategy, and the sensitivity of the realised fill to execution latency is an order
of magnitude higher. A strategy of this shape is only viable with (a) real-time
data, (b) a measured spread, and (c) a cost model calibrated to the opening auction.
This program has none of the three: real time is unentitled, NBBO quotes return
`403 not_authorized` (`docs/CAPABILITY_MATRIX.md`; `universe/screen.py` flags every
symbol `F_SPREAD = "spread_filter_not_licensed"`), and R4 freezes the cost model at a
universe-independent flat 5.0 bps assumed spread (`engine.py:90`,
`backtest_runner.py:205-206` never overrides it).

Relation to the existing hypothesis set: H13 does not use H1–H4 (v3, demoted by
`v3_duration_exits.md` and `v3_atr_at_exit.md`), H6/H8/H9 (v4), or H11. It **inherits
H12's replacement mechanism** from `v6_regime_power.md` — a regime gate that is shut
on almost every bear session, producing a breadth/availability failure at gate 6 with
a hard calendar ceiling — and shows in §3 that `intraday_orb` sits behind *the same
gate expression* (`not ctx.regime.risk_off`) as `breakout.py:102`.

---

## 2. Exact change — file, symbol, before → after

### 2.1 What this proposal does **not** change

- `src/signalforge/research/strategies/intraday_orb.py` — **unchanged**. `VERSION`
  stays `"0.1.0"`; `ORBParams` (`:29-35`) unchanged; `IntradayORB.evaluate`
  (`:88-127`) unchanged. No `v0.2.0` row is created (R3/R7 are satisfied vacuously).
- `research/strategies/__init__.py:43-51` `default_strategies()` — unchanged (6
  entries; `IntradayORB` already registered).
- Any threshold in `config/research.py:93-123` or `backtest/costs.py:11-16` —
  unchanged (R4).
- **R7 safety check (FACT):** nothing here touches any `StrategySpec`, so
  `approval_scope.current_spec_json_hash()` for the two live PAPER_APPROVED versions
  (v2 `trend_continuation.short_swing`, v5 `relative_strength.medium_swing`) cannot
  move, and no new passing evaluation is created, so the `scopes[0]` ordering hazard
  (R7b) is not activated.

### 2.2 The R4-permissible change: gate 0 becomes a real data query

**File:** `src/signalforge/research/promotion.py`. **Symbol:** `evaluate_promotion`,
the `Horizon.INTRADAY` early-return block.

**Before (FACT, `promotion.py:512-534`, verbatim structure):**

```python
if spec.horizon is Horizon.INTRADAY:
    gates.append(
        Gate(
            0,
            "data_availability",
            False,
            "no intraday bar history is ingested for this horizon — evaluation not attempted "
            "(not a fabricated pass on absent data)",
        )
    )
    return _finalize(session, strategy, version, config, symbols, start, end,
                     gates, None, {}, dataset_snapshot.id)
```

**After (specification, NOT applied — no `src/` file was modified):** replace the
declared-horizon test with a coverage query against `OHLCVIntraday`, and then **fall
through to the same `MIN_PRESEALED_DAYS` check the daily path already applies**
(`promotion.py:559-583`), which the current early return skips entirely.

```
gate 0 (INTRADAY) passes only if ALL of:
  a. for every symbol in `symbols`, OHLCVIntraday rows exist with
       bar_size == config.intraday_bar_size, source == the run's SourceFilter,
       is_simulated is False, session == "rth",
       bar_start within [start, end];
  b. per-symbol session coverage >= 95% of the daily sessions the same symbol
     has in OHLCVDaily over the same span and source (catches partial backfills);
  c. per-session bar count == the expected RTH count for that bar size
     (26 for "15m", 78 for "5m"), for >= 99% of covered sessions
     (catches half-days silently ingested as full ones, and pre/post contamination);
  d. the latest ingested bar_start is not staler than the daily feed's own
     freshness bound used by approved_scope_scan.data_readiness;
  e. the existing pre-sealed-span length test then runs unchanged
     ((pre_sealed_end - start).days >= MIN_PRESEALED_DAYS == 350).
Otherwise: Gate(0, "data_availability", False, <which of a-e failed, per symbol>).
```

**Why this is R4-permissible and not a weakening (the §1 carve-out 2 argument, made
symmetric):** the current test is a hard-coded fail; any real query is *at least as
hard* to satisfy, because it fails for as long as no intraday data exists and then
keeps failing on partial, mis-sized, simulated, wrong-source or stale data. Nothing
in the ladder becomes easier to pass. Conditions (b)–(d) are additions that the
hard-coded fail never enforced.

### 2.3 The mandatory bundle — gate 0 must NOT ship alone

**FACT:** after the §2.2 change, execution falls through to
`full = run_strategy_over_universe(session, strategy, symbols, start, pre_sealed_end, …)`
at `promotion.py:586`, which **does not pass `intraday=` or `bar_size=`**. Those
parameters default to `intraday=False, bar_size="15m"` (`backtest_runner.py:179-180`),
so the whole ladder would evaluate an INTRADAY strategy on **daily** bars. The same
omission exists at `promotion.py:386` (gate 9's sealed run) and inside
`research/sensitivity.py:148` (gate 5's nine grid re-runs).

**FACT (verified in-process, read-only):** running `IntradayORB()` over the 24
snapshot-3 symbols on **daily** `massive` bars for `2016-10-17 … 2025-09-07` yields
`n_trades = 0` over 53,196 bars. Mechanism: `features/intraday.py:19-21`
`_session_date` returns each daily bar's own date, so `bars_since_open` (`:24-32`) is
always `0` and `opening_range` (`:35-45`) never accumulates `k_bars=3` bars in one
"session", returning `(nan, nan)`; `evaluate` exits at `intraday_orb.py:91-92`.

So the failure mode of shipping §2.2 alone is **misleading, not unsafe**: gate 0
would report data availability, then gates 1–7 would report zero-trade failures that
read as strategy defects rather than as a plumbing bug. It cannot fabricate a pass.
That is still unacceptable for an auditable ladder. Bundle items, each with the
file:line that must change:

| # | File / symbol | Defect today (FACT) | Required |
|---|---|---|---|
| B1 | `promotion.py:586`, `:386`; `research/sensitivity.py:148` | `run_strategy_over_universe` called without `intraday=`/`bar_size=` | thread `intraday = spec.horizon is Horizon.INTRADAY` and `bar_size = config.intraday_bar_size` through gates 1–5 and gate 9 |
| B2 | `promotion.py:744` `regimes.get(t.entry_date, "warmup")`; keys from `backtest/regime.py:25` `dict[date, str]` | for intraday runs `t.entry_date` is a `datetime` (`engine.py:134` ← `series.dates[entry_idx]`); a `datetime` key never matches a `date` key (verified) → buckets `0/0/0`, 100 % unbucketed, **gate 6 fails unconditionally** | normalise with the module's own `_as_date` helper (`backtest_runner.py:163-164`) before the lookup |
| B3 | `data/validate.py` — only `validate_daily` (`:66`) and `validate_option_aggregates` (`:249`) exist | gate 8 (`promotion.py:808`) validates **daily** bars for an intraday strategy: a PASS that says nothing about the data actually traded | a `validate_intraday` counterpart (session completeness, bar-count-per-session, duplicate `bar_start`, non-positive prices, `source`/`bar_size` purity) wired into gate 8 when the horizon is INTRADAY |
| B4 | `promotion.py:249-267` `_leakage_self_check` checks `sma/rolling_return/atr/realized_vol` on the **daily** proxy only | the intraday feature set is never leakage-checked in the ladder | add `opening_range`, `bars_since_open`, `session_bar_count` to the check on the intraday series when the horizon is INTRADAY (§7 shows they pass today) |
| B5 | `promotion.py:161-210` `_sensitivity_plan` has no `intraday_orb` branch | gate 5 hard-fails (`promotion.py:694-703`) — an automatic permanent failure, not a skip | register the pre-registered grid in §6 (R4 carve-out 1) |
| B6 | `features/intraday.py:35-45` `opening_range` is `O(t)` per bar; `series.head(t)` (`series.py:40-51`) copies the `dates` tuple, also `O(t)` | the backtest is `O(n²)` per symbol — measured (§3.4): one full-span pass over 24 symbols at 15 m takes **32 min**, one complete 10-gate evaluation **≈5.4 h** (at 5 m, **≈48.5 h**) | cache the per-session index (or precompute session boundaries once per series) before any intraday evaluation is attempted |

Two further defects are **reporting**, not gate, problems, and are listed for
disclosure rather than as blockers: `research/portfolio_metrics.py:97` sums
`bars_held` into `exposure_days` (15-minute bars counted as days; `:119` clamps
`exposure` at 1.0, so gate 7's evidence blob would report 100 % exposure for a
strategy that is flat overnight), and `_resolve_exit` (`engine.py:152-184`) has no
session-boundary awareness — see the ORB leash defect in §5.

### 2.4 Data-pipeline requirements (the part that costs money and time)

| Item | Requirement | Evidence / basis |
|---|---|---|
| Adapter | a real `MassiveAdapter.fetch_intraday_bars` satisfying `IntradayBarAdapter` (`adapters/base.py:138-149`), declaring an `AdapterCapability(feed_type=FeedType.BAR_INTRADAY, latency_category=DELAYED, rate_limit_per_min=5)` | FACT: `massive.py:86-100` declares **only** `BAR_DAILY`; the only `BAR_INTRADAY` capability in the repo is the test fixture (`adapters/fixture/__init__.py:79`) |
| Endpoint | `/v2/aggs/ticker/{sym}/range/15/minute/{from}/{to}?adjusted=true&sort=asc&limit=50000` | FACT: the daily path uses the same family at `massive.py:178`; the entitlement probe uses `/range/5/minute/` (`entitlements.py:252-254`) |
| Pagination | the daily adapter **rejects** any response carrying `next_url` (`massive.py:186`). An intraday adapter must chunk by calendar instead | FACT |
| Bar size | **15 m**, not 5 m | FACT: `config/research.py:303`; `backtest_runner.py:180` default; and the strategy's own guard `session_bar_count + time_stop_bars > 26 + or_bars` (`intraday_orb.py:97`) is written against a **26-bar** session = 390 RTH minutes ÷ 15 |
| Session filter | ingest **RTH only** (`session="rth"`) | FACT: `PriceSeries.load_intraday` (`series.py:118-134`) filters on `bar_size` and `source` but **not** on `session`, so any pre/post rows enter the series; `_session_date` (`features/intraday.py:19-21`) then groups by **UTC** calendar date, so (i) a 04:00 ET pre-market bar becomes the "opening range", and (ii) under EST a post-market bar starting ≥19:00 ET falls on the *next* UTC date and corrupts that session's opening range |
| Ingest entry point | `ingest_intraday_symbol` / `ingest_intraday_universe` (`ingest.py:455-489`, `:527-542`) and `signalforge data ingest-intraday` (`cli.py:622-659`) already exist and write `OHLCVIntraday` | FACT — no new ingest code is needed |
| Snapshot key | a **new, explicit** key, e.g. `universe_24_ex_meta_intraday_15m` | FACT: `DataSnapshot` (`db/models/research.py:224-249`) has **no bar-size or horizon column**, and an unkeyed call matches any reusable snapshot on an exact symbol-set match (`promotion.py:331-337`) — an unkeyed intraday run on the 24 ex-META symbols would silently attach to **snapshot id 3**, the daily-bar snapshot the two live approvals sit on. A distinct key with the same symbol set is accepted (the key branch, `promotion.py:309-329`, requires the symbol sets to *match*). Verify the key against both auto-generators (`universe_auto_*`, `promotion.py:339`; `liquid_us_<date>_<digest>`, `screen.py:259`) |
| Concurrency | schedule the backfill in a maintenance window with the worker stopped | a live paper probation and a background worker run against `data/signalforge.sqlite`; a 0.8–1.6 M-row insert (§3.3) inside a sticky write-intent session is exactly the contention the project's SQLite rules exist to avoid |

---

## 3. Pre-sealed evidence, with standard errors

All computations below use **only** pre-sealed data (`2016-10-17 … 2025-09-07`,
source `massive`) or pure code arithmetic. §0.3 of the map supplies no per-trade `sd`
for version 1 (it has never been evaluated past gate 0), so where a per-trade `sd`
is needed I state the result **as a function of `sd`** over the program's observed
range 0.807–1.741 rather than inventing one. Proportions carry binomial SEs;
a difference under 2 SE is not treated as evidence.

### 3.1 The regime gate is shut on 93 % of bear sessions (decisive for gate 6)

Computed in-process: `label_regimes(SPY)` (gate 6's labeller, `backtest/regime.py`)
crossed with `regime_lookup(SPY).risk_off` (the strategy's own gate,
`research/regime.py:41-42`), pre-sealed span, source `massive`.

| gate-6 bucket | labelled sessions | tradeable (`not risk_off`) | share ± SE |
|---|---|---|---|
| bull | 1,392 | 1,024 | 73.56 % ± 1.18 % |
| **bear** | **267** | **19** | **7.12 % ± 1.57 %** |
| range | 375 | 116 | 30.93 % ± 2.39 % |
| warmup (unbucketable, §0.6) | 200 | 178 | 89.00 % ± 2.21 % |

FACT — cross-check: 267 bear-labelled sessions and 267/2,234 = 11.95 % reproduce
`v6_regime_power.md` exactly, on an independently written computation. Bear sessions
are 13.13 % ± 0.75 % of the 2,034 **labelled** pre-sealed sessions.

FACT — where the 19 tradeable bear sessions sit: **3** in Oct–Nov 2020 and **16** in
Feb–Jun 2023. None after 2023-06-02.

### 3.2 History depth is forced by gate 6, not by gate 0

Tradeable (`not risk_off`) sessions by gate-6 bucket, as a function of the pre-sealed
start date. `label_regimes` labels the first `TREND_LOOKBACK = 200` sessions
`"warmup"` (`backtest/regime.py:20, 36-37`), so a later start swallows real regime
sessions into the warmup hole.

| pre-sealed start | sessions | bull | **bear** | range | warmup |
|---|---|---|---|---|---|
| 2016-10-17 (parity with the daily program) | 2,234 | 1,024 | **19** | 116 | 178 |
| 2018-09-10 | 1,757 | 822 | **19** | 71 | 161 |
| 2019-09-09 | 1,507 | 707 | **19** | 65 | 95 |
| 2020-09-08 | 1,255 | 493 | **16** | 65 | 200 |
| 2021-09-08 | 1,003 | 400 | **16** | 62 | 94 |
| 2022-09-08 | 751 | 348 | **0** | 31 | 200 |
| 2023-09-08 | 500 | 139 | **0** | 4 | 177 |
| 2024-09-22 (the shortest gate-0-legal span) | 239 | 39 | **0** | 0 | 108 |

DERIVED, and this is the single hardest requirement in the document:

- The **shortest span gate 0 will accept** is 716 calendar days
  (`sealed_start = end − 365`; `pre_sealed_end = sealed_start − 1`;
  `(pre_sealed_end − start).days ≥ MIN_PRESEALED_DAYS = ceil(200×365.25/252)+60 =
  350` — `promotion.py:90-94, :554-559`). For `end = 2026-09-08` that is
  `start ≤ 2024-09-22`. At that start, **39 of 239 pre-sealed sessions are labelled
  and every one is `bull_lowvol`**: bear = 0 and range = 0, so gate 6
  (`≥ 10 trades in each of 3 buckets`, `config/research.py:109-110`) is
  **arithmetically unreachable** no matter how good the strategy is.
- Any start on or after **2022-09-08** yields **0** tradeable bear sessions.
- A start of **2021-09-08** recovers the 16 Feb–Jun 2023 bear sessions; a start of
  **2019-09-09** or earlier recovers all 19.

**So the intraday backfill must reach back to at least 2021-09, and to 2016-10 for
parity with the daily program. "Two years of intraday bars" is not a viable option.**

### 3.3 Data volume, API budget and storage

DERIVED. Symbols = the 24 of snapshot 3 (`universe_24_ex_meta`, the only universe on
which gate 8 passes — §0.1); RTH bars/session = 26 at 15 m, 78 at 5 m; extended-hours
figures (64 / 192 per day) are shown because the provider returns them unless the
window is filtered, and §2.4 requires they be dropped.

| Option | Span | Sessions/sym | 15 m RTH rows | 15 m rows if pre/post kept | 5 m RTH rows | API calls (yearly chunks × 24) | Paced wall-clock |
|---|---|---|---|---|---|---|---|
| **A** minimum legal | 2024-09-22 → 2026-09-08 | 491 | 306,384 | 754,176 | 919,152 | 48 | **9.7 min** |
| **B** bear-coverage minimum | 2021-09-08 → 2026-09-08 | 1,255 | 783,120 | 1,927,680 | 2,349,360 | 120 | **24.2 min** |
| **C** parity with the daily program | 2016-10-17 → 2026-09-08 | 2,486 | 1,551,264 | 3,818,496 | 4,653,792 | 240 | **48.4 min** |

Basis: pacing 12.1 s/request (`massive.py:39-40 _MIN_REQUEST_SPACING_S = 12.1`;
`config/settings.py:53` same default; Basic plan 5 req/min,
`reports/UNIVERSE_CAPACITY_PLAN.md` "Adapter REST throttle … rate_limit_per_min=5").
This is the same order as W1's pre-registered daily build (126 calls / ~26 min,
`w1_universe_preregistration.md`). Yearly chunking keeps every request under the
50,000-row cap even with extended hours (252 × 192 = 48,384 at 5 m).

**Storage (FACT, measured):** `ohlcv_daily` plus its five indexes occupy
355,749,888 bytes for 1,036,162 rows = **343 bytes/row** (`dbstat`, read-only).
`OHLCVIntraday` carries two extra short string columns and four indexes, so this is a
close estimate. DERIVED: option C at 15 m RTH ≈ **532 MB**, option C at 5 m RTH ≈
**1.60 GB**, option C at 15 m with pre/post kept ≈ **1.31 GB**. The whole database is
**381,739,008 bytes** today, so the recommended option roughly **2.4×** the file.
FACT: `ohlcv_intraday` currently holds **0 rows**.

### 3.4 Compute cost of one promotion evaluation

FACT (measured, synthetic in-memory series, no DB): `run_backtest` with
`signal_fn_for(IntradayORB())` on 15-minute bars is cleanly quadratic in bar count —
1,560 bars 0.06 s; 3,120 bars 0.24 s; 6,552 bars 1.03 s; 13,104 bars 4.11 s. Fit
`t ≈ 2.394 × 10⁻⁸ · n²` s/symbol (mechanism: `opening_range` rescans `range(t+1)`
each bar, `features/intraday.py:39`, and `series.head(t)` copies the `dates` tuple,
`series.py:45`).

DERIVED, 24 symbols, one complete evaluation = 1 pre-sealed pass + 9 gate-5 grid
re-runs (`sensitivity.py:148`, one per grid point) + 1 sealed pass:

| Option | bar size | bars/symbol (pre-sealed) | one pass | one full 10-gate evaluation |
|---|---|---|---|---|
| A | 15 m | 6,214 | 0.4 min | **0.07 h** |
| B | 15 m | 26,078 | 6.5 min | **1.1 h** |
| **C** | **15 m** | **58,084** | **32.3 min** | **5.4 h** |
| C | 5 m | 174,252 | 290.7 min | **48.5 h** |

Every re-evaluation, every variant and every sensitivity check pays this again.
Bundle item B6 is therefore a prerequisite, not an optimisation.

### 3.5 Entry-rate and trade-count scale (HYPOTHESIS, order of magnitude only)

FACT (code arithmetic, `intraday_orb.py:94, 97`): with `or_bars=3`,
`min_bars_before_entry=3`, `max_bars_after_open=20`, `time_stop_bars=12`, entries are
admissible only for `3 ≤ since_open ≤ 16` — a **14-bar** window in a 26-bar session.

HYPOTHESIS (synthetic geometric-random-walk 15 m series, *not* market data, stated
only to size the gates, never as evidence about expectancy): the entry rate is
**0.42 ± 0.04** trades per symbol-session (107 trades / 252 sessions; a 504-session
replicate gives 0.405 ± 0.028). DERIVED at that rate on option C: pre-sealed trades
≈ 1,337 tradeable sessions × 24 × 0.42 ≈ **13,500**, OOS ≈ **5,400**, bear-bucket
trades ≈ 19 × 24 × 0.42 ≈ **190**. **This must be replaced by a measurement on real
bars before any gate forecast is relied upon**; it is used below only to establish
which gates are and are not power-limited.

---

## 4. Falsification — stated in advance, required to hold on all four snapshots

Per R10 each condition must hold across snapshots 1–4, not just snapshot 3. Note the
structural reason most of these are snapshot-invariant: gate 6's labels and the
strategy's regime gate both derive from the **SPY proxy alone**, which is identical
in all four snapshots (the snapshots differ only in `META` / `META_CONT` / its
absence). I verified this rather than asserting it: recomputing §3.2 with snapshot
1's pre-sealed end (2025-09-06) and with snapshots 2–4's (2025-09-07) returns
**identical** counts at every start date (1,024/19/116/178 at 2016-10-17;
400/16/62/94 at 2021-09-08; 348/0/31/200 at 2022-09-08; 139/0/4/177 at 2023-09-08).

| # | Claim | What kills it (pre-sealed only, all four snapshots) |
|---|---|---|
| **F1** | A pre-sealed span starting on/after 2022-09-08 has zero tradeable bear sessions, so gate 6 is unreachable at that depth | any snapshot on which that span yields ≥ 1 session that is `bear_*` under `label_regimes` **and** `not risk_off` under `regime_lookup`. Verified false on all four today. |
| **F2** | Gate 6 returns `bull 0 / bear 0 / range 0` with 100 % unbucketed for **any** intraday run of the *current* promotion path | any intraday gate-6 evidence blob with a non-zero bucket before bundle item B2 is applied. (Type-level: `datetime` keys never match `date` keys — verified.) |
| **F3** | Cost is ≥ 0.1375R per round trip at the frozen 11.0 bps | measuring, after ingest, a **median OR width > 0.80 % of price** across the 24 symbols on the pre-sealed span — which would put cost below 0.1375R. Pre-sealed anchor: median daily `(H−L)/C` is 1.579 % (min 1.090 % DIA, max 3.663 % NVDA); F3 fails only if the first 45 RTH minutes routinely capture **more than half** the day's whole range. |
| **F4** | One full 10-gate evaluation on option C at 15 m exceeds 2 h before B6 | a measured single 24-symbol pre-sealed pass completing in under 12 min. |
| **F5** | Live execution cannot reproduce the modelled fill on this entitlement | an entitlement probe recording `latency_category = REALTIME` for any equities feed, or a bar size strictly greater than the measured feed delay being adopted (e.g. hourly bars against a 15-minute delay). |
| **F6** | The strategy's own regime gate, not the market, produces the bear shortfall | finding that on the 19 tradeable bear sessions the strategy still generates < 10 trades across 24 symbols — that would move the diagnosis from "gate shut" to "no signal", and would *strengthen* the null option rather than weaken it. |

**If F1 or F3 is falsified, the recommendation in §0 changes.** If F2 or F4 is
falsified, the corresponding bundle item is dropped. F5 is the operator's decision
gate, not a research finding.

---

## 5. Gate-by-gate forecast

Trade sets tagged per §0.2: gates 2/3/4 read `full.out_of_sample`; gates 1/6/7 read
`full.trades` (**all** pre-sealed, IS+OOS — including gate 7, whose docstring at
`config/research.py:111-113` contradicts `promotion.py:775`). Forecasts assume the
full bundle (§2.3) is applied and option C data exists; without the bundle every
gate 1–7 reads **0 trades** and fails (verified, §2.3).

| Gate | Trade set | Forecast | Confidence |
|---|---|---|---|
| **0** `data_availability` | — | **Pass only under option B or C**, and only after §2.2. Fails on option A by (e) if the window is shorter than 716 days, and passes (a)–(d) only with a complete, RTH-only, `massive`-sourced, correctly-sized backfill | FACT (arithmetic) |
| **1** `rolling_walkforward` | all pre-sealed (~13,500) | **Pass on the trade-count conjunct** — each of 4 folds would carry ~3,400 trades against a floor of 15 (`promotion.py:632`, the shared `sensitivity_min_grid_trades` constant). Whether 2 of 4 folds show `expectancy_r > 0` is unknown and is the real test | HYPOTHESIS |
| **2** `min_oos_trades` | OOS (~5,400) | **Pass with enormous margin** (≥ 30). The only gate in the ladder that is trivially satisfied here | HYPOTHESIS on the rate; FACT on the mechanism |
| **3** `net_expectancy` | OOS | **Expected FAIL — the binding gate.** Requires gross edge > 0.14R–0.37R/trade (§8). Break-even hit rate 45.5 %–54.7 % against a 1.5R:1R nominal payoff whose random-walk baseline is 40.0 % — and the realised payoff ratio is **strictly below 1.5** (see the leash/target note below) | HYPOTHESIS, but the cost half is FACT |
| **4** `bootstrap_ci` | OOS | **Not power-limited — a first for this program.** Required n = `(1.96·sd/(exp − 0.02))²`. At an expected OOS n ≈ 5,400 the hurdle is `exp > 0.02 + 1.96·sd/√5400` = **+0.0415R** at `sd = 0.807`, **+0.0467R** at `sd = 1.0`, **+0.0579R** at `sd = 1.420`, **+0.0664R** at `sd = 1.741`. Contrast v6, which needs n = 5,428 at its point estimate. Gate 4 passes iff gate 3 passes with ≈ 0.05R to spare | DERIVED |
| **5** `parameter_sensitivity` | OOS per grid point | **Automatic FAIL today** (`promotion.py:694-703`: no grid for the `intraday_orb` prefix). With §6's grid registered, 9 cells × ~5,400 OOS trades each — the 15-trade floor is irrelevant; positivity is the open question. Cost: 9 extra full passes (§3.4) | FACT on the current failure |
| **6** `regime_coverage` | all pre-sealed | **FAIL today, unconditionally** (F2 — `datetime`/`date` key miss: `0/0/0`, unbucketed = 100 %). After B2: **unbucketed ≈ 178/1,337 = 13.3 % of tradeable sessions** (the `label_regimes` 200-session warmup, §0.6); bull ≈ 10,300, **bear ≈ 190**, range ≈ 1,170 at the §3.5 rate. Passes on option C or B; **arithmetically impossible on option A** (0 bear, 0 range sessions). Bear is the binding bucket and its ceiling is calendar, not skill | FACT on the mechanism; HYPOTHESIS on counts |
| **7** `benchmark_comparison` | all pre-sealed | **Unforecastable and, as constructed, not comparable.** `compute_portfolio_metrics` annualises with `ann_factor = √(trades/year)` (`portfolio_metrics.py:110`); at ~1,500 trades/year vs SPY buy-and-hold this is a very different construction on the two sides. Also `exposure` would report a clamped 1.0 (`:119`) for a strategy flat overnight | FACT on the construction |
| **8** `data_quality_and_leakage` | — | **Passes vacuously and misleadingly today** — `validate_daily` (`promotion.py:808`) would validate the *daily* bars of the 24 symbols (which pass on snapshot 3) and say nothing about the intraday bars actually traded. Requires B3 before any weight is put on it. The leakage half is clean (§7) | FACT |
| **9** `sealed_final_test` | sealed year | Not forecast. Needs ≥ 10 trades and expectancy ≥ 0R. Would be **version 1's first ever sealed test** (§10) | — |
| **10** `live_paper_probation` | — | `health_monitor.enabled` is true, so the gate itself would pass — **but a pass here is meaningless for this horizon**: `approved_scope_scan.approved_horizons` excludes INTRADAY (`approved_scope_scan.py:81`, policy comment `:19-22`) and `alerts/dispatch.py:241` skips INTRADAY, so no candidate and no alert could ever be produced | FACT |

**Zero-margin cases carried forward (§4.2 item 5).** Neither of the two named cases
is touched by this proposal: v6's gate-5 neighbour fraction (0.750 on snapshot 3,
0.500 on snapshot 4) and v5's bear bucket (11 against a floor of 10) both belong to
other versions, and nothing here re-evaluates them. The **new** zero-margin case this
proposal introduces is `intraday_orb`'s own bear bucket: 19 tradeable bear sessions is
the entire nine-year supply, and at the §3.5 rate the bucket clears the floor of 10
only if the realised entry rate exceeds `10 / (19 × 24) = 2.2 %` per symbol-session.

**A strategy-code defect found while forecasting (reported, not proposed as a
change).** FACT: `intraday_orb.py:97` admits entries while
`since_open + 1 + time_stop_bars ≤ 26 + or_bars = 29`, i.e. `since_open ≤ 16`. In a
26-bar RTH session (bars 0–25) an entry at `since_open ∈ {14, 15, 16}` puts the
12-bar time stop at bars 26–28 — **after the close**. `_resolve_exit`
(`engine.py:152-184`) has no session-boundary awareness, so those positions are
carried **overnight** with the opposite opening-range edge as the stop, exposed to the
gap. FACT: `target_price = close + 1.5 × width` is measured from the signal *close*
while the stop is `or_lo` and the fill is the *next bar's open*
(`intraday_orb.py:108-109`, `engine.py:108-109`), so the realised reward:risk is
`1.5w / (entry_fill − or_lo) < 1.5` whenever the entry is above `or_hi` — which it
always is. **Both are out of scope here** (fixing either is a behavioural change and
would require `VERSION = "0.2.0"` under R3/R7). They are recorded so that a future
intraday design starts from them, and so that no one reads a gate-3 failure as
purely a cost effect.

---

## 6. Sensitivity-grid plan (gate 5)

§4.2 item 6 requires every parameter a change introduces to become a pre-registered
axis. This proposal introduces no parameter, so the requirement resolves to R4's
carve-out 1: **register the missing grid for a family that has none** — a genuine
±1-step neighbourhood around the shipped parameters, chosen and written down before
any result is seen.

**Pre-registered now, before any intraday bar exists** (`promotion.py:161-210`, a new
`key.startswith("intraday_orb")` branch returning a factory over `ORBParams`):

```
{"or_bars": [2, 3, 4], "target_range_mult": [1.25, 1.5, 1.75]}
```

Rationale, stated in advance: `or_bars` is the definitional parameter of an
opening-range breakout (it sets both the range and, via
`26 + p.or_bars`, the entry-window guard at `intraday_orb.py:97`), and
`target_range_mult` sets the payoff ratio that §5's break-even hit rate turns on.
Coverage is **2 of 5** `ORBParams` fields — the same 2-of-6-to-8 shortfall §0.5
criticises, and it is declared rather than hidden. The three untested fields are
`min_bars_before_entry`, `max_bars_after_open` and `time_stop_bars`.

**Why the usual `stop_atr` axis is unavailable (FACT):** every other family's grid
pairs a signal axis with `stop_atr`. `ORBParams` has no `stop_atr` — the stop is
structural (`stop_price = or_lo`, `intraday_orb.py:108`). There is no risk-sizing
axis to perturb, so this grid is genuinely two signal axes.

**Mandatory pre-integration no-op check (§4.2 item 6, §2.1's silent failure mode).**
Before the grid is used in a verdict, confirm each axis measurably moves the OOS
trade count **or** OOS expectancy: run the 3 × 3 grid and assert that the nine
`(n_trades, expectancy_r)` pairs are not all identical, and specifically that
`or_bars ∈ {2,4}` changes `n_trades` (it must: it changes both the range definition
and the entry-window guard) and that `target_range_mult ∈ {1.25, 1.75}` changes
expectancy. A grid whose nine cells coincide passes gate 5 at 100 % having tested
nothing.

**Coupling to disclose (§4.3):** the per-cell floor `sensitivity_min_grid_trades = 15`
(`config/research.py:106`) is **also** gate 1's per-fold floor (`promotion.py:632`).
Neither may be changed (R4); at the trade scale forecast in §3.5 neither binds.

---

## 7. Leakage argument

**Point-in-time contract.** All three intraday features read `(series, t)` with
slices `≤ t`: `bars_since_open` walks backwards from `t`
(`features/intraday.py:28-32`); `opening_range` enumerates `range(t + 1)`
(`:39`); `session_bar_count` delegates to `bars_since_open` (`:52-54`). The module
docstring states the contract (`:3-5`). The strategy reads nothing else except
`ctx.regime`, which is a **daily** `RegimeState` looked up by the trade's own session
date (`backtest_runner.py:183, 213-217`) — i.e. the regime as of the close of a bar
in the same session. That is the one place a careful reader should stop.

**Verified, not asserted (FACT, in-process on a synthetic 40-session 15 m series):**
`assert_no_lookahead` (`backtest/leakage.py:23-41`) reports **clean** for
`opening_range(...)[0]`, `opening_range(...)[1]`, `bars_since_open` and
`session_bar_count`. This is the check gate 8 would run under bundle item B4; it is
not run by the ladder today (`promotion.py:249-267` checks only the four daily
features against the daily proxy).

**Two residual point-in-time concerns, both requirements rather than findings.**

1. **Same-session regime.** `regime_lookup` labels a session from the daily bar of
   that session, whose close is not known while the session is being traded. For a
   *daily* strategy this is harmless (the signal is evaluated at bar `t`'s close and
   filled at `t+1`'s open, so the regime is strictly past). For an **intraday**
   strategy trading inside session `D`, `ctx.regime` for `D` is derived from `D`'s
   own close — **future information relative to a 10:15 entry**. Requirement: an
   intraday run must lag the regime by one session (use `D−1`'s label). This is a
   genuine lookahead that `assert_no_lookahead` cannot catch, because it lives in the
   `regime_by_date` plumbing (`backtest_runner.py:183`), not in a feature function.
   **It is also a behavioural change and therefore out of scope here** — it would
   require `VERSION = "0.2.0"` under R3. Recorded as a blocking prerequisite for any
   future intraday promotion attempt.
2. **Session grouping by UTC date.** Covered in §2.4: RTH-only ingest is required, or
   `_session_date` mis-assigns EST post-market bars to the following session.

**No new cross-sectional or breadth term is introduced**, so no new
`StrategyContext` plumbing (`strategies/base.py:15-19`) is needed and no shared
surface changes.

---

## 8. Cost-model statement (quantitative)

**The cost model is unchanged (R4).** FACT: `backtest/costs.py:11-16` —
`commission_per_share = 0.0`, `commission_min_per_order = 0.0`, `slippage_bps = 3.0`,
`half_spread_fill_penalty = True`. FACT: `engine.py:90` `spread_bps: float = 5.0`;
`engine.py:94` `slip = (3.0 + 5.0/2)/10,000 = 5.5 bps` per side; `engine.py:144`
`costs_bps = 11.0` bps of notional per round trip. FACT:
`backtest_runner.py:205-206` never passes `spread_bps`, so the 5.0 bps assumption is
universe- **and horizon**-independent.

**Per-trade cost in R.** `engine.py:111` defines `risk_per_share =
|entry_fill − stop_price|`. For this strategy the stop is the opposite opening-range
edge (`intraday_orb.py:108`), so `risk/price ≈ w`, the **opening-range width as a
fraction of price** — *not* `stop_atr × ATR/price`. The map's formula therefore
becomes `cost_R = round_trip_bps / 10,000 ÷ w`:

| OR width `w` (% of price) | @ 11.0 bps (today) | @ 26 bps (20 bps quoted) | @ 36 bps (30 bps quoted) | @ 66 bps (60 bps quoted) |
|---|---|---|---|---|
| 0.20 % | **0.5500R** | 1.3000R | 1.8000R | 3.3000R |
| 0.30 % | **0.3667R** | 0.8667R | 1.2000R | 2.2000R |
| 0.50 % | **0.2200R** | 0.5200R | 0.7200R | 1.3200R |
| 0.80 % | **0.1375R** | 0.3250R | 0.4500R | 0.8250R |
| 1.20 % | **0.0917R** | 0.2167R | 0.3000R | 0.5500R |

Sanity check of the formula against the map: `trend_continuation` at
`stop_atr = 1.5`, `ATR/price = 2 %` gives `risk/price = 3 %` and
`0.0011 / 0.03 = 0.0367R`, matching §0.4's 0.037R exactly.

**Pre-sealed anchor for `w` (FACT, read-only):** across the 24 snapshot-3 symbols on
`2016-10-17 … 2025-09-07`, mean daily `(H − L)/C` has median **1.579 %**
(min 1.090 % DIA, max 3.663 % NVDA). HYPOTHESIS: a 45-minute opening range captures
roughly 30–45 % of the day's range, putting `w ≈ 0.5–0.7 %` for this universe — this
fraction is **not** verified in this repo and measuring it is item 1 of the
post-ingest diagnostic. F3 (§4) is the kill test.

**Comparison to the rest of the program (DERIVED):** at `w = 0.5 %` this strategy
pays **0.22R** per round trip at the *unchanged, optimistic* 11 bps — **5.2×**
`volatility_breakout`'s 0.042R, which §0.4 already flags as "68 % of its entire
edge", and **6.0×** `trend_continuation`'s 0.037R.

**Turnover delta.** This proposal changes no rule, so the turnover delta versus
`intraday_orb` v0.1.0 is **zero by construction**. In absolute terms, DERIVED at the
§3.5 rate: ~13,500 pre-sealed trades against v2's 1,169 (§0.6) — **≈11.5×** the
busiest strategy in the program, so any cost error is amplified ~11.5× at the
portfolio level.

**Break-even hit rate (DERIVED).** With a nominal 1.5R target and a 1R stop, net
expectancy `p·1.5 − (1−p)·1 − c > 0` requires `p > (1 + c)/2.5`: **45.5 %** at
c = 0.1375R, **48.8 %** at 0.22R, **54.7 %** at 0.3667R, **62.0 %** at 0.55R. The
random-walk baseline for a 1.5:1 bracket is 40.0 %, and §5 notes the *realised*
payoff ratio is strictly below 1.5, which raises every figure above.

**Expanded-snapshot requirement (§4.2 item 8).** Not applicable — this proposal uses
the existing 24-symbol snapshot-3 set and does not run on an expanded universe.
Should an intraday run ever be attempted on an expanded snapshot, the 2× (26 bps) and
5× (66 bps) columns above are pre-registered as mandatory, and the 5× column puts
cost above **1R per round trip** for `w ≤ 0.5 %`.

**Unmeasurable-spread caveat (FACT).** NBBO quotes return `403 not_authorized`
(`data/entitlements.py`, feed `stocks_nbbo_quotes`;
`reports/SUBSCRIPTION_STATUS.md:17`), and `universe/screen.py` flags every symbol
`F_SPREAD = "spread_filter_not_licensed"`. **The true opening-auction spread cannot
be measured on this plan at all**, so the 5.0 bps assumption can be neither validated
nor calibrated for the one time of day this strategy trades.

---

## 9. Variant budget and stopping rule

**Strategy variants: 0.** This angle proposes no rule change and no `v0.2.0`, so it
consumes **none** of `intraday_orb`'s variant budget. Recorded verbatim for the final
report (R5): *`intraday_orb.intraday` — requirements angle: 0 strategy variants
tried, 0 pre-sealed backtests of a modified rule set, 0 sealed looks consumed.*

**Non-strategy work items, and their stopping rule.** If the operator authorises the
pipeline, the budget is:

| Item | Budget | Stopping rule |
|---|---|---|
| Bar size | **1** (15 m) | fixed in advance by `config/research.py:303` and the 26-bar guard at `intraday_orb.py:97`. **5 m is not to be tried** as an alternative — it would be a bar-size search over the same sealed calendar year, i.e. a variant in disguise, and it costs 9× the compute (§3.4) |
| History depth | **1** (option C, 2016-10-17) | chosen in advance by §3.2's bear-coverage arithmetic, not by results. If the budget only permits option B, that is a cost decision taken before any run |
| Gate-5 grid | **1** (§6, pre-registered) | fixed before any intraday bar exists |
| Full promotion evaluations of the unchanged v0.1.0 | **1** | a single evaluation on the keyed intraday snapshot. If it fails, the outcome is the §11 documented non-pass — **not** a strategy variant. Proposing a `v0.2.0` afterwards would be a *new* proposal requiring its own §4.2 document and its own budget |

**Hard stop.** If any of F1, F4 or F5 (§4) holds at decision time — and all three hold
today — the work stops before ingestion and the null option is taken. The most
expensive failure mode available here is spending ~50 min of API budget, 0.5–1.6 GB
of a live database and 5.4 h of compute to reach a gate-3 failure that §8 already
forecasts from arithmetic.

---

## 10. Sealed-look accounting

**Reproduction of the §0.1 ledger (FACT, re-queried read-only for this document:
`strategy_sealed_test` has 20 rows, 4 each for versions 2–6):**

| Ver | Strategy | snap 1 `universe_25_baseline_legacy` | snap 2 `universe_25_baseline` | snap 3 `universe_24_ex_meta` | snap 4 `universe_25_meta_continuity_corrected` |
|---|---|---|---|---|---|
| 2 | `trend_continuation.short_swing` | id 1: +0.3246R / 112 ✅ | id 6: +0.3246R / 112 ✅ | id 11: +0.2982R / 109 ✅ | id 16: +0.3246R / 112 ✅ |
| 3 | `trend_continuation.medium_swing` | id 2: +0.0109R / 98 ✅ | id 7: +0.0109R / 98 ✅ | id 12: −0.0294R / 95 ❌ | id 17: +0.0109R / 98 ✅ |
| 4 | `mean_reversion.short_swing` | id 3: +0.1230R / 91 ✅ | id 8: +0.1230R / 91 ✅ | id 13: +0.1278R / 84 ✅ | id 18: +0.1230R / 91 ✅ |
| 5 | `relative_strength.medium_swing` | id 4: +0.2935R / 16 ✅ | id 9: +0.2935R / 16 ✅ | id 14: +0.2935R / 16 ✅ | id 19: +0.2935R / 16 ✅ |
| 6 | `volatility_breakout.short_swing` | id 5: −0.0979R / 10 ❌ | id 10: −0.0979R / 10 ❌ | id 15: −0.0979R / 10 ❌ | id 20: −0.0979R / 10 ❌ |
| **1** | **`intraday_orb.intraday`** | **— none** | **— none** | **— none** | **— none** |

**The program-wide baseline count is k = 5** (four existing locked sealed draws per
strategy family plus the next one), and every report must start from it.

**Version 1's own position in that ledger (FACT, queried):** version 1 has **zero**
rows in `strategy_sealed_test` — it is the reason there are 20 rows and not 24
(§2.4). It has **seven** promotion evaluations (ids **1, 7, 13, 19, 25, 31, 37**,
across snapshots 1, 1, 2, 3, 2, 3, 4), every one recording verdict *"NO TRADE —
insufficient evidence or poor risk/reward"* with `passed = 0`, all stopped at gate 0
before any sealed window was ever opened.

**What this proposal costs in looks: zero.** It proposes no evaluation, no new
`StrategyVersion`, and no run that could reach gate 9. `intraday_orb`'s sealed-look
count stays at **0** and the program's stays at **k = 5**.

**Accounting for any future intraday evaluation, pre-registered now:**

- An evaluation of the **unchanged v0.1.0** on a new keyed intraday snapshot
  (`universe_24_ex_meta_intraday_15m`) that reaches gate 9 would create
  `strategy_sealed_test` row **21** — **version 1's first sealed look ever**. Under
  the program-wide convention it is disclosed as **look 6** (k = 5 baseline + 1) and
  **simultaneously** as version 1's own look 1. Both numbers must appear.
- A subsequent `v0.2.0` on the same snapshot would be **look 7**; a `v0.2.0` on both
  the intraday snapshot and any expanded snapshot would be **looks 7 and 8**.
- **Which snapshot the report leads with, pre-registered (R1):**
  `universe_24_ex_meta_intraday_15m` — because its symbol set is snapshot 3's, the
  only symbol set on which gate 8 `validate_daily` passes (§0.1), and because no
  other intraday snapshot exists. The four daily draws in the table above are
  disclosed alongside it in every case, and the fact that version 1 contributes none
  of them is stated explicitly.
- **R3 trap check.** No strategy code changes here, so `upsert_strategy_version`
  (`persistence.py:46-93`) refreshing `spec_json`/`git_sha` on the same row cannot
  produce a stale-sealed-test pass. Any *future* behavioural change (including the
  regime-lag fix in §7 and the leash/target defects in §5) ships as
  `VERSION = "0.2.0"`, with the §4.3 pre-integration check that the new sealed test's
  `strategy_version_id` is a row created by that run.

---

## 11. Null option

**The null option is the recommendation, not the fallback.**

**What gets written:** a documented, evidence-backed *"does not operate"* record for
`intraday_orb.intraday` v0.1.0 — the second of the two honest end-states
`STRATEGY_COMPLETION_PLAN.md` allows, and distinct from the "does not pass" records
the other four strategies may earn. The distinction matters: v3, v4 and v6 can fail
on *evidence*; v1 has never been measured and cannot be, so its record is a
**capability** finding, and it must not be filed as though the rules had been tested
and found wanting.

**Evidence it carries (all pre-sealed or code arithmetic, all reproducible read-only):**

1. Three independent blocks, unchanged from §2.4 of the map, with the R4 correction:
   the promotion-path gate is removable in principle (§2.2), the EOD-only operating
   policy (`approved_scope_scan.py:81` and its `:19-22` comment;
   `alerts/dispatch.py:241`) and the absent data path (`massive.py:86-100` declares
   only `BAR_DAILY`) are not.
2. **A fourth block the map did not state: latency.** The entitled intraday feed is
   `DELAYED` ≥ 15 min against a 15-minute bar, so the modelled next-bar-open fill is
   unattainable live, and no `REALTIME` equities feed exists on this plan (§0.1).
3. **A fifth block: cost.** 0.14R–0.37R per round trip at the frozen, optimistic
   11.0 bps — 4–10× any daily strategy — against a nominal 1.5:1 payoff whose
   break-even hit rate is 45.5 %–54.7 % versus a 40.0 % random-walk baseline (§8).
4. The measured build cost of finding out anyway: 240 paced API calls / ~48 min,
   0.53–1.60 GB added to a live 0.38 GB database, and ~5.4 h of compute per
   evaluation before the `O(n²)` fix (§3.3, §3.4).
5. The gate-6 calendar ceiling: 19 tradeable bear sessions in nine pre-sealed years
   (7.12 % ± 1.57 % of bear-labelled sessions), zero after 2023-06-02, and zero at any
   pre-sealed start on or after 2022-09-08 (§3.1, §3.2).
6. The five promotion-path defects (B1–B6, §2.3) that must be fixed before any
   intraday number from this pipeline means anything, and the two behavioural defects
   (§5) and one regime-lookahead (§7) that would each force a `v0.2.0`.

**Sealed-window use in this section, marked per R1 (disposition — permitted):** the
sealed year plays no part in the argument above; `intraday_orb` has no sealed test to
cite (§10). Its absence is itself the disposition fact: **nothing in this program's
sealed evidence has ever bound on this strategy, so declining to build the pipeline
forfeits no measured edge.**

**Status the record should carry:** `EXPERIMENTAL`, unchanged — no downgrade, no
approval, no deletion. `Strategy` id 1 stays as it is. The record is a document, not
a database change.

**What would reopen it (the operator's re-entry condition, pre-registered):** a
real-time (not `DELAYED`) U.S. equities entitlement verified by
`data/entitlements.py`, **plus** a measured effective opening-auction spread for the
24-symbol universe (which today requires an NBBO entitlement that returns `403`),
**plus** an operator decision to change the EOD-only policy. Absent all three, the
answer is stable and should not be revisited per-quarter.

---

## Operator questions (the explicit decisions this design exists to surface)

**Q1 (the decisive one) — do you want intraday operation at all, given that the
policy is currently also an entitlement fact?** EOD-only is enforced structurally in
three places (`approved_scope_scan.py:81`, `alerts/dispatch.py:241`, and
`MassiveAdapter`'s hard-wired `END_OF_DAY` latency, `massive.py:1-10, 86-100`).
Relaxing the policy does **not** make intraday operable, because the entitled feed is
`DELAYED` ≥ 15 min against a 15-minute bar and no `REALTIME` feed exists on this plan.
The real question is *"will you buy a real-time equities entitlement?"* — and until
that is yes, the honest answer to Q1 is **no**, and §11 is the outcome.

**Q2 — convert gate 0 to a real data query (R4-permissible, §2.2)?** My
recommendation: **only bundled with B1–B6 (§2.3), or not at all.** Alone it converts
a truthful, self-explaining hard fail into a set of zero-trade gate failures that read
as strategy defects (verified: 0 trades on daily bars). It buys nothing while blocks 2
and 3 stand, exactly as §2.4 of the map says.

**Q3 — history depth, if Q1 is yes.** Option A (the shortest gate-0-legal span) is
**not viable**: 0 bear and 0 range sessions, gate 6 arithmetically unreachable. Option
B (2021-09) is the minimum that admits *any* bear coverage (16 sessions). Option C
(2016-10, parity with the daily program) gives 19. Recommendation if proceeding: **C**.

**Q4 — operational risk to the live probation.** The backfill inserts 0.8–1.6 M rows
into the same SQLite file a live paper probation and a background worker are using,
growing it by 1.4–4.2×. It needs a maintenance window with the worker stopped, and a
decision on whether intraday bars belong in this database at all rather than a
sidecar.

**Q5 — gate 7's docstring/code divergence** (`config/research.py:111-113` says OOS,
`promotion.py:775` computes all pre-sealed) remains open from §0.2. It is not
specific to this strategy, but an intraday run at ~1,500 trades/year makes the
Sharpe-annualisation construction (`portfolio_metrics.py:110`) much more consequential
than it is for a 100-trade/year swing strategy.

---

*Requirements proposal, `intraday_orb.intraday` v0.1.0. Read-only: no strategy code,
no configuration, no database row and no gate threshold was changed in producing this
document. No provider API was called. Every number above is a `SELECT` result, a
`file:line` citation, an in-process read-only computation, or an arithmetic derivation
whose inputs are stated.*
