# Research and paper-operation repair audit — 2026-11-02

This audit supersedes earlier claims of validated monthly portfolio income and the
CRYPTO-2 promotion claim. Raw locked evidence remains intact.

## Corrected findings

1. **BNB continuity invalidates the expanded crypto evidence.** The daily series has 1,742
   missing days between its first and last bar, with a maximum 1,735-day gap. The locked
   2025-11-03..2026-11-02 sealed window contains 244/365 bars, starting 2026-03-04. A fresh
   provider request for 2025-11-03..09 returned 0 bars and no pagination. The old test
   treated nonadjacent observations as adjacent calendar bars and could award a pass.
   `crypto_coverage_audit_2026-11-02.json` gives every pair's count. The fix adds fail-closed
   daily/hourly crypto continuity checks and refuses silently omitted requested pairs.
   Locked sealed rows 1–3 are preserved; none is rerun. CRYPTO-2's book has an audited data
   hold against new entries; it has zero positions, and the guard never prevents closing
   or marking a pre-existing position. Missed entries are stored as SKIPPED and never
   opened retrospectively. The hold is visible in the CLI and dashboard.
2. **Monthly income estimates were unsupported.** Fixed dollars per R times an unconstrained
   trade list is an illustration. It does not model capital, cash, concurrency, candidate
   selection or the daily paper cap. Adding 3-pair and 10-pair Donchian totals counts shared
   BTC/ETH/SOL exposure twice unless funded separately. Crypto books have an illustrative
   risk-dollar amount and no cash account; the previous "$90k total capital" denominator
   was not established. Portfolio forecasts and those aggregate totals are withdrawn.
3. **Annualisation had the wrong denominator.** The original script inferred history from
   the first trade in EXIT order and the final exit, ignoring idle months. It now uses the
   requested research window, includes zero-trade calendar months, exposes monthly R,
   and explicitly labels dollars as illustrations and drawdown as realised-exit-only.
4. **Intraday runtime was quadratic.** Opening-range queries repeatedly scanned every
   previous date. A chronological binary search finds the current session boundary and
   reads its opening bars only. A parity test covers all bars, three range lengths,
   daily input and shortened sessions. Benchmark for 100 late-history queries: the
   original full scan took 0.1704s; bounded scan 0.0003s (single local measurement).
   Coverage calendars now use one schedule query; expected counts remain exact, including
   holidays, daylight-saving changes and early closes.

## Operational state and evidence

- The configured equity open-risk limit remains 1.5%; the temporary 12.33% change was reverted.
- CRYPTO-2 stays a preserved, data-held experimental paper record; the numerical sealed
  pass is not sufficient to promote or forecast income. CRYPTO-3 retains its sealed fail.
- Existing approvals, kill switches and execution arming rules are unchanged.
- Source failures are fixed with tests. Provider gaps cannot be truthfully filled with
  interpolation or selectively deleted to force a pass. A repaired dataset requires a
  documented new evaluation and genuinely fresh prospective evidence.
- Corrected research run outputs and full-suite results are recorded below when complete.
