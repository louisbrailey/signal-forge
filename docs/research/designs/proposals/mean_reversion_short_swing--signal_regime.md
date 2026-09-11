# Proposal — `mean_reversion.short_swing` v0.1.0 (version 4)
## Angle: signal quality / regime — entry selection conditioned on proxy trend context

**Author:** independent proposer (Phase 2, `STRATEGY_COMPLETION_PLAN.md` step 2).
**Date:** 2026-09-10. **Sections:** all eleven required by `STRATEGY_COMPLETION_MAP.md` §4.2.

> **Bottom line, stated up front so no judge has to read to the end for it.**
> This proposal identifies a **real, large, pre-sealed, four-snapshot-stable regime
> effect** — much stronger than either mechanism the map nominated for this angle
> (H6 and H9, both already refuted) — and then **falsifies itself on its own
> pre-registered gate forecast.** The rule it implies flips gate 3 from fail to pass
> and moves gate 7's Sharpe by **+0.976**, but it **breaks gate 6** (bear bucket
> 46 → 2), leaves gate 4 needing **6,894 OOS trades** against 212, and fails gate 5
> on the headline snapshot. The gate-3 gain and the gate-6 loss are provably **the
> same quantity** (§5.3): no setting of the parameter buys one without paying the
> other. **The recommendation is therefore the null option (§11)** — a documented
> "does not pass" carrying this evidence — and the recommended variant count for
> this angle is **zero implemented variants** (§9).
>
> Everything below is computed read-only on the **pre-sealed span only**. No sealed
> bar was loaded. This proposal consumes **zero sealed looks**; the count remains
> **k = 5** (§10).

---

## 0. Compliance and provenance

**FACT.** Every number in this document was computed in-process against
`data/signalforge.sqlite` through a **read-only** SQLAlchemy engine
(`sqlite+pysqlite:///file:data/signalforge.sqlite?mode=ro&uri=true`), using
`PriceSeries.load`, `research.regime.regime_lookup`, `backtest.engine.run_backtest`,
`research.portfolio_metrics.compute_portfolio_metrics`, `backtest.regime.label_regimes`
and `backtest.montecarlo.bootstrap_ci` — none of which contain `session.add`,
`session.flush` or `session.commit`. **No database write of any kind occurred**, no
scratch copy was needed, no file under `src/` or `tests/` was modified, no package was
installed, and no provider API was called. The live paper-probation worker was not
touched.

**FACT — span.** All computation is over `2016-09-10 .. 2025-09-07` (snapshots 2, 3, 4)
and `2016-09-10 .. 2025-09-06` (snapshot 1). Sealed windows begin **2025-09-08**
(`strategy_sealed_test` ids 8, 13, 18) and **2025-09-07** (id 3);
`pre_sealed_end = sealed_start − 1 day` (`promotion.py:555`). No sealed bar was read,
and **no sealed number appears anywhere in the motivation, the design, or the
forecast.** The only sealed figures cited are in §10 and §11, both explicitly
**disposition** uses permitted by R1 and marked inline.

**FACT — reproduction check (this is what licenses every other number).** The
unmodified v0.1.0 was re-run over all four snapshots and reproduces the recorded
promotion evaluations exactly:

| Quantity | recomputed here | recorded | match |
|---|---|---|---|
| snap 3 pre-sealed trades | **984** | 984 (eval 34) | ✅ |
| snap 3 OOS trades / expectancy | **309 / −0.0837R** | 309 / −0.0837R (eval 34 gates 2, 3) | ✅ |
| snap 3 gate-1 folds | **257/+0.0175, 292/−0.1949, 181/+0.0436, 254/−0.0651** | identical | ✅ |
| snap 3 gate-6 buckets | **bull 618 / bear 46 / range 260 / unbucketed 60** | identical (§0.6) | ✅ |
| snap 3 gate-7 Sharpe | **−0.749** vs SPY **+0.719** | identical (§2.2) | ✅ |
| snap 2 pre-sealed / OOS | **999 / 320 at −0.0782R** | 999 / 320 / −0.0782R (eval 28) | ✅ |

**FACT — "all four snapshots" is really two populations for this strategy.** The
pre-sealed re-runs give **snapshot 3 ≡ snapshot 4** (both 984 trades, −0.0621R, to full
float precision) and **snapshot 1 ≡ snapshot 2** (both 999 trades, −0.0622R). Reasons,
both verified: `META_CONT` carries source `continuity_bridge:1` and has **zero**
`massive` bars (queried: `META_CONT` 2,510 bars all `continuity_bridge:1`), so under
`source="massive"` it loads nothing and is dropped by the `min_bars=60` guard — snapshot 4's
pre-sealed universe *is* snapshot 3's; and snapshot 1 differs from snapshot 2 only by one
calendar day at the far end (2025-09-06 vs 2025-09-07), which changes no trade. Every
"across all four snapshots" claim below is therefore verified on both distinct
populations, which is the strongest form the requirement can take here. This is stated
rather than glossed because R10 asks for four and the honest answer is "four labels, two
samples".

Raw output: `docs/research/designs/proposals/mean_reversion_short_swing--signal_regime.json`.

---

## 1. Mechanism

**The hypothesis (new, stated in the §2 form). H13 — *systemic-drawdown adverse
selection, measured on the proxy's quarterly return rather than on its volatility
label*.**

A −2σ one-day drop in a single name is two different events depending on what the
broad market has been doing for the preceding quarter. When the market's trailing
63-session return is **positive**, a single-name −2σ day is overwhelmingly
idiosyncratic — an earnings miss, a downgrade, a liquidity air-pocket — and
idiosyncratic overreaction is exactly the thing short-horizon mean reversion is built
to harvest: there is a standing bid, the SMA(20) target is still a level the market
believes in, and the reversion has somewhere to revert *to*. When the market's trailing
63-session return is **negative**, the same −2σ day is far more likely to be the local
expression of a systemic repricing that is still in progress. The whole cross-section
is being marked down together, the SMA(20) the strategy is targeting is itself falling
away underneath the trade, and — the mechanically decisive part — the **next session's
open gaps down**, which is where this strategy's money actually goes (§3.4).

**Why this is a different claim from H6, which is refuted.** H6 said the strategy is
blind to *volatility*. The v4 regime-vol diagnostic refuted it: `Vol.HIGH` is a
**relative, self-rebasing** label — `regime.py:78-85` marks HIGH when 20-day realised
vol exceeds **1.15 × the median** of its own trailing 252-day history, so ~37% of
sessions are HIGH in every era by construction and March 2020 receives the same label as
a choppy week in 2017. That diagnostic's own closing caveat is the opening for this
proposal: *"A design that wants 'crisis' rather than 'above-median chop' needs a
different statistic."* H13 supplies one. `market_ret_63d` is **directional and on an
absolute scale**: it does not rebase, it distinguishes "the market has fallen" from "the
market is jumpy", and it is the statistic a dip-buyer actually needs.

**Why this is a different claim from H9, also refuted.** H9 said the *trigger* fires
pro-cyclically with volatility. It does not — `zscore_last_return`
(`features/daily.py:66-73`) divides by the same symbol's own trailing 20-return sd, so
it is self-normalising by construction. H13 makes no claim about entry *rate*; it is
purely a claim about entry *quality* conditional on market context.

**Why it is H7's mechanism without H7's cost.** §2.2's H7 ("systemic vs idiosyncratic
dips") is rated highest-ceiling and highest-cost because a breadth term needs new
`StrategyContext` plumbing (`base.py:15-19`), a shared-surface change touching every
strategy, plus its own leakage audit — and §2.2 notes a breadth figure computed on a
universe that is 15 ETFs holding the other 9 is near-degenerate anyway. H13 reaches the
same mechanism through a field that is **already computed, already point-in-time,
already on the object the strategy is handed, and already unused**:
`RegimeState.market_ret_63d` (`regime.py:38, 88, 94-95`). The strategy reads
`ctx.regime.trend` and nothing else (`mean_reversion.py:88`). Zero new plumbing, zero
new features, zero shared-surface change (§7).

**Why the existing `Trend.BEAR` guard does not already do this.** `mean_reversion.py:88`
already refuses `Trend.BEAR`. But `Trend.BEAR` requires SMA-50 **below** SMA-200 **and**
a falling 10-bar SMA-200 slope (`regime.py:71-77`) — a label that needs months of
damage before it turns. **FACT:** across the 984 snapshot-3 pre-sealed trades the
strategy takes **zero** BEAR-labelled entries, i.e. the guard binds only where it is
already too late to matter. `market_ret_63d < 0` is the *fast* version of the same idea:
it fires on the quarter's actual drawdown, not on a crossover confirming one. This is
precisely §2.2's stated diagnosis — *"entries fire on … days that a slow SMA50/SMA200
trend label still calls non-BEAR"* — with a measurement attached.

---

## 2. Exact change

New behaviour ships as **`VERSION = "0.2.0"`** (R3, R7). v0.1.0's row, spec, sealed tests
and (non-existent, it is EXPERIMENTAL) approved scope are untouched.

### 2.1 `src/signalforge/research/strategies/mean_reversion.py`

| Symbol | Before | After |
|---|---|---|
| `VERSION` (line 17) | `"0.1.0"` | `"0.2.0"` |
| `MeanReversionParams` (lines 20-27) | 6 fields: `z_lookback=20, z_entry=-2.0, sma_window=20, atr_window=14, stop_atr=2.0, time_stop_bars=6` | **+1 field**: `market_ret_63d_min: float = 0.0`. All six existing defaults **unchanged**. |
| `MeanReversion.evaluate` entry test (line 88) | `if z <= p.z_entry and close < mean and ctx.regime.trend is not Trend.BEAR:` | `if z <= p.z_entry and close < mean and ctx.regime.trend is not Trend.BEAR and _mkt_ok(ctx.regime, p.market_ret_63d_min):` |
| new module-level helper | — | `def _mkt_ok(r: RegimeState, floor: float) -> bool: return r.market_ret_63d is not None and r.market_ret_63d >= floor` |
| `spec().entry_conditions` (line 55) | `"z_ret <= {z_entry} and close < sma and regime not BEAR"` | `… and regime not BEAR and market_ret_63d >= {market_ret_63d_min}` |
| `spec().feature_definitions` (50-54) | 3 entries | +`"market_ret_63d = proxy close[t]/close[t-63] - 1 (RegimeState, point-in-time)"` |
| `spec().known_failure_modes` (68-72) | 3 entries | +`"a market-wide drawdown that has not yet turned the proxy's 63-session return negative"` |

**Nothing else changes.** `stop_atr` stays 2.0, `target_price` stays the frozen SMA(20),
`time_stop_bars` stays 6, direction stays long-only. The v4 MFE/target diagnostic showed
the exit levers are dead (SMA-tracking target: Δ = −0.003R ± 0.004, wrong sign; the 6-bar
leash is a net **positive** +0.0410R), so this proposal deliberately does not touch them —
that is a different angle's territory and combining them would confound both.

**Semantics of the `None` case.** `market_ret_63d` is `None` for the first 63 proxy
sessions (`regime.py:88, 94-95` via `rolling_return`, `features/daily.py:54-57`, which
returns NaN when `t - window < 0`). `_mkt_ok` returns `False` there, i.e. **no trade
during proxy warmup**. FACT: this affects **2 of 984** trades on snapshot 3. Stated
explicitly because a silent `None >= 0.0` would raise `TypeError`, and because the
alternative convention (treat unknown as permissive) would be a leakage-adjacent
judgement call made for convenience.

### 2.2 `src/signalforge/research/strategies/__init__.py:43-51`

`default_strategies()` gains a seventh entry registering the v0.2.0 instance alongside
the untouched `MeanReversion()` v0.1.0. **R7 check required before integration:** v2 and
v5 are the live PAPER_APPROVED versions and neither is `mean_reversion`, so
`approval_scope.current_spec_json_hash()` for them cannot move; and R7b's `scopes[0]`
hazard is not engaged because no new *passing* evaluation on a different snapshot is
created by a strategy that (per §5) does not pass.

### 2.3 `src/signalforge/research/promotion.py:189-197`

The `mean_reversion` grid gains the new parameter as a **third axis** (§6):

```
before: {"z_entry": [-2.5, -2.0, -1.5], "stop_atr": [1.5, 2.0, 2.5]}                        #  9 points
after:  {"z_entry": [-2.5, -2.0, -1.5], "stop_atr": [1.5, 2.0, 2.5],
         "market_ret_63d_min": [-0.02, 0.0, 0.02]}                                          # 27 points
```

27 ≤ `MAX_GRID_POINTS = 120` (`sensitivity.py:29`), so this raises no `ValueError`.
Adding an axis is permitted under R4 — it makes gate 5 strictly more searching and can
never make it easier to pass. §6 shows, with numbers, that this is not a formality: the
same v0.2.0 **passes** gate 5 under the legacy 2-axis grid and **fails** it under the
honest 3-axis grid.

---

## 3. Pre-sealed evidence, with standard errors

Per §0.3 of the map, v4's per-trade sd is ≈0.807 (recovered from the stored CI) and
≈0.820 measured directly. All SEs below are measured on the actual samples, not assumed.
**`se_cl` clusters on the calendar signal date** — the map's §3(a) and the v4 vol
diagnostic both establish that iid SEs are ~1.9× too narrow for this strategy (984
snapshot-3 trades fall on only **352** distinct dates). Under the program's 2-SE rule I
treat `se_cl` as the one to act on and report both.

### 3.1 The partition (snapshot 3, all 984 pre-sealed trades)

| set | n | expectancy | sd | se_iid | **se_cl** | win rate |
|---|---|---|---|---|---|---|
| **KEEP** `market_ret_63d ≥ 0` | 711 | **+0.0201R** | 0.7936 | 0.0298 | 0.0591 | 0.575 |
| **DROP** `market_ret_63d < 0` | 271 | **−0.2837R** | 1.0214 | 0.0620 | 0.1395 | 0.406 |
| **difference** | | **+0.3038R** | | 0.0688 → **+4.41 SE** | 0.1515 → **+2.01 SE** | |

Snapshot 2 (the other distinct population): KEEP 722 at +0.0216R, DROP 275 at −0.2881R,
difference **+0.3097R**, **+4.56 SE iid / +2.07 SE clustered**.

**This clears 2 SE on the clustered measure.** For calibration against the two mechanisms
this angle was nominated for, both of which failed the same test:

| mechanism | pre-sealed difference | SE iid | **SE clustered** | ex-F2 | verdict |
|---|---|---|---|---|---|
| H6 `Vol.LOW` vs `HIGH` | +0.1491R | 2.53 | **1.14** | +0.0106R (**0.16 SE**) | refuted |
| H9 vol-normalised trigger | — | — | — | — | refuted (trigger is self-normalising) |
| **H13 `market_ret_63d ≥ 0`** | **+0.3038R** | **4.41** | **2.01** | **+0.2636R (3.52 / 1.73 SE)** | **survives** |

### 3.2 The effect is not one fold — the decisive contrast with H6

H6's fatal defect was that its entire effect lived in fold F2 (Dec-2018 + COVID) and
**reversed sign in F1**. H13 does not:

| fold | span | KEEP n / exp | DROP n / exp | difference | t_iid |
|---|---|---|---|---|---|
| F1 | 2016-09 → 2018-12 | 173 / **+0.0696** | 82 / −0.1101 | **+0.1797** | +1.63 |
| F2 | 2018-12 → 2021-03 | 208 / −0.0842 | 84 / **−0.4691** | **+0.3849** | +2.65 |
| F3 | 2021-03 → 2023-06 | 140 / **+0.0890** | 41 / −0.1113 | **+0.2003** | +1.28 |
| F4 | 2023-06 → 2025-09 | 190 / **+0.0386** | 64 / −0.3731 | **+0.4116** | +2.98 |

**All four folds agree in sign**; two exceed 2.5 SE; none reverses. Removing F2 entirely
leaves **+0.2636R (3.52 SE iid, 1.73 SE clustered)** — where H6 ex-F2 collapsed to
+0.0106R / 0.16 SE. Under R10 as amended ("not to rest on one fold"), H13 passes the test
H6 failed.

### 3.3 The mechanism check — the effect shows up where the mechanism says it should

If H13's story is right, the DROP set should be enriched in **gap-down entries**, which
the v4 MFE diagnostic (Finding 7) identified as carrying this strategy's entire loss:
6.6% of trades whose next open gaps down a median −1.40 ATR collapse the risk unit below
1×ATR and average −0.671R.

**FACT (snapshot 3).**

| set | n | collapsed-risk trades (risk < 1×ATR) | share | their mean pnl |
|---|---|---|---|---|
| KEEP `r63 ≥ 0` | 711 | 31 | **4.36%** | **+0.0839R** |
| DROP `r63 < 0` | 271 | 34 | **12.55%** | **−1.3592R** |

The gap tail is **2.9× denser** in the DROP set, and inside the DROP set it is
catastrophic. The exit mix says the same thing:

| set | target | stop | time_stop |
|---|---|---|---|
| KEEP | **385 (54.1%)** at +0.434R | 172 (24.2%) at −1.010R | 153 (21.5%) at +0.140R |
| DROP | 57 (21.0%) at +0.691R | **115 (42.4%)** at −1.176R | 99 (36.5%) at +0.191R |

Mean reversion **reverts** when the market's quarter is not down (54% of trades reach the
frozen SMA target) and **does not** when it is (21%). This is the mechanism showing its
face in the data, not a curve fit: no parameter was tuned to produce these tables.

### 3.4 H13 subsumes and explains H6 — the cross-tabulation

This is the single most informative table in the document.

| | `r63 ≥ 0` | `r63 < 0` | within-vol difference |
|---|---|---|---|
| **`Vol.HIGH`** | n=209, **+0.0624R** ± 0.0654 | n=204, **−0.3647R** ± 0.0729 | **+0.4271R, 4.36 SE iid / 1.84 SE cl** |
| **`Vol.LOW`** | n=502, +0.0026R ± 0.0322 | n=67, −0.0369R ± 0.1128 | +0.0395R, 0.34 SE |

Read it and H6 dissolves. The "HIGH-vol penalty" H6 found is **entirely** the `r63 < 0`
corner of HIGH vol. Within HIGH vol, trades taken when the market's quarter is up earn
**+0.0624R** — *better* than LOW-vol trades. So H6's proposed filter throws away 209
profitable HIGH-vol trades while keeping 67 LOW-vol trades that lose money. The
volatility label was a **noisy proxy** for the quarterly-drawdown condition, and a
badly aligned one.

Confirming this from the other side: applying H6's filter **on top of** H13's destroys
the result. **FACT:** `Vol.LOW ∧ r63 ≥ 0`, OOS, snapshot 3: **−0.0740R** (n=163) — worse
than H13 alone (+0.0373R) and worse than doing nothing to the vol axis. Stated so that no
later synthesis stacks the two filters on the assumption that both help.

### 3.5 The rejected sibling, disclosed under R5

`RegimeState` exposes exactly **two** unused trailing-return fields. Both were examined,
at the same parameter-free zero threshold, before either was written up:

| candidate | all-pre-sealed difference | se_cl | quintile monotonicity | OOS(KEEP) | verdict |
|---|---|---|---|---|---|
| `market_ret_20d ≥ 0` | +0.1265R | 0.1153 → **1.10 SE** | **non-monotone** (Q1 −0.209, Q2 −0.065, Q3 −0.047, **Q4 −0.132**, Q5 +0.139) | +0.0736R (n=138) | **rejected** — under 2 SE clustered, and the "gradient" is one quintile |
| **`market_ret_63d ≥ 0`** | **+0.3038R** | 0.1515 → **2.01 SE** | monotone in sign across folds | +0.0373R (n=212) | carried forward |

`market_ret_20d` is rejected **despite a higher OOS point estimate** (+0.0736 vs +0.0373),
because its all-span effect is under 2 SE clustered and its quintile structure shows the
apparent gradient is a single top-quintile artefact rather than a monotone relationship.
Selecting the 20-day field on its OOS number would have been exactly the error R5 exists
to prevent. This counts as **one examined-and-rejected variant** (§9).

### 3.6 Threshold transparency — and the honest red flag

The threshold `0.0` was fixed **a priori** as the parameter-free split (is the market's
quarter up or down?), before any sweep was run. The sweep is reported anyway, because
concealing it would be the offence:

| `x` | all n | all exp | OOS n | OOS exp | OOS se |
|---|---|---|---|---|---|
| −0.08 | 927 | −0.0282 | 281 | −0.0256 | 0.0464 |
| −0.04 | 854 | +0.0039 | 251 | −0.0385 | 0.0488 |
| −0.02 | 799 | +0.0032 | 225 | −0.0137 | 0.0499 |
| **0.00** | **711** | **+0.0201** | **212** | **+0.0373** | 0.0503 |
| +0.02 | 586 | −0.0118 | 179 | +0.0060 | 0.0552 |
| +0.04 | 389 | −0.0422 | 127 | +0.0335 | 0.0665 |

**Red flag, disclosed: `x = 0.0` is the maximum of the all-pre-sealed column.** A
pre-registered choice landing on a local optimum is suspicious even when the
pre-registration is genuine, and a judge should discount accordingly. Two things
partially mitigate it and neither is decisive: `0.0` is *not* the OOS maximum (+0.04 and
+0.02 sit nearby, and the earlier `market_ret_20d` sweep peaked at +0.02), and the
neighbouring values ±0.02 are the gate-5 axis precisely so that this fragility is
measured rather than asserted (§6). It remains the weakest point in the evidence and is
not argued away.

---

## 4. Falsification — stated before the run, checked on both distinct populations

Pre-registered kill conditions, written before the counterfactual was executed:

| # | Falsifier | Result | Verdict |
|---|---|---|---|
| **F-1** | The KEEP/DROP difference is under **2 SE on the clustered measure** on either distinct pre-sealed population. | snap 3 **+2.01 SE**, snap 2 **+2.07 SE** | **survived** (narrowly) |
| **F-2** | The difference **reverses sign in any walk-forward fold**, as H6's did in F1. | +0.1797 / +0.3849 / +0.2003 / +0.4116 — all positive | **survived** |
| **F-3** | The difference **vanishes with F2 removed** (< 1 SE clustered), as H6's did. | ex-F2 **+0.2636R, 1.73 SE cl** | **survived** (narrowly) |
| **F-4** | The filtered strategy's **OOS expectancy is not positive** (gate 3 unfixed). | **+0.0373R** (snap 3), **+0.0462R** (snap 2) | **survived** |
| **F-5** | The effect is **just `Vol.HIGH` relabelled** — i.e. it disappears when conditioning on vol. | Within HIGH vol the difference is **+0.4271R (4.36 SE iid)**; H13 *explains* H6 rather than duplicating it | **survived** |
| **F-6** | **The filtered strategy does not clear more gates than v0.1.0.** | v0.1.0 fails **3, 4, 5, 7**; v0.2.0 fails **4, 5, 6, 7** — four either way, one traded for another | **❌ FAILED** |
| **F-7** | The change **breaks a gate v0.1.0 passes.** | gate 6 bear bucket **46 → 2** against a floor of 10 | **❌ FAILED** |

**Five of seven survived; the two that matter for shipping did not.** F-6 and F-7 were
written as kill conditions precisely so that a mechanism that is real but useless could
not be talked into an implementation. They fired. Under R10 that ends the matter: this
proposal is falsified as a **change**, and survives only as a **finding**.

---

## 5. Gate-by-gate forecast

These are not forecasts in the estimative sense — the full re-simulation was run, so they
are **measured outcomes** of the exact proposed rule. Trade sets are tagged per §0.2
(OOS-only for gates 2/3/4; **all pre-sealed** for gates 1, 6, 7 — including gate 7,
whose docstring at `config/research.py:111-113` contradicts its code at `promotion.py:775`).

**FACT — the counterfactual needs no paired/re-simulation caveat.** The engine is
flat-only (`engine.py:149`, `t = exit_idx + 1`), so blocking an entry can in principle
free capacity for a later one, and a partition of baseline trades need not equal a
re-simulation. Here they are **literally identical**: the re-simulated filtered trade set
and the `r63 ≥ 0` partition of the baseline set match element-for-element on
`(symbol, entry_date)` — 711/711 on snapshot 3 and 722/722 on snapshot 2, zero
differences either way. Mechanically this is because the filter is a **market-wide**
condition: when it blocks, it blocks every symbol for a contiguous stretch, so there is no
freed capacity to redeploy.

### 5.1 Snapshot 3 (headline), v0.1.0 → v0.2.0

| Gate | Trade set | v0.1.0 | **v0.2.0** | Verdict |
|---|---|---|---|---|
| 1 `rolling_walkforward` (≥2 of 4, n≥15 & exp>0) | all pre-sealed | **2/4** (bare) 257/+0.0175, 292/−0.1949, 181/+0.0436, 254/−0.0651 | **3/4** 173/**+0.0696**, 208/−0.0842, 140/**+0.0890**, 190/**+0.0386** | **PASS, margin improved** |
| 2 `min_oos_trades` (≥30) | OOS | 309 | **212** (−31.4%) | **PASS**, comfortable |
| 3 `net_expectancy` (>0) | OOS | **−0.0837R** ± 0.0467 | **+0.0373R** ± 0.0503 (se_cl 0.0619) | **fail → PASS** (but only **0.74 SE** iid / **0.60 SE** clustered from zero) |
| 4 `bootstrap_ci` (low > +0.02R) | OOS | [−0.1739, +0.0061] | **[−0.0568, +0.1356]**, low **−0.0568** | **FAIL** |
| 5 `parameter_sensitivity` (≥60% / ≥75%) | OOS per cell | 0/9 = **0%**, 0% nbr | 27/27 evaluable, **15/27 = 55.6%** positive, neighbours **4/6 = 66.7%** | **FAIL** (needs 60% / 75%) |
| 6 `regime_coverage` (≥10 each) | all pre-sealed | bull 618 / **bear 46** / range 260; **unbucketed 60** | bull 559 / **bear 2** / range 92; **unbucketed 58** | **PASS → FAIL** |
| 7 `benchmark_comparison` (Sharpe > SPY) | all pre-sealed | **−0.749** vs +0.719 | **+0.227** vs +0.719 | **FAIL** (gap 1.468 → **0.492**) |
| 8 `data_quality_and_leakage` | — | pass (snap 3 only) | **unchanged** — no data or source change | PASS |
| — portfolio (all pre-sealed) | | CAGR −3.48%, maxDD 37.93%, PF 0.831, turnover 110.8/yr | CAGR **+0.75%**, maxDD **19.83%**, PF **1.068**, turnover **80.0/yr** | materially better, still short |

**Gate 4 as a required n, per §4.2 item 5.** `n > (1.96·sd/(exp − 0.02))²` at the measured
filtered OOS sd = **0.7324** and exp = **+0.0373**:

| snapshot | OOS exp | sd | **required n** | has | multiple |
|---|---|---|---|---|---|
| 3 | +0.0373R | 0.7324 | **6,894** | 212 | **32.5×** |
| 2 | +0.0462R | 0.7220 | **2,926** | 221 | **13.2×** |

The snapshot-3-vs-2 spread (6,894 vs 2,926) is itself the warning: required-n is
hypersensitive to a point estimate this close to the +0.02 bar, and the two populations
differ only by META. **W1 does not rescue this.** A 150-symbol universe is ≈6.25×
breadth → ≈1,325 OOS trades against a requirement of 6,894. Gate 4 fails powered.

**Gate 6's unbucketed count, mandatory per §4.2 item 5.** v0.1.0: **60** (6.1%).
v0.2.0: **58** (5.9%). The count barely moves — it is dominated by
`label_regimes`'s 200-session warmup (`backtest/regime.py:20, 36-37`) — so the bear
collapse from 46 to 2 is **real attrition, not reclassification into the unbucketed
hole**. Note also that gate 6 uses `backtest/regime.py:label_regimes` while the filter
reads `research/regime.py` — two different labellers (§4.3), which is exactly why this
was measured rather than assumed.

**Zero-margin cases, mandatory per §4.2 item 5.** The two the map names (v6's 0.750
neighbour fraction; v5's bear bucket of 11) are not touched by this proposal — it is a
`mean_reversion` change and neither v5 nor v6 is affected. **A new zero-margin case is
created and is reported in §6:** under the *legacy* 2-axis grid this v0.2.0's neighbour
fraction is **exactly 0.750**, the same knife-edge `sensitivity.py:194` (`nb_frac < min`)
that v6 sits on.

### 5.2 All four snapshots

| | snap 3 | snap 4 | snap 2 | snap 1 |
|---|---|---|---|---|
| pre-sealed n (filtered) | 711 | 711 | 722 | 722 |
| all-pre-sealed exp | +0.0201R | +0.0201R | +0.0216R | +0.0216R |
| OOS n / exp | 212 / **+0.0373R** | 212 / +0.0373R | 221 / **+0.0462R** | 221 / +0.0462R |
| gate 3 | PASS | PASS | PASS | PASS |
| gate 4 CI low | −0.0568 | −0.0568 | −0.0501 | −0.0501 |
| gate 5 pos / nbr | **55.6% / 66.7% FAIL** | (= snap 3) | **66.7% / 83.3% PASS** | (= snap 2) |
| gate 6 bear | **2 FAIL** | 2 FAIL | 2 FAIL | 2 FAIL |
| gate 7 Sharpe | +0.227 | +0.227 | +0.247 | +0.247 |

**Gate 5 is snapshot-fragile in the same way v6's is** — it passes on the 25-symbol
population and fails on the 24-symbol one, flipped by a single symbol. Since snapshot 3
is the only snapshot on which gate 8 passes (§0.1), the binding answer is **FAIL**.

### 5.3 The structural finding: gate 3 and gate 6 are the same quantity

This is the result that settles the angle, and it generalises beyond this one parameter.
The threshold was swept across its full plausible range and **both** gates evaluated at
every point (snapshot 3):

| `x` | pre-sealed n | OOS n | OOS exp | CI low | required n | gate 1 | bull | **bear** | range | unbuck. | Sharpe | **gate 3** | **gate 6** |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| none (v0.1.0) | 984 | 309 | −0.0837 | −0.1739 | — | 2/4 | 618 | **46** | 260 | 60 | −0.749 | fail | **PASS** |
| −0.10 | 951 | 305 | −0.0854 | −0.1753 | — | 2/4 | 606 | **29** | 258 | 58 | −0.561 | fail | **PASS** |
| −0.08 | 927 | 281 | −0.0256 | −0.1174 | — | 3/4 | 603 | **12** | 254 | 58 | −0.334 | fail | **PASS** |
| −0.06 | 887 | 265 | −0.0561 | −0.1505 | — | 2/4 | 601 | **13** | 215 | 58 | −0.400 | fail | **PASS** |
| −0.04 | 854 | 251 | −0.0385 | −0.1304 | — | 3/4 | 600 | **11** | 185 | 58 | +0.048 | fail | **PASS** |
| −0.03 | 824 | 243 | −0.0311 | −0.1215 | — | 3/4 | 586 | **11** | 169 | 58 | −0.049 | fail | **PASS** |
| −0.02 | 799 | 225 | −0.0137 | −0.1081 | — | 3/4 | 584 | **4** | 153 | 58 | +0.017 | fail | FAIL |
| −0.01 | 761 | 218 | +0.0093 | −0.0935 | — | 3/4 | 575 | **4** | 124 | 58 | +0.174 | **PASS** | FAIL |
| **0.00** | **711** | **212** | **+0.0373** | −0.0568 | 6,894 | 3/4 | 559 | **2** | 92 | 58 | +0.227 | **PASS** | FAIL |
| +0.01 | 669 | 206 | +0.0406 | −0.0591 | 4,710 | 3/4 | 535 | **2** | 86 | 46 | −0.170 | **PASS** | FAIL |
| +0.02 | 586 | 179 | +0.0060 | −0.1018 | — | 3/4 | 466 | **2** | 72 | 46 | −0.088 | **PASS** | FAIL |
| +0.04 | 389 | 127 | +0.0335 | −0.0973 | 11,834 | 2/4 | 344 | **1** | 29 | 15 | −0.371 | **PASS** | FAIL |

Snapshot 2 reproduces the same frontier exactly: gate 3 passes only for `x ≥ −0.01`,
gate 6 passes only for `x ≤ −0.03`.

**The two admissible regions are disjoint, on both populations.** Gate 3 turns positive
at `x ≥ −0.01`; gate 6's bear bucket drops below 10 at `x ≥ −0.02`. There is no value of
the parameter — not the pre-registered one, not any other — that satisfies both. And
across the *entire* sweep gate 4's CI low never approaches +0.02 (best: −0.0568) and gate
7's Sharpe never approaches SPY's +0.719 (best: +0.227).

**Why this is not a tuning failure but a structural one.** The filter's whole content is
"do not buy dips while the market's quarter is down". Gate 6 requires ≥10 trades in the
regime `label_regimes` calls **bear** — a falling 200-session SMA — which is very nearly
the same condition. The gate demands evidence from exactly the regime the mechanism
exists to avoid. **Any** v4 proposal in this angle that conditions on market direction
will hit this same wall; the finding transfers to the whole angle, not just to this
parameter.

**Is gate 6 recoverable under W1?** Partly, and this is a **HYPOTHESIS**, not a claim.
**FACT:** of the 267 bear-labelled pre-sealed proxy sessions, **47 (17.6%)** have
`market_ret_63d ≥ 0` — bear-market rallies — so unlike v6's case (whose inherited gate
shuts on 93% of bear sessions) there is no hard calendar ceiling of zero here. With 2
bear trades on 24 symbols, a 6.25× breadth multiplier projects to **≈12**, which would
clear the floor of 10 — **by two trades, on a projection, with no margin.** That is a
reason to keep the finding on file for the W1 discussion, not a reason to ship. It also
would not help gates 4, 5 or 7.

---

## 6. Sensitivity-grid plan, and the no-op check

**Pre-registered axes** (fixed before the grid was run):

```python
{"z_entry": [-2.5, -2.0, -1.5],          # unchanged, existing axis
 "stop_atr": [1.5, 2.0, 2.5],            # unchanged, existing axis
 "market_ret_63d_min": [-0.02, 0.0, 0.02]}   # NEW — the parameter this variant is about
```

A genuine ±1-step neighbourhood around the shipped `0.0`, symmetric, chosen before
results were seen, and adopted as a **third** axis rather than by displacing an existing
one (27 points, under the 120 cap) so that no existing coverage is lost. Permitted under
R4: strictly more searching, never easier.

**The no-op check demanded by §4.2 item 6 — passed, with numbers.** A retained-but-unused
field would make all grid points identical and gate 5 would pass at 100% having tested
nothing (§2.1). Holding `z_entry = −2.0, stop_atr = 2.0` and moving only the new axis:

| `market_ret_63d_min` | OOS n | OOS expectancy |
|---|---|---|
| −0.02 | 225 | −0.0137 |
| 0.00 | 212 | +0.0373 |
| +0.02 | 179 | +0.0060 |

Trade count moves by 46 and expectancy by 0.051R across one axis step. **The axis
measurably changes both quantities; it is not a no-op.**

### 6.1 Why adding the axis is load-bearing — a quantified demonstration of §0.5's warning

The map warns (§0.5) that *"the decisive new parameter of a v0.2.0 is exactly the one gate
5 will not test unless it is added as an axis"* and calls that "the cleanest available
route to a hidden-fragility pass". Here is that claim measured, on this exact proposal,
snapshot 3:

| grid | points | positive | neighbours positive | gate 5 |
|---|---|---|---|---|
| **legacy 2-axis** (`z_entry` × `stop_atr`, new param pinned at 0.0) | 9 | **8/9 = 88.9%** | **3/4 = 75.0%** | **PASS** — and at *exactly* the 0.750 knife-edge (`sensitivity.py:194` tests `nb_frac < min`) |
| **honest 3-axis** (as proposed) | 27 | **15/27 = 55.6%** | **4/6 = 66.7%** | **FAIL** |

Shipping this v0.2.0 **without** amending the grid would have converted v4's most
emphatic failure — 0/9, 0% positive — into an 89% pass, on a strategy whose real
robustness had got worse, not better. The two-line grid edit in `promotion.py:189-197` is
the difference between a true fail and a false pass. Recommended regardless of this
proposal's disposition.

**Cell-floor check (gate 5's ≥15, which per §4.3 is also gate 1's per-fold floor).** All
**27/27** points clear 15 OOS trades; the smallest cell is **n = 76**. No cell is at risk,
so no gate-5 or gate-1 verdict here turns on the floor.

---

## 7. Leakage argument

**No new feature is introduced.** The change reads one already-computed field.

1. **Point-in-time by construction.** `market_ret_63d` is
   `rolling_return(proxy, t, 63)` = `close[t] / close[t-63] − 1`
   (`features/daily.py:54-57`) — indices `t` and `t-63`, both ≤ `t`, returning NaN when
   `t - 63 < 0`. `regime_from_proxy` is documented and implemented as *"Point-in-time:
   uses only `proxy` bars at indices <= `t`"* (`regime.py:65`, computed at `:88`, stored
   at `:94-95`).
2. **The lookup key is the signal bar, not the entry bar.** `signal_fn_for` resolves the
   regime by `series.dates[t]` (`base.py:39-41`) — the bar the decision is made on. The
   engine fills at `entry_idx = t + 1` (`engine.py:99`), so the filter is evaluated
   strictly **before** the bar it acts on. It could be evaluated in live trading at the
   same moment the existing `ctx.regime.trend` test is.
3. **`regime_lookup` builds one state per proxy session from that session's own history**
   (`regime.py:99-101`), so no cross-sectional or forward information enters the map.
4. **Covered by the existing self-check.** `assert_no_lookahead`
   (`backtest/leakage.py:23-41`) calls a `(series, t)` feature on `series.head(t)` and on
   the full series and requires equality. `rolling_return` satisfies this trivially
   (fixed offsets relative to `t`). **Required addition before integration:** add
   `lambda s, t: rolling_return(s, t, 63)` to the leakage self-check list so the guarantee
   is enforced rather than argued.
5. **No `StrategyContext` change, no shared surface touched.** The field is already on
   `RegimeState` and already reaches every strategy through `StrategyContext.regime`
   (`base.py:15-19`). This is the concrete legitimacy advantage over §2.2's H7 breadth
   lever, which needs new plumbing and a fresh audit.
6. **One judgement call, declared:** `market_ret_63d is None` (proxy warmup) is treated as
   **fail-closed** (no trade). Affects 2 of 984 snapshot-3 trades. The permissive
   alternative would let trades through on unknown context, which is the wrong default for
   a safety filter.
7. **Walk-forward assumption preserved.** `walkforward.py` does not re-fit per fold, which
   is sound only while strategies fit nothing. This change introduces **no fitted
   quantity** — the threshold is a constant, not an estimate — so the assumption holds
   (§4.3).

---

## 8. Cost-model statement, quantitative

**The cost model is unchanged and untouched** (R4): `CostModel` defaults
(`costs.py:11-16`, `commission_per_share = 0.0`, `slippage_bps = 3.0`,
`half_spread_fill_penalty = True`), `spread_bps = 5.0` default (`engine.py:90`), never
overridden by `backtest_runner.py:205-206`; `slip = (3.0 + 5.0/2)/10,000 = 5.5 bps` per
side (`engine.py:94`), **11.0 bps round trip** (`engine.py:143`). Every number in this
document was produced under exactly that model.

**Per-trade cost in R.** `stop_atr` is **unchanged at 2.0**, so the risk unit and hence
the per-trade cost are unchanged:
`11.0/10,000 ÷ (2.0 × 0.02) = ` **0.028R per trade** at a 2% ATR/price — v4's baseline
figure from §0.4, still the lowest in the program.

**Turnover delta (all pre-sealed, snapshot 3).**

| | v0.1.0 | v0.2.0 | delta |
|---|---|---|---|
| pre-sealed trades | 984 | 711 | **−27.7%** |
| turnover | 110.8 /yr | 80.0 /yr | **−27.8%** |
| cost paid per trade | 0.028R | 0.028R | **0** |
| total cost over the span | ≈27.6R (984 × 0.028) | ≈19.9R (711 × 0.028) | **−7.6R** |

The change is **cost-reducing**: same cost per trade, 27.7% fewer trades. Cost is not a
risk to this proposal — which makes the failure to clear gate 4 entirely an edge-size
problem, not a friction problem.

**Spread sensitivity, and it is fatal on its own.** The flat 5 bps is universe-independent
and optimistic for anything outside the current mega-cap/ETF set. Required for any
expanded-snapshot run (§4.2 item 8), and instructive even here:

| assumed quoted spread | round trip | cost/trade | **filtered OOS expectancy net of the increment** |
|---|---|---|---|
| 5 bps (today, already in the numbers) | 11.0 bps | 0.028R | **+0.0373R** |
| 20 bps (2×) | 26 bps | 0.065R | **+0.0003R** |
| 30 bps | 36 bps | 0.090R | −0.0247R |
| 60 bps (5×) | 66 bps | 0.165R | **−0.0997R** |

**The entire filtered edge is smaller than one doubling of the assumed spread.** At 2×
the modelled spread the strategy's OOS expectancy is +0.0003R — indistinguishable from
zero and below gate 3's bar in any practical sense. Since W1's 150-name universe is
precisely where wider spreads live (§0.4), the combination "expand the universe to power
this up" is self-defeating for **this** strategy: breadth adds n while spread removes the
point estimate, and gate 4 needs the point estimate.

---

## 9. Variant budget and stopping rule

**Budget declared for this angle: 2 candidate mechanisms examined at the diagnostic
stage, maximum 2. Both examined. Zero recommended for implementation. Angle closed.**

Ledger, per R5 — every variant, including abandoned ones:

| # | Variant | Status | Pre-sealed result |
|---|---|---|---|
| 1 | `market_ret_20d ≥ 0` | **examined, rejected** (§3.5) | difference +0.1265R, **1.10 SE clustered** (under 2 SE); non-monotone quintiles |
| 2 | `market_ret_63d ≥ 0` | **examined, falsified as a change** (§4 F-6/F-7) | difference +0.3038R, 2.01 SE cl; filtered OOS +0.0373R ± 0.0503; **gates 4, 5, 6, 7 fail** |

**Not counted as variants, and why.** (a) The threshold sweeps in §3.6 and §5.3 are
*sensitivity reporting on a single pre-registered axis*, not a search for a shipping
value — no swept value is proposed, and the sweep's purpose was to test whether the
gate-3/gate-6 conflict was general or particular to `0.0` (it is general). (b) The
27-point grid in §6 **is gate 5**, not variant search. (c) Per the v4 vol diagnostic's
finding that `not risk_off` ≡ `vol is LOW` for this strategy (it takes zero BEAR
entries), the H6 filter is **one** variant, and it was already examined and refuted by
that diagnostic — it is not re-counted here.

**Stopping rule, pre-registered and now triggered.** *Stop after two mechanism-motivated
variants unless one of them produces a filtered OOS expectancy that is (i) positive and
(ii) at least 2 SE above zero on the clustered measure, without breaking a gate v0.1.0
passes.* Variant 2 is positive but only **0.60 SE** clustered above zero, and it breaks
gate 6. **The rule fires: stop.** Do not try a third.

This matters more here than elsewhere. §2.2 records the asymmetry explicitly: v4's gate 9
already passes on all four snapshots (a calm, persistently bullish sealed year that is
exactly this strategy's best regime), so a v0.2.0 that repaired gates 3/4/5/7 would
inherit a friendly sealed test providing **no independent check**. v4 is the strategy in
this program most likely to manufacture a spurious pass under repeated trying, and the
discipline that protects against that is the stopping rule, not the ladder.

**Recommended total across all three v4 angles: ≤ 3 implemented variants.** This angle
contributes **0**. The exits/risk angle should note that the v4 MFE diagnostic has already
refuted its headline lever (SMA-tracking target, Δ = −0.003R ± 0.004) and that the 6-bar
leash is a net positive, so its budget should also be small.

---

## 10. Sealed-look accounting

**This proposal consumes zero sealed looks.** No sealed bar was read; gate 9 was never
evaluated. The baseline count stands at **k = 5**.

Reproducing the §0.1 ledger — the four existing locked sealed tests for
`mean_reversion.short_swing` v0.1.0 (version 4), one per snapshot, unique per
`(strategy_version_id, dataset_snapshot_id)` (`db/models/research.py:263`):

| Ver | Strategy | snap 1 `universe_25_baseline_legacy` | snap 2 `universe_25_baseline` | snap 3 `universe_24_ex_meta` | snap 4 `universe_25_meta_continuity_corrected` |
|---|---|---|---|---|---|
| 2 | `trend_continuation.short_swing` | id 1: +0.3246R / 112 ✅ | id 6: +0.3246R / 112 ✅ | id 11: +0.2982R / 109 ✅ | id 16: +0.3246R / 112 ✅ |
| 3 | `trend_continuation.medium_swing` | id 2: +0.0109R / 98 ✅ | id 7: +0.0109R / 98 ✅ | id 12: −0.0294R / 95 ❌ | id 17: +0.0109R / 98 ✅ |
| **4** | **`mean_reversion.short_swing`** | **id 3: +0.1230R / 91 ✅** | **id 8: +0.1230R / 91 ✅** | **id 13: +0.1278R / 84 ✅** | **id 18: +0.1230R / 91 ✅** |
| 5 | `relative_strength.medium_swing` | id 4: +0.2935R / 16 ✅ | id 9: +0.2935R / 16 ✅ | id 14: +0.2935R / 16 ✅ | id 19: +0.2935R / 16 ✅ |
| 6 | `volatility_breakout.short_swing` | id 5: −0.0979R / 10 ❌ | id 10: −0.0979R / 10 ❌ | id 15: −0.0979R / 10 ❌ | id 20: −0.0979R / 10 ❌ |

*(Row 4's figures are quoted for ledger completeness under R2's disclosure requirement.
Per R1 they are used below only for **disposition**, never for design — and no design
choice in §§1–9 is derived from them.)*

**If this proposal were implemented** (it is not recommended): registering
`VERSION = "0.2.0"` creates a new `StrategyVersion` row, hence a never-before-sealed
gate 9. Sealing it on snapshot 3 would be **look 6** for this strategy family. Evaluating
the same v0.2.0 additionally against a new W1 expanded snapshot would be looks **6 and
7**. A pass on look 6 must be reported as *"passed on look 6"*, never as an unqualified
pass. No look counter exists in code (R2) — grep for `sealed_look` / `look_count` returns
nothing — so this disclosure is manual and must be copied into the final report verbatim.

**Pre-registered leading snapshot, per R1.** The report will lead with **snapshot 3**,
because it is the **only** snapshot on which gate 8 (`data_quality_and_leakage`) passes
for any version — snapshots 1 and 2 fail on META's 90 missing sessions and snapshot 4
fails because `META_CONT` is not `massive`-sourced (§0.1, and re-confirmed here: 2,510
`continuity_bridge:1` bars, zero `massive`). The choice is forced by a pre-sealed
data-quality gate, not selected after seeing any outcome. The other three sealed draws
are disclosed alongside it in the table above, in every case.

**R3 staleness trap.** `upsert_strategy_version` (`persistence.py:46-93`) refreshes
`spec_json` and `git_sha` on the *same row* when the version string is unchanged, so
editing `mean_reversion.py` without bumping `VERSION` would recompute gates 1–8 against
new code while gate 9 replays sealed test **id 13**, measured against the old code — a
silently invalid pass. Because this proposal recommends **no code change**, the trap is
not engaged; if any later v4 proposal is implemented, verify that its
`StrategySealedTest.strategy_version_id` is a row created by that run (§4.3).

---

## 11. Null option — and it is the recommendation

**Recommendation: take the null option. Write the documented "does not pass" for
`mean_reversion.short_swing`, and implement no v0.2.0 from this angle.**

This is not a fallback reached after the change failed to be interesting. It is the
disposition the pre-registered falsifiers F-6 and F-7 selected, and it is argued on the
merits:

1. **The mechanism is real and now settled, and it still does not produce a passing
   strategy.** H13 is the strongest pre-sealed regime effect found for v4 —
   **+0.3038R at 2.01 SE clustered**, consistent in sign across all four folds and both
   distinct snapshot populations, corroborated independently by the gap-tail density
   (12.55% vs 4.36%) and the exit mix (21% vs 54% target hits). Acting on it produces a
   strategy earning **+0.0201R ± 0.0591** over nine pre-sealed years: a **zero**-expectancy
   strategy, not a profitable one. Gross of the modelled 0.028R cost that is ~+0.048R of
   raw edge, essentially all of it consumed by frictions — and by 2× spread, entirely.
2. **Four gates fail either way, and one of the new failures is worse.** v0.1.0 fails
   gates 3, 4, 5, 7. The v0.2.0 fails gates 4, 5, 6, 7. Trading a gate-3 failure for a
   gate-6 failure is not progress, and gate 6's is the harder kind: it is a **coverage**
   failure created by the fix itself.
3. **The gate-3/gate-6 conflict is structural and closes the whole angle (§5.3).** The two
   admissible parameter regions are disjoint on both populations. Any v4 proposal that
   conditions entries on market direction — the definition of this angle — buys gate 3
   with gate 6. A judge synthesising the three v4 proposals should treat "condition on
   regime/market context" as **measured and closed**, not as untried.
4. **Gate 4 is a point-estimate problem no universe fixes.** Required n is **6,894**
   against 212; W1's 6.25× gives ≈1,325. Per §3(a) breadth cannot move gate 7's
   risk-adjusted point estimate at all, and the clustered design effect (1.87× for this
   strategy) means the required-n figures are **lower bounds**.
5. **Gate 9 provides no independent check here, so the usual safety net is absent.** v4's
   sealed test passes on all four snapshots on a calm bullish year that is exactly this
   dip-buy's best regime *(sealed figures used for disposition only, R1)*. A v0.2.0 that
   repaired the pre-sealed gates would inherit a friendly gate 9 that could not catch an
   overfit. Under R5 that raises the bar for shipping, and this proposal does not clear
   the ordinary bar, let alone a raised one.

### What the documented "does not pass" should carry

- The §0.1 sealed ledger and the explicit statement **k = 5, zero looks consumed by the
  design phase**.
- The gate-by-gate table for v0.1.0 on snapshot 3, with trade sets tagged and gate 6's
  **60 unbucketed** trades stated.
- The three W2 diagnostics as the evidentiary spine: **H6 refuted** (one fold, reverses in
  F1), **H9 refuted** (trigger self-normalising by construction), **H8 survives only
  narrowly** and its two actionable components refuted (SMA-tracking target −0.003R ±
  0.004; the 6-bar leash a net **+0.0410R**), plus **H13 established and shown
  insufficient** by this document.
- The honest restatement of the headline number, which the clustered bootstrap requires:
  v4's OOS −0.0837R is **−0.96 SE** from zero once same-date clustering is respected.
  **v4 has no measurable edge; it is not a measured loss.** Any future claim to have
  "fixed a 0.08R deficit" is a claim to have fixed noise.
- The four remaining unfalsified levers, correctly scoped: **H7 breadth** (needs W1 and
  new `StrategyContext` plumbing), and the untested `time_stop_bars` / `sma_window` /
  `z_lookback` / `atr_window` region (§0.5) — noting that H8's diagnostic already found
  the leash to be a net positive, so that region is less promising than §2.2 assumed.

### Two things worth doing regardless of disposition

Both are permitted under R4 (more searching, never weaker) and neither requires a
strategy change:

1. **Add `market_ret_63d_min` — or whatever parameter a future v4 variant introduces — as
   a third gate-5 axis** (`promotion.py:189-197`). §6.1 shows the legacy 2-axis grid would
   have scored this v0.2.0 at **88.9% / 75.0% (PASS)** while the honest 3-axis grid scores
   it **55.6% / 66.7% (FAIL)**. That is §0.5's hidden-fragility warning demonstrated with
   numbers on a live example, and it is the single cheapest integrity improvement
   available to this program.
2. **Record H13 in the W1 file.** If the universe is expanded, the pre-registered
   expectation for a filtered v4 should be written down **in advance**: gate 6's bear
   bucket plausibly reaches ≈12 (from 47 eligible bear sessions × breadth) and gates 4 and
   7 remain failing. Writing that down first is what stops "gate 4 still fails" from being
   mistaken for new information later.

---

## Appendix — reproduction

| Artefact | Path |
|---|---|
| Raw per-trade records, four snapshots, with signal-bar regime context | `…/mean_reversion_short_swing--signal_regime.json` (`base_recs`) |
| Gate-by-gate re-simulation, four snapshots + 27-point grids | same file (`forecast`) |
| Gate-3/gate-6 threshold frontier | same file (`tradeoff`) |

Deterministic: the engine has no RNG and no wall-clock dependence; `bootstrap_ci` is
seeded (`montecarlo.py:18-20`, seed 20240101). Re-running reproduces every figure exactly,
including the v0.1.0 baselines that match evaluations 34 and 28 on every gate.
