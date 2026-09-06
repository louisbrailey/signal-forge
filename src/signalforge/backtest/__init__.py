"""Backtest + walk-forward validation engine.

Deterministic (invariant S4). No look-ahead: features at bar *t* use data <= *t*;
fills occur at *t+1* open or a defined rule. All results are net of modeled costs
(commission + spread + slippage). Never imports :mod:`signalforge.llm`.
"""

from __future__ import annotations
