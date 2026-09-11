# Proposal — `volatility_breakout.short_swing` v0.1.0 (version 6)
## Angle: UNIVERSE / POWER — "re-run the unchanged rules on the expanded snapshot, and pre-register everything that can happen"

**One line.** Change **nothing** in `src/`; build the pre-registered 150-symbol snapshot
(W1) and evaluate the **unchanged v0.1.0** rules on it once — but pre-register, before
the data exists, that the expanded snapshot is a **different estimand** (the trade
population goes from 74% ETF to ~16% ETF), that **gate 7 is expected to flip to PASS for
a purely mechanical turnover reason** (contradicting W1 §8), that **gate 4's outcome is
genuinely unpredictable** rather than a confident FAIL, and that a pass obtained this way
must be reported as a composition/turnover result, not as evidence the edge improved.

**Status: PROPOSAL. Nothing was executed against the live system.** No file under `src/`
or `tests/` was modified, no provider API was called, and nothing was written to
`data/signalforge.sqlite`. Every number labelled FACT below was produced either by a
read-only `SELECT` (`sqlite3` with `mode=ro`) or by an in-process call to
`research.backtest_runner.run_strategy_over_universe` / `research.portfolio_metrics.compute_portfolio_metrics`
inside a default `session_scope()` (`write=False`, `db/session.py:99`; the runner contains
no `session.add/flush/commit`). Computation date 2026-09-10.

**Claim labelling.** **FACT** = verified against `file:line` or a query/computation run
for this document. **DERIVED** = arithmetic on FACTs, derivation shown. **HYPOTHESIS** =
an inference a later phase must test. **Every estimate carries a standard error; a
difference under 2 SE is not evidence** (MAP §0.3).

**Governing documents.** `docs/research/STRATEGY_COMPLETION_MAP.md` §0, §1 (R1–R10),
§2.3, §3(a), §4.0–§4.3; `docs/research/STRATEGY_COMPLETION_PLAN.md`;
`docs/research/diagnostics/w1_universe_preregistration.md`;
`docs/research/diagnostics/v6_regime_power.md`;
`docs/research/diagnostics/clustered_bootstrap_all.md`;
`docs/research/diagnostics/pipeline_hardening_spec.md`.

**Sealed-window discipline (R1).** No quantity inside the sealed window
(2025-09-08 → 2026-09-08 on snapshots 2–4; 2025-09-07 → 2026-09-07 on snapshot 1) was
computed for this document. Every new number below is on the pre-sealed span
**2016-09-10 → 2025-09-07**. Sealed numbers appear only in §10 (the ledger, a disclosure)
and in §11 (disposition, which R1 permits and which is marked inline).

---

## 1. Mechanism

**The hypothesis this addresses is H10 (power), and the honest form of H10 is narrower
than "more data".** v6 fires **1.00 trades per symbol-year** (FACT,
`v6_regime_power.md` §4: 211 trades over 211.1 symbol-years) against v2's 5.54 and v5's
2.68, because its entry demands two partially anti-correlated states on the same bar —
`ATR(10)/ATR(50) ≤ 0.75` **and** a close through the 20-day Donchian channel
(`breakout.py:92-99, 102`). Scarcity is structural, so every statistic about v6 on 24
symbols is measured with a standard error large enough to swallow the whole effect: OOS
SE = 0.2134R on n = 51 (FACT, recomputed; §3.1), sealed SE = 0.49R on n = 10 (MAP §0.3).
The market mechanism this proposal relies on is therefore **not** a claim about how
breakouts behave. It is the claim that **a volatility-contraction breakout is a
symbol-level, episodic event whose per-symbol arrival rate is roughly independent across
names**, so the only way to observe it enough times to say anything is to watch more
names over the same calendar. `v6_regime_power.md` §4 establishes the condition that
makes this sound: the engine caps one open position per symbol
(`engine.py:149`), and at ~1 trade/symbol-year with a 10-bar leash that cap is nowhere
near binding, so trade count scales linearly with symbol count.

**But the same evidence shows breadth is not a neutral magnifying glass, and that is this
proposal's actual contribution.** Two mechanisms make the expanded run a *different
experiment*, both measurable on pre-sealed data and both quantified in §3:

1. **Composition (a distribution shift in the trade population, not just the symbol
   population).** Snapshot 3 is 62.5% ETFs by symbol but **74.4% ETFs by trade**
   (FACT: 157 of 211). The pre-registered 150-symbol universe is 10% ETF by symbol and
   projects to **~16% ETF by trade** (DERIVED, §3.3). Since v6's measured pre-sealed
   expectancy differs between the two classes by **+0.4839R ± 0.2018** (§3.2), the
   expanded snapshot's pooled expectancy is an average over a *different mixture* — it can
   move a long way for reasons that have nothing to do with the rule set.
2. **Gate 7 is a turnover gate as coded, and breadth is turnover.** FACT
   (`portfolio_metrics.py:109-111`): `sharpe = (mean_r / std) × √(trades_per_year)`,
   while the benchmark side is a buy-and-hold daily-return Sharpe that does not move
   (`promotion.py:216-246`). MAP §3(a) and §2.3 state that "breadth does not move a
   risk-adjusted point estimate" and W1 §8 pre-registers gate 7 as an expected FAIL.
   **Both are wrong on this code path** (§3.5). Gate 7 flips on breadth alone at
   **1.17–1.28× today's trade rate** on all four snapshots, against a projected 4.55×.

New hypothesis, stated in §2-form so it can be scored and killed:

> **H13 (composition, not power, dominates the expanded re-run).** The change in v6's
> gate outcomes between snapshot 3 and the 150-symbol snapshot will be driven mainly by
> (a) the ETF→single-name mix of the trade population and (b) the mechanical
> √(trades/year) term in gate 7's Sharpe — not by the reduction in sampling error.
> *Falsified if* (§4) the expanded snapshot's ETF-only sub-sample expectancy and the
> single-name-only sub-sample expectancy are each within 2 SE of their snapshot-3
> counterparts **and** the pooled point estimate is within 2 SE of +0.0613R **and** gate 7's
> Sharpe divided by √(trades/year) is within 2 SE of today's 0.1368.

---

## 2. Exact change

### 2.1 Strategy code: **no change** — and that is the pre-registered first move

| File / symbol | Before | After |
|---|---|---|
| `src/signalforge/research/strategies/breakout.py` — `VERSION` | `"0.1.0"` (line 21) | **`"0.1.0"` (unchanged)** |
| `breakout.py` — `BreakoutParams` (:25-32) | `channel=20, contraction_max=0.75, atr_window=14, stop_atr=1.75, target_atr=3.5, time_stop_short=10, time_stop_medium=40` | **unchanged, every field** |
| `breakout.py` — `evaluate` (:90-124) | as written | **unchanged** |
| `research/strategies/__init__.py:43-51` (`default_strategies()`) | 6 entries | **unchanged** (no v0.2.0 sibling registered) |
| `research/promotion.py:199-208` (`_sensitivity_plan`, `volatility_breakout` prefix) | `contraction_max [0.65,0.75,0.85] × stop_atr [1.5,1.75,2.0]` | **unchanged** (§6 explains why this is compliant, and verifies the axes are live) |
| any file under `src/` or `tests/` | — | **no edit of any kind** |

**Why `VERSION` must NOT be bumped, and why that is R3/R7-compliant.** R3 requires a
version bump for **behavioural change**; there is none here, so bumping would create a
`StrategyVersion` row whose code is byte-identical to version 6 and would corrupt the
look ledger rather than protect it. The staleness trap R3 warns about cannot fire,
because it is a *code changed, version reused* trap; here the code is unchanged. FACT
(`db/models/research.py:263`): `StrategySealedTest` is unique per
`(strategy_version_id, dataset_snapshot_id)`, and FACT (`promotion.py:377-384`)
`_get_or_create_sealed_test` reads before recomputing — so evaluating version 6 against a
**new** snapshot does not replay snapshot 3's locked sealed test; it **mints a new, sixth
one** (§10). That is the entire sealed cost of this proposal and it is paid deliberately.

### 2.2 What *is* created (data and invocation artefacts, not strategy behaviour)

1. **`DataSnapshot` key `research_150_massive_10y_2026-09-08`**, exactly as pre-registered
   in W1 §5, created with `key=` passed explicitly (FACT, `promotion.py:310-329`: a keyed
   row is immutable-by-contract). Symbol rule W1-SEL, composition rule W1-COMP,
   completeness rule W1-COMPLETE, reserve list W1 §11.3 — **all adopted verbatim; this
   proposal changes none of them.**
2. **One in-process evaluation script** (W1 §9.2 resolution **A**, recommended over the
   `--dataset-key` CLI edit **B** because B is a `src/` change and this angle's whole
   claim is that no `src/` change is needed):

   ```python
   evaluate_promotion(
       session, VolatilityBreakout(Horizon.SHORT_SWING),
       symbols=<the final 150>, source="massive",          # never None — W1 §9.1
       dataset_snapshot=<the keyed row>,                   # never unkeyed — W1 §9.2
       ...,
   )
   ```
   Pre-integration assertions, required before the result is read: (i)
   `StrategyPromotionEvaluation.dataset_snapshot_id` equals the keyed row's id; (ii) no
   `universe_auto_150sym_*` row was created; (iii) the new
   `StrategySealedTest.strategy_version_id` is version **6** and its
   `dataset_snapshot_id` is the keyed row (a *new* row, not a replay of ids 5/10/15/20);
   (iv) `data_provenance.sources == ["massive"]`.
3. **Five read-only diagnostic runs** that produce no database rows and cost no sealed
   look (§5.11): the ETF/CS decomposition on the new snapshot, the 126-new-symbols-only
   pre-sealed run, the month-clustered bootstrap, the leave-one-month-out sweep, and the
   four spread re-pricings.

### 2.3 The operational consequence of a PASS, pre-registered before it can surprise anyone

FACT (`promotion.py:945-952`): a passing evaluation sets **both** `Strategy.status` and
`StrategyVersion.status` to `PAPER_APPROVED` and writes an audit row. FACT
(`approval_scope.py:45-66, 69-94`): the resulting approved scope carries
`dataset_snapshot_id` = the 150-symbol row, and `scan_scope_matches` requires the **live
scan's** snapshot id to equal it. FACT (`research/scan.py:165` + `get_settings().research.universe`
= 25 symbols): the live scan resolves a 25-symbol snapshot. **Therefore a v6 pass on the
expanded snapshot produces a PAPER_APPROVED strategy that can generate no live paper
candidate at all** (`ledger.py:473-512` `assert_auto_simulate_allowed` fails at
`scan_scope_matches`), while simultaneously adding a row to the operator's probation
dashboard (`paper_probation.py:100-130`). `approved_scopes` is keyed by
`strategy_version_id`, so v2's and v5's `scopes[0]` selection is **not** disturbed
(R7b satisfied). The operator must be told this *before* approval line 2: a pass here is
a research verdict that changes a live surface and buys **zero** confirming evidence
under R8 unless `cfg.research.universe` is later changed, which is an operating decision
outside this program.

---

## 3. Pre-sealed evidence (all with standard errors)

All figures in §3 are new computations for this document on the pre-sealed span
**2016-09-10 → 2025-09-07**, snapshot 3's 24 symbols, `source="massive"`, frozen cost
model (`CostModel()` = commission 0, `slippage_bps=3.0`, `half_spread_fill_penalty=True`,
`costs.py:11-16`), proxy SPY.

### 3.1 Reproduction check (the diagnostic measures the same objects the gates measured)

FACT. Recomputed vs stored `gates_json` (eval 36, snapshot 3): pre-sealed trades
**211 = 211**; OOS **51 = 51**; OOS expectancy **+0.06135 = +0.0613**; gate-7 Sharpe
**0.6665 vs 0.666**, turnover **23.75 = 23.75**; gate-5 grid **6/9 positive, 3/4
neighbours = 67% / 75%**. Empirical OOS per-trade sd **1.5242** (MAP §0.3's inverted-CI
value 1.554 is 2.0% higher); all-pre-sealed sd **1.2097**.

### 3.2 v6's expectancy differs by instrument class — the load-bearing new number

FACT (computed):

| Trade set | Class | n | expectancy | per-trade sd | **SE** |
|---|---|---:|---:|---:|---:|
| all pre-sealed (gates 1/6/7) | **ETF (15)** | 157 | **+0.0412R** | 1.1471 | **0.0915** |
| all pre-sealed | **single names (9)** | 54 | **+0.5251R** | 1.3222 | **0.1799** |
| all pre-sealed | pooled | 211 | +0.1651R | 1.2097 | 0.0833 |
| **OOS only (gates 2/3/4)** | **ETF** | 37 | **−0.0636R** | 1.4938 | **0.2456** |
| OOS only | **single names** | 14 | **+0.3914R** | 1.6106 | **0.4305** |
| OOS only | pooled | 51 | +0.0613R | 1.5242 | 0.2134 |

DERIVED. Single-name minus ETF, **all pre-sealed**: **+0.4839R ± 0.2018 = 2.40 SE** —
above the 2 SE bar on the iid standard error. Under the program's own measured
month-clustering haircut of ~1.6× (`v6_regime_power.md` §6.1) it becomes **~1.50 SE**,
i.e. **below** the bar. On the **OOS** cut the difference is **+0.4550R ± 0.4956 =
0.92 SE — not evidence.**

**Honest reading, and it is deliberately two-sided.** This is *suggestive, not
established*. It is enough to say the expanded snapshot is a different estimand (a
mixture change of this magnitude cannot be assumed neutral); it is **not** enough to
predict the direction of the change, and §3.4 gives a strong reason to think the
single-name figure is inflated by hindsight.

### 3.3 The breadth multiplier is 4.55×, not 6.25× — measured, not assumed

FACT (computed): ETF symbol-years 131.31 (33,090 bars ÷ 252), single-name symbol-years
79.79 (20,106 ÷ 252). Entry rates:

| Class | trades | symbol-years | **trades / symbol-year** | Poisson SE |
|---|---:|---:|---:|---:|
| ETF | 157 | 131.31 | **1.1956** | ±0.0954 |
| single name | 54 | 79.79 | **0.6768** | ±0.0921 |

DERIVED: the ETF:single-name signal-rate ratio is **k = 1.767 ± 0.279** (delta method),
i.e. **2.75 SE above 1** — the ETF concentration W1 §4.3 raised as a hypothesis is
measurable, and W1's uniform-rate assumption (k = 1) is rejected at >2 SE.

DERIVED: applying these rates to W1-COMP's 15 ETFs + 135 single names,
trades/year goes from `15(1.1956) + 9(0.6768) = 24.03` to
`15(1.1956) + 135(0.6768) = 109.30`, a multiplier of **4.549 ± 0.418** — **not** MAP
§3(a)'s 6.25× (which assumes uniform per-symbol rates). Projections:

| Quantity | today (24 sym) | **projected (150 sym)** |
|---|---:|---:|
| pre-sealed trades | 211 | **≈ 960 (±88)** |
| OOS trades | 51 | **≈ 247** (232 by flat multiplier; 247 with per-class OOS rates) |
| sealed-window trades | 10 | **≈ 46** (W1 §8 said 62 on the 6.25× assumption) |
| ETF share of trades | **74.4%** | **≈ 16.4%** |

Cross-check on a second snapshot (DERIVED, R10): snapshot 2 = snapshot 3 + META. FACT
(stored evals 18/30): 213 pre-sealed trades, i.e. META contributes 2. ETFs are unchanged
at 157, so the single-name rate becomes `56 / (21,320/252) = 0.662`/symbol-year and
**k = 1.807** — within 0.15 SE of 1.767. The multiplier estimate is not a snapshot 3
artefact.

### 3.4 Why the single-name number is probably too good — stated before the run, not after

**HYPOTHESIS (hindsight/survivorship in the *current* universe, not the new one).** The 9
single names in snapshot 3 are `AAPL, AMZN, GOOGL, HD, JPM, MSFT, NVDA, UNH, XOM` — a
hand-picked mega-cap set. A long-only breakout evaluated on the decade's best-performing
mega-caps is a hindsight-favoured sample, and **+0.5251R ± 0.1799 is plausibly measuring
that selection rather than a single-name effect**. The 135 names of W1-COMP are selected
by a *2026* liquidity rule (also not point-in-time; W1 §12.5–12.6) but are far less
concentrated in hindsight winners, reaching down to `TRV` at 598 $M/day.

**Pre-registered consequence:** the composition-aware forecast of §5 is reported as a
*range whose optimistic end rests on a hindsight-suspect estimate*, and if the expanded
run's single-name expectancy comes in far below +0.5251R, that is **confirmation of this
caveat, not a disappointment to be explained away.**

### 3.5 Gate 7's Sharpe is `(mean/sd) × √(trades per year)` — verified, and it changes the W1 forecast

FACT (`portfolio_metrics.py:109-111`):
`trades_per_year = n / (span_days/365.25)`; `sharpe = (mean_r/std) × √trades_per_year`.
FACT (`promotion.py:216-246`): the benchmark side is `cagr / ann_vol` from SPY daily
returns — **0.719 on every one of the four snapshots** (stored evals 12, 30, 36, 42) and
independent of the strategy's trade count.

FACT (computed, snapshot 3): `mean/sd_pop = 0.1651/1.2068 = 0.1368`;
`0.1368 × √23.75 = 0.6665` vs the stored **0.666**. The identity reproduces the gate.

FACT (stored gate-7 evidence, all four snapshots) and DERIVED (the turnover multiple that
would flip gate 7, `(0.719/sharpe)²`):

| Snapshot | strategy Sharpe | turnover/yr | SPY | **turnover multiple needed to pass gate 7** |
|---|---:|---:|---:|---:|
| 1 `universe_25_baseline_legacy` (eval 12) | 0.635 | 23.97 | 0.719 | **1.282×** |
| 2 `universe_25_baseline` (eval 30) | 0.635 | 23.97 | 0.719 | **1.282×** |
| 3 `universe_24_ex_meta` (eval 36) | 0.666 | 23.75 | 0.719 | **1.166×** |
| 4 `universe_25_meta_continuity_corrected` (eval 42) | 0.665 | 24.65 | 0.719 | **1.169×** |

**On all four snapshots gate 7 needs only 1.17–1.28× more trades per year at unchanged
per-trade quality — about 28–31 symbols.** The projection is 4.55×.

**Direct empirical demonstration that gate 7 rewards turnover rather than edge** (FACT,
computed, same 24 symbols, pre-sealed): at `contraction_max = 0.85, stop_atr = 1.75` v6
takes 477 pre-sealed trades, turnover 53.69/yr, **Sharpe 0.924 > SPY 0.719 → gate 7 would
PASS**, while its **OOS expectancy is −0.0512R** and gate 3 would fail. A configuration
with a *negative* out-of-sample edge clears gate 7 on trade count alone. This is a
property of the gate's Sharpe convention (per-trade Sharpe annualised by √turnover vs a
daily-return benchmark Sharpe), not a defect introduced by anything proposed here — and it
is exactly why §5 requires a pass to be disclosed as such.

### 3.6 What the sample-size reduction does and does not buy (the honest H10 core)

DERIVED, from `v6_regime_power.md` §5 and §6 plus §3.3's multiplier:

| | today | at n ≈ 247 |
|---|---:|---:|
| SE(OOS expectancy), iid | 0.2134R | **0.0987R** |
| SE(OOS expectancy), month-clustered (×1.628) | 0.3474R | **0.1607R** |
| gate-4 hurdle `0.02 + 1.96·sd/√n` (sd 1.55) | +0.4465R | **+0.2133R** |
| required n at exp = +0.0613R | 5,439 (iid) / 14,413 (clustered) | unchanged — **not reachable**: ≈2,554 ten-year symbols, DB holds 26 with `massive` history |

---

## 4. Falsification — stated before the run, and required to hold on all four snapshots (R10)

This proposal is falsifiable in two distinct places: the **claims** it makes, and the
**plan** it pre-registers.

**F1 (kills the breadth-multiplier claim).** The measured multiplier 4.549 ± 0.418 rests
on per-class rates. *Falsified if*, on the expanded snapshot, the realised pre-sealed
trade count is outside **960 ± 3 SE (≈ 700–1,220)**. Cross-snapshot check already
performed: k = 1.767 (snap 3) vs 1.807 (snap 2), 0.15 SE apart (§3.3); snapshots 1 and 4
carry the same 15 ETFs plus META/META_CONT and their stored trade counts (213, 219) are
within 4% of snapshot 3's 211, so no snapshot supports a materially different rate
structure.

**F2 (kills the gate-7 mechanism claim, H13b).** *Falsified if* the expanded run's
gate-7 evidence blob fails the identity `sharpe ≈ (avg_trade_r / sd_pop) × √turnover_per_year`
to within 1%, or if gate 7 fails at a turnover above 1.30× today's 23.75/yr. This is an
algebraic property of `portfolio_metrics.py:109-111`, so it cannot be snapshot-dependent;
it is nevertheless verified on all four stored snapshots in §3.5 (0.631/0.635/0.666/0.665
against turnovers 23.68/23.97/23.75/24.65 — every one consistent with the identity).

**F3 (kills the composition claim, H13a).** *Falsified if*, on the expanded snapshot, the
ETF-only pre-sealed expectancy is within 2 SE of **+0.0412R**, the single-name-only
pre-sealed expectancy is within 2 SE of **+0.5251R**, **and** the pooled OOS point
estimate is within 2 SE of **+0.0613R**. (If H13a is falsified this way, the run reduces
to the plain power experiment W1 §8 describes, and W1 §8's forecast stands unamended.)

**F4 (kills the *plan*, i.e. the reason to run it at all).** The plan's premise is that
an unchanged re-run is informative. *It is falsified in advance* if either:
 (a) W1-COMPLETE (W1 §6.4) drops so many candidates that the final snapshot has **< 120
     symbols** — below that the projected multiplier falls under ~3.7× and the projected
     OOS n under ~200, at which point the gate-4 hurdle (+0.235R) exceeds even the
     optimistic composition-aware forecast's lower half and the run stops discriminating;
     **stop and re-consult the operator rather than substituting extra reserve names
     beyond the pre-registered list**; or
 (b) the pre-integration assertions of §2.2 fail (wrong snapshot id, an
     `universe_auto_150sym_*` row, a non-`massive` source, a replayed sealed test) — in
     which case **no result may be read at all**, because a result read from the wrong
     snapshot row is an unrecorded sealed look.

**F5 (the anti-rationalisation clause).** If gate 4 passes and the decomposition of §5.11
shows the ETF sub-sample expectancy statistically unchanged while the single-name
sub-sample carries the whole pass, the honest conclusion is **"the strategy's measured
edge is a single-name/composition effect, measured on a survivorship-biased,
non-point-in-time universe"** (§7), *not* "v6 works". This is written down now so it
cannot be renegotiated later.

---

## 5. Gate-by-gate forecast

Trade sets tagged per MAP §0.2: gates **2/3/4** read OOS only; gates **1/6/7** read **all
pre-sealed trades** (gate 7 despite its docstring, `config/research.py:111-113` vs
`promotion.py:775`). Projections use §3.3's multiplier 4.549 ± 0.418, per-class rates, and
sd = 1.55.

### 5.1 Gate 0 `data_availability` — PASS (unchanged)
Span 2016-10-17 → 2026-09-08 ≫ `MIN_PRESEALED_DAYS` = 350. Horizon is SHORT_SWING, not
INTRADAY. No risk.

### 5.2 Gate 1 `rolling_walkforward` (all pre-sealed) — PASS, high confidence
Today: folds **+0.4745/36, +0.1111/98, +0.0389/34, +0.1286/43 → 4 of 4 clear** (need 2 of
4 with n ≥ 15 and exp > 0). Projected fold counts ≈ **164 / 446 / 155 / 196**. The
per-fold floor is `sensitivity_min_grid_trades = 15` (`promotion.py:632` — the same
constant as gate 5's per-cell floor, MAP §4.3; nothing here changes it). Risk: fold
*signs*, not counts. Even if the two smallest fold expectancies flip negative, 2 of 4
still clears. **Forecast: PASS.**

### 5.3 Gate 2 `min_oos_trades` (OOS) — PASS, comfortably
51 → **≈ 247** (range 210–320) against a floor of 30. Required n = 30; the floor is met at
≈ 14 symbols (`v6_regime_power.md` §5). **Forecast: PASS.**

### 5.4 Gate 3 `net_expectancy` (OOS) — PASS at baseline cost, uncertain, and cost-fragile
Today +0.0613R ± 0.2134. Composition-aware projection **+0.3233R ± 0.3679** (§5.5).
Two standing fragilities, both pre-registered so neither is news: (i) dropping the single
month 2023-12 (7 of 51 trades) takes today's estimate to **−0.2623R**
(`v6_regime_power.md` §6.3) — the expanded sample should have ~4.5× more entry months,
which is the main thing that would fix this, and the leave-one-month-out sweep is
**mandatory** on the new snapshot; (ii) re-pricing at 31 bps round trip removes
0.0762R (§8). **Forecast: PASS at the frozen cost model, with an explicit
"fails at 31 bps" disclosure if the point estimate lands below +0.0762R.**

### 5.5 Gate 4 `bootstrap_ci` (OOS) — **genuinely uncertain; W1 §8's confident FAIL is not warranted, and neither is optimism**

Stated as a required n, per MAP §4.2 item 5, `n > (1.96·sd/(exp − 0.02))²`:

| Point estimate | sd | **required n (iid)** | **required n (month-clustered, ×2.65)** | projected n ≈ 247 |
|---|---:|---:|---:|---|
| +0.0613R (today's, composition-blind — W1 §8's assumption) | 1.554 | **5,439** | **14,413** | FAIL, decisively |
| +0.0613R | 1.5242 (empirical) | 5,232 | 13,866 | FAIL |
| **+0.3233R (composition-aware projection)** | 1.55 | **100** | **266** | **PASS on the iid gate; FAIL under clustering** |

DERIVED, the composition-aware projection: holding the 15 ETFs fixed (37 OOS trades) and
scaling the 9 single names by 135/9 (14 → 210 OOS trades) gives n = 247 with weights
0.150 / 0.850 and
`0.150(−0.0636) + 0.850(+0.3914) = +0.3233R`, forecast **SE = 0.3679R** (propagating the
two class SEs). The hurdle at n = 247 is **+0.2133R** (half-width 0.1933).

**So the pre-registered statement is: the forecast's own uncertainty (±0.368R) is nearly
twice the hurdle (+0.213R). Gate 4's outcome on this snapshot is not predictable.** Both
of the following are pre-registered as *expected possibilities*, and neither may be
reported as a surprise:
- **FAIL** (what W1 §8 predicts, and what happens if the single-name advantage is the
  hindsight artefact §3.4 suspects) — then §11's null option is written, unchanged.
- **PASS** — then the report must state, in the headline, that (i) the point estimate
  moved ~3–5× for a **composition** reason that was predicted in advance from pre-sealed
  data, (ii) it does **not** survive the program's own month-clustered bootstrap unless
  n ≥ 266 with the same estimate, and (iii) the iid gate is the gate that exists (R4) —
  it passed the gate, and the stricter statistic is disclosed alongside
  (`clustered_bootstrap_all.md`, `v6_regime_power.md` §6).

### 5.6 Gate 5 `parameter_sensitivity` (OOS per grid point) — the zero-margin case, no prediction offered
FACT (MAP §2.3, stored evals): snapshot 3 passes at **0.667 / 0.750** — the neighbour
fraction is **exactly** the 0.750 threshold (`sensitivity.py:194` tests `nb_frac < min`) —
while **snapshot 4 fails at 0.556 / 0.500**. FACT (reproduced here, §6): 6/9 positive,
3/4 neighbours.
FACT (`v6_regime_power.md` §5.2): at n = 51 a cell reads positive with probability 0.611
and `P(≥ 6 of 9)` = **0.510** — the positive fraction is a **coin flip**, so neither the
snapshot-3 pass nor the snapshot-4 fail is evidence.
Projected per-cell counts: thinnest cell 19 → **≈ 86**; baseline cell 51 → ≈ 247. Cells
comfortably clear the 15-trade floor. Sign reliability at 95% would need **1,736 per
cell** (≈ 816 symbols) — unreachable. **Forecast: no prediction. Whatever gate 5 returns
must be reported with the 0.51 coin-flip probability attached**, and a pass must not be
described as robustness.

### 5.7 Gate 6 `regime_coverage` (all pre-sealed) — likely PASS, and an unreportable failure if not
Today: **bull 167 / bear 0 / range 30**, with **14 unbucketed (6.6%)** — FACT
(`v6_regime_power.md` §3.1) all 14 are proxy-warmup entries between 2017-01-05 and
2017-07-25, none labelable with any data in the database, and all 11 distinct dates sit
above a rising SPY SMA (so they would label bull, not bear).

DERIVED, composition-weighted (solving the overall bull rate 6.845 per 1,000 gate-open
symbol-days into per-class rates at k = 1.767: **ETF 8.175**, **single name 4.628**), with
18 gate-open bear proxy sessions per symbol over the span:

| Bucket | today | **projected at 150 symbols** |
|---|---:|---:|
| bull | 167 | ≈ 760 |
| **bear** | **0 of 432 gate-open symbol-days** | **λ ≈ 13.5** (uniform-rate assumption gives 18.5) → **P(≥ 10) = 0.86** (0.99 at λ = 18.5) |
| range | 30 | ≈ 137 |
| **unbucketed (MAP §0.6 — mandatory to report)** | **14 (6.6%)** | **≈ 64 (6.6%)** — same fixed 200-session proxy warmup, more symbols inside it |

**Pre-registered, per `v6_regime_power.md` §5.3's corrected falsification rule:** the bear
rate is *unmeasured* (0 of 432 is 1.72 SE below the bull-rate expectation of 2.96 — under
2 SE, therefore not evidence). The expanded snapshot supplies ≈ 2,700 gate-open bear
symbol-days, above the 1,461 needed for the test to have power. **If the bear bucket
still comes in under 10, that is a power/availability outcome carrying no information
about the rule set, and it must not motivate any change** — least of all a change to the
inherited `not ctx.regime.risk_off` conjunct (`breakout.py:102`), which is the
signal-quality angle's territory and which this proposal deliberately does not touch.

### 5.8 Gate 7 `benchmark_comparison` (all pre-sealed) — **PASS expected, and it must be disclosed as a turnover artefact**
Contradicting MAP §3(a) ("breadth does not move a risk-adjusted point estimate") and W1 §8
("FAIL expected"). At unchanged per-trade quality (`mean/sd = 0.1368`) and projected
turnover `23.75 × 4.549 = 108.0/yr`: **Sharpe ≈ 0.1368 × √108.0 = 1.42** vs SPY **0.719**.
The break-even is 27.6 trades/yr, i.e. **1.163×**, i.e. ≈ **28 symbols** — so gate 7 flips
long before 150. It would take the 126 new names firing at **< 0.070 trades/symbol-year**
(10× below the measured single-name rate of 0.677 ± 0.092) for gate 7 to still fail.
**Forecast: PASS, high confidence — and the report must state that the pass comes from
`√(trades per year)`, that a configuration with a −0.0512R OOS expectancy also passes it
(§3.5), and that gate 7 therefore contributes little independent evidence of edge quality
on an expanded universe.** No threshold is touched (R4); this is disclosure, which R4
explicitly permits.

### 5.9 Gate 8 `data_quality_and_leakage` — PASS conditional on W1-COMPLETE
The binding risks are W1's own: a relisted ticker with a multi-year hole (`NBIS` named in
advance, W1 §2.4), and the **source-wide** checks (`db_unique_bars`,
`chronological_order`, `no_duplicate_sessions`, W1 §6.4) which fail the whole snapshot on
one duplicated bar anywhere in `massive`. Also standing: every call must pass
`source="massive"` or both sources load and duplicate bars appear **inside the sealed
window** (W1 §9.1). **Forecast: PASS if and only if W1-COMPLETE passes first; the
snapshot is not registered before it does.**

### 5.10 Gate 9 `sealed_final_test` — new locked test, low power, and it is **look 6**
Projected sealed n ≈ **46** (not W1 §8's 62, which used the 6.25× multiplier),
SE ≈ 1.554/√46 = **0.229R**. At that SE gate 9 would reject a genuinely +0.30R strategy
~10% of the time and a genuinely +0.06R strategy ~40% of the time. **Forecast: no
prediction; its result is disposition information only (R1), and it is the sixth look
(§10).**

### 5.11 Gate 10 `live_paper_probation` — passes as coded, but see §2.3
`health_monitor.enabled` is true, so the gate passes; the *substance* (R8's confirming
test) is unavailable because a 150-symbol approved scope cannot match the 25-symbol live
scan.

### 5.12 Mandatory disclosures attached to **any** outcome
1. ETF-only and single-name-only sub-sample expectancies with SEs, compared to §3.2's
   +0.0412 ± 0.0915 and +0.5251 ± 0.1799.
2. The **126-new-symbols-only** pre-sealed run (read-only, pre-sealed span only, **never**
   the sealed window — a sealed computation on an unregistered symbol set would be an
   unrecorded look). This is the closest thing to an out-of-sample *universe* test the
   program can run.
3. Gate 6's three buckets **and** the unbucketed count.
4. Month-clustered bootstrap CI alongside the iid gate-4 CI, with the half-width ratio as
   the effective-sample-size haircut (~1.6× expected).
5. Leave-one-month-out expectancy sweep (today one month moves it by 0.32R).
6. The four spread re-pricings (§8).
7. Per-symbol IS/OOS boundary dates, demonstrating W1 §2.4.1's alignment claim.
8. The §10 sealed ledger and the statement "this is look 6".

---

## 6. Sensitivity-grid plan

**Pre-registered axes: unchanged — `contraction_max ∈ {0.65, 0.75, 0.85} × stop_atr ∈
{1.5, 1.75, 2.0}`** (`promotion.py:208`). MAP §4.2 item 6 requires *every parameter the
v0.2.0 introduces or changes* to become an axis; **this proposal introduces and changes
none**, so the requirement is satisfied without adding an axis. Adding axes anyway
(`channel`, `target_atr`, `time_stop_short`) would be a *different* experiment: it changes
what gate 5 measures between the snapshot-3 baseline and the expanded run, destroying the
like-for-like comparison that is this angle's entire purpose. Those axes belong with the
signal-quality/mechanism proposal that actually changes those parameters.

**The no-op check MAP §4.2 item 6 demands — already performed, read-only, on pre-sealed
data.** The silent failure mode (a retained-but-unused field making all 9 points identical
and gate 5 passing at 100% having tested nothing, MAP §2.1) is **verified absent**:

FACT (computed for this document, snapshot 3, pre-sealed):

| `contraction_max` | `stop_atr` | pre-sealed trades | OOS n | OOS expectancy |
|---:|---:|---:|---:|---:|
| 0.65 | 1.50 | 58 | 19 | +0.4657 |
| 0.65 | 1.75 | 58 | 19 | +0.5828 |
| 0.65 | 2.00 | 58 | 19 | +0.4132 |
| 0.75 | 1.50 | 213 | 51 | +0.0296 |
| **0.75** | **1.75** *(baseline)* | **211** | **51** | **+0.0613** |
| 0.75 | 2.00 | 208 | 50 | +0.0646 |
| 0.85 | 1.50 | 480 | 139 | −0.0681 |
| 0.85 | 1.75 | 477 | 139 | −0.0512 |
| 0.85 | 2.00 | 474 | 139 | −0.0058 |

Both axes measurably move the OOS trade count (58 → 480 across `contraction_max`) and the
expectancy (`stop_atr` moves it by 0.032–0.170R at fixed `contraction_max`). Positive
fraction **6/9 = 0.667**; one-step neighbours of the baseline **3/4 = 0.750** — reproducing
the stored gate-5 evidence exactly. **Re-run this identical check on the expanded snapshot
before reading the gate-5 verdict**, and report the per-cell trade counts (projected
thinnest ≈ 86).

Note (MAP §4.3): the per-cell floor `sensitivity_min_grid_trades = 15` is the **same
constant** gate 1 uses (`promotion.py:632`). Neither is touched.

---

## 7. Leakage argument

**Within the `(series, t)` contract: nothing changes, and nothing new is introduced.** No
new feature, no new `StrategyContext` field (`base.py:15-19` untouched — no breadth or
cross-sectional term, which is exactly what makes this angle cheap), no change to
`features/daily.py`'s `atr_contraction` / `donchian_high` / `donchian_low`, all of which
slice to ≤ t by construction. `backtest/leakage.py:assert_no_lookahead` runs unchanged as
gate 8's self-check, over 150 symbols instead of 24 — strictly more coverage of the same
contract. The engine still fills at `t+1` (`engine.py:108, 134`).

**Where the real exposure is, and it is not lookahead in the code — it is lookahead in the
universe.** Stated plainly because no gate detects it:

1. **The symbol set is chosen with 2026 information and applied to 2016 bars.** W1-SEL
   ranks by 60-session median dollar volume over 2026-06-12 → 2026-09-08 and requires
   `list_date ≤ 2016-10-17`; discovery is active-tickers-only, so delisted and failed
   names cannot enter (W1 §12.6). A name illiquid in 2017 and liquid now still enters
   (W1 §12.5). This is **selection on the future at the universe level**, and it inflates
   results in a direction no gate measures.
2. **Snapshot 3 has the same defect, arguably worse, and §3.2 measures its size.** The 9
   hand-picked mega-caps return **+0.5251R ± 0.1799** against the 15 ETFs' **+0.0412R ±
   0.0915**. That +0.48R gap is the best available estimate of how much hindsight-favoured
   single-name selection is worth to this strategy — which is why §3.4 pre-registers that
   the expanded run's single-name expectancy is *expected to be lower* than +0.5251R.
3. **Bars are split-adjusted as of fetch date, not point-in-time**, and
   `validate.py:180-205`'s `adjustment_behaviour` check is a **no-op** for this source
   because `massive.py:212` sets `adj_close = close` (W1 §6.4). Expansion applies this
   known bias to 6× more names.
4. **The dual-source hazard is a leakage hazard, not just a hygiene one** (W1 §9.1):
   omitting `source="massive"` loads `massive_grouped` too, duplicating every session
   between 2025-01-03 and 2026-09-08 — i.e. **inside the sealed window**. `source="massive"`
   is asserted in the §2.2 pre-integration checks.

**Conclusion:** the leakage exposure of this proposal is entirely inherited from the
universe-construction step and is disclosed, quantified where possible (§3.2), and
unchanged in kind from the approved dataset. It adds no new code-level leakage surface.

---

## 8. Cost-model statement (quantitative)

**The cost model is unchanged and frozen (R4):** `CostModel(commission_per_share=0.0,
commission_min_per_order=0.0, slippage_bps=3.0, half_spread_fill_penalty=True)`
(`costs.py:11-16`); `engine.py:94` `slip = (3.0 + 5.0/2)/10,000`; `engine.py:143`
`costs_bps = 11.0` round trip; `backtest_runner.py:205-206` passes no `spread_bps`, so the
term is universe-independent.

**Per-trade cost in R at this proposal's parameters.** `stop_atr = 1.75` and, because the
`contraction_max ≤ 0.75` filter selects a contracted ATR by construction, reference
`ATR/price = 1.5%` → risk/price = 2.625%:
`cost_R = round_trip_bps/10,000 ÷ 0.02625`.

| round trip | equivalent quoted spread | **cost per trade** | v6 OOS at today's +0.0613R | at the composition-aware +0.3233R | **gate-7 Sharpe at 4.55× turnover** |
|---:|---:|---:|---:|---:|---:|
| **11.0 bps (frozen — what the gates use)** | 5 bps | **0.0419R** | **+0.0613R** | **+0.3233R** | **1.42** |
| 16.0 bps ("2×" per W1 §7.1) | 10 bps | 0.0610R | +0.0423R | +0.3042R | 1.26 |
| 26.0 bps (MAP §0.4 named case) | 20 bps = `max_avg_spread_bps` | 0.0990R | +0.0042R | +0.2662R | 0.93 |
| 31.0 bps ("5×" per W1 §7.1) | 25 bps | 0.1181R | **−0.0149R** | +0.2471R | 0.77 |
| 66.0 bps (MAP §0.4 named case) | 60 bps | 0.2514R | **−0.1482R** | +0.1138R | **−0.38** |

(The 11 / 26 / 66 columns reproduce MAP §0.4 and W1 §7.2–7.3 exactly. W1 §7.1 flags that
MAP §0.4 and §3(a) disagree on what "2× and 5×" means; like W1, this proposal reports
**all four** non-baseline points so the requirement is met under either reading.)

**Turnover delta and the resulting cost delta in R.** Per-symbol turnover is **unchanged**
— no rule, parameter or exit changes, so the per-trade cost in R is **identical** to
today's 0.0419R and the cost *delta per trade is exactly zero*. What changes is
**portfolio** turnover: 23.75 → ≈ 108 round trips/year (4.55×). Two consequences, both
pre-registered:
- **Gate 3/4 are unaffected by the turnover rise** (they are per-trade means).
- **Gate 7 is affected twice over** — √turnover raises Sharpe (§5.8) while any real spread
  widening lowers `mean_r` and therefore lowers Sharpe proportionally. The last column
  above shows gate 7 surviving to 31 bps and failing at 66 bps. **If the expanded run
  passes gate 7, the 26 and 31 bps rows must be reported next to it.**
- **The composition shift is a cost risk in itself**: the trade population moves from 74%
  broad ETFs (tightest quotes in the pool, held tight by creation/redemption arbitrage) to
  ~84% single names. W1 §4.4 establishes that no *new* name is less liquid than `XLRE`,
  already in the approved dataset (`TRV` 598 $M/day vs `XLRE` 214 $M/day) — but dollar
  volume is not spread, and the project holds **no spread data at all**
  (`universe/screen.py:47`, `spread_filter_not_licensed`). Every spread statement here is
  a modelling assumption (HYPOTHESIS), not a measurement.

---

## 9. Variant budget and stopping rule

**Strategy variants this angle intends to try: ZERO.** No rule, parameter, filter, exit or
threshold is changed. Under R5 this angle costs **0 of v6's variant budget**; the
proposed total for v6 across all angles is **2** (this one at 0 variants, plus the
signal-quality/mechanism angle's budget), consistent with MAP §4.1's "2 proposals, after
W1".

**Non-strategy budget: exactly one of each.** One universe build (126 paced GETs), one
`DataSnapshot`, one `evaluate_promotion` call, one new sealed test (look 6), and the
read-only diagnostics of §5.12 which create no rows and no looks.

**Stopping rule (binding):**
1. **Run once.** The unchanged v0.1.0 rules are evaluated on
   `research_150_massive_10y_2026-09-08` **one time**.
2. **No second universe.** If the result disappoints, this angle does **not** propose
   N = 300, a different composition rule, a different liquidity statistic, or dropping
   symbols. Any of those would be universe selection after seeing results — the same
   offence as tuning on the sealed window (MAP §3(a)) — and each would cost another look.
   The only permitted post-hoc symbol change is W1-COMPLETE's data-quality replacement
   from the pre-registered reserve list (W1 §11.3), applied **before** any backtest.
3. **No rule change may be motivated by this run's gate 4 or gate 7 result.** Gate 4
   failing is a pre-registered expectation under the composition-blind forecast; gate 7
   passing is a pre-registered mechanical artefact. Neither is new information.
4. **Hand-off, not escalation.** If the run fails, this angle terminates and hands to
   (a) the signal-quality/mechanism proposal — whose most promising pre-sealed-motivated
   target is the inherited `not ctx.regime.risk_off` conjunct at `breakout.py:102`, which
   shuts v6 out of 93% of bear sessions and 368 bull sessions
   (`v6_regime_power.md` §7) — or (b) §11's null option. Deciding between them on the
   basis of *this* run's sealed number is permitted (disposition, R1); designing a change
   from it is not.
5. **Hard stop at look 6 for v6 on new snapshots.** No third snapshot for this version.

---

## 10. Sealed-look accounting

FACT (`db/models/research.py:263`): `StrategySealedTest` is unique per
`(strategy_version_id, dataset_snapshot_id)`. FACT (`promotion.py:377-384`): a repeat call
on an existing pair returns the identical locked numbers. Therefore evaluating the
**unchanged** version 6 against a **new** snapshot mints a **new** sealed test — a genuine
additional look at the same sealed calendar year through a different universe.

**The baseline count is k = 5 per strategy** (MAP §0.1: four locked sealed tests, one per
existing snapshot, plus the pre-registered fifth look that a v0.2.0 on snapshot 3 would
represent). Reproducing the MAP §0.1 ledger in full:

| Ver | Strategy | snap 1 `universe_25_baseline_legacy` | snap 2 `universe_25_baseline` | snap 3 `universe_24_ex_meta` | snap 4 `universe_25_meta_continuity_corrected` |
|---|---|---|---|---|---|
| 2 | `trend_continuation.short_swing` | id 1: +0.3246R / 112 ✅ | id 6: +0.3246R / 112 ✅ | id 11: +0.2982R / 109 ✅ | id 16: +0.3246R / 112 ✅ |
| 3 | `trend_continuation.medium_swing` | id 2: +0.0109R / 98 ✅ | id 7: +0.0109R / 98 ✅ | id 12: −0.0294R / 95 ❌ | id 17: +0.0109R / 98 ✅ |
| 4 | `mean_reversion.short_swing` | id 3: +0.1230R / 91 ✅ | id 8: +0.1230R / 91 ✅ | id 13: +0.1278R / 84 ✅ | id 18: +0.1230R / 91 ✅ |
| 5 | `relative_strength.medium_swing` | id 4: +0.2935R / 16 ✅ | id 9: +0.2935R / 16 ✅ | id 14: +0.2935R / 16 ✅ | id 19: +0.2935R / 16 ✅ |
| **6** | **`volatility_breakout.short_swing`** | **id 5: −0.0979R / 10 ❌** | **id 10: −0.0979R / 10 ❌** | **id 15: −0.0979R / 10 ❌** | **id 20: −0.0979R / 10 ❌** |

**Executing this proposal takes version 6 from k = 5 to k = 6.** It is **look 6**, and any
result must be reported as "passed/failed on look 6", never as an unqualified verdict.
Because no `VERSION` bump occurs, no *further* look is created on snapshot 3 — v6's
snapshot-3 sealed test (id 15) is replayed identically, not redrawn.

Per W1 §8.1's tighter restriction, **only** version 6 is evaluated on this snapshot under
this proposal (version 4 later, under its own universe/power proposal). Versions **2, 3
and 5 are NOT evaluated on it** and stay at k = 5 — for v2 and v5 this is a prohibition,
not a preference (R7b: a passing scope on a second snapshot makes
`paper_probation.py:118`'s `scopes[0]` order-dependent for a **live** strategy;
`approved_scopes` issues no `order_by`, `approval_scope.py:45-66`).

**Which snapshot the report leads with, pre-registered per R1.** **Snapshot 3
`universe_24_ex_meta` remains the headline for all v0.1.0 statements**, because it is the
only snapshot on which gate 8 passes (MAP §0.1) — a pre-sealed data-quality reason, fixed
before any result is seen. The expanded snapshot is reported as a **separate experiment**
with its own gate table, never as an update to the snapshot-3 numbers, with the ledger
above reproduced alongside.

**Power note on gate 9 at the new snapshot (disposition information only, R1):** projected
sealed n ≈ 46, SE ≈ 0.229R. v6's four existing sealed draws are all the same 10 trades at
−0.0979R = 0.20 SE from zero (MAP §0.3) — they carry no information about sign, and they
are **not** cited anywhere in §1–§9 as support for anything.

---

## 11. Null option

**If the powered re-run fails — the expected case under the composition-blind forecast —
the deliverable is a documented "does not pass", not another variant.**

The document to be written is
`docs/research/designs/volatility_breakout.short_swing--does_not_pass.md`, and it carries:

1. **The exact blocking gates on look 6**, with trade sets tagged and each stated as a
   required n rather than a shortfall: gate 4 needs **5,439 OOS trades** (iid) or
   **≈ 14,400** under the program's own month-clustered bootstrap at the observed point
   estimate — DERIVED, **≈ 2,554 ten-year symbols**, against a database holding **26** with
   `massive` history and a project ceiling of `max_universe_size = 150`. **Gate 4 is not
   reachable by universe expansion at any feasible scale**; H11 (the edge magnitude is
   genuinely insufficient) stands.
2. **The pre-registered forecasts next to the outcomes**, so the reader can see which
   predictions held: this document's gate-7 PASS-by-turnover call, the gate-4
   "unpredictable" call, W1 §8's gate-4 FAIL call, and `v6_regime_power.md` §5.3's gate-6
   power call.
3. **The full sealed ledger (§10) and the statement "look 6".**
4. **The composition decomposition (§5.12 items 1–2)** — including the 126-new-symbols-only
   pre-sealed result, which is the program's only quasi-out-of-sample *universe* evidence.
5. **The three structural findings that make this an informative failure rather than a
   null result:** (i) v6's entry demands two partially anti-correlated states, so scarcity
   is by construction (MAP §2.3); (ii) its bear-regime coverage is governed by an
   **inherited** filter (`not ctx.regime.risk_off`, `breakout.py:102`) that is shut on 93%
   of bear sessions, not by the breakout rule (`v6_regime_power.md` §1); (iii) 68% of the
   point estimate is modelled transaction cost (0.0419R of +0.0613R) and one month of 51
   trades carries the rest.
6. **The honest closing statement:** *`volatility_breakout.short_swing` v0.1.0 does not
   pass the ladder on either the approved 24-symbol dataset or the 150-symbol expanded
   dataset; its measured edge is smaller than the sample can resolve, and the sample
   cannot be enlarged enough within this project's data footprint. It remains
   `experimental`; no v0.2.0 was shipped from this angle, and zero strategy variants were
   consumed.*

**And the symmetric case, pre-registered so it cannot be quietly upgraded.** If the run
**passes**, the deliverable is still not a clean promotion story: it is a promotion
**report with three caveats in the headline** — look 6 of 6; the pass is composition- and
turnover-driven (§5.5, §5.8) and predicted as such in advance; and the approved scope
cannot be exercised by the live scan (§2.3), so R8's confirming test is unavailable
without a separate operating decision. A pass that cannot be confirmed live is a weaker
outcome than the gate ladder alone suggests, and this proposal says so before the number
exists.

---

## 12. Self-assessed risks of this proposal

1. **The composition-aware gate-4 projection (+0.3233R ± 0.3679) leans on 14 OOS
   single-name trades.** Its SE exceeds the hurdle. It is offered to show the outcome is
   *unpredictable*, never as a forecast of a pass. §3.4 pre-registers that the optimistic
   half is probably hindsight.
2. **Linear scaling of trade count with symbol count** is justified
   (`v6_regime_power.md` §4: the one-position-per-symbol cap is not binding) but remains a
   projection; F1 gives the falsification band.
3. **The per-trade sd is assumed constant as the universe grows.** A single-name universe
   plausibly *raises* sd (gaps, earnings, idiosyncratic vol), which would make every
   required-n figure a lower bound twice over (clustering and sd).
4. **Gate 7's expected pass is a gate-convention artefact.** It is disclosed, not
   exploited: no threshold moves (R4), and §5.8 requires the disclosure in the headline.
   A reader who takes the pass at face value would be misled, which is precisely why it is
   pre-registered here rather than discovered afterwards.
5. **This angle cannot fix gate 4 and does not try.** Its honest value is that it makes
   every *other* v6 statistic measurable, converts three coin-flip gates into decidable
   ones, and pays exactly one look to do it.
6. **W1's data step is a live write to the production database** (126 paced GETs, one
   short transaction per symbol) and needs the operator's explicit approval lines (W1
   §10.1, §10.2). Nothing in this proposal authorises it.
7. **The 2×/5× spread convention is still ambiguous** between MAP §0.4 and §3(a) (W1 §7.1);
   this proposal reports all four points rather than guessing, and the operator should fix
   the convention.

---

*Proposal only. No file under `src/` or `tests/` was modified; no provider API was called;
nothing was written to `data/signalforge.sqlite`. Every FACT above is a `file:line`
citation, a read-only query result, or a read-only in-process computation whose method is
stated in the header; every DERIVED figure shows its arithmetic; every estimate carries a
standard error.*
