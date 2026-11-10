# Daily EOD ordinary-record calendar policy

Review base:6bb9fbe462dfa73dd3129c1740c6a7d391aa5d36. This is the bounded
DAILY-EOD-XNYS-1 source correction for review, not approval to compute or persist
operating research results. No live backtest, provider or database writer was run.

## Exact calendar contract

The caller must provide an actual XNYS session date. The last XNYS session
strictly before the selected evaluation's linked locked sealed boundary MUST
equal the last XNYS session strictly before the earliest applicable locked
boundary. Both must equal caller_until. No caller date is silently normalized.
The absolute refusal until>=ANY applicable boundary is retained in calculation
and persistence. A mismatch cannot be waived by allow_mismatch or allow_duplicate.

For linked Monday2025-09-08 and earliest Sunday2025-09-07, both final sessions
are Friday2025-09-05. Only an explicit September5 request is accepted; September6
or7 are refused, even though they are weekends. For linked Monday and earliest
Friday, linked's final Friday differs from earliest's final Thursday: abort,
rather than delete a trading session from the evaluated development window.
Holidays follow the same pinned XNYS calendar used elsewhere in the repository.

This policy is ONLY for daily EOD. Intraday is rejected before boundary/data
work; it needs its own explicit RTH/bar-size/timestamp protocol. No assumptions
about hourly FX/crypto or Kronos/forward private engines are made here.

## Metadata and coverage assumptions

Before any OHLCV or backtest query, the linked sealed row must exist, belong to
the exact evaluation strategy-version/snapshot, and carry a valid date range.
Only locked IDs and boundary dates are selected; sealed result columns and
sealed price bars are never queried by these checks. Conflicting boundaries,
non-session/noncanonical callers, missing/wrong linked metadata and unsupported
intraday requests fail before any market data or computation.

The evaluation must retain input coverage from its first XNYS session through
the canonical final session. Its ordered universe, input source set, exact
calendar window start and session coverage must equal the requested scope.
SHA256 scope identities and the XNYS session-grid hash are appended to NEW
ordinary-record provenance. These are hashes of retained metadata, NOT original
historical price-content hashes; missing original price hashes remain unknown.
This correction does not certify that mutable historical prices never changed.

After the metadata checks, every required symbol and the regime proxy must have
a bar from the requested source on the exact canonical cutoff. Missing required
coverage refuses before computation: no last-observed-row lookup, backward cutoff
or shorter-window fallback. This query is exactly session_date=cutoff and lies
strictly before both locked boundaries. The computed input coverage/source/count
must also match the evaluation's recorded metadata before a result can be recorded.
Existing continuity/promotion gates remain responsible for the other aspects of
dataset quality; no numeric threshold is relaxed here.

## Independent writer validation

persist_development_oos_record independently re-reads the linked/applicable
boundary metadata and recomputes the same calendar policy. It also repeats cutoff
coverage validation. A new earlier trading lock is refused. Even an intervening
non-trading lock that leaves the final session unchanged requires recomputation
if the recorded raw-boundary provenance changed. Lost coverage, missing metadata,
intraday or noncanonical dates cannot be overridden. No writer is invoked by the
new failure-path tests; their computation and result writer are mocked.

New provenance includes policy/calendar/frequency, linked lock ID and raw dates,
earliest raw boundary and lock IDs, expected session cutoff, evaluation coverage,
matching requested/evaluation scope hashes and session-grid hash. Old stored
metrics, mismatch flags, provenance and statuses are not changed or migrated.
An authorized exploratory config mismatch remains explicitly marked under the
existing override policy and still fails the separate forced-evidence guard.

## Scope of this patch

The backtest engine, numeric thresholds, strategy parameters, cost assumptions,
promotion/status transitions and replay/price calculations are unchanged. The
ordinary evaluation selector is unchanged. Existing recorder tests use exact
session dates and retain explicit forced-config provenance coverage. Synthetic
calendar tests exercise weekends, holidays, unchanged weekdays, pre-data
refusals, missing required coverage and calculation-to-writer lock changes.

The historical179f82 and persistedfe365 configurations are separate scopes.
This calendar correction does not make one eligible for the other's scans.
See OOS_SCOPE_GUARD_PROPOSAL.md for a separate, unimplemented proposal.
