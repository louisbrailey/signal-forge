"""Universe selection for the grid strategy.

The canonical file is ``data/grid_universe_top1000.json``: a ``top1000`` list of
U.S.-listed common stocks (including ADRs) ranked by 60-session **median dollar
volume**, produced by the liquid-universe screen. Because that ranking is
computed from *today's* liquidity, the list is survivorship-biased — names that
delisted, were acquired, or collapsed before the screen date are simply absent.
Every report states this.

Resolution order for the file (first hit wins):

1. an explicit ``path``;
2. ``<SIGNALFORGE_DATA_DIR>/grid_universe_top1000.json``;
3. ``<repo root>/data/grid_universe_top1000.json``;
4. :data:`MAIN_REPO_UNIVERSE_PATH` — the operator's main checkout, so a run from
   a git worktree (which has no ``data/``) still finds the real list.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from signalforge.config import paths

__all__ = [
    "GridUniverse",
    "UNIVERSE_FILENAME",
    "MAIN_REPO_UNIVERSE_PATH",
    "load_universe",
    "resolve_universe_file",
    "rank_map",
    "order_by_rank",
]

UNIVERSE_FILENAME = "grid_universe_top1000.json"
MAIN_REPO_UNIVERSE_PATH = Path("/Users/louisbrailey/signal-forge/data") / UNIVERSE_FILENAME
_REPO_DATA_DIR = Path(__file__).resolve().parents[3] / "data"


@dataclass(frozen=True, slots=True)
class GridUniverse:
    """A resolved, ordered symbol list plus the provenance of the ranking."""

    name: str
    symbols: tuple[str, ...]
    source: str  # where the list came from (file path, "explicit", ...)
    ranking_note: str = ""
    liquidity_window: tuple[str, ...] = ()
    screen_run: int | None = None
    requested_size: int | None = None

    def __len__(self) -> int:
        return len(self.symbols)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "size": len(self.symbols),
            "requested_size": self.requested_size,
            "source": self.source,
            "ranking_note": self.ranking_note,
            "liquidity_window": list(self.liquidity_window),
            "screen_run": self.screen_run,
            "symbols": list(self.symbols),
        }


def resolve_universe_file(path: str | Path | None = None) -> Path:
    """Locate ``grid_universe_top1000.json``; raises if nothing is found."""
    candidates: list[Path] = []
    if path:
        candidates.append(Path(path).expanduser())
    else:
        candidates.append(paths.data_dir() / UNIVERSE_FILENAME)
        candidates.append(_REPO_DATA_DIR / UNIVERSE_FILENAME)
        candidates.append(MAIN_REPO_UNIVERSE_PATH)
    for cand in candidates:
        if cand.is_file():
            return cand
    tried = ", ".join(str(c) for c in candidates)
    raise FileNotFoundError(f"grid universe file not found — tried: {tried}")


def _read_json_universe(file: Path) -> tuple[list[str], dict[str, Any]]:
    raw: Any = json.loads(file.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return [str(s).strip().upper() for s in raw if str(s).strip()], {}
    if not isinstance(raw, dict):
        raise ValueError(f"{file}: expected a JSON object or list")
    for key in ("top1000", "symbols", "universe", "tickers"):
        val = raw.get(key)
        if isinstance(val, list):
            return [str(s).strip().upper() for s in val if str(s).strip()], raw
    raise ValueError(f"{file}: no 'top1000'/'symbols'/'universe'/'tickers' list found")


def _read_text_universe(file: Path) -> list[str]:
    out: list[str] = []
    for line in file.read_text(encoding="utf-8").splitlines():
        for piece in line.split(","):
            sym = piece.strip().upper()
            if sym and not sym.startswith("#"):
                out.append(sym)
    return out


def _dedupe(symbols: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for s in symbols:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def load_universe(
    spec: str = "top1000",
    *,
    top: int | None = None,
    path: str | Path | None = None,
    symbols: Sequence[str] | None = None,
) -> GridUniverse:
    """Resolve a universe specification.

    ``spec`` accepts:

    * ``"top1000"`` / ``"top100"`` / ``"topN"`` — the ranked file, sliced to N;
    * ``"all"`` — the whole ranked file;
    * a path to a ``.json`` / ``.txt`` / ``.csv`` file of symbols;
    * a comma-separated symbol list (``"AAPL,MSFT"``).

    ``top`` slices whatever was resolved (and wins over the ``topN`` in ``spec``).
    ``symbols`` bypasses resolution entirely with an explicit list.
    """
    if symbols is not None:
        syms = _dedupe(str(s).strip().upper() for s in symbols)
        sliced = syms[:top] if top else syms
        return GridUniverse(
            name="explicit",
            symbols=tuple(sliced),
            source="explicit list",
            ranking_note="caller-supplied order",
            requested_size=top or len(sliced),
        )

    spec = (spec or "top1000").strip()
    spec_path = Path(spec).expanduser()
    if spec_path.suffix.lower() in (".json", ".txt", ".csv") or spec_path.is_file():
        if not spec_path.is_file():
            raise FileNotFoundError(f"universe file not found: {spec_path}")
        if spec_path.suffix.lower() == ".json":
            syms, meta = _read_json_universe(spec_path)
        else:
            syms, meta = _read_text_universe(spec_path), {}
        syms = _dedupe(syms)
        sliced = syms[:top] if top else syms
        return GridUniverse(
            name=spec_path.stem,
            symbols=tuple(sliced),
            source=str(spec_path),
            ranking_note=str(meta.get("note", "")),
            liquidity_window=tuple(str(x) for x in (meta.get("liquidity_window") or ())),
            screen_run=meta.get("screen_run") if isinstance(meta.get("screen_run"), int) else None,
            requested_size=top or len(sliced),
        )

    lowered = spec.lower()
    if "," in spec:
        syms = _dedupe(s.strip().upper() for s in spec.split(","))
        sliced = syms[:top] if top else syms
        return GridUniverse(
            name="explicit",
            symbols=tuple(sliced),
            source="explicit list",
            ranking_note="caller-supplied order",
            requested_size=top or len(sliced),
        )

    n: int | None = None
    if lowered.startswith("top"):
        tail = lowered[3:]
        if tail.isdigit():
            n = int(tail)
        elif tail:
            raise ValueError(f"unrecognised universe spec {spec!r} — use top1000 / top100 / all")
    elif lowered != "all":
        raise ValueError(
            f"unrecognised universe spec {spec!r} — use top1000 / top100 / all, "
            "a file path, or a comma-separated list"
        )

    file = resolve_universe_file(path)
    syms, meta = _read_json_universe(file)
    syms = _dedupe(syms)
    size = top or n
    sliced = syms[:size] if size else syms
    return GridUniverse(
        name=lowered,
        symbols=tuple(sliced),
        source=str(file),
        ranking_note=str(meta.get("note", "")),
        liquidity_window=tuple(str(x) for x in (meta.get("liquidity_window") or ())),
        screen_run=meta.get("screen_run") if isinstance(meta.get("screen_run"), int) else None,
        requested_size=size or len(sliced),
    )


def rank_map(path: str | Path | None = None) -> dict[str, int]:
    """``symbol -> 0-based rank`` from the ranked file (most liquid first)."""
    syms, _ = _read_json_universe(resolve_universe_file(path))
    return {s: i for i, s in enumerate(_dedupe(syms))}


def order_by_rank(
    symbols: Iterable[str],
    *,
    ranking: Mapping[str, int] | None = None,
    path: str | Path | None = None,
    top: int | None = None,
) -> list[str]:
    """Order ``symbols`` by the file's liquidity ranking.

    Symbols absent from the ranking (e.g. the sector ETFs in the 150-symbol
    research snapshot, which the stocks-only screen never ranked) sort AFTER
    every ranked name, alphabetically, so the order is total and deterministic.
    """
    rk = dict(ranking) if ranking is not None else rank_map(path)
    syms = _dedupe(str(s).strip().upper() for s in symbols)
    ordered = sorted(syms, key=lambda s: (rk.get(s, len(rk)), s))
    return ordered[:top] if top else ordered
