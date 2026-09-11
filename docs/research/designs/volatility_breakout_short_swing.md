# Design — `volatility_breakout.short_swing` v0.2.0 (from version 6 / v0.1.0)

**Synthesis of two proposals** (`--mechanism`, `--universe_power`) and four judge verdicts
(both proposals scored **revise**: mechanism 7 / 6.5, universe_power 6 / 6.5).
**Strategy:** `volatility_breakout.short_swing` v0.1.0 = `StrategyVersion` id **6**,
EXPERIMENTAL, latest evaluation id **36** on snapshot **3** (`universe_24_ex_meta`).

**Governing:** `STRATEGY_COMPLETION_MAP.md` §0, §1 (R1–R10), §2.3, §3(a), §4.0–§4.3;
`STRATEGY_COMPLETION_PLAN.md`; `diagnostics/w1_universe_preregistration.md`;
`diagnostics/v6_regime_power.md`; `diagnostics/clustered_bootstrap_all.md`.

**Claim labelling.** **FACT** = verified by `file:line` or by a computation run for this
document (provenance §0.4). **DERIVED** = arithmetic on FACTs, shown. **HYPOTHESIS** = an
inference a later phase must test. **A difference under 2 SE is not evidence** and is
labelled so everywhere it appears.

---

## 0. Decision, and what changed from the proposals

### 0.1 The chosen path

**A single v0.2.0 design — the mechanism change (lagged squeeze + break-bar release) —
evaluated on the expanded universe only, and STAGED so that the sealed look is a separate
operator decision taken after the decisive evidence is already in hand.**

Three sub-decisions, each of which departs from both proposals:

1. **W1's symbol-selection rule must be re-derived on a PRE-SEALED liquidity window before
   any snapshot is built.** Both legitimacy judges independently found the same R1 defect and
   neither proposal carried it: **FACT** (`w1_universe_preregistration.md:52-72`, Rule W1-SEL)
   the 150 symbols are ranked by the median of `close × volume` over **2026-06-12 →
   2026-09-08** — a statistic computed *entirely inside the sealed window* — from a base pool
   (`universe_screen_run` id 3, `screen_date` 2026-09-08) that also spans it. Gate 9's sealed
   test would then be run over the very calendar year that selected its universe. MAP §1 R1
   forbids sealed data motivating a **universe** choice in terms.
   **FACT (queried today):** `ohlcv_daily` source `massive_grouped` spans 2025-01-03 →
   2026-09-08 and holds **168 pre-sealed sessions** (≤ 2025-09-07). The 60 most recent
   pre-sealed sessions are **2025-06-11 → 2025-09-05**, and **2,312 symbols** carry ≥ 55 of
   them. A clean pre-sealed analogue of W1-SEL(2) therefore exists with **zero new data and
   zero new API calls**. W1 §12.5's "unavoidable with the available data" is not established.
   This is a blocking precondition (§13, operator approval A0).
2. **Stage A buys the evidence at ZERO sealed cost; Stage B is the only thing that costs a
   look.** Both proposals spend a sealed look in the same step as the informative part, and
   both judges said so. **FACT** (`backtest_runner.py:167`) `run_strategy_over_universe`
   contains no `session.add`/`flush`/`commit` and never touches the sealed window; gates 1–7
   are reproducible in-process, read-only, on the pre-sealed span. Only `evaluate_promotion`
   computes gate 9 and mints a `StrategySealedTest`. So the whole K3 comparison
   (v0.2.0 vs v0.1.0 pre-sealed OOS on the same expanded universe), the 81-cell grid, the
   clustered bootstrap, the leave-one-month-out sweep, the composition decomposition and the
   spread re-pricings all run for **0 looks**. The sealed look is spent once, at Stage B, only
   if Stage A passes its pre-registered kill tests and the operator says yes.
3. **v0.1.0 is NOT put through `evaluate_promotion` on the expanded snapshot.** This rejects
   the universe_power proposal's central act. Its unique products are a sealed test at
   projected n ≈ 46 / SE ≈ 0.229R — which the proposal itself declines to predict — and a
   `PAPER_APPROVED` status that **FACT** (`approval_scope.py:69-94`, `scan.py:165`,
   `get_settings().research.universe` = 25 symbols) the live scan can never exercise. Its
   *evidence* (composition split, breadth multiplier, the gate-7 identity) is all obtainable
   read-only in Stage A. Total sealed looks for this strategy: **1**, not 2.

**Total cost of this design: 1 strategy variant (cap 2), 1 sealed look (k = 5 → 6), one
universe build, one `evaluate_promotion` call.**

### 0.2 Why the mechanism angle and not the null option as the headline

MAP §0.3 and §2.3 both conclude that gate 4 is a **point-estimate** problem and that the
squeeze-timing question is "the only class of change that can move the point estimate".
universe_power says of itself, correctly, that it "cannot fix gate 4 and does not try".
So the mechanism change is the only live candidate. The null option is not discarded — it is
pre-registered in §11 as the expected outcome and as the mandatory deliverable if Stage A's
kill tests fire, and Stage A's design guarantees it costs nothing to reach it.

### 0.3 Judge-defect ledger — what was accepted, what was rejected

Accepted and corrected in this document (each independently re-verified by me where a number
was in dispute):

| # | Defect (source) | Disposition |
|---|---|---|
| A1 | Sealed-window universe selection in W1-SEL (both legitimacy judges) | **Accepted, escalated to blocking.** §0.1(1), §7.2, §13 A0. |
| A2 | Mechanism K2 "cost SURVIVED at 3.9 SE" is computed on **signal bars** (494/175), not the **trade** population (211/132) the engine takes (mechanism judge 2) | **Accepted, reproduced exactly.** On trades: v0.1.0 **0.0608 ± 0.0026 R**, v0.2.0 **0.0540 ± 0.0029 R**, Δ **1.72 SE** → **K2 does NOT survive at 2 SE**. §3.4, §4 K2. |
| A3 | "+0.009R that requires no edge claim at all" is unearned (both mechanism judges) | **Accepted.** Deleted. Gate 4's bar is stated with **no cost credit netted off**. §3.4, §5. |
| A4 | Gate-6 forecast is apples-to-oranges and its headline direction is inverted (mechanism judge 1 D3) | **Accepted.** Like-for-like, v0.2.0 is **better** for gate 6 (P(≥10) 0.920 vs 0.870), not worse. §5.6. |
| A5 | Gate-5 denominators: sub-floor cells are **dropped**, not counted as failures (mechanism judge 2) | **Accepted, code-verified.** `sensitivity.py:176-182`. §5.5, §6.2. |
| A6 | Entry-rate SEs assume within-class Poisson homogeneity the data rejects (universe_power judge 1) | **Accepted, reproduced exactly.** φ = **5.658** (ETF) / **2.250** (CS) for v0.1.0. `k = 1.767 ± 0.492` = **1.56 SE** above 1 — *not* the claimed 2.75 SE, *not* established. §3.3. |
| A7 | The composition projection is jackknife-fragile to two JPM trades (universe_power judge 2) | **Accepted, reproduced exactly** (+0.0072R dropping JPM to +0.8172R dropping GOOGL). §3.5. |
| A8 | Mechanism gate-7 forecast ("FAIL expected") is wrong on the W1 target; gate 7 is a turnover gate as coded (universe_power, both its judges) | **Accepted, code- and arithmetic-verified.** Gate 7 is forecast to **PASS** for v0.2.0 on the expanded snapshot, and the pass is a `√(trades/year)` artefact that must be disclosed. §5.7. |
| A9 | `_leakage_self_check` omits the features v6's rule is built on; adding them is R4-permitted (mechanism, both judges) | **Accepted.** `promotion.py:249-261`. §2.5, §7.3. |
| A10 | K3b at 1.0 SE has a ~16% false-pass rate and ~50% power (mechanism judge 2) | **Accepted.** K3b raised to **2.0 SE**, consistent with this programme's own evidence rule. §4 K3. |
| A11 | "strict generalisation" is false: the new `base` guard rejects a bar v0.1.0 admits at t = 50 (mechanism judge 1 D8) | **Accepted as a wording/test defect, rejected as a live failure.** I reproduced the degenerate cell **with** the guard at **211 / 51 on snapshot 3, set-identical to v0.1.0** — no snapshot-3 symbol enters at t = 50. The fix is to gate the guard behind `release_min > 0` and write the test as "identical for t ≥ 51". §2.3, §12. |
| A12 | Δk = 3.8 SE uses Poisson counting SEs (mechanism judge 1 D6, universe_power judge 1) | **Accepted.** Under quasi-Poisson, Δk = **−1.140 ± 0.513 = 2.22 SE**. Still evidence; weaker. §3.3. |
| A13 | Internal number/citation drift in both proposals (3,713 vs 3,727; `engine.py:98` vs `:102`; `promotion.py:256-262` vs `:258-261`; `daily.py:38-43` vs `:39-44`; F2's non-existent 0.631/23.68 pair; 960 vs 967; 21.1% vs 20.9%) | **Accepted.** All citations in this document re-verified against the files; F2's stored-value error is corrected in §4. |
| A14 | The variant/look budget was stated per-version, leaving the family budget open (universe_power judge 1) | **Accepted.** §9, §10 state a single family-level ceiling. |
| A15 | "The scripts are the record" but no script was preserved (mechanism judge 1 D5) | **Accepted.** §12 requires the verification scripts and their stdout to be committed alongside the implementation. |

Rejected, with reasons:

| # | Defect (source) | Why rejected |
|---|---|---|
| R1 | "Carry v0.2.0's per-trade sd as ≈ 2.25; the gate-4 hurdle is +0.297R and required n ~529" (mechanism judge 2) | **Rejected as stated.** The judge *projected* an OOS sd from the pre-sealed sd ratio. **Measured directly (FACT, today): v0.2.0's OOS sd is 1.0469, LOWER than v0.1.0's 1.5242** (−2.36 SE), while its pre-sealed sd is 1.7498, HIGHER than 1.2097 (+4.39 SE). The two cuts **disagree in sign**, so sd is *not established*. This document carries gate 4 as a **range over sd ∈ [1.05, 1.75]** and states that the *conclusion* is robust across it while the magnitude is not. §5.4. |
| R2 | "Run the unchanged v0.1.0 through `evaluate_promotion` on the expanded snapshot" (universe_power §2.2) | **Rejected.** Its evidence is obtainable read-only for 0 looks (§0.1(2)); its only unique products are a powerless sealed test and an unexercisable `PAPER_APPROVED` row (universe_power's own §2.3). |
| R3 | "This change makes gate 6 LESS likely to clear than doing nothing" (mechanism §5, volunteered against itself) | **Rejected on the arithmetic** — see A4. The self-criticism was generous but wrong. |
| R4 | "Gate 4 FAILS with high confidence" (mechanism §5) | **Rejected as over-confident.** See §5.4: with the snapshot-3 v0.2.0 OOS figure now measured (§0.5) and sd unresolved, gate 4's outcome on the expanded snapshot is **genuinely uncertain**. Both outcomes are pre-registered; neither may be reported as news. |
| R5 | "Add axes anyway / don't add axes" (universe_power §6 argues against adding gate-5 axes) | **Rejected here only because the premise differs.** universe_power changes no parameter, so it owed no axis. This design introduces two parameters, so MAP §4.2 item 6 **requires** both as axes. §6. |
| R6 | "Cost is 104% of the net edge" (mechanism §3.5/§8/§11) | **Rejected — wrong population and wrong denominator.** Measured on the OOS **trades** gate 3 actually reads: **0.0548 ± 0.0036 R** against +0.0613R = **89%**, gross pre-cost OOS edge ≈ **+0.116R**. MAP §0.4's 0.042R is still an understatement, by 30%, not 52%. §3.4. |

### 0.4 Provenance of every new number in this document

**FACT.** All computations were run against a **read-only backup copy** of the live database
(`sqlite3 "file:data/signalforge.sqlite?mode=ro" ".backup $TMPDIR/scratch-v6synth.sqlite"`,
`pragma integrity_check` = ok, 2026-09-10), with `DATABASE_URL` pointed at the copy. **No
command wrote to `data/signalforge.sqlite`.** No promotion, sensitivity or sealed entry point
was invoked; no provider API was called; no file under `src/` or `tests/` was modified. The
proposed rule was implemented as a throw-away class in a scratchpad script.
Trades were produced by `backtest.engine.run_backtest` driven by
`research.strategies.base.signal_fn_for` and `research.regime.regime_lookup`, with the
IS/OOS split reproduced from `backtest_runner.py:29, 158-160` (`_TRAIN_FRAC = 0.6`, per
symbol) and `CostModel()` frozen (`costs.py:11-16`), `spread_bps` left at the engine default
5.0 exactly as `backtest_runner.py` leaves it.
**Reproduction check (FACT):** v0.1.0 recomputes to **211 pre-sealed / 51 OOS, expectancy
+0.06135R, OOS sd 1.5242, pre-sealed sd 1.2097** on snapshot 3 — matching stored evaluation
36 and both judges' independent reproductions.
**Span:** pre-sealed only, **2016-09-10 → 2025-09-07**. **Nothing inside 2025-09-08 →
2026-09-08 was computed.**

### 0.5 Disclosure — an abstention this document broke, and what follows from it

The mechanism proposal's §3.6 deliberately never computed the proposed rule's P&L, so that no
parameter could be selected on it. **In recomputing v0.2.0's per-trade dispersion to settle
judge defect R1 above, I necessarily computed its mean as well.** Concealing the number would
be worse than reporting it, so:

**FACT (snapshot 3, pre-sealed):** v0.2.0 at `squeeze_lag = 5, release_min = 1.0` gives
**pre-sealed +0.2937R ± 0.1523 (n = 132, sd 1.7498)** and **OOS +0.3168R ± 0.1851
(n = 32, sd 1.0469)**, against v0.1.0's +0.1651R ± 0.0833 and +0.0613R ± 0.2134.
**DERIVED:** the OOS difference is **+0.2555 ± 0.2825 = 0.90 SE**; the all-pre-sealed
difference is **+0.1286 ± 0.1736 = 0.74 SE**. **Neither is evidence.**
**DERIVED:** v0.2.0's own gate-4 CI low on snapshot 3 would be ≈ **−0.046R** — gate 4 still
fails there.

Three consequences, binding:

1. **No parameter is changed because of this number.** `squeeze_lag = 5` and
   `release_min = 1.0` were fixed by the mechanism proposal on stated mechanical grounds (half
   the `ATR(10)` window; the zero-parameter statement of release) before any expectancy
   existed, and they are carried into this design **unchanged**. The variant count stays 1.
2. **This is pre-sealed data, so R1 is not engaged** — R1 forbids *sealed* numbers motivating
   design and explicitly requires pre-sealed motivation. It is an **R5 multiple-testing
   disclosure**, and it is recorded here so no later reader believes the design was blind.
3. **It changes a forecast, not a design.** It is the reason §5.4 downgrades the mechanism
   proposal's confident gate-4 FAIL to "genuinely uncertain". A forecast is a prediction; R1
   and R5 govern choices.

The snapshot-3 v0.2.0 numbers **may not be used as the K3 test** (§4): n = 32 against n = 51
gives an SE of the difference of ≈ 0.28R, so the test has ~0.9 SE of power, and its only use
would be to justify re-tuning.

---

## 1. Mechanism

> **H13 (the same-bar squeeze/break conjunction is self-defeating).** v6 requires
> `ATR(10)/ATR(50) ≤ 0.75` **on the same bar** as the Donchian break
> (`breakout.py:92, 98, 102`). **FACT** (`features/daily.py:47-51`): `ATR(10)` at bar *t* is
> the simple mean of ten true ranges **including `true_range(t)`** — the break bar's own
> range, at weight 1/10. A wide-range break therefore *raises* the very ratio the filter caps.
> The conjunction does not select "a stock that was coiled and has now broken out"; it selects
> "a stock that is breaking out **feebly**". The strategy's own spec already names the
> symptom — *"contraction filter admits low-volume drift that fails to follow through"*
> (`breakout.py:80`) — but attributes it to the filter's **threshold** rather than to its
> **timing**.

This is MAP §2.3 lever 3 stated as a testable mechanism: *"is the squeeze best measured at the
breakout bar, or in the window preceding it — a coiled-then-released framing rather than
coiled-and-releasing-simultaneously"*, which the map calls "the only class of change that can
move the **point estimate**, which §0.3 shows is what gate 4 actually needs".

**Why it should work in markets.** A range contraction is information about *stored* potential
— a supply/demand balance narrowing until one side gives way. That information lives in the
contraction that **preceded** the break. What confirms the balance actually broke is the
**energy of the break bar**: a wide-range close through a 20-day high is an imbalance
resolving; a narrow-range close a few cents through the same high is drift into a stale level,
indistinguishable from noise — and, for a 1.75 × ATR stop measured on a *contracted* ATR,
indistinguishable from a stop already inside the noise band. Requiring the squeeze **before**
the break and expansion **at** the break separates those two populations. The current rule
prefers the second.

**Relation to the hypothesis set.** H10 (power) is addressed by the universe expansion this
design depends on and which costs it zero variants. H11 (edge magnitude insufficient) is what
this design tests. H12 is refuted by `v6_regime_power.md`, which found the bear-bucket zero is
a property of the inherited `not ctx.regime.risk_off` conjunct, not of the contraction rule.
This design deliberately **does not touch** that conjunct: it is an availability lever, mixing
it in would make the result uninterpretable, and it would cost a second variant (R5).

---

## 2. Exact change

**File:** `src/signalforge/research/strategies/breakout.py`. New behaviour ships as
`VERSION = "0.2.0"` (R3/R7); version id 6's rows, sealed tests and `spec_json` are never
mutated.

### 2.1 `VERSION` (breakout.py:21)

```python
VERSION = "0.1.0"        # before
VERSION = "0.2.0"        # after
```

**FACT** (`persistence.py:46`, `upsert_strategy_version` matches on
`(strategy_id, version)`; `db/models/research.py:47` `UniqueConstraint("strategy_id",
"version")`): a bumped string creates a **new** `StrategyVersion` row and leaves id 6
untouched. **FACT** (`db/models/research.py:263`): `StrategySealedTest` is unique per
`(strategy_version_id, dataset_snapshot_id)`, so the new version has never been sealed
anywhere — R3's staleness trap cannot fire.

**Accepted consequence:** `VERSION` is module-level, so after the bump the
`VolatilityBreakout` class can no longer construct a v0.1.0 spec. Safe **here and only here**
because **FACT** (`strategies/__init__.py:43-51`) `default_strategies()` registers exactly one
instance of this class, and **FACT** (MAP §0.1) version 6 is EXPERIMENTAL with no approved
scope, so nothing live reads its spec hash. R7's live-scope constraint binds v2 and v5, which
this change does not touch. **This reasoning must be re-checked if either fact changes.**

### 2.2 `BreakoutParams` (breakout.py:24-32) — two new fields, nothing removed, nothing retuned

```python
@dataclass(frozen=True, slots=True)
class BreakoutParams:
    channel: int = 20
    contraction_max: float = 0.75
    squeeze_lag: int = 5          # NEW — squeeze measured this many bars BEFORE the break
    release_min: float = 1.0      # NEW — break-bar TR, in units of ATR(50) at t-1
    atr_window: int = 14
    stop_atr: float = 1.75
    target_atr: float = 3.5
    time_stop_short: int = 10
    time_stop_medium: int = 40
```

Every pre-existing default is **unchanged**. `contraction_max` stays 0.75 — this design does
not loosen it, which MAP §2.3 lever 3 rules out as "buying quantity at the direct expense of
quality".

**`squeeze_lag = 5`:** `ATR(10)` evaluated at `t − 5` spans bars `t−14 … t−5`, disjoint from
the break bar *and* from the four-bar approach into it where pre-break expansion typically
begins. Five is half the `ATR(10)` window — the smallest lag that makes the squeeze and
release windows non-overlapping in the intended sense. Lags 3 and 10 are grid neighbours (§6),
not alternatives.
**`release_min = 1.0`:** "the break bar's true range is at least the average true range of the
last 50 sessions" is the zero-parameter statement of *release*, measured against the same
50-day baseline the contraction ratio already uses as its denominator. It introduces no new
scale and no new lookback. 0.8 and 1.2 are grid neighbours.
**Both were fixed before any expectancy existed** — see the §0.5 disclosure.

### 2.3 `evaluate` (breakout.py:90-99)

```python
    def evaluate(self, series, t, ctx):
        p = self.params
-       contraction = atr_contraction(series, t, 10, 50)
+       contraction = atr_contraction(series, t - p.squeeze_lag, 10, 50)   # squeeze BEFORE
        dc_hi = donchian_high(series, t, p.channel)
        dc_lo = donchian_low(series, t, p.channel)
        a = atr(series, t, p.atr_window)
        if any(math.isnan(x) for x in (contraction, dc_hi, dc_lo, a)) or a <= 0:
            return None
        if contraction > p.contraction_max:
            return None
+       if p.release_min > 0.0:                                            # release AT the break
+           base = atr(series, t - 1, 50)
+           if math.isnan(base) or base <= 0 or true_range(series, t) / base < p.release_min:
+               return None
        close = float(series.close[t])
        ...  # long / short branches at :102-123 unchanged, byte for byte
```

Import line 16 gains `true_range` (exported from `features/daily.py:39-44`). **No new feature
function is written.** Long/short branches, stops, targets, time stops and the inherited
`not ctx.regime.risk_off` gate (`:102`) are byte-for-byte unchanged. Single-mechanism change
by design (R5).

**The `release_min > 0.0` guard is the fix for judge defect A11** and is why the diff differs
from the mechanism proposal's. Placing the `base` NaN/`<= 0` check unconditionally in the
shared guard makes the degenerate cell `(squeeze_lag = 0, release_min = 0.0)` require
`t ≥ 51` where v0.1.0 requires only `t ≥ 50` (`daily.py:47-48`: `if t + 1 < window + 1: return
NAN`), so it would be a strict **subset** of v0.1.0, not an identity. Gated as above, the
degenerate cell is an exact identity by construction on every universe.
**FACT (verified today):** even *ungated*, the degenerate cell reproduces **211 / 51** on
snapshot 3, set-identical to v0.1.0 (symmetric difference empty) — no snapshot-3 symbol enters
at t = 50. The gate makes the identity guaranteed rather than lucky.

### 2.4 `spec()` (breakout.py:49-88) — text only

`rule_definition`, `feature_definitions` and `entry_conditions` regenerated, e.g.
`"contraction(t - squeeze_lag) <= contraction_max and TR(t) >= release_min * ATR(50, t-1) and
close beyond the Donchian edge"`. **FACT** (`persistence.py:32-44`): `spec_json` feeds
`spec_json_hash`, compared by `approval_scope.scan_scope_matches`
(`approval_scope.py:89-92`) — but only for **approved** versions. This strategy has none, and
`approved_scopes` is keyed by `strategy_version_id` (`approval_scope.py:45-66`), so v2's and
v5's approved scopes and their `scopes[0]` selection are untouched (R7, R7b).

### 2.5 Other touchpoints

| File | Change | Rule |
|---|---|---|
| `research/promotion.py:199-208` | add `squeeze_lag` and `release_min` to the `volatility_breakout` grid (§6) | R4 carve-out: makes gate 5 **more** searching |
| `research/promotion.py:249-261` (`_leakage_self_check`) | add `atr_contraction(10,50)`, its `t−5` form, `donchian_high(20)`, `true_range` (§7.3) | R4 carve-out: makes gate 8 **more** searching |
| `research/strategies/__init__.py:43-51` | **no edit** — the single registered instance picks up the new `VERSION` | R7 |
| `tests/` | new leakage + rule + degenerate-identity tests (§12) | — |
| `src/` — anything else | **no edit of any kind** | — |

---

## 3. Pre-sealed evidence

All numbers below are on the pre-sealed span only. Provenance §0.4.

### 3.1 The mechanical claim — the same-bar filter selects feeble breaks (26 SE, all four snapshots)

Definitions: a **break bar** is a session *t* with `close(t) > donchian_high(t, 20)`,
`ATR(14, t)` defined and positive, and the proxy regime at *t* **not** `risk_off` (v6's long
gate open). **Energy** `E(t) = true_range(t) / ATR(50, t−1)` — the break bar's range against
the same 50-day baseline the contraction ratio uses, sharing no bar with the break.

**FACT** (from the mechanism proposal, **independently reproduced to every printed digit by
both judges** on separate read-only runs; not recomputed by me):

| snapshot | all break bars | after `contraction(t) ≤ 0.75` | difference | SE units |
|---|---|---|---|---|
| **3** | **1.1385 ± 0.0112** (n = 3,727) | **0.7184 ± 0.0116** (n = 494) | **−0.4201 ± 0.0161** | **26.1 SE** |
| 2 | 1.1468 ± 0.0117 (n = 3,792) | 0.7192 ± 0.0116 (n = 497) | −0.4276 ± 0.0165 | 26.0 SE |
| 1 | 1.1468 ± 0.0117 (n = 3,792) | 0.7192 ± 0.0116 (n = 497) | −0.4276 ± 0.0165 | 26.0 SE |
| 4 | 1.1513 ± 0.0116 (n = 3,869) | 0.7206 ± 0.0114 (n = 507) | −0.4307 ± 0.0163 | 26.5 SE |

**The typical break bar in this universe has a range 1.14× its own 50-day ATR; the bars v0.1.0
actually trades have 0.72× — 37% smaller, identically on all four snapshots, 26 SE from zero.**
The arithmetic is elementary: with `ATR(10)` averaging ten true ranges, a break bar at
`2 × ATR(50)` contributes 0.20 to the ratio by itself, forcing the other nine below
`0.61 × ATR(50)`; a break bar at `0.5 × ATR(50)` only requires the other nine to average 0.78.

**FACT:** the lag alone, without the release test, already decouples the two conditions —
bars with `contraction(t−5) ≤ 0.75` have mean energy **0.9505 ± 0.0274** (n = 571) against
**0.7184 ± 0.0116**: **+0.2321 ± 0.0298 = 7.8 SE** — while admitting **more** bars (571 vs
494). It is not a stricter test, it is a differently-timed one, which is the mechanism's claim.
Bars passing the full proposed rule have mean energy **1.5751 ± 0.0659** (n = 175).

**Defect carried forward for the implementer (A13):** the proposal's §3.5 reports n = 3,713
for the same population §3.1 reports at 3,727; both judges reproduced **3,727**. The §3.5
table must be republished on the §3.1 population or the 14-bar difference explained.

### 3.2 The two rules select nearly disjoint populations — and it is worse than reported

**FACT (verified today, snapshot 3, TRADE level, not signal-bar level):** v0.1.0 takes 211
trades and v0.2.0 takes 132; **exactly 11 `(symbol, entry_date)` pairs are common** — **8.3%
of v0.2.0's trades and 5.2% of v0.1.0's.** (The proposals' 32 / 18.3% / 6.5% figures are at
**signal-bar** level; the engine jumps to `exit_idx + 1` after each fill, `engine.py:149`, so
most overlapping signals never become trades.)

Two consequences: (i) "will the surviving trades still be profitable?" is the wrong question —
**92% of v0.2.0's trades are new**; (ii) when the two OOS samples are compared on the expanded
snapshot, treating them as approximately independent for the SE of the difference is
*better* justified than the proposal claimed.

### 3.3 Composition — corrected for over-dispersion

**FACT (verified today, snapshot 3, all pre-sealed).** ETFs = the 15 of
`DIA, IWM, QQQ, SPY, XLB…XLY`; single names = the 9 of
`AAPL, AMZN, GOOGL, HD, JPM, MSFT, NVDA, UNH, XOM`. Symbol-years: ETF 131.31, CS 79.79.

| | ETF trades | CS trades | ETF rate /sym-yr | CS rate /sym-yr | **k = ETF/CS** |
|---|---:|---:|---:|---:|---:|
| v0.1.0 | 157 | 54 | 1.1956 | 0.6768 | **1.767** |
| **v0.2.0** | **67** | **65** | **0.5102** | **0.8147** | **0.626** |

**FACT (verified today): within-class Poisson homogeneity is rejected.** Per-symbol trade
counts for v0.1.0 run SPY 28, QQQ 21, DIA 19, XLK 18 … XLE/XLU/XLV 3 (ETF) and GOOGL 11,
AMZN 10, MSFT 10 … NVDA 2 (CS). Quasi-Poisson dispersion **φ = 5.658 (ETF), 2.250 (CS)** for
v0.1.0 and **1.710 / 1.723** for v0.2.0.

**DERIVED, with quasi-Poisson SEs** (this replaces both proposals' Poisson counting SEs):

- `k(v0.1.0) = 1.767 ± 0.492` → **1.56 SE above 1. Not established.** universe_power's claim
  that "W1's uniform-rate assumption is rejected at > 2 SE" is **refuted**.
- `k(v0.2.0) = 0.626 ± 0.143`.
- **Δk = −1.140 ± 0.513 = 2.22 SE** — still above the 2 SE bar, so the composition shift **is**
  evidence, but at 2.2 SE, not the mechanism proposal's 3.8 SE.

Mechanistically Δk is what H13 predicts: a diversified index rarely produces a wide-range
break, because its constituents' idiosyncratic moves net out. v0.1.0's preference for feeble
breaks is therefore also a preference for ETFs — **FACT** SPY/QQQ/DIA/XLK alone supply 86 of
211 (40.8%) of v0.1.0's trades and 27 of 132 (20.5%) of v0.2.0's.

**DERIVED, breadth multiplier** to 15 ETFs + 135 CS, using W1 §4.3's formula
`(15k + 135)/(15k + 9)`, with bands from the quasi-Poisson SEs on k:

| rule | k | multiplier | pre-sealed n | **OOS n** |
|---|---:|---:|---:|---:|
| v0.1.0 | 1.767 | **4.55** [3.94, 5.48] | ≈ 960 | ≈ **232** |
| **v0.2.0** | **0.626** | **7.85** [7.14, 8.75] | ≈ **1,036** | ≈ **251** [228, 280] |

**v0.2.0 cuts trade count by 37% on the 24-symbol universe and still lands with slightly MORE
out-of-sample trades than v0.1.0 on the 150-symbol universe**, because the universe being
expanded into is 90% single names. HYPOTHESIS: this is a projection from a 24-symbol
composition measurement, not a measurement; F1 (§4) gives its falsification band. Note the
multiplier is a function of each cell's own ETF/CS mix and **may not be applied per grid
cell** (§6.3).

### 3.4 Cost — corrected to the trade population (defect A2/R6)

MAP §0.4 estimates v6's per-trade cost at **0.042R** from an *assumed* 1.5% ATR/price. The
assumption is right in direction and too generous in magnitude — but the mechanism proposal's
correction to 0.0640R is also wrong, because it averages over **signal bars** (494 / 175)
rather than the **trades** the engine actually takes (211 / 132).

**FACT (verified today, computed on trades using the engine's own risk unit** — `pnl_r /
pnl_pct = entry_fill / risk_per_share`, `engine.py:111, 128-129` — at the recorded
`costs_bps = 11.0`, `engine.py:144):`

| population | n | **mean cost / trade** | median |
|---|---:|---:|---:|
| v0.1.0, all pre-sealed | 211 | **0.0608 ± 0.0026 R** | 0.0526 |
| v0.2.0, all pre-sealed | 132 | **0.0540 ± 0.0029 R** | 0.0462 |
| **v0.1.0, OOS** (the set gate 3 reads) | 51 | **0.0548 ± 0.0036 R** | 0.0514 |
| **v0.2.0, OOS** | 32 | **0.0421 ± 0.0024 R** | 0.0400 |

**DERIVED:**

1. **MAP §0.4 understates v6's cost by ~30% at the entries gate 3 reads** (0.0548R vs 0.042R),
   not by 52%. Against the +0.0613R OOS point estimate, modelled transaction cost is **89% of
   the entire net edge**; the gross pre-cost OOS edge is ≈ **+0.116R**. MAP §2.3's "0.042R of
   modelled cost sits inside it" and §0.4's "68% of its entire edge" both understate it. **This
   correction stands whether or not this design is implemented.**
2. **The cost reduction is NOT established at 2 SE on the population that matters.**
   All pre-sealed: **Δ = +0.0068 ± 0.0039 R = 1.72 SE**. OOS: **Δ = +0.0127 ± 0.0044 R = 2.90
   SE**, but on n = 51 / 32. The honest statement is the all-pre-sealed one. **K2 is
   re-recorded as RUN, NOT SURVIVED at the 2 SE bar** (§4).
3. **There is no free point-estimate credit.** A cost saving of ~0.007R only becomes a
   +0.007R *expectancy* gain if the **gross-of-cost** expectancy of a population sharing 11 of
   132 trades with v0.1.0's is unchanged — which is an edge claim, just a null one, and is
   untested. Gate 4's bar in §5 is stated **with no cost credit netted off**. The saving is
   also ≈ 0.004–0.007 of v0.2.0's own per-trade sd: unmeasurable at any n this programme
   reaches.

### 3.5 The outcome gradient — uninformative in sign, both directions reported

**FACT** (mechanism §3.2, reproduced by both judges): v0.1.0's own 211 pre-sealed trades split
into energy terciles give **T3 − T1 = +0.1364 ± 0.2083 (0.65 SE)** on snapshot 3, with the
same sign and 0.57–0.61 SE on snapshots 1/2/4; the binary split at E = 0.8 gives
+0.1761 ± 0.1843 (0.96 SE). The four snapshots share ≥ 96% of their trades, so their agreement
is close to one observation.

**The contrary cut, which the mechanism proposal omitted (defect accepted, judge 2).** FACT
(from the stored gate-5 grid, eval 36, and reproduced by both judges): loosening
`contraction_max` 0.75 → 0.85 admits precisely the *higher*-energy break bars H13 wants, and
OOS expectancy moves **+0.0613R (n = 51) → −0.0512R (n = 139)**; the incremental 0.75–0.85
band is n = 88 at **−0.1164R**, i.e. ≈ 0.8 SE **against** H13. Pre-sealed the same band is
roughly flat.

**Verdict: the sign of the energy/expectancy relation is not consistently signed across the
available cuts, and every cut is under 1 SE. This is NOT evidence in either direction.** It is
also structurally the best the current sample can do: energy at v0.1.0's entries has mean
0.745 and sd 0.250 against 1.139 / 0.682 unfiltered — **the current rule cannot measure the
gradient over the range the design opens up, because it never trades there.**

**Fragility of everything measured against +0.0613R.** **FACT** (`v6_regime_power.md` §6.3):
dropping one month (2023-12, 7 of 51 OOS trades) moves v0.1.0's OOS expectancy from +0.0613R
to **−0.2623R**. **FACT (verified today):** the 14 single-name OOS trades sit in 8 symbols, and
leave-one-symbol-out moves their mean from **+0.0072R (drop JPM, 2 trades at +2.6967R mean)**
to **+0.8172R (drop GOOGL)**, against a pooled +0.3914R. Any composition-based projection
inherits this fragility and is reported as a range, never a point.

### 3.6 What is and is not established, in one place

| Claim | Status |
|---|---|
| Same-bar conjunction selects break bars 37% smaller, all four snapshots | **FACT, 26 SE** — established |
| The lag alone decouples the conditions and admits more bars | **FACT, 7.8 SE** — established |
| The rule shifts the trade mix from ETFs to single names (Δk) | **FACT, 2.22 SE** — established, weakly |
| Cost per trade falls | **1.72 SE on the population that matters — NOT established** |
| Energy predicts expectancy | **≤ 1 SE, and oppositely signed across cuts — NOT established** |
| v0.2.0's expectancy exceeds v0.1.0's (snapshot 3) | **0.90 SE — NOT established** (§0.5) |
| v0.2.0's per-trade sd differs from v0.1.0's | **NOT established — the two cuts disagree in sign** (−2.36 SE OOS, +4.39 SE pre-sealed) |
| `k(v0.1.0) > 1` (ETF concentration) | **1.56 SE — NOT established** |

---

## 4. Falsification

Stated **before** the Stage A run. R10 requires conditions that hold across all four
snapshots; K1, K2 and K2b are of that kind and have already been run on all four. K3 and K5
are the Stage A outcome tests on the expanded snapshot and can be run once.

### K1 — mechanical (all four snapshots) — **RUN, SURVIVED**
*Kill if the same-bar filter does not bias break-bar energy downward by ≥ 2 SE on any
snapshot.* Observed **26.0–26.5 SE** (§3.1). **Survives.**

### K2 — cost (all four snapshots) — **RUN, NOT SURVIVED at the 2 SE bar**
*Kill the cost half of the argument if the released population does not carry a larger risk
unit by ≥ 2 SE.* Observed on the trade population: **+0.0068 ± 0.0039 R = 1.72 SE**
all-pre-sealed (§3.4). **The cost argument is withdrawn as evidence.** It is retained only as
a directional disclosure, and **no cost credit is netted against gate 4's bar.** The design
proceeds on K1 and K3 alone.

### K2b — counts (all four snapshots) — **RUN, SURVIVED, narrowly on snapshot 3**
*Kill if the rule leaves fewer than 30 OOS trades on any existing snapshot, i.e. if it only
exists on a 150-name universe.* Observed **32 / 34 / 34 / 36** on snapshots 3 / 2 / 1 / 4 —
survives by **2 trades on snapshot 3**, recorded as a zero-margin case (§5.9).

### K3 — outcome (Stage A, expanded snapshot, pre-registered) — the decisive test
Let `E₀₂` and `E₀₁` be the **pre-sealed OOS expectancy** of v0.2.0 and v0.1.0 on the expanded
snapshot, both from read-only `run_strategy_over_universe` calls (no sealed test, no look).

- **K3a — sign (hard kill).** If `E₀₂ ≤ E₀₁`, the mechanism is refuted. **Stop.** No
  re-parameterisation, no second variant, no Stage B. Write §11.
- **K3b — magnitude (hard kill).** If `E₀₂ − E₀₁ < 2.0 SE` of the difference, the mechanism is
  **unsupported at achievable power**. **Stop.** Write §11.
  *Raised from the mechanism proposal's 1.0 SE* (judge defect A10: at 1.0 SE the false-pass
  rate under a true null is ≈ 16%). 2.0 SE is this programme's own evidence rule (MAP §0.3) and
  applying a looser bar to one's own kill test than to everyone else's evidence is a weakening
  in disguise.
  **SE convention, pre-registered so it cannot be chosen afterwards:** the binding form is the
  **entry-month clustered** SE — the iid bootstrap SE of the difference multiplied by **1.638**
  (`v6_regime_power.md` §6.1, the same factor §5.4 applies as ×2.68 in variance). Both forms
  are reported; the clustered one binds. DERIVED at the projected n's and sd ∈ [1.05, 1.75],
  the clustered 2.0 SE threshold is a required improvement of roughly **+0.31 to +0.52R** —
  a demanding bar, stated here so a K3 failure is not later re-described as a near miss.
- **K3c — the ceiling.** Passing K3 means "the mechanism is real and measured". It does **not**
  mean "promote", and it does not by itself authorise Stage B (§13 approval A2).

### K5 — grid no-op (Stage A, pre-integration, mandatory)
*If any of the four gate-5 axes fails to change the OOS trade count or the OOS expectancy on
the expanded snapshot, gate 5 is passing at 100% having tested nothing (MAP §2.1, §4.2 item 6)
and the run is void.* Pre-computed evidence on snapshot 3 that all four bite is in §6.3; the
check is **re-run on the expanded snapshot before the gate-5 verdict is read**.

### K6 — plan kill (before any backtest)
*The plan is falsified in advance if:*
 (a) the operator declines the pre-sealed re-derivation of W1-SEL (§13 A0) — in which case
 gate 9's sealed test is contaminated by construction, Stage B buys nothing, and the design
 terminates at Stage A with §11 written; **or**
 (b) W1-COMPLETE leaves **< 120 symbols** — the projected multiplier falls under ~3.7×, the
 projected OOS n under ~200, and the gate-4 hurdle rises above the plausible range; **stop and
 re-consult the operator** rather than reaching past the pre-registered reserve list; **or**
 (c) any §12 pre-integration assertion fails — **no result may be read at all**, because a
 result read off the wrong snapshot row is an unrecorded sealed look.

### Anti-rationalisation clause (grafted from universe_power F5, carries over unchanged)
If gate 4 passes while the **ETF** sub-sample is statistically unchanged and the
**single-name** sub-sample carries the pass, the pre-registered conclusion is *"a
composition effect measured on a survivorship-biased, non-point-in-time universe"*, **not**
"v6 works". Written down now so it cannot be renegotiated later.

### Correction to universe_power F2 (defect A13)
universe_power's F2 cites stored gate-7 evidence as "0.631/0.635/0.666/0.665 against turnovers
23.68/23.97/23.75/24.65". **FACT (per the judges' queries of `gates_json`): no snapshot has
Sharpe 0.631 or turnover 23.68.** The stored pairs are **0.635 / 23.97 (evals 12 and 30),
0.666 / 23.75 (eval 36), 0.665 / 24.65 (eval 42)**, and snapshot 1 carries two non-identical v6
evaluations (ids 6 and 12). F2 is carried into this design with the corrected values.

---

## 5. Gate-by-gate forecast

**Target: the expanded snapshot only** (key per §12; 150 symbols, 15 ETFs + 135 common stocks,
selected by the **pre-sealed** liquidity rule of §13 A0). Trade sets tagged per MAP §0.2:
gates 2/3/4 read `full.out_of_sample`; gates 1/6/7 read `full.trades` (all pre-sealed, IS+OOS)
— gate 7 included despite its docstring (`config/research.py:111-113` vs `promotion.py:775`).

Projections use the §3.3 multiplier **7.85× [7.14, 8.75]** and carry per-trade sd as a
**range, sd ∈ [1.05, 1.75]**, because §0.5/§3.6 show it is not established.

| # | Gate | Trade set | v0.1.0 on snap 3 | **v0.2.0 forecast, expanded** | Notes |
|---|---|---|---|---|---|
| 0 | `data_availability` | — | pass | **PASS** | span ≫ `MIN_PRESEALED_DAYS` = 350; horizon SHORT_SWING |
| 1 | `rolling_walkforward` | all pre-sealed | 4/4 (36/98/34/43) | **PASS, high confidence** — ≈ 1,036 trades, folds ≈ 220/460/175/190 vs a 15 floor | needs 2 of 4; counts are not binding |
| 2 | `min_oos_trades` | OOS | 51 | **PASS**, ≈ **251** [228, 280] vs 30 | zero-margin only on snapshot 3 (32 vs 30), which is not the target |
| 3 | `net_expectancy` | OOS | +0.0613R | **uncertain, no point prediction** | **fails at 26 bps round trip on arithmetic alone** (§8) |
| **4** | `bootstrap_ci` | OOS | low −0.3553R, FAIL | **GENUINELY UNCERTAIN — both outcomes pre-registered** | §5.4 |
| 5 | `parameter_sensitivity` | OOS per cell | 0.667 / **0.750 exactly**; **FAILS 0.556/0.500 on snap 4** | **materially harder; no prediction** | 9 → 81 points, 4 → 8 neighbours (§6) |
| 6 | `regime_coverage` | all pre-sealed | bull 167 / **bear 0** / range 30; **14 unbucketed (6.6%)** | **bear λ ≈ 14.7, P(≥10) = 0.920; unbucketed ≈ 79 (7.6%)** | **better than v0.1.0 like-for-like** (§5.6) |
| **7** | `benchmark_comparison` | all pre-sealed | Sharpe 0.666 vs SPY 0.719, FAIL | **PASS expected — and it is a `√(trades/year)` artefact** | §5.7 |
| 8 | `data_quality_and_leakage` | — | pass on snap 3 only | **PASS iff W1-COMPLETE passes first** | strengthened by §7.3 |
| 9 | `sealed_final_test` | sealed year | −0.0979R / 10, FAIL, all four | **Stage B only; projected n ≈ 49, SE ≈ 0.15–0.25R** | derived from the pre-sealed rate ratio only; **no sealed quantity was computed** |
| 10 | `live_paper_probation` | — | pass | **PASS as coded, substantively vacuous** | §5.8 |

### 5.4 Gate 4 stated as a required n (MAP §4.2 item 5, mandatory form)

`n > (1.96 · sd / (exp − 0.02))²`, carried over the sd range because sd is not established:

| | sd = 1.05 (measured OOS) | sd = 1.55 (MAP §0.3) | sd = 1.75 (measured pre-sealed) |
|---|---:|---:|---:|
| **hurdle at n = 251** | **+0.149R** | **+0.211R** | **+0.236R** |
| required n at +0.2115R | 115 | 252 | 321 |
| required n at +0.3168R (snapshot 3's figure) | 48 | 105 | 134 |
| required n at +0.0613R (no improvement) | 2,478 | 5,426 | 6,918 |
| the same under entry-month clustering (×2.68 in variance) | 6,641 | 14,540 | 18,540 |

**Pre-registered reading, and it corrects the mechanism proposal (defect R4).** At +0.0613R
gate 4 needs ≈ 2,500–6,900 OOS trades iid — **unreachable**: `UniverseFilters.max_universe_size
= 150` (`config/research.py:139`) and the database holds **26** symbols with 10-year `massive`
history. But the design's premise is precisely that the point estimate moves, and the only
direct read on v0.2.0's point estimate (snapshot 3, n = 32, +0.3168R, 0.90 SE above v0.1.0 —
**not evidence**, §0.5) sits **above** the hurdle at every sd in the range. Treating that as a
weak prior and adding the new sample's own error gives a rough **P(gate 4 passes) ≈ 0.5–0.65**
— a coin flip, not a confident FAIL and not optimism.

**Both outcomes are therefore pre-registered as expected, and neither may be reported as
news:**
- **FAIL** → §11's null option is written, unchanged.
- **PASS** → the headline must state that (i) the point estimate moved ~3–5× on a snapshot that
  is a **distribution shift**, not a more-powered version of the same experiment (MAP §3(a));
  (ii) the **month-clustered** CI is reported alongside, under which **v2 and v5 themselves
  would fail** (`v6_regime_power.md` §6.2); (iii) it is a pass on **look 6** of a sealed
  calendar year; and (iv) 92% of v0.2.0's trades are entries v0.1.0 never took (§3.2), so this
  is a new selection being measured once, not a refinement being confirmed.

### 5.6 Gate 6 arithmetic — corrected like-for-like (defect A4)

**FACT** (`v6_regime_power.md` §5.3): gate-open **bear** proxy sessions are fixed by the
calendar and the shared `risk_off` filter at **19 in nine years**; at 150 symbols that is
≈ **2,700** gate-open bear symbol-days. v0.1.0's bull-bucket entry rate is 6.845 ± 0.530 per
1,000 gate-open symbol-days.

The mechanism proposal compared v0.1.0's **uniform-rate** λ = 18.5 against v0.2.0's
**composition-adjusted** λ = 14.7 and concluded its own change made gate 6 worse. That is
apples-to-oranges: v0.1.0's own measured multiplier is 4.55× against the naive 6.25×, so its
per-symbol rate on a 90%-single-name universe is ×0.728.

**DERIVED, like-for-like** (Poisson tails computed today):

| | λ | **P(≥ 10)** |
|---|---:|---:|
| v0.1.0, uniform-rate (the proposal's figure) | 18.5 | 0.988 |
| **v0.1.0, composition-adjusted** | **13.5** | **0.865** |
| **v0.2.0, composition-adjusted** | **14.7** | **0.920** |
| v0.2.0, uniform-rate | 11.6 | 0.721 |
| bear rate at half the bull rate (lower plausible bound) | 6.8 | **0.150** |

**Corrected statement: like-for-like, this design makes gate 6 slightly BETTER than the
unchanged v0.1.0 (0.920 vs 0.865), not worse.** The proposal's self-criticism was generous and
wrong.

**CAVEAT, carried verbatim.** All of this assumes "bear entry rate = bull entry rate", which
the data can neither support nor refute: **0 bear entries in 432 gate-open bear symbol-days is
1.72 SE below the 2.96 expected — under 2 SE, therefore not evidence.** The λ = 6.8 row is
included so the band is visible. **A bear bucket under 10 is a power/availability outcome,
pre-registered as carrying no information about the rule set, and it may not motivate any
change** — least of all to the inherited `not ctx.regime.risk_off` conjunct.

**Unbucketed count (MAP §0.6 / §4.2 item 5, mandatory).** v0.1.0: **14 of 211 (6.6%)**, all
between 2017-01-05 and 2017-07-25 inside the proxy's 200-session warmup and unlabelable with
any data in the database. v0.2.0 on snapshot 3: **10 of 132 (7.6%)**. Projected on the
expanded snapshot: **≈ 79 of ≈ 1,036 (7.6%)**, all warmup.

### 5.7 Gate 7 — PASS expected, and it is a turnover artefact (defect A8)

**FACT** (`portfolio_metrics.py:109-111`): `trades_per_year = n / (span_days / 365.25)` and
`sharpe = (mean_r / std) × √trades_per_year`, against a benchmark `cagr / ann_vol` from SPY
daily returns that is **0.719 on all four snapshots** and does not move with trade count.

**FACT (verified today, snapshot 3, all pre-sealed):** v0.1.0 `mean/sd_pop = 0.1651/1.2068 =
0.1368`; `0.1368 × √23.75 = 0.6665` vs the stored **0.666** — the identity reproduces the gate.
v0.2.0 `mean/sd_pop = 0.1685` at turnover `23.75 × 132/211 = 14.86/yr` → **Sharpe 0.650**.

**DERIVED on the expanded snapshot:** v0.1.0 at 4.55× → turnover 108/yr → Sharpe **1.42**;
v0.2.0 at 7.85× → turnover ≈ 117/yr → Sharpe **≈ 1.82**. Both ≫ SPY 0.719. The break-even is
**1.166×** today's turnover (≈ 28 symbols).

**FACT (reproduced by both universe_power judges):** at `contraction_max = 0.85, stop_atr =
1.75` v6 takes 477 pre-sealed trades at turnover 53.69/yr and **Sharpe 0.924 > 0.719 → gate 7
PASSES**, while its OOS expectancy is **−0.0512R**. A configuration with a negative
out-of-sample edge clears gate 7 on trade count alone.

**Mandatory disclosure attached to any gate-7 pass:**
1. the pass comes from `√(trades per year)`, not from edge quality;
2. the −0.0512R counter-example above must be printed beside it;
3. the **cluster-adjusted** figure must be reported alongside: at the programme's own 1.628×
   SE ratio the effective Sharpe is ≈ `0.1685 × √(117/1.628²) ≈ 1.12`, and the expanded run
   holds ≈ `117 × 10/252 ≈ 4.6` concurrent correlated positions against ≈ 0.94 today — **the
   artefact grows with breadth rather than shrinking**;
4. MAP §3(a)'s "breadth does not move a risk-adjusted point estimate" and W1 §8's "gate 7 FAIL
   expected" are both **wrong on this code path**, and the correction is an open item for the
   operator alongside the gate-7 docstring divergence.
**No threshold is touched (R4).** This is disclosure, which R4 explicitly permits.

### 5.8 The operational consequence of a PASS, pre-registered (grafted from universe_power §2.3)

**FACT** (`promotion.py:922`, `:943-952`): `passed = bool(gates) and all(...)`; on a pass the
pipeline sets **both** `Strategy.status` and `StrategyVersion.status` to `PAPER_APPROVED` and
writes an audit row — unconditionally, with no operator gate. **FACT**
(`approval_scope.py:69-94`): `scan_scope_matches` compares `dataset_snapshot_id`,
`config_hash`, `spec_json_hash`, `sources`. **FACT** (`scan.py:165`;
`get_settings().research.universe` = 25 symbols): the live scan resolves a 25-symbol snapshot.
**Therefore a pass on the expanded snapshot produces a `PAPER_APPROVED` strategy that can
generate no live paper candidate at all** (`ledger.py:473-512` fails at `scan_scope_matches`),
while adding a row to the operator's probation dashboard. R8's confirming test is
**unavailable** without a separate operating decision that is outside this programme.
`approved_scopes` is keyed by `strategy_version_id`, so v2's and v5's `scopes[0]` selection is
not disturbed (R7b).
**This is why Stage B requires its own operator approval (§13 A2): prose disclosure written
after the evaluation runs cannot undo a `PAPER_APPROVED` row.**

### 5.9 Zero-margin cases (MAP §4.2 item 5, mandatory)

1. **v0.1.0's gate-5 neighbour fraction is exactly 0.750 on snapshot 3** (`sensitivity.py:194`
   tests `nb_frac < min`, so 0.750 passes) **and already fails at 0.556 / 0.500 on snapshot 4**
   (eval 42). The 4-axis grid changes the neighbour denominator from 4 to 8, so the margin does
   not carry over in either direction — it is a new test.
2. **v0.2.0 clears gate 2 on snapshot 3 by 2 trades (32 vs 30).** Snapshot 3 is not the target;
   on the expanded snapshot the margin is ≈ 221 trades.
3. **v5's bear bucket is 11 against a floor of 10** — untouched by this design, which registers
   a new version of a different strategy. Recorded because MAP §4.2 item 5 requires it, and
   because it is the standing precedent for why a λ ≈ 14.7 projection is not a comfortable pass.
4. **v0.1.0's OOS expectancy is a 12-cluster estimate**: dropping 2023-12 (7 of 51 trades)
   takes +0.0613R to −0.2623R (§3.5).
5. **The single-name OOS sub-sample is an 8-symbol estimate**: dropping JPM's 2 trades takes
   +0.3914R to +0.0072R (§3.5).

---

## 6. Sensitivity-grid plan

MAP §4.2 item 6 is a hard requirement: **every parameter the v0.2.0 introduces or changes
becomes a pre-registered gate-5 axis.** This design introduces two.

### 6.1 The pre-registered grid (fixed now, before any expanded-snapshot number exists)

`research/promotion.py:199-208`, `volatility_breakout` branch:

```python
        return factory, {
            "contraction_max": [0.65, 0.75, 0.85],   # unchanged
            "stop_atr":        [1.5, 1.75, 2.0],     # unchanged
            "squeeze_lag":     [3, 5, 10],           # NEW
            "release_min":     [0.8, 1.0, 1.2],      # NEW
        }
```

- **3⁴ = 81 points**, within `MAX_GRID_POINTS = 120` (`sensitivity.py:29, 137-139`). No
  existing axis is removed — removing one reduces coverage and is treated as a weakening (R4).
- **FACT** (`promotion.py:203-207`): the factory uses `_replace(base, **p)`, so new dataclass
  fields flow through with no plumbing edit, and a *renamed* field would raise `TypeError`
  loudly (`promotion.py:50`).
- Shipped defaults sit at the **centre** of every axis, so each axis contributes exactly two
  one-step neighbours: **8 neighbours**, against v0.1.0's 4.
- Runtime: each point is a full `run_strategy_over_universe` over the pre-sealed span
  (`sensitivity.py:143-159`) — measured at ~3.4 s for 24 symbols → ≈ 21 s for 150 → **≈ 28
  minutes for the grid**, plus gate 1's folds. Budget it; do not discover it.

### 6.2 What the wider grid costs, and how the denominators actually work (defect A5)

**FACT** (`sensitivity.py:176-182`):

```python
    evaluable = [p for p in points if p.n_trades >= min_trades]
    positive  = [p for p in evaluable if p.oos_expectancy_r > 0]
    neighbours = [p for p in evaluable if p.is_neighbour]
    pos_frac = len(positive) / len(evaluable); nb_frac = len(neighbour_pos) / len(neighbours)
```

**Cells below the 15-trade floor are DROPPED from both denominators, not counted as failures.**
So "6 of 8 neighbours" and "≥ 49 of 81 points" hold only if every cell clears 15 OOS trades.
On snapshot 3 the `contraction_max = 0.65` neighbour has **6 OOS trades** and would be dropped,
making the neighbour test **6 of 7**; only **63 of 81** cells are evaluable there, so the
positive-fraction bar would be 38 of 63, not 49 of 81. **The mechanic can make gate 5 easier as
well as harder, and the realised denominators must be printed with the verdict.**

This design still makes gate 5 **materially harder in expectation**, and that is intentional:
v0.1.0 needed 3 of 4 neighbours; v0.2.0 needs 6 of 8 when all clear the floor. **FACT**
(`v6_regime_power.md` §5.2): at this effect size a grid cell's sign is close to a coin flip
(P(positive) ≈ 0.61 at n = 51), and P(pass) fell out at ≈ 0.51 for the 9-point grid. With 81
points the positive-fraction test becomes more reliable; the 8-neighbour test is harder to
clear by luck. **A gate-5 failure is a likely and largely uninformative outcome and is
pre-registered as such.**

### 6.3 The no-op check (MAP §4.2 item 6) — pre-computed on snapshot 3, all four axes bite

**FACT** (snapshot 3, reproduced by both mechanism judges; baseline cell
`(0.75, 1.75, 5, 1.0)` = **32 OOS / 132 pre-sealed**):

| axis moved one step | OOS n | pre-sealed n | moves the count? |
|---|---:|---:|---|
| `contraction_max` 0.75 → 0.65 | **6** | 28 | yes — **and falls below the 15 floor on snapshot 3** |
| `contraction_max` 0.75 → 0.85 | **91** | 344 | yes |
| `stop_atr` 1.75 → 1.5 | 32 | 132 | **no — by design; it changes exits, not entries** |
| `stop_atr` 1.75 → 2.0 | 32 | 132 | **no — same** |
| `squeeze_lag` 5 → 3 | **25** | 107 | yes |
| `squeeze_lag` 5 → 10 | **36** | 133 | yes |
| `release_min` 1.0 → 0.8 | **48** | 191 | yes |
| `release_min` 1.0 → 1.2 | **22** | 91 | yes |

`stop_atr` changes no entry, so its no-op check is on **expectancy**, and **FACT** (eval 36
gate-5 evidence, v0.1.0) it demonstrably moves it: at `contraction_max = 0.75` the three
`stop_atr` values return **+0.0296 / +0.0613 / +0.0646 R** on 51 / 51 / 50 trades. **All four
axes satisfy §4.2 item 6; no field is retained-but-unused, so MAP §2.1's silent 100%-pass
failure mode cannot occur.**

**Cell coverage on the expanded snapshot — HYPOTHESIS, not a finding (defect A5/A12).** Across
81 cells on snapshot 3 the OOS n ranges 4 … 127 and 63 of 81 reach the floor. The mechanism
proposal asserted that at 7.85× "all 81 cells clear the floor". **That is a projection, not a
measurement**: the multiplier is a function of each cell's own ETF/CS mix, and low
`contraction_max` cells are mechanically more ETF-tilted, so k differs by cell. The
conservative check is the one to quote: at v0.1.0's own **4.55×**, the smallest cell (4 OOS)
projects to **≈ 18**, still ≥ 15 — but the 4-trade base carries roughly ±50% sampling error, so
**one or two cells falling below the floor is an expected outcome** and the realised
`evaluable` count must be printed.
Note (MAP §4.3): `sensitivity_min_grid_trades = 15` is **also** gate 1's per-fold floor
(`promotion.py:632`; `config/research.py:106`), so this paragraph argues about gate 1 too.
Neither constant is changed.

---

## 7. Leakage argument

### 7.1 Code-level: clean, and the failure mode that would matter does not exist

**FACT** (`engine.py:102`): the engine calls `signal_fn(series.head(t), t)` — the strategy is
handed a series truncated at *t* and physically cannot read later bars. **FACT**
(`engine.py:108-109`): the entry fills at `series.open[t+1]`, so the signal bar's close is
fully observable before the decision is acted on.

| expression | bars read | ≤ t? |
|---|---|---|
| `atr_contraction(series, t − p.squeeze_lag, 10, 50)` | `t−54 … t−5` at lag 5 (`t−59 … t−10` at lag 10) | yes |
| `atr(series, t − 1, 50)` | `t−50 … t−1` (`daily.py:47-51`) | yes |
| `true_range(series, t)` | `high[t]`, `low[t]`, `close[t−1]` (`daily.py:39-44`) | yes |
| `donchian_high/low(series, t, 20)` | `t−20 … t−1` — **excludes today** (`daily.py:92-99`) | yes |
| `atr(series, t, 14)` | `t−14 … t` | yes |
| `ctx.regime` | `regime_lookup(proxy)[date(t)]`, point-in-time (`regime.py:65-96`) | yes |

**Negative-index hazard checked and absent:** `atr()` guards with `if t + 1 < window + 1:
return NAN` (`daily.py:48`), so `atr_contraction(series, t − lag, 10, 50)` returns NaN rather
than wrapping a negative index onto the tail of the array. Warm-up: `t ≥ 55` (lag 5) and
`t ≥ 51`, against v0.1.0's `t ≥ 50` and an engine warmup of `min_bars // 2 = 30`
(`backtest_runner.py:206`) — **5 candidate bars lost per symbol** (≈ 0.23% of snapshot 3's
symbol-bars), recorded so it is not later mistaken for an effect.

`true_range(t)` uses the signal bar's own high and low — the same information horizon v0.1.0
already relies on for `close(t) > donchian_high(t)` and `stop = close(t) − 1.75 × ATR(14, t)`,
and strictly before the `t+1` open at which the trade fills. **No new feature function**, so
the `(series, t)` contract is not extended. **No cross-sectional or breadth term**, so
`StrategyContext` (`base.py:15-19`) is untouched and this is **not** a shared-surface change.

### 7.2 Universe-level: the real exposure, and the blocking fix (defect A1)

No gate detects universe-level lookahead, and this is where the exposure is.

1. **Sealed-window selection — the blocking defect.** W1-SEL ranks by median dollar volume
   over **2026-06-12 → 2026-09-08** from a base pool screened at 2026-09-08
   (`w1_universe_preregistration.md:52-72`), i.e. membership is defined by a statistic computed
   **entirely inside the sealed window**, and every member is selected for being liquid and
   still listed at the **end** of the sealed year. Gate 9 would then be run over the same
   window that chose its universe. **MAP §1 R1 forbids sealed data motivating a universe
   choice.**
   **FACT (queried today): the fix exists with no new data.** `massive_grouped` holds **168**
   pre-sealed sessions; the 60 most recent are **2025-06-11 → 2025-09-05** and **2,312 symbols**
   carry ≥ 55 of them. **Requirement: re-derive W1-SEL(2) on 2025-06-11 → 2025-09-05, re-run
   the rank order, the 135-name cut, the reserve list and the liquidity floor on that basis,
   and re-key the snapshot** (§12, §13 A0). This can only make the universe less
   hindsight-favoured, never more, and it is applied **before** any backtest.
2. **Survivorship remains, and cannot be fixed here.** Discovery is active-tickers-only, so
   names delisted or failed between 2016 and 2026 can never enter, regardless of which
   liquidity window ranks the survivors. **This must be disclosed verbatim in every report on
   this snapshot.** The size of the effect is unmeasurable with the data held.
3. **Snapshot 3 has the same defect, arguably worse, and §3.3/§3.5 bound it.** Its 9 single
   names are a hand-picked mega-cap set returning +0.5251R ± 0.1799 (all pre-sealed) against
   the 15 ETFs' +0.0412R ± 0.0915 — and the OOS version of that gap is jackknife-fragile to two
   JPM trades. **Pre-registered: the expanded run's single-name expectancy is EXPECTED to come
   in lower than +0.5251R, and that is confirmation of this caveat, not a disappointment to be
   explained away.**
4. **Bars are split-adjusted as of fetch date, not point-in-time**, and `validate.py:180-205`'s
   `adjustment_behaviour` check is a **no-op** for this source because `massive.py:212` sets
   `adj_close = close`. Expansion applies this known bias to 6× more names.
5. **The dual-source hazard is a leakage hazard.** Omitting `source="massive"` loads
   `massive_grouped` too, duplicating every session 2025-01-03 → 2026-09-08 — **inside the
   sealed window**. `source="massive"` is asserted in the §12 pre-integration checks.

**Conclusion: the code-level leakage surface is clean and this design adds none. The
universe-level exposure is inherited, is partly fixable (item 1, and the fix is required), and
is partly not (item 2, and it is disclosed).**

### 7.3 A gate-8 gap this design closes (R4-permitted strengthening)

**FACT** (`promotion.py:249-261`): `_leakage_self_check` covers only `sma(50)`,
`rolling_return(20)`, `atr(14)` and `realized_vol(20)`. **`atr_contraction`, `donchian_high`,
`donchian_low` and `true_range` are not in the list** — so v0.1.0's gate-8 pass never exercised
the features its own entry rule is built on. Add:

```python
        ("atr_contraction(10,50)", lambda s, t: atr_contraction(s, t, 10, 50)),
        ("atr_contraction(10,50) @ t-5", lambda s, t: atr_contraction(s, t - 5, 10, 50)),
        ("donchian_high(20)", lambda s, t: donchian_high(s, t, 20)),
        ("true_range", lambda s, t: true_range(s, t)),
```

This makes gate 8 strictly more searching and can never make it easier to satisfy — the same
R4 carve-out that permits adding a missing sensitivity grid. **If it ever fails, the finding is
about `features/daily.py`, not about this design, and must be reported as such** — including
for the already-approved v2 and v5, which share `atr`.

---

## 8. Cost-model statement

**The cost model is unchanged and is not touched.** **FACT** (`costs.py:11-16`):
`commission_per_share = 0.0`, `commission_min_per_order = 0.0`, `slippage_bps = 3.0`,
`half_spread_fill_penalty = True`. **FACT** (`engine.py:90, 94, 144`): `spread_bps` default
5.0 → `slip = (3.0 + 2.5)/10,000` → **11.0 bps round trip**, recorded per trade. **FACT**
(`backtest_runner.py:205-206`): `spread_bps` is never overridden, so the assumption is
**universe-independent** — SPY and the 150th name by ADV alike.

**Per-trade cost in R, measured on the trade population** (§3.4; `stop_atr` unchanged at 1.75):

| round trip | quoted spread | v0.1.0 OOS cost | **v0.1.0 net OOS** | v0.2.0 OOS cost |
|---:|---:|---:|---:|---:|
| **11.0 bps** (frozen — what the gates use) | 5 bps | **0.0548R** | **+0.0613R** | **0.0421R** |
| 16.0 bps ("2×" under W1 §7.1's reading) | 10 bps | 0.0797R | **+0.0364R** | 0.0612R |
| 26.0 bps (MAP §0.4 / §3(a) "2×") | 20 bps | 0.1295R | **−0.0134R** | 0.0995R |
| 31.0 bps ("5×" under W1 §7.1's reading) | 25 bps | 0.1544R | **−0.0383R** | 0.1186R |
| 66.0 bps (MAP §0.4 / §3(a) "5×") | 60 bps | 0.3288R | **−0.2127R** | 0.2526R |

MAP §4.2 item 8 and W1 §7 make the 2× and 5× rows **mandatory reporting outputs** for any
expanded-snapshot run. The 2×/5× convention is ambiguous between MAP §0.4 and §3(a); **all four
non-baseline points are reported rather than guessing, and the operator should fix the
convention** (§13 Q1).

**Turnover delta.** **FACT** (eval 36 gate-7 evidence): v0.1.0's pre-sealed turnover is
**23.75/yr** at exposure 0.66. **DERIVED:** v0.2.0 takes 132/211 = **0.626×** the trades on a
fixed universe → turnover ≈ **14.9/yr**, exposure ≈ 0.41. Aggregate cost drag per symbol-slot
falls ~40% (`23.75 × 0.0608 = 1.44 R/yr` → `14.9 × 0.0540 = 0.80 R/yr`). On the expanded
universe **portfolio** turnover rises to ≈ 117/yr for v0.2.0 (≈ 108 for v0.1.0), which is what
drives the gate-7 artefact (§5.7); the **per-trade** figures above are what matter for
expectancy, and gates 3 and 4 are per-trade means, unaffected by the turnover rise.

**Two statements that must appear in the final report whatever happens:**

1. **MAP §0.4's 0.042R is an understatement.** Measured at v0.1.0's own OOS entries it is
   **0.0548 ± 0.0036 R** — **89% of the +0.0613R net edge**, so the gross pre-cost OOS edge is
   ≈ **+0.116R**. MAP §2.3's "0.042R of modelled cost sits inside it" and §0.4's "68% of its
   entire edge" both understate it. **This correction stands independently of this design.**
2. **At 26 bps round trip, v0.1.0's OOS expectancy is −0.0134R: gate 3 fails on arithmetic
   alone at the 2× spread the map mandates.** v0.2.0 is better at every point and is very
   likely also under water at 26 bps. **This is the single largest threat to the whole
   strategy, and it is a data/liquidity fact, not a rule-design fact.** Mitigating context
   (W1 §4.4): the least liquid *new* name (`TRV`, 598 $M/day median) is 2.8× more liquid than
   `XLRE`, already in snapshot 3 — so the flat 5 bps is no more wrong for the new names than
   for the current ones. It is wrong for both, and **the project holds no spread data at all**
   (`universe/screen.py:47`, `spread_filter_not_licensed`), so every spread statement here is
   a modelling assumption, not a measurement.
   **Composition adds a second-order cost risk in both directions:** the trade population moves
   from 74% broad ETFs (tightest quotes, held by creation/redemption arbitrage) to ~84% single
   names, which widens spreads; but single names also carry a higher ATR/price, which shrinks
   cost in R. Neither is measurable here; both are disclosed.

---

## 9. Variant budget and stopping rule

**Family-level budget for `volatility_breakout.short_swing`, all angles combined: 1 strategy
variant, hard cap 2.** This goes in the final report verbatim (R5). The universe/power angle
contributes **0** variants (it changes no rule); this design contributes **1**.

- **Variant 1 (the only planned one):** `squeeze_lag = 5`, `release_min = 1.0`, everything else
  at v0.1.0 defaults. Both values fixed on mechanism before any expectancy existed, and
  **unchanged after the §0.5 disclosure**.
- **Variant 2, permitted only on a pre-specified COUNTING failure:** OOS n < 30 (gate 2) or
  fewer than 3 evaluable grid cells (`sensitivity.py:187`). In that case, and only then, one
  re-run at the pre-registered fallback `release_min = 0.8` (one grid step, named here before
  any result is seen). **It may not be re-run because the point estimate disappointed.** The
  two cases are distinguished mechanically by the gate detail strings.
- **Stopping rule (binding):** if **K3a or K3b** fires at Stage A, **stop**. No third
  parameterisation, no `channel` change, no `contraction_max` loosening, no combination with
  the `risk_off` lever, no Stage B. Write §11.
- **No second universe.** If the result disappoints, this design does **not** propose N = 300,
  a different composition rule, a different liquidity statistic, or dropping symbols. Each
  would be universe selection after seeing results — the same offence as tuning on the sealed
  window — and each costs another look. The only permitted post-hoc symbol change is
  W1-COMPLETE's data-quality replacement from the pre-registered reserve list, applied
  **before** any backtest. (Grafted from universe_power §9.2; carries over unchanged.)
- **Grid points are not variants.** The 81-point grid is the mandated robustness test, run once
  inside the single evaluation. **No cell may be promoted to a shipped parameter.** Selecting a
  parameter set from grid results after the fact is exactly the offence R5 exists to prevent.
- **Hard stop at look 6 for this strategy family**, across **all** versions and **all**
  snapshots (§10). This closes the family-budget gap judge A14 identified.

**Multiple-testing honesty.** This is the first variant tried on this strategy. If it passes,
the pass is a 1-of-1 and its bootstrap CI carries no selection penalty beyond the
programme-level one already disclosed — with the §0.5 disclosure attached.

---

## 10. Sealed-look accounting

### 10.1 The §0.1 ledger, reproduced (FACT, `strategy_sealed_test`: 20 rows, 4 per version 2–6)

| Ver | Strategy | snap 1 `universe_25_baseline_legacy` | snap 2 `universe_25_baseline` | snap 3 `universe_24_ex_meta` | snap 4 `universe_25_meta_continuity_corrected` |
|---|---|---|---|---|---|
| 2 | `trend_continuation.short_swing` | id 1: +0.3246R / 112 ✅ | id 6: +0.3246R / 112 ✅ | id 11: +0.2982R / 109 ✅ | id 16: +0.3246R / 112 ✅ |
| 3 | `trend_continuation.medium_swing` | id 2: +0.0109R / 98 ✅ | id 7: +0.0109R / 98 ✅ | id 12: −0.0294R / 95 ❌ | id 17: +0.0109R / 98 ✅ |
| 4 | `mean_reversion.short_swing` | id 3: +0.1230R / 91 ✅ | id 8: +0.1230R / 91 ✅ | id 13: +0.1278R / 84 ✅ | id 18: +0.1230R / 91 ✅ |
| 5 | `relative_strength.medium_swing` | id 4: +0.2935R / 16 ✅ | id 9: +0.2935R / 16 ✅ | id 14: +0.2935R / 16 ✅ | id 19: +0.2935R / 16 ✅ |
| **6** | **`volatility_breakout.short_swing`** | **id 5: −0.0979R / 10 ❌** | **id 10: −0.0979R / 10 ❌** | **id 15: −0.0979R / 10 ❌** | **id 20: −0.0979R / 10 ❌** |

Sealed windows: snapshot 1 `2025-09-07 … 2026-09-07`; snapshots 2–4 `2025-09-08 … 2026-09-08`.
All four v6 draws are the **identical** 10 trades at −0.0979R; **DERIVED** (MAP §0.3)
SE = **0.491R**, so −0.0979R is **0.20 SE** from zero and carries no information about sign.
**No sealed number appears anywhere in §1–§9 of this document, and none may.**

### 10.2 What this design costs in looks

**Baseline k = 5 per strategy** (MAP §0.1, §4.2 item 10; the brief states the same).
**FACT** (`db/models/research.py:263`; `promotion.py:377-384`): a new `StrategyVersion` plus a
`dataset_snapshot_id` is a new pair, so `_get_or_create_sealed_test` computes a **fresh** sealed
test rather than replaying a locked one. There is no way to run `evaluate_promotion` without
creating it — gate 9 is not optional. **This is exactly why Stage A avoids
`evaluate_promotion`.**

| event | new sealed test? | look |
|---|---|---|
| four existing locked draws (ids 5, 10, 15, 20) | — | baseline **k = 5** |
| **Stage A** — read-only `run_strategy_over_universe` for v0.1.0 **and** v0.2.0 on the expanded snapshot, pre-sealed span only, plus the 81-cell grid and all diagnostics | **no** | **0 looks** |
| **Stage B** — one `evaluate_promotion` for **v0.2.0** on the expanded snapshot | yes | **look 6** |
| v0.1.0 through `evaluate_promotion` on the expanded snapshot | **NOT RUN** — rejected (§0.1(3)) | would have been a further look |
| v0.2.0 on snapshots 1–4 | **NOT RUN** — explicitly excluded (§10.3) | would have been up to four further looks |
| versions 2, 3, 5 on the expanded snapshot | **NOT RUN** | for v2 and v5 this is a **prohibition**, not a preference (R7b: a passing scope on a second snapshot makes `paper_probation.py:118`'s `scopes[0]` order-dependent; `approved_scopes` issues no `order_by`) |

**Total: k = 5 → 6. One look, for the whole strategy family, across all angles.**

**Convention ambiguity, flagged rather than silently resolved.** MAP **§0.1** says *"a v0.2.0
that seals against snapshot 3 is the **fifth** look"*; MAP **§4.2 item 10** says *"the baseline
count is k = 5 … so a first v0.2.0 sealing on snapshot 3 is **look 6**"*. The two differ by one.
**This document follows §4.2 item 10** and reports both readings wherever it matters. The
substantive fact — *four locked draws exist and this adds exactly one more* — is identical
either way, and it is that sentence, not the index, that belongs in the report. **Operator
question Q2 (§13).**

### 10.3 Which snapshot the report leads with (pre-registered per R1)

**The v0.2.0 report leads with the expanded snapshot, because it is the only snapshot on which
v0.2.0 is evaluated.** Reproduced alongside it, verbatim and in every table:

1. the §10.1 four-draw v0.1.0 ledger;
2. the statement that **snapshot 3 remains the headline for all v0.1.0 comparisons** — it is
   the only snapshot on which gate 8 passes for any version (MAP §0.1), a pre-sealed
   data-quality reason fixed before any result was seen;
3. the statement that the expanded snapshot is a **separate experiment**, never an update to
   the snapshot-3 numbers (MAP §3(a): 62.5% of snapshot 3 is ETFs by symbol and 74.4% by trade;
   the expanded universe is 90% single names by symbol and ≈ 16% ETF by trade);
4. the §7.2 disclosure that the universe is **survivorship-selected** even after the
   pre-sealed liquidity fix;
5. the §0.5 disclosure.

**v0.2.0 is deliberately NOT evaluated on snapshots 1–4.** Reasons, in order: (i) it would
create up to four more sealed tests for a version whose gate 9 there would have SE ≈ 0.35–0.40R
and no discriminating power; (ii) OOS n = 32 on snapshot 3 cannot test K3; (iii) the only use
of the resulting numbers would be re-parameterisation. **If the operator overrides this, each
run is an additional look and must be counted and disclosed.**

---

## 11. Null option

**The null option is the pre-registered likely outcome, not a fallback**, and Stage A is
designed so that reaching it costs **zero sealed looks**. It is written if **K3a or K3b fires
at Stage A**, if **K6** fires, or if **gate 4 fails at Stage B**.

Deliverable: `docs/research/designs/volatility_breakout.short_swing--does_not_pass.md`,
carrying:

1. **The structural finding, which stands regardless of outcome.** The same-bar squeeze/break
   conjunction selects break bars **37% smaller** than the typical break bar
   (−0.4201 ± 0.0161, **26.1 SE**), identically on all four snapshots (§3.1). A permanent,
   reusable result, and the honest answer to "was the rule ever given a fair chance?"
2. **The corrected cost arithmetic (§3.4, §8).** Modelled cost at v0.1.0's own OOS entries is
   **0.0548 ± 0.0036 R = 89% of the +0.0613R net edge**; gross pre-cost edge ≈ +0.116R; and at
   the mandated 2× spread the net OOS expectancy is **−0.0134R**, so **gate 3 fails on
   arithmetic alone**. Correction to MAP §0.4 either way.
3. **The required-n arithmetic (§5.4), with the clustered statistic alongside.** At the observed
   point estimate gate 4 needs **≈ 2,500–6,900 OOS trades** iid and **≈ 6,600–18,500** under
   entry-month clustering, against a database holding **26** ten-year `massive` symbols and
   `max_universe_size = 150`. **Gate 4 is not reachable by universe expansion at any feasible
   scale.** H11 stands.
4. **The gate-6 disclosure.** The bear-bucket zero has a hard calendar ceiling — **19 gate-open
   bear proxy sessions in nine years** — set by the inherited `not ctx.regime.risk_off`
   conjunct that v6 shares with the approved v2. The bear entry rate has never been measured
   (0 of 432, 1.72 SE). A bear bucket under 10 is a power outcome, pre-registered as
   uninformative, and the λ band runs 6.8 → 14.7 (P(≥10) 0.15 → 0.92).
5. **The gate-7 correction.** Gate 7 is a turnover gate as coded (`portfolio_metrics.py:109-111`),
   a −0.0512R configuration clears it, and MAP §3(a) / W1 §8 are both wrong on this code path.
   An open item for the operator whatever happens to this design.
6. **The fragility disclosures.** One month (2023-12, 7 of 51 trades) moves v0.1.0's OOS
   expectancy from +0.0613R to −0.2623R; two JPM trades move the single-name OOS mean from
   +0.3914R to +0.0072R.
7. **The universe-level leakage disclosure (§7.2)**, including the sealed-window selection
   defect that was found and fixed, and the survivorship exposure that could not be.
8. **The variant ledger (R5):** 1 of 1 (2 if the counting-failure retry fired), what it
   changed, why, and the §3 evidence that motivated it — plus the §0.5 disclosure.
9. **The look ledger (§10):** four locked draws, plus the one Stage B created (if it ran), with
   the convention ambiguity flagged.
10. **Disposition.** v0.1.0 stays **EXPERIMENTAL**; v0.2.0 stays EXPERIMENTAL. Neither is
    promoted, neither is deleted, no gate or threshold is touched, the cost model is unchanged.
    **Recommendation: stop.** With 1 of 1 mechanism variants failing and gate 4 unreachable, a
    third angle would be variant-hunting.

**And the symmetric case, so a pass cannot be quietly upgraded.** If v0.2.0 clears gates 1–9 at
Stage B, the deliverable is a promotion report with **five caveats in the headline**: the point
estimate moved ~3–5× on a distribution-shifted snapshot; it is a pass on **look 6**; gate 7's
contribution is a `√turnover` artefact predicted in advance; the **month-clustered** CI is
reported alongside the iid gate-4 CI, under which **v2 and v5 themselves would fail**; and the
approved scope **cannot be exercised by the 25-symbol live scan**, so R8's confirming test is
unavailable without a separate operating decision. **A pass that cannot be confirmed live is a
weaker outcome than the gate ladder alone suggests, and this document says so before the number
exists.**

---

## 12. Pre-registration block, implementation checklist and exact commands

Everything in §12 is fixed **before** any run and may not be altered afterwards.

### 12.1 Pre-registered, in one place

| Item | Pre-registration |
|---|---|
| **Gate-5 axes** | `contraction_max [0.65, 0.75, 0.85]` × `stop_atr [1.5, 1.75, 2.0]` × `squeeze_lag [3, 5, 10]` × `release_min [0.8, 1.0, 1.2]` = 81 points, 8 one-step neighbours, defaults at the centre of every axis. No axis removed, no threshold moved. |
| **Falsification, snapshots 1–4** | K1 (≥ 2 SE energy bias) **run, survived, 26.0–26.5 SE**. K2 (cost ≥ 2 SE) **run, NOT survived, 1.72 SE — withdrawn as evidence**. K2b (OOS n ≥ 30) **run, survived at 32/34/34/36**. |
| **Falsification, expanded snapshot (Stage A)** | **K3a:** `E₀₂ ≤ E₀₁` → stop. **K3b:** `E₀₂ − E₀₁ < 2.0` **clustered** SE (iid SE × 1.638) → stop; both forms reported, clustered binds. **K5:** any of the four axes fails to move OOS count or expectancy → run void. **K6:** operator declines A0, or < 120 symbols after W1-COMPLETE, or any §12.4 assertion fails → stop, no result read. |
| **Variant budget (whole strategy, all angles)** | **1**, hard cap **2**. Variant 2 only on a mechanical COUNTING failure (gate 2 n < 30, or `sensitivity.py:187`'s < 3 evaluable cells), at the named fallback `release_min = 0.8`. Never because the point estimate disappointed. |
| **Stopping rule** | K3a or K3b fires → stop, no Stage B, write §11. No second universe, no third parameterisation, no `channel`/`contraction_max`/`risk_off` change. Hard stop at **look 6** for the family across all versions and snapshots. |
| **Headline snapshot** | The expanded snapshot (the only one v0.2.0 is evaluated on), with snapshot 3 retained as the headline for all v0.1.0 comparisons and the §10.1 ledger, §7.2 survivorship disclosure and §0.5 disclosure reproduced alongside. |
| **Sealed-look accounting** | Baseline **k = 5**. Stage A adds **0**. Stage B adds exactly **1** → **k = 6**, "look 6" under MAP §4.2 item 10 (look 5 under §0.1; both reported). v0.1.0 not re-sealed anywhere; v0.2.0 not evaluated on snapshots 1–4; versions 2/3/5 not evaluated on the expanded snapshot. |
| **Gate-4 forecast** | Genuinely uncertain, P ≈ 0.5–0.65; both outcomes pre-registered; a PASS carries the five §11 caveats. |
| **Gate-7 forecast** | **PASS expected**, disclosed as a `√(trades/year)` artefact with the −0.0512R counter-example and the cluster-adjusted figure printed beside it. |
| **Gate-6 forecast** | bear λ ≈ 14.7 (band 6.8–14.7), P(≥10) = 0.15–0.92; a sub-10 bucket is a power outcome and motivates nothing. |

### 12.2 Files touched

| File | Change |
|---|---|
| `src/signalforge/research/strategies/breakout.py` | `VERSION` → `"0.2.0"`; `BreakoutParams` + `squeeze_lag: int = 5`, `release_min: float = 1.0`; `evaluate` per §2.3; `spec()` text; import `true_range` |
| `src/signalforge/research/promotion.py:199-208` | grid gains `squeeze_lag`, `release_min` |
| `src/signalforge/research/promotion.py:249-261` | `_leakage_self_check` gains 4 entries (§7.3) |
| `tests/` | new tests (§12.3) |
| **nothing else under `src/`** | — |
| `docs/research/designs/scripts/volatility_breakout_short_swing/` | **new** — the verification scripts, their raw stdout, and the backup/`pragma integrity_check` transcript (defect A15) |

### 12.3 Tests required

1. **Degenerate-identity test.** `VolatilityBreakout(SHORT_SWING, BreakoutParams(squeeze_lag=0,
   release_min=0.0))` produces **exactly** v0.1.0's signal set on a fixture series, **for every
   `t`** — guaranteed by the `release_min > 0.0` gate of §2.3. Assert set equality, not just
   counts.
2. **Lag test.** `squeeze_lag` shifts the contraction read: a series contrived so
   `contraction(t) > 0.75` but `contraction(t−5) ≤ 0.75` produces a signal at lag 5 and none at
   lag 0.
3. **Release test.** A break bar with `TR(t) = 0.9 × ATR(50, t−1)` is rejected at
   `release_min = 1.0` and accepted at `0.8`.
4. **Warm-up test.** No signal before `t = 55` at lag 5; no negative-index read (assert
   `atr_contraction(series, t − lag, 10, 50)` is NaN, not a wrapped value, for `t < lag + 50`).
5. **Leakage tests.** `assert_no_lookahead` over `atr_contraction(10,50)`, its `t−5` form,
   `donchian_high(20)` and `true_range` — the four functions added to `_leakage_self_check`.
6. **Grid-plumbing test.** `_sensitivity_plan` for the `volatility_breakout` prefix returns 4
   axes and 81 combinations, and `_replace(base, **p)` accepts both new keys.
7. **No-op guard test (K5 in unit form).** Each of the four axes changes the signal set or the
   exit behaviour on a fixture.

### 12.4 Pre-integration assertions — checked BEFORE any result is read

Failing any of these means **no result may be read at all** (K6c): a result read off the wrong
snapshot row is an unrecorded sealed look.

1. `StrategyPromotionEvaluation.dataset_snapshot_id` equals the keyed row's id.
2. No `universe_auto_150sym_*` row was minted (`promotion.py:339`; `scan.py:165` mints these on
   every live scan — always pass the key explicitly).
3. The key cannot be produced by either auto-generator (`universe_auto_*`,
   `liquid_us_<date>_<digest>`, `screen.py:259`) and matches no existing reusable snapshot's
   symbol set (rows 6, 8, 10 and any newer).
4. The new `StrategySealedTest.strategy_version_id` is the row **created by this run**
   (v0.2.0), not a replay of ids 5/10/15/20 — **this is MAP §4.3's staleness guard, and it is
   the single most likely way to produce an invalid pass**.
5. `data_provenance.sources == ["massive"]`. Omitting `source` loads `massive_grouped` too and
   duplicates every bar inside the sealed window.
6. **Spec-hash non-disturbance:** `approval_scope.current_spec_json_hash()` for versions **2**
   and **5** is byte-identical before and after registering v0.2.0, and
   `approved_scopes(v2)` / `approved_scopes(v5)` still return exactly one scope each, both on
   `dataset_snapshot_id = 3` → sealed tests **11** and **14** (R7, R7b; MAP §1 records these as
   the current state for exactly this comparison).
7. `strategy_sealed_test` row count is **20 before Stage A and still 20 after Stage A**
   (Stage A must create no sealed test), and **21 after Stage B**.
8. `PromotionThresholds` and `CostModel` are byte-identical to HEAD (R4).

### 12.5 The exact commands — Stage A (zero looks, zero DB rows, SCRATCH database)

```bash
cd /Users/louisbrailey/signal-forge
# 0. scratch copy; never touch the live DB
sqlite3 "file:data/signalforge.sqlite?mode=ro" ".backup $TMPDIR/scratch-v6impl.sqlite"
sqlite3 "$TMPDIR/scratch-v6impl.sqlite" "pragma integrity_check;"
export DATABASE_URL="sqlite+pysqlite:///$TMPDIR/scratch-v6impl.sqlite"

# 1. gates that do not need the DB at all
make secrets && make lint && make typecheck
.venv/bin/pytest tests/ -q                       # includes the §12.3 tests

# 2. Stage A evidence — read-only, no sealed test, no look
.venv/bin/python scripts/stage_a_v6.py \
    --snapshot-key research_150_massive_10y_presealed_sel \
    --source massive \
    --emit docs/research/designs/scripts/volatility_breakout_short_swing/stage_a.json
#    runs, for BOTH v0.1.0 and v0.2.0, over the PRE-SEALED span only:
#      run_strategy_over_universe            -> E01, E02, sds, per-class split, per-symbol counts
#      the 81-cell grid via research.sensitivity (K5 no-op check re-run)
#      gate-1 folds, gate-6 buckets + unbucketed count, gate-7 Sharpe identity
#      month-clustered bootstrap alongside the iid CI (half-width ratio = the ESS haircut)
#      leave-one-month-out and leave-one-symbol-out sweeps
#      the four spread re-pricings (16 / 26 / 31 / 66 bps)
#      the 135-new-symbols-only pre-sealed run (the only quasi-OOS universe evidence)
#    and NEVER calls evaluate_promotion, sensitivity's writing path, or any sealed entry point.

# 3. evaluate K3a / K3b / K5 from stage_a.json. If K3a or K3b fires -> STOP, write §11.
```

### 12.6 The exact commands — Stage B (one look; only after operator approval A2)

```bash
# Rehearse on the scratch copy FIRST, end to end, and diff the gate table.
export DATABASE_URL="sqlite+pysqlite:///$TMPDIR/scratch-v6impl.sqlite"
.venv/bin/python scripts/stage_b_v6.py --dry-run --assert-preintegration   # §12.4 items 1-8

# Live run: the ONLY command in this design that writes to data/signalforge.sqlite.
unset DATABASE_URL
.venv/bin/python scripts/stage_b_v6.py --confirm
#    one evaluate_promotion(session, VolatilityBreakout(Horizon.SHORT_SWING),
#        symbols=<the final 150>, source="massive",
#        dataset_snapshot=<the keyed row>)   # key passed explicitly, source never None
#    then re-asserts §12.4 items 1-8 and aborts the transaction if any fails.
```

**Worker/DB safety.** A live paper probation and a background worker run against
`data/signalforge.sqlite`. Stage B is a single short write transaction; per the project's
SQLite rules it must use a write-intent session, must not hold a transaction across any network
I/O, and must be run with the operator's knowledge. **Stage A never writes.**

### 12.7 Reporting outputs, mandatory with any outcome

1. ETF-only and single-name-only expectancies with SEs, against §3.3's baselines.
2. The 135-new-symbols-only pre-sealed run.
3. Gate 6's three buckets **and** the unbucketed count.
4. Month-clustered bootstrap CI beside the iid gate-4 CI, with the half-width ratio.
5. Leave-one-month-out and leave-one-symbol-out sweeps.
6. The four spread re-pricings (§8).
7. Gate 5's realised `evaluable` / `neighbours` denominators, not just the fractions (§6.2).
8. The §10.1 ledger, the "look 6" statement, the §0.5 disclosure and the §7.2 survivorship
   disclosure.
9. Per-symbol IS/OOS boundary dates (`_TRAIN_FRAC = 0.6` splits per symbol, so aggregated OOS
   mixes calendar sub-periods — worse at 150 symbols than at 24).

---

## 13. What the operator must approve, and what is reported if it fails

**Nothing in this document authorises anything.** Four approvals and two questions.

**A0 — BLOCKING, and new: re-derive W1-SEL on a pre-sealed liquidity window.**
> Approve re-running Rule W1-SEL(2) using the median of `close × volume` over the **60 most
> recent PRE-SEALED `massive_grouped` sessions, 2025-06-11 → 2025-09-05** (168 pre-sealed
> sessions exist; 2,312 symbols carry ≥ 55 of these 60), instead of 2026-06-12 → 2026-09-08;
> re-derive the rank order, the top-135 cut, the reserve list and the liquidity floor on that
> basis; and re-key the snapshot accordingly. W1-COMP (15 ETFs + 135 CS), the listing filter
> and W1-COMPLETE are unchanged. This uses **no new data and no API calls** and can only make
> the universe less hindsight-favoured.

*If declined:* gate 9's sealed test is contaminated by construction — the symbols were chosen
by how heavily they traded inside the year gate 9 measures. Reported outcome: the design
**terminates at Stage A**; Stage B is not run; §11 is written with the contamination stated as
the reason the sealed test was not purchased. Stage A's evidence is still produced and is still
valid, because it never touches the sealed window.

**A1 — the backfill (data only, unchanged from W1 §10.1).**
> Approve ~126 paced GETs to the Massive API (~25 min at `_MIN_REQUEST_SPACING_S = 12.1`) to
> ingest 10 years of daily bars for the new symbols, written with `source = "massive"`, one
> short commit per symbol.

*If declined:* no expanded snapshot exists; v0.2.0 cannot be evaluated at any useful power
(OOS n = 32 on snapshot 3, SE ≈ 0.19R). Reported outcome: §11 is written on the snapshot-3
evidence alone, carrying the 26-SE structural finding, the corrected cost arithmetic, the
required-n table and the §0.5 disclosure, with the explicit statement that **the design was
never tested**, not that it failed.

**A2 — Stage B: spend the sealed look and accept its irreversible side effect.**
> Approve, **after** reading Stage A's result, one `evaluate_promotion` for v0.2.0 on the keyed
> snapshot. Acknowledge that **FACT** (`promotion.py:922, 943-952`) a pass writes
> `PAPER_APPROVED` to both `Strategy` and `StrategyVersion` **unconditionally**, that
> **FACT** (`approval_scope.py:69-94`, `scan.py:165`) the resulting 150-symbol scope can never
> match the 25-symbol live scan so the pass buys **zero** confirming evidence under R8, and
> that prose disclosure written afterwards cannot undo the row. Acknowledge that this takes the
> family from **k = 5 to k = 6** and that **no further look will be taken for this strategy**.

*If declined:* Stage A's result is reported as a pre-sealed research finding with **no sealed
test**, k stays at 5, and the disposition is deferred. This is a legitimate and cheap ending.

**A3 — pre-register that a turnover-driven gate-7 pass is "not an approval".**
> Approve recording in advance that if the gate-7 margin is attributable to `√(trades/year)` —
> i.e. per-trade `mean/sd` is not improved by ≥ 2 SE over today's 0.1368 — the gate-7 pass
> contributes no independent evidence of edge quality, and the report says so in the headline.
> No threshold is touched (R4); this is disclosure only.

*If declined:* the gate-7 pass is reported with the §5.7 arithmetic attached anyway, since it
is a verified property of `portfolio_metrics.py:109-111` and reporting it is not optional.

**Q1 — fix the 2×/5× spread convention.** MAP §0.4 names 26 and 66 bps; W1 §7.1 reads "2×/5×"
as 16 and 31 bps. All four are reported until the operator picks one.

**Q2 — settle the look-index convention.** MAP §0.1 and §4.2 item 10 disagree by one about
whether a first v0.2.0 is look 5 or look 6. This document follows §4.2 item 10 and reports both.
Nine proposals write ledgers against the same baseline; they will not reconcile until this is
named.

**Q3 — gate 7's docstring contradicts its code** (`config/research.py:111-113` says OOS,
`promotion.py:775` computes all pre-sealed trades), **and its Sharpe convention rewards
turnover** (§5.7). Both are standing open items that this design discloses and does not touch.

---

*Design-phase output. Read-only in its production: no file under `src/` or `tests/` was
modified, no row in `data/signalforge.sqlite` was written, no promotion / sensitivity / sealed
entry point was invoked, no provider API was called, and no quantity inside the sealed window
was computed. The sealed-look count is unchanged at **k = 5** by the writing of this document.
One abstention held by the source proposal was broken in the course of settling a judge
dispute, and is disclosed in full at §0.5.*
