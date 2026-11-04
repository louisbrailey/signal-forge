# Research study integration

Authenticated dashboard: `/research-studies` (Research → Study collection), also
linked from `/ops`. Refresh every 60 seconds; no provider requests or model runs
occur during rendering. The existing `/kronos` collection panel is retained.

The two Kronos books and ten funded-forward scenario books stay separate from
the operating paper account. Their collector services already run automatically.
Integration means shared operational visibility, not authority to trade or change
the frozen protocols. No interim performance is read by the new page.

Configuration (paths only, never credentials):

- `KRONOS_COMPARISON_STATUS_PATH`: existing collector's operational status JSON.
- `FUNDED_FORWARD_STUDY_ROOT`: optional root of an existing funded study;
  defaults to `$SIGNALFORGE_DATA_DIR/funded-validation-v1`, or `./data/...`.
- Keep collectors running from the checkouts recorded in their launchd plists.
  Do not repoint them to the newest dashboard source: frozen code digests are
  intentionally different. Changes to experiments require a separately versioned
  plan; never edit the old protocol or reclassify historical runs as prospective.

The funded panel reads only a bounded plan/status and at most 253 filenames. It
does not open collection report contents, regenerate decisions, validate results,
or write files. File modification time is labelled explicitly as filesystem
evidence. Copies/restores can change that timestamp. The pinned collector verifies
source and immutable prefixes; the dashboard does not claim to independently
validate them. A missing/malformed file, future timestamp, session gap, or storage
bound fails visibly. A fresh check is separate from a successful collection.

Kronos checks every minute and projects its recorded successful collection times;
its status is stale after 180 seconds. Funded forward checks every 30 minutes,
accepts completed sessions after 17:30 America/New_York, and shows status stale
after 90 minutes. Launchd interval jobs normally show “not running” between
successful runs. Keep the Mac awake and logged in; a working dashboard does not
prove collectors are active.

Readiness verified 2026-11-03: both Kronos books recorded the November 3 session;
funded forward is waiting for first observation November 4 and first eligible fill
November 5. This is a time-specific observation, not a continuing health promise.
No interim performance was inspected or changed. No new candidate was registered
in these studies. Research signal only — no order was placed.
