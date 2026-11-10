# Kronos comparison books and the 2026-11-10 re-scope: roll back, or roll forward?

Read-only operations plan. Nothing on the operating system was changed. Every step in the step lists is marked NOT RUN.

**Read this first: timing.** The evidence was gathered 2026-11-10 11:39 to 12:12 UTC, from a database copy taken at 08:46 UTC. The Mac then slept from about 12:07 until about 22:59 UTC. The worker log has no job between 12:07:16 and 23:03:00. The scheduled 22:30 UTC end-of-day job did not start. According to a checkpoint another session recorded at 23:04 UTC, the machine was awake by 22:59 with the worker's scheduler not firing, and that session stopped and restarted the worker at 23:01 UTC on the same release (21e87a3); the catch-up ingest at 23:03:00 UTC is the restarted worker's start-up catch-up. I did not verify the "scheduler stuck" claim myself. So tonight's Kronos window is short, and the roll-back can no longer be done cleanly for session 2026-11-10. This plan was first finished at 23:05 UTC and repaired after review at about 23:20 UTC (see "Repair after review" at the end).

## Recommendation

**Do not roll back (option A). Roll the two Kronos books to a new generation (option B), but not tonight, and not with the tool as it stands.** Tonight, change nothing.

1. **Rolling back works mechanically and is a bad trade.** Deleting the three evaluations and three runs restores all four pinned hashes exactly (tested on a private copy). But versions 2 and 3 then fall back to forced evidence the scan refuses, and no clean evidence can be recorded under the old pins (tested). The two strategies that actually trade would stop producing paper candidates for as long as generation 2 is kept, the short book would stay empty for its whole 252-session life, and the medium book would hold version 13 only.
2. **Generation 2 has nothing to protect.** As far as I can establish without opening the books, neither Kronos book has captured a session. The first one (2026-11-09) was missed because the Mac slept through the collection window.
3. **A new generation cannot be made with the committed tool, and cannot capture tonight's session whatever is done.** The tool hard-codes "v2" names, the registry refuses a re-used name (replayed in memory), and activation demands three fresh studies including a new funded-validation study. By the date rule the first session a new generation could observe is 2026-11-11, but that needs a tooling change reviewed and a release ready before 05:00 UTC tonight. Realistically 2026-11-12 or 2026-11-13, **and only if the tooling commit is cut on a release branch that does not contain PR #68**. PR #68 is already merged into main, so a tooling change merged through main cannot be used with the present worker (section D, "Which base for the tooling commit"). The main-based route takes longer: it also needs a worker deployment and a roll of all three studies.
4. **Fix the sleeping Mac before either option; it is costing more sessions than the scope question.** No worker job ran for three stretches in 27 hours: 20:22 to 00:48 UTC (the whole first collection window), 05:07 to 08:36, and 12:07 to 23:03 today (through the scheduled 22:30 start). No option captures anything while the machine is asleep. After the third stretch jobs reportedly did not resume on wake until the worker was restarted, so being awake at 22:30 may not be enough: the Mac should not sleep at all on a trading day, or someone must check that jobs resume after every wake.

**If nothing is done tonight:** each generation-2 book completes the session if its stale version has no passing candidate, and refuses the whole session if it has. Counting only sessions the collector could have collected (an ok scan job between the close and UTC midnight), that was 7 of 14 since 2026-09-25, the same 7 for both books: about half. The other 18 of the 32 sessions had no in-window scan and would have been lost anyway. (Counting scans at any time of day, the versions signalled on 11 of 32 sessions.) Nothing else is affected. Paper trading does not depend on these books.

**Three decisions are the operator's:**

| Decision | My lean | Why |
|---|---|---|
| Version 5 (relative_strength.medium_swing): retire before the freeze, or pin it again | Retire first | It cannot pass the scan. Pinned, it makes the medium book depend on a second nightly scan (24 symbols) and stops the book if it is ever retired later |
| funded-validation-v2: restart it with the Kronos books, or change the tool to carry it over | Operator's call | The committed design restarts it (it has 1 captured session, 2 after tonight). Carrying it needs new cutover logic around a live study |
| Roll now with the worker left on 21e87a3, or once together with deploying the held worker update (PR #68) | Ask before building | PR #68 is **already merged into main** (main's head 1479b1c is its merge commit); only its deployment is held. It changes 9 files inside the studies' code hashes, so deploying it forces a roll of all three studies anyway (`docs/WORKER_RELIABILITY_RELEASE.md:7-29`). "Roll now" therefore needs a release cut from a side branch that excludes PR #68 (section D) |

## Where things are

| Item | Path |
|---|---|
| Worktree read (`W`) | `/private/tmp/claude-501/-Users-louisbrailey-Projects-signal-forge/ec635db8-8e7c-46dd-bc95-83c88a678e74/scratchpad/r3wt` |
| Scratch database (copied 2026-11-10 08:46 UTC) | `/private/tmp/claude-501/-Users-louisbrailey-Projects-signal-forge/ec635db8-8e7c-46dd-bc95-83c88a678e74/scratchpad/r3/db/signalforge.sqlite` |
| Everything this task wrote (`OUT`) | `/private/tmp/claude-501/-Users-louisbrailey-Projects-signal-forge/ec635db8-8e7c-46dd-bc95-83c88a678e74/scratchpad/r3/out/roll-plan/` |
| Roll-back SQL, tested on the private copy only | `OUT/option_A_rollback.sql` |
| Read-only SQL as run | `OUT/queries.sql` |

"Release" means commit 21e87a3, read with `git show`. "Deployed collector" means `scripts/kronos_comparison_collect.py` at commit 3a202c5, which is what the launchd job names. It is the same file as in the worktree. Where the two differ I give both line numbers as release / deployed.

## Timeline (UTC, from row timestamps)

| When | What | Source |
|---|---|---|
| 2026-11-09 02:50:54, 02:51:01 | short and medium books staged | `refresh.json` `created_at` |
| 2026-11-09 02:51:58 | generation 2 activated, first observation 2026-11-09 | `active.json` |
| 2026-11-09 20:22 to 2026-11-10 00:48 | no worker job ran (266 minutes) | Q13; `W/docs/STUDY_OPERATIONS.md:10-16` says the lid was closed |
| 2026-11-10 00:00 | collection deadline for session 2026-11-09 passes | collector line 53 / 60-67 |
| 2026-11-10 01:22:59 to 01:23:08 | approved-scope scan for session 2026-11-09 (job 7511, audit 544) | Q12, Q10 |
| 2026-11-10 01:30 | funded-validation-v2 collects 2026-11-09, 1 observed session | forward collector log, last 60 lines |
| 2026-11-10 04:50:22, 04:50:53, 04:52:44 | evaluations 52 (version 2), 53 (version 5), 54 (version 3) | Q4 |
| 2026-11-10 04:52:56, 04:53:00, 04:53:11 | runs 53 (version 2), 54 (version 5), 55 (version 3) | Q6 |
| 2026-11-10 05:07 to 08:36 | no worker job ran (209 minutes) | Q13 |
| 2026-11-10 12:07 to 23:03 | no worker job ran (about 656 minutes) | worker log, last 60 lines, read at 23:03 UTC |
| 2026-11-10 about 22:59 | Mac awake again; worker heartbeat back but no job firing (reported, not verified by me) | checkpoint of another session, `~/.local/share/codex-continuity/notes/20261110-150434-f33badcb.md` |
| 2026-11-10 23:01 | worker stopped and restarted by that other session, same release 21e87a3 | same checkpoint |
| 2026-11-10 21:00 | close of session 2026-11-10 | project calendar |
| 2026-11-10 22:30 | end-of-day chain was due (17:30 New York); it did not start | release `scheduler.py:1379-1386`; worker log |
| 2026-11-10 23:03:00 | start-up catch-up ingest of the restarted worker begins | worker log; same checkpoint |
| on a normal night, about 23:01 to 23:09 | scan step finishes (23:00:56 on 11-06, 23:08:54 on 11-08), about 30 minutes after the ingest starts | Q12 |
| 2026-11-11 00:00 | collection deadline for session 2026-11-10 | collector line 53 / 60-67; `comparison.py:622, 651` |

**The brief's "2026-11-09 about 20:50 UTC" is 20:50 Pacific.** The rows are stamped 2026-11-10 04:50 to 04:53 UTC. So the change came after the first session's window had already closed, and no collection has yet run against the changed scopes. Tonight is the first.

## A. The mismatch

**Confirmed.** Three of the four pinned versions no longer match. Computed with the release's own `_scopes_hash` (`experiments/comparison.py:123-128`) on the scratch database, opened with the release's own read-only engine (`comparison.py:94-109`).

| Book | Version | Pinned in `refresh.json` | Now | Result | Passing evaluations now, newest first |
|---|---|---|---|---|---|
| kronos-comparison-v2-short | 2 trend_continuation.short_swing | `97d559b2225d…b32ccd` | `720d2aa0a412…cfc892` | **mismatch** | 52, 48, 43, 32, 20 |
| kronos-comparison-v2-medium | 3 trend_continuation.medium_swing | `c2cb5cc69e0c…9782cd` | `a625f9f64704…5feaaa` | **mismatch** | 54, 50, 45 |
| kronos-comparison-v2-medium | 5 relative_strength.medium_swing | `54401ece3ea4…58c651` | `5f1f4f5b69d4…21551a` | **mismatch** | 53, 49, 47, 44, 35, 23 |
| kronos-comparison-v2-medium | 13 high52_breakout.medium_swing | `6b31b9bd6275…a1807a` | `6b31b9bd6275…a1807a` | match | 51 |

- The short book pins version 2. The medium book pins versions 3, 5 and 13.
- **Why it changed.** The hash covers every passing evaluation's id, snapshot, config hash, spec hash, universe and sources (`research/approval_scope.py:35-42, 59-98`). A new passing evaluation adds an entry. The three backtest runs are not in the hash.
- The other pin, the spec digest (`comparison.py:152`, checked at `:538`), still matches for all four versions.
- The operating research config, as of the copy, still hashes to the registry's `config_sha256` `e1e70c53340b…` for both books. So the separate "Operating research config changed" check (`comparison.py:478-483`) is not in play.
- Full hashes are in `OUT/hash_check_scratch.json`.

Identity before importing worktree code: nine files that compute or feed the hash are the same git blob in the release and the worktree. `db/models/research.py` differs in one hunk, a comment on `StrategyHealth.action`. The model classes used are identical by syntax tree (`OUT/ast_identity.log`).

## B. What happens at collection

| Question | Answer | Code |
|---|---|---|
| When is the hash checked? | **Only when the collector meets a candidate.** Not at open, and not for a pinned version with no candidate that day | check `comparison.py:541-542`, inside the candidate loop `:531-585`; open checks only manifest and code hash `:272-288` |
| Which candidates reach the check? | Passed, long, plain equity, the book's horizon, created after the close, from a `massive` scan, symbol in the 25-symbol configured universe, and whose version is approved with a matching spec digest | query `:503-528`; version tests `:534-540` |
| Does one mismatch stop the whole book's session? | **Yes.** The error is raised before the session's batch is written, so nothing for that day is kept, including other versions' candidates. The other book is unaffected | raise `:542`; batch write `:595-601`; per-book handling collector `170-201` / `178-209` |
| Is the refused session recorded? | Not in the book. The collector's status file gets `blocked`, error category `ValueError` (the message text is not kept) and a 5-minute retry. Nothing is written to the operating database | collector `194-200` / `202-208`; read-only source `comparison.py:94-109`; Q11 |
| Can it be recovered? | Only the same UTC day. It retries every 5 minutes; if the hash is right again before 00:00 UTC the next retry captures the session. After midnight it is gone for good: the collector stops trying and the engine never backfills | collector `53-54` / `60-67`; `comparison.py:441, 503-527, 622, 651` |
| Does the book halt permanently? | **No.** Each session is a fresh attempt. A book with a stale pin keeps completing quiet sessions and refusing sessions on which the stale version signals | no latch in `poll` or `_advance` |

**That is worse for the study than a clean halt.** Which sessions enter the book would depend on the strategy's own signals. In practice:

- The short book could never hold a candidate. Its only version is version 2, and any version 2 candidate refuses the session.
- The medium book could hold version 13 only, on sessions where version 3 is silent. Version 5 never produces a passing candidate, so its stale pin never fires.
- Since 2026-09-25, version 2 had a qualifying passed candidate on 11 of 32 sessions and version 3 on the same 11, counting scans at any time of day (`OUT/base_rate.log`). Versions 5 and 13 had none.
- That understates the refusal rate for a book. Only 14 of the 32 sessions had an ok scan job between the close and UTC midnight, which is what the collector needs; the other 18 were lost regardless. On those 14, versions 2 and 3 each had an in-window passed candidate on 7 (09-25, 10-01, 10-08, 10-28, 11-02, 11-03, 11-04). So a generation-2 book would have refused about half of the sessions it could otherwise have collected (`OUT/base_rate_inwindow.log`).

**Has any collection been attempted since the change? No, and none could have been.**

- From 04:50 UTC until tonight's close the last closed session is 2026-11-09 while the UTC date is 2026-11-10. The deployed collector then reports `blocked` / `MissedUTCCollectionWindow` on every poll without calling the book engine (deployed `60-67`; the release version reports `waiting_for_postclose_window`, `53-54`).
- The first real attempt will be tonight, once a scan completes. With the catch-up ingest starting at 23:03 UTC, that is likely after 23:30 UTC, which leaves the collector little time before midnight. It may not finish, in which case session 2026-11-10 is missed for a reason unrelated to the hashes.
- The collector leaves no row in the operating database, by design (Q11: 0 job rows, no audit row).
- **It has no log.** The launchd job sends stdout and stderr to `/dev/null`. Its only record is its status file, which was not on my list of files to read. I did not open it.

**Has either book captured any session? No, as far as I can establish.**

- For session 2026-11-09 no scan job started between the close (21:00 UTC) and midnight. The first is job 7511 at 01:22:59 UTC the next day (Q12). Without a completed scan the collector never reports ready (collector `66-139` / `74-147`).
- The committed note says the same: "the missing Kronos session" (`W/docs/STUDY_OPERATIONS.md:10-16`).
- Not checked directly. A manual `scripts/kronos_comparison.py advance`, which skips the readiness rule (`:49-50`), cannot be ruled out from the database.

## C. Option A: roll back

### What would be deleted

| Table | Rows | Which |
|---|---|---|
| `strategy_promotion_evaluation` | 3 | ids 52, 53, 54 (versions 2, 5, 3) |
| `backtest_run` | 3 | ids 53, 54, 55 (versions 2, 5, 3), each linked to its evaluation in `params_json` |
| `backtest_metric` | 18 | ids 210 to 227, six per run |
| `backtest_trade` | 0 | none stored |
| `walkforward_window` | 0 | none stored |
| `audit_log` | 0 deleted, 1 added | the three `strategy.promote` rows 545 to 547 stay; one new row records the roll-back, following audit row 9 of 2026-09-08 |

Not touched: strategy and version statuses (already approved before and after; audit rows 545 to 547), sealed tests (evaluations 52 to 54 reuse rows 11, 14, 21) and dataset snapshots. Three lines in the JSONL audit file (`audit.py:22-36`) would keep naming evaluation ids that no longer exist. I did not open that file.

### Does anything block it?

| Check | Result |
|---|---|
| Triggers | None on these tables. The database has 12, all on execution, options and `paper_trade` tables (Q1) |
| Foreign keys | Nothing references an evaluation. Three tables reference a run with cascade (Q2). The app turns foreign keys on (release `db/session.py:53-56`); the `sqlite3` command line does not, so the script deletes children explicitly |
| Audit rule | None in the database |
| Application command | None exists. It is a manual SQL change to the operating database and needs the operator's explicit authorisation |
| Id reuse | The tables have no AUTOINCREMENT. The next evaluation would be numbered 52 again and the next run 53, which collides with audit rows 545 to 547 and with R3 documents that cite them |

### Does it restore the pins? Yes, exactly.

`OUT/option_A_rollback.sql` ran on the private copy in one transaction, with 9 pre-conditions and 4 post-conditions all true. A second run is refused by its own guard. After it (`OUT/hash_check_after_rollback.log`):

| Version | Hash after deletion | Pinned | Result |
|---|---|---|---|
| 2 | `97d559b2225d…` | `97d559b2225d…` | match |
| 3 | `c2cb5cc69e0c…` | `c2cb5cc69e0c…` | match |
| 5 | `54401ece3ea4…` | `54401ece3ea4…` | match |
| 13 | `6b31b9bd6275…` | `6b31b9bd6275…` | match |

### What versions 2, 3 and 5 then do at the scan

The scan reads only the newest run for a version and never falls back to an older good one (`research/persistence.py:215-231`). After the roll-back that is a forced run. Replayed with the real gate functions on the private copy (`OUT/gate_replay_after_rollback.log`):

| Version | Newest approval | Evidence run read | Evidence gate | Failure |
|---|---|---|---|---|
| 2 | 48 | 50 | **fail** | "OOS provenance mismatch (allow_mismatch=true; mismatched_inputs: config_hash, until; …)" |
| 3 | 50 | 52 | **fail** | same |
| 5 | 49 | 51 | **fail** | same, plus "OOS regime coverage: 1 regime(s) … < 2 required" |
| 13 | 51 | 49 | pass | none |

- Deciding code: evidence gate `research/scan.py:486-503`; provenance refusal `persistence.py:181-212, 272-273`; the candidate becomes NO_TRADE at `scan.py:530`.
- Auto-simulation and the Kronos collector both read passed candidates only (`comparison.py:511`).
- The scan groups do not change, so the collector's readiness rule is still met.
- For comparison, today's state: versions 2, 3 and 13 pass; version 5 fails on regime coverage alone (`OUT/gate_replay_scratch.log`).

### Could clean evidence be recorded afterwards without a new evaluation? No.

Replayed on the private copy with the two identity checks `record-oos-backtest` makes before it reads any data (`OUT/refusal_checks.log`). The release's command always demands the current scope (release `cli.py:3635, 3690`).

| Version | Evaluation tried | Result | Code |
|---|---|---|---|
| 2, 3, 5 | newest approval 48, 50, 49 (config `179f82f0…`, not the live `fe365720…`) | refused: "evaluation_id is not the latest approved metadata match for the intended config/scan scope" | `research/promotion.py:2085-2089` |
| 2, 3, 5 | newest live-config approval 43, 45, 47 (window from 2016-09-10, data from 2016-10-17) | refused: "evaluation input coverage does not attest the full canonical daily window" | `promotion.py:1921-1924` |

The only way out is a new passing evaluation, which changes the hash again. So option A is one-way for generation 2.

### What the two books would contain if rolled back

| Book | Contents |
|---|---|
| short | Nothing, for up to 252 sessions. Its only version cannot produce a passed candidate |
| medium | Version 13 only, and only its candidates on the 25 configured symbols. Version 13 has not yet produced a passed candidate (0 of 32 sessions) |

Outside the books, operating paper entries for versions 2 and 3 would stop. They had passed candidates on 11 of the last 32 sessions.

## D. Option B: a new generation

### The procedure, from `W/docs/STUDY_REFRESH.md` and `scripts/study_refresh.py` (same file in the release)

| Step | What it does | Code |
|---|---|---|
| `validate-parent` | Runs the parent's own pinned code to check its manifest. Read-only | `:91-159` |
| `stage` | Records a request in a new control folder. With `--accept-scope-change --scope-change-reason` it takes a metadata-only freeze to capture today's approved versions and scope hashes | `:225-316`; scope capture `:250-272` |
| `check` | Trial freeze in a temporary folder; reports `COMPATIBLE` or `WAITING_FOR_FREEZE_WINDOW` | `:423-470` |
| `start` | Freezes for real and publishes the study with its lineage file. Refuses if scope drifted since staging | `:449-453, 466-493` |
| `activate` | Replaces the one registry file by compare-and-swap on the generation number and moves the old generation to the archive list | `:575-677` |

**Which checkout, and why.**

- The refresh commands must run from the new release's own clean, detached checkout at the exact full SHA, with imports resolving there (`:72-82`, repeated at `:330`). The frozen study records the code hash of the checkout that freezes it (`comparison.py:77-91, 185`).
- The parent is validated by the parent's checkout, because a book refuses any code but its own (`comparison.py:286-287`).
- The collector must be given `--checkout` equal to the importing checkout (collector `307-308` / `315-316`). The collector script itself may live elsewhere; it is outside the code hash (`W/docs/KRONOS-COMPARISON-COLLECTOR.md:31-34`).
- The worker must stay on the commit it was running when the books were frozen. Another commit rewrites `spec_json.git_sha` on every scan (`research/persistence.py:94-96`) and the collector then silently skips every candidate (`comparison.py:538`).

**Preconditions `stage` enforces.**

- `--paper-only`, with execution disabled and the `paper_reference` adapter (`:85-88`).
- Destination folder does not exist and is disjoint from the parent (`:243-247, 306-307`).
- Parent model weights, tokenizer and implementation unchanged (`:136-154`).
- Every inherited setting identical; only versions and scopes may differ (`:260-266`).
- The parent checkout's commit differs from the new release (`:275-276`).
- The first observation is later than the parent's (`:277-279`).

**The first-observation rule.** The first observation must be a trading session strictly after the New York calendar date at staging, and again at publication (`:162-168`, applied at `:241, 437, 473`; docs `:59-72`). The native freeze also sets its first study day to the first session whose close is still ahead (`comparison.py:166-171`), and `start` requires the two to agree (`:454-470`). So `start` works only between a session's close (21:00 UTC) and New York midnight (05:00 UTC), for the next session (`OUT/refusal_checks.log`, timing section).

**What gets a new identity.** New control folders, new study names and folders, new books with fresh $10,000 accounts per version and arm (`comparison.py:253-260`), a new manifest hash, a new collector state folder (`:646-647`), a new generation number and registry hash. Inherited unchanged: config, cash, costs, thresholds, model, seed, 252 sessions.

**What happens to generation 2.** Its names and status path move to the registry's archive list (`:613-624`). Nothing is overwritten, deleted or copied (docs `:9-11, 77, 85-87`). A collector still pointed at generation 2 is refused: "Collector expected generation mismatch" (`study_registry.py:254-256`).

**How the collector finds the active generation.** It does not discover it. The launchd arguments name the registry file, the expected generation, the two study folders and the state folder. The collector checks all four against the registry and each study's checksums before polling (`study_registry.py:251-266`; collector `263-284` / `271-292`).

**Restarts.**

| Service | Needs a restart? |
|---|---|
| Worker and web app | No, if the registry stays at the same path. It is read on each request (release `kronos/collection_status.py:182-190, 215`) |
| Kronos collector launchd job | Yes. Its arguments must be edited and the job reloaded |
| funded-validation launchd job | Yes, if the registry generation changes. It carries `--expected-generation 2` |

### Three things in the committed tool block a third generation

| Blocker | Evidence | Consequence |
|---|---|---|
| Study names are hard-coded: `kronos-comparison-v2-short`, `-medium`, `funded-validation-v2` | `study_refresh.py:206-210` | A new generation would re-use generation 2's names |
| The registry refuses an active name that is also an archived name | `study_registry.py:172-178`. Replayed in memory on a generation-3 candidate built the way `activate` builds it: **"REFUSED: Archive and active identities must be distinct"**. With new names it is accepted | `activate` fails. The docs say so: "another rollover requires new native versioned identities" (docs `:88-89`) |
| Activation takes exactly three started studies from one release, and the forward study must have no heartbeat yet | `:586-588, 648-649`; registry `:126-127, 149-150` | **funded-validation-v2 cannot simply be carried over** |

The forward collector also refuses a heartbeat written under another generation (release `scripts/funded_forward.py:114-120`). That file is inside the forward study's code digest (release `research/prospective_funded.py:31-34`), so it cannot be edited without stopping funded-validation-v2.

**So is funded-validation-v2 touched? By the committed design, yes.** A generation is three fresh studies. There are two ways forward, both needing a reviewed tooling change first:

| Route | Tool change | funded-validation-v2 | Risk |
|---|---|---|---|
| B-all: roll all three | Names take a generation suffix. Nothing else | Archived; a new forward study starts. It has 1 captured session now, 2 after tonight | Lowest. Everything else is the designed, tested path |
| B-kronos: roll the two Kronos books, carry the forward study | Names, plus activation that carries an unchanged forward entry and rotates its old heartbeat aside under the registry lock | Evidence untouched. Its launchd job still needs `--expected-generation 3` and a reload | New logic in the cutover of a live study. More review |

- The tool files (`scripts/study_refresh.py`, `src/signalforge/study_registry.py`, `scripts/kronos_comparison_collect.py`) are outside both studies' code hashes (`comparison.py:77-91`; `prospective_funded.py:18-35`). A tooling-only commit on top of 21e87a3 leaves the frozen engine and the worker unchanged. Commit 3a202c5 is the precedent (`W/docs/STUDY_OPERATIONS.md:26-31`).
- Parents for generation 3 would be the generation-2 studies, validated by the 21e87a3 checkout. `stage` then needs a release commit other than 21e87a3 (`:275-276`), which the tooling commit provides.

**Which base for the tooling commit.** Main's first-parent history after 21e87a3 is: 94a6c4c (merge of PR #69, which brings in 3a202c5), then 1479b1c (merge of PR #68).

| Base | Hashed files changed against 21e87a3 | Kronos / forward code hash | Usable with the worker left on 21e87a3? |
|---|---|---|---|
| 3a202c5 or 94a6c4c (before PR #68) | none | unchanged: `ccec7a71fb1f…` / `fdbf60fb92ee…` (the registry's values) | Yes |
| current main, 1479b1c (contains PR #68) | 9: `scripts/funded_forward.py`, `data/feeds.py`, `db/models/research.py`, `db/session.py`, `research/approved_scope_scan.py`, `research/health_monitor.py`, `research/paper_probation.py`, `research/prospective_funded.py`, `research/scan_session_outcomes.py` | `1112d3d61028…` / `39d35602acd5…` (computed on the worktree, whose `src/` equals main; `OUT/main_tree_code_hashes.log`) | No |

- **Side-branch route (roll now).** Create a release branch at 94a6c4c (or 3a202c5), open the tooling pull request **against that branch**, not against main, and release its merge commit. CI runs on every pull request whatever its target (`.github/workflows/ci.yml:6-9`). The same change still has to reach main afterwards by a second pull request; the tool files are identical between 3a202c5 and main today, so it should apply cleanly. The worker stays on 21e87a3. B-all and B-kronos are both possible. The check in step B2 passes only on this route.
- **Main-based route (combine with PR #68).** The tooling change is merged to main as usual. The new checkout then has new code hashes, so: step B2's check does not apply (see the alternative check there); all three studies must roll, because `scripts/funded_forward.py` is inside the forward digest and changed, so B-kronos is impossible; both collector launchd jobs must be moved to the new checkout (interpreter, `PYTHONPATH`, `--checkout`, and the forward collector's script path); and **the worker must be deployed on the new release before the freeze**, with at least one approved-scope scan completed on it, so that the `spec_json.git_sha` values the freeze pins are the ones the worker will keep writing. That is the deployment `docs/WORKER_RELIABILITY_RELEASE.md` holds, and it stops the generation-2 Kronos books at once (their pinned spec digests no longer match). I did not rehearse this route.

**Routes the code allows that I do not recommend.**

- A native freeze with `scripts/kronos_comparison.py freeze`, collected without a registry. It needs no code change and leaves funded-validation-v2 alone. It also skips the lineage record, the strict-future-date rule, the inherited-settings check and the generation fence, and the dashboard would not show the new books.
- Staging again from the v1 parents into a second registry file. It passes the name check only because the archive there would list v1 names. It would create a second study called `kronos-comparison-v2-short`, need a new forward study too, and need the worker and web app restarted on a new registry path.

### Version 5, and the order of steps

- A freeze pins every approved version of the horizon (`comparison.py:151-160`). Frozen today, the medium book pins 3, 5 and 13 again.
- A pinned version 5 can never contribute. But the collector reports the book ready only when the night's scan covers every pinned version (collector `131` / `139`). Replayed on today's scan groups: with version 5 scanned the medium book is covered; without it, not (`OUT/gate_replay_scratch.log`).
- So with version 5 pinned, the medium book depends every night on the separate 24-symbol medium scan, and retiring version 5 at any later date stops collection for versions 3 and 13 too.
- **Order: decide version 5 first. If it is to be retired, retire, then stage, then start.** The new medium book then pins 3 and 13 and needs only the 150-symbol scan.
- Retiring is the dashboard's downgrade action (release `app/routers/dashboard.py:298-329`). It cannot be undone without a new passing evaluation.
- Retiring also stops the generation-2 medium book at once, by the same readiness rule. That is acceptable only because generation 2 is being replaced.
- funded-validation does not read strategy status, approvals or scans (0 matches in its five source files at the release).

**Hashes a generation staged today would pin**, if no further evaluation is recorded first:

| Version | Scope hash |
|---|---|
| 2 | `720d2aa0a412b3b1e4aee658c6aa677b85b23ecba3241000ead06fe231cfc892` |
| 3 | `a625f9f647041f885bda5165996f2ec3feba22e1ff489458daf31125f45feaaa` |
| 13 | `6b31b9bd62755de1f5354f9a96c7a8f9b596ece447d171dbd3320415d0a1807a` |
| 5, only if still approved | `5f1f4f5b69d44bc8f9ef102e29f122104165785f6a93a41bf5d9dfb62721551a` |

**Standing rules for the life of any new generation.** Each of these stops or empties a book:

- a new passing evaluation of a pinned version (`comparison.py:541-542`);
- any research-config change (`:478-483`);
- a worker on another commit (`:538`);
- retiring a pinned version (collector `131` / `139`);
- any change to model files (`:455-459`).

## E. Timing

All times UTC. Pacific is 8 hours behind.

| | Option A | Option B |
|---|---|---|
| Capture today's session, 2026-11-10 | The rule is: commit the roll-back before the end-of-day job starts writing (22:30 on a normal day), and in any case before the scan step. **For today that moment has passed:** the catch-up chain has been writing since 23:03 | **Not possible.** A first observation must be after the New York date of staging |
| Capture the next session, 2026-11-11 | Before 22:30 on 11-11 | By the date rule: `start` both books **between 21:00 today and 05:00 tomorrow**, then activate and switch the collector before the 11-11 scan. That needs the tooling change reviewed and a release checkout ready within hours, so treat 11-11 as out of reach |
| Capture 2026-11-12 | Before 22:30 on 11-12 | `start` the studies between 21:00 on 11-11 and 05:00 on 11-12. Feasible on the side-branch route only. The main-based route also needs the worker deployed and scanned on the new release first, so expect later |
| Each further day of delay | A book loses a session only if its stale version signals that day: 7 of the 14 collectable sessions since 2026-09-25, the same for both (11 of 32 counting scans at any hour). Other collectable sessions complete anyway | One session. The 252-session window starts a day later. Nothing already collected is lost, because generation 2 holds no captured session |
| Paper trading | Entries for versions 2 and 3 stop from the moment of the roll-back | Unaffected by any delay |

- A roll-back between the scan and midnight would still be picked up by a 5-minute retry. Avoid it: tonight's scan would by then have passed candidates on evidence the roll-back deletes.
- If funded-validation is restarted (B-all), it loses its sessions from 2026-11-09 up to the restart.
- **For any option the Mac must be awake with the lid open from 22:30 until the collector finishes, and it should not sleep earlier on a trading day.** After today's sleep the worker reportedly fired no job on wake until it was restarted (cause unverified; after the two earlier gaps jobs resumed on their own). If it does sleep, check after waking that jobs are running again. No worker job ran during all three gaps in the timeline, and the idle-sleep guard does not prevent lid-closed sleep (`W/docs/STUDY_OPERATIONS.md:13-15, 21-23`). Nothing else may hold the Kronos runtime lock in that hour (collector `146-159` / `154-167`).

## F. Step lists

### Tonight, under the recommendation (all NOT RUN)

1. **NOT RUN.** Decide: no roll-back. Leave evaluations 52 to 54 and runs 53 to 55 in place.
   Check: nothing to check.
2. **NOT RUN.** Leave both collectors and the worker as they are (the worker was already restarted at 23:01 UTC by another session, on the same release; do not restart it again). Keep the Mac awake, lid open, until 00:00 UTC tonight. From now on do not let it sleep on a trading day; at the least it must be awake from 22:30 to 00:00 UTC, and after any wake confirm with the query below that jobs have resumed.
   Check once the catch-up has finished (tonight probably after 23:35 UTC), read-only. Tonight the scan job may be named `catchup_approved_scope_scan`:
   ```sh
   sqlite3 -readonly /Users/louisbrailey/Projects/signal-forge/data/signalforge.sqlite "SELECT id,name,status,started_at,finished_at FROM job_run WHERE name IN ('daily_eod_update','catch_up','approved_scope_scan','catchup_approved_scope_scan') ORDER BY id DESC LIMIT 6;"
   ```
3. **NOT RUN.** Expect on `/kronos` one of three states for each generation-2 book: `complete`; `blocked` with category `ValueError` (versions 2 or 3 signalled, so the mismatch fired as coded); or, after 00:00 UTC, `blocked` with category `MissedUTCCollectionWindow` (the late catch-up left too little time). None is a new fault.
   Check: the collector's own status file (the documented way, `W/docs/KRONOS-COMPARISON-COLLECTOR.md:61`).

### Option B (all NOT RUN)

1. **NOT RUN.** Operator decisions: version 5; B-all or B-kronos; side-branch route (worker stays on 21e87a3) or main-based route (deploy PR #68, which forces B-all).
   Check: decisions written down before any code is touched.
2. **NOT RUN.** Tooling change by pull request and CI. **Side-branch route: the pull request targets a release branch created at 94a6c4c (or 3a202c5), not main**, and the release is that branch's merge commit; a commit merged through current main contains PR #68 and fails the check below. Minimum change: `study_name` takes a generation suffix (`scripts/study_refresh.py:206-210`), and the printed `--expected-generation` hint at `:533` stops being a fixed `2`. (The `"version": 2` at `:282` is the request-format version, not a generation; leave it.) For B-kronos also the carry logic in `activate` (`:586-588, 648-649`). Tests: `tests/experiments/test_study_refresh.py`, `tests/experiments/test_study_registry.py`.
   Check, side-branch route: the diff against 21e87a3 touches no file in either code hash, and the Kronos code hash computed in the new checkout equals the registry's `code_digest` `ccec7a71fb1f…`:
   ```sh
   git diff --name-only 21e87a33c77c1b63fcef99f4d52026b77c62b359 <NEW_SHA> -- src/signalforge/paper src/signalforge/config src/signalforge/experiments src/signalforge/kronos src/signalforge/data src/signalforge/db src/signalforge/research src/signalforge/risk src/signalforge/backtest src/signalforge/domain.py src/signalforge/settings_store.py uv.lock pyproject.toml scripts/kronos_comparison.py scripts/funded_forward.py scripts/action_replay_report.py docs/KRONOS-COMPARISON-PLAN.md
   ```
   Expect no output. Against current main this command prints the 9 files listed in section D; that is the expected failure if the wrong base was used.
   Check, main-based route instead: the command prints exactly the files PR #68 changed and nothing from the tooling change; the worker has been deployed on `<NEW_SHA>` and has completed an approved-scope scan there before step 5; B-kronos is not attempted.
3. **NOT RUN.** Create the new release checkout: separate, detached, clean, at the full SHA (`W/docs/RELEASE_DEPLOYMENT.md:9-27`).
   Check: `git -C <checkout> status --porcelain` prints nothing and `git -C <checkout> rev-parse --abbrev-ref HEAD` prints `HEAD`.
4. **NOT RUN.** If version 5 is to be retired: dashboard, Strategies page, set `relative_strength.medium_swing` to experimental. This stops the generation-2 medium book.
   Check, read-only:
   ```sh
   sqlite3 -readonly /Users/louisbrailey/Projects/signal-forge/data/signalforge.sqlite "SELECT sv.id,s.name,s.status,sv.status FROM strategy_version sv JOIN strategy s ON s.id=sv.strategy_id WHERE s.status='PAPER_APPROVED' OR sv.id=5;"
   ```
   Expect versions 2, 3 and 13 approved and version 5 experimental.
5. **NOT RUN.** Validate parents and stage. Any time on the New York date before the first observation. The naming argument is whatever step 2 defines.
   ```sh
   set -e
   RELEASE_SHA='<full SHA of the new release>'
   STUDY_RELEASE=/Users/louisbrailey/Projects/signal-forge-releases/$RELEASE_SHA
   G2_RELEASE=/Users/louisbrailey/Projects/signal-forge-releases/21e87a33c77c1b63fcef99f4d52026b77c62b359
   G2=/Users/louisbrailey/Projects/signal-forge/data/study-refresh-v2
   G3=/Users/louisbrailey/Projects/signal-forge/data/study-refresh-v3
   STUDY_ENV=/Users/louisbrailey/Projects/signal-forge/.env
   ACTIVE_REGISTRY=$G2/active.json
   OBS='<next session after the New York date on which you stage and start>'
   cd "$STUDY_RELEASE"
   for H in short medium; do
     .venv/bin/python scripts/study_refresh.py validate-parent --kind kronos \
       --parent "$G2/$H/kronos-comparison-v2-$H" --parent-checkout "$G2_RELEASE" \
       --paper-only --env-file "$STUDY_ENV"
     .venv/bin/python scripts/study_refresh.py stage --kind kronos \
       --parent "$G2/$H/kronos-comparison-v2-$H" --parent-checkout "$G2_RELEASE" \
       --checkout "$STUDY_RELEASE" --release "$RELEASE_SHA" --destination "$G3/$H" \
       --first-observation "$OBS" --paper-only --env-file "$STUDY_ENV" \
       --accept-scope-change \
       --scope-change-reason 'Re-pin approval scopes after evaluations 52-54 of 2026-11-10; inherited controls unchanged'
   done
   ```
   For B-all, also stage the forward study with `--kind forward --first-entry <session after OBS>`, as in docs `:172-176`.
   Check: each prints `PARENT_METADATA_VALID` then `STAGED_NOT_STARTED`. Open each new `refresh.json`: `scope_change.new.approval_scopes` must equal the table in section D, and the medium book must list the versions you intend.
6. **NOT RUN.** After the close (21:00 UTC) and before New York midnight (05:00 UTC): check, then start, each study. For B-all the list is `short medium forward` (docs `:177`), because step 7 needs three started studies; for B-kronos it is `short medium` and the forward entry is carried by the changed tool.
   ```sh
   for STUDY in short medium forward; do   # B-kronos: short medium
     .venv/bin/python scripts/study_refresh.py check "$G3/$STUDY" --paper-only --env-file "$STUDY_ENV"
     .venv/bin/python scripts/study_refresh.py start "$G3/$STUDY" --paper-only --env-file "$STUDY_ENV"
   done
   ```
   Check: `COMPATIBLE` then `STARTED_NEW_PAPER_STUDY`. `WAITING_FOR_FREEZE_WINDOW` means it is before the close; wait, do not force. Publication is per study, not across all of them (docs `:183-184`).
7. **NOT RUN.** Activate once, generation 2 to 3.
   ```sh
   .venv/bin/python scripts/study_refresh.py activate --paper-only --env-file "$STUDY_ENV" \
     --registry "$ACTIVE_REGISTRY" --generation 3 --expected-generation 2 \
     --study "$G3/short" --study "$G3/medium" --study "$G3/forward" \
     --state-dir "$G3/collector-state-g3"
   ```
   `$G3/forward` is the B-all form: `activate` reads `<control>/<study name>/plan.json` for every `--study` and requires exactly three (`:584-588`). For B-kronos the third argument is whatever the changed tool defines for a carried forward study.
   Check: `ACTIVE_GENERATION_PUBLISHED`, generation 3. `active.json` shows generation 3 with generation 2 in `archive`.
8. **NOT RUN.** Point the Kronos collector's launchd job at the new study folders, the new state folder and `--expected-generation 3`, then reload it (`W/docs/KRONOS-COMPARISON-COLLECTOR.md:55-64`). Then edit and reload the funded-validation job (`com.signalforge.funded-validation`), whose arguments today are: the 21e87a3 interpreter, the 21e87a3 `scripts/funded_forward.py`, `collect`, the study folder `…/study-refresh-v2/forward/funded-validation-v2`, `--env-file`, `--registry …/study-refresh-v2/active.json`, `--expected-generation 2`:

   | Route | Study folder argument | `--expected-generation` | Interpreter and script path |
   |---|---|---|---|
   | B-kronos (side branch only) | unchanged | 3 | unchanged |
   | B-all, side branch | the new forward study folder, `$G3/forward/<new forward study name>` | 3 | may stay on 21e87a3, since the forward digest is the same in both checkouts; moving both to the new checkout is equally valid. Not rehearsed; the `--check-only` run below decides |
   | B-all, main-based | the new forward study folder | 3 | must move to the new checkout (the forward digest changed); likewise the Kronos job's interpreter, `PYTHONPATH` and `--checkout` |

   The registry path stays the same on every route. Do not restart the worker on another commit (on the main-based route it was already deployed before step 5).
   Check: run each collector once in the foreground with `--check-only` (docs `:198-204`). Kronos reports a waiting status for both new books, not `blocked`. Forward reports waiting, ready or already collected.
9. **NOT RUN.** On the first observation night, watch each new book go from waiting to `ready` to `complete` before 00:00 UTC.
   Check: `/kronos` shows generation 3 and a completed batch for the day. A fresh heartbeat alone is not proof (`W/docs/STUDY_OPERATIONS.md:33-35`).

### Option A, not recommended (all NOT RUN)

1. **NOT RUN.** Operator authorises deleting evaluations 52 to 54 and runs 53 to 55 from the operating database, and accepts that versions 2 and 3 stop passing the scan. Do it on a trading day before 22:30 UTC, with no end-of-day or catch-up job running. Not tonight: the catch-up chain is already writing.
   Check: authorisation is explicit and written.
2. **NOT RUN.** Confirm nothing newer was recorded since the 08:46 UTC copy.
   ```sh
   sqlite3 -readonly /Users/louisbrailey/Projects/signal-forge/data/signalforge.sqlite "SELECT (SELECT max(id) FROM strategy_promotion_evaluation),(SELECT max(id) FROM backtest_run),(SELECT count(*) FROM backtest_metric WHERE run_id IN (53,54,55)),(SELECT max(id) FROM audit_log);"
   ```
   Check: `54|55|18|` and an audit id of 547 or higher. Any other evaluation or run number: stop.
3. **NOT RUN.** Online backup. Never a file copy of a live WAL database (docs `:126-128`).
   ```sh
   sqlite3 -readonly /Users/louisbrailey/Projects/signal-forge/data/signalforge.sqlite ".backup '<BACKUP_FOLDER>/signalforge_before_rollback_2026-11-10.sqlite'"
   ```
   Check: the backup opens and returns the same four numbers as step 2.
4. **NOT RUN.** Run the tested script.
   ```sh
   sqlite3 /Users/louisbrailey/Projects/signal-forge/data/signalforge.sqlite < /private/tmp/claude-501/-Users-louisbrailey-Projects-signal-forge/ec635db8-8e7c-46dd-bc95-83c88a678e74/scratchpad/r3/out/roll-plan/option_A_rollback.sql
   ```
   Check: one line `30000`, then 13 lines each ending `|1`. "CHECK constraint failed" means a guard refused and nothing was changed.
5. **NOT RUN.** Recompute the hashes, read-only.
   ```sh
   S=/private/tmp/claude-501/-Users-louisbrailey-Projects-signal-forge/ec635db8-8e7c-46dd-bc95-83c88a678e74/scratchpad
   cd $S/r3 && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$S/r3wt/src:$S/r3wt/scripts MARKET_DATA_PROVIDER=massive SIGNALFORGE_DATA_DIR=$S/r3/db \
     /Users/louisbrailey/Projects/signal-forge/.venv/bin/python $S/r3/out/roll-plan/hash_check.py \
     /Users/louisbrailey/Projects/signal-forge/data/signalforge.sqlite operating-db-after-rollback $S/r3/out/roll-plan/hash_check_operating.json
   ```
   Check: four lines reading `scope MATCH`.
6. **NOT RUN.** After that day's scan, about 23:15 UTC. Replace the date with the day you run it:
   ```sh
   sqlite3 -readonly /Users/louisbrailey/Projects/signal-forge/data/signalforge.sqlite "SELECT c.strategy_version_id,c.quality_gate_status,count(*) FROM candidate c JOIN scan_run sr ON sr.id=c.scan_run_id WHERE sr.started_at>='<YYYY-MM-DD> 21:00:00' AND c.strategy_version_id IN (2,3,5,13) GROUP BY 1,2;"
   ```
   Check: no PASSED row for versions 2, 3 or 5. Both books show `complete` for that session before 00:00 UTC.
7. **NOT RUN.** Record the roll-back in the operations note.
   Check: the note names the audit row the script added.

There is no clean undo. Restoring the backup after the worker has written again would lose those writes, and re-creating the evaluations breaks the pins again.

## What I could not verify

- **The operating database as it is now.** Everything is from the 08:46 UTC copy, about 14 hours old when this plan was finished. The roll-back script's guards stop it if anything newer exists.
- **How tonight ends.** I did not wait for the catch-up chain. Whether its scan completes, and whether the collector then finishes before 00:00 UTC, is unknown.
- **Why no worker job ran in the three gaps.** The operations note attributes the first to a closed lid. The other two are inferred from missing job rows and log lines only. For the third, another session's checkpoint says the Mac was suspended from 12:10 UTC and that the scheduler did not fire after waking until the worker was restarted at 23:01; I did not confirm that. After the first two gaps the same process resumed on its usual quarter-hour cadence (00:52:11, 08:37:11).
- **The main-based route.** Not rehearsed: worker deployment order, the first scan on the new release, and the collectors' moves to the new checkout are from reading code and the release note only.
- **The Kronos collector's status file and the books.** Not opened. "No session captured" and "no attempt since the change" rest on code, job times and the committed operations note.
- **Whether launchd has actually reloaded the collector with the 3a202c5 script.** The property list was edited at 04:41 UTC; I ran no `launchctl`.
- **That the generation-2 manifests pin exactly what `refresh.json` lists.** I read the request, not the manifest. `start` enforces that they agree (`study_refresh.py:449-453`).
- **The release folders.** Not opened: whether they are clean and detached.
- **How long Kronos inference takes** between the scan and midnight.
- **The `.env` file.** Not read. The config digest computed without it equals the registry's, which suggests it adds no research setting.
- **The tooling change.** No code was written or tested. The Option B commands follow the documented form; the naming argument does not exist yet.
- **The health monitor after a roll-back.** It also reads evidence runs; not examined.
- **How often version 13 will signal.** It has no passed candidate on record.

## Deviations and clarifications

1. No pre-registration applies. No scan, evaluation or backtest was run and no price was loaded.
2. The brief's time of the re-scope is Pacific; the rows are 2026-11-10 04:50 to 04:53 UTC.
3. The Kronos comparison collector has no log to tail. I read the last 60 lines of the funded-validation collector's stdout log (statuses only) and of the two worker logs (job and error lines only). That stdout log is `/Users/louisbrailey/Projects/signal-forge/data/funded-validation-v1/collector.out.log`, which sits inside a frozen study folder because the launchd job writes it there. Only the collector's status fields were read (status, through-date, book count, observed-session count); the collector prints no outcome data (`scripts/funded_forward.py:88-93` at the release) and no book or collection file was opened.
4. Scripts were written to `OUT`, not `scripts/r4/`, because this task may write nowhere else.
5. The private copy is an APFS clone of the scratch database inside `OUT`. The roll-back SQL ran there and nowhere else. The scratch database's SHA-256 was `49b27252617e…f16c97` before and after.
6. Gate, identity, registry and date functions were replayed read-only on recorded rows or in memory. `validate_registry` was called without a registry path, so no file was touched.
7. Six launchd property lists were read. Environment values were printed only for path-like keys.
8. One early command ran with the study control folder as its working directory. It only read `active.json` and the two `refresh.json` files.
9. Read-only git commands were used in the worktree. Git state is unchanged.
10. The base rate (11 of 32) applies the collector's candidate filter without its time-of-day bound, and maps each scan to the last closed session at its start. With the bound applied (repair, `OUT/base_rate_inwindow.py`): 14 of the 32 sessions were collectable and versions 2 and 3 signalled in-window on 7 of them.
11. **This task overran its time and the round's 19:00 UTC computing deadline.** All database work finished by 12:12 UTC. The session was then suspended with the Mac until 23:03 UTC. After that I only wrote this file and read the last 60 lines of the worker log once more; no database was opened and nothing was computed while the catch-up chain ran.

### Repair after review (2026-11-10, about 23:15 to 23:20 UTC)

One review, verdict BLOCK, six findings. All six were confirmed and fixed in this file. No earlier number changed; numbers were added.

| # | Finding | Outcome |
|---|---|---|
| 1 (major) | Step B2 could not pass its own check: PR #68 is already on main | Confirmed with `git log --first-parent 21e87a3..origin/main` and the step's own diff command (9 files; none against 3a202c5 or 94a6c4c). Fixed: section D "Which base for the tooling commit", decision table, recommendation 3, section E, steps B1 and B2 |
| 2 | B-all step list never started the forward study; funded-validation job changes incomplete | Confirmed (docs `:177`; `study_refresh.py:584-588`; the job's arguments). Fixed in steps B6, B7, B8 |
| 3 | `:282` is the request-format version, not a generation | Confirmed. Fixed in step B2 |
| 4 | 11 of 32 understates the refusal rate | Confirmed by a new read-only count: 14 collectable sessions, 7 with an in-window signal. Fixed in the recommendation, sections B and E, deviation 10 |
| 5 | Wake time and worker restart | The other session's checkpoint was read and says what the review reports. Timeline, "Read this first", recommendation 4, section E and tonight's step 2 corrected; the "scheduler stuck" cause is marked unverified |
| 6 | Location of the forward collector log not disclosed | Confirmed from the job's `StandardOutPath`. Disclosed in deviation 3 |

What the repair ran, all after the round's 19:00 UTC cut-off: read-only git commands in the worktree; `base_rate_inwindow.py` on the scratch database (counts only, no price; its first run had a column-alias bug that zeroed the candidate filter and was re-run once after the one-line fix; both collectable-session counts were 14); `comparison.code_hash()` and `prospective_funded.code_digest()` on the worktree (file hashing only); one read of the other session's checkpoint note and of the funded-validation launchd property list. The scratch database's SHA-256 still begins `49b27252617e`. The operating database, the books, the release folders and `launchctl` were not touched. The plan as reviewed is kept at `OUT/review/PLAN_as_reviewed.md`.

## Files

| File in `OUT` | What |
|---|---|
| `PLAN.md` | this plan |
| `option_A_rollback.sql`, `option_A_private_copy_test.log` | the roll-back script and its run on the private copy |
| `hash_check.py`, `hash_check_scratch.log/.json`, `hash_check_after_rollback.log/.json` | question A and the recheck after deletion |
| `gate_replay.py`, `gate_replay_scratch.log/.json`, `gate_replay_after_rollback.log/.json` | the scan's evidence gate, before and after |
| `refusal_checks.py`, `refusal_checks.log/.json` | record refusals, registry refusal, timing windows |
| `base_rate.py`, `base_rate.log/.json` | sessions with passed candidates |
| `base_rate_inwindow.py`, `base_rate_inwindow.log/.json` | repair: the same count restricted to collectable sessions and in-window candidates |
| `main_tree_code_hashes.log` | repair: code hashes of the main-equivalent tree |
| `review/PLAN_as_reviewed.md` | this plan before the repair |
| `ast_identity.log` | function-level identity, release against worktree |
| `queries.sql` | the read-only SQL as run |
| `private_copy.sqlite` | the private copy, after the test deletion |

Research signal only — no order was placed.
