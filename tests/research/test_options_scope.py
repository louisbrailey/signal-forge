"""``options_scope_json`` as snapshot identity (D1 §9).

``DataSnapshot``'s only database identity is ``UniqueConstraint("key")``, and
``StrategySealedTest`` is unique on ``(strategy_version_id,
dataset_snapshot_id)``. So without a procedural refusal, a second sealed look at
a materially different options dataset — different ladder, IV policy, ``q``
policy, rate, or spread multiplier — reuses the FIRST sealed row instead of
counting as a new look, and the sealed-look protection is silently defeated.

The unkeyed path is worse: it matches on the symbol set and nothing else, and
the live 24-symbol equity snapshot holds exactly the symbols an options
evaluation asks for. These tests pin both doors shut, and pin that the DDL
protecting the live equity snapshots was not touched to do it.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from signalforge.config.research import OptionsEvaluationConfig
from signalforge.data.options_backfill import OptionsCoverageSummary
from signalforge.db.models import DataSnapshot
from signalforge.research.options_scope import (
    build_options_scope,
    options_scope_hash,
    scopes_match,
)
from signalforge.research.promotion import get_or_create_dataset_snapshot

UNIVERSE = ["AAPL", "MSFT", "SPY"]


def _summary(**kw: object) -> OptionsCoverageSummary:
    base: dict[str, object] = {
        "provider": "massive_options",
        "run_id": 1,
        "window_start": date(2023, 9, 4),
        "window_end": date(2026, 9, 4),
        "cycle_rule": "monthly_third_friday",
        "ladder_id": "LADDER_17",
        "strike_listing_basis": "vendor_as_of",
        "underlyings": tuple(UNIVERSE),
        "cycles_total": 34,
        "cycles_covered": 34,
        "cycles_excluded": 0,
        "exclusions_by_reason": (),
        "contracts_selected": 1156,
        "contracts_fetched": 1156,
        "bars_written": 55_000,
        "bars_skipped": 0,
        "sessions_expected": 55_000,
        "shares_per_contract_refusals": 0,
        "ladder_incomplete_cycles": 0,
        "underlyings_ok": tuple(UNIVERSE),
        "underlyings_failed": (),
        "earliest_available_date": date(2022, 10, 3),
        "max_total_bars": 2_000_000,
        "max_total_bars_prior": 200_000,
        "pacing_s": 12.1,
        "status": "ok",
    }
    base.update(kw)
    return OptionsCoverageSummary(**base)  # type: ignore[arg-type]


# --- the scope document ----------------------------------------------------- #
def test_the_scope_carries_every_assumption_that_changes_what_the_data_means() -> None:
    scope = build_options_scope(_summary(), spread_multiplier=1.0, fill_timing_basis="next_session")

    assert scope["schema_version"] == 1
    assert scope["underlyings"] == sorted(UNIVERSE)
    assert scope["window"] == {"start": "2023-09-04", "end": "2026-09-04"}
    assert scope["ladder"]["id"] == "LADDER_17"
    assert len(scope["ladder"]["offsets"]) == 17
    assert scope["strike_listing_basis"] == "vendor_as_of"
    assert scope["q_policy"]["default_zero_permitted"] is False
    assert scope["iv_policy"]["realised_vol_fallback"] is False
    assert scope["iv_policy"]["extrapolation"] is False
    assert scope["spread_model"]["spread_multipliers"] == [1.0, 2.0]
    assert scope["spread_model"]["multiplier_this_evaluation"] == 1.0
    assert scope["fill_timing"]["print_time_known"] is False
    assert scope["coverage_thresholds"]["gate_0c_cycles_bracket"] == 0.90
    assert scope["options_config_hash"] == OptionsEvaluationConfig().options_config_hash


def test_the_scope_hash_excludes_provenance_but_nothing_else() -> None:
    """A resume adds an ingestion_run id. That must not mint a new snapshot for
    an identical dataset DEFINITION — but every parameter must."""
    a = build_options_scope(_summary(), ingestion_run_ids=(1,))
    b = build_options_scope(_summary(), ingestion_run_ids=(1, 2, 3))
    assert options_scope_hash(a) == options_scope_hash(b)
    assert scopes_match(a, b)

    # gate 4b: baseline and 2x baseline are NOT the same dataset identity
    at_2x = build_options_scope(_summary(), spread_multiplier=2.0)
    assert options_scope_hash(at_2x) != options_scope_hash(a)

    # a weaker point-in-time instrument is a different dataset, always
    proxy = build_options_scope(_summary(strike_listing_basis="first_bar_proxy"))
    assert options_scope_hash(proxy) != options_scope_hash(a)

    # so is a different rate, ladder window, or surface floor
    ev = OptionsEvaluationConfig(risk_free_rate=0.05)
    assert options_scope_hash(build_options_scope(_summary(), evaluation=ev)) != options_scope_hash(
        a
    )
    assert options_scope_hash(
        build_options_scope(_summary(window_end=date(2026, 8, 21)))
    ) != options_scope_hash(a)


def test_null_versus_present_is_a_difference_in_both_directions() -> None:
    scope = build_options_scope(_summary())
    assert not scopes_match(None, scope)
    assert not scopes_match(scope, None)
    assert scopes_match(None, None)
    assert options_scope_hash(None) == ""


# --- the two doors into DataSnapshot ---------------------------------------- #
def test_a_key_reused_with_a_different_options_scope_is_refused(session: Session) -> None:
    scope = build_options_scope(_summary())
    snap = get_or_create_dataset_snapshot(
        session, key="options_v1", symbols=UNIVERSE, options_scope=scope
    )
    assert snap.options_scope_json == scope

    again = get_or_create_dataset_snapshot(
        session, key="options_v1", symbols=UNIVERSE, options_scope=build_options_scope(_summary())
    )
    assert again.id == snap.id  # an IDENTICAL scope still reuses

    with pytest.raises(ValueError, match="different options scope"):
        get_or_create_dataset_snapshot(
            session,
            key="options_v1",
            symbols=UNIVERSE,
            options_scope=build_options_scope(_summary(), spread_multiplier=2.0),
        )


def test_an_equity_snapshot_may_not_be_reinterpreted_as_an_options_one(session: Session) -> None:
    """The NULL-vs-present case, on the keyed path. This is the one that would
    quietly re-scope a live PAPER_APPROVED strategy's snapshot."""
    get_or_create_dataset_snapshot(session, key="universe_24_ex_meta", symbols=UNIVERSE)

    with pytest.raises(ValueError, match="different options scope"):
        get_or_create_dataset_snapshot(
            session,
            key="universe_24_ex_meta",
            symbols=UNIVERSE,
            options_scope=build_options_scope(_summary()),
        )


def test_the_unkeyed_symbol_fallback_refuses_to_match_when_a_scope_is_supplied(
    session: Session,
) -> None:
    """The path that would collapse the options sealed ledger onto the equity
    one: it consults the symbol set and NOTHING else."""
    equity = get_or_create_dataset_snapshot(session, symbols=UNIVERSE)
    assert equity.options_scope_json is None

    scope = build_options_scope(_summary())
    opts = get_or_create_dataset_snapshot(session, symbols=UNIVERSE, options_scope=scope)
    assert opts.id != equity.id
    assert opts.options_scope_json == scope

    # The auto key hashes the SYMBOL SET and nothing else, so without a
    # scope-aware derived key the options row would collide with the equity row
    # on UniqueConstraint("key") — an IntegrityError instead of a decision.
    assert opts.key != equity.key

    # the same scope resolves back to its own row, not to a second one
    assert get_or_create_dataset_snapshot(session, symbols=UNIVERSE, options_scope=scope).id == (
        opts.id
    )
    # a different scope is a different dataset and gets its own row
    other = get_or_create_dataset_snapshot(
        session,
        symbols=UNIVERSE,
        options_scope=build_options_scope(_summary(), spread_multiplier=2.0),
    )
    assert other.id not in (equity.id, opts.id)

    # an unkeyed EQUITY request still reuses the equity row, with its key
    # unchanged by a byte
    again = get_or_create_dataset_snapshot(session, symbols=UNIVERSE)
    assert again.id == equity.id
    assert again.key.startswith("universe_auto_")


def test_the_unique_constraint_protecting_the_live_equity_snapshots_is_untouched(
    db_url: str,
) -> None:
    """Scope identity is procedural on purpose: a UNIQUE over a nullable scope
    column would let two rows with the same key and a NULL scope both be legal,
    silently removing the single-key protection the live equity snapshots rely
    on."""
    from sqlalchemy import create_engine

    engine = create_engine(db_url)
    insp = inspect(engine)
    cols = {c["name"] for c in insp.get_columns("data_snapshot")}
    assert "options_scope_json" in cols

    constrained = {
        tuple(uc["column_names"]) for uc in insp.get_unique_constraints("data_snapshot")
    } | {tuple(ix["column_names"]) for ix in insp.get_indexes("data_snapshot") if ix["unique"]}
    assert ("key",) in constrained
    assert not any("options_scope_json" in cs for cs in constrained)
    engine.dispose()


def test_the_scope_survives_a_round_trip_through_the_database(session: Session) -> None:
    scope = build_options_scope(_summary(), ingestion_run_ids=(7,))
    snap = get_or_create_dataset_snapshot(
        session, key="options_rt", symbols=UNIVERSE, options_scope=scope
    )
    sid = snap.id
    session.commit()
    session.expunge_all()

    stored = session.get(DataSnapshot, sid)
    assert stored is not None
    assert options_scope_hash(stored.options_scope_json) == options_scope_hash(scope)
