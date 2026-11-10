# Kronos path dispersion versus simple volatility measures — result (2026-11-10)

**FAIL.**
With the seven simple volatility measures already in the regression, the spread of the ten Kronos paths (D1) adds a mean coefficient of +0.0259 at 5 sessions (Newey–West t +4.07) and +0.0258 at 10 sessions (t +3.16) for ranking next-period realised volatility (T1). The rule needs a coefficient of at least 0.03, a t of at least 3 and the same sign in both halves at both horizons; not met: at 5 sessions the coefficient is below 0.03; at 10 sessions the coefficient is below 0.03. By the pre-registered rule this closes zero-shot Kronos-small as a risk input as well.

Pre-registration: `docs/research/kronos/PREREGISTRATION_2026-11-10_kronos_dispersion_volatility.md`. Script: `scripts/r5/kronos_dispersion_volatility.py`. Generated 2026-11-10T23:12:02Z. No inference was run: the 60 saved primary forecasts of the rank-IC study were re-used (60 of 60 origin files passed that study's integrity checks), with the same bars file (last date 2025-09-05).

## Decision rule, applied mechanically

| h | mean D1 coefficient | needs ≥ 0.03 | Newey–West t | needs ≥ 3 | first half | second half | same sign | cell passes |
|---|---|---|---|---|---|---|---|---|
| 5 | +0.0259 | no | +4.07 | yes | +0.0210 | +0.0310 | yes | no |
| 10 | +0.0258 | no | +3.16 | yes | +0.0251 | +0.0265 | yes | no |

## Every cell: Kronos coefficient with the seven simple ranks in the regression

Per origin, the target's rank is regressed on the Kronos predictor's rank and the seven simple ranks (all rescaled to −0.5..0.5). The coefficient is averaged over origins. Only T1 with D1 carries a verdict.

| target | predictor | h | origins | names (mean) | mean coefficient | NW s.e. | NW t | first half | second half | plain rank corr. | mean R² simple only | mean R² with Kronos | R² gain |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| T1 realised volatility (primary) | D1 spread of path returns (primary) | 5 | 59 | 500.0 | +0.0259 | +0.0064 | +4.07 | +0.0210 | +0.0310 | +0.3339 | +0.3798 | +0.3817 | +0.0020 |
| T1 realised volatility (primary) | D1 spread of path returns (primary) | 10 | 58 | 500.0 | +0.0258 | +0.0082 | +3.16 | +0.0251 | +0.0265 | +0.3262 | +0.4822 | +0.4847 | +0.0025 |
| T1 realised volatility (primary) | D2 mean path volatility | 5 | 59 | 500.0 | +0.0324 | +0.0089 | +3.65 | +0.0199 | +0.0452 | +0.4152 | +0.3798 | +0.3823 | +0.0025 |
| T1 realised volatility (primary) | D2 mean path volatility | 10 | 58 | 500.0 | +0.0182 | +0.0135 | +1.35 | +0.0128 | +0.0236 | +0.4320 | +0.4822 | +0.4857 | +0.0034 |
| T2 absolute return | D1 spread of path returns (primary) | 5 | 59 | 500.0 | +0.0143 | +0.0068 | +2.12 | +0.0135 | +0.0152 | +0.1762 | +0.1383 | +0.1404 | +0.0021 |
| T2 absolute return | D1 spread of path returns (primary) | 10 | 58 | 500.0 | +0.0049 | +0.0068 | +0.73 | -0.0033 | +0.0132 | +0.1523 | +0.1426 | +0.1450 | +0.0024 |
| T2 absolute return | D2 mean path volatility | 5 | 59 | 500.0 | +0.0082 | +0.0105 | +0.78 | -0.0045 | +0.0213 | +0.2137 | +0.1383 | +0.1415 | +0.0032 |
| T2 absolute return | D2 mean path volatility | 10 | 58 | 500.0 | -0.0159 | +0.0110 | -1.44 | -0.0217 | -0.0101 | +0.1973 | +0.1426 | +0.1465 | +0.0039 |
| T3 largest overnight gap | D1 spread of path returns (primary) | 5 | 59 | 500.0 | +0.0364 | +0.0060 | +6.02 | +0.0322 | +0.0408 | +0.3365 | +0.3608 | +0.3632 | +0.0025 |
| T3 largest overnight gap | D1 spread of path returns (primary) | 10 | 58 | 500.0 | +0.0419 | +0.0086 | +4.85 | +0.0390 | +0.0448 | +0.3060 | +0.3837 | +0.3872 | +0.0034 |
| T3 largest overnight gap | D2 mean path volatility | 5 | 59 | 500.0 | +0.0687 | +0.0100 | +6.87 | +0.0588 | +0.0788 | +0.4250 | +0.3608 | +0.3661 | +0.0053 |
| T3 largest overnight gap | D2 mean path volatility | 10 | 58 | 500.0 | +0.0695 | +0.0115 | +6.06 | +0.0555 | +0.0835 | +0.4137 | +0.3837 | +0.3888 | +0.0051 |

## Plain rank correlations with each target (no controls)

Mean over origins of the cross-sectional rank correlation; Newey–West t in brackets. The best simple measure for each target and horizon is in bold.

| measure | T1 h=5 | T1 h=10 | T2 h=5 | T2 h=10 | T3 h=5 | T3 h=10 |
|---|---|---|---|---|---|---|
| Kronos D1 spread of path returns (primary) | +0.3339 (+34.8) | +0.3262 (+22.4) | +0.1762 (+16.4) | +0.1523 (+12.5) | +0.3365 (+30.9) | +0.3060 (+19.3) |
| Kronos D2 mean path volatility | +0.4152 (+34.2) | +0.4320 (+21.4) | +0.2137 (+14.5) | +0.1973 (+11.9) | +0.4250 (+29.1) | +0.4137 (+19.8) |
| realised volatility, 5 sessions | +0.4097 (+23.2) | +0.4609 (+20.7) | +0.2076 (+14.0) | +0.2138 (+14.9) | +0.4051 (+20.2) | +0.4084 (+16.6) |
| realised volatility, 20 sessions | +0.5030 (+33.7) | +0.5652 (+30.6) | +0.2599 (+17.8) | +0.2725 (+15.8) | +0.4910 (+26.0) | +0.4988 (+22.1) |
| realised volatility, 60 sessions | +0.5469 (+41.8) | +0.6301 (+46.1) | +0.2900 (+19.2) | +0.3049 (+19.5) | +0.5405 (+28.8) | +0.5668 (+26.7) |
| realised volatility, 90 sessions | +0.5607 (+44.9) | +0.6424 (+47.4) | **+0.2984 (+20.3)** | **+0.3104 (+19.3)** | **+0.5522 (+34.4)** | **+0.5746 (+30.2)** |
| ATR14 / close | **+0.5657 (+39.9)** | **+0.6433 (+39.6)** | +0.2958 (+19.7) | +0.3058 (+18.9) | +0.5279 (+29.5) | +0.5462 (+25.8) |
| Parkinson range volatility, 20 sessions | +0.5612 (+46.4) | +0.6385 (+46.4) | +0.2920 (+21.2) | +0.3073 (+18.1) | +0.5142 (+30.0) | +0.5326 (+26.5) |
| absolute 5-session return | +0.2171 (+13.6) | +0.2431 (+13.7) | +0.1055 (+8.0) | +0.1094 (+8.2) | +0.2148 (+12.1) | +0.2193 (+10.9) |

## Checks run before the result

**Identity check (passed).** This script's own D1 and T2 reproduce the rank-IC study's dispersion rows to four decimals:

| h | rank corr. D1 vs absolute return: here / study | partial given 20-session volatility: here / study | origins |
|---|---|---|---|
| 5 | +0.1762 / +0.1762 | +0.0642 / +0.0642 | 59 |
| 10 | +0.1523 / +0.1523 | +0.0581 / +0.0581 | 58 |

**No look-ahead (passed).** At each of the 60 origins the seven simple measures were recomputed with every bar after the origin set to missing; all 420 arrays were identical. Targets use sessions origin+1..origin+h only; the latest target session used is 2025-09-04.

**Synthetic self-test (passed).** Same regression code, made-up data (60 origins, 500 names):

| synthetic predictor | mean coefficient | NW t | plain rank corr. | R² gain | expected |
|---|---|---|---|---|---|
| pure noise | -0.0049 | -1.11 | -0.0001 | +0.0013 | near zero |
| noisy copy of rv60 | -0.0028 | -0.26 | +0.5554 | +0.0013 | near zero despite a large plain correlation |
| planted independent | +0.3594 | +99.65 | +0.3643 | +0.1283 | clearly positive |

## Deviations and clarifications

1. No deviation from the pre-registration. The points below record choices the text left open.
2. Loading: the origin files were loaded with `load_bars` and `load_run` imported from `scripts/r3/kronos_ic_analyze.py`, so that study's integrity checks ran on all 60 files; the rank, correlation and Newey–West functions are imported from the same file. Only `pred_close` is used; `pred_high` and `pred_low` are not read.
3. Realised volatility in the simple measures uses the pre-registration's own definition (root mean square of daily close-to-close log returns) over the last 5, 20, 60 and 90 returns ending at the origin. The rank-IC study's 20-session volatility was a sample standard deviation; that version is used only inside the identity check, to reproduce that study's rows.
4. ATR14 is the plain average of the last 14 true ranges (the convention of `signalforge.research.features.daily.atr`), divided by the origin close. Parkinson volatility is sqrt(mean(ln(high/low)²) / (4 ln 2)) over the 20 sessions ending at the origin. Absolute 5-session return is |close ÷ close five sessions earlier − 1|.
5. D1 is the sample standard deviation (n − 1) across the ten paths of predicted close at step h ÷ last observed close − 1, exactly as in the rank-IC study. D2 takes each path's daily log returns over steps 1..h, the first measured from the last observed close, then the root mean square per path, then the mean over paths.
6. T3 uses the opens of sessions origin+1..origin+h, each against the previous session's close (the origin close for the first).
7. All 500 names; a name is used at an origin only if the target, the predictor and all seven simple measures are finite, and ranks are taken among the names used. An origin needs at least 30 names (the rank-IC study's rule). The plain rank correlations are computed on the same names as the regression.
8. Halves: the first ⌈n/2⌉ scored origins against the rest (the rank-IC study's rule). Newey–West: Bartlett weights, lag ⌈h/5⌉ (1 at h = 5, 2 at h = 10), variance divided by n, as in that study's `nw_stats`.
9. R² gain is the mean over origins of (R² with the Kronos rank and the seven simple ranks − R² with the seven simple ranks alone); it cannot be negative for any single origin.
10. The no-look-ahead assertion compares bit for bit. On its first execution it stopped the script before any result was computed or written: the bars had been held in column-major memory order and the masked copy in row-major order, so sums differed in the last binary digit (relative difference below 5e-16) with no later bar involved. The arrays are now held in row-major order and the comparison is exact; the definitions did not change. Run history: the second execution produced the results. The script was then executed a third time after a wording-only edit to the verdict sentence, and a fourth time after review added sentences to this section and to the limits; neither edit touched a definition, the statistic or the decision rule. The fourth execution's cell statistics, decision values, check results and per-origin series were compared with the third's and are identical; the second execution's outputs were overwritten, so its equality with the later ones rests on the code being deterministic and unchanged in its computations, not on a saved copy.
11. Coverage of the built-in checks: the identity check exercises D1 and T2 only, and the synthetic self-test exercises only the regression function on made-up data. T1, T3, D2 and the seven simple measures are covered by the no-look-ahead assertion but by no other built-in check.
12. The coefficients of the seven simple ranks from the same regressions are saved in `dispersion_summary.json` for reference; no extra regression or variant was run. The incomplete secondary run and the contrast run were not read.

## Limits

- The fail is on coefficient size only (about 0.026 against the required 0.03 at both horizons); the t and same-sign conditions are met. The pre-registration names ATR14 without saying how the 14 true ranges are averaged; the plain average used here was fixed by the repo's existing function, not by the pre-registration, and the margin of the fail may depend on that choice. The rule was applied as written and no other convention was run by this script.
- Same forecasts and window as a study whose dispersion row had already been seen.
- One model size (Kronos-small), one sampling configuration, ten paths per name.
- At most 59 overlapping origins; nominal Newey–West t values run large with this few origins.
- A survivor-conditioned list of 500 names; nothing after 2025-09-05.
- Ranks only: the result says nothing about the level or calibration of a volatility forecast.
- A pass would be a reason to test further, not a risk model; a fail speaks only to zero-shot use of this model here.

Research signal only — no order was placed.
