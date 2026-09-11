# Design proposal — `trend_continuation.medium_swing` v0.1.0 (version 3)
## Angle: EXITS & RISK

**Author:** independent proposer (design phase, angle 2 of 3).
**Target:** `STRATEGY_COMPLETION_MAP.md` §2.1, levers 3 and 4.
**Structure:** the eleven mandatory sections of `STRATEGY_COMPLETION_MAP.md` §4.2, in order.

---

## Verdict, stated before the argument

**This angle was chartered conditionally.** `STRATEGY_COMPLETION_MAP.md` §4.1 admits the
two v3 change proposals *"conditional on a W2 duration diagnostic that survives all four
snapshots"*, and §2.1 lever 2 is explicitly gated on *"only if a W2 diagnostic first
establishes a duration effect (H1) that holds on all four snapshots"*. My own brief
repeats the condition: *"conditional on the W2 duration/ATR diagnostics surviving all
four snapshots"*.

**FACT — the condition failed.** The two W2 diagnostics are in:

- `docs/research/diagnostics/v3_duration_exits.md` — **H1 and H2 FALSIFIED** on all four
  snapshots, on both the all-pre-sealed and OOS cuts.
- `docs/research/diagnostics/v3_atr_at_exit.md` — **H3 NOT SUPPORTED**, its own
  falsification criterion met, on all four snapshots.

**So the honest output of the exits-and-risk angle is a NO-CHANGE recommendation, and
this document argues it on the merits rather than by default.** To be a proposal and not
a shrug, it does three things a bare "the condition failed" note would not:

1. It contributes **new pre-sealed measurement** that no existing diagnostic covers —
   the MFE/MAE distributions of v3's trades — and uses them to put **hard arithmetic
   ceilings** on what each remaining exits-and-risk lever could possibly achieve
   (§3, items C–F). Two of the three levers are killed outright by those ceilings; the
   third is shown to have an admissible range that straddles zero by ±5 SE, i.e. it is
   a coin flip dressed as a design.
2. It **fully pre-registers** the one contingent variant (V-A) that a judge panel might
   still want run, with its exact diff, its gate-5 axes, its kill criteria and an
   explicit forecast that it fails them — so that if the operator overrules this
   recommendation, the variant is already registered and cannot be re-specified after
   seeing its result (R5).
3. It **escalates one real defect** found along the way — an engine risk-unit collapse
   worth 42–45% of v3's entire pre-sealed R — to the correct track (pipeline hardening /
   operator decision), and explains why it is *not* a v3 v0.2.0 lever.

**Sealed-look consequence of the primary recommendation: k stays at 5.** No new
`StrategyVersion`, therefore no new `StrategySealedTest`, therefore no sixth look (§10).

---

## §0. Method, provenance and safety

**FACT — everything numbered below is read-only and pre-sealed.** New numbers in this
document come from one in-process run of
`research.backtest_runner.run_strategy_over_universe`
(`/Users/louisbrailey/signal-forge/src/signalforge/research/backtest_runner.py:167-243`),
which contains no `session.add`, `session.flush` or `session.commit` — it is a pure read
path. It was executed against the **live** `data/signalforge.sqlite` through SQLAlchemy
reads only; no scratch copy was needed because no writing entry point was used. No file
under `src/` or `tests/` was modified, no provider API was called, no service restarted.

**FACT — no promotion evaluation was run and no `strategy_sealed_test` row was created.
The sealed-look count remains k = 5** (map §0.1, R2).

**FACT — the sealed window was never loaded.** Every run covers only
`[start, pre_sealed_end]` with `pre_sealed_end = sealed_start − 1 day`, exactly as
`promotion.py:557` computes it. Sealed windows are the locked
`strategy_sealed_test.window_start/window_end` values (ids 2, 7, 12, 17 for version 3;
1, 6, 11, 16 for version 2), re-queried read-only for this document.

| Snapshot | key | symbols | source filter | pre-sealed run span | sealed window (untouched) |
|---|---|---|---|---|---|
| 1 | `universe_25_baseline_legacy` | 25 (incl. `META`) | `massive` | 2016-09-10 → **2025-09-06** | 2025-09-07 → 2026-09-07 |
| 2 | `universe_25_baseline` | 25 (incl. `META`) | `massive` | 2016-09-10 → **2025-09-07** | 2025-09-08 → 2026-09-08 |
| 3 | `universe_24_ex_meta` | 24 (**no** META) | `massive` | 2016-09-10 → **2025-09-07** | 2025-09-08 → 2026-09-08 |
| 4 | `universe_25_meta_continuity_corrected` | 25 (`META_CONT`) | `["massive","continuity_bridge:1"]` | 2016-09-10 → **2025-09-07** | 2025-09-08 → 2026-09-08 |

Other call arguments match `promotion.py:585-594`: `proxy_symbol="SPY"`, default
`CostModel()` (0 commission / 3.0 bps slippage / half-spread on → **11.0 bps round trip**,
`engine.py:94,144`), `min_bars=60` (so `warmup = 30`), and **`allow_short` left at its
default `False`**.

**FACT — the reproduction is exact**, which is the control that this harness is the same
computation the gates ran:

| | snap 1 | snap 2 | snap 3 | snap 4 |
|---|---|---|---|---|
| v3 pre-sealed trades | 1,091 | 1,091 | **1,071** ✓ | 1,112 |
| v3 OOS n / expectancy | 326 / +0.2936R | 326 / +0.2936R | **319 / +0.3064R** ✓ | **336 / +0.3169R** ✓ |
| v2 pre-sealed trades | 1,190 | 1,190 | **1,169** ✓ | 1,216 |
| v2 OOS n / expectancy | 348 / +0.2609R | 348 / +0.2609R | **341 / +0.2648R** ✓ | 359 / +0.2724R |

(✓ = matches `gates_json` on evals 32/33 and the §2.1 quotation of eval 39.)

**FACT — measured per-trade sd, used for every SE below** (not map §0.3's inverted-CI
estimate, which it corroborates to 0.9%): v3 OOS sd = **1.7259** (snap 3), 1.7179
(snaps 1/2), 1.7219 (snap 4); v3 all-pre-sealed sd = **1.5839** (snap 3). SE = sd/√n.
Differences between two *paired* re-pricings of the same trade list use the **paired**
SE (sd of the per-trade difference / √n), which is the correct and much tighter figure.

**Convention.** Every claim is **FACT** (verified, with file:line or the computation that
produced it), **DERIVED** (arithmetic on FACTs, derivation shown), or **HYPOTHESIS**.
Per the rules of engagement, *a difference under 2 SE is not evidence* and is not
treated as one anywhere below.

---

## 1. Mechanism

### 1.1 The hypotheses this angle was built on are dead

`STRATEGY_COMPLETION_MAP.md` §2.1 demoted H1–H4 to "unmotivated until a diagnostic
supports them", and required any supporting diagnostic to hold **on all four snapshots**
(R10). The exits-and-risk angle owns H1, H2 and H3. All three are now settled against it:

| Hyp | Claim | Map's own falsification condition | Result | Source |
|---|---|---|---|---|
| **H1** | 40-bar leash holds through reversals the 10-bar version never sees | falsified if 11–40-bar buckets are net positive and comparable in per-bar R to 1–10 | **FALSIFIED, all 4 snapshots.** OOS per-bar R: 11–20 = +0.0394/+0.0409/+0.0438; 21–40 = +0.0393/+0.0393/+0.0401; 1–5 = **−0.035 to −0.042** | `v3_duration_exits.md` §5 |
| **H2** | 3.0×ATR target rarely reached inside 40 bars; time stop becomes modal | falsified if target hits dominate, or time-stop exits are non-negative on average | **FALSIFIED, all 4 snapshots, both limbs.** Target = 41.5% of exits at mean 10.9 bars; time stop = **0.75%** (8 of 1,071) at **+0.3493R ± 0.1716** | `v3_duration_exits.md` §2a, §5 |
| **H3** | ATR(14) at entry is a stale risk scale 40 bars later | falsified if ATR@exit/ATR@entry is tightly clustered near 1 | **NOT SUPPORTED, criterion met, all 4 snapshots.** median 1.0565 ± 0.0047, IQR [0.963, 1.137], 83.9% inside ±25%; v3−v2 median difference **+0.0012 ± 0.0062** (z = +0.19) | `v3_atr_at_exit.md` §1, §7 |

Under R10 none of H1, H2 or H3 may motivate a v0.2.0. The exits-and-risk angle therefore
has **no surviving inherited mechanism**.

### 1.2 The new hypothesis this proposal actually tests

Stated in the §2 form, and it is the *negative* of the usual design hypothesis:

> **H13 — exit-geometry local optimum.** `trend_continuation`'s shipped exit geometry
> (stop = 1.5×ATR(14), target = 3.0×ATR(14), leash = 40 bars) sits at a **local maximum**
> of pre-sealed out-of-sample expectancy along every exit-and-risk axis that can be
> measured without lookahead, and the maximum is deep enough that every admissible
> perturbation is either (i) arithmetically incapable of producing a ≥ 2 SE improvement,
> or (ii) has an admissible range that straddles zero by several SE. If H13 holds, the
> correct exits-and-risk design for v0.2.0 is *no exits-and-risk change*, and any
> perturbation that nonetheless produces a nice-looking number is selection.

**Why this should be true in markets, not just in the backtest.** The strategy is a
long-only continuation entry taken *after* a confirmed trend alignment and a volume
spike. Its entire realised edge is the right tail: **99.3% of gross positive exit-reason
P&L comes from target hits** (`v3_duration_exits.md` §5, +807.92R of +813.50R on snapshot
3), against a 57% stop bucket paying ≈ −1.04R apiece. A payoff shaped like that is a
lottery-ticket structure: it survives because a minority of entries run the full 2R and
pay for the majority that do not. Every classical "exits and risk" improvement —
trailing the stop up, arming a breakeven stop, taking profit earlier, tightening the
initial stop — is a **truncation of the right tail purchased with a reduction in the left
tail**. For a payoff whose expectancy lives entirely in the right tail, that trade is
priced against you unless the left tail is fatter than the geometry implies. §3 shows,
on nine years of pre-sealed data and on all four snapshots, that it is not: the stops
that a trailing rule would rescue mostly never went anywhere (median MFE of a stop-out is
**+0.47R**), while the winners that a trailing rule would clip all dug meaningfully
against the position before winning (**100%** of target exits have MAE ≤ 0; 37.5% dug
≥ 0.5R below entry).

That is the mechanism claim, and it is falsifiable: see §4.

### 1.3 The one real defect the angle found, and why it is not this proposal's change

> **H14 — entry-bar risk-unit collapse (engine, not strategy).** `engine.py:111` defines
> `risk_per_share = abs(entry_fill − sig.stop_price)`, where `entry_fill` is bar *t+1*'s
> **open** (`engine.py:109-110`) but `sig.stop_price` was fixed off bar *t*'s **close**
> (`trend_continuation.py:105`). When the entry bar gaps down toward the stop, the
> denominator of every R figure collapses, and the fixed 5.5 bps-per-side slippage becomes
> enormous *in R*. When the gap carries the open **through** the stop, `entry_fill` falls
> *below* `stop_price`, `abs()` silently flips the sign of the risk unit, and
> `_resolve_exit`'s entry-bar branch (`engine.py:167`, `px = sig.stop_price`, the
> optimistic branch that ignores the open) books the immediately-stopped trade as a
> **≈ +1R win**.

**FACT (new, this document, §3 item E).** This is not hypothetical and it is not small.
On snapshot 3, v3 has 106 trades exiting on the entry bar (9.9%), expectancy
**−0.7527R ± 0.0889**, total **−79.79R** = **44.7% of v3's entire pre-sealed +178.55R**.
**16 of them are gap-through-stop "wins"** totalling **+12.38R**. Worst single trade
**−6.13R**. Stable on all four snapshots (106/106/106/108 trades; −79.79/−79.79/−79.79/
−79.81R). It is **worse in the PAPER_APPROVED v2**: 118 trades, −0.8338R ± 0.1291,
−98.39R = **84.3%** of v2's +116.72R, with 18 gap-through-stop wins (+14.24R) and a worst
trade of **−12.38R**.

**Why H14 is out of scope for this proposal, on three independent grounds:**

1. **It cannot be fixed in the strategy without lookahead.** `evaluate(series, t, ctx)`
   sees only `series.head(t)` (`engine.py:102`); bar *t+1*'s open — the thing that
   collapses the risk unit — is by construction invisible. Any strategy-level veto of a
   gapped entry would read `series.open[t+1]` and fail
   `backtest/leakage.py:assert_no_lookahead`. Correctly so.
2. **It is not a v3 property.** It is present identically in v2 and is *proportionally
   larger* there. It therefore cannot explain any medium-swing/short-swing difference and
   cannot motivate a `medium_swing`-specific v0.2.0.
3. **Fixing it in `engine.py` reaches a live approval.** `engine.py` is shared by v2
   (PAPER_APPROVED, live-scoped) and v5. Changing `risk_per_share` or the entry-bar exit
   branch changes v2's gate evidence without changing its `spec_json_hash` — the exact
   silent-invalidation pattern R3/R7 exist to prevent, arriving from the engine side
   rather than the strategy side.

**Recommendation for H14: escalate, do not implement here.** It belongs with the
`pipeline_hardening_spec` track and needs an operator decision, because any fix
re-prices the evidence underpinning a live probation. §11 records this as the concrete
deliverable this angle produces.

---

## 2. Exact change — file, symbol, before → after

### 2.1 Primary recommendation: **no change**

| File | Symbol | Before | After |
|---|---|---|---|
| `src/signalforge/research/strategies/trend_continuation.py:17` | `VERSION` | `"0.1.0"` | **`"0.1.0"` (unchanged)** |
| `src/signalforge/research/strategies/trend_continuation.py:20-29` | `TrendParams` | `stop_atr=1.5, target_atr=3.0, time_stop_bars=10` | **unchanged** |
| `src/signalforge/research/strategies/trend_continuation.py:37-39` | horizon branch | `TrendParams(time_stop_bars=40) if horizon is MEDIUM_SWING else TrendParams()` | **unchanged** |
| `src/signalforge/research/strategies/trend_continuation.py:102-113` | `evaluate` long branch | `stop_price = close − 1.5·ATR(14)`, `target_price = close + 3.0·ATR(14)`, `time_stop_bars = 40` | **unchanged** |
| `src/signalforge/research/strategies/__init__.py:43-51` | `default_strategies()` | 6 entries | **unchanged** |
| `src/signalforge/research/promotion.py:178-187` | `_sensitivity_plan` trend grid | `sma_fast [15,20,25] × stop_atr [1.2,1.5,1.8]` | **unchanged** *(see §6 for the axis-declaration caveat)* |
| `src/signalforge/backtest/engine.py` | `run_backtest`, `_resolve_exit` | as shipped | **unchanged** — H14 escalated, not patched (§1.3) |

No `StrategyVersion` row is created. No sealed test is created. `git diff --stat` under
this recommendation touches **zero** files under `src/` or `tests/`; the only artefacts
are documents.

### 2.2 Contingent variant V-A, pre-registered in full (recommended **not** to run)

Registered here so that, if the judge panel or the operator overrules §2.1, the variant is
fixed *before* its result is seen and cannot be re-specified afterwards (R5). This is the
single strongest member of the exits-and-risk family on the §3 evidence — an
**ATR-refreshed, profit-armed trailing stop**, which is the concrete form of the map's
lever 3 ("an ATR-trailing stop after defined R progress").

`src/signalforge/research/strategies/trend_continuation.py`:

```
- VERSION = "0.1.0"
+ VERSION = "0.2.0"

  @dataclass(frozen=True, slots=True)
  class TrendParams:
      sma_fast: int = 20
      sma_slow: int = 50
      vol_window: int = 20
      vol_mult: float = 1.3
      atr_window: int = 14
      stop_atr: float = 1.5
      target_atr: float = 3.0
      time_stop_bars: int = 10
+     trail_arm_r: float = 1.0      # arm once open profit reaches this many R
+     trail_lock_r: float = 0.5     # then hold a stop this many R above entry
```

The engine has no trailing-stop concept: `EntrySignal` (`engine.py:29-41`) carries one
immutable `stop_price` and `_resolve_exit` (`engine.py:154-184`) never re-reads it. So
V-A **cannot** be expressed inside `trend_continuation.py` alone; it is a
**shared-surface change** and must be called out as one:

`src/signalforge/backtest/engine.py`:

```
  @dataclass(frozen=True, slots=True)
  class EntrySignal:
      direction: Direction
      stop_price: float
      time_stop_bars: int
      target_price: float | None = None
+     trail_arm_price: float | None = None   # None => today's behaviour, exactly
+     trail_stop_price: float | None = None
      reason: str = ""
```

and inside `_resolve_exit`'s loop, **before** the stop test, a strictly additive branch
that is inert when `trail_arm_price is None`:

```
+ armed = False
  for u in range(entry_idx, n):
      o, hi, lo = series.open[u], series.high[u], series.low[u]
+     eff_stop = sig.trail_stop_price if armed else sig.stop_price
+     if (not armed) and sig.trail_arm_price is not None and u > entry_idx:
+         if (sig.direction is Direction.LONG and hi >= sig.trail_arm_price) or \
+            (sig.direction is Direction.SHORT and lo <= sig.trail_arm_price):
+             armed = True   # takes effect from the NEXT bar, never same-bar
      ... existing stop / target / time-stop tests, reading eff_stop ...
```

Two properties of that sketch are load-bearing and must be asserted in tests:

- **`trail_arm_price is None` reproduces today's numbers bit-for-bit** — the pre-integration
  regression is `v2 pre-sealed n = 1,169 / OOS +0.2648R` and `v3 = 1,071 / +0.3064R` on
  snapshot 3, unchanged to the digit. Without this, V-A silently re-prices the live-approved
  v2 (§1.3 ground 3).
- **Arming takes effect from the *next* bar.** Arming and firing on the same bar would
  assume intra-bar ordering the daily series does not contain — a within-bar lookahead of
  exactly the kind `assert_no_lookahead` cannot see, because it inspects the signal
  function, not the exit resolver.

Registration and grid changes that must accompany V-A:
`__init__.py:43-51` gains a v0.2.0 instance; `promotion.py:178-187` gains the two new
axes (§6).

### 2.3 Contingent variant V-B: killed before it is written

Lever 3's other form — "time-stop redesign", i.e. changing `time_stop_bars` from 40 to
some other value. **DERIVED (§3 item D): arithmetically incapable of producing evidence.**
The 40-bar leash binds on 8 of 1,071 pre-sealed trades and **1 of 319 OOS trades**, on all
four snapshots. Even the physically unattainable ceiling — every time-stop trade instead
running to the full target — moves OOS expectancy by **+0.0071R = +0.07 SE**, and the
matching floor (every one taking a full stop) by **−0.02 SE**. Any change to
`time_stop_bars` above 40 is confined to that interval, on every snapshot. Changing it
*below* 40 moves toward v2 and is contradicted by the matched-pair result
(`v3_duration_exits.md` §4: **+0.18 to +0.20R ± 0.077 per affected trade**, 2.3–2.7 SE,
all four snapshots). **V-B is dropped and is not part of the variant budget (§9).**

---

## 3. Pre-sealed evidence, with standard errors

New in this document: items **C–F**. Items **A** and **B** restate the two W2 diagnostics
that closed the angle. All figures are pre-sealed; the sealed window contributed nothing
to any of them (R1).

### A. What the W2 diagnostics already established (all four snapshots)

| Finding | Estimate ± SE | Snapshot-stable? | Source |
|---|---|---|---|
| Longer leash, matched pair, per affected trade, all pre-sealed | **+0.1770R ± 0.0777** (snap 3; +0.1843/+0.2049 on 1-2/4) — **+2.3 to +2.7 SE** | yes | `v3_duration_exits.md` §4 |
| same, OOS only | +0.1029R ± 0.1386 (**+0.7 SE — not evidence**) | yes, same sign all four | ibid. |
| Time-stop exits | 8 of 1,071 (0.75%), **+0.3493R ± 0.1716** | identical set on all four | ibid. §2a |
| ATR@exit/ATR@entry, v3 − v2, median | **+0.0012 ± 0.0062** (+0.19 SE) | yes | `v3_atr_at_exit.md` §1 |
| Entry-time ATR(14)/ATR(50) tercile gradient (the only exogenous conditioner) | **+0.1374R ± 0.1209** (+1.14 SE) | yes, under 2 SE on all four | ibid. §6 |

### B. The gate-5 grid is itself pre-sealed evidence about the risk axis

**FACT** (`gates_json`, eval 33, gate 5 evidence blob — existing, no new run). All nine
grid points are OOS on snapshot 3's pre-sealed span:

| `sma_fast` | `stop_atr` | n | OOS expectancy | vs baseline |
|---|---|---|---|---|
| 15 | 1.2 | 319 | +0.0933 | −0.2131 |
| 15 | 1.5 | 309 | +0.2726 | −0.0338 |
| 15 | 1.8 | 296 | +0.2311 | −0.0753 |
| 20 | 1.2 | 330 | +0.1684 | −0.1380 |
| **20** | **1.5** | **319** | **+0.3064 (baseline)** | — |
| 20 | 1.8 | 303 | +0.2523 | **−0.0541** |
| 25 | 1.2 | 336 | +0.1275 | −0.1789 |
| 25 | 1.5 | 324 | +0.2848 | −0.0216 |
| 25 | 1.8 | 306 | +0.2392 | −0.0672 |

**DERIVED — two readings, and both matter.**

- *Against the risk-geometry lever (map lever 4):* **all eight non-baseline cells are
  below the baseline**, and the two `stop_atr` neighbours at the shipped `sma_fast` are
  −0.1380R (tighter) and −0.0541R (wider). These are heavily overlapping samples, so a
  naive independent SE overstates the uncertainty; the point estimates are the decidable
  part, and they say **there is no free improvement along `stop_atr`** in the measured
  neighbourhood. Nothing here motivates re-scaling the risk unit.
- *As a caveat, HYPOTHESIS, which cuts against v3 rather than for it:* the shipped
  parameters sitting at the **maximum** of a 9-point OOS grid is the pattern one expects
  if those parameters were chosen on this data. It is a reason to treat v3's OOS
  +0.3064R as somewhat selection-inflated, and it is consistent with map §0.3's finding
  that the sealed year came in 1.65–1.88 σ below the pre-sealed mean. It is **not** a
  reason to change anything (that would be selecting again); it is a reason to write the
  caveat into the final report (§11).

### C. NEW — MFE and MAE distributions (this is what no diagnostic had measured)

**FACT**, v3, all pre-sealed trades, by exit reason. MFE/MAE are `SimTrade.mfe_r/mae_r`
(`engine.py:119-126`), i.e. peak favourable / adverse excursion over the holding window,
in units of the trade's own risk unit.

| Snap | reason | n | MFE median | MFE p75 | MFE p90 | MFE max |
|---|---|---|---|---|---|---|
| 1 | stop | 621 | **+0.472** | +0.967 | +1.702 | +58.09 |
| 1 | target | 456 | +1.865 | +2.436 | +3.376 | +11.68 |
| **3** | **stop** | **612** | **+0.471** | **+0.966** | **+1.672** | **+58.09** |
| **3** | **target** | **445** | **+1.857** | **+2.425** | **+3.379** | **+11.68** |
| 3 | time_stop | 8 | +1.054 | +1.188 | +1.439 | +1.83 |
| 3 | eod | 6 | +1.553 | +1.688 | +1.853 | +1.99 |
| 4 | stop | 634 | +0.466 | +0.963 | +1.666 | +58.09 |
| 4 | target | 464 | +1.876 | +2.437 | +3.382 | +11.68 |

MAE of target exits (how deep the winners dig before winning):

| Snap | n targets | MAE p10 | MAE p25 | MAE median | share MAE ≤ 0 | share MAE ≤ −0.5R |
|---|---|---|---|---|---|---|
| 1 | 456 | −0.833 | −0.641 | −0.379 | **100.0%** | 36.8% |
| **3** | **445** | **−0.834** | **−0.646** | **−0.383** | **100.0%** | **37.5%** |
| 4 | 464 | −0.835 | −0.646 | −0.383 | **100.0%** | 37.3% |

**Share of stop-outs that ever showed a profit of at least aR** — the population any
trailing/breakeven rule could rescue:

| Snap | cut | stops | MFE ≥ 0.5R | MFE ≥ 1.0R | MFE ≥ 1.5R | MFE ≥ 2.0R |
|---|---|---|---|---|---|---|
| 1 | all | 621 | 48.5% | 23.5% | 11.4% | 6.3% |
| **3** | **all** | **612** | **48.4%** | **23.4%** | **11.3%** | **6.0%** |
| 4 | all | 634 | 48.1% | 23.2% | 11.2% | 6.2% |
| 1 | OOS | 180 | 53.3% | 20.0% | 10.0% | 7.2% |
| **3** | **OOS** | **175** | **52.6%** | **19.4%** | **9.7%** | **6.9%** |
| 4 | OOS | 183 | 53.0% | 20.2% | 10.4% | 7.7% |

Robustness (snapshot 3, all pre-sealed): dropping the entry-bar bucket and the
risk-unit-collapse tail barely moves it — stops with `bars_held ≥ 1`: median MFE +0.503,
23.5% ≥ 1.0R; `bars_held ≥ 1` **and** MFE < 3: median +0.496, 22.9% ≥ 1.0R.

**DERIVED, and it is the core of H13:** the median stop-out never got past **+0.47R**, and
three-quarters of them never reached +1R — so a rule that arms at +1R can touch at most
**23%** of the loss bucket. Meanwhile **every single** winner traded below its entry at
some point and 37.5% dug ≥ 0.5R against the position, so the same armed stop is exposed
to essentially the whole win bucket. That is the asymmetry that makes the family
unattractive *a priori*, before any counterfactual is run.

### D. NEW — the time-stop ceiling (kills V-B)

**DERIVED.** Every trade that a change to `time_stop_bars > 40` can possibly touch is a
current `time_stop` exit. Holding the trade set fixed and re-pricing those trades at the
best and worst conceivable outcomes:

| Snap | cut | n | time-stops | current R | base ± SE | ceiling (all → +2.0R) | floor (all → −1.0R) |
|---|---|---|---|---|---|---|---|
| 1 | all | 1,091 | 8 (0.73%) | +2.79 | +0.1738 ± 0.0480 | +0.1859 (**+0.25 SE**) | +0.1639 (−0.21 SE) |
| **3** | **all** | **1,071** | **8 (0.75%)** | **+2.79** | **+0.1667 ± 0.0484** | **+0.1790 (+0.25 SE)** | **+0.1566 (−0.21 SE)** |
| 4 | all | 1,112 | 8 (0.72%) | +2.79 | +0.1704 ± 0.0478 | +0.1823 (+0.25 SE) | +0.1607 (−0.20 SE) |
| 1 | OOS | 326 | 1 (0.31%) | −0.27 | +0.2936 ± 0.0951 | +0.3005 (**+0.07 SE**) | +0.2913 (−0.02 SE) |
| **3** | **OOS** | **319** | **1 (0.31%)** | **−0.27** | **+0.3064 ± 0.0966** | **+0.3135 (+0.07 SE)** | **+0.3041 (−0.02 SE)** |
| 4 | OOS | 336 | 1 (0.30%) | −0.27 | +0.3169 ± 0.0939 | +0.3236 (+0.07 SE) | +0.3147 (−0.02 SE) |

The gate-3/gate-4 trade set is OOS. **A lever whose entire attainable range is ±0.07 SE
on the deciding trade set cannot produce evidence at a 2 SE bar, on any snapshot.** V-B is
dead on arithmetic, not on taste.

### E. NEW — the entry-bar risk-unit artefact, quantified and snapshot-stable (H14)

**FACT.** `bars_held == 0` trades, all pre-sealed:

| | n | share | expectancy ± SE | total R | as % of that version's total R | gap-through-stop "wins" | worst trade |
|---|---|---|---|---|---|---|---|
| v3 snap 1 | 106 | 9.7% | −0.7527 ± 0.0889 | −79.79 | **−42.1%** | 16 (+12.38R) | −6.13R |
| **v3 snap 3** | **106** | **9.9%** | **−0.7527 ± 0.0889** | **−79.79** | **−44.7%** | **16 (+12.38R)** | **−6.13R** |
| v3 snap 4 | 108 | 9.7% | −0.7390 ± 0.0887 | −79.81 | −42.1% | 17 (+13.37R) | −6.13R |
| v2 snap 3 (**live-approved**) | 118 | 10.1% | −0.8338 ± 0.1291 | −98.39 | **−84.3%** | 18 (+14.24R) | **−12.38R** |

"gap-through-stop wins" = entry-bar `stop` exits with **positive** `pnl_r`, which is only
possible when `entry_fill < stop_price` inverts the risk unit (§1.3). The MFE max of
+58.09 in item C is the same artefact seen from the other side. This is the single
largest identifiable distortion in the family's evidence base, it is stable on all four
snapshots, and it is **larger in the strategy that is live**.

### F. NEW — headroom bounds for the trailing/breakeven family (V-A)

MFE and MAE do not determine the *order* of excursions within a trade, so a trailing rule's
realised effect is path-dependent and cannot be computed exactly from them. What *can* be
computed is a rigorous bracket for the rule "arm once open profit reaches +aR, then hold a
stop at +bR":

- **BEST case** — every stop-out with MFE ≥ a is rescued at exactly +b, and **no** winner
  is ever clipped. Unattainable by construction (item C: 100% of winners have MAE ≤ 0), but
  a true upper bound.
- **WORST case** — additionally every non-stop trade with MFE ≥ a **and** MAE ≤ b is cut to
  +b. A true lower bound.

**FACT/DERIVED**, v3, five representative cells:

| Snap | cut | n | base ± SE | (a, b) | BEST | WORST |
|---|---|---|---|---|---|---|
| 3 | all | 1,071 | +0.1667 ± 0.0484 | (1.0, 0.0) | +0.3054 (**+2.87 SE**) | −0.4400 (−12.54 SE) |
| 3 | all | 1,071 | | (1.0, 0.5) | +0.3722 (+4.25 SE) | −0.1786 (−7.13 SE) |
| 3 | all | 1,071 | | (1.5, 0.75) | +0.2772 (+2.28 SE) | −0.1447 (−6.43 SE) |
| 3 | all | 1,071 | | (2.0, 1.0) | +0.2328 (+1.37 SE) | −0.0451 (−4.38 SE) |
| **3** | **OOS** | **319** | **+0.3064 ± 0.0966** | **(1.0, 0.0)** | **+0.4190 (+1.17 SE)** | **−0.4350 (−7.67 SE)** |
| **3** | **OOS** | **319** | | **(1.0, 0.5)** | **+0.4723 (+1.72 SE)** | **−0.1780 (−5.01 SE)** |
| 3 | OOS | 319 | | (1.5, 0.75) | +0.4018 (+0.99 SE) | −0.1131 (−4.34 SE) |
| 3 | OOS | 319 | | (2.0, 1.0) | +0.3891 (+0.86 SE) | +0.0099 (−3.07 SE) |

Snapshots 1/2 and 4 agree cell-for-cell to within 0.02R and 0.2 SE (OOS (1.0, 0.5):
+1.81 SE / +1.82 SE best, −4.95 SE / −5.16 SE worst).

**DERIVED — two conclusions, and the second is the important one.**

1. On the **deciding trade set (OOS)**, the *unattainable best case* of the whole family
   reaches at most **+1.72 to +1.82 SE**, on every snapshot. Under the program's own
   evidence bar (a difference under 2 SE is not evidence), **no member of this family can
   produce evidence on the current OOS sample even if every path resolves in its favour.**
2. The admissible range for the strongest cell is **[−5.01 SE, +1.72 SE]** on snapshot 3
   OOS. A design whose bracket is that wide is not a design; running it is a coin flip
   whose result would be interpreted as a finding.

*(The formal supremum of the bracket, taken over a → 0 with b = a, is +5.7 SE OOS — but
that limit describes a 0.05R trailing stop that rescues every loser and clips no winner,
which item C shows is impossible. It is reported for completeness and is not used.)*

### G. NEW — the exact tighter-target counterfactual (closes the "target scaled to the horizon" lever)

Unlike a trailing stop, a **fixed** target at +xR can be re-priced *exactly* from realised
paths, because a trade reaches it iff MFE ≥ x. (Two approximations, both stated: the trade
*set* is held fixed — an earlier exit would let the engine re-enter sooner — and intra-bar
ordering on the exit bar is assumed. Neither can change a sign at these magnitudes.)
Differences use the **paired** SE.

**FACT**, v3 snapshot 3:

| Target | all pre-sealed (n = 1,071, base +0.1667) | OOS (n = 319, base +0.3064) |
|---|---|---|
| 0.50R | +0.0406, Δ **−0.1261 ± 0.0419** (−3.01 SE) | +0.1080, Δ **−0.1984 ± 0.0862** (−2.30 SE) |
| 0.75R | +0.0887, Δ −0.0780 ± 0.0393 (−1.99 SE) | +0.1515, Δ −0.1549 ± 0.0808 (−1.92 SE) |
| 1.00R | +0.0865, Δ **−0.0802 ± 0.0353** (−2.27 SE) | +0.0880, Δ **−0.2183 ± 0.0701** (−3.11 SE) |
| 1.25R | +0.1209, Δ −0.0458 ± 0.0323 (−1.42 SE) | +0.1387, Δ **−0.1677 ± 0.0647** (−2.59 SE) |
| 1.50R | +0.1346, Δ −0.0321 ± 0.0287 (−1.12 SE) | +0.1780, Δ **−0.1284 ± 0.0597** (−2.15 SE) |
| 1.75R | +0.1691, Δ +0.0024 ± 0.0269 (+0.09 SE) | +0.2265, Δ −0.0798 ± 0.0567 (−1.41 SE) |
| 2.00R (≈ incumbent) | +0.1659, Δ −0.0008 ± 0.0242 (−0.03 SE) | +0.2638, Δ −0.0426 ± 0.0543 (−0.78 SE) |

All four snapshots, OOS:

| Target | snap 1 | snap 3 | snap 4 |
|---|---|---|---|
| 1.00R | +0.0891 (Δ −0.2045, **−2.95 SE**) | +0.0880 (Δ −0.2183, **−3.11 SE**) | +0.1013 (Δ −0.2155, **−3.15 SE**) |
| 1.25R | +0.1418 (Δ −0.1518, **−2.37 SE**) | +0.1387 (Δ −0.1677, **−2.59 SE**) | +0.1576 (Δ −0.1593, **−2.51 SE**) |
| 1.50R | +0.1754 (Δ −0.1182, **−2.00 SE**) | +0.1780 (Δ −0.1284, **−2.15 SE**) | +0.1955 (Δ −0.1214, **−2.08 SE**) |

Excluding the entry-bar bucket entirely (so the H14 artefact cannot be driving it), OOS:
snap 1 base +0.4093 → x = 1.0R gives −0.2549 (−3.36 SE); snap 3 base +0.4266 → −0.2718
(−3.53 SE); snap 4 base +0.4315 → −0.2656 (−3.56 SE).

**DERIVED.** Taking profit earlier is worse, monotonically, at every level tested, on
every snapshot, on both cuts, with and without the artefact bucket — and it is worse at
≥ 2 SE across the whole 1.0R–1.5R band that a "horizon-appropriate" target would occupy.
This is the same directional bet a trailing stop makes, measured exactly rather than
bracketed. **Map lever 3's "target scaled to the holding horizon" is closed.**

### 3.1 Summary: every exits-and-risk axis, measured

| Lever (map §2.1) | Axis | Best available pre-sealed OOS evidence | Verdict |
|---|---|---|---|
| 3 — time-stop redesign | `time_stop_bars` ↑ | attainable range **±0.07 SE** (item D) | **closed — cannot produce evidence** |
| 3 — time-stop redesign | `time_stop_bars` ↓ | matched pair **−0.18R ± 0.078** per affected trade (item A) | **closed — wrong direction** |
| 3 — ATR-refreshed stop | ATR@exit/@entry | v3 − v2 median **+0.0012 ± 0.0062** (item A) | **closed — nothing to refresh** |
| 3 — trailing stop | `(trail_arm_r, trail_lock_r)` | bracket **[−5.01, +1.72] SE** OOS; best case under 2 SE (item F) | **not runnable as evidence** |
| 3 — target to horizon | `target_atr` ↓ | **−2.0 to −3.2 SE** OOS on all four snapshots (item G) | **closed — measurably worse** |
| 4 — risk geometry | `stop_atr` | all 8 non-baseline grid cells below baseline (item B) | **closed — no free improvement** |
| — (new, H14) | engine risk unit | −79.79R = 44.7% of v3's total R; **worse in live v2** (item E) | **escalate, not a v3 lever** |

**H13 is supported on every axis that can be measured.** No exits-and-risk change to
`trend_continuation.medium_swing` is admissible on pre-sealed evidence.

---

## 4. Falsification — stated in advance, and across all four snapshots

The primary recommendation is "make no exits-and-risk change". Its falsification condition
is therefore the observation that would **re-open** the angle. Pre-registered here, before
any further run:

**F1 — the trailing family becomes runnable.** The exits-and-risk angle re-opens if a
*future, better-powered* pre-sealed OOS sample (e.g. the W1 150-symbol snapshot,
`w1_universe_preregistration.md`) shows the item-F **BEST case** for the (1.0, 0.5) cell
clearing **+2 SE on all four of that snapshot's cuts**. On today's data it reaches
+1.17 to +1.82 SE and therefore does not. Note the required move is in the *bound*, not
in a realised result: a bound below 2 SE cannot be rescued by a favourable realisation.

**F2 — the target lever reverses.** Re-opens if the exact tighter-target re-pricing
(item G) shows **any** target level in [0.75R, 1.75R] beating the incumbent by ≥ 2 SE
(paired) on OOS, **on all four snapshots**. Today every level in that band is *worse*, and
three of the five are worse at ≥ 2 SE on all four. A result on one snapshot only is a
META/composition artefact and does not re-open it (R10).

**F3 — the time stop starts to bind.** Re-opens if, on any dataset, the share of v3
pre-sealed trades exiting on `time_stop` exceeds **5%** (today 0.72–0.75%), which is the
point at which item D's ±0.07 SE ceiling stops being decisive.

**F4 — the risk axis develops a gradient.** Re-opens if a gate-5 grid on a
better-powered snapshot shows `stop_atr = 1.8` (or 1.2) beating `1.5` by ≥ 2 SE on OOS
on all four snapshots. Today all eight non-baseline cells are below baseline on snapshot 3.

**And the condition that would falsify H13 itself:** any exits-and-risk perturbation whose
*bracket* (not point estimate) lies entirely above the incumbent by ≥ 2 SE on OOS on all
four snapshots. None of the seven axes in §3.1 does.

**Symmetric commitment (R5).** If V-A is run against this recommendation and returns a
favourable point estimate inside the [−5.01, +1.72] SE bracket, that is **not** a
falsification of H13 and must not be reported as a finding — it is a draw from a bracket
that was pre-registered as uninformative. This sentence exists so that the interpretation
is fixed before the number is seen.

---

## 5. Gate-by-gate forecast, with trade sets

### 5.1 Primary recommendation (no change) — snapshot 3, all gates as evaluated at eval 33

Every number is the **already-recorded** value; a no-change proposal predicts them exactly,
which makes this forecast unusually easy to falsify (any deviation means something else
changed, e.g. `git_sha` or ingested data).

| # | Gate | Trade set | Forecast | Risk introduced |
|---|---|---|---|---|
| 1 | `rolling_walkforward` | **all pre-sealed (1,071)** | 4 of 4 folds clear (+0.1822/310, +0.0772/323, +0.0343/179, +0.3513/259); threshold 2 of 4 with n ≥ 15 | none |
| 2 | `min_oos_trades` | **OOS (319)** | 319 ≥ 30 | none |
| 3 | `net_expectancy` | **OOS (319)** | **+0.3064R** > 0 | none |
| 4 | `bootstrap_ci` | **OOS (319)** | CI low **+0.1205R** > +0.02. **Required n at this point estimate = 140** (sd 1.7259, `n > (1.96·1.7259/(0.3064−0.02))²`); has 319. Snap 1: required 152, has 326. Snap 4: required 130, has 336 | none |
| 5 | `parameter_sensitivity` | OOS per grid cell | 9/9 evaluable, 100% positive, 100% neighbours; worst cell +0.0933; every cell n ≥ 296 against the 15-trade floor | none — **but see §6**, the grid still covers 2 of 8 params |
| 6 | `regime_coverage` | **all pre-sealed (1,071)** | bull **857** / bear **22** / range **69**, all ≥ 10; **unbucketed = 123 (11.5%)** — trades entered inside `label_regimes`' 200-session warmup (map §0.6). Nearest margin: **bear 22 vs floor 10** | none |
| 7 | `benchmark_comparison` | **all pre-sealed (1,071)** — note the code reads `full.trades`, not OOS, contradicting its docstring (map §0.2) | Sharpe **1.156** vs SPY **0.719** | none |
| 8 | `data_quality_and_leakage` | — | pass **on snapshot 3 only**; fails on 1, 2 and 4 for every version (map §0.1) | none |
| 9 | `sealed_final_test` | sealed year | **replayed, not recomputed.** `_get_or_create_sealed_test` (promotion.py:377-384) returns the locked row: id 12, **−0.0294R / 95 trades, passed = 0** on snapshot 3; ids 2/7/17 return **+0.0109R / 98, passed = 1** on snapshots 1/2/4 | **the only failing gate, and it does not move** |
| 10 | `live_paper_probation` | — | `health_monitor.enabled` → pass | none |

**Zero-margin cases required by §4.2 item 5.** The two named cases —
`volatility_breakout`'s gate-5 neighbour fraction (0.750 on snapshot 3, **already 0.500 on
snapshot 4**) and `relative_strength`'s bear bucket (11 against a floor of 10) — belong to
versions 6 and 5. A no-change proposal touches neither: no `_sensitivity_plan` entry is
edited, no `StrategyVersion` row is created, no `approval_scope` row is added, so
`scopes[0].dataset_snapshot_id` (R7b) is undisturbed for both live strategies and
`current_spec_json_hash()` for v2 and v5 is unchanged by construction. v3's own smallest
margin is gate 6's bear bucket at **22 against a floor of 10**; a change that cut trade
count by more than **55%** would breach it, which is one more reason the no-change option
carries no gate risk.

**Net forecast: 9 of 10 gates pass on snapshot 3, gate 9 fails there and passes on the
other three, and the verdict string is unchanged.** This proposal does not claim to make
v3 pass. It claims that no exits-and-risk change can make it pass on evidence, which is a
different and — on §3 — better-supported claim.

### 5.2 Contingent variant V-A, if the operator overrules §2.1

Forecast per §4.2 item 5, stated **before** any run so it can be scored:

| # | Gate | Trade set | Forecast | At risk? |
|---|---|---|---|---|
| 1 | walkforward | all pre-sealed | still ≥ 2 of 4; per-fold n falls ~0–10% (earlier exits → earlier re-entries, bounded above by v2's +9.2% trade count at a far more aggressive truncation). Fold n today 310/323/179/259, all far above the 15 floor **which is `sensitivity_min_grid_trades` — moving it would move gate 1 too (map §4.3)** | low |
| 2 | OOS trades | OOS | 319 → ~320–350; ≥ 30 comfortably | no |
| 3 | net expectancy | OOS | **bracket [−0.1780, +0.4723]**; point unknown. Sign not predictable | **YES — could fail outright** |
| 4 | bootstrap CI | OOS | **required n**: at the best-case +0.4723 → n > **56**; at +0.30 → **140**; at the (1.5,0.75) best case +0.4018 → **80**; at any point estimate ≤ +0.02 → **never**. With ~330 OOS trades the gate passes iff the realised point estimate exceeds ≈ **+0.21R** | **YES** |
| 5 | sensitivity | OOS per cell | **must be re-planned** — see §6. With four axes the grid is no longer 3×3; the pre-registered choice is to *replace* one incumbent axis, keeping 9 cells and the 15-trade floor | **YES — silent no-op risk** |
| 6 | regime | all pre-sealed | bull/bear/range roughly proportional to the ~0–10% trade-count change: bull ~857–940, **bear ~22–24**, range ~69–76; **unbucketed ~123–135 (≈11.5%)**. Bear stays above 10 unless trade count falls > 55% | low, but bear is the binding bucket |
| 7 | benchmark | **all pre-sealed** (not OOS — map §0.2) | Sharpe 1.156 vs SPY 0.719 today. A trailing rule compresses per-trade R *and* per-trade variance; the ratio's direction is genuinely unpredictable, and gate 7's margin (+0.437) is the second-largest in the ladder | medium |
| 8 | data/leakage | — | pass, **provided** the engine change is inert when `trail_arm_price is None` and arming never fires same-bar (§2.2) | **YES if the engine sketch is implemented carelessly** |
| 9 | sealed | sealed year | **a brand-new draw — look 6** (§10). No forecast is offered: forecasting it would be reasoning about the sealed window | n/a |

---

## 6. Sensitivity-grid plan, and the no-op check

### 6.1 Under the primary recommendation

No parameter is introduced or changed, so §4.2 item 6's "every new or changed parameter
becomes a pre-registered gate-5 axis" has nothing to bind on. The grid stays
`sma_fast [15,20,25] × stop_atr [1.2,1.5,1.8]` (`promotion.py:187`).

**But the standing defect is restated, because a no-change proposal must not be read as an
endorsement of the grid.** Gate 5 covers **2 of 8** `TrendParams` fields and **excludes
`time_stop_bars`** — the only field that distinguishes v3 from v2 (map §0.5). v3's
"9/9 positive, 100% neighbours" therefore certifies robustness in a slice that omits the
strategy's defining parameter. `v3_duration_exits.md` §6c confirms the axis is live and
would be a genuine test (10 → 40 moves trade count ~8%, target share ~17 pp, total R
+53 to +70R).

**Recommendation, and why this proposal does not act on it.** Adding `time_stop_bars` as
an axis is permitted under R4 (it makes the gate more searching, never weaker) and would
be a real improvement. It is nevertheless **out of scope here** for a mechanical reason
established by `pipeline_hardening_spec.md`: the axis-declaration mechanism must live
**off** `StrategySpec`, because putting it on the spec changes `spec_json_hash` and
"would permanently break both live approvals". Re-pointing `_sensitivity_plan` for the
`trend_continuation` prefix would also re-plan gate 5 for the **live-approved v2**, whose
last passing evaluation (eval 32) recorded the current grid. That is a cross-cutting
promotion-path change requiring operator sign-off, not a strategy-angle deliverable. It is
carried into §11 as a recommendation, addressed to the hardening track.

### 6.2 Under V-A (pre-registered before any result)

V-A introduces two parameters, so both **must** become axes. Keeping 9 cells (so the
15-trade floor and gate 1's shared constant behave as today), the pre-registered grid
**replaces** `sma_fast` — the axis with the least bearing on an exits change — and keeps
`stop_atr`, which interacts directly with a trailing rule:

```
  "trend_continuation": {                         # promotion.py:178-187
-     "sma_fast":  [15, 20, 25],
-     "stop_atr":  [1.2, 1.5, 1.8],
+     "trail_arm_r":  [0.75, 1.0, 1.25],          # baseline 1.0
+     "trail_lock_r": [0.25, 0.5, 0.75],          # baseline 0.5
  }
```

pre-registered **before** any V-A result is seen, and applied **only** to the v0.2.0 key
(`trend_continuation.medium_swing` at version 0.2.0), never to the prefix — otherwise it
re-plans gate 5 for the live-approved v2.

**Mandatory no-op check (§4.2 item 6), and it is not a formality here.** The silent
failure mode is a retained-but-unused field: `_replace` succeeds, all 9 cells return
identical results, `positive_fraction` and `neighbour_positive_fraction` both come back
1.0, and gate 5 passes at 100% having tested nothing — the
`len(evaluable) >= 4 and len(positive) <= 1` guard (`sensitivity.py:199`) does not catch
it. A *renamed* field is safe by comparison: `promotion.py:50` imports
`replace as _replace`, and an unknown keyword raises `TypeError` loudly.

Pre-integration assertion, to be run and recorded before any V-A evaluation:

> For each of the 9 cells, the OOS **trade count** or **expectancy** must differ from the
> baseline cell. Concretely: at least **7 of 9** cells must differ from the baseline in
> `oos_expectancy_r` by more than 1e-6, and **no two** cells may be byte-identical in
> `(n_trades, oos_expectancy_r)`. If they are identical, the engine's `trail_arm_price`
> plumbing is not wired through `EntrySignal` and the run is void.

V-A carries a **second**, sharper no-op risk that the map does not yet name: because the
trailing branch is inert when `trail_arm_price is None`, a v0.2.0 that forgets to *emit*
those fields from `evaluate()` produces a strategy that is byte-identical to v0.1.0 while
carrying a new `VERSION`, a new `StrategyVersion` row, and **a fresh sealed look spent on
nothing**. The pre-integration assertion above catches it; running it is mandatory.

---

## 7. Leakage argument

**Primary recommendation: nothing new to argue, and that is the point.** No feature is
added, no condition is changed, `evaluate(series, t, ctx)` continues to read only
`series.head(t)` (`engine.py:102`), and `backtest/leakage.py:assert_no_lookahead`
(lines 23-41) continues to cover it unchanged.

Three leakage-adjacent facts are recorded because they bear on how the *evidence* in §3
may be used, not on the strategy:

1. **`mfe_r` / `mae_r` are post-treatment quantities.** They are computed over
   `[entry_idx, exit_idx]` (`engine.py:119-126`) — a window whose right edge is determined
   by the trade's own outcome. §3 items C, F and G use them **only** to bound or re-price
   counterfactuals on realised paths; **no strategy rule reads them**, and none is
   proposed that would. This is the same discipline `v3_atr_at_exit.md` §4 applies to the
   at-exit ATR ratio, and for the same reason: conditioning a *rule* on a post-treatment
   variable is not implementable and would be a lookahead if it were.
2. **The tighter-target re-pricing (item G) holds the trade set fixed.** An earlier exit
   would free the engine to re-enter sooner (`engine.py:149`, `t = exit_idx + 1`), so the
   real counterfactual has a slightly different trade list. This is stated as an
   approximation, is bounded in magnitude by v2's +9.2% trade count under a far more
   aggressive truncation, and cannot flip a −3 SE result.
3. **V-A's engine change is where the real leakage risk would live**, and it is *not* in
   the signal function — so `assert_no_lookahead` would not catch it. Arming and firing a
   trailing stop on the **same daily bar** assumes an intra-bar ordering of the high and
   the low that a daily OHLC bar does not contain. §2.2 pre-registers "arming takes effect
   from the next bar" precisely to close this, and a test asserting it is a condition of
   V-A ever being run.

**Shared-surface flag (§4.2 item 7).** V-A modifies `EntrySignal` and `_resolve_exit` —
shared by all six strategies including the two live-approved ones. The inertness
regression in §2.2 (v2 = 1,169 / +0.2648R, v3 = 1,071 / +0.3064R on snapshot 3, to the
digit) is not optional; without it, a v3 exits experiment silently re-prices a live
approval.

---

## 8. Cost-model statement (quantitative)

**FACT — the cost model is unchanged, and this proposal changes nothing about it.**
`costs.py:11-16`: `commission_per_share = 0.0`, `commission_min_per_order = 0.0`,
`slippage_bps = 3.0`, `half_spread_fill_penalty = True`. `engine.py:90,94`: default
`spread_bps = 5.0`, `slip = (3.0 + 5.0/2)/10,000 = 5.5 bps` per side. `engine.py:144`:
`costs_bps = 11.0` per round trip, for every trade in the program.
`backtest_runner.py:205-207` never overrides `spread_bps`, so the spread term is
**universe-independent**.

**Per-trade cost in R at this proposal's `stop_atr`.** Using map §4.2's formula
`round_trip_bps/10,000 ÷ (stop_atr × ATR/price)` with `stop_atr = 1.5` and this family's
**measured** median ATR/price at entry of **1.29%** (`v3_atr_at_exit.md` §5 — not map
§0.4's 2% reference, which **understates** the trend family's real modelled cost by ~50%):

| Round trip | implied quoted spread | cost in R at ATR/price = 1.29% | at map §0.4's 2% reference |
|---|---|---|---|
| **11.0 bps (today)** | 5 bps | **0.0568R** (mean 0.060R; IQR 0.042–0.075R) | 0.0367R |
| 26 bps | 20 bps | 0.1344R | 0.087R |
| 36 bps | 30 bps | 0.1860R | 0.120R |
| 66 bps | 60 bps | 0.3411R | 0.220R |

**Turnover delta: exactly zero.** The primary recommendation changes no entry condition,
no exit condition and no parameter, so the trade list is byte-identical: 1,071 pre-sealed
/ 319 OOS on snapshot 3. Cost delta in R: **0.0000R**.

**Turnover delta for V-A, bounded.** A trailing stop exits earlier, freeing the engine to
re-enter sooner (`engine.py:149`). The bound is v2's trade count under a *far* more
aggressive truncation (a hard 10-bar leash): 1,169 vs 1,071 = **+9.2%**. So V-A's turnover
increase is **≤ ~9%**, and the cost delta is ≤ `0.09 × 0.0568R ≈ **0.005R** per baseline
trade` — an order of magnitude below the [−5.01, +1.72] SE bracket it would be trying to
resolve. **Cost is not what decides V-A; power is.**

**Expanded-snapshot requirement (§4.2 item 8, third bullet).** This proposal does **not**
run on an expanded snapshot, so the 2×/5× spread sensitivity is not owed today. It is
pre-registered against any future run: on the W1 150-symbol snapshot the trend family's
cost would rise from **0.057R** to **0.134R (2×)** and **0.341R (5×)**. Against v3's OOS
point estimate of +0.3064R, a 5× spread consumes **more than the entire edge**. Any
exits-and-risk variant re-run on an expanded universe must report all three columns, and
a variant that only survives at 11 bps must be reported as failing.

**One cost fact that bears directly on the disposition** (map §2.1 makes the same point at
the 2% reference; at the measured 1.29% it is sharper): v3's snapshot-3 sealed shortfall is
**0.0294R**, which is **52% of one trade's modelled transaction cost** (0.0568R). The
quantity this whole angle was chartered to close is half a trade's slippage.

---

## 9. Variant budget and stopping rule

**This angle's budget: 0 strategy variants, and 0 spent.**

| | count | note |
|---|---|---|
| Strategy variants evaluated by this proposal | **0** | §3's items C–G are re-pricings of the two **already-shipped** configurations (v0.1.0 `short_swing`, v0.1.0 `medium_swing`) on the pre-sealed span. No new `evaluate()` was written or run. |
| Sealed looks consumed | **0** | k remains 5 (§10) |
| Variants this angle *proposes* to run | **0** | V-A is registered as contingent-on-override, not requested |
| Variants requested if the operator overrules §2.1 | **1** (V-A only) | V-B is dropped on arithmetic (§2.3); the `stop_atr`/`target_atr` re-scalings are dropped on §3 items B and G |

**Stopping rule, pre-registered.**

1. If V-A is run and its OOS point estimate lands anywhere inside the pre-registered
   bracket **[−0.1780, +0.4723]** — which it must, by construction — **stop**. Report the
   number with the bracket attached, report it as one variant out of one, and do not
   propose a second cell. A second cell would be searching the bracket.
2. **No grid over `(trail_arm_r, trail_lock_r)` outside gate 5's own pre-registered 3×3.**
   Gate 5's grid is a robustness test, not a candidate pool; its best cell may never be
   promoted to the shipped parameter set (that is exactly the selection R5 forbids).
3. **Hard cap: one variant for this angle, ever.** If V-A fails, the exits-and-risk angle
   is closed for v3 and the null option (§11) is written. It is not re-opened by a new
   idea; it is re-opened only by one of the pre-registered conditions F1–F4 (§4) firing on
   a better-powered dataset.

**Cross-angle note.** Map §4.1 allocates v3 three proposals (null / exits-risk /
signal-quality) and warns that "total per strategy across all three angles should be small
and stated up front". This angle contributes **0** to that total under its own
recommendation and at most **1** under override. That leaves the whole budget to the
signal-quality angle, which is the right allocation given that H1–H3 are dead and H4
(volume-confirmation decay) has not yet been tested.

---

## 10. Sealed-look accounting

**FACT — the baseline count is k = 5** (map §0.1, R2): four locked sealed tests already
exist per version, one per dataset snapshot, and the §0.1 ledger is reproduced here in
full, re-queried read-only from `strategy_sealed_test` for this document (20 rows, exactly
4 per version for versions 2–6):

| Ver | Strategy | snap 1 `universe_25_baseline_legacy` | snap 2 `universe_25_baseline` | snap 3 `universe_24_ex_meta` | snap 4 `universe_25_meta_continuity_corrected` |
|---|---|---|---|---|---|
| 2 | `trend_continuation.short_swing` | id 1: **+0.3246R / 112** ✅ | id 6: **+0.3246R / 112** ✅ | id 11: **+0.2982R / 109** ✅ | id 16: **+0.3246R / 112** ✅ |
| **3** | **`trend_continuation.medium_swing`** | **id 2: +0.0109R / 98** ✅ | **id 7: +0.0109R / 98** ✅ | **id 12: −0.0294R / 95** ❌ | **id 17: +0.0109R / 98** ✅ |
| 4 | `mean_reversion.short_swing` | id 3: +0.1230R / 91 ✅ | id 8: +0.1230R / 91 ✅ | id 13: +0.1278R / 84 ✅ | id 18: +0.1230R / 91 ✅ |
| 5 | `relative_strength.medium_swing` | id 4: +0.2935R / 16 ✅ | id 9: +0.2935R / 16 ✅ | id 14: +0.2935R / 16 ✅ | id 19: +0.2935R / 16 ✅ |
| 6 | `volatility_breakout.short_swing` | id 5: −0.0979R / 10 ❌ | id 10: −0.0979R / 10 ❌ | id 15: −0.0979R / 10 ❌ | id 20: −0.0979R / 10 ❌ |

Sealed windows: 2025-09-07 → 2026-09-07 on snapshot 1; 2025-09-08 → 2026-09-08 on
snapshots 2–4. Version 3's sealed SEs at its measured per-trade sd of 1.7259:
**n = 95 → SE 0.1771, z = −0.166**; **n = 98 → SE 0.1743, z = +0.063**. The sealed evidence
is statistically indistinguishable from zero on every snapshot.

**Under the primary recommendation (§2.1): k stays at 5.** No behavioural change ⇒ no
`VERSION` bump ⇒ no new `StrategyVersion` row ⇒ `_get_or_create_sealed_test`
(`promotion.py:354-384`) **replays** the locked row rather than drawing a new one, and the
unique constraint on `(strategy_version_id, dataset_snapshot_id)`
(`db/models/research.py:263`) guarantees it. Even re-running `evaluate-promotion` against
snapshot 3 on the unchanged v0.1.0 creates **no new look**. This is a real and
under-appreciated advantage of the null: it is the only option in the program that costs
nothing in multiple-testing budget.

**Under V-A (if the operator overrules):** `VERSION = "0.2.0"` creates a new
`StrategyVersion` row, hence a never-before-sealed gate 9. Sealing on snapshot 3 is
**look 6**. Evaluating the same v0.2.0 on both snapshot 3 and a new expanded (W1) snapshot
is **looks 6 and 7**. A pass must be reported as *"passed on look 6"*, never as an
unqualified pass. Also required at integration (map §4.3): assert that the v0.2.0's
`StrategySealedTest.strategy_version_id` is a row created by *that* run, to catch the
R3 staleness trap.

**Pre-registered lead snapshot (R1).** This report leads with **snapshot 3**, because it is
the **only** snapshot on which gate 8 `data_quality_and_leakage` passes at all — snapshots
1 and 2 fail on META's 90 missing bars (6.9%) and snapshot 4 fails because `META_CONT`
carries source `continuity_bridge:1`, not `massive`. The choice is forced by a pre-sealed
data-quality gate, not selected after seeing gate 9. **The other three sealed draws are
disclosed alongside it in the table above, in every case**, and the honest one-line summary
is: *v3's gate 9 passes on three of four snapshots; the single failure turns on 3 META
trades worth +3.86R; and the sealed mean is between +0.06 and −0.17 SE from zero on every
snapshot.*

**Sealed-look disclosure for this document itself:** zero looks consumed, zero
`strategy_sealed_test` rows created, zero `strategy_promotion_evaluation` rows created.
Verifiable: `strategy_sealed_test` still has 20 rows and
`strategy_promotion_evaluation` still has 42.

---

## 11. Null option

For this angle the null option is not a fallback — **it is the recommendation** (map §4.1
makes the null v3's proposal #1; this document reaches the same place from the exits-and-risk
side, independently and on new evidence). §4.2 item 11 asks what documented "does not pass"
would be written and what evidence it would carry. Concretely:

### 11.1 The document that gets written

**Title:** `trend_continuation.medium_swing` v0.1.0 — documented non-pass on snapshot 3,
exits-and-risk angle exhausted.

**Verdict paragraph, in the form it should appear:**

> `trend_continuation.medium_swing` v0.1.0 clears gates 1–8 and 10 on snapshot 3 with
> margins wider than the approved `short_swing` on gates 3, 4 and 7 (+0.3064R vs +0.2648R;
> CI low +0.1205 vs +0.1129; Sharpe 1.156 vs 0.807). It fails gate 9 on snapshot 3 by
> **0.0294R** — **52% of one trade's modelled transaction cost** — and passes gate 9 on
> snapshots 1, 2 and 4. The failure turns on **3 META trades worth +3.86R**. The sealed
> mean is **−0.166 SE** from zero on snapshot 3 and **+0.063 SE** on the others; it is
> also **1.65–1.88 σ below** its own pre-sealed mean, and under the pre-sealed estimate
> `P(sealed mean < 0 | n = 95) = 4.3%`. The strategy is **not promoted**. No change was
> made, and the reason is not resignation: **every exits-and-risk lever was measured and
> each is either arithmetically incapable of producing evidence or measurably worse.**

**Evidence it carries** (all pre-sealed, all on four snapshots, all with SEs):

1. The §0.1 sealed ledger in full, with the lead-snapshot justification (§10).
2. H1, H2 falsified; H3 not supported — with each hypothesis's own pre-registered
   falsification condition and the result against it.
3. **The exits-and-risk closure table (§3.1)** — seven axes, each with its best available
   pre-sealed OOS estimate and verdict. In particular: the time-stop lever's attainable
   range is **±0.07 SE** on OOS; the trailing family's unattainable best case is
   **+1.72 to +1.82 SE**, below the 2 SE evidence bar; tighter targets are worse by
   **2.0–3.2 SE** across the 1.0R–1.5R band on all four snapshots; all eight non-baseline
   `stop_atr`/`sma_fast` grid cells are below the baseline.
4. The **selection caveat** (§3 item B, HYPOTHESIS): the shipped parameters sit at the
   maximum of gate 5's 9-point OOS grid, which is the pattern expected if they were chosen
   on this data, and which is consistent with the pre-sealed→sealed gap. This belongs in
   the report because it argues *against* the strategy, and a report that only carries
   arguments in its own favour is not evidence.
5. The **clustered-bootstrap disclosure** (`clustered_bootstrap_all.md`): under a
   calendar-month block bootstrap both live-approved strategies would fail gate 4's
   +0.02R lower bound. v3 is not the weakest thing in this program, and the report should
   say so without using it as an argument for promotion.
6. The variant count: **0 variants tried by this angle**, k unchanged at 5.

### 11.2 The one action item this angle produces

**Escalate H14 (§1.3, §3 item E) to the pipeline-hardening track and to the operator.**
The entry-bar risk-unit collapse is worth **−79.79R on v3 (44.7% of its total pre-sealed
R)** and **−98.39R on the live-approved v2 (84.3% of its total)**, is stable on all four
snapshots, and includes **16–19 trades per version that the engine books as ≈ +1R wins
after gapping through their own stop**. It is not a v3 lever — it cannot be fixed without
either lookahead or an engine change that re-prices a live approval — but it is the largest
identifiable distortion in the family's evidence base and it should not stay buried in an
incidental-findings section. The operator decision it needs is: *do we re-price v2's
approval evidence to fix this, or do we document it as a known bias and leave the live
approval on the numbers it was granted on?*

### 11.3 What "success" looks like for this angle

Not a promotion. The successful outcome is that **the next person who proposes a trailing
stop for this strategy family finds the arithmetic already done and the bracket already
pre-registered**, and either produces evidence that clears F1–F4 or does not run it. That
is what an exhausted angle should leave behind.

---

*Raw computed numbers: `trend_continuation_medium_swing--exits_risk.json` (sibling).
Trade-level MFE/MAE data (9,130 rows across four snapshots and two versions) was written
to the session scratchpad only and is not committed.*
