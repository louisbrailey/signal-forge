# Design — `intraday_orb.intraday` v0.1.0 (version 1): requirements, costed, with the operator question

**Synthesis of the design phase for version 1.** One proposal was written for this
strategy (`docs/research/designs/proposals/intraday_orb--requirements.md`, the
*requirements* angle — `STRATEGY_COMPLETION_MAP.md` §4.1 assigns exactly one,
"requirements only … **No promotion attempt**"), and it was scored by two judges
(legitimacy 7/10 *revise*; impact/robustness/cost 7.5/10 *revise*). There are no
runners-up to graft from; this document is that proposal corrected against every
judge defect that survived checking, plus four findings of my own, plus the
pre-registration and implementation material §4.2 items 4/6/9/10 require.

**Conformance.** Written to `STRATEGY_COMPLETION_MAP.md` §4.2 (all eleven sections,
in order, §§1–11 below), under §1 rules R1–R10 and `STRATEGY_COMPLETION_PLAN.md`'s
seven rules. Every claim is labelled **FACT** (a `file:line`, a read-only `SELECT`,
or a reproducible in-process computation), **DERIVED** (arithmetic on stated inputs)
or **HYPOTHESIS**.

**Sealed-window discipline (R1).** Nothing here is derived from the sealed window
(2025-09-08 → 2026-09-08 on snapshots 2–4; 2025-09-07 → 2026-09-07 on snapshot 1).
Every computed number is code arithmetic, a read-only query, or a computation over
the **pre-sealed** span `2016-10-17 … 2025-09-07`. The sealed window is referenced
twice, both for **disposition** (permitted under R1) and both marked inline: §10
(the look ledger) and §11 (the null option).

**Work performed.** Read-only. No file under `src/` or `tests/` was modified, no
database write was issued, no provider API was called, no package installed, no
service restarted. In-process calls were limited to `PriceSeries.load`,
`backtest/regime.label_regimes` and `research/regime.regime_lookup` (all read-only),
plus `SELECT`s against `data/signalforge.sqlite` opened `mode=ro`.

---

## A. Chosen path

**The chosen path is the requirements record plus the operator question — and its
recommendation is the null option of §11: do not build the intraday pipeline.**

This is not a "does not pass" record. `intraday_orb.intraday` has never been
measured past gate 0 and, under today's entitlements, cannot be measured in a way
that would mean anything live. Its record is a **capability finding**
("DOES NOT OPERATE"), and filing it as though the rules had been tested and found
wanting would be false. Status stays `EXPERIMENTAL`; no database row changes.

Three things the corrected analysis says that the original proposal did not:

1. **No evaluation of the unchanged v0.1.0 may ever be run.** The proposal's own §7
   establishes a genuine lookahead — an intraday entry inside session *D* reads
   `ctx.regime` derived from *D*'s own daily close — and then §9/§10 pre-registered
   "full promotion evaluations of the unchanged v0.1.0: **1**". Those cannot both
   stand. The lag fix is behavioural and requires `VERSION = "0.2.0"` (R3/R7), so the
   **first evaluable artifact for this strategy is a v0.2.0, not v0.1.0**, and that
   v0.2.0 needs its own §4.2 design document and its own variant budget. This
   document therefore pre-registers **zero** evaluations and **zero** sealed looks.
2. **The "hard nine-year calendar ceiling" on gate 6's bear bucket is a property of
   the ladder's long-only run configuration, not of the calendar.** Both judges caught
   this and both are right; I reproduced it independently (§3.1). It changes the
   framing of the headline finding, not the recommendation.
3. **The cost finding is an upper bound, and gate 4 is *not* "the first non-power-
   limited gate in the program".** Once the program's own adopted clustering
   diagnostic (`docs/research/diagnostics/clustered_bootstrap_all.md`) is applied, an
   intraday strategy is the most calendar-clustered trade set here and its effective
   *n* is nothing like its trade count (§5, gate 4).

### A.1 Judge-defect disposition

| Defect | Judge | Disposition | Where fixed |
|---|---|---|---|
| J1-1 / J2-1 `allow_short` undisclosed; bear-session arithmetic conditional | both | **Accepted (major).** Reproduced independently: short-eligible bear sessions are **248 / 212 / 167 / 167 / 123 / 18 / 18 / 0** at starts 2016-10-17 / 2018-09-10 / 2019-09-09 / 2020-09-08 / 2021-09-08 / 2022-09-08 / 2023-09-08 / 2024-09-22 | §3.1, §3.2, F1, §12.2, Q6 |
| J1-2 §7 "blocking" vs §9/§10 budget | legitimacy | **Accepted (major).** Resolved in favour of §7: the lag is blocking; the budget now pre-registers 0 evaluations of v0.1.0 | §A, §9, §10 |
| J1-3 new gate-0 constants (95 %/99 %/staleness) | legitimacy | **Accepted as a hardening requirement; rejected as a legitimacy violation.** A hard-coded unconditional fail cannot be *weakened* by adding conditions, so R4 is not breached — but the constants are unnecessary slack on an operator-controlled backfill. Replaced with 100 % against an enumerated exchange calendar, and frozen | §2.2 |
| J1-4 no R4 argument for B1–B6 | legitimacy | **Accepted.** Each bundle item now carries one | §2.3 |
| J1-5 B2 unreconciled with §7 | legitimacy | **Accepted.** Gate 6 buckets *descriptively* on session *D*; the traded signal must lag to *D−1*. Stated, with the asymmetry disclosed in the evidence blob | §2.3 B2, §7 |
| J1-6 / J2-4 "4–10×" multiple unsupported | both | **Accepted.** Corrected to 3.3×–8.7× vs `volatility_breakout` (0.042R) and 6.3×–16.7× vs `relative_strength` (0.022R) at λ = 1 | §0, §8, §11 |
| J1-7 zero-margin case in wrong units | legitimacy | **Accepted.** Restated in gate 6's own units (trades) *and* in sessions, naming session supply as the zero-margin quantity | §5 |
| J1-8 F3/F4/F6 not stated across snapshots (R10) | legitimacy | **Accepted.** All eight falsifiers now carry an explicit four-snapshot statement | §4 |
| J1-9 gate-0 RTH purity depends on ingest discipline, not code | legitimacy | **Accepted.** Added as bundle item **B7** (`load_intraday` must filter or assert on `session`) | §2.3 B7 |
| J1-10 map self-contradiction on *k* | legitimacy | **Accepted.** The contradiction is in the map, not the proposal: `MAP.md:69` and `:341` say "look 5", `:1321-1322` says "look 6". Flagged; this report adopts **k = 5 baseline, next = look 6**, per §4.2 item 10 and per my task brief, with version 1's own count disclosed alongside | §10 |
| J2-2 gate 4 ignores the clustered-bootstrap diagnostic | impact | **Accepted (major).** Gate 4 restated with a design-effect term; "not power-limited — a first for this program" **withdrawn** | §5 gate 4 |
| J2-3 cost table ignores the overshoot factor λ | impact | **Accepted, with one correction to the judge.** λ = (entry_fill − or_lo)/w is **not** strictly ≥ 1: the fill is the *next bar's open* (`engine.py:107-109`), which can print back inside the range. λ ≥ 1 holds typically, not by construction | §8, F3 |
| J2-5 entry rate quoted with a sampling SE | impact | **Accepted.** Replaced by a bracket **0.4–0.8 trades/symbol-session** with no SE, plus a hard structural ceiling of **2** | §3.5 |
| J2-6 gate-6 unbucketed stated as a session share | impact | **Accepted.** Trade count now stated, with the uniformity assumption named | §5 |
| J2-7 storage multiple inconsistent (§3.3 vs Q4) | impact | **Accepted.** One table, added bytes and final multiple both stated | §3.3 |
| J2-8 wall-clock quoted without a hardware band | impact | **Accepted.** ±15 % band; F4 restated as a ratio | §3.4, F4 |
| J1-1's inference that the Option C recommendation collapses | legitimacy | **Partially rejected.** Option **A** is dead under *both* settings (0 bear and 0 range *labelled* sessions at 2024-09-22 — verified), and the pre-registered ladder configuration is long-only, under which the 2021-09 floor stands. What collapses is the claim that the ceiling is *calendar*, not configuration | §3.2 |
| J1-2's alternative remedy ("withdraw the word blocking") | legitimacy | **Rejected.** The same-session regime read is a real lookahead for an intraday entry; it is blocking | §7 |

### A.2 Four findings neither the proposal nor the judges stated

- **FACT.** `signalforge data ingest-intraday` (`cli.py:622-659`) takes only a
  trailing `--days`; there is no `--since`/`--until`. A 2016 backfill has no CLI
  entry point today, and `ingest_intraday_universe` would be handed one ten-year
  window. The proposal's "no new ingest code is needed" is wrong at the CLI layer
  and at the chunking layer (B9, §2.3).
- **FACT.** `signalforge evaluate-promotion` (`cli.py:1282-1305`) accepts
  `--dataset` from a closed set of three names only; there is no way to select or
  create a custom-keyed snapshot from the CLI. `evaluate_promotion(...,
  dataset_snapshot=...)` does accept one (`promotion.py:483-491`), so the keyed
  intraday snapshot requires an in-process script or a new CLI flag (B10, §2.3).
- **FACT.** `ResearchConfig.enabled_horizons` **includes** `Horizon.INTRADAY`
  (`config/research.py:297-302`) while `approved_scope_scan.approved_horizons`
  excludes it (`:81`) and `alerts/dispatch.py:241` skips it. The EOD-only policy is
  therefore inconsistent across three surfaces — a fourth policy surface the map's
  §2.4 "three blocks" framing does not name.
- **FACT.** `run_backtest` sets `t = exit_idx + 1` (`engine.py:150`) — no overlapping
  positions per symbol. With a 26-bar RTH session, an entry window of
  `3 ≤ since_open ≤ 16` and a 12-bar time stop, **at most 2 trades per symbol-session
  are structurally possible**. This is a hard ceiling on every trade-count forecast
  below and on the gate-6 bear bucket (≤ 19 × 24 × 2 = 912 long bear trades in nine
  pre-sealed years).

---

## 0. Executive summary — the five findings that decide this

1. **FACT — latency: the entitled feed's delay equals the bar size, so the modelled
   fill is unattainable live.** Intraday aggregates are entitled but `DELAYED` ≥ 15 min
   (`data/entitlements.py:246-257`, feed `stocks_intraday_aggs_5m`, `latency="DELAYED"`;
   `docs/CAPABILITY_MATRIX.md:26`; `reports/SUBSCRIPTION_STATUS.md:19` "No real-time
   feed on this plan"), and the research bar size is 15 m
   (`config/research.py:303`). **DERIVED:** the engine signals on bar *t*'s close and
   fills at bar *t+1*'s open (`engine.py:106-109`), i.e. at the same instant. With a
   delay *d* and bar size *b*, the earliest attainable action is the open of bar
   *t + 1 + ceil(d/b)* — at *d = b =* 15 min that is bar *t+2*. **The backtest fill is
   exactly one bar early, permanently.** `LatencyCategory.REALTIME` is never set by
   any adapter (`grep`: only the enum, the migrations and a docstring warning).
2. **FACT/DERIVED — cost: this strategy's risk unit is the opening-range width, so
   the frozen 11.0 bps round trip buys a far bigger slice of it than for any daily
   strategy.** `risk_per_share = |entry_fill − stop_price|` (`engine.py:110`) and the
   stop is the opposite OR edge (`intraday_orb.py:108`), so
   `cost_R = 0.0011 / (λ·w)` where *w* is the OR width as a fraction of price and
   λ = (entry_fill − or_lo)/w. At **λ = 1** and *w* ∈ [0.30 %, 0.80 %] the cost is
   **0.37R – 0.14R per round trip** — **3.3×–8.7×** `volatility_breakout`'s 0.042R
   (the program's most expensive) and **6.3×–16.7×** `relative_strength`'s 0.022R
   (`MAP.md` §0.4). Gate 3, not gate 4, is the expected binding gate — a reversal of
   the pattern for every other strategy. This is an **upper bound**: λ > 1 lowers it.
3. **FACT — the promotion path is intraday-incapable in at least eight places beyond
   gate 0, and one makes gate 6 fail unconditionally.** `promotion.py:744` looks each
   trade up as `regimes.get(t.entry_date, "warmup")` against `label_regimes`'
   `dict[date, str]` (`backtest/regime.py:25`); for an intraday run `t.entry_date` is
   a `datetime` (`engine.py:136` ← `series.dates[entry_idx]`), and a `datetime` key
   never matches a `date` key. Buckets would read `0/0/0` with 100 % unbucketed
   whatever the data says. Converting gate 0 alone is therefore **necessary but must
   not ship alone** (bundle B1–B10, §2.3).
4. **FACT — gate 6's bear bucket is supply-limited, and the size of the limit depends
   on the run configuration.** Under the ladder's **hard-wired long-only**
   configuration (`run_strategy_over_universe(..., allow_short: bool = False)`,
   `backtest_runner.py:176`, never passed at `promotion.py:586`, `promotion.py:386`
   or `sensitivity.py:148`), only **19 of 267** bear-labelled pre-sealed sessions are
   tradeable (**7.12 % ± 1.57 %**), none after 2023-06-02, and **zero** at any
   pre-sealed start on or after 2022-09-08. Under `allow_short=True` — a config flag
   the operator can set from the dashboard (`config/research.py:296`;
   `app/routers/dashboard.py:332`; passed on the *live* scan path at
   `research/scan.py:271` and `cli.py:903`, but **not** on the ladder) — the strategy
   has a SHORT branch that fires exactly when `risk_off` is true
   (`intraday_orb.py:116`, `permits_short=True` at `:75`), and 248 further bear
   sessions become eligible. **Either way, the shortest gate-0-legal span (start
   2024-09-22) has 0 bear and 0 range *labelled* sessions and gate 6 is
   arithmetically unreachable.**
5. **FACT — no promotion evaluation of v0.1.0 is admissible at all.** For an intraday
   entry inside session *D*, `ctx.regime` is derived from *D*'s own daily close
   (`backtest_runner.py:183-185`; `strategies/base.py:39-40` normalises the intraday
   stamp to its session date) — future information relative to a 10:15 entry, and
   invisible to `assert_no_lookahead` because it lives in the plumbing, not in a
   feature. Fixing it is behavioural → `VERSION = "0.2.0"` (R3/R7). Running v0.1.0
   would spend version 1's first-ever sealed look on a rule set already known to read
   the future.

**Recommendation: do not build the pipeline; take the null option (§11).** It is
reversed only by an affirmative answer to **Q1** *and* a real-time equities
entitlement. The requirements below are specified in full so the decision is made on
costed facts rather than on the absence of a plan.

---

## 1. Mechanism

This design proposes no market hypothesis and forecasts no edge. It states a
**capability hypothesis**, in the §2 form the map requires, so it can be killed:

> **H13 (new).** `intraday_orb.intraday` is blocked by three independent layers
> (`MAP.md` §2.4: promotion-path gate, EOD-only operating policy, absent data path).
> H13 asserts that removing all three is **neither sufficient nor economically
> sensible**, because three further layers — provider **latency**, the frozen **cost
> model**, and a **same-session regime lookahead** in the intraday plumbing —
> independently prevent an honest, operable pass, and all three are quantifiable
> **today, with no intraday data at all**.

Why this should be true in markets, not merely in the backtest: an opening-range
breakout is a **microstructure** strategy. Whatever edge it has lives in the first
hour, when effective spread and adverse selection are at their daily maximum, and its
risk unit is the opening range — tens of basis points — rather than a multi-percent
ATR stop. Both push the same way: the ratio of transaction cost to risk unit is an
order of magnitude worse than for a swing strategy, and the sensitivity of the
realised fill to execution latency is an order of magnitude higher. A strategy of
this shape needs (a) real-time data, (b) a measured spread, and (c) a cost model
calibrated to the opening auction. This program has none of the three: real time is
unentitled, NBBO quotes return `403 not_authorized`
(`reports/SUBSCRIPTION_STATUS.md:17`; `universe/screen.py` flags every symbol
`F_SPREAD = "spread_filter_not_licensed"`), and R4 freezes the cost model at a flat,
universe- and horizon-independent 5.0 bps assumed spread (`engine.py:90`;
`backtest_runner.py:205-206` never overrides it).

H13 inherits **H12**'s replacement mechanism from
`docs/research/diagnostics/v6_regime_power.md` — a regime gate shut on almost every
bear session, producing an availability failure at gate 6 with a calendar ceiling —
and §3 shows `intraday_orb`'s LONG branch sits behind *the same gate expression*
(`not ctx.regime.risk_off`, `intraday_orb.py:105`) as `breakout.py:102`. **Corrected
from the proposal:** unlike `volatility_breakout`, this strategy also has a SHORT
branch keyed to the *complement* of that expression, so the ceiling is
configuration-dependent (§3.1).

---

## 2. Exact change — file, symbol, before → after

### 2.1 What this design does **not** change

- `src/signalforge/research/strategies/intraday_orb.py` — **unchanged**. `VERSION`
  stays `"0.1.0"`; `ORBParams` (`:29-35`) unchanged; `IntradayORB.evaluate`
  (`:88-127`) unchanged. **No `v0.2.0` is created by this design** (R3/R7 satisfied
  vacuously). The regime-lag fix that a future evaluation requires is *specified*
  here (§7) and *implemented* in a separate, separately-budgeted v0.2.0 design.
- `research/strategies/__init__.py:43-51` `default_strategies()` — unchanged.
- Any threshold in `config/research.py:93-123` or `backtest/costs.py:11-16` —
  unchanged (R4).
- **R7 / R7b safety (FACT).** Nothing here touches any `StrategySpec`, so
  `approval_scope.current_spec_json_hash()` cannot move for the two live
  PAPER_APPROVED versions (v2 `trend_continuation.short_swing`, v5
  `relative_strength.medium_swing`), and no new *passing* evaluation is created, so
  the `scopes[0]` ordering hazard (`paper_probation.py:113-122`) is not activated.
  Verified state to re-record before any future run: v2 and v5 each have exactly two
  passing evaluations, both on snapshot 3 → sealed tests 11 and 14.

### 2.2 The R4-permissible change: gate 0 becomes a real data query

**File:** `src/signalforge/research/promotion.py`. **Symbol:** `evaluate_promotion`,
the `Horizon.INTRADAY` early-return block.

**Before (FACT, `promotion.py:512-534`):** `if spec.horizon is Horizon.INTRADAY:`
appends a hard-coded failing `Gate(0, "data_availability", False, …)` and returns
`_finalize(...)` immediately — **skipping even the `MIN_PRESEALED_DAYS` check** that
the daily path applies at `:556-583`.

**After (specification, NOT applied):**

```
gate 0 (INTRADAY) passes only if ALL of:
  a. for every symbol in `symbols`, OHLCVIntraday rows exist with
       bar_size == config.intraday_bar_size, source == the run's SourceFilter,
       is_simulated is False, session == "rth", bar_start within [start, end];
  b. per-symbol session coverage == 100% of the daily sessions the same symbol
     has in OHLCVDaily over the same span and source;
  c. per-session bar count == the expected RTH count for that bar size and that
     calendar day (26 at "15m" on a full day; 14 on an enumerated NYSE half-day),
     for 100% of covered sessions;
  d. the latest ingested bar_start is no staler than the bound
     `approved_scope_scan.data_readiness` already applies to the daily feed
     (`approved_scope_scan.py:84-130`) — the SAME bound, not a new constant;
  e. the existing pre-sealed-span test then runs UNCHANGED, by falling through
     rather than returning early:
       (pre_sealed_end - start).days >= MIN_PRESEALED_DAYS == 350.
Otherwise: Gate(0, "data_availability", False, <which of a-e failed, per symbol>).
```

**Why this is R4-permissible (the §1 carve-out 2 argument, stated symmetrically).**
The current test is an unconditional fail; **any** real query is at least as hard to
satisfy, because it fails for as long as no intraday data exists and then keeps
failing on partial, mis-sized, simulated, wrong-source, non-RTH or stale data.
Nothing in the ladder becomes easier to pass, and (e) makes the intraday path
*strictly stricter* than today by restoring a check the early return skips.

**Judge defect J1-3, accepted as hardening.** The proposal's 95 % / 99 % tolerances
are unnecessary slack on a backfill the operator controls end to end, and a
tolerance that can later be relaxed to obtain a pass is a latent threshold. They are
replaced by **100 %** against an **enumerated** exchange calendar (the half-day list
is data, checked into the repo alongside the validator, not a tunable), and (d)
**reuses the daily path's existing bound rather than introducing a number**.
**Pre-registered and frozen for the duration of the program: (b) = 100 %,
(c) = 100 %, (d) = the daily feed's own bound. None of the three may be relaxed to
obtain a pass.** A gate-0 failure still returns early via `_finalize` — the ladder
must not report gates 1–10 computed on data it has just declared unfit.

### 2.3 The mandatory bundle — gate 0 must NOT ship alone

**FACT.** After §2.2, execution falls through to
`run_strategy_over_universe(...)` at `promotion.py:586`, which passes **neither**
`intraday=` **nor** `bar_size=`; the defaults are `intraday=False, bar_size="15m"`
(`backtest_runner.py:179-180`). The same omission exists at `promotion.py:386`
(gate 9's sealed run) and `research/sensitivity.py:148` (gate 5's nine re-runs). The
whole ladder would evaluate an INTRADAY strategy on **daily** bars. The proposal
verified in-process that this yields `n_trades = 0` over 53,196 daily bars —
mechanically, `_session_date` (`features/intraday.py:19-21`) returns each daily
bar's own date, so `bars_since_open` is always 0, `opening_range` never accumulates
`k_bars` bars in one "session" and returns `(nan, nan)`, and `evaluate` exits at
`intraday_orb.py:91-92`. The failure mode of shipping §2.2 alone is therefore
**misleading, not unsafe**: it cannot fabricate a pass, but it converts a truthful
self-explaining gate-0 fail into zero-trade failures at gates 1–7 that read as
strategy defects. That is unacceptable for an auditable ladder.

Each item below carries its own R4 argument, per judge defect J1-4.

| # | File / symbol | Defect today (FACT) | Required | R4 argument |
|---|---|---|---|---|
| **B1** | `promotion.py:586`, `:386`; `sensitivity.py:148` | called without `intraday=`/`bar_size=` | thread `intraday = spec.horizon is Horizon.INTRADAY` and `bar_size = config.intraday_bar_size` through gates 1–5 and 9 | Not a threshold change. Today five gates are computed on data the strategy cannot trade, yielding 0 trades → automatic fail. Threading makes them *measure the declared horizon*; the thresholds they test against are untouched. It cannot make a gate pass that a correct measurement would fail. |
| **B2** | `promotion.py:744` `regimes.get(t.entry_date, "warmup")`; keys are `dict[date, str]` (`backtest/regime.py:25`) | intraday `t.entry_date` is a `datetime` → every trade unbucketed → **gate 6 fails unconditionally** | normalise with the module's own `_as_date` (`backtest_runner.py:163-164`) before the lookup | Same carve-out shape as gate 0: a type error that makes a gate un-passable is not a *threshold*. `min_trades_per_regime = 10` and `min_regimes_covered = 3` (`config/research.py:109-110`) are untouched. Note `run_strategy_over_universe` **already** applies `_as_date` at three places (`:211`, `:214`, `:220`) — gate 6 is the one place that forgot. |
| **B3** | `data/validate.py` has only `validate_daily` (`:66`) and `validate_option_aggregates` (`:249`) | gate 8 (`promotion.py:808`) validates **daily** bars for an intraday strategy — a PASS that says nothing about the data traded | add `validate_intraday` (session completeness, bars-per-session, duplicate `bar_start`, non-positive prices, `source`/`bar_size`/`session` purity) and dispatch on horizon at gate 8 | Adds a check where there is effectively none. Strictly harder. |
| **B4** | `promotion.py:249-267` `_leakage_self_check` covers four **daily** features on the daily proxy | the intraday feature set is never leakage-checked by the ladder | add `opening_range`, `bars_since_open`, `session_bar_count` on the intraday series when the horizon is INTRADAY | Adds assertions. Strictly harder. |
| **B5** | `promotion.py:161-210` `_sensitivity_plan` has no `intraday_orb` branch (verified: four `startswith` branches, then `return None`) | gate 5 hard-fails (`promotion.py:694-703`) — permanent automatic failure, not a skip | register §6's pre-registered grid | Explicitly R4 carve-out 1 in `MAP.md` §1. The grid is fixed before any intraday bar exists. |
| **B6** | `features/intraday.py:39` `opening_range` rescans `range(t+1)`; `series.head(t)` copies the `dates` tuple (`series.py:40-51`) | backtest is `O(n²)` per symbol — one 24-symbol option-C pass ≈ **32 min**, one 10-gate evaluation ≈ **5.4 h** | precompute session boundaries once per series / cache the per-session index | Pure performance. No statistic changes; a regression test must assert identical trades before/after. |
| **B7** *(new, J1-9)* | `data/series.py:105-137` `PriceSeries.load_intraday` filters `bar_size` and `source` but **not** `session`, while `OHLCVIntraday` carries `session` (`db/models/market.py:117`) | gate 0 can certify RTH purity while the series actually traded contains pre/post bars; `_session_date` groups by **UTC** date, so an EST post-market bar ≥ 19:00 ET lands on the *next* session and corrupts its opening range | filter `session == "rth"` in the loader (or assert purity and raise) | Removes contaminating rows. Cannot admit a trade that the correct series would not admit. Ingest discipline is policy; this is code. |
| **B8** *(new)* | `portfolio_metrics.py:97` sums `bars_held` into `exposure_days`; `:119` clamps `exposure` at 1.0; `:110` `ann_factor = sqrt(trades_per_year)` | gate 7's evidence would report 100 % exposure for a strategy flat overnight, and annualise ~1,500 trades/yr against SPY buy-and-hold | horizon-aware `exposure_days` (`bars_held × bar_minutes / 390`) **reported as a diagnostic**; gate 7's pass/fail construction unchanged pending Q5 | Reporting only. Changing gate 7's construction is **out of scope** — it is the operator's open item (`MAP.md` §0.2). |
| **B9** *(new, §A.2)* | `cli.py:622-659` `ingest-intraday` offers only trailing `--days`; adapter rejects `next_url` (`massive.py:186`) | no CLI entry point for a dated backfill; a ten-year window in one request | add `--since/--until`, and calendar chunking inside the intraday adapter | New capability, no gate touched. |
| **B10** *(new, §A.2)* | `cli.py:1282-1305` `evaluate-promotion --dataset` accepts three fixed names only | the keyed intraday snapshot cannot be selected from the CLI | add `--dataset-key`, or drive `evaluate_promotion(..., dataset_snapshot=...)` (`promotion.py:483-491`) from a script | Plumbing; prevents the silent-attach hazard below. |

**Reconciliation of B2 with §7 (judge defect J1-5).** Gate 6 buckets trades by the
**daily regime label of the session the trade was entered in**. That is a
*descriptive coverage* statistic computed after the fact by the evaluator — it is not
a signal the strategy reads, so bucketing on session *D* is **not** a lookahead.
The strategy's own gate is different: it *does* read *D*'s regime while *D* is being
traded, and that **is** a lookahead (§7). The two must be allowed to disagree: after
the v0.2.0 regime lag, a trade taken on the *D−1* label is still bucketed by the *D*
label. **Requirement:** the gate-6 evidence blob must state which session's label it
buckets on, so the asymmetry is visible in the audit record rather than inferred.

### 2.4 Data-pipeline requirements

| Item | Requirement | Evidence / basis |
|---|---|---|
| Adapter | a real `MassiveAdapter.fetch_intraday_bars` satisfying `IntradayBarAdapter` (`adapters/base.py:138-149`), declaring `AdapterCapability(feed_type=BAR_INTRADAY, latency_category=DELAYED, rate_limit_per_min=5)` | FACT: `massive.py:86-100` declares **only** `BAR_DAILY` with `END_OF_DAY`; the only `BAR_INTRADAY` capability in the repo is the test fixture (`adapters/fixture/__init__.py:79`) |
| Endpoint | `/v2/aggs/ticker/{sym}/range/15/minute/{from}/{to}?adjusted=true&sort=asc&limit=50000` | FACT: the daily path uses the same family (`massive.py:178`); the entitlement probe uses `/range/5/minute/` (`entitlements.py:252-254`) |
| Pagination | the daily adapter **rejects** any response carrying `next_url` (`massive.py:186`); an intraday adapter must chunk by calendar (B9) | FACT |
| Bar size | **15 m**, not 5 m | FACT: `config/research.py:303`; `backtest_runner.py:180` default; the strategy's own guard `session_bar_count + time_stop_bars > 26 + or_bars` (`intraday_orb.py:97`) is written against a 26-bar session = 390 RTH min ÷ 15 |
| Session filter | ingest **RTH only** *and* filter in the loader (**B7**) | FACT as above |
| Ingest entry point | `ingest_intraday_symbol` / `ingest_intraday_universe` (`ingest.py:455-489`, `:527-542`) exist and write `OHLCVIntraday`; **the CLI does not expose a dated backfill** (B9) | FACT |
| Snapshot key | a **new, explicit** key `universe_24_ex_meta_intraday_15m` | FACT: `DataSnapshot` has **no bar-size or horizon column**; an unkeyed call matches any reusable snapshot on an exact symbol-set match (`promotion.py:331-337`), so an unkeyed intraday run on the 24 ex-META symbols would silently attach to **snapshot id 3** — the daily snapshot the two live approvals sit on. A distinct key with the same symbol set is accepted by the key branch (`:309-329`). Verify the key against both auto-generators (`universe_auto_*`, `:339`; `liquid_us_<date>_<digest>`, `screen.py:259`) |
| Concurrency | maintenance window, worker stopped | a live paper probation and a background worker run against `data/signalforge.sqlite`; a 0.3–1.6 M-row insert under a sticky write-intent session is exactly the contention the project's SQLite rules exist to avoid |

---

## 3. Pre-sealed evidence, with standard errors

All computations use **only** pre-sealed data (`2016-10-17 … 2025-09-07`, source
`massive`) or code arithmetic. `MAP.md` §0.3 supplies **no per-trade `sd` for
version 1** (it has never been evaluated past gate 0), so every `sd`-dependent result
is stated **as a function of `sd`** over the program's observed range 0.807–1.741
rather than invented. Proportions carry binomial SEs; a difference under 2 SE is not
evidence.

### 3.1 The regime gate and the bear bucket — corrected for `allow_short`

**FACT (recomputed independently for this document, in-process, read-only):**
`label_regimes(SPY)` (gate 6's labeller) crossed with `regime_lookup(SPY).risk_off`
(the strategy's own gate), pre-sealed span, source `massive`:

| gate-6 bucket | labelled sessions | **long-tradeable** (`not risk_off`) | **short-eligible** (`risk_off`) | long share ± SE |
|---|---|---|---|---|
| bull | 1,392 | 1,024 | 368 | 73.56 % ± 1.18 % |
| **bear** | **267** | **19** | **248** | **7.12 % ± 1.57 %** |
| range | 375 | 116 | 259 | 30.93 % ± 2.39 % |
| warmup (unbucketable, §0.6) | 200 | 178 | 22 | 89.00 % ± 2.21 % |

Cross-check: 267 bear-labelled sessions and 267/2,234 = 11.95 % reproduce
`v6_regime_power.md` exactly on an independently written computation. Bear sessions
are 13.13 % ± 0.75 % of the 2,034 **labelled** pre-sealed sessions. The 19
long-tradeable bear sessions are 3 in Oct–Nov 2020 and 16 in Feb–Jun 2023; none
after 2023-06-02.

**The correction (judge defects J1-1 / J2-1, both accepted).** `intraday_orb.py:105`
gates the **LONG** branch on `not ctx.regime.risk_off`; `intraday_orb.py:116` opens a
**SHORT** branch on `ctx.allow_short and close < or_lo and ctx.regime.risk_off`, and
`spec()` declares `permits_short=True` (`:75`). The ladder is long-only **only
because** `run_strategy_over_universe(..., allow_short: bool = False, ...)`
(`backtest_runner.py:176`) is never passed `allow_short` at `promotion.py:586`,
`promotion.py:386` or `sensitivity.py:148` — verified by reading all three call
sites. `ResearchConfig.allow_short_candidates` defaults to `False`
(`config/research.py:296`), is operator-togglable from the dashboard
(`app/routers/dashboard.py:332`, `app/templates/settings.html:40`) and **is** passed
on the live scan path (`research/scan.py:271`, `cli.py:903`) — so the ladder and the
live scanner do not agree on this flag.

**Pre-registered run configuration: `allow_short = False`**, matching the ladder's
current hard-wired behaviour and the config default. Enabling shorts is a
**variant** under R5 (it changes which trades exist, hence every gate), needs its own
pre-registration and its own budget line, and is raised as **Q6**.

### 3.2 History depth — forced by gate 6, and by which configuration

Sessions by gate-6 bucket as a function of pre-sealed start date. `label_regimes`
labels the first `TREND_LOOKBACK = 200` sessions `"warmup"` (`backtest/regime.py:20,
36-37`), so a later start swallows real regime sessions into the warmup hole.
**FACT (recomputed for this document at both pre-sealed ends, 2025-09-06 and
2025-09-07 — identical at every start date):**

| pre-sealed start | sessions | bull L / S | **bear L / S** | range L / S | warmup L / S |
|---|---|---|---|---|---|
| 2016-10-17 (parity with the daily program) | 2,234 | 1,024 / 368 | **19 / 248** | 116 / 259 | 178 / 22 |
| 2018-09-10 | 1,757 | 822 / 260 | **19 / 212** | 71 / 173 | 161 / 39 |
| 2019-09-09 | 1,507 | 707 / 208 | **19 / 167** | 65 / 141 | 95 / 105 |
| 2020-09-08 | 1,255 | 493 / 179 | **16 / 167** | 65 / 135 | 200 / 0 |
| 2021-09-08 | 1,003 | 400 / 115 | **16 / 123** | 62 / 87 | 94 / 106 |
| 2022-09-08 | 751 | 348 / 115 | **0 / 18** | 31 / 39 | 200 / 0 |
| 2023-09-08 | 500 | 139 / 100 | **0 / 18** | 4 / 39 | 177 / 23 |
| **2024-09-22** (shortest gate-0-legal span) | 239 | 39 / 0 | **0 / 0** | **0 / 0** | 108 / 92 |

L = long-tradeable (`not risk_off`), S = short-eligible (`risk_off`). Under
`allow_short=True` a bucket's usable supply is L + S, i.e. **every labelled session**.

**DERIVED, and this is the single hardest requirement in the document:**

- The **shortest span gate 0 will accept** is 716 calendar days
  (`sealed_start = end − 365`; `pre_sealed_end = sealed_start − 1`;
  `(pre_sealed_end − start).days ≥ MIN_PRESEALED_DAYS = ceil(200 × 365.25/252) + 60 =
  350` — `promotion.py:94`, `:556-559`). For `end = 2026-09-08` that is
  `start ≤ 2024-09-22`. At that start only **39 of 239** sessions are labelled and
  every one is `bull_*`: **bear = 0 and range = 0 under *both* configurations**, so
  gate 6 (`≥ 10 trades in each of 3 buckets`) is **arithmetically unreachable** no
  matter how good the strategy is. **Option A is dead under every configuration.**
- Under the pre-registered **long-only** configuration: any start on or after
  2022-09-08 yields **0** tradeable bear sessions; 2021-09-08 recovers 16;
  2019-09-09 or earlier recovers all 19. **Minimum viable depth: 2021-09.**
- Under `allow_short=True`: 2022-09-08 already yields 18 short-eligible bear
  sessions. **Minimum viable depth: 2022-09** — so the *configuration*, not the
  calendar, sets two of the three depth options apart.

**So the backfill must reach back to at least 2021-09 under the pre-registered
configuration, and to 2016-10 for parity with the daily program. "Two years of
intraday bars" is not a viable option under any configuration.**

### 3.3 Data volume, API budget and storage

DERIVED. Symbols = the 24 of snapshot 3 (`universe_24_ex_meta`, the only universe on
which gate 8 passes — `MAP.md` §0.1); RTH bars/session = 26 at 15 m, 78 at 5 m.

| Option | Span | Sessions/sym | 15 m RTH rows | API calls (yearly chunks × 24) | Paced wall-clock |
|---|---|---|---|---|---|
| **A** minimum legal (**dead**, §3.2) | 2024-09-22 → 2026-09-08 | 491 | 306,384 | 48 | 9.7 min |
| **B** minimum viable depth | 2021-09-08 → 2026-09-08 | 1,255 | 783,120 | 120 | 24.2 min |
| **C** parity with the daily program | 2016-10-17 → 2026-09-08 | 2,486 | 1,551,264 | 240 | **48.4 min** |

Basis: pacing 12.1 s/request (`massive.py:39-40 _MIN_REQUEST_SPACING_S = 12.1`;
Basic plan 5 req/min). Same order as W1's pre-registered daily build (126 calls /
~26 min, `w1_universe_preregistration.md`). Yearly chunking keeps every request under
the 50,000-row cap even with extended hours (252 × 192 = 48,384 at 5 m).

**Storage — one table, both conventions (judge defect J2-7).** FACT (measured,
`dbstat`, read-only): `ohlcv_daily` plus its five indexes occupy 355,749,888 B for
1,036,162 rows = **343 B/row**; the whole database is **381,739,008 B = 0.382 GB**;
`ohlcv_intraday` holds **0 rows**. `OHLCVIntraday` carries two extra short string
columns and a different index set, so ±20 % on the per-row figure.

| Variant | rows | **added** | **final file** | **final multiple** |
|---|---|---|---|---|
| B, 15 m, RTH only | 783,120 | 0.27 GB | 0.65 GB | **1.70×** |
| **C, 15 m, RTH only (recommended if proceeding)** | 1,551,264 | **0.53 GB** | **0.91 GB** | **2.39×** |
| C, 15 m, pre/post kept | 3,818,496 | 1.31 GB | 1.69 GB | 4.43× |
| C, 5 m, RTH only | 4,653,792 | 1.60 GB | 1.98 GB | 5.18× |

### 3.4 Compute cost of one promotion evaluation

FACT (measured by the proposal on synthetic in-memory series, no DB): `run_backtest`
with `signal_fn_for(IntradayORB())` on 15-minute bars is cleanly quadratic —
1,560 bars 0.06 s; 3,120 bars 0.24 s; 6,552 bars 1.03 s; 13,104 bars 4.11 s; fit
`t ≈ 2.394 × 10⁻⁸ · n²` s/symbol. Mechanism: `opening_range` rescans `range(t+1)`
(`features/intraday.py:39`) and `series.head(t)` copies the `dates` tuple
(`series.py:45`). **A second, independent replicate by the impact judge reproduced
the quadratic shape ~10 % faster at every point.** The figures below therefore carry
an explicit **±15 % hardware band** and are extrapolations from ≤ 13,104 bars up to
58,084, not measurements.

| Option | bar size | bars/symbol (pre-sealed) | one 24-symbol pass | one full 10-gate evaluation (1 + 9 grid + 1 sealed) |
|---|---|---|---|---|
| B | 15 m | 26,078 | 6.5 min (5.5–7.5) | **1.1 h** (0.9–1.3) |
| **C** | **15 m** | **58,084** | **32.3 min** (27–37) | **5.4 h** (4.6–6.2) |
| C | 5 m | 174,252 | 290.7 min | **48.5 h** |

Every re-evaluation, variant and sensitivity check pays this again. **B6 is a
prerequisite, not an optimisation.**

### 3.5 Entry-rate and trade-count scale (HYPOTHESIS, order of magnitude only)

FACT (code arithmetic, `intraday_orb.py:94, 97`): with `or_bars=3`,
`min_bars_before_entry=3`, `max_bars_after_open=20`, `time_stop_bars=12`, entries are
admissible only for `3 ≤ since_open ≤ 16` — a 14-bar window in a 26-bar session.
FACT (§A.2): `engine.py:150` sets `t = exit_idx + 1`, so **at most 2 trades per
symbol-session** are structurally possible.

**HYPOTHESIS, restated per judge defect J2-5.** The proposal's synthetic
geometric-random-walk estimate was 0.42 trades/symbol-session quoted with a
*sampling* SE of ±0.04; an independent replicate at σ = 15 bps/bar returned
0.633 / 0.692 / 0.766 / 0.764 at 60 / 120 / 252 / 504 sessions — 5–9 of those SEs
away. The dispersion is driven by the synthetic's volatility parameter, not by
sampling, so **the SE is withdrawn**. The pre-registered working bracket is

> **entry rate ∈ [0.4, 0.8] trades per symbol-session, hard ceiling 2, synthetic,
> not market data, to be replaced by a measurement on real bars before any gate
> forecast is relied upon.**

DERIVED at that bracket on option C, long-only (1,337 tradeable sessions × 24):
pre-sealed trades **12,800–25,700**; OOS (~40 %) **5,100–10,300**; bear-bucket trades
**182–365** (ceiling 912). Every count in §5 is **order-of-magnitude only**, and §5's
gate-6 conclusion is carried on the parameter-free threshold instead (§5).

---

## 4. Falsification — stated in advance, on all four snapshots (R10)

**Why most of these are snapshot-invariant, verified rather than asserted.** Gate 6's
labels and the strategy's regime gate both derive from the **SPY proxy alone**, which
is identical in all four snapshots (they differ only in `META` / `META_CONT` / its
absence). Recomputing §3.1/§3.2 at snapshot 1's pre-sealed end (2025-09-06) and at
snapshots 2–4's (2025-09-07) returns **identical** counts at every start date. F3,
F4 and F6 run over the *symbol set*, so they are stated explicitly for the 25-symbol
snapshots too (judge defect J1-8).

| # | Claim | What kills it (pre-sealed only) | Four-snapshot statement |
|---|---|---|---|
| **F1** | Under the pre-registered `allow_short=False` configuration, a pre-sealed span starting on/after 2022-09-08 has **zero long-tradeable bear sessions**, so gate 6 is unreachable at that depth | any snapshot on which that span yields ≥ 1 session that is `bear_*` under `label_regimes` **and** `not risk_off` under `regime_lookup` | Verified false on all four (SPY-proxy derived; identical at both pre-sealed ends). **Explicitly conditional:** under `allow_short=True` F1 is *already false* (18 short-eligible bear sessions) — that is a configuration change, not a falsification |
| **F1b** | The shortest gate-0-legal span (start 2024-09-22) has 0 bear **and** 0 range **labelled** sessions, so option A is dead under *every* configuration | ≥ 1 `bear_*` or `range_bound` label in that span on any snapshot | Verified false on all four |
| **F2** | Gate 6 returns `0/0/0` with 100 % unbucketed for **any** intraday run of the current promotion path | any intraday gate-6 evidence blob with a non-zero bucket before B2 is applied | Type-level (`datetime` key vs `date` key), so snapshot-independent by construction |
| **F3** | Cost is ≥ 0.1375R per round trip at the frozen 11.0 bps | measuring, after ingest, a **median λ·w > 0.80 % of price** — where λ = (entry_fill − or_lo)/w and *w* is the OR width — across the universe on the pre-sealed span | Stated for **all four**: snapshot 3's 24 symbols and the 25-symbol sets of snapshots 1/2/4 (adding one mega-cap to a 24-name median moves it by at most one rank position; the pre-sealed anchor median daily (H−L)/C = 1.579 % is computed on the 24 and must be recomputed on the 25 before F3 is scored there) |
| **F4** | One full 10-gate evaluation on option C at 15 m exceeds 2 h before B6 | a measured single 24-symbol pre-sealed pass completing in **under 40 % of the forecast for that hardware** (i.e. under ~13 min against a 32.3 min forecast) — stated as a ratio, not an absolute, because the forecast is hardware-dependent (J2-8) | Compute scales with symbol count: the 25-symbol snapshots cost 25/24 = 1.04× the 24-symbol figure; the ratio form is snapshot-invariant |
| **F5** | Live execution cannot reproduce the modelled fill on this entitlement | an entitlement probe recording `latency_category = REALTIME` for any equities feed, or adoption of a bar size strictly greater than the measured feed delay | Entitlement is a plan property, independent of snapshot |
| **F6** | The strategy's own regime gate, not the market, produces the bear shortfall | finding **< 10 trades across the universe on the 19 long-tradeable bear sessions** — which would move the diagnosis from "gate shut" to "no signal" and would **strengthen** the null option | Stated for all four: 19 sessions × 24 symbols (snapshot 3) and 19 × 25 (snapshots 1/2/4); the session set is proxy-derived and identical |
| **F7** *(new)* | Gate 4 is **not** an easy gate for this strategy once calendar clustering is admitted | measuring a session-block design effect `deff ≤ 1.2` on real intraday OOS trades (the program's daily strategies measure 2.55–4.86 at month blocks — `clustered_bootstrap_all.md` §3.1) | Diagnostic is computed per run; must be reported on whichever snapshot the run uses |
| **F8** *(new)* | No admissible evaluation of v0.1.0 exists, because the same-session regime read is a lookahead | a demonstration that `regime_by_date` for session *D* is derivable from information available at 10:15 on *D* (it is not: `regime_lookup` labels *D* from *D*'s daily bar) | Plumbing-level, snapshot-independent |

**If F1 *and* F1b both fell, the depth recommendation changes. If F3 falls, the §0
cost finding weakens materially and the recommendation changes. If F2, F4 or F7
falls, the corresponding bundle item or caveat is dropped. F5 and F8 are blocking:
neither is a research finding the pipeline can overturn.**

---

## 5. Gate-by-gate forecast

Trade sets tagged per `MAP.md` §0.2: gates 2/3/4 read `full.out_of_sample`
(`promotion.py:652`, `:679`); gates 1/6/7 read `full.trades` — **all** pre-sealed,
IS+OOS — including gate 7, whose docstring (`config/research.py:111-113`) contradicts
`promotion.py:775`. Forecasts assume the **full bundle** (§2.3) is applied, option C
data exists, and the run is `allow_short=False`. **Without the bundle every gate 1–7
reads 0 trades and fails** (verified).

| Gate | Trade set | Forecast | Confidence |
|---|---|---|---|
| **0** `data_availability` | — | **Pass only under option B or C**, and only after §2.2. Fails on option A by (e). Passes (a)–(d) only with a complete, RTH-only, `massive`-sourced, correctly-sized, fresh backfill | FACT (arithmetic) |
| **1** `rolling_walkforward` | all pre-sealed (12,800–25,700) | **Trade-count conjunct passes trivially** — ~3,200–6,400 per fold against a floor of 15 (`promotion.py:632`, the shared `sensitivity_min_grid_trades` constant). Whether 2 of 4 folds show `expectancy_r > 0` is the real test and is unforecastable | HYPOTHESIS |
| **2** `min_oos_trades` | OOS (5,100–10,300) | **Pass with enormous margin** (≥ 30). The only trivially satisfied gate | HYPOTHESIS on the rate; FACT on the mechanism |
| **3** `net_expectancy` | OOS | **Expected FAIL — the binding gate.** Requires gross edge above 0.14R–0.37R/trade at λ = 1 (§8). Break-even hit rate **45.5 %** at c = 0.1375R, **48.8 %** at 0.22R, **54.7 %** at 0.3667R, against a **40.0 %** random-walk baseline for a nominal 1.5:1 bracket — and the *realised* payoff ratio is strictly below 1.5 (target measured from the signal close, stop at `or_lo`, fill at the next open) | HYPOTHESIS; the cost half is FACT |
| **4** `bootstrap_ci` | OOS | **"Not power-limited" is WITHDRAWN (judge defect J2-2).** The hurdle is `exp > 0.02 + 1.96·sd·√deff/√n`, and the program's own diagnostic measures month-block `deff` of **2.55 / 3.04 / 4.86 / 2.60 / 2.66** for versions 2/3/4/5/6 (`clustered_bootstrap_all.md` §3.1), flipping gate 4 to FAIL for **both** currently PAPER_APPROVED strategies. An intraday ORB is the **most calendar-clustered trade set in the program** — up to 24 symbols entering inside the same 90-minute window of the same session. Effective independent units are ~1,337 pre-sealed sessions / ~535 OOS sessions (~108 / ~43 months), not 5,100–10,300 trades. At n = 5,400: **deff = 1** → hurdle +0.0415R (sd 0.807) to +0.0664R (sd 1.741); **deff = 2.5** → **+0.0540R to +0.0934R**; **deff = 4** → +0.0620R to +0.1126R. Required n = `deff·(1.96·sd/(exp − 0.02))²`. **Honest statement: gate 4's hurdle is unknown until a session-clustered `deff` is measured on real bars, and is structurally worse here than for any daily strategy** | DERIVED; `deff` is HYPOTHESIS (F7) |
| **5** `parameter_sensitivity` | OOS per grid point | **Automatic FAIL today** (`promotion.py:694-703`: `_sensitivity_plan` returns `None` for this prefix). With §6's grid, 9 cells × thousands of OOS trades — the 15-trade floor never binds; positivity is the open question. Cost: 9 extra full passes (§3.4) | FACT on the current failure |
| **6** `regime_coverage` | all pre-sealed | **FAIL today, unconditionally** (F2). After B2, long-only option C: unbucketed ≈ **178/1,337 = 13.3 % of tradeable sessions ≈ 1,700–3,400 trades** — the two coincide only if the per-session entry rate is uniform across warmup and labelled sessions, which is **assumed, not measured** (judge defect J2-6). Buckets ≈ bull 9,800–19,700, **bear 182–365**, range 1,110–2,230. Passes on option C or B; **arithmetically impossible on option A** | FACT on the mechanism; HYPOTHESIS on counts |
| **7** `benchmark_comparison` | all pre-sealed | **Unforecastable and, as constructed, not comparable.** `ann_factor = sqrt(trades_per_year)` (`portfolio_metrics.py:110`) at ~1,500–3,000 trades/yr against SPY buy-and-hold is a different construction on the two sides, and `exposure` would report a clamped 1.0 (`:119`) for a strategy flat overnight. B8 reports the corrected exposure as a diagnostic; the gate's construction is Q5, the operator's open item | FACT on the construction |
| **8** `data_quality_and_leakage` | — | **Passes vacuously and misleadingly today** — `validate_daily` (`promotion.py:808`) would validate the *daily* bars of the 24 symbols and say nothing about the intraday bars actually traded. Requires B3. The leakage half is clean for the three intraday features (§7) but **does not cover the regime plumbing**, which is where the real lookahead lives | FACT |
| **9** `sealed_final_test` | sealed year | **Not forecast, and not to be run on v0.1.0** (§A, F8). Needs ≥ 10 trades and expectancy ≥ 0R | — |
| **10** `live_paper_probation` | — | `health_monitor.enabled` is true, so the gate passes — **but a pass is meaningless for this horizon**: `approved_scope_scan.py:81` excludes INTRADAY (policy comment `:19-22`) and `alerts/dispatch.py:241` skips it, so no candidate and no alert could ever be produced. Note `ResearchConfig.enabled_horizons` *includes* INTRADAY (`config/research.py:297-302`) — the policy is inconsistent across surfaces (§A.2) | FACT |

**Zero-margin cases (§4.2 item 5), corrected for units (judge defect J1-7).** Neither
named case is touched: v6's gate-5 neighbour fraction (0.750 on snapshot 3, already
failing at 0.500 on snapshot 4) and v5's bear bucket (11 against a floor of 10)
belong to other versions and nothing here re-evaluates them. The **new** zero-margin
case is `intraday_orb`'s bear bucket, and it must be stated in both units:

- **In gate 6's own units (trades):** ~182–365 bear trades against a floor of 10 — a
  **18×–36× margin**, not zero margin.
- **The genuinely zero-margin quantity is the SESSION SUPPLY:** **19** long-tradeable
  bear sessions in nine pre-sealed years, the entire supply, zero after 2023-06-02,
  and zero at any start on or after 2022-09-08. The floor of 10 clears only if the
  realised entry rate exceeds **10 / (19 × 24) = 2.19 %** per symbol-session — a
  parameter-free threshold that does not depend on §3.5's synthetic bracket. **This
  is the form the gate-6 conclusion is carried on.**

**Two strategy-code defects found while forecasting (reported, not proposed).**
FACT: `intraday_orb.py:97` admits entries while `since_open ≤ 16`; in a 26-bar
session (bars 0–25) an entry at `since_open ∈ {14,15,16}` puts the 12-bar time stop
at bars 26–28 — **after the close** — and `_resolve_exit` (`engine.py:152-184`) has
no session-boundary awareness, so those positions are carried **overnight** with the
opposite OR edge as the stop, exposed to the gap. FACT:
`target_price = close + 1.5 × width` is measured from the signal *close* while the
stop is `or_lo` and the fill is the next bar's *open*, so the realised reward:risk is
`1.5w / (entry_fill − or_lo)`, below 1.5 whenever the fill is above `or_hi`. Both are
**out of scope here** (each is behavioural → `VERSION = "0.2.0"`), recorded so that a
future intraday design starts from them and so no one reads a gate-3 failure as a
pure cost effect.

---

## 6. Sensitivity-grid plan (gate 5)

§4.2 item 6 requires every parameter a change introduces to become a pre-registered
axis. This design introduces no parameter, so the requirement resolves to R4's
carve-out 1: **register the missing grid for a family that has none** — a genuine
±1-step neighbourhood around the shipped parameters, written down before any result
is seen.

**Pre-registered now, before any intraday bar exists** (`promotion.py:161-210`, a new
`key.startswith("intraday_orb")` branch returning a factory over `ORBParams`):

```
{"or_bars": [2, 3, 4], "target_range_mult": [1.25, 1.5, 1.75]}
```

Rationale, in advance: `or_bars` is the definitional parameter of an opening-range
breakout — it sets both the range and, via `26 + p.or_bars`, the entry-window guard
(`intraday_orb.py:97`); `target_range_mult` sets the payoff ratio that §5's
break-even hit rate turns on. **Coverage is 2 of 5 `ORBParams` fields** — the same
2-of-6-to-8 shortfall `MAP.md` §0.5 criticises, declared rather than hidden. The
three untested fields are `min_bars_before_entry`, `max_bars_after_open`,
`time_stop_bars`.

**Why no `stop_atr` axis (FACT):** every other family's grid pairs a signal axis with
`stop_atr`. `ORBParams` has no `stop_atr` — the stop is structural
(`stop_price = or_lo`). There is no risk-sizing axis to perturb, so this grid is
genuinely two signal axes.

**Mandatory pre-integration no-op check** (§4.2 item 6; `MAP.md` §2.1's silent
failure mode). Before the grid is used in any verdict, run the 3 × 3 grid and assert:
(i) the nine `(n_trades, expectancy_r)` pairs are **not all identical**;
(ii) `or_bars ∈ {2,4}` **changes `n_trades`** (it must — it changes both the range
definition and the entry-window guard); (iii) `target_range_mult ∈ {1.25,1.75}`
**changes `expectancy_r`**. A grid whose nine cells coincide passes gate 5 at 100 %
having tested nothing. **If any assertion fails, gate 5's result is void and must be
reported as void, not as a pass.**

**Coupling to disclose (`MAP.md` §4.3):** `sensitivity_min_grid_trades = 15`
(`config/research.py:106`) is **also** gate 1's per-fold floor (`promotion.py:632`).
Neither may change (R4); at this trade scale neither binds.

---

## 7. Leakage argument

**Point-in-time contract.** All three intraday features read `(series, t)` with
slices ≤ *t*: `bars_since_open` walks backwards from *t* (`features/intraday.py:28-32`);
`opening_range` enumerates `range(t + 1)` (`:39`); `session_bar_count` delegates to
`bars_since_open` (`:52-54`). **FACT (verified in-process by the proposal on a
synthetic 40-session 15 m series):** `assert_no_lookahead`
(`backtest/leakage.py:23-41`) reports **clean** for `opening_range(...)[0]`,
`opening_range(...)[1]`, `bars_since_open` and `session_bar_count`. That is the check
gate 8 would run under **B4**; the ladder does not run it today
(`promotion.py:249-267` checks four daily features on the daily proxy only).

**The blocking lookahead — and why it settles the variant budget.** `regime_lookup`
labels a session from **that session's daily bar**, whose close is not known while
the session is being traded. For a *daily* strategy this is harmless (signal at bar
*t*'s close, fill at *t+1*'s open → the regime is strictly past). For an **intraday**
strategy trading inside session *D*, `ctx.regime` for *D* is derived from *D*'s own
close — **future information relative to a 10:15 entry**. The plumbing is
`backtest_runner.py:183-185` (`regimes = regime_lookup(proxy)`, keyed by date) and
`strategies/base.py:39-40` (the intraday stamp is normalised to its own session
date). `assert_no_lookahead` cannot catch it: it lives in the `regime_by_date`
plumbing, not in a feature function.

**Requirement:** an intraday run must lag the regime by one session (use *D−1*'s
label). **This is behavioural and therefore requires `VERSION = "0.2.0"` (R3/R7).**
Consequently — and this is the resolution of judge defect J1-2 — **no promotion
evaluation of v0.1.0 may be run**, because gate 9 would lock version 1's first-ever
sealed test against a rule set known to read the future. The first evaluable artifact
is a v0.2.0 with its own §4.2 design document and its own budget.

**Gate 6 is not part of this lookahead** (see §2.3's reconciliation): it buckets
descriptively on *D*, after the fact, and buckets no trade the strategy did not
already take.

**Session grouping by UTC date** (§2.4, B7): RTH-only ingest **and** a loader filter,
or `_session_date` (`features/intraday.py:19-21`) mis-assigns EST post-market bars to
the following session and corrupts its opening range.

**No new cross-sectional or breadth term is introduced**, so no new
`StrategyContext` plumbing (`strategies/base.py:15-19`) and no shared-surface change.

---

## 8. Cost-model statement (quantitative)

**The cost model is unchanged (R4).** FACT: `backtest/costs.py:11-16` —
`commission_per_share = 0.0`, `commission_min_per_order = 0.0`, `slippage_bps = 3.0`,
`half_spread_fill_penalty = True`. FACT: `engine.py:90` `spread_bps: float = 5.0`;
`engine.py:94` `slip = (3.0 + 5.0/2)/10,000 = 5.5 bps` per side; `engine.py:144`
`costs_bps = slip × 2 × 10,000 = 11.0 bps` per round trip. FACT:
`backtest_runner.py:205-206` never passes `spread_bps`, so the 5.0 bps assumption is
universe- **and horizon**-independent.

**Per-trade cost in R, with the overshoot factor (judge defect J2-3, accepted with a
correction).** `engine.py:110` defines `risk_per_share = |entry_fill − stop_price|`
and the stop is the opposite OR edge, so the risk unit is `entry_fill − or_lo`, not
the OR width itself. Define

> **λ = (entry_fill − or_lo) / w**, where *w* is the OR width as a fraction of price;
> **cost_R = (round_trip_bps / 10,000) / (λ · w)**.

**Correction to the judge:** λ ≥ 1 is **not** guaranteed by construction. The signal
requires `close > or_hi`, but the fill is the *next bar's open* (`engine.py:107-109`,
plus slippage), which can print back inside the range. λ ≥ 1 holds *typically*, not
strictly. The table below is therefore the **λ = 1 reference**, i.e. an **upper bound
on cost in the typical case**:

| OR width `w` (% of price) | @ 11.0 bps (today) | @ 26 bps (20 bps quoted) | @ 36 bps | @ 66 bps |
|---|---|---|---|---|
| 0.20 % | **0.5500R** | 1.3000R | 1.8000R | 3.3000R |
| 0.30 % | **0.3667R** | 0.8667R | 1.2000R | 2.2000R |
| 0.50 % | **0.2200R** | 0.5200R | 0.7200R | 1.3200R |
| 0.80 % | **0.1375R** | 0.3250R | 0.4500R | 0.8250R |
| 1.20 % | **0.0917R** | 0.2167R | 0.3000R | 0.5500R |

At λ = 1.3 and *w* = 0.50 %, cost falls from 0.2200R to **0.1692R** — λ matters as
much as *w*, and **both must be measured post-ingest**. F3's kill test is therefore
stated on the **product λ·w**, not on *w* alone.

Formula sanity check against the map: `trend_continuation` at `stop_atr = 1.5`,
`ATR/price = 2 %` gives `risk/price = 3 %` and `0.0011/0.03 = 0.0367R`, matching
`MAP.md` §0.4's 0.037R exactly.

**Pre-sealed anchor for *w* (FACT, read-only):** across the 24 snapshot-3 symbols on
`2016-10-17 … 2025-09-07`, mean daily `(H − L)/C` has median **1.579 %** (min 1.090 %
DIA, max 3.663 % NVDA). HYPOTHESIS: a 45-minute opening range captures roughly
30–45 % of the day's range, putting *w* ≈ 0.5–0.7 %. **This fraction is not verified
anywhere in this repo**; measuring λ and *w* is item 1 of the post-ingest diagnostic.

**Comparison to the rest of the program (DERIVED, corrected — judge defects J1-6 /
J2-4).** At λ = 1 and *w* ∈ [0.30 %, 0.80 %], cost is 0.3667R–0.1375R, i.e.
**3.3×–8.7×** `volatility_breakout`'s 0.042R (the program's most expensive, already
"68 % of its entire edge" per `MAP.md` §0.4) and **6.3×–16.7×** `relative_strength`'s
0.022R (the cheapest). At the *w* = 0.50 % point estimate specifically: **5.2×**
volatility_breakout, **5.9×** trend_continuation (0.037R), **10.0×**
relative_strength. The proposal's "4–10× any daily strategy" is not the minimum or
maximum of any consistent comparison and is **withdrawn**.

**Turnover delta.** This design changes no rule, so the delta versus v0.1.0 is
**zero by construction**. In absolute terms, DERIVED at §3.5's bracket: 12,800–25,700
pre-sealed trades against v2's 1,169 (`MAP.md` §0.6) — **11×–22×** the busiest
strategy in the program, so any cost error is amplified by that factor at the
portfolio level.

**Break-even hit rate (DERIVED).** With a nominal 1.5R target and a 1R stop, net
expectancy `p·1.5 − (1−p)·1 − c > 0` requires `p > (1 + c)/2.5`: **45.5 %** at
c = 0.1375R, **46.8 %** at 0.169R (λ = 1.3, *w* = 0.5 %), **48.8 %** at 0.22R,
**54.7 %** at 0.3667R, **62.0 %** at 0.55R. The random-walk baseline for a 1.5:1
bracket is **40.0 %**, and §5 notes the realised payoff ratio is strictly below 1.5,
which raises every figure above.

**Expanded-snapshot requirement (§4.2 item 8).** Not applicable — this design uses
snapshot 3's 24-symbol set and does not run on an expanded universe. Should an
intraday run ever be attempted on an expanded snapshot, the 2× (26 bps) and 5×
(66 bps) columns above are **pre-registered as mandatory**, and the 5× column puts
cost above **1R per round trip** for *w* ≤ 0.5 %.

**Unmeasurable-spread caveat (FACT).** NBBO quotes return `403 not_authorized`
(`reports/SUBSCRIPTION_STATUS.md:17`) and `universe/screen.py` flags every symbol
`F_SPREAD = "spread_filter_not_licensed"`. **The true opening-auction spread cannot
be measured on this plan at all**, so the 5.0 bps assumption can be neither validated
nor calibrated for the one time of day this strategy trades.

---

## 9. Variant budget and stopping rule (whole strategy, all angles)

**Strategy variants: 0. Promotion evaluations: 0. Sealed looks: 0.**

Recorded verbatim for the final report (R5):

> *`intraday_orb.intraday` — design phase: **1** angle (requirements), **0** strategy
> variants tried, **0** pre-sealed backtests of a modified rule set, **0** promotion
> evaluations run, **0** sealed looks consumed. The strategy's sealed-look count
> stays at 0; the program's stays at k = 5.*

**Corrected from the proposal (judge defect J1-2):** the proposal budgeted "full
promotion evaluations of the unchanged v0.1.0: 1". That is **withdrawn**. §7
establishes that v0.1.0 reads future information on an intraday run, so no evaluation
of it is admissible; the first evaluable artifact is a v0.2.0 carrying the
regime lag, and a v0.2.0 is a **new design document with its own budget**, not a line
in this one.

**Conditional budget, pre-registered, applicable only if the operator answers Q1
"yes" and authorises a v0.2.0 design:**

| Item | Budget | Stopping rule |
|---|---|---|
| Bar size | **1** (15 m) | fixed in advance by `config/research.py:303` and the 26-bar guard at `intraday_orb.py:97`. **5 m may not be tried** as an alternative — it would be a bar-size search over the same sealed calendar year, a variant in disguise, at 9× the compute (§3.4) |
| History depth | **1** (option C, 2016-10-17) | chosen in advance by §3.2's arithmetic, not by results. Option B if the budget forbids C — a **cost** decision taken before any run. Option A is excluded by F1b |
| Run configuration | **1** (`allow_short = False`) | matches the ladder's hard-wired behaviour and the config default. Enabling shorts is a **separate pre-registered variant** requiring its own budget line and an operator decision (Q6) |
| Gate-5 grid | **1** (§6) | fixed before any intraday bar exists; void if the no-op check fails |
| Promotion evaluations of **v0.1.0** | **0** | inadmissible (§7, F8) |
| Promotion evaluations of a future **v0.2.0** | **budgeted in that document, not here** | — |

**Hard stop.** If any of **F1b, F4, F5 or F8** holds at decision time — and F1b, F5
and F8 all hold today — the work stops **before ingestion** and the null option is
taken. The most expensive failure mode available is spending ~48 min of API budget,
0.53 GB in a live database and ~5.4 h of compute per evaluation to reach a gate-3
failure that §8's arithmetic already forecasts.

---

## 10. Sealed-look accounting

**Reproduction of the `MAP.md` §0.1 ledger (FACT, re-queried read-only for this
document: `strategy_sealed_test` has **20** rows — exactly 4 each for versions 2–6,
and **none** for version 1):**

| Ver | Strategy | snap 1 `universe_25_baseline_legacy` | snap 2 `universe_25_baseline` | snap 3 `universe_24_ex_meta` | snap 4 `universe_25_meta_continuity_corrected` |
|---|---|---|---|---|---|
| 2 | `trend_continuation.short_swing` | id 1: +0.3246R / 112 ✅ | id 6: +0.3246R / 112 ✅ | id 11: +0.2982R / 109 ✅ | id 16: +0.3246R / 112 ✅ |
| 3 | `trend_continuation.medium_swing` | id 2: +0.0109R / 98 ✅ | id 7: +0.0109R / 98 ✅ | id 12: −0.0294R / 95 ❌ | id 17: +0.0109R / 98 ✅ |
| 4 | `mean_reversion.short_swing` | id 3: +0.1230R / 91 ✅ | id 8: +0.1230R / 91 ✅ | id 13: +0.1278R / 84 ✅ | id 18: +0.1230R / 91 ✅ |
| 5 | `relative_strength.medium_swing` | id 4: +0.2935R / 16 ✅ | id 9: +0.2935R / 16 ✅ | id 14: +0.2935R / 16 ✅ | id 19: +0.2935R / 16 ✅ |
| 6 | `volatility_breakout.short_swing` | id 5: −0.0979R / 10 ❌ | id 10: −0.0979R / 10 ❌ | id 15: −0.0979R / 10 ❌ | id 20: −0.0979R / 10 ❌ |
| **1** | **`intraday_orb.intraday`** | **— none** | **— none** | **— none** | **— none** |

**The map contradicts itself on *k*, and this report flags it (judge defect J1-10).**
`STRATEGY_COMPLETION_MAP.md:69` ("A v0.2.0 that seals against snapshot 3 is the
**fifth** look") and `:341` ("**A v0.2.0 sealing against snapshot 3 is look 5**")
disagree with `:1321-1322` ("the baseline count is **k = 5** … so a first v0.2.0
sealing on snapshot 3 is **look 6**"). **Convention adopted here, and stated so it
can be checked:** `k = 5` is the baseline count and the next sealed draw is **look
6** — the §4.2-item-10 form, which is also the form my task brief fixes.

**The parenthetical the map attaches to k = 5 is false for this family, and is
corrected rather than repeated.** "Four existing locked sealed draws per strategy
family plus the next one" is a category error for version 1, which verifiably has
**zero**. For `intraday_orb` the accounting is therefore stated **twice, always
together**: the program-wide count, and version 1's own.

**Version 1's position (FACT, queried):** zero rows in `strategy_sealed_test` — the
reason there are 20 rows and not 24. **Seven** promotion evaluations, ids
**1, 7, 13, 19, 25, 31, 37** on snapshots 1, 1, 2, 3, 2, 3, 4, every one with
`passed = 0` and the verdict *"NO TRADE — insufficient evidence or poor risk/reward"*,
all stopped at gate 0 before any sealed window was opened.

**What this design costs in looks: zero.** No evaluation, no new `StrategyVersion`,
no run that could reach gate 9. `intraday_orb` stays at **0**; the program stays at
**k = 5**.

**Pre-registered accounting for any future intraday evaluation:**

- The **first** admissible evaluation is of a **v0.2.0** (regime lag, §7) on the new
  keyed snapshot `universe_24_ex_meta_intraday_15m`. If it reaches gate 9 it creates
  `strategy_sealed_test` row **21** — **version 1's first sealed look ever** —
  disclosed **simultaneously** as **program look 6** (k = 5 + 1) and as **version 1's
  own look 1**. Both numbers must appear in the report.
- A subsequent v0.3.0 on the same snapshot would be program look 7 / family look 2; a
  v0.2.0 evaluated on both the intraday snapshot and an expanded snapshot would be
  looks 7 and 8 / family looks 1 and 2.
- **Snapshot the report will lead with, pre-registered (R1):**
  **`universe_24_ex_meta_intraday_15m`** — because its symbol set is snapshot 3's, the
  only symbol set on which gate 8 `validate_daily` passes (`MAP.md` §0.1), and because
  no other intraday snapshot exists or may be created. The four daily draws above are
  disclosed alongside it in every case, together with the explicit statement that
  version 1 contributes **none** of them.
- **R3 trap check.** No strategy code changes here, so `upsert_strategy_version`
  (`persistence.py:46-93`) refreshing `spec_json`/`git_sha` on the same row cannot
  produce a stale-sealed-test pass. Any future behavioural change — the regime lag
  (§7), the time-stop leash and the target/stop asymmetry (§5) — ships as
  `VERSION = "0.2.0"` with the `MAP.md` §4.3 pre-integration check that the new sealed
  test's `strategy_version_id` is a row created by **that** run.

---

## 11. Null option

**The null option is the recommendation, not the fallback.**

**What gets written:** a documented, evidence-backed **"DOES NOT OPERATE"** record for
`intraday_orb.intraday` v0.1.0 — the second of the two honest end-states
`STRATEGY_COMPLETION_PLAN.md` allows, and **distinct** from the "does not pass"
records v3, v4 and v6 may earn. The distinction matters: those three can fail on
*evidence*; version 1 has never been measured and, under today's entitlements, cannot
be measured in a way that would mean anything. Its record is a **capability finding**
and must not be filed as though the rules had been tested and found wanting.

**Evidence it carries (all pre-sealed or code arithmetic, all reproducible
read-only):**

1. The three independent blocks of `MAP.md` §2.4, with the R4 correction: the
   promotion-path gate is removable in principle (§2.2); the EOD-only operating
   policy (`approved_scope_scan.py:81` and its `:19-22` comment;
   `alerts/dispatch.py:241`) and the absent data path (`massive.py:86-100` declares
   only `BAR_DAILY`) are not. **Plus a fourth policy surface the map does not name:**
   `ResearchConfig.enabled_horizons` *includes* INTRADAY (`config/research.py:297-302`),
   so the policy is inconsistent across surfaces.
2. **A fourth block: latency.** The entitled feed is `DELAYED` ≥ 15 min against a
   15-minute bar; the modelled fill (bar *t+1*'s open) precedes the earliest
   attainable action (bar *t+2*'s open) by exactly one bar, permanently; no `REALTIME`
   equities feed exists on this plan (§0.1).
3. **A fifth block: cost.** 0.14R–0.37R per round trip at λ = 1 and the frozen,
   optimistic 11.0 bps — **3.3×–8.7×** `volatility_breakout` and **6.3×–16.7×**
   `relative_strength` — against a nominal 1.5:1 payoff whose break-even hit rate is
   45.5 %–54.7 % versus a 40.0 % random-walk baseline, with the realised payoff ratio
   strictly below 1.5 (§8, §5).
4. **A sixth block: a blocking lookahead.** The same-session regime read (§7) makes
   even a fully-built pipeline unable to evaluate v0.1.0 honestly. It cannot be fixed
   without a v0.2.0, and a v0.2.0 is a fresh design with a fresh budget.
5. The measured build cost of finding out anyway: 240 paced API calls / ~48 min,
   +0.53 GB on a live 0.382 GB database (2.39× the file), and ~5.4 h (4.6–6.2 h) of
   compute per evaluation before the `O(n²)` fix (§3.3, §3.4).
6. The gate-6 supply ceiling: **19** long-tradeable bear sessions in nine pre-sealed
   years (7.12 % ± 1.57 %), none after 2023-06-02, none at any start on or after
   2022-09-08 — and **0 bear and 0 range labelled sessions** at the shortest
   gate-0-legal start under *every* configuration (F1b).
7. The **ten** promotion-path defects B1–B10 (§2.3) that must be fixed before any
   intraday number from this pipeline means anything, plus the two behavioural
   defects (§5) that would each force a v0.2.0.
8. The honest gate-4 statement: with a month-block `deff` of 2.55–4.86 already
   measured for the program's daily strategies (`clustered_bootstrap_all.md`), an
   intraday ORB's effective *n* is session-count, not trade-count, and gate 4 is
   **not** the easy gate the proposal claimed.

**Sealed-window use in this section, marked per R1 (disposition — permitted):** the
sealed year plays no part in the argument above. `intraday_orb` has **no** sealed test
to cite, and that absence *is* the disposition fact — nothing in this program's sealed
evidence has ever bound on this strategy, so declining to build the pipeline forfeits
no measured edge.

**Status the record carries:** `EXPERIMENTAL`, unchanged. No downgrade, no approval,
no deletion, no database change. `Strategy` id 1 stays as it is. **The record is a
document, not a database write.**

**Re-entry condition, pre-registered.** All three, together:
(i) a **real-time** (not `DELAYED`) U.S. equities entitlement verified by
`data/entitlements.py`; (ii) a **measured** effective opening-auction spread for the
universe (today blocked by the NBBO `403`); (iii) an **operator decision** to change
the EOD-only policy. Absent all three the answer is stable and **should not be
revisited per quarter**.

---

## 12. Pre-registration block (consolidated, before any run)

Everything in this section is fixed **now**, before any intraday bar exists.

### 12.1 Gate-5 axes
`{"or_bars": [2, 3, 4], "target_range_mult": [1.25, 1.5, 1.75]}` — §6. Coverage 2 of
5 `ORBParams` fields, declared. No `stop_atr` axis exists. Void unless the three no-op
assertions in §6 hold.

### 12.2 Run configuration
Bar size **15 m**; source **`massive`**; `session == "rth"`; symbols = snapshot 3's
24; snapshot key **`universe_24_ex_meta_intraday_15m`** (explicit, never unkeyed);
**`allow_short = False`**; history **option C** (2016-10-17), or **option B**
(2021-09-08) if the API/storage budget forbids C; cost model unchanged (11.0 bps).

### 12.3 Falsification criteria
F1, F1b, F2, F3, F4, F5, F6, F7, F8 — §4, each with its four-snapshot statement.

### 12.4 Variant budget and stopping rule (whole strategy)
0 strategy variants / 0 evaluations / 0 sealed looks in this design; conditional
budget of 1 bar size, 1 depth, 1 configuration, 1 grid and 0 v0.1.0 evaluations if
Q1 is answered yes — §9. Hard stop on F1b, F4, F5 or F8.

### 12.5 Lead snapshot (R1)
`universe_24_ex_meta_intraday_15m`, with all four daily draws disclosed alongside and
the fact that version 1 contributes none of them stated explicitly — §10.

### 12.6 Sealed-look accounting
Baseline **k = 5** (program convention; map self-contradiction flagged in §10). This
design adds **0** looks. The first admissible future evaluation (a v0.2.0) would be
**program look 6 and version 1's own look 1**, both stated together.

### 12.7 Post-ingest diagnostics that must run before any gate is scored
1. median **λ·w** and its distribution across the universe (F3 — the single input the
   whole cost argument turns on);
2. measured **entry rate** per symbol-session, replacing §3.5's synthetic bracket;
3. measured **session-block `deff`** on OOS trades (F7), reported alongside gate 4's
   iid CI as a diagnostic (explicitly permitted by R4: "adding a stricter reported
   statistic is never a weakening");
4. measured single-pass wall clock, to score F4 as a ratio;
5. count of trades on the 19 long-tradeable bear sessions (F6).

---

## 13. Implementation checklist (only if the operator authorises)

### 13.1 Files to change

| File | Change | Item |
|---|---|---|
| `src/signalforge/data/adapters/massive.py` | `fetch_intraday_bars` + `BAR_INTRADAY`/`DELAYED` capability + calendar chunking | §2.4, B9 |
| `src/signalforge/data/series.py` | `load_intraday` filters `session == "rth"` | **B7** |
| `src/signalforge/data/validate.py` | `validate_intraday` | **B3** |
| `src/signalforge/research/features/intraday.py` | per-session index cache (behaviour-identical) | **B6** |
| `src/signalforge/research/promotion.py` | gate 0 real query + fall-through (§2.2); thread `intraday`/`bar_size` at `:586` and `:386` (**B1**); `_as_date` at `:744` (**B2**); intraday features in `_leakage_self_check` (**B4**); `intraday_orb` branch in `_sensitivity_plan` (**B5**); horizon dispatch at gate 8 (**B3**) | B1–B5 |
| `src/signalforge/research/sensitivity.py` | thread `intraday`/`bar_size` at `:148` | **B1** |
| `src/signalforge/research/portfolio_metrics.py` | horizon-aware `exposure_days` **as a diagnostic only** | **B8** |
| `src/signalforge/cli.py` | `ingest-intraday --since/--until`; `evaluate-promotion --dataset-key` | **B9, B10** |
| `src/signalforge/research/strategies/intraday_orb.py` | **NOT in this scope** — the regime lag is a v0.2.0 with its own design document | §7 |

### 13.2 Tests to add

- `tests/data/test_series_intraday_session.py` — `load_intraday` drops `pre`/`post`
  rows (B7); an EST post-market bar does not leak into the next session's opening
  range.
- `tests/data/test_validate_intraday.py` — session completeness, bars-per-session
  (26 full / 14 half-day), duplicate `bar_start`, non-positive prices,
  `source`/`bar_size`/`session` purity (B3).
- `tests/research/test_promotion_intraday_gate0.py` — gate 0 fails on: no rows;
  partial coverage; wrong bar size; `is_simulated=True`; wrong source; a non-RTH row;
  a stale latest bar; and a span shorter than `MIN_PRESEALED_DAYS` (the fall-through,
  §2.2 (e)).
- `tests/research/test_promotion_intraday_gate6.py` — with `datetime` entry stamps,
  buckets are non-zero after `_as_date` and `0/0/0` before it (B2, F2).
- `tests/research/test_sensitivity_intraday_grid.py` — the `intraday_orb` branch
  returns a 3 × 3 grid; **the no-op assertions of §6** (nine cells not identical;
  `or_bars` moves `n_trades`; `target_range_mult` moves `expectancy_r`).
- `tests/research/test_intraday_features_perf.py` — B6 produces **byte-identical
  trades** to the pre-optimisation path on a fixture series, and is sub-quadratic.
- `tests/data/test_massive_intraday.py` — capability declaration, pacing, calendar
  chunking, `next_url` handling.
- `tests/research/test_approved_scope_intraday_unchanged.py` — `approved_horizons`
  still excludes INTRADAY and `dispatch` still skips it (the policy must not drift as
  a side effect of research plumbing).

### 13.3 Three pre-integration guards (each must be a test, not a habit)

1. **No-op grid check (§6).** Assert the nine `(n_trades, expectancy_r)` pairs are not
   all identical and that each axis moves its named statistic. If it fails, gate 5's
   result is **void**, reported as void.
2. **Sealed-test staleness guard (`MAP.md` §4.3, R3).** After any evaluation, assert
   `StrategySealedTest.strategy_version_id` refers to a `StrategyVersion` row created
   by **this** run, and that the run's `git_sha`/`spec_json` match the code under
   test. `upsert_strategy_version` (`persistence.py:46-93`) refreshes those fields on
   the **same row** when `version` is unchanged, which would silently replay an old
   sealed result against new code.
3. **Spec-hash non-disturbance (R7 / R7b).** Before and after the change, assert
   `approval_scope.current_spec_json_hash()` is **unchanged** for v2
   (`trend_continuation.short_swing`) and v5 (`relative_strength.medium_swing`), and
   re-record that each still has exactly two passing evaluations, both on snapshot 3
   → sealed tests **11** and **14**, so `paper_probation.py:113-122`'s `scopes[0]`
   selection stays deterministic. Any new passing evaluation on a different snapshot
   activates the ordering hazard.

### 13.4 Exact validation commands — **SCRATCH database only**

A live paper probation and a background worker run against
`data/signalforge.sqlite`. Nothing below may touch it.

```bash
cd /Users/louisbrailey/signal-forge

# 0. Scratch copy (the ONLY database any writing command may see).
cp data/signalforge.sqlite "$TMPDIR/scratch-intraday-orb.sqlite"
export DATABASE_URL="sqlite+pysqlite:///$TMPDIR/scratch-intraday-orb.sqlite"

# 1. Repo gates, before anything else.
make lint
make test
make secrets          # check-only; never rewrite .secrets.baseline
make safety           # S1-S10 invariants

# 2. Targeted suites for the bundle.
.venv/bin/python -m pytest -q \
  tests/data/test_series_intraday_session.py \
  tests/data/test_validate_intraday.py \
  tests/data/test_massive_intraday.py \
  tests/research/test_promotion_intraday_gate0.py \
  tests/research/test_promotion_intraday_gate6.py \
  tests/research/test_sensitivity_intraday_grid.py \
  tests/research/test_intraday_features_perf.py \
  tests/research/test_approved_scope_intraday_unchanged.py

# 3. Gate 0 must STILL FAIL on the scratch DB before any ingest
#    (0 rows in ohlcv_intraday -> condition (a) fails). This is the
#    regression that proves the new query is not a fabricated pass.
.venv/bin/signalforge evaluate-promotion --strategy intraday_orb \
  --dataset ex_meta --since 2016-10-17 --until 2026-09-08

# 4. Backfill into the SCRATCH database only (operator-authorised, paced,
#    ~240 calls / ~48 min). Requires B9.
.venv/bin/signalforge ingest-intraday --bar-size 15m \
  --since 2016-10-17 --until 2026-09-08 \
  --symbols "$(.venv/bin/python -c 'from signalforge.config import get_settings; print(",".join(get_settings().research.universe))')"

# 5. Post-ingest diagnostics (§12.7) BEFORE any gate is scored.
.venv/bin/python scripts/intraday_orb_diagnostics.py   # lambda*w, entry rate, deff, wall clock, bear-session trades

# 6. The keyed snapshot + single evaluation (requires B10; in-process because
#    the CLI's --dataset accepts three fixed names only).
.venv/bin/python scripts/evaluate_intraday_orb.py \
  --dataset-key universe_24_ex_meta_intraday_15m \
  --since 2016-10-17 --until 2026-09-08

# 7. Guards.
.venv/bin/python scripts/check_spec_hash_unchanged.py   # R7/R7b, §13.3 item 3
.venv/bin/python scripts/check_sealed_test_freshness.py # R3,    §13.3 item 2

# 8. Confirm the live database was never touched.
shasum -a 256 data/signalforge.sqlite   # compare against the value taken at step 0
```

**Step 6 is only ever run against a v0.2.0 (§7).** Running it against v0.1.0 is
forbidden by this pre-registration.

---

## 14. What the operator must approve, and what is reported if it fails

### 14.1 Approvals required before any implementation

| # | Approval | Why it is the operator's, not research's |
|---|---|---|
| **A1** | **Buy a real-time U.S. equities entitlement** (Q1) | Without it the modelled fill is unattainable (§0.1, F5) and every number produced is about a strategy that cannot be traded. This is a spend decision. |
| **A2** | **Change the EOD-only operating policy** (Q1) | `approved_scope_scan.py:19-22, :81` and `alerts/dispatch.py:241` enforce it structurally; `ResearchConfig.enabled_horizons` contradicts them. These are policy surfaces, explicitly out of scope for this program (`MAP.md` §2.4). |
| **A3** | **~240 paced provider API calls / ~48 min of quota** (the W1-equivalent sign-off) | An external, metered resource. Option B is 120 calls / ~24 min. |
| **A4** | **+0.53 GB in the operational database, or a sidecar** (Q4) | Grows a live 0.382 GB file to 0.91 GB (2.39×) and needs a maintenance window with the worker stopped. |
| **A5** | **Authorise a v0.2.0 design** for the regime lag (and optionally the leash/target defects) | The only admissible evaluable artifact (§7). It is a new design document with its own variant budget under R5. |
| **A6** | **Decide `allow_short`** (Q6) | It changes the gate-6 bear supply from 19 to 267 sessions and is a variant under R5. |
| **A7** | **Resolve gate 7's docstring/code divergence** (Q5) | `config/research.py:111-113` says OOS; `promotion.py:775` computes all pre-sealed. An intraday run at 1,500–3,000 trades/yr makes the Sharpe annualisation far more consequential than for a 100-trade/yr swing strategy. |

Absent **A1 and A2**, the answer to Q1 is no and §11 is the outcome. **A3–A7 are not
reached.**

### 14.2 What is reported if it proceeds and fails

The failure is pre-classified so the report cannot be reshaped after the fact:

- **Fails at gate 0** → the backfill is incomplete. Report which of §2.2 (a)–(e)
  failed, per symbol. **Not** a strategy finding. Fix the data or stop; **do not
  relax (b), (c) or (d)** — they are frozen (§2.2).
- **Fails at gate 3** (the forecast outcome) → report the measured **λ·w** and the
  measured cost in R beside the §8 forecast, the realised payoff ratio against the
  nominal 1.5, and the realised hit rate against the break-even table. Verdict:
  **"does not pass — the frozen cost model exceeds the measured gross edge"**, filed
  as an *evidence* failure (unlike §11's capability failure) and stated as
  **program look 6 / version 1's own look 1** if gate 9 was reached.
- **Fails at gate 4 only** → report the iid CI **and** the session-block `deff` and
  clustered CI side by side (F7), and state plainly that the iid gate is the one the
  ladder scores and the clustered one is the honest statistic.
- **Fails at gate 6** → report the three buckets, the **unbucketed trade count**, the
  19-session supply, and the 2.19 %-per-symbol-session threshold. Say explicitly
  whether the shortfall is supply (calendar) or rate (signal) — F6 decides it.
- **Gate 5 void** (no-op check fails) → report the gate as **void**, never as a pass,
  and do not score the evaluation.
- **Passes every gate** → it is still **not operable**: report the pass, then report
  that `approved_scope_scan.py:81` and `alerts/dispatch.py:241` would refuse to scan
  or alert on it, and that the modelled fill is one bar earlier than the entitlement
  permits. A pass here is a research result, not a deployment.

In every branch the report states: **k = 5 baseline**, the look number in both
conventions, the variant count from §9 verbatim, the lead snapshot from §12.5, and
the fact that the same-session regime lookahead forced a v0.2.0.

---

## Operator questions

**Q1 (decisive) — do you want intraday operation at all, given that the policy is
currently also an entitlement fact?** EOD-only is enforced structurally in three
places (`approved_scope_scan.py:81`, `alerts/dispatch.py:241`, `MassiveAdapter`'s
hard-wired `END_OF_DAY`) and contradicted in a fourth (`enabled_horizons`). Relaxing
the policy does **not** make intraday operable, because the entitled feed is
`DELAYED` ≥ 15 min against a 15-minute bar. The real question is *"will you buy a
real-time equities entitlement?"* — and until that is yes, the honest answer to Q1 is
**no**, and §11 is the outcome.

**Q2 — convert gate 0 to a real data query (R4-permissible, §2.2)?**
Recommendation: **only bundled with B1–B10, or not at all.** Alone it converts a
truthful, self-explaining hard fail into zero-trade gate failures that read as
strategy defects (verified: 0 trades on daily bars).

**Q3 — history depth, if Q1 is yes.** Option A (2024-09-22) is **dead under every
configuration** (0 bear *and* 0 range labelled sessions, F1b). Option B (2021-09) is
the minimum viable under the pre-registered long-only configuration (16 bear
sessions). Option C (2016-10, parity with the daily program) gives 19.
**Recommendation if proceeding: C.**

**Q4 — operational risk to the live probation.** Option C at 15 m RTH inserts
1,551,264 rows (+0.53 GB) into the same SQLite file a live paper probation and a
background worker use, taking it from 0.382 GB to 0.91 GB (**2.39×**). It needs a
maintenance window with the worker stopped, and a decision on whether intraday bars
belong in this database at all rather than in a sidecar.

**Q5 — gate 7's docstring/code divergence** (`config/research.py:111-113` says OOS;
`promotion.py:775` computes all pre-sealed) remains open from `MAP.md` §0.2. Not
specific to this strategy, but an intraday run at ~1,500–3,000 trades/yr makes the
`sqrt(trades_per_year)` annualisation (`portfolio_metrics.py:110`) and the clamped
exposure (`:119`) far more consequential.

**Q6 (new) — `allow_short`: which configuration is the ladder supposed to test?**
The ladder is hard-wired long-only (`allow_short` never passed at `promotion.py:586`,
`:386`, `sensitivity.py:148`); the **live scan path passes it**
(`research/scan.py:271`, `cli.py:903`) from an operator-togglable setting
(`config/research.py:296`, dashboard `:332`). For `intraday_orb` this is not cosmetic:
it moves gate 6's bear supply from **19** to **267** sessions. The pre-registration
here is `allow_short = False`; changing it is a variant under R5 and needs your
decision **before** any run. It also means that, today, the ladder and the live
scanner could disagree about what a promoted strategy would trade — worth resolving
independently of this strategy.

**Q7 (new) — the CLI gaps.** `ingest-intraday` has no `--since/--until` and
`evaluate-promotion` cannot select a custom snapshot key (§A.2). Both must be built
before any keyed intraday evaluation is possible, and the second is what stops an
unkeyed run from silently attaching to **snapshot id 3**, the daily snapshot both
live approvals sit on.

---

*Design synthesis, `intraday_orb.intraday` v0.1.0. Read-only: no strategy code, no
configuration, no database row and no gate threshold was changed in producing this
document. No provider API was called. Every number is a `SELECT` result, a
`file:line` citation, an in-process read-only computation, or an arithmetic
derivation whose inputs are stated.*
