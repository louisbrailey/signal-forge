# Design proposal — `trend_continuation.medium_swing` v0.1.0 (version 3)
## Angle: signal quality / regime conditioning

**Proposal id:** `SR-1` (signal_regime, variant 1) — *no-chase entry filter*
**Author role:** independent proposer (Phase 2, `STRATEGY_COMPLETION_PLAN.md`)
**Target snapshot (pre-registered):** snapshot 3 `universe_24_ex_meta`, source `massive`
**Sealed-look count if implemented:** k = 5 → **look 6**

---

## VERDICT UP FRONT

**Recommendation: DO NOT IMPLEMENT. Take the null option (§11).**

This proposal is written in full because §4.2 requires every section, and because the
work it reports is the diagnostic the signal-quality/regime angle owed the program.
Its own conclusion is negative, on its own pre-registered evidence bar:

1. **FACT — the regime axis is already saturated and offers nothing.** Across all
   four snapshots, **every one of v3's pre-sealed trades enters in a `Vol.LOW`,
   non-`BEAR` `RegimeState`** (snapshot 3: 858 `bull/low` + 213 `neutral/low` =
   1,071; zero `bear`, zero `high`). The inherited `not ctx.regime.risk_off` gate
   (`trend_continuation.py:100`, inside the `long_ok` conjunction :95-101) has already removed every risk-off session. The only
   remaining `RegimeState` split is bull vs neutral, and **neutral is the better
   bucket** (+0.2523R ± 0.1137 vs +0.1455R ± 0.0534 all-pre-sealed, snapshot 3), so
   any tightening on this axis removes the better trades. There is no regime filter
   to add.
2. **FACT — H4 (volume-confirmation decay) is falsified.** Expectancy by entry
   `vol_ratio` tercile is flat on all four snapshots and both cuts; the largest
   T3−T1 contrast anywhere is **+0.0390R ± 0.1179 (0.33 SE)**.
3. **FACT — H5 is falsified in its strongest form** (already recorded in
   `v3_duration_exits.md`, reproduced here): 0 of 4,365 v3 pre-sealed trades are
   SHORT, because `evaluate_promotion` never passes `allow_short`.
4. The single best surviving entry-quality conditioner — recent 5-session run-up in
   ATR units, the "chase" filter specified below — produces a **kept-minus-suppressed
   contrast of +0.1786R ± 0.0987 (1.81 SE) all-pre-sealed and +0.3200R ± 0.1938
   (1.65 SE) OOS on snapshot 3**. Under the program's own rule (*"a difference under
   2 SE is not evidence"*) **that is not evidence**, and its pre-registered kill
   condition (§4) is therefore already met.
5. Its own mechanism sub-prediction fails: chased entries do **not** stop out sooner
   (same-bar exit rate 7.9% for suppressed vs 10.7% for retained trades, snapshot 3),
   so the "over-extended entries get shaken out" story is not what the data shows.
6. **It cannot help the only gate v3 fails.** v3 passes gates 1–8 on snapshot 3
   today. Its sole failing gate is **9**, which lives in the sealed window and which
   R1 forbids targeting. Any pre-sealed improvement is unverifiable against the
   actual failure, and shipping it spends **look 6** on a change whose stated benefit
   cannot be checked without spending the look.
7. It **creates two new zero-margin cases** that do not exist today: gate 6's bear
   bucket falls 22 → 13 against a floor of 10, and walk-forward fold F3's expectancy
   falls +0.0343R → **+0.0007R** (snapshot 3) — a fold that currently clears gate 1's
   `expectancy_r > 0` test by 49× would clear it by a rounding error.

SR-1 is specified completely and pre-registered anyway, so that if the operator
decides a change is warranted the *one* variant is already fixed and cannot be
re-chosen after seeing more results.

---

## 0. Provenance, safety and reproduction

**FACT.** Every number below was produced in-process by
`signalforge.backtest.engine.run_backtest` driven by
`signalforge.research.strategies.base.signal_fn_for`, with call arguments matched to
`research/promotion.py:585-594` (`proxy_symbol="SPY"`, default `CostModel()`,
`allow_short=False`, `warmup=min_bars // 2 = 30`). Both are pure read paths
(`backtest_runner.run_strategy_over_universe`, `backtest_runner.py:167`, contains no
`session.add`/`flush`/`commit`). The **live** `data/signalforge.sqlite` was opened
read-only; **no scratch copy was needed and no write was issued**. No file under
`src/` or `tests/` was modified. No promotion evaluation was run, so **no
`strategy_sealed_test` row was created and the look count remains k = 5**.

**FACT — the sealed window was never loaded.** Each run covers only
`[start, pre_sealed_end]` with `pre_sealed_end = sealed_start − 1 day`
(`promotion.py:549-557`), taken from the stored evaluation rows:

| Snapshot | key | symbols | source filter | run span (pre-sealed) | sealed window (untouched) |
|---|---|---|---|---|---|
| 1 | `universe_25_baseline_legacy` | 25 (incl. `META`) | `massive` | 2016-09-09 → **2025-09-06** | 2025-09-07 → 2026-09-07 |
| 2 | `universe_25_baseline` | 25 (incl. `META`) | `massive` | 2016-09-10 → **2025-09-07** | 2025-09-08 → 2026-09-08 |
| 3 | `universe_24_ex_meta` | 24 (no META) | `massive` | 2016-09-10 → **2025-09-07** | 2025-09-08 → 2026-09-08 |
| 4 | `universe_25_meta_continuity_corrected` | 25 (`META_CONT`) | `["massive","continuity_bridge:1"]` | 2016-09-10 → **2025-09-07** | 2025-09-08 → 2026-09-08 |

**FACT — exact reproduction of the stored gate evidence.** The harness reproduces
evaluation id 33's numbers to the digit, which is the control that it is the same
computation the gates ran:

| quantity | harness | stored (`gates_json`, §2.1/§0.6) |
|---|---|---|
| v3 snap-3 pre-sealed trades | **1,071** | 1,071 |
| v3 snap-3 OOS n / expectancy | **319 / +0.3064R** | 319 / +0.3064R |
| v3 snap-3 OOS bootstrap CI | **[+0.1205, +0.5027]** | [+0.1205, +0.5027] |
| v3 snap-3 gate-6 buckets | **bull 857 / bear 22 / range 69**, unbucketed **123** | 857 / 22 / 69, 123 |
| v3 snap-3 gate-7 Sharpe vs SPY | **+1.1560 vs +0.7190** | 1.156 vs 0.719 |
| v3 snap-3 folds | **+0.1822/310, +0.0772/323, +0.0343/179, +0.3513/259** | same |
| v3 snap-4 OOS n / expectancy | **336 / +0.3169R** | 336 / +0.3169R (eval 39) |

**FACT — the directly measured OOS per-trade sd is 1.7259** (snapshot 3), against
§0.3's CI-inverted estimate of 1.741 (0.9% apart). All SEs below use the measured sd.

**A caveat that governs every "all four snapshots" claim in this document.**
Snapshots 1 and 2 are byte-identical in result; snapshot 3 is snapshot 2 **minus one
symbol**; snapshot 4 is snapshot 2 with `META` replaced by `META_CONT`. Agreement
across the four is therefore *close to one observation*, not four. Where a claim
needs independent replication this document uses the **four walk-forward folds**
(disjoint calendar periods) instead, and says so.

---

## 1. Mechanism

**Hypotheses this proposal addresses, and their status.**

- **H4 (volume confirmation decays) — tested here, FALSIFIED.** The premise was that
  `vol_ratio ≥ 1.3` over a 20-day window is a 1–5-day trigger whose information is
  spent long before a 40-bar hold ends, so higher-`vol_ratio` entries should
  underperform on a medium-swing leash. The prediction fails: expectancy by entry
  `vol_ratio` tercile is flat everywhere (§3). H4 may not motivate anything (R10).
- **H5 (short-side asymmetry) — FALSIFIED** (confirmed independently here; first
  established in `v3_duration_exits.md`): the short branch
  (`trend_continuation.py:113-133`) is dead code under the gates.
- **H14 (new) — the regime axis is saturated by construction.** *Statement:* v3's
  entry already requires `not ctx.regime.risk_off`, and `risk_off = trend is BEAR or
  vol is HIGH` (`regime.py:41-42`), so **no `RegimeState`-based conditioner can
  remove a bear or high-vol entry — there are none to remove.** The only available
  split is `Trend.BULL` vs `Trend.NEUTRAL`, and neutral is the *better* bucket.
  *Verified* (§3). H14 is the reason this angle has no regime proposal at all.
- **H13 (new) — entry over-extension ("chase").** *Statement:* a trend-continuation
  entry taken after price has already travelled a large distance in a few sessions is
  buying the end of a thrust rather than the middle of a trend; the 1.5×ATR stop then
  sits inside the ordinary give-back of that thrust and the 3.0×ATR target requires
  the thrust to extend rather than merely continue. *Prediction:* expectancy declines
  monotonically in recent run-up measured in ATR units, and the mechanism should show
  up as **earlier, more frequent stop-outs** among extended entries.
  *Result:* the expectancy gradient exists and is directionally stable in all 16
  fold×snapshot cells, but it is **under 2 SE**, and **the sub-prediction is wrong** —
  extended entries stop out *less* often on the entry bar (7.9% vs 10.7%) and carry
  *larger* excursions in both directions (mean MFE +1.560 vs +1.406R; mean MAE −1.257
  vs −1.164R). The honest reading is not "chasing gets shaken out" but "extended
  entries are noisier with a slightly worse target/stop mix" (target rate 39.2% vs
  42.5%). A mechanism whose own diagnostic signature is absent is a weak mechanism.

**Why this is a market claim and not a backtest claim.** Trend continuation profits
from the *persistence* of an established move. Persistence and exhaustion are
different states of the same trend, and the distance travelled since the last
consolidation is the classical, non-fitted way to distinguish them. That is a real
market hypothesis. The evidence just does not clear the bar (§3, §4).

---

## 2. Exact change

New behaviour ships as a **new version**, `v0.2.0`, with v0.1.0 untouched (R3/R7).

### 2.1 `src/signalforge/research/strategies/trend_continuation.py`

**`TrendParams` (lines 20-29) — before:**

```python
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
```

**after** (two added fields; every existing field and default unchanged):

```python
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
    run_lookback: int = 5             # NEW — sessions of run-up measured
    max_run_up_atr: float | None = None  # NEW — None = v0.1.0 behaviour exactly
```

`max_run_up_atr = None` is the **identity default**: an existing `TrendParams()`
constructed anywhere in the codebase or in a test keeps v0.1.0 behaviour bit for bit.

**`TrendContinuation.evaluate` (lines 85-133) — before**, the long branch is:

```python
long_ok = (
    close > slow
    and fast > slow
    and close > fast
    and vr >= p.vol_mult
    and not ctx.regime.risk_off
)
```

**after** — one added conjunct, computed from a new local:

```python
run_up = run_up_atr(series, t, p.run_lookback, p.atr_window)   # NEW
if p.max_run_up_atr is not None and (math.isnan(run_up) or run_up > p.max_run_up_atr):
    return None                                                 # NEW

long_ok = (
    close > slow
    and fast > slow
    and close > fast
    and vr >= p.vol_mult
    and not ctx.regime.risk_off
)
```

The early `return None` is placed **before** the long branch and therefore also
suppresses the (dead-under-the-gates) short branch; that is deliberate — a symmetric
rule is easier to reason about than a long-only exception, and it changes nothing
measurable while `allow_short=False`.

### 2.2 `src/signalforge/research/features/daily.py` — one new feature

```python
def run_up_atr(series: PriceSeries, t: int, lookback: int = 5, atr_window: int = 14) -> float:
    """Close-to-close advance over ``lookback`` sessions, in ATR units.

    Point-in-time: reads only indices <= t.
    """
    if t - lookback < 0:
        return NAN
    a = atr(series, t, atr_window)
    if a != a or a <= 0:
        return NAN
    return (float(series.close[t]) - float(series.close[t - lookback])) / a
```

### 2.3 Version handling — **the single most dangerous part of this change**

**FACT (hazard).** `VERSION = "0.1.0"` is a **module-level constant**
(`trend_continuation.py:17`) and `spec()` returns `version=VERSION`
(`trend_continuation.py:46`). The same module and the same class serve **both**
`trend_continuation.short_swing` (**version 2, PAPER_APPROVED, live**) and
`trend_continuation.medium_swing` (version 3).

**FACT.** `approval_scope.current_spec_json_hash` (`approval_scope.py:97-121`)
resolves a live strategy by iterating `default_strategies()` and matching
`(Strategy.name, StrategyVersion.version)`. **If the module constant were simply
bumped to `"0.2.0"`, nothing in `default_strategies()` would resolve to v2's
`StrategyVersion` row any more, `current_spec_json_hash` would return `None`, and
every live auto-simulation and alert scope check for the approved short-swing
strategy would fail** (`paper/ledger.py:387, 509`; `alerts/dispatch.py:277`).

**Therefore the version must become per-instance, not module-wide:**

```python
VERSION = "0.1.0"            # unchanged — the baseline version string
VERSION_NO_CHASE = "0.2.0"   # NEW

class TrendContinuation:
    def __init__(self, horizon=Horizon.SHORT_SWING, params=None):
        ...
        self.version = (
            VERSION_NO_CHASE if (self.params.max_run_up_atr is not None) else VERSION
        )

    def spec(self) -> StrategySpec:
        return StrategySpec(..., version=self.version, ...)
```

so that the version string is a function of *behaviour*, and an unchanged
`TrendParams` can never silently acquire a new version string.

`spec()` is generated from params (`trend_continuation.py:42-83`) and needs no manual
sync, but two literal strings must be extended so the recorded spec describes what
runs:

- `rule_definition` — append: `"…, and only when the {run_lookback}-session close-to-close advance is <= {max_run_up_atr} x ATR({atr_window})"`.
- `feature_definitions` — append: `f"run_up_atr=(close(t)-close(t-{p.run_lookback}))/ATR({p.atr_window})"`.

### 2.4 `src/signalforge/research/strategies/__init__.py:43-51`

```python
def default_strategies() -> list[BaselineStrategy]:
    return [
        IntradayORB(),
        TrendContinuation(Horizon.SHORT_SWING),                       # v0.1.0, version 2 — UNTOUCHED
        TrendContinuation(Horizon.MEDIUM_SWING),                      # v0.1.0, version 3 — UNTOUCHED
        TrendContinuation(                                            # NEW — v0.2.0
            Horizon.MEDIUM_SWING,
            TrendParams(time_stop_bars=40, max_run_up_atr=2.0, run_lookback=5),
        ),
        MeanReversion(),
        RelativeStrength(Horizon.MEDIUM_SWING),
        VolatilityBreakout(Horizon.SHORT_SWING),
    ]
```

`StrategyRegistry` keys on `versioned_key` (`registry.py:94-96`), so
`trend_continuation.medium_swing@0.1.0` and `@0.2.0` coexist without collision.

**Side effect to disclose:** `research/scan.py:111` selects strategies by horizon
from `default_strategies()`, so the v0.2.0 sibling **joins every live scan** as an
EXPERIMENTAL strategy. It cannot generate alerts or auto-simulated fills (both
require `PAPER_APPROVED`, `ledger.py:473-512`), but it does add scan work and a row
to the scan output. That is an operating-surface change and must be acknowledged
before merge.

### 2.5 The threshold, and why 2.0

`max_run_up_atr = 2.0` is a **round number chosen before the re-runs**, not an
optimum. The empirical 67th percentile of the 5-session run-up over snapshot 3's
pre-sealed trades is 1.8636 ATR; picking that value would be fitting the cut point to
the sample. 2.0 ATR suppresses **29.5%** of snapshot-3 pre-sealed baseline signals.
All three grid values 1.5 / 2.0 / 2.5 are reported in §3 and §5 so the choice is
visibly not the argmax (1.5 gives the highest OOS expectancy; 2.0 is the middle).

---

## 3. Pre-sealed evidence, with standard errors

All figures are pre-sealed only. `exp` = mean `pnl_r`; `SE` = sample sd / √n.
**"ALL"** = the whole pre-sealed span (the trade set gates 1, 6 and 7 read);
**"OOS"** = the last 40% of each symbol's own bars (the set gates 2, 3, 4 read).

### 3.1 The regime axis is saturated (H14) — FACT

`RegimeState` at the signal bar, for every v3 pre-sealed trade:

| snapshot | `bull/low` | `neutral/low` | `bull/high` | `bear/*` | total |
|---|---|---|---|---|---|
| 1 / 2 | 874 | 217 | **0** | **0** | 1,091 |
| 3 | 858 | 213 | **0** | **0** | 1,071 |
| 4 | 889 | 223 | **0** | **0** | 1,112 |

Expectancy by the only available split:

| snapshot | cut | `bull` | `neutral` |
|---|---|---|---|
| 3 | ALL | +0.1455 ± 0.0534 (n=858) | **+0.2523 ± 0.1137** (n=213) |
| 3 | OOS | +0.2597 ± 0.1002 (n=269) | **+0.5574 ± 0.2991** (n=50) |
| 4 | ALL | +0.1440 ± 0.0530 (n=889) | **+0.2760 ± 0.1109** (n=223) |
| 1 / 2 | ALL | +0.1532 ± 0.0530 (n=874) | **+0.2571 ± 0.1125** (n=217) |

The favoured bucket is the *less* trend-confirmed one, and the contrast is itself
under 2 SE (snapshot 3 ALL: +0.1068 ± 0.1256, 0.85 SE). There is no regime filter
here worth proposing in either direction.

**A concrete instance of the §4.3 two-labeller caveat, quantified.** The same 1,071
snapshot-3 trades are labelled by `research/regime.py` as **0 bear / 0 high-vol**,
and by `backtest/regime.py:label_regimes` (the labeller gate 6 uses,
`promotion.py:739-763`) as **22 bear**. The two labellers disagree about 22 trades'
regime, in the direction that matters most for gate 6. This proposal therefore
**measures** every gate-6 bucket directly (§5) rather than inferring it from any
`RegimeState` reasoning — as §4.3 requires.

### 3.2 H4 — volume-ratio conditioning is flat (FALSIFIED)

Terciles of entry `vol_ratio`; cut points from snapshot 3 ALL (1.4131 / 1.6376):

| snapshot | cut | T1 (low vol_ratio) | T2 | T3 (high) | T3−T1 |
|---|---|---|---|---|---|
| 1 / 2 | ALL | +0.1452 ± 0.0893 (360) | +0.1917 ± 0.0831 (361) | +0.1843 ± 0.0770 (370) | +0.0390 ± 0.1179 (**+0.33 SE**) |
| 3 | ALL | +0.1550 ± 0.0898 (357) | +0.1816 ± 0.0830 (357) | +0.1635 ± 0.0785 (357) | +0.0085 ± 0.1193 (**+0.07 SE**) |
| 4 | ALL | +0.1530 ± 0.0886 (366) | +0.2030 ± 0.0827 (365) | +0.1560 ± 0.0774 (381) | +0.0031 ± 0.1177 (**+0.03 SE**) |
| 3 | OOS | +0.4109 ± 0.1888 (115) | +0.1776 ± 0.1488 (106) | +0.3231 ± 0.1557 (98) | −0.0878 ± 0.2447 (−0.36 SE) |
| 4 | OOS | +0.3744 ± 0.1851 (118) | +0.2108 ± 0.1498 (110) | +0.3620 ± 0.1468 (108) | −0.0124 ± 0.2363 (−0.05 SE) |

H4's stated falsification condition — *"pre-sealed expectancy conditioned on entry
`vol_ratio` bucket is flat"* — is met on every snapshot and both cuts.

### 3.3 The full conditioner screen (R5 disclosure: 15 variables examined)

Every candidate was scored the same way — terciles on snapshot-3 ALL cut points,
evaluated on all four snapshots × both cuts. `T3−T1` in SE units:

| conditioner | ALL (snaps 1/2, 3, 4) | OOS (snaps 1/2, 3, 4) | verdict |
|---|---|---|---|
| `vol_ratio` (H4) | +0.33, +0.07, +0.03 | −0.27, −0.36, −0.05 | flat — falsified |
| entry-bar true range / ATR | −0.40, −0.09, −0.51 | −0.66, −0.49, −0.97 | flat |
| 3-bar mean TR / ATR | −0.69, −0.54, −0.81 | −0.93, −0.78, −1.03 | flat |
| overnight gap to fill, in ATR | +0.52, +0.48, +0.15 | −0.53, −0.56, −0.50 | flat |
| realised risk unit / 1.5×ATR | +0.40, +0.35, +0.05 | −0.72, −0.74, −0.66 | flat |
| close position in signal-bar range | −0.63, −0.59, −0.69 | +0.38, +0.39, +0.32 | sign flip |
| 10-bar run-up in ATR | +0.64, +0.51, +0.70 | +0.51, +0.56, +0.77 | flat, wrong sign for H13 |
| extension above SMA20, in ATR | −1.27, −1.40, −1.40 | −0.89, −0.84, −0.66 | consistent, **< 2 SE** |
| **5-bar run-up in ATR (H13)** | **−1.28, −1.19, −1.22** | **−1.79, −1.64, −1.74** | consistent, **< 2 SE** |
| extension above SMA50, in ATR | **−2.04, −2.22, −2.29** | −0.18, −0.26, +0.01 | **collapses OOS** |
| (SMA20 − SMA50)/ATR | **−2.26, −2.35, −2.36** | +0.93, +0.86, +1.04 | **sign reverses OOS** |
| ATR/price at signal | **+2.28, +2.18, +2.19** | −1.16, −1.05, −0.96 | **sign reverses OOS** |
| proxy trailing 20d return | **−2.36, −2.40, −2.62** | −0.25, −0.28, −0.37 | **collapses OOS** |
| `RegimeState.trend` | bull vs neutral, 0.85 SE | 0.94 SE | saturated (§3.1) |
| `RegimeState.vol` | single-valued (`low`) | single-valued | saturated (§3.1) |

**The pattern is the finding.** Four conditioners clear 2 SE on the all-pre-sealed
cut; **every one of them collapses to ≈0 or reverses sign on the OOS cut.** They are
in-sample structure, and any of them would have made a superficially attractive
proposal. The only conditioners that keep their sign on both cuts are the two
extension measures, and neither reaches 2 SE anywhere. Fifteen variables were
screened to find this; that count is part of the record under R5, and it means the
1.6–1.8 SE survivor should be discounted further, not rounded up to "nearly
significant".

### 3.4 SR-1's measured effect (re-run, not post-hoc filtering)

Post-hoc dropping of trades from the baseline list is **not** a valid forecast: the
engine takes no overlapping positions (`engine.py:149`, `t = exit_idx + 1`), so
suppressing a signal frees later bars for signals the baseline never saw. Everything
below is a **full re-run** with the filter inside the signal function. (For scale:
post-hoc filtering of snapshot 3 leaves 714 trades; the re-run produces **871**.)

Kept-vs-suppressed contrast, from the baseline trade list (the cleanest statement of
the effect size, since the two groups are disjoint):

| snapshot | cut | retained (run-up ≤ 2.0) | suppressed (> 2.0) | difference |
|---|---|---|---|---|
| 1 / 2 | ALL | +0.2383 ± 0.0610 (725) | +0.0461 ± 0.0763 (366) | +0.1922 ± 0.0977 (**1.97 SE**) |
| 3 | ALL | +0.2262 ± 0.0614 (714) | +0.0477 ± 0.0773 (357) | +0.1786 ± 0.0987 (**1.81 SE**) |
| 4 | ALL | +0.2290 ± 0.0611 (735) | +0.0563 ± 0.0755 (377) | +0.1726 ± 0.0971 (**1.78 SE**) |
| 1 / 2 | OOS | +0.3986 ± 0.1207 (223) | +0.0662 ± 0.1479 (103) | +0.3325 ± 0.1909 (**1.74 SE**) |
| 3 | OOS | +0.4077 ± 0.1228 (218) | +0.0877 ± 0.1500 (101) | +0.3200 ± 0.1938 (**1.65 SE**) |
| 4 | OOS | +0.4262 ± 0.1201 (227) | +0.0892 ± 0.1442 (109) | +0.3369 ± 0.1877 (**1.80 SE**) |

**Not one cell reaches 2 SE.**

Fold-level replication (the only genuinely independent axis available — four disjoint
calendar periods; snapshot 3, retained − suppressed):

| fold | span | baseline n / exp | retained | suppressed | difference |
|---|---|---|---|---|---|
| F1 | 2016-09-10 → 2018-12-10 | 310 / +0.1822 | +0.2081 ± 0.1093 (198) | +0.1365 ± 0.1368 (112) | +0.0717 ± 0.1751 (+0.41 SE) |
| F2 | 2018-12-10 → 2021-03-10 | 323 / +0.0772 | +0.1387 ± 0.1113 (211) | −0.0385 ± 0.1381 (112) | +0.1771 ± 0.1774 (+1.00 SE) |
| F3 | 2021-03-10 → 2023-06-09 | 179 / +0.0343 | +0.0793 ± 0.1331 (122) | −0.0621 ± 0.1932 (57) | +0.1414 ± 0.2346 (+0.60 SE) |
| F4 | 2023-06-09 → 2025-09-07 | 259 / +0.3513 | +0.4448 ± 0.1372 (183) | +0.1261 ± 0.1717 (76) | +0.3187 ± 0.2198 (+1.45 SE) |

**All 16 fold × snapshot cells share the sign** (positive), which is the one genuinely
encouraging property of H13 — but the largest single-fold contrast is 1.51 SE and the
pooled figure is 1.81 SE. Sixteen same-sign cells drawn from four folds × four nested
snapshots is roughly four independent observations, not sixteen.

For contrast, the *other* consistent conditioner, extension above SMA20, **fails**
fold replication outright: F2 gives +2.15 to +2.33 SE while **F3 gives −0.36 to −0.65
SE** on every snapshot. It is one fold's effect, exactly as `v4_regime_vol_stationarity.md`
found for v4's HIGH-vol penalty. It is rejected on that basis and is not carried
forward as a variant.

Mechanism sub-test (snapshot 3, baseline trades, retained vs suppressed):

| quantity | retained (≤2.0 ATR) | suppressed (>2.0 ATR) |
|---|---|---|
| same-bar exit rate | **10.7%** | **7.9%** |
| stop-exit share | 56.6% | 58.5% |
| target-exit share | 42.5% | 39.2% |
| mean MFE | +1.406R | **+1.560R** |
| mean MAE | −1.164R | **−1.257R** |

H13 predicted *more* immediate stop-outs among extended entries. The opposite is
observed on all four snapshots. What is actually there is a 3.3pp target-rate tilt
and larger two-sided excursions.

---

## 4. Falsification — stated before the runs, evaluated on all four snapshots

The proposal was pre-registered to die on **any** of the following. All four
conditions are evaluated on all four snapshots (R10).

| # | Kill condition | Result | Status |
|---|---|---|---|
| K1 | The retained-minus-suppressed contrast fails to reach **2.0 SE** on the all-pre-sealed cut on **all four** snapshots | 1.97 / 1.97 / 1.81 / 1.78 SE — **no snapshot reaches 2.0** | **MET → proposal dies** |
| K2 | The contrast fails to reach 2.0 SE on the **OOS** cut on all four snapshots | 1.74 / 1.74 / 1.65 / 1.80 SE | **MET** |
| K3 | The sign of the contrast flips in **any** walk-forward fold on **any** snapshot | no flip (16/16 positive) | not met |
| K4 | The mechanism's own signature is absent: suppressed entries do **not** show a higher same-bar / early stop-out rate | suppressed 7.9% vs retained 10.7% — **the wrong way round** on all four snapshots | **MET** |
| K5 | The change pushes any currently passing gate to a margin thinner than it has today | gate 6 bear 22 → 13 (floor 10); fold F3 +0.0343 → +0.0007 | **MET** |
| K6 | Any grid value of the new axis makes OOS expectancy negative or drops a grid cell below the 15-trade floor | all three values positive; min cell 237 OOS trades | not met |

**Three of six kill conditions are met, including the two headline ones.** Under R10
that ends the proposal. It is retained in written form only as a pre-registration
(§9) in case the operator overrides the recommendation.

For completeness, the condition that *would* have justified proceeding, stated so it
cannot be moved later: **a ≥2 SE retained-minus-suppressed contrast on the OOS cut on
at least three of four snapshots, together with a ≥2 SE contrast in at least two of
the four walk-forward folds, and no currently passing gate losing margin.** SR-1 meets
none of the three clauses.

---

## 5. Gate-by-gate forecast (measured, not guessed)

Everything except gate 9 is **measured** on the pre-sealed span for the exact v0.2.0
rule at `max_run_up_atr = 2.0`, `run_lookback = 5`, and is reported per trade set as
§0.2 requires. Gate 9 is unforecastable by rule.

### 5.1 Snapshot 3 (the pre-registered lead snapshot)

| # | Gate | Trade set | v0.1.0 (measured) | **v0.2.0 SR-1 (measured)** | Verdict / risk |
|---|---|---|---|---|---|
| 0 | `data_availability` | — | pass | pass (span unchanged) | no change |
| 1 | `rolling_walkforward` | ALL pre-sealed | 4/4 folds clear: +0.1822/310, +0.0772/323, **+0.0343/179**, +0.3513/259 | 4/4 clear: +0.1719/239, +0.2386/269, **+0.0007/146**, +0.3570/217 | **pass, but new fragility** — F3's margin over `expectancy_r > 0` collapses from +0.0343 to **+0.0007**; a 4th-decimal sign change would take it to 3/4 (still ≥ 2 of 4, so gate 1 survives either way). All folds clear the 15-trade floor (`th.sensitivity_min_grid_trades`, `promotion.py:632` — note this is gate 5's constant, §4.3) |
| 2 | `min_oos_trades` | **OOS** | 319 | **262** (−17.9%) | pass; floor 30, margin 232 |
| 3 | `net_expectancy` | **OOS** | +0.3064R | **+0.3480R** (+0.0416R) | pass |
| 4 | `bootstrap_ci` | **OOS** | low **+0.1205R**; sd 1.7259; **required n = 140** | low **+0.1401R**; sd 1.7612; **required n = `(1.96 × 1.7612 / (0.3480 − 0.02))² = 111`** against 262 available | pass; hurdle falls because the point estimate rises faster than √n falls. *Standing caveat (`clustered_bootstrap_all.md`): a calendar-month block bootstrap widens every OOS CI in this program by ≈1.6×; at that haircut SR-1's low ≈ +0.02R and gate 4 becomes marginal. Report the clustered CI alongside (permitted under R4).* |
| 5 | `parameter_sensitivity` | OOS per grid point | 9/9 positive (100% / 100% neighbours) on `sma_fast` × `stop_atr` | on the **same 2 axes** with the filter on: 9/9 positive, min +0.0728R, min cell 243 OOS trades → 100% / 100%. With the mandatory third axis (§6) the grid is 27 points | pass forecast; see §6 for the axis that must be added and the `_replace` hazard |
| 6 | `regime_coverage` | ALL pre-sealed | bull 857 / **bear 22** / range 69; **unbucketed 123 (11.5%)**, of which no-proxy-bar **0** | bull 705 / **bear 13** / range 58; **unbucketed 95 (10.9%)**, no-proxy-bar **0** | **pass with 3 trades of margin** — this is the proposal's most serious gate cost. Bear margin over the floor of 10 falls **12 → 3**. At `max_run_up_atr = 1.5` the bear bucket is **11** (margin 1) |
| 7 | `benchmark_comparison` | ALL pre-sealed (per code, not docstring — §0.2) | Sharpe **+1.1560** vs SPY +0.7190; CAGR +10.15%, maxDD 28.45%, turnover 120.5/yr | Sharpe **+1.1900** vs SPY +0.7190; CAGR +10.42%, maxDD **24.38%**, turnover **98.0/yr** | pass, improved; margin 0.437 → 0.471 |
| 8 | `data_quality_and_leakage` | — | pass (snapshot 3 only) | pass — unchanged; the new feature adds no data source | no change |
| 9 | `sealed_final_test` | sealed year | −0.0294R / 95 (snap 3); +0.0109R / 98 (snaps 1/2/4) | **unforecastable — R1 forbids predicting or targeting it** | this is the only gate v3 fails, and this proposal cannot address it |
| 10 | `live_paper_probation` | — | pass | pass | no change |

### 5.2 The other three snapshots (SR-1, measured)

| snapshot | pre-sealed n | OOS n | OOS exp | CI low | required n (gate 4) | bull / bear / range | unbucketed | Sharpe vs SPY |
|---|---|---|---|---|---|---|---|---|
| 1 | 1,091 → **885** | 326 → **268** | +0.2936 → **+0.3394** | +0.1026 → **+0.1415** | 151 → **115** | 874/**23**/71 → 718/**13**/59 | 123 → **95** | +1.2160 → **+1.2590** |
| 2 | 1,091 → **885** | 326 → **268** | +0.2936 → **+0.3394** | +0.1026 → **+0.1415** | 151 → **115** | 874/**23**/71 → 718/**13**/59 | 123 → **95** | +1.2160 → **+1.2590** |
| 3 | 1,071 → **871** | 319 → **262** | +0.3064 → **+0.3480** | +0.1205 → **+0.1401** | 140 → **111** | 857/**22**/69 → 705/**13**/58 | 123 → **95** | +1.1560 → **+1.1900** |
| 4 | 1,112 → **901** | 336 → **273** | +0.3169 → **+0.3694** | +0.1331 → **+0.1583** | 129 → **97** | 889/**23**/72 → 730/**13**/59 | 128 → **99** | +1.1960 → **+1.2000** |

The bear bucket lands on **13 on every snapshot**, three above the floor. Note that
gates 1–8 can only actually *run* on snapshot 3, because gate 8 fails on snapshots
1, 2 and 4 for every version (§0.1); the other three rows are diagnostic.

### 5.3 Zero-margin cases §4.2 item 5 requires naming

- **Created by this proposal:** gate 6 bear = **13** (floor 10) on all four
  snapshots; walk-forward fold F3 = **+0.0007R** (threshold `> 0`).
- **v6's gate-5 neighbour fraction — exactly 0.750 on snapshot 3, already 0.500
  (FAIL) on snapshot 4.** Unaffected by this proposal: `_sensitivity_plan` dispatches
  on `key.startswith("volatility_breakout")` (`promotion.py:199-208`), a different
  branch. **But see §6** — the `trend_continuation` branch is shared with v2.
- **v5's bear bucket = 11 against a floor of 10.** Unaffected: v5 is
  `relative_strength.medium_swing`, a different strategy, different grid branch, and
  this change registers a new version rather than mutating any existing one.
- **v2 (PAPER_APPROVED, live) must be verified untouched:** its `spec_json_hash` is
  computed from `TrendContinuation(Horizon.SHORT_SWING).spec()`. Adding two
  **defaulted** `TrendParams` fields changes `dataclasses.asdict(params)` and hence
  anything that hashes the params. **Pre-integration check (mandatory):** compute
  `research.persistence.spec_json_hash(TrendContinuation(Horizon.SHORT_SWING).spec())`
  before and after the change and confirm it is byte-identical to the
  `spec_json_hash` stored on passing evaluations **20 and 32**; if it differs, v2's
  live approval scope breaks (`approval_scope.py:88-93`) and the change must be
  reshaped (e.g. by putting the new fields on a separate params subclass used only by
  the v0.2.0 instance). Do the same for v5 via evaluations 23 and 35, and re-record
  the R7b `scopes[0]` state.

---

## 6. Sensitivity-grid plan (hard requirement)

**Pre-registered new axis, fixed before any result was seen:**

```python
"max_run_up_atr": [1.5, 2.0, 2.5]
```

with `2.0` as the baseline (the middle value, so both neighbours exist and the
neighbour test is symmetric). `run_lookback` is **not** made an axis: it is fixed at
5 and never varied, so it cannot be tuned; if a future variant varies it, it becomes
an axis at that point.

**Grid size.** The `trend_continuation` grid becomes
`sma_fast [15,20,25] × stop_atr [1.2,1.5,1.8] × max_run_up_atr [1.5,2.0,2.5]` =
**27 points**, comfortably under `MAX_GRID_POINTS = 120` (`sensitivity.py:29`).
Runtime rises ~3× for this strategy's gate 5.

**The no-op check §4.2 item 6 demands — performed, and passed.** A retained-but-unused
field makes all grid points identical and gate 5 passes at 100% having tested nothing
(§2.1). Measured on snapshot 3, varying **only** the new axis at baseline
`sma_fast`/`stop_atr`:

| `max_run_up_atr` | pre-sealed trades | OOS trades | OOS expectancy |
|---|---|---|---|
| 1.5 | **774** | **237** | **+0.3589** |
| 2.0 | **871** | **262** | **+0.3480** |
| 2.5 | **958** | **288** | **+0.3041** |

Trade count and expectancy both move materially at every step, so the axis is live,
not a no-op. Every cell clears the 15-trade floor by more than 15×. And the existing
two axes, re-measured with the filter on (snapshot 3, OOS):

| | `stop_atr` 1.2 | 1.5 | 1.8 |
|---|---|---|---|
| `sma_fast` 15 | +0.0728 (n=257) | +0.2911 (248) | +0.1975 (243) |
| **20** | +0.1338 (272) | **+0.3480 (262)** | +0.2524 (255) |
| 25 | +0.0939 (279) | +0.3004 (268) | +0.2150 (259) |

9/9 positive, all evaluable → `positive_fraction = 1.00`, `neighbour_positive_fraction
= 1.00`.

**The `_sensitivity_plan` hazard this axis creates — must be solved before merge.**
FACT: `promotion.py:176-187` dispatches on `key.startswith("trend_continuation")`, so
**one grid serves both `trend_continuation.short_swing` (v2, live) and
`medium_swing`**. FACT: `promotion.py:50` imports `dataclasses.replace as _replace`
and `_replace(base, **p)` raises `TypeError` on an unknown field. If v2 keeps a
`TrendParams` without `max_run_up_atr`, adding the axis to the shared branch makes
**v2's gate 5 crash** on any future re-evaluation. Two acceptable resolutions, both
R4-permitted because they make gate 5 more searching and never easier:

1. Give `TrendParams` the new fields (as in §2.1) so `_replace` succeeds for both
   versions, **and** branch the grid on the resolved version so v0.1.0 keeps its
   2-axis grid and only v0.2.0 gets the third axis; or
2. dispatch `_sensitivity_plan` on `spec.versioned_key` rather than the key prefix.

Option 2 is the cleaner fix but touches the dispatch for all four families; option 1
is narrower. Either way the choice must be made explicitly and the before/after
gate-5 evidence for **v2** recorded, since v2 is live.

---

## 7. Leakage argument

- **The new feature is point-in-time by construction.** `run_up_atr(series, t, 5, 14)`
  reads `series.close[t]`, `series.close[t-5]` and `atr(series, t, 14)`; `atr` reads
  `true_range` over `[t-13, t]` (`features/daily.py:47-51`; `true_range` :39-45), which reaches back to
  `close[t-14]`. Maximum index touched is **t**. It matches the module contract
  stated at `features/daily.py:1-5` and the existing `(series, t)` shape exactly.
- **The engine enforces it structurally.** `run_backtest` calls
  `signal_fn(series.head(t), t)` (`engine.py:102`), so bars after `t` are not merely
  unused — they are **not present** in the object the strategy sees. A feature that
  tried to read `t+1` would raise, not silently leak.
- **The entry is still filled at the next bar's open** (`engine.py:108-110`), so the
  filter changes *which* signals fire, never *when* they fill.
- **No new data source, no cross-sectional term, no `StrategyContext` change.** The
  filter is symbol-local. `base.py:15-19` is untouched, so this is **not** a
  shared-surface change of the kind §4.2 item 7 flags (unlike v4's breadth lever).
- **Coverage:** `run_up_atr` must be added to the feature list exercised by
  `backtest/leakage.py:assert_no_lookahead` (`:23-41`), and the v0.2.0 strategy
  instance must appear in whatever test enumerates strategies for the leakage
  self-check, so gate 8's `leakage self-check: clean` line covers the new rule.
- **Walk-forward assumption preserved.** `walkforward.py`'s docstring notes the
  folds do not re-fit per fold, which is correct only while strategies fit nothing.
  `max_run_up_atr = 2.0` is a **frozen constant in the spec**, not an estimated
  quantity, so nothing is fitted per fold and the assumption still holds. (A version
  that set the threshold to a rolling percentile of the symbol's own history *would*
  break it, and is therefore explicitly out of scope.)

---

## 8. Cost-model statement (quantitative)

**The cost model is unchanged** (R4): `CostModel()` defaults — `commission_per_share
= 0.0`, `commission_min_per_order = 0.0`, `slippage_bps = 3.0`,
`half_spread_fill_penalty = True` (`costs.py:11-16`) — with `run_backtest`'s
`spread_bps = 5.0` default (`engine.py:90`), giving `slip = (3.0 + 2.5)/10,000` and
`costs_bps = 11.0` per round trip (`engine.py:94, 144`). Every run in this document
used exactly that, and `backtest_runner.py:205-206` still passes no `spread_bps`.

**Per-trade cost in R, measured rather than assumed.** §0.4 quotes 0.037R for the
trend family at a *reference* ATR/price of 2%. The **measured** ATR/price at v3's
snapshot-3 pre-sealed entries is median **1.287%** (mean 1.487%, p25 0.980%, p75
1.759%), which is materially tighter than the reference. Using
`round_trip_bps/10,000 ÷ (stop_atr × ATR/price)`:

| | risk / price | cost @ 11.0 bps (today) | @ 26 bps (2× spread) | @ 66 bps (5× spread) |
|---|---|---|---|---|
| §0.4 reference (ATR/price 2%) | 3.00% | 0.037R | 0.087R | 0.220R |
| **v3 measured, all entries (median)** | **1.931%** | **0.0570R** | **0.1347R** | **0.3418R** |
| **v3 measured, SR-1 retained entries (median)** | **1.887%** | **0.0583R** | **0.1379R** | **0.3499R** |

So today's realistic per-trade cost for this strategy is **≈0.057R, about 1.5× the
map's reference figure** — worth carrying back into §0.4. It is **19% of v3's
snapshot-3 OOS expectancy** and, as §2.1 already notes, larger than the entire
snapshot-3 sealed shortfall.

**Turnover and cost delta.**

| | v0.1.0 | SR-1 | delta |
|---|---|---|---|
| pre-sealed trades (snap 3) | 1,071 | 871 | **−18.7%** |
| turnover (gate-7 portfolio metric) | 120.5 /yr | 98.0 /yr | **−18.7%** |
| per-trade cost (median) | 0.0570R | 0.0583R | **+0.0013R** (+2.3%) |
| aggregate modelled cost, pre-sealed | ≈61.0R | ≈50.8R | **−10.2R (−16.8%)** |

The filter is **cost-neutral per trade** — it does not select systematically
lower-ATR names — and reduces aggregate cost roughly in proportion to the trade
count. Costs are therefore not an argument against SR-1; they are also not an
argument for it, since the per-trade edge, not the cost, is what fails to clear the
bar.

**Expanded-snapshot requirement (§4.2 item 8).** This proposal targets snapshot 3
only and does **not** require W1. If SR-1 were ever run on an expanded snapshot, the
2× and 5× spread rows above are the mandatory companions, and at 5× the cost
(0.35R/trade) exceeds the whole measured OOS expectancy of either version — a
decisive result that must be reported, not buried.

---

## 9. Variant budget and stopping rule

**Budget for this angle: 1 variant.** SR-1 at `max_run_up_atr = 2.0`,
`run_lookback = 5`, on snapshot 3. That is the entire signal-quality/regime budget
for v3, and it is now spent — on a diagnostic that returned a negative answer.

**What has been consumed so far, disclosed in full under R5:**

- **15 conditioning variables screened** (§3.3), each on 4 snapshots × 2 cuts, all
  read-only, none creating a sealed test or a `StrategyVersion` row.
- **3 threshold values** of the surviving conditioner re-run end to end (1.5 / 2.0 /
  2.5) — these are the pre-registered grid axis, not separate variants.
- **9 grid points** of `sma_fast × stop_atr` re-run with the filter on, to forecast
  gate 5.
- **0 strategy versions created, 0 sealed tests created, 0 promotion evaluations run.**

**Stopping rule (pre-registered, and already triggered):** the angle stops the first
time a screened conditioner fails **K1 or K2** — i.e. fails to reach a 2 SE contrast
on any snapshot on either cut. SR-1 failed both. **No second threshold, no second
lookback, no combination filter, and no re-screen on a different cut point will be
proposed by this angle.** Specifically ruled out in advance so they cannot be reached
for later: combining the run-up filter with the SMA20-extension filter (measured at
+0.0476R OOS delta, worse than the run-up filter alone — a hint that the two are the
same effect measured twice); moving the threshold to a percentile of the symbol's own
history (breaks the no-fitting property, §7); and reviving any of the four
conditioners that reversed sign out of sample (§3.3).

**Program-level count if the operator overrides.** v3's three proposals (null, exits
& risk, signal quality/regime) would then have tried **1** rule-set variant in total.
That is the number the final report must state verbatim.

---

## 10. Sealed-look accounting

**Baseline count: k = 5.** Four locked sealed tests already exist for version 3, one
per snapshot, plus the map's convention that a v0.2.0 sealing on snapshot 3 is the
fifth look at that calendar year for this strategy family. Reproduced from §0.1
(queried, `strategy_sealed_test`; 20 rows, exactly 4 per version for versions 2–6):

| Ver | Strategy | snap 1 `universe_25_baseline_legacy` | snap 2 `universe_25_baseline` | snap 3 `universe_24_ex_meta` | snap 4 `universe_25_meta_continuity_corrected` |
|---|---|---|---|---|---|
| 2 | `trend_continuation.short_swing` | id 1: **+0.3246R / 112** ✅ | id 6: **+0.3246R / 112** ✅ | id 11: **+0.2982R / 109** ✅ | id 16: **+0.3246R / 112** ✅ |
| 3 | `trend_continuation.medium_swing` | id 2: **+0.0109R / 98** ✅ | id 7: **+0.0109R / 98** ✅ | id 12: **−0.0294R / 95** ❌ | id 17: **+0.0109R / 98** ✅ |
| 4 | `mean_reversion.short_swing` | id 3: +0.1230R / 91 ✅ | id 8: +0.1230R / 91 ✅ | id 13: +0.1278R / 84 ✅ | id 18: +0.1230R / 91 ✅ |
| 5 | `relative_strength.medium_swing` | id 4: +0.2935R / 16 ✅ | id 9: +0.2935R / 16 ✅ | id 14: +0.2935R / 16 ✅ | id 19: +0.2935R / 16 ✅ |
| 6 | `volatility_breakout.short_swing` | id 5: −0.0979R / 10 ❌ | id 10: −0.0979R / 10 ❌ | id 15: −0.0979R / 10 ❌ | id 20: −0.0979R / 10 ❌ |

(Re-verified read-only against `strategy_sealed_test` while preparing this proposal:
20 rows, ids and values exactly as above.)

**What implementing SR-1 would cost.** `StrategySealedTest` is unique per
`(strategy_version_id, dataset_snapshot_id)` (`db/models/research.py:263`), and
`_get_or_create_sealed_test` (`promotion.py:377-384`) reads before recomputing, so a
repeat call returns identical locked numbers. Creating
`trend_continuation.medium_swing@0.2.0` creates a **new `StrategyVersion` row**, hence
a **never-before-sealed** gate 9:

- v0.2.0 evaluated on snapshot 3 → **look 6**.
- If it were also evaluated on an expanded snapshot (not proposed here) → looks
  **6 and 7**.
- Evaluating even the **unchanged** v0.1.0 against a new snapshot would also create a
  fresh sealed test, taking every version to k = 6 — an argument for building any new
  snapshot once, and a reason not to spend look 6 on a 1.8 SE effect.

**Pre-registered reporting snapshot (R1).** The report will lead with **snapshot 3**,
because it is the **only** snapshot on which gate 8 `data_quality_and_leakage` passes
for any version (snaps 1/2: `META` has 90 missing sessions, 6.9%; snap 4:
`META_CONT` carries source `continuity_bridge:1`, not `massive`). All four sealed
results will be disclosed alongside it in every table, and any pass will be reported
as **"passed on look 6"**, never as an unqualified pass. This choice is recorded here,
before any run, exactly as R1 requires.

**Sealed-look accounting for the recommended path (§11): zero.** The null option
creates no `StrategyVersion`, runs no promotion evaluation and therefore creates **no
new sealed test**. The count stays at **k = 5**.

---

## 11. Null option — and it is the recommendation

**What is written instead:** `docs/research/results/trend_continuation_medium_swing--does_not_pass.md`,
an honest, evidence-backed "does not pass on snapshot 3", carrying:

1. **The precise gate statement.** v3 passes gates 0–8 and 10 on snapshot 3 with
   margins *better* than the approved v2 on gates 3, 4 and 7 (+0.3064R vs +0.2648R;
   CI low +0.1205 vs +0.1129; Sharpe 1.156 vs 0.807). It fails **gate 9 only**, on
   **one of four** snapshots.
2. **The §0.1 ledger in full**, with v3's four sealed draws: +0.0109R/98 on snapshots
   1, 2 and 4 (pass) and −0.0294R/95 on snapshot 3 (fail). The entire difference is
   the removal of META: 98 − 95 = **3 trades** worth **+3.86R**.
3. **The power arithmetic.** The snapshot-3 sealed mean is **−0.16 SE** from zero
   (SE = 0.179 at n = 95) and −1.65σ (two-sample) to −1.88σ (pre-sealed mean treated
   as known) below its own pre-sealed estimate; `P(sealed mean < 0 | pre-sealed
   estimate, n = 95) = 4.3%`. The failure is a coin-flip-scale outcome, mildly
   disappointing against the pre-sealed estimate and statistically indistinguishable
   from zero.
4. **The measured cost correction from §8:** ≈0.057R per trade at the measured median
   ATR/price of 1.287% — nearly **twice** the 0.0294R sealed shortfall. The gap that
   fails gate 9 is smaller than half a round trip.
5. **What was investigated and ruled out**, which is the part that makes the
   "does not pass" credible rather than resigned:
   - H1 (duration mismatch) and H2 (target unreachable) — falsified on all four
     snapshots (`v3_duration_exits.md`); the long-duration buckets are v3's *most*
     profitable and the 40-bar leash **adds** +0.18R ± 0.08 per affected trade.
   - H3 (stale volatility scale) — not supported; ATR@exit/ATR@entry median
     1.0565 ± 0.0047, indistinguishable from the v2 control (`v3_atr_at_exit.md`).
   - H4 (volume-confirmation decay) — falsified here: largest contrast 0.33 SE (§3.2).
   - H5 (short-side asymmetry) — falsified: zero short trades exist under the gates.
   - H14 (regime conditioning) — impossible: the inherited `not risk_off` gate has
     already removed every bear and high-vol session; 0 of 1,071 trades remain to
     filter (§3.1).
   - H13 (entry over-extension) — the best surviving candidate, at **1.65–1.97 SE**,
     below the program's own evidence bar, with its mechanism signature absent (§3.4)
     and two new zero-margin gates as its price (§5).
   - Four further conditioners that clear 2 SE **in sample and reverse out of
     sample** (§3.3) — recorded explicitly, because they are exactly the changes an
     unrigorous version of this program would have shipped.
6. **The disposition argument, marked as sealed-informed under R1.** Deciding *not to
   change anything* is a disposition decision, and R1 permits sealed numbers to inform
   it. The sealed evidence says the miss is 3 trades and 0.16 SE; the pre-sealed
   evidence says there is no defect to fix; the multiple-testing arithmetic says a
   1.8 SE effect selected from 15 screened conditioners is likely to be noise. Every
   one of those points to leaving v3 alone.
7. **The standing disclosures:** the clustered-bootstrap haircut (`clustered_bootstrap_all.md`
   — under month-block resampling **both** currently PAPER_APPROVED strategies fail
   gate 4's +0.02R lower bound); gate 7's docstring/code divergence; gate 6's 123
   unbucketed trades (11.5%, entirely `label_regimes` warmup, no-proxy-bar = 0); and
   the fact that v3's profile is *stronger* than a live-approved strategy's on three
   gates while remaining EXPERIMENTAL.

**Cost of the null option:** zero API calls, zero database writes, zero code change,
**zero sealed looks** — k stays at 5 — and v0.1.0's four locked sealed tests stay
exactly as they are.

**What would reopen the question.** Not a better filter. Either (a) live paper
evidence, under R8, that contradicts or confirms the pre-sealed picture for the
*approved* trend strategy v2 — which shares v3's entire rule set apart from
`time_stop_bars` — or (b) an expanded, pre-registered universe (W1) on which v3's
pre-sealed estimate can be re-measured with genuinely more independent information,
noting that such a run creates a fresh sealed test and takes the count to k = 6, and
that `w1_universe_preregistration.md` has already pre-registered a v6 re-run there.
Neither is a signal-quality change, and neither is proposed here.

---

## Appendix A — files, symbols and line references used

| Purpose | Location |
|---|---|
| Strategy under study | `src/signalforge/research/strategies/trend_continuation.py` (`VERSION` :17, `TrendParams` :20-29, horizon branch :37-39, `spec()` :42-83, `evaluate()` :85-133) |
| Feature module (new feature's home) | `src/signalforge/research/features/daily.py` (contract :1-5, `atr` :47-51, `true_range` :39-45) |
| Strategy registration | `src/signalforge/research/strategies/__init__.py:43-51`; `src/signalforge/research/registry.py:85-96` |
| Gate ladder | `src/signalforge/research/promotion.py` (span :549-557, gate 1 :606-649, gates 2-4 :651-689, gate 5 :691-731, gate 6 :739-763, gate 7 :765-790, verdict :922) |
| Sensitivity grid | `src/signalforge/research/promotion.py:161-210`; `src/signalforge/research/sensitivity.py` (`MAX_GRID_POINTS` :29, `_is_neighbour` :100-112, expansion :134-137, verdicts :176-205) |
| Engine and costs | `src/signalforge/backtest/engine.py` (`run_backtest` :85, slip :94, next-bar fill :108-110, head(t) :102, `costs_bps` :144, `_resolve_exit` :154-179); `src/signalforge/backtest/costs.py:11-16` |
| Regime labellers (the two of §4.3) | `src/signalforge/research/regime.py` (`risk_off` :41-42, `regime_from_proxy` :62-93); `src/signalforge/backtest/regime.py:25` (`label_regimes`, used by gate 6) |
| Approval-scope safety | `src/signalforge/research/approval_scope.py` (`scan_scope_matches` :69-94, `current_spec_json_hash` :97-121); consumers `paper/ledger.py:387, 509`, `alerts/dispatch.py:277` |
| Leakage check | `src/signalforge/backtest/leakage.py:23-41` |
| Prior diagnostics relied on | `docs/research/diagnostics/v3_duration_exits.md`, `v3_atr_at_exit.md`, `clustered_bootstrap_all.md`, `pipeline_hardening_spec.md`, `w1_universe_preregistration.md` |

## Appendix B — reproduction

The harness is deliberately outside the repo (scratchpad only; §0 rules forbid
writing anywhere but this file). To reproduce: instantiate
`TrendContinuation(Horizon.MEDIUM_SWING, TrendParams(time_stop_bars=40))`, wrap
`signal_fn_for(...)` in a function that returns `None` when
`(close[t] − close[t−5]) / atr(series, t, 14) > threshold`, and drive
`run_backtest(series, fn, cost_model=None, warmup=30)` per symbol over the spans in
§0, splitting IS/OOS at 60% of each symbol's own bar count
(`backtest_runner.py:29, 158-160`). Gate-6 buckets come from
`backtest.regime.label_regimes(proxy)` keyed on `SimTrade.entry_date`; gate 7 from
`research.portfolio_metrics.compute_portfolio_metrics(all_trades, span_start, span_end)`
against `promotion._benchmark_metrics(proxy, …)` over the proxy's matched dates. The
baseline reproduction table in §0 is the check that the harness matches the gates.

*Read-only: no strategy code, no configuration, no database row and no gate threshold
was changed in producing this proposal. Every number is a measured result from a
read-only in-process run, a `SELECT`, or a `file:line` citation.*
