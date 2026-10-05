"""Standalone worker: only history, held-out dates and inference mode arrive on stdin."""

import contextlib
import json
import sys
from typing import Any

# Production (dashboard) behaviour. ``eval`` is always True here: the model and the
# tokenizer are put in eval mode so dropout is inactive at inference.
DEFAULT_MODE: dict[str, Any] = {
    "eval": True,
    "T": 1.0,
    "top_p": 0.9,
    "samples": 3,
    "return_paths": False,
}
MAX_SAMPLES = 10
T_BOUNDS = (0.1, 2.0)
TOP_P_BOUNDS = (0.1, 1.0)
SEED = 42


def normalise_mode(mode: Any) -> dict[str, Any]:
    """Strictly validate a study-only inference mode; ``None`` means production defaults.

    Exactly the five known keys, exact types (bool is never accepted as a number) and
    bounded sizes. Raises ``ValueError`` on anything else.
    """
    if mode is None:
        return dict(DEFAULT_MODE)
    if type(mode) is not dict or set(mode) != set(DEFAULT_MODE):
        raise ValueError("Invalid inference mode")
    if type(mode["eval"]) is not bool or type(mode["return_paths"]) is not bool:
        raise ValueError("Invalid inference mode")
    if type(mode["samples"]) is not int or not 1 <= mode["samples"] <= MAX_SAMPLES:
        raise ValueError("Invalid inference mode")
    out: dict[str, Any] = {
        "eval": mode["eval"],
        "samples": mode["samples"],
        "return_paths": mode["return_paths"],
    }
    for key, (low, high) in (("T", T_BOUNDS), ("top_p", TOP_P_BOUNDS)):
        value = mode[key]
        if type(value) not in (int, float) or not low <= value <= high:  # also rejects NaN
            raise ValueError("Invalid inference mode")
        out[key] = float(value)
    return out


def offline(event: str, args: tuple[Any, ...]) -> None:
    if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.sendto"}:
        raise RuntimeError("Network disabled for research inference")


def main() -> None:
    sys.addaudithook(offline)
    payload = json.loads(sys.stdin.buffer.read(65537))
    if len(payload["history"]) != 128 or len(payload["dates"]) not in (5, 20):
        raise ValueError("Invalid replay dimensions")
    mode = normalise_mode(payload.get("mode"))
    sys.path.insert(0, sys.argv[1])
    with contextlib.redirect_stdout(sys.stderr):
        import numpy as np
        import pandas as pd
        import torch  # type: ignore[import-not-found]
        from model import Kronos, KronosPredictor, KronosTokenizer  # type: ignore[import-not-found]

        torch.set_num_threads(4)
        tokenizer = KronosTokenizer.from_pretrained(
            "NeoQuasar/Kronos-Tokenizer-base", local_files_only=True
        )
        model = Kronos.from_pretrained("NeoQuasar/Kronos-small", local_files_only=True)
        # from_pretrained leaves modules in train mode (dropout active). Inference must
        # run in eval mode; train mode is kept reachable only for the study's replication
        # arm of the pre-fix behaviour, and is set explicitly so it never depends on
        # whatever state the loader happens to return.
        if mode["eval"]:
            tokenizer.eval()
            model.eval()
        else:
            tokenizer.train()
            model.train()
        if bool(model.training) is mode["eval"] or bool(tokenizer.training) is mode["eval"]:
            raise RuntimeError("Model mode does not match the requested mode")
        predictor = KronosPredictor(model, tokenizer, device="cpu", max_context=512)
        frame = pd.DataFrame(payload["history"])
        x = pd.Series(pd.to_datetime(frame["date"]))
        y = pd.Series(pd.to_datetime(payload["dates"]))
        paths = []
        for sample in range(mode["samples"]):
            torch.manual_seed(SEED + sample)
            np.random.seed(SEED + sample)
            forecast = predictor.predict(
                df=frame[["open", "high", "low", "close", "volume"]],
                x_timestamp=x,
                y_timestamp=y,
                pred_len=len(y),
                T=mode["T"],
                top_p=mode["top_p"],
                sample_count=1,
                verbose=False,
            )
            paths.append([float(v) for v in forecast["close"]])
        in_eval = not model.training and not tokenizer.training
    print(json.dumps({"paths": paths, "eval": in_eval}, allow_nan=False))


if __name__ == "__main__":
    main()
