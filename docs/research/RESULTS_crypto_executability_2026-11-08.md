# Crypto executability at the account's real Coinbase fees (2026-11-08)

Development-window evidence only. Every series was cut with the harness `_cut()` before
each rule's sealed start (CRYPTO-1 2025-10-26; CRYPTO-2 and H4 2025-11-03). No sealed
window was read for this note; sealed figures quoted are the recorded `currency_sealed_test`
rows only. Scripts and outputs: scratchpad `crypto_exec/` (`cost_sweep.py`, `stop_dist.py`,
`sizing.py`), produced by workflow `sf-crypto-executability` and checked by three
adversarial verifiers whose corrections are applied below.

## Fees read from the account (read-only `coinbase_fees`)

| Venue | Tier | Maker | Taker | Other |
|---|---|---|---|---|
| Spot | Intro | 0.50% | **0.90%** | spot balance about $32 |
| US futures (CFM) | Intro | 0.095% | 0.10% | plus per-contract exchange/NFA/clearing fees (estimated $0.15/side) |

The harness models 10 bps taker plus a half-spread (`fx/harness.py:80-85`). That is roughly
a futures cost, so CRYPTO-1/H4 approvals and paper R are effectively futures-cost results.

## Expectancy by leg and cost case (R per trade, whole development window)

| Rule / leg | n | Current model | Spot taker 90 bps | Futures (10 bps + contract fee), 0% / 10% carry | Break-even bps/side |
|---|---|---|---|---|---|
| d55 LONG | 101 | +1.724 | +1.396 | +1.705 / +1.626 | 766 |
| d55 SHORT | 52 | +0.080 | −0.092 | +0.071 / +0.017 | 48 |
| u10 LONG | 244 | +1.683 | +1.411 | +1.665 / +1.606 | 889 |
| u10 SHORT | 159 | −0.106 | −0.224 | −0.115 / −0.161 | negative at zero cost |
| H4 long-only (re-run) | 309 | +1.287 | +0.381 | +1.222 / +1.164 | 152 |
| H4 SHORT | 280 | +0.003 | −0.461 | −0.029 / −0.066 | 14 |

Verifier corrections that bound these numbers:

- The table pools the whole pre-seal history, most of which is walk-forward training. On the
  harness's pre-registered OOS segment (last 40% of each pair's development window) the long
  edge is about 30–45% smaller and break-evens roughly halve — still far above 90 bps for the
  daily rules.
- H4 long on 2022-04..2025-11 repriced exactly at the spot-taker cost is **+0.245R** (130
  trades), not the +0.46R a linear sensitivity suggests. Spot H4 is thin; futures H4 is not.
- "Maker entries, taker stops" figures charge maker on trail/time exits, which are market
  exits in practice; treat maker cases as optimistic.
- Data hygiene: an earlier diagnostic (`crypto_diag.py`) ran on uncut series and bucketed
  trades inside the sealed window. Those rows are not the sealed record and must not be cited.

## Conclusions

1. **Shorts carry no development-window edge on any venue** once realistic costs apply, and
   spot cannot short at all. Every open crypto paper position on 2026-11-07 was a short.
2. **Daily Donchian-55 long-only is executable on spot at the Intro tier** with a large cost
   margin. It is a new rule definition (`*_long`) and needs registration and forward paper
   evidence; no fresh crypto holdout remains for BTC/ETH/SOL daily.
3. **H4 is executable with a meaningful edge only on futures** (perp-style BIP/ETP contracts,
   hourly funding, no rolls). Long-only on spot is about +0.25R in the recent sub-window.
4. **Account size, not edge, is the binding constraint.** $32 on spot gives about $3 of risk
   per trade. Futures margin plus whole-contract rounding needs roughly $2–3k for d55 at three
   concurrent positions and $5–6k for H4 at $100 risk; u10 at nine pairs needs about 3× d55.

## Changes Signal Forge needs before crypto paper R can be read as account dollars

- Per-venue cost model: half-spread, maker and taker fee, per-contract fee, funding; fee tier
  as configuration, not a constant.
- `long_only` parameter on the crypto Donchian rules (precedent: `strategies.py:305/313`).
- Futures sizing in whole contracts with a rounding policy, margin check against equity and a
  minimum risk per pair.
- Funding accrual plus a forward collector of hourly funding snapshots (no US history is
  available through the API).
- Paper books: per-venue cost columns and a long-only view beside the existing R.
