"""Standalone worker: only history and held-out dates arrive on stdin."""

import contextlib
import json
import sys
from typing import Any


def offline(event: str, args: tuple[Any, ...]) -> None:
    if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.sendto"}:
        raise RuntimeError("Network disabled for research inference")


def main() -> None:
    sys.addaudithook(offline)
    payload = json.loads(sys.stdin.buffer.read(65537))
    if len(payload["history"]) != 128 or len(payload["dates"]) not in (5, 20):
        raise ValueError("Invalid replay dimensions")
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
        predictor = KronosPredictor(model, tokenizer, device="cpu", max_context=512)
        frame = pd.DataFrame(payload["history"])
        x = pd.Series(pd.to_datetime(frame["date"]))
        y = pd.Series(pd.to_datetime(payload["dates"]))
        paths = []
        for sample in range(3):
            torch.manual_seed(42 + sample)
            np.random.seed(42 + sample)
            forecast = predictor.predict(
                df=frame[["open", "high", "low", "close", "volume"]],
                x_timestamp=x,
                y_timestamp=y,
                pred_len=len(y),
                T=1.0,
                top_p=0.9,
                sample_count=1,
            )
            paths.append([float(v) for v in forecast["close"]])
    print(json.dumps({"paths": paths}, allow_nan=False))


if __name__ == "__main__":
    main()
