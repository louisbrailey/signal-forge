#!/usr/bin/env python3
"""Explicit local experiment CLI. Never installed into the operating scheduler."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from signalforge.domain import Horizon
from signalforge.experiments.comparison import advance, freeze, status
from signalforge.experiments.report import finalize


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "advance", "status", "finalize"))
    parser.add_argument("directory", type=Path, help="NEW private directory for freeze")
    parser.add_argument(
        "--env-file", type=Path, help="Read the operating env locally; never copied"
    )
    parser.add_argument("--source", type=Path, help="Operating SQLite database; opened read-only")
    parser.add_argument("--horizon", choices=("short_swing", "medium_swing"), default="short_swing")
    parser.add_argument(
        "--marks-only", action="store_true", help="No new admissions; continue existing positions"
    )
    args = parser.parse_args()
    if args.env_file:
        from dotenv import load_dotenv

        load_dotenv(args.env_file, override=False)
    if args.action == "freeze":
        if args.source is None:
            parser.error("freeze requires --source")
        cache = Path.home() / ".cache/huggingface/hub"
        model = Path.home() / "my-stack/Kronos"
        roots = [
            cache / "models--NeoQuasar--Kronos-small",
            cache / "models--NeoQuasar--Kronos-Tokenizer-base",
            model / "model",
            model / ".venv/pyvenv.cfg",
        ]
        roots.extend(
            sorted((model / ".venv/lib").glob("python*/site-packages/*.dist-info/METADATA"))
        )
        roots.extend(sorted((model / ".venv/lib").glob("python*/site-packages/*.dist-info/RECORD")))
        result = freeze(args.source, args.directory, roots, horizon=Horizon(args.horizon.upper()))
        result = {k: result[k] for k in ("protocol", "hash", "horizon", "study_days", "notice")}
    elif args.action == "advance":
        result = advance(args.directory, collect=not args.marks_only)
    elif args.action == "finalize":
        result = finalize(args.directory)
    else:
        result = status(args.directory)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
