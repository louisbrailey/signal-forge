# Rejection breakdown — snapshot 17, pre-sealed span, counts only (2026-10-06)

**Status: read-only diagnostic.** Produced by `scripts/options_rejection_breakdown.py` against
the live database opened `mode=ro` (`sqlite3 file:...?mode=ro` + `PRAGMA query_only`). No
provider call, no write, no snapshot created, no sealed look consumed (k remains 0 for the
family: no `strategy` row begins `options`). The script replays the FROZEN
`options_short_vertical.medium_swing` v0.1.2 selection (`short_vertical.py`, D5 + D5a +
Amendment 2) stage by stage on every monthly cycle's signal session **on or before the
pre-sealed end 2025-09-03** (`--sealed-days 365`, the `options evaluate-promotion` default)
and records only the first stage that stops it. **No strategy parameter, threshold, floor,
width or pre-registration text was changed.**

**Disclosure (R5).** The frozen selection needs prices, IVs, deltas and adverse credits to
decide, so the script computes them in memory exactly as the step-8 dry run
(`IO2_RUNBOOK.md` §12.3) already did on this snapshot; nothing priced is written here. Every
figure below is a count, a strike identity, a date or a boolean. No P&L, return, credit value or
per-strike volume is reported. This is pre-sealed selection diagnostics on a snapshot whose
dry run has already been taken (checkpoint 2026-10-05: "evaluable, zero structures"); it is
not a look at the sealed span.

## 0. Headline

| | IWM | QQQ | SPY | total |
|---|---|---|---|---|
| signal sessions evaluated (pre-sealed) | 21 | 21 | 21 | **63** |
| stopped at (d) no wing at exactly $8 | 13 | 16 | 15 | **44** |
| … of which the exact wing strike is **NOT STORED** | 13 | 16 | 15 | **44** |
| … of which the exact wing is stored but not print-eligible | 0 | 0 | 0 | **0** |
| reached (f) credit floor (an exact $8 wing existed) | 5 | 1 | 5 | **11** |
| passed (f) credit floor | 0 | 0 | 0 | **0** |
| selectable structures | 0 | 0 | 0 | **0** |

1. **Stage (d) is a data-collection miss, not a liquidity miss.** In all 44 stage-(d) stops the
   strike at `K_short -/+ 8` is absent from `option_contract` for that expiry; in none of them
   is it stored-but-thin. The nearest stored width was 5, 6, 7, 9 or 10 (histogram in §2).
2. **Stage (f) stopped every session that reached it: 0 of 11.** Where the LADDER_17 rounding
   happened to put two stored strikes exactly $8 apart (SPY at the ~500-540 level, IWM where
   rungs 3-4 apart compound to 8), the short strike and wing were both print-eligible, the
   width was exact, and the adverse net credit was below 0.150 of width every time.
3. Stages (a), (q), (e) and (g) stopped nothing. Stage (b) stopped 6 sessions, all because the
   cycle's expiry has **no stored contracts at all**: run 44 excluded QQQ 2024-01-19
   (`insufficient_rungs_per_side`), QQQ 2024-02-16 (`reference_price_outside_ladder`), IWM
   2025-09-19 (`insufficient_rungs_per_side`) and 2025-04-17 on all three
   (`no_contracts_returned` — the backfill keyed the cycle as Good Friday 2025-04-18 while the
   exchange listed Thursday 04-17; see the plan's §C.4). Stage (c) stopped 2 (no OTM
   print-eligible strike landed within |delta| 0.20 +/- 0.05).

See `BACKFILL_PLAN_2026-10-06_dense_strikes.md` for what (1) and (2) imply together.

## 1. Logic, exactly as run

Script: `scripts/options_rejection_breakdown.py` (committed with this document). Inputs:
`data_snapshot.key = options_idx3_massive_2023-09-04_2026-09-04_0ae681d590` (id 17);
underlyings, window and `option_data.source` read from its `options_scope_json`; underlying
bars under `ohlcv_daily.source = 'massive'` (the evidence assembler's default), unadjusted
(`options_evidence.UNDERLYING_ADJUSTED = False`); `q` from `dividend_yield_daily`
(`source = 'vendor_dividends'`, exact session match, `None` otherwise — `build_q_lookup`'s
contract); warmup 50 sessions (`run_options_backtest` default).

SQL (parameterised; `?` are the symbol, labels and ISO dates):

```sql
SELECT id, symbols_json, options_scope_json FROM data_snapshot WHERE key = ?;

SELECT o.session_date, o.open, o.high, o.low, o.close, o.volume
FROM ohlcv_daily o JOIN instrument i ON i.id = o.instrument_id
WHERE i.symbol = ? AND o.source = ? AND o.session_date >= ? AND o.session_date <= ?
ORDER BY o.session_date;

SELECT option_ticker, underlying_symbol, contract_type, strike_price, expiration_date,
       shares_per_contract, exercise_style
FROM option_contract WHERE underlying_symbol = ? AND source = ?;

SELECT option_ticker, session_date, open, high, low, close, volume, vwap, transactions
FROM option_aggregate_daily
WHERE underlying_symbol = ? AND source = ? AND session_date >= ? AND session_date <= ?
ORDER BY session_date, option_ticker;

SELECT session_date, q FROM dividend_yield_daily WHERE symbol = ? AND source = ?;
```

The chain is assembled with `OptionChainSeries.from_rows` exactly as
`options_evidence.load_option_chain_series` does (`first_print_session` = the contract's first
stored bar; a contract is visible at `t` only once it has printed).

Per session `t` in `[50, n-1)` with `session_date <= 2025-09-03`, the strategy's own code is
replayed (`OptionsShortVertical._side`, `_selectable`, `_pick_short`, `_pick_wing`,
`_credit_floor_clears`, all unmodified) and classified by the first failing stage:

| stage | predicate (frozen code) |
|---|---|
| `a_no_chain_rows` | `chain.head(t).printed_tickers(t)` empty, or underlying close <= 0 |
| `b_no_expiry_in_dte_window` | `_cycle_expiry` arithmetic yields no expiry: no visible monthly expiry with DTE <= 35 whose previous session was > 35, or the first such session has DTE outside [28, 45]. Sub-reason recorded (no contracts stored / not yet printed / window skip). Sessions that are not any cycle's first DTE <= 35 session are not counted at all. |
| `q_missing` | `q_lookup(symbol, today) is None` (gate 0.g non-entry) |
| `e_no_print_eligible_leg` | `_selectable(...)` empty: no contract on that expiry/side with `volume >= 10` and `transactions >= 5` (or `shares_per_contract != 100`) |
| `c_no_short_in_delta_band` | `_pick_short` returns none: no OTM print-eligible strike whose own-print inverted IV gives abs(delta) <= 0.35 and within 0.05 of 0.20 |
| `d_no_wing_at_exact_width` | `_pick_wing` finds no further-OTM print-eligible strike, or the nearest one is not within 1e-3 of `K_short -/+ 8.00` (`width_tolerance_pct = 0.0`) |
| `f_credit_floor` | `_credit_floor_clears` false: `net_credit <= 0` or `net_credit / (8 x 100) < 0.150 - 1e-9` at the ADVERSE modelled fill, baseline cost model |
| `g_op1_risk_fit` | `8 x 100 + commission(2) + fees(2) = $801.60 > $900` — structurally never true at v0.1.2 |
| `selectable` | every stage cleared |

Two disclosed differences from the engine: the funnel evaluates every cycle's signal session
(the engine would skip one while a prior structure is open — at 35 DTE the prior cycle's
7-DTE time stop precedes the next signal session, so the bound is tight), and the stage-(d)
counterfactuals (`exact wing stored`, `exact wing print-eligible`, nearest realised width) are
computed on the stored chain for this report only; the strategy never computes them.

Strike-grid section: distinct `option_contract.strike_price` per (underlying, expiry <=
2025-09-03, right); median consecutive spacing; spacing histogram; the three strike-to-strike
distances (over all pairs up to $16 apart) nearest to $8; and the count of strike pairs exactly
$8 apart.

## 2. Script output (verbatim)

# Rejection breakdown — snapshot 17 (`options_idx3_massive_2023-09-04_2026-09-04_0ae681d590`)

Underlyings IWM, QQQ, SPY; window 2023-09-04 .. 2026-09-04; **pre-sealed span only: signal sessions on or before 2025-09-03**; option source `massive_options`; underlying bars `massive`; ingestion run(s) [44]; database opened `mode=ro` at `/Users/louisbrailey/Projects/signal-forge/data/signalforge.sqlite`.

Frozen parameters replayed (v0.1.2, not changed here): short |delta| target 0.2 +/- 0.05, cap 0.35; DTE target 35 in [28, 45]; width EXACTLY $8.00 (tolerance 0%); credit floor 0.15 of width at the adverse fill; print eligibility volume >= 10, transactions >= 5; OP-1 cap $900.

## Funnel — counts of signal sessions by the FIRST stage that stops them

| stage | IWM | QQQ | SPY | total |
|---|---|---|---|---|
| chain sessions (pre-sealed) | 501 | 501 | 501 | 1503 |
| signal sessions evaluated | 21 | 21 | 21 | 63 |
| a_no_chain_rows | 0 | 0 | 0 | 0 |
| b_no_expiry_in_dte_window | 2 | 3 | 1 | 6 |
| q_missing | 0 | 0 | 0 | 0 |
| e_no_print_eligible_leg | 0 | 0 | 0 | 0 |
| c_no_short_in_delta_band | 1 | 1 | 0 | 2 |
| d_no_wing_at_exact_width | 13 | 16 | 15 | 44 |
| f_credit_floor | 5 | 1 | 5 | 11 |
| g_op1_risk_fit | 0 | 0 | 0 | 0 |
| selectable | 0 | 0 | 0 | 0 |

### Stage (d) decomposition — where the exact $8 wing went

| underlying | d total | exact wing STORED but not print-eligible | exact wing NOT STORED | nearest realised width histogram (width: sessions) |
|---|---|---|---|---|
| IWM | 13 | 0 | 13 | 6: 1, 7: 4, 9: 4, 10: 4 |
| QQQ | 16 | 0 | 16 | 5: 6, 6: 1, 9: 1, 10: 7 |
| SPY | 15 | 0 | 15 | 5: 1, 7: 4, 9: 6, 10: 3 |

### Conditional pass rates (counts only)

| underlying | reached (c) | passed (c) | reached (d) | passed (d) | reached (f) | passed (f) | selectable |
|---|---|---|---|---|---|---|---|
| IWM | 19 | 18 (95%) | 18 | 5 (28%) | 5 | 0 (0%) | 0 |
| QQQ | 18 | 17 (94%) | 17 | 1 (6%) | 1 | 0 (0%) | 0 |
| SPY | 20 | 20 (100%) | 20 | 5 (25%) | 5 | 0 (0%) | 0 |

### Per-signal-session records (identities only)

| underlying | session | expiry | DTE | side | stage | K_short | wing target | nearest width | exact wing stored | exact wing eligible | OTM eligible | OTM invertible | note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| IWM | 2023-12-15 | 2024-01-19 | 35 | put | f_credit_floor | 187 | 179 | 8 | True | True | 13 | 13 | - |
| IWM | 2024-01-12 | 2024-02-16 | 35 | put | f_credit_floor | 185 | 177 | 8 | True | True | 7 | 7 | - |
| IWM | 2024-02-09 | 2024-03-15 | 35 | put | d_no_wing_at_exact_width | 191 | 183 | 9 | False | False | 10 | 10 | exact wing strike not stored |
| IWM | 2024-03-15 | 2024-04-19 | 35 | put | d_no_wing_at_exact_width | 193 | 185 | 10 | False | False | 9 | 9 | exact wing strike not stored |
| IWM | 2024-04-12 | 2024-05-17 | 35 | put | f_credit_floor | 189 | 181 | 8 | True | True | 7 | 7 | - |
| IWM | 2024-05-17 | 2024-06-21 | 35 | put | d_no_wing_at_exact_width | 198 | 190 | 9 | False | False | 12 | 12 | exact wing strike not stored |
| IWM | 2024-06-14 | 2024-07-19 | 35 | put | d_no_wing_at_exact_width | 188 | 180 | 10 | False | False | 5 | 5 | exact wing strike not stored |
| IWM | 2024-07-12 | 2024-08-16 | 35 | put | d_no_wing_at_exact_width | 203 | 195 | 9 | False | False | 12 | 12 | exact wing strike not stored |
| IWM | 2024-08-16 | 2024-09-20 | 35 | put | d_no_wing_at_exact_width | 203 | 195 | 10 | False | False | 6 | 6 | exact wing strike not stored |
| IWM | 2024-09-13 | 2024-10-18 | 35 | put | f_credit_floor | 206 | 198 | 8 | True | True | 8 | 8 | - |
| IWM | 2024-10-11 | 2024-11-15 | 35 | put | f_credit_floor | 208 | 200 | 8 | True | True | 10 | 10 | - |
| IWM | 2024-11-15 | 2024-12-20 | 35 | put | d_no_wing_at_exact_width | 215 | 207 | 6 | False | False | 9 | 9 | exact wing strike not stored |
| IWM | 2024-12-13 | 2025-01-17 | 35 | put | d_no_wing_at_exact_width | 222 | 214 | 7 | False | False | 9 | 9 | exact wing strike not stored |
| IWM | 2025-01-17 | 2025-02-21 | 35 | put | d_no_wing_at_exact_width | 215 | 207 | 7 | False | False | 8 | 8 | exact wing strike not stored |
| IWM | 2025-02-14 | 2025-03-21 | 35 | put | d_no_wing_at_exact_width | 216 | 208 | 9 | False | False | 7 | 7 | exact wing strike not stored |
| IWM | 2025-03-13 | 2025-04-17 | - | - | b_no_expiry_in_dte_window | - | - | - | - | - | - | - | no contracts stored for expiry 2025-04-17 |
| IWM | 2025-04-11 | 2025-05-16 | 35 | call | d_no_wing_at_exact_width | 202 | 210 | 7 | False | False | 11 | 11 | exact wing strike not stored |
| IWM | 2025-05-16 | 2025-06-20 | 35 | call | c_no_short_in_delta_band | - | - | - | - | - | 1 | 1 | - |
| IWM | 2025-06-13 | 2025-07-18 | 35 | call | d_no_wing_at_exact_width | 220 | 228 | 10 | False | False | 8 | 8 | exact wing strike not stored |
| IWM | 2025-07-11 | 2025-08-15 | 35 | put | d_no_wing_at_exact_width | 208 | 200 | 7 | False | False | 9 | 9 | exact wing strike not stored |
| IWM | 2025-08-15 | 2025-09-19 | - | - | b_no_expiry_in_dte_window | - | - | - | - | - | - | - | no contracts stored for expiry 2025-09-19 |
| QQQ | 2023-12-15 | 2024-01-19 | - | - | b_no_expiry_in_dte_window | - | - | - | - | - | - | - | no contracts stored for expiry 2024-01-19 |
| QQQ | 2024-01-12 | 2024-02-16 | - | - | b_no_expiry_in_dte_window | - | - | - | - | - | - | - | no contracts stored for expiry 2024-02-16 |
| QQQ | 2024-02-09 | 2024-03-15 | 35 | put | d_no_wing_at_exact_width | 422 | 414 | 6.22 | False | False | 10 | 10 | exact wing strike not stored |
| QQQ | 2024-03-15 | 2024-04-19 | 35 | put | d_no_wing_at_exact_width | 414.78 | 406.78 | 5 | False | False | 9 | 9 | exact wing strike not stored |
| QQQ | 2024-04-12 | 2024-05-17 | 35 | put | d_no_wing_at_exact_width | 419.78 | 411.78 | 9.78 | False | False | 7 | 7 | exact wing strike not stored |
| QQQ | 2024-05-17 | 2024-06-21 | 35 | put | c_no_short_in_delta_band | - | - | - | - | - | 9 | 9 | - |
| QQQ | 2024-06-14 | 2024-07-19 | 35 | put | d_no_wing_at_exact_width | 460 | 452 | 10 | False | False | 11 | 11 | exact wing strike not stored |
| QQQ | 2024-07-12 | 2024-08-16 | 35 | put | d_no_wing_at_exact_width | 470 | 462 | 5 | False | False | 10 | 10 | exact wing strike not stored |
| QQQ | 2024-08-16 | 2024-09-20 | 35 | put | d_no_wing_at_exact_width | 454.78 | 446.78 | 10 | False | False | 8 | 8 | exact wing strike not stored |
| QQQ | 2024-09-13 | 2024-10-18 | 35 | put | d_no_wing_at_exact_width | 450 | 442 | 5 | False | False | 8 | 8 | exact wing strike not stored |
| QQQ | 2024-10-11 | 2024-11-15 | 35 | put | d_no_wing_at_exact_width | 465 | 457 | 5 | False | False | 11 | 11 | exact wing strike not stored |
| QQQ | 2024-11-15 | 2024-12-20 | 35 | put | d_no_wing_at_exact_width | 474.78 | 466.78 | 9.78 | False | False | 9 | 9 | exact wing strike not stored |
| QQQ | 2024-12-13 | 2025-01-17 | 35 | put | d_no_wing_at_exact_width | 509.78 | 501.78 | 9.78 | False | False | 11 | 11 | exact wing strike not stored |
| QQQ | 2025-01-17 | 2025-02-21 | 35 | put | d_no_wing_at_exact_width | 500 | 492 | 10 | False | False | 8 | 8 | exact wing strike not stored |
| QQQ | 2025-02-14 | 2025-03-21 | 35 | put | d_no_wing_at_exact_width | 515 | 507 | 5 | False | False | 9 | 9 | exact wing strike not stored |
| QQQ | 2025-03-13 | 2025-04-17 | - | - | b_no_expiry_in_dte_window | - | - | - | - | - | - | - | no contracts stored for expiry 2025-04-17 |
| QQQ | 2025-04-11 | 2025-05-16 | 35 | put | d_no_wing_at_exact_width | 415 | 407 | - | False | False | 4 | 4 | no print-eligible strike further OTM than K_short at all |
| QQQ | 2025-05-16 | 2025-06-20 | 35 | put | d_no_wing_at_exact_width | 494.78 | 486.78 | 10 | False | False | 13 | 13 | exact wing strike not stored |
| QQQ | 2025-06-13 | 2025-07-18 | 35 | put | f_credit_floor | 499 | 491 | 8 | True | True | 9 | 9 | - |
| QQQ | 2025-07-11 | 2025-08-15 | 35 | put | d_no_wing_at_exact_width | 525 | 517 | 5 | False | False | 11 | 11 | exact wing strike not stored |
| QQQ | 2025-08-15 | 2025-09-19 | 35 | put | d_no_wing_at_exact_width | 556 | 548 | 9 | False | False | 9 | 9 | exact wing strike not stored |
| SPY | 2023-12-15 | 2024-01-19 | 35 | put | d_no_wing_at_exact_width | 454 | 446 | 7 | False | False | 10 | 10 | exact wing strike not stored |
| SPY | 2024-01-12 | 2024-02-16 | 35 | put | d_no_wing_at_exact_width | 465 | 457 | 7 | False | False | 6 | 6 | exact wing strike not stored |
| SPY | 2024-02-09 | 2024-03-15 | 35 | put | d_no_wing_at_exact_width | 489 | 481 | 7 | False | False | 9 | 9 | exact wing strike not stored |
| SPY | 2024-03-15 | 2024-04-19 | 35 | put | d_no_wing_at_exact_width | 489 | 481 | 7 | False | False | 9 | 9 | exact wing strike not stored |
| SPY | 2024-04-12 | 2024-05-17 | 35 | put | f_credit_floor | 490 | 482 | 8 | True | True | 8 | 8 | - |
| SPY | 2024-05-17 | 2024-06-21 | 35 | put | f_credit_floor | 515 | 507 | 8 | True | True | 11 | 11 | - |
| SPY | 2024-06-14 | 2024-07-19 | 35 | put | f_credit_floor | 530 | 522 | 8 | True | True | 7 | 7 | - |
| SPY | 2024-07-12 | 2024-08-16 | 35 | put | d_no_wing_at_exact_width | 545 | 537 | 5 | False | False | 7 | 7 | exact wing strike not stored |
| SPY | 2024-08-16 | 2024-09-20 | 35 | put | f_credit_floor | 538 | 530 | 8 | True | True | 8 | 8 | - |
| SPY | 2024-09-13 | 2024-10-18 | 35 | put | d_no_wing_at_exact_width | 543 | 535 | 9 | False | False | 9 | 9 | exact wing strike not stored |
| SPY | 2024-10-11 | 2024-11-15 | 35 | put | f_credit_floor | 554 | 546 | 8 | True | True | 10 | 10 | - |
| SPY | 2024-11-15 | 2024-12-20 | 35 | put | d_no_wing_at_exact_width | 566 | 558 | 9 | False | False | 9 | 9 | exact wing strike not stored |
| SPY | 2024-12-13 | 2025-01-17 | 35 | put | d_no_wing_at_exact_width | 588 | 580 | 9 | False | False | 10 | 10 | exact wing strike not stored |
| SPY | 2025-01-17 | 2025-02-21 | 35 | put | d_no_wing_at_exact_width | 577 | 569 | 9 | False | False | 9 | 9 | exact wing strike not stored |
| SPY | 2025-02-14 | 2025-03-21 | 35 | put | d_no_wing_at_exact_width | 585 | 577 | 9 | False | False | 9 | 9 | exact wing strike not stored |
| SPY | 2025-03-13 | 2025-04-17 | - | - | b_no_expiry_in_dte_window | - | - | - | - | - | - | - | no contracts stored for expiry 2025-04-17 |
| SPY | 2025-04-11 | 2025-05-16 | 35 | put | d_no_wing_at_exact_width | 485 | 477 | - | False | False | 5 | 5 | no print-eligible strike further OTM than K_short at all |
| SPY | 2025-05-16 | 2025-06-20 | 35 | put | d_no_wing_at_exact_width | 565 | 557 | 10 | False | False | 17 | 17 | exact wing strike not stored |
| SPY | 2025-06-13 | 2025-07-18 | 35 | put | d_no_wing_at_exact_width | 568 | 560 | 9 | False | False | 9 | 9 | exact wing strike not stored |
| SPY | 2025-07-11 | 2025-08-15 | 35 | put | d_no_wing_at_exact_width | 595 | 587 | 10 | False | False | 9 | 9 | exact wing strike not stored |
| SPY | 2025-08-15 | 2025-09-19 | 35 | put | d_no_wing_at_exact_width | 620 | 612 | 10 | False | False | 10 | 10 | exact wing strike not stored |

## Stored strike grid per (underlying, expiry, right)

| underlying | expiry | right | n | min | max | median spacing | spacing histogram | widths nearest $8 | pairs exactly $8 |
|---|---|---|---|---|---|---|---|---|---|
| IWM | 2023-11-17 | call | 17 | 156 | 209 | 3 | 2: 2, 3: 7, 4: 7 | 8, 7, 9 | 9 |
| IWM | 2023-11-17 | put | 16 | 156 | 205 | 3 | 2: 2, 3: 7, 4: 6 | 8, 7, 9 | 8 |
| IWM | 2023-12-15 | call | 17 | 148 | 198 | 3 | 2: 4, 3: 8, 4: 2, 5: 2 | 8, 7, 9 | 8 |
| IWM | 2023-12-15 | put | 17 | 148 | 198 | 3 | 2: 4, 3: 8, 4: 2, 5: 2 | 8, 7, 9 | 8 |
| IWM | 2024-01-19 | call | 17 | 153 | 205 | 3 | 2: 3, 3: 7, 4: 5, 5: 1 | 8, 7, 9 | 10 |
| IWM | 2024-01-19 | put | 17 | 153 | 205 | 3 | 2: 3, 3: 7, 4: 5, 5: 1 | 8, 7, 9 | 10 |
| IWM | 2024-02-16 | call | 17 | 168 | 225 | 3 | 3: 9, 4: 5, 5: 2 | 8, 7, 9 | 3 |
| IWM | 2024-02-16 | put | 17 | 168 | 225 | 3 | 3: 9, 4: 5, 5: 2 | 8, 7, 9 | 3 |
| IWM | 2024-03-15 | call | 17 | 163 | 219 | 3 | 2: 1, 3: 8, 4: 5, 5: 2 | 8, 7, 9 | 3 |
| IWM | 2024-03-15 | put | 17 | 163 | 219 | 3 | 2: 1, 3: 8, 4: 5, 5: 2 | 8, 7, 9 | 3 |
| IWM | 2024-04-19 | call | 17 | 170 | 225 | 3 | 1: 1, 3: 8, 4: 5, 5: 2 | 8, 7, 9 | 2 |
| IWM | 2024-04-19 | put | 17 | 170 | 225 | 3 | 1: 1, 3: 8, 4: 5, 5: 2 | 8, 7, 9 | 2 |
| IWM | 2024-05-17 | call | 17 | 172 | 230 | 3.5 | 3: 8, 4: 6, 5: 2 | 8, 7, 9 | 3 |
| IWM | 2024-05-17 | put | 17 | 172 | 230 | 3.5 | 3: 8, 4: 6, 5: 2 | 8, 7, 9 | 3 |
| IWM | 2024-06-21 | call | 17 | 167 | 224 | 3.5 | 2: 1, 3: 7, 4: 6, 5: 2 | 8, 7, 9 | 4 |
| IWM | 2024-06-21 | put | 17 | 167 | 224 | 3.5 | 2: 1, 3: 7, 4: 6, 5: 2 | 8, 7, 9 | 4 |
| IWM | 2024-07-19 | call | 16 | 178 | 235 | 4 | 2: 1, 3: 6, 4: 4, 5: 3, 6: 1 | 8, 7, 9 | 2 |
| IWM | 2024-07-19 | put | 16 | 178 | 235 | 4 | 2: 1, 3: 6, 4: 4, 5: 3, 6: 1 | 8, 7, 9 | 2 |
| IWM | 2024-08-16 | call | 17 | 171 | 230 | 3.5 | 3: 8, 4: 5, 5: 3 | 8, 7, 9 | 2 |
| IWM | 2024-08-16 | put | 17 | 171 | 230 | 3.5 | 3: 8, 4: 5, 5: 3 | 8, 7, 9 | 2 |
| IWM | 2024-09-20 | call | 16 | 188 | 250 | 4 | 2: 1, 3: 5, 4: 5, 5: 3, 10: 1 | 8, 7, 9 | 1 |
| IWM | 2024-09-20 | put | 16 | 188 | 250 | 4 | 2: 1, 3: 5, 4: 5, 5: 3, 10: 1 | 8, 7, 9 | 1 |
| IWM | 2024-10-18 | call | 17 | 183 | 245 | 4 | 3: 7, 4: 5, 5: 3, 6: 1 | 8, 7, 9 | 4 |
| IWM | 2024-10-18 | put | 17 | 183 | 245 | 4 | 3: 7, 4: 5, 5: 3, 6: 1 | 8, 7, 9 | 4 |
| IWM | 2024-11-15 | call | 17 | 185 | 250 | 4 | 3: 6, 4: 5, 5: 3, 6: 2 | 8, 7, 9 | 3 |
| IWM | 2024-11-15 | put | 17 | 185 | 250 | 4 | 3: 6, 4: 5, 5: 3, 6: 2 | 8, 7, 9 | 3 |
| IWM | 2024-12-20 | call | 17 | 189 | 255 | 4.5 | 1: 1, 3: 4, 4: 3, 5: 7, 6: 1 | 8, 7, 9 | 2 |
| IWM | 2024-12-20 | put | 17 | 189 | 255 | 4.5 | 1: 1, 3: 4, 4: 3, 5: 7, 6: 1 | 8, 7, 9 | 2 |
| IWM | 2025-01-17 | call | 17 | 195 | 263 | 4 | 3: 4, 4: 6, 5: 4, 6: 2 | 8, 7, 9 | 2 |
| IWM | 2025-01-17 | put | 15 | 195 | 252 | 4 | 3: 4, 4: 6, 5: 3, 6: 1 | 8, 7, 9 | 2 |
| IWM | 2025-02-21 | call | 17 | 189 | 254 | 4 | 3: 5, 4: 5, 5: 6 | 8, 7, 9 | 1 |
| IWM | 2025-02-21 | put | 17 | 189 | 254 | 4 | 3: 5, 4: 5, 5: 6 | 8, 7, 9 | 1 |
| IWM | 2025-03-21 | call | 17 | 196 | 264 | 4 | 3: 4, 4: 6, 5: 4, 6: 2 | 8, 7, 9 | 2 |
| IWM | 2025-03-21 | put | 16 | 196 | 259 | 4 | 3: 4, 4: 6, 5: 3, 6: 2 | 8, 7, 9 | 2 |
| IWM | 2025-05-16 | call | 17 | 175 | 236 | 4 | 3: 7, 4: 5, 5: 4 | 8, 7, 9 | 2 |
| IWM | 2025-05-16 | put | 17 | 175 | 236 | 4 | 3: 7, 4: 5, 5: 4 | 8, 7, 9 | 2 |
| IWM | 2025-06-20 | call | 17 | 156 | 210 | 3 | 2: 2, 3: 7, 4: 6, 5: 1 | 8, 7, 9 | 8 |
| IWM | 2025-06-20 | put | 17 | 156 | 210 | 3 | 2: 2, 3: 7, 4: 6, 5: 1 | 8, 7, 9 | 8 |
| IWM | 2025-07-18 | call | 16 | 178 | 240 | 4 | 3: 5, 4: 3, 5: 7 | 8, 7, 9 | 3 |
| IWM | 2025-07-18 | put | 16 | 178 | 240 | 4 | 3: 5, 4: 3, 5: 7 | 8, 7, 9 | 3 |
| IWM | 2025-08-15 | call | 16 | 180 | 240 | 4 | 1: 1, 3: 4, 4: 4, 5: 5, 6: 1 | 8, 7, 9 | 1 |
| IWM | 2025-08-15 | put | 16 | 180 | 240 | 4 | 1: 1, 3: 4, 4: 4, 5: 5, 6: 1 | 8, 7, 9 | 1 |
| QQQ | 2023-11-17 | call | 17 | 316 | 425 | 6 | 5: 3, 6: 6, 7: 1, 8: 4, 9: 1, 10: 1 | 8, 7, 9 | 4 |
| QQQ | 2023-11-17 | put | 17 | 316 | 425 | 6 | 5: 3, 6: 6, 7: 1, 8: 4, 9: 1, 10: 1 | 8, 7, 9 | 4 |
| QQQ | 2023-12-15 | call | 17 | 314 | 420 | 6 | 4: 1, 5: 3, 6: 5, 7: 3, 8: 1, 9: 2, 10: 1 | 8, 7, 9 | 1 |
| QQQ | 2023-12-15 | put | 17 | 314 | 420 | 6 | 4: 1, 5: 3, 6: 5, 7: 3, 8: 1, 9: 2, 10: 1 | 8, 7, 9 | 1 |
| QQQ | 2024-03-15 | call | 17 | 348.78 | 470 | 6.61 | 5.78: 1, 6: 6, 6.22: 1, 7: 1, 8: 1, 8.22: 1, 10: 5 | 8, 8.22, 7 | 1 |
| QQQ | 2024-03-15 | put | 17 | 348.78 | 470 | 6.61 | 5.78: 1, 6: 6, 6.22: 1, 7: 1, 8: 1, 8.22: 1, 10: 5 | 8, 8.22, 7 | 1 |
| QQQ | 2024-04-19 | call | 17 | 364.78 | 490 | 8 | 5: 1, 5.22: 2, 6: 4, 8: 2, 9.78: 1, 10: 6 | 8, 9.78, 6 | 2 |
| QQQ | 2024-04-19 | put | 17 | 364.78 | 490 | 8 | 5: 1, 5.22: 2, 6: 4, 8: 2, 9.78: 1, 10: 6 | 8, 9.78, 6 | 2 |
| QQQ | 2024-05-17 | call | 17 | 374.78 | 500 | 9.78 | 5: 3, 5.22: 4, 9.78: 3, 10: 6 | 9.78, 10, 10.22 | 0 |
| QQQ | 2024-05-17 | put | 17 | 374.78 | 500 | 9.78 | 5: 3, 5.22: 4, 9.78: 3, 10: 6 | 9.78, 10, 10.22 | 0 |
| QQQ | 2024-06-21 | call | 17 | 356.78 | 481 | 8.61 | 5: 4, 5.22: 2, 7.22: 1, 8.22: 1, 9: 1, 9.78: 3, 10: 4 | 8.22, 7.22, 9 | 0 |
| QQQ | 2024-06-21 | put | 17 | 356.78 | 481 | 8.61 | 5: 4, 5.22: 2, 7.22: 1, 8.22: 1, 9: 1, 9.78: 3, 10: 4 | 8.22, 7.22, 9 | 0 |
| QQQ | 2024-07-19 | call | 17 | 390 | 520 | 9 | 5: 4, 6: 1, 7: 1, 9: 3, 10: 7 | 7, 9, 6 | 0 |
| QQQ | 2024-07-19 | put | 17 | 390 | 520 | 9 | 5: 4, 6: 1, 7: 1, 9: 3, 10: 7 | 7, 9, 6 | 0 |
| QQQ | 2024-08-16 | call | 17 | 415 | 555 | 10 | 5: 4, 10: 12 | 10, 5, 15 | 0 |
| QQQ | 2024-08-16 | put | 17 | 415 | 555 | 10 | 5: 4, 10: 12 | 10, 5, 15 | 0 |
| QQQ | 2024-09-20 | call | 17 | 410 | 550 | 9.78 | 5: 1, 5.22: 5, 9.78: 3, 10: 5, 14.78: 2 | 9.78, 10, 10.22 | 0 |
| QQQ | 2024-09-20 | put | 17 | 410 | 550 | 9.78 | 5: 1, 5.22: 5, 9.78: 3, 10: 5, 14.78: 2 | 9.78, 10, 10.22 | 0 |
| QQQ | 2024-10-18 | call | 17 | 410 | 550 | 10 | 5: 5, 10: 10, 15: 1 | 10, 5, 15 | 0 |
| QQQ | 2024-10-18 | put | 17 | 410 | 550 | 10 | 5: 5, 10: 10, 15: 1 | 10, 5, 15 | 0 |
| QQQ | 2024-11-15 | call | 17 | 405 | 540 | 10 | 5: 5, 10: 11 | 10, 5, 15 | 0 |
| QQQ | 2024-11-15 | put | 17 | 405 | 540 | 10 | 5: 5, 10: 11 | 10, 5, 15 | 0 |
| QQQ | 2024-12-20 | call | 17 | 424.78 | 565 | 9.89 | 5.22: 3, 7: 1, 8: 1, 9.78: 3, 10: 7, 10.22: 1 | 8, 7, 9.78 | 1 |
| QQQ | 2024-12-20 | put | 16 | 424.78 | 555 | 9.78 | 5.22: 3, 7: 1, 8: 1, 9.78: 3, 10: 6, 10.22: 1 | 8, 7, 9.78 | 1 |
| QQQ | 2025-01-17 | call | 17 | 429.78 | 574.78 | 9.89 | 5: 1, 5.22: 3, 9.78: 4, 10: 6, 10.22: 1, 15: 1 | 9.78, 10, 10.22 | 0 |
| QQQ | 2025-01-17 | put | 17 | 429.78 | 574.78 | 9.89 | 5: 1, 5.22: 3, 9.78: 4, 10: 6, 10.22: 1, 15: 1 | 9.78, 10, 10.22 | 0 |
| QQQ | 2025-02-21 | call | 17 | 445 | 600 | 10 | 5: 3, 10: 11, 15: 2 | 10, 5, 15 | 0 |
| QQQ | 2025-02-21 | put | 17 | 445 | 600 | 10 | 5: 3, 10: 11, 15: 2 | 10, 5, 15 | 0 |
| QQQ | 2025-03-21 | call | 17 | 447 | 600 | 10 | 5: 4, 10: 9, 13: 1, 15: 2 | 10, 5, 13 | 0 |
| QQQ | 2025-03-21 | put | 17 | 447 | 600 | 10 | 5: 4, 10: 9, 13: 1, 15: 2 | 10, 5, 13 | 0 |
| QQQ | 2025-05-16 | call | 17 | 415 | 555 | 9.5 | 5: 5, 8: 1, 9: 2, 10: 5, 12: 2, 15: 1 | 8, 9, 10 | 1 |
| QQQ | 2025-05-16 | put | 17 | 415 | 555 | 9.5 | 5: 5, 8: 1, 9: 2, 10: 5, 12: 2, 15: 1 | 8, 9, 10 | 1 |
| QQQ | 2025-06-20 | call | 17 | 369.78 | 494.78 | 9.78 | 5: 4, 5.22: 3, 9.78: 3, 10: 6 | 9.78, 10, 10.22 | 0 |
| QQQ | 2025-06-20 | put | 17 | 369.78 | 494.78 | 9.78 | 5: 4, 5.22: 3, 9.78: 3, 10: 6 | 9.78, 10, 10.22 | 0 |
| QQQ | 2025-07-18 | call | 17 | 445 | 600 | 9.5 | 7: 1, 8: 6, 9: 1, 10: 5, 11: 1, 15: 2 | 8, 7, 9 | 6 |
| QQQ | 2025-07-18 | put | 17 | 445 | 600 | 9.5 | 7: 1, 8: 6, 9: 1, 10: 5, 11: 1, 15: 2 | 8, 7, 9 | 6 |
| QQQ | 2025-08-15 | call | 17 | 455 | 610 | 10 | 5: 3, 10: 11, 15: 2 | 10, 5, 15 | 0 |
| QQQ | 2025-08-15 | put | 17 | 455 | 610 | 10 | 5: 3, 10: 11, 15: 2 | 10, 5, 15 | 0 |
| SPY | 2023-11-17 | call | 17 | 380 | 510 | 7.5 | 6: 3, 7: 5, 8: 1, 9: 3, 10: 3, 12: 1 | 8, 7, 9 | 1 |
| SPY | 2023-11-17 | put | 17 | 380 | 510 | 7.5 | 6: 3, 7: 5, 8: 1, 9: 3, 10: 3, 12: 1 | 8, 7, 9 | 1 |
| SPY | 2023-12-15 | call | 17 | 371 | 501 | 8 | 6: 4, 7: 4, 9: 4, 10: 2, 11: 2 | 7, 9, 6 | 0 |
| SPY | 2023-12-15 | put | 17 | 371 | 501 | 8 | 6: 4, 7: 4, 9: 4, 10: 2, 11: 2 | 7, 9, 6 | 0 |
| SPY | 2024-01-19 | call | 17 | 387 | 520 | 8 | 6: 2, 7: 5, 8: 2, 9: 2, 10: 4, 12: 1 | 8, 7, 9 | 2 |
| SPY | 2024-01-19 | put | 17 | 387 | 520 | 8 | 6: 2, 7: 5, 8: 2, 9: 2, 10: 4, 12: 1 | 8, 7, 9 | 2 |
| SPY | 2024-02-16 | call | 17 | 402 | 540 | 8 | 7: 8, 9: 1, 10: 5, 11: 1, 12: 1 | 7, 9, 10 | 0 |
| SPY | 2024-02-16 | put | 16 | 402 | 530 | 7 | 7: 8, 9: 1, 10: 4, 11: 1, 12: 1 | 7, 9, 10 | 0 |
| SPY | 2024-03-15 | call | 17 | 404 | 545 | 8 | 7: 6, 8: 3, 9: 1, 10: 3, 11: 1, 12: 1, 13: 1 | 8, 7, 9 | 3 |
| SPY | 2024-03-15 | put | 17 | 404 | 545 | 8 | 7: 6, 8: 3, 9: 1, 10: 3, 11: 1, 12: 1, 13: 1 | 8, 7, 9 | 3 |
| SPY | 2024-04-19 | call | 17 | 425 | 570 | 8 | 7: 4, 8: 5, 10: 5, 12: 1, 15: 1 | 8, 7, 10 | 5 |
| SPY | 2024-04-19 | put | 17 | 425 | 570 | 8 | 7: 4, 8: 5, 10: 5, 12: 1, 15: 1 | 8, 7, 10 | 5 |
| SPY | 2024-05-17 | call | 17 | 440 | 585 | 9 | 7: 2, 8: 5, 9: 2, 10: 6, 13: 1 | 8, 7, 9 | 5 |
| SPY | 2024-05-17 | put | 17 | 440 | 585 | 9 | 7: 2, 8: 5, 9: 2, 10: 6, 13: 1 | 8, 7, 9 | 5 |
| SPY | 2024-06-21 | call | 17 | 425 | 570 | 9 | 7: 4, 8: 4, 10: 6, 12: 1, 13: 1 | 8, 7, 10 | 4 |
| SPY | 2024-06-21 | put | 17 | 425 | 570 | 9 | 7: 4, 8: 4, 10: 6, 12: 1, 13: 1 | 8, 7, 10 | 4 |
| SPY | 2024-07-19 | call | 17 | 455 | 605 | 9.5 | 5: 1, 7: 1, 8: 5, 9: 1, 10: 5, 11: 1, 13: 1, 15: 1 | 8, 7, 9 | 5 |
| SPY | 2024-07-19 | put | 17 | 455 | 605 | 9.5 | 5: 1, 7: 1, 8: 5, 9: 1, 10: 5, 11: 1, 13: 1, 15: 1 | 8, 7, 9 | 5 |
| SPY | 2024-08-16 | call | 17 | 470 | 625 | 10 | 5: 2, 8: 2, 9: 1, 10: 7, 11: 2, 13: 1, 15: 1 | 8, 9, 10 | 2 |
| SPY | 2024-08-16 | put | 17 | 470 | 625 | 10 | 5: 2, 8: 2, 9: 1, 10: 7, 11: 2, 13: 1, 15: 1 | 8, 9, 10 | 2 |
| SPY | 2024-09-20 | call | 17 | 475 | 635 | 10 | 8: 4, 9: 3, 10: 6, 11: 1, 15: 2 | 8, 9, 10 | 4 |
| SPY | 2024-09-20 | put | 17 | 475 | 635 | 10 | 8: 4, 9: 3, 10: 6, 11: 1, 15: 2 | 8, 9, 10 | 4 |
| SPY | 2024-10-18 | call | 17 | 480 | 640 | 10 | 8: 4, 9: 3, 10: 6, 11: 1, 15: 2 | 8, 9, 10 | 4 |
| SPY | 2024-10-18 | put | 17 | 480 | 640 | 10 | 8: 4, 9: 3, 10: 6, 11: 1, 15: 2 | 8, 9, 10 | 4 |
| SPY | 2024-11-15 | call | 17 | 480 | 645 | 10 | 5: 1, 8: 3, 9: 3, 10: 4, 11: 2, 15: 2, 17: 1 | 8, 9, 10 | 3 |
| SPY | 2024-11-15 | put | 17 | 480 | 645 | 10 | 5: 1, 8: 3, 9: 3, 10: 4, 11: 2, 15: 2, 17: 1 | 8, 9, 10 | 3 |
| SPY | 2024-12-20 | call | 17 | 500 | 670 | 10 | 8: 2, 9: 5, 10: 4, 12: 2, 15: 3 | 8, 9, 10 | 2 |
| SPY | 2024-12-20 | put | 17 | 500 | 670 | 10 | 8: 2, 9: 5, 10: 4, 12: 2, 15: 3 | 8, 9, 10 | 2 |
| SPY | 2025-01-17 | call | 17 | 500 | 675 | 9.5 | 8: 2, 9: 6, 10: 2, 12: 1, 13: 1, 15: 4 | 8, 9, 10 | 2 |
| SPY | 2025-01-17 | put | 16 | 500 | 660 | 9 | 8: 2, 9: 6, 10: 2, 12: 1, 13: 1, 15: 3 | 8, 9, 10 | 2 |
| SPY | 2025-02-21 | call | 17 | 510 | 680 | 9.5 | 8: 1, 9: 7, 10: 3, 12: 2, 15: 3 | 8, 9, 10 | 1 |
| SPY | 2025-02-21 | put | 16 | 510 | 670 | 9 | 8: 1, 9: 7, 10: 2, 12: 2, 15: 3 | 8, 9, 10 | 1 |
| SPY | 2025-03-21 | call | 17 | 515 | 690 | 9.5 | 9: 8, 10: 2, 11: 1, 12: 1, 15: 4 | 9, 10, 11 | 0 |
| SPY | 2025-03-21 | put | 15 | 515 | 680 | 9 | 9: 8, 10: 1, 11: 1, 12: 1, 15: 2, 30: 1 | 9, 10, 11 | 0 |
| SPY | 2025-05-16 | call | 17 | 485 | 650 | 9.5 | 8: 4, 9: 4, 10: 2, 11: 1, 12: 2, 13: 1, 14: 1, 15: 1 | 8, 9, 10 | 4 |
| SPY | 2025-05-16 | put | 16 | 485 | 650 | 9 | 8: 4, 9: 4, 10: 2, 11: 1, 12: 1, 13: 1, 15: 1, 26: 1 | 8, 9, 10 | 4 |
| SPY | 2025-06-20 | call | 17 | 440 | 590 | 10 | 5: 4, 10: 10, 15: 2 | 10, 5, 15 | 0 |
| SPY | 2025-06-20 | put | 17 | 440 | 590 | 10 | 5: 4, 10: 10, 15: 2 | 10, 5, 15 | 0 |
| SPY | 2025-07-18 | call | 17 | 510 | 680 | 9.5 | 8: 1, 9: 7, 10: 3, 12: 2, 15: 3 | 8, 9, 10 | 1 |
| SPY | 2025-07-18 | put | 16 | 510 | 670 | 9 | 8: 1, 9: 7, 10: 2, 12: 2, 15: 3 | 8, 9, 10 | 1 |
| SPY | 2025-08-15 | call | 17 | 513 | 690 | 10 | 5: 1, 9: 2, 10: 7, 12: 1, 13: 1, 14: 1, 15: 3 | 9, 10, 5 | 0 |
| SPY | 2025-08-15 | put | 17 | 513 | 690 | 10 | 5: 1, 9: 2, 10: 7, 12: 1, 13: 1, 14: 1, 15: 3 | 9, 10, 5 | 0 |

### Strikes present (identities)

- IWM 2023-11-17 call: 156, 160, 164, 168, 171, 174, 177, 180, 182, 185, 188, 191, 193, 197, 201, 205, 209
- IWM 2023-11-17 put: 156, 160, 164, 168, 171, 174, 177, 180, 182, 185, 188, 191, 193, 197, 201, 205
- IWM 2023-12-15 call: 148, 151, 156, 159, 163, 165, 168, 170, 173, 176, 178, 181, 183, 187, 190, 195, 198
- IWM 2023-12-15 put: 148, 151, 156, 159, 163, 165, 168, 170, 173, 176, 178, 181, 183, 187, 190, 195, 198
- IWM 2024-01-19 call: 153, 157, 161, 165, 169, 171, 174, 177, 179, 182, 185, 187, 190, 194, 197, 200, 205
- IWM 2024-01-19 put: 153, 157, 161, 165, 169, 171, 174, 177, 179, 182, 185, 187, 190, 194, 197, 200, 205
- IWM 2024-02-16 call: 168, 172, 177, 181, 185, 188, 191, 194, 197, 200, 203, 206, 209, 213, 217, 222, 225
- IWM 2024-02-16 put: 168, 172, 177, 181, 185, 188, 191, 194, 197, 200, 203, 206, 209, 213, 217, 222, 225
- IWM 2024-03-15 call: 163, 167, 172, 176, 179, 182, 185, 188, 191, 194, 197, 199, 202, 206, 210, 215, 219
- IWM 2024-03-15 put: 163, 167, 172, 176, 179, 182, 185, 188, 191, 194, 197, 199, 202, 206, 210, 215, 219
- IWM 2024-04-19 call: 170, 174, 179, 183, 187, 190, 193, 196, 199, 202, 205, 208, 211, 215, 219, 224, 225
- IWM 2024-04-19 put: 170, 174, 179, 183, 187, 190, 193, 196, 199, 202, 205, 208, 211, 215, 219, 224, 225
- IWM 2024-05-17 call: 172, 176, 181, 185, 189, 192, 195, 198, 201, 204, 207, 210, 213, 217, 221, 225, 230
- IWM 2024-05-17 put: 172, 176, 181, 185, 189, 192, 195, 198, 201, 204, 207, 210, 213, 217, 221, 225, 230
- IWM 2024-06-21 call: 167, 171, 176, 180, 184, 187, 189, 192, 195, 198, 201, 204, 207, 211, 215, 220, 224
- IWM 2024-06-21 put: 167, 171, 176, 180, 184, 187, 189, 192, 195, 198, 201, 204, 207, 211, 215, 220, 224
- IWM 2024-07-19 call: 178, 182, 188, 192, 196, 199, 202, 205, 209, 212, 215, 218, 220, 225, 230, 235
- IWM 2024-07-19 put: 178, 182, 188, 192, 196, 199, 202, 205, 209, 212, 215, 218, 220, 225, 230, 235
- IWM 2024-08-16 call: 171, 175, 180, 184, 188, 191, 194, 197, 200, 203, 206, 209, 212, 216, 220, 225, 230
- IWM 2024-08-16 put: 171, 175, 180, 184, 188, 191, 194, 197, 200, 203, 206, 209, 212, 216, 220, 225, 230
- IWM 2024-09-20 call: 188, 193, 198, 203, 207, 210, 214, 217, 220, 224, 227, 230, 234, 238, 240, 250
- IWM 2024-09-20 put: 188, 193, 198, 203, 207, 210, 214, 217, 220, 224, 227, 230, 234, 238, 240, 250
- IWM 2024-10-18 call: 183, 188, 194, 198, 202, 206, 209, 212, 215, 218, 222, 225, 228, 232, 237, 240, 245
- IWM 2024-10-18 put: 183, 188, 194, 198, 202, 206, 209, 212, 215, 218, 222, 225, 228, 232, 237, 240, 245
- IWM 2024-11-15 call: 185, 190, 196, 200, 205, 208, 211, 214, 218, 221, 224, 227, 231, 235, 239, 245, 250
- IWM 2024-11-15 put: 185, 190, 196, 200, 205, 208, 211, 214, 218, 221, 224, 227, 231, 235, 239, 245, 250
- IWM 2024-12-20 call: 189, 194, 200, 204, 209, 212, 215, 219, 222, 225, 229, 230, 235, 240, 245, 250, 255
- IWM 2024-12-20 put: 189, 194, 200, 204, 209, 212, 215, 219, 222, 225, 229, 230, 235, 240, 245, 250, 255
- IWM 2025-01-17 call: 195, 200, 206, 211, 215, 219, 222, 225, 229, 232, 236, 239, 243, 247, 252, 258, 263
- IWM 2025-01-17 put: 195, 200, 206, 211, 215, 219, 222, 225, 229, 232, 236, 239, 243, 247, 252
- IWM 2025-02-21 call: 189, 194, 199, 204, 208, 211, 215, 218, 221, 225, 228, 231, 235, 239, 244, 249, 254
- IWM 2025-02-21 put: 189, 194, 199, 204, 208, 211, 215, 218, 221, 225, 228, 231, 235, 239, 244, 249, 254
- IWM 2025-03-21 call: 196, 201, 207, 211, 216, 219, 223, 226, 230, 233, 237, 240, 244, 248, 253, 259, 264
- IWM 2025-03-21 put: 196, 201, 207, 211, 216, 219, 223, 226, 230, 233, 237, 240, 244, 248, 253, 259
- IWM 2025-05-16 call: 175, 180, 185, 189, 193, 196, 199, 202, 205, 209, 212, 215, 218, 222, 226, 231, 236
- IWM 2025-05-16 put: 175, 180, 185, 189, 193, 196, 199, 202, 205, 209, 212, 215, 218, 222, 226, 231, 236
- IWM 2025-06-20 call: 156, 160, 164, 168, 172, 175, 177, 180, 183, 185, 188, 191, 194, 197, 201, 206, 210
- IWM 2025-06-20 put: 156, 160, 164, 168, 172, 175, 177, 180, 183, 185, 188, 191, 194, 197, 201, 206, 210
- IWM 2025-07-18 call: 178, 183, 188, 192, 196, 200, 203, 206, 209, 212, 215, 220, 225, 230, 235, 240
- IWM 2025-07-18 put: 178, 183, 188, 192, 196, 200, 203, 206, 209, 212, 215, 220, 225, 230, 235, 240
- IWM 2025-08-15 call: 180, 184, 190, 194, 198, 201, 204, 208, 211, 214, 215, 220, 225, 230, 235, 240
- IWM 2025-08-15 put: 180, 184, 190, 194, 198, 201, 204, 208, 211, 214, 215, 220, 225, 230, 235, 240
- QQQ 2023-11-17 call: 316, 324, 334, 342, 348, 354, 360, 365, 371, 376, 382, 387, 393, 400, 408, 417, 425
- QQQ 2023-11-17 put: 316, 324, 334, 342, 348, 354, 360, 365, 371, 376, 382, 387, 393, 400, 408, 417, 425
- QQQ 2023-12-15 call: 314, 323, 332, 340, 347, 353, 358, 364, 369, 375, 380, 386, 392, 399, 406, 416, 420
- QQQ 2023-12-15 put: 314, 323, 332, 340, 347, 353, 358, 364, 369, 375, 380, 386, 392, 399, 406, 416, 420
- QQQ 2024-03-15 call: 348.78, 358.78, 368.78, 376.78, 385, 390.78, 396.78, 403.78, 409.78, 415.78, 422, 428, 434, 440, 450, 460, 470
- QQQ 2024-03-15 put: 348.78, 358.78, 368.78, 376.78, 385, 390.78, 396.78, 403.78, 409.78, 415.78, 422, 428, 434, 440, 450, 460, 470
- QQQ 2024-04-19 call: 364.78, 374.78, 384.78, 394.78, 400, 409.78, 414.78, 420, 428, 434, 440, 446, 452, 460, 470, 480, 490
- QQQ 2024-04-19 put: 364.78, 374.78, 384.78, 394.78, 400, 409.78, 414.78, 420, 428, 434, 440, 446, 452, 460, 470, 480, 490
- QQQ 2024-05-17 call: 374.78, 384.78, 394.78, 404.78, 410, 419.78, 424.78, 430, 439.78, 444.78, 450, 455, 464.78, 474.78, 480, 490, 500
- QQQ 2024-05-17 put: 374.78, 384.78, 394.78, 404.78, 410, 419.78, 424.78, 430, 439.78, 444.78, 450, 455, 464.78, 474.78, 480, 490, 500
- QQQ 2024-06-21 call: 356.78, 366.78, 376.78, 385, 394.78, 400, 405, 414.78, 419.78, 425, 430, 439.78, 444.78, 452, 461, 471, 481
- QQQ 2024-06-21 put: 356.78, 366.78, 376.78, 385, 394.78, 400, 405, 414.78, 419.78, 425, 430, 439.78, 444.78, 452, 461, 471, 481
- QQQ 2024-07-19 call: 390, 400, 410, 419, 428, 434, 441, 450, 455, 460, 470, 475, 480, 490, 500, 510, 520
- QQQ 2024-07-19 put: 390, 400, 410, 419, 428, 434, 441, 450, 455, 460, 470, 475, 480, 490, 500, 510, 520
- QQQ 2024-08-16 call: 415, 425, 435, 445, 455, 465, 470, 480, 485, 490, 500, 505, 515, 525, 535, 545, 555
- QQQ 2024-08-16 put: 415, 425, 435, 445, 455, 465, 470, 480, 485, 490, 500, 505, 515, 525, 535, 545, 555
- QQQ 2024-09-20 call: 410, 420, 434.78, 444.78, 454.78, 460, 469.78, 475, 480, 489.78, 495, 504.78, 510, 520, 530, 544.78, 550
- QQQ 2024-09-20 put: 410, 420, 434.78, 444.78, 454.78, 460, 469.78, 475, 480, 489.78, 495, 504.78, 510, 520, 530, 544.78, 550
- QQQ 2024-10-18 call: 410, 420, 435, 445, 450, 460, 465, 475, 480, 490, 495, 505, 510, 520, 530, 540, 550
- QQQ 2024-10-18 put: 410, 420, 435, 445, 450, 460, 465, 475, 480, 490, 495, 505, 510, 520, 530, 540, 550
- QQQ 2024-11-15 call: 405, 415, 425, 435, 445, 450, 460, 465, 475, 480, 485, 495, 500, 510, 520, 530, 540
- QQQ 2024-11-15 put: 405, 415, 425, 435, 445, 450, 460, 465, 475, 480, 485, 495, 500, 510, 520, 530, 540
- QQQ 2024-12-20 call: 424.78, 434.78, 445, 455, 465, 474.78, 480, 489.78, 495, 503, 510, 519.78, 525, 535, 545, 555, 565
- QQQ 2024-12-20 put: 424.78, 434.78, 445, 455, 465, 474.78, 480, 489.78, 495, 503, 510, 519.78, 525, 535, 545, 555
- QQQ 2025-01-17 call: 429.78, 439.78, 450, 460, 470, 479.78, 485, 494.78, 500, 509.78, 515, 524.78, 529.78, 539.78, 549.78, 564.78, 574.78
- QQQ 2025-01-17 put: 429.78, 439.78, 450, 460, 470, 479.78, 485, 494.78, 500, 509.78, 515, 524.78, 529.78, 539.78, 549.78, 564.78, 574.78
- QQQ 2025-02-21 call: 445, 460, 470, 480, 490, 500, 505, 515, 525, 530, 540, 545, 555, 565, 575, 590, 600
- QQQ 2025-02-21 put: 445, 460, 470, 480, 490, 500, 505, 515, 525, 530, 540, 545, 555, 565, 575, 590, 600
- QQQ 2025-03-21 call: 447, 460, 470, 485, 495, 500, 510, 515, 525, 535, 540, 550, 555, 565, 575, 590, 600
- QQQ 2025-03-21 put: 447, 460, 470, 485, 495, 500, 510, 515, 525, 535, 540, 550, 555, 565, 575, 590, 600
- QQQ 2025-05-16 call: 415, 420, 435, 445, 455, 460, 470, 475, 485, 490, 495, 504, 512, 521, 531, 543, 555
- QQQ 2025-05-16 put: 415, 420, 435, 445, 455, 460, 470, 475, 485, 490, 495, 504, 512, 521, 531, 543, 555
- QQQ 2025-06-20 call: 369.78, 379.78, 389.78, 399.78, 405, 414.78, 420, 425, 434.78, 439.78, 445, 454.78, 459.78, 469.78, 474.78, 484.78, 494.78
- QQQ 2025-06-20 put: 369.78, 379.78, 389.78, 399.78, 405, 414.78, 420, 425, 434.78, 439.78, 445, 454.78, 459.78, 469.78, 474.78, 484.78, 494.78
- QQQ 2025-07-18 call: 445, 455, 470, 480, 491, 499, 506, 514, 522, 530, 538, 546, 555, 565, 575, 585, 600
- QQQ 2025-07-18 put: 445, 455, 470, 480, 491, 499, 506, 514, 522, 530, 538, 546, 555, 565, 575, 585, 600
- QQQ 2025-08-15 call: 455, 470, 480, 490, 500, 510, 520, 525, 535, 540, 550, 560, 565, 575, 590, 600, 610
- QQQ 2025-08-15 put: 455, 470, 480, 490, 500, 510, 520, 525, 535, 540, 550, 560, 565, 575, 590, 600, 610
- SPY 2023-11-17 call: 380, 390, 399, 408, 417, 424, 430, 437, 444, 450, 457, 464, 470, 480, 488, 500, 510
- SPY 2023-11-17 put: 380, 390, 399, 408, 417, 424, 430, 437, 444, 450, 457, 464, 470, 480, 488, 500, 510
- SPY 2023-12-15 call: 371, 382, 392, 401, 410, 416, 423, 429, 436, 443, 449, 456, 462, 471, 480, 491, 501
- SPY 2023-12-15 put: 371, 382, 392, 401, 410, 416, 423, 429, 436, 443, 449, 456, 462, 471, 480, 491, 501
- SPY 2024-01-19 call: 387, 397, 409, 418, 427, 434, 441, 447, 454, 462, 468, 475, 482, 490, 500, 510, 520
- SPY 2024-01-19 put: 387, 397, 409, 418, 427, 434, 441, 447, 454, 462, 468, 475, 482, 490, 500, 510, 520
- SPY 2024-02-16 call: 402, 413, 425, 434, 444, 451, 458, 465, 472, 479, 486, 493, 500, 510, 520, 530, 540
- SPY 2024-02-16 put: 402, 413, 425, 434, 444, 451, 458, 465, 472, 479, 486, 493, 500, 510, 520, 530
- SPY 2024-03-15 call: 404, 416, 427, 437, 446, 454, 461, 468, 475, 482, 489, 496, 504, 512, 522, 535, 545
- SPY 2024-03-15 put: 404, 416, 427, 437, 446, 454, 461, 468, 475, 482, 489, 496, 504, 512, 522, 535, 545
- SPY 2024-04-19 call: 425, 435, 447, 457, 467, 474, 482, 489, 497, 504, 512, 519, 527, 535, 545, 560, 570
- SPY 2024-04-19 put: 425, 435, 447, 457, 467, 474, 482, 489, 497, 504, 512, 519, 527, 535, 545, 560, 570
- SPY 2024-05-17 call: 440, 449, 462, 472, 482, 490, 497, 505, 513, 521, 528, 536, 545, 555, 565, 575, 585
- SPY 2024-05-17 put: 440, 449, 462, 472, 482, 490, 497, 505, 513, 521, 528, 536, 545, 555, 565, 575, 585
- SPY 2024-06-21 call: 425, 437, 450, 460, 470, 477, 485, 492, 500, 507, 515, 522, 530, 540, 550, 560, 570
- SPY 2024-06-21 put: 425, 437, 450, 460, 470, 477, 485, 492, 500, 507, 515, 522, 530, 540, 550, 560, 570
- SPY 2024-07-19 call: 455, 464, 477, 488, 498, 506, 514, 522, 530, 538, 545, 555, 560, 570, 585, 595, 605
- SPY 2024-07-19 put: 455, 464, 477, 488, 498, 506, 514, 522, 530, 538, 545, 555, 560, 570, 585, 595, 605
- SPY 2024-08-16 call: 470, 479, 492, 503, 514, 522, 530, 540, 545, 555, 565, 570, 580, 590, 600, 615, 625
- SPY 2024-08-16 put: 470, 479, 492, 503, 514, 522, 530, 540, 545, 555, 565, 570, 580, 590, 600, 615, 625
- SPY 2024-09-20 call: 475, 485, 500, 510, 521, 530, 538, 546, 555, 563, 571, 580, 590, 600, 610, 625, 635
- SPY 2024-09-20 put: 475, 485, 500, 510, 521, 530, 538, 546, 555, 563, 571, 580, 590, 600, 610, 625, 635
- SPY 2024-10-18 call: 480, 490, 505, 515, 526, 534, 543, 551, 560, 568, 576, 585, 595, 605, 615, 630, 640
- SPY 2024-10-18 put: 480, 490, 505, 515, 526, 534, 543, 551, 560, 568, 576, 585, 595, 605, 615, 630, 640
- SPY 2024-11-15 call: 480, 490, 507, 518, 529, 538, 546, 554, 563, 571, 580, 590, 595, 610, 620, 635, 645
- SPY 2024-11-15 put: 480, 490, 507, 518, 529, 538, 546, 554, 563, 571, 580, 590, 595, 610, 620, 635, 645
- SPY 2024-12-20 call: 500, 510, 525, 537, 549, 557, 566, 575, 584, 592, 601, 610, 620, 630, 640, 655, 670
- SPY 2024-12-20 put: 500, 510, 525, 537, 549, 557, 566, 575, 584, 592, 601, 610, 620, 630, 640, 655, 670
- SPY 2025-01-17 call: 500, 515, 530, 540, 553, 562, 571, 579, 588, 597, 606, 615, 623, 635, 645, 660, 675
- SPY 2025-01-17 put: 500, 515, 530, 540, 553, 562, 571, 579, 588, 597, 606, 615, 623, 635, 645, 660
- SPY 2025-02-21 call: 510, 520, 535, 547, 559, 568, 577, 586, 595, 604, 613, 621, 630, 640, 655, 670, 680
- SPY 2025-02-21 put: 510, 520, 535, 547, 559, 568, 577, 586, 595, 604, 613, 621, 630, 640, 655, 670
- SPY 2025-03-21 call: 515, 530, 545, 555, 567, 576, 585, 594, 603, 612, 621, 630, 639, 650, 665, 680, 690
- SPY 2025-03-21 put: 515, 530, 545, 555, 567, 576, 585, 594, 603, 612, 621, 630, 639, 650, 680
- SPY 2025-05-16 call: 485, 495, 510, 520, 533, 542, 550, 559, 567, 576, 584, 593, 601, 613, 624, 638, 650
- SPY 2025-05-16 put: 485, 495, 510, 520, 533, 542, 550, 559, 567, 576, 584, 593, 601, 613, 624, 650
- SPY 2025-06-20 call: 440, 450, 460, 475, 485, 490, 500, 505, 515, 520, 530, 535, 545, 555, 565, 580, 590
- SPY 2025-06-20 put: 440, 450, 460, 475, 485, 490, 500, 505, 515, 520, 530, 535, 545, 555, 565, 580, 590
- SPY 2025-07-18 call: 510, 520, 535, 547, 559, 568, 577, 586, 595, 604, 613, 622, 630, 640, 655, 670, 680
- SPY 2025-07-18 put: 510, 520, 535, 547, 559, 568, 577, 586, 595, 604, 613, 622, 630, 640, 655, 670
- SPY 2025-08-15 call: 513, 527, 542, 554, 567, 576, 585, 595, 605, 610, 620, 630, 640, 650, 665, 680, 690
- SPY 2025-08-15 put: 513, 527, 542, 554, 567, 576, 585, 595, 605, 610, 620, 630, 640, 650, 665, 680, 690
