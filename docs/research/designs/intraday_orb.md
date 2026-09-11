# Design — `intraday_orb.intraday` v0.1.0 (version 1)

**Synthesis of the design phase for version 1.** One proposal was written for this
strategy (`designs/proposals/intraday_orb--requirements.md`, the requirements /
data-and-policy angle mandated by `STRATEGY_COMPLETION_MAP.md` §4.1), scored by two
judges (legitimacy 7/10 *revise*; impact-robustness-cost 8/10 *revise*). This document
is the single design of record. It supersedes the proposal wherever the two differ.

**Chosen path (§A): the requirements design plus the operator question, with the null
option — a documented `DOES NOT OPERATE` record — as the standing recommendation.**
No `v0.2.0`. No promotion attempt. No strategy-code change. No database write.

**Conformance:** `STRATEGY_COMPLETION_MAP.md` §1 (R1–R10), §2.4, §4.0/§4.2/§4.3, and
`STRATEGY_COMPLETION_PLAN.md`'s seven rules. The eleven §4.2 sections are reproduced in
order as §1–§11; §12 is the frozen pre-registration record; §13 the implementation
checklist and scratch-database commands; §14 the operator approvals and the failure
report.

**Labelling.** Every claim is **FACT** (verified in this synthesis by `file:line`, a
read-only `SELECT`, or a reproducible in-process computation), **DERIVED** (arithmetic
on stated inputs), or **HYPOTHESIS**. Proportions carry binomial standard errors. A
difference under 2 SE is not treated as evidence.

**Sealed-window discipline (R1).** Nothing below is derived from the sealed window
(2025-09-08 → 2026-09-08 on snapshots 2–4; 2025-09-07 → 2026-09-07 on snapshot 1). Every
computed number is code arithmetic, a read-only query, or a computation over the
**pre-sealed** span `2016-10-17 … 2025-09-07`. The sealed window is referenced exactly
twice, both for *disposition*, both marked inline: §10 (the look ledger) and §11 (the
null option).

**Work performed for this synthesis:** read-only. No file under `src/` or `tests/` was
modified; no command that writes `data/signalforge.sqlite` was run; no provider API was
called; no package installed; no service restarted. In-process calls were limited to
`PriceSeries.load`, `backtest/regime.label_regimes` and `research/regime.regime_lookup`
(all read-only), plus `sqlite3` opened `mode=ro`.

---

## A. Chosen path, and the disposition of every judge defect

### A.1 The path

The map (§2.4, §4.1) and the plan both fix this strategy's output as *"a data-and-policy
requirements design plus an explicit operator question, explicitly not a promotion
attempt."* Both judges agreed the proposal's substance is right and neither asked for a
different path; both asked for corrections. This design therefore keeps the path and
applies the corrections.

The synthesis makes **one substantive addition** that neither the proposal nor the map
contained, and it is the most consequential thing in this document:

> **FACT (verified for this synthesis).** `evaluate_promotion` has exactly **three**
> `return _finalize` sites — `promotion.py:522`, `:571`, `:893` — and the first two are
> **both inside gate 0**. There is no early return anywhere between gate 0 and gate 9.
> Gate 9 at `promotion.py:838` therefore runs on **every** evaluation that clears gate 0,
> whatever gates 1–8 did, and it calls `_get_or_create_sealed_test`, which is keyed on
> `(strategy_version_id, dataset_snapshot_id)` and documented at `promotion.py:377-384`
> as *"locked — never recomputed, never overwritten"*.
>
> **Consequence.** The *first* intraday run that clears gate 0 — including a partial,
> pre-bundle or debugging run — irreversibly creates version 1's **first-ever**
> `strategy_sealed_test` row and locks it. FACT (queried): version 1 has **zero** rows in
> `strategy_sealed_test` today; that is why the table holds 20 rows and not 24. Because
> `VERSION` stays `"0.1.0"`, `upsert_strategy_version` (`persistence.py:46-93`) reuses the
> same version row, so a *later, correct* evaluation on the same snapshot would silently
> **replay** the locked, meaningless result. Escaping it needs either a `VERSION` bump or
> a new snapshot key — each of which is itself a further sealed look.

This is the R3 staleness trap arriving through the **promotion path** rather than through
the strategy code. The proposal's §10 asserted the trap "cannot" occur here; that
assertion is withdrawn. It converts the variant budget's "1 full promotion evaluation"
from a compute cost into an **irreversible, single-use asset**, and it is the reason §13
mandates that all bundle development and every dry run happen on a scratch database copy.

### A.2 Judge defects — accepted

| # | Judge | Defect | Disposition |
|---|---|---|---|
| J1-1 | legitimacy | Gate 9 runs unconditionally after gate 0; §2.3's "misleading, not unsafe" and §10's R3 trap check are wrong | **ACCEPTED, verified.** §A.1, §10, §12.5, §13. Promoted to the headline finding. |
| J1-2 / J2-2 | both | The cost table uses the OR width `w` as the risk unit; the engine's unit is `entry_fill − or_lo` | **ACCEPTED, verified** (`engine.py:108-111`), **with a correction to the judges' framing** — see §A.3(a). §8 is recomputed on the engine's unit. |
| J1-3 | legitimacy | B1's cited location is wrong: `sensitivity.py:148` already threads `intraday`/`bar_size` | **ACCEPTED, verified.** `run_parameter_sensitivity` declares them at `sensitivity.py:128-129` and passes them at `:155-157`; the omission is at the **caller**, `promotion.py:708`. B1 relocated. |
| J1-4 | legitimacy | The bear-supply ceiling silently assumes long-only; the strategy is two-sided | **ACCEPTED, verified and quantified.** `backtest_runner.py:176` `allow_short: bool = False`, never passed at `promotion.py:386`/`:586`; `intraday_orb.py:116` shorts exactly when `ctx.regime.risk_off`. I measured the short-eligible set: **248** bear-labelled risk-off sessions against the 19 long-eligible ones. Disclosed at every point the ceiling is asserted, and added to F1. |
| J1-5 | legitimacy | Gate 0's predicate is not the predicate the backtest loads under | **ACCEPTED, verified.** `PriceSeries.load_intraday` (`series.py:105-136`) filters only `bar_size`, `bar_start` and `source` — not `session`, not `is_simulated`, both of which exist as columns (`db/models/market.py:117`, `:126`). New bundle item **B7**. |
| J1-6 / J2-6 | both | Sealed-look accounting is internally inconsistent ("k = 5 … plus the next one", then "look 6") and the k=5 baseline does not exist for this family | **ACCEPTED.** §10 now reports three numbers on every future look and flags the map's own §0.1-vs-§4.2 contradiction as an operator open item. |
| J1-7 | legitimacy | The "≥ 15 min" latency magnitude is over-labelled as measured | **ACCEPTED, verified.** `entitlements.py:250-257` passes `latency="DELAYED"` as a *declared* label into `_check`; `CAPABILITY_MATRIX.md:26` attributes the 15-minute figure to the lead's brief. Relabelled; the conclusion is restated to hold for **any** delay of one bar or more. |
| J1-8 / J2-8 | both | §2.2's 95% / 99% gate-0 thresholds are unpre-registered, and the 99% bar-count condition **rejects a correct backfill** because of NYSE early closes | **ACCEPTED.** Condition (c) is rewritten as a calendar-typed set membership; the thresholds are pre-registered with a stated basis in §12.1. |
| J1-9 | legitimacy | R10 partially unmet: F3/F4 not stated across all four snapshots | **ACCEPTED.** §4 now states the cross-snapshot status of every falsifier explicitly, including why snapshots 1/2/4 cannot carry an intraday snapshot at all. |
| J1-10 / J2-5 | both | The synthetic entry rate carries a misleading SE and silently underwrites four gate forecasts | **ACCEPTED.** The `± 0.04` is relabelled as simulation sampling error, and §3.5 now carries a rate-sensitivity band that §5 uses. |
| J2-1 | impact | Gate 4's "not power-limited" ignores trade clustering | **ACCEPTED, verified** against `diagnostics/clustered_bootstrap_all.md:130-155` (month-block `deff` 2.55/3.04/4.86/2.60/2.66), which map §4.3 makes mandatory to report. The claim is withdrawn; §5 and §12 carry a design-effect table. **The judge's specific numbers are corrected** — see §A.3(b). |
| J2-3 | impact | "4–10× any daily strategy" is not supported at the low end | **ACCEPTED with a better replacement.** §8 now reports the raw multiple correctly *and* the break-even **cost wedge**, which is nearly invariant to the risk-unit correction — see §A.3(c). |
| J2-4 | impact | Gate 7 is declared unforecastable when its direction is computable | **ACCEPTED, verified** (`portfolio_metrics.py:110`, `promotion.py:775`, `_benchmark_metrics` at `:216-238`). Restated as *expected pass, and uninformative*. |
| J2-7 | impact | B2 collides with `diagnostics/pipeline_hardening_spec.md:167-169`, which already claims `promotion.py:744` | **ACCEPTED, verified.** B2 is restated as a **rider** on that spec's Change A, not a competing patch. |
| J2-9 | impact | Storage figures are stated two inconsistent ways | **ACCEPTED.** §3.3 states added bytes and resulting multiple separately per option. |

### A.3 Judge defects — rejected, or accepted only in part, with reasons

**(a) J1-2 / J2-2's "upper bound" framing is rejected; the correction itself is accepted.**
Both judges concluded that because `risk_per_share = |entry_fill − sig.stop_price|`
(`engine.py:111`) with `stop_price = or_lo` and the signal requires `close[t] > or_hi`,
the engine's risk unit `d` is *strictly greater* than the OR width `w`, so the w-anchored
cost figures are an **upper bound** on cost in R. That is wrong in general. FACT
(`engine.py:107-109`): the fill is the **next bar's open**, `entry_fill =
series.open[t+1] × (1 + slip)`, not the signal close. A next bar that opens back inside
the opening range gives `entry_fill < or_hi`, hence `d < w`, hence cost in R **higher**
than the w-anchored figure. The w-table is therefore neither an upper nor a lower bound;
it is the `ρ = d/w = 1` special case of a quantity that is unmeasurable without intraday
data. §8 is rewritten in terms of `d/price` directly, `ρ` is added to the post-ingest
measurement list, and the modal expectation `E[ρ] > 1` (so the w-table *usually*
overstates cost) is stated as HYPOTHESIS, not as a bound.

**(b) J2-1's design-effect arithmetic is rejected; its substance is accepted.** The judge
gives the sd = 1.420 gate-4 hurdle as **+0.0819R** at `deff` 3 and **+0.0999R** at
`deff` 5. Recomputed: the hurdle is `0.02 + 1.96·sd·√(D/n)`, and at `n = 5,393`,
`1.96 × 1.420/√5,393 = 0.03789`, so `D = 3` gives **+0.0856R** and `D = 5` gives
**+0.1047R**. The judge's figures correspond to `D ≈ 2.67` and `D ≈ 4.45`. §5 and §12.2
use the recomputed values.

**(c) J2-3's "3.3×–8.7×" is accepted arithmetically but is not the right statistic, and
the proposal's "4–10×" was not fabricated.** At the *hypothesised* OR-width band
(w = 0.5–0.7%) the raw multiple against `volatility_breakout`'s 0.042R is 4.0–5.2×, i.e.
inside the proposal's stated range; the "low end" the judge objects to (3.3×) comes from
w = 0.8%, the extreme edge of the proposal's own table. The deeper problem is that the
raw multiple moves with the risk-unit correction while the economically meaningful
quantity does not. §8 therefore leads with the **cost wedge** — the number of percentage
points by which cost lifts the break-even hit rate above the geometry's random-walk
baseline — which has the closed form `wedge = (round_trip/10⁴)/(d + m·w)` and is
therefore almost insensitive to `ρ`. See §8.

**(d) J1-4's "the claim inverts if `allow_short` is ever true" is accepted as a
disclosure requirement, not as a correction to the forecast.** FACT: the promotion ladder
is long-only today and nothing in `promotion.py` can change that — `allow_short` is never
passed at `:386` or `:586`. The gate-6 forecast in §5 is computed for the ladder as it
runs. What is added is the disclosure that the 19-session ceiling is a property of the
*long-only ladder*, that 248 bear-labelled sessions are short-eligible under
`intraday_orb.py:116`, that the operating path already threads the flag
(`scan.py:271`, `cli.py:903`, `config/research.py:296 allow_short_candidates = False`),
and that turning it on would be a **behavioural change to the evidence base** requiring
its own pre-registration.

**(e) J1-5's "B3 runs at gate 8, i.e. after gates 1–7 have already produced the numbers"
is accepted with a precision.** A gate-8 failure does block promotion — `passed =
bool(gates) and all(g.passed …)` (`promotion.py:922`). The real harm is that gates 1–7
would *report* numbers computed on contaminated bars, and those numbers are what a human
reads. B7 (filter at load) is therefore the fix, and B3 (validate at gate 8) is the
audit, not the other way round.

**(f) J1-8's implication that the new gate-0 thresholds risk an R4 weakening is
rejected.** Every condition in §2.2 is strictly harder to satisfy than the hard-coded
fail it replaces; none can make any gate easier to pass. What the judge is right about is
that they are gate numbers entering a pre-registration document with no stated basis —
that is fixed in §12.1, and condition (c) is repaired.

---

## 0. Executive summary — the six findings that decide this

1. **FACT — the first intraday run past gate 0 permanently burns version 1's only
   sealed look, whatever else it does.** `evaluate_promotion` has no early return between
   gate 0 and gate 9 (`promotion.py:522`, `:571`, `:893` are the only three); gate 9 at
   `:838` locks a row keyed `(version, snapshot)` (`:377-384`). Version 1 has zero sealed
   rows today. A debugging run is indistinguishable, afterwards, from the real one. §A.1.
2. **FACT — the entitled feed is `DELAYED`, and no `REALTIME` equities feed exists on
   this plan.** `entitlements.py:250-257` probes `stocks_intraday_aggs_5m` with a declared
   `latency="DELAYED"`; `MassiveAdapter` declares only `LatencyCategory.END_OF_DAY`
   (`massive.py:86-100`). The engine enters at the **next bar's open**
   (`engine.py:107-109`). Any feed delay of one bar or more makes the modelled fill
   unattainable live. *(The specific "≥ 15 minutes" magnitude is out-of-band — attributed
   to the lead's brief by `CAPABILITY_MATRIX.md:26` — not measured in this repo. The
   conclusion does not depend on the magnitude.)*
3. **FACT/DERIVED — the frozen cost model imposes a break-even hit-rate penalty 3.3×–10.5×
   larger than any daily strategy's.** The engine's risk unit is `entry_fill − or_lo`, a
   few tens of basis points, not an ATR multiple. At the unchanged 11.0 bps round trip
   (`engine.py:94`, `:144`) the cost wedge above the geometry's random-walk break-even is
   **4.6–14.7 pp** across the plausible opening-range band, against **1.23 pp** for
   `trend_continuation` and **1.40 pp** for `volatility_breakout` (§8). Gate 3, not gate 4,
   is the binding gate — a reversal of the pattern for every other strategy in the program.
4. **FACT — gate 6 fails unconditionally on any intraday run of the promotion path as it
   stands.** `promotion.py:744` looks trades up in `label_regimes`'s `dict[date, str]`
   (`backtest/regime.py:25`) using `t.entry_date`, which for an intraday run is a
   timezone-aware `datetime` (`engine.py:113` ← `series.dates[entry_idx]`). A `datetime`
   key never matches a `date` key. Buckets `0/0/0`, 100% unbucketed. Note the asymmetry
   that makes this survivable to diagnose: `signal_fn_for` **does** normalise
   (`base.py:38-40`), so the strategy's own regime gate works; only the gate-6 census does
   not.
5. **FACT — gate 6's bear bucket has a hard nine-year calendar ceiling under the long-only
   ladder.** Recomputed independently for this synthesis over `2016-10-17 … 2025-09-07`,
   source `massive`: of **267** bear-labelled proxy sessions only **19** are tradeable
   under the strategy's own `not ctx.regime.risk_off` gate — **7.12% ± 1.57%**, against
   bull **73.56% ± 1.18%** (a ~34 SE contrast). All 19 fall in Oct–Nov 2020 (3) and
   Feb–Jun 2023 (16); **none after 2023-06-02**; **zero** for any pre-sealed start on or
   after 2022-09-08, which includes the shortest span gate 0 will accept. Disclosed
   dependency: the ladder runs `allow_short=False`; **248** bear sessions are short-eligible
   under `intraday_orb.py:116` and the ladder cannot reach them.
6. **FACT — the promotion path is intraday-incapable in eight places beyond gate 0**, and
   converting gate 0 alone (the R4-permissible change) turns a truthful, self-explaining
   hard fail into a set of zero-trade gate failures that read as strategy defects. §2.3.

**Recommendation: do not build the pipeline. Take the null option (§11).** The
requirements below are specified in full so the decision is made on costed facts rather
than on the absence of a plan. The recommendation changes only if the operator answers
**Q1** (§14) by acquiring a real-time equities entitlement, or if **F1** or **F3** (§4)
falls.

---

## 1. Mechanism

This design proposes no market hypothesis about opening-range breakouts, because it
proposes no rule and forecasts no edge. It states a **capability hypothesis** in the §2
form the map requires, so that it can be killed:

> **H13.** `STRATEGY_COMPLETION_MAP.md` §2.4 identifies three independent blocks
> (promotion-path gate, EOD-only operating policy, absent data path). H13 asserts that
> **removing all three is neither sufficient nor economically sensible**, because three
> further layers — provider **latency**, the frozen **cost model**, and the
> **irreversibility of the first gate-9 lock** — independently prevent an honest,
> operable pass, and all three are quantifiable **today, with no intraday data at all**.

Why this should be true in markets rather than only in the backtest: an opening-range
breakout is a *microstructure* strategy. Whatever edge it has lives in the first hour,
when effective spread and adverse selection are at their daily maximum, and its risk unit
is the opening range — tens of basis points — rather than a multi-percent ATR stop. Both
facts push the same way: the ratio of transaction cost to risk unit is an order of
magnitude worse than for a swing strategy, and the sensitivity of the realised fill to
execution latency is an order of magnitude higher. A strategy of this shape is viable only
with (a) real-time data, (b) a measured spread, and (c) a cost model calibrated to the
opening auction. This program has none of the three: real time is unentitled; NBBO quotes
return `403 not_authorized` (`data/entitlements.py`, feed `stocks_nbbo_quotes`;
`universe/screen.py` flags every symbol `F_SPREAD = "spread_filter_not_licensed"`); and
R4 freezes the cost model at a universe- and horizon-independent flat 5.0 bps assumed
spread (`engine.py:90`; `backtest_runner.py:205-206` never overrides it).

Relation to the existing hypothesis set: H13 uses none of H1–H4 (v3, demoted), H6/H8/H9
(v4) or H11. It **inherits H12's mechanism** from `diagnostics/v6_regime_power.md` — a
regime gate shut on almost every bear session, producing a breadth/availability failure at
gate 6 with a hard calendar ceiling — and §3.1 shows `intraday_orb` sits behind *the same
gate expression* (`not ctx.regime.risk_off`, `intraday_orb.py:105`) that `breakout.py:102`
uses.

---

## 2. Exact change — file, symbol, before → after

### 2.1 What this design does **not** change

- `src/signalforge/research/strategies/intraday_orb.py` — **unchanged**. `VERSION` stays
  `"0.1.0"` (`:25`); `ORBParams` (`:28-34`) unchanged; `IntradayORB.evaluate` (`:88-127`)
  unchanged. No `v0.2.0` row is created, so R3 and R7 are satisfied vacuously.
- `research/strategies/__init__.py:43-51` `default_strategies()` — unchanged (6 entries;
  `IntradayORB` is already registered).
- Any threshold in `config/research.py:93-123` or `backtest/costs.py:11-16` — unchanged
  (R4).
- **R7 / R7b safety (FACT).** Nothing here touches any `StrategySpec`, so
  `approval_scope.current_spec_json_hash()` for the two live PAPER_APPROVED versions
  (v2 `trend_continuation.short_swing`, v5 `relative_strength.medium_swing`) cannot move,
  and no new *passing* evaluation is created, so the `scopes[0]` ordering hazard
  (`paper_probation.py:118`, `approval_scope.py:45-66` with no `order_by`) is not
  activated. §13 re-verifies both after any future work.

### 2.2 The R4-permissible change (specified, **not applied**): gate 0 becomes a real query

**File:** `src/signalforge/research/promotion.py`. **Symbol:** `evaluate_promotion`, the
`Horizon.INTRADAY` block.

**Before (FACT, `promotion.py:512-534`):** `if spec.horizon is Horizon.INTRADAY:` appends
a hard-coded failing `Gate(0, "data_availability", False, …)` and `return _finalize(…)`
at `:522`, skipping even the `MIN_PRESEALED_DAYS` check that the daily path applies at
`:559-583`.

**After (specification):** replace the declared-horizon test with a coverage query against
`OHLCVIntraday`, then **fall through** to the existing `MIN_PRESEALED_DAYS` check.

```
gate 0 (INTRADAY) passes only if ALL of:
  a. for every symbol in `symbols`, OHLCVIntraday rows exist with
       bar_size == config.intraday_bar_size, source == the run's SourceFilter,
       is_simulated is False, session == "rth", bar_start within [start, end];
  b. per-symbol session coverage >= 99% of the daily sessions the same symbol has in
     OHLCVDaily over the same span and source (catches partial backfills);
  c. per-session bar count is EXACTLY the expected RTH count for that session's
     exchange-calendar type at that bar size -- 26 for a full session at "15m",
     14 for a 13:00 ET early close -- for 100% of covered sessions, with the
     early-close dates supplied by an explicit calendar list, not inferred;
  d. the latest ingested bar_start satisfies the same freshness bound
     approved_scope_scan.data_readiness applies to the daily feed;
  e. the existing pre-sealed-span test then runs unchanged
     ((pre_sealed_end - start).days >= MIN_PRESEALED_DAYS == 350,
      promotion.py:94, :559).
Otherwise: Gate(0, "data_availability", False, <which of a-e failed, per symbol>).
```

**Condition (c) is the judges' repair (J2-8), and it matters.** A 13:00 ET early close is
9:30–13:00 = 210 minutes = **14** bars at 15 m, not 26. NYSE runs roughly two to three
early closes a year (July 3 when it falls on a weekday, the day after Thanksgiving,
Christmas Eve in most years) — HYPOTHESIS from the market calendar, out-of-band, ~0.8–1.2%
of sessions. The proposal's "== 26 bars for ≥ 99% of sessions" therefore **rejects a
complete, correct, RTH-only backfill** by roughly 0.2 pp every year while nominally
policing exactly the defect it misses. Set membership against a calendar type is both
stricter (100%, not 99%) and correct.

**Why this is R4-permissible and not a weakening.** The current test is a hard-coded fail;
any real query is *at least as hard* to satisfy, because it keeps failing for as long as
no intraday data exists and then keeps failing on partial, mis-sized, simulated,
wrong-source or stale data. Conditions (b)–(d) are additions the hard-coded fail never
enforced. This is the same carve-out that permits adding a missing sensitivity grid
(map §1, R4 carve-out 1) and the map itself already rules it permitted-in-principle
(§2.4, §1 R4 carve-out 2).

### 2.3 The mandatory bundle — gate 0 must NOT ship alone

**FACT:** after §2.2, execution falls through to
`full = run_strategy_over_universe(…)` at `promotion.py:586`, which does **not** pass
`intraday=` or `bar_size=`. Those default to `intraday=False, bar_size="15m"`
(`backtest_runner.py:179-180`), so the ladder would evaluate an INTRADAY strategy on
**daily** bars. FACT (verified read-only in the proposal, mechanism re-verified here):
`IntradayORB` over daily bars yields `n_trades = 0` — `features/intraday.py:19-21`
`_session_date` returns each daily bar's own date, so `bars_since_open` (`:24-32`) is
always `0`, `opening_range` (`:35-45`) never accumulates `k_bars = 3` bars in one
"session" and returns `(nan, nan)`, and `evaluate` exits at `intraday_orb.py:90-91`.

Shipping §2.2 alone is therefore **not safe**, contrary to the proposal: gate 0 would
report data availability, gates 1–7 would report zero-trade failures that read as strategy
defects, and — per §A.1 — **gate 9 would run and lock version 1's first sealed test on
zero trades**.

| # | File / symbol | Defect today (FACT) | Required |
|---|---|---|---|
| **B1** | `promotion.py:586` and `:386`; **`promotion.py:708`** (the `run_parameter_sensitivity` call) | `run_strategy_over_universe` called without `intraday=`/`bar_size=`; the sensitivity **caller** omits them too. *(Corrected from the proposal: `run_parameter_sensitivity` already declares them at `sensitivity.py:128-129` and threads them at `:155-157` — the callee is fine.)* | thread `intraday = spec.horizon is Horizon.INTRADAY` and `bar_size = config.intraday_bar_size` through gates 1–5 and gate 9 |
| **B2** | `promotion.py:744` `regimes.get(t.entry_date, "warmup")` against `dict[date, str]` (`backtest/regime.py:25`) | intraday `t.entry_date` is a `datetime`; buckets `0/0/0`, 100% unbucketed, **gate 6 fails unconditionally**. `signal_fn_for` normalises (`base.py:38-40`); this call site does not | apply `_as_date` (`backtest_runner.py:163-164`) to `t.entry_date`. **This is a rider on `diagnostics/pipeline_hardening_spec.md` §1.5 Change A (lines 167-169), which already pre-registers replacing this same line with a three-way `missing`/`warmup`/bucket classification.** The two are complementary — the hardening spec does not address the key *type* — and must land as one patch, not two |
| **B3** | `data/validate.py` has only `validate_daily` (`:66`) and `validate_option_aggregates` (`:249`) | gate 8 (`promotion.py:808`) validates **daily** bars for an intraday strategy — a PASS that says nothing about the data traded | a `validate_intraday` counterpart (session completeness, bar-count-per-session against the calendar type, duplicate `bar_start`, non-positive prices, `source`/`bar_size`/`session`/`is_simulated` purity) wired into gate 8 when the horizon is INTRADAY |
| **B4** | `promotion.py:249-267` `_leakage_self_check` covers four daily features on the daily proxy | the intraday feature set is never leakage-checked by the ladder | add `opening_range`, `bars_since_open`, `session_bar_count` on the intraday series when the horizon is INTRADAY (§7 shows they pass today) |
| **B5** | `promotion.py:161-210` `_sensitivity_plan` has no `intraday_orb` branch | gate 5 **hard-fails** (`promotion.py:694-703`) — an automatic permanent failure, not a skip | register the §6 grid (R4 carve-out 1) |
| **B6** | `features/intraday.py:38` `opening_range` rescans `range(t+1)`; `series.head(t)` (`series.py:40-51`) copies the `dates` tuple | the backtest is `O(n²)` per symbol — extrapolated ~32 min per 24-symbol full-span pass at 15 m, ~5.4 h per 10-gate evaluation (§3.4) | precompute session boundaries once per series (or cache the per-session index) before any intraday evaluation is attempted |
| **B7** *(new, J1-5)* | `PriceSeries.load_intraday` (`series.py:105-136`) filters only `bar_size`, `bar_start` and `source` | gate 0 could pass on the RTH, non-simulated subset while gates 1–9 **trade pre/post-market and simulated bars** — the exact corruption `_session_date`'s UTC grouping produces. `session` and `is_simulated` both exist as columns (`db/models/market.py:117`, `:126`) | filter `session` and `is_simulated` at load, so the predicate gate 0 asserts is the predicate the backtest runs under. Enforce **before** gate 1, not at gate 8 via B3 |
| **B8** *(new)* | `cli.py:1282-1412` `evaluate-promotion` accepts only `--dataset baseline\|ex_meta\|meta_continuity_corrected`, and with `--symbols` it passes `dataset_snapshot=None`, so `evaluate_promotion` calls `get_or_create_dataset_snapshot(session, symbols=…)` **unkeyed** (`promotion.py:505`) | FACT (queried): snapshot **3** `universe_24_ex_meta` has `reusable_by_new_evaluations = 1`, and the unkeyed branch (`promotion.py:333-337`) matches any reusable snapshot on an exact symbol-set match. An intraday run on the 24 ex-META symbols would **silently attach to snapshot 3** — the daily-bar snapshot the two live approvals sit on | add an explicit intraday dataset variant that mints the key `universe_24_ex_meta_intraday_15m`. FACT: the keyed branch (`promotion.py:309-329`) accepts a distinct key with the same symbol set, and raises rather than reusing on a mismatch |

Two further defects are **reporting**, not gate, problems, listed for disclosure rather
than as blockers: `research/portfolio_metrics.py:97` sums `bars_held` into `exposure_days`
(15-minute bars counted as days) and `:119` clamps `exposure` at 1.0, so gate 7's evidence
blob would report 100% exposure for a strategy that is flat overnight; and `_resolve_exit`
(`engine.py:152-184`) has no session-boundary awareness — see the leash defect in §5.

### 2.4 Data-pipeline requirements (the part that costs money and time)

| Item | Requirement | Evidence / basis |
|---|---|---|
| Adapter | a real `MassiveAdapter.fetch_intraday_bars` satisfying `IntradayBarAdapter` (`adapters/base.py:138-149`), declaring `AdapterCapability(feed_type=FeedType.BAR_INTRADAY, latency_category=DELAYED, rate_limit_per_min=5)` | FACT: `massive.py:86-100` declares **only** `BAR_DAILY`; the only `BAR_INTRADAY` capability in the repo is the test fixture (`adapters/fixture/__init__.py:79`) |
| Endpoint | `/v2/aggs/ticker/{sym}/range/15/minute/{from}/{to}?adjusted=true&sort=asc&limit=50000` | FACT: the daily path uses the same family at `massive.py:178`; the entitlement probe uses `/range/5/minute/` (`entitlements.py:252-254`) |
| Pagination | the daily adapter **rejects** any response carrying `next_url` (`massive.py:186`); an intraday adapter must chunk by calendar instead | FACT |
| Bar size | **15 m**, not 5 m | FACT: `config/research.py:303 intraday_bar_size = "15m"`; `backtest_runner.py:180` default; and the strategy's own guard `session_bar_count + time_stop_bars > 26 + or_bars` (`intraday_orb.py:97`) is written against a **26-bar** session = 390 RTH minutes ÷ 15 |
| Session filter | ingest **RTH only** (`session="rth"`) **and** filter at load (B7) | FACT: `load_intraday` (`series.py:105-136`) filters neither `session` nor `is_simulated`; `_session_date` (`features/intraday.py:19-21`) groups by **UTC** date, so (i) a 04:00 ET pre-market bar becomes the "opening range" and (ii) under EST a post-market bar starting ≥ 19:00 ET falls on the *next* UTC date and corrupts that session's range |
| Ingest entry point | `ingest_intraday_symbol` / `ingest_intraday_universe` (`ingest.py:455-489`, `:527-542`) and `signalforge ingest-intraday` (`cli.py:622-659`) already exist and write `OHLCVIntraday` | FACT — no new ingest code is needed, but `cli.py:640-642` exits if the adapter has no `fetch_intraday_bars`, which today it does not |
| Snapshot key | a **new, explicit** key `universe_24_ex_meta_intraday_15m`, plus the B8 CLI path to mint it | FACT: `DataSnapshot` (`db/models/research.py:224-249`) has **no bar-size or horizon column**; see B8 for the silent-attachment hazard. Verify the key against both auto-generators (`universe_auto_*`, `promotion.py:339`; `liquid_us_<date>_<digest>`, `screen.py:259`) — FACT (queried): ten `data_snapshot` rows exist today, ids 1–10 |
| Concurrency | schedule the backfill in a maintenance window with the worker stopped | a live paper probation and a background worker run against `data/signalforge.sqlite`; a 0.8–1.6 M-row insert inside a sticky write-intent session is exactly the contention the project's SQLite rules exist to avoid |

---

## 3. Pre-sealed evidence, with standard errors

All computations use **only** the pre-sealed span `2016-10-17 … 2025-09-07`, source
`massive`, or pure code arithmetic. `STRATEGY_COMPLETION_MAP.md` §0.3 supplies **no**
per-trade `sd` for version 1 (it has never been evaluated past gate 0), so where an `sd`
is needed the result is stated **as a function of `sd`** over the program's observed range
0.807–1.741 rather than invented.

### 3.1 The regime gate is shut on 93% of bear sessions (decisive for gate 6)

FACT — recomputed **independently for this synthesis** in-process (read-only):
`label_regimes(SPY)` (gate 6's labeller, `backtest/regime.py`) crossed with
`regime_lookup(SPY).risk_off` (the strategy's own gate, `research/regime.py:41-42`).
Proxy: 2,234 SPY sessions, 2016-10-17 → 2025-09-05.

| gate-6 bucket | labelled sessions | tradeable (`not risk_off`) | share ± SE |
|---|---|---|---|
| bull | 1,392 | 1,024 | 73.56% ± 1.18% |
| **bear** | **267** | **19** | **7.12% ± 1.57%** |
| range | 375 | 116 | 30.93% ± 2.39% |
| warmup (unbucketable, map §0.6) | 200 | 178 | 89.00% ± 2.21% |

The load-bearing contrast — bear 7.12% ± 1.57% against bull 73.56% ± 1.18% — is roughly
**34 SE**, far past the 2 SE bar. Bear sessions are 267/2,034 = **13.13% ± 0.75%** of
labelled pre-sealed sessions, reproducing `diagnostics/v6_regime_power.md`'s 267 / 11.95%
(the latter over all 2,234 sessions including warmup) exactly.

FACT — the 19 tradeable bear sessions, in full: 2020-10-28, 2020-10-30, 2020-11-02;
2023-02-02, -02-03, -02-06, -02-07, -02-08, -02-09, -02-10, -02-13, -02-14, -02-16,
-02-17; 2023-05-16, -05-24, -05-31; 2023-06-01, 2023-06-02. **None after 2023-06-02.**

**Disclosed long-only dependency (J1-4).** FACT: the ladder runs `allow_short=False`
(`backtest_runner.py:176`, never passed at `promotion.py:386`/`:586`), while
`intraday_orb.py:116` takes shorts precisely when `ctx.allow_short and close < or_lo and
ctx.regime.risk_off`. Measured for this synthesis: **248** of the 267 bear-labelled
sessions are risk-off, i.e. short-eligible and long-ineligible. The 19-session ceiling is a
property of the long-only ladder, not of the market. FACT: the operating path does thread
the flag (`scan.py:271`, `cli.py:903`) from `config/research.py:296
allow_short_candidates = False`. Turning it on would change the evidence base and requires
its own pre-registration; it is added to F1 as a falsifier.

### 3.2 History depth is forced by gate 6, not by gate 0

Tradeable (`not risk_off`) sessions by gate-6 bucket, as a function of pre-sealed start.
`label_regimes` labels the first `TREND_LOOKBACK = 200` sessions `"warmup"`
(`backtest/regime.py:20, 36-37`), so a later start swallows real regime sessions into the
warmup hole. (Table from the proposal; both judges reproduced it and I reproduced the
2016-10-17 row exactly in §3.1.)

| pre-sealed start | sessions | bull | **bear** | range | warmup |
|---|---|---|---|---|---|
| 2016-10-17 (parity with the daily program) | 2,234 | 1,024 | **19** | 116 | 178 |
| 2018-09-10 | 1,757 | 822 | **19** | 71 | 161 |
| 2019-09-09 | 1,507 | 707 | **19** | 65 | 95 |
| 2020-09-08 | 1,255 | 493 | **16** | 65 | 200 |
| 2021-09-08 | 1,003 | 400 | **16** | 62 | 94 |
| 2022-09-08 | 751 | 348 | **0** | 31 | 200 |
| 2023-09-08 | 500 | 139 | **0** | 4 | 177 |
| 2024-09-22 (shortest gate-0-legal span) | 239 | 39 | **0** | 0 | 108 |

DERIVED, and this is the hardest requirement in the document:

- The **shortest span gate 0 will accept** is 716 calendar days
  (`sealed_start = end − 365`; `pre_sealed_end = sealed_start − 1`;
  `(pre_sealed_end − start).days ≥ MIN_PRESEALED_DAYS = ceil(200 × 365.25/252) + 60 = 350`
  — `promotion.py:90-94`, `:559`). For `end = 2026-09-08` that is `start ≤ 2024-09-22`. At
  that start **39 of 239** pre-sealed sessions are labelled and every one is `bull_lowvol`:
  bear = 0 and range = 0, so gate 6 (`≥ 10 trades in each of 3 buckets`,
  `config/research.py:109-110`) is **arithmetically unreachable** no matter how good the
  strategy is.
- Any start on or after **2022-09-08** yields **0** tradeable bear sessions.
- A start of **2021-09-08** recovers the 16 Feb–Jun 2023 sessions; **2019-09-09** or
  earlier recovers all 19.

**So the intraday backfill must reach back to at least 2021-09, and to 2016-10 for parity
with the daily program. "Two years of intraday bars" is not a viable option.**

### 3.3 Data volume, API budget and storage

DERIVED. Symbols = the 24 of snapshot 3 (`universe_24_ex_meta`, the only universe on which
gate 8 passes — map §0.1); RTH bars/session = 26 at 15 m, 78 at 5 m. Extended-hours figures
are shown because the provider returns them unless the window is filtered, and §2.4 / B7
require they be dropped.

| Option | Span | Sessions/sym | 15 m RTH rows | 15 m incl. pre/post | 5 m RTH rows | API calls (yearly × 24) | Paced wall-clock |
|---|---|---|---|---|---|---|---|
| **A** minimum legal | 2024-09-22 → 2026-09-08 | 491 | 306,384 | 754,176 | 919,152 | 48 | 9.7 min |
| **B** bear-coverage minimum | 2021-09-08 → 2026-09-08 | 1,255 | 783,120 | 1,927,680 | 2,349,360 | 120 | 24.2 min |
| **C** parity with the daily program | 2016-10-17 → 2026-09-08 | 2,486 | 1,551,264 | 3,818,496 | 4,653,792 | 240 | **48.4 min** |

Basis: pacing 12.1 s/request (`massive.py:39-40 _MIN_REQUEST_SPACING_S = 12.1`;
`config/settings.py:53` same default; Basic plan 5 req/min). Same order as W1's
pre-registered daily build (126 calls / ~25 min,
`diagnostics/w1_universe_preregistration.md:275-276`). Yearly chunking keeps every request
under the 50,000-row cap even with extended hours (252 × 192 = 48,384 at 5 m).

**Storage — stated as added bytes and resulting multiple separately, per option (J2-9).**
FACT (measured, `dbstat`, read-only): `ohlcv_daily` plus its five indexes occupy
355,749,888 B for 1,036,162 rows = **343 B/row**. FACT (queried): the database file is
**381,739,008 B (0.382 GB)** and `ohlcv_intraday` holds **0 rows**. `OHLCVIntraday` carries
two extra short string columns and a different index set, so ±20% is the honest band.

| Option C variant | rows | added | resulting file | resulting multiple |
|---|---|---|---|---|
| 15 m, RTH only (**recommended if proceeding**) | 1,551,264 | ~0.53 GB | ~0.91 GB | **~2.4×** |
| 15 m, pre/post kept | 3,818,496 | ~1.31 GB | ~1.69 GB | ~4.4× |
| 5 m, RTH only | 4,653,792 | ~1.60 GB | ~1.98 GB | ~5.2× |

### 3.4 Compute cost of one promotion evaluation

FACT (measured by the proposal on synthetic in-memory series, no DB; mechanism verified
here at `features/intraday.py:38` and `series.py:40-51`): `run_backtest` with
`signal_fn_for(IntradayORB())` on 15-minute bars is cleanly quadratic — 1,560 bars 0.06 s;
3,120 bars 0.24 s; 6,552 bars 1.03 s; 13,104 bars 4.11 s; fit `t ≈ 2.394 × 10⁻⁸ · n²`
s/symbol.

DERIVED, 24 symbols, one complete evaluation = 1 pre-sealed pass + 9 gate-5 grid re-runs
(`sensitivity.py:148`, one per grid point) + 1 sealed pass:

| Option | bar size | pre-sealed bars/symbol | one pass | one full 10-gate evaluation |
|---|---|---|---|---|
| A | 15 m | 6,214 | 0.4 min | 0.07 h |
| B | 15 m | 26,078 | 6.5 min | 1.1 h |
| **C** | **15 m** | **58,084** | **32.3 min** | **5.4 h** |
| C | 5 m | 174,252 | 290.7 min | 48.5 h |

**Declared limitation:** the fit is measured over 1,560–13,104 bars and extrapolated to
58,084–174,252. The quadratic form is mechanistically justified and the four points fit
cleanly, but the 5.4 h and 48.5 h figures are **extrapolations, not measurements**, and
they exclude database load time. F4 is the kill test.

### 3.5 Entry-rate scale (HYPOTHESIS, order of magnitude only) and its sensitivity band

FACT (code arithmetic, `intraday_orb.py:94, 97`): with `or_bars = 3`,
`min_bars_before_entry = 3`, `max_bars_after_open = 20`, `time_stop_bars = 12`, entries are
admissible only for `3 ≤ since_open ≤ 16` — a **14-bar** window in a 26-bar session.

HYPOTHESIS (synthetic geometric-random-walk 15 m series, **not** market data): the entry
rate is **≈ 0.42** trades per symbol-session. **The `± 0.04` the proposal attached is the
sampling error of the simulation, not uncertainty about the real rate, and is dropped**
(J1-10/J2-5) — a geometric random walk has neither volatility clustering nor opening-range
persistence, which are precisely the properties that set an ORB entry rate. DERIVED at
that rate on option C: pre-sealed trades ≈ 1,337 tradeable sessions × 24 × 0.42 ≈
**13,500**; OOS ≈ **5,400**; bear-bucket trades ≈ 19 × 24 × 0.42 ≈ **190**.

**Rate-sensitivity band (J2-5), pre-registered so §5's labels can be audited.** OOS
symbol-sessions on option C ≈ 0.4 × 1,337 × 24 = **12,835**.

| Forecast | flips below an entry rate of |
|---|---|
| gate 2 (≥ 30 OOS trades) passes | **0.0023** /symbol-session |
| gate 5's 15-per-cell floor is non-binding | **0.0012** |
| gate 6's bear bucket (≥ 10, over 19 × 24 = 456 symbol-sessions) clears | **0.0219** |

| entry rate | OOS n | gate-4 iid hurdle (sd 1.420) | at `deff` 3 |
|---|---|---|---|
| 0.42 | 5,391 | +0.0579R | +0.0857R |
| 0.25 | 3,209 | +0.0691R | +0.1051R |
| 0.10 | 1,284 | +0.0977R | +0.1546R |
| 0.05 | 642 | +0.1299R | +0.2103R |

Gates 2 and 5 survive as "pass" over essentially the whole plausible band. **Gate 6's bear
bucket is the fragile one**: it needs the realised rate to exceed 2.19% per symbol-session,
and it is the only forecast in §5 whose label the synthetic rate does real work to support.
Gate 4's label depends on the rate *and* on the design effect, which is why §5 withdraws
"not power-limited".

---

## 4. Falsification — stated in advance, cross-snapshot status given for every item

Per R10 each condition must be stated to hold across snapshots 1–4. The structural reason
most are snapshot-invariant: gate 6's labels and the strategy's regime gate both derive
from the **SPY proxy alone**, which is identical in all four snapshots (they differ only by
`META` / `META_CONT` / its absence). The proposal verified this rather than asserting it —
recomputing §3.2 with snapshot 1's pre-sealed end (2025-09-06) and snapshots 2–4's
(2025-09-07) returns identical counts at every start date.

| # | Claim | What kills it (pre-sealed only) | Cross-snapshot status |
|---|---|---|---|
| **F1** | A pre-sealed span starting on/after 2022-09-08 has **zero** long-tradeable bear sessions, so gate 6 is unreachable at that depth | any snapshot on which that span yields ≥ 1 session that is `bear_*` under `label_regimes` **and** `not risk_off` under `regime_lookup`; **or** the evaluation being run with `allow_short=True` / `config/research.py:296 allow_short_candidates` turned on, which opens the 248 short-eligible bear sessions (`scan.py:271`) | **Verified false on all four** (SPY-proxy-driven; identical counts at both pre-sealed end dates) |
| **F2** | Gate 6 returns `0/0/0` with 100% unbucketed for **any** intraday run of the *current* promotion path | any intraday gate-6 evidence blob with a non-zero bucket before B2 lands | **Snapshot-invariant** — a type-level property of `promotion.py:744` vs `backtest/regime.py:25`, independent of universe |
| **F3** | Cost is ≥ 0.1375R per round trip at the frozen 11.0 bps | measuring, after ingest, a **median engine risk unit `d = entry_fill − or_lo` > 0.80% of price** across the 24 symbols pre-sealed. *(Restated on `d`, not `w`, per §A.3(a).)* Pre-sealed anchor: median mean daily `(H−L)/C` = 1.579% (min 1.090% DIA, max 3.663% NVDA) — F3 fails only if the first 45 RTH minutes plus the breakout extension routinely exceed half the day's whole range | **Snapshot-3 symbol set only, and necessarily so:** no other snapshot can carry an intraday snapshot — META has no intraday backfill plan and `META_CONT` is `continuity_bridge:1`-sourced, which fails gate 8 outright (map §0.1). Stated as a scope limit, not a gap |
| **F4** | One full 10-gate evaluation on option C at 15 m exceeds 2 h before B6 | a measured single 24-symbol pre-sealed pass completing in under 12 min | **Snapshot-agnostic**: compute scales with symbols × bars²; 25 vs 24 symbols moves it ~4% |
| **F5** | Live execution cannot reproduce the modelled next-bar-open fill on this entitlement | an entitlement probe recording `latency_category = REALTIME` for any equities feed, or adoption of a bar size strictly greater than the measured feed delay | **Snapshot-independent** (a provider fact) |
| **F6** | The strategy's own regime gate, not the market, produces the bear shortfall | fewer than 10 trades across 24 symbols on the 19 tradeable bear sessions — which would move the diagnosis from "gate shut" to "no signal" and *strengthen* the null option | **Snapshot-invariant** (same 19 SPY-derived sessions on all four) |
| **F7** *(new)* | Any evaluation that clears gate 0 irreversibly creates and locks version 1's first `strategy_sealed_test` row | finding any early return, guard or skip between the gate-0 block and `promotion.py:838`; or a run that clears gate 0 and leaves `strategy_sealed_test` unchanged for `(version 1, that snapshot)` | **Snapshot-independent** — verified today: the only `return _finalize` sites are `:522`, `:571`, `:893` |

**If F1 or F3 falls, the §0 recommendation changes.** If F2, F4 or F7 falls, the
corresponding bundle item is dropped. F5 is the operator's decision gate, not a research
finding.

---

## 5. Gate-by-gate forecast

Trade sets tagged per map §0.2: gates 2/3/4 read `full.out_of_sample`; gates 1/6/7 read
`full.trades` (**all** pre-sealed, IS+OOS — including gate 7, whose docstring at
`config/research.py:111-113` contradicts `promotion.py:775`). Forecasts assume the full
bundle B1–B8 is applied and option C data exists; **without the bundle every gate 1–7 reads
0 trades and fails, and gate 9 still runs and locks** (§A.1).

| Gate | Trade set | Forecast | Confidence |
|---|---|---|---|
| **0** `data_availability` | — | **Pass only under option B or C**, and only after §2.2. Fails on option A by (e) (window < 716 days) and passes (a)–(d) only on a complete, RTH-only, non-simulated, `massive`-sourced, calendar-correct backfill | FACT (arithmetic) |
| **1** `rolling_walkforward` | all pre-sealed (~13,500) | **Pass on the trade-count conjunct** — ~3,400 trades/fold against a floor of 15 (`promotion.py:632`, the shared `sensitivity_min_grid_trades` constant). Whether 2 of 4 folds show `expectancy_r > 0` is the real test and is unforecastable | HYPOTHESIS |
| **2** `min_oos_trades` | OOS (~5,400) | **Pass**, and robust: the label survives any entry rate above 0.0023/symbol-session (§3.5) — a factor of ~180 below the synthetic estimate. The only trivially satisfied gate | HYPOTHESIS on the rate; FACT on the mechanism |
| **3** `net_expectancy` | OOS | **Expected FAIL — the binding gate.** Requires a gross edge exceeding a cost that lifts the break-even hit rate **4.6–14.7 pp** above the geometry's own random-walk baseline (§8), against **1.23 pp** for `trend_continuation`. The realised payoff ratio is additionally **strictly below** the nominal 1.5 (see the target/stop note below) | HYPOTHESIS on the edge; FACT on the cost half |
| **4** `bootstrap_ci` | OOS | **"Not power-limited" is WITHDRAWN (J2-1).** The iid form `exp > 0.02 + 1.96·sd/√n` gives +0.0415R (sd 0.807) to +0.0665R (sd 1.741) at n ≈ 5,391 — but `diagnostics/clustered_bootstrap_all.md:130-155` measures month-block design effects of **2.55 / 3.04 / 4.86 / 2.60 / 2.66** for versions 2–6, and map §4.3 makes reporting them mandatory. An intraday run is the program's worst case for clustering: ~5,400 trades in ~535 OOS sessions across 24 symbols of which 15 are ETFs, several containing the others, so same-morning breakouts are near-replicates. Cluster-adjusted hurdles below | DERIVED |
| **5** `parameter_sensitivity` | OOS per grid point | **Automatic FAIL today** (`promotion.py:694-703`: no `intraday_orb` grid). With §6's grid registered, 9 cells × ~5,400 OOS trades — the 15-trade floor never binds above a rate of 0.0012; positivity is the open question. Cost: 9 extra full passes (§3.4) | FACT on the current failure |
| **6** `regime_coverage` | all pre-sealed | **FAIL today, unconditionally** (F2). After B2: unbucketed ≈ 178/1,337 = **13.3%** of tradeable sessions (the 200-session `label_regimes` warmup, map §0.6); bull ≈ 10,300, **bear ≈ 190**, range ≈ 1,170 at the §3.5 rate. Passes on option C or B; **arithmetically impossible on option A**. Bear is the binding bucket, its ceiling is calendar rather than skill, and its label is the most rate-fragile in this table (flips below 0.0219/symbol-session) | FACT on the mechanism; HYPOTHESIS on counts |
| **7** `benchmark_comparison` | all pre-sealed | **"Unforecastable" is WITHDRAWN (J2-4): expected PASS, and uninformative.** FACT: `portfolio_metrics.py:110` sets `ann_factor = √(trades_per_year)` and `:111` `sharpe = (mean_r/std)·ann_factor`, while `_benchmark_metrics` (`promotion.py:216-238`) computes the SPY side as `cagr/ann_vol` — two different constructions. At ~1,500 trades/yr, √1,500 = 38.73 against SPY's pre-sealed Sharpe of 0.719 (map §2.1), gate 7 needs only `mean_r/std > 0.01856`: **exp > 0.015R** at sd 0.807, **+0.0186R** at 1.0, **+0.0264R** at 1.420, **+0.0323R** at 1.741 — *below* gate 4's own hurdle at every sd. Gate 7 provides **no independent check at this turnover**. `exposure` would also report a clamped 1.0 (`:119`) for a strategy flat overnight | FACT on the construction; DERIVED on the hurdle |
| **8** `data_quality_and_leakage` | — | **Passes vacuously and misleadingly today** — `validate_daily` at `promotion.py:808` would validate the *daily* bars (which pass on snapshot 3) and say nothing about the intraday bars traded. Needs B3, and B7 before it (§A.3(e)). The leakage half is clean (§7) | FACT |
| **9** `sealed_final_test` | sealed year | **Runs unconditionally once gate 0 passes and locks permanently** (§A.1). Needs ≥ 10 trades and expectancy ≥ 0R. Would be **version 1's first sealed test ever** (§10) | FACT on the mechanism |
| **10** `live_paper_probation` | — | `health_monitor.enabled` is true so the gate passes — **but a pass is meaningless for this horizon**: `approved_scope_scan.approved_horizons` excludes INTRADAY (`approved_scope_scan.py:81`, policy comment `:19-22`) and `alerts/dispatch.py:241` skips INTRADAY (`continue  # never alert on intraday signals (EOD-only operation)`). No candidate and no alert could ever be produced | FACT |

**Gate 4 restated as a required n, with the mandatory clustering correction.** Hurdle
`= 0.02 + 1.96·sd·√(D/n)`; required `n = (1.96·sd/(exp − 0.02))²·D`. At n = 5,391:

| per-trade sd | iid (D = 1) | D = 2 | D = 3 | D = 4.86 (program max) | D = 10.08 (n_eff = OOS sessions) |
|---|---|---|---|---|---|
| 0.807 | +0.0415R | +0.0505R | +0.0573R | +0.0675R | +0.0884R |
| 1.000 | +0.0467R | +0.0577R | +0.0662R | +0.0788R | +0.1047R |
| 1.420 | +0.0579R | +0.0736R | **+0.0856R** | +0.1036R | +0.1403R |
| 1.741 | +0.0665R | +0.0857R | +0.1005R | +0.1224R | +0.1675R |

The last column takes the most conservative available clustering assumption, `n_eff` = the
OOS **session** count (~535), which corresponds to `D = 10.08` at this n. **The corrected
statement is: gate 4 passes only if gate 3 passes with roughly 0.06R–0.14R to spare, not
0.05R.** A clustered bootstrap on the realised trades is a required post-ingest diagnostic
(permitted under R4 as a stricter reported statistic, never a gate change).

**Zero-margin cases (§4.2 item 5).** Neither named case is touched: v6's gate-5 neighbour
fraction (0.750 on snapshot 3, already 0.500 on snapshot 4) and v5's bear bucket (11 against
a floor of 10) belong to other versions and nothing here re-evaluates them. The **new**
zero-margin case is `intraday_orb`'s own bear bucket: 19 tradeable bear sessions is the
entire nine-year long-only supply, and the floor of 10 clears only if the realised entry
rate exceeds `10/(19 × 24) = 2.19%` per symbol-session.

**Two strategy-code defects found while forecasting (reported, not proposed as changes).**
FACT: `intraday_orb.py:97` admits entries while `session_bar_count + time_stop_bars ≤
26 + or_bars = 29`, i.e. `since_open ≤ 16`. In a 26-bar RTH session (bars 0–25) an entry at
`since_open ∈ {14, 15, 16}` puts the 12-bar time stop at bars 26–28 — **after the close**.
`_resolve_exit` (`engine.py:152-184`) has no session-boundary awareness, so those positions
are carried **overnight** with the opposite opening-range edge as the stop, exposed to the
gap. FACT: `target_price = close + target_range_mult × width` is measured from the signal
*close* (`intraday_orb.py:108`) while the stop is `or_lo` and the fill is the next bar's
open (`engine.py:107-109`), so the realised reward:risk is
`m·w/(entry_fill − or_lo)`, which is **below** `m` whenever the fill lands above `or_hi`.
**Both are out of scope here** — fixing either is behavioural and requires
`VERSION = "0.2.0"` under R3/R7. They are recorded so no one reads a gate-3 failure as
purely a cost effect, and so a future intraday design starts from them.

---

## 6. Sensitivity-grid plan (gate 5)

§4.2 item 6 requires every parameter a change introduces to become a pre-registered axis.
This design introduces no parameter, so the requirement resolves to R4 carve-out 1:
**register the missing grid for a family that has none** — a genuine ±1-step neighbourhood
around the shipped parameters, written down before any result is seen.

**Pre-registered now, before any intraday bar exists** (`promotion.py:161-210`, a new
`key.startswith("intraday_orb")` branch returning a factory over `ORBParams`):

```
{"or_bars": [2, 3, 4], "target_range_mult": [1.25, 1.5, 1.75]}
```

Rationale, in advance: `or_bars` is the definitional parameter of an opening-range breakout
— it sets both the range and, via `26 + p.or_bars`, the entry-window guard
(`intraday_orb.py:97`); `target_range_mult` sets the payoff ratio that §8's break-even hit
rate turns on. Coverage is **2 of 5** `ORBParams` fields (`intraday_orb.py:28-34`) — the
same 2-of-6-to-8 shortfall map §0.5 criticises, declared rather than hidden. The three
untested fields are `min_bars_before_entry`, `max_bars_after_open` and `time_stop_bars`.

**Why the usual `stop_atr` axis is unavailable (FACT):** every other family's grid pairs a
signal axis with `stop_atr`. `ORBParams` has **no** `stop_atr` — the stop is structural
(`stop_price = or_lo`, `intraday_orb.py:108`). There is no risk-sizing axis to perturb, so
this grid is genuinely two signal axes.

**Mandatory pre-integration no-op check (§4.2 item 6; map §2.1's silent failure mode).**
Before the grid is used in any verdict, confirm each axis measurably moves the OOS trade
count **or** OOS expectancy: run the 3 × 3 grid on the scratch database and assert
(i) the nine `(n_trades, expectancy_r)` pairs are **not all identical**; (ii) `or_bars ∈
{2, 4}` changes `n_trades` — it must, since it changes both the range definition and the
entry-window guard; (iii) `target_range_mult ∈ {1.25, 1.75}` changes `expectancy_r`. A grid
whose nine cells coincide passes gate 5 at 100% having tested nothing. §13 makes this a
blocking checklist item.

**Coupling to disclose (map §4.3):** the per-cell floor `sensitivity_min_grid_trades = 15`
(`config/research.py:106`) is **also** gate 1's per-fold floor (`promotion.py:632`). Neither
may be changed (R4); at the forecast trade scale neither binds (§3.5).

---

## 7. Leakage argument

**Point-in-time contract.** All three intraday features read `(series, t)` with slices
`≤ t`: `bars_since_open` walks backwards from `t` (`features/intraday.py:26-32`);
`opening_range` enumerates `range(t + 1)` (`:38`); `session_bar_count` delegates to
`bars_since_open` (`:52-54`). The module docstring states the contract (`:3-4`). The
strategy reads nothing else except `ctx.regime`.

**Verified, not asserted (FACT, in-process on a synthetic 40-session 15 m series, per the
proposal):** `assert_no_lookahead` (`backtest/leakage.py:23-41`) reports **clean** for
`opening_range(...)[0]`, `opening_range(...)[1]`, `bars_since_open` and
`session_bar_count`. This is the check gate 8 would run under B4; the ladder does not run
it today (`promotion.py:249-267` checks only the four daily features against the daily
proxy).

**Two residual point-in-time concerns, both requirements rather than findings.**

1. **Same-session regime — a genuine lookahead the ladder cannot catch.** `regime_lookup`
   labels a session from that session's own daily bar, whose close is not known while the
   session is being traded. For a *daily* strategy this is harmless (signal at bar `t`'s
   close, fill at `t+1`'s open, so the regime is strictly past). For an **intraday**
   strategy trading inside session `D`, `ctx.regime` for `D` derives from `D`'s own close —
   **future information relative to a 10:15 entry**. It is invisible to
   `assert_no_lookahead` because it lives in the `regime_by_date` plumbing
   (`backtest_runner.py:183, 213-217`, `base.py:38-40`), not in a feature function.
   **Requirement: any intraday run must lag the regime by one session (use `D−1`'s
   label).** This is a behavioural change requiring `VERSION = "0.2.0"` under R3, so it is
   **out of scope here** and recorded as a **blocking prerequisite** for any future
   intraday promotion attempt. *(Escalation note, per the proposal's own self-assessment:
   this is a lookahead, not a nicety. It is stated here at §7's head and again in §11 and
   §14 rather than buried as a sub-item.)*
2. **Session grouping by UTC date.** Covered in §2.4 and B7: RTH-only ingest **and** an
   RTH filter at load, or `_session_date` (`features/intraday.py:19-21`) mis-assigns EST
   post-market bars to the following session.

**No new cross-sectional or breadth term is introduced**, so no new `StrategyContext`
plumbing (`strategies/base.py:15-19`) is needed and no shared surface changes.

---

## 8. Cost-model statement (quantitative, recomputed on the engine's own risk unit)

**The cost model is unchanged (R4).** FACT: `backtest/costs.py:11-16` —
`commission_per_share = 0.0`, `commission_min_per_order = 0.0`, `slippage_bps = 3.0`,
`half_spread_fill_penalty = True`. FACT: `engine.py:90` `spread_bps: float = 5.0`;
`engine.py:94` `slip = (3.0 + 5.0/2)/10,000 = 5.5 bps` per side; `engine.py:144`
`costs_bps = slip × 2 × 10,000 = 11.0` bps of notional per round trip. FACT:
`backtest_runner.py:205-206` never passes `spread_bps`, so the 5.0 bps assumption is
universe- **and horizon**-independent.

### 8.1 The risk unit — the correction both judges demanded, restated correctly

FACT (`engine.py:107-111`): `entry_idx = t + 1`; `entry_fill = series.open[entry_idx] ×
(1 + d·slip)`; `risk_per_share = |entry_fill − sig.stop_price|`. For this strategy
`stop_price = or_lo` (`intraday_orb.py:108`), so the engine's risk unit is

> **`d = entry_fill − or_lo`**, *not* the opening-range width `w = or_hi − or_lo`.

Write `ρ = d/w`. The signal requires `close[t] > or_hi` (`intraday_orb.py:105`) but the
fill is the **next bar's open**, so `ρ > 1` in the modal case (the breakout holds) and
`ρ < 1` when the next bar opens back inside the range. **The proposal's w-anchored table is
therefore the `ρ = 1` special case — neither an upper nor a lower bound**, contrary to both
judges (§A.3(a)). HYPOTHESIS: `E[ρ] > 1`, so the w-table usually *overstates* cost in R.
Measuring the realised `ρ` distribution is item 1 of the post-ingest diagnostic (§12.3).

`cost_R = (round_trip_bps/10,000)/(d/price)`:

| `d/price` | @ 11.0 bps (today) | @ 26 bps (20 bps quoted) | @ 36 bps (30 bps quoted) | @ 66 bps (60 bps quoted) |
|---|---|---|---|---|
| 0.20% | **0.5500R** | 1.3000R | 1.8000R | 3.3000R |
| 0.30% | **0.3667R** | 0.8667R | 1.2000R | 2.2000R |
| 0.50% | **0.2200R** | 0.5200R | 0.7200R | 1.3200R |
| 0.65% | **0.1692R** | 0.4000R | 0.5538R | 1.0154R |
| 0.80% | **0.1375R** | 0.3250R | 0.4500R | 0.8250R |
| 1.20% | **0.0917R** | 0.2167R | 0.3000R | 0.5500R |

Formula sanity check against map §0.4: `trend_continuation` at `stop_atr = 1.5`,
`ATR/price = 2%` gives `risk/price = 3%` and `0.0011/0.03 = 0.0367R`, matching the map's
0.037R exactly.

**Pre-sealed anchor for `w` (FACT, read-only, from the proposal):** across the 24
snapshot-3 symbols over `2016-10-17 … 2025-09-07`, mean daily `(H − L)/C` has median
**1.579%** (min 1.090% DIA, max 3.663% NVDA). HYPOTHESIS: a 45-minute opening range
captures roughly 30–45% of the day's range, putting `w ≈ 0.5–0.7%`. **This fraction is not
verified anywhere in this repo** and measuring it is item 2 of the post-ingest diagnostic.
F3 is the kill test.

### 8.2 The cost wedge — the statistic that survives the risk-unit correction

With a target of `m·w` measured from the close and a stop at `or_lo`, the realised payoff
ratio is `b = m·w/d` and the break-even hit rate is `p* = (1 + c)/(1 + b)` against a
random-walk baseline of `1/(1 + b)`. The **cost wedge** — how far cost lifts the required
hit rate above what the geometry alone demands — has the closed form

> **`wedge = c/(1 + b) = (round_trip/10⁴)/(d + m·w)`**

which depends on `ρ` only through the smaller of the two terms in the denominator. That is
why it, and not the raw multiple, is the right comparator (§A.3(c)). At `m = 1.5`:

| `w` | `ρ = 1.0` | `ρ = 1.2` | `ρ = 1.3` | `ρ = 1.5` |
|---|---|---|---|---|
| 0.30% | 14.67 pp | 13.58 pp | 13.10 pp | 12.22 pp |
| 0.50% | 8.80 pp | 8.15 pp | **7.86 pp** | 7.33 pp |
| 0.80% | 5.50 pp | 5.09 pp | 4.91 pp | 4.58 pp |

**Daily comparators (DERIVED from map §0.4 and the shipped params):**
`trend_continuation` — `stop_atr 1.5`, `target_atr 3.0`, so `b = 2.0`, `c = 0.037R`,
wedge = **1.23 pp**. `volatility_breakout` — `stop_atr 1.75`, `target_atr 3.5`
(`breakout.py:29-30`), so `b = 2.0`, `c = 0.042R`, wedge = **1.40 pp**.

> **`intraday_orb`'s cost wedge is 4.6–14.7 pp against 1.23–1.40 pp for the daily
> strategies — a factor of 3.3× to 10.5× across the plausible opening-range band, and
> 4.0×–5.6× at the hypothesised `w = 0.5–0.7%`, `ρ = 1.3`.**

**Fully worked consistent case (J2-2's required example), `w = 0.5%`, `ρ = 1.3`:**
`d = 0.65%`; `c = 0.1692R` (not the proposal's 0.22R); realised payoff `b = 1.154` (not
1.5); break-even `p* = 54.3%` (not 48.8%) against a random-walk baseline of **46.4%** (not
40.0%); wedge **7.86 pp**. Both the cost and the payoff move together, which is exactly why
the proposal's mixed-unit presentation was misleading and why the wedge is quoted first.

**The raw multiple, corrected (J2-3):** at 11 bps, cost in R is 3.3× (`d = 0.80%`) to 8.7×
(`d = 0.30%`) `volatility_breakout`'s 0.042R, and 3.7×–9.9× `trend_continuation`'s 0.037R.
The proposal's "4–10×" is right at its own hypothesised `w` band and wrong at the edges of
its own table; it is replaced by these figures and by the wedge above.

**Turnover delta.** This design changes no rule, so the turnover delta versus
`intraday_orb` v0.1.0 is **zero by construction**. In absolute terms, DERIVED at the §3.5
rate: ~13,500 pre-sealed trades against v2's 1,169 (map §0.6) — **≈11.5×** the busiest
strategy in the program, so any cost error is amplified ~11.5× at the portfolio level.
Carries the §3.5 rate caveat.

**Expanded-snapshot requirement (§4.2 item 8).** Not applicable — this design uses the
existing 24-symbol snapshot-3 set. Should an intraday run ever be attempted on an expanded
universe, the 2× (26 bps) and 5× (66 bps) columns above are pre-registered as mandatory; the
5× column puts cost above **1R per round trip** for `d ≤ 0.65%`.

**Unmeasurable-spread caveat (FACT).** NBBO quotes return `403 not_authorized`
(`data/entitlements.py`, feed `stocks_nbbo_quotes`), and `universe/screen.py` flags every
symbol `F_SPREAD = "spread_filter_not_licensed"`. **The true opening-auction spread cannot
be measured on this plan at all**, so the 5.0 bps assumption can be neither validated nor
calibrated for the one time of day this strategy trades. Every figure above is therefore
optimistic by an unknown, unmeasurable amount.

---

## 9. Variant budget and stopping rule (whole strategy, all angles combined)

**Strategy variants: 0.** Only one angle was written for this strategy (§4.1 assigns it
one, requirements-only), and it proposes no rule change and no `v0.2.0`. Recorded verbatim
for the final report (R5):

> *`intraday_orb.intraday` — 1 proposal (requirements angle), 0 strategy variants tried,
> 0 pre-sealed backtests of a modified rule set, 0 sealed looks consumed.*

**Non-strategy budget, if and only if the operator authorises the pipeline:**

| Item | Budget | Stopping rule |
|---|---|---|
| Bar size | **1** (15 m) | fixed in advance by `config/research.py:303` and the 26-bar guard at `intraday_orb.py:97`. **5 m is not to be tried** as an alternative — it would be a bar-size search over the same sealed calendar year, a variant in disguise, at 9× the compute (§3.4) |
| History depth | **1** (option C, 2016-10-17) | chosen in advance by §3.2's bear-coverage arithmetic, not by results. If budget permits only option B, that is a cost decision taken before any run |
| Gate-5 grid | **1** (§6, pre-registered before any intraday bar exists) | fixed; the no-op check is a blocking gate on its use, not a tuning loop |
| Bundle dry runs on a **scratch** database | **unlimited** | scratch copies consume no looks and touch nothing live |
| Full promotion evaluations against `data/signalforge.sqlite` | **1, and it is irreversible** | §A.1: the first run past gate 0 locks version 1's only sealed test. If it fails, the outcome is the §11 documented non-pass — **not** a strategy variant. Proposing a `v0.2.0` afterwards requires its own §4.2 document and its own budget, and costs a further look |

**Hard stop.** If any of **F1**, **F4**, **F5** or **F7** holds at decision time — and all
four hold today — the work stops **before ingestion** and the null option is taken. The most
expensive failure mode available is spending ~48 min of API budget, 0.53–1.60 GB on a live
probation database, ~5.4 h of compute **and version 1's only sealed look** to reach a gate-3
failure that §8's arithmetic already forecasts.

---

## 10. Sealed-look accounting

**Reproduction of the map §0.1 ledger (FACT, re-queried read-only for this synthesis:
`strategy_sealed_test` has 20 rows, exactly 4 each for versions 2–6; 42 rows in
`strategy_promotion_evaluation`):**

| Ver | Strategy | snap 1 `universe_25_baseline_legacy` | snap 2 `universe_25_baseline` | snap 3 `universe_24_ex_meta` | snap 4 `universe_25_meta_continuity_corrected` |
|---|---|---|---|---|---|
| 2 | `trend_continuation.short_swing` | id 1: +0.3246R / 112 ✅ | id 6: +0.3246R / 112 ✅ | id 11: +0.2982R / 109 ✅ | id 16: +0.3246R / 112 ✅ |
| 3 | `trend_continuation.medium_swing` | id 2: +0.0109R / 98 ✅ | id 7: +0.0109R / 98 ✅ | id 12: −0.0294R / 95 ❌ | id 17: +0.0109R / 98 ✅ |
| 4 | `mean_reversion.short_swing` | id 3: +0.1230R / 91 ✅ | id 8: +0.1230R / 91 ✅ | id 13: +0.1278R / 84 ✅ | id 18: +0.1230R / 91 ✅ |
| 5 | `relative_strength.medium_swing` | id 4: +0.2935R / 16 ✅ | id 9: +0.2935R / 16 ✅ | id 14: +0.2935R / 16 ✅ | id 19: +0.2935R / 16 ✅ |
| 6 | `volatility_breakout.short_swing` | id 5: −0.0979R / 10 ❌ | id 10: −0.0979R / 10 ❌ | id 15: −0.0979R / 10 ❌ | id 20: −0.0979R / 10 ❌ |
| **1** | **`intraday_orb.intraday`** | **— none** | **— none** | **— none** | **— none** |

**Version 1's own position (FACT, queried):** version 1 has **zero** rows in
`strategy_sealed_test` — that is why the table holds 20 rows and not 24. It has **seven**
promotion evaluations, ids **1, 7, 13, 19, 25, 31, 37** on snapshots 1, 1, 2, 3, 2, 3, 4,
every one `passed = 0`, all stopped at gate 0 before any sealed window was opened.

**What this design costs in looks: zero.** No evaluation, no new `StrategyVersion`, no run
that could reach gate 9. `intraday_orb`'s count stays at **0**; the program's baseline stays
at **k = 5**.

### 10.1 The numbering convention, made self-consistent, and the map's own contradiction

Both judges flagged that "k = 5 (four existing locked sealed draws per strategy family plus
the next one)" followed by "look 6 (k = 5 baseline + 1)" double-counts the next draw, and
that "four existing draws" is **false for this family** (version 1 has zero).

**Open item for the operator — the map contradicts itself and this design does not silently
pick the larger number.** `STRATEGY_COMPLETION_MAP.md` §0.1 and R2 both say *"A v0.2.0 that
seals against snapshot 3 is the **fifth** look"*; §4.2 item 10 says *"the baseline count is
k = 5 … so a first v0.2.0 sealing on snapshot 3 is **look 6**."* These cannot both be right.

**Convention adopted here, and it is to state all three numbers every time**, so that no
reader depends on which clause the program later settles on:

1. **Program-wide sealed-test row number** — unambiguous and queryable: 20 rows exist, so
   the first intraday sealed test is **row 21**.
2. **Program look number** under the brief's and §4.2 item 10's `k = 5` baseline:
   **look 6**.
3. **This strategy's own look number**: **version 1's look 1** — version 1 contributes
   **none** of the four baseline draws, a fact that must be stated whenever number 2 is
   quoted, because otherwise "look 6" implies a selection history this strategy does not
   have.

### 10.2 Accounting for any future intraday evaluation, pre-registered now

- An evaluation of the **unchanged v0.1.0** on the new keyed snapshot
  `universe_24_ex_meta_intraday_15m` that clears gate 0 creates `strategy_sealed_test`
  **row 21** — **program look 6, version 1's look 1** — and it does so **whether or not
  gates 1–8 pass** (§A.1). There is no such thing as a trial run.
- A subsequent `v0.2.0` on the same snapshot would be **row 22 / program look 7 /
  version 1-lineage look 2**; a `v0.2.0` on both the intraday and an expanded snapshot would
  be rows 22–23 / looks 7–8.
- **Which snapshot the report leads with, pre-registered (R1):**
  `universe_24_ex_meta_intraday_15m` — because its symbol set is snapshot 3's, the only
  symbol set on which gate 8 `validate_daily` passes (map §0.1), and because no other
  intraday snapshot can exist (META has no intraday plan; `META_CONT` is
  `continuity_bridge:1`-sourced and fails gate 8). The four daily draws in the table above
  are disclosed alongside it in every case, together with the explicit statement that
  version 1 contributes none of them.
- **R3 trap check, corrected.** The proposal asserted the staleness trap "cannot" occur
  because no strategy code changes. That assertion is **withdrawn**: the trap here arrives
  through the *promotion path*, not the strategy code (§A.1). `upsert_strategy_version`
  (`persistence.py:46-93`) refreshes `spec_json`/`git_sha` on the same row while
  `_get_or_create_sealed_test` replays the locked result, so a first bad run and a later
  good run on the same `(version 1, snapshot)` pair return the same sealed number. The
  mitigations are §13's scratch-only rule and its pre-integration check that no
  `strategy_sealed_test` row exists for `(version 1, the intraday snapshot id)` before the
  single live evaluation, and that the row created afterwards was created by *that* run.
  Any future behavioural change — including the §7 regime-lag fix and the §5 leash/target
  defects — ships as `VERSION = "0.2.0"`.

---

## 11. Null option — and it is the recommendation, not the fallback

**What gets written:** a documented, evidence-backed **"DOES NOT OPERATE"** record for
`intraday_orb.intraday` v0.1.0 — the second of the two honest end-states
`STRATEGY_COMPLETION_PLAN.md` allows, and **distinct from the "does not pass" records** v3,
v4 and v6 may earn. The distinction matters and must survive into the final report: those
three can fail on *evidence*; version 1 has never been measured and, on current
entitlements, cannot be. Its record is a **capability** finding and must not be filed as
though the rules had been tested and found wanting.

**Evidence it carries** (all pre-sealed or code arithmetic, all reproducible read-only):

1. The three independent blocks from map §2.4, with the R4 correction: the promotion-path
   gate is removable in principle (§2.2); the EOD-only operating policy
   (`approved_scope_scan.py:81` with its `:19-22` comment; `alerts/dispatch.py:241`) and the
   absent data path (`massive.py:86-100` declares only `BAR_DAILY`) are not.
2. **A fourth block the map did not state — latency.** The entitled intraday feed is
   `DELAYED`; `LatencyCategory.REALTIME` is never set anywhere in the codebase; the engine
   fills at the next bar's open. Any delay of one bar or more makes the modelled fill
   unattainable live.
3. **A fifth block — cost.** A break-even wedge of **4.6–14.7 pp** at the frozen, optimistic
   11.0 bps, against 1.23–1.40 pp for the daily strategies — 3.3×–10.5× — with the true
   opening-auction spread **unmeasurable** on this plan (§8).
4. **A sixth block — irreversibility.** The first run past gate 0 permanently locks version
   1's only sealed test, whatever gates 1–8 did (§A.1). There is no cheap way to find out.
5. The measured build cost of finding out anyway: 240 paced API calls / ~48 min; ~0.53 GB
   added to a 0.38 GB live database (resulting ~2.4×); ~5.4 h of compute per evaluation
   before the `O(n²)` fix (§3.3, §3.4).
6. The gate-6 calendar ceiling: **19** long-tradeable bear sessions in nine pre-sealed years
   (7.12% ± 1.57%), none after 2023-06-02, zero at any pre-sealed start on or after
   2022-09-08 — with the disclosure that 248 bear sessions are short-eligible and the
   long-only ladder cannot reach them (§3.1).
7. The eight promotion-path defects B1–B8 (§2.3), the two behavioural defects (§5), and the
   **same-session regime lookahead** (§7 item 1) — which is a genuine lookahead that
   `assert_no_lookahead` structurally cannot catch, and which would by itself force a
   `v0.2.0` before any intraday number could be believed.

**Sealed-window use in this section, marked per R1 (disposition — permitted):** the sealed
year plays no part in the argument above. `intraday_orb` has no sealed test to cite (§10),
and that absence *is* the disposition fact: **nothing in this program's sealed evidence has
ever bound on this strategy, so declining to build the pipeline forfeits no measured edge.**

**Status the record carries:** `EXPERIMENTAL`, unchanged — no downgrade, no approval, no
deletion. `Strategy` id 1 stays as it is. The record is a document, not a database change.

**What would reopen it (pre-registered re-entry condition, so this is not relitigated
quarterly):** a real-time — not `DELAYED` — U.S. equities entitlement verified by
`data/entitlements.py`, **plus** a measured effective opening-auction spread for the
24-symbol universe (which today requires an NBBO entitlement returning `403`), **plus** an
operator decision to change the EOD-only policy. Absent all three the answer is stable.

---

## 12. Pre-registration record — frozen BEFORE any run

Everything in this section is fixed now and may not be revised after any intraday bar is
ingested or any number is seen. It is reproduced verbatim into the final report.

### 12.1 Gate-5 axes, and the gate-0 thresholds' basis

- **Gate-5 grid:** `{"or_bars": [2, 3, 4], "target_range_mult": [1.25, 1.5, 1.75]}` — a
  ±1-step neighbourhood around the shipped `or_bars = 3`, `target_range_mult = 1.5`
  (`intraday_orb.py:29, 32`). Coverage 2 of 5 `ORBParams` fields, declared. No `stop_atr`
  axis exists for this family (§6). Untested: `min_bars_before_entry`,
  `max_bars_after_open`, `time_stop_bars`.
- **No-op check** (§6) is a blocking precondition on any gate-5 verdict.
- **Gate-0 threshold basis (J1-8).** Condition (b) is set at **99%** session coverage, not
  the proposal's 95%, because the daily path's own `validate_daily` treats missing sessions
  as a finding at all (map §0.1 shows a 6.9% META gap failing gate 8 outright), so a 5%
  intraday tolerance would be looser than the daily standard the same universe already
  meets. Condition (c) is set at **100%** against an explicit exchange-calendar bar count
  per session type, because set membership against a known calendar has no legitimate
  tolerance — a wrong bar count is either an early close (enumerable) or corruption.
  Condition (d) inherits `approved_scope_scan.data_readiness`'s existing freshness bound
  verbatim rather than inventing one. All four are strictly harder than the hard-coded fail
  they replace (R4).

### 12.2 Falsification criteria, per snapshot

F1–F7 as tabulated in §4, each with its cross-snapshot status stated: F1, F2, F6 verified
snapshot-invariant (SPY-proxy-driven); F4, F5, F7 snapshot-independent by construction; F3
scoped to the snapshot-3 symbol set with the reason no other snapshot can carry an intraday
snapshot stated explicitly. **F1 or F3 falling changes the recommendation. F2, F4 or F7
falling drops the corresponding bundle item.**

### 12.3 Post-ingest diagnostics that must run before any gate verdict is read

1. The realised **`ρ = (entry_fill − or_lo)/w` distribution** — median and IQR — which is
   the unit every cost figure in §8 depends on and which cannot be estimated without bars.
2. The realised **median `w`** (opening-range width as a fraction of price) across the 24
   symbols pre-sealed, against F3's 0.80% kill line on `d`.
3. The realised **entry rate** per symbol-session, replacing §3.5's synthetic figure, and a
   re-read of every §5 label against §3.5's sensitivity band.
4. A **clustered / block bootstrap** (month blocks and symbol blocks) alongside the gate-4
   iid CI, per map §4.3 — a stricter reported statistic, permitted under R4, never a gate
   change.
5. The **exit-reason mix**, specifically the share of entries at `since_open ∈ {14, 15, 16}`
   whose time stop lands after the close and which are therefore carried overnight (§5).

### 12.4 Variant budget and stopping rule

§9, in full: 0 strategy variants; bar size 1; history depth 1; gate-5 grid 1; unlimited
scratch dry runs; **exactly one irreversible evaluation against the live database**. Hard
stop if F1, F4, F5 or F7 holds — all four hold today.

### 12.5 Lead snapshot and sealed-look accounting

Lead snapshot: **`universe_24_ex_meta_intraday_15m`**, with the four daily draws disclosed
alongside and version 1's zero contribution to them stated (§10.2). Any first intraday
sealed test is reported simultaneously as **`strategy_sealed_test` row 21**, **program
look 6** (k = 5 baseline), and **version 1's own look 1**, with the map's §0.1-vs-§4.2
numbering contradiction flagged to the operator (§10.1). Looks this design adds: **zero**.

---

## 13. Implementation checklist (only if the operator authorises §14 Q1)

Nothing in this list may begin before an affirmative answer to Q1. Items are ordered; each
is blocking on the ones above it.

### 13.1 Files touched

| Area | File | Change |
|---|---|---|
| Adapter | `src/signalforge/data/adapters/massive.py` | add `fetch_intraday_bars` satisfying `IntradayBarAdapter` (`adapters/base.py:138-149`); declare `BAR_INTRADAY` in `capabilities()` (`:86-100`); calendar chunking (the daily path rejects `next_url` at `:186`); RTH-only window |
| Load | `src/signalforge/data/series.py` | **B7** — `load_intraday` (`:105-136`) must filter `session` and `is_simulated` |
| Validate | `src/signalforge/data/validate.py` | **B3** — add `validate_intraday` beside `validate_daily` (`:66`) |
| Promotion | `src/signalforge/research/promotion.py` | **§2.2** gate 0 (`:512-534`); **B1** `:386`, `:586`, `:708`; **B2** `:744` *(as a rider on `diagnostics/pipeline_hardening_spec.md` §1.5 Change A — one patch, not two)*; **B4** `:249-267`; **B5** `:161-210`; **B3** wiring at `:808` |
| Features | `src/signalforge/research/features/intraday.py` | **B6** — precompute session boundaries; `opening_range` (`:38`) must not rescan `range(t+1)` |
| CLI / snapshot | `src/signalforge/cli.py`, `research/fb_meta_universe_comparison.resolve_variant` | **B8** — an explicit intraday dataset variant minting `universe_24_ex_meta_intraday_15m`; never allow the unkeyed path (`promotion.py:505`) for an intraday run |
| **Not touched** | `research/strategies/intraday_orb.py`, `config/research.py:93-123`, `backtest/costs.py:11-16`, `research/approved_scope_scan.py`, `alerts/dispatch.py` | strategy unchanged (`VERSION = "0.1.0"`); no threshold, no cost-model change (R4); the two policy surfaces are out of scope for this program (map §2.4) |

### 13.2 Tests

- `tests/data/test_intraday.py` — extend: RTH-only load, `is_simulated` exclusion, the UTC
  `_session_date` post-market misassignment case, early-close bar counts.
- `tests/data/test_massive.py` — the new adapter: pacing, calendar chunking, `next_url`
  absence, capability declaration.
- `tests/backtest/test_engine.py` — a session-boundary case: an entry at `since_open = 16`
  whose 12-bar time stop lands past the close.
- `tests/research/test_promotion.py` — gate 0 passing and failing on each of conditions
  (a)–(e); gate 6 bucketing an intraday `datetime` `entry_date` correctly after B2; gate 5
  no longer hard-failing for the `intraday_orb` prefix.
- `tests/research/test_sensitivity.py` — the `intraday_orb` grid factory round-trips
  `ORBParams` (a renamed field must raise `TypeError` loudly, `promotion.py:50`).
- `tests/research/test_backtest_runner.py` — `intraday=`/`bar_size=` threading from the
  promotion call sites.
- Full gate: `make check` (`lint` + `test`), plus `make safety` and `make secrets`.

### 13.3 Blocking pre-integration checks

1. **No-op grid check (§6).** Run the 3 × 3 grid on the scratch database and assert the nine
   `(n_trades, expectancy_r)` pairs are not all identical, that `or_bars ∈ {2, 4}` moves
   `n_trades`, and that `target_range_mult ∈ {1.25, 1.75}` moves `expectancy_r`. **Gate 5's
   result is void until this passes.**
2. **Sealed-test staleness guard (R3, map §4.3, §A.1).** Before the single live evaluation,
   assert `SELECT count(*) FROM strategy_sealed_test WHERE strategy_version_id = 1` is
   **0**. Afterwards, assert exactly one row exists and that it was created by that run
   (compare `id` against the pre-run `max(id) = 20` and the recorded
   `dataset_snapshot_id`). If a row already exists, **stop**: the look is already spent and
   any number produced is a replay.
3. **Spec-hash non-disturbance (R7).** Before and after, record
   `approval_scope.current_spec_json_hash()` for version 2 and version 5 and assert both are
   unchanged; nothing here touches a `StrategySpec`, so any movement means an unintended
   edit. Re-record the R7b state (v2 → sealed test 11; v5 → sealed test 14; both scopes on
   snapshot 3) and confirm the probation dashboard still shows those after the run — a new
   passing evaluation on a *different* snapshot would make `scopes[0]`
   (`paper_probation.py:118`, `approval_scope.py:45-66`, no `order_by`) order-dependent.
4. **Snapshot-key check (B8).** Assert `universe_24_ex_meta_intraday_15m` does not collide
   with any `universe_auto_*` (`promotion.py:339`) or `liquid_us_*` (`screen.py:259`) row —
   FACT: ten `data_snapshot` rows exist today, ids 1–10 — and that the run resolves to it
   rather than to snapshot 3 (`reusable_by_new_evaluations = 1`).
5. **Worker stopped, maintenance window open** before any ingest touches
   `data/signalforge.sqlite`.

### 13.4 Exact commands the validation phase runs — SCRATCH DATABASE ONLY

Every command below runs against a copy. Nothing in this phase may write
`data/signalforge.sqlite`.

```bash
cd /Users/louisbrailey/signal-forge

# 0. Scratch copy (repeat from a fresh copy for each clean run).
cp data/signalforge.sqlite "$TMPDIR/scratch-orb.sqlite"
export DATABASE_URL="sqlite+pysqlite:///$TMPDIR/scratch-orb.sqlite"
.venv/bin/python -c "import os;print(os.environ['DATABASE_URL'])"   # confirm before anything else

# 1. Static gates (no DB).
make lint
make test
make safety
make secrets

# 2. Ingest into the SCRATCH copy only (requires the new adapter; paced, ~48 min for option C).
.venv/bin/signalforge ingest-intraday --bar-size 15m --days 3620 \
  --symbols "$(.venv/bin/python -c "
import sqlite3,json
c=sqlite3.connect('file:data/signalforge.sqlite?mode=ro',uri=True)
print(','.join(json.loads(c.execute(\"select symbols_json from data_snapshot where key='universe_24_ex_meta'\").fetchone()[0])))")"

# 3. Post-ingest diagnostics (§12.3) — read-only, in-process, no writes.
.venv/bin/python scripts/orb_post_ingest_diagnostics.py     # rho, w, entry rate, clustered bootstrap, exit mix

# 4. Gate-5 no-op check (§6, §13.3 item 1) — must pass before any gate-5 verdict is read.
.venv/bin/python scripts/orb_grid_noop_check.py

# 5. Full 10-gate dry run on the scratch copy — as many times as needed.
.venv/bin/signalforge evaluate-promotion \
  --strategy intraday_orb --dataset ex_meta_intraday_15m \
  --since 2016-10-17 --until 2026-09-08

# 6. Staleness / spec-hash / snapshot checks (§13.3 items 2-4) against the scratch copy,
#    then re-run them against a FRESH copy to confirm they are deterministic.
.venv/bin/python scripts/orb_preintegration_checks.py
```

Only after every item in §13.3 passes on the scratch copy, and only with the operator's
explicit go-ahead on the record, is `DATABASE_URL` unset and step 5 run **exactly once**
against `data/signalforge.sqlite` — with the worker stopped. That single run is
irreversible (§A.1).

*(`scripts/orb_*.py` are new files created by the implementation phase; they are named here
so the plan is auditable, and each is read-only against the database except for the
promotion command itself.)*

---

## 14. What the operator must approve, and what is reported if it fails

### 14.1 Approvals required before any implementation begins

| # | Approval | Why it is the operator's call, not research's |
|---|---|---|
| **A1** | **Buy a real-time (not `DELAYED`) U.S. equities entitlement**, or accept that the modelled fill is unattainable live | A spend decision, and the precondition for everything else. Without it, a passing backtest describes a fill the system cannot obtain (§0 finding 2, F5) |
| **A2** | **~240 paced provider API calls (~48 min) for the option-C intraday backfill** | This is the W1-equivalent sign-off the map §4.0 requires for any paced API work; it is the only item here that spends provider budget |
| **A3** | **Accept ~0.53 GB added to the live database (0.38 GB → ~0.91 GB, ~2.4×), inside a maintenance window with the worker stopped**, or direct the intraday bars to a sidecar store instead | It is the same SQLite file a live paper probation and a background worker use |
| **A4** | **Spend version 1's only sealed look**, knowing the first run past gate 0 locks it irreversibly whatever gates 1–8 do (§A.1) | This is a one-way door and it is not recoverable by re-running |
| **A5** | **Change the EOD-only operating policy**, or accept that a passing intraday strategy still cannot produce a live candidate | `approved_scope_scan.py:81` (`:19-22` policy comment) and `alerts/dispatch.py:241` are policy surfaces, out of scope for this program (map §2.4) |
| **A6** | **Authorise a `v0.2.0` for the same-session regime lookahead** (§7 item 1) before any intraday number is believed | It is a genuine lookahead the ladder structurally cannot catch, and fixing it is behavioural, hence a version bump and a further look |
| **A7** | **Rule on the two open map items**: gate 7's docstring-vs-code divergence (`config/research.py:111-113` vs `promotion.py:775`), and the §0.1-vs-§4.2 sealed-look numbering contradiction (§10.1) | Both are program-wide; the second changes how every strategy's report numbers its looks |

**The recommendation is that A1 is answered "no", in which case A2–A7 do not arise and §11
is the outcome.**

### 14.2 The operator questions, restated

- **Q1 (decisive) — do you want intraday operation at all, given the policy is currently
  also an entitlement fact?** Relaxing the EOD-only policy does **not** make intraday
  operable, because the entitled feed is `DELAYED` and no `REALTIME` equities feed exists on
  this plan. The real question is *"will you buy a real-time equities entitlement?"* Until
  that is yes, the honest answer to Q1 is **no**.
- **Q2 — convert gate 0 to a real data query (R4-permissible)?** Recommendation: **only
  bundled with B1–B8, or not at all.** Alone it converts a truthful, self-explaining hard
  fail into zero-trade gate failures that read as strategy defects **and** exposes the
  sealed-lock trap (§A.1). It buys nothing while blocks 2 and 3 stand.
- **Q3 — history depth, if Q1 is yes?** Option A is **not viable** (0 bear, 0 range
  sessions; gate 6 arithmetically unreachable). Option B (2021-09) is the minimum admitting
  any bear coverage (16 sessions). Option C (2016-10, parity with the daily program) gives
  19. **Recommendation if proceeding: C.**
- **Q4 — operational risk to the live probation?** §3.3 and A3.
- **Q5 — gate 7's docstring/code divergence?** Open from map §0.2; an intraday run at
  ~1,500 trades/year makes the `√(trades_per_year)` annualisation
  (`portfolio_metrics.py:110`) far more consequential than for a 100-trade/year swing
  strategy — see §5, where it makes gate 7 an expected but uninformative pass.

### 14.3 What is reported if this fails

Three distinct failure reports are pre-registered, so that none of them can be presented as
another:

1. **If Q1 is answered "no" (the expected outcome).** The §11 record is filed:
   *`intraday_orb.intraday` v0.1.0 — **DOES NOT OPERATE**, a capability finding, not an
   evidence finding.* It carries the six blocks of §11, states `0 variants / 0 sealed looks
   consumed`, keeps status `EXPERIMENTAL`, changes no database row, and carries the
   pre-registered re-entry condition so the question is not reopened quarterly.
2. **If the pipeline is authorised and the single evaluation fails a gate.** The report is a
   documented **"does not pass"** naming the binding gate, the trade set it was measured on
   (map §0.2), the realised `ρ`, `w`, entry rate and cost wedge against §8's forecast, the
   gate-4 hurdle at both the iid and the measured clustered design effect, gate 6's three
   buckets **and** its unbucketed count, and the disclosure that the result is **row 21 /
   program look 6 / version 1's look 1** with the four daily draws alongside. It states
   explicitly that this is version 1's only look and that it is spent.
3. **If the pipeline is authorised and the run is invalidated by a defect** (a bundle item
   missed, gate 0 passing on contaminated bars, the sealed row already locked by an earlier
   run). The report is a **process failure**, not a strategy result: it names the defect, it
   does **not** quote the gate numbers as evidence about the strategy, and it records that
   the look is spent and cannot be recovered without a `VERSION` bump or a new snapshot key —
   each of which costs a further look. §13.3's checks exist to make this outcome
   detectable rather than silent.

---

*Design of record, `intraday_orb.intraday` v0.1.0. Read-only: no strategy code, no
configuration, no database row and no gate threshold was changed in producing this
document. No provider API was called. Every number is a `SELECT` result, a `file:line`
citation, an in-process read-only computation, or an arithmetic derivation whose inputs are
stated.*
