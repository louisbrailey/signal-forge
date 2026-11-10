# Prospective collection operations

The Kronos collector requires a completed, readiness-enforced approved scan
before midnight UTC. This is the frozen engine's admission boundary, not New
York midnight. In Pacific standard time the deadline is 16:00; after a missed
window the collector reports `blocked` with error category `MissedUTCCollectionWindow`, never a
successful prospective observation. A previously captured batch can resume;
an uncaptured missed decision cannot be reconstructed as forward evidence.

November 9, 2026: the approved scan completed November 10 at 01:23:08 UTC
(November 9, 17:23 Pacific), after that deadline. Forward study collection is
separate and completed for November 9. macOS power logs confirm Clamshell Sleep
at12:29 Pacific, then full wake at16:44; the laptop lid was closed during
the scheduled scan and the UTC collection cutoff. An idle assertion cannot
prevent this physical closed-lid condition. Neither historical outcomes nor frozen
parameters should be rewritten to hide the missing Kronos session.

For an always-on Mac, install the optional `com.signalforge.study-awake.plist`
from `deploy/launchd/templates` into `~/Library/LaunchAgents` with mode 600 and use
`launchctl bootstrap gui/$(id -u) <absolute-plist-path>`. It runs the macOS
`caffeinate -i` assertion while loaded, preventing idle system sleep. It does
not prevent deliberate sleep, closed-lid sleep, power loss or shutdown, and
cannot wake an already sleeping Mac. Remove the assertion with
`launchctl bootout gui/$(id -u)/com.signalforge.study-awake`.

The source worker, model runtime, registry and all frozen study inputs remain
pinned. A collector-only orchestration script may be deployed separately with
the frozen release's Python/dependencies and `PYTHONPATH=<release>/src`;
`--checkout` must still identify that frozen release. Do not restart the source
worker on a different commit, edit native manifests or change the engine's
code hash to accommodate an orchestration fix.

Check operational status, scan completion and captured batches separately.
A fresh polling heartbeat is not proof of a completed study observation.
No performance review is justified by the first observation alone.

Research signal only — no order was placed.
