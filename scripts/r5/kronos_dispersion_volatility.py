"""R5 -- does Kronos path dispersion forecast volatility beyond simple measures?

Pre-registration:
docs/research/kronos/PREREGISTRATION_2026-11-10_kronos_dispersion_volatility.md

No inference. Re-uses the 60 saved primary forecasts of the cross-sectional rank-IC study and
the same bars file (nothing after 2025-09-05). numpy only.

Loading: the origin files are loaded through ``load_bars`` / ``load_run`` of
``scripts/r3/kronos_ic_analyze.py`` (imported, not re-implemented), so every integrity check
of that study (plan, future dates, hashes, seeds, last close, completeness) is applied before
a forecast is used. ``rankdata``, ``pearson``, ``spearman``, ``centred_rank``, ``nw_stats``
and ``nw_lag`` are imported from the same file so the statistics are the study's own.

Order of work: (1) synthetic self-test, (2) identity check against the rank-IC study's
dispersion rows, (3) no-look-ahead assertion on the simple measures, (4) every
pre-registered cell, (5) the PASS rule, (6) outputs. A failure in 1-3 stops the script
before any result is written.

Research signal only -- no order was placed.
"""

# Report prose and table rows are kept on one line.
# ruff: noqa: E501

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse  # noqa: E402
import csv  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
from datetime import UTC, datetime  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1] / "r3"))
import kronos_ic_analyze as K  # noqa: E402

SCRATCH = K.SCRATCH
PRIMARY_DIR = SCRATCH / "r3/out/kronos-ic/primary_paper_test"
RAW_DIR = SCRATCH / "r3/out/kronos-verify/dispersion"
DOC_DIR = SCRATCH / "r3wt/docs/research/kronos/2026-11-10-cross-sectional"
RANK_IC_SUMMARY = DOC_DIR / "summary.json"
RESULTS_NAME = "KRONOS_DISPERSION_VOLATILITY_2026-11-10.md"
SUMMARY_NAME = "dispersion_summary.json"

HORIZONS = (5, 10)
TARGETS = ("T1", "T2", "T3")
PREDICTORS = ("D1", "D2")
SIMPLE = ("rv5", "rv20", "rv60", "rv90", "atr14_close", "parkinson20", "abs_ret5")
LABEL = {
    "T1": "T1 realised volatility (primary)",
    "T2": "T2 absolute return",
    "T3": "T3 largest overnight gap",
    "D1": "D1 spread of path returns (primary)",
    "D2": "D2 mean path volatility",
    "rv5": "realised volatility, 5 sessions",
    "rv20": "realised volatility, 20 sessions",
    "rv60": "realised volatility, 60 sessions",
    "rv90": "realised volatility, 90 sessions",
    "atr14_close": "ATR14 / close",
    "parkinson20": "Parkinson range volatility, 20 sessions",
    "abs_ret5": "absolute 5-session return",
}
MIN_NAMES = K.MIN_NAMES
PASS_MIN_COEF = 0.03
PASS_MIN_T = 3.0
IDENTITY_EXPECTED = {  # from the task statement; also read from summary.json and compared
    5: {"rank_corr": 0.1762, "partial": 0.0642},
    10: {"rank_corr": 0.1523, "partial": 0.0581},
}


class Stop(RuntimeError):
    pass


# ------------------------------------------------------------------ definitions
def simple_measures(o: np.ndarray, hi: np.ndarray, lo: np.ndarray, c: np.ndarray, t: int) -> dict:
    """The seven simple measures at origin row ``t``. Only rows <= t are indexed."""
    c = c[: t + 1]
    hi = hi[: t + 1]
    lo = lo[: t + 1]
    lr = np.diff(np.log(c[-91:]), axis=0)  # the last 90 daily log returns, ending at the origin
    out = {}
    for n in (5, 20, 60, 90):
        out[f"rv{n}"] = np.sqrt(np.mean(lr[-n:] ** 2, axis=0))
    pc = c[-15:-1]
    h14, l14 = hi[-14:], lo[-14:]
    tr = np.maximum(h14 - l14, np.maximum(np.abs(h14 - pc), np.abs(l14 - pc)))
    out["atr14_close"] = tr.mean(axis=0) / c[-1]
    out["parkinson20"] = np.sqrt(np.mean(np.log(hi[-20:] / lo[-20:]) ** 2, axis=0) / (4.0 * math.log(2.0)))
    out["abs_ret5"] = np.abs(c[-1] / c[-6] - 1.0)
    return out


def targets(o: np.ndarray, c: np.ndarray, t: int, h: int) -> dict:
    """Targets over sessions t+1..t+h. The caller guarantees t + h is inside the bars file."""
    seg = c[t : t + h + 1]  # closes of the origin and the h sessions after it
    lr = np.diff(np.log(seg), axis=0)
    gaps = np.abs(o[t + 1 : t + h + 1] / c[t : t + h] - 1.0)
    return {
        "T1": np.sqrt(np.mean(lr**2, axis=0)),
        "T2": np.abs(seg[-1] / seg[0] - 1.0),
        "T3": gaps.max(axis=0),
    }


def kronos_predictors(pred_close: np.ndarray, c0: np.ndarray, h: int) -> dict:
    """pred_close [names, paths, steps]; c0 the last observed close."""
    pc = pred_close.astype(np.float64)
    d1 = (pc[:, :, h - 1] / c0[:, None] - 1.0).std(axis=1, ddof=1)
    full = np.concatenate([np.broadcast_to(c0[:, None, None], (pc.shape[0], pc.shape[1], 1)), pc[:, :, :h]], axis=2)
    lr = np.diff(np.log(full), axis=2)  # step 1 is measured from the last observed close
    d2 = np.sqrt(np.mean(lr**2, axis=2)).mean(axis=1)
    return {"D1": d1, "D2": d2}


# ------------------------------------------------------------------- statistics
def ols(y: np.ndarray, cols: list) -> tuple[np.ndarray, float]:
    X = np.column_stack([np.ones(y.size), *cols])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    res = y - X @ beta
    d = y - y.mean()
    return beta, 1.0 - float(res @ res) / float(d @ d)


def cell(y_by_origin: list, x_by_origin: list, simple_by_origin: list, lag: int) -> dict:
    """One (target, predictor, h) cell. Each list holds one entry per origin (None = not scored).

    Per origin: OLS of the target's centred rank on the predictor's centred rank and the
    seven simple centred ranks, over the names where all nine values are finite."""
    n_or = len(y_by_origin)
    coef = np.full(n_or, np.nan)
    coef_simple = np.full((n_or, len(SIMPLE)), np.nan)
    r2_full, r2_base = np.full(n_or, np.nan), np.full(n_or, np.nan)
    plain = np.full(n_or, np.nan)
    plain_simple = np.full((n_or, len(SIMPLE)), np.nan)
    used = np.zeros(n_or, dtype=int)
    for i in range(n_or):
        y, x, s = y_by_origin[i], x_by_origin[i], simple_by_origin[i]
        if y is None:
            continue
        ok = np.isfinite(y) & np.isfinite(x)
        for nm in SIMPLE:
            ok &= np.isfinite(s[nm])
        used[i] = int(ok.sum())
        if used[i] < MIN_NAMES:
            continue
        ry, rx = K.centred_rank(y[ok]), K.centred_rank(x[ok])
        rs = [K.centred_rank(s[nm][ok]) for nm in SIMPLE]
        beta, r2f = ols(ry, [rx, *rs])
        _b0, r2b = ols(ry, rs)
        coef[i], coef_simple[i] = beta[1], beta[2:]
        r2_full[i], r2_base[i] = r2f, r2b
        plain[i] = K.pearson(rx, ry)
        for j in range(len(SIMPLE)):
            plain_simple[i, j] = K.pearson(rs[j], ry)
    scored = np.isfinite(coef)
    return {
        "kronos_coef": K.nw_stats(coef, lag),
        "plain_rank_corr": K.nw_stats(plain, lag),
        "r2_full_mean": float(np.nanmean(r2_full)) if scored.any() else float("nan"),
        "r2_simple_only_mean": float(np.nanmean(r2_base)) if scored.any() else float("nan"),
        "r2_gain_mean": float(np.nanmean(r2_full - r2_base)) if scored.any() else float("nan"),
        "simple_coefs_in_full_regression": {nm: K.nw_stats(coef_simple[:, j], lag) for j, nm in enumerate(SIMPLE)},
        "simple_plain_rank_corr": {nm: K.nw_stats(plain_simple[:, j], lag) for j, nm in enumerate(SIMPLE)},
        "origins_scored": int(scored.sum()),
        "n_names_mean": float(used[scored].mean()) if scored.any() else float("nan"),
        "series_coef": coef,
        "series_plain": plain,
        "series_r2_gain": r2_full - r2_base,
    }


# -------------------------------------------------------------------- self-test
def selftest() -> dict:
    """Synthetic only; never reads a forecast. Same ``cell`` code as the real analysis."""
    rng = np.random.default_rng(20261110)
    n_or, n = 60, 500
    ys, simp, noise, copy60, planted = [], [], [], [], []
    for _ in range(n_or):
        s = rng.standard_normal(n)  # latent volatility level
        z = rng.standard_normal(n)  # independent information nobody but 'planted' sees
        m = {nm: s + 0.5 * rng.standard_normal(n) for nm in SIMPLE}
        ys.append(np.exp(s + 0.6 * z + 0.8 * rng.standard_normal(n)))
        simp.append({nm: np.exp(v) for nm, v in m.items()})
        noise.append(rng.standard_normal(n))
        copy60.append(np.exp(m["rv60"] + 0.5 * rng.standard_normal(n)))
        planted.append(z + 0.5 * rng.standard_normal(n))
    res = {}
    for nm, xs in (("pure_noise", noise), ("noisy_copy_of_rv60", copy60), ("planted_independent", planted)):
        c = cell(ys, xs, simp, 1)
        res[nm] = {
            "coef_mean": c["kronos_coef"]["mean"],
            "coef_t": c["kronos_coef"]["t"],
            "plain_rank_corr": c["plain_rank_corr"]["mean"],
            "r2_gain": c["r2_gain_mean"],
        }
    tol = 0.015
    checks = {
        "pure_noise_coef_near_zero": abs(res["pure_noise"]["coef_mean"]) < tol,
        "noisy_copy_of_rv60_coef_near_zero_given_simple_ranks": abs(res["noisy_copy_of_rv60"]["coef_mean"]) < tol,
        "noisy_copy_of_rv60_plain_corr_is_large": res["noisy_copy_of_rv60"]["plain_rank_corr"] > 0.3,
        "planted_information_recovered": res["planted_independent"]["coef_mean"] > 0.15 and res["planted_independent"]["coef_t"] > 10,
    }
    return {"tolerance_for_near_zero": tol, "origins": n_or, "names": n, "results": res, "checks": checks, "passed": all(checks.values())}


# --------------------------------------------------------------- identity check
def identity_check(run, bars: dict, reference: dict) -> dict:
    """Reproduce the rank-IC study's dispersion rows from this script's own D1 and T2."""
    close, o = bars["close"][:, run.cols], bars["open"][:, run.cols]
    last = len(bars["dates"]) - 1
    out, ok_all = {}, True
    for h in HORIZONS:
        raw, part = [], []
        for org in run.origins:
            t = org["t"]
            if t + h > last:
                continue
            d = kronos_predictors(org["pred_close"], close[t], h)["D1"]
            a = targets(o, close, t, h)["T2"]
            v = np.diff(np.log(close[t - 20 : t + 1]), axis=0).std(axis=0, ddof=1)  # the study's 20-session volatility
            ok = np.isfinite(d) & np.isfinite(a) & np.isfinite(v)
            if int(ok.sum()) < MIN_NAMES:
                continue
            rd, ra, rv = K.rankdata(d[ok]), K.rankdata(a[ok]), K.rankdata(v[ok])
            r_da, r_dv, r_av = K.pearson(rd, ra), K.pearson(rd, rv), K.pearson(ra, rv)
            raw.append(r_da)
            part.append((r_da - r_dv * r_av) / math.sqrt((1 - r_dv**2) * (1 - r_av**2)))
        mine = {"rank_corr": float(np.mean(raw)), "partial": float(np.mean(part)), "origins": len(raw)}
        ref = reference[str(h)]
        theirs = {"rank_corr": ref["rank_corr"]["mean"], "partial": ref["partial_given_rvol20"]["mean"], "origins": ref["rank_corr"]["n"]}
        match = (
            round(mine["rank_corr"], 4) == round(theirs["rank_corr"], 4) == IDENTITY_EXPECTED[h]["rank_corr"]
            and round(mine["partial"], 4) == round(theirs["partial"], 4) == IDENTITY_EXPECTED[h]["partial"]
            and mine["origins"] == theirs["origins"]
        )
        ok_all &= match
        out[h] = {"this_script": mine, "rank_ic_summary_json": theirs, "task_statement": IDENTITY_EXPECTED[h], "match_to_4_decimals": bool(match)}
    out["passed"] = bool(ok_all)
    return out


# ---------------------------------------------------------------------- outputs
def f(x, nd=4) -> str:
    return "n/a" if x is None or not math.isfinite(x) else f"{x:+.{nd}f}"


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def render(S: dict) -> str:
    cells, dec = S["cells"], S["decision"]
    L = ["# Kronos path dispersion versus simple volatility measures — result (2026-11-10)", ""]
    a, b = dec["cells"]["5"], dec["cells"]["10"]
    L.append(f"**{dec['verdict']}.**")
    if dec["verdict"] == "PASS":
        L.append(
            f"With the seven simple volatility measures already in the regression, the spread of the ten Kronos paths (D1) still helps rank next-period realised volatility (T1): mean coefficient {f(a['mean'])} at 5 sessions (Newey–West t {f(a['t'], 2)}) and {f(b['mean'])} at 10 sessions (t {f(b['t'], 2)}), the same sign in both halves at both horizons. "
            "All three pre-registered conditions are met at both horizons. This justifies pre-registering a candidate-level study and authorises nothing else."
        )
    else:
        words = {"mean_coef_at_least_0.03": "the coefficient is below 0.03", "newey_west_t_at_least_3": "the t is below 3", "same_sign_in_both_halves": "the sign differs between the halves"}
        failed = [f"at {h} sessions {words[k]}" for h, c in ((5, a), (10, b)) for k, v in c["criteria"].items() if not v]
        L.append(
            f"With the seven simple volatility measures already in the regression, the spread of the ten Kronos paths (D1) adds a mean coefficient of {f(a['mean'])} at 5 sessions (Newey–West t {f(a['t'], 2)}) and {f(b['mean'])} at 10 sessions (t {f(b['t'], 2)}) for ranking next-period realised volatility (T1). "
            f"The rule needs a coefficient of at least 0.03, a t of at least 3 and the same sign in both halves at both horizons; not met: {'; '.join(failed)}. By the pre-registered rule this closes zero-shot Kronos-small as a risk input as well."
        )
    L += [
        "",
        f"Pre-registration: `docs/research/kronos/PREREGISTRATION_2026-11-10_kronos_dispersion_volatility.md`. Script: `scripts/r5/kronos_dispersion_volatility.py`. Generated {S['generated_utc']}. No inference was run: the 60 saved primary forecasts of the rank-IC study were re-used ({S['run']['origins_verified']} of {S['run']['origins_expected']} origin files passed that study's integrity checks), with the same bars file (last date {S['run']['bars_last_date']}).",
        "",
        "## Decision rule, applied mechanically",
        "",
        "| h | mean D1 coefficient | needs ≥ 0.03 | Newey–West t | needs ≥ 3 | first half | second half | same sign | cell passes |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for h in HORIZONS:
        c = dec["cells"][str(h)]
        cr = c["criteria"]
        L.append(f"| {h} | {f(c['mean'])} | {'yes' if cr['mean_coef_at_least_0.03'] else 'no'} | {f(c['t'], 2)} | {'yes' if cr['newey_west_t_at_least_3'] else 'no'} | {f(c['half1'])} | {f(c['half2'])} | {'yes' if cr['same_sign_in_both_halves'] else 'no'} | {'yes' if c['passes'] else 'no'} |")
    L += [
        "",
        "## Every cell: Kronos coefficient with the seven simple ranks in the regression",
        "",
        "Per origin, the target's rank is regressed on the Kronos predictor's rank and the seven simple ranks (all rescaled to −0.5..0.5). The coefficient is averaged over origins. Only T1 with D1 carries a verdict.",
        "",
        "| target | predictor | h | origins | names (mean) | mean coefficient | NW s.e. | NW t | first half | second half | plain rank corr. | mean R² simple only | mean R² with Kronos | R² gain |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for tg in TARGETS:
        for pr in PREDICTORS:
            for h in HORIZONS:
                c = cells[f"{tg}|{pr}|{h}"]
                k = c["kronos_coef"]
                L.append(
                    f"| {LABEL[tg]} | {LABEL[pr]} | {h} | {c['origins_scored']} | {c['n_names_mean']:.1f} | {f(k['mean'])} | {f(k['se'])} | {f(k['t'], 2)} | {f(k['half1'])} | {f(k['half2'])} | {f(c['plain_rank_corr']['mean'])} | {f(c['r2_simple_only_mean'])} | {f(c['r2_full_mean'])} | {f(c['r2_gain_mean'])} |"
                )
    L += [
        "",
        "## Plain rank correlations with each target (no controls)",
        "",
        "Mean over origins of the cross-sectional rank correlation; Newey–West t in brackets. The best simple measure for each target and horizon is in bold.",
        "",
        "| measure | T1 h=5 | T1 h=10 | T2 h=5 | T2 h=10 | T3 h=5 | T3 h=10 |",
        "|---|---|---|---|---|---|---|",
    ]
    pl = S["plain_rank_correlations"]
    for nm in (*PREDICTORS, *SIMPLE):
        row = [f"Kronos {LABEL[nm]}" if nm in PREDICTORS else LABEL[nm]]
        for tg in TARGETS:
            for h in HORIZONS:
                v = pl[f"{tg}|{h}"][nm]
                txt = f"{f(v['mean'])} ({f(v['t'], 1)})"
                row.append(f"**{txt}**" if S["best_simple"][f"{tg}|{h}"]["measure"] == nm else txt)
        L.append("| " + " | ".join(row) + " |")
    L += [
        "",
        "## Checks run before the result",
        "",
        "**Identity check (passed).** This script's own D1 and T2 reproduce the rank-IC study's dispersion rows to four decimals:",
        "",
        "| h | rank corr. D1 vs absolute return: here / study | partial given 20-session volatility: here / study | origins |",
        "|---|---|---|---|",
    ]
    for h in HORIZONS:
        i = S["identity_check"][str(h)]
        L.append(f"| {h} | {f(i['this_script']['rank_corr'])} / {f(i['rank_ic_summary_json']['rank_corr'])} | {f(i['this_script']['partial'])} / {f(i['rank_ic_summary_json']['partial'])} | {i['this_script']['origins']} |")
    la = S["lookahead_check"]
    L += [
        "",
        f"**No look-ahead (passed).** At each of the {la['origins_checked']} origins the seven simple measures were recomputed with every bar after the origin set to missing; all {la['arrays_compared']} arrays were identical. Targets use sessions origin+1..origin+h only; the latest target session used is {la['latest_target_session']}.",
        "",
        "**Synthetic self-test (passed).** Same regression code, made-up data (60 origins, 500 names):",
        "",
        "| synthetic predictor | mean coefficient | NW t | plain rank corr. | R² gain | expected |",
        "|---|---|---|---|---|---|",
    ]
    exp = {"pure_noise": "near zero", "noisy_copy_of_rv60": "near zero despite a large plain correlation", "planted_independent": "clearly positive"}
    for nm, r in S["selftest"]["results"].items():
        L.append(f"| {nm.replace('_', ' ')} | {f(r['coef_mean'])} | {f(r['coef_t'], 2)} | {f(r['plain_rank_corr'])} | {f(r['r2_gain'])} | {exp[nm]} |")
    L += ["", "## Deviations and clarifications", ""]
    L += [f"{i}. {d}" for i, d in enumerate(S["deviations_and_clarifications"], 1)]
    L += ["", "## Limits", ""]
    L += [f"- {d}" for d in S["limits"]]
    L += ["", "Research signal only — no order was placed."]
    return "\n".join(L) + "\n"


CLARIFICATIONS = [
    "No deviation from the pre-registration. The points below record choices the text left open.",
    "Loading: the origin files were loaded with `load_bars` and `load_run` imported from `scripts/r3/kronos_ic_analyze.py`, so that study's integrity checks ran on all 60 files; the rank, correlation and Newey–West functions are imported from the same file. Only `pred_close` is used; `pred_high` and `pred_low` are not read.",
    "Realised volatility in the simple measures uses the pre-registration's own definition (root mean square of daily close-to-close log returns) over the last 5, 20, 60 and 90 returns ending at the origin. The rank-IC study's 20-session volatility was a sample standard deviation; that version is used only inside the identity check, to reproduce that study's rows.",
    "ATR14 is the plain average of the last 14 true ranges (the convention of `signalforge.research.features.daily.atr`), divided by the origin close. Parkinson volatility is sqrt(mean(ln(high/low)²) / (4 ln 2)) over the 20 sessions ending at the origin. Absolute 5-session return is |close ÷ close five sessions earlier − 1|.",
    "D1 is the sample standard deviation (n − 1) across the ten paths of predicted close at step h ÷ last observed close − 1, exactly as in the rank-IC study. D2 takes each path's daily log returns over steps 1..h, the first measured from the last observed close, then the root mean square per path, then the mean over paths.",
    "T3 uses the opens of sessions origin+1..origin+h, each against the previous session's close (the origin close for the first).",
    "All 500 names; a name is used at an origin only if the target, the predictor and all seven simple measures are finite, and ranks are taken among the names used. An origin needs at least 30 names (the rank-IC study's rule). The plain rank correlations are computed on the same names as the regression.",
    "Halves: the first ⌈n/2⌉ scored origins against the rest (the rank-IC study's rule). Newey–West: Bartlett weights, lag ⌈h/5⌉ (1 at h = 5, 2 at h = 10), variance divided by n, as in that study's `nw_stats`.",
    "R² gain is the mean over origins of (R² with the Kronos rank and the seven simple ranks − R² with the seven simple ranks alone); it cannot be negative for any single origin.",
    "The no-look-ahead assertion compares bit for bit. On its first execution it stopped the script before any result was computed or written: the bars had been held in column-major memory order and the masked copy in row-major order, so sums differed in the last binary digit (relative difference below 5e-16) with no later bar involved. The arrays are now held in row-major order and the comparison is exact; the definitions did not change. Run history: the second execution produced the results. The script was then executed a third time after a wording-only edit to the verdict sentence, and a fourth time after review added sentences to this section and to the limits; neither edit touched a definition, the statistic or the decision rule. The fourth execution's cell statistics, decision values, check results and per-origin series were compared with the third's and are identical; the second execution's outputs were overwritten, so its equality with the later ones rests on the code being deterministic and unchanged in its computations, not on a saved copy.",
    "Coverage of the built-in checks: the identity check exercises D1 and T2 only, and the synthetic self-test exercises only the regression function on made-up data. T1, T3, D2 and the seven simple measures are covered by the no-look-ahead assertion but by no other built-in check.",
    "The coefficients of the seven simple ranks from the same regressions are saved in `dispersion_summary.json` for reference; no extra regression or variant was run. The incomplete secondary run and the contrast run were not read.",
]
LIMITS = [
    "The fail is on coefficient size only (about 0.026 against the required 0.03 at both horizons); the t and same-sign conditions are met. The pre-registration names ATR14 without saying how the 14 true ranges are averaged; the plain average used here was fixed by the repo's existing function, not by the pre-registration, and the margin of the fail may depend on that choice. The rule was applied as written and no other convention was run by this script.",
    "Same forecasts and window as a study whose dispersion row had already been seen.",
    "One model size (Kronos-small), one sampling configuration, ten paths per name.",
    "At most 59 overlapping origins; nominal Newey–West t values run large with this few origins.",
    "A survivor-conditioned list of 500 names; nothing after 2025-09-05.",
    "Ranks only: the result says nothing about the level or calibration of a volatility forecast.",
    "A pass would be a reason to test further, not a risk model; a fail speaks only to zero-shot use of this model here.",
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--selftest-only", action="store_true", help="run the synthetic self-test and stop; reads no forecast, writes nothing")
    args = ap.parse_args()

    st = selftest()
    print("self-test:", json.dumps(st, indent=1))
    if not st["passed"]:
        raise Stop("synthetic self-test failed; nothing was read or written")
    if args.selftest_only:
        return 0

    bars = K.load_bars(K.DEFAULT_BARS)
    run = K.load_run("primary", PRIMARY_DIR, bars, must_be_complete=True)
    if run is None or not run.scored or run.verified != run.expected:
        raise Stop("primary run is not complete and verified")
    dates = bars["dates"]
    last = len(dates) - 1
    # Row-major copies: the look-ahead comparison below is exact (bit for bit) only if the
    # original and the masked copy are summed in the same memory order.
    o, hi, lo, c = (np.ascontiguousarray(bars[k][:, run.cols]) for k in ("open", "high", "low", "close"))

    reference = json.loads(RANK_IC_SUMMARY.read_text())["primary"]["dispersion"]
    ident = identity_check(run, bars, reference)
    print("identity check:", json.dumps(ident, indent=1))
    if not ident["passed"]:
        raise Stop("identity check failed; stopping before any result")

    # Simple measures at every origin, with the no-look-ahead assertion.
    simp, compared = [], 0
    for org in run.origins:
        t = org["t"]
        if t < 90:
            raise Stop("an origin has fewer than 90 prior sessions")
        m = simple_measures(o, hi, lo, c, t)
        masked = [a.copy() for a in (o, hi, lo, c)]
        for a in masked:
            a[t + 1 :] = np.nan
        m2 = simple_measures(*masked, t)
        for nm in SIMPLE:
            if not np.array_equal(m[nm], m2[nm], equal_nan=True):
                raise Stop(f"look-ahead: {nm} at {org['date']} changes when later bars are removed")
            compared += 1
        simp.append(m)

    cells, plain, best, series_rows = {}, {}, {}, []
    latest_target = ""
    for h in HORIZONS:
        lag = K.nw_lag(h)
        tg_by, pr_by = {tg: [] for tg in TARGETS}, {pr: [] for pr in PREDICTORS}
        for org in run.origins:
            t = org["t"]
            scored = t + h <= last and org["steps"] >= h
            if scored:
                if dates[t + h] > K.LAST_DEV_SESSION:
                    raise Stop("a target session lies after 2025-09-05")
                latest_target = max(latest_target, dates[t + h])
                tv = targets(o, c, t, h)
            kp = kronos_predictors(org["pred_close"], c[t], h) if org["steps"] >= h else None
            for tg in TARGETS:
                tg_by[tg].append(tv[tg] if scored else None)
            for pr in PREDICTORS:
                pr_by[pr].append(kp[pr] if kp is not None else None)
        for tg in TARGETS:
            for pr in PREDICTORS:
                res = cell(tg_by[tg], pr_by[pr], simp, lag)
                for i, org in enumerate(run.origins):
                    if np.isfinite(res["series_coef"][i]):
                        series_rows.append({"target": tg, "predictor": pr, "h": h, "origin_index": org["k"], "origin_date": org["date"], "kronos_coef": float(res["series_coef"][i]), "plain_rank_corr": float(res["series_plain"][i]), "r2_gain": float(res["series_r2_gain"][i])})
                cells[f"{tg}|{pr}|{h}"] = res
            c1, c2 = cells[f"{tg}|D1|{h}"], cells[f"{tg}|D2|{h}"]
            p = {"D1": c1["plain_rank_corr"], "D2": c2["plain_rank_corr"], **c1["simple_plain_rank_corr"]}
            plain[f"{tg}|{h}"] = p
            bs = max(SIMPLE, key=lambda nm: p[nm]["mean"])
            best[f"{tg}|{h}"] = {"measure": bs, "label": LABEL[bs], "mean": p[bs]["mean"], "t": p[bs]["t"]}

    dec_cells = {}
    for h in HORIZONS:
        k = cells[f"T1|D1|{h}"]["kronos_coef"]
        crit = {
            "mean_coef_at_least_0.03": bool(k["mean"] >= PASS_MIN_COEF),
            "newey_west_t_at_least_3": bool(k["t"] >= PASS_MIN_T),
            "same_sign_in_both_halves": bool(k["same_sign"]),
        }
        dec_cells[str(h)] = {"mean": k["mean"], "se": k["se"], "t": k["t"], "half1": k["half1"], "half2": k["half2"], "n": k["n"], "criteria": crit, "passes": all(crit.values())}
    verdict = "PASS" if all(v["passes"] for v in dec_cells.values()) else "FAIL"

    S = {
        "study": "kronos dispersion vs simple volatility measures",
        "preregistration": "docs/research/kronos/PREREGISTRATION_2026-11-10_kronos_dispersion_volatility.md",
        "generated_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "script": "scripts/r5/kronos_dispersion_volatility.py",
        "script_sha256": sha256_file(HERE),
        "run": {
            "directory": str(PRIMARY_DIR),
            "config_name": run.manifest["config_name"],
            "config": run.manifest["config"],
            "origins_expected": run.expected,
            "origins_verified": run.verified,
            "first_origin": run.origins[0]["date"],
            "last_origin": run.origins[-1]["date"],
            "n_symbols": len(run.symbols),
            "bars_content_sha256": bars["_content_sha256"],
            "inference_script_sha256": run.manifest.get("script_sha256"),
            "bars_last_date": dates[-1],
        },
        "decision": {"rule": "PASS only if, for T1 with D1 at both h = 5 and h = 10: mean coefficient >= 0.03, Newey-West t >= 3, same sign in both halves", "cells": dec_cells, "verdict": verdict},
        "cells": K.strip(cells),
        "plain_rank_correlations": K.strip(plain),
        "best_simple": K.strip(best),
        "identity_check": K.strip(ident),
        "lookahead_check": {"origins_checked": len(run.origins), "arrays_compared": compared, "passed": True, "latest_target_session": latest_target},
        "selftest": K.strip(st),
        "deviations_and_clarifications": CLARIFICATIONS,
        "limits": LIMITS,
        "note": "Research signal only — no order was placed.",
    }
    S = json.loads(json.dumps(K.strip(S)))  # plain JSON types, string keys, as written to disk

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with (RAW_DIR / "coef_series.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(series_rows[0].keys()))
        w.writeheader()
        w.writerows(series_rows)
    (RAW_DIR / "selftest.json").write_text(json.dumps(S["selftest"], indent=1) + "\n")
    (RAW_DIR / "identity.json").write_text(json.dumps(S["identity_check"], indent=1) + "\n")
    (RAW_DIR / "dispersion_summary_raw.json").write_text(json.dumps(S, indent=1) + "\n")
    (DOC_DIR / SUMMARY_NAME).write_text(json.dumps(S, indent=1, ensure_ascii=False) + "\n")
    (DOC_DIR / RESULTS_NAME).write_text(render(S))

    print(f"\nVERDICT: {verdict}")
    for key, cl in S["cells"].items():
        k = cl["kronos_coef"]
        print(f"{key:10s} n={cl['origins_scored']} coef={k['mean']:+.4f} t={k['t']:+.2f} h1={k['half1']:+.4f} h2={k['half2']:+.4f} plain={cl['plain_rank_corr']['mean']:+.4f} r2gain={cl['r2_gain_mean']:+.5f} r2base={cl['r2_simple_only_mean']:.4f}")
    for key, b in S["best_simple"].items():
        print(f"best simple {key}: {b['measure']} {b['mean']:+.4f}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (Stop, K.IdentityError, K.Incomplete) as e:
        print(f"STOPPED: {e}", file=sys.stderr)
        sys.exit(3)
