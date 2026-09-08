"""FB->META symbol-continuity dataset comparison.

Runs the full promotion pipeline for every default strategy against three
named, separately-identified :class:`~signalforge.db.models.DataSnapshot`
variants so the effect of the FB/META ticker-collision finding on strategy
evidence is directly comparable — with each variant's sealed test preserved
independently (see ``research.promotion``'s dataset-snapshot mechanism: a
changed universe is new data, never a silent overwrite of another variant's
locked result):

* ``baseline``                    — the configured universe, unmodified (raw
                                     META data, known contamination and all).
* ``ex_meta``                      — the configured universe with META removed.
* ``meta_continuity_corrected``    — the configured universe with META replaced
                                     by a verified continuity-bridged series
                                     (only resolvable once a verified
                                     ``SymbolContinuityMapping`` exists).
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from signalforge.db.models import DataSnapshot
from signalforge.research.promotion import (
    PromotionResult,
    evaluate_all_default_strategies,
    get_or_create_dataset_snapshot,
)
from signalforge.settings_store import effective_research_config

BASELINE_KEY = "universe_25_baseline"
EX_META_KEY = "universe_24_ex_meta"
CORRECTED_KEY = "universe_25_meta_continuity_corrected"
ALL_VARIANTS = (BASELINE_KEY, EX_META_KEY, CORRECTED_KEY)

# The short, ergonomic names a CLI user actually types (and this module's own
# early design used internally before the DataSnapshot keys were finalized).
# resolve_variant accepts either form so a caller can never pass a value that
# LOOKS like a valid variant name yet silently fails to match any branch.
SHORT_NAME = {
    "baseline": BASELINE_KEY,
    "ex_meta": EX_META_KEY,
    "meta_continuity_corrected": CORRECTED_KEY,
}


def source_for_variant(
    variant: str, provider: str | None, mapping_id: int | None
) -> str | list[str] | None:
    """The ``source`` filter a promotion evaluation should use for one
    variant: the plain provider name for baseline/ex_meta, or the provider
    PLUS this exact mapping's continuity-bridge tag for the corrected
    variant — without this, ``get_daily_bars`` (an exact/one-of-many source
    filter) would silently return zero bars for the bridged symbol, since
    its bars are deliberately tagged distinctly from raw provider data.
    ``provider=None`` (no filtering at all) passes through unchanged."""
    if provider is None:
        return None
    variant = SHORT_NAME.get(variant, variant)
    if variant == CORRECTED_KEY and mapping_id is not None:
        return [provider, f"continuity_bridge:{mapping_id}"]
    return provider


def resolve_variant(
    session: Session,
    *,
    variant: str,
    exclude_symbol: str = "META",
    derived_symbol: str | None = None,
    mapping_id: int | None = None,
) -> tuple[list[str], DataSnapshot]:
    """Resolve one of the three named comparison variants to
    ``(symbols, dataset_snapshot)``. Idempotent: repeat calls reuse the same
    snapshot row rather than creating a new one each run. ``variant`` accepts
    either the short CLI name ('baseline'/'ex_meta'/'meta_continuity_corrected')
    or the long DataSnapshot key it maps to."""
    variant = SHORT_NAME.get(variant, variant)
    cfg = effective_research_config(session)
    base = list(cfg.universe)

    if variant == BASELINE_KEY:
        snap = get_or_create_dataset_snapshot(
            session,
            key=BASELINE_KEY,
            symbols=base,
            description=(
                f"The configured {len(base)}-symbol universe, unmodified. Includes "
                f"{exclude_symbol}'s raw ingested data, which is known to blend an "
                "unrelated pre-corporate-action ticker holder's price history with the "
                "real successor entity's data — see symbol_continuity_mapping for the "
                "investigation and evidence."
            ),
        )
        return base, snap

    if variant == EX_META_KEY:
        syms = [s for s in base if s != exclude_symbol]
        snap = get_or_create_dataset_snapshot(
            session,
            key=EX_META_KEY,
            symbols=syms,
            description=(
                f"The configured universe with {exclude_symbol} excluded entirely, "
                "rather than silently trading a series known to blend two entities."
            ),
        )
        return syms, snap

    if variant == CORRECTED_KEY:
        if not derived_symbol:
            raise ValueError(
                f"{CORRECTED_KEY} requires a verified derived_symbol from a "
                "SymbolContinuityMapping with validation_status == 'verified'"
            )
        syms = [derived_symbol if s == exclude_symbol else s for s in base]
        snap = get_or_create_dataset_snapshot(
            session,
            key=CORRECTED_KEY,
            symbols=syms,
            description=(
                f"The configured universe with {exclude_symbol} replaced by "
                f"{derived_symbol}: predecessor-symbol bars through the corporate "
                "action's effective date, successor-symbol bars after it — built and "
                "validated once, immutable, sourced from symbol_continuity_mapping."
            ),
            continuity_mapping_id=mapping_id,
        )
        return syms, snap

    raise ValueError(f"unknown dataset variant {variant!r}; expected one of {ALL_VARIANTS}")


def run_comparison(
    session: Session,
    *,
    variants: list[str] | None = None,
    exclude_symbol: str = "META",
    derived_symbol: str | None = None,
    mapping_id: int | None = None,
    start: date | None = None,
    end: date | None = None,
    provider: str | None = None,
) -> dict[str, list[PromotionResult]]:
    """Run every default strategy through the promotion pipeline once per
    requested variant (default: all three, skipping ``meta_continuity_corrected``
    if no ``derived_symbol`` was resolved). Returns ``{variant_key: [PromotionResult, ...]}``.

    ``provider`` is the real market-data provider name (e.g. ``"massive"``) —
    each variant resolves its OWN actual ``source`` filter from it via
    :func:`source_for_variant`, so the corrected variant's bridged symbol is
    actually visible to the backtest (not just the baseline provider tag).
    """
    end = end or date.today()
    start = start or (end - timedelta(days=365 * 10))
    want = list(variants) if variants is not None else [BASELINE_KEY, EX_META_KEY]
    if variants is None and derived_symbol:
        want.append(CORRECTED_KEY)

    out: dict[str, list[PromotionResult]] = {}
    for variant in want:
        syms, snap = resolve_variant(
            session,
            variant=variant,
            exclude_symbol=exclude_symbol,
            derived_symbol=derived_symbol,
            mapping_id=mapping_id,
        )
        out[variant] = evaluate_all_default_strategies(
            session,
            symbols=syms,
            start=start,
            end=end,
            source=source_for_variant(variant, provider, mapping_id),
            dataset_snapshot=snap,
        )
    return out
