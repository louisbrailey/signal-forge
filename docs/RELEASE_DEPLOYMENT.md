# Paper-only immutable release launcher

`deploy/run_release.py` launches exactly `api` or `worker`. It does not manage
launchd, merge branches, migrate a database, arm execution, enable notifications,
or change paper-ledger auto-simulation settings. Deployment and service cutover
belong to the main orchestrator. Keep the operating checkout and pinned research
study checkouts unchanged.

## Prepare a release

After the approved source and this launcher are merged, choose the full 40-character
commit SHA. Create a separate, preferably detached checkout at a permanent absolute
path outside the canonical checkout, for example
`/Users/louisbrailey/.codex/releases/signal-forge/<RELEASE_SHA>`.
The orchestrator must keep that checkout and its environment immutable for the
lifetime of both processes. Never move a live release or reuse it for edits.

From the release root, provision **its own** venv using the committed lockfile:

```sh
uv sync --frozen --no-dev --no-install-project --extra llm
```

Do not reuse/symlink the canonical venv. No `.env` belongs in the release root.
The launcher takes the existing canonical `.env` by path; it never copies that
file or writes its contents to disk or logs. Dependencies are provisioned here;
the launcher performs no installation or network request.

The package is loaded directly from `<release>/src`, with the release root as cwd.
This is intentional: `signalforge.experiments.comparison.ROOT`, research evidence
references and other `Path(__file__).parents[...]` readers need the repository's
`src`, `docs`, scripts and lockfile together. A normal noneditable wheel changes
that layout. An editable installation is unnecessary: the launcher mounts the
immutable source directory explicitly and verifies `signalforge.__file__` plus
loaded configuration origins. `.pth` editable-install hooks are never executed.

## Exact launchd ProgramArguments contract

Substitute the final full SHA and the permanent release path consistently in
both arrays. These are argv elements, without shell expansion or shell quoting:

```json
[
  "/Users/louisbrailey/.codex/releases/signal-forge/<RELEASE_SHA>/.venv/bin/python",
  "-I", "-S", "-u",
  "/Users/louisbrailey/.codex/releases/signal-forge/<RELEASE_SHA>/deploy/run_release.py",
  "api",
  "--release-root", "/Users/louisbrailey/.codex/releases/signal-forge/<RELEASE_SHA>",
  "--canonical-root", "/Users/louisbrailey/Projects/signal-forge",
  "--expected-sha", "<RELEASE_SHA>"
]
```

For the worker, use the identical array with `"worker"` instead of `"api"`.
Append `"--check-only"` to either array for preflight without starting a service.
The caller's working directory can be arbitrary; all supplied roots must be absolute.
No actual plist installation or service restart is part of this change.

`-I -S` is mandatory. It prevents cwd, user-site, inherited `PYTHONPATH`, and
site-startup `.pth` hooks from running before provenance checks. The launcher
mounts only release `src`, interpreter standard-library paths, and that release's
venv site-packages. It exports `PYTHONSAFEPATH=1`, restricts `PYTHONPATH` to release
`src`, sets executable `PATH` to the release venv plus system binaries, disables
bytecode writes, then `execve`s the same release Python with a
fixed bootstrap. That process rechecks preflight immediately before running:

- API: `uvicorn signalforge.app.main:app --host <effective APP_HOST> --port <effective APP_PORT>`
- Worker: `signalforge.cli run-scheduler`

The API's `APP_RUN_SCHEDULER` is explicitly `false` in both process environments.
The separate worker retains the existing application single-worker lock and
kill-switch behavior. This launcher does not stop an already running worker;
the orchestrator must perform the single-worker cutover.

## Configuration and path guarantees

The canonical `.env` is loaded with `override=False`. Explicit launchd variables,
including empty and lower-case settings variables, take precedence. The only
intentional replacements are interpreter isolation, normalized storage paths,
the disabled API scheduler, and the paper-only execution guard.

While cwd is still the canonical root, the launcher resolves
`SIGNALFORGE_DATA_DIR` (including its cwd-relative/default `data` behavior), reads
the release's `get_settings()`, and resolves the SQLite filename against that
same canonical root. It exports those absolute storage locations before changing
cwd to the release. An unset/empty `DATABASE_URL` retains
`<resolved data_dir>/signalforge.sqlite`. An explicit relative SQLite URL is
relative to canonical cwd, **not** relative to the data directory. Storage must
already exist; the launcher refuses to create a new data directory or database.

This reviewed source's `Settings.model_config` has **no** `env_nested_delimiter`;
`RESEARCH__EXECUTION__ENABLED=false` alone would silently do nothing. The launcher
instead uses the supported `RESEARCH` JSON environment field, preserving every
effective research setting except `execution.enabled`, which is forced to `false`.
It clears the settings cache and verifies the effective flag and preservation of
the other research values, then verifies again after changing cwd. An incompatible
future settings implementation fails closed. The same read-only SQLite preflight
reads `app_setting.research_overrides` and validates the deep-merged effective
research config: if that overlay restores execution, startup is refused. It does
not mistake `app_overrides.execution_enabled` for the actual execution setting.
No overlay, arming row, execution limit or persisted configuration is modified.
Paper auto-simulation and notification policy remain governed by their existing
settings; the launcher does not enable them or a new automated lane.

Only ordinary file-backed SQLite URLs are supported. In-memory/URI SQLite and
other backends fail closed; credentialed URLs are never included in status or
errors. Query parameters on ordinary SQLite URLs are retained.

## Safe preflight and migration check

`--check-only` validates the exact Git SHA, clean checkout (tracked changes and
untracked files), release Python, source provenance, canonical env/data paths,
effective paper boundary and existing SQLite schema. It returns only whitelisted
path origins, booleans and the code SHA. Launcher failures print a fixed category
such as `release_launcher: migration_required`, without traceback, exception text,
settings values or DSNs. Dotenv parser diagnostics are suppressed too.

The no-op migration verification reads `alembic_version` through SQLite `mode=ro`
and compares it with heads derived from the release migration files using AST
literal metadata. It imports no application/database models or migration modules,
runs no Alembic environment or upgrade function, and writes no database content.
It honours committed WAL state; it does not use `immutable=1`. A missing schema or
different/unknown head refuses startup. Schema equality establishes that no upgrade
is needed; it does not validate every column or prove operational health. Any
required migration remains a separately reviewed orchestrator action.

Check-only never imports the app, scheduler or execution layer, starts jobs, or
calls a market provider. Normal service execution subsequently retains the app's
existing behavior and logging. A clean Git check is a startup check, not a
filesystem security boundary: the orchestrator remains responsible for keeping
release code and dependency files unchanged after validation.

## Focused validation

```sh
devkit run -- env PYTHONPATH=src .venv/bin/python -m pytest tests/test_release_launcher.py --no-cov -q
devkit run -- .venv/bin/python -m ruff check deploy/run_release.py tests/test_release_launcher.py
devkit run -- .venv/bin/python -m black --check deploy/run_release.py tests/test_release_launcher.py
```

Tests use disposable Git checkouts, venvs, real release configuration modules,
fake service entrypoints, SQLite fixtures and sentinel secrets. They exercise the
actual isolated interpreter and exec path without live credentials, providers,
canonical state or service changes.
