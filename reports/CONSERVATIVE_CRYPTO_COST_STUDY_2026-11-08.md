# Conservative crypto cost study — 2026-11-08

DESCRIPTIVE, already-seen history. Liquidity UNVALIDATED. No promotion or execution claim.

Protocol commit: `bb8c27ea925d315b15a8c9e8fc64ac98ef608149`. Source: `5df4f5aa73028f836cc25505140f7b70ff37e1ed`.
Protocol revision: `5df4f5aa73028f836cc25505140f7b70ff37e1ed`.
Base: `bb624d7`. Bounded data SHA256: `becc82a484317308523aa45d31cc4d8340c4a4935758bed2b6224f3e0d95d512`.
Local detailed evidence: `/Users/louisbrailey/.codex/worktrees/conservative-crypto-cost-study/signal-forge/.toolkit-runs/conservative-crypto-cost-study/evidence.json`; SHA256 `b7f8f00d7a83d19f345519afe2f65779cb040ddedf2e52097aea251f257802cc`.
Project source pin: `3049892b9dd7a8fe53e37dba9991b4f28e68e6d3dd2b56cef4dce14cde0c28f9`; runtime source pin: `d78a88e5e5bb164325ffdde83b27c95d3ccd7c76e948170b9bcb3b70201b348c`.
Pinned files: 833 tracked checkout files and 2312 runtime files.
Source/runtime pins verified after evaluation and after rendering, before publication: True.

24 portfolio runs, each $10,000; 5% all-in entry allocation, 20% crypto theme,
60% gross, 0.5% trade / 1.5% aggregate modeled all-in stop risk; 10% DD entry halt.
Limits apply at admission; price drift and stop gaps can exceed them afterward.
Maximum passive close exposure: 30.962%; maximum admitted theme/gross: 14.180%.
Maximum observed DD: 6.871%; 0/24 accounts halted entries.
These are admission controls, not continuously enforced exposure ceilings.

Outcome: 12/12 distinct long-only window/cost portfolios had positive
net returns; 12/12 exceeded the exposure-matched basket's point
return. 4/4 followup excess-return intervals include zero.
Parent/variant full-account equality: 12/12 paired comparisons;
0 incomplete schedule groups. 24 runs contain 12 distinct full accounts.
Fully funded buy-and-hold has higher absolute returns in 12/12
comparisons and larger close drawdowns in 12/12 comparisons.
These descriptive comparisons do not establish reliable future excess returns.

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

Finite daily volume rows: 24983/24983 accepted bars. Venue spreads,
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
need not match the variant. Recorded filter-before-scheduling parity: 12/12 cases. No short/futures/margin positions enter any cash account.

## Limitations and interpretation

These are fixed seen-history comparisons, not a strategy search or a new sealed look.
The registered surviving pair lists, earliest available stored bars and historical
quality filters are not a point-in-time exchange universe. Venue spread/depth
measurements, order increments, minimum sizes, impact, queueing, trading
availability and intraday mark paths are unvalidated. Stops can gap beyond reserved
risk. The 10% DD control only halts entries at observed opens/closes; it cannot
guarantee a maximum loss. Zero yield is assumed on idle cash. No guarantee of
positive returns, excess returns, execution capacity or promotion follows.

## Gatekeeper repair and fresh provenance proof

This report supersedes the report at `b53bd00`, which was held for two source/reporting
defects. Repair commit `5df4f5aa73028f836cc25505140f7b70ff37e1ed` derives outcome
counts, parent-account equivalence, distinct-account counts, benchmark return/DD
comparisons and volume coverage from the supplied results. Regressions include
losing variants, losing benchmarks, unequal parent accounts and failed parity.

The runner now requires a fully committed, clean checkout before project imports
and before reading data. Its project manifest covers every tracked file; imported
project modules must resolve to tracked source in this checkout. A separate runtime
manifest covers loaded source/cache files, compiled modules and the Python
executable. Both pins are checked after evaluation and after rendering, before any
evidence/report write. The recorded manifests and digests are in the evidence JSON.
This is a source/runtime provenance check, separate from the coherent mode=ro /
query_only SQLite read transaction and the SQL-bounded data hash.

The original economic protocol remains `bb8c27e`. Its `5df4f5a` amendment adds only
these provenance/publication checks. An AST audit found all 21 study/data/accounting
definitions and fixed parameter assignments identical to `b53bd00`; costs, sizing,
windows, the sealed cutoff and signal rules did not change.

The fresh pinned run completed in **11.9 seconds**. Bounded data, all 24 full
portfolio/benchmark paths, coverage, comparison records and bootstrap intervals
were exactly equal to the held artifact. Independent Decimal arithmetic again
reconciled all **822 saved trade rows**, every book's costs/ending equity and
matched exposure. The source audit checked every recorded project hash directly
against the committed Git blobs, verified both manifest digests and verified every
runtime file hash. The held artifact remains local at
`.toolkit-runs/conservative-crypto-cost-study/evidence-b53-held-abb69535.json`,
SHA256 `abb695351f7eb4555868fe8886fb94f38ae547513ff90dc331d0420f7d2bea21`.

**67 focused tests passed**, including 37 conservative-study tests and the existing
venue/harness tests. Source-guard regressions cover staged/unstaged/untracked and
ignored Python changes, committed helper changes during evaluation or rendering,
changed external runtime files, newly loaded runtime files, and foreign project
imports. Refusal preserves the previous report and publishes no new evidence.
Focused Ruff and Black checks passed.

Local verification logs:

* 67 tests: `.toolkit-runs/20261109T002948.008570Z.log`.
* AST invariance: `.toolkit-runs/20261109T002901.145755Z.log`.
* Fresh pinned run: `.toolkit-runs/20261109T003055.359358Z.log`.
* Independent accounting/source/blob audit:
  `.toolkit-runs/20261109T003145.078500Z.log`.
* Black check: `.toolkit-runs/20261109T003222.280838Z.log`.

Reproduce from a clean, committed checkout (no credentials are needed):

```sh
devkit run -- env PYTHONPATH=src \
  /Users/louisbrailey/Projects/signal-forge/.venv/bin/python \
  scripts/conservative_crypto_cost_study.py \
  /Users/louisbrailey/Projects/signal-forge/data/signalforge.sqlite
```

The report date is the requested study date; the fresh run occurred on
2026-11-09 UTC / 2026-11-08 Pacific. A later database snapshot must match the
bounded-data hash before claiming numerical reproduction. Only the same four
assigned files changed; no canonical writes, provider/broker calls, sealed reads,
paper actions, merge, deployment or CI integration were performed. Gatekeeper
re-review remains separate from this repair and its passing local checks.
