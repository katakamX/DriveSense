"""FastAPI dependencies gating routes behind a logged-in `User`, and behind a role."""

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.sessions import get_user_for_token
from app.db.models import User, UserRole
from app.db.session import get_db

# Admin/creation endpoints (drivers, vehicles) are staff tooling, not
# something a plain "user" role gets by logging in. Employee is deliberately
# included ahead of M-Auth-4 actually onboarding employees as a distinct flow.
STAFF_ROLES = frozenset({UserRole.EMPLOYEE, UserRole.ADMIN})


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name)
    user = await get_user_for_token(db, token) if token else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return user


async def require_staff(user: User = Depends(get_current_user)) -> User:
    """Gate for admin/creation endpoints: logged in AND role is employee or admin."""
    if user.role not in STAFF_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Staff role required")
    return user
