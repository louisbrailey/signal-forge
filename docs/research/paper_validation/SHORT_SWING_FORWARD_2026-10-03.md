# Forward paper validation — short swing (v2) and v2+v3 — 2026-10-03

Read-only measurement of the live paper ledger. Research evidence only; no order was placed, nothing was written to the database, no service or CLI was touched.

- Database: `/Users/louisbrailey/signal-forge/data/signalforge.sqlite`, opened with SQLite URI `mode=ro` plus `PRAGMA query_only=ON`.
- Reproduce: `python3 docs/research/paper_validation/paper_validation_query.py [--csv paper_validation_candidates.csv]` (standard library only). Every number below is printed by that script; the CSV holds all 99 approved-scope candidates.
- As-of: last stored `massive` daily bar **2026-10-02**. Window start **2026-09-10** (probation activation). "Post-fix" = accepted trades whose `plan_json.risk_decision` exists (written only by the 2026-10-02 ledger), i.e. trades 18 and 19.

## Headline

| | v2 `trend_continuation.short_swing` | v2+v3 combined |
|---|---|---|
| Accepted paper trades since 09-10 | **0** | 6 (all v3) |
| Accepted since the 10-02 fixes | **0** | 2 (TSLA, ACN; zero bars held) |
| Closed trades | 0 | 2, both legacy rows with impossible chronology |
| Cumulative P&L on $30,000 | n/a | **-$93.41 (-0.31%)**; realised -$166.98, unrealised +$79.43, legacy double-counted costs -$5.87 |
| SPY buy-and-hold, same window | +$467.52 (+1.56%) | +$467.52 (+1.56%) |

**There is no forward evidence for v2.** It produced 5 gate-PASSED candidates in its approved scope (4 distinct signals: MSFT x2, XLK x2) and every one was refused with "an open paper position already exists", because v3 had taken the same symbol seconds earlier in the same job. The combined sample is n=6 entries with at most one session of holding on the four open positions. Nothing here supports any statement about edge, positive or negative.

## 1. Trade ledger

Tables `paper_trade` (decision=ACCEPTED), `paper_position`, `paper_order`, `paper_fill`, `candidate`, `instrument`; account `default`. SQL: `SQL_TRADES` in the script.

| trade | ver | sym | entry (UTC date) | fill | qty | exit / mark date | exit / mark px | state | planned risk $ | P&L $ | R | sessions held | entry cost $ | post-fix |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2 | v3 | MSFT | 09-25 | 516.45 | 5 | 09-25 | 499.75 | closed (legacy) | 84.85 | -83.49 | -0.98 | 0 | 1.42 | no |
| 5 | v3 | MSFT | 09-26 (Sat) | 516.45 | 5 | 09-26 | 499.75 | closed (legacy) | 84.85 | -83.49 | -0.98 | 0 | 1.42 | no |
| 7 | v3 | XLK | 10-01 | 195.86 | 15 | 10-02 | 199.81 | open | 75.45 | +59.25 | +0.79 | 1 | 1.61 | no |
| 8 | v3 | MSFT | 10-01 | 513.18 | 5 | 10-02 | 517.53 | open | 92.05 | +21.75 | +0.24 | 1 | 1.41 | no |
| 18 | v3 | TSLA | 10-02 | 370.79 | 4 | 10-02 | 370.59 | open | 70.36 | -0.80 | -0.01 | 0 | 0.80 | yes |
| 19 | v3 | ACN | 10-02 | 199.01 | 7 | 10-02 | 198.90 | open | 108.29 | -0.77 | -0.01 | 0 | 0.77 | yes |

| Subset | n | closed | P&L $ | sum R | planned risk $ | entry costs $ |
|---|---|---|---|---|---|---|
| v2 since 09-10 | 0 | 0 | 0 | 0 | 0 | 0 |
| v2 post-fix | 0 | 0 | 0 | 0 | 0 | 0 |
| v2+v3 since 09-10 | 6 | 2 | -87.55 | -0.96 | 515.85 | 7.43 |
| v2+v3 post-fix | 2 | 0 | -1.57 | -0.02 | 178.65 | 1.57 |

Definitions and cost model:

- Planned risk: post-fix rows use the recorded `risk_decision.accepted_risk_dollars`; legacy rows are recomputed with the same formula, qty x (fill - stop x (1 - 5.5 bps)). R = P&L / planned risk. Open rows are unrealised R at the 10-02 close.
- Costs as configured in `paper/ledger.py`: commission $0; entry fill = zone midpoint x (1 + 3 bps slippage + half of a 5 bps nominal spread) = 5.5 bps of notional, embedded in the fill price; exits pay the same 5.5 bps. `paper_fill.spread_cost + slippage` is attribution of that embedded cost. Entry cost is 5.4-5.5 bps of notional on all six.
- Costs as % of gross (P&L before the entry cost): XLK 2.6%, MSFT (trade 8) 6.1%, each legacy MSFT 1.7%. For TSLA and ACN the entry cost is the entire P&L (gross is zero), so the ratio is undefined.
- Sessions held counts `massive` bars strictly after the entry date, as the ledger does.

## 2. Equity curve

Reconstructed per session as cash events plus open quantity x `massive` close. Flat at $30,000 from 09-10 to 09-24 (no trades); rows from 09-24:

| date | cash | positions MV | equity | cum P&L | SPY B&H on $30k |
|---|---|---|---|---|---|
| 09-24 | 30,000.00 | 0 | 30,000.00 | 0.00 | +370.14 |
| 09-25 | 29,915.09 | 0 | 29,915.09 | -84.91 | +535.21 |
| 09-28 | 29,830.18 | 0 | 29,830.18 | -169.82 | +307.98 |
| 09-29 | 29,830.18 | 0 | 29,830.18 | -169.82 | +252.17 |
| 09-30 | 29,830.18 | 0 | 29,830.18 | -169.82 | +190.02 |
| 10-01 | 24,323.36 | 5,531.15 | 29,854.51 | -145.49 | +243.85 |
| 10-02 | 21,447.13 | 8,459.46 | 29,906.59 | -93.41 | +467.52 |

- Ledger cash `paper_account.cash` = **$21,447.12**. Rebuilding cash from fills and realised P&L gives $21,452.99; the -$5.87 residual equals the entry costs of the four pre-fix fills ($5.86), i.e. the legacy double-count the 10-02 release describes. The curve above includes that debit so it ends at ledger cash (1 cent rounding).
- Max drawdown **$169.82** (reached 09-28, entirely the two legacy MSFT rows) = 1.98R where R is the mean planned risk per accepted trade ($85.98), or 1.13x the $150 (0.5%) per-trade budget. Since the fixes the equity change is -$1.57 (entry costs).
- Open stop risk at 10-02 marks: **$425.58 = 1.42% of equity**, against a 1.5% cap of $448.60 (95% used). The ledger's own figure at the ACN acceptance was $318.06 before plus $108.29 accepted.

## 3. Concentration (10-02 marks, equity $29,906.59)

| symbol | market value $ | % of equity | vs 5% symbol cap | share of gross |
|---|---|---|---|---|
| XLK | 2,997.15 | 10.02 | over (opened pre-fix) | 35.4% |
| MSFT | 2,587.65 | 8.65 | over (opened pre-fix) | 30.6% |
| TSLA | 1,482.36 | 4.96 | within | 17.5% |
| ACN | 1,392.30 | 4.66 | within | 16.5% |

- Gross exposure $8,459.46 = 28.3% of equity (configured cap 60%). Largest position is XLK at 35.4% of gross, 10.0% of equity.
- XLK and MSFT were opened on 10-01 under the old sizing and are roughly double the 5% cap. The release note says existing positions are not resized, so this persists until they exit.
- **The 20% sector cap is not operating.** `instrument.sector` is blank for all 2,658 instruments, and the ledger only adds the sector budget when a sector is known (both post-fix `risk_decision` rows record `"sector": null`). Sector exposure cannot be measured from stored data. By inspection, three of four positions (XLK, MSFT, ACN) are technology exposure and XLK holds MSFT, so about 23% of equity is in one correlated group, with no cap applied to it.

## 4. Benchmark

- SPY buy-and-hold on $30,000 from the 09-10 close (757.83) to the 10-02 close (769.64): **+$467.52 (+1.56%)** versus the paper account's -$93.41 (-0.31%). The account held no positions for 15 of 17 sessions, so this is mostly a cash-versus-equity comparison, not a strategy comparison.
- Same dollars in SPY over each trade's holding period (SPY close on the entry date to SPY close on the exit/mark date):

| trade | sym | notional $ | trade P&L $ | SPY same-$ P&L |
|---|---|---|---|---|
| 2, 5 | MSFT (legacy) | 2,582.25 each | -83.49 each | 0.00 (zero-length holding period) |
| 7 | XLK | 2,937.90 | +59.25 | +21.73 |
| 8 | MSFT | 2,565.90 | +21.75 | +18.98 |
| 18, 19 | TSLA, ACN | 1,483.16 / 1,393.07 | -0.80 / -0.77 | 0.00 (no bar after entry) |

  Total: trades -$87.55 versus SPY +$40.70. Only two rows have a non-degenerate holding period, and it is one session long.

## 5. Candidates that were not simulated

Approved scopes come from `strategy_promotion_evaluation` (passed=1): v2 = evaluation 43, dataset snapshot 3, 24 symbols, source `massive`; v3 = evaluation 45, snapshot 11, 150 symbols, source `massive`. SQL: `SQL_CANDS` (join `candidate`, `scan_run`, `instrument`, left join `paper_trade`), `scan_run.started_at >= 2026-09-10`.

| scope | ACCEPTED | WATCH: daily cap | REJECTED: open position | NO_TRADE: quality gate | total |
|---|---|---|---|---|---|
| v2 short_swing | 0 | 0 | 5 | 17 | 22 |
| v3 medium_swing | 6 | 7 | 1 | 63 | 77 |

No approved-scope candidate was refused by a risk cap or by a regime gate at acceptance time; no PASSED candidate was left without a decision. (Two further v3 REJECTED rows, trades 1 and 4, came from the 24-symbol snapshot, which is not v3's approved scope.)

Hypothetical outcome assumptions (function `simulate`, mirroring the ledger): long only; fill = entry-zone midpoint x (1 + 5.5 bps) on the decision date; only `massive` bars after that date; stop tested before target on the same bar; stop fills at min(stop, open); target at the target; time stop at the close of the first bar on or after decision date + `time_stop_days` calendar days (10 for v2, 40 for v3); 5.5 bps exit cost; still-open signals marked at the 10-02 close. "$ at policy size" uses shares = min(candidate risk, 0.5% of $30k, 5% of $30k) and ignores open-risk, cash and daily-cap interactions. All bars used were clean (adjusted, unflagged, not simulated).

PASSED but not simulated, every row:

| cand | ver | decided | sym | reason | fill | stop | target | bars | state | mark | R | $ at policy size |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 13081 | v2 | 09-25 | MSFT | open position (v3 trade 2) | 516.45 | 499.75 | 549.01 | 5 | open | 517.53 | +0.06 | +2.16 |
| 14080 | v2 | 09-26 | MSFT | open position; same signal re-emitted | 516.45 | 499.75 | 549.01 | 5 | open | 517.53 | +0.06 | dup |
| 16031 | v2 | 10-01 | MSFT | open position (v3 trade 8) | 513.18 | 495.05 | 548.61 | 1 | open | 517.53 | +0.24 | +8.70 |
| 16032 | v2 | 10-01 | XLK | open position (v3 trade 7) | 195.86 | 190.94 | 205.38 | 1 | open | 199.81 | +0.79 | +27.65 |
| 16076 | v2 | 10-01 | XLK | open position | 197.92 | 193.04 | 207.35 | 1 | open | 199.81 | +0.38 | +13.23 |
| 16078 | v3 | 10-01 | XLK | open position | 197.92 | 193.04 | 207.35 | 1 | open | 199.81 | +0.38 | +13.23 |
| 16055 | v3 | 10-01 | APH | daily cap | 84.35 | 79.94 | 93.01 | 1 | open | 86.96 | +0.59 | +44.37 |
| 16084 | v3 | 10-01 | MU | daily cap | 1,097.99 | 1,030.08 | 1,232.00 | 1 | open | 1,074.89 | -0.34 | -23.10 |
| 16093 | v3 | 10-01 | ACN | daily cap | 212.42 | 197.40 | 242.10 | 1 | open | 198.90 | -0.89 | -94.64 |
| 16101 | v3 | 10-01 | SNPS | daily cap | 490.81 | 462.16 | 547.29 | 1 | open | 489.90 | -0.03 | -2.73 |
| 16116 | v3 | 10-01 | MCK | daily cap | 899.31 | 863.29 | 969.88 | 1 | open | 902.28 | +0.08 | +2.97 |
| 17099 | v3 | 10-02 | ABBV | daily cap | 262.96 | 255.72 | 277.03 | 0 | no bars | - | 0 | 0 |
| 17102 | v3 | 10-02 | SNPS | daily cap | 490.17 | 461.63 | 546.45 | 0 | no bars | - | 0 | 0 |

Summary. "Unique" keeps the first candidate per strategy / symbol / entry band / stop, because weekend re-scans re-emit the identical signal on unchanged bars.

| scope | disposition | rows | unique | stop | target | time stop | open / no bars | sum R | mean R | $ at policy size |
|---|---|---|---|---|---|---|---|---|---|---|
| v2 | NO_TRADE gate | 17 | 11 | 6 | 1 | 4 | 0 | -2.83 | -0.258 | -143.10 |
| v2 | REJECTED open position | 5 | 4 | 0 | 0 | 0 | 4 | +1.46 | +0.366 | +51.74 |
| v3 | NO_TRADE gate | 63 | 45 | 19 | 2 | 0 | 24 | -5.76 | -0.128 | -22.75 |
| v3 | WATCH daily cap | 7 | 7 | 0 | 0 | 0 | 7 | -0.59 | -0.085 | -73.13 |
| v3 | REJECTED open position | 1 | 1 | 0 | 0 | 0 | 1 | +0.38 | +0.380 | +13.23 |
| v2+v3 | NO_TRADE gate | 80 | 56 | 25 | 3 | 4 | 24 | -8.60 | -0.154 | -165.85 |
| v2+v3 | WATCH daily cap | 7 | 7 | 0 | 0 | 0 | 7 | -0.59 | -0.085 | -73.13 |
| v2+v3 | REJECTED open position | 6 | 5 | 0 | 0 | 0 | 5 | +1.84 | +0.369 | +64.97 |

What the controls cost or saved, so far:

- **Quality gates (09-10 to 09-24).** v2's 17 rows all failed one gate: OOS regime coverage (1 regime with >=10 trades, 2 required). v3's 63 rows all failed three: OOS expectancy -0.049R <= 0, CI low -0.363R < -0.15, and the same regime coverage. Taken hypothetically, the 11 unique v2 signals resolved 6 stops / 1 target / 4 time stops for -2.83R; the 45 unique v3 signals show 19 stops / 2 targets / 24 still open for -5.76R. The gates avoided a hypothetical loss in this window. These signals overlap heavily (same symbols on consecutive days in one market stretch), so the effective sample is far smaller than 56.
- **Daily cap (2/day).** 7 WATCH rows, all v3, on two days. With zero or one bar of history they sum to -0.59R (-$73 at policy size), dominated by ACN's -0.89R. Too short to say the cap cost or saved anything.
- **One open position per symbol.** 6 rows, 5 of them v2. These were not missed exposure for the account (the symbol was already held through v3); they are missed attribution for v2. Hypothetical +1.46R over 4 unique v2 signals, all still open.

## 6. Risk utilisation and sizing counterfactual

| trade | sym | actual shares | planned risk % equity | % of 0.5% budget used | notional % equity | recorded binding cap |
|---|---|---|---|---|---|---|
| 2 | MSFT | 5 | 0.283 | 57 | 8.61 | none recorded (legacy) |
| 5 | MSFT | 5 | 0.283 | 57 | 8.61 | none recorded (legacy) |
| 7 | XLK | 15 | 0.252 | 50 | 9.79 | none recorded (legacy) |
| 8 | MSFT | 5 | 0.307 | 61 | 8.55 | none recorded (legacy) |
| 18 | TSLA | 4 | 0.235 | 47 | 4.96 | symbol (5%) |
| 19 | ACN | 7 | 0.362 | 72 | 4.66 | symbol (5%) |

- Recorded share caps, TSLA: candidate 5, per-trade 8, open-risk 11, symbol **4**, gross 33, cash 65. ACN: candidate 11, per-trade 9, open-risk 8, symbol **7**, gross 54, cash 114.
- Per-trade risk used 47-72% of the 0.5% budget; it never bound. Aggregate open risk is now 95% of the 1.5% budget, so it is the constraint most likely to bind on the next entry (about $23 of headroom at 10-02 marks).
- How often each constraint bit, since 09-10: daily cap 7 candidates (all v3, on 10-01 and 10-02); one-position-per-symbol 6 candidates (5 v2); 5% symbol cap bound on 2 of 2 post-fix acceptances; 0.5% per-trade risk 0; 1.5% open risk 0; 20% sector 0 (inert, see section 3). Trade count is set by the daily cap and the open-position rule, not by the risk percentages.

Counterfactual, not a recommendation to change configuration: replay each accepted trade's acceptance-time share caps with 1.0% per-trade and 3.0% open risk, holding the 5% symbol cap, 60% gross cap, candidate risk, 2/day cap, the open-position rule and the recorded entry and mark prices fixed. Legacy rows carry no `risk_decision`, so their account state is rebuilt from prior-close marks.

| trade | sym | actual shares / P&L | replay at 0.5% / 1.5% | replay at 1.0% / 3.0% | binding in both replays |
|---|---|---|---|---|---|
| 2 | MSFT | 5 / -83.49 | 2 / -33.40 | 2 / -33.40 | symbol |
| 5 | MSFT | 5 / -83.49 | 2 / -33.40 | 2 / -33.40 | symbol |
| 7 | XLK | 15 / +59.25 | 7 / +27.65 | 7 / +27.65 | symbol |
| 8 | MSFT | 5 / +21.75 | 2 / +8.70 | 2 / +8.70 | symbol |
| 18 | TSLA | 4 / -0.80 | 4 / -0.80 | 4 / -0.80 | symbol |
| 19 | ACN | 7 / -0.77 | 7 / -0.77 | 7 / -0.77 | symbol |
| total | | 6 trades / -87.55 | 6 trades / -32.01 | 6 trades / -32.01 | |

Doubling the two risk percentages changes nothing in this sample: same 6 trades, same shares, same P&L, because the 5% symbol cap is the tighter limit on every trade. The only difference from actual is that the four pre-fix trades would have been about half their recorded size under the current policy. The v2 count stays at 0 in both replays.

## 7. Data caveats

1. **n is tiny.** 17 sessions live, 6 entries, 0 for v2. Four positions are open with 0-1 bars of history; the two closed rows are invalid (next point). No significance claim is possible and none is made.
2. **The only realised P&L is a known artefact.** Trades 2 and 5 were closed by the pre-fix ledger at 00:00 UTC on their entry date, using the entry-day low (MSFT 09-25 low 497.25 against a 499.75 stop) that preceded the post-close fill. Trade 5 was opened on Saturday 09-26 from the same unchanged bar. `trade_correction` has 0 rows, so the ledger still carries -$166.98 realised. Under the corrected chronology trade 2 would still be open after 5 bars at +$5.40 (+0.06R), and trades 5 and 8 would not exist (open-position rule). On that restatement the account would be roughly flat to slightly positive, not -$93; that is an inference, not a ledger fact.
3. **v2 is structurally starved by ordering.** `auto_simulate_scan_runs` orders candidates by `Candidate.horizon`, and "MEDIUM_SWING" sorts before "SHORT_SWING", so v3 always decides first. v2's approved universe (24 symbols) sits inside v3's liquid-name set, both use the same trend rule with stop 1.5 ATR and target 3 ATR, and they fired on the same symbols on the same days. All 5 v2 PASSED candidates lost the symbol to v3. Unless this changes, the "priority" version will keep accumulating little or no forward evidence.
4. **Gate regime change on 09-25.** Every approved-scope candidate before 09-25 was NO_TRADE; every one from 09-25 on PASSED. v3's stored OOS evidence up to 09-24 was negative (-0.049R). The forward record therefore covers only 4 scan days of eligible signals (09-25, 09-26, 10-01, 10-02).
5. **Coverage gap.** No approved-scope scan ran on the 09-28, 09-29 and 09-30 sessions; those bars were ingested on 10-01. Signals on those days were never seen.
6. **Stale-reference fill on 10-01.** Trades 7 and 8 were accepted at 19:59 UTC, before the 10-01 bar existed, and priced off the 09-30 close. Both fills were inside the 10-01 range, but the ledger then ignores the 10-01 bar for exits.
7. **Fill model.** Zone midpoint plus 5.5 bps, not an observed quote; end-of-day bars only; stops cannot protect against gaps (ACN opened 10-01 at 215.98 after closing 183.37). Bars are split-adjusted, not dividend-adjusted.
8. **Time-stop mismatch.** The ledger's time stop is calendar days (10 / 40) while the v2 sensitivity record lists `time_stop_bars: 10`. Ten calendar days is about seven sessions, so paper exits for v2 would be earlier than the backtested rule. The hypothetical outcomes above use the ledger's convention.
9. **Hypotheticals are optimistic about fills and pessimistic about nothing else.** They assume every signal filled at the modelled price, ignore account-level limits (except the per-signal policy size) and count overlapping signals separately.
10. **Mixed sizing regimes.** Four of six trades were sized before the caps existed, so the combined P&L mixes two policies. Section 6 shows the same trades at one policy.
