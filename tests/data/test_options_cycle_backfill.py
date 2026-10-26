"""Per-cycle options backfill against fixture chains — offline contract tests.

MockTransport stands in for api.massive.com. What these pin, in order of how
badly each would corrupt an evidence pipeline if it regressed:

* the strike band is centred on the CYCLE'S OWN point-in-time close, not on the
  most recent one;
* the listing call carries ``expired=true`` and ``as_of``, and the basis it
  achieved is recorded on the dataset;
* every per-contract fetch covers the CYCLE'S trade window, not the whole
  backfill window;
* anything the run cannot serve is excluded and counted BY REASON;
* the run is resumable at (underlying, cycle) granularity, and a retryable
  exclusion stays retryable while a deterministic one does not;
* the run's own provenance records the ceiling raise, the pacing used, and the
  discovered history depth.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge.data.adapters import massive_options as mo
from signalforge.data.adapters.massive_options import MassiveOptionsAdapter
from signalforge.data.calendar import sessions as _sessions
from signalforge.data.options_backfill import (
    CycleBackfillCaps,
    OptionsCoverageSummary,
    backfill_option_cycles,
    coverage_summary,
    reference_price,
)
from signalforge.data.options_cycles import (
    BASIS_NONE,
    BASIS_VENDOR_AS_OF,
    EXCL_CONTRACT_FETCH_FAILED,
    EXCL_LADDER_INCOMPLETE,
    EXCL_NO_BAR_ON_OR_BEFORE,
    EXCL_REFERENCE_OUTSIDE_LADDER,
    EXCL_STRIKE_NOT_LISTED_AS_OF_ENTRY,
    monthly_cycles,
)
from signalforge.db.models import Instrument, OHLCVDaily, OptionAggregateDaily
from signalforge.domain import LatencyCategory

# A short window so the fixtures stay small: three monthly cycles.
WINDOW_START = date(2024, 1, 2)
WINDOW_END = date(2024, 9, 30)
CYCLES = monthly_cycles(WINDOW_START, WINDOW_END, dte_entry_max=60)


@pytest.fixture(autouse=True)
def _no_real_sleeping(monkeypatch: pytest.MonkeyPatch) -> None:
    """The adapter now backs off before retrying a retryable status (D1 §7.6).
    That is right in production and ruinous in an offline suite: the fixtures
    below inject 503s deliberately, and a real backoff would charge ~22 s per
    failing contract for a rate limit that does not exist here.

    Patch ``_sleep`` itself, NOT ``time.sleep``. The backoff is a chunked wait
    driven by ``time.monotonic()``, so neutering ``time.sleep`` alone converts
    it into a busy-spin of exactly the same duration — slower, not faster."""
    monkeypatch.setattr(mo.MassiveOptionsAdapter, "_sleep", lambda self, _s: None)


def _occ(u: str, expiry: date, strike: float, cp: str) -> str:
    return f"O:{u}{expiry.strftime('%y%m%d')}{cp}{round(strike * 1000):08d}"


def _seed_equity(session: Session, symbol: str, *, level: float = 400.0, step: float = 0.0) -> None:
    """A clean daily close series so each cycle has its own reference price."""
    inst = Instrument(symbol=symbol, name=symbol, instrument_type="etf", exchange="ARCX")
    session.add(inst)
    session.flush()
    for i, d in enumerate(_sessions(WINDOW_START - timedelta(days=120), WINDOW_END)):
        px = level + step * i
        session.add(
            OHLCVDaily(
                instrument_id=inst.id,
                session_date=d,
                open=px,
                high=px,
                low=px,
                close=px,
                volume=1_000_000,
                source="massive",
                latency_category=LatencyCategory.HISTORICAL,
                ingested_at=datetime.now(UTC),
                is_simulated=False,
            )
        )
    session.flush()


_AGG_RE = re.compile(r"/v2/aggs/ticker/(?P<tk>[^/]+)/range/1/day/(?P<a>[\d-]+)/(?P<b>[\d-]+)")
_EXP_RE = re.compile(r"O:[A-Z]+(?P<yy>\d\d)(?P<mm>\d\d)(?P<dd>\d\d)[CP]")


def _expiry_of(tk: str) -> date:
    m = _EXP_RE.search(tk)
    assert m
    return date(2000 + int(m["yy"]), int(m["mm"]), int(m["dd"]))


def _make_client(
    *,
    ladder_lo: float = 340.0,
    ladder_hi: float = 460.0,
    step: float = 1.0,
    shares_per_contract: int = 100,
    truncate_ladder: bool = False,
    fail_aggs: bool = False,
    listing_urls: list[str] | None = None,
    agg_urls: list[str] | None = None,
) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/v3/reference/options/contracts" in url:
            if listing_urls is not None:
                listing_urls.append(url)
            u = re.search(r"underlying_ticker=([A-Z]+)", url)
            exp = re.search(r"expiration_date\.gte=([\d-]+)", url)
            assert u and exp
            expiry = date.fromisoformat(exp.group(1))
            rows = []
            k = ladder_lo
            while k <= ladder_hi + 1e-9:
                for cp, right in (("C", "call"), ("P", "put")):
                    rows.append(
                        {
                            "ticker": _occ(u.group(1), expiry, k, cp),
                            "contract_type": right,
                            "strike_price": round(k, 2),
                            "expiration_date": expiry.isoformat(),
                            "exercise_style": "american",
                            "shares_per_contract": shares_per_contract,
                        }
                    )
                k += step
            body: dict[str, object] = {"status": "OK", "results": rows}
            if truncate_ladder:
                # A vendor cursor that never runs out. It must carry the same
                # query as the first page, because that is what a real cursor
                # URL does — a bare "?cursor=more" would make page 2 a
                # differently-shaped request and test the fixture, not the cap.
                body["next_url"] = (
                    "https://api.massive.com/v3/reference/options/contracts"
                    f"?underlying_ticker={u.group(1)}"
                    f"&expiration_date.gte={exp.group(1)}"
                    f"&expiration_date.lte={exp.group(1)}&cursor=more"
                )
            return httpx.Response(200, json=body)
        m = _AGG_RE.search(url)
        if m:
            if agg_urls is not None:
                agg_urls.append(url)
            if fail_aggs:
                return httpx.Response(503, json={"status": "ERROR"})
            a, b = date.fromisoformat(m["a"]), date.fromisoformat(m["b"])
            out = []
            for d in _sessions(a, min(b, _expiry_of(m["tk"]))):
                ts = int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() * 1000)
                out.append(
                    {"t": ts, "o": 1.0, "h": 1.5, "l": 0.8, "c": 1.2, "v": 10, "vw": 1.1, "n": 3}
                )
            return httpx.Response(200, json={"status": "OK", "results": out})
        return httpx.Response(404, json={})

    return httpx.Client(transport=httpx.MockTransport(handler))


def _adapter(**kw: object) -> MassiveOptionsAdapter:
    return MassiveOptionsAdapter("k", client=_make_client(**kw))  # type: ignore[arg-type]


def _caps(**kw: object) -> CycleBackfillCaps:
    base = {
        "window_start": WINDOW_START,
        "window_end": WINDOW_END,
        "max_total_bars": 1_000_000,
    }
    base.update(kw)
    return CycleBackfillCaps(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
def test_the_band_is_centred_on_each_cycles_own_point_in_time_close(session: Session) -> None:
    """A trending underlying: the 2024-02 cycle must be centred on a February
    close, not on September's. The shipped path used one value for the run."""
    _seed_equity(session, "SPY", level=300.0, step=1.0)
    run = backfill_option_cycles(
        session, _adapter(ladder_lo=200.0, ladder_hi=700.0), ["SPY"], caps=_caps()
    )
    refs = {
        k: v["reference_price"]
        for k, v in run.gaps_json["SPY"]["cycles"].items()
        if v.get("reference_price") is not None
    }
    assert len(refs) >= 3
    assert len(set(refs.values())) == len(refs)  # a distinct reference per cycle
    assert sorted(refs.values()) == [refs[k] for k in sorted(refs)]  # and it tracks the trend


def test_reference_price_is_point_in_time_source_pinned_and_staleness_bounded(
    session: Session,
) -> None:
    _seed_equity(session, "SPY", level=400.0, step=0.5)
    ref, why = reference_price(session, "SPY", date(2024, 3, 15))
    assert why is None and ref is not None
    assert ref.priced_on <= date(2024, 3, 15)
    assert ref.source == "massive"

    # a date long after the series ends is refused, never silently carried
    stale, why = reference_price(session, "SPY", WINDOW_END + timedelta(days=90))
    assert stale is None and why == "reference_stale"

    missing, why = reference_price(session, "NOPE", date(2024, 3, 15))
    assert missing is None and why == "no_instrument"

    early, why = reference_price(session, "SPY", date(2019, 1, 2))
    assert early is None and why == "no_bar_on_or_before"


def test_the_listing_call_is_point_in_time_and_per_expiry(session: Session) -> None:
    _seed_equity(session, "SPY")
    urls: list[str] = []
    adapter = MassiveOptionsAdapter("k", client=_make_client(listing_urls=urls))
    run = backfill_option_cycles(session, adapter, ["SPY"], caps=_caps())
    assert urls
    for u in urls:
        # Measured 2026-09-12 (D1 Appendix P, P6): ``expired=true`` is judged relative
        # to ``as_of``, so sending both returns ZERO rows for every cycle. A point-in-time
        # listing carries ``as_of`` alone; ``expired=true`` belongs to end-of-life listings.
        assert "as_of=" in u  # otherwise the ladder is an END-OF-LIFE ladder
        assert "expired=" not in u
        gte = re.search(r"expiration_date\.gte=([\d-]+)", u).group(1)  # type: ignore[union-attr]
        lte = re.search(r"expiration_date\.lte=([\d-]+)", u).group(1)  # type: ignore[union-attr]
        assert gte == lte  # one expiry per call: the ladder is per-cycle
        assert "strike_price." not in u  # UNFILTERED: the bracket check needs the true ladder
    assert run.gaps_json["__run__"]["strike_listing_basis"] == BASIS_VENDOR_AS_OF


def test_without_a_point_in_time_instrument_the_ladder_may_not_select_at_all(
    session: Session,
) -> None:
    """Selecting from an end-of-life ladder favours short strikes in the
    direction the market actually went. That is a lookahead in the selection
    rule, so the correct outcome is no selection — not a caveat."""
    _seed_equity(session, "SPY")
    run = backfill_option_cycles(
        session, _adapter(), ["SPY"], caps=_caps(listing_as_of_enabled=False)
    )
    assert run.gaps_json["__run__"]["strike_listing_basis"] == BASIS_NONE
    reasons = run.gaps_json["SPY"]["cycles_excluded"]
    assert reasons.get(EXCL_STRIKE_NOT_LISTED_AS_OF_ENTRY) == len(CYCLES)
    assert session.scalar(select(func.count()).select_from(OptionAggregateDaily)) == 0


def test_each_contract_is_fetched_over_its_cycle_window_not_the_whole_window(
    session: Session,
) -> None:
    _seed_equity(session, "SPY")
    urls: list[str] = []
    adapter = MassiveOptionsAdapter("k", client=_make_client(agg_urls=urls))
    backfill_option_cycles(session, adapter, ["SPY"], caps=_caps())
    assert urls
    whole_window = len(_sessions(WINDOW_START, WINDOW_END))
    for u in urls:
        m = _AGG_RE.search(u)
        assert m
        span = len(_sessions(date.fromisoformat(m["a"]), date.fromisoformat(m["b"])))
        assert span <= 55  # DTE-60 plus a 5-session buffer, never the ~190-session window
        assert span < whole_window


def test_a_full_ladder_selects_seventeen_rungs_per_right(session: Session) -> None:
    _seed_equity(session, "SPY")
    run = backfill_option_cycles(session, _adapter(), ["SPY"], caps=_caps())
    for cyc in run.gaps_json["SPY"]["cycles"].values():
        assert cyc["excluded"] is None
        assert cyc["selected_calls"] == 17
        assert cyc["selected_puts"] == 17
        assert cyc["rungs_per_side"][0] >= 7 and cyc["rungs_per_side"][1] >= 7
    assert run.gaps_json["SPY"]["cycles_covered"] == len(CYCLES)


def test_a_reference_outside_the_vendor_ladder_excludes_the_cycle(session: Session) -> None:
    """The mechanical enforcement of the split hazard: a back-adjusted close
    against unadjusted strikes fails the bracket test by orders of magnitude."""
    _seed_equity(session, "SPY", level=40.0)  # post-split adjusted close
    run = backfill_option_cycles(
        session, _adapter(ladder_lo=340.0, ladder_hi=460.0), ["SPY"], caps=_caps()
    )
    reasons = run.gaps_json["SPY"]["cycles_excluded"]
    assert reasons.get(EXCL_REFERENCE_OUTSIDE_LADDER) == len(CYCLES)
    assert session.scalar(select(func.count()).select_from(OptionAggregateDaily)) == 0


def test_a_truncated_ladder_excludes_the_cycle_rather_than_shortening_it(
    session: Session,
) -> None:
    _seed_equity(session, "SPY")
    run = backfill_option_cycles(session, _adapter(truncate_ladder=True), ["SPY"], caps=_caps())
    reasons = run.gaps_json["SPY"]["cycles_excluded"]
    assert reasons.get(EXCL_LADDER_INCOMPLETE) == len(CYCLES)


def test_a_non_100_deliverable_is_refused_and_counted(session: Session) -> None:
    """Gate 0.h, mechanically: a non-100 deliverable is the machine-readable
    signature of an OCC adjustment and every 'x 100' downstream would be wrong."""
    _seed_equity(session, "SPY")
    run = backfill_option_cycles(session, _adapter(shares_per_contract=10), ["SPY"], caps=_caps())
    cycles = run.gaps_json["SPY"]["cycles"].values()
    assert all(c["shares_per_contract_refusals"] > 0 for c in cycles)
    assert all(c["excluded"] == "shares_per_contract_not_100" for c in cycles)
    assert session.scalar(select(func.count()).select_from(OptionAggregateDaily)) == 0


def test_the_global_bar_ceiling_is_a_hard_stop_and_leaves_the_run_retryable(
    session: Session,
) -> None:
    _seed_equity(session, "SPY")
    run = backfill_option_cycles(session, _adapter(), ["SPY"], caps=_caps(max_total_bars=60))
    assert (session.scalar(select(func.count()).select_from(OptionAggregateDaily)) or 0) <= 60
    assert "SPY" not in (run.symbols_ok or [])  # budget-starved, never "done"
    assert "SPY" in (run.symbols_failed or {})


def test_resume_skips_covered_cycles_and_retries_only_the_retryable_ones(
    session: Session,
) -> None:
    _seed_equity(session, "SPY")
    failing = MassiveOptionsAdapter("k", client=_make_client(fail_aggs=True))
    run1 = backfill_option_cycles(session, failing, ["SPY"], caps=_caps())
    assert run1.bars_written == 0
    assert all(
        c["excluded"] == EXCL_CONTRACT_FETCH_FAILED
        for c in run1.gaps_json["SPY"]["cycles"].values()
    )
    assert "SPY" not in (run1.symbols_ok or [])

    urls: list[str] = []
    good = MassiveOptionsAdapter("k", client=_make_client(agg_urls=urls))
    run2 = backfill_option_cycles(session, good, ["SPY"], caps=_caps(), resume_run_id=run1.id)
    assert run2.id == run1.id
    assert run2.bars_written > 0
    assert run2.symbols_ok == ["SPY"]
    assert run2.gaps_json["SPY"]["cycles_covered"] == len(CYCLES)

    # a third pass re-fetches nothing: every cycle is already recorded
    before = session.scalar(select(func.count()).select_from(OptionAggregateDaily))
    urls2: list[str] = []
    run3 = backfill_option_cycles(
        session,
        MassiveOptionsAdapter("k", client=_make_client(agg_urls=urls2)),
        ["SPY"],
        caps=_caps(),
        resume_run_id=run2.id,
    )
    assert urls2 == []
    assert run3.bars_written == run2.bars_written
    assert session.scalar(select(func.count()).select_from(OptionAggregateDaily)) == before


def test_a_deterministic_exclusion_is_not_re_attempted_on_resume(session: Session) -> None:
    _seed_equity(session, "SPY", level=40.0)  # every cycle fails the bracket check
    run1 = backfill_option_cycles(session, _adapter(), ["SPY"], caps=_caps())
    assert run1.symbols_ok == ["SPY"]  # nothing a resume could fix
    listing: list[str] = []
    backfill_option_cycles(
        session,
        MassiveOptionsAdapter("k", client=_make_client(listing_urls=listing)),
        ["SPY"],
        caps=_caps(),
        resume_run_id=run1.id,
    )
    assert listing == []  # the underlying was done; no request was re-issued


def test_the_run_records_its_own_parameters_and_the_ceiling_raise(session: Session) -> None:
    _seed_equity(session, "SPY")
    adapter = MassiveOptionsAdapter("k", client=_make_client(), min_request_spacing_s=7.5)
    run = backfill_option_cycles(
        session, adapter, ["SPY"], caps=_caps(), options_config_hash="abc123"
    )
    prov = run.gaps_json["__run__"]
    assert prov["max_total_bars"] == 1_000_000
    assert prov["max_total_bars_prior"] == 200_000
    assert "decision 6" in prov["max_total_bars_raise_decision"]
    assert prov["pacing_s"] == 7.5  # the pacing ACTUALLY used, not a literal
    assert prov["ladder_id"] == "LADDER_17"
    assert prov["cycle_rule"] == "monthly_third_friday"
    assert prov["cycle_expiry_adjustment"] == "holiday_preceding_session"
    assert prov["options_config_hash"] == "abc123"
    assert prov["require_shares_per_contract"] == 100
    assert run.kind == "options_cycle_backfill"
    assert len(run.kind) > 16  # the column was widened; this used to overflow silently


def test_the_run_records_the_discovered_history_depth(session: Session) -> None:
    _seed_equity(session, "SPY")
    run = backfill_option_cycles(session, _adapter(), ["SPY"], caps=_caps())
    assert run.earliest_available_date is not None
    assert run.earliest_probe_at is not None
    assert run.earliest_available_date >= WINDOW_START


def test_every_stored_bar_is_historical_and_inside_the_cycle(session: Session) -> None:
    _seed_equity(session, "SPY")
    backfill_option_cycles(session, _adapter(), ["SPY"], caps=_caps())
    rows = list(session.scalars(select(OptionAggregateDaily)))
    assert rows
    assert all(r.latency_category is LatencyCategory.HISTORICAL for r in rows)
    assert all(r.session_date <= _expiry_of(r.option_ticker) for r in rows)
    assert all(WINDOW_START <= r.session_date <= WINDOW_END for r in rows)


def test_a_cycle_with_no_equity_bar_is_excluded_by_name(session: Session) -> None:
    run = backfill_option_cycles(session, _adapter(), ["SPY"], caps=_caps())
    reasons = run.gaps_json["SPY"]["cycles_excluded"]
    assert reasons.get("no_instrument") == len(CYCLES)
    assert EXCL_NO_BAR_ON_OR_BEFORE not in reasons


def test_a_ladder_larger_than_the_runaway_guard_fails_loudly(session: Session) -> None:
    """The ladder decides coverage, never the cap — a guard that would truncate
    a cycle raises instead of silently keeping an arbitrary slice."""
    _seed_equity(session, "SPY")
    with pytest.raises(ValueError, match="max_contracts_per_cycle"):
        backfill_option_cycles(session, _adapter(), ["SPY"], caps=_caps(max_contracts_per_cycle=10))


# --- the COVERAGE-SUMMARY-ONLY rule ---------------------------------------- #
def test_the_coverage_summary_cannot_hold_a_price_by_construction() -> None:
    OptionsCoverageSummary.assert_price_free()


def test_the_coverage_summary_reports_counts_and_completeness_only(session: Session) -> None:
    _seed_equity(session, "SPY")
    run = backfill_option_cycles(session, _adapter(), ["SPY"], caps=_caps())
    cov = coverage_summary(run)

    assert cov.cycles_total == len(CYCLES)
    assert cov.cycles_covered == len(CYCLES)
    assert cov.contracts_selected == 34 * len(CYCLES)
    assert cov.bars_written > 0
    assert 0.0 < cov.bar_continuity_fraction <= 1.0
    assert cov.cycles_bracket_fraction == 1.0
    assert cov.strike_listing_basis == BASIS_VENDOR_AS_OF
    assert cov.max_total_bars_prior == 200_000

    # Every value it exposes is a count, a fraction, a date, a bool or an
    # identity string. Nothing here can be a price, an IV, a greek or a return.
    import dataclasses

    for f in dataclasses.fields(cov):
        v = getattr(cov, f.name)
        assert isinstance(v, int | float | str | date | tuple | type(None)), f.name


def test_the_summary_is_derived_from_provenance_and_never_reads_a_bar(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Enforcement, not policy: with the bar table made unreadable the summary
    still renders, which proves it never consults one."""
    _seed_equity(session, "SPY")
    run = backfill_option_cycles(session, _adapter(), ["SPY"], caps=_caps())
    session.expunge_all()

    def _boom(*a: object, **k: object) -> None:
        raise AssertionError("the coverage summary must never query a price table")

    monkeypatch.setattr(Session, "execute", _boom)
    monkeypatch.setattr(Session, "scalars", _boom)
    cov = coverage_summary(run)
    assert cov.cycles_total == len(CYCLES)
