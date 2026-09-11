# Proposal — `trend_continuation.medium_swing` v0.1.0 (version 3), angle: **THE NULL OPTION**

**Angle:** §4.1 "null option (primary)" — argue on the merits that v0.1.0 should **not**
be changed, and that the correct outputs are (a) a documented "does not pass" carrying
the full four-snapshot ledger, and (b) a pre-registered live-paper (shadow) confirmation
plan.
**Author role:** independent proposer. **Date:** 2026-09-10.
**Structure:** the eleven mandatory sections of `STRATEGY_COMPLETION_MAP.md` §4.2, in order.

> **Safety / provenance.** Everything below is read-only. `data/signalforge.sqlite` was
> opened only with `mode=ro` `SELECT`s; no promotion evaluation, backtest-write entry
> point or migration was run; no file under `src/` or `tests/` was touched; no provider
> API was called. **No `StrategySealedTest` row was created or read into a design
> argument, so the sealed-look count is unchanged (§10).** Every claim is labelled
> **FACT** (with `file:line`, a query, or an arithmetic derivation from those) or
> **HYPOTHESIS**, and every estimate carries a standard error. A difference under 2 SE is
> not treated as evidence.
>
> **R1 disclosure — where sealed numbers appear in this document and why that is
> permitted.** R1 permits sealed numbers to inform *disposition* (ship / stop / document
> a fail) and forbids them from motivating a parameter, filter, entry, exit or universe
> choice. This proposal's entire recommendation is a **disposition**: change nothing.
> Sealed numbers therefore appear deliberately in §1 (framing), §5 (gate 9), §8 (cost
> comparison), §10 (the ledger) and §11. **No sealed number motivates any change to
> `src/`, because this proposal makes none.** The sections that *do* constrain future
> design — §3 (pre-sealed evidence), §4 (falsification and re-run triggers), §6
> (grid) — are built exclusively from pre-sealed data, and §4 explicitly disqualifies
> the sealed miss as a motivation.

---

## 1. Mechanism

**The claim is a negative one, and it is a claim about markets, not about the backtest:
there is no identified defect in `trend_continuation.medium_swing`'s rule set, and the
one gate it fails is a measurement with no power at the point where it is being read.**

The economic mechanism v0.1.0 encodes is intact and, on nine years of pre-sealed data,
it works exactly as designed. FACT: the strategy is a *target-driven* trend-continuation
rule — 41.5% of its 1,071 pre-sealed snapshot-3 trades exit at the 3.0×ATR target at a
mean of +1.8156R ± 0.0493 after 10.9 bars, 57.1% exit at the 1.5×ATR stop at −1.0375R ±
0.0164, and the whole edge is target-driven: **+807.92R of the +813.50R of gross positive
exit-reason P&L (99.3%) comes from target hits**
(`docs/research/diagnostics/v3_duration_exits.md` §2a). The 40-bar leash is not a
liability; it is the reason the target is reachable. FACT (matched-pair, same entries,
only `time_stop_bars` differs): holding past bar 10 converts 59.2% of the positions the
approved v2 abandons into full target hits and 37.2% into stops, netting **+0.1770R ±
0.0777 per affected trade** and **+0.0524R ± 0.0231 (2.3 SE) per matched trade** on the
whole pre-sealed span, on all four snapshots (`v3_duration_exits.md` §4).

Against that, every mechanism §2.1 nominated as a possible defect is now dead or
unsupported **on pre-sealed data, on all four snapshots**:

| §2.1 hypothesis | Status after W2 | Decisive pre-sealed number |
|---|---|---|
| **H1** duration mismatch | **FALSIFIED** (all 4 snapshots, IS+OOS and OOS) | OOS per-bar R: 11–20 bucket **+0.0394…+0.0438**, 21–40 bucket **+0.0393…+0.0401**, vs 1–5 bucket **−0.035…−0.042**. The long buckets are the *best* ones (`v3_duration_exits.md` §5) |
| **H2** target unreachable in the leash | **FALSIFIED** (all 4) | time stop is the **rarest** exit: 8 of 1,071 pre-sealed (0.7%), 1 of 319 OOS (0.3%), and pays **+0.3493R ± 0.1716** when it fires (`v3_duration_exits.md` §2a, §5) |
| **H3** stale volatility scale | **NOT SUPPORTED**; its own falsification criterion met | ATR@exit/ATR@entry median **1.0565 ± 0.0047**, 83.9% within ±25%; v3−v2 median difference **+0.0012 ± 0.0062** (z = +0.19); the −0.4381R ± 0.1217 tercile gradient vanishes within `stop` exits (**+0.0059 ± 0.0371**) and is **−0.1320 ± 0.2533 OOS** (`v3_atr_at_exit.md` §1, §4.3, §5) |
| **H5** short-side asymmetry | **structurally absent** | all 9,130 collected trades are LONG; `evaluate_promotion` never sets `allow_short`, so `trend_continuation.py:113-133` is dead code under every gate (`v3_duration_exits.md` §0, §6b) |
| **H4** volume confirmation decays | **UNTESTED** — and unmotivated | no W2 diagnostic exists. It was demoted with H1–H3 because it rested on the same snapshot-3 gate-9 number, which §2.1 has withdrawn as support (see §4.2 below) |

FACT: the only coded difference between v3 and the **PAPER_APPROVED** v2 is one line —
`TrendParams(time_stop_bars=40) if horizon is MEDIUM_SWING else TrendParams()`
(`src/signalforge/research/strategies/trend_continuation.py:36-39`). Every other
parameter is byte-identical (`:21-29`), and entry/exit logic is shared verbatim
(`:85-133`). There is no medium-swing-specific code to have overfit, and the one
medium-swing-specific *behaviour* is, on pre-sealed evidence, the better of the two.

**Why gate 9's verdict carries almost no information here.** Gate 9 is
`n ≥ 10 and expectancy ≥ 0.0R` (`config/research.py:121-123`, `promotion.py:402`) — a
**sign test at a threshold of exactly zero**. DERIVED, using the directly measured
pre-sealed OOS per-trade sd of **1.7259** (`clustered_bootstrap_all.md` §3;
`v3_atr_at_exit.md` §0 measures the same 1.726, against §0.3's CI-inverted 1.741) at the
sealed count n = 95: SE = **0.1771R**.

| true per-trade expectancy | P(sealed 95-trade mean < 0) = P(gate 9 fails) |
|---|---|
| +0.3064R (the pre-sealed OOS estimate) | **4.2%** |
| +0.1667R (the pre-sealed all-trades mean) | 17.3% |
| +0.1000R | 28.6% |
| **0.0000R** | **50.0%** |

A threshold at zero means gate 9 rejects a *genuinely zero-edge* strategy half the time
**at any sample size** — more data narrows the estimate but never moves that 50%. So the
observed −0.0294R is one draw from a distribution whose centre the data cannot locate:
the sealed mean is **−0.17 SE** from zero (−0.0294/0.1771; −0.165 SE using §0.3's sd),
and the three other snapshots' +0.0109R on 98 trades is **+0.06 SE** from zero. Both
draws say the same thing — *we cannot tell this year's expectancy apart from zero* — and
the two verdicts differ only because the threshold sits exactly at the point estimate's
own neighbourhood.

**The size of the thing being "fixed".** DERIVED: total sealed R on snapshot 3 is
95 × (−0.0294) = **−2.793R**. That is **1.54** average target hits (+1.8156R each), or
**2.69** average stops avoided (−1.0375R each). Adding **two** average target hits to
the sealed year turns −0.0294R into **+0.0086R on 97 trades — a gate-9 pass**. The whole
verdict turns on roughly two trades in ninety-seven. FACT (and this is the same fact
from the other direction): the entire gap between snapshot 3 and snapshots 1/2/4 is
**3 META trades worth +3.861R** (98 × 0.0109 − 95 × (−0.0294)), i.e. +1.287R each — one
symbol's ordinary target hits.

**And the shortfall is smaller than one trade's transaction cost.** FACT: the measured
median ATR/price at v3's own entries is **1.29%** (IQR 0.98%–1.76%), so the modelled
11.0 bps round trip (`engine.py:94,143`) costs **0.057R per trade**
(`v3_atr_at_exit.md` §5). DERIVED: the sealed shortfall of 0.0294R is **52% of one
trade's modelled cost**.

**The mechanism claim, stated as the hypothesis it is.** HYPOTHESIS (the null): v3's
true expectancy is in the region the pre-sealed evidence estimates (+0.31R ± 0.10R OOS),
the sealed year is an uninformative draw from a distribution centred somewhere between
zero and that, and no rule change is available that is motivated by anything other than
the miss itself. Under R10 the falsifier is stated in §4; under R1 the miss may not
motivate a change; under R5 every change attempted here costs credibility that the gates
cannot restore. **On the merits, the correct action is to change nothing.**

---

## 2. Exact change — file, symbol, before → after

**The change set under `src/` and `tests/` is empty.** Stated explicitly for each of
§2.1's four implementation touchpoints, because "no change" is a claim that has to be
auditable:

| File / symbol | Before | After | Note |
|---|---|---|---|
| `src/signalforge/research/strategies/trend_continuation.py:19` `VERSION` | `"0.1.0"` | **`"0.1.0"` (unchanged)** | No new `StrategyVersion` row; R3's staleness trap cannot be tripped because nothing is edited |
| `…/trend_continuation.py:21-29` `TrendParams` | `sma_fast=20, sma_slow=50, vol_window=20, vol_mult=1.3, atr_window=14, stop_atr=1.5, target_atr=3.0, time_stop_bars=10` | **unchanged** | including the MEDIUM_SWING branch `time_stop_bars=40` at `:36-39` |
| `…/trend_continuation.py:85-133` `evaluate` | long/short branches as shipped | **unchanged** | no condition added or removed |
| `…/trend_continuation.py:42-83` `spec()` | as generated from params | **unchanged** | `spec_json_hash` therefore unchanged — see the R7 note below |
| `src/signalforge/research/strategies/__init__.py:43-51` `default_strategies()` | 6 entries | **6 entries (unchanged)** | no v0.2.0 sibling registered |
| `src/signalforge/research/promotion.py:178-187` (`trend_continuation` grid) | `{"sma_fast": [15,20,25], "stop_atr": [1.2,1.5,1.8]}` | **unchanged** | see §6 for why touching this is *not* free |
| `tests/` | — | **unchanged** | no behaviour changes, so no test changes |

**What this proposal *does* produce** (documents and one read-only tool, never `src/`):

1. **D1 — the documented "does not pass".** A new report at
   `reports/trend_continuation.medium_swing-0.1.0-does-not-pass.md`, sitting alongside the
   existing `reports/trend_continuation.medium_swing-0.1.0.md`. Contents are specified in
   §11.
2. **D2 — the pre-registered shadow-confirmation plan** (§11.2), written *before* any
   forward data is read, and its periodic read-only read-outs.
3. **D3 — a read-only shadow-ledger script** (implement phase; a standalone script, not a
   `src/` module, no DB writes, no API calls). Specified in §11.2 and leakage-argued in §7.

**R7 / R7b safety of the null option (FACT, and the reason "do nothing" is strictly safer
than any change):**

- `persistence.spec_json_hash` hashes every `StrategySpec` field except `git_sha`,
  `status`, `notes` (`persistence.py:29,32-43`). Because nothing in `spec()` changes,
  v2's stored hash `2ed97431…` and v5's `dfe696b6…` — the hashes on the passing
  evaluations that scope the two live approvals (evals 20 & 32, 23 & 35) — are untouched,
  so `scan_scope_matches` (`approval_scope.py:69-94`) keeps returning `True` and the live
  probation is undisturbed (`pipeline_hardening_spec.md` §2.2).
- No new passing evaluation is created on any snapshot, so no new `ApprovedScope` row
  appears and the `scopes[0]` ordering hazard (R7b, `paper_probation.py:113-122`,
  `approval_scope.py:45-66` with no `order_by`) stays deterministic: v2 → sealed id 11,
  v5 → sealed id 14, both on snapshot 3.
- FACT: v3 remains `EXPERIMENTAL`. It keeps being *scanned* (see §11.2) and can never be
  accepted into the paper ledger: `assert_auto_simulate_allowed` raises
  `AutoSimulateForbidden("strategy version is not PAPER_APPROVED")`
  (`paper/ledger.py:500-502`), and `plan_alerts` only emits candidate alerts for
  paper-approved strategies (`alerts/dispatch.py:238, 259, 265`). The null option
  therefore carries **zero** live-trading risk by construction, not by policy.

---

## 3. Pre-sealed evidence, with standard errors

All figures below are **pre-sealed only** (`[2016-09-10 … 2025-09-07]` on snapshots 2–4,
`[2016-09-10 … 2025-09-05]` in effect on snapshot 1 — see `v3_duration_exits.md` §0).
SEs are empirical `sd/√n` on the stated subset unless noted.

### 3.1 What the strategy looks like before the sealed year (snapshot 3, eval 33)

| Quantity | Trade set | Value ± SE | Note |
|---|---|---|---|
| OOS expectancy | OOS (n = 319) | **+0.3064R ± 0.0966** | 3.17 SE from zero; reproduced to 4 dp by two independent read-only re-runs (`pipeline_hardening_spec.md` §0; `v3_duration_exits.md` §0) |
| All-pre-sealed expectancy | 1,071 | +0.1667R ± 0.0484 | |
| Bootstrap CI low (gate 4, iid) | OOS | +0.1205 | vs threshold +0.02 |
| Walk-forward folds (gate 1) | all pre-sealed | +0.1822/310, +0.0772/323, +0.0343/179, +0.3513/259 | **4 of 4** clear, vs a floor of 2 of 4 |
| Sharpe (gate 7) | all pre-sealed | 1.156 vs SPY 0.719 | +0.437 |
| Sensitivity (gate 5) | OOS per cell | 9/9 (100%) positive | on `sma_fast` × `stop_atr` only — 2 of 8 fields (§0.5) |
| Comparison: v2 (approved) | OOS (341) | +0.2648R ± 0.0795 | v3 is **stronger** on gates 3, 4 and 7 than the strategy that is live |

### 3.2 The diagnostics that closed the change levers

| Finding | Estimate ± SE | z | Stable on all 4 snapshots? | Source |
|---|---|---|---|---|
| Extra leash (40 vs 10 bars), matched pairs, all pre-sealed | **+0.0524R ± 0.0231** (per matched trade); **+0.1770R ± 0.0777** (per affected trade) | +2.3 | yes (+2.3 to +2.7 SE) | `v3_duration_exits.md` §4 |
| Same, **OOS only** | +0.0326R ± 0.0439 | +0.7 | yes — and **under 2 SE on all four, therefore not evidence** | ibid. |
| 40-bar time-stop exits | +0.3493R ± 0.1716 (n = 8, 0.7% of trades) | +2.0 | identical set on all four | `v3_duration_exits.md` §2a |
| Expectancy within `stop` exits, by duration bucket (1–5 → 21–40) | spread 0.028R against SEs 0.012–0.021 | ≈1 | yes | `v3_duration_exits.md` §3 |
| ATR@exit/ATR@entry, v3 − v2 (median) | +0.0012 ± 0.0062 | +0.19 | yes | `v3_atr_at_exit.md` §1 |
| ATR-ratio tercile gradient **within `stop` exits** | +0.0059R ± 0.0371 | +0.16 | yes | `v3_atr_at_exit.md` §4.3 |
| ATR-ratio tercile gradient, **OOS only** | −0.1320R ± 0.2533 | −0.52 | yes (−0.52 to −0.64) | `v3_atr_at_exit.md` §4.2 |
| **Entry-time** ATR(14)/ATR(50) tercile gradient (the only *exogenous, known-at-entry* conditioner tested) | **+0.1374R ± 0.1209** | +1.14 | yes, under 2 SE on all four, same sign/size for v2 | `v3_atr_at_exit.md` §6 |
| Gate-4 CI low under **calendar-month block bootstrap** | **−0.0191R** (iid +0.1205); design effect **3.04** | — | snapshot 3 (diagnostic only) | `clustered_bootstrap_all.md` §1, §3.1 |

### 3.3 The two pieces of evidence that cut *against* the strategy, stated plainly

A null proposal that only lists supportive numbers is advocacy. These two are the honest
counterweight, and neither of them motivates a change:

1. **v3's pre-sealed edge does not survive the stricter clustered diagnostic.** FACT: under
   a calendar-month block bootstrap the OOS 95% CI is **[−0.0191, +0.6406]**, so the gate-4
   lower bound is **below zero**, with design effect 3.04 — an effective sample of ≈105
   rather than 319 (`clustered_bootstrap_all.md` §3.1). DERIVED: at SE_month = 0.1682 the
   month-clustered version of gate 4 would need **+0.3497R** against the observed +0.3064R.
   This is a *disclosure*, not a gate (R4 permits reporting a stricter statistic; gate 4
   remains the iid bootstrap at +0.02R). It matters here for one reason: **the pre-sealed
   profile that a v0.2.0 would be tuned to preserve is itself weaker than the iid CI makes
   it look**, so "v3 is stronger than the approved v2 on gates 3/4/7" — true, and it is
   (v2's month-block low is +0.0125, v5's is −0.0238; *both live strategies fail that
   diagnostic too*) — is an argument about the *program's* uncertainty, not a licence to
   go hunting for the last 0.03R.
2. **The sealed year is mildly disappointing relative to the pre-sealed estimate, on every
   snapshot.** FACT/DERIVED (§0.3): −0.0294 vs +0.3064 is z = **−1.88** treating the
   pre-sealed mean as known and **−1.65** on the two-sample SE; `P(sealed mean < 0 |
   pre-sealed estimate, n = 95) = 4.2%`. That is *mild* evidence the pre-sealed estimate is
   optimistic — which is an argument for **more caution about promoting**, and therefore an
   argument *for* the null option, not against it. Under R1 it may inform disposition only.

---

## 4. Falsification — stated before the fact, required to hold on all four snapshots

### 4.1 What would kill this proposal

The null option is falsified — i.e. a change proposal becomes legitimate — **only** by a
pre-sealed observation meeting **all five** of the following, which are set at the
standard the two completed W2 diagnostics already met and which the surviving evidence
does not:

1. **Mechanism-specific.** It identifies a named, market-level mechanism (a new H, in
   §2's form) and predicts the sign of its effect *before* measurement.
2. **≥ 2 SE, on the OOS cut**, not only on the better-powered all-pre-sealed cut. (This is
   the bar the leash result itself fails: +0.0326 ± 0.0439 OOS. It is deliberately the
   same bar applied to a finding that favours the incumbent.)
3. **Stable on all four dataset snapshots** (R10), with the same sign and a spread across
   snapshots well inside one SE.
4. **Stable across the IS→OOS split.** This is the cut that killed the ATR tercile
   gradient (−0.5461 ± 0.1362 IS → −0.1320 ± 0.2533 OOS) and it is a far more informative
   robustness test than snapshot stability, which a one-symbol perturbation of a 25-symbol
   universe barely stresses (`v3_atr_at_exit.md` §7).
5. **Not a post-treatment conditioner.** Any statistic measured at or after exit
   (at-exit ATR, realised duration, realised exit reason) is an *output* of the trade and
   is inadmissible as motivation, per `v3_atr_at_exit.md` §4.3's endogeneity finding.
   Conditioners must be computable from `(series, t ≤ signal bar)`.

**Additionally, and independently: the effect must survive a month-block resampling at
≥ 2 SE**, given §3.3(1). An effect that exists only under the iid assumption this
universe violates is not a mechanism.

### 4.2 The one open lever, and its pre-registered test

FACT: **H4 (volume-confirmation decay) is the only §2.1 hypothesis with no W2 diagnostic.**
If the panel wants one more shot before closing the lane, this is the only legitimate
place to take it, and it must be pre-registered as follows:

- **Test:** pre-sealed expectancy conditioned on entry `vol_ratio` bucket
  (`volume_ratio(series, t, 20)`, an exogenous known-at-entry quantity) — e.g. buckets
  [1.3, 1.5), [1.5, 2.0), [2.0, 3.0), ≥ 3.0 — reported for v3 **and** v2, all pre-sealed
  and OOS, on all four snapshots, with SEs.
- **Kills the null option only if:** the gradient across buckets is ≥ 2 SE **on the OOS
  cut, on all four snapshots, and larger for v3 than for v2 by ≥ 2 SE** (the v3−v2
  differential is what a *medium-swing* change must be justified by; a shared gradient is
  a `trend_continuation`-family finding and would implicate the live v2, which is out of
  scope under §4.1).
- **Confirms the null option if:** the gradient is under 2 SE, or is present equally in
  v2 (as the entry-ATR conditioner was: v3 +0.1374 ± 0.1209 vs v2 +0.1400 ± 0.1045,
  `v3_atr_at_exit.md` §6).
- HYPOTHESIS (my prediction, recorded so it can be scored): the gradient will be under
  2 SE OOS on all four snapshots, because every entry-side conditioner tested so far has
  been, and because v2 and v3 share the entry rule exactly.

### 4.3 What evidence would later justify a promotion re-run — **and what would not**

This subsection is the operative part of the angle. It rests on a structural fact that
has to be stated first, because it changes what "re-run" can even mean.

**FACT — `trend_continuation.medium_swing` v0.1.0 can never pass promotion on snapshot 3,
no matter how many times it is re-run, and no matter how much new data arrives.**
`_get_or_create_sealed_test` is keyed on `(strategy_version_id, dataset_snapshot_id)` and
returns any existing row **as-is, "locked — never recomputed, never overwritten"**
(`promotion.py:376-385`). `evaluate_promotion` then pins the whole window from that row:
`sealed_start = existing_sealed.window_start`, `sealed_end = existing_sealed.window_end`,
and `pre_sealed_end = sealed_start − 1 day` (`promotion.py:545-557`). So a re-run in 2030
still evaluates the sealed window **2025-09-08 → 2026-09-08** and still replays sealed
test **id 12** (−0.0294R / 95 trades / `passed = 0`). Since
`passed = bool(gates) and all(g.passed for g in gates)` (`promotion.py:922`), the verdict
is `NO TRADE` forever. FACT (queried): all seven of v3's promotion evaluations (ids 3, 9,
15, 21, 27, 33, 39) returned `NO TRADE`, and eval 33's gate-9 detail already says
*"reused, locked on a prior evaluation; never recomputed"*.

**FACT, and it must be in the documented fail:** v3 has never had an all-gates pass on
*any* snapshot. On snapshots 1, 2 and 4 gate 9 passes (+0.0109R / 98) but gate 8 fails —
`validate_daily: FAIL (META: 90 missing (6.9%)…)` on snapshots 1 and 2, and
`missing: ['META_CONT']` on snapshot 4 (queried `gates_json`, evals 3, 15, 39). "Passes
gate 9 on three of four snapshots" is true and must be disclosed; "would have been
approved on three of four snapshots" is **false** and must not be written.

Therefore there are exactly **two** routes to a different verdict, and only these two:

| # | Route | Qualifies as a legitimate re-run when… |
|---|---|---|
| **A** | A **new dataset snapshot** evaluated with the **unchanged v0.1.0** | The snapshot was built for reasons **independent of v3** (today: W1's 150-symbol `research_150_massive_10y_2026-09-08`, built for v6's power problem, `w1_universe_preregistration.md`); its symbol rule and composition rule were pre-registered **before** any v3 number on it existed; v3's inclusion in the run and the intention to report its result **whatever it is** are pre-registered in writing beforehand; the run is disclosed as a new look (§10) |
| **B** | A **v0.2.0** with a real rule change | The change is motivated by a pre-sealed finding meeting **all** of §4.1's five conditions plus the month-block condition; the motivation is documented before the variant is run; the variant budget and stopping rule of §9 are respected |

**What does NOT justify a re-run** — each of these has a specific reason, and each is a
mistake this program is at real risk of making:

| Non-qualifying trigger | Why not |
|---|---|
| The sealed miss itself (−0.0294R, 3 META trades, "it's only 0.03R") | R1: sealed numbers may not motivate a design choice. Also self-defeating: a change sized to close 0.0294R is smaller than half of one trade's modelled cost (§8) |
| Any duration, leash, or exit-timing change | H1 and H2 are **falsified on all four snapshots** (`v3_duration_exits.md` §5). §2.1 lever 2 is closed by its own stated precondition; lever 3 has lost its stated motivation |
| Any ATR-window, volatility-scaled stop, trailing stop, or ATR re-estimation change citing the at-exit ATR work | `v3_atr_at_exit.md` §7 rules this out by name: the criterion for H3 was met, and the surviving gradient is post-treatment |
| A grid or sweep over `time_stop_bars` (e.g. 50, 60, 80 bars) | The +2.3 SE matched-pair result is a **single pre-registered comparison of the two shipped configurations**, not a search; turning it into a sweep and reporting the survivor is exactly the R5 offence, and `v3_duration_exits.md` §7 forbids it explicitly |
| Leading with snapshot 1, 2 or 4 because gate 9 passes there | Snapshot-shopping (R1's new clause). Those snapshots fail gate 8 for *every* version, which is why snapshot 3 is the pre-registered headline (§0.1) |
| Waiting for the calendar to roll so a "fresher" sealed year is used | Structurally impossible: the window is pinned by the locked row (`promotion.py:545-557`) |
| Building a new snapshot **in order to** get v3 another sealed draw | Sealed-window shopping with extra steps. Route A qualifies only because W1's purpose and symbol rule are independently pre-registered |
| Live-paper or shadow-ledger results, in either direction | R8: live paper confirms, never promotes; FACT: no code path re-promotes from live evidence (`health_monitor.py:100-113` is one-way down) |
| Re-running v0.1.0 on snapshot 3 after a pipeline-hardening change (gate-6 warmup split, gate-7 docstring resolution, sealed-look ledger) | Those change reporting and counting, not gate 9. The verdict is pinned. `pipeline_hardening_spec.md` verifies none of the six items changes a verdict for the approved strategies either |

**Pre-registered prediction for Route A, recorded now so a pass cannot be over-read.**
HYPOTHESIS: on a 150-symbol snapshot, v3's sealed-window trade count scales roughly with
breadth — 4.96 trades per symbol-year pre-sealed (1,071 trades / 24 symbols / 8.99 years)
implies **≈600–750 sealed trades**, at which SE falls to **≈0.063–0.071R**. That does
**not** make gate 9 a better test — at a threshold of exactly zero it still rejects a
true-zero strategy 50% of the time — but it makes the *reported estimate* informative for
the first time. Pre-register, therefore: **the number to read from Route A is the sealed
expectancy ± SE, not the pass/fail bit**, and the report must say so before the run. Also
pre-register the known risks: gate 8 requires every symbol to be genuinely `massive`-sourced
end to end (snapshot 4's failure mode), and the run creates a fresh sealed test for **every**
version, which is the main argument for building the snapshot once (§3a).

---

## 5. Gate-by-gate forecast, with trade sets

Because the change set is empty, gates 1–8 are **unchanged by construction**: they are
computed over `[start, pre_sealed_end]` with `pre_sealed_end` pinned by the locked sealed
row (`promotion.py:545-557`), from strategy code that is not being edited. The only way a
number in this table moves is if the *underlying bars* for the pre-sealed span change
(a backfill or vendor revision) — which is a data event, not a proposal effect.

| # | Gate | **Trade set** | Value today (snapshot 3, eval 33) | Forecast under this proposal | At risk? |
|---|---|---|---|---|---|
| 1 | `rolling_walkforward` | **all pre-sealed** (1,071) | 4 of 4 folds clear (+0.1822/310, +0.0772/323, +0.0343/179, +0.3513/259); floor is `sensitivity_min_grid_trades` = 15 per fold (`promotion.py:632`) | **identical**; margin 4 of 4 vs a 2-of-4 bar | no |
| 2 | `min_oos_trades` | **OOS** (319) | 319 ≥ 30 | **identical** | no |
| 3 | `net_expectancy` | **OOS** (319) | **+0.3064R ± 0.0966** | **identical** | no |
| 4 | `bootstrap_ci` | **OOS** (319) | low +0.1205 > +0.02. **Required n at this point estimate = 140** (sd 1.7259 measured) / **142** (§0.3's 1.741): `n > (1.96·sd/(0.3064 − 0.02))²`. Has 319 | **identical**. *Disclosure (not a gate): month-block low **−0.0191**, deff 3.04, effective n ≈ 105; a month-clustered version of this gate would need +0.3497R* | no (as specified); **fails the stricter diagnostic** |
| 5 | `parameter_sensitivity` | OOS per grid cell | 9/9 (100%) positive, on `sma_fast` × `stop_atr` = **2 of 8** `TrendParams` fields | **identical** — and the shared `trend_continuation` grid (`promotion.py:178-187`) is *not* touched, which protects v2 too (§6) | no |
| 6 | `regime_coverage` | **all pre-sealed** (1,071) | bull **857** / bear **22** / range **69**; **unbucketed 123 (11.48%)**, decomposed as **warmup 123, no-proxy-bar 0** (`pipeline_hardening_spec.md` §1.2) | **identical**. Bear margin 22 vs a floor of 10 — the only bucket with a thin margin, and nothing here reduces trade count | no |
| 7 | `benchmark_comparison` | **all pre-sealed** (1,071) — *not* OOS, despite the docstring at `config/research.py:111-113`; the code is `promotion.py:775` | Sharpe 1.156 vs SPY 0.719 (+0.437) | **identical** | no |
| 8 | `data_quality_and_leakage` | — | pass on snapshot 3 only; fails on 1, 2 (META 90 missing) and 4 (`META_CONT` not `massive`) | **identical** | no |
| **9** | `sealed_final_test` | sealed year | **−0.0294R / 95 trades, `passed = 0`, LOCKED** (sealed id 12) | **identical and unchangeable** (`promotion.py:376-385, 545-557`) → verdict stays `NO TRADE` | n/a — this is the documented outcome |
| 10 | `live_paper_probation` | — | `health_monitor.enabled` → pass | identical | no |

**Trade-count effect (mandatory entry): zero.** No entry, exit or parameter changes, so
gate 1's per-fold counts (310/323/179/259), gate 2's 319, gate 5's per-cell counts, and
gate 6's 10-per-regime floor are all untouched.

**The two zero-margin cases named in §4.2 item 5, and this proposal's effect on them:**

- **v6's gate-5 neighbour fraction** — exactly **0.750** on snapshot 3 (passes, since
  `sensitivity.py:194` tests `nb_frac < min`) and **0.500 / FAIL** on snapshot 4 (eval 42).
  **Effect of this proposal: none.** It touches no grid, and the `volatility_breakout`
  plan (`promotion.py:199-208`) is a different prefix entirely.
- **v5's bear bucket** — **11** against a floor of 10. **Effect: none.** No new evaluation
  of v5 is run and no shared code path changes. (For completeness: v5's unbucketed count
  is **0** — its own feature warmup pushes its first trade past the proxy's 200-session
  mark, `pipeline_hardening_spec.md` §1.2.)

**Forecast for Route A (a W1-snapshot run of the unchanged v0.1.0), pre-registered so a
result cannot be re-narrated afterwards.** HYPOTHESIS throughout:

- Gate 8 is the *first* risk, not gate 9: every one of the 150 symbols must be genuinely
  `massive`-sourced (snapshot 4's failure mode). If one is not, everything else is moot.
- Gate 2 and gate 5 get comfortably more data (≈6.25× breadth); gate 6's bear bucket
  should rise from 22 toward ~100+, and the warmup-unbucketed share should stay ≈11%
  unless the proxy or the per-symbol history lengths change.
- Gates 3, 4 and 7 are **point-estimate** questions and breadth does not move a point
  estimate. Gate 4's required n at +0.3064R is 140 and would already be met many times
  over; the honest risk is that the *point estimate itself* falls on a single-name-heavy
  universe with wider real spreads (§8) and with far more heterogeneous per-symbol
  history, which worsens the `_TRAIN_FRAC = 0.6` per-symbol IS/OOS misalignment
  (`backtest_runner.py:29,158-160`).
- Gate 9 is a fresh, genuinely-unseen draw with SE ≈ 0.063–0.071R. **Pre-registered
  reading: report the estimate and its SE; treat the pass/fail bit as near-uninformative
  at a zero threshold.**

---

## 6. Sensitivity-grid plan — pre-registered axes and the no-op check

**This proposal introduces or changes zero parameters, so under §4.2 item 6 it adds zero
axes.** The grid stays `{"sma_fast": [15, 20, 25], "stop_atr": [1.2, 1.5, 1.8]}`
(`promotion.py:187`).

That is not a free pass, so three things are pre-registered anyway:

**(a) The no-op check, run before any future evaluation of this family on any snapshot.**
For each axis independently, verify that perturbing it to each of its three values
**measurably changes the OOS trade count or the OOS expectancy** — concretely, that at
least one off-baseline value differs from the baseline by ≥ 1 trade or ≥ 0.001R. Rationale
(§2.1): `_replace` raises `TypeError` loudly on a *renamed* field (`promotion.py:50`), but
a **retained-but-unused** field silently makes all 9 cells identical,
`positive_fraction` and `neighbour_positive_fraction` both come back 1.0, and gate 5
passes at 100% having tested nothing; `sensitivity.py:199`'s
`len(evaluable) >= 4 and len(positive) <= 1` guard does not catch it. Today the check
passes trivially — v3's 9 cells are not identical (9/9 *positive* is not 9/9 *identical*)
— but the check must be mechanical, not assumed.

**(b) Why `time_stop_bars` is *not* being added as an axis, even though it is the
parameter that defines this strategy.** Two reasons, both FACT:

1. `_sensitivity_plan` is keyed on the **`trend_continuation` prefix**
   (`promotion.py:177-187`), so the grid is shared by `short_swing` and `medium_swing` and
   by any v0.2.0 of either. Adding an axis changes gate 5 for the **PAPER_APPROVED v2**
   the next time v2 is evaluated. §4.2 item 6 requires new axes only for parameters a
   v0.2.0 *introduces or changes* — this proposal introduces none, and unilaterally
   widening a shared grid is a change to a live strategy's gate, made from a proposal
   about a different strategy.
2. The axis-declaration mechanism itself must live **off** `StrategySpec`:
   `persistence.spec_json_hash` hashes every spec field except `git_sha`, `status`,
   `notes` (`persistence.py:29`), so adding a `sensitivity_axes` field changes v2's hash
   `2ed97431… → 6e35dbe5…` and v5's `dfe696b6… → 3138ed57…`, permanently breaking
   `scan_scope_matches` for both live approvals (`pipeline_hardening_spec.md` §2.2). That
   work belongs to the hardening lane, not to a strategy proposal.

Recorded for whoever *does* ship a v0.2.0 here: `time_stop_bars` is a **live** axis, not a
dead one — moving it 10 → 40 changes the pre-sealed trade count by ~8%, target share by
~17 pp and total R by +53 to +70R (`v3_duration_exits.md` §6c). If a v0.2.0 in this family
ever ships, adding it would be a genuine test; it just cannot be added by a proposal that
ships nothing.

**(c) On a new snapshot (Route A), re-run (a) there.** Grid degeneracy is snapshot-
dependent through the 15-trade-per-cell floor (`config/research.py:106`), and that same
constant is gate 1's per-fold floor (`promotion.py:632`) — so a cell-count argument is
always simultaneously a gate-1 argument.

---

## 7. Leakage argument

**For the strategy: nothing changes, so no new leakage surface exists.** No feature is
added; `sma`, `volume_ratio` and `atr` continue to be read as `(series, t)` with slices
≤ t (`research/features/daily.py`), and `backtest/leakage.py:assert_no_lookahead` (`:23-41`)
covers the same call sites it covers today. No cross-sectional or breadth term is
introduced, so `StrategyContext` (`strategies/base.py:15-19`) is untouched and there is no
shared-surface change to audit.

**For the shadow-confirmation tool (D3), the point-in-time argument is structural, and it
is stronger than the backtest's.** The tool reads `Candidate` rows, each created by a scan
run at a wall-clock time from bars available at that time
(`research/scan.py:265-300`, `research/candidates.py:persist_scan`), and evaluates them
forward against bars ingested **strictly later**. Specifically:

1. The entry decision is *already made and persisted* before any forward bar exists — the
   tool cannot influence or re-select it. Its inputs are `entry_zone_low/high`,
   `invalidation_level`, `target_level`, `time_stop_days`, `direction` — all frozen columns
   on the `candidate` row.
2. Forward evaluation uses only bars with `date > scan_run.started_at`'s session, applying
   the same rules the engine applies: fill at the next session's open, stop / target /
   40-session time stop, and the **unchanged** cost model (§8).
3. The tool performs **no** `session.add` / `flush` / `commit` against
   `data/signalforge.sqlite`; it opens read-only and writes a dated markdown + JSON under
   `docs/research/`. It calls no provider API.
4. Selection-effect disclosure: the shadow ledger observes only symbols in the approved
   scan universe on days the scan ran. Missed sessions (a blocked scan — see
   `approved_scope_scan.py`'s three hard gates) produce **gaps, not deletions**, and every
   read-out must report the number of scan sessions covered and missed. A gap is not
   random with respect to market conditions (scans block on stale feeds, which correlate
   with disorderly markets), so the read-out must state this as a known bias, not average
   over it.

---

## 8. Cost-model statement (quantitative)

**The cost model is unchanged, and this proposal changes turnover by exactly zero.**

FACT: `CostModel` (`backtest/costs.py:11-16`) — commission 0, `slippage_bps = 3.0`,
`half_spread_fill_penalty = True`; `engine.py:90` defaults `spread_bps = 5.0`; `engine.py:94`
gives `slip = (3.0 + 5.0/2)/10,000 = 5.5 bps` per side; `engine.py:143` records
**11.0 bps of notional per round trip**. FACT: `backtest_runner.py:205-206` never passes
`spread_bps`, so the assumption is universe-independent.

**Per-trade cost in R at this strategy's own geometry.** The formula is
`round_trip_bps/10,000 ÷ (stop_atr × ATR/price)` with `stop_atr = 1.5`. Map §0.4 uses a
2% ATR/price reference and reports 0.037R; the **measured** median ATR/price at v3's own
entries is **1.29%** (IQR 0.98%–1.76%), giving:

| Scenario | round trip | cost per trade @ ATR/price = 1.29% | increment vs today | v3 OOS expectancy, approx. re-derived |
|---|---|---|---|---|
| **Today (the model in force)** | 11.0 bps | **0.0568R** | — | **+0.3064R ± 0.0966** |
| 2× modelled spread (20 bps quoted) | 26 bps | 0.1344R | +0.0775R | ≈ +0.2289R → gate-4 required n rises 140 → **262** |
| 5× modelled spread (60 bps quoted) | 66 bps | 0.3411R | +0.2842R | ≈ **+0.0222R** → gate 4 effectively unreachable |

(DERIVED and **approximate**: the re-derived expectancies subtract the *mean* cost
increment from the mean expectancy rather than re-running per-trade at each trade's own
ATR/price. Direction and order of magnitude only.)

Three consequences, all of which point the same way:

1. **Map §0.4's 0.037R understates this family's real modelled cost by ~50%.** The trend
   strategies enter on lower-volatility names than the 2% reference assumed
   (`v3_atr_at_exit.md` §5). Every downstream use of 0.037R for `trend_continuation`
   should be re-derived at 0.057R.
2. **The sealed shortfall is half of one trade's modelled cost.** 0.0294R / 0.0568R =
   **0.52**. A design change targeted at that number is targeting less than a single
   trade's frictions.
3. **This is a live constraint on Route A, not a footnote.** A 150-name universe outside
   the current mega-cap/ETF set plausibly quotes wider than the flat 5 bps assumption. At
   2× the modelled spread v3's pre-sealed edge survives (+0.229R); at 5× it is essentially
   gone (+0.022R). §4.2 item 8 requires any expanded-snapshot result to be reported at 2×
   and 5×, and for this strategy that reporting is decision-relevant rather than
   ceremonial. Turnover under this proposal: **unchanged** (95.07 sealed-year round trips,
   1,071 pre-sealed trades — nothing is altered).

---

## 9. Variant budget and stopping rule

**Variants this angle intends to try: zero.** No `StrategyVersion` is created, no
parameter is perturbed outside the existing gate-5 grid, and no backtest of a modified
rule set is run. Under R5 the recorded variant count for version 3 contributed by this
proposal is **0** — matching the two completed W2 diagnostics, each of which also
evaluated zero variants (`v3_duration_exits.md` §7, `v3_atr_at_exit.md` §7). **The
program-wide variant count for `trend_continuation.medium_swing` therefore stands at 0
today.**

**Recommended total budget across all three v3 angles: ≤ 2 variants**, and my
recommendation is **0**. Justification: the two levers the other two angles were written
to explore (§2.1 levers 2 and 3) have both had their stated preconditions fail — lever 2's
precondition ("only if a W2 diagnostic first establishes a duration effect that holds on
all four snapshots") failed explicitly, and lever 3's motivating hypothesis H2 is dead.
Lever 4 (MAE/MFE risk geometry) is untested but is a `stop_atr`/`target_atr` change on a
strategy whose `stop_atr` neighbourhood is already the one axis gate 5 does measure, at
9/9 positive.

**Stopping rule (pre-registered):**

1. If §4.2's H4 volume diagnostic returns a sub-2-SE or v2-shared gradient → the v3 change
   lane **closes**; publish D1 and start D2.
2. If any change proposal is nonetheless implemented, it gets **one** v0.2.0. If that
   v0.2.0 fails any gate, the lane closes with a documented fail that states the variant
   count; it does **not** get a v0.3.0. A second variant would make the surviving one's
   bootstrap CI optimistic by roughly the selection it survived (R5) and would take the
   family to look 7.
3. Route A (a W1-snapshot run of the unchanged v0.1.0) is **not** a variant and does not
   consume this budget — but it does consume a **look** (§10).

---

## 10. Sealed-look accounting

**This proposal consumes zero sealed looks.** No `StrategyVersion` row is created
(`VERSION` stays `"0.1.0"`, so `upsert_strategy_version` would refresh the same row —
`persistence.py:46-93`), no new snapshot is introduced, and no `evaluate_promotion` call
is made. FACT: even if one were made against snapshot 3, `_get_or_create_sealed_test`
returns the locked row and no new sealed test is created (`promotion.py:376-385`).

**The §0.1 ledger, reproduced in full (FACT, queried from `strategy_sealed_test`):**

| Ver | Strategy | snap 1 `universe_25_baseline_legacy` | snap 2 `universe_25_baseline` | snap 3 `universe_24_ex_meta` | snap 4 `universe_25_meta_continuity_corrected` |
|---|---|---|---|---|---|
| 2 | `trend_continuation.short_swing` | id 1: **+0.3246R / 112** ✅ | id 6: **+0.3246R / 112** ✅ | id 11: **+0.2982R / 109** ✅ | id 16: **+0.3246R / 112** ✅ |
| **3** | **`trend_continuation.medium_swing`** | **id 2: +0.0109R / 98** ✅ | **id 7: +0.0109R / 98** ✅ | **id 12: −0.0294R / 95** ❌ | **id 17: +0.0109R / 98** ✅ |
| 4 | `mean_reversion.short_swing` | id 3: +0.1230R / 91 ✅ | id 8: +0.1230R / 91 ✅ | id 13: +0.1278R / 84 ✅ | id 18: +0.1230R / 91 ✅ |
| 5 | `relative_strength.medium_swing` | id 4: +0.2935R / 16 ✅ | id 9: +0.2935R / 16 ✅ | id 14: +0.2935R / 16 ✅ | id 19: +0.2935R / 16 ✅ |
| 6 | `volatility_breakout.short_swing` | id 5: −0.0979R / 10 ❌ | id 10: −0.0979R / 10 ❌ | id 15: −0.0979R / 10 ❌ | id 20: −0.0979R / 10 ❌ |

20 rows, exactly 4 per version for versions 2–6. Version 3's rows carry windows
2025-09-07→2026-09-07 (snap 1) and 2025-09-08→2026-09-08 (snaps 2–4) and details
"98 trades, net expectancy +0.0109R" / "95 trades, net expectancy −0.0294R" against
"need >= +0.0000R on >= 10 trades" (queried).

**The count, with the naming inconsistency disclosed.** This brief and MAP §0.1/R2 set the
**baseline at k = 5 per strategy**; MAP §4.2 item 10 says a first v0.2.0 sealing on
snapshot 3 is "look 6"; `pipeline_hardening_spec.md` §4 resolves the ambiguity mechanically
as `k_prior` = existing rows for the family = **4**, `this_look` = `k_prior + 1` = **5**.
Under this proposal none of it moves: **no look is consumed, the family's existing sealed
tests remain ids 2, 7, 12, 17, and the next look — whichever convention numbers it — is
still ahead of us.** For the two routes in §4.3: Route A (v0.1.0 on a new snapshot) is the
next look, and it is a look for **every** version simultaneously, since a new snapshot
creates a fresh sealed test per version (`db/models/research.py:263`). Route B (a v0.2.0)
is the next look for this family only.

**Which snapshot the report leads with, pre-registered:** **snapshot 3**, because it is the
only snapshot on which gate 8 passes for any version — snapshots 1 and 2 fail
`validate_daily` on META's 90 missing sessions and snapshot 4 fails because `META_CONT`
carries source `continuity_bridge:1` rather than `massive` (FACT, queried from evals 3,
15, 39). The choice is forced by a **pre-sealed data-quality gate**, not selected after
seeing gate 9. **All four sealed draws are disclosed alongside it in every table**, and
the report must state that v3 has never had an all-gates pass on any snapshot (§4.3).

**Sealed SEs to print next to every sealed number in D1** (using the measured pre-sealed
per-trade sd 1.7259): snapshot 3, −0.0294R on 95 → SE **0.1771**, **−0.17 SE** from zero;
snapshots 1/2/4, +0.0109R on 98 → SE **0.1743**, **+0.06 SE** from zero. A number without
its SE is what made the first draft of the map wrong; the ledger must not repeat it.

---

## 11. Null option

For this proposal the "null option" is not a fallback — it *is* the proposal. This section
therefore states (11.1) the deliverable if the panel accepts it, (11.2) the confirmation
plan, and (11.3) what happens if the panel rejects it.

### 11.1 D1 — the documented "does not pass"

`reports/trend_continuation.medium_swing-0.1.0-does-not-pass.md`, carrying, at minimum:

1. **The verdict, stated precisely.** "`trend_continuation.medium_swing` v0.1.0 does not
   pass promotion on dataset snapshot 3 (`universe_24_ex_meta`). It fails one gate —
   gate 9 `sealed_final_test`, at −0.0294R on 95 trades. It has never passed all gates on
   any snapshot: on snapshots 1, 2 and 4 gate 9 passes at +0.0109R on 98 trades but gate 8
   `data_quality_and_leakage` fails. Because sealed tests are locked per
   `(version, snapshot)`, **this version can never pass on snapshot 3**."
2. **The full §10 ledger** — all four sealed draws with ids, windows, counts and **SEs**.
3. **The gate-by-gate table of §5**, with trade sets tagged, gate 4 stated as a required n
   (140/142 against 319), gate 6's unbucketed count (123, all warmup, 0 no-proxy-bar), and
   gate 7 flagged as computed over all pre-sealed trades despite its docstring.
4. **The power statement.** Gate 9 is a sign test at a zero threshold: it rejects a true
   +0.3064R strategy 4.2% of the time and a true-zero strategy 50% of the time at n = 95,
   at *any* sample size. The observed miss is −0.17 SE from zero; the pass on the other
   three snapshots is +0.06 SE from zero; the difference between them is 3 META trades
   worth +3.861R, and the deficit is ≈1.5 average target hits, or ≈52% of one trade's
   modelled cost.
5. **The three refuted mechanisms**, with their falsification criteria and the numbers
   that met them (§1's table), so a future reader cannot re-propose them unknowingly.
6. **The honest counterweight of §3.3** — the month-block CI low of −0.0191R with deff
   3.04, and the −1.65 to −1.88 z of the sealed year against the pre-sealed mean —
   presented as reasons the pre-sealed profile is weaker than the iid numbers suggest,
   *not* as reasons to change the rules.
7. **The cost arithmetic of §8**, including the correction from 0.037R to 0.057R.
8. **The variant count: 0**, and the §4.3 table of qualifying vs non-qualifying re-run
   triggers, so the next person to look at this strategy inherits the pre-registration
   rather than re-deriving it.
9. **A statement of what is *not* being claimed:** not that v3 is unprofitable, not that
   it is inferior to v2, and not that it should be deleted. It stays `EXPERIMENTAL`, it
   keeps being scanned, and it remains eligible for Route A.

### 11.2 D2/D3 — the pre-registered shadow-confirmation plan

**The structural constraint first, because it is decisive.** FACT: v3 is `EXPERIMENTAL`,
so no live-paper *ledger* evidence can ever accrue for it —
`assert_auto_simulate_allowed` raises `AutoSimulateForbidden("strategy version is not
PAPER_APPROVED")` (`paper/ledger.py:500-502`) and `plan_alerts` gates candidate alerts on
paper-approved status (`alerts/dispatch.py:238, 259, 265`). A "live-paper confirmation plan" for
v3 in the `PaperTrade` sense would require promotion first — which is exactly what gate 9
blocks. Anyone who writes such a plan without noticing this has written a plan that cannot
run.

**But a shadow signal stream already exists, at zero risk, with no code change and no
promotion.** FACT: `research/scan.py:110-111` selects strategies by **horizon**, not by
status, and `:298` records **both** `PASSED` and `NO_TRADE` drafts as `Candidate` rows.
MEDIUM_SWING is scanned because v5 is PAPER_APPROVED on it
(`approved_scope_scan.py:77-82`). FACT (queried, read-only): version 3 already has **199
`candidate` rows**, of which **3** are on `dataset_snapshot_id = 3` / source `massive` —
XLK on 2026-09-09 (×2 scan runs) and XLE on 2026-09-10 — each carrying its frozen
`entry_zone_low/high`, `invalidation_level`, `target_level` and `time_stop_days = 40`.
(All three are marked `NO_TRADE` by the *candidate-desk* quality gates, which are a
different mechanism from the promotion gates; the shadow ledger records every triggered
candidate regardless, because the research question is the rule's expectancy, not the
desk's filter — and that inclusion rule is pre-registered here, before any outcome is
known.)

**The plan, pre-registered in full:**

| Item | Pre-registration |
|---|---|
| **Population** | Every `candidate` row with `strategy_version_id = 3` from a scan run with `dataset_snapshot_id = 3` and `source = 'massive'`, from **2026-09-11** forward (today's 3 rows are excluded as pre-registration-contaminated) |
| **Simulation rule** | Mirror the engine exactly: fill at the next session's open, stop at `invalidation_level`, target at `target_level`, 40-session time stop, one open position per symbol (a duplicate signal while a position is open is ignored, matching `run_backtest`), unchanged `CostModel` → 11.0 bps round trip |
| **Metric** | Per-trade R and its empirical SE; equity curve; exit-reason mix; realised ATR/price to check the 1.29% cost assumption |
| **Read-out 1** | At **12 months or n ≥ 95, whichever is later.** DERIVED expected n at v3's pre-sealed rate of 4.96 trades per symbol-year × 24 symbols = **≈119/year**, i.e. ~9.6 months to 95 |
| **Read-out 2** | At **24 months or n ≥ 220** |
| **Honest power statement, stated before the first read-out** | At n = 20 SE = 0.386R (useless); n = 95 → SE 0.177R (+0.3064 sits 1.73 SE from zero — **cannot separate the pre-sealed estimate from zero**); n = 132 → SE 0.150R (2.04 SE); n = 220 → SE 0.116R (2.63 SE). **Read-out 1 will not settle anything on its own, and must not be reported as if it had.** Only read-out 2 has ≥ 2 SE resolving power |
| **What it can conclude** | (i) a realised expectancy ≥ 2 SE **below** the pre-sealed +0.3064R strengthens the documented fail and is evidence the pre-sealed estimate was optimistic; (ii) a realised expectancy consistent with +0.3064R is *context* and, under **R8**, is **never** an argument for promotion; (iii) exit-mix or ATR/price divergence from the backtest is a model-fidelity finding worth reporting on its own |
| **What it can never do** | Promote, re-promote, or motivate a v0.2.0 (R8; and FACT: no code path re-promotes from live evidence, `health_monitor.py:100-113`) |
| **Known dependency, disclosed now** | If v5 were ever downgraded, MEDIUM_SWING would drop out of `approved_horizons()` (`approved_scope_scan.py:77-82`) and the shadow stream would **stop**. The read-out must report scan sessions covered and missed (§7 item 4) |
| **Implementation constraint** | D3 is a standalone read-only script (no `src/` module, no migration, no DB write, no API call) producing dated markdown + JSON under `docs/research/` |

### 11.3 If the panel rejects this proposal

Then one of the other two angles ships a v0.2.0, and this proposal's contribution becomes
the constraint set it leaves behind, which the panel should adopt regardless of which
angle wins:

- the §4.1 five-condition evidentiary bar plus the month-block condition;
- the §4.3 table of non-qualifying re-run triggers (in particular: no duration/exit/ATR
  change, no `time_stop_bars` sweep, no snapshot-shopping);
- the §9 stopping rule (one v0.2.0, no v0.3.0);
- the §6(b) prohibition on widening the shared `trend_continuation` grid from a
  medium-swing proposal, and the requirement that any axis-declaration mechanism live off
  `StrategySpec`;
- the §10 requirement that the resulting report print the four-snapshot ledger, the
  new look number, and an SE beside every sealed figure.

**And if that v0.2.0 fails**, the output is D1 with two additions: the variant's full
pre-sealed record (what was changed, why, its OOS expectancy and CI) per R5, and the
statement that the family is now at the next look. A program in which no strategy is
allowed to fail is a program that will manufacture a pass; this strategy is the one where
that pressure is highest, because it fails by 0.0294R on a single gate whose measurement
error is six times the gap.

---

*Proposal complete. Read-only: no strategy code, no configuration, no database row and no
gate threshold was changed in producing this document. Every number is a query result, a
`file:line` citation, a figure carried forward from a committed W2 diagnostic (cited), or
an arithmetic derivation whose inputs are those.*
