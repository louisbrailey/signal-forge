# Conservative crypto cost study — 2026-11-08

DESCRIPTIVE, already-seen history. Liquidity UNVALIDATED. No promotion or execution claim.

Protocol commit: `bb8c27ea925d315b15a8c9e8fc64ac98ef608149`. Source: `3613e97064bce9dd058764b959be92f8c441b0b5`.
Base: `bb624d7`. Bounded data SHA256: `becc82a484317308523aa45d31cc4d8340c4a4935758bed2b6224f3e0d95d512`.
Local detailed evidence: `/Users/louisbrailey/.codex/worktrees/conservative-crypto-cost-study/signal-forge/.toolkit-runs/conservative-crypto-cost-study/evidence.json`; SHA256 `abb695351f7eb4555868fe8886fb94f38ae547513ff90dc331d0420f7d2bea21`.

24 fixed portfolio runs, each $10,000; 5% all-in entry allocation, 20% crypto theme,
60% gross, 0.5% trade / 1.5% aggregate modeled all-in stop risk; 10% DD entry halt.
Limits apply at admission; price drift and stop gaps can exceed them afterward.

The 20% theme limit is an admission limit in this protocol, not continuous
rebalancing: maximum passive close exposure reached **30.962%** in the nine-pair
2021–23 base account. Maximum admitted theme/gross was **14.180%**. Largest
observed portfolio DD was **6.871%**; no account activated the 10% entry halt.
These results do not establish compliance with a continuously enforced 20% cap.

Outcome: 12/12 distinct long-only window/cost portfolios had positive
net returns; 12/12 exceeded the exposure-matched basket's point
return. 4/4 followup excess-return intervals include zero.
Every parent LONG-leg schedule and full account path equals its CRYPTO-5 variant here:
24 runs represent 12 distinct accounts, not 24 independent confirmations.
Fully funded buy-and-hold has higher absolute returns in every comparison and much
larger drawdowns. Conservative sizing reduces losses; it does not remove cost drag
or establish reliable future excess returns.

Costs: base Coinbase Intro 90 bps taker + estimated half-spread (BTC 2, ETH 3,
SOL 10, other pairs 15 bps) + 1 bp slippage, each side. Stress doubles fee and
half-spread; the separate 1 bp slip stays fixed (harness convention).

## Data and coverage

One SQLite mode=ro, query_only transaction, exact massive_crypto rows, SQL-bounded
2016-01-01 <= date < 2025-10-26. No sealed bars fetched, providers called, operating
writes, paper trades, alerts, or study updates. 2016 context is warmup only.

Quality: recorded_flags_only. Simulation: UNKNOWN: no explicit simulation field.
Source identifies stored Massive data; it does not establish historical venue listing,
point-in-time universe membership, measured depth/spreads or execution capacity.

| Pair | Bounded selected/accepted rows | First–last accepted | Finite/positive volume rows | Excluded |
|---|---:|---|---:|---|
| ADAUSD | 2799/2799 | 2018-02-26–2025-10-25 | 2799/2799 | {} |
| AVAXUSD | 1446/1446 | 2021-11-10–2025-10-25 | 1446/1446 | {} |
| BTCUSD | 3586/3586 | 2016-01-01–2025-10-25 | 3586/3586 | {} |
| DOGEUSD | 3069/3069 | 2017-06-01–2025-10-25 | 3069/3069 | {} |
| ETHUSD | 3586/3586 | 2016-01-01–2025-10-25 | 3586/3586 | {} |
| LINKUSD | 2312/2312 | 2019-06-27–2025-10-25 | 2312/2312 | {} |
| LTCUSD | 3277/3277 | 2016-11-04–2025-10-25 | 3277/3277 | {} |
| SOLUSD | 1703/1703 | 2021-02-25–2025-10-25 | 1703/1703 | {} |
| XRPUSD | 3205/3205 | 2017-01-03–2025-10-25 | 3205/3205 | {} |

| Window | Pair | Actual/expected days | Longest gap | Admission / gaps |
|---|---|---:|---:|---|
| development | ADAUSD | 1040/1040 | 0 | within continuity policy; [] |
| development | AVAXUSD | 0/0 | 0 | not yet incepted; [] |
| development | BTCUSD | 1461/1461 | 0 | within continuity policy; [] |
| development | DOGEUSD | 1310/1310 | 0 | within continuity policy; [] |
| development | ETHUSD | 1461/1461 | 0 | within continuity policy; [] |
| development | LINKUSD | 554/554 | 0 | within continuity policy; [] |
| development | LTCUSD | 1461/1461 | 0 | within continuity policy; [] |
| development | SOLUSD | 0/0 | 0 | not yet incepted; [] |
| development | XRPUSD | 1447/1459 | 7 | within continuity policy; [['2017-01-04', '2017-01-08'], ['2017-01-10', '2017-01-16']] |
| validation_SEEN | ADAUSD | 1095/1095 | 0 | within continuity policy; [] |
| validation_SEEN | AVAXUSD | 782/782 | 0 | within continuity policy; [] |
| validation_SEEN | BTCUSD | 1095/1095 | 0 | within continuity policy; [] |
| validation_SEEN | DOGEUSD | 1095/1095 | 0 | within continuity policy; [] |
| validation_SEEN | ETHUSD | 1095/1095 | 0 | within continuity policy; [] |
| validation_SEEN | LINKUSD | 1095/1095 | 0 | within continuity policy; [] |
| validation_SEEN | LTCUSD | 1095/1095 | 0 | within continuity policy; [] |
| validation_SEEN | SOLUSD | 1040/1040 | 0 | within continuity policy; [] |
| validation_SEEN | XRPUSD | 1095/1095 | 0 | within continuity policy; [] |
| followup_SEEN | ADAUSD | 664/664 | 0 | within continuity policy; [] |
| followup_SEEN | AVAXUSD | 664/664 | 0 | within continuity policy; [] |
| followup_SEEN | BTCUSD | 664/664 | 0 | within continuity policy; [] |
| followup_SEEN | DOGEUSD | 664/664 | 0 | within continuity policy; [] |
| followup_SEEN | ETHUSD | 664/664 | 0 | within continuity policy; [] |
| followup_SEEN | LINKUSD | 663/664 | 1 | within continuity policy; [['2025-03-25', '2025-03-25']] |
| followup_SEEN | LTCUSD | 663/664 | 1 | within continuity policy; [['2025-03-25', '2025-03-25']] |
| followup_SEEN | SOLUSD | 663/664 | 1 | within continuity policy; [['2025-03-25', '2025-03-25']] |
| followup_SEEN | XRPUSD | 663/664 | 1 | within continuity policy; [['2025-03-25', '2025-03-25']] |

Stored daily volume is present for all accepted bars in this snapshot. Venue spreads,
depth and market impact were not measured: liquidity remains UNVALIDATED.
Not-yet-incepted symbols have zero expected days, rather than a continuity failure.

Warmup resets signal eligibility after any gap; entries require the next actual
calendar open. No synthetic bars. Missing holding marks use the last real close
for accounting only and block entries; exits still follow the harness's surviving
bars, so missing-interval stop paths remain unknown. Each window starts flat, with
no carry-in; harness EOD exits liquidate at the last actual window close.

| Window/rule | First eligible actual benchmark opens (after warmup) |
|---|---|
| development/crypto_donchian_55_long | BTCUSD 2017-01-02, ETHUSD 2017-01-02 |
| development/crypto_donchian_55_u10_long | ADAUSD 2018-04-25, BTCUSD 2017-01-02, DOGEUSD 2017-07-29, ETHUSD 2017-01-02, LINKUSD 2019-08-24, LTCUSD 2017-01-02, XRPUSD 2017-03-16 |
| validation_SEEN/crypto_donchian_55_long | BTCUSD 2021-01-02, ETHUSD 2021-01-02, SOLUSD 2021-04-24 |
| validation_SEEN/crypto_donchian_55_u10_long | ADAUSD 2021-01-02, AVAXUSD 2022-01-07, BTCUSD 2021-01-02, DOGEUSD 2021-01-02, ETHUSD 2021-01-02, LINKUSD 2021-01-02, LTCUSD 2021-01-02, SOLUSD 2021-04-24, XRPUSD 2021-01-02 |
| followup_SEEN/crypto_donchian_55_long | BTCUSD 2024-01-02, ETHUSD 2024-01-02, SOLUSD 2024-01-02 |
| followup_SEEN/crypto_donchian_55_u10_long | ADAUSD 2024-01-02, AVAXUSD 2024-01-02, BTCUSD 2024-01-02, DOGEUSD 2024-01-02, ETHUSD 2024-01-02, LINKUSD 2024-01-02, LTCUSD 2024-01-02, SOLUSD 2024-01-02, XRPUSD 2024-01-02 |

## Results

D = 2017–20 development; V = 2021–23 validation (SEEN); F = 2024–2025-10-25
followup (SEEN). P = actual parent schedule's LONG legs; L = registered long-only
variant. 3/9 identifies the registered pair list, before coverage exclusions.

B&H reserves equal initial sleeves, admits after inception/warmup and holds to
window end. It is an unmanaged fully funded reference with different risk limits.
Matched holds the same sleeves plus cash, fitted to average realized close exposure;
it is an ex-post normalization, not a forecast. All benchmarks pay both-side costs.

| Window | Rule/schedule | Cost | Net % | Cost $ | Close/observed DD % | Mean/max exposure % | Trades/candidates | B&H % / DD % | Matched % / DD % |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| D | 3P | 1x | 28.931 | 251.57 | 3.806/3.851 | 1.77/17.58 | 30/34 | 5743.71/92.62 | 4.816/6.558 |
| D | 3L | 1x | 28.931 | 251.57 | 3.806/3.851 | 1.77/17.58 | 30/34 | 5743.71/92.62 | 4.816/6.558 |
| D | 3P | 2x | 23.807 | 436.50 | 3.595/3.681 | 1.59/15.28 | 30/34 | 5636.28/92.62 | 4.253/5.892 |
| D | 3L | 2x | 23.807 | 436.50 | 3.595/3.681 | 1.59/15.28 | 30/34 | 5636.28/92.62 | 4.253/5.892 |
| D | 9P | 1x | 40.980 | 404.53 | 4.381/4.384 | 2.48/17.89 | 51/80 | 2563.40/92.67 | 3.927/11.716 |
| D | 9L | 1x | 40.980 | 404.53 | 4.381/4.384 | 2.48/17.89 | 51/80 | 2563.40/92.67 | 3.927/11.716 |
| D | 9P | 2x | 31.895 | 698.80 | 4.322/4.325 | 2.23/16.33 | 50/80 | 2512.04/92.67 | 3.486/10.644 |
| D | 9L | 2x | 31.895 | 698.80 | 4.322/4.325 | 2.23/16.33 | 50/80 | 2512.04/92.67 | 3.486/10.644 |
| V | 3P | 1x | 14.788 | 253.05 | 2.587/2.605 | 2.92/16.06 | 32/35 | 138.24/84.76 | 2.222/6.546 |
| V | 3L | 1x | 14.788 | 253.05 | 2.587/2.605 | 2.92/16.06 | 32/35 | 138.24/84.76 | 2.222/6.546 |
| V | 3P | 2x | 11.342 | 447.70 | 2.666/2.731 | 2.69/15.57 | 33/35 | 133.74/84.75 | 1.999/6.061 |
| V | 3L | 2x | 11.342 | 447.70 | 2.666/2.731 | 2.69/15.57 | 33/35 | 133.74/84.75 | 1.999/6.061 |
| V | 9P | 1x | 44.596 | 455.74 | 6.864/6.871 | 3.98/30.96 | 49/97 | 241.44/88.89 | 2.457/13.196 |
| V | 9L | 1x | 44.596 | 455.74 | 6.864/6.871 | 3.98/30.96 | 49/97 | 241.44/88.89 | 2.457/13.196 |
| V | 9P | 2x | 35.875 | 780.62 | 6.346/6.353 | 3.58/28.74 | 48/97 | 234.49/88.89 | 2.160/11.999 |
| V | 9L | 2x | 35.875 | 780.62 | 6.346/6.353 | 3.58/28.74 | 48/97 | 234.49/88.89 | 2.160/11.999 |
| F | 3P | 1x | 6.263 | 147.81 | 2.664/2.664 | 3.23/13.80 | 16/19 | 95.31/46.18 | 2.032/1.957 |
| F | 3L | 1x | 6.263 | 147.81 | 2.664/2.664 | 3.23/13.80 | 16/19 | 95.31/46.18 | 2.032/1.957 |
| F | 3P | 2x | 4.644 | 266.69 | 2.808/2.809 | 3.01/13.68 | 16/19 | 91.65/46.18 | 1.834/1.822 |
| F | 3L | 2x | 4.644 | 266.69 | 2.808/2.809 | 3.01/13.68 | 16/19 | 91.65/46.18 | 1.834/1.822 |
| F | 9P | 1x | 7.911 | 241.96 | 4.741/4.744 | 4.22/20.91 | 28/53 | 76.43/51.87 | 2.267/3.579 |
| F | 9L | 1x | 7.911 | 241.96 | 4.741/4.744 | 4.22/20.91 | 28/53 | 76.43/51.87 | 2.267/3.579 |
| F | 9P | 2x | 4.929 | 420.71 | 4.893/4.895 | 3.78/18.45 | 28/53 | 72.89/51.87 | 1.955/3.218 |
| F | 9L | 2x | 4.929 | 420.71 | 4.893/4.895 | 3.78/18.45 | 28/53 | 72.89/51.87 | 1.955/3.218 |

| Distinct variant window/rule/cost | Ending equity $ | Losing trades / total | Total losing P&L $ | Largest trade loss $ |
|---|---:|---:|---:|---:|
| development/crypto_donchian_55_long/1x | 12893.12 | 16/30 | -878.42 | -60.66 |
| development/crypto_donchian_55_long/2x | 12380.71 | 17/30 | -832.78 | -58.92 |
| development/crypto_donchian_55_u10_long/1x | 14098.03 | 32/51 | -1639.25 | -70.25 |
| development/crypto_donchian_55_u10_long/2x | 13189.51 | 33/50 | -1602.75 | -65.89 |
| validation_SEEN/crypto_donchian_55_long/1x | 11478.84 | 18/32 | -745.74 | -53.97 |
| validation_SEEN/crypto_donchian_55_long/2x | 11134.22 | 17/33 | -739.26 | -55.68 |
| validation_SEEN/crypto_donchian_55_u10_long/1x | 14459.61 | 29/49 | -1335.89 | -69.40 |
| validation_SEEN/crypto_donchian_55_u10_long/2x | 13587.52 | 29/48 | -1325.60 | -67.86 |
| followup_SEEN/crypto_donchian_55_long/1x | 10626.29 | 8/16 | -372.43 | -53.30 |
| followup_SEEN/crypto_donchian_55_long/2x | 10464.36 | 8/16 | -383.54 | -52.51 |
| followup_SEEN/crypto_donchian_55_u10_long/1x | 10791.07 | 18/28 | -820.92 | -54.67 |
| followup_SEEN/crypto_donchian_55_u10_long/2x | 10492.89 | 18/28 | -830.14 | -53.21 |

## Accounting and uncertainty

| Window/rule/schedule/cost | Fee/spread/slip $ | Min cash $ | Turnover / initial equity | Halt | Skips | Annual mean excess 90% interval, pp |
|---|---:|---:|---:|---|---|---:|
| development/crypto_donchian_55_long/parent_long_legs/1x | 242.31/6.57/2.69 | 8927.16 | 2.692 | None | {'cash_or_cap_or_risk': 4} | [1.260, 10.300] |
| development/crypto_donchian_55_long/variant/1x | 242.31/6.57/2.69 | 8927.16 | 2.692 | None | {'cash_or_cap_or_risk': 4} | [1.260, 10.300] |
| development/crypto_donchian_55_long/parent_long_legs/2x | 422.74/11.41/2.35 | 9062.07 | 2.349 | None | {'cash_or_cap_or_risk': 4} | [0.790, 8.748] |
| development/crypto_donchian_55_long/variant/2x | 422.74/11.41/2.35 | 9062.07 | 2.349 | None | {'cash_or_cap_or_risk': 4} | [0.790, 8.748] |
| development/crypto_donchian_55_u10_long/parent_long_legs/1x | 370.11/30.31/4.11 | 8927.16 | 4.112 | None | {'cash_or_cap_or_risk': 29} | [2.898, 13.297] |
| development/crypto_donchian_55_u10_long/variant/1x | 370.11/30.31/4.11 | 8927.16 | 4.112 | None | {'cash_or_cap_or_risk': 29} | [2.898, 13.297] |
| development/crypto_donchian_55_u10_long/parent_long_legs/2x | 641.95/53.28/3.57 | 9062.07 | 3.566 | None | {'cash_or_cap_or_risk': 30} | [1.868, 10.965] |
| development/crypto_donchian_55_u10_long/variant/2x | 641.95/53.28/3.57 | 9062.07 | 3.566 | None | {'cash_or_cap_or_risk': 30} | [1.868, 10.965] |
| validation_SEEN/crypto_donchian_55_long/parent_long_legs/1x | 240.09/10.29/2.67 | 9247.35 | 2.668 | None | {'cash_or_cap_or_risk': 3} | [0.516, 8.065] |
| validation_SEEN/crypto_donchian_55_long/variant/1x | 240.09/10.29/2.67 | 9247.35 | 2.668 | None | {'cash_or_cap_or_risk': 3} | [0.516, 8.065] |
| validation_SEEN/crypto_donchian_55_long/parent_long_legs/2x | 427.57/17.75/2.38 | 9117.35 | 2.375 | None | {'cash_or_cap_or_risk': 2} | [-0.155, 6.639] |
| validation_SEEN/crypto_donchian_55_long/variant/2x | 427.57/17.75/2.38 | 9117.35 | 2.375 | None | {'cash_or_cap_or_risk': 2} | [-0.155, 6.639] |
| validation_SEEN/crypto_donchian_55_u10_long/parent_long_legs/1x | 411.25/39.93/4.57 | 9338.19 | 4.569 | None | {'cash_or_cap_or_risk': 48} | [0.235, 26.503] |
| validation_SEEN/crypto_donchian_55_u10_long/variant/1x | 411.25/39.93/4.57 | 9338.19 | 4.569 | None | {'cash_or_cap_or_risk': 48} | [0.235, 26.503] |
| validation_SEEN/crypto_donchian_55_u10_long/parent_long_legs/2x | 708.91/67.77/3.94 | 9405.20 | 3.938 | None | {'cash_or_cap_or_risk': 49} | [-0.569, 23.216] |
| validation_SEEN/crypto_donchian_55_u10_long/variant/2x | 708.91/67.77/3.94 | 9405.20 | 3.938 | None | {'cash_or_cap_or_risk': 49} | [-0.569, 23.216] |
| followup_SEEN/crypto_donchian_55_long/parent_long_legs/1x | 139.96/6.29/1.56 | 8912.19 | 1.555 | None | {'cash_or_cap_or_risk': 3} | [-1.049, 6.238] |
| followup_SEEN/crypto_donchian_55_long/variant/1x | 139.96/6.29/1.56 | 8912.19 | 1.555 | None | {'cash_or_cap_or_risk': 3} | [-1.049, 6.238] |
| followup_SEEN/crypto_donchian_55_long/parent_long_legs/2x | 254.10/11.18/1.41 | 8910.55 | 1.412 | None | {'cash_or_cap_or_risk': 3} | [-1.669, 5.225] |
| followup_SEEN/crypto_donchian_55_long/variant/2x | 254.10/11.18/1.41 | 8910.55 | 1.412 | None | {'cash_or_cap_or_risk': 3} | [-1.669, 5.225] |
| followup_SEEN/crypto_donchian_55_u10_long/parent_long_legs/1x | 218.65/20.87/2.43 | 8602.67 | 2.429 | None | {'cash_or_cap_or_risk': 25} | [-2.674, 11.094] |
| followup_SEEN/crypto_donchian_55_u10_long/variant/1x | 218.65/20.87/2.43 | 8602.67 | 2.429 | None | {'cash_or_cap_or_risk': 25} | [-2.674, 11.094] |
| followup_SEEN/crypto_donchian_55_u10_long/parent_long_legs/2x | 382.79/35.79/2.13 | 8711.19 | 2.127 | None | {'cash_or_cap_or_risk': 25} | [-3.557, 8.840] |
| followup_SEEN/crypto_donchian_55_u10_long/variant/2x | 382.79/35.79/2.13 | 8711.19 | 2.127 | None | {'cash_or_cap_or_risk': 25} | [-3.557, 8.840] |

Maximum admission ratios across all runs: `{'allocation': 0.05, 'theme': 0.14180266404217953, 'gross': 0.14180266404217953, 'trade_risk': 0.005, 'open_risk': 0.015}`.
Stale held-position days: 0.
Gross and theme are identical for a crypto-only book. Exposure is calendar close
gross/equity, so same-day round trips contribute costs and trades but no close exposure.
Observed DD includes available portfolio opens and closes; benchmark DD uses closes.
Ending equity is $10,000 × (1 + net return / 100); exact values are in local evidence.
Daily curves, all closed trades, admission audits, exact eligibility and rejected
candidate reasons are in the hashed local JSON evidence.

Uncertainty uses 500 paired circular 20-day block resamples, seed 20261108,
365-day annualization. Intervals describe mean daily excess over the matched
benchmark, not compounded return differences or independent OOS confidence.

## Parent comparison

| Window/rule/cost | Parent LONG / variant candidates | Same schedule | Filter-before-scheduling parity |
|---|---:|---|---|
| development/crypto_donchian_55_long/1x | 34/34 | True | True |
| development/crypto_donchian_55_long/2x | 34/34 | True | True |
| development/crypto_donchian_55_u10_long/1x | 80/80 | True | True |
| development/crypto_donchian_55_u10_long/2x | 80/80 | True | True |
| validation_SEEN/crypto_donchian_55_long/1x | 35/35 | True | True |
| validation_SEEN/crypto_donchian_55_long/2x | 35/35 | True | True |
| validation_SEEN/crypto_donchian_55_u10_long/1x | 97/97 | True | True |
| validation_SEEN/crypto_donchian_55_u10_long/2x | 97/97 | True | True |
| followup_SEEN/crypto_donchian_55_long/1x | 19/19 | True | True |
| followup_SEEN/crypto_donchian_55_long/2x | 19/19 | True | True |
| followup_SEEN/crypto_donchian_55_u10_long/1x | 53/53 | True | True |
| followup_SEEN/crypto_donchian_55_u10_long/2x | 53/53 | True | True |

A two-sided parent's short can block a later long; its funded LONG legs therefore
need not match the variant. Removing shorts at signal time reproduces CRYPTO-5
exactly. No short/futures/margin positions enter any cash account.

## Limitations and interpretation

These are fixed seen-history comparisons, not a strategy search or a new sealed look.
The registered surviving pair lists, earliest available stored bars and historical
quality filters are not a point-in-time exchange universe. Venue spread/depth
measurements, order increments, minimum sizes, impact, queueing, trading
availability and intraday mark paths are unvalidated. Stops can gap beyond reserved
risk. The 10% DD control only halts entries at observed opens/closes; it cannot
guarantee a maximum loss. Zero yield is assumed on idle cash. No guarantee of
positive returns, excess returns, execution capacity or promotion follows.

## Verification and run provenance

Only the four assigned new files changed on isolated branch
`codex/conservative-crypto-cost-study-20261108`, based on `bb624d7`.
The protocol was committed as `bb8c27e` before the first bar evaluation.
Implementation `442242d` ran the fixed study successfully. Reporting correction
`3613e97` then distinguished pre-inception dates from missing data and expanded
the report, with no parameter, rule, sizing or accounting change. The same fixed
study was repeated once to verify that correction: the bounded source metadata,
all 24 complete portfolio/benchmark paths, trades, admission audits and bootstrap
intervals were **exactly unchanged**. Both raw evidence files remain local:

* First run: `.toolkit-runs/conservative-crypto-cost-study/evidence-first-run-b62999df.json`,
  SHA256 `b62999df49efa12a28debe231520dd04bc4f572a0551cdd2f49fbd928cbd2787`.
* Final run: the evidence file and SHA256 at the top of this report.

Tests: **51 passed** across the new accounting suite (21), existing crypto venue
tests and existing FX harness tests. After the reporting correction, all 21 new
tests passed again. Focused Ruff and Black checks passed. The independent
saved-trade audit used literal Coinbase fee/half-spread rates and Decimal
arithmetic to reconcile every trade, total costs and ending equity, enforce all
admission maxima/nonnegative cash, verify matched exposure and confirm complete
parent/variant account equality. No local Qwen answers were used.

Local full verification logs:

* Focused 51-test run: `.toolkit-runs/20261109T000623.396223Z.log`.
* Post-correction 21-test run: `.toolkit-runs/20261109T000917.515544Z.log`.
* Final fixed study: `.toolkit-runs/20261109T000932.502168Z.log` (4.1 seconds).
* Independent reconciliation and unchanged-path check:
  `.toolkit-runs/20261109T001011.397661Z.log`.

The report is dated for the requested study; actual run timestamps were
2026-11-09 UTC / 2026-11-08 Pacific. A new invocation reads the current bounded
database snapshot and must compare its data hash before claiming reproduction:

```sh
PYTHONPATH=src /Users/louisbrailey/Projects/signal-forge/.venv/bin/python \
  scripts/conservative_crypto_cost_study.py \
  /Users/louisbrailey/Projects/signal-forge/data/signalforge.sqlite
```

No merge, deployment or CI integration was performed; those remain Main's scope.
