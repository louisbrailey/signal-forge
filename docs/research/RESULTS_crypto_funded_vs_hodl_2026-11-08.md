# Long-only crypto Donchian in a shared-cash account vs buy-and-hold (2026-11-08)

DESCRIPTIVE, development window only: every daily series cut before 2025-10-26 (CRYPTO-1
sealed start). Fractional units, one cash account, risk r% of equity per trade (entry to
stop), 33% or 100% per-position cap, taker costs on every fill at the real Coinbase venues
(`research/fx/venues.py`). Produced by workflow `sf-crypto-funded-vs-hodl` (scratch scripts
`replay.py`, `analysis.py`, `render.py`; 528 runs, 111 benchmark rows, Sharpe-gap resampling,
start-year sweep). Two adversarial verifiers found three major and seven minor issues; all
were fixed and the runs repeated (the first 396 runs reproduced exactly).

## Headline

**No long-only crypto rule beats buy-and-hold on a risk-adjusted basis by more than noise.**
Every resampled Sharpe-gap interval contains zero except 4 of 116 comparisons, all against a
weak BTC 200-day-SMA timing benchmark.

| $10k, r 1%, 33% cap | Window | Sharpe | CAGR % | Max DD % | Exposure % |
|---|---|---:|---:|---:|---:|
| crypto_donchian_55_long, spot | 2021-09-12..2025-10-25 | 0.96 | 10.4 | 7.6 | 9 |
| crypto_donchian_55_long, futures 1x | same | 1.13 | 13.6 | 7.4 | 10 |
| BTC buy-and-hold | same | 0.67 | 24.0 | 76.7 | 100 |
| crypto_donchian_55_u10_long, spot | 2022-05-28..2025-10-25 | 0.97 | 24.9 | 21.9 | 20 |
| BTC buy-and-hold | same | 1.04 | 48.2 | 50.4 | 100 |
| crypto_donchian_55_long, spot | full history 2015-07..2025-10 | 1.07 | 12.1 | 12.2 | 7 |
| crypto_donchian_55_u10_long, spot | full history | 0.92 | 26.3 | 34.2 | 14 |
| equal-weight basket adding pairs as they list | full history | 1.29–1.35 | — | — | 100 |

- D55_long's post-2021 Sharpe lead comes from sitting out 2022 plus one SOL trade
  (+13.8% of starting equity); it wins for 1 January starts 2017–2022 and loses for 2016, 2023
  and 2024. Over full history it loses to the staggered basket (gap −0.22, P(gap>0) 0.23).
- u10 shows no edge at spot fees and loses to the staggered basket by close to a significant
  margin (gap −0.43, 90% range [−0.88, +0.02]).
- What the rules do deliver is a much smaller drawdown (7–22% vs 50–85%) at much lower
  return. Against exposure-matched buy-and-hold D55_long wins on return per drawdown, u10 does
  not.
- Spot fees cost 17–19% of D55_long's gross profit (u10: up to 221% of starting cash on the
  full history at r 1%). Futures add +0.12 to +0.17 Sharpe over spot; 10%/yr funding takes
  back 0.05–0.09. Cash level does not change the results (fractional units).

## Caveats

Trades already open at a window start are dropped (carry-in variant: −0.8 pp, −0.014
Sharpe). Four pairs miss 2025-03-25 and BTC/ETH/XRP have 2015–2017 gaps (forward-filled,
within harness tolerance). These are unsealed experimental rules evaluated on already-seen
history.

## Reading

Crypto trend-following here is a drawdown-control tool, not a demonstrated source of excess
risk-adjusted return. D55_long on futures is the strongest candidate found in this program,
and it is still not distinguishable from holding the coins.
