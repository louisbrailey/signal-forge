# Results — strategy round 2 (2026-11-03/04)

Pre-registrations: `PREREGISTRATION_round2_2026-11-03.md` (Codex session, commit `aca5e63`:
admissibility policy, CRYPTO-H3 `_quiet`/336-168, R2-E1 `high52_breakout`, R2-E2
`trend_pullback`, CRYPTO-4 `crypto_high252_u9`) and
`PREREGISTRATION_round2_hourly_H4_2026-11-03.md` (Claude session: CRYPTO-H4 hourly variants).
Two agents worked this round concurrently on one branch; each result below names which
pre-registration and which run produced it. Nothing here consumed a sealed year. Nothing is
armed. BNB is in no universe.

## 1. CRYPTO-H4 — hourly Donchian variants, BTC + ETH (zero-gap pairs), development window only

`crypto research-hourly --version CRYPTO-H4 --pairs BTCUSD,ETHUSD`, live DB read-only, 2026-11-04
02:1x–02:4x UTC. Report `data/research/crypto/crypto_hourly_CRYPTO-H4_2026-11-03.md`. Sealed from
2025-11-03 20:00 UTC, not evaluated. Costs BTC 24 / ETH 26 bps per side + 1 bp; 2× stress.

| Strategy | Verdict | OOS trades | Expectancy (R) | CI low (R) | 2x-spread (R) | Folds (R) | BTC / ETH exp. |
|---|---|---|---|---|---|---|---|
| crypto_h_donchian168_trail72 (baseline, look #4) | DEV_FAIL (CI) | 335 | +0.460 | +0.007 | +0.286 | +0.92, +0.10, +0.79, +0.07 | +0.330 / +0.598 |
| crypto_h_donchian168_trail120 | DEV_FAIL (CI) | 308 | +0.515 | −0.036 | +0.337 | +0.90, +0.07, +0.94, +0.17 | +0.315 / +0.732 |
| **crypto_h_donchian168_trail72_volx** | **DEV_PASS** | 265 | **+0.649** | **+0.106** | +0.469 | +1.21, +0.10, +1.37, +0.08 | +0.495 / +0.811 |

Reading. The volatility-expansion filter did what the pre-registration said it should: it
removed about a fifth of the baseline's trades (335 → 265) and raised expectancy per trade
from +0.46R to +0.65R, lifting the CI lower bound from +0.007R to +0.106R — the first hourly
rule to clear every development gate. The longer trail raised expectancy slightly but widened
the CI and fails. Caveats, all visible in the table: two pairs only; folds 1 and 3 carry the
result (+1.21R, +1.37R) while folds 2 and 4 are near zero (+0.10R, +0.08R), so the edge is
concentrated in trending periods; and the baseline it improves on has now had four
development looks, which the volx variant inherits as context even though the filter itself
was fixed before the run.

**Disposition: `crypto_h_donchian168_trail72_volx` (CRYPTO-H4, BTC+ETH) is a sealed-look
candidate. Not run.** Taking that look needs the user's explicit authorisation; the sealed
window would be 2025-11-03 20:00 → 2026-11-04 on hourly bars for BTC and ETH, which no rule in
this family has evaluated. If authorised and passed, there is no hourly paper book mechanism
yet; one would have to be built (the daily crypto ledger replays daily bars only).

## 2. R2-E1 `high52_breakout.medium_swing`, R2-E2 `trend_pullback.short_swing` (equities; scratch `sfdata6`; `--since 2016-10-17 --until 2025-09-07`)

Rules and grids exactly as committed in `PREREGISTRATION_round2_2026-11-03.md` (Codex spec:
high52 = close above the prior 252-session high with volume ≥ 1.3× its 20-session average,
stop 2×ATR(14), target 4×ATR, time stop 40, grid `lookback` × `stop_atr`; pullback = close >
SMA(200), three down closes, close < SMA(10), stop 2×ATR, target 2×ATR, time stop 10, grid
`sma_fast` × `stop_atr`). Gate 9 here is a diagnostic window on development data
(2024-09-07..2025-09-07); the real sealed years are untouched.

| Strategy | Universe | OOS trades | Expectancy | CI low | Grid | Regimes bull/bear/range | Sharpe vs SPY 0.68 | Diag. sealed | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| high52_breakout | 24 (snapshot 3) | 83 | +0.334R | −0.009R ✗ | 9/9 ✓ | 237/3/3 ✗ | 0.72 ✓ | −0.054R / 88 ✗ | fails 4, 6, 9 |
| **high52_breakout** | **150 (snapshot 11)** | **500** | **+0.209R** | **+0.080R ✓** | **9/9 ✓** | 1297/12/50 ✓ | **1.17 ✓** (CAGR 11.7%, vol 9.9%, maxDD 31.9%, 172 trades/yr) | **+0.159R / 138 ✓** | **passes all 10 gates** (scratch evaluation 69) |
| trend_pullback | 24 | 343 | +0.024R | −0.079R ✗ | 9/9 ✓ | 719/16/65 ✓ | 0.66 ✗ | −0.081R / 99 ✗ | fails 4, 7, 9 |
| trend_pullback | 150 | 1,952 | +0.048R | −0.003R ✗ | 9/9 ✓ | 4041/105/418 ✓ | 1.51 ✓ | −0.027R / 562 ✗ | fails 4, 9 |

Reading. **The 52-week-high breakout on the 150-symbol universe is the round's one full
development pass**: +0.209R on 500 out-of-sample trades, every grid point positive, all four
walk-forward folds positive, all three regimes covered, Sharpe 1.17 vs 0.68, and the
diagnostic window positive (+0.159R on 138). It is the same kind of rule as the approved
trend family (long, trend-following, regime-gated) and will be correlated with it; on the
24-symbol universe it has too few trades (83) and almost no bear/range coverage. The pullback
rule is positive everywhere but thin (+0.02–0.05R before the CI gate) and negative in both
diagnostic windows: short-term reversal does not survive an 11 bps round trip on large caps,
as the pre-registration expected.

**Disposition: `high52_breakout.medium_swing` v0.1.0 on snapshot 11 (150 symbols) is a
sealed-look candidate. Not run.** A real sealed test (2025-09-08 → 2026-09-08 on snapshot 11)
needs the user's explicit authorisation; if passed, approval and a paper book would follow the
existing equity path (same hash-scoped approval mechanism as the three live strategies).
`trend_pullback` is rejected on both universes.

## 3. CRYPTO-H3 — Codex's two new hourly rules on BTC, ETH, SOL, DOGE (admissibility policy; baseline NOT re-run)

`crypto research-hourly --version CRYPTO-H3 --pairs BTCUSD,ETHUSD,SOLUSD,DOGEUSD`, live DB
read-only, 2026-11-04 02:5x UTC; report `data/research/crypto/crypto_hourly_CRYPTO-H3_2026-11-03.md`.
Implemented by the Claude session exactly to the committed spec (commit `7b9ecc0`).

| Strategy | Verdict | OOS trades | Expectancy (R) | CI low (R) | 2x-spread (R) | Folds (R) | BTC / ETH / SOL / DOGE |
|---|---|---|---|---|---|---|---|
| crypto_h_donchian168_trail72_quiet (ATR24/close ≤ 240h median) | DEV_FAIL (CI, folds 2/4) | 299 | +0.217 | −0.172 | +0.032 | +0.81, −0.39, +0.63, −0.21 | +0.59 / +0.22 / +0.13 / −0.14 |
| crypto_h_donchian336_trail168 | DEV_FAIL (CI) | 357 | +0.449 | −0.039 | +0.273 | +0.78, +0.22, +1.04, −0.12 | +0.60 / +1.08 / −0.53 / +0.28 |

Reading. The "quiet tape" filter did the opposite of what its rationale predicted: gating the
168h breakout to compressed volatility *lowered* expectancy from the baseline's +0.46R to
+0.22R and made two folds negative — while the CRYPTO-H4 filter in §1, which gates to
*expanding* volatility (ATR(24) ≥ ATR(168)), raised it to +0.65R. The two results are the two
sides of one finding: hourly crypto breakouts work when volatility is rising into them, not
out of a lull. The two-week channel is positive on three of four pairs with a strong ETH
(+1.08R) and a bad SOL (−0.53R) and misses the CI gate. Both CRYPTO-H3 rules are rejected.

## 4. CRYPTO-4 `crypto_high252_u9` — DEV_FAIL (statistical power), run 2026-11-03

`run_crypto4_research` (equivalent of `crypto research --version CRYPTO-4`), live DB
read-only, nine admissible daily pairs (BTC, ETH, SOL, XRP, DOGE, ADA, LINK, AVAX, LTC; no
BNB), CRYPTO-1 gates plus the §0 admissibility policy (every pair admitted; no continuity
reason raised). Report `data/research/crypto/crypto_research_CRYPTO-4_2026-11-03.md`. Sealed
from 2025-11-04, not evaluated. Code `92a9af5`.

| Strategy | Verdict | OOS trades | Expectancy (R) | CI low (R) | 2x-spread (R) | Folds (R) |
|---|---|---|---|---|---|---|
| crypto_high252_u9 | **DEV_FAIL** | 37 | +0.573 | −0.227 | +0.523 | +0.46, −0.56, +1.49, +0.30 |

| Pair | OOS from | OOS trades | Expectancy (R) | 2x-spread (R) |
|---|---|---|---|---|
| ADAUSD | 2022-10-07 | 3 | −1.019 | −1.036 |
| AVAXUSD | 2024-04-01 | 0 | — | — |
| BTCUSD | 2021-07-04 | 9 | +1.397 | +1.333 |
| DOGEUSD | 2022-06-21 | 2 | +3.591 | +3.458 |
| ETHUSD | 2021-10-01 | 7 | +0.025 | −0.010 |
| LINKUSD | 2023-04-19 | 5 | +1.049 | +0.979 |
| LTCUSD | 2022-03-29 | 4 | −1.018 | −1.034 |
| SOLUSD | 2023-12-19 | 3 | −0.224 | −0.248 |
| XRPUSD | 2022-04-27 | 4 | +0.959 | +0.897 |

Reading: a close above the prior 252-day high is rare on daily crypto bars (37 out-of-sample
trades across nine pairs, four pairs with ≤ 3), so the only failed gate is the bootstrap CI
(−0.227R vs +0.02R). The sign is positive (+0.57R, +0.52R at double costs) but one fold is
negative and per-pair results swing from −1.0R to +3.6R on a handful of trades. A power
failure, not evidence either way; shortening the channel to manufacture trades would be the
Donchian-55 rule the system already has. **Rejected at this parameterisation; not refined.**

## 5. Summary for the operator

| Pre-registered | Development | Needs a sealed-look decision |
|---|---|---|
| CRYPTO-H4: 3 hourly rules, BTC+ETH | `..._trail72_volx` **PASS**; trail120 fail; baseline fail | **taken 2026-11-04 (user: "Yes, both") → SEALED_PASS**, see §6 |
| CRYPTO-H3: 2 hourly rules, 4 pairs | both fail | no |
| R2-E1 `high52_breakout`, snapshots 3 and 11 | **PASS on 150**; fail on 24 | **taken 2026-11-04 (user: "Yes, both") → all 10 gates PASS on the live DB, PAPER_APPROVED**, see §6 |
| R2-E2 `trend_pullback`, snapshots 3 and 11 | fail on both | no |
| CRYPTO-4 `crypto_high252_u9`, 9 daily pairs | fail (37 trades, CI low −0.227R) | no |

No sealed year was consumed in this round. Nothing is armed. BNB is in no universe.


## 6. Sealed looks taken 2026-11-04 (operator authorisation: "Yes, both")

### 6.1 `high52_breakout.medium_swing` v0.1.0 on snapshot 11 — PAPER_APPROVED (live evaluation 51, sealed test 23)

`evaluate-promotion --strategy high52_breakout --symbols <150 of snapshot 11> --snapshot-key
research_150_massive_10y_presealed_sel --since 2016-10-17 --until 2026-09-08` on the LIVE
database (development span identical to the scratch run; sealed window 2025-09-08 →
2026-09-08, never read before; config hash fe365720c0b6 = live scan hash).

| Gate | Result |
|---|---|
| 1 walk-forward | 4/4 folds clear the floor with positive expectancy |
| 2 trades | 525 OOS |
| 3 expectancy | +0.227R after costs |
| 4 bootstrap CI | low +0.098R |
| 5 sensitivity | 9/9 grid positive, 100% neighbours |
| 6 regimes | bull 1,427 / bear 12 / range 58 |
| 7 benchmark | Sharpe 1.18 (CAGR 11.7%, vol 9.8%, maxDD 31.9%, 169 trades/yr) vs SPY 0.72 |
| 8 data quality | pass, leakage self-check clean |
| **9 sealed year** | **201 trades, +0.263R** (730-day indicator warm-up, entries inside the window only) |
| 10 probation | active once it books paper trades |

The strategy is now `PAPER_APPROVED` with its scope locked to snapshot 11's 150 symbols and
the live config hash; the approved-scope scan picks it up at the next session. Honest
caveats: 12 bear-regime trades is the minimum the gate allows; the 150-symbol universe is
survivorship-biased (disclosed in the snapshot); gate 7's Sharpe is computed on the fixed-risk
ladder, not a capital-constrained book.

### 6.2 `crypto_h_donchian168_trail72_volx` (CRYPTO-H4, hourly, BTC+ETH) — SEALED_PASS (`currency_sealed_test` id 4)

Run through the new hourly sealed-test path (`research/fx/sealed.py`, market key
`crypto_hourly`, row market "Crypto (hourly)"). Sealed window 2025-11-03 → 2026-11-02 on
hourly bars; development gates recomputed and passed first; the look is consumed.

| Metric | Sealed year |
|---|---|
| Trades | 79 (BTC 41, ETH 38) |
| Expectancy | **+0.373R** (BTC +0.296R, ETH +0.456R) |
| At 2× costs | +0.206R (BTC +0.130R, ETH +0.288R) |
| Win rate / avg win / avg loss | 21.5% / +5.50R / −1.03R |
| Profit factor | 1.46 |
| Max drawdown | 13.2R; longest losing streak 12 |
| Total | +29.5R over the year |

A pass, with the shape of a trend rule: one win in five, paid for by large winners, and a
twelve-trade losing streak inside the year.

**Hourly paper book (operator decision 2026-11-04, "Restart + build book").** The daily crypto
ledger keys trades by calendar date, so an hourly twin was built (commit `9b19b70`): tables
`crypto_hourly_paper_book` / `crypto_hourly_paper_trade` (migration `f3a7c1d9e5b2`), module
`paper/crypto_hourly_ledger.py` (same rules as the daily book: SEALED_PASS required, kill
switch and data holds block opening only, SKIPPED never opened late, CLOSED immutable; replays
`research.fx.harness.backtest` so parity with the sealed test is structural), an hourly
scheduler job that tops up the book's pairs' bars then replays, and `crypto paper-hourly
start|run|status`. Book started 2026-11-04 03:00 UTC on BTCUSD + ETHUSD, $100 R per trade,
observation to 2027-05-03; first cycle clean, no trade yet (bars through 2026-11-02 20:00 UTC
at start; the hourly job tops them up). Paper-only; nothing armed. Start command:
`signalforge crypto paper-hourly start crypto_h_donchian168_trail72_volx --confirm`; book row
`crypto_hourly_paper_book` id 1 (sealed_test_id 4). The cycle is gated by its own flag
`CRYPTO_HOURLY_PAPER_ENABLED` (off by default; set true in the live `.env` on 2026-11-04).
