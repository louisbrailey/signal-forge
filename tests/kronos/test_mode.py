"""Hermetic checks of eval mode and the study-only inference mode.

The real ``worker.py`` runs in a child process against a FAKE ``torch`` and ``model``
package written to a temp directory, so no Kronos code or weights are loaded.
"""

from __future__ import annotations

import ast
import inspect
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from tests.kronos.test_replay import stored  # noqa: F401  (fixture)

from signalforge.kronos import runtime, service, worker

FAKE_TORCH = """
def set_num_threads(n):
    pass

def manual_seed(seed):
    import model
    model.SEED = seed
"""

# predict() returns a close path that encodes the mode the worker actually applied:
# close = 100 (eval) or 200 (train), + T, + top_p/10, + seed/1000.
FAKE_MODEL = """
import pandas as pd

SEED = None
BROKEN_EVAL = False


class _Module:
    def __init__(self):
        self.training = True  # mirrors from_pretrained: modules come back in train mode

    @classmethod
    def from_pretrained(cls, name, local_files_only=False):
        assert local_files_only
        return cls()

    def eval(self):
        if not BROKEN_EVAL:
            self.training = False
        return self

    def train(self, mode=True):
        self.training = mode
        return self


class Kronos(_Module):
    pass


class KronosTokenizer(_Module):
    pass


class KronosPredictor:
    def __init__(self, model, tokenizer, device=None, max_context=512):
        self.model, self.tokenizer = model, tokenizer

    def predict(self, df, x_timestamp, y_timestamp, pred_len, T, top_p, sample_count, verbose):
        assert sample_count == 1 and verbose is False
        assert self.model.training == self.tokenizer.training
        base = 200.0 if self.model.training else 100.0
        value = base + T + top_p / 10 + SEED / 1000
        return pd.DataFrame({"close": [value] * pred_len}, index=y_timestamp)
"""

HISTORY = [
    {"date": f"2024-01-{1 + i % 28:02d}", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}
    for i in range(128)
]
DATES = ["2024-07-01", "2024-07-02", "2024-07-03", "2024-07-05", "2024-07-08"]
TRAIN = {"eval": False, "T": 1.0, "top_p": 0.9, "samples": 3, "return_paths": True}
A2 = {"eval": True, "T": 0.6, "top_p": 0.9, "samples": 10, "return_paths": True}


@pytest.fixture
def fake_runtime(monkeypatch, tmp_path):
    """Point the runtime at a fake Kronos home executed by this interpreter."""
    home = tmp_path / "kronos-home"
    (home / "model").mkdir(parents=True)
    (home / "model" / "__init__.py").write_text(FAKE_MODEL)
    (home / "model" / "kronos.py").write_text("")
    (home / "torch.py").write_text(FAKE_TORCH)
    monkeypatch.setattr(runtime, "HOME", home)
    monkeypatch.setattr(runtime, "PYTHON", Path(sys.executable))
    monkeypatch.setattr(runtime.tempfile, "tempdir", str(tmp_path))
    return home


def expected(eval_: bool, t: float, top_p: float, sample: int) -> float:
    return (100.0 if eval_ else 200.0) + t + top_p / 10 + (42 + sample) / 1000


# --- validation -----------------------------------------------------------------


def test_default_mode_is_eval_three_samples():
    assert worker.normalise_mode(None) == {
        "eval": True,
        "T": 1.0,
        "top_p": 0.9,
        "samples": 3,
        "return_paths": False,
    }
    assert worker.DEFAULT_MODE["eval"] is True
    out = worker.normalise_mode(None)
    out["eval"] = False  # a copy: callers cannot mutate the production default
    assert worker.DEFAULT_MODE["eval"] is True


def test_mode_round_trip_normalises_numbers():
    assert worker.normalise_mode(A2) == A2
    assert worker.normalise_mode({**A2, "T": 1})["T"] == 1.0
    assert worker.normalise_mode({**A2, "samples": worker.MAX_SAMPLES})["samples"] == 10
    assert worker.normalise_mode({**A2, "T": 0.1, "top_p": 1.0}) == {**A2, "T": 0.1, "top_p": 1.0}


@pytest.mark.parametrize(
    "bad",
    [
        {},
        [],
        "eval",
        {k: v for k, v in A2.items() if k != "eval"},
        {**A2, "extra": 1},
        {**A2, "eval": 1},
        {**A2, "eval": "false"},
        {**A2, "return_paths": 0},
        {**A2, "samples": 0},
        {**A2, "samples": 11},
        {**A2, "samples": 3.0},
        {**A2, "samples": True},
        {**A2, "T": 0.0},
        {**A2, "T": 2.01},
        {**A2, "T": "0.6"},
        {**A2, "T": True},
        {**A2, "T": float("nan")},
        {**A2, "T": float("inf")},
        {**A2, "top_p": 0.0},
        {**A2, "top_p": 1.5},
        {**A2, "top_p": None},
    ],
)
def test_mode_validation_bounds(bad: Any):
    with pytest.raises(ValueError, match="Invalid inference mode"):
        worker.normalise_mode(bad)
    with pytest.raises(runtime.KronosUnavailable, match="Invalid inference mode"):
        runtime.infer(HISTORY, DATES, mode=bad)
    with pytest.raises(ValueError):
        service.study_replay(None, "TEST", 5, as_of=None, mode=bad)  # type: ignore[arg-type]


def test_output_cap_unchanged_and_sufficient_for_ten_paths():
    largest = json.dumps({"paths": [[123456.123456789012] * 20] * 10, "eval": True})
    assert runtime.MAX_OUTPUT == 128 * 1024
    assert len(largest) * 8 < runtime.MAX_OUTPUT


# --- real worker in a child process, fake torch/model ---------------------------


def test_default_request_runs_worker_in_eval_mode(fake_runtime):
    paths = runtime.infer(HISTORY, DATES)
    assert len(paths) == 3 and all(len(p) == 5 for p in paths)
    assert [p[0] for p in paths] == pytest.approx([expected(True, 1.0, 0.9, i) for i in range(3)])


def test_payload_without_mode_key_still_runs_eval(fake_runtime):
    """Even a payload from an older caller (no mode key) gets eval mode in the worker."""
    out = json.loads(runtime.run_worker(json.dumps({"history": HISTORY, "dates": DATES}).encode()))
    assert out["eval"] is True
    assert out["paths"][0][0] == pytest.approx(expected(True, 1.0, 0.9, 0))


def test_study_mode_round_trip_through_worker(fake_runtime):
    paths = runtime.infer(HISTORY, DATES, mode=A2)
    assert len(paths) == 10
    assert [p[-1] for p in paths] == pytest.approx([expected(True, 0.6, 0.9, i) for i in range(10)])
    train = runtime.infer(HISTORY, DATES, mode=TRAIN)
    assert [p[0] for p in train] == pytest.approx([expected(False, 1.0, 0.9, i) for i in range(3)])


def test_worker_rejects_invalid_mode_and_fails_closed(fake_runtime):
    payload = json.dumps({"history": HISTORY, "dates": DATES, "mode": {**A2, "samples": 500}})
    with pytest.raises(runtime.KronosUnavailable, match="Local inference failed"):
        runtime.run_worker(payload.encode())


def test_worker_fails_if_eval_does_not_take_effect(fake_runtime):
    init = fake_runtime / "model" / "__init__.py"
    init.write_text(init.read_text().replace("BROKEN_EVAL = False", "BROKEN_EVAL = True"))
    with pytest.raises(runtime.KronosUnavailable, match="Local inference failed"):
        runtime.infer(HISTORY, DATES)


@pytest.mark.parametrize("reported", [False, None, "true"])
def test_runtime_rejects_unexpected_reported_mode(monkeypatch, tmp_path, reported):
    monkeypatch.setattr(runtime.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(runtime, "runtime_status", lambda: {"configured": True})
    body = json.dumps({"paths": [[1.0] * 5] * 3, "eval": reported}).encode()
    monkeypatch.setattr(runtime, "run_worker", lambda payload: body)
    with pytest.raises(runtime.KronosUnavailable):
        runtime.infer(HISTORY, DATES)


def test_infer_sends_resolved_default_mode(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(runtime, "runtime_status", lambda: {"configured": True})
    seen: list[dict[str, Any]] = []

    def fake(payload: bytes) -> bytes:
        seen.append(json.loads(payload))
        return json.dumps({"paths": [[1.0] * 5] * 3, "eval": True}).encode()

    monkeypatch.setattr(runtime, "run_worker", fake)
    runtime.infer(HISTORY, DATES)
    assert seen[0]["mode"] == worker.DEFAULT_MODE and seen[0]["mode"]["eval"] is True


# --- service --------------------------------------------------------------------


def test_replay_has_no_mode_parameter_and_uses_default(stored, monkeypatch):  # noqa: F811
    assert set(inspect.signature(service.replay).parameters) == {
        "session",
        "symbol",
        "horizon",
        "as_of",
    }
    calls: list[tuple[Any, ...]] = []

    def infer(*args: Any, **kwargs: Any) -> list[list[float]]:
        calls.append((args, kwargs))
        return [[1.0] * 5] * 3

    monkeypatch.setattr(service, "infer", infer)
    result = service.replay(stored, "TEST")
    assert len(calls[0][0]) == 2 and calls[0][1] == {}  # no mode ever leaves replay()
    assert result["inference"] == {"eval": True, "T": 1.0, "top_p": 0.9, "samples": 3}
    assert result["samples"] == 3 and "paths" not in result
    with pytest.raises(TypeError):
        service.replay(stored, "TEST", mode=TRAIN)  # type: ignore[call-arg]


def test_study_replay_round_trip(stored, monkeypatch):  # noqa: F811
    seen: list[dict[str, Any]] = []

    def infer(history: Any, dates: list[str], mode: dict[str, Any]) -> list[list[float]]:
        seen.append(mode)
        return [[100.0 + i] * len(dates) for i in range(mode["samples"])]

    monkeypatch.setattr(service, "infer", infer)
    result = service.study_replay(stored, "TEST", 20, as_of=None, mode=A2)
    assert seen == [A2]
    assert result["samples"] == 10 and len(result["paths"]) == 10
    assert result["inference"] == {"eval": True, "T": 0.6, "top_p": 0.9, "samples": 10}
    assert result["predicted"] == pytest.approx([104.5] * 20)
    assert result["lower"] == [100.0] * 20 and result["upper"] == [109.0] * 20
    json.dumps(result, allow_nan=False)
    train = service.study_replay(stored, "TEST", 5, as_of=None, mode=TRAIN)
    assert train["inference"]["eval"] is False and len(train["paths"]) == 3
    default = service.study_replay(
        stored, "TEST", 5, as_of=None, mode={**TRAIN, "eval": True, "return_paths": False}
    )
    assert "paths" not in default
    assert len({result["id"], train["id"], default["id"]}) == 3  # mode is part of the digest


def test_study_replay_rejects_wrong_path_count(stored, monkeypatch):  # noqa: F811
    monkeypatch.setattr(service, "infer", lambda h, d, mode: [[1.0] * len(d)] * 3)
    with pytest.raises(service.KronosUnavailable, match="Invalid model output"):
        service.study_replay(stored, "TEST", 5, as_of=None, mode=A2)


# --- the web route can never reach the study field -------------------------------


def test_web_route_cannot_request_study_mode():
    from signalforge.app.routers import kronos as router

    source = Path(inspect.getfile(router)).read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
    }
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom | ast.Import)
        for alias in node.names
    }
    for forbidden in ("study_replay", "_replay", "infer", "normalise_mode", "run_worker"):
        assert forbidden not in names and forbidden not in imported
    assert not any("worker" in name or name == "runtime" for name in imported)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "replay":
            assert not node.keywords and len(node.args) == 3  # (db, symbol, horizon) only
    params = set(inspect.signature(router.kronos_replay).parameters)
    assert params == {"request", "db", "user", "symbol", "horizon"}
