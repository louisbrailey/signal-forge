# Pre-registration — Kronos eval-mode diagnostic of the null result (2026-10-03)

> Historical replay only, not advice or a trading instruction. Pretraining overlap is
> unknown; this is not verified out-of-sample model evaluation. Sampling spread is not a
> calibrated confidence interval. Price error is not investment performance and excludes
> costs. Persisted adjusted history may include later vendor revisions and corporate actions.

This record is committed BEFORE any diagnostic inference. At the time of the first commit
of this file the only model-related command executed was a load-only check (§2) that
loads the cached weights and prints `model.training`; it runs no forecast. Structure
follows `PREREGISTRATION_2026-10-03_kronos_skill.md`.

## 1. Purpose and scope

The first study (`docs/research/kronos/2026-10-02/`, 160/160 windows) found no forecast
skill, and ADR 0004 was closed as not proceeding. A code review then found that the
inference worker never puts the model in eval mode, so every forecast so far was produced
with dropout active. This diagnostic exists to **explain the null**: was "no skill" a
property of the model on this data, or an artefact of the inference settings?

It is **not an integration gate.** ADR 0004 stays closed. No outcome of this diagnostic
authorises, enables or schedules any use of Kronos on a decision path; any integration
would need a new ADR and its own pre-registered evidence. The results of the first study
under `docs/research/kronos/2026-10-02/` are preserved unchanged.

## 2. Verified premises

- `src/signalforge/kronos/worker.py` (pre-fix) loads `Kronos.from_pretrained` and
  `KronosTokenizer.from_pretrained` and never calls `.eval()`. Upstream
  `~/my-stack/Kronos/model/kronos.py` (`KronosPredictor`, `auto_regressive_inference`)
  does not call `.eval()` either; it only wraps generation in `torch.no_grad()`.
- Load-only check in the Kronos venv (offline flags, no forecast), 2026-10-02, torch
  2.14.0: `model.training True tokenizer.training True`; 18 of 18 `nn.Dropout` modules in
  the model are in train mode; after `.eval()` both report `False`.
- Cached Kronos-small `config.json`: `ffn_dropout_p 0.25`, `resid_dropout_p 0.25`,
  `attn_dropout_p 0.1`, `token_dropout_p 0.1`. Cached Kronos-Tokenizer-base config: all
  dropout probabilities 0.0, so tokenizer eval mode is not expected to change dropout.
- Train mode has one further effect upstream besides dropout:
  `model/module.py` `MultiHeadCrossAttentionWithRoPE` sets `is_causal = self.training`,
  so the s2 cross-attention is causally masked in train mode and unmasked in eval mode.
  Arm A1 therefore changes dropout **and** this mask together; the diagnostic does not
  separate them (both are "the model was not in eval mode").
- DB `~/signal-forge/data/signalforge.sqlite` is opened `mode=ro`; max massive
  `session_date` is 2026-10-02, so every window below is fully realised.

## 3. Windows (mechanical; fixed now)

- Symbols: SPY and the 11 sector ETFs XLB XLC XLE XLF XLI XLK XLP XLRE XLU XLV XLY.
- Origins: every 5th XNYS session from 2025-09-30 through 2026-08-31 inclusive, i.e.
  `sessions(2025-09-30, 2026-08-31)[::5]` — 47 origins, first 2025-09-30, last 2026-08-31.
- Horizons 5 and 20 sessions; lookback 128 (context ends at the origin; `heldout_end` is
  the h-th XNYS session after the origin). 12 × 47 × 2 = **1,128 calls per arm**.
- Resume key `symbol|horizon|heldout_end` per arm. A completed key is never re-run. Busy
  lock: sleep 30 s, ≤ 5 retries. Timeout: one retry. A failed call is recorded with its
  reason, listed in the report, and never replaced by another origin.

## 4. Arms (run once each)

| Arm | Model/tokenizer mode | T | top_p | Paths | Seeds |
| --- | --- | --- | --- | --- | --- |
| **A0** replication | train (pre-fix behaviour) | 1.0 | 0.9 | 3 single-sample paths | 42–44 |
| **A1** | eval | 1.0 | 0.9 | 3 single-sample paths | 42–44 |
| **A2** (primary, paper-faithful settings) | eval | 0.6 | 0.9 | 10 single-sample paths | 42–51 |

In every arm each path is one `predict(..., sample_count=1)` call seeded with
`torch.manual_seed(seed)` and `np.random.seed(seed)`; the point forecast is the mean
close path; all paths are retained in the ledger. `top_k` stays at the upstream default
(0). Nothing else differs between arms. A0 requires train mode, which is reachable only
through the study-only request field and never from the web route.

Integrity check (not a metric): where an A0 key coincides with a key in the first
study's `calls.jsonl`, the maximum absolute difference of `predicted` is reported. It is
expected to be 0 (same seeds, same inputs); a non-zero value is reported, not hidden.

## 5. Metrics

Definitions, per call: `r_hat = ln(mean-path close at step h / close_T)`,
`r = ln(actual close at step h / close_T)`, model error `|r_hat − r|`, unchanged
(zero-return) error `|r|`.

**Primary (A2 only).** Pooled error ratio per horizon
`R_h = Σ|r_hat − r| / Σ|r|` over all 12 symbols and all origins (a ratio of mean absolute
h-day log-return errors; the statistic analysed is `ln R_h`). The pooled form is used
because a per-call ratio is undefined when `r = 0` and heavy-tailed when either error is
near zero. Uncertainty: origin-cluster percentile bootstrap (resample origins with
replacement, keep all symbols of an origin together, recompute `ln R_h`; 10,000 draws,
seed 20261003), 95 % CI. One two-sided test per horizon of H0 `ln R_h = 0`
(bootstrap p = 2·min(share of draws ≤ 0, share ≥ 0), floored at 1/10,000); Holm across
the two horizons. The mean per-call log ratio is reported descriptively with the number
of undefined calls.

**Secondary (reported for A0, A1 and A2; no gate except rank IC in §7).**

- Error ratio as above for A0 and A1 (same bootstrap), for comparison only.
- Rank IC: for each origin, the Spearman rank correlation (average ranks for ties) of
  `r_hat` vs `r` across the 11 sector ETFs (SPY excluded). Reported: mean over origins,
  t-statistic `mean / (sd/√n)` with sample sd, share of origins with IC > 0. An origin
  missing any sector call in that arm is dropped from the IC and listed.
- Direction: share of calls with `sign(r_hat) = sign(r) ≠ 0`, next to the majority-class
  rate `max(share r > 0, share r < 0)` of the same calls, and their difference with an
  origin-cluster bootstrap 95 % CI.
- Coverage: share of calls whose realised step-h close lies within the 10 % and 90 %
  quantiles (numpy linear interpolation) of the path step-h closes. Nominal 80 %; the
  finite-sample expectation for a calibrated ensemble of n draws under this
  interpolation is 0.8·(n−1)/(n+1) (65.5 % for n = 10, 40 % for n = 3) and is printed
  beside it.
- Volatility: Kronos forecast = sample standard deviation of the predicted daily log
  returns pooled over all paths and steps of the call (first step taken from close_T);
  competitor = sample standard deviation of the trailing 20 daily log returns of the
  context; target = sample standard deviation of the h realised daily log returns
  (first from close_T). Reported: MAE of each predictor, MAE ratio Kronos/trailing with
  origin-cluster bootstrap CI, and pooled Spearman of each predictor with the target.
- Sensitivity (descriptive): the A2 `ln R_h` CI recomputed with a moving-block bootstrap
  over consecutive origins (block length 4 at h = 20, 1 at h = 5).

Known limitation, stated now: origins are 5 sessions apart, so h = 20 windows overlap
(each shares 15 sessions with its neighbour). The origin-cluster bootstrap and the IC
t-statistic treat origins as independent, which makes the h = 20 CI too narrow and the
h = 20 t-statistic too large. This biases towards finding "skill", i.e. against the
expected null; the block-bootstrap sensitivity shows the size of the effect. The whole
span is one ~11-month, mostly rising market regime.

## 6. Expectations (written before any diagnostic inference)

- A0 reproduces the first study: error ratio vs unchanged above 1 at both horizons.
- A1 (eval mode) lowers error relative to A0, because dropout noise is removed, but a
  mean of 3 sampled paths is still noisy against a deterministic baseline; ratio ≥ 1.
- A2: lower-variance point forecast; ratio expected close to but **not below** 1 (upper
  95 % CI not below 1.0 at either horizon). Mean rank IC expected indistinguishable from
  0 (|t| < 2) at both horizons. Direction expected at or below the majority-class rate.
  Coverage expected below the finite-sample reference (under-dispersion at T = 0.6).
  Volatility: trailing-20-day realised vol expected to be at least as good as Kronos.
- Expected verdict: "no zero-shot skill; not a settings artefact".

## 7. Stopping rule (verbatim)

> Run A0–A2 once; if A2's upper 95% CI for the error ratio is not below 1.0 at either
> horizon AND mean rank IC has |t| < 2, STOP and record "no zero-shot skill; not a
> settings artefact"; no further arms, knobs, lookbacks or model sizes. If either passes,
> record which and stop anyway — any follow-up is a new pre-registration. Volatility is
> reported but cannot rescue the price gate.

Operationalisation, fixed now so the verdict is mechanical:

- "Error-ratio condition passes" = the A2 origin-cluster bootstrap upper 95 % bound of
  `R_h` is below 1.0 at h = 5 or at h = 20 (either horizon is enough; which one is
  recorded, together with its Holm-adjusted p).
- "Rank-IC condition passes" = the A2 mean rank IC has |t| ≥ 2 at h = 5 or at h = 20
  (which horizon and the sign are recorded; a significantly negative IC is reported as
  such and is not "skill").
- Neither passes → the verdict sentence above is recorded verbatim. Either passes → the
  report records which and the diagnostic still stops. A0 and A1 never enter the rule.

## 8. Disclosure — outputs already seen

The first study's outputs were seen before this design was written: no skill at either
horizon (Tier A MAE ratio vs unchanged 1.34 at h = 20 and 1.26 at h = 5; Tier B pooled
1.22–1.26); its h = 20 forecasts leaned downward in a rising market; and a 3-path mean
is a noisy point forecast compared with a deterministic baseline. The arms, the T = 0.6
/ 10-path setting and the return-space metrics were chosen with that knowledge. The 12
symbols and the date span overlap the first study's windows (its month-end origins are a
different grid over the same span), so this is not independent out-of-sample evidence;
it is a diagnostic of settings on essentially the same data.

## 9. Rules

- Symmetric reporting: every arm, horizon and metric is written to `summary.json` and
  the Markdown report whatever its sign, with the §6 expectation beside the outcome.
  Failed calls are listed.
- No change of symbols, origins, horizons, lookback, arms, T, top_p, path count, seeds,
  metrics or corrections after any diagnostic result is seen.
- Volatility results cannot rescue the price gate and authorise nothing.
- The DB is opened read-only and never written. No strategy, threshold, risk rule,
  config key or import contract changes. The only production behaviour change in this
  branch is the bug fix (eval mode for the dashboard path).
- Runs are `nice -n 15`, share the one-process inference lock with `/kronos`, and are
  resumable from `docs/research/kronos/2026-10-03-diagnostic/<arm>/calls.jsonl`.

## 10. Verbatim `plan` output

Added in the commit that lands the diagnostic tooling, still before any diagnostic
inference (`plan` reads the DB `mode=ro` with plain SQL and loads no model). Command:
`uv run python scripts/kronos_eval_diagnostic.py plan`. §1–§9 are unchanged from the
first commit of this file.

Implementation notes fixed with the tooling (no result seen): the per-path seeds are
`42 + i`; the worker passes `verbose=False` to the upstream predictor (progress bar
only, no numerical effect — the A0 integrity check in §4 tests this); each ledger record
stores the git SHA, all paths, and the last 21 context closes.

```
Kronos eval-mode diagnostic plan (db=/Users/louisbrailey/signal-forge/data/signalforge.sqlite, read-only; no inference)
Symbols: ['SPY', 'XLB', 'XLC', 'XLE', 'XLF', 'XLI', 'XLK', 'XLP', 'XLRE', 'XLU', 'XLV', 'XLY']; horizons (5, 20); lookback 128
Arm A0: {"T": 1.0, "eval": false, "return_paths": true, "samples": 3, "top_p": 0.9}  # replication of pre-fix behaviour (train mode, T=1.0, top_p=0.9, 3 paths)
Arm A1: {"T": 1.0, "eval": true, "return_paths": true, "samples": 3, "top_p": 0.9}  # A0 + eval mode on model and tokenizer
Arm A2: {"T": 0.6, "eval": true, "return_paths": true, "samples": 10, "top_p": 0.9}  # PRIMARY: eval mode, T=0.6, top_p=0.9, 10 paths
Origins (47): ['2025-09-30', '2025-10-07', '2025-10-14', '2025-10-21', '2025-10-28', '2025-11-04', '2025-11-11', '2025-11-18', '2025-11-25', '2025-12-03', '2025-12-10', '2025-12-17', '2025-12-24', '2026-01-02', '2026-01-09', '2026-01-16', '2026-01-26', '2026-02-02', '2026-02-09', '2026-02-17', '2026-02-24', '2026-03-03', '2026-03-10', '2026-03-17', '2026-03-24', '2026-03-31', '2026-04-08', '2026-04-15', '2026-04-22', '2026-04-29', '2026-05-06', '2026-05-13', '2026-05-20', '2026-05-28', '2026-06-04', '2026-06-11', '2026-06-18', '2026-06-26', '2026-07-06', '2026-07-13', '2026-07-20', '2026-07-27', '2026-08-03', '2026-08-10', '2026-08-17', '2026-08-24', '2026-08-31']
  origin=2025-09-30 heldout_end h5=2025-10-07 h20=2025-10-28 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2025-10-07 heldout_end h5=2025-10-14 h20=2025-11-04 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2025-10-14 heldout_end h5=2025-10-21 h20=2025-11-11 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2025-10-21 heldout_end h5=2025-10-28 h20=2025-11-18 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2025-10-28 heldout_end h5=2025-11-04 h20=2025-11-25 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2025-11-04 heldout_end h5=2025-11-11 h20=2025-12-03 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2025-11-11 heldout_end h5=2025-11-18 h20=2025-12-10 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2025-11-18 heldout_end h5=2025-11-25 h20=2025-12-17 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2025-11-25 heldout_end h5=2025-12-03 h20=2025-12-24 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2025-12-03 heldout_end h5=2025-12-10 h20=2026-01-02 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2025-12-10 heldout_end h5=2025-12-17 h20=2026-01-09 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2025-12-17 heldout_end h5=2025-12-24 h20=2026-01-16 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2025-12-24 heldout_end h5=2026-01-02 h20=2026-01-26 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2026-01-02 heldout_end h5=2026-01-09 h20=2026-02-02 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2026-01-09 heldout_end h5=2026-01-16 h20=2026-02-09 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2026-01-16 heldout_end h5=2026-01-26 h20=2026-02-17 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2026-01-26 heldout_end h5=2026-02-02 h20=2026-02-24 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2026-02-02 heldout_end h5=2026-02-09 h20=2026-03-03 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2026-02-09 heldout_end h5=2026-02-17 h20=2026-03-10 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2026-02-17 heldout_end h5=2026-02-24 h20=2026-03-17 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2026-02-24 heldout_end h5=2026-03-03 h20=2026-03-24 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2026-03-03 heldout_end h5=2026-03-10 h20=2026-03-31 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2026-03-10 heldout_end h5=2026-03-17 h20=2026-04-08 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2026-03-17 heldout_end h5=2026-03-24 h20=2026-04-15 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2026-03-24 heldout_end h5=2026-03-31 h20=2026-04-22 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2026-03-31 heldout_end h5=2026-04-08 h20=2026-04-29 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2026-04-08 heldout_end h5=2026-04-15 h20=2026-05-06 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2026-04-15 heldout_end h5=2026-04-22 h20=2026-05-13 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2026-04-22 heldout_end h5=2026-04-29 h20=2026-05-20 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2026-04-29 heldout_end h5=2026-05-06 h20=2026-05-28 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2026-05-06 heldout_end h5=2026-05-13 h20=2026-06-04 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2026-05-13 heldout_end h5=2026-05-20 h20=2026-06-11 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2026-05-20 heldout_end h5=2026-05-28 h20=2026-06-18 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2026-05-28 heldout_end h5=2026-06-04 h20=2026-06-26 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2026-06-04 heldout_end h5=2026-06-11 h20=2026-07-06 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2026-06-11 heldout_end h5=2026-06-18 h20=2026-07-13 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2026-06-18 heldout_end h5=2026-06-26 h20=2026-07-20 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2026-06-26 heldout_end h5=2026-07-06 h20=2026-07-27 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2026-07-06 heldout_end h5=2026-07-13 h20=2026-08-03 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2026-07-13 heldout_end h5=2026-07-20 h20=2026-08-10 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2026-07-20 heldout_end h5=2026-07-27 h20=2026-08-17 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2026-07-27 heldout_end h5=2026-08-03 h20=2026-08-24 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2026-08-03 heldout_end h5=2026-08-10 h20=2026-08-31 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2026-08-10 heldout_end h5=2026-08-17 h20=2026-09-08 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2026-08-17 heldout_end h5=2026-08-24 h20=2026-09-15 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2026-08-24 heldout_end h5=2026-08-31 h20=2026-09-22 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
  origin=2026-08-31 heldout_end h5=2026-09-08 h20=2026-09-29 bars 133/148 SPY:ok XLB:ok XLC:ok XLE:ok XLF:ok XLI:ok XLK:ok XLP:ok XLRE:ok XLU:ok XLV:ok XLY:ok
Windows per arm: 1128; arms: 3; total calls: 3384
Bar-count problems: 0
Projected runtime per arm at 3s/call: 0.9 h
Projected runtime per arm at 10s/call: 3.1 h
DB facts: {"max_session_date_massive": "2026-10-02", "mtime_utc": "2026-10-03T04:23:51.454179+00:00", "path": "/Users/louisbrailey/signal-forge/data/signalforge.sqlite", "size_bytes": 1393070080}
```
