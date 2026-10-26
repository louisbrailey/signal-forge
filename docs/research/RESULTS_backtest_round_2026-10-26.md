# Results — unapproved-strategy backtest round (2026-10-26)

Pre-registration: `PREREGISTRATION_backtest_round_2026-10-26.md`, committed
before any 0.2.0 mean-reversion result existed.

## How it was run

- The full 10-gate promotion pipeline (`evaluate_promotion`), unchanged thresholds and cost model.
- Runs used a **scratch copy** of `data/signalforge.sqlite`. The live database has no new rows.
- Every run ended on **2025-09-07**, before the already-viewed sealed year (2025-09-08 to 2026-09-08).
  - Versions that already have a locked sealed test replayed it. That is not a new look.
  - Versions without one got a diagnostic "sealed" window of 2024-09-07 to 2025-09-07. That is development-period data inside the scratch copy only. It is **not** the real sealed test.
- Two universes:
  - snapshot #3, the 24 symbols the existing approvals are scoped to;
  - snapshot #11, the 150-symbol research selection.

## Results (gates 1–8, development window)

| Strategy | Version | 24 symbols | 150 symbols | Failing gates |
|---|---|---|---|---|
| relative_strength.medium_swing | 0.1.0 | **PASS** (197 trades, +0.30R, CI low +0.09R) | **PASS** (1,556 trades, +0.17R, CI low +0.10R) | none |
| volatility_breakout.short_swing | 0.2.0 | FAIL (25 trades, +0.36R) | FAIL (142 trades, +0.12R) | bootstrap CI (−0.07R); bear-regime coverage (4 trades, needs 10); on 24 symbols also min trades |
| mean_reversion.short_swing | 0.1.0 | FAIL (−0.08R) | — | expectancy, CI, sensitivity 0%, benchmark |
| mean_reversion.short_swing | **0.2.0** (new) | FAIL (+0.03R, CI low −0.08R) | FAIL (−0.05R, CI low −0.09R) | CI, regime coverage (24), benchmark; on 150: expectancy, sensitivity 0%, walk-forward |
| intraday_orb.intraday | 0.2.0 | FAIL at gate 0 | — | no intraday bars stored (0 of 2,010 sessions) |

Also re-run for context, unchanged:
- `trend_continuation.short_swing` passes all gates.
- `trend_continuation.medium_swing` passes gates 1–8.

## Disposition

1. **mean_reversion: documented fail.**
   - 0.2.0's single pre-registered change, the per-symbol SMA(200) filter, helped on 24 symbols: −0.08R became +0.03R, max drawdown fell from 38% to 18%, and sensitivity rose from 0% to 67%.
   - It still fails the confidence-interval gate on 24 symbols and fails clearly on 150 symbols.
   - Per the pre-registration there is no further iteration. 0.2.0 is kept in code because it is strictly less exposed to the named falling-knife failure. It stays EXPERIMENTAL.
2. **volatility_breakout 0.2.0: fail, structurally.**
   - Positive expectancy on both universes, all sensitivity points positive, and a Sharpe of 1.25 on 150 symbols.
   - It fails on statistical confidence, and it almost never trades in bear regimes because longs are blocked in risk-off conditions.
   - No parameter change is justified by this evidence. More history or a bear-market rule would have to be a new pre-registered hypothesis.
3. **relative_strength 0.1.0: passes everywhere, but its status is EXPERIMENTAL.**
   - The pipeline promoted it to PAPER_APPROVED on 2026-09-08 and again on 2026-09-11 (audit rows exist).
   - Today it is EXPERIMENTAL, and no audit row records that change.
   - This round does not change any status. **Operator decision required:** restore approval with an audit trail, or record why it was withdrawn.
4. **intraday_orb: blocked on data.** It needs 15-minute bars. The Stocks Advanced plan likely provides them, but ingesting them is a separate, operator-authorised data task.
5. **FX-1 and CRYPTO-1 failures: no new versions.** The reasons are in the pre-registration.

## Observations for the operator

- **Scope mismatch:** the live `approved_scope_scan` runs on 150 symbols with no dataset snapshot. The paper-probation document scopes approvals to snapshot #3. It is worth confirming the scan still matches the approved scopes.
- **No sealed look was taken this round.** A real sealed test for any new version would be look *k + 1* for its family and needs explicit authorisation.
