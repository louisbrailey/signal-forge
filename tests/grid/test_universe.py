"""Universe resolution: ranked file slicing, explicit lists, rank ordering."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from signalforge.grid.universe import (
    load_universe,
    order_by_rank,
    rank_map,
    resolve_universe_file,
)

_RANKED = ["MU", "NVDA", "AAPL", "AMD", "MSFT", "TSLA"]


@pytest.fixture
def ranked_file(tmp_path: Path) -> Path:
    p = tmp_path / "grid_universe_top1000.json"
    p.write_text(
        json.dumps(
            {
                "screen_run": 3,
                "liquidity_window": ["2026-06-12", "2026-09-08"],
                "top1000": _RANKED,
                "note": "ranked by 60-session median dollar volume",
            }
        ),
        encoding="utf-8",
    )
    return p


def test_top_n_slices_the_ranked_list(ranked_file: Path) -> None:
    uni = load_universe("top3", path=ranked_file)
    assert uni.symbols == ("MU", "NVDA", "AAPL")
    assert uni.screen_run == 3
    assert uni.liquidity_window == ("2026-06-12", "2026-09-08")
    assert "median dollar volume" in uni.ranking_note


def test_all_returns_the_whole_list(ranked_file: Path) -> None:
    assert load_universe("all", path=ranked_file).symbols == tuple(_RANKED)


def test_top_option_overrides_the_spec(ranked_file: Path) -> None:
    assert load_universe("top1000", top=2, path=ranked_file).symbols == ("MU", "NVDA")


def test_explicit_comma_list() -> None:
    uni = load_universe("aapl,msft, nvda")
    assert uni.symbols == ("AAPL", "MSFT", "NVDA")
    assert uni.source == "explicit list"


def test_explicit_symbols_argument() -> None:
    uni = load_universe(symbols=["aapl", "AAPL", "msft"])
    assert uni.symbols == ("AAPL", "MSFT")  # de-duplicated, order preserved


def test_a_file_path_spec(ranked_file: Path) -> None:
    uni = load_universe(str(ranked_file))
    assert uni.symbols == tuple(_RANKED)
    assert uni.source == str(ranked_file)


def test_a_text_file_spec(tmp_path: Path) -> None:
    p = tmp_path / "syms.txt"
    p.write_text("AAPL, MSFT\n# comment\nNVDA\n", encoding="utf-8")
    assert load_universe(str(p)).symbols == ("AAPL", "MSFT", "NVDA")


def test_unknown_spec_raises() -> None:
    with pytest.raises(ValueError):
        load_universe("biggest")


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        resolve_universe_file(tmp_path / "nope.json")


def test_rank_map_and_ordering(ranked_file: Path) -> None:
    rk = rank_map(ranked_file)
    assert rk["MU"] == 0 and rk["TSLA"] == 5

    # Unranked symbols (e.g. the sector ETFs in the research snapshot) sort last,
    # alphabetically, so the order is total and deterministic.
    ordered = order_by_rank(["SPY", "AAPL", "XLK", "MU"], ranking=rk)
    assert ordered == ["MU", "AAPL", "SPY", "XLK"]
    assert order_by_rank(["SPY", "AAPL", "MU"], ranking=rk, top=2) == ["MU", "AAPL"]


def test_resolution_prefers_the_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGNALFORGE_DATA_DIR", str(tmp_path))
    (tmp_path / "grid_universe_top1000.json").write_text(
        json.dumps({"top1000": ["AAA"]}), encoding="utf-8"
    )
    assert load_universe("top1000").symbols == ("AAA",)


def test_the_real_universe_file_is_a_ranked_thousand() -> None:
    """The operator's real list, if this checkout can see it."""
    try:
        path = resolve_universe_file()
    except FileNotFoundError:
        pytest.skip("grid_universe_top1000.json is not present in this checkout")
    uni = load_universe("top1000", path=path)
    assert len(uni.symbols) == 1_000
    assert len(set(uni.symbols)) == 1_000
    assert load_universe("top100", path=path).symbols == uni.symbols[:100]
