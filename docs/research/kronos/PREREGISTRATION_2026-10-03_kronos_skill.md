# Pre-registration — Kronos forecast-skill study (2026-10-03)

> Historical replay only, not advice or a trading instruction. Pretraining overlap is
> unknown; this is not verified out-of-sample model evaluation. Sampling spread is not a
> calibrated confidence interval. Price MAE is not investment performance and excludes
> costs. Persisted adjusted history may include later vendor revisions and corporate actions.

This record is written BEFORE any study inference. Nothing below has been run with
`pilot` or `run`. The only command executed was `plan`, which reads the database
`mode=ro` with plain SQL and performs no inference (§9). Structure follows
`docs/research/PREREGISTRATION_2026-09-24_regime_diversity.md`.

## 1. Problem

`/kronos` replays `NeoQuasar/Kronos-small` on persisted Massive daily bars and shows a
per-window MAE beside the unchanged-price baseline. One window is an anecdote. Before
anyone proposes Kronos as an input to anything (see the PROPOSED, not accepted,
`docs/decisions/0004-kronos-regime-input.md`), the question "does the model beat trivial
baselines on windows it plausibly has not seen?" needs a pre-registered answer with
symmetric reporting. The expected answer is **no detectable skill** (§7).

## 2. Verified premises (source and read-only DB)

- `kronos.service.replay(session, symbol, horizon, as_of=)` selects the latest 128+h
  massive bars at/before `as_of`, requires an exact XNYS-continuous window, rejects
  flagged/simulated/unadjusted bars, sends only the 128 context bars and the held-out
  *dates* to the worker, and returns `predicted` = mean of 3 seeded paths (42–44),
  `lower`/`upper` = sampled min/max. Pretraining overlap is `"unknown"`.
- Inference is one process at a time via an OS lock (`runtime.infer`), 90 s timeout,
  offline flags, no inherited credentials. The study calls the same function, so it
  contends with the dashboard and the live worker's CPU; it never calls the worker
  module directly.
- Import contracts: `signalforge.kronos` is forbidden to `research`, `risk`, `paper`,
  `execution`, `backtest`, and cannot import `paper`, `execution`, `alerts`, `llm`,
  `data.adapters`, `research.scan`. This study changes none of them.
- DB (`~/signal-forge/data/signalforge.sqlite`, 1,393,045,504 bytes, mtime
  2026-10-02T23:38:31Z): SPY massive 2,504 sessions 2016-10-17 → 2026-10-02; the 11
  sector ETFs have 2,504 each except XLC (2,084, listed 2018). All 160 Tier A+B windows
  have exactly 128+h bars ending on the pre-registered `heldout_end` with the context
  ending on the origin (`plan`, §9).
- Kronos-small weights cached at HF snapshot `901c26c1…` and the tokenizer at
  `0e011738…`; the cached snapshots contain `config.json` + `model.safetensors` only, so
  no model-card data-cutoff line is available locally. The `report` command records the
  sha256 of every cached weight file.

## 3. Mechanical symbol, origin and horizon rules (fixed now)

- Horizons: 5 and 20 held-out sessions (the only two the service accepts).
- **Tier A (primary):** SPY. Origins = last XNYS session of each month 2025-09 … 2026-08
  (12). `heldout_end` = h-th XNYS session after the origin. The run asserts
  `result["input_end"] == origin`.
- **Exploratory, excluded from every family:** SPY origins 2025-02-27 and 2025-03-31,
  labelled `overlap_possible` (before the model's public release, so pretraining overlap
  is more likely). Reported descriptively only.
- **Tier B (pooled):** XLB XLC XLE XLF XLI XLK XLP XLRE XLU XLV XLY, every second Tier A
  origin (6: 2025-09-30, 2025-11-28, 2026-01-30, 2026-03-31, 2026-05-29, 2026-07-31),
  both horizons: 132 calls.
- **Tier C (optional, only with `--tier C`):** the 8 symbols, excluding SPY and Tier B,
  with ≥ 2,400 XNYS-continuous massive sessions, ordered by
  `sha256("kronos-study-2026|" + symbol)` ascending, evaluated on the Tier B origins.
  `plan --tier C` resolves this today to: MAA, CINF, SNA, STX, CDE, QCOM, COO, IESC
  (96 calls). Exploratory only.
- Resume key: `symbol|horizon|heldout_end`. A completed key is never re-run. Busy lock:
  sleep 30 s, ≤ 5 retries. Timeout: one retry, then the failure is recorded with its
  reason and listed in the report. No failed call is replaced by a different origin.

## 4. Baselines (all computed from the 128 context closes only)

- `unchanged`: close_T repeated.
- `drift`: close_T · exp(k · mean log-return over the context), k = 1..h.
- `sma20`: flat trailing 20-close mean (descriptive only, not in any family).

## 5. Endpoints and corrections

Per window: MAE, MAPE, relative MAE (MAE/close_T), MAE ratio = model MAE / baseline
MAE (and its log), horizon-end directional accuracy (sign of predicted move vs
realised move from close_T; zero counts as a miss), per-bar hit rate, band coverage per
bar and at horizon end, mean band width / close_T, band degeneracy flag.

- **Primary family (Holm, α = 0.05), Tier A 12 origins:** four tests — MAE ratio vs
  drift and vs unchanged at h = 20 and h = 5. Statistic: per-origin log-MAE-ratio;
  exact sign-flip permutation test (4,096 assignments), two-sided p; effect = geometric
  mean ratio; percentile CI of the sign-flipped mean re-centred on the observation
  (a descriptive band, not a calibrated interval). One-sided p is reported alongside.
- **Secondary family (Benjamini–Hochberg, q = 0.10), Tier A:** horizon-end directional
  accuracy vs 50 % (exact binomial, n = 12) at h = 20 and h = 5; model direction vs
  drift-sign direction (paired sign-flip test on hit differences); horizon-end band
  coverage vs the 50 % nominal rate of a 3-sample min–max band ((n−1)/(n+1) = 0.5),
  exact binomial, at both horizons. Per-bar coverage, band width and per-bar hit rate
  are descriptive (bars within a window are dependent).
- **Tier B pooled:** cluster bootstrap over origins (10,000 draws, seed 20261003) of the
  pooled mean log-MAE-ratio vs drift and vs unchanged at both horizons. Effect + CI only;
  no p-value, no gate other than G5.
- Tier C and `overlap_possible`: descriptive only.

## 6. Gates

- **G1** pre-registration before inference.
- **G2** skill: Tier A h=20 and h=5 MAE ratio vs drift and vs unchanged all <1, Holm p<0.05, CI upper<1, point ≤0.95 at h=20.
- **G3** direction: h=20 horizon-end accuracy >50%, BH p<0.10, not worse than drift sign.
- **G4** calibration: coverage not rejected at 50% (p≥0.10), bands non-degenerate.
- **G5** Tier B pooled MAE ratio vs drift CI upper<1 at h=20.
- **G6** second pre-registered regime-relevance study on ≥2 non-bull spans with tighten-only ablation.
- **G7** per-strategy pre-registered promotion re-evaluation, no threshold changes.
- **G8** engineering: forecast table + inference-free reader, flag default OFF, safety tests, explicit ignore_imports amendment.
- **G9** reproducibility: report regenerates byte-identical summary; ≥5-window re-inference spot check.
- **G10** operator sign-off.

G1–G5 are answered by this study. G6–G10 are listed so the full ladder is visible now;
none of them is started by this record and none can be satisfied by it.

## 7. Expected outcome

**The null is expected.** Kronos-small is a general-purpose K-line foundation model with
no claimed daily-horizon edge on US ETFs; drift and unchanged baselines are hard to beat
at 5–20 sessions. With n = 12 origins the smallest attainable two-sided permutation p is
2/4096 and a true 5 % MAE improvement would usually NOT reach Holm significance, so a
"fail" of G2 is weak evidence of no skill, not proof. A pass of G2 on this sample would
be surprising and would itself need the G9 re-inference check before being believed.
Coverage of the 3-sample band is expected near 50 % at h = 5 and possibly lower at
h = 20; a clearly lower rate is reported as under-dispersion, not corrected.

## 8. Rules

- Symmetric reporting: every test's effect, CI and p (raw and adjusted) is written to
  `summary.json` and the Markdown report whatever its sign. Failed calls are listed.
- No re-selection of origins, symbols, horizons, baselines, sample count, seed or
  correction after any result is seen. `pilot` results are the first three Tier A calls
  and count as study calls; they are not discarded.
- No strategy, threshold, risk rule, regime input, config key, contract or dashboard
  behaviour changes as part of this study. The DB is never written.
- The study runs only when the operator chooses; it shares the inference lock and the
  CPU with the live worker.
- A good result is not a reason to promote anything. It is at most a reason to design G6.

## 9. Verbatim `plan` output (2026-10-03, read-only; no inference)

```
Kronos forecast-skill study plan (db=/Users/louisbrailey/signal-forge/data/signalforge.sqlite, read-only)
Tiers: AB; horizons (5, 20); lookback 128
Tier A origins: ['2025-09-30', '2025-10-31', '2025-11-28', '2025-12-31', '2026-01-30', '2026-02-27', '2026-03-31', '2026-04-30', '2026-05-29', '2026-06-30', '2026-07-31', '2026-08-31']
Tier B origins: ['2025-09-30', '2025-11-28', '2026-01-30', '2026-03-31', '2026-05-29', '2026-07-31']
  ok  A primary          SPY   h= 5 origin=2025-09-30 heldout_end=2025-10-07 bars=133/133
  ok  A primary          SPY   h=20 origin=2025-09-30 heldout_end=2025-10-28 bars=148/148
  ok  A primary          SPY   h= 5 origin=2025-10-31 heldout_end=2025-11-07 bars=133/133
  ok  A primary          SPY   h=20 origin=2025-10-31 heldout_end=2025-12-01 bars=148/148
  ok  A primary          SPY   h= 5 origin=2025-11-28 heldout_end=2025-12-05 bars=133/133
  ok  A primary          SPY   h=20 origin=2025-11-28 heldout_end=2025-12-29 bars=148/148
  ok  A primary          SPY   h= 5 origin=2025-12-31 heldout_end=2026-01-08 bars=133/133
  ok  A primary          SPY   h=20 origin=2025-12-31 heldout_end=2026-01-30 bars=148/148
  ok  A primary          SPY   h= 5 origin=2026-01-30 heldout_end=2026-02-06 bars=133/133
  ok  A primary          SPY   h=20 origin=2026-01-30 heldout_end=2026-03-02 bars=148/148
  ok  A primary          SPY   h= 5 origin=2026-02-27 heldout_end=2026-03-06 bars=133/133
  ok  A primary          SPY   h=20 origin=2026-02-27 heldout_end=2026-03-27 bars=148/148
  ok  A primary          SPY   h= 5 origin=2026-03-31 heldout_end=2026-04-08 bars=133/133
  ok  A primary          SPY   h=20 origin=2026-03-31 heldout_end=2026-04-29 bars=148/148
  ok  A primary          SPY   h= 5 origin=2026-04-30 heldout_end=2026-05-07 bars=133/133
  ok  A primary          SPY   h=20 origin=2026-04-30 heldout_end=2026-05-29 bars=148/148
  ok  A primary          SPY   h= 5 origin=2026-05-29 heldout_end=2026-06-05 bars=133/133
  ok  A primary          SPY   h=20 origin=2026-05-29 heldout_end=2026-06-29 bars=148/148
  ok  A primary          SPY   h= 5 origin=2026-06-30 heldout_end=2026-07-08 bars=133/133
  ok  A primary          SPY   h=20 origin=2026-06-30 heldout_end=2026-07-29 bars=148/148
  ok  A primary          SPY   h= 5 origin=2026-07-31 heldout_end=2026-08-07 bars=133/133
  ok  A primary          SPY   h=20 origin=2026-07-31 heldout_end=2026-08-28 bars=148/148
  ok  A primary          SPY   h= 5 origin=2026-08-31 heldout_end=2026-09-08 bars=133/133
  ok  A primary          SPY   h=20 origin=2026-08-31 heldout_end=2026-09-29 bars=148/148
  ok  A overlap_possible SPY   h= 5 origin=2025-02-27 heldout_end=2025-03-06 bars=133/133
  ok  A overlap_possible SPY   h=20 origin=2025-02-27 heldout_end=2025-03-27 bars=148/148
  ok  A overlap_possible SPY   h= 5 origin=2025-03-31 heldout_end=2025-04-07 bars=133/133
  ok  A overlap_possible SPY   h=20 origin=2025-03-31 heldout_end=2025-04-29 bars=148/148
  ok  B pooled           XLB   h= 5 origin=2025-09-30 heldout_end=2025-10-07 bars=133/133
  ok  B pooled           XLB   h=20 origin=2025-09-30 heldout_end=2025-10-28 bars=148/148
  ok  B pooled           XLB   h= 5 origin=2025-11-28 heldout_end=2025-12-05 bars=133/133
  ok  B pooled           XLB   h=20 origin=2025-11-28 heldout_end=2025-12-29 bars=148/148
  ok  B pooled           XLB   h= 5 origin=2026-01-30 heldout_end=2026-02-06 bars=133/133
  ok  B pooled           XLB   h=20 origin=2026-01-30 heldout_end=2026-03-02 bars=148/148
  ok  B pooled           XLB   h= 5 origin=2026-03-31 heldout_end=2026-04-08 bars=133/133
  ok  B pooled           XLB   h=20 origin=2026-03-31 heldout_end=2026-04-29 bars=148/148
  ok  B pooled           XLB   h= 5 origin=2026-05-29 heldout_end=2026-06-05 bars=133/133
  ok  B pooled           XLB   h=20 origin=2026-05-29 heldout_end=2026-06-29 bars=148/148
  ok  B pooled           XLB   h= 5 origin=2026-07-31 heldout_end=2026-08-07 bars=133/133
  ok  B pooled           XLB   h=20 origin=2026-07-31 heldout_end=2026-08-28 bars=148/148
  ok  B pooled           XLC   h= 5 origin=2025-09-30 heldout_end=2025-10-07 bars=133/133
  ok  B pooled           XLC   h=20 origin=2025-09-30 heldout_end=2025-10-28 bars=148/148
  ok  B pooled           XLC   h= 5 origin=2025-11-28 heldout_end=2025-12-05 bars=133/133
  ok  B pooled           XLC   h=20 origin=2025-11-28 heldout_end=2025-12-29 bars=148/148
  ok  B pooled           XLC   h= 5 origin=2026-01-30 heldout_end=2026-02-06 bars=133/133
  ok  B pooled           XLC   h=20 origin=2026-01-30 heldout_end=2026-03-02 bars=148/148
  ok  B pooled           XLC   h= 5 origin=2026-03-31 heldout_end=2026-04-08 bars=133/133
  ok  B pooled           XLC   h=20 origin=2026-03-31 heldout_end=2026-04-29 bars=148/148
  ok  B pooled           XLC   h= 5 origin=2026-05-29 heldout_end=2026-06-05 bars=133/133
  ok  B pooled           XLC   h=20 origin=2026-05-29 heldout_end=2026-06-29 bars=148/148
  ok  B pooled           XLC   h= 5 origin=2026-07-31 heldout_end=2026-08-07 bars=133/133
  ok  B pooled           XLC   h=20 origin=2026-07-31 heldout_end=2026-08-28 bars=148/148
  ok  B pooled           XLE   h= 5 origin=2025-09-30 heldout_end=2025-10-07 bars=133/133
  ok  B pooled           XLE   h=20 origin=2025-09-30 heldout_end=2025-10-28 bars=148/148
  ok  B pooled           XLE   h= 5 origin=2025-11-28 heldout_end=2025-12-05 bars=133/133
  ok  B pooled           XLE   h=20 origin=2025-11-28 heldout_end=2025-12-29 bars=148/148
  ok  B pooled           XLE   h= 5 origin=2026-01-30 heldout_end=2026-02-06 bars=133/133
  ok  B pooled           XLE   h=20 origin=2026-01-30 heldout_end=2026-03-02 bars=148/148
  ok  B pooled           XLE   h= 5 origin=2026-03-31 heldout_end=2026-04-08 bars=133/133
  ok  B pooled           XLE   h=20 origin=2026-03-31 heldout_end=2026-04-29 bars=148/148
  ok  B pooled           XLE   h= 5 origin=2026-05-29 heldout_end=2026-06-05 bars=133/133
  ok  B pooled           XLE   h=20 origin=2026-05-29 heldout_end=2026-06-29 bars=148/148
  ok  B pooled           XLE   h= 5 origin=2026-07-31 heldout_end=2026-08-07 bars=133/133
  ok  B pooled           XLE   h=20 origin=2026-07-31 heldout_end=2026-08-28 bars=148/148
  ok  B pooled           XLF   h= 5 origin=2025-09-30 heldout_end=2025-10-07 bars=133/133
  ok  B pooled           XLF   h=20 origin=2025-09-30 heldout_end=2025-10-28 bars=148/148
  ok  B pooled           XLF   h= 5 origin=2025-11-28 heldout_end=2025-12-05 bars=133/133
  ok  B pooled           XLF   h=20 origin=2025-11-28 heldout_end=2025-12-29 bars=148/148
  ok  B pooled           XLF   h= 5 origin=2026-01-30 heldout_end=2026-02-06 bars=133/133
  ok  B pooled           XLF   h=20 origin=2026-01-30 heldout_end=2026-03-02 bars=148/148
  ok  B pooled           XLF   h= 5 origin=2026-03-31 heldout_end=2026-04-08 bars=133/133
  ok  B pooled           XLF   h=20 origin=2026-03-31 heldout_end=2026-04-29 bars=148/148
  ok  B pooled           XLF   h= 5 origin=2026-05-29 heldout_end=2026-06-05 bars=133/133
  ok  B pooled           XLF   h=20 origin=2026-05-29 heldout_end=2026-06-29 bars=148/148
  ok  B pooled           XLF   h= 5 origin=2026-07-31 heldout_end=2026-08-07 bars=133/133
  ok  B pooled           XLF   h=20 origin=2026-07-31 heldout_end=2026-08-28 bars=148/148
  ok  B pooled           XLI   h= 5 origin=2025-09-30 heldout_end=2025-10-07 bars=133/133
  ok  B pooled           XLI   h=20 origin=2025-09-30 heldout_end=2025-10-28 bars=148/148
  ok  B pooled           XLI   h= 5 origin=2025-11-28 heldout_end=2025-12-05 bars=133/133
  ok  B pooled           XLI   h=20 origin=2025-11-28 heldout_end=2025-12-29 bars=148/148
  ok  B pooled           XLI   h= 5 origin=2026-01-30 heldout_end=2026-02-06 bars=133/133
  ok  B pooled           XLI   h=20 origin=2026-01-30 heldout_end=2026-03-02 bars=148/148
  ok  B pooled           XLI   h= 5 origin=2026-03-31 heldout_end=2026-04-08 bars=133/133
  ok  B pooled           XLI   h=20 origin=2026-03-31 heldout_end=2026-04-29 bars=148/148
  ok  B pooled           XLI   h= 5 origin=2026-05-29 heldout_end=2026-06-05 bars=133/133
  ok  B pooled           XLI   h=20 origin=2026-05-29 heldout_end=2026-06-29 bars=148/148
  ok  B pooled           XLI   h= 5 origin=2026-07-31 heldout_end=2026-08-07 bars=133/133
  ok  B pooled           XLI   h=20 origin=2026-07-31 heldout_end=2026-08-28 bars=148/148
  ok  B pooled           XLK   h= 5 origin=2025-09-30 heldout_end=2025-10-07 bars=133/133
  ok  B pooled           XLK   h=20 origin=2025-09-30 heldout_end=2025-10-28 bars=148/148
  ok  B pooled           XLK   h= 5 origin=2025-11-28 heldout_end=2025-12-05 bars=133/133
  ok  B pooled           XLK   h=20 origin=2025-11-28 heldout_end=2025-12-29 bars=148/148
  ok  B pooled           XLK   h= 5 origin=2026-01-30 heldout_end=2026-02-06 bars=133/133
  ok  B pooled           XLK   h=20 origin=2026-01-30 heldout_end=2026-03-02 bars=148/148
  ok  B pooled           XLK   h= 5 origin=2026-03-31 heldout_end=2026-04-08 bars=133/133
  ok  B pooled           XLK   h=20 origin=2026-03-31 heldout_end=2026-04-29 bars=148/148
  ok  B pooled           XLK   h= 5 origin=2026-05-29 heldout_end=2026-06-05 bars=133/133
  ok  B pooled           XLK   h=20 origin=2026-05-29 heldout_end=2026-06-29 bars=148/148
  ok  B pooled           XLK   h= 5 origin=2026-07-31 heldout_end=2026-08-07 bars=133/133
  ok  B pooled           XLK   h=20 origin=2026-07-31 heldout_end=2026-08-28 bars=148/148
  ok  B pooled           XLP   h= 5 origin=2025-09-30 heldout_end=2025-10-07 bars=133/133
  ok  B pooled           XLP   h=20 origin=2025-09-30 heldout_end=2025-10-28 bars=148/148
  ok  B pooled           XLP   h= 5 origin=2025-11-28 heldout_end=2025-12-05 bars=133/133
  ok  B pooled           XLP   h=20 origin=2025-11-28 heldout_end=2025-12-29 bars=148/148
  ok  B pooled           XLP   h= 5 origin=2026-01-30 heldout_end=2026-02-06 bars=133/133
  ok  B pooled           XLP   h=20 origin=2026-01-30 heldout_end=2026-03-02 bars=148/148
  ok  B pooled           XLP   h= 5 origin=2026-03-31 heldout_end=2026-04-08 bars=133/133
  ok  B pooled           XLP   h=20 origin=2026-03-31 heldout_end=2026-04-29 bars=148/148
  ok  B pooled           XLP   h= 5 origin=2026-05-29 heldout_end=2026-06-05 bars=133/133
  ok  B pooled           XLP   h=20 origin=2026-05-29 heldout_end=2026-06-29 bars=148/148
  ok  B pooled           XLP   h= 5 origin=2026-07-31 heldout_end=2026-08-07 bars=133/133
  ok  B pooled           XLP   h=20 origin=2026-07-31 heldout_end=2026-08-28 bars=148/148
  ok  B pooled           XLRE  h= 5 origin=2025-09-30 heldout_end=2025-10-07 bars=133/133
  ok  B pooled           XLRE  h=20 origin=2025-09-30 heldout_end=2025-10-28 bars=148/148
  ok  B pooled           XLRE  h= 5 origin=2025-11-28 heldout_end=2025-12-05 bars=133/133
  ok  B pooled           XLRE  h=20 origin=2025-11-28 heldout_end=2025-12-29 bars=148/148
  ok  B pooled           XLRE  h= 5 origin=2026-01-30 heldout_end=2026-02-06 bars=133/133
  ok  B pooled           XLRE  h=20 origin=2026-01-30 heldout_end=2026-03-02 bars=148/148
  ok  B pooled           XLRE  h= 5 origin=2026-03-31 heldout_end=2026-04-08 bars=133/133
  ok  B pooled           XLRE  h=20 origin=2026-03-31 heldout_end=2026-04-29 bars=148/148
  ok  B pooled           XLRE  h= 5 origin=2026-05-29 heldout_end=2026-06-05 bars=133/133
  ok  B pooled           XLRE  h=20 origin=2026-05-29 heldout_end=2026-06-29 bars=148/148
  ok  B pooled           XLRE  h= 5 origin=2026-07-31 heldout_end=2026-08-07 bars=133/133
  ok  B pooled           XLRE  h=20 origin=2026-07-31 heldout_end=2026-08-28 bars=148/148
  ok  B pooled           XLU   h= 5 origin=2025-09-30 heldout_end=2025-10-07 bars=133/133
  ok  B pooled           XLU   h=20 origin=2025-09-30 heldout_end=2025-10-28 bars=148/148
  ok  B pooled           XLU   h= 5 origin=2025-11-28 heldout_end=2025-12-05 bars=133/133
  ok  B pooled           XLU   h=20 origin=2025-11-28 heldout_end=2025-12-29 bars=148/148
  ok  B pooled           XLU   h= 5 origin=2026-01-30 heldout_end=2026-02-06 bars=133/133
  ok  B pooled           XLU   h=20 origin=2026-01-30 heldout_end=2026-03-02 bars=148/148
  ok  B pooled           XLU   h= 5 origin=2026-03-31 heldout_end=2026-04-08 bars=133/133
  ok  B pooled           XLU   h=20 origin=2026-03-31 heldout_end=2026-04-29 bars=148/148
  ok  B pooled           XLU   h= 5 origin=2026-05-29 heldout_end=2026-06-05 bars=133/133
  ok  B pooled           XLU   h=20 origin=2026-05-29 heldout_end=2026-06-29 bars=148/148
  ok  B pooled           XLU   h= 5 origin=2026-07-31 heldout_end=2026-08-07 bars=133/133
  ok  B pooled           XLU   h=20 origin=2026-07-31 heldout_end=2026-08-28 bars=148/148
  ok  B pooled           XLV   h= 5 origin=2025-09-30 heldout_end=2025-10-07 bars=133/133
  ok  B pooled           XLV   h=20 origin=2025-09-30 heldout_end=2025-10-28 bars=148/148
  ok  B pooled           XLV   h= 5 origin=2025-11-28 heldout_end=2025-12-05 bars=133/133
  ok  B pooled           XLV   h=20 origin=2025-11-28 heldout_end=2025-12-29 bars=148/148
  ok  B pooled           XLV   h= 5 origin=2026-01-30 heldout_end=2026-02-06 bars=133/133
  ok  B pooled           XLV   h=20 origin=2026-01-30 heldout_end=2026-03-02 bars=148/148
  ok  B pooled           XLV   h= 5 origin=2026-03-31 heldout_end=2026-04-08 bars=133/133
  ok  B pooled           XLV   h=20 origin=2026-03-31 heldout_end=2026-04-29 bars=148/148
  ok  B pooled           XLV   h= 5 origin=2026-05-29 heldout_end=2026-06-05 bars=133/133
  ok  B pooled           XLV   h=20 origin=2026-05-29 heldout_end=2026-06-29 bars=148/148
  ok  B pooled           XLV   h= 5 origin=2026-07-31 heldout_end=2026-08-07 bars=133/133
  ok  B pooled           XLV   h=20 origin=2026-07-31 heldout_end=2026-08-28 bars=148/148
  ok  B pooled           XLY   h= 5 origin=2025-09-30 heldout_end=2025-10-07 bars=133/133
  ok  B pooled           XLY   h=20 origin=2025-09-30 heldout_end=2025-10-28 bars=148/148
  ok  B pooled           XLY   h= 5 origin=2025-11-28 heldout_end=2025-12-05 bars=133/133
  ok  B pooled           XLY   h=20 origin=2025-11-28 heldout_end=2025-12-29 bars=148/148
  ok  B pooled           XLY   h= 5 origin=2026-01-30 heldout_end=2026-02-06 bars=133/133
  ok  B pooled           XLY   h=20 origin=2026-01-30 heldout_end=2026-03-02 bars=148/148
  ok  B pooled           XLY   h= 5 origin=2026-03-31 heldout_end=2026-04-08 bars=133/133
  ok  B pooled           XLY   h=20 origin=2026-03-31 heldout_end=2026-04-29 bars=148/148
  ok  B pooled           XLY   h= 5 origin=2026-05-29 heldout_end=2026-06-05 bars=133/133
  ok  B pooled           XLY   h=20 origin=2026-05-29 heldout_end=2026-06-29 bars=148/148
  ok  B pooled           XLY   h= 5 origin=2026-07-31 heldout_end=2026-08-07 bars=133/133
  ok  B pooled           XLY   h=20 origin=2026-07-31 heldout_end=2026-08-28 bars=148/148
Windows: 160 total {'A': 28, 'B': 132}; bar-count problems: 0
Projected runtime at 50s/call: 2.2 h
Projected runtime at 90s/call: 4.0 h
DB facts: {"max_session_date_massive": "2026-10-02", "mtime_utc": "2026-10-02T23:38:31.835336+00:00", "path": "/Users/louisbrailey/signal-forge/data/signalforge.sqlite", "size_bytes": 1393045504}
```
