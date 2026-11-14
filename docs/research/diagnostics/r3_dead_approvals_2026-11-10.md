# Dead approvals: why two of four PAPER_APPROVED versions earn nothing

R3 read-only diagnosis, 2026-11-10, corrected the same day after an adversarial review (what changed is in deviation 11). No pre-registration applies. No scan, evaluation or backtest was run.

**relative_strength.medium_swing (version 5) cannot trade, and has never produced a passing candidate in 13,321 attempts.** The scan's "OOS regime coverage" gate wants 10 out-of-sample trades in each of two market trends. A rule that only signals in a bull trend has 193 bull trades and 4 others, and those 4 are an accident of timing. Leaving the approval as it is, inert, is the only choice that does not touch the frozen studies: retiring it would stop the Kronos medium book's collector.

**high52_breakout.medium_swing (version 13) is no longer blocked.** Its only failure was a missing evidence record, fixed on 2026-11-08. It has not signalled in the one in-scope scan since.

**Neither version lacks a paper book for a reason of its own.** A book is created automatically at a version's first paper decision, and neither version has reached one.

## Where things are

| Item | Path |
|---|---|
| Code read (`W`) | `/private/tmp/claude-501/-Users-louisbrailey-Projects-signal-forge/ec635db8-8e7c-46dd-bc95-83c88a678e74/scratchpad/r3wt` |
| Scratch database | `/private/tmp/claude-501/-Users-louisbrailey-Projects-signal-forge/ec635db8-8e7c-46dd-bc95-83c88a678e74/scratchpad/r3/db/signalforge.sqlite` |
| Script | `W/scripts/r3/dead_approvals_diag.py` |
| SQL | `W/scripts/r3/dead_approvals_queries.sql` |
| Script output | `/private/tmp/claude-501/-Users-louisbrailey-Projects-signal-forge/ec635db8-8e7c-46dd-bc95-83c88a678e74/scratchpad/r3/out/dead-approvals/diag_output.txt` and `diag.json` beside it |
| SQL output | `/private/tmp/claude-501/-Users-louisbrailey-Projects-signal-forge/ec635db8-8e7c-46dd-bc95-83c88a678e74/scratchpad/r3/out/dead-approvals/queries_output.txt` |
| First-pass copies, before the repair | `/private/tmp/claude-501/-Users-louisbrailey-Projects-signal-forge/ec635db8-8e7c-46dd-bc95-83c88a678e74/scratchpad/r3/out/dead-approvals/pre_repair/` |

Code citations are `src/signalforge/...` under `W` unless they start with `scripts/` or `tests/`. Every cited `src` file is the same git blob in the deployed release 21e87a3, except `research/approved_scope_scan.py`, `scheduler.py`, `cli.py` and `research/prospective_funded.py`. Of the cited scripts and tests, `scripts/kronos_comparison_collect.py` and `tests/experiments/test_collector.py` also differ. For those six I checked the cited logic against the release with `git show` and give release line numbers where they differ.

## A. Version 5: the regime-coverage gate

### A1. Two gates count two different things

| | Promotion gate 6 (passed) | Scan gate "OOS regime coverage" (fails) |
|---|---|---|
| Code | `research/promotion.py:1410-1448`, census `:474-507` | `research/scan.py:505-513`, helper `:362-380` |
| Labeller | `backtest/regime.py:25-63`: slope of SPY's 200-day average over one session; "range" when price is within 3% of it | `research/regime.py:63-109`: 50-day against 200-day average, and the 200-day's slope over ten sessions. This is the label the strategies themselves read |
| Buckets | bull / bear / range | bull / bear / neutral. The volatility half of "bull/low" is dropped (`scan.py:376-378`) |
| Trades counted | every pre-sealed trade, in-sample and out-of-sample (`promotion.py:1417`) | out-of-sample only: each symbol's last 40% of bars (`research/backtest_runner.py:164-166, 214-224`), stored per run (`research/persistence.py:167-177`) |
| Label date | entry date (`promotion.py:488`) | entry date (`backtest_runner.py:222`) |
| Threshold | `promotion.min_regimes_covered` 3, `promotion.min_trades_per_regime` 10 (`config/research.py:121-124`) | `quality_gates.min_oos_regimes` 2, `quality_gates.min_trades_per_regime` 10 (`config/research.py:85-90`) |
| In the approval-scope hash | no | yes (`config/research.py:738-755`) |
| Version 5 result | bull 466, bear 11, range 89: 3 of 3, pass | bull 193, neutral 4, bear 0: 1 of 2, fail |

Thresholds are the code defaults. `app_setting.research_overrides` holds no `quality_gates` or `promotion` key (SQL Q8). The effective config hash computed here equals the newest approved-scope scan's hash, `fe365720c0b6…`.

### A2. The recorded evidence

Per-regime out-of-sample rows of the latest development run per version (SQL Q3, Q3b). All four runs are development-window records ending 2025-09-05 (run 49's window field reads 2025-09-07, a Sunday).

| Version (run, symbols) | bull/high | bull/low | neutral/high | neutral/low | bear | By trend: bull / neutral / bear | Trends with 10 or more | Scan gate (needs 2) |
|---|---|---|---|---|---|---|---|---|
| 2 trend_continuation.short_swing (53, 24) | 7 | 280 | 2 | 52 | no row | 287 / 54 / 0 | bull, neutral | pass |
| 3 trend_continuation.medium_swing (55, 150) | 40 | 1,676 | 13 | 257 | no row | 1,716 / 270 / 0 | bull, neutral | pass |
| 5 relative_strength.medium_swing (54, 24) | 49 | 144 | 1 | 3 | no row | 193 / 4 / 0 | bull | **fail** |
| 13 high52_breakout.medium_swing (49, 150) | 14 | 483 | 3 | 25 | no row | 497 / 28 / 0 | bull, neutral | pass |

Recorded expectancy per row, in R, for completeness:

| Version | bull/high | bull/low | neutral/high | neutral/low | All out-of-sample |
|---|---|---|---|---|---|
| 2 | −0.156 | +0.291 | −1.020 | +0.228 | +0.265 on 341 |
| 3 | −0.222 | +0.197 | +0.098 | +0.452 | +0.221 on 1,986 |
| 5 | +0.012 | +0.391 | −1.629 | +1.326 | +0.300 on 197 |
| 13 | +0.290 | +0.216 | +0.818 | +0.335 | +0.227 on 525 |

Gate 6 of the evaluation each run is linked to (SQL Q4; gate 6 only was read):

| Version | Evaluation | Bull | Bear | Range | In no bucket | Rule | Result |
|---|---|---|---|---|---|---|---|
| 2 | 52 | 939 | 22 | 75 | 133 | 10 or more in each of 3 | pass |
| 3 | 54 | 4,972 | 95 | 415 | 673 | same | pass |
| 5 | 53 | 466 | 11 | 89 | 0 | same | pass |
| 13 | 51 | 1,427 | 12 | 58 | 0 | same | pass |

### A3. The contradiction, precisely

1. The rule signals only when `ctx.regime.trend is Trend.BULL` (`research/strategies/relative_strength.py:106-110`). The label is read on the signal bar (`research/strategies/base.py:105-111`).
2. The fill is the next bar (`backtest/engine.py:108-109`). The scan gate labels each trade by that entry date, with the same labeller.
3. So a trade lands outside "bull" only when SPY's label leaves bull overnight, after a bull signal day.
4. In the out-of-sample segment (after 2022-02-10; 894 sessions: 573 bull, 112 neutral, 209 bear) that happened on four entry days: 2022-03-14, 2023-03-14, 2023-06-02 and 2025-04-09. All four are neutral; none is bear.
5. Version 5 has 4 neutral trades, against 10 required. It has no bear trade, although the segment holds 209 bear sessions.
6. Gate 6 passes because the other labeller disagrees with the strategy's own. Of the 1,522 sessions that can follow a bull signal day in the whole window, gate 6's labeller calls 1,332 bull, 168 range and 22 bear. Gate 6's "bear 11" and "range 89" are trades the rule took in what it itself calls a bull market.

Items 4 and 6 come from SPY labels on development bars only (`diag_output.txt` section 8).

### A4. Could any amount of clean evidence pass?

**Not with the current approving evaluation.** The only evidence the scan accepts is an exact reproduction of the approving evaluation: same symbols, window start, cut-off, source and config (`persistence.py:280-287`; `promotion.py:2253-2259, 2385-2391`). For evaluation 53 (24 symbols, from 2016-10-17) that computation is deterministic and yields 4. Re-recording changes nothing, and an identical run is refused without `--force` (`promotion.py:2392-2397`).

**Otherwise only by calendar accident.** A pass needs 10 out-of-sample entries on label-flip sessions. The approved scope has 95 such slots: 23 symbols with 4 flip sessions each, plus 3 for XLC, whose history starts 2018-06-19 so its out-of-sample segment starts after the first flip. 4 of the 95 were filled. Two routes add slots (`diag_output.txt` section 10):

| Route | Slots | Neutral trades at the observed 4-in-95 rate | Against the floor of 10 | Needs |
|---|---|---|---|---|
| Approved scope as evaluated (24 symbols, from 2016-10-17) | 95 | 4 (recorded, run 54) | fail | nothing; this is the evidence on record |
| Same 24 symbols, evaluation window from 2003-10-20 | 143 | about 6 | still under | a new passing evaluation of version 5; no new sealed look |
| The 150-symbol snapshot, window from 2016-10-17 | 597 | about 25 | likely over | a new evaluation on a new snapshot, which is sealed look 5 for this family (four taken: SQL Q6) |

- The two "about" figures are arithmetic, not measurements. No strategy was run.
- 2003-10-20 is SPY's first bar in the database. 12 of the 24 symbols have bars from that day; their out-of-sample segment would start after 2016-11-30 and hold 8 flip sessions. 11 symbols have bars only from 2016-10-17 and keep 4; XLC keeps 3. That gives 12 × 8 + 11 × 4 + 3 = 143.
- The plain proportion for the 150-symbol route is 4 × 150 / 24 = 25.0; by slots it is 597 × 4 / 95 = 25.1.
- Neither route adds a second regime. Every slot's entry day is labelled neutral: 95 of 95, 143 of 143 and 597 of 597. None is bear.
- Whether the bars before 2016-10-17 are admissible evidence, and whether the ten gates would pass on either route, was not examined.

This sharpens a finding already on record. The 2026-09-24 pre-registration called the gate "structurally unsatisfiable for this version on any window" and left eligibility as "an operator policy question" (`docs/research/PREREGISTRATION_2026-09-24_regime_diversity.md:84-87, 156-160`). The 2026-10-02 audit called the refusals "a valid evidence refusal" (`docs/PAPER_OPERATION_AUDIT.md:30`). I found no later decision in the repository documents or in the local continuity archive (three focused searches in the first pass and three more in the repair pass), so the question appears to be still open.

### A5. The options, and what each does to the frozen v2 studies

Replaying the deployed gate functions on the recorded rows shows the regime gate is now the only evidence check version 5 fails (`diag_output.txt` section 4). In its own 24-symbol scope it returns that one failure, and the auto-simulation scope guard matches. None of its 77 in-scope candidates since 2026-09-25 failed reward-to-risk or sizing.

| Option | What changes | Scope hash and re-evaluation | Frozen v2 studies | Would version 5 trade? |
|---|---|---|---|---|
| 1. Leave it | nothing | none | **no effect; the only such option.** Version 5's daily 24-symbol scan is what lets the Kronos medium book's readiness rule be met (see option 2) | no; 4 to 7 refused rows per in-scope scan continue |
| 2. Retire the approval | version 5 set to experimental with the dashboard's downgrade-only action, which changes the strategy row and every version row (`app/routers/dashboard.py:298-329`) | none. The 24-symbol medium-swing scan stops, as it did 2026-10-01 to 10-25: scan groups are built from PAPER_APPROVED versions only (release `research/approved_scope_scan.py:199-204`) | **not safe during the hold: it stops the Kronos medium book.** The collector reports a book ready only when the day's completed-scan audit covers every version the book pins (`scripts/kronos_comparison_collect.py`, release line 131, worktree line 139). The medium book pins 3, 5 and 13. Without version 5's scan the audit covers 3 and 13 only, so the collector waits on every later session and captures nothing, for versions 3 and 13 too. funded-validation-v2 does not read strategy status | no. Re-approval later needs a new passing evaluation, which the hold forbids, so the step cannot be undone during the hold |
| 3. Change how regimes are counted (code) | `scan.py:362-380, 505-513`, with no threshold change. Variants: (a) count gate 6's buckets; (b) require coverage only of the trends a rule may trade, declared on the class and not in `StrategySpec` (`strategies/base.py:42-46`); (c) count trend and volatility cells | **hash unchanged; no re-evaluation.** Variant (a) by re-labelling would need new evidence runs | cannot ship during the hold. Both studies hash `research/` (`experiments/comparison.py:77-91, 286-287`; `prospective_funded.py:41-55, 161-165`, release `:21, :111`). A worker on another commit rewrites `spec_json.git_sha` (`persistence.py:94-96`), and the Kronos collector then skips every candidate (`comparison.py:538`). Once version 5 passes, the Kronos medium book raises "Approval scope changed" on its first candidate, because its pinned scope hash already differs | yes, after the studies are rolled to a new generation |
| 4. Lower a threshold | `quality_gates.min_oos_regimes` 2 to 1, or `min_trades_per_regime` 10 to 4 or less | **hash changes**: `fe365720c0b6…` becomes `74bf65b937e3…` or `c536929cb4f2…` (computed in memory). All four approved versions fall out of scope (`persistence.py:288-289`; `paper/ledger.py:1052-1060`) until each is re-evaluated and its evidence re-recorded. No new sealed look: locked rows are replayed (`promotion.py:947-954`) | breaks three listed prohibitions at once. Both Kronos books raise "Operating research config changed" at the next collection (`comparison.py:478-483`) | yes, and so would any other single-regime rule |
| 5. Re-approve on a wider universe | new evaluation of version 5 on the 150-symbol snapshot | new approved scope; sealed look 5 | a new passing evaluation, which the hold forbids | probably, mechanically: about 25 neutral trades against a floor of 10 (arithmetic, not measured; A4). Still a calendar accident, not a second regime |
| 6. Re-evaluate the same 24 symbols over a longer window | new evaluation of version 5 on the same snapshot with an earlier `--since` (`cli.py:3377-3380`), then a new evidence record | hash unchanged. No new sealed look: the locked row for version 5 on snapshot 3 is replayed (`promotion.py:947-954`), as evaluations 47, 49 and 53 did with three different windows (SQL Q5) | a new passing evaluation and a new evidence run for an approved version, both forbidden in the hold | probably not: about 6 neutral trades against a floor of 10 (arithmetic, not measured; A4) |

Notes on the table:

- **Option 2 and the Kronos collector.** A test pins the rule: a scan that covers other versions never triggers (`tests/experiments/test_collector.py:76-89`). I replayed the coverage part of the rule on the recorded scan audits (`diag_output.txt` section 9):
  - The newest audit (544, 2026-11-10 01:23 UTC) covers versions 3, 5 and 13. A book pinning those three is covered.
  - Take version 5's scan group out of that audit and it covers 3 and 13. The book is not covered. A book pinning only 3 and 13 would be.
  - The same holds for all three audits that cover the full set (493, 519, 544).
  - While version 5 was experimental (20 audits, 2026-10-01 to 2026-10-25) none covers version 5; 18 cover version 3.
- **Limits of that replay.** The job-status and time-of-day conditions of the rule were not replayed. I did not open the book's manifest: the pinned set 3, 5, 13 is from `maps/constraints.md` section 1 and from the freeze rule (`experiments/comparison.py:151-160`) applied to the statuses in this database copy. I did not check which checkout the live collector runs from; the readiness line is the same in the release and in main. A manual `scripts/kronos_comparison.py advance` does not go through the readiness rule (`scripts/kronos_comparison.py:49-50`); that is an override, not a way to keep the study running.
- **If the Kronos books are rolled anyway.** The orchestrator's alert (`r3/ckpt_alert.md`, not re-verified here) says the medium book's pinned scope hashes for versions 3 and 5 already differ and recommends a new generation. A generation frozen after a retirement would pin 3 and 13 only. A generation frozen while version 5 is still approved pins it again, and a later retirement stops that book the same way. So the order is: retire first, then freeze.
- The funded study's independence from strategy status rests on a search of the release's `research/prospective_funded.py`, `research/action_replay.py`, `research/strategy_scope.py` and `scripts/funded_forward.py`: none reads a status, an approval scope or a scan.
- Option 3(a) would rest on 11 "bear" trades, one above the floor, taken on days the rule calls bull.
- Option 3(c) contradicts the stated intent (`config/research.py:85-88`; `scan.py:363-365`) and a test (`tests/research/test_scan.py:171-174`).
- Option 4 has no supported control. The Settings form writes three keys only (`dashboard.py:350-372`); it would be a code-default edit or a manual settings write. A test pins `min_oos_regimes >= 2` (`tests/research/test_scan.py:141`), and ADR 0004 names `min_oos_regimes` among things not to change (`docs/decisions/0004-kronos-regime-input.md:122`). Setting the floor to 4 would be tuning it to the observed count.
- The Kronos scope-hash mismatch for version 5 is taken from the orchestrator's alert, not re-verified here.

### A6. The same rule is frozen into funded-validation-v2 (inference from code; no study file opened)

The funded study's review floor also needs two trend regimes with 10 trades each, keyed on the **signal** day (release 21e87a3 `research/prospective_funded.py:97-98, 193-200`; worktree `:128-129, 584-591`). Its labels come from the labeller the rule gates on (`research/action_replay.py:228-231, 247`). Every relative_strength trade there is signalled in bull, so that book's status can never read "EVIDENCE_REVIEW_REQUIRED".

That does not leave the book without a review. The plan has a 252-session maximum, after which further collections are refused with "Planned collection horizon completed; review required" (release `:99, :122-124`; worktree `:130, :500-501`). So this book cannot qualify for review early; its review comes only when the horizon ends, with its status still reading "INSUFFICIENT_EVIDENCE" (release `:205`).

### A7. Could the gate start blocking version 13 or trend_continuation?

**It already has blocked trend_continuation.** Every approved-scope candidate of versions 2 and 3 cited this gate until 2026-09-24: 19 rows for version 2 on the 24-symbol scan, 63 for version 3 on the 150-symbol scan (SQL Q10). Evidence runs with a four-year window replaced two-year ones at 2026-09-24 23:33 UTC (SQL Q21), and the first passing candidates appeared the next day. Version 5's rows kept failing.

The gate reads only the newest run for a version (`persistence.py:215-231`), so its verdict moves only when a new run is recorded, or thresholds or code change.

| Version | Neutral trades now | Margin over 10 | What would flip it |
|---|---|---|---|
| 2 | 54 | 44 | a newer run with under 10 neutral trades |
| 3 | 270 | 260 | same |
| 13 | 28 | 18 | same. On a 24-symbol scope 28 scales to about 4 or 5 (arithmetic, not measured), so high52 would fail there |

Three related hazards:

- **An exploratory `backtest-report` (code reading; never observed).** It writes a run with no reproduction flags for every default strategy in one go (`cli.py:2820-2837`). Each becomes the newest run for its version. The scan would then refuse every candidate of every approved version with "OOS scope mismatch: complete five literal-True reproduction flags required" (`persistence.py:280-287`). As of this database copy no candidate row carries an "OOS scope mismatch" string (SQL Q24).
- **A forced evidence record (observed, on version 5 only).** Runs 50 to 52 were development records written with `allow_mismatch`; the mismatched inputs were the config hash and the cut-off (SQL Q22). The scan refuses such a run through a different check, "OOS provenance mismatch" (`persistence.py:181-212, 272-273`). The scans of session 2026-11-09 carry that string on all 69 version 5 rows: 5 in scope, 58 on the 150-symbol scan and 6 on a 25-symbol scan with no source (SQL Q23). Versions 2 and 3 produced no candidate on those scans, and none since 2026-11-04 (SQL Q25), so runs 50 and 52 blocked nothing that was observed. Runs 53 to 55 replaced all three on 2026-11-10.
- Raising `min_oos_regimes` to 3 would block all four versions. None has a bear row.

## B. Paper books

### B1. How a book comes to exist

- **Automatically, at the first paper decision.** `book_for_candidate` creates `book-sv<id>` for a PAPER_APPROVED version when none exists (`paper/books.py:125-141`). It is called by auto-simulation (`paper/auto_simulate.py:179`) and by any manual decision (`paper/ledger.py:131-138`, used at `:172` and `:468`).
- **Approval creates nothing.** The migration inserts no account (`db/migrations/versions/20261003_0900-e3b8c5d1f7a2_paper_books_per_strategy_version.py:21-22`). `docs/PAPER_OPERATIONS.md:54-58` says the same.
- **Auto-simulation only looks at passing candidates** (`auto_simulate.py:158-163`), after the approved-scope scan (`scheduler.py:899-904`).
- **No command is needed.** `book-sv2` appeared at 2026-10-08 22:00:45 UTC, in the same second as its first two accepted trades, at the first scan with passing version 2 candidates since 2026-10-01 (audit row 254; SQL Q7, Q19, Q20).
- **Do not pre-create a book with `signalforge paper init --name book-sv13`.** That makes an unkeyed account (`cli.py:3052-3081`); the later keyed create then hits the unique name and raises (`books.py:103-107`).
- A manual `signalforge paper accept <candidate_id>` would also create the book, because the manual path does not check the quality gate (`ledger.py:436-473`). That is an override, not a fix.

Accounts on record: `default` (version 3), `grid`, `options`, `book-sv2`. Auto-simulation is on, at 2 accepts per book per UTC day.

### B2. Version 13 now

| Fact | Value |
|---|---|
| Approved | 2026-11-04 02:42:43 UTC, evaluation 51, snapshot 11 (150 symbols) |
| All candidates ever | 17, all from the 2026-11-04 23:00 UTC scans, all refused only for "no out-of-sample backtest on record" (`scan.py:487-491`) |
| Of those in its own scope | 13 (scan 405). The other 4 are from the 24-symbol scan, where it is not approved |
| Evidence recorded | backtest_run 49, 2026-11-08 20:57:14 UTC |
| Candidates since 2026-11-08 | **0** (SQL Q16) |
| In-scope scans since run 49 | 1 (scan 425, session 2026-11-09), with no high52 signal on any of 150 symbols |
| Replay of the scan's evidence gates on recorded rows | no failure in the 150-symbol scope; "saved dataset identity does not match" in the 24-symbol scope |
| Auto-simulation scope guard, replayed | matches in the 150-symbol scope |

**So the fix is in place but untested by a live signal.** At the next high52 signal in the 150-symbol scan the candidate should pass, `book-sv13` should be created with $30,000 of simulated cash, and up to 2 entries per UTC day accepted, subject to the freshness check and the book's risk caps (`ledger.py:284-433, 1006-1061`). All 13 earlier in-scope candidates cleared reward-to-risk and sizing.

Run 49 was written by an older revision. It lacks the `data_provenance` and `development_calendar` blocks. The deployed check treats the first as optional (`persistence.py:317-325`) and does not read the second (SQL Q17).

Version 13's pinned scope hash still matches (per the alert), and it is not in the funded study, so its first trades add no new problem for the frozen studies.

### B3. Version 5

It has no book because it has had 0 passing candidates in 13,321. 13,315 cite the regime gate. The other 6 are from one scan on 2026-09-07 07:33 UTC, the day the gate was committed (SQL Q11, Q18; commit 25c781b).

## C. Forgone signals since 2026-09-25 (counts only; nothing priced)

"Since" means `scan_run.started_at` on or after 2026-09-25 00:00 UTC. Sessions are assigned with the exchange calendar (`data/calendar.py:77-92`); no bar was read. The period has 32 XNYS sessions. No candidate was ever blocked by a missing book, so for version 13 the count is of signals blocked only by the missing evidence record.

| Version | In-scope scans (sessions) | In-scope rows | Blocked only by the named cause | Distinct session and symbol | Distinct symbols | Ceiling at 2 entries per UTC day |
|---|---|---|---|---|---|---|
| 5 relative_strength | 15, of which 14 scanned (12 of 32) | 77, none passed | 72 by the regime gate alone; 5 more by the regime gate plus a provenance mismatch | 61 + 5 = 66 | 10 of 24 | 24 + 2 = 26, over 13 UTC days |
| 13 high52_breakout | 3 since approval (3) | 13, none passed | 13 by the missing evidence record alone | 13 | 13 | 2, on one UTC day |
| 2 trend_continuation.short | 36, of which 30 scanned (22) | 32, all passed | 0 | n/a | n/a | n/a |
| 3 trend_continuation.medium | 30, of which 26 scanned (20) | 165, all passed | 0 | n/a | n/a | n/a |

- The 5 provenance rows are the 2026-11-09 session, when the newest version 5 run was a forced one. Run 54 cleared that at 04:53 UTC on 2026-11-10.
- **The ceiling is counted per UTC day, because that is the code's cap**: 2 accepted trades per book since 00:00 UTC (`paper/auto_simulate.py:88-102`). Version 5's in-scope rows fall on 13 UTC days, each with at least 2 distinct symbols (SQL Q27). Counted per session it would be 22 + 2 = 24, which is not an upper bound: sessions 2026-09-25 and 2026-11-06 were each scanned on two UTC days, and sessions 2026-10-23 and 2026-10-26 were both scanned on one.
- The ceiling is an upper bound on entries, not a count of trades. A held symbol cannot be re-entered, and exits were not priced.
- **Version 5 had no in-scope scan on 20 of 32 sessions.** On 10 of them no approved-scope scan run scanned anything. On the other 10 a scan ran and scanned symbols, but none in version 5's scope.
- **It was not approved for most of that gap.** None of the 20 completed-scan audits from 2026-10-01 19:59 UTC to 2026-10-25 22:46 UTC lists version 5 (SQL Q13, Q28). Audit row 396 shows it moving from experimental back to paper_approved on 2026-10-26 17:29 UTC (SQL Q15). Judged by session close, 16 of the 20 sessions (2026-10-01 to 2026-10-22) fall inside that stretch. On 3 (2026-09-28, 09-29, 09-30) its status is not established: the demotion falls somewhere between 2026-09-26 22:00 and 2026-10-01 19:59 UTC. On 1 (2026-11-05) it was approved and no approved-scope scan ran.
- On 9 of the 10 scanned sessions the 150-symbol scan recorded 44 version 5 signals on the 24 approved symbols. They are out of scope and not counted. The tenth, 2026-10-06, had only the short-swing scan: the job failed after it (scan 238, audit row 242; SQL Q26).
- A further 1,100 version 5 rows since 2026-09-25 come from the 150-symbol scan, where it is not approved. 77 + 1,100 is the 1,177 in the paper-funnel map.

Version 5 by session:

| Session | Scans (UTC day of the scan) | Rows | Distinct symbols | Refused for |
|---|---|---|---|---|
| 2026-09-25 | 169 (09-25), 179 (09-26) | 10 | 5 | regime gate |
| 2026-10-23 | 342 (10-26) | 4 | 4 | regime gate |
| 2026-10-26 | 349 (10-26) | 5 | 5 | regime gate |
| 2026-10-27 | 356 (10-27) | 6 | 6 | regime gate |
| 2026-10-28 | 368 (10-28) | 5 | 5 | regime gate |
| 2026-10-29 | 375 (10-30) | 5 | 5 | regime gate |
| 2026-10-30 | 382 (11-01) | 6 | 6 | regime gate |
| 2026-11-02 | 389 (11-02) | 7 | 7 | regime gate |
| 2026-11-03 | 396 (11-03) | 6 | 6 | regime gate |
| 2026-11-04 | 403 (11-04) | 6 | 6 | regime gate |
| 2026-11-06 | 410 (11-06), 417 (11-08) | 12 | 6 | regime gate |
| 2026-11-09 | 423 (11-10) | 5 | 5 | regime gate and provenance mismatch |

Version 5 by UTC day, the cap's unit:

| UTC day | Scans | Rows | Distinct symbols | Counted toward the ceiling |
|---|---|---|---|---|
| 2026-09-25 | 169 | 5 | 5 | 2 |
| 2026-09-26 | 179 | 5 | 5 | 2 |
| 2026-10-26 | 342, 349 | 9 | 6 | 2 |
| 2026-10-27 | 356 | 6 | 6 | 2 |
| 2026-10-28 | 368 | 5 | 5 | 2 |
| 2026-10-30 | 375 | 5 | 5 | 2 |
| 2026-11-01 | 382 | 6 | 6 | 2 |
| 2026-11-02 | 389 | 7 | 7 | 2 |
| 2026-11-03 | 396 | 6 | 6 | 2 |
| 2026-11-04 | 403 | 6 | 6 | 2 |
| 2026-11-06 | 410 | 6 | 6 | 2 |
| 2026-11-08 | 417 | 6 | 6 | 2 |
| 2026-11-10 | 423 | 5 | 5 | 2 |
| Total, 13 UTC days | 15 scans, 14 with rows | 77 | | 26 |

Scan 362 (2026-10-28 21:48 UTC) is the fifteenth in-scope scan. It scanned nothing and has no rows.

Version 13: session 2026-11-04, scan 405, 13 rows, 13 symbols, refused for no evidence record. Sessions 2026-11-06 and 2026-11-09: 0 rows.

## Verdicts

| Version | Why it earns nothing | Minimal fix | Who decides |
|---|---|---|---|
| 5 relative_strength.medium_swing | The scan gate needs two trend regimes; the rule may only enter in one. 193 bull and 4 neutral out-of-sample trades against a floor of 10. With the current approving evaluation that count cannot change | None makes it trade without a policy decision. The only state with no effect on the frozen studies is to leave it inert. Do not retire the approval while the generation 2 Kronos medium book is active: that stops the book's collector. To trade: a code change to the regime count, with no hash change and no re-evaluation, deployable only when the v2 studies are rolled | The operator. The eligibility question was recorded as open on 2026-09-24 and I found no decision since |
| 13 high52_breakout.medium_swing | Until 2026-11-08 it had no evidence record. Since then it has not signalled | None. Already fixed by backtest_run 49. The book creates itself | Nobody needs to act. The operator may want to know a third $30,000 simulated book will open by itself |

## Commands (all NOT RUN)

A frozen-study hold is in force. Nothing below was executed, and the exact flags used for evaluations 52 to 54 are not recorded in the database, so the write commands are forms taken from the CLI help.

**Version 13: nothing to run.** Optional read-only checks, safe during the hold:

```sh
sqlite3 -readonly data/signalforge.sqlite "SELECT scan_run_id, quality_gate_status, failed_gates, count(*) FROM candidate WHERE strategy_version_id=13 AND created_at>='2026-11-10' GROUP BY 1,2,3;"
sqlite3 -readonly data/signalforge.sqlite "SELECT id, name, strategy_version_id, initial_cash, created_at FROM paper_account;"
```

Do not run `signalforge paper init --name book-sv13`.

**Version 5, option 1 (leave it): nothing to run.**

**Version 5, option 2 (retire): do not do this while kronos-comparison-v2-medium is the active medium book.** The action itself is in the dashboard, Strategies page: set `relative_strength.medium_swing` to experimental. This posts `status=experimental` to `/strategies/relative_strength.medium_swing/status`. Hold: not safe. It removes version 5's scan, and the medium book's collector then never reports ready (A5). It cannot be undone during the hold. If the approval is to be retired, do it before freezing the next Kronos medium generation, which will then pin versions 3 and 13 only.

**Version 5, option 3 (code change).** No command. It is a pull request after the operator's decision, deployed only with a new study generation. No re-evaluation follows. Hold: blocked until both v2 studies are rolled, and the Kronos medium book must be rolled first.

**Version 5, option 4 (threshold), not recommended.** After the config change, all four versions need re-evaluation and new evidence:

```sh
uv run signalforge evaluate-promotion --strategy trend_continuation.short_swing --dataset ex_meta --since 2016-10-17 --until 2026-09-08
uv run signalforge evaluate-promotion --strategy relative_strength.medium_swing --dataset ex_meta --since 2016-10-17 --until 2026-09-08
uv run python scripts/evaluate_on_snapshot.py --strategy trend_continuation.medium_swing --snapshot-key research_150_massive_10y_presealed_sel --start 2016-10-17 --end 2026-09-08 --confirm
uv run python scripts/evaluate_on_snapshot.py --strategy high52_breakout.medium_swing --snapshot-key research_150_massive_10y_presealed_sel --start 2016-10-17 --end 2026-09-08 --confirm
uv run signalforge record-oos-backtest --strategy <key> --snapshot-id <3 or 11> --until 2025-09-05 --evaluation-id <new id>   # once per version
```

Hold: forbidden. It changes the research config, adds passing evaluations and adds evidence runs for approved versions.

**Version 5, option 5 (wider universe), not recommended.** Sealed look 5; needs explicit authorisation:

```sh
uv run python scripts/evaluate_on_snapshot.py --strategy relative_strength.medium_swing --snapshot-key research_150_massive_10y_presealed_sel --start 2016-10-17 --end 2026-09-08 --confirm
```

Hold: forbidden. A new passing evaluation.

**Version 5, option 6 (longer window), not recommended.** About 6 neutral trades expected against a floor of 10:

```sh
uv run signalforge evaluate-promotion --strategy relative_strength.medium_swing --dataset ex_meta --since 2003-10-20 --until 2026-09-08
uv run signalforge record-oos-backtest --strategy relative_strength.medium_swing --snapshot-id 3 --until 2025-09-05 --evaluation-id <new id>
```

Hold: forbidden. A new passing evaluation and a new evidence run for an approved version.

## Deviations and clarifications

1. **Scope of work.** Diagnosis only. I ran no scan, no promotion evaluation and no strategy backtest, and wrote nothing outside the script directory and this output directory. There is no pre-registered results path for this study, so this file stays in the output directory.
2. **Price series loaded, all source `massive`, all ending 2025-09-05, each load asserted not to pass that date:**
   - first pass: SPY from 2016-10-17, to count regime labels;
   - repair pass: SPY from its first bar (2003-10-20), and the 24 symbols of snapshot 3 (from both starts) and the 150 symbols of snapshot 11 (from 2016-10-17).
   Only bar dates and SPY's regime labels were used. No return, level or price was computed or printed.
3. **Functions replayed on recorded rows** (`latest_oos_metric`, `oos_scope_failures`, `_oos_metric_failures`, `_oos_regime_coverage`, `approved_scopes`, `scan_scope_matches`, `approved_scan_groups`, and in the repair pass `_is_boundary` and `regime_lookup`). These read; they do not scan. The database was opened read-only.
4. **The Kronos collector's readiness rule was re-implemented from the script's source**, coverage part only, and run on the recorded scan audit payloads. No manifest, book or collection file was opened.
5. **Identity checks:** 28 of 28 passed before any result was read (`diag_output.txt` section 0): config hash, statuses, spec hashes, run ids 53/55/54/49, development windows, per-regime rows summing to the out-of-sample totals, and two added in the repair pass (the approved medium-swing versions are 3, 5 and 13; every `massive` scan since 2026-09-25 is on snapshot 3 or 11).
6. **Read-only git commands** (`log`, `diff`, `show`, `rev-parse`, `cat-file`, `grep`, `status`) were used in the worktree to compare it with release 21e87a3. The release directory itself was not opened. Git state is unchanged. In the first pass I listed the operating data folder once (names and timestamps only) to confirm I had written nothing there; no file in it was opened.
7. **"B" in part C.** Nothing was blocked by a missing book. For version 13 I counted the signals blocked by the missing evidence record.
8. **Not verified:**
   - why version 5 was demoted between 2026-09-26 22:00 and 2026-10-01 19:59 UTC. The database has no audit row; the dashboard downgrade writes only to the JSONL audit file (`audit.py:26-36`), which I did not open;
   - whether the silence of high52 and trend_continuation on the 2026-11-06 and 2026-11-09 scans reflects a risk-off label. Checking needs bars after the development window;
   - the Kronos scope-hash states, taken from `r3/ckpt_alert.md`;
   - that the Kronos medium book's manifest pins versions 3, 5 and 13, and which checkout its live collector runs from (A5 notes);
   - which trade was entered on which day in A3. Trades are not stored one by one (`backtest_trade` is empty). The claim rests on the four flip sessions being the only possible entry days for a non-bull label;
   - whether bars before 2016-10-17 are admissible evidence, and whether the ten promotion gates would pass on the routes in A4.
9. **Frozen studies.** No study file or outcome was opened. Statements about them come from code and `maps/constraints.md`.
10. **Seen in passing and not used:**
    - three table lines (200-202) of `docs/research/PREREGISTRATION_2026-09-24_regime_diversity.md` section 9, quoting expectancy for runs 46 to 48, whose windows run past 2025-09-07;
    - one gate string from scan 2 (2026-09-07) embedding a confidence-interval figure from an early run with such a window;
    - two audit rows (173, 192) showing symbol, share count and simulated fill price of two operating paper trades;
    - repair pass: the first 150 characters of audit rows 238 to 245 (agent-run and job metadata and one job error string; no price or trade field).
11. **Repair pass, 2026-11-10.** An adversarial review raised one blocker and five minor findings. All six were confirmed against the code and the scratch database, and all six are fixed here:
    - *Blocker, option 2.* The first draft called retiring version 5 a "consistent state" with no effect on the frozen studies. It had read only the collection step, which skips non-approved versions, and missed the readiness rule that decides whether a book collects at all. Corrected in the opening paragraph, A5, Verdicts and Commands; evidence in section 9 of the script output.
    - *Ceiling.* Was 24, counted per session. The code's cap is per UTC day, which gives 26 (SQL Q27).
    - *Sessions without an in-scope scan.* Was 11 and 9; it is 10 and 10. The first draft read completed-scan audit rows only and missed scan 238 on 2026-10-06, whose job failed. The 16 / 3 / 1 split by approval state is new.
    - *A4 and A5.* The slot count was 96; it is 95 (XLC). The longer-window route was missing; it is option 6. Option 5 said "unknown"; it now carries the same arithmetic as A7.
    - *A7.* The hazard bullet mixed a `backtest-report` run with the forced runs 50 to 52. It is now two bullets, one from code reading and one observed.
    - *A6.* Added the 252-session horizon, so "never review-ready" is not read as "never reviewed".
12. **Reconciliation with the scouts.** The paper-funnel map's 1,177 version 5 rows are 77 in scope plus 1,100 out of scope. Its "14 (13)" scans against my "15 (14)" is now reconciled: the map counts scans listed in completed-scan audit rows, and I count `scan_run` rows. The one scan between them is 356 (2026-10-27 22:26 UTC), whose job failed after scanning. The same two failed jobs explain version 2: 34 (28) in the map, 36 (30) here, the difference being scans 238 and 357.

## Exact SQL

All of it is in `W/scripts/r3/dead_approvals_queries.sql` (Q1 to Q28; Q22 to Q28 were added in the repair pass), run as:

```sh
sqlite3 -header -column 'file:/private/tmp/claude-501/-Users-louisbrailey-Projects-signal-forge/ec635db8-8e7c-46dd-bc95-83c88a678e74/scratchpad/r3/db/signalforge.sqlite?immutable=1' < dead_approvals_queries.sql
```

The queries behind the main tables:

```sql
-- Q3b: per-regime rows collapsed to the trend the scan gate counts
SELECT m.run_id, r.strategy_version_id,
       substr(json_extract(m.metrics_json,'$.regime_label'),1,
              instr(json_extract(m.metrics_json,'$.regime_label'),'/')-1) AS trend,
       sum(CAST(json_extract(m.metrics_json,'$.n_trades') AS INTEGER)) AS n_trades,
       sum(CAST(json_extract(m.metrics_json,'$.n_trades') AS INTEGER)) >= 10 AS meets_10
FROM backtest_metric m JOIN backtest_run r ON r.id=m.run_id
WHERE m.run_id IN (53,55,54,49) AND m.phase='oos_by_regime' GROUP BY 1,2,3 ORDER BY 2,3;

-- Q4: promotion gate 6 only
SELECT e.id, e.strategy_version_id, json_extract(g.value,'$.passed'),
       json_extract(g.value,'$.evidence.trades_per_regime.bull'),
       json_extract(g.value,'$.evidence.trades_per_regime.bear'),
       json_extract(g.value,'$.evidence.trades_per_regime.range'),
       json_extract(g.value,'$.evidence.min_trades_per_regime'),
       json_extract(g.value,'$.evidence.n_trades_considered')
FROM strategy_promotion_evaluation e, json_each(e.gates_json) g
WHERE e.id IN (52,53,54,51) AND json_extract(g.value,'$.number')=6;

-- Q7: books and switches
SELECT id, name, strategy_version_id, initial_cash, created_at FROM paper_account ORDER BY id;
SELECT key, value_json FROM app_setting
WHERE key IN ('auto_simulate_qualified_signals','auto_simulate_max_per_day');
SELECT id, ts, actor, entity, after_json FROM audit_log WHERE action='paper.book_created';

-- Q10: every regime-gate string, by version and scan scope
SELECT c.strategy_version_id, sr.dataset_snapshot_id, coalesce(sr.source,''), j.value, count(*),
       min(sr.started_at), max(sr.started_at)
FROM candidate c JOIN scan_run sr ON sr.id=c.scan_run_id, json_each(c.failed_gates) j
WHERE c.strategy_version_id IN (2,3,5,13) AND j.value LIKE 'OOS regime coverage%'
GROUP BY 1,2,3,4;

-- Q16: version 13 candidates since 2026-11-08, and all of them by scan
SELECT count(*) FROM candidate WHERE strategy_version_id=13 AND created_at>='2026-11-08';
SELECT c.scan_run_id, sr.started_at, sr.dataset_snapshot_id, c.quality_gate_status, c.failed_gates, count(*)
FROM candidate c JOIN scan_run sr ON sr.id=c.scan_run_id WHERE c.strategy_version_id=13 GROUP BY 1,2,3,4,5;

-- Q27: version 5 in-scope rows by UTC day of the scan, and the ceiling at 2 per UTC day
SELECT date(sr.started_at) AS utc_day, group_concat(DISTINCT sr.id) AS scans, count(*) AS rows_,
       count(DISTINCT c.instrument_id) AS symbols, min(2, count(DISTINCT c.instrument_id)) AS capped
FROM candidate c JOIN scan_run sr ON sr.id=c.scan_run_id
WHERE c.strategy_version_id=5 AND sr.source='massive' AND sr.dataset_snapshot_id=3
  AND sr.horizon='MEDIUM_SWING' AND sr.started_at>='2026-09-25'
GROUP BY 1 ORDER BY 1;

-- Part C (in the script): candidates joined to their scan; scope and session are applied in Python
SELECT c.id, c.strategy_version_id, c.scan_run_id, c.quality_gate_status, c.failed_gates, c.created_at, i.symbol
FROM candidate c JOIN scan_run sr ON sr.id=c.scan_run_id JOIN instrument i ON i.id=c.instrument_id
WHERE sr.started_at >= '2026-09-25' AND sr.source='massive' AND c.strategy_version_id IN (2,3,5,13);
SELECT id, started_at, source, dataset_snapshot_id, horizon, config_hash, universe_json, scanned_count, candidate_count
FROM scan_run WHERE started_at >= '2026-09-25' AND source='massive';
```

A scan is in a version's scope when its source is `massive` and its horizon, dataset snapshot, config hash and exact symbol set all equal those of one of the version's passing evaluations. That is the rule in `research/approval_scope.py:102-138`.

Research signal only — no order was placed.
