"""Chart data for the UI — read-only, always from what is stored right now.

Every payload carries ``as_of`` (the newest bar or event it contains),
``latency`` (the honest S7 label: END_OF_DAY for daily bars, never "live"),
``stale`` (as-of older than the market's expected freshness) and
``generated_at``. The browser re-polls these endpoints, so a chart is always
current with the database; it is never more current than the provider feed.
Nothing here writes, places, or decides anything.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import (
    Candidate,
    CryptoBarDaily,
    CryptoPaperBook,
    CryptoPaperTrade,
    FxBarDaily,
    GridTradeRow,
    Instrument,
    OHLCVDaily,
    PaperAccount,
    PaperPosition,
)

MAX_DAYS = 3650
# A daily feed is stale when its newest bar is older than this many calendar
# days (covers weekends and one missed publication; matches context staleness).
_STALE_DAYS = {"stocks": 4, "fx": 4, "crypto": 2}


def _now() -> datetime:
    return datetime.now(UTC)


def _envelope(
    *,
    kind: str,
    title: str,
    series: list[dict[str, Any]],
    as_of: date | None,
    latency: str,
    market: str | None = None,
    unit: str = "",
    note: str = "",
) -> dict[str, Any]:
    stale = None
    if market and as_of is not None:
        stale = (_now().date() - as_of).days > _STALE_DAYS[market]
    return {
        "kind": kind,
        "title": title,
        "unit": unit,
        "series": series,
        "as_of": as_of.isoformat() if as_of else None,
        "latency": latency,
        "stale": stale,
        "empty": not any(s["data"] for s in series),
        "note": note,
        "generated_at": _now().isoformat(timespec="seconds"),
    }


def _cut(days: int) -> date:
    return _now().date() - timedelta(days=max(1, min(days, MAX_DAYS)))


def _ohlc(rows: list[tuple[date, float, float, float, float]]) -> list[dict[str, Any]]:
    return [
        {"time": d.isoformat(), "open": o, "high": h, "low": lo, "close": c}
        for d, o, h, lo, c in rows
    ]


def equity_bars(session: Session, symbol: str, days: int = 365) -> dict[str, Any]:
    sym = symbol.upper()
    inst = session.scalar(select(Instrument).where(Instrument.symbol == sym))
    rows: list[tuple[date, float, float, float, float]] = []
    if inst is not None:
        rows = [
            (r[0], r[1], r[2], r[3], r[4])
            for r in session.execute(
                select(
                    OHLCVDaily.session_date,
                    OHLCVDaily.open,
                    OHLCVDaily.high,
                    OHLCVDaily.low,
                    OHLCVDaily.close,
                )
                .where(
                    OHLCVDaily.instrument_id == inst.id,
                    OHLCVDaily.source == "massive",
                    OHLCVDaily.session_date >= _cut(days),
                )
                .order_by(OHLCVDaily.session_date)
            )
        ]
    return _envelope(
        kind="candles",
        title=f"{sym} daily",
        series=[{"name": sym, "type": "candles", "data": _ohlc(rows)}],
        as_of=rows[-1][0] if rows else None,
        latency="END_OF_DAY",
        market="stocks",
        unit="USD",
        note="" if inst else f"{sym} is not in the local store",
    )


def _pair_bars(
    session: Session,
    model: type[FxBarDaily] | type[CryptoBarDaily],
    source: str,
    pair: str,
    days: int,
    market: str,
) -> dict[str, Any]:
    p = pair.upper().replace("/", "").replace("-", "")
    rows: list[tuple[date, float, float, float, float]] = [
        (r[0], r[1], r[2], r[3], r[4])
        for r in session.execute(
            select(model.session_date, model.open, model.high, model.low, model.close)
            .where(model.pair == p, model.source == source, model.session_date >= _cut(days))
            .order_by(model.session_date)
        )
    ]
    return _envelope(
        kind="candles",
        title=f"{p} daily (UTC)",
        series=[{"name": p, "type": "candles", "data": _ohlc(rows)}],
        as_of=rows[-1][0] if rows else None,
        latency="END_OF_DAY",
        market=market,
        note="" if rows else f"no stored bars for {p}",
    )


def fx_bars(session: Session, pair: str, days: int = 365) -> dict[str, Any]:
    return _pair_bars(session, FxBarDaily, "massive_fx", pair, days, "fx")


def crypto_bars(session: Session, pair: str, days: int = 365) -> dict[str, Any]:
    return _pair_bars(session, CryptoBarDaily, "massive_crypto", pair, days, "crypto")


def pair_snapshot(session: Session, market: str, pairs: list[str]) -> list[dict[str, Any]]:
    """Last close, 1-day and 30-day change and a 60-bar sparkline per pair."""
    model: type[FxBarDaily] | type[CryptoBarDaily]
    model, source = (
        (FxBarDaily, "massive_fx") if market == "fx" else (CryptoBarDaily, "massive_crypto")
    )
    out: list[dict[str, Any]] = []
    for p in pairs:
        rows = list(
            session.execute(
                select(model.session_date, model.close)
                .where(model.pair == p, model.source == source)
                .order_by(model.session_date.desc())
                .limit(60)
            )
        )[::-1]
        if not rows:
            out.append({"pair": p, "close": None})
            continue
        last_d, last_c = rows[-1]
        prev = rows[-2][1] if len(rows) > 1 else None
        month_cutoff = last_d - timedelta(days=30)
        month = next((c for d, c in reversed(rows) if d <= month_cutoff), None)
        out.append(
            {
                "pair": p,
                "close": last_c,
                "as_of": last_d.isoformat(),
                "chg_1d": (last_c / prev - 1) * 100 if prev else None,
                "chg_30d": (last_c / month - 1) * 100 if month else None,
                "stale": (_now().date() - last_d).days > _STALE_DAYS[market],
                "spark": [c for _, c in rows],
            }
        )
    return out


def paper_equity(session: Session) -> dict[str, Any]:
    """Realized equity per equity paper book: initial cash plus cumulative
    realized P&L at each close. Open positions are not marked here (their
    unrealized P&L is on the paper pages); the chart says so."""
    from signalforge.paper.books import equity_books

    series = []
    last: date | None = None
    for acct in equity_books(session):
        closes = list(
            session.execute(
                select(PaperPosition.closed_at, PaperPosition.realized_pnl)
                .where(
                    PaperPosition.account_id == acct.id,
                    PaperPosition.closed_at.is_not(None),
                )
                .order_by(PaperPosition.closed_at)
            )
        )
        start = float(acct.initial_cash or Decimal("0"))
        by_day: dict[date, float] = defaultdict(float)
        for closed_at, pnl in closes:
            by_day[closed_at.date()] += float(pnl or 0)
        eq = start
        pts = [{"time": acct.created_at.date().isoformat(), "value": round(start, 2)}]
        for d in sorted(by_day):
            eq += by_day[d]
            if d.isoformat() == pts[-1]["time"]:
                pts[-1]["value"] = round(eq, 2)
            else:
                pts.append({"time": d.isoformat(), "value": round(eq, 2)})
            last = max(last, d) if last else d
        if closes or acct.name in ("default",):
            series.append({"name": _book_label(acct), "type": "line", "data": pts})
    return _envelope(
        kind="lines",
        title="Paper books — realized equity",
        series=series,
        as_of=last,
        latency="END_OF_DAY",
        unit="USD",
        note="Realized P&L only; open positions are shown on the paper pages. SIMULATED.",
    )


def _book_label(acct: PaperAccount) -> str:
    return acct.name if acct.strategy_version_id is None else f"{acct.name}"


def crypto_paper_curve(session: Session, key: str) -> dict[str, Any]:
    book = session.scalar(select(CryptoPaperBook).where(CryptoPaperBook.strategy_key == key))
    pts: list[dict[str, Any]] = []
    open_pts: list[dict[str, Any]] = []
    as_of = None
    if book is not None:
        pts.append({"time": book.start_date.isoformat(), "value": 0.0})
        rows = list(
            session.scalars(
                select(CryptoPaperTrade)
                .where(CryptoPaperTrade.book_id == book.id)
                .order_by(CryptoPaperTrade.exit_date)
            )
        )
        total = 0.0
        for r in rows:
            if r.status == "CLOSED" and r.pnl_r is not None and r.exit_date is not None:
                total += r.pnl_r
                if r.exit_date.isoformat() == pts[-1]["time"]:
                    pts[-1]["value"] = round(total, 3)
                else:
                    pts.append({"time": r.exit_date.isoformat(), "value": round(total, 3)})
        marks = sum(r.mark_r or 0.0 for r in rows if r.status == "OPEN")
        as_of = book.last_bar_date
        if as_of is not None and as_of.isoformat() >= pts[-1]["time"]:
            if as_of.isoformat() != pts[-1]["time"]:
                pts.append({"time": as_of.isoformat(), "value": round(total, 3)})
            # Only one observation exists for open marks. Two points at the same
            # timestamp violate Lightweight Charts' strictly increasing contract.
            open_pts = [{"time": as_of.isoformat(), "value": round(total + marks, 3)}]
    return _envelope(
        kind="lines",
        title=f"{key} paper — cumulative R",
        series=[
            {"name": "Closed trades (R)", "type": "line", "data": pts},
            {"name": "Incl. open marks (R)", "type": "line", "data": open_pts},
        ],
        as_of=as_of,
        latency="END_OF_DAY",
        market="crypto",
        unit="R",
        note="" if book else "no paper book yet",
    )


def feed_ages(session: Session) -> list[dict[str, Any]]:
    from signalforge.data.feeds import feed_status_report

    rep = feed_status_report(session)
    return [
        {
            "provider": f["provider"],
            "feed": f["feed_type"],
            "latency": f["latency_category"],
            "age_hours": round(f["age_seconds"] / 3600, 1) if f["age_seconds"] else None,
            "stale": f["is_stale"],
            "last": f["last_success_at"],
        }
        for f in rep["feeds"]
    ]


def scanner_activity(session: Session, days: int = 180) -> dict[str, Any]:
    """Trade ideas produced per day, one bar series per horizon."""
    since = datetime.combine(_cut(days), datetime.min.time(), tzinfo=UTC)
    counts: dict[str, dict[date, int]] = defaultdict(lambda: defaultdict(int))
    last: date | None = None
    for created, horizon in session.execute(
        select(Candidate.created_at, Candidate.horizon).where(Candidate.created_at >= since)
    ):
        d = created.date()
        counts[str(getattr(horizon, "value", horizon))][d] += 1
        last = max(last, d) if last else d
    series = [
        {
            "name": h.replace("_", " "),
            "type": "bars",
            "data": [{"time": d.isoformat(), "value": n} for d, n in sorted(c.items())],
        }
        for h, c in sorted(counts.items())
    ]
    return _envelope(
        kind="bars",
        title="Trade ideas per day",
        series=series,
        as_of=last,
        latency="END_OF_DAY",
        unit="ideas",
        note="" if series else "no scans in this period",
    )


def grid_activity(session: Session, days: int = 365) -> dict[str, Any]:
    """Simulated grid fills per day: dollars bought and dollars sold."""
    buys: dict[date, float] = defaultdict(float)
    sells: dict[date, float] = defaultdict(float)
    last: date | None = None
    for d, side, usd in session.execute(
        select(GridTradeRow.session_date, GridTradeRow.side, GridTradeRow.usd).where(
            GridTradeRow.session_date >= _cut(days)
        )
    ):
        (buys if side == "buy" else sells)[d] += float(usd)
        last = max(last, d) if last else d
    return _envelope(
        kind="bars",
        title="Grid fills per day (simulated USD)",
        series=[
            {
                "name": "Bought",
                "type": "bars",
                "data": [
                    {"time": d.isoformat(), "value": round(v, 2)} for d, v in sorted(buys.items())
                ],
            },
            {
                "name": "Sold",
                "type": "bars",
                "data": [
                    {"time": d.isoformat(), "value": round(v, 2)} for d, v in sorted(sells.items())
                ],
            },
        ],
        as_of=last,
        latency="END_OF_DAY",
        unit="USD",
        note="SIMULATED grid book.",
    )
