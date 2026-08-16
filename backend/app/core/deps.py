"""FastAPI dependencies gating routes behind a logged-in `User`."""

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.sessions import get_user_for_token
from app.db.models import User
from app.db.session import get_db


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name)
    user = await get_user_for_token(db, token) if token else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return user
