# Results — cross-domain strategy program (pre-registered 2026-11-02)

Pre-registration: `docs/research/PREREGISTRATION_universe_program_2026-11-02.md` (commit
`377c0c2`, written and committed before any of the runs below). All runs 2026-11-02/03 on
scratch copies or read-only against the live database; the live database gained **data
only** (ETF deep history, 10 crypto pairs) and no evaluation, sealed test or approval rows.
Nothing was armed. Sealed years: none consumed. Every number below is development-window
evidence after the shipped cost models.

## 1. Headline

| Family | Universe | Verdict | Key figure |
|---|---|---|---|
| D `crypto_donchian_55_u10` (CRYPTO-2) | 10 crypto pairs vs USD | **DEV_PASS and SEALED_PASS** (+0.693R / 55 on the never-seen year) | OOS +0.574R on 176 trades, CI low +0.134R, 2× costs +0.520R, 7/10 pairs positive; sealed 9/10 pairs positive |
| D `crypto_mom_21_u10` | same | DEV_FAIL (near miss) | +0.115R / 620, CI low −0.052R; 7/10 pairs positive, 2/4 folds |
| D `crypto_tsmom_126_ma50_u10`, `crypto_zfade_20_u10` | same | DEV_FAIL | +0.015R and −0.122R |
| C `fx_mom_21` (FX-3) | 7 majors + gold | DEV_FAIL, as the pre-registration expected | −0.086R / 784, CI low −0.175R, 0/4 folds; only GBP, JPY and gold positive |
| D′ `crypto_mom_21_long_u10` (CRYPTO-3, refinement §7.2) | 10 crypto pairs | DEV_PASS, then **SEALED_FAIL** (−0.062R / 130) — rejected | dev +0.279R / 433, CI low +0.040R; sealed year negative on 7/10 pairs |
| A `tsmom_etf.medium_swing` | 10 ETFs 2016+ / 9 ETFs 2006+ | fails gate 4 (CI) and gate 7 (Sharpe vs SPY); positive expectancy, 100% grid positive | +0.130R / 93 and +0.077R / 224; diagnostic sealed +0.109R / 45 and +0.051R / 40 |
| A2 `tsmom_etf.position` (quarterly hold, §7.1) | same | **fails** gates 4, 7 and the diagnostic sealed window; refinement did not help — family A closed | +0.142R / 61 and +0.213R / 145 (higher per trade, fewer trades); diag. sealed −0.084R / 31 and −0.126R / 29 |
| B `turn_of_month.short_swing` | 6 index ETFs 2016+ / 5 ETFs 2003+ | **reject**: −0.037R on 2016+ (0% grid positive); +0.040R on 2003+ but CI low −0.012R and Sharpe 0.25 vs 0.43 | effect is small and fading; diagnostic sealed +0.052R / 72 and +0.074R / 60 |
| E existing six strategies | sector SPDRs (10); mega-caps (9) | running | |

## 2. Equity ladder runs (`--until 2025-09-07`; gate 9 is a diagnostic window on development data)

**Pipeline fix found by this program (commit `07a91fe`).** Gate 9 used to start the sealed-
window backtest on the window's first day, so a rule with a 12-month lookback scored "0
trades" by construction (first run of A), and every rule lost its first N sessions of the
window. Gate 9 now warms indicators up on 730 days before the window and scores only trades
*entered* inside it. Locked sealed rows are untouched. The A/B numbers below are from the
re-run on a fresh copy (`sfdata6`) with that fix; the first-run numbers for gates 1–8 were
identical, as they must be (gates 1–8 never changed).

### A. `tsmom_etf.medium_swing` v0.1.0

| Universe / window | OOS trades | Expectancy | CI low | Grid | Regimes | Sharpe vs SPY | Diag. sealed (2024-09-07..2025-09-07) | Verdict |
|---|---|---|---|---|---|---|---|---|
| 10 ETFs, 2016-10-17+ | 93 | +0.130R | −0.106R ✗ | 9/9 positive ✓ | bull 194 / bear 13 / range 39 ✓ | 0.44 vs 0.68 ✗ (CAGR 1.4%, vol 3.2%, maxDD 6.3%, 31 trades/yr) | +0.109R / 45 ✓ | fails 4, 7 |
| 9 ETFs (no QQQ), 2006-03-01+ | 224 | +0.077R | −0.067R ✗ | 9/9 positive ✓ | bull 412 / bear 42 / range 123 ✓ | 0.18 vs 0.41 ✗ (maxDD 14.1%) | +0.051R / 40 ✓ | fails 4, 7 |

Reading: the sign is right everywhere (every grid point positive on both windows, both
diagnostic sealed windows positive), but the per-trade edge is small and the fixed-risk,
one-month-hold implementation produces too few trades for the CI gate and too little return
per unit risk to beat SPY's Sharpe. This is the motivation for refinement A2 (quarterly hold).

### A2. `tsmom_etf.position` v0.1.0 (refinement §7.1: same signal, 63-session hold)

| Universe / window | OOS trades | Expectancy | CI low | Grid | Sharpe vs SPY | Diag. sealed | Verdict |
|---|---|---|---|---|---|---|---|
| 10 ETFs, 2016+ | 61 | +0.142R | −0.309R ✗ | 6/9 positive ✓ | 0.57 vs 0.68 ✗ (20 trades/yr) | **−0.084R / 31** ✗ | fails 4, 7, 9 |
| 9 ETFs, 2006+ | 145 | +0.213R | −0.085R ✗ | 8/9 positive ✓ | 0.38 vs 0.41 ✗ | **−0.126R / 29** ✗ | fails 4, 7, 9 |

Reading: the quarterly hold raised expectancy per trade as hypothesised, but it cut the trade
count by a third (CI wider), left the Sharpe below buy-and-hold SPY, and the 2024-09..2025-09
diagnostic window is negative on both universes. The refinement is reported as a failure.
**Family A is closed**: the published diversified-trend result depends on volatility-scaled,
continuously-held exposure across many futures markets, which this fixed-risk, stop-based,
one-position-per-symbol engine cannot express; a third parameterisation would be curve
fitting. No further A variants will be run.

### B. `turn_of_month.short_swing` v0.1.0

| Universe / window | OOS trades | Expectancy | CI low | Grid | Sharpe vs SPY | Diag. sealed | Verdict |
|---|---|---|---|---|---|---|---|
| 6 index ETFs, 2016-10-17+ | 228 | −0.037R ✗ | −0.109R ✗ | 0/9 positive ✗ | 0.77 vs 0.68 ✓ | +0.052R / 72 | **reject** |
| 5 index ETFs (no QQQ), 2003-10-20+ | 505 | +0.040R | −0.012R ✗ | 9/9 positive | 0.25 vs 0.43 ✗ | +0.074R / 60 | fails 4, 7 |

Reading: McConnell–Xu's effect is visible over 2003–2025 (+0.04R per trade, every grid
point positive) but has been absent on 2016+ data and is too small to clear an 11 bps round
trip with confidence. Not refined (pre-registration §7.4).

### E. Existing six strategies on the sector-SPDR and mega-cap universes

_Running on `sfdata5`; filled when complete._

## 3. FX-3 (`fx research --version FX-3`, live DB read-only, report `data/research/fx/fx_research_FX-3_2026-11-02.md`)

Sealed from 2025-11-03 (not evaluated). 8 strategy × pair tests.

| Strategy | Verdict | OOS trades | Expectancy (R) | CI low (R) | 2x-spread (R) | Folds (R) |
|---|---|---|---|---|---|---|
| fx_mom_21 | DEV_FAIL | 784 | -0.086 | -0.175 | -0.095 | -0.02, -0.06, -0.10, -0.15 |

Failed gates: OOS expectancy −0.086R < 0; CI low −0.175R < +0.02R; positive folds 0 < 3;
2×-spread −0.095R < 0; 1 bp/day holding-cost −0.168R < 0; pairs positive 38% < 50%.

| Pair | OOS from | OOS trades | Expectancy (R) | 2x-spread (R) |
|---|---|---|---|---|
| AUDUSD | 2019-07-05 | 103 | -0.204 | -0.211 |
| EURUSD | 2019-06-24 | 101 | -0.099 | -0.106 |
| GBPUSD | 2019-06-24 | 96 | +0.034 | +0.024 |
| NZDUSD | 2019-05-20 | 106 | -0.274 | -0.283 |
| USDCAD | 2019-06-10 | 99 | -0.140 | -0.152 |
| USDCHF | 2019-05-16 | 94 | -0.112 | -0.122 |
| USDJPY | 2019-06-04 | 104 | +0.031 | +0.023 |
| XAUUSD | 2020-08-19 | 81 | +0.132 | +0.120 |

**Disposition: reject.** This matches Menkhoff et al.'s own caveat that the effect is
cross-sectional across many currencies, partly eaten by costs, and absent in majors over
their last decade. Time-series one-month momentum on 8 liquid pairs has no edge here.

## 4. CRYPTO-2 (`crypto research --version CRYPTO-2`, 10 pairs, live DB read-only, report `data/research/crypto/crypto_research_CRYPTO-2_2026-11-02.md`)

Sealed from 2025-11-03 (not evaluated). 40 strategy × pair tests. Costs: BTC 24 / ETH 26 /
SOL 40 bps per side; all other pairs 50 bps per side; 1 bp slippage; 2× stress.

| Strategy | Verdict | OOS trades | Expectancy (R) | CI low (R) | 2x-spread (R) | Folds (R) |
|---|---|---|---|---|---|---|
| crypto_donchian_55_u10 | DEV_PASS | 176 | +0.574 | +0.134 | +0.520 | +0.28, +0.12, +1.84, +0.01 |
| crypto_tsmom_126_ma50_u10 | DEV_FAIL | 190 | +0.015 | -0.192 | -0.012 | -0.07, +0.10, +0.30, -0.26 |
| crypto_zfade_20_u10 | DEV_FAIL | 643 | -0.122 | -0.193 | -0.169 | -0.19, -0.10, -0.09, -0.11 |
| crypto_mom_21_u10 | DEV_FAIL | 620 | +0.115 | -0.052 | +0.074 | +0.11, -0.00, +0.39, -0.04 |

`crypto_donchian_55_u10` per pair:

| Pair | OOS from | OOS trades | Expectancy (R) | 2x-spread (R) |
|---|---|---|---|---|
| ADAUSD | 2022-10-07 | 17 | +0.576 | +0.510 |
| AVAXUSD | 2024-03-31 | 8 | -0.007 | -0.042 |
| BNBUSD | 2020-04-24 | 8 | +3.136 | +3.028 |
| BTCUSD | 2021-07-03 | 26 | +0.703 | +0.652 |
| DOGEUSD | 2022-06-21 | 21 | +0.950 | +0.879 |
| ETHUSD | 2021-10-01 | 24 | +0.857 | +0.812 |
| LINKUSD | 2023-04-19 | 20 | +0.071 | +0.025 |
| LTCUSD | 2022-03-29 | 23 | -0.375 | -0.414 |
| SOLUSD | 2023-12-18 | 11 | +0.305 | +0.265 |
| XRPUSD | 2022-04-26 | 18 | +0.623 | +0.563 |

Honest reading: the pass is real on the pooled gates, but the fold profile (+0.28, +0.12,
**+1.84**, +0.01) and BNB's +3.1R on 8 trades show the result is concentrated in one
crypto bull phase; the fourth fold is flat. Seven of ten pairs are positive, including the
three large ones (BTC +0.70, ETH +0.86, XRP +0.62). `crypto_mom_21_u10` (Liu–Tsyvinski–Wu
one-month momentum) is positive on 7/10 pairs and +0.074R at 2× costs but fails the CI gate.

### CRYPTO-3 — `crypto_mom_21_long_u10` (refinement §7.2, run after ONE look at CRYPTO-2)

| Strategy | Verdict | OOS trades | Expectancy (R) | CI low (R) | 2x-spread (R) | Folds (R) |
|---|---|---|---|---|---|---|
| crypto_mom_21_long_u10 | DEV_PASS | 433 | +0.279 | +0.040 | +0.233 | +0.04, +0.13, +0.76, +0.15 |

| Pair | OOS from | OOS trades | Expectancy (R) | 2x-spread (R) |
|---|---|---|---|---|
| ADAUSD | 2022-10-07 | 46 | +0.297 | +0.244 |
| AVAXUSD | 2024-03-31 | 21 | -0.040 | -0.076 |
| BNBUSD | 2020-04-24 | 21 | +1.567 | +1.492 |
| BTCUSD | 2021-07-03 | 67 | +0.146 | +0.109 |
| DOGEUSD | 2022-06-21 | 46 | +0.529 | +0.476 |
| ETHUSD | 2021-10-01 | 61 | +0.204 | +0.174 |
| LINKUSD | 2023-04-19 | 38 | +0.153 | +0.111 |
| LTCUSD | 2022-03-29 | 51 | -0.134 | -0.175 |
| SOLUSD | 2023-12-18 | 33 | +0.114 | +0.082 |
| XRPUSD | 2022-04-26 | 49 | +0.522 | +0.456 |

Dropping the short leg turns the CRYPTO-2 near miss into a pass on every gate: 8/10 pairs
positive, all four folds positive, +0.233R at double costs. Honest caveats: this is a second
look at the same development data (disclosed in the pre-registration §7); BNB again
contributes an outsized +1.57R on 21 trades; and the sample is a crypto bull market.

### Sealed tests — operator-authorised 2026-11-02 ("Yes, run both"), one look each, live database

| Version / strategy | Sealed window | Trades | Expectancy | 2× costs | Win | Profit factor | Max DD | Verdict |
|---|---|---|---|---|---|---|---|---|
| CRYPTO-2 `crypto_donchian_55_u10` (10 pairs) | 2025-11-03 → 2026-11-02 | 55 | **+0.693R** | +0.627R | 55% | 2.66 | 4.1R | **SEALED_PASS** (`currency_sealed_test` id 2) |
| CRYPTO-3 `crypto_mom_21_long_u10` (10 pairs) | 2025-11-03 → 2026-11-02 | 130 | **−0.062R** | −0.109R | 35% | 0.89 | 13.7R | **SEALED_FAIL** (id 3) — rejected, look spent |

Per pair, sealed year — Donchian: ADA +0.01 (7), AVAX +1.83 (4), BNB +0.78 (3), BTC +0.95 (6),
DOGE +0.33 (5), ETH +0.89 (6), LINK +1.12 (6), LTC −0.19 (6), SOL +0.85 (7), XRP +0.85 (5):
nine of ten pairs positive on data no one had looked at. Momentum: ADA −0.45, AVAX −0.16,
BNB +0.69, BTC +0.07, DOGE −0.18, ETH +0.26, LINK −0.16, LTC −0.06, SOL +0.07, XRP −0.37 —
the development pass (+0.279R on 433 trades, after one refinement look) did not survive the
year it had never seen. That is exactly what the sealed year is for; CRYPTO-3 is closed.

**Disposition:** `crypto_donchian_55_u10` (CRYPTO-2) is the program's one new validated edge
— development +0.574R / 176, sealed +0.693R / 55, both with 2× costs positive — and goes to
the crypto paper book. `crypto_mom_21_long_u10` is rejected. Taking that
look consumes CRYPTO-2's one sealed year for this rule and needs the operator's explicit
authorisation; it is **not** taken by this program. If authorised and passed, the existing
crypto paper book mechanism (currently CRYPTO-1 on 3 pairs, $100 R) is the paper venue.

## 4b. CRYPTO-H2 — the three CRYPTO-H1 hourly rules on 6 pairs (refinement §7.3; live DB read-only, report `data/research/crypto/crypto_hourly_CRYPTO-H2_2026-11-02.md`)

Hourly bars backfilled 2026-11-02 for XRP (2017-01), BNB (2018-08, only 23k bars — Massive's
hourly BNB history is sparse) and DOGE (2017-06). Sealed from 2025-11-04 (not evaluated).

| Strategy | Verdict | OOS trades | Expectancy (R) | CI low (R) | 2x-spread (R) | Folds (R) |
|---|---|---|---|---|---|---|
| crypto_h_donchian168_trail72 | DEV_FAIL | 827 | +0.465 | −0.010 | +0.264 | +0.15, −0.24, +1.82, +0.12 |
| crypto_h_tsmom72_sma168 | DEV_FAIL | 1344 | −0.061 | −0.139 | −0.174 | |
| crypto_h_zfade48 | DEV_FAIL | 3766 | −0.349 | −0.382 | −0.513 | |

Donchian per pair: BNB +2.455R (51), BTC +0.330 (173), DOGE +0.149 (165), ETH +0.598 (162),
SOL +0.127 (90), XRPUSD / 2022-05-04T17:00:00+00:00 / 186 / +0.373 / +0.135.

Reading: the hypothesis was that doubling the trade count would tighten the CI past +0.02R.
It did not — the CI lower bound moved from +0.010R (3 pairs) to −0.010R (6 pairs) because
the added pairs are more dispersed (BNB +2.46R on 51 trades, one fold at +1.82R, one fold
negative). The hourly Donchian is positive at double costs but its edge is too lumpy to
clear the gate. **CRYPTO-H2 fails; the hourly family is closed at this parameterisation.**

## 4c. E — existing six strategies on the sector-SPDR universe (10 symbols, 2003-10-20 → 2025-09-07, `sfdata5`)

Every strategy has positive OOS expectancy and every one fails gate 4 (bootstrap CI):
trend short +0.047R (CI −0.096), trend medium +0.098R (CI −0.053), mean reversion +0.050R
(CI −0.049), relative strength +0.085R (CI −0.136), volatility breakout fails net
expectancy, tsmom_etf.medium_swing +0.064R (CI −0.040), turn_of_month +0.037R (CI +0.003),
tsmom_etf.position +0.198R (CI +0.006). Sector ETFs trend less cleanly than the large-cap
names; nothing passes. The mega-cap universe (9 stocks, 2016+) is still running.

## 5. Not run, and why (from the pre-registration)

Overnight premium (engine fills at next open; cost-dominated), volatility-managed overlay
(sizing, contested OOS), options (no multi-year history on this plan), news (no history; S12).

## 6. Data work this program added to the live database (research tables only)

- `ohlcv_daily`/`massive`: 2003-10-20 → today for SPY, DIA, IWM, EFA, EEM, TLT, IEF and the
  nine sector SPDRs; GLD, VNQ, DBC, USO, SLV from listing (`ingestion_run` #83, #84).
  QQQ pre-2016 unavailable from Massive (runs #84, #85). HYG pre-2007 bars are a different
  security (ticker reuse) — excluded.
- `crypto_bar_daily`: XRP, ADA, DOGE, LTC, LINK, AVAX, DOT, BCH, XLM, BNB vs USD from each
  pair's Massive history start (XRP 2017-01; BNB 2018-08; LINK 2019-06; AVAX 2021-11).
