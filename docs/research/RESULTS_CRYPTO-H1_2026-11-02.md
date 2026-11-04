# Results — CRYPTO-H1 hourly round (2026-11-02)

Pre-registration: `PREREGISTRATION_CRYPTO-H1_2026-10-27.md` (commit 9365023). Hourly bars were ingested for the first time on 2026-11-02 (`signalforge data crypto-hourly-ingest --since 2017-01-01`: BTC 86,229 + ETH 86,229 + SOL 49,812 bars, 24 missing SOL hours, 0 failed months). Evaluation: `signalforge crypto research-hourly`, live database read-only; generated report copied below verbatim from `data/research/crypto/crypto_hourly_CRYPTO-H1_2026-11-02.md`.

## Disposition (pre-registered: a failing rule is reported, with no variants)

- `crypto_h_donchian168_trail72` fails exactly one gate: bootstrap CI low +0.010R against the +0.02R floor. Expectancy +0.39R on 425 OOS trades, 4/4 folds positive, +0.22R at 2x costs, 3/3 pairs positive (SOL −0.02R at 2x). This is the closest miss in the programme; under the pre-registration it gets no sealed test and no paper book. Any follow-up (more pairs, or waiting for more data) is a new pre-registration.
- `crypto_h_tsmom72_sma168` and `crypto_h_zfade48` fail clearly (−0.06R and −0.34R). The hourly mean-reversion rule is the worst result in the system: 2,044 trades paying hourly costs.

---

# Crypto (hourly) research report — strategies CRYPTO-H1

Sealed from 2025-11-03T20:00:00+00:00 (not evaluated). Tests run: 9 (strategy x pair).

| Strategy | Verdict | OOS trades | Expectancy (R) | CI low (R) | 2x-spread (R) | Folds (R) |
|---|---|---|---|---|---|---|
| crypto_h_donchian168_trail72 | DEV_FAIL | 425 | +0.390 | +0.010 | +0.222 | +0.78, +0.17, +0.62, +0.05 |
| crypto_h_tsmom72_sma168 | DEV_FAIL | 715 | -0.055 | -0.154 | -0.149 | -0.10, -0.08, +0.05, -0.07 |
| crypto_h_zfade48 | DEV_FAIL | 2044 | -0.337 | -0.380 | -0.485 | -0.33, -0.36, -0.37, -0.29 |

## crypto_h_donchian168_trail72

Close beyond the prior 168h high/low; 2xATR(24) stop; exit on a close back through the prior 72h channel; 720h safety stop.

- bootstrap CI low 0.010R < 0.02R

| Pair | OOS from | OOS trades | Expectancy (R) | 2x-spread (R) |
|---|---|---|---|---|
| BTCUSD | 2022-04-22T07:00:00+00:00 | 173 | +0.330 | +0.153 |
| ETHUSD | 2022-04-22T07:00:00+00:00 | 162 | +0.598 | +0.428 |
| SOLUSD | 2023-12-19T06:00:00+00:00 | 90 | +0.129 | -0.017 |

## crypto_h_tsmom72_sma168

Close crosses SMA(168) in the direction of the 72h return; 3xATR(24) stop; 48h time stop.

- OOS expectancy -0.055R < 0.0R
- bootstrap CI low -0.154R < 0.02R
- positive OOS folds 1 < 3
- 2x-spread expectancy -0.149R < 0.0R
- pairs with positive OOS expectancy 33% < 50%

| Pair | OOS from | OOS trades | Expectancy (R) | 2x-spread (R) |
|---|---|---|---|---|
| BTCUSD | 2022-04-22T07:00:00+00:00 | 279 | -0.056 | -0.156 |
| ETHUSD | 2022-04-22T07:00:00+00:00 | 288 | -0.088 | -0.174 |
| SOLUSD | 2023-12-19T06:00:00+00:00 | 148 | +0.009 | -0.089 |

## crypto_h_zfade48

Fade a close 2.5 standard deviations from its 48h mean; target the mean; 1.5xATR(24) stop; 12h time stop.

- OOS expectancy -0.337R < 0.0R
- bootstrap CI low -0.380R < 0.02R
- positive OOS folds 0 < 3
- 2x-spread expectancy -0.485R < 0.0R
- pairs with positive OOS expectancy 0% < 50%

| Pair | OOS from | OOS trades | Expectancy (R) | 2x-spread (R) |
|---|---|---|---|---|
| BTCUSD | 2022-04-22T07:00:00+00:00 | 859 | -0.340 | -0.499 |
| ETHUSD | 2022-04-22T07:00:00+00:00 | 805 | -0.359 | -0.496 |
| SOLUSD | 2023-12-19T06:00:00+00:00 | 380 | -0.282 | -0.427 |

Development-window research only. Sealed final year not evaluated. Spot-style costs; no funding or exchange risk modelled. No order was placed.
