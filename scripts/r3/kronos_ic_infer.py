"""R3 Kronos cross-sectional IC study -- step 2: batched sampling that keeps every path.

Pre-registration: docs/research/kronos/PREREGISTRATION_2026-11-10_kronos_cross_sectional_ic.md

Runs in the Kronos venv (torch) on a PRIVATE copy of the upstream model code and weights.
It never imports from ~/my-stack/Kronos, never reads or writes ~/.cache/huggingface,
never takes the production runtime lock and never touches the network or a database.
Its only inputs are ``bars.npz`` and a universe list written by ``kronos_ic_export.py``.

What is reproduced from upstream (model/kronos.py), expression for expression:
  * per-series normalisation over the look-back: float32 mean/std, (x - mean) / (std + 1e-5),
    clip to [-5, 5] (KronosPredictor.predict);
  * ``amount = volume * mean(open, high, low, close)`` when no amount is supplied;
  * calendar features minute/hour/weekday/day/month of the look-back sessions and of the
    future XNYS sessions (calc_time_stamps);
  * tokenizer.encode(half=True), decode_s1 -> sample s1 -> decode_s2 -> sample s2 with
    logits / T, upstream's own top_k_top_p_filtering, softmax, torch.multinomial
    (sample_from_logits / auto_regressive_inference);
  * tokenizer.decode(half=True) of context + generated tokens and de-normalisation
    ``z * (std + 1e-5) + mean``.
What differs, and why it does not change the distribution:
  * every sample path is kept (upstream averages them inside auto_regressive_inference);
  * each (origin, symbol, path) row owns a CPU ``torch.Generator``; ``torch.multinomial`` is
    called once per row with that generator. A row therefore draws exactly what upstream
    draws for a one-row batch seeded with the same number, and a row's draws do not depend
    on --batch-rows or on row order (``--mode g0`` records one chunk against four chunks as
    bitwise identical; the pilot origin was reproduced bitwise at 1000 and at 2500 rows per
    chunk). Across devices the logits agree to about 5e-5, so a row can differ only where
    that flips a near-tied draw;
  * the transformer reuses key/value projections of earlier positions (a KV cache) instead
    of recomputing the whole context at every step. Attention is causal and the context
    never exceeds max_context (asserted), so the logits are the same up to float rounding;
    ``--no-kv-cache`` runs upstream's decode_s1/decode_s2 unchanged and ``--mode equiv``
    measures the difference.

Seeds (recorded in every origin file together with the origin index): path seed = 42 + path
index; the row seed is the first four bytes of SHA-256 over
``kronos-ic-r3/<window>/origin/<origin index>/symbol/<symbol>/path-seed/<42 + path>``.

Look-ahead: an origin's input is cut from a view of the bars that ends at the origin, so the
property holds by construction. It is also tested from outside (``look_ahead_test``): the
input must be bit-for-bit unchanged when every bar after the origin is replaced by NaN, and an
input deliberately cut one session late must be caught. ``--mode inputs`` runs both for every
origin before a run, and run mode repeats the first for every origin it generates. Only
calendar dates, never prices, of later sessions are used.

Clock: nothing that runs the model starts between 20:00 UTC and 00:15 UTC. 20:00 UTC is this
script's own cut-off (the R3 round limit, 30 minutes before the frozen books' 20:30-00:15 UTC
collection window); ``--deadline`` can only make the stop earlier.

Provenance: the hash of this file is part of the frozen run definition, so a run directory
cannot be resumed by an edited script; every origin file records the script hash, the chunk
size and the thread count it was made with.

Exit codes of run mode: 0 complete; 2 refused; 3 error or failed check; 10 stopped at the
deadline; 11 stopped by --max-origins; 12 otherwise incomplete. A run is finished only when the
exit code is 0 and run_status.json says "complete".

Research signal only -- no order was placed.
"""

# Report prose, table headers and help strings are kept on one line.
# ruff: noqa: E501

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

SCRATCH = Path(
    "/private/tmp/claude-501/-Users-louisbrailey-Projects-signal-forge/"
    "ec635db8-8e7c-46dd-bc95-83c88a678e74/scratchpad/r3"
)
DEFAULT_KRONOS_ROOT = SCRATCH / "kronos"
DEFAULT_BARS = SCRATCH / "out/kronos-ic/bars/bars.npz"
LAST_DEV_SESSION = "2025-09-05"

# SHA-256 of the upstream files at the time the private copy was made (2026-11-10).
EXPECTED_SHA256 = {
    "src/model/__init__.py": "f8f856ca3fedadcaac97e196be23d1aeda1c3c9ffe8903d66d43ea3bcac6240c",
    "src/model/kronos.py": "0a5f90282e2039c2de0771473419715c845def154896dbd0f5747837e6241032",
    "src/model/module.py": "a07edbadc0e96804c8158c021bbc6063bb7cc43b34d7fc470d5c8ff2005a409f",
    "weights/Kronos-small/model.safetensors": "b082dfcbd8e8c142a725c8bbb99781802f38fec81210e13479effb32b3c3e020",
    "weights/Kronos-small/config.json": "5e0f6a605d5f81b5c9b559fe5cf716a1acb041c744e6f41bd05b097b7a685396",
    "weights/Kronos-Tokenizer-base/model.safetensors": "59d85f6af76a2c3b8240ea06cb21db4213b4eeca053f246b23e29cf832fc6bee",
    "weights/Kronos-Tokenizer-base/config.json": "2366e7ccfec76cbc19cf3c4c1b9c5d901be336ca1e83f2d2292c9bff381b77a2",
}

CONFIGS = {
    # Paper (arXiv 2508.02739, Appendix D): 90-day look-back, T = 0.6, top-p = 0.9, N = 10.
    "paper": {"lookback": 90, "T": 0.6, "top_p": 0.9, "top_k": 0, "paths": 10},
    # Production shadow ledger / frozen books (src/signalforge/kronos/worker.py).
    "production": {"lookback": 128, "T": 1.0, "top_p": 0.9, "top_k": 0, "paths": 3},
}
WINDOWS = {
    "test": {"first": "2024-07-01", "last": LAST_DEV_SESSION, "every": 5},
    "contrast": {"first": "2023-01-03", "last": "2024-06-14", "every": 5},
}
CLIP = 5
MAX_CONTEXT = 512
BASE_SEED = 42
PRICE_COLS = ["open", "high", "low", "close"]
FEATURES = ["open", "high", "low", "close", "volume", "amount"]
# Frozen comparison books' collection window (UTC): inference must not run inside it.
QUIET_START = (20, 30)
QUIET_END = (0, 15)
# This script's own daily cut-off (UTC): the R3 round limit, 30 minutes before the collection
# window. Nothing that runs the model is started that cannot finish before it.
CUTOFF = (20, 0)
VALIDATION_ALLOWANCE_S = 600.0  # g0 and equiv each take one to two minutes
TIER1_LIMIT_HOURS = 5.0  # pre-registered: tier 2 only if tier 1 projects past 5 hours
EXIT_COMPLETE, EXIT_REFUSED, EXIT_ERROR, EXIT_G0_FAIL = 0, 2, 3, 4
EXIT_STOPPED_DEADLINE, EXIT_STOPPED_MAX_ORIGINS, EXIT_INCOMPLETE = 10, 11, 12


# ----------------------------------------------------------------------------- utilities
def utcnow() -> datetime:
    return datetime.now(UTC)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def bars_content_sha256(path: Path) -> str:
    """SHA-256 over the arrays in bars.npz. A re-export of unchanged data gives the same value;
    the zip container itself does not, because it stores timestamps."""
    z = np.load(path, allow_pickle=False)
    h = hashlib.sha256()
    for key in sorted(z.files):
        a = np.ascontiguousarray(z[key])
        h.update(f"{key}|{a.dtype}|{a.shape}|".encode())
        h.update(a.tobytes())
    return h.hexdigest()


def atomic_write_json(path: Path, payload: object) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


class Log:
    def __init__(self, path: Path | None) -> None:
        self.path = path

    def __call__(self, msg: str) -> None:
        line = f"{utcnow().isoformat(timespec='seconds')} {msg}"
        print(line, flush=True)
        if self.path is not None:
            with self.path.open("a") as fh:
                fh.write(line + "\n")


def parse_deadline(text: str) -> datetime:
    t = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return t.astimezone(UTC)


def in_quiet_window(t: datetime) -> bool:
    hm = (t.hour, t.minute)
    return hm >= QUIET_START or hm < QUIET_END


def past_cutoff(t: datetime) -> bool:
    """True from the 20:00 UTC cut-off until the collection window has ended at 00:15 UTC."""
    hm = (t.hour, t.minute)
    return hm >= CUTOFF or hm < QUIET_END


def next_cutoff(t: datetime) -> datetime:
    start = t.replace(hour=CUTOFF[0], minute=CUTOFF[1], second=0, microsecond=0)
    return start if t <= start else start + timedelta(days=1)


def clock_gate(deadline_text: str, now: datetime, allowance_s: float | None):
    """Start check shared by every mode that runs the model.

    Returns (stop_at, None), or (None, reason) when the mode must not start. ``allowance_s``
    is the time the whole mode needs (validation modes); run mode passes None and applies its
    own allowance origin by origin.
    """
    if past_cutoff(now):
        where = (
            "inside the frozen books' 20:30-00:15 UTC collection window"
            if in_quiet_window(now)
            else "after this script's 20:00 UTC cut-off (the collection window starts at 20:30 UTC)"
        )
        return None, f"{now.isoformat(timespec='seconds')} is {where}"
    stop_at = min(parse_deadline(deadline_text), next_cutoff(now))
    if allowance_s is not None and now + timedelta(seconds=allowance_s) > stop_at:
        return None, (
            f"needs up to {allowance_s:.0f}s and would pass {stop_at.isoformat(timespec='seconds')}"
        )
    return stop_at, None


def seed32(label: str) -> int:
    return int.from_bytes(hashlib.sha256(label.encode()).digest()[:4], "big")


def row_seeds(window: str, origin_index: int, symbols: list[str], n_paths: int) -> np.ndarray:
    """One 32-bit generator seed per (symbol, path); unique within the origin."""
    out = np.zeros((len(symbols), n_paths), dtype=np.int64)
    seen: set[int] = set()
    for i, sym in enumerate(symbols):
        for p in range(n_paths):
            base = f"kronos-ic-r3/{window}/origin/{origin_index}/symbol/{sym}/path-seed/{BASE_SEED + p}"
            s, salt = seed32(base), 0
            while (
                s in seen
            ):  # 32-bit collisions inside one cross-section are re-drawn deterministically
                salt += 1
                s = seed32(f"{base}/salt/{salt}")
            seen.add(s)
            out[i, p] = s
    return out


# ------------------------------------------------------------------------------- loading
def verify_private_copy(root: Path) -> dict[str, str]:
    forbidden = ("/my-stack/Kronos", "/.cache/huggingface")
    if any(f in str(root.resolve()) for f in forbidden):
        raise SystemExit("Refusing to run from the upstream checkout or the Hugging Face cache")
    hashes = {}
    for rel, want in EXPECTED_SHA256.items():
        got = sha256_file(root / rel)
        if got != want:
            raise SystemExit(f"Identity check failed: {rel} sha256 {got} != expected {want}")
        hashes[rel] = got
    return hashes


def load_models(root: Path):
    """Import the private copy of upstream and load both checkpoints in eval mode (CPU)."""
    import torch

    sys.path.insert(0, str(root / "src"))
    import model as up_pkg  # private copy of upstream model/
    import model.kronos as up

    if not str(Path(up_pkg.__file__).resolve()).startswith(str((root / "src").resolve())):
        raise SystemExit(
            "Identity check failed: model package was not imported from the private copy"
        )
    tok = up.KronosTokenizer.from_pretrained(
        str(root / "weights/Kronos-Tokenizer-base"), local_files_only=True
    )
    mdl = up.Kronos.from_pretrained(str(root / "weights/Kronos-small"), local_files_only=True)
    # from_pretrained loads non-strictly; verify the checkpoint covers every parameter.
    from safetensors import safe_open

    key_report = {}
    for name, module, rel in (
        ("tokenizer", tok, "weights/Kronos-Tokenizer-base"),
        ("model", mdl, "weights/Kronos-small"),
    ):
        with safe_open(str(root / rel / "model.safetensors"), framework="pt") as fh:
            file_keys = set(fh.keys())
        state_keys = set(module.state_dict().keys())
        key_report[name] = {
            "missing_in_file": sorted(state_keys - file_keys),
            "unexpected_in_file": sorted(file_keys - state_keys),
        }
        param_keys = {k for k, _ in module.named_parameters()}
        if param_keys - file_keys:
            raise SystemExit(
                f"Identity check failed: {name} parameters absent from checkpoint: {sorted(param_keys - file_keys)[:5]}"
            )
    tok.eval()
    mdl.eval()
    if tok.training or mdl.training:
        raise SystemExit("Model is not in eval mode")
    torch.set_grad_enabled(False)
    return up, tok, mdl, key_report


def to_device(module, device):
    """Move a module and drop upstream's rotary cos/sin caches (plain attributes, not buffers)."""
    module = module.to(device)
    for sub in module.modules():
        if hasattr(sub, "seq_len_cached"):
            sub.seq_len_cached = None
            sub.cos_cached = None
            sub.sin_cached = None
    return module


def load_bars(path: Path) -> dict:
    z = np.load(path, allow_pickle=False)
    bars = {k: z[k] for k in z.files}
    dates = [str(d) for d in bars["dates"]]
    if max(dates) > LAST_DEV_SESSION or dates != sorted(dates) or len(set(dates)) != len(dates):
        raise SystemExit(
            "Hard-rule violation: bars file is unsorted or contains a date after 2025-09-05"
        )
    bars["dates"] = dates
    bars["symbols"] = [str(s) for s in bars["symbols"]]
    return bars


def window_origins(dates: list[str], window: str) -> list[int]:
    spec = WINDOWS[window]
    if spec["first"] not in dates:
        raise SystemExit(
            f"Identity check failed: {spec['first']} is not a session in the bars file"
        )
    i0 = dates.index(spec["first"])
    return [i for i in range(i0, len(dates), spec["every"]) if dates[i] <= spec["last"]]


def origin_inputs(up, bars: dict, sym_cols: list[int], oi: int, lookback: int):
    """Normalised look-back for every series, built only from bars dated <= the origin.

    That holds by construction: the dates and every feature array are cut to ``[: oi + 1]``
    before anything else reads them. A slice cannot be checked from inside the function that
    takes it, so the property is tested from outside by ``look_ahead_test``.
    """
    origin_date = bars["dates"][oi]
    visible_dates = bars["dates"][: oi + 1]  # nothing after the origin is visible below
    if len(visible_dates) < lookback:
        raise SystemExit(f"Not enough history before {origin_date}")
    x_dates = visible_dates[-lookback:]
    view = {f: bars[f][: oi + 1] for f in FEATURES}
    xs, means, stds = [], [], []
    last_close = np.empty(len(sym_cols), dtype=np.float64)
    for n, j in enumerate(sym_cols):
        frame = pd.DataFrame(
            {f: view[f][-lookback:, j] for f in ("open", "high", "low", "close", "volume")}
        )
        # Upstream KronosPredictor.predict, verbatim from here to the clip.
        frame["amount"] = frame["volume"] * frame[PRICE_COLS].mean(axis=1)
        if not np.array_equal(frame["amount"].to_numpy(), view["amount"][-lookback:, j]):
            raise SystemExit("Identity check failed: exported amount differs from upstream's fill")
        if frame[FEATURES].isnull().values.any():
            raise SystemExit(f"NaN in the look-back of {bars['symbols'][j]} at {origin_date}")
        x = frame[FEATURES].values.astype(np.float32)
        x_mean, x_std = np.mean(x, axis=0), np.std(x, axis=0)
        x = (x - x_mean) / (x_std + 1e-5)
        x = np.clip(x, -CLIP, CLIP)
        xs.append(x)
        means.append(x_mean)
        stds.append(x_std)
        last_close[n] = view["close"][-1, j]
    x_stamp = up.calc_time_stamps(pd.Series(pd.to_datetime(x_dates))).values.astype(np.float32)
    return (
        np.stack(xs).astype(np.float32),
        np.stack(means),
        np.stack(stds),
        x_stamp,
        x_dates,
        last_close,
    )


def poisoned_after(bars: dict, oi: int) -> dict:
    """A copy of the bars in which every value dated after bar index ``oi`` is NaN."""
    out = dict(bars)
    for f in FEATURES:
        a = np.array(bars[f], dtype=np.float64, copy=True)
        a[oi + 1 :] = np.nan
        out[f] = a
    return out


def same_inputs(a: tuple, b: tuple) -> bool:
    return len(a) == len(b) and all(
        np.array_equal(np.asarray(x), np.asarray(y)) for x, y in zip(a, b, strict=True)
    )


def look_ahead_test(up, bars: dict, sym_cols: list[int], oi: int, lookback: int, built) -> bool:
    """True if the inputs of origin ``oi`` are bit-for-bit unchanged when every bar after the
    origin is destroyed. A builder that read any later price would return NaN or stop."""
    try:
        again = origin_inputs(up, poisoned_after(bars, oi), sym_cols, oi, lookback)
    except SystemExit:
        return False
    return same_inputs(built, again)


def look_ahead_negative_control(up, bars: dict, sym_cols: list[int], oi: int, lookback: int, built):
    """The test above must be able to fail: an input cut one session late (it includes bar
    oi + 1) has to be caught. Returns True if it was caught, None if there is no later bar."""
    if oi + 1 >= len(bars["dates"]):
        return None
    try:
        leaky = origin_inputs(up, poisoned_after(bars, oi), sym_cols, oi + 1, lookback)
    except SystemExit:
        return True
    return not same_inputs(built, leaky)


def future_stamps(up, bars: dict, oi: int, steps: int):
    """Calendar features of the next XNYS sessions. Dates only; all are <= 2025-09-05."""
    y_dates = bars["dates"][oi + 1 : oi + 1 + steps]
    if len(y_dates) != steps or max(y_dates) > LAST_DEV_SESSION:
        raise SystemExit("Hard-rule violation: a future session after 2025-09-05 was requested")
    y_stamp = up.calc_time_stamps(pd.Series(pd.to_datetime(y_dates))).values.astype(np.float32)
    return y_stamp, y_dates


# -------------------------------------------------------------------------------- sampler
def filtered_probs(up, logits, T: float, top_k: int, top_p: float):
    """sample_from_logits up to (not including) the multinomial draw; CPU tensors."""
    import torch.nn.functional as F

    logits = logits / T
    if top_k is not None or top_p is not None:  # noqa: SIM102 - upstream's structure, kept verbatim
        if top_k > 0 or top_p < 1.0:
            logits = up.top_k_top_p_filtering(logits, top_k=top_k, top_p=top_p)
    return F.softmax(logits, dim=-1)


def draw_rows(probs, gens):
    """torch.multinomial(probs, 1) row by row, each row with its own generator."""
    import torch

    out = torch.empty((probs.shape[0], 1), dtype=torch.long)
    for r, g in enumerate(gens):
        out[r] = torch.multinomial(probs[r : r + 1], num_samples=1, generator=g)
    return out


def _rot(x):
    import torch

    x1, x2 = x.chunk(2, dim=-1)
    return torch.cat((-x2, x1), dim=-1)


class CachedDecoder:
    """decode_s1 / decode_s2 of upstream Kronos with cached keys and values.

    Position p of the transformer input depends only on positions <= p (causal attention,
    rotary phase is a function of the absolute position), so the keys/values and the final
    hidden state of earlier positions are reused rather than recomputed.
    """

    def __init__(self, mdl, batch: int, max_len: int, device) -> None:
        import torch

        self.mdl = mdl
        self.B = batch
        self.len = 0
        blocks = list(mdl.transformer)
        a0 = blocks[0].self_attn
        self.H, self.hd, self.d = a0.n_heads, a0.head_dim, mdl.d_model
        self.K = [torch.empty((batch, self.H, max_len, self.hd), device=device) for _ in blocks]
        self.V = [torch.empty((batch, self.H, max_len, self.hd), device=device) for _ in blocks]
        self.ctx = torch.empty((batch, max_len, self.d), device=device)
        ca = mdl.dep_layer.cross_attn
        self.cH, self.chd = ca.n_heads, ca.head_dim
        self.cK = torch.empty((batch, self.cH, max_len, self.chd), device=device)
        self.cV = torch.empty((batch, self.cH, max_len, self.chd), device=device)
        self.cos, self.sin = [], []
        for blk in blocks:
            inv_freq = blk.self_attn.rotary.inv_freq
            t = torch.arange(max_len, device=device).type_as(inv_freq)
            freqs = torch.einsum("i,j->ij", t, inv_freq)
            emb = torch.cat((freqs, freqs), dim=-1)
            self.cos.append(emb.cos()[None, None, :, :])
            self.sin.append(emb.sin()[None, None, :, :])

    def extend(self, s1_ids, s2_ids, time_emb):
        """Append positions [len, len + Tn); returns s1 logits for the next position."""
        import torch.nn.functional as F

        mdl = self.mdl
        B, Tn = s1_ids.shape
        p0, p1 = self.len, self.len + Tn
        if p0 > 0 and Tn != 1:
            raise ValueError("after the first call positions are appended one at a time")
        x = mdl.embedding([s1_ids, s2_ids]) + time_emb
        x = mdl.token_drop(x)
        for li, blk in enumerate(mdl.transformer):
            a = blk.self_attn
            h = blk.norm1(x)
            q = a.q_proj(h).view(B, Tn, self.H, self.hd).transpose(1, 2)
            k = a.k_proj(h).view(B, Tn, self.H, self.hd).transpose(1, 2)
            v = a.v_proj(h).view(B, Tn, self.H, self.hd).transpose(1, 2)
            cos, sin = self.cos[li][:, :, p0:p1], self.sin[li][:, :, p0:p1]
            q = (q * cos) + (_rot(q) * sin)
            k = (k * cos) + (_rot(k) * sin)
            self.K[li][:, :, p0:p1] = k
            self.V[li][:, :, p0:p1] = v
            if p0 == 0:
                o = F.scaled_dot_product_attention(
                    q, k, v, attn_mask=None, dropout_p=0.0, is_causal=True
                )
            else:  # one new query; every cached key is at or before its position
                o = F.scaled_dot_product_attention(q, self.K[li][:, :, :p1], self.V[li][:, :, :p1])
            o = o.transpose(1, 2).contiguous().view(B, Tn, self.d)
            x = x + a.resid_dropout(a.out_proj(o))
            x = x + blk.ffn(blk.norm2(x))
        ctx = mdl.norm(x)
        self.ctx[:, p0:p1] = ctx
        ca = mdl.dep_layer.cross_attn
        self.cK[:, :, p0:p1] = ca.k_proj(ctx).view(B, Tn, self.cH, self.chd).transpose(1, 2)
        self.cV[:, :, p0:p1] = ca.v_proj(ctx).view(B, Tn, self.cH, self.chd).transpose(1, 2)
        self.len = p1
        return mdl.head(ctx[:, -1:, :])[:, -1, :]

    def s2_logits(self, s1_sample):
        """decode_s2 for the last position. Upstream's rotary sees a query of length 1, so
        its phase is cos 0 = 1, sin 0 = 0 for the query and (by broadcast) every key."""
        import torch.nn.functional as F

        mdl = self.mdl
        ca = mdl.dep_layer.cross_attn
        B = s1_sample.shape[0]
        sib = mdl.embedding.emb_s1(s1_sample)  # [B, 1, d]
        q = ca.q_proj(sib).view(B, 1, self.cH, self.chd).transpose(1, 2)
        o = F.scaled_dot_product_attention(q, self.cK[:, :, : self.len], self.cV[:, :, : self.len])
        o = o.transpose(1, 2).contiguous().view(B, 1, self.d)
        attn_out = ca.resid_dropout(ca.out_proj(o))
        x2 = mdl.dep_layer.norm(self.ctx[:, self.len - 1 : self.len] + attn_out)
        return mdl.head.cond_forward(x2)[:, -1, :]


def generate_chunk(
    up,
    tok,
    mdl,
    x_norm,
    stamp,
    n_paths,
    steps,
    cfg,
    seeds,
    device,
    *,
    kv_cache=True,
    forced=None,
    collect=False,
):
    """Autoregressive sampling for one chunk of series.

    x_norm [S, L, 6] float32 (normalised, clipped); stamp [L + steps, 5] float32;
    seeds [S, n_paths] ints. Rows are ordered (series, path) as in upstream's
    ``x.unsqueeze(1).repeat(1, sample_count, 1, 1).reshape(...)``.
    Returns z [S, n_paths, steps, 6] in normalised space, tokens, optional per-step logits.
    """
    import torch

    S, L, _ = x_norm.shape
    B = S * n_paths
    total = L + steps
    if total > MAX_CONTEXT:
        raise SystemExit(
            "look-back + steps exceeds max_context; the sliding buffer is not implemented"
        )
    x = torch.from_numpy(x_norm).to(device)
    x = torch.clip(x, -CLIP, CLIP)
    tokens = tok.encode(x, half=True)
    pre = tokens[0].repeat_interleave(n_paths, dim=0)  # [B, L]
    post = tokens[1].repeat_interleave(n_paths, dim=0)
    full_stamp = torch.from_numpy(stamp).to(device).unsqueeze(0)  # [1, L + steps, 5]
    gens = None
    if forced is None:
        gens = []
        for s in np.asarray(seeds).reshape(-1):
            g = torch.Generator(device="cpu")
            g.manual_seed(int(s))
            gens.append(g)
    gen_pre = torch.empty((B, steps), dtype=pre.dtype, device=device)
    gen_post = torch.empty((B, steps), dtype=post.dtype, device=device)
    log1, log2 = [], []
    dec = CachedDecoder(mdl, B, total, device) if kv_cache else None
    time_emb_all = (
        mdl.time_emb(full_stamp) if kv_cache else None
    )  # [1, L + steps, d], same for every row
    for i in range(steps):
        cur = L + i
        if kv_cache:
            if i == 0:
                s1_logits = dec.extend(pre, post, time_emb_all[:, :L])
            else:
                s1_logits = dec.extend(
                    gen_pre[:, i - 1 : i], gen_post[:, i - 1 : i], time_emb_all[:, cur - 1 : cur]
                )
        else:  # upstream, unchanged: recompute the whole context
            in_pre = torch.cat([pre, gen_pre[:, :i]], dim=1)
            in_post = torch.cat([post, gen_post[:, :i]], dim=1)
            cur_stamp = full_stamp[:, :cur, :].expand(B, -1, -1).contiguous()
            s1_all, context = mdl.decode_s1(in_pre, in_post, cur_stamp)
            s1_logits = s1_all[:, -1, :]
        s1_cpu = s1_logits.to("cpu")
        if forced is None:
            sample_pre = draw_rows(
                filtered_probs(up, s1_cpu.clone(), cfg["T"], cfg["top_k"], cfg["top_p"]), gens
            )
        else:
            sample_pre = forced[0][:, i : i + 1].to("cpu")
        sample_pre_dev = sample_pre.to(device)
        if kv_cache:
            s2_logits = dec.s2_logits(sample_pre_dev)
        else:
            s2_logits = mdl.decode_s2(context, sample_pre_dev)[:, -1, :]
        s2_cpu = s2_logits.to("cpu")
        if forced is None:
            sample_post = draw_rows(
                filtered_probs(up, s2_cpu.clone(), cfg["T"], cfg["top_k"], cfg["top_p"]), gens
            )
        else:
            sample_post = forced[1][:, i : i + 1].to("cpu")
        gen_pre[:, i] = sample_pre_dev.squeeze(-1)
        gen_post[:, i] = sample_post.to(device).squeeze(-1)
        if collect:
            log1.append(s1_cpu)
            log2.append(s2_cpu)
    full_pre = torch.cat([pre, gen_pre], dim=1)
    full_post = torch.cat([post, gen_post], dim=1)
    z = tok.decode([full_pre.contiguous(), full_post.contiguous()], half=True)
    z = z[:, -steps:, :].reshape(S, n_paths, steps, z.size(-1)).to("cpu").numpy()
    out = {
        "z": z,
        "pre": gen_pre.to("cpu"),
        "post": gen_post.to("cpu"),
        "ctx_pre": tokens[0].to("cpu"),
        "ctx_post": tokens[1].to("cpu"),
    }
    if collect:
        out["s1_logits"] = torch.stack(log1, dim=1)
        out["s2_logits"] = torch.stack(log2, dim=1)
    return out


def sample_origin(
    up,
    tok,
    mdl,
    x_norm,
    means,
    stds,
    stamp,
    n_paths,
    steps,
    cfg,
    seeds,
    device,
    batch_rows,
    kv_cache,
):
    """All series of one origin, chunked so that a chunk holds at most batch_rows rows."""
    import torch

    S = x_norm.shape[0]
    per_chunk = max(1, batch_rows // n_paths)
    preds = np.empty((S, n_paths, steps, len(FEATURES)), dtype=np.float32)
    for a in range(0, S, per_chunk):
        b = min(S, a + per_chunk)
        out = generate_chunk(
            up,
            tok,
            mdl,
            x_norm[a:b],
            stamp,
            n_paths,
            steps,
            cfg,
            seeds[a:b],
            device,
            kv_cache=kv_cache,
        )
        # Upstream: preds * (x_std + 1e-5) + x_mean (float32), here applied to every path.
        preds[a:b] = out["z"] * (stds[a:b, None, None, :] + 1e-5) + means[a:b, None, None, :]
        del out
        if device == "mps":
            torch.mps.empty_cache()
    return preds


# ------------------------------------------------------------------------------ run mode
def run(args, log: Log) -> int:
    import torch

    cfg = dict(CONFIGS[args.config])
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    now = utcnow()
    stop_at, refusal = clock_gate(args.deadline, now, None)
    if stop_at is None:
        log(f"REFUSED: {refusal}")
        return EXIT_REFUSED
    if (args.config, args.window) != ("paper", "test"):
        # Pre-registered order: the secondary configuration and the contrast window run only
        # after the primary (paper configuration, test window) has finished.
        ok = False
        if args.primary_dir and (Path(args.primary_dir) / "run_status.json").exists():
            pdir = Path(args.primary_dir)
            st = json.loads((pdir / "run_status.json").read_text())
            pm = json.loads((pdir / "run_manifest.json").read_text())
            ok = (
                (pm.get("config_name"), pm.get("window")) == ("paper", "test")
                and st.get("status") == "complete"
                and st.get("origins_present") == st.get("origins_expected")
                and len(list(pdir.glob("origin_*.npz"))) == st.get("origins_expected")
                # all three runs must come from the same version of this file
                and pm.get("script_sha256") == sha256_file(Path(__file__))
            )
        if not ok:
            log(
                "REFUSED: the production configuration and the contrast window run only after the "
                "primary run (paper, test) is complete and was made by this version of the script; "
                "pass its directory as --primary-dir"
            )
            return EXIT_REFUSED
    root = Path(args.kronos_root)
    hashes = verify_private_copy(root)
    bars = load_bars(Path(args.bars))
    universe = json.loads(Path(args.universe).read_text())
    symbols = list(universe["symbols"])
    col = {s: j for j, s in enumerate(bars["symbols"])}
    sym_cols = [col[s] for s in symbols]
    origins = window_origins(bars["dates"], args.window)
    n_dates = len(bars["dates"])
    plan = []
    for k, oi in enumerate(origins):
        steps_o = min(
            args.steps, n_dates - 1 - oi
        )  # sessions after the origin that are <= 2025-09-05
        plan.append(
            {"origin_index": k, "date": bars["dates"][oi], "bar_index": oi, "steps": steps_o}
        )
    torch.set_num_threads(args.threads)
    up, tok, mdl, key_report = load_models(root)
    device = args.device
    tok = to_device(tok, device)
    mdl = to_device(mdl, device)
    manifest = {
        "study": "kronos-cross-sectional-ic-2026-11-10",
        "config_name": args.config,
        "config": cfg,
        "clip": CLIP,
        "max_context": MAX_CONTEXT,
        "eval_mode": True,
        "window": args.window,
        "window_spec": WINDOWS[args.window],
        "steps_requested": args.steps,
        "universe_file": str(Path(args.universe).resolve()),
        "universe_sha256": sha256_file(Path(args.universe)),
        "n_symbols": len(symbols),
        "bars_file": str(Path(args.bars).resolve()),
        "bars_content_sha256": bars_content_sha256(Path(args.bars)),
        "device": device,
        "kv_cache": not args.no_kv_cache,
        "batch_rows": args.batch_rows,
        "threads": args.threads,
        "torch": torch.__version__,
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "python": sys.version.split()[0],
        "file_sha256": hashes,
        "checkpoint_key_report": key_report,
        "batch_rows_threads_note": "values of the latest start; each origin file records its own",
        "seeds": {
            "path_seed": "42 + path index",
            "origin_index": "recorded in every origin file; it enters every row seed",
            "row_seed": "first 4 bytes of sha256('kronos-ic-r3/<window>/origin/<origin index>/symbol/<symbol>/path-seed/<42 + path index>'), salted on a collision inside the origin",
            "sampler": "torch.multinomial(probs[row], 1, generator=torch.Generator().manual_seed(row_seed)) on CPU",
        },
        "origins": plan,
        "n_origins": len(plan),
        "script_sha256": sha256_file(Path(__file__)),
        "primary_dir": str(Path(args.primary_dir).resolve()) if args.primary_dir else None,
    }
    man_path = out_dir / "run_manifest.json"
    if man_path.exists():
        old = json.loads(man_path.read_text())
        # The script hash and the library versions are part of the run definition: a directory
        # started by one version of this file cannot be resumed by another.
        frozen_keys = (
            "config_name",
            "config",
            "window",
            "steps_requested",
            "universe_sha256",
            "bars_content_sha256",
            "file_sha256",
            "kv_cache",
            "device",
            "origins",
            "script_sha256",
            "torch",
            "numpy",
            "pandas",
        )
        diff = [k for k in frozen_keys if old.get(k) != manifest[k]]
        if diff:
            log(
                f"REFUSED: {man_path} was written by a different run definition (differs in {diff})"
            )
            return EXIT_REFUSED
        manifest["first_started_utc"] = old.get("first_started_utc")
    manifest.setdefault("first_started_utc", now.isoformat(timespec="seconds"))
    manifest["last_started_utc"] = now.isoformat(timespec="seconds")
    atomic_write_json(man_path, manifest)
    log(
        f"START config={args.config} window={args.window} device={device} kv_cache={not args.no_kv_cache} "
        f"symbols={len(symbols)} paths={cfg['paths']} steps={args.steps} origins={len(plan)} "
        f"batch_rows={args.batch_rows} stop_at={stop_at.isoformat(timespec='seconds')}"
    )
    durations: list[float] = []
    done = skipped = 0
    status = "complete"
    for item in plan:
        k, oi, steps_o = item["origin_index"], item["bar_index"], item["steps"]
        path = out_dir / f"origin_{k:03d}_{item['date']}.npz"
        if steps_o <= 0:
            log(
                f"origin {k:03d} {item['date']}: no later session on or before {LAST_DEV_SESSION}; nothing to forecast"
            )
            continue
        if path.exists():
            skipped += 1
            continue
        if args.max_origins is not None and done >= args.max_origins:
            status = "stopped_max_origins"
            break
        est = (max(durations) * 1.25 + 15.0) if durations else float(args.est_seconds)
        now = utcnow()
        if now + timedelta(seconds=est) > stop_at:
            status = "stopped_deadline"
            log(
                f"DEADLINE: origin {k:03d} needs ~{est:.0f}s and would pass {stop_at.isoformat(timespec='seconds')}; stopping cleanly"
            )
            break
        t0 = time.time()
        built = origin_inputs(up, bars, sym_cols, oi, cfg["lookback"])
        x_norm, means, stds, x_stamp, x_dates, last_close = built
        if not look_ahead_test(up, bars, sym_cols, oi, cfg["lookback"], built):
            log(
                f"ERROR: look-ahead test failed at origin {k:03d}: the inputs change when later bars are destroyed"
            )
            return EXIT_ERROR
        y_stamp, y_dates = future_stamps(up, bars, oi, steps_o)
        stamp = np.concatenate([x_stamp, y_stamp], axis=0)
        seeds = row_seeds(args.window, k, symbols, cfg["paths"])
        preds = sample_origin(
            up,
            tok,
            mdl,
            x_norm,
            means,
            stds,
            stamp,
            cfg["paths"],
            steps_o,
            cfg,
            seeds,
            device,
            args.batch_rows,
            not args.no_kv_cache,
        )
        if not np.isfinite(preds).all():
            log(f"ERROR: non-finite prediction at origin {k:03d}")
            return EXIT_ERROR
        secs = time.time() - t0
        meta = {
            "config_name": args.config,
            "config": cfg,
            "window": args.window,
            "origin_index": k,
            "origin_date": item["date"],
            "steps": steps_o,
            "future_dates": y_dates,
            "lookback_first": x_dates[0],
            "lookback_last": x_dates[-1],
            "look_ahead_test": "inputs bit-for-bit unchanged with every later bar set to NaN",
            "path_seeds": [BASE_SEED + p for p in range(cfg["paths"])],
            "device": device,
            "kv_cache": not args.no_kv_cache,
            "batch_rows": args.batch_rows,
            "threads": args.threads,
            "seconds": round(secs, 3),
            "completed_utc": utcnow().isoformat(timespec="seconds"),
            "universe_sha256": manifest["universe_sha256"],
            "bars_content_sha256": manifest["bars_content_sha256"],
            "script_sha256": manifest["script_sha256"],
            "torch": manifest["torch"],
        }
        tmp = out_dir / f".tmp_origin_{k:03d}.npz"
        with tmp.open("wb") as fh:
            np.savez_compressed(
                fh,
                meta=np.array(json.dumps(meta, sort_keys=True)),
                symbols=np.array(symbols),
                pred_close=preds[..., 3],
                pred_high=preds[..., 1],
                pred_low=preds[..., 2],
                last_close=last_close,
                row_seeds=seeds,
            )
        tmp.replace(path)
        durations.append(secs)
        done += 1
        remaining = sum(
            1
            for it in plan
            if it["steps"] > 0
            and not (out_dir / f"origin_{it['origin_index']:03d}_{it['date']}.npz").exists()
        )
        log(
            f"origin {k:03d} {item['date']} steps={steps_o} rows={len(symbols) * cfg['paths']} "
            f"{secs:.1f}s done={done} skipped={skipped} remaining={remaining} "
            f"eta_min={remaining * float(np.mean(durations)) / 60:.1f}"
        )
    expected = sum(1 for it in plan if it["steps"] > 0)
    present = sum(
        1
        for it in plan
        if it["steps"] > 0
        and (out_dir / f"origin_{it['origin_index']:03d}_{it['date']}.npz").exists()
    )
    if status == "complete" and present != expected:
        status = "incomplete"
    if present == expected:
        status = "complete"
    exit_code = {
        "complete": EXIT_COMPLETE,
        "stopped_deadline": EXIT_STOPPED_DEADLINE,
        "stopped_max_origins": EXIT_STOPPED_MAX_ORIGINS,
    }.get(status, EXIT_INCOMPLETE)
    summary = {
        "status": status,
        "exit_code": exit_code,
        "origins_expected": expected,
        "origins_present": present,
        "origins_done_this_run": done,
        "seconds_per_origin_mean": float(np.mean(durations)) if durations else None,
        "seconds_per_origin_max": float(np.max(durations)) if durations else None,
        "script_sha256": manifest["script_sha256"],
        "finished_utc": utcnow().isoformat(timespec="seconds"),
    }
    atomic_write_json(out_dir / "run_status.json", summary)
    log(f"END {json.dumps(summary, sort_keys=True)}")
    return exit_code


# ----------------------------------------------------------------------- validation modes
def _first_origin_inputs(up, bars, symbols, window, lookback, steps):
    col = {s: j for j, s in enumerate(bars["symbols"])}
    oi = window_origins(bars["dates"], window)[0]
    x_norm, means, stds, x_stamp, x_dates, last_close = origin_inputs(
        up, bars, [col[s] for s in symbols], oi, lookback
    )
    y_stamp, y_dates = future_stamps(up, bars, oi, steps)
    return oi, x_norm, means, stds, x_stamp, x_dates, y_stamp, y_dates, last_close


def mode_g0(args, log: Log) -> int:
    """Pre-registered device check: 32 series, CPU vs accelerator, first-step probabilities."""
    import copy

    import torch
    import torch.nn.functional as F

    _stop_at, refusal = clock_gate(args.deadline, utcnow(), VALIDATION_ALLOWANCE_S)
    if refusal:
        log(f"REFUSED: {refusal}")
        return EXIT_REFUSED
    torch.set_num_threads(args.threads)
    root = Path(args.kronos_root)
    verify_private_copy(root)
    bars = load_bars(Path(args.bars))
    symbols = list(json.loads(Path(args.universe).read_text())["symbols"])[:32]
    up, tok, mdl, _ = load_models(root)
    cfg = dict(CONFIGS[args.config])
    steps = args.steps
    oi, x_norm, means, stds, x_stamp, _x_dates, y_stamp, _y_dates, _ = _first_origin_inputs(
        up, bars, symbols, args.window, cfg["lookback"], steps
    )
    stamp = np.concatenate([x_stamp, y_stamp], axis=0)
    seeds = row_seeds(args.window, 0, symbols, 1)
    tok_d, mdl_d = (
        to_device(copy.deepcopy(tok), args.device),
        to_device(copy.deepcopy(mdl), args.device),
    )
    # Reference: CPU, upstream decode_s1/decode_s2 unchanged; its sampled tokens are then forced on every other arm.
    ref = generate_chunk(
        up, tok, mdl, x_norm, stamp, 1, steps, cfg, seeds, "cpu", kv_cache=False, collect=True
    )
    forced = (ref["pre"], ref["post"])
    res = {}
    runs = {
        "cpu_kv_cache": generate_chunk(
            up,
            tok,
            mdl,
            x_norm,
            stamp,
            1,
            steps,
            cfg,
            seeds,
            "cpu",
            kv_cache=True,
            forced=forced,
            collect=True,
        )
    }
    if args.device != "cpu":
        runs[f"{args.device}_upstream"] = generate_chunk(
            up,
            tok_d,
            mdl_d,
            x_norm,
            stamp,
            1,
            steps,
            cfg,
            seeds,
            args.device,
            kv_cache=False,
            forced=forced,
            collect=True,
        )
        runs[f"{args.device}_kv_cache"] = generate_chunk(
            up,
            tok_d,
            mdl_d,
            x_norm,
            stamp,
            1,
            steps,
            cfg,
            seeds,
            args.device,
            kv_cache=True,
            forced=forced,
            collect=True,
        )

    def prob_sets(lg):
        return {
            "softmax_T1": F.softmax(lg, dim=-1),
            "softmax_T": F.softmax(lg / cfg["T"], dim=-1),
            "sampling_T_top_p": filtered_probs(
                up, lg.clone(), cfg["T"], cfg["top_k"], cfg["top_p"]
            ),
        }

    for name, r in runs.items():
        entry = {}
        for head in ("s1_logits", "s2_logits"):
            a, b = ref[head], r[head]
            first = {
                k: float((prob_sets(a[:, 0])[k] - prob_sets(b[:, 0])[k]).abs().max())
                for k in prob_sets(a[:, 0])
            }
            allsteps = {}
            for k in ("softmax_T1", "softmax_T", "sampling_T_top_p"):
                allsteps[k] = float(
                    max(
                        (prob_sets(a[:, i])[k] - prob_sets(b[:, i])[k]).abs().max()
                        for i in range(steps)
                    )
                )
            entry[head] = {
                "first_step_max_abs_prob_diff": first,
                "all_steps_max_abs_prob_diff": allsteps,
                "first_step_max_abs_logit_diff": float((a[:, 0] - b[:, 0]).abs().max()),
                "all_steps_max_abs_logit_diff": float((a - b).abs().max()),
            }
        entry["look_back_tokens_identical_to_reference"] = bool(
            (ref["ctx_pre"] == r["ctx_pre"]).all() and (ref["ctx_post"] == r["ctx_post"]).all()
        )
        entry["decode_max_abs_diff_normalised"] = float(np.abs(ref["z"] - r["z"]).max())
        res[name] = entry
    # Free-running check with the run's own seeds: CPU versus the accelerator, and one chunk
    # versus four chunks on the accelerator.
    n_paths = cfg["paths"]
    seeds_p = row_seeds(args.window, 0, symbols, n_paths)
    big = len(symbols) * n_paths
    free_cpu = sample_origin(
        up, tok, mdl, x_norm, means, stds, stamp, n_paths, steps, cfg, seeds_p, "cpu", big, True
    )[..., 3]
    free_dev = sample_origin(
        up,
        tok_d,
        mdl_d,
        x_norm,
        means,
        stds,
        stamp,
        n_paths,
        steps,
        cfg,
        seeds_p,
        args.device,
        big,
        True,
    )[..., 3]
    free_chunked = sample_origin(
        up,
        tok_d,
        mdl_d,
        x_norm,
        means,
        stds,
        stamp,
        n_paths,
        steps,
        cfg,
        seeds_p,
        args.device,
        big // 4,
        True,
    )[..., 3]
    same = np.isclose(free_cpu, free_dev, rtol=1e-4, atol=0.0).all(axis=-1)
    free_running = {
        "series": len(symbols),
        "paths_total": int(same.size),
        "paths_identical_cpu_vs_device": int(same.sum()),
        "max_rel_diff_close_identical_paths": float(
            (np.abs(free_cpu - free_dev) / free_cpu)[same].max()
        ),
        "bitwise_identical_one_chunk_vs_four_chunks": bool(np.array_equal(free_dev, free_chunked)),
    }
    acc = res.get(f"{args.device}_kv_cache", res["cpu_kv_cache"])
    worst_first = max(
        max(
            acc[h]["first_step_max_abs_prob_diff"]["softmax_T1"],
            acc[h]["first_step_max_abs_prob_diff"]["softmax_T"],
        )
        for h in ("s1_logits", "s2_logits")
    )
    report = {
        "check": "G0 device check (pre-registered): first-step class probabilities, CPU vs accelerator, 32 series",
        "config": args.config,
        "window": args.window,
        "origin_date": bars["dates"][oi],
        "n_series": len(symbols),
        "steps_compared": steps,
        "device": args.device,
        "threshold": 1e-3,
        "script_sha256": sha256_file(Path(__file__)),
        "reference": "CPU, upstream decode_s1/decode_s2 (no KV cache); the reference's sampled tokens are forced on every arm",
        "arms": res,
        "free_running": free_running,
        "g0_max_first_step_class_prob_diff": worst_first,
        "g0_pass": bool(worst_first <= 1e-3),
        "torch": torch.__version__,
        "created_utc": utcnow().isoformat(timespec="seconds"),
    }
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out_dir / f"g0_{args.config}_{args.device}.json", report)
    log(json.dumps(report, indent=1, sort_keys=True))
    return EXIT_COMPLETE if report["g0_pass"] else EXIT_G0_FAIL


def mode_inputs(args, log: Log) -> int:
    """Dry check: build every origin's input (no model, no forecast) so that a data problem in
    any window is found before inference is launched."""
    root = Path(args.kronos_root)
    verify_private_copy(root)
    sys.path.insert(0, str(root / "src"))
    import model.kronos as up  # private copy; only calc_time_stamps is used here

    bars = load_bars(Path(args.bars))
    symbols = list(json.loads(Path(args.universe).read_text())["symbols"])
    col = {s: j for j, s in enumerate(bars["symbols"])}
    sym_cols = [col[s] for s in symbols]
    cfg = dict(CONFIGS[args.config])
    origins = window_origins(bars["dates"], args.window)
    n_dates = len(bars["dates"])
    steps_by_origin, clipped, earliest = [], 0, None
    built_n = poison_same = control_n = control_caught = 0
    for k, oi in enumerate(origins):
        steps_o = min(args.steps, n_dates - 1 - oi)
        steps_by_origin.append(steps_o)
        if steps_o <= 0:
            continue
        built = origin_inputs(up, bars, sym_cols, oi, cfg["lookback"])
        x_norm, _means, stds, _x_stamp, x_dates, _last = built
        _y_stamp, y_dates = future_stamps(up, bars, oi, steps_o)
        if not np.isfinite(x_norm).all() or (stds[:, :4] <= 0).any():
            log(f"ERROR: unusable look-back at origin {k:03d} {bars['dates'][oi]}")
            return EXIT_ERROR
        if (
            x_dates[-1] != bars["dates"][oi]
            or y_dates != bars["dates"][oi + 1 : oi + 1 + steps_o]
            or min(y_dates) <= bars["dates"][oi]
        ):
            log(f"ERROR: date check failed at origin {k:03d}")
            return EXIT_ERROR
        # Look-ahead test and its negative control (see the module docstring).
        built_n += 1
        if not look_ahead_test(up, bars, sym_cols, oi, cfg["lookback"], built):
            log(
                f"ERROR: look-ahead test failed at origin {k:03d}: inputs change when later bars are destroyed"
            )
            return EXIT_ERROR
        poison_same += 1
        caught = look_ahead_negative_control(up, bars, sym_cols, oi, cfg["lookback"], built)
        if caught is not None:
            control_n += 1
            control_caught += int(caught)
        clipped += int((np.abs(x_norm) >= CLIP).sum())
        earliest = x_dates[0] if earliest is None else min(earliest, x_dates[0])
        row_seeds(args.window, k, symbols, cfg["paths"])
    if control_n == 0 or control_caught != control_n:
        log(
            f"ERROR: the look-ahead test has no teeth: negative control caught at {control_caught} of {control_n} origins"
        )
        return EXIT_ERROR
    report = {
        "check": "input construction for every origin (no inference)",
        "config": args.config,
        "window": args.window,
        "n_symbols": len(symbols),
        "origins": len(origins),
        "look_ahead_test": {
            "what": "inputs rebuilt with every bar after the origin set to NaN must be bit-for-bit identical",
            "origins_tested": built_n,
            "origins_identical": poison_same,
            "negative_control": "an input cut one session late (it includes the first later bar) must be caught",
            "negative_control_origins": control_n,
            "negative_control_caught": control_caught,
        },
        "first_origin": bars["dates"][origins[0]],
        "last_origin": bars["dates"][origins[-1]],
        "origins_with_all_steps": int(sum(s == args.steps for s in steps_by_origin)),
        "origins_with_fewer_steps": {
            bars["dates"][oi]: s
            for oi, s in zip(origins, steps_by_origin, strict=True)
            if s < args.steps
        },
        "scored_origins": {
            str(h): int(sum(s >= h for s in steps_by_origin))
            for h in (5, 10, 20)
            if h <= args.steps
        },
        "earliest_look_back_session": earliest,
        "normalised_values_at_clip": clipped,
        "rows_per_origin": len(symbols) * cfg["paths"],
        "script_sha256": sha256_file(Path(__file__)),
        "created_utc": utcnow().isoformat(timespec="seconds"),
    }
    atomic_write_json(Path(args.out) / f"inputs_{args.config}_{args.window}.json", report)
    log(json.dumps(report, indent=1, sort_keys=True))
    return EXIT_COMPLETE


def mode_pilot(args, log: Log) -> int:
    """Throughput record and tier choice from the origins already present in the primary
    directory. No model is loaded and no forecast value is read: only run_manifest.json,
    run_status.json and the ``meta`` entry of each origin file (plus, with --compare-dir, a
    bitwise comparison of the origin files with an earlier pilot of the same origins)."""
    if not args.primary_dir:
        raise SystemExit("--mode pilot needs --primary-dir (the primary run directory to read)")
    pdir = Path(args.primary_dir)
    man = json.loads((pdir / "run_manifest.json").read_text())
    status = json.loads((pdir / "run_status.json").read_text())
    if (man["config_name"], man["window"]) != ("paper", "test"):
        raise SystemExit("--mode pilot reads the primary run (paper configuration, test window)")
    me = sha256_file(Path(__file__))
    files = sorted(pdir.glob("origin_*.npz"))
    full_secs, origins_read = [], []
    for fp in files:
        with np.load(fp, allow_pickle=False) as z:
            meta = json.loads(str(z["meta"]))
        if meta.get("script_sha256") != me:
            raise SystemExit(f"{fp.name} was not written by this version of the script")
        if int(meta["steps"]) == int(man["steps_requested"]):
            full_secs.append(float(meta["seconds"]))
            origins_read.append(meta["origin_date"])
    if not full_secs:
        raise SystemExit("no full-size origin in the primary directory to time")
    sec = max(full_secs)  # the slowest measured origin, so projections err on the long side
    n_test = sum(1 for it in man["origins"] if it["steps"] > 0)
    cfg_p, cfg_s = CONFIGS["paper"], CONFIGS["production"]
    steps = int(man["steps_requested"])
    n_sym = int(man["n_symbols"])
    primary_h = n_test * sec / 3600.0
    # Secondary run: same origins, 3 paths and a 128-session look-back. It is not timed before
    # the primary finishes; the figure below is scaled by rows x context length and bounded
    # above by the primary's own time (fewer rows, and fewer row x context^2 attention terms).
    scale = (cfg_s["paths"] * (cfg_s["lookback"] + steps)) / (
        cfg_p["paths"] * (cfg_p["lookback"] + steps)
    )
    projected = {
        "primary_test_window": round(primary_h, 3),
        "secondary_production_configuration_scaled_estimate": round(primary_h * scale, 3),
        "secondary_production_configuration_upper_bound": round(primary_h, 3),
    }
    n_contrast = None
    cu = Path(args.universe).with_name("universe_contrast.json")
    if cu.exists():
        bars = load_bars(Path(args.bars))
        n_dates = len(bars["dates"])
        n_contrast = sum(
            1
            for oi in window_origins(bars["dates"], "contrast")
            if min(steps, n_dates - 1 - oi) > 0
        )
        n_csym = len(json.loads(cu.read_text())["symbols"])
        projected["contrast_window"] = round(n_contrast * sec * (n_csym / n_sym) / 3600.0, 3)
    tier = 1 if primary_h <= TIER1_LIMIT_HOURS else None
    report = {
        "check": "throughput pilot and tier choice (made before any score is examined)",
        "origins_timed": origins_read,
        "seconds_per_origin": sec,
        "seconds_per_origin_all": full_secs,
        "rows": n_sym * cfg_p["paths"],
        "steps": steps,
        "device": man["device"],
        "kv_cache": man["kv_cache"],
        "batch_rows": man["batch_rows"],
        "threads": man["threads"],
        "origins_test_window": n_test,
        "origins_contrast_window": n_contrast,
        "projected_hours": projected,
        "tier": tier,
        "tier_rule": f"tier 1 unless the primary test window projects past {TIER1_LIMIT_HOURS:g} hours",
        "primary_run_status": status.get("status"),
        "script_sha256": me,
        "note": (
            "The pilot origin's forecast file is kept because the run is resumable; its relation to "
            "realised returns was not examined. The first pilot record also listed 5.3 s for one unsaved "
            "production-configuration origin; no script or log supports that figure, so it is not used."
        ),
        "measured_utc": utcnow().isoformat(timespec="seconds"),
    }
    if args.compare_dir:
        cdir = Path(args.compare_dir)
        compared, identical, detail = 0, 0, []
        for fp in files:
            other = cdir / fp.name
            if not other.exists():
                continue
            with np.load(fp, allow_pickle=False) as a, np.load(other, allow_pickle=False) as b:
                keys = ("symbols", "pred_close", "pred_high", "pred_low", "last_close", "row_seeds")
                same = {k: bool(np.array_equal(a[k], b[k])) for k in keys}
                old_meta = json.loads(str(b["meta"]))
            compared += 1
            identical += int(all(same.values()))
            detail.append({"file": fp.name, **same})
        old_man = json.loads((cdir / "run_manifest.json").read_text())
        report["regenerated_vs_earlier_pilot"] = {
            "earlier_directory": str(cdir.resolve()),
            "earlier_script_sha256": old_man.get("script_sha256"),
            "earlier_batch_rows": old_man.get("batch_rows"),
            "earlier_completed_utc": old_meta.get("completed_utc") if compared else None,
            "origin_files_compared": compared,
            "origin_files_bitwise_identical": identical,
            "arrays_compared": "symbols, pred_close, pred_high, pred_low, last_close, row_seeds",
            "detail": detail,
        }
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out_dir / "pilot.json", report)
    log(json.dumps(report, indent=1, sort_keys=True))
    if tier is None:
        log("Tier 1 projects past the limit: measure tier 2 (--steps 10) before choosing a tier")
        return EXIT_ERROR
    cmp_ = report.get("regenerated_vs_earlier_pilot")
    if cmp_ and cmp_["origin_files_bitwise_identical"] != cmp_["origin_files_compared"]:
        log("ERROR: a regenerated origin differs from the earlier pilot")
        return EXIT_ERROR
    return EXIT_COMPLETE


def mode_equiv(args, log: Log) -> int:
    """Batched sampler versus upstream KronosPredictor.predict on CPU, 3 symbols, one origin."""
    import torch

    _stop_at, refusal = clock_gate(args.deadline, utcnow(), VALIDATION_ALLOWANCE_S)
    if refusal:
        log(f"REFUSED: {refusal}")
        return EXIT_REFUSED
    torch.set_num_threads(args.threads)
    root = Path(args.kronos_root)
    verify_private_copy(root)
    bars = load_bars(Path(args.bars))
    symbols = list(json.loads(Path(args.universe).read_text())["symbols"])[:3]
    up, tok, mdl, key_report = load_models(root)
    predictor = up.KronosPredictor(mdl, tok, device="cpu", max_context=MAX_CONTEXT)
    col = {s: j for j, s in enumerate(bars["symbols"])}
    steps = args.steps
    report = {
        "symbols": symbols,
        "steps": steps,
        "window": args.window,
        "checkpoint_key_report": key_report,
        "torch": torch.__version__,
        "script_sha256": sha256_file(Path(__file__)),
        "configs": {},
    }
    for cname in ("paper", "production"):
        cfg = dict(CONFIGS[cname])
        oi, x_norm, means, stds, x_stamp, x_dates, y_stamp, y_dates, last_close = (
            _first_origin_inputs(up, bars, symbols, args.window, cfg["lookback"], steps)
        )
        stamp = np.concatenate([x_stamp, y_stamp], axis=0)
        x_ts = pd.Series(pd.to_datetime(x_dates))
        y_ts = pd.Series(pd.to_datetime(y_dates))
        frames = []
        for s in symbols:  # production hands upstream OHLCV only; upstream fills amount itself
            j = col[s]
            frames.append(
                pd.DataFrame(
                    {
                        f: bars[f][oi - cfg["lookback"] + 1 : oi + 1, j]
                        for f in ("open", "high", "low", "close", "volume")
                    }
                )
            )
        n_seed = cfg["paths"]
        # (1) path-for-path: upstream one-row batch seeded 42 + p, versus this sampler's row seeded 42 + p.
        t0 = time.time()
        up_paths = np.empty((len(symbols), n_seed, steps, 6), dtype=np.float64)
        for i, frame in enumerate(frames):
            for p in range(n_seed):
                torch.manual_seed(BASE_SEED + p)
                np.random.seed(BASE_SEED + p)
                fc = predictor.predict(
                    df=frame,
                    x_timestamp=x_ts,
                    y_timestamp=y_ts,
                    pred_len=steps,
                    T=cfg["T"],
                    top_k=cfg["top_k"],
                    top_p=cfg["top_p"],
                    sample_count=1,
                    verbose=False,
                )
                up_paths[i, p] = fc[FEATURES].to_numpy()
        t_up = time.time() - t0
        seeds = np.tile(np.arange(BASE_SEED, BASE_SEED + n_seed), (len(symbols), 1))
        entry = {
            "origin_date": bars["dates"][oi],
            "lookback": cfg["lookback"],
            "T": cfg["T"],
            "top_p": cfg["top_p"],
            "paths_compared": n_seed,
            "upstream_seconds": round(t_up, 2),
        }
        for label, kv in (("kv_cache", True), ("no_kv_cache", False)):
            t0 = time.time()
            out = generate_chunk(
                up,
                tok,
                mdl,
                x_norm,
                stamp,
                n_seed,
                steps,
                cfg,
                seeds,
                "cpu",
                kv_cache=kv,
                collect=True,
            )
            mine = out["z"] * (stds[:, None, None, :] + 1e-5) + means[:, None, None, :]
            rel = np.abs(mine - up_paths) / np.maximum(np.abs(up_paths), 1e-12)
            close_rel = rel[..., 3]
            path_match = close_rel.max(axis=-1) < 1e-4
            entry[label] = {
                "seconds": round(time.time() - t0, 2),
                "paths_identical_to_upstream": int(path_match.sum()),
                "paths_total": int(path_match.size),
                "max_rel_diff_close": float(close_rel.max()),
                "max_rel_diff_all_features": float(rel.max()),
                "max_rel_diff_mean_over_paths_close": float(
                    (
                        np.abs(mine[..., 3].mean(axis=1) - up_paths[..., 3].mean(axis=1))
                        / np.abs(up_paths[..., 3].mean(axis=1))
                    ).max()
                ),
            }
            if kv:
                kv_out = out
            else:
                nokv_out = out
        # (2) first-step logits: upstream decode_s1 on a one-row batch per symbol.
        worst = {"kv_cache": 0.0, "no_kv_cache": 0.0}
        for i in range(len(symbols)):
            x = torch.clip(torch.from_numpy(x_norm[i : i + 1]), -CLIP, CLIP)
            t_ = tok.encode(x, half=True)
            st = torch.from_numpy(x_stamp).unsqueeze(0)
            s1_all, _ctx = mdl.decode_s1(t_[0], t_[1], st)
            ref_logits = s1_all[:, -1, :]
            for label, o in (("kv_cache", kv_out), ("no_kv_cache", nokv_out)):
                worst[label] = max(
                    worst[label], float((o["s1_logits"][i * n_seed, 0] - ref_logits[0]).abs().max())
                )
        entry["first_step_s1_logit_max_abs_diff_vs_upstream"] = worst
        entry["all_steps_logit_max_abs_diff_kv_vs_no_kv"] = {
            "s1": float((kv_out["s1_logits"] - nokv_out["s1_logits"]).abs().max()),
            "s2": float((kv_out["s2_logits"] - nokv_out["s2_logits"]).abs().max()),
            "note": "comparable only while both arms sampled the same tokens; see paths_identical_to_upstream",
        }
        # (3) 200-path mean: upstream predict(sample_count=N) (one batch, global generator) versus N independent rows here.
        if cname == args.config:
            n = args.equiv_paths
            t0 = time.time()
            up_mean = np.empty((len(symbols), steps), dtype=np.float64)
            for i, frame in enumerate(frames):
                torch.manual_seed(20261110 + i)
                fc = predictor.predict(
                    df=frame,
                    x_timestamp=x_ts,
                    y_timestamp=y_ts,
                    pred_len=steps,
                    T=cfg["T"],
                    top_k=cfg["top_k"],
                    top_p=cfg["top_p"],
                    sample_count=n,
                    verbose=False,
                )
                up_mean[i] = fc["close"].to_numpy()
            t_up = time.time() - t0
            seeds_n = row_seeds("equiv", 0, symbols, n)
            t0 = time.time()
            out = generate_chunk(
                up, tok, mdl, x_norm, stamp, n, steps, cfg, seeds_n, "cpu", kv_cache=True
            )
            mine = (out["z"] * (stds[:, None, None, :] + 1e-5) + means[:, None, None, :])[
                ..., 3
            ].astype(np.float64)
            m, sd = mine.mean(axis=1), mine.std(axis=1, ddof=1)
            zscore = (m - up_mean) / (sd * np.sqrt(2.0 / n))
            entry["mean_of_paths"] = {
                "paths": n,
                "upstream_seconds": round(t_up, 2),
                "this_sampler_seconds": round(time.time() - t0, 2),
                "z_definition": "(mean_here - mean_upstream) / (sd_here * sqrt(2 / paths)) per symbol and step",
                "max_abs_z": float(np.abs(zscore).max()),
                "share_abs_z_below_2": float((np.abs(zscore) < 2).mean()),
                "cells": int(zscore.size),
                "max_rel_diff_of_means": float((np.abs(m - up_mean) / up_mean).max()),
                "terminal_mean_return_here": [float(v) for v in (m[:, -1] / last_close - 1)],
                "terminal_mean_return_upstream": [
                    float(v) for v in (up_mean[:, -1] / last_close - 1)
                ],
                "terminal_sd_return_here": [float(v) for v in (sd[:, -1] / last_close)],
            }
        report["configs"][cname] = entry
    report["created_utc"] = utcnow().isoformat(timespec="seconds")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out_dir / "equivalence.json", report)
    log(json.dumps(report, indent=1, sort_keys=True))
    return EXIT_COMPLETE


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mode", choices=["run", "g0", "equiv", "inputs", "pilot"], default="run")
    ap.add_argument("--config", choices=sorted(CONFIGS), required=True)
    ap.add_argument("--window", choices=sorted(WINDOWS), required=True)
    ap.add_argument("--steps", type=int, required=True)
    ap.add_argument(
        "--universe", required=True, help="universe JSON written by kronos_ic_export.py"
    )
    ap.add_argument("--device", choices=["mps", "cpu"], required=True)
    ap.add_argument("--batch-rows", type=int, default=2500)
    ap.add_argument(
        "--deadline",
        required=True,
        help="UTC ISO time; no origin is started that cannot finish before it",
    )
    ap.add_argument("--out", required=True)
    ap.add_argument("--bars", default=str(DEFAULT_BARS))
    ap.add_argument("--kronos-root", default=str(DEFAULT_KRONOS_ROOT))
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--max-origins", type=int, default=None)
    ap.add_argument(
        "--primary-dir",
        help="finished primary run; required for the production configuration and the contrast window. "
        "With --mode pilot: the primary run directory to read",
    )
    ap.add_argument(
        "--compare-dir",
        help="--mode pilot only: an earlier pilot directory whose origin files are compared bitwise",
    )
    ap.add_argument(
        "--est-seconds", type=float, default=240.0, help="time allowance for the first origin"
    )
    ap.add_argument(
        "--no-kv-cache",
        action="store_true",
        help="recompute the full context each step, as upstream does",
    )
    ap.add_argument("--equiv-paths", type=int, default=200)
    args = ap.parse_args()
    if not 1 <= args.steps <= 20:
        raise SystemExit("--steps must be between 1 and 20")
    if args.threads > 4:
        raise SystemExit("CPU budget for this study is 4 threads")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    if os.environ.get("HF_HUB_OFFLINE") != "1":
        raise SystemExit("HF_HUB_OFFLINE=1 is required")

    def offline(event: str, _args: tuple) -> None:
        if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.sendto"}:
            raise RuntimeError("Network disabled for research inference")

    sys.addaudithook(offline)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    log = Log(out_dir / ("infer.log" if args.mode == "run" else f"{args.mode}.log"))
    if args.mode == "g0":
        return mode_g0(args, log)
    if args.mode == "equiv":
        return mode_equiv(args, log)
    if args.mode == "inputs":
        return mode_inputs(args, log)
    if args.mode == "pilot":
        return mode_pilot(args, log)
    return run(args, log)


if __name__ == "__main__":
    sys.exit(main())
