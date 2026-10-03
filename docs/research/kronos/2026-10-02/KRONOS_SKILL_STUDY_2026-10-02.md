# Kronos forecast-skill study — results (2026-10-02)

> Historical replay only, not advice or a trading instruction. Pretraining overlap is unknown; this is not verified out-of-sample model evaluation. Sampling spread is not a calibrated confidence interval. Price MAE is not investment performance and excludes costs. Persisted adjusted history may include later vendor revisions and corporate actions.

Pre-registration: `PREREGISTRATION_2026-10-03_kronos_skill.md`. Every outcome is reported, including nulls and failures. Nothing here changes any strategy, threshold, risk rule or trade. Research signal only — no order was placed.

## Pre-registered expectations next to outcomes

| Gate | Pre-registered expectation | Outcome |
|---|---|---|
| G2 skill | Null expected: geometric-mean MAE ratio vs drift and vs unchanged near 1 at both horizons; Holm-adjusted p >= 0.05. n=12 is low power, so a true 5% improvement would usually NOT be detected. | h20_mae_ratio_vs_drift: ratio 1.043 CI [0.746, 1.460] p=0.8149 Holm=0.8149 fail<br>h20_mae_ratio_vs_unchanged: ratio 1.338 CI [0.958, 1.869] p=0.0947 Holm=0.3789 fail<br>h5_mae_ratio_vs_drift: ratio 1.246 CI [0.910, 1.707] p=0.1851 Holm=0.4790 fail<br>h5_mae_ratio_vs_unchanged: ratio 1.256 CI [0.916, 1.724] p=0.1597 Holm=0.4790 fail |
| G3 direction | Null expected: horizon-end directional accuracy within binomial noise of 50% and not distinguishable from the drift sign. | h20_direction_end_vs_50pct: 8/12 p=0.3877 BH=0.7744<br>h20_direction_end_vs_drift_sign: model 0.67 vs drift 0.42 p=0.5488 BH=0.7744<br>h5_direction_end_vs_50pct: 7/12 p=0.7744 BH=0.7744<br>h5_direction_end_vs_drift_sign: model 0.58 vs drift 0.42 p=0.6875 BH=0.7744 |
| G4 calibration | Coverage of the 3-sample min-max band near its (n-1)/(n+1) = 50% nominal rate; bands non-degenerate. A clearly lower rate means the spread understates uncertainty. | h20_coverage_end_vs_50pct: 3/12 p=0.1460 BH=0.7744; per-bar 0.31; width/close 0.0205; degenerate=False<br>h5_coverage_end_vs_50pct: 5/12 p=0.7744 BH=0.7744; per-bar 0.43; width/close 0.0162; degenerate=False |
| G5 Tier B pooled | Null expected: Tier B pooled MAE ratio vs drift CI at h=20 includes 1. | h20_mae_ratio_vs_drift: ratio 1.215 CI [0.997, 1.375] (n=66, 6 origin clusters)<br>h20_mae_ratio_vs_unchanged: ratio 1.218 CI [0.996, 1.410] (n=66, 6 origin clusters)<br>h5_mae_ratio_vs_drift: ratio 1.259 CI [1.093, 1.434] (n=66, 6 origin clusters)<br>h5_mae_ratio_vs_unchanged: ratio 1.237 CI [1.079, 1.438] (n=66, 6 origin clusters) |

Per-origin MAE ratios (Tier A primary):

- h20_mae_ratio_vs_drift: 2025-09-30 1.866, 2025-10-31 0.638, 2025-11-28 1.417, 2025-12-31 2.917, 2026-01-30 0.371, 2026-02-27 0.549, 2026-03-31 0.660, 2026-04-30 2.443, 2026-05-29 1.177, 2026-06-30 1.271, 2026-07-31 0.868, 2026-08-31 0.793
- h20_mae_ratio_vs_unchanged: 2025-09-30 2.210, 2025-10-31 1.355, 2025-11-28 3.144, 2025-12-31 1.478, 2026-01-30 0.697, 2026-02-27 0.643, 2026-03-31 0.675, 2026-04-30 2.115, 2026-05-29 1.796, 2026-06-30 1.856, 2026-07-31 0.694, 2026-08-31 1.603
- h5_mae_ratio_vs_drift: 2025-09-30 2.912, 2025-10-31 0.811, 2025-11-28 1.679, 2025-12-31 0.687, 2026-01-30 0.843, 2026-02-27 0.488, 2026-03-31 1.202, 2026-04-30 1.992, 2026-05-29 2.162, 2026-06-30 1.555, 2026-07-31 0.853, 2026-08-31 1.822
- h5_mae_ratio_vs_unchanged: 2025-09-30 1.058, 2025-10-31 1.131, 2025-11-28 2.498, 2025-12-31 0.517, 2026-01-30 1.032, 2026-02-27 0.571, 2026-03-31 1.233, 2026-04-30 1.827, 2026-05-29 2.596, 2026-06-30 1.916, 2026-07-31 0.802, 2026-08-31 1.892

## Exploratory origins (overlap_possible, excluded from every family)

- h20 2025-02-27: ratio vs drift 1.658, vs unchanged 1.849, direction 0
- h20 2025-03-31: ratio vs drift 1.426, vs unchanged 1.380, direction 0
- h5 2025-02-27: ratio vs drift 2.191, vs unchanged 2.350, direction 0
- h5 2025-03-31: ratio vs drift 1.078, vs unchanged 1.072, direction 0

## Tier C (optional, exploratory)


## Failed calls

- none

## Reproducibility

- git SHA: `1533c46568467b77331e137c56a4f4ee42d3bfef`
- database: `/Users/louisbrailey/signal-forge/data/signalforge.sqlite` size 1393045504 bytes, mtime 2026-10-02T23:38:31.835336+00:00, max massive session_date 2026-10-02
- runtime_status(): `{"configuration_only": true, "configured": true, "horizons": [5, 20], "lookback": 128, "mode": "historical_replay", "model": "NeoQuasar/Kronos-small", "notice": "Historical replay only, not advice or a trading instruction. Pretraining overlap is unknown; this is not verified out-of-sample model evaluation. Sampling spread is not a calibrated confidence interval. Price MAE is not investment performance and excludes costs. Persisted adjusted history may include later vendor revisions and corporate actions.", "offline": true}`
- model: `NeoQuasar/Kronos-small`, seed 42, samples 3, lookback 128
- `models--NeoQuasar--Kronos-small` snapshots ['901c26c1332695a2a8f243eb2f37243a37bea320']: combined weights sha256 `14d3cff2b1da9f5fecded00104daeffbf8411ff25b105326f39bdcb0e7eb6b55`
  - `901c26c1332695a2a8f243eb2f37243a37bea320/config.json`: `5e0f6a605d5f81b5c9b559fe5cf716a1acb041c744e6f41bd05b097b7a685396`
  - `901c26c1332695a2a8f243eb2f37243a37bea320/model.safetensors`: `b082dfcbd8e8c142a725c8bbb99781802f38fec81210e13479effb32b3c3e020`
  - model-card data-cutoff line: not present in cached README
- `models--NeoQuasar--Kronos-Tokenizer-base` snapshots ['0e0117387f39004a9016484a186a908917e22426']: combined weights sha256 `0e5480473463f074d77fe0eb83e736330a5bda4e28d1daa5a5689e58e598708b`
  - `0e0117387f39004a9016484a186a908917e22426/config.json`: `2366e7ccfec76cbc19cf3c4c1b9c5d901be336ca1e83f2d2292c9bff381b77a2`
  - `0e0117387f39004a9016484a186a908917e22426/model.safetensors`: `59d85f6af76a2c3b8240ea06cb21db4213b4eeca053f246b23e29cf832fc6bee`
  - model-card data-cutoff line: not present in cached README
- calls analysed: 160; regenerate with `scripts/kronos_skill_study.py report`
