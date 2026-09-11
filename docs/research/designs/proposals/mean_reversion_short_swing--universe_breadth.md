# Proposal — `mean_reversion.short_swing` v0.2.0, universe/statistical-power angle

**Strategy:** `mean_reversion.short_swing` v0.1.0 (`strategy_version` id **4**)
**Angle:** universe breadth / cross-sectional conditioning (MAP §4.1, v4 slot 3)
**Hypothesis addressed:** **H7** (systemic vs idiosyncratic dips), MAP §2.2
**Status of this document:** a Phase-2 *proposal*. Nothing was implemented. No file
under `src/` or `tests/` was modified, no package installed, no provider API called,
and **no write of any kind reached `data/signalforge.sqlite`** — every number below
came from a read-only SQLAlchemy engine
(`sqlite+pysqlite:///file:data/signalforge.sqlite?mode=ro&uri=true`) driving
`PriceSeries.load`, `research.regime.regime_lookup`, `strategies.base.signal_fn_for`,
`backtest.engine.run_backtest`, `backtest.regime.label_regimes` and
`research.portfolio_metrics.compute_portfolio_metrics`, none of which contain
`session.add` / `flush` / `commit`.

**Sealed-look cost of this document: zero.** Gate 9 was never evaluated; no
`StrategySealedTest` row was created or read into any argument below. The baseline
count remains **k = 5** (§10).

**Claim labelling.** **FACT** = verified against a `file:line` or a query/computation
run for this document. **DERIVED** = arithmetic on FACTs, derivation shown.
**HYPOTHESIS** = an inference a later phase must test. Every estimate carries a
standard error; **a difference under 2 SE is not evidence** (MAP §0.3).

---

## 0. Headline, stated before the detail

I ran the H7 falsification test that MAP §2.2 pre-registered, read-only, on the
**pre-sealed span only**, on **all four dataset snapshots**. The result:

> **The mechanism has the right sign and nowhere near enough magnitude on the
> current 24-symbol universe, and the filtered strategy acquires a *new* gate
> failure (gate 6) while still failing gates 3 and 7.**

| Measured, snapshot 3, pre-sealed | value |
|---|---|
| gradient: expectancy(breadth ≤ 3/24) − expectancy(breadth ≥ 4/24) | **+0.0979R**, se_iid 0.0567 (**+1.73 SE**), se_clustered 0.0990 (**+0.99 SE**) |
| filtered variant, all pre-sealed | n = 312, **+0.0048R ± 0.0446** (indistinguishable from zero) |
| filtered variant, **OOS** (gates 2/3/4) | n = 142, **−0.0335R ± 0.0684** → **gate 3 FAILS** |
| filtered variant, gate 6 buckets | bull 202 / **bear 5** / range 73, unbucketed 32 → **gate 6 FAILS** (was passing at bear 46) |
| filtered variant, gate 7 Sharpe | **+0.036** vs SPY **+0.719** → **gate 7 FAILS** (large improvement from −0.749, still 0.683 short) |

This proposal therefore does **not** ask for a v0.2.0 on the current universe. It
asks for the same battery to be re-run **read-only on W1's 150-symbol snapshot**,
where the breadth statistic is not degenerate, with four pre-registered killing
observations (§4) that on today's evidence are more likely than not to fire. A
`StrategyVersion` is created — and look 6 spent — **only if all four survive**.

The expected outcome of this angle is the **null option (§11)**. It is written as a
real proposal because the diagnostic is cheap, the mechanism is the only one of
v4's four hypotheses that has not been tested at all, and the null it produces is
substantive rather than an absence of effort.

---

## 1. Mechanism

A −2σ single-day drop in one name means two different things depending on what the
rest of the market did that day. If the name fell alone, the move is idiosyncratic:
liquidity demand, a stale quote, a single-name headline that the crowd will
reprice over the next few sessions. Mean reversion is a bet that the seller was
impatient, and impatience is a property of *one* seller. If instead a third of the
universe printed −2σ on the same session, the drop is not one impatient seller — it
is a common factor repricing: a macro release, a rate shock, a systemic
de-risking. There is no counterparty waiting to pay up for the dip, because the
same information hit everyone. Buying the second kind of dip is adverse selection
dressed as a discount: the strategy is systematically selling liquidity into the
one state where liquidity is genuinely scarce and the repricing is permanent.

This is **H7** exactly as MAP §2.2 states it, and it is the only one of v4's four
hypotheses with no diagnostic in
`docs/research/diagnostics/`. H6 and H9 are refuted
(`v4_regime_vol_stationarity.md`: filtering to LOW vol moves OOS expectancy
−0.0837R → −0.0754R, **+0.16 SE**, and the whole HIGH-vol penalty is one fold).
H8 survives its own kill test by 3.1 SE but three of its four component claims are
refuted (`v4_mfe_target.md`). H7 is what is left.

**Why breadth is not a relabelling of H6's vol filter.** These are different
conditioning variables and they disagree. `RegimeState.vol` is a property of the
**proxy's own trailing realised volatility** relative to a self-rebasing median
(`regime.py:78-84`), i.e. a slow, market-level state that persists for weeks;
36.7% of pre-sealed proxy sessions carry it. Breadth is a **same-session
cross-sectional count**: FACT (computed) only **2.57%** of the 2,214 pre-sealed
sessions with a valid z panel have ≥ 8 of 24 members at z ≤ −2.0, and **5.6%** have
≥ 4. A vol filter removes long stretches of calendar; a breadth filter removes
individual days. That said, the two are not orthogonal, and §3.4 reports how much of
the breadth gradient is really H6 wearing a different hat.

**What the mechanism predicts, mechanically.** FACT (computed, snapshot 3,
pre-sealed): **48.8% of v4's trades (480 of 984) are entered off signal dates on
which ≥ 8 of 24 members are simultaneously at z ≤ −2.0** — dates that are only
**2.39%** of the span (53 of 2,214). The entry rule is not merely exposed to
systemic days; it is concentrated on them by roughly 20×, because a market-wide
−2σ session makes 8–24 members fire at once. If H7 is right, that concentration is
where the money goes. It is.

---

## 2. Exact change (file, symbol, before → after)

Four files change; a fifth (`scan.py`) is a live-path change discussed in §7 and
deliberately **not** bundled. New behaviour ships as `VERSION = "0.2.0"` (R3/R7);
v0.1.0 is untouched.

### 2.1 `src/signalforge/research/strategies/base.py` — the shared-surface change

**This is the change the angle exists to justify, and it touches every strategy.**
FACT (`base.py:15-19`): `StrategyContext` carries `regime` and `allow_short` only —
nothing in it is universe-wide, which is precisely why MAP §2.2 lever 4 is scored
"highest implementation cost".

Before (`base.py:15-19`, `:29-44`):

```python
@dataclass(frozen=True, slots=True)
class StrategyContext:
    regime: RegimeState
    allow_short: bool = False

def signal_fn_for(strategy, *, regime_by_date=None, allow_short=False) -> SignalFn:
    regimes = regime_by_date or {}
    def _fn(series, t):
        stamp = series.dates[t]
        key = stamp.date() if isinstance(stamp, datetime) else stamp
        regime = regimes.get(key, NEUTRAL)
        return strategy.evaluate(series, t, StrategyContext(regime=regime, allow_short=allow_short))
    return _fn
```

After:

```python
@dataclass(frozen=True, slots=True)
class UniverseBreadth:
    """Point-in-time cross-sectional state of the *run's own* symbol list.

    Computed only from bars dated <= as_of. `n_members` counts symbols with a
    defined 20-day return z-score on this session; `n_extreme` counts those at
    z <= EXTREME_Z. Never constructed from the sealed window in research runs.
    """
    as_of: date
    n_members: int
    n_extreme: int

    @property
    def frac_extreme(self) -> float:
        return self.n_extreme / self.n_members if self.n_members else float("nan")

EXTREME_Z = -2.0          # module constant, NOT a strategy parameter — see 2.3

@dataclass(frozen=True, slots=True)
class StrategyContext:
    regime: RegimeState
    allow_short: bool = False
    breadth: UniverseBreadth | None = None        # NEW, defaulted -> back-compatible

def signal_fn_for(strategy, *, regime_by_date=None, allow_short=False,
                  breadth_by_date: Mapping[date, UniverseBreadth] | None = None) -> SignalFn:
    regimes = regime_by_date or {}
    breadths = breadth_by_date or {}
    def _fn(series, t):
        stamp = series.dates[t]
        key = stamp.date() if isinstance(stamp, datetime) else stamp
        return strategy.evaluate(series, t, StrategyContext(
            regime=regimes.get(key, NEUTRAL),
            allow_short=allow_short,
            breadth=breadths.get(key),            # None when not supplied
        ))
    return _fn
```

**Back-compatibility, verified.** FACT: the five other strategies never read
`ctx.breadth`, so their behaviour is byte-identical. FACT
(`persistence.py:29`, `:32-43`): `spec_json_hash` hashes `asdict(spec)` minus
`{"git_sha", "status", "notes"}` — it hashes the **`StrategySpec`**, which is
produced from a strategy's own params and `VERSION`. `StrategyContext` is not part
of `StrategySpec`, so **this change cannot move v2's or v5's
`current_spec_json_hash()`** and cannot break their live approved scopes (R7).
This is the same constraint `pipeline_hardening_spec.md` identified for the
axis-declaration mechanism ("must live OFF `StrategySpec`"); this design satisfies
it by construction. A pre-integration assertion is still required (§5, checklist).

### 2.2 `src/signalforge/research/backtest_runner.py` — building the panel

FACT (`backtest_runner.py:167`, `:184-185`, `:194-207`): the runner loads the proxy,
builds `regimes = regime_lookup(proxy)`, builds `fn = signal_fn_for(...)`, and only
then loads each symbol inside the per-symbol loop. The breadth panel needs every
member's series **before** the first backtest, so the loop is split in two:

Before (`:194-207`, abridged):

```python
for sym in symbols:
    series = PriceSeries.load(session, sym, start, end, source=source)
    if len(series) < min_bars: continue
    outcome = run_backtest(series, fn, cost_model=cost_model, warmup=min_bars // 2)
```

After:

```python
loaded: dict[str, PriceSeries] = {}
for sym in symbols:
    series = PriceSeries.load(...)          # unchanged loader, unchanged source filter
    if len(series) >= min_bars: loaded[sym] = series

breadth_by_date = build_breadth_panel(loaded)     # new module-level helper, below
fn = signal_fn_for(strategy, regime_by_date=regimes, allow_short=allow_short,
                   breadth_by_date=breadth_by_date)

for sym, series in loaded.items():
    outcome = run_backtest(series, fn, cost_model=cost_model, warmup=min_bars // 2)
```

with

```python
def build_breadth_panel(loaded: Mapping[str, PriceSeries]) -> dict[date, UniverseBreadth]:
    counts: dict[date, list[int]] = {}          # date -> [n_members, n_extreme]
    for series in loaded.values():
        for t in range(len(series)):
            z = zscore_last_return(series, t, _BREADTH_Z_LOOKBACK)   # 20, fixed
            if z != z:                                                # NaN -> not a member
                continue
            d = _as_date(series.dates[t])
            c = counts.setdefault(d, [0, 0])
            c[0] += 1
            if z <= EXTREME_Z:
                c[1] += 1
    return {d: UniverseBreadth(as_of=d, n_members=c[0], n_extreme=c[1])
            for d, c in counts.items()}
```

**Two properties this shape is chosen for.**

1. **Memory.** 150 symbols × ~2,500 bars of `PriceSeries` held at once, versus one at
   a time today. DERIVED: at 5 float64 OHLCV arrays + dates, ≈ 2,500 × 5 × 8 B ≈
   100 kB of numeric payload per symbol, ≈ 15 MB for 150 — not a constraint, but it
   is a real change from the current streaming shape and must be stated.
2. **Cost inside gate 5.** FACT (`sensitivity.py:148-160`): gate 5 calls
   `run_strategy_over_universe` **once per grid point**. A 27-point grid (§6) would
   rebuild the panel 27 times. Because the panel depends only on
   `(symbols, start, end, source)` and **not on any strategy parameter** (§2.3), it
   must be memoised on exactly that key. Without the memo, gate 5 on 150 symbols is
   27 × 150 = 4,050 series loads plus 27 full z-panel builds.

### 2.3 `src/signalforge/research/strategies/mean_reversion.py`

| Symbol | Before | After |
|---|---|---|
| `VERSION` (`:17`) | `"0.1.0"` | **`"0.2.0"`** |
| `MeanReversionParams` (`:20-27`) | `z_lookback=20, z_entry=-2.0, sma_window=20, atr_window=14, stop_atr=2.0, time_stop_bars=6` | **unchanged, plus `breadth_max_frac: float = 0.125`** |
| `evaluate` (`:88`) | `if z <= p.z_entry and close < mean and ctx.regime.trend is not Trend.BEAR:` | `if ctx.breadth is None: return None` *(fail-closed, see below)*, then `if z <= p.z_entry and close < mean and ctx.regime.trend is not Trend.BEAR and ctx.breadth.frac_extreme <= p.breadth_max_frac:` |
| `spec()` (`:44-61`) | rule/entry strings as today | strings regenerate from params automatically; `entry_conditions` gains `and universe_breadth_frac(z<=-2.0) <= {p.breadth_max_frac}`; `feature_definitions` gains `breadth = #{{z_ret <= -2.0}} / #{{z_ret defined}} over the run's symbol list` |

Everything else — stop `close − 2.0×ATR(14)`, frozen `SMA(20)` target, 6-bar leash,
long-only, `Trend.BEAR` exclusion — is **unchanged**. This proposal adds exactly one
condition and exactly one parameter.

**`EXTREME_Z = -2.0` is deliberately a module constant, not a strategy parameter,
and not `p.z_entry`.** Three reasons: (a) the breadth panel must be invariant across
gate 5's `z_entry` axis, or every grid point silently re-defines the conditioning
variable and the memo in §2.2 becomes unsound; (b) breadth is a property of the
*market*, not of this strategy's trigger, and coupling them would make the same
calendar day "systemic" for one grid point and not another; (c) it keeps the number
of new tunable parameters at exactly one, which is what R5 and §6 want.

**Fail-closed on `ctx.breadth is None`.** If breadth is absent the strategy returns
`None` rather than falling through to v0.1.0 behaviour. This is the choice that
prevents the worst failure mode available here: a v0.2.0 that is researched *with* a
breadth filter and operated *without* one, because the live scan constructs
`StrategyContext` directly and would pass `breadth=None`
(`scan.py:269-272`). Fail-closed makes that divergence a visible zero-signal
condition instead of a silent reversion to the un-filtered rule. See §7.

### 2.4 `src/signalforge/research/strategies/__init__.py:43-51`

`default_strategies()` has 6 entries. Registering the v0.2.0 sibling is one added
line. FACT (R7): v0.1.0's row is never mutated — `upsert_strategy_version`
(`persistence.py:46-93`) keys on the version string, so `"0.2.0"` creates a **new**
`StrategyVersion` row and therefore a never-before-sealed gate 9.

### 2.5 `src/signalforge/research/promotion.py:189-197` — the gate-5 grid

Before: `{"z_entry": [-2.5, -2.0, -1.5], "stop_atr": [1.5, 2.0, 2.5]}` (9 points).
After: **`{"z_entry": [-2.5, -2.0, -1.5], "stop_atr": [1.5, 2.0, 2.5],
"breadth_max_frac": [0.08, 0.125, 0.20]}`** (27 points).

FACT (`sensitivity.py:29`): `MAX_GRID_POINTS = 120`, so 27 is accepted.
FACT (`sensitivity.py:99-113`): `_is_neighbour` handles any number of axes — a point
differing on exactly one axis by one grid step. Adding an axis takes gate-5 coverage
for this strategy from **2 of 6** to **3 of 7** `MeanReversionParams` fields
(MAP §0.5) and is a *strictly more searching* gate, permitted under R4.
The grid is keyed on the `mean_reversion` **prefix** (`promotion.py:189`), so it
applies to v0.1.0 too — but v0.1.0's params have no `breadth_max_frac` and
`_replace` would raise `TypeError` (`promotion.py:50`; MAP §2.1 verifies the raise).
**The plan must therefore branch on `hasattr(base, "breadth_max_frac")`**, keeping
the 9-point grid for v0.1.0 and using the 27-point grid for v0.2.0. Getting this
wrong is a loud crash, not a silent pass — the safe direction — but it would block
any re-evaluation of v0.1.0 and must be handled in the same commit.

---

## 3. Pre-sealed evidence, with standard errors

### 3.1 Provenance and the reproduction check

All numbers are computed over the pre-sealed span only. FACT
(`strategy_sealed_test` ids 8, 13: `window_start = 2025-09-08`;
`promotion.py:555`: `pre_sealed_end = sealed_start − 1 day`): the span is
**2016-09-10 .. 2025-09-07** on snapshots 2, 3, 4 and **2016-09-10 .. 2025-09-06**
on snapshot 1. Configuration replicated from evaluation id 34: symbols from
`data_snapshot`, `source="massive"`, proxy `SPY`, `CostModel()` defaults (11.0 bps
round trip), `warmup=30`, `min_bars=60`, per-symbol IS/OOS cut at 60% of that
symbol's own bars.

**Reproduction is exact** — this is the validity check for everything below:

| | stored gate value (eval 34) | recomputed here |
|---|---|---|
| snap 3 pre-sealed trades (gate 7 set) | 984 | **984** |
| snap 3 OOS trades (gate 2) | 309 | **309** |
| snap 3 OOS expectancy (gate 3) | −0.0837R | **−0.0837R** |
| snap 3 gate-6 buckets | bull 618 / bear 46 / range 260, 60 unbucketed | **618 / 46 / 260, 60** |
| snap 3 gate-7 Sharpe | −0.749 vs SPY +0.719 | **−0.749 vs +0.719** |
| snap 3 distinct signal dates | 352 (`v4_regime_vol_stationarity.md` §4) | **352** |

### 3.2 The H7 gradient — measured, on all four snapshots

`k` = number of the run's symbols at `zscore_last_return(20) ≤ −2.0` on the
**signal bar** (the bar the strategy's `evaluate` saw; `engine.py:99,129` fills at
`t+1`, so `SimTrade.entry_date` is one bar later). `se_cl` clusters on the calendar
signal date, the axis `clustered_bootstrap_all.md` establishes as the right one for
this universe.

**Snapshot 3, all pre-sealed (n = 984):**

| bucket | n | clusters | expectancy | sd | se_iid | se_cl |
|---|---|---|---|---|---|---|
| k = 1 (purely idiosyncratic) | 151 | 151 | **−0.0350R** | 0.7793 | 0.0634 | 0.0636 |
| k = 2–3 | 161 | 91 | **+0.0421R** | 0.7972 | 0.0628 | 0.0821 |
| k = 4–7 | 192 | 57 | **−0.0276R** | 0.8348 | 0.0602 | 0.0911 |
| **k ≥ 8 (systemic)** | **480** | **53** | **−0.1193R** | 0.9349 | 0.0427 | **0.1120** |

**The headline contrast, on every snapshot:**

| snapshot | pre-sealed n | k ≤ 3 | k ≥ 4 | difference | iid | clustered |
|---|---|---|---|---|---|---|
| 1 `universe_25_baseline_legacy` | 999 | +0.0091R ± 0.0438 (n=319) | −0.0957R ± 0.0347 (n=680) | **+0.1048R** | 0.0559 → **+1.88 SE** | 0.0979 → **+1.07 SE** |
| 2 `universe_25_baseline` | 999 | +0.0091R ± 0.0438 (n=319) | −0.0957R ± 0.0347 (n=680) | **+0.1048R** | 0.0559 → **+1.88 SE** | 0.0979 → **+1.07 SE** |
| 3 `universe_24_ex_meta` | 984 | +0.0048R ± 0.0446 (n=312) | −0.0931R ± 0.0350 (n=672) | **+0.0979R** | 0.0567 → **+1.73 SE** | 0.0990 → **+0.99 SE** |
| 4 `universe_25_meta_continuity_corrected` | 984 | +0.0048R ± 0.0446 (n=312) | −0.0931R ± 0.0350 (n=672) | **+0.0979R** | 0.0567 → **+1.73 SE** | 0.0990 → **+0.99 SE** |

(Snapshot 4 loads 24 symbols under `source="massive"`: `META_CONT` carries
`continuity_bridge:1` and returns no bars, which is why it reproduces snapshot 3
exactly. That is the same fact that fails gate 8 there — MAP §0.1.)

**Reading, stated against the program's own rule.** The sign is right and stable on
all four snapshots. The magnitude is **+1.73 to +1.88 SE on the iid measure and
+0.99 to +1.07 SE clustered**. MAP's binding rule is *"a difference under 2 SE is not
evidence"*. **On the honest (clustered) measure this is not evidence, and even on the
generous iid measure it does not clear the bar.** I am not going to describe a
1.7-SE effect as a finding.

### 3.3 The number that decides the lever — what the *filtered* strategy earns

The design question is not "is systemic worse" but "what does the filtered strategy
make". Snapshot 3, sweeping the threshold:

| filter | pre-sealed n | pre-sealed exp | OOS n | **OOS exp** | se_iid | se_cl | folds ≥15 & >0 |
|---|---|---|---|---|---|---|---|
| none (v0.1.0) | 984 | −0.0621R ± 0.0278 | 309 | **−0.0837R** | 0.0467 | 0.0871 | 2/4 |
| k ≤ 1 | 151 | −0.0350R ± 0.0634 | 75 | **−0.0636R** | 0.0914 | 0.0914 | **2/4** |
| k ≤ 2 | 264 | −0.0430R ± 0.0477 | 124 | **−0.0497R** | 0.0738 | 0.0779 | **1/4 → gate 1 FAILS** |
| **k ≤ 3 (= frac 0.125)** | **312** | **+0.0048R ± 0.0446** | **142** | **−0.0335R** | 0.0684 | 0.0766 | **2/4 (bare)** |
| k ≤ 4 | 365 | +0.0075R ± 0.0409 | 178 | **−0.0410R** | 0.0604 | 0.0731 | **1/4 → gate 1 FAILS** |
| k ≤ 5 | 420 | +0.0062R ± 0.0395 | 204 | **−0.0387R** | 0.0572 | 0.0659 | **1/4 → gate 1 FAILS** |

Walk-forward folds at `k ≤ 3` (gate 1 needs 2 of 4 with n ≥ 15 and exp > 0):
F1 −0.0410 (n=78), F2 **+0.1848** (n=54), F3 −0.0930 (n=69), F4 **+0.0102** (n=111).

**Three things this table settles.**

1. **No threshold produces a positive OOS expectancy.** Gate 3 needs `> 0`. The best
   is −0.0335R. Gate 4 needs a CI low `> +0.02R` and, per MAP §0.3's arithmetic,
   **no n fixes a negative point estimate** — required n is *never* at every
   threshold in the table.
2. **The pre-sealed sign flip at k ≤ 3 is a 0.11-SE event, not a discovery.**
   +0.0048R ± 0.0446 is a strategy with exactly zero edge. After the modelled
   0.028R/trade cost (§8) that is a gross edge of ~+0.031R entirely consumed by
   frictions — the identical conclusion `v4_regime_vol_stationarity.md` §3.4 reached
   for the vol filter (+0.0005R ± 0.0511).
3. **Gate 1 is at zero margin and flips on the adjacent grid values.** 2/4 at
   `k ≤ 3` (with F4 clearing by +0.0102R), 1/4 at both `k ≤ 2` and `k ≤ 4`. Since
   `breadth_max_frac` becomes a gate-5 axis (§6) and gate 1's per-fold floor is the
   *same constant* as gate 5's per-cell floor (`promotion.py:632`,
   `th.sensitivity_min_grid_trades = 15`; MAP §4.3), this is not an academic point:
   the parameter's own neighbours flip gate 1.

### 3.4 Why the current universe cannot answer this question — the degeneracy, quantified

MAP §2.2 warns that with 15 of 24 snapshot-3 symbols being ETFs, "several of which
contain the other 9", a breadth term is "near-degenerate". Measured:

- FACT: the z panel has a stable denominator — 2,214 pre-sealed sessions, member
  count min 23 / median 24 / max 24.
- FACT: **on the 81 sessions where SPY itself is at z ≤ −2.0, mean k = 10.90; on the
  other 2,133 sessions, mean k = 0.36.** Breadth on this universe is, to a very good
  approximation, a **binary indicator of "SPY had a −2σ day"** — which is a
  *market-level* variable, not a cross-sectional one.
- FACT: corr(ETF-only breadth fraction, single-name-only breadth fraction) = **0.752**.
- FACT: `k ≥ 8` occurs on **2.57%** of sessions (53 dates carry 480 of the 984
  trades). The systemic bucket's 480 trades sit in **53 clusters** — an average of
  9.1 trades per date, and its clustered SE is **2.6× its iid SE** (0.1120 vs
  0.0427).

**Consequence, and the reason this angle needs W1.** What I measured on the current
universe is not "systemic vs idiosyncratic dips". It is closer to "SPY down 2σ vs
not", computed on a universe in which the majority of members are baskets of the
minority. A genuine cross-sectional breadth statistic needs a denominator of
independent single names. W1's pre-registered snapshot supplies exactly that: FACT
(`w1_universe_preregistration.md` §3) **150 symbols = the 15 snapshot-3 ETFs
verbatim + 135 common stocks**, taking the ETF share from **62.5% → 10%**, with
`list_date ≤ 2016-10-17` so every member's history starts on the same date and the
breadth denominator is stable from bar one.

### 3.5 Non-monotonicity — the strongest single argument against the mechanism

If H7 is a real mechanism, expectancy should fall as breadth rises. Measured against
the *single-name* count (`k_cs`, denominator 9), snapshot 3, all pre-sealed:

| k_cs | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---|---|---|---|---|---|---|---|---|---|
| n | 152 | 269 | 151 | 109 | 93 | 95 | 58 | 7 | 34 | 16 |
| exp | +0.0121 | −0.0883 | +0.0947 | −0.0788 | **+0.2655** | **−0.2279** | −0.5717 | +1.8720 | −0.7640 | −0.1170 |
| se | 0.0580 | 0.0523 | 0.0639 | 0.0628 | 0.0710 | 0.0819 | 0.1831 | 0.8749 | 0.1080 | 0.0462 |

This is not a gradient; it is noise with a downward drift in the far tail. Adjacent
buckets swing by 0.49R (k_cs 4 → 5). The `k = 1` bucket in §3.2 is **worse** than
`k = 2–3` (−0.0350R vs +0.0421R), which the mechanism does not predict. Any
threshold placed inside this series is placed on sampling variation. This is exactly
why §4 pre-registers monotonicity as a falsifier and why §6 makes
`breadth_max_frac` a gate-5 axis rather than a fixed choice.

### 3.6 Honest accounting of how the baseline value was chosen (R5)

**`breadth_max_frac = 0.125` was selected after seeing the §3.3 sweep** — it is the
threshold at which pre-sealed expectancy first turns non-negative. That is legitimate
under R1 (pre-sealed data is the design surface) and it is exactly the multiple-testing
cost R5 exists to record. Consequences, stated rather than buried:

- The baseline grid point is **selection-contaminated**. Its gate-5 result is not an
  independent robustness measurement.
- **The neighbour fraction (`0.08`, `0.20`) is the primary robustness statistic for
  this proposal**, not the baseline point. The proposal should be judged on it.
- The sweep is disclosed in the variant ledger (§9) as **one mechanism explored at
  five thresholds**, not as five variants — no version was created, no sealed test
  touched, and only one threshold is carried forward.

---

## 4. Falsification — stated before the W1 run, across all four snapshots

MAP §2.2's stated falsifier for H7 is: *"falsified if conditioning entries on the
fraction of the universe simultaneously at z ≤ −2 shows no expectancy gradient on
pre-sealed data."*

**On the current universe that test has now been run, on all four snapshots, and
the result is reported in §3.2–§3.5: the gradient exists in sign, fails the
program's own 2-SE bar (iid +1.73 to +1.88 SE; clustered +0.99 to +1.07 SE), is
non-monotone, and is contaminated by the ETF degeneracy of §3.4.** I treat that as
"not falsified, but not evidence either" — the four-snapshot requirement of R10 is
discharged by that run, and the mechanism is passed to W1 rather than to a v0.2.0.

The following four conditions are pre-registered **now**, before W1's data exists.
They are evaluated **read-only** on the 150-symbol snapshot (`run_strategy_over_universe`
with a `MeanReversion(breadth_max_frac=…)` instance, plus `label_regimes` and
`compute_portfolio_metrics` — the same read-only battery used for §3, costing **zero
sealed looks**). **If any one fires, this proposal is dead and §11 is written.**

| # | Killing observation (pre-sealed, 150-symbol snapshot) | Today's value on snap 3 |
|---|---|---|
| **F1** | The `frac ≤ 0.125` vs `frac > 0.125` difference is **< 2 SE on the date-clustered SE**, *or* is < 2 SE clustered with fold F2 excluded. The ex-F2 clause is mandatory: `v4_regime_vol_stationarity.md` §3.2 showed v4's entire vol effect lives in F2 and reverses without it, and the same trap is available here. | **+0.99 SE clustered → F1 fires today** |
| **F2** | The filtered variant's **OOS expectancy is ≤ 0**. Gate 3 needs `> 0`; gate 4 needs a CI low `> +0.02R`, which is unreachable from a negative point estimate at any n (MAP §0.3). | **−0.0335R → F2 fires today** |
| **F3** | Gate 6's **bear bucket under the filter is < 10** (reported with the unbucketed count, MAP §0.6). | **bear 5 → F3 fires today** |
| **F4** | Expectancy is **not weakly monotone decreasing across four pre-registered breadth quartiles** of the trade population (`frac` quartile boundaries computed on the pre-sealed panel before any P&L is looked at), *or* the top quartile is not the worst of the four. | **non-monotone (§3.5) → F4 fires today** |

**All four fire on the current universe.** That is the honest state of this proposal
and the reason §11 is written as the expected outcome rather than as a fallback. The
only claim being made is that the 150-symbol universe changes the *measurement*
enough to be worth one read-only re-run: the ETF share drops 62.5% → 10% (§3.4),
the denominator becomes 150 independent-ish names, `k ≥ 8` stops being a proxy for
"SPY fell", and the quartile buckets get ~6× the trades.

**A discipline this proposal binds itself to.** If the W1 re-run produces a
*different* threshold at which things look better, that is **not** a rescue — it is
the §3.6 selection performed a second time on a second universe. The pre-registered
baseline is `0.125` and the pre-registered grid is `{0.08, 0.125, 0.20}`. No value
outside that set may be adopted.

---

## 5. Gate-by-gate forecast, with trade sets

Two columns: **measured** = read-only recomputation on snapshot 3 pre-sealed
(a real number, not a forecast, and it cost zero looks); **forecast on W1** = the
prediction for the 150-symbol snapshot, using the ≈**6.25×** breadth multiplier
(MAP §3(a): 24 → ~150 symbols on the same ~9.4y span). Every forecast is tagged with
its trade set per MAP §0.2 — **gates 2/3/4 read OOS only; gates 1/6/7 read all
pre-sealed trades**, gate 7 included, despite its docstring (MAP §0.2 open item).

| Gate | Trade set | v0.1.0 today (snap 3) | **Measured**: v0.2.0 rule, snap 3 | **Forecast on the 150-symbol snapshot** |
|---|---|---|---|---|
| **0** data availability | — | pass (SHORT_SWING; pre-sealed span ≫ 350 days) | pass | **pass** — every member starts 2016-10-17 (W1 §2.4) |
| **1** walk-forward | all pre-sealed | 2 of 4 (bare) | **2 of 4** — F1 −0.0410/78, F2 +0.1848/54, F3 −0.0930/69, **F4 +0.0102/111** | **genuinely uncertain, zero margin.** Per-fold floor 15 is not binding (all folds ≥ 54 → ≥ ~340). Positivity is: F4 clears by 0.0102R and both neighbouring grid values give 1/4 (§3.3). **HYPOTHESIS: ~50/50** |
| **2** min OOS trades ≥ 30 | **OOS** | 309 | **142** | 142 × 6.25 ≈ **890** → **pass, comfortably** |
| **3** net expectancy > 0 | **OOS** | −0.0837R | **−0.0335R ± 0.0684** → **FAIL** | **FAIL predicted with high confidence.** Requires the composition change alone to move the point estimate by **+0.034R**; nothing in §3 suggests it will |
| **4** bootstrap CI low > +0.02R | **OOS** | [−0.1739, +0.0061] → FAIL | **FAIL.** Required n = `(1.96·sd/(exp−0.02))²` with sd = 0.815, exp = −0.0335 → **never** (negative point estimate) | **FAIL.** At n = 890 and sd = 0.815 the bar is `exp > 0.02 + 1.96×0.815/√890` = **+0.0736R**; observed −0.0335R, a gap of **+0.1071R ≈ 3.9 SE** at that n. Under the clustered haircut (deff 1.87× for v4 OOS, `v4_regime_vol_stationarity.md` §4 → variance ×3.5, n_eff ≈ 254) the honest bar is **+0.1202R**. **Required n at the observed estimate: never.** |
| **5** sensitivity ≥ 60% / ≥ 75% nbr, ≥ 15 per cell | OOS per grid point | **0/9 positive (0%)**, worst −0.1908R | not re-run (would be 27 read-only universe passes; deferred to the W1 battery) | **FAIL predicted with high confidence.** Every threshold in §3.3 is OOS-negative and the existing `z_entry × stop_atr` slice is 0/9. **Cell counts stop being binding** (today's thinnest cells ×6.25), so this is an edge verdict, not a power verdict. Report the **neighbour fraction** as primary (§3.6) |
| **6** ≥ 10 trades in each of bull/bear/range | all pre-sealed | bull 618 / **bear 46** / range 260; **60 unbucketed (6.1%)** | **bull 202 / bear 5 / range 73; 32 unbucketed (10.3% of 312)** → **FAIL — a new failure the filter creates** | 5 × 6.25 ≈ **31 bear → plausibly passes, must be measured.** The unbucketed count must be reported alongside: it rises as a *share* under the filter (6.1% → 10.3%) because the filter removes proportionally more post-warmup systemic-day trades. **HYPOTHESIS, not a forecast** |
| **7** Sharpe > SPY | all pre-sealed | **−0.749** vs +0.719 → FAIL by 1.468 | **+0.036** vs +0.719 → **FAIL by 0.683.** (CAGR +0.06%, ann vol 2.33%, maxDD 6.93%, turnover 35.1/yr, exposure 0.427 — against −3.48% / 4.59% / 37.93% / 110.8 / 1.000) | **FAIL expected.** Breadth does not move a risk-adjusted point estimate (MAP §3(a)). The filter's Sharpe gain is real and large but 0.68 short; composition could move it either way |
| **8** data quality + leakage | — | pass (snap 3 only) | pass | **pass, conditional on W1-COMPLETE** (`w1_universe_preregistration.md` §6.4; `NBIS` is the named drop risk). **Caveat: gate 8 gives the breadth feature no coverage at all** — §7 |
| **9** sealed | sealed year | +0.1278R / 84, passes on all four snapshots | — | **new sealed test; look 6** (§10). Gate 9 provides **no independent check for this strategy**: MAP §2.2 records that v4's sealed year already passes on all four snapshots, so a v0.2.0 that fixed gates 3/4/5/7 would inherit a friendly gate 9 |
| **10** probation | — | pass (`health_monitor.enabled`) | pass | pass |

**Effect on trade count, gathered in one place (mandatory, MAP §4.2 item 5).**
Snapshot 3: all pre-sealed **984 → 312 (−68.3%)**; OOS **309 → 142 (−54.0%)**;
per-fold **257/292/181/254 → 78/54/69/111**. Gate 5's 15-per-cell floor and gate 1's
15-per-fold floor (the *same* constant, `promotion.py:632`) are both comfortable at
these counts and would be very comfortable at 6.25×. **The binding constraint is
gate 6's bear bucket at 5, and no floor problem anywhere else.**

**Zero-margin cases carried forward (MAP §4.2 item 5, mandatory).**

- **v6's gate 5** passes at *exactly* `neighbour_fraction = 0.750` on snapshot 3 and
  already **fails at 0.500 on snapshot 4** (MAP §2.3). Unrelated to this proposal,
  but it is the standing warning that a 27-point grid can flip on universe change.
- **v5's bear bucket is 11 against a floor of 10** (MAP §4.2). This proposal must not
  disturb it: per `w1_universe_preregistration.md` §9.4, **v2 and v5 are prohibited
  from being evaluated on the expanded snapshot** (a passing scope on a second
  snapshot would make `paper_probation.py:118`'s `scopes[0]` order-dependent for a
  **live** strategy — R7b). Nothing in this proposal evaluates them.
- **New, discovered by this proposal:** **gate 1 at exactly 2 of 4 with F4 clearing
  by +0.0102R**, and **gate 6's bear bucket at 5 against a floor of 10**. Both are
  reported as zero-margin/failing cases in their own right.

---

## 6. Sensitivity-grid plan (pre-registered) and the no-op check

**Pre-registered axis.** `breadth_max_frac ∈ {0.08, 0.125, 0.20}`, chosen now,
before the W1 run, as a genuine ±1-step neighbourhood around the shipped value. It
is the **only** parameter this v0.2.0 introduces or changes, so MAP §4.2 item 6 is
satisfied by adding exactly this one axis. Full grid: `z_entry × stop_atr ×
breadth_max_frac` = **27 points** (cap 120, `sensitivity.py:29`). Coverage rises
from 2 of 6 to **3 of 7** `MeanReversionParams` fields (MAP §0.5).

**Why these three values.** On 24 symbols they map to `k ≤ 1`, `k ≤ 3`, `k ≤ 4`
(0.08×24 = 1.92; 0.125×24 = 3.0; 0.20×24 = 4.8); on 150 they map to `k ≤ 12`,
`k ≤ 18`, `k ≤ 30`. The fraction is the scale-free statistic, which is what makes
the same three numbers meaningful on both universes. The spread is wide enough to be
a real perturbation (§ below) and narrow enough not to degenerate into "no filter"
at the top end.

**The no-op check — required by MAP §4.2 item 6, and already performed on snapshot 3.**
The hazard is a retained-but-unused field: `_replace` succeeds, all grid points
return identical results, `positive_fraction` and `neighbour_positive_fraction` both
come back 1.0, and gate 5 passes at 100% having tested nothing
(MAP §2.1; the `len(evaluable) >= 4 and len(positive) <= 1` guard at
`sensitivity.py:199` does not catch it). **FACT (computed, snapshot 3, pre-sealed):
the three axis values produce OOS trade counts 75 / 142 / 178 and pre-sealed counts
151 / 312 / 365 — three distinct values on both measures, and OOS expectancies
−0.0636 / −0.0335 / −0.0410.** The axis is demonstrably live. The same check must be
repeated on the 150-symbol snapshot before integration, with the counts recorded, and
it must be an **assertion in the integration checklist**, not a glance at a table.

**Pre-integration checklist for this change** (all mechanical, all cheap):

1. Assert the three `breadth_max_frac` values give **distinct** OOS trade counts on
   the target snapshot (the no-op check above).
2. Assert `spec_json_hash` for **v2** (`trend_continuation.short_swing` v0.1.0) and
   **v5** (`relative_strength.medium_swing` v0.1.0) is byte-identical before and
   after the `StrategyContext` change (§2.1 argues it must be; assert it anyway —
   `pipeline_hardening_spec.md` records this as the mechanism that would
   "permanently break both live approvals").
3. Assert the v0.2.0's `StrategySealedTest.strategy_version_id` names a
   `StrategyVersion` row created by *this* run (R3's staleness trap, MAP §4.3).
4. Assert `_sensitivity_plan` still returns the **9-point** grid for a v0.1.0
   `MeanReversion` instance (§2.5's `TypeError` hazard).
5. Assert the breadth panel is memoised on `(symbols, start, end, source)` and that
   27 grid points build it **once** (§2.2).
6. Assert `build_breadth_panel` is invariant to the presence of bars after the panel
   date (§7's panel-level leakage test).

---

## 7. Leakage argument

**Point-in-time, per member.** FACT (`features/daily.py:67-74`):
`zscore_last_return(series, t, lookback)` calls `daily_returns(series, t, lookback)`
and reads `rets[-1]`, `rets.mean()`, `rets.std()` — all `t`-relative slices, no
absolute indexing, no `[-1]` on the full array. Each member's contribution to
`build_breadth_panel` at date `d` therefore uses only that member's bars ≤ `d`.

**Point-in-time, cross-sectionally.** The panel is a per-date aggregation of
per-date values. `UniverseBreadth(as_of=d)` counts only symbols that *had a bar on
`d`* and a defined 20-day z at `d`. No symbol contributes to a date it did not
trade on, and no date's count depends on any later date. FACT (computed): the
denominator is stable at 23–24 (median 24) across all 2,214 pre-sealed sessions on
snapshot 3, and W1's `list_date ≤ 2016-10-17` filter is designed to make it stable
at 150 from 2016-10-17 on the expanded snapshot.

**The gap this angle must own — `assert_no_lookahead` cannot cover a breadth term.**
FACT (`backtest/leakage.py:14-16, 23-41`): `assert_no_lookahead` takes a
`FeatureFn = Callable[[PriceSeries, int], float]` — a **single-series** feature —
and verifies `fn(series.head(t), t) == fn(series, t)`. A cross-sectional statistic
takes a *panel*, so it has the wrong type and **cannot be passed to the existing
detector at all**.

FACT, and it is worse than it sounds: `_leakage_self_check`
(`promotion.py:249-268`) runs `assert_no_lookahead` over a **hard-coded list of four
features** — `sma(50)`, `rolling_return(20)`, `atr(14)`, `realized_vol(20)` — on the
**proxy symbol only**. It does not check `zscore_last_return` today, and it would
not check a breadth panel. **Gate 8 provides this proposal's new feature with zero
leakage coverage**, and gate 8 would report `leakage self-check: clean` regardless.

**Required mitigation, and it is part of the change, not an afterthought.** A
panel-level analogue in `tests/`:

```
for each date d in the panel:
    full  = build_breadth_panel(all series)[d]
    trunc = build_breadth_panel({s: ser.head(index_of(d)) for s, ser in ...})[d]
    assert full == trunc
```

i.e. rebuild the panel from every series truncated at `d` and assert the entry for
`d` is identical. This is the direct panel generalisation of
`assert_no_lookahead`'s contract and it is the only thing that actually tests the
new surface. **Note under the hard rules of this phase: writing that test is a
`tests/` change and is therefore out of scope for this document — it is specified
here as a binding requirement on whoever implements the change.**

**Three biases the breadth term inherits, disclosed rather than solved.**

1. **Universe survivorship.** The panel's membership is the snapshot's symbol list,
   fixed as of the fetch date. Breadth at 2017-03-01 is computed over the symbols
   that were liquid and listed in **2026**, not the symbols that were liquid in
   2017. This is the same survivorship bias the whole program carries (gate 8's own
   `known_caveats` names it: *"the equities universe is a fixed hand-picked
   large-cap list"*), but a cross-sectional statistic is more exposed to it than a
   per-symbol feature is, because membership enters the **denominator**.
   W1 §5's pre-registered `description` records it explicitly:
   *"discovery was active-only, so the set is survivorship-biased"*.
2. **Split adjustment is as-of-fetch, not point-in-time.** Same source
   (W1 §5). Returns are adjusted-price returns throughout, so this does not
   introduce a *new* leakage channel; it is stated because the breadth count is a
   count of *return* extremes.
3. **Research/live denominator mismatch — the most serious item on this list.**
   FACT (`scan.py:269-272`): the live scan builds `StrategyContext(regime=…,
   allow_short=…)` with no breadth, over `cfg.research.universe` — **25 symbols**,
   not 150. Even if `scan.py` is plumbed, the live breadth denominator would be the
   25-name live universe, which is the degenerate 15-ETF panel of §3.4, not the
   150-name research panel the strategy would have been validated on. **A strategy
   whose edge is defined against a 150-name cross-section cannot be honestly
   operated against a 25-name one**, and expanding the live universe is an
   *operating* change explicitly out of scope (MAP §3(a): "not a change to
   `cfg.research.universe` or to any live approved scope"). The fail-closed
   `ctx.breadth is None → return None` of §2.3 makes the unplumbed case a visible
   zero-signal condition rather than a silent reversion to v0.1.0 behaviour — but it
   does **not** solve the mismatch. **This is a standing objection to the whole
   angle and a judge should weigh it as such:** even a passing v0.2.0 here would not
   be operable without a separate, operator-owned universe decision.

**Shared-surface change, called out as the angle requires.** `StrategyContext`
(`base.py:15-19`) is consumed by all six strategies via `signal_fn_for`
(`backtest_runner.py:185`) and constructed directly in `scan.py:269` and in eight
places across `tests/research/test_strategies.py` and
`tests/research/test_strategies_phase2.py`. Adding a **defaulted** field keeps every
one of those call sites valid. The change is nonetheless a shared-surface change and
should be reviewed on its own merits, with its own leakage audit (the panel test
above), independently of whether the v4 proposal proceeds — it is the plumbing MAP
§2.2 lever 4 identifies as the cost of the entire cross-sectional family.

---

## 8. Cost-model statement (quantitative)

**The cost model is unchanged.** FACT (`costs.py:11-16`):
`commission_per_share = 0.0`, `commission_min_per_order = 0.0`,
`slippage_bps = 3.0`, `half_spread_fill_penalty = True`. FACT
(`engine.py:90, 94`): `spread_bps = 5.0` default, `slip = (3.0 + 5.0/2)/10,000 =
5.5 bps` per side. FACT (`engine.py:143`): **11.0 bps round trip**, every trade in
the program. Every gate number in §5 was computed under exactly this model (R4).

**Per-trade cost in R at this proposal's `stop_atr`.** `stop_atr` is **unchanged at
2.0**, so at MAP §0.4's reference `ATR/price = 2%` the risk unit is 4.00% of price
and per-trade cost is `11.0/10,000 ÷ 0.04 = ` **0.028R** — unchanged from v0.1.0,
and still the lowest in the program in R terms. **The filter buys nothing on cost
per trade.** Note MAP §2.2's own conclusion: for v4, "cost is *not* the problem
here".

**Turnover delta (measured, snapshot 3, all pre-sealed).**

| | v0.1.0 | v0.2.0 at `frac ≤ 0.125` | delta |
|---|---|---|---|
| trades | 984 | 312 | **−68.3%** |
| `turnover_per_year` | 110.8 | **35.1** | −68.3% |
| `exposure` | 1.000 | **0.427** | −57.3% |
| total modelled cost paid | 984 × 0.028R = **27.6R** | 312 × 0.028R = **8.7R** | −18.9R |
| **cost per trade** | 0.028R | **0.028R** | **0.000R** |

Gates 3 and 4 read *per-trade* expectancy, so the cost delta that matters is
**zero**. The turnover reduction is a real operational benefit (fewer fills, lower
capacity strain) and a real statistical cost (fewer trades, §5 gate 2/5/6).

**Expanded-snapshot spread sensitivity at 2× and 5× (mandatory, MAP §3(a) /
§4.2 item 8).** Using `w1_universe_preregistration.md` §7.1's mechanism — raise
`CostModel.slippage_bps` on a read-only `run_strategy_over_universe`, no `src/`
change — and §7.2's arithmetic at `stop_atr = 2.0`, `ATR/price = 2%`. W1 §7.1 flags
that MAP §0.4 and §3(a) disagree on what "2× and 5×" denotes (16/31 bps under one
reading, 26/66 bps under the other); **all four non-baseline points are reported**,
as W1 pre-registered, so the requirement is met under either convention.

| round trip | quoted spread | `slippage_bps` passed | cost/trade | v0.2.0 OOS expectancy, re-priced from **−0.0335R** |
|---|---|---|---|---|
| **11.0 bps** (frozen baseline — what the gates use) | 5 bps | 3.0 | 0.028R | **−0.0335R** |
| **16.0 bps (2× the modelled spread)** | 10 bps | 5.5 | 0.040R | **−0.0455R** |
| 26.0 bps (MAP §0.4 named case) | 20 bps | 10.5 | 0.065R | **−0.0705R** |
| **31.0 bps (5× the modelled spread)** | 25 bps | 13.0 | 0.078R | **−0.0835R** |
| 66.0 bps (MAP §0.4 named case) | 60 bps | 30.5 | 0.165R | **−0.1705R** |

Re-pricing shifts every trade by the same amount, so this is a deterministic
accounting shift, not a sampled comparison; what is uncertain is the spread
assumption, not the arithmetic. For scale, at the forecast n = 890 the OOS SE is
0.815/√890 = **0.0273R**, so the 11 → 31 bps shift of 0.050R is **1.8 SE**.
**Every re-priced value is negative**, so no spread scenario rescues gate 3.

**An asymmetry that cuts against this proposal specifically, and is unmeasurable
here.** The whole point of the filter is to keep **idiosyncratic** single-name dips
and discard market-wide ones. HYPOTHESIS: an idiosyncratic −2σ day in one name —
no macro event, no market-wide repricing that market makers are already positioned
for — is plausibly the state in which *that name's* quoted spread widens most,
while a broad selloff widens spreads across the board in ways an index-heavy
universe partly absorbs. If so, the retained subset pays **more** spread than
average, not less, and the flat universe-independent 5 bps of
`backtest_runner.py:205-206` is *more* optimistic for the filtered strategy than for
the unfiltered one. There is no quote data in this database, so this cannot be
measured; it is recorded as an unquantified downward bias on every number in §5,
and it is one more reason the 2×/5× table above is not a formality.

---

## 9. Variant budget and stopping rule

**Budget for this angle: 2 variants, hard cap.**

| # | Variant | Precondition | Description |
|---|---|---|---|
| **V-U1** | `breadth_max_frac = 0.125`, hard filter | W1 built and W1-COMPLETE passed | The §2 change exactly as specified, evaluated **read-only** on the 150-symbol snapshot against F1–F4 |
| **V-U2** | breadth as a *modulation* of `z_entry` rather than a hard filter (require a deeper z on high-breadth days) | **only if all four of F1–F4 survive V-U1** | Structurally distinct mechanism (continuous, no cliff), not a re-tune of V-U1's threshold |

**Stopping rule, binding:**

1. **V-U1 is run read-only first.** Gates 1–8 have read-only equivalents
   (`run_strategy_over_universe`, `run_parameter_sensitivity`, `label_regimes`,
   `compute_portfolio_metrics`, `validate_daily` with `persist=False`), and none of
   them touches gate 9. **The entire falsification battery costs zero sealed looks.**
2. **If any of F1–F4 fires → stop. Write §11. No `StrategyVersion` is created, no
   sealed look is spent.** On today's evidence all four fire, so this is the
   expected branch.
3. **If all four survive → V-U1 only** is promoted to a real `VERSION = "0.2.0"` and
   a single `evaluate_promotion` on the expanded snapshot (look 6, §10). V-U2 is
   *not* run in parallel and not run at all unless V-U1 also clears gates 3 and 5.
4. **No third variant.** If V-U1 and V-U2 both fail, the angle is closed. MAP §2.2
   lever 5 is explicit about the asymmetry here: v4 is *"the one most likely to
   produce a spurious pass under repeated trying, because its sealed year already
   passes on all four snapshots"* — a v0.2.0 that fixed gates 3/4/5/7 would inherit
   a friendly gate 9 that provides **no independent check**.

**Disclosed exploration already performed (R5).** One mechanism (H7), evaluated
read-only at **five thresholds** (`k ≤ 1..5`) plus two conditioning variants
(all-member `k`, single-name `k_cs`), on **four snapshots**, plus a
non-monotonicity check and a degeneracy check. **Zero versions created, zero sealed
tests touched, zero gates evaluated.** The `0.125` baseline was selected from that
sweep and §3.6 states the consequence. Counted honestly in the strategy's ledger,
this is **one mechanism explored, one threshold carried forward** — not five
variants — but a judge should treat the baseline point's gate-5 result as
selection-contaminated and read the neighbour fraction instead.

**Cross-angle note.** MAP §4.1 allocates v4 three proposals. This angle's 2 variants
should be added to the other two angles' budgets, and the total stated verbatim in
the final report (R5). If the exits-and-risk angle also adds a gate-5 axis
(`time_stop_bars`, as MAP §2.2 lever 3 requires), the two changes must not be
combined into one v0.2.0 without the combination itself being counted as a variant.

---

## 10. Sealed-look accounting

**The baseline count is k = 5 per strategy** (MAP §0.1, R2), not 2. FACT: no look
counter exists anywhere in `src/signalforge` — the count is reconstructed from
`strategy_sealed_test` (20 rows, exactly 4 per version for versions 2–6) and
disclosure is manual. The §0.1 ledger, reproduced:

| Ver | Strategy | snap 1 `universe_25_baseline_legacy` | snap 2 `universe_25_baseline` | snap 3 `universe_24_ex_meta` | snap 4 `universe_25_meta_continuity_corrected` |
|---|---|---|---|---|---|
| 2 | `trend_continuation.short_swing` | id 1: **+0.3246R / 112** ✅ | id 6: **+0.3246R / 112** ✅ | id 11: **+0.2982R / 109** ✅ | id 16: **+0.3246R / 112** ✅ |
| 3 | `trend_continuation.medium_swing` | id 2: **+0.0109R / 98** ✅ | id 7: **+0.0109R / 98** ✅ | id 12: **−0.0294R / 95** ❌ | id 17: **+0.0109R / 98** ✅ |
| **4** | **`mean_reversion.short_swing`** | **id 3: +0.1230R / 91 ✅** | **id 8: +0.1230R / 91 ✅** | **id 13: +0.1278R / 84 ✅** | **id 18: +0.1230R / 91 ✅** |
| 5 | `relative_strength.medium_swing` | id 4: +0.2935R / 16 ✅ | id 9: +0.2935R / 16 ✅ | id 14: +0.2935R / 16 ✅ | id 19: +0.2935R / 16 ✅ |
| 6 | `volatility_breakout.short_swing` | id 5: −0.0979R / 10 ❌ | id 10: −0.0979R / 10 ❌ | id 15: −0.0979R / 10 ❌ | id 20: −0.0979R / 10 ❌ |

*(Reproduced from MAP §0.1 for disclosure. No number in this table motivates any
design choice in this document — R1. They appear here because R2 requires the
ledger in every report, and in §11 as a **disposition** argument, which R1
permits and which is marked inline there.)*

**What this proposal costs.** FACT (`db/models/research.py:263`):
`StrategySealedTest` is unique per `(strategy_version_id, dataset_snapshot_id)`, so
a new `StrategyVersion` on any snapshot creates a fresh sealed test.

| Action | New sealed test? | Resulting k for version 4 |
|---|---|---|
| Everything in §3 of this document (read-only diagnostics) | **no** | stays **5** |
| The V-U1 read-only falsification battery on the 150-symbol snapshot (§9 step 1) | **no** | stays **5** |
| V-U1 promoted to `VERSION = "0.2.0"` and evaluated on `research_150_massive_10y_2026-09-08` | **yes** | 5 → **6** |
| *(not planned)* the same v0.2.0 also evaluated on snapshot 3 | yes, a second one | would be 6 **and 7** |

**Pre-registered restriction: the v0.2.0 is evaluated on the expanded snapshot
only.** That is one look, not two. This matches
`w1_universe_preregistration.md` §8.1's per-version table, which already
pre-registers version 4 as *"yes, when its universe/power proposal is run"*, 5 → 6.
It also honours W1 §9.4's prohibition: **versions 2 and 5 are not evaluated on the
expanded snapshot** under any circumstances, because a passing scope on a second
snapshot would make `paper_probation.py:118`'s `scopes[0].dataset_snapshot_id`
order-dependent for a live strategy (R7b).

**Which snapshot the report leads with, pre-registered per R1.** The v0.2.0 result
leads with **`research_150_massive_10y_2026-09-08`**, because the mechanism is only
defined against a non-degenerate cross-section (§3.4) and that is the only snapshot
on which it can be honestly measured. Snapshot 3 remains the headline for **v0.1.0**
comparisons — it is the only snapshot on which gate 8 passes (MAP §0.1) — and the
four-draw ledger above is reproduced alongside every reported result. The expanded
snapshot is reported as a **separate experiment**, never as an update to snapshot-3
numbers (MAP §3(a): "a distribution shift, not a more-powered version of the same
experiment"). Two accompanying disclosures are mandatory on any result there
(W1 §9.5): a **date-clustered / block bootstrap** alongside the gate-4 iid CI with
the half-width ratio as the effective-sample-size haircut, and the **per-symbol
IS/OOS boundary dates** (W1 §2.4.1 claims the `list_date ≤ 2016-10-17` filter makes
the 60% cut land on one calendar date for every member; that must be shown, not
asserted).

---

## 11. Null option — the expected outcome

**If any of F1–F4 fires (all four fire today), no code is written and the following
is filed as `mean_reversion.short_swing`'s universe/power result.**

> **`mean_reversion.short_swing` v0.1.0 — H7 (systemic vs idiosyncratic dips) does
> not pass.**
>
> The cross-sectional breadth conditioning that MAP §2.2 identified as v4's
> highest-ceiling lever was tested read-only on the pre-sealed span, on all four
> dataset snapshots, and — if W1 is built — on the 150-symbol expanded snapshot. It
> is not a rescue.
>
> 1. **The mechanism's sign is right and its magnitude is not evidence.**
>    Expectancy on idiosyncratic dips (≤ 3 of 24 members simultaneously at
>    z ≤ −2.0) exceeds expectancy on systemic dips by **+0.0979R to +0.1048R**
>    across the four snapshots — **+1.73 to +1.88 SE** on the iid measure and
>    **+0.99 to +1.07 SE** once clustered on the calendar signal date, the axis
>    `clustered_bootstrap_all.md` establishes for this universe. The program's rule
>    is that a difference under 2 SE is not evidence.
> 2. **The filtered strategy earns nothing.** Pre-sealed **+0.0048R ± 0.0446** on
>    312 trades — an edge of exactly zero, which after the modelled 0.028R/trade
>    cost is a gross edge of ~0.031R entirely consumed by frictions. **OOS
>    −0.0335R ± 0.0684**, so **gate 3 fails on sign** and gate 4's required n is
>    *never* (MAP §0.3: no n fixes a negative point estimate). No threshold in a
>    five-point sweep produces a positive OOS number.
> 3. **The filter creates a new gate failure.** Gate 6's bear bucket falls from 46
>    to **5** against a floor of 10 (unbucketed 32, 10.3%). Gate 7 improves
>    dramatically — Sharpe **−0.749 → +0.036**, maxDD 37.9% → 6.9%, turnover 110.8
>    → 35.1/yr — and still fails against SPY's +0.719 by 0.683. Gate 1 lands at
>    exactly 2 of 4 with the fourth fold clearing by +0.0102R, and **flips to 1 of 4
>    at both adjacent grid values**.
> 4. **The gradient is not monotone.** Across single-name breadth counts 0–9,
>    adjacent buckets swing by up to 0.49R (+0.2655R at 4, −0.2279R at 5), and the
>    most idiosyncratic bucket (k = 1, −0.0350R) is *worse* than k = 2–3
>    (+0.0421R). Any threshold placed in that series is placed on noise.
> 5. **On the 24-symbol universe the statistic is degenerate, and the expanded
>    universe was built to remove that objection.** With 15 of 24 members being
>    index/sector ETFs, breadth is effectively a binary "SPY had a −2σ day"
>    indicator: mean k = **10.90** on the 81 sessions where SPY is at z ≤ −2.0
>    versus **0.36** elsewhere, with corr(ETF-breadth, single-name-breadth) = 0.752.
>    On the 150-symbol snapshot (ETF share 62.5% → 10%) the statistic is
>    well-defined — *and the result was still [outcome]*.
> 6. **Even a pass would not have been operable.** A strategy conditioned on a
>    150-name cross-section cannot be run against the 25-symbol live scan universe
>    (`scan.py:269`), and expanding that universe is an operating decision outside
>    this program's scope.
>
> **Combined with the other two angles**, v4's position is: H6 and H9 refuted
> (`v4_regime_vol_stationarity.md`), H8 surviving as a much weaker claim with three
> of four component claims refuted (`v4_mfe_target.md`), and H7 sub-2-SE and
> gate-failing. **Sensitivity remains 0 of 9 positive** on the shipped parameters
> and full-span Sharpe remains −0.749 against SPY's +0.719.
>
> **Disposition, and this is where R1 permits sealed numbers (marked).** v4's
> sealed year passes on all four snapshots (+0.1230R to +0.1278R, PF 1.45–1.47) on
> a calm, persistently bullish twelve months. Under R1 a sealed result may inform
> *whether to stop trying* — and it argues for stopping, not continuing: the sealed
> year is precisely the regime this dip-buy is built for, the nine-year pre-sealed
> record says that regime is the exception, and because gate 9 is already friendly
> it supplies **no independent check** on any v0.2.0 that fixed the earlier gates.
> That is the strongest available argument that further variants here would
> manufacture a pass rather than find one. **No design choice in this document is
> derived from those sealed numbers.**
>
> **Sealed looks consumed by this angle: 0.** The entire investigation was read-only
> and never evaluated gate 9. Version 4's count stays at **k = 5**.

**What the null option is worth.** It converts MAP §2.2's fourth lever from "highest
ceiling, untested" into a measured, four-snapshot, SE-bearing negative with a named
degeneracy and a named operability blocker — which is what a documented "does not
pass" is supposed to carry. It also delivers, at zero cost to the strategy program,
two reusable findings: the concentration fact (**48.8% of v4's trades come from
2.39% of sessions**) and the measured degeneracy of any cross-sectional statistic
computed on an ETF-majority universe, which applies to every future breadth idea in
this repo, not just this one.

---

## Appendix — reproduction

Every number labelled FACT/DERIVED above that is not a `file:line` citation was
produced by read-only scripts run under
`/Users/louisbrailey/signal-forge/.venv/bin/python` against
`sqlite+pysqlite:///file:/Users/louisbrailey/signal-forge/data/signalforge.sqlite?mode=ro&uri=true`.
The machine-readable companion is
`mean_reversion_short_swing--universe_breadth.json` in this directory. The pipeline
is deterministic (`engine.py` has no RNG and no wall-clock dependence), and the
exact-reproduction table in §3.1 — 984 / 309 / −0.0837R / 618-46-260-60 / Sharpe
−0.749, all matching evaluation id 34 — is the validity check for the rest.

**Known limits of this document.**

- Every forecast for the 150-symbol snapshot is a **forecast**. The snapshot does
  not exist; W1 is pre-registration only, and its backfill (126 paced API calls,
  ~26 min) has not been run and requires operator approval.
- The 6.25× breadth multiplier is MAP §3(a)'s figure and W1 §4.3 treats it as itself
  uncertain. Trade-count forecasts inherit that uncertainty.
- Gate 5 was **not** re-run under the 27-point grid (that is 27 read-only universe
  passes and belongs in the V-U1 battery). Its forecast in §5 is a HYPOTHESIS
  grounded in the fact that every threshold in §3.3 is OOS-negative.
- The clustered SEs here cluster on the calendar signal date. `clustered_bootstrap_all.md`
  establishes that as the right axis for this universe and that symbol clustering is
  the wrong one; that conclusion is inherited, not re-derived.
