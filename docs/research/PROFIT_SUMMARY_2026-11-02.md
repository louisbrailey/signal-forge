# Historical profit illustrations — corrected 2026-11-02

**The earlier $300–$1,100 monthly portfolio forecasts are withdrawn.** These numbers
are retrospective arithmetic from independent trade lists. No capital-constrained
portfolio replay establishes a monthly income expectation. CRYPTO-2 is held against
new paper entries because its BNB data are incomplete; its locked pass is preserved
as historical evidence of the deficient test, not proof of a tradable edge.

## Method and limits

- Fixed hypothetical risk is $55 per equity/FX trade and $100 per crypto trade. These
  are scenarios, not a promise that every signal is affordable or executable.
- Every signal is taken independently, with one position per symbol within a rule.
  Cash, gross exposure, portfolio risk, correlated positions and daily acceptance caps
  are not simulated. No totals across strategies are reported.
- The denominator is the full requested calendar window, including idle periods.
  Losing-month counts include partial first/last months; annualised dollar averages
  use elapsed calendar years. Monthly R is booked at exits, including the final
  historical liquidation, not from an intraday marked equity curve.
- Equity costs: 3 bps slippage plus half a 5 bps quoted spread on each fill (11 bps
  round trip), zero commission. Crypto configured spread inputs are 24/26/40 bps
  BTC/ETH/SOL and 50 bps for other pairs: the engine charges half plus 1 bp slippage
  per fill, i.e. 26/28/42/52 bps round trip. No funding/borrow model.
- Full-history figures mix development and previously observed periods. They are
  descriptive, cannot earn approval, and are not new sealed tests. The original script
  incorrectly described some version/snapshot-specific sealed status as consumed;
  that label was not an approval. Frozen gate results remain in the research ledger.
- Surviving selection, symbol identity, split adjustments, missing observations and
  modelled spreads still limit what can be concluded. Realised-exit drawdown understates
  the information needed for a cash/margin portfolio assessment.

## Fixed-risk historical scenarios

| Rule / universe | Window | Trades | Mean R/trade | Historical $/month | Worst calendar month ($) | Losing months |
|---|---|---:|---:|---:|---:|---:|
| trend.short_swing / 24 symbols | 2016-10-17..2026-11-02 | 1,330 | +0.121 | +73 | -936 | 49/122 |
| trend.short_swing / 150 symbols | 2016-10-17..2026-11-02 | 7,714 | +0.110 | +386 | -2,503 | 41/122 |
| trend.medium_swing / 24 symbols | 2016-10-17..2026-11-02 | 1,213 | +0.146 | +81 | -1,227 | 51/122 |
| trend.medium_swing / 150 symbols | 2016-10-17..2026-11-02 | 6,998 | +0.159 | +509 | -2,858 | 41/122 |
| relative strength.medium_swing / 24 symbols | 2016-10-17..2026-11-02 | 664 | +0.209 | +63 | -884 | 40/122 |
| relative strength.medium_swing / 150 symbols | 2016-10-17..2026-11-02 | 5,562 | +0.159 | +403 | -4,409 | 30/122 |
| mean_reversion.short_swing / 24 symbols | 2016-10-17..2026-11-02 | 727 | +0.015 | +5 | -630 | 43/122 |
| volatility_breakout.short_swing / 24 symbols | 2016-10-17..2026-11-02 | 145 | +0.261 | +17 | -509 | 23/122 |
| volatility_breakout.short_swing / 150 symbols | 2016-10-17..2026-11-02 | 795 | +0.170 | +62 | -1,466 | 39/122 |
| tsmom_etf.medium_swing / 9 symbols | 2006-03-01..2025-09-07 | 617 | +0.039 | +6 | -415 | 102/235 |
| turn_of_month.short_swing / 5 symbols | 2003-10-20..2025-09-07 | 1,305 | +0.020 | +6 | -376 | 121/264 |
| CRYPTO-1 crypto_donchian_55 / 3 pairs | 2015-01-01..2026-11-02 | 172 | +1.135 | +137 | -309 | 53/143 |
| CRYPTO-1 crypto_tsmom_126_ma50 / 3 pairs | 2015-01-01..2025-11-03 | 141 | +0.135 | +15 | -255 | 39/131 |
| CRYPTO-1 crypto_zfade_20 / 3 pairs | 2015-01-01..2025-11-03 | 569 | -0.210 | -92 | -880 | 77/131 |
| CRYPTO-2 crypto_donchian_55_u10 / 10 pairs | 2015-01-01..2025-11-03 | 421 | +1.044 | unusable: data gaps | unusable | 71/131 |
| CRYPTO-3 crypto_mom_21_long_u10 / 10 pairs | 2015-01-01..2025-11-03 | 1,049 | +0.436 | unusable: data gaps | unusable | 64/131 |
| FX-1 fx_donchian_55 / 8 pairs | 2010-01-04..2025-11-03 | 633 | -0.109 | -20 | -333 | 116/191 |
| FX-1 fx_tsmom_126_ma50 / 8 pairs | 2010-01-04..2025-11-03 | 605 | -0.022 | -4 | -260 | 104/191 |
| FX-1 fx_zfade_20 / 8 pairs | 2010-01-04..2025-11-03 | 1,627 | -0.016 | -7 | -553 | 91/191 |
| FX-2 fx_donchian_55_trail20 / 8 pairs | 2010-01-04..2025-11-03 | 543 | -0.110 | -17 | -428 | 121/191 |

The 3-pair and 10-pair Donchian rules overlap in BTC/ETH/SOL exposure. Their
illustrative profits must not be added without a joint, funded portfolio simulation.
The crypto paper books store a risk-dollar illustration and do not establish a $30,000
cash account. The earlier "$90,000 total paper capital" denominator was unsupported.

## Evidence and scope

`scripts/profit_backtest_full_history.py` reproduces the calculation on a scratch database
containing the documented datasets; its positional argument is an output directory holding
`syms24_snap3.txt` and `syms150_snap11.txt` (the exact symbol arrays from snapshots 3/11).
Corrected output: `diagnostics/profit_backtest_corrected_2026-11-02.json`.
Original output retained separately as `diagnostics/profit_backtest_2026-11-02.json`.
Month-by-month realised R, zero months and drawdown basis are available in the corrected JSON.

This table covers the listed daily rule/universe combinations. It does not pretend that
options, the mechanical grid or an unfinished intraday sensitivity run have a validated
monthly dollar result. Options failed the existing ladder with zero OOS structures;
FX and the newer ETF strategies failed their gates. No new live execution is enabled.

For the data-quality findings, operational hold and verification, see
`REPAIR_AUDIT_2026-11-02.md`.
