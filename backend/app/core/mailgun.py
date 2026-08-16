"""Mailgun email sending, currently just the registration OTP."""

import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_MAILGUN_API_BASE = "https://api.mailgun.net/v3"


async def send_otp_email(to_email: str, code: str) -> None:
    """Send the OTP code to `to_email`.

    Missing credentials or a Mailgun-side failure are logged, not raised -
    registration must not 500 because outbound email is unavailable.
    """
    settings = get_settings()
    if not settings.mailgun_api_key or not settings.mailgun_domain:
        logger.warning("Mailgun not configured; skipping OTP email to %s", to_email)
        return

    url = f"{_MAILGUN_API_BASE}/{settings.mailgun_domain}/messages"
    data = {
        "from": f"DriveSense <no-reply@{settings.mailgun_domain}>",
        "to": to_email,
        "subject": "Your DriveSense verification code",
        "text": f"Your verification code is {code}. It expires in 10 minutes.",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as http_client:
            response = await http_client.post(
                url, auth=("api", settings.mailgun_api_key), data=data
            )
            response.raise_for_status()
    except httpx.HTTPError:
        logger.exception("Failed to send OTP email to %s", to_email)
