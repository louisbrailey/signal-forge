# Wave-3 decisions and status (2026-09-12)

Merged on `main`: W3-A (D5 Amendment 1 → `options_designs/D5a_amendment_1_reachable_credit_floor_and_fixed_R.md`,
O3 short vertical **v0.1.1**), W3-B (`research/options_evidence.py`, `research/options_sensitivity.py`,
`signalforge options evaluate-promotion --dry-run|--confirm [--grid]`), W3-D
(`docs/PREREGISTRATION_execution_limits_v1.md`, Phase V drills 23/23 PASS in
`docs/research/execution_drills/DRILLS_2026-09-12.md`, worktree-safe launchd test), and the
Stage A post-mortem fix (D1 Appendix P, P6: `as_of` alone; `expired=true&as_of` returns zero rows).
In flight: W3-C (options paper EOD chain, injected from the CLI so S16 holds), W4-A (arming
ceremony runnable: B1 enable/disable CLI, B2 limits writer, B3 adapter lookup, OMS position
attribution for reconciliation).

## Rulings taken by the orchestrator (research design, k = 0, before any options evaluation)

| # | Question | Ruling |
|---|---|---|
| R-1 | Cluster unit: D4 §6.3 item 12 `(underlying, expiry cycle)` vs D5 §6.3b F11 cycle-month pooled across underlyings | **Both bind.** Gate 8's CI uses the D4 unit (finer, ICC/deff disclosed); F11 stays a separate NO-SHIP rule (`f11_breached`). A version ships only if neither fails. Conservative by construction; no threshold moved. |
| R-2 | `--confirm` without `--grid` | A sealed look must not be spent on an automatic gate-5 failure: `--confirm` **requires** `--grid` (follow-up code change, W4). |
| R-3 | OQ-1 horizon | MEDIUM_SWING, per D5a §5 (holding period 14–34 days; POSITION's floor is 2.17× the longest hold). |
| R-4 | OQ-10 | Answered by P6: the vendor honours `as_of`; the credit floor is now a cost filter (D5a), disclosed at gate 8, not compensated. |
| R-5 | Options EOD chain placement | 18:30 ET, injected from `cli.py` (`run-scheduler`) like the execution cycle so `scheduler.py` never imports an options paper module (S16). Default OFF (`research.options.paper_eod_enabled=false`). |

## Operator items (money / risk — not taken here)

| # | Item | Why it is yours | Recommendation |
|---|---|---|---|
| OP-1 | Decision 4's **$250 per-structure max loss** makes every cost-viable short-vertical width impossible: at the cap-compliant $2.00 width the target-win outcome is negative in every Stage A cell; cost-viable widths imply max losses of **$254–$842** (D5a §2.3, F14). D4 §2.8a forbids raising the cap after a gate result, so this must be decided **before** the first evaluation. | It is a capital limit on the account that would eventually trade real money; paper and live must share one population (decision 13). | Raise per-structure max loss to **$900** and aggregate open max loss to **$3,600** for the $25,000 options paper account (3.6 % / 14.4 %); keep the $1,000 per-order notional and daily order cap. Then D5a gets a dated Amendment 2 with widths re-derived under the new cap, still at k = 0. If you keep $250, O3 is expected to be the null result and the program's next structure is O2 (covered call) or O1 with a bear-regime carve-out. |
| OP-2 | Broker + paper API keys (Alpaca assumed) | Credentials | — |
| OP-3 | Options approval level | Account permission | Level 2 assumed in every design |
| OP-4 | Gate 0.i aggregate leg: 14 structures × $201.60 = $2,822 vs the $1,000 aggregate cap → at most 4 concurrent structures under the current limits | Follows from OP-1 | Resolved by OP-1's aggregate figure |

## Stage A backfill status

Pass 1 (run #17) excluded all 102 units (`no_contracts_returned`) — cause P6, fixed in `5d37284`.
Pass 2 started 2026-09-12 09:56 UTC on a fresh bulk copy (`data/io2_bulk.sqlite`), bounded to
590 min; first cycles committed (contracts and bars growing). Merge into the live DB only via
`signalforge options merge --from data/io2_bulk.sqlite` after `--dry-run`, with the worker stopped
(runbook §7). No options evaluation runs until OP-1 is decided and D5a is re-derived if needed.

## Addendum (2026-09-12, later): OP-1 now gates the whole options program

- **O3 short vertical v0.1.1** (D5a): expected null under the $250 per-structure cap (F14); viable widths need ≈ $254–$842.
- **O2 covered call** (D7 DRAFT, `options_designs/D7_o2_covered_call_preregistration_DRAFT.md`): gates 0.5 and 0.i are jointly unsatisfiable under any cap below ≈ $3,428 (Stage A) / $1,061 (IWM only), and 100 shares of SPY or QQQ exceed the $25,000 account outright; the $5,000 collateral cap admits zero structures on all three underlyings. Not a fallback.
- **O1 cash-secured put**: excluded by decision 12 (gate 6 / collateral wall).

Consequence: no defined-risk options structure can pass the ladder on this account under decision 4's
limits as they stand. The operator's choices are (a) OP-1 as recommended (per-structure ≈ $900,
aggregate ≈ $3,600) which makes O3 evaluable, (b) a larger options paper account and collateral cap,
which would additionally open O2 on IWM, or (c) keep the limits and accept that the options program's
pre-registered expectation is the null result. Nothing in the code chooses among these.

Execution layer status: the arming ceremony is runnable end-to-end on `paper_reference` (W4-A: enable/
disable, limits from the pre-registration document, adapter lookup, OMS position attribution; W4-B:
per-cycle adapter with account-scope refusal). The cycle's OPEN LANE (intent → OMS → adapter.place) is
being built as its own increment (W4-C) under the orchestrator's decision recorded here: it is the
ADR's designed body, default-disabled, unreachable unless a strategy is armed by the operator's ceremony.
