# Disposition — `mean_reversion.short_swing`, exits & risk angle (V1 / V2 vs v0.1.0)

**Verdict: STOP at Stage A. Does not pass.** No v0.2.0 is shipped, no sealed look is
consumed, the strategy stays **`EXPERIMENTAL`** (`strategy_version.id = 4`), and its four
sealed tests (ids 3, 8, 13, 18) are untouched. **Sealed looks consumed: 0.** Ledger (`strategy_sealed_test`, family `mean_reversion.short_swing`): previous looks recorded = 5 (snapshots 1, 2, 3, 4, 11); next new look index = 6. Unchanged by this stage.
No `evaluate_promotion`, no `StrategySealedTest`, no `StrategyVersion` row.

Source: `docs/research/designs/proposals/mean_reversion_short_swing--exits_risk.md`
(§4 F1–F5, §9 stopping rule, §11 null option). This record is that proposal's §11.
Evidence: `docs/research/designs/scripts/mean_reversion_short_swing/stage_a.{json,md}`,
produced by `scripts/stage_a_mr.py` on a `mode=ro` copy of the live database with every
sealed/minting entry point replaced by a function that raises. Every number carries its
n and SE. **A difference under 2 SE is not evidence.**

---

## 1. The verdict, precisely

Both pre-specified variants failed the primary kill test **F1** on every snapshot, and
V1 additionally failed **F3**. Under §9 the lane is closed: no third variant, no λ
tuning, no promotion run.

| test | bar (§4) | V1 (fill-anchored stop, λ = 1) | V2 (min-risk guard, 1 ATR) |
|---|---|---|---|
| **F1** paired, fixed denominator | mean > 0 and ≥ 2 SE, every snapshot | **FAIL** — Δ = **−0.0165R ± 0.0118** (−1.40 SE) snap 3; −0.0135R (−1.14 SE) snaps 2/1; −0.0121R (−1.03 SE) snap 4. **Negative on all four** | **FAIL** — Δ ≡ **0.0000** on every matched trade (a no-trade rule leaves matched entries identical); cannot clear 2 SE by construction |
| **F2** risk ≥ 1 ATR partition | subset Δ ≥ 2 SE when whole Δ > 0 | PASS (vacuous: whole Δ ≤ 0). Subset Δ −0.0078R (−0.91 SE); tail Δ −0.1358R (−1.06 SE, n = 65) | PASS (vacuous: Δ ≡ 0) |
| **F3** folds | ≥ 2 of 4 positive with n ≥ 15; no redistribution | **FAIL** — **1 of 4** folds positive on every snapshot (fold 3 flips from +0.0436R to −0.0212R) | PASS — 3 of 4 (+0.0060 / −0.1099 / +0.0612 / +0.0228 on snap 3) |
| **F4** artefact class | 0 profitable stops, 0 risk < 0.5 ATR | PASS — 0 / 0 (v0.1.0: 4 profitable stops, 65 trades under 1 ATR) | PASS — 0 / 0 |
| **F5** snapshot invariance | F1–F4 hold, same F1 sign, on all 4 | FAIL (F1 sign is uniformly negative) | FAIL (F1 fails everywhere) |

**Reproduction first.** `run_strategy_over_universe` on snapshot 3 gives **984 pre-sealed /
309 OOS at −0.08374R**, matching evaluation 34 exactly; the script's variant wrapper at
`stop_anchor_blend = 0.0` reproduces that trade list trade-for-trade before any variant
number was read. Snapshot 4 (`META_CONT`) was loaded through the same continuity mapping
the promotion path uses (`source = ["massive", "continuity_bridge:1"]`), closing the F5
coverage gap the proposal recorded.

## 2. What the numbers say about the mechanism (H13)

The proposal's §3.4 warned that one third to one half of V1's apparent gain was
definitional. Stage A shows it was **all** of it, and then some:

* **Raw R, unpaired** (not accounting-invariant): V1 moves pre-sealed expectancy from
  −0.0621R to −0.0580R on snapshot 3 (+0.0041R ± 0.0377, 0.11 SE). OOS: −0.0837R →
  −0.0843R. Nothing moves.
* **Fixed denominator, paired** (the test that cancels the rescaling): V1 is **worse** on
  962 of 984 matched trades by −0.0165R ± 0.0118. Re-anchoring the stop to the fill pulls
  the stop **up** on the median trade (the fill typically sits ~0.13 ATR above the signal
  close), and the extra stop-outs on the 93% of normal trades cost more than the tail
  saves. The tail itself (65 gapped trades) is −0.1358R ± 0.128 under V1 — still negative
  and within one SE of zero.
* **F3** is the structural confirmation: V1 turns fold 3 (2021-03 → 2023-06) from
  +0.0436R to −0.0212R while improving folds 1, 2 and 4 by 0.01–0.03R. Gate 1 would fail
  under V1 (1 of 4 folds) where v0.1.0 passes by a coin flip (2 of 4).
* **V2** removes 48–50 trades per snapshot (the ones with < 1 ATR of room) and the raw
  pre-sealed expectancy rises to **−0.0134R ± 0.0250** (OOS **−0.0136R ± 0.0456**, n =
  291). This is exactly the §11 item 3 ceiling the proposal computed in advance: even a
  perfect removal of the tail leaves the point estimate **negative** and indistinguishable
  from zero — short of gate 3 (> 0), gate 4 (+0.1115R at this n) and gate 7 (+0.0596R).
  V2's F1 is identically zero because a no-trade rule changes no matched trade; under §4
  and §9 step 3 that is a FAIL, and the operator-facing alternative reading ("F1 does not
  apply to a filter") changes nothing about the outcome because the OOS estimate stays
  negative on all four snapshots.

**The finding is not "the diagnostic was wrong".** The anchor defect is real and F4
confirms both variants remove it completely (0 profitable "stop" exits, 0 sub-0.5-ATR
risk units, versus 4 and 65 in v0.1.0). It is that removing it does not produce an edge:
the strategy's deficit is in the 93% of trades that were never affected by the gap.

## 3. Disposition

- **v0.1.0** (version 4): stays **`EXPERIMENTAL`**. Untouched. Four sealed draws stand.
- **v0.2.0**: **not implemented.** No `VERSION` bump, no `EntrySignal` fields, no
  `sensitivity_axes`, no pre-registration. The §2.1 engine change is **not** shipped by
  this lane.
- **No gate, threshold or cost-model constant was changed.** No file under `src/` was
  modified; the variants were realised as a script-side wrapper around the public engine.
- **Variant ledger for this angle: 2 of 2 spent (cap 2).** Both dead. No third variant.
- **Sealed-look ledger:** previous looks = 5 before, **5 after** (next new look index stays 6). `strategy_sealed_test` verified
  at 22 rows before and after on the copy.

## 4. The dissenting recommendation, carried forward (§11)

Independent of this strategy, the shared execution model still allows a stop to sit
above the fill and a risk unit to collapse to 0.0043 ATR (JPM 2025-04-04, booked at
−3.099R off a 2.9-cent risk unit). Shipping §2.1's `stop_anchor_blend` /
`stop_distance` / `min_risk_distance` fields as a **behaviour-preserving engine
correctness fix** (defaults `0.0` / `None`, opt-in per strategy, zero sealed looks,
v2/v5 spec hashes unmoved) remains a legitimate option for the operator. It is **not** a
promotion attempt and this disposition does not authorise it; it records that Stage A's
evidence (F4: 0 / 0 on every snapshot under either variant) supports the mechanics of the
fix while refuting its value as an edge for this strategy.

## 5. What would reopen the lane

Nothing from the exits-and-risk side. Per §11, the honest output when the variant budget
is exhausted without a pre-sealed positive surviving falsification is the documented
fail. Any future work on `mean_reversion.short_swing` belongs to a different angle with
its own budget, and must contend with the structural facts restated in §11 items 3–4:
the point-estimate gates 4 and 7 are out of reach at this effect size, and gate 1 is one
noisy fold from failing.

---

*Read-only disposition. No row in `data/signalforge.sqlite` was written, no promotion,
sensitivity-writing or sealed entry point was invoked, no provider API was called, and no
quantity inside the sealed window 2025-09-08 → 2026-09-08 (2025-09-07 → 2026-09-07 on
snapshot 1) was computed. Source: the proposal §§0–11 and
`docs/research/designs/scripts/mean_reversion_short_swing/stage_a.json`.*
