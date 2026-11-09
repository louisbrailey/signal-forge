# OOS evidence scope binding and explicit evaluation identity

This is the revised full-binding design acknowledged by Dirac and implemented
in the scope commit following the independent daily calendar commits. It adds
no parameter, threshold, numeric gate, price/replay or promotion-status change.
All checks use ordinary metadata; there is no provider call or new sealed look.

## Actual latest candidate evidence

The selector `latest_oos_metric` is unchanged. Candidate quality calls the pure
SELECT helper:

    persistence.oos_scope_failures(session, metric, spec, *, config_hash,
                                   dataset_snapshot_id, source, symbols)

`run_scan` forwards its actual captured dataset ID, source, universe and current
config through `_build_draft`. The actual latest metric must bind its saved
purpose, dataset ID/key, source, universe, executable spec hash and run config
hash to that context, and link a PASSED evaluation on the same version and scope.
Missing/malformed identity is ineligible. All five reproduction flags must be
literal True; forced, non-reproducing and malformed optional override flags fail.
Absent measured-data provenance remains unknown; contradictory measured sources
fail. No data-kind claim is inferred from a matching identity.

Universe membership is compared as sets, with normalized symbol case. The saved
record must separately preserve the linked evaluation's bootstrap/input order.
The helper disables autoflush and never changes a row or chooses another metric.
Latest evidence with the wrong scope produces NO_TRADE even when an older row
matches. Existing numeric, regime, status, health and risk gates remain in force.
The helper does not add a current strategy-status requirement to old evidence;
linked PASSED approval is its approval condition.

The strategy inventory checks that same latest metric against the newest
current-config approved metadata scope and displays ambiguous scope warnings
while retaining saved numbers. This inventory scope is descriptive: each actual
scan independently checks its own captured context. Unknown legacy scope is not
reconstructed or called clean. Historical 179f82 config evidence cannot globally
unlock current fe365 scans or another dataset with the same config hash.

## Ordinary recorder and current writer

`record_development_oos_backtest` adds optional keyword-only
`evaluation_id: int | None = None` and `require_current_scope: bool = False`.
None preserves the existing historical selector: newest passing evaluation on
the version/snapshot, otherwise newest evaluation. Historical API research still
has no automatic claim to current-scan eligibility.

An explicit ID is validated BEFORE any bars/backtest access: positive integer,
exact strategy version and snapshot, current executable hash, PASSED evaluation,
current PAPER_APPROVED Strategy/StrategyVersion, matching config/source/universe,
exact evaluation window and canonical daily cutoff. It must be the latest
matching approved metadata ordered by evaluated_at then ID. There is no ranking
by returns or retry of another evaluation after observing an outcome. Matching
may legitimately select an older config-specific scope while a newer approval
belongs to another config.

The ordinary CLI adds `--evaluation-id INTEGER` and always sets
`require_current_scope=True` for BOTH computation and persistence. The optional
ID does not silently change its default selector. Actual current effective
configuration is independently read from the DB overlay and base settings. The
short writer repeats that equality, runtime executable hash, current approved
status and deterministic selected approved scope inside its existing writing
transaction, along with the raw calendar-boundary and required-session checks.
An intervening config/approval/status/spec or lock change refuses persistence.
Neither mismatch nor duplicate override can bypass those checks. Historical
config remains ordinary research only; no production setting is restored.

Only synthetic fixtures whose purpose is matching candidate scope receive
matching test metadata. Legacy-unknown and intentional mismatch cases stay
unknown/mismatched. Independent adversarial full-scope tests are owned by Gauss
in `tests/research/test_oos_scope_binding.py`; this patch does not edit that file.
