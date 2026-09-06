"""Offline CSV sniff (no persistence, no network)."""

from __future__ import annotations

from signalforge.portfolio.import_csv import sniff


def test_detects_generic_positions() -> None:
    preview = sniff("Symbol,Quantity,Cost Basis\nAAPL,10,1500\nSPY,5,2200\n")
    assert preview.detected_format == "generic_positions"
    assert preview.row_count == 2
    assert preview.columns == ("Symbol", "Quantity", "Cost Basis")


def test_detects_fidelity_history_shape() -> None:
    preview = sniff("Run Date,Action,Symbol,Quantity,Price\n01/02/2024,BUY,AAPL,10,150\n")
    assert preview.detected_format == "fidelity_history"


def test_unknown_shape() -> None:
    assert sniff("a,b,c\n1,2,3\n").detected_format == "unknown"


def test_empty_input() -> None:
    preview = sniff("")
    assert preview.row_count == 0
    assert preview.detected_format == "unknown"
