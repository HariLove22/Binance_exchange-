"""Email sending — intentionally a no-op while disabled.

The verification flow is fully wired end-to-end, but `settings.email_enabled` is False, so
links are logged to the server console instead of being sent. Flip `email_enabled=True` and
fill in the SMTP settings to go live; the call sites don't change.
"""

import logging

from app.core.config import settings

logger = logging.getLogger("app.email")


def _verification_url(token: str) -> str:
    return f"{settings.frontend_url}/#/verify-email?token={token}"


def send_verification_email(to_email: str, token: str) -> None:
    url = _verification_url(token)
    if not settings.email_enabled:
        # Disabled: log the link so the flow is testable without an SMTP server.
        logger.info("[email disabled] verification link for %s -> %s", to_email, url)
        return

    # Real delivery goes here (smtplib or a provider SDK). Not implemented while disabled.
    raise NotImplementedError("SMTP delivery is not configured (email_enabled is False)")
