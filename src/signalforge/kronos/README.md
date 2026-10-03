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

## Eval mode (bug fix, 2026-10-03)

`from_pretrained` returns the model and tokenizer in **train mode**, and neither the
upstream predictor nor the original worker called `.eval()`. Every replay before this
fix therefore ran with dropout active (cached Kronos-small config: ffn 0.25, resid 0.25,
attention 0.1, token 0.1) and with the s2 cross-attention causally masked
(`is_causal = self.training` upstream). The worker now always puts the model and the
tokenizer in eval mode for the dashboard path, verifies that the switch took effect, and
reports the mode it ran in; the runtime rejects a result whose reported mode differs
from the requested one.

**Pre-fix replays were produced with dropout active.** That includes every `/kronos`
replay stored in the audit log before this change, the release-report AAPL runs, and
the whole 2026-10-02 skill study (`docs/research/kronos/2026-10-02/`). Their numbers are
not comparable with post-fix replays. The result now carries
`inference = {eval, T, top_p, samples}` and that block is part of the `id` digest, so
post-fix ids differ from pre-fix ids for the same input.

## Study-only inference mode

`service.study_replay(session, symbol, horizon, as_of=..., mode=...)` accepts
`mode = {"eval": bool, "T": float, "top_p": float, "samples": int, "return_paths": bool}`.
All five keys are required with exact types; `T` is bounded to [0.1, 2.0], `top_p` to
[0.1, 1.0], `samples` to 1–10 (path `i` is seeded `42 + i`). The mode is validated in the
service, again in the runtime and again inside the worker. `return_paths` adds the raw
close paths to the result. `eval: false` (train mode) exists only so a pre-registered
diagnostic can replicate the pre-fix behaviour; it is reachable only through
`study_replay`. `replay()` — the only function the web route imports — has no mode
parameter and always runs the production default (eval mode, T 1.0, top_p 0.9, three
samples). The 128 KiB output cap was not raised: 10 paths × 20 steps is a few KiB and
the upstream progress bar is now disabled.

The package neither imports TradePilot code nor decides, ranks, sizes, or executes
trades. Hermetic tests exercise local synthetic fixtures and tiny child processes;
they do not assert installed-model or dashboard validation.
