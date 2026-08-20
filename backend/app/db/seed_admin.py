"""Seed a local/dev admin `User` so login doesn't require a manual DB promotion.

Run with `python -m app.db.seed_admin`. Idempotent — re-running updates the
existing row's password hash and role rather than erroring on a duplicate
email, so it's safe in a dev loop that runs it after every fresh
`alembic upgrade head`.
"""

import asyncio
import sys

from sqlalchemy import select

from app.config import get_settings
from app.core.security import hash_password
from app.db.models import User, UserRole
from app.db.session import SessionLocal, dispose_engine


async def seed_admin() -> None:
    settings = get_settings()
    async with SessionLocal() as db:
        result = await db.execute(select(User).where(User.email == settings.seed_admin_email))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(email=settings.seed_admin_email)
            db.add(user)
        user.password_hash = hash_password(settings.seed_admin_password)
        user.role = UserRole.ADMIN
        # No OTP round trip for a seeded account — there is no inbox to check.
        user.email_verified = True
        await db.commit()
    print(f"Seeded admin: {settings.seed_admin_email}")


async def main() -> None:
    try:
        await seed_admin()
    finally:
        await dispose_engine()


if __name__ == "__main__":
    # psycopg's async driver needs a selector loop; Windows defaults to
    # Proactor (see run.py for the same fix on the uvicorn entrypoint).
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
