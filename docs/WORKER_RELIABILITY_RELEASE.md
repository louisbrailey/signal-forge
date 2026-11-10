# Worker reliability release boundary

PR #68 repairs long SQLite write transactions, missing scan-session outcomes,
mechanical-only health evidence, feed-calendar staleness, and forward collector
handling of missed sessions and vendor revisions.

## Deployment hold (2026-11-09)

The operating worker and the prospective studies currently use source release
`21e87a33c77c1b63fcef99f4d52026b77c62b359`. Do not deploy this worker update over
that source worker while treating the existing Kronos v2 books as unchanged.

A scan refreshes `StrategyVersion.spec_json`, including its `git_sha`. The
frozen Kronos collector checks the complete spec digest against its manifest.
A worker upgrade therefore changes admitted source provenance even when the
rule parameters are unchanged. Keeping only the collector pinned is insufficient.
Do not preserve a false source SHA, weaken its comparison, or rewrite its manifest
to make an upgraded worker appear to satisfy the old experiment.

The funded forward collector has a separate frozen source digest. This release
changes files outside the two collector-protocol amendment files, so applying
its collector directly to existing v2 is refused. Keep the existing collector,
five-spec scope, registry and plan pinned. The new collector behavior is available
for a separately registered future study, not automatically applied to v1/v2.

A later deployment must either preserve the genuinely frozen source scanner or
register an independent future study under the reviewed new source. Preserve the
old observations and missed windows, identify the transition explicitly, and
verify both source and collector identities before collecting new evidence.

## Health display

The latest assessment of each version is authoritative, including `insufficient`.
Historical favorable or adverse assessments remain stored but cannot masquerade
as current evidence. Across versions, a sibling with no evidence cannot hide
another version's current assessed downgrade. Strategy status and arming gates
remain separate from display selection.
