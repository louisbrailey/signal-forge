# Proposal — `volatility_breakout.short_swing` v0.2.0, SIGNAL-QUALITY / MECHANISM angle

**Strategy:** `volatility_breakout.short_swing` v0.1.0 (`StrategyVersion` id **6**), status
EXPERIMENTAL, latest evaluation **id 36** on dataset snapshot **3** (`universe_24_ex_meta`).
**Angle:** signal quality / mechanism — a change intended to move the **point estimate**, which
`STRATEGY_COMPLETION_MAP.md` §0.3 and `diagnostics/v6_regime_power.md` §5 both identify as the
only thing that can clear gate 4. **Co-primary with** the universe/power proposal (which *is*
W1, `diagnostics/w1_universe_preregistration.md`).

**Standing caveat, stated first because it governs everything below.** v6's out-of-sample
sample today is **n = 51 with SE = 0.2176R** (MAP §0.3). No change to this rule set can be
*evaluated* on that sample: the smallest effect worth caring about (roughly +0.13R, the gap
between the observed +0.0613R and something that would matter) is **0.6 SE**. Every
outcome number in this proposal is therefore **pre-registered for the W1 expanded snapshot
`research_150_massive_10y_2026-09-08` and for that snapshot only**. Nothing here was
motivated by, and nothing here may be re-tuned against, an expectancy measured on snapshots
1–4.

**Discipline actually applied while writing this (auditable).** The diagnostics below compute
**mechanical properties, entry counts, composition and cost** for the proposed rule on all
four snapshots. They deliberately **never compute, print, inspect or record the proposed
rule's P&L, expectancy, hit rate or any R statistic** on any snapshot. The scripts are the
record; every printed line is a count, a ratio, a bar-level feature statistic, or a cost. See
§3.6.

Claim labelling: **FACT** = verified by `file:line` or by a computation run for this document
(method and provenance in §3.0). **DERIVED** = arithmetic on FACTs, derivation shown.
**HYPOTHESIS** = an inference a later phase must test. **A difference under 2 SE is not
evidence** and is labelled as such everywhere it appears.

---

## 1. Mechanism

**The hypothesis, in the form §2 of the map uses.**

> **H13 (same-bar squeeze/break conjunction is self-defeating).** v6 requires
> `ATR(10)/ATR(50) ≤ 0.75` **on the same bar** as the Donchian break (`breakout.py:92,98`).
> `ATR(10)` at bar *t* includes `true_range(t)` — the breakout bar's own range — with weight
> 1/10 (`features/daily.py:46-50`). A breakout bar with a large range therefore *raises* the
> very ratio the filter caps. The conjunction does not select "a stock that was coiled and
> has now broken out"; it selects "a stock that is breaking out **feebly**". The strategy's
> own spec already names this failure mode — *"contraction filter admits low-volume drift
> that fails to follow through"* (`breakout.py:80`) — but attributes it to the filter's
> threshold rather than to its **timing**. The premise of a volatility-contraction breakout
> is *coiled, then released*; the code encodes *coiled while releasing*, which is
> arithmetically close to *coiled instead of releasing*.

This is the map's own §2.3 lever 3, stated as a testable mechanism: *"is the squeeze best
measured at the breakout bar, or in the window preceding it — a coiled-then-released framing
rather than coiled-and-releasing-simultaneously"*. The map calls it "the only class of change
that can move the **point estimate**, which §0.3 shows is what gate 4 actually needs".

**Why it should work in markets, not merely in the backtest.** A range contraction is
information about *stored* potential — a supply/demand balance narrowing until one side gives
way. The information is in the *contraction that preceded* the break. What confirms that the
balance actually broke is the **energy of the break bar itself**: a wide-range close through a
20-day high is an imbalance being resolved; a narrow-range close a few cents through the same
high is drift into a stale level, indistinguishable from noise and, for a 1.75×ATR stop
measured on a *contracted* ATR, indistinguishable from a stop that is already inside the
noise band. Requiring the squeeze **before** the break and expansion **at** the break separates
those two populations. The current rule does the opposite: it prefers the second.

**Relation to the existing hypothesis set.** H10 (power) and H11 (edge magnitude) are
addressed by W1 and by this proposal respectively; H12 is refuted and replaced by
`diagnostics/v6_regime_power.md`, which found the bear-bucket zero is a property of the
inherited `not ctx.regime.risk_off` conjunct, **not** of the contraction rule. H13 is
independent of all three: it concerns which *breakouts* are selected, not how many days are
open for trading. This proposal deliberately does **not** touch the `risk_off` conjunct —
that is a breadth/availability lever belonging to the universe/power angle, and mixing it in
would make the result uninterpretable and would cost a second variant (R5).

---

## 2. Exact change

**File:** `src/signalforge/research/strategies/breakout.py`.
**New behaviour ships as `VERSION = "0.2.0"` (R3/R7); v0.1.0 rows, sealed tests and the
`spec_json` of version id 6 are never mutated.**

### 2.1 `VERSION` (breakout.py:21)

```python
VERSION = "0.1.0"        # before
VERSION = "0.2.0"        # after
```

FACT (`research/persistence.py:78-90`): `upsert_strategy_version` matches on
`(strategy_id, version)`, so a bumped string creates a **new** `StrategyVersion` row and
leaves version id 6 untouched. FACT (`db/models/research.py:263`): `StrategySealedTest` is
unique per `(strategy_version_id, dataset_snapshot_id)`, so the new version has never been
sealed anywhere — R3's staleness trap cannot fire.

FACT and a consequence to accept explicitly: `VERSION` is a **module-level** constant, so
after the bump the `VolatilityBreakout` class can no longer construct a v0.1.0 spec. That is
acceptable here and only here, because FACT (`strategies/__init__.py:43-51`)
`default_strategies()` registers exactly one instance of this class
(`VolatilityBreakout(Horizon.SHORT_SWING)`), and FACT (MAP §0.1) version 6 is EXPERIMENTAL
with **no approved scope** — so nothing live reads its spec hash. R7's live-scope constraint
binds v2 and v5, which this change does not touch.

### 2.2 `BreakoutParams` (breakout.py:24-32) — two new fields, nothing removed, nothing retuned

```python
@dataclass(frozen=True, slots=True)
class BreakoutParams:
    channel: int = 20
    contraction_max: float = 0.75
    squeeze_lag: int = 5          # NEW — the squeeze is measured this many bars BEFORE the break
    release_min: float = 1.0      # NEW — break-bar true range, in units of ATR(50) at t-1
    atr_window: int = 14
    stop_atr: float = 1.75
    target_atr: float = 3.5
    time_stop_short: int = 10
    time_stop_medium: int = 40
```

Every pre-existing default is **unchanged**. `contraction_max` stays 0.75 — this proposal does
not loosen it, which MAP §2.3 lever 3 explicitly rules out as "buying quantity at the direct
expense of quality".

**Why `squeeze_lag = 5` and not 1, chosen on mechanism before any count was computed.**
`ATR(10)` evaluated at `t − 5` spans bars `t−14 … t−5`. It is disjoint from the break bar
*and* from the four-bar approach into it, which is where pre-break expansion typically begins;
`squeeze_lag = 1` removes only the break bar itself and leaves the approach inside the
measurement window. Five bars is half the `ATR(10)` window — the smallest lag that makes the
squeeze window and the "release" window non-overlapping in the intended sense. Lags 3 and 10
are the pre-registered grid neighbours (§6), not alternatives selected on results.

**Why `release_min = 1.0`.** "The break bar's true range is at least the average true range of
the last 50 sessions" is the natural zero-parameter statement of *release*: the bar is at least
an ordinary bar for this name, measured against the same 50-day baseline the contraction ratio
already uses as its denominator. It introduces no new scale and no new lookback. 0.8 and 1.2 are
the pre-registered grid neighbours.

### 2.3 `evaluate` (breakout.py:90-99) — three lines changed, two conditions added

```python
    def evaluate(self, series, t, ctx):
        p = self.params
-       contraction = atr_contraction(series, t, 10, 50)
+       contraction = atr_contraction(series, t - p.squeeze_lag, 10, 50)   # squeeze BEFORE the break
        dc_hi = donchian_high(series, t, p.channel)
        dc_lo = donchian_low(series, t, p.channel)
        a = atr(series, t, p.atr_window)
+       base = atr(series, t - 1, 50)                                       # release denominator
-       if any(math.isnan(x) for x in (contraction, dc_hi, dc_lo, a)) or a <= 0:
+       if any(math.isnan(x) for x in (contraction, dc_hi, dc_lo, a, base)) or a <= 0 or base <= 0:
            return None
        if contraction > p.contraction_max:
            return None
+       if true_range(series, t) / base < p.release_min:                    # release AT the break
+           return None
        close = float(series.close[t])
        ...  # long / short branches at :102-123 unchanged, byte for byte
```

Import line 16 gains `true_range` (already exported from `features/daily.py:38-43`). **No new
feature function is written**; the change composes three existing point-in-time primitives.

**Everything else is unchanged**: `channel`, `atr_window`, `stop_atr`, `target_atr`,
`time_stop_short/medium`, the `not ctx.regime.risk_off` long gate (`:102`), the
`ctx.allow_short … Trend.BEAR` short gate (`:113`), the stop/target arithmetic and the
`_time_stop()` branch. This is a **single-mechanism change** by design (R5).

### 2.4 `spec()` (breakout.py:49-88) — text only, generated from params

`rule_definition`, `feature_definitions` and `entry_conditions` must be updated to describe the
lagged squeeze and the release test, e.g.
`"contraction(t-squeeze_lag) <= contraction_max and TR(t) >= release_min * ATR(50, t-1) and close beyond the Donchian edge"`.
FACT (`persistence.py:32-44`): `spec_json` feeds `spec_json_hash`, which
`approval_scope.scan_scope_matches` (`approval_scope.py:89-92`) compares — but only for
**approved** versions, of which this strategy has none, so there is no live scope to disturb
(R7, R7b).

### 2.5 Other touchpoints

| File | Change | Rule |
|---|---|---|
| `research/promotion.py:199-208` | add `squeeze_lag` and `release_min` to the `volatility_breakout` grid (§6) | R4 carve-out: makes gate 5 **more** searching |
| `research/promotion.py:256-262` (`_leakage_self_check`) | add `atr_contraction(10,50)`, `atr_contraction` at a lag, `donchian_high(20)` and `true_range` to the checked list (§7) | R4 carve-out: makes gate 8 **more** searching |
| `research/strategies/__init__.py:43-51` | no edit required — the single registered instance picks up the new `VERSION` | R7 |
| `tests/` | new leakage + rule tests for the two conditions (implementer's task; out of scope for this document, which may not write under `tests/`) | — |

### 2.6 Implementation-correctness check that the change is exactly these two conditions

**FACT (computed for this document).** Running the proposed `evaluate` with the degenerate
parameters `squeeze_lag = 0, release_min = 0.0` reproduces v0.1.0's pre-sealed trade counts
**exactly, on all four snapshots**:

| snapshot | v0.1.0 pre-sealed / OOS (stored, evals 36/30/12/42) | degenerate v0.2.0 cell (recomputed) |
|---|---|---|
| 3 `universe_24_ex_meta` | **211 / 51** | **211 / 51** |
| 2 `universe_25_baseline` | **213 / 52** | **213 / 52** |
| 1 `universe_25_baseline_legacy` | 213 / 52 | **213 / 52** |
| 4 `universe_25_meta_continuity_corrected` | 219 / 53 | **219 / 53** |

So the v0.2.0 rule is a strict generalisation of v0.1.0 whose only behavioural difference is
the two new conditions. The implementer must add this as a unit test.

**Warm-up cost (FACT).** `atr_contraction(series, t-5, 10, 50)` requires `t ≥ 55` and
`atr(series, t-1, 50)` requires `t ≥ 51`, against v0.1.0's `t ≥ 50`. The engine's warmup is
`min_bars // 2 = 30` (`backtest_runner.py:206`), so v0.2.0 loses **5 candidate bars per symbol**
(≈120 of 53,196 symbol-bars on snapshot 3, 0.23%). At the `squeeze_lag = 10` grid point it is 10
bars per symbol. Negligible, but it is a real difference and is recorded here so it is not
mistaken later for an effect.

---

## 3. Pre-sealed evidence

### 3.0 Method and provenance

**FACT.** Every number in §3 was computed against a **read-only backup copy** of the live
database taken with the SQLite backup API over a `mode=ro` connection
(`sqlite3 "file:data/signalforge.sqlite?mode=ro" ".backup $TMPDIR/scratch-v6mech.sqlite"`,
2026-09-10, `pragma integrity_check` = ok), with `DATABASE_URL` pointed at the copy. **No
command in this work wrote to `data/signalforge.sqlite`**; no promotion, sensitivity or sealed
entry point was invoked; no provider API was called; no file under `src/` or `tests/` was
modified. The proposed rule was implemented as a throw-away class in a scratchpad script, never
in the repository.

Trades were reproduced with `backtest.engine.run_backtest` driven by
`research.strategies.base.signal_fn_for` and `research.regime.regime_lookup` — the same objects
`research.backtest_runner.run_strategy_over_universe` uses (`backtest_runner.py:167-215`), which
FACT contains no `session.add`/`flush`/`commit`. Cost model frozen at
`CostModel(0.0, 0.0, 3.0, half_spread_fill_penalty=True)` (`backtest/costs.py:11-16`),
`spread_bps` left at the engine default 5.0 (`engine.py:90`) exactly as
`backtest_runner.py:205-206` leaves it. IS/OOS split reproduced from
`backtest_runner.py:29,158-160` (`_TRAIN_FRAC = 0.6`, per symbol).

**Reproduction check (FACT).** v0.1.0 recomputes to **211 pre-sealed / 51 OOS** on snapshot 3
and **213 / 52** on snapshot 2, matching stored evaluations 36 and 30 exactly (and matching
`diagnostics/v6_regime_power.md` §1).

**Spans.** Pre-sealed only: snapshot 1 `2016-09-10 … 2025-09-06`; snapshots 2, 3, 4
`2016-09-10 … 2025-09-07` (derived from the *locked* sealed windows in `strategy_sealed_test`
ids 5/10/15/20 and `promotion.py:549-557`). Snapshot 4 loaded with sources
`("massive", "continuity_bridge:1")`, matching sealed test id 20's recorded provenance.
**Nothing inside 2025-09-08 → 2026-09-08 (2025-09-07 → 2026-09-07 on snapshot 1) was computed**,
including proxy regime labels (R1).

Definitions used throughout:

- **break bar** — a session `t` at which `close(t) > donchian_high(t, 20)`, `ATR(14, t)` is
  defined and positive, and the proxy regime on `t` is **not** `risk_off` (i.e. v6's long gate
  at `breakout.py:102` is open). This is the population v6 chooses from.
- **energy** `E(t) = true_range(t) / ATR(50, t−1)` — the break bar's range relative to the same
  50-day baseline the contraction ratio uses as its denominator, evaluated so that it shares no
  bar with the break itself.

### 3.1 The mechanical claim — the same-bar filter selects feeble breaks (26 SE, all four snapshots)

**FACT.** Mean energy of break bars, unfiltered vs after v0.1.0's same-bar contraction filter:

| snapshot | all break bars | after `contraction(t) ≤ 0.75` | difference | SE units |
|---|---|---|---|---|
| **3** | **1.1385 ± 0.0112** (n = 3,727) | **0.7184 ± 0.0116** (n = 494) | **−0.4201 ± 0.0161** | **26.1 SE** |
| 2 | 1.1468 ± 0.0117 (n = 3,792) | 0.7192 ± 0.0116 (n = 497) | −0.4276 ± 0.0165 | 26.0 SE |
| 1 | 1.1468 ± 0.0117 (n = 3,792) | 0.7192 ± 0.0116 (n = 497) | −0.4276 ± 0.0165 | 26.0 SE |
| 4 | 1.1513 ± 0.0116 (n = 3,869) | 0.7206 ± 0.0114 (n = 507) | −0.4307 ± 0.0163 | 26.5 SE |

**The typical breakout bar in this universe has a range 1.14× its own 50-day ATR. The bars
v0.1.0 actually trades have a range 0.72× — 37% smaller. The effect is identical on all four
snapshots and is 26 standard errors from zero.** This is not a marginal statistical claim; it
is a structural property of the conjunction, and the arithmetic behind it is elementary: with
`ATR(10)` averaging ten true ranges, a break bar at `2 × ATR(50)` contributes 0.20 to the ratio
by itself, forcing the other nine bars below `0.61 × ATR(50)` to keep the ratio under 0.75,
whereas a break bar at `0.5 × ATR(50)` only requires the other nine to average 0.78.

**FACT.** The proposed rule inverts this: bars satisfying `contraction(t−5) ≤ 0.75` **and**
`E ≥ 1.0` have mean energy **1.5751 ± 0.0659** (n = 175) on snapshot 3 (1.5659 ± 0.0646 on
snapshots 1/2; 1.5869 ± 0.0655 on snapshot 4).

**FACT — the two rules select nearly disjoint populations.** On snapshot 3, of 175 bars passing
the proposed rule and 494 passing v0.1.0's, only **32 pass both** — 18.3% of the proposed set
and 6.5% of the current set (18.4%/6.6% on snapshots 1 and 2; 17.9%/6.5% on snapshot 4). This
is **not** a filter applied on top of v0.1.0's trades; it is a different selection. Two
consequences: (i) "will the surviving trades still be profitable?" is the wrong question — 82%
of them are new; (ii) the two OOS samples on the W1 snapshot may be treated as approximately
independent when their difference is tested (§4).

**FACT — the lag alone, without the release test, already decouples the two conditions.**
Bars passing `contraction(t−5) ≤ 0.75` have mean energy **0.9505 ± 0.0274** (n = 571,
snapshot 3) against **0.7184 ± 0.0116** for the same-bar filter: **+0.2321 ± 0.0298, 7.8 SE**.
The lagged filter also admits **more** bars (571 vs 494, +15.6%), so it is not simply a
stricter test — it is a differently-timed one, which is the mechanism's claim.

### 3.2 The outcome gradient — directionally consistent on all four snapshots, and **under 2 SE everywhere**

This is the honest limit of what today's data can say, and it is stated before anything else it
might be used to justify.

**FACT.** v0.1.0's own 211 pre-sealed trades, split into terciles by their entry bar's energy
(per-trade R, mean ± SE):

| snapshot | T1 (low energy) | T2 | T3 (high energy) | **T3 − T1** | SE units |
|---|---|---|---|---|---|
| **3** | +0.1035 ± 0.1219 (n=71) | +0.1527 ± 0.1403 (n=70) | +0.2399 ± 0.1689 (n=70) | **+0.1364 ± 0.2083** | **0.65 SE** |
| 2 | +0.1035 ± 0.1219 (n=71) | +0.1361 ± 0.1393 (n=71) | +0.2295 ± 0.1669 (n=71) | +0.1261 ± 0.2067 | 0.61 SE |
| 1 | +0.1035 ± 0.1219 (n=71) | +0.1361 ± 0.1393 (n=71) | +0.2295 ± 0.1669 (n=71) | +0.1261 ± 0.2067 | 0.61 SE |
| 4 | +0.1228 ± 0.1197 (n=73) | +0.1225 ± 0.1364 (n=73) | +0.2382 ± 0.1653 (n=73) | +0.1154 ± 0.2041 | 0.57 SE |

Binary split at `E = 0.8` on snapshot 3: below **+0.1008 ± 0.0946** (n=134) vs above
**+0.2769 ± 0.1582** (n=77), difference **+0.1761 ± 0.1843 (0.96 SE)**.

**Verdict, stated plainly: this is NOT evidence.** Every comparison is under 1 SE. The sign is
the same on all four snapshots and in every cut, which is mildly encouraging and nothing more —
the four snapshots share ≥ 96% of their trades, so their agreement is close to one observation,
not four.

**And there is a structural reason the existing sample cannot do better, which is itself part
of the argument.** The same-bar filter **truncates the exact variable the mechanism is about**:
energy at v0.1.0's entries has mean 0.745 and sd 0.250, against 1.139 / 0.682 in the unfiltered
break population. The tercile contrast available inside v0.1.0's trades is a cut at 0.635 vs
0.819 — a span of 0.18 in a variable whose full range is ~3. **The current rule cannot measure
the gradient over the range the proposal would open up, because it never trades there.** That
is precisely why the proposal is pre-registered for a fresh, powered run rather than argued from
a within-sample split.

### 3.3 Trade counts under the proposed rule (counts only, all four snapshots)

**FACT** (recomputed; the P&L of these trades was never computed — §3.6):

| snapshot | v0.1.0 pre-sealed / OOS | **v0.2.0 baseline cell** pre-sealed / OOS | change |
|---|---|---|---|
| **3** | 211 / **51** | **132 / 32** | −37.4% / −37.3% |
| 2 | 213 / 52 | 136 / 34 | −36.2% / −34.6% |
| 1 | 213 / 52 | 136 / 34 | −36.2% / −34.6% |
| 4 | 219 / 53 | 141 / 36 | −35.6% / −32.1% |

**On snapshot 3 the proposal clears gate 2's floor of 30 by two trades.** That is a
zero-margin case in the same class as the two MAP §4.2 item 5 already names, and it is the
single strongest reason this proposal must not be run on snapshot 3 (§5, §9).

Entries by year (snapshot 3): 2017: 21, 2018: 7, 2019: 31, 2020: 22, 2021: 19, **2022: 0**,
2023: 15, 2024: 8, 2025: 9. The 2022 zero is unchanged and unchangeable by this proposal —
FACT (`diagnostics/v6_regime_power.md` §2.2): 2022 has **3 gate-open sessions out of 251**, a
property of the inherited `risk_off` conjunct that this change deliberately does not touch.

### 3.4 Composition — the proposed rule shifts the sample from index ETFs to single names

**FACT** (snapshot 3; ETFs = the 15 of `DIA, IWM, QQQ, SPY, XLB…XLY`, single names = the 9 of
`AAPL, AMZN, GOOGL, HD, JPM, MSFT, NVDA, UNH, XOM`):

| | ETF trades | single-name trades | ETF share | rate ratio **k** = (ETF/15) ÷ (CS/9) |
|---|---:|---:|---:|---:|
| v0.1.0 | 157 | 54 | 74.4% | **1.744 ± 0.275** |
| **v0.2.0** | **67** | **65** | **50.8%** | **0.618 ± 0.108** |

DERIVED: Δk = **−1.126 ± 0.296 (3.8 SE)** — above the 2 SE bar, so this one *is* evidence.
Mechanistically it is what H13 predicts: a diversified index rarely produces a wide-range
break, because its constituents' idiosyncratic moves net out. v0.1.0's preference for feeble
breaks is therefore also a preference for ETFs, and FACT
(`diagnostics/v6_regime_power.md` §4) SPY/QQQ/DIA/XLK alone supply **86 of 211 (40.8%)** of
v0.1.0's trades. Under v0.2.0 those four supply **27 of 132 (20.5%)**.

**This is the load-bearing consequence for W1, and it reverses a documented concern.**
W1 §4.3 raised, as a *risk*, the hypothesis that v6's signals are ETF-concentrated and that the
breadth multiplier for a 135-single-name expansion would therefore be well below the naive
6.25×. Using W1 §4.3's own formula `(15k + 135)/(15k + 9)`:

| rule | measured k | breadth multiplier to N = 150 | projected pre-sealed n | **projected OOS n** |
|---|---:|---:|---:|---:|
| v0.1.0 | 1.744 | **4.58×** | 967 | **234** |
| **v0.2.0** | **0.618** | **7.89×** | 1,042 | **253** |

**DERIVED, and it is the reason this proposal is compatible with W1 rather than in tension with
it: v0.2.0 cuts trade count by 37% on the current 24-symbol universe and still lands with
slightly MORE out-of-sample trades than v0.1.0 on the 150-symbol universe** (253 vs 234), because
the universe it is being expanded into is 90% single names. HYPOTHESIS (the multiplier is a
projection, not a measurement; §10 carries the caveat).

### 3.5 Cost — a correction to MAP §0.4, and a measured cost reduction

MAP §0.4 estimates `volatility_breakout`'s per-trade cost at **0.042R**, using an *assumed*
ATR/price of 1.5% chosen because the contraction filter selects a contracted ATR. The
assumption is right in direction and **too generous in magnitude**.

**FACT** (measured at the actual signal bars, snapshot 3, `ATR(14,t)/close(t)`):

| population | n | median ATR/price | mean cost in R at 11.0 bps round trip |
|---|---:|---:|---:|
| all gate-open break bars | 3,713 | 1.258% | 0.0540 ± 0.0004 R |
| **v0.1.0 entries** | 494 | **1.059%** | **0.0640 ± 0.0011 R** |
| **v0.2.0 entries** | 175 | **1.288%** | **0.0555 ± 0.0019 R** |

DERIVED, using `cost_R = (round_trip_bps/10,000) / (stop_atr × ATR/price)` with
`stop_atr = 1.75` and the round trip fixed at `2 × (3.0 + 5.0/2) = 11.0` bps
(`engine.py:94,143`):

1. **MAP §0.4 understates v6's cost by 52%.** The real figure at v0.1.0's own entries is
   **0.0640R**, not 0.042R. Against the observed OOS point estimate of **+0.0613R**, modelled
   transaction cost is **104%** of the entire net edge — v0.1.0's gross pre-cost expectancy is
   ≈ **+0.125R** and *all* of it is consumed by 11 bps. MAP §2.3's "0.042R of modelled cost sits
   inside it" and §0.4's "68% of its entire edge" should both read **104%**. This correction is
   independent of the proposal and should be carried into the strategy's final report either way.
2. **The proposal reduces cost in R by construction**, because a released break bar has a larger
   ATR and therefore a larger risk unit: **−0.0085 ± 0.0022 R per trade (3.9 SE)** on snapshot 3
   (−0.0091 ± 0.0022, 4.1 SE on snapshots 1/2; −0.0091 ± 0.0022, 4.3 SE on snapshot 4). This is a
   point-estimate contribution of about **+0.009R** that requires no edge claim at all.

Full cost table in §8.

### 3.6 What was deliberately NOT computed

No expectancy, hit rate, profit factor, Sharpe, R-multiple, equity curve or CI was computed for
the proposed rule on any snapshot. The counts-only script reads `SimTrade.entry_date` and
`SimTrade.symbol` and never `SimTrade.pnl_r`. The reason is not ceremony: at n ≈ 32 OOS the SE
is ≈ 0.27R, the number would be uninformative, and having seen it would make every subsequent
parameter choice a selection under R5. The pre-registration in §4 is worth exactly as much as
this abstention.

---

## 4. Falsification

Stated **before** the W1 run. R10 requires falsification conditions that hold across all four
snapshots; K1 and K2 are of that kind and have already been run on all four. K3 is the outcome
test and can only be run once, on W1.

### K1 — mechanical kill test (all four snapshots) — **RUN, SURVIVED**

> *If the same-bar contraction filter did not bias break-bar energy downward — i.e. if the mean
> energy of bars passing `contraction(t) ≤ 0.75` were within 2 SE of the unfiltered break-bar
> mean on any of the four snapshots — H13 would be false and this proposal would be withdrawn.*

Observed: **−0.4201 ± 0.0161 (26.1 SE)** on snapshot 3, and 26.0 / 26.0 / 26.5 SE on snapshots
2 / 1 / 4 (§3.1). **Survives on all four.**

### K2 — cost kill test (all four snapshots) — **RUN, SURVIVED**

> *If the released-break population did not carry a larger risk unit — i.e. if the per-trade
> modelled cost in R under the proposed rule were not lower than under v0.1.0 by at least 2 SE
> on all four snapshots — the cost half of the argument would be void.*

Observed: **−0.0085 ± 0.0022 R (3.9 SE)** on snapshot 3; 4.1 / 4.1 / 4.3 SE on snapshots 2 / 1 / 4
(§3.5). **Survives on all four.**

### K2b — count kill test (all four snapshots) — **RUN, SURVIVED, narrowly on snapshot 3**

> *If the proposed rule left fewer than 30 OOS trades on any of the four existing snapshots, it
> could not even be evaluated there, and the claim that it is a viable rule (as opposed to a
> rule that only exists on a 150-name universe) would fail.*

Observed: **32 / 34 / 34 / 36** OOS on snapshots 3 / 2 / 1 / 4 (§3.3). Survives, but by 2 trades
on snapshot 3 — recorded as a zero-margin case in §5.

### K3 — outcome kill test (W1 expanded snapshot only), pre-registered

Let `E₀₂` and `E₀₁` be the **pre-sealed OOS expectancy** of v0.2.0 and v0.1.0 on
`research_150_massive_10y_2026-09-08`, with their own bootstrap SEs from the same
`run_strategy_over_universe` call the gates use.

- **K3a — sign (hard kill).** If `E₀₂ ≤ E₀₁`, the mechanism is refuted. The proposal is
  withdrawn, no re-parameterisation is attempted, no second variant is run, and §11's null
  option is written.
- **K3b — magnitude (hard kill).** If `E₀₂ − E₀₁ < 1.0 SE` of the difference (SE computed as
  `√(SE₀₂² + SE₀₁²)`, justified as approximately independent by the 18%/6.5% overlap measured in
  §3.1), the mechanism is declared **unsupported at achievable power** and §11's null option is
  written. This is a criterion that can actually fire: at the projected n's it corresponds to a
  required improvement of about **+0.14R**.
- **K3c — the honest ceiling.** Even if K3a and K3b are passed, gate 4 is **still expected to
  fail** (§5). Passing K3 means "the mechanism is real and measured"; it does **not** mean
  "promote". Partial success is not to be reported as success.

**Why K3 cannot be run on snapshots 1–4, stated as a pre-registration and not as an excuse.**
At n ≈ 32 (v0.2.0) and n = 51 (v0.1.0) with per-trade sd ≈ 1.55, the SE of the difference is
`√(1.55²/32 + 1.55²/51)` = **0.35R**. K3b's ~+0.14R threshold is 0.4 SE at that sample size —
the test has essentially no power, and running it would produce a number whose only use would be
to justify re-tuning `squeeze_lag` or `release_min`, which R5 counts as variants and R1 would
not save from being selection.

### K4 — no-op kill test (pre-integration, mandatory before the gates are trusted)

> *If any of the four gate-5 axes fails to change the OOS trade count or the OOS expectancy, gate
> 5 is passing at 100% having tested nothing (MAP §2.1, §4.2 item 6) and the run is void.*

Pre-computed evidence that all four axes bite is in §6.3.

---

## 5. Gate-by-gate forecast

**Target: the W1 expanded snapshot `research_150_massive_10y_2026-09-08` only.** Trade sets are
tagged per MAP §0.2: gates 2/3/4 read `full.out_of_sample`; gates 1/6/7 read `full.trades` (all
pre-sealed, IS+OOS) — including gate 7, whose docstring says otherwise
(`config/research.py:111-113` vs `promotion.py:775`; MAP §0.2 open item).

Projections use the §3.4 multiplier **7.89×** for v0.2.0 (v0.1.0: 4.58×) and, where a dispersion
figure is needed, v0.1.0's per-trade sd of **1.554** (MAP §0.3; empirical 1.5242 per
`v6_regime_power.md` §3). HYPOTHESIS: v0.2.0's sd is unknown and could be higher — larger break
bars mean larger risk units, which is R-normalising, but single names bring gap risk that ETFs do
not (§10, caveat 3).

| # | Gate | Trade set | v0.1.0 on snap 3 today | **v0.2.0 forecast on W1** | Direction / at risk |
|---|---|---|---|---|---|
| 0 | `data_availability` | — | pass | **pass** | span ≥ 350 days is unaffected |
| 1 | `rolling_walkforward` | all pre-sealed | 4/4 folds clear (36 / 98 / 34 / 43) | **pass, high confidence**: ~1,042 pre-sealed trades, folds ≈ 220 / 460 / 175 / 190 | needs ≥ 2 of 4 with n ≥ 15 and exp > 0; counts are not the binding issue |
| 2 | `min_oos_trades` | **OOS** | 51 | **≈ 253** (pass) | **on snapshot 3 it would be 32 vs a floor of 30 — a zero-margin case (§3.3); on W1 it is comfortable** |
| 3 | `net_expectancy` | **OOS** | +0.0613R | **genuinely uncertain — no prediction offered** | pass at 11 bps requires only exp > 0; **expected to FAIL at 26 bps round trip** (§8) |
| **4** | `bootstrap_ci` | **OOS** | low −0.3553R, FAIL | **FAIL — predicted with high confidence** | see the required-n block below |
| 5 | `parameter_sensitivity` | OOS per cell | pass at 0.667 / **0.750 exactly**; **FAILS at 0.556 / 0.500 on snapshot 4** | **materially harder than today; no prediction offered** | grid goes 9 → 81 points and neighbours 4 → 8 (§6) |
| **6** | `regime_coverage` | all pre-sealed | bull 167 / **bear 0** / range 30; **14 unbucketed (6.6%)** | **bear bucket: λ ≈ 11.6–14.7, P(≥10) = 0.72–0.92; unbucketed ≈ 79 (7.6%)** | **worse than v0.1.0's λ ≈ 18.5 / P = 0.988** — this change reduces trade count and cannot help gate 6 |
| **7** | `benchmark_comparison` | all pre-sealed | Sharpe 0.666 vs SPY 0.719, FAIL | **FAIL expected; and this change makes it structurally harder** | see the Sharpe-scaling block below |
| 8 | `data_quality_and_leakage` | — | pass on snapshot 3 only | **pass, conditional on W1-COMPLETE** (W1 §6.4) | strengthened by the §7 additions |
| 9 | `sealed_final_test` | sealed year | −0.0979R / 10 trades, FAIL, identical on all 4 | **new sealed test; projected n ≈ 10 × 0.626 × 7.89 ≈ 49, SE ≈ 0.222R** | derived from the pre-sealed rate ratio only — v0.2.0's sealed-window trade count was **not** computed (R1). At that SE gate 9 still rejects a genuinely +0.30R rule ~9% of the time and a genuinely +0.06R rule ~39% of the time |
| 10 | `live_paper_probation` | — | pass | pass | `health_monitor.enabled` is on |

### Gate 4 stated as a required n (MAP §4.2 item 5, mandatory form)

`n > (1.96 · sd / (exp − 0.02))²` with sd = 1.554:

| assumed v0.2.0 OOS expectancy | required OOS n (iid) | required n under month-clustering (×2.68, `v6_regime_power.md` §6.1: ratio 1.638) | symbols at v0.2.0's measured rate |
|---:|---:|---:|---:|
| +0.0613R (= v0.1.0's, i.e. no improvement) | 5,426 | 14,540 | ≈ 3,200 / 8,600 |
| +0.10R | 1,449 | 3,883 | ≈ 860 / 2,300 |
| +0.15R | 549 | 1,471 | ≈ 325 / 870 |
| **+0.2115R** | **253** | 678 | **≈ 150 — the W1 universe** |
| +0.30R | 118 | 316 | ≈ 70 / 187 |
| +0.3336R | 94 | **252** | ≈ 56 / **150 under clustering** |

**Read this row-by-row and the forecast is unambiguous: at the projected n ≈ 253, gate 4 needs a
point estimate of +0.2115R — 3.45× v0.1.0's +0.0613R — and +0.3336R if the entry-month clustered
statistic is applied (a disclosure, not the gate).** The measured cost saving (§3.5) contributes
about +0.009R of that. The mechanism must supply the remaining ~+0.14R on its own. **The
pre-registered expectation is that it does not, and that gate 4 fails.** If gate 4 nevertheless
passes, the honest report is that the point estimate moved 3.5×, which itself demands an
explanation and should be treated with more suspicion than a failure.

### Gate 6 arithmetic (mandatory form: three buckets **and** the unbucketed count)

FACT (`v6_regime_power.md` §5.3): gate-open **bear** proxy sessions are fixed by the calendar and
the shared `risk_off` filter at **19 in nine years**; at 150 symbols there are ≈ **2,700**
gate-open bear symbol-days. v0.1.0's bull-bucket entry rate is 6.845 ± 0.530 per 1,000 gate-open
symbol-days → λ ≈ 18.5, P(≥10) = **0.988**.

DERIVED for v0.2.0: overall entry rate is 132/211 = **0.626×** v0.1.0's → λ ≈ **11.6**,
P(≥10) = **0.721**. Adjusting for the single-name tilt (the composition uplift 7.89/6.25 = 1.264,
and the expanded universe is 90% single names) → λ ≈ **14.7**, P(≥10) = **0.920**.

**Honest reading: this proposal makes gate 6 *less* likely to clear than the unchanged v0.1.0
would on the same expanded universe** (0.72–0.92 against 0.988). That is a real cost of the
change and it is on the record here. **CAVEAT, carried verbatim from `v6_regime_power.md` §5.3:**
all of this assumes the counterfactual "bear entry rate = bull entry rate", which the data can
neither support nor refute (0 bear entries in 432 gate-open bear symbol-days, 1.72 SE below the
2.96 expected — under 2 SE, therefore **not evidence**). A bear bucket under 10 on W1 would be a
**power** outcome and must not be reported as a strategy finding.

**Unbucketed count (FACT, required by MAP §0.6 / §4.2 item 5).** v0.1.0 has **14 of 211 (6.6%)**,
all in 2017-01-05 → 2017-07-25 inside the proxy's 200-session warmup and unlabelable with any
data in the database (`v6_regime_power.md` §3.1). v0.2.0 has **10 of 132 (7.6%)** on snapshot 3
(10/136 = 7.4% on snapshots 1 and 2; 11/141 = 7.8% on snapshot 4). On W1 the projected unbucketed
count is **≈ 79 of ~1,042 (7.6%)**, all warmup, all before 2017-08-03.

### Gate 7 — the change makes it structurally harder, quantified

FACT (eval 36 gate-7 evidence): v0.1.0 Sharpe **0.666** (CAGR +1.9%, vol 2.9%, maxDD 5.8%,
turnover **23.8/yr**, exposure **0.66**) vs SPY **0.719**.

DERIVED (HYPOTHESIS-grade approximation; `compute_portfolio_metrics` works on a daily equity
curve, not on `√n · E / sd`, so treat this as a direction with a magnitude, not an identity): for
a fixed per-trade sd, annualised return scales with `n · E` and annualised vol with `√n · sd`, so
Sharpe scales with `√n · E / sd`. On a fixed universe, cutting n by 37.4% cuts `√n` by **21.1%**,
so **E must rise by 26.4% merely to hold Sharpe constant**, and by
`(0.719/0.666)/0.789 = 1.368×` — i.e. to **≥ +0.0839R** — to reach SPY's Sharpe on snapshot 3's
span. On the W1 snapshot both v0.1.0 and v0.2.0 gain from breadth, but the *ratio* between them is
what this change controls, and it moves against gate 7.

Two further reasons gate 7 is expected to stay failed regardless: (i) MAP §3(a) — breadth does not
move a risk-adjusted point estimate; (ii) exposure falls with trade count, so the strategy is flat
more of the time while SPY is not.

### Zero-margin cases (MAP §4.2 item 5, mandatory)

1. **v0.1.0's gate-5 neighbour fraction is exactly 0.750 on snapshot 3** (`sensitivity.py:194`
   tests `nb_frac < min`, so 0.750 passes) **and already fails at 0.556 / 0.500 on snapshot 4**
   (eval 42). The 4-axis grid proposed in §6 changes the denominator from 4 neighbours to 8, so
   this margin does not carry over in either direction — it is a new test.
2. **v0.2.0 clears gate 2 on snapshot 3 by 2 trades (32 vs 30)** — §3.3. On W1 the margin is
   ≈ 223 trades.
3. **v5's bear bucket is 11 against a floor of 10** — untouched by this proposal, which registers
   a new version of a different strategy and cannot disturb v5's approved scope (R7, R7b). Recorded
   because MAP §4.2 item 5 requires it.
4. FACT (`v6_regime_power.md` §6.3), recorded as context for how little the current point estimate
   can bear: dropping **one month** (2023-12, 7 of v0.1.0's 51 OOS trades) moves OOS expectancy from
   +0.0613R to **−0.2623R**. Any comparison against +0.0613R is a comparison against a
   12-cluster estimate.

---

## 6. Sensitivity-grid plan

MAP §4.2 item 6 is a hard requirement: **every parameter the v0.2.0 introduces or changes becomes
a pre-registered gate-5 axis.** This proposal introduces two.

### 6.1 The pre-registered grid (chosen now, before any expectancy is seen)

`research/promotion.py:199-208`, `volatility_breakout` branch:

```python
        return factory, {
            "contraction_max": [0.65, 0.75, 0.85],   # unchanged
            "stop_atr":        [1.5, 1.75, 2.0],     # unchanged
            "squeeze_lag":     [3, 5, 10],           # NEW
            "release_min":     [0.8, 1.0, 1.2],      # NEW
        }
```

- **3 × 3 × 3 × 3 = 81 points**, within `sensitivity.MAX_GRID_POINTS = 120`
  (`sensitivity.py:29,133-139`). No existing axis is removed — removing one would reduce coverage
  and is treated here as a weakening, which R4 forbids.
- The shipped defaults sit at the **centre** of every axis, so each axis contributes exactly 2
  one-step neighbours: **8 neighbours**, against v0.1.0's 4.
- Runtime: each point is a full `run_strategy_over_universe` over the pre-sealed span
  (`sensitivity.py:143-159`). Measured here at ~3.4 s for 24 symbols → ≈ 21 s for 150 symbols →
  **≈ 28 minutes for the grid**, plus gate 1's folds. Worth stating so it is budgeted, not
  discovered.

### 6.2 What the wider grid costs, stated honestly

**This makes gate 5 materially harder to pass, and that is intentional.** v0.1.0 needed 3 of 4
neighbours positive; v0.2.0 needs **6 of 8** (≥ 75%) and **≥ 49 of 81** points positive (≥ 60%).
FACT (`v6_regime_power.md` §5.2): at this effect size a grid cell's *sign* is close to a coin
flip (P(positive) ≈ 0.61 at n = 51), so `P(pass)` fell out at ≈ 0.51 for the 9-point grid. With
81 points the positive-fraction test becomes *more* reliable, not less — but the 8-neighbour test
is a harder bar to clear by luck. A gate-5 pass on this grid would mean substantially more than
v0.1.0's did; a gate-5 failure would be the expected outcome of an honest test, not a surprise.

### 6.3 The no-op check (MAP §4.2 item 6, mandatory) — **pre-computed, all four axes bite**

**FACT** (snapshot 3 OOS trade counts per cell, computed for this document; expectancies were not
computed — §3.6). Baseline cell `(0.75, 1.75, 5, 1.0)` = **32 OOS / 132 pre-sealed**.

| axis moved one step from baseline | OOS n | pre-sealed n | changes the trade count? |
|---|---:|---:|---|
| `contraction_max` 0.75 → 0.65 | **6** | 28 | yes (and **falls below the 15-trade floor on snapshot 3**) |
| `contraction_max` 0.75 → 0.85 | **91** | 344 | yes |
| `stop_atr` 1.75 → 1.5 | 32 | 132 | **no — by design; it changes exits, not entries** |
| `stop_atr` 1.75 → 2.0 | 32 | 132 | **no — same** |
| `squeeze_lag` 5 → 3 | **25** | 107 | yes |
| `squeeze_lag` 5 → 10 | **36** | 133 | yes |
| `release_min` 1.0 → 0.8 | **48** | 191 | yes |
| `release_min` 1.0 → 1.2 | **22** | 91 | yes |

`stop_atr` changes no entry, so its no-op check must be on **expectancy**, and FACT (eval 36 gate-5
evidence, v0.1.0) it demonstrably moves it: at `contraction_max = 0.75` the three `stop_atr` values
returned **+0.0296 / +0.0613 / +0.0646 R** on 51 / 51 / 50 trades. The axis is not a dead
parameter. **All four axes therefore satisfy §4.2 item 6**, and no field is retained-but-unused —
the silent 100%-pass failure mode of MAP §2.1 cannot occur here.

**Cell-count coverage.** Across all 81 cells on snapshot 3, OOS n ranges **4 … 127**, and **63 of
81** reach the 15-trade floor. On the W1 snapshot at the §3.4 multiplier of 7.89×, the smallest
cell projects to **≈ 32 OOS trades** and **all 81 cells clear the floor**. Note that
`sensitivity_min_grid_trades = 15` is also gate 1's per-fold floor (`promotion.py:632`;
`config/research.py:106`) — MAP §4.3 — so this paragraph is an argument about gate 1 as well;
neither constant is changed.

---

## 7. Leakage argument

**Structural guarantee first.** FACT (`engine.py:98`): the engine calls
`signal_fn(series.head(t), t)` — the strategy is handed a series truncated at `t` and physically
cannot read later bars. FACT (`engine.py:108,134`): the entry fills at `series.open[t+1]`, so the
signal bar's close is fully observable before the decision is acted on.

**Every quantity the change reads, with its index range:**

| expression | bars read | ≤ t? |
|---|---|---|
| `atr_contraction(series, t - p.squeeze_lag, 10, 50)` | `t−54 … t−5` at lag 5 (`t−59 … t−10` at lag 10) | yes |
| `atr(series, t - 1, 50)` | `t−50 … t−1` (`features/daily.py:46-50`) | yes |
| `true_range(series, t)` | `high[t]`, `low[t]`, `close[t−1]` (`features/daily.py:38-43`) | yes |
| `donchian_high/low(series, t, 20)` | `t−20 … t−1` — **excludes today by construction** (`features/daily.py:92-99`) | yes |
| `atr(series, t, 14)` | `t−14 … t` | yes |
| `ctx.regime` | `regime_lookup(proxy)[date(t)]`, itself point-in-time (`regime.py:65-96`) | yes |

`true_range(t)` uses the signal bar's own high and low. That is the same information horizon
v0.1.0 already relies on when it evaluates `close(t) > donchian_high(t)` and sets
`stop = close(t) − 1.75 × ATR(14, t)`; it is not a new class of dependency, and it is strictly
before the `t+1` open at which the trade fills.

**No new feature function is introduced**, so the `(series, t)` slice-to-≤t contract of
`features/daily.py` is not extended. **No cross-sectional or breadth term is introduced**, so
`StrategyContext` (`base.py:15-19`) is untouched and this is **not** a shared-surface change —
unlike v4's breadth lever, this proposal adds no plumbing that other strategies would inherit.

**A gap in gate 8 that this proposal closes (R4-permitted strengthening).** FACT
(`promotion.py:256-262`): `_leakage_self_check` covers only `sma(50)`, `rolling_return(20)`,
`atr(14)` and `realized_vol(20)`. **`atr_contraction`, `donchian_high`, `donchian_low` and
`true_range` are not in the list** — so v0.1.0's gate-8 pass never exercised the two features its
own entry rule is built on. The proposal adds:

```python
        ("atr_contraction(10,50)", lambda s, t: atr_contraction(s, t, 10, 50)),
        ("atr_contraction(10,50) @ t-5", lambda s, t: atr_contraction(s, t - 5, 10, 50)),
        ("donchian_high(20)", lambda s, t: donchian_high(s, t, 20)),
        ("true_range", lambda s, t: true_range(s, t)),
```

This makes gate 8 strictly more searching and can never make it easier to satisfy — the same R4
carve-out that permits adding a missing sensitivity grid (MAP §1, R4 item 1). It is an addition,
not a threshold change. Note that it also applies retroactively in spirit: if it ever fails, the
finding is about `features/daily.py`, not about this proposal, and must be reported as such.

---

## 8. Cost-model statement

**The cost model is unchanged and is not touched by this proposal.** FACT
(`backtest/costs.py:11-16`): `commission_per_share = 0.0`, `commission_min_per_order = 0.0`,
`slippage_bps = 3.0`, `half_spread_fill_penalty = True`. FACT (`engine.py:90,94,143`):
`spread_bps` default 5.0 → `slip = (3.0 + 2.5)/10,000` → **11.0 bps round trip**, recorded per
trade. FACT (`backtest_runner.py:205-206`): `spread_bps` is never overridden, so the assumption is
universe-independent.

**Per-trade cost in R at the proposal's `stop_atr` (unchanged at 1.75), measured not assumed.**
Using `cost_R = (round_trip_bps/10,000) / (stop_atr × ATR/price)` averaged over the actual signal
bars (snapshot 3; §3.5):

| round trip | implied quoted spread | **v0.1.0 cost/trade** | **v0.2.0 cost/trade** | delta |
|---|---|---:|---:|---:|
| **11.0 bps** (today) | 5 bps | **0.0640R** | **0.0555R** | **−0.0085 ± 0.0022 R (3.9 SE)** |
| 26.0 bps (2× spread) | 20 bps | 0.1513R | 0.1311R | −0.0202R |
| 36.0 bps (3× spread) | 30 bps | 0.2094R | 0.1815R | −0.0279R |
| 66.0 bps (5–6× spread) | 60 bps | 0.3840R | 0.3327R | −0.0513R |

MAP §4.2 item 8 and W1 §7 require the 2× and 5× rows for any expanded-snapshot run; they are
mandatory reporting outputs of the W1 evaluation, not optional.

**Turnover delta.** FACT (eval 36 gate-7 evidence): v0.1.0's pre-sealed turnover is **23.8/yr** at
exposure 0.66. DERIVED: v0.2.0 takes 132/211 = **0.626×** the trades on a fixed universe →
turnover ≈ **14.9/yr**, exposure ≈ 0.41 (both scale with trade count at an unchanged 10-bar time
stop). **Aggregate cost drag falls by ~45%**: `23.8 × 0.0640 = 1.52 R/yr` → `14.9 × 0.0555 = 0.83
R/yr` per symbol-slot. On the expanded universe both rules' turnover rises with breadth; the
per-trade figures above are the ones that matter for expectancy.

**Three statements that must appear in the final report.**

1. **MAP §0.4's 0.042R for this strategy is wrong at the entries it actually takes; the measured
   figure is 0.0640R.** At +0.0613R OOS, modelled cost is **104%** of the net edge, so the gross
   pre-cost edge is ≈ +0.125R and *all* of it is consumed by 11 bps. MAP §2.3's "0.042R of
   modelled cost sits inside it" and §0.4's "68% of its entire +0.0613R OOS edge" both understate
   it. **This correction stands whether or not this proposal is implemented.**
2. **At 26 bps round trip (the 2× case W1 §7 mandates), v0.1.0's cost is 0.1513R — 2.5× its entire
   point estimate. Gate 3 fails for v0.1.0 at 2× spread on arithmetic alone.** v0.2.0 at 0.1311R
   is better and still very likely under water. This is the single largest threat to the whole
   strategy and it is a data/liquidity fact, not a rule-design fact.
3. W1 §4.4's mitigating finding applies and is worth repeating: the least liquid *new* W1 name
   (`TRV`, 598.2 $M/day median) is **2.8× more liquid than `XLRE`**, which snapshot 3 already
   contains — so the flat 5 bps is no more wrong for the new names than for the current ones. It
   is wrong for both, and the project holds **no spread data at all**
   (`universe/screen.py:47`, `spread_filter_not_licensed`).

---

## 9. Variant budget and stopping rule

**Budget for this angle: 1 variant, hard cap 2.** Recorded per R5 for the final report.

- **Variant 1 (the only planned one):** `squeeze_lag = 5`, `release_min = 1.0`, everything else at
  v0.1.0 defaults, evaluated **once** on `research_150_massive_10y_2026-09-08` via
  `evaluate_promotion` with the key passed explicitly and `source="massive"` passed explicitly
  (W1 §9.1 — omitting the source silently loads `massive` **and** `massive_grouped`, duplicating
  every bar in 2025-01-03 → 2026-09-08, i.e. inside the sealed window).
- **Variant 2, permitted only under one pre-specified condition:** if variant 1 fails for a
  **counting** reason — OOS n < 30 (gate 2), or fewer than 3 evaluable grid cells (gate 5's
  `sensitivity.py:187` guard) — then and only then it may be re-run at the pre-registered fallback
  `release_min = 0.8` (one grid step, named here before any result is seen). **It may not be
  re-run because the point estimate disappointed.** Distinguishing the two cases is mechanical:
  gate 2's and gate 5's detail strings say which failed.
- **Stopping rule:** if variant 1 fails K3a or K3b (§4), **stop**. No third parameterisation, no
  `channel` change, no `contraction_max` loosening, no combination with the `risk_off` lever. Write
  §11's null option.
- **Grid points are not variants.** The 81-point gate-5 grid is the mandated robustness test, run
  once as part of the single evaluation, and its cells are never promoted to shipped parameters.
  Selecting a parameter set from grid results after the fact would be exactly the offence R5 exists
  to prevent.

**Programme-level count for this strategy.** MAP §4.1 allocates v6 **2 proposals**: the
universe/power angle (which is W1 itself and costs **0** strategy variants) and this mechanism
angle. **Total strategy variants for `volatility_breakout.short_swing` across all angles: 1,
capped at 2.** That number goes in the final report verbatim.

**Multiple-testing honesty.** This is the first variant tried on this strategy. If it passes gate
4 — which §5 predicts it will not — the pass is a 1-of-1, and its bootstrap CI carries no
selection penalty beyond the one already disclosed for the cross-strategy programme. That is the
main argument for spending the look on **one** mechanism-motivated change rather than a sweep.

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

Sealed windows: snapshot 1 `2025-09-07 … 2026-09-07`; snapshots 2–4 `2025-09-08 … 2026-09-08`
(verified against the rows). All four v6 draws are the **identical** 10 trades at −0.0979R;
DERIVED (MAP §0.3): SE = **0.491R**, so −0.0979R is **0.20 SE** from zero and carries no
information about this strategy's sign. **No sealed number appears anywhere in §1–§9 of this
proposal**, and none may.

### 10.2 What implementing this costs in looks

**FACT** (`db/models/research.py:263`; `promotion.py:377-384`): a new `StrategyVersion` plus a
`dataset_snapshot_id` is a new `(version, snapshot)` pair, so `_get_or_create_sealed_test` computes
a **fresh** sealed test rather than replaying a locked one. There is no way to run
`evaluate_promotion` without creating it — gate 9 is not optional.

**Baseline count: k = 5 per strategy** (MAP §0.1, §4.2 item 10; my brief states the same).

| event | new sealed test? | resulting look |
|---|---|---|
| four existing locked draws (ids 5, 10, 15, 20) | — | baseline **k = 5** per MAP §4.2 item 10's convention |
| W1's pre-registered **v0.1.0** re-run on `research_150_massive_10y_2026-09-08` (the universe/power proposal, W1 §8.1) | yes | **look 6** |
| **this proposal — v0.2.0 on `research_150_massive_10y_2026-09-08`** | yes | **look 7** if the W1 v0.1.0 run happens first; **look 6** if this is the only new sealed test |
| v0.2.0 on snapshot 3 | **NOT RUN — explicitly excluded** (§10.3) | would have been an additional look |

**A documentation inconsistency the operator should resolve, flagged rather than silently
resolved.** MAP **§0.1** says *"A v0.2.0 that seals against snapshot 3 is the **fifth** look"*
(4 locked + 1). MAP **§4.2 item 10** says *"the baseline count is k = 5 … so a first v0.2.0
sealing on snapshot 3 is **look 6**"* (4 locked + 1 = the baseline, next = 6). W1 §8.1 follows the
§0.1 reading. The two conventions differ by one. **This document follows §4.2 item 10**, because
that is the section governing what a proposal must state, and reports the count under both
readings wherever it matters. The substantive fact — *four locked draws exist and this adds one
more* — is the same either way, and it is that sentence, not the index, that belongs in the final
report.

### 10.3 Which snapshot the report leads with (pre-registered per R1)

**The v0.2.0 report leads with `research_150_massive_10y_2026-09-08`, because it is the only
snapshot on which v0.2.0 is evaluated.** Alongside it, verbatim and in every table:

1. the §10.1 four-draw v0.1.0 ledger;
2. W1 §8's pre-registered expectation that a powered run leaves gates 4 and 7 failing;
3. the statement that **snapshot 3 remains the headline for v0.1.0 comparisons** (it is the only
   snapshot on which gate 8 passes for any version — MAP §0.1) and that the expanded snapshot is a
   **separate experiment**, never an update to snapshot-3 numbers (MAP §3(a): 62.5% of snapshot 3
   is ETFs; the expanded universe is 90% single names, and §3.4 shows this proposal's trade mix
   moves with it).

**v0.2.0 is deliberately NOT evaluated on snapshots 1–4.** Reasons, in order: (i) it would create
up to four more sealed tests for a version whose gate 9 at n ≈ 15–20 would have SE ≈ 0.35–0.40R and
therefore no discriminating power; (ii) OOS n = 32 on snapshot 3 cannot test K3 (§4); (iii) the
only use of the resulting numbers would be re-parameterisation, which R5 counts and R1 does not
excuse. If the operator overrides this and runs snapshot 3 anyway, that is an **additional look**
and must be counted and disclosed as such.

---

## 11. Null option

**The null option here is not a fallback — it is the pre-registered *expected* outcome** (§5:
gates 4 and 7 are forecast to fail). The proposal's value is that it converts a structural defect
from an untested hypothesis into a measured one, and the null result is publishable evidence.

**If K3a or K3b fires (or gate 4 fails, as forecast), the output is a documented
"does not pass" for `volatility_breakout.short_swing`, carrying:**

1. **The structural finding, which stands on its own regardless of outcome.** The same-bar
   squeeze/break conjunction selects break bars **37% smaller** than the typical break bar
   (−0.4201 ± 0.0161, **26.1 SE**), identically on all four snapshots (§3.1). This is a permanent,
   reusable finding about the rule as designed, and it is the honest answer to "was the rule ever
   given a fair chance?"
2. **The corrected cost arithmetic (§3.5, §8).** Modelled transaction cost at v0.1.0's own entries
   is **0.0640R/trade**, **104%** of its +0.0613R OOS point estimate — so the strategy's entire net
   edge is a rounding artefact of a 11 bps assumption, its gross edge is ≈ +0.125R, and at the
   mandated 2× spread sensitivity (0.1513R) gate 3 fails on arithmetic alone. This correction to
   MAP §0.4 belongs in the report whatever happens.
3. **The required-n arithmetic (§5), with the clustered statistic alongside.** Gate 4 at the
   observed point estimate needs **n ≈ 5,426** OOS trades (≈ 2,554 ten-year symbols) on the iid
   bootstrap and **≈ 14,540** (≈ 6,800 symbols) under entry-month clustering
   (`v6_regime_power.md` §5, §6.1). FACT: the database holds **26** symbols with 10-year `massive`
   history and `UniverseFilters.max_universe_size = 150` (`config/research.py:139`). **Gate 4 is
   not reachable by universe expansion at any feasible scale.**
4. **The gate-6 disclosure.** The bear-bucket zero is a breadth problem with a hard calendar
   ceiling — **19 gate-open bear proxy sessions in nine years** — set by the inherited
   `not ctx.regime.risk_off` conjunct that v6 shares with the approved v2
   (`v6_regime_power.md` §1). The bear entry rate has never been measured (0 of 432, 1.72 SE from
   expectation). A bear bucket under 10 on W1 is a **power** outcome, pre-registered as
   uninformative.
5. **The fragility disclosure.** Dropping one month (2023-12, 7 of 51 trades) takes v0.1.0's OOS
   expectancy from +0.0613R to −0.2623R (`v6_regime_power.md` §6.3). The gate-3 pass this whole
   programme has been reasoning about is a 12-cluster estimate.
6. **The variant ledger (R5):** 1 variant tried (2 if the pre-specified counting-failure retry
   fired), what it changed, why, and the pre-sealed evidence that motivated it — §3, verbatim.
7. **The look ledger (§10):** the four locked draws plus the one this run created, with the
   convention ambiguity flagged.
8. **The disposition.** v0.1.0 stays **EXPERIMENTAL**. v0.2.0 stays EXPERIMENTAL. Neither is
   promoted; neither is deleted; no gate or threshold is touched; the cost model is unchanged.
   **Recommendation: stop.** With 1 of 1 mechanism variants failing and the required-n arithmetic
   showing gate 4 is unreachable, a third angle on this strategy would be variant-hunting, and MAP
   §2.2 lever 5's asymmetry argument applies with more force here than anywhere else in the
   programme.

**What a *pass* would mean, so it is not oversold either.** If v0.2.0 clears gates 1–8 on W1, the
report must state: the point estimate moved by ≈ 3.5×, on a snapshot that is a **distribution
shift** rather than a more-powered version of the same experiment (MAP §3(a)); the pass is on look
6 or 7 of a sealed calendar year (§10); gate 4's margin should be reported alongside the
entry-month clustered CI, under which **v2 and v5 themselves would fail**
(`v6_regime_power.md` §6.2); and live paper probation is the confirming test, never the promoting
one (R8) — with the standing caveat that as of today the paper loop has produced **zero** trades.

---

*Design-phase proposal. Read-only: no file under `src/` or `tests/` was modified, no row in
`data/signalforge.sqlite` was written, no promotion / sensitivity / sealed entry point was
invoked, no provider API was called, and no quantity inside the sealed window was computed. The
sealed-look count is unchanged at k = 5 by the writing of this document.*
