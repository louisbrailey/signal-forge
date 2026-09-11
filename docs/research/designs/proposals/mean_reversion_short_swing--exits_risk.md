# Design proposal — `mean_reversion.short_swing` v0.2.0, angle **EXITS & RISK**

**Strategy:** `mean_reversion.short_swing` v0.1.0 (`strategy_version.id = 4`), status
EXPERIMENTAL, latest evaluation **id 34** on dataset snapshot **3**
(`universe_24_ex_meta`), blocking gates **3, 4, 5, 7**.
**Angle:** exits & risk — exit logic (SMA-touch vs fixed target, stop placement, time
stop), motivated by the MFE/MAE diagnostic; `time_stop_bars` becomes a gate-5 axis;
explicit turnover and cost-in-R delta.
**Phase:** 2 (Design). This document proposes; it implements nothing.

**Compliance statement.** No file under `src/` or `tests/` was modified. No gate,
threshold or cost-model constant is changed anywhere in this proposal. Every number
below comes from (a) a read-only `SELECT` against `data/signalforge.sqlite`, (b) the
committed diagnostic `docs/research/diagnostics/v4_mfe_target.md` and its `.json`
sibling, (c) a `file:…?mode=ro&uri=true` **read-only** in-process re-run of
`research.backtest_runner.run_strategy_over_universe` (which contains no
`session.add/flush/commit`), or (d) arithmetic over those, shown. No provider API was
called. **Nothing in the sealed window (2025-09-08 → 2026-09-08; 2025-09-07 →
2026-09-07 on snapshot 1) was read, computed or consulted in forming any design choice.**
Sealed numbers appear only in §10, marked, and only as *disposition* context under R1.
Raw outputs: `mean_reversion_short_swing--exits_risk.json` (sibling of this file).

**Headline, stated before the details so it cannot be buried.**
This angle **cannot promote this strategy, and this proposal does not claim it can.**
The best-supported exits-and-risk change is forecast to move pre-sealed expectancy from
−0.0621R to roughly **−0.04R**, against gate 3's bar of `> 0`, gate 4's effective bar of
**+0.1115R** at n = 309, and gate 7's bar of **+0.0596R**. What the change *does* buy is
the removal of a genuine, demonstrable execution defect — a stop anchored to a price the
trade never traded at — plus a clean risk unit for whatever the signal-quality angle
proposes on top. It should be judged as a **composable correctness fix with a forecast
gate outcome of "still fails 3/4/5/7"**, or rejected in favour of §11.

---

## 0. What the MFE/MAE diagnostic already settled, so this proposal does not re-litigate it

FACT (`docs/research/diagnostics/v4_mfe_target.md` §5, §7, §8; reproduced independently
below in the Appendix):

| Exit lever this angle is nominally about | Diagnostic verdict | Number |
|---|---|---|
| Replace the frozen SMA target with a **tracking SMA touch** | **Dead.** Wrong sign, 0.8 SE | paired Δ = **−0.0032R ± 0.0040** pre-sealed; **−0.0004R ± 0.0064** OOS |
| **Lengthen the 6-bar time stop** | **Unmotivated.** The leash is a net *positive* contributor | time-stop exits contribute **+0.0410R**; 57.5% closed in profit; mean hold **2.84 bars** against a 6-bar leash |
| "Sub-ATR target vs 2-ATR stop" asymmetry | **Overstated by ~2×** | median target **1.598 ATR** vs median risk **2.127 ATR** → **0.77 : 1**, not ≈0.5 : 1 |
| "Big winners given back by a dumb exit" | **Not there** | at MFE > 1R only **3.05% ± 0.55%** of trades lose; on the unambiguous prior-bar definition **1.42%** |
| Where the money actually goes | **The stop bucket, alone** | target **+0.2114R**, time stop **+0.0410R**, stop **−0.3139R** → total −0.0621R |

Two consequences shape everything below.

1. **The target and the leash are not the defect.** Any proposal in this angle that
   changes `target_price` or `time_stop_bars` in the hope of expectancy is proposing
   something the pre-sealed data has already refused. This proposal therefore leaves
   both **unchanged in value** and touches `time_stop_bars` only as a *gate-5 axis*
   (§6), which is mandatory under MAP §4.2 item 6 and is a strictly-more-searching
   change under R4.
2. **The stop is the defect, and specifically its *anchor*, not its width.** That is
   diagnostic Finding 7, and it is the only surviving exits-and-risk mechanism with
   ≥2 SE pre-sealed support.

---

## 1. Mechanism

**Hypothesis addressed: H13 (new, stated in the §2 form).** *The strategy's risk unit is
anchored to a price it never trades at, so on the entries that matter most the stop is
not a risk control at all.*

`mean_reversion.py:91` sets `stop_price = close − stop_atr × ATR` using the **signal
bar's close**. `engine.py:108-111` fills the entry at the **next bar's open** and then
defines the risk unit as `risk_per_share = abs(entry_fill − sig.stop_price)`. Between
those two prices sits an overnight gap. This strategy enters only after a ≤ −2σ
one-day return with the close already below SMA(20) — i.e. it deliberately selects the
days on which the overnight gap distribution is fattest and most left-skewed. So the
one input the design does not control is systematically largest exactly where the design
is most exposed.

Economically the consequence is not "the stop is too tight" or "too wide". It is that
the *quantity of risk taken per trade is randomised by the gap*, in the wrong direction:
a bad overnight gap moves the fill down toward a stop that was fixed the previous
afternoon, so the position that has already gone against you before it opened is also
the position holding the least room. On **6.61% ± 0.79%** of pre-sealed trades the fill
lands with less than **1×ATR** of room to a 2×ATR-intended stop; **86%** of those stop
out; they average **−0.6710R ± 0.2141** against **−0.0190R ± 0.0251** for the other
93.4%. At the extreme the stop ends up *above* the fill, at which point it is not a stop
at all — five pre-sealed trades are in that state (§3.3), four of which the engine books
as **profitable "stop" exits**.

Why fixing the anchor should help in markets, not just in the backtest: a stop's job is
to bound the loss from the price you actually own at. Anchoring it to a stale reference
means the realised loss bound varies between ~0 and ~2.5×ATR trade by trade, with the
small values concentrated on the worst entries. Re-anchoring to the fill makes the loss
bound a constant `stop_atr × ATR` — which is what the R-multiple accounting, the
position sizer (`ledger.py` sizes off the stop), the sensitivity grid's `stop_atr` axis
and every number in the program already *assume* is true. This is the risk-management
convention every discretionary and systematic desk uses, and it is implementable exactly
as modelled: the stop is placed after the fill is known.

**Relation to the existing hypothesis set.** H8 (unfavourable exit geometry) survives
its own kill test by 3.1 SE but three of its four component claims are refuted
(§0); H13 is the surviving residue of H8, re-stated as a *risk-unit-definition*
hypothesis rather than a target/leash hypothesis. H13 is **not** H6/H7/H9 (entry-side,
signal-quality angle) and **not** H10/H11 (power). Overlap with the signal-quality
angle is confined to variant **V2** (§9), which is flagged there so the two angles do
not both count it.

---

## 2. Exact change (file, symbol, before → after)

New behaviour ships as **`VERSION = "0.2.0"`** (R3/R7). `strategy_version.id = 4`
(v0.1.0), its four sealed tests (ids 3, 8, 13, 18) and its evaluations are never
mutated, re-run or purged.

Two variants are specified. **V1 is primary**; V2 is the fallback and is the cheaper,
more conservative reading of the same mechanism. They are alternatives — exactly one
ships, if either does (§9).

### 2.1 Shared: the engine plumbing (a shared-surface change — call-out per MAP §4.2 item 7)

The stop must be computed from a price the strategy cannot see at signal time, so the
level has to be resolved by the engine at fill time. This is **not** new information —
`engine.py:109` already reads `series.open[entry_idx]` to price the fill.

`src/signalforge/backtest/engine.py`

```
# BEFORE (:29-41)
@dataclass(frozen=True, slots=True)
class EntrySignal:
    direction: Direction
    stop_price: float
    time_stop_bars: int
    target_price: float | None = None
    reason: str = ""

# AFTER — two (V1) / one (V2) new fields, both with behaviour-preserving defaults
@dataclass(frozen=True, slots=True)
class EntrySignal:
    direction: Direction
    stop_price: float          # unchanged: the signal-bar-anchored level
    time_stop_bars: int
    target_price: float | None = None
    reason: str = ""
    stop_distance: float | None = None    # V1 only: intended risk in price units
    stop_anchor_blend: float = 0.0        # V1 only: 0.0 == today's behaviour exactly
    min_risk_distance: float | None = None  # V2 only: minimum acceptable risk unit
```

`__post_init__` gains: `0.0 <= stop_anchor_blend <= 1.0`; `stop_distance > 0` required
whenever `stop_anchor_blend > 0`; `min_risk_distance > 0` when not `None`.

```
# BEFORE (:107-116)
d = _sign(sig.direction)
entry_idx = t + 1
raw_entry = series.open[entry_idx]
entry_fill = raw_entry * (1 + d * slip)
risk_per_share = abs(entry_fill - sig.stop_price)
if risk_per_share <= 0:
    t += 1
    continue
exit_idx, exit_fill, reason = _resolve_exit(series, entry_idx, entry_fill, sig, d, slip)

# AFTER
d = _sign(sig.direction)
entry_idx = t + 1
raw_entry = series.open[entry_idx]
entry_fill = raw_entry * (1 + d * slip)
stop_level = sig.stop_price
if sig.stop_anchor_blend > 0.0:                                   # V1
    fill_anchored = entry_fill - d * sig.stop_distance
    lam = sig.stop_anchor_blend
    stop_level = (1.0 - lam) * sig.stop_price + lam * fill_anchored
risk_per_share = abs(entry_fill - stop_level)
if risk_per_share <= 0 or (                                       # V2
    sig.min_risk_distance is not None and risk_per_share < sig.min_risk_distance
):
    t += 1
    continue
exit_idx, exit_fill, reason = _resolve_exit(
    series, entry_idx, entry_fill, sig, stop_level, d, slip
)
```

`_resolve_exit` (`:154-184`) takes `stop_level: float` as a new parameter and uses it in
place of `sig.stop_price` at `:166, :167, :169, :170`. No other line changes; the
stop-before-target ordering, the entry-bar fill convention
(`px = stop_level if u == entry_idx`), the time stop and the `eod` fallback are all
untouched.

**Why this is safe for the two live approvals (R7, R7b).** `stop_anchor_blend` defaults
to `0.0` and `min_risk_distance` to `None`, so for every strategy that does not set them
the computed `stop_level` is `sig.stop_price` and the code path is arithmetically
identical. `EntrySignal` is not part of `StrategySpec`, so `persistence.spec_json_hash`
(`persistence.py:32-43`) is untouched and `scan_scope_matches`
(`approval_scope.py:69-94`) keeps matching for v2 (`2ed97431…`) and v5 (`dfe696b6…`).
Mandatory pre-integration checks are in §5.6.

### 2.2 V1 (primary) — fill-anchored stop

`src/signalforge/research/strategies/mean_reversion.py`

```
# BEFORE (:17)                       # AFTER
VERSION = "0.1.0"                    VERSION = "0.2.0"

# BEFORE (:20-27)                    # AFTER
class MeanReversionParams:           class MeanReversionParams:
    z_lookback: int = 20                 z_lookback: int = 20
    z_entry: float = -2.0                z_entry: float = -2.0
    sma_window: int = 20                 sma_window: int = 20
    atr_window: int = 14                 atr_window: int = 14
    stop_atr: float = 2.0                stop_atr: float = 2.0
    time_stop_bars: int = 6              time_stop_bars: int = 6
                                         stop_anchor_blend: float = 1.0   # NEW

# BEFORE (:89-98)                    # AFTER
return EntrySignal(                  return EntrySignal(
    direction=Direction.LONG,            direction=Direction.LONG,
    stop_price=close - p.stop_atr * a,   stop_price=close - p.stop_atr * a,
    target_price=mean,                   target_price=mean,
    time_stop_bars=p.time_stop_bars,     time_stop_bars=p.time_stop_bars,
    reason=...,                          stop_distance=p.stop_atr * a,        # NEW
)                                        stop_anchor_blend=p.stop_anchor_blend,# NEW
                                         reason=...,
                                     )
```

Nothing else in `evaluate` changes: the entry condition (`:88`), the target
(`target_price=mean`, the SMA(20) frozen at the signal bar) and the 6-bar leash are
byte-identical. `stop_anchor_blend = 1.0` means the stop sits exactly
`stop_atr × ATR(14)` below the **fill**; `0.0` reproduces v0.1.0.

`spec()` strings must be re-worded to describe the shipped behaviour honestly —
`stop_logic = f"stop = entry fill − {p.stop_atr} × ATR({p.atr_window}) (anchor blend
{p.stop_anchor_blend}; 0 = signal-bar close)"` and `walkforward_result_ref` →
`reports/mean_reversion.short_swing-0.2.0.md` — and that report must be written.

### 2.3 V2 (fallback) — minimum-risk guard, no re-anchoring

Identical to V1 except: no `stop_anchor_blend` / `stop_distance`; instead

```
    min_risk_atr: float = 1.0        # NEW; 0.0 == v0.1.0 behaviour
...
    min_risk_distance=p.min_risk_atr * a,   # NEW field on EntrySignal
```

Semantics: when the fill leaves less than `min_risk_atr × ATR` of room to the
signal-anchored stop, the engine takes no trade and advances one bar (`t += 1`), so the
same symbol may re-enter the next session if the rule still fires. **Execution
assumption, to be stated in the report:** modelled as a cancel-at-the-open. A literal
real-world implementation (a buy-stop at `close − min_risk_atr × ATR`) could instead
fill *later* in the session on a rebound, at a worse price than the model's "no trade".
The modelled version is therefore mildly optimistic relative to that implementation;
it is exactly right for an operator who simply skips the order when the indication gaps.

### 2.4 Registration and grid

* `src/signalforge/research/strategies/__init__.py:43-51` — `default_strategies()`
  continues to hold one `MeanReversion()`; bumping `VERSION` makes it the v0.2.0
  instance. Consequence to state in the report: v0.1.0 becomes non-re-runnable from the
  working tree; its record is the DB (`strategy_version.id = 4`, sealed tests 3/8/13/18,
  evals) plus git history. (The alternative — a frozen `MeanReversionV1` class kept in
  the registry — adds a second registry entry *and* a second gate-5 grid for no research
  benefit, and is not recommended.)
* `src/signalforge/research/promotion.py:189-197` — the family grid
  `{"z_entry": [-2.5,-2.0,-1.5], "stop_atr": [1.5,2.0,2.5]}` is **left exactly as it
  is**. The two new axes arrive through the declared-axis mechanism (§6), which must
  ship first.

---

## 3. Pre-sealed evidence, with standard errors

Scope of every number in this section: **pre-sealed span only**, 2016-09-10 → 2025-09-07,
source `massive`, proxy SPY, snapshot 3 primary. Per-trade sd for this strategy is
**0.8725** pre-sealed / **0.8202** OOS (measured; MAP §0.3's implied 0.807 is the
bootstrap-inverted figure and is used wherever the map's own arithmetic is reproduced).

### 3.1 Reproduction check (what licenses the rest)

FACT. An independent read-only re-run reproduces evaluation 34 exactly:

| Quantity | This proposal | Recorded (eval 34 / 28) |
|---|---|---|
| snap 3 pre-sealed trades / expectancy | **984 / −0.0621R** (SE 0.0278) | 984 / −0.0621R |
| snap 3 OOS trades / expectancy | **309 / −0.0837R** (SE 0.0467) | 309 / −0.0837R (gates 2, 3) |
| snap 2 pre-sealed / OOS | **999 / 320 at −0.0782R** (SE 0.0454) | 999 / 320 at −0.0782R |

### 3.2 The motivating effect (diagnostic Finding 7, independently reproduced)

FACT, snapshot 3, pre-sealed:

| Partition on the realised risk unit | n | share | expectancy | SE |
|---|---|---|---|---|
| risk < 1×ATR (the gapped fills) | **65** | 6.61% ± 0.79% | **−0.6710R** | 0.2141 |
| risk ≥ 1×ATR | **919** | 93.39% | **−0.0190R** | 0.0251 |
| **difference** | | | **−0.6520R** | 0.2157 → **t = −3.02** |

OOS: 23 trades at **−0.8600R ± 0.2360** vs 286 at **−0.0213R ± 0.0449**; difference
**−0.8387R ± 0.2402**, **t = −3.49**. Snapshot 2 agrees within 0.1 SE on every cell.
Median realised risk unit **2.1272 ATR** (pre-sealed) — i.e. the *typical* fill is
+0.127 ATR **above** the signal close, so the defect is two-sided, and the collapsed
tail is the left half of a distribution that is not centred where the design assumes.

Both differences clear the map's 2-SE bar. This is the only exits-and-risk effect in the
strategy that does.

### 3.3 New FACT contributed by this proposal — the anchor produces stops that are not stops

FACT (read-only re-run; raw rows in the `.json` sibling). **Five** pre-sealed trades
have `stop_price > entry_fill` on a LONG — the "stop" sits above the entry:

| symbol | signal date | entry | close@signal | ATR(14) | stale stop | fill | realised risk | exit | pnl_r |
|---|---|---|---|---|---|---|---|---|---|
| UNH | 2024-02-27 | 2024-02-28 | 513.42 | 7.281 | 498.857 | 495.71 | 3.14 (0.43 ATR) | `stop` | **+0.913** |
| XLY | 2020-01-24 | 2020-01-27 | 62.975 | 0.577 | 61.821 | 61.649 | 0.17 (0.30 ATR) | `stop` | **+0.803** |
| XLY | 2024-08-02 | 2024-08-05 | 88.08 | 2.150 | 83.779 | 83.576 | 0.20 (0.09 ATR) | `stop` | **+0.773** |
| XLB | 2021-09-17 | 2021-09-20 | 40.665 | 0.535 | 39.595 | 39.562 | 0.03 (0.06 ATR) | `stop` | **+0.339** |
| JPM | 2025-04-03 | 2025-04-04 | 228.69 | 6.619 | 215.452 | 215.423 | **0.0286 (0.0043 ATR)** | `stop` | **−3.099** |

FACT: **four `stop` exits in the pre-sealed sample are booked as wins** (+0.339 to
+0.913R, total +2.828R, contributing **+0.0029R** to the headline −0.0621R), because
`engine.py:166-168` exits a LONG at `stop_price` on the entry bar whenever
`low ≤ stop_price`, and does not require the stop to be below the fill. The JPM row is
the same pathology with the sign reversed: the fill landed **2.9 cents** below the stale
stop, so `risk_per_share = 0.0286` and the 5.5 bps exit slippage alone renders as
**−3.099R**. These five are the extreme of the 65-trade tail; identical on snapshots 2
and 1. Under V1 the class cannot exist: the stop is `stop_atr × ATR` below the fill by
construction. Under V2 all five are excluded by a `min_risk_atr = 1.0` floor.

### 3.4 What the change is worth, decomposed — and the half of it that is only accounting

**This is the most important number in the proposal, and it cuts against it.**

DERIVED (exact recomputation over the 984 existing trades, holding behaviour fixed and
substituting the λ = 1 risk denominator `stop_atr × ATR` for the realised
`|fill − stale stop|`):

| Cut | v0.1.0 as run | λ = 1, **accounting only** (same trades, same exits) | change |
|---|---|---|---|
| pre-sealed (984) | −0.0621R | **−0.0407R** | +0.0214R |
| OOS (309) | −0.0837R | **−0.0484R** | +0.0353R |
| snap 2 pre-sealed (999) | −0.0622R | −0.0404R | +0.0218R |

HYPOTHESIS: roughly **one third to one half of V1's apparent improvement is definitional**
— the same dollars divided by a different denominator. The economic component is
whatever the *behaviour* change adds on top (the stop level itself moves: down by ~1.4
ATR on the gapped tail, **up** by ~0.13 ATR on the median trade, which will cause *more*
stop-outs there). Its sign is not predictable from this data, which is why §4 makes the
accounting-invariant test the kill test.

### 3.5 Fold structure (bearing directly on gate 1, which passes by 0.32 SE)

FACT (read-only re-run; fold boundaries copied from eval 34's gate-1 evidence):

| Fold | span | n | expectancy | SE | t | tail (risk<1ATR) n / exp | non-tail n / exp ± SE | λ=1 accounting |
|---|---|---|---|---|---|---|---|---|
| 1 | 2016-09-10→2018-12-10 | 257 | **+0.0175** | 0.0549 | **+0.32** | 10 / +0.4015 | 247 / **+0.0019** ± 0.0485 | +0.0361 |
| 2 | 2018-12-10→2021-03-10 | 292 | −0.1949 | 0.0552 | −3.53 | 23 / −1.0680 | 269 / −0.1202 ± 0.0463 | −0.1620 |
| 3 | 2021-03-10→2023-06-09 | 181 | **+0.0436** | 0.0564 | **+0.77** | 9 / −0.3650 | 172 / **+0.0650** ± 0.0570 | +0.0175 |
| 4 | 2023-06-09→2025-09-07 | 254 | −0.0651 | 0.0527 | −1.24 | 23 / −0.8600 | 231 / **+0.0140** ± 0.0503 | −0.0203 |

Three things follow, none of them comfortable:

* **Gate 1's current pass is a coin flip.** It needs 2 of 4 folds positive with n ≥ 15;
  it has exactly 2, at **+0.32 SE** and **+0.77 SE** from zero. Any change to this
  strategy is one fold-sign flip away from failing a gate it currently passes.
* **The tail is not uniformly the villain.** In fold 1 the ten gapped trades are
  **+0.4015R** (SE 0.7709 — one SE wide, so this says nothing except that the effect is
  not homogeneous). Removing the tail is what makes folds 3 and 4 look better; it makes
  fold 1 *worse* (+0.0175 → +0.0019).
* **V2's implied fold set is 3 of 4 positive** (+0.0019 / −0.1202 / +0.0650 / +0.0140),
  V1's accounting-only fold set is 2 of 4 (+0.0361 / −0.1620 / +0.0175 / −0.0203). Both
  clear gate 1 on paper; both do so on margins under 1 SE.

### 3.6 What the existing gate-5 grid already says about stop width (and why this
proposal does not touch `stop_atr`)

FACT (eval 34, gate-5 evidence, 9 points, all negative):

| `z_entry` \ `stop_atr` | 1.5 | 2.0 | 2.5 |
|---|---|---|---|
| −2.5 | −0.1416 (n=131) | −0.1908 (131) | −0.0988 (131) |
| **−2.0** | −0.1049 (311) | **−0.0837 (309, baseline)** | −0.0325 (305) |
| −1.5 | −0.0799 (634) | −0.0725 (616) | −0.0499 (606) |

The `stop_atr` gradient is monotone at z = −2.0 and −1.5 and looks inviting
(−0.0837 → −0.0325 at 2.5). It is **not** evidence and this proposal does not act on it:
(a) the unpaired difference is 0.0512R against SEs of ~0.047 each, i.e. **0.77 SE**;
(b) widening `stop_atr` inflates the R denominator by 25%, which alone accounts for
−0.0837/1.25 = −0.067 of the −0.0325, so at most ~0.03R is economic and it is well
inside noise; (c) selecting `stop_atr = 2.5` because the grid liked it is tuning on the
gate that is supposed to audit the tuning. **`stop_atr` stays at 2.0.**

---

## 4. Falsification — stated now, before anything is run, and required on all four snapshots

The proposal dies if **any** of the following holds. Each is computable on pre-sealed
data alone, with no promotion run and therefore **no sealed look**.

**F1 — the accounting-invariant test (the primary kill test).** Recompute both v0.1.0
and the variant on a **fixed denominator** `stop_atr × ATR(14)` measured at the signal
bar — identical for both versions, so the R-rescaling of §3.4 cancels exactly — and take
the **paired per-trade difference** over the matched entry set.
*Kill if the paired mean difference is under **2 SE**, or is negative, on any snapshot.*
By analogy with the tracking-SMA counterfactual (paired Δ SE = 0.0040 on n = 984, where
only ~30% of trades changed), expect SE here of order 0.01–0.03; the bar is therefore an
economic gain of roughly **≥ +0.03R per trade**, which is a demanding test the proposal
may well fail. **This is the test that decides the proposal, not the headline expectancy.**

**F2 — the effect must not live only in 65 trades.** Compute F1 restricted to the
**risk ≥ 1×ATR** subset (919 pre-sealed / 286 OOS). *If the paired difference there is
under 2 SE while the whole-sample difference is positive, V1 is not a general risk rule*
— it is a 6.6% outlier patch, and V2 (which is honest about being exactly that) strictly
dominates it. Ship neither as "improved exits"; report the partition.

**F3 — no fold may be bought at another's expense.** *Kill if fewer than 2 of the 4
walk-forward folds are positive with n ≥ 15* (that is gate 1 failing), *or if fold 2
(−0.1949R, the Dec-2018 + COVID fold) improves by less than 0.05R while folds 1/3
deteriorate* — that pattern means the change is redistributing noise, not removing a
mechanism.

**F4 — the artefact class must actually disappear.** *Kill if the variant still produces
any trade with `exit_reason == "stop"` and `pnl_r > 0`, or any trade with a realised risk
unit below 0.5×ATR.* Under V1 both counts must be exactly **0** by construction; a
non-zero count means the implementation is wrong.

**F5 — snapshot invariance (R10).** Every one of F1–F4 must hold on **all four**
snapshots. Coverage status of this proposal's own evidence: computed on snapshot **3**
(24 symbols) and snapshot **2** (25 symbols); snapshot **1**'s pre-sealed span
(ending 2025-09-06, a Saturday) resolves to the identical bar set as snapshot 2 and
reproduces it exactly. Snapshot **4** (`META_CONT`, source `continuity_bridge:1`) was
**not** computed here — under R6 a `massive`-only load drops that symbol — and the
implementation phase must run it through the same continuity mapping the promotion path
uses (`data_snapshot.continuity_mapping_id = 1`) before F1–F4 may be declared satisfied.
*If the sign of the F1 difference is not the same on all four, the proposal is a
snapshot artefact and dies.*

**What would NOT kill it, and must not be treated as if it did:** the variant still
failing gates 3, 4, 5 and 7. §5 forecasts exactly that. A proposal that treats its own
forecast failure as new information is laundering a fishing expedition.

---

## 5. Gate-by-gate forecast

Trade sets are tagged per MAP §0.2: gates 2/3/4 read **OOS only**; gates 1/6/7 read
**all pre-sealed trades (IS+OOS)**, gate 7 included, despite its docstring.

### 5.1 Summary table

| Gate | Trade set | v0.1.0 today | V1 forecast | V2 forecast | Verdict |
|---|---|---|---|---|---|
| 1 rolling walkforward | all pre-sealed (984) | pass, **2 of 4** (+0.32 SE, +0.77 SE) | pass, 2 of 4 (fragile) | pass, **3 of 4** (fragile) | **pass, at risk** |
| 2 min OOS trades | OOS (309) | pass, 309 | 300–320 | **285–300** | pass |
| 3 net expectancy | OOS (309) | **fail**, −0.0837R | **fail**, ≈ **−0.05 to −0.03R** | **fail**, ≈ −0.04 to −0.01R | **fail** |
| 4 bootstrap CI low | OOS (309) | **fail**, low −0.1739R | **fail**; needs **+0.1115R** at n=309 | **fail** | **fail** |
| 5 sensitivity | OOS per grid point | **fail**, 0/9 positive | **fail**, forecast 0–6 of **81** positive | **fail** | **fail** |
| 6 regime coverage | all pre-sealed (984) | pass, 618/46/260, **60 unbucketed** | pass, ≈ 600–640 / 44–48 / 250–270, ≈ 58–62 unbucketed | pass, ≈ 43 bear | pass |
| 7 benchmark Sharpe | all pre-sealed (984) | **fail**, −0.749 vs +0.719 | **fail**, ≈ −0.49 | **fail**, ≈ −0.23 | **fail** |
| 8 data/leakage | — | pass (snapshot 3 only) | pass — no new feature function | pass | pass |
| 9 sealed | sealed year | passes on all four snapshots | **new look, see §10** | new look | n/a |
| 10 probation | — | pass | pass | pass | pass |

**Predicted verdict: NO TRADE, blocked on 3, 4, 5, 7 — the same four gates as today.**

### 5.2 Gate 3 and gate 4, quantitatively

Basis: §3.4's accounting-only OOS figure of **−0.0484R** plus an unsigned behaviour
term. V1 forecast band **−0.05R to −0.03R**; a generous upper bound in which the
behaviour term equals the accounting term is **−0.01R**. V2's ceiling is the published
partition, **−0.0213R ± 0.0449** (OOS, 286 trades), before replacement entries.

Gate 4 as a required n (`n > (1.96·sd/(exp − 0.02))²`, measured OOS sd = 0.8202):

| Hypothetical OOS expectancy | required n | vs 309 today |
|---|---|---|
| −0.05 … −0.01 (V1's forecast band) | **never** — point estimate negative | — |
| +0.03 | 25,844 | 84× |
| +0.05 | 2,872 | 9.3× |
| +0.08 | 718 | 2.3× |
| +0.10 | 404 | 1.3× |
| **+0.1115** | **309** | the bar at today's n |

FACT-adjacent framing: gate 4 at n = 309 demands **+0.1115R** (with MAP §0.3's implied
sd = 0.807, +0.1100R). The whole exits-and-risk mechanism is worth an *accounting* +0.035R
and an unknown, probably smaller, economic increment. **Gate 4 is out of reach for this
angle by a factor of roughly four**, and no realistic universe expansion closes it while
the point estimate is negative.

### 5.3 Gate 5 — and the new axes are the point

Forecast: **fail.** The 81-point grid (§6) sits in a region whose *best* known cell is
−0.0325R; adding two axes that shift expectancy by ≲0.04R cannot lift 60% of cells above
zero. Expected positive fraction 0–8%; required 60%. Neighbour fraction: the baseline
has **7** one-step neighbours in a 4-axis grid (2 each on `z_entry`, `stop_atr`,
`time_stop_bars`; 1 on `stop_anchor_blend`, whose baseline 1.0 is an endpoint), so
≥ 6 of 7 must be positive; forecast 0 of 7.

Per-cell trade counts: the family grid's thinnest cells today are the `z_entry = −2.5`
column at n = 131 OOS, comfortably above the 15-trade floor
(`th.sensitivity_min_grid_trades`). Adding `time_stop_bars ∈ {4,6,8}` moves counts by
single-digit percentages (the leash changes exit timing, hence re-arm timing) and
`stop_anchor_blend` by ~±3%. **No cell is forecast within 3× of the 15-trade floor.**
Note per MAP §4.3 that this floor is the *same constant* as gate 1's per-fold floor, so
this paragraph is also a statement about gate 1.

**Zero-margin cases required by MAP §4.2 item 5.** Neither is in this strategy: v6's
gate-5 neighbour fraction (0.750 on snapshot 3, already 0.500/FAIL on snapshot 4) and
v5's bear bucket (11 against a floor of 10) belong to other versions. They are
nonetheless **at risk from this proposal**, because §2.1 edits the shared engine — see
§5.6, which makes proving them untouched a release gate.

### 5.4 Gate 6 — buckets and the unbucketed count

FACT today (eval 34): bull **618**, bear **46**, range **260** = 924 bucketed against
`full.trades` = 984 → **60 unbucketed (6.10%)**, all of them trades entered inside
`label_regimes`'s 200-session warmup (`backtest/regime.py:20,36-37`) or on a date with
no proxy bar. Forecast: both variants change *which bar* a trade exits on, hence when
the engine re-arms, hence entry dates shift by a few sessions; bucket shares move by
≲5%. V1: bull 600–640 / bear 44–48 / range 250–270, unbucketed 58–62. V2: ≈ −6% across
the board, bear ≈ 43. Floor is 10 per bucket → **pass with ≥ 4× margin on the binding
bucket**. Caveat carried from MAP §4.3: gate 6 uses `backtest/regime.py:label_regimes`
while the strategy filters on `research/regime.py:RegimeState` — different labellers, so
this forecast is about the former only.

### 5.5 Gate 7 — the bar, derived

DERIVED, and validated to four decimals against the stored evidence: annualised Sharpe
≈ `(expectancy_R / sd_R) × √(trades per year)`. With expectancy −0.0621, sd 0.8725 and
`turnover_per_year = 110.76` (FACT, eval 34 gate-7 evidence; = 984 trades / 8.884 y),
this gives **−0.74905** against the recorded **−0.749**. Inverting it, gate 7 requires

* **pre-sealed expectancy ≥ +0.0596R** at unchanged turnover (V1), or
* **≥ +0.0617R** at V2's ~6.6% lower turnover (fewer trades → smaller √N).

V1's forecast pre-sealed expectancy of ≈ −0.04R maps to a Sharpe of ≈ **−0.49**; V2's
≈ −0.019R maps to ≈ **−0.23**. Both fail against SPY's **+0.719** by more than a full
Sharpe unit. Gate 7 is not addressable by exit engineering at this effect size, and no
amount of data changes that — it is a point-estimate gate, like gate 4.

### 5.6 Mandatory pre-integration checks (release gates on the shared-surface change)

1. **Byte-identical behaviour for every other strategy.** With the new fields at their
   defaults, `run_backtest` must return identical `SimTrade` sequences. Test:
   `tests/backtest/test_engine.py::test_default_entrysignal_fields_do_not_change_results`
   over fixture data, plus a scratch-DB (`$TMPDIR/scratch-*.sqlite`,
   `DATABASE_URL=sqlite+pysqlite:///…`) re-evaluation of **versions 2, 5 and 6**
   comparing `gates_json` field-for-field against evals 32, 35, 36. v6's
   `neighbour_positive_fraction` must still read exactly **0.750** and v5's bear bucket
   exactly **11**; any drift is a stop-ship.
2. **Approved-scope hashes unchanged.** Assert `spec_json_hash` for
   `TrendContinuation(SHORT_SWING)` = `2ed97431…` and `RelativeStrength(MEDIUM_SWING)`
   = `dfe696b6…` (the literals pinned in the hardening spec §2.3), and that
   `scan_scope_matches` still returns True for both live scopes.
3. **Fresh sealed row.** Assert the v0.2.0 evaluation's
   `StrategySealedTest.strategy_version_id` is a row created by *this* run and not
   version 4's (MAP §4.3, the R3 staleness trap).
4. **New engine invariants.** `stop_anchor_blend = 1.0` ⇒ every trade's
   `|entry_fill − stop_level| == stop_atr × ATR` to floating tolerance; zero trades with
   `exit_reason == "stop" and pnl_r > 0` (F4).

---

## 6. Sensitivity-grid plan (pre-registered, before any result is seen)

**Prerequisite.** This grid requires the declared-axis mechanism specified in
`docs/research/diagnostics/pipeline_hardening_spec.md` §2 — an optional
`sensitivity_axes()` method on the strategy class, merged into `_sensitivity_plan`'s
family grid, **never** a `StrategySpec` field (which would change every strategy's
`spec_json_hash` and permanently unscope the two live approvals). That item must ship
**before** this v0.2.0, because axes must be pre-registered ahead of results.

**Declared grid — V1 (81 points, cap is `MAX_GRID_POINTS = 120`, `sensitivity.py:29`):**

| Axis | Values | Source | Baseline |
|---|---|---|---|
| `z_entry` | −2.5, −2.0, −1.5 | family grid, unchanged (`promotion.py:197`) | −2.0 |
| `stop_atr` | 1.5, 2.0, 2.5 | family grid, unchanged | 2.0 |
| **`time_stop_bars`** | **4, 6, 8** | **declared — mandated by the angle and by MAP §4.2 item 6** | 6 |
| **`stop_anchor_blend`** | **0.0, 0.5, 1.0** | **declared — the parameter that defines the variant** | 1.0 |

**V2's grid** is identical with `min_risk_atr ∈ {0.0, 0.5, 1.0}` (baseline 1.0) in place
of `stop_anchor_blend`. Both are 3×3×3×3 = **81** points.

Notes and honest limitations:

* `stop_anchor_blend`'s baseline (1.0) is an **endpoint**, so it contributes one
  one-step neighbour rather than two; the neighbour denominator is 7. This is disclosed
  rather than fixed by padding the axis with a value above 1.0, which has no meaning.
  The axis includes **0.0 = v0.1.0's behaviour**, which makes the grid a direct
  A/B of the change at eight other parameter settings — a stronger test than a
  neighbourhood alone.
* `time_stop_bars ∈ {4, 6, 8}` is a genuine ±1-step neighbourhood around the shipped 6
  and is chosen **before** results; it is not a search for a better leash. The
  diagnostic says the current leash contributes +0.0410R and 57.5% of leash exits are
  profitable, so the pre-registered expectation is that this axis is *live but flat*.
* **A combined V1+V2 variant is structurally discouraged**: five axes × three values =
  243 > 120, so `run_parameter_sensitivity` raises `ValueError`
  (`sensitivity.py:137-140`) and the combined variant could only be shipped by shrinking
  an axis to two values — i.e. by weakening the neighbourhood. That is a reason not to
  ship it, and it is recorded here as one (§9).
* Runtime: 81 full universe backtests. Measured reference: ~55 s for a 27-point,
  24-symbol, 9-year grid (hardening spec §9), so ≈ **2.5–3 min** per evaluation. Fine.

**Pre-integration no-op (inert-axis) check — required by MAP §4.2 item 6.** Before the
promotion run, execute a 3-point mini-grid on each declared axis alone over the
pre-sealed OOS span and record `n_trades` and `oos_expectancy_r` to 4 d.p. An axis whose
three points are identical on **both** is inert and the grid tested nothing on it.

Pre-registered expectations (so that a surprise is visible): `time_stop_bars` must move
the trade count — **25.6% ± 1.4%** of trades exit on the leash today, so 6 → 4 and 6 → 8
cannot be no-ops. `stop_anchor_blend` must move both count and expectancy — the median
fill sits **0.127 ATR** from the signal close and the gap is non-zero on essentially
every trade, so λ changes the risk unit of ~100% of trades. `min_risk_atr` must remove
≈ 65 pre-sealed trades at 1.0. **If any declared axis comes back inert, the
implementation is wrong and the run is void** — that is the failure mode (a retained but
unused field) that lets gate 5 pass at 100% having tested nothing.

---

## 7. Leakage argument

**No new feature function is introduced.** `zscore_last_return`, `sma` and `atr` are
unchanged and remain the only features the strategy reads, all via the `(series, t)`
contract with slices ≤ t. Gate 8's self-check list (`promotion.py:257-262`: `sma(50)`,
`rolling_return(20)`, `atr(14)`, `realized_vol(20)`) is unaffected and stays valid.

**The one new input is the entry fill, and it is not future information.** The engine
computes `entry_fill` from `series.open[t+1]` at `engine.py:109-110` **today**, to price
the entry. V1 uses that same already-consumed number to place the stop; V2 uses it to
decide whether the order is taken. Neither reads any bar after `entry_idx`. The
strategy's own `evaluate()` still sees only `series.head(t)` (`engine.py:102`) and still
returns the same signal-time information it does now — the new fields are
`stop_atr × ATR(14)` at bar `t` and a constant. **Non-anticipation is structural, not
argued.**

`assert_no_lookahead` (`backtest/leakage.py:23-41`) checks feature functions, not the
engine, so it neither covers nor needs to cover this change. Two targeted tests carry
the burden instead:

1. `test_fill_anchored_stop_is_invariant_to_future_bars` — run `run_backtest` on
   `series` and on `series.head(k)` for several `k` past a known entry; every trade
   whose entire life is inside both windows must be identical.
2. `test_stop_level_depends_only_on_entry_bar_open_and_signal_atr` — assert
   `|entry_fill − stop_level| == p.stop_atr × atr(series, t, 14)` for λ = 1.

**Realism, which is the other half of a leakage argument.** A stop placed at
`fill − 2×ATR` is placed after the fill is known and is the ordinary way stops are
placed; it needs no information the operator would not have. V2's skip rule is the one
that needs care, and §2.3 states its execution assumption and the direction in which it
is optimistic.

---

## 8. Cost-model statement (quantitative)

**The cost model is unchanged.** `CostModel` stays at `commission_per_share = 0.0`,
`commission_min_per_order = 0.0`, `slippage_bps = 3.0`, `half_spread_fill_penalty = True`
(`costs.py:11-16`); `run_backtest`'s `spread_bps = 5.0` default stays
(`engine.py:90`), and `backtest_runner.py:205-206` still does not override it. Round trip
remains **11.0 bps of notional** (`engine.py:94, 143`). Nothing in §2 touches any of it.

**Measured per-trade cost in R today** (FACT, read-only re-run over the 984 pre-sealed
trades; cost in R = `11 bps × entry price ÷ risk_per_share`):

| | median | mean | max |
|---|---|---|---|
| v0.1.0 as run (stale-anchored risk unit) | **0.0343R** | **0.0520R** | **8.19R** |
| V1, λ = 1 (risk = 2×ATR by construction) | 0.0339R | **0.0363R** | **0.1115R** |
| **paired delta (V1 − v0.1.0), per trade** | **+0.0019R** | **−0.0157R ± 0.0085** | — |

Read this carefully, because it points both ways:

* For a **typical** trade the fill-anchored risk unit is *smaller* than the realised one
  (2.000 vs a median 2.127 ATR), so the same 11 bps buys 6.4% more of it: cost rises by
  **+0.0019R per trade**, the median paired delta. That is a real, if small, drag, and
  it partly offsets §3.4's accounting gain.
* For the **tail** the current cost figure is nonsense — a trade with a 0.0043 ATR risk
  unit pays **8.19R** of modelled cost — which is why the *mean* cost falls by
  0.0157R ± 0.0085 under V1. The mean is the number that enters expectancy, so the cost
  channel contributes part of §3.4's improvement and, once again, part of that is
  denominator, not dollars.
* Note also that MAP §0.4's reference figure of 0.028R/trade for this strategy assumed
  ATR/price = 2%. Measured at these entries, ATR/price is **median 1.62%, mean 1.92%**,
  so the true median cost is **0.0343R**, ~22% higher than the map's estimate. The map's
  figure is a reference, not a measurement; this one is a measurement.

**Turnover delta.** FACT: `turnover_per_year = 110.76` today (eval 34, gate-7 evidence),
mean holding period **2.84 bars ± 0.079**, 984 trades over 8.884 years.

* **V1:** the stop moves *up* ~0.13 ATR for the median trade (marginally more stop-outs,
  marginally shorter holds, earlier re-arm) and *down* ~1.4 ATR for the gapped tail
  (fewer instant stop-outs, longer holds). Net forecast **−3% to +5%** on trade count
  and turnover; cost delta in R = the paired figures above, i.e. **+0.0019R/trade at the
  median, −0.0157R/trade at the mean**.
* **V2:** removes ~65 pre-sealed entries (−6.6%) but re-arms the next bar, so some are
  replaced. Forecast trade count **−4% to −7%**, turnover **≈ 103–106/yr**, per-trade
  cost in R **unchanged at the median** and lower at the mean (the 8.19R outliers are
  precisely the excluded trades). Aggregate modelled cost falls ~6%.

**Spread sensitivity (MAP §4.2 item 8).** At the measured ATR/price and a λ = 1 risk
unit, median cost in R is **0.0339R at 11 bps**, **0.0801R at 26 bps** (2× spread) and
**0.2034R at 66 bps** (a 30 bps half-spread). Against a forecast expectancy of ≈ −0.04R,
a 2× spread assumption alone removes another ~0.046R — i.e. **this strategy has no cost
headroom at all**, and any future evaluation on an expanded, less liquid snapshot must
report the 2× and 5× columns beside the headline. This proposal targets the current
24-symbol snapshot 3 and does not depend on W1.

---

## 9. Variant budget and stopping rule

**Budget for this angle: 2 variants. Hard cap 2.** V1 (fill-anchored stop) and V2
(minimum-risk guard). Both are pre-specified here, before any run.

**Explicitly excluded, and why — so that not trying them is on the record:**

* tracking-SMA target — refuted, Δ = −0.0032R ± 0.0040 (0.8 SE, wrong sign);
* longer/shorter leash as an *expectancy* change — the leash is +0.0410R net positive;
  `time_stop_bars` moves only as a gate-5 axis, at its shipped value of 6;
* `stop_atr = 2.5` — the gate-5 grid's best cell, at 0.77 SE, mostly denominator, and
  selecting it would be tuning on the audit gate (§3.6);
* V1+V2 combined — five axes exceed `MAX_GRID_POINTS` (§6), so it cannot be shipped with
  a full pre-registered neighbourhood;
* any grid sweep over the new parameters beyond the pre-registered 81-point gate-5 grid.

**Overlap accounting with the other two angles.** V2 is a *no-trade* rule and could be
read as an entry filter; it is claimed **here** and must **not** be counted again by the
signal-quality proposal. This angle claims **2** of the strategy's total variant budget.

**Stopping rule (sequenced, and each step is cheap and sealed-look-free):**

1. Run **F1** for V1 on snapshots 3 and 2 using `run_strategy_over_universe`
   in-process, read-only. **If F1 fails → V1 is dead. Do not tune λ.**
2. If F1 passes, run **F2–F4** on snapshots 3, 2, 1 and 4. Any failure → V1 dead.
3. If V1 dies, run F1–F4 once for V2. Any failure → **both dead → §11**.
4. Only if a variant survives all of F1–F5 does anything get implemented, reviewed and
   put through `evaluate-promotion`. **At most one promotion run.** If the surviving
   variant's pre-sealed OOS expectancy is still negative — which §5 forecasts — the
   right call is to record it in the variant ledger and go to §11 **without** running
   `evaluate_promotion` at all (see §10: the run itself is what costs the look).
5. No third variant. If both die, this angle reports a documented negative result.

**Multiple-testing disclosure for this proposal itself (R5).** In writing it, **zero**
strategy variants were backtested and **zero** parameters were searched. Three read-only
computations were run over the *unmodified* v0.1.0 trade population: a reproduction of
eval 34; a deterministic re-expression of the existing trades under a λ = 1 denominator
(§3.4 — no rule changed, no trade re-simulated); and a census of stop/risk pathologies
(§3.3) and per-trade costs (§8). None of these is a variant, and none touched sealed data.

---

## 10. Sealed-look accounting

**Implementing either variant creates a new `StrategyVersion` row and therefore a new,
never-before-computed `StrategySealedTest` on whatever snapshot it is evaluated against**
(unique on `(strategy_version_id, dataset_snapshot_id)`, `db/models/research.py:263`).

FACT, and the operational point that shapes §9's stopping rule: gate 9 is computed
**unconditionally** — `_get_or_create_sealed_test` is called at `promotion.py:838-844`,
after gate 8, with no dependence on whether gates 1–8 passed (eval 34 is itself proof:
four gates failed and the sealed test still ran). **A look is consumed by calling
`evaluate_promotion`, not by passing gates.** Pre-sealed screening via
`run_strategy_over_universe` / `run_parameter_sensitivity` consumes none.

**The existing ledger for this strategy (R2; reproduced from MAP §0.1 and re-verified by
read-only `SELECT` against `strategy_sealed_test` for `strategy_version_id = 4`):**

| Snapshot | key | sealed test id | window | result | passed |
|---|---|---|---|---|---|
| 1 | `universe_25_baseline_legacy` | **3** | 2025-09-07 → 2026-09-07 | +0.1230R / 91 trades | ✅ |
| 2 | `universe_25_baseline` | **8** | 2025-09-08 → 2026-09-08 | +0.1230R / 91 trades | ✅ |
| 3 | `universe_24_ex_meta` | **13** | 2025-09-08 → 2026-09-08 | +0.1278R / 84 trades | ✅ |
| 4 | `universe_25_meta_continuity_corrected` | **18** | 2025-09-08 → 2026-09-08 | +0.1230R / 91 trades | ✅ |

*(These sealed numbers appear here for **disposition and disclosure only**, as R1
permits and MAP §4.2 item 10 requires. No design choice in §1–§9 is derived from them;
every motivating number in §3 is pre-sealed.)*

**Count.** The baseline is **k = 5** for this strategy (four locked sealed tests, plus
the program's convention that the next seal is counted from there). A v0.2.0 sealing on
snapshot 3 is therefore **look 6**, and a v0.2.0 additionally evaluated on any expanded
snapshot would be looks **6 and 7**. *(Recorded discrepancy: the hardening spec §9 fixes
`k_prior = 4, this_look = 5`; MAP §4.2 item 10 and the brief governing this proposal say
baseline k = 5 → look 6. This proposal uses **look 6** and flags the convention clash for
the operator to settle once, before any counter ships.)*

**Pre-registered reporting snapshot (R1).** The report will lead with **snapshot 3**,
because it is the only snapshot on which gate 8 passes for any version (META has 90
missing sessions on snapshots 1–2; `META_CONT` is `continuity_bridge:1`, not `massive`,
on snapshot 4) — a pre-sealed data-quality reason, fixed before the run — **and it will
print the full four-row table above alongside the new result in every case.** A pass, if
one ever occurred, would be reported as "passed on look 6", never as an unqualified pass.

**Warning specific to this strategy, restated from MAP §2.2.** Gate 9 already passes on
all four snapshots at +0.1230–0.1278R. A v0.2.0 that fixed gates 3/4/5/7 would inherit a
friendly gate 9, so **gate 9 provides no independent check here**. That asymmetry is the
strongest argument for the tight variant cap in §9 and for the honesty of §11.

---

## 11. Null option

**What it is.** A documented, evidence-backed **"does not pass"** for
`mean_reversion.short_swing`, written from the exits-and-risk side, with **no v0.2.0
shipped, no sealed look consumed, and the strategy left EXPERIMENTAL**. Under §9's
stopping rule this is the outcome whenever F1 or F2 fails, and it is also the correct
outcome if a variant survives falsification but leaves the OOS point estimate negative
— which §5 forecasts.

**The evidence it would carry** (all of it already exists or is generated by the
sealed-look-free steps in §9):

1. The exit-geometry ledger: target **+0.2114R**, leash **+0.0410R**, stop **−0.3139R**
   — the entire deficit is the stop bucket, and the two obvious exit levers are refuted
   (tracking target −0.0032R ± 0.0040; leash net positive).
2. The anchor defect and its size: 6.61% ± 0.79% of trades at −0.6710R ± 0.2141 vs
   −0.0190R ± 0.0251 (t = −3.02), five trades whose "stop" sits above the fill, four of
   them booked as stop *wins*, one at −3.099R off a 2.9-cent risk unit.
3. The ceiling: even *perfectly* removing the tail leaves pre-sealed −0.0190R ± 0.0251
   and OOS −0.0213R ± 0.0449 — indistinguishable from zero, and still short of gate 3's
   `> 0`, gate 4's **+0.1115R** at n = 309 and gate 7's **+0.0596R**.
4. The structural verdict: gates 4 and 7 are **point-estimate** gates for this strategy,
   so neither universe expansion nor any exit rule of this magnitude can reach them;
   and gate 1 currently passes at **+0.32 SE**, so the strategy is one noisy fold from
   failing a gate it nominally clears.
5. The disposition note (R1-marked): the sealed year passes on all four snapshots at
   +0.1230–0.1278R, which is exactly why the ladder is ordered as it is — a calm bull
   year is the regime this dip-buy is built for, and the nine-year pre-sealed record
   says that regime is the exception.

**A dissenting recommendation worth putting in front of the judges.** Even under the null
option, the §2.1 engine change has value **independent of this strategy**: a stop that
can sit above the fill, and a risk unit that can collapse to 0.0043 ATR and render a
5.5 bps slippage as −3.099R, is a defect in the shared execution model that flatters or
punishes *any* strategy whose entries cluster on gap-prone days. Shipping it as an
engine correctness fix with **no strategy version bump** — behaviour-preserving by
default, opt-in per strategy, and therefore consuming **zero** sealed looks and leaving
v2/v5 provably untouched (§5.6) — is a legitimate outcome that is neither a promotion
attempt nor a null result. It is offered as an option for the operator, not assumed.

**What the null option is not.** It is not "keep trying". This strategy has 0 of 9
gate-5 cells positive, a −0.749 full-span Sharpe, and a sealed year that cannot
contradict a bad promotion. If this angle's two variants and the other two angles'
budgets are exhausted without a pre-sealed positive that survives falsification on all
four snapshots, the honest output is the documented fail — and per MAP §2.2 lever 5,
this is the strategy in the program most likely to manufacture a spurious pass if the
programme keeps trying.

---

## Appendix — reproduction log

Read-only re-runs (`sqlite+pysqlite:///file:…/data/signalforge.sqlite?mode=ro&uri=true`,
`run_strategy_over_universe`, source `massive`, proxy SPY, `min_bars = 60`,
`CostModel()` defaults, window 2016-09-10 → 2025-09-07):

| Snapshot | symbols | pre-sealed n / exp | OOS n / exp | matches |
|---|---|---|---|---|
| 3 `universe_24_ex_meta` | 24 | 984 / −0.0621R (SE 0.0278) | 309 / −0.0837R (SE 0.0467) | eval 34 gates 2, 3, 7 |
| 2 `universe_25_baseline` | 25 | 999 / −0.0622R (SE 0.0275) | 320 / −0.0782R (SE 0.0454) | eval 28 gates 2, 3 |
| 1 window (ends 2025-09-06, a Saturday) | 25 | identical to snapshot 2 | identical | — |
| 4 | — | **not run** (`META_CONT` is `continuity_bridge:1`, excluded by R6 source isolation) | — | required by F5 before implementation |

Per-trade risk units were recovered by recording each `EntrySignal`'s `stop_price` and
`ATR(14)` through a wrapper on `MeanReversion.evaluate` in the analysis process only —
no repository file was modified. Full outputs, including the fold tables, the cost
distributions and the five inverted-stop rows, are in
`mean_reversion_short_swing--exits_risk.json` beside this file.

*Proposal only. No strategy code, configuration, gate threshold, cost-model constant or
database row was changed in producing this document, and no sealed look was consumed.*
