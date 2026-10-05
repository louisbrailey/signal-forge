"""``options_scope_json`` — the identity of an options DATASET (D1 §9).

The problem this closes. ``DataSnapshot``'s database identity is
``UniqueConstraint("key")`` **and nothing else**: the symbol set and the
continuity mapping are checked only procedurally, and the description and
source note are checked by nothing at all. So two options evaluations against
materially different datasets — a different band, a different ladder, a
different IV source, a different ``q`` policy, a different spread multiplier —
resolve to the *same* snapshot. ``StrategySealedTest`` is unique on
``(strategy_version_id, dataset_snapshot_id)``, so sealed-look protection is
then silently defeated: a second look at a genuinely different dataset reuses
the first sealed row instead of counting as a new look.

There is a second, worse path. When no key is given,
``get_or_create_dataset_snapshot`` returns the first reusable snapshot whose
sorted symbol set matches, consulting nothing else — and the live 24-symbol
equity snapshot holds exactly the symbols an options evaluation would ask for.
An unkeyed options evaluation would bind to the **equity** snapshot and ignore
this scope entirely, collapsing the options sealed ledger onto the equity one.

Which side of S11 writes it. The backfill returns a plain
``OptionsCoverageSummary`` of counts; **this** module, on the research side,
composes the scope from the pre-registered parameters plus that summary and
writes it onto the snapshot. The dependency arrow is therefore
``research -> data.options_backfill``, which S11 permits; the backfill never
imports research, never writes a research row, and never learns this exists.
"""

from __future__ import annotations

from typing import Any

from signalforge.config.hashing import config_hash
from signalforge.config.research import OptionsEvaluationConfig
from signalforge.data.options_backfill import OptionsCoverageSummary
from signalforge.data.options_cycles import LADDER_17, LADDER_ID

OPTIONS_SCOPE_SCHEMA_VERSION = 1

# ``ingestion_run_ids`` is provenance, not identity: re-running a resume must
# not mint a new snapshot for an identical dataset definition.
_UNHASHED_KEYS = frozenset({"ingestion_run_ids"})


def build_options_scope(
    summary: OptionsCoverageSummary,
    *,
    evaluation: OptionsEvaluationConfig | None = None,
    spread_model_id: str = "",
    spread_multiplier: float = 1.0,
    fill_timing_basis: str = "",
    ingestion_run_ids: tuple[int, ...] = (),
) -> dict[str, Any]:
    """Compose the scope from pre-registered parameters + a coverage summary.

    ``spread_multiplier`` is part of the identity on purpose. Decision 5 makes
    the dual-spread pass permanent on both asset classes; without the
    multiplier here, an evaluation at baseline spread and the same evaluation at
    2x baseline would hash identically, resolve to one snapshot and one sealed
    row, and the gate would enforce nothing.
    """
    ev = evaluation or OptionsEvaluationConfig()
    return {
        "schema_version": OPTIONS_SCOPE_SCHEMA_VERSION,
        "underlyings": sorted(summary.underlyings),
        "window": {
            "start": summary.window_start.isoformat(),
            "end": summary.window_end.isoformat(),
        },
        "cycle_rule": summary.cycle_rule,
        "cycles": summary.cycles_total,
        "dte_entry": {"min": 21, "max": 60},
        "strike_band_pct": 0.15,
        "ladder": {
            "id": summary.ladder_id or LADDER_ID,
            "offsets": list(LADDER_17),
            "min_rungs_per_side": 7,
        },
        "rights": ["call", "put"],
        "fetch_span": {"from_dte": 60, "pre_entry_buffer_sessions": 5},
        "reference_price": {
            "source": "massive",
            "basis": "close",
            "max_staleness_sessions": 3,
        },
        "iv_policy": {
            "primary": "local_bs_inverted",
            "mark_fallback": "same_session_surface",
            "surface_fit": ev.surface_fit,
            "term_interp": ev.surface_term_interp,
            "min_prints_per_expiry": ev.surface_min_prints_per_expiry,
            "min_distinct_strikes": ev.surface_min_distinct_strikes,
            "extrapolation": ev.surface_extrapolation,
            "realised_vol_fallback": ev.realised_vol_fallback,
        },
        "q_policy": {
            "precedence": list(ev.q_precedence),
            "parity_min_pairs": ev.parity_min_pairs,
            "parity_max_abs_log_moneyness": ev.parity_max_abs_log_moneyness,
            "parity_statistic": ev.parity_statistic,
            "default_zero_permitted": ev.q_default_zero_permitted,
        },
        "r_policy": {"source": ev.r_source, "value": ev.risk_free_rate},
        "spread_model": {
            "nbbo_available": False,  # 403 on options AND equities under this entitlement
            "model_id": spread_model_id,
            "spread_multipliers": list(ev.spread_multipliers),
            "multiplier_this_evaluation": spread_multiplier,
        },
        "strike_listing_basis": summary.strike_listing_basis,
        "fill_timing": {"basis": fill_timing_basis, "print_time_known": False},
        "iv_admissibility": {
            "max_price_residual": ev.iv_max_price_residual,
            "min_vega": ev.iv_min_vega,
        },
        "deliverable": {"require_shares_per_contract": ev.require_shares_per_contract},
        "coverage_thresholds": {
            "gate_0c_cycles_bracket": ev.gate_0c_cycles_bracket,
            "gate_0d_session_bars": ev.gate_0d_session_bars,
        },
        "options_config_hash": ev.options_config_hash,
        "ingestion_run_ids": list(ingestion_run_ids),
    }


def options_scope_hash(scope: dict[str, Any] | None) -> str:
    """Stable hash over everything in the scope except pure provenance."""
    if not scope:
        return ""
    return config_hash({k: v for k, v in sorted(scope.items()) if k not in _UNHASHED_KEYS})


def scopes_match(a: dict[str, Any] | None, b: dict[str, Any] | None) -> bool:
    """Identity comparison, with NULL-vs-present counted as a DIFFERENCE.

    A request carrying a scope against a stored row without one is a genuine
    mismatch, and so is the reverse: the equity snapshots have no options scope,
    and an options evaluation must never bind to one.
    """
    if (a is None) != (b is None):
        return False
    if a is None and b is None:
        return True
    return options_scope_hash(a) == options_scope_hash(b)


# --------------------------------------------------------------------------- #
# the `options snapshot` command's fixed inputs and key convention
# --------------------------------------------------------------------------- #
#: D2's modelled spread (NBBO is not entitled): a fraction of the last print
#: with an absolute floor, rounded to tick away from the engine.  An identity
#: string — the constants themselves live in ``PREREGISTERED_COST_MODEL``.
DEFAULT_SPREAD_MODEL_ID = "d2_pct_of_last_print_abs_floor"
#: D2 §10.1: a triggered fill is taken at the session after the signal (t+1).
DEFAULT_FILL_TIMING_BASIS = "next_session"
#: The Stage A index ETFs (IO2 runbook §2), which get a readable key label.
STAGE_A_INDEX_UNDERLYINGS = ("IWM", "QQQ", "SPY")
#: How many leading hex characters of ``options_scope_hash`` the key carries.
SNAPSHOT_KEY_HASH_CHARS = 10


def canonical_options_snapshot_key(scope: dict[str, Any]) -> str:
    """``options_<set>_<provider>_<start>_<end>_<scopehash10>`` (D3 §1 item 4).

    D3 requires the options snapshot key to **carry the scope hash**, so a
    change to any identity parameter cannot reuse a key by accident: the key
    itself moves.  ``<set>`` is ``idx3`` for exactly the Stage A index ETFs and
    ``<n>und`` otherwise; the readable parts are a convenience, the hash suffix
    is the identity.
    """
    underlyings = sorted(str(u).upper() for u in scope.get("underlyings", []))
    label = "idx3" if tuple(underlyings) == STAGE_A_INDEX_UNDERLYINGS else f"{len(underlyings)}und"
    window = scope.get("window", {})
    provider = str((scope.get("reference_price") or {}).get("source", "") or "unknown")
    digest = options_scope_hash(scope)[:SNAPSHOT_KEY_HASH_CHARS]
    return f"options_{label}_{provider}_{window.get('start')}_{window.get('end')}_{digest}"
