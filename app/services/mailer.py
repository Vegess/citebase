"""Transactional email through Resend's HTTP API. Off unless RESEND_API_KEY is set."""
import logging

import httpx

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger("app.services.mailer")


def enabled() -> bool:
    return bool(settings.resend_api_key)


def send(to: str, subject: str, text: str) -> bool:
    if not enabled():
        return False
    try:
        resp = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={"from": settings.mail_from, "to": [to], "subject": subject, "text": text},
            timeout=15,
        )
        resp.raise_for_status()
        return True
    except httpx.HTTPError as exc:
        logger.warning("email send failed", extra={"error": str(exc)[:200]})
        return False
