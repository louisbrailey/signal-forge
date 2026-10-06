# OR-0c — pooled versus per-symbol reading of the gate 0.c / 0.d coverage floors

**Status: OPEN. Operator decision required. Nothing below decides it.**
Written 2026-10-06, before any `--confirm` evaluation of any options strategy (options
sealed-look ledger: 0 previous looks; next look index 1).

## What is undecided

D5 fixes the coverage floors at 0.90 (gate 0.c, cycle bracketing) and 0.80 (gate 0.d, bar
continuity). It states how they are read in two places that do not agree:

| Passage | Reading | Text |
|---|---|---|
| D5 §5.1 (line ~622) | **pooled** over the evaluated set | "≥ 90% of (underlying, monthly cycle) pairs in the window must bracket the structure" |
| D5 §2.2 (line ~146) | **per symbol** | "a symbol is dropped if its chain coverage summary … fails gate 0.c or 0.d at the thresholds fixed in §5" |

## The numbers (counts only; no performance was viewed)

Snapshot 17 (`options_idx3_massive_2023-09-04_2026-09-04_0ae681d590`, SPY/QQQ/IWM,
cycle run 44 = bulk run 17):

| Underlying | 0.c cycles bracketed | 0.d bar continuity |
|---|---|---|
| SPY | 32/34 = 0.941 | 0.86 |
| QQQ | 30/34 = 0.882 | 0.854 |
| IWM | 30/34 = 0.882 | 0.804 |
| **Pooled** | **92/102 = 0.902** | **0.828** |

Under the pooled reading the set passes both floors. Under the per-symbol reading QQQ and IWM
fail 0.c (0.882 < 0.90) and the eligible set is **SPY alone**.

## Why this is not for an agent to decide

- Both readings are present in the frozen pre-registration; choosing one after seeing which
  symbols pass is selection on the data.
- The pooled reading admits any subset whose pool clears, so a weak member can ride inside a
  strong one (the pool passes at 0.902 with two members at 0.882).
- The per-symbol reading is stricter and matches how the 21 Stage B stocks were dropped
  (each on its own summary), but it shrinks the first evaluation to one underlying.

## What the code does meanwhile (PR #10, PR #14)

- The pre-flight computes the pooled result **and** lists `members_below_floor`.
- `options snapshot` and `options evaluate-promotion --dry-run` proceed with a printed WARNING.
- `options evaluate-promotion --confirm` **refuses** while any member is below a floor on its own
  numbers, unless the operator passes `--accept-pooled-coverage OR-0c` AND
  `docs/research/DECISIONS_2026-09-12_wave3.md` contains a line beginning exactly
  `OR-0c: DECIDED pooled`. Neither exists today.
- No floor, threshold or universe has been changed, and snapshot 17 was built on coverage
  counts only.

## How the operator records a decision (either way)

1. Add one line to `docs/research/DECISIONS_2026-09-12_wave3.md` under the OR table:
   - `OR-0c: DECIDED pooled` — the set stays SPY/QQQ/IWM; `--confirm` additionally requires the
     explicit flag; or
   - `OR-0c: DECIDED per-symbol` — a new snapshot is built for SPY alone (new key); QQQ/IWM are
     recorded as dropped on coverage; the code's refusal then never triggers.
2. Date and sign the line; reference this memo.
3. Do not change the floors.

## Interaction with the zero-entry finding

Independently of OR-0c, the frozen strategy currently enters zero structures on snapshot 17
because the stored strike ladder (17 rungs, $7–13 apart) rarely contains an exact $8 wing.
Deciding OR-0c does not change that; it only determines which underlyings a later evaluation
may include once the data question is resolved by its own amendment.
