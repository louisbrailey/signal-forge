# D4 — ratcheting-trail closure diagnostic, and the D2/D3 shadow-stream state

**Strategy:** `trend_continuation.medium_swing` v0.1.0 (`strategy_version.id = 3`, `EXPERIMENTAL`)
**Pre-registration:** `docs/research/designs/trend_continuation_medium_swing.md` §12.2 (cells,
method and the five-clause bar), §12.3 F1′/F6, §11.2 (D2/D3)
**Date:** 2026-09-10 · **Companion JSON:** `v3_d4_closure.json`
*(The design's §13.1 file table names this deliverable `v3_trailing_pathlevel.md`; the
orchestrator's task names it `v3_d4_closure.md`. Same artefact, one filename — recorded so the
two documents can be reconciled.)*

---

## 0. Verdict, stated first

> **FACT — D4's pre-registered falsification does NOT fire.** Of the five clauses in §12.2,
> the three evidentiary clauses (1, 2, 3) **all fail**, and they fail **with the wrong sign**:
> not one of the six pre-registered cells has a positive point estimate on the deciding OOS cut
> on any of the four snapshots, on either form of the replay. The two robustness clauses (4, 5)
> hold — and holding, here, only confirms that the harm is real and uniform rather than a
> re-pricing artefact.
>
> Under §12.2's own disposition rule — *"If it does not clear: the exits-and-risk lane is
> **closed permanently** for this family; D1 records the closure with the numbers"* — **the
> exits-and-risk lane for `trend_continuation` is now closed.** H13 (exit-geometry local
> optimum) was supported on five of six axes and not established on the sixth; the sixth axis
> is now measured, and it supports H13 as well. §12.3's **F6** (the falsifier of H13 itself)
> **does not fire**.

**No strategy change is proposed by this document.** No variant is recommended, V-A′ is not
triggered, the variant count stays 0 and the look count stays k = 5 (0 looks added).

**Symmetric commitment discharged (§12.2).** The one positive point estimate anywhere in the
full 6 × 4 × 3-cut grid is the **in-sample** cut at (a = 1.5, g = 1.5) on snapshot 3:
**+0.0048R ± 0.0208 (0.23 SE, n = 752)**. It is on the wrong cut, it is 0.23 SE, and it is
**not a finding**. It is stated here only because the pre-registration requires favourable
point estimates to be disclosed rather than buried.

---

## 1. Provenance — everything below is read-only

**FACT.** No file under `src/` or `tests/` was created, edited or deleted. No writing entry
point was run. No provider or network API was called, no service restarted, no secret read.

The live database `data/signalforge.sqlite` was **never opened for writing by anything in this
diagnostic**. A consistent point-in-time copy was taken with
`sqlite3 "file:…signalforge.sqlite?mode=ro" ".backup $TMPDIR/scratch-v3d4.sqlite"` and every
in-process run pointed `DATABASE_URL` at that scratch copy; the live file was touched only by
`mode=ro` `SELECT`s. The replay itself is a standalone script outside `src/` and persists
nothing.

**Post-state, verified on the live database after every run (FACT):** `strategy_sealed_test`
= **20** rows, `strategy_promotion_evaluation` = **42**, `strategy_version` = **6**,
`data_snapshot` = **10**, `paper_trade` = **0** — identical to the pre-state recorded in the
design's §0. The two PAPER_APPROVED approvals are undisturbed and their spec hashes are
byte-identical to the hashes stored on their passing evaluations:

| Version | Passing evaluations | `spec_json_hash` |
|---|---|---|
| 2 `trend_continuation.short_swing` | 20, 32 (snapshot 3) | `2ed9743170bd3bbdb450ea03a004a7ffaeb64ccbbe6075db312ffd544072f382` |
| 5 `relative_strength.medium_swing` | 23, 35 (snapshot 3) | `dfe696b662dd02b8fa3a02ce5b987c6eade84a40d88c1a2d8d52e206cb6f6c32` |

The live `candidate` table is the one table that **did** grow during this session: the highest
candidate id seen at the first query was 1,858 and the table stood at 1,861 rows (max id 1,861)
at the last. **That is the running worker's own status-blind scan, not this diagnostic** — it is
exactly the D2/D3 stream described in §5, and it is recorded here because a reader comparing
row counts would otherwise suspect a write. Nothing in this diagnostic opened the live database
for writing at any point.

### 1.1 Windows, universes and cost model — taken from the ledger, not chosen

The pre-sealed span is `[start, sealed.window_start − 1 day]` exactly as `promotion.py:557`
computes it, with `start = 2016-09-10` from evaluation rows 9 / 27 / 33 / 39 and
`sealed.window_start` from the **locked** sealed rows 2 / 7 / 12 / 17.

| Snapshot | Key | Symbols | Source filter | Pre-sealed span | Sealed row |
|---|---|---|---|---|---|
| 1 | `universe_25_baseline_legacy` | 25 | `massive` | 2016-09-10 → **2025-09-06** | 2 |
| 2 | `universe_25_baseline` | 25 | `massive` | 2016-09-10 → **2025-09-07** | 7 |
| 3 | `universe_24_ex_meta` | 24 | `massive` | 2016-09-10 → **2025-09-07** | 12 |
| 4 | `universe_25_meta_continuity_corrected` | 25 | `massive` + `continuity_bridge:1` | 2016-09-10 → **2025-09-07** | 17 |

Proxy `SPY`; `allow_short=False` (the promotion path's default, so every trade is LONG);
`min_bars=60`, `warmup=30`; **`CostModel()` unchanged** — 0 commission, 3.0 bps slippage,
half-spread on, `spread_bps=5.0` ⇒ **11.0 bps of notional per round trip** (`engine.py:94,144`).
**The cost model is not altered anywhere in this diagnostic (R4).**

**Snapshots 1 and 2 return identical trade sets.** FACT, and expected: the symbol lists are
identical and the one extra calendar day on snapshot 2 produces no additional entry. Every
figure below is therefore reported for all four snapshots but snapshots 1 and 2 contribute
**one** observation, not two — the §4.1 clause-3 caveat applies to D4 as well.

### 1.2 Fidelity check — the replay is the shipped engine

The replay is a line-for-line clone of `backtest/engine.py`'s loop with one difference: the
exit resolver takes an optional trail. **With `trail=None` it was asserted against
`run_backtest` on every symbol of every snapshot: 4,365 trades, zero mismatches** in trade
count, entry date, exit date, exit reason, `pnl_r`, `mfe_r` and `mae_r` (tolerance 1e-12).

The baseline profile reproduces §3.1 of the design to the digit:

| Snapshot | n (all pre-sealed) | ALL expectancy ± SE | n OOS | **OOS expectancy ± SE** | OOS sd | n IS | IS expectancy ± SE |
|---|---|---|---|---|---|---|---|
| 1 | 1,091 | +0.1738 ± 0.0480 | 326 | **+0.2936 ± 0.0951** | 1.7179 | 765 | +0.1228 ± 0.0551 |
| 2 | 1,091 | +0.1738 ± 0.0480 | 326 | **+0.2936 ± 0.0951** | 1.7179 | 765 | +0.1228 ± 0.0551 |
| **3 (lead)** | **1,071** | **+0.1667 ± 0.0484** | **319** | **+0.3064 ± 0.0966** | **1.7259** | 752 | +0.1075 ± 0.0553 |
| 4 | 1,112 | +0.1704 ± 0.0478 | 336 | **+0.3169 ± 0.0939** | 1.7219 | 776 | +0.1071 ± 0.0551 |

---

## 2. The rule, the cells, and the one interpretation decision

**Rule family, as pre-registered.** Arm when open profit reaches `aR` on a **closed** bar,
effective from the **next** bar; thereafter the effective stop is
`max(entry_fill + bR, peak_favourable_price − g·R)`, ratcheting upward only. `R` is the
engine's `risk_per_share` = `abs(entry_fill − sig.stop_price)` (`engine.py:111`). The target
(`3.0 × ATR`) and the 40-session time stop are **unchanged**; only the stop moves. Because
`b = 0.5 > 0`, an armed stop is always above the entry fill and therefore always above the
original stop — the trail can only ever exit a trade *earlier*, never later.

**Cells (the entire search, no seventh tried):** `a ∈ {1.0, 1.5}` × `b = 0.5` ×
`g ∈ {0.5, 1.0, 1.5}` = **6 cells**.

**Gap and ordering fidelity.** Within a bar the engine's order is stop → target → time stop,
and a stop is filled at `min(open, stop)` when the bar gaps through it. The trail uses the
same order and the same gap rule, and because arming can never take effect on the entry bar
itself, the trail stop is always evaluated at `u > entry_idx` — so a gap below the trail fills
at the open, not at the trail price. No look-ahead: the peak that sets bar *u*'s stop is the
running extreme over **closed** bars strictly before *u*.

> **Disclosed interpretation decision (one, made before any cell was priced).** "Open profit
> reaches `aR` on a closed bar" admits two readings: the bar's *close* crosses `entry + aR`, or
> the position has *touched* `entry + aR` at any point up to that close (i.e. MFE ≥ a). **The
> touch reading was taken**, because §12.2's own companion statistic defines the arming bar as
> *"the first bar on which MFE ≥ a"* — the two clauses must refer to the same bar or the
> statistic measures nothing. This is also the **more aggressive** reading: it arms earlier and
> more often, so it gives the trailing family its best case. **The close-based variant was not
> run**, and running it later would be a seventh through twelfth cell and a second search
> family; it is foreclosed by the same pre-registration that fixed the six.

---

## 3. Results

### 3.1 Form (i) — trade-set-fixed, paired (the inference instrument)

Baseline entries are held fixed; only the exit is re-resolved. Δ = trail − baseline, per trade.
**Paired SE** = sd(Δ)/√n. "chg" = trades whose R outcome actually moved.

**OOS cut (the deciding cut).**

| Cell (a, b, g) | Snap 1 (n=326) | Snap 2 (n=326) | **Snap 3 (n=319)** | Snap 4 (n=336) |
|---|---|---|---|---|
| 1.0, 0.5, **0.5** | −0.1884 ± 0.0611 (**−3.09**) | −0.1884 ± 0.0611 (−3.09) | **−0.1988 ± 0.0620 (−3.21)** | −0.2068 ± 0.0610 (−3.39) |
| 1.0, 0.5, **1.0** | −0.1908 ± 0.0628 (−3.04) | −0.1908 ± 0.0628 (−3.04) | **−0.2006 ± 0.0638 (−3.14)** | −0.2046 ± 0.0627 (−3.26) |
| 1.0, 0.5, **1.5** | −0.2030 ± 0.0626 (−3.24) | −0.2030 ± 0.0626 (−3.24) | **−0.2130 ± 0.0636 (−3.35)** | −0.2163 ± 0.0625 (−3.46) |
| 1.5, 0.5, **0.5** | −0.0828 ± 0.0513 (−1.62) | −0.0828 ± 0.0513 (−1.62) | **−0.0926 ± 0.0517 (−1.79)** | −0.0829 ± 0.0502 (−1.65) |
| 1.5, 0.5, **1.0** | −0.0863 ± 0.0503 (−1.71) | −0.0863 ± 0.0503 (−1.71) | **−0.0946 ± 0.0510 (−1.86)** | −0.0890 ± 0.0495 (−1.80) |
| 1.5, 0.5, **1.5** | −0.0949 ± 0.0497 (−1.91) | −0.0949 ± 0.0497 (−1.91) | **−0.1024 ± 0.0505 (−2.03)** | −0.0876 ± 0.0485 (−1.81) |

Trades actually moved, snapshot 3 OOS: 101 / 88 / 86 (a = 1.0) and 51 / 40 / 36 (a = 1.5) of 319.

**All-pre-sealed cut**, snapshot 3 (n = 1,071): −0.0915 ± 0.0298 (−3.07) · −0.0813 ± 0.0289
(−2.81) · −0.0750 ± 0.0281 (−2.67) · −0.0411 ± 0.0240 (−1.71) · −0.0334 ± 0.0226 (−1.48) ·
−0.0271 ± 0.0210 (−1.29), in the cell order of the table above. The other three snapshots agree
to ±0.008R throughout; the full grid is in the JSON.

**In-sample cut**, snapshot 3 (n = 752): −0.0460 ± 0.0333 · −0.0306 ± 0.0308 · −0.0165 ± 0.0294 ·
−0.0193 ± 0.0263 · −0.0074 ± 0.0238 · **+0.0048 ± 0.0208**. The last of these is the single
positive point estimate in the study (0.23 SE — see §0).

### 3.2 Form (ii) — trade set free (the reality check)

The full engine loop is re-run with the trail active, so an earlier exit frees later bars and
new entries appear. Snapshot 3, OOS cut; baseline +0.3064R on n = 319.

| Cell | n (free) | Free OOS expectancy ± SE | Difference vs baseline | Unpaired SE | z |
|---|---|---|---|---|---|
| 1.0, 0.5, 0.5 | 342 | +0.1199 ± 0.0641 | **−0.1864** | 0.1160 | −1.61 |
| 1.0, 0.5, 1.0 | 340 | +0.1142 ± 0.0658 | −0.1922 | 0.1169 | −1.64 |
| 1.0, 0.5, 1.5 | 338 | +0.0927 ± 0.0649 | −0.2137 | 0.1164 | −1.84 |
| 1.5, 0.5, 0.5 | 333 | +0.2316 ± 0.0764 | −0.0748 | 0.1232 | −0.61 |
| 1.5, 0.5, 1.0 | 331 | +0.2101 ± 0.0776 | −0.0963 | 0.1239 | −0.78 |
| 1.5, 0.5, 1.5 | 328 | +0.1951 ± 0.0778 | −0.1112 | 0.1241 | −0.90 |

The extra trades are real — the trail exits earlier, so the "one open position per symbol"
constraint releases sooner — and they are **not** free money: the free re-run's expectancy is
below the baseline's in every cell on every snapshot and cut, and on the all-pre-sealed cut it
falls from +0.1667R to between +0.0785R and +0.1366R.

### 3.3 Month-block resampling — snapshot 3, paired OOS Δ

Non-overlapping calendar-month cluster bootstrap, pooled-mean ratio estimator, 2,000 resamples,
seed 20240101, percentile 95% — **identical construction to `clustered_bootstrap_all.md` §2.3(b)**.
G = 28 month blocks. Stability is the mean/min/max over 25 consecutive seeds (20240101…20240125),
the same practice that diagnostic used.

| Cell | mean Δ | SE(block), 25-seed mean [min…max] | **z** (25-seed mean) | most favourable z over 25 seeds | 95% CI |
|---|---|---|---|---|---|
| 1.0, 0.5, 0.5 | −0.1988 | 0.0732 [0.0707…0.0754] | **−2.72** | −2.81 | [−0.3422, −0.0567] |
| 1.0, 0.5, 1.0 | −0.2006 | 0.0765 [0.0739…0.0788] | −2.62 | −2.71 | [−0.3567, −0.0537] |
| 1.0, 0.5, 1.5 | −0.2130 | 0.0775 [0.0752…0.0800] | −2.75 | −2.83 | [−0.3701, −0.0644] |
| 1.5, 0.5, 0.5 | −0.0926 | 0.0628 [0.0610…0.0644] | **−1.47** | −1.52 | [−0.2191, +0.0214] |
| 1.5, 0.5, 1.0 | −0.0946 | 0.0639 [0.0623…0.0658] | −1.48 | −1.52 | [−0.2300, +0.0168] |
| 1.5, 0.5, 1.5 | −0.1024 | 0.0647 [0.0629…0.0664] | −1.58 | −1.63 | [−0.2429, +0.0090] |

No seed produces a positive mean, a positive z, or a CI that excludes harm in the favourable
direction. Reported as a **disclosure applied to the challenger exactly as §3.4 of the design
applies it to the incumbent**, not as a gate.

### 3.4 Walk-forward folds — paired Δ

Folds are the **gate-1 construction** (`promotion.py:613-617`): four contiguous calendar
quarters of the pre-sealed span, every pre-sealed trade assigned by entry date. Snapshot 3:

| Cell | Fold 1 (n=310) | Fold 2 (n=323) | Fold 3 (n=179) | Fold 4 (n=259) | folds positive |
|---|---|---|---|---|---|
| 1.0, 0.5, 0.5 | −0.0640 ± 0.0513 | −0.0482 ± 0.0523 | −0.0671 ± 0.0600 | −0.1955 ± 0.0739 | **0 / 4** |
| 1.0, 0.5, 1.0 | −0.0579 ± 0.0491 | −0.0175 ± 0.0462 | −0.0582 ± 0.0583 | −0.2047 ± 0.0763 | **0 / 4** |
| 1.0, 0.5, 1.5 | −0.0476 ± 0.0487 | +0.0180 ± 0.0414 | −0.0741 ± 0.0580 | −0.2245 ± 0.0761 | **1 / 4** |
| 1.5, 0.5, 0.5 | −0.0077 ± 0.0428 | −0.0629 ± 0.0398 | −0.0109 ± 0.0449 | −0.0749 ± 0.0620 | **0 / 4** |
| 1.5, 0.5, 1.0 | −0.0028 ± 0.0393 | −0.0470 ± 0.0357 | +0.0143 ± 0.0422 | −0.0860 ± 0.0609 | **1 / 4** |
| 1.5, 0.5, 1.5 | −0.0074 ± 0.0372 | −0.0017 ± 0.0263 | +0.0037 ± 0.0417 | −0.1037 ± 0.0605 | **1 / 4** |

Identical counts on all four snapshots. A secondary, OOS-only quartile split (reported in the
JSON) gives at most **1 / 4** positive for every cell on every snapshot, with fold 2 the
consistently worst (−0.41R to −0.46R at a = 1.0). **No cell reaches the required 3 / 4 under
either fold definition.**

### 3.5 Exit-reason mix — the mechanism, snapshot 3, all pre-sealed, form (i)

| Exit | baseline | a=1.0 g=0.5 | a=1.0 g=1.0 | a=1.0 g=1.5 | a=1.5 g=0.5 | a=1.5 g=1.0 | a=1.5 g=1.5 |
|---|---|---|---|---|---|---|---|
| `stop` (original) | 612 | 493 | 493 | 493 | 563 | 563 | 563 |
| `trail` | 0 | **337** | 286 | 271 | 156 | 118 | 98 |
| `target` | **445** | **236** | 287 | 301 | 341 | 379 | 398 |
| `time_stop` | 8 | 2 | 2 | 3 | 7 | 7 | 8 |
| `eod` | 6 | 3 | 3 | 3 | 4 | 4 | 4 |

At the most aggressive cell the trail destroys **209 of 445 target exits (47%)** while
converting only 119 original stops into earlier, shallower trail exits. That trade is the whole
result: the winners it truncates are worth more than the losers it shortens.

### 3.6 The companion statistic §12.2 asked for — never previously measured

*Among **target** exits, the distribution of the minimum excursion from the **first bar on
which MFE ≥ a**, per cell, with a paired SE.* The statistic depends on `a` only (the arming
bar), so it is reported per `a` and is constant across `g` by construction. Snapshot 3;
445 target exits all-pre-sealed, 137 OOS.

| a | cut | armed n | **min excursion after arming, mean ± SE** | median | p10 | share falling below the b = 0.5R lock |
|---|---|---|---|---|---|---|
| 1.0 | ALL | 410 | **+0.3497 ± 0.0261** | +0.446 | −0.394 | **54.6%** |
| 1.0 | OOS | 127 | **+0.2244 ± 0.0473** | +0.297 | −0.499 | **61.4%** |
| 1.5 | ALL | 324 | **+0.8796 ± 0.0330** | +0.980 | +0.048 | 20.1% |
| 1.5 | OOS | 102 | **+0.7668 ± 0.0653** | +0.913 | −0.089 | 29.4% |

And the quantity that decides whether a *ratcheting* trail survives — the maximum post-arm
giveback from the running peak, which is exactly what `g` has to absorb:

| a | cut | giveback mean ± SE | median | **share > 0.5R** | **share > 1.0R** | **share > 1.5R** |
|---|---|---|---|---|---|---|
| 1.0 | ALL | 1.1691 ± 0.0421 | 0.928 | 90.0% | 46.3% | 25.1% |
| 1.0 | **OOS** | **1.3910 ± 0.1081** | 1.196 | **92.1%** | **56.7%** | **33.9%** |
| 1.5 | ALL | 1.1236 ± 0.0514 | 0.890 | 83.6% | 41.0% | 22.2% |
| 1.5 | **OOS** | **1.3882 ± 0.1320** | 1.039 | **91.2%** | **52.9%** | **29.4%** |

Snapshots 1, 2 and 4 agree to within ±0.02R and ±1.5 percentage points throughout.

**This is the mechanism, stated plainly.** A trade that eventually reaches its 3×ATR target
does not travel there monotonically: on the OOS cut **92%** of the trades that touch 1.0R give
back more than 0.5R from their running peak before the target prints, **57%** give back more
than a full R, and **61%** retrace below the `entry + 0.5R` profit lock itself. A ratcheting
trail is not harvesting a giveback these trades do not have — it is standing exactly where the
winners breathe. That is why every cell is negative, and why `a` (which decides *how many*
trades the trail touches) dominates `g`: raising the arm from 1.0R to 1.5R halves the number of
trades whose outcome moves (101 → 51 of 319, snapshot 3 OOS) and halves the harm with it,
from ≈ −0.20R to ≈ −0.09R.

**The harm is not monotone in `g`, and the direction reverses between cuts — stated rather
than smoothed over.** On snapshot 3, tightening the give makes things *worse* on the
all-pre-sealed cut (a = 1.0: −0.0750 → −0.0813 → −0.0915 as `g` falls 1.5 → 1.0 → 0.5) and
mildly *better* on the OOS cut (−0.2130 → −0.2006 → −0.1988), with the same reversal at
a = 1.5 and on all four snapshots. A tighter give touches more trades (101 / 88 / 86 of 319 at
a = 1.0) but removes each one earlier and therefore cheaper. **Every one of these differences
is well under 2 SE of the others and none of them is treated as a finding**; they are recorded
only so that no future reader can claim D4 established a preferred `g`. It did not. It
established that all six cells lose.

### 3.7 Bound versus realised — the reason D4 existed

The judge recomputation that kept this lane open put the ratcheting **upper bound** at
**≈ +0.56R** at `g = 0.5` (snapshot 3 OOS, excluding the entry-bar bucket and MFE ≥ 5R) against
a base of +0.30R. The realised path-level replay at the matching cell is **−0.1988R ± 0.0620**.

To compare like with like, one **disclosed** additional read (not a new cell, not part of the
five-clause bar, and it can only strengthen or weaken the closure — it does neither
direction's favour): the same paired Δ under the bound's own exclusions.

| Cell | OOS, all (n=319) | OOS ex entry-bar (n=283) | **OOS ex entry-bar & MFE ≥ 5R (n=277)** |
|---|---|---|---|
| 1.0, 0.5, 0.5 | −0.1988 ± 0.0620 (−3.21) | −0.2241 ± 0.0697 (−3.21) | **−0.1418 ± 0.0586 (−2.42)** |
| 1.0, 0.5, 1.0 | −0.2006 ± 0.0638 (−3.14) | −0.2261 ± 0.0718 (−3.15) | −0.1410 ± 0.0606 (−2.33) |
| 1.0, 0.5, 1.5 | −0.2130 ± 0.0636 (−3.35) | −0.2401 ± 0.0716 (−3.36) | −0.1521 ± 0.0596 (−2.55) |
| 1.5, 0.5, 0.5 | −0.0926 ± 0.0517 (−1.79) | −0.1044 ± 0.0583 (−1.79) | −0.0196 ± 0.0428 (−0.46) |
| 1.5, 0.5, 1.0 | −0.0946 ± 0.0510 (−1.86) | −0.1067 ± 0.0574 (−1.86) | −0.0189 ± 0.0407 (−0.47) |
| 1.5, 0.5, 1.5 | −0.1024 ± 0.0505 (−2.03) | −0.1154 ± 0.0569 (−2.03) | −0.0246 ± 0.0388 (−0.64) |

**FACT: on the bound's own trade set the bound overstates the realised effect by ≈ 0.70R and
gets the sign wrong.** Dropping the MFE ≥ 5R tail shrinks the harm toward zero at `a = 1.5` —
because that tail is where the trail's damage concentrates — but it never turns the sign
positive in any cell.

This is §0's SE convention vindicated in the most concrete way available: *a bound is not an
estimate*, and the design was right to refuse to divide it by a sampling SE. It is also why
this diagnostic was worth running rather than asserting: the closure claim the original
proposal made was unsupported, and the correct answer could only be obtained by replaying the
paths.

---

## 4. The five-clause bar, clause by clause

§12.2: *"The bar to re-open the exits lane — **all five** must hold."*

| # | Clause | Holds? | Evidence |
|---|---|---|---|
| **1** | paired OOS difference **≥ +2 SE on all four snapshots** | **NO** | 0 of 6 cells is positive on any snapshot. Range: −0.0828R (−1.62 SE, snap 1, a=1.5 g=0.5) to −0.2163R (−3.46 SE, snap 4, a=1.0 g=1.5). |
| **2** | **≥ +2 SE under calendar-month block resampling** on snapshot 3 | **NO** | All six negative; least unfavourable z = **−1.47** (25-seed mean; most favourable single seed −1.52). No seed, no cell, gives a positive z. |
| **3** | positive in **≥ 3 of the 4** walk-forward folds | **NO** | Best any cell achieves is **1 / 4** (gate-1 folds and OOS-only folds alike), on all four snapshots. |
| **4** | trade-set-free re-run reproduces the **sign** with a point estimate **within 1 SE** of the paired estimate | **YES** | Sign reproduced in 6/6 cells × 4/4 snapshots; largest gap between free and paired estimates is **0.0190R** (a=1.5 g=0.5, snapshot 4) against paired SEs of 0.049–0.064 — well inside 1 SE. **The sign it reproduces is negative.** |
| **5** | the best cell is **not adjacent to a sign change** in the 6-cell grid | **YES (vacuously)** | The best cell is (a=1.5, b=0.5, g=0.5) on every snapshot (−0.0828 / −0.0828 / −0.0926 / −0.0829). **No sign change exists anywhere in the grid** — all six cells are negative on all four snapshots — so no cell can be adjacent to one. |

**Score: 2 of 5, and the two that hold are the robustness clauses.** Clause 4, designed to catch
a paired re-pricing that a full re-run would not reproduce, instead certifies that the harm is
genuine. Clause 5, designed to catch a knife-edge optimum, instead certifies that the harm is
uniform across the family. **The bar is not cleared. V-A′ is not triggered.**

**Symmetric commitment (§12.2, restated as it applies in this direction too):** the closure is
not being over-claimed either. At `a = 1.5` the harm is **not** established at 2 SE on the OOS
cut on any snapshot (−1.62 to −2.03 SE), and under the bound's own exclusions it is −0.46 to
−0.64 SE. What is established is the **absence of the required positive evidence** — which is
what the pre-registered bar asks, since the bar is one the challenger must clear, not one the
incumbent must clear. *"A favourable point estimate that fails any of the five clauses is not a
finding"*; equally, an unfavourable point estimate under 2 SE is not proof of harm, and is not
reported as one here.

### 4.1 Consequences that follow automatically from the pre-registration

- **§12.2:** *"If it does not clear: the exits-and-risk lane is closed permanently for this
  family."* → **The lane is closed.** The §3.5 table's one OPEN row (ratcheting ATR trail,
  `(arm, lock, give)`) becomes **closed — realised effect negative on all four snapshots, both
  forms, both cuts**. Every lever in map §2.1 for `trend_continuation` is now closed.
- **§12.3 F1′** (D4's five-clause bar) → **does not fire.**
- **§12.3 F6** (*"any perturbation whose realised, measured effect lies above the incumbent by
  ≥ 2 SE paired on OOS on all four snapshots — this is the falsifier of H13 itself"*) → **does
  not fire.** **H13 is now supported on all six axes**, the sixth by realised measurement rather
  than by assertion.
- **§4.3 Route B** (*"Today the only admissible source of such a finding is D4"*) → **Route B
  has no admissible source.** Route A (the unchanged v0.1.0 on an independently-motivated new
  snapshot) is the only remaining route for this version, and it remains subject to §12.5's
  look accounting and the binding gate-9 pass/fail bit.
- **§9.1 budget:** variants proposed 0, contingent variant **not** triggered, hard cap
  untouched. **§12.5:** k = 5, **0 looks added by this diagnostic.**
- **§9.2 search count:** this document spends exactly the **6 pre-registered cells**. The
  additional reads it contains — the two exclusion-matched columns of §3.7, the 25-seed
  stability of §3.3, and the OOS-only fold split of §3.4 — are **re-readings of the same six
  cells**, not new cells, and are disclosed here so the next reader can count them as such.

---

## 5. D2 / D3 — the shadow-confirmation stream, state as of 2026-09-10

### 5.1 The structural facts, re-verified read-only

| Claim (§11.2) | Verified |
|---|---|
| v3 is `EXPERIMENTAL`, so no `PaperTrade` evidence can ever accrue | **FACT.** `strategy_version.id=3` status `EXPERIMENTAL`; `assert_auto_simulate_allowed` raises `AutoSimulateForbidden("strategy version is not PAPER_APPROVED")` at `paper/ledger.py:501-502`. |
| No code path re-promotes from live evidence | **FACT.** `health_monitor._decide` (`health_monitor.py:100-113`) returns only unchanged, `downgrade` or `disable` — one-way down. |
| The scan selects strategies by **horizon, not status** | **FACT.** `scan.py:110-111`, `_strategies_for(horizon)` filters on `spec().horizon` alone. |
| Both `PASSED` and `NO_TRADE` drafts are persisted as `Candidate` rows | **FACT.** `scan.py:298`, `result.candidates.append(draft)  # both PASSED and NO_TRADE drafts are recorded`. The design's citation is exact. |
| MEDIUM_SWING is scanned only because v5 is `PAPER_APPROVED` on it | **FACT.** `approved_scope_scan.approved_horizons` (`:76-77`) returns *"distinct horizons of every PAPER_APPROVED strategy, INTRADAY excluded"*, and `run_approved_scope_scan` (`:180`) iterates exactly those. v5 is the only PAPER_APPROVED MEDIUM_SWING strategy (v2 is SHORT_SWING). **The disclosed dependency is real: if v5 were downgraded, the v3 shadow stream stops.** |
| v3 holds 199 candidate rows, of which 3 are on snapshot 3 / source `massive` | **FACT, exactly.** 199 total; the 3 are ids 1821, 1831, 1858. |

### 5.2 The pre-registration-contaminated rows, recorded so they can be excluded

The §11.2 population begins **2026-09-11**. Today's rows are excluded and are listed here so the
exclusion is auditable rather than assertable:

| Candidate id | scan_run | date | symbol | gate status | direction | invalidation | target | time stop |
|---|---|---|---|---|---|---|---|---|
| 1821 | 20 | 2026-09-09 | XLK | `NO_TRADE` | LONG | 183.2377 | 197.1346 | 40 |
| 1831 | 26 | 2026-09-09 | XLK | `NO_TRADE` | LONG | 183.2377 | 197.1346 | 40 |
| 1858 | 38 | 2026-09-10 | XLE | `NO_TRADE` | LONG | 63.1231 | 68.5438 | 40 |

**The de-duplication rule earns its place immediately.** Rows 1821 and 1831 are the *same*
XLK signal, persisted twice because scan runs 20 and 26 both executed on 2026-09-09. Under
§11.2's `(symbol, date)` rule the three raw rows are **2 de-duplicated signals over 2 scan
days**. **Citation correction:** the design cites scan runs **32 and 38** (both 2026-09-10) as
the same-day duplication evidence; on snapshot 3 / `massive`, run 32 produced no v3 row at all,
so the realised duplicate pair is **20 and 26 on 2026-09-09**. Runs 32 and 38 are indeed both
dated 2026-09-10 and the design's *point* is correct — scans do run more than once a calendar
day — but the v3 rows it implies are not there.

### 5.3 What is due now: nothing

**FACT.** The pre-registered population (`strategy_version_id = 3`, scan run with
`dataset_snapshot_id = 3` and `source = 'massive'`, from 2026-09-11 forward) currently contains
**n = 0** de-duplicated signals. The read-outs are **n-triggered only** — read-out 1 at n ≥ 95,
read-out 2 at n ≥ 220 — and §11.2 forbids any interim read being *"produced, circulated, or
cited"*. **No D3 read-out is produced by this document, and none is due.**

**The arrival-rate hypothesis is already under strain, and is recorded, not acted on.**
HYPOTHESIS: §11.2 transfers ≈119 de-duplicated signals/year from the backtest trade rate.
FACT: the observed stream has produced **2 de-duplicated signals across 2 scan days** on
snapshot 3 / `massive` (and both were `NO_TRADE` desk drafts, which the pre-registration
correctly includes). Two days is far too short to estimate a rate and **no rate is estimated
here**; §11.2's own instruction stands — *"calendar triggers are not used until an arrival rate
has been measured on the stream itself"*. The observation is logged only so that the first
read-out, whenever it arrives, can report how long n ≥ 95 actually took against the 119/year
hypothesis.

**Nothing in §5 is evidence about v3's expectancy, in either direction, and under R8 nothing
in this stream may ever motivate a rule, parameter, filter, entry, exit or universe change.**

---

## 6. What this document does and does not claim

**Does claim (FACT unless marked).**
1. The pre-sealed baseline reproduces the design's §3.1 profile exactly on all four snapshots,
   from a replay asserted bar-for-bar identical to the shipped engine on 4,365 trades.
2. All six pre-registered ratcheting-trail cells reduce expectancy on every snapshot, in both
   forms of the replay, on both cuts — with the single 0.23 SE in-sample exception disclosed
   in §0.
3. The five-clause bar is not cleared: clauses 1, 2 and 3 fail; clauses 4 and 5 hold and in
   holding confirm the harm rather than an edge.
4. The mechanism is measured, not inferred: 92.1% of OOS target-reaching trades give back more
   than 0.5R from their running peak after first touching 1.0R, and 61.4% retrace below the
   0.5R profit lock.
5. The judge's +0.56R ratcheting upper bound is unreachable; the realised effect at the matching
   cell is −0.1988R ± 0.0620, and stays negative under the bound's own exclusions.
6. The D2/D3 structural facts hold as pre-registered, with two citation corrections; the
   pre-registered population is empty and no read-out is due.

**Does not claim.**
1. **Not** that a trailing stop is a bad idea in general, or for any other strategy family.
   This is one rule family, one strategy, one universe, one cost model.
2. **Not** that the harm at `a = 1.5` is established at 2 SE — it is not (§4, symmetric
   commitment).
3. **Not** that v3 is unprofitable, that it is worse than v2, or that it should be deleted.
4. **Not** any proposal to change `src/`, `tests/`, any threshold, any gate, or the cost model.
5. **Not** a sealed look. k remains 5; the next sealed draw is look 6 whenever it occurs.

**Reproduction.** Every figure in this document comes from the two read-only scripts described
in §1–§2 run against a `.backup` copy of the live database, and every one of them — including
the per-fold, per-snapshot, in-sample and companion distributions abbreviated in the tables
above — is serialised in `v3_d4_closure.json` alongside the clause-by-clause evaluation.
