# Dashboard integration

```python
from signalforge.kronos.service import replay, runtime_status, KronosUnavailable

configuration = runtime_status()
result = replay(session, symbol="AAPL", horizon=5)  # or 20; synchronous
```

Run replay in a worker thread, not an async event loop. The parent route supplies
its own authenticated SQLAlchemy session, CSRF protection and kill-switch gate.
No provider is called, no result or settings are written, and no pending session
changes are flushed. Only persisted `massive` daily bars are queried. The selected
window must contain 128 context bars plus 5/20 held-out bars, all real, adjusted,
unflagged, and numerically valid. Today/future dates are excluded. Optional
`as_of=date(...)` chooses the latest available window ending at/before that date.
The selected window must match every XNYS session between its first and last dates;
missing sessions and weekend/holiday bars are rejected before inference. This does
not certify freshness beyond the last persisted date. Calendar spans over 730 days
are rejected to bound validation work.

`ValueError` indicates invalid symbol/horizon/as_of. `KronosUnavailable` indicates
unavailable/unsuitable history, unavailable runtime, busy inference or model failure.
`KronosError` is a compatibility alias for that same exception.

The JSON-serializable result has parallel `dates` (ISO session dates), `actual`,
`predicted`, `baseline`, `lower`, `upper` arrays. `predicted` is the mean of three
seeded paths (42–44); lower/upper are sampled extrema, not confidence intervals.
`mae` and `baseline_mae` measure close-price error. The unchanged baseline repeats
the final context close. Also returned: `ticker`, `model`, `mode`, `source`,
`generated_at`, `input_start`, `input_end`, `heldout_start`, `heldout_end`, `lookback`,
`horizon`, `samples`, `seed`, `id` (input/model/seed digest, not model-weights hash),
`notice`, `pretraining_overlap`, per-bar `provenance`, `history`, and `points`.
Points use `date`, `actual`, `predicted`, `baseline`, `low`, `high`.
Each provenance row includes its persisted `latency_category`. Overall labels are
`bar_size="1d"`, `calendar="XNYS"`, `latency_category="HISTORICAL"`, a `data_label`,
and the distinct `source_latency_categories`; this historical replay is never live.
Always display the notice and source/date ranges beside MAE. Neither error metric
is a trading recommendation or profit measure. Pretraining overlap is unknown;
current stored adjusted data may contain later vendor revisions/corporate actions.

Runtime status is configuration-only, not proof that weights are cached or inference
works. Runtime is fixed to `~/my-stack/Kronos/.venv/bin/python`; weights load locally
with HF/Transformers offline flags, no implicit HF token, and no inherited credentials.
A Python audit hook rejects network connect/DNS/sendto events (defense in depth,
not an OS sandbox for arbitrary native code). Three CPU samples use four threads.
Subprocess input is capped at 64 KiB, combined output at 128 KiB, time at 90 seconds,
and an OS lock permits one process at a time. Children are terminated/reaped on
failure. Held-out OHLCV never reaches inference; only dates do.

The package neither imports TradePilot code nor decides, ranks, sizes, or executes
trades. Hermetic tests exercise local synthetic fixtures and tiny child processes;
they do not assert installed-model or dashboard validation.
