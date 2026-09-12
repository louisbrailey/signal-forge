# ADR — Execution layer (pointer)

- **Status:** accepted and IMPLEMENTED through increment W4c (2026-09-12). The execution
  layer exists, is default-disabled, and its cycle can submit orders once a strategy is
  armed — see "Increment W4c" at the foot of this file. **Nothing is armed. Nothing reaches
  real money:** the only registered adapter is `paper_reference`, a local, deterministic,
  network-free simulator, and `research.execution.enabled` ships False.
- **Deciders:** Louis Brailey (operator). Direction of 2026-09-11: Signal Forge is "no longer
  research use only"; end-to-end operational control granted.
- **Full text:** `docs/research/options_designs/D6_execution_adr.md` — this file is a short
  pointer, not a second copy. Where the two could ever disagree, D6 is the ADR.
- **Decision log it implements:** `docs/research/DECISIONS_2026-09-12_options_execution.md`
  (decision 1 records this supersession; decisions 2, 4, 9, 10 bound it).
- **Program context:** `docs/research/OPTIONS_EXECUTION_PROGRAM_MAP.md` §6, §6.8, §7.

## What is superseded

`docs/PORTFOLIO_RESEARCH_ROADMAP.md` "Non-negotiable boundaries" carried two bullets that this
ADR supersedes **in writing rather than by routing around them**:

> "**No brokerage, no order placement, no trade mirroring, anywhere.**"

> "**No brokerage/Webull/order-placement integration is in scope for any module, at any phase.**
> This roadmap does not create one and does not plan to."

They are replaced by a **narrower** boundary, not deleted: a brokerage surface may exist in
`signalforge.execution` and nowhere else. Every other module keeps the original prohibition,
and the prohibition is now enforced in **both** directions rather than one.

## What replaces it

1. A `signalforge.execution` package may submit orders to a broker's **paper/sandbox**
   endpoint only. It is disabled by default (`EXECUTION_DISABLED_BY_DEFAULT = True` plus an
   `execution_enabled` app setting defaulting False — two independent gates, neither
   sufficient alone), and it can submit nothing while no unexpired `armed_strategy` row
   exists.
2. Arming is a per-strategy-version, audited, hard-expiring operator ceremony. There is no
   `ARMED` strategy status; arming is layered **on top of** `PAPER_APPROVED`, never folded
   into the enum (D6 §12).
3. The kill switch **blocks opening and never blocks closing**. Open and protective-close
   intents are built by two different factories whose fail-closed directions are opposite: a
   check that cannot be evaluated refuses an open and blocks no close (D6 §5.2, §5.2b, §7).
4. **No LLM decides, shapes, ranks, sizes, times, or describes an order**, enforced
   structurally by import-linter S15a/S15b and the S14 amendment (D6 §17.2) — not by
   convention, and not by a direct-edge check: `allow_indirect_imports` is deliberately unset,
   so a two-hop chain is a violation too.
5. Credentials exist only as **env-var names or macOS Keychain item names**. The system never
   acquires, stores, rotates, or logs one (D6 §16).

## What remains absolutely prohibited

- Any real-money endpoint. This ADR covers `paper_reference` (local, no network) and one
  vendor **paper** endpoint. Live money is a separate operator decision and a separate ADR.
- Any order sourced from a manually accepted paper trade (D6 §5 precondition P6).
- Any structure with undefined max loss, any leg-by-leg multi-leg submission, any 0DTE, any
  naked short option.
- Any automatic liquidation, automatic reconciliation repair, or retry of a broker rejection.
- Any credential acquisition, storage, rotation, or logging by the system.

## Status of the work

| Step | State |
|---|---|
| I-E1 — contracts (S15b live, S14 amended, S15a staged) + safety tests T1–T13 | done |
| §18 documentation amendment (roadmap, methodology, capability matrix, ARCHITECTURE invariants) | done |
| §18 amendment of the shipped strings (`README.md`, `DISCLAIMER.md`, `src/signalforge/options/__init__.py`, `src/signalforge/cli.py` help text, `src/signalforge/__init__.py` docstring) | **outstanding — lands with I-E2**, because those promises are still literally true until the package exists. See the note below for exactly what holds the reminder |
| I-E2 and later | not started; no execution code exists |

**The deviation from §18, recorded rather than glossed.** §18 says "**one commit, all of these
files, or none of them**", and this was not that: five documents were amended and five shipped
strings were not. The reason is that the unamended five are still *literally true* while no
execution package exists, so amending them now would describe a capability the tree does not
have — but the §18 rule exists precisely because a half-amended repository contradicts itself,
and that is the state this leaves. It is acceptable only for as long as the reminder is
mechanical rather than a line in this table.

**What actually holds the reminder.** Safety test T9
(`tests/safety/test_s15_execution_boundary.py`) fails the moment `src/signalforge/execution`
exists while any unconditional no-order promise survives, and it was verified against a
throwaway stub package to report: `src/signalforge/__init__.py`, all four `cli.py` help
strings, `README.md`, `DISCLAIMER.md`, and two the ADR did not enumerate —
`data/adapters/massive_options.py` and `grid/live.py`. **One file in the row above is NOT
covered by T9:** `src/signalforge/options/__init__.py`. Its "no options execution path anywhere
in this package" is genuinely package-scoped and stays true once execution lives elsewhere; what
goes stale there is the separate claim that "0DTE alerting, **and spreads** are intentionally
absent", which decision 12 falsifies by making a short vertical spread the first structure. That
one is a prose fix I-E2 must make by hand.

The paper-first evidence discipline (`docs/research/STRATEGY_COMPLETION_MAP.md` §1 R1–R10) is
unchanged by this ADR. No promotion gate or threshold is weakened anywhere in it; every
addition is strictly more searching.

## Increment W4c — the OPEN lane is built (2026-09-12)

The cycle body described in §2 now has its opening half. Until W4c nothing in
`src/signalforge/` called `adapter.place()` at all; the cycle evaluated,
reconciled, swept and reported, and submission existed only in the drill
harness.

What landed:

* `execution/open_lane.py` — candidate selection (ACCEPTED + AUTOMATIC actor +
  armed version + today), `build_open_intent`, `may_open` per order, then the
  §6/§8 durable order: `SUBMITTING` committed BEFORE `place()`. One order per
  paper trade forever, via the attempt-counter-free `client_order_id`.
* `paper_reference`'s book is now DURABLE (`paper_reference_order`, migration
  `c1e5a9f37b24`). A fresh instance per cycle used to start flat and reconcile
  CLEAN because it had forgotten; it now holds what the last one filled.
* Drills V23-V30 in `scripts/execution_drills.py`.

The guards are unchanged and are what make this safe to have: nothing is armed
by default, `execution.enabled` ships False, the only registered adapter is a
network-free local simulator, and with no live arming the lane is absent rather
than inert.

**One finding worth reading before arming:** under
`PREREGISTRATION_execution_limits_v1` the binding per-order notional cap on the
$25,000 reference account is `min($1,000, 0.5% x equity)` = **$125**, so no
instrument priced above $125 can be opened under v1. See
`docs/PAPER_PROBATION_ACTIVATION.md` ("The OPEN lane") and drill V30.
