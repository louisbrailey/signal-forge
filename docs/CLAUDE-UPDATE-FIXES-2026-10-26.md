# Claude update review fixes — 2026-10-26

## Confirmed defects fixed

- The shared emergency-stop reader returned inactive on corrupt or unreadable
  state. It now returns engaged for read/encoding errors, malformed JSON, wrong
  active types, missing/invalid timestamps, or timestamps without a timezone.
  Error logs contain only a fixed category, not file contents or exception text.
  Reads preserve the broken file for inspection; an explicit operator release
  writes a valid replacement and records the normal transition. A missing file
  retains the documented fresh-install inactive behavior.
- The crypto paper chart produced two observations at the same timestamp whenever
  open marks were nonzero. Lightweight Charts requires unique increasing times.
  It now emits a single point with closed R plus the stored open marks; it does
  not invent a historical mark series.

- The markets snapshot labelled a 22-observation return as a 30-day return.
  It now compares to the last stored close on or before 30 calendar days earlier;
  insufficient history returns unavailable instead of a shorter-period return.

## Scope and safeguards

Changes are prepared on a separate branch, not deployed to the operating Mac.
No provider calls, live database writes, strategy parameter changes, promotion
changes, new sealed evaluations, service restarts, or alert dispatches were made.
Execution's independent K2 check and protective-close rules remain unchanged.
The frozen Kronos checkout, manifests, books, model artifacts and collector are
not modified. These fixes must not be copied into that pinned study checkout.

## Remaining research and operational limits

This review does not establish profitability or certify every path. The crypto
ledger is a replay-derived R record, not a cash-constrained portfolio simulation.
Its reported sealed result has only 17 trades and correlated assets. Existing
historical results are preserved, not recomputed or promoted. Real-time provider
entitlements, deployed UI behavior and operating services were not probed here.
A missing kill-switch file is still distinguishable from a corrupt one only by
its absence; removal cannot be distinguished from a fresh installation without
additional persisted initialization state.

Research signal only — no order was placed.

## Reproduce validation (offline)

```sh
uv run pytest tests/safety/test_s6_kill_switch.py tests/execution/test_deadman.py tests/paper/test_crypto_ledger.py tests/app/test_ui_charts.py --no-cov -q
uv run pytest -n 4 -m 'not serial' --no-cov -q
uv run pytest -m serial --no-cov -q
uv run ruff check src tests
uv run black --check src tests
uv run mypy
uv run lint-imports
make secrets
```

Tests use isolated temporary databases and synthetic fixtures, not the operating
DB or sealed research. Execution source edits are explanatory comments only.
