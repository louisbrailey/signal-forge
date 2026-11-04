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

## 2. R2-E1 `high52_breakout.medium_swing`, R2-E2 `trend_pullback.short_swing` (equities, snapshots 3 and 11)

_Running on scratch `sfdata6` with the pre-registered grids (`lookback` × `stop_atr`;
`sma_fast` × `stop_atr`); filled on completion._

## 3. CRYPTO-H3 (`_quiet`, 336/168) and CRYPTO-4 `crypto_high252_u9`

_Codex session's families; code not yet present at the time of writing. Results to be added
by whichever session runs them, under this heading._
