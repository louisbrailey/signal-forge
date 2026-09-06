"""User creation and authentication against the ``user`` table."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge.auth.passwords import hash_password, needs_rehash, verify_password
from signalforge.db.models import User
from signalforge.db.types import utcnow


class AuthError(RuntimeError):
    pass


class UserAlreadyExistsError(AuthError):
    pass


def user_count(session: Session) -> int:
    return int(session.scalar(select(func.count()).select_from(User)) or 0)


def has_any_user(session: Session) -> bool:
    return user_count(session) > 0


def create_initial_user(session: Session, username: str, password: str) -> User:
    """Create the single local user. Fails if one already exists."""
    if has_any_user(session):
        raise UserAlreadyExistsError("A user already exists; registration is closed.")
    username = username.strip().lower()
    if not username:
        raise AuthError("Username is required.")
    user = User(username=username, password_hash=hash_password(password))
    session.add(user)
    session.flush()
    return user


def authenticate(session: Session, username: str, password: str) -> User | None:
    """Return the user on success, ``None`` on any failure (no user enumeration)."""
    user = session.scalar(select(User).where(User.username == username.strip().lower()))
    if user is None or not user.is_active:
        return None
    if not verify_password(user.password_hash, password):
        return None
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.last_login_at = utcnow()
    session.flush()
    return user
