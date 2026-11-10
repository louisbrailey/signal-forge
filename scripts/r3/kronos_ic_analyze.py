"""R3 Kronos cross-sectional IC study -- step 3: endpoints, decision rule and report.

Pre-registration: docs/research/kronos/PREREGISTRATION_2026-11-10_kronos_cross_sectional_ic.md

Runs in the Signal Forge venv with numpy only (no scipy, no torch, no database). Inputs are
``bars.npz`` from ``kronos_ic_export.py`` (dates <= 2025-09-05) and the per-origin forecast
files written by ``kronos_ic_infer.py``. Every pre-registered endpoint is computed and the
PASS/FAIL rule is applied mechanically.

A run directory that is missing origins is never scored, so there is no interim look. If the
primary run is incomplete the analysis is refused and nothing is written (exit 2); with
``--incomplete-notice`` it instead writes a results file that only says so, with no outcome
number. If the secondary or the contrast run is incomplete, its cells are reported as
"incomplete, not scored" and no forecast of that run is read; the primary verdict does not
depend on them.

Every origin file is checked before it is scored: its plan entry, its future dates against
the calendar in the bars file, its bars, universe and script hashes and configuration against
the run manifest, its last observed close against the bars file, and its recorded row seeds
against the documented formula. A failed check stops the analysis (exit 3) with no results.

``--selftest`` never reads a real forecast: it builds synthetic forecasts (pure noise, a
planted signal, an oracle and shifted oracles) and pushes them through the same code, and it
measures how often the test rejects when the score carries no information at all.

Research signal only -- no order was placed.
"""

# Report prose, table headers and help strings are kept on one line.
# ruff: noqa: E501

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

SCRATCH = Path(
    "/private/tmp/claude-501/-Users-louisbrailey-Projects-signal-forge/"
    "ec635db8-8e7c-46dd-bc95-83c88a678e74/scratchpad"
)
DEFAULT_BARS = SCRATCH / "r3/out/kronos-ic/bars/bars.npz"
DEFAULT_OUT = SCRATCH / "r3wt/docs/research/kronos/2026-11-10-cross-sectional"
DEFAULT_VALIDATION = SCRATCH / "r3/out/kronos-ic/validate"
RESULTS_NAME = "KRONOS_CROSS_SECTIONAL_IC_2026-11-10.md"
LAST_DEV_SESSION = "2025-09-05"
TRAINING_CUTOFF = "2024-06-30"  # "pre-training data for Kronos extends up to June 2024"
WINDOWS = {
    "test": {"first": "2024-07-01", "last": LAST_DEV_SESSION, "every": 5},
    "contrast": {"first": "2023-01-03", "last": "2024-06-14", "every": 5},
}
FAMILY = (5, 10, 20)
PRIMARY_H = 10
COST_ROUND_TRIP = 0.0011
THRESHOLD = 1.0011
FACTORS = ("ret5", "ret20", "mom_252_21", "rvol20")
FACTOR_LABEL = {
    "ret5": "5-session return",
    "ret20": "20-session return",
    "mom_252_21": "252-minus-21 session return",
    "rvol20": "20-session realised volatility",
}
MIN_NAMES = 30
PASS_MIN_IC = 0.02
PASS_MIN_T = 3.0
PASS_MIN_INCREMENTAL_T = 2.0
# Reported by the model's authors for Kronos-small (arXiv 2508.02739, Table 6; quoted in the
# pre-registration). Used only to describe where the interval around the measured IC lies.
PAPER_RANK_IC = 0.0622
BASE_SEED = 42
CRITERION_WORDS = {
    "mean_rank_ic_at_least_0.02": "a mean rank IC of at least 0.02",
    "newey_west_t_at_least_3": "a Newey-West t of at least 3",
    "holm_adjusted_p_not_above_p_of_t3": "a Holm-adjusted p-value no larger than the p-value of t = 3",
    "same_sign_in_both_halves": "the same sign in both halves of the window",
    "incremental_kronos_t_at_least_2": "a t of at least 2 for the Kronos coefficient alongside the four simple ranks",
}


class IdentityError(RuntimeError):
    """An identity check failed: stop and report it instead of results."""


class Incomplete(RuntimeError):
    pass


def seed32(label: str) -> int:
    return int.from_bytes(hashlib.sha256(label.encode()).digest()[:4], "big")


def row_seeds(window: str, origin_index: int, symbols: list[str], n_paths: int) -> np.ndarray:
    """The documented row-seed formula of kronos_ic_infer.py, restated here so that the seeds
    recorded in an origin file can be checked independently of the script that wrote them."""
    out = np.zeros((len(symbols), n_paths), dtype=np.int64)
    seen: set[int] = set()
    for i, sym in enumerate(symbols):
        for p in range(n_paths):
            base = f"kronos-ic-r3/{window}/origin/{origin_index}/symbol/{sym}/path-seed/{BASE_SEED + p}"
            s, salt = seed32(base), 0
            while s in seen:
                salt += 1
                s = seed32(f"{base}/salt/{salt}")
            seen.add(s)
            out[i, p] = s
    return out


# ------------------------------------------------------------------------------ statistics
def rankdata(a: np.ndarray) -> np.ndarray:
    """Average ranks (1-based), ties share the mean rank. Input must be finite."""
    n = a.size
    order = np.argsort(a, kind="mergesort")
    s = a[order]
    new = np.r_[True, s[1:] != s[:-1]]
    dense = np.cumsum(new) - 1
    bounds = np.r_[np.nonzero(new)[0], n]
    ranks = np.empty(n, dtype=np.float64)
    ranks[order] = 0.5 * (bounds[dense] + bounds[dense + 1] + 1)
    return ranks


def pearson(x: np.ndarray, y: np.ndarray) -> float:
    x = x - x.mean()
    y = y - y.mean()
    den = math.sqrt(float(x @ x) * float(y @ y))
    return float(x @ y) / den if den > 0 else float("nan")


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    return pearson(rankdata(x), rankdata(y))


def nw_lag(h: int) -> int:
    return math.ceil(h / 5)


def normal_p_two_sided(t: float) -> float:
    return float(math.erfc(abs(t) / math.sqrt(2.0))) if math.isfinite(t) else float("nan")


def nw_stats(series, lag: int) -> dict:
    """Mean of a per-origin series with a Newey-West (Bartlett) standard error."""
    x = np.asarray(series, dtype=np.float64)
    x = x[np.isfinite(x)]
    n = int(x.size)
    out = {
        "n": n,
        "mean": float("nan"),
        "se": float("nan"),
        "t": float("nan"),
        "p": float("nan"),
        "half1": float("nan"),
        "half2": float("nan"),
        "same_sign": None,
        "share_positive": float("nan"),
        "lag": lag,
    }
    if n == 0:
        return out
    m = float(x.mean())
    out["mean"] = m
    out["share_positive"] = float((x > 0).mean())
    cut = math.ceil(n / 2)
    if n >= 2:
        out["half1"], out["half2"] = float(x[:cut].mean()), float(x[cut:].mean())
        out["same_sign"] = bool(out["half1"] * out["half2"] > 0)
    if n < 3:
        return out
    d = x - m
    var = float(d @ d) / n
    for j in range(1, min(lag, n - 1) + 1):
        var += 2.0 * (1.0 - j / (lag + 1.0)) * float(d[j:] @ d[:-j]) / n
    if var > 0:
        out["se"] = math.sqrt(var / n)
        out["t"] = m / out["se"]
        out["p"] = normal_p_two_sided(out["t"])
    return out


def holm(pvals: dict) -> dict:
    items = sorted(((p, k) for k, p in pvals.items() if math.isfinite(p)))
    m, out, running = len(items), {}, 0.0
    for i, (p, k) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        out[k] = running
    for k in pvals:
        out.setdefault(k, float("nan"))
    return out


# -------------------------------------------------------------------------------- loading
def load_bars(path: Path) -> dict:
    z = np.load(path, allow_pickle=False)
    bars = {k: z[k] for k in z.files}
    dates = [str(d) for d in bars["dates"]]
    if max(dates) > LAST_DEV_SESSION or dates != sorted(dates) or len(set(dates)) != len(dates):
        raise IdentityError("bars file is unsorted or contains a date after 2025-09-05")
    bars["dates"] = dates
    bars["symbols"] = [str(s) for s in bars["symbols"]]
    h = hashlib.sha256()  # same content hash as kronos_ic_export.py / kronos_ic_infer.py
    for key in sorted(z.files):
        a = np.ascontiguousarray(z[key])
        h.update(f"{key}|{a.dtype}|{a.shape}|".encode())
        h.update(a.tobytes())
    bars["_content_sha256"] = h.hexdigest()
    return bars


def window_plan(dates: list[str], window: str, steps: int) -> list[dict]:
    spec = WINDOWS[window]
    i0 = dates.index(spec["first"])
    plan = []
    for k, t in enumerate(
        i for i in range(i0, len(dates), spec["every"]) if dates[i] <= spec["last"]
    ):
        plan.append(
            {
                "origin_index": k,
                "date": dates[t],
                "bar_index": t,
                "steps": min(steps, len(dates) - 1 - t),
            }
        )
    return plan


@dataclass
class Run:
    name: str
    manifest: dict
    symbols: list
    cols: np.ndarray
    origins: list = field(
        default_factory=list
    )  # dicts: k, date, t, steps, pred_close [n, P, steps]
    expected: int = 0
    present: int = 0  # origin files found on disk
    last_present: str | None = None
    verified: int = 0  # origin files that passed every check
    provenance: dict = field(default_factory=dict)  # per-origin batch_rows / threads seen

    @property
    def paths(self) -> int:
        return int(self.manifest["config"]["paths"])

    @property
    def scored(self) -> bool:
        return bool(self.origins) and len(self.origins) == self.expected


# Keys every origin file must carry with exactly the manifest's value.
ORIGIN_MATCHES_MANIFEST = (
    "config_name",
    "config",
    "window",
    "device",
    "kv_cache",
    "universe_sha256",
    "bars_content_sha256",
    "script_sha256",
)


def load_run(
    name: str,
    directory: Path | None,
    bars: dict,
    *,
    must_be_complete: bool = True,
    verify_only: bool = False,
) -> Run | None:
    """Load one run directory after checking every origin file against the plan, the bars file
    and the run manifest. An incomplete directory is never scored: it raises ``Incomplete``
    when ``must_be_complete`` is set, and otherwise comes back with no origins and without any
    forecast having been read.

    ``verify_only`` runs the same checks on whatever origin files are present and keeps no
    forecast, so the result cannot be scored. It exists to confirm, before a run is complete,
    that the files being written will be accepted."""
    if directory is None or not (Path(directory) / "run_manifest.json").exists():
        return None
    directory = Path(directory)
    man = json.loads((directory / "run_manifest.json").read_text())
    if man.get("bars_content_sha256") != bars["_content_sha256"]:
        raise IdentityError(
            f"{name}: the forecasts were made from a different bars file than the one being scored"
        )
    if not man.get("script_sha256"):
        raise IdentityError(f"{name}: the run manifest does not record the script that wrote it")
    plan = window_plan(bars["dates"], man["window"], int(man["steps_requested"]))
    if [(p["origin_index"], p["date"], p["bar_index"], p["steps"]) for p in plan] != [
        (p["origin_index"], p["date"], p["bar_index"], p["steps"]) for p in man["origins"]
    ]:
        raise IdentityError(
            f"{name}: the manifest's origin plan does not match the calendar in the bars file"
        )
    col = {s: j for j, s in enumerate(bars["symbols"])}
    run = Run(name=name, manifest=man, symbols=[], cols=np.array([], dtype=int))
    wanted = [p for p in plan if p["steps"] > 0]
    run.expected = len(wanted)
    files = [(p, directory / f"origin_{p['origin_index']:03d}_{p['date']}.npz") for p in wanted]
    stray = sorted({q.name for q in directory.glob("origin_*.npz")} - {fp.name for _p, fp in files})
    if stray:
        raise IdentityError(f"{name}: origin files outside the plan are present: {stray[:3]}")
    on_disk = [(p, fp) for p, fp in files if fp.exists()]
    run.present = len(on_disk)
    run.last_present = on_disk[-1][0]["date"] if on_disk else None
    if run.present != run.expected and not verify_only:
        if must_be_complete:
            raise Incomplete(
                f"{name}: {run.present} of {run.expected} origins present in {directory}"
            )
        return run  # not scored; no forecast of an incomplete run is read
    window, n_paths = man["window"], run.paths
    for p, fp in on_disk:
        t, steps = p["bar_index"], p["steps"]
        with np.load(fp, allow_pickle=False) as zf:
            z = {k: zf[k] for k in ("meta", "symbols", "pred_close", "last_close", "row_seeds")}
        meta = json.loads(str(z["meta"]))
        symbols = [str(s) for s in z["symbols"]]
        if not run.symbols:
            run.symbols = symbols
            run.cols = np.array([col[s] for s in symbols])
        if symbols != run.symbols:
            raise IdentityError(f"{name}: symbol list changes at origin {p['date']}")
        pc = z["pred_close"]
        if (
            meta["origin_date"] != p["date"]
            or int(meta["origin_index"]) != p["origin_index"]
            or int(meta["steps"]) != steps
            or pc.shape != (len(symbols), n_paths, steps)
        ):
            raise IdentityError(f"{name}: origin file {fp.name} does not match the plan")
        # Step i of the forecast is scored against session origin + i + 1 of the bars file, so the
        # dates the forecast was generated for must be exactly those sessions.
        if list(meta["future_dates"]) != bars["dates"][t + 1 : t + 1 + steps]:
            raise IdentityError(
                f"{name}: future dates in {fp.name} are not the sessions that follow the origin"
            )
        if max(meta["future_dates"]) > LAST_DEV_SESSION or meta["lookback_last"] != p["date"]:
            raise IdentityError(
                f"{name}: origin file {fp.name} carries a date outside its permitted range"
            )
        differs = [k for k in ORIGIN_MATCHES_MANIFEST if meta.get(k) != man.get(k)]
        if differs:
            raise IdentityError(
                f"{name}: origin file {fp.name} disagrees with the run manifest in {differs}"
            )
        if list(meta["path_seeds"]) != [BASE_SEED + i for i in range(n_paths)]:
            raise IdentityError(f"{name}: path seeds in {fp.name} are not 42 + path index")
        if not np.array_equal(
            z["row_seeds"], row_seeds(window, p["origin_index"], symbols, n_paths)
        ):
            raise IdentityError(
                f"{name}: row seeds in {fp.name} do not follow the documented formula"
            )
        if not np.array_equal(z["last_close"], bars["close"][t, run.cols]):
            raise IdentityError(
                f"{name}: last observed close in {fp.name} differs from the bars file"
            )
        if not np.isfinite(pc).all():
            raise IdentityError(f"{name}: non-finite forecast in {fp.name}")
        for key in ("batch_rows", "threads"):
            run.provenance.setdefault(key, set()).add(meta.get(key))
        run.verified += 1
        if verify_only:
            continue  # checked; the forecast is not kept
        run.origins.append(
            {
                "k": p["origin_index"],
                "date": p["date"],
                "t": t,
                "steps": steps,
                "pred_close": pc,
            }
        )
    if on_disk and len(run.symbols) != int(man["n_symbols"]):
        raise IdentityError(f"{name}: symbol count differs from the manifest")
    return run


# ---------------------------------------------------------------------------------- panel
def build_panel(run: Run, bars: dict) -> dict:
    """Predicted and realised returns, [origin, horizon, symbol]; NaN where not scored."""
    close, open_ = bars["close"], bars["open"]
    last = len(bars["dates"]) - 1
    K, H, n = len(run.origins), int(run.manifest["steps_requested"]), len(run.symbols)
    shape = (K, H, n)
    P = {k: np.full(shape, np.nan) for k in ("pred", "disp", "cc", "on", "mean_close")}
    P["c0"] = np.full((K, n), np.nan)
    P["factors"] = {f: np.full((K, n), np.nan) for f in FACTORS}
    for i, o in enumerate(run.origins):
        t = o["t"]
        c_hist = close[: t + 1, :][
            :, run.cols
        ]  # nothing after the origin is visible to the factors
        c0 = c_hist[-1]
        P["c0"][i] = c0
        pc = o["pred_close"].astype(np.float64)
        for h in range(1, o["steps"] + 1):
            mc = pc[:, :, h - 1].mean(axis=1)
            P["mean_close"][i, h - 1] = mc
            P["pred"][i, h - 1] = mc / c0 - 1.0
            if pc.shape[1] > 1:
                P["disp"][i, h - 1] = (pc[:, :, h - 1] / c0[:, None] - 1.0).std(axis=1, ddof=1)
            if t + h <= last:  # scored only if origin + h is on or before 2025-09-05
                ch = close[t + h, run.cols]
                P["cc"][i, h - 1] = ch / c0 - 1.0
                P["on"][i, h - 1] = ch / open_[t + 1, run.cols] - 1.0
        if t >= 5:
            P["factors"]["ret5"][i] = c0 / c_hist[-6] - 1.0
        if t >= 20:
            P["factors"]["ret20"][i] = c0 / c_hist[-21] - 1.0
            P["factors"]["rvol20"][i] = np.diff(np.log(c_hist[-21:]), axis=0).std(axis=0, ddof=1)
        if t >= 252:
            P["factors"]["mom_252_21"][i] = c_hist[-22] / c_hist[-253] - 1.0
    P["dates"] = [o["date"] for o in run.origins]
    P["k"] = [o["k"] for o in run.origins]
    return P


def corr_series(
    X: np.ndarray, Y: np.ndarray, mask: np.ndarray, fn
) -> tuple[np.ndarray, np.ndarray]:
    """Per-origin cross-sectional correlation of X[origin] with Y[origin] over ``mask`` symbols."""
    K = X.shape[0]
    out, used = np.full(K, np.nan), np.zeros(K, dtype=int)
    for i in range(K):
        ok = mask & np.isfinite(X[i]) & np.isfinite(Y[i])
        used[i] = int(ok.sum())
        if used[i] >= MIN_NAMES:
            out[i] = fn(X[i][ok], Y[i][ok])
    return out, used


def ic_block(P: dict, mask: np.ndarray, horizons, target: str = "cc") -> dict:
    block = {}
    for h in horizons:
        if h > P["pred"].shape[1]:
            continue
        rank_ic, used = corr_series(P["pred"][:, h - 1], P[target][:, h - 1], mask, spearman)
        pear_ic, _ = corr_series(P["pred"][:, h - 1], P[target][:, h - 1], mask, pearson)
        st = nw_stats(rank_ic, nw_lag(h))
        sp = nw_stats(pear_ic, nw_lag(h))
        scored = np.isfinite(rank_ic)
        block[h] = {
            "rank": st,
            "pearson": sp,
            "series_rank": rank_ic,
            "series_pearson": pear_ic,
            "n_names_mean": float(used[scored].mean()) if scored.any() else float("nan"),
        }
    fam = {h: block[h]["rank"]["p"] for h in FAMILY if h in block}
    adj = holm(fam)
    for h in fam:
        block[h]["rank"]["p_holm"] = adj[h]
    return block


def centred_rank(v: np.ndarray) -> np.ndarray:
    return (rankdata(v) - 1.0) / (v.size - 1.0) - 0.5


def incremental(P: dict, mask: np.ndarray, h: int) -> dict:
    """Per-origin OLS of realised rank on Kronos rank + four simple ranks (Fama-MacBeth)."""
    K = P["pred"].shape[0]
    names = ["kronos", *FACTORS]
    coefs, used = np.full((K, len(names)), np.nan), np.zeros(K, dtype=int)
    for i in range(K):
        y, x = P["cc"][i, h - 1], P["pred"][i, h - 1]
        ok = mask & np.isfinite(y) & np.isfinite(x)
        for f in FACTORS:
            ok &= np.isfinite(P["factors"][f][i])
        used[i] = int(ok.sum())
        if used[i] < MIN_NAMES:
            continue
        cols = [np.ones(used[i]), centred_rank(x[ok])] + [
            centred_rank(P["factors"][f][i][ok]) for f in FACTORS
        ]
        beta, *_ = np.linalg.lstsq(np.column_stack(cols), centred_rank(y[ok]), rcond=None)
        coefs[i] = beta[1:]
    scored = np.isfinite(coefs[:, 0])
    out = {
        "n_names_mean": float(used[scored].mean()) if scored.any() else float("nan"),
        "series_kronos": coefs[:, 0],
    }
    for j, nm in enumerate(names):
        out[nm] = nw_stats(coefs[:, j], nw_lag(h))
    return out


def factor_ics(P: dict, mask: np.ndarray, h: int) -> dict:
    out = {}
    for f in FACTORS:
        s, used = corr_series(P["factors"][f], P["cc"][:, h - 1], mask, spearman)
        st = nw_stats(s, nw_lag(h))
        scored = np.isfinite(s)
        st["n_names_mean"] = float(used[scored].mean()) if scored.any() else float("nan")
        out[f] = st
    return out


def decile_spreads(P: dict, mask: np.ndarray, h: int) -> dict:
    """Top/bottom decile by predicted return, entered at the next open, exited at the close of origin + h."""
    K = P["pred"].shape[0]
    tb, tu, sizes = np.full(K, np.nan), np.full(K, np.nan), []
    for i in range(K):
        x, r = P["pred"][i, h - 1], P["on"][i, h - 1]
        ok = mask & np.isfinite(x) & np.isfinite(r)
        m = int(ok.sum())
        if m < MIN_NAMES:
            continue
        nd = m // 10
        order = np.argsort(x[ok], kind="mergesort")
        rr = r[ok]
        top, bottom = rr[order[-nd:]].mean(), rr[order[:nd]].mean()
        tb[i], tu[i] = top - bottom, top - rr.mean()
        sizes.append(nd)
    lag = nw_lag(h)
    return {
        "names_per_decile_mean": float(np.mean(sizes)) if sizes else float("nan"),
        "top_minus_bottom_gross": nw_stats(tb, lag),
        "top_minus_bottom_net": nw_stats(tb - 2 * COST_ROUND_TRIP, lag),
        "top_minus_universe_gross": nw_stats(tu, lag),
        "top_minus_universe_net": nw_stats(tu - COST_ROUND_TRIP, lag),
        "series_tb_gross": tb,
        "series_tu_gross": tu,
    }


def dispersion(P: dict, mask: np.ndarray, h: int) -> dict:
    K = P["pred"].shape[0]
    raw, part = np.full(K, np.nan), np.full(K, np.nan)
    for i in range(K):
        d, a, v = P["disp"][i, h - 1], np.abs(P["cc"][i, h - 1]), P["factors"]["rvol20"][i]
        ok = mask & np.isfinite(d) & np.isfinite(a) & np.isfinite(v)
        if int(ok.sum()) < MIN_NAMES:
            continue
        rd, ra, rv = rankdata(d[ok]), rankdata(a[ok]), rankdata(v[ok])
        r_da, r_dv, r_av = pearson(rd, ra), pearson(rd, rv), pearson(ra, rv)
        raw[i] = r_da
        den = math.sqrt(max(0.0, (1 - r_dv**2) * (1 - r_av**2)))
        part[i] = (r_da - r_dv * r_av) / den if den > 0 else np.nan
    lag = nw_lag(h)
    return {
        "rank_corr": nw_stats(raw, lag),
        "partial_given_rvol20": nw_stats(part, lag),
        "series_raw": raw,
        "series_partial": part,
    }


def threshold_preview(P: dict, mask: np.ndarray, h: int) -> dict:
    """Frozen rule's condition on a broad universe: mean terminal close > last close * 1.0011."""
    K = P["pred"].shape[0]
    share, sel_r, uns_r, diff = (np.full(K, np.nan) for _ in range(4))
    pooled_sel, pooled_uns = [], []
    for i in range(K):
        mc, r = P["mean_close"][i, h - 1], P["cc"][i, h - 1]
        ok = mask & np.isfinite(mc) & np.isfinite(r)
        if int(ok.sum()) < MIN_NAMES:
            continue
        sel = mc[ok] > P["c0"][i][ok] * THRESHOLD
        share[i] = float(sel.mean())
        rr = r[ok]
        if sel.any():
            sel_r[i] = float(rr[sel].mean())
            pooled_sel.append(rr[sel])
        if (~sel).any():
            uns_r[i] = float(rr[~sel].mean())
            pooled_uns.append(rr[~sel])
        if sel.any() and (~sel).any():
            diff[i] = sel_r[i] - uns_r[i]
    lag = nw_lag(h)
    return {
        "share_selected": nw_stats(share, lag),
        "share_selected_min": float(np.nanmin(share)) if np.isfinite(share).any() else float("nan"),
        "share_selected_max": float(np.nanmax(share)) if np.isfinite(share).any() else float("nan"),
        "mean_return_selected": nw_stats(sel_r, lag),
        "mean_return_unselected": nw_stats(uns_r, lag),
        "selected_minus_unselected": nw_stats(diff, lag),
        "pooled_mean_return_selected": float(np.concatenate(pooled_sel).mean())
        if pooled_sel
        else float("nan"),
        "pooled_mean_return_unselected": float(np.concatenate(pooled_uns).mean())
        if pooled_uns
        else float("nan"),
        "series_share": share,
    }


# ------------------------------------------------------------------------------- analysis
def subset_masks(run: Run, bars: dict) -> dict:
    is_etf = bars["is_etf"][run.cols]
    snap = bars["in_snap11"][run.cols]
    return {"all": np.ones(len(run.symbols), dtype=bool), "stocks": ~is_etf, "snapshot11": snap}


def strip(d):
    """Drop per-origin series (kept for the CSV) and make the rest JSON-safe."""
    if isinstance(d, dict):
        return {str(k): strip(v) for k, v in d.items() if not str(k).startswith("series")}
    if isinstance(d, (list, tuple)):
        return [strip(v) for v in d]
    if isinstance(d, (np.floating, float)):
        return float(d) if math.isfinite(float(d)) else None
    if isinstance(d, (np.integer,)):
        return int(d)
    if isinstance(d, np.bool_):
        return bool(d)
    return d


def run_info(run: Run | None, P: dict | None) -> dict:
    if run is None:
        return {"present": False, "scored": False}
    man = run.manifest
    scored = {}
    if P is not None:
        for h in range(1, P["cc"].shape[1] + 1):
            scored[h] = int(np.isfinite(P["cc"][:, h - 1]).any(axis=1).sum())
    return {
        "present": True,
        "scored": run.scored and P is not None,
        "config_name": man["config_name"],
        "config": man["config"],
        "window": man["window"],
        "n_symbols": int(man["n_symbols"]),
        "steps_requested": man["steps_requested"],
        "origins_expected": run.expected,
        "origins_present": run.present,
        "complete": run.present == run.expected,
        "first_origin": run.origins[0]["date"] if run.origins else None,
        "last_origin": run.origins[-1]["date"] if run.origins else run.last_present,
        "scored_origins_by_horizon": scored,
        "device": man.get("device"),
        "kv_cache": man.get("kv_cache"),
        "batch_rows_used": sorted(str(v) for v in run.provenance.get("batch_rows", ())),
        "threads_used": sorted(str(v) for v in run.provenance.get("threads", ())),
        "universe_sha256": man.get("universe_sha256"),
        "bars_content_sha256": man.get("bars_content_sha256"),
        "script_sha256": man.get("script_sha256"),
    }


def decide(st: dict, inc: dict, fam_present: list) -> dict:
    """The pre-registered PASS/FAIL rule, applied to the primary endpoint's statistics.

    ``st`` is the rank-IC block of h = 10 (mean, se, t, p, p_holm, halves); ``inc`` is the
    Newey-West block of the Kronos coefficient in the incremental regression at h = 10.
    """
    p_at_3 = normal_p_two_sided(PASS_MIN_T)
    c = {
        "mean_rank_ic_at_least_0.02": bool(st["mean"] >= PASS_MIN_IC),
        "newey_west_t_at_least_3": bool(st["t"] >= PASS_MIN_T),
        "holm_adjusted_p_not_above_p_of_t3": bool(st.get("p_holm", float("nan")) <= p_at_3),
        "same_sign_in_both_halves": bool(st["same_sign"]),
        "incremental_kronos_t_at_least_2": bool(inc["t"] >= PASS_MIN_INCREMENTAL_T),
    }
    verdict = "PASS" if all(c.values()) else "FAIL"
    # The clause "t >= 3 (Holm within the horizon family)" has a plainer reading (t >= 3 alone).
    # The stricter reading above is the one applied; this records whether the verdict would
    # differ under the plainer one, so that a result in that band is not reported as clear-cut.
    plain = all(v for k, v in c.items() if k != "holm_adjusted_p_not_above_p_of_t3")
    lo, hi = st["mean"] - 1.96 * st["se"], st["mean"] + 1.96 * st["se"]
    return {
        "values": {
            "mean_rank_ic": st["mean"],
            "newey_west_se": st["se"],
            "newey_west_t": st["t"],
            "p": st["p"],
            "p_holm": st.get("p_holm"),
            "p_of_t3": p_at_3,
            "half1": st["half1"],
            "half2": st["half2"],
            "incremental_kronos_coef": inc["mean"],
            "incremental_kronos_t": inc["t"],
            "holm_family": fam_present,
        },
        "criteria": c,
        "verdict": verdict,
        "holm_reading": {
            "applied": "t >= 3 and Holm-adjusted two-sided p <= p(t = 3)",
            "verdict_if_t_at_least_3_alone": "PASS" if plain else "FAIL",
            "verdict_depends_on_reading": bool(plain != (verdict == "PASS")),
        },
        "interval_95": {
            "note": "mean +/- 1.96 Newey-West s.e.; nominal and descriptive, not part of the rule",
            "low": lo,
            "high": hi,
            "contains_zero": bool(lo <= 0.0 <= hi),
            "paper_rank_ic": PAPER_RANK_IC,
            "contains_paper_rank_ic": bool(lo <= PAPER_RANK_IC <= hi),
            "interval_relative_to_paper_rank_ic": "contains"
            if lo <= PAPER_RANK_IC <= hi
            else ("lies wholly below" if hi < PAPER_RANK_IC else "lies wholly above"),
        },
    }


def analyze(
    bars: dict, primary: Run, secondary: Run | None, contrast: Run | None
) -> tuple[dict, list]:
    rows: list[dict] = []  # ic_series.csv

    def emit(run: Run, P: dict, subset: str, h: int, metric: str, series, n_names=None):
        for i, v in enumerate(series):
            if np.isfinite(v):
                rows.append(
                    {
                        "run": run.name,
                        "config": run.manifest["config_name"],
                        "window": run.manifest["window"],
                        "subset": subset,
                        "origin_index": P["k"][i],
                        "origin_date": P["dates"][i],
                        "h": h,
                        "metric": metric,
                        "value": float(v),
                    }
                )

    if not primary.scored:
        # Unreachable from the command line (an incomplete primary run is refused before any
        # forecast is read); kept so that nothing can ever be computed from a partial run.
        raise Incomplete("the primary run is incomplete; nothing is evaluated")
    out: dict = {}
    P = build_panel(primary, bars)
    masks = subset_masks(primary, bars)
    H = P["pred"].shape[1]
    all_h = list(range(1, H + 1))
    prim: dict = {"subsets": {}}
    for sub, mask in masks.items():
        blk = ic_block(P, mask, all_h)
        prim["subsets"][sub] = {"n_symbols": int(mask.sum()), "by_horizon": blk}
        for h, b in blk.items():
            emit(primary, P, sub, h, "rank_ic", b["series_rank"])
            emit(primary, P, sub, h, "pearson_ic", b["series_pearson"])
    trad = ic_block(P, masks["all"], [h for h in FAMILY if h <= H], target="on")
    prim["tradable_next_open"] = trad
    for h, b in trad.items():
        emit(primary, P, "all", h, "rank_ic_next_open", b["series_rank"])
    prim["incremental"], prim["simple_ranks"], prim["dispersion"], prim["deciles"] = {}, {}, {}, {}
    for h in FAMILY:
        if h > H:
            continue
        inc = incremental(P, masks["all"], h)
        prim["incremental"][h] = inc
        emit(primary, P, "all", h, "incremental_kronos_coef", inc["series_kronos"])
        prim["simple_ranks"][h] = factor_ics(P, masks["all"], h)
        dsp = dispersion(P, masks["all"], h)
        prim["dispersion"][h] = dsp
        emit(primary, P, "all", h, "dispersion_rank_corr", dsp["series_raw"])
        emit(primary, P, "all", h, "dispersion_partial_corr", dsp["series_partial"])
    for h in (5, 10):
        if h > H:
            continue
        dec = decile_spreads(P, masks["all"], h)
        prim["deciles"][h] = dec
        emit(primary, P, "all", h, "decile_top_minus_bottom_gross", dec["series_tb_gross"])
        emit(primary, P, "all", h, "decile_top_minus_universe_gross", dec["series_tu_gross"])
    out["primary"] = prim
    info = {"primary": run_info(primary, P)}

    if secondary is not None and secondary.scored:
        Ps = build_panel(secondary, bars)
        ms = subset_masks(secondary, bars)
        Hs = Ps["pred"].shape[1]
        sec = {
            "by_horizon": ic_block(Ps, ms["all"], list(range(1, Hs + 1))),
            "threshold_preview": {},
        }
        for h, b in sec["by_horizon"].items():
            emit(secondary, Ps, "all", h, "rank_ic", b["series_rank"])
            emit(secondary, Ps, "all", h, "pearson_ic", b["series_pearson"])
        for h in (5, 20):
            if h <= Hs:
                tp = threshold_preview(Ps, ms["all"], h)
                sec["threshold_preview"][h] = tp
                emit(secondary, Ps, "all", h, "threshold_share_selected", tp["series_share"])
        out["secondary"] = sec
        info["secondary"] = run_info(secondary, Ps)
    else:
        info["secondary"] = run_info(secondary, None)

    if contrast is not None and contrast.scored:
        Pc = build_panel(contrast, bars)
        mc = subset_masks(contrast, bars)
        Hc = Pc["pred"].shape[1]
        con = {"by_horizon": ic_block(Pc, mc["all"], list(range(1, Hc + 1))), "memorisation": {}}
        for h, b in con["by_horizon"].items():
            emit(contrast, Pc, "all", h, "rank_ic", b["series_rank"])
            emit(contrast, Pc, "all", h, "pearson_ic", b["series_pearson"])
        beyond = 0
        for o in contrast.origins:
            for h in FAMILY:
                if h <= o["steps"] and bars["dates"][o["t"] + h] > TRAINING_CUTOFF:
                    beyond += 1
        con["family_cells_with_target_after_training_cutoff"] = beyond
        for h in FAMILY:
            if h > min(H, Hc):
                continue
            a = con["by_horizon"][h]["rank"]
            b = prim["subsets"]["all"]["by_horizon"][h]["rank"]
            se_d = (
                math.sqrt(a["se"] ** 2 + b["se"] ** 2)
                if math.isfinite(a["se"]) and math.isfinite(b["se"])
                else float("nan")
            )
            d = a["mean"] - b["mean"]
            con["memorisation"][h] = {
                "contrast_ic": a["mean"],
                "contrast_se": a["se"],
                "test_ic": b["mean"],
                "test_se": b["se"],
                "difference": d,
                "se_of_difference": se_d,
                "exceeds_two_se": bool(d > 2 * se_d) if math.isfinite(se_d) else None,
                # Context for the flag, not part of it: a gap can come from a negative
                # test-window IC as well as from a positive contrast-window IC.
                "contrast_ic_positive": bool(a["mean"] > 0),
                "contrast_ic_more_than_two_se_above_zero": bool(a["mean"] > 2 * a["se"])
                if math.isfinite(a["se"])
                else None,
            }
        out["contrast"] = con
        info["contrast"] = run_info(contrast, Pc)
    else:
        info["contrast"] = run_info(contrast, None)

    # ---- decision rule (mechanical) ----
    dec: dict = {"endpoint": f"rank IC, h = {PRIMARY_H}, primary configuration, full universe"}
    full = prim["subsets"]["all"]["by_horizon"]
    if PRIMARY_H not in full or PRIMARY_H not in prim["incremental"]:
        raise IdentityError("the primary run has no h = 10; the primary endpoint does not exist")
    fam_present = [h for h in FAMILY if h in full]  # tier 2 generates h <= 10 only
    dec.update(
        decide(full[PRIMARY_H]["rank"], prim["incremental"][PRIMARY_H]["kronos"], fam_present)
    )
    out["decision"] = dec
    out["runs"] = info
    steps = int(primary.manifest["steps_requested"])
    n_sym = len(primary.symbols)
    full_n = int(bars["in_test"].sum())
    out["tier"] = {
        "tier": 1 if (steps == 20 and n_sym == full_n) else (2 if n_sym == full_n else 3),
        "steps": steps,
        "n_symbols": n_sym,
        "full_universe_n": full_n,
    }
    return out, rows


# --------------------------------------------------------------------------------- report
def f(x, nd=4, signed=True) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "n/a"
    return f"{x:+.{nd}f}" if signed else f"{x:.{nd}f}"


def bps(x) -> str:
    if x is None or not math.isfinite(x):
        return "n/a"
    return f"{x * 1e4:+.1f}"


def yn(b) -> str:
    return "n/a" if b is None else ("yes" if b else "no")


def not_scored_text(r: dict) -> str:
    """Cell text for a run whose numbers are absent: never started, or incomplete."""
    if not r.get("present"):
        return "not run"
    return f"incomplete ({r['origins_present']} of {r['origins_expected']} origins), not scored"


def ic_row(label: str, b: dict | None, holm_col: bool = False, absent: str = "not run") -> str:
    if b is None:
        return f"| {label} | {absent} |" + " |" * (11 if holm_col else 9)
    r, p = b["rank"], b["pearson"]
    cells = [
        label,
        str(r["n"]),
        f(b.get("n_names_mean"), 0, False),
        f(r["mean"]),
        f(r["se"], 4, False),
        f(r["t"], 2),
    ]
    if holm_col:
        cells += [f(r.get("p"), 4, False), f(r.get("p_holm"), 4, False)]
    cells += [f(r["half1"]), f(r["half2"]), yn(r["same_sign"]), f(p["mean"]), f(p["t"], 2)]
    return "| " + " | ".join(cells) + " |"


IC_HEAD = (
    "| Cell | Origins | Names | Mean rank IC | NW s.e. | NW t | First half | Second half | Same sign | "
    "Pearson IC (exploratory) | NW t (Pearson, exploratory) |\n|---|---|---|---|---|---|---|---|---|---|---|"
)
IC_HEAD_HOLM = (
    "| Horizon | Origins | Names | Mean rank IC | NW s.e. | NW t | p | Holm p | First half | Second half | "
    "Same sign | Pearson IC (exploratory) | NW t (Pearson, exploratory) |\n"
    "|---|---|---|---|---|---|---|---|---|---|---|---|---|"
)

DEVIATIONS = [
    "**Late origins.** An origin near the end of the window is given only as many steps as there are sessions on "
    "or before 2025-09-05 after it, so no date after 2025-09-05 is used even as a calendar feature. Generation is "
    "causal, so the retained steps are what a 20-step run would have produced. The last test origin therefore has "
    "fewer than 5 steps and enters no pre-registered horizon.",
    "**Seeds.** Path seeds are 42 + path index. So that results do not depend on batch size or device, every "
    "(origin, symbol, path) row owns a CPU generator whose 32-bit seed is the first four bytes of SHA-256 over "
    "`kronos-ic-r3/<window>/origin/<origin index>/symbol/<symbol>/path-seed/<42 + path index>`; the origin index, "
    "the path seeds and all row seeds are stored in each origin file, and the analysis recomputes the row seeds from "
    "this formula before it scores a file. Rows are sampled independently, as in upstream's batched sampler. "
    "Production runs one symbol per process and so reuses stream 42 + path for every symbol; that sharing of noise "
    "across symbols is not reproduced here. The production-configuration cells and the threshold preview therefore "
    "describe the frozen settings under independent draws, not under the exact streams the frozen books use.",
    "**Speed-up, not a variant.** The transformer reuses cached keys and values of earlier positions instead of "
    "recomputing the context at each step, and sampling (upstream's own top-p filter, softmax and "
    "`torch.multinomial`) runs on the CPU while the transformer runs on the accelerator. The validation section "
    "gives the measured agreement with upstream.",
    "**`t >= 3 (Holm within the horizon family)`** is applied in its stricter reading: the Newey-West t of the "
    "primary endpoint must be at least 3 and its Holm-adjusted two-sided p-value (family h = 5, 10, 20; normal "
    "reference) must not exceed the p-value of t = 3 (0.0027). That amounts to t >= 3.32 when the primary has the "
    "smallest p-value of the three, 3.21 when it has the middle one and 3.00 when it has the largest. Under the "
    "plainer reading (t >= 3 alone) a t between 3.00 and 3.32 could pass; the reading was fixed before any forecast "
    "was scored, and the decision section states whether the verdict would differ under the plainer one.",
    "**Newey-West.** Bartlett kernel, lag = ceil(h / 5) origins, variance of the mean of the per-origin series, "
    "no small-sample correction, normal p-values. Halves are the first ceil(n / 2) and the remaining scored origins. "
    "The p-values, the Holm p-values and every 'two standard errors' statement are nominal: with this few "
    "overlapping origins they understate tail probabilities. The validation section gives the measured rejection "
    "rates when the score carries no information. The rule itself is stated on t and on the mean, and is unchanged.",
    "**Interval in the lead.** The lead adds a nominal 95% interval (mean +/- 1.96 Newey-West standard errors) and "
    "says whether it contains zero and the paper's rank IC of 0.0622. This is a description of how tight the result "
    "is. It is not a pre-registered endpoint and takes no part in the verdict.",
    "**Incremental regression.** Per origin, ordinary least squares with an intercept of the realised-return rank "
    "on the Kronos rank and the four simple ranks, all ranks rescaled to [-0.5, 0.5]; the coefficient series is "
    "averaged with a Newey-West t. A name without 252 earlier sessions at an origin is left out of that origin's "
    "regression and of the 252-minus-21 rank. Realised volatility is the sample standard deviation of the last 20 "
    "daily log returns. Every simple rank uses bars up to the origin only.",
    "**Decile spreads.** A decile is floor(n / 10) names. Returns run from the open of origin + 1 to the close of "
    "origin + h. Net top-minus-bottom deducts 22 bps (a round trip on each leg); net top-minus-universe deducts "
    "11 bps (only the top decile is traded; the universe mean is a benchmark).",
    "**Dispersion** is the sample standard deviation across paths of the path return at h; the partial rank "
    "correlation controls for the 20-session realised-volatility rank.",
    "**Memorisation flag.** 'More than two standard errors' is read as two standard errors of the difference, "
    "sqrt(se_contrast^2 + se_test^2), with Newey-West standard errors. The contrast universe additionally requires "
    "every session from 2022-06-01. Contrast origins are scored by the same rule as test origins (origin + h on or "
    "before 2025-09-05), so a few of the latest contrast targets fall after June 2024; the count is given below. "
    "The flag compares two different market periods and fires on the gap alone, so the report also says whether "
    "the contrast-window IC is itself positive.",
    "**Snapshot-11 subset** means study-universe members that are complete members of data snapshot 11 (every XNYS "
    "session 2016-10-17 to 2025-09-05 in `massive` bars).",
    "**Threshold preview** uses steps 5 and 20 of the single 20-step generation of the production configuration.",
    "**`amount`** is volume x mean(open, high, low, close), the value upstream fills in when, as in production, "
    "no amount column is supplied.",
    "**Device check G0** compares the softmax of the first-step logits of both token heads (at T = 1 and at the "
    "sampling temperature) between CPU and the accelerator; the distribution after the top-p filter and every "
    "later step are also recorded in the check's output.",
    "**Pilot origin.** The first test origin (2024-07-01) was generated during the throughput pilot and kept, "
    "because the run is resumable. It was made by the same version of the script as every other origin (the run "
    "cannot be resumed by a different one). Its forecasts were not compared with realised returns before this "
    "analysis.",
    "**Production configuration before the primary run.** The pre-registration says the secondary configuration "
    "runs only after the primary finishes, and the script refuses the secondary run until then. Before the primary "
    "run, the production configuration was nevertheless used for validation: the device check on 32 series and the "
    "three-symbol equivalence check (each run once when the scripts were built and once more after the review "
    "repairs), the code review's own comparison of 24 production-configuration paths with upstream, and one "
    "full-size origin that the first pilot timed without saving it and without leaving a log. No forecast from "
    "any of these was kept or compared with realised returns.",
    "**Review repairs before the run.** After two adversarial reviews and before the long run, the scripts were "
    "hardened: a real look-ahead test, the script hash frozen into the run definition and stored in every origin "
    "file, stricter checks of every origin file at scoring time, a 20:00 UTC cut-off, distinct exit codes, no "
    "scoring of incomplete runs, and the wording and tables of this report. The sampling code was not changed "
    "(its syntax tree is identical before and after), and the pilot origin regenerated by the final script is "
    "bitwise identical to the first one; the validation section gives the records.",
    "**Look-ahead.** No bar after an origin can enter its input because the input is cut from a view that ends at "
    "the origin. That is true by construction, so it is tested from outside: for every origin the input is rebuilt "
    "with all later bars replaced by NaN and must be bit-for-bit identical, and an input deliberately cut one "
    "session late must be caught.",
    "**Rank IC at every generated horizon** is shown for completeness. Only h = 5, 10 and 20 are pre-registered "
    "endpoints; the other horizons are descriptive and carry no adjustment.",
    "**Incomplete runs are not scored.** The analysis refuses an incomplete primary run outright. An incomplete "
    "secondary or contrast run is reported as incomplete and none of its forecasts is read.",
]


def render(summary: dict, validation: dict, title_note: str = "") -> str:
    L: list[str] = []
    dec, runs, prim = summary["decision"], summary["runs"], summary["primary"]
    full = prim["subsets"]["all"]["by_horizon"]
    sec, con = summary.get("secondary"), summary.get("contrast")
    placebo = ((validation or {}).get("selftest") or {}).get("placebo")
    L.append(
        "# Kronos zero-shot cross-sectional rank IC on US daily bars (2026-11-10)" + title_note
    )
    L.append("")
    L.append(
        "Pre-registration: `docs/research/kronos/PREREGISTRATION_2026-11-10_kronos_cross_sectional_ic.md` "
        "(commit 9bc9d24)."
    )
    L.append("")
    pr = runs["primary"]
    v, iv, hr = dec["values"], dec["interval_95"], dec["holm_reading"]
    st = full[PRIMARY_H]["rank"]
    L.append(
        f"**{dec['verdict']}.** Kronos-small's zero-shot forecast had a mean cross-sectional rank IC of "
        f"{f(v['mean_rank_ic'])} at 10 sessions (Newey-West t {f(v['newey_west_t'], 2)}, {st['n']} origins, "
        f"{pr['n_symbols']} names, 2024-07-01 to 2025-09-05); the first and second halves were "
        f"{f(v['half1'])} and {f(v['half2'])}, and its coefficient alongside four simple ranks had t "
        f"{f(v['incremental_kronos_t'], 2)}."
    )
    if dec["verdict"] == "PASS":
        L.append(
            "Every pre-registered criterion is met. That justifies writing a new ADR and a new "
            "pre-registered prospective study that uses the forecast to rank candidates; it authorises "
            "nothing else and is not a profit claim."
        )
    else:
        failed = [CRITERION_WORDS[k] for k, ok in dec["criteria"].items() if not ok]
        L.append(
            "The pre-registered rule needs all of: mean rank IC at least 0.02, Newey-West t at least 3 "
            "after Holm, the same sign in both halves and an incremental t of at least 2. Not met: "
            + "; ".join(failed)
            + ". This closes zero-shot Kronos-small as a cross-sectional US daily "
            "signal; fine-tuning would need its own pre-registration."
        )
    L.append(
        f"A nominal 95% interval for the mean rank IC (mean +/- 1.96 Newey-West standard errors; a description, "
        f"not part of the rule) runs from {f(iv['low'])} to {f(iv['high'])}: it "
        f"{'contains' if iv['contains_zero'] else 'excludes'} zero and {iv['interval_relative_to_paper_rank_ic']} "
        f"the {iv['paper_rank_ic']:.4f} that the paper reports for Kronos-small"
        + (
            ", so this window alone does not rule out an IC of that size."
            if iv["contains_paper_rank_ic"]
            else "."
        )
    )
    ctx: list[str] = []
    if hr["verdict_depends_on_reading"]:
        ctx.append(
            "The verdict depends on how the pre-registered clause `t >= 3 (Holm within the horizon family)` is "
            f"read. Under the stricter reading applied here, which was fixed before any forecast was scored, it is "
            f"{dec['verdict']}; with t >= 3 alone it would be {hr['verdict_if_t_at_least_3_alone']}."
        )
    for nm, label in (
        ("secondary", "secondary (production configuration)"),
        ("contrast", "contrast-window"),
    ):
        r = runs[nm]
        if not r["present"]:
            ctx.append(f"The {label} run was not run.")
        elif not r["scored"]:
            ctx.append(
                f"The {label} run is incomplete ({r['origins_present']} of {r['origins_expected']} origins) and "
                "is not scored."
            )
    mem = (con or {}).get("memorisation", {}).get(PRIMARY_H)
    if mem is not None:
        if not mem["contrast_ic_positive"]:
            own = "not positive"
        elif mem["contrast_ic_more_than_two_se_above_zero"]:
            own = "positive and more than two of its own standard errors above zero"
        else:
            own = "positive but within two of its own standard errors of zero"
        ctx.append(
            f"Memorisation check at 10 sessions: contrast-window IC {f(mem['contrast_ic'])} against test-window "
            f"IC {f(mem['test_ic'])}, difference {f(mem['difference'])} with standard error "
            f"{f(mem['se_of_difference'], 4, False)} - "
            + (
                "more than two standard errors, reported as evidence of memorisation."
                if mem["exceeds_two_se"]
                else "not more than two standard errors."
            )
            + f" The contrast-window IC is itself {own}. The two windows are different market periods, so a "
            "gap can also reflect the period."
        )
    if ctx:
        L.append("")
        L.extend(ctx)
    L.append("")
    L.append("## Decision rule")
    L.append("")
    c = dec["criteria"]
    L.append(
        "| Criterion (primary endpoint: h = 10, paper configuration, full universe) | Value | Required | Met |"
    )
    L.append("|---|---|---|---|")
    L.append(
        f"| Mean rank IC | {f(v['mean_rank_ic'])} | >= 0.02 | {yn(c['mean_rank_ic_at_least_0.02'])} |"
    )
    L.append(
        f"| Newey-West t (lag 2) | {f(v['newey_west_t'], 2)} | >= 3 | {yn(c['newey_west_t_at_least_3'])} |"
    )
    L.append(
        f"| Holm-adjusted p within h = {', '.join(str(h) for h in v['holm_family'])} | "
        f"{f(v['p_holm'], 4, False)} | <= {v['p_of_t3']:.4f} "
        f"| {yn(c['holm_adjusted_p_not_above_p_of_t3'])} |"
    )
    L.append(
        f"| Half-window means | {f(v['half1'])} / {f(v['half2'])} | same sign | "
        f"{yn(c['same_sign_in_both_halves'])} |"
    )
    L.append(
        f"| Incremental Kronos coefficient t | {f(v['incremental_kronos_t'], 2)} | >= 2 | "
        f"{yn(c['incremental_kronos_t_at_least_2'])} |"
    )
    L.append(f"| **Verdict** | **{dec['verdict']}** | | |")
    L.append("")
    L.append(
        f"Not part of the rule: nominal 95% interval {f(iv['low'])} to {f(iv['high'])} (Newey-West s.e. "
        f"{f(v['newey_west_se'], 4, False)}); verdict if the Holm clause were read as t >= 3 alone: "
        f"{hr['verdict_if_t_at_least_3_alone']} "
        f"({'differs from' if hr['verdict_depends_on_reading'] else 'the same as'} the verdict above)."
    )
    L.append("")
    L.append("## What was run")
    L.append("")
    tier = summary["tier"]
    L.append(
        f"Compute tier {tier['tier']}: {tier['steps']} generated steps, {tier['n_symbols']} names "
        f"(full universe {tier['full_universe_n']})."
    )
    L.append("")
    L.append(
        "| Run | Configuration | Window | Names | Origins present / expected | First origin | Last origin | "
        "Scored origins at h = 5 / 10 / 20 |"
    )
    L.append("|---|---|---|---|---|---|---|---|")
    for nm, label in (("primary", "Primary"), ("secondary", "Secondary"), ("contrast", "Contrast")):
        r = runs[nm]
        if not r["present"]:
            L.append(f"| {label} | not run | | | | | | |")
            continue
        cfg = r["config"]
        left = (
            f"| {label} | {r['config_name']}: look-back {cfg['lookback']}, T = {cfg['T']}, top-p = {cfg['top_p']}, "
            f"{cfg['paths']} paths | {r['window']} | {r['n_symbols']} | {r['origins_present']} / "
            f"{r['origins_expected']}"
        )
        if not r["scored"]:
            L.append(
                left
                + f" (incomplete, not scored) | | {r['last_origin'] or 'none'} (last present) | not scored |"
            )
            continue
        sc = r["scored_origins_by_horizon"]
        L.append(
            left
            + f" | {r['first_origin']} | {r['last_origin']} | "
            + " / ".join(str(sc.get(h, sc.get(str(h), 0))) for h in FAMILY)
            + " |"
        )
    used = [
        f"{label.lower()} {' / '.join(runs[nm]['batch_rows_used'])} rows per chunk on "
        f"{' / '.join(runs[nm]['threads_used'])} CPU threads"
        for nm, label in (
            ("primary", "Primary"),
            ("secondary", "Secondary"),
            ("contrast", "Contrast"),
        )
        if runs[nm].get("scored")
    ]
    L.append("")
    L.append(
        "All runs were written by one version of the inference script (SHA-256 "
        f"`{str(pr['script_sha256'])[:16]}...`). Recorded in the origin files: "
        + "; ".join(used)
        + "."
    )
    L.append("")
    L.append(
        "## Primary and secondary endpoints: rank IC by horizon (paper configuration, full universe)"
    )
    L.append("")
    L.append(
        "Predicted return at h is the mean over paths of the predicted close at origin + h divided by the "
        "observed close at the origin, minus 1; realised return is close to close."
    )
    L.append("")
    L.append(IC_HEAD_HOLM)
    for h in FAMILY:
        tag = f"h = {h}" + (" (primary)" if h == PRIMARY_H else " (secondary)")
        if h in full:
            L.append(ic_row(tag, full[h], holm_col=True))
        else:
            L.append(f"| {tag} | not generated in this tier |" + " |" * 11)
    L.append("")
    note = (
        "The p and Holm p columns use a normal reference and are nominal: with this few overlapping origins "
        "they run small."
    )
    if placebo:
        fx = placebo["fixed_score_per_name"]
        b10 = fx["by_h"]["10"]
        note += (
            f" When {fx['simulations']:,} random scores with no information were scored against this window "
            f"in the same way, |t| >= 2 occurred in {b10['share_abs_t_ge_2']:.2%} of cases at h = 10 (nominal "
            f"4.55%) and t >= 3 in {b10['share_t_ge_3']:.2%} (nominal 0.13%); the IC part of the PASS rule was "
            f"met in {fx['ic_part_of_rule_pass_share']:.2%}."
        )
    L.append(note + " The Pearson columns are exploratory.")
    L.append("")
    L.append("Tradable version (entered at the next open, exit at the close of origin + h):")
    L.append("")
    L.append(IC_HEAD)
    for h in FAMILY:
        L.append(
            ic_row(
                f"h = {h}, next-open entry",
                prim["tradable_next_open"].get(h),
                absent="not generated in this tier",
            )
        )
    L.append("")
    L.append("## Exploratory cells (no adjustment)")
    L.append("")
    L.append(
        "The production-configuration rows use the frozen books' settings (look-back 128, T = 1.0, top-p = 0.9, "
        "3 paths) with an independent random stream for every name, not the shared stream the frozen books use "
        "(deviation 2). They describe those settings on a broad universe; they are not the frozen books' outcome."
    )
    L.append("")
    L.append(IC_HEAD)
    for h in FAMILY:
        L.append(
            ic_row(
                f"Production configuration, h = {h}",
                sec["by_horizon"].get(h) if sec else None,
                absent=not_scored_text(runs["secondary"]),
            )
        )
    for sub, label in (("stocks", "Stocks only"), ("snapshot11", "Snapshot-11 subset")):
        blk = prim["subsets"][sub]
        for h in FAMILY:
            L.append(
                ic_row(
                    f"{label} ({blk['n_symbols']} names), h = {h}",
                    blk["by_horizon"].get(h),
                    absent="not generated in this tier",
                )
            )
    L.append("")
    L.append(
        "Pearson IC of the primary configuration (exploratory) is in the right-hand columns of the tables above."
    )
    L.append("")
    L.append("## Incremental value: Kronos rank alongside four simple ranks")
    L.append("")
    L.append(
        "| Horizon | Origins | Names | Kronos coef. | NW t | "
        + " | ".join(f"{FACTOR_LABEL[x]} coef. (t)" for x in FACTORS)
        + " |"
    )
    L.append("|---|---|---|---|---|" + "---|" * len(FACTORS))
    for h in FAMILY:
        inc = prim["incremental"].get(h)
        if inc is None:
            L.append(f"| h = {h} | not generated in this tier | | | |" + " |" * len(FACTORS))
            continue
        k = inc["kronos"]
        L.append(
            f"| h = {h} | {k['n']} | {f(inc['n_names_mean'], 0, False)} | {f(k['mean'])} | {f(k['t'], 2)} | "
            + " | ".join(f"{f(inc[x]['mean'])} ({f(inc[x]['t'], 2)})" for x in FACTORS)
            + " |"
        )
    L.append("")
    L.append(
        "Rank IC of each simple rank alone (same origins, same realised returns, same statistics as the "
        "table for the Kronos forecast):"
    )
    L.append("")
    L.append(
        "| Simple rank | Horizon | Origins | Names | Mean rank IC | NW s.e. | NW t | First half | Second half | "
        "Same sign |"
    )
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for x in FACTORS:
        for h in FAMILY:
            s = prim["simple_ranks"].get(h, {}).get(x)
            if s is None:
                L.append(
                    f"| {FACTOR_LABEL[x]} | h = {h} | not generated in this tier | | | | | | | |"
                )
                continue
            L.append(
                f"| {FACTOR_LABEL[x]} | h = {h} | {s['n']} | {f(s['n_names_mean'], 0, False)} | {f(s['mean'])} | "
                f"{f(s['se'], 4, False)} | {f(s['t'], 2)} | {f(s['half1'])} | {f(s['half2'])} | "
                f"{yn(s['same_sign'])} |"
            )
    L.append("")
    L.append(
        "## Economic size: decile spreads, entered at the next open (basis points per holding period)"
    )
    L.append("")
    L.append(
        "| Horizon | Origins | Names per decile | Top - bottom gross | Top - bottom net of 22 bps (NW t) | "
        "Top - universe gross | Top - universe net of 11 bps (NW t) |"
    )
    L.append("|---|---|---|---|---|---|---|")
    for h in (5, 10):
        d = prim["deciles"].get(h)
        if d is None:
            L.append(f"| h = {h} | not generated in this tier | | | | | |")
            continue
        L.append(
            f"| h = {h} | {d['top_minus_bottom_gross']['n']} | {f(d['names_per_decile_mean'], 0, False)} | "
            f"{bps(d['top_minus_bottom_gross']['mean'])} | {bps(d['top_minus_bottom_net']['mean'])} "
            f"({f(d['top_minus_bottom_net']['t'], 2)}) | {bps(d['top_minus_universe_gross']['mean'])} | "
            f"{bps(d['top_minus_universe_net']['mean'])} ({f(d['top_minus_universe_net']['t'], 2)}) |"
        )
    L.append("")
    L.append("## Dispersion: does path spread rank realised absolute return?")
    L.append("")
    L.append(
        "| Horizon | Origins | Rank correlation with abs. realised return (NW t) | "
        "Partial, given 20-session realised volatility (NW t) |"
    )
    L.append("|---|---|---|---|")
    for h in FAMILY:
        d = prim["dispersion"].get(h)
        if d is None:
            L.append(f"| h = {h} | not generated in this tier | | |")
            continue
        L.append(
            f"| h = {h} | {d['rank_corr']['n']} | {f(d['rank_corr']['mean'])} ({f(d['rank_corr']['t'], 2)}) | "
            f"{f(d['partial_given_rvol20']['mean'])} ({f(d['partial_given_rvol20']['t'], 2)}) |"
        )
    L.append("")
    L.append("## Threshold preview (production configuration)")
    L.append("")
    L.append(
        "Share of names for which the mean terminal close exceeds the last close x 1.0011, and the mean realised "
        "close-to-close return of selected and unselected names. This describes the frozen rule's condition on "
        "a broad universe. It is not the frozen books' outcome and is not used to tune them. The three paths "
        "here use an independent random stream for every name; the frozen books give every name the same "
        "three streams (deviation 2), so the share selected there can differ."
    )
    L.append("")
    L.append(
        "| Horizon | Origins | Share selected (min - max) | Mean return, selected | Mean return, unselected | "
        "Selected - unselected (NW t) |"
    )
    L.append("|---|---|---|---|---|---|")
    for h in (5, 20):
        tp = sec["threshold_preview"].get(h) if sec else None
        if tp is None:
            L.append(f"| h = {h} | {not_scored_text(runs['secondary'])} | | | | |")
            continue
        L.append(
            f"| h = {h} | {tp['share_selected']['n']} | {tp['share_selected']['mean']:.1%} "
            f"({tp['share_selected_min']:.1%} - {tp['share_selected_max']:.1%}) | "
            f"{bps(tp['mean_return_selected']['mean'])} bps | {bps(tp['mean_return_unselected']['mean'])} bps | "
            f"{bps(tp['selected_minus_unselected']['mean'])} bps ({f(tp['selected_minus_unselected']['t'], 2)}) |"
        )
    L.append("")
    L.append(
        "## Memorisation contrast (paper configuration, contrast window 2023-01-03 to 2024-06-14)"
    )
    L.append("")
    rc = runs["contrast"]
    if rc["scored"]:
        L.append(
            f"Contrast origins scored: {rc['origins_present']} of {rc['origins_expected']}, from "
            f"{rc['first_origin']} to {rc['last_origin']}; {rc['n_symbols']} names."
        )
        L.append("")
    L.append(
        "| Horizon | Contrast IC (NW s.e.) | Test IC (NW s.e.) | Difference | s.e. of difference | "
        "More than two s.e.? | Contrast IC itself positive? |"
    )
    L.append("|---|---|---|---|---|---|---|")
    for h in FAMILY:
        m = con["memorisation"].get(h) if con else None
        if m is None:
            L.append(f"| h = {h} | {not_scored_text(rc)} | | | | | |")
            continue
        L.append(
            f"| h = {h} | {f(m['contrast_ic'])} ({f(m['contrast_se'], 4, False)}) | {f(m['test_ic'])} "
            f"({f(m['test_se'], 4, False)}) | {f(m['difference'])} | {f(m['se_of_difference'], 4, False)} | "
            f"{yn(m['exceeds_two_se'])} | {yn(m['contrast_ic_positive'])} |"
        )
    if con:
        L.append("")
        L.append(
            f"Contrast origin-horizon cells (h = 5, 10, 20) whose target date falls after 2024-06-30: "
            f"{con['family_cells_with_target_after_training_cutoff']}. Standard errors are nominal "
            "(deviation 5), and the two windows are different market periods."
        )
    L.append("")
    L.append(
        "## Rank IC at every generated horizon (descriptive, not a pre-registered endpoint, no adjustment)"
    )
    L.append("")
    L.append(
        "Paper configuration, full universe. Only h = 5, 10 and 20 are pre-registered; the other rows are shown "
        "so that nothing generated is left out."
    )
    L.append("")
    L.append("| h | Origins | Mean rank IC | NW t | h | Origins | Mean rank IC | NW t |")
    L.append("|---|---|---|---|---|---|---|---|")
    hs = sorted(full)
    half = (len(hs) + 1) // 2
    for i in range(half):
        a = hs[i]
        left = f"| {a} | {full[a]['rank']['n']} | {f(full[a]['rank']['mean'])} | {f(full[a]['rank']['t'], 2)} "
        if i + half < len(hs):
            b = hs[i + half]
            right = f"| {b} | {full[b]['rank']['n']} | {f(full[b]['rank']['mean'])} | {f(full[b]['rank']['t'], 2)} |"
        else:
            right = "| | | | |"
        L.append(left + right)
    L.append("")
    L.append("## Validation before the run")
    L.append("")
    lines = validation_lines(validation) if validation else []
    if lines:
        for line in lines:
            L.append(f"- {line}")
    else:
        L.append("- Validation records were not found next to the raw outputs.")
    L.append("")
    L.append("## Deviations and clarifications")
    L.append("")
    for i, d in enumerate(DEVIATIONS, 1):
        L.append(f"{i}. {d}")
    extra = summary.get("extra_notes") or []
    for j, d in enumerate(extra, len(DEVIATIONS) + 1):
        L.append(f"{j}. {d}")
    L.append("")
    L.append("## Limits")
    L.append("")
    L.append(
        "One model size, one tokenizer, daily bars, a survivor-conditioned list chosen in 2025, one 14-month "
        "window containing one market regime, overlapping horizons. Per-origin values are in `ic_series.csv`; "
        "every number above is in `summary.json`."
    )
    L.append("")
    L.append("Research signal only — no order was placed.")
    L.append("")
    return "\n".join(L)


def validation_lines(v: dict) -> list[str]:
    out = []
    for key in ("g0", "g0_production"):
        g = v.get(key)
        if g:
            out.append(
                f"Device check G0, {g['config']} configuration ({g['n_series']} series, origin "
                f"{g['origin_date']}): largest difference in first-step class probabilities between CPU and "
                f"{g['device']} was {g['g0_max_first_step_class_prob_diff']:.2e} (limit 1e-3): "
                f"{'passed' if g['g0_pass'] else 'FAILED'}."
            )
            fr = g.get("free_running")
            if fr:
                out.append(
                    f"Same seeds on CPU and on {g['device']}, {g['config']} configuration ({fr['series']} "
                    f"series): {fr['paths_identical_cpu_vs_device']} of {fr['paths_total']} paths identical; one "
                    f"chunk versus four chunks bitwise identical: "
                    f"{yn(fr['bitwise_identical_one_chunk_vs_four_chunks'])}."
                )
    e = v.get("equivalence")
    if e:
        for cname, c in e["configs"].items():
            kv = c["kv_cache"]
            line = (
                f"Equivalence with upstream `KronosPredictor.predict` on CPU ({cname} configuration, "
                f"{', '.join(e['symbols'])}, origin {c['origin_date']}): {kv['paths_identical_to_upstream']} of "
                f"{kv['paths_total']} seeded paths identical (largest relative difference in predicted close "
                f"{kv['max_rel_diff_close']:.1e}); first-step logits differ by at most "
                f"{c['first_step_s1_logit_max_abs_diff_vs_upstream']['kv_cache']:.1e}."
            )
            m = c.get("mean_of_paths")
            if m:
                line += (
                    f" Mean of {m['paths']} independent paths against upstream's own {m['paths']}-path mean: "
                    f"largest |z| {m['max_abs_z']:.2f} over {m['cells']} symbol-step cells, "
                    f"{m['share_abs_z_below_2']:.0%} below 2."
                )
            out.append(line)
    for key in ("inputs_paper_test", "inputs_production_test", "inputs_paper_contrast"):
        la = (v.get(key) or {}).get("look_ahead_test")
        if la:
            i = v[key]
            out.append(
                f"Look-ahead test, {i['config']} configuration on the {i['window']} window: inputs bit-for-bit "
                f"unchanged with every later bar set to NaN at {la['origins_identical']} of "
                f"{la['origins_tested']} origins; an input cut one session late was caught at "
                f"{la['negative_control_caught']} of {la['negative_control_origins']}."
            )
    s = v.get("selftest")
    if s:
        n = s["noise"]
        out.append(
            f"Synthetic noise forecasts through the whole analysis ({n['seeds']} seeds): mean rank IC at h = 10 "
            f"averaged {n['h10_mean_of_means']:+.4f}; the rule returned "
            f"{', '.join(n['verdicts_first_three_seeds'])} on the seeds pushed through it."
        )
        pl = s.get("placebo")
        if pl:
            for key, label in (
                ("fixed_score_per_name", "one fixed random score per name"),
                ("fresh_noise_each_origin", "fresh noise at every origin"),
            ):
                b = pl[key]
                out.append(
                    f"Rejection rates with no information ({label}, {b['simulations']:,} simulations scored "
                    "against this window's realised returns; no forecast is read): |t| >= 2 in "
                    + " / ".join(
                        f"{b['by_h'][h]['share_abs_t_ge_2']:.2%}" for h in ("5", "10", "20")
                    )
                    + " of cases at h = 5 / 10 / 20 (nominal 4.55%); t >= 3 in "
                    + " / ".join(f"{b['by_h'][h]['share_t_ge_3']:.2%}" for h in ("5", "10", "20"))
                    + f" (nominal 0.13%); IC part of the PASS rule met in {b['ic_part_of_rule_pass_share']:.2%}."
                )
        p = s["planted"]
        out.append(
            f"Planted signal (target rank IC {p['target_ic']:.3f}): recovered "
            + ", ".join(
                f"{p['recovered'][h]['mean']:+.4f} (t {p['recovered'][h]['t']:.1f}) at h = {h}"
                for h in ("5", "10", "20")
            )
            + "."
        )
        o = s["oracle"]
        out.append(
            f"Oracle forecast (equals the future close): rank IC {o['aligned']['10']:.4f} at h = 10; shifted by "
            f"one origin {o['shift_one_origin']['5']:+.3f} / {o['shift_one_origin']['10']:+.3f} / "
            f"{o['shift_one_origin']['20']:+.3f} at h = 5 / 10 / 20 (return windows then overlap by "
            f"0, 1/2 and 3/4)."
        )
        g = s.get("guards")
        if g:
            out.append(
                f"Analysis guards on synthetic run directories: {sum(bool(x) for x in g.values())} of {len(g)} "
                "passed (an incomplete primary is refused; an incomplete secondary is reported and not scored; "
                "a changed last close, shifted future dates, a foreign script hash, altered row seeds and a "
                "stray origin file each stop the analysis; the directories are put back unchanged)."
            )
    p = v.get("pilot")
    if p:
        line = (
            f"Throughput pilot: {p['seconds_per_origin']:.1f} s for one origin at full size on {p['device']}; "
            f"tier {p['tier']} chosen before any score was examined."
        )
        rg = p.get("regenerated_vs_earlier_pilot")
        if rg:
            line += (
                f" The pilot origin regenerated by the final script is bitwise identical to the earlier pilot in "
                f"{rg['origin_files_bitwise_identical']} of {rg['origin_files_compared']} files."
            )
        out.append(line)
    a = v.get("repair_code_compare")
    if a:
        ib = a["input_builder_origin_inputs"]
        out.append(
            f"Review repairs: {a['sampling_definitions_identical']} of {a['sampling_definitions_checked']} "
            "definitions that make up the sampler have an identical syntax tree before and after the repairs; "
            f"the input builder lost {ib['unfailable_checks_removed']} checks that could not fail and is "
            f"otherwise {'identical' if ib['otherwise_identical'] else 'DIFFERENT'}."
        )
        an = a.get("analysis")
        if an:
            out.append(
                f"Review repairs, analysis: {an['statistics_definitions_identical']} of "
                f"{an['statistics_definitions_checked']} definitions that compute the statistics have an "
                "identical syntax tree before and after the repairs, and the five PASS criteria are "
                f"{'identical' if an['decision_criteria_identical'] else 'DIFFERENT'}."
            )
    return out


def load_validation(directory: Path) -> dict:
    v = {}
    for key, name in (
        ("g0", "g0_paper_mps.json"),
        ("g0_production", "g0_production_mps.json"),
        ("equivalence", "equivalence.json"),
        ("inputs_paper_test", "inputs_paper_test.json"),
        ("inputs_production_test", "inputs_production_test.json"),
        ("inputs_paper_contrast", "inputs_paper_contrast.json"),
        ("selftest", "selftest_summary.json"),
        ("pilot", "pilot.json"),
        ("repair_code_compare", "repair_code_compare.json"),
    ):
        p = directory / name
        if p.exists():
            v[key] = json.loads(p.read_text())
    for key, name in (("g0", "g0_paper_cpu.json"), ("g0_production", "g0_production_cpu.json")):
        if key not in v and (directory / name).exists():
            v[key] = json.loads((directory / name).read_text())
    return v


def write_outputs(
    out_dir: Path, summary: dict, rows: list, validation: dict, title_note: str = ""
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    clean = strip(summary)
    clean["generated_utc"] = datetime.now(UTC).isoformat(timespec="seconds")
    clean["validation"] = validation
    clean["deviations_and_clarifications"] = DEVIATIONS + (summary.get("extra_notes") or [])
    tmp = out_dir / "summary.json.tmp"
    tmp.write_text(json.dumps(clean, indent=2, sort_keys=True) + "\n")
    tmp.replace(out_dir / "summary.json")
    tmp = out_dir / "ic_series.csv.tmp"
    with tmp.open("w", newline="") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=[
                "run",
                "config",
                "window",
                "subset",
                "origin_index",
                "origin_date",
                "h",
                "metric",
                "value",
            ],
        )
        w.writeheader()
        for r in rows:
            w.writerow({**r, "value": f"{r['value']:.8f}"})
    tmp.replace(out_dir / "ic_series.csv")
    tmp = out_dir / (RESULTS_NAME + ".tmp")
    tmp.write_text(render(clean_for_render(summary), validation, title_note))
    tmp.replace(out_dir / RESULTS_NAME)


def clean_for_render(summary: dict) -> dict:
    return summary


PREREGISTERED_CELLS = (
    "Primary endpoint: rank IC at h = 10, paper configuration, full universe",
    "Secondary endpoints: rank IC at h = 5 and h = 20 (Holm with the primary)",
    "Tradable version from the next open",
    "Exploratory: production configuration; stocks only; snapshot-11 subset; Pearson IC",
    "Incremental value alongside four simple ranks, and each simple rank alone",
    "Economic size: decile spreads at h = 5 and h = 10",
    "Dispersion against absolute realised return",
    "Threshold preview (production configuration)",
    "Memorisation contrast (2023-01-03 to 2024-06-14)",
    "Decision rule (PASS / FAIL)",
)


def render_notice(runs: dict, validation: dict) -> str:
    """The results file when the primary run did not finish: what was run, and nothing else.
    No forecast is read to write it and it contains no outcome number."""
    pr = runs["primary"]
    L = [
        "# Kronos zero-shot cross-sectional rank IC on US daily bars (2026-11-10)",
        "",
        "Pre-registration: `docs/research/kronos/PREREGISTRATION_2026-11-10_kronos_cross_sectional_ic.md` "
        "(commit 9bc9d24).",
        "",
        f"**Not evaluated.** The primary run is incomplete: {pr['origins_present']} of "
        f"{pr['origins_expected']} origins were generated. No forecast was scored, no endpoint was computed and "
        "the decision rule was not applied, so nothing here is an interim look. The pre-registered question is "
        "still open.",
        "",
        "## What was run",
        "",
        "| Run | Configuration | Window | Names | Origins present / expected | Last origin present | Scored |",
        "|---|---|---|---|---|---|---|",
    ]
    for nm, label in (("primary", "Primary"), ("secondary", "Secondary"), ("contrast", "Contrast")):
        r = runs[nm]
        if not r["present"]:
            L.append(f"| {label} | not run | | | | | no |")
            continue
        cfg = r["config"]
        L.append(
            f"| {label} | {r['config_name']}: look-back {cfg['lookback']}, T = {cfg['T']}, top-p = {cfg['top_p']}, "
            f"{cfg['paths']} paths | {r['window']} | {r['n_symbols']} | {r['origins_present']} / "
            f"{r['origins_expected']} | {r['last_origin'] or 'none'} | no |"
        )
    L += ["", "## Pre-registered cells", "", "| Cell | Status |", "|---|---|"]
    L += [f"| {c} | not evaluated: the primary run is incomplete |" for c in PREREGISTERED_CELLS]
    L += ["", "## Validation before the run", ""]
    lines = validation_lines(validation) if validation else []
    L += [f"- {line}" for line in lines] or [
        "- Validation records were not found next to the raw outputs."
    ]
    L += [
        "",
        "## Deviations and clarifications",
        "",
        "1. The primary run did not finish, so the analysis stopped before reading any forecast. This file is "
        "written by the analysis script's `--incomplete-notice` option and holds no outcome number.",
        "2. The run directories can be resumed only by the same version of the inference script, and only "
        "outside 20:00-00:15 UTC. Resuming is a continuation of the same pre-registered run, not a new variant.",
        "3. Before the primary run the production configuration was used for validation only (device check, "
        "equivalence with upstream, the code review's comparison of 24 paths with upstream, and one unsaved "
        "origin timed by the first pilot without a log). No forecast from these was kept or compared with "
        "realised returns.",
        "",
        "Research signal only — no order was placed.",
        "",
    ]
    return "\n".join(L)


def write_notice(out_dir: Path, runs: dict, validation: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "decision": {"verdict": "NOT EVALUATED", "reason": "the primary run is incomplete"},
        "runs": strip(runs),
        "validation": validation,
        "generated_utc": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    (out_dir / "summary.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    (out_dir / "ic_series.csv").write_text(
        "run,config,window,subset,origin_index,origin_date,h,metric,value\n"
    )
    (out_dir / RESULTS_NAME).write_text(render_notice(runs, validation))


# ------------------------------------------------------------------------------- selftest
SYNTHETIC = "synthetic-selftest"


def synth_run(name, bars, symbols, config_name, paths, window, steps, maker) -> Run:
    col = {s: j for j, s in enumerate(bars["symbols"])}
    cols = np.array([col[s] for s in symbols])
    plan = window_plan(bars["dates"], window, steps)
    man = {
        "config_name": config_name,
        "config": {"paths": paths, "lookback": 0, "T": 0.0, "top_p": 0.0},
        "window": window,
        "steps_requested": steps,
        "n_symbols": len(symbols),
        "origins": plan,
        "device": "synthetic",
        "kv_cache": None,
        "universe_sha256": SYNTHETIC,
        "bars_content_sha256": bars["_content_sha256"],
        "script_sha256": SYNTHETIC,
    }
    run = Run(name=name, manifest=man, symbols=list(symbols), cols=cols)
    wanted = [p for p in plan if p["steps"] > 0]
    run.expected = len(wanted)
    for p in wanted:
        pc = maker(p, cols)
        run.origins.append(
            {
                "k": p["origin_index"],
                "date": p["date"],
                "t": p["bar_index"],
                "steps": p["steps"],
                "pred_close": pc.astype(np.float32),
            }
        )
    run.present = len(run.origins)
    return run


def save_run(run: Run, directory: Path, bars: dict) -> None:
    """Write a synthetic run in the on-disk format of kronos_ic_infer.py, with every key the
    loader checks, so that the self-test goes through the same checks as a real run."""
    directory.mkdir(parents=True, exist_ok=True)
    man = run.manifest
    (directory / "run_manifest.json").write_text(json.dumps(man))
    for o in run.origins:
        meta = {k: man[k] for k in ORIGIN_MATCHES_MANIFEST}
        meta.update(
            {
                "origin_index": o["k"],
                "origin_date": o["date"],
                "steps": o["steps"],
                "lookback_last": o["date"],
                "future_dates": bars["dates"][o["t"] + 1 : o["t"] + 1 + o["steps"]],
                "path_seeds": [BASE_SEED + i for i in range(run.paths)],
                "batch_rows": None,
                "threads": None,
            }
        )
        np.savez_compressed(
            directory / f"origin_{o['k']:03d}_{o['date']}.npz",
            meta=np.array(json.dumps(meta)),
            symbols=np.array(run.symbols),
            pred_close=o["pred_close"],
            last_close=bars["close"][o["t"], run.cols],
            row_seeds=row_seeds(man["window"], o["k"], run.symbols, run.paths),
        )


def placebo_size(bars: dict, symbols: list, sims_fixed: int, sims_fresh: int, seed: int) -> dict:
    """How often the test rejects when the score carries no information at all.

    Random scores are ranked against the realised returns of the test window exactly as a
    forecast would be: Spearman per origin, Newey-West with lag ceil(h / 5), Holm over
    h = 5, 10, 20, half-window signs. No forecast is read. Two kinds of score are used: one
    fixed random score per name (a characteristic that never changes; the harder case, because
    its IC series is autocorrelated at overlapping horizons) and fresh noise at every origin.
    The incremental-regression criterion is not applied, so the pass rates below are upper
    bounds on how often the full rule would pass.
    """
    col = {s: j for j, s in enumerate(bars["symbols"])}
    close = bars["close"][:, np.array([col[s] for s in symbols])]
    last = len(bars["dates"]) - 1
    plan = [p for p in window_plan(bars["dates"], "test", 20) if p["steps"] > 0]
    n = len(symbols)

    def zrank_rows(M: np.ndarray) -> np.ndarray:
        """Standardised ranks of each row (continuous values, so no ties)."""
        r = np.argsort(np.argsort(M, axis=-1), axis=-1).astype(np.float64)
        r -= (n - 1) / 2.0
        return r / math.sqrt((n * n - 1) / 12.0)

    Z = {}  # h -> standardised ranks of realised returns, one row per scored origin
    for h in FAMILY:
        rows = []
        for p in plan:
            t = p["bar_index"]
            if t + h > last:
                break  # scored origins are a prefix of the plan
            r = rankdata(close[t + h] / close[t] - 1.0)
            r = r - r.mean()
            rows.append(r / math.sqrt(float(r @ r) / n))
        Z[h] = np.stack(rows)

    def nw_rows(X: np.ndarray, lag: int):
        """nw_stats for every row of X at once: mean, t and the two half-window means."""
        K = X.shape[1]
        m = X.mean(axis=1)
        d = X - m[:, None]
        var = (d * d).sum(axis=1) / K
        for j in range(1, min(lag, K - 1) + 1):
            var += 2.0 * (1.0 - j / (lag + 1.0)) * (d[:, j:] * d[:, :-j]).sum(axis=1) / K
        cut = math.ceil(K / 2)
        return m, m / np.sqrt(var / K), X[:, :cut].mean(axis=1), X[:, cut:].mean(axis=1)

    erfc = np.vectorize(math.erfc)
    p_at_3 = normal_p_two_sided(PASS_MIN_T)

    def summarise(ic: dict, sims: int) -> dict:
        res = {h: nw_rows(ic[h], nw_lag(h)) for h in FAMILY}
        # the vectorised statistics must equal the analyzer's own on a single series
        for h in FAMILY:
            one = nw_stats(ic[h][0], nw_lag(h))
            if abs(one["t"] - res[h][1][0]) > 1e-9 or abs(one["mean"] - res[h][0][0]) > 1e-12:
                raise IdentityError("placebo: vectorised Newey-West disagrees with nw_stats")
        pv = np.stack([erfc(np.abs(res[h][1]) / math.sqrt(2.0)) for h in FAMILY], axis=1)
        order = np.argsort(pv, axis=1, kind="mergesort")
        srt = np.take_along_axis(pv, order, axis=1)
        mult = np.arange(len(FAMILY), 0, -1)
        adj_sorted = np.maximum.accumulate(np.minimum(1.0, srt * mult), axis=1)
        adj = np.empty_like(pv)
        np.put_along_axis(adj, order, adj_sorted, axis=1)
        one_p = {h: float(pv[0, i]) for i, h in enumerate(FAMILY)}
        one_adj = holm(one_p)
        if any(abs(one_adj[h] - adj[0, i]) > 1e-12 for i, h in enumerate(FAMILY)):
            raise IdentityError("placebo: vectorised Holm disagrees with holm()")
        i10 = FAMILY.index(PRIMARY_H)
        m10, t10, h1, h2 = res[PRIMARY_H]
        passed = (
            (m10 >= PASS_MIN_IC) & (t10 >= PASS_MIN_T) & (adj[:, i10] <= p_at_3) & (h1 * h2 > 0)
        )
        by_h = {}
        for h in FAMILY:
            m, t = res[h][0], res[h][1]
            by_h[str(h)] = {
                "origins": int(ic[h].shape[1]),
                "sd_of_mean_ic": float(m.std()),
                "sd_of_t": float(t.std()),
                "share_abs_t_ge_2": float(np.mean(np.abs(t) >= 2.0)),
                "share_t_ge_3": float(np.mean(t >= 3.0)),
            }
        return {
            "simulations": sims,
            "by_h": by_h,
            "ic_part_of_rule_passes": int(passed.sum()),
            "ic_part_of_rule_pass_share": float(passed.mean()),
            "share_mean_ic_at_least_0.02_at_h10": float(np.mean(m10 >= PASS_MIN_IC)),
        }

    rng = np.random.default_rng(seed)
    S = zrank_rows(rng.normal(size=(sims_fixed, n)))
    fixed = summarise({h: S @ Z[h].T / n for h in FAMILY}, sims_fixed)
    ic = {h: np.empty((sims_fresh, Z[h].shape[0])) for h in FAMILY}
    for k in range(len(plan)):
        zs = zrank_rows(rng.normal(size=(sims_fresh, n)))
        for h in FAMILY:
            if k < Z[h].shape[0]:
                ic[h][:, k] = zs @ Z[h][k] / n
    fresh = summarise(ic, sims_fresh)
    return {
        "what": "random scores with no information, scored against the realised returns of the test window; no forecast is read",
        "seed": seed,
        "names": n,
        "nominal": {"share_abs_t_ge_2": 0.0455, "share_t_ge_3": 0.00135},
        "rule_part_applied": "mean rank IC >= 0.02, Newey-West t >= 3, Holm clause, same sign in both halves (incremental t not applied)",
        "fixed_score_per_name": fixed,
        "fresh_noise_each_origin": fresh,
    }


def expect(exc_type, fn) -> bool:
    """True if ``fn`` raises exactly the expected kind of error."""
    try:
        fn()
    except exc_type:
        return True
    except Exception:
        return False
    return False


def selftest(
    bars: dict, out_root: Path, validation_dir: Path, seeds: int, placebo_sims: int
) -> int:
    symbols = [s for s, ok in zip(bars["symbols"], bars["in_test"], strict=True) if ok]
    con_symbols = [s for s, ok in zip(bars["symbols"], bars["in_contrast"], strict=True) if ok]
    close = bars["close"]
    last = len(bars["dates"]) - 1
    n = len(symbols)

    def noise_maker(rng, paths):
        def make(p, cols):
            c0 = close[p["bar_index"], cols]
            return c0[:, None, None] * (1.0 + rng.normal(0.0, 0.03, (len(cols), paths, p["steps"])))

        return make

    def planted_maker(rng, paths, rho):
        def make(p, cols):
            t, m = p["bar_index"], len(cols)
            c0 = close[t, cols]
            out = np.empty((m, paths, p["steps"]))
            for h in range(1, p["steps"] + 1):
                v = rng.normal(0.0, 1.0, m)
                if t + h <= last:
                    u = (rankdata(close[t + h, cols] / c0 - 1.0) - (m + 1) / 2.0) / math.sqrt(
                        (m * m - 1) / 12.0
                    )
                    score = rho * u + math.sqrt(1 - rho * rho) * v
                else:
                    score = v
                e = rng.normal(0.0, 1.0, (m, paths))
                e -= e.mean(
                    axis=1, keepdims=True
                )  # the path mean carries exactly the planted score
                out[:, :, h - 1] = c0[:, None] * (1.0 + 0.02 * (score[:, None] + e))
            return out

        return make

    def oracle_maker(rng, paths, shift_origins=0, shift_sessions=0):
        def make(p, cols):
            t, m = p["bar_index"], len(cols)
            c0 = close[t, cols]
            tb = t + 5 * shift_origins  # bar index of the origin whose future is (wrongly) used
            out = np.empty((m, paths, p["steps"]))
            for h in range(1, p["steps"] + 1):
                tt = tb + h + shift_sessions
                if 0 <= tb <= last and tt <= last:
                    ret = close[tt, cols] / close[tb, cols] - 1.0
                else:
                    ret = rng.normal(0.0, 0.03, m)
                out[:, :, h - 1] = (c0 * (1.0 + ret))[:, None]
            return out

        return make

    def fam(run):
        P = build_panel(run, bars)
        blk = ic_block(P, np.ones(len(run.symbols), dtype=bool), FAMILY)
        return {
            str(h): {
                "mean": blk[h]["rank"]["mean"],
                "t": blk[h]["rank"]["t"],
                "n": blk[h]["rank"]["n"],
                "pearson": blk[h]["pearson"]["mean"],
            }
            for h in FAMILY
        }

    result: dict = {"bars_last_session": bars["dates"][-1], "n_symbols": n}
    # (a) pure noise through the whole analysis
    per_seed, verdicts, noise_report = [], [], None
    for s in range(seeds):
        run = synth_run(
            "primary",
            bars,
            symbols,
            "paper",
            10,
            "test",
            20,
            noise_maker(np.random.default_rng(1000 + s), 10),
        )
        per_seed.append(fam(run))
        if s < 3:
            ns, nr = analyze(bars, run, None, None)
            verdicts.append(ns["decision"]["verdict"])
            if noise_report is None:
                noise_report = (ns, nr)
    t10 = np.array([r["10"]["t"] for r in per_seed])
    m10 = np.array([r["10"]["mean"] for r in per_seed])
    result["noise"] = {
        "seeds": seeds,
        "h10_mean_of_means": float(m10.mean()),
        "h10_max_abs_mean": float(np.abs(m10).max()),
        "h10_share_abs_t_below_2": float((np.abs(t10) < 2).mean()),
        "share_abs_t_below_2_by_h": {
            h: float(np.mean([abs(r[h]["t"]) < 2 for r in per_seed])) for h in ("5", "10", "20")
        },
        "mean_of_means_by_h": {
            h: float(np.mean([r[h]["mean"] for r in per_seed])) for h in ("5", "10", "20")
        },
        "t_values_h10": [round(float(x), 3) for x in t10],
        "verdicts_first_three_seeds": verdicts,
    }
    # (a2) size of the test when the score carries no information (many simulations)
    result["placebo"] = placebo_size(
        bars, symbols, placebo_sims, max(1, placebo_sims // 5), 20261110
    )
    # (c) oracle and misaligned oracles
    rng = np.random.default_rng(11)
    aligned = fam(
        synth_run("primary", bars, symbols, "paper", 10, "test", 20, oracle_maker(rng, 10))
    )
    plus1 = fam(
        synth_run(
            "primary",
            bars,
            symbols,
            "paper",
            10,
            "test",
            20,
            oracle_maker(rng, 10, shift_origins=1),
        )
    )
    minus1 = fam(
        synth_run(
            "primary",
            bars,
            symbols,
            "paper",
            10,
            "test",
            20,
            oracle_maker(rng, 10, shift_origins=-1),
        )
    )
    sess1 = fam(
        synth_run(
            "primary",
            bars,
            symbols,
            "paper",
            10,
            "test",
            20,
            oracle_maker(rng, 10, shift_sessions=1),
        )
    )
    result["oracle"] = {
        "aligned": {h: aligned[h]["mean"] for h in aligned},
        "aligned_pearson": {h: aligned[h]["pearson"] for h in aligned},
        "shift_one_origin": {h: plus1[h]["mean"] for h in plus1},
        "shift_minus_one_origin": {h: minus1[h]["mean"] for h in minus1},
        "shift_one_session": {h: sess1[h]["mean"] for h in sess1},
        "expected_overlap_after_one_origin_shift": {"5": 0.0, "10": 0.5, "20": 0.75},
    }
    # (b) planted signal, through the on-disk format and the full report
    target = 0.05
    rho = target / (
        math.sqrt(12.0) / (2.0 * math.sqrt(math.pi))
    )  # Spearman of a uniform score in Gaussian noise
    planted = synth_run(
        "primary",
        bars,
        symbols,
        "paper",
        10,
        "test",
        20,
        planted_maker(np.random.default_rng(7), 10, rho),
    )
    sec = synth_run(
        "secondary",
        bars,
        symbols,
        "production",
        3,
        "test",
        20,
        noise_maker(np.random.default_rng(8), 3),
    )
    con = synth_run(
        "contrast",
        bars,
        con_symbols,
        "paper",
        10,
        "contrast",
        20,
        noise_maker(np.random.default_rng(9), 10),
    )
    disk = out_root / "runs"
    if disk.exists():
        shutil.rmtree(disk)
    for r in (planted, sec, con):
        save_run(r, disk / r.name, bars)
    loaded = [load_run(nm, disk / nm, bars) for nm in ("primary", "secondary", "contrast")]
    summary, rows = analyze(bars, *loaded)
    result["planted"] = {
        "target_ic": target,
        "rho_used": rho,
        "recovered": fam(loaded[0]),
        "verdict": summary["decision"]["verdict"],
        "incremental_t_h10": summary["primary"]["incremental"][10]["kronos"]["t"],
        "report": str(out_root / "report_planted" / RESULTS_NAME),
        "round_trip_identical": bool(
            all(
                np.array_equal(a["pred_close"], b["pred_close"])
                for a, b in zip(planted.origins, loaded[0].origins, strict=True)
            )
        ),
    }
    # ---- guards: every case changes one thing in a synthetic run directory, checks that the
    # analysis reacts, and puts the directory back exactly as it was.
    prim_dir, sec_dir = disk / "primary", disk / "secondary"
    victim = sorted(prim_dir.glob("origin_*.npz"))[3]
    original = victim.read_bytes()

    def tampered(mutate) -> bool:
        with np.load(victim, allow_pickle=False) as zf:
            z = {k: zf[k] for k in zf.files}
        meta = json.loads(str(z["meta"]))
        mutate(z, meta)
        z["meta"] = np.array(json.dumps(meta))
        np.savez_compressed(victim, **z)
        try:
            return expect(IdentityError, lambda: load_run("primary", prim_dir, bars))
        finally:
            victim.write_bytes(original)

    def change_last_close(z, meta):
        z["last_close"] = z["last_close"] * 1.0001

    def shift_future_dates(z, meta):
        t = bars["dates"].index(meta["origin_date"])
        meta["future_dates"] = bars["dates"][t + 2 : t + 2 + int(meta["steps"])]

    def foreign_script(z, meta):
        meta["script_sha256"] = "another-version-of-the-script"

    def change_row_seed(z, meta):
        seeds_ = z["row_seeds"].copy()
        seeds_[0, 0] += 1
        z["row_seeds"] = seeds_

    guards = {
        "changed_last_close_stops": tampered(change_last_close),
        "shifted_future_dates_stop": tampered(shift_future_dates),
        "foreign_script_hash_stops": tampered(foreign_script),
        "altered_row_seed_stops": tampered(change_row_seed),
    }
    stray = prim_dir / "origin_999_stray.npz"
    stray.write_bytes(original)
    guards["stray_origin_file_stops"] = expect(
        IdentityError, lambda: load_run("primary", prim_dir, bars)
    )
    stray.unlink()
    hidden = victim.with_suffix(".hidden")
    victim.rename(hidden)
    guards["incomplete_primary_refused"] = expect(
        Incomplete, lambda: load_run("primary", prim_dir, bars)
    )
    hidden.rename(victim)
    sec_victim = sorted(sec_dir.glob("origin_*.npz"))[-1]
    sec_hidden = sec_victim.with_suffix(".hidden")
    sec_victim.rename(sec_hidden)
    try:
        part = load_run("secondary", sec_dir, bars, must_be_complete=False)
        s2, _rows2 = analyze(bars, loaded[0], part, loaded[2])
        text2 = render(s2, {})
        want = f"incomplete ({part.present} of {part.expected} origins), not scored"
        guards["incomplete_secondary_not_scored"] = bool(
            not part.origins
            and part.present == part.expected - 1
            and "secondary" not in s2
            and s2["runs"]["secondary"]["scored"] is False
            and s2["decision"]["verdict"] == summary["decision"]["verdict"]
            and want in text2
            and "The secondary (production configuration) run is incomplete" in text2
        )
    finally:
        sec_hidden.rename(sec_victim)
    guards["directories_restored"] = bool(
        victim.read_bytes() == original
        and all(
            not expect(Exception, lambda nm=nm: load_run(nm, disk / nm, bars))
            for nm in ("primary", "secondary", "contrast")
        )
    )
    result["guards"] = guards
    result["partial_run_refused"] = guards["incomplete_primary_refused"]
    result["identity_check_fires"] = guards["changed_last_close_stops"]

    # ---- the decision rule at its edges, on hand-made statistics
    def stat(mean, t, multiplier, same=True):
        p = normal_p_two_sided(t)
        return {
            "mean": mean,
            "se": abs(mean / t),
            "t": t,
            "p": p,
            "p_holm": min(1.0, multiplier * p),
            "half1": mean,
            "half2": mean if same else -mean,
            "same_sign": same,
        }

    def rule(mean, t, multiplier, inc_t, same=True):
        d = decide(stat(mean, t, multiplier, same), {"mean": 0.01, "t": inc_t}, list(FAMILY))
        return (
            d["verdict"],
            d["holm_reading"]["verdict_if_t_at_least_3_alone"],
            d["holm_reading"]["verdict_depends_on_reading"],
        )

    edges = {
        "t_3.19_smallest_p": rule(0.03, 3.19, 3, 2.5),
        "t_3.19_largest_p": rule(0.03, 3.19, 1, 2.5),
        "t_3.40_smallest_p": rule(0.03, 3.40, 3, 2.5),
        "t_2.50": rule(0.03, 2.50, 3, 2.5),
        "t_3.50_incremental_1.5": rule(0.03, 3.50, 3, 1.5),
        "ic_0.01": rule(0.01, 3.50, 3, 2.5),
        "halves_differ": rule(0.03, 3.50, 3, 2.5, same=False),
        "negative": rule(-0.05, -9.0, 3, -9.0),
    }
    expected_edges = {
        "t_3.19_smallest_p": ("FAIL", "PASS", True),
        "t_3.19_largest_p": ("PASS", "PASS", False),
        "t_3.40_smallest_p": ("PASS", "PASS", False),
        "t_2.50": ("FAIL", "FAIL", False),
        "t_3.50_incremental_1.5": ("FAIL", "FAIL", False),
        "ic_0.01": ("FAIL", "FAIL", False),
        "halves_differ": ("FAIL", "FAIL", False),
        "negative": ("FAIL", "FAIL", False),
    }
    result["rule_edges"] = {k: list(v) for k, v in edges.items()}

    # ---- reports: the planted run (PASS) and a noise run (FAIL), rendered with the validation
    # records as they stand, so that every line of the real report is exercised here first.
    validation = load_validation(validation_dir)
    validation["selftest"] = strip(result)
    note = " - SYNTHETIC SELF-TEST, NOT A RESULT"
    write_outputs(out_root / "report_planted", summary, rows, validation, title_note=note)
    write_outputs(out_root / "report_noise", *noise_report, validation, title_note=note)
    text_pass = (out_root / "report_planted" / RESULTS_NAME).read_text()
    text_fail = (out_root / "report_noise" / RESULTS_NAME).read_text()
    closing = "Research signal only — no order was placed."
    # internal criterion names must not leak into the report (the one that reads as plain
    # English anyway, "same sign in both halves", is legitimately part of the rule's wording)
    raw_keys = [k.replace("_", " ") for k in CRITERION_WORDS if not k.startswith("same_sign")]
    result["report_checks"] = {
        "pass_report_leads_with_verdict": "**PASS.**" in text_pass.split("\n\n")[2],
        "fail_report_leads_with_verdict": "**FAIL.**" in text_fail.split("\n\n")[2],
        "fail_report_names_unmet_criteria_in_plain_words": "Not met: " in text_fail
        and not any(k in text_fail for k in raw_keys),
        "interval_in_lead": all(
            "A nominal 95% interval for the mean rank IC" in t.split("\n\n")[2]
            for t in (text_pass, text_fail)
        ),
        "nominal_p_note_with_placebo_rates": "random scores with no information" in text_pass,
        "pearson_labelled_exploratory": "Pearson IC (exploratory)" in text_pass,
        "all_horizon_table_labelled": "descriptive, not a pre-registered endpoint, no adjustment"
        in text_pass,
        "simple_rank_table_has_halves": "| Simple rank | Horizon | Origins | Names | Mean rank IC | NW s.e. |"
        in text_pass,
        "memorisation_sentence_says_sign": "The contrast-window IC is itself " in text_pass,
        "unscored_runs_named_in_fail_report": "The secondary (production configuration) run was not run."
        in text_fail
        and "The contrast-window run was not run." in text_fail,
        "closing_line": text_pass.rstrip().endswith(closing)
        and text_fail.rstrip().endswith(closing),
    }
    pl = result["placebo"]
    checks = {
        "noise_mean_near_zero": abs(result["noise"]["h10_mean_of_means"]) < 0.01,
        "noise_t_calibrated": result["noise"]["h10_share_abs_t_below_2"] >= 0.8,
        "noise_never_passes": all(v == "FAIL" for v in verdicts),
        "rule_rarely_passes_with_no_information": max(
            pl["fixed_score_per_name"]["ic_part_of_rule_pass_share"],
            pl["fresh_noise_each_origin"]["ic_part_of_rule_pass_share"],
        )
        < 0.01,
        "planted_recovered": all(
            abs(result["planted"]["recovered"][h]["mean"] - target) < 0.02
            for h in ("5", "10", "20")
        ),
        "planted_passes": result["planted"]["verdict"] == "PASS",
        "oracle_ic_is_one": all(result["oracle"]["aligned"][h] > 0.999 for h in ("5", "10", "20")),
        "origin_shift_destroys_h5": abs(result["oracle"]["shift_one_origin"]["5"]) < 0.15
        and abs(result["oracle"]["shift_minus_one_origin"]["5"]) < 0.15,
        "session_shift_detected": all(
            result["oracle"]["shift_one_session"][h] < 0.99 for h in ("5", "10", "20")
        ),
        "guards_all_fire": all(guards.values()),
        "rule_edges_as_expected": all(tuple(edges[k]) == expected_edges[k] for k in expected_edges),
        "report_wording": all(result["report_checks"].values()),
        "disk_round_trip": result["planted"]["round_trip_identical"],
    }
    result["checks"] = {k: bool(v) for k, v in checks.items()}
    result["all_passed"] = bool(all(checks.values()))
    result["created_utc"] = datetime.now(UTC).isoformat(timespec="seconds")
    validation_dir.mkdir(parents=True, exist_ok=True)
    (validation_dir / "selftest_summary.json").write_text(
        json.dumps(strip(result), indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(strip(result), indent=1, sort_keys=True))
    return 0 if result["all_passed"] else 5


# ----------------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--bars", default=str(DEFAULT_BARS))
    ap.add_argument(
        "--primary", help="output directory of the paper configuration on the test window"
    )
    ap.add_argument(
        "--secondary", help="output directory of the production configuration on the test window"
    )
    ap.add_argument(
        "--contrast", help="output directory of the paper configuration on the contrast window"
    )
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--validation-dir", default=str(DEFAULT_VALIDATION))
    ap.add_argument(
        "--selftest",
        action="store_true",
        help="synthetic forecasts only; never reads a real forecast",
    )
    ap.add_argument(
        "--incomplete-notice",
        action="store_true",
        help="if the primary run is incomplete, write a results file that says so (no forecast is "
        "read and no number is computed) instead of writing nothing",
    )
    ap.add_argument(
        "--verify-only",
        action="store_true",
        help="check the origin files present in the given directories and stop: no return is "
        "computed, nothing is scored and nothing is written",
    )
    ap.add_argument("--selftest-out", default=str(SCRATCH / "r3/out/kronos-ic/selftest"))
    ap.add_argument("--selftest-seeds", type=int, default=20)
    ap.add_argument(
        "--placebo-sims",
        type=int,
        default=20000,
        help="self-test: simulations of a fixed no-information score (a fifth as many with fresh noise)",
    )
    args = ap.parse_args()
    bars = load_bars(Path(args.bars))
    if args.selftest:
        return selftest(
            bars,
            Path(args.selftest_out),
            Path(args.validation_dir),
            args.selftest_seeds,
            args.placebo_sims,
        )
    if not args.primary:
        raise SystemExit("--primary is required")
    if args.verify_only:
        report = {}
        try:
            for nm, d in (
                ("primary", args.primary),
                ("secondary", args.secondary),
                ("contrast", args.contrast),
            ):
                run = load_run(nm, Path(d), bars, verify_only=True) if d else None
                if run is not None:
                    report[nm] = {
                        "origin_files_present": run.present,
                        "origin_files_expected": run.expected,
                        "origin_files_passing_every_check": run.verified,
                        "script_sha256": run.manifest["script_sha256"],
                    }
        except IdentityError as exc:
            print(f"IDENTITY CHECK FAILED: {exc}", file=sys.stderr)
            return 3
        print(json.dumps({"verify_only": report, "scored": False}, indent=1))
        return 0
    try:
        primary = load_run("primary", Path(args.primary), bars, must_be_complete=True)
        if primary is None:
            raise SystemExit(f"No run manifest found in {args.primary}")
        secondary = (
            load_run("secondary", Path(args.secondary), bars, must_be_complete=False)
            if args.secondary
            else None
        )
        contrast = (
            load_run("contrast", Path(args.contrast), bars, must_be_complete=False)
            if args.contrast
            else None
        )
        for run, cfg, win in (
            (primary, "paper", "test"),
            (secondary, "production", "test"),
            (contrast, "paper", "contrast"),
        ):
            if run is not None and (run.manifest["config_name"], run.manifest["window"]) != (
                cfg,
                win,
            ):
                raise IdentityError(
                    f"{run.name}: expected the {cfg} configuration on the {win} window"
                )
        present_runs = [r for r in (primary, secondary, contrast) if r is not None]
        if len({r.manifest["script_sha256"] for r in present_runs}) != 1:
            raise IdentityError(
                "the runs were written by different versions of the inference script"
            )
        if (
            len({json.dumps(r.manifest.get("file_sha256"), sort_keys=True) for r in present_runs})
            != 1
        ):
            raise IdentityError("the runs did not use the same model code and weights")
    except Incomplete as exc:
        if args.incomplete_notice:
            # Status only: load_run returns before it opens any origin file of an incomplete run.
            runs = {}
            for nm, d in (
                ("primary", args.primary),
                ("secondary", args.secondary),
                ("contrast", args.contrast),
            ):
                try:
                    r = load_run(nm, Path(d), bars, must_be_complete=False) if d else None
                except IdentityError as exc2:
                    print(f"IDENTITY CHECK FAILED - nothing written: {exc2}", file=sys.stderr)
                    return 3
                info = run_info(r, None)
                info["scored"] = False
                runs[nm] = info
            write_notice(Path(args.out), runs, load_validation(Path(args.validation_dir)))
            print(
                json.dumps(
                    {
                        "verdict": "NOT EVALUATED",
                        "reason": str(exc),
                        "out": str(Path(args.out) / RESULTS_NAME),
                    },
                    indent=1,
                )
            )
            return 0
        print(
            f"REFUSED: {exc}. Nothing was read or written. Finish the run (it is resumable) and "
            "analyse it then; an incomplete primary run is never scored. Add --incomplete-notice "
            "to write a results file that only says the run is incomplete.",
            file=sys.stderr,
        )
        return 2
    except IdentityError as exc:
        print(f"IDENTITY CHECK FAILED - no results written: {exc}", file=sys.stderr)
        return 3
    for run in (secondary, contrast):
        if run is not None and not run.scored:
            print(
                f"NOTE: {run.name}: {run.present} of {run.expected} origins present; the run is "
                "reported as incomplete and none of its forecasts is read.",
                file=sys.stderr,
            )
    summary, rows = analyze(bars, primary, secondary, contrast)
    validation = load_validation(Path(args.validation_dir))
    write_outputs(Path(args.out), summary, rows, validation)
    dec = summary["decision"]
    print(
        json.dumps(
            {
                "verdict": dec["verdict"],
                "values": strip(dec.get("values", {})),
                "criteria": dec.get("criteria", {}),
                "holm_reading": dec.get("holm_reading", {}),
                "interval_95": strip(dec.get("interval_95", {})),
                "runs_scored": {k: v.get("scored") for k, v in summary["runs"].items()},
                "out": str(Path(args.out) / RESULTS_NAME),
            },
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
