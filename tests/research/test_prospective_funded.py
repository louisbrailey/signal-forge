from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from signalforge.backtest.actions import Dividend, Split
from signalforge.backtest.engine import EntrySignal
from signalforge.backtest.funded import run_funded_replay
from signalforge.config.research import RiskLimits
from signalforge.data.calendar import sessions
from signalforge.data.series import PriceSeries
from signalforge.domain import Direction
from signalforge.research import action_replay
from signalforge.research import prospective_funded as pf
from signalforge.research.action_replay import ActionDataset, input_fingerprints
from signalforge.research.prospective_funded import (
    amend_collector,
    collection_state,
    entries_blocked,
    entry_signal_days,
    freeze,
    record_collection,
    retain_recorded_inputs,
    validate_plan,
    without_entries_on,
)


def plan(root):
    return freeze(
        root,
        {"SPY": {"instrument_type": "etf", "sector": "broad"}},
        (),
        ["SPY"],
        date(2023, 1, 1),
        now=datetime(2024, 1, 2, 20, tzinfo=UTC),
    )


def report(day, value="10000", blocked=()):
    extra = {"blocked_entry_sessions": list(blocked)} if blocked else {}
    return extra | {
        "end": str(day),
        "input_prefix_fingerprints": {str(d): "test-hash" for d in sessions(date(2024, 1, 3), day)},
        "books": {
            "A": {
                "scenarios": {
                    "base": {
                        "result": {
                            "marks": [{"day": "2024-01-03", "net_liquidation_usd": value}],
                            "fills": [],
                            "decisions": [],
                            "corporate_events": [],
                        }
                    }
                }
            }
        },
    }


def test_freeze_cannot_be_overwritten_and_code_change_halts(tmp_path, monkeypatch):
    p = plan(tmp_path)
    assert p["first_observation_session"] == "2024-01-03"
    assert p["first_entry_session"] == "2024-01-04"
    with pytest.raises(ValueError, match="Plan exists"):
        plan(tmp_path)
    monkeypatch.setattr("signalforge.research.prospective_funded.code_digest", lambda: "changed")
    with pytest.raises(ValueError, match="code changed"):
        validate_plan(tmp_path)


def test_forward_records_are_immutable_and_revisions_block(tmp_path):
    plan(tmp_path)
    day = date(2024, 1, 3)
    first = record_collection(tmp_path, day, report(day))
    assert record_collection(tmp_path, day, report(day)) == first
    with pytest.raises(ValueError, match="rewrite"):
        record_collection(tmp_path, day, report(day, "10001"))
    with pytest.raises(ValueError, match="history changed"):
        record_collection(tmp_path, date(2024, 1, 4), report(date(2024, 1, 4), "10001"))


def test_missed_session_is_recorded_and_must_block_entries(tmp_path):
    plan(tmp_path)
    day = date(2024, 1, 4)
    with pytest.raises(ValueError, match="not blocked from entries"):
        record_collection(tmp_path, day, report(day))
    saved = record_collection(tmp_path, day, report(day, blocked=["2024-01-03"]))
    assert saved["missed_sessions"] == ["2024-01-03"]
    assert saved["blocked_entry_sessions"] == ["2024-01-03"]
    assert saved["elapsed_sessions"] == 2
    assert saved["observed_sessions"] == 1  # a missed session is never an observation


def test_study_continues_after_a_gap_and_blocks_stay_cumulative(tmp_path):
    plan(tmp_path)
    record_collection(tmp_path, date(2024, 1, 3), report(date(2024, 1, 3)))
    monday = date(2024, 1, 8)  # Thu 4th and Fri 5th were never collected
    state = collection_state(tmp_path, monday)
    assert state["missed"] == [date(2024, 1, 4), date(2024, 1, 5)]
    assert state["blocked"] == (date(2024, 1, 4), date(2024, 1, 5))
    gap = ["2024-01-04", "2024-01-05"]
    saved = record_collection(tmp_path, monday, report(monday, blocked=gap))
    assert saved["missed_sessions"] == gap
    assert saved["observed_sessions"] == 2
    tuesday = date(2024, 1, 9)
    assert collection_state(tmp_path, tuesday)["missed"] == []
    with pytest.raises(ValueError, match="not blocked"):  # an old gap cannot be re-traded
        record_collection(tmp_path, tuesday, report(tuesday))
    saved = record_collection(tmp_path, tuesday, report(tuesday, blocked=gap))
    assert saved["missed_sessions"] == []
    assert saved["blocked_entry_sessions"] == gap
    with pytest.raises(ValueError, match="Out-of-order"):
        collection_state(tmp_path, monday)


def test_raw_revision_blocks_even_when_trades_would_not_change(tmp_path):
    plan(tmp_path)
    record_collection(tmp_path, date(2024, 1, 3), report(date(2024, 1, 3)))
    revised = report(date(2024, 1, 4))
    revised["input_prefix_fingerprints"]["2024-01-03"] = "revision"
    with pytest.raises(ValueError, match="raw inputs changed"):
        record_collection(tmp_path, date(2024, 1, 4), revised)


def test_no_forward_outcome_is_claimed_at_freeze(tmp_path):
    from signalforge.research.prospective_funded import review_readiness

    plan(tmp_path)
    r = review_readiness(tmp_path)
    assert r["observed_sessions"] == 0
    assert r["status"] == "WAITING_FOR_FUTURE_EVIDENCE"


def _dataset(rows, dividends=(), end=date(2024, 1, 5)):
    return ActionDataset(
        {
            symbol: PriceSeries.from_bars(symbol, [(d, *v) for d, v in sorted(bars.items())])
            for symbol, bars in rows.items()
        },
        (),
        tuple(dividends),
        (),
        "manifest",
        date(2024, 1, 2),
        end,
    )


def _bars(*days, close=100.0, volume=1000.0):
    return dict.fromkeys(days, (close, close + 1, close - 1, close, volume))


def test_vendor_revision_is_quarantined_and_recorded_not_applied():
    d2, d3, d4, d5 = date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5)
    div = Dividend("SPY", d3, d5, Decimal("1.50"), "massive")
    recorded = _dataset({"SPY": _bars(d2, d3)}, [div], end=d3)
    revised_bars = _bars(d2, d3, d4) | {d3: (100.0, 101.0, 99.0, 100.0, 1234.5)}
    vendor = _dataset({"SPY": revised_bars}, [div], end=d4)
    assert input_fingerprints(vendor)[str(d3)] != input_fingerprints(recorded)[str(d3)]

    effective, events = retain_recorded_inputs(vendor, recorded, {}, d3)

    # First-recorded inputs are kept, so prior decisions cannot change; new bars are used.
    assert input_fingerprints(effective)[str(d3)] == input_fingerprints(recorded)[str(d3)]
    assert effective.series["SPY"].dates == (d2, d3, d4)
    assert effective.series["SPY"].volume[1] == 1000.0
    assert effective.dividends == (div,)
    assert [(e["kind"], e["day"]) for e in events] == [("bar", "2024-01-03")]
    assert events[0]["vendor_previous"][4] == 1000.0
    assert events[0]["vendor_revised"][4] == 1234.5
    assert events[0]["retained"] == events[0]["vendor_previous"]

    # A later snapshot keeps the pin even when the vendor does not revise again.
    retained = {(e["kind"], e["symbol"], e["day"]): e["retained"] for e in events}
    later = _dataset({"SPY": revised_bars | _bars(d5)}, [div], end=d5)
    again, more = retain_recorded_inputs(later, vendor, retained, d4)
    assert more == []
    assert input_fingerprints(again)[str(d4)] == input_fingerprints(effective)[str(d4)]


def test_late_corporate_event_on_recorded_history_still_halts():
    d2, d3, d4, d5 = date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5)
    recorded = _dataset({"SPY": _bars(d2, d3)}, end=d3)
    split = Split("SPY", d3, Decimal(2), "massive")
    late_split = _dataset({"SPY": _bars(d2, d3, d4)}, end=d4)
    late_split.splits = (split,)
    with pytest.raises(ValueError, match="corporate event revised"):
        retain_recorded_inputs(late_split, recorded, {}, d3)
    late_div = _dataset({"SPY": _bars(d2, d3, d4)}, [Dividend("SPY", d3, d5, Decimal(1), "m")])
    with pytest.raises(ValueError, match="corporate event revised"):
        retain_recorded_inputs(late_div, recorded, {}, d3)
    # A split effective after the last recorded session is new data, not a revision.
    future = _dataset({"SPY": _bars(d2, d3, d4)}, end=d4)
    future.splits = (Split("SPY", d4, Decimal(2), "massive"),)
    assert retain_recorded_inputs(future, recorded, {}, d3)[1] == []
    with pytest.raises(ValueError, match="only bars"):
        retain_recorded_inputs(recorded, recorded, {("dividend", "SPY", str(d3)): None}, d3)


def test_vendor_coverage_change_still_halts():
    d2, d3 = date(2024, 1, 2), date(2024, 1, 3)
    recorded = _dataset({"SPY": _bars(d2, d3)}, end=d3)
    vendor = _dataset({"SPY": _bars(d2, d3), "QQQ": _bars(d2, d3)}, end=d3)
    with pytest.raises(ValueError, match="raw inputs changed"):
        retain_recorded_inputs(vendor, recorded, {}, d3)


def test_record_keeps_quarantined_revisions_and_rejects_future_ones(tmp_path):
    plan(tmp_path)
    record_collection(tmp_path, date(2024, 1, 3), report(date(2024, 1, 3)))
    event = {
        "kind": "bar",
        "symbol": "SPY",
        "day": "2024-01-03",
        "vendor_previous": [1.0, 1.0, 1.0, 1.0, 10.0],
        "vendor_revised": [1.0, 1.0, 1.0, 1.0, 11.0],
        "retained": [1.0, 1.0, 1.0, 1.0, 10.0],
    }
    future = event | {"day": "2024-01-04"}
    with pytest.raises(ValueError, match="outside recorded history"):
        record_collection(
            tmp_path, date(2024, 1, 4), report(date(2024, 1, 4)), vendor_revisions=[future]
        )
    saved = record_collection(
        tmp_path, date(2024, 1, 4), report(date(2024, 1, 4)), vendor_revisions=[event]
    )
    assert saved["vendor_revisions"] == [event]
    assert collection_state(tmp_path, date(2024, 1, 5))["retained"] == {
        ("bar", "SPY", "2024-01-03"): event["retained"]
    }


def _gap_replay(signal, blocked=()):
    days = sessions(date(2024, 1, 2), date(2024, 1, 12))
    series = {"A": PriceSeries.from_bars("A", [(d, 100, 101, 99, 100, 100000) for d in days])}
    fn = without_entries_on(signal, entry_signal_days(blocked)) if blocked else signal
    return run_funded_replay(
        series, {"A": fn}, {"A": "A"}, limits=RiskLimits(), warmup=0, max_volume_participation=1
    )


def _long_on(*days):
    def signal(s, t):
        return EntrySignal(Direction.LONG, 95, 20, 120) if s.dates[t] in days else None

    return signal


def _buys(result):
    return [(f["day"], f["signal_day"]) for f in result.fills if f["side"] == "buy"]


def test_missed_session_admits_no_entry_from_a_stale_signal():
    # Last record Jan 3; Jan 4 and Jan 5 missed; next collection through Mon Jan 8.
    gap = (date(2024, 1, 4), date(2024, 1, 5))
    assert entry_signal_days(gap) == {date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5)}
    for signal_day, entry in (
        (date(2024, 1, 3), "2024-01-04"),  # recorded close, fill on the missed open
        (date(2024, 1, 4), "2024-01-05"),  # missed close, fill on the missed open
        (date(2024, 1, 5), "2024-01-08"),  # last missed close, fill on the resume open
    ):
        assert _buys(_gap_replay(_long_on(signal_day))) == [(entry, str(signal_day))]
        assert _gap_replay(_long_on(signal_day), gap).fills == []
    # The resume session's own close is a recorded forward decision: filled next open.
    resumed = _gap_replay(_long_on(date(2024, 1, 5), date(2024, 1, 8)), gap)
    assert _buys(resumed) == [("2024-01-09", "2024-01-08")]
    with pytest.raises(ValueError, match="not a market session"):
        entry_signal_days((date(2024, 1, 6),))


def test_single_missed_session_blocks_its_own_signal_at_the_next_open():
    missed = (date(2024, 1, 4),)  # collector missed Jan 4; next collection through Jan 5
    assert _gap_replay(_long_on(date(2024, 1, 4)), missed).fills == []


def test_non_long_signals_on_missed_sessions_keep_their_records():
    def signal(s, t):
        return EntrySignal(Direction.SHORT, 105, 20, 80) if s.dates[t] == date(2024, 1, 4) else None

    result = _gap_replay(signal, (date(2024, 1, 4),))
    assert [d["reason"] for d in result.decisions] == ["long_only"]


def test_entry_block_wraps_frozen_replay_signals_and_always_restores(monkeypatch):
    days = sessions(date(2024, 1, 2), date(2024, 1, 5))
    series = PriceSeries.from_bars("A", [(d, 100, 101, 99, 100, 1) for d in days])
    monkeypatch.setattr(action_replay, "signal_fn_for", lambda strategy, **kw: _long_on(*days))
    frozen = action_replay.signal_fn_for
    with pytest.raises(RuntimeError), entries_blocked(frozenset({date(2024, 1, 3)})):
        fn = action_replay.signal_fn_for(None, regime_by_date={})
        assert fn(series, 1) is None  # Jan 3 long dropped
        assert fn(series, 2) is not None
        raise RuntimeError
    assert action_replay.signal_fn_for is frozen


def test_record_rejects_a_fill_from_a_missed_session_signal(tmp_path):
    plan(tmp_path)
    record_collection(tmp_path, date(2024, 1, 3), report(date(2024, 1, 3)))
    monday, gap = date(2024, 1, 8), ["2024-01-04", "2024-01-05"]
    stale = report(monday, blocked=gap)
    stale["books"]["A"]["scenarios"]["base"]["result"]["fills"] = [
        {"day": "2024-01-08", "side": "buy", "symbol": "SPY", "signal_day": "2024-01-05"}
    ]
    with pytest.raises(ValueError, match="not blocked from entries"):
        record_collection(tmp_path, monday, stale)
    saved = record_collection(tmp_path, monday, report(monday, blocked=gap))
    assert saved["entry_blocked_signal_days"] == ["2024-01-03", "2024-01-04", "2024-01-05"]


def test_new_books_or_changed_costs_are_not_forward_evidence(tmp_path):
    plan(tmp_path)
    first = report(date(2024, 1, 3))
    first["books"]["A"]["scenarios"]["base"]["cost_model"] = {"slippage_bps": 0}
    record_collection(tmp_path, date(2024, 1, 3), first)
    day = date(2024, 1, 4)
    added = report(day)
    added["books"]["A"]["scenarios"]["base"]["cost_model"] = {"slippage_bps": 0}
    added["books"]["high52"] = added["books"]["A"]
    with pytest.raises(ValueError, match="book configuration changed"):
        record_collection(tmp_path, day, added)
    cheaper = report(day)
    cheaper["books"]["A"]["scenarios"]["base"]["cost_model"] = {"slippage_bps": -1}
    with pytest.raises(ValueError, match="book configuration changed"):
        record_collection(tmp_path, day, cheaper)
    limits = report(day) | {"risk_limits": {"per_trade_risk_pct": 9}}
    limits["books"]["A"]["scenarios"]["base"]["cost_model"] = {"slippage_bps": 0}
    with pytest.raises(ValueError, match="book configuration changed"):
        record_collection(tmp_path, day, limits)


def _amendable_plan(tmp_path, monkeypatch, previous):
    accepted = pf.code_digest(previous)
    monkeypatch.setattr(pf, "code_digest", lambda overrides=None: accepted)
    plan(tmp_path)
    monkeypatch.undo()


def _collector_sources():
    inputs = pf._digest_inputs()
    return {name: inputs[name].read_bytes() for name in pf.COLLECTOR_PROTOCOL_FILES}


def test_collector_amendment_requires_byte_identical_decision_code(tmp_path, monkeypatch):
    previous = _collector_sources() | {"scripts/funded_forward.py": b"# accepted collector\n"}
    _amendable_plan(tmp_path, monkeypatch, previous)
    with pytest.raises(ValueError, match="code changed"):
        validate_plan(tmp_path)
    with pytest.raises(ValueError, match="every accepted collector"):
        amend_collector(tmp_path, {"scripts/funded_forward.py": b"x"}, "fix")
    with pytest.raises(ValueError, match="every accepted collector"):
        amend_collector(tmp_path, previous | {"research/action_replay.py": b"x"}, "fix")
    amendment = amend_collector(
        tmp_path, previous, "Quarantine revisions", now=datetime(2026, 11, 8, tzinfo=UTC)
    )
    assert amendment["sequence"] == 1
    assert list(amendment["changed_files"]) == ["scripts/funded_forward.py"]
    diff = amendment["changed_files"]["scripts/funded_forward.py"]["unified_diff"]
    assert diff.startswith("--- accepted/scripts/funded_forward.py")
    assert "-# accepted collector" in diff
    assert validate_plan(tmp_path)["schema"] == "funded-forward-v1"  # plan itself unchanged
    with pytest.raises(ValueError, match="unchanged"):
        amend_collector(tmp_path, previous, "again")


def test_amendment_cannot_cover_code_outside_the_collector_files(tmp_path, monkeypatch):
    # Accepted code that differs outside the two collector files (e.g. an added strategy
    # such as high52, or a different replay/cost/risk module) is refused.
    monkeypatch.setattr(pf, "code_digest", lambda overrides=None: "accepted-other-strategies")
    plan(tmp_path)
    monkeypatch.undo()
    with pytest.raises(ValueError, match="outside the collector protocol"):
        amend_collector(tmp_path, _collector_sources(), "would add a strategy")


def test_replay_and_decision_code_is_not_an_amendable_file(tmp_path, monkeypatch):
    assert pf.COLLECTOR_PROTOCOL_FILES == (
        "research/prospective_funded.py",
        "scripts/funded_forward.py",
    )
    inputs = pf._digest_inputs()
    accepted = pf.code_digest({"research/action_replay.py": b"# different replay code\n"})
    monkeypatch.setattr(pf, "code_digest", lambda overrides=None: accepted)
    plan(tmp_path)
    monkeypatch.undo()
    assert "research/action_replay.py" in inputs
    with pytest.raises(ValueError, match="outside the collector protocol"):
        amend_collector(tmp_path, _collector_sources(), "would change replay decisions")


def test_broken_amendment_chain_halts(tmp_path, monkeypatch):
    previous = _collector_sources() | {"scripts/funded_forward.py": b"# accepted collector\n"}
    _amendable_plan(tmp_path, monkeypatch, previous)
    amend_collector(tmp_path, previous, "fix", now=datetime(2026, 11, 8, tzinfo=UTC))
    (tmp_path / "amendments" / "0002.json").write_text(
        '{"sequence": 2, "plan_sha256": "x", "from_code_digest": "y", "to_code_digest": "z"}'
    )
    with pytest.raises(ValueError, match="amendment chain is broken"):
        validate_plan(tmp_path)


def test_changed_strategy_rule_halts_but_checkout_provenance_does_not(tmp_path):
    plan(tmp_path)

    def with_spec(day, **spec):
        r = report(day)
        r["books"]["A"]["strategy_spec"] = {"exit_logic": "target 3 ATR", "git_sha": "a"} | spec
        return r

    record_collection(tmp_path, date(2024, 1, 3), with_spec(date(2024, 1, 3)))
    day = date(2024, 1, 4)
    with pytest.raises(ValueError, match="book configuration changed"):
        record_collection(tmp_path, day, with_spec(day, exit_logic="target 5 ATR"))
    assert record_collection(tmp_path, day, with_spec(day, git_sha="b"))["through"] == "2024-01-04"
