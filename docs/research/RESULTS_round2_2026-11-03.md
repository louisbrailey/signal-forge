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

## 4. CRYPTO-4 `crypto_high252_u9` (Codex session)

_Codex's family; results to be appended by that session under this heading._

## 5. Summary for the operator

| Pre-registered | Development | Needs a sealed-look decision |
|---|---|---|
| CRYPTO-H4: 3 hourly rules, BTC+ETH | `..._trail72_volx` **PASS**; trail120 fail; baseline fail | **yes** — `crypto_h_donchian168_trail72_volx` (no hourly paper book exists yet) |
| CRYPTO-H3: 2 hourly rules, 4 pairs | both fail | no |
| R2-E1 `high52_breakout`, snapshots 3 and 11 | **PASS on 150**; fail on 24 | **yes** — `high52_breakout.medium_swing` on snapshot 11 |
| R2-E2 `trend_pullback`, snapshots 3 and 11 | fail on both | no |
| CRYPTO-4 `crypto_high252_u9`, 9 daily pairs | pending (Codex) | — |

No sealed year was consumed in this round. Nothing is armed. BNB is in no universe.
