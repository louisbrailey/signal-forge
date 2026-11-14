# Pre-registration — Kronos zero-shot cross-sectional rank IC on US daily bars (2026-11-10)

Status: written 2026-11-10 before any inference of this study. Operator request
(2026-11-10): "continue pushing for more profit within each strategy and the kronos ai
part of the workflow". ADR 0004 stays closed and ADR 0005 stays research-only; Kronos
remains off the decision path. No sealed look, no operating-database write, no change to
the frozen comparison books, their manifests, the model cache or `~/my-stack/Kronos`.
Outputs, named in advance: `docs/research/kronos/2026-11-10-cross-sectional/`
(`KRONOS_CROSS_SECTIONAL_IC_2026-11-10.md`, `summary.json`, `ic_series.csv`).

## Why

The two earlier studies could not see the one thing the model's authors claim. The skill
study scored price-level error on SPY at 12 origins; the eval-mode diagnostic's rank IC
used 11–12 correlated ETFs (standard error ≈ 0.05). The paper (arXiv 2508.02739,
Appendix D and Table 6) reports a *cross-sectional* return signal — IC 0.0665, RankIC
0.0622 for Kronos-small — from daily bars with a 90-day look-back, sampling at T = 0.6,
top-p = 0.9, N = 10 paths, predicted return = last predicted close ÷ last observed close.
It also states "The pre-training data for Kronos extends up to June 2024" and that every
test period starts in July 2024. So 2024-07-01..2025-09-05 is both after the model's
training data and before the equity sealed window: the only clean, unsealed test window
this project has. If the signal exists on US stocks, the natural use is ranking same-day
candidates when capacity binds — not the fixed 11 bps threshold of the frozen books.

## Verified premises

- Cached weights: `NeoQuasar/Kronos-small` and `NeoQuasar/Kronos-Tokenizer-base` only.
  They are loaded from a private copy made for this study; the Hugging Face cache and
  `~/my-stack/Kronos` are not written to (bytecode writes disabled, model code imported
  from a private copy). No download. No network.
- Universe: members of the frozen list
  `docs/research/diagnostics/universe500_selection_presealed.json` (485 common stocks +
  15 ETFs, chosen before this study) that have every XNYS session from 2023-12-01 to
  2025-09-05 in persisted `massive` adjusted daily bars. The list was selected in 2025,
  so membership is survivor-conditioned; this is a limit on return *levels*, less so on
  ranks.
- Inference never runs between 20:30 UTC and 00:15 UTC (the frozen books' collection
  window) and never takes the production runtime lock.

## Design (fixed)

- **Origins:** every fifth XNYS session starting 2024-07-01. An origin is scored at
  horizon h only if session origin+h is on or before 2025-09-05.
- **Primary configuration (paper):** look-back 90 sessions, T = 0.6, top-p = 0.9, 10
  paths, seeds 42 + path index and origin index recorded, eval mode. 20 steps are
  generated, giving h = 1..20.
- **Secondary configuration (production):** look-back 128, T = 1.0, top-p = 0.9, 3 paths
  — the settings of the shadow ledger and the frozen books.
- **Score:** predicted return at h = mean over paths of predicted close at origin+h ÷
  observed close at origin − 1. Realised return = adjusted close at origin+h ÷ adjusted
  close at origin − 1 (close-to-close; a tradable version from the next open is
  reported as secondary).
- **Device check (G0):** before the run, one batch of 32 series is scored on CPU and on
  the accelerator with identical inputs; the first-step class probabilities must agree
  within 1e-3. If not, the run uses CPU and the reduced tiers below.
- **Compute tiers (chosen by measured throughput before any score is examined):** tier 1
  as above; tier 2 generates 10 steps (h ≤ 10) if tier 1 projects past 5 hours; tier 3
  additionally restricts the universe to the complete members of data snapshot 11. The
  primary endpoint exists in every tier. The secondary configuration and the contrast
  window run only after the primary finishes.
- **Contrast window (memorisation check):** the same primary design on origins every
  fifth session from 2023-01-03 to 2024-06-14, which lies inside the training period.

## Endpoints and tests

Cross-sectional Spearman rank IC per origin between predicted and realised return; the
series mean, Newey–West t (lag = ⌈h/5⌉ origins), and the mean in each half of the window.

- **Primary:** h = 10, primary configuration, full universe.
- **Secondary (Holm-adjusted together with the primary within the family h ∈ {5, 10, 20}):**
  h = 5 and h = 20; then, reported without adjustment and labelled exploratory: the
  production configuration; stocks only; the snapshot-11 subset; Pearson IC.
- **Incremental value:** per-origin regression of realised rank on Kronos rank plus four
  simple ranks known at the origin — 5-session return, 20-session return, 252-minus-21
  session return, 20-session realised volatility — and the Newey–West t of the Kronos
  coefficient. The same IC table is reported for each simple rank alone.
- **Economic size:** equal-weight top-decile minus bottom-decile and top-decile minus
  universe mean, h = 5 and h = 10, entered at the next open, 11 bps round trip.
- **Dispersion:** rank correlation of path dispersion (standard deviation of path
  returns at h) with realised absolute return, and its partial correlation given
  20-session realised volatility.
- **Threshold preview:** share of names the frozen rule's condition (mean terminal close
  > last close × 1.0011) selects at h = 5 and h = 20 under the production configuration,
  and the mean realised return of selected versus unselected names. This describes the
  rule on a broad universe; it is not the frozen books' outcome and is not used to tune
  them.

## Decision rule (fixed)

**PASS** only if, for the primary endpoint: mean rank IC ≥ 0.02, Newey–West t ≥ 3 (Holm
within the horizon family), the same sign in both halves, and the incremental Kronos
coefficient has t ≥ 2. A pass justifies writing a *new* ADR and a *new* pre-registered
prospective study that uses the forecast to rank candidates; it authorises nothing else.
**FAIL** closes zero-shot Kronos-small as a cross-sectional US daily signal; fine-tuning
would be the only remaining route and needs its own pre-registration. If the contrast
window's IC exceeds the test window's by more than two standard errors, that is reported
as evidence of memorisation.

## Expectations (stated in advance)

A null: mean rank IC between −0.01 and +0.02 at every horizon, short-term reversal
explaining most of whatever appears, and the production configuration no better than the
paper one. The paper's 0.06 was measured on its own test universes; US large caps are the
most efficient part of them.

## Limits

One model size, one tokenizer, daily bars, a survivor-conditioned list, one 14-month
window containing one market regime, overlapping horizons. A pass would be a reason to
test prospectively, not a profit claim.

Research signal only — no order was placed.
