"""Session creation/lookup/revocation backing the auth cookie.

DB-backed opaque tokens, not JWT: logout (or an admin revoking a user) is
one `DELETE`, with no denylist to maintain and no token that keeps working
after the row is gone.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession as DbSession

from app.config import get_settings
from app.db.models import Session, User

_TOKEN_BYTES = 32


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def create_session(db: DbSession, user: User) -> str:
    """Create a session row for `user` and return the raw cookie token."""
    settings = get_settings()
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    session = Session(
        user_id=user.id,
        token_hash=_hash_token(token),
        expires_at=datetime.now(UTC) + timedelta(hours=settings.session_ttl_hours),
    )
    db.add(session)
    await db.commit()
    return token


async def get_user_for_token(db: DbSession, token: str) -> User | None:
    """Resolve a raw cookie token to its `User`, or None if absent/expired."""
    stmt = select(Session).where(Session.token_hash == _hash_token(token))
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if session is None or session.expires_at < datetime.now(UTC):
        return None
    return await db.get(User, session.user_id)


async def delete_session(db: DbSession, token: str) -> None:
    await db.execute(delete(Session).where(Session.token_hash == _hash_token(token)))
    await db.commit()
