"""OTP generation and verification for registration email checks."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.mailgun import send_otp_email
from app.db.models import User

_OTP_TTL_MINUTES = 10
_OTP_DIGITS = 6


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _generate_code() -> str:
    return f"{secrets.randbelow(10**_OTP_DIGITS):0{_OTP_DIGITS}d}"


async def issue_otp(db: AsyncSession, user: User) -> None:
    """Generate a fresh OTP for `user`, store its hash, and email it."""
    code = _generate_code()
    user.otp_code_hash = _hash_code(code)
    user.otp_expires_at = datetime.now(UTC) + timedelta(minutes=_OTP_TTL_MINUTES)
    await db.commit()
    await send_otp_email(user.email, code)


def verify_otp(user: User, code: str) -> bool:
    """Check `code` against `user`'s pending OTP. Does not commit or clear it."""
    if user.otp_code_hash is None or user.otp_expires_at is None:
        return False
    if user.otp_expires_at < datetime.now(UTC):
        return False
    return secrets.compare_digest(user.otp_code_hash, _hash_code(code))
