# Kronos zero-shot cross-sectional rank IC on US daily bars (2026-11-10)

Pre-registration: `docs/research/kronos/PREREGISTRATION_2026-11-10_kronos_cross_sectional_ic.md` (commit 9bc9d24).

**FAIL.** Kronos-small's zero-shot forecast had a mean cross-sectional rank IC of +0.0156 at 10 sessions (Newey-West t +0.66, 58 origins, 500 names, 2024-07-01 to 2025-09-05); the first and second halves were +0.0240 and +0.0071, and its coefficient alongside four simple ranks had t +1.05.
The pre-registered rule needs all of: mean rank IC at least 0.02, Newey-West t at least 3 after Holm, the same sign in both halves and an incremental t of at least 2. Not met: a mean rank IC of at least 0.02; a Newey-West t of at least 3; a Holm-adjusted p-value no larger than the p-value of t = 3; a t of at least 2 for the Kronos coefficient alongside the four simple ranks. This closes zero-shot Kronos-small as a cross-sectional US daily signal; fine-tuning would need its own pre-registration.
A nominal 95% interval for the mean rank IC (mean +/- 1.96 Newey-West standard errors; a description, not part of the rule) runs from -0.0309 to +0.0620: it contains zero and lies wholly below the 0.0622 that the paper reports for Kronos-small.

The secondary (production configuration) run is incomplete (46 of 60 origins) and is not scored.
The contrast-window run was not run.

## Decision rule

| Criterion (primary endpoint: h = 10, paper configuration, full universe) | Value | Required | Met |
|---|---|---|---|
| Mean rank IC | +0.0156 | >= 0.02 | no |
| Newey-West t (lag 2) | +0.66 | >= 3 | no |
| Holm-adjusted p within h = 5, 10, 20 | 1.0000 | <= 0.0027 | no |
| Half-window means | +0.0240 / +0.0071 | same sign | yes |
| Incremental Kronos coefficient t | +1.05 | >= 2 | no |
| **Verdict** | **FAIL** | | |

Not part of the rule: nominal 95% interval -0.0309 to +0.0620 (Newey-West s.e. 0.0237); verdict if the Holm clause were read as t >= 3 alone: FAIL (the same as the verdict above).

## What was run

Compute tier 1: 20 generated steps, 500 names (full universe 500).

| Run | Configuration | Window | Names | Origins present / expected | First origin | Last origin | Scored origins at h = 5 / 10 / 20 |
|---|---|---|---|---|---|---|---|
| Primary | paper: look-back 90, T = 0.6, top-p = 0.9, 10 paths | test | 500 | 60 / 60 | 2024-07-01 | 2025-09-04 | 59 / 58 / 56 |
| Secondary | production: look-back 128, T = 1.0, top-p = 0.9, 3 paths | test | 500 | 46 / 60 (incomplete, not scored) | | 2025-05-23 (last present) | not scored |
| Contrast | not run | | | | | | |

All runs were written by one version of the inference script (SHA-256 `e484b6526d4e9447...`). Recorded in the origin files: primary 2500 rows per chunk on 4 CPU threads.

## Primary and secondary endpoints: rank IC by horizon (paper configuration, full universe)

Predicted return at h is the mean over paths of the predicted close at origin + h divided by the observed close at the origin, minus 1; realised return is close to close.

| Horizon | Origins | Names | Mean rank IC | NW s.e. | NW t | p | Holm p | First half | Second half | Same sign | Pearson IC (exploratory) | NW t (Pearson, exploratory) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| h = 5 (secondary) | 59 | 500 | -0.0006 | 0.0168 | -0.03 | 0.9728 | 1.0000 | +0.0181 | -0.0199 | no | -0.0020 | -0.12 |
| h = 10 (primary) | 58 | 500 | +0.0156 | 0.0237 | +0.66 | 0.5106 | 1.0000 | +0.0240 | +0.0071 | yes | +0.0093 | +0.39 |
| h = 20 (secondary) | 56 | 500 | +0.0134 | 0.0419 | +0.32 | 0.7491 | 1.0000 | -0.0207 | +0.0475 | no | +0.0145 | +0.36 |

The p and Holm p columns use a normal reference and are nominal: with this few overlapping origins they run small. When 20,000 random scores with no information were scored against this window in the same way, |t| >= 2 occurred in 7.75% of cases at h = 10 (nominal 4.55%) and t >= 3 in 0.50% (nominal 0.13%); the IC part of the PASS rule was met in 0.18%. The Pearson columns are exploratory.

Tradable version (entered at the next open, exit at the close of origin + h):

| Cell | Origins | Names | Mean rank IC | NW s.e. | NW t | First half | Second half | Same sign | Pearson IC (exploratory) | NW t (Pearson, exploratory) |
|---|---|---|---|---|---|---|---|---|---|---|
| h = 5, next-open entry | 59 | 500 | -0.0016 | 0.0163 | -0.10 | +0.0087 | -0.0122 | no | -0.0013 | -0.08 |
| h = 10, next-open entry | 58 | 500 | +0.0109 | 0.0249 | +0.44 | +0.0095 | +0.0123 | yes | +0.0066 | +0.27 |
| h = 20, next-open entry | 56 | 500 | +0.0063 | 0.0424 | +0.15 | -0.0334 | +0.0460 | no | +0.0092 | +0.23 |

## Exploratory cells (no adjustment)

The production-configuration rows use the frozen books' settings (look-back 128, T = 1.0, top-p = 0.9, 3 paths) with an independent random stream for every name, not the shared stream the frozen books use (deviation 2). They describe those settings on a broad universe; they are not the frozen books' outcome.

| Cell | Origins | Names | Mean rank IC | NW s.e. | NW t | First half | Second half | Same sign | Pearson IC (exploratory) | NW t (Pearson, exploratory) |
|---|---|---|---|---|---|---|---|---|---|---|
| Production configuration, h = 5 | incomplete (46 of 60 origins), not scored | | | | | | | | | |
| Production configuration, h = 10 | incomplete (46 of 60 origins), not scored | | | | | | | | | |
| Production configuration, h = 20 | incomplete (46 of 60 origins), not scored | | | | | | | | | |
| Stocks only (485 names), h = 5 | 59 | 485 | -0.0006 | 0.0167 | -0.03 | +0.0187 | -0.0204 | no | -0.0019 | -0.11 |
| Stocks only (485 names), h = 10 | 58 | 485 | +0.0151 | 0.0235 | +0.64 | +0.0234 | +0.0068 | yes | +0.0090 | +0.38 |
| Stocks only (485 names), h = 20 | 56 | 485 | +0.0129 | 0.0416 | +0.31 | -0.0216 | +0.0473 | no | +0.0142 | +0.36 |
| Snapshot-11 subset (147 names), h = 5 | 59 | 147 | -0.0100 | 0.0208 | -0.48 | +0.0041 | -0.0245 | no | -0.0081 | -0.36 |
| Snapshot-11 subset (147 names), h = 10 | 58 | 147 | +0.0174 | 0.0287 | +0.61 | +0.0288 | +0.0061 | yes | +0.0042 | +0.14 |
| Snapshot-11 subset (147 names), h = 20 | 56 | 147 | +0.0203 | 0.0543 | +0.37 | -0.0093 | +0.0498 | no | +0.0263 | +0.46 |

Pearson IC of the primary configuration (exploratory) is in the right-hand columns of the tables above.

## Incremental value: Kronos rank alongside four simple ranks

| Horizon | Origins | Names | Kronos coef. | NW t | 5-session return coef. (t) | 20-session return coef. (t) | 252-minus-21 session return coef. (t) | 20-session realised volatility coef. (t) |
|---|---|---|---|---|---|---|---|---|
| h = 5 | 59 | 500 | -0.0010 | -0.09 | -0.0077 (-0.44) | +0.0056 (+0.27) | +0.0237 (+1.12) | +0.0245 (+0.96) |
| h = 10 | 58 | 500 | +0.0117 | +1.05 | -0.0051 (-0.31) | +0.0165 (+0.56) | +0.0305 (+1.33) | +0.0316 (+0.87) |
| h = 20 | 56 | 500 | +0.0152 | +0.38 | -0.0078 (-0.46) | +0.0362 (+0.97) | +0.0333 (+1.18) | +0.0137 (+0.31) |

Rank IC of each simple rank alone (same origins, same realised returns, same statistics as the table for the Kronos forecast):

| Simple rank | Horizon | Origins | Names | Mean rank IC | NW s.e. | NW t | First half | Second half | Same sign |
|---|---|---|---|---|---|---|---|---|---|
| 5-session return | h = 5 | 59 | 500 | -0.0122 | 0.0207 | -0.59 | -0.0145 | -0.0099 | yes |
| 5-session return | h = 10 | 58 | 500 | -0.0142 | 0.0195 | -0.73 | -0.0241 | -0.0043 | yes |
| 5-session return | h = 20 | 56 | 500 | +0.0004 | 0.0262 | +0.02 | -0.0310 | +0.0319 | no |
| 20-session return | h = 5 | 59 | 500 | -0.0069 | 0.0257 | -0.27 | -0.0376 | +0.0249 | no |
| 20-session return | h = 10 | 58 | 500 | -0.0011 | 0.0303 | -0.04 | -0.0384 | +0.0362 | no |
| 20-session return | h = 20 | 56 | 500 | +0.0225 | 0.0392 | +0.58 | -0.0023 | +0.0474 | no |
| 252-minus-21 session return | h = 5 | 59 | 500 | +0.0099 | 0.0234 | +0.42 | +0.0425 | -0.0238 | no |
| 252-minus-21 session return | h = 10 | 58 | 500 | +0.0068 | 0.0255 | +0.27 | +0.0511 | -0.0375 | no |
| 252-minus-21 session return | h = 20 | 56 | 500 | -0.0030 | 0.0309 | -0.10 | +0.0564 | -0.0625 | no |
| 20-session realised volatility | h = 5 | 59 | 500 | +0.0293 | 0.0307 | +0.95 | +0.0085 | +0.0508 | yes |
| 20-session realised volatility | h = 10 | 58 | 500 | +0.0429 | 0.0409 | +1.05 | +0.0072 | +0.0787 | yes |
| 20-session realised volatility | h = 20 | 56 | 500 | +0.0395 | 0.0587 | +0.67 | -0.0039 | +0.0828 | no |

## Economic size: decile spreads, entered at the next open (basis points per holding period)

| Horizon | Origins | Names per decile | Top - bottom gross | Top - bottom net of 22 bps (NW t) | Top - universe gross | Top - universe net of 11 bps (NW t) |
|---|---|---|---|---|---|---|
| h = 5 | 59 | 50 | -21.1 | -43.1 (-1.49) | -6.4 | -17.4 (-0.95) |
| h = 10 | 58 | 50 | +18.3 | -3.7 (-0.06) | +25.6 | +14.6 (+0.50) |

## Dispersion: does path spread rank realised absolute return?

| Horizon | Origins | Rank correlation with abs. realised return (NW t) | Partial, given 20-session realised volatility (NW t) |
|---|---|---|---|
| h = 5 | 59 | +0.1762 (+16.40) | +0.0642 (+7.89) |
| h = 10 | 58 | +0.1523 (+12.52) | +0.0581 (+6.71) |
| h = 20 | 56 | +0.1781 (+11.67) | +0.0831 (+8.15) |

## Threshold preview (production configuration)

Share of names for which the mean terminal close exceeds the last close x 1.0011, and the mean realised close-to-close return of selected and unselected names. This describes the frozen rule's condition on a broad universe. It is not the frozen books' outcome and is not used to tune them. The three paths here use an independent random stream for every name; the frozen books give every name the same three streams (deviation 2), so the share selected there can differ.

| Horizon | Origins | Share selected (min - max) | Mean return, selected | Mean return, unselected | Selected - unselected (NW t) |
|---|---|---|---|---|---|
| h = 5 | incomplete (46 of 60 origins), not scored | | | | |
| h = 20 | incomplete (46 of 60 origins), not scored | | | | |

## Memorisation contrast (paper configuration, contrast window 2023-01-03 to 2024-06-14)

| Horizon | Contrast IC (NW s.e.) | Test IC (NW s.e.) | Difference | s.e. of difference | More than two s.e.? | Contrast IC itself positive? |
|---|---|---|---|---|---|---|
| h = 5 | not run | | | | | |
| h = 10 | not run | | | | | |
| h = 20 | not run | | | | | |

## Rank IC at every generated horizon (descriptive, not a pre-registered endpoint, no adjustment)

Paper configuration, full universe. Only h = 5, 10 and 20 are pre-registered; the other rows are shown so that nothing generated is left out.

| h | Origins | Mean rank IC | NW t | h | Origins | Mean rank IC | NW t |
|---|---|---|---|---|---|---|---|
| 1 | 60 | +0.0054 | +0.40 | 11 | 58 | +0.0225 | +0.83 |
| 2 | 59 | +0.0121 | +0.75 | 12 | 57 | +0.0311 | +1.04 |
| 3 | 59 | +0.0110 | +0.72 | 13 | 57 | +0.0334 | +1.02 |
| 4 | 59 | +0.0164 | +0.94 | 14 | 57 | +0.0357 | +1.03 |
| 5 | 59 | -0.0006 | -0.03 | 15 | 57 | +0.0167 | +0.43 |
| 6 | 59 | +0.0004 | +0.02 | 16 | 57 | +0.0279 | +0.67 |
| 7 | 58 | +0.0163 | +0.83 | 17 | 56 | +0.0301 | +0.74 |
| 8 | 58 | +0.0179 | +0.87 | 18 | 56 | +0.0242 | +0.59 |
| 9 | 58 | +0.0294 | +1.47 | 19 | 56 | +0.0250 | +0.61 |
| 10 | 58 | +0.0156 | +0.66 | 20 | 56 | +0.0134 | +0.32 |

## Validation before the run

- Device check G0, paper configuration (32 series, origin 2024-07-01): largest difference in first-step class probabilities between CPU and mps was 3.28e-06 (limit 1e-3): passed.
- Same seeds on CPU and on mps, paper configuration (32 series): 320 of 320 paths identical; one chunk versus four chunks bitwise identical: yes.
- Device check G0, production configuration (32 series, origin 2024-07-01): largest difference in first-step class probabilities between CPU and mps was 2.25e-06 (limit 1e-3): passed.
- Same seeds on CPU and on mps, production configuration (32 series): 96 of 96 paths identical; one chunk versus four chunks bitwise identical: yes.
- Equivalence with upstream `KronosPredictor.predict` on CPU (paper configuration, NVDA, TSLA, AAPL, origin 2024-07-01): 30 of 30 seeded paths identical (largest relative difference in predicted close 0.0e+00); first-step logits differ by at most 1.3e-05. Mean of 200 independent paths against upstream's own 200-path mean: largest |z| 2.49 over 60 symbol-step cells, 98% below 2.
- Equivalence with upstream `KronosPredictor.predict` on CPU (production configuration, NVDA, TSLA, AAPL, origin 2024-07-01): 9 of 9 seeded paths identical (largest relative difference in predicted close 0.0e+00); first-step logits differ by at most 1.8e-05.
- Look-ahead test, paper configuration on the test window: inputs bit-for-bit unchanged with every later bar set to NaN at 60 of 60 origins; an input cut one session late was caught at 60 of 60.
- Look-ahead test, production configuration on the test window: inputs bit-for-bit unchanged with every later bar set to NaN at 60 of 60 origins; an input cut one session late was caught at 60 of 60.
- Look-ahead test, paper configuration on the contrast window: inputs bit-for-bit unchanged with every later bar set to NaN at 73 of 73 origins; an input cut one session late was caught at 73 of 73.
- Synthetic noise forecasts through the whole analysis (20 seeds): mean rank IC at h = 10 averaged +0.0010; the rule returned FAIL, FAIL, FAIL on the seeds pushed through it.
- Rejection rates with no information (one fixed random score per name, 20,000 simulations scored against this window's realised returns; no forecast is read): |t| >= 2 in 5.37% / 7.75% / 9.62% of cases at h = 5 / 10 / 20 (nominal 4.55%); t >= 3 in 0.21% / 0.50% / 0.89% (nominal 0.13%); IC part of the PASS rule met in 0.18%.
- Rejection rates with no information (fresh noise at every origin, 4,000 simulations scored against this window's realised returns; no forecast is read): |t| >= 2 in 6.02% / 6.42% / 7.35% of cases at h = 5 / 10 / 20 (nominal 4.55%); t >= 3 in 0.40% / 0.25% / 0.43% (nominal 0.13%); IC part of the PASS rule met in 0.00%.
- Planted signal (target rank IC 0.050): recovered +0.0508 (t 9.5) at h = 5, +0.0468 (t 7.2) at h = 10, +0.0550 (t 9.5) at h = 20.
- Oracle forecast (equals the future close): rank IC 1.0000 at h = 10; shifted by one origin -0.014 / +0.443 / +0.704 at h = 5 / 10 / 20 (return windows then overlap by 0, 1/2 and 3/4).
- Analysis guards on synthetic run directories: 8 of 8 passed (an incomplete primary is refused; an incomplete secondary is reported and not scored; a changed last close, shifted future dates, a foreign script hash, altered row seeds and a stray origin file each stop the analysis; the directories are put back unchanged).
- Throughput pilot: 14.0 s for one origin at full size on mps; tier 1 chosen before any score was examined. The pilot origin regenerated by the final script is bitwise identical to the earlier pilot in 1 of 1 files.
- Review repairs: 22 of 22 definitions that make up the sampler have an identical syntax tree before and after the repairs; the input builder lost 3 checks that could not fail and is otherwise identical.
- Review repairs, analysis: 31 of 31 definitions that compute the statistics have an identical syntax tree before and after the repairs, and the five PASS criteria are identical.

## Deviations and clarifications

1. **Late origins.** An origin near the end of the window is given only as many steps as there are sessions on or before 2025-09-05 after it, so no date after 2025-09-05 is used even as a calendar feature. Generation is causal, so the retained steps are what a 20-step run would have produced. The last test origin therefore has fewer than 5 steps and enters no pre-registered horizon.
2. **Seeds.** Path seeds are 42 + path index. So that results do not depend on batch size or device, every (origin, symbol, path) row owns a CPU generator whose 32-bit seed is the first four bytes of SHA-256 over `kronos-ic-r3/<window>/origin/<origin index>/symbol/<symbol>/path-seed/<42 + path index>`; the origin index, the path seeds and all row seeds are stored in each origin file, and the analysis recomputes the row seeds from this formula before it scores a file. Rows are sampled independently, as in upstream's batched sampler. Production runs one symbol per process and so reuses stream 42 + path for every symbol; that sharing of noise across symbols is not reproduced here. The production-configuration cells and the threshold preview therefore describe the frozen settings under independent draws, not under the exact streams the frozen books use.
3. **Speed-up, not a variant.** The transformer reuses cached keys and values of earlier positions instead of recomputing the context at each step, and sampling (upstream's own top-p filter, softmax and `torch.multinomial`) runs on the CPU while the transformer runs on the accelerator. The validation section gives the measured agreement with upstream.
4. **`t >= 3 (Holm within the horizon family)`** is applied in its stricter reading: the Newey-West t of the primary endpoint must be at least 3 and its Holm-adjusted two-sided p-value (family h = 5, 10, 20; normal reference) must not exceed the p-value of t = 3 (0.0027). That amounts to t >= 3.32 when the primary has the smallest p-value of the three, 3.21 when it has the middle one and 3.00 when it has the largest. Under the plainer reading (t >= 3 alone) a t between 3.00 and 3.32 could pass; the reading was fixed before any forecast was scored, and the decision section states whether the verdict would differ under the plainer one.
5. **Newey-West.** Bartlett kernel, lag = ceil(h / 5) origins, variance of the mean of the per-origin series, no small-sample correction, normal p-values. Halves are the first ceil(n / 2) and the remaining scored origins. The p-values, the Holm p-values and every 'two standard errors' statement are nominal: with this few overlapping origins they understate tail probabilities. The validation section gives the measured rejection rates when the score carries no information. The rule itself is stated on t and on the mean, and is unchanged.
6. **Interval in the lead.** The lead adds a nominal 95% interval (mean +/- 1.96 Newey-West standard errors) and says whether it contains zero and the paper's rank IC of 0.0622. This is a description of how tight the result is. It is not a pre-registered endpoint and takes no part in the verdict.
7. **Incremental regression.** Per origin, ordinary least squares with an intercept of the realised-return rank on the Kronos rank and the four simple ranks, all ranks rescaled to [-0.5, 0.5]; the coefficient series is averaged with a Newey-West t. A name without 252 earlier sessions at an origin is left out of that origin's regression and of the 252-minus-21 rank. Realised volatility is the sample standard deviation of the last 20 daily log returns. Every simple rank uses bars up to the origin only.
8. **Decile spreads.** A decile is floor(n / 10) names. Returns run from the open of origin + 1 to the close of origin + h. Net top-minus-bottom deducts 22 bps (a round trip on each leg); net top-minus-universe deducts 11 bps (only the top decile is traded; the universe mean is a benchmark).
9. **Dispersion** is the sample standard deviation across paths of the path return at h; the partial rank correlation controls for the 20-session realised-volatility rank.
10. **Memorisation flag.** 'More than two standard errors' is read as two standard errors of the difference, sqrt(se_contrast^2 + se_test^2), with Newey-West standard errors. The contrast universe additionally requires every session from 2022-06-01. Contrast origins are scored by the same rule as test origins (origin + h on or before 2025-09-05), so a few of the latest contrast targets fall after June 2024; the count is given below. The flag compares two different market periods and fires on the gap alone, so the report also says whether the contrast-window IC is itself positive.
11. **Snapshot-11 subset** means study-universe members that are complete members of data snapshot 11 (every XNYS session 2016-10-17 to 2025-09-05 in `massive` bars).
12. **Threshold preview** uses steps 5 and 20 of the single 20-step generation of the production configuration.
13. **`amount`** is volume x mean(open, high, low, close), the value upstream fills in when, as in production, no amount column is supplied.
14. **Device check G0** compares the softmax of the first-step logits of both token heads (at T = 1 and at the sampling temperature) between CPU and the accelerator; the distribution after the top-p filter and every later step are also recorded in the check's output.
15. **Pilot origin.** The first test origin (2024-07-01) was generated during the throughput pilot and kept, because the run is resumable. It was made by the same version of the script as every other origin (the run cannot be resumed by a different one). Its forecasts were not compared with realised returns before this analysis.
16. **Production configuration before the primary run.** The pre-registration says the secondary configuration runs only after the primary finishes, and the script refuses the secondary run until then. Before the primary run, the production configuration was nevertheless used for validation: the device check on 32 series and the three-symbol equivalence check (each run once when the scripts were built and once more after the review repairs), the code review's own comparison of 24 production-configuration paths with upstream, and one full-size origin that the first pilot timed without saving it and without leaving a log. No forecast from any of these was kept or compared with realised returns.
17. **Review repairs before the run.** After two adversarial reviews and before the long run, the scripts were hardened: a real look-ahead test, the script hash frozen into the run definition and stored in every origin file, stricter checks of every origin file at scoring time, a 20:00 UTC cut-off, distinct exit codes, no scoring of incomplete runs, and the wording and tables of this report. The sampling code was not changed (its syntax tree is identical before and after), and the pilot origin regenerated by the final script is bitwise identical to the first one; the validation section gives the records.
18. **Look-ahead.** No bar after an origin can enter its input because the input is cut from a view that ends at the origin. That is true by construction, so it is tested from outside: for every origin the input is rebuilt with all later bars replaced by NaN and must be bit-for-bit identical, and an input deliberately cut one session late must be caught.
19. **Rank IC at every generated horizon** is shown for completeness. Only h = 5, 10 and 20 are pre-registered endpoints; the other horizons are descriptive and carry no adjustment.
20. **Incomplete runs are not scored.** The analysis refuses an incomplete primary run outright. An incomplete secondary or contrast run is reported as incomplete and none of its forecasts is read.

## Limits

One model size, one tokenizer, daily bars, a survivor-conditioned list chosen in 2025, one 14-month window containing one market regime, overlapping horizons. Per-origin values are in `ic_series.csv`; every number above is in `summary.json`.

Research signal only — no order was placed.
