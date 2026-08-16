"""Registration, login, and logout for the staff/admin/employee `User`."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.deps import get_current_user
from app.core.otp import issue_otp
from app.core.otp import verify_otp as check_otp
from app.core.security import hash_password, verify_password
from app.core.sessions import create_session, delete_session
from app.db.models import User
from app.db.session import get_db
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    ResendOtpRequest,
    UserRead,
    VerifyOtpRequest,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        max_age=settings.session_ttl_hours * 3600,
        path="/",
    )


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest, response: Response, db: AsyncSession = Depends(get_db)
) -> User:
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "email already registered")

    user = User(email=payload.email, password_hash=hash_password(payload.password))
    db.add(user)
    await db.commit()
    await db.refresh(user)

    await issue_otp(db, user)

    token = await create_session(db, user)
    _set_session_cookie(response, token)
    return user


@router.post("/login", response_model=UserRead)
async def login(
    payload: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)
) -> User:
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    if user is None or user.password_hash is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid email or password")
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid email or password")

    token = await create_session(db, user)
    _set_session_cookie(response, token)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> None:
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name)
    response.delete_cookie(settings.session_cookie_name, path="/")
    if token:
        await delete_session(db, token)


@router.get("/me", response_model=UserRead)
async def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.post("/verify-otp", response_model=UserRead)
async def verify_otp_endpoint(
    payload: VerifyOtpRequest, db: AsyncSession = Depends(get_db)
) -> User:
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    if user is None or not check_otp(user, payload.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid or expired code")

    user.email_verified = True
    user.otp_code_hash = None
    user.otp_expires_at = None
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/resend-otp", status_code=status.HTTP_204_NO_CONTENT)
async def resend_otp(payload: ResendOtpRequest, db: AsyncSession = Depends(get_db)) -> None:
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    # Same response whether or not the email exists - resend must not leak
    # which emails are registered.
    if user is not None and not user.email_verified:
        await issue_otp(db, user)
