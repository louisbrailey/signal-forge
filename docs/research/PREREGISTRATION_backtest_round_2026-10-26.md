# Pre-registration — unapproved-strategy backtest round (2026-10-26)

Written **before** any result for the changed versions below was computed. Rules
R1–R4 in `STRATEGY_COMPLETION_MAP.md` apply: sealed data may decide disposition,
never design. Thresholds and the cost model are unchanged.

## Scope

| Strategy | Version(s) | Status before | What happens |
|---|---|---|---|
| mean_reversion.short_swing | 0.1.0 → **0.2.0** | EXPERIMENTAL, failing | one pre-registered change (below) |
| volatility_breakout.short_swing | 0.2.0 | never evaluated | evaluated unchanged |
| relative_strength.medium_swing | 0.1.0 | EXPERIMENTAL, but passed all 10 gates on 2026-09-11 | re-evaluated unchanged; status question goes to the operator |
| intraday_orb.intraday | 0.2.0 | blocked: no intraday bars | no change possible without intraday data |
| FX-1 (3 rules) | — | DEV_FAIL on 16 years | no new version (see below) |
| CRYPTO-1 tsmom / zfade | — | DEV_FAIL | no new version (see below) |

## The one design change: mean_reversion.short_swing 0.2.0

**Evidence used (development window only, pre-sealed span 2016-09-10..2025-09-07,
already recorded on 2026-09-11):** OOS expectancy −0.019R over 2,057 trades,
portfolio max drawdown 88%, turnover 681/yr, only 22% of sensitivity grid points
positive. No sealed number was consulted.

**Diagnosis:** the rule buys any large one-day drop as long as the *market*
regime is not bearish. That includes stocks in their own long-term downtrend —
the "falling knife" failure mode the spec already names.

**Change (single, pre-registered):** add a per-symbol long-term trend filter —
enter only when `close > SMA(200)` of that symbol. This is the standard
formulation of short-horizon pullback buying in the literature (buy dips in
names that are themselves in an uptrend). Every other parameter is unchanged:
z-lookback 20, z-entry −2.0, SMA(20) target, 2×ATR(14) stop, 6-session time stop.

**Pass/fail:** the unchanged 10 promotion gates. No further iteration in this
round: if 0.2.0 fails, the family is reported as failing.

## Why no new FX or crypto versions

FX-1's three classic rules all failed on 16 years and 8 pairs with very large
samples (261–676 OOS trades). The known structural gap — no swap/carry model
and no interest-rate data — cannot be fixed by re-parameterising the same rules,
and trying more variants on the same data would be data-mining. CRYPTO-1's two
failures are reported, not tuned; its one pass is already in paper trading.

## Sealed-look discipline

The diagnostic run ends on 2025-09-07, before the already-viewed sealed year
(2025-09-08..2026-09-08). Any new version's sealed test is look *k + 1* for its
family and is left for the operator to authorise; it is not run in this round.
