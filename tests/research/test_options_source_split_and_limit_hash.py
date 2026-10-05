"""Two sources, one per data kind — and the risk limits inside the options hash.

The live database stores an underlying's daily bars under ``massive`` and its
option rows under ``massive_options``.  The evidence path used to pass ONE
``source`` to both tables, so the chain read matched nothing and every underlying
reported "no option chain rows in the window".  The fixtures here store the two
kinds under their two real labels, which is what makes these tests able to see it.

Second half: gate 0.i's limit set must be inside ``options_config_hash`` (D4
§2.8a / §2.9b), and the snapshot being evaluated must be keyed on that hash.

Synthetic rows only; no provider is contacted (R1).
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from signalforge.cli import app
from signalforge.config.research import OptionsEvaluationConfig, OptionsRiskLimits, ResearchConfig
from signalforge.data.options_backfill import coverage_summary
from signalforge.research.options_evidence import (
    OptionSourceUnresolved,
    load_option_chain_series,
    options_ladder_preview,
    resolve_option_data_source,
    run_underlying,
)
from signalforge.research.options_evidence import (
    assemble_options_evidence as assemble,
)
from signalforge.research.options_gates import (
    OptionsGateThresholds,
    UnderlyingCoverage,
    gate_0b_underlyings,
    gate_0i_risk_limits,
)
from signalforge.research.options_scope import (
    build_options_scope,
    canonical_options_snapshot_key,
    options_scope_hash,
    recorded_option_source,
)
from signalforge.research.options_sensitivity import run_options_sensitivity
from signalforge.research.options_strategies.short_vertical import OPTIONS_PER_STRUCTURE_MAX_LOSS
from tests.research.options_evidence_support import (
    OPTION_SOURCE,
    SOURCE,
    WINDOW_END,
    WINDOW_START,
    StubOptionsStrategy,
    seed_chain,
    seed_coverage_run,
    seed_everything,
    seed_snapshot,
    seed_underlying,
    window,
)
from tests.research.options_gate_support import WINDOW as GATE_WINDOW
from tests.research.options_gate_support import availability

runner = CliRunner()


def _gate(gates: list, label: str):
    return next(g for g in gates if g.label == label)


# --------------------------------------------------------------------------- #
# the fixture itself: two labels, as stored live
# --------------------------------------------------------------------------- #
def test_the_fixture_stores_bars_and_option_rows_under_different_labels() -> None:
    assert SOURCE == "massive"
    assert OPTION_SOURCE == "massive_options"
    assert SOURCE != OPTION_SOURCE


# --------------------------------------------------------------------------- #
# the chain loader takes two explicit sources
# --------------------------------------------------------------------------- #
def test_chain_loads_with_bars_under_one_label_and_option_rows_under_another(
    session: Session,
) -> None:
    seed_everything(session)
    w = window()
    chain = load_option_chain_series(
        session, "SPY", start=w.start, end=w.end, source=SOURCE, option_source=OPTION_SOURCE
    )
    assert chain is not None and len(chain) > 50


def test_the_bar_label_does_not_find_the_option_rows(session: Session) -> None:
    """The original defect, pinned: ``massive`` matches no option row."""
    seed_everything(session)
    w = window()
    assert (
        load_option_chain_series(
            session, "SPY", start=w.start, end=w.end, source=SOURCE, option_source=SOURCE
        )
        is None
    )


def test_an_empty_option_source_is_refused_not_defaulted(session: Session) -> None:
    seed_everything(session)
    w = window()
    with pytest.raises(OptionSourceUnresolved, match="never defaulted"):
        load_option_chain_series(
            session, "SPY", start=w.start, end=w.end, source=SOURCE, option_source=""
        )


def test_a_mismatched_option_source_is_named_in_the_skip_reason(session: Session) -> None:
    """A chain stored under another label is a source mismatch, and says so."""
    seed_everything(session)
    run = run_underlying(
        session,
        StubOptionsStrategy(),
        "SPY",
        window=window(),
        source=SOURCE,
        option_source="some_other_vendor",
        dte_targets=[35],
    )
    assert run.dual is None
    assert "no option chain rows in the window" in run.skipped_reason
    assert "'some_other_vendor'" in run.skipped_reason
    assert OPTION_SOURCE in run.skipped_reason  # what IS stored
    assert run.coverage.source == SOURCE
    assert run.coverage.option_source == "some_other_vendor"


# --------------------------------------------------------------------------- #
# the option source comes from recorded provenance, or not at all
# --------------------------------------------------------------------------- #
def test_resolver_reads_the_scope_and_the_pinned_runs_and_they_agree(session: Session) -> None:
    snap, _ = seed_everything(session)
    assert resolve_option_data_source(session, snap) == OPTION_SOURCE


def test_resolver_reads_the_pinned_runs_when_the_scope_predates_the_field(
    session: Session,
) -> None:
    """The live snapshot's shape: no ``option_data`` block, one pinned run."""
    run = seed_coverage_run(session, ["SPY"])
    snap = seed_snapshot(session, ["SPY"], ingestion_run_ids=[run.id], option_source=None)
    assert recorded_option_source(snap.options_scope_json) == ""
    assert resolve_option_data_source(session, snap) == OPTION_SOURCE


def test_resolver_refuses_when_nothing_names_an_option_source(session: Session) -> None:
    snap = seed_snapshot(session, ["SPY"], ingestion_run_ids=[], option_source=None)
    with pytest.raises(OptionSourceUnresolved, match="names no option-data source"):
        resolve_option_data_source(session, snap)


def test_resolver_refuses_a_run_that_is_not_stored(session: Session) -> None:
    snap = seed_snapshot(session, ["SPY"], ingestion_run_ids=[987654])
    with pytest.raises(OptionSourceUnresolved, match="not stored"):
        resolve_option_data_source(session, snap)


def test_resolver_refuses_when_scope_and_runs_disagree(session: Session) -> None:
    run = seed_coverage_run(session, ["SPY"])
    snap = seed_snapshot(
        session, ["SPY"], ingestion_run_ids=[run.id], option_source="some_other_vendor"
    )
    with pytest.raises(OptionSourceUnresolved, match="does not name ONE"):
        resolve_option_data_source(session, snap)


def test_resolver_refuses_runs_from_two_option_sources(session: Session) -> None:
    """R6 per data kind: one options source.  Two is a blend."""
    a = seed_coverage_run(session, ["SPY"])
    b = seed_coverage_run(session, ["QQQ"], provider="some_other_vendor")
    snap = seed_snapshot(
        session, ["SPY", "QQQ"], ingestion_run_ids=[a.id, b.id], option_source=None
    )
    with pytest.raises(OptionSourceUnresolved, match="R6 forbids a blend"):
        resolve_option_data_source(session, snap)


def test_resolver_never_falls_back_to_the_bar_source(session: Session) -> None:
    """Bars exist under ``massive``; that must not become the option source."""
    seed_underlying(session, "SPY")
    seed_chain(session, "SPY")
    snap = seed_snapshot(session, ["SPY"], ingestion_run_ids=[], option_source=None)
    session.commit()
    with pytest.raises(OptionSourceUnresolved):
        assemble(session, StubOptionsStrategy(), dataset_snapshot=snap, window=window())


# --------------------------------------------------------------------------- #
# the assembler and the grid, end to end on the two-label dataset
# --------------------------------------------------------------------------- #
def test_assembler_evaluates_every_underlying_on_the_two_label_dataset(session: Session) -> None:
    snap, _ = seed_everything(session)
    assembled = assemble(
        session, StubOptionsStrategy(), dataset_snapshot=snap, window=window(), source=SOURCE
    )
    assert [r.symbol for r in assembled.per_underlying if r.dual is None] == []
    assert len(assembled.evidence.dual.baseline.trades) > 0
    assert not any("no option chain rows" in n for n in assembled.notes)
    av = assembled.evidence.availability
    assert av.required_source == SOURCE
    assert av.required_option_source == OPTION_SOURCE
    assert {u.source for u in av.underlyings} == {SOURCE}
    assert {u.option_source for u in av.underlyings} == {OPTION_SOURCE}
    gate = gate_0b_underlyings(av)
    assert gate.passed, gate.detail
    assert gate.evidence["underlying_source"] == SOURCE
    assert gate.evidence["option_data_source"] == OPTION_SOURCE


def test_assembler_reports_no_chain_when_the_recorded_source_holds_no_rows(
    session: Session,
) -> None:
    """Provenance names a source the rows are NOT stored under: nothing is
    evaluable, the note names both labels, and gate 0.b fails — no silent pass,
    and no quiet switch to the label that does hold rows."""
    for sym in ("SPY",):
        seed_underlying(session, sym)
        seed_chain(session, sym)  # stored under OPTION_SOURCE
    run = seed_coverage_run(session, ["SPY"], provider="some_other_vendor")
    snap = seed_snapshot(
        session, ["SPY"], ingestion_run_ids=[run.id], option_source="some_other_vendor"
    )
    session.commit()
    assembled = assemble(session, StubOptionsStrategy(), dataset_snapshot=snap, window=window())
    assert all(r.dual is None for r in assembled.per_underlying)
    assert any("'some_other_vendor'" in n and OPTION_SOURCE in n for n in assembled.notes)
    assert not gate_0b_underlyings(assembled.evidence.availability).passed


def test_the_sensitivity_grid_uses_the_recorded_option_source(session: Session) -> None:
    snap, _ = seed_everything(session)
    strat = StubOptionsStrategy()
    axes = strat.sensitivity_axes()
    report = run_options_sensitivity(
        session,
        strat,
        lambda _p: StubOptionsStrategy(),
        baseline_params={k: v[0] for k, v in axes.items()},
        dataset_snapshot=snap,
        window=window(),
        version="0.0.1",
        options_config_hash="h",
        source=SOURCE,
        use_cache=False,
    )
    # every grid point found the chain: a mis-sourced grid reports 0 trades everywhere
    assert report.grid and all(p.n_trades > 0 for p in report.grid)


def test_the_sensitivity_grid_refuses_an_unnamed_option_source(session: Session) -> None:
    seed_underlying(session, "SPY")
    seed_chain(session, "SPY")
    snap = seed_snapshot(session, ["SPY"], ingestion_run_ids=[], option_source=None)
    session.commit()
    strat = StubOptionsStrategy()
    with pytest.raises(OptionSourceUnresolved):
        run_options_sensitivity(
            session,
            strat,
            lambda _p: StubOptionsStrategy(),
            baseline_params={k: v[0] for k, v in strat.sensitivity_axes().items()},
            dataset_snapshot=snap,
            window=window(),
            version="0.0.1",
            options_config_hash="h",
            use_cache=False,
        )


# --------------------------------------------------------------------------- #
# gate 0.b — R6 per data kind
# --------------------------------------------------------------------------- #
def _cov(symbol: str, source: str, option_source: str) -> UnderlyingCoverage:
    return UnderlyingCoverage(
        symbol, source, GATE_WINDOW.start, GATE_WINDOW.end, 0, option_source=option_source
    )


def test_gate_0b_passes_one_bar_source_and_one_option_source() -> None:
    av = availability(
        underlyings=(
            _cov("SPY", "massive", "massive_options"),
            _cov("QQQ", "massive", "massive_options"),
        )
    )
    assert gate_0b_underlyings(av).passed


def test_gate_0b_still_fails_genuinely_blended_bar_sources() -> None:
    """Unchanged semantics: two BAR sources is the blend R6 forbids."""
    av = availability(
        underlyings=(
            _cov("SPY", "massive", "massive_options"),
            _cov("QQQ", "yfinance", "massive_options"),
        )
    )
    gate = gate_0b_underlyings(av)
    assert not gate.passed
    assert "sources ['massive', 'yfinance'] != ['massive'] — R6 forbids a blend" in gate.detail


def test_gate_0b_fails_a_single_wrong_bar_source() -> None:
    av = availability(underlyings=(_cov("SPY", "yfinance", "massive_options"),))
    gate = gate_0b_underlyings(av)
    assert not gate.passed
    assert "sources ['yfinance'] != ['massive']" in gate.detail


def test_gate_0b_fails_blended_option_sources() -> None:
    av = availability(
        underlyings=(
            _cov("SPY", "massive", "massive_options"),
            _cov("QQQ", "massive", "some_other_vendor"),
        )
    )
    gate = gate_0b_underlyings(av)
    assert not gate.passed
    assert "option-data sources ['massive_options', 'some_other_vendor']" in gate.detail
    assert "R6 forbids a blend" in gate.detail
    # the bar half is clean and is not blamed
    assert "sources ['massive'] !=" not in gate.detail


def test_gate_0b_does_not_accept_the_bar_label_as_the_option_source() -> None:
    """The two labels differing is the NORMAL case, never itself a blend; but an
    underlying whose option rows were read under the bar label is a mismatch."""
    av = availability(underlyings=(_cov("SPY", "massive", "massive"),))
    assert not gate_0b_underlyings(av).passed


def test_gate_0b_fails_when_no_option_source_is_named() -> None:
    av = availability(required_option_source="")
    gate = gate_0b_underlyings(av)
    assert not gate.passed
    assert "no option-data source is named" in gate.detail


# --------------------------------------------------------------------------- #
# the scope records the option source, and it is identity
# --------------------------------------------------------------------------- #
def test_scope_records_the_runs_provider_as_the_option_source(session: Session) -> None:
    summary = coverage_summary(seed_coverage_run(session, ["SPY"]))
    scope = build_options_scope(summary)
    assert scope["option_data"] == {"source": OPTION_SOURCE}
    assert scope["reference_price"]["source"] == "massive"
    assert recorded_option_source(scope) == OPTION_SOURCE


def test_a_different_option_source_is_a_different_dataset(session: Session) -> None:
    summary = coverage_summary(seed_coverage_run(session, ["SPY"]))
    other = replace(summary, provider="some_other_vendor")
    assert options_scope_hash(build_options_scope(summary)) != options_scope_hash(
        build_options_scope(other)
    )


def test_scope_refuses_a_summary_that_names_no_provider(session: Session) -> None:
    summary = replace(coverage_summary(seed_coverage_run(session, ["SPY"])), provider="")
    with pytest.raises(ValueError, match="never guesses"):
        build_options_scope(summary)


# --------------------------------------------------------------------------- #
# gate 0.i — the limit set is inside options_config_hash
# --------------------------------------------------------------------------- #
def test_the_limit_set_is_a_field_of_the_hashed_evaluation_config() -> None:
    fields = set(OptionsEvaluationConfig.model_fields)
    assert {"options_per_structure_max_loss", "options_total_open_max_loss"} <= fields
    dumped = OptionsEvaluationConfig().model_dump(mode="json")
    assert dumped["options_per_structure_max_loss"] == 900.0
    assert dumped["options_total_open_max_loss"] == 3600.0


def test_every_copy_of_the_op1_limits_agrees() -> None:
    """OP-1's $900 / $3,600 in the hashed config, the gate thresholds, the paper
    book's refusal-only caps and the strategy's declared cap: one decision."""
    ev, th, paper = OptionsEvaluationConfig(), OptionsGateThresholds(), OptionsRiskLimits()
    assert ev.options_per_structure_max_loss == th.options_per_structure_max_loss == 900.0
    assert ev.options_total_open_max_loss == th.options_total_open_max_loss == 3600.0
    assert paper.per_structure_max_loss_dollars == ev.options_per_structure_max_loss
    assert paper.total_open_max_loss_dollars == ev.options_total_open_max_loss
    assert ev.options_per_structure_max_loss == OPTIONS_PER_STRUCTURE_MAX_LOSS


@pytest.mark.parametrize(
    "override",
    [{"options_per_structure_max_loss": 1200.0}, {"options_total_open_max_loss": 5000.0}],
)
def test_moving_a_limit_moves_the_config_hash_the_scope_hash_and_the_key(
    session: Session, override: dict[str, float]
) -> None:
    summary = coverage_summary(seed_coverage_run(session, ["SPY"]))
    base, moved = OptionsEvaluationConfig(), OptionsEvaluationConfig(**override)
    assert moved.options_config_hash != base.options_config_hash
    a = build_options_scope(summary, evaluation=base)
    b = build_options_scope(summary, evaluation=moved)
    assert options_scope_hash(a) != options_scope_hash(b)
    assert canonical_options_snapshot_key(a) != canonical_options_snapshot_key(b)


def test_hashing_the_limits_does_not_move_the_equity_scope_hash() -> None:
    """D3 §1.4: the equity ``config_hash`` (7fb8213a…) is untouched."""
    assert ResearchConfig().config_hash.startswith("7fb8213a")


def test_gate_0i_sees_the_limits_as_hashed_on_a_snapshot_keyed_on_this_config(
    session: Session,
) -> None:
    snap, _ = seed_everything(session)
    assembled = assemble(session, StubOptionsStrategy(), dataset_snapshot=snap, window=window())
    av = assembled.evidence.availability
    assert av.limits_in_options_config_hash is True
    assert av.limits_hash_detail == ""
    gate = _gate(options_ladder_preview(assembled.evidence, window=window()), "0.i")
    assert "NOT inside options_config_hash" not in gate.detail


def test_gate_0i_fails_a_snapshot_minted_under_another_config_hash(session: Session) -> None:
    """The superseded-snapshot case: its key is not bound to these limits."""
    for sym in ("SPY",):
        seed_underlying(session, sym)
        seed_chain(session, sym)
    run = seed_coverage_run(session, ["SPY"])
    snap = seed_snapshot(
        session, ["SPY"], ingestion_run_ids=[run.id], options_config_hash="554de314845538ce"
    )
    session.commit()
    assembled = assemble(session, StubOptionsStrategy(), dataset_snapshot=snap, window=window())
    av = assembled.evidence.availability
    assert av.limits_in_options_config_hash is False
    assert "554de3148455" in av.limits_hash_detail and "superseded" in av.limits_hash_detail
    gate = gate_0i_risk_limits(av, OptionsGateThresholds())
    assert not gate.passed
    assert "NOT inside options_config_hash" in gate.detail
    assert any(n.startswith("gate 0.i:") for n in assembled.notes)


def test_gate_0i_fails_when_the_applied_limits_are_not_the_hashed_ones(session: Session) -> None:
    """A hashed $900 beside an applied $1,200 binds nothing: raising the gate's
    cap without moving the hashed config must not read as 'hashed'."""
    snap, _ = seed_everything(session)
    loose = replace(OptionsGateThresholds(), options_per_structure_max_loss=1200.0)
    assembled = assemble(
        session, StubOptionsStrategy(), dataset_snapshot=snap, window=window(), thresholds=loose
    )
    av = assembled.evidence.availability
    assert av.limits_in_options_config_hash is False
    assert "hashed 900.00 vs applied 1,200.00" in av.limits_hash_detail
    assert not gate_0i_risk_limits(av, loose).passed


def test_gate_0i_still_fails_on_the_flag_alone() -> None:
    """The gate is not weakened: an unhashed limit set fails whatever else holds."""
    gate = gate_0i_risk_limits(
        availability(limits_in_options_config_hash=False), OptionsGateThresholds()
    )
    assert not gate.passed


# --------------------------------------------------------------------------- #
# the CLI says the same things, before any evidence is assembled
# --------------------------------------------------------------------------- #
_ARGS = (
    "options",
    "evaluate-promotion",
    "--strategy",
    "options_short_vertical.medium_swing",
    "--since",
    WINDOW_START.isoformat(),
    "--until",
    WINDOW_END.isoformat(),
    "--sealed-days",
    "30",
)


def test_cli_refuses_a_snapshot_keyed_on_a_stale_options_config_hash(session: Session) -> None:
    seed_underlying(session, "SPY")
    seed_chain(session, "SPY")
    run = seed_coverage_run(session, ["SPY"])
    seed_snapshot(
        session,
        ["SPY"],
        key="stale_hash_snapshot",
        ingestion_run_ids=[run.id],
        options_config_hash="554de314845538ce",
    )
    session.commit()
    res = runner.invoke(app, [*_ARGS, "--snapshot-key", "stale_hash_snapshot", "--confirm"])
    assert res.exit_code == 2
    assert "records options_config_hash 554de3148455" in res.output
    assert "superseded" in res.output
    assert "no sealed look was spent" in res.output


def test_cli_dry_run_finds_the_chain_on_the_two_label_dataset(session: Session) -> None:
    seed_everything(session)
    res = runner.invoke(app, [*_ARGS, "--snapshot-key", "options_w3b_test"])
    assert "no option chain rows in the window" not in res.output
    assert "underlyings evaluable: 2/2" in res.output
    assert "NOT inside options_config_hash" not in res.output
