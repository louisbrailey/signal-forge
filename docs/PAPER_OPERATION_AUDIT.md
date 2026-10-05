# Paper operations audit — 2026-10-02

Evidence window: **22:04–22:09 UTC, October 2, 2026**. Checkout HEAD observed: `ad6ebb3faf5f3024ba5778bf919aa046c08647d6`. This is a read-only operational assessment, not activation or certification. The integration agent is concurrently changing this checkout; findings describe the inspected source and database during this window.

## Outcome

**Automatic simulated paper trading is enabled and has traded.** The main blockers are trustworthy risk enforcement and exit accounting, plus an ongoing data catch-up. Absence of a new trade is not proof of a broken system. Do not relax statistical, scope, freshness, or arming gates to generate activity.

All database reads used Python SQLite URI `mode=ro` (and `PRAGMA query_only=on` for the principal evidence queries), against `data/signalforge.sqlite`. No application jobs, provider calls, messages, broker calls, restarts, settings changes, or trade writes were initiated. Worker logs were filtered with URLs and credential-shaped fields redacted. Only this report was added to the project by this audit. No tests were run against the live application.

## Verified operational state

| Item | Observation |
|---|---|
| Automatic equity simulation | `auto_simulate_qualified_signals=true`; cap **2/day**, counted at UTC midnight, including manual accepts |
| Probation and notifications | `paper_probation_enabled=true`, `alerts_enabled=true`, candidate alert type true, alert cap 2; delivery was not tested |
| Risk overrides | per-trade risk **10%**, position concentration **10%**, portfolio exposure **60%**. **5% concentration is not the persisted setting.** |
| Main paper account | Initial cash $30,000; cash $24,323.35; two open positions |
| Decisions | 4 ACCEPTED, 8 REJECTED, 5 WATCH; latest acceptance October 1 at 19:59:10 UTC |
| Open positions | XLK 15 shares at $195.86; MSFT 5 shares at $513.18; both opened October 1 |
| Approved versions | StrategyVersion IDs 2 and 3, both `PAPER_APPROVED` |
| Execution adapter lane | Zero `armed_strategy` rows; no execution-enabled override. Separate from the functioning simulated equity ledger. No arming is needed to fix this ledger. |
| Kill state | No `data/kill_switch.json` and no kill-switch event rows observed; no state was changed |
| launchd | API PID 819 and worker PID 827 reported running; worker heartbeat started/last beat 21:58:36 UTC |

The launch agents use this checkout as working directory, with no data-directory or database environment override observed. The local `.env` database override is empty. No secret values or full environment were printed.

## Why there are no newer paper trades

Latest approved-scope scans were **198** (24-symbol short swing, October 1 22:00:38 UTC, 1 PASSED) and **199** (150-symbol medium swing, 22:00:39 UTC, 5 PASSED and 36 NO_TRADE candidate rows). The 36 failures all cite insufficient OOS regime coverage: one qualifying regime versus two required. This is a valid evidence refusal.

October 1's earlier approved scans 192/193 accepted XLK and MSFT (PaperTrade 7/8), exhausting the daily cap. Subsequent decisions 12–17 rejected XLK because it was already open and marked MU, ACN, SNPS, and MCK WATCH because the cap was reached. These are functioning controls, not unexplained inactivity. Watch decisions are immutable and not automatically retried the next day; a new scan supplies new candidates.

Worker logs show startup catch-up beginning at **21:58:36 October 2**, then ingestion of 151 symbols (configured 25 plus approved-scope additions). Recent completed comparable ingestions took about 30 minutes. At observation the latest completed ingestion remained #33 (October 1 22:00:32), and latest scans remained 202/201. PID existence plus an old heartbeat does not prove scan progress or a dead worker: source `scheduler.py:975` runs catch-up ingestion before subsequent scans. The ongoing provider success timestamp advanced to 22:05:23. This audit did not wait for completion or restart anything.

## Findings and recommended fixes

### P1 — Portfolio limits are not enforced against actual open exposure at acceptance

`research/scan.py:235` uses cash as equity, and `scan.py:450–459` calls `size_position` with an empty `OpenExposure()`. `paper/ledger.py:170–240` reconstructs shares from stored risk dollars, has a nominal fallback when sizing is absent, applies a fill adjustment, then debits cash without rechecking concentration, cash availability, sector/gross exposure, or aggregate open risk. The scanner's per-position sizing cap is real, but it is not a portfolio-aware acceptance gate. Several candidates in a batch can be sized against the same pre-fill balance.

The persisted 10% concentration setting also disagrees with the requested 5% objective. Current entry notionals are approximately $2,937.90 XLK and $2,565.90 MSFT: **9.79% and 8.55% of initial $30,000**, respectively. These percentages use initial capital for comparison, not a claim about current marked equity; each exceeds even the $1,500 initial-capital 5% budget. No 5% enforcement can be claimed.

**Fix:** establish the intended paper risk policy through the supported audited settings workflow in a separate authorized implementation; then use current marked equity and actual exposure, serialize/revalidate immediately before every acceptance, and size against adverse fill plus costs. Refuse absent/invalid sizing instead of silently falling back. Test sequential candidates, insufficient cash, one-share concentration boundary, and already-open sector/gross risk. Scope-hash changes require normal reevaluation; do not manufacture approval matches or overwrite immutable trades.

### P1 — Exit accounting uses price action from before entry and records impossible chronology

PaperPosition **1** opened September 25 at 22:02:35 UTC but closed at September 25 **00:00 UTC**; position **2** opened September 26 at 22:00:38 but closed September 26 **00:00 UTC**. Each recorded -$83.49. The September 25 MSFT bar is low 497.25, high 519.40, close 516.17; there is no September 26 MSFT bar in the inspected data.

`paper/ledger.py:310–339` takes the last available daily bar without requiring it to occur after entry, then `_exit_reason` uses its entire high/low and sets `closed_at` to midnight on the valuation date. For a post-close simulated entry, the entry-day low is not a subsequent executable stop. Reusing that bar on the next day compounds the problem. The records prove impossible timestamps; source inspection identifies the mechanism. Historical losses cannot be treated as validated forward paper outcomes.

**Fix:** define fill-time/session semantics, only evaluate eligible post-entry bars, process unseen sessions in order, and record a chronologically valid exit time with bar provenance. Preserve immutable trade evidence and apply explicit append-only corrections/quarantine to affected performance evidence. Test post-close entries, weekends, missed sessions, stop/target ambiguity and gaps.

### P1 — Stored PASSED signals can outlive their freshness authority

`paper/ledger.py:506` (`assert_auto_simulate_allowed`) checks the enabled flag, stored PASSED status, instrument type, current approved version and five-part scope. It does **not** compare candidate/scan age to acceptance time or reevaluate underlying-bar freshness. `accept_candidate` itself is reachable without this automatic guard. The scheduled path mitigates the problem by passing only the just-completed scan IDs (`scheduler.py:343`), but direct replay/manual calls are not protected by an equivalent freshness boundary.

**No observed stale acceptance is proven:** all four accepted trades were created immediately after their candidates and their snapshots say `fresh=true`. A frozen freshness flag is evidence of the original check, not continuing authority. The approved-scope data gate permits a newest bar up to **5 calendar days** old and requires **90%** of the universe on that newest date (`approved_scope_scan.py:75–77,595–605`); this is weaker than an exact last-completed-session requirement and does not establish that every selected candidate has a current bar.

**Fix:** enforce a documented horizon/session-specific age limit at acceptance, validate the selected instrument's source-qualified latest completed bar, reject future timestamps and stale replay, and store the acceptance-time evidence. Keep snapshot/approval matching intact. Add deterministic clock-controlled tests; do not relabel old candidates as fresh.

### P2 — Feed success, actual bar dates and source identity diverge

At the later coverage read, approved snapshot **3** had 24/24 `massive` symbols through October 2; snapshot **11** had 42/150 through October 2 and 108 through October 1. This is an in-flight catch-up snapshot, not proof of permanent feed failure. It would fail the 90% newest-session coverage criterion for snapshot 11 at that instant; the latest completed ingestion was also over 24 hours old by the audit window.

`massive_grouped` feed success was October 1 22:24:25, but its persisted daily bars ended **September 8** across 2,655 symbols. Universe scans **200/201** on snapshot 13 each stored 93 PASSED candidates despite that old source history. Those are **not** the approved-scope scan IDs handed to equity auto-simulation. Do not substitute these apparent opportunities for approved fresh candidates.

Additionally, `paper/ledger.py:319` calls `get_daily_bars` without a source, and `data/repository.py:51–72` sorts only by session date. Marking can mix sources or choose an ambiguous same-date row as coverage grows.

**Fix:** separate fetch-success age from actual market-session coverage, apply source/instrument-specific freshness to every candidate-producing lane, and bind marks to the accepted source with a deterministic fallback/refusal policy. Investigate grouped ingestion's old maximum date without weakening gates. Observe catch-up completion and then recompute coverage before deciding on corrective operations.

### P2 — Operational documentation and liveness labels need updating

`AGENTS.md` and `.toolkit.json` point to missing `docs/decisions/ADR-execution-layer.md`; the actual ADR pointer is `docs/decisions/0003-execution-layer.md`, referencing `docs/research/options_designs/D6_execution_adr.md`. `PAPER_PROBATION_ACTIVATION.md` starts with September 10 OFF/not-activated statements and later supersedes them with activation. Its narrative of complete daily data is stronger than the current 90%/five-day gate. Stale docs can lead to unnecessary activation attempts.

**Fix:** repair entry-point links and clearly separate current persisted posture, historical authorization, paper simulation, and optional armed execution. Surface in-progress ingestion, last completed scan, actual bar coverage and heartbeat separately. Do not call a running launchd process end-to-end healthy.

## 2026-10-04 addendum — missed sessions 09-28..09-30, worker fixes

**What happened.** The 09-28 21:30 UTC EOD update fired ~4 h late and was dropped (1 h misfire grace). A catch-up ingest then failed on provider network errors until 05:14 UTC 09-29; no job ran again until a manual restart at 19:28 UTC 10-01. **There is no approved-scope scan for those sessions, and there will not be one**: the sessions are recorded as explicitly unscanned, not back-filled. This is part of the gap behind "Why there are no newer paper trades" above and behind the P2 liveness finding ("do not call a running launchd process end-to-end healthy").

**What changed** (details and operator notes: `docs/RUNBOOK_ALWAYS_ON.md`, section "2026-10-04 — ingest deadline, multi-session catch-up, visible EOD gaps"):

1. **Ingest deadline.** The daily-bar ingest stops between symbols once the EOD-locked unit has run `EOD_INGEST_DEADLINE_MINUTES` (default 45). It records a resumable `stopped` ingestion run, releases the lock, fails the job with `deadline exceeded after N/M symbols …; resume on next catch-up`, and runs no scan on the half-fetched session.
2. **Multi-session catch-up.** Every completed session since the last scanned one (look-back `CATCH_UP_LOOKBACK_SESSIONS`, default 10) is resolved oldest first: bars ingested (one provider pass for all of them) and a `scan_skipped_missed_session` row written per session. Only the latest completed session runs the real scan.
3. **EOD gap check.** `/ops` and the health check flag a last completed session with no successful EOD job run `EOD_GAP_GRACE_MINUTES` (default 120) after its cutoff.

**Why past sessions are not scanned as-of.** `run_scan(as_of=…)` bounds the price read only. Approval state, OOS evidence, the earnings calendar, account equity and both freshness gates are read as of *now*, and the persisted scan/candidate rows carry no as-of marker, so a back-filled scan would be look-ahead evidence that every consumer would treat as live. That would deepen finding P1 above (stored PASSED signals outliving their freshness authority) rather than fix a gap. **No candidate from a missed past session exists, so none can be auto-simulated.**

**Paper-evidence consequence.** Forward paper statistics have no observations for the skipped sessions. Treat them as missing data, not as "no signal" days: a session with a `scan_skipped_missed_session` row says nothing about whether the strategy would have traded.

**Scope hashes.** The three new fields live on the process `Settings`, not `ResearchConfig`; `config_hash` and `full_config_hash` are unchanged (`tests/test_catch_up_multi_session.py`, `tests/unit/test_scope_hash.py`).

**Not addressed here:** P1 portfolio-limit enforcement, P1 exit chronology, the acceptance-time freshness limit, and source-qualified marks all remain open.

## Kronos, GitHub and verification boundaries

Kronos files and navigation appeared in the checkout during this audit, consistent with the parent integration assignment. This audit did not modify them, run inference, or certify their boundary tests. Kronos should remain a research comparison with explicit provenance and held-out/baseline evaluation; no model output should choose entries, sizes, approvals, or orders.

GitHub was not contacted and nothing was committed/pushed. The integration owner should review this report, implement the risk/freshness/exit fixes, run focused offline regressions and safety gates, and publish through its authorized GitHub workflow. This report verifies stored state and inspected code only, not CI, notification delivery, continuous uptime, predictive edge, or broker execution.
