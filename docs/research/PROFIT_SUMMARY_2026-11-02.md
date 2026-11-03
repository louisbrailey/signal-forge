# What the strategies would have made — full available history (2026-11-02)

Script: `scripts/profit_backtest_full_history.py` (read-only, scratch copy of the live DB taken
2026-11-02 19:4x PST; raw output `docs/research/diagnostics/profit_backtest_2026-11-02.json`).
Shipped cost models (equities 3 bps slippage + half of a 5 bps spread, $0 commission; crypto
24/26/40 bps per side BTC/ETH/SOL and 50 bps/side other pairs + 1 bp; FX 1–3 bps + 1 bp).
Long only, every signal taken, one position per symbol at a time — **no book capacity
limit**, so these are the strategy's numbers, not a $30k book's.

**Sealed-year rule respected.** A strategy whose sealed test is already locked runs through
the last bar (2026-11-02). One that has never had its sealed look (CRYPTO-2, CRYPTO-3, the
FX versions, the two new ETF rules) is cut at its sealed-window start, so this report spends
no look. "R" is one unit of planned risk. Dollar columns use the realised paper R (~$55 per
trade on a $30k equity book, see RESULTS_full_pipeline §7), the 0.5% cap ($150) and the crypto
book's $100.

## 1. Full-history results

| Strategy | Universe | Window | Trades | Exp. (R) | Win | R / year | Max DD (R) | Losing years | $/month @ $55 R | $/month @ $150 R | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| trend_continuation.short_swing | 24 | 2016-12 → 2026-11 (through sealed yr) | 1,330 | +0.121 | 47% | 16.3 | 65 | 2 of 11 | $75 | $204 | approved, in paper |
| trend_continuation.short_swing | 150 | same | 7,714 | +0.110 | 47% | 85.8 | 148 | 2 of 11 | $393 | $1,073 | passes on 150 (scratch) |
| trend_continuation.medium_swing | 24 | same | 1,213 | +0.146 | 43% | 18.0 | 69 | 3 of 11 | $83 | $225 | |
| trend_continuation.medium_swing | 150 | same | 6,998 | +0.159 | 43% | 113.4 | 160 | 3 of 11 | $520 | $1,417 | approved on 150, in paper |
| relative_strength.medium_swing | 24 | same | 664 | +0.209 | 46% | 15.0 | 39 | 1 of 10 | $69 | $188 | approved, idle (scan gate) |
| relative_strength.medium_swing | 150 | same | 5,562 | +0.159 | 44% | 95.5 | 189 | 2 of 10 | $438 | $1,193 | |
| mean_reversion.short_swing | 24 | same | 727 | +0.015 | 58% | 1.2 | 38 | 6 of 10 | $5 | $15 | rejected |
| volatility_breakout.short_swing | 24 | same | 145 | +0.261 | 52% | 3.9 | 15 | 1 of 9 | $18 | $48 | rejected (power) |
| volatility_breakout.short_swing | 150 | same | 795 | +0.170 | 47% | 13.8 | 42 | 1 of 9 | $63 | $172 | rejected (CI, bear) |
| tsmom_etf.medium_swing | 9 ETFs | 2007 → 2025-09 (dev only) | 617 | +0.039 | 49% | 1.3 | 32 | 9 of 19 | $6 | $16 | closed |
| turn_of_month.short_swing | 5 ETFs | 2004 → 2025-09 (dev only) | 1,305 | +0.020 | 54% | 1.2 | 33 | 10 of 22 | $6 | $15 | rejected |

| Crypto / FX | Pairs | Window | Trades | Exp. (R) | Win | R / year | Max DD (R) | Losing years | $/month @ $100 R | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| CRYPTO-1 crypto_donchian_55 | 3 | 2015 → 2026-11 (through sealed yr) | 172 | **+1.135** | 41% | 16.9 | 9 | 1 of 12 | **$141** | sealed pass, in paper |
| CRYPTO-2 crypto_donchian_55_u10 | 10 | 2015 → 2025-11 (dev); sealed yr 2025-11→2026-11 **+0.693R / 55 PASS** | 421 | +1.044 | 35% | 41.6 | 30 | 1 of 11 | $347 (sealed-year rate ≈ $320) | **sealed pass 2026-11-02** |
| CRYPTO-3 crypto_mom_21_long_u10 | 10 | 2015 → 2025-11 (dev); sealed yr **−0.062R / 130 FAIL** | 1,049 | +0.436 | 43% | 42.5 | 63 | 3 of 11 | $354 on dev, −$68 in the sealed year | **rejected 2026-11-02** |
| CRYPTO-1 tsmom_126 / zfade_20 | 3 | dev only | 141 / 569 | +0.135 / −0.210 | | 1.8 / −11.3 | | | $15 / −$94 | rejected |
| FX-1 (3 rules), FX-2 (1 rule) | 8 | 2010 → 2025-11 (dev only) | 543–1,627 | −0.02 to −0.11 | 28–48% | −0.9 to −4.4 | 28–95 | 9–12 of 16 | −$4 to −$20 at $55 R | rejected |

## 2. What this says about profit

- **Equities.** Over the whole 2016–2026 history the three approved rules earn
  **+0.11 to +0.21R per trade** — lower than their out-of-sample windows (+0.22 to +0.30R)
  because the full span includes the weaker 2016–2019 years and 2019/2022, which were losing
  years for every trend rule. On the 24-symbol universe each rule makes **15–18R a year**:
  about **$70–85/month at the realised $55 R, $190–225/month at the $150 cap**, with a worst
  drawdown of 39–69R ($2,100–3,800 at $55 R). On 150 symbols the same rules make 86–113R a year
  (**$390–520/month at $55 R**) but a $30k book cannot take 700–800 trades a year; the book
  realises roughly the 24-symbol figures.
- **Year by year** the equity rules are positive in 8–9 of 11 years each, with 2024 the best
  year (64–218R) and 2019 and 2022 the losing ones.
- **Crypto Donchian on 3 pairs** is the strongest rule per trade in the whole system:
  +1.1R per trade, 17R a year, max drawdown only 9R, one losing year in twelve, including the
  sealed year it has already passed. At the paper book's $100 R that is **≈ $140/month**;
  the drawdown is under $1,000.
- **The two crypto candidates** (10-pair Donchian, long-only one-month momentum) each make
  ≈ 42R a year on development data (**≈ $350/month at $100 R**), with 2025 slightly negative
  and 2022 (momentum) the bad year. Those numbers are not yet sealed-tested.
- **Everything else** — mean reversion, volatility breakout, ETF trend, turn-of-month, every
  FX rule — makes between −$20 and +$60 a month before any capacity limit. The FX rules lose
  money in 9–12 of 16 years.

## 3. Bottom line (all books at current sizing, every signal taken)

| Running today | $/month, full-history rate |
|---|---|
| trend short swing (24, $55 R) | ≈ $75 |
| trend medium swing (150, capacity-limited to ~9 slots → roughly the 24-symbol rate) | ≈ $85 |
| relative strength (approved, currently idle) | $0 (would be ≈ $70) |
| crypto Donchian, 3 pairs ($100 R) | ≈ $140 |
| **Total** | **≈ $300/month on ~$90k of paper capital** |

With the two crypto candidates sealed-tested and passed, and relative strength trading, the
same books would run at roughly **$1,000/month**; at the $150 equity R instead of the realised
$55, roughly **$1,400/month**. These are averages over 10–12 years that include 2–3 losing
years per rule; drawdowns of 40–70R per equity rule are part of the record.
