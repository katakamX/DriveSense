import asyncio
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db.models import User, UserRole
from app.db.session import engine, get_db
from app.main import create_app

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    connection = await engine.connect()
    transaction = await connection.begin()
    session_factory = async_sessionmaker(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    session = session_factory()

    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


@pytest.fixture
def storage_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point document storage (ADR 0009) at a temp dir for the duration of a test.

    Goes through the environment rather than patching the module, because
    `get_settings` is `lru_cache`d and read at call time by both the storage
    layer and the upload endpoints — clearing the cache on the way in and out
    is what keeps a test's root from leaking into the next one.
    """
    monkeypatch.setenv("DOCUMENT_STORAGE_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


@pytest.fixture
def client(db_session: AsyncSession) -> Iterator[TestClient]:
    app = create_app()

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


async def register_staff(
    client: TestClient, db_session: AsyncSession, email: str, role: UserRole = UserRole.ADMIN
) -> None:
    """Register through the real endpoint, then promote out-of-band.

    Self-serve registration always lands on `UserRole.USER` — there is no
    endpoint yet that hands out `employee`/`admin` (that's M-Auth-4's job) —
    so tests that need a staff session reach into the DB directly, the same
    session the app itself is using via `client`'s `get_db` override.
    """
    response = client.post(
        "/api/v1/auth/register", json={"email": email, "password": "correcthorsebattery"}
    )
    assert response.status_code == 201, response.text
    await db_session.execute(update(User).where(User.email == email).values(role=role))
    await db_session.commit()
