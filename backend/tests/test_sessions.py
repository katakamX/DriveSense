from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.sessions import create_session, delete_session, get_user_for_token
from app.db.models import Session, User


async def _make_user(db: AsyncSession, email: str = "staff@example.com") -> User:
    user = User(email=email, password_hash="irrelevant-for-this-test")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def test_create_session_resolves_to_user(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)

    token = await create_session(db_session, user)
    resolved = await get_user_for_token(db_session, token)

    assert resolved is not None
    assert resolved.id == user.id


async def test_get_user_for_token_rejects_unknown_token(db_session: AsyncSession) -> None:
    resolved = await get_user_for_token(db_session, "not-a-real-token")
    assert resolved is None


async def test_get_user_for_token_rejects_expired_session(db_session: AsyncSession) -> None:
    user = await _make_user(db_session, email="expired@example.com")
    token = await create_session(db_session, user)

    result = await db_session.execute(select(Session).where(Session.user_id == user.id))
    row = result.scalar_one()
    row.expires_at = datetime.now(UTC) - timedelta(hours=1)
    await db_session.commit()

    resolved = await get_user_for_token(db_session, token)
    assert resolved is None


async def test_delete_session_revokes_token(db_session: AsyncSession) -> None:
    user = await _make_user(db_session, email="logout@example.com")
    token = await create_session(db_session, user)

    await delete_session(db_session, token)
    resolved = await get_user_for_token(db_session, token)

    assert resolved is None
