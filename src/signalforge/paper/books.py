"""Equity paper BOOKS: one paper account per PAPER_APPROVED strategy version.

Operator decision 2026-10-03, paper simulation only. Before it there was one
equity account, so the first strategy version to take a symbol starved every
other version of forward evidence on that symbol. Now:

* the book of strategy version N is the ``paper_account`` row whose
  ``strategy_version_id`` is N (unique). It is created lazily and idempotently
  the first time a PAPER_APPROVED version needs it, named ``book-sv<N>``, with
  the same starting reference equity as the legacy ``default`` account's
  ``initial_cash``;
* existing rows are ATTRIBUTED, never moved: the migration keys the legacy
  ``default`` account to the single version all of its positions belong to
  (see revision ``e3b8c5d1f7a2``);
* a candidate whose version is not PAPER_APPROVED (manual acceptance of an
  experimental signal) never lands in an approved version's book: it goes to
  the unkeyed ``default`` account, or — when ``default`` has become a version's
  book — to the unkeyed ``manual`` account, created the same lazy way;
* "position already open", every risk cap and the auto-simulation daily cap are
  all evaluated PER BOOK, because each of them is evaluated per account.

This module imports no ledger code (contract S14: ``signalforge.agents`` reaches
``paper.portfolio``, which reaches this module, and must not reach
``paper.ledger``).
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from signalforge.db.models import AuditLog, Candidate, PaperAccount, Strategy, StrategyVersion
from signalforge.db.types import utcnow
from signalforge.domain import StrategyStatus
from signalforge.observability import get_logger

__all__ = [
    "LEGACY_ACCOUNT",
    "MANUAL_ACCOUNT",
    "book_for_candidate",
    "book_for_version",
    "book_label",
    "book_name",
    "equity_books",
]

_log = get_logger("paper.books")

#: The pre-2026-10-03 single equity account. Its ``initial_cash`` is the
#: reference equity every lazily created book starts with.
LEGACY_ACCOUNT = "default"
#: Unkeyed equity account for candidates of non-approved versions once
#: ``default`` has become a version's book.
MANUAL_ACCOUNT = "manual"


def book_name(strategy_version_id: int) -> str:
    return f"book-sv{strategy_version_id}"


def _by_name(session: Session, name: str) -> PaperAccount | None:
    return session.scalar(select(PaperAccount).where(PaperAccount.name == name))


def _legacy(session: Session) -> PaperAccount:
    legacy = _by_name(session, LEGACY_ACCOUNT)
    if legacy is None:
        raise ValueError(
            f"paper account {LEGACY_ACCOUNT!r} does not exist — run `signalforge seed`"
        )
    return legacy


def _create(session: Session, name: str, strategy_version_id: int | None) -> PaperAccount:
    """Insert one book; a concurrent creator losing the unique race re-reads."""
    cash = Decimal(_legacy(session).initial_cash)
    try:
        with session.begin_nested():
            acct = PaperAccount(
                name=name, initial_cash=cash, cash=cash, strategy_version_id=strategy_version_id
            )
            session.add(acct)
            session.flush()
            session.add(
                AuditLog(
                    ts=utcnow(),
                    actor="paper.books",
                    action="paper.book_created",
                    entity=f"paper_account:{acct.id}",
                    before_json={},
                    after_json={
                        "name": name,
                        "strategy_version_id": strategy_version_id,
                        "initial_cash": str(cash),
                        "simulated": True,
                    },
                )
            )
            session.flush()
    except IntegrityError:
        existing = _by_name(session, name)
        if existing is None or existing.strategy_version_id != strategy_version_id:
            raise
        return existing
    _log.info("paper.book_created", name=name, strategy_version_id=strategy_version_id)
    return acct


def book_for_version(
    session: Session, strategy_version_id: int, *, create: bool = True
) -> PaperAccount | None:
    """The book keyed to ``strategy_version_id``; created when missing and
    ``create`` is true. Idempotent."""
    acct = session.scalar(
        select(PaperAccount).where(PaperAccount.strategy_version_id == strategy_version_id)
    )
    if acct is not None or not create:
        return acct
    return _create(session, book_name(strategy_version_id), strategy_version_id)


def book_for_candidate(session: Session, cand: Candidate) -> PaperAccount:
    """The equity account a decision on ``cand`` is recorded in.

    An existing book of the candidate's version always wins (a version that
    was approved, traded, and later lost approval keeps its book). A new book
    is created only for a PAPER_APPROVED version.
    """
    existing = book_for_version(session, cand.strategy_version_id, create=False)
    if existing is not None:
        return existing
    legacy = _legacy(session)
    ver = session.get(StrategyVersion, cand.strategy_version_id)
    if ver is not None and ver.status is StrategyStatus.PAPER_APPROVED:
        return _create(session, book_name(ver.id), ver.id)
    if legacy.strategy_version_id is None:
        return legacy
    return _by_name(session, MANUAL_ACCOUNT) or _create(session, MANUAL_ACCOUNT, None)


def equity_books(session: Session) -> list[PaperAccount]:
    """Every equity paper account, in strategy-version-id order (unkeyed last,
    then by id): each version's book plus the unkeyed ``default`` / ``manual``
    accounts. The options and grid accounts are never included."""
    rows = session.scalars(
        select(PaperAccount).where(
            or_(
                PaperAccount.strategy_version_id.is_not(None),
                PaperAccount.name.in_((LEGACY_ACCOUNT, MANUAL_ACCOUNT)),
            )
        )
    ).all()
    return sorted(
        rows,
        key=lambda a: (a.strategy_version_id is None, a.strategy_version_id or 0, a.id),
    )


def book_label(session: Session, acct: PaperAccount) -> str:
    """Human label for dashboards: ``<strategy name> v<version>`` or the account name."""
    if acct.strategy_version_id is None:
        return f"{acct.name} (unattributed)"
    ver = session.get(StrategyVersion, acct.strategy_version_id)
    if ver is None:
        return f"{acct.name} (strategy version {acct.strategy_version_id})"
    strat = session.get(Strategy, ver.strategy_id)
    name = strat.name if strat is not None else "strategy"
    return f"{name} v{ver.version} (#{ver.id})"
