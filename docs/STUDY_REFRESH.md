# Versioned paper study rollover

`scripts/study_refresh.py` validates parent metadata, stages, freezes and
activates a separate generation. Collectors and dashboard use one atomic active
registry. Refresh commands never fetch data, run inference, inspect interim
performance, promote strategies, submit orders, change kill state or install
launchd. Main performs actual creation and service cutover after merged CI.

The v2 envelope and versioned directories contain unchanged native
`kronos-comparison-v1` / `funded-forward-v1` file schemas. Evidence stays
independent; no v1 collections, positions, decisions or scores are copied.

## Freeze and lineage

`validate-parent` runs the pinned checkout's `open_books` / `validate_plan`
with bytecode writes disabled. Kronos cross-checks the sidecar and embedded
SQLite manifest, code hash and pinned artifacts. Forward validates its code
digest; its v1 plan has no original self-checksum, so the refresh attests its
current bytes rather than claiming an unverifiable historical checksum.

`stage` requires a different, clean, detached checkout at a full Git SHA.
Script and package `ROOT` must resolve there. It archives exact parent metadata
and records parent/release/native code SHA, config/model hashes and explicit
future dates. No environment contents, credentials or secret hashes are saved.
`check` uses the native freeze API in a private temporary directory and removes
it. `start` repeats validation and atomically publishes one new native study,
with a separate `refresh-lineage.json` attesting child and parent metadata.

All inherited settings, cash, costs, thresholds, review floors, model
weights/tokenizer/implementation and duration must match. Only creation dates,
native code digests, strategy `git_sha` provenance and the explicitly authorized
Kronos version/scope exception below may differ. Forward config hash covers its
native plan policies/specs; engine defaults are covered by the code digest.
Forward's model hash is null. Kronos hashes its native config and complete
per-file model artifact inventory. Parent, runtime and Kronos source effective
execution must remain disabled with `paper_reference`.

## Explicit scope APIs: forward blocker resolved

The real forward v1 plan freezes **five** strategies while the current default
registry has ten daily strategies. `prospective_funded.freeze` and
`action_replay.compare` now accept optional `strategy_specs=None`. Supplied
definitions must match current registered `(name, version)` specs in every
field except `git_sha`. Unknown, duplicate, empty, intraday or changed
definitions are refused. The forward collector validates and executes **only**
the plan's listed definitions. `None` preserves existing API behavior. Production
code never monkeypatches the registry. Tests use actual v1 metadata to freeze
five definitions and execute a real offline replay with exactly those five.

Kronos preserves parent versions/scopes by default. To include **current
PAPER_APPROVED versions**, including high52 where approved, staging requires
`--accept-scope-change --scope-change-reason '...'`. A native metadata-only
freeze captures the exact new versions and approval-scope hashes. The old/new
maps and reason are immutable request/child lineage metadata. Every other field
must match; `start` refuses further scope drift since staging. The flag never
promotes a strategy or permits threshold/model-parameter changes. Forward
retains its parent's five-strategy scope.

## Strict future dates

Observation must be a trading session **strictly after the New York calendar
date at staging and publication**, within 90 days. Forward entry must explicitly
be the next trading session. Even a creation before today's opening bar cannot
claim today's session. Weekend, NY midnight and exchange-calendar boundaries
are tested. Historical warmup retains its inherited history start.

Native APIs use real creation time; dates/clocks are never patched. For a
Monday observation, run Kronos after Friday's real exchange close (including
early closes), during the weekend or before NY midnight ending Sunday.
Forward can freeze Friday through Sunday. `check` reports
`WAITING_FOR_FREEZE_WINDOW` when native dates differ; `start` refuses. If the
release arrives late, stage another unused control folder with later dates.

## Atomic registry, collector fencing and UI

Staging/publication use nonblocking sibling `flock`, private temporary builds
and same-filesystem rename. Existing requests/studies are never overwritten
or refrozen; failed generation can retry. Hard termination may leave
`.refresh-stage-*`, `.scope-check-*` or `.refresh-build-*` orphans. Remove only
after confirming no publisher holds the lock. This is atomic publication,
not a power-loss durability guarantee.

`activate` validates all three started studies and atomically replaces one
checksummed registry using compare-and-swap `--expected-generation`. It requires
a **new** Kronos state directory and fresh forward heartbeat path. Archives
retain old operational identities/status paths separately. Success counters,
transitions and evidence are not copied into v2. Numbers increase and native
identities cannot overlap archived ones. This implementation creates v2 names;
another rollover requires new native versioned identities.

Both collectors require `--registry --expected-generation` for versioned
studies. They pin registry hash/generation, exact directories and native
metadata/lineage checksums before polling. Before heartbeat publication they
recheck under the **same lock used by activation**. A mid-poll cutover fences
the old publisher. Per-study locks and daily deduplication remain. Old polls
may finish appending to their own private study, but cannot publish active
health for a different generation. No kill-all-writes policy is introduced;
allowed maintenance closes remain governed by existing runners.

Set `STUDY_ACTIVE_REGISTRY_PATH` in the app/service environment. `/kronos` and
authenticated `GET /kronos/collection-status` expose bounded operational
projections: generation, release/lineage identity, future start date, known
statuses and times. Missing/mismatched/stale v2 never falls back to healthy v1.
Archived generations have a separate details section containing operational
metadata only. Forward has an independent fenced heartbeat and visible status.
Without a registry configured the old setting remains compatible, explicitly
labelled **Legacy configuration**. Registry replacement during projection
invalidates the mixed snapshot rather than displaying stale active health.

Heartbeat freshness: Kronos 180 seconds; forward 3900 seconds. Immutable hashes
do not age. Bounds: registry 60 KiB/16 archived generations, native metadata
2 MiB, Kronos heartbeat 256 KiB, artifact validation 256 roots/20,000 files/4 GiB,
pinned subprocess 60 seconds. No arbitrary text, local paths, P&L or model output
is projected to the UI.

Only frozen manifest metadata is archived. Embedded Kronos metadata is read in
a read-only SQLite snapshot, including with unrelated WAL appends; the sidecar
is cross-checked and reread. No concurrent raw DB copy/hash is taken. Parent
byte mutation blocks rather than rebasing. For full archival, stop v1, wait for
its collector lock and use SQLite online backup/read-only transaction; never
copy/hash the main DB while ignoring WAL. Retain v1 plans/outcomes/checkouts,
do not force finalization and do not label v1 invalid without evidence. No crypto
old-period performance is inherited or compared.

## Exact operator commands after merged CI

Main owns actual creation, environment changes, service scheduling and cutover.
The release helper agent owns `deploy/run_release.py`. This implementation does
not edit that file, `app/views.py`, scheduler/hourly ledgers, canonical dirty
code or pinned v1 files. Replace the full release SHA. Never print/copy env
contents or credentials. Configure the app/service with the same registry path
and restart through the coordinated release procedure; the export below also
configures this operator shell.

```sh
set -e
RELEASE_SHA='<full merged release SHA>'
STUDY_RELEASE=/Users/louisbrailey/.codex/worktrees/study-release-v2/signal-forge
STUDY_CONTROL=/Users/louisbrailey/Projects/signal-forge/data/study-refresh-v2
STUDY_ENV=/Users/louisbrailey/Projects/signal-forge/.env
KRONOS_V1=/Users/louisbrailey/.codex/worktrees/kronos-shadow-research/signal-forge
FORWARD_V1=/Users/louisbrailey/.codex/worktrees/profit-target-assessment/signal-forge
ACTIVE_REGISTRY="$STUDY_CONTROL/active.json"
export STUDY_ACTIVE_REGISTRY_PATH="$ACTIVE_REGISTRY"
git worktree add --detach "$STUDY_RELEASE" "$RELEASE_SHA"
cd "$STUDY_RELEASE"
uv sync --frozen --extra llm
```

The explicit example dates below are valid for creation on November 8, 2026.
Choose later future trading sessions if the release arrives later. Publication
must finish before the observation NY calendar date begins.

```sh
OBS=2026-11-09
ENTRY=2026-11-10
for HORIZON in short medium; do
  .venv/bin/python scripts/study_refresh.py stage --kind kronos \
    --parent "$KRONOS_V1/data/kronos-comparison-v1-$HORIZON" \
    --parent-checkout "$KRONOS_V1" --checkout "$STUDY_RELEASE" \
    --release "$RELEASE_SHA" --destination "$STUDY_CONTROL/$HORIZON" \
    --first-observation "$OBS" --paper-only --env-file "$STUDY_ENV" \
    --accept-scope-change --scope-change-reason 'Current PAPER_APPROVED scope, including high52 where approved'
done
.venv/bin/python scripts/study_refresh.py stage --kind forward \
  --parent /Users/louisbrailey/Projects/signal-forge/data/funded-validation-v1 \
  --parent-checkout "$FORWARD_V1" --checkout "$STUDY_RELEASE" \
  --release "$RELEASE_SHA" --destination "$STUDY_CONTROL/forward" \
  --first-observation "$OBS" --first-entry "$ENTRY" --paper-only --env-file "$STUDY_ENV"
for STUDY in short medium forward; do
  .venv/bin/python scripts/study_refresh.py check "$STUDY_CONTROL/$STUDY" --paper-only --env-file "$STUDY_ENV"
  .venv/bin/python scripts/study_refresh.py start "$STUDY_CONTROL/$STUDY" --paper-only --env-file "$STUDY_ENV"
done
```

Review staged scope old/new maps and reason before start. Publication is atomic
per study, not across all three. A settings/definition mismatch blocks rather
than changing parameters. Provider entitlement, model runtime and source scan
availability remain separate operational checks.

After all starts succeed, activate once. Supply the actual v1 operational
heartbeat path; the known default is shown. Preconfiguring the app to the new
registry is safe: until it exists, status is unavailable, not v1 success.

```sh
.venv/bin/python scripts/study_refresh.py activate --paper-only --env-file "$STUDY_ENV" \
  --registry "$ACTIVE_REGISTRY" --generation 2 --expected-generation 0 \
  --study "$STUDY_CONTROL/short" --study "$STUDY_CONTROL/medium" --study "$STUDY_CONTROL/forward" \
  --state-dir "$STUDY_CONTROL/collector-state-g2" \
  --legacy-kronos-status "$KRONOS_V1/data/comparison-collector/status.json"
.venv/bin/python scripts/kronos_comparison_collect.py --checkout "$STUDY_RELEASE" \
  --experiment "$STUDY_CONTROL/short/kronos-comparison-v2-short" \
  --experiment "$STUDY_CONTROL/medium/kronos-comparison-v2-medium" \
  --state-dir "$STUDY_CONTROL/collector-state-g2" --env-file "$STUDY_ENV" \
  --registry "$ACTIVE_REGISTRY" --expected-generation 2 --check-only
.venv/bin/python scripts/funded_forward.py collect "$STUDY_CONTROL/forward/funded-validation-v2" \
  --env-file "$STUDY_ENV" --registry "$ACTIVE_REGISTRY" --expected-generation 2 --check-only
```

Both checks are offline, including after observation begins. Forward validates
the plan/scope and returns waiting, already collected or ready before reading
credentials or fetching data. Remove `--check-only` for scheduled collection:
forward may fetch licensed data and Kronos may invoke local inference after an
approved scan. Neither is activated or scheduled by the refresh command.

Main points interpreter, script, `PYTHONPATH`, working directory, roots,
registry and expected generation together to the immutable release, using
existing launchd definitions/release helper. Verify generation 2 and separate
archive status on `/kronos` and `/kronos/collection-status`. Stop/archive v1 only
after v2 checks, collectors and visible status are verified; never rewrite it.
