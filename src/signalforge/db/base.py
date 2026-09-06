"""Declarative base + common mixins.

A stable naming convention is set so Alembic autogenerate produces deterministic
constraint names across SQLite (Phase 1) and PostgreSQL (Phase 2).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from signalforge.db.types import UTCDateTime, utcnow

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class IntPK:
    id: Mapped[int] = mapped_column(primary_key=True)


class CreatedAt:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class TimestampedMixin(CreatedAt):
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
