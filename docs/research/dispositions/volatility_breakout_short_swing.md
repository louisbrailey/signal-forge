# Disposition — `volatility_breakout.short_swing` v0.2.0 (from version 6 / v0.1.0)

**Verdict: STOP at Stage A. The mechanism is NOT established.** v0.2.0 is implemented,
tested and left **unsealed and `EXPERIMENTAL`**. v0.1.0 (version 6) is untouched.
**Sealed looks consumed: 0. k stays 5.** No Stage B, no `evaluate_promotion`, no
`StrategySealedTest`.

Source: `docs/research/designs/volatility_breakout_short_swing.md`, read in full; this
record is its §11 null option, which the design pre-registered as the **expected**
outcome and required to be reachable at zero sealed cost. Evidence:
`docs/research/designs/scripts/volatility_breakout_short_swing/stage_a.{json,md}`,
produced by `scripts/stage_a_v6.py` on a `mode=ro` backup copy of the live database.
Every number carries its n and SE. **A difference under 2 SE is not evidence**, and is
labelled so wherever it appears.

---

## 1. The verdict, precisely

The pre-registered kill test **K3b fired**. The mechanism moved the point estimate in
the predicted direction and the improvement is **not measurable at the achievable
power**.

| test | bar | measured | outcome |
|---|---|---|---|
| **K3a** — sign | `E02 > E01` | +0.17618R vs +0.10651R | **PASSED** |
| **K3b** — magnitude | ≥ 2.0 **clustered** SE (= +0.4218R) | **+0.06967R = 0.33 SE** | **FIRED** |
| **K5** — grid no-op | all 4 axes move OOS count or expectancy | all 4 move; `inert_axes = []` | **PASSED** |

On the expanded snapshot 11 (`research_150_massive_10y_presealed_sel`, 150 symbols),
pre-sealed span 2016-09-10 → 2025-09-07:

| | OOS expectancy | all pre-sealed |
|---|---|---|
| **v0.1.0** (E01) | **+0.1065R ± 0.0912** (n = 212, sd 1.3286) | +0.1642R ± 0.0485 (n = 785) |
| **v0.2.0** (E02) | **+0.1762R ± 0.0908** (n = 184, sd 1.2322) | +0.2010R ± 0.0561 (n = 712) |

E02 − E01 = **+0.06967R**; iid SE of the difference 0.1288 → **0.54 SE**; entry-month
clustered SE 0.2109 (the pre-registered iid × **1.638**, fixed in the design before any
expanded-snapshot number existed) → **0.33 SE**. The clustered form binds.

**This is not "the mechanism failed".** The sign is right and it is right on every cut
taken. It is 0.33 SE, against a 2.0 SE bar — six times short. Under §12.1's stopping
rule that ends the lane: no re-parameterisation, no second variant, no second universe.

## 2. The baseline is genuinely v0.1.0 (checked before any result was read)

**FACT.** The degenerate cell `squeeze_lag=0, release_min=0.0` reproduces v0.1.0's
stored snapshot-3 evaluation **exactly** — **211 pre-sealed / 51 OOS at +0.06135R**,
matching evaluation 36 and both judges' independent reproductions. E01 was measured
through that cell, so the comparison is against the real predecessor. This is what the
`release_min > 0.0` gate of design §2.3 buys (judge defect A11); without it the
degenerate cell would require `t ≥ 51` where v0.1.0 requires `t ≥ 50`, making it a
strict subset rather than an identity, and E01 would have been silently biased.

## 3. Gate-by-gate forecast on the expanded snapshot (read-only, gates 1–8)

Computed for v0.2.0 with the shipped thresholds. **Gate 9 was not computed — it is
precisely the sealed look Stage A exists to avoid.**

| # | Gate | Forecast | Measured |
|---|---|---|---|
| 1 | `rolling_walkforward` | **PASS** | 4 of 4 folds clear the 15-trade floor and are positive (need 2): 172@+0.333R, 285@+0.155R, 103@+0.119R, 152@+0.194R |
| 2 | `min_oos_trades` | **PASS** | 184 vs threshold 30 |
| 3 | `net_expectancy` | **PASS** | +0.1762R > +0.0000R |
| **4** | `bootstrap_ci` | **FAIL** | iid CI low **+0.0018R** vs bar > +0.0200R; month-clustered low **−0.0449R** |
| 5 | `parameter_sensitivity` | **PASS** | **81/81 evaluable**, 80/81 = **98.8%** positive (need 60%), **8/8 = 100%** of one-step neighbours positive (need 75%); `fragile = False` |
| **6** | `regime_coverage` | **FAIL** | bull **567**, bear **4**, range **63**; 2 of 3 regimes covered, bear floor is 10. Unbucketed **78**, all of it proxy warm-up (no-proxy-bar 0, unlabelled 0); census closes over 712 trades |
| 7 | `benchmark_comparison` | **PASS** | Sharpe **+1.202** vs SPY **+0.719** — and see §5, it is a turnover artefact |
| 8 | `data_quality_and_leakage` | not run | `validate_daily(persist=True)` writes rows, so Stage A cannot run it. The four v0.2.0 entry features are covered by `LEAKAGE_FEATURE_CHECKS` and unit-tested |
| 9 | `sealed_final_test` | **NOT COMPUTED** | the look that was not spent |

**Two gates fail independently of K3b.** Even had the magnitude test passed, gate 4
misses by 0.018R and gate 6's bear bucket is 4 against a floor of 10. Stage B would
have bought a failure for a sealed look.

## 4. Where the design's own forecast was wrong, recorded against it

The design pre-registered its predictions so they could be scored. Three missed:

| Quantity | Design forecast (§5) | Measured | Verdict |
|---|---|---|---|
| OOS n for v0.2.0 | ≈ **251** [228, 280] | **184** | overshot by 27%; the 7.85× multiplier was optimistic |
| Gate 6 bear bucket | λ ≈ **14.7**, P(≥10) = **0.920** | **4** | badly overshot. §11 item 4's hard calendar ceiling — 19 gate-open bear proxy sessions in nine years — is what actually binds |
| Gate 4 | "genuinely uncertain, P ≈ 0.5–0.65" | **FAIL** by 0.018R | within the stated uncertainty; correctly *not* claimed as confident either way |

Scored correctly: gate 7 was predicted to **PASS as a `√(trades/year)` artefact**, and
it does, to four decimal places (§5 below); gate 5 was predicted to become materially
harder and was cleared anyway; gate 2 was predicted to pass comfortably and does.

## 5. Gate 7 is a turnover gate, demonstrated (design §5.7, approval A3)

**FACT** (`portfolio_metrics.py:109-111`): `sharpe = (mean/sd) × √(trades per year)`.
Reconstructed exactly from this run:

| | per-trade mean/sd | trades/yr | √(trades/yr) | product | reported Sharpe |
|---|---|---|---|---|---|
| v0.1.0 | 0.1210 | 88.4 | 9.400 | **1.1373** | **1.137** |
| v0.2.0 | 0.1343 | 80.1 | 8.952 | **1.2020** | **1.202** |

Per-trade quality improves by 0.0133 (0.121 → 0.134) — **nowhere near the ≥ 2 SE
improvement A3 sets as the bar for calling a gate-7 pass evidence of edge quality**.
Both versions clear SPY's 0.719 chiefly by trading 80–88 times a year. **The gate-7
pass contributes no independent evidence of edge quality.** This holds whether or not
the operator approves A3, because it is a verified property of the code.

## 6. What did improve, stated without inflating it

Reported because suppressing a real directional result would be as dishonest as
overclaiming one. None of it reaches 2 SE; none of it reopens the lane.

- **Fragility to the worst month.** v0.1.0's OOS expectancy **flips sign** when
  2023-12 is dropped (+0.1065R → **−0.0260R**, 29 of 212 trades). v0.2.0 does **not**
  flip: its worst leave-one-month-out is **+0.1246R** (dropping the same month, 39 of
  184 trades), range +0.1246R … +0.2220R over 23 months. On the expanded universe the
  single-month fragility the design flagged for v0.1.0 is materially reduced.
- **Fragility to the worst symbol.** v0.1.0 ranges +0.0749R … +0.1248R over 115
  symbols; v0.2.0 **+0.1493R … +0.2024R** over 111. Neither flips sign; the
  two-JPM-trades fragility of snapshot 3 does not reproduce at 150 symbols.
- **Cost tolerance.** At the mandated 2× spread (26 bps round trip) v0.1.0 falls to
  **+0.0446R** and v0.2.0 holds **+0.1253R**; at 66 bps v0.1.0 is **−0.1006R** while
  v0.2.0 is **+0.0020R**. v0.2.0 is better at every priced point, as the design's
  mechanism argument predicted.
- **Grid robustness.** 81/81 cells evaluable and 98.8% positive is a stronger gate-5
  result than v0.1.0 ever produced on 9 points.

**None of this is a basis for continuing.** The programme's rule is 2 SE, and the
headline comparison is 0.33 SE.

## 7. Composition, and the anti-rationalisation clause (design §4)

| | v0.1.0 OOS | v0.2.0 OOS |
|---|---|---|
| ETFs | **−0.0636R ± 0.2456** (n = 37) | +0.2129R ± 0.2335 (n = 17) |
| single names | +0.1425R ± 0.0977 (n = 175) | +0.1724R ± 0.0974 (n = 167) |

The design's anti-rationalisation clause required that a pass carried by the
single-name sub-sample be called *"a composition effect measured on a
survivorship-biased, non-point-in-time universe"*, not *"v6 works"*. **It does not
arise: nothing passed.** Recorded so the clause is visibly honoured rather than
quietly dropped.

**§7.2 item 3, pre-registered and confirmed:** the expanded run's single-name
expectancy was EXPECTED to come in below snapshot 3's +0.5251R, and it does
(+0.1724R). That is confirmation of the survivorship caveat, not a disappointment.

## 8. Sub-universe cuts (§12.7 item 2)

| universe | n | v0.1.0 OOS | v0.2.0 OOS | difference |
|---|---|---|---|---|
| `single_names_135` (W1-COMP's CS block) | 135 | +0.1425R ± 0.0977 (n = 175) | +0.1724R ± 0.0974 (n = 167) | +0.0300R |
| `new_vs_snapshot3_126` (absent from snapshot 3) | 126 | +0.1208R ± 0.0997 (n = 161) | +0.1466R ± 0.1029 (n = 152) | +0.0258R |

The stricter cut is the only genuinely quasi-out-of-sample universe evidence
available. The difference is **smaller** there than on the full snapshot
(+0.0258R vs +0.0697R) — the opposite of what a real mechanism strengthening on fresh
names would show, and a further reason not to read the headline difference as signal.

## 9. The clustered statistic, and why its SE was fixed in advance

| version | iid 95% CI | half-width | month-clustered 95% CI | half-width | ratio | G |
|---|---|---|---|---|---|---|
| v0.1.0 | [−0.0678, +0.2897] | 0.1788 | [−0.1833, +0.4321] | 0.3077 | **1.721×** | 23 |
| v0.2.0 | [+0.0018, +0.3545] | 0.1763 | [−0.0449, +0.3165] | 0.1807 | **1.025×** | 23 |

The OOS pool spans only **23 distinct entry months**, and
`clustered_bootstrap_all.md` §4.2 records that a cluster bootstrap on fewer than ~30
clusters is unreliable and erratic in both directions. The two measured ratios
(1.721× and 1.025×) **straddle** the pre-registered 1.638 rather than confirming it.
**K3b binds on the fixed factor precisely so that the SE could not be chosen once the
difference was known** — and this run is the case that shows why that mattered: had
the SE been measured, v0.2.0's own 1.025× would have made the test ~1.6× easier.

## 10. Sealed-look accounting (design §10)

**Baseline k = 5. Consumed by Stage A: 0. Planned: 0. k stays 5.** Stage B would have
been **look 6** under MAP §4.2 item 10 (**look 5** under MAP §0.1 — the two conventions
differ by one; flagged, not silently resolved; operator question Q2).

The §10.1 four-draw ledger for v0.1.0, reproduced:

| Ver | Strategy | snap 1 | snap 2 | snap 3 | snap 4 |
|---|---|---|---|---|---|
| 2 | `trend_continuation.short_swing` | id 1: +0.3246R / 112 ✅ | id 6: +0.3246R / 112 ✅ | id 11: +0.2982R / 109 ✅ | id 16: +0.3246R / 112 ✅ |
| 3 | `trend_continuation.medium_swing` | id 2: +0.0109R / 98 ✅ | id 7: +0.0109R / 98 ✅ | id 12: −0.0294R / 95 ❌ | id 17: +0.0109R / 98 ✅ |
| 4 | `mean_reversion.short_swing` | id 3: +0.1230R / 91 ✅ | id 8: +0.1230R / 91 ✅ | id 13: +0.1278R / 84 ✅ | id 18: +0.1230R / 91 ✅ |
| 5 | `relative_strength.medium_swing` | id 4: +0.2935R / 16 ✅ | id 9: +0.2935R / 16 ✅ | id 14: +0.2935R / 16 ✅ | id 19: +0.2935R / 16 ✅ |
| **6** | **`volatility_breakout.short_swing`** | **id 5: −0.0979R / 10 ❌** | **id 10: −0.0979R / 10 ❌** | **id 15: −0.0979R / 10 ❌** | **id 20: −0.0979R / 10 ❌** |

All four v6 draws are the **identical** 10 trades at −0.0979R; SE = 0.491R, so it is
**0.20 SE** from zero and carries no information about sign. *(Sealed numbers,
disposition use only, R1/R2 — none of them motivated anything in the design or in this
record.)*

**Ledger correction.** The design records `strategy_sealed_test` as 20 rows. It now
holds **22**: rows 21 and 22 are `strategy_version_id` **3** and **4** on
`dataset_snapshot_id` **11**, written 2026-09-11 06:29 and 06:31 by the separate
v3/v4 evaluation work (commits `21e4702`, `68b533c`) — **not by this lane**. Verified
read-only before and after Stage A: **22 → 22**.

## 11. Variant ledger (R5)

**1 of 1 mechanism variants used; hard cap 2. The second is NOT taken.** The design
permits variant 2 only on a *mechanical counting failure* — gate 2 with n < 30, or
fewer than 3 evaluable gate-5 cells — at the named fallback `release_min = 0.8`.
Neither occurred: gate 2 returned n = 184 and **81 of 81** grid cells were evaluable.
**The kill was a point-estimate outcome, and §12.1 forbids spending the second variant
on one.**

Nothing was re-tuned after seeing a number: `squeeze_lag = 5` and `release_min = 1.0`
shipped as pre-registered, and the grid neighbours (3/10, 0.8/1.2) are the
pre-registered ones.

## 12. Mandatory disclosures

**§0.5 — the broken abstention.** The mechanism proposal deliberately never computed
the proposed rule's P&L so that no parameter could be selected on it. That abstention
was broken during the design phase while settling a judge dispute about per-trade
dispersion; v0.2.0's snapshot-3 figures (pre-sealed +0.2937R ± 0.1523, OOS +0.3168R ±
0.1851) were computed and reported there. **No parameter was changed as a result, and
none was changed here.**

**§7.2 — survivorship, which could not be fixed.** *Discovery is active-tickers-only,
so names delisted or failed between 2016 and 2026 can never enter this universe,
regardless of which liquidity window ranks the survivors. The size of the effect is
unmeasurable with the data held.* Required verbatim in every report on this snapshot.
The related sealed-window **selection** defect (W1-SEL ranking by dollar volume
computed inside the sealed year) was found and fixed before the snapshot was built —
snapshot 11 is selected on a pre-sealed window. Bars remain split-adjusted as of fetch
date, not point-in-time. `source="massive"` was passed explicitly everywhere, so the
dual-source hazard (loading `massive_grouped` duplicates every session *inside* the
sealed window) cannot arise.

**Cost (§8).** Modelled cost at v0.1.0's own OOS entries is **89% of its net edge** on
snapshot 3 — MAP §0.4's 0.042R is an understatement. On this snapshot both versions
lose most of the measured edge at the mandated 2× spread. The project holds **no
spread data at all** (`universe/screen.py:47`, `spread_filter_not_licensed`), so every
spread statement is a modelling assumption, not a measurement.

**Structural finding, which stands regardless of outcome.** The same-bar squeeze/break
conjunction selects break bars **37% smaller** than the typical break bar
(−0.4201 ± 0.0161, **26.1 SE**), identically on all four snapshots. This is a
permanent, reusable result and the honest answer to "was the rule ever given a fair
chance?" — it was.

## 13. Disposition

- **v0.1.0** (version 6): stays **`EXPERIMENTAL`**. Untouched. Its four sealed draws
  stand.
- **v0.2.0**: implemented and committed on branch `v6-squeeze-release`, fully tested,
  **never registered in any database, never sealed**. Stays `EXPERIMENTAL`.
- **No gate, threshold or cost-model constant was changed.** `PromotionThresholds` and
  `CostModel` are byte-identical to HEAD.
- **Recommendation: stop.** One of one mechanism variants did not clear its
  pre-registered bar; gate 4 and gate 6 fail independently on the best universe
  available; and gate 4 is not reachable by universe expansion at any feasible scale
  (at +0.0613R it needs ≈ 2,500–6,900 OOS trades iid, ≈ 6,600–18,500 clustered, against
  `max_universe_size = 150`). A third angle would be variant-hunting.

## 14. What would reopen the lane

All four required together; any one alone is not sufficient.

| # | Condition | Status today |
|---|---|---|
| RO-1 | A mechanism separating pre-sealed OOS expectancy by **≥ 2.0 entry-month-clustered SE** — not 1.0, not iid | **fails at 0.33 SE.** The measured gap would need to roughly sextuple, or n to rise ~36× at this effect size |
| RO-2 | Gate 4's iid CI low **> +0.0200R** on a universe that exists | **fails at +0.0018R.** Needs either +0.018R more point estimate or materially more n |
| RO-3 | Gate 6's **bear** bucket ≥ 10 pre-sealed trades | **fails at 4.** Hard calendar ceiling: 19 gate-open bear proxy sessions in nine years, set by the inherited `not ctx.regime.risk_off` conjunct v6 shares with the approved v2. **Not fixable by adding symbols** — it is a date-count limit, and the honest route is a regime-definition change, which is a different lane and a different design |
| RO-4 | Real **spread data**, so the cost assumption stops being a flat 5 bps guess | **unavailable** — `spread_filter_not_licensed`. Until then the 26 bps row, where most of the edge disappears, cannot be ruled in or out |

**RO-3 is the binding one and it is structural, not statistical.** More symbols do not
buy bear sessions. Anyone reopening this lane should start there, and should expect to
be proposing a change to the shared `risk_off` gate — which would touch the live
`trend_continuation.short_swing` approval and is therefore an operator decision before
it is a research one.

## 15. Operator items raised, none authorised here

1. **Q1 — the 2×/5× spread convention.** MAP §0.4 reads 26/66 bps; W1 §7.1 reads
   16/31 bps. All four are reported in `stage_a.md`; the operator should fix one.
2. **Q2 — the look-index convention.** MAP §0.1 and §4.2 item 10 differ by one. Both
   readings are reported. Nine proposals write ledgers against the same baseline and
   they will not reconcile until this is named.
3. **Q3 / A3 — gate 7.** Its docstring (`config/research.py:111-113`) says OOS; its
   code (`promotion.py:775`) uses all pre-sealed trades. And it rewards turnover (§5).
   Recommendation: fix the docstring, not the code, and record A3's disclosure rule.
4. **§12.4 item 6 deviation, found in passing.** The design expects
   `approved_scopes(v2)` / `approved_scopes(v5)` to return **exactly one** scope each.
   Both now return **three**, all on `dataset_snapshot_id = 3` with identical
   `spec_json_hash` and universe, differing only in `evaluation_id` and `config_hash`
   (two distinct values: `11b54aee…` and `fe365720…`). The spec hashes themselves are
   unmoved — **v2 `2ed97431…f382`, v5 `dfe696b6…6f6c32`, byte-identical before and
   after v0.2.0** — so R7 holds. But R7b's concern is now live rather than
   hypothetical: `paper_probation.py:118` takes `scopes[0]` and `approved_scopes`
   issues no `order_by`, so which of three scopes is selected is **order-dependent**.
   This is not caused by this lane and is not fixed by it; it should be a separate
   hardening item before any further approval.

---

*Read-only disposition. No row in `data/signalforge.sqlite` was written, no promotion,
sensitivity-writing or sealed entry point was invoked, no provider API was called, no
package was installed, and no quantity inside the sealed window 2025-09-08 → 2026-09-08
was computed. `strategy_sealed_test` verified at 22 rows before and after. Source:
`docs/research/designs/volatility_breakout_short_swing.md` §§0–13 and
`docs/research/designs/scripts/volatility_breakout_short_swing/stage_a.json`.*
