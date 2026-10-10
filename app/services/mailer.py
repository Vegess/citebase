"""Transactional email over HTTPS (Render's free plan blocks SMTP ports).

Providers, picked by which key is set:
- BREVO_API_KEY  — Brevo, free for 300 emails/day; the sender address in
  MAIL_FROM must be verified in Brevo (a single address is enough, no domain).
- RESEND_API_KEY — Resend; needs a verified domain to email anyone but you.
Without either, email is off: admins copy invite and reset links by hand.
"""
import logging
from email.utils import parseaddr

import httpx

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger("app.services.mailer")


def provider() -> str | None:
    if settings.brevo_api_key:
        return "brevo"
    if settings.resend_api_key:
        return "resend"
    return None


def enabled() -> bool:
    return provider() is not None


def send(to: str, subject: str, text: str) -> bool:
    which = provider()
    if which is None:
        return False
    name, address = parseaddr(settings.mail_from)
    try:
        if which == "brevo":
            resp = httpx.post(
                "https://api.brevo.com/v3/smtp/email",
                headers={"api-key": settings.brevo_api_key, "accept": "application/json"},
                json={"sender": {"name": name or "Citebase", "email": address}, "to": [{"email": to}],
                      "subject": subject, "textContent": text},
                timeout=15,
            )
        else:
            resp = httpx.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json={"from": settings.mail_from, "to": [to], "subject": subject, "text": text},
                timeout=15,
            )
        resp.raise_for_status()
        return True
    except httpx.HTTPError as exc:
        logger.warning("email send failed", extra={"provider": which, "error": str(exc)[:200]})
        return False
