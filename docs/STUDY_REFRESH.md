# Versioned paper study refresh

`scripts/study_refresh.py` stages a new v2 generation and invokes the existing
`experiments.comparison.freeze` or `research.prospective_funded.freeze` API. It
does not run collectors, providers, inference, backtests, strategy selection or
promotion. It does not change launchd, operating settings, arming or kill state.
It reads manifest/configuration metadata only, never interim performance.

The version belongs to the refresh envelope and folder identity. Native
`kronos-comparison-v1` / `funded-forward-v1` **file schemas remain unchanged** so
the existing collectors can open their new private studies.

## Lifecycle and invariants

1. `validate-parent` runs the pinned checkout's `open_books` / `validate_plan`
   in a separate Python process with bytecode writes disabled. For Kronos it
   cross-checks the JSON sidecar with the embedded SQLite manifest, verifies
   its digest/code hash and all existing model artifacts. Forward checks the
   frozen code digest. A forward v1 plan has no original self-checksum; the
   refresh attests its current bytes, not an unverifiable historical checksum.
2. `stage` requires a different, clean, detached release checkout at an exact
   full Git SHA. The script and package imports must resolve to that checkout;
   installed copies with a different repository `ROOT` are refused. Supply
   explicit future observation/entry sessions and `--paper-only`.
3. The new control folder contains `refresh.json` and a byte-exact archived
   `manifest.json` or `plan.json`. Lineage includes parent path/commit/native
   code digest, metadata checksum, config hash and model artifact inventory
   hash. No credentials, environment contents or secret hashes are stored.
4. `check` freezes a temporary candidate using the native API and removes it.
   It compares **all** inherited fields, including scopes, approved versions,
   model roots/weights/tokenizer/implementation, cash, costs and review
   thresholds. Forward retains symbols, metadata, ticker bridges, history
   warmup and strategy definitions. Only native creation dates/code digest,
   future study dates, and strategy `git_sha` provenance may differ.
5. `start` performs the same checks, verifies exact requested dates, rechecks
   parent/release/execution, then atomically publishes one new native folder:
   `kronos-comparison-v2-short`, `kronos-comparison-v2-medium` or
   `funded-validation-v2`. It adds a separate `refresh-lineage.json` recording
   the child native manifest checksum, release SHA, native code/config/model
   hashes and parent lineage. It never edits the native frozen metadata.

The forward config hash covers native plan policies/specs, including thresholds
and metadata. Its engine's hard-coded risk/cost defaults are covered by the
native code digest; they are not falsely represented as environment settings.
Forward has no model weights, so `modelweights_sha256` is null. Kronos hashes
the native config and the complete per-file model artifact hash inventory.

Both parent and runtime execution must be disabled with `paper_reference`;
Kronos also checks the source DB's effective execution configuration. Staging
does not submit openings or close positions. Existing kill-switch behavior,
including allowed maintenance closes, remains with the existing runners.

## Future date window

Observation must be a trading session **strictly after the New York calendar
date at staging and at publication**, within 90 days. Forward's explicit entry
must be the trading session immediately following observation. Thus even a
creation before today's opening bar cannot claim today's session.

Native APIs do not accept arbitrary future start dates. Kronos chooses the
first session whose close is after freeze time; forward chooses the next NY
session and entry one session later. `start` never patches dates or supplies a
fictional `now`. For a Monday start, run Kronos after Friday's exchange close
(including its real early-close calendar), during the weekend, or before NY
midnight ending Sunday. Forward may freeze on Friday through Sunday. All
studies must publish before observation's NY calendar date begins. `check`
returns `WAITING_FOR_FREEZE_WINDOW` when native dates differ; `start` refuses.
If a release arrives too late, stage a new unused control folder with later
dates; never reset or rewrite the earlier request or any observed study.

New generations contain no parent collections, positions, decisions or scores.
Historical bars used for warmup retain the inherited history start; observation
and entry windows remain future-only. Crypto ledger performance is never
imported. Nothing here declares Kronos v1 invalid or validates its performance.

## Atomicity, concurrency and archive scope

Staging and publication use a nonblocking sibling `flock`, a private temporary
directory on the same filesystem and directory rename. Cooperating publishers
cannot race or overwrite a destination. A completed study is never refrozen;
the existing collectors retain their per-study locks/deduplication. Failed
generation cleans its temporary directory and can retry from the same request.
A hard process termination can leave `.refresh-stage-*` / `.refresh-build-*`
orphans; these are never treated as started studies and can be removed after
confirming no publisher holds the lock. The sibling lock files intentionally
remain. This is atomic publication, not a power-loss durability guarantee.

The archive is **frozen manifest metadata only**. Embedded Kronos metadata is
read with the pinned API in a read-only SQLite snapshot (a single SELECT),
including when unrelated records are being appended in WAL mode. The sidecar
is cross-checked and reread after validation. No raw DB checksum/copy is taken
against a concurrent writer. Parent metadata must remain immutable; any later
byte change, including whitespace, blocks check/start rather than rebasing.
An immutable checksum does not expire with age.

Keep full v1 evidence and its original checkout in place. If the operator wants
a full archive after cutover, first stop that v1 collector, wait for its lock to
be free, and use SQLite's online backup API/read-only transaction for a
consistent snapshot. Do not copy/hash a live main DB file while ignoring WAL.
Do not force finalization or rewrite outcomes. Stop/archive v1 only after v2
creation, collector checks and the visible active-status switch succeed.

Metadata is capped at 2 MiB, each pinned subprocess at 60 seconds, and Kronos
artifact inventory at 256 roots, 20,000 files and 4 GiB. Refreshing fails closed
if inherited assets are missing or revised. Existing provider entitlement,
model runtime readiness and source scan availability are separate checks.

## Verified forward API blocker at base bc37836

Metadata-only inspection of the existing `funded-validation-v1/plan.json`
found **five** frozen strategies. At this base, `default_strategies()` returns
**ten** non-intraday strategies. The first five definitions match the parent
apart from code provenance, but expanding the scope is not an authorized
refresh. `check` / `start` therefore block on `strategies` for this real parent.
No v2 forward study has been created or declared runnable from that parent.

Preserving the five-strategy scope requires coordinated changes outside this
patch's ownership:

* `src/signalforge/research/prospective_funded.py::freeze`: accept and validate
  an explicit immutable strategy scope rather than always freezing the whole
  default registry. Keep the parent's review thresholds and policies exact.
* `src/signalforge/research/action_replay.py::compare`: accept the same scope;
  currently it independently loops over all defaults, ignoring the plan's
  `strategies` field. Merely changing the frozen JSON would be unsafe.
* `scripts/funded_forward.py::_collect`: pass the frozen validated scope into
  the replay and refuse definition mismatches. Add focused tests proving only
  the parent scope is executed and extra defaults cannot silently enter it.
* `scripts/study_refresh.py::native_freeze`: after that explicit scope API is
  agreed and implemented, pass the parent's frozen strategy scope into it.
  The current call deliberately uses the existing API and fails closed when
  its default registry would expand the parent plan.

Main should coordinate these API repairs before making a release intended to
start this forward v2. The CLI intentionally reports the blocker rather than
patching native manifests or monkeypatching registry functions. Kronos does
not share this forward runner; this finding says nothing about Kronos v1
validity. Its updated source approvals/settings still need a post-release
`check` before publication; they were not inferred from interim outcomes.

## Operator commands after a merged release exists

These commands are for the main orchestrator, not a deployment performed by
this change. `RELEASE_SHA` must include this implementation **and** any
coordinated status-reader changes. Use a new release checkout and data folders;
leave the canonical checkout and both pinned v1 code checkouts untouched.
Replace the full SHA and local env path; never paste credential values.

```sh
RELEASE_SHA='<full merged release SHA>'
STUDY_RELEASE=/Users/louisbrailey/.codex/worktrees/study-release-v2/signal-forge
STUDY_CONTROL="$STUDY_RELEASE/data/study-refresh-v2"
STUDY_ENV=/Users/louisbrailey/Projects/signal-forge/.env
KRONOS_V1=/Users/louisbrailey/.codex/worktrees/kronos-shadow-research/signal-forge
FORWARD_V1=/Users/louisbrailey/.codex/worktrees/profit-target-assessment/signal-forge

git worktree add --detach "$STUDY_RELEASE" "$RELEASE_SHA"
cd "$STUDY_RELEASE"
uv sync --frozen --extra llm
```

Explicit example dates below work only for creation on November 8, 2026 (or an
eligible preceding freeze window). If the release lands later, select later
future sessions from the exchange calendar and change **both** variables.

```sh
OBS=2026-11-09
ENTRY=2026-11-10

for HORIZON in short medium; do
  .venv/bin/python scripts/study_refresh.py validate-parent \
    --kind kronos --parent "$KRONOS_V1/data/kronos-comparison-v1-$HORIZON" \
    --parent-checkout "$KRONOS_V1" --paper-only --env-file "$STUDY_ENV"
  .venv/bin/python scripts/study_refresh.py stage \
    --kind kronos --parent "$KRONOS_V1/data/kronos-comparison-v1-$HORIZON" \
    --parent-checkout "$KRONOS_V1" --checkout "$STUDY_RELEASE" \
    --release "$RELEASE_SHA" --destination "$STUDY_CONTROL/$HORIZON" \
    --first-observation "$OBS" --paper-only --env-file "$STUDY_ENV"
done

.venv/bin/python scripts/study_refresh.py stage --kind forward \
  --parent /Users/louisbrailey/Projects/signal-forge/data/funded-validation-v1 \
  --parent-checkout "$FORWARD_V1" --checkout "$STUDY_RELEASE" \
  --release "$RELEASE_SHA" --destination "$STUDY_CONTROL/forward" \
  --first-observation "$OBS" --first-entry "$ENTRY" \
  --paper-only --env-file "$STUDY_ENV"

for STUDY in short medium forward; do
  .venv/bin/python scripts/study_refresh.py check "$STUDY_CONTROL/$STUDY" \
    --paper-only --env-file "$STUDY_ENV" || break
  .venv/bin/python scripts/study_refresh.py start "$STUDY_CONTROL/$STUDY" \
    --paper-only --env-file "$STUDY_ENV" || break
done
```

Check each exit code; this is per-study atomicity, not an all-three transaction.
`Inherited metadata changed: <field paths>` is a blocker, not a request to tune
or edit the v1 record. A merged release that changes config schema, scopes,
caps, definitions or review policy may need a separately reviewed future study
protocol. This tool deliberately does not auto-migrate those semantics.

After all three start successfully, run these bounded collector checks from
the immutable checkout. Kronos `--check-only` never invokes inference or
advances books. Before `OBS`, forward `collect` must return
`WAITING_FOR_FIRST_FUTURE_SESSION` before reading credentials or making a
provider call. At/after `OBS`, that forward command is an actual authorized
collection and can fetch data; it is not an offline check.

```sh
.venv/bin/python scripts/kronos_comparison_collect.py \
  --checkout "$STUDY_RELEASE" \
  --experiment "$STUDY_CONTROL/short/kronos-comparison-v2-short" \
  --experiment "$STUDY_CONTROL/medium/kronos-comparison-v2-medium" \
  --state-dir "$STUDY_CONTROL/collector-state" --env-file "$STUDY_ENV" --check-only

.venv/bin/python scripts/funded_forward.py collect \
  "$STUDY_CONTROL/forward/funded-validation-v2" --env-file "$STUDY_ENV"
```

Kronos' ongoing command is identical with `--check-only` removed; it can perform
local model inference after an approved scan. Forward's ongoing command is the
same `collect`. No commands here install or reload launchd. The release helper
agent owns `deploy/run_release.py` and its tests; main owns scheduling/cutover.

## Required active-status integration: main orchestrator ownership

The existing reader at `src/signalforge/kronos/collection_status.py` hard-codes
`BOOKS` to the two v1 basenames. Merely changing
`KRONOS_COMPARISON_STATUS_PATH` to a v2 heartbeat will show invalid metadata.
Leaving the path unchanged can silently keep displaying a healthy v1 collector.
The collector identifies experiments by `directory.name`, which is why the
native v2 directories above have distinct, versioned names.

Minimal coordinated integration proposal (not implemented in this patch):

* `src/signalforge/config/settings.py`: add an optional active-study registry
  path (for example `STUDY_ACTIVE_REGISTRY_PATH`); keep the existing heartbeat
  setting only as an explicitly labelled legacy fallback.
* `src/signalforge/kronos/collection_status.py`: resolve the expected active
  names **and heartbeat path from one bounded registry snapshot**, rather
  than a hard-coded `BOOKS` tuple plus a separately switched environment path.
  Validate exact generation, unique names, known statuses, freshness and
  timestamps. Missing/mismatched active metadata must be visibly unavailable;
  never fall back to v1 success as evidence of active v2 health.
* `scripts/kronos_comparison_collect.py`: pin the active registry identity for
  the poll, and refuse to publish active health if its generation/expected
  names change before publication. Preserve existing per-study collector
  locks and day deduplication. Use a **new v2 state directory**; do not mix v1
  transitions/last-success history into v2. The release helper must serialize
  collector stop/start and registry cutover so only the intended active poll
  publishes; the refresh lock alone does not own daemon scheduling.
* `src/signalforge/app/routers/kronos.py` and
  `src/signalforge/app/templates/kronos.html`: surface active generation,
  start date and lineage identity from the sanitized status projection; put
  archived v1 operational metadata in an explicitly separate section. Do not
  open book DBs or expose interim performance. No `app/views.py` edits are
  required by the reader inspected at base `bc37836`; coordinate any newer
  canonical changes with main before editing that shared file.
* `tests/app/test_collection_status.py` and
  `tests/experiments/test_collector.py`: add active-v2/archived-v1 separation,
  registry mismatch/missing/stale heartbeat, mid-poll cutover race and duplicate
  poll tests. These integration tests belong with main's reader changes.
* `deploy/launchd/com.signalforge.kronos-comparison.plist` and
  `deploy/launchd/templates/com.signalforge.funded-validation.plist`: main
  points interpreter, scripts, `PYTHONPATH`, working directory and study roots
  to the same immutable release; use the new v2 heartbeat directory. Do not
  reuse the old pinned package imports with the new script.

A registry can hold `{schema, generation, activated_at, release_sha, active,
archive}`. `active.kronos` contains the two names, control/native directories,
request hashes and common heartbeat path. `active.forward` contains its native
directory, request hash and operational `status.json` path. `archive` references
v1 metadata separately. Main atomically replaces the registry **after** every
new study/check succeeds and coordinates old collector retirement. Never
copy prior success counters into the new generation. No general forward-study
dashboard reader exists in the inspected base; main must add a bounded
operational projection if forward status is to be displayed.

No active-pointer switch is performed by this implementation. Treat visible
status integration and scheduling as outstanding release work, not as already
working merely because the staging CLI passes its tests.
