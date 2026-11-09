# Pre-registration — CRYPTO-H4 hourly Donchian variants (2026-11-03)

**Provenance, stated plainly.** This family was written to disk as §1 of
`PREREGISTRATION_round2_2026-11-03.md` at ~02:05 UTC on 2026-11-04 (Claude session) and run at
02:17 UTC (`scratchpad/logs/run_crypto_h3.log`, report
`data/research/crypto/crypto_hourly_CRYPTO-H3_2026-11-03.md`). Before it could be committed, a
concurrent Codex session replaced that file with its own round-2 pre-registration (commit
`aca5e63`), which reserves the label **CRYPTO-H3** for a *different* hourly family
(`_quiet` filter, 336/168 channel). To keep one label per family, these variants are
relabelled **CRYPTO-H4** and re-run under that name; the rules, universe and gates below are
exactly what was written before the first run. Because the original text was never committed,
the only pre-run evidence is the scratch log timestamp; that is weaker than a commit and is
said so here.

## Universe (fixed by data before the run)

From {BTC, ETH, SOL, DOGE} vs USD, hourly, every pair with **zero** missing bars after the
targeted re-fetch of 2026-11-04 (SOL's 24 missing hours on 2025-03-25 and DOGE's 32 scattered
hours were re-requested; Massive returned none). Result: **BTCUSD, ETHUSD**. BNB (sparse) and
XRP (737 missing hours) excluded. Under the admissibility policy Codex pre-registered later the
same hour (≤1% missing, longest hole ≤48 h), SOL and DOGE would also be admissible; running
these variants on that wider universe would be a *further* look and is not done here.

## Disclosure of prior looks on the baseline

`crypto_h_donchian168_trail72` was evaluated on development data as CRYPTO-H1 (3 pairs, CI low
+0.010R), CRYPTO-H2 (6 pairs incl. the now-excluded BNB and XRP, CI low −0.010R), and re-checked
under the continuity gate on 2026-11-03. Its appearance here as the baseline on BTC/ETH is look
#4 for that rule. The two variants are new rules.

## Rules (CRYPTO-1 gates `FxGates()`, costs BTC 24 / ETH 26 bps per side + 1 bp, 2× stress)

| Key | Rule | Hypothesis stated before the run |
|---|---|---|
| `crypto_h_donchian168_trail72` | baseline, unchanged | clean universe decides the near miss |
| `crypto_h_donchian168_trail120` | same entry/stop; exit channel 120 h instead of 72 h; 720 h safety | longer trail keeps more of a crypto trend (Hurst–Ooi–Pedersen horizon argument) at the cost of give-back |
| `crypto_h_donchian168_trail72_volx` | baseline entry only when ATR(24) ≥ ATR(168) | breakouts with expanding volatility persist more often; fewer trades, higher expectancy |

Expectation stated before the run: baseline ≈ +0.4R with CI low near zero; `trail120` higher
expectancy, wider CI; `volx` about a third fewer trades.

## Command

```
uv run signalforge crypto research-hourly --version CRYPTO-H4 --pairs BTCUSD,ETHUSD
```

Results: `RESULTS_round2_2026-11-03.md` (shared round-2 results file), section "CRYPTO-H4".
A development pass is a sealed-look *candidate* and stops there.
