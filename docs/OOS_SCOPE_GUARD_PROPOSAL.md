# Separate proposal: explicit evaluation identity and current candidate config

PROPOSAL ONLY, awaiting Dirac design review. No selector, CLI, candidate config
gate, current settings or fixture config hashes change in the calendar patch.
This can be a second independently reviewed commit in follow-up67 after approval.

## Scope separation and feasibility

The preceding bounded audit on6bb9fbe found recovered179f82... matches newest
approvals48/49/50. Persistedfe365... differs and matches older approvals on these
version/snapshot pairs. These are historical audit observations, not a fresh
attestation of a running worker. approved_scope_scan groups by newest approval
but calls run_scan without a historical config; run_scan reads effective current
settings. Approval membership permits ANY matching passing scope, whereas
latest_oos_metric selects newest name/version evidence independently of config.
A legitimate179f82 record must not globally unlockfe365 scans.

The requested separation is feasible without new sealed evaluations or parameter
changes. Choose a predeclared evaluation using approval/input metadata only, then
require the actual latest candidate evidence to match effective config. The daily
calendar fix is an independent prerequisite and review item.

## Exact proposed optional API and CLI

Add keyword-only evaluation_id: int | None = None to
record_development_oos_backtest. Add optional --evaluation-id INTEGER to
record_oos_backtest_cmd and forward it. None MUST preserve the existing selector:
newest passing evaluation for the version/snapshot, otherwise newest evaluation.
No new write mode, replacement record path, migration or outcome selector.

For an explicit ID, BEFORE any data/backtest query require:

- Exact registered strategy name/version and dataset_snapshot_id membership.
- Current executable spec hash, evaluation.passed=true and currently PAPER_APPROVED
  Strategy/StrategyVersion status with a matching approved scope.
- evaluation.config_hash==the supplied CURRENT cfg.config_hash. An ID does not
  authorize restoring historical settings or overriding a config mismatch.
- Exact ordered symbols, source, window start and canonical daily cutoff; all
  five reproduction flags true. No override can waive calendar/coverage checks.

Main preselects the LATEST metadata-approved evaluation matching CURRENT config,
strategy version, snapshot and parameter hash, ordered by evaluated_at/id, then
pins that ID before computation. Olderfe365 approvals may be legitimate even if
a newer179f82 approval exists; do NOT require the globally newest approval under
another config. Never select by expectancy or try other IDs after outcomes.
Recommended API enforcement: refuse an explicit ID other than that deterministic
latest current-scope metadata match, rather than leaving this solely to convention.

DevelopmentOOSRecord already carries evaluation_id and provenance. The existing
short writer can retain that pin and independently revalidate identity/config/
calendar checks. No serialized JSON becomes a trusted writer dataclass. An absent
matching current approval is a blocker, never an optimization opportunity.

## Exact proposed candidate-quality gate

Keep latest_oos_metric's selector unchanged. After selecting the actual LATEST
metric for CURRENT name/version in _build_draft, require:

    metric.run.config_hash == cfg.config_hash

Missing/empty/malformed saved config identity stays unknown, never clean. A
mismatch yields NO_TRADE with an OOS config-scope reason. Never filter by config
and silently fall back to an older good row. Numeric/provenance/regime/risk gates
and all thresholds remain unchanged.

A shared pure helper can report missing/invalid/mismatched config identity for
candidate quality and UI. Pass effective expected config explicitly from
evidence_inventory into metric_evidence. Retain measured values, but display
ambiguity and both identities; no expected current config means unverified match.
No saved rows, old decisions, statuses or promotions are rewritten.

The forced-provenance guard remains independent: matching config does not cure
allow_mismatch/non-reproducing inputs. A later stronger association should also
tie evaluation ID, dataset snapshot, source/universe and spec hash to the intended
approval. Config equality alone is not full dataset identity; that broader work
must not be silently included. Per-scope historical config injection into scans
is also a broader change, not an implicit global settings replacement.

## Minimal anticipated fixture impact — NOT changed yet

Only seeds entering candidate/display matching, whose purpose is NOT mismatch,
should use that test's actual cfg.config_hash. Do not globally replace literals:

- tests/research/test_scan.py: _seed's "test"; its unrelated regime-only "t"
  need not change if it never reaches candidate/config gating.
- tests/research/test_oos_provenance.py: _record's "synthetic-regression" default
  becomes a real synthetic ResearchConfig hash; mismatch cases override it.
- tests/research/test_scan_source_isolation.py: matching candidate-evidence seed.
- tests/research/test_briefing.py: matching scan seed where it reaches quality.
- tests/app/test_dashboard.py: matching seed's "t" becomes effective fixture cfg;
  unrelated manual candidate records remain as intended.
- tests/research/test_evidence.py: matching _metric seeds use an actual hash;
  intentionally unknown-config legacy cases remain unknown.

Health-monitor/options-only "test" hashes are separate consumers; do not rewrite
them merely because a text search finds them. Never fabricate matching provenance
for a test explicitly exercising legacy unknown identity.

Proposed tests: explicit current-scope ID match; wrong version/snapshot/spec,
unapproved/stale ID and cfg mismatch; default None compatibility; deterministic
metadata-only choice; pre-data refusal on invalid explicit ID. Candidates: latest
match unchanged; latest wrong cfg -> NO_TRADE despite older matching positive
row; latest unknown cfg -> NO_TRADE; newer other-version row cannot substitute.
UI shows ambiguity without numeric/status rewrites. No production settings,
strategy parameters or numeric thresholds change.
