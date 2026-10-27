# Intraday backfill resume agent

The per-user launch agent resumes the existing run ID recorded in its template
after login and retries at most every 30 minutes. It reads the original provider,
symbol list, date window and bar-size metadata, checks the emergency stop, and
holds an exclusive lock until the backfill exits. A completed run performs no
provider request. No ORB diagnostic or strategy evaluation is triggered.

Installation is an operator action. Place `scripts/resume_intraday_backfill.py`
at `~/.local/share/signalforge/resume_intraday_backfill.py`, install the plist
in `~/Library/LaunchAgents`, and bootstrap it in the user's GUI domain. Stop
any older direct backfill and legacy agent first: direct CLI invocations do not
acquire the resume agent's lock. Chunk-level commits preserve completed progress;
the interrupted chunk is fetched again and deduplicated.

The Mac must be awake and the user logged in. Reboot/log-in resumes the recorded
scope; sleep pauses it. Watch the two `intraday_resume.*.log` files and
`ingestion_run` for failures. `launchctl print gui/$(id -u)/com.signalforge.intraday-backfill`
shows the job state. After completion, periodic checks exit without a request.
Paper trading, risk settings, and frozen research studies are unaffected.
