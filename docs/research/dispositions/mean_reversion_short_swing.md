# Disposition — `mean_reversion.short_swing` v0.1.0 (version 4)

**Verdict: DOES NOT PASS (documented).** Status stays `EXPERIMENTAL`. No `src/` or
`tests/` file is touched. **Sealed looks consumed: 0. k stays 5.**

Source: `docs/research/designs/mean_reversion_short_swing.md` (design, read in full);
this record follows its §11/§14. Every number below carries its SE and clustering
convention and the design section it is drawn from. Convention: `se_cl` clusters on
calendar signal date unless stated as month-block; "deff" means the **variance**
inflation factor (design §3, §C.5's I6/U15/U10 corrections).

---

## 1. The verdict, precisely

`mean_reversion.short_swing` v0.1.0 has **no pre-sealed edge that survives the
program's own 2-SE bar**, and the two gates that bind it (4 and 7) are point-estimate
gates that no surviving mechanism moves (design §1). Pre-sealed OOS expectancy is
**−0.0837R ± 0.0467 (n=309, sd 0.8202) = −0.96 SE from zero** under signal-date
clustering, further from significance under month blocks — **v4 has no measurable
edge; it is not a measured loss** (design §3.1, §11).

## 2. The four-snapshot sealed ledger (design §10)

| Snap | Window | Sealed n | Expectancy | passed |
|---|---|---|---|---|
| 1 (`universe_25_baseline_legacy`) | 2025-09-07→2026-09-07 | 91 | +0.1230R | ✅ |
| 2 (`universe_25_baseline`) | 2025-09-08→2026-09-08 | 91 | +0.1230R | ✅ |
| 3 (`universe_24_ex_meta`) | 2025-09-08→2026-09-08 | 84 | +0.1278R | ✅ |
| 4 (`universe_25_meta_continuity_corrected`) | 2025-09-08→2026-09-08 | 91 | +0.1230R | ✅ |

Gate 9 passes on **all four** snapshots (+0.1230R–0.1278R, PF 1.45–1.47) — but gate 9
is not a safety net here: it was earned on a calm, persistently bullish twelve months
that is exactly this dip-buy's best regime, and it cannot catch an overfit (design
§9.3, §11 item 9). *(sealed numbers, disposition use only, R1, marked per design
convention.)* Per R2, disclosed but never used for design in §§1–9 of the source
document.

## 3. The ten prior mechanism tests ledger (design §9.1)

**Total: 10 distinct mechanism tests on version 4. Zero implemented. Zero sealed
looks consumed.** Declared budget was 6 (2 per angle × 3 angles); 7 were evaluated in
Phase 2 plus 3 prior diagnostic levers.

| # | Angle | Variant / lever | Status | Pre-sealed result (SE) |
|---|---|---|---|---|
| 1 | prior W2 | H6 `Vol.LOW` filter | refuted | +0.1491R diff, **1.14 SE clustered**; +0.0106R/0.16 SE ex-F2; OOS −0.0754R |
| 2 | prior W2 | H8 tracking-SMA target | refuted | paired Δ **−0.0032R ± 0.0040** (wrong sign) |
| 3 | prior W2 | H8 leash lengthening | unmotivated | 6-bar leash net **+0.0410R** |
| 4 | prior W2 | unplanned Finding-7 (collapsed risk unit) | carried into #6/#7 | 65 trades −0.6710R as-run; **−0.1190R/1.60 SE invariant** |
| 5 | signal/regime | `market_ret_20d ≥ 0` | rejected | +0.1265R diff, **1.10 SE clustered**; non-monotone quintiles |
| 6 | signal/regime | **`market_ret_63d ≥ 0` (H13)** | falsified | +0.3038R/**2.005 SE** strict; **1.96 SE** vs rule complement; OOS +0.0373R ± 0.0503; gates 4,5,6,7 fail |
| 7 | signal/regime | stacked `Vol.LOW ∧ r63 ≥ 0` | rejected | OOS **−0.0740R**, n=163 (subset, not like-for-like) |
| 8 | exits/risk | V1 fill-anchored stop | **falsified before running** | invariant ceiling **+0.0079R** vs own ≥+0.03R bar |
| 9 | exits/risk | V2 min-risk guard | falsified | same invariant evidence; guard is sign-blind |
| 10 | universe/breadth | breadth filter `frac≤0.125` | falsified | re-sim 308/+0.0140R; OOS 142/−0.0335R; bear 6; grid **0/27** |

## 4. H13 — the strongest effect found, and why it is not evidence (design §3.2, §B.3)

The headline **+0.3038R at 2.005 SE clustered** (strict `r63<0` partition, n=271)
reproduces exactly, but is a definitional artefact: measured against the complement
the *shipped fail-closed rule* actually blocks (n=273, including two proxy-warmup
trades that are both winners), the difference is **+0.2963R at 1.96 SE clustered —
below the bar**. Ex-fold-2 (proposal's own): +0.2636R, **1.73 SE**. All three readings
sit within 0.3 SE of the 2-SE line — a straddle, not a pass.

## 5. Gate-3/gate-6 structural conflict (design §5.4)

Swept across the full threshold range on both populations: **gate 3 passes only for
x ≥ −0.01; gate 6 passes only for x ≤ −0.03. The admissible regions are disjoint.**
The filter's content — "do not buy dips while the market's quarter is down" — is very
nearly the condition gate 6 demands ≥10 trades from. **Any v4 proposal conditioning on
market direction hits this wall.** Zero-margin disclosure: on that frontier gate 6's
bear bucket is **11 against a floor of 10** at x=−0.04 and −0.03 (12/13 at −0.08/−0.06)
— located to ±1 trade. **The lane is measured and closed, not untried.**

## 6. The hidden-fragility demonstration (design §C.5)

Both 27-point gate-5 grids actually run, replicating `sensitivity.py`'s enumeration:

| Grid | evaluable | positive | neighbours+ | worst cell | gate 5 |
|---|---|---|---|---|---|
| H13 v0.2.0: `z_entry × stop_atr × market_ret_63d_min` (27 pts) | 27/27 | **15/27 = 55.6%** | **4/6 = 66.7%** | −0.0662 | **FAIL** |
| **same v0.2.0 under legacy 2-axis grid** (new axis pinned at 0.0) | 9/9 | **8/9 = 88.9%** | **3/4 = 0.750** | −0.0033 | **PASS**, at the exact `nb_frac<min` knife-edge |
| Breadth v0.2.0: `z_entry × stop_atr × breadth_max_frac` (27 pts) | 27/27 | **0/27 = 0.0%** | **0/6 = 0%** | −0.2679 | **FAIL** |

The middle row converts v4's most emphatic failure (0/9, 0%) into an **88.9% pass**,
on a strategy whose robustness had got *worse*. This is MAP §0.5's hidden-fragility
warning demonstrated live and is the evidentiary basis for **P2** (§8 below).

## 7. Other mechanisms tested, with SEs (design §3.5, §3.6, §C.2, §C.4)

- **Exits/risk anchor.** As-run circular statistic (partition variable is the
  denominator) gives t=−3.02/−3.49; on a denominator that does not contain it:
  **pre-sealed −0.1190 ± 0.0742 (1.60 SE)**, **OOS −0.1863 ± 0.0975 (1.91 SE)**. Both
  under 2 SE. The invariant ceiling — zeroing the entire tail's excess — is
  **+0.00786R pre-sealed / +0.01387R OOS**, against the proposal's own ≥+0.03R kill
  bar. The primary variant fails its own kill test by 2–4×, before it is run.
- **Universe/breadth.** Gradient **+0.10067R, 1.75 SE iid, 1.02 SE clustered**;
  non-monotone across single-name counts; degenerate on this universe: mean k=10.90 on
  the 81 sessions where SPY itself is at z≤−2.0 vs 0.36 elsewhere, corr(ETF-breadth,
  single-name-breadth) = 0.752.
- **H6 `Vol.LOW` vs HIGH:** +0.1491R at **1.14 SE clustered**, collapsing to +0.0106R
  (0.16 SE) ex-fold-2. **H9 refuted by construction** (self-normalising trigger).

## 8. Two deferred, separable items — put to the operator, not authorised (design §2.4, §14.2)

**P1 — engine risk-unit correctness fix (NOT `mean_reversion`-specific).**
`backtest/engine.py` `EntrySignal` gains `stop_distance` + `stop_anchor_blend` (default
0.0, byte-identical behaviour; no strategy opts in; no `VERSION` bump). Evidence: 4
`stop` exits booked as **wins**; median realised risk **2.1272 ATR** against an
intended 2.000; one trade renders 5.5 bps slippage as **−3.099R** off a 2.9-cent risk
unit. **This is a correctness fix, not an edge claim** — its invariant value is
+0.0079R at 1.74 SE and must not be framed otherwise. Seven release gates (byte-
identical default behaviour; no opt-in/no VERSION bump; both live approvals' spec
hashes unmoved — `2ed97431…f382` v2, `dfe696b6…6f6c32` v5; zero-margin cases unmoved
— v6 neighbour fraction 0.750, v5 bear bucket 11; directional guard closing the
inverted-stop class; live-path divergence closed or recorded; no expectancy framing)
gate any implementation, on a scratch database only.

**P2 — gate-5 axis integrity rule.** Standing rule: every parameter a v0.2.0
introduces becomes a pre-registered gate-5 axis in the same change. Prerequisite: the
declared-axis mechanism of `pipeline_hardening_spec.md` §2 (an optional
`sensitivity_axes()` on the strategy class — **never** a `StrategySpec` field, which
would move every `spec_json_hash` and unscope both live approvals). Evidence: §6
above.

**Neither is a `mean_reversion` change; neither bumps a strategy version; neither
costs a sealed look. Both require operator approval before any code is written.**

## 9. Pre-registered re-opening criteria (design §4.2) — measured today, every candidate fails ≥3 of 6

| # | Condition | Status today |
|---|---|---|
| RO-1 | mechanism separates pre-sealed expectancy ≥2 SE on calendar-MONTH block | **fails all three angles** even on the narrower day-clustered measure (H13 1.96–2.01, anchor 1.60/1.91, breadth 1.02) |
| RO-2 | re-simulated OOS expectancy >0 and ≥2 SE above zero, month-block | fails |
| RO-3 | breaks no gate v0.1.0 passes (gate-6 bear ≥10, gate-1 ≥2/4) | **fails** for H13 (bear 2) and breadth (bear 6) |
| RO-4 | full gate-5 grid ≥60% positive, ≥75% neighbours | **fails** for both grids actually run |
| RO-5 | conditioning variable computable in live scan path | required, unassessed |
| RO-6 | survives 2×/5× spread re-pricing, OOS expectancy still >0 | **fails** for H13 (+0.0003R at 26 bps) and breadth (negative at every priced point) |

Nine pre-registered kill conditions fired across three independent angles (design §4.1).
**Under R10 that ends the matter.**

## 10. Cost — the last escape closed (design §8)

At MAP's own "2×" column (26 bps round trip, `spread_bps=20`), H13's best OOS
expectancy falls from +0.0373R to **+0.0003R** — indistinguishable from zero. Because a
wider universe is exactly where wider spreads live, expanding the universe to power
this strategy is **self-defeating**: breadth adds n while spread removes the point
estimate, and gate 4 needs the point estimate.

## 11. Sealed-look accounting (design §10)

**Baseline k = 5. Consumed by this disposition: 0. Planned: 0. k stays 5.** A
hypothetical v0.2.0 on snapshot 3 would be **look 6**. Convention clash flagged, not
silently resolved: MAP §0.1/R2 say "look 5"; MAP §4.2 item 10 and this record's
convention say **look 6**; `pipeline_hardening_spec.md` adopts `k_prior=4,
this_look=5`. This record uses **k=5 → look 6** per MAP §4.2 item 10 and the binding
brief; the operator should settle it once, before any counter ships.

## 12. Promotion-integrity finding (design §7, §14.2 Q4)

Gate 10 is `health_monitor.enabled` and passes unconditionally — nothing in the ladder
prevents a strategy structurally incapable of emitting a live signal (e.g. any
fail-closed cross-sectional rule, given `scan.py:269-272` passes no breadth) from
reaching PAPER_APPROVED. Out of scope for a `mean_reversion` change; raised as a
separate hardening item, not bundled with this disposition.

## 13. Operator decisions outstanding (design §14.2)

1. Approve **P1** (engine risk-unit fix) — recommended yes, subject to all seven
   release gates.
2. Approve **P2** (gate-5 axis integrity rule) — recommended yes.
3. Settle the look-numbering convention (k=5→look 6 vs the alternatives) once.
4. Accept the promotion-integrity finding (gate 10) as a separate hardening item.
5. Confirm gate-7 docstring/code divergence disposition (fix the docstring, not the
   code).
6. Confirm MAP §4.2 item 8's "2×/5× spread" is understood as 4×/12× the modelled
   quoted spread.

---

*Read-only disposition. No strategy code, configuration, database row, or gate
threshold was changed in producing this record. Source:
`docs/research/designs/mean_reversion_short_swing.md` §§A–14 and Appendix.*


## CONFIRMED — 2026-09-11 powered evaluation on the 150-symbol snapshot: DOES NOT PASS

Pre-registered (docs/research/PREREGISTRATION_2026-09-11_snapshot11.md) and run
unchanged (v0.1.0) on DataSnapshot 11 (evaluation 46, sealed test locked; family look
6). With 2,057 OOS trades the point-estimate gates fail with power to spare: OOS
expectancy −0.0191R, bootstrap CI low −0.0551R, sensitivity 22% of points / 25% of
neighbours positive, Sharpe −0.75 (CAGR −15.1%, maxDD 88.3%). Gates 1, 2, 6, 8 pass;
the sealed year alone is +0.0579R on 570 trades and does not rescue it. This closes
the strategy as designed; the design document's candidate mechanisms were already
refuted pre-sealed. Status stays EXPERIMENTAL. No further look on this snapshot.
